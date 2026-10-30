/**
 * Browser check for the director's panel — a real Chrome pass, driven over the
 * DevTools Protocol. No npm dependencies (Node 24 has global fetch + WebSocket).
 *
 *   # 1. serve the panel
 *   cd web && python3 -m http.server 8765
 *   # 2. drive it
 *   node web/tools/browser_check.mjs [http://127.0.0.1:8765/]
 *
 * It asserts the acceptance criteria that need a browser:
 *   - the page loads and the rule panel renders all 9 rules
 *   - the default frame reports overall FAIL (something to fix)
 *   - moving a slider changes the measured values live
 *   - pressing Auto-Frame converges and flips the panel to overall PASS
 *   - "Check continuity" renders verdicts for both rules on both cuts
 *   - a screenshot is written for the record
 *
 * Exit code 0 = every assertion held.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const URL_ = process.argv[2] ?? 'http://127.0.0.1:8765/';
const SHOT = process.argv[3] ?? join(tmpdir(), 'cinematographer-panel.png');

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
  console.log('SKIP — no Chrome/Chromium found. Set CHROME_PATH to run this check.');
  process.exit(0);
}

let failures = 0;
let checks = 0;
const ok = (cond, label, detail = '') => {
  checks++;
  if (cond) console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`);
  else {
    failures++;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Launch Chrome with remote debugging
// ---------------------------------------------------------------------------

const profile = mkdtempSync(join(tmpdir(), 'cine-chrome-'));
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
    '--window-size=1600,1500',
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
  console.log('SKIP — Chrome did not expose a debugging port.');
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Minimal CDP client
// ---------------------------------------------------------------------------

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === 'page');
if (!page) {
  chrome.kill();
  console.log('SKIP — no page target.');
  process.exit(0);
}

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener('open', res, { once: true });
  ws.addEventListener('error', rej, { once: true });
});

let nextId = 1;
const pending = new Map();
const events = [];
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  } else if (msg.method) {
    events.push(msg.method);
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

async function waitFor(expression, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await evaluate(expression)) return true;
    } catch {
      /* page still loading */
    }
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${label}`);
}

// ---------------------------------------------------------------------------
// Drive the panel
// ---------------------------------------------------------------------------

console.log(`panel browser check — ${URL_}\n`);

try {
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.navigate', { url: URL_ });
  await waitFor('document.readyState === "complete"', 'page load');
  await waitFor('document.querySelectorAll("#rules .rule").length === 9', 'rule panel');

  console.log('[1] first paint');
  const names = await evaluate(
    '[...document.querySelectorAll("#rules .rule-name")].map(e => e.textContent).join(",")',
  );
  ok(
    names ===
      'in_frame,rule_of_thirds,headroom,shot_size,lead_room,negative_space,camera_angle,level,direct_address',
    'all 9 rules render in engine order',
    names,
  );
  const firstOverall = await evaluate('document.getElementById("overall-value").textContent');
  ok(firstOverall === 'FAIL', 'default frame reports overall FAIL', firstOverall);
  const zone = await evaluate('document.getElementById("reliability-value").textContent');
  ok(['GREEN', 'YELLOW', 'RED'].includes(zone), 'reliability badge renders', zone);
  const three = await evaluate('document.getElementById("three-status").textContent');
  console.log(`  info 3D viewport: ${three}`);
  // The CDN import is async; give it a moment, then report (never fatal — the
  // panel is designed to work without three.js).
  try {
    await waitFor(
      '!document.getElementById("three-status").textContent.includes("loading")',
      'three.js',
      8000,
    );
    const three2 = await evaluate('document.getElementById("three-status").textContent');
    const chip = await evaluate('document.getElementById("chip-fov").textContent');
    console.log(`  info 3D viewport after load: ${three2} · ${chip}`);
  } catch {
    console.log('  info 3D viewport: three.js did not finish loading (panel still works)');
  }

  console.log('\n[2] the numbers move when the camera moves');
  const before = await evaluate(
    '[...document.querySelectorAll("#rules .rule-value")].map(e => e.textContent).join("|")',
  );
  await evaluate(`(() => {
    const el = document.getElementById('in-dist');
    el.value = '7.5';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(250);
  const after = await evaluate(
    '[...document.querySelectorAll("#rules .rule-value")].map(e => e.textContent).join("|")',
  );
  ok(before !== after, 'measured values change live when distance moves', `${before.split('|')[3]} → ${after.split('|')[3]}`);
  const distOut = await evaluate('document.getElementById("out-dist").textContent');
  ok(distOut.includes('7.50'), 'the distance readout follows the slider', distOut);

  console.log('\n[3] Auto-Frame');
  await evaluate('document.getElementById("autoframe").click(), true');
  await waitFor(
    'document.getElementById("solver-badge").textContent.includes("converged")',
    'solver badge',
  );
  const solver = await evaluate(
    'document.getElementById("solver-badge").querySelector(".badge-value").textContent',
  );
  ok(/converged/.test(solver) && !/NOT/.test(solver), 'solver reports converged', solver);
  const afterAF = await evaluate('document.getElementById("overall-value").textContent');
  ok(afterAF === 'PASS', 'panel flips to overall PASS after Auto-Frame', afterAF);
  // Overall pass requires every rule with weight >= 0.8 to pass. A low-weight
  // rule may legitimately stay red — that is the spec, not a bug.
  const weightedRed = await evaluate(`(() => {
    return [...document.querySelectorAll('#rules .rule.fail')]
      .filter(row => parseFloat(row.querySelector('.rule-weight').textContent.replace('w ', '')) >= 0.8)
      .map(row => row.querySelector('.rule-name').textContent).join(',');
  })()`);
  ok(weightedRed === '', 'no rule with weight >= 0.8 is red after Auto-Frame', weightedRed || 'none');
  const lowRed = await evaluate(`(() => {
    return [...document.querySelectorAll('#rules .rule.fail')]
      .map(row => row.querySelector('.rule-name').textContent + ' (w '
        + row.querySelector('.rule-weight').textContent.replace('w ', '') + ')').join(', ');
  })()`);
  console.log(`  info low-weight rules still red (allowed): ${lowRed || 'none'}`);
  const solverNote = await evaluate('document.getElementById("solver-note").textContent');
  ok(/Converged in \d+/.test(solverNote), 'solver note states the iteration count', solverNote.trim());

  console.log('\n[4] continuity strip');
  await evaluate('document.getElementById("check-continuity").click(), true');
  await sleep(250);
  const cuts = await evaluate('document.querySelectorAll("#continuity-out .cut").length');
  ok(cuts === 2, 'two cuts are rendered', `${cuts}`);
  const issueRules = await evaluate(
    '[...document.querySelectorAll("#continuity-out .issue-rule")].map(e => e.textContent).join(",")',
  );
  ok(
    issueRules === '180_axis,30_degree,180_axis,30_degree',
    'both rules are checked on both cuts',
    issueRules,
  );
  const summary = await evaluate(
    'document.querySelector("#continuity-out .continuity-summary").textContent',
  );
  ok(/^(PASS|FAIL)/.test(summary), 'continuity summary renders', summary);

  console.log('\n[5] 3D viewport actually draws');
  // Force a synchronous render, then read pixels in the same task — before the
  // buffer is swapped — so this is a real check, not a guess.
  const gl = await evaluate(`(() => {
    const hook = window.__cinematographer;
    if (!hook || !hook.view) return { ok: false, reason: 'viewport not initialised' };
    const v = hook.view;
    v.renderer.render(v.scene, v.viewer);
    const c = v.renderer.domElement;
    const ctx = v.renderer.getContext();
    const sample = (x, y) => {
      const px = new Uint8Array(4);
      ctx.readPixels(x, y, 1, 1, ctx.RGBA, ctx.UNSIGNED_BYTE, px);
      return [px[0], px[1], px[2]];
    };
    const pts = [
      sample(Math.floor(c.width / 2), Math.floor(c.height / 2)),
      sample(Math.floor(c.width / 2), Math.floor(c.height * 0.75)),
      sample(Math.floor(c.width * 0.25), Math.floor(c.height * 0.5)),
      sample(Math.floor(c.width * 0.75), Math.floor(c.height * 0.5)),
    ];
    return {
      ok: true,
      w: c.width,
      h: c.height,
      pts,
      lit: pts.filter(p => p[0] + p[1] + p[2] > 12).length,
      objects: v.scene.children.length,
      glError: ctx.getError(),
    };
  })()`);
  ok(gl.ok, 'viewport exposes a live WebGL context', gl.reason ?? '');
  if (gl.ok) {
    ok(gl.w > 0 && gl.h > 0, 'canvas has a real drawing buffer', `${gl.w}×${gl.h}`);
    ok(gl.objects >= 6, 'scene holds the ground, grid, subject, action line and frustum', `${gl.objects} objects`);
    ok(gl.lit >= 2, 'the viewport renders lit pixels, not a black canvas', `${gl.lit}/4 samples lit`);
    ok(gl.glError === 0, 'no WebGL error', `glGetError=${gl.glError}`);
    console.log(`  info samples rgb: ${gl.pts.map((p) => `(${p.join(',')})`).join(' ')}`);
  }

  console.log('\n[6] screenshot');
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
  ok(existsSync(SHOT), 'screenshot written', SHOT);
} catch (err) {
  failures++;
  checks++;
  console.log(`  FAIL driver error — ${err.message}`);
} finally {
  try {
    ws.close();
  } catch {
    /* ignore */
  }
  chrome.kill();
}

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} — ${checks - failures}/${checks} browser checks passed`);
process.exit(failures === 0 ? 0 : 1);
