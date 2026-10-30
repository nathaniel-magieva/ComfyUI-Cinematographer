"""The Element (stage 1.3) and POST plan (stage 5) nodes.

Why this file exists
--------------------
These five nodes had no regression guard. They were verified once by hand, and a
hand check does not fail when someone else changes the engine underneath them.
That is not hypothetical: ``elements.py`` was edited while this pack was being
built, and the only reason the interaction was noticed is that a throwaway
script happened to exercise it. A test is what makes that a failure instead of a
surprise.

Two properties are worth more than the rest, and they are the reason this file
is organised the way it is:

* **Nothing here touches a pixel.** ``CinemaExtend`` and ``CinemaEdit`` emit
  plans. Extending is generation and editing is regional regeneration; neither
  is a tensor operation, so neither gets an apply node. The tests assert the
  return types contain no IMAGE.
* **"Not measured" is not the same as "measured as empty."** An Element saved
  with no palette keeps ``palette=[]`` rather than being handed a default,
  because an invented palette would make a drift measurement look like a pass.

The engine's own behaviour is tested in ``test_elements.py`` and
``test_post.py``. This file tests the wiring.
"""

import json
import os

import pytest

from cinematographer import elements
from cinematographer import nodes
from cinematographer import post


@pytest.fixture()
def registry_path(tmp_path):
    return str(tmp_path / "elements.json")


def _save(registry_path, name="tamsin", category="character", **kwargs):
    kwargs.setdefault(
        "image_path", os.path.join(os.path.dirname(registry_path), f"{name}.png")
    )
    return nodes.CinemaElementSave().save(name, category, registry_path=registry_path, **kwargs)


# ==========================================================================
# CinemaElementSave
# ==========================================================================


def test_save_is_an_output_node():
    """A save node whose output nothing consumes would be pruned from the graph."""
    assert nodes.CinemaElementSave.OUTPUT_NODE is True


def test_no_other_node_claims_to_be_an_output_node():
    others = [
        name
        for name, cls in nodes.NODE_CLASS_MAPPINGS.items()
        if cls.OUTPUT_NODE and name != "CinemaElementSave"
    ]
    assert others == []


def test_save_writes_a_sidecar_next_to_the_asset(registry_path):
    _, sidecar, _ = _save(registry_path)
    assert sidecar.endswith(elements.ELEMENT_SIDECAR_SUFFIX)
    assert os.path.isfile(sidecar)


def test_save_adds_the_element_to_the_registry(registry_path):
    _save(registry_path)
    assert os.path.isfile(registry_path)
    assert elements.ElementRegistry.load(registry_path).names() == ["tamsin"]


def test_save_returns_the_element_as_json(registry_path):
    element_json, _, _ = _save(registry_path, description="the lead")
    data = json.loads(element_json)
    assert data["name"] == "tamsin"
    assert data["category"] == "character"
    assert data["description"] == "the lead"


def test_the_category_dropdown_is_the_engine_taxonomy(registry_path):
    dropdown = nodes.CinemaElementSave.INPUT_TYPES()["required"]["category"][0]
    assert tuple(dropdown) == tuple(elements.ELEMENT_CATEGORIES)


def test_a_category_outside_the_taxonomy_is_rejected(registry_path):
    with pytest.raises(ValueError):
        _save(registry_path, category="vehicle")


def test_a_duplicate_name_is_rejected_rather_than_silently_overwritten(registry_path):
    """Two Elements with one name would make `@name` ambiguous."""
    _save(registry_path)
    with pytest.raises(ValueError, match="duplicate"):
        _save(registry_path)


def test_save_accepts_a_comma_separated_palette(registry_path):
    element_json, _, _ = _save(registry_path, palette="0.82,0.61,0.55")
    assert json.loads(element_json)["palette"] == [[0.82, 0.61, 0.55]]


def test_save_accepts_several_semicolon_separated_colours(registry_path):
    element_json, _, _ = _save(
        registry_path, palette="0.82,0.61,0.55;0.11,0.09,0.08"
    )
    assert json.loads(element_json)["palette"] == [
        [0.82, 0.61, 0.55],
        [0.11, 0.09, 0.08],
    ]


