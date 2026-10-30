"""Element-registry tests — every rule pinned from both sides.

Why this file exists
--------------------

``elements.py`` is the piece that makes the pack a *pipeline* rather than a pile
of graphs: an Element is created once and tagged thereafter. That makes two
things load-bearing and easy to break silently:

* the **name rules** — case-insensitive lookup, the ``@`` sigil, the
  duplicate-in-one-category error, and the ambiguity error when one name lives in
  two categories. Get any of these wrong and a prompt resolves to the wrong
  asset, which is worse than not resolving at all;
* the **tag grammar** — ``@Mirror Dunes`` is multi-word, ``nathaniel@example.com``
  is an email address and must NOT yield a tag, and the greedy capture runs to
  the next ``@``, ``#`` or punctuation.

Every expected value here is hand-computed from the definition, never read back
from the code under test. Where a value is a closed form the arithmetic is
written out so it is visible. The constants are pinned as literal tuples and
dicts, so moving one breaks a test rather than quietly changing behaviour.

The honesty cases get their own tests: an unresolved ``@Name`` must be
**reported**, not raised, because a graph should be able to show the user what is
unresolved; and an Element with no palette or no bounding box must make
``character_record_from_element`` **raise**, never invent one.
"""

import json

import pytest

from cinematographer import elements
from cinematographer.character import (
    DEFAULT_EYE_RATIO,
    CharacterAppearance,
    evaluate_character_continuity,
)
from cinematographer.elements import (
    ELEMENT_CATEGORIES,
    ELEMENT_RULES,
    ELEMENT_RULE_WEIGHTS,
    ELEMENT_SIDECAR_SUFFIX,
    ELEMENT_TAG_PREFIX,
    Element,
    ElementAudit,
    ElementRegistry,
    ElementResolution,
    audit_element,
    audit_summary,
    character_record_from_element,
    element_summary,
    parse_element_tags,
    resolve_elements,
    sidecar_path,
)
from cinematographer.geometry import OVERALL_PASS_WEIGHT

# --------------------------------------------------------------------------
# Fixtures — built from the definitions, not from the engine
# --------------------------------------------------------------------------


def _tamsin() -> Element:
    """A complete character Element: palette and bbox both present."""
    return Element(
        name="Tamsin",
        category="character",
        asset_path="assets/tamsin.png",
        description="lead",
        seed=7,
        palette=((0.1, 0.2, 0.3), (0.9, 0.8, 0.7)),
        bbox=(-0.25, -0.9, 0.25, 0.1),
        created_utc="2026-10-29T20:00:00Z",
    )


def _dunes() -> Element:
    """A location clean plate: no palette, no bbox — and that is legal."""
    return Element(
        name="Mirror Dunes",
        category="location",
        asset_path="assets/dunes.png",
    )


def _helmet() -> Element:
    return Element(name="helmet", category="prop", asset_path="assets/helmet.png")


@pytest.fixture
def registry() -> ElementRegistry:
    return ElementRegistry([_tamsin(), _dunes(), _helmet()])


# --------------------------------------------------------------------------
# Constants — pinned as literals, so moving one breaks a test
# --------------------------------------------------------------------------


def test_categories_are_the_confirmed_taxonomy():
    """Higgsfield's own taxonomy is Characters / Locations / Props."""
    assert ELEMENT_CATEGORIES == ("character", "location", "prop")


def test_rules_are_pinned_in_order():
    assert ELEMENT_RULES == (
        "named",
        "categorised",
        "asset_present",
        "palette_present",
        "bbox_present",
        "described",
    )


def test_rule_weights_are_pinned():
    assert ELEMENT_RULE_WEIGHTS == {
        "named": 1.0,
        "categorised": 1.0,
        "asset_present": 1.0,
        "palette_present": 0.5,
        "bbox_present": 0.5,
        "described": 0.3,
    }


def test_gating_split_is_the_documented_one():
    """Three rules gate; palette, bbox and description are reported only."""
    gating = [r for r in ELEMENT_RULES if ELEMENT_RULE_WEIGHTS[r] >= OVERALL_PASS_WEIGHT]
    assert gating == ["named", "categorised", "asset_present"]


