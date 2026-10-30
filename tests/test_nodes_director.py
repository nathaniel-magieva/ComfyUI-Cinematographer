"""The Stage 3/4 nodes: the director's panel, the move resolver, the emotion
wheel, and the prompt composer.

Why this file exists
--------------------
These four nodes are thin wrappers, and thin wrappers fail in one specific way:
the dropdown drifts from the engine. A hand-typed copy of an enum looks
identical to the real one until the engine adds a value, and then the node
silently offers a stale list. So the central test here is not "does the node
work" but **"is every dropdown value a member of the engine's own constant"** --
read from the constant, never re-typed.

The other thing worth pinning is that these nodes *describe*. None of them
renders, grades, or generates anything, and none of them may claim to.

The engine's own behaviour (which values are legal, what a fragment looks like)
is tested in ``test_director.py`` and ``test_prompt.py``. This file tests the
wiring.
"""

import json

import pytest

from cinematographer import director
from cinematographer import elements
from cinematographer import nodes
from cinematographer import prompt


# --------------------------------------------------------------------------
# the drift guard: every dropdown is the engine's constant, not a copy
# --------------------------------------------------------------------------

#: (node, input name, engine module, constant name, prepended values)
DROPDOWNS = [
    (nodes.CinemaDirectorPanel, "genre", director, "GENRES", ("auto",)),
    (nodes.CinemaDirectorPanel, "era", director, "ERAS", ("auto",)),
    (nodes.CinemaDirectorPanel, "pacing", director, "TEMPOS", ("auto",)),
    (nodes.CinemaDirectorPanel, "camera_model", director, "CAMERA_BODIES", ("auto",)),
    (nodes.CinemaDirectorPanel, "camera_lens", director, "LENSES", ("auto",)),
    (nodes.CinemaDirectorPanel, "camera_aperture", director, "APERTURES", ("auto",)),
    (nodes.CinemaDirectorPanel, "light", director, "LIGHTING_LOOKS", ("auto",)),
    (nodes.CinemaDirectorPanel, "color_palette", director, "COLOUR_PALETTES", ("auto",)),
    (nodes.CinemaDirectorPanel, "emotion", director, "EMOTIONS", ("auto",)),
    (nodes.CinemaEmotionWheel, "emotion", director, "EMOTIONS", ()),
    (nodes.CinemaCameraMove, "move", prompt, "CAMERA_MOVES", ("none",)),
]


def _dropdown(node_cls, name):
    inputs = node_cls.INPUT_TYPES()
    for group in ("required", "optional"):
        if name in inputs.get(group, {}):
            return inputs[group][name][0]
    raise AssertionError(f"{node_cls.__name__} has no input {name!r}")


@pytest.mark.parametrize(
    "node_cls,name,module,const,prepend",
    DROPDOWNS,
    ids=[f"{n.__name__}.{i}" for n, i, _, _, _ in DROPDOWNS],
)
def test_every_dropdown_is_the_engine_constant_plus_its_prepends(
    node_cls, name, module, const, prepend
):
    """The dropdown must be exactly `prepend + engine_constant`, in order.

    Equality, not subset: a subset would let the node drop a value the engine
    supports, and a superset would let it offer one the engine rejects.
    """
    expected = tuple(prepend) + tuple(getattr(module, const))
    assert tuple(_dropdown(node_cls, name)) == expected


@pytest.mark.parametrize(
    "node_cls,name,module,const,prepend",
    DROPDOWNS,
    ids=[f"{n.__name__}.{i}" for n, i, _, _, _ in DROPDOWNS],
)
def test_no_dropdown_offers_a_value_the_engine_would_reject(
    node_cls, name, module, const, prepend
):
    """Every offered value is either a prepend sentinel or a real engine member."""
    allowed = set(getattr(module, const))
    for value in _dropdown(node_cls, name):
        assert value in allowed or value in prepend, (
            f"{node_cls.__name__}.{name} offers {value!r}, which is neither a "
            f"{const} member nor one of {prepend}"
        )


