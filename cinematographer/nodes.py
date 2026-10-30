"""ComfyUI node classes for ComfyUI-Cinematographer.

Six nodes, one category (``Cinematographer``). Every structured input and output
is a plain JSON string, so the nodes compose with anything in a graph and are
trivially testable without ComfyUI installed.

This is the only module in the package permitted to touch ComfyUI, and even here
the dependency is optional: the probe below is wrapped, so this module -- and
every node class in it -- imports cleanly on a machine with no ComfyUI. That is
what lets ``python -c "import cinematographer"`` work in CI and lets the
director's panel reuse the same classes.

The geometry engine (``geometry``, ``framing``, ``scene``, ``continuity``,
``autoframe``, ``reliability``) is imported lazily and defensively: a missing or
broken engine module does not stop the pack from importing, it only makes the
node that needs it raise a clear error when that node is actually executed.

Engine entry points are resolved by name with a fallback, so both the spec's
CamelCase names (``EvaluateFraming``) and the Pythonic snake_case names the
engine actually ships (``evaluate_framing``) work.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import sys
from typing import Any

__all__ = [
    "CinematographerEvaluate",
    "CinematographerAutoFrame",
    "ChorosContinuity",
    "SceneFramingExtras",
    "CameraReliabilityZone",
    "CinematographerCorrection",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "COMFYUI_AVAILABLE",
]

# --------------------------------------------------------------------------
# The one ComfyUI import in the package -- optional, and never load-bearing.
# --------------------------------------------------------------------------
try:  # pragma: no cover - only true inside a ComfyUI install
    import comfy.utils as _comfy_utils  # noqa: F401

    COMFYUI_AVAILABLE = True
except Exception:  # noqa: BLE001 - a half-installed ComfyUI can raise anything
    _comfy_utils = None
    COMFYUI_AVAILABLE = False


# --------------------------------------------------------------------------
# Engine loading -- lazy, defensive, and re-tried until it succeeds
# --------------------------------------------------------------------------

_ENGINE_MODULES = ("geometry", "framing", "scene", "continuity", "autoframe", "reliability")
_ENGINE: dict[str, Any] = {}
_ENGINE_ERROR: str | None = None


def _import_engine_module(name: str) -> Any:
    """Import one engine module, tolerating being loaded outside the package."""
    package = __package__ or "cinematographer"
    try:
        return importlib.import_module("." + name, package)
    except ImportError as exc:
        # Only fall back when the *target file* is missing. An ImportError raised
        # from inside the engine module (a real bug, or a missing third-party
        # dependency) must propagate rather than be silently retried.
        if exc.name not in (name, package + "." + name):
            raise
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        return importlib.import_module(name)


def _load_engine() -> dict[str, Any]:
    """Import every engine module that is importable; cache the successes."""
    global _ENGINE_ERROR
    missing: list[str] = []
    for name in _ENGINE_MODULES:
        if name in _ENGINE:
            continue
        try:
            _ENGINE[name] = _import_engine_module(name)
        except ImportError as exc:
            missing.append(f"{name} ({exc})")
    _ENGINE_ERROR = "; ".join(missing) if missing else None
    return _ENGINE


def _require(*names: str) -> list[Any]:
    """Return the named engine modules, or raise a message a user can act on."""
    engine = _load_engine()
    missing = [n for n in names if n not in engine]
    if missing:
        raise RuntimeError(
            "ComfyUI-Cinematographer: engine module(s) "
            + ", ".join(missing)
            + " could not be imported"
            + (f" ({_ENGINE_ERROR})" if _ENGINE_ERROR else "")
            + ". The node pack is installed but the pure-Python engine is not."
        )
    return [engine[n] for n in names]


def _fn(module: Any, *names: str) -> Any:
    """Resolve an engine entry point by any of its accepted names."""
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    raise RuntimeError(
        f"ComfyUI-Cinematographer: {module.__name__} exposes none of {names!r}; "
        "the engine API does not match the node pack."
    )


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------


def _loads(text: Any, what: str, default: Any = None) -> Any:
    """Parse a node's JSON string input, with a clear error when it is malformed."""
    if text is None:
        return {} if default is None else default
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str):
        raise ValueError(
            f"ComfyUI-Cinematographer: {what} must be a JSON string, "
            f"got {type(text).__name__}"
        )
    if not text.strip():
        return {} if default is None else default
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(
            f"ComfyUI-Cinematographer: {what} is not valid JSON: {exc}"
        ) from exc


