"""Stage 4 SHOOT -- tag order, tag dedup, and the promise of no invented prose.

Why this file exists
--------------------

``prompt.py`` makes one promise that is easy to break by accident and hard to
notice: **the prompt does exactly two jobs**. It describes the action and it
carries the tags. The moment ``compose_prompt`` adds a word of its own --
"cinematic", "8k", "masterpiece" -- the product's central claim collapses,
because the panels are supposed to be doing that work and a self-padding prompt
would hide whether they do.

So the prose test is written as a *negative*: the final prompt is asserted equal
to a hand-typed string built only from the inputs. Any extra word fails it.

The other two things pinned here:

* **Order is load-bearing.** Stacked moves run in order, so ``parse_move_tags``
  must preserve first-appearance order and collapse duplicates without
  reordering. A set would pass a naive membership test and fail the product.
* **Unknown moves are reported, not dropped.** ``#moonwalk`` must come back in
  ``unknown``. Silently discarding it would make the engine look like it honoured
  a move it does not know.

Expected values are typed out by hand, never read back from the module under test.
"""

import pytest

from cinematographer import prompt
from cinematographer.elements import Element, ElementRegistry
from cinematographer.prompt import (
    API_REFERENCE_TOKEN,
    CAMERA_MOVES,
    CAMERA_MOVES_TOTAL,
    MOVE_TAG_PREFIX,
    ComposedPrompt,
    MoveResolution,
    MoveStack,
    compose_prompt,
    move_summary,
    parse_move_tags,
    resolve_move_tags,
)

# --------------------------------------------------------------------------
# The constants, spelled out
# --------------------------------------------------------------------------


def test_camera_moves_are_complete_and_match_the_total():
    """The list is the whole enum, not a subset.

    An earlier revision shipped 9 of 33 and asserted ``len < TOTAL``. That
    assertion was true and the premise behind it was false: the other 24 names
    were in the prose section of the schema capture the whole time. The list is
    now transcribed in full, so the two counts must be equal -- and the
    transcription is pinned verbatim below so a future edit that drops or
    reorders a member fails here rather than silently shrinking the enum.
    """
    assert CAMERA_MOVES_TOTAL == 33
    assert len(CAMERA_MOVES) == CAMERA_MOVES_TOTAL
    assert len(set(CAMERA_MOVES)) == len(CAMERA_MOVES)
    assert CAMERA_MOVES == (
        "snorricam",
        "robot-arm",
        "tilt-up",
        "rack-focus",
        "tilt-down",
        "pov",
        "pan-left",
        "crane-up",
        "pan-right",
        "crane-down",
        "side-tracking",
        "pedestal-up",
        "pedestal-down",
        "handheld",
        "tracking",
        "drone-orbit",
        "dolly-zoom",
        "aerial-pullback",
        "static-shot",
        "bullet-time",
        "whip-pan",
        "slow-zoom-in",
        "arc-left",
        "slow-zoom-out",
        "arc-right",
        "truck-right",
        "dolly-in",
        "truck-left",
        "dolly-out",
        "slider-right",
        "crush-zoom",
        "slider-left",
        "helicopter-shot",
    )


def test_move_tag_prefix_is_hash():
    assert MOVE_TAG_PREFIX == "#"


def test_api_reference_token_is_one_based_image_form():
    assert API_REFERENCE_TOKEN.format(n=1) == "<<<image_1>>>"
    assert API_REFERENCE_TOKEN.format(n=7) == "<<<image_7>>>"


@pytest.mark.parametrize("move", CAMERA_MOVES)
def test_every_documented_move_is_recognised(move):
    resolution = resolve_move_tags(f"a shot {MOVE_TAG_PREFIX}{move}")
    assert resolution.moves == [move]
    assert resolution.unknown == []
    assert resolution.ok is True


# --------------------------------------------------------------------------
# parse_move_tags -- order, dedup, verbatim
# --------------------------------------------------------------------------


def test_a_single_move_is_extracted_and_removed_from_the_text():
    clean, moves = parse_move_tags("a woman walks #tracking into the diner")
    assert clean == "a woman walks into the diner"
    assert moves == ["tracking"]


def test_stacked_moves_keep_their_order():
    clean, moves = parse_move_tags("#helicopter-shot then #tracking")
    assert clean == "then"
    assert moves == ["helicopter-shot", "tracking"]


def test_duplicate_moves_collapse_and_keep_first_position():
    clean, moves = parse_move_tags("a #tracking b #crane-up c #tracking")
    assert clean == "a b c"
    assert moves == ["tracking", "crane-up"]


def test_duplicates_collapse_case_insensitively_keeping_the_first_spelling():
    _, moves = parse_move_tags("#tracking #TRACKING")
    assert moves == ["tracking"]