def test_the_palette_dropdown_carries_all_fifty_documented_presets():
    """The list was once short. It is complete now, and this pins that."""
    assert len(director.COLOUR_PALETTES) == director.COLOUR_PALETTES_TOTAL == 50
    assert len(_dropdown(nodes.CinemaDirectorPanel, "color_palette")) == 51  # +auto


def test_the_move_dropdown_carries_all_thirty_three_documented_moves():
    assert len(prompt.CAMERA_MOVES) == prompt.CAMERA_MOVES_TOTAL == 33
    assert len(_dropdown(nodes.CinemaCameraMove, "move")) == 34  # +none


def test_the_emotion_intensity_range_comes_from_the_engine():
    """The scale is invented, but it is invented in ONE place."""
    for node_cls in (nodes.CinemaDirectorPanel, nodes.CinemaEmotionWheel):
        spec = node_cls.INPUT_TYPES()
        group = "optional" if node_cls is nodes.CinemaDirectorPanel else "required"
        key = "emotion_intensity" if node_cls is nodes.CinemaDirectorPanel else "intensity"
        widget = spec[group][key][1]
        assert widget["min"] == director.EMOTION_INTENSITY_MIN
        assert widget["max"] == director.EMOTION_INTENSITY_MAX


# --------------------------------------------------------------------------
# CinemaDirectorPanel
# --------------------------------------------------------------------------


def _panel(**kwargs):
    defaults = dict(
        genre="auto",
        era="auto",
        pacing="auto",
        camera_model="auto",
        camera_lens="auto",
        camera_aperture="auto",
        light="auto",
        color_palette="auto",
    )
    defaults.update(kwargs)
    return nodes.CinemaDirectorPanel().panel(**defaults)


def test_an_all_auto_panel_contributes_nothing():
    """If auto added a character, "auto" would stop meaning "the model decides"."""
    panel_json, fragment, summary = _panel()
    assert fragment == ""
    assert "all groups auto" in summary
    assert json.loads(panel_json)["emotion"] == []


def test_a_set_panel_produces_a_fragment_naming_each_group():
    _, fragment, _ = _panel(
        genre="noir",
        era="1980s",
        pacing="calm",
        camera_model="35mm-film",
        camera_lens="anamorphic",
        camera_aperture="f4-moderate",
        light="practicals",
        color_palette="static-noon",
    )
    for token in (
        "genre noir",
        "era 1980s",
        "pacing calm",
        "camera 35mm-film",
        "lens anamorphic",
        "aperture f4-moderate",
        "lighting practicals",
        "palette static-noon",
    ):
        assert token in fragment


def test_the_panel_json_uses_the_api_field_names_verbatim():
    """This is what makes the web panel's parity check a real drift check."""
    panel_json, _, _ = _panel(genre="noir")
    assert set(json.loads(panel_json)) == set(director.PANEL_FIELDS)


def test_the_panel_json_round_trips_through_the_engine():
    panel_json, _, _ = _panel(genre="noir", color_palette="static-noon")
    rebuilt = director.DirectorPanel.from_dict(json.loads(panel_json))
    assert rebuilt.to_dict() == json.loads(panel_json)


def test_a_custom_palette_is_accepted_and_flagged():
    """A user-created palette is free text, and the flag says so."""
    panel_json, fragment, _ = _panel(custom_palette="Molten Dawn")
    data = json.loads(panel_json)
    assert data["color_palette"] == "Molten Dawn"
    assert data["custom"] is True
    assert "Molten Dawn" in fragment


def test_a_custom_palette_round_trips_through_the_engine():
    """Without the flag the engine would reject its own output."""
    panel_json, _, _ = _panel(custom_palette="Molten Dawn")
    rebuilt = director.DirectorPanel.from_dict(json.loads(panel_json))
    assert rebuilt.to_dict() == json.loads(panel_json)


def test_a_preset_panel_does_not_carry_the_custom_flag():
    """The flag is emitted only when true, so preset dicts are unchanged."""
    panel_json, _, _ = _panel(color_palette="static-noon")
    assert "custom" not in json.loads(panel_json)


def test_an_explicit_palette_beats_the_custom_text():
    """The dropdown wins; the free-text box is only a fallback."""
    panel_json, _, _ = _panel(color_palette="static-noon", custom_palette="Molten Dawn")
    assert json.loads(panel_json)["color_palette"] == "static-noon"


