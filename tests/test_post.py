"""Post-stage tests — every range probed from both sides, and the catch pinned.

Why this file exists
--------------------

``post.py`` carries two things that are easy to get wrong and expensive to get
wrong:

* **the architectural catch** — in the real product Extend and Edit are *not*
  Cinema Studio endpoints, they are separate Seedance calls. The module docstring
  has to say so, and the tests pin the docstring so a later edit cannot quietly
  drop the disclaimer;
* **the invented ranges** — the source documents the seven grade control *names*
  and nothing about their scale, so every range, unit and neutral point in
  ``GRADE_RANGES`` / ``GRADE_NEUTRAL`` is our choice. That makes them exactly the
  kind of unconstrained constant this project treats as a defect, so every one is
  probed at its minimum, at its maximum, and one step past each.

Every expected value here is hand-computed from the definition, never read back
from the code under test. The constants are pinned as literal tuples and dicts,
so moving one breaks a test rather than quietly changing behaviour.

``apply_grade`` is a **description**, not a pixel operation, and the tests hold
that line: they assert the returned deltas, and there is no image anywhere in
this file to grade.
"""

import pytest

from cinematographer import post
from cinematographer.geometry import OVERALL_PASS_WEIGHT
from cinematographer.post import (
    DEFAULT_EXTEND_DURATION_S,
    DEFAULT_FPS,
    EXTEND_DURATION_RANGE,
    EXTEND_MODES,
    EXTEND_OVERLAP_MAX_FRAMES,
    GRADE_NEUTRAL,
    GRADE_PARAMS,
    GRADE_RANGES,
    POST_RULES,
    POST_RULE_WEIGHTS,
    POST_STAGES,
    EditPlan,
    EditRegion,
    ExtendPlan,
    GradePlan,
    GradeSettings,
    PostPlan,
    apply_grade,
    grade_range,
    post_summary,
)

# --------------------------------------------------------------------------
# Constants — pinned as literals, so moving one breaks a test
# --------------------------------------------------------------------------


def test_grade_params_are_the_seven_documented_controls():
    assert GRADE_PARAMS == (
        "temperature",
        "contrast",
        "saturation",
        "sharpness",
        "film_grain",
        "highlights",
        "exposure",
    )


def test_grade_neutral_is_zero_for_every_control():
    assert GRADE_NEUTRAL == {
        "temperature": 0.0,
        "contrast": 0.0,
        "saturation": 0.0,
        "sharpness": 0.0,
        "film_grain": 0.0,
        "highlights": 0.0,
        "exposure": 0.0,
    }


def test_grade_ranges_are_pinned():
    """These are invented — the source documents the names, not the scale."""
    assert GRADE_RANGES == {
        "temperature": (-1.0, 1.0),
        "contrast": (-1.0, 1.0),
        "saturation": (-1.0, 1.0),
        "sharpness": (0.0, 1.0),
        "film_grain": (0.0, 1.0),
        "highlights": (-1.0, 1.0),
        "exposure": (-2.0, 2.0),
    }


def test_extend_modes_are_pinned():
    assert EXTEND_MODES == ("sequel", "prequel")


def test_extend_duration_range_is_the_documented_generation_bar():
    """Sourced: the generation bar documents a 4-30 s duration."""
    assert EXTEND_DURATION_RANGE == (4.0, 30.0)


def test_extend_defaults_are_pinned():
    assert DEFAULT_EXTEND_DURATION_S == 5.0
    assert DEFAULT_FPS == 24.0
    assert EXTEND_OVERLAP_MAX_FRAMES == 48


def test_post_stages_are_pinned_in_order():
    assert POST_STAGES == ("grade", "extend", "edit")


def test_post_rules_are_pinned_in_order():
    assert POST_RULES == (
        "grade_in_range",
        "extend_in_range",
        "edit_prompt_present",
        "edit_region_in_frame",
    )


def test_post_rule_weights_are_pinned():
    assert POST_RULE_WEIGHTS == {
        "grade_in_range": 1.0,
        "extend_in_range": 1.0,
        "edit_prompt_present": 1.0,
        "edit_region_in_frame": 0.5,
    }


