/**
 * The Run tab — hand the panel's current state to a live ComfyUI.
 *
 * What this tab actually does
 * ---------------------------
 *   * Builds a real ComfyUI **API-format** prompt from the five other tabs'
 *     current state, and shows the exact JSON. That part needs no server at all.
 *   * On request, POSTs it to `<base>/prompt`, polls `<base>/history/<id>`, and
 *     renders the strings the engine returned.
 *
 * The graph has to end in an output node
 * --------------------------------------
 * ComfyUI rejects a prompt with no UI output (`prompt_no_outputs`, HTTP 400).
 * The pack's only `OUTPUT_NODE` is `CinemaElementSave`, which writes to disk —
 * so a graph made only of the pack's nodes cannot be run at all. Every graph
 * here therefore terminates in `PreviewAny` taps, one per value worth reading.
 * Those taps are also the *only* honest way to count what ran: our nodes return
 * plain STRING/BOOLEAN and never appear in `history.outputs`.
 *
 * A run is also a parity check
 * ----------------------------
 * The report is produced by the **server**, not shipped from the panel: the
 * graph wires `CinematographerEvaluate` -> `CinematographerCorrection` and lets
 * the engine make its own verdict. The panel then compares that verdict, the
 * corrections text and the grade summary against its own mirrors, string for
 * string, and says on screen whether they agree. Translating one shape into the
 * other would let a shape bug masquerade as agreement.
 *
 * What is NOT real, and is said on screen
 * ---------------------------------------
 *   * No image and no video. The pack ships no `IMAGE` node, so
 *     `CinemaGradeApply` has nothing to consume. A run returns text, not pixels.
 *   * If the server cannot be reached, this tab says so and sends nothing. It
 *     never reports a result it did not receive.
 */

import * as C from './cinematographer.js';
import * as P from './panel_state.js';
import * as D from './director.js';
import * as S from './studio.js';
import * as DP from './director_panel.js';
import * as EP from './elements_panel.js';
import * as PP from './post_panel.js';
import * as CC from './comfy_client.js';

const $ = (id) => document.getElementById(id);

/** Supplied by `app.js`: the panel's live state object. */
let getState = () => null;

/** The last successful `/system_stats` probe, so the notes can cite real facts. */
let lastProbe = null;

/** The last graph built, so a run sends exactly what the JSON pane shows. */
let lastBuilt = null;

/** The last `/history` record received, so a check can inspect what really came back. */
let lastRecordValue = null;

/**
 * The `node_errors` from the last submit.
 *
 * A 200 with a `prompt_id` is not a clean bill of health: ComfyUI validates each
 * output node separately and drops the ones that fail, naming them only here.
 * Kept so a check can assert the last run was whole rather than merely accepted.
 */
let lastNodeErrorsValue = {};

let busy = false;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/**
 * The inverse of `studio.parsePalette`.
 *
 * `elementRecords()` hands back a parsed `number[][]`, but `CinemaElementSave`
 * takes the raw `"r,g,b;r,g,b"` string. This is a formatter, not a second
 * parser — the parsing stays in `studio.js`.
 */
function paletteText(palette) {
  if (!Array.isArray(palette) || !palette.length) return '';
  return palette
    .map((c) => (Array.isArray(c) ? c.join(',') : String(c)))
    .join(';');
}

// ---------------------------------------------------------------------------
// Reading the panel's state
// ---------------------------------------------------------------------------

/** Everything `comfy_client.buildGraph` needs, read from the live tabs. */
function collect() {
  const state = getState();
  const data = state ? P.compute(state) : null;
  const director = DP.directorState;
  const registryPath = ($('r-registry-path')?.value ?? '').trim();
  const writeElements = Boolean($('r-write-elements')?.checked);

  return {
    director,
    subject: state?.subject,
    camera: data?.camera,
    intent: data?.intent,
    shotType: state?.shotType,
    action: $('s-action')?.value ?? '',
    moves: director?.moves ?? [],
    grade: PP.readGrade(),
    registryPath,
    elements: writeElements
      ? EP.elementRecords().map((r) => ({ ...r, palette: paletteText(r.palette) }))
      : null,
    panelReport: data?.report ?? null,
  };
}

