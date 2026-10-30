"""Cinematographer — Stage 5 POST: grade, extend and edit, as *descriptions*.

**The architectural catch, stated up front.** In the real product, Extend and
Edit are **not Cinema Studio endpoints**. The API documentation says it plainly:
"This endpoint produces a new video. Editing and extension use the separate
Seedance 2.5 endpoints." So two of the four features advertised on the post
panel are, at the API layer, calls to a *different* model's endpoints. We
implement them here as graph stages because the app presents them as one panel,
and we say so rather than implying we are reproducing a Cinema Studio capability
that does not exist. The colour-grade controls, by contrast, *are* documented as
Cinema Studio's own.

**This module never touches a pixel.** ``apply_grade`` returns a *plan* — an
ordered list of deltas — not a graded image. That is deliberate: the node pack
describes the grade, and the graph applies it with whatever image nodes are wired
in. Nothing here imports numpy, torch, PIL or ComfyUI, and nothing here can claim
a frame was graded.

What is sourced and what is invented
------------------------------------

* The seven grade control **names** are documented (temperature, contrast,
  saturation, sharpness, film grain, highlights, exposure). See ``GRADE_PARAMS``.
* The **ranges, units and neutral points** are **invented — no published source**.
  The source documents the control names and nothing about their scale. See
  ``GRADE_RANGES`` and ``GRADE_NEUTRAL``.
* The Sequel / Prequel **modes** are documented: Sequel continues after the end,
  Prequel leads in before the start. See ``EXTEND_MODES``.
* The extension **duration range** is sourced: the generation bar documents 4-30 s.
  See ``EXTEND_DURATION_RANGE``.
* The **overlap** ceiling is **invented — no published source**: the source does
  not mention an overlap at all. See ``EXTEND_OVERLAP_MAX_FRAMES``.
* The audit weights in ``POST_RULE_WEIGHTS`` are **invented — no published
  source**.

Two honesty rules, carried over from the rest of the pack:

* Every threshold is a named module constant, and the comment says where the
  number came from. Where it is a judgement call rather than a published figure,
  the comment says **invented — no published source**.
* A stage that is absent is reported as absent. ``PostPlan.is_noop()`` is True
  only when there is genuinely nothing to do, and it never claims a stage ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import OVERALL_PASS_WEIGHT

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: The seven documented colour-grade controls, in evaluation order. The *names*
#: are sourced (the walkthrough's post-generation table lists exactly these
#: seven); nothing about their scale is.
GRADE_PARAMS = (
    "temperature",
    "contrast",
    "saturation",
    "sharpness",
    "film_grain",
    "highlights",
    "exposure",
)

#: Neutral value per control: 0.0 for all seven. A neutral grade is a no-op, so
#: ``GradeSettings()`` describes "change nothing".
#: invented — no published source: the source names the controls and does not say
#: what their neutral point is. 0.0 is the reading that makes a neutral grade a
#: no-op, which is the only choice that cannot silently alter a frame.
GRADE_NEUTRAL: dict[str, float] = {
    "temperature": 0.0,
    "contrast": 0.0,
    "saturation": 0.0,
    "sharpness": 0.0,
    "film_grain": 0.0,
    "highlights": 0.0,
    "exposure": 0.0,
}

#: Legal range per control, as ``(min, max)``.
#: invented — no published source. The source documents the seven control names
#: and nothing about their ranges or units, so these are our choices:
#: temperature / contrast / saturation / highlights are normalised bipolar
#: controls over -1..+1 (cool..warm, flat..punchy, muted..vivid, crushed..lifted);
#: sharpness and film_grain are unipolar over 0..1 (none..maximum); exposure is in
#: stops over -2..+2, because a two-stop bracket is the conventional photographic
#: working range — a convention, not a measurement of the source product.
GRADE_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (-1.0, 1.0),
    "contrast": (-1.0, 1.0),
    "saturation": (-1.0, 1.0),
    "sharpness": (0.0, 1.0),
    "film_grain": (0.0, 1.0),
    "highlights": (-1.0, 1.0),
    "exposure": (-2.0, 2.0),
}

#: The two documented extension modes. Sequel continues after the end of the
#: clip; Prequel leads in before its start. Sourced.
EXTEND_MODES = ("sequel", "prequel")

#: Legal extension length in seconds. Sourced: the generation bar documents a
#: 4-30 s duration range.
EXTEND_DURATION_RANGE = (4.0, 30.0)

#: Default extension length in seconds. Sourced: the API's documented default
#: duration is 5.
DEFAULT_EXTEND_DURATION_S = 5.0

#: Film-standard frame rate. Used only to express the overlap ceiling in seconds.
#: A convention (24 fps), not a measurement of the source product.
DEFAULT_FPS = 24.0

#: Maximum overlap between an extension and the existing clip, in frames.
#: invented — no published source: the source does not mention an overlap at all.
#: 48 frames is 2 s at ``DEFAULT_FPS``, half the shortest legal extension
#: (4 s = 96 frames), so an overlap can never swallow a whole extension.
EXTEND_OVERLAP_MAX_FRAMES = 48

#: The three post stages, in the order the graph runs them.
POST_STAGES = ("grade", "extend", "edit")

#: The post-plan audit rules, in evaluation order.
POST_RULES = (
    "grade_in_range",
    "extend_in_range",
    "edit_prompt_present",
    "edit_region_in_frame",
)

#: Rule weights. At or above ``OVERALL_PASS_WEIGHT`` (0.8) a rule gates the plan;
#: below it the rule is reported but cannot fail the plan.
#:
#: grade_in_range / extend_in_range — 1.0, gating. Guaranteed for a plan built
#: through ``GradeSettings`` and ``ExtendPlan``, which validate on construction;
#: kept because a ``GradePlan`` can also be assembled by hand or read back from a
#: sidecar, where nothing has validated it.
#:
#: edit_prompt_present — 1.0, gating. A region that says *where* to edit but not
#: *what* to change is a defect, and it can genuinely fail.
#:
#: edit_region_in_frame — 0.5, non-gating. A region that spills past the NDC
#: frame is a warning, not a failure: the image node can clamp it, and a
#: deliberate overscan is a legitimate choice.
#: invented — no published source; chosen below the 0.8 gate.
POST_RULE_WEIGHTS: dict[str, float] = {
    "grade_in_range": 1.0,
    "extend_in_range": 1.0,
    "edit_prompt_present": 1.0,
    "edit_region_in_frame": 0.5,
}


def _gates(weight: float) -> bool:
    """Whether a rule at ``weight`` gates the post plan.

    Split out so the boundary itself is testable: with the current weights
    (1.0, 1.0, 1.0, 0.5) no rule sits at exactly 0.8, so ``>=`` and ``>`` are
    indistinguishable from the rule set alone. This predicate is where the
    inclusive comparison lives, and it is pinned directly.
    """
    return weight >= OVERALL_PASS_WEIGHT


def grade_range(param: str) -> tuple[float, float]:
    """The legal ``(min, max)`` for one grade control."""
    if param not in GRADE_PARAMS:
        raise ValueError(
            f"unknown grade control {param!r}; legal controls are {GRADE_PARAMS}"
        )
    return GRADE_RANGES[param]


# --------------------------------------------------------------------------
# Grade
# --------------------------------------------------------------------------


@dataclass
class GradeSettings:
    """The seven grade controls, each inside its legal range.

    Constructing an out-of-range value raises ``ValueError`` naming the control,
    the value and the range. The engine does not clamp: silently clamping a
    request would make the plan disagree with what the user asked for.
    """

    temperature: float = GRADE_NEUTRAL["temperature"]
    contrast: float = GRADE_NEUTRAL["contrast"]
    saturation: float = GRADE_NEUTRAL["saturation"]
    sharpness: float = GRADE_NEUTRAL["sharpness"]
    film_grain: float = GRADE_NEUTRAL["film_grain"]
    highlights: float = GRADE_NEUTRAL["highlights"]
    exposure: float = GRADE_NEUTRAL["exposure"]

    def __post_init__(self) -> None:
        for param in GRADE_PARAMS:
            value = float(getattr(self, param))
            low, high = GRADE_RANGES[param]
            if not (low <= value <= high):
                raise ValueError(
                    f"grade control {param}={value!r} is outside its legal range "
                    f"{low}..{high}"
                )
            setattr(self, param, value)

    @classmethod
    def neutral(cls) -> "GradeSettings":
        """A grade that changes nothing."""
        return cls()

    def is_neutral(self) -> bool:
        """True when every control sits at its neutral value."""
        return all(
            getattr(self, param) == GRADE_NEUTRAL[param] for param in GRADE_PARAMS
        )

    def to_dict(self) -> dict:
        return {param: getattr(self, param) for param in GRADE_PARAMS}

    @classmethod
    def from_dict(cls, d: dict) -> "GradeSettings":
        return cls(
            **{
                param: float(d.get(param, GRADE_NEUTRAL[param]))
                for param in GRADE_PARAMS
            }
        )


def _direction(from_value: float, to_value: float) -> str:
    """``"up"``, ``"down"`` or ``"none"``.

    Split out so the equality boundary is testable on its own: ``apply_grade``
    only ever calls this with two different values, so ``>`` and ``>=`` would be
    indistinguishable from the grade path alone.
    """
    if to_value > from_value:
        return "up"
    if to_value < from_value:
        return "down"
    return "none"


@dataclass
class GradePlan:
    """A pure description of a grade: what to change, and which way.

    ``deltas`` is an ordered list of ``(param, from_value, to_value, direction)``
    tuples in ``GRADE_PARAMS`` order, and contains an entry **only** for a control
    that differs from neutral. A control left at neutral contributes no delta, so
    the graph leaves it at the model's own default. Nothing here has been applied
    to any image.
    """

    deltas: list[tuple[str, float, float, str]] = field(default_factory=list)

    def is_noop(self) -> bool:
        """True when the plan asks for no change at all."""
        return not self.deltas

    def params(self) -> list[str]:
        """The controls this plan touches, in order."""
        return [param for param, _frm, _to, _direction_name in self.deltas]

    def to_dict(self) -> dict:
        return {
            "deltas": [
                {
                    "param": param,
                    "from": from_value,
                    "to": to_value,
                    "direction": direction,
                }
                for param, from_value, to_value, direction in self.deltas
            ],
            "count": len(self.deltas),
            "is_noop": self.is_noop(),
        }

    def summary(self) -> str:
        """A one-line, ASCII-only description of the grade."""
        if not self.deltas:
            return "grade: neutral (no deltas)"
        parts = [
            f"{param} {direction} {from_value:.3f}->{to_value:.3f}"
            for param, from_value, to_value, direction in self.deltas
        ]
        return f"grade: {len(self.deltas)} delta(s) - " + ", ".join(parts)


def apply_grade(settings: GradeSettings) -> GradePlan:
    """Describe ``settings`` as an ordered list of deltas. Does not touch pixels.

    The name is ``apply_grade`` for symmetry with the rest of the pack, but the
    return value is a *plan*: this module has no image to apply it to and never
    will. The graph applies it with whatever image nodes are wired in.
    """
    deltas: list[tuple[str, float, float, str]] = []
    for param in GRADE_PARAMS:
        from_value = GRADE_NEUTRAL[param]
        to_value = float(getattr(settings, param))
        direction = _direction(from_value, to_value)
        if direction == "none":
            continue
        deltas.append((param, from_value, to_value, direction))
    return GradePlan(deltas=deltas)


# --------------------------------------------------------------------------
# Extend
# --------------------------------------------------------------------------


@dataclass
class ExtendPlan:
    """A Sequel or Prequel extension of a finished clip.

    ``mode`` is one of ``EXTEND_MODES``. ``duration_s`` is the length of the new
    segment and must sit inside ``EXTEND_DURATION_RANGE``. ``overlap_frames`` is
    how many frames of the existing clip the extension re-covers, and must sit
    inside ``0..EXTEND_OVERLAP_MAX_FRAMES``.

    In the real product this is a separate Seedance call, not a Cinema Studio
    endpoint — see the module docstring. This record describes the request; it
    does not make it.
    """

    mode: str = "sequel"
    duration_s: float = DEFAULT_EXTEND_DURATION_S
    overlap_frames: int = 0

    def __post_init__(self) -> None:
        if self.mode not in EXTEND_MODES:
            raise ValueError(
                f"unknown Extend mode {self.mode!r}; legal modes are {EXTEND_MODES}"
            )
        self.duration_s = float(self.duration_s)
        low, high = EXTEND_DURATION_RANGE
        if not (low <= self.duration_s <= high):
            raise ValueError(
                f"Extend duration_s={self.duration_s!r} is outside its legal range "
                f"{low}..{high} seconds"
            )
        self.overlap_frames = int(self.overlap_frames)
        if not (0 <= self.overlap_frames <= EXTEND_OVERLAP_MAX_FRAMES):
            raise ValueError(
                f"Extend overlap_frames={self.overlap_frames!r} is outside its legal "
                f"range 0..{EXTEND_OVERLAP_MAX_FRAMES} frames"
            )

    @property
    def overlap_s(self) -> float:
        """The overlap in seconds, at ``DEFAULT_FPS``."""
        return self.overlap_frames / DEFAULT_FPS

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "duration_s": self.duration_s,
            "overlap_frames": self.overlap_frames,
            "overlap_s": self.overlap_s,
        }


# --------------------------------------------------------------------------
# Edit
# --------------------------------------------------------------------------


@dataclass
class EditRegion:
    """One regional edit: a label, an NDC box, and what to change inside it.

    ``bbox`` is ``(min_x, min_y, max_x, max_y)`` in the same NDC convention as
    :mod:`~cinematographer.geometry` — x, y in [-1, 1], y up, frame edges at
    +/-1. A box that spills past the frame is allowed here and reported as a
    non-gating flag by ``PostPlan.checks()``; a box with min greater than max is
    rejected, because that is a bug rather than a choice.
    """

    label: str
    bbox: tuple[float, float, float, float]
    prompt: str = ""

    def __post_init__(self) -> None:
        self.label = str(self.label)
        self.prompt = str(self.prompt)
        bounds = tuple(float(v) for v in self.bbox)
        if len(bounds) != 4:
            raise ValueError(
                f"EditRegion {self.label!r}: bbox must be 4 NDC values "
                f"(min_x, min_y, max_x, max_y), got {len(bounds)}"
            )
        if bounds[0] > bounds[2] or bounds[1] > bounds[3]:
            raise ValueError(
                f"EditRegion {self.label!r}: bbox {bounds} is inverted "
                "(min must not exceed max on either axis)"
            )
        self.bbox = bounds  # type: ignore[assignment]

    def in_frame(self) -> bool:
        """True when the whole box sits inside the NDC frame."""
        return all(-1.0 <= value <= 1.0 for value in self.bbox)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "bbox": list(self.bbox),
            "prompt": self.prompt,
            "in_frame": self.in_frame(),
        }


@dataclass
class EditPlan:
    """A set of regional edits. In the real product these are Seedance calls."""

    regions: list[EditRegion] = field(default_factory=list)

    def labels(self) -> list[str]:
        """The region labels, in order."""
        return [region.label for region in self.regions]

    def to_dict(self) -> dict:
        return {
            "regions": [region.to_dict() for region in self.regions],
            "count": len(self.regions),
        }


# --------------------------------------------------------------------------
# The composed plan
# --------------------------------------------------------------------------


@dataclass
class PostCheck:
    """One audit rule's verdict on one post plan."""

    rule: str
    passed: bool
    weight: float
    detail: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "pass": self.passed,
            "weight": self.weight,
            "detail": self.detail,
        }


