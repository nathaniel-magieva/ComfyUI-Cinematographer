"""Framing rule tests — the nine per-shot rules, with hand-computed values."""

import pytest

from cinematographer.framing import (
    FRAMING_RULES,
    INFORMATIONAL_RULES,
    _headroom_correction,
    evaluate_framing,
    summary,
)
from cinematographer.geometry import (
    CamPose,
    ShotIntent,
    Subject,
    headroom_band,
)

F = 3.45679012345679  # 1/tan(vfov/2) for the reference camera (35 mm / 36 mm / 16:9)


def ref_camera() -> CamPose:
    return CamPose(eye=(0.0, 1.656, 3.0), target=(0.0, 1.656, 0.0), focal_mm=35.0)


def ref_subject() -> Subject:
    return Subject(name="hero", base=(0.0, 0.0, 0.0), height=1.8, facing_yaw_deg=0.0)


def test_all_nine_rules_are_reported_in_order():
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    assert tuple(s.rule for s in rep.scores) == FRAMING_RULES
    assert len(rep.scores) == 9


def test_hand_computed_values_for_the_centred_reference_frame():
    """The reference camera centres the subject dead-on.

    ndcY(top)  = 0.048 * f = 0.1659250  -> headroom = 1 - 0.1659250 = 0.8340750
    ndcY(base) = -0.552 * f = -1.9081371
    shot_size  = (0.1659250 - (-1.9081371)) / 2 = 1.0370310
    """
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    assert rep.value("headroom") == pytest.approx(0.834, abs=1e-3)
    assert rep.value("shot_size") == pytest.approx(1.037, abs=1e-3)
    assert rep.value("rule_of_thirds") == pytest.approx(0.0, abs=1e-9)


def test_centred_frame_fails_thirds_and_headroom_and_size():
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    failed = {s.rule for s in rep.failures()}
    assert "rule_of_thirds" in failed
    assert "headroom" in failed
    assert "shot_size" in failed
    assert rep.overall_pass is False


def test_in_frame_passes_for_the_reference_frame():
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    assert rep.score("in_frame").passed is True


def test_in_frame_fails_when_the_subject_is_behind_the_camera():
    behind = CamPose(eye=(0.0, 1.656, -3.0), target=(0.0, 1.656, -6.0), focal_mm=35.0)
    rep = evaluate_framing(ref_subject(), behind, "medium", ShotIntent())
    assert rep.score("in_frame").passed is False
    assert "off-frame or behind camera" in rep.score("in_frame").correction


def test_intent_center_relaxes_the_thirds_rule():
    """A deliberately centred frame is correct when centred is intended."""
    rep = evaluate_framing(
        ref_subject(), ref_camera(), "medium", ShotIntent(center=True)
    )
    assert rep.score("rule_of_thirds").passed is True
    assert rep.score("rule_of_thirds").target == "centered (symmetry intended)"


def test_thirds_rule_passes_when_the_subject_sits_on_a_third():
    """Move the camera so the subject lands near ndcX = -1/3.

    ndcX = (-dx/3) * (f/aspect); setting it to -1/3 gives dx = aspect/f.
    """
    dx = (16.0 / 9.0) / F
    cam = CamPose(eye=(dx, 1.656, 3.0), target=(dx, 1.656, 0.0), focal_mm=35.0)
    rep = evaluate_framing(ref_subject(), cam, "medium", ShotIntent())
    assert rep.score("rule_of_thirds").value == pytest.approx(-1.0 / 3.0, abs=1e-3)
    assert rep.score("rule_of_thirds").passed is True


def test_lead_room_sign_flips_with_facing():
    """A subject facing screen-right should sit on the left for positive lead room.

    The camera sits at x=+1, so the subject at the origin lands at ndcX < 0
    (left of frame) — which is the correct side for a subject facing right.
    """
    cam = CamPose(eye=(1.0, 1.656, 3.0), target=(1.0, 1.656, 0.0), focal_mm=35.0)
    facing_right = Subject("a", (0.0, 0.0, 0.0), 1.8, facing_yaw_deg=90.0)
    facing_left = Subject("b", (0.0, 0.0, 0.0), 1.8, facing_yaw_deg=-90.0)
    r_right = evaluate_framing(facing_right, cam, "medium", ShotIntent())
    r_left = evaluate_framing(facing_left, cam, "medium", ShotIntent())
    assert r_right.value("rule_of_thirds") < 0, "subject must be left of frame"
    assert r_right.value("lead_room") > 0
    assert r_left.value("lead_room") < 0


