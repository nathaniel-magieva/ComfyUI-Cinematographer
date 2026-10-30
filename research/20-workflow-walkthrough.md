# The Cinema Studio 4.0 workflow, soup to nuts

> **What this section is.** The ordered pipeline a user actually walks, reconstructed by
> reconciling three independent tutorials against Higgsfield's own published API schema.
> Where the schema and the tutorials agree, the control is stated as fact. Where they
> disagree, the disagreement is shown. Where only a tutorial asserts something, it is
> marked **(b) claimed**.
>
> **The authoritative control vocabulary** in this section comes from the Cinema Studio
> 4.0 Generate API schema (T1, `docs.higgsfield.ai`, fetched 2026-10-29) — a closed
> enumeration set, which is the strongest available evidence of what the controls are.
> Tutorial timestamps are given as `[V1 04:35]` etc.

---

## 1. The workflow in one paragraph

Cinema Studio 4.0 is a **pre-generation directorial control surface**. You do not prompt
your way to a look; you **build reusable assets once, attach them as references, set a
closed set of cinematography parameters, and then describe only what happens.** The
prompt carries the action plus two kinds of inline tag — `@` for an Element (a character,
location or prop) and `#` for a camera move. Everything else — genre, era, pacing, camera
body, lens, aperture, lighting, colour palette, and per-character emotion — is a discrete
setting chosen before you press Generate. The output is video **with native audio in the
same pass**.

Higgsfield's own summary of the mechanism is the cleanest statement of the design intent:

> "Cinema Studio is how Higgsfield handles cinematography: production-grade video where
> **the movement itself is written in the prompt while everything around it, from genre
> logic to lens character, is locked as an explicit generation parameter before you press
> Generate**." — T1, [How to Control Camera Movement, Angles, and Lens in AI Video](https://higgsfield.ai/blog/ai-video-camera-control), 2026-10-09

That sentence is the whole architecture. It is also why the tutorials keep repeating the
same thesis in different words: **style belongs in the panels, action belongs in the
prompt.**

---

## 2. The mental model

All three tutorials teach the same shape, and it matches the API. The pipeline has four
movements:

```
   BUILD            ATTACH           DIRECT              SHOOT
   ─────            ──────           ──────              ─────
   image mode  →    Elements /   →   Director's Panel →  prompt + tags
   cast & sets      references       (5 control groups)  → Generate
                                                          (audio in-pass)
                                                              ↓
                                                          POST: grade,
                                                          extend, edit
```

The load-bearing idea is **reuse**. An Element is created once and tagged thereafter:

> "because everything I made is saved as an element, I never have to describe any of them
> again. I just tag whichever ones I need into a prompt. So, before animating anything, the
> look of every character, location, and prop is already locked in." — [V3 03:18–03:22]

That is the answer to the consistency problem. Higgsfield states the economics of it
directly: "A face described fresh in every prompt drifts between generations, and each
fix-it attempt is a paid regeneration. Training it once removes that entire category of
failed attempts." (T1)

> **Design note — why the panels exist at all.** Higgsfield's stated rationale is variance
> reduction: "A text-only prompt returns a different move on every run because speed, path,
> and end position stay unspecified. Cinema Studio fixes those properties as explicit
> settings." (T1, 2026-10-09). The panels are a determinism mechanism, not a filter rack.

---

## 3. Stage 0 — Project

Cinema Studio is project-scoped. A project holds its Elements, a Project Brief (tone,
references, do's and don'ts), subfolders, and shared team access. V1 — the adversarial
reviewer — argues this workspace layer, not the style engine, is the product's real value:

> "Cinema Studio is much more powerful now in collaborative organization and as a
> workspace. You can add project information in the brief page, organize assets by folder,
> create a visual canvas and node workflow alongside your assets, share the project with
> others at varying access levels, and even chat with those collaborators on Higgsfield
> while you're working." — [V1 09:32–09:52]

**Caveat, and it is a serious one:** V1 shows **none** of these workspace features on
screen. The one section where he recommends the product is the one section with zero
visual evidence. Treat the workspace claim as **(b) claimed**.

---

## 4. Stage 1 — Build the cast and the sets (image mode)

Cinema Studio has exactly **two modes: image and video** [V3 01:12]. Every character,
location and prop starts as an image, because the video model needs something to copy.

### 4.1 The two schools of asset generation

The tutorials diverge here, and the divergence is instructive.