def test_overall_pass_weight_is_geometrys_object_not_a_copy():
    """A local ``OVERALL_PASS_WEIGHT = 0.8`` would satisfy an equality check."""
    assert elements.OVERALL_PASS_WEIGHT is OVERALL_PASS_WEIGHT
    assert OVERALL_PASS_WEIGHT == 0.8


def test_gates_boundary_is_inclusive():
    """``_gates(0.8)`` is True; ``_gates(0.799)`` is False.

    No rule sits at exactly 0.8, so this predicate is the only place the
    inclusive comparison can be pinned.
    """
    assert elements._gates(OVERALL_PASS_WEIGHT) is True
    assert elements._gates(OVERALL_PASS_WEIGHT + 0.001) is True
    assert elements._gates(OVERALL_PASS_WEIGHT - 0.001) is False
    assert elements._gates(0.0) is False


def test_tag_prefix_and_character_sets_are_pinned():
    assert ELEMENT_TAG_PREFIX == "@"
    assert elements._NAME_EXTRA_CHARS == " _'-"
    assert elements._SENTENCE_PUNCTUATION == ",.;:!?"
    assert elements._TAG_BLOCKING_PREVIOUS_CHARS == "@_"


def test_sidecar_suffix_and_path():
    assert ELEMENT_SIDECAR_SUFFIX == ".element.json"
    assert sidecar_path("out/tamsin.png") == "out/tamsin.element.json"
    assert sidecar_path("tamsin") == "tamsin.element.json"
    assert sidecar_path("a/b/c/dunes.jpeg") == "a/b/c/dunes.element.json"


# --------------------------------------------------------------------------
# Element — category validation, every path
# --------------------------------------------------------------------------


@pytest.mark.parametrize("category", ["character", "location", "prop"])
def test_element_accepts_every_legal_category(category):
    element = Element(name="X", category=category, asset_path="x.png")
    assert element.category == category


@pytest.mark.parametrize("category", ["Character", "CHARACTER", "set", "props", ""])
def test_element_rejects_unknown_category(category):
    """The error names the bad value AND the legal set."""
    with pytest.raises(ValueError) as excinfo:
        Element(name="X", category=category, asset_path="x.png")
    message = str(excinfo.value)
    assert repr(category) in message
    assert "('character', 'location', 'prop')" in message


def test_element_rejects_empty_name():
    with pytest.raises(ValueError) as excinfo:
        Element(name="   ", category="character", asset_path="x.png")
    assert str(excinfo.value) == "Element name must be a non-empty string"


def test_element_strips_surrounding_whitespace_from_name():
    element = Element(name="  Tamsin  ", category="character", asset_path="x.png")
    assert element.name == "Tamsin"


@pytest.mark.parametrize("colour", [(0.1, 0.2), (0.1, 0.2, 0.3, 0.4), (0.5,)])
def test_element_rejects_wrong_palette_channel_count(colour):
    with pytest.raises(ValueError, match="3 channels"):
        Element(
            name="X", category="character", asset_path="x.png", palette=(colour,)
        )


@pytest.mark.parametrize("channel", [0.0, 1.0, 0.5])
def test_palette_channel_bounds_are_inclusive(channel):
    element = Element(
        name="X",
        category="character",
        asset_path="x.png",
        palette=((channel, channel, channel),),
    )
    assert element.palette == ((channel, channel, channel),)


@pytest.mark.parametrize("channel", [-0.001, 1.001, -1.0, 2.0])
def test_element_rejects_out_of_range_palette_channel(channel):
    with pytest.raises(ValueError, match="outside 0..1"):
        Element(
            name="X",
            category="character",
            asset_path="x.png",
            palette=((channel, 0.5, 0.5),),
        )


@pytest.mark.parametrize("bbox", [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0, 0.0)])
def test_element_rejects_wrong_bbox_length(bbox):
    with pytest.raises(ValueError, match="4 NDC values"):
        Element(name="X", category="character", asset_path="x.png", bbox=bbox)


@pytest.mark.parametrize(
    "bbox",
    [
        (-0.5, 0.0, -0.6, 1.0),  # x inverted only
        (0.0, 0.5, 1.0, 0.4),  # y inverted only
        (0.5, 0.5, -0.5, -0.5),  # both inverted
        (0.5, 0.0, 0.0, 0.5),  # x inverted, y ascending
        (0.5, 0.0, 0.4, 0.6),  # x inverted, y ascending, max_x < max_y
    ],
)
def test_element_rejects_inverted_bbox(bbox):
    with pytest.raises(ValueError, match="inverted"):
        Element(name="X", category="character", asset_path="x.png", bbox=bbox)