def _json_default(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=repr)
    if isinstance(obj, (tuple, list)):
        return list(obj)
    return str(obj)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default, ensure_ascii=False, sort_keys=False)


def _as_dict(obj: Any) -> dict:
    """Normalise an engine return value (dataclass, dict, or None) to a dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(
        f"ComfyUI-Cinematographer: cannot serialise {type(obj).__name__} to JSON"
    )


def _check_shot_type(geometry: Any, shot_type: str) -> None:
    allowed = tuple(getattr(geometry, "SHOT_TYPES", ("closeup", "medium", "wide")))
    if shot_type not in allowed:
        raise ValueError(
            f"ComfyUI-Cinematographer: shot_type must be one of {allowed}, "
            f"got {shot_type!r}"
        )


# --------------------------------------------------------------------------
# Report rendering -- the human-readable strings the panel and the graph show
# --------------------------------------------------------------------------


def _scores_summary(report: dict) -> str:
    scores = report.get("scores")
    if not isinstance(scores, list) or not scores:
        return "no framing scores returned"
    verdict = "PASS" if report.get("overall_pass") else "FAIL"
    bits = [f"{verdict} {report.get('shot_type', '?')} on '{report.get('subject', '?')}'"]
    fails = [s for s in scores if isinstance(s, dict) and not s.get("pass")]
    if not fails:
        bits.append("all weighted rules pass")
    for s in fails:
        bits.append(f"{s.get('rule')}={s.get('value')}")
    return " | ".join(bits)


def _framing_summary(framing: Any, report_obj: Any, report: dict) -> str:
    fn = getattr(framing, "summary", None)
    if callable(fn):
        try:
            text = fn(report_obj)
        except Exception:  # noqa: BLE001 - a summary is cosmetic; never fail the node
            text = None
        if isinstance(text, str) and text.strip():
            return text
    text = report.get("summary")
    if isinstance(text, str) and text.strip():
        return text
    return _scores_summary(report)


def _extras_summary(scores: list) -> str:
    if not scores:
        return "no multi-entity rules evaluated"
    bits = []
    for s in scores:
        if not isinstance(s, dict):
            continue
        passed = s.get("pass")
        tag = "PASS" if passed else ("FAIL" if passed is not None else "INFO")
        bits.append(f"{s.get('rule', '?')}={s.get('value')} {tag}")
    return "; ".join(bits) if bits else "no multi-entity rules evaluated"


def _corrections(report: dict) -> list[str]:
    """Every failing rule's correction lever, newline-joinable and de-duplicated."""
    out: list[str] = []

    def push(line: Any) -> None:
        text = str(line).strip()
        if text and text not in out:
            out.append(text)

    def lever(entry: dict) -> Any:
        return entry.get("correction") or entry.get("lever") or entry.get("fix")

    scores = report.get("scores")
    if isinstance(scores, list):
        for s in scores:
            if isinstance(s, dict) and not s.get("pass"):
                corr = lever(s)
                if corr:
                    push(f"{s.get('rule', 'rule')}: {corr}")

    rules = report.get("rules")
    if isinstance(rules, dict):
        for name, entry in rules.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("pass", entry.get("passed", True)):
                continue
            corr = lever(entry)
            if corr:
                push(f"{name}: {corr}")

    for key in ("corrections", "levers"):
        value = report.get(key)
        if isinstance(value, str):
            for line in value.splitlines():
                push(line)
        elif isinstance(value, (list, tuple)):
            for line in value:
                push(line)

    issues = report.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict) and not issue.get("pass", True):
                push(
                    f"{issue.get('rule', 'issue')} "
                    f"(shot {issue.get('shot_a')}->{issue.get('shot_b')}): "
                    f"{issue.get('detail', '')}"
                )

    return out


