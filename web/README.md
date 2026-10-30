# Director's Panel

A single-page panel with two tabs, because the entry has two halves:

- **Director** *(default)* — the **pre**-generation control surface. Five control groups, a prompt box
  with live `@Element` / `#move` resolution, a generation bar with a real credit cost, and a pane
  showing **exactly what would be sent**. It composes a plan. It does not generate anything.
- **Judge** — the **post**-generation measurement surface. Move the camera and watch all nine
  per-shot cinematography rules recompute live: measured value, pass/fail, and the correction lever
  for every one. Press **Auto-Frame** and the solver moves the camera for you, reporting honestly
  whether it converged.

No build step. No framework. No backend.

```bash
cd web
python3 -m http.server 8765
# open http://127.0.0.1:8765/
```

A static server is required (not `file://`) because the panel is an ES module, and browsers block
module imports from `file://`.

---

## Why the pairing is the entry

Re-shooting a subject from a chosen angle is **not novel**. Other entries in this competition already
do it in image space, and one ships a Cinema Studio tab of its own. What none of them does is
*measure* the result.

So the claim here is narrow and checkable: the **Director** tab *sets* the parameters, and the
**Judge** tab *measures* whether the result obeyed them — nine rules, a pass/fail per rule, and a
correction in metres. Setting is commodity. Verifying is the entry.

---

## The Director tab

Every option list is imported from [`director.js`](director.js) at runtime. **Nothing is hand-typed in
the HTML**, so there is exactly one place to fix when an enum changes, and the parity check can prove
the lists have not drifted.

| Group | Control | Source |
|---|---|---|
| Film setup | genre, era, tempo | API enum (`genre`, `era`, `pacing`) |
| Camera | body, lens, aperture | API enum (`camera_model`, `camera_lens`, `camera_aperture`) |
| Camera movement | 33 named moves, **stackable and ordered** | API enum (`camera_movement`) |
| Lighting | 6 documented looks | API enum (`light`) |
| Colour palette | 50 named palettes | API enum (`color_palette`) |
| Emotion wheel | 9 names + continuous intensity | UI-sourced; **no API field exists** |

Plus a **prompt box** where `@Element` and `#move` resolve live (resolved tags render as chips,
unresolved ones flag red with a spelling suggestion), and a **generation bar**: duration 4–30 s,
resolution, aspect ratio, native-audio toggle, and the credit cost on the Generate button.

### `auto` means "omit the field", not "send the string auto"

The API reference is explicit: *"Omit creative-control fields to let the director choose them
automatically; the literal value `auto` is not accepted for these enum fields."* The panel models
that literally — every group defaults to Auto, and the plan pane lists those fields under **Omitted
(auto)** rather than putting `"auto"` in the parameter block.

### `@` and `#` are the app's syntax, not the API's

The API's own reference tokens are `<<<image_1>>>`-style. The plan pane shows that translation
(`@tamsincamp` → `<<<image_1>>>`, with the attachment list beside it) because it is the step the
tutorials keep skipping. Moves are appended as `#` tags **in stack order** — that ordering is the
whole point of the panel.

### Focal length is ours, not 4.0's

Cinema Studio 4.0 **dropped focal length**. It was one of the three original 1.0 controls and is still
named in the 2.0/3.5 material, but it is absent from the 4.0 settings reference, the help-centre
walkthrough, and the API schema — 4.0 ships four bodies and five lenses with no focal control. This
engine keeps it first-class, so the Director tab exposes it and says so.

It is therefore **not an API field**. The plan puts it in a separate **engine extension** block, never
in the parameter block, because sending it as if the contract accepted it would misrepresent the
contract. `FOCAL_LENGTH_DROPPED_IN_4_0` records the finding in both the JS and Python engines.

### The cost readout is a real published table

The credit model is `credits = duration_seconds × rate(resolution)`, with rate **3 / 7 / 16** for
480p / 720p / 1080p. Those rates are derived from — and reproduce with **zero residual** — all nine
cells of the published credit table (native audio on, 16:9, priced 2026-10-24):