def test_a_tag_free_prompt_is_returned_verbatim():
    text = "a woman walks into the diner, slowly."
    clean, moves = parse_move_tags(text)
    assert clean == text
    assert moves == []


def test_an_empty_prompt_is_handled():
    assert parse_move_tags("") == ("", [])
    assert parse_move_tags(None) == ("", [])


def test_a_hex_colour_is_not_a_move_tag():
    # Uppercase hex must not parse: move names are lowercase slugs.
    clean, moves = parse_move_tags("a wall in #E36332 and #FEA63C")
    assert moves == []
    assert clean == "a wall in #E36332 and #FEA63C"


def test_a_hash_glued_to_a_word_is_not_a_tag():
    clean, moves = parse_move_tags("he writes C# and shot#1")
    assert moves == []
    assert clean == "he writes C# and shot#1"


def test_a_hash_glued_to_an_underscore_or_hyphen_is_not_a_tag():
    """The separator set is `_` and `-` as well as word characters.

    `_` is not alphanumeric, so a check that only tested `isalnum()` would let
    `shot_#tracking` through and invent a move out of the middle of a word.
    """
    for text in ("shot_#tracking", "shot-#tracking", "x_#tracking"):
        clean, moves = parse_move_tags(text)
        assert moves == [], text
        assert clean == text


def test_a_hash_at_the_very_end_is_not_a_tag():
    """There is no name after it, and reading one would run off the string."""
    clean, moves = parse_move_tags("a #")
    assert moves == []
    assert clean == "a #"


def test_a_hash_followed_by_a_digit_is_not_a_tag():
    """Move names start with a letter; `#1` is a shot number, not a move."""
    for text in ("a #1", "a #2 and #3"):
        clean, moves = parse_move_tags(text)
        assert moves == [], text
        assert clean == text


def test_a_hash_followed_by_a_hyphen_is_not_a_tag():
    """A leading hyphen is not the start of a move name."""
    clean, moves = parse_move_tags("a #-tracking")
    assert moves == []
    assert clean == "a #-tracking"


def test_an_email_is_not_an_element_tag_and_does_not_break_move_parsing():
    # parse_element_tags handles the email case; this asserts prompt.py inherits
    # that rather than reimplementing it.
    resolution = resolve_move_tags("nathaniel@example.com walks #whip-pan")
    assert resolution.moves == ["whip-pan"]
    assert resolution.clean_prompt == "nathaniel@example.com walks"


def test_a_trailing_hyphen_is_trimmed_from_a_move_name():
    _, moves = parse_move_tags("#tracking- then")
    assert moves == ["tracking"]


# --------------------------------------------------------------------------
# resolve_move_tags -- unknown is a value, not an exception
# --------------------------------------------------------------------------


def test_an_unknown_move_is_reported_not_dropped():
    resolution = resolve_move_tags("a shot #moonwalk")
    assert resolution.moves == []
    assert resolution.unknown == ["moonwalk"]
    assert resolution.ok is False


def test_known_and_unknown_moves_are_separated_in_order():
    resolution = resolve_move_tags("#tracking #moonwalk #crane-up #robot")
    assert resolution.moves == ["tracking", "crane-up"]
    assert resolution.unknown == ["moonwalk", "robot"]
    assert resolution.ok is False


def test_no_moves_at_all_is_ok():
    resolution = resolve_move_tags("just prose")
    assert resolution.moves == []
    assert resolution.unknown == []
    assert resolution.ok is True


def test_resolution_to_dict_has_the_documented_keys():
    resolution = resolve_move_tags("a shot #tracking #moonwalk")
    assert resolution.to_dict() == {
        "clean_prompt": "a shot",
        "moves": ["tracking"],
        "unknown": ["moonwalk"],
        "ok": False,
    }


def test_resolution_tag_string_renders_recognised_moves_only():
    resolution = resolve_move_tags("#tracking #moonwalk #crane-up")
    assert resolution.tag_string() == "#tracking #crane-up"


def test_move_summary_when_there_are_no_moves():
    assert move_summary(resolve_move_tags("prose")) == (
        "OK - no #camera-move tags in prompt"
    )


def test_move_summary_when_all_moves_are_known():
    assert move_summary(resolve_move_tags("#helicopter-shot #tracking")) == (
        "OK - 2 move(s) in order: helicopter-shot then tracking"
    )


def test_move_summary_when_a_move_is_unknown():
    assert move_summary(resolve_move_tags("#tracking #moonwalk")) == (
        "moves - recognised: tracking; unknown: moonwalk"
    )


# --------------------------------------------------------------------------
# MoveStack
# --------------------------------------------------------------------------


