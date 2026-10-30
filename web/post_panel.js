/**
 * The Post tab — Stage 5 POST.
 *
 *   Stage 5 POST   grade, extend, regional edit
 *
 * The gate this tab exists to show
 * --------------------------------
 * `CinemaGrade` takes the judge's verdict as its `corrections` input and carries
 * it into `grade_json`. It does not interpret the verdict — it *requires* it, so
 * that POST cannot execute without the judge having executed. The corrections
 * text on this tab is produced by `studio.correctionsFromReport`, which mirrors
 * `nodes._corrections` (the function behind `CinematographerCorrection`), from
 * the **Judge tab's live report**. Change a slider on the Judge tab and the text
 * here changes with it.
 *
 * What is real here
 * -----------------
 *   * The seven controls, their ranges and their neutral points come from
 *     `post.GRADE_PARAMS` / `GRADE_RANGES` / `GRADE_NEUTRAL`, via `studio.js`,
 *     which `web/parity_check.py` compares against the engine.
 *   * The delta list, the summary, the four audit rules and their weights are
 *     computed, not typed.
 *   * The corrections text is computed from the live judge report.
 *
 * What is NOT real, and is said on screen
 * ---------------------------------------
 *   * `CinemaGradeApply` is the node that changes pixels, and it takes an
 *     `IMAGE`. This panel has no image and no render, so the plan stops at
 *     `grade_json`. The footer says the same thing.
 *   * Extend and Edit describe Seedance requests. They are not made.
 */

import * as S from './studio.js';

const $ = (id) => document.getElementById(id);

/** Supplied by `app.js`: returns the Judge tab's live framing report. */
let getReport = () => ({ scores: [] });

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

const fmt = (v) => (v >= 0 ? '+' : '') + Number(v).toFixed(2);

// ---------------------------------------------------------------------------
// Reading the controls
// ---------------------------------------------------------------------------

function readGrade() {
  const settings = {};
  for (const param of S.GRADE_PARAMS) {
    const input = $(`p-grade-${param}`);
    settings[param] = input ? Number(input.value) : S.GRADE_NEUTRAL[param];
  }
  return settings;
}

function readExtend() {
  if (!$('p-extend-on')?.checked) return null;
  const result = S.extendPlan({
    mode: $('p-extend-mode')?.value ?? 'sequel',
    duration_s: Number($('p-extend-duration')?.value ?? S.DEFAULT_EXTEND_DURATION_S),
    overlap_frames: Number($('p-extend-overlap')?.value ?? 0),
  });
  return result.ok ? result.plan : { error: result.error };
}

