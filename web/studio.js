/**
 * Cinema Studio 4.0 — the stages the Director and Judge tabs do not cover,
 * mirrored from the Python engine.
 *
 *   Stage 1 BUILD   the cast and the sets, as images            (elements.py)
 *   Stage 2 ATTACH  a finished image becomes a named Element    (elements.py)
 *   Stage 4 PROMPT  action + panel + @Elements + #moves         (prompt.py)
 *   Stage 5 POST    grade, extend, regional edit                (post.py)
 *
 * This module is the JS half of the same contract `cinematographer.js` keeps for
 * geometry: **every constant is the engine's constant, and every number the panel
 * shows is computed here rather than typed into the HTML.** `web/parity_check.py`
 * compares this file against the Python engine, so a drift is a test failure
 * rather than a wrong number on screen.
 *
 * What is mirrored, and what is not
 * ---------------------------------
 *
 * Mirrored exactly (and parity-checked):
 *   * `ELEMENT_CATEGORIES`        <- elements.ELEMENT_CATEGORIES
 *   * `GRADE_PARAMS`              <- post.GRADE_PARAMS
 *   * `GRADE_NEUTRAL`             <- post.GRADE_NEUTRAL
 *   * `GRADE_RANGES`              <- post.GRADE_RANGES
 *   * `EXTEND_MODES`              <- post.EXTEND_MODES
 *   * `EXTEND_DURATION_RANGE`     <- post.EXTEND_DURATION_RANGE
 *   * `EXTEND_OVERLAP_MAX_FRAMES` <- post.EXTEND_OVERLAP_MAX_FRAMES
 *   * `POST_RULES` / `POST_RULE_WEIGHTS` <- post.POST_RULES / POST_RULE_WEIGHTS
 *   * `applyGrade`                <- post.apply_grade
 *   * `gradeSummary`              <- post.GradePlan.summary
 *   * `postChecks`                <- post.PostPlan.checks
 *   * `correctionsFromReport`     <- nodes._corrections
 *   * `parsePalette`              <- nodes._parse_palette
 *   * `elementRecord`             <- elements.Element.to_dict
 *   * `registryDoc`               <- elements.ElementRegistry.to_dict
 *   * `sidecarPath`               <- elements.sidecar_path
 *
 * NOT mirrored, and deliberately left to `director.js`:
 *   * the `@Element` / `#move` tag parser and the prompt composer. The Shoot tab
 *     reuses the Director tab's machinery rather than growing a second copy of
 *     it — two parsers would be two chances to disagree.
 *
 * Nothing here touches the network, a file, or a pixel. `CinemaElementSave`
 * writes a sidecar and a registry; this module only *describes* what it would
 * write, so the panel can show it without claiming to have written it.
 */

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

/** Where each mirrored constant comes from, for the tabs' provenance footers. */
export const STUDIO_SOURCE = {
  label: 'cinematographer/ (Python) — elements.py, prompt.py, post.py, nodes.py',
  note:
    'Every constant below is read from the engine and re-checked by ' +
    'web/parity_check.py. Nothing here is hand-written from the docs.',
};

// ---------------------------------------------------------------------------
// Stage 1.3 ATTACH — the Element registry (engine: elements.py)
// ---------------------------------------------------------------------------

/** The confirmed Element taxonomy: Characters / Locations / Props. */
export const ELEMENT_CATEGORIES = ['character', 'location', 'prop'];

/** The sigil that introduces an Element tag in a prompt. */
export const ELEMENT_TAG_PREFIX = '@';

/** The sigil that introduces a camera-move tag in a prompt. */
export const MOVE_TAG_PREFIX = '#';

/** The API's own reference token, which an `@Name` is translated to. */
export const API_REFERENCE_TOKEN = '<<<image_{n}>>>';

/** The sidecar suffix: `out/tamsin.png` -> `out/tamsin.element.json`. */
export const ELEMENT_SIDECAR_SUFFIX = '.element.json';