def test_gating_split_is_the_documented_one():
    """Three rules gate; a region spilling past the frame is reported only."""
    gating = [r for r in POST_RULES if POST_RULE_WEIGHTS[r] >= OVERALL_PASS_WEIGHT]
    assert gating == ["grade_in_range", "extend_in_range", "edit_prompt_present"]


def test_overall_pass_weight_is_geometrys_object_not_a_copy():
    assert post.OVERALL_PASS_WEIGHT is OVERALL_PASS_WEIGHT
    assert OVERALL_PASS_WEIGHT == 0.8


def test_gates_boundary_is_inclusive():
    assert post._gates(OVERALL_PASS_WEIGHT) is True
    assert post._gates(OVERALL_PASS_WEIGHT + 0.001) is True
    assert post._gates(OVERALL_PASS_WEIGHT - 0.001) is False
    assert post._gates(0.0) is False


def test_the_architectural_catch_is_stated_in_the_module_docstring():
    """Extend and Edit are Seedance calls, not Cinema Studio endpoints.

    Pinned so a later edit cannot quietly drop the disclaimer.
    """
    docstring = post.__doc__ or ""
    assert "not Cinema Studio endpoints" in docstring
    assert "Seedance" in docstring
    assert "never touches a pixel" in docstring


def test_grade_range_helper():
    assert grade_range("temperature") == (-1.0, 1.0)
    assert grade_range("sharpness") == (0.0, 1.0)
    assert grade_range("exposure") == (-2.0, 2.0)


def test_grade_range_rejects_an_unknown_control():
    with pytest.raises(ValueError, match="unknown grade control"):
        grade_range("gamma")


# --------------------------------------------------------------------------
# GradeSettings — every range boundary, from both sides
# --------------------------------------------------------------------------


def test_neutral_settings_are_all_zero():
    settings = GradeSettings()
    assert settings.to_dict() == {
        "temperature": 0.0,
        "contrast": 0.0,
        "saturation": 0.0,
        "sharpness": 0.0,
        "film_grain": 0.0,
        "highlights": 0.0,
        "exposure": 0.0,
    }


def test_neutral_classmethod_matches_the_default_constructor():
    assert GradeSettings.neutral() == GradeSettings()
    assert GradeSettings.neutral().is_neutral() is True


def test_is_neutral_is_false_when_any_control_moves():
    assert GradeSettings(temperature=0.001).is_neutral() is False
    assert GradeSettings(exposure=-2.0).is_neutral() is False
    assert GradeSettings(film_grain=1.0).is_neutral() is False


@pytest.mark.parametrize("param", list(GRADE_PARAMS))
def test_range_minimum_is_inclusive(param):
    low, _high = GRADE_RANGES[param]
    settings = GradeSettings(**{param: low})
    assert getattr(settings, param) == low


@pytest.mark.parametrize("param", list(GRADE_PARAMS))
def test_range_maximum_is_inclusive(param):
    _low, high = GRADE_RANGES[param]
    settings = GradeSettings(**{param: high})
    assert getattr(settings, param) == high


@pytest.mark.parametrize("param", list(GRADE_PARAMS))
def test_one_step_below_the_minimum_is_rejected(param):
    low, _high = GRADE_RANGES[param]
    with pytest.raises(ValueError, match=param):
        GradeSettings(**{param: low - 0.5})


@pytest.mark.parametrize("param", list(GRADE_PARAMS))
def test_one_step_above_the_maximum_is_rejected(param):
    _low, high = GRADE_RANGES[param]
    with pytest.raises(ValueError, match=param):
        GradeSettings(**{param: high + 0.5})


def test_out_of_range_error_names_the_control_the_value_and_the_range():
    with pytest.raises(ValueError) as excinfo:
        GradeSettings(exposure=2.5)
    message = str(excinfo.value)
    assert "exposure" in message
    assert "2.5" in message
    assert "-2.0..2.0" in message


def test_settings_round_trip_through_dict():
    settings = GradeSettings(
        temperature=0.25,
        contrast=-0.5,
        saturation=0.75,
        sharpness=1.0,
        film_grain=0.1,
        highlights=-0.2,
        exposure=1.5,
    )
    assert GradeSettings.from_dict(settings.to_dict()) == settings


