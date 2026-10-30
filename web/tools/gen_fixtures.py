#!/usr/bin/env python3
"""Freeze `parity_fixtures.json` from the Python engine.

This is the *generator*; `parity_check.py` is the *checker*. Run this only when
you deliberately want to re-freeze the fixtures (e.g. the engine changed on
purpose), then re-run the checker and commit both.

    python3 web/tools/gen_fixtures.py

It imports the engine read-only from `cinematographer/` and writes
`web/parity_fixtures.json`. It never writes outside `web/`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.dirname(HERE)
APP_DIR = os.path.dirname(WEB_DIR)
OUT = os.path.join(WEB_DIR, "parity_fixtures.json")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from cinematographer.autoframe import auto_frame_camera  # noqa: E402
from cinematographer.continuity import (  # noqa: E402
    ContinuityShot,
    evaluate_continuity,
)
from cinematographer.framing import evaluate_framing  # noqa: E402
from cinematographer.geometry import CamPose, ShotIntent, Subject  # noqa: E402
from cinematographer.reliability import camera_reliability_zone  # noqa: E402


def cam(eye, target, focal_mm=35.0, sensor_mm=36.0, aspect=16.0 / 9.0, roll_deg=0.0, fov=0.0):
    return CamPose(
        eye=tuple(eye),
        target=tuple(target),
        focal_mm=focal_mm,
        sensor_mm=sensor_mm,
        aspect=aspect,
        roll_deg=roll_deg,
        fov=fov,
    )


def subj(name, base, height, facing_yaw_deg=0.0):
    return Subject(name=name, base=tuple(base), height=height, facing_yaw_deg=facing_yaw_deg)


# ---------------------------------------------------------------------------
# Framing fixtures — at least 5 (camera, subject, shot_type) triples, covering
# every branch of every rule.
# ---------------------------------------------------------------------------

FRAMING = [
    {
        "id": "go-test-centered-closeup",
        "description": (
            "The reference engine's own test pose 'camCentered'. "
            "Centred framing must FAIL rule_of_thirds. Cross-checked against "
            "the reference framing-scorer test."
        ),
        "subject": subj("Maya", (0, 0, 3), 1.7, 180),
        "camera": cam((0, 1.5, 1.7), (0, 1.3, 3), focal_mm=42, sensor_mm=36),
        "shot_type": "closeup",
        "intent": ShotIntent(),
    },
    {
        "id": "go-test-offset-closeup",
        "description": (
            "The reference engine's own test pose 'camOffset'. "
            "Off-centre framing must PASS rule_of_thirds. Cross-checked against "
            "the reference framing-scorer test."
        ),
        "subject": subj("Maya", (0, 0, 3), 1.7, 180),
        "camera": cam((0.65, 1.52, 1.75), (-0.2, 1.5, 3), focal_mm=40, sensor_mm=36),
        "shot_type": "closeup",
        "intent": ShotIntent(),
    },
    {
        "id": "medium-thirds-left",
        "description": "Medium shot, camera in front of the subject, intent puts the subject on the left third.",
        "subject": subj("Ava", (0, 0, 0), 1.75, 0),
        "camera": cam((0.55, 1.61, 3.2), (0.0, 1.61, 0.0), focal_mm=35, sensor_mm=36),
        "shot_type": "medium",
        "intent": ShotIntent(angle="eye", side="left"),
    },
    {
        "id": "wide-high-angle",
        "description": "Wide shot from above the eye-line: camera_angle reads high, shot_size must sit in the wide band.",
        "subject": subj("Ben", (0, 0, 0), 1.8, 0),
        "camera": cam((1.4, 3.4, 5.6), (0.0, 1.66, 0.0), focal_mm=24, sensor_mm=36),
        "shot_type": "wide",
        "intent": ShotIntent(angle="high", side="right"),
    },
    {
        "id": "closeup-dutch-intended",
        "description": "Dutch roll 8 deg with intent.dutch_deg=8: the level rule must PASS.",
        "subject": subj("Cleo", (0, 0, 0), 1.68, 0),
        "camera": cam((0.3, 1.55, 1.5), (0.0, 1.55, 0.0), focal_mm=50, sensor_mm=36, roll_deg=8.0),
        "shot_type": "closeup",
        "intent": ShotIntent(dutch_deg=8.0, side="left"),
    },
    {
        "id": "closeup-dutch-accidental",
        "description": "Roll 5 deg with no intended Dutch: the level rule must FAIL with the roll lever.",
        "subject": subj("Cleo", (0, 0, 0), 1.68, 0),
        "camera": cam((0.3, 1.55, 1.5), (0.0, 1.55, 0.0), focal_mm=50, sensor_mm=36, roll_deg=5.0),
        "shot_type": "closeup",
        "intent": ShotIntent(),
    },
    {
        "id": "medium-centered-intent",
        "description": "intent.center=True takes the 'centered is correct' branch of rule_of_thirds.",
        "subject": subj("Dana", (0, 0, 0), 1.72, 0),
        "camera": cam((0.0, 1.58, 2.6), (0.0, 1.58, 0.0), focal_mm=35, sensor_mm=36),
        "shot_type": "medium",
        "intent": ShotIntent(center=True),
    },
    {
        "id": "wide-lead-room-fail",
        "description": "Subject facing screen-right but sitting on the right: lead_room must FAIL (negative).",
        "subject": subj("Eli", (0, 0, 0), 1.78, 90),
        "camera": cam((1.9, 1.64, 4.4), (0.0, 1.64, 0.0), focal_mm=28, sensor_mm=36),
        "shot_type": "wide",
        "intent": ShotIntent(side="right"),
    },
    {
        "id": "behind-camera-in-frame-fail",
        "description": "The subject is behind the camera: in_frame must FAIL and every projection must return the behind-camera sentinel.",
        "subject": subj("Fay", (0, 0, -4), 1.7, 0),
        "camera": cam((0, 1.56, 0), (0, 1.56, 1), focal_mm=35, sensor_mm=36),
        "shot_type": "medium",
        "intent": ShotIntent(),
    },
    {
        "id": "medium-solver-fov",
        "description": "A solver-shaped pose: fov=40 overrides focal/sensor (the Auto-Frame lens path).",
        "subject": subj("Gus", (0, 0, 0), 1.75, 0),
        "camera": cam((0.0, 1.61, 2.4), (0.0, 1.61, 0.0), focal_mm=0.0, fov=40.0),
        "shot_type": "medium",
        "intent": ShotIntent(side="left"),
    },
    {
        "id": "closeup-low-angle",
        "description": "Camera below the eye-line with an upward pitch: camera_angle reads low (power/heroic).",
        "subject": subj("Hana", (0, 0, 0), 1.65, 0),
        "camera": cam((0.25, 0.9, 1.4), (0.0, 1.52, 0.0), focal_mm=40, sensor_mm=36),
        "shot_type": "closeup",
        "intent": ShotIntent(angle="low", side="left"),
    },
    {
        "id": "wide-far-subject-small",
        "description": "A very wide framing where shot_size falls below the wide band and headroom is large.",
        "subject": subj("Ivo", (0, 0, 0), 1.8, 0),
        "camera": cam((0.0, 1.66, 14.0), (0.0, 1.66, 0.0), focal_mm=35, sensor_mm=36),
        "shot_type": "wide",
        "intent": ShotIntent(side="right"),
    },
]

# ---------------------------------------------------------------------------
# Continuity fixtures — 180_axis and 30_degree across cuts.
# ---------------------------------------------------------------------------


def shot(n, az_deg, yaw_deg=0.0, dist=3.0, height=1.6, base=(0, 0, 0)):
    import math

    r = math.radians(az_deg)
    eye = (base[0] + math.sin(r) * dist, height, base[2] + math.cos(r) * dist)
    return ContinuityShot(
        shot_number=n,
        base=tuple(base),
        yaw_deg=yaw_deg,
        camera=CamPose(eye=eye, target=(base[0], height, base[2]), focal_mm=35),
    )


CONTINUITY = [
    {
        "id": "axis-cross-and-jump-cut",
        "description": (
            "Shot 1->2 keeps the side but changes the bearing by only 15 deg (30_degree FAIL); "
            "shot 2->3 crosses the action line (180_axis FAIL) while clearing 30 deg."
        ),
        "shots": [shot(1, 15.0), shot(2, 30.0), shot(3, -25.0)],
    },
    {
        "id": "clean-sequence",
        "description": "Three shots on one side of the line, each 40 deg apart: both rules PASS.",
        "shots": [shot(1, 10.0), shot(2, 50.0), shot(3, 90.0)],
    },
    {
        "id": "both-rules-fail",
        "description": "A 5 deg bearing change that also flips sides: both rules FAIL on the same cut.",
        "shots": [shot(1, 20.0), shot(2, -15.0)],
    },
    {
        "id": "single-shot",
        "description": "One shot only: no consecutive pair, so no issues at all.",
        "shots": [shot(1, 0.0)],
    },
]

# ---------------------------------------------------------------------------
# Reliability fixtures — the training envelope, computed not hard-coded.
# ---------------------------------------------------------------------------

RELIABILITY = [
    {
        "id": "green-front",
        "description": "Camera straight in front, eye-level: green.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((0.0, 1.564, 3.0), (0.0, 1.564, 0.0)),
        "azimuth_deg": 0.0,
        "elevation_deg": 0.0,
    },
    {
        "id": "green-boundary",
        "description": "Exactly on both green boundaries (45 deg azimuth, 30 deg elevation): still green.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((2.1213, 2.864, 2.1213), (0.0, 1.564, 0.0)),
        "azimuth_deg": 45.0,
        "elevation_deg": 30.0,
    },
    {
        "id": "yellow-azimuth",
        "description": "50 deg azimuth, level: yellow, extrapolating on azimuth.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((2.2981, 1.564, 1.9284), (0.0, 1.564, 0.0)),
        "azimuth_deg": 50.0,
        "elevation_deg": 0.0,
    },
    {
        "id": "yellow-azimuth-boundary",
        "description": "Exactly 60 deg azimuth, level: the last yellow step before red.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((2.5981, 1.564, 1.5), (0.0, 1.564, 0.0)),
        "azimuth_deg": 60.0,
        "elevation_deg": 0.0,
    },
    {
        "id": "red-azimuth",
        "description": "70 deg azimuth: beyond the trained range, the hidden side will be invented.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((2.8191, 1.564, 1.0261), (0.0, 1.564, 0.0)),
        "azimuth_deg": 70.0,
        "elevation_deg": 0.0,
    },
    {
        "id": "red-elevation",
        "description": "Level azimuth but 40 deg elevation: red on the elevation axis.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((0.0, 4.0813, 3.0), (0.0, 1.564, 0.0)),
        "azimuth_deg": 0.0,
        "elevation_deg": 40.0,
    },
    {
        "id": "derived-from-pose",
        "description": "No explicit azimuth/elevation: both are derived from the camera pose, as the node does.",
        "subject": subj("Nia", (0, 0, 0), 1.7, 0),
        "camera": cam((1.5, 2.2, 2.5981), (0.0, 1.564, 0.0)),
        "azimuth_deg": None,
        "elevation_deg": None,
    },
]

# ---------------------------------------------------------------------------
# Auto-frame fixtures — the solver, including the convergence flag.
# ---------------------------------------------------------------------------

AUTOFRAME = [
    {
        "id": "autoframe-medium-thirds-left",
        "description": "Solvable: medium shot, subject on the left third.",
        "subject": subj("Juno", (0, 0, 0), 1.75, 0),
        "shot_type": "medium",
        "intent": ShotIntent(side="left"),
    },
    {
        "id": "autoframe-closeup-centered",
        "description": "Solvable: centred close-up (symmetry intent).",
        "subject": subj("Juno", (0, 0, 0), 1.75, 0),
        "shot_type": "closeup",
        "intent": ShotIntent(center=True),
    },
    {
        "id": "autoframe-wide-low",
        "description": "Solvable: wide shot from a low angle.",
        "subject": subj("Juno", (0, 0, 0), 1.75, 0),
        "shot_type": "wide",
        "intent": ShotIntent(angle="low", side="right"),
    },
    {
        "id": "autoframe-medium-dutch",
        "description": "Solvable: medium shot with an intended Dutch angle.",
        "subject": subj("Juno", (0, 0, 0), 1.75, 0),
        "shot_type": "medium",
        "intent": ShotIntent(dutch_deg=8.0, side="left"),
    },
    {
        "id": "autoframe-offset-azimuth",
        "description": "Solvable: the camera orbits 25 deg off the subject's front.",
        "subject": subj("Juno", (0, 0, 0), 1.75, 0),
        "shot_type": "medium",
        "intent": ShotIntent(azimuth_deg=25.0, side="left"),
    },
]


# ---------------------------------------------------------------------------
# Director's Panel fixtures
# ---------------------------------------------------------------------------
#
# The Director tab's option lists come from the Cinema Studio 4.0 Generate API
# reference. Those lists are frozen here so `parity_check.py` can catch drift in
# `web/director.js` — and, the moment `cinematographer/director.py` exists,
# catch drift between the JS mirror and the engine.
#
# The frozen lists are additionally re-verified against the captured schema when
# that capture is readable, so this file is anchored to a source outside itself.

#: The captured API reference, relative to the repository root. Best-effort: the
#: check degrades to a note when the capture is not on disk.
#:
#: The capture ships in this repository under ``research/`` so the citation resolves
#: for anyone who clones it. It previously pointed two levels above the pack root at
#: a private research directory, which meant the one check anchoring these enums to a
#: source outside themselves could never run for a reader.
CAPTURE_RELPATH = os.path.join("research", "cinema-studio-4.0-api-schema.txt")

DIRECTOR_ENUM_SOURCE = (
    "Cinema Studio 4.0 Generate API reference (first-party), captured 2026-10-29"
)

#: Frozen transcription of the API's closed enumerations.
DIRECTOR_ENUMS = {
    "genre": ["epic", "drama", "noir", "comedy", "horror", "action"],
    "era": ["1960s", "1980s", "1990s", "2000s", "2020s"],
    "pacing": ["chaotic", "dynamic", "calm", "single-shot"],
    "camera_model": ["modern", "35mm-film", "8mm-film", "dv-camcorder"],
    "camera_lens": [
        "clean-sharp",
        "anamorphic",
        "vintage-anamorphic",
        "warm-vintage",
        "halation-vintage",
    ],
    "camera_aperture": ["f14-wide-open", "f4-moderate", "f11-deep-focus"],
    "camera_movement": [
        "snorricam", "robot-arm", "tilt-up", "rack-focus", "tilt-down", "pov",
        "pan-left", "crane-up", "pan-right", "crane-down", "side-tracking",
        "pedestal-up", "pedestal-down", "handheld", "tracking", "drone-orbit",
        "dolly-zoom", "aerial-pullback", "static-shot", "bullet-time", "whip-pan",
        "slow-zoom-in", "arc-left", "slow-zoom-out", "arc-right", "truck-right",
        "dolly-in", "truck-left", "dolly-out", "slider-right", "crush-zoom",
        "slider-left", "helicopter-shot",
    ],
    "light": [
        "silhouette", "practicals", "window", "overhead-fall", "contre-jour", "soft-cross",
    ],
    "color_palette": [
        "static-noon", "twilight-fable", "back-row-kissing-seats",
        "on-the-other-side-of-the-porthole", "the-emerald-ambush", "highway-standoff",
        "the-faded-fresco", "oil-ochre", "the-mountain-convent", "ghost-in-the-code",
        "pink-velvet", "two-days-to-the-horizon", "industrial-fog", "stairs-go-up",
        "field-post", "home-is-the-next-gas-station", "glossy-flesh",
        "the-crimson-ballet", "neon-rain-at-midnight", "the-morning-after-rain",
        "the-iron-borough", "the-ground", "the-investigation", "turquoise-mirage",
        "a-dream-in-color", "breakfast-on-schedule", "favela-gold", "a-hotel-for-one",
        "after-dark", "crimson-vigi", "the-neighbors-saw-everything",
        "the-grey-channel", "mirage-at-noon", "bubblegum-boulevard", "yellow-room",
        "the-earth-keeps-things-reluctantly", "tropic-fever-dream",
        "bioluminescent-night", "dont-turn-it-off-im-watching",
        "the-silk-curtain-falls", "the-butterfly", "playtime", "wallpaper-romance",
        "overtime", "the-way-home-is-longer", "everyone-speaks-in-whispers",
        "runaway-summer", "amber-wasteland", "the-circus", "gasoline-sunset",
    ],
    "aspect_ratio": ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9"],
    # The union of the on-screen wheel (8) and the settings reference (8), which
    # differ by Interest vs Hope. NOT API-sourced: no `emotion` field exists.
    "emotion": [
        "sadness", "fear", "anger", "joy", "trust", "disgust", "surprise",
        "interest", "hope",
    ],
    # The API accepts two; the shipped UI offers three. The panel shows all three
    # and flags 1080p, so the fixture records both facts.
    "resolution": ["480p", "720p"],
}

#: Enum members the shipped UI offers but the documented API rejects.
DIRECTOR_UI_ONLY = {"resolution": ["1080p"]}

#: Enums that are NOT in the API schema, with the source that does carry them.
#: The capture anchor must not be applied to these.
DIRECTOR_NON_API_ENUMS = {
    "emotion": (
        "Emotion wheel: union of the on-screen wheel (V3) and the settings "
        "reference, which differ by Interest vs Hope. No API `emotion` field exists."
    ),
}

#: The published credit table: native audio on, 16:9 frame, priced 2026-10-24.
#: All nine cells are exactly linear in duration (3 / 7 / 16 credits per second).
DIRECTOR_CREDIT_TABLE = {
    "480p": {10: 30, 15: 45, 30: 90},
    "720p": {10: 70, 15: 105, 30: 210},
    "1080p": {10: 160, 15: 240, 30: 480},
}

DIRECTOR_CREDIT_SOURCE = (
    "Cinema Studio 4.0 credit table (first-party), pricing checked 2026-10-24; "
    "corroborated for 10 s 720p and 30 s 1080p by the 2026-10-28 press release"
)


def parse_capture_enums() -> dict[str, list[str]]:
    """Re-read the enum lists out of the captured API reference.

    Returns an empty dict when the capture is not on disk. This is an anchor,
    not a dependency: the frozen lists above are what the fixtures use.
    """
    path = os.path.normpath(os.path.join(APP_DIR, CAPTURE_RELPATH))
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {}

    found: dict[str, list[str]] = {}
    # The capture escapes underscores in field names (`**camera\_lens**`).
    field_re = re.compile(r"^\*\*([a-z_\\]+)\*\*\s+`", re.M)
    allowed_re = re.compile(r"^Allowed values:\s*(.+?)\.\s*$", re.M)

    marks = list(field_re.finditer(text))
    for i, m in enumerate(marks):
        name = m.group(1).replace("\\_", "_")
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.end():end]
        am = allowed_re.search(block)
        if not am:
            continue
        found[name] = re.findall(r'`"([^"]+)"`', am.group(1))
    return found


def director_fixtures() -> tuple[dict, list[str]]:
    """Build the `director` fixture section, plus notes for the report."""
    notes: list[str] = []

    # Anchor check: the frozen lists must agree with the capture when it is here.
    captured = parse_capture_enums()
    if not captured:
        notes.append("schema capture not readable — frozen lists used unverified")
    else:
        for name, values in DIRECTOR_ENUMS.items():
            if name in DIRECTOR_NON_API_ENUMS:
                continue
            if name not in captured:
                notes.append(f"{name}: not found in the capture")
            elif captured[name] != values:
                notes.append(
                    f"{name}: frozen list disagrees with the capture "
                    f"({len(values)} vs {len(captured[name])})"
                )
        extra = sorted(set(captured) - set(DIRECTOR_ENUMS))
        if extra:
            notes.append("capture has enums we do not model: " + ", ".join(extra))

    # The engine's own module is authoritative when it exists.
    py_present = os.path.exists(os.path.join(APP_DIR, "cinematographer", "director.py"))
    notes.append(
        "cinematographer/director.py present — cross-checked"
        if py_present
        else "cinematographer/director.py ABSENT — Python side not cross-checked"
    )

    enums = []
    for name, values in DIRECTOR_ENUMS.items():
        entry = {
            "id": f"enum_{name}",
            "enum": name,
            "values": list(values),
            "source": DIRECTOR_NON_API_ENUMS.get(name, DIRECTOR_ENUM_SOURCE),
            "api_backed": name not in DIRECTOR_NON_API_ENUMS,
        }
        if name in DIRECTOR_UI_ONLY:
            entry["ui_only"] = list(DIRECTOR_UI_ONLY[name])
        enums.append(entry)

    credits = []
    for resolution, cells in DIRECTOR_CREDIT_TABLE.items():
        for duration, published in cells.items():
            credits.append(
                {
                    "id": f"credit_{duration}s_{resolution}",
                    "duration": duration,
                    "resolution": resolution,
                    "expected_credits": published,
                    "source": DIRECTOR_CREDIT_SOURCE,
                }
            )

    section = {
        "meta": {
            "enum_source": DIRECTOR_ENUM_SOURCE,
            "credit_source": DIRECTOR_CREDIT_SOURCE,
            "python_module": "cinematographer/director.py",
            "python_present": py_present,
            "capture_verified": bool(captured),
            "notes": notes,
        },
        "enums": enums,
        "credits": credits,
    }
    return section, notes


def engine_revision() -> str:
    """Best-effort git revision for provenance."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:  # pragma: no cover - provenance only
        pass
    return "unknown"


