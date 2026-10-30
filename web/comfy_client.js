/**
 * Cinematographer — drive a live ComfyUI from the panel's current state.
 *
 * The panel used to compose a plan and send nothing. This module closes that
 * loop: it turns the five tabs' state into a real ComfyUI **API-format** prompt,
 * POSTs it to `/prompt`, polls `/history/<id>`, and hands back the values the
 * engine actually returned.
 *
 * Deliberately DOM-free, like `panel_state.js`, so `tools/browser_check.mjs` and
 * a plain `node` script drive the very same builder the panel uses. If the graph
 * were assembled in the click handler, the check would be testing a copy.
 *
 * ---------------------------------------------------------------------------
 * Why the graph looks the way it does
 * ---------------------------------------------------------------------------
 *
 * **It terminates in `PreviewAny`.** Our pack's only `OUTPUT_NODE` is
 * `CinemaElementSave`, and that exists for its side effect on disk. A graph of
 * only our nodes is rejected by ComfyUI with HTTP 400
 * `{"error": {"type": "prompt_no_outputs"}}`. `PreviewAny` is stock, takes one
 * required `source` of type `*`, and renders whatever it is handed — so it is
 * both the output requirement and the read-out.
 *
 * **The report is computed by the SERVER, not shipped from here.** The panel's
 * own report uses `pass`; the engine's uses `passed`. Rather than translate one
 * into the other — which would let a shape bug masquerade as agreement — the
 * graph wires `CinematographerEvaluate` into `CinematographerCorrection` and
 * lets the engine produce its own report from the panel's subject, camera, shot
 * type and intent. The panel then COMPARES the server's verdict with its own and
 * says so on screen. A live run is therefore also a live parity check.
 *
 * **Nothing is written unless asked.** `CinemaElementSave` is opt-in. It writes
 * a sidecar and the registry to the server's disk, and `ElementRegistry.add`
 * RAISES on a duplicate — so a second run after any change would fail with a
 * duplicate error. Off by default; the panel says exactly what it would write.
 *
 * **`registry_path` must be sent EXPLICITLY, and the panel does.** This was
 * measured, not assumed, and the obvious reading is wrong twice over.
 *
 * Both nodes declare `registry_path` in `INPUT_TYPES` with a default of the
 * engine's own `_default_registry_path()` — ComfyUI's output directory. That is
 * a **widget default, not an API default**: the Python methods are
 * `registry_path: str = ""`. ComfyUI does not apply an `INPUT_TYPES` default to
 * a prompt that omits the key, so an omitted path arrives as `""`.
 *
 * And `""` does not mean "use your default" either. `CinemaElementSave` writes
 * each sidecar but skips the registry (`if registry_path: registry.save(...)`),
 * and `CinemaPromptCompose` sets `registry = None`, so every `@tag` comes back
 * unresolved. The graph validates, the run reports success, sidecars appear on
 * disk, and nothing resolves — a silent no-op that looks exactly like a pass.
 *
 * So the panel resolves a path and sends it to both nodes: the server's own
 * default, read back from `/object_info`. `FALLBACK_REGISTRY_PATH` is the
 * engine's documented no-ComfyUI fallback, used only before the server answers.
 */

/** Where ComfyUI listens unless the user says otherwise. */
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8188';

/** Stock node that satisfies the output requirement and renders a value. */
export const PREVIEW_NODE = 'PreviewAny';

/** The one node in our pack that writes to disk. Opt-in only. */
export const ELEMENT_SAVE_NODE = 'CinemaElementSave';

/**
 * The engine's own no-ComfyUI fallback for the Element registry, copied from
 * `nodes._default_registry_path()`. Only used before the server has answered;
 * once `/object_info` replies, the panel shows the server's real path instead.
 */
export const FALLBACK_REGISTRY_PATH = 'cinematographer/elements.json';

