"""Identity-continuity fixtures — every threshold pinned from both sides.

Why this file exists
--------------------

``character.py`` is the pack's newest measure and the one with the least
external evidence behind it: there is no reference implementation to diff
against, and three of its four numbers are judgement calls. That makes it the
module most likely to drift silently — change ``PALETTE_DRIFT_MAX`` from 0.173 to
0.30 and a naive suite still passes.

So every threshold here is probed the way ``test_boundaries.py`` probes the
framing constants: build a pair that sits just *inside* the boundary and assert
it passes, then nudge it just *outside* and assert it fails. A constant that
moves breaks one of the two sides.

Expected values are hand-computed from the definition, never read back from the
code under test. Where a value is a closed form (``sqrt(3) * 0.09``,
``0.33 / 1.33``) the expression is written out so the arithmetic is visible.

The two honesty cases get their own tests: an empty palette and a degenerate
bounding box must **fail**, not pass. A measure that cannot measure is not a
measure that succeeded.
"""

import json
import math

import pytest

from cinematographer import character
from cinematographer.character import (
    CHARACTER_RULES,
    DEFAULT_EYE_RATIO,
    FRAMING_DRIFT_MAX,
    FRAMING_DRIFT_WEIGHT,
    INFORMATIONAL_CHARACTER_RULES,
    PALETTE_DRIFT_MAX,
    PALETTE_DRIFT_WEIGHT,
    PROPORTION_DRIFT_MAX,
    PROPORTION_DRIFT_WEIGHT,
    CharacterAppearance,
    CharacterContinuityReport,
    CharacterDrift,
    character_continuity_summary,
    evaluate_character_continuity,
    framing_delta,
    palette_distance,
    proportion_delta,
)
from cinematographer.geometry import OVERALL_PASS_WEIGHT
from cinematographer.nodes import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    CharacterContinuity,
)

# --------------------------------------------------------------------------
# Fixtures — built from the definitions, not from the engine
# --------------------------------------------------------------------------

GREY = (0.5, 0.5, 0.5)


def shot(
    name: str = "hero",
    height: float = 1.0,
    palette=((0.5, 0.5, 0.5),),
    eye_ratio: float = 0.92,
) -> CharacterAppearance:
    """A shot whose bbox height is exactly ``height`` (centred on NDC y = 0)."""
    return CharacterAppearance(
        name=name,
        bbox=(-0.2, -height / 2, 0.2, height / 2),
        palette=tuple(palette),
        eye_ratio=eye_ratio,
    )


def shifted(base: tuple[float, float, float], delta: float) -> tuple[float, float, float]:
    """``base`` with ``delta`` added to every channel — a uniform colour shift."""
    return (base[0] + delta, base[1] + delta, base[2] + delta)


def drift(report, rule: str):
    d = report.score(rule)
    assert d is not None, f"rule {rule!r} not reported"
    return d


# --------------------------------------------------------------------------
# 1. The rule surface and the gate
# --------------------------------------------------------------------------


def test_character_rules_are_the_three_measured_ones():
    """The rule surface is exactly three rules, in evaluation order."""
    assert CHARACTER_RULES == ("palette_drift", "proportion_drift", "framing_drift")


def test_no_rule_is_informational():
    """Every rule here is a measurement that can fail.

    The gating distinction is carried by *weight* (``framing_drift`` is 0.5), not
    by a rule being decorative. If a rule were ever added to this tuple it would
    stop being able to fail, and the threshold tests below would go blind.
    """
    assert INFORMATIONAL_CHARACTER_RULES == ()


def test_overall_pass_weight_is_imported_not_redefined():
    """``OVERALL_PASS_WEIGHT`` is the *same object* as geometry's, not a copy.

    Constrains the gate. A local ``OVERALL_PASS_WEIGHT = 0.8`` would satisfy an
    equality check but not an identity check, and the two could then drift apart.
    """
    assert character.OVERALL_PASS_WEIGHT is OVERALL_PASS_WEIGHT
    assert OVERALL_PASS_WEIGHT == 0.8


