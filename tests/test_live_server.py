"""Drive the pack through a LIVE ComfyUI server's public HTTP API.

Why this file exists
--------------------
``test_comfy_execution.py`` proves the pack loads and executes by calling
ComfyUI's loader and ``PromptExecutor`` directly, in-process. That is a real
proof, but it is not how anyone actually runs a custom node pack. A user runs
``python main.py``, opens the browser, and the server receives ``POST /prompt``.

This module closes that last gap. It talks to a running server over HTTP only:
``GET /object_info`` to see what registered, ``POST /prompt`` to submit, and
``GET /history/<id>`` to read the result. Nothing is imported from ComfyUI.

How to run it
-------------
Start a server, then point the test at it::

    cd /path/to/ComfyUI
    python main.py --cpu --port 8188
    # in another shell:
    COMFYUI_URL=http://127.0.0.1:8188 python -m pytest tests/test_live_server.py -q

Without ``COMFYUI_URL`` every test here skips with a specific reason, so the
normal suite stays green on a machine with no server.

What it found
-------------
A live server rejects a prompt that contains only our judgement nodes::

    {"error": {"type": "prompt_no_outputs", "message": "Prompt has no outputs"}}

``CinemaElementSave`` is the pack's only ``OUTPUT_NODE``, and it is an output
node for its *side effect* (it writes an Element into the registry), not for
display -- it returns no image and no text. Every other node is pruned unless
something consumes it, so **a user must terminate a Cinematographer graph in a
stock output node** (``PreviewAny``, ``SaveImage``, ...). That is correct
ComfyUI behaviour and true of most packs, but it is worth stating plainly. The
graphs here do exactly that.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import pytest

OUR_NODES = (
    "CameraReliabilityZone",
    "CharacterContinuity",
    "ChorosContinuity",
    "CinemaCameraMove",
    "CinemaDirectorPanel",
    "CinemaEdit",
    "CinemaElementList",
    "CinemaElementLoad",
    "CinemaElementSave",
    "CinemaEmotionWheel",
    "CinemaExtend",
    "CinemaGrade",
    "CinemaGradeApply",
    "CinemaPromptCompose",
    "CinematographerAutoFrame",
    "CinematographerCorrection",
    "CinematographerEvaluate",
    "SceneFramingExtras",
)


def _base() -> str | None:
    return os.environ.get("COMFYUI_URL") or None


def _skip_reason() -> str | None:
    url = _base()
    if not url:
        return "COMFYUI_URL is not set; start ComfyUI and point this test at it"
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/system_stats", timeout=5):
            return None
    except Exception as exc:  # noqa: BLE001 - any failure means "not reachable"
        return f"no ComfyUI server answering at {url}: {type(exc).__name__}: {exc}"


pytestmark = pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")


def _get(path: str):
    with urllib.request.urlopen(_base().rstrip("/") + path, timeout=60) as r:
        return json.loads(r.read().decode())


def _post(path: str, payload: dict):
    req = urllib.request.Request(
        _base().rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _submit(prompt: dict) -> dict:
    """POST a prompt and wait for its history entry. Returns the entry."""
    res = _post("/prompt", {"prompt": prompt, "client_id": "pytest-live-server"})
    pid = res["prompt_id"]
    deadline = time.time() + 120
    while time.time() < deadline:
        hist = _get(f"/history/{pid}")
        if pid in hist:
            return hist[pid]
        time.sleep(0.5)
    raise AssertionError(f"prompt {pid} never appeared in /history within 120 s")


def _errors(entry: dict) -> list[dict]:
    return [
        m[1]
        for m in entry.get("status", {}).get("messages", [])
        if m[0] == "execution_error"
    ]


def _text_of(entry: dict, node_id: str) -> str:
    """Read a PreviewAny node's rendered text out of the history entry."""
    out = entry.get("outputs", {}).get(node_id)
    assert out is not None, f"node {node_id} produced no output: {entry.get('status')}"
    text = out.get("text")
    assert text, f"node {node_id} has no 'text' key: {list(out)}"
    return text[0] if isinstance(text, list) else text