/** How long to wait for a prompt to finish before giving up. */
export const DEFAULT_POLL_TIMEOUT_MS = 120000;
export const DEFAULT_POLL_INTERVAL_MS = 400;

/**
 * The emotion combo's exact members, as `CinemaDirectorPanel` publishes them.
 *
 * This is the one enum where the panel and the engine disagree on spelling, and
 * the disagreement is not cosmetic. `director.EMOTION` in the panel is slugs
 * (`sadness`); the node's COMBO is Title Case (`Sadness`), and ComfyUI validates
 * a COMBO by **exact membership**.
 *
 * Measured, not assumed: sending `"sadness"` makes `CinemaDirectorPanel` fail
 * validation, and ComfyUI then drops that node *and every node downstream of it*
 * — here the `CinemaPromptCompose` chain and four of the seven `PreviewAny`
 * taps — while still answering **HTTP 200 with a `prompt_id`** and reporting
 * `status_str: "success"`. The dropped nodes are named only in the response's
 * `node_errors`, which is why `runLive` now refuses to call such a run clean.
 *
 * `parity_check.py` asserts this list equals `director.EMOTIONS` exactly, so it
 * cannot drift into a second, hand-typed source of truth.
 */
export const ENGINE_EMOTIONS = [
  'Sadness',
  'Fear',
  'Anger',
  'Joy',
  'Trust',
  'Disgust',
  'Surprise',
  'Interest',
  'Hope',
];

/**
 * Map the panel's emotion slug onto the node's exact COMBO member.
 *
 * An unrecognised value is passed through unchanged rather than dropped: the
 * server should be the one to reject it, out loud, in `node_errors`.
 */
export function engineEmotion(slug) {
  const text = String(slug ?? '').trim();
  if (!text || text === 'auto') return 'auto';
  const hit = ENGINE_EMOTIONS.find((e) => e.toLowerCase() === text.toLowerCase());
  return hit ?? text;
}

/** The seven grade controls, in the engine's own order. */
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
 * The taps the panel reads back, in the order it shows them.
 *
 * `source` is `[nodeId, outputIndex]`, matching the engine's `RETURN_NAMES`:
 * `CinematographerEvaluate` -> (report_json, overall_pass, summary), so index 2
 * is the summary. Getting one of these wrong yields a plausible-looking wrong
 * string, so each label names the output it claims to be.
 */
const TAP_SPEC = [
  { key: 'evaluate', from: 'evaluate', index: 2, label: 'CinematographerEvaluate · summary' },
  { key: 'corrections', from: 'correction', index: 0, label: 'CinematographerCorrection · corrections' },
  { key: 'grade', from: 'grade', index: 2, label: 'CinemaGrade · summary' },
  { key: 'final_prompt', from: 'compose', index: 0, label: 'CinemaPromptCompose · final_prompt' },
  { key: 'attachments', from: 'compose', index: 1, label: 'CinemaPromptCompose · attachments_json' },
  { key: 'unresolved', from: 'compose', index: 2, label: 'CinemaPromptCompose · unresolved_json' },
  { key: 'panel', from: 'panel', index: 2, label: 'CinemaDirectorPanel · summary' },
];

/** A client id ComfyUI can route on. Any string works; this one is traceable. */
export function newClientId() {
  const rand = Math.random().toString(36).slice(2, 10);
  return `cinematographer-panel-${rand}`;
}

/** JSON with a stable key order, so the same state always yields the same bytes. */
function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${stableJson(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value === undefined ? null : value);
}

/**
 * The `CinemaDirectorPanel` inputs for one Director-tab state.
 *
 * `auto` is a legal combo value for every enum here — the node's own combos
 * begin with it — so the panel's "auto" is sent as-is rather than omitted. That
 * is the opposite of the published HTTP contract, where `auto` is not a value;
 * the node is the one that accepts it.
 *
 * The node takes ONE emotion. The panel can hold several, so the first is sent
 * and the rest are reported by `buildGraph` rather than silently dropped.
 */