def _zone_reason(result: Any) -> tuple[str, str]:
    data = _as_dict(result)
    zone = str(data.get("zone", "")).strip().lower()
    reason = str(data.get("reason", "") or "")
    if zone not in ("green", "yellow", "red"):
        note = f"engine returned an unrecognised zone {zone!r}; reported as red"
        reason = f"{reason} ({note})" if reason else note
        zone = "red"
    return zone, reason


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


class CinematographerEvaluate:
    """Project a subject through a camera pose and score the 9 framing rules.

    Per rule: a measured value, a pass/fail, and the camera lever that fixes it.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Score a camera pose against the 9 deterministic framing rules. Returns "
        "the full report as JSON, the weighted overall verdict, and a one-line "
        "summary. No model, no GPU, no AI cost -- it is arithmetic."
    )
    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("report_json", "overall_pass", "summary")
    FUNCTION = "evaluate"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "subject_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8, "facing_yaw_deg": 0.0}',
                    },
                ),
                "camera_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"eye": [0.0, 1.66, 3.0], "target": [0.0, 1.66, 0.0], "focal_mm": 35.0}',
                    },
                ),
                "shot_type": (["closeup", "medium", "wide"],),
            },
            "optional": {
                "intent_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"angle": "eye", "side": "center", "center": false, "dutch_deg": 0.0, "azimuth_deg": 0.0}',
                    },
                ),
            },
        }

    def evaluate(
        self,
        subject_json: str,
        camera_json: str,
        shot_type: str,
        intent_json: str = "{}",
    ) -> tuple[str, bool, str]:
        geometry, framing = _require("geometry", "framing")
        _check_shot_type(geometry, shot_type)
        subject = geometry.Subject.from_dict(_loads(subject_json, "subject_json"))
        cam = geometry.CamPose.from_dict(_loads(camera_json, "camera_json"))
        intent = geometry.ShotIntent.from_dict(_loads(intent_json, "intent_json"))

        report_obj = _fn(framing, "evaluate_framing", "EvaluateFraming")(
            subject, cam, shot_type, intent
        )
        report = _as_dict(report_obj)
        return (
            _dumps(report),
            bool(report.get("overall_pass", False)),
            _framing_summary(framing, report_obj, report),
        )


class CinematographerAutoFrame:
    """Solve a compliant camera pose geometrically -- 24 iterations, no AI cost.

    Reports ``converged`` honestly: if the solve does not pass in 24 iterations
    it says so rather than returning a pose that merely looks solved.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Solve a camera pose that frames the subject per shot type and intent. "
        "Returns the pose, its framing report, whether the solve converged, and "
        "the iteration count actually used."
    )
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN", "INT")
    RETURN_NAMES = ("camera_json", "report_json", "converged", "iterations")
    FUNCTION = "autoframe"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "subject_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8, "facing_yaw_deg": 0.0}',
                    },
                ),
                "shot_type": (["closeup", "medium", "wide"],),
            },
            "optional": {
                "intent_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"angle": "eye", "side": "left", "center": false, "dutch_deg": 0.0, "azimuth_deg": 0.0}',
                    },
                ),
            },
        }

    def autoframe(
        self, subject_json: str, shot_type: str, intent_json: str = "{}"
    ) -> tuple[str, str, bool, int]:
        geometry, autoframe = _require("geometry", "autoframe")
        _check_shot_type(geometry, shot_type)
        subject = geometry.Subject.from_dict(_loads(subject_json, "subject_json"))
        intent = geometry.ShotIntent.from_dict(_loads(intent_json, "intent_json"))

        result = _fn(autoframe, "auto_frame_camera", "AutoFrameCamera")(
            subject, shot_type, intent
        )
        data = _as_dict(result)
        camera = data.get("camera") or {}
        report = data.get("report") or {}
        converged = bool(data.get("converged", False))
        iterations = int(data.get("iterations", 0) or 0)
        return (_dumps(camera), _dumps(report), converged, iterations)


