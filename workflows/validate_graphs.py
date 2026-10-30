#!/usr/bin/env python3
"""Structural validator for the ComfyUI-Cinematographer re-shoot graphs.

Run it from anywhere:

    python3 workflows/validate_graphs.py

It checks only what can be checked without ComfyUI, and it is deliberately
honest about the boundary:

  CHECKED       the file parses as JSON; ``_README`` is a list of strings; every
                node has ``class_type`` and ``inputs``; every ``class_type`` is in
                the verified slot table below; every link resolves to an
                existing node id and an output slot that node actually declares;
                every node passes the declared input-count bounds for its
                class_type; the graph is acyclic; every node is reachable from an
                output node (a SaveVideo, or any node that declares no outputs).

  NOT CHECKED   that ComfyUI accepts the prompt, that the node packs and weights
                are installed, that the graph runs, or that it produces a clip.
                None of the graphs have ever been executed. Do not read a pass
                here as "the workflow works".

The two tables below are the load-bearing part. Every count was read from the
node source named in each graph's own ``_README`` PROVENANCE block, not guessed.
If a node pack changes its slots, this validator is what will notice.

One exception, and it is printed rather than hidden. ``cinema_studio_full.json``
wires ten class_types that do not exist in the tree yet -- they are being written
in parallel by other people. Their counts are DECLARED, not read, and they are
listed in ``UNVERIFIED_SLOTS``. When any graph uses one, ``main`` prints a NOTE
naming it, so a PASS that leans on a declared count can never be mistaken for a
PASS that does not. Delete a name from that set the moment its node lands and its
counts have been read from the source that defines it.

``OUTPUT_SLOTS`` is exact: a link may only read a slot the node declares.
``INPUT_SLOTS`` is a ``(required, total)`` pair, because API-format prompts may
omit optional inputs but may never omit a required one and may never invent a
name. ``total`` counts every declared input except ``hidden`` ones, which
ComfyUI injects and which therefore never appear in an API prompt.

Exit code 0 = every check passed. Exit code 1 = at least one failure, printed.
"""

from __future__ import annotations

import json
import os
import sys

