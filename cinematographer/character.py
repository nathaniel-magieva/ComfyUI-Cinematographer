"""Cinematographer — identity continuity: did the character survive the cut?

``continuity.py`` compares *camera positions* across a cut. It says nothing about
whether the person in shot 3 is the same person as in shot 1. This module
measures that second question, as far as it can be measured without a vision
model.

Three rules, each a number a human can check by hand:

* **palette_drift** — greedy nearest-neighbour mean RGB distance between the
  character's dominant colours in two shots. Catches wardrobe and lighting drift.
* **proportion_drift** — the change in eye height as a fraction of total height.
  The engine's ``anchors()`` puts the eye anchor at 0.92 of stature; a change in
  that ratio means the character's proportions changed, which is what a LoRA
  failing to hold looks like.
* **framing_drift** — the relative change in the character's normalised screen
  height, as a proxy for distance consistency. Non-gating (weight 0.5): a
  deliberate cut from a wide to a close-up changes screen height on purpose.

**What this does NOT do.** It does not verify *facial identity*. Nothing here
looks at a face, and no arrangement of palette, proportion, and scale statistics
can decide whether two faces are the same person — that needs a vision model (a
face embedding or verifier), which is out of scope for a pure-stdlib node pack.
This module measures **appearance drift**: a necessary but not sufficient signal.
A sequence can pass every rule here and still have swapped the actor.

Two honesty rules, carried over from the rest of the pack:

* Every threshold is a named module constant, and the comment says where the
  number came from. Where it is a judgement call rather than a published figure,
  the comment says **invented — no published source**.
* When a rule cannot measure, it **fails** and says so. An empty palette or a
  degenerate bounding box is reported as a failure, never as a pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .geometry import OVERALL_PASS_WEIGHT, round3

#: The three appearance rules, in evaluation order.
CHARACTER_RULES = ("palette_drift", "proportion_drift", "framing_drift")

#: Rules that describe rather than judge. Empty on purpose: every rule here is a
#: measurement that can fail, and the gating distinction is carried by *weight* —
#: ``framing_drift`` is weighted below ``OVERALL_PASS_WEIGHT``, so it is reported
#: but cannot fail a cut. The name mirrors ``framing.INFORMATIONAL_RULES`` so a
#: consumer can ask the same question of both engines.
INFORMATIONAL_CHARACTER_RULES: tuple[str, ...] = ()

#: The engine's default human eye anchor, as a fraction of stature. Mirrors the
#: 0.92 in ``geometry.anchors()``; it is a default, not a threshold.
DEFAULT_EYE_RATIO = 0.92

#: Mean nearest-neighbour RGB distance at which a palette counts as drifted.
#: ``sqrt(3) * 0.10`` — the Euclidean RGB distance of a *uniform* 10% shift on
#: every channel (26/255). Below that we call the difference render/lighting
#: noise; above it, a wardrobe or lighting change.
#: invented — no published source.
PALETTE_DRIFT_MAX = math.sqrt(3.0) * 0.10

#: Maximum tolerated change in the eye-height ratio between consecutive shots.
#: 0.03 of stature is ~5 cm on a 1.8 m figure — about a quarter of a head, and
#: tighter than the framing engine's loosest positional tolerance (0.12 NDC)
#: because a proportion change is structural, not compositional.
#: invented — no published source.
PROPORTION_DRIFT_MAX = 0.03

#: Maximum tolerated relative change in the character's normalised screen height.
#: 0.25 sits below one full shot-size step: the engine's own size targets
#: (``geometry.size_target_mid``) step 0.30 -> 0.55 -> 0.85, i.e. 55-83% between
#: adjacent shot types, so a single deliberate cut does not trip this rule.
#: invented — no published source.
FRAMING_DRIFT_MAX = 0.25

#: Rule weights. At or above ``OVERALL_PASS_WEIGHT`` (0.8) a rule gates the
#: sequence verdict; below it the rule is reported but cannot fail a cut.
#:
#: palette_drift — wardrobe/lighting drift is the most direct appearance signal
#: available without a vision model. 1.0 mirrors the framing engine's ``in_frame``.
PALETTE_DRIFT_WEIGHT = 1.0

#: proportion_drift — a proportion change is structural; this is the rule that
#: catches a LoRA failing to hold. 1.0, as above.
PROPORTION_DRIFT_WEIGHT = 1.0

#: framing_drift — a legitimate cut changes shot size on purpose, so this rule
#: must not gate. invented — no published source; chosen below the 0.8 gate.
FRAMING_DRIFT_WEIGHT = 0.5


@dataclass
class CharacterAppearance:
    """A character's measurable appearance in ONE shot.

    ``bbox`` is normalised NDC bounds ``(min_x, min_y, max_x, max_y)``, the same
    convention as :mod:`~cinematographer.geometry` (x, y in [-1, 1], y up).
    ``palette`` is the dominant colours, each 0..1 RGB, ordered by coverage.
    ``eye_ratio`` is eye height as a fraction of total height —
    ``DEFAULT_EYE_RATIO`` for a default human (see ``geometry.anchors()``).
    """

    name: str
    bbox: tuple[float, float, float, float]
    palette: tuple[tuple[float, float, float], ...] = ()
    eye_ratio: float = DEFAULT_EYE_RATIO

    @property
    def height(self) -> float:
        """Normalised screen height (``max_y - min_y``), floored at 0."""
        return max(0.0, self.bbox[3] - self.bbox[1])

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bbox": list(self.bbox),
            "palette": [list(c) for c in self.palette],
            "eye_ratio": self.eye_ratio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterAppearance":
        bbox = d.get("bbox") or (0.0, 0.0, 0.0, 0.0)
        return cls(
            name=str(d.get("name", "character")),
            bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
            palette=tuple(
                tuple(float(c) for c in colour) for colour in d.get("palette") or ()
            ),
            eye_ratio=float(d.get("eye_ratio", DEFAULT_EYE_RATIO)),
        )


@dataclass
class CharacterDrift:
    """One rule's verdict on one consecutive pair.

    Same shape as ``geometry.FramingScore``: a measured value, a pass/fail, the
    weight that decides whether it gates, and the correction lever that fixes it.
    ``shot_a`` / ``shot_b`` are 1-based positions in the input sequence.
    """

    rule: str
    value: float
    passed: bool
    weight: float
    detail: str
    correction: str = ""
    shot_a: int = 1
    shot_b: int = 2

    def to_dict(self) -> dict:
        d = {
            "rule": self.rule,
            "pass": self.passed,
            "value": self.value,
            "weight": self.weight,
            "shot_a": self.shot_a,
            "shot_b": self.shot_b,
            "detail": self.detail,
        }
        if self.correction:
            d["correction"] = self.correction
        return d


@dataclass
class CharacterContinuityReport:
    """The appearance verdict across a sequence, cut by cut."""

    character: str
    drifts: list[CharacterDrift] = field(default_factory=list)
    overall_pass: bool = True

    @property
    def cuts(self) -> int:
        """How many consecutive pairs were evaluated."""
        return len({(d.shot_a, d.shot_b) for d in self.drifts})

    def score(self, rule: str) -> CharacterDrift | None:
        """The first pair's verdict for ``rule`` (mirrors ``FramingReport.score``).

        Iterate ``drifts`` to see every pair.
        """
        for d in self.drifts:
            if d.rule == rule:
                return d
        return None

    def value(self, rule: str) -> float:
        d = self.score(rule)
        return d.value if d else 0.0

    def failures(self) -> list[CharacterDrift]:
        """Every failing drift, gating or not."""
        return [d for d in self.drifts if not d.passed]

    def corrections(self) -> list[str]:
        """The correction levers, in rule order, for every failing rule."""
        return [d.correction for d in self.drifts if not d.passed and d.correction]

    def to_dict(self) -> dict:
        return {
            "character": self.character,
            "cuts": self.cuts,
            "drifts": [d.to_dict() for d in self.drifts],
            "overall_pass": self.overall_pass,
        }


# --------------------------------------------------------------------------
# The three measures — each one a number, not a vibe
# --------------------------------------------------------------------------


def _rgb_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance between two 0..1 RGB triples."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def palette_distance(
    a: Sequence[tuple[float, float, float]],
    b: Sequence[tuple[float, float, float]],
) -> float | None:
    """Greedy nearest-neighbour mean RGB distance between two palettes.

    Each colour in the **shorter** palette is matched to its nearest colour in
    the longer one, and the matches are averaged. Greedy, not an optimal
    assignment, so the number is an upper bound on the true palette distance —
    and exactly reproducible, which an optimal assignment would not be when two
    candidates tie.

    Returns ``None`` when either palette is empty: there is nothing to measure,
    and the caller must fail rather than pass. Units are RGB (0..1 per channel);
    the largest possible value is ``sqrt(3)``.
    """
    if not a or not b:
        return None
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    total = 0.0
    for colour in short:
        total += min(_rgb_distance(colour, other) for other in long_)
    return total / len(short)


def proportion_delta(a: CharacterAppearance, b: CharacterAppearance) -> float:
    """Absolute change in the eye-height ratio. Units: ratio (fraction of stature)."""
    return abs(a.eye_ratio - b.eye_ratio)


def framing_delta(a: CharacterAppearance, b: CharacterAppearance) -> float | None:
    """Relative change in normalised screen height, in [0, 1].

    ``abs(h_b - h_a) / max(h_a, h_b)`` — symmetric, so the verdict does not
    depend on which shot is listed first. Returns ``None`` when both heights are
    zero (a degenerate bounding box): there is nothing to measure.
    """
    ha, hb = a.height, b.height
    largest = max(ha, hb)
    if largest <= 0.0:
        return None
    return abs(hb - ha) / largest


def _gates(weight: float) -> bool:
    """Whether a rule at ``weight`` gates the sequence verdict.

    Split out so the boundary itself is testable: with the current weights
    (1.0, 1.0, 0.5) no rule sits at exactly 0.8, so ``>=`` and ``>`` are
    indistinguishable from the rule set alone. This predicate is where the
    inclusive comparison lives, and it is pinned directly.
    """
    return weight >= OVERALL_PASS_WEIGHT


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _pair_drifts(
    a: CharacterAppearance,
    b: CharacterAppearance,
    shot_a: int,
    shot_b: int,
) -> list[CharacterDrift]:
    """The three rule verdicts for one consecutive pair, in ``CHARACTER_RULES`` order."""
    out: list[CharacterDrift] = []

    # 1. palette_drift — how far the dominant colours moved, in RGB units.
    dist = palette_distance(a.palette, b.palette)
    if dist is None:
        out.append(
            CharacterDrift(
                rule="palette_drift",
                value=0.0,
                passed=False,
                weight=PALETTE_DRIFT_WEIGHT,
                detail=f"cannot measure: shot {shot_a} or {shot_b} has no palette",
                correction=(
                    "supply at least one dominant colour (0..1 RGB) per shot - "
                    "an unmeasurable palette is reported as a failure, not a pass"
                ),
                shot_a=shot_a,
                shot_b=shot_b,
            )
        )
    else:
        ok = dist <= PALETTE_DRIFT_MAX
        out.append(
            CharacterDrift(
                rule="palette_drift",
                value=round3(dist),
                passed=ok,
                weight=PALETTE_DRIFT_WEIGHT,
                detail=f"palette distance {dist:.3f} RGB (max {PALETTE_DRIFT_MAX:.3f})",
                correction=""
                if ok
                else (
                    f"palette drifted {dist:.3f} RGB (max {PALETTE_DRIFT_MAX:.3f}): "
                    "re-shoot with the reference wardrobe and lighting, or re-train "
                    "the LoRA on the drifted shot"
                ),
                shot_a=shot_a,
                shot_b=shot_b,
            )
        )

    # 2. proportion_drift — the eye anchor's share of stature, in ratio units.
    pdelta = proportion_delta(a, b)
    p_ok = pdelta <= PROPORTION_DRIFT_MAX
    out.append(
        CharacterDrift(
            rule="proportion_drift",
            value=round3(pdelta),
            passed=p_ok,
            weight=PROPORTION_DRIFT_WEIGHT,
            detail=f"eye ratio moved {pdelta:.3f} (max {PROPORTION_DRIFT_MAX:.3f})",
            correction=""
            if p_ok
            else (
                f"eye ratio moved {pdelta:.3f} (max {PROPORTION_DRIFT_MAX:.3f}): "
                "the character's proportions changed - re-render from the reference "
                "sheet, or lower the LoRA strength"
            ),
            shot_a=shot_a,
            shot_b=shot_b,
        )
    )

    # 3. framing_drift — the screen-height change, as a percentage. Non-gating.
    fdelta = framing_delta(a, b)
    if fdelta is None:
        out.append(
            CharacterDrift(
                rule="framing_drift",
                value=0.0,
                passed=False,
                weight=FRAMING_DRIFT_WEIGHT,
                detail=(
                    f"cannot measure: shots {shot_a} and {shot_b} both have zero height"
                ),
                correction=(
                    "supply a non-degenerate bbox (max_y > min_y) per shot - "
                    "an unmeasurable height is reported as a failure, not a pass"
                ),
                shot_a=shot_a,
                shot_b=shot_b,
            )
        )
    else:
        f_ok = fdelta <= FRAMING_DRIFT_MAX
        out.append(
            CharacterDrift(
                rule="framing_drift",
                value=round3(fdelta),
                passed=f_ok,
                weight=FRAMING_DRIFT_WEIGHT,
                detail=(
                    f"screen height changed {fdelta * 100:.1f}% "
                    f"(max {FRAMING_DRIFT_MAX * 100:.1f}%)"
                ),
                correction=""
                if f_ok
                else (
                    f"screen height changed {fdelta * 100:.1f}% "
                    f"(max {FRAMING_DRIFT_MAX * 100:.1f}%): the cut changed the "
                    "character's scale - hold the camera distance, or accept it as a "
                    "deliberate shot-size change"
                ),
                shot_a=shot_a,
                shot_b=shot_b,
            )
        )

    return out


def evaluate_character_continuity(
    shots: Sequence[CharacterAppearance],
) -> CharacterContinuityReport:
    """Evaluate every consecutive pair of shots for the three appearance rules.

    A sequence of fewer than two shots has no cut to check and passes trivially:
    ``overall_pass`` is True and ``drifts`` is empty, because there is nothing
    that could have drifted.

    ``overall_pass`` is True only when every drift weighted at or above
    ``geometry.OVERALL_PASS_WEIGHT`` passes. ``framing_drift`` (weight 0.5) is
    reported but cannot fail a cut.
    """
    report = CharacterContinuityReport(character=shots[0].name if shots else "")
    for i in range(1, len(shots)):
        report.drifts.extend(_pair_drifts(shots[i - 1], shots[i], i, i + 1))
    report.overall_pass = all(
        d.passed for d in report.drifts if _gates(d.weight)
    )
    return report


def character_continuity_summary(report: CharacterContinuityReport) -> str:
    """A one-line verdict across the whole sequence."""
    if not report.drifts:
        return "no consecutive shots to check"
    failed = report.failures()
    if not failed:
        return (
            f"PASS - {len(report.drifts)} appearance checks across "
            f"{report.cuts} cut(s)"
        )
    parts = [f"{d.rule} (shot {d.shot_a}->{d.shot_b})" for d in failed]
    if report.overall_pass:
        # Only sub-threshold rules failed. Say so rather than calling the cut a
        # failure the verdict does not agree with.
        return (
            f"PASS - {len(report.drifts)} appearance checks across "
            f"{report.cuts} cut(s), {len(failed)} non-gating flag(s): "
            + ", ".join(parts)
        )
    return f"FAIL - {len(failed)} of {len(report.drifts)} checks: " + ", ".join(parts)