# --------------------------------------------------------------------------
# What registered
# --------------------------------------------------------------------------
def test_all_eighteen_nodes_are_registered_on_the_live_server():
    info = _get("/object_info")
    assert len(info) > 100, "the server reported an implausibly small node set"
    missing = [n for n in OUR_NODES if n not in info]
    assert not missing, f"not registered on the live server: {missing}"
    for name in OUR_NODES:
        assert info[name]["category"] == "Cinematographer", (
            f"{name} is filed under {info[name]['category']!r}, not 'Cinematographer'"
        )


def test_the_only_output_node_is_the_one_that_writes_the_registry():
    """Documents the pruning trap that forces a stock terminal node.

    ``CinemaElementSave`` sets ``OUTPUT_NODE = True`` because it has a side
    effect -- it writes an Element into the registry -- and ComfyUI would
    otherwise prune it. It is not a *display* node: it returns no image and no
    text a user can look at. So a graph whose results a user wants to see still
    needs a stock terminal node (``PreviewAny``, ``SaveImage``, ...).

    If this ever fails, the pack gained or lost an output node; re-check the
    terminal nodes in ``workflows/`` before relaxing the assertion.
    """
    info = _get("/object_info")
    output_nodes = sorted(n for n in OUR_NODES if info[n].get("output_node"))
    assert output_nodes == ["CinemaElementSave"], (
        f"the pack's output nodes changed: {output_nodes}. "
        "Update this test and the workflows' terminal nodes."
    )


def test_a_prompt_of_only_our_nodes_is_rejected_for_having_no_outputs():
    """The measured consequence of the test above, asserted rather than assumed."""
    prompt = {
        "1": {
            "class_type": "CinematographerEvaluate",
            "inputs": {
                "subject_json": json.dumps({"name": "s", "base": [0, 0, 0], "height": 1.8}),
                "camera_json": json.dumps({"eye": [0, 1.66, 3], "target": [0, 1.66, 0], "focal_mm": 35}),
                "shot_type": "medium",
            },
        }
    }
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _post("/prompt", {"prompt": prompt, "client_id": "pytest-live-server"})
    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read().decode())
    assert body["error"]["type"] == "prompt_no_outputs", body


# --------------------------------------------------------------------------
# The gate, end to end, over HTTP
# --------------------------------------------------------------------------
def test_judge_to_post_gate_carries_corrections_through_a_live_server():
    """Evaluate -> Correction -> Grade, submitted to a real server.

    The assertion that matters is the last one: the correction text that the
    Judge measured arrives in the Grade node's JSON *verbatim*. That is the
    data dependency the whole entry rests on, proven over HTTP.
    """
    prompt = {
        "1": {
            "class_type": "CinematographerEvaluate",
            "inputs": {
                "subject_json": json.dumps(
                    {"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8,
                     "facing_yaw_deg": 0.0}
                ),
                "camera_json": json.dumps(
                    {"eye": [0.0, 1.66, 3.0], "target": [0.0, 1.66, 0.0],
                     "focal_mm": 35.0}
                ),
                "shot_type": "medium",
            },
        },
        "2": {"class_type": "CinematographerCorrection", "inputs": {"report_json": ["1", 0]}},
        "3": {
            "class_type": "CinemaGrade",
            "inputs": {
                "temperature": 0.0, "contrast": 0.0, "saturation": 0.0,
                "sharpness": 0.0, "film_grain": 0.0, "highlights": 0.0,
                "exposure": 0.0,
                "corrections": ["2", 0],
            },
        },
        # A live server needs a terminal output node; see the module docstring.
        "4": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}},
        "5": {"class_type": "PreviewAny", "inputs": {"source": ["2", 0]}},
        "6": {"class_type": "PreviewAny", "inputs": {"source": ["3", 0]}},
    }
    entry = _submit(prompt)
    assert entry["status"]["status_str"] == "success", _errors(entry)
    assert not _errors(entry)

    report = json.loads(_text_of(entry, "4"))
    corrections = _text_of(entry, "5")
    grade = json.loads(_text_of(entry, "6"))

    # The report is the measured shape: a list of per-rule entries.
    assert isinstance(report["scores"], list) and report["scores"]
    headroom = next(s for s in report["scores"] if s["rule"] == "headroom")
    assert headroom["pass"] is False, "this pose is chosen to fail headroom"
    assert headroom["value"] > 0.45, "the measured headroom must exceed the medium band"
    assert "lower the camera target or push in" in headroom["correction"]

    assert "headroom:" in corrections
    # The gate: the text the Judge produced is the text the Grade received.
    assert grade["corrections"] == corrections, (
        "the correction text was altered in transit through the live server"
    )


