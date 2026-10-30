"""Execute this pack through ComfyUI's real execution engine.

Every other test in this suite calls the engine modules directly. That proves the
arithmetic, but it does not prove the pack is a *ComfyUI node pack*: it does not
prove the nodes load, that their declared inputs match their function signatures,
or that a graph built from them runs. Those are exactly the failures that a
direct-call test cannot see, because a direct call bypasses ``INPUT_TYPES``
entirely.

This module drives ``comfy_execution``'s ``PromptExecutor`` -- the same class the
ComfyUI server uses -- over a graph built with ComfyUI's own ``GraphBuilder``. It
is the only test here that would have caught the two defects it was written
after:

* ``CinematographerEvaluate`` requires ``shot_type``. A caller that omits it gets
  a ``TypeError`` from inside the executor, not from the node.
* ``CinemaCameraMove.moves`` emits a JSON array while ``CinemaPromptCompose.moves``
  parses comma/newline-separated names. Both are ``STRING``, so the link is
  type-legal and semantically wrong. See ``workflows/cinema_studio_full.json``'s
  ``_README``: the two nodes are deliberately NOT linked, and this test pins that
  decision so a future edit cannot quietly wire them together.

Skipped unless ComfyUI is importable. Point ``COMFYUI_PATH`` at a checkout to run
it::

    COMFYUI_PATH=/path/to/ComfyUI python -m pytest tests/test_comfy_execution.py -v

The pack must also be visible to that checkout as a custom node. The test does not
install it; it asserts on the pack as loaded.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "")


def _skip_reason():
    """Why these tests cannot run here, or ``None`` if they can.

    ComfyUI's own dependencies (torch above all) are heavy and are not this
    pack's dependencies, so the common case is that the interpreter running the
    suite cannot import ComfyUI at all. That is a skip, not a failure -- but it
    must be a skip that says which piece is missing, so a green run is never
    mistaken for "the pack was executed".
    """
    if not COMFYUI_PATH:
        return "set COMFYUI_PATH to a ComfyUI checkout to run the execution tests"
    if not os.path.isdir(COMFYUI_PATH):
        return f"COMFYUI_PATH={COMFYUI_PATH} is not a directory"
    if not os.path.isfile(os.path.join(COMFYUI_PATH, "nodes.py")):
        return f"COMFYUI_PATH={COMFYUI_PATH} has no nodes.py; is it a ComfyUI checkout?"
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        return f"ComfyUI needs torch, which this interpreter lacks ({exc})"
    return None


pytestmark = pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")


class _Server:
    """The stub ComfyUI's own tests-unit suite uses to drive the executor.

    ``PromptExecutor`` requires a server for ``send_sync``; nothing in this test
    reads the messages, so a no-op is enough. This is the sanctioned pattern --
    see ``tests-unit/execution_test/test_nested_loop_execution.py``.
    """

    client_id = None

    def send_sync(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def comfy():
    """Boot ComfyUI's loader once and hand back the pieces the tests need."""
    sys.argv = ["main.py", "--cpu", "--quick-test-for-ci"]
    os.chdir(COMFYUI_PATH)
    if COMFYUI_PATH not in sys.path:
        sys.path.insert(0, COMFYUI_PATH)

    import nodes as comfy_nodes  # noqa: E402

    # The loader is async; run it in its own loop. The executor's sync
    # ``execute()`` wraps ``asyncio.run`` internally, so it must NOT be called
    # from inside this loop -- hence the separate ``asyncio.run`` here.
    asyncio.run(comfy_nodes.init_extra_nodes(init_custom_nodes=True))

    import execution  # noqa: E402
    from comfy_execution.graph_utils import GraphBuilder  # noqa: E402

    return {
        "nodes": comfy_nodes,
        "execution": execution,
        "GraphBuilder": GraphBuilder,
    }


def _run(comfy, build):
    """Build a graph, execute it, and return ``(prompt, executor)``.

    ``CacheType.CLASSIC`` rather than ``NONE``: ``NONE`` installs a ``NullCache``,
    which discards outputs, so the nodes run but nothing is readable. A fresh
    executor starts with an empty cache, so every node still executes.
    """
    execution = comfy["execution"]
    g = comfy["GraphBuilder"]()
    build(g, comfy["nodes"].NODE_CLASS_MAPPINGS)
    prompt = g.finalize()

    ex = execution.PromptExecutor(
        _Server(),
        cache_type=execution.CacheType.CLASSIC,
        cache_args={"ram": 0, "ram_inactive": 0},
    )
    ex.execute(prompt, "test-prompt-id", execute_outputs=list(prompt.keys()))
    return prompt, ex


def _outputs(ex, prompt, node_id):
    """Read one node's outputs. ``get_local`` is the sync accessor."""
    entry = ex.caches.outputs.get_local(node_id)
    assert entry is not None, f"node {node_id} produced no cached output"
    return entry.outputs