function panelInputs(director) {
  const first = (director.emotions || [])[0] || null;
  return {
    genre: director.genre,
    era: director.era,
    pacing: director.pacing,
    camera_model: director.camera_model,
    camera_lens: director.camera_lens,
    camera_aperture: director.camera_aperture,
    light: director.light,
    color_palette: director.color_palette,
    custom_palette: '',
    emotion_character: first ? first.element : '',
    emotion: first ? engineEmotion(first.emotion) : 'auto',
    emotion_intensity: first ? first.intensity : 0.5,
  };
}

/**
 * Build the API-format prompt from the panel's current state.
 *
 * Pure: no DOM, no network, no clock. Returns the graph plus everything the
 * panel needs to explain it.
 *
 * @param {object} input
 * @param {object} input.director      Director-tab state (`DEFAULT_DIRECTOR_STATE` shape)
 * @param {object} input.subject       the Judge tab's subject
 * @param {object} input.camera        the Judge tab's camera pose
 * @param {object} input.intent        the Judge tab's shot intent
 * @param {string} input.shotType      'closeup' | 'medium' | 'wide'
 * @param {string} input.action        the Shoot tab's action prose
 * @param {string[]} input.moves       the Director tab's move stack
 * @param {object} input.grade         the Post tab's seven grade values
 * @param {string} input.registryPath  '' = let the server resolve its own default
 * @param {object[]} [input.elements]  when present, write these via CinemaElementSave
 */
export function buildGraph(input) {
  const {
    director,
    subject,
    camera,
    intent,
    shotType,
    action,
    moves = [],
    grade = {},
    registryPath = '',
    elements = null,
  } = input;

  const graph = {};
  const notes = [];

  // -- the five stages, wired in order ------------------------------------
  graph['1'] = { class_type: 'CinemaDirectorPanel', inputs: panelInputs(director) };
  graph['2'] = {
    class_type: 'CinematographerEvaluate',
    inputs: {
      subject_json: stableJson(subject),
      camera_json: stableJson(camera),
      shot_type: shotType,
      intent_json: stableJson(intent),
    },
  };
  graph['3'] = {
    class_type: 'CinematographerCorrection',
    inputs: { report_json: ['2', 0] },
  };
  graph['4'] = {
    class_type: 'CinemaGrade',
    inputs: {
      ...GRADE_PARAMS.reduce((acc, p) => {
        acc[p] = Number(grade[p] ?? 0);
        return acc;
      }, {}),
      // The JUDGE -> POST gate, live: the engine's own corrections, straight
      // into the grade plan, exactly as the two nodes are meant to chain.
      corrections: ['3', 0],
    },
  };
  graph['5'] = {
    class_type: 'CinemaPromptCompose',
    inputs: {
      action: String(action ?? ''),
      panel_json: ['1', 0],
      moves: moves.join(', '),
      ...(registryPath ? { registry_path: String(registryPath) } : {}),
    },
  };
  graph['6'] = {
    class_type: 'CinemaCameraMove',
    inputs: {
      prompt: ['5', 0],
      move: moves.length ? moves[0] : 'none',
    },
  };

  // -- the read-outs ------------------------------------------------------
  const idFor = {
    panel: '1',
    evaluate: '2',
    correction: '3',
    grade: '4',
    compose: '5',
  };
  const taps = [];
  let next = 7;
  for (const spec of TAP_SPEC) {
    const id = String(next++);
    graph[id] = {
      class_type: PREVIEW_NODE,
      inputs: { source: [idFor[spec.from], spec.index] },
    };
    taps.push({ id, key: spec.key, label: spec.label, from: idFor[spec.from], index: spec.index });
  }

  // -- optional: write the panel's Elements to the server ------------------
  const elementIds = [];
  if (elements && elements.length) {
    for (const el of elements) {
      const id = String(next++);
      graph[id] = {
        class_type: ELEMENT_SAVE_NODE,
        inputs: {
          name: el.name,
          category: el.category,
          image_path: el.asset_path,
          description: el.description ?? '',
          seed: Number(el.seed ?? 0),
          palette: el.palette ?? '',
          has_bbox: Boolean(el.bbox),
          bbox_min_x: el.bbox ? Number(el.bbox[0]) : -1,
          bbox_min_y: el.bbox ? Number(el.bbox[1]) : -1,
          bbox_max_x: el.bbox ? Number(el.bbox[2]) : 1,
          bbox_max_y: el.bbox ? Number(el.bbox[3]) : 1,
          ...(registryPath ? { registry_path: String(registryPath) } : {}),
        },
      };
      elementIds.push({ id, name: el.name, category: el.category });
    }
    notes.push(
      `writes ${elements.length} sidecar(s) and the registry to the server's disk ` +
        `via ${ELEMENT_SAVE_NODE} — this is a real file write, not a plan`,
    );
    notes.push(
      'the engine RAISES on a duplicate Element, so re-running after changing one ' +
        'can fail with a duplicate error; that error is shown verbatim',
    );
  }

  const emotions = director.emotions || [];
  if (emotions.length > 1) {
    notes.push(
      `CinemaDirectorPanel takes one emotion; the panel holds ${emotions.length}, ` +
        `so only "${emotions[0].element}" was sent`,
    );
  }
  if (moves.length > 1) {
    notes.push(
      `CinemaCameraMove takes one move; the panel's stack has ${moves.length}, ` +
        `so only "${moves[0]}" was sent to it — all ${moves.length} still reach ` +
        'CinemaPromptCompose',
    );
  }

  return {
    graph,
    taps,
    elementIds,
    notes,
    nodeCount: Object.keys(graph).length,
    classTypes: [...new Set(Object.values(graph).map((n) => n.class_type))].sort(),
    previewCount: taps.length,
  };
}

