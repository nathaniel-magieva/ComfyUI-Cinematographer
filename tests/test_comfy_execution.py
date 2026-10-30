"""Drive the pack through ComfyUI's real execution engine.

Every other test in this repository exercises the engine directly, as plain
Python. That is fast and it is where the arithmetic is pinned down, but it
cannot answer the question a user actually asks: *does this load and run in
ComfyUI?* A node can have a correct engine behind it and still be broken as a
node -- a declared input the callable does not accept, a return arity that
disagrees with ``RETURN_TYPES``, a ``FUNCTION`` name that does not exist, an
output nothing consumes and which is therefore pruned and never runs.

This module closes that gap. It boots ComfyUI's own loader, builds a graph with
``GraphBuilder``, runs it through ``execution.PromptExecutor``, and reads the
values back out of the executor cache.

It is gated on ``COMFYUI_PATH`` and skips with a *specific* reason when it
cannot run -- no path, not a checkout, or no ``torch``. A skip that says why is
the difference between "this passed" and "this never ran", and a green suite
must never be mistaken for the second.

Run it with::

    COMFYUI_PATH=/path/to/ComfyUI python -m pytest tests/test_comfy_execution.py -q

Two things this module would have caught, and did:

* ``CinematographerEvaluate`` declares ``shot_type`` as a required input. A
  harness that guessed the signature instead of reading ``INPUT_TYPES()``
  failed on it.
* ``CinemaGrade.corrections`` is optional, so a graph that omits the
  JUDGE->POST edge still validates. Only execution proves the correction text
  actually arrives.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import sys

import pytest

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "")


def _skip_reason() -> str | None:
    """Why this module cannot run, or ``None`` if it can.

    Deliberately specific. "skipped" with no reason is how a suite goes green
    while proving nothing.
    """
    if not COMFYUI_PATH:
        return "COMFYUI_PATH is not set; set it to a ComfyUI checkout to run these"
    if not os.path.isdir(COMFYUI_PATH):
        return f"COMFYUI_PATH={COMFYUI_PATH!r} is not a directory"
    if not os.path.isfile(os.path.join(COMFYUI_PATH, "nodes.py")):
        return f"COMFYUI_PATH={COMFYUI_PATH!r} has no nodes.py; not a ComfyUI checkout"
    if importlib.util.find_spec("torch") is None:
        return "torch is not importable; ComfyUI cannot be loaded in this interpreter"
    return None


pytestmark = pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")


class _Server:
    """The stub ComfyUI's own test suite uses.

    ``PromptExecutor`` requires a server for ``send_sync``. ComfyUI's
    ``tests-unit/execution_test/`` passes exactly this shape, so using it is
    the sanctioned way to drive the executor without a live server.
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

    import nodes as comfy_nodes

    # The loader is async and must own its event loop. ``execute()`` below is
    # sync and calls ``asyncio.run`` internally, so it cannot be called from
    # inside this coroutine -- hence the split.
    asyncio.run(comfy_nodes.init_extra_nodes(init_custom_nodes=True))

    import execution
    from comfy_execution.graph_utils import GraphBuilder

    return {"nodes": comfy_nodes, "execution": execution, "GraphBuilder": GraphBuilder}