def test_direct_to_shoot_composes_a_prompt_through_a_live_server():
    prompt = {
        "1": {
            "class_type": "CinemaDirectorPanel",
            "inputs": {
                "genre": "noir", "era": "1980s", "pacing": "calm",
                "camera_model": "35mm-film", "camera_lens": "anamorphic",
                "camera_aperture": "f4-moderate", "light": "practicals",
                "color_palette": "static-noon",
            },
        },
        "2": {
            "class_type": "CinemaPromptCompose",
            "inputs": {
                "action": "a detective walks into the rain #dolly-in",
                "panel_json": ["1", 0],
            },
        },
        "3": {"class_type": "PreviewAny", "inputs": {"source": ["2", 0]}},
        "4": {"class_type": "PreviewAny", "inputs": {"source": ["2", 2]}},
    }
    entry = _submit(prompt)
    assert entry["status"]["status_str"] == "success", _errors(entry)

    final_prompt = _text_of(entry, "3")
    unresolved = json.loads(_text_of(entry, "4"))

    assert "noir" in final_prompt, final_prompt
    assert "anamorphic" in final_prompt, final_prompt
    assert "#dolly-in" in final_prompt, final_prompt
    assert unresolved == [], f"the composer left tags unresolved: {unresolved}"


def test_a_bad_input_is_reported_as_our_error_not_a_silent_pass():
    """The pack must fail loudly and name itself when it fails."""
    prompt = {
        "1": {
            "class_type": "CinematographerEvaluate",
            "inputs": {"subject_json": "{not json", "camera_json": "{}",
                       "shot_type": "medium"},
        },
        "2": {"class_type": "PreviewAny", "inputs": {"source": ["1", 0]}},
    }
    entry = _submit(prompt)
    assert entry["status"]["status_str"] == "error"
    assert entry["status"]["completed"] is False
    errs = _errors(entry)
    assert errs, "an error status must carry an execution_error message"
    assert errs[0]["node_type"] == "CinematographerEvaluate"
    assert "ComfyUI-Cinematographer" in errs[0]["exception_message"], (
        "the error must name the pack so a user knows whose node failed"
    )


# --------------------------------------------------------------------------
# What the shipped graphs would need installed
# --------------------------------------------------------------------------
# Class types the shipped graphs use that live in a third-party pack this repo
# does not vendor. Measured against a live server: three graphs reference
# CrossViewWarp, and two of those also the two LTX IC-LoRA helpers. The README
# names the pack (`cseti007/ComfyUI-CrossViewWarp`) in its graph table.
EXTERNAL_CLASS_TYPES = {
    "CrossViewWarp",
    "LTXAddVideoICLoRAGuide",
    "LTXICLoRALoaderModelOnly",
}


def _graphs():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wf = os.path.join(root, "workflows")
    out = {}
    for name in sorted(os.listdir(wf)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(wf, name)) as fh:
            g = json.load(fh)
        out[name] = {k: v for k, v in g.items() if k != "_README"}
    return out