// ---------------------------------------------------------------------------
// Rendering the prompt
// ---------------------------------------------------------------------------

function renderNotes(notes) {
  const el = $('r-notes');
  if (!el) return;
  if (!notes.length) {
    el.textContent = 'No caveats: every field the panel holds was sent.';
    return;
  }
  el.innerHTML = notes.map((n) => `&bull; ${escapeHtml(n)}`).join('<br />');
}

function renderRegistryNote(input) {
  const el = $('r-registry-note');
  if (!el) return;
  const path = input.registryPath;

  if (!path) {
    el.innerHTML =
      'Registry path is <strong>empty</strong>. That is a real, silent difference: ' +
      '<code>CinemaPromptCompose</code> then loads <strong>no registry</strong>, so every ' +
      '<code>@tag</code> comes back unresolved, and <code>CinemaElementSave</code> writes ' +
      'sidecars but never saves the registry. Press <strong>Check server</strong> to fill in ' +
      'the path the server itself would use.';
    return;
  }

  const serverDefault = lastProbe?.registryDefault ?? '';
  const isDefault = Boolean(serverDefault) && path === serverDefault;
  el.innerHTML =
    `Sending <code>${escapeHtml(path)}</code> — `
    + (isDefault
      ? "the server's own default, read back from <code>/object_info</code>."
      : "typed by hand; the server's own default is "
        + `<code>${escapeHtml(serverDefault || '(not published)')}</code>.`);
}

function renderServerStatus(probe) {
  const el = $('r-server-status');
  if (!el) return;
  if (!probe?.ok) {
    el.innerHTML =
      `No ComfyUI at <code>${escapeHtml(probe?.base ?? '')}</code> — `
      + `${escapeHtml(probe?.error ?? 'unreachable')}.`;
    return;
  }
  const cine = probe.classes.filter((c) => c.startsWith('Cinema')).length;
  el.innerHTML =
    `ComfyUI <strong>${escapeHtml(probe.version)}</strong> on ${escapeHtml(probe.os)} &middot; `
    + `${probe.classes.length} node classes, <strong>${cine}</strong> of them Cinematographer &middot; `
    + `registry default <code>${escapeHtml(probe.registryDefault || '(none published)')}</code>`;
}

/** Build the graph from current state and show it. Returns the build. */
export function renderRun() {
  const input = collect();
  const built = CC.buildGraph(input);
  lastBuilt = built;

  const pre = $('r-json');
  if (pre) pre.textContent = JSON.stringify(built.graph, null, 2);

  const stats = $('r-graph-stats');
  if (stats) {
    stats.textContent =
      `${built.nodeCount} nodes · ${built.classTypes.length} classes · `
      + `${built.previewCount} PreviewAny taps`;
  }

  const notes = [...built.notes];
  if (!input.registryPath) {
    notes.push(
      'the registry path is empty, so no @tag can resolve on the server — see the note ' +
        'under the server card',
    );
  }
  if (!input.action.trim()) {
    notes.push('the action string is empty; CinemaPromptCompose requires a non-empty prompt');
  }
  renderNotes(notes);
  renderRegistryNote(input);

  const label = $('r-write-label');
  if (label) {
    const n = EP.elementRecords().length;
    label.textContent = `also write this panel's ${n} Element(s) to the server`;
  }

  return built;
}

// ---------------------------------------------------------------------------
// Rendering a result
// ---------------------------------------------------------------------------

