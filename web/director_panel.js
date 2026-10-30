/**
 * Director tab — DOM wiring for the pre-generation control surface.
 *
 * Every option list is built from `director.js` at runtime. Nothing is
 * hand-typed in the HTML, so there is exactly one place to fix when an enum
 * changes.
 *
 * This module composes a plan and renders it. It does not generate anything:
 * the Generate button is deliberately disabled and says so.
 */

import * as D from './director.js';

export const directorState = structuredClone(D.DEFAULT_DIRECTOR_STATE);

let registry = D.DEMO_REGISTRY.map((e) => ({ ...e }));

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Control construction — all from the enums
// ---------------------------------------------------------------------------

/** Fill a <select> with Auto first, then the enum's slugs. */
function fillSelect(select, slugs, { auto = true, label = D.labelFor } = {}) {
  if (!select) return;
  const frag = document.createDocumentFragment();
  if (auto) {
    const o = document.createElement('option');
    o.value = D.AUTO;
    o.textContent = 'Auto';
    frag.append(o);
  }
  for (const slug of slugs) {
    const o = document.createElement('option');
    o.value = slug;
    o.textContent = label(slug);
    frag.append(o);
  }
  select.replaceChildren(frag);
}

/** The move picker, grouped so 33 options stay navigable. */
function fillMoveSelect(select) {
  if (!select) return;
  const frag = document.createDocumentFragment();
  const placed = new Set();
  for (const group of D.MOVEMENT_GROUPS) {
    const og = document.createElement('optgroup');
    og.label = group.name;
    for (const slug of group.slugs) {
      const o = document.createElement('option');
      o.value = slug;
      o.textContent = D.labelFor(slug);
      og.append(o);
      placed.add(slug);
    }
    frag.append(og);
  }
  // Anything the grouping missed still has to be reachable.
  const missed = D.CAMERA_MOVEMENT.filter((m) => !placed.has(m));
  if (missed.length) {
    const og = document.createElement('optgroup');
    og.label = 'Other';
    for (const slug of missed) {
      const o = document.createElement('option');
      o.value = slug;
      o.textContent = D.labelFor(slug);
      og.append(o);
    }
    frag.append(og);
  }
  select.replaceChildren(frag);
}

function buildControls() {
  fillSelect($('d-genre'), D.GENRE);
  fillSelect($('d-era'), D.ERA);
  fillSelect($('d-pacing'), D.PACING);
  fillSelect($('d-model'), D.CAMERA_MODEL);
  fillSelect($('d-lens'), D.CAMERA_LENS);
  fillSelect($('d-aperture'), D.CAMERA_APERTURE);
  fillSelect($('d-light'), D.LIGHT);
  fillSelect($('d-palette'), D.COLOR_PALETTE);
  fillSelect($('d-resolution'), D.RESOLUTION_UI, { auto: false });
  fillSelect($('d-aspect'), D.ASPECT_RATIO, { auto: false });
  fillSelect($('d-emo-emotion'), D.EMOTION, { auto: false });
  fillMoveSelect($('d-move-add'));
  fillSelect($('d-emo-element'), registry.map((e) => e.name), { auto: false, label: (n) => n });
}

// ---------------------------------------------------------------------------
// Prompt tags
// ---------------------------------------------------------------------------

function renderTags() {
  const host = $('d-tags');
  if (!host) return;
  const tokens = D.parsePrompt(directorState.prompt, registry);
  if (!tokens.length) {
    host.innerHTML =
      '<span class="empty-note">No tags yet — type <code>@name</code> for an Element or ' +
      '<code>#move</code> for a camera move.</span>';
    return;
  }
  const frag = document.createDocumentFragment();
  for (const t of tokens) {
    const chip = document.createElement('span');
    chip.className = `tag-chip ${t.resolved ? 'ok' : 'bad'}`;
    const kind = t.kind === 'element' ? 'Element' : 'Move';
    let text = `<span class="tag-kind">${kind}</span> ${escapeHtml(t.raw)}`;
    if (t.resolved) {
      text += t.kind === 'element'
        ? ` <span class="tag-hint">→ ${escapeHtml(t.element.category ?? 'unspecified')}</span>`
        : ' <span class="tag-hint">→ in stack order</span>';
    } else if (t.suggestion) {
      text += ` <span class="tag-hint">did you mean #${escapeHtml(t.suggestion)}?</span>`;
    }
    chip.innerHTML = text;
    chip.title = t.resolved ? 'resolved' : t.reason;
    frag.append(chip);
  }
  host.replaceChildren(frag);
}