@dataclass
class PostPlan:
    """Stage 5 as one object: a grade, an optional extension, optional edits.

    ``is_noop()`` is True only when there is genuinely nothing to do — a neutral
    grade, no extension, and no edit regions. It is not a claim that any stage
    ran; nothing in this module runs.
    """

    grade: GradePlan = field(default_factory=GradePlan)
    extend: ExtendPlan | None = None
    edit: EditPlan | None = None

    def is_noop(self) -> bool:
        """True when the plan asks for no change at all."""
        if not self.grade.is_noop():
            return False
        if self.extend is not None:
            return False
        if self.edit is not None and self.edit.regions:
            return False
        return True

    def checks(self) -> list[PostCheck]:
        """Audit the plan against ``POST_RULES``, in order."""
        checks: list[PostCheck] = []

        bad_grade = [
            param
            for param, _from_value, to_value, _direction_name in self.grade.deltas
            if not (GRADE_RANGES[param][0] <= to_value <= GRADE_RANGES[param][1])
        ]
        checks.append(
            PostCheck(
                rule="grade_in_range",
                passed=not bad_grade,
                weight=POST_RULE_WEIGHTS["grade_in_range"],
                detail=(
                    "every grade delta target is inside its legal range"
                    if not bad_grade
                    else "grade delta(s) outside range: " + ", ".join(bad_grade)
                ),
            )
        )

        if self.extend is None:
            extend_ok = True
            extend_detail = "no extension requested"
        else:
            low, high = EXTEND_DURATION_RANGE
            extend_ok = (low <= self.extend.duration_s <= high) and (
                0 <= self.extend.overlap_frames <= EXTEND_OVERLAP_MAX_FRAMES
            )
            extend_detail = (
                f"{self.extend.mode} {self.extend.duration_s:.1f}s, "
                f"overlap {self.extend.overlap_frames} frame(s)"
            )
        checks.append(
            PostCheck(
                rule="extend_in_range",
                passed=extend_ok,
                weight=POST_RULE_WEIGHTS["extend_in_range"],
                detail=extend_detail,
            )
        )

        regions = self.edit.regions if self.edit is not None else []
        blank = [
            region.label or f"region {position}"
            for position, region in enumerate(regions, start=1)
            if not region.prompt.strip()
        ]
        checks.append(
            PostCheck(
                rule="edit_prompt_present",
                passed=not blank,
                weight=POST_RULE_WEIGHTS["edit_prompt_present"],
                detail=(
                    "every edit region names what to change"
                    if not blank
                    else "edit region(s) with no prompt: " + ", ".join(blank)
                ),
            )
        )

        outside = [
            region.label or f"region {position}"
            for position, region in enumerate(regions, start=1)
            if not region.in_frame()
        ]
        checks.append(
            PostCheck(
                rule="edit_region_in_frame",
                passed=not outside,
                weight=POST_RULE_WEIGHTS["edit_region_in_frame"],
                detail=(
                    "every edit region is inside the NDC frame"
                    if not outside
                    else "edit region(s) outside the NDC frame: " + ", ".join(outside)
                ),
            )
        )

        return checks

    @property
    def overall_pass(self) -> bool:
        """True only when every rule weighted at or above the gate passes.

        ``edit_region_in_frame`` (weight 0.5) is reported but cannot fail a plan.
        """
        return all(check.passed for check in self.checks() if _gates(check.weight))

    def to_dict(self) -> dict:
        return {
            "stages": list(POST_STAGES),
            "grade": self.grade.to_dict(),
            "extend": self.extend.to_dict() if self.extend is not None else None,
            "edit": self.edit.to_dict() if self.edit is not None else None,
            "is_noop": self.is_noop(),
            "overall_pass": self.overall_pass,
            "checks": [check.to_dict() for check in self.checks()],
        }

    def summary(self) -> str:
        """A one-line, ASCII-only description of the whole post plan."""
        if self.is_noop():
            return "post: no-op (neutral grade, no extend, no edit)"
        parts: list[str] = []
        if not self.grade.is_noop():
            parts.append(self.grade.summary())
        if self.extend is not None:
            parts.append(
                f"extend: {self.extend.mode} {self.extend.duration_s:.1f}s, "
                f"overlap {self.extend.overlap_frames} frame(s)"
            )
        if self.edit is not None and self.edit.regions:
            parts.append(
                f"edit: {len(self.edit.regions)} region(s) - "
                + ", ".join(self.edit.labels())
            )
        verdict = "PASS" if self.overall_pass else "FAIL"
        return f"{verdict} - " + "; ".join(parts)


def post_summary(plan: PostPlan) -> str:
    """Module-level alias for :meth:`PostPlan.summary`, for symmetry with the pack."""
    return plan.summary()
