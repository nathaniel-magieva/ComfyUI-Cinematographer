"""Geometry tests — hand-computed expected values.

The reference camera used throughout: eye (0, 1.656, 3), target (0, 1.656, 0),
35 mm focal, 36 mm sensor, 16:9. That gives

    vfov = 2*atan((36/(16/9)) / (2*35)) = 2*atan(0.2892857142857143)
    f    = 1/tan(vfov/2) = (2*focal)/(sensor/aspect) = 70/20.25 = 3.45679012345679

which is the constant every expected value below is derived from.
"""

import math

import pytest

from cinematographer.geometry import (
    CamPose,
    ShotIntent,
    Subject,
    anchors,
    clamp,
    cross,
    dot,
    headroom_band,
    norm,
    projector,
    round3,
    shot_size_ok,
    shot_weights,
    size_target_mid,
    sub,
)

F = 70.0 / 20.25  # = 3.45679012345679, exact for 35 mm / 36 mm / 16:9


def ref_camera() -> CamPose:
    return CamPose(eye=(0.0, 1.656, 3.0), target=(0.0, 1.656, 0.0), focal_mm=35.0)


def ref_subject() -> Subject:
    return Subject(name="hero", base=(0.0, 0.0, 0.0), height=1.8, facing_yaw_deg=0.0)


# ---------------------------------------------------------------- vector helpers


def test_vector_helpers():
    assert sub((3, 2, 1), (1, 1, 1)) == (2, 1, 0)
    assert cross((1, 0, 0), (0, 1, 0)) == (0, 0, 1)
    assert dot((1, 2, 3), (4, 5, 6)) == 32
    assert norm((0, 0, 5)) == (0.0, 0.0, 1.0)


def test_norm_degenerate_returns_plus_z():
    """The Go source returns (0,0,1) for a degenerate vector; we must match."""
    assert norm((0.0, 0.0, 0.0)) == (0.0, 0.0, 1.0)


def test_clamp_and_round3():
    assert clamp(5, 0, 1) == 1
    assert clamp(-5, 0, 1) == 0
    assert clamp(0.5, 0, 1) == 0.5
    assert round3(0.123456) == 0.123


# ------------------------------------------------------------------- projection


def test_projector_derives_fov_from_focal_and_sensor():
    proj = projector(ref_camera())
    x, y, d, in_front = proj((0.0, 1.656, 0.0))
    assert in_front
    assert x == pytest.approx(0.0, abs=1e-9)
    assert y == pytest.approx(0.0, abs=1e-9)
    assert d == pytest.approx(3.0, abs=1e-9)


def test_projector_top_of_subject_matches_hand_computation():
    """ndcY(top) = (0.144/3) * f = 0.048 * 3.4567701 = 0.1659250"""
    proj = projector(ref_camera())
    _, y, _, _ = proj((0.0, 1.8, 0.0))
    assert y == pytest.approx(0.048 * F, abs=1e-6)
    assert y == pytest.approx(0.1659250, abs=1e-6)


def test_projector_base_of_subject_matches_hand_computation():
    """ndcY(base) = (-1.656/3) * f = -0.552 * 3.4567701 = -1.9081371"""
    proj = projector(ref_camera())
    _, y, _, _ = proj((0.0, 0.0, 0.0))
    assert y == pytest.approx(-0.552 * F, abs=1e-6)


def test_projector_reports_behind_camera():
    proj = projector(ref_camera())
    _, _, _, in_front = proj((0.0, 1.656, 6.0))  # behind the camera at z=3
    assert in_front is False


def test_projector_horizontal_offset():
    """A point 1 m to the right at 3 m depth: ndcX = (1/3)*(f/aspect)."""
    proj = projector(ref_camera())
    x, _, _, _ = proj((1.0, 1.656, 0.0))
    assert x == pytest.approx((1.0 / 3.0) * (F / (16.0 / 9.0)), abs=1e-6)


def test_explicit_fov_overrides_focal_and_sensor():
    """With fov=40 the projector must use it directly, not the focal/sensor pair."""
    cam = CamPose(eye=(0.0, 1.656, 3.0), target=(0.0, 1.656, 0.0), fov=40.0)
    proj = projector(cam)
    _, y, _, _ = proj((0.0, 1.8, 0.0))
    f40 = 1.0 / math.tan(math.radians(40.0) / 2)
    assert y == pytest.approx(0.048 * f40, abs=1e-6)


def test_roll_rotates_the_basis():
    """A 90-degree roll swaps the axes — but the two axes have different scales.

    ndcX uses f/aspect and ndcY uses f, so a 90-degree roll maps
    x -> y/aspect and y -> -x*aspect. Asserting a plain swap would be wrong.
    """
    aspect = 16.0 / 9.0
    level = projector(ref_camera())
    rolled = projector(CamPose(**{**ref_camera().to_dict(), "roll_deg": 90.0}))
    x0, y0, _, _ = level((1.0, 1.656, 0.0))
    x1, y1, _, _ = rolled((1.0, 1.656, 0.0))
    assert x1 == pytest.approx(y0 / aspect, abs=1e-9)
    assert y1 == pytest.approx(-x0 * aspect, abs=1e-9)


# ---------------------------------------------------------------------- anchors


def test_anchors_use_the_092_eye_height_constant():
    base, eye, top = anchors(ref_subject())
    assert base == (0.0, 0.0, 0.0)
    assert eye == (0.0, 0.92 * 1.8, 0.0)
    assert top == (0.0, 1.8, 0.0)


# ------------------------------------------------------------------- shot bands


def test_headroom_bands():
    assert headroom_band("closeup") == (0.05, 0.30)
    assert headroom_band("medium") == (0.10, 0.45)
    assert headroom_band("wide") == (0.20, 0.70)
    assert headroom_band("nonsense") == (0.10, 0.45)  # defaults to medium


def test_shot_size_bands():
    assert shot_size_ok(0.8, "closeup")[0] is True
    assert shot_size_ok(0.5, "closeup")[0] is False
    assert shot_size_ok(0.5, "medium")[0] is True
    assert shot_size_ok(0.9, "medium")[0] is False
    assert shot_size_ok(0.3, "wide")[0] is True
    assert shot_size_ok(0.6, "wide")[0] is False


def test_size_target_mid():
    assert size_target_mid("closeup") == 0.85
    assert size_target_mid("medium") == 0.55
    assert size_target_mid("wide") == 0.30


def test_shot_weights_match_the_spec_table():
    w = shot_weights("medium")
    assert w["in_frame"] == 1
    assert w["rule_of_thirds"] == 0.8
    assert w["headroom"] == 0.7
    assert w["shot_size"] == 1.0
    assert shot_weights("nonsense") == shot_weights("medium")


# ------------------------------------------------------------ serialisation


def test_campose_round_trip():
    cam = ref_camera()
    assert CamPose.from_dict(cam.to_dict()).to_dict() == cam.to_dict()


def test_subject_round_trip():
    s = ref_subject()
    assert Subject.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_intent_from_none_is_default():
    it = ShotIntent.from_dict(None)
    assert it.angle == "eye" and it.center is False and it.dutch_deg == 0.0