function renderRegistry() {
  const host = $('d-registry');
  if (!host) return;
  const frag = document.createDocumentFragment();
  for (const e of registry) {
    const s = document.createElement('span');
    s.className = 'registry-item';
    s.innerHTML = `@${escapeHtml(e.name)} <span class="cat">${escapeHtml(e.category)}</span>`;
    frag.append(s);
  }
  host.replaceChildren(frag);
}

// ---------------------------------------------------------------------------
// Move stack
// ---------------------------------------------------------------------------

function renderMoveStack() {
  const host = $('d-move-stack');
  if (!host) return;
  if (!directorState.moves.length) {
    host.innerHTML =
      '<li class="move-empty">No moves stacked. Add one above — the order here is the order ' +
      'they run.</li>';
    return;
  }
  const frag = document.createDocumentFragment();
  directorState.moves.forEach((slug, i) => {
    const li = document.createElement('li');
    li.className = 'move-row';
    li.dataset.index = String(i);

    const ord = document.createElement('span');
    ord.className = 'ord';
    ord.textContent = String(i + 1);

    const name = document.createElement('span');
    name.className = 'mv-name';
    name.textContent = D.labelFor(slug);

    const tag = document.createElement('span');
    tag.className = 'mv-tag';
    tag.textContent = `#${slug}`;

    const up = mkBtn('↑', 'move earlier', i === 0, () => move(i, i - 1));
    const down = mkBtn('↓', 'move later', i === directorState.moves.length - 1, () => move(i, i + 1));
    const rm = mkBtn('✕', 'remove', false, () => {
      directorState.moves.splice(i, 1);
      renderDirector();
    });

    li.append(ord, name, tag, up, down, rm);
    frag.append(li);
  });
  host.replaceChildren(frag);
}

function mkBtn(label, title, disabled, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.textContent = label;
  b.title = title;
  b.disabled = disabled;
  b.addEventListener('click', onClick);
  return b;
}

function move(from, to) {
  if (to < 0 || to >= directorState.moves.length) return;
  const [item] = directorState.moves.splice(from, 1);
  directorState.moves.splice(to, 0, item);
  renderDirector();
}

// ---------------------------------------------------------------------------
// Emotion list
// ---------------------------------------------------------------------------

function renderEmotions() {
  const host = $('d-emo-list');
  if (!host) return;
  if (!directorState.emotions.length) {
    host.innerHTML = '<li class="move-empty">No performance direction set.</li>';
    return;
  }
  const frag = document.createDocumentFragment();
  directorState.emotions.forEach((e, i) => {
    const li = document.createElement('li');
    li.className = 'move-row';
    li.innerHTML =
      `<span class="ord">${i + 1}</span>` +
      `<span class="mv-name">@${escapeHtml(e.element)} — ${escapeHtml(D.labelFor(e.emotion))}` +
      ` <span class="mv-tag">(${escapeHtml(D.intensityLabel(e.intensity))}, ` +
      `${e.intensity.toFixed(2)})</span></span>`;
    li.append(
      mkBtn('✕', 'remove', false, () => {
        directorState.emotions.splice(i, 1);
        renderDirector();
      }),
    );
    frag.append(li);
  });
  host.replaceChildren(frag);
}

// ---------------------------------------------------------------------------
// Plan
// ---------------------------------------------------------------------------

