/**
 * Cinema Studio Director's Panel — the pre-generation control surface.
 *
 * This module is the panel's single source of truth for every option list. No
 * option is hand-typed in the HTML: `app.js` builds every control from the
 * enums exported here, so there is exactly one place to fix when the engine
 * changes.
 *
 * PROVENANCE OF THE ENUMS
 * -----------------------
 * Every enum below is the closed enumeration published in the Cinema Studio 4.0
 * Generate API reference (T1, first-party), captured verbatim at
 * `research/cinema-studio-4.0-api-schema.txt` -- shipped in this repository, so the
 * citation resolves. The API is the authority: the
 * shipped UI scrolls, truncates and omits, so several on-screen lists were only
 * partially legible.
 *
 * `parity_check.py` cross-checks these lists against the engine's own
 * `director.py` the moment that module exists, so this file cannot silently
 * drift from the engine. Until then the check reports the section as SKIPPED
 * rather than passing it.
 *
 * WHAT THIS MODULE DOES NOT DO
 * ----------------------------
 * It composes a plan. It does not generate, render, or send anything.
 */

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

export const SCHEMA_SOURCE = {
  label: 'Cinema Studio 4.0 — Generate API reference (first-party)',
  captured: '2026-10-29',
  note:
    'Closed enumerations published in the API reference. The shipped UI scrolls and ' +
    'truncates, so on-screen lists were only partially legible; the API is the authority.',
};

export const CREDIT_SOURCE = {
  label: 'Cinema Studio 4.0 credit table (first-party), pricing checked 2026-10-24',
  note:
    'Published "with native audio in a 16:9 frame". Corroborated for two cells by the ' +
    '2026-10-28 press release (10 s 720p = 70; 30 s 1080p = 480, or 360 under a ' +
    'limited-time 1080p discount).',
};

// ---------------------------------------------------------------------------
// Display labels
// ---------------------------------------------------------------------------

/** Slugs whose on-screen label is not a mechanical title-case of the slug. */
const LABEL_OVERRIDES = {
  '35mm-film': '35mm Film',
  '8mm-film': '8mm Film',
  'dv-camcorder': 'DV Camcorder',
  'clean-sharp': 'Clean Sharp',
  'vintage-anamorphic': 'Vintage Anamorphic',
  'warm-vintage': 'Warm Vintage',
  'halation-vintage': 'Halation Vintage',
  'f14-wide-open': 'f/1.4 Wide Open',
  'f4-moderate': 'f/4 Moderate',
  'f11-deep-focus': 'f/11 Deep Focus',
  '1960s': '1960s',
  '1980s': '1980s',
  '1990s': '1990s',
  '2000s': '2000s',
  '2020s': '2020s',
  'pov': 'POV',
  'contre-jour': 'Contre-Jour',
  'overhead-fall': 'Overhead Fall',
  'soft-cross': 'Soft Cross',
  'single-shot': 'Single Shot',
  'dolly-zoom': 'Dolly Zoom',
  'rack-focus': 'Rack Focus',
  'whip-pan': 'Whip Pan',
  'bullet-time': 'Bullet Time',
  'drone-orbit': 'Drone Orbit',
  'robot-arm': 'Robot Arm',
  'aerial-pullback': 'Aerial Pullback',
  'helicopter-shot': 'Helicopter Shot',
  'snorricam': 'Snorricam',
  'crush-zoom': 'Crush Zoom',
  'static-shot': 'Static Shot',
  '16:9': '16:9',
  '4:3': '4:3',
  '1:1': '1:1',
  '3:4': '3:4',
  '9:16': '9:16',
  '21:9': '21:9',
  '480p': '480p',
  '720p': '720p',
  '1080p': '1080p',
};