function renderTaps(record, built) {
  const box = $('r-taps');
  const ran = $('r-ran');
  if (!box) return;

  const cachedNodes = new Set(cachedNodeIds(record));
  const taps = CC.readTaps(record, built.taps);
  const withValue = taps.filter((t) => t.ran).length;
  const fromCache = taps.filter((t) => !t.ran && cachedNodes.has(String(t.id))).length;

  if (ran) {
    ran.textContent =
      `${withValue} / ${taps.length} taps returned output in this record`
      + (fromCache ? ` · ${fromCache} more were served from ComfyUI's execution cache` : '');
  }

  box.innerHTML = taps
    .map((t) => {
      // A tap with no value must say *why*. ComfyUI re-emits a cached node's UI,
      // so an empty tap usually means the node was neither run nor reported as
      // cached — but guessing would be worse than saying which it is.
      let body;
      if (t.ran) {
        body = `<pre class="plan-pre">${escapeHtml(t.text ?? '(empty string)')}</pre>`;
      } else if (cachedNodes.has(String(t.id))) {
        body =
          '<p class="card-foot dim">served from ComfyUI\'s execution cache — this run reused an '
          + 'earlier identical result, so no new output was emitted for this node</p>';
      } else {
        body =
          '<p class="card-foot dim">no output in this record — ComfyUI neither ran this node nor '
          + 'reported it as cached</p>';
      }
      return (
        `<div class="tap-item"><div class="tap-head"><code>${escapeHtml(t.id)}</code> `
        + `${escapeHtml(t.label)}</div>${body}</div>`
      );
    })
    .join('');
}

/** The node ids ComfyUI reported as served from its execution cache. */
function cachedNodeIds(record) {
  const msg = (record?.status?.messages ?? []).find(
    (m) => Array.isArray(m) && m[0] === 'execution_cached',
  );
  const nodes = msg?.[1]?.nodes;
  return Array.isArray(nodes) ? nodes.map(String) : [];
}

function renderErrors(errors) {
  const box = $('r-errors');
  if (!box) return;
  if (!errors.length) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = errors
    .map((e) => {
      const what = e.phase === 'validation'
        ? 'was rejected at validation, so ComfyUI dropped it and everything downstream of it:'
        : 'raised:';
      return `<div class="warn-item warn-item-bad"><strong>${escapeHtml(e.node_type)}</strong> `
        + `(node <code>${escapeHtml(e.node_id)}</code>) ${what}`
        + `<pre class="plan-pre">${escapeHtml(e.message)}</pre></div>`;
    })
    .join('');
}

/**
 * `POST /prompt` node errors, which arrive BEFORE anything executes.
 *
 * These are not execution errors: ComfyUI validates each output node on its own,
 * drops the ones that fail, and runs the rest — answering 200 with a
 * `prompt_id` either way. They are kept separate from `executionErrors` only so
 * the panel can say which of the two happened; both are rendered together.
 */
function nodeErrorEntries(nodeErrors) {
  return Object.entries(nodeErrors ?? {}).map(([id, info]) => ({
    node_id: id,
    node_type: info?.class_type ?? '?',
    phase: 'validation',
    message:
      (info?.errors ?? [])
        .map((e) => e?.message ?? e?.details ?? 'invalid input')
        .join('\n') || 'invalid input',
  }));
}

/** `POST /prompt` node errors, which arrive before anything executes. */
function renderNodeErrors(nodeErrors) {
  renderErrors(nodeErrorEntries(nodeErrors));
}

function compare(label, mine, theirs) {
  if (theirs === null || theirs === undefined) return { label, state: 'missing', mine, theirs };
  return { label, state: mine === theirs ? 'same' : 'differs', mine, theirs };
}

