"""Cinematographer — geometry core.

A faithful Python port of the deterministic half of a production cinematography
engine that scores a camera pose against a named set of framing rules.

Everything here is pure stdlib and has **no ComfyUI dependency** — that is a hard
requirement (spec §8), because it is what makes the rules testable and reusable.

Conventions
-----------
* All world distances are **metres**.
* All angles at this API boundary are **degrees**.
* NDC is x, y in [-1, 1] with the frame edges at +/-1 and **y up**
  (screen-top = +1).
* The subject's *eye anchor* sits at ``0.92 * height`` — this is load-bearing,
  not a rounding choice. See ``anchors()``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

Vec3 = tuple[float, float, float]

# --------------------------------------------------------------------------
# Vector helpers — mirroring the reference renderer's vector primitives
# --------------------------------------------------------------------------


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: Vec3) -> Vec3:
    """Normalise. A degenerate vector returns (0, 0, 1), matching the Go source."""
    length = math.sqrt(dot(a, a))
    if length < 1e-9:
        return (0.0, 0.0, 1.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def round3(v: float) -> float:
    """Round to 3 dp — the reported precision of every measured value."""
    return round(v * 1000) / 1000


# --------------------------------------------------------------------------
# Scene primitives
# --------------------------------------------------------------------------


@dataclass
class CamPose:
    """A camera placement to evaluate (any keyframe of a move)."""

    eye: Vec3
    target: Vec3
    focal_mm: float = 35.0
    sensor_mm: float = 36.0  # horizontal aperture (sensor width)
    aspect: float = 16.0 / 9.0
    roll_deg: float = 0.0  # camera roll about the optical axis (Dutch); 0 = level
    fov: float = 0.0  # vertical FOV in degrees; if > 0 used directly

    def to_dict(self) -> dict:
        return {
            "eye": list(self.eye),
            "target": list(self.target),
            "focal_mm": self.focal_mm,
            "sensor_mm": self.sensor_mm,
            "aspect": self.aspect,
            "roll_deg": self.roll_deg,
            "fov": self.fov,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CamPose":
        return cls(
            eye=tuple(d["eye"]),  # type: ignore[arg-type]
            target=tuple(d["target"]),  # type: ignore[arg-type]
            focal_mm=float(d.get("focal_mm", 35.0)),
            sensor_mm=float(d.get("sensor_mm", 36.0)),
            aspect=float(d.get("aspect", 16.0 / 9.0)),
            roll_deg=float(d.get("roll_deg", 0.0)),
            fov=float(d.get("fov", 0.0)),
        )


@dataclass
class Subject:
    """The framed entity, from the scene graph (feet position + height)."""

    name: str
    base: Vec3  # feet, world space
    height: float  # metres
    facing_yaw_deg: float = 0.0  # direction the subject faces; 0 = +Z

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base": list(self.base),
            "height": self.height,
            "facing_yaw_deg": self.facing_yaw_deg,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Subject":
        return cls(
            name=str(d.get("name", "subject")),
            base=tuple(d["base"]),  # type: ignore[arg-type]
            height=float(d["height"]),
            facing_yaw_deg=float(d.get("facing_yaw_deg", 0.0)),
        )


@dataclass
class ShotIntent:
    """The director's intent — so the DP does not flag deliberate choices.

    A Dutch angle for unease, a centred symmetrical frame, a low hero angle: all
    of these are *correct* when intended, and wrong when accidental.
    """

    angle: str = "eye"  # "low" | "high" | "eye"
    side: str = "center"  # "left" | "right" | "center"
    center: bool = False  # intentionally centred (symmetry) — relaxes thirds
    dutch_deg: float = 0.0  # intended camera roll
    azimuth_deg: float = 0.0  # camera orbit offset from the subject's front

    def to_dict(self) -> dict:
        return {
            "angle": self.angle,
            "side": self.side,
            "center": self.center,
            "dutch_deg": self.dutch_deg,
            "azimuth_deg": self.azimuth_deg,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "ShotIntent":
        if not d:
            return cls()
        return cls(
            angle=str(d.get("angle", "eye")),
            side=str(d.get("side", "center")),
            center=bool(d.get("center", False)),
            dutch_deg=float(d.get("dutch_deg", 0.0)),
            azimuth_deg=float(d.get("azimuth_deg", 0.0)),
        )


@dataclass
class FramingScore:
    """One rule's verdict: a measured value, a pass/fail, and a correction lever."""

    rule: str
    passed: bool
    value: float
    target: str
    weight: float
    correction: str = ""

    def to_dict(self) -> dict:
        d = {
            "rule": self.rule,
            "pass": self.passed,
            "value": self.value,
            "target": self.target,
            "weight": self.weight,
        }
        if self.correction:
            d["correction"] = self.correction
        return d


@dataclass
class FramingReport:
    """The DP's structured, auditable judgement of a frame."""

    subject: str
    shot_type: str
    scores: list[FramingScore] = field(default_factory=list)
    overall_pass: bool = True

    def score(self, rule: str) -> FramingScore | None:
        for s in self.scores:
            if s.rule == rule:
                return s
        return None

    def value(self, rule: str) -> float:
        s = self.score(rule)
        return s.value if s else 0.0

    def failures(self) -> list[FramingScore]:
        return [s for s in self.scores if not s.passed]

    def corrections(self) -> list[str]:
        """The correction levers, in rule order, for every failing rule."""
        return [s.correction for s in self.scores if not s.passed and s.correction]

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "shot_type": self.shot_type,
            "scores": [s.to_dict() for s in self.scores],
            "overall_pass": self.overall_pass,
        }


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