def test_from_dict_fills_missing_controls_with_neutral():
    settings = GradeSettings.from_dict({"temperature": 0.5})
    assert settings.temperature == 0.5
    assert settings.contrast == 0.0
    assert settings.exposure == 0.0


def test_from_dict_ignores_unknown_keys():
    settings = GradeSettings.from_dict({"temperature": 0.5, "gamma": 9.0})
    assert settings.temperature == 0.5


def test_values_are_coerced_to_float():
    settings = GradeSettings(temperature=1)
    assert isinstance(settings.temperature, float)
    assert settings.temperature == 1.0


# --------------------------------------------------------------------------
# apply_grade — a description, never a pixel operation
# --------------------------------------------------------------------------


def test_a_neutral_grade_produces_no_deltas():
    plan = apply_grade(GradeSettings.neutral())
    assert plan.deltas == []
    assert plan.is_noop() is True
    assert plan.summary() == "grade: neutral (no deltas)"


def test_deltas_are_ordered_by_grade_params():
    plan = apply_grade(GradeSettings(exposure=-1.5, temperature=0.3))
    assert plan.deltas == [
        ("temperature", 0.0, 0.3, "up"),
        ("exposure", 0.0, -1.5, "down"),
    ]


def test_direction_is_up_for_a_positive_move_and_down_for_a_negative_one():
    plan = apply_grade(GradeSettings(contrast=-0.25, saturation=0.5))
    assert plan.deltas == [
        ("contrast", 0.0, -0.25, "down"),
        ("saturation", 0.0, 0.5, "up"),
    ]


def test_from_value_is_always_the_neutral_value():
    plan = apply_grade(GradeSettings(sharpness=1.0))
    assert plan.deltas == [("sharpness", 0.0, 1.0, "up")]


@pytest.mark.parametrize(
    "from_value,to_value,expected",
    [
        (0.0, 0.0, "none"),
        (0.5, 0.5, "none"),
        (-1.0, -1.0, "none"),
        (0.0, 0.1, "up"),
        (-1.0, 1.0, "up"),
        (0.0, -0.1, "down"),
        (1.0, -1.0, "down"),
    ],
)
def test_direction_boundary_is_pinned(from_value, to_value, expected):
    """``apply_grade`` never calls this with equal values, so pin it directly."""
    assert post._direction(from_value, to_value) == expected


def test_grade_plan_params_lists_only_the_touched_controls():
    plan = apply_grade(GradeSettings(exposure=-1.5, temperature=0.3))
    assert plan.params() == ["temperature", "exposure"]


def test_grade_plan_to_dict():
    plan = apply_grade(GradeSettings(exposure=-1.5, temperature=0.3))
    assert plan.to_dict() == {
        "deltas": [
            {"param": "temperature", "from": 0.0, "to": 0.3, "direction": "up"},
            {"param": "exposure", "from": 0.0, "to": -1.5, "direction": "down"},
        ],
        "count": 2,
        "is_noop": False,
    }


def test_grade_plan_summary():
    plan = apply_grade(GradeSettings(exposure=-1.5, temperature=0.3))
    assert plan.summary() == (
        "grade: 2 delta(s) - temperature up 0.000->0.300, "
        "exposure down 0.000->-1.500"
    )


def test_an_empty_grade_plan_is_a_noop():
    assert GradePlan().is_noop() is True
    assert GradePlan().params() == []


# --------------------------------------------------------------------------
# ExtendPlan — mode, duration and overlap
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["sequel", "prequel"])
def test_extend_accepts_every_legal_mode(mode):
    assert ExtendPlan(mode=mode).mode == mode


@pytest.mark.parametrize("mode", ["Sequel", "SEQUEL", "midquel", ""])
def test_extend_rejects_an_unknown_mode(mode):
    with pytest.raises(ValueError) as excinfo:
        ExtendPlan(mode=mode)
    message = str(excinfo.value)
    assert repr(mode) in message
    assert "('sequel', 'prequel')" in message