/** The label the UI shows for a slug. */
export function labelFor(slug) {
  if (LABEL_OVERRIDES[slug]) return LABEL_OVERRIDES[slug];
  return String(slug)
    .split('-')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

// ---------------------------------------------------------------------------
// The enums
// ---------------------------------------------------------------------------

/** Film Setup → Genre. API field `genre`. */
export const GENRE = ['epic', 'drama', 'noir', 'comedy', 'horror', 'action'];

/** Film Setup → Era. API field `era`. */
export const ERA = ['1960s', '1980s', '1990s', '2000s', '2020s'];

/** Film Setup → Tempo. API field `pacing` (the UI tab says "Tempo"). */
export const PACING = ['chaotic', 'dynamic', 'calm', 'single-shot'];

/** Camera → body. API field `camera_model`. */
export const CAMERA_MODEL = ['modern', '35mm-film', '8mm-film', 'dv-camcorder'];

/** Camera → lens. API field `camera_lens`. */
export const CAMERA_LENS = [
  'clean-sharp',
  'anamorphic',
  'vintage-anamorphic',
  'warm-vintage',
  'halation-vintage',
];

/** Camera → aperture. API field `camera_aperture`. */
export const CAMERA_APERTURE = ['f14-wide-open', 'f4-moderate', 'f11-deep-focus'];

/**
 * Camera movement — 33 named moves. API field `camera_movement`.
 * Carried in the prompt as `#` tags; stackable, and they run in the order given.
 */
export const CAMERA_MOVEMENT = [
  'snorricam',
  'robot-arm',
  'tilt-up',
  'rack-focus',
  'tilt-down',
  'pov',
  'pan-left',
  'crane-up',
  'pan-right',
  'crane-down',
  'side-tracking',
  'pedestal-up',
  'pedestal-down',
  'handheld',
  'tracking',
  'drone-orbit',
  'dolly-zoom',
  'aerial-pullback',
  'static-shot',
  'bullet-time',
  'whip-pan',
  'slow-zoom-in',
  'arc-left',
  'slow-zoom-out',
  'arc-right',
  'truck-right',
  'dolly-in',
  'truck-left',
  'dolly-out',
  'slider-right',
  'crush-zoom',
  'slider-left',
  'helicopter-shot',
];

/**
 * Panel-added grouping of the 33 moves, purely to make the picker navigable.
 * NOT part of the API — every slug in it is an enum member, and the union of the
 * groups is exactly `CAMERA_MOVEMENT`.
 */
export const MOVEMENT_GROUPS = [
  { name: 'Push / pull', slugs: ['dolly-in', 'dolly-out', 'slow-zoom-in', 'slow-zoom-out', 'crush-zoom', 'dolly-zoom', 'aerial-pullback'] },
  { name: 'Lateral', slugs: ['tracking', 'side-tracking', 'truck-left', 'truck-right', 'slider-left', 'slider-right'] },
  { name: 'Rotate', slugs: ['pan-left', 'pan-right', 'whip-pan', 'tilt-up', 'tilt-down', 'arc-left', 'arc-right'] },
  { name: 'Vertical', slugs: ['crane-up', 'crane-down', 'pedestal-up', 'pedestal-down'] },
  { name: 'Orbit / aerial', slugs: ['drone-orbit', 'helicopter-shot'] },
  { name: 'Optical', slugs: ['rack-focus'] },
  { name: 'Body / rig', slugs: ['handheld', 'snorricam', 'robot-arm', 'pov', 'bullet-time'] },
  { name: 'Static', slugs: ['static-shot'] },
];

/**
 * Lighting → look. API field `light`.
 *
 * Count verified against the UI anatomy read: the lighting grid was cut off by
 * the generation bar, and only `Practicals`, `Window` and two truncated labels
 * (`Si…`, `Ove…`) were legible. The API enum is the full set — six presets.
 * `contre-jour` was never legible on screen at all.
 */
export const LIGHT = [
  'silhouette',
  'practicals',
  'window',
  'overhead-fall',
  'contre-jour',
  'soft-cross',
];

/**
 * Colour palette. API field `color_palette`. 50 named palettes.
 *
 * Count verified against the UI anatomy read: the enum lists 50, and **none of
 * the 50 names was legible on screen** — the modal only ever showed a user-made
 * palette (`Molten Dawn`, six hex swatches), which is not in this enum. So this
 * list is API-sourced end to end, with no on-screen corroboration.
 */
export const COLOR_PALETTE = [
  'static-noon',
  'twilight-fable',
  'back-row-kissing-seats',
  'on-the-other-side-of-the-porthole',
  'the-emerald-ambush',
  'highway-standoff',
  'the-faded-fresco',
  'oil-ochre',
  'the-mountain-convent',
  'ghost-in-the-code',
  'pink-velvet',
  'two-days-to-the-horizon',
  'industrial-fog',
  'stairs-go-up',
  'field-post',
  'home-is-the-next-gas-station',
  'glossy-flesh',
  'the-crimson-ballet',
  'neon-rain-at-midnight',
  'the-morning-after-rain',
  'the-iron-borough',
  'the-ground',
  'the-investigation',
  'turquoise-mirage',
  'a-dream-in-color',
  'breakfast-on-schedule',
  'favela-gold',
  'a-hotel-for-one',
  'after-dark',
  'crimson-vigi',
  'the-neighbors-saw-everything',
  'the-grey-channel',
  'mirage-at-noon',
  'bubblegum-boulevard',
  'yellow-room',
  'the-earth-keeps-things-reluctantly',
  'tropic-fever-dream',
  'bioluminescent-night',
  'dont-turn-it-off-im-watching',
  'the-silk-curtain-falls',
  'the-butterfly',
  'playtime',
  'wallpaper-romance',
  'overtime',
  'the-way-home-is-longer',
  'everyone-speaks-in-whispers',
  'runaway-summer',
  'amber-wasteland',
  'the-circus',
  'gasoline-sunset',
];

/**
 * Emotion wheel. Nine names — the union of the two lists the evidence contains:
 *
 *   on-screen wheel (V3):  Sadness, Fear, Anger, Joy, Trust, Disgust, Surprise, Interest
 *   settings reference:    Hope, Anger, Joy, Trust, Fear, Surprise, Sadness, Disgust
 *
 * The two eight-item lists differ by exactly one member (`Interest` vs `Hope`),
 * so the union is nine. One tutorial claims **80 emotions across 3 strength
 * levels**; that is unverified and we do not implement 80 — it is the largest
 * unresolved discrepancy between a tutorial and the documentation anywhere in
 * the source set.
 *
 * There is no `emotion` field anywhere in the published API schema — the wheel
 * is a UI-only control as far as the public contract goes.
 */
export const EMOTION = [
  'sadness',
  'fear',
  'anger',
  'joy',
  'trust',
  'disgust',
  'surprise',
  'interest',
  'hope',
];

/**
 * Performance intensity, as a continuous 0..1.
 *
 * The evidence claims three discrete strength levels, but **no intensity or
 * strength control was legible in any frame**, so the number of levels and their
 * boundaries are unknown. Rather than invent three cut points, both this panel
 * and the engine model intensity as continuous 0..1. The words below are
 * descriptors *on* that scale, not enum members.
 */
export const EMOTION_INTENSITY_MIN = 0.0;
export const EMOTION_INTENSITY_MAX = 1.0;
export const EMOTION_INTENSITY_DEFAULT = 0.5;

/** PANEL-ADDED descriptors for the continuous scale. Not enum members. */
export const EMOTION_INTENSITY_LABELS = [
  { value: 0.0, label: 'subtle' },
  { value: 0.5, label: 'moderate' },
  { value: 1.0, label: 'intense' },
];

/** The descriptor nearest a 0..1 intensity. */
export function intensityLabel(value) {
  let best = EMOTION_INTENSITY_LABELS[0];
  let bestD = Infinity;
  for (const l of EMOTION_INTENSITY_LABELS) {
    const d = Math.abs(l.value - value);
    if (d < bestD) {
      bestD = d;
      best = l;
    }
  }
  return best.label;
}

/** Resolution. The API accepts two values; the shipped UI offers a third. */
export const RESOLUTION_API = ['480p', '720p'];

/**
 * The shipped UI's resolution dropdown reads `480p`, `720p`, `1080p`, and the
 * published credit table prices 1080p — but the documented `resolution` enum is
 * only `480p`/`720p`. The panel shows all three and marks 1080p as rejected by
 * the documented API rather than hiding the contradiction.
 */
export const RESOLUTION_UI = ['480p', '720p', '1080p'];

/** Aspect ratio. API field `aspect_ratio`. */
export const ASPECT_RATIO = ['16:9', '4:3', '1:1', '3:4', '9:16', '21:9'];

/** Duration bounds, from the API schema. */
export const DURATION_MIN = 4;
export const DURATION_MAX = 30;
export const DURATION_DEFAULT = 5;

// ---------------------------------------------------------------------------
// Focal length — the control 4.0 dropped, and we kept
// ---------------------------------------------------------------------------

/**
 * Cinema Studio 4.0 **dropped focal length**. It was one of the three original
 * 1.0 controls, is still named in the 2.0/3.5 material, and is absent from the
 * 4.0 settings reference, the help-centre walkthrough, and the API schema.
 *
 * This engine keeps it first-class, so the Director tab exposes it. It is
 * therefore NOT an API field: the plan puts it in `extensions`, never in the
 * parameter block, because sending it would be a lie about the contract.
 *
 * Mirrors `FOCAL_LENGTH_DROPPED_IN_4_0` in the Python engine.
 */
export const FOCAL_LENGTH_DROPPED_IN_4_0 = true;

export const FOCAL_MIN = 14;
export const FOCAL_MAX = 135;
export const FOCAL_DEFAULT = 35;

/** Every enum in one place, so the panel and the parity check agree on names. */
export const ENUMS = {
  genre: GENRE,
  era: ERA,
  pacing: PACING,
  camera_model: CAMERA_MODEL,
  camera_lens: CAMERA_LENS,
  camera_aperture: CAMERA_APERTURE,
  camera_movement: CAMERA_MOVEMENT,
  light: LIGHT,
  color_palette: COLOR_PALETTE,
  emotion: EMOTION,
  resolution: RESOLUTION_UI,
  aspect_ratio: ASPECT_RATIO,
};

/** The API field each panel group maps onto. */
export const API_FIELDS = {
  genre: 'genre',
  era: 'era',
  pacing: 'pacing',
  camera_model: 'camera_model',
  camera_lens: 'camera_lens',
  camera_aperture: 'camera_aperture',
  camera_movement: 'camera_movement',
  light: 'light',
  color_palette: 'color_palette',
  resolution: 'resolution',
  aspect_ratio: 'aspect_ratio',
  duration: 'duration',
  generate_audio: 'generate_audio',
};

/** The literal `auto` is NOT an accepted enum value — it means "omit the field". */
export const AUTO = 'auto';

// ---------------------------------------------------------------------------
// Cost
// ---------------------------------------------------------------------------

/**
 * The published credit table, verbatim: native audio on, 16:9 frame.
 *
 *   duration   480p   720p   1080p
 *   10 s         30     70     160
 *   15 s         45    105     240
 *   30 s         90    210     480
 *
 * All nine cells are exactly linear in duration, so the model below is
 * `credits = duration_seconds x rate(resolution)` with rate 3 / 7 / 16. It
 * reproduces every published cell with no residual.
 */
export const CREDIT_TABLE = {
  '480p': { 10: 30, 15: 45, 30: 90 },
  '720p': { 10: 70, 15: 105, 30: 210 },
  '1080p': { 10: 160, 15: 240, 30: 480 },
};

/** Credits per second, derived from (and exactly reproducing) the table above. */
export const CREDIT_RATE = { '480p': 3, '720p': 7, '1080p': 16 };

/** The press release's limited-time 1080p launch discount: 480 -> 360. */
export const LAUNCH_DISCOUNT = {
  resolution: '1080p',
  factor: 0.75,
  documented_example: { duration: 30, list: 480, current: 360 },
};

/** Monthly Plus rate, used only for the secondary dollar estimate. */
export const USD_PER_CREDIT = 0.049;

/**
 * Estimate the credit cost of a generation.
 *
 * @param {{duration:number, resolution:string, aspect_ratio?:string, generate_audio?:boolean}} req
 * @returns {{rate:number, list:number, current:number, discounted:boolean,
 *            dollars:number, notes:string[]}}
 */
export function estimateCredits(req) {
  const duration = Number(req.duration);
  const resolution = req.resolution;
  const notes = [];

  const rate = CREDIT_RATE[resolution];
  if (rate === undefined) {
    return {
      rate: 0,
      list: 0,
      current: 0,
      discounted: false,
      dollars: 0,
      notes: [`no published rate for resolution "${resolution}"`],
    };
  }

  const list = rate * duration;
  const discounted = resolution === LAUNCH_DISCOUNT.resolution;
  const current = discounted ? Math.round(list * LAUNCH_DISCOUNT.factor) : list;

  if (discounted) {
    notes.push(
      'limited-time 1080p launch discount (25%) applied — documented for the 30 s tier ' +
        '(480 → 360) and applied to the tier',
    );
  }
  if (req.aspect_ratio && req.aspect_ratio !== '16:9') {
    notes.push(
      `the published table is a 16:9 frame; no rate is published for ${req.aspect_ratio}, ` +
        'so the 16:9 rate is shown',
    );
  }
  if (req.generate_audio === false) {
    notes.push(
      'the published table is native-audio-on; whether audio off reduces cost is not ' +
        'sourced, so the cost is unchanged here',
    );
  }
  if (RESOLUTION_API.indexOf(resolution) === -1) {
    notes.push(
      `${resolution} is offered by the shipped UI and priced in the credit table, but the ` +
        'documented API resolution enum is only 480p/720p',
    );
  }
  if (duration < DURATION_MIN || duration > DURATION_MAX) {
    notes.push(`duration ${duration}s is outside the documented ${DURATION_MIN}–${DURATION_MAX}s range`);
  }

  return {
    rate,
    list,
    current,
    discounted,
    dollars: current * USD_PER_CREDIT,
    notes,
  };
}

/** Verify the linear model against every published cell. Used by the smoke test. */
export function creditTableResiduals() {
  const out = [];
  for (const [resolution, cells] of Object.entries(CREDIT_TABLE)) {
    for (const [duration, published] of Object.entries(cells)) {
      const modelled = CREDIT_RATE[resolution] * Number(duration);
      out.push({ resolution, duration: Number(duration), published, modelled, residual: modelled - published });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Prompt parsing — @Element and #move
// ---------------------------------------------------------------------------

/**
 * Parse `@Element` and `#move` tags out of a plain-language prompt.
 *
 * `@`/`#` is the *app's* surface syntax. The API's own reference tokens are
 * `<<<image_1>>>`-style; `composePrompt` performs that translation and shows it,
 * because the tutorials keep tripping over the difference.
 *
 * @param {string} text
 * @param {Array<{name:string, category?:string}>} registry
 */
export function parsePrompt(text, registry = []) {
  const byName = new Map();
  for (const el of registry) byName.set(String(el.name).toLowerCase(), el);

  const tokens = [];
  const re = /([@#])([A-Za-z0-9][A-Za-z0-9_-]*)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const sigil = m[1];
    const name = m[2];
    const kind = sigil === '@' ? 'element' : 'move';

    if (kind === 'element') {
      const hit = byName.get(name.toLowerCase());
      tokens.push({
        kind,
        sigil,
        name,
        raw: m[0],
        start: m.index,
        end: m.index + m[0].length,
        resolved: Boolean(hit),
        element: hit ?? null,
        suggestion: hit ? null : suggestName(name, registry.map((e) => e.name)),
        reason: hit ? null : `no Element named "${name}" in the registry`,
      });
    } else {
      const hit = CAMERA_MOVEMENT.indexOf(name) !== -1;
      tokens.push({
        kind,
        sigil,
        name,
        raw: m[0],
        start: m.index,
        end: m.index + m[0].length,
        resolved: hit,
        element: null,
        suggestion: hit ? null : suggestMove(name),
        reason: hit ? null : `"${name}" is not one of the ${CAMERA_MOVEMENT.length} camera moves`,
      });
    }
  }
  return tokens;
}

/** Closest camera move to a misspelling, or null. */
export function suggestMove(name) {
  return suggestName(name, CAMERA_MOVEMENT);
}

/** Closest string in `candidates` by edit distance, within a sane threshold. */
export function suggestName(name, candidates) {
  const target = String(name).toLowerCase();
  let best = null;
  let bestD = Infinity;
  for (const c of candidates) {
    const d = editDistance(target, String(c).toLowerCase());
    if (d < bestD) {
      bestD = d;
      best = c;
    }
  }
  const limit = Math.max(2, Math.floor(target.length / 2));
  return bestD <= limit ? best : null;
}

function editDistance(a, b) {
  const prev = new Array(b.length + 1);
  const cur = new Array(b.length + 1);
  for (let j = 0; j <= b.length; j++) prev[j] = j;
  for (let i = 1; i <= a.length; i++) {
    cur[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
    }
    for (let j = 0; j <= b.length; j++) prev[j] = cur[j];
  }
  return prev[b.length];
}

/**
 * Compose the final prompt: resolve `@Element` to the API's reference token,
 * append the ordered `#move` tags, and return the attachment list.
 *
 * @param {{text:string, moves?:string[], registry?:Array}} req
 */
export function composePrompt(req) {
  const text = req.text ?? '';
  const moves = req.moves ?? [];
  const registry = req.registry ?? [];
  const tokens = parsePrompt(text, registry);

  const attachments = [];
  const tokenFor = new Map();
  let unresolved = 0;
  let out = '';
  let cursor = 0;

  for (const t of tokens) {
    out += text.slice(cursor, t.start);
    cursor = t.end;

    if (t.kind === 'element' && t.resolved) {
      const key = t.element.name.toLowerCase();
      if (!tokenFor.has(key)) {
        const token = `<<<image_${attachments.length + 1}>>>`;
        tokenFor.set(key, token);
        attachments.push({
          token,
          name: t.element.name,
          category: t.element.category ?? 'unspecified',
        });
      }
      out += tokenFor.get(key);
    } else {
      if (!t.resolved) unresolved++;
      out += t.raw;
    }
  }
  out += text.slice(cursor);

  const moveTags = moves.map((mv) => `#${mv}`);
  const withMoves = moveTags.length ? `${out.trim()} ${moveTags.join(' ')}`.trim() : out.trim();

  return {
    prompt: withMoves,
    body: out.trim(),
    attachments,
    moveTags,
    tokens,
    unresolved,
    resolved_count: tokens.length - unresolved,
  };
}

// ---------------------------------------------------------------------------
// The plan
// ---------------------------------------------------------------------------

/** The Director's Panel's opening state — everything on auto, as the product ships. */
export const DEFAULT_DIRECTOR_STATE = {
  genre: AUTO,
  era: AUTO,
  pacing: AUTO,
  camera_model: AUTO,
  camera_lens: AUTO,
  camera_aperture: AUTO,
  focal_mm: FOCAL_DEFAULT,
  moves: [],
  light: AUTO,
  color_palette: AUTO,
  emotions: [],
  prompt: '',
  duration: DURATION_DEFAULT,
  resolution: '720p',
  aspect_ratio: '16:9',
  generate_audio: true,
};

/** A small demo registry, so the `@` mechanism is visible with nothing wired up. */
export const DEMO_REGISTRY = [
  { name: 'tamsincamp', category: 'character' },
  { name: 'the-diner', category: 'location' },
  { name: 'chrome-revolver', category: 'prop' },
];

/**
 * The prompt fragment each group contributes. These are panel-authored
 * descriptions of the selected look, not model prompts from the product.
 */
export function groupFragments(state) {
  const frag = {};
  const add = (key, parts) => {
    const s = parts.filter(Boolean).join(', ');
    if (s) frag[key] = s;
  };
  add('film_setup', [
    state.genre !== AUTO && `genre: ${state.genre}`,
    state.era !== AUTO && `era: ${state.era}`,
    state.pacing !== AUTO && `tempo: ${state.pacing}`,
  ]);
  add('camera', [
    state.camera_model !== AUTO && `body: ${state.camera_model}`,
    state.camera_lens !== AUTO && `lens: ${state.camera_lens}`,
    state.camera_aperture !== AUTO && `aperture: ${state.camera_aperture}`,
    // Not an API field — 4.0 dropped it. Marked so the fragment cannot be
    // mistaken for something the contract accepts.
    `focal: ${state.focal_mm}mm (engine extension — 4.0 dropped focal length)`,
  ]);
  add('lighting', [state.light !== AUTO && `lighting: ${state.light}`]);
  add('color_palette', [state.color_palette !== AUTO && `palette: ${state.color_palette}`]);
  add('camera_movement', state.moves.length ? [`moves in order: ${state.moves.join(' → ')}`] : []);
  add(
    'emotion',
    state.emotions.map(
      (e) => `${e.element}: ${e.emotion} (${intensityLabel(e.intensity)}, ${e.intensity.toFixed(2)})`,
    ),
  );
  return frag;
}

/**
 * The structured parameter block that would be sent. `auto` means the field is
 * OMITTED — the API does not accept the literal string "auto" for these enums.
 */
export function parameterBlock(state) {
  const block = {};
  for (const key of [
    'genre',
    'era',
    'pacing',
    'camera_model',
    'camera_lens',
    'camera_aperture',
    'light',
    'color_palette',
  ]) {
    if (state[key] !== AUTO) block[API_FIELDS[key]] = state[key];
  }
  if (state.moves.length) block[API_FIELDS.camera_movement] = state.moves.slice();
  block[API_FIELDS.duration] = state.duration;
  block[API_FIELDS.resolution] = state.resolution;
  block[API_FIELDS.aspect_ratio] = state.aspect_ratio;
  block[API_FIELDS.generate_audio] = state.generate_audio;
  return block;
}

/**
 * Controls this engine has that the published contract does not.
 *
 * Kept out of `parameterBlock` on purpose: sending `focal_mm` as if the API
 * accepted it would misrepresent the contract. It is a real, first-class
 * parameter of *this* engine, so it is shown — in its own block, labelled.
 */
export function extensionBlock(state) {
  return {
    focal_mm: state.focal_mm,
    _note:
      'engine extension — Cinema Studio 4.0 dropped focal length; this engine keeps it ' +
      'first-class. Not part of the published API contract.',
  };
}

/** Fields the panel deliberately does NOT send, and why. */
export function omittedFields(state) {
  const omitted = [];
  for (const key of [
    'genre',
    'era',
    'pacing',
    'camera_model',
    'camera_lens',
    'camera_aperture',
    'light',
    'color_palette',
  ]) {
    if (state[key] === AUTO) omitted.push(API_FIELDS[key]);
  }
  if (!state.moves.length) omitted.push(API_FIELDS.camera_movement);
  if (state.emotions.length) {
    omitted.push('emotion (no such field exists in the published API schema)');
  }
  return omitted;
}

/** Compose the whole plan. Pure — no DOM, no network, no generation. */
export function directorPlan(state, registry = DEMO_REGISTRY) {
  const composed = composePrompt({
    text: state.prompt,
    moves: state.moves,
    registry,
  });
  const cost = estimateCredits({
    duration: state.duration,
    resolution: state.resolution,
    aspect_ratio: state.aspect_ratio,
    generate_audio: state.generate_audio,
  });

  const warnings = [];
  if (!state.prompt.trim()) warnings.push('the prompt is empty — the API requires a non-empty prompt');
  if (composed.unresolved > 0) {
    warnings.push(`${composed.unresolved} tag(s) did not resolve and are shown in red`);
  }
  if (RESOLUTION_API.indexOf(state.resolution) === -1) {
    warnings.push(`the documented API rejects resolution "${state.resolution}"`);
  }
  if (state.duration < DURATION_MIN || state.duration > DURATION_MAX) {
    warnings.push(`duration must be ${DURATION_MIN}–${DURATION_MAX} s`);
  }
  if (state.moves.length > 1) {
    warnings.push(`the ${state.moves.length} moves run in the order shown — reorder to change the shot`);
  }

  return {
    groups: {
      film_setup: { genre: state.genre, era: state.era, pacing: state.pacing },
      camera: {
        camera_model: state.camera_model,
        camera_lens: state.camera_lens,
        camera_aperture: state.camera_aperture,
        focal_mm: state.focal_mm,
      },
      camera_movement: state.moves.slice(),
      lighting: { light: state.light },
      color_palette: { color_palette: state.color_palette },
      emotion: state.emotions.map((e) => ({ ...e })),
    },
    fragments: groupFragments(state),
    parameters: parameterBlock(state),
    extensions: extensionBlock(state),
    omitted: omittedFields(state),
    prompt: composed,    cost,
    warnings,
    sends: false,
  };
}