def test_move_stack_preserves_order():
    stack = MoveStack(["helicopter-shot", "tracking"])
    assert stack.moves == ["helicopter-shot", "tracking"]
    assert len(stack) == 2


def test_move_stack_collapses_duplicates_keeping_first_position():
    stack = MoveStack(["tracking", "crane-up", "tracking"])
    assert stack.moves == ["tracking", "crane-up"]


def test_move_stack_rejects_an_unknown_move():
    with pytest.raises(ValueError) as excinfo:
        MoveStack(["moonwalk"])
    assert "'moonwalk'" in str(excinfo.value)


def test_move_stack_tag_string_round_trips():
    stack = MoveStack(["helicopter-shot", "tracking"])
    assert stack.tag_string() == "#helicopter-shot #tracking"
    clean, moves = parse_move_tags(stack.tag_string())
    assert moves == stack.moves
    assert clean == ""


def test_an_empty_move_stack_renders_an_empty_string():
    assert MoveStack().tag_string() == ""
    assert MoveStack().is_empty() is True
    assert MoveStack().summary() == "move stack: empty"


def test_move_stack_summary_names_the_order():
    assert MoveStack(["helicopter-shot", "tracking"]).summary() == (
        "move stack: 2 move(s), in order - helicopter-shot then tracking"
    )


def test_move_stack_to_dict():
    assert MoveStack(["tracking"]).to_dict() == {"moves": ["tracking"], "count": 1}


def test_move_stack_round_trips_through_dict():
    stack = MoveStack(["drone-orbit", "arc-left"])
    assert MoveStack.from_dict(stack.to_dict()).moves == stack.moves


def test_move_stack_from_dict_rejects_an_unknown_field():
    with pytest.raises(ValueError):
        MoveStack.from_dict({"moves": [], "nope": 1})


def test_move_stack_from_dict_rejects_a_non_list():
    with pytest.raises(ValueError):
        MoveStack.from_dict({"moves": "tracking"})


def test_move_stack_is_iterable():
    assert list(MoveStack(["tracking", "crane-up"])) == ["tracking", "crane-up"]


# --------------------------------------------------------------------------
# compose_prompt -- the two jobs, and nothing else
# --------------------------------------------------------------------------


def _registry(*names):
    return ElementRegistry(
        [Element(name, "character", f"/assets/{name}.png") for name in names]
    )


def test_compose_with_no_elements_and_no_moves_returns_the_action_alone():
    composed = compose_prompt("a woman walks into the diner")
    assert composed.final_prompt == "a woman walks into the diner"
    assert composed.element_tags == []
    assert composed.move_tags == []
    assert composed.panel_fragment == ""
    assert composed.attachments == []
    assert composed.unresolved == []


def test_compose_adds_no_prose_of_its_own():
    # The exact string, typed by hand. Any inserted word fails this.
    composed = compose_prompt("a woman walks into the diner")
    assert composed.final_prompt == "a woman walks into the diner"
    for banned in ("cinematic", "8k", "masterpiece", "beautiful", "high quality"):
        assert banned not in composed.final_prompt


def test_compose_with_one_element_and_one_move():
    composed = compose_prompt(
        "@tamsin, walks into the diner #tracking", None, _registry("tamsin")
    )
    assert composed.element_tags == ["tamsin"]
    assert composed.move_tags == ["tracking"]
    assert composed.final_prompt == "walks into the diner @tamsin #tracking"
    assert composed.unresolved == []


def test_compose_with_many_elements_and_many_moves():
    composed = compose_prompt(
        "@tamsin, and @oscar, walk in #helicopter-shot #tracking",
        None,
        _registry("tamsin", "oscar"),
    )
    assert composed.element_tags == ["tamsin", "oscar"]
    assert composed.move_tags == ["helicopter-shot", "tracking"]
    # The comma after "@oscar," survives as an interior comma. That is
    # parse_element_tags' documented behaviour -- it trims *edge* punctuation,
    # not interior punctuation -- and prompt.py inherits it rather than
    # second-guessing the shared parser. Asserted so a future change to the
    # shared parser is visible here.
    assert composed.final_prompt == (
        "and, walk in @tamsin @oscar #helicopter-shot #tracking"
    )


def test_compose_attachments_are_one_based_api_tokens_in_order():
    composed = compose_prompt(
        "@tamsin, and @oscar, walk in", None, _registry("tamsin", "oscar")
    )
    assert composed.attachments == [
        {"token": "<<<image_1>>>", "name": "tamsin", "asset_path": "/assets/tamsin.png"},
        {"token": "<<<image_2>>>", "name": "oscar", "asset_path": "/assets/oscar.png"},
    ]


def test_compose_with_no_elements_produces_no_attachments():
    composed = compose_prompt("a woman walks", None, _registry())
    assert composed.attachments == []
    assert composed.element_tags == []