def test_weights_are_pinned():
    """The gating surface: two rules gate, one does not."""
    assert PALETTE_DRIFT_WEIGHT == 1.0
    assert PROPORTION_DRIFT_WEIGHT == 1.0
    assert FRAMING_DRIFT_WEIGHT == 0.5
    assert FRAMING_DRIFT_WEIGHT < OVERALL_PASS_WEIGHT
    assert PALETTE_DRIFT_WEIGHT >= OVERALL_PASS_WEIGHT
    assert PROPORTION_DRIFT_WEIGHT >= OVERALL_PASS_WEIGHT


def test_default_eye_ratio_matches_the_engine_anchor():
    """0.92 is the engine's default human (``geometry.anchors()``), not a new number."""
    assert DEFAULT_EYE_RATIO == 0.92


# --------------------------------------------------------------------------
# 2. palette_distance — the metric itself, by hand
# --------------------------------------------------------------------------


def test_palette_distance_single_colour_is_plain_rgb_distance():
    """One colour each: the distance is the Euclidean RGB distance, nothing else.

    (0.8, 0.2, 0.2) vs (0.9, 0.2, 0.2) -> sqrt(0.1^2) = 0.1.
    (0, 0, 0) vs (0.5, 0.5, 0.5)      -> sqrt(3 * 0.25) = sqrt(0.75).
    """
    assert palette_distance([(0.8, 0.2, 0.2)], [(0.9, 0.2, 0.2)]) == pytest.approx(0.1)
    assert palette_distance([(0.0, 0.0, 0.0)], [(0.5, 0.5, 0.5)]) == pytest.approx(
        math.sqrt(0.75)
    )


def test_palette_distance_averages_over_the_shorter_palette():
    """The mean is taken over the *shorter* palette, so extra colours are ignored.

    A = [(1,0,0), (0,0,1)], B = [(1,0,0)]: B is shorter, its one colour matches
    (1,0,0) at distance 0, so the mean is 0 — the unmatched blue in A contributes
    nothing. This is the documented asymmetry of the metric.
    """
    a = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)]
    b = [(1.0, 0.0, 0.0)]
    assert palette_distance(a, b) == pytest.approx(0.0)
    assert palette_distance(b, a) == pytest.approx(0.0)


def test_palette_distance_picks_the_nearest_neighbour():
    """A = [(0,0,0), (1,1,1)], B = [(0.5,0.5,0.5)]: both candidates are equidistant.

    Distance to either is sqrt(3 * 0.25) = sqrt(0.75); the mean over the single
    shorter-palette colour is that same value. Hand-computed, not read back.
    """
    a = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
    b = [(0.5, 0.5, 0.5)]
    assert palette_distance(a, b) == pytest.approx(math.sqrt(0.75))


def test_palette_distance_is_a_mean_over_a_multi_colour_short_palette():
    """The divisor is the shorter palette's length, not 1.

    A = [(0,0,0), (1,1,1)] (2 colours), B = [(0.1,0.1,0.1), (0.5,0.5,0.5),
    (0.9,0.9,0.9)] (3 colours). The shorter palette is A, and each of its colours
    has a nearest neighbour at a per-channel distance of 0.1:

        (0,0,0) -> (0.1,0.1,0.1)  = sqrt(3 * 0.01) = sqrt(0.03)
        (1,1,1) -> (0.9,0.9,0.9)  = sqrt(3 * 0.01) = sqrt(0.03)

    The mean is sqrt(0.03) = 0.1732; the *sum* would be 0.3464. This test exists
    because the mutation gate found that every other palette fixture had a
    one-colour shorter palette, so dropping the division changed nothing.
    """
    a = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
    b = [(0.1, 0.1, 0.1), (0.5, 0.5, 0.5), (0.9, 0.9, 0.9)]
    assert palette_distance(a, b) == pytest.approx(math.sqrt(0.03))
    assert palette_distance(a, b) != pytest.approx(2 * math.sqrt(0.03))