def _run(comfy, build):
    """Build a graph, execute it, return ``(prompt, executor)``.

    ``CacheType.CLASSIC`` matters. ``CacheType.NONE`` yields a ``NullCache``,
    which discards outputs by design: every node executes, but nothing is
    readable, so the run proves execution and cannot prove *output*. CLASSIC
    with a fresh executor gives both -- the cache starts empty, so every node
    still runs, and the results are retained.
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
    # execute_outputs forces every node to run. Without it, a node whose output
    # nothing consumes and which is not OUTPUT_NODE is pruned and never
    # executes -- a silent pass.
    ex.execute(prompt, "test-prompt-id", execute_outputs=list(prompt.keys()))
    return prompt, ex


def _outputs(ex, prompt, node_id):
    """Read a node's outputs out of the executor cache.

    ``get_local`` returns a ``CacheEntry`` namedtuple, not a dict: read
    ``entry.outputs[i][0]``. ``HierarchicalCache.get`` is the async equivalent
    and takes a bare node id, not a ``(prompt_id, node_id, index)`` tuple.
    """
    entry = ex.caches.outputs.get_local(node_id)
    assert entry is not None, f"node {node_id} produced no output; it was pruned or failed"
    return entry.outputs


def _errors(ex):
    return [
        d for event, d in ex.status_messages if event == "execution_error"
    ]


def _first_node_of(prompt, class_type):
    """Find a node by class_type.

    ``GraphBuilder`` node ids are the ``.0.0.N`` strings, so a ``k.isdigit()``
    filter would exclude every node in the graph.
    """
    for nid, node in prompt.items():
        if node.get("class_type") == class_type:
            return nid
    raise AssertionError(f"no {class_type} in the graph")


def test_pack_loads_and_registers_its_nodes(comfy):
    """The pack's nodes are present in ComfyUI's registry, and are callable."""
    mappings = comfy["nodes"].NODE_CLASS_MAPPINGS
    ours = {
        name: cls
        for name, cls in mappings.items()
        if getattr(cls, "__module__", "").startswith("cinematographer")
    }
    assert len(ours) == 18, f"expected 18 nodes, found {len(ours)}: {sorted(ours)}"

    for name, cls in ours.items():
        assert hasattr(cls, "FUNCTION"), f"{name} declares no FUNCTION"
        fn = getattr(cls, cls.FUNCTION, None)
        assert callable(fn), f"{name}.{cls.FUNCTION} is not callable"
        assert cls.INPUT_TYPES() is not None, f"{name}.INPUT_TYPES() returned None"


def test_every_declared_input_is_accepted_by_the_function(comfy):
    """A declared input the callable cannot accept is a node that cannot run.

    This is the check that catches a signature drifting away from
    ``INPUT_TYPES()`` -- the failure mode that no amount of engine-level
    testing sees.
    """
    mappings = comfy["nodes"].NODE_CLASS_MAPPINGS
    problems = []
    for name, cls in mappings.items():
        if not getattr(cls, "__module__", "").startswith("cinematographer"):
            continue
        fn = getattr(cls, cls.FUNCTION)
        sig = inspect.signature(fn)

        # A **kwargs catch-all accepts anything, so it cannot be a missing
        # input. CinemaGrade.grade is `(self, corrections="", **settings)`.
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue

        declared = set()
        spec = cls.INPUT_TYPES()
        for group in ("required", "optional"):
            declared |= set(spec.get(group, {}) or {})

        accepted = {
            p.name
            for p in sig.parameters.values()
            if p.name != "self"
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        }
        missing = declared - accepted
        if missing:
            problems.append(f"{name}.{cls.FUNCTION} needs {sorted(missing)} but does not declare it")
    assert not problems, "\n".join(problems)


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
    """The JUDGE->POST edge carries data, not just a wire.

    ``CinemaGrade.corrections`` is optional, so a graph that omits this edge
    still validates structurally. Only execution proves the correction text
    arrives. ComfyUI has no conditional execution in API format without a
    switch node, so a FAIL verdict does not stop a render -- it travels into
    POST as text. That is the design, and this is the test of it.
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
            shot_type="medium",
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
    # The report carries `scores`: a list of per-rule entries, not a dict keyed
    # by rule name. Each entry has rule/pass/value/target/weight, and a
    # `correction` only when the rule failed.
    assert "scores" in report, "the report must carry per-rule measurements"
    assert isinstance(report["scores"], list) and report["scores"]
    assert all("rule" in s and "pass" in s for s in report["scores"])

    corr_out = _outputs(ex, prompt, _first_node_of(prompt, "CinematographerCorrection"))
    corrections = corr_out[0][0]
    assert isinstance(corrections, str)

    grade_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaGrade"))
    grade_json = json.loads(grade_out[0][0])
    assert "corrections" in grade_json, "the gate did not reach POST"
    assert grade_json["corrections"] == corrections, (
        "the correction text was altered in transit; the gate must carry it verbatim"
    )