| duration | 480p | 720p | 1080p |
|---|---|---|---|
| 10 s | 30 | 70 | 160 |
| 15 s | 45 | 105 | 240 |
| 30 s | 90 | 210 | 480 |

The 1080p tier also carries the documented limited-time launch discount (480 → 360 at 30 s), shown as
a struck list price beside the current one — the same two-number pattern the product's own Generate
button uses.

Caveats the panel states on screen rather than hiding:

- the table covers only 10 / 15 / 30 s; other durations are linearly interpolated from a model that is
  exact at all three published points;
- the table is a 16:9 frame — no rate is published for the other five aspect ratios;
- the table is native-audio-**on**; whether audio off reduces cost is **not sourced**, so the cost is
  unchanged here;
- the dollar figure is a secondary estimate at the monthly Plus rate.

---

## The one thing that matters: the numbers are real

Every value on screen — all nine rule measurements, the weights, the overall verdict, the solver's
pose and convergence flag, the continuity verdicts, the reliability zone — is computed by
[`cinematographer.js`](cinematographer.js), a line-by-line JavaScript mirror of the Python engine in
[`../cinematographer/`](../cinematographer/). The Python engine is itself a port of a production
cinematography engine.

**A panel whose numbers disagree with the engine is worse than no panel**, so the mirror is proven,
not asserted:

```bash
# from the repository root
python3 app/web/parity_check.py
```

```
Cinematographer parity check
  fixtures      : app/web/parity_fixtures.json
  generated     : 2026-10-30T03:41:12+00:00 (engine rev unknown)
  engine hash   : d93581b30ce0a7c1…  (matches live engine)
  JS engine     : web/cinematographer.js (node v24.18.0)
  Python engine : cinematographer/ (importable)

[1/3] JS vs frozen fixtures
  framing      12/12 OK
  continuity   4/4 OK
  reliability  7/7 OK
  autoframe    5/5 OK
  director     21/21 OK

[2/3] Python engine vs frozen fixtures
  framing      12/12 OK
  continuity   4/4 OK
  reliability  7/7 OK
  autoframe    5/5 OK

[3/3] Python engine vs JS (live)
  framing      12/12 OK
  continuity   4/4 OK
  reliability  7/7 OK
  autoframe    5/5 OK

[4/4] Director's Panel — engine enums vs the API lists
  engine lists compared against the frozen API enums

FINDINGS — not failures, but do not let them go quiet:
    camera_movement: engine ships 9 of 33 (24 missing); engine declares TOTAL=33 …
    color_palette: engine ships 8 of 50 (42 missing); engine declares TOTAL=50 …
    aspect_ratio: the engine has no constant for this enum (6 API values are unmodelled)
    resolution: the engine has no constant for this enum (2 API values are unmodelled)

RESULT: PASS — 49 fixtures, 0 mismatches
```

**This check must pass.** It is the panel's contract with the engine. It compares four ways:

1. the JS mirror against the frozen fixtures,
2. the Python engine against the same fixtures,
3. the Python engine against the JS mirror, live, field by field,
4. the Director tab's enums against the engine's own constants.

Numeric tolerance is `1e-9`; camera poses are compared at `1e-6`. It exits non-zero on any mismatch,
on a structural problem (fewer than five framing fixtures, or a fixture without all nine rules), and
on **stale fixtures** — the fixture file records a sha256 over the six engine modules, and the checker
recomputes it, so an engine edit cannot silently invalidate the proof.

If you change the engine, re-freeze and re-check:

```bash
python3 app/web/tools/gen_fixtures.py && python3 app/web/parity_check.py
```

The fixtures are generated by the Python engine, never hand-written. Two of them
(`go-test-centered-closeup`, `go-test-offset-closeup`) reproduce the poses in the reference engine's
own test suite, so the chain traces back past the Python port to the reference implementation.

### Findings are not failures — and they are not silence

The Director section distinguishes two things that look alike:

