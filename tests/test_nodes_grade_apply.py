"""``CinemaGradeApply`` -- the one node in this pack that changes pixels.

Why this file exists
--------------------
Every other node in the pack measures, describes, or assembles text. This one
does arithmetic on an image tensor, and arithmetic is the kind of thing that is
easy to get subtly wrong and impossible to notice by eye. So every control is
pinned to a **hand-computed** value here, not to whatever the implementation
happens to return. If a control's formula changes, these tests fail and the
change has to be argued for.

What is deliberately NOT claimed
--------------------------------
The control *ranges* come from ``post.GRADE_RANGES``, which is this pack's own
convention -- no published source defines them. The grade itself is a simple
approximation, one arithmetic operation per control, not colour science. These
tests pin the arithmetic; they do not and cannot claim the result looks right.

The gate
--------
``grade_json`` is a **required** input, and an empty one is a hard error rather
than a neutral grade. That is the whole point: POST must not run before the
judge has, and "nothing was wired in" must not be indistinguishable from "the
judge said leave it alone".
"""

import json

import pytest

# numpy is imported lazily *inside* the node's helpers, so the pack still
# imports without it and only ``CinemaGradeApply`` fails at execution time.
# The test module must be at least as tolerant, or a stdlib-only interpreter
# (which is what the engine's own test venv is) cannot even collect the suite:
# a module-scope import here turns "one node needs numpy" into "no test runs".
np = pytest.importorskip(
    "numpy", reason="CinemaGradeApply needs numpy; the rest of the pack does not"
)

from cinematographer import nodes
from cinematographer import post


def _plan(**settings):
    """A real grade plan, produced by the real ``CinemaGrade`` node."""
    return nodes.CinemaGrade().grade("", **settings)[0]


def _apply(image, plan_json, seed=0):
    return nodes.CinemaGradeApply().apply(image, plan_json, seed=seed)


def _flat(value, shape=(1, 2, 2, 3)):
    return np.full(shape, value, dtype=np.float32)


# --------------------------------------------------------------------------
# The node's declared interface
# --------------------------------------------------------------------------


def test_grade_json_is_required_not_optional():
    """The gate is a data dependency, so the input must be in `required`.

    If this were optional, ComfyUI would happily execute POST with nothing
    wired into it, and the judge -> POST ordering would be a convention rather
    than something the graph enforces.
    """
    inputs = nodes.CinemaGradeApply.INPUT_TYPES()
    assert "required" in inputs
    assert "optional" not in inputs or "grade_json" not in inputs.get("optional", {})
    assert "image" in inputs["required"]
    assert "grade_json" in inputs["required"]


def test_declared_interface_is_exactly_what_was_specified():
    assert nodes.CinemaGradeApply.RETURN_TYPES == ("IMAGE", "STRING")
    assert nodes.CinemaGradeApply.RETURN_NAMES == ("image", "summary")
    assert nodes.CinemaGradeApply.FUNCTION == "apply"
    assert nodes.CinemaGradeApply.CATEGORY == "Cinematographer"
    assert nodes.CinemaGradeApply.OUTPUT_NODE is False


def test_apply_returns_an_image_and_a_summary():
    out, summary = _apply(_flat(0.5), _plan())
    assert isinstance(summary, str)
    assert out.shape == (1, 2, 2, 3)


def test_a_numpy_input_comes_back_as_numpy():
    """The node must not require torch just to be testable."""
    out, _ = _apply(_flat(0.5), _plan())
    assert isinstance(out, np.ndarray)


# --------------------------------------------------------------------------
# Neutral is identity -- the control case everything else is measured against
# --------------------------------------------------------------------------


def test_a_neutral_plan_is_exactly_the_identity():
    """Not "close to" -- exactly. A neutral plan must not perturb one bit."""
    image = np.random.default_rng(0).random((1, 4, 4, 3)).astype(np.float32)
    out, _ = _apply(image, _plan())
    assert np.array_equal(out, image)


def test_a_neutral_plan_says_so_without_claiming_a_grade():
    _, summary = _apply(_flat(0.5), _plan())
    assert "neutral" in summary
    assert "unchanged" in summary


