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
python -m pytest tests/ -q      # 884 tests, all hand-computed expected values
```

One test module needs numpy, because one node does. It is imported lazily inside
that node, so the pack still imports without numpy and only `CinemaGradeApply`
fails at execution time. The test module matches that tolerance with
`pytest.importorskip`, so on a stdlib-only interpreter you get
**804 passed, 1 skipped** rather than a collection error that hides the other 800.

**Name the interpreter when you quote a total.** 884 and 804 are the same tree: the
80-test difference is exactly `tests/test_nodes_grade_apply.py`, which is numpy-gated.
The skip is loud and carries its reason, not a silent zero.

The engine imports with **zero ComfyUI dependency** — that is a deliberate design constraint, so
the geometry is testable and reusable outside ComfyUI.

---

## The nodes

| Node | What it does |
|---|---|
| `CinematographerEvaluate` | Scores a camera + subject against the 9 per-shot rules. Returns a report, an overall pass, and a one-line summary. |
| `CinematographerAutoFrame` | Solves a camera pose for a shot type and intent. **Reports whether it actually converged.** |
| `ChorosContinuity` | Checks a shot list for 180°-axis breaks and sub-30° jump cuts. |
| `SceneFramingExtras` | The multi-entity rules: size = story importance, dirty-frame foreground, eyeline. |
| `CameraReliabilityZone` | Grades a requested angle against the view-steering model's trained envelope. |
| `CinematographerCorrection` | Turns a report into a plain list of correction levers. |

All JSON in, all JSON out — the nodes compose with anything.

---

## The rules — 14, honestly counted

The reference engine documents 38 cinematography rules. **Only 14 are machine-evaluated.** We
port the 14 and say so, because a rule you cannot measure is a rule you cannot enforce.

**Per shot (9):** `in_frame` · `rule_of_thirds` · `headroom` · `shot_size` · `lead_room` ·
`negative_space` · `camera_angle` · `level` · `direct_address`

**Per scene (3):** `size_importance` · `foreground_occlusion` · `eyeline`

**Across cuts (2):** `180_axis` · `30_degree`

Four of these are *informational* — they describe the frame's register (isolated, heroic,
down-the-lens) rather than judging it. The other ten carry weights, and a frame passes only when
every rule at weight ≥ 0.8 passes.

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

`web/` is a single-page panel that runs the same geometry in the browser: move the camera,
watch all nine rule values change live, hit Auto-Frame and see the solver's iteration count and
convergence badge. See [`web/README.md`](web/README.md) for how to run it and an explicit
list of what is mocked.

---

## The workflows

Six ready-to-load graphs live in [`workflows/`](workflows/):

| Graph | Stack | Licence |
|---|---|---|
| `cinema_studio_full.json` | The whole flow: Flux.1 [schnell] → Elements → Director → LTX 2.5 → judge → post | Apache-2.0 |
| `reshoot_ltx25.json` | LTX 2.5 (official two-stage distilled, flattened) | LTX Community |
| `reshoot_ltx_crossview.json` | LTX 2.3 + CrossView-Warp IC-LoRA + MoGe-2 | LTX Community / Apache-2.0 |
| `reshoot_ltx23_character.json` | As above, plus a character LoRA | LTX Community / Apache-2.0 |
| `reshoot_wan22_fun_control.json` | Wan 2.2 Fun-Control | Apache-2.0 |
| `character_lora_train.json` | Native ComfyUI LoRA training on the LTX 2.3 transformer | Apache-2.0 |

`cinema_studio_full.json` is the entry: it runs the five stages end to end and needs **no custom
node packs at all** beyond this one. The rest are the individual stacks, so you can swap the video
model under the same directorial controls.

All six are **structurally validated and none has been executed**:

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