def test_palette_distance_is_symmetric():
    """Swapping the arguments cannot change the number."""
    a = [(0.9, 0.1, 0.1), (0.1, 0.1, 0.9), (0.5, 0.5, 0.5)]
    b = [(0.85, 0.15, 0.12), (0.12, 0.1, 0.88)]
    assert palette_distance(a, b) == pytest.approx(palette_distance(b, a))


def test_palette_distance_is_none_when_a_palette_is_empty():
    """No colours means no measurement — ``None``, never 0.0."""
    assert palette_distance([], [(0.5, 0.5, 0.5)]) is None
    assert palette_distance([(0.5, 0.5, 0.5)], []) is None
    assert palette_distance([], []) is None


# --------------------------------------------------------------------------
# 3. PALETTE_DRIFT_MAX — both sides
# --------------------------------------------------------------------------


def test_palette_drift_max_is_sqrt3_times_ten_percent():
    """The constant is the Euclidean distance of a uniform 10% channel shift.

    sqrt(3 * 0.10^2) = sqrt(3) * 0.10 = 0.17320508...
    """
    assert PALETTE_DRIFT_MAX == pytest.approx(math.sqrt(3.0) * 0.10)
    assert PALETTE_DRIFT_MAX == pytest.approx(0.17320508, abs=1e-8)


def test_palette_threshold_edges():
    """A uniform 9% shift passes; a uniform 11% shift fails.

    Constrains ``PALETTE_DRIFT_MAX``. A uniform shift of ``s`` on every channel
    gives distance ``sqrt(3) * s``, so the two fixtures straddle the threshold at
    0.1559 and 0.1905 against a limit of 0.1732. Moving the constant to 0.20
    flips the second assert; moving it to 0.15 flips the first.
    """
    inside = evaluate_character_continuity(
        [shot(palette=[GREY]), shot(palette=[shifted(GREY, 0.09)])]
    )
    outside = evaluate_character_continuity(
        [shot(palette=[GREY]), shot(palette=[shifted(GREY, 0.11)])]
    )

    assert drift(inside, "palette_drift").value == pytest.approx(
        math.sqrt(3.0) * 0.09, abs=1e-3
    )
    assert drift(inside, "palette_drift").passed is True
    assert drift(outside, "palette_drift").passed is False


def test_palette_drift_fails_honestly_when_it_cannot_measure():
    """An empty palette is a failure with a correction, not a silent pass.

    This is the module's stated contract: if it cannot measure, it says so.
    """
    report = evaluate_character_continuity([shot(), shot(palette=[])])
    d = drift(report, "palette_drift")
    assert d.passed is False
    assert d.value == 0.0
    assert "cannot measure" in d.detail
    assert d.correction, "an unmeasurable palette must still offer a lever"
    assert report.overall_pass is False


def test_palette_correction_names_the_distance_in_rgb_units():
    """The correction carries a real number and a unit."""
    report = evaluate_character_continuity(
        [shot(palette=[GREY]), shot(palette=[shifted(GREY, 0.11)])]
    )
    correction = drift(report, "palette_drift").correction
    assert "0.191 RGB" in correction  # sqrt(3) * 0.11 = 0.1905 -> 0.191
    assert "max 0.173" in correction  # the threshold, to 3 dp


# --------------------------------------------------------------------------
# 4. PROPORTION_DRIFT_MAX — both sides
# --------------------------------------------------------------------------


def test_proportion_delta_is_the_absolute_ratio_change():
    """|0.92 - 0.95| = 0.03, in ratio units."""
    a, b = shot(eye_ratio=0.92), shot(eye_ratio=0.95)
    assert proportion_delta(a, b) == pytest.approx(0.03)
    assert proportion_delta(b, a) == pytest.approx(0.03)
    assert proportion_delta(a, a) == pytest.approx(0.0)