Projector = Callable[[Vec3], tuple[float, float, float, bool]]


def projector(cam: CamPose) -> Projector:
    """Map a world point to NDC (x, y in [-1, 1]) plus depth and an in-front flag.

    Mirrors the reference ``projector()``.
    """
    eye = cam.eye
    fwd = norm(sub(cam.target, eye))
    right = norm(cross(fwd, (0.0, 1.0, 0.0)))
    up = cross(right, fwd)

    aspect = cam.aspect if cam.aspect > 0 else 16.0 / 9.0
    sensor = cam.sensor_mm if cam.sensor_mm > 0 else 36.0
    focal = cam.focal_mm if cam.focal_mm > 0 else 35.0

    if cam.roll_deg != 0:
        # Dutch: rotate the right/up basis about the optical axis.
        r = math.radians(cam.roll_deg)
        cs, sn = math.cos(r), math.sin(r)
        right, up = (
            (
                right[0] * cs + up[0] * sn,
                right[1] * cs + up[1] * sn,
                right[2] * cs + up[2] * sn,
            ),
            (
                -right[0] * sn + up[0] * cs,
                -right[1] * sn + up[1] * cs,
                -right[2] * sn + up[2] * cs,
            ),
        )

    vfov = 2 * math.atan((sensor / aspect) / (2 * focal))
    if cam.fov > 0:
        vfov = math.radians(cam.fov)
    f = 1.0 / math.tan(vfov / 2)

    def project(p: Vec3) -> tuple[float, float, float, bool]:
        d = sub(p, eye)
        cx, cy, cz = dot(d, right), dot(d, up), dot(d, fwd)
        if cz <= 1e-4:
            return (0.0, 0.0, cz, False)
        return ((cx / cz) * (f / aspect), (cy / cz) * f, cz, True)

    return project


def anchors(s: Subject) -> tuple[Vec3, Vec3, Vec3]:
    """Return (base, eye, top) world anchors.

    The eye anchor is at **0.92 x height** — the Go source's constant. Changing it
    changes every framing measurement, so it is deliberately not configurable.
    """
    base = s.base
    eye = (s.base[0], s.base[1] + 0.92 * s.height, s.base[2])
    top = (s.base[0], s.base[1] + s.height, s.base[2])
    return base, eye, top


def base3(s: Subject) -> Vec3:
    return anchors(s)[0]


def eye_pt(s: Subject) -> Vec3:
    return anchors(s)[1]


def top_pt(s: Subject) -> Vec3:
    return anchors(s)[2]


# --------------------------------------------------------------------------
# Shot-type bands
# --------------------------------------------------------------------------

SHOT_TYPES = ("closeup", "medium", "wide")

#: rule -> {shot_type -> weight}. Mirrors the reference ``ruleWeights``.
RULE_WEIGHTS: dict[str, dict[str, float]] = {
    "closeup": {
        "in_frame": 1,
        "rule_of_thirds": 1.0,
        "headroom": 1.0,
        "shot_size": 1.0,
        "lead_room": 0.4,
        "negative_space": 0.3,
        "camera_angle": 0.3,
        "level": 0.5,
    },
    "medium": {
        "in_frame": 1,
        "rule_of_thirds": 0.8,
        "headroom": 0.7,
        "shot_size": 1.0,
        "lead_room": 0.4,
        "negative_space": 0.3,
        "camera_angle": 0.3,
        "level": 0.5,
    },
    "wide": {
        "in_frame": 1,
        "rule_of_thirds": 0.6,
        "headroom": 0.4,
        "shot_size": 1.0,
        "lead_room": 0.3,
        "negative_space": 0.4,
        "camera_angle": 0.3,
        "level": 0.5,
    },
}

#: A rule at or above this weight must pass for the frame to pass overall.
OVERALL_PASS_WEIGHT = 0.8


def shot_weights(shot_type: str) -> dict[str, float]:
    return RULE_WEIGHTS.get(shot_type, RULE_WEIGHTS["medium"])


def headroom_band(shot_type: str) -> tuple[float, float]:
    if shot_type == "closeup":
        return 0.05, 0.30
    if shot_type == "wide":
        return 0.20, 0.70
    return 0.10, 0.45


def shot_size_ok(frac: float, shot_type: str) -> tuple[bool, str]:
    """Target strings match the Go source verbatim so the differential check is exact."""
    if shot_type == "closeup":
        return frac >= 0.7, "subject \u226570% of frame height (CU)"
    if shot_type == "wide":
        return 0.15 <= frac <= 0.45, "subject 15\u201345% of frame height (WS)"
    return 0.4 <= frac <= 0.75, "subject 40\u201375% of frame height (MS)"


def size_target_mid(shot_type: str) -> float:
    """Desired subject screen-height fraction per shot type (the solver's target)."""
    if shot_type == "closeup":
        return 0.85
    if shot_type == "wide":
        return 0.30
    return 0.55


def _corr_if(cond: bool, s: str) -> str:
    return s if cond else ""


def _btf(b: bool) -> float:
    return 1.0 if b else 0.0
