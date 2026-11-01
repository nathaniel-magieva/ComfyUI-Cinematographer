# Comfy Cloud validation — findings

**The question asked first, because it is load-bearing: does Comfy Cloud support custom nodes?**

## Answer: not yours. Comfy Org's curated set only — and that set includes LTXVideo.

Comfy Cloud runs a **fixed catalogue of node packs that Comfy Org maintains**. You cannot
install or upload your own. Two independent primary sources:

> **Q. Can I install or import my custom nodes on Comfy Cloud?**
> Not at the moment. Unlike ComfyUI Local, Comfy Cloud does not currently support direct
> installation of custom nodes by users. Cloud provides a managed environment to maintain
> compatibility and stability, so custom node uploads and environment customization are
> currently not supported.
>
> — <https://support.comfy.org/articles/6791455062-custom-nodes-on-cloud>

> Comfy Cloud runs a fixed set of custom nodes that Comfy maintains. **You cannot install your
> own node packs there**, so a workflow that depends on a pack Cloud does not include will not
> run as it is.
>
> Comfy Cloud flags the nodes it cannot run in two places: they are marked on the canvas, and
> the Errors tab of the right side panel lists them under **Unsupported Node Packs**.
>
> — <https://docs.comfy.org/get_started/cloud>

> **Q. Is Custom Nodes Manager available on Comfy Cloud?** No. Custom Nodes Manager is only
> available in local ComfyUI environments.
>
> — <https://support.comfy.org/articles/9321608144-installing-custom-nodes>

**`ComfyUI-Cinematographer` is not in that catalogue and cannot be added to it.** It is
unpublished, and the upload path does not exist even once published.

### The catalogue, measured

`https://comfy.org/cloud/supported-nodes/` was fetched and parsed (1,060,548 bytes). It lists
**89 custom packs** and **2,715 custom node types**. Core ComfyUI nodes are *not* on that page —
they are always present — so the page answers "which custom packs exist", not "which nodes exist".

**`ComfyUI-LTXVideo` (Lightricks) IS one of the 89 packs.** That matters, and it is the reason
this document does not simply say "nothing can be validated".