def test_proportion_threshold_edges():
    """A 0.02 ratio change passes; a 0.04 change fails.

    Constrains ``PROPORTION_DRIFT_MAX`` (0.03). Moving it to 0.05 flips the
    second assert; moving it to 0.01 flips the first.
    """
    assert PROPORTION_DRIFT_MAX == 0.03

    inside = evaluate_character_continuity(
        [shot(eye_ratio=0.92), shot(eye_ratio=0.94)]
    )
    outside = evaluate_character_continuity(
        [shot(eye_ratio=0.92), shot(eye_ratio=0.96)]
    )

    assert drift(inside, "proportion_drift").value == pytest.approx(0.02, abs=1e-3)
    assert drift(inside, "proportion_drift").passed is True
    assert drift(outside, "proportion_drift").value == pytest.approx(0.04, abs=1e-3)
    assert drift(outside, "proportion_drift").passed is False


def test_proportion_correction_names_the_number_in_ratio_units():
    """The correction carries the measured change and the limit."""
    report = evaluate_character_continuity(
        [shot(eye_ratio=0.92), shot(eye_ratio=0.96)]
    )
    correction = drift(report, "proportion_drift").correction
    assert "0.040" in correction
    assert "0.030" in correction


# --------------------------------------------------------------------------
# 5. FRAMING_DRIFT_MAX — both sides
# --------------------------------------------------------------------------


def test_framing_delta_is_relative_and_symmetric():
    """|1.5 - 1.0| / max(1.5, 1.0) = 1/3, whichever shot comes first."""
    a, b = shot(height=1.0), shot(height=1.5)
    assert framing_delta(a, b) == pytest.approx(1.0 / 3.0)
    assert framing_delta(b, a) == pytest.approx(1.0 / 3.0)
    assert framing_delta(a, a) == pytest.approx(0.0)


def test_framing_threshold_edges():
    """A 24.8% height change passes; a 25.4% change fails.

    Constrains ``FRAMING_DRIFT_MAX`` (0.25). The two fixtures are 0.33/1.33 and
    0.34/1.34 — a deliberately tight straddle, so a move of the constant in
    either direction is caught.
    """
    assert FRAMING_DRIFT_MAX == 0.25

    inside = evaluate_character_continuity([shot(height=1.0), shot(height=1.33)])
    outside = evaluate_character_continuity([shot(height=1.0), shot(height=1.34)])

    assert drift(inside, "framing_drift").value == pytest.approx(0.33 / 1.33, abs=1e-3)
    assert drift(inside, "framing_drift").passed is True
    assert drift(outside, "framing_drift").value == pytest.approx(0.34 / 1.34, abs=1e-3)
    assert drift(outside, "framing_drift").passed is False


def test_framing_correction_is_a_percentage():
    """The correction carries a real percentage and the limit."""
    report = evaluate_character_continuity([shot(height=1.0), shot(height=1.34)])
    correction = drift(report, "framing_drift").correction
    assert "25.4%" in correction  # 0.34 / 1.34 = 25.37%
    assert "25.0%" in correction  # the threshold


def test_framing_drift_fails_honestly_when_it_cannot_measure():
    """Two zero-height bboxes are a failure, not a 0% change."""
    flat = CharacterAppearance(name="hero", bbox=(0.0, 0.0, 0.0, 0.0), palette=[GREY])
    assert framing_delta(flat, flat) is None

    report = evaluate_character_continuity([flat, flat])
    d = drift(report, "framing_drift")
    assert d.passed is False
    assert d.value == 0.0
    assert "cannot measure" in d.detail
    assert d.correction


def test_height_is_floored_at_zero_for_an_inverted_bbox():
    """An inverted bbox (max_y < min_y) yields height 0, not a negative height."""
    inverted = CharacterAppearance(name="hero", bbox=(0.0, 0.5, 0.0, -0.5), palette=[GREY])
    assert inverted.height == 0.0


# --------------------------------------------------------------------------
# 6. Report semantics
# --------------------------------------------------------------------------


def test_single_shot_sequence_passes_trivially():
    """One shot has no cut, so there is nothing that could have drifted."""
    report = evaluate_character_continuity([shot()])
    assert report.drifts == []
    assert report.cuts == 0
    assert report.overall_pass is True
    assert report.failures() == []
    assert report.corrections() == []
    assert character_continuity_summary(report) == "no consecutive shots to check"