/**
 * Ask the server what it knows.
 *
 * `/object_info/<class>` returns one class, which keeps the payload small; the
 * full `/object_info` is over a megabyte. The registry default is read from
 * `CinemaElementSave.registry_path` so the panel can show the path the server
 * would actually use instead of guessing it.
 */
export async function probeServer(baseUrl = DEFAULT_BASE_URL, timeoutMs = 4000) {
  const base = String(baseUrl || '').replace(/\/+$/, '');
  const withTimeout = async (url) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  };

  try {
    const stats = await withTimeout(`${base}/system_stats`);
    if (!stats.ok) {
      return { ok: false, error: `GET /system_stats -> HTTP ${stats.status}` };
    }
    const info = await stats.json();

    let classes = [];
    let registryDefault = '';
    try {
      const oi = await withTimeout(`${base}/object_info`);
      if (oi.ok) {
        const all = await oi.json();
        classes = Object.keys(all);
        const save = all[ELEMENT_SAVE_NODE];
        registryDefault = save?.input?.optional?.registry_path?.[1]?.default ?? '';
      }
    } catch {
      /* /object_info is a nicety; its absence must not fail the probe */
    }

    return {
      ok: true,
      base,
      version: info?.system?.comfyui_version ?? 'unknown',
      os: info?.system?.os ?? 'unknown',
      devices: (info?.devices || []).map((d) => d.name).filter(Boolean),
      classes,
      registryDefault,
    };
  } catch (err) {
    const msg = err?.name === 'AbortError' ? `no response within ${timeoutMs} ms` : String(err?.message ?? err);
    return { ok: false, error: msg, base };
  }
}

/**
 * POST the graph. Returns a discriminated result — never throws for an HTTP
 * error, because `prompt_no_outputs` is a case the panel must render, not crash on.
 */