def test_the_summary_says_applied_never_plan():
    """Wording is the honesty requirement: this node changed the pixels.

    `CinemaGrade` describes a plan. This node applies one. If the summary said
    "plan" a reader could not tell the two apart.
    """
    _, summary = _apply(_flat(0.5), _plan(contrast=0.4))
    assert summary.startswith("applied grade")
    assert "plan" not in summary


# --------------------------------------------------------------------------
# exposure -- x * 2**exposure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exposure,expected",
    [
        (0.0, 0.5),
        (1.0, 1.0),  # 0.5 * 2 = 1.0
        (-1.0, 0.25),  # 0.5 * 0.5 = 0.25
        (2.0, 1.0),  # 0.5 * 4 = 2.0, clamped to 1.0
        (-2.0, 0.125),  # 0.5 * 0.25 = 0.125
    ],
)
def test_exposure_is_a_power_of_two_gain(exposure, expected):
    out, _ = _apply(_flat(0.5), _plan(exposure=exposure))
    assert float(out.ravel()[0]) == pytest.approx(expected, abs=1e-6)


def test_exposure_leaves_black_black():
    """A gain on zero is still zero -- exposure must not lift the floor."""
    out, _ = _apply(_flat(0.0), _plan(exposure=2.0))
    assert float(out.ravel()[0]) == 0.0


# --------------------------------------------------------------------------
# contrast -- (x - 0.5) * (1 + contrast) + 0.5
# --------------------------------------------------------------------------


def test_mid_grey_is_the_contrast_pivot():
    """0.5 is the fixed point, so contrast alone cannot move it."""
    out, _ = _apply(_flat(0.5), _plan(contrast=0.4))
    assert float(out.ravel()[0]) == pytest.approx(0.5, abs=1e-6)


@pytest.mark.parametrize(
    "value,contrast,expected",
    [
        (0.75, 0.4, 0.85),  # (0.75-0.5)*1.4+0.5
        (0.75, -0.4, 0.65),  # (0.75-0.5)*0.6+0.5
        (0.25, 0.4, 0.15),  # (0.25-0.5)*1.4+0.5
        (0.25, -0.4, 0.35),  # (0.25-0.5)*0.6+0.5
    ],
)
def test_contrast_moves_away_from_the_pivot_in_both_directions(
    value, contrast, expected
):
    out, _ = _apply(_flat(value), _plan(contrast=contrast))
    assert float(out.ravel()[0]) == pytest.approx(expected, abs=1e-6)


def test_contrast_pushes_high_up_and_low_down():
    """The sign of the effect, checked on one image rather than two."""
    image = np.array([[[[0.25, 0.25, 0.25], [0.75, 0.75, 0.75]]]], dtype=np.float32)
    out, _ = _apply(image, _plan(contrast=0.4))
    assert float(out[0, 0, 0, 0]) < 0.25
    assert float(out[0, 0, 1, 0]) > 0.75


# --------------------------------------------------------------------------
# saturation -- gray + (x - gray) * (1 + saturation), Rec. 709 luma
# --------------------------------------------------------------------------


def test_saturation_minus_one_collapses_to_luma():
    """At -1 the colour is fully desaturated, so all three channels are luma."""
    image = np.array([[[[0.2, 0.5, 0.8]]]], dtype=np.float32)
    gray = 0.2126 * 0.2 + 0.7152 * 0.5 + 0.0722 * 0.8
    out, _ = _apply(image, _plan(saturation=-1.0))
    assert out.ravel().tolist() == pytest.approx([gray, gray, gray], abs=1e-6)


def test_saturation_uses_rec709_weights_not_a_flat_mean():
    """A flat mean would give a different number; this pins the actual weights."""
    image = np.array([[[[0.2, 0.5, 0.8]]]], dtype=np.float32)
    flat_mean = (0.2 + 0.5 + 0.8) / 3
    out, _ = _apply(image, _plan(saturation=-1.0))
    assert float(out.ravel()[0]) != pytest.approx(flat_mean, abs=1e-4)
    assert float(out.ravel()[0]) == pytest.approx(0.45788, abs=1e-5)