#: class_type -> number of output slots, read from the node sources.
OUTPUT_SLOTS = {
    # ComfyUI core -- comfy_extras/nodes_video.py
    "LoadVideo": 1,
    "GetVideoComponents": 5,  # images, audio, fps, bit_depth, color_space
    "CreateVideo": 1,
    "SaveVideo": 1,
    # ComfyUI core -- nodes.py
    "LoadImage": 2,  # IMAGE, MASK
    "SaveImage": 1,  # images (OUTPUT_NODE = True)
    "ImageScale": 1,
    "UNETLoader": 1,
    "CLIPLoader": 1,
    "VAELoader": 1,
    "DualCLIPLoader": 1,
    "LoraLoaderModelOnly": 1,
    "CLIPTextEncode": 1,
    "ModelSamplingSD3": 1,
    "KSampler": 1,
    "KSamplerAdvanced": 1,
    "VAEDecode": 1,
    "VAEDecodeTiled": 1,
    # ComfyUI core -- comfy_extras/nodes_images.py
    "ImageFromBatch": 1,
    # ComfyUI core -- comfy_extras/nodes_moge.py
    "LoadMoGeModel": 1,
    "MoGeInference": 1,
    # ComfyUI core -- comfy_extras/nodes_lt.py
    "EmptyLTXVLatentVideo": 1,
    "LTXVConditioning": 2,  # positive, negative
    "LTXVCropGuides": 3,  # positive, negative, latent
    "LTXVConcatAVLatent": 1,
    "LTXVSeparateAVLatent": 2,  # video_latent, audio_latent
    "LTXVPreprocess": 1,
    "LTXVImgToVideoInplace": 1,
    # ComfyUI core -- comfy_extras/nodes_lt_audio.py
    "LTXVEmptyLatentAudio": 1,
    "LTXVAudioVAEDecode": 1,
    # ComfyUI core -- comfy_extras/nodes_lt_upsampler.py
    "LTXVLatentUpsampler": 1,
    # ComfyUI core -- comfy_extras/nodes_hunyuan.py
    "LatentUpscaleModelLoader": 1,
    # ComfyUI core -- comfy_extras/nodes_custom_sampler.py
    "CFGGuider": 1,
    "KSamplerSelect": 1,
    "ManualSigmas": 1,
    "RandomNoise": 1,
    "SamplerCustomAdvanced": 2,  # output, denoised_output
    # ComfyUI core -- comfy_extras/nodes_wan.py
    "Wan22FunControlToVideo": 3,  # positive, negative, latent
    # ComfyUI core -- comfy_extras/nodes_primitive.py
    "PrimitiveStringMultiline": 1,
    # ComfyUI core -- comfy_extras/nodes_preview_any.py  (OUTPUT_NODE = True)
    "PreviewAny": 1,
    # ComfyUI core -- comfy_extras/nodes_flux.py
    "CLIPTextEncodeFlux": 1,
    # ComfyUI core -- comfy_extras/nodes_sd3.py
    "EmptySD3LatentImage": 1,
    # ComfyUI core -- nodes.py (ConditioningZeroOut)
    "ConditioningZeroOut": 1,
    # This pack -- app/cinematographer/nodes.py, read directly.
    "CinematographerEvaluate": 3,  # report_json, overall_pass, summary
    "CinematographerAutoFrame": 4,  # camera_json, report_json, converged, iterations
    "ChorosContinuity": 3,  # issues_json, all_pass, summary
    "CharacterContinuity": 3,  # report_json, overall_pass, summary
    "SceneFramingExtras": 2,  # scores_json, summary
    "CameraReliabilityZone": 2,  # zone, reason
    "CinematographerCorrection": 1,  # corrections
    # This pack -- DECLARED, NOT READ. These class_types do not exist in the tree
    # yet; see UNVERIFIED_SLOTS below and the NOTE printed by main().
    "CinemaDirectorPanel": 3,  # panel_json, prompt_fragment, summary
    "CinemaCameraMove": 4,  # clean_prompt, moves, unknown, ok
    "CinemaEmotionWheel": 3,  # direction_json, fragment, summary
    "CinemaPromptCompose": 4,  # final_prompt, attachments_json, unresolved_json, ok
    # This pack -- READ FROM SOURCE, app/cinematographer/nodes.py (read 2026-10-29).
    # Every one of these is stdlib-only and touches no pixels: no IMAGE input and
    # no IMAGE output anywhere in the set.
    "CinemaElementSave": 3,  # element_json, sidecar_path, summary
    "CinemaElementLoad": 3,  # asset_path, element_json, found
    "CinemaElementList": 3,  # names_json, count, summary
    "CinemaGrade": 3,  # grade_json, is_neutral, summary
    "CinemaGradeApply": 2,  # image, summary
    "CinemaExtend": 3,  # extend_json, overlap_s, summary
    "CinemaEdit": 3,  # edit_json, in_frame, summary
    # ComfyUI core -- comfy_extras/nodes_dataset.py  (category model/training)
    "LoadImageDataSetFromFolder": 1,
    "MakeTrainingDataset": 2,  # latents, conditioning
    "LoadTrainingDataset": 2,  # latents, conditioning
    "SaveTrainingDataset": 0,  # output node
    "ResolutionBucket": 2,  # latents, conditioning
    # ComfyUI core -- comfy_extras/nodes_train.py  (category model/training)
    "TrainLoraNode": 3,  # lora, loss_map, steps
    "SaveLoRA": 0,  # output node
    "LossGraphNode": 0,  # output node
    "LoraModelLoader": 1,
    # Lightricks ComfyUI-LTXVideo -- iclora.py
    "LTXICLoRALoaderModelOnly": 2,  # model, latent_downscale_factor
    "LTXAddVideoICLoRAGuide": 3,  # positive, negative, latent
    # Cseti ComfyUI-CrossViewWarp -- crossview_warp_node.py
    "CrossViewWarp": 2,  # warp, orbit_view
}