class ChorosContinuity:
    """Sequence-level continuity: the 180-degree axis rule and the 30-degree rule.

    Flags a deliberate axis cross and a jump cut where consecutive shots change
    the camera angle by less than 30 degrees.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Check a shot list for the 180-degree axis rule and the 30-degree rule "
        "across cuts. Input is a JSON array of "
        "{shot_number, base, yaw_deg, camera}. Returns per-pair issues, the "
        "overall verdict, and a one-line summary."
    )
    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("issues_json", "all_pass", "summary")
    FUNCTION = "continuity"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "shots_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": (
                            '[{"shot_number": 1, "base": [0.0, 0.0, 0.0], "yaw_deg": 0.0, '
                            '"camera": {"eye": [2.0, 1.66, 2.0], "target": [0.0, 1.66, 0.0]}}, '
                            '{"shot_number": 2, "base": [0.0, 0.0, 0.0], "yaw_deg": 0.0, '
                            '"camera": {"eye": [-2.0, 1.66, 2.0], "target": [0.0, 1.66, 0.0]}}]'
                        ),
                    },
                ),
            },
        }

    def continuity(self, shots_json: str) -> tuple[str, bool, str]:
        geometry, continuity = _require("geometry", "continuity")
        raw = _loads(shots_json, "shots_json", default=[])
        if isinstance(raw, dict):
            raw = raw.get("shots", [])
        if not isinstance(raw, list):
            raise ValueError(
                "ComfyUI-Cinematographer: shots_json must be a JSON array of shots"
            )

        shot_cls = getattr(continuity, "ContinuityShot", None) or getattr(
            geometry, "ContinuityShot", None
        )
        if shot_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: continuity.ContinuityShot is missing; "
                "the engine API does not match the node pack."
            )
        shots = [shot_cls.from_dict(s) for s in raw]

        issues = _fn(continuity, "evaluate_continuity", "EvaluateContinuity")(shots)
        data = [_as_dict(i) for i in issues]
        all_pass = all(bool(i.get("pass", True)) for i in data)

        summary_fn = getattr(continuity, "continuity_summary", None)
        if callable(summary_fn):
            summary = str(summary_fn(issues))
        elif not data:
            summary = "no consecutive shots to check"
        else:
            failed = [i for i in data if not i.get("pass", True)]
            summary = (
                f"PASS - {len(data)} continuity checks"
                if not failed
                else "FAIL - " + ", ".join(
                    f"{i.get('rule')} (shot {i.get('shot_a')}->{i.get('shot_b')})"
                    for i in failed
                )
            )
        return (_dumps(data), all_pass, summary)


class SceneFramingExtras:
    """The 3 multi-entity rules: size = importance, dirty frame, eyeline."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Score the multi-entity rules for a shot: Hitchcock size-importance, "
        "foreground occlusion (dirty frame), and the two-shot eyeline. Input is "
        "a scene graph, a camera pose, and the key subject."
    )
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("scores_json", "summary")
    FUNCTION = "extras"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "scene_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"characters": [], "props": []}',
                    },
                ),
                "camera_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"eye": [0.0, 1.66, 3.0], "target": [0.0, 1.66, 0.0], "focal_mm": 35.0}',
                    },
                ),
                "key_subject_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8, "facing_yaw_deg": 0.0}',
                    },
                ),
            },
        }

    def extras(
        self, scene_json: str, camera_json: str, key_subject_json: str
    ) -> tuple[str, str]:
        geometry, scene = _require("geometry", "scene")
        scene_cls = getattr(scene, "SceneGraph", None)
        if scene_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: scene.SceneGraph is missing; "
                "the engine API does not match the node pack."
            )
        graph = scene_cls.from_dict(_loads(scene_json, "scene_json"))
        cam = geometry.CamPose.from_dict(_loads(camera_json, "camera_json"))
        key_subject = geometry.Subject.from_dict(
            _loads(key_subject_json, "key_subject_json")
        )

        scores = _fn(scene, "scene_framing_extras", "SceneFramingExtras")(
            graph, cam, key_subject
        )
        data = [_as_dict(s) for s in scores]
        return (_dumps(data), _extras_summary(data))