function renderPlan(plan) {
  const promptOut = $('d-prompt-out');
  if (promptOut) {
    promptOut.textContent = plan.prompt.prompt || '(empty)';
  }

  const attach = $('d-attachments');
  if (attach) {
    if (!plan.prompt.attachments.length) {
      attach.innerHTML = '<span class="empty-note">No Elements referenced.</span>';
    } else {
      const frag = document.createDocumentFragment();
      for (const a of plan.prompt.attachments) {
        const s = document.createElement('span');
        s.className = 'attach-item';
        s.textContent = `${a.token} ← @${a.name} (${a.category})`;
        frag.append(s);
      }
      attach.replaceChildren(frag);
    }
  }

  const params = $('d-params');
  if (params) params.textContent = JSON.stringify(plan.parameters, null, 2);

  const ext = $('d-extensions');
  if (ext) ext.textContent = JSON.stringify(plan.extensions, null, 2);

  const omitted = $('d-omitted');
  if (omitted) {
    if (!plan.omitted.length) {
      omitted.innerHTML = '<span class="empty-note">Nothing omitted — every field is set.</span>';
    } else {
      const frag = document.createDocumentFragment();
      for (const f of plan.omitted) {
        const s = document.createElement('span');
        s.className = 'omitted-item';
        s.textContent = f;
        frag.append(s);
      }
      omitted.replaceChildren(frag);
    }
  }

  const warns = $('d-warnings');
  if (warns) {
    const frag = document.createDocumentFragment();
    for (const w of plan.warnings) {
      const d = document.createElement('div');
      d.className = `warn-item${/reject|empty|must be/.test(w) ? ' err' : ''}`;
      d.textContent = w;
      frag.append(d);
    }
    warns.replaceChildren(frag);
  }
}

function renderCost(plan) {
  const cost = plan.cost;
  const btn = $('d-cost');
  if (btn) {
    if (cost.discounted) {
      btn.innerHTML = `<span class="was">✦ ${cost.list}</span>✦ ${cost.current}`;
    } else {
      btn.textContent = `✦ ${cost.current}`;
    }
  }
  const note = $('d-cost-note');
  if (note) {
    const lines = [
      `${cost.rate} credits/s at ${directorState.resolution} × ${directorState.duration}s = ` +
        `${cost.current} credits (≈$${cost.dollars.toFixed(2)} at the monthly Plus rate).`,
      ...cost.notes,
    ];
    note.textContent = lines.join(' ');
  }
}

// ---------------------------------------------------------------------------
// Master render
// ---------------------------------------------------------------------------

