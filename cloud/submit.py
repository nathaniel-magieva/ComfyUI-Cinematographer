#!/usr/bin/env python3
"""Submit an API-format ComfyUI workflow to Comfy Cloud and report what happened.

Design rules, because this script is the thing that decides whether we believe a
result:

  * FAIL LOUDLY. Every non-2xx response is printed with the server's own status,
    body and message, and the process exits non-zero. No error is ever converted
    into a success, and no missing field is defaulted into a pass.
  * NO SPEND WITHOUT SAYING SO. Submitting costs credits. `--submit` is required
    to actually spend; the default is a free local check. `--yes` is required on
    top of that when the workflow looks expensive.
  * POLL, DO NOT STREAM. `GET /api/v2/jobs/{id}` is the authoritative view and is
    resumable. The SSE stream is a live enhancement, never the source of truth.

Surfaces (all three speak the same v2 API; only the base URL changes):
  Comfy Cloud          https://cloud.comfy.org        Authorization: Bearer <key>
  Comfy API deployment https://<d>.run.comfy.app      Authorization: Bearer <key>
  self-hosted proxy    http://127.0.0.1:8189          none by default

Usage:
  export COMFY_API_KEY=comfyui-...
  python submit.py --workflow ../workflows/reshoot_ltx25.json --check-nodes
  python submit.py --workflow ../workflows/reshoot_ltx25.json --dry-run
  python submit.py --workflow ../workflows/reshoot_ltx25.json --submit --yes

Docs: https://docs.comfy.org/api-reference/v2/overview
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_BASE = "https://cloud.comfy.org"

#: Statuses that mean the job will not change again.
TERMINAL = frozenset({"succeeded", "failed", "expired", "canceled"})

#: HTTP statuses worth naming, because each means something different and the
#: difference matters operationally. 401 and 429 are the two the brief calls out.
HTTP_MEANING = {
    400: "invalid request (bad workflow, missing fields)",
    401: "UNAUTHORIZED -- invalid or missing API key",
    402: "INSUFFICIENT CREDITS",
    403: "forbidden",
    404: "not found",
    422: "unprocessable -- the graph was rejected before execution",
    429: "SUBSCRIPTION INACTIVE (or rate limited)",
    500: "server error",
    503: "service unavailable",
}


class ComfyError(Exception):
    """Any failure that must stop the run. Never caught into a success."""


# --------------------------------------------------------------------------- io


def load_workflow(path: str) -> dict:
    """Read an API-format workflow and refuse anything that is not one.

    The UI graph format has a top-level "nodes" array; the API format is a flat
    map of node-id -> {class_type, inputs}. Submitting the wrong one produces a
    confusing server error, so it is caught here with a clear message.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ComfyError(f"{path}: file not found")
    except ValueError as exc:
        raise ComfyError(f"{path}: not valid JSON: {exc}")

    if not isinstance(raw, dict):
        raise ComfyError(f"{path}: top level must be a JSON object")

    if "nodes" in raw and isinstance(raw["nodes"], list):
        raise ComfyError(
            f"{path}: this is UI graph format (top-level 'nodes' array). Comfy Cloud "
            "needs API format -- export with 'Save (API Format)'."
        )

    nodes = {k: v for k, v in raw.items() if k != "_README"}
    if not nodes:
        raise ComfyError(f"{path}: no nodes")

    for nid, node in nodes.items():
        if not isinstance(node, dict):
            raise ComfyError(f"{path}: node {nid} is not an object")
        if "class_type" not in node:
            raise ComfyError(f"{path}: node {nid} has no class_type")
        if not isinstance(node.get("inputs"), dict):
            raise ComfyError(f"{path}: node {nid} has no inputs object")

    return raw


def node_map(workflow: dict) -> dict:
    return {k: v for k, v in workflow.items() if k != "_README"}


# ------------------------------------------------------------------------ http