/** The registry path the nodes default to when the caller does not say. */
export const DEFAULT_REGISTRY_PATH = 'cinematographer/elements.json';

/**
 * The API reference token for the n-th attachment (1-based).
 * Mirrors `prompt.API_REFERENCE_TOKEN.format(n=...)`.
 */
export function referenceToken(n) {
  return API_REFERENCE_TOKEN.replace('{n}', String(n));
}

/**
 * `out/tamsin.png` -> `out/tamsin.element.json`.
 *
 * Mirrors `elements.sidecar_path`, which is `Path(asset).with_suffix(...)`:
 * the **last** suffix is replaced, and a leading dot does not count as a suffix.
 */
export function sidecarPath(assetPath) {
  const text = String(assetPath ?? '');
  const cut = Math.max(text.lastIndexOf('/'), text.lastIndexOf('\\'));
  const dir = cut === -1 ? '' : text.slice(0, cut + 1);
  const base = cut === -1 ? text : text.slice(cut + 1);
  const dot = base.lastIndexOf('.');
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return `${dir}${stem}${ELEMENT_SIDECAR_SUFFIX}`;
}

/**
 * Parse `"0.82,0.61,0.55;0.11,0.09,0.08"` into normalised RGB triples.
 *
 * Mirrors `nodes._parse_palette`. Empty means **not measured** and yields `[]`;
 * it is never replaced with a default, because an invented palette would make an
 * appearance-drift measurement look like a pass. A malformed entry is a hard
 * error rather than a silent skip, so a typo cannot quietly become "not
 * measured" either.
 *
 * @returns {{ok: true, palette: number[][]} | {ok: false, error: string}}
 */
export function parsePalette(text) {
  const raw = String(text ?? '').trim();
  if (!raw) return { ok: true, palette: [] };
  const palette = [];
  for (const chunk of raw.split(';')) {
    const piece = chunk.trim();
    if (!piece) continue;
    const parts = piece.split(',').map((p) => p.trim());
    if (parts.length !== 3) {
      return {
        ok: false,
        error:
          `palette entry "${piece}" must be three comma-separated 0..1 RGB ` +
          `channels, e.g. '0.82,0.61,0.55'. Separate colours with ';'.`,
      };
    }
    const channels = [];
    for (const part of parts) {
      const value = Number(part);
      if (part === '' || !Number.isFinite(value)) {
        return {
          ok: false,
          error: `palette entry "${piece}" has a channel that is not a number.`,
        };
      }
      channels.push(value);
    }
    palette.push(channels);
  }
  return { ok: true, palette };
}

/**
 * Validate an Element draft the way `elements.Element.__post_init__` does.
 *
 * Returns every problem rather than the first, so the form can show them all.
 * The rules, in the engine's order:
 *   * the category is one of `ELEMENT_CATEGORIES`
 *   * the name is non-empty after stripping
 *   * every palette colour has 3 channels, each inside 0..1
 *   * a bbox has 4 NDC values, each inside -1..1, and is not inverted
 *
 * @returns {{ok: boolean, errors: string[], element: object|null}}
 */