def test_saturation_leaves_a_grey_pixel_alone():
    """A pixel that is already grey has x == gray, so the term vanishes."""
    out, _ = _apply(_flat(0.4), _plan(saturation=1.0))
    assert float(out.ravel()[0]) == pytest.approx(0.4, abs=1e-6)


def test_positive_saturation_pushes_colour_further_from_grey():
    image = np.array([[[[0.6, 0.4, 0.4]]]], dtype=np.float32)
    out, _ = _apply(image, _plan(saturation=0.5))
    assert float(out[0, 0, 0, 0]) > 0.6  # the dominant channel grows
    assert float(out[0, 0, 0, 1]) < 0.4  # the others shrink


# --------------------------------------------------------------------------
# temperature -- R up, B down, G untouched
# --------------------------------------------------------------------------


def test_temperature_lifts_red_and_drops_blue_by_the_same_amount():
    out, _ = _apply(_flat(0.5), _plan(temperature=1.0))
    red, green, blue = (float(v) for v in out[0, 0, 0])
    assert red == pytest.approx(0.75, abs=1e-6)  # 0.5 + 1.0 * 0.25
    assert green == pytest.approx(0.5, abs=1e-6)  # untouched
    assert blue == pytest.approx(0.25, abs=1e-6)  # 0.5 - 1.0 * 0.25


def test_negative_temperature_is_the_mirror_image():
    out, _ = _apply(_flat(0.5), _plan(temperature=-1.0))
    red, green, blue = (float(v) for v in out[0, 0, 0])
    assert (red, green, blue) == pytest.approx((0.25, 0.5, 0.75), abs=1e-6)


def test_temperature_never_touches_green():
    """Green is the anchor; if it moved, this would be a tint, not a temperature."""
    image = np.random.default_rng(1).random((1, 3, 3, 3)).astype(np.float32)
    out, _ = _apply(image, _plan(temperature=0.5))
    assert np.array_equal(out[..., 1], image[..., 1])


# --------------------------------------------------------------------------
# highlights -- weighted to the top end only
# --------------------------------------------------------------------------


def test_highlights_does_not_touch_mid_grey_or_below():
    """The weight is zero at and below 0.5, so the lower half is untouched."""
    image = np.array([[[[0.2, 0.2, 0.2], [0.5, 0.5, 0.5]]]], dtype=np.float32)
    out, _ = _apply(image, _plan(highlights=1.0))
    assert float(out[0, 0, 0, 0]) == pytest.approx(0.2, abs=1e-6)
    assert float(out[0, 0, 1, 0]) == pytest.approx(0.5, abs=1e-6)


def test_highlights_hand_computed_above_mid():
    """At 0.75 the weight is 0.5, so x' = 0.75 * (1 + 1.0 * 0.5 * 0.5)."""
    out, _ = _apply(_flat(0.75), _plan(highlights=1.0))
    assert float(out.ravel()[0]) == pytest.approx(0.9375, abs=1e-6)


def test_negative_highlights_compresses_the_top_end():
    out, _ = _apply(_flat(0.75), _plan(highlights=-1.0))
    assert float(out.ravel()[0]) == pytest.approx(0.5625, abs=1e-6)  # 0.75 * 0.75


# --------------------------------------------------------------------------
# sharpness -- unsharp mask against a 3x3 box blur
# --------------------------------------------------------------------------


def test_sharpness_leaves_a_flat_image_alone():
    """Blur of a constant image is that constant, so the difference is zero."""
    out, _ = _apply(_flat(0.4), _plan(sharpness=1.0))
    assert out.ravel().tolist() == pytest.approx([0.4] * 12, abs=1e-6)