| | V2 (Thomas Creates) | V3 (Youri) | V1 (Joseph Martin) |
|---|---|---|---|
| Model | GPT Image 2.5 Sunburst | GPT Image 2.5 Sunburst | Cinematic Locations · Soul Cast · Cinematic Cameras |
| Settings | 4K · high · 16:9 | high · max · 16:9 | 4K |
| Character method | one reference image per person | three-panel character sheet | Soul Cast genre menu |
| Verdict | works well | works well | **weak** — prefers Nano Banana Pro |

V2 and V3 agree on the model and the settings; V1 rejects the whole approach and uses an
external model instead. See §9 for why this matters.

### 4.2 The character sheet — and a trap

V3 teaches a **character sheet**: one image containing three panels of the same person,
with a deliberate quirk — the first panel has no head, so the face comes only from the
portrait panel — on a plain gray background with flat lighting, because "any lighting baked
in here will carry over into the final videos" [V3 02:44–02:50].

> **Trap, and the report flags it prominently.** The sheet-maker V3 uses is **his own
> bonus-package tool, not a Cinema Studio feature.** He says so himself — "instead of
> writing all that structure out myself, I'll use the sheet maker in my bonus package"
> [V3 02:20] — but he then presents the output inside the Cinema Studio workflow without
> re-flagging the boundary. The three-panel sheet, the headless first panel and the flat
> gray background are **not** product features. Do not credit them to Higgsfield.

V2 takes the simpler route: generate one clean reference image per character and one
"clean plate" of the location, then attach them. Both routes work; V2's is the one that
maps directly onto the product's own reference system.

### 4.3 Save as an Element

Whatever the route, the asset is saved as an **Element** with a category. V3 uses three:

| Category | Example | Tagged later as |
|---|---|---|
| **location** | `Mirror Dunes`, `bell barge` | `@Mirror Dunes` |
| **character** | `Tamsin`, `Oscar` | `@Tamsin` |
| **prop** | `helmet` | `@helmet` |

Higgsfield's own taxonomy is Characters / Locations / Props (T1), so the three categories
are confirmed. V3 created **15 named Elements** across the video.

### 4.4 The image-mode controls, as documented

| Control | Values | Tier |
|---|---|---|
| Model | GPT Image 2.5 Sunburst (tutorial choice); Nano Banana Pro, Flux 2, Seedream 5, GPT Image 2, Ideogram 4.5 also on the platform | T1 (catalogue) / T3 (tutorial preference) |
| Quality | high | T3 |
| Resolution | max / 4K | T3 |
| Aspect | 16:9 | T3 |

> **Note the asymmetry.** The image side is *not* governed by the Cinema Studio enum set —
> it is the general Higgsfield image surface. V1's finding that "there [is] no difference
> between Cinema Studio and Higgsfield['s] typical image gen workflow" for locations
> [V1 02:19] is therefore structurally plausible: image generation inside Cinema Studio is
> the platform's image generation.

---

## 5. Stage 2 — Enter video mode and pick the engine

Switch to **video mode** and select the model. V3 and V2 both select **Cinema Studio 4.0**
from the model selector [V3 03:46, V2 00:57].

| Setting | Value used | Tier |
|---|---|---|
| Model | Cinema Studio 4.0 | T1 |
| Resolution | 1080p | T1 (app max) |
| Aspect ratio | 16:9 (V2) · 21:9 (V3) | T1 |
| Sound | on | T1 |

**The engine question.** Cinema Studio 4.0's native model **runs on Seedance 2.5** (T1,
help centre) — but the workspace is explicitly **multi-model**: "Seedance and other leading
video models run natively inside Cinema Studio 4.0 — pick the engine per shot" (T1, product
page), with Kling 3.0, Veo 3.1 and WAN 3.0 named as selectable. So:

- V1's "Cinema Studio 4.0 is simply a wrapper UI built around Seedance 2.5" [V1 00:27] is
  **half right** — correct about the native model, wrong about the wrapper being
  single-engine.
- The 1080p claim is **true in the app, false in the API** — the API caps at 720p (T1).

---

## 6. Stage 3 — The Director's Panel

Four control groups sit in a row above the prompt box, and **every one of them starts on
auto** [V3 03:57]. V3's pedagogy is to change exactly one at a time so the effect is
visible; that is a teaching device, not a production practice — his capstone scene sets all
of them at once.

### 6.1 Film Setup — genre · era · tempo

