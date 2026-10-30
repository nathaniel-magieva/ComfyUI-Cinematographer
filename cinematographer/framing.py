"""Cinematographer — per-shot deterministic framing rules.

A faithful port of the reference ``EvaluateFraming``.

Nine rules, each returning a **measured value, a pass/fail, and the camera lever
that fixes it**. Four of them (``negative_space``, ``camera_angle``,
``direct_address``, and ``foreground_occlusion`` in ``scene.py``) are
*informational* — they always pass and exist to describe the frame's register
rather than to judge it.

This is the deterministic half of the engine. The perceptual half needs a vision
model and is deliberately out of scope (spec §10).
"""

from __future__ import annotations

import math

from .geometry import (
    OVERALL_PASS_WEIGHT,
    CamPose,
    FramingReport,
    FramingScore,
    ShotIntent,
    Subject,
    base3,
    clamp,
    dot,
    eye_pt,
    headroom_band,
    norm,
    projector,
    round3,
    shot_size_ok,
    shot_weights,
    sub,
    top_pt,
)

#: The nine per-shot rule keys, in evaluation order.
FRAMING_RULES = (
    "in_frame",
    "rule_of_thirds",
    "headroom",
    "shot_size",
    "lead_room",
    "negative_space",
    "camera_angle",
    "level",
    "direct_address",
)

#: Rules that describe rather than judge — they never fail.
INFORMATIONAL_RULES = ("negative_space", "camera_angle", "direct_address")


def _headroom_correction(head: float, lo: float, hi: float) -> str:
    """``head`` is the space above the subject, so it grows as the aim rises.

    Both halves of each string must move ``head`` toward the band: the target
    half changes the aim, the distance half changes how much of the subject the
    frame holds. Getting the target direction backwards sends the operator
    further from a pass, which is worse than saying nothing.
    """
    if head < lo:
        # Too little space above the head: aim higher, or pull back to fit more in.
        return "too tight / clipped top: raise the camera target or pull back"
    # Too much space above the head: aim lower, or push in to fill the frame.
    return "too much headroom: lower the camera target or push in"


def _lead_room(s: Subject, ndc_x: float) -> float:
    """Positive when the subject looks into the frame's negative space.

    A subject looking screen-right should sit on the left, so the sign flips.
    """
    face_right = math.sin(math.radians(s.facing_yaw_deg)) > 0
    return -ndc_x if face_right else ndc_x