- an engine enum member the API **does not have** is an **invented value** → a **failure**;
- an engine that ships a **documented subset** of an enum is **incomplete, not wrong** → a **finding**,
  printed loudly with the shortfall.

Failing on the second would push the next person to pad the list to make the check green. Padding is
the failure mode this project forbids, so the check reports the shortfall and stays green.

The four current findings are real and unresolved:

- `prompt.CAMERA_MOVES` ships **9 of 33** moves (`CAMERA_MOVES_TOTAL = 33` declares the rest);
- `director.COLOUR_PALETTES` ships **8 of 50** (`COLOUR_PALETTES_TOTAL = 50`);
- the engine has **no constant** for `aspect_ratio` or `resolution`.

The panel itself carries the full 33 and 50, transcribed from the captured API reference. The engine's
partial lists are a deliberate, documented choice by their author; the disagreement is surfaced here
rather than resolved by picking one.

### The Director tab's enums are anchored to a source outside this repo

`tools/gen_fixtures.py` re-reads the captured API reference and verifies its frozen lists against it
whenever that capture is on disk, so the fixtures are not self-certifying. If the capture is missing,
the generator says so instead of quietly trusting itself.

---

## What is real, and what is mocked

Read this section before believing anything on screen.

### Real — computed from the same geometry as the engine

| On screen | Where it comes from |
|---|---|
| All 9 rule measurements, pass/fail, weights | `evaluateFraming()` — the same function the Python engine runs |
| Overall PASS/FAIL | every rule with `weight >= 0.8` must pass (`OVERALL_PASS_WEIGHT`) |
| Correction levers on failing rules | the engine's own `correction` strings |
| Auto-Frame solved pose + `converged` / `iterations` / `residual` | `autoFrameCamera()` — the solver, with the convergence check the reference implementation lacked |
| Continuity `180_axis` / `30_degree` verdicts | `evaluateContinuity()` |
| Reliability zone (green/yellow/red) | `cameraReliabilityZone()` |
| Frame preview geometry, headroom band, NDC readouts | `projector()`, `headroomBand()` |
| Node I/O JSON panes | the literal `to_dict()` shapes the ComfyUI nodes emit |
| Director: every option list | `director.js`, cross-checked against the engine by the parity check |
| Director: the credit cost | the published credit table, reproduced exactly (see above) |
| Director: `@`/`#` resolution and the composed prompt | `parsePrompt()` / `composePrompt()` — pure string work, no model |

The panel is honest about the solver in a way the reference implementation was not: its
`AutoFrameCamera` returned its 24th iterate unconditionally. This one reports `converged: false` and
the residual when it does not converge, and the badge turns red rather than showing a pose that merely
looks solved.

### Mocked, stubbed, or simply not wired

| Thing | Status |
|---|---|
| **Video generation** | **Not wired to a live ComfyUI at all.** Neither tab generates anything. There is no LTX, no CrossView-Warp, no MoGe-2, no depth pass, no render. The Generate button is **disabled** and says so. |
| **The Director tab's plan** | It is a plan, not a request. Nothing is sent anywhere; there is no network call in the panel. |
| **The Element registry** | Three demo Elements (`@tamsincamp`, `@the-diner`, `@chrome-revolver`) so the `@` mechanism is visible with nothing wired up. Not loaded from a project. |
| **The emotion wheel** | 9 names, being the union of the on-screen wheel and the settings reference (they differ by `Interest` vs `Hope`). The wheel is visibly larger than its visible arc, so this is a floor. One tutorial claims 80 emotions across three strength levels; that is unverified and not implemented. |
| **Emotion intensity** | Continuous 0–1. The evidence claims three strength levels but **no strength control was legible in any frame**, so the cut points are unknown — the three words on screen are descriptors on the scale, not enum members. |
| **The subject** | A synthetic figure at a fixed world position (base `(0,0,0)`, height 1.75 m, facing yaw 0). There is no clip, no frame, and no depth analysis — nothing was measured from footage. |
| **The 3D viewport** | An *illustration*, not a render. The subject is a capsule and a sphere; the frustum is a three.js `CameraHelper`. It shows you where the camera is, not what it sees. |
| **The continuity strip** | Shots 2 and 3 are panel-local camera bearings on the same synthetic subject, not shots loaded from a clip. Shot 1 follows the panel camera. The 180°/30° arithmetic is real; the "footage" is not. |
| **The reliability envelope** | The constants (±45° green, ±60° yellow, 30° elevation) are the documented CrossView-Warp trained range, taken from the spec. They were not measured here. |
| **Scene-level rules** | The five `SceneFramingExtras` rules (size_importance, foreground_occlusion, eyeline, …) and the PER rules are **not** in the panel. Only the nine per-shot DET rules are. |
| **Persistence, backend, auth** | None. State lives in the page and is lost on reload. |