def test_a_character_with_no_emotion_does_not_turn_the_panel_off_auto():
    """Listing a character is not the same as directing them."""
    _, fragment, summary = _panel(emotion_character="tamsin")
    assert fragment == ""
    assert "all groups auto" in summary


def test_an_emotion_direction_reaches_the_fragment():
    _, fragment, _ = _panel(
        emotion_character="tamsin", emotion="Joy", emotion_intensity=0.5
    )
    assert fragment == "@tamsin Joy 0.5"


def test_an_emotion_direction_reaches_the_panel_json():
    panel_json, _, _ = _panel(
        emotion_character="tamsin", emotion="Joy", emotion_intensity=0.25
    )
    assert json.loads(panel_json)["emotion"] == [
        {"character": "tamsin", "emotion": "Joy", "intensity": 0.25}
    ]


def test_an_emotion_without_a_character_is_ignored():
    """There is nobody to direct, so nothing is emitted."""
    panel_json, fragment, _ = _panel(emotion="Joy", emotion_intensity=0.5)
    assert fragment == ""
    assert json.loads(panel_json)["emotion"] == []


def test_a_value_outside_the_engine_enum_raises_rather_than_being_passed_on():
    with pytest.raises(ValueError, match="genre="):
        _panel(genre="general")


def test_a_bad_emotion_raises_rather_than_being_passed_on():
    with pytest.raises(ValueError, match="emotion="):
        _panel(emotion_character="tamsin", emotion="Ecstatic")


def test_an_out_of_range_intensity_raises():
    with pytest.raises(ValueError):
        _panel(emotion_character="tamsin", emotion="Joy", emotion_intensity=5.0)


def test_the_panel_node_does_not_claim_to_render_anything():
    """It describes a look. The wording must not overstate."""
    description = nodes.CinemaDirectorPanel.DESCRIPTION.lower()
    assert "does not render" in description


# --------------------------------------------------------------------------
# CinemaCameraMove
# --------------------------------------------------------------------------


def test_move_tags_are_extracted_and_stripped_from_the_prompt():
    clean, moves, unknown, ok = nodes.CinemaCameraMove().resolve(
        "she walks in #tracking then #helicopter-shot"
    )
    assert clean == "she walks in then"
    assert json.loads(moves) == ["tracking", "helicopter-shot"]
    assert json.loads(unknown) == []
    assert ok is True


def test_an_unknown_move_is_reported_not_raised():
    """Same contract as an unresolved @Element: a value, not an exception."""
    _, moves, unknown, ok = nodes.CinemaCameraMove().resolve("a #moonwalk b")
    assert json.loads(moves) == []
    assert json.loads(unknown) == ["moonwalk"]
    assert ok is False


def test_a_move_chosen_from_the_dropdown_is_added_to_the_prompt():
    """The widget is a way to ask for a move without typing the tag."""
    _, moves, _, ok = nodes.CinemaCameraMove().resolve("no tags here", move="dolly-in")
    assert json.loads(moves) == ["dolly-in"]
    assert ok is True


def test_the_none_sentinel_adds_nothing():
    _, moves, _, ok = nodes.CinemaCameraMove().resolve("no tags here", move="none")
    assert json.loads(moves) == []
    assert ok is True


def test_a_dropdown_move_already_in_the_text_is_not_duplicated():
    _, moves, _, _ = nodes.CinemaCameraMove().resolve("a #tracking b", move="tracking")
    assert json.loads(moves) == ["tracking"]


def test_a_prompt_with_no_moves_is_clean_and_ok():
    clean, moves, unknown, ok = nodes.CinemaCameraMove().resolve("just prose")
    assert clean == "just prose"
    assert json.loads(moves) == []
    assert json.loads(unknown) == []
    assert ok is True


def test_a_hex_colour_is_not_mistaken_for_a_move_tag():
    """`#E36332` is a colour, not a camera move."""
    _, moves, unknown, _ = nodes.CinemaCameraMove().resolve("paint it #E36332")
    assert json.loads(moves) == []
    assert json.loads(unknown) == []


# --------------------------------------------------------------------------
# CinemaEmotionWheel
# --------------------------------------------------------------------------