def test_compose_reports_a_missing_element_as_unresolved():
    composed = compose_prompt("@nobody, walks in", None, _registry("tamsin"))
    assert composed.element_tags == []
    assert composed.unresolved == ["nobody"]
    assert composed.is_ok() is False


def test_compose_reports_an_unknown_move_as_unresolved():
    composed = compose_prompt("a shot #moonwalk")
    assert composed.move_tags == []
    assert composed.unresolved == ["moonwalk"]
    assert composed.is_ok() is False


def test_compose_reports_both_kinds_of_unresolved_together():
    composed = compose_prompt("@nobody, walks #moonwalk", None, _registry("tamsin"))
    assert composed.unresolved == ["nobody", "moonwalk"]
    assert composed.is_ok() is False


def test_compose_without_a_registry_reports_tags_as_unresolved_rather_than_assuming():
    composed = compose_prompt("@tamsin, walks in", None, None)
    assert composed.element_tags == ["tamsin"]
    assert composed.unresolved == ["tamsin"]
    assert composed.is_ok() is False


def test_compose_accepts_a_plain_iterable_of_elements():
    composed = compose_prompt(
        "@tamsin, walks in", None, [Element("tamsin", "character", "/a/t.png")]
    )
    assert composed.element_tags == ["tamsin"]
    assert composed.unresolved == []


def test_compose_accepts_a_move_stack():
    composed = compose_prompt("a woman walks", None, None, MoveStack(["whip-pan"]))
    assert composed.move_tags == ["whip-pan"]
    assert composed.final_prompt == "a woman walks #whip-pan"


def test_compose_accepts_a_plain_iterable_of_moves():
    composed = compose_prompt("a woman walks", None, None, ["tracking", "arc-left"])
    assert composed.move_tags == ["tracking", "arc-left"]


def test_compose_does_not_duplicate_a_move_present_in_both_text_and_stack():
    composed = compose_prompt(
        "a woman walks #tracking", None, None, MoveStack(["tracking"])
    )
    assert composed.move_tags == ["tracking"]
    assert composed.final_prompt == "a woman walks #tracking"


def test_compose_with_an_all_auto_panel_adds_nothing():
    from cinematographer.director import DirectorPanel

    composed = compose_prompt("a woman walks", DirectorPanel.defaults())
    assert composed.panel_fragment == ""
    assert composed.final_prompt == "a woman walks"


def test_compose_includes_the_panel_fragment_between_action_and_tags():
    from cinematographer.director import DirectorPanel, FilmSetup

    composed = compose_prompt(
        "@tamsin, walks in #tracking",
        DirectorPanel(film=FilmSetup(genre="noir")),
        _registry("tamsin"),
    )
    assert composed.panel_fragment == "genre noir"
    assert composed.final_prompt == "walks in genre noir @tamsin #tracking"


def test_compose_final_prompt_is_ascii_only():
    composed = compose_prompt("a woman named Zoë walks")
    assert composed.final_prompt.isascii()


def test_compose_to_dict_has_the_documented_keys():
    composed = compose_prompt("a woman walks #tracking")
    assert set(composed.to_dict()) == {
        "action",
        "element_tags",
        "move_tags",
        "panel_fragment",
        "final_prompt",
        "attachments",
        "unresolved",
    }


def test_compose_to_dict_copies_attachments_rather_than_aliasing():
    composed = compose_prompt("@tamsin, walks", None, _registry("tamsin"))
    snapshot = composed.to_dict()
    snapshot["attachments"][0]["name"] = "mutated"
    assert composed.attachments[0]["name"] == "tamsin"


def test_compose_keeps_the_raw_action_on_the_result():
    composed = compose_prompt("@tamsin, walks #tracking", None, _registry("tamsin"))
    assert composed.action == "@tamsin, walks #tracking"


def test_composed_prompt_is_ok_when_everything_resolves():
    composed = compose_prompt("@tamsin, walks #tracking", None, _registry("tamsin"))
    assert composed.is_ok() is True


def test_module_exposes_the_documented_names():
    for name in (
        "CAMERA_MOVES",
        "parse_move_tags",
        "MoveStack",
        "compose_prompt",
        "ComposedPrompt",
        "MoveResolution",
        "resolve_move_tags",
    ):
        assert hasattr(prompt, name), name


def test_composed_prompt_defaults_are_empty():
    composed = ComposedPrompt(action="x")
    assert composed.element_tags == []
    assert composed.move_tags == []
    assert composed.attachments == []
    assert composed.unresolved == []
    assert composed.is_ok() is True


def test_move_resolution_defaults_are_ok():
    resolution = MoveResolution(clean_prompt="x")
    assert resolution.moves == []
    assert resolution.unknown == []
    assert resolution.ok is True