#: The six engine modules the spec requires to be ComfyUI-free and stdlib-only
#: (spec §8). These are the files that decide parity, so they are what we hash.
ENGINE_MODULES = (
    "geometry.py",
    "framing.py",
    "scene.py",
    "continuity.py",
    "autoframe.py",
    "reliability.py",
)


def engine_hash() -> tuple[str, list[str]]:
    """A sha256 over the six engine modules, so fixture drift cannot be silent.

    `parity_check.py` recomputes this and refuses to pass when it differs from
    the value frozen in the fixtures — a stale fixture set proves nothing.
    """
    import hashlib

    digest = hashlib.sha256()
    present = []
    for name in ENGINE_MODULES:
        path = os.path.join(APP_DIR, "cinematographer", name)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        try:
            with open(path, "rb") as fh:
                digest.update(fh.read())
        except FileNotFoundError:
            digest.update(b"<missing>")
        else:
            present.append(name)
        digest.update(b"\0")
    return digest.hexdigest(), present


def main() -> int:
    digest, present = engine_hash()
    data = {
        "meta": {
            "generated_by": "web/tools/gen_fixtures.py",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine": "cinematographer/ (Python)",
            "engine_revision": engine_revision(),
            "engine_hash_sha256": digest,
            "engine_hash_modules": list(ENGINE_MODULES),
            "engine_hash_modules_present": present,
            "note": (
                "Expected values are computed by the Python engine, not hand-written. "
                "The two 'go-test-*' fixtures are additionally cross-checked against the "
                "reference engine's own test output. "
                "engine_hash_sha256 covers the six engine modules; parity_check.py "
                "recomputes it and fails when the fixtures are stale."
            ),
        },
        "framing": [],
        "continuity": [],
        "reliability": [],
        "autoframe": [],
        "director": {},
    }

    for fx in FRAMING:
        rep = evaluate_framing(fx["subject"], fx["camera"], fx["shot_type"], fx["intent"])
        data["framing"].append(
            {
                "id": fx["id"],
                "description": fx["description"],
                "subject": fx["subject"].to_dict(),
                "camera": fx["camera"].to_dict(),
                "shot_type": fx["shot_type"],
                "intent": fx["intent"].to_dict(),
                "expected": rep.to_dict(),
            }
        )

    for fx in CONTINUITY:
        issues = evaluate_continuity(fx["shots"])
        data["continuity"].append(
            {
                "id": fx["id"],
                "description": fx["description"],
                "shots": [s.to_dict() for s in fx["shots"]],
                "expected": [i.to_dict() for i in issues],
            }
        )

    for fx in RELIABILITY:
        zone = camera_reliability_zone(
            fx["camera"], fx["subject"], fx["azimuth_deg"], fx["elevation_deg"]
        )
        data["reliability"].append(
            {
                "id": fx["id"],
                "description": fx["description"],
                "subject": fx["subject"].to_dict(),
                "camera": fx["camera"].to_dict(),
                "azimuth_deg": fx["azimuth_deg"],
                "elevation_deg": fx["elevation_deg"],
                "expected": zone.to_dict(),
            }
        )

    for fx in AUTOFRAME:
        res = auto_frame_camera(fx["subject"], fx["shot_type"], fx["intent"])
        data["autoframe"].append(
            {
                "id": fx["id"],
                "description": fx["description"],
                "subject": fx["subject"].to_dict(),
                "shot_type": fx["shot_type"],
                "intent": fx["intent"].to_dict(),
                "expected": res.to_dict(),
            }
        )

    director, director_notes = director_fixtures()
    data["director"] = director

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

    print(f"wrote {OUT}")
    print(f"  engine sha256 {digest[:16]}… over {len(present)}/{len(ENGINE_MODULES)} modules")
    print(
        "  framing={framing} continuity={continuity} reliability={reliability} autoframe={autoframe}".format(
            **{k: len(data[k]) for k in ("framing", "continuity", "reliability", "autoframe")}
        )
    )
    print(
        "  director: {e} enums, {c} credit cells".format(
            e=len(director["enums"]), c=len(director["credits"])
        )
    )
    for note in director_notes:
        print(f"    note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