def test_element_accepts_a_degenerate_bbox():
    """min == max is a degenerate box, not an inverted one.

    ``character.py`` reports a zero-height box as an unmeasurable *failure*; it
    must not be rejected at construction, or that failure could never be
    reported.
    """
    element = Element(
        name="X", category="character", asset_path="x.png", bbox=(0.0, 0.0, 0.0, 0.0)
    )
    assert element.bbox == (0.0, 0.0, 0.0, 0.0)


def test_element_accepts_empty_palette_and_no_bbox():
    element = Element(name="X", category="location", asset_path="x.png")
    assert element.palette == ()
    assert element.bbox is None


def test_element_defaults_on_direct_construction():
    """The dataclass defaults, not ``from_dict``'s fallbacks."""
    element = Element(name="X", category="prop", asset_path="x.png")
    assert element.description == ""
    assert element.seed == 0
    assert element.created_utc == ""


def test_element_round_trips_through_dict():
    element = _tamsin()
    assert element.to_dict() == {
        "name": "Tamsin",
        "category": "character",
        "asset_path": "assets/tamsin.png",
        "description": "lead",
        "seed": 7,
        "palette": [[0.1, 0.2, 0.3], [0.9, 0.8, 0.7]],
        "bbox": [-0.25, -0.9, 0.25, 0.1],
        "created_utc": "2026-10-29T20:00:00Z",
    }
    assert Element.from_dict(element.to_dict()) == element


def test_element_from_dict_fills_defaults():
    element = Element.from_dict(
        {"name": "Oscar", "category": "prop", "asset_path": "p.png"}
    )
    assert element.description == ""
    assert element.seed == 0
    assert element.palette == ()
    assert element.bbox is None
    assert element.created_utc == ""


def test_element_from_dict_fills_the_asset_path_default():
    element = Element.from_dict({"name": "Oscar", "category": "prop"})
    assert element.asset_path == ""


def test_element_from_dict_without_a_name_is_an_error():
    """An empty default would silently create a nameless Element."""
    with pytest.raises(ValueError, match="non-empty"):
        Element.from_dict({"category": "prop", "asset_path": "x.png"})


def test_element_from_dict_without_a_category_is_an_error():
    """The fallback must be empty, so the error names the empty value."""
    with pytest.raises(ValueError) as excinfo:
        Element.from_dict({"name": "Oscar", "asset_path": "x.png"})
    assert "unknown Element category ''" in str(excinfo.value)


def test_element_from_dict_with_nothing_is_an_error():
    with pytest.raises(ValueError):
        Element.from_dict({})


def test_a_null_seed_loads_like_an_absent_one():
    """``"seed": null`` is not the same as a missing key to ``dict.get``.

    ``d.get("seed", 0)`` returns ``None`` when the key is present and null, so a
    bare ``int()`` raised ``TypeError`` on a registry written by hand or by
    another tool. An absent seed and a null seed both mean "no seed", so the
    loader must resolve them identically. ``nodes.CinemaElementSave`` already
    guards its own widget with ``int(seed or 0)``; this pins the loader to it.
    """
    base = {"name": "Oscar", "category": "prop", "asset_path": "x.png"}

    absent = Element.from_dict(base)
    null = Element.from_dict({**base, "seed": None})
    assert absent.seed == 0
    assert null.seed == 0
    assert null == absent

    # A real seed still survives, and 0 is not mistaken for "unset".
    assert Element.from_dict({**base, "seed": 7}).seed == 7
    assert Element.from_dict({**base, "seed": 0}).seed == 0


def test_the_element_constructor_accepts_a_null_seed_too():
    """The dataclass is public API, so the same guard belongs on both paths."""
    element = Element(name="Oscar", category="prop", asset_path="x.png", seed=None)
    assert element.seed == 0


# --------------------------------------------------------------------------
# ElementRegistry — lookup rules
# --------------------------------------------------------------------------


def test_get_is_case_insensitive(registry):
    assert registry.get("tamsin") is registry.get("TAMSIN")
    assert registry.get("tamsin").name == "Tamsin"