class CameraReliabilityZone:
    """Grade a requested pose against the view-steering training envelope.

    ``comfy-reshoot`` shows a hard-coded green/yellow/red indicator. This node
    *computes* it from the CrossView-Warp training range: green inside
    +/-45 degrees azimuth, yellow out to +/-60 degrees or beyond 30 degrees
    elevation, red past both.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Compute the green/yellow/red reliability zone for a camera pose against "
        "the view-steering training envelope, and say which axis left it."
    )
    RETURN_TYPES = (["green", "yellow", "red"], "STRING")
    RETURN_NAMES = ("zone", "reason")
    FUNCTION = "zone"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "camera_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"eye": [2.0, 1.66, 2.0], "target": [0.0, 1.66, 0.0], "focal_mm": 35.0}',
                    },
                ),
                "subject_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": '{"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8, "facing_yaw_deg": 0.0}',
                    },
                ),
                "azimuth_deg": (
                    "FLOAT",
                    {"default": 30.0, "min": -180.0, "max": 180.0, "step": 0.5},
                ),
                "elevation_deg": (
                    "FLOAT",
                    {"default": 10.0, "min": -90.0, "max": 90.0, "step": 0.5},
                ),
            },
        }

    def zone(
        self,
        camera_json: str,
        subject_json: str,
        azimuth_deg: float,
        elevation_deg: float,
    ) -> tuple[str, str]:
        geometry, reliability = _require("geometry", "reliability")
        cam = geometry.CamPose.from_dict(_loads(camera_json, "camera_json"))
        subject = geometry.Subject.from_dict(_loads(subject_json, "subject_json"))

        result = _fn(reliability, "camera_reliability_zone", "CameraReliabilityZone")(
            cam, subject, float(azimuth_deg), float(elevation_deg)
        )
        return _zone_reason(result)


class CinematographerCorrection:
    """Turn a framing report into the list of camera levers that fix it."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Read a report_json from CinematographerEvaluate (or any report with the "
        "same shape) and return the correction levers for every failing rule, "
        "one per line."
    )
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("corrections",)
    FUNCTION = "correction"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "report_json": (
                    "STRING",
                    {"multiline": True, "default": "{}"},
                ),
            },
        }

    def correction(self, report_json: str) -> tuple[str]:
        report = _loads(report_json, "report_json")
        if not isinstance(report, dict):
            raise ValueError(
                "ComfyUI-Cinematographer: report_json must be a JSON object"
            )
        return ("\n".join(_corrections(report)),)


NODE_CLASS_MAPPINGS = {
    "CinematographerEvaluate": CinematographerEvaluate,
    "CinematographerAutoFrame": CinematographerAutoFrame,
    "ChorosContinuity": ChorosContinuity,
    "SceneFramingExtras": SceneFramingExtras,
    "CameraReliabilityZone": CameraReliabilityZone,
    "CinematographerCorrection": CinematographerCorrection,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CinematographerEvaluate": "Cinematographer Evaluate",
    "CinematographerAutoFrame": "Cinematographer Auto-Frame",
    "ChorosContinuity": "Choros Continuity",
    "SceneFramingExtras": "Scene Framing Extras",
    "CameraReliabilityZone": "Camera Reliability Zone",
    "CinematographerCorrection": "Cinematographer Correction",
}