def test_sharpness_hand_computed_across_a_step_edge():
    """A 1x5 row, 0.25 then 0.75, sharpness 0.3.

    The 3x3 box blur at pixel 2 is (0.25+0.25+0.75)/3 = 0.4166667, and at
    pixel 3 is (0.25+0.75+0.75)/3 = 0.5833333. So with s=0.3:
        pixel 2: 0.25 + 0.3*(0.25 - 0.4166667) = 0.20
        pixel 3: 0.75 + 0.3*(0.75 - 0.5833333) = 0.80
    """
    row = np.array([0.25, 0.25, 0.25, 0.75, 0.75], dtype=np.float32)
    image = np.repeat(row[None, None, :, None], 3, axis=3)
    out, _ = _apply(image, _plan(sharpness=0.3))
    assert float(out[0, 0, 2, 0]) == pytest.approx(0.20, abs=1e-6)
    assert float(out[0, 0, 3, 0]) == pytest.approx(0.80, abs=1e-6)


def test_sharpness_increases_local_contrast_across_an_edge():
    """The property, stated independently of the exact formula."""
    row = np.array([0.25, 0.25, 0.25, 0.75, 0.75], dtype=np.float32)
    image = np.repeat(row[None, None, :, None], 3, axis=3)
    out, _ = _apply(image, _plan(sharpness=0.3))
    before = float(image[0, 0, 3, 0]) - float(image[0, 0, 2, 0])
    after = float(out[0, 0, 3, 0]) - float(out[0, 0, 2, 0])
    assert after > before


# --------------------------------------------------------------------------
# film_grain -- seeded, so a run is reproducible
# --------------------------------------------------------------------------


def test_grain_is_identical_at_the_same_seed():
    """Reproducibility is the requirement: a re-shoot must be repeatable."""
    image = _flat(0.5)
    first, _ = _apply(image, _plan(film_grain=1.0), seed=7)
    second, _ = _apply(image, _plan(film_grain=1.0), seed=7)
    assert np.array_equal(first, second)


def test_grain_differs_at_a_different_seed():
    image = _flat(0.5)
    first, _ = _apply(image, _plan(film_grain=1.0), seed=7)
    other, _ = _apply(image, _plan(film_grain=1.0), seed=8)
    assert not np.array_equal(first, other)


def test_zero_grain_is_the_identity_regardless_of_seed():
    image = _flat(0.5)
    for seed in (0, 1, 12345):
        out, _ = _apply(image, _plan(), seed=seed)
        assert np.array_equal(out, image)


def test_grain_actually_perturbs_the_image():
    out, _ = _apply(_flat(0.5), _plan(film_grain=1.0), seed=3)
    assert not np.allclose(out, 0.5)


def test_grain_amplitude_scales_with_the_control():
    """A stronger grain setting must move the pixels further."""
    image = _flat(0.5)
    weak, _ = _apply(image, _plan(film_grain=0.25), seed=5)
    strong, _ = _apply(image, _plan(film_grain=1.0), seed=5)
    assert np.abs(strong - 0.5).mean() > np.abs(weak - 0.5).mean()


def test_grain_stays_inside_the_clamp():
    out, _ = _apply(_flat(0.5), _plan(film_grain=1.0), seed=11)
    assert float(out.min()) >= 0.0
    assert float(out.max()) <= 1.0


# --------------------------------------------------------------------------
# the clamp, probed from both sides
# --------------------------------------------------------------------------


def test_the_top_end_clamps_to_one():
    out, _ = _apply(_flat(0.9), _plan(exposure=2.0))
    assert float(out.ravel()[0]) == 1.0


def test_the_bottom_end_clamps_to_zero():
    """Contrast, not exposure, is what can drive a value below zero.

    Exposure is a positive gain (``2**exposure``), so it can never take a
    non-negative pixel negative -- 0.1 at exposure -2 is 0.025, not 0. Contrast
    around the 0.5 pivot can: (0.1-0.5)*2+0.5 = -0.3.
    """
    out, _ = _apply(_flat(0.1), _plan(contrast=1.0))
    assert float(out.ravel()[0]) == 0.0


def test_exposure_alone_cannot_drive_a_pixel_negative():
    """The floor is preserved by a pure gain, which is why the clamp above
    needs a pivot-based control to reach it."""
    out, _ = _apply(_flat(0.1), _plan(exposure=-2.0))
    assert float(out.ravel()[0]) == pytest.approx(0.025, abs=1e-6)


