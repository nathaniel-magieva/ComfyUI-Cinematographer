/**
 * Cinematographer — the Studio tab: one screen, from a sentence to a verdict.
 *
 * WHY THIS TAB EXISTS
 * -------------------
 * Comfy Org's reference app (`comfy-cinematic-studio`, MIT) is 17 files and one
 * button. A stranger can use it in 30 seconds. This panel is six tabs and a node
 * graph, and needs a README. So this tab steals their *shape* — one scene box,
 * four dropdowns, one button — and runs *our* engine behind it.
 *
 * The difference is what comes back. Their app can only ever show you a string:
 * its entire "cinematic engine" is
 *
 *     [shot, scene, camera, light, look].filter(Boolean).join('. ')
 *
 * and its own UI admits the camera choices "add words to the prompt; the image
 * model does not physically simulate a lens or camera". This tab shows the
 * *measured* result instead: the nine per-frame rules, each one pass or fail,
 * with the engine's own correction lever for every rule that failed.
 *
 * WHAT IS REUSED, NOT REIMPLEMENTED
 * ---------------------------------
 * - The prompt preview calls `director.js`'s `composePrompt` through
 *   `directorPlan`. There is one parser in this panel, not two.
 * - Generate calls `run_panel.js`'s `executeLive`, which is the same probe /
 *   POST / poll / render path the Run tab uses. There is one POST path, not two.
 * - The verdict calls `panel_state.js`'s `compute`, which calls the engine
 *   mirror. Every number on screen is computed, never typed.
 *
 * WHAT IT DOES NOT DO
 * -------------------
 * It does not write to any other tab's state. It *derives* its own from the
 * panel state the Director tab owns, so switching tabs never silently changes
 * what another tab was showing. It still generates no image and no video.
 */

import * as C from './cinematographer.js';
import * as P from './panel_state.js';
import * as D from './director.js';
import * as DP from './director_panel.js';
import * as S from './studio.js';
import * as RP from './run_panel.js';
import * as CC from './comfy_client.js';

// ---------------------------------------------------------------------------
// Their vocabulary, verbatim
// ---------------------------------------------------------------------------
//
// Copied from `lib/prompt.ts` in the reference app so the four dropdowns read
// the way a stranger expects. The *options* are theirs; the *mapping* below is
// ours, and it is checked against the engine's own enums at module load.

export const SCENE_PLACEHOLDER = 'A lone astronaut finds a field of flowers on Mars…';
export const SCENE_MAX_LENGTH = 900;

/**
 * What the scene box starts with.
 *
 * Not empty, and deliberately **not** carrying an `@tag`.
 *
 * A stranger's first Generate has to come back clean, and a tag cannot
 * guarantee that: this panel resolves tags against its own demo registry, but
 * `CinemaPromptCompose` resolves them against a registry *file* on the server,
 * and on a fresh server that file does not exist. Measured on 2026-10-30:
 * `/private/tmp/ComfyUI/output/cinematographer/elements.json` was absent, so
 * the engine returned `unresolved: ["tamsincamp"]` for `@tamsincamp,` while
 * this panel's preview resolved it to `<<<image_1>>>`. A tag-free default is
 * clean on any server, and the disagreement is reported on screen when a tag
 * *is* used — see `renderPrompt` and the reconcile card.
 *
 * The greedy-`@` contract is still reported when you hit it: `tools/studio_check.mjs`
 * `[T7]` and `tools/browser_check.mjs` `[S4]` both assert it.
 */
export const SCENE_DEFAULT =
  'A lone astronaut finds a field of flowers on Mars, in the doorway of a ruined greenhouse';

export const SHOT_CHOICES = [
  'Wide establishing shot',
  'Medium shot',
  'Close-up portrait',
  'Low-angle shot',
  'Overhead shot',
];

export const CAMERA_CHOICES = [
  '35mm lens, shallow depth of field',
  'Wide-angle lens, deep focus',
  '85mm portrait lens, soft background',
  'Handheld documentary camera',
];

export const LIGHT_CHOICES = [
  'Soft window light',
  'Golden-hour backlight',
  'Hard noon sunlight',
  'Blue-hour practical lights',
];

export const LOOK_CHOICES = [
  'Warm cinematic film',
  'Cool science-fiction film',
  'Natural documentary color',
  'High-contrast noir',
];