function renderReconcile(record, built, input) {
  const el = $('r-reconcile');
  if (!el) return;

  const byKey = Object.fromEntries(CC.readTaps(record, built.taps).map((t) => [t.key, t.text]));
  const rows = [];

  if (input.panelReport) {
    rows.push(compare('framing verdict', C.summary(input.panelReport), byKey.evaluate));
    rows.push(compare('corrections text', S.correctionsText(input.panelReport), byKey.corrections));
  }
  rows.push(compare('grade summary', S.gradeSummary(S.applyGrade(input.grade)), byKey.grade));

  const same = rows.filter((r) => r.state === 'same').length;
  const comparable = rows.filter((r) => r.state !== 'missing').length;

  const head =
    `<p class="card-foot"><strong>${same} of ${comparable}</strong> comparable strings are `
    + `identical between the panel and the engine.</p>`;

  const body = rows
    .map((r) => {
      if (r.state === 'missing') {
        return (
          `<div class="warn-item">${escapeHtml(r.label)}: the engine returned no value for this `
          + 'tap, so nothing can be compared.</div>'
        );
      }
      if (r.state === 'same') {
        return (
          `<div class="warn-item" style="border-left-color:var(--pass);background:var(--pass-bg);color:#bdf0d2">`
          + `${escapeHtml(r.label)}: <strong>identical</strong> — the panel and the engine produced `
          + 'the same string.</div>'
        );
      }
      return (
        `<div class="warn-item warn-item-bad">${escapeHtml(r.label)}: <strong>differs</strong>.`
        + `<br />panel: <code>${escapeHtml(r.mine)}</code>`
        + `<br />engine: <code>${escapeHtml(r.theirs)}</code></div>`
      );
    })
    .join('');

  // The composed prompt is expected to differ, and saying so is the point.
  let promptNote = '';
  if (byKey.final_prompt !== null && byKey.final_prompt !== undefined) {
    const mine = D.composePrompt({
      text: input.action,
      moves: input.moves,
      registry: DP.getRegistry(),
    }).prompt;
    promptNote =
      mine === byKey.final_prompt
        ? '<p class="card-foot">The composed prompt is byte-identical too.</p>'
        : '<p class="card-foot dim">The composed prompt is <strong>not</strong> identical, and that '
          + 'is expected: the panel substitutes <code>&lt;&lt;&lt;image_N&gt;&gt;&gt;</code> inline '
          + 'where <code>prompt.py</code> appends the <code>@name</code> tags at the end, and the '
          + "engine's <code>@</code> scanner is greedy where the panel's is not. Both strings are "
          + 'shown above rather than reconciled.</p>';
  }

  el.innerHTML = head + body + promptNote;
}

function renderResult(base, promptId, record, built, input, rejectedCount = 0, nodeErrors = {}) {
  lastRecordValue = record;

  const statusStr = record?.status?.status_str ?? 'unknown';
  const completed = record?.status?.completed;
  const errors = CC.executionErrors(record);
  const ran = CC.countRan(record, built.taps);
  const cachedIds = cachedNodeIds(record);

  const status = $('r-run-status');
  if (status) {
    const ok = statusStr === 'success' && completed === true;
    const partial = rejectedCount
      ? ` <strong>${rejectedCount} node(s) were rejected at validation and never ran</strong>, so `
        + 'this is a partial run, not a clean one.'
      : '';
    status.innerHTML = ok
      ? `ComfyUI ran it: <code>status_str: "success"</code>, <code>completed: true</code>, `
        + `<strong>${ran} / ${built.taps.length}</strong> taps returned output in this record.`
        + (cachedIds.length
          ? ` ComfyUI served ${cachedIds.length} node(s) from its execution cache.`
          : '')
        + partial
      : `ComfyUI ran it and it <strong>failed</strong>: `
        + `<code>status_str: "${escapeHtml(statusStr)}"</code>, `
        + `<code>completed: ${escapeHtml(String(completed))}</code>. The engine's own error is `
        + 'below, verbatim.'
        + partial;
  }

  renderTaps(record, built);
  // Validation rejections and execution errors are both "what went wrong", and
  // the validation ones arrive before the run, so they would be lost if this
  // only rendered `executionErrors(record)`.
  renderErrors([...nodeErrorEntries(nodeErrors), ...errors]);
  renderReconcile(record, built, input);

  const live = $('provenance-live');
  if (live) {
    live.textContent =
      `Last run: prompt ${promptId} against ${base} — status_str "${statusStr}", `
      + `${ran} / ${built.taps.length} taps returned output. No image and no video were generated.`;
  }
}

// ---------------------------------------------------------------------------
// Running
// ---------------------------------------------------------------------------

function setBusy(on) {
  for (const id of ['r-run', 'r-build', 'r-check', 'r-use-default']) {
    const b = $(id);
    if (b) b.disabled = on;
  }
}