export function validateElement(draft) {
  const errors = [];
  const name = String(draft?.name ?? '').trim();
  const category = String(draft?.category ?? '');
  const assetPath = String(draft?.asset_path ?? '');

  if (!ELEMENT_CATEGORIES.includes(category)) {
    errors.push(
      `unknown Element category "${category}"; legal categories are ` +
        ELEMENT_CATEGORIES.join(', '),
    );
  }
  if (!name) errors.push('Element name must be a non-empty string');
  if (!assetPath.trim()) {
    errors.push(
      'image_path must be the path to the asset on disk. The node stores the ' +
        'path; it does not read the file.',
    );
  }

  const parsed = parsePalette(draft?.palette);
  if (!parsed.ok) errors.push(parsed.error);
  const palette = parsed.ok ? parsed.palette : [];
  for (const colour of palette) {
    for (const channel of colour) {
      if (!(channel >= 0 && channel <= 1)) {
        errors.push(
          `Element "${name}": palette channel ${channel} is outside 0..1 ` +
            '(colours are normalised RGB)',
        );
      }
    }
  }

  let bbox = null;
  if (draft?.has_bbox) {
    const bounds = ['bbox_min_x', 'bbox_min_y', 'bbox_max_x', 'bbox_max_y'].map((k) =>
      Number(draft?.[k]),
    );
    if (bounds.some((v) => !Number.isFinite(v))) {
      errors.push(`Element "${name}": bbox must be 4 NDC numbers`);
    } else {
      for (const value of bounds) {
        if (!(value >= -1 && value <= 1)) {
          errors.push(
            `Element "${name}": bbox value ${value} is outside the NDC frame -1..1`,
          );
        }
      }
      if (bounds[0] > bounds[2] || bounds[1] > bounds[3]) {
        errors.push(
          `Element "${name}": bbox (${bounds.join(', ')}) is inverted ` +
            '(min must not exceed max on either axis)',
        );
      }
      bbox = bounds;
    }
  }

  if (errors.length) return { ok: false, errors, element: null };

  return {
    ok: true,
    errors: [],
    element: {
      name,
      category,
      asset_path: assetPath,
      description: String(draft?.description ?? ''),
      seed: Math.trunc(Number(draft?.seed ?? 0)) || 0,
      palette,
      bbox,
      created_utc: String(draft?.created_utc ?? ''),
    },
  };
}

/**
 * The `element_json` record `CinemaElementSave` writes to the sidecar.
 * Mirrors `elements.Element.to_dict()`.
 */
export function elementRecord(element) {
  return {
    name: element.name,
    category: element.category,
    asset_path: element.asset_path,
    description: element.description,
    seed: element.seed,
    palette: element.palette.map((c) => [...c]),
    bbox: element.bbox === null || element.bbox === undefined ? null : [...element.bbox],
    created_utc: element.created_utc,
  };
}

/**
 * The registry document `ElementRegistry.save` writes.
 * Mirrors `ElementRegistry.to_dict()`: ordered by `(category, name.casefold())`.
 */
export function registryDoc(elements) {
  const ordered = [...elements].sort((a, b) => {
    if (a.category !== b.category) return a.category < b.category ? -1 : 1;
    const an = a.name.toLowerCase();
    const bn = b.name.toLowerCase();
    if (an === bn) return 0;
    return an < bn ? -1 : 1;
  });
  return {
    categories: [...ELEMENT_CATEGORIES],
    elements: ordered.map(elementRecord),
  };
}

/** The `@Name` tag Stage 4 will resolve, for one Element. */
export function elementTag(element) {
  return `${ELEMENT_TAG_PREFIX}${element.name}`;
}

/**
 * The `summary` string `CinemaElementSave` returns.
 * Mirrors `f"saved {category} '{name}' -> {sidecar}"`.
 */
export function saveSummary(element) {
  return `saved ${element.category} '${element.name}' -> ${sidecarPath(element.asset_path)}`;
}

// ---------------------------------------------------------------------------
// Stage 5 POST — grade (engine: post.py)
// ---------------------------------------------------------------------------

/** The seven documented grade controls, in engine order. */
export const GRADE_PARAMS = [
  'temperature',
  'contrast',
  'saturation',
  'sharpness',
  'film_grain',
  'highlights',
  'exposure',
];

/**
 * Neutral value per control. A neutral grade is a no-op, so `GradeSettings()`
 * describes "change nothing".
 */
export const GRADE_NEUTRAL = {
  temperature: 0.0,
  contrast: 0.0,
  saturation: 0.0,
  sharpness: 0.0,
  film_grain: 0.0,
  highlights: 0.0,
  exposure: 0.0,
};

