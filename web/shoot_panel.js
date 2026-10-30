/**
 * The Shoot tab — Stage 4 PROMPT.
 *
 *   Stage 4 PROMPT   action + panel fragment + @Elements + #moves
 *
 * One parser, not two
 * -------------------
 * This tab does **not** re-implement tag parsing. It imports `parsePrompt` and
 * `composePrompt` from `web/director.js` — the same functions the Director tab
 * uses — and reads the registry through `director_panel.getRegistry()`, the same
 * seam the Director tab and the browser check use. It also reads the Director
 * tab's live `directorState` for the move stack and the panel fragment, so what
 * you set on the Director tab is what gets composed here. Two parsers would be
 * two chances to disagree about what `@tamsincamp` means.
 *
 * What is real here
 * -----------------
 *   * Resolution is real: an `@Name` that is in the registry becomes an API
 *     reference token; one that is not stays literal and is counted.
 *   * The move stack and the panel fragment are the Director tab's, live.
 *
 * What is NOT real, and is said on screen
 * ---------------------------------------
 *   * Nothing is sent. `CinemaPromptCompose` runs inside ComfyUI; this page has
 *     no server and no ComfyUI connection.
 *   * The panel's composer substitutes `<<<image_N>>>` **inline**, where the
 *     Python node appends the `@name` tags at the end. Both are shown, labelled,
 *     because a panel that showed only its own arrangement would misrepresent
 *     the node's output.
 */

import * as D from './director.js';
import * as DP from './director_panel.js';
import * as EP from './elements_panel.js';
import * as S from './studio.js';

const $ = (id) => document.getElementById(id);

const DEFAULT_ACTION = 'A detective crosses the diner at 2am, @tamsincamp in the doorway';

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** The full record behind a resolved attachment, so `asset_path` can be shown. */
function recordForAttachment(name) {
  const wanted = String(name).toLowerCase();
  return EP.elementRecords().find((r) => r.name.toLowerCase() === wanted) ?? null;
}

/**
 * The `attachments_json` the Python node emits.
 *
 * `prompt.compose_prompt` builds each entry as
 * `{"token": "<<<image_n>>>", "name": ..., "asset_path": ...}` — note
 * `asset_path`, not the `category` the panel's own composer carries. The tab
 * shows the node's shape, because that is what it claims to be showing.
 */
