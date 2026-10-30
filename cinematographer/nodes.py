"""ComfyUI node classes for ComfyUI-Cinematographer.

Eighteen nodes, one category (``Cinematographer``). Every structured input and output
is a plain JSON string, so the nodes compose with anything in a graph and are
trivially testable without ComfyUI installed.

This is the only module in the package permitted to touch ComfyUI, and even here
the dependency is optional: the probe below is wrapped, so this module -- and
every node class in it -- imports cleanly on a machine with no ComfyUI. That is
what lets ``python -c "import cinematographer"`` work in CI and lets the
director's panel reuse the same classes.

The engine modules (``geometry``, ``framing``, ``scene``, ``continuity``,
``character``, ``autoframe``, ``reliability``, ``elements``, ``post``,
``director``, ``prompt``) are imported lazily and defensively: a missing or
broken engine module does not stop the pack from importing, it only makes the
node that needs it raise a clear error when that node is actually executed.

Engine entry points are resolved by name with a fallback, so both the spec's
CamelCase names (``EvaluateFraming``) and the Pythonic snake_case names the
engine actually ships (``evaluate_framing``) work.

``CinemaGradeApply`` is the only node in this pack that changes pixels. Every
other node measures, describes, or assembles text.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import sys
from typing import Any

__all__ = [
    # the judge
    "CinematographerEvaluate",
    "CinematographerAutoFrame",
    "ChorosContinuity",
    "CharacterContinuity",
    "SceneFramingExtras",
    "CameraReliabilityZone",
    "CinematographerCorrection",
    # stage 1.3 ATTACH
    "CinemaElementSave",
    "CinemaElementLoad",
    "CinemaElementList",
    # stage 3 DIRECT
    "CinemaDirectorPanel",
    "CinemaCameraMove",
    "CinemaEmotionWheel",
    # stage 4 SHOOT
    "CinemaPromptCompose",
    # stage 5 POST
    "CinemaGrade",
    "CinemaGradeApply",
    "CinemaExtend",
    "CinemaEdit",
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

_ENGINE_MODULES = (
    "geometry",
    "framing",
    "scene",
    "continuity",
    "character",
    "autoframe",
    "reliability",
    "elements",
    "post",
    "director",
    "prompt",
)
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


def _combo(module: Any, constant: str, *, prepend: tuple[str, ...] = ()) -> list[str]:
    """A ComfyUI dropdown whose options ARE the engine's own constant.

    A dropdown must never drift from the engine, so this reads the constant at
    ``INPUT_TYPES()`` time instead of copying its values into this file. If the
    constant is missing that is a hard error: a silently-empty dropdown would be
    far worse than a loud failure, because the graph would still build and the
    user would only find out at execution.

    ``prepend`` puts extra options in front (typically ``("auto",)``) without
    duplicating a value the engine already lists.
    """
    values = getattr(module, constant, None)
    if values is None:
        raise RuntimeError(
            f"ComfyUI-Cinematographer: {module.__name__}.{constant} is missing; "
            "the engine API does not match the node pack."
        )
    out = list(prepend)
    for value in values:
        text = str(value)
        if text not in out:
            out.append(text)
    return out


def _parse_palette(text: Any) -> tuple[tuple[float, float, float], ...]:
    """Parse ``"0.82,0.61,0.55;0.11,0.09,0.08"`` into normalised RGB triples.

    Empty (or whitespace) means **not measured** and yields an empty tuple. It is
    deliberately NOT replaced with a default palette: ``elements`` refuses to
    invent one for exactly this reason -- an invented palette would make an
    appearance-drift measurement look like a pass. A malformed value is a hard
    error rather than a silent skip, so a typo cannot quietly become "not
    measured" either.
    """
    raw = str(text or "").strip()
    if not raw:
        return ()
    colours: list[tuple[float, float, float]] = []
    for chunk in raw.split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        parts = [p.strip() for p in piece.split(",")]
        if len(parts) != 3:
            raise ValueError(
                f"ComfyUI-Cinematographer: palette entry {piece!r} must be three "
                "comma-separated 0..1 RGB channels, e.g. '0.82,0.61,0.55'. "
                "Separate colours with ';'."
            )
        try:
            channels = tuple(float(p) for p in parts)
        except ValueError as exc:
            raise ValueError(
                f"ComfyUI-Cinematographer: palette entry {piece!r} has a channel "
                "that is not a number."
            ) from exc
        for channel in channels:
            if not (0.0 <= channel <= 1.0):
                raise ValueError(
                    f"ComfyUI-Cinematographer: palette channel {channel!r} in "
                    f"{piece!r} is outside 0..1; colours are normalised RGB."
                )
        colours.append(channels)  # type: ignore[arg-type]
    return tuple(colours)


# --------------------------------------------------------------------------
# Pixel maths -- the ONE place in this pack that changes an image
#
# These gains are this pack's own convention, like post.GRADE_RANGES itself.
# No published source defines them, and nothing here claims otherwise. The
# whole routine is a simple approximation, not colour science: each control is
# one arithmetic operation, applied in a fixed and documented order.
# --------------------------------------------------------------------------

#: How far a full-scale temperature swing moves the red and blue channels.
_TEMPERATURE_GAIN = 0.25
#: How hard the highlights control pulls on the top end.
_HIGHLIGHT_GAIN = 0.5
#: Peak amplitude of film grain at film_grain=1.0.
_GRAIN_GAIN = 0.08
#: Rec. 709 luma weights, used by the saturation control.
_LUMA = (0.2126, 0.7152, 0.0722)


def _to_array(image: Any) -> Any:
    """Best-effort conversion of a ComfyUI IMAGE to a float32 numpy array.

    ComfyUI hands custom nodes a torch tensor, which may be on any device. This
    unwraps the common cases and falls back to ``numpy.asarray`` so the node is
    also usable from a plain test harness with no torch installed.
    """
    import numpy as np

    obj = image
    detach = getattr(obj, "detach", None)
    if callable(detach):
        obj = detach()
    cpu = getattr(obj, "cpu", None)
    if callable(cpu):
        obj = cpu()
    numpy_fn = getattr(obj, "numpy", None)
    if callable(numpy_fn):
        obj = numpy_fn()
    return np.asarray(obj, dtype=np.float32)


def _from_array(array: Any, like: Any) -> Any:
    """Return ``array`` in the same container type as ``like``.

    ComfyUI expects a torch tensor back on an IMAGE output, so if the input was
    a tensor the output is one too. A numpy input stays numpy, which is what
    lets the tests exercise the pixel maths without torch.
    """
    module = (type(like).__module__ or "").split(".")[0]
    if module == "torch":
        import torch

        return torch.from_numpy(array)
    return array


def _box_blur_3x3(image: Any) -> Any:
    """A 3x3 box blur with edge padding. Used only by the sharpness control."""
    import numpy as np

    padded = np.pad(image, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
    height, width = image.shape[1], image.shape[2]
    acc = np.zeros_like(image)
    for dy in range(3):
        for dx in range(3):
            acc += padded[:, dy : dy + height, dx : dx + width, :]
    return acc / 9.0


def _grade_tensor(image: Any, settings: dict, seed: int) -> Any:
    """Apply the grade controls to an IMAGE tensor, in a fixed order.

    The order is part of the contract, not an implementation detail, because the
    controls do not commute: exposure, contrast, saturation, temperature,
    highlights, sharpness, film_grain, then a final clamp to 0..1. Every control
    is one arithmetic operation on ``[B,H,W,C]`` float data in 0..1.
    """
    import numpy as np

    source = _to_array(image)
    if source.ndim == 3:
        source = source[None, ...]
    if source.ndim != 4 or source.shape[-1] < 3:
        raise ValueError(
            "ComfyUI-Cinematographer: image must be [B,H,W,C] with at least 3 "
            f"channels, got shape {tuple(source.shape)}."
        )
    x = source.astype(np.float32, copy=True)

    exposure = float(settings.get("exposure", 0.0) or 0.0)
    if exposure:
        x = x * (2.0**exposure)

    contrast = float(settings.get("contrast", 0.0) or 0.0)
    if contrast:
        x = (x - 0.5) * (1.0 + contrast) + 0.5

    saturation = float(settings.get("saturation", 0.0) or 0.0)
    if saturation:
        gray = (
            x[..., 0] * _LUMA[0] + x[..., 1] * _LUMA[1] + x[..., 2] * _LUMA[2]
        )[..., None]
        x = gray + (x - gray) * (1.0 + saturation)

    temperature = float(settings.get("temperature", 0.0) or 0.0)
    if temperature:
        shift = temperature * _TEMPERATURE_GAIN
        x[..., 0] += shift
        x[..., 2] -= shift

    highlights = float(settings.get("highlights", 0.0) or 0.0)
    if highlights:
        # Weight rises from 0 at mid-grey to 1 at white, so this touches only
        # the top end -- "compress/expand the highlights", not the whole image.
        weight = np.clip((x - 0.5) * 2.0, 0.0, None)
        x = x * (1.0 + highlights * _HIGHLIGHT_GAIN * weight)

    sharpness = float(settings.get("sharpness", 0.0) or 0.0)
    if sharpness:
        x = x + sharpness * (x - _box_blur_3x3(x))

    grain = float(settings.get("film_grain", 0.0) or 0.0)
    if grain:
        # Seeded, so the same seed and plan give the same grain: a re-shoot is
        # repeatable and the node is testable.
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(x.shape).astype(np.float32)
        x = x + grain * _GRAIN_GAIN * noise

    x = np.clip(x, 0.0, 1.0)
    return _from_array(x, image)


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


class CharacterContinuity:
    """Identity continuity: did the character's appearance survive the cut?

    Measures palette drift, proportion drift, and scale drift between consecutive
    shots, and returns a correction with a real number for each failure. It
    measures *appearance* drift -- it does NOT verify facial identity, which
    needs a vision model and is out of scope for this pack.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Measure whether a character survived a cut: palette distance in RGB, "
        "eye-ratio proportion change, and screen-height change. Input is a JSON "
        "array of {name, bbox, palette, eye_ratio}. Returns the full report as "
        "JSON, the overall verdict, and a one-line summary. It measures "
        "appearance drift, not facial identity."
    )
    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("report_json", "overall_pass", "summary")
    FUNCTION = "character_continuity"
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
                            '[{"name": "hero", "bbox": [-0.2, -0.9, 0.2, 0.9], '
                            '"palette": [[0.8, 0.2, 0.2], [0.1, 0.1, 0.15]], '
                            '"eye_ratio": 0.92}, '
                            '{"name": "hero", "bbox": [-0.18, -0.85, 0.18, 0.85], '
                            '"palette": [[0.78, 0.22, 0.21], [0.11, 0.1, 0.14]], '
                            '"eye_ratio": 0.91}]'
                        ),
                    },
                ),
            },
        }

    def character_continuity(self, shots_json: str) -> tuple[str, bool, str]:
        character = _require("character")[0]
        raw = _loads(shots_json, "shots_json", default=[])
        if isinstance(raw, dict):
            raw = raw.get("shots", [])
        if not isinstance(raw, list):
            raise ValueError(
                "ComfyUI-Cinematographer: shots_json must be a JSON array of shots"
            )

        shot_cls = getattr(character, "CharacterAppearance", None)
        if shot_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: character.CharacterAppearance is missing; "
                "the engine API does not match the node pack."
            )
        shots = [shot_cls.from_dict(s) for s in raw]

        report_obj = _fn(
            character, "evaluate_character_continuity", "EvaluateCharacterContinuity"
        )(shots)
        report = _as_dict(report_obj)

        summary_fn = getattr(character, "character_continuity_summary", None)
        if callable(summary_fn):
            summary = str(summary_fn(report_obj))
        elif not report.get("drifts"):
            summary = "no consecutive shots to check"
        else:
            drifts = [d for d in report["drifts"] if isinstance(d, dict)]
            failed = [d for d in drifts if not d.get("pass")]
            summary = (
                f"PASS - {len(drifts)} appearance checks"
                if not failed
                else "FAIL - " + ", ".join(
                    f"{d.get('rule')} (shot {d.get('shot_a')}->{d.get('shot_b')})"
                    for d in failed
                )
            )
        return (_dumps(report), bool(report.get("overall_pass", False)), summary)


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


