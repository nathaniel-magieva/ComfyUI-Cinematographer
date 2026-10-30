"""Drive this pack through the official Comfy API v2 proxy.

Why this file exists
--------------------
Comfy Org publishes two MIT pieces that together let SDK code written for Comfy
Cloud drive a *self-hosted* ComfyUI:

    @comfyorg/sdk        the client  (COMFY_BASE_URL is the only per-surface difference)
    comfy-api-proxy      the server  (serves /api/v2/* in front of a local ComfyUI)

The SDK's own source says the self-hosted path needs no key::

    // COMFY_BASE_URL=http://127.0.0.1:8189 in the environment targets a
    // self-hosted proxy instead, where no key is needed.

That claim is about *their* client talking to *a* ComfyUI. This file tests the
part that actually matters to us: that the thing on the other end can be **this
pack**. It submits a graph made only of Cinematographer nodes, through the
proxy, and reads the values back.

Two traps this file is written around
-------------------------------------
1. **The pruning trap.** A node whose output nothing consumes, and which is not
   ``OUTPUT_NODE = True``, is pruned and never executes. ``CinemaElementSave``
   is this pack's only output node, and it is one for its side effect, not for
   display. So the graph here terminates in stock ``PreviewAny`` taps.

2. **The ``outputs`` trap, in a new place.** The proxy reports
   ``status: "succeeded"`` with ``outputs: []`` for a job whose nodes ran
   perfectly. ``outputs`` is populated from ComfyUI's ``/view``-able artifacts
   (images, video), and this pack returns plain ``STRING``/``BOOLEAN``. Reading
   ``outputs`` alone would say "nothing happened", which is false. The values
   are in ComfyUI's own ``/history``, and that is where this test reads them.

Gating
------
Needs a live ComfyUI (``COMFYUI_URL``) *and* a proxy in front of it
(``COMFY_PROXY_URL``). Both are skipped with a specific reason when absent, so
the suite stays green on a machine with neither.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import pytest

COMFYUI_URL = os.environ.get("COMFYUI_URL", "").rstrip("/")
PROXY_URL = os.environ.get("COMFY_PROXY_URL", "").rstrip("/")

# The proxy's terminal statuses. Note "succeeded", not "success" -- the proxy
# normalises ComfyUI's status_str into its own vocabulary.
_TERMINAL = {"succeeded", "success", "completed", "failed", "error", "cancelled"}


def _skip_reason() -> str | None:
    if not COMFYUI_URL:
        return "COMFYUI_URL is not set; point it at a running ComfyUI to run this module"
    if not PROXY_URL:
        return "COMFY_PROXY_URL is not set; start comfy-api-proxy and point it here"
    for label, base in (("ComfyUI", COMFYUI_URL), ("proxy", PROXY_URL)):
        try:
            with urllib.request.urlopen(base + "/api/v2/health" if label == "proxy"
                                        else base + "/system_stats", timeout=5):
                pass
        except Exception as exc:  # noqa: BLE001 - any failure means "not up"
            return f"{label} at {base} is not reachable ({type(exc).__name__})"
    return None


pytestmark = pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _our_graph() -> dict:
    """A graph of nothing but Cinematographer nodes, plus stock PreviewAny taps."""
    return {
        "1": {"class_type": "CinemaDirectorPanel", "inputs": {
            "genre": "noir", "era": "1980s", "pacing": "calm",
            "camera_model": "35mm-film", "camera_lens": "anamorphic",
            "camera_aperture": "f4-moderate", "light": "contre-jour",
            "color_palette": "twilight-fable"}},
        "2": {"class_type": "CinemaPromptCompose", "inputs": {
            "action": "@tamsin walks into the diner, #dolly-in",
            "panel_json": ["1", 0],
            "registry_path": "cinematographer/elements.json"}},
        "3": {"class_type": "CinematographerEvaluate", "inputs": {
            "subject_json": json.dumps({
                "name": "Tamsin", "base": [0, 0, 0],
                "height": 1.75, "facing_yaw_deg": 0.0}),
            "camera_json": json.dumps({
                "eye": [0, 1.66, 3.0], "target": [0, 1.66, 0.0],
                "focal_mm": 35.0}),
            "shot_type": "medium"}},
        "4": {"class_type": "CinematographerCorrection",
              "inputs": {"report_json": ["3", 0]}},
        "5": {"class_type": "PreviewAny", "inputs": {"source": ["2", 0]}},
        "6": {"class_type": "PreviewAny", "inputs": {"source": ["3", 2]}},
        "7": {"class_type": "PreviewAny", "inputs": {"source": ["4", 0]}},
    }


def _submit_and_wait(graph: dict) -> tuple[str, dict]:
    """POST the graph to the proxy, poll to a terminal status, return (id, job)."""
    status, body = _post(PROXY_URL + "/api/v2/jobs", {"workflow": graph})
    assert status in (200, 201), f"proxy rejected the graph: HTTP {status} {body}"
    job_id = body.get("id") or body.get("job_id") or body.get("prompt_id")
    assert job_id, f"proxy returned no job id: {body}"

    deadline = time.time() + 120
    job: dict = {}
    while time.time() < deadline:
        _, job = _get(f"{PROXY_URL}/api/v2/jobs/{job_id}")
        if job.get("status") in _TERMINAL:
            return job_id, job
        time.sleep(1)
    pytest.fail(f"job {job_id} never reached a terminal status; last={job.get('status')!r}")


def _history_entry(prompt_id: str) -> dict:
    _, hist = _get(f"{COMFYUI_URL}/history/{prompt_id}")
    assert prompt_id in hist, f"{prompt_id} is not in ComfyUI history"
    return hist[prompt_id]


def _tap(entry: dict, node_id: str) -> str:
    """Read a PreviewAny tap's rendered text out of ComfyUI's history."""
    out = entry.get("outputs", {}).get(node_id)
    assert out is not None, (
        f"node {node_id} produced no UI output; it was pruned or never ran. "
        f"nodes that did: {sorted(entry.get('outputs', {}))}"
    )
    text = out.get("text")
    if isinstance(text, list):
        text = text[0] if text else ""
    return str(text)


def test_the_proxy_accepts_a_graph_made_only_of_our_nodes():
    """The proxy resolves our class_types against the live ComfyUI and queues it."""
    job_id, job = _submit_and_wait(_our_graph())
    assert job.get("status") in ("succeeded", "success", "completed"), job
    assert job.get("error") is None, job.get("error")


def test_our_nodes_actually_executed_behind_the_proxy():
    """The values are real, and they came from our engine, not from a stub."""
    job_id, _ = _submit_and_wait(_our_graph())
    entry = _history_entry(job_id)
    assert entry["status"]["status_str"] == "success", entry["status"]

    panel = _tap(entry, "5")
    assert "genre noir" in panel and "palette twilight-fable" in panel, panel
    assert "#dolly-in" in panel, panel

    verdict = _tap(entry, "6")
    assert verdict.startswith(("PASS", "FAIL")), verdict
    assert "medium" in verdict, verdict

    corrections = _tap(entry, "7")
    assert corrections.strip(), "the JUDGE->POST gate produced no correction text"


def test_the_judge_to_post_gate_carries_corrections_through_the_proxy():
    """The gate is a data dependency, so it must survive the extra hop."""
    job_id, _ = _submit_and_wait(_our_graph())
    entry = _history_entry(job_id)
    corrections = _tap(entry, "7")
    # The default pose fails rule_of_thirds, headroom and shot_size at medium.
    assert "rule_of_thirds" in corrections, corrections
    assert "headroom" in corrections, corrections
    # And the headroom advice must point the right way (see tests/test_framing.py).
    assert "lower the camera target or push in" in corrections, corrections


def test_the_proxy_reports_succeeded_with_empty_outputs_for_a_text_only_pack():
    """Pin the trap, so nobody later reads ``outputs: []`` as "nothing ran".

    This is not a defect report against the proxy. ``outputs`` is built from
    ComfyUI's viewable artifacts; this pack returns STRING/BOOLEAN. The
    assertion is deliberately written as "empty AND the work happened", so that
    if the proxy ever starts surfacing text outputs, this test fails loudly and
    we update the README rather than silently keeping a stale claim.
    """
    job_id, job = _submit_and_wait(_our_graph())
    entry = _history_entry(job_id)

    assert entry["status"]["status_str"] == "success"
    assert _tap(entry, "6").startswith(("PASS", "FAIL"))

    assert job.get("outputs") == [], (
        "the proxy now returns non-empty outputs for a text-only graph; "
        "the README's note about outputs: [] is stale and should be updated"
    )


def test_the_proxy_round_trips_our_graph_unchanged():
    """What we sent is what ComfyUI ran -- no silent rewriting of our inputs."""
    graph = _our_graph()
    job_id, _ = _submit_and_wait(graph)
    status, body = _get(f"{PROXY_URL}/api/v2/jobs/{job_id}/workflow")
    assert status == 200, body
    sent = body.get("workflow", body)
    for node_id, node in graph.items():
        assert node_id in sent, f"node {node_id} missing from the round-tripped graph"
        assert sent[node_id]["class_type"] == node["class_type"]
        for key, value in node["inputs"].items():
            assert sent[node_id]["inputs"][key] == value, (
                f"node {node_id}.{key} was rewritten: "
                f"{value!r} -> {sent[node_id]['inputs'][key]!r}"
            )