function attachmentsJson(composed) {
  return composed.attachments.map((a) => {
    const record = recordForAttachment(a.name);
    return {
      token: a.token,
      name: a.name,
      asset_path: record ? record.asset_path : '',
    };
  });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderTagChips(tokens) {
  const box = $('s-tags');
  if (!box) return;
  if (!tokens.length) {
    box.innerHTML = '<span class="empty-note">No @Element or #move tags in the action.</span>';
    return;
  }
  box.innerHTML = tokens
    .map((t) => {
      const cls = t.resolved ? 'ok' : 'bad';
      const hint = t.resolved
        ? ''
        : `<span class="tag-hint"> — ${escapeHtml(t.reason ?? 'unresolved')}`
          + (t.suggestion ? ` · did you mean <code>${escapeHtml(t.sigil)}${escapeHtml(t.suggestion)}</code>?` : '')
          + '</span>';
      return `<span class="tag-chip ${cls}"><span class="tag-kind">${escapeHtml(t.sigil)}</span>`
        + `${escapeHtml(t.name)}${hint}</span>`;
    })
    .join('');
}

function renderRegistry() {
  const box = $('s-registry');
  if (!box) return;
  const entries = DP.getRegistry();
  if (!entries.length) {
    box.innerHTML = '<span class="empty-note">No Elements registered — every @tag will be unresolved.</span>';
    return;
  }
  box.innerHTML = entries
    .map((e) => `<span class="registry-item"><span class="tag-kind">@</span>${escapeHtml(e.name)}</span>`)
    .join('');
}

function renderDirectorInputs() {
  const state = DP.directorState;

  const moves = $('s-moves');
  if (moves) {
    moves.innerHTML = state.moves.length
      ? state.moves.map((m) => `<span class="registry-item">#${escapeHtml(m)}</span>`).join('')
      : '<span class="empty-note">No moves stacked on the Director tab.</span>';
  }

  const fragment = $('s-panel-fragment');
  if (fragment) {
    const groups = D.groupFragments(state);
    const keys = Object.keys(groups);
    fragment.textContent = keys.length
      ? keys.map((k) => `${k}: ${groups[k]}`).join('\n')
      : '(empty — every Director field is on auto, so the node sends no panel fragment)';
  }
}

function renderUnresolved(tokens) {
  const box = $('s-unresolved');
  const count = $('s-unresolved-count');
  const card = $('s-unresolved-card');
  const bad = tokens.filter((t) => !t.resolved);

  if (count) {
    count.textContent = bad.length ? `${bad.length} unresolved` : 'none';
  }
  if (card) card.style.borderColor = bad.length ? 'var(--fail)' : '';
  if (!box) return;

  if (!bad.length) {
    box.innerHTML =
      '<div class="warn-item" style="border-left-color:var(--pass);background:var(--pass-bg);color:#bdf0d2">'
      + 'Every tag resolved. <code>CinemaPromptCompose</code>\'s <code>ok</code> output is <code>true</code>.</div>';
    return;
  }
  box.innerHTML = bad
    .map((t) => {
      const suggestion = t.suggestion
        ? ` Did you mean <code>${escapeHtml(t.sigil)}${escapeHtml(t.suggestion)}</code>?`
        : '';
      return `<div class="warn-item warn-item-bad"><code>${escapeHtml(t.raw)}</code> — `
        + `${escapeHtml(t.reason ?? 'unresolved')}.${suggestion}</div>`;
    })
    .join('');
}

function renderAttachments(composed) {
  const box = $('s-attachments');
  const count = $('s-attach-count');
  const rows = attachmentsJson(composed);
  if (count) count.textContent = `${rows.length} attachment(s)`;
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = '<span class="empty-note">No Element resolved, so the call carries no reference image.</span>';
    return;
  }
  box.innerHTML = rows
    .map((r) => `<span class="attach-item">${escapeHtml(r.token)} ${escapeHtml(r.name)}`
      + (r.asset_path ? ` <span class="dim">${escapeHtml(r.asset_path)}</span>` : '')
      + '</span>')
    .join('');
}

function renderShoot() {
  const action = $('s-action')?.value ?? '';
  const state = DP.directorState;
  const composed = D.composePrompt({
    text: action,
    moves: state.moves,
    registry: DP.getRegistry(),
  });

  renderTagChips(composed.tokens);
  renderRegistry();
  renderDirectorInputs();
  renderUnresolved(composed.tokens);
  renderAttachments(composed);

  const final = $('s-final');
  if (final) {
    final.textContent = composed.prompt
      || '(empty — the API requires a non-empty prompt, so this call would be rejected)';
  }

  const ok = $('s-ok');
  if (ok) {
    const good = composed.unresolved === 0 && action.trim().length > 0;
    ok.innerHTML = `<span class="badge ${good ? 'badge-pass' : 'badge-fail'}">`
      + `<span class="badge-label">ok</span>`
      + `<span class="badge-value">${composed.unresolved === 0 ? 'true' : 'false'}</span></span>`;
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

let wired = false;

export function initShootPanel() {
  if (wired) return;
  wired = true;

  const action = $('s-action');
  if (action && !action.value) action.value = DEFAULT_ACTION;
  action?.addEventListener('input', renderShoot);

  const provenance = $('s-provenance');
  if (provenance) {
    provenance.innerHTML =
      'Tag parsing and resolution: <code>web/director.js</code> '
      + '(<code>parsePrompt</code>, <code>composePrompt</code>) — the Director tab\'s own '
      + 'functions, imported rather than copied. Registry: <code>director_panel.getRegistry()</code>. '
      + 'Move stack and panel fragment: the live Director state. '
      + 'Attachment shape: <code>cinematographer/prompt.py</code> '
      + '(<code>ComposedPrompt.attachments</code> → <code>token</code>, <code>name</code>, '
      + '<code>asset_path</code>). '
      + 'Nothing is sent anywhere: this page has no server and no ComfyUI connection.';
  }

  renderShoot();
}

export { renderShoot };