| Control | API enum values | Tutorial values used |
|---|---|---|
| **Genre** | `epic` `drama` `noir` `comedy` `horror` `action` | adventure (V1) · noir, epic (V2) · epic, drama (V3) |
| **Era** | `1960s` `1980s` `1990s` `2000s` `2020s` | 1960s (V2, V1) · 1980s, 1990s (V3) · 2020s (V2) |
| **Tempo** | `chaotic` `dynamic` `calm` `single-shot` | chaotic (V1, V3) · calm, dynamic (V2) · calm (V3) |

> **Conflict — genre count.** The API enum has **6** genres with no `general`; the UI and
> help centre list **7** including General. Both are first-party. "7 genres" is right for
> the UI, "6" for the API.

> **Conflict — the name.** The 4.0 editorial and settings reference call this group
> **Tempo**; the how-we-built FAQ and product page call the same feature **Montage
> Pacing**. Same control, two names, both first-party.

V3 draws the sharpest distinction in the whole evidence set here: **era changes the medium,
not the set.** His '80s scene already had an '80s room in the prompt; what the era setting
changed was "how the video itself looks… colors and grain" [V3 11:16–11:34]. That is a
coherent reading of a conditioning parameter, and it is the kind of claim that would be
settled in one A/B generation.

### 6.2 Camera — body · lens · aperture

| Control | API enum values | Tutorial values used |
|---|---|---|
| **Camera body** | `modern` `35mm-film` `8mm-film` `dv-camcorder` | 35mm film (V2, V3) · 8mm film (V1) · modern (V2) |
| **Lens** | `clean-sharp` `anamorphic` `vintage-anamorphic` `warm-vintage` `halation-vintage` | anamorphic (V2, V3) · halation vintage (V3) · vintage halation (V1) |
| **Aperture** | `f14-wide-open` `f4-moderate` `f11-deep-focus` | f/1.4 wide open (V3) · f/4 moderate (V2, V3 capstone) |

**Four bodies, five lenses — exactly as V1 counted.** His complaint that the video panel is
"way more limited than it was in photo… only four cameras, five lenses, and no focal length
control" [V1 07:57] is **confirmed by the API schema**. And the focal-length disappearance
is real: focal length was one of the **three original controls in Cinema Studio 1.0** and
was still named in 2.0 and 3.5, but it is absent from the 4.0 settings reference, the 4.0
help-centre walkthrough, and the 4.0 API schema. **Focal length was dropped in 4.0.**

> **What the lens actually is.** Not optics. Higgsfield's DP: "Obviously it's not the same
> as shooting on a real camera and real optics. So we looked for each lens's character, and
> **we amplified it**." (T1). The lenses are hand-tuned, deliberately exaggerated character
> profiles applied as conditioning. The 3.5→4.0 change is that lenses went from a
> **post-hoc filter** to **optically modelled at generation time** (T1).

### 6.3 Camera movement — the `#` tag

This is the mechanism that trips people up, and it is the one control that is **not** a
panel value in the API's sense: the move is carried **in the prompt**.

- **33 named moves** in the API enum — `tracking`, `crane-up`, `helicopter-shot`,
  `dolly-zoom`, `whip-pan`, `bullet-time`, `snorricam`, `drone-orbit`, `arc-left`, and so on.
- Higgsfield: "every move is a `#` tag. Type it in the prompt or pick from the library;
  **stack several per shot, they run in order**." (T1, product page)
- V2 confirms the stacking: "you can actually stack more than one move, so I'll add a
  helicopter shot first, and then a tracking move, and it runs them in order, sweeping in
  from above, and then following the action on the ground." [V2 11:24–11:56]
- V2 also shows the *entry point*: the camera console has two sections, **setup** and
  **movement**, and clicking a move "drop[s] a tracking tag straight into my prompt"
  [V2 09:10–09:54].

> **Not a conflict — a reconciliation.** V3 says the move "isn't in that camera panel at
> all, because the camera movement goes straight into the prompt. Type hashtag in the
> prompt box and pick a move from the list" [V3 05:16–05:38]. V2 says it is in the camera
> console, under **movement**. The two accounts agree once separated: **the picker lives in
> the console, and it writes a tag into the prompt.** V2 states the mechanism plainly —
> "click it to drop a tracking tag straight into my prompt" [V2 09:10]. V3 is describing the
> same feature from the prompt end. This is a description-order difference, not a
> disagreement about where the control is.