// ---------------------------------------------------------------------------
// Their words -> our engine
// ---------------------------------------------------------------------------
//
// Each of their choices resolves to real engine values. `shot_type` is the
// engine's own COMBO; `angle` and `comp` are the panel's shot-intent toggles
// (index.html `#seg-angle` / `#seg-comp`); the rest are `director.py` enums.

const ANGLES = ['low', 'eye', 'high'];
const COMPS = ['centered', 'thirds-left', 'thirds-right'];

export const TRANSLATION = {
  shot: {
    'Wide establishing shot': { shot_type: 'wide', angle: 'eye', comp: 'thirds-left' },
    'Medium shot': { shot_type: 'medium', angle: 'eye', comp: 'thirds-left' },
    'Close-up portrait': { shot_type: 'closeup', angle: 'eye', comp: 'thirds-left' },
    'Low-angle shot': { shot_type: 'medium', angle: 'low', comp: 'thirds-left' },
    'Overhead shot': { shot_type: 'medium', angle: 'high', comp: 'thirds-left' },
  },
  camera: {
    '35mm lens, shallow depth of field': {
      camera_model: '35mm-film',
      camera_lens: 'clean-sharp',
      camera_aperture: 'f14-wide-open',
      focal_mm: 35,
    },
    'Wide-angle lens, deep focus': {
      camera_model: 'modern',
      camera_lens: 'anamorphic',
      camera_aperture: 'f11-deep-focus',
      focal_mm: 24,
    },
    '85mm portrait lens, soft background': {
      camera_model: 'modern',
      camera_lens: 'warm-vintage',
      camera_aperture: 'f14-wide-open',
      focal_mm: 85,
    },
    'Handheld documentary camera': {
      camera_model: 'dv-camcorder',
      camera_lens: 'clean-sharp',
      camera_aperture: 'f4-moderate',
      focal_mm: 35,
    },
  },
  light: {
    'Soft window light': { light: 'window' },
    'Golden-hour backlight': { light: 'contre-jour' },
    'Hard noon sunlight': { light: 'overhead-fall' },
    'Blue-hour practical lights': { light: 'practicals' },
  },
  look: {
    'Warm cinematic film': {
      color_palette: 'gasoline-sunset',
      genre: 'drama',
      era: '1990s',
    },
    'Cool science-fiction film': {
      color_palette: 'bioluminescent-night',
      genre: 'epic',
      era: '2020s',
    },
    'Natural documentary color': {
      color_palette: 'static-noon',
      genre: 'drama',
      era: '2020s',
    },
    'High-contrast noir': {
      color_palette: 'neon-rain-at-midnight',
      genre: 'noir',
      era: '1980s',
    },
  },
};

/**
 * Every mapped value must be a member of the engine's own enum.
 *
 * A hand-typed second source of truth is exactly how the emotion slug drifted
 * from the node's COMBO in task 6 — a lowercase `sadness` made ComfyUI drop
 * node 1 and everything downstream while still answering 200. This check runs
 * at module load and its result is rendered on screen, so a bad mapping is
 * loud rather than silent. `tools/browser_check.mjs` asserts it is empty.
 */
function checkMapping() {
  const errs = [];
  const has = (list, v) => Array.isArray(list) && list.indexOf(v) !== -1;

  for (const [choice, t] of Object.entries(TRANSLATION.shot)) {
    if (!has(C.SHOT_TYPES, t.shot_type)) {
      errs.push(`shot "${choice}": shot_type "${t.shot_type}" is not one of ${C.SHOT_TYPES.join(', ')}`);
    }
    if (!has(ANGLES, t.angle)) errs.push(`shot "${choice}": angle "${t.angle}" is not one of ${ANGLES.join(', ')}`);
    if (!has(COMPS, t.comp)) errs.push(`shot "${choice}": comp "${t.comp}" is not one of ${COMPS.join(', ')}`);
  }
  for (const [choice, t] of Object.entries(TRANSLATION.camera)) {
    for (const key of ['camera_model', 'camera_lens', 'camera_aperture']) {
      if (!has(D.ENUMS[key], t[key])) {
        errs.push(`camera "${choice}": ${key} "${t[key]}" is not a director.py enum member`);
      }
    }
    if (!Number.isFinite(t.focal_mm) || t.focal_mm <= 0) {
      errs.push(`camera "${choice}": focal_mm ${t.focal_mm} is not a positive number`);
    }
  }
  for (const [choice, t] of Object.entries(TRANSLATION.light)) {
    if (!has(D.ENUMS.light, t.light)) {
      errs.push(`light "${choice}": light "${t.light}" is not a director.py enum member`);
    }
  }
  for (const [choice, t] of Object.entries(TRANSLATION.look)) {
    if (!has(D.ENUMS.color_palette, t.color_palette)) {
      errs.push(`look "${choice}": color_palette "${t.color_palette}" is not a director.py enum member`);
    }
    if (!has(D.ENUMS.genre, t.genre)) {
      errs.push(`look "${choice}": genre "${t.genre}" is not a director.py enum member`);
    }
    if (!has(D.ENUMS.era, t.era)) {
      errs.push(`look "${choice}": era "${t.era}" is not a director.py enum member`);
    }
  }
  return errs;
}