def _errors(ex):
    return [
        data.get("exception_message")
        for event, data in ex.status_messages
        if event == "execution_error"
    ]


def _first_node_of(prompt, class_type):
    for nid, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return nid
    raise AssertionError(f"{class_type} is not in the graph")


# --------------------------------------------------------------------------
# The pack loads and its declared inputs match its functions
# --------------------------------------------------------------------------


def test_pack_loads_and_registers_its_nodes(comfy):
    """The pack is visible to ComfyUI and every node is callable."""
    mappings = comfy["nodes"].NODE_CLASS_MAPPINGS
    ours = {
        name: cls
        for name, cls in mappings.items()
        if getattr(cls, "__module__", "").startswith("cinematographer")
    }
    assert len(ours) == 18, f"expected 18 nodes, loaded {len(ours)}: {sorted(ours)}"

    for name, cls in ours.items():
        assert callable(getattr(cls, "FUNCTION", None)) or isinstance(
            getattr(cls, "FUNCTION", None), str
        ), f"{name} has no FUNCTION"
        assert cls.INPUT_TYPES() is not None, f"{name}.INPUT_TYPES() returned None"


def test_every_declared_input_is_accepted_by_the_function(comfy):
    """A declared input the function cannot accept is a node that can never run.

    ComfyUI passes exactly the declared inputs, so a required parameter missing
    from ``INPUT_TYPES`` raises ``TypeError`` from inside the executor. This is
    the check that would have caught ``shot_type`` had it been undeclared.
    """
    import inspect

    mappings = comfy["nodes"].NODE_CLASS_MAPPINGS
    problems = []
    for name, cls in mappings.items():
        if not getattr(cls, "__module__", "").startswith("cinematographer"):
            continue
        declared = set()
        types = cls.INPUT_TYPES() or {}
        for group in ("required", "optional"):
            declared |= set(types.get(group, {}) or {})
        fn = getattr(cls, cls.FUNCTION)
        sig = inspect.signature(fn)
        # A **kwargs catch-all accepts anything, so it cannot be a missing input.
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue
        params = set(sig.parameters) - {"self"}
        missing = params - declared
        if missing:
            problems.append(f"{name}.{cls.FUNCTION} needs {sorted(missing)} but does not declare it")
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------
# A graph actually executes
# --------------------------------------------------------------------------


def test_director_panel_and_prompt_compose_execute(comfy):
    """DIRECT runs: the panel produces JSON, compose consumes it.

    ``auto`` is a node-level sentinel meaning "the director did not set this
    group", and it serialises as ``None`` -- it does NOT resolve to the first
    enum value. ``director._check`` rejects the literal string ``"auto"``, so
    the node strips it before constructing the panel. Both halves are asserted
    here: unset stays unset, and a concrete choice round-trips.
    """

    def build(g, M):
        panel = g.node(
            "CinemaDirectorPanel",
            genre="auto",
            era="auto",
            pacing="auto",
            camera_model="auto",
            camera_lens="auto",
            camera_aperture="auto",
            light="auto",
            color_palette="auto",
        )
        g.node(
            "CinemaPromptCompose",
            action="a detective walks in #dolly-in",
            panel_json=panel.out(0),
        )

    prompt, ex = _run(comfy, build)
    assert ex.success, _errors(ex)

    panel_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaDirectorPanel"))
    panel_json = json.loads(panel_out[0][0])
    assert "genre" in panel_json, "the panel must report every group, set or not"
    assert panel_json["genre"] is None, (
        "'auto' means the director left this group unset; it must not be "
        "silently resolved to a concrete value"
    )

    compose_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaPromptCompose"))
    final_prompt, _attachments, unresolved, ok = compose_out
    assert ok[0] is True
    assert "#dolly-in" in final_prompt[0], "the #move tag did not survive composition"
    assert json.loads(unresolved[0]) == [], "the move should have resolved"


def test_director_panel_concrete_choice_round_trips(comfy):
    """A set group survives the node and reaches the composed prompt."""

    def build(g, M):
        panel = g.node(
            "CinemaDirectorPanel",
            genre="noir",
            era="1980s",
            pacing="calm",
            camera_model="35mm-film",
            camera_lens="anamorphic",
            camera_aperture="f4-moderate",
            light="practicals",
            color_palette="static-noon",
        )
        g.node(
            "CinemaPromptCompose",
            action="a detective walks in",
            panel_json=panel.out(0),
        )

    prompt, ex = _run(comfy, build)
    assert ex.success, _errors(ex)

    panel_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaDirectorPanel"))
    panel_json = json.loads(panel_out[0][0])
    assert panel_json["genre"] == "noir"
    assert panel_json["era"] == "1980s"
    assert panel_json["camera_lens"] == "anamorphic"

    compose_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaPromptCompose"))
    final_prompt = compose_out[0][0]
    assert "noir" in final_prompt, "the panel fragment did not reach the prompt"
    assert "anamorphic" in final_prompt