def evaluate_framing(
    subject: Subject,
    cam: CamPose,
    shot_type: str = "medium",
    intent: ShotIntent | None = None,
) -> FramingReport:
    """Score the deterministic cinematography rules for one subject and camera."""
    it = intent or ShotIntent()
    proj = projector(cam)

    _, by, _, _ = proj(base3(subject))
    ex, ey, _, e_in = proj(eye_pt(subject))
    _, ty, _, _ = proj(top_pt(subject))

    w = shot_weights(shot_type)
    rep = FramingReport(subject=subject.name, shot_type=shot_type)

    def add(rule: str, passed: bool, val: float, target: str, corr: str = "") -> None:
        rep.scores.append(
            FramingScore(
                rule=rule,
                passed=passed,
                value=round3(val),
                target=target,
                weight=w.get(rule, 0.0),
                correction=corr,
            )
        )

    # 1. in_frame — the subject's FACE is in front of the camera and within the
    #    frame. Feet need not be visible: a close-up crops the body.
    in_frame = e_in and abs(ex) <= 1 and abs(ey) <= 1
    add(
        "in_frame",
        in_frame,
        1.0 if in_frame else 0.0,
        "subject's face within frame & in front",
        "" if in_frame else "re-aim/pull back: subject's face is off-frame or behind camera",
    )

    # 2. rule_of_thirds — the eye anchor near a vertical third line (+/-1/3 NDC),
    #    unless the shot is intentionally centred, where centred is correct.
    if it.center:
        centered = abs(ex) <= 0.12
        add(
            "rule_of_thirds",
            centered,
            ex,
            "centered (symmetry intended)",
            "" if centered else "center the subject (ndcX\u22480)",
        )
    else:
        third_dist = min(abs(ex - (1.0 / 3)), abs(ex + (1.0 / 3)))
        thirds_pass = third_dist <= 0.12
        add(
            "rule_of_thirds",
            thirds_pass,
            ex,
            "eyes near x=\u00b10.33 (not centered)",
            ""
            if thirds_pass
            else f"offset subject to a third: shift camera x / aim (eyes at ndcX={ex:.2f})",
        )

    # 3. headroom — the gap from the subject's top to the frame top (ndcY=1).
    head = 1 - ty
    head_lo, head_hi = headroom_band(shot_type)
    head_pass = head_lo <= head <= head_hi
    add(
        "headroom",
        head_pass,
        head,
        f"top gap in [{head_lo:.2f}, {head_hi:.2f}]",
        "" if head_pass else _headroom_correction(head, head_lo, head_hi),
    )

    # 4. shot_size — the subject's screen-height fraction, classified vs intent.
    frac = (ty - by) / 2
    size_pass, size_tgt = shot_size_ok(frac, shot_type)
    add(
        "shot_size",
        size_pass,
        frac,
        size_tgt,
        ""
        if size_pass
        else f"dolly/zoom to hit {shot_type} (subject fills {frac * 100:.0f}% of height)",
    )

    # 5. lead_room — the subject should look INTO the frame.
    lead = _lead_room(subject, ex)
    lead_pass = lead >= -0.05
    add(
        "lead_room",
        lead_pass,
        lead,
        "gaze leads into frame",
        "" if lead_pass else "flip composition: leave space in the direction the subject faces",
    )

    # 6. negative_space — the fraction of frame NOT covered by the subject.
    #    Informational: >0.7 reads isolated, ~0.5 balanced.
    sub_h = max(0.0, ty - by) / 2
    sub_area = min(1.0, sub_h * (0.38 * sub_h + 0.05))
    add("negative_space", True, 1 - sub_area, ">0.7 reads isolated; ~0.5 balanced")

    # 7. camera_angle <-> power: pitch sign plus camera height vs the eye-line.
    #    Informational.
    fwd = norm(sub(cam.target, cam.eye))
    pitch = math.degrees(math.asin(clamp(fwd[1], -1.0, 1.0)))
    dh = cam.eye[1] - (subject.base[1] + 0.92 * subject.height)
    angle_class = "eye-level (neutral)"
    if dh < -0.1 and pitch > 2:
        angle_class = "low (power/heroic)"
    elif dh > 0.1 and pitch < -2:
        angle_class = "high (vulnerable)"
    add("camera_angle", True, dh, angle_class)

    # 8. level / Dutch — the roll should match the intended Dutch (0 = level).
    level_pass = abs(cam.roll_deg - it.dutch_deg) < 1
    level_tgt = "roll\u22480 (level)"
    if it.dutch_deg != 0:
        level_tgt = f"Dutch {it.dutch_deg:g}\u00b0 (unease intended)"
    add(
        "level",
        level_pass,
        cam.roll_deg,
        level_tgt,
        "" if level_pass else "match the intended camera roll",
    )

    # 9. direct_address — the angle between the subject's gaze and the
    #    camera->subject axis. <8 deg looks down the lens (intimacy, complicity,
    #    confrontation; breaks the fourth wall). Informational register.
    gaze = norm(
        (
            math.sin(math.radians(subject.facing_yaw_deg)),
            0.0,
            math.cos(math.radians(subject.facing_yaw_deg)),
        )
    )
    to_cam = norm(sub(cam.eye, eye_pt(subject)))
    addr = math.degrees(math.acos(clamp(dot(gaze, to_cam), -1.0, 1.0)))
    if addr < 8:
        addr_class = "direct address (down the lens)"
    elif addr < 25:
        addr_class = "near-lens (engaged)"
    else:
        addr_class = "off-lens (observational)"
    add("direct_address", True, addr, addr_class)

    # Overall: every rule at or above the weight threshold must pass.
    rep.overall_pass = all(
        s.passed for s in rep.scores if s.weight >= OVERALL_PASS_WEIGHT
    )
    return rep


def summary(report: FramingReport) -> str:
    """A one-line, human-readable verdict — the string the panel and node show."""
    verdict = "PASS" if report.overall_pass else "FAIL"
    bits = [f"{verdict} {report.shot_type} on '{report.subject}'"]
    fails = report.failures()
    if not fails:
        bits.append("all weighted rules pass")
    for s in fails:
        bits.append(f"{s.rule}={s.value:g}")
    return " | ".join(bits)