function readEdit() {
  if (!$('p-edit-on')?.checked) return null;
  const result = S.editRegion({
    label: $('p-edit-label')?.value ?? 'region',
    bbox: ['p-edit-min-x', 'p-edit-min-y', 'p-edit-max-x', 'p-edit-max-y'].map((id) =>
      Number($(id)?.value ?? 0),
    ),
    prompt: $('p-edit-prompt')?.value ?? '',
  });
  return result.ok ? result.region : { error: result.error };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderGate() {
  const report = getReport();
  const corrections = S.correctionsText(report);
  const pre = $('p-corrections');
  const badge = $('p-gate');

  if (pre) {
    pre.textContent = corrections
      || '(empty — the judge found no failing rule, so there is nothing to correct)';
  }
  if (badge) {
    const open = corrections.length > 0;
    badge.className = `gate-badge ${open ? 'open' : 'closed'}`;
    badge.textContent = open
      ? `carrying ${S.correctionsFromReport(report).length} correction(s) into grade_json`
      : 'judge has run — no corrections to carry';
  }
  return corrections;
}

function renderGrade(corrections) {
  const settings = readGrade();
  const plan = S.applyGrade(settings);

  for (const param of S.GRADE_PARAMS) {
    const out = $(`p-grade-${param}-out`);
    if (out) out.textContent = fmt(settings[param]);
  }

  const summary = $('p-summary');
  if (summary) summary.textContent = S.gradeSummary(plan);

  const neutral = $('p-neutral');
  if (neutral) {
    neutral.innerHTML = `<span class="badge ${plan.is_noop ? 'badge-muted' : 'badge-pass'}">`
      + `<span class="badge-label">is_neutral</span>`
      + `<span class="badge-value">${plan.is_noop ? 'true' : 'false'}</span></span>`;
  }

  const json = $('p-grade-json');
  if (json) {
    json.textContent = JSON.stringify(
      { deltas: plan.deltas, count: plan.count, is_noop: plan.is_noop, corrections },
      null,
      2,
    );
  }
}

function renderExtendAndEdit(extend, edit) {
  const extendPre = $('p-extend-json');
  if (extendPre) {
    extendPre.textContent = extend === null
      ? 'null — no extension requested'
      : extend.error
        ? JSON.stringify({ error: extend.error }, null, 2)
        : JSON.stringify(extend, null, 2);
  }

  const editPre = $('p-edit-json');
  if (editPre) {
    editPre.textContent = edit === null
      ? JSON.stringify({ regions: [], count: 0 }, null, 2)
      : edit.error
        ? JSON.stringify({ error: edit.error }, null, 2)
        : JSON.stringify({ regions: [edit], count: 1 }, null, 2);
  }
}

function renderChecks(grade, extend, edit) {
  const plan = {
    grade,
    extend: extend && !extend.error ? extend : null,
    edit: edit && !edit.error ? { regions: [edit] } : null,
  };
  const checks = S.postChecks(plan);

  const box = $('p-checks');
  if (box) {
    box.innerHTML = checks
      .map((c) => {
        const cls = c.pass ? 'pass' : 'fail';
        return `<div class="rule ${cls}">`
          + '<div class="rule-head">'
          + `<span class="rule-name">${escapeHtml(c.rule)}</span>`
          + `<span class="rule-weight">w ${c.weight.toFixed(1)}</span>`
          + `<span class="rule-badge">${c.pass ? 'PASS' : 'FAIL'}</span>`
          + '</div>'
          + `<div class="rule-body"><span class="rule-target">${escapeHtml(c.detail)}</span></div>`
          + '</div>';
      })
      .join('');
  }

  const overall = $('p-overall');
  if (overall) {
    const pass = S.postOverallPass(checks);
    overall.innerHTML = `<span class="badge ${pass ? 'badge-pass' : 'badge-fail'}">`
      + `<span class="badge-label">overall</span>`
      + `<span class="badge-value">${pass ? 'PASS' : 'FAIL'}</span></span>`;
  }
}

function renderPost() {
  const corrections = renderGate();
  const grade = S.applyGrade(readGrade());
  const extend = readExtend();
  const edit = readEdit();

  renderGrade(corrections);
  renderExtendAndEdit(extend, edit);
  renderChecks(grade, extend, edit);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

let wired = false;

export function initPostPanel(opts = {}) {
  if (opts.getReport) getReport = opts.getReport;
  if (wired) {
    renderPost();
    return;
  }
  wired = true;

  // The seven controls are generated from the engine's own GRADE_PARAMS, so
  // adding an eighth in post.py adds a slider here with no edit to this file.
  const controls = $('p-grade-controls');
  if (controls) {
    controls.innerHTML = S.GRADE_PARAMS
      .map((param) => {
        const [lo, hi] = S.GRADE_RANGES[param];
        const neutral = S.GRADE_NEUTRAL[param];
        return '<div class="control">'
          + `<label for="p-grade-${param}">${param} `
          + `<output id="p-grade-${param}-out">${fmt(neutral)}</output></label>`
          + `<input id="p-grade-${param}" type="range" min="${lo}" max="${hi}" `
          + `step="0.01" value="${neutral}" />`
          + '</div>';
      })
      .join('');
  }

  const mode = $('p-extend-mode');
  if (mode) {
    mode.innerHTML = S.EXTEND_MODES.map((m) => `<option value="${m}">${m}</option>`).join('');
  }

  for (const param of S.GRADE_PARAMS) {
    $(`p-grade-${param}`)?.addEventListener('input', renderPost);
  }
  for (const id of [
    'p-extend-on', 'p-extend-mode', 'p-extend-duration', 'p-extend-overlap',
    'p-edit-on', 'p-edit-label', 'p-edit-min-x', 'p-edit-min-y', 'p-edit-max-x',
    'p-edit-max-y', 'p-edit-prompt',
  ]) {
    const el = $(id);
    if (!el) continue;
    el.addEventListener('input', renderPost);
    el.addEventListener('change', renderPost);
  }

  $('p-reset')?.addEventListener('click', () => {
    for (const param of S.GRADE_PARAMS) {
      const input = $(`p-grade-${param}`);
      if (input) input.value = String(S.GRADE_NEUTRAL[param]);
    }
    renderPost();
  });

  const provenance = $('p-provenance');
  if (provenance) {
    provenance.innerHTML =
      'Grade controls, ranges and neutral points: <code>web/studio.js</code> ↔ '
      + `<code>${escapeHtml(S.STUDIO_SOURCE.label)}</code>, checked by `
      + '<code>web/parity_check.py</code>. '
      + 'Corrections text: <code>studio.correctionsFromReport</code> ↔ '
      + '<code>nodes._corrections</code>, fed by the Judge tab\'s live report. '
      + 'Nothing is rendered and no image is touched: <code>CinemaGradeApply</code> takes an '
      + '<code>IMAGE</code>, and this page has none.';
  }

  renderPost();
}

export { renderPost };