export function renderDirector() {
  const plan = D.directorPlan(directorState, registry);

  renderTags();
  renderRegistry();
  renderMoveStack();
  renderEmotions();
  renderPlan(plan);
  renderCost(plan);

  // Reflect state into the controls without stomping the focused one.
  const map = {
    'd-genre': 'genre',
    'd-era': 'era',
    'd-pacing': 'pacing',
    'd-model': 'camera_model',
    'd-lens': 'camera_lens',
    'd-aperture': 'camera_aperture',
    'd-light': 'light',
    'd-palette': 'color_palette',
    'd-resolution': 'resolution',
    'd-aspect': 'aspect_ratio',
  };
  for (const [id, key] of Object.entries(map)) {
    const sel = $(id);
    if (!sel) continue;
    if (document.activeElement !== sel) sel.value = directorState[key];
    sel.classList.toggle('auto', directorState[key] === D.AUTO);
    sel.classList.toggle(
      'flagged',
      key === 'resolution' && D.RESOLUTION_API.indexOf(directorState[key]) === -1,
    );
  }

  const dur = $('d-duration');
  if (dur && document.activeElement !== dur) dur.value = String(directorState.duration);
  const durOut = $('d-duration-out');
  if (durOut) durOut.textContent = `${directorState.duration} s`;

  const focal = $('d-focal');
  if (focal && document.activeElement !== focal) focal.value = String(directorState.focal_mm);
  const focalOut = $('d-focal-out');
  if (focalOut) focalOut.textContent = `${directorState.focal_mm} mm`;

  const audio = $('d-audio');
  if (audio) audio.checked = directorState.generate_audio;

  const emoInt = $('d-emo-intensity');
  if (emoInt) {
    const out = $('d-emo-intensity-out');
    if (out) out.textContent = `${D.intensityLabel(Number(emoInt.value))} (${Number(emoInt.value).toFixed(2)})`;
  }

  return plan;
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

export function initDirectorPanel() {
  buildControls();

  const bindings = {
    'd-genre': 'genre',
    'd-era': 'era',
    'd-pacing': 'pacing',
    'd-model': 'camera_model',
    'd-lens': 'camera_lens',
    'd-aperture': 'camera_aperture',
    'd-light': 'light',
    'd-palette': 'color_palette',
    'd-resolution': 'resolution',
    'd-aspect': 'aspect_ratio',
  };
  for (const [id, key] of Object.entries(bindings)) {
    const sel = $(id);
    if (!sel) continue;
    sel.addEventListener('change', () => {
      directorState[key] = sel.value;
      renderDirector();
    });
  }

  const prompt = $('d-prompt');
  if (prompt) {
    prompt.addEventListener('input', () => {
      directorState.prompt = prompt.value;
      renderDirector();
    });
  }

  const addMove = $('d-move-add-btn');
  if (addMove) {
    addMove.addEventListener('click', () => {
      const sel = $('d-move-add');
      if (!sel || !sel.value) return;
      directorState.moves.push(sel.value);
      renderDirector();
    });
  }

  const addEmo = $('d-emo-add');
  if (addEmo) {
    addEmo.addEventListener('click', () => {
      const el = $('d-emo-element');
      const em = $('d-emo-emotion');
      const it = $('d-emo-intensity');
      if (!el || !em || !it) return;
      directorState.emotions.push({
        element: el.value,
        emotion: em.value,
        intensity: Number(it.value),
      });
      renderDirector();
    });
  }

  const dur = $('d-duration');
  if (dur) {
    dur.addEventListener('input', () => {
      directorState.duration = Number(dur.value);
      renderDirector();
    });
  }

  const focal = $('d-focal');
  if (focal) {
    focal.addEventListener('input', () => {
      directorState.focal_mm = Number(focal.value);
      renderDirector();
    });
  }

  const emoInt = $('d-emo-intensity');
  if (emoInt) {
    emoInt.addEventListener('input', () => {
      const out = $('d-emo-intensity-out');
      if (out) {
        out.textContent = `${D.intensityLabel(Number(emoInt.value))} (${Number(emoInt.value).toFixed(2)})`;
      }
    });
  }

  const audio = $('d-audio');
  if (audio) {
    audio.addEventListener('change', () => {
      directorState.generate_audio = audio.checked;
      renderDirector();
    });
  }

  const reset = $('d-reset');
  if (reset) {
    reset.addEventListener('click', () => {
      Object.assign(directorState, structuredClone(D.DEFAULT_DIRECTOR_STATE));
      registry = D.DEMO_REGISTRY.map((e) => ({ ...e }));
      const p = $('d-prompt');
      if (p) p.value = '';
      buildControls();
      renderDirector();
    });
  }

  const prov = $('d-provenance');
  if (prov) {
    prov.innerHTML =
      `<strong>Option lists:</strong> ${escapeHtml(D.SCHEMA_SOURCE.label)}, captured ` +
      `${escapeHtml(D.SCHEMA_SOURCE.captured)}. ${escapeHtml(D.SCHEMA_SOURCE.note)}<br /><br />` +
      `<strong>Cost:</strong> ${escapeHtml(D.CREDIT_SOURCE.label)}. ${escapeHtml(D.CREDIT_SOURCE.note)}`;
  }

  renderDirector();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Test seam: swap the Element registry (used by the browser check). */
export function setRegistry(next) {
  registry = next.map((e) => ({ ...e }));
  buildControls();
  renderDirector();
}

export function getRegistry() {
  return registry.map((e) => ({ ...e }));
}