def test_no_output_ever_leaves_the_unit_interval():
    """Whatever the combination, the result is a legal image."""
    image = np.random.default_rng(2).random((1, 3, 3, 3)).astype(np.float32)
    out, _ = _apply(
        image,
        _plan(
            exposure=2.0,
            contrast=1.0,
            saturation=1.0,
            temperature=1.0,
            highlights=1.0,
            sharpness=1.0,
            film_grain=1.0,
        ),
        seed=4,
    )
    assert float(out.min()) >= 0.0
    assert float(out.max()) <= 1.0


# --------------------------------------------------------------------------
# the gate: empty, malformed, and out-of-range input
# --------------------------------------------------------------------------


def test_an_empty_grade_json_is_a_hard_error():
    """The gate. "Nothing wired in" must not read as "no changes"."""
    with pytest.raises(ValueError, match="grade_json is empty"):
        _apply(_flat(0.5), "")


def test_whitespace_only_grade_json_is_a_hard_error():
    with pytest.raises(ValueError, match="grade_json is empty"):
        _apply(_flat(0.5), "   \n  ")


def test_malformed_grade_json_is_a_hard_error():
    with pytest.raises(ValueError, match="not valid JSON"):
        _apply(_flat(0.5), "{not json")


def test_a_json_null_grade_json_is_a_hard_error():
    with pytest.raises(ValueError, match="not valid JSON"):
        _apply(_flat(0.5), "null")


def test_a_json_list_grade_json_is_a_hard_error():
    with pytest.raises(ValueError, match="must be a JSON object"):
        _apply(_flat(0.5), "[]")


@pytest.mark.parametrize("param", post.GRADE_PARAMS)
def test_every_control_rejects_a_value_above_its_legal_range(param):
    """The range comes from the engine, so the node cannot drift from it."""
    low, high = post.GRADE_RANGES[param]
    plan = json.dumps({"deltas": [{"param": param, "to": float(high) + 1.0}]})
    with pytest.raises(ValueError, match="outside its legal range"):
        _apply(_flat(0.5), plan)


@pytest.mark.parametrize("param", post.GRADE_PARAMS)
def test_every_control_rejects_a_value_below_its_legal_range(param):
    low, high = post.GRADE_RANGES[param]
    plan = json.dumps({"deltas": [{"param": param, "to": float(low) - 1.0}]})
    with pytest.raises(ValueError, match="outside its legal range"):
        _apply(_flat(0.5), plan)


@pytest.mark.parametrize("param", post.GRADE_PARAMS)
def test_every_control_accepts_both_ends_of_its_legal_range(param):
    """The boundary is legal; only past it is an error."""
    low, high = post.GRADE_RANGES[param]
    for value in (float(low), float(high)):
        plan = json.dumps({"deltas": [{"param": param, "to": value}]})
        out, _ = _apply(_flat(0.5), plan)
        assert out.shape == (1, 2, 2, 3)


def test_a_non_numeric_delta_value_is_rejected():
    plan = json.dumps({"deltas": [{"param": "contrast", "to": "a lot"}]})
    with pytest.raises(ValueError, match="non-numeric"):
        _apply(_flat(0.5), plan)


def test_a_control_the_engine_does_not_know_is_ignored_not_invented():
    """An unknown key must not be silently applied as if it meant something."""
    plan = json.dumps({"deltas": [{"param": "bloom", "to": 1.0}]})
    out, summary = _apply(_flat(0.5), plan)
    assert np.allclose(out, 0.5)
    assert "neutral" in summary


# --------------------------------------------------------------------------
# the plan is read as deltas, and the order of operations is fixed
# --------------------------------------------------------------------------


def test_the_plan_is_read_from_the_deltas_not_from_a_settings_block():
    """`CinemaGrade` emits deltas; this node must read what it actually emits."""
    plan = json.loads(_plan(contrast=0.4))
    assert "deltas" in plan
    assert any(d["param"] == "contrast" for d in plan["deltas"])