function baseUrl() {
  return ($('r-base-url')?.value ?? '').trim() || CC.DEFAULT_BASE_URL;
}

async function checkServer() {
  const base = baseUrl();
  const el = $('r-server-status');
  if (el) el.textContent = `Checking ${base} …`;
  const probe = await CC.probeServer(base);
  lastProbe = probe;
  renderServerStatus(probe);

  const pathInput = $('r-registry-path');
  if (probe.ok && probe.registryDefault && !(pathInput?.value ?? '').trim()) {
    pathInput.value = probe.registryDefault;
  }
  renderRun();
  return probe;
}

async function useServerDefault() {
  const probe = lastProbe?.ok ? lastProbe : await checkServer();
  const input = $('r-registry-path');
  if (input) input.value = probe?.registryDefault || CC.FALLBACK_REGISTRY_PATH;
  renderRun();
}

/**
 * The whole live pipeline, with no DOM in it.
 *
 * `runLive` renders this; the Studio tab renders the same result its own way.
 * There is exactly one probe, one POST, one poll and one place where
 * `node_errors` is read — a second copy of this sequence would be a second
 * chance to disagree about what a 200 means.
 *
 * `makeInput(probe)` is called only after the probe succeeds, so a caller can
 * fill in a registry path the server published before building the graph.
 * `opts.onStatus(stage, data)` fires at each step boundary; stages are
 * `probe`, `built`, `queued`, `done`.
 *
 * Returns a discriminated result. `ok: false` carries `stage` and whatever was
 * learned up to that point; it never throws for an expected failure.
 */
export async function executeLive(base, makeInput, opts = {}) {
  const onStatus = typeof opts.onStatus === 'function' ? opts.onStatus : () => {};

  onStatus('probe', { base });
  const probe = await CC.probeServer(base);
  if (!probe.ok) return { ok: false, stage: 'probe', probe };

  const input = makeInput(probe);
  const built = CC.buildGraph(input);
  onStatus('built', { probe, built, input });

  const unknown = built.classTypes.filter((c) => !probe.classes.includes(c));
  if (unknown.length) return { ok: false, stage: 'classes', probe, built, input, unknown };

  const submit = await CC.submitPrompt(base, built.graph, CC.newClientId());
  if (!submit.ok) return { ok: false, stage: 'submit', probe, built, input, submit };

  // A 200 with a prompt_id is NOT a clean bill of health. ComfyUI validates
  // each output node separately: an output that fails validation is dropped
  // from the run and named only in `node_errors`, and the prompt still runs.
  // Reporting "success" without that would be a fabricated pass.
  const rejected = Object.entries(submit.node_errors ?? {});
  onStatus('queued', { probe, built, input, submit, rejected });

  const hist = await CC.awaitHistory(base, submit.prompt_id);
  if (!hist.ok) {
    return { ok: false, stage: 'history', probe, built, input, submit, rejected, error: hist.error };
  }

  const result = {
    ok: true,
    stage: 'done',
    probe,
    built,
    input,
    submit,
    rejected,
    record: hist.record,
  };
  onStatus('done', result);
  return result;
}