def test_get_strips_one_leading_at(registry):
    assert registry.get("@Tamsin").name == "Tamsin"
    assert registry.get("@tamsin").name == "Tamsin"
    assert registry.get("  @Tamsin  ").name == "Tamsin"


def test_get_missing_raises_keyerror(registry):
    with pytest.raises(KeyError) as excinfo:
        registry.get("ghost")
    assert excinfo.value.args[0] == "no Element named 'ghost'"


def test_get_missing_with_category_raises_keyerror(registry):
    with pytest.raises(KeyError) as excinfo:
        registry.get("Tamsin", "prop")
    assert excinfo.value.args[0] == "no Element named 'Tamsin' in category 'prop'"


def test_duplicate_name_in_one_category_is_an_error(registry):
    with pytest.raises(ValueError, match="duplicate"):
        registry.add(Element(name="TAMSIN", category="character", asset_path="b.png"))


def test_same_name_in_two_categories_is_legal():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    assert len(both) == 2


def test_get_without_category_is_ambiguous_when_the_name_is_in_two():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    with pytest.raises(ValueError) as excinfo:
        both.get("Tamsin")
    assert str(excinfo.value) == (
        "Element name 'Tamsin' is ambiguous: it exists in categories "
        "character, location; pass the category to choose one"
    )


def test_get_with_category_resolves_the_ambiguity():
    """The category argument must actually be used, not ignored."""
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    assert both.get("Tamsin", "character").asset_path == "c.png"
    assert both.get("Tamsin", "location").asset_path == "l.png"


def test_find_returns_none_for_a_missing_name(registry):
    assert registry.find("ghost") is None
    assert registry.find("ghost", "prop") is None


def test_find_raises_on_ambiguity():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    with pytest.raises(ValueError, match="ambiguous"):
        both.find("Tamsin")


def test_by_category_filters_and_orders_case_insensitively():
    mixed = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="bell barge", category="location", asset_path="b.png"),
            Element(name="Mirror Dunes", category="location", asset_path="d.png"),
        ]
    )
    assert [e.name for e in mixed.by_category("location")] == [
        "bell barge",
        "Mirror Dunes",
    ]
    assert [e.name for e in mixed.by_category("character")] == ["Tamsin"]
    assert mixed.by_category("prop") == []


def test_by_category_rejects_an_unknown_category(registry):
    with pytest.raises(ValueError, match="unknown Element category"):
        registry.by_category("set")


def test_names_orders_case_insensitively_and_keeps_duplicates():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
            Element(name="oscar", category="prop", asset_path="o.png"),
            Element(name="Bell Barge", category="location", asset_path="b.png"),
        ]
    )
    assert both.names() == ["Bell Barge", "oscar", "Tamsin", "Tamsin"]


def test_len_and_iter_are_deterministic(registry):
    assert len(registry) == 3
    assert [e.name for e in registry] == ["Tamsin", "Mirror Dunes", "helmet"]


def test_remove_returns_the_element_and_deletes_it(registry):
    removed = registry.remove("@tamsin")
    assert removed.name == "Tamsin"
    assert len(registry) == 2
    assert registry.find("Tamsin") is None


def test_remove_missing_raises(registry):
    with pytest.raises(KeyError, match="ghost"):
        registry.remove("ghost")


def test_add_rejects_a_non_element(registry):
    with pytest.raises(TypeError, match="expects an Element"):
        registry.add("Tamsin")  # type: ignore[arg-type]


def test_add_returns_the_element_for_chaining():
    fresh = ElementRegistry()
    element = Element(name="X", category="prop", asset_path="x.png")
    assert fresh.add(element) is element


def test_registry_from_dict_accepts_a_bare_list():
    rebuilt = ElementRegistry.from_dict([_helmet().to_dict()])
    assert rebuilt.names() == ["helmet"]


def test_registry_from_dict_rejects_other_types():
    with pytest.raises(ValueError, match="cannot read an Element registry"):
        ElementRegistry.from_dict("nope")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Persistence — the sidecar
# --------------------------------------------------------------------------


def test_registry_round_trips_through_dict(registry):
    assert ElementRegistry.from_dict(registry.to_dict()).to_dict() == registry.to_dict()


