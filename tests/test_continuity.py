"""Choros continuity tests — the 180-degree axis rule and the 30-degree rule."""

import pytest

from cinematographer.continuity import (
    MIN_ANGLE_CHANGE_DEG,
    ContinuityShot,
    ang_delta,
    axis_side,
    cam_azimuth_deg,
    continuity_summary,
    evaluate_continuity,
)
from cinematographer.geometry import CamPose


def cam_at(x: float, z: float = 3.0) -> CamPose:
    return CamPose(eye=(x, 1.6, z), target=(0.0, 1.6, 0.0))


def test_cam_azimuth_is_zero_on_the_plus_z_axis():
    assert cam_azimuth_deg((0, 0, 0), (0, 1.6, 3)) == pytest.approx(0.0)


def test_cam_azimuth_is_90_degrees_on_the_plus_x_axis():
    assert cam_azimuth_deg((0, 0, 0), (3, 1.6, 0)) == pytest.approx(90.0)


def test_axis_side_is_opposite_for_mirrored_cameras():
    """A subject facing +Z: cameras at +X and -X are on opposite sides of the line."""
    a = axis_side((0, 0, 0), 0.0, (3.0, 1.6, 3.0))
    b = axis_side((0, 0, 0), 0.0, (-3.0, 1.6, 3.0))
    assert a != b


def test_axis_side_is_stable_for_two_cameras_on_the_same_side():
    a = axis_side((0, 0, 0), 0.0, (1.0, 1.6, 3.0))
    b = axis_side((0, 0, 0), 0.0, (2.0, 1.6, 2.0))
    assert a == b


def test_ang_delta_wraps_correctly():
    assert ang_delta(0, 30) == pytest.approx(30.0)
    assert ang_delta(350, 10) == pytest.approx(20.0)  # wraps through 0
    assert ang_delta(0, 180) == pytest.approx(180.0)
    assert ang_delta(0, 190) == pytest.approx(170.0)  # takes the short way


def test_axis_cross_is_flagged():
    shots = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(1.5)),
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(-1.5)),  # crossed to the other side
    ]
    issues = evaluate_continuity(shots)
    axis = [i for i in issues if i.rule == "180_axis"][0]
    assert axis.passed is False
    assert "axis crossed" in axis.detail


def test_same_side_axis_passes():
    shots = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(1.0)),
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(2.0)),
    ]
    axis = [i for i in evaluate_continuity(shots) if i.rule == "180_axis"][0]
    assert axis.passed is True


def test_jump_cut_under_30_degrees_is_flagged():
    """Two cameras 20 degrees apart read as a jump cut."""
    shots = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(0.0, 3.0)),  # azimuth 0
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(1.0925, 3.0)),  # azimuth ~20
    ]
    deg = [i for i in evaluate_continuity(shots) if i.rule == "30_degree"][0]
    assert deg.passed is False
    assert "jump cut" in deg.detail


def test_angle_change_above_the_threshold_passes():
    """31 degrees clears the 30-degree rule.

    The exact-30 boundary is deliberately not asserted: `atan2(3*tan(30), 3)`
    lands a few ulps either side of 30.0, so a test there would be flaky rather
    than meaningful.
    """
    import math

    x = 3.0 * math.tan(math.radians(31.0))
    shots = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(0.0, 3.0)),
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(x, 3.0)),
    ]
    deg = [i for i in evaluate_continuity(shots) if i.rule == "30_degree"][0]
    assert deg.passed is True


def test_two_checks_are_emitted_per_cut():
    shots = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(1.0)),
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(2.0)),
        ContinuityShot(3, (0, 0, 0), 0.0, cam_at(3.0)),
    ]
    issues = evaluate_continuity(shots)
    assert len(issues) == 4  # 2 cuts x 2 rules
    assert {i.rule for i in issues} == {"180_axis", "30_degree"}


def test_single_shot_yields_no_issues():
    assert evaluate_continuity([ContinuityShot(1, (0, 0, 0), 0.0, cam_at(1.0))]) == []


def test_summary_reports_pass_and_fail():
    # Same side of the action line, 45 degrees apart: both rules pass.
    good = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(0.0, 3.0)),  # azimuth 0
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(3.0, 3.0)),  # azimuth 45
    ]
    assert continuity_summary(evaluate_continuity(good)).startswith("PASS")

    bad = [
        ContinuityShot(1, (0, 0, 0), 0.0, cam_at(1.5)),
        ContinuityShot(2, (0, 0, 0), 0.0, cam_at(-1.5)),
    ]
    text = continuity_summary(evaluate_continuity(bad))
    assert text.startswith("FAIL")
    assert "180_axis" in text


def test_min_angle_constant_is_thirty():
    assert MIN_ANGLE_CHANGE_DEG == 30.0


def test_shot_round_trips_through_dict():
    shot = ContinuityShot(7, (1.0, 0.0, 2.0), 45.0, cam_at(1.0))
    assert ContinuityShot.from_dict(shot.to_dict()).to_dict() == shot.to_dict()
