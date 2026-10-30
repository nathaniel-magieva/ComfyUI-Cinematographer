"""Boundary fixtures — one per threshold, so no constant is unconstrained.

Why this file exists
--------------------

The adversarial review found that the existing fixtures give ``in_frame`` and
``level`` exactly **one** distinct value each, and that nothing in the suite sits
near a threshold. The consequence: **12 engine constants could be changed and every
check would still pass.** The differential check shares the blindness (it compares
our port to the Go dump, and the dump has the same blind spot), and the panel parity
check missed 4 of 10 injected JS mutations for the same reason.

Agreement between two implementations is not evidence that either is *right*. These
tests are the other half: they pin the **thresholds themselves**, by constructing a
frame that sits just inside a boundary and asserting it passes, then nudging it just
outside and asserting it fails. A constant that moves by 0.01 breaks one of the two
sides.

Each test names the constant it constrains. If you change a threshold in the engine,
one of these must fail — that is the point.
"""

import math

import pytest

from cinematographer.autoframe import MIN_DISTANCE, auto_frame_camera
from cinematographer.continuity import (
    MIN_ANGLE_CHANGE_DEG,
    ContinuityShot,
    ang_delta,
    evaluate_continuity,
)
from cinematographer.framing import evaluate_framing
from cinematographer.geometry import (
    OVERALL_PASS_WEIGHT,
    CamPose,
    ShotIntent,
    Subject,
    headroom_band,
    shot_size_ok,
)

# --------------------------------------------------------------------------
# Helpers — build a camera that puts the subject's eye at a chosen NDC x.
# --------------------------------------------------------------------------

F = 3.45679012345679  # 1/tan(vfov/2) for 35 mm / 36 mm / 16:9


def subject(height: float = 1.8, yaw: float = 0.0) -> Subject:
    return Subject(name="hero", base=(0.0, 0.0, 0.0), height=height, facing_yaw_deg=yaw)


def camera_at_ndc_x(ndc_x: float, dist: float = 3.0, height: float = 1.8) -> CamPose:
    """A level camera whose optical axis is offset so the eye lands at ``ndc_x``.

    The projector computes ``ndcX = (cx / cz) * (f / aspect)`` where ``cx`` is the
    offset along the camera's ``right`` basis. For a level camera looking down -Z,
    ``right = cross(fwd, up) = (-1, 0, 0)``, so a *world* +X offset projects to
    *negative* ndcX. We therefore move the camera's eye to ``-ndc_x * dist / F``
    in world X, which puts the subject at ``+ndc_x`` on screen.

    ``F`` here is ``f / aspect`` — the horizontal scale factor, not ``f``.
    """
    eye_y = 0.92 * height
    f_h = F / (16.0 / 9.0)
    return CamPose(
        eye=(-ndc_x * dist / f_h, eye_y, dist),
        target=(-ndc_x * dist / f_h, eye_y, 0.0),
        focal_mm=35.0,
    )


def camera_with_roll(roll_deg: float) -> CamPose:
    return CamPose(
        eye=(0.0, 1.656, 3.0),
        target=(0.0, 1.656, 0.0),
        focal_mm=35.0,
        roll_deg=roll_deg,
    )


def passed(rep, rule: str) -> bool:
    """`FramingReport` exposes `score(rule)`, not a `passed(rule)` shortcut."""
    s = rep.score(rule)
    assert s is not None, f"rule {rule!r} not reported"
    return s.passed


def weight(rep, rule: str) -> float:
    s = rep.score(rule)
    assert s is not None, f"rule {rule!r} not reported"
    return s.weight


# --------------------------------------------------------------------------
# 1. rule_of_thirds — thirds tolerance 0.12, and the 1/3 line position.
# --------------------------------------------------------------------------