/** The legal `(min, max)` for each control. */
export const GRADE_RANGES = {
  temperature: [-1.0, 1.0],
  contrast: [-1.0, 1.0],
  saturation: [-1.0, 1.0],
  sharpness: [0.0, 1.0],
  film_grain: [0.0, 1.0],
  highlights: [-1.0, 1.0],
  exposure: [-2.0, 2.0],
};

/** `"up"`, `"down"` or `"none"`. Mirrors `post._direction`. */
export function gradeDirection(fromValue, toValue) {
  if (toValue > fromValue) return 'up';
  if (toValue < fromValue) return 'down';
  return 'none';
}

/**
 * Describe grade settings as an ordered list of deltas. Does not touch pixels.
 * Mirrors `post.apply_grade` / `GradePlan.to_dict()`.
 *
 * A control left at neutral contributes no delta, so the graph leaves it at the
 * model's own default.
 */
export function applyGrade(settings) {
  const deltas = [];
  for (const param of GRADE_PARAMS) {
    const from = GRADE_NEUTRAL[param];
    const to = Number(settings?.[param] ?? from);
    const direction = gradeDirection(from, to);
    if (direction === 'none') continue;
    deltas.push({ param, from, to, direction });
  }
  return { deltas, count: deltas.length, is_noop: deltas.length === 0 };
}

/** A one-line, ASCII-only description of a grade plan. Mirrors `GradePlan.summary`. */
export function gradeSummary(plan) {
  if (!plan.deltas.length) return 'grade: neutral (no deltas)';
  const parts = plan.deltas.map(
    (d) => `${d.param} ${d.direction} ${d.from.toFixed(3)}->${d.to.toFixed(3)}`,
  );
  return `grade: ${plan.deltas.length} delta(s) - ${parts.join(', ')}`;
}

/** True when every control sits at its neutral value. Mirrors `GradeSettings.is_neutral`. */
export function gradeIsNeutral(settings) {
  return GRADE_PARAMS.every((p) => Number(settings?.[p] ?? GRADE_NEUTRAL[p]) === GRADE_NEUTRAL[p]);
}

// ---------------------------------------------------------------------------
// Stage 5 POST — extend and edit (engine: post.py)
// ---------------------------------------------------------------------------

/** Sequel or Prequel. */
export const EXTEND_MODES = ['sequel', 'prequel'];

/** The legal length of the new segment, in seconds. */
export const EXTEND_DURATION_RANGE = [4.0, 30.0];

/** The most frames of the existing clip an extension may re-cover. */
export const EXTEND_OVERLAP_MAX_FRAMES = 48;

/** The frame rate `overlap_s` is computed at. */
export const DEFAULT_FPS = 24.0;

/** The default extension length. */
export const DEFAULT_EXTEND_DURATION_S = 5.0;

/**
 * A Sequel/Prequel extension request. Mirrors `post.ExtendPlan`.
 *
 * In the real product this is a separate Seedance call, not a Cinema Studio
 * endpoint. This record describes the request; it does not make it.
 *
 * @returns {{ok: true, plan: object} | {ok: false, error: string}}
 */
export function extendPlan({ mode, duration_s, overlap_frames }) {
  const m = String(mode ?? 'sequel');
  if (!EXTEND_MODES.includes(m)) {
    return { ok: false, error: `unknown Extend mode "${m}"; legal modes are ${EXTEND_MODES.join(', ')}` };
  }
  const duration = Number(duration_s);
  const [low, high] = EXTEND_DURATION_RANGE;
  if (!(duration >= low && duration <= high)) {
    return {
      ok: false,
      error: `Extend duration_s=${duration} is outside its legal range ${low}..${high} seconds`,
    };
  }
  const overlap = Math.trunc(Number(overlap_frames) || 0);
  if (!(overlap >= 0 && overlap <= EXTEND_OVERLAP_MAX_FRAMES)) {
    return {
      ok: false,
      error:
        `Extend overlap_frames=${overlap} is outside its legal range ` +
        `0..${EXTEND_OVERLAP_MAX_FRAMES} frames`,
    };
  }
  return {
    ok: true,
    plan: {
      mode: m,
      duration_s: duration,
      overlap_frames: overlap,
      overlap_s: overlap / DEFAULT_FPS,
    },
  };
}

