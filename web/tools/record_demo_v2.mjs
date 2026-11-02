/**
 * Records the v2 submission demo video from the real panel.
 *
 *   # 1. serve the panel
 *   cd /tmp/cine-publish/web && python3 -m http.server 8765
 *   # 2. record
 *   node web/tools/record_demo_v2.mjs http://127.0.0.1:8765/ <output-dir>
 *
 * Scope: the full walkthrough — all seven tabs, then the Cloud render.
 *
 * Chrome launch flags and the CDP client are lifted verbatim from
 * `browser_check.mjs` / `record_demo.mjs` — those flags are what make three.js
 * render headless, so they are not to be "improved".
 *
 * Motion comes from `Page.startScreencast`, not from per-beat screenshots: the
 * compositor pushes a frame whenever the page repaints, so a slider drag is
 * recorded as a drag rather than as two stills.
 *
 * Every number that appears on screen is read back out of the live panel and
 * written to `beats.json`. Nothing is retyped from the script.
 *
 * The output directory is REQUIRED (argv[3]). The v1 recorder inferred it as
 * `resolve(WEB,'..','..')`, which was correct for an `app/web/tools/` layout and
 * resolves to `/tmp` in this one. It is not inferred here.
 *
 * Exit code 0 = the capture completed and the beats were recorded.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, '..');

const URL_ = process.argv[2] ?? 'http://127.0.0.1:8765/';
const OUT = process.argv[3] ? resolve(process.argv[3]) : null;
if (!OUT) {
  console.log('FAIL — no output directory. Usage:');
  console.log('  node web/tools/record_demo_v2.mjs <panel-url> <output-dir>');
  process.exit(2);
}
const RAW = join(OUT, 'raw');

// The render to show. It lives beside the panel, not inside it, so it is not
// reachable over the panel's own static server. Rather than stand up a second
// server (or drop a copy into `web/`), the file is read here and injected into
// the page as a blob URL. Nothing on disk changes and the cut stays reproducible
// from this one script.
const RENDER_MP4 =
  process.env.RENDER_MP4 ?? '/tmp/cine-publish/assets/reshoot_ltx25.mp4';
if (!existsSync(RENDER_MP4)) {
  console.log(`FAIL — render not found at ${RENDER_MP4} (set RENDER_MP4).`);
  process.exit(2);
}
const RENDER_B64 = readFileSync(RENDER_MP4).toString('base64');
console.log(`render: ${RENDER_MP4} (${readFileSync(RENDER_MP4).length} B)`);

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);

const chromePath = CHROME_CANDIDATES.find((p) => existsSync(p));
if (!chromePath) {
  console.log('FAIL — no Chrome/Chromium found. Set CHROME_PATH.');
  process.exit(1);
}

mkdirSync(RAW, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Launch Chrome with remote debugging — flags verbatim from browser_check.mjs
// ---------------------------------------------------------------------------

const profile = mkdtempSync(join(tmpdir(), 'cine-rec2-'));
const chrome = spawn(
  chromePath,
  [
    '--headless=new',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--enable-unsafe-swiftshader',
    '--use-gl=angle',
    '--use-angle=swiftshader',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    '--window-size=1920,1080',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    'about:blank',
  ],
  { stdio: 'ignore' },
);

const portFile = join(profile, 'DevToolsActivePort');
let port = null;
for (let i = 0; i < 100; i++) {
  if (existsSync(portFile)) {
    port = readFileSync(portFile, 'utf8').split('\n')[0].trim();
    if (port) break;
  }
  await sleep(100);
}
if (!port) {
  chrome.kill();
  console.log('FAIL — Chrome did not expose a debugging port.');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Minimal CDP client — verbatim from browser_check.mjs
// ---------------------------------------------------------------------------

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === 'page');
if (!page) {
  chrome.kill();
  console.log('FAIL — no page target.');
  process.exit(1);
}

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener('open', res, { once: true });
  ws.addEventListener('error', rej, { once: true });
});

let nextId = 1;
const pending = new Map();
const screencastFrames = [];
let screencastOn = false;

ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  } else if (msg.method === 'Page.screencastFrame') {
    screencastFrames.push({
      data: msg.params.data,
      t: Date.now(),
      sessionId: msg.params.sessionId,
    });
    // Ack immediately, or the compositor stops sending.
    send('Page.screencastFrameAck', { sessionId: msg.params.sessionId }).catch(() => {});
  }
});

function send(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const res = await send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (res.exceptionDetails) {
    throw new Error(res.exceptionDetails.exception?.description ?? 'evaluate threw');
  }
  return res.result.value;
}

async function waitFor(expression, label, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await evaluate(expression)) return true;
    } catch {
      /* still loading */
    }
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${label}`);
}

// ---------------------------------------------------------------------------
// Page setup
// ---------------------------------------------------------------------------

await send('Page.enable');
await send('Runtime.enable');
// Record into a 960x540 surface and upscale 2x to 1920x1080 afterwards.
//
// Why: the headless SwiftShader compositor repaints in proportion to surface
// area, so a native 1920x1080 screencast yields ~1.9 fps -- a slideshow, not
// motion. At 960x540 the same page repaints at ~10 fps. To keep the layout at
// its true 1920 CSS px (so nothing is cramped) we lay out at 1920 and paint
// through `zoom: 0.5`, which is the only one of the three emulation routes that
// actually works in headless:
//   - setDeviceMetricsOverride({deviceScaleFactor:0.5}) -> innerWidth 960 (cramped)
//   - setPageScaleFactor({pageScaleFactor:0.5})        -> silent no-op
//   - documentElement.style.zoom = '0.5'               -> layout 1920, paint 960
await send('Emulation.setDeviceMetricsOverride', {
  width: 960,
  height: 540,
  deviceScaleFactor: 1,
  mobile: false,
});
await send('Page.navigate', { url: URL_ });
await waitFor('!!window.__cinematographer', 'the panel to boot');
await waitFor('document.getElementById("rules")?.children.length === 9', 'the rule panel');
await sleep(1200);

const bootErrors = await evaluate('JSON.stringify(window.__panelErrors ?? [])');
if (bootErrors !== '[]') {
  console.log(`FAIL — the panel booted with JS errors: ${bootErrors}`);
  chrome.kill();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Lay out at 1920 CSS px, paint into 960x540
// ---------------------------------------------------------------------------

// The Judge tab is hidden at load, so its column has no layout box and the
// viewport card measures 0x0. Show it first, then zoom, then resize the
// renderer. `view.resize()` reallocates the drawing buffer, which clears it,
// so the master render() must run afterwards or the canvas stays black.
await evaluate('window.__cinematographer.showTab("judge"), true');
await sleep(300);
await evaluate('document.documentElement.style.zoom = "0.5", true');
await sleep(300);
await evaluate('(() => { const c = window.__cinematographer; c.view.resize(); c.render(); return true; })()');
await sleep(600);

const layout = await evaluate(`JSON.stringify({
  inner: [window.innerWidth, window.innerHeight],
  scrollW: document.body.scrollWidth,
  canvas: (() => { const g = document.getElementById('gl'); return [g.width, g.height]; })(),
  status: document.getElementById('three-status')?.textContent ?? '',
})`);
const L = JSON.parse(layout);
console.log(`layout: inner=${L.inner.join('x')} body.scrollWidth=${L.scrollW} canvas=${L.canvas.join('x')} · ${L.status}`);
if (L.canvas[0] < 1000) {
  console.log('FAIL — the three.js canvas did not lay out at full width; the zoom sequence is broken.');
  chrome.kill();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Capture helpers
// ---------------------------------------------------------------------------

const beats = [];
// Set by `beat()` so `snapshot()` can stamp each record with its slot's start.
let currentBeatStart = 0;
let currentBeatDuration = 0;
let t0 = null;

/** Start the screencast. Frames arrive on every compositor repaint. */
async function startCast() {
  screencastFrames.length = 0;
  await send('Page.startScreencast', {
    format: 'jpeg',
    quality: 92,
    maxWidth: 960,
    maxHeight: 540,
    everyNthFrame: 1,
  });
  screencastOn = true;
  t0 = Date.now();
}

async function stopCast() {
  if (!screencastOn) return;
  await send('Page.stopScreencast');
  screencastOn = false;
}

/** Seconds since the cast started. */
const now = () => (Date.now() - t0) / 1000;

/**
 * Drive a slider the way a person does: a sequence of real `input` events, so
 * the panel recomputes and the compositor repaints on every step.
 */
async function dragSlider(id, from, to, seconds) {
  const steps = Math.max(2, Math.round(seconds * 30));
  await evaluate(`(() => {
    const el = document.getElementById(${JSON.stringify(id)});
    el.value = ${JSON.stringify(String(from))};
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  for (let i = 1; i <= steps; i++) {
    const v = from + ((to - from) * i) / steps;
    await evaluate(`(() => {
      const el = document.getElementById(${JSON.stringify(id)});
      el.value = ${JSON.stringify(String(v))};
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
    await sleep((seconds * 1000) / steps);
  }
}

/** Hold the current view for `seconds`, letting the compositor push frames. */
async function hold(seconds) {
  await sleep(seconds * 1000);
}

/** Switch tabs the way a viewer does, and let the panel re-render. */
async function tab(name, settle = 700) {
  await evaluate(`window.__cinematographer.showTab(${JSON.stringify(name)}), true`);
  await sleep(settle);
}

/**
 * A caption strip pinned to the bottom of the viewport.
 *
 * The panel is 1920 CSS px wide and the capture is 960x540, so the strip is
 * sized in CSS px and inherits the 0.5 zoom. It is `position: fixed`, so it
 * survives tab switches and scroll.
 */
async function caption(text, sub = '') {
  await evaluate(`(() => {
    let el = document.getElementById('__cap');
    if (!el) {
      const style = document.createElement('style');
      style.textContent = \`
        #__cap {
          position: fixed; left: 0; right: 0; bottom: 0; z-index: 99999;
          padding: 18px 40px 20px;
          background: linear-gradient(to top, rgba(4,7,12,0.97) 0%, rgba(4,7,12,0.90) 70%, rgba(4,7,12,0) 100%);
          font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
          color: #e8eef7; pointer-events: none;
        }
        #__cap .c-t { font-size: 30px; font-weight: 650; letter-spacing: -0.3px; }
        #__cap .c-s { font-size: 19px; color: #9fb3c8; margin-top: 5px; line-height: 1.35; }
        #__cap .c-s code { color: #7fb2e5; font-family: ui-monospace, Menlo, monospace; }
      \`;
      document.head.appendChild(style);
      el = document.createElement('div');
      el.id = '__cap';
      document.body.appendChild(el);
    }
    el.innerHTML = '<div class="c-t"></div><div class="c-s"></div>';
    el.querySelector('.c-t').textContent = ${JSON.stringify(text)};
    el.querySelector('.c-s').textContent = ${JSON.stringify(sub)};
    return true;
  })()`);
}

/** Read the live panel state into a beat record. */
async function snapshot(label) {
  // Nothing secret may reach the screen. That is a competition rule and a
  // security rule, and eyeballing five minutes of video is not a check. Scan
  // the rendered text of the whole document on every beat and fail loudly.
  const leak = await evaluate(`(() => {
    const text = document.body.innerText + ' ' + [...document.querySelectorAll('input,textarea')]
      .map((e) => e.value).join(' ');
    const pats = [
      [/\\bsk-[A-Za-z0-9_-]{16,}/g, 'openai-style key'],
      [/\\bBearer\\s+[A-Za-z0-9._-]{16,}/g, 'bearer token'],
      [/\\beyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}/g, 'JWT'],
      [/X-Amz-Signature/gi, 'signed S3 URL'],
      [/[?&](token|key|signature|sig|access_token)=/gi, 'credential in a query string'],
      [/service_role/gi, 'service-role key'],
      [/csrf/gi, 'CSRF token'],
      [/\\bapi[_-]?key\\b/gi, 'api_key'],
      [/\\bgh[pousr]_[A-Za-z0-9]{20,}/g, 'GitHub token'],
      [/\\bAIza[A-Za-z0-9_-]{20,}/g, 'Google API key'],
    ];
    const hits = [];
    for (const [re, name] of pats) {
      const m = text.match(re);
      if (m) hits.push(name + ': ' + m.slice(0, 3).join(', '));
    }
    return JSON.stringify(hits);
  })()`);
  const hits = JSON.parse(leak);
  if (hits.length) {
    console.log(`\nFAIL — possible secret on screen at beat '${label}':`);
    for (const h of hits) console.log(`   ${h}`);
    await stopCast();
    chrome.kill();
    process.exit(1);
  }

  const data = await evaluate(`(() => {
    const C = window.__cinematographer;
    const d = C.compute();
    const rules = [...document.querySelectorAll('#rules .rule')].map((r) => ({
      name: r.querySelector('.rule-name')?.textContent.trim(),
      weight: r.querySelector('.rule-weight')?.textContent.trim(),
      verdict: r.querySelector('.rule-badge')?.textContent.trim(),
      value: r.querySelector('.rule-value')?.textContent.trim(),
      target: r.querySelector('.rule-target')?.textContent.trim(),
      lever: r.querySelector('.rule-lever')?.textContent.trim() ?? null,
    }));
    const txt = (id) => document.getElementById(id)?.textContent.trim() ?? null;
    return {
      overall: txt('overall-value'),
      reliability: txt('reliability-value'),
      solver: txt('solver-badge'),
      solverNote: txt('solver-note'),
      rules,
      continuity: document.getElementById('continuity-out')?.innerText.trim() ?? '',
      tab: document.querySelector('.tab.on')?.textContent.trim(),
      // Per-tab evidence, read from the live DOM rather than retyped.
      studio: {
        verdict: txt('st-verdict-head'),
        gate: txt('st-gate'),
        status: txt('st-status'),
        prompt: txt('st-prompt'),
        mappingRows: document.querySelectorAll('#st-mapping tr').length,
        verdictRows: document.querySelectorAll('#st-verdict tr').length,
      },
      director: {
        cost: txt('d-cost'),
        costNote: txt('d-cost-note'),
        tags: txt('d-tags'),
        moves: document.querySelectorAll('#d-move-stack .move, #d-move-stack li').length,
        selects: document.querySelectorAll('#tab-director select').length,
        promptOut: (txt('d-prompt-out') ?? '').slice(0, 300),
      },
      elements: {
        count: txt('e-count'),
        summary: txt('e-summary'),
        tag: txt('e-tag'),
        measurable: txt('e-measurable'),
        sidecar: txt('e-sidecar'),
        errors: txt('e-errors'),
        registryRows: document.querySelectorAll('#e-registry .registry-item').length,
      },
      shoot: {
        ok: txt('s-ok'),
        final: (txt('s-final') ?? '').slice(0, 300),
        unresolvedCount: txt('s-unresolved-count'),
        unresolved: (txt('s-unresolved') ?? '').slice(0, 200),
        attachCount: txt('s-attach-count'),
        tags: txt('s-tags'),
      },
      post: {
        gate: txt('p-gate'),
        neutral: txt('p-neutral'),
        summary: txt('p-summary'),
        overall: txt('p-overall'),
        checks: document.querySelectorAll('#p-checks .rule').length,
        gradeControls: document.querySelectorAll('#p-grade-controls input[type=range]').length,
      },
      run: {
        serverStatus: txt('r-server-status'),
        runStatus: txt('r-run-status'),
        ran: txt('r-ran'),
        graphStats: txt('r-graph-stats'),
        reconcile: txt('r-reconcile'),
        tapCount: document.querySelectorAll('#r-taps .tap-item').length,
        honesty: (document.querySelector('#tab-run .col-right .card:last-child .card-foot')?.textContent ?? '')
          .replace(/\\s+/g, ' ').trim().slice(0, 400),
      },
    };
  })()`);
  const beat = {
    label,
    t: +now().toFixed(2),
    // When this beat's slot began, and how long it was planned to run. The
    // assembler places each narration line at `tStart + lead-in`, so the voice
    // lands inside the beat it belongs to even when a beat overruns its slot.
    tStart: +currentBeatStart.toFixed(3),
    planned: currentBeatDuration,
    ...data,
  };
  beats.push(beat);
  const hr = data.rules.find((r) => r.name === 'headroom');
  console.log(
    `  [${beat.t.toFixed(1).padStart(6)}s] ${label.padEnd(30)} ` +
      `tab=${String(data.tab).padEnd(9)} overall=${data.overall} headroom=${hr ? `${hr.value} ${hr.verdict}` : '—'}`,
  );
  return beat;
}

// ---------------------------------------------------------------------------
// The shot list — full walkthrough, all seven tabs, then the render
//
// Every beat's length comes from `timeline.json`, which `make_timeline_v2.py`
// produced from the measured narration. The recorder does not carry its own
// timings: the on-screen action is paced to the voice, not the other way round.
// ---------------------------------------------------------------------------

const timeline = JSON.parse(readFileSync(join(OUT, 'timeline.json'), 'utf8'));
const DUR = Object.fromEntries(timeline.map((b) => [b.id, b.duration]));
const LABEL = Object.fromEntries(timeline.map((b) => [b.id, b.label]));
console.log(`${timeline.length} beats, ${timeline.reduce((a, b) => a + b.duration, 0).toFixed(1)}s planned\n`);

/**
 * Run one beat's action, then hold the view until the beat's planned duration
 * has elapsed. If the action overruns its slot the beat simply runs long and
 * says so — better a long beat than a truncated action.
 */
async function beat(id, fn) {
  const dur = DUR[id];
  if (dur == null) throw new Error(`no timeline entry for beat '${id}'`);
  const start = now();
  currentBeatStart = start;
  currentBeatDuration = dur;
  await fn();
  const left = dur - (now() - start);
  if (left > 0) await hold(left);
  const used = now() - start;
  const flag = used > dur + 0.05 ? '  <-- OVER' : '';
  console.log(`  ${id.padEnd(20)} ${used.toFixed(2)}s / ${dur}s${flag}`);
}

// Decode the render up front, so the probe's cost is not charged to a beat.
await evaluate(`(() => {
  const bin = atob(${JSON.stringify(RENDER_B64)});
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  window.__renderUrl = URL.createObjectURL(new Blob([bytes], { type: 'video/mp4' }));
  return true;
})()`);
const renderProbe = await evaluate(`(async () => {
  const v = document.createElement('video');
  v.src = window.__renderUrl;
  v.preload = 'auto';
  await new Promise((res) => {
    v.addEventListener('loadedmetadata', res, { once: true });
    v.addEventListener('error', res, { once: true });
    setTimeout(res, 8000);
  });
  return JSON.stringify({
    w: v.videoWidth, h: v.videoHeight, dur: v.duration,
    err: v.error ? v.error.code + ':' + v.error.message : null,
  });
})()`);
console.log(`render probe: ${renderProbe}`);
const RP = JSON.parse(renderProbe);
if (!RP.w || RP.err) {
  console.log('FAIL — headless Chrome could not decode the render; the video beat would be blank.');
  chrome.kill();
  process.exit(1);
}

console.log('Recording…\n');
await startCast();

// ===========================================================================
// 1. STUDIO — the front door (default on load)
// ===========================================================================
await beat('title', async () => {
  await tab('studio', 900);
  await caption(
    'Studio — the front door',
    'One scene, four dropdowns, one button. The shape of Comfy Org\'s reference app; the difference is what comes back.',
  );
  await snapshot(LABEL.title);
});

await beat('studio_verdict', async () => {
  await caption(
    'The verdict is the difference',
    'Nine per-shot rules, each measured, each pass or fail, with the engine\'s own correction lever for every failure.',
  );
  await evaluate('document.getElementById("st-verdict").scrollIntoView({block:"center"}), true');
  await sleep(400);
  await snapshot(LABEL.studio_verdict);
});

await beat('studio_autoframe', async () => {
  await caption(
    'Auto-frame the camera',
    'A real solver, run in the browser. It reports whether it converged, and it writes to no other tab.',
  );
  await evaluate('document.getElementById("st-autoframe").click(), true');
  await sleep(1200);
  await snapshot(LABEL.studio_autoframe);
});

// ===========================================================================
// 2. DIRECTOR — the parameter surface
// ===========================================================================
await beat('director', async () => {
  await tab('director');
  await caption(
    'Director — the parameters',
    'Thirteen dropdowns, every option a real engine enum member. The panel asserts that at load; drift is a visible error.',
  );
  await snapshot(LABEL.director);
});

await beat('director_change', async () => {
  await caption(
    'Change a parameter, the plan recomputes',
    'Genre, era, tempo; body, lens, aperture. The cost readout is a real published table, not a guess.',
  );
  await evaluate(`(() => {
    const set = (id, v) => { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); };
    set('d-genre', 'noir'); set('d-era', '1980s'); set('d-model', '35mm-film'); set('d-lens', 'anamorphic');
    return true;
  })()`);
  await sleep(500);
  await dragSlider('d-duration', 5, 30, 2.4);
  await snapshot(LABEL.director_change);
});

// ===========================================================================
// 3. ELEMENTS — the registry and the @ tokens
// ===========================================================================
await beat('elements', async () => {
  await tab('elements');
  await caption(
    'Elements — the cast and the sets',
    'Characters, locations, props. Each one is a named, categorised, reusable asset with a sidecar.',
  );
  await snapshot(LABEL.elements);
});

await beat('elements_tag', async () => {
  await caption(
    'The @ reference token',
    'An Element is referenced by @name. The panel validates what the node would write — and writes no file itself.',
  );
  await evaluate('document.getElementById("e-tag").scrollIntoView({block:"center"}), true');
  await sleep(400);
  await snapshot(LABEL.elements_tag);
});

// ===========================================================================
// 4. SHOOT — the prompt composer
// ===========================================================================
await beat('shoot', async () => {
  await tab('shoot');
  await caption(
    'Shoot — the prompt composer',
    'Two jobs: describe the action, and carry the tags. @Element resolves to the API\'s <<<image_N>>> token; #move to a camera move.',
  );
  await evaluate(`(() => {
    const ta = document.getElementById('s-action');
    ta.value = 'A detective crosses the diner, @tamsincamp waits by the window';
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(600);
  await snapshot(LABEL.shoot);
});

await beat('shoot_unresolved', async () => {
  await caption(
    'An unresolved tag is a visible failure',
    'Not a silent drop. The panel names the tag and the engine\'s own reason, and the count is on screen.',
  );
  await evaluate(`(() => {
    const ta = document.getElementById('s-action');
    ta.value = 'A detective crosses the diner, @nobody-here waits by the window';
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(600);
  await snapshot(LABEL.shoot_unresolved);
});

// ===========================================================================
// 5. POST — grade, extend, edit
// ===========================================================================
await beat('post', async () => {
  await tab('post');
  await caption(
    'Post — grade, extend, edit',
    'Seven grade parameters, each with a real range. The summary is the engine\'s own, computed from the deltas.',
  );
  await dragSlider('p-grade-temperature', 0, 0.6, 2.2);
  await dragSlider('p-grade-contrast', 0, 0.4, 1.8);
  await snapshot(LABEL.post);
});

await beat('post_extend', async () => {
  await caption(
    'Extend and edit',
    'Sequel or prequel with an overlap; a labelled region with a bounding box. Both validated, both reported.',
  );
  await evaluate(`(() => {
    const on = document.getElementById('p-extend-on'); if (on && !on.checked) on.click();
    const ed = document.getElementById('p-edit-on'); if (ed && !ed.checked) ed.click();
    return true;
  })()`);
  await sleep(600);
  await snapshot(LABEL.post_extend);
});

// ===========================================================================
// 6. RUN — the load-bearing honesty moment
// ===========================================================================
await beat('run_check', async () => {
  await tab('run');
  await caption(
    'Run — it really sends, and it really reads back',
    'A real POST to a live ComfyUI, a real poll of /history, and the engine\'s own returned text rendered on screen.',
  );
  await evaluate('document.getElementById("r-check").click(), true');
  await sleep(2500);
  await snapshot(LABEL.run_check);
});

await beat('run_honesty', async () => {
  await caption(
    'A run returns text, not pixels',
    'The pack ships no IMAGE node, so CinemaGradeApply has nothing to consume. The graph ends in PreviewAny taps — that is what makes it runnable at all.',
  );
  await evaluate('document.getElementById("r-run").click(), true');
  await waitFor(
    `(() => { const s = document.getElementById('r-run-status').textContent;
       return /taps returned output|it failed|Nothing was sent|does not know|threw|No ComfyUI|partial/.test(s); })()`,
    'the run to settle',
    180000,
  );
  await sleep(800);
  await snapshot(LABEL.run_honesty);
});

// ===========================================================================
// 7. JUDGE — the differentiator, and the 30-second proof path
// ===========================================================================
await beat('judge', async () => {
  await tab('judge', 1000);
  await caption(
    'Judge — move the camera, watch the arithmetic',
    'The same nine rules, recomputed live as the camera moves. Every number is computed, never hardcoded.',
  );
  await snapshot(LABEL.judge);
});

await beat('judge_drag', async () => {
  await caption(
    'Drag the distance',
    'The measurements move with the camera. This is the 30-second proof: the numbers are real.',
  );
  await dragSlider('in-dist', 3.2, 2.91, 3.0);
  await snapshot(LABEL.judge_drag);
});

await beat('judge_autoframe', async () => {
  await caption(
    'Auto-Frame',
    'The solver moves the camera for you, and reports honestly whether it converged.',
  );
  await evaluate('document.getElementById("autoframe").click(), true');
  await sleep(1200);
  await snapshot(LABEL.judge_autoframe);
});

// ===========================================================================
// 8. THE RENDER — a separate artifact, from a separate graph
// ===========================================================================
await beat('render', async () => {
  await caption(
    'The render',
    'reshoot_ltx25.mp4 — 121 frames at 24 fps, 1920×1088, from the LTX 2.5 path on Comfy Cloud. Its AAC track is present but silent.',
  );
  await evaluate(`(() => {
    const style = document.createElement('style');
    style.textContent = \`
      #__render {
        position: fixed; inset: 0; z-index: 99998; background: #04070c;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; color: #e8eef7;
      }
      #__render video { width: 100%; height: 100%; object-fit: contain; }
      #__render .r-note {
        position: absolute; left: 0; right: 0; bottom: 0; padding: 16px 40px 18px;
        background: linear-gradient(to top, rgba(4,7,12,0.97), rgba(4,7,12,0));
        font-size: 19px; color: #9fb3c8; line-height: 1.35;
      }
    \`;
    document.head.appendChild(style);
    const d = document.createElement('div');
    d.id = '__render';
    d.innerHTML = '<video id="__rv" playsinline></video>'
      + '<div class="r-note">Rendered on Comfy Cloud by <code>workflows/reshoot_ltx25.json</code> — the LTX 2.5 model path, not our nodes. Our nodes are not on Comfy Cloud.</div>';
    document.body.appendChild(d);
    const v = document.getElementById('__rv');
    v.src = window.__renderUrl;
    v.muted = false; v.volume = 1.0;
    v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
    return true;
  })()`);
  await sleep(1000);
  await snapshot(LABEL.render);
});

await beat('render_caveat', async () => {
  await caption(
    'What the render proves, and what it does not',
    'It proves the LTX 2.5 path renders video. It does not prove our nodes render: they are structurally validated, and locally unexecuted.',
  );
  await snapshot(LABEL.render_caveat);
});

// ===========================================================================
// 9. END CARD — the disclosures
// ===========================================================================
await beat('endcard', async () => {
  await evaluate(`(() => {
    const r = document.getElementById('__render'); if (r) r.remove();
    const c = document.getElementById('__cap'); if (c) c.remove();
    const style = document.createElement('style');
    style.textContent = \`
      #endcard {
        position: fixed; inset: 0; z-index: 99999;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 12px; padding: 44px; text-align: center;
        background: radial-gradient(ellipse at 50% 40%, #101826 0%, #070a0f 70%);
        font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
        color: #e8eef7;
      }
      #endcard .ec-title { font-size: 44px; font-weight: 700; letter-spacing: -0.5px; }
      #endcard .ec-url { font-size: 19px; color: #7fb2e5; font-family: ui-monospace, Menlo, monospace; }
      #endcard .ec-stack { font-size: 22px; color: #9fe8c4; margin-top: 8px; }
      #endcard .ec-lic { font-size: 17px; color: #8b9bb0; }
      #endcard .ec-credit {
        font-size: 14px; color: #6b7c93; max-width: 1180px; line-height: 1.55;
        margin-top: 14px; padding-top: 14px; border-top: 1px solid #1e2836;
      }
      #endcard .ec-note { font-size: 14px; color: #c9a227; max-width: 1180px; line-height: 1.55; }
    \`;
    document.head.appendChild(style);
    const card = document.createElement('div');
    card.id = 'endcard';
    card.innerHTML = \`
      <div class="ec-title">ComfyUI-Cinematographer</div>
      <div class="ec-url">github.com/nathaniel-magieva/ComfyUI-Cinematographer</div>
      <div class="ec-stack">LTX 2.5 · CrossView-Warp · MoGe-2 · ComfyUI — no MiniMax H3</div>
      <div class="ec-lic">Apache-2.0 · #OpenSourceHiggsfield</div>
      <div class="ec-credit">Third-party tools: ComfyUI · LTX-Video 2.5 (Lightricks) · CrossView-Warp IC-LoRA (Cseti) · MoGe-2. The entry deliberately uses no MiniMax H3.</div>
      <div class="ec-note">The Cloud render came from the LTX 2.5 model path, not from our nodes. Our nodes are not on Comfy Cloud: they are structurally validated and locally unexecuted, except that cinema_studio_full.json runs 25 of 94 nodes locally. The other reshoot_* graphs have never been executed.</div>
    \`;
    document.body.appendChild(card);
    return true;
  })()`);
  await sleep(600);
  await snapshot(LABEL.endcard);
});

await stopCast();

// ---------------------------------------------------------------------------
// Write the frames out
// ---------------------------------------------------------------------------

console.log(`\n${screencastFrames.length} screencast frames captured`);

const base = screencastFrames[0]?.t ?? Date.now();
const manifest = screencastFrames.map((f, i) => {
  const name = `f_${String(i).padStart(5, '0')}.jpg`;
  writeFileSync(join(RAW, name), Buffer.from(f.data, 'base64'));
  return { name, t: (f.t - base) / 1000 };
});

writeFileSync(join(OUT, 'frames.json'), JSON.stringify(manifest, null, 1));
writeFileSync(join(OUT, 'beats.json'), JSON.stringify(beats, null, 1));

const span = manifest.length ? manifest[manifest.length - 1].t : 0;
console.log(`  span      : ${span.toFixed(2)}s`);
console.log(`  mean rate : ${(manifest.length / Math.max(span, 0.001)).toFixed(1)} fps`);
console.log(`  frames    : ${RAW}`);
console.log(`  beats     : ${join(OUT, 'beats.json')}`);

ws.close();
chrome.kill();
process.exit(0);