def test_empty_sequence_passes_trivially():
    """No shots at all is the same case, and must not raise."""
    report = evaluate_character_continuity([])
    assert report.overall_pass is True
    assert report.drifts == []
    assert character_continuity_summary(report) == "no consecutive shots to check"


def test_overall_pass_ignores_rules_below_the_gate():
    """A failing ``framing_drift`` (weight 0.5) must not fail the sequence.

    The pair is built to satisfy every gating rule while failing the non-gating
    one: identical palettes (distance 0), identical eye ratios (0), and a 25.4%
    screen-height change. This is the gating-surface claim for this module, and
    it is the reason ``framing_drift`` cannot gate — a deliberate cut from a wide
    to a close-up changes screen height on purpose.
    """
    report = evaluate_character_continuity([shot(height=1.0), shot(height=1.34)])

    assert drift(report, "framing_drift").passed is False
    assert drift(report, "framing_drift").weight == 0.5

    gating = [d for d in report.drifts if d.weight >= OVERALL_PASS_WEIGHT]
    assert gating, "there must be gating rules"
    assert all(d.passed for d in gating), [d.rule for d in gating if not d.passed]
    assert report.overall_pass is True, (
        "a 0.5-weighted failure must not fail the cut — this is the gating-surface "
        "claim the module makes"
    )


def test_failures_reports_non_gating_failures_too():
    """``failures()`` is the *reported* surface; ``overall_pass`` is the *gating* one."""
    report = evaluate_character_continuity([shot(height=1.0), shot(height=1.34)])
    failures = report.failures()
    assert [d.rule for d in failures] == ["framing_drift"]
    assert report.overall_pass is True


def test_summary_does_not_call_a_non_gating_flag_a_failure():
    """The one-liner must agree with ``overall_pass``, not contradict it."""
    report = evaluate_character_continuity([shot(height=1.0), shot(height=1.34)])
    summary = character_continuity_summary(report)
    assert summary.startswith("PASS")
    assert "non-gating" in summary
    assert "framing_drift (shot 1->2)" in summary


def test_a_gating_failure_fails_the_sequence():
    """A palette drift past the threshold fails the cut and yields a lever."""
    report = evaluate_character_continuity(
        [shot(palette=[GREY]), shot(palette=[shifted(GREY, 0.11)])]
    )
    assert report.overall_pass is False
    assert [d.rule for d in report.failures()] == ["palette_drift"]
    corrections = report.corrections()
    assert len(corrections) == 1
    assert "RGB" in corrections[0]
    assert character_continuity_summary(report).startswith("FAIL - 1 of 3 checks")


def test_every_pair_is_evaluated_and_labelled():
    """Three shots means two cuts and six verdicts, each labelled with its pair.

    The second cut drifts (a uniform 13% shift from shot 2, sqrt(3)*0.13 = 0.2252
    > 0.1732); the first does not (9%, 0.1559).
    """
    report = evaluate_character_continuity(
        [
            shot(palette=[GREY]),
            shot(palette=[shifted(GREY, 0.09)]),
            shot(palette=[shifted(GREY, 0.22)]),
        ]
    )
    assert report.cuts == 2
    assert len(report.drifts) == 6
    assert [(d.shot_a, d.shot_b) for d in report.drifts] == [
        (1, 2), (1, 2), (1, 2), (2, 3), (2, 3), (2, 3)
    ]
    failures = report.failures()
    assert [(d.rule, d.shot_a, d.shot_b) for d in failures] == [
        ("palette_drift", 2, 3)
    ]
    assert report.overall_pass is False


def test_score_returns_the_first_pair_for_a_rule():
    """``score`` mirrors ``FramingReport.score``: first match, not the worst.

    With two cuts the first is clean and the second drifts, so ``score`` returns
    the *passing* verdict. That is the documented contract — iterate ``drifts``
    for every pair — and it is pinned here so it cannot change silently.
    """
    report = evaluate_character_continuity(
        [
            shot(palette=[GREY]),
            shot(palette=[shifted(GREY, 0.09)]),
            shot(palette=[shifted(GREY, 0.22)]),
        ]
    )
    first = report.score("palette_drift")
    assert (first.shot_a, first.shot_b) == (1, 2)
    assert first.passed is True
    assert report.value("palette_drift") == pytest.approx(math.sqrt(3.0) * 0.09, abs=1e-3)