def test_extend_defaults():
    plan = ExtendPlan()
    assert plan.mode == "sequel"
    assert plan.duration_s == 5.0
    assert plan.overlap_frames == 0


@pytest.mark.parametrize("duration", [4.0, 30.0, 5.0])
def test_extend_duration_boundaries_are_inclusive(duration):
    assert ExtendPlan(duration_s=duration).duration_s == duration


@pytest.mark.parametrize("duration", [3.999, 30.001, 0.0, -5.0])
def test_extend_rejects_a_duration_outside_the_range(duration):
    with pytest.raises(ValueError, match="duration_s"):
        ExtendPlan(duration_s=duration)


@pytest.mark.parametrize("overlap", [0, 48, 24])
def test_extend_overlap_boundaries_are_inclusive(overlap):
    assert ExtendPlan(overlap_frames=overlap).overlap_frames == overlap


@pytest.mark.parametrize("overlap", [-1, 49, 1000])
def test_extend_rejects_an_overlap_outside_the_range(overlap):
    with pytest.raises(ValueError, match="overlap_frames"):
        ExtendPlan(overlap_frames=overlap)


@pytest.mark.parametrize(
    "frames,expected_seconds",
    [(0, 0.0), (12, 0.5), (24, 1.0), (48, 2.0)],
)
def test_overlap_seconds_uses_the_film_standard_frame_rate(frames, expected_seconds):
    assert ExtendPlan(overlap_frames=frames).overlap_s == expected_seconds


def test_extend_to_dict():
    plan = ExtendPlan(mode="prequel", duration_s=8.0, overlap_frames=24)
    assert plan.to_dict() == {
        "mode": "prequel",
        "duration_s": 8.0,
        "overlap_frames": 24,
        "overlap_s": 1.0,
    }


# --------------------------------------------------------------------------
# EditRegion / EditPlan
# --------------------------------------------------------------------------


def test_edit_region_to_dict():
    region = EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "de-age")
    assert region.to_dict() == {
        "label": "face",
        "bbox": [-0.3, 0.0, 0.3, 0.6],
        "prompt": "de-age",
        "in_frame": True,
    }


@pytest.mark.parametrize("bbox", [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0, 0.0)])
def test_edit_region_rejects_a_wrong_length_bbox(bbox):
    with pytest.raises(ValueError, match="4 NDC values"):
        EditRegion("face", bbox)


@pytest.mark.parametrize(
    "bbox",
    [
        (-0.5, 0.0, -0.6, 1.0),
        (0.0, 0.5, 1.0, 0.4),
        (0.5, 0.0, 0.0, 0.5),
        (0.5, 0.0, 0.4, 0.6),
    ],
)
def test_edit_region_rejects_an_inverted_bbox(bbox):
    with pytest.raises(ValueError, match="inverted"):
        EditRegion("face", bbox)


def test_edit_region_accepts_a_degenerate_bbox():
    """A zero-area region is a degenerate box, not an inverted one."""
    region = EditRegion("face", (0.0, 0.0, 0.0, 0.0))
    assert region.bbox == (0.0, 0.0, 0.0, 0.0)
    assert region.in_frame() is True


def test_edit_region_defaults():
    region = EditRegion("face", (0.0, 0.0, 0.5, 0.5))
    assert region.prompt == ""
    assert region.to_dict()["prompt"] == ""


@pytest.mark.parametrize(
    "bbox,expected",
    [
        ((-1.0, -1.0, 1.0, 1.0), True),
        ((-1.0, 0.0, 0.0, 1.0), True),
        ((1.001, 0.0, 1.5, 0.5), False),
        ((-1.001, 0.0, 0.0, 0.5), False),
        ((0.0, -1.001, 0.5, 0.5), False),
        ((0.0, 0.0, 0.5, 1.001), False),
    ],
)
def test_edit_region_in_frame_boundaries(bbox, expected):
    assert EditRegion("face", bbox).in_frame() is expected