# ==========================================================================
# Stage 1.3 ATTACH -- the Element registry (engine: elements.py)
#
# An Element is a named, categorised, reusable reference. It is created once and
# tagged thereafter as @Name, which is what makes the five stages a pipeline
# rather than a pile of graphs.
# ==========================================================================


def _default_registry_path() -> str:
    """Where the Element registry lives when the caller does not say.

    ``elements.py`` deliberately ships no default location -- a hard-coded one
    would be an invented convention with no published source, so the module
    leaves it to the caller. The *node* is the caller, so it resolves one here:
    ComfyUI's own output directory when ComfyUI is present, a relative path
    otherwise. Either way the widget is editable, so nothing is forced.
    """
    base = None
    try:  # pragma: no cover - only inside a ComfyUI install
        import folder_paths  # type: ignore

        base = folder_paths.get_output_directory()
    except Exception:  # noqa: BLE001 - ComfyUI absent, or its API moved
        base = None
    if base:
        return os.path.join(base, "cinematographer", "elements.json")
    return os.path.join("cinematographer", "elements.json")


def _registry(module: Any, path: str) -> Any:
    """Load the Element registry at ``path``, or start an empty one."""
    registry_cls = getattr(module, "ElementRegistry", None)
    if registry_cls is None:
        raise RuntimeError(
            "ComfyUI-Cinematographer: elements.ElementRegistry is missing; "
            "the engine API does not match the node pack."
        )
    if path and os.path.isfile(path):
        return registry_cls.load(path)
    return registry_cls()


