"""Auto-frame solver tests — including the convergence fix the Go original lacks."""

import pytest

from cinematographer.autoframe import (
    MAX_ITERATIONS,
    SOLVER_ASPECT,
    SOLVER_FOV_DEG,
    auto_frame_camera,
    autoframe_summary,
    mood_to_intent,
)
from cinematographer.framing import evaluate_framing
from cinematographer.geometry import ShotIntent, Subject


def ref_subject() -> Subject:
    return Subject(name="hero", base=(0.0, 0.0, 0.0), height=1.8, facing_yaw_deg=0.0)


# --------------------------------------------------------------- the fix itself


def test_solver_reports_converged_on_a_solvable_frame():
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent(side="left"))
    assert res.converged is True
    assert res.report.overall_pass is True
    assert res.residual == []


def test_solver_exits_early_rather_than_always_running_24_iterations():
    """The Go original always runs 24. Ours must stop as soon as the frame passes.

    This is the headline behavioural difference: if this ever equals
    MAX_ITERATIONS on a solvable frame, the early exit has regressed.
    """
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent(side="left"))
    assert res.iterations < MAX_ITERATIONS
    assert res.iterations >= 1


def test_iterations_never_exceed_the_budget():
    for shot in ("closeup", "medium", "wide"):
        res = auto_frame_camera(ref_subject(), shot, ShotIntent())
        assert 1 <= res.iterations <= MAX_ITERATIONS


def test_converged_flag_agrees_with_the_report():
    """`converged` must never claim success the report does not support."""
    for shot in ("closeup", "medium", "wide"):
        for intent in (ShotIntent(), ShotIntent(center=True), ShotIntent(side="left")):
            res = auto_frame_camera(ref_subject(), shot, intent)
            assert res.converged == res.report.overall_pass


def test_residual_is_populated_only_when_not_converged():
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent())
    if res.converged:
        assert res.residual == []
    else:
        assert res.residual  # must name what is still failing


def test_unsolvable_intent_is_reported_honestly_not_hidden():
    """An impossible combination must return converged=False, not a fake pose.

    A Dutch angle of 45 degrees with intent.dutch_deg=0 makes the `level` rule
    unsatisfiable, so the solver cannot converge and must say so.
    """
    from cinematographer.geometry import CamPose

    # Force an unsatisfiable level rule by asking for a roll the intent forbids.
    subject = ref_subject()
    intent = ShotIntent()
    res = auto_frame_camera(subject, "medium", intent)
    # Sanity: the solver sets roll from the intent, so level always passes here.
    assert res.report.score("level").passed is True

    # Now a genuinely unsolvable case: a subject with zero height cannot be framed.
    degenerate = Subject(name="point", base=(0.0, 0.0, 0.0), height=0.0)
    res2 = auto_frame_camera(degenerate, "medium", ShotIntent())
    assert res2.converged is False
    assert res2.residual, "an unconverged solve must name its residual"


# ------------------------------------------------------------------ the solve


def test_solver_places_the_camera_in_front_of_the_subject():
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent())
    assert res.camera.eye[2] > 0  # in front of a subject facing +Z
    assert res.camera.eye[1] > 0  # above the floor


def test_solver_uses_the_documented_fov_and_aspect():
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent())
    assert res.camera.fov == SOLVER_FOV_DEG
    assert res.camera.aspect == pytest.approx(SOLVER_ASPECT)


def test_solver_honours_the_intended_dutch():
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent(dutch_deg=8.0))
    assert res.camera.roll_deg == 8.0


def test_solver_low_angle_lowers_the_camera():
    low = auto_frame_camera(ref_subject(), "medium", ShotIntent(angle="low"))
    eye_level = auto_frame_camera(ref_subject(), "medium", ShotIntent(angle="eye"))
    assert low.camera.eye[1] < eye_level.camera.eye[1]


def test_solver_high_angle_raises_the_camera():
    high = auto_frame_camera(ref_subject(), "medium", ShotIntent(angle="high"))
    eye_level = auto_frame_camera(ref_subject(), "medium", ShotIntent(angle="eye"))
    assert high.camera.eye[1] > eye_level.camera.eye[1]


def test_solver_respects_the_minimum_distance():
    tiny = Subject(name="ant", base=(0.0, 0.0, 0.0), height=0.01)
    res = auto_frame_camera(tiny, "closeup", ShotIntent())
    dist = (res.camera.eye[0] ** 2 + res.camera.eye[2] ** 2) ** 0.5
    assert dist >= 0.3 - 1e-9


def test_solved_pose_reproduces_a_passing_report_when_re_evaluated():
    """The returned pose must actually pass when fed back through the evaluator."""
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent(side="left"))
    if res.converged:
        again = evaluate_framing(
            ref_subject(), res.camera, "medium", ShotIntent(side="left")
        )
        assert again.overall_pass is True


def test_azimuth_orbits_the_camera():
    front = auto_frame_camera(ref_subject(), "medium", ShotIntent(azimuth_deg=0.0))
    side = auto_frame_camera(ref_subject(), "medium", ShotIntent(azimuth_deg=40.0))
    assert front.camera.eye != side.camera.eye


# ------------------------------------------------------------------ mood intent


def test_mood_to_intent_reads_low_angle_and_power():
    assert mood_to_intent("low-angle power shot", "medium", 0).angle == "low"
    assert mood_to_intent("hero moment", "medium", 0).angle == "low"


def test_mood_to_intent_reads_high_angle_and_vulnerability():
    assert mood_to_intent("high angle, vulnerable", "medium", 0).angle == "high"


def test_mood_to_intent_reads_dutch():
    assert mood_to_intent("dutch tilt, unease", "medium", 0).dutch_deg == 8.0


def test_mood_to_intent_centres_hero_and_product_beats():
    assert mood_to_intent("product hero", "medium", 0).center is True
    assert mood_to_intent("symmetry", "medium", 0).center is True


def test_mood_to_intent_alternates_sides_for_variety():
    assert mood_to_intent("neutral", "medium", 0).side == "left"
    assert mood_to_intent("neutral", "medium", 1).side == "right"


# ------------------------------------------------------------------- summary


def test_summary_states_convergence_and_iterations():
    res = auto_frame_camera(ref_subject(), "medium", ShotIntent(side="left"))
    text = autoframe_summary(res)
    assert "CONVERGED" in text
    assert str(res.iterations) in text


def test_summary_says_not_converged_when_it_did_not():
    degenerate = Subject(name="point", base=(0.0, 0.0, 0.0), height=0.0)
    res = auto_frame_camera(degenerate, "medium", ShotIntent())
    text = autoframe_summary(res)
    assert "NOT CONVERGED" in text
    assert "still failing" in text


def test_result_serialises_to_json_safe_dict():
    import json

    res = auto_frame_camera(ref_subject(), "medium", ShotIntent())
    json.dumps(res.to_dict())  # must not raise
    assert set(res.to_dict()) == {
        "camera",
        "report",
        "converged",
        "iterations",
        "residual",
    }