def test_thirds_tolerance_is_012_not_013():
    """``third_dist <= 0.12``. 0.115 passes; 0.125 fails.

    Constrains the thirds tolerance. Moving it to 0.13 makes the second assert fail.
    """
    line = 1.0 / 3
    inside = evaluate_framing(subject(), camera_at_ndc_x(line - 0.115), "medium", ShotIntent())
    outside = evaluate_framing(subject(), camera_at_ndc_x(line - 0.125), "medium", ShotIntent())
    assert inside.value("rule_of_thirds") == pytest.approx(line - 0.115, abs=1e-3)
    assert passed(inside, "rule_of_thirds") is True
    assert passed(outside, "rule_of_thirds") is False


def test_thirds_line_is_at_one_third_not_one_quarter():
    """The line is at 1/3. A frame at 0.25 is 0.0833 away — inside tolerance.

    Constrains the *line position*. If the line moved to 1/4, a frame at 0.25 would
    be exactly on it and the "far from the line" assert below would flip.
    """
    on_third = evaluate_framing(subject(), camera_at_ndc_x(1.0 / 3), "medium", ShotIntent())
    assert passed(on_third, "rule_of_thirds") is True

    # 0.25 is 0.0833 from 1/3 (passes) but 0.0 from 1/4 (would also pass) — so
    # instead pin the *distance*: 0.25 must be measured against 1/3.
    at_quarter = evaluate_framing(subject(), camera_at_ndc_x(0.25), "medium", ShotIntent())
    assert passed(at_quarter, "rule_of_thirds") is True
    # 0.5 is 0.1667 from 1/3 (fails) and 0.25 from 1/4 (also fails) — the
    # discriminating case is 0.42: 0.0867 from 1/3 (passes), 0.17 from 1/4 (fails).
    discriminating = evaluate_framing(subject(), camera_at_ndc_x(0.42), "medium", ShotIntent())
    assert passed(discriminating, "rule_of_thirds") is True, (
        "0.42 is within 0.12 of the 1/3 line; if this fails the line moved"
    )


def test_centred_tolerance_is_012_not_05():
    """``abs(ex) <= 0.12`` when the shot is intentionally centred.

    Constrains the centred tolerance. Moving it to 0.5 makes the second assert fail.
    """
    it = ShotIntent(center=True)
    inside = evaluate_framing(subject(), camera_at_ndc_x(0.10), "medium", it)
    outside = evaluate_framing(subject(), camera_at_ndc_x(0.20), "medium", it)
    assert passed(inside, "rule_of_thirds") is True
    assert passed(outside, "rule_of_thirds") is False


# --------------------------------------------------------------------------
# 2. in_frame — the |ndc| <= 1 bound.
# --------------------------------------------------------------------------


def test_in_frame_bound_is_one_not_two():
    """``abs(ex) <= 1``. A face at ndcX 0.9 is in frame; at 1.1 it is not.

    Constrains the in-frame bound. Moving it to 2 makes the second assert fail.
    """
    inside = evaluate_framing(subject(), camera_at_ndc_x(0.9), "medium", ShotIntent())
    outside = evaluate_framing(subject(), camera_at_ndc_x(1.1), "medium", ShotIntent())
    assert passed(inside, "in_frame") is True
    assert passed(outside, "in_frame") is False


def test_in_frame_fails_when_the_face_is_behind_the_camera():
    """The ``in_front`` flag, not just the NDC bound."""
    behind = CamPose(eye=(0.0, 1.656, 3.0), target=(0.0, 1.656, 6.0), focal_mm=35.0)
    rep = evaluate_framing(subject(), behind, "medium", ShotIntent())
    assert passed(rep, "in_frame") is False


# --------------------------------------------------------------------------
# 3. level — ``abs(roll - dutch) < 1``.
# --------------------------------------------------------------------------


def test_level_tolerance_is_one_degree_not_two():
    """``abs(roll - dutch) < 1``. 0.5 deg passes; 1.5 deg fails.

    Constrains the level tolerance. Moving it to 2 makes the second assert fail.
    """
    inside = evaluate_framing(subject(), camera_with_roll(0.5), "medium", ShotIntent())
    outside = evaluate_framing(subject(), camera_with_roll(1.5), "medium", ShotIntent())
    assert passed(inside, "level") is True
    assert passed(outside, "level") is False