def _registry_note(path: str) -> str:
    """Say whether the registry file was actually there.

    A missing registry and a misspelled tag both come back as "unresolved", and
    on a fresh install the first is the likelier cause: nothing has been saved
    yet, so *every* ``@tag`` is unresolved. Saying which one it is costs one
    ``os.path.isfile`` and saves the operator from hunting a typo that is not
    there. Returns "" when the file exists, so the common case adds no noise.
    """
    if not str(path or "").strip():
        return "no registry_path set, so no @tag can resolve"
    if not os.path.isfile(path):
        return (
            f"no registry file at {path!r} yet -- save an Element first "
            "(CinemaElementSave), or point registry_path at an existing one"
        )
    return ""


class CinemaElementSave:
    """Register an asset as a named, categorised, reusable Element.

    Writes the per-asset sidecar and adds the Element to the project registry, so
    later shots can reference it as ``@Name``.

    ``palette`` and the ``bbox_*`` inputs are what make the Element usable for
    identity continuity, not just for prompt text: ``elements``'
    ``character_record_from_element`` **raises** for an Element with no palette or
    no bbox, so an Element saved without them feeds the prompt but cannot be
    measured for appearance drift. Both are optional and both default to "not
    measured" -- an empty palette and no box -- because inventing either would
    make a drift measurement look like a pass.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Save an asset as an Element: a named, categorised reference that later "
        "shots reuse as an @Name tag. Writes a sidecar next to the asset and "
        "updates the project registry. Takes an image PATH, not an IMAGE tensor "
        "-- the engine is stdlib-only and never touches pixels. Supply palette "
        "and bbox to make the Element measurable for identity continuity; leave "
        "them unset and it still works as a prompt reference, but drift cannot "
        "be measured against it."
    )
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("element_json", "sidecar_path", "summary")
    FUNCTION = "save"
    # OUTPUT_NODE, not a pure function: this node's whole job is a side effect on
    # disk. ComfyUI prunes a node whose outputs nothing consumes, so without this
    # a save whose summary is not wired anywhere would silently never run.
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        elements = _require("elements")[0]
        return {
            "required": {
                "name": ("STRING", {"default": "tamsin"}),
                "category": (_combo(elements, "ELEMENT_CATEGORIES"),),
                "image_path": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Path to the asset on disk. The engine stores "
                        "this string; it never reads the file.",
                    },
                ),
            },
            "optional": {
                "description": ("STRING", {"multiline": True, "default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "palette": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "Dominant colours, ordered by coverage, as "
                        "semicolon-separated 0..1 RGB triples, e.g. "
                        "'0.82,0.61,0.55;0.11,0.09,0.08'. Leave EMPTY when the "
                        "palette was not measured -- empty means 'not measured' "
                        "and is stored as an empty palette. It is never replaced "
                        "with a default: an invented palette would make an "
                        "appearance-drift measurement look like a pass.",
                    },
                ),
                "has_bbox": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Tick to store a bounding box. Unticked means "
                        "'not measured' and stores no box at all, which is "
                        "distinguishable from a real box at the origin.",
                    },
                ),
                "bbox_min_x": (
                    "FLOAT",
                    {
                        "default": -1.0,
                        "min": -1.0,
                        "max": 1.0,
                        "step": 0.01,
                        "tooltip": "NDC, -1..1, y up. Only stored when has_bbox "
                        "is ticked.",
                    },
                ),
                "bbox_min_y": (
                    "FLOAT",
                    {"default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01},
                ),
                "bbox_max_x": (
                    "FLOAT",
                    {"default": 1.0, "min": -1.0, "max": 1.0, "step": 0.01},
                ),
                "bbox_max_y": (
                    "FLOAT",
                    {"default": 1.0, "min": -1.0, "max": 1.0, "step": 0.01},
                ),
                "registry_path": ("STRING", {"default": _default_registry_path()}),
            },
        }

    def save(
        self,
        name: str,
        category: str,
        image_path: str,
        description: str = "",
        seed: int = 0,
        palette: str = "",
        has_bbox: bool = False,
        bbox_min_x: float = -1.0,
        bbox_min_y: float = -1.0,
        bbox_max_x: float = 1.0,
        bbox_max_y: float = 1.0,
        registry_path: str = "",
    ) -> tuple[str, str, str]:
        elements = _require("elements")[0]
        element_cls = getattr(elements, "Element", None)
        sidecar_fn = getattr(elements, "sidecar_path", None)
        if element_cls is None or not callable(sidecar_fn):
            raise RuntimeError(
                "ComfyUI-Cinematographer: elements.Element / elements.sidecar_path "
                "are missing; the engine API does not match the node pack."
            )
        asset = str(image_path or "").strip()
        if not asset:
            raise ValueError(
                "ComfyUI-Cinematographer: image_path must be the path to the asset "
                "on disk. This node stores the path; it does not read the file."
            )

        element = element_cls(
            name=str(name),
            category=str(category),
            asset_path=asset,
            description=str(description or ""),
            seed=int(seed or 0),
            palette=_parse_palette(palette),
            bbox=(
                (
                    float(bbox_min_x),
                    float(bbox_min_y),
                    float(bbox_max_x),
                    float(bbox_max_y),
                )
                if has_bbox
                else None
            ),
        )
        record = _as_dict(element)

        sidecar = str(sidecar_fn(asset))
        parent = os.path.dirname(os.path.abspath(sidecar))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(sidecar, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        registry = _registry(elements, str(registry_path or ""))
        registry.add(element)
        if registry_path:
            registry.save(str(registry_path))

        summary = f"saved {category} '{name}' -> {sidecar}"
        return (_dumps(record), sidecar, summary)


class CinemaElementLoad:
    """Resolve an Element name back to its asset and record."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Look up an Element by name, optionally within a category, and return its "
        "asset path and record. An unknown name is REPORTED, not raised: "
        "found=False and an empty path, so a graph can branch on it. An ambiguous "
        "name (same name in two categories, category='any') is a real error and "
        "does raise."
    )
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("asset_path", "element_json", "found")
    FUNCTION = "load"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        elements = _require("elements")[0]
        return {
            "required": {
                "name": ("STRING", {"default": "tamsin"}),
                "category": (_combo(elements, "ELEMENT_CATEGORIES", prepend=("any",)),),
            },
            "optional": {
                "registry_path": ("STRING", {"default": _default_registry_path()}),
            },
        }

    def load(
        self, name: str, category: str, registry_path: str = ""
    ) -> tuple[str, str, bool]:
        elements = _require("elements")[0]
        registry = _registry(elements, str(registry_path or ""))
        wanted = None if str(category) == "any" else str(category)

        # find() returns None when absent and raises ValueError when the name is
        # ambiguous. Absence is a normal outcome; ambiguity is a configuration
        # error the user needs to see.
        element = registry.find(str(name), wanted)
        if element is None:
            return ("", "{}", False)
        record = _as_dict(element)
        return (str(record.get("asset_path", "")), _dumps(record), True)