def test_registry_to_dict_is_ordered_and_self_describing(registry):
    data = registry.to_dict()
    assert data["categories"] == ["character", "location", "prop"]
    assert [e["name"] for e in data["elements"]] == [
        "Tamsin",
        "Mirror Dunes",
        "helmet",
    ]


def test_registry_saves_and_loads_a_real_file(registry, tmp_path):
    path = tmp_path / "elements.json"
    written = registry.save(str(path))
    assert written == str(path)
    assert path.exists()
    loaded = ElementRegistry.load(str(path))
    assert loaded.to_dict() == registry.to_dict()
    assert len(loaded) == 3


def test_save_creates_parent_directories(registry, tmp_path):
    path = tmp_path / "nested" / "deeper" / "elements.json"
    registry.save(str(path))
    assert path.exists()


def test_saved_file_is_json_with_the_categories(registry, tmp_path):
    path = tmp_path / "elements.json"
    registry.save(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["categories"] == ["character", "location", "prop"]
    assert len(data["elements"]) == 3


def test_saved_file_ends_with_a_newline(registry, tmp_path):
    path = tmp_path / "elements.json"
    registry.save(str(path))
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_saved_file_is_indented_by_two_spaces(registry, tmp_path):
    """A sidecar is meant to be read and diffed by a human."""
    path = tmp_path / "elements.json"
    registry.save(str(path))
    text = path.read_text(encoding="utf-8")
    assert '\n  "categories"' in text
    assert '\n      "name"' in text


# --------------------------------------------------------------------------
# parse_element_tags — the grammar
# --------------------------------------------------------------------------


def test_parse_a_single_tag():
    assert parse_element_tags("@Tamsin") == ("", ["Tamsin"])


def test_parse_a_tag_after_text():
    assert parse_element_tags("hello @Tamsin") == ("hello", ["Tamsin"])


def test_parse_a_multiword_name():
    assert parse_element_tags("@Mirror Dunes") == ("", ["Mirror Dunes"])


def test_parse_stops_a_multiword_name_at_a_comma():
    assert parse_element_tags("go to @Mirror Dunes, now") == ("go to, now", ["Mirror Dunes"])


def test_parse_stops_at_a_hash_tag():
    assert parse_element_tags("@Tamsin #dolly-in") == ("#dolly-in", ["Tamsin"])


def test_parse_a_tag_inside_parentheses():
    assert parse_element_tags("(@Tamsin)") == ("()", ["Tamsin"])


@pytest.mark.parametrize(
    "prompt",
    [
        "nathaniel@example.com",
        "mail nathaniel@example.com now",
        "a@b",
        "user_@Tamsin",
        "@@Tamsin",
    ],
)
def test_parse_does_not_match_an_email_address(prompt):
    """The negative case that matters: an ``@`` glued to a word char is not a tag."""
    assert parse_element_tags(prompt) == (prompt, [])


def test_parse_returns_the_prompt_verbatim_when_there_are_no_tags():
    """A tag-free prompt is never rewritten, whitespace and all."""
    prompt = "  a  prompt   with no tags  "
    assert parse_element_tags(prompt) == (prompt, [])


def test_parse_handles_an_empty_prompt():
    assert parse_element_tags("") == ("", [])


def test_parse_handles_a_missing_prompt():
    assert parse_element_tags(None) == ("", [])  # type: ignore[arg-type]


def test_parse_handles_a_lone_at_sign():
    assert parse_element_tags("@") == ("@", [])


def test_parse_requires_an_alphanumeric_first_character():
    assert parse_element_tags("@1st") == ("", ["1st"])
    assert parse_element_tags("@-x") == ("@-x", [])


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("@Mirror Dunes", "Mirror Dunes"),
        ("@snake_case", "snake_case"),
        ("@O'Brien", "O'Brien"),
        ("@bell-barge", "bell-barge"),
    ],
)
def test_parse_name_character_set(prompt, expected):
    """Space, underscore, apostrophe and hyphen are all legal inside a name."""
    assert parse_element_tags(prompt) == ("", [expected])


@pytest.mark.parametrize(
    "separator,expected_clean",
    [(" ", ""), ("_", "_"), ("'", "'"), ("-", "-")],
)
def test_parse_trims_trailing_separators(separator, expected_clean):
    """The separator is not part of the name, but it is not swallowed either."""
    assert parse_element_tags("@Tamsin" + separator) == (expected_clean, ["Tamsin"])


