"""ComfyUI-Cinematographer -- the missing DP layer for ComfyUI re-shoot.

Every re-shoot app asks you to aim a camera and hope. This pack tells you the
frame is wrong, by how much, and which way to move -- before you spend the
render.

Exports
-------
``NODE_CLASS_MAPPINGS`` / ``NODE_DISPLAY_NAME_MAPPINGS``
    The six ComfyUI nodes (see :mod:`cinematographer.nodes`).
``geometry``, ``framing``, ``scene``, ``continuity``, ``autoframe``,
``reliability``
    The pure-Python engine, re-exported for convenience. It is stdlib-only and
    has no ComfyUI dependency, so it is importable anywhere.

Importing this package never requires ComfyUI. If the engine modules are
missing, the import still succeeds and ``ENGINE_IMPORT_ERROR`` records why --
the node that needs a missing module raises a clear error only when executed.
"""

from __future__ import annotations

import importlib
import os

__version__ = "0.1.0"

# --------------------------------------------------------------------------
# The ComfyUI nodes. nodes.py is the only module that may touch ComfyUI, and it
# degrades gracefully when ComfyUI is absent, so this import is always safe.
# --------------------------------------------------------------------------
from .nodes import (  # noqa: E402
    CameraReliabilityZone as _CameraReliabilityZoneNode,
    ChorosContinuity as _ChorosContinuityNode,
    CinematographerAutoFrame as _CinematographerAutoFrameNode,
    CinematographerCorrection as _CinematographerCorrectionNode,
    CinematographerEvaluate as _CinematographerEvaluateNode,
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    SceneFramingExtras as _SceneFramingExtrasNode,
)

#: The six node classes, re-exported by their ComfyUI class names.
CinematographerEvaluate = _CinematographerEvaluateNode
CinematographerAutoFrame = _CinematographerAutoFrameNode
ChorosContinuity = _ChorosContinuityNode
SceneFramingExtras = _SceneFramingExtrasNode
CameraReliabilityZone = _CameraReliabilityZoneNode
CinematographerCorrection = _CinematographerCorrectionNode

# --------------------------------------------------------------------------
# Safe re-export of the engine API.
# --------------------------------------------------------------------------
_ENGINE_MODULES = ("geometry", "framing", "scene", "continuity", "autoframe", "reliability")

#: ``None`` when every engine module imported; otherwise the reason it did not.
ENGINE_IMPORT_ERROR: str | None = None

for _name in _ENGINE_MODULES:
    try:
        globals()[_name] = importlib.import_module("." + _name, __name__)
    except ImportError as _exc:  # pragma: no cover - only when the engine is absent
        ENGINE_IMPORT_ERROR = f"{_name}: {_exc}"

del _name

#: Public engine names, re-exported at package level. Each entry maps the
#: exported name to ``(module, attribute)``. The CamelCase aliases are the names
#: used by the node-pack API; the snake_case names are what
#: the engine ships. Both resolve.
_ENGINE_EXPORTS = {
    # geometry
    "Vec3": ("geometry", "Vec3"),
    "CamPose": ("geometry", "CamPose"),
    "Subject": ("geometry", "Subject"),
    "ShotIntent": ("geometry", "ShotIntent"),
    "FramingScore": ("geometry", "FramingScore"),
    "FramingReport": ("geometry", "FramingReport"),
    "SHOT_TYPES": ("geometry", "SHOT_TYPES"),
    "projector": ("geometry", "projector"),
    "anchors": ("geometry", "anchors"),
    "round3": ("geometry", "round3"),
    # framing
    "evaluate_framing": ("framing", "evaluate_framing"),
    "EvaluateFraming": ("framing", "evaluate_framing"),
    "framing_summary": ("framing", "summary"),
    "FRAMING_RULES": ("framing", "FRAMING_RULES"),
    # scene
    "PlacedEntity": ("scene", "PlacedEntity"),
    "SceneGraph": ("scene", "SceneGraph"),
    "scene_framing_extras": ("scene", "scene_framing_extras"),
    # NOTE: the CamelCase alias "SceneFramingExtras" is deliberately NOT exported
    # here -- the spec uses that name for both the engine rule set and the
    # ComfyUI node, and the node class wins at package level. Reach the engine
    # function as scene.scene_framing_extras or scene_framing_extras.
    # continuity
    "ContinuityShot": ("continuity", "ContinuityShot"),
    "ContinuityIssue": ("continuity", "ContinuityIssue"),
    "evaluate_continuity": ("continuity", "evaluate_continuity"),
    "EvaluateContinuity": ("continuity", "evaluate_continuity"),
    "continuity_summary": ("continuity", "continuity_summary"),
    "CONTINUITY_RULES": ("continuity", "CONTINUITY_RULES"),
    # autoframe
    "AutoFrameResult": ("autoframe", "AutoFrameResult"),
    "auto_frame_camera": ("autoframe", "auto_frame_camera"),
    "AutoFrameCamera": ("autoframe", "auto_frame_camera"),
    "autoframe_summary": ("autoframe", "autoframe_summary"),
    "mood_to_intent": ("autoframe", "mood_to_intent"),
    "MAX_ITERATIONS": ("autoframe", "MAX_ITERATIONS"),
    # reliability
    "ReliabilityZone": ("reliability", "ReliabilityZone"),
    "camera_reliability_zone": ("reliability", "camera_reliability_zone"),
    # NOTE: the CamelCase alias "CameraReliabilityZone" is deliberately NOT
    # exported here -- the spec uses that name for both the engine function and
    # the ComfyUI node, and the node class wins at package level. Reach the
    # engine function as reliability.camera_reliability_zone or
    # camera_reliability_zone.
    "ZONES": ("reliability", "ZONES"),
}

for _export, (_module_name, _attr) in _ENGINE_EXPORTS.items():
    _module = globals().get(_module_name)
    if _module is not None and hasattr(_module, _attr):
        globals()[_export] = getattr(_module, _attr)

del _export, _module_name, _attr, _module

# --------------------------------------------------------------------------
# ComfyUI web assets. The director's panel lives at web/ (a sibling of this
# package), not inside it, so there is normally nothing to serve from here. If a
# ``cinematographer/web`` directory is ever added, expose it the standard way.
# --------------------------------------------------------------------------
_web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.isdir(_web_dir):
    WEB_DIRECTORY = "web"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "ENGINE_IMPORT_ERROR",
    "__version__",
    "CinematographerEvaluate",
    "CinematographerAutoFrame",
    "ChorosContinuity",
    "SceneFramingExtras",
    "CameraReliabilityZone",
    "CinematographerCorrection",
    *_ENGINE_MODULES,
    *_ENGINE_EXPORTS.keys(),
]