### Contradictions the panel shows instead of hiding

- **`1080p` is UI-only.** The shipped UI offers `480p / 720p / 1080p` and the credit table prices
  1080p, but the documented API `resolution` enum is only `480p / 720p`. The panel offers all three
  and marks 1080p as rejected by the documented API.
- **The emotion wheel has no API field at all.** It is shown in the plan and listed under *Omitted*,
  because there is nothing to send it as.
- **The UI tab says `Tempo`; the API field is `pacing`.** The panel labels the control *Tempo* and
  sends `pacing`.

### three.js

The 3D viewport loads three.js r160 from a CDN (unpkg, falling back to jsDelivr). **If the CDN is
unreachable the panel still works** — the rule panel, frame preview, solver, continuity and
reliability checks are pure arithmetic, and the whole Director tab is pure arithmetic. The viewport is
replaced by a note saying so.

---

## How this was verified

Three checks, all re-runnable. Nothing below is claimed without having been run.

| Check | Command | Result |
|---|---|---|
| Parity, four ways | `python3 app/web/parity_check.py` | `RESULT: PASS — 49 fixtures, 0 mismatches` (exit 0), 4 findings |
| Headless panel logic | `node app/web/tools/smoke_test.mjs` | `PASS — 63/63 checks passed` (exit 0) |
| Real browser pass | see below | `PASS — 50/50 browser checks passed` (exit 0) |

The smoke test drives the *real* panel pipeline (`panel_state.js` → `cinematographer.js`, and
`director.js` directly), not a copy. It also asserts that every DOM id `app.js` **and**
`director_panel.js` query exists in `index.html`, that the credit model reproduces all nine published
cells, and that `@`/`#` parsing resolves and flags correctly.

The browser check drives headless Chrome over the DevTools Protocol. On the Director tab it asserts
the tab is the default, that all 13 dropdowns match the engine enums exactly, that the move stack
reorders and the composed prompt follows that order, that `@`/`#` tags resolve and unresolved ones
flag red, that the cost readout follows duration and resolution, and that focal length lands in the
engine-extension block and never in the API parameter block. It then switches to the Judge tab and
asserts all nine rules render, moves a slider and confirms the measured values change, clicks
Auto-Frame and confirms the panel flips to overall PASS, checks the continuity strip, and forces a
synchronous render to **sample real WebGL pixels** (proving the viewport draws rather than showing a
black canvas).

```bash
# terminal 1
cd web && python3 -m http.server 8765
# terminal 2
node web/tools/browser_check.mjs http://127.0.0.1:8765/ /tmp/panel.png
```

It needs Chrome or Chromium; set `CHROME_PATH` if it is not in a standard location. It exits 0 with a
`SKIP` message when no browser is present, so it never fails a build for the wrong reason.

---

## Files

