"""Cinematographer — Choros, the sequence-level continuity engine.

A faithful port of the reference ``EvaluateContinuity``.

Single-shot geometry can be perfect and the **cut** can still break. These rules
compare *consecutive* shots, not one frame:

* **180_axis** — the camera must stay on one side of the action line. Crossing it
  flips the subject's screen direction between cuts.
* **30_degree** — consecutive shots of the same subject must change the camera
  angle by at least 30 degrees, or the cut reads as a jump.

This is the direct answer to the failure Higgsfield's own consistency guide
concedes: *"AI video distortion is not a quality problem. It is a memory
problem... each new generation is a fresh context."*

Eyeline is a third continuity rule in the engine, but it needs two subjects per
shot and lives per-shot in ``scene.py`` — the reference keeps that split, and so
do we.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import CamPose, Vec3

#: The two rules Choros enforces across a cut.
CONTINUITY_RULES = ("180_axis", "30_degree")

#: Minimum camera-angle change between consecutive shots, in degrees.
MIN_ANGLE_CHANGE_DEG = 30.0


@dataclass
class ContinuityShot:
    """One shot's continuity-relevant state."""

    shot_number: int
    base: Vec3  # primary subject world position
    yaw_deg: float  # subject facing (0 = +Z)
    camera: CamPose

    def to_dict(self) -> dict:
        return {
            "shot_number": self.shot_number,
            "base": list(self.base),
            "yaw_deg": self.yaw_deg,
            "camera": self.camera.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContinuityShot":
        return cls(
            shot_number=int(d.get("shot_number", 0)),
            base=tuple(d["base"]),  # type: ignore[arg-type]
            yaw_deg=float(d.get("yaw_deg", 0.0)),
            camera=CamPose.from_dict(d["camera"]),
        )


@dataclass
class ContinuityIssue:
    """One verdict on a consecutive pair."""

    rule: str  # "180_axis" | "30_degree"
    shot_a: int
    shot_b: int
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "shot_a": self.shot_a,
            "shot_b": self.shot_b,
            "pass": self.passed,
            "detail": self.detail,
        }


def cam_azimuth_deg(base: Vec3, eye: Vec3) -> float:
    """The camera's bearing around the subject (0 = camera on +Z of the subject)."""
    return math.degrees(math.atan2(eye[0] - base[0], eye[2] - base[2]))


def axis_side(base: Vec3, yaw_deg: float, eye: Vec3) -> float:
    """Which side of the subject's facing line (the action line) the camera is on.

    Returns +1 or -1. A flip between consecutive shots is a 180-degree break.
    """
    fx, fz = math.sin(math.radians(yaw_deg)), math.cos(math.radians(yaw_deg))
    nx, nz = fz, -fx  # the action line's perpendicular
    d = (eye[0] - base[0]) * nx + (eye[2] - base[2]) * nz
    return 1.0 if d >= 0 else -1.0


def ang_delta(a: float, b: float) -> float:
    """The smallest absolute angle between two bearings, in [0, 180]."""
    d = math.fmod(abs(a - b), 360.0)
    if d > 180:
        d = 360 - d
    return d


def evaluate_continuity(shots: list[ContinuityShot]) -> list[ContinuityIssue]:
    """Check each consecutive pair for the 180-degree axis rule and the 30-degree rule."""
    out: list[ContinuityIssue] = []
    for i in range(1, len(shots)):
        a, b = shots[i - 1], shots[i]

        # 180 / axis rule: the camera must stay on one side of the action line.
        side_a = axis_side(a.base, a.yaw_deg, a.camera.eye)
        side_b = axis_side(b.base, b.yaw_deg, b.camera.eye)
        axis_pass = side_a == side_b
        axis_detail = (
            "camera stays on one side of the action line"
            if axis_pass
            else "axis crossed - the subject's screen direction flips between the cuts"
        )
        out.append(
            ContinuityIssue("180_axis", a.shot_number, b.shot_number, axis_pass, axis_detail)
        )

        # 30 rule: consecutive shots of the same subject must change the camera
        # angle by >30 degrees (and reposition), else the cut reads as a jump.
        d = ang_delta(
            cam_azimuth_deg(a.base, a.camera.eye),
            cam_azimuth_deg(b.base, b.camera.eye),
        )
        deg_pass = d >= MIN_ANGLE_CHANGE_DEG
        out.append(
            ContinuityIssue(
                "30_degree",
                a.shot_number,
                b.shot_number,
                deg_pass,
                f"camera angle changed {d:.0f} deg "
                f"(need >={MIN_ANGLE_CHANGE_DEG:.0f} deg to avoid a jump cut)",
            )
        )
    return out


def continuity_summary(issues: list[ContinuityIssue]) -> str:
    """A one-line verdict across the whole sequence."""
    if not issues:
        return "no consecutive shots to check"
    failed = [i for i in issues if not i.passed]
    if not failed:
        return f"PASS - {len(issues)} continuity checks across {len(issues) // 2} cut(s)"
    parts = [f"{i.rule} (shot {i.shot_a}->{i.shot_b})" for i in failed]
    return f"FAIL - {len(failed)} of {len(issues)} checks: " + ", ".join(parts)