export const MAPPING_ERRORS = checkMapping();

/** The nine per-frame rules, in the order the engine emits them. */
export const RULE_LABELS = {
  in_frame: 'Subject in frame',
  rule_of_thirds: 'Rule of thirds',
  headroom: 'Headroom',
  shot_size: 'Shot size',
  lead_room: 'Lead room',
  negative_space: 'Negative space',
  camera_angle: 'Camera angle',
  level: 'Level',
  direct_address: 'Direct address',
};

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let getState = () => null;
let busy = false;
let wired = false;
let lastVerdict = null;
let lastRun = null;
let lastNodeErrors = {};

/**
 * A solved camera pose this tab adopted, or null.
 *
 * Auto-frame is the correction lever made pullable. It lives here rather than
 * in the shared panel state so pressing it never changes what the Director tab
 * is showing.
 */
let solvedPose = null;

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function setStatus(html) {
  const el = $('st-status');
  if (el) el.innerHTML = html;
}

function setBusy(on) {
  for (const id of ['st-generate', 'st-autoframe', 'st-shot', 'st-camera', 'st-light', 'st-look']) {
    const el = $(id);
    if (el) el.disabled = on;
  }
  const btn = $('st-generate');
  if (btn) btn.textContent = on ? 'Generating…' : 'Generate →';
}

/** The server address is the Run tab's, so there is one place to change it. */
function baseUrl() {
  const fromRun = ($('r-base-url')?.value ?? '').trim();
  return fromRun || CC.DEFAULT_BASE_URL;
}

// ---------------------------------------------------------------------------
// Deriving this tab's state from the panel's
// ---------------------------------------------------------------------------

function readChoices() {
  return {
    scene: $('st-scene')?.value ?? '',
    shot: $('st-shot')?.value ?? SHOT_CHOICES[1],
    camera: $('st-camera')?.value ?? CAMERA_CHOICES[0],
    light: $('st-light')?.value ?? LIGHT_CHOICES[0],
    look: $('st-look')?.value ?? LOOK_CHOICES[0],
  };
}

/** Their four choices, flattened into engine values. */
export function translate(sel) {
  return {
    ...TRANSLATION.shot[sel.shot],
    ...TRANSLATION.camera[sel.camera],
    ...TRANSLATION.light[sel.light],
    ...TRANSLATION.look[sel.look],
  };
}

/**
 * The panel state this tab measures.
 *
 * The camera's *position* is inherited from the Director tab — this tab does
 * not expose azimuth, distance or height. The four dropdowns set the shot, the
 * lens, the light and the look on top of it.
 */
function studioState(sel) {
  const t = translate(sel);
  const base = getState() ?? P.createState();
  const st = structuredClone(base);

  st.shotType = t.shot_type;
  st.angle = t.angle;
  st.comp = t.comp;
  st.focalMm = t.focal_mm;

  if (solvedPose) Object.assign(st, solvedPose);
  else st.lensMode = 'focal';

  return st;
}

