/**
 * The Elements tab — Stage 1 BUILD and Stage 2 ATTACH.
 *
 *   Stage 1 BUILD   the cast and the sets, as images
 *   Stage 2 ATTACH  a finished image becomes a named Element, tagged `@Name`
 *
 * Why this tab exists
 * -------------------
 * The five stages are a pipeline only because an Element is named once and
 * reused. Without a registry, every stage re-describes the same character in
 * prose and nothing can be measured against anything. This tab is where the
 * naming happens, and it is the reason the Shoot tab's `@Name` resolves at all.
 *
 * What is real here
 * -----------------
 *   * The category list, the validation rules, the sidecar path, the sidecar
 *     record and the registry document are all computed by `studio.js`, which
 *     `web/parity_check.py` compares against `cinematographer/elements.py`.
 *   * Adding an Element really does change what the Director and Shoot tabs
 *     resolve: this tab writes through `director_panel.setRegistry`, the same
 *     seam the browser check uses. One registry, not two.
 *
 * What is NOT real, and is said on screen
 * ---------------------------------------
 *   * The panel is a static page with no server. It does **not** write
 *     `cinematographer/elements.json` or any sidecar. `CinemaElementSave` does
 *     that inside ComfyUI. The tab shows the bytes the node would write.
 *   * The registry starts as three demo entries. The repo ships exactly one real
 *     sidecar, `assets/tamsin.element.json`; the provenance card says so, and
 *     says where the demo registry disagrees with it.
 */

import * as S from './studio.js';
import * as D from './director.js';
import * as DP from './director_panel.js';

const $ = (id) => document.getElementById(id);

/** Full records for the registry entries, keyed by `category:name.casefold()`. */
const records = new Map();

const keyOf = (name, category) => `${String(category)}:${String(name).toLowerCase()}`;

/**
 * The demo registry, with full records.
 *
 * `tamsincamp` carries the real shipped sidecar's metadata (`assets/tamsin.png`,
 * description "lead", seed 7, no palette, no bbox) because that sidecar is the
 * sidecar for that asset. The *name* differs: the file on disk says `Tamsin`,
 * the Director tab's placeholder says `@tamsincamp`. Lookup is exact after
 * casefolding, so those are two different names — the provenance card says so
 * rather than quietly renaming either one.
 */
const SEED = [
  {
    name: 'tamsincamp',
    category: 'character',
    asset_path: 'assets/tamsin.png',
    description: 'lead',
    seed: 7,
    palette: [],
    bbox: null,
    created_utc: '',
  },
  {
    name: 'the-diner',
    category: 'location',
    asset_path: 'assets/the-diner.png',
    description: '',
    seed: 0,
    palette: [],
    bbox: null,
    created_utc: '',
  },
  {
    name: 'chrome-revolver',
    category: 'prop',
    asset_path: 'assets/chrome-revolver.png',
    description: '',
    seed: 0,
    palette: [],
    bbox: null,
    created_utc: '',
  },
];

function seedRecords() {
  records.clear();
  for (const element of SEED) records.set(keyOf(element.name, element.category), { ...element });
}

/** The full record for a registry entry, synthesised if the tab never saw it. */
function recordFor(entry) {
  const known = records.get(keyOf(entry.name, entry.category));
  if (known) return known;
  return {
    name: entry.name,
    category: entry.category,
    asset_path: '',
    description: '',
    seed: 0,
    palette: [],
    bbox: null,
    created_utc: '',
  };
}

// ---------------------------------------------------------------------------
// The draft
// ---------------------------------------------------------------------------