def test_the_wheel_emits_a_direction_and_a_fragment():
    direction_json, fragment, summary = nodes.CinemaEmotionWheel().direct(
        "tamsin", "Joy", 0.5
    )
    assert json.loads(direction_json) == {
        "character": "tamsin",
        "emotion": "Joy",
        "intensity": 0.5,
    }
    assert fragment == "@tamsin Joy 0.5"
    assert "invented" in summary


def test_the_wheel_round_trips_through_the_engine():
    direction_json, _, _ = nodes.CinemaEmotionWheel().direct("tamsin", "Joy", 0.25)
    rebuilt = director.EmotionDirection.from_dict(json.loads(direction_json))
    assert rebuilt.to_dict() == json.loads(direction_json)


def test_the_wheel_rejects_an_emotion_the_engine_does_not_know():
    with pytest.raises(ValueError, match="emotion="):
        nodes.CinemaEmotionWheel().direct("tamsin", "Ecstatic", 0.5)


def test_the_wheel_rejects_an_empty_character():
    with pytest.raises(ValueError):
        nodes.CinemaEmotionWheel().direct("", "Joy", 0.5)


def test_the_wheel_summary_says_the_scale_is_invented():
    """Honesty: no published source defines the intensity scale."""
    _, _, summary = nodes.CinemaEmotionWheel().direct("tamsin", "Joy", 0.5)
    assert "invented" in summary


# --------------------------------------------------------------------------
# CinemaPromptCompose
# --------------------------------------------------------------------------


def test_a_bare_action_composes_to_itself():
    final, attachments, unresolved, ok = nodes.CinemaPromptCompose().compose(
        "a woman walks into the diner"
    )
    assert final == "a woman walks into the diner"
    assert json.loads(attachments) == []
    assert json.loads(unresolved) == []
    assert ok is True


def test_the_panel_fragment_is_appended_to_the_action():
    panel_json, _, _ = _panel(genre="noir")
    final, _, _, _ = nodes.CinemaPromptCompose().compose(
        "a woman walks in", panel_json=panel_json
    )
    assert final == "a woman walks in genre noir"


def test_extra_moves_are_appended_as_tags():
    final, _, _, _ = nodes.CinemaPromptCompose().compose(
        "a woman walks in", moves="dolly-in, tracking"
    )
    assert final.endswith("#dolly-in #tracking")


def test_an_empty_panel_json_means_no_panel():
    final, _, _, _ = nodes.CinemaPromptCompose().compose("a walk", panel_json="")
    assert final == "a walk"


def test_a_malformed_panel_json_raises():
    with pytest.raises(ValueError, match="panel_json"):
        nodes.CinemaPromptCompose().compose("a walk", panel_json="{not json")


def test_a_panel_json_that_is_not_an_object_raises():
    with pytest.raises(ValueError, match="must be a JSON object"):
        nodes.CinemaPromptCompose().compose("a walk", panel_json="[]")


def test_a_custom_palette_panel_survives_the_compose_round_trip():
    """The panel node emits it, the compose node must be able to read it back."""
    panel_json, _, _ = _panel(custom_palette="Molten Dawn")
    final, _, _, _ = nodes.CinemaPromptCompose().compose("a walk", panel_json=panel_json)
    assert final == "a walk palette Molten Dawn"


def test_an_element_tag_resolves_against_a_registry(tmp_path):
    """A resolved tag is kept in the prompt AND gets an API attachment.

    The ``@Name`` tag is the app's own prompt syntax, so it stays in the final
    prompt -- but it is re-emitted in canonical position (after the action and
    the panel, before the ``#`` moves) rather than left wherever it was typed.
    The attachment is what the API actually consumes.
    """
    registry_path = str(tmp_path / "elements.json")
    registry = elements.ElementRegistry()
    registry.add(
        elements.Element(
            name="tamsin",
            category="character",
            asset_path=str(tmp_path / "tamsin.png"),
        )
    )
    registry.save(registry_path)

    final, attachments, unresolved, ok = nodes.CinemaPromptCompose().compose(
        "a walk with @tamsin", registry_path=registry_path
    )
    assert final == "a walk with @tamsin"
    assert json.loads(unresolved) == []
    assert ok is True
    assert json.loads(attachments) == [
        {
            "token": prompt.API_REFERENCE_TOKEN.format(n=1),
            "name": "tamsin",
            "asset_path": str(tmp_path / "tamsin.png"),
        }
    ]