> **The single most load-bearing unverified claim in the evidence set.** V3 asserts that
> **the position of the `#` tag in the prompt sets the time the move starts**: "it adds a
> tag to your prompt, and the camera starts that move at the exact point where you put the
> tag" [V3 05:38–05:45]. He then builds his durations around it — an 18-second clip because
> "the move only starts 6 seconds in" [V3 05:45]. **Every long duration in V3 is downstream
> of this one claim, and he never demonstrates a tag starting at the wrong time.** Higgsfield
> says the preset "sets the register it runs in" and that stacking runs moves "in order"
> (T1) — which is consistent with, but does not confirm, position-as-timestamp. **Treat as
> (b) claimed, and as the highest-value thing to test.**

### 6.4 Lighting

| API enum values | Tutorial values used |
|---|---|
| `silhouette` `practicals` `window` `overhead-fall` `contre-jour` `soft-cross` | practicals (V2, V3) · contre jour (V2, V3) · silhouette (V1, V3) |

Six presets, plus a manual mode with colour, brightness, diffusion and angle (T1). V3 also
notes you can save your own setup [V3 07:12].

V2's framing of why this matters is the product's core pitch:

> "Most AI tools offer you some generic lighting options… You type something like cinematic
> lighting into the prompt, you generate, and you just hope the model lights it the way you
> pictured, which most of the time it doesn't. Cinema Studio 4.0 is the only one that gives
> you lighting as an actual console, a real setting you pick, the same way you'd set the
> lights on a real film set." — [V2 00:31–01:02]

**And this is exactly the claim V1 falsifies.** See §9.

### 6.5 Colour palette

| Aspect | Detail | Tier |
|---|---|---|
| Templates | **50 named palettes** — `static-noon`, `twilight-fable`, `pink-velvet`, `neon-rain-at-midnight`, `gasoline-sunset`, `dont-turn-it-off-im-watching`, `the-neighbors-saw-everything`, … | T1 |
| Custom | Build your own: **1–12 hex codes**, first one marked **main** | T3 (V2/V3) |
| From image | Drop in an image and it pulls the colours out | T3 (V2) |

> **A naming trap worth flagging.** V2's custom palette is `Nostalgic Blue` — which is
> **not** one of the 50 presets; he says so himself at [V2 02:44] ("it isn't one of the
> presets"). The presets are hyphenated slugs (`twilight-fable`); user palettes are
> free-text and often sentence-like. Do not mistake a creator's custom palette for a
> product preset. The same caution applies to the blog's own palette examples (Film Colors,
> Black Gloss, Candy Pink, Lime Jam), which are **absent from the 50-value enum**.

Both V2 and V3 build custom palettes and both name them — V2's `Nostalgic Blue` and
`dreamy teal`, V3's `graveyard shift`, `molten dawn` and `violet hour`. V3's demo is the
strongest single piece of evidence in any of the three videos for the panels actually
working, because **neither of his two prompts mentions a colour**:

> "And neither of these prompts mentions a single color. All of it comes from the palette."
> — [V3 09:59–10:01]

### 6.6 Emotion Wheel

| Aspect | Higgsfield (T1) | V3 (T3) |
|---|---|---|
| Count | **8** — Hope, Anger, Joy, Trust, Fear, Surprise, Sadness, Disgust | **80 emotions** |
| Levels | not documented | **3 strength levels** each; joy's lowest = "serenity" |
| Scope | per character, applied as `@character_name Joy` | per saved character |

> **Conflict — emotion count.** V3 says "you pick one of 80 emotions and then how strong you
> want it with three levels for each one" [V3 12:38–12:42]. Higgsfield's settings reference
> and complete guide enumerate exactly **8**, and the 4.0 editorial says "8+". A 10×
> discrepancy. Either V3 misread the UI, or the UI exposes far more presets than the docs
> enumerate. **Unresolved — flagged for verification.**

V3's demonstration is nonetheless the most rigorous experiment in the evidence set: he runs
**the identical prompt three times** changing only the emotion, and gets three different
performances of the same line [V3 12:42–13:38].

---

## 7. Stage 4 — The prompt

The prompt does two jobs and only two:

1. **Describe the action.** "the prompt only has to describe what happens" [V3 04:14].
2. **Carry the tags** — `@` for Elements, `#` for camera moves.

V3's convention for locations is worth recording as a technique: describe every location as
"a real photo taken on a film set" and keep it "completely empty of people because the
characters get added in by the video model later" [V3 01:38–01:41].