| File | Role |
|---|---|
| [`index.html`](index.html) | The panel markup: tab bar, Director tab, Judge tab. |
| [`styles.css`](styles.css) | Dark high-contrast theme; pass/fail/info colour coding. |
| [`app.js`](app.js) | Tab switching, Judge-tab DOM wiring, 2D frame preview, three.js viewport. No arithmetic. |
| [`director_panel.js`](director_panel.js) | Director-tab DOM wiring. Builds every control from `director.js`. |
| [`director.js`](director.js) | **The Director tab's source of truth**: every enum, the credit model, `@`/`#` parsing, the plan. |
| [`panel_state.js`](panel_state.js) | Judge-tab state + the compute pipeline. DOM-free, so tests drive the real thing. |
| [`cinematographer.js`](cinematographer.js) | **The engine mirror.** All geometry, rules, solver, continuity, reliability. |
| [`parity_fixtures.json`](parity_fixtures.json) | 49 frozen fixtures with expected values, plus the engine hash. |
| [`parity_check.py`](parity_check.py) | The four-way parity check. Must pass. |
| [`parity_runner.mjs`](parity_runner.mjs) | Runs the JS mirror over the fixtures; called by the checker. |
| [`tools/gen_fixtures.py`](tools/gen_fixtures.py) | Regenerates the fixtures from the Python engine. |
| [`tools/smoke_test.mjs`](tools/smoke_test.mjs) | Headless panel-logic checks. |
| [`tools/browser_check.mjs`](tools/browser_check.mjs) | Headless-Chrome end-to-end check. |

`app.js` exposes `window.__cinematographer`
(`{ state, view, compute, render, engine, panel, director, directorState, directorPanel, showTab }`) as
a debug hook; the browser check uses it to drive both tabs and to force a render and read pixels.

---

## Using the panel

### Director tab

- **Prompt** — type `@name` for an Element and `#move` for a camera move. Tags resolve as you type;
  unresolved ones turn red and suggest the nearest real value.
- **Film setup / Camera / Lighting & colour** — every dropdown starts on **Auto**, which means the
  field is omitted from the plan.
- **Camera movement** — pick a move and **Add** it. The list is ordered: use ↑ / ↓ to reorder and ✕ to
  remove. The composed prompt appends the `#` tags in exactly that order.
- **Emotion wheel** — pick an Element, an emotion and an intensity, then **Add**. Shown in the plan,
  never sent (there is no API field).
- **Generation** — duration, resolution, aspect ratio, native audio. The credit cost updates live on
  the Generate button. The button is disabled on purpose.
- **What would be sent** — the composed prompt, the attachment list, the parameter block, the engine
  extension, the omitted fields, and any warnings.

### Judge tab

- **Move the camera** — azimuth, distance, height, elevation, focal length, roll, aim offset. Every
  slider recomputes the rules immediately. The elevation slider and the height slider are two views
  of the same degree of freedom and stay in sync.
- **Composition / angle / shot type** — segmented controls feeding the `ShotIntent`, so deliberate
  choices are not flagged as errors.
- **Auto-Frame** — solves a pose that satisfies the weighted rules, keeping your chosen bearing, and
  reports the iteration count. The badge turns red if it did not converge.
- **Continuity** — three shots with editable bearings; each cut is checked for an axis cross and for
  an insufficient angle change.
- **Reliability** — the badge grades the current viewpoint against the model's trained range.
- **Node I/O** — the JSON panes show the exact camera and report objects the ComfyUI nodes consume.

### A note on the default frame

The Judge tab opens on a frame that **fails** (`rule_of_thirds`, `shot_size`). That is deliberate — a
demo that starts green has nothing to show. Press Auto-Frame to watch it converge in three iterations.

After Auto-Frame the overall badge reads PASS while `lead_room` (weight 0.4) may still be red. That is
the spec, not a bug: overall pass requires only the rules with `weight >= 0.8`.

---

## Porting notes

The mirror is line-by-line, so a few Python behaviours needed explicit equivalents:

- **`pyRound`** — Python's `round()` is ties-to-even; JS `Math.round` is ties-away-from-zero.
- **`pyFixed`** — Python's `format(x, '.2f')` renders negative zero as `-0.00`; JS `toFixed` drops the
  sign. The frame preview's NDC readouts depend on this.
- **`pyG`** — Python's `'%g'` formatting, used in the Dutch target string.
- **Unicode target strings** are written as `\u` escapes so the transport encoding cannot corrupt
  them. They are the reference source's strings verbatim (`≥`, `–`, `±`, `≈`, `°`).