def test_edit_plan_labels_and_to_dict():
    plan = EditPlan(
        regions=[
            EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "de-age"),
            EditRegion("helmet", (0.4, 0.4, 0.9, 0.9), "remove"),
        ]
    )
    assert plan.labels() == ["face", "helmet"]
    assert plan.to_dict() == {
        "regions": [
            {
                "label": "face",
                "bbox": [-0.3, 0.0, 0.3, 0.6],
                "prompt": "de-age",
                "in_frame": True,
            },
            {
                "label": "helmet",
                "bbox": [0.4, 0.4, 0.9, 0.9],
                "prompt": "remove",
                "in_frame": True,
            },
        ],
        "count": 2,
    }


def test_an_empty_edit_plan_has_no_regions():
    assert EditPlan().regions == []
    assert EditPlan().labels() == []


# --------------------------------------------------------------------------
# PostPlan — is_noop, checks, overall_pass, summary
# --------------------------------------------------------------------------


def test_a_bare_plan_is_a_noop():
    plan = PostPlan()
    assert plan.is_noop() is True
    assert plan.overall_pass is True
    assert plan.summary() == "post: no-op (neutral grade, no extend, no edit)"


def test_a_grade_makes_the_plan_not_a_noop():
    plan = PostPlan(grade=apply_grade(GradeSettings(saturation=0.5)))
    assert plan.is_noop() is False


def test_an_extension_makes_the_plan_not_a_noop():
    assert PostPlan(extend=ExtendPlan()).is_noop() is False


def test_an_edit_region_makes_the_plan_not_a_noop():
    plan = PostPlan(
        edit=EditPlan(regions=[EditRegion("face", (0.0, 0.0, 0.5, 0.5), "de-age")])
    )
    assert plan.is_noop() is False


def test_an_empty_edit_plan_does_not_make_the_plan_not_a_noop():
    assert PostPlan(edit=EditPlan()).is_noop() is True


def test_checks_are_in_post_rules_order_with_the_pinned_weights():
    checks = PostPlan().checks()
    assert [check.rule for check in checks] == list(POST_RULES)
    assert [check.weight for check in checks] == [1.0, 1.0, 1.0, 0.5]


def test_a_full_valid_plan_passes():
    plan = PostPlan(
        grade=apply_grade(GradeSettings(saturation=0.5)),
        extend=ExtendPlan(mode="prequel", duration_s=8.0, overlap_frames=24),
        edit=EditPlan(regions=[EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "de-age")]),
    )
    assert plan.overall_pass is True
    assert all(check.passed for check in plan.checks())


def test_a_region_with_no_prompt_fails_the_plan():
    """``edit_prompt_present`` gates: where without what is a defect."""
    plan = PostPlan(
        edit=EditPlan(regions=[EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "")])
    )
    assert plan.checks()[2].passed is False
    assert plan.checks()[2].detail == "edit region(s) with no prompt: face"
    assert plan.overall_pass is False


def test_an_unlabelled_region_is_named_by_position_in_the_detail():
    plan = PostPlan(edit=EditPlan(regions=[EditRegion("", (0.0, 0.0, 0.5, 0.5), "")]))
    assert plan.checks()[2].detail == "edit region(s) with no prompt: region 1"


def test_an_unlabelled_region_outside_the_frame_is_named_by_position():
    plan = PostPlan(
        edit=EditPlan(regions=[EditRegion("", (0.5, 0.0, 1.5, 0.5), "de-age")])
    )
    assert plan.checks()[3].detail == "edit region(s) outside the NDC frame: region 1"


def test_two_blank_regions_are_both_listed():
    plan = PostPlan(
        edit=EditPlan(
            regions=[
                EditRegion("face", (0.0, 0.0, 0.5, 0.5), ""),
                EditRegion("helmet", (0.0, 0.0, 0.5, 0.5), ""),
            ]
        )
    )
    assert plan.checks()[2].detail == "edit region(s) with no prompt: face, helmet"
    assert plan.overall_pass is False


def test_two_regions_outside_the_frame_are_both_listed():
    plan = PostPlan(
        edit=EditPlan(
            regions=[
                EditRegion("face", (0.5, 0.0, 1.5, 0.5), "de-age"),
                EditRegion("helmet", (0.0, 0.5, 0.5, 1.5), "remove"),
            ]
        )
    )
    assert plan.checks()[3].detail == "edit region(s) outside the NDC frame: face, helmet"
    assert plan.overall_pass is True