async function runLive() {
  if (busy) return;
  busy = true;
  setBusy(true);

  const base = baseUrl();
  const status = $('r-run-status');
  const setStatus = (html) => {
    if (status) status.innerHTML = html;
  };

  try {
    const res = await executeLive(
      base,
      (probe) => {
        lastProbe = probe;
        renderServerStatus(probe);
        const pathInput = $('r-registry-path');
        if (!(pathInput?.value ?? '').trim() && probe.registryDefault) {
          pathInput.value = probe.registryDefault;
        }
        return collect();
      },
      {
        onStatus: (stage, d) => {
          if (stage === 'probe') {
            setStatus(`Checking <code>${escapeHtml(base)}</code> …`);
          } else if (stage === 'built') {
            lastBuilt = d.built;
            renderRun();
            setStatus(`Submitting ${d.built.nodeCount} nodes to <code>${escapeHtml(base)}</code> …`);
          } else if (stage === 'queued') {
            lastNodeErrorsValue = d.submit.node_errors ?? {};
            if (d.rejected.length) {
              renderNodeErrors(d.submit.node_errors);
              setStatus(
                `ComfyUI <strong>accepted</strong> the prompt as `
                + `<code>${escapeHtml(d.submit.prompt_id)}</code> but rejected `
                + `<strong>${d.rejected.length} node(s)</strong> at validation. Those nodes and `
                + 'everything downstream of them were dropped from the run, so the taps below are '
                + 'only part of the graph. The engine\'s own reasons are listed under "What the '
                + 'engine returned".',
              );
            } else {
              setStatus(
                `Queued <code>${escapeHtml(d.submit.prompt_id)}</code> · polling `
                + '<code>/history</code> …',
              );
            }
          }
        },
      },
    );

    if (!res.ok) {
      if (res.stage === 'probe') {
        setStatus(
          `No ComfyUI answered at <code>${escapeHtml(base)}</code> — ${escapeHtml(res.probe.error)}. `
          + '<strong>Nothing was sent.</strong> The prompt JSON on the right is complete: paste it '
          + "into ComfyUI's API workflow, or start the server and press Run again.",
        );
      } else if (res.stage === 'classes') {
        setStatus(
          `The server does not know ${res.unknown.length} class(es): `
          + `<code>${escapeHtml(res.unknown.join(', '))}</code>. <strong>Not sending</strong> — a `
          + 'graph with an unknown class would be rejected.',
        );
      } else if (res.stage === 'submit') {
        setStatus(escapeHtml(CC.describeSubmitFailure(res.submit)));
        renderNodeErrors(res.submit.node_errors);
      } else if (res.stage === 'history') {
        setStatus(
          `Submitted as <code>${escapeHtml(res.submit.prompt_id)}</code>, but `
          + `${escapeHtml(res.error)}. The run may still be executing; nothing is claimed about `
          + 'its result.',
        );
      }
      return;
    }

    renderResult(
      base,
      res.submit.prompt_id,
      res.record,
      res.built,
      res.input,
      res.rejected.length,
      res.submit.node_errors,
    );
  } catch (err) {
    setStatus(
      `The run threw: ${escapeHtml(err?.message ?? err)}. Nothing is claimed about the result.`,
    );
  } finally {
    busy = false;
    setBusy(false);
  }
}

async function copyJson() {
  const text = $('r-json')?.textContent ?? '';
  const hint = $('r-graph-stats');
  try {
    await navigator.clipboard.writeText(text);
    if (hint) hint.textContent = `copied ${text.length} characters`;
  } catch (err) {
    if (hint) {
      hint.textContent = `clipboard unavailable (${err?.message ?? err}) — select the JSON by hand`;
    }
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

let wired = false;

export function initRunPanel(opts = {}) {
  if (opts.getState) getState = opts.getState;
  if (wired) return;
  wired = true;

  $('r-run')?.addEventListener('click', runLive);
  $('r-build')?.addEventListener('click', () => renderRun());
  $('r-check')?.addEventListener('click', () => {
    checkServer();
  });
  $('r-use-default')?.addEventListener('click', () => {
    useServerDefault();
  });
  $('r-copy')?.addEventListener('click', copyJson);

  $('r-base-url')?.addEventListener('change', () => {
    lastProbe = null;
    renderRun();
  });
  $('r-registry-path')?.addEventListener('input', renderRun);
  $('r-write-elements')?.addEventListener('change', renderRun);

  renderRun();
}

export { renderRun as render, runLive, checkServer, collect };

/** The last `/history` record this tab received, or `null`. For checks, not for the UI. */
export function lastRecord() {
  return lastRecordValue;
}

/**
 * The `node_errors` from the last submit. Empty means ComfyUI accepted every
 * node; non-empty means it silently dropped some. For checks, not for the UI.
 */
export function lastNodeErrors() {
  return lastNodeErrorsValue;
}