/**
 * One regional edit: a label, an NDC box, and what to change inside it.
 * Mirrors `post.EditRegion`.
 *
 * A box that spills past the frame is allowed and reported as a non-gating flag;
 * a box with min greater than max is rejected, because that is a bug rather than
 * a choice.
 *
 * @returns {{ok: true, region: object} | {ok: false, error: string}}
 */
export function editRegion({ label, bbox, prompt }) {
  const name = String(label ?? '');
  const text = String(prompt ?? '');
  const bounds = (bbox ?? []).map((v) => Number(v));
  if (bounds.length !== 4 || bounds.some((v) => !Number.isFinite(v))) {
    return { ok: false, error: `EditRegion "${name}": bbox must be 4 NDC values (min_x, min_y, max_x, max_y)` };
  }
  if (bounds[0] > bounds[2] || bounds[1] > bounds[3]) {
    return {
      ok: false,
      error: `EditRegion "${name}": bbox (${bounds.join(', ')}) is inverted (min must not exceed max on either axis)`,
    };
  }
  return {
    ok: true,
    region: {
      label: name,
      bbox: bounds,
      prompt: text,
      in_frame: bounds.every((v) => v >= -1.0 && v <= 1.0),
    },
  };
}

// ---------------------------------------------------------------------------
// Stage 5 POST — the audit (engine: post.py)
// ---------------------------------------------------------------------------

/** The four POST audit rules, in engine order. */
export const POST_RULES = [
  'grade_in_range',
  'extend_in_range',
  'edit_prompt_present',
  'edit_region_in_frame',
];

/**
 * The audit weights. `edit_region_in_frame` (0.5) is reported but cannot fail a
 * plan; the other three gate it.
 */
export const POST_RULE_WEIGHTS = {
  grade_in_range: 1.0,
  extend_in_range: 1.0,
  edit_prompt_present: 1.0,
  edit_region_in_frame: 0.5,
};

/** The overall gate, shared with the framing engine. */
export const OVERALL_PASS_WEIGHT = 0.8;

/**
 * Audit a post plan against `POST_RULES`, in order. Mirrors `PostPlan.checks()`.
 *
 * @param {{grade: object, extend: object|null, edit: object|null}} plan
 * @returns {Array<{rule: string, pass: boolean, weight: number, detail: string}>}
 */