def test_judge_to_post_gate_carries_corrections(comfy):
    """The JUDGE -> POST gate is a data dependency, and it carries real text.

    ``CinemaGrade.corrections`` is optional, so a graph that omits the edge still
    validates. This asserts the text actually arrives -- the thing
    ``validate_graphs.py`` cannot check, because it validates link legality rather
    than whether a link is present or what flows through it.
    """

    def build(g, M):
        ev = g.node(
            "CinematographerEvaluate",
            subject_json=json.dumps(
                {"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8, "facing_yaw_deg": 0.0}
            ),
            camera_json=json.dumps(
                {"eye": [0.0, 1.66, 3.0], "target": [0.0, 1.66, 0.0], "focal_mm": 35.0}
            ),
            shot_type="closeup",
        )
        corr = g.node("CinematographerCorrection", report_json=ev.out(0))
        g.node(
            "CinemaGrade",
            temperature=0.0,
            contrast=0.0,
            saturation=0.0,
            sharpness=0.0,
            film_grain=0.0,
            highlights=0.0,
            exposure=0.0,
            corrections=corr.out(0),
        )

    prompt, ex = _run(comfy, build)
    assert ex.success, _errors(ex)

    ev_out = _outputs(ex, prompt, _first_node_of(prompt, "CinematographerEvaluate"))
    report = json.loads(ev_out[0][0])
    assert report["shot_type"] == "closeup"
    assert len(report["scores"]) == 9, "the report should carry all nine framing rules"

    corr_out = _outputs(ex, prompt, _first_node_of(prompt, "CinematographerCorrection"))
    corrections = corr_out[0][0]
    assert corrections.strip(), "a failing frame must produce at least one lever"

    grade_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaGrade"))
    grade = json.loads(grade_out[0][0])
    assert grade["corrections"] == corrections, (
        "the corrections text did not reach CinemaGrade -- the gate is not wired"
    )


def test_headroom_correction_survives_the_engine(comfy):
    """The corrected headroom string is what a ComfyUI user actually sees.

    This is the end-to-end form of ``test_framing.py``'s regression: the same
    string, but read out of a node that ran inside ComfyUI rather than out of a
    direct function call.
    """

    def build(g, M):
        g.node(
            "CinematographerEvaluate",
            subject_json=json.dumps(
                {"name": "subject", "base": [0.0, 0.0, 0.0], "height": 1.8, "facing_yaw_deg": 0.0}
            ),
            camera_json=json.dumps(
                {"eye": [0.0, 1.66, 3.0], "target": [0.0, 1.66, 0.0], "focal_mm": 35.0}
            ),
            shot_type="closeup",
        )

    prompt, ex = _run(comfy, build)
    assert ex.success, _errors(ex)

    report = json.loads(_outputs(ex, prompt, _first_node_of(prompt, "CinematographerEvaluate"))[0][0])
    headroom = next(s for s in report["scores"] if s["rule"] == "headroom")

    assert headroom["pass"] is False, "this pose is the failing case the test is built on"
    assert headroom["value"] > 0.30, "headroom above the closeup band means too much space"
    assert headroom["correction"] == "too much headroom: lower the camera target or push in", (
        "the correction must move headroom toward the band; the inverted string sends "
        "the operator further from a pass"
    )


def test_camera_move_output_is_not_wireable_into_prompt_compose(comfy):
    """Pin the documented incompatibility so nobody 'fixes' it by wiring them.

    ``CinemaCameraMove.moves`` is a JSON array; ``CinemaPromptCompose.moves`` wants
    comma/newline-separated names. Both are ``STRING``, so ComfyUI will happily
    accept the link and the graph will fail at execution time. The pack's answer is
    that ``CinemaPromptCompose`` resolves ``#tags`` from ``action`` itself and
    ``CinemaCameraMove`` is a parallel resolver -- see the graph's ``_README``.

    If this test ever starts passing, the two nodes have been made compatible and
    the ``_README`` note is stale.
    """

    def build(g, M):
        move = g.node("CinemaCameraMove", prompt="a detective walks in #dolly-in", move="dolly-in")
        g.node(
            "CinemaPromptCompose",
            action="a detective walks in",
            moves=move.out(1),  # the JSON array output
        )

    prompt, ex = _run(comfy, build)

    assert not ex.success, (
        "wiring CinemaCameraMove.moves into CinemaPromptCompose.moves now works -- "
        "update workflows/cinema_studio_full.json's _README, which says it does not"
    )
    errors = _errors(ex)
    assert any("is not one of the 33 documented moves" in (e or "") for e in errors), errors
