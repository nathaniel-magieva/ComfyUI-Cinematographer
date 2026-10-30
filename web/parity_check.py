#!/usr/bin/env python3
"""Parity check: the panel's JavaScript must reproduce the Python engine exactly.

    python3 web/parity_check.py

Three comparisons, in order:

  1. **JS vs frozen fixtures** — `cinematographer.js` (run under Node) against the
     expected values in `parity_fixtures.json`, which were generated *by the
     Python engine* (`tools/gen_fixtures.py`). This is the check that proves the
     numbers on screen are the engine's numbers.
  2. **Python engine vs frozen fixtures** — catches fixture drift if the engine
     changed after the fixtures were frozen.
  3. **Python engine vs JS, live** — the strongest check: both engines are run on
     the same inputs right now and compared field by field.

Exit code 0 means every comparison agreed. Non-zero means the panel would show
numbers the engine disagrees with — which is worse than showing nothing.

The Python engine is imported read-only from `cinematographer/`. If it is not
importable, comparisons 2 and 3 are skipped and reported as SKIPPED (the check
still fails if comparison 1 fails).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "parity_fixtures.json")
RUNNER = os.path.join(HERE, "parity_runner.mjs")

#: Absolute tolerance for numbers. Rule values are rounded to 3 dp by both
#: engines, so agreement here is effectively exact; the slack only absorbs the
#: last-bit differences between libm and V8's Math.
TOL = 1e-9

#: Raw (unrounded) camera floats from the solver accumulate over 24 iterations.
CAM_TOL = 1e-6


class Mismatch:
    def __init__(self, fixture: str, path: str, expected, actual):
        self.fixture = fixture
        self.path = path
        self.expected = expected
        self.actual = actual

    def __str__(self) -> str:
        return f"    {self.fixture}: {self.path}\n        expected: {self.expected!r}\n        actual:   {self.actual!r}"


def compare(fixture_id: str, expected, actual, path: str, tol: float, out: list[Mismatch]) -> None:
    """Deep-compare two JSON-shaped values, collecting every difference."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected != actual:
            out.append(Mismatch(fixture_id, path, expected, actual))
        return
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if abs(float(expected) - float(actual)) > tol:
            out.append(Mismatch(fixture_id, path, expected, actual))
        return
    if isinstance(expected, str) or isinstance(actual, str):
        if expected != actual:
            out.append(Mismatch(fixture_id, path, expected, actual))
        return
    if expected is None or actual is None:
        if expected != actual:
            out.append(Mismatch(fixture_id, path, expected, actual))
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            out.append(Mismatch(fixture_id, path, f"list[{len(expected)}]", f"list[{len(actual) if isinstance(actual, list) else type(actual).__name__}]"))
            return
        for i, (e, a) in enumerate(zip(expected, actual)):
            compare(fixture_id, e, a, f"{path}[{i}]", tol, out)
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            out.append(Mismatch(fixture_id, path, "object", type(actual).__name__))
            return
        for key in expected:
            if key not in actual:
                out.append(Mismatch(fixture_id, f"{path}.{key}", expected[key], "<missing>"))
                continue
            # The solver's camera carries raw floats; everything else is rounded.
            child_tol = CAM_TOL if path.endswith(".camera") or path == "camera" else tol
            compare(fixture_id, expected[key], actual[key], f"{path}.{key}", child_tol, out)
        for key in actual:
            if key not in expected:
                out.append(Mismatch(fixture_id, f"{path}.{key}", "<absent>", actual[key]))
        return
    if expected != actual:
        out.append(Mismatch(fixture_id, path, expected, actual))


# ---------------------------------------------------------------------------
# JS side
# ---------------------------------------------------------------------------


