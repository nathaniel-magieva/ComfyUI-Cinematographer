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

What *can* be validated there is the **native LTX 2.5 model path**, and it now has been: on
2026-11-01 `reshoot_ltx25.json` ran end to end on Comfy Cloud and produced a 5.04 s 1920×1088 MP4.
Its audio track is present but **silent** — see [§ The run that actually
happened](#the-run-that-actually-happened).

## Two ways in

| | `submit.py` | `session_client.mjs` |
|---|---|---|
| auth | Comfy Cloud **API key** | a **logged-in browser session** |
| needs | `COMFY_API_KEY` | Chrome on a CDP port, logged into `cloud.comfy.org` |
| language | Python, stdlib only | Node, zero dependencies |
| status | the honest reference implementation | the fallback that turned out to be the only route available here |

**No Comfy Cloud API key exists on the machine this was built on.** API access also requires a paid
subscription. So the run described below went through the browser session instead. `submit.py`
remains the reference implementation and its `--check-nodes` and `--selftest` paths are both proven
green; `session_client.mjs` is what actually spent the credits.

## Setup

### With an API key

```bash
export COMFY_API_KEY=comfyui-...        # platform.comfy.org -> Profile -> API Keys
```

API access requires a **paid** Comfy Cloud subscription; the free tier does not include it.
An invalid key returns 401, a key on an inactive subscription returns 429.

### With a browser session

Start Chrome with a debug port, log into `https://cloud.comfy.org/`, and leave the tab open:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/comfy-cdp
```

```bash
node cloud/session_client.mjs check --graph workflows/reshoot_ltx25.json
```

`CDP_PORT` (default `9222`) and `COMFY_WORKSPACE_ID` are read from the environment. The workspace
header matters: on a multi-workspace account the credits live in one of them, and the wrong
`X-Comfy-Workspace-ID` spends from the wrong balance.

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

### 5. The same four steps, over a browser session

```bash
node cloud/session_client.mjs check    --graph workflows/reshoot_ltx25.json
node cloud/session_client.mjs submit   --graph workflows/reshoot_ltx25.json \
                                       --image assets/tamsin.png          # dry: no --yes
node cloud/session_client.mjs submit   --graph workflows/reshoot_ltx25.json \
                                       --image assets/tamsin.png --yes    # SPENDS CREDITS
node cloud/session_client.mjs poll     --prompt-id <uuid>
node cloud/session_client.mjs download --filename <hash>.mp4 \
                                       --subfolder cinematographer --out out.mp4
```

`submit` without `--yes` uploads, substitutes, and prints what it *would* send. It refuses outright
if any `CLIPTextEncode` still carries a `PLACEHOLDER_` prompt — a placeholder prompt generates
garbage silently, whereas a wrong image path fails loudly at run time, so only the former is fatal.

`download` mints the signed URL in the browser and moves the bytes in Node. It is the only route
that works, and it is verified: re-downloading the run above reproduces sha256
`bcdde13b…20fc` byte for byte.

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
   a missing checkpoint fails at load, after the credits are committed. **All five were confirmed
   present before the 2026-11-01 run** — 513 model options across the four loader classes.
   `--check-nodes` does **not** check model files; it checks node classes only.
4. The spend is approved.

## The run that actually happened

**2026-11-01, `cloud.comfy.org`, ComfyUI v0.43.2.** `reshoot_ltx25.json`, submitted through the
browser session with the real LTX 2.5 weights and no stubs:

| | |
|---|---|
| `prompt_id` | `07fca462-482e-401f-92b5-3a0109f606b0` |
| status | `status_str "success"`, `completed true`, `node_errors {}` |
| timing | `execution_start 1793564356463` → `execution_success 1793564401280` = **44.8 s** |
| cache | 11 nodes served from cache (the loaders and the noise/sampler/sigma nodes) |
| output | `cinematographer/reshoot_ltx25_00001_.mp4`, **844,021 bytes** |
| video | h264 **1920×1088**, 121 frames, 24 fps, 5.0417 s |
| audio | AAC-LC 48 kHz stereo, 236 frames — **present but silent** (`max_volume -78.3 dB`) |
| sha256 | `bcdde13bb1650e06141269e41fe7523856ae8e0a25132573a949bc242dbf20fc` |

The output is 1920×1088, not the 960×544 the latent was built at: `LTXVLatentUpsampler` (node 22)
doubled it, which is the two-stage distilled graph working as designed.

Before submitting, two things were checked and both were green: all **24** `class_type`s present in
Cloud's 3,858 node classes, and all **five** LTX 2.5 model files present in Cloud's catalogue.

### What this proves, and what it does not

It proves **the LTX 2.5 model path renders** — the loader block, the two-stage sampler chain and the
audio+video decode produce a real file on a real GPU. That is the first executed evidence this
project has, and it retires the "no frame of video has ever been rendered" caveat.

It does **not** prove our graph works, because our graph is not what runs. The director, the judge,
the element registry and the grade are our nodes and are not on Cloud. Those remain "structurally
validated, not executed" until they run in local ComfyUI.

It also does **not** prove the audio branch produces sound. The graph wires the full audio path —
`LTXVEmptyLatentAudio` → `LTXVConcatAVLatent` → `SamplerCustomAdvanced` → `LTXVSeparateAVLatent` →
`LTXVAudioVAEDecode` → `CreateVideo` — and that path **executed without error**, emitting a real
AAC-LC stream (48 kHz stereo, 236 frames, 127 kb/s). But the samples are the noise floor:
`ffmpeg -af volumedetect` reports **`mean_volume -90.3 dB`, `max_volume -78.3 dB`**. The stream is
present; it is silent. **An earlier revision of this file called that "native audio" on the strength
of the stream's presence — presence is not audibility, and the claim was wrong.** Why the audio
latent denoises to silence is **not yet known**: the two-stage distilled graph uses `ManualSigmas`
tuned for the video latent and `cfg: 1.0`, and whether the audio latent needs its own schedule or its
own conditioning is an open question. It is recorded as open, not guessed at.

## The four traps, if you take the session route

Each of these cost real time. They are in the header comment of `session_client.mjs` too.

1. **`X-Comfy-Client: web` on every call**, or 403 `origin_not_allowed`. A **403** (not a 401) is
   the proof a session is alive; a 401 `invalid session cookie` means it is dead.
2. **`X-CSRF-Token` on every write**, or 403 `csrf_invalid`. The token is at
   **`GET /api/auth/session`** → `csrf_token`. **Not `/auth/session`** — that path is served by the
   SPA's static handler and returns `index.html` with HTTP **200**, a silent false success.
3. **`POST /api/upload/image` returns a content-hashed filename**, not the one you uploaded. A graph
   naming `tamsin.png` fails with a missing-file error. The submitter must rewrite the `LoadImage`
   input to the returned name — that is the substitution the app is supposed to perform.
4. **`GET /api/view` answers 302 to a signed `storage.googleapis.com` URL.** A page-context `fetch`
   dies with `net::ERR_FAILED` because the GCS bucket sends no CORS headers on the redirect target,
   which reads exactly like a missing file and is not one. Harvest the `Location` at the **protocol**
   layer with `Fetch.enable {requestStage:'Response'}` — `Network.*` events never surface it — then
   fetch that URL from Node with **no cookie and no header**. The signature is the credential.

Two more that are easy to get wrong:

- **`/api/history` does not exist on Comfy Cloud.** It 404s and names its own replacement,
  `/api/history_v2`. A poll watching `/api/history` looks exactly like a poll watching a long run.
- **`/api/history_v2` returns `{"history": [ … ]}`** — an array under a key, not a prompt_id-keyed
  dict. Reading it as a dict yields `mine: null` and looks like the run is missing.

## API notes

- v2: `POST /api/v2/jobs` to submit, `GET /api/v2/jobs/{id}` to poll. `Authorization: Bearer <key>`.
- v1 (deprecated, still live): `X-API-Key`; `GET /api/object_info`, `GET /api/queue`, `GET /api/user`.
  `--check-nodes` uses v1's `object_info` because **v2 does not expose node definitions** — that is
  documented, not a guess: <https://docs.comfy.org/development/cloud/overview>
- Terminal statuses: `succeeded`, `failed`, `expired`, `canceled`.
- Output URLs are pre-signed and expire (roughly 6 hours). Download promptly.