export async function submitPrompt(baseUrl, graph, clientId, timeoutMs = 30000) {
  const base = String(baseUrl || '').replace(/\/+$/, '');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}/prompt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: graph, client_id: clientId }),
      signal: ctrl.signal,
    });
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (res.ok && body?.prompt_id) {
      return { ok: true, prompt_id: body.prompt_id, node_errors: body.node_errors ?? {} };
    }
    return {
      ok: false,
      status: res.status,
      error: body?.error ?? null,
      node_errors: body?.node_errors ?? {},
      raw: body,
    };
  } catch (err) {
    const msg = err?.name === 'AbortError' ? `POST /prompt timed out after ${timeoutMs} ms` : String(err?.message ?? err);
    return { ok: false, status: 0, error: { type: 'network', message: msg }, node_errors: {} };
  } finally {
    clearTimeout(timer);
  }
}

/** Poll `/history/<id>` until the record appears, or give up. */
export async function awaitHistory(baseUrl, promptId, opts = {}) {
  const base = String(baseUrl || '').replace(/\/+$/, '');
  const timeoutMs = opts.timeoutMs ?? DEFAULT_POLL_TIMEOUT_MS;
  const intervalMs = opts.intervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const onTick = opts.onTick;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/history/${encodeURIComponent(promptId)}`);
      if (res.ok) {
        const all = await res.json();
        const rec = all?.[promptId];
        if (rec) return { ok: true, record: rec };
      }
    } catch {
      /* transient; keep polling until the deadline */
    }
    if (onTick) onTick();
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { ok: false, error: `no /history entry for ${promptId} within ${timeoutMs} ms` };
}

/**
 * Read the taps out of a history record.
 *
 * `outputs` lists ONLY nodes that produced UI output. Our nodes return plain
 * STRING/BOOLEAN and never appear as keys, so counting that dict would read
 * "0 of our nodes ran" — which is false. Every node that ran is counted from the
 * PreviewAny taps instead.
 */
export function readTaps(record, taps) {
  const outputs = record?.outputs ?? {};
  return taps.map((tap) => {
    const entry = outputs[tap.id];
    const text = Array.isArray(entry?.text) ? entry.text.join('\n') : null;
    return { ...tap, ran: entry !== undefined, text };
  });
}

/** How many of the panel's taps actually produced output. */
export function countRan(record, taps) {
  const outputs = record?.outputs ?? {};
  return taps.filter((t) => outputs[t.id] !== undefined).length;
}

/** Execution errors, flattened from the status message list. */
export function executionErrors(record) {
  const messages = record?.status?.messages ?? [];
  const out = [];
  for (const entry of messages) {
    if (!Array.isArray(entry) || entry[0] !== 'execution_error') continue;
    const p = entry[1] ?? {};
    out.push({
      node_id: p.node_id ?? '?',
      node_type: p.node_type ?? '?',
      message: p.exception_message ?? p.exception_type ?? 'unknown error',
    });
  }
  return out;
}

/** A one-line description of a failed POST, for the screen. */
export function describeSubmitFailure(result) {
  const type = result?.error?.type ?? 'unknown';
  const message = result?.error?.message ?? '';
  if (type === 'prompt_no_outputs') {
    return (
      'ComfyUI rejected the graph with prompt_no_outputs: it has no node that ' +
      'produces UI output. This panel terminates in PreviewAny, so seeing this ' +
      'means the graph was built without its taps.'
    );
  }
  if (type === 'network') {
    return `Could not reach ComfyUI: ${message}`;
  }
  const nodeErrors = Object.entries(result?.node_errors ?? {});
  if (nodeErrors.length) {
    const [id, info] = nodeErrors[0];
    const detail = info?.errors?.[0]?.message ?? info?.errors?.[0]?.details ?? 'invalid input';
    return `ComfyUI rejected node ${id} (${info?.class_type ?? '?'}): ${detail}`;
  }
  return `ComfyUI rejected the prompt: HTTP ${result?.status} ${type}${message ? ` — ${message}` : ''}`;
}