def test_level_rule_honours_an_intended_dutch():
    cam = CamPose(
        eye=(0.0, 1.656, 3.0), target=(0.0, 1.656, 0.0), focal_mm=35.0, roll_deg=8.0
    )
    intended = evaluate_framing(
        ref_subject(), cam, "medium", ShotIntent(dutch_deg=8.0)
    )
    accidental = evaluate_framing(ref_subject(), cam, "medium", ShotIntent())
    assert intended.score("level").passed is True
    assert accidental.score("level").passed is False
    assert accidental.score("level").correction == "match the intended camera roll"


def test_informational_rules_always_pass():
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    for rule in INFORMATIONAL_RULES:
        assert rep.score(rule).passed is True, rule


def test_overall_pass_requires_every_rule_at_or_above_weight_08():
    """rule_of_thirds (0.8) and shot_size (1.0) must both pass for medium."""
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    heavy_failures = [s for s in rep.failures() if s.weight >= 0.8]
    assert heavy_failures
    assert rep.overall_pass is False


def test_direct_address_classifies_down_the_lens():
    """A subject facing the camera is a direct address."""
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    assert rep.score("direct_address").target == "direct address (down the lens)"


def test_summary_reports_fail_and_names_the_failing_rules():
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    text = summary(rep)
    assert text.startswith("FAIL")
    assert "rule_of_thirds" in text


def test_corrections_are_returned_for_every_failing_rule():
    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    corr = rep.corrections()
    assert len(corr) == len(rep.failures())
    assert all(isinstance(c, str) and c for c in corr)


def test_report_serialises_to_json_safe_dict():
    import json

    rep = evaluate_framing(ref_subject(), ref_camera(), "medium", ShotIntent())
    json.dumps(rep.to_dict())  # must not raise
    assert rep.to_dict()["overall_pass"] is False


# ---------------------------------------------------------------------------
# The correction string must move the frame TOWARD the band, not away from it.
#
# This is a regression test for a real bug: both target directions in
# `_headroom_correction` were inverted, so an operator who followed the advice
# moved further from a pass. The bug survived because the string was only ever
# asserted for its *presence*, never for its *direction*.
#
# Sign convention, from framing.py:146 -- `head = 1 - ty`, where `ty` is the
# subject's top in NDC. Aiming the camera HIGHER points it up, so the subject
# sits LOWER in frame, so `ty` falls and `head` RISES. Therefore:
#     "raise the camera target" -> head increases
#     "lower the camera target" -> head decreases
# ---------------------------------------------------------------------------

def _head_after_following(advice: str, head: float, step: float = 0.05) -> float:
    """Apply the target half of the advice, using the convention above."""
    if "raise the camera target" in advice:
        return head + step
    if "lower the camera target" in advice:
        return head - step
    raise AssertionError(f"advice names no target direction: {advice!r}")


@pytest.mark.parametrize("shot_type", ["closeup", "medium", "wide"])
@pytest.mark.parametrize("side", ["below", "above"])
def test_headroom_correction_moves_toward_the_band(shot_type, side):
    """Following the advice must turn a failing frame into a passing one."""
    lo, hi = headroom_band(shot_type)
    head = lo - 0.05 if side == "below" else hi + 0.05

    assert not (lo <= head <= hi), "the fixture must start outside the band"

    advice = _headroom_correction(head, lo, hi)
    after = _head_after_following(advice, head)

    assert lo <= after <= hi, (
        f"{shot_type}/{side}: head {head:+.2f} is outside [{lo}, {hi}], the advice "
        f"{advice!r} moved it to {after:+.2f}, which is still outside. "
        f"The target direction is inverted."
    )


def test_headroom_correction_direction_is_not_symmetric():
    """Guard against a 'fix' that swaps both branches and stays self-consistent.

    If both directions were flipped together, the parametrised test above would
    still pass for a symmetric band. Asserting the two branches disagree pins
    the absolute sign, not just the relative one.
    """
    lo, hi = headroom_band("medium")
    tight = _headroom_correction(lo - 0.05, lo, hi)
    loose = _headroom_correction(hi + 0.05, lo, hi)

    assert "raise the camera target" in tight, tight
    assert "lower the camera target" in loose, loose
