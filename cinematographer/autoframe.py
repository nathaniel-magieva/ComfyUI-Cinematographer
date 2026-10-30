"""Cinematographer — the auto-framer, with the convergence check the original lacks.

A port of the reference ``AutoFrameCamera`` solver, **plus a fix**.

The reference implementation runs exactly 24 iterations and returns the 24th
iterate's report *unconditionally*. There is no convergence test and no early
exit, so nothing guarantees ``overall_pass`` — describing it as a solver that
"finds a compliant camera pose" is overstated. This port:

* exits early as soon as the frame passes,
* reports ``converged`` honestly,
* reports the iteration count actually used,
* reports the residual (which rules were still failing) when it does not converge.

That difference is the point: a demo that shows a *guarantee* beats a demo that
shows a number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .framing import evaluate_framing
from .geometry import (
    CamPose,
    FramingReport,
    ShotIntent,
    Subject,
    clamp,
    cross,
    headroom_band,
    norm,
    round3,
    size_target_mid,
    sub,
)

#: The solver's fixed vertical FOV and aspect, matching the Go source.
SOLVER_FOV_DEG = 40.0
SOLVER_ASPECT = 16.0 / 9.0

#: The Go source's iteration budget. We keep it, but we no longer *rely* on it.
MAX_ITERATIONS = 24

#: Minimum camera distance, in metres.
MIN_DISTANCE = 0.3


@dataclass
class AutoFrameResult:
    """A solved camera pose and an honest account of how it was reached."""

    camera: CamPose
    report: FramingReport
    converged: bool
    iterations: int
    residual: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "camera": self.camera.to_dict(),
            "report": self.report.to_dict(),
            "converged": self.converged,
            "iterations": self.iterations,
            "residual": self.residual,
        }


def mood_to_intent(mood: str, shot_type: str, idx: int = 0) -> ShotIntent:
    """Derive the director's intent from a shot's mood text and type.

    Lets the DP honour deliberate choices (Dutch for unease, centred hero/product
    frames, low/high angles) and alternate which third the subject sits on for
    variety. Ported from the reference ``moodToIntent``.
    """
    m = (mood or "").lower()
    it = ShotIntent(angle="eye")
    if "low-angle" in m or "power" in m or "hero" in m:
        it.angle = "low"
    elif "high angle" in m or "vulnerab" in m:
        it.angle = "high"
    if "dutch" in m or "unease" in m or "kinetic" in m:
        it.dutch_deg = 8.0
    if "product" in m or "climax" in m or "hero" in m or "symmetr" in m:
        it.center = True
    elif idx % 2 == 0:
        it.side = "left"
    else:
        it.side = "right"
    return it


def auto_frame_camera(
    subject: Subject,
    shot_type: str = "medium",
    intent: ShotIntent | None = None,
    max_iterations: int = MAX_ITERATIONS,
    early_exit: bool = True,
) -> AutoFrameResult:
    """Solve a camera pose that frames the subject per shot type and intent.

    Returns the pose, its framing report, and whether the solve actually
    converged. **Check ``converged`` before claiming the frame is compliant.**

    Set ``early_exit=False`` to reproduce the original Go behaviour exactly
    (always run the full iteration budget). That is used by the differential
    test to prove this port is faithful before the fix is applied.
    """
    it = intent or ShotIntent()
    f = 1.0 / math.tan(math.radians(SOLVER_FOV_DEG) / 2)
    eye_height = subject.base[1] + 0.92 * subject.height
    target_frac = size_target_mid(shot_type)
    dist = max(MIN_DISTANCE, subject.height * f / (2 * target_frac))
    az_r = math.radians(subject.facing_yaw_deg + it.azimuth_deg)

    height_y = eye_height
    if it.angle == "low":
        height_y = subject.base[1] + 0.4
    elif it.angle == "high":
        height_y = eye_height + 0.8

    desired = 1.0 / 3
    if it.center:
        desired = 0.0
    elif it.side == "left":
        desired = -1.0 / 3

    lo, hi = headroom_band(shot_type)
    mid_head = (lo + hi) / 2

    look = (subject.base[0], eye_height, subject.base[2])
    off_x = 0.0
    off_y = 0.0
    cam = CamPose(eye=look, target=look)
    rep = evaluate_framing(subject, cam, shot_type, it)
    iterations = 0

    for i in range(max_iterations):
        iterations = i + 1
        eye = (
            subject.base[0] + math.sin(az_r) * dist,
            height_y,
            subject.base[2] + math.cos(az_r) * dist,
        )
        fwd = norm(sub(look, eye))
        right = norm(cross(fwd, (0.0, 1.0, 0.0)))
        up = cross(right, fwd)
        target = (
            look[0] + right[0] * off_x + up[0] * off_y,
            look[1] + right[1] * off_x + up[1] * off_y,
            look[2] + right[2] * off_x + up[2] * off_y,
        )
        cam = CamPose(
            eye=eye,
            target=target,
            fov=SOLVER_FOV_DEG,
            roll_deg=it.dutch_deg,
            aspect=SOLVER_ASPECT,
        )
        rep = evaluate_framing(subject, cam, shot_type, it)

        # --- the fix: stop as soon as the frame is actually compliant ---
        if early_exit and rep.overall_pass:
            break

        ex = rep.value("rule_of_thirds")
        head = rep.value("headroom")
        frac = rep.value("shot_size")

        if frac > 0.01:  # size is proportional to 1/dist (damped)
            dist *= 1 + 0.6 * (frac / target_frac - 1)
        dist = max(MIN_DISTANCE, dist)

        # Offsets are along the camera's own axes, so the sign is consistent for
        # any facing: aim +right moves the subject left (ndcX down); aim +up moves
        # the subject down (headroom up).
        off_x += 0.6 * (ex - desired) * dist * SOLVER_ASPECT / f
        off_y += 0.6 * (mid_head - head) * dist / f
        off_x = clamp(off_x, -0.8 * dist, 0.8 * dist)
        off_y = clamp(off_y, -0.6 * dist, 0.6 * dist)

    residual = [
        f"{s.rule}={s.value:g}" for s in rep.failures() if s.weight >= 0.8
    ]
    return AutoFrameResult(
        camera=cam,
        report=rep,
        converged=rep.overall_pass,
        iterations=iterations,
        residual=residual,
    )


def autoframe_summary(result: AutoFrameResult) -> str:
    """A one-line account of the solve — including when it did not converge."""
    if result.converged:
        return (
            f"CONVERGED in {result.iterations} iteration(s) - "
            f"{result.report.shot_type} frame passes all weighted rules"
        )
    return (
        f"NOT CONVERGED after {result.iterations} iteration(s) - "
        f"still failing: {', '.join(result.residual) or 'unknown'}"
    )