def test_every_graph_class_type_is_registered_or_a_documented_external():
    """A graph must not silently depend on a pack nobody was told to install.

    If a future edit adds a node from an uninstalled pack, this fails and names
    it, instead of shipping a graph that dies with ``missing_node_type`` the
    first time a user loads it.
    """
    info = _get("/object_info")
    problems = []
    for name, nodes in _graphs().items():
        for nid, node in nodes.items():
            ct = node["class_type"]
            if ct in info or ct in EXTERNAL_CLASS_TYPES:
                continue
            problems.append(f"{name} node {nid}: {ct}")
    assert not problems, (
        "these graphs reference class types that are neither registered on the "
        "server nor listed in EXTERNAL_CLASS_TYPES: " + "; ".join(problems)
    )


def test_the_entry_graph_needs_no_extra_packs():
    """`cinema_studio_full.json` is the entry; it must run on a bare install."""
    info = _get("/object_info")
    nodes = _graphs()["cinema_studio_full.json"]
    external = sorted(
        {n["class_type"] for n in nodes.values()
         if n["class_type"] not in info and n["class_type"] in EXTERNAL_CLASS_TYPES}
    )
    assert external == [], (
        f"the entry graph now needs third-party packs: {external}. "
        "The README claims it needs none."
    )


def test_the_autoframe_loop_closes_through_a_live_server():
    """Judge fails -> AutoFrame solves -> the solver's own pose passes the Judge.

    This is the load-bearing claim of the entry: the camera move is *verifiable*,
    not merely asserted. The previous test proves the Judge's text survives the
    trip to the next node; this one proves the loop actually closes -- that the
    pose AutoFrame hands back is scored by the same Judge, in the same server,
    and comes out passing.

    The pose below is deliberately the one the Judge fails (see the headroom
    assertion in the previous test). AutoFrame must move it to a pose that
    passes, and it must say how many iterations that took.
    """
    subject = json.dumps(
        {"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8,
         "facing_yaw_deg": 0.0}
    )
    failing_camera = json.dumps(
        {"eye": [0.0, 1.66, 3.0], "target": [0.0, 1.66, 0.0], "focal_mm": 35.0}
    )

    prompt = {
        # 1: the Judge scores the authored pose. It must fail.
        "1": {
            "class_type": "CinematographerEvaluate",
            "inputs": {
                "subject_json": subject,
                "camera_json": failing_camera,
                "shot_type": "medium",
            },
        },
        # 2: the solver proposes a pose from the subject alone.
        "2": {
            "class_type": "CinematographerAutoFrame",
            "inputs": {"subject_json": subject, "shot_type": "medium"},
        },
        # 3: the Judge scores the solver's pose. It must pass.
        "3": {
            "class_type": "CinematographerEvaluate",
            "inputs": {
                "subject_json": subject,
                "camera_json": ["2", 0],
                "shot_type": "medium",
            },
        },
        # A live server needs a terminal output node; see the module docstring.
        "4": {"class_type": "PreviewAny", "inputs": {"source": ["1", 1]}},
        "5": {"class_type": "PreviewAny", "inputs": {"source": ["2", 2]}},
        "6": {"class_type": "PreviewAny", "inputs": {"source": ["2", 3]}},
        "7": {"class_type": "PreviewAny", "inputs": {"source": ["3", 1]}},
        "8": {"class_type": "PreviewAny", "inputs": {"source": ["3", 2]}},
    }
    entry = _submit(prompt)
    assert entry["status"]["status_str"] == "success", _errors(entry)
    assert not _errors(entry)

    # The authored pose fails, so the loop has something to close.
    assert _text_of(entry, "4") == "False", (
        "the authored pose was expected to fail the Judge; if it now passes, "
        "this test no longer exercises the solver"
    )

    # The solver reports that it converged, and in how many iterations.
    assert _text_of(entry, "5") == "True", (
        "AutoFrame did not converge on a pose that satisfies the Judge"
    )
    iterations = int(_text_of(entry, "6"))
    assert 1 <= iterations <= 24, (
        f"AutoFrame reported {iterations} iterations; the reference budget is 24"
    )

    # And the solver's pose is scored by the same Judge, in the same server.
    assert _text_of(entry, "7") == "True", (
        "the pose AutoFrame returned does not pass the Judge that rejected the "
        f"authored pose -- the loop does not close. Judge said: {_text_of(entry, '8')}"
    )