def test_score_and_value_are_none_and_zero_for_an_unknown_rule():
    report = evaluate_character_continuity([shot(), shot()])
    assert report.score("not_a_rule") is None
    assert report.value("not_a_rule") == 0.0


def test_corrections_only_cover_failing_rules():
    """A clean pair produces no levers at all."""
    report = evaluate_character_continuity([shot(), shot()])
    assert report.overall_pass is True
    assert report.corrections() == []
    assert all(d.correction == "" for d in report.drifts)


def test_corrections_ignore_a_passing_drift_that_carries_a_lever():
    """The contract is "failing rules only", not "any non-empty correction".

    Built by hand, because the engine never emits a passing drift with a
    correction — which means the ``not d.passed`` guard in ``corrections()`` is
    unobservable from the rule set alone. This pins the contract directly.
    """
    passing_with_lever = CharacterDrift(
        rule="palette_drift",
        value=0.01,
        passed=True,
        weight=PALETTE_DRIFT_WEIGHT,
        detail="clean",
        correction="this must not be returned",
    )
    report = CharacterContinuityReport(
        character="hero", drifts=[passing_with_lever], overall_pass=True
    )
    assert report.corrections() == []
    assert report.failures() == []


def test_the_gate_is_inclusive_at_exactly_the_gate_weight():
    """``_gates(0.8)`` is True; ``_gates(0.799)`` is False.

    Constrains the ``>=`` in the gate. No rule currently sits at exactly 0.8
    (weights are 1.0, 1.0, 0.5), so ``>=`` and ``>`` are indistinguishable from
    the rule set — this predicate is where the comparison lives, and it is pinned
    here so the boundary cannot move silently.
    """
    assert character._gates(OVERALL_PASS_WEIGHT) is True
    assert character._gates(OVERALL_PASS_WEIGHT + 0.001) is True
    assert character._gates(OVERALL_PASS_WEIGHT - 0.001) is False
    assert character._gates(0.0) is False


def test_every_correction_contains_a_number():
    """House rule: a correction gives a real number with a unit."""
    report = evaluate_character_continuity(
        [
            shot(height=1.0, palette=[GREY], eye_ratio=0.92),
            shot(height=1.34, palette=[shifted(GREY, 0.11)], eye_ratio=0.96),
        ]
    )
    corrections = report.corrections()
    assert len(corrections) == 3
    for text in corrections:
        assert any(ch.isdigit() for ch in text), text
    assert any("RGB" in t for t in corrections)
    assert any("%" in t for t in corrections)


# --------------------------------------------------------------------------
# 7. Serialisation
# --------------------------------------------------------------------------


def test_report_to_dict_round_trips_through_json():
    """``to_dict()`` must survive ``json.dumps``/``json.loads`` unchanged.

    This is the node's wire format, so a tuple or a non-finite float anywhere in
    the report would break the graph.
    """
    report = evaluate_character_continuity(
        [
            shot(height=1.0, palette=[GREY], eye_ratio=0.92),
            shot(height=1.34, palette=[shifted(GREY, 0.11)], eye_ratio=0.96),
        ]
    )
    data = report.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["overall_pass"] is False
    assert data["cuts"] == 1
    assert len(data["drifts"]) == 3


def test_report_to_dict_is_json_for_every_edge_case():
    """The unmeasurable and single-shot reports are JSON too."""
    for report in (
        evaluate_character_continuity([]),
        evaluate_character_continuity([shot()]),
        evaluate_character_continuity([shot(palette=[]), shot(palette=[])]),
    ):
        data = report.to_dict()
        assert json.loads(json.dumps(data)) == data