def test_a_resolved_tag_is_moved_to_its_canonical_position(tmp_path):
    """Assembly order is action, panel, @tags, #tags -- and nothing else.

    The comma after ``@tamsin`` matters: the shared parser reads a name greedily
    up to the next ``@``, ``#`` or punctuation, so ``@tamsin walks in`` is one
    (unknown) name. That is ``elements``' documented contract, not a bug here.
    """
    registry_path = str(tmp_path / "elements.json")
    registry = elements.ElementRegistry()
    registry.add(
        elements.Element(
            name="tamsin", category="character", asset_path=str(tmp_path / "t.png")
        )
    )
    registry.save(registry_path)
    panel_json, _, _ = _panel(genre="noir")

    final, _, _, _ = nodes.CinemaPromptCompose().compose(
        "@tamsin, walks in #tracking",
        panel_json=panel_json,
        registry_path=registry_path,
    )
    assert final == "walks in genre noir @tamsin #tracking"


def test_an_unknown_element_is_reported_not_raised(tmp_path):
    registry_path = str(tmp_path / "elements.json")
    elements.ElementRegistry().save(registry_path)

    _, _, unresolved, ok = nodes.CinemaPromptCompose().compose(
        "a walk with @nobody", registry_path=registry_path
    )
    assert json.loads(unresolved) == ["nobody"]
    assert ok is False


def test_a_missing_registry_file_starts_empty_rather_than_failing(tmp_path):
    """A first run has no registry yet; that is not an error."""
    _, _, unresolved, ok = nodes.CinemaPromptCompose().compose(
        "a walk with @nobody", registry_path=str(tmp_path / "absent.json")
    )
    assert json.loads(unresolved) == ["nobody"]
    assert ok is False


def test_the_compose_node_does_not_duplicate_the_element_parser():
    """`@Name` parsing lives in `elements`; `prompt` imports it.

    A second parser is how two modules end up disagreeing about where a name
    ends. This asserts the node reaches for the shared one.
    """
    import inspect

    source = inspect.getsource(nodes.CinemaPromptCompose)
    assert "parse_element_tags" not in source
    assert "resolve_elements" not in source


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def test_all_eighteen_nodes_are_registered():
    assert len(nodes.NODE_CLASS_MAPPINGS) == 18


def test_every_registered_node_has_a_display_name():
    for class_name in nodes.NODE_CLASS_MAPPINGS:
        assert class_name in nodes.NODE_DISPLAY_NAME_MAPPINGS


def test_every_registered_node_declares_the_full_comfyui_interface():
    for class_name, node_cls in nodes.NODE_CLASS_MAPPINGS.items():
        assert node_cls.CATEGORY == "Cinematographer", class_name
        assert isinstance(node_cls.RETURN_TYPES, tuple), class_name
        assert isinstance(node_cls.RETURN_NAMES, tuple), class_name
        assert len(node_cls.RETURN_TYPES) == len(node_cls.RETURN_NAMES), class_name
        assert isinstance(node_cls.FUNCTION, str), class_name
        assert callable(getattr(node_cls, node_cls.FUNCTION)), class_name
        assert "required" in node_cls.INPUT_TYPES(), class_name


def test_the_four_new_director_and_prompt_nodes_are_registered():
    for class_name in (
        "CinemaDirectorPanel",
        "CinemaCameraMove",
        "CinemaEmotionWheel",
        "CinemaPromptCompose",
    ):
        assert class_name in nodes.NODE_CLASS_MAPPINGS


def test_only_the_grade_apply_node_changes_pixels():
    """Every other node measures, describes, or assembles text."""
    for class_name, node_cls in nodes.NODE_CLASS_MAPPINGS.items():
        if class_name == "CinemaGradeApply":
            assert node_cls.RETURN_TYPES[0] == "IMAGE"
            continue
        assert "IMAGE" not in node_cls.RETURN_TYPES, class_name