@pytest.mark.parametrize("punctuation", [",", ".", ";", ":", "!", "?"])
def test_parse_stops_at_sentence_punctuation(punctuation):
    assert parse_element_tags("@Tamsin" + punctuation + " wide shot") == (
        "wide shot",
        ["Tamsin"],
    )


def test_parse_collapses_whitespace_inside_a_name():
    assert parse_element_tags("@Mirror   Dunes") == ("", ["Mirror Dunes"])


def test_parse_keeps_first_appearance_order_and_collapses_duplicates():
    assert parse_element_tags("@Tamsin @Oscar @tamsin @Mirror Dunes") == (
        "",
        ["Tamsin", "Oscar", "Mirror Dunes"],
    )


def test_parse_is_greedy_to_the_next_delimiter():
    """The documented consequence of the syntax, pinned so it cannot drift.

    A multi-word name runs to the next ``@``, ``#`` or punctuation, so filler
    words between two tags become part of the first name. Put the delimiter in.
    """
    assert parse_element_tags("@Tamsin walks into @Mirror Dunes") == (
        "",
        ["Tamsin walks into", "Mirror Dunes"],
    )


def test_parse_clean_prompt_collapses_whitespace():
    assert parse_element_tags("@Tamsin,   wide    shot") == ("wide shot", ["Tamsin"])


def test_parse_clean_prompt_tidies_a_space_before_punctuation():
    assert parse_element_tags("a @Tamsin, wide shot") == ("a, wide shot", ["Tamsin"])


def test_parse_clean_prompt_drops_leftover_edge_punctuation():
    assert parse_element_tags("@Tamsin, wide shot") == ("wide shot", ["Tamsin"])


def test_parse_clean_prompt_keeps_a_trailing_word():
    """Only whitespace and punctuation are trimmed, never a letter."""
    assert parse_element_tags("@Tamsin, X") == ("X", ["Tamsin"])
    assert parse_element_tags("@Tamsin, Xx") == ("Xx", ["Tamsin"])


def test_parse_handles_several_tags_and_text():
    assert parse_element_tags("a @Tamsin and @helmet, wide") == (
        "a, wide",
        ["Tamsin and", "helmet"],
    )


# --------------------------------------------------------------------------
# resolve_elements — a missing Element is a value, not an exception
# --------------------------------------------------------------------------


def test_resolve_all_present(registry):
    resolution = resolve_elements("@Tamsin @helmet", registry)
    assert resolution.names == ["Tamsin", "helmet"]
    assert resolution.missing == []
    assert resolution.ambiguous == []
    assert resolution.ok is True
    assert resolution.clean_prompt == ""


def test_resolve_reports_missing_names_without_raising(registry):
    resolution = resolve_elements("@Tamsin @ghost @phantom", registry)
    assert resolution.names == ["Tamsin"]
    assert resolution.missing == ["ghost", "phantom"]
    assert resolution.ok is False


def test_resolve_reports_ambiguous_names_separately():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    resolution = resolve_elements("@Tamsin", both)
    assert resolution.resolved == []
    assert resolution.missing == []
    assert resolution.ambiguous == ["Tamsin"]
    assert resolution.ok is False


def test_resolve_with_no_tags_is_ok(registry):
    resolution = resolve_elements("a prompt with no tags", registry)
    assert resolution.resolved == []
    assert resolution.missing == []
    assert resolution.ok is True
    assert resolution.clean_prompt == "a prompt with no tags"


def test_resolve_keeps_the_clean_prompt(registry):
    resolution = resolve_elements("a @Tamsin, wide shot", registry)
    assert resolution.clean_prompt == "a, wide shot"


def test_resolution_to_dict(registry):
    resolution = resolve_elements("@Tamsin @ghost", registry)
    assert resolution.to_dict() == {
        "clean_prompt": "",
        "resolved": [_tamsin().to_dict()],
        "missing": ["ghost"],
        "ambiguous": [],
        "ok": False,
    }