def run_js() -> dict:
    node = os.environ.get("NODE", "node")
    proc = subprocess.run(
        [node, RUNNER, FIXTURES],
        capture_output=True,
        text=True,
        cwd=HERE,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"parity_runner.mjs failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise SystemExit(f"parity_runner.mjs did not emit JSON: {exc}\n{proc.stdout[:2000]}")


# ---------------------------------------------------------------------------
# Python engine side
# ---------------------------------------------------------------------------


def load_engine():
    """Import the engine, or return None with a reason."""
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    try:
        from cinematographer.autoframe import auto_frame_camera
        from cinematographer.continuity import ContinuityShot, evaluate_continuity
        from cinematographer.framing import evaluate_framing
        from cinematographer.geometry import CamPose, ShotIntent, Subject
        from cinematographer.reliability import camera_reliability_zone
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        return None, f"{type(exc).__name__}: {exc}"
    return (
        {
            "auto_frame_camera": auto_frame_camera,
            "ContinuityShot": ContinuityShot,
            "evaluate_continuity": evaluate_continuity,
            "evaluate_framing": evaluate_framing,
            "CamPose": CamPose,
            "ShotIntent": ShotIntent,
            "Subject": Subject,
            "camera_reliability_zone": camera_reliability_zone,
        },
        None,
    )


def run_engine(engine: dict, fixtures: dict) -> dict:
    out = {"framing": [], "continuity": [], "reliability": [], "autoframe": []}

    for fx in fixtures["framing"]:
        rep = engine["evaluate_framing"](
            engine["Subject"].from_dict(fx["subject"]),
            engine["CamPose"].from_dict(fx["camera"]),
            fx["shot_type"],
            engine["ShotIntent"].from_dict(fx["intent"]),
        )
        out["framing"].append({"id": fx["id"], "actual": rep.to_dict()})

    for fx in fixtures["continuity"]:
        shots = [engine["ContinuityShot"].from_dict(s) for s in fx["shots"]]
        out["continuity"].append(
            {"id": fx["id"], "actual": [i.to_dict() for i in engine["evaluate_continuity"](shots)]}
        )

    for fx in fixtures["reliability"]:
        zone = engine["camera_reliability_zone"](
            engine["CamPose"].from_dict(fx["camera"]),
            engine["Subject"].from_dict(fx["subject"]),
            fx["azimuth_deg"],
            fx["elevation_deg"],
        )
        out["reliability"].append({"id": fx["id"], "actual": zone.to_dict()})

    for fx in fixtures["autoframe"]:
        res = engine["auto_frame_camera"](
            engine["Subject"].from_dict(fx["subject"]),
            fx["shot_type"],
            engine["ShotIntent"].from_dict(fx["intent"]),
        )
        out["autoframe"].append({"id": fx["id"], "actual": res.to_dict()})

    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

SECTIONS = ("framing", "continuity", "reliability", "autoframe")


def compare_section(label: str, fixtures: dict, expected_key: str, actual: dict) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    by_id = {row["id"]: row["actual"] for row in actual[label]}
    for fx in fixtures[label]:
        if fx["id"] not in by_id:
            mismatches.append(Mismatch(fx["id"], "<fixture>", "present", "<missing>"))
            continue
        compare(fx["id"], fx["expected"], by_id[fx["id"]], label, TOL, mismatches)
    return mismatches


#: The six engine modules the spec requires to be ComfyUI-free (spec §8).
ENGINE_MODULES = (
    "geometry.py",
    "framing.py",
    "scene.py",
    "continuity.py",
    "autoframe.py",
    "reliability.py",
)


def current_engine_hash() -> str:
    """Recompute the engine hash the fixtures recorded, so drift is not silent."""
    import hashlib

    digest = hashlib.sha256()
    for name in ENGINE_MODULES:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        try:
            with open(os.path.join(APP_DIR, "cinematographer", name), "rb") as fh:
                digest.update(fh.read())
        except FileNotFoundError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    if not os.path.exists(FIXTURES):
        print(f"FAIL: fixtures not found at {FIXTURES}")
        print("      generate them with: python3 web/tools/gen_fixtures.py")
        return 1

    with open(FIXTURES, encoding="utf-8") as fh:
        fixtures = json.load(fh)

    meta = fixtures.get("meta", {})
    js = run_js()
    engine, engine_error = load_engine()

    frozen_hash = meta.get("engine_hash_sha256")
    live_hash = current_engine_hash()
    stale = bool(frozen_hash) and frozen_hash != live_hash

    print("Cinematographer parity check")
    print(f"  fixtures      : {os.path.relpath(FIXTURES, os.path.dirname(APP_DIR))}")
    print(f"  generated     : {meta.get('generated_at', '?')} (engine rev {meta.get('engine_revision', '?')})")
    if frozen_hash:
        tail = f"  ← STALE, live is {live_hash[:16]}…" if stale else "  (matches live engine)"
        print(f"  engine hash   : {frozen_hash[:16]}…{tail}")
    else:
        print("  engine hash   : not recorded (re-run tools/gen_fixtures.py)")
    print(f"  JS engine     : web/cinematographer.js (node {node_version()})")
    if engine:
        print("  Python engine : cinematographer/ (importable)")
    else:
        print(f"  Python engine : NOT IMPORTABLE ({engine_error})")
    print()

    if stale:
        print("STALE FIXTURES — the engine changed after the fixtures were frozen, so the")
        print("comparisons below are against outdated expectations and prove nothing.")
        print("Re-freeze, then re-check:")
        print("    python3 web/tools/gen_fixtures.py && python3 web/parity_check.py")
        print()

    # Structural sanity: the task requires >= 5 framing fixtures with all 9 rules.
    structural: list[str] = []
    if len(fixtures["framing"]) < 5:
        structural.append(f"only {len(fixtures['framing'])} framing fixtures (need >= 5)")
    for fx in fixtures["framing"]:
        rules = [s["rule"] for s in fx["expected"]["scores"]]
        if len(rules) != 9:
            structural.append(f"{fx['id']}: {len(rules)} rules (need 9)")
        missing = set(rules) ^ {
            "in_frame",
            "rule_of_thirds",
            "headroom",
            "shot_size",
            "lead_room",
            "negative_space",
            "camera_angle",
            "level",
            "direct_address",
        }
        if missing:
            structural.append(f"{fx['id']}: unexpected rule set (diff {sorted(missing)})")

    failures: list[Mismatch] = []
    findings: list[str] = []
    total = 0

    print("[1/3] JS vs frozen fixtures")
    for section in SECTIONS:
        ms = compare_section(section, fixtures, "expected", js)
        total += len(fixtures[section])
        print(f"  {section:<12} {len(fixtures[section]) - len(ms)}/{len(fixtures[section])} OK")
        failures.extend(ms)
    d_checked, d_ok, d_engine = compare_director(fixtures, js, None, failures, findings)
    total += d_checked
    print(f"  {'director':<12} {d_ok}/{d_checked} OK")
    print()

    if engine:
        print("[2/3] Python engine vs frozen fixtures")
        engine_out = run_engine(engine, fixtures)
        for section in SECTIONS:
            ms = compare_section(section, fixtures, "expected", engine_out)
            print(f"  {section:<12} {len(fixtures[section]) - len(ms)}/{len(fixtures[section])} OK")
            failures.extend(ms)
        print()

        print("[3/3] Python engine vs JS (live)")
        for section in SECTIONS:
            ms: list[Mismatch] = []
            js_by_id = {row["id"]: row["actual"] for row in js[section]}
            eng_by_id = {row["id"]: row["actual"] for row in engine_out[section]}
            for fx in fixtures[section]:
                compare(fx["id"], eng_by_id[fx["id"]], js_by_id[fx["id"]], section, TOL, ms)
            print(f"  {section:<12} {len(fixtures[section]) - len(ms)}/{len(fixtures[section])} OK")
            failures.extend(ms)
        print()

        # The Director's Panel engine modules are a separate import: they are not
        # part of the six geometry modules, and their absence must be loud.
        director_mods, director_error = load_director_engine()
        print("[4/4] Director's Panel — engine enums vs the API lists")
        if director_mods:
            _, _, compared = compare_director(
                fixtures, js, director_mods, failures, findings, check_js=False
            )
            if compared:
                print("  engine lists compared against the frozen API enums")
            else:
                print("  no director fixtures to compare")
        else:
            print("  SKIPPED — cinematographer/director.py is NOT importable")
            print(f"            reason: {director_error}")
            print("            This is a SKIP, not a pass: the Director tab's option lists are")
            print("            currently checked against the frozen API capture only, with no")
            print("            cross-check against the engine. Re-run once it lands.")
            findings.append(
                "director.py not importable — the Director tab's enums are NOT cross-checked "
                f"against the engine ({director_error})"
            )
        print()
    else:
        print("[2/3] Python engine vs frozen fixtures — SKIPPED (engine not importable)")
        print("[3/3] Python engine vs JS (live)         — SKIPPED (engine not importable)")
        print("[4/4] Director's Panel                   — SKIPPED (engine not importable)")
        print()

    if structural:
        print("Structural problems:")
        for s in structural:
            print(f"    {s}")
        print()

    if findings:
        print("FINDINGS — not failures, but do not let them go quiet:")
        for f in findings:
            print(f"    {f}")
        print()

    if failures or structural or stale:
        reasons = []
        if failures:
            reasons.append(f"{len(failures)} mismatch(es)")
        if structural:
            reasons.append(f"{len(structural)} structural problem(s)")
        if stale:
            reasons.append("stale fixtures (engine hash changed)")
        print(f"RESULT: FAIL — {', '.join(reasons)} across {total} fixtures")
        for m in failures[:80]:
            print(str(m))
        if len(failures) > 80:
            print(f"    ... and {len(failures) - 80} more")
        return 1

    print(
        f"RESULT: PASS — {total} fixtures, 0 mismatches"
        + ("" if engine else " (JS vs fixtures only; Python engine unavailable)")
    )
    return 0


# ---------------------------------------------------------------------------
# Director's Panel
# ---------------------------------------------------------------------------
#
# The Director tab's option lists are the API's closed enumerations. Two things
# are checked:
#
#   * `web/director.js` must match the frozen lists exactly. Drift is a failure.
#   * `cinematographer/director.py` + `prompt.py` must not contain a member the
#     API does not have. An INVENTED member is a failure.
#
# An engine that ships a *documented subset* of an enum is a different thing: it
# is incomplete, not wrong. That is reported as a FINDING — loudly, with the
# shortfall — and does not fail the check, because failing would push the next
# person to pad the list to make it green. Padding is the failure mode this
# project forbids.

#: fixture enum name -> (engine module, constant name)
DIRECTOR_ENGINE_ENUMS = {
    "genre": ("director", "GENRES"),
    "era": ("director", "ERAS"),
    "pacing": ("director", "TEMPOS"),
    "camera_model": ("director", "CAMERA_BODIES"),
    "camera_lens": ("director", "LENSES"),
    "camera_aperture": ("director", "APERTURES"),
    "camera_movement": ("prompt", "CAMERA_MOVES"),
    "light": ("director", "LIGHTING_LOOKS"),
    "color_palette": ("director", "COLOUR_PALETTES"),
    "emotion": ("director", "EMOTIONS"),
}

#: Totals the engine declares for enums it ships only partially.
DIRECTOR_ENGINE_TOTALS = {
    "camera_movement": ("prompt", "CAMERA_MOVES_TOTAL"),
    "color_palette": ("director", "COLOUR_PALETTES_TOTAL"),
}


def load_director_engine():
    """Import the Director's Panel engine modules, or return (None, reason)."""
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    try:
        from cinematographer import director as director_mod
        from cinematographer import prompt as prompt_mod
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        return None, f"{type(exc).__name__}: {exc}"
    return {"director": director_mod, "prompt": prompt_mod}, None


def compare_director(
    fixtures, js, engine_mods, failures, findings, check_js: bool = True
) -> tuple[int, int, bool]:
    """Compare the Director section. Returns (checked, ok, engine_compared)."""
    section = fixtures.get("director") or {}
    enums = section.get("enums", [])
    credits = section.get("credits", [])
    if not enums and not credits:
        return 0, 0, False

    checked = 0
    ok = 0

    # --- JS enums vs the frozen lists ---------------------------------------
    # A fixture may declare `ui_only` members: values the shipped UI offers but
    # the documented API rejects. The panel is required to show them AND to flag
    # them, so the JS list must equal the API values plus exactly those extras —
    # no more (drift) and no fewer (a hidden contradiction).
    js_enums = {row["id"]: row["actual"] for row in js.get("director", {}).get("enums", [])}
    for fx in enums:
        if not check_js:
            break
        checked += 1
        got = js_enums.get(fx["id"])
        expected_js = list(fx["values"]) + list(fx.get("ui_only", []))
        if got is None:
            failures.append(Mismatch(fx["id"], "director.enum", expected_js, "<missing from JS>"))
            continue
        if list(got) != expected_js:
            failures.append(Mismatch(fx["id"], "director.enum", expected_js, list(got)))
        else:
            ok += 1

    # --- JS credits vs the published table ----------------------------------
    js_credits = {row["id"]: row for row in js.get("director", {}).get("credits", [])}
    for fx in credits:
        if not check_js:
            break
        checked += 1
        got = js_credits.get(fx["id"])
        if got is None:
            failures.append(
                Mismatch(fx["id"], "director.credits", fx["expected_credits"], "<missing from JS>")
            )
            continue
        if int(got["actual"]) != int(fx["expected_credits"]):
            failures.append(
                Mismatch(fx["id"], "director.credits", fx["expected_credits"], got["actual"])
            )
        elif int(got["current"]) > int(got["actual"]):
            failures.append(
                Mismatch(fx["id"], "director.credits.discount", "<= list", got["current"])
            )
        else:
            ok += 1

    # --- the engine's own lists ---------------------------------------------
    if not engine_mods:
        return checked, ok, False

    for fx in enums:
        name = fx["enum"]
        target = DIRECTOR_ENGINE_ENUMS.get(name)
        if not target:
            findings.append(
                f"{name}: the engine has no constant for this enum "
                f"({len(fx['values'])} API values are unmodelled)"
            )
            continue
        mod_name, const_name = target
        values = getattr(engine_mods[mod_name], const_name, None)
        if values is None:
            findings.append(f"{name}: {mod_name}.{const_name} not found in the engine")
            continue

        engine_values = [str(v) for v in values]
        api_values = [str(v) for v in fx["values"]]

        # Case-insensitive: the engine uses Title Case for emotions, the panel
        # uses slugs. That is presentation, not a different enum.
        engine_lc = {v.lower() for v in engine_values}
        api_lc = {v.lower() for v in api_values}

        invented = sorted(engine_lc - api_lc)
        if invented:
            failures.append(
                Mismatch(fx["id"], f"director.engine.{const_name}.invented", sorted(api_lc), invented)
            )

        missing = sorted(api_lc - engine_lc)
        if missing:
            total = len(api_values)
            declared = None
            dt = DIRECTOR_ENGINE_TOTALS.get(name)
            if dt:
                declared = getattr(engine_mods[dt[0]], dt[1], None)
            findings.append(
                f"{name}: engine ships {len(engine_values)} of {total} "
                f"({len(missing)} missing)"
                + (f"; engine declares TOTAL={declared}" if declared is not None else "")
                + f" — missing: {', '.join(missing[:6])}"
                + (" …" if len(missing) > 6 else "")
            )

    return checked, ok, True


def node_version() -> str:
    try:
        return subprocess.run(
            [os.environ.get("NODE", "node"), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip() or "?"
    except Exception:  # pragma: no cover - cosmetic
        return "?"


if __name__ == "__main__":
    raise SystemExit(main())