> **The API's own reference tokens are different.** The API uses one-based
> `<<<image_1>>>`, `<<<video_1>>>`, `<<<audio_1>>>` tokens that must each match an attached
> item of the same type (T1). The `@`/`#` syntax is the **app's** surface. A workflow built
> in the UI does not port to the API unchanged — the tags must be rewritten.

---

## 8. Stage 5 — Generate, then post

### 8.1 The generation bar

| Control | Values | Tier |
|---|---|---|
| Duration | **4–30 s** (API int, default 5) | T1 |
| Resolution | 480p / 720p / 1080p in app; **480p / 720p only in API** | T1 |
| Aspect ratio | 16:9, 4:3, 1:1, 3:4, 9:16, 21:9 | T1 |
| Sound | toggle; API `generate_audio` default **true** | T1 |
| Bitrate | Standard | T1 |
| Cost | **shown on the Generate button before you confirm** | T1 |

**Native audio is generated in the same pass** — speech, SFX and music — on every version
from 2.5 to 4.0 (T1). It is not a separate step and there is no separate audio model to
choose.

### 8.2 What a generation costs

Higgsfield's published table, "with native audio in a 16:9 frame", pricing checked
**2026-10-24** (T1):

| Duration | 480p | 720p | 1080p |
|---|---|---|---|
| 10 s | 30 cr | **70 cr** | 160 cr |
| 15 s | 45 cr | 105 cr | 240 cr |
| 30 s | 90 cr | 210 cr | **480 cr** |

The PR release (2026-10-28) corroborates two cells exactly — 70 credits for 10 s at 720p,
480 credits for 30 s at 1080p — and adds a **limited-time 25% discount** bringing the 30 s
1080p tier to **360 credits**.

> **This is the number V1 never gives.** V1's entire credit-waste argument [V1 00:07] runs
> without a single figure. **This report declines to supply one.** The fourteen discarded
> generations decompose into six image generations on a different price basis, three AI
> Director attempts whose billing status is unclear, and five video generations for which
> V1 gives no duration or resolution — and the table spans a 16× range. A video-only range
> at 10 s would be roughly **350–800 credits**. Anything more precise would be invention,
> and inventing it would be exactly the failure this report criticises in the tutorials.

### 8.3 Post-generation

| Feature | What it does | Tier |
|---|---|---|
| **Colour grading** | temperature, contrast, saturation, sharpness, film grain, highlights, exposure | T1 |
| **Change colour palette** | re-grade to a different palette | T1 |
| **Extend** | **Sequel** (continue after the end) / **Prequel** (lead-in before the start) | T1 |
| **Edit Video** | regional edits — an object or a face | T1 |

> **Architectural catch.** Extend and Edit are **not Cinema Studio endpoints**. The API docs
> state it plainly: "This endpoint produces a new video. **Editing and extension use the
> separate Seedance 2.5 endpoints.**" (T1). So two of 4.0's advertised features are, at the
> API layer, Seedance calls.

---

## 9. The conflict that defines this report

**V1 says the style panels do nothing. V2 and V3 demonstrate them working.** This is not a
nuance; it is the central question, and the report does not average it.

### 9.1 V1's evidence (2026-08-24, adversarial)

| Test | Setting | Result |
|---|---|---|
| Film setup | noir · 1960s · chaotic | "did absolutely nothing" [V1 07:45] |
| Camera styles | 8mm film · vintage halation · f/1.4 | "didn't do anything to the footage either" [V1 08:26] |
| Camera + palette | modern anamorphic + bluish palette | "No anamorphic attributes here whatsoever, and no bluish color grade either" [V1 08:48] |
| Lighting | silhouette preset | "Cinema Studio is 0 for 4 on actually applying styles to the footage" [V1 09:14] |
| **Control** | same prompt, "silhouette backlighting" **written in the text** | "it was able to do it just fine" [V1 09:20] |

The control is what makes V1's finding serious. The model *can* produce the effect; the
panel *cannot request it*. If that reproduces, every panel-routed style generation is a
wasted credit — which is precisely his opening warning.

### 9.2 V2's and V3's evidence

| Test | Setting | Result |
|---|---|---|
| V2 film setup | noir · 1960s · calm | "it actually looks like it could be running on TV as a cartoon people would watch" [V2 08:08] |
| V2 camera | 35mm film · anamorphic · f/4 | "the shot is framed and moving the way a real camera would" [V2 09:54] |
| V2 lighting | contre-jour | "the lighting looks by far the best out of every result so far" [V2 11:56] |
| V2 palette | custom `dreamy teal` | "the colors look incredible" [V2 12:37] |
| V3 palette | `graveyard shift` / `molten dawn` | "neither of these prompts mentions a single color" [V3 09:59] |
| V3 lighting | practicals | worked, **with an admitted glitch** [V3 08:20] |