#: class_type -> (required inputs, all declared inputs except hidden ones).
#: Read from the same sources as OUTPUT_SLOTS. A node in an API prompt must
#: supply at least ``required`` and at most ``total`` inputs.
INPUT_SLOTS = {
    # comfy_extras/nodes_video.py
    "LoadVideo": (1, 1),
    "GetVideoComponents": (1, 1),
    "CreateVideo": (2, 6),  # images, fps | + audio, bit_depth, color_space, codec
    "SaveVideo": (3, 4),  # video, filename_prefix, format | + hidden codec slot
    # nodes.py
    "LoadImage": (1, 1),
    "SaveImage": (2, 2),  # images, filename_prefix
    "ImageScale": (5, 5),
    "UNETLoader": (2, 2),
    "CLIPLoader": (2, 3),  # clip_name, type | + device
    "VAELoader": (1, 1),
    "DualCLIPLoader": (3, 4),  # clip_name1, clip_name2, type | + device
    "LoraLoaderModelOnly": (3, 3),
    "CLIPTextEncode": (2, 2),
    "ModelSamplingSD3": (2, 2),
    "KSampler": (10, 10),  # model, seed, steps, cfg, sampler_name, scheduler,
                           # positive, negative, latent_image, denoise
    "KSamplerAdvanced": (13, 13),
    "VAEDecode": (2, 2),
    "VAEDecodeTiled": (6, 6),
    # comfy_extras/nodes_images.py
    "ImageFromBatch": (3, 3),
    # comfy_extras/nodes_moge.py
    "LoadMoGeModel": (1, 1),
    "MoGeInference": (8, 8),
    # comfy_extras/nodes_lt.py
    "EmptyLTXVLatentVideo": (4, 4),
    "LTXVConditioning": (3, 3),
    "LTXVCropGuides": (3, 3),
    "LTXVConcatAVLatent": (2, 2),
    "LTXVSeparateAVLatent": (1, 1),
    "LTXVPreprocess": (2, 2),
    "LTXVImgToVideoInplace": (5, 5),
    # comfy_extras/nodes_lt_audio.py
    "LTXVEmptyLatentAudio": (4, 4),
    "LTXVAudioVAEDecode": (2, 2),
    # comfy_extras/nodes_lt_upsampler.py
    "LTXVLatentUpsampler": (3, 3),
    # comfy_extras/nodes_hunyuan.py
    "LatentUpscaleModelLoader": (1, 1),
    # comfy_extras/nodes_custom_sampler.py
    "CFGGuider": (4, 4),
    "KSamplerSelect": (1, 1),
    "ManualSigmas": (1, 1),
    "RandomNoise": (1, 1),
    "SamplerCustomAdvanced": (5, 5),
    # comfy_extras/nodes_wan.py
    "Wan22FunControlToVideo": (7, 9),  # + ref_image, control_video
    # comfy_extras/nodes_primitive.py
    "PrimitiveStringMultiline": (1, 1),
    # comfy_extras/nodes_preview_any.py
    "PreviewAny": (1, 1),
    # comfy_extras/nodes_flux.py
    "CLIPTextEncodeFlux": (4, 4),  # clip, clip_l, t5xxl, guidance
    # comfy_extras/nodes_sd3.py
    "EmptySD3LatentImage": (3, 3),  # width, height, batch_size
    # nodes.py
    "ConditioningZeroOut": (1, 1),
    # This pack -- app/cinematographer/nodes.py, read directly.
    "CinematographerEvaluate": (3, 4),  # subject_json, camera_json, shot_type | + intent_json
    "CinematographerAutoFrame": (2, 3),  # subject_json, shot_type | + intent_json
    "ChorosContinuity": (1, 1),
    "CharacterContinuity": (1, 1),
    "SceneFramingExtras": (3, 3),
    "CameraReliabilityZone": (4, 4),
    "CinematographerCorrection": (1, 1),
    # This pack -- DECLARED, NOT READ. See UNVERIFIED_SLOTS.
    "CinemaDirectorPanel": (8, 12),  # genre, era, pacing, camera_model, camera_lens,
    #   camera_aperture, light, color_palette | + custom_palette, emotion_character,
    #   emotion, emotion_intensity
    "CinemaCameraMove": (1, 2),  # prompt | + move
    "CinemaEmotionWheel": (3, 3),  # character, emotion, intensity
    "CinemaPromptCompose": (1, 4),  # action | + panel_json, registry_path, moves
    # This pack -- READ FROM SOURCE, app/cinematographer/nodes.py (read 2026-10-29).
    "CinemaElementSave": (3, 6),  # name, category, image_path | + description, seed, registry_path
    "CinemaElementLoad": (2, 3),  # name, category | + registry_path
    "CinemaElementList": (1, 2),  # category | + registry_path
    "CinemaGrade": (7, 8),  # the seven GRADE_PARAMS floats | + corrections (the judge gate)
    "CinemaGradeApply": (3, 3),  # image, grade_json, seed
    "CinemaExtend": (3, 3),  # mode, duration_s, overlap_frames
    "CinemaEdit": (6, 6),  # label, bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y, prompt
    # comfy_extras/nodes_dataset.py
    "LoadImageDataSetFromFolder": (1, 1),
    "MakeTrainingDataset": (3, 4),  # images, vae, clip | + texts
    "LoadTrainingDataset": (1, 1),
    "SaveTrainingDataset": (4, 4),
    "ResolutionBucket": (2, 2),
    # comfy_extras/nodes_train.py
    "TrainLoraNode": (21, 21),
    "SaveLoRA": (2, 3),  # lora, prefix | + steps
    "LossGraphNode": (2, 2),
    "LoraModelLoader": (4, 4),
    # Lightricks ComfyUI-LTXVideo -- iclora.py
    "LTXICLoRALoaderModelOnly": (3, 3),
    "LTXAddVideoICLoRAGuide": (12, 14),  # + use_streaming, tile_frames
    # Cseti ComfyUI-CrossViewWarp -- crossview_warp_node.py
    # 9 required + 16 optional; ``hidden`` unique_id is injected, not supplied.
    "CrossViewWarp": (9, 25),
}