/** The director state this tab would send — a copy, never the shared object. */
function studioDirectorState(sel) {
  const t = translate(sel);
  return {
    ...DP.directorState,
    genre: t.genre,
    era: t.era,
    camera_model: t.camera_model,
    camera_lens: t.camera_lens,
    camera_aperture: t.camera_aperture,
    focal_mm: t.focal_mm,
    light: t.light,
    color_palette: t.color_palette,
    prompt: sel.scene,
  };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderMapping(sel) {
  const el = $('st-mapping');
  if (!el) return;

  if (MAPPING_ERRORS.length) {
    el.innerHTML =
      '<div class="warn-item warn-item-bad"><strong>This tab\'s mapping is broken.</strong> '
      + 'A choice below resolves to a value the engine does not accept, so nothing will be sent:'
      + MAPPING_ERRORS.map((e) => `<pre class="plan-pre">${escapeHtml(e)}</pre>`).join('')
      + '</div>';
    return;
  }

  const t = translate(sel);
  const row = (label, theirs, ours) =>
    `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(theirs)}</td>`
    + `<td><code>${escapeHtml(ours)}</code></td></tr>`;

  el.innerHTML =
    '<table class="map-table"><thead><tr><th>Field</th><th>Their word</th>'
    + '<th>What our engine is told</th></tr></thead><tbody>'
    + row('shot', sel.shot, `${t.shot_type} · angle ${t.angle} · ${t.comp}`)
    + row('camera', sel.camera, `${t.camera_model} · ${t.camera_lens} · ${t.camera_aperture} · ${t.focal_mm}mm`)
    + row('light', sel.light, t.light)
    + row('look', sel.look, `${t.color_palette} · ${t.genre} · ${t.era}`)
    + '</tbody></table>';
}

function renderPrompt(sel, plan, data) {
  const pre = $('st-prompt');
  const detail = $('st-prompt-detail');
  const composed = plan.prompt;

  if (pre) {
    pre.textContent = composed.prompt || '(empty — the scene box has nothing in it)';
  }
  if (!detail) return;

  const attach = composed.attachments ?? [];
  const tokens = composed.tokens ?? [];
  // `composePrompt` returns `unresolved` as a COUNT, not a list. The list of
  // which tags failed is on the tokens, each carrying the engine's own reason.
  const unresolvedCount = composed.unresolved ?? 0;
  const unresolvedTokens = tokens.filter((t) => t.kind === 'element' && !t.resolved);
  const registry = DP.getRegistry();
  const registryPath = ($('r-registry-path')?.value ?? '').trim();

  detail.innerHTML =
    `<p class="card-foot">Composed by <code>director.js</code>'s <code>composePrompt</code> — the `
    + 'same function the Shoot tab uses. There is one parser in this panel, not two.</p>'
    + `<p class="card-foot">${composed.resolved_count ?? attach.length} of `
    + `${tokens.length} <code>@tag</code>(s) resolved against this panel's `
    + `${registry.length}-entry Element registry.`
    + (unresolvedCount
      ? ` <strong>${unresolvedCount} did not resolve:</strong> `
        + unresolvedTokens
          .map((t) => `<code>${escapeHtml(t.raw)}</code>`
            + (t.reason ? ` <span class="dim">— ${escapeHtml(t.reason)}</span>` : ''))
          .join('; ')
        + '. The engine\'s <code>@</code> scanner is greedy to the next <code>@</code>, '
        + '<code>#</code> or punctuation, so a tag followed by a bare word absorbs it.'
      : '')
    + '</p>'
    + `<p class="card-foot dim">This panel resolves tags against its own `
    + `${registry.length}-entry demo registry. <strong>The engine does not.</strong> `
    + `<code>CinemaPromptCompose</code> reads a registry <em>file</em> on the server`
    + (registryPath
      ? ` — <code>${escapeHtml(registryPath)}</code>, which is what the Run tab will send.`
      : ', and the Run tab\'s registry path is empty, so it will send none.')
    + ' If that file does not exist, every <code>@tag</code> comes back unresolved from the '
    + 'engine even though this preview resolved it. The Elements tab is what writes it; the '
    + 'reconcile card below reports the disagreement when it happens.</p>'
    + `<pre class="plan-pre">${escapeHtml(JSON.stringify(composed.body, null, 2))}</pre>`
    + `<p class="card-foot dim">The measured camera this tab uses is `
    + `<code>${escapeHtml(JSON.stringify(data.camera.eye))}</code> looking at `
    + `<code>${escapeHtml(JSON.stringify(data.camera.target))}</code>, `
    + `fov ${escapeHtml(String(data.camera.fov))}°, roll ${escapeHtml(String(data.camera.roll_deg))}°.</p>`;
}

function renderVerdict(sel, st, data) {
  const head = $('st-verdict-head');
  const body = $('st-verdict');
  const lever = $('st-lever');
  if (!body) return;

  const report = data.report;
  const fails = C.failures(report);
  const weighted = data.weightedFails;
  const zone = data.zone;

  if (head) {
    const verdict = report.overall_pass ? 'PASS' : 'FAIL';
    const cls = report.overall_pass ? 'gate-badge gate-badge-pass' : 'gate-badge gate-badge-fail';
    head.innerHTML =
      `<span class="${cls}">${verdict}</span> `
      + `<code>${escapeHtml(C.summary(report))}</code>`
      + `<p class="card-foot">${report.scores.length} rules measured on this frame · `
      + `<strong>${fails.length}</strong> failing · <strong>${weighted.length}</strong> of them at or `
      + `above the ${C.OVERALL_PASS_WEIGHT} weight that decides the verdict · reliability `
      + `<strong>${escapeHtml(zone.zone)}</strong> — ${escapeHtml(zone.reason)}</p>`;
  }

  body.innerHTML =
    '<table class="rule-table"><thead><tr><th>Rule</th><th>Result</th><th>Measured</th>'
    + '<th>Target</th><th>Weight</th></tr></thead><tbody>'
    + report.scores
      .map((sc) => {
        const badge = sc.pass
          ? '<span class="gate-badge gate-badge-pass">pass</span>'
          : '<span class="gate-badge gate-badge-fail">fail</span>';
        return `<tr class="${sc.pass ? '' : 'rule-fail'}"><td><code>${escapeHtml(sc.rule)}</code> `
          + `<span class="dim">${escapeHtml(RULE_LABELS[sc.rule] ?? '')}</span></td>`
          + `<td>${badge}</td>`
          + `<td><code>${escapeHtml(C.pyG(sc.value))}</code></td>`
          + `<td>${escapeHtml(sc.target)}</td>`
          + `<td>${escapeHtml(String(sc.weight))}</td></tr>`;
      })
      .join('')
    + '</tbody></table>';

  if (!lever) return;

  const levers = C.corrections(report);
  const engineText = S.correctionsText(report);

  lever.innerHTML =
    `<p class="card-foot"><strong>${levers.length}</strong> correction lever(s) from the engine, `
    + 'verbatim. This is the part their app cannot show you: not a string, a measurement.</p>'
    + (levers.length
      ? levers.map((c) => `<div class="warn-item warn-item-bad">${escapeHtml(c)}</div>`).join('')
      : '<div class="warn-item" style="border-left-color:var(--pass);background:var(--pass-bg);'
        + 'color:#bdf0d2">Every weighted rule passes, so the engine offers no correction.</div>')
    + `<p class="card-foot dim">As one string, exactly as <code>CinematographerCorrection</code> `
    + `returns it: <code>${escapeHtml(engineText || '(empty)')}</code></p>`
    + (solvedPose
      ? '<p class="card-foot">This frame uses an <strong>auto-framed</strong> camera solved in this '
        + `tab (fov ${escapeHtml(String(solvedPose.fovDeg))}°). The lens dropdown still writes its `
        + 'lens into the prompt, but the measured frame uses the solved field of view. Changing any '
        + 'dropdown clears the solve.</p>'
      : '<p class="card-foot dim">The camera\'s position is inherited from the Director tab. '
        + '<strong>Auto-frame</strong> solves it here without changing that tab.</p>');
}

function renderGate(sel) {
  const btn = $('st-generate');
  const note = $('st-gate');
  if (!note) return;

  const reasons = [];
  if (MAPPING_ERRORS.length) reasons.push('this tab\'s mapping is broken');
  if (sel.scene.trim().length < 3) reasons.push('the scene needs at least 3 characters');
  if (!(DP.getRegistry().length)) reasons.push('the Element registry is empty, so no @tag can resolve');

  if (btn) btn.disabled = busy || reasons.length > 0;

  note.innerHTML = reasons.length
    ? `Generate is disabled: ${escapeHtml(reasons.join('; '))}.`
    : `Ready. Generate sends this to <code>${escapeHtml(baseUrl())}</code> and shows what the `
      + 'engine returned.';
}

function renderEngine(res) {
  const ran = $('st-ran');
  const taps = $('st-taps');
  const errors = $('st-errors');
  const reconcile = $('st-reconcile');

  if (!res || !res.ok) {
    if (ran) ran.textContent = '';
    if (taps) taps.innerHTML = '';
    if (reconcile) reconcile.innerHTML = '';
    if (errors) {
      errors.innerHTML = res && res.stage === 'submit'
        ? Object.entries(res.submit.node_errors ?? {})
          .map(([id, info]) => `<div class="warn-item warn-item-bad"><strong>`
            + `${escapeHtml(info?.class_type ?? '?')}</strong> (node <code>${escapeHtml(id)}</code>) `
            + 'was rejected at validation, so ComfyUI dropped it and everything downstream of it:'
            + `<pre class="plan-pre">${escapeHtml((info?.errors ?? [])
              .map((e) => e?.message ?? e?.details ?? 'invalid input').join('\n'))}</pre></div>`)
          .join('')
        : '';
    }
    return;
  }

  const record = res.record;
  const built = res.built;
  const read = CC.readTaps(record, built.taps);
  const byKey = Object.fromEntries(read.map((t) => [t.key, t.text]));
  const withValue = read.filter((t) => t.ran).length;
  const statusStr = record?.status?.status_str ?? 'unknown';
  const completed = record?.status?.completed;
  const execErrors = CC.executionErrors(record);

  if (ran) {
    ran.textContent =
      `${withValue} / ${read.length} taps returned output in this record · `
      + `status_str "${statusStr}", completed ${String(completed)}`
      + (res.rejected.length
        ? ` · ${res.rejected.length} node(s) rejected at validation and never ran`
        : '');
  }

  if (taps) {
    taps.innerHTML = read
      .map((t) => {
        const body = t.ran
          ? `<pre class="plan-pre">${escapeHtml(t.text ?? '(empty string)')}</pre>`
          : '<p class="card-foot dim">no output in this record</p>';
        return `<div class="tap-item"><div class="tap-head"><code>${escapeHtml(t.id)}</code> `
          + `${escapeHtml(t.label)}</div>${body}</div>`;
      })
      .join('');
  }

  if (errors) {
    errors.innerHTML = execErrors.length
      ? execErrors
        .map((e) => `<div class="warn-item warn-item-bad"><strong>${escapeHtml(e.node_type)}</strong> `
          + `(node <code>${escapeHtml(e.node_id)}</code>) raised:`
          + `<pre class="plan-pre">${escapeHtml(e.message)}</pre></div>`)
        .join('')
      : '';
  }

  if (reconcile) {
    const panelReport = res.input.panelReport;
    const rows = [];
    if (panelReport) {
      rows.push(['framing verdict', C.summary(panelReport), byKey.evaluate]);
      rows.push(['corrections text', S.correctionsText(panelReport), byKey.corrections]);
    }
    rows.push(['grade summary', S.gradeSummary(S.applyGrade(res.input.grade)), byKey.grade]);

    const same = rows.filter((r) => r[1] === r[2]).length;
    const comparable = rows.filter((r) => r[2] !== null && r[2] !== undefined).length;

    // Tags are the one place the panel and the engine are expected to disagree:
    // this panel resolves against its own demo registry, `CinemaPromptCompose`
    // against a registry file on the server. Compare them explicitly instead of
    // letting a green "3 of 3 identical" imply the whole run agreed.
    const panelUnresolved = res.input.panelUnresolved ?? null;
    let engineUnresolved = null;
    try {
      const parsed = JSON.parse(byKey.unresolved ?? 'null');
      if (Array.isArray(parsed)) engineUnresolved = parsed;
    } catch { engineUnresolved = null; }

    const tagRow = (panelUnresolved === null || engineUnresolved === null)
      ? ''
      : (panelUnresolved === engineUnresolved.length
        ? `<div class="warn-item" style="border-left-color:var(--pass);background:var(--pass-bg);`
          + `color:#bdf0d2">@tags: <strong>the panel and the engine agree</strong> — `
          + `${panelUnresolved} unresolved on both sides.</div>`
        : `<div class="warn-item warn-item-bad">@tags: <strong>the panel and the engine disagree</strong>.`
          + `<br />panel resolved all but <code>${panelUnresolved}</code> against its own `
          + `${DP.getRegistry().length}-entry demo registry.`
          + `<br />engine: <code>${escapeHtml(byKey.unresolved ?? '')}</code>`
          + `<br />The engine reads a registry <em>file</em> on the server; this panel reads its `
          + 'own list. If that file is missing, every tag comes back unresolved here even though '
          + 'the preview above resolved it. The Elements tab is what writes the file.</div>');

    reconcile.innerHTML =
      `<p class="card-foot"><strong>${same} of ${comparable}</strong> comparable strings are `
      + 'identical between this tab and the engine that just ran. The verdict above is the '
      + 'panel\'s; this is the server\'s, and they are compared rather than assumed equal.</p>'
      + rows
        .map(([label, mine, theirs]) => {
          if (theirs === null || theirs === undefined) {
            return `<div class="warn-item">${escapeHtml(label)}: the engine returned no value, so `
              + 'nothing can be compared.</div>';
          }
          return mine === theirs
            ? `<div class="warn-item" style="border-left-color:var(--pass);background:var(--pass-bg);`
              + `color:#bdf0d2">${escapeHtml(label)}: <strong>identical</strong>.</div>`
            : `<div class="warn-item warn-item-bad">${escapeHtml(label)}: <strong>differs</strong>.`
              + `<br />panel: <code>${escapeHtml(mine)}</code>`
              + `<br />engine: <code>${escapeHtml(theirs)}</code></div>`;
        })
        .join('')
      + tagRow;
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/** Solve a camera for this shot and adopt it locally. */
function autoFrameNow() {
  const sel = readChoices();
  const st = studioState(sel);
  const solved = P.applyAutoFrame(st);

  solvedPose = {
    azimuthDeg: st.azimuthDeg,
    distance: st.distance,
    height: st.height,
    aim: st.aim,
    rollDeg: st.rollDeg,
    lensMode: st.lensMode,
    fovDeg: st.fovDeg,
  };

  renderStudio();
  setStatus(
    `Auto-frame ${solved.converged ? '<strong>converged</strong>' : '<strong>did NOT converge</strong>'} `
    + `after ${solved.iterations} iteration(s)`
    + (solved.converged
      ? '.'
      : `; residual ${escapeHtml(JSON.stringify(solved.residual))}. The frame below is the `
        + 'solver\'s last iterate, not a compliant frame.'),
  );
}

async function generate() {
  if (busy) return;

  const sel = readChoices();
  if (MAPPING_ERRORS.length) {
    setStatus('This tab\'s mapping is broken, so <strong>nothing was sent</strong>.');
    return;
  }
  if (sel.scene.trim().length < 3) {
    setStatus('The scene needs at least 3 characters. <strong>Nothing was sent.</strong>');
    return;
  }

  busy = true;
  setBusy(true);
  lastRun = null;
  lastNodeErrors = {};

  const base = baseUrl();

  try {
    const res = await RP.executeLive(
      base,
      () => {
        // Derived, not mutated: the shared panel state is left exactly as the
        // Director tab had it.
        const collected = RP.collect();
        const st = studioState(sel);
        const data = P.compute(st);
        return {
          ...collected,
          director: studioDirectorState(sel),
          subject: st.subject,
          camera: data.camera,
          intent: data.intent,
          shotType: st.shotType,
          action: sel.scene,
          panelReport: data.report,
          // What this panel's own parser made of the tags, so the reconcile card
          // can compare it with the engine's `unresolved` tap. Same arguments
          // `directorPlan` uses for the preview above, and `composePrompt`
          // returns a COUNT here, not a list.
          panelUnresolved: D.composePrompt({
            text: sel.scene, moves: DP.directorState.moves, registry: DP.getRegistry(),
          }).unresolved,
        };
      },
      {
        onStatus: (stage, d) => {
          if (stage === 'probe') setStatus(`Checking <code>${escapeHtml(base)}</code> …`);
          else if (stage === 'built') {
            setStatus(`Submitting ${d.built.nodeCount} nodes to <code>${escapeHtml(base)}</code> …`);
          } else if (stage === 'queued') {
            lastNodeErrors = d.submit.node_errors ?? {};
            setStatus(
              d.rejected.length
                ? `ComfyUI <strong>accepted</strong> the prompt as `
                  + `<code>${escapeHtml(d.submit.prompt_id)}</code> but rejected `
                  + `<strong>${d.rejected.length} node(s)</strong> at validation. Those nodes and `
                  + 'everything downstream of them were dropped, so this is a partial run.'
                : `Queued <code>${escapeHtml(d.submit.prompt_id)}</code> · polling `
                  + '<code>/history</code> …',
            );
          }
        },
      },
    );

    lastRun = res;

    if (!res.ok) {
      if (res.stage === 'probe') {
        setStatus(
          `No ComfyUI answered at <code>${escapeHtml(base)}</code> — `
          + `${escapeHtml(res.probe.error)}. <strong>Nothing was sent.</strong> The verdict above is `
          + 'still real: it is computed here, not by the server.',
        );
      } else if (res.stage === 'classes') {
        setStatus(
          `The server does not know ${res.unknown.length} class(es): `
          + `<code>${escapeHtml(res.unknown.join(', '))}</code>. <strong>Not sending.</strong>`,
        );
      } else if (res.stage === 'submit') {
        setStatus(escapeHtml(CC.describeSubmitFailure(res.submit)));
      } else if (res.stage === 'history') {
        setStatus(
          `Submitted as <code>${escapeHtml(res.submit.prompt_id)}</code>, but `
          + `${escapeHtml(res.error)}. Nothing is claimed about its result.`,
        );
      }
      renderEngine(res);
      return;
    }

    const statusStr = res.record?.status?.status_str ?? 'unknown';
    const completed = res.record?.status?.completed;
    const ran = CC.countRan(res.record, res.built.taps);
    const ok = statusStr === 'success' && completed === true;

    setStatus(
      (ok
        ? `ComfyUI ran it: <code>status_str: "success"</code>, <code>completed: true</code>, `
          + `<strong>${ran} / ${res.built.taps.length}</strong> taps returned output in this record.`
        : `ComfyUI ran it and it <strong>failed</strong>: <code>status_str: `
          + `"${escapeHtml(statusStr)}"</code>, <code>completed: ${escapeHtml(String(completed))}`
          + '</code>. The engine\'s own error is below, verbatim.')
      + (res.rejected.length
        ? ` <strong>${res.rejected.length} node(s) were rejected at validation and never ran</strong>, `
          + 'so this is a partial run, not a clean one.'
        : '')
      + ' No image and no video were generated.',
    );

    renderEngine(res);
  } catch (err) {
    setStatus(
      `The run threw: ${escapeHtml(err?.message ?? err)}. Nothing is claimed about the result.`,
    );
  } finally {
    busy = false;
    setBusy(false);
    renderGate(readChoices());
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

/** Recompute everything this tab shows. Returns the derivation it used. */
export function renderStudio() {
  const sel = readChoices();
  const st = studioState(sel);
  const data = P.compute(st);
  const plan = D.directorPlan(studioDirectorState(sel), DP.getRegistry());

  lastVerdict = { sel, state: st, data, plan };
  renderMapping(sel);
  renderPrompt(sel, plan, data);
  renderVerdict(sel, st, data);
  renderGate(sel);
  return lastVerdict;
}

export function initStudioPanel(opts = {}) {
  if (typeof opts.getState === 'function') getState = opts.getState;

  const scene = $('st-scene');
  if (scene) {
    scene.maxLength = SCENE_MAX_LENGTH;
    scene.placeholder = SCENE_PLACEHOLDER;
    if (!scene.value.trim()) scene.value = SCENE_DEFAULT;
  }

  const fill = (id, choices) => {
    const el = $(id);
    if (!el) return;
    el.innerHTML = choices
      .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
      .join('');
  };
  fill('st-shot', SHOT_CHOICES);
  fill('st-camera', CAMERA_CHOICES);
  fill('st-light', LIGHT_CHOICES);
  fill('st-look', LOOK_CHOICES);

  if (!wired) {
    wired = true;
    $('st-generate')?.addEventListener('click', () => { generate(); });
    $('st-autoframe')?.addEventListener('click', () => { autoFrameNow(); });

    for (const id of ['st-scene', 'st-shot', 'st-camera', 'st-light', 'st-look']) {
      const el = $(id);
      if (!el) continue;
      el.addEventListener('input', () => {
        // Changing a choice invalidates a solve: the solve was for the old one.
        if (id !== 'st-scene') solvedPose = null;
        renderStudio();
      });
      el.addEventListener('change', () => {
        if (id !== 'st-scene') solvedPose = null;
        renderStudio();
      });
    }
  }

  renderStudio();
}

// ---------------------------------------------------------------------------
// Read-only accessors for the tools
// ---------------------------------------------------------------------------

export function studioVerdict() {
  if (!lastVerdict) return null;
  const { report, zone, weightedFails } = lastVerdict.data;
  return {
    summary: C.summary(report),
    overall_pass: report.overall_pass,
    rules: report.scores.map((sc) => ({ rule: sc.rule, pass: sc.pass, value: sc.value, weight: sc.weight })),
    failures: C.failures(report).map((sc) => sc.rule),
    weighted_failures: weightedFails.map((sc) => sc.rule),
    levers: C.corrections(report),
    corrections_text: S.correctionsText(report),
    zone: zone.zone,
    shot_type: report.shot_type,
  };
}

export function studioPrompt() {
  return lastVerdict?.plan?.prompt?.prompt ?? '';
}

export function studioTranslation() {
  return lastVerdict ? translate(lastVerdict.sel) : null;
}

export function lastStudioRun() {
  return lastRun;
}

export function studioNodeErrors() {
  return lastNodeErrors;
}

export function isSolved() {
  return Boolean(solvedPose);
}