class CinemaElementList:
    """Enumerate the project's Elements, so a graph can be built against a real cast list."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "List the Element names in the project registry, optionally filtered by "
        "category. Returns a JSON array of names, the count, and a one-line "
        "summary. An empty or missing registry is an empty list, not an error."
    )
    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("names_json", "count", "summary")
    FUNCTION = "list_elements"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        elements = _require("elements")[0]
        return {
            "required": {
                "category": (_combo(elements, "ELEMENT_CATEGORIES", prepend=("all",)),),
            },
            "optional": {
                "registry_path": ("STRING", {"default": _default_registry_path()}),
            },
        }

    def list_elements(self, category: str, registry_path: str = "") -> tuple[str, int, str]:
        elements = _require("elements")[0]
        registry = _registry(elements, str(registry_path or ""))
        wanted = str(category)

        if wanted == "all":
            names = [str(n) for n in registry.names()]
        else:
            names = [str(e.name) for e in registry.by_category(wanted)]

        where = "" if wanted == "all" else f" in '{wanted}'"
        if names:
            summary = f"{len(names)} Element(s){where}: " + ", ".join(names)
        else:
            summary = f"no Elements{where} (registry is empty)"
        return (_dumps(names), len(names), summary)


# ==========================================================================
# Stage 5 POST -- grade / extend / edit (engine: post.py)
#
# Every node here emits a PLAN. None of them touches a pixel: the engine is a
# pure description layer, and the graph applies the plan with image nodes. The
# summaries say "plan", never "graded".
# ==========================================================================


class CinemaGrade:
    """Describe a colour grade as a plan of per-parameter deltas.

    This is the **gate**, not the grader. It takes the judge's verdict text as an
    optional ``corrections`` input and carries it into ``grade_json`` under a
    ``corrections`` key. It does not interpret the verdict -- it *requires* it, so
    that POST cannot execute without the judge having executed. Wire
    ``grade_json`` into :class:`CinemaGradeApply` to actually change pixels.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Build a colour-grade plan from the seven documented controls, carrying "
        "the judge's corrections through with it. This node DESCRIBES the grade; "
        "it does not apply it -- wire grade_json into CinemaGradeApply to change "
        "pixels. Out-of-range values are rejected by the engine with the "
        "parameter, the value and the range named."
    )
    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("grade_json", "is_neutral", "summary")
    FUNCTION = "grade"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        post = _require("post")[0]
        # The seven controls come from the engine's own GRADE_PARAMS, so adding
        # an eighth in post.py adds a widget here with no edit to this file.
        params = _combo(post, "GRADE_PARAMS")
        neutral = getattr(post, "GRADE_NEUTRAL", None) or {}
        ranges = getattr(post, "GRADE_RANGES", None) or {}

        required: dict[str, Any] = {}
        for param in params:
            lo, hi = ranges.get(param, (-1.0, 1.0))
            required[param] = (
                "FLOAT",
                {
                    "default": float(neutral.get(param, 0.0)),
                    "min": float(lo),
                    "max": float(hi),
                    "step": 0.01,
                },
            )
        return {
            "required": required,
            "optional": {
                # The judge's verdict text, carried through to the plan. This node
                # does not interpret it -- it *requires* it, so POST cannot execute
                # without the judge having executed. See the class docstring.
                "corrections": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    def grade(self, corrections: str = "", **settings: float) -> tuple[str, bool, str]:
        post = _require("post")[0]
        settings_cls = getattr(post, "GradeSettings", None)
        if settings_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: post.GradeSettings is missing; "
                "the engine API does not match the node pack."
            )
        grade_settings = settings_cls(**{k: float(v) for k, v in settings.items()})
        plan = _fn(post, "apply_grade")(grade_settings)
        data = _as_dict(plan)
        # Carry the judge's verdict, do not drop it. The plan then records what
        # the judge said as well as what the grade will do.
        data["corrections"] = str(corrections or "")

        is_neutral = False
        for source, attr in ((plan, "is_noop"), (grade_settings, "is_neutral")):
            probe = getattr(source, attr, None)
            if callable(probe):
                is_neutral = bool(probe())
                break
        else:
            is_neutral = not any(float(v) for v in settings.values())

        summary_fn = getattr(plan, "summary", None)
        if callable(summary_fn):
            summary = str(summary_fn())
        elif is_neutral:
            summary = "neutral grade plan (no change)"
        else:
            deltas = data.get("deltas") or []
            bits = [
                f"{d.get('param')} {d.get('direction')}"
                for d in deltas
                if isinstance(d, dict)
            ]
            summary = f"grade plan: {len(deltas)} delta(s)" + (
                " -- " + ", ".join(bits) if bits else ""
            )
        return (_dumps(data), is_neutral, summary)


class CinemaExtend:
    """Plan a Sequel or Prequel continuation of a shot."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Plan a Sequel or Prequel: the mode, the duration in seconds, and how many "
        "frames overlap the source. Returns the plan as JSON and the overlap in "
        "seconds. It describes the extension; the graph performs it."
    )
    RETURN_TYPES = ("STRING", "FLOAT", "STRING")
    RETURN_NAMES = ("extend_json", "overlap_s", "summary")
    FUNCTION = "extend"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        post = _require("post")[0]
        lo, hi = getattr(post, "EXTEND_DURATION_RANGE", (4.0, 30.0))
        default_duration = float(getattr(post, "DEFAULT_EXTEND_DURATION_S", 5.0))
        max_overlap = int(getattr(post, "EXTEND_OVERLAP_MAX_FRAMES", 48))
        return {
            "required": {
                "mode": (_combo(post, "EXTEND_MODES"),),
                "duration_s": (
                    "FLOAT",
                    {
                        "default": default_duration,
                        "min": float(lo),
                        "max": float(hi),
                        "step": 0.5,
                    },
                ),
                "overlap_frames": (
                    "INT",
                    {"default": 0, "min": 0, "max": max_overlap},
                ),
            },
        }

    def extend(self, mode: str, duration_s: float, overlap_frames: int) -> tuple[str, float, str]:
        post = _require("post")[0]
        plan_cls = getattr(post, "ExtendPlan", None)
        if plan_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: post.ExtendPlan is missing; "
                "the engine API does not match the node pack."
            )
        plan = plan_cls(
            mode=str(mode),
            duration_s=float(duration_s),
            overlap_frames=int(overlap_frames),
        )
        data = _as_dict(plan)

        overlap_s = getattr(plan, "overlap_s", None)
        if overlap_s is None:
            overlap_s = data.get("overlap_s")
        if overlap_s is None:
            fps = float(getattr(post, "DEFAULT_FPS", 24.0) or 24.0)
            overlap_s = round(int(overlap_frames) / fps, 4) if fps else 0.0
        overlap_s = float(overlap_s)

        summary = (
            f"{mode} plan: {float(duration_s):g}s, {int(overlap_frames)} frame(s) "
            f"overlap ({overlap_s:g}s)"
        )
        return (_dumps(data), overlap_s, summary)


class CinemaEdit:
    """Plan a regional edit: a labelled NDC box plus the instruction."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Plan a regional edit: a labelled box in normalised device coordinates "
        "(y up, edges +/-1) plus the instruction for that region. Returns the plan "
        "as JSON and whether the box is inside the frame. It describes the edit; "
        "the graph performs it."
    )
    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("edit_json", "in_frame", "summary")
    FUNCTION = "edit"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        # The +/-1 NDC convention is the engine's own, stated on EditRegion:
        # "bbox NDC (min_x,min_y,max_x,max_y), y up, edges +/-1". There is no
        # range constant to import, so the bound is cited rather than invented.
        def box(default: float) -> tuple[str, dict]:
            return ("FLOAT", {"default": default, "min": -1.0, "max": 1.0, "step": 0.01})

        return {
            "required": {
                "label": ("STRING", {"default": "region"}),
                "bbox_min_x": box(-0.5),
                "bbox_min_y": box(-0.5),
                "bbox_max_x": box(0.5),
                "bbox_max_y": box(0.5),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    def edit(
        self,
        label: str,
        bbox_min_x: float,
        bbox_min_y: float,
        bbox_max_x: float,
        bbox_max_y: float,
        prompt: str = "",
    ) -> tuple[str, bool, str]:
        post = _require("post")[0]
        region_cls = getattr(post, "EditRegion", None)
        plan_cls = getattr(post, "EditPlan", None)
        if region_cls is None or plan_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: post.EditRegion / post.EditPlan are "
                "missing; the engine API does not match the node pack."
            )
        bbox = (
            float(bbox_min_x),
            float(bbox_min_y),
            float(bbox_max_x),
            float(bbox_max_y),
        )
        region = region_cls(label=str(label), bbox=bbox, prompt=str(prompt or ""))
        plan = plan_cls(regions=[region])
        data = _as_dict(plan)

        in_frame_fn = getattr(region, "in_frame", None)
        if callable(in_frame_fn):
            in_frame = bool(in_frame_fn())
        else:
            in_frame = all(-1.0 <= v <= 1.0 for v in bbox)

        summary = (
            f"edit plan '{label}' bbox=({bbox[0]:g},{bbox[1]:g},{bbox[2]:g},{bbox[3]:g}) "
            + ("in frame" if in_frame else "OUTSIDE the frame")
        )
        return (_dumps(data), in_frame, summary)


class CinemaGradeApply:
    """Apply a grade plan to an image. The one POST node that touches pixels.

    ``grade_json`` is **required, not optional**. That is deliberate: it is what
    makes the judge -> POST gate a real data dependency end to end, so POST cannot
    execute without the judge having executed::

        judge -> CinemaGrade.corrections -> CinemaGrade.grade_json
              -> CinemaGradeApply.image

    Honesty, three ways
    -------------------

    1. **The control ranges are invented.** They come from
       :data:`cinematographer.post.GRADE_RANGES`, which is this pack's own
       convention. No published source defines them, and nothing here claims
       otherwise.
    2. **This is a simple, approximate grade, not colour science.** Each control
       is one arithmetic operation on the tensor. It is not a film emulation, not
       a LUT, and not a colour-managed pipeline. It exists so the plan the judge
       produced has somewhere to land.
    3. **``summary`` says "applied"**, never "plan". Every other POST node in this
       pack describes; this one has actually changed the pixels, and the wording
       has to say so.

    ``film_grain`` is seeded from a widget so a run is reproducible: the same seed
    and the same plan give the same grain, which is what makes the node testable
    and a re-shoot repeatable.
    """

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Apply a grade plan to an image and return the graded image. This is the "
        "only POST node that changes pixels; Grade, Extend and Edit describe, this "
        "one applies. grade_json is REQUIRED so the judge must have run first. The "
        "control ranges are this pack's own convention (no published source) and "
        "the grade is a simple approximation, not colour science."
    )
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "summary")
    FUNCTION = "apply"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "image": ("IMAGE",),
                "grade_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "The grade_json output of Cinema Grade. "
                        "Required: POST must not run before the judge has.",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "tooltip": "Seeds film_grain only, so a run is "
                        "reproducible. Ignored when film_grain is 0.",
                    },
                ),
            },
        }

    def apply(self, image: Any, grade_json: str, seed: int = 0) -> tuple[Any, str]:
        post = _require("post")[0]
        params = tuple(getattr(post, "GRADE_PARAMS", ()))
        ranges = getattr(post, "GRADE_RANGES", {})
        neutral = getattr(post, "GRADE_NEUTRAL", {})

        # An empty grade_json is a hard error, not a neutral grade. The whole
        # point of requiring this input is that POST must not run before the
        # judge has; silently treating "nothing wired in" as "no changes" would
        # turn the gate into a no-op that still reports success.
        if not str(grade_json or "").strip():
            raise ValueError(
                "ComfyUI-Cinematographer: grade_json is empty. Wire Cinema "
                "Grade's grade_json output in -- POST must not run before the "
                "judge has."
            )
        plan = _loads(grade_json, "grade_json", default=None)
        if plan is None:
            raise ValueError(
                "ComfyUI-Cinematographer: grade_json is not valid JSON. Wire "
                "Cinema Grade's grade_json output in -- POST must not run "
                "before the judge has."
            )
        if not isinstance(plan, dict):
            raise ValueError(
                "ComfyUI-Cinematographer: grade_json must be a JSON object, got "
                f"{type(plan).__name__}."
            )

        # The plan carries the deltas; the *settings* are the "to" values. A
        # control absent from the plan is neutral, which is exactly what the
        # engine means by "no delta".
        settings: dict[str, float] = {}
        for param in params:
            settings[param] = float(neutral.get(param, 0.0))
        for delta in plan.get("deltas") or []:
            if not isinstance(delta, dict):
                continue
            param = delta.get("param")
            if param not in settings:
                continue
            try:
                value = float(delta.get("to"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"ComfyUI-Cinematographer: grade_json delta for {param!r} has "
                    f"a non-numeric 'to' value {delta.get('to')!r}."
                ) from exc
            low, high = ranges.get(param, (None, None))
            if low is not None and not (float(low) <= value <= float(high)):
                raise ValueError(
                    f"ComfyUI-Cinematographer: grade control {param}={value} is "
                    f"outside its legal range {float(low)}..{float(high)}."
                )
            settings[param] = value

        out = _grade_tensor(image, settings, int(seed or 0))

        touched = [p for p in params if settings.get(p, 0.0) != float(neutral.get(p, 0.0))]
        if touched:
            detail = ", ".join(f"{p}={settings[p]:g}" for p in touched)
            summary = f"applied grade: {len(touched)} control(s) - {detail}"
        else:
            summary = "applied grade: neutral (image unchanged)"
        return (out, summary)


class CinemaDirectorPanel:
    """The Stage 3 director's panel: five groups, each on auto or set."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "The director's panel: film (genre/era/pacing), camera (body/lens/"
        "aperture), lighting, colour palette and per-character emotion. Every "
        "group starts on auto and an auto group contributes nothing. Returns the "
        "panel as JSON keyed by the API's own field names, the prompt fragment it "
        "contributes, and a summary. It describes the look; it does not render."
    )
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("panel_json", "prompt_fragment", "summary")
    FUNCTION = "panel"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        director = _require("director")[0]
        auto = ("auto",)
        return {
            "required": {
                "genre": (_combo(director, "GENRES", prepend=auto),),
                "era": (_combo(director, "ERAS", prepend=auto),),
                "pacing": (_combo(director, "TEMPOS", prepend=auto),),
                "camera_model": (_combo(director, "CAMERA_BODIES", prepend=auto),),
                "camera_lens": (_combo(director, "LENSES", prepend=auto),),
                "camera_aperture": (_combo(director, "APERTURES", prepend=auto),),
                "light": (_combo(director, "LIGHTING_LOOKS", prepend=auto),),
                "color_palette": (
                    _combo(director, "COLOUR_PALETTES", prepend=auto),
                ),
            },
            "optional": {
                "custom_palette": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "A user-created palette name. Only used when "
                        "color_palette is 'auto'. User-created palettes are not "
                        "members of the documented preset list, so they are "
                        "accepted here as free text.",
                    },
                ),
                "emotion_character": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Character to direct, e.g. 'tamsin'. Leave "
                        "empty for no emotion direction.",
                    },
                ),
                "emotion": (
                    _combo(director, "EMOTIONS", prepend=auto),
                ),
                "emotion_intensity": (
                    "FLOAT",
                    {
                        "default": 0.5,
                        "min": float(getattr(director, "EMOTION_INTENSITY_MIN", 0.0)),
                        "max": float(getattr(director, "EMOTION_INTENSITY_MAX", 1.0)),
                        "step": 0.05,
                        "tooltip": "INVENTED scale -- no published source defines "
                        "it. Only used when an emotion is chosen.",
                    },
                ),
            },
        }

    def panel(
        self,
        genre: str,
        era: str,
        pacing: str,
        camera_model: str,
        camera_lens: str,
        camera_aperture: str,
        light: str,
        color_palette: str,
        custom_palette: str = "",
        emotion_character: str = "",
        emotion: str = "auto",
        emotion_intensity: float = 0.5,
    ) -> tuple[str, str, str]:
        director = _require("director")[0]
        panel_cls = getattr(director, "DirectorPanel", None)
        if panel_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: director.DirectorPanel is missing; "
                "the engine API does not match the node pack."
            )

        def pick(value: str) -> Any:
            """'auto' means the group is untouched, which the engine spells None."""
            text = str(value or "").strip()
            return None if text in ("", "auto") else text

        palette_text = pick(color_palette)
        custom = False
        if palette_text is None:
            free = str(custom_palette or "").strip()
            if free:
                palette_text = free
                custom = True

        emotions: list[Any] = []
        character = str(emotion_character or "").strip()
        chosen = pick(emotion)
        if character:
            direction_cls = getattr(director, "EmotionDirection", None)
            if direction_cls is None:
                raise RuntimeError(
                    "ComfyUI-Cinematographer: director.EmotionDirection is "
                    "missing; the engine API does not match the node pack."
                )
            emotions.append(
                direction_cls(
                    character=character,
                    emotion=chosen,
                    intensity=(
                        float(emotion_intensity) if chosen is not None else None
                    ),
                )
            )

        panel = panel_cls.from_dict(
            {
                "genre": pick(genre),
                "era": pick(era),
                "pacing": pick(pacing),
                "camera_model": pick(camera_model),
                "camera_lens": pick(camera_lens),
                "camera_aperture": pick(camera_aperture),
                "light": pick(light),
                "color_palette": palette_text,
                "custom": custom,
                "emotion": [d.to_dict() for d in emotions],
            }
        )

        data = _as_dict(panel)
        fragment_fn = getattr(director, "panel_prompt_fragment", None)
        fragment = str(fragment_fn(panel)) if callable(fragment_fn) else ""
        summary_fn = getattr(director, "panel_summary", None)
        summary = (
            str(summary_fn(panel))
            if callable(summary_fn)
            else ("director panel: all groups auto" if panel.is_auto() else "director panel")
        )
        return (_dumps(data), fragment, summary)


class CinemaCameraMove:
    """Resolve the ``#move`` tags in a prompt against the engine's move list."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Resolve the #camera-move tags in a prompt against the engine's list of "
        "named moves. Returns the prompt with the tags stripped, the recognised "
        "moves, the unknown ones, and whether every tag resolved. An unknown move "
        "is reported, never silently dropped."
    )
    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("clean_prompt", "moves", "unknown", "ok")
    FUNCTION = "resolve"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        prompt = _require("prompt")[0]
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {
                "move": (
                    _combo(prompt, "CAMERA_MOVES", prepend=("none",)),
                ),
            },
        }

    def resolve(self, prompt: str, move: str = "none") -> tuple[str, str, str, bool]:
        prompt_mod = _require("prompt")[0]
        resolve_fn = getattr(prompt_mod, "resolve_move_tags", None)
        if resolve_fn is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: prompt.resolve_move_tags is missing; "
                "the engine API does not match the node pack."
            )
        resolution = resolve_fn(str(prompt or ""))

        moves = list(resolution.moves)
        unknown = list(resolution.unknown)
        # A move picked from the dropdown but absent from the text is still a
        # move the user asked for, so it is added rather than required to appear.
        chosen = str(move or "").strip()
        if chosen and chosen != "none" and chosen not in moves:
            moves.append(chosen)

        ok = bool(resolution.ok) and not unknown
        summary = (
            f"{len(moves)} move(s): {', '.join(moves)}"
            if moves
            else "no camera moves"
        )
        if unknown:
            summary += f" | UNKNOWN: {', '.join(unknown)}"
        return (
            str(resolution.clean_prompt),
            _dumps(moves),
            _dumps(unknown),
            ok,
        )