export function postChecks(plan) {
  const checks = [];

  const badGrade = (plan.grade?.deltas ?? [])
    .filter((d) => {
      const [lo, hi] = GRADE_RANGES[d.param] ?? [-Infinity, Infinity];
      return !(d.to >= lo && d.to <= hi);
    })
    .map((d) => d.param);
  checks.push({
    rule: 'grade_in_range',
    pass: badGrade.length === 0,
    weight: POST_RULE_WEIGHTS.grade_in_range,
    detail: badGrade.length === 0
      ? 'every grade delta target is inside its legal range'
      : `grade delta(s) outside range: ${badGrade.join(', ')}`,
  });

  let extendOk = true;
  let extendDetail = 'no extension requested';
  if (plan.extend) {
    const [lo, hi] = EXTEND_DURATION_RANGE;
    extendOk =
      plan.extend.duration_s >= lo &&
      plan.extend.duration_s <= hi &&
      plan.extend.overlap_frames >= 0 &&
      plan.extend.overlap_frames <= EXTEND_OVERLAP_MAX_FRAMES;
    extendDetail =
      `${plan.extend.mode} ${plan.extend.duration_s.toFixed(1)}s, ` +
      `overlap ${plan.extend.overlap_frames} frame(s)`;
  }
  checks.push({
    rule: 'extend_in_range',
    pass: extendOk,
    weight: POST_RULE_WEIGHTS.extend_in_range,
    detail: extendDetail,
  });

  const regions = plan.edit?.regions ?? [];
  const blank = regions
    .map((r, i) => [r, i])
    .filter(([r]) => !String(r.prompt ?? '').trim())
    .map(([r, i]) => r.label || `region ${i + 1}`);
  checks.push({
    rule: 'edit_prompt_present',
    pass: blank.length === 0,
    weight: POST_RULE_WEIGHTS.edit_prompt_present,
    detail: blank.length === 0
      ? 'every edit region names what to change'
      : `edit region(s) with no prompt: ${blank.join(', ')}`,
  });

  const outside = regions
    .map((r, i) => [r, i])
    .filter(([r]) => !r.in_frame)
    .map(([r, i]) => r.label || `region ${i + 1}`);
  checks.push({
    rule: 'edit_region_in_frame',
    pass: outside.length === 0,
    weight: POST_RULE_WEIGHTS.edit_region_in_frame,
    detail: outside.length === 0
      ? 'every edit region is inside the NDC frame'
      : `edit region(s) outside the NDC frame: ${outside.join(', ')}`,
  });

  return checks;
}

/** True only when every rule weighted at or above the gate passes. */
export function postOverallPass(checks) {
  return checks.every((c) => !(c.weight >= OVERALL_PASS_WEIGHT) || c.pass);
}

// ---------------------------------------------------------------------------
// The JUDGE -> POST gate (engine: nodes.py)
// ---------------------------------------------------------------------------

/**
 * Every failing rule's correction lever, de-duplicated, one line each.
 *
 * Mirrors `nodes._corrections` — the function behind `CinematographerCorrection`,
 * whose output `CinemaGrade` carries into `grade_json` under `corrections`. That
 * carry-through is the gate: POST cannot execute without the judge having
 * executed, and the panel shows the same text the node would produce.
 *
 * @param {object} report a framing report with `scores` (the Judge tab's shape)
 * @returns {string[]}
 */
export function correctionsFromReport(report) {
  const out = [];
  const push = (line) => {
    const text = String(line ?? '').trim();
    if (text && !out.includes(text)) out.push(text);
  };
  const lever = (entry) => entry?.correction ?? entry?.lever ?? entry?.fix;

  const scores = report?.scores;
  if (Array.isArray(scores)) {
    for (const s of scores) {
      if (s && typeof s === 'object' && !s.pass) {
        const corr = lever(s);
        if (corr) push(`${s.rule ?? 'rule'}: ${corr}`);
      }
    }
  }

  const rules = report?.rules;
  if (rules && typeof rules === 'object' && !Array.isArray(rules)) {
    for (const [name, entry] of Object.entries(rules)) {
      if (!entry || typeof entry !== 'object') continue;
      const passed = entry.pass ?? entry.passed ?? true;
      if (passed) continue;
      const corr = lever(entry);
      if (corr) push(`${name}: ${corr}`);
    }
  }

  for (const key of ['corrections', 'levers']) {
    const value = report?.[key];
    if (typeof value === 'string') {
      for (const line of value.split('\n')) push(line);
    } else if (Array.isArray(value)) {
      for (const line of value) push(line);
    }
  }

  const issues = report?.issues;
  if (Array.isArray(issues)) {
    for (const issue of issues) {
      if (issue && typeof issue === 'object' && !(issue.pass ?? true)) {
        push(
          `${issue.rule ?? 'issue'} (shot ${issue.shot_a}->${issue.shot_b}): ` +
            `${issue.detail ?? ''}`,
        );
      }
    }
  }

  return out;
}

/** The `corrections` string `CinematographerCorrection` returns. */
export function correctionsText(report) {
  return correctionsFromReport(report).join('\n');
}