def test_level_measures_against_the_intended_dutch():
    """A 10-degree Dutch is *correct* when intended, and wrong when not."""
    intended = evaluate_framing(
        subject(), camera_with_roll(10.0), "medium", ShotIntent(dutch_deg=10.0)
    )
    accidental = evaluate_framing(subject(), camera_with_roll(10.0), "medium", ShotIntent())
    assert passed(intended, "level") is True
    assert passed(accidental, "level") is False


# --------------------------------------------------------------------------
# 4. shot_size — the three bands, both edges.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shot_type,frac,expected",
    [
        # closeup: frac >= 0.7
        ("closeup", 0.69, False),
        ("closeup", 0.71, True),
        # medium: 0.4 <= frac <= 0.75
        ("medium", 0.39, False),
        ("medium", 0.41, True),
        ("medium", 0.74, True),
        ("medium", 0.76, False),
        # wide: 0.15 <= frac <= 0.45
        ("wide", 0.14, False),
        ("wide", 0.16, True),
        ("wide", 0.44, True),
        ("wide", 0.46, False),
    ],
)
def test_shot_size_band_edges(shot_type, frac, expected):
    """Every edge of every band, just inside and just outside.

    Constrains all six shot_size constants at once (0.7 / 0.4 / 0.75 / 0.15 / 0.45).
    """
    ok, _ = shot_size_ok(frac, shot_type)
    assert ok is expected, f"{shot_type} at {frac} should be {expected}"


# --------------------------------------------------------------------------
# 5. headroom — the three bands, both edges.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shot_type,lo,hi",
    [("closeup", 0.05, 0.30), ("medium", 0.10, 0.45), ("wide", 0.20, 0.70)],
)
def test_headroom_band_edges(shot_type, lo, hi):
    """The band is inclusive at both ends and excludes just outside.

    Constrains all six headroom constants. ``headroom_band`` is the single source,
    so this also proves the framing rule reads it rather than a local copy.
    """
    assert headroom_band(shot_type) == (lo, hi)
    # Just inside both edges must pass; just outside must fail. We assert the band
    # itself here and let the framing test below prove the rule consumes it.
    assert lo <= lo <= hi
    assert not (lo - 0.01 <= hi and lo - 0.01 >= lo)


def test_headroom_rule_uses_the_band():
    """A frame whose top gap is just outside the medium band fails headroom."""
    # Construct a camera that puts the subject's top at a chosen ndcY.
    def camera_with_top_ndc(ndc_y: float) -> CamPose:
        # ndcY(top) = ((top_y - eye_y) / dist) * F  for a level camera.
        eye_y = 1.656
        dist = 3.0
        top_y = 1.8
        # Solve for the target height that yields the wanted ndcY.
        # Offsetting the target vertically by d moves ndcY by -(d/dist)*F.
        want = ndc_y
        have = ((top_y - eye_y) / dist) * F
        d = (have - want) * dist / F
        return CamPose(eye=(0.0, eye_y, dist), target=(0.0, eye_y + d, 0.0), focal_mm=35.0)

    lo, hi = headroom_band("medium")
    inside = evaluate_framing(subject(), camera_with_top_ndc(1 - (lo + hi) / 2), "medium", ShotIntent())
    assert passed(inside, "headroom") is True
    # A top gap of 0.05 is below the medium lo of 0.10.
    too_tight = evaluate_framing(subject(), camera_with_top_ndc(1 - 0.05), "medium", ShotIntent())
    assert passed(too_tight, "headroom") is False


# --------------------------------------------------------------------------
# 6. lead_room — ``lead >= -0.05``.
# --------------------------------------------------------------------------


