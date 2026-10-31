# Validating on Comfy Cloud

Two files and one command. Read [`FINDINGS.md`](FINDINGS.md) first — it establishes which of our
graphs can go to Comfy Cloud at all, and the answer is not "all of them".

## The short version

| graph | class_types | on Comfy Cloud? |
|---|---|---|
| **`workflows/reshoot_ltx25.json`** | 24 | **YES** — 24/24 ComfyUI core |
| **`workflows/character_lora_train.json`** | 9 | **YES** — 9/9 core |
| `workflows/cinema_studio_full.json` | 50 | **NO** — 18 are our pack |
| `workflows/reshoot_ltx_crossview.json` | 28 | NO — 3 LTXVideo nodes absent from Cloud |
| `workflows/reshoot_ltx23_character.json` | 28 | NO — same 3 |
| `workflows/reshoot_wan22_fun_control.json` | 17 | NO — `CrossViewWarp` |

Comfy Cloud runs a **fixed catalogue of packs Comfy Org maintains**; you cannot install your own.
`ComfyUI-Cinematographer` is not in it. So the pack's own nodes — the director panel, the judge,
the element registry, the grade — **cannot be validated on Cloud at all**. They are local-only.

What *can* be validated there is the **native LTX 2.5 model path**, which is the surface that has
never been executed: no frame of video has ever been rendered by this project.

## Setup

```bash
export COMFY_API_KEY=comfyui-...        # platform.comfy.org -> Profile -> API Keys
```

API access requires a **paid** Comfy Cloud subscription; the free tier does not include it.
An invalid key returns 401, a key on an inactive subscription returns 429.

## The commands

### 1. Prove the tool's own checks work — free, offline, no key

```bash
python cloud/submit.py --selftest
```

Nine checks, each run against a deliberately broken input. Exits non-zero if any check fails to
discriminate. Run this first: it is the evidence that the other commands mean anything.

### 2. Ask Cloud which nodes it has — free, no credits

```bash
python cloud/submit.py --workflow workflows/reshoot_ltx25.json --check-nodes
```

This is the decisive test for "can this graph run here". It is a `GET /api/object_info`; it
generates nothing and spends nothing. It prints every `class_type` Cloud does not have, or
`ALL PRESENT`.

### 3. Inspect the plan locally — free, no network

```bash
python cloud/submit.py --workflow workflows/reshoot_ltx25.json --dry-run
```

Validates the file is API format and lists the class_types. Catches the common mistake of
submitting a UI-format graph.

### 4. Actually run it — **SPENDS CREDITS**

```bash
python cloud/submit.py --workflow workflows/reshoot_ltx25.json --submit --yes
```

`--submit` alone refuses to run; `--yes` is the second confirmation. Submits, polls to a terminal
state, and reports per-node outputs with sizes and download URLs.

Tuning: `--interval 5` (poll seconds), `--max-wait 1800` (give up after N seconds).

## What the tool does with failures

It never turns an error into a success. Specifically:

| Situation | Behaviour |
|---|---|
| **401** | prints `HTTP 401 -- UNAUTHORIZED -- invalid or missing API key` plus the server's own `code` and `message`; exit 2 |
| **429** | prints `HTTP 429 -- SUBSCRIPTION INACTIVE (or rate limited)`; exit 2 |
| **402** | prints `INSUFFICIENT CREDITS`; exit 2 |
| **`node_errors`** | prints the server's `node_errors` object and `traceback` verbatim; exit 1 |
| **`prompt_no_outputs`** | a job that reports `succeeded` with **zero outputs is reported as a failure**; exit 1 |
| **failed / expired / canceled** | prints the server's `error` object; exit 1 |
| **timeout** | says the job is *still running*, not failed and not succeeded, and prints the URL to re-poll; exit 1 |
| **UI-format input** | rejected before any network call, with the fix in the message; exit 2 |

Exit codes: `0` success with outputs · `1` the job ran and failed · `2` the request was never
made (bad key, bad file, missing confirmation).

## Surfaces

The same v2 API serves all three; only `--base` changes.

```bash
# Comfy Cloud (default)
python cloud/submit.py --workflow workflows/reshoot_ltx25.json --check-nodes

# a Comfy API deployment
python cloud/submit.py --base https://<deployment>.run.comfy.app --workflow ... --check-nodes

# a self-hosted ComfyUI behind the API proxy
python cloud/submit.py --base http://127.0.0.1:8189 --workflow ... --check-nodes
```

`COMFY_BASE_URL` sets the default base if you would rather not pass `--base`.

## Before spending anything

1. `--selftest` passes.
2. `--check-nodes` says `ALL PRESENT` for `reshoot_ltx25.json`.
3. **The models exist on Cloud.** `reshoot_ltx25.json` names
   `ltx-2.5-22b-distilled-transformer-bf16.safetensors`,
   `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors`, `ltx-2.5-video-vae-bf16.safetensors`,
   `ltx-2.5-audio-vae-bf16.safetensors` and
   `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors`. Cloud exposes a fixed model set;
   a missing checkpoint fails at load, after the credits are committed.
4. The spend is approved.

## What a green run would and would not prove

It would prove **the LTX 2.5 model path renders** — the loader block, the two-stage sampler chain
and the audio+video decode produce a real file on a real GPU. That is the first executed evidence
this project has.

It would **not** prove our graph works, because our graph is not what runs. The director, the
judge, the element registry and the grade are our nodes and are not on Cloud. Those remain
"structurally validated, not executed" until they run in local ComfyUI.

## API notes

- v2: `POST /api/v2/jobs` to submit, `GET /api/v2/jobs/{id}` to poll. `Authorization: Bearer <key>`.
- v1 (deprecated, still live): `X-API-Key`; `GET /api/object_info`, `GET /api/queue`, `GET /api/user`.
  `--check-nodes` uses v1's `object_info` because **v2 does not expose node definitions** — that is
  documented, not a guess: <https://docs.comfy.org/development/cloud/overview>
- Terminal statuses: `succeeded`, `failed`, `expired`, `canceled`.
- Output URLs are pre-signed and expire (roughly 6 hours). Download promptly.