def test_an_empty_palette_stays_empty_and_is_not_given_a_default(registry_path):
    """An invented palette would make a drift measurement look like a pass."""
    element_json, _, _ = _save(registry_path, palette="")
    assert json.loads(element_json)["palette"] == []


def test_a_malformed_palette_is_a_hard_error(registry_path):
    for bad in ("0.82,0.61", "0.82,0.61,0.55,0.1", "red,green,blue"):
        with pytest.raises(ValueError):
            _save(registry_path, name=f"e{bad!r}", palette=bad)


def test_a_palette_channel_outside_zero_to_one_is_rejected(registry_path):
    """Colours are normalised RGB, so 255 is not a colour here."""
    with pytest.raises(ValueError, match="0..1"):
        _save(registry_path, palette="255,128,0")


def test_bbox_is_only_recorded_when_has_bbox_is_set(registry_path):
    """`unset` must be distinguishable from `a box at the origin`."""
    element_json, _, _ = _save(registry_path, has_bbox=False)
    assert json.loads(element_json)["bbox"] is None


def test_has_bbox_records_the_box(registry_path):
    element_json, _, _ = _save(
        registry_path,
        has_bbox=True,
        bbox_min_x=-0.5,
        bbox_min_y=-0.9,
        bbox_max_x=0.5,
        bbox_max_y=0.9,
    )
    assert json.loads(element_json)["bbox"] == [-0.5, -0.9, 0.5, 0.9]


def test_an_inverted_bbox_is_rejected(registry_path):
    with pytest.raises(ValueError, match="inverted"):
        _save(
            registry_path,
            has_bbox=True,
            bbox_min_x=0.5,
            bbox_min_y=-0.5,
            bbox_max_x=-0.5,
            bbox_max_y=0.5,
        )


def test_a_saved_element_with_palette_and_bbox_can_be_measured(registry_path):
    """This is the point of the palette/bbox plumbing.

    `character_record_from_element` raises for an Element with neither, so an
    Element saved without them feeds the prompt but cannot be measured.
    """
    _save(registry_path, palette="0.82,0.61,0.55", has_bbox=True)
    element = elements.ElementRegistry.load(registry_path).get("tamsin")
    record = elements.character_record_from_element(element)
    assert record is not None


def test_an_element_without_a_palette_cannot_be_measured(registry_path):
    """The engine raises rather than substituting a default. That is correct."""
    _save(registry_path)
    element = elements.ElementRegistry.load(registry_path).get("tamsin")
    with pytest.raises(ValueError, match="no palette"):
        elements.character_record_from_element(element)


# ==========================================================================
# CinemaElementLoad
# ==========================================================================


def test_load_finds_a_saved_element(registry_path):
    _save(registry_path)
    asset_path, element_json, found = nodes.CinemaElementLoad().load(
        "tamsin", "any", registry_path=registry_path
    )
    assert found is True
    assert asset_path.endswith("tamsin.png")
    assert json.loads(element_json)["name"] == "tamsin"


def test_load_filters_by_category(registry_path):
    _save(registry_path, name="tamsin", category="character")
    _save(registry_path, name="the-diner", category="location")
    assert nodes.CinemaElementLoad().load("tamsin", "character", registry_path=registry_path)[2]
    assert not nodes.CinemaElementLoad().load("tamsin", "location", registry_path=registry_path)[2]


def test_load_with_any_ignores_the_category(registry_path):
    _save(registry_path, name="the-diner", category="location")
    assert nodes.CinemaElementLoad().load("the-diner", "any", registry_path=registry_path)[2]


def test_a_missing_element_is_reported_not_raised(registry_path):
    """Same contract as an unresolved `@Name`: a value, not an exception."""
    _save(registry_path)
    asset_path, element_json, found = nodes.CinemaElementLoad().load(
        "nobody", "any", registry_path=registry_path
    )
    assert found is False
    assert asset_path == ""
    assert json.loads(element_json) == {}


def test_a_missing_registry_is_reported_not_raised(registry_path):
    asset_path, _, found = nodes.CinemaElementLoad().load(
        "tamsin", "any", registry_path=registry_path
    )
    assert found is False
    assert asset_path == ""