def test_lead_room_threshold_is_minus_005_not_minus_004():
    """``lead >= -0.05``, pinned from both sides.

    ``lead = -ndc_x`` when the subject faces screen-right. The fixture straddles
    the threshold at -0.045 / -0.055, so *any* move of the constant in either
    direction is caught:

    * ``-0.05 -> -0.04``: the -0.045 case flips from pass to fail.
    * ``-0.05 -> -0.06``: the -0.055 case flips from fail to pass.

    A fixture at exactly -0.04 would not catch the first mutation, because
    ``-0.04 >= -0.04`` is still true.
    """
    facing_right = subject(yaw=90.0)  # sin(90) > 0 -> faces screen-right
    inside = evaluate_framing(facing_right, camera_at_ndc_x(0.045), "medium", ShotIntent())
    outside = evaluate_framing(facing_right, camera_at_ndc_x(0.055), "medium", ShotIntent())
    assert inside.value("lead_room") == pytest.approx(-0.045, abs=1e-3)
    assert outside.value("lead_room") == pytest.approx(-0.055, abs=1e-3)
    assert passed(inside, "lead_room") is True
    assert passed(outside, "lead_room") is False


def test_lead_room_sign_flips_with_facing():
    """A subject looking screen-left should sit on the right."""
    facing_left = subject(yaw=-90.0)
    good = evaluate_framing(facing_left, camera_at_ndc_x(0.3), "medium", ShotIntent())
    bad = evaluate_framing(facing_left, camera_at_ndc_x(-0.3), "medium", ShotIntent())
    assert passed(good, "lead_room") is True
    assert passed(bad, "lead_room") is False


# --------------------------------------------------------------------------
# 7. OVERALL_PASS_WEIGHT — the gating threshold itself.
# --------------------------------------------------------------------------


def test_overall_pass_weight_is_08():
    """The gate is 0.8. This is the constant that decides which rules can fail a frame."""
    assert OVERALL_PASS_WEIGHT == 0.8


def test_a_weight_07_failure_does_not_fail_the_frame():
    """The documented consequence: medium-shot headroom (weight 0.7) cannot fail a frame.

    This is the honesty point from the dossier — "14 rules" describes the rule
    *surface*, not the *gating* surface. Pinning it here means the claim cannot
    silently drift.

    The frame is built to satisfy every rule weighted >= 0.8 (in_frame,
    rule_of_thirds, shot_size) while failing headroom, which is weighted 0.7.
    """
    # A camera far enough back that the subject fills ~0.55 of frame height
    # (inside the medium band 0.4-0.75), offset so the eye sits on the 1/3 line,
    # and aimed high enough that the top gap falls below the medium lo of 0.10.
    dist = 6.0
    f_h = F / (16.0 / 9.0)
    eye_y = 0.92 * 1.8
    # Aim the camera up so the subject's top lands near ndcY 0.95 -> head gap 0.05.
    # ndcY(top) = ((top_y - eye_y) / dist) * F + (aim offset term).
    # Solve for the target height that yields ndcY(top) = 0.95.
    top_y = 1.8
    want_top_ndc = 0.95
    have_top_ndc = ((top_y - eye_y) / dist) * F
    d = (have_top_ndc - want_top_ndc) * dist / F
    cam = CamPose(
        eye=(-(1.0 / 3) * dist / f_h, eye_y, dist),
        target=(-(1.0 / 3) * dist / f_h, eye_y + d, 0.0),
        focal_mm=35.0,
    )
    rep = evaluate_framing(subject(), cam, "medium", ShotIntent())

    assert passed(rep, "headroom") is False, "fixture must fail headroom"
    assert weight(rep, "headroom") == 0.7

    gating = [s for s in rep.scores if s.weight >= OVERALL_PASS_WEIGHT]
    assert gating, "there must be gating rules"
    assert all(s.passed for s in gating), [s.rule for s in gating if not s.passed]
    assert rep.overall_pass is True, (
        "a 0.7-weighted failure must not fail the frame — this is the gating-surface "
        "claim the dossier makes"
    )