def test_resolution_defaults_are_optimistic(registry):
    """The dataclass defaults, not the values ``resolve_elements`` computes.

    ``resolve_elements`` always sets ``ok`` explicitly, so nothing else in this
    file exercises the default. It matters because a caller constructing a
    resolution by hand (a node assembling a partial result) gets ``ok=True`` and
    empty lists unless it says otherwise -- an optimistic default that should be
    a deliberate choice, not an accident of the field order.
    """
    resolution = ElementResolution(clean_prompt="wide")
    assert resolution.ok is True
    assert resolution.resolved == []
    assert resolution.missing == []
    assert resolution.ambiguous == []


def test_element_summary_when_everything_resolves(registry):
    assert (
        element_summary(resolve_elements("@Tamsin @helmet", registry))
        == "OK - resolved 2 element(s): Tamsin, helmet"
    )


def test_element_summary_when_names_are_missing(registry):
    assert (
        element_summary(resolve_elements("@Tamsin @ghost @phantom", registry))
        == "UNRESOLVED - 1 of 3 element(s) resolved; missing: ghost, phantom"
    )


def test_element_summary_when_a_name_is_ambiguous():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    assert (
        element_summary(resolve_elements("@Tamsin", both))
        == "UNRESOLVED - 0 of 1 element(s) resolved; ambiguous: Tamsin"
    )


def test_element_summary_with_no_tags(registry):
    assert (
        element_summary(resolve_elements("nothing here", registry))
        == "OK - no @Element tags in prompt"
    )


def test_element_summary_lists_several_ambiguous_names():
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
            Element(name="Oscar", category="character", asset_path="o.png"),
            Element(name="Oscar", category="location", asset_path="o2.png"),
        ]
    )
    assert element_summary(resolve_elements("@Tamsin @Oscar", both)) == (
        "UNRESOLVED - 0 of 2 element(s) resolved; ambiguous: Tamsin, Oscar"
    )


def test_element_summary_separates_missing_from_ambiguous():
    """Both kinds of failure in one prompt: the two clauses must stay distinct."""
    both = ElementRegistry(
        [
            Element(name="Tamsin", category="character", asset_path="c.png"),
            Element(name="Tamsin", category="location", asset_path="l.png"),
        ]
    )
    assert element_summary(resolve_elements("@Tamsin @ghost", both)) == (
        "UNRESOLVED - 0 of 2 element(s) resolved; missing: ghost; ambiguous: Tamsin"
    )


def test_element_summaries_are_ascii(registry):
    summaries = [
        element_summary(resolve_elements("@Tamsin @helmet", registry)),
        element_summary(resolve_elements("@Tamsin @ghost", registry)),
        element_summary(resolve_elements("nothing here", registry)),
    ]
    assert all(summary.isascii() for summary in summaries)


# --------------------------------------------------------------------------
# audit_element — what is usable, and what is measurable
# --------------------------------------------------------------------------


def test_audit_of_a_complete_element_passes():
    audit = audit_element(_tamsin())
    assert audit.overall_pass is True
    assert audit.failures() == []
    assert audit.continuity_ready is True
    assert [check.rule for check in audit.checks] == list(ELEMENT_RULES)
    assert [check.weight for check in audit.checks] == [1.0, 1.0, 1.0, 0.5, 0.5, 0.3]
    assert audit_summary(audit) == "OK - Element 'Tamsin' (character) passes all 6 checks"


def test_audit_of_a_clean_plate_passes_with_non_gating_flags():
    """A location has no palette and no bbox; that must not fail the Element."""
    audit = audit_element(_dunes())
    assert audit.overall_pass is True
    assert [check.rule for check in audit.failures()] == [
        "palette_present",
        "bbox_present",
        "described",
    ]
    assert audit.continuity_ready is False
    assert audit_summary(audit) == (
        "OK - Element 'Mirror Dunes' (location) passes 6 checks with 3 non-gating "
        "flag(s): palette_present (0 palette colour(s)), bbox_present (bbox None), "
        "described (description '')"
    )


def test_audit_fails_when_the_asset_is_missing():
    """``asset_present`` gates: an Element with no asset cannot be loaded."""
    element = Element(
        name="Oscar",
        category="prop",
        asset_path="",
        description="a helmet",
        palette=((0.0, 0.0, 0.0),),
        bbox=(0.0, 0.0, 0.0, 0.0),
    )
    audit = audit_element(element)
    assert audit.overall_pass is False
    assert audit.check("asset_present").passed is False
    assert audit.continuity_ready is True
    assert audit_summary(audit) == "FAIL - Element 'Oscar' (prop): asset_present (asset_path '')"