def test_the_load_category_dropdown_offers_any_plus_the_taxonomy():
    dropdown = nodes.CinemaElementLoad.INPUT_TYPES()["required"]["category"][0]
    assert tuple(dropdown) == ("any",) + tuple(elements.ELEMENT_CATEGORIES)


# ==========================================================================
# CinemaElementList
# ==========================================================================


def test_list_all_returns_every_name(registry_path):
    _save(registry_path, name="tamsin", category="character")
    _save(registry_path, name="the-diner", category="location")
    names_json, count, _ = nodes.CinemaElementList().list_elements(
        "all", registry_path=registry_path
    )
    assert count == 2
    assert sorted(json.loads(names_json)) == ["tamsin", "the-diner"]


def test_list_filters_by_category(registry_path):
    _save(registry_path, name="tamsin", category="character")
    _save(registry_path, name="the-diner", category="location")
    names_json, count, _ = nodes.CinemaElementList().list_elements(
        "character", registry_path=registry_path
    )
    assert count == 1
    assert json.loads(names_json) == ["tamsin"]


def test_list_of_an_empty_category_is_empty_not_an_error(registry_path):
    _save(registry_path, name="tamsin", category="character")
    names_json, count, summary = nodes.CinemaElementList().list_elements(
        "prop", registry_path=registry_path
    )
    assert (json.loads(names_json), count) == ([], 0)
    assert "no Elements" in summary


def test_list_of_a_missing_registry_is_empty_not_an_error(registry_path):
    names_json, count, _ = nodes.CinemaElementList().list_elements(
        "all", registry_path=registry_path
    )
    assert (json.loads(names_json), count) == ([], 0)


def test_the_all_sentinel_never_reaches_by_category(registry_path):
    """`all` is the node's own sentinel, not an Element category.

    The engine validates the category it is handed and raises on an unknown one,
    so passing the sentinel through would make "list everything" fail. This
    pins the branch that avoids it.
    """
    _save(registry_path)
    assert "all" not in elements.ELEMENT_CATEGORIES
    with pytest.raises(ValueError):
        elements.ElementRegistry.load(registry_path).by_category("all")
    # ...and the node still works, because it does not do that.
    assert nodes.CinemaElementList().list_elements("all", registry_path=registry_path)[1] == 1


def test_the_list_category_dropdown_offers_all_plus_the_taxonomy():
    dropdown = nodes.CinemaElementList.INPUT_TYPES()["required"]["category"][0]
    assert tuple(dropdown) == ("all",) + tuple(elements.ELEMENT_CATEGORIES)


# ==========================================================================
# CinemaExtend -- a plan, not a render
# ==========================================================================


def test_extend_emits_a_plan_and_never_an_image():
    """Extending is generation. There is no tensor to operate on."""
    assert "IMAGE" not in nodes.CinemaExtend.RETURN_TYPES
    assert nodes.CinemaExtend.OUTPUT_NODE is False


def test_extend_returns_the_plan_the_overlap_and_a_summary():
    extend_json, overlap_s, summary = nodes.CinemaExtend().extend("sequel", 8.0, 24)
    data = json.loads(extend_json)
    assert data["mode"] == "sequel"
    assert data["duration_s"] == 8.0
    assert data["overlap_frames"] == 24
    assert overlap_s == pytest.approx(1.0)  # 24 frames at 24 fps
    assert isinstance(summary, str)


def test_the_extend_mode_dropdown_is_the_engine_constant():
    dropdown = nodes.CinemaExtend.INPUT_TYPES()["required"]["mode"][0]
    assert tuple(dropdown) == tuple(post.EXTEND_MODES)


def test_the_extend_duration_range_is_the_engine_constant():
    widget = nodes.CinemaExtend.INPUT_TYPES()["required"]["duration_s"][1]
    assert widget["min"] == post.EXTEND_DURATION_RANGE[0]
    assert widget["max"] == post.EXTEND_DURATION_RANGE[1]


def test_the_overlap_ceiling_is_the_engine_constant():
    widget = nodes.CinemaExtend.INPUT_TYPES()["required"]["overlap_frames"][1]
    assert widget["max"] == post.EXTEND_OVERLAP_MAX_FRAMES