function readDraft() {
  return {
    name: $('e-name')?.value ?? '',
    category: $('e-category')?.value ?? '',
    asset_path: $('e-image-path')?.value ?? '',
    description: $('e-description')?.value ?? '',
    seed: Number($('e-seed')?.value ?? 0),
    palette: $('e-palette')?.value ?? '',
    has_bbox: Boolean($('e-has-bbox')?.checked),
    bbox_min_x: Number($('e-bbox-min-x')?.value ?? 0),
    bbox_min_y: Number($('e-bbox-min-y')?.value ?? 0),
    bbox_max_x: Number($('e-bbox-max-x')?.value ?? 0),
    bbox_max_y: Number($('e-bbox-max-y')?.value ?? 0),
  };
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderErrors(errors) {
  const box = $('e-errors');
  if (!box) return;
  if (!errors.length) {
    box.innerHTML = '<div class="warn-item" style="border-left-color:var(--pass);background:var(--pass-bg);color:#bdf0d2">'
      + 'Valid — <code>elements.Element</code> would accept this record.</div>';
    return;
  }
  box.innerHTML = errors
    .map((e) => `<div class="warn-item">${escapeHtml(e)}</div>`)
    .join('');
}

function renderMeasurable(element) {
  const box = $('e-measurable');
  if (!box) return;
  const hasPalette = element.palette.length > 0;
  const hasBbox = element.bbox !== null && element.bbox !== undefined;
  const ready = hasPalette && hasBbox;
  const missing = [];
  if (!hasPalette) missing.push('no palette');
  if (!hasBbox) missing.push('no bbox');

  box.innerHTML =
    `<span class="badge ${ready ? 'badge-pass' : 'badge-fail'}">`
    + `<span class="badge-label">appearance drift</span>`
    + `<span class="badge-value">${ready ? 'MEASURABLE' : 'NOT MEASURABLE'}</span></span>`
    + `<span class="zone-reason">${ready
      ? 'palette and bbox are both present, so <code>character_record_from_element</code> returns a record.'
      : `<code>character_record_from_element</code> <strong>raises</strong> — ${escapeHtml(missing.join(', '))}. `
        + 'The Element still feeds the prompt; identity continuity simply cannot be measured against it.'
    }</span>`;
}

function renderTag(element) {
  const box = $('e-tag');
  if (!box) return;
  const tag = S.elementTag(element);
  const token = S.referenceToken(1);
  box.innerHTML =
    `<span class="tag-chip ok"><span class="tag-kind">@</span>${escapeHtml(element.name)}</span>`
    + `<span class="tag-chip"><span class="tag-kind">→</span>${escapeHtml(token)}</span>`;
}

function renderRegistry() {
  const list = $('e-registry');
  const count = $('e-count');
  const entries = DP.getRegistry();
  if (count) {
    const cats = S.ELEMENT_CATEGORIES
      .map((c) => `${entries.filter((e) => e.category === c).length} ${c}`)
      .join(' · ');
    count.textContent = `${entries.length} Element(s) — ${cats}`;
  }
  if (!list) return;
  if (!entries.length) {
    list.innerHTML = '<div class="empty-note">No Elements registered. Every @tag will be unresolved.</div>';
    return;
  }
  const ordered = [...entries].sort((a, b) => {
    if (a.category !== b.category) return a.category < b.category ? -1 : 1;
    const an = a.name.toLowerCase();
    const bn = b.name.toLowerCase();
    return an === bn ? 0 : an < bn ? -1 : 1;
  });
  list.innerHTML = ordered
    .map((entry) => {
      const rec = recordFor(entry);
      const measurable = rec.palette.length > 0 && rec.bbox !== null;
      return (
        '<div class="registry-item registry-item-block">'
        + `<span><span class="tag-kind">@</span>${escapeHtml(entry.name)}</span>`
        + `<span class="cat">${escapeHtml(entry.category)}</span>`
        + `<span class="measurable ${measurable ? 'yes' : 'no'}">`
        + `${measurable ? 'measurable' : 'not measurable'}</span>`
        + '</div>'
      );
    })
    .join('');
}

function renderRegistryJson() {
  const pre = $('e-registry-json');
  if (!pre) return;
  const entries = DP.getRegistry().map(recordFor);
  pre.textContent = JSON.stringify(S.registryDoc(entries), null, 2);
}

function renderElements() {
  const draft = readDraft();
  const result = S.validateElement(draft);

  renderErrors(result.errors);

  const bboxGrid = $('e-bbox-grid');
  if (bboxGrid) bboxGrid.style.opacity = draft.has_bbox ? '1' : '0.45';

  if (result.ok) {
    const element = result.element;
    renderTag(element);
    renderMeasurable(element);
    const sidecar = $('e-sidecar');
    if (sidecar) sidecar.textContent = S.sidecarPath(element.asset_path);
    const summary = $('e-summary');
    if (summary) summary.textContent = S.saveSummary(element);
    const json = $('e-element-json');
    if (json) json.textContent = JSON.stringify(S.elementRecord(element), null, 2);
  } else {
    const tag = $('e-tag');
    if (tag) tag.innerHTML = '<span class="empty-note">Fix the record above to see its tag.</span>';
    renderMeasurable({ palette: [], bbox: null });
    for (const id of ['e-sidecar', 'e-summary']) {
      const el = $(id);
      if (el) el.textContent = '—';
    }
    const json = $('e-element-json');
    if (json) json.textContent = '{}';
  }

  renderRegistry();
  renderRegistryJson();
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function addElement() {
  const result = S.validateElement(readDraft());
  if (!result.ok) {
    renderElements();
    return;
  }
  const element = result.element;
  const k = keyOf(element.name, element.category);

  // `ElementRegistry.add` refuses a duplicate in the SAME category. The same name
  // in a different category is legal — and then `get(name)` is ambiguous, which
  // is a thing the caller has to resolve rather than the registry guessing.
  if (records.has(k)) {
    const box = $('e-errors');
    if (box) {
      box.innerHTML =
        `<div class="warn-item">A ${escapeHtml(element.category)} named `
        + `<code>${escapeHtml(element.name)}</code> is already registered. `
        + 'The same name in a <em>different</em> category is legal; the same name in the '
        + 'same category is not.</div>';
    }
    return;
  }

  records.set(k, element);
  DP.setRegistry([...DP.getRegistry(), { name: element.name, category: element.category }]);
  renderElements();
}

function resetElements() {
  seedRecords();
  DP.setRegistry(D.DEMO_REGISTRY.map((e) => ({ ...e })));
  renderElements();
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

let wired = false;

export function initElementsPanel() {
  if (wired) return;
  wired = true;

  const select = $('e-category');
  if (select) {
    select.innerHTML = S.ELEMENT_CATEGORIES
      .map((c) => `<option value="${c}">${c}</option>`)
      .join('');
    select.value = 'character';
  }

  const path = $('e-registry-path');
  if (path) path.textContent = S.DEFAULT_REGISTRY_PATH;

  const provenance = $('e-provenance');
  if (provenance) {
    provenance.innerHTML =
      'Category list, validation rules, sidecar path and registry document: '
      + `<code>web/studio.js</code> ↔ <code>${escapeHtml(S.STUDIO_SOURCE.label)}</code>, `
      + 'checked by <code>web/parity_check.py</code>. '
      + 'The repo ships one real sidecar, <code>assets/tamsin.element.json</code> — name '
      + '<code>Tamsin</code>, category <code>character</code>, no palette, no bbox. The demo '
      + 'registry spells that Element <code>tamsincamp</code> because that is the tag the '
      + 'Director tab\'s placeholder uses; lookup is exact after casefolding, so the two names '
      + 'are not interchangeable.';
  }

  for (const id of [
    'e-name', 'e-category', 'e-image-path', 'e-description', 'e-seed', 'e-palette',
    'e-has-bbox', 'e-bbox-min-x', 'e-bbox-min-y', 'e-bbox-max-x', 'e-bbox-max-y',
  ]) {
    const el = $(id);
    if (!el) continue;
    el.addEventListener('input', renderElements);
    el.addEventListener('change', renderElements);
  }

  $('e-add')?.addEventListener('click', addElement);
  $('e-reset')?.addEventListener('click', resetElements);

  seedRecords();
  renderElements();
}

/** Test seam: the full records behind the registry, for the browser check. */
export function elementRecords() {
  return DP.getRegistry().map(recordFor);
}

export { renderElements };