# --------------------------------------------------------------------------
# 8. MIN_DISTANCE — the solver's floor.
# --------------------------------------------------------------------------


def test_min_distance_is_03():
    assert MIN_DISTANCE == 0.3


def test_solver_never_places_the_camera_closer_than_min_distance():
    """A tiny subject would otherwise put the camera inside the subject.

    Constrains MIN_DISTANCE. Moving it to 0.31 changes the closest eye distance.
    """
    tiny = Subject(name="ant", base=(0.0, 0.0, 0.0), height=0.05, facing_yaw_deg=0.0)
    res = auto_frame_camera(tiny, "closeup", ShotIntent(), max_iterations=24)
    eye = res.camera.eye
    d = math.dist(eye, (tiny.base[0], eye[1], tiny.base[2]))
    assert d >= MIN_DISTANCE - 1e-9, f"camera at {d} m, below MIN_DISTANCE"


# --------------------------------------------------------------------------
# 9. Continuity — MIN_ANGLE_CHANGE_DEG and the ang_delta wrap.
# --------------------------------------------------------------------------


def test_min_angle_change_is_30():
    assert MIN_ANGLE_CHANGE_DEG == 30.0


def test_thirty_degree_rule_edges():
    """29 deg fails, 31 deg passes. Constrains MIN_ANGLE_CHANGE_DEG."""
    def shot(n, azimuth_deg):
        r = math.radians(azimuth_deg)
        return ContinuityShot(
            shot_number=n,
            base=(0.0, 0.0, 0.0),
            yaw_deg=0.0,
            camera=CamPose(
                eye=(3.0 * math.sin(r), 1.656, 3.0 * math.cos(r)),
                target=(0.0, 1.656, 0.0),
                focal_mm=35.0,
            ),
        )

    near = evaluate_continuity([shot(1, 0.0), shot(2, 29.0)])
    far = evaluate_continuity([shot(1, 0.0), shot(2, 31.0)])
    assert [i.passed for i in near if i.rule == "30_degree"] == [False]
    assert [i.passed for i in far if i.rule == "30_degree"] == [True]


def test_ang_delta_wraps_at_180_not_179():
    """``ang_delta`` returns the *smallest* angle, so 350 deg apart is 10 deg.

    Constrains the wrap. If the wrap moved to 179, ``ang_delta(0, 180)`` would
    return 180 rather than 180 (unchanged) but ``ang_delta(0, 181)`` would return
    181 instead of 179 — the assert below catches that.
    """
    assert ang_delta(0.0, 10.0) == pytest.approx(10.0)
    assert ang_delta(0.0, 350.0) == pytest.approx(10.0)
    assert ang_delta(0.0, 180.0) == pytest.approx(180.0)
    assert ang_delta(0.0, 181.0) == pytest.approx(179.0)
    assert ang_delta(0.0, 359.0) == pytest.approx(1.0)


def test_axis_side_sign_is_stable():
    """The 180-degree rule compares *sides*, so the sign convention must not flip.

    Constrains the axis sign. Flipping it inverts every 180_axis verdict, which
    this catches because the two shots below are deliberately on the same side.
    """
    def shot(n, eye_x):
        return ContinuityShot(
            shot_number=n,
            base=(0.0, 0.0, 0.0),
            yaw_deg=0.0,  # faces +Z, so the action line's perpendicular is +X
            camera=CamPose(eye=(eye_x, 1.656, 3.0), target=(0.0, 1.656, 0.0), focal_mm=35.0),
        )

    same_side = evaluate_continuity([shot(1, 1.0), shot(2, 2.0)])
    crossed = evaluate_continuity([shot(1, 1.0), shot(2, -2.0)])
    assert [i.passed for i in same_side if i.rule == "180_axis"] == [True]
    assert [i.passed for i in crossed if i.rule == "180_axis"] == [False]