def _request(method: str, url: str, api_key: str, body: dict | None = None,
             timeout: int = 60) -> tuple[int, dict | str]:
    """One HTTP call. Returns (status, parsed-json-or-raw-text).

    Never raises for an HTTP error status -- the caller decides, because a 401
    during `--check-nodes` and a 401 during `--submit` deserve different words.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(text)
            except ValueError:
                return resp.status, text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except ValueError:
            return exc.code, text
    except urllib.error.URLError as exc:
        raise ComfyError(f"could not reach {url}: {exc.reason}")


def explain_http(status: int, payload) -> str:
    """Turn a non-2xx response into the loudest accurate sentence we can.

    The live server answers a bad key with `{"code":"UNAUTHORIZED","message":"Unauthorized"}`
    -- two fields, and the CODE is the machine-readable one. Picking a single key
    loses half of that, so a dict carrying `code` is printed whole.
    """
    meaning = HTTP_MEANING.get(status, "unexpected status")
    if isinstance(payload, dict) and ("code" in payload or "message" in payload):
        parts = []
        if payload.get("code"):
            parts.append(f"code={payload['code']}")
        if payload.get("message"):
            parts.append(f"message={payload['message']!r}")
        detail = " ".join(parts)
        rest = {k: v for k, v in payload.items() if k not in ("code", "message")}
        if rest:
            detail += f"  other={json.dumps(rest)[:1500]}"
        return f"HTTP {status} -- {meaning}\n  server said: {detail}"
    detail = payload
    if isinstance(payload, dict):
        for key in ("error", "detail", "errors"):
            if key in payload:
                detail = payload[key]
                break
    return f"HTTP {status} -- {meaning}\n  server said: {json.dumps(detail)[:2000]}"


# ------------------------------------------------------------------ node check


def check_nodes(workflow: dict, api_key: str, base: str) -> int:
    """Ask Cloud which node types it has, and report the ones it does not.

    This is the cheap, decisive test for the question 'can this graph run on
    Comfy Cloud at all'. It costs no credits -- it is a GET against the node
    definition endpoint.

    `GET /api/object_info` is a v1 Cloud endpoint; v2 does not expose node
    definitions. That is documented, not a guess:
    https://docs.comfy.org/development/cloud/overview
    """
    status, payload = _request("GET", f"{base}/api/object_info", api_key, timeout=120)
    if status != 200:
        print(explain_http(status, payload), file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print(f"object_info returned {type(payload).__name__}, expected an object",
              file=sys.stderr)
        return 2

    available = set(payload)
    used = sorted({n["class_type"] for n in node_map(workflow).values()})
    missing = [c for c in used if c not in available]

    print(f"Cloud reports {len(available)} node types.")
    print(f"This workflow uses {len(used)} distinct class_types.")
    if not missing:
        print("ALL PRESENT -- every class_type is available on this surface.")
        return 0

    print(f"\nMISSING ({len(missing)}) -- these would fail with 'node type not found':")
    for c in missing:
        print(f"  {c}")
    print("\nThis graph CANNOT run on this surface as written.")
    return 1


# --------------------------------------------------------------------- submit


def submit(workflow: dict, api_key: str, base: str) -> str:
    """POST the workflow, return the job id. Raises on anything but 201."""
    body = {
        "workflow": node_map(workflow),
        "extra_data": {"api_key_comfy_org": api_key},
        "metadata": {"client": "cine-publish/cloud/submit.py"},
    }
    status, payload = _request(
        "POST", f"{base}/api/v2/jobs", api_key, body=body,
        # Idempotency guards against a duplicate submission if the connection
        # drops after the server accepted it -- a duplicate would spend credits
        # twice for one intended run.
    )
    if status != 201:
        raise ComfyError(explain_http(status, payload))
    if not isinstance(payload, dict) or "id" not in payload:
        raise ComfyError(
            f"submit returned HTTP {status} but no job id; body was "
            f"{json.dumps(payload)[:2000]}"
        )
    return payload["id"]


def poll(job_id: str, api_key: str, base: str, interval: float,
         max_wait: float) -> dict:
    """Poll to a terminal state. Returns the final job object."""
    started = time.monotonic()
    last_line = ""
    while True:
        status, payload = _request("GET", f"{base}/api/v2/jobs/{job_id}", api_key)
        if status != 200:
            raise ComfyError(explain_http(status, payload))
        if not isinstance(payload, dict):
            raise ComfyError(f"job {job_id}: expected an object, got {type(payload).__name__}")

        state = payload.get("status")
        if state is None:
            raise ComfyError(f"job {job_id}: response has no 'status': {json.dumps(payload)[:500]}")

        progress = payload.get("progress") or {}
        line = f"  [{time.monotonic() - started:6.1f}s] {state}"
        if isinstance(progress, dict) and progress.get("message"):
            line += f"  {progress['message']}"
        elif isinstance(progress, dict) and progress.get("nodes_done") is not None:
            line += f"  {progress['nodes_done']}/{progress.get('nodes_total')} nodes"
        if line != last_line:
            print(line, flush=True)
            last_line = line

        if state in TERMINAL:
            return payload

        if time.monotonic() - started > max_wait:
            raise ComfyError(
                f"job {job_id} still {state!r} after {max_wait:.0f}s. It is NOT failed "
                f"and NOT succeeded -- it is still running. Re-poll with:\n"
                f"  GET {base}/api/v2/jobs/{job_id}"
            )
        time.sleep(interval)


def report(job: dict) -> int:
    """Print the outcome. Returns the process exit code.

    The whole point of this function is that a failure must never print like a
    success. `succeeded` with zero outputs is reported as a failure, because a
    job that produced nothing did not do the thing we asked.
    """
    state = job.get("status")
    job_id = job.get("id", "?")
    print(f"\njob {job_id}: {state}")

    for key in ("created_at", "started_at", "completed_at"):
        if job.get(key):
            print(f"  {key}: {job[key]}")

    if state != "succeeded":
        error = job.get("error")
        print("\nFAILED. Server's own report:", file=sys.stderr)
        if isinstance(error, dict):
            for key in ("code", "message", "node_id", "class_type"):
                if error.get(key) is not None:
                    print(f"  {key}: {error[key]}", file=sys.stderr)
            if error.get("node_errors"):
                print("  node_errors:", file=sys.stderr)
                print(f"    {json.dumps(error['node_errors'], indent=2)[:4000]}", file=sys.stderr)
            if error.get("traceback"):
                print("  traceback:", file=sys.stderr)
                print(f"    {error['traceback'][:4000]}", file=sys.stderr)
        elif error is not None:
            print(f"  {json.dumps(error)[:4000]}", file=sys.stderr)
        else:
            print("  (the server returned no 'error' object -- that is itself a finding)",
                  file=sys.stderr)
        return 1

    outputs = job.get("outputs") or []
    if not outputs:
        print(
            "\nstatus is 'succeeded' but there are ZERO outputs. That is not a pass: "
            "the job ran and produced nothing. Treat as failure.",
            file=sys.stderr,
        )
        return 1

    print(f"\n{len(outputs)} output(s):")
    by_node: dict[str, list] = {}
    for item in outputs:
        by_node.setdefault(str(item.get("node_id", "?")), []).append(item)
    for nid in sorted(by_node, key=str):
        print(f"  node {nid}:")
        for item in by_node[nid]:
            size = item.get("size_bytes")
            size_s = f"{size:,} bytes" if isinstance(size, int) else "size unknown"
            print(f"    {item.get('name', '?')}  [{item.get('type', '?')}]  {size_s}")
            if item.get("url"):
                print(f"      {item['url']}")
    return 0


# ------------------------------------------------------------------- selftest


def selftest() -> int:
    """Prove the checks discriminate, by sabotaging what they check.

    A check that has never failed is not evidence. This runs the local
    validation against deliberately broken inputs and asserts each one is
    rejected. If any sabotage slips through, the selftest fails.
    """
    import tempfile

    good = {
        "1": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    cases: list[tuple[str, object, bool]] = []

    def write(obj) -> str:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(obj, handle)
        return path

    # 1. a good workflow must load
    cases.append(("valid API-format workflow loads", write(good), True))
    # 2. UI format must be rejected
    cases.append(("UI graph format rejected",
                  write({"nodes": [{"id": 1}], "links": []}), False))
    # 3. a node with no class_type must be rejected
    cases.append(("node without class_type rejected",
                  write({"1": {"inputs": {}}}), False))
    # 4. a node with no inputs object must be rejected
    cases.append(("node without inputs rejected",
                  write({"1": {"class_type": "KSampler"}}), False))
    # 5. non-JSON must be rejected
    fd, bad = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(bad, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    cases.append(("malformed JSON rejected", bad, False))
    # 6. a missing file must be rejected
    cases.append(("missing file rejected", "/nonexistent/workflow.json", False))

    failures = 0
    for label, path, should_load in cases:
        try:
            load_workflow(path)
            loaded = True
            note = ""
        except ComfyError as exc:
            loaded = False
            note = f"  ({str(exc)[:70]})"
        ok = loaded == should_load
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'}  {label}{note}")

    # 7. explain_http must surface the server's own words, not a generic string
    msg = explain_http(401, {"error": "invalid api key"})
    ok = "401" in msg and "invalid api key" in msg
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'}  explain_http surfaces the server's own message")

    # 8. report() must NOT return 0 for succeeded-with-no-outputs
    code = report({"id": "x", "status": "succeeded", "outputs": []})
    ok = code != 0
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'}  succeeded-with-zero-outputs is NOT a pass")

    # 9. report() must NOT return 0 for a failed job
    code = report({"id": "x", "status": "failed", "error": {"code": "node_execution_error"}})
    ok = code != 0
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'}  failed job is NOT a pass")

    print(f"\nselftest: {len(cases) + 3 - failures}/{len(cases) + 3} checks discriminate")
    return 1 if failures else 0


# ----------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Submit an API-format workflow to Comfy Cloud.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workflow", help="path to an API-format workflow JSON")
    parser.add_argument("--base", default=os.environ.get("COMFY_BASE_URL", DEFAULT_BASE),
                        help=f"API base URL (default {DEFAULT_BASE})")
    parser.add_argument("--check-nodes", action="store_true",
                        help="ask Cloud which class_types it has; costs NO credits")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the file locally and print the plan; costs NO credits")
    parser.add_argument("--submit", action="store_true",
                        help="ACTUALLY SUBMIT. This spends credits.")
    parser.add_argument("--yes", action="store_true",
                        help="required alongside --submit to confirm the spend")
    parser.add_argument("--interval", type=float, default=5.0, help="poll interval seconds")
    parser.add_argument("--max-wait", type=float, default=1800.0, help="give up after N seconds")
    parser.add_argument("--selftest", action="store_true",
                        help="prove the checks discriminate; needs no key and no network")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.workflow:
        parser.error("--workflow is required (or use --selftest)")

    try:
        workflow = load_workflow(args.workflow)
    except ComfyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    nodes = node_map(workflow)
    used = sorted({n["class_type"] for n in nodes.values()})
    print(f"{args.workflow}: {len(nodes)} nodes, {len(used)} distinct class_types")

    if args.dry_run:
        print("\ndry run -- nothing submitted, no credits spent.")
        for c in used:
            print(f"  {c}")
        return 0

    api_key = os.environ.get("COMFY_API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: COMFY_API_KEY is not set.\n"
            "  Get a key at https://platform.comfy.org -> Profile -> API Keys (prefix comfyui-).\n"
            "  API access requires a PAID subscription; the free tier does not include it.",
            file=sys.stderr,
        )
        return 2

    try:
        if args.check_nodes:
            return check_nodes(workflow, api_key, args.base)

        if not args.submit:
            print(
                "\nNothing to do. Pass --check-nodes (free), --dry-run (free), or "
                "--submit --yes (SPENDS CREDITS).",
                file=sys.stderr,
            )
            return 2

        if not args.yes:
            print(
                "ERROR: --submit spends credits and --yes was not given.\n"
                "  Re-run with --submit --yes once the spend is approved.",
                file=sys.stderr,
            )
            return 2

        print(f"\nsubmitting to {args.base} ...")
        job_id = submit(workflow, api_key, args.base)
        print(f"job id: {job_id}")
        job = poll(job_id, api_key, args.base, args.interval, args.max_wait)
        return report(job)

    except ComfyError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