def test_two_bad_grade_deltas_are_both_listed():
    plan = PostPlan(
        grade=GradePlan(
            deltas=[
                ("temperature", 0.0, 99.0, "up"),
                ("exposure", 0.0, 99.0, "up"),
            ]
        )
    )
    assert plan.checks()[0].detail == (
        "grade delta(s) outside range: temperature, exposure"
    )


def test_a_region_outside_the_frame_is_a_non_gating_flag():
    plan = PostPlan(
        edit=EditPlan(regions=[EditRegion("face", (0.5, 0.0, 1.5, 0.5), "de-age")])
    )
    assert plan.checks()[3].passed is False
    assert plan.checks()[3].detail == "edit region(s) outside the NDC frame: face"
    assert plan.overall_pass is True


def test_a_hand_built_grade_delta_outside_range_fails_the_plan():
    """A plan read back from a sidecar has not been through GradeSettings."""
    plan = PostPlan(grade=GradePlan(deltas=[("temperature", 0.0, 99.0, "up")]))
    assert plan.checks()[0].passed is False
    assert plan.checks()[0].detail == "grade delta(s) outside range: temperature"
    assert plan.overall_pass is False


def test_a_grade_delta_exactly_at_the_range_minimum_passes():
    plan = PostPlan(grade=GradePlan(deltas=[("temperature", 0.0, -1.0, "down")]))
    assert plan.checks()[0].passed is True


def test_a_grade_delta_exactly_at_the_range_maximum_passes():
    plan = PostPlan(grade=GradePlan(deltas=[("exposure", 0.0, 2.0, "up")]))
    assert plan.checks()[0].passed is True


def test_a_tampered_extension_overlap_fails_the_plan():
    """The check must not trust construction-time validation alone."""
    extend = ExtendPlan(mode="sequel", duration_s=10.0, overlap_frames=0)
    extend.overlap_frames = 999
    plan = PostPlan(extend=extend)
    assert plan.checks()[1].passed is False
    assert plan.overall_pass is False


@pytest.mark.parametrize("duration", [4.0, 30.0])
def test_an_extension_at_either_duration_boundary_passes(duration):
    plan = PostPlan(extend=ExtendPlan(duration_s=duration))
    assert plan.checks()[1].passed is True


@pytest.mark.parametrize("overlap", [0, 48])
def test_an_extension_at_either_overlap_boundary_passes(overlap):
    plan = PostPlan(extend=ExtendPlan(overlap_frames=overlap))
    assert plan.checks()[1].passed is True


def test_extend_check_detail_names_the_request():
    plan = PostPlan(extend=ExtendPlan(mode="prequel", duration_s=8.0, overlap_frames=24))
    assert plan.checks()[1].detail == "prequel 8.0s, overlap 24 frame(s)"


def test_no_extension_is_reported_as_such():
    assert PostPlan().checks()[1].detail == "no extension requested"


def test_post_plan_to_dict_for_a_full_plan():
    plan = PostPlan(
        grade=apply_grade(GradeSettings(saturation=0.5)),
        extend=ExtendPlan(mode="prequel", duration_s=8.0, overlap_frames=24),
        edit=EditPlan(regions=[EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "de-age")]),
    )
    assert plan.to_dict() == {
        "stages": ["grade", "extend", "edit"],
        "grade": {
            "deltas": [
                {"param": "saturation", "from": 0.0, "to": 0.5, "direction": "up"}
            ],
            "count": 1,
            "is_noop": False,
        },
        "extend": {
            "mode": "prequel",
            "duration_s": 8.0,
            "overlap_frames": 24,
            "overlap_s": 1.0,
        },
        "edit": {
            "regions": [
                {
                    "label": "face",
                    "bbox": [-0.3, 0.0, 0.3, 0.6],
                    "prompt": "de-age",
                    "in_frame": True,
                }
            ],
            "count": 1,
        },
        "is_noop": False,
        "overall_pass": True,
        "checks": [
            {
                "rule": "grade_in_range",
                "pass": True,
                "weight": 1.0,
                "detail": "every grade delta target is inside its legal range",
            },
            {
                "rule": "extend_in_range",
                "pass": True,
                "weight": 1.0,
                "detail": "prequel 8.0s, overlap 24 frame(s)",
            },
            {
                "rule": "edit_prompt_present",
                "pass": True,
                "weight": 1.0,
                "detail": "every edit region names what to change",
            },
            {
                "rule": "edit_region_in_frame",
                "pass": True,
                "weight": 0.5,
                "detail": "every edit region is inside the NDC frame",
            },
        ],
    }


