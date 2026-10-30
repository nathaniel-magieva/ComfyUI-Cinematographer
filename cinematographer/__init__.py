"""ComfyUI-Cinematographer -- the missing DP layer for ComfyUI re-shoot.

Every re-shoot app asks you to aim a camera and hope. This pack tells you the
frame is wrong, by how much, and which way to move -- before you spend the
render.

Exports
-------
``NODE_CLASS_MAPPINGS`` / ``NODE_DISPLAY_NAME_MAPPINGS``
    The eighteen ComfyUI nodes (see :mod:`cinematographer.nodes`).
``geometry``, ``framing``, ``scene``, ``continuity``, ``character``,
``autoframe``, ``reliability``, ``elements``, ``post``, ``director``, ``prompt``
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
    CharacterContinuity as _CharacterContinuityNode,
    ChorosContinuity as _ChorosContinuityNode,
    CinemaCameraMove as _CinemaCameraMoveNode,
    CinemaDirectorPanel as _CinemaDirectorPanelNode,
    CinemaEdit as _CinemaEditNode,
    CinemaElementList as _CinemaElementListNode,
    CinemaElementLoad as _CinemaElementLoadNode,
    CinemaElementSave as _CinemaElementSaveNode,
    CinemaEmotionWheel as _CinemaEmotionWheelNode,
    CinemaExtend as _CinemaExtendNode,
    CinemaGrade as _CinemaGradeNode,
    CinemaGradeApply as _CinemaGradeApplyNode,
    CinemaPromptCompose as _CinemaPromptComposeNode,
    CinematographerAutoFrame as _CinematographerAutoFrameNode,
    CinematographerCorrection as _CinematographerCorrectionNode,
    CinematographerEvaluate as _CinematographerEvaluateNode,
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    SceneFramingExtras as _SceneFramingExtrasNode,
)

#: The node classes, re-exported by their ComfyUI class names.
CinematographerEvaluate = _CinematographerEvaluateNode
CinematographerAutoFrame = _CinematographerAutoFrameNode
ChorosContinuity = _ChorosContinuityNode
CharacterContinuity = _CharacterContinuityNode
SceneFramingExtras = _SceneFramingExtrasNode
CameraReliabilityZone = _CameraReliabilityZoneNode
CinematographerCorrection = _CinematographerCorrectionNode
CinemaElementSave = _CinemaElementSaveNode
CinemaElementLoad = _CinemaElementLoadNode
CinemaElementList = _CinemaElementListNode
CinemaDirectorPanel = _CinemaDirectorPanelNode
CinemaCameraMove = _CinemaCameraMoveNode
CinemaEmotionWheel = _CinemaEmotionWheelNode
CinemaPromptCompose = _CinemaPromptComposeNode
CinemaGrade = _CinemaGradeNode
CinemaGradeApply = _CinemaGradeApplyNode
CinemaExtend = _CinemaExtendNode
CinemaEdit = _CinemaEditNode

# --------------------------------------------------------------------------
# Safe re-export of the engine API.
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
    # character
    "CharacterAppearance": ("character", "CharacterAppearance"),
    "CharacterDrift": ("character", "CharacterDrift"),
    "CharacterContinuityReport": ("character", "CharacterContinuityReport"),
    "evaluate_character_continuity": ("character", "evaluate_character_continuity"),
    "EvaluateCharacterContinuity": ("character", "evaluate_character_continuity"),
    "character_continuity_summary": ("character", "character_continuity_summary"),
    "palette_distance": ("character", "palette_distance"),
    "proportion_delta": ("character", "proportion_delta"),
    "framing_delta": ("character", "framing_delta"),
    "CHARACTER_RULES": ("character", "CHARACTER_RULES"),
    "INFORMATIONAL_CHARACTER_RULES": ("character", "INFORMATIONAL_CHARACTER_RULES"),
    "PALETTE_DRIFT_MAX": ("character", "PALETTE_DRIFT_MAX"),
    "PROPORTION_DRIFT_MAX": ("character", "PROPORTION_DRIFT_MAX"),
    "FRAMING_DRIFT_MAX": ("character", "FRAMING_DRIFT_MAX"),
    # NOTE: the CamelCase alias "CharacterContinuity" is deliberately NOT exported
    # here -- the spec uses that name for both the engine module and the ComfyUI
    # node, and the node class wins at package level. Reach the engine function as
    # character.evaluate_character_continuity or evaluate_character_continuity.
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
    # elements -- the @Name registry that makes the stages a pipeline
    "ELEMENT_CATEGORIES": ("elements", "ELEMENT_CATEGORIES"),
    "ELEMENT_RULES": ("elements", "ELEMENT_RULES"),
    "ELEMENT_RULE_WEIGHTS": ("elements", "ELEMENT_RULE_WEIGHTS"),
    "ELEMENT_SIDECAR_SUFFIX": ("elements", "ELEMENT_SIDECAR_SUFFIX"),
    "Element": ("elements", "Element"),
    "ElementRegistry": ("elements", "ElementRegistry"),
    "ElementResolution": ("elements", "ElementResolution"),
    "parse_element_tags": ("elements", "parse_element_tags"),
    "resolve_elements": ("elements", "resolve_elements"),
    "element_summary": ("elements", "element_summary"),
    "character_record_from_element": ("elements", "character_record_from_element"),
    "audit_element": ("elements", "audit_element"),
    "audit_summary": ("elements", "audit_summary"),
    "sidecar_path": ("elements", "sidecar_path"),
    # post -- grade / extend / edit, as plans rather than pixels
    "GRADE_PARAMS": ("post", "GRADE_PARAMS"),
    "GRADE_NEUTRAL": ("post", "GRADE_NEUTRAL"),
    "GRADE_RANGES": ("post", "GRADE_RANGES"),
    "grade_range": ("post", "grade_range"),
    "GradeSettings": ("post", "GradeSettings"),
    "GradePlan": ("post", "GradePlan"),
    "apply_grade": ("post", "apply_grade"),
    "EXTEND_MODES": ("post", "EXTEND_MODES"),
    "EXTEND_DURATION_RANGE": ("post", "EXTEND_DURATION_RANGE"),
    "EXTEND_OVERLAP_MAX_FRAMES": ("post", "EXTEND_OVERLAP_MAX_FRAMES"),
    "DEFAULT_FPS": ("post", "DEFAULT_FPS"),
    "DEFAULT_EXTEND_DURATION_S": ("post", "DEFAULT_EXTEND_DURATION_S"),
    "ExtendPlan": ("post", "ExtendPlan"),
    "EditRegion": ("post", "EditRegion"),
    "EditPlan": ("post", "EditPlan"),
    "POST_STAGES": ("post", "POST_STAGES"),
    "POST_RULES": ("post", "POST_RULES"),
    "POST_RULE_WEIGHTS": ("post", "POST_RULE_WEIGHTS"),
    "PostPlan": ("post", "PostPlan"),
    "post_summary": ("post", "post_summary"),
    # director -- the Stage 3 panel, as data rather than a widget
    "GENRES": ("director", "GENRES"),
    "ERAS": ("director", "ERAS"),
    "TEMPOS": ("director", "TEMPOS"),
    "CAMERA_BODIES": ("director", "CAMERA_BODIES"),
    "LENSES": ("director", "LENSES"),
    "APERTURES": ("director", "APERTURES"),
    "LIGHTING_LOOKS": ("director", "LIGHTING_LOOKS"),
    "COLOUR_PALETTES": ("director", "COLOUR_PALETTES"),
    "COLOUR_PALETTES_TOTAL": ("director", "COLOUR_PALETTES_TOTAL"),
    "EMOTIONS": ("director", "EMOTIONS"),
    "EMOTION_INTENSITY_MIN": ("director", "EMOTION_INTENSITY_MIN"),
    "EMOTION_INTENSITY_MAX": ("director", "EMOTION_INTENSITY_MAX"),
    "PANEL_FIELDS": ("director", "PANEL_FIELDS"),
    "FilmSetup": ("director", "FilmSetup"),
    "CameraSetup": ("director", "CameraSetup"),
    "LightingSetup": ("director", "LightingSetup"),
    "PaletteSetup": ("director", "PaletteSetup"),
    "EmotionDirection": ("director", "EmotionDirection"),
    "DirectorPanel": ("director", "DirectorPanel"),
    "panel_prompt_fragment": ("director", "panel_prompt_fragment"),
    "panel_conditioning": ("director", "panel_conditioning"),
    "panel_summary": ("director", "panel_summary"),
    # prompt -- the Stage 4 assembly, and the #camera-move tags
    "CAMERA_MOVES": ("prompt", "CAMERA_MOVES"),
    "CAMERA_MOVES_TOTAL": ("prompt", "CAMERA_MOVES_TOTAL"),
    "MOVE_TAG_PREFIX": ("prompt", "MOVE_TAG_PREFIX"),
    "API_REFERENCE_TOKEN": ("prompt", "API_REFERENCE_TOKEN"),
    "parse_move_tags": ("prompt", "parse_move_tags"),
    "resolve_move_tags": ("prompt", "resolve_move_tags"),
    "move_summary": ("prompt", "move_summary"),
    "MoveResolution": ("prompt", "MoveResolution"),
    "MoveStack": ("prompt", "MoveStack"),
    "ComposedPrompt": ("prompt", "ComposedPrompt"),
    "compose_prompt": ("prompt", "compose_prompt"),
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
    "CharacterContinuity",
    "SceneFramingExtras",
    "CameraReliabilityZone",
    "CinematographerCorrection",
    *_ENGINE_MODULES,
    *_ENGINE_EXPORTS.keys(),
]