def test_the_summary_names_the_controls_that_moved():
    _, summary = _apply(_flat(0.5), _plan(contrast=0.4, temperature=-0.3))
    assert "contrast" in summary
    assert "temperature" in summary
    assert "2 control(s)" in summary


def test_a_control_at_its_neutral_value_is_not_reported_as_moved():
    """A delta that lands back on neutral must not be counted as a change."""
    plan = json.dumps({"deltas": [{"param": "contrast", "to": 0.0}]})
    _, summary = _apply(_flat(0.5), plan)
    assert "neutral" in summary


def test_the_documented_order_of_operations_is_the_one_implemented():
    """exposure then contrast is not the same as contrast then exposure.

    The docstring commits to a fixed order. This pins it: applying exposure
    first and contrast second to 0.25 with both at full strength gives a
    different number than the reverse, and the node must produce the former.
    """
    image = _flat(0.25)
    out, _ = _apply(image, _plan(exposure=1.0, contrast=1.0))
    # exposure: 0.25 * 2 = 0.5 ; contrast: (0.5-0.5)*2+0.5 = 0.5
    assert float(out.ravel()[0]) == pytest.approx(0.5, abs=1e-6)
    # the reverse order would give: (0.25-0.5)*2+0.5 = 0.0 ; 0.0*2 = 0.0
    assert float(out.ravel()[0]) != pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------
# shape handling
# --------------------------------------------------------------------------


def test_a_three_dimensional_image_is_accepted_as_a_single_frame():
    """ComfyUI normally sends [B,H,W,C], but [H,W,C] must not crash.

    It is promoted to a one-frame batch rather than returned as-is, because
    ComfyUI's IMAGE type is always 4D -- handing back 3D would break the next
    node in the graph.
    """
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    out, _ = _apply(image, _plan())
    assert out.shape == (1, 2, 2, 3)
    assert np.allclose(out, 0.5)


def test_an_image_with_too_few_channels_is_rejected():
    image = np.full((1, 2, 2, 2), 0.5, dtype=np.float32)
    with pytest.raises(ValueError, match=r"\[B,H,W,C\]"):
        _apply(image, _plan())


def test_a_batch_of_frames_is_graded_frame_by_frame():
    """Every frame in the batch gets the same treatment."""
    image = np.stack([_flat(0.25, (1, 2, 2, 3))[0], _flat(0.75, (1, 2, 2, 3))[0]])
    out, _ = _apply(image, _plan(exposure=1.0))
    assert float(out[0].ravel()[0]) == pytest.approx(0.5, abs=1e-6)
    assert float(out[1].ravel()[0]) == pytest.approx(1.0, abs=1e-6)


def test_the_input_image_is_not_mutated_in_place():
    """A node must not scribble on the tensor its upstream handed it."""
    image = _flat(0.5)
    before = image.copy()
    _apply(image, _plan(exposure=1.0, temperature=0.5))
    assert np.array_equal(image, before)


# --------------------------------------------------------------------------
# the node is registered, and the plan it consumes is the one Grade emits
# --------------------------------------------------------------------------


def test_the_node_is_registered_under_its_class_name():
    assert "CinemaGradeApply" in nodes.NODE_CLASS_MAPPINGS
    assert nodes.NODE_CLASS_MAPPINGS["CinemaGradeApply"] is nodes.CinemaGradeApply
    assert "CinemaGradeApply" in nodes.NODE_DISPLAY_NAME_MAPPINGS


def test_grade_apply_consumes_grade_output_end_to_end():
    """The gate, exercised as a graph would: judge -> Grade -> Apply."""
    judge_verdict = "raise contrast; subject is 0.3 stops hot"
    plan_json = nodes.CinemaGrade().grade(judge_verdict, contrast=0.4)[0]
    assert json.loads(plan_json)["corrections"] == judge_verdict
    out, summary = _apply(_flat(0.75), plan_json)
    assert float(out.ravel()[0]) == pytest.approx(0.85, abs=1e-6)
    assert summary.startswith("applied grade")