def test_extend_accepts_both_ends_of_the_duration_range():
    low, high = post.EXTEND_DURATION_RANGE
    for duration in (low, high):
        assert nodes.CinemaExtend().extend("sequel", duration, 0)[0]


def test_extend_rejects_a_duration_outside_the_range():
    low, high = post.EXTEND_DURATION_RANGE
    for duration in (low - 1.0, high + 1.0):
        with pytest.raises(ValueError):
            nodes.CinemaExtend().extend("sequel", duration, 0)


def test_extend_rejects_a_mode_the_engine_does_not_know():
    with pytest.raises(ValueError):
        nodes.CinemaExtend().extend("sidequel", 5.0, 0)


def test_extend_rejects_an_overlap_beyond_the_ceiling():
    with pytest.raises(ValueError):
        nodes.CinemaExtend().extend("sequel", 5.0, post.EXTEND_OVERLAP_MAX_FRAMES + 1)


def test_the_extend_summary_does_not_claim_to_have_extended_anything():
    _, _, summary = nodes.CinemaExtend().extend("sequel", 8.0, 24)
    assert "plan" in summary.lower()


# ==========================================================================
# CinemaEdit -- a plan, not a regeneration
# ==========================================================================


def test_edit_emits_a_plan_and_never_an_image():
    """Editing is regional regeneration. There is no tensor to operate on."""
    assert "IMAGE" not in nodes.CinemaEdit.RETURN_TYPES
    assert nodes.CinemaEdit.OUTPUT_NODE is False


def test_edit_returns_the_plan_whether_it_is_in_frame_and_a_summary():
    edit_json, in_frame, summary = nodes.CinemaEdit().edit(
        "the sign", -0.2, -0.2, 0.2, 0.2, "make it neon"
    )
    data = json.loads(edit_json)
    assert data["regions"][0]["label"] == "the sign"
    assert data["regions"][0]["prompt"] == "make it neon"
    assert in_frame is True
    assert isinstance(summary, str)


def test_a_region_outside_the_frame_is_flagged_not_rejected():
    """The user should see that the box misses, not get an exception."""
    _, in_frame, summary = nodes.CinemaEdit().edit("off", -0.2, 1.4, 0.2, 1.8)
    assert in_frame is False
    assert "OUTSIDE" in summary.upper()


def test_the_frame_boundary_is_probed_from_both_sides():
    """±1 is the edge of NDC space; just inside is legal, just outside is not."""
    assert nodes.CinemaEdit().edit("edge", -1.0, -1.0, 1.0, 1.0)[1] is True
    assert nodes.CinemaEdit().edit("past", -1.0, -1.0, 1.0, 1.01)[1] is False


def test_edit_rejects_an_inverted_box():
    with pytest.raises(ValueError):
        nodes.CinemaEdit().edit("bad", 0.5, -0.5, -0.5, 0.5)


def test_the_edit_summary_does_not_claim_to_have_edited_anything():
    _, _, summary = nodes.CinemaEdit().edit("the sign", -0.2, -0.2, 0.2, 0.2)
    assert "plan" in summary.lower()


# ==========================================================================
# the POST group as a whole
# ==========================================================================


def test_only_grade_apply_in_the_post_group_touches_pixels():
    post_nodes = {
        "CinemaGrade": nodes.CinemaGrade,
        "CinemaGradeApply": nodes.CinemaGradeApply,
        "CinemaExtend": nodes.CinemaExtend,
        "CinemaEdit": nodes.CinemaEdit,
    }
    for name, cls in post_nodes.items():
        if name == "CinemaGradeApply":
            assert cls.RETURN_TYPES[0] == "IMAGE"
        else:
            assert "IMAGE" not in cls.RETURN_TYPES, name


def test_grade_and_extend_and_edit_all_emit_plans_not_results():
    """Wording matters: a plan is a description, and must not read as a result."""
    for cls in (nodes.CinemaGrade, nodes.CinemaExtend, nodes.CinemaEdit):
        assert "plan" in cls.DESCRIPTION.lower(), cls.__name__