> **Read V2's last two rows with care.** His lighting and palette verdicts at [11:56] and
> [12:37] come from the **capstone run, in which every console was already set** — he says
> so at [V2 11:24]: "With every single console now set". They are therefore his overall
> impression of a fully-configured generation, not isolated per-console test results. Only
> his film-setup and camera rows are single-variable demonstrations, and both of those
> prompts name the variable under test.

### 9.3 What would settle it

The two results are not reconcilable by preference — they are contradictory observations of
the same feature. Candidate explanations, none established:

1. **Build drift.** V1 is dated 2026-08-24; V2 and V3 are undated but reference the same
   4.0. If Higgsfield fixed the conditioning path after V1's test, both are right at
   different times. **This is the most likely explanation and is untested.**
2. **Method.** V1 removed the style section from his prompt before testing the panels. If
   the panels require the prompt to be silent about style *and* the reference images to be
   neutral, his test conditions may differ from V2/V3's in a way that matters.
3. **Selection.** V1 may have had a different engine selected per shot (the workspace is
   multi-model) — a Cinema Studio panel applied to a non-native engine may not condition.
4. **V1 is wrong.** Possible, but his control experiment makes this the least likely of the
   four.

**The report's position:** the panels are **documented, enumerated, and API-exposed** (T1),
so they are real parameters, not marketing. Whether they **visibly condition the output** is
**contested** — demonstrated by two creators, denied by a third with a control experiment.
**One A/B generation on the current build settles it.** Until then, any claim that Cinema
Studio's style engine works, or does not, is **(b) claimed**.

---

## 10. The canonical recipes

Two fully-specified parameter sets exist in the evidence set. They are the most useful
artefacts in this report, because they are the only places where every control is set at
once.

### 10.1 V3's capstone — the full-surface recipe

| Control | Value |
|---|---|
| Duration | 30 s |
| Genre · Era · Tempo | drama · 1990s · calm |
| Camera body · Lens · Aperture | 35mm film · anamorphic · f/4 moderate |
| Lighting | contre-jour |
| Colour palette | `violet hour` (indigo/violet + apricot/honey) |
| Emotion | Tamsin neutral · Oscar joy (lowest = "serenity") |
| Prompt tags | `tracking` @ 12 s · `crane up` @ 23 s |
| Scene | Tamsin flies Oscar home at dusk, lands on a dirt strip by his farmhouse, the pair walk inside |

### 10.2 V2's capstone — the stacked-console recipe

| Control | Value |
|---|---|
| Duration | 30 s |
| Genre · Era · Tempo | epic · 2020s · dynamic |
| Camera body · Lens · Aperture | modern · anamorphic · f/4 |
| Lighting | contre-jour |
| Colour palette | custom `dreamy teal` (gunmetal gray main, steel teal, near-black blue, aurora green silver, ember gold) |
| Movement | `helicopter shot` then `tracking` (stacked, in order) |
| Scene | a grandmother and grandson on a cliff at night hauling a net of glowing fish out of an aurora |

Note how closely the two independent creators converge: 30 seconds, anamorphic, f/4,
contre-jour, a custom cool-toned palette, and stacked movement tags. That convergence is
itself evidence that the workflow is real and teachable — whatever the panels do to the
pixels.

---

## 11. The minimal workflow

If you strip the pedagogy, the shortest path that uses the product as designed is:

1. **Image mode** → generate one clean reference per character and one clean plate per
   location (GPT Image 2.5 Sunburst, 4K, 16:9).
2. **Save each as an Element** with the right category.
3. **Video mode** → model **Cinema Studio 4.0**, 1080p, sound on.
4. **Attach the references** (V2's "references pill" at the top [V2 05:48]).
5. **Set the Director's Panel** — film setup, camera, lighting, palette. Optionally the
   emotion wheel per character.
6. **Prompt the action only**, with `@` tags for Elements and `#` tags for moves.
7. **Set duration** (4–30 s), check the credit cost on the button, **Generate**.
8. **Post** — grade, extend, or edit.

Everything else in the three tutorials is either pedagogy (one variable at a time), a
creator's own tooling (V3's sheet maker), or a feature that may not work (§9).