Do not confuse this with the unrelated **"Comfy Cloud nodes"** feature
(<https://docs.comfy.org/cloud-nodes/overview>): eight core `[BETA]` nodes that let a *local*
ComfyUI offload one fixed workflow to Comfy's GPUs. Not a way to run your own graph on Cloud.

---

## What that means for our six graphs — measured, per graph

Every `class_type` in every graph was classified against (a) the real ComfyUI core registry
(v0.43.0, `/tmp/ComfyUI`, `init_extra_nodes()` awaited → **1024 core nodes**), (b) our own
`NODE_CLASS_MAPPINGS` (**18 nodes**), and (c) Cloud's 2,715-node custom catalogue.

| graph | class_types | core | **ours** | on Cloud | unknown | verdict |
|---|---|---|---|---|---|---|
| `cinema_studio_full.json` | 50 | 32 | **18** | 0 | 0 | **BLOCKED** |
| **`reshoot_ltx25.json`** | **24** | **24** | 0 | 0 | 0 | **SUBMITTABLE** |
| `reshoot_ltx_crossview.json` | 28 | 25 | 0 | 0 | 3 | BLOCKED |
| `reshoot_ltx23_character.json` | 28 | 25 | 0 | 0 | 3 | BLOCKED |
| `reshoot_wan22_fun_control.json` | 17 | 16 | 0 | 0 | 1 | BLOCKED |
| **`character_lora_train.json`** | **9** | **9** | 0 | 0 | 0 | **SUBMITTABLE** |

"unknown" = not core, not ours, and not in Cloud's catalogue. Those three are `CrossViewWarp`,
`LTXAddVideoICLoRAGuide` and `LTXICLoRALoaderModelOnly` — the last two are LTXVideo nodes that
exist upstream but are **absent from Cloud's snapshot** of the pack.

### `cinema_studio_full.json` cannot be submitted

18 of its 50 class_types are ours. It would fail with `node type not found` on the first one the
server walks, and the UI would list the pack under *Unsupported Node Packs*:

```
CameraReliabilityZone      CinemaGrade                CinematographerAutoFrame
CharacterContinuity        CinemaGradeApply           CinematographerCorrection
ChorosContinuity           CinemaPromptCompose        CinematographerEvaluate
CinemaCameraMove           CinemaElementList          SceneFramingExtras
CinemaDirectorPanel        CinemaElementLoad
CinemaEdit                 CinemaElementSave
CinemaEmotionWheel         CinemaExtend
```

---

## The pivot: `reshoot_ltx25.json` is the graph to validate

**It uses 24 class_types and every one is ComfyUI core. Zero are ours. Zero are unknown.**

```
UNETLoader  CLIPLoader  VAELoader  LatentUpscaleModelLoader  LoadImage
LTXVConditioning  LTXVPreprocess  LTXVImgToVideoInplace  EmptyLTXVLatentVideo
LTXVEmptyLatentAudio  LTXVConcatAVLatent  LTXVSeparateAVLatent  LTXVAudioVAEDecode
LTXVLatentUpsampler  ManualSigmas  CFGGuider  SamplerCustomAdvanced  KSamplerSelect
RandomNoise  CreateVideo  SaveVideo  VAEDecodeTiled  ImageScale  CLIPTextEncode
```

That is the **native LTX 2.5 model path**, and as of **2026-11-01 it has been exercised**: the graph
ran end to end on Comfy Cloud and produced a 5.04 s 1920×1088 h264 MP4 with a native AAC track
(844,021 bytes, sha256 `bcdde13b…20fc`). Before that run, no frame of video had ever been rendered by
this project — everything was structurally validated, never executed. See
[`README.md` § The run that actually happened](README.md#the-run-that-actually-happened).

What that run did **not** exercise is our own nodes: the director, the judge, the element registry
and the grade are not on Cloud, so they remain structurally validated and locally unexecuted.

`character_lora_train.json` is also submittable (9 core class_types) but is a LoRA-training
graph; it is a different claim and a different cost profile.

### What validating it would and would not prove

| Surface | On Cloud? | Why |
|---|---|---|
| `cinema_studio_full.json` (94 nodes) | **No** | 18 of 50 class_types are our pack |
| `reshoot_ltx25.json` (34 nodes) | **Yes — and it ran** | 24/24 core; executed 2026-11-01, 44.8 s, produced an MP4 |
| `character_lora_train.json` (9 nodes) | **Yes** | 9/9 core |
| The other three reshoot graphs | **No** | use LTXVideo nodes absent from Cloud's snapshot |
| The judge / director / element engine | **No** | our pack; local ComfyUI only |

Validating `reshoot_ltx25.json` on Cloud proves **the model path renders** — that the LTX 2.5
loader block, the two-stage sampler chain and the audio+video decode produce a real file on a
real GPU. It does **not** prove our graph works, because our graph is not what runs. Those are
different claims and this document does not merge them.

### Two things that could still block it, both checkable for free — and both were checked

1. **Model availability.** Cloud exposes a fixed model set. `reshoot_ltx25.json` names
   `ltx-2.5-22b-distilled-transformer-bf16.safetensors`, `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors`,
   `ltx-2.5-video-vae-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` and
   `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors`. Whether Cloud has them is answered
   by `GET /api/object_info` — **no credits, no generation.** **Result: all five present**, out of
   513 model options across the four loader classes. Note that `--check-nodes` does *not* answer
   this: it checks node classes only.
2. **Core version drift.** Cloud's core is a snapshot. `StringContains`, `ComfySwitchNode` and
   `ComfyMathExpression` are core in local v0.43.0; whether Cloud has them is again answered by
   `object_info`. `submit.py --check-nodes` asks exactly this question. **Result: 24/24 present**
   in Cloud's 3,858 node classes.

A third blocker turned out to matter more than either: **there is no Comfy Cloud API key on this
machine**, and API access needs a paid subscription. The run went through a logged-in browser
session instead — see [`README.md`](README.md#two-ways-in).

---

## The official LTX 2.5 example workflows are not a shortcut

Enumerated live from `Lightricks/ComfyUI-LTXVideo@master`, `example_workflows/2.5/` (12 files)
plus `2.5/HDR_workflows/` (5 files) — **17 workflows, all fetched HTTP 200**.

**All 17 are UI graph format, not API format.** They carry a top-level `nodes` array and
`definitions.subgraphs`; none is a flat `node-id -> {class_type, inputs}` map. They must be
opened in the frontend and exported to API format before they can be POSTed, and the export must
expand subgraphs.

Across all 17, there are **85 distinct real node types** (excluding subgraph-instance UUIDs).
**29 of those are not ComfyUI core**, including `LTXICLoRALoaderModelOnly`,
`LTXAddVideoICLoRAGuide`, `LTXVInpaintPreprocess`, `LTXVLoadConditioning`, `LTXVDrawTracks`,
`LTXVLaplacianPyramidBlend`, `LTXVSparseTrackEditor`, `GemmaAPITextEncode` and
`TextGenerateLTX2Prompt`. Several of those are **absent from Cloud's LTXVideo snapshot**, so the
official examples are *not* a drop-in validation target.

The simplest official graph is `LTX-2.5_T2V_I2V_Single_Stage_Distilled.json` (18 top-level nodes,
5 subgraphs); the repo's own README labels its two-stage sibling "Start here".

**A caveat worth carrying forward:** the official T2V graphs are **not purely local by default**.
An `Input Parameters` subgraph contains a `StringContains` node titled *"has ltxv api key?"*
(needle `ltxv_`) feeding a `ComfySwitchNode`, plus two `GemmaAPITextEncode` nodes. The embedded
note says the workflow *"switches over on its own whenever a key is present — there is nothing to
un-bypass."* So a run intended to exercise the **native** path must confirm no `ltxv_*` key is
configured, or prompt encoding silently routes to the LTX API.

---

## Blockers

1. **No API key.** `COMFY_API_KEY` is not in the environment; `~/.nathanielhunter-credentials`
   holds email+password only. Nothing in `cloud/submit.py` can be exercised end-to-end until a
   key exists. **Verified live:** `GET https://cloud.comfy.org/api/object_info` with a bad key
   returns `HTTP 401 {"code":"UNAUTHORIZED","message":"Unauthorized"}`.
2. **API access needs a paid subscription.** Invalid key → 401; inactive subscription → 429.
3. **No spend without approval.** No generation call has been made. Credits are untouched.

## Reproduce

```bash
# Cloud's custom catalogue: 89 packs, 2715 nodes
curl -s -A "Mozilla/5.0" https://comfy.org/cloud/supported-nodes/ -o /tmp/cloud_nodes.html

# The four-way classification
cd /tmp/ComfyUI && /tmp/comfy-venv/bin/python - <<'EOF'
import sys, json, asyncio, re, html
sys.path.insert(0, '/tmp/ComfyUI'); import nodes
asyncio.run(nodes.init_extra_nodes(init_custom_nodes=False)); core = set(nodes.NODE_CLASS_MAPPINGS)
cloud = set(re.findall(r'"name":\[0,"([^"]+)"\]',
            html.unescape(open('/tmp/cloud_nodes.html', encoding='utf-8', errors='ignore').read())))
sys.path.insert(0, '/tmp/cine-publish'); import cinematographer; ours = set(cinematographer.NODE_CLASS_MAPPINGS)
for wf in ('cinema_studio_full', 'reshoot_ltx25'):
    g = json.load(open(f'/tmp/cine-publish/workflows/{wf}.json'))
    cts = {n['class_type'] for k, n in g.items() if k != '_README' and isinstance(n, dict)}
    print(wf, 'core', len(cts & core), 'ours', len(cts & ours),
          'cloud', len({c for c in cts if c not in core and c not in ours and c in cloud}),
          'unknown', len({c for c in cts if c not in core and c not in ours and c not in cloud}))
EOF
```

## Sources

- <https://support.comfy.org/articles/6791455062-custom-nodes-on-cloud> — custom nodes on Cloud
- <https://docs.comfy.org/get_started/cloud> — Cloud overview, Unsupported Node Packs
- <https://support.comfy.org/articles/9321608144-installing-custom-nodes> — Manager not on Cloud
- <https://comfy.org/cloud/supported-nodes/> — the curated catalogue (89 packs, 2715 nodes)
- <https://docs.comfy.org/development/cloud/overview> — v1 vs v2, auth, error codes
- <https://docs.comfy.org/cloud-nodes/overview> — the unrelated "Comfy Cloud nodes" feature
- <https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5> — 17 UI-format examples