def test_appearance_round_trips_through_json():
    """A shot survives the node's JSON boundary: tuples become lists and back."""
    original = shot(height=1.8, palette=[(0.8, 0.2, 0.2), (0.1, 0.1, 0.15)], eye_ratio=0.91)
    restored = CharacterAppearance.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored == original
    assert restored.height == pytest.approx(1.8)


def test_appearance_from_dict_defaults_are_the_engine_defaults():
    """A minimal shot dict is accepted and defaults to the 0.92 human."""
    minimal = CharacterAppearance.from_dict({"name": "hero", "bbox": [0.0, -0.5, 0.0, 0.5]})
    assert minimal.palette == ()
    assert minimal.eye_ratio == DEFAULT_EYE_RATIO


def test_drift_to_dict_omits_an_empty_correction():
    """Passing rules carry no ``correction`` key; failing rules do."""
    report = evaluate_character_continuity([shot(), shot()])
    passing = report.to_dict()["drifts"][0]
    assert "correction" not in passing
    assert passing["pass"] is True

    failing = evaluate_character_continuity(
        [shot(palette=[GREY]), shot(palette=[shifted(GREY, 0.11)])]
    ).to_dict()["drifts"][0]
    assert failing["correction"]


# --------------------------------------------------------------------------
# 8. The node
# --------------------------------------------------------------------------


def test_character_node_is_registered_and_the_six_existing_nodes_survive():
    """The character node is registered and the original six survive.

    The total node count is deliberately NOT pinned. It was `== 7` and that broke
    the moment the full-flow nodes landed -- a count assertion is a maintenance
    trap in a pack that is still growing. What matters is that these seven are
    present and none was dropped.
    """
    assert "CharacterContinuity" in NODE_CLASS_MAPPINGS
    assert "CharacterContinuity" in NODE_DISPLAY_NAME_MAPPINGS
    for name in (
        "CinematographerEvaluate",
        "CinematographerAutoFrame",
        "ChorosContinuity",
        "SceneFramingExtras",
        "CameraReliabilityZone",
        "CinematographerCorrection",
    ):
        assert name in NODE_CLASS_MAPPINGS, f"{name} was dropped"
    assert len(NODE_CLASS_MAPPINGS) >= 7


def test_character_node_returns_json_and_a_summary():
    """The node is JSON in, JSON out, with a verdict that matches the report."""
    node = CharacterContinuity()
    shots = json.dumps(
        [
            shot(palette=[GREY]).to_dict(),
            shot(palette=[shifted(GREY, 0.11)]).to_dict(),
        ]
    )
    report_json, overall_pass, summary = node.character_continuity(shots)

    report = json.loads(report_json)
    assert overall_pass is False
    assert report["overall_pass"] is False
    assert report["cuts"] == 1
    assert [d["rule"] for d in report["drifts"] if not d["pass"]] == ["palette_drift"]
    assert isinstance(summary, str) and summary.startswith("FAIL")


def test_character_node_default_input_passes():
    """The default the node ships with is a clean cut, so a fresh graph is green."""
    node = CharacterContinuity()
    default = CharacterContinuity.INPUT_TYPES()["required"]["shots_json"][1]["default"]
    report_json, overall_pass, summary = node.character_continuity(default)

    assert overall_pass is True
    assert json.loads(report_json)["overall_pass"] is True
    assert summary.startswith("PASS")


def test_character_node_accepts_a_single_shot_and_an_empty_list():
    """A one-shot graph is not an error — it simply has no cut to check."""
    node = CharacterContinuity()
    _, overall_pass, summary = node.character_continuity(
        json.dumps([shot().to_dict()])
    )
    assert overall_pass is True
    assert summary == "no consecutive shots to check"

    _, overall_pass, summary = node.character_continuity("[]")
    assert overall_pass is True
    assert summary == "no consecutive shots to check"


def test_character_node_rejects_malformed_input():
    """Bad JSON and a non-array both raise a message a user can act on."""
    node = CharacterContinuity()
    with pytest.raises(ValueError, match="not valid JSON"):
        node.character_continuity("{not json")
    with pytest.raises(ValueError, match="JSON array"):
        node.character_continuity('{"shots": 3}')