def test_audit_check_lookup_returns_none_for_an_unknown_rule():
    assert audit_element(_tamsin()).check("nonsense") is None


def test_audit_defaults_are_optimistic():
    """The dataclass defaults, not the verdict ``audit_element`` computes.

    ``audit_element`` always sets ``overall_pass`` from the weighted rules, so
    nothing else exercises the default. A hand-built audit (a node reporting a
    partial check) therefore reads as a pass until told otherwise, which is the
    honest default only because an audit with no failing check has, in fact,
    failed nothing.
    """
    audit = ElementAudit(name="Tamsin", category="character")
    assert audit.overall_pass is True
    assert audit.checks == []


def test_audit_to_dict():
    element = Element(name="Oscar", category="prop", asset_path="")
    audit = audit_element(element)
    data = audit.to_dict()
    assert data["name"] == "Oscar"
    assert data["category"] == "prop"
    assert data["overall_pass"] is False
    assert data["continuity_ready"] is False
    assert len(data["checks"]) == 6
    assert data["checks"][2] == {
        "rule": "asset_present",
        "pass": False,
        "weight": 1.0,
        "detail": "asset_path ''",
    }


def test_audit_summaries_are_ascii():
    summaries = [
        audit_summary(audit_element(_tamsin())),
        audit_summary(audit_element(_dunes())),
        audit_summary(audit_element(Element(name="X", category="prop", asset_path=""))),
    ]
    assert all(summary.isascii() for summary in summaries)


def test_audit_summary_fail_lists_every_failure():
    element = Element(name="X", category="prop", asset_path="")
    assert audit_summary(audit_element(element)) == (
        "FAIL - Element 'X' (prop): asset_present (asset_path ''), "
        "palette_present (0 palette colour(s)), bbox_present (bbox None), "
        "described (description '')"
    )


def test_continuity_ready_needs_both_a_palette_and_a_bbox():
    """Either one alone is not enough to measure identity against."""
    palette_only = Element(
        name="P",
        category="character",
        asset_path="p.png",
        palette=((0.1, 0.2, 0.3),),
    )
    bbox_only = Element(
        name="B", category="character", asset_path="b.png", bbox=(-0.1, -0.5, 0.1, 0.5)
    )
    assert audit_element(palette_only).continuity_ready is False
    assert audit_element(bbox_only).continuity_ready is False
    assert audit_element(_tamsin()).continuity_ready is True


# --------------------------------------------------------------------------
# The bridge into the identity layer
# --------------------------------------------------------------------------


def test_character_record_from_element_carries_the_reference_data():
    record = character_record_from_element(_tamsin())
    assert record.name == "Tamsin"
    assert record.bbox == (-0.25, -0.9, 0.25, 0.1)
    assert record.palette == ((0.1, 0.2, 0.3), (0.9, 0.8, 0.7))
    assert record.eye_ratio == DEFAULT_EYE_RATIO
    assert record.eye_ratio == 0.92
    assert record.height == 1.0  # 0.1 - (-0.9)


def test_character_record_from_element_raises_without_a_palette():
    with pytest.raises(ValueError, match="no palette"):
        character_record_from_element(_dunes())


def test_character_record_from_element_raises_without_a_bbox():
    element = Element(
        name="Tamsin",
        category="character",
        asset_path="t.png",
        palette=((0.1, 0.2, 0.3),),
    )
    with pytest.raises(ValueError, match="no bbox"):
        character_record_from_element(element)


def test_character_record_from_element_feeds_the_continuity_layer():
    """The whole point of the bridge: measure a shot against its Element."""
    reference = character_record_from_element(_tamsin())
    identical = CharacterAppearance(
        name="Tamsin",
        bbox=(-0.25, -0.9, 0.25, 0.1),
        palette=((0.1, 0.2, 0.3), (0.9, 0.8, 0.7)),
    )
    assert identical.height == 1.0
    report = evaluate_character_continuity([reference, identical])
    assert report.overall_pass is True
    assert report.value("palette_drift") == 0.0
    assert report.value("proportion_drift") == 0.0
    assert report.value("framing_drift") == 0.0
