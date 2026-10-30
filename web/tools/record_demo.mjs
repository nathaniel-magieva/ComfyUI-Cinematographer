/**
 * Records the submission demo video from the real panel.
 *
 *   # 1. serve the panel
 *   cd app/web && python3 -m http.server 8765
 *   # 2. record
 *   node app/web/tools/record_demo.mjs
 *
 * Chrome launch flags and the CDP client are lifted verbatim from
 * `browser_check.mjs` — those flags are what make three.js render headless, so
 * they are not to be "improved".
 *
 * Motion comes from `Page.startScreencast`, not from per-beat screenshots: the
 * compositor pushes a frame whenever the page repaints, so a slider drag is
 * recorded as a drag rather than as two stills.
 *
 * Every number that appears on screen is read back out of the live panel and
 * written to `beats.json`. Nothing is retyped from the script.
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
const REPO = resolve(WEB, '..', '..');
const OUT = resolve(REPO, 'video');
const RAW = join(OUT, 'raw');

const URL_ = process.argv[2] ?? 'http://127.0.0.1:8765/';

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

const profile = mkdtempSync(join(tmpdir(), 'cine-rec-'));
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

/** Read the live panel state into a beat record. */
async function snapshot(label) {
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
    return {
      overall: document.getElementById('overall-value')?.textContent.trim(),
      reliability: document.getElementById('reliability-value')?.textContent.trim(),
      solver: document.getElementById('solver-badge')?.textContent.trim(),
      solverNote: document.getElementById('solver-note')?.textContent.trim(),
      rules,
      continuity: document.getElementById('continuity-out')?.innerText.trim() ?? '',
      tab: document.querySelector('.tab.on')?.textContent.trim(),
    };
  })()`);
  const beat = { label, t: +now().toFixed(2), ...data };
  beats.push(beat);
  const hr = data.rules.find((r) => r.name === 'headroom');
  console.log(
    `  [${beat.t.toFixed(1).padStart(6)}s] ${label.padEnd(26)} ` +
      `overall=${data.overall} headroom=${hr ? `${hr.value} ${hr.verdict}` : '—'}`,
  );
  return beat;
}

// ---------------------------------------------------------------------------
// The shot list
// ---------------------------------------------------------------------------

console.log('Recording…\n');
await startCast();

// --- Beat 1: the problem. A frame that fails, and the lever that fixes it. ---
// Timed against the narration: L1 runs 0.0-21.2s (the problem), L2 runs
// 21.2-38.3s (the proof). The headroom FAIL -> PASS transition must land inside
// L2, so the opening hold and the orbit drag are sized to fill L1.
await evaluate('window.__cinematographer.showTab("judge"), true');
await sleep(400);
await snapshot('open — default frame');
await hold(6.0);

// Drag the camera so the numbers move, then settle on the failing frame.
await dragSlider('in-az', 12, -34, 6.0);
await snapshot('orbit — numbers move live');
await hold(4.0);

// The headroom FAIL state, reached by pushing in (distance 3.2 -> 2.91).
await dragSlider('in-dist', 3.2, 2.91, 3.0);
const failBeat = await snapshot('headroom FAIL');
await hold(3.0);

// --- Beat 2: the fix. Push in, and it passes. ------------------------------
await dragSlider('in-dist', 2.91, 0.8, 4.0);
const passBeat = await snapshot('push in — headroom PASS');
await hold(4.0);

// --- Beat 3: Auto-Frame, converged. ----------------------------------------
await evaluate('document.getElementById("reset").click(), true');
await sleep(500);
await snapshot('reset');
await evaluate('document.getElementById("autoframe").click(), true');
await sleep(900);
const convBeat = await snapshot('Auto-Frame CONVERGED');
await hold(6.0);

// --- Beat 4: the honest bit. The recipe that does NOT converge. ------------
await evaluate('document.getElementById("reset").click(), true');
await sleep(400);
await dragSlider('in-sheight', 1.75, 1.2, 1.6);
await evaluate(`(() => {
  document.querySelector('#seg-shot button[data-value="closeup"]').click();
  document.querySelector('#seg-angle button[data-value="high"]').click();
  return true;
})()`);
await sleep(400);
await evaluate('document.getElementById("autoframe").click(), true');
await sleep(1000);
const notConvBeat = await snapshot('Auto-Frame NOT CONVERGED');
await hold(6.0);

// --- Beat 5: continuity. ---------------------------------------------------
await evaluate('document.getElementById("reset").click(), true');
await sleep(400);
await evaluate('document.getElementById("check-continuity").click(), true');
await sleep(700);
const contBeat = await snapshot('continuity');
await hold(6.0);

// --- Beat 6: the Director tab. ---------------------------------------------
await evaluate('window.__cinematographer.showTab("director"), true');
await sleep(600);
await evaluate(`(() => {
  const ta = document.getElementById('d-prompt');
  ta.value = 'A detective crosses the diner, @tamsincamp waits, @nobody watches, #dolly-in then #dollyin';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
})()`);
await sleep(500);
await snapshot('director — prompt tags resolve');
await hold(3.0);

await evaluate(`(() => {
  const sel = document.getElementById('d-move-add');
  sel.value = 'dolly-in';
  document.getElementById('d-move-add-btn').click();
  return true;
})()`);
await sleep(300);
await evaluate(`(() => {
  const sel = document.getElementById('d-move-add');
  sel.value = 'crane-up';
  document.getElementById('d-move-add-btn').click();
  return true;
})()`);
await sleep(300);
await dragSlider('d-duration', 5, 30, 2.4);
const dirBeat = await snapshot('director — move stack + cost');
await hold(4.0);

// --- Beat 7: the end card. -------------------------------------------------
await evaluate(`(() => {
  const style = document.createElement('style');
  style.textContent = \`
    #endcard {
      position: fixed; inset: 0; z-index: 9999;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 14px; padding: 48px; text-align: center;
      background: radial-gradient(ellipse at 50% 40%, #101826 0%, #070a0f 70%);
      font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
      color: #e8eef7;
    }
    #endcard .ec-title { font-size: 46px; font-weight: 700; letter-spacing: -0.5px; }
    #endcard .ec-url { font-size: 20px; color: #7fb2e5; font-family: ui-monospace, Menlo, monospace; }
    #endcard .ec-stack { font-size: 24px; color: #9fe8c4; margin-top: 10px; }
    #endcard .ec-lic { font-size: 18px; color: #8b9bb0; }
    #endcard .ec-credit {
      font-size: 14px; color: #6b7c93; max-width: 1100px; line-height: 1.6;
      margin-top: 18px; padding-top: 18px; border-top: 1px solid #1e2836;
    }
    #endcard .ec-note { font-size: 14px; color: #c9a227; max-width: 1000px; line-height: 1.6; }
  \`;
  document.head.appendChild(style);
  const card = document.createElement('div');
  card.id = 'endcard';
  card.innerHTML = \`
    <div class="ec-title">ComfyUI-Cinematographer</div>
    <div class="ec-url">github.com/nathaniel-magieva/ComfyUI-Cinematographer</div>
    <div class="ec-stack">LTX 2.5 · LTX 2.3 · CrossView-Warp · MoGe-2 — no MiniMax H3</div>
    <div class="ec-lic">Apache-2.0 · #OpenSourceHiggsfield</div>
    <div class="ec-credit">Built on ComfyUI · LTX-Video (Lightricks) · CrossView-Warp IC-LoRA (Cseti) · MoGe-2 · FLUX.1 [schnell] (BFL) · Wan 2.2 (Alibaba)</div>
    <div class="ec-note">The graphs are structurally validated and have never been executed. No model was called for this video.</div>
  \`;
  document.body.appendChild(card);
  return true;
})()`);
await sleep(500);
await snapshot('end card');
await hold(8.0);

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
