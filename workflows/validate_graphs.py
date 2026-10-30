#!/usr/bin/env python3
"""Structural validator for the ComfyUI-Cinematographer re-shoot graphs.

Run it from anywhere:

    python3 workflows/validate_graphs.py

It checks only what can be checked without ComfyUI, and it is deliberately
honest about the boundary:

  CHECKED       the file parses as JSON; ``_README`` is a list of strings; every
                node has ``class_type`` and ``inputs``; every ``class_type`` is in
                the verified output-slot table below; every link resolves to an
                existing node id and an output slot that node actually declares;
                the graph is acyclic; every node is reachable from a SaveVideo.

  NOT CHECKED   that ComfyUI accepts the prompt, that the node packs and weights
                are installed, that the graph runs, or that it produces a clip.
                None of the graphs have ever been executed. Do not read a pass
                here as "the workflow works".

The output-slot table is the load-bearing part. Each count was read from the node
source named in the graph's own ``_README`` PROVENANCE block, not guessed. If a
node pack changes its outputs, this validator is what will notice.

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
    "ImageScale": 1,
    "UNETLoader": 1,
    "CLIPLoader": 1,
    "VAELoader": 1,
    "DualCLIPLoader": 1,
    "LoraLoaderModelOnly": 1,
    "CLIPTextEncode": 1,
    "ModelSamplingSD3": 1,
    "KSamplerAdvanced": 1,
    "VAEDecode": 1,
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
    # ComfyUI core -- comfy_extras/nodes_lt_audio.py
    "LTXVEmptyLatentAudio": 1,
    "LTXVAudioVAEDecode": 1,
    # ComfyUI core -- comfy_extras/nodes_custom_sampler.py
    "CFGGuider": 1,
    "KSamplerSelect": 1,
    "ManualSigmas": 1,
    "RandomNoise": 1,
    "SamplerCustomAdvanced": 2,  # output, denoised_output
    # ComfyUI core -- comfy_extras/nodes_wan.py
    "Wan22FunControlToVideo": 3,  # positive, negative, latent
    # Lightricks ComfyUI-LTXVideo -- iclora.py
    "LTXICLoRALoaderModelOnly": 2,  # model, latent_downscale_factor
    "LTXAddVideoICLoRAGuide": 3,  # positive, negative, latent
    # Cseti ComfyUI-CrossViewWarp -- crossview_warp_node.py
    "CrossViewWarp": 2,  # warp, orbit_view
}

GRAPHS = ("reshoot_ltx_crossview.json", "reshoot_wan22_fun_control.json")


def _is_link(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


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
        if node["class_type"] not in OUTPUT_SLOTS:
            problems.append(
                f"{path}: node {nid} class_type {node['class_type']!r} is not in the "
                "verified output-slot table -- add it there only after reading the "
                "node source"
            )

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

    # Acyclic, and every node reachable from a SaveVideo (no dead weight).
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

    saves = [n for n, node in nodes.items() if node.get("class_type") == "SaveVideo"]
    if not saves:
        problems.append(f"{path}: no SaveVideo node -- the graph produces nothing")
    reachable: set[str] = set()
    frontier = list(saves)
    while frontier:
        nid = frontier.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        frontier.extend(deps.get(nid, []))
    orphans = sorted(set(nodes) - reachable)
    if orphans:
        problems.append(
            f"{path}: {len(orphans)} node(s) unreachable from a SaveVideo: {orphans}"
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
    print(
        "\nAll structural checks passed. This does NOT mean the graphs run: they have "
        "never been executed. See each _README."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