def test_post_plan_to_dict_for_a_noop():
    assert PostPlan().to_dict() == {
        "stages": ["grade", "extend", "edit"],
        "grade": {"deltas": [], "count": 0, "is_noop": True},
        "extend": None,
        "edit": None,
        "is_noop": True,
        "overall_pass": True,
        "checks": [
            {
                "rule": "grade_in_range",
                "pass": True,
                "weight": 1.0,
                "detail": "every grade delta target is inside its legal range",
            },
            {
                "rule": "extend_in_range",
                "pass": True,
                "weight": 1.0,
                "detail": "no extension requested",
            },
            {
                "rule": "edit_prompt_present",
                "pass": True,
                "weight": 1.0,
                "detail": "every edit region names what to change",
            },
            {
                "rule": "edit_region_in_frame",
                "pass": True,
                "weight": 0.5,
                "detail": "every edit region is inside the NDC frame",
            },
        ],
    }


def test_post_plan_summary_for_a_full_plan():
    plan = PostPlan(
        grade=apply_grade(GradeSettings(saturation=0.5)),
        extend=ExtendPlan(mode="prequel", duration_s=8.0, overlap_frames=24),
        edit=EditPlan(regions=[EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "de-age")]),
    )
    assert plan.summary() == (
        "PASS - grade: 1 delta(s) - saturation up 0.000->0.500; "
        "extend: prequel 8.0s, overlap 24 frame(s); "
        "edit: 1 region(s) - face"
    )


def test_post_plan_summary_for_a_failing_plan():
    plan = PostPlan(
        grade=apply_grade(GradeSettings(contrast=0.2)),
        edit=EditPlan(regions=[EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "")]),
    )
    assert plan.summary() == (
        "FAIL - grade: 1 delta(s) - contrast up 0.000->0.200; "
        "edit: 1 region(s) - face"
    )


def test_post_plan_summary_for_a_non_gating_flag():
    plan = PostPlan(
        edit=EditPlan(regions=[EditRegion("face", (0.5, 0.0, 1.5, 0.5), "de-age")])
    )
    assert plan.summary() == "PASS - edit: 1 region(s) - face"


def test_post_plan_summary_lists_several_regions():
    plan = PostPlan(
        edit=EditPlan(
            regions=[
                EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "de-age"),
                EditRegion("helmet", (0.4, 0.4, 0.9, 0.9), "remove"),
            ]
        )
    )
    assert plan.summary() == "PASS - edit: 2 region(s) - face, helmet"


def test_post_summary_is_an_alias_for_the_method():
    plan = PostPlan(extend=ExtendPlan(mode="prequel"))
    assert post_summary(plan) == plan.summary()


def test_post_summaries_are_ascii():
    plans = [
        PostPlan(),
        PostPlan(grade=apply_grade(GradeSettings(saturation=0.5))),
        PostPlan(extend=ExtendPlan(mode="prequel", duration_s=8.0, overlap_frames=24)),
        PostPlan(
            edit=EditPlan(regions=[EditRegion("face", (0.5, 0.0, 1.5, 0.5), "de-age")])
        ),
        PostPlan(
            edit=EditPlan(regions=[EditRegion("face", (-0.3, 0.0, 0.3, 0.6), "")])
        ),
    ]
    assert all(plan.summary().isascii() for plan in plans)
    assert all(apply_grade(GradeSettings(saturation=0.5)).summary().isascii() for _ in [0])