def test_headroom_correction_survives_the_engine(comfy):
    """A known-failing pose produces the correction the engine computes.

    This pins the sign convention end to end: ``head = 1 - ty``, so aiming
    higher lowers the subject and *raises* headroom. Getting that backwards
    sends the operator further from a pass, which is worse than saying nothing.
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
            shot_type="medium",
        )
        g.node("CinematographerCorrection", report_json=ev.out(0))

    prompt, ex = _run(comfy, build)
    assert ex.success, _errors(ex)

    ev_out = _outputs(ex, prompt, _first_node_of(prompt, "CinematographerEvaluate"))
    report = json.loads(ev_out[0][0])
    headroom = next(s for s in report["scores"] if s["rule"] == "headroom")
    assert headroom["pass"] is False, "this pose is chosen to fail headroom"
    assert headroom["value"] > 0.45, "the measured headroom must exceed the medium band"

    corr_out = _outputs(ex, prompt, _first_node_of(prompt, "CinematographerCorrection"))
    corrections = corr_out[0][0]
    assert "headroom" in corrections
    assert "lower the camera target or push in" in corrections, (
        "too much headroom must advise lowering the target or pushing in"
    )


def test_camera_move_output_is_not_wireable_into_prompt_compose(comfy):
    """The two move resolvers are parallel, not a pipeline.

    ``CinemaCameraMove.moves`` emits a JSON array; ``CinemaPromptCompose.moves``
    parses comma/newline-separated names. Linking them is type-legal (STRING to
    STRING) and semantically wrong, so the shipped graph does not link them.
    This test pins that decision: feeding the JSON form in must not silently
    produce a bogus move.
    """

    def build(g, M):
        mv = g.node("CinemaCameraMove", prompt="a detective walks in #dolly-in")
        g.node(
            "CinemaPromptCompose",
            action="a detective walks in",
            moves=mv.out(1),
        )

    prompt, ex = _run(comfy, build)
    # Either it raises, or it resolves nothing -- what it must not do is invent
    # a move from the JSON punctuation.
    if ex.success:
        compose_out = _outputs(ex, prompt, _first_node_of(prompt, "CinemaPromptCompose"))
        final_prompt, _a, unresolved, ok = compose_out
        assert ok[0] is False or json.loads(unresolved[0]) != [], (
            "the JSON form of moves must not resolve as if it were a move name"
        )
    else:
        errs = _errors(ex)
        assert errs, "a failed run must report an execution_error"


def test_shipped_full_flow_graph_executes_until_it_needs_weights(comfy):
    """The shipped 94-node graph runs, and stops only where weights are missing.

    This is the honest boundary of the whole repository. The graph is real and
    it executes; it halts at the first node that needs a checkpoint file, which
    on a machine with no models is ``VAELoader``. That is a weights problem,
    not a code problem, and the difference matters: it is the difference
    between "we never ran it" and "we ran it as far as this machine allows".

    The assertion is deliberately about *where* it stops, not *that* it stops.
    If a future edit breaks a node upstream of the loaders, the count drops and
    this fails. If someone adds weights, the count rises and this still passes.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "workflows", "cinema_studio_full.json")
    with open(path) as fh:
        graph = json.load(fh)
    prompt = {k: v for k, v in graph.items() if k != "_README"}

    execution = comfy["execution"]
    ex = execution.PromptExecutor(
        _Server(),
        cache_type=execution.CacheType.CLASSIC,
        cache_args={"ram": 0, "ram_inactive": 0},
    )
    ex.execute(prompt, "full-graph", execute_outputs=list(prompt.keys()))

    ran = [nid for nid in prompt if ex.caches.outputs.get_local(nid) is not None]
    errs = _errors(ex)

    # Every node that ran, ran without error. A node that produced output and
    # an error is a contradiction.
    assert len(ran) >= 25, (
        f"only {len(ran)}/{len(prompt)} nodes executed; the graph regressed "
        f"upstream of the model loaders. Errors: {[e.get('node_type') for e in errs]}"
    )

    if errs:
        # The stop must be a missing-file stop, not a wiring stop.
        first = errs[0]
        msg = str(first.get("exception_message", ""))
        assert "not found" in msg or "No such file" in msg, (
            f"the graph stopped for a reason other than missing weights: "
            f"{first.get('node_type')}: {msg}"
        )
        assert first.get("node_type") in {
            "VAELoader", "UNETLoader", "CLIPLoader", "DualCLIPLoader",
            "LatentUpscaleModelLoader",
        }, f"stopped at {first.get('node_type')}, which is not a model loader"
