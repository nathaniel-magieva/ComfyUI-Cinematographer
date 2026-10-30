# ComfyUI-Cinematographer

**Every re-shoot tool asks you to aim a camera and hope. This one tells you the frame is wrong,
by how much, and which way to move — before you spend the render.**

A ComfyUI custom node pack that evaluates a camera setup against the rules a working
cinematographer actually uses, returns a **measured value and a correction lever in metres** for
each one, solves a compliant camera pose for you, and checks the 180° line across cuts.

Built for the [Comfy Org "Open Source Higgsfield"](https://comfy.org/open-source-higgsfield/)
build night.

---

## Why this is different

The ComfyUI ecosystem has plenty of camera *presets*. It has no camera *judgement*.

| What exists | What it gives you |
|---|---|
| `ComfyUI-CameraReference3D` | 17 camera-move **presets** + Plücker export |
| `WanCameraEmbedding` | 9 camera **presets** |
| `comfy-reshoot`'s reliability zone | A hard-coded green/yellow/red **indicator** |

None of them will tell you *"your headroom is 0.83, the medium-shot band is 0.10–0.45, raise the
target or push in."* That is the gap this pack fills. It is arithmetic, not a conditioning claim —
you can check every number by hand.

---

## Install

**As a ComfyUI custom node:**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nathaniel-magieva/ComfyUI-Cinematographer
# no dependencies — the engine is pure stdlib
```

Restart ComfyUI. The nodes appear under the **Cinematographer** category.

> **Why the clone target matters.** ComfyUI's loader does a **non-recursive** `os.listdir` over
> `custom_nodes/` and then loads `<pack_root>/__init__.py` by path. The pack root is therefore
> whatever directory you put in `custom_nodes/`, and it must contain `__init__.py` at its top
> level. This repository is laid out that way, so the clone above works unchanged. If you vendor
> the pack into a larger repository instead, point ComfyUI at the directory that holds
> `__init__.py`, not at its parent — a pack root without `__init__.py` fails at startup with
> `FileNotFoundError: '<dir>/__init__.py'`.
>
> Verified by replaying ComfyUI's exact loader (`os.listdir` with no recursion, then
> `spec_from_file_location(pack_root/__init__.py)`) against a clean copy: 18 nodes load.

**To run the tests (no ComfyUI required):**

```bash
python -m pytest tests/ -q      # 918 tests, all hand-computed expected values
```

One test module needs numpy, because one node does. It is imported lazily inside
that node, so the pack still imports without numpy and only `CinemaGradeApply`
fails at execution time. The test module matches that tolerance with
`pytest.importorskip`, so on a stdlib-only interpreter you get
**816 passed, 23 skipped** rather than a collection error that hides the other 800.

**Name the interpreter when you quote a total.** 918, 896 and 816 are the same tree:
the 80-test difference between 816 and 896 is exactly `tests/test_nodes_grade_apply.py`,
which is numpy-gated, and the remaining 22 are the ComfyUI-, server- and proxy-gated
modules. The skip is loud and carries its reason, not a silent zero.

| Interpreter | Result | Why |
|---|---|---|
| stdlib only | **816 passed, 23 skipped** | no numpy, so the 80 grade-apply tests skip whole; plus the 22 gated below |
| with numpy | **896 passed, 22 skipped** | the grade-apply tests run; the 22 gated ones still skip |

**Nine of those tests drive ComfyUI's real execution engine.** They are gated on
`COMFYUI_PATH` and skip with a specific reason when it is unset, when the path is not a
ComfyUI checkout, or when `torch` is missing — so a green run is never mistaken for
"the pack was executed". To run them:

```bash
COMFYUI_PATH=/path/to/ComfyUI python -m pytest tests/test_comfy_execution.py -q
```

They boot ComfyUI's own loader, build a graph with `GraphBuilder`, run it through
`execution.PromptExecutor`, and read the values back out of the executor cache. That is
the only test here that would catch a node whose declared inputs and callable signature
disagree, or a JUDGE→POST edge that is wired but carries nothing.

One of the nine is different in kind: it drives `CinemaGradeApply` — the only node in the
pack that touches pixels — with a real tensor, through the engine, and asserts the output
is *not* equal to the input. Every other test in this file moves strings and booleans, so
without it the one path a user actually sees was unproven. Its image source is
`EmptyImage`, which needs no weights: every shipped graph stops at a model loader on a
machine with no checkpoints, so a weight-free source is the only way to reach the pixel
path headlessly. It lives here rather than in `test_nodes_grade_apply.py` because that
module needs numpy at import time and collects zero tests without it, whereas this file
must stay importable under the stdlib interpreter.

**Eight more drive a live ComfyUI server over HTTP** — the way a user actually runs the
pack. They are gated on `COMFYUI_URL`:

```bash
# in one shell
cd /path/to/ComfyUI && python main.py --cpu --port 8188
# in another
COMFYUI_URL=http://127.0.0.1:8188 python -m pytest tests/test_live_server.py -q
```

They import nothing from ComfyUI. They `GET /object_info` to see what registered,
`POST /prompt` to submit, and `GET /history/<id>` to read the result. Measured against
ComfyUI 0.43.0: **18/18 nodes registered under category `Cinematographer`**, the
JUDGE→POST gate returns `status_str: success` with the Judge's correction text arriving
in the Grade node's JSON **verbatim**, the Director→Shoot path composes a real prompt
with `#dolly-in` resolved and zero unresolved tags, and a malformed input fails with an
error that names the pack rather than passing silently.

> **One thing a user must know, found by running this.** A live server rejects a prompt
> that contains only our judgement nodes:
> `{"error": {"type": "prompt_no_outputs", "message": "Prompt has no outputs"}}`.
> `CinemaElementSave` is the pack's only `OUTPUT_NODE`, and it is one for its *side
> effect* — it writes an Element into the registry — not for display. Every other node
> is pruned unless something consumes it. **Terminate a Cinematographer graph in a stock
> output node** (`PreviewAny`, `SaveImage`, …). This is correct ComfyUI behaviour and
> true of most packs; it is stated here because it is the first thing that will bite
> someone who wires up our nodes and hits Queue Prompt.

**Five more drive the pack through the official Comfy API v2 proxy.** Comfy Org ships two
MIT pieces that together let SDK code written for Comfy Cloud drive a *self-hosted*
ComfyUI — `@comfyorg/sdk` (the client) and `comfy-api-proxy` (the server). The SDK's own
source says the self-hosted path needs no key:

```js
// COMFY_BASE_URL=http://127.0.0.1:8189 in the environment targets a
// self-hosted proxy instead, where no key is needed.
```

That claim is about *their* client talking to *a* ComfyUI. These tests check the part that
matters to us: that the thing on the other end can be **this pack**. They are gated on
`COMFYUI_URL` *and* `COMFY_PROXY_URL`:

```bash
# in one shell
cd /path/to/ComfyUI && python main.py --cpu --port 8188
# in another
pip install comfy-api-proxy
comfy-api-proxy --comfyui http://127.0.0.1:8188 --port 8189
# in a third
COMFYUI_URL=http://127.0.0.1:8188 COMFY_PROXY_URL=http://127.0.0.1:8189 \
  python -m pytest tests/test_api_v2_proxy.py -q
```

Measured against ComfyUI 0.43.0 + `comfy-api-proxy` 0.1.6: **5 passed**. A graph of
nothing but Cinematographer nodes (`CinemaDirectorPanel` → `CinemaPromptCompose` →
`CinematographerEvaluate` → `CinematographerCorrection`, plus three `PreviewAny` taps) is
submitted to `POST /api/v2/jobs`, and the values come back out of ComfyUI's own
`/history` — the composed prompt, the `FAIL medium on 'Tamsin'` verdict, and the three
correction levers. One test also asserts the proxy round-trips our graph **unchanged**,
so nothing silently rewrites our inputs on the way through.

> **Two traps, both found by running this.**
>
> **The proxy reports `status: "succeeded"` with `outputs: []` for a job whose nodes ran
> perfectly.** `outputs` is built from ComfyUI's viewable artifacts (images, video), and
> this pack returns plain `STRING`/`BOOLEAN`. Reading `outputs` alone says "nothing
> happened", which is false — the values are in ComfyUI's `/history`. One test pins that
> behaviour deliberately, so that if the proxy ever starts surfacing text outputs the
> test fails loudly rather than leaving this paragraph stale.
>
> **The proxy's terminal success string is `succeeded`, not `success` or `completed`.**
> A poll loop testing for ComfyUI's native vocabulary never terminates. The proxy is a
> different surface with its own status words.

The engine imports with **zero ComfyUI dependency** — that is a deliberate design constraint, so
the geometry is testable and reusable outside ComfyUI.

---

## The nodes

**18 nodes, in five groups.** The first six are the judgement engine; the rest carry the
five stages of the flow around it.

**Judge — the framing arithmetic**

| Node | What it does |
|---|---|
| `CinematographerEvaluate` | Scores a camera + subject against the 9 per-shot rules. Returns a report, an overall pass, and a one-line summary. |
| `CinematographerAutoFrame` | Solves a camera pose for a shot type and intent. **Reports whether it actually converged.** |
| `CinematographerCorrection` | Turns a report into a plain list of correction levers. **This is the JUDGE→POST gate.** |
| `ChorosContinuity` | Checks a shot list for 180°-axis breaks and sub-30° jump cuts. |
| `SceneFramingExtras` | The multi-entity rules: size = story importance, dirty-frame foreground, eyeline. |
| `CameraReliabilityZone` | Grades a requested angle against the view-steering model's trained envelope. |

**Stage 1 BUILD / 2 ATTACH — Elements**

| Node | What it does |
|---|---|
| `CinemaElementSave` | Register an asset as a named, categorised, reusable Element. **The pack's only `OUTPUT_NODE`.** |
| `CinemaElementLoad` | Resolve an Element by name back to its record. |
| `CinemaElementList` | Enumerate the project's Elements, so a graph can be built against a registry. |
| `CharacterContinuity` | Identity continuity: did the character's appearance survive the cut? |

**Stage 3 DIRECT**

| Node | What it does |
|---|---|
| `CinemaDirectorPanel` | The director's panel: five groups, each on `auto` or set. |
| `CinemaEmotionWheel` | One character's emotion and intensity, as a direction. |

**Stage 4 SHOOT**

| Node | What it does |
|---|---|
| `CinemaPromptCompose` | Assemble the prompt from the action, panel, Elements and moves. Resolves `@` and `#` tags. |
| `CinemaCameraMove` | Resolve the `#move` tags in a prompt against the engine's move list. A **parallel** resolver, not a filter. |

**Stage 5 POST**

| Node | What it does |
|---|---|
| `CinemaGrade` | Describe a colour grade as a plan of per-parameter deltas. |
| `CinemaGradeApply` | Apply a grade plan to an image. The one POST node that touches pixels. |
| `CinemaExtend` | Plan a Sequel or Prequel continuation of a shot. |
| `CinemaEdit` | Plan a regional edit: a labelled NDC box plus the instruction. |

All JSON in, all JSON out — the nodes compose with anything.

> **`CinemaCameraMove.moves` is JSON; `CinemaPromptCompose.moves` wants comma- or
> newline-separated names.** Linking them is type-legal (`STRING` to `STRING`) and
> semantically wrong, so the shipped graph does **not** link them. `CinemaPromptCompose`
> resolves `@`/`#` itself from `action`; `CinemaCameraMove` is a parallel resolver that
> reports what it found. Both read the same text, and every output of both is exposed on a
> `PreviewAny`, so a disagreement is visible rather than inferred.

---

## The rules — 9 per frame, 14 in total, honestly counted

The reference engine documents 38 cinematography rules. **Only 14 are machine-evaluated, and
only 9 of those are per-frame.** We port the 14 and say so, because a rule you cannot measure
is a rule you cannot enforce.

**Per frame (9):** `in_frame` · `rule_of_thirds` · `headroom` · `shot_size` · `lead_room` ·
`negative_space` · `camera_angle` · `level` · `direct_address`

**Per scene (3):** `size_importance` · `foreground_occlusion` · `eyeline`

**Across cuts (2):** `180_axis` · `30_degree`

Three of the nine per-frame rules are *informational* — they describe the frame's register
(isolated, heroic, down-the-lens) rather than judging it. The other six per-frame rules carry
weights, as do the 3 scene rules and the 2 continuity rules; a frame passes only when every
rule at weight ≥ 0.8 passes.

> **Say "9" for per-frame.** 14 is a legitimate total *across three families*, but it is wrong
> as a per-frame count — the 3 scene rules and the 2 continuity rules are not evaluated on a
> single frame. When the fuller picture is needed, state the parts separately: "9 framing rules
> per frame, plus 2 sequence-level continuity rules and 3 multi-entity scene rules." Never fold
> them into a single "14" as if per-frame, and never claim 38.

---

## The convergence fix

The reference solver this pack ports runs **exactly 24 iterations and returns the 24th iterate
unconditionally** — no convergence test, no early exit, no guarantee the result passes.

This port adds an early exit on success, a `converged` flag, the iteration count actually used,
and the residual when it does not converge. On the reference fixture it converges in **3
iterations** and says so. When it cannot converge, it returns `converged: False` and names the
rules still failing rather than handing you a pose that looks solved.

That difference is the point: a guarantee beats a number.

---

## The model stack — licence-clean by construction

| Role | Model | Licence |
|---|---|---|
| Core video | **LTX 2.3** | LTX-2.x Community (free under $10M revenue) |
| View steering | **CrossView-Warp** | Apache-2.0 |
| Depth | **MoGe-2** | open |
| Zero-caveat alternative | **Wan 2.2** (Fun-Control) | **Apache-2.0** |

**We deliberately do not use MiniMax H3.** It has open weights, but the **United States is an
excluded territory** and local commercial use requires a $5,000/month licence. Both reference
apps in this competition depend on it. We ship a path that does not.

---

## The director's panel

`web/` is a single-page panel with six tabs covering all five Cinema Studio stages — Director,
Judge, Elements, Shoot, Post, and **Run**. It runs the same geometry in the browser: move the
camera, watch all nine rule values change live, hit Auto-Frame and see the solver's iteration
count and convergence badge.

**The Run tab actually drives ComfyUI.** It builds a real API-format prompt from the panel's
current state, POSTs it to a server (default `http://127.0.0.1:8188`), polls `/history`, and
renders what the engine returned — including a byte-for-byte comparison of the server's framing
verdict against the panel's own mirror. With no server running it still shows the complete prompt
JSON so you can paste it into ComfyUI by hand, and it says on screen that nothing was sent.

```bash
# in one shell
cd /path/to/ComfyUI && python main.py --cpu --port 8188 --enable-cors-header
# in another
cd web && python3 -m http.server 8765     # then open http://127.0.0.1:8765/
```

`--enable-cors-header` is required for the browser to POST across ports.

> **A 200 with a `prompt_id` is not a clean bill of health.** ComfyUI validates a COMBO by exact
> membership, and when a node fails validation it is **dropped along with everything downstream**
> — while the server still answers `HTTP 200`, returns a `prompt_id`, and reports
> `status_str: "success"`. The only trace is `node_errors` in the response body. The Run tab
> surfaces that and refuses to call a partial run clean. This was found the hard way: the panel
> was sending the emotion as `"sadness"` where the node's combo wants `"Sadness"`.

See [`web/README.md`](web/README.md) for how to run it and an explicit list of what is mocked.
**No image and no video are generated by the panel** — the graph terminates in stock `PreviewAny`
taps, which render text, and `CinemaGradeApply` has no `IMAGE` to consume.

---

## The workflows

Six ready-to-load graphs live in [`workflows/`](workflows/):

| Graph | Stack | Licence | Extra packs needed |
|---|---|---|---|
| `cinema_studio_full.json` | The whole flow: Flux.1 [schnell] → Elements → Director → LTX 2.5 → judge → post | Apache-2.0 | **none** |
| `reshoot_ltx25.json` | LTX 2.5 (official two-stage distilled, flattened) | LTX Community | **none** |
| `reshoot_ltx_crossview.json` | LTX 2.3 + CrossView-Warp IC-LoRA + MoGe-2 | LTX Community / Apache-2.0 | `cseti007/ComfyUI-CrossViewWarp` |
| `reshoot_ltx23_character.json` | As above, plus a character LoRA | LTX Community / Apache-2.0 | `cseti007/ComfyUI-CrossViewWarp` |
| `reshoot_wan22_fun_control.json` | Wan 2.2 Fun-Control | Apache-2.0 | `cseti007/ComfyUI-CrossViewWarp` |
| `character_lora_train.json` | Native ComfyUI LoRA training on the LTX 2.3 transformer | Apache-2.0 | **none** |

`cinema_studio_full.json` is the entry: it runs the five stages end to end and needs **no custom
node packs at all** beyond this one. The rest are the individual stacks, so you can swap the video
model under the same directorial controls.

> **Read the last column before you load a graph.** Three of the six reference `CrossViewWarp`
> (and two of those also `LTXAddVideoICLoRAGuide` / `LTXICLoRALoaderModelOnly`), which live in
> **`cseti007/ComfyUI-CrossViewWarp`** — a third-party pack that is *not* vendored here. Load one
> without it and ComfyUI refuses the prompt with
> `missing_node_type: ... The custom node may not be installed.` That is measured, not inferred:
> see the audit below. `cinema_studio_full.json` and `reshoot_ltx25.json` need nothing extra.

**Measured against a live server.** POSTing each graph to `/prompt` makes ComfyUI validate every
`class_type` before it runs anything, which answers "what would I have to install?" precisely:

| Graph | Live-server verdict |
|---|---|
| `cinema_studio_full.json` | **HTTP 200 — accepted, queued, and `status_str: success`.** Every class_type registered. |
| `reshoot_ltx25.json` | all class_types registered; rejected on missing model files and a placeholder image |
| `reshoot_ltx_crossview.json` | **`missing_node_type`** — `CrossViewWarp`, `LTXAddVideoICLoRAGuide`, `LTXICLoRALoaderModelOnly` |
| `reshoot_ltx23_character.json` | **`missing_node_type`** — the same three |
| `reshoot_wan22_fun_control.json` | **`missing_node_type`** — `CrossViewWarp` |
| `character_lora_train.json` | all class_types registered; rejected on missing model files and an absent `character_refs` folder |

**Read that `success` carefully — it is not "the graph ran".** A live server *prunes* every branch
that does not reach an output node, and with no weights on the machine it pruned all ten loaders,
both `KSampler`s, both `VAEDecode`s, `SaveImage` and `SaveVideo`. What ran was the diagnostic
branch: our own nodes, tapped by `PreviewAny`. Their values came back over HTTP, measured:

| Node | Value returned by the live server |
|---|---|
| `CinematographerEvaluate` | `PASS medium on 'Tamsin' \| lead_room=-0.286` |
| `CinematographerCorrection` | `lead_room: flip composition: leave space in the direction the subject faces` |
| `CinemaGrade` | `grade: 5 delta(s) - temperature up 0.000->0.150, contrast up 0.000->0.100, …` |
| `CinemaDirectorPanel` | `genre epic, era 1980s, pacing calm, camera 35mm-film, lens anamorphic, … @tamsin Joy 0.5` |
| `CinemaCameraMove` | `["helicopter-shot"]` |
| `CinemaPromptCompose` | `[]` — zero unresolved tags |

> **A measurement trap worth knowing, because it nearly produced a false claim here.**
> `history.outputs` lists only nodes that produced **UI** output. Our nodes return plain
> `STRING`/`BOOLEAN` values, so they never appear as keys — a naive count of that dict reads
> "0 of our 19 node instances ran", which is **false**. They ran; their results are visible only
> through the `PreviewAny` taps. Count executions from the server log, not from `outputs`.

Two of the rejections are worth calling out because they are *our* loose ends, not the user's:
`reshoot_ltx25.json` carries a literal `PLACEHOLDER_SET_BY_THE_APP.png` in a `LoadImage`, and
`character_lora_train.json` expects an input folder named `character_refs` that nothing creates.
Both are deliberate placeholders for an app to fill in, and both will stop a user who loads the
graph by hand. They are listed here rather than hidden.

All six are **structurally validated**. What has actually been *executed* is narrower, and the
difference is worth stating precisely:

| Graph | Executed? | Where it stops |
|---|---|---|
| `cinema_studio_full.json` | **yes — two ways** | headless: 25 of 94, at `VAELoader` (no `vae/ae.safetensors`); live server: the weights branches are pruned, our nodes run |
| the five `reshoot_*` / `character_lora_train.json` | **no** | never run |

`cinema_studio_full.json` was driven through ComfyUI 0.43.0's real execution engine. It runs 25 of
its 94 nodes and halts at the first node that needs a checkpoint file. **10 of our 19 node instances
execute** before that point. Stubbing the ten model loaders moves the boundary to **50 of 94**, where
it stops at `KSampler` because a stub has no `get_model_object` — a missing-weights stop, not a
wiring defect. That is the honest boundary of this repository: the code runs, the weights are absent.

The same graph was then submitted to a **live server**, which behaves differently and is worth
stating separately: it *prunes* rather than forcing execution, so the weights branches never start
and our nodes run on their own. Same graph, same machine, two different honest answers — see the
live-server table above for the values it returned.

The other five graphs have **never been executed** and no claim here should be read as one.

Separately from the shipped graphs, the pack itself has been driven through a **live ComfyUI
server** over HTTP — `POST /prompt`, `GET /history` — with a graph of our own nodes. That run
needs no weights and completes: the Judge measures a frame, the Correction node turns the
failures into levers, and the Grade node receives that text verbatim. See
`tests/test_live_server.py` and the section above.

```bash
python workflows/validate_graphs.py
```

That proves valid JSON, `class_type` + `inputs` on every node, every link resolving to a real node
id and a declared output slot, and acyclicity. It does **not** prove ComfyUI accepts the prompt,
that the node packs and weights are installed, or that a clip comes out. Each graph carries a
`_README` node stating exactly what is and is not verified — read it before trusting the graph.

---

## Honest limitations

- **14 rules, not 38.** The perceptual rules need a vision model and are out of scope.
- **The solver does not always converge**, and says so when it does not.
- **`size_importance` uses role-derived entity half-extents**, not the reference engine's full
  dimension resolver — the comparison is right, the absolute areas are approximate.
- **The workflow graphs are unverified against a live ComfyUI** unless their `_README` node says
  otherwise. Read that node before trusting a graph.
- **The reliability envelope (±45° azimuth)** is CrossView-Warp's documented trained range. It is
  a model property, not a law of physics.

---

## Licence

Apache-2.0. See [LICENSE](LICENSE).