class CinemaEmotionWheel:
    """One character's emotion and intensity, as a direction."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Direct one character's emotion and intensity, e.g. '@tamsin Joy 0.5'. "
        "Returns the direction as JSON and the '@character Emotion' fragment it "
        "contributes. The intensity scale is this pack's own invention -- no "
        "published source defines it."
    )
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("direction_json", "fragment", "summary")
    FUNCTION = "direct"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        director = _require("director")[0]
        return {
            "required": {
                "character": ("STRING", {"default": "tamsin"}),
                "emotion": (_combo(director, "EMOTIONS"),),
                "intensity": (
                    "FLOAT",
                    {
                        "default": 0.5,
                        "min": float(getattr(director, "EMOTION_INTENSITY_MIN", 0.0)),
                        "max": float(getattr(director, "EMOTION_INTENSITY_MAX", 1.0)),
                        "step": 0.05,
                        "tooltip": "INVENTED scale -- no published source defines "
                        "it.",
                    },
                ),
            },
        }

    def direct(
        self, character: str, emotion: str, intensity: float
    ) -> tuple[str, str, str]:
        director = _require("director")[0]
        direction_cls = getattr(director, "EmotionDirection", None)
        if direction_cls is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: director.EmotionDirection is missing; "
                "the engine API does not match the node pack."
            )
        direction = direction_cls(
            character=str(character),
            emotion=str(emotion),
            intensity=float(intensity),
        )
        data = _as_dict(direction)
        fragment = f"@{direction.character} {direction.emotion} {direction.intensity:g}"
        summary = (
            f"emotion direction: @{direction.character} {direction.emotion} "
            f"at {direction.intensity:g} (intensity scale is invented)"
        )
        return (_dumps(data), fragment, summary)


class CinemaPromptCompose:
    """Assemble the Stage 4 prompt from the action, panel, Elements and moves."""

    CATEGORY = "Cinematographer"
    DESCRIPTION = (
        "Assemble the Stage 4 prompt: the action prose, the director's panel "
        "fragment, the @Element tags and the #camera-move tags, in that order and "
        "nothing else. Resolves @Name against the Element registry and reports "
        "every tag it could not resolve. Returns the final prompt, the API "
        "reference attachments, and the unresolved tags."
    )
    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = (
        "final_prompt",
        "attachments_json",
        "unresolved_json",
        "ok",
        "summary",
    )
    FUNCTION = "compose"
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "action": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {
                "panel_json": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "The panel_json output of Cinema Director "
                        "Panel. Empty means no panel.",
                    },
                ),
                "registry_path": ("STRING", {"default": _default_registry_path()}),
                "moves": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "Extra move names, one per line or "
                        "comma-separated. Added to the #tags found in the action.",
                    },
                ),
            },
        }

    def compose(
        self,
        action: str,
        panel_json: str = "",
        registry_path: str = "",
        moves: str = "",
    ) -> tuple[str, str, str, bool]:
        prompt_mod = _require("prompt")[0]
        compose_fn = getattr(prompt_mod, "compose_prompt", None)
        if compose_fn is None:
            raise RuntimeError(
                "ComfyUI-Cinematographer: prompt.compose_prompt is missing; "
                "the engine API does not match the node pack."
            )

        panel = None
        raw_panel = str(panel_json or "").strip()
        if raw_panel:
            director = _require("director")[0]
            panel_cls = getattr(director, "DirectorPanel", None)
            if panel_cls is None:
                raise RuntimeError(
                    "ComfyUI-Cinematographer: director.DirectorPanel is missing; "
                    "the engine API does not match the node pack."
                )
            data = _loads(raw_panel, "panel_json", default=None)
            if not isinstance(data, dict):
                raise ValueError(
                    "ComfyUI-Cinematographer: panel_json must be a JSON object, "
                    f"got {type(data).__name__}."
                )
            panel = panel_cls.from_dict(data)

        registry = None
        if str(registry_path or "").strip():
            elements = _require("elements")[0]
            registry = _registry(elements, str(registry_path))

        extra: list[str] = []
        for chunk in str(moves or "").replace(",", "\n").splitlines():
            name = chunk.strip().lstrip("#")
            if name and name not in extra:
                extra.append(name)

        composed = compose_fn(
            str(action or ""),
            panel=panel,
            elements=registry,
            moves=extra or None,
        )
        data = _as_dict(composed)
        unresolved = list(composed.unresolved)
        ok = bool(composed.is_ok())
        summary = (
            f"composed prompt: {len(composed.element_tags)} element(s), "
            f"{len(composed.move_tags)} move(s)"
        )
        if unresolved:
            summary += f" | UNRESOLVED: {', '.join(unresolved)}"
            note = _registry_note(str(registry_path or ""))
            if note:
                summary += f" | {note}"
        return (
            str(composed.final_prompt),
            _dumps(data.get("attachments", [])),
            _dumps(unresolved),
            ok,
            summary,
        )


NODE_CLASS_MAPPINGS = {
    # --- the judge: measure a frame against the rules -----------------------
    "CinematographerEvaluate": CinematographerEvaluate,
    "CinematographerAutoFrame": CinematographerAutoFrame,
    "ChorosContinuity": ChorosContinuity,
    "CharacterContinuity": CharacterContinuity,
    "SceneFramingExtras": SceneFramingExtras,
    "CameraReliabilityZone": CameraReliabilityZone,
    "CinematographerCorrection": CinematographerCorrection,
    # --- stage 1.3 ATTACH: the Element registry -----------------------------
    "CinemaElementSave": CinemaElementSave,
    "CinemaElementLoad": CinemaElementLoad,
    "CinemaElementList": CinemaElementList,
    # --- stage 3 DIRECT: the panel, the moves, the emotion wheel ------------
    "CinemaDirectorPanel": CinemaDirectorPanel,
    "CinemaCameraMove": CinemaCameraMove,
    "CinemaEmotionWheel": CinemaEmotionWheel,
    # --- stage 4 SHOOT: assemble the prompt ---------------------------------
    "CinemaPromptCompose": CinemaPromptCompose,
    # --- stage 5 POST: grade / extend / edit --------------------------------
    "CinemaGrade": CinemaGrade,
    "CinemaGradeApply": CinemaGradeApply,
    "CinemaExtend": CinemaExtend,
    "CinemaEdit": CinemaEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CinematographerEvaluate": "Cinematographer Evaluate",
    "CinematographerAutoFrame": "Cinematographer Auto-Frame",
    "ChorosContinuity": "Choros Continuity",
    "CharacterContinuity": "Character Continuity",
    "SceneFramingExtras": "Scene Framing Extras",
    "CameraReliabilityZone": "Camera Reliability Zone",
    "CinematographerCorrection": "Cinematographer Correction",
    "CinemaElementSave": "Cinema Element Save",
    "CinemaElementLoad": "Cinema Element Load",
    "CinemaElementList": "Cinema Element List",
    "CinemaDirectorPanel": "Cinema Director Panel",
    "CinemaCameraMove": "Cinema Camera Move",
    "CinemaEmotionWheel": "Cinema Emotion Wheel",
    "CinemaPromptCompose": "Cinema Prompt Compose",
    "CinemaGrade": "Cinema Grade",
    "CinemaGradeApply": "Cinema Grade Apply",
    "CinemaExtend": "Cinema Extend",
    "CinemaEdit": "Cinema Edit",
}