#: Input NAMES, not counts. ``class_type -> (required, optional)``. Read from the
#: source that defines each node -- ``INPUT_TYPES`` for the old-style nodes and
#: ``define_schema`` / ``io.Schema(inputs=[...])`` for the schema-API ones, keyed on
#: ``node_id`` where the mapping name differs from the class name (e.g.
#: ``PrimitiveStringMultiline`` is ``StringMultiline``).
#:
#: Counts alone were the hole this closes: a node wired with the right NUMBER of
#: wrongly-NAMED inputs used to pass. Three shapes had to be handled before the
#: extraction was trustworthy, and each was invisible until the check ran:
#:   * ``id="name"`` instead of a positional name (LTXVPreprocess.img_compression);
#:   * a wrapper, ``io.MultiType.Input(io.Float.Input("frame_rate"), [io.Int])``;
#:   * a helper that returns the input, ``_save_video_codec_input(...)`` (SaveVideo.codec).
#: Every name below was extracted mechanically, not typed.
#:
#: Only the class_types these six graphs use are listed; a class_type absent here is
#: not name-checked, and ``main`` says so.
INPUT_NAMES = {
    'CFGGuider': (
        ('model', 'positive', 'negative', 'cfg'),
        (),
    ),
    'CLIPLoader': (
        ('clip_name', 'type'),
        ('device',),
    ),
    'CLIPTextEncode': (
        ('text', 'clip'),
        (),
    ),
    'CLIPTextEncodeFlux': (
        ('clip', 'clip_l', 't5xxl', 'guidance'),
        (),
    ),
    'CameraReliabilityZone': (
        ('camera_json', 'subject_json', 'azimuth_deg', 'elevation_deg'),
        (),
    ),
    'CharacterContinuity': (
        ('shots_json',),
        (),
    ),
    'ChorosContinuity': (
        ('shots_json',),
        (),
    ),
    'CinemaCameraMove': (
        ('prompt',),
        ('move',),
    ),
    'CinemaDirectorPanel': (
        ('genre', 'era', 'pacing', 'camera_model', 'camera_lens', 'camera_aperture', 'light', 'color_palette'),
        ('custom_palette', 'emotion_character', 'emotion', 'emotion_intensity'),
    ),
    'CinemaEdit': (
        ('label', 'bbox_min_x', 'bbox_min_y', 'bbox_max_x', 'bbox_max_y', 'prompt'),
        (),
    ),
    'CinemaElementList': (
        ('category',),
        ('registry_path',),
    ),
    'CinemaElementLoad': (
        ('name', 'category'),
        ('registry_path',),
    ),
    'CinemaElementSave': (
        ('name', 'category', 'image_path'),
        ('description', 'seed', 'palette', 'has_bbox', 'bbox_min_x', 'bbox_min_y', 'bbox_max_x', 'bbox_max_y', 'registry_path'),
    ),
    'CinemaEmotionWheel': (
        ('character', 'emotion', 'intensity'),
        (),
    ),
    'CinemaExtend': (
        ('mode', 'duration_s', 'overlap_frames'),
        (),
    ),
    'CinemaGrade': (
        ('temperature', 'contrast', 'saturation', 'sharpness', 'film_grain', 'highlights', 'exposure'),
        ('corrections',),
    ),
    'CinemaGradeApply': (
        ('image', 'grade_json', 'seed'),
        (),
    ),
    'CinemaPromptCompose': (
        ('action',),
        ('panel_json', 'registry_path', 'moves'),
    ),
    'CinematographerAutoFrame': (
        ('subject_json', 'shot_type'),
        ('intent_json',),
    ),
    'CinematographerCorrection': (
        ('report_json',),
        (),
    ),
    'CinematographerEvaluate': (
        ('subject_json', 'camera_json', 'shot_type'),
        ('intent_json',),
    ),
    'ConditioningZeroOut': (
        ('conditioning',),
        (),
    ),
    'CreateVideo': (
        ('images', 'fps'),
        ('audio', 'bit_depth', 'color_space', 'codec'),
    ),
    'CrossViewWarp': (
        ('frames', 'azimuth', 'elevation', 'distance', 'hfov', 'vertical_shift', 'depth_ratio', 'smooth_depth', 'invert_depth'),
        ('roll_lock', 'pivot_override', 'pivot_x', 'pivot_y', 'pivot_z', 'use_keyframes', 'frame_count', 'keyframes', 'interp_motion', 'interpolation', 'keep_source_aim', 'depth', 'moge_geometry', 'camera_info', 'preview_size', 'frame_index'),
    ),
    'DualCLIPLoader': (
        ('clip_name1', 'clip_name2', 'type'),
        ('device',),
    ),
    'EmptyLTXVLatentVideo': (
        ('width', 'height', 'length', 'batch_size'),
        (),
    ),
    'EmptySD3LatentImage': (
        ('width', 'height', 'batch_size'),
        (),
    ),
    'GetVideoComponents': (
        ('video',),
        (),
    ),
    'ImageFromBatch': (
        ('image', 'batch_index', 'length'),
        (),
    ),
    'ImageScale': (
        ('image', 'upscale_method', 'width', 'height', 'crop'),
        (),
    ),
    'KSampler': (
        ('model', 'seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'positive', 'negative', 'latent_image', 'denoise'),
        (),
    ),
    'KSamplerAdvanced': (
        ('model', 'add_noise', 'noise_seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'positive', 'negative', 'latent_image', 'start_at_step', 'end_at_step', 'return_with_leftover_noise'),
        (),
    ),
    'KSamplerSelect': (
        ('sampler_name',),
        (),
    ),
    'LTXAddVideoICLoRAGuide': (
        ('positive', 'negative', 'vae', 'latent', 'image', 'frame_idx', 'strength', 'latent_downscale_factor', 'crop', 'use_tiled_encode', 'tile_size', 'tile_overlap'),
        ('use_streaming', 'tile_frames'),
    ),
    'LTXICLoRALoaderModelOnly': (
        ('model', 'lora_name', 'strength_model'),
        (),
    ),
    'LTXVAudioVAEDecode': (
        ('samples', 'audio_vae'),
        (),
    ),
    'LTXVConcatAVLatent': (
        ('video_latent', 'audio_latent'),
        (),
    ),
    'LTXVConditioning': (
        ('positive', 'negative', 'frame_rate'),
        (),
    ),
    'LTXVCropGuides': (
        ('positive', 'negative', 'latent'),
        (),
    ),
    'LTXVEmptyLatentAudio': (
        ('frames_number', 'frame_rate', 'batch_size', 'audio_vae'),
        (),
    ),
    'LTXVImgToVideoInplace': (
        ('vae', 'image', 'latent', 'strength', 'bypass'),
        (),
    ),
    'LTXVLatentUpsampler': (
        ('samples', 'upscale_model', 'vae'),
        (),
    ),
    'LTXVPreprocess': (
        ('image', 'img_compression'),
        (),
    ),
    'LTXVSeparateAVLatent': (
        ('av_latent',),
        (),
    ),
    'LatentUpscaleModelLoader': (
        ('model_name',),
        (),
    ),
    'LoadImage': (
        ('image',),
        (),
    ),
    'LoadImageDataSetFromFolder': (
        ('folder',),
        (),
    ),
    'LoadMoGeModel': (
        ('model_name',),
        (),
    ),
    'LoadVideo': (
        ('file',),
        (),
    ),
    'LoraLoaderModelOnly': (
        ('model', 'lora_name', 'strength_model'),
        (),
    ),
    'LossGraphNode': (
        ('loss', 'filename_prefix'),
        (),
    ),
    'MakeTrainingDataset': (
        ('images', 'vae', 'clip'),
        ('texts',),
    ),
    'ManualSigmas': (
        ('sigmas',),
        (),
    ),
    'MoGeInference': (
        ('moge_model', 'image', 'resolution_level', 'fov_x_degrees', 'batch_size', 'force_projection', 'apply_mask', 'refine_steps'),
        (),
    ),
    'ModelSamplingSD3': (
        ('model', 'shift'),
        (),
    ),
    'PreviewAny': (
        ('source',),
        (),
    ),
    'PrimitiveStringMultiline': (
        ('value',),
        (),
    ),
    'RandomNoise': (
        ('noise_seed',),
        (),
    ),
    'SamplerCustomAdvanced': (
        ('noise', 'guider', 'sampler', 'sigmas', 'latent_image'),
        (),
    ),
    'SaveImage': (
        ('images', 'filename_prefix'),
        (),
    ),
    'SaveLoRA': (
        ('lora', 'prefix'),
        ('steps',),
    ),
    'SaveVideo': (
        ('video', 'filename_prefix', 'format', 'codec'),
        (),
    ),
    'SceneFramingExtras': (
        ('scene_json', 'camera_json', 'key_subject_json'),
        (),
    ),
    'TrainLoraNode': (
        ('model', 'latents', 'positive', 'batch_size', 'grad_accumulation_steps', 'steps', 'learning_rate', 'rank', 'optimizer', 'loss_function', 'seed', 'training_dtype', 'lora_dtype', 'quantized_backward', 'algorithm', 'gradient_checkpointing', 'checkpoint_depth', 'offloading', 'existing_lora', 'bucket_mode', 'bypass_mode'),
        (),
    ),
    'UNETLoader': (
        ('unet_name', 'weight_dtype'),
        (),
    ),
    'VAEDecode': (
        ('samples', 'vae'),
        (),
    ),
    'VAEDecodeTiled': (
        ('samples', 'vae', 'tile_size', 'overlap', 'temporal_size', 'temporal_overlap'),
        (),
    ),
    'VAELoader': (
        ('vae_name',),
        (),
    ),
    'Wan22FunControlToVideo': (
        ('positive', 'negative', 'vae', 'width', 'height', 'length', 'batch_size'),
        ('ref_image', 'control_video'),
    ),
}

#: class_types whose slot counts above are DECLARED, not read from source, because
#: the node does not exist in the tree yet. A pass that involves these is a weaker
#: pass than one that does not, and ``main`` says so out loud rather than letting
#: the word PASS stand unqualified. Remove a name from this set the moment its
#: node lands and its counts have been read from the source that defines it.
UNVERIFIED_SLOTS = frozenset()  # empty: every class_type in these graphs now
# exists in the tree and its slot counts are read from the source that defines it.

#: Nodes that terminate a graph. Anything that declares no outputs is an output
#: node by construction; SaveVideo declares one (it passes the video through) but
#: is still a sink. PreviewAny is a core OUTPUT_NODE = True, so a diagnostic that
#: nothing else consumes still executes and still counts as a sink. A graph must
#: contain at least one of these, and every node in it must be reachable from one.
TERMINAL_TYPES = frozenset({
    "SaveVideo",
    "SaveImage",
    "SaveLoRA",
    "LossGraphNode",
    "SaveTrainingDataset",
    "PreviewAny",
})

#: Class types whose input names are asserted against the LIVE source at
#: validation time, not against the declared INPUT_NAMES table above.
#:
#: Why this exists. INPUT_NAMES is a *declared* table, and a declared table can go
#: stale exactly the way the old slot table did -- and it did. This file asserted
#: for three turns that CinemaGrade had no `corrections` input, because the table
#: was built from a read taken before `nodes` added it. The judge gate is the one
#: place the entry's central claim depends on, so for these nodes the check calls
#: cls.INPUT_TYPES() and compares against the running code. A stale table is then
#: reported as a FAIL rather than silently believed.
SOURCE_ASSERTED = frozenset({
    "CinemaGrade",
    "CinemaGradeApply",
    "CinematographerCorrection",
})


def _live_input_names(class_type: str):
    """Read (required_names, optional_names) from the node class itself.

    Returns None when the pack cannot be imported or the class is absent, so a
    missing checkout degrades to a reported problem rather than a false PASS.
    """
    import importlib
    import os
    import sys

    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        nodes = importlib.import_module("cinematographer.nodes")
    except Exception:
        return None
    cls = getattr(nodes, "NODE_CLASS_MAPPINGS", {}).get(class_type)
    if cls is None:
        return None
    try:
        info = cls.INPUT_TYPES()
    except Exception:
        return None
    return (
        tuple((info.get("required") or {}).keys()),
        tuple((info.get("optional") or {}).keys()),
    )


def check_source_asserted(path: str, nodes: dict) -> list[str]:
    """Assert SOURCE_ASSERTED nodes against cls.INPUT_TYPES(), and the table too."""
    problems: list[str] = []
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if class_type not in SOURCE_ASSERTED:
            continue
        live = _live_input_names(class_type)
        if live is None:
            problems.append(
                f"{path}: node {node_id} ({class_type}) is SOURCE_ASSERTED but its "
                "class could not be imported, so the live gate check did NOT run"
            )
            continue
        req, opt = live
        allowed = set(req) | set(opt)
        wired = set(node.get("inputs") or {})
        undeclared = sorted(wired - allowed)
        missing = sorted(set(req) - wired)
        if undeclared:
            problems.append(
                f"{path}: node {node_id} ({class_type}) wires {undeclared}, which the "
                "LIVE cls.INPUT_TYPES() does not declare"
            )
        if missing:
            problems.append(
                f"{path}: node {node_id} ({class_type}) is missing required {missing} "
                "per the LIVE cls.INPUT_TYPES()"
            )
        declared = INPUT_NAMES.get(class_type)
        if declared is not None:
            if tuple(declared[0]) != req:
                problems.append(
                    f"{path}: INPUT_NAMES[{class_type!r}] required "
                    f"{list(declared[0])} != LIVE {list(req)} -- THE TABLE IS STALE"
                )
            if tuple(declared[1]) != opt:
                problems.append(
                    f"{path}: INPUT_NAMES[{class_type!r}] optional "
                    f"{list(declared[1])} != LIVE {list(opt)} -- THE TABLE IS STALE"
                )
    return problems


#: Links the entry's central claim depends on: the judge's verdict must reach POST
#: as a DATA DEPENDENCY, not merely sit beside it in the same graph.
#:
#: Why this is separate from the name check. The name check proves a link is LEGAL.
#: It cannot prove the link is PRESENT -- `corrections` is optional, so deleting the
#: gate edge violates nothing and produced a clean PASS. A check that verifies
#: well-formedness is not a check that verifies the property being claimed. This was
#: found by deliberately breaking the graph and watching it still pass.
#:
#: Each entry is (producer class_type, consumer class_type, consumer input name).
#:
#: Scoping is by CONTENT, not by filename: an edge is asserted only when the graph
#: actually contains a node of the producer class_type. The five reshoot graphs are
#: independent single-purpose graphs with no judge in them, so the edge does not
#: apply and is not asserted -- but the decision is made by looking at the graph, not
#: at its name. Scoping by filename was the first attempt and it was a silent no-op
#: the moment the file was renamed, which is the same failure mode as an allowlisted
#: action with no handler.
REQUIRED_EDGES = (
    ("CinematographerCorrection", "CinemaGrade", "corrections"),
    ("CinemaGrade", "CinemaGradeApply", "grade_json"),
)


def check_required_edges(path: str, nodes: dict) -> list[str]:
    """Assert each REQUIRED_EDGES link exists, in graphs that contain its producer."""
    problems: list[str] = []
    present = {
        node.get("class_type")
        for node in nodes.values()
        if isinstance(node, dict)
    }
    for producer, consumer, input_name in REQUIRED_EDGES:
        if producer not in present:
            continue  # this graph does not make the claim; nothing to assert
        found = False
        for node in nodes.values():
            if not isinstance(node, dict) or node.get("class_type") != consumer:
                continue
            value = (node.get("inputs") or {}).get(input_name)
            if not _is_link(value):
                continue
            src = nodes.get(value[0])
            if isinstance(src, dict) and src.get("class_type") == producer:
                found = True
                break
        if not found:
            problems.append(
                f"{path}: REQUIRED EDGE MISSING -- this graph contains a {producer}, "
                f"but no {consumer}.{input_name} is wired from it. The entry claims the "
                "judge's verdict gates POST as a data dependency; without this link it "
                "does not."
            )
    return problems


GRAPHS = (
    "reshoot_ltx_crossview.json",
    "reshoot_ltx23_character.json",
    "reshoot_ltx25.json",
    "reshoot_wan22_fun_control.json",
    "character_lora_train.json",
    "cinema_studio_full.json",
)


def _is_link(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def _is_terminal(class_type: object) -> bool:
    if class_type in TERMINAL_TYPES:
        return True
    return OUTPUT_SLOTS.get(class_type) == 0


def validate(path: str) -> list[str]:
    """Return a list of failure strings; empty means the graph passed."""
    problems: list[str] = []

    try:
        with open(path, encoding="utf-8") as handle:
            graph = json.load(handle)
    except FileNotFoundError:
        return [f"{path}: file not found"]
    except ValueError as exc:
        return [f"{path}: not valid JSON: {exc}"]

    if not isinstance(graph, dict):
        return [f"{path}: top level must be a JSON object"]

    readme = graph.get("_README")
    if not isinstance(readme, list) or not all(isinstance(s, str) for s in readme):
        problems.append(f"{path}: _README must be an array of strings")

    nodes = {k: v for k, v in graph.items() if k != "_README"}
    if not nodes:
        return problems + [f"{path}: no nodes"]

    for nid, node in nodes.items():
        if not isinstance(node, dict):
            problems.append(f"{path}: node {nid} is not an object")
            continue
        if "class_type" not in node:
            problems.append(f"{path}: node {nid} has no class_type")
            continue
        if not isinstance(node.get("inputs"), dict):
            problems.append(f"{path}: node {nid} has no inputs object")
            continue
        class_type = node["class_type"]
        if class_type not in OUTPUT_SLOTS:
            problems.append(
                f"{path}: node {nid} class_type {class_type!r} is not in the "
                "verified output-slot table -- add it there only after reading the "
                "node source"
            )
        bounds = INPUT_SLOTS.get(class_type)
        if bounds is not None:
            required, total = bounds
            given = len(node["inputs"])
            if not required <= given <= total:
                problems.append(
                    f"{path}: node {nid} ({class_type}) supplies {given} input(s); "
                    f"the node declares {required} required and {total} in total"
                )

        # Names, not just counts. A count check passes a node wired with the right
        # NUMBER of wrongly-NAMED inputs, which is the failure this closes. Where the
        # name table has the class_type we can also check that every REQUIRED input is
        # actually present -- the count bound alone cannot tell a required input from
        # an optional one, so 3-of-5 could be the three optional ones.
        names = INPUT_NAMES.get(class_type)
        if names is not None:
            req_names, opt_names = names
            declared = set(req_names) | set(opt_names)
            supplied = set(node["inputs"])
            unknown = sorted(supplied - declared)
            if unknown:
                problems.append(
                    f"{path}: node {nid} ({class_type}) supplies input name(s) "
                    f"{unknown} that the node does not declare; declared names are "
                    f"{sorted(declared)}"
                )
            absent = sorted(set(req_names) - supplied)
            if absent:
                problems.append(
                    f"{path}: node {nid} ({class_type}) is missing required input(s) "
                    f"{absent}"
                )

    # The gate, asserted against the running code rather than against the table.
    problems.extend(check_source_asserted(path, nodes))
    problems.extend(check_required_edges(path, nodes))

    for nid, node in nodes.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        for name, value in node["inputs"].items():
            if not _is_link(value):
                continue
            src, slot = value
            if src not in nodes:
                problems.append(f"{path}: {nid}.{name} links to missing node {src}")
                continue
            src_type = nodes[src].get("class_type")
            count = OUTPUT_SLOTS.get(src_type)
            if count is None:
                continue  # already reported above
            if not 0 <= slot < count:
                problems.append(
                    f"{path}: {nid}.{name} reads slot {slot} of {src} ({src_type}), "
                    f"which declares {count} output(s) (0..{count - 1})"
                )

    # Acyclic, and every node reachable from an output node (no dead weight).
    deps = {
        nid: [v[0] for v in node["inputs"].values() if _is_link(v)]
        for nid, node in nodes.items()
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict)
    }

    state: dict[str, int] = {}

    def visit(nid: str, stack: list[str]) -> bool:
        if state.get(nid) == 1:
            problems.append(f"{path}: cycle {' -> '.join(stack + [nid])}")
            return False
        if state.get(nid) == 2:
            return True
        state[nid] = 1
        for dep in deps.get(nid, []):
            if not visit(dep, stack + [nid]):
                return False
        state[nid] = 2
        return True

    for nid in nodes:
        visit(nid, [])

    sinks = [n for n, node in nodes.items() if _is_terminal(node.get("class_type"))]
    if not sinks:
        problems.append(
            f"{path}: no output node (SaveVideo, or any node that declares no "
            "outputs) -- the graph produces nothing"
        )
    reachable: set[str] = set()
    frontier = list(sinks)
    while frontier:
        nid = frontier.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        frontier.extend(deps.get(nid, []))
    orphans = sorted(set(nodes) - reachable)
    if orphans:
        problems.append(
            f"{path}: {len(orphans)} node(s) unreachable from an output node: {orphans}"
        )

    return problems


def main(argv: list[str]) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    targets = argv[1:] or [os.path.join(here, name) for name in GRAPHS]

    failures = 0
    for target in targets:
        problems = validate(target)
        name = os.path.basename(target)
        if problems:
            failures += len(problems)
            print(f"FAIL  {name}")
            for problem in problems:
                print(f"        {problem}")
        else:
            with open(target, encoding="utf-8") as handle:
                graph = json.load(handle)
            count = len(graph) - 1
            links = sum(
                1
                for node in graph.values()
                if isinstance(node, dict)
                for value in node.get("inputs", {}).values()
                if _is_link(value)
            )
            print(f"PASS  {name}  ({count} nodes, {links} links)")

    if failures:
        print(f"\n{failures} problem(s). Structural checks only -- see the module docstring.")
        return 1

    used_declared: set[str] = set()
    for target in targets:
        try:
            with open(target, encoding="utf-8") as handle:
                graph = json.load(handle)
        except (OSError, ValueError):
            continue
        for node in graph.values():
            if isinstance(node, dict) and node.get("class_type") in UNVERIFIED_SLOTS:
                used_declared.add(node["class_type"])

    if used_declared:
        print(
            f"\nNOTE  {len(used_declared)} class_type(s) in these graphs have DECLARED "
            "slot counts, not source-read ones, because the node does not exist in the "
            "tree yet. A pass involving them is weaker than one that does not:"
        )
        for name in sorted(used_declared):
            print(f"        {name}")

    print(
        "\nAll structural checks passed. This does NOT mean the graphs run. "
        "cinema_studio_full.json has been executed through ComfyUI's engine as far as "
        "missing weights allow (25 of 94 nodes); the five reshoot_* and "
        "character_lora_train.json graphs have never been executed. See each _README."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
