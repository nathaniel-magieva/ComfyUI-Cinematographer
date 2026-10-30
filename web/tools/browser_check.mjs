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
 *   - the Run tab exports a real API prompt, and — when a ComfyUI is listening
 *     on 127.0.0.1:8188 — POSTs it, polls /history and renders what came back
 *   - a screenshot is written for the record
 *
 * The live half of the Run checks is skipped, with a stated reason, when no
 * ComfyUI answers. The exported prompt JSON is checked either way, because it
 * needs no server.
 *
 * Exit code 0 = every assertion held.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// The panel's own ComfyUI client, imported rather than re-implemented: the
// Stage 6 checks must exercise the module the page actually runs. Node 24
// detects the ESM syntax in the `.js` file, so no package.json is needed.
import * as CC from '../comfy_client.js';

const URL_ = process.argv[2] ?? 'http://127.0.0.1:8765/';
const SHOT = process.argv[3] ?? join(tmpdir(), 'cinematographer-panel.png');

/** Where the live ComfyUI is expected. Overridable for a non-default port. */
const COMFY = process.env.CINE_COMFY_URL ?? CC.DEFAULT_BASE_URL;

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
  await waitFor('document.querySelectorAll("#d-move-add option").length > 0', 'director controls');

  // ===================== DIRECTOR TAB (the default) =====================
  console.log('[D1] the Studio tab is the default — it is the front door');
  const tabState = await evaluate(`(() => ({
    studioHidden: document.getElementById('tab-studio').classList.contains('hidden'),
    directorHidden: document.getElementById('tab-director').classList.contains('hidden'),
    judgeHidden: document.getElementById('tab-judge').classList.contains('hidden'),
    onTab: document.querySelector('#tabnav .tab.on')?.dataset.tab,
    note: document.getElementById('tabnav-note').textContent.trim(),
    order: [...document.querySelectorAll('#tabnav .tab')].map((b) => b.dataset.tab),
  }))()`);
  ok(!tabState.studioHidden, 'the Studio tab is visible on load');
  ok(tabState.directorHidden, 'the Director tab starts hidden');
  ok(tabState.judgeHidden, 'the Judge tab starts hidden');
  ok(tabState.onTab === 'studio', 'the Studio tab button is selected', tabState.onTab);
  ok(
    tabState.order[0] === 'studio'
      && JSON.stringify(tabState.order.slice(1))
        === JSON.stringify(['director', 'judge', 'elements', 'shoot', 'post', 'run']),
    'Studio is first and the other six keep their relative order',
    tabState.order.join(' → '),
  );
  ok(
    /one screen.*measured framing verdict/.test(tabState.note),
    'the tab bar explains the landing tab',
    tabState.note,
  );

  // Everything below this line was written against the Director tab being the
  // landing tab. Reveal it explicitly rather than relying on the default.
  await evaluate(`window.__cinematographer.showTab('director')`);
  await waitFor(
    `!document.getElementById('tab-director').classList.contains('hidden')`,
    'the Director tab to be shown',
  );

  const panelErrors = await evaluate('JSON.stringify(window.__panelErrors || [])');
  ok(panelErrors === '[]', 'the page booted with no JS errors', panelErrors);

  console.log('\n[D2] every dropdown is populated from the engine constants');
  const enumMismatch = await evaluate(`(() => {
    const D = window.__cinematographer.director;
    const pairs = [
      ['d-genre','genre'], ['d-era','era'], ['d-pacing','pacing'],
      ['d-model','camera_model'], ['d-lens','camera_lens'], ['d-aperture','camera_aperture'],
      ['d-light','light'], ['d-palette','color_palette'],
      ['d-resolution','resolution'], ['d-aspect','aspect_ratio'],
      ['d-emo-emotion','emotion'],
    ];
    const bad = [];
    for (const [id, key] of pairs) {
      const sel = document.getElementById(id);
      if (!sel) { bad.push(id + ': missing'); continue; }
      const got = [...sel.options].map(o => o.value).filter(v => v !== 'auto');
      const want = D.ENUMS[key];
      if (got.join('|') !== want.join('|')) {
        bad.push(id + ': got ' + got.length + ' want ' + want.length);
      }
    }
    // The move picker is grouped into families for usability, so its DOM order is
    // the group order. Compare it as a set: same members, no drift, no extras.
    const mv = [...document.querySelectorAll('#d-move-add option')].map(o => o.value);
    const mvSet = [...mv].sort().join('|');
    const wantSet = [...D.CAMERA_MOVEMENT].sort().join('|');
    if (mvSet !== wantSet) {
      bad.push('d-move-add: got ' + mv.length + ' want ' + D.CAMERA_MOVEMENT.length +
        (mv.length === D.CAMERA_MOVEMENT.length ? ' (same size, different members)' : ''));
    }
    return bad;
  })()`);
  ok(enumMismatch.length === 0, 'all 13 selects match the engine enums exactly', enumMismatch.join('; ') || 'no drift');
  const enumCounts = await evaluate(`(() => {
    const D = window.__cinematographer.director;
    return Object.entries(D.ENUMS).map(([k, v]) => k + '=' + v.length).join(' ');
  })()`);
  console.log(`  info enum sizes: ${enumCounts}`);

  console.log('\n[D3] the move stack is ordered and reorderable');
  await evaluate(`(() => {
    const add = (slug) => {
      const sel = document.getElementById('d-move-add');
      sel.value = slug;
      document.getElementById('d-move-add-btn').click();
    };
    add('dolly-in'); add('crane-up'); add('pan-left');
    return true;
  })()`);
  await sleep(200);
  const stackBefore = await evaluate(
    '[...document.querySelectorAll("#d-move-stack .mv-tag")].map(e => e.textContent).join(",")',
  );
  ok(stackBefore === '#dolly-in,#crane-up,#pan-left', 'three moves stack in the order added', stackBefore);
  await evaluate(`(() => {
    const rows = document.querySelectorAll('#d-move-stack .move-row');
    rows[0].querySelectorAll('button')[1].click();  // the "move later" button
    return true;
  })()`);
  await sleep(200);
  const stackAfter = await evaluate(
    '[...document.querySelectorAll("#d-move-stack .mv-tag")].map(e => e.textContent).join(",")',
  );
  ok(stackAfter === '#crane-up,#dolly-in,#pan-left', 'reordering the stack changes the run order', stackAfter);
  const promptMoves = await evaluate('document.getElementById("d-prompt-out").textContent');
  ok(
    promptMoves.includes('#crane-up #dolly-in #pan-left'),
    'the composed prompt carries the moves in stack order',
    promptMoves.trim().slice(-40),
  );

  console.log('\n[D4] @Element and #move resolve live');
  await evaluate(`(() => {
    const ta = document.getElementById('d-prompt');
    ta.value = 'A detective crosses the diner, @tamsincamp waits, @nobody watches, #dolly-in then #dollyin';
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(250);
  const chips = await evaluate(`(() => {
    const all = [...document.querySelectorAll('#d-tags .tag-chip')];
    return {
      total: all.length,
      ok: all.filter(c => c.classList.contains('ok')).length,
      bad: all.filter(c => c.classList.contains('bad')).length,
      badText: all.filter(c => c.classList.contains('bad')).map(c => c.textContent.trim()).join(' | '),
    };
  })()`);
  ok(chips.total === 4, 'four tags are recognised', `${chips.total}`);
  ok(chips.ok === 2, 'the two valid tags resolve', `${chips.ok} resolved`);
  ok(chips.bad === 2, 'the two invalid tags are flagged red', chips.badText);
  const composed = await evaluate('document.getElementById("d-prompt-out").textContent');
  ok(
    composed.includes('<<<image_1>>>'),
    '@Element is translated to the API reference token',
    composed.trim().slice(0, 60),
  );
  const attachments = await evaluate(
    '[...document.querySelectorAll("#d-attachments .attach-item")].map(e => e.textContent).join(" | ")',
  );
  ok(/tamsincamp/.test(attachments), 'the attachment list names the resolved Element', attachments);

  console.log('\n[D5] the cost readout follows duration and resolution');
  const costAt = async (duration, resolution) => {
    await evaluate(`(() => {
      const d = document.getElementById('d-duration');
      d.value = '${duration}';
      d.dispatchEvent(new Event('input', { bubbles: true }));
      const r = document.getElementById('d-resolution');
      r.value = '${resolution}';
      r.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    await sleep(180);
    return evaluate('document.getElementById("d-cost").textContent.replace(/\\s+/g, " ").trim()');
  };
  const c10_720 = await costAt(10, '720p');
  ok(c10_720 === '✦ 70', '10 s at 720p costs 70 credits (published cell)', c10_720);
  await costAt(30, '1080p');
  const c30_1080 = await evaluate(`(() => {
    const el = document.getElementById('d-cost');
    return {
      text: el.textContent.replace(/\\s+/g, ' ').trim(),
      was: el.querySelector('.was') ? el.querySelector('.was').textContent.trim() : null,
    };
  })()`);
  ok(
    c30_1080.was === '✦ 480' && c30_1080.text.includes('✦ 360'),
    '30 s at 1080p shows 480 struck and 360 discounted',
    `was=${c30_1080.was} now=${c30_1080.text}`,
  );
  const c4_480 = await costAt(4, '480p');
  ok(c4_480 === '✦ 12', '4 s at 480p costs 12 credits (3 credits/s)', c4_480);
  const c15_720 = await costAt(15, '720p');
  ok(c15_720 === '✦ 105', '15 s at 720p costs 105 credits (published cell)', c15_720);
  const genDisabled = await evaluate('document.getElementById("d-generate").disabled');
  ok(genDisabled === true, 'the Generate button is disabled — the panel composes, it does not send');

  console.log('\n[D5b] focal length — the control 4.0 dropped and this engine kept');
  const focalMeta = await evaluate(`(() => {
    const D = window.__cinematographer.director;
    const f = document.getElementById('d-focal');
    return {
      dropped: D.FOCAL_LENGTH_DROPPED_IN_4_0,
      min: f.min, max: f.max, value: f.value,
      wantMin: String(D.FOCAL_MIN), wantMax: String(D.FOCAL_MAX),
      inApiFields: Object.values(D.API_FIELDS).includes('focal_mm'),
    };
  })()`);
  ok(focalMeta.dropped === true, 'the engine records that 4.0 dropped focal length');
  ok(
    focalMeta.min === focalMeta.wantMin && focalMeta.max === focalMeta.wantMax,
    'the focal slider spans the engine range',
    `${focalMeta.min}–${focalMeta.max} mm`,
  );
  ok(!focalMeta.inApiFields, 'focal_mm is not claimed as an API field');
  await evaluate(`(() => {
    const f = document.getElementById('d-focal');
    f.value = '85';
    f.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(200);
  const focalPlan = await evaluate(`(() => ({
    ext: document.getElementById('d-extensions').textContent,
    params: document.getElementById('d-params').textContent,
    out: document.getElementById('d-focal-out').textContent,
  }))()`);
  ok(focalPlan.out === '85 mm', 'the focal readout follows the slider', focalPlan.out);
  ok(/"focal_mm": 85/.test(focalPlan.ext), 'focal length lands in the engine-extension block', focalPlan.ext.split('\n')[1]);
  ok(!/focal_mm/.test(focalPlan.params), 'focal length is NOT in the API parameter block');

  console.log('\n[D5c] emotion wheel — 9 names, continuous intensity');
  const emo = await evaluate(`(() => {
    const D = window.__cinematographer.director;
    const sel = document.getElementById('d-emo-emotion');
    const it = document.getElementById('d-emo-intensity');
    return {
      names: [...sel.options].map(o => o.value).join('|'),
      want: D.EMOTION.join('|'),
      sliderType: it.type, min: it.min, max: it.max,
      isEnum: 'emotion_intensity' in D.ENUMS,
    };
  })()`);
  ok(emo.names === emo.want, 'the emotion wheel lists all 9 names from the engine', `${emo.names.split('|').length} names`);
  ok(
    emo.sliderType === 'range' && emo.min === '0' && emo.max === '1',
    'intensity is a continuous 0..1 slider, not an invented enum',
    `${emo.sliderType} ${emo.min}–${emo.max}`,
  );
  ok(!emo.isEnum, 'intensity is not exposed as an enum');
  await evaluate(`(() => {
    const it = document.getElementById('d-emo-intensity');
    it.value = '1';
    it.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('d-emo-add').click();
    return true;
  })()`);
  await sleep(200);
  const emoRow = await evaluate(
    'document.querySelector("#d-emo-list .mv-name")?.textContent.trim() ?? ""',
  );
  ok(/intense/.test(emoRow) && /1\.00/.test(emoRow), 'an emotion row records the intensity', emoRow);

  console.log('\n[D6] Director tab screenshot');
  const shotD = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  const SHOT_DIRECTOR = SHOT.replace(/\.png$/, '-director.png');
  writeFileSync(SHOT_DIRECTOR, Buffer.from(shotD.data, 'base64'));
  ok(existsSync(SHOT_DIRECTOR), 'Director tab screenshot written', SHOT_DIRECTOR);

  // ===================== JUDGE TAB (unchanged) =====================
  console.log('\n[J0] switching to the Judge tab');
  await evaluate(`document.querySelector('#tabnav [data-tab="judge"]').click(), true`);
  await sleep(400);
  const judgeVisible = await evaluate(`(() => ({
    judgeHidden: document.getElementById('tab-judge').classList.contains('hidden'),
    directorHidden: document.getElementById('tab-director').classList.contains('hidden'),
  }))()`);
  ok(!judgeVisible.judgeHidden, 'the Judge tab becomes visible');
  ok(judgeVisible.directorHidden, 'the Director tab hides');

  console.log('\n[1] first paint');
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

  // ========== ELEMENTS TAB (Stage 1 BUILD + Stage 2 ATTACH) ==========
  console.log('\n[E1] Elements tab — the registry and the engine\'s categories');
  await evaluate(`document.querySelector('#tabnav [data-tab="elements"]').click(), true`);
  await sleep(300);
  const elTab = await evaluate(`(() => ({
    visible: !document.getElementById('tab-elements').classList.contains('hidden'),
    judgeHidden: document.getElementById('tab-judge').classList.contains('hidden'),
    onTab: document.querySelector('#tabnav .tab.on')?.dataset.tab,
    note: document.getElementById('tabnav-note').textContent.trim(),
    categories: [...document.getElementById('e-category').options].map(o => o.value),
    engineCategories: window.__cinematographer.studio.ELEMENT_CATEGORIES,
    rows: document.querySelectorAll('#e-registry .registry-item').length,
    count: document.getElementById('e-count').textContent.trim(),
  }))()`);
  ok(elTab.visible, 'the Elements tab becomes visible');
  ok(elTab.judgeHidden, 'the Judge tab hides');
  ok(elTab.onTab === 'elements', 'the Elements tab button is selected', elTab.onTab);
  ok(/writes no file/.test(elTab.note), 'the tab bar says the Elements tab writes no file', elTab.note);
  ok(
    elTab.categories.join('|') === elTab.engineCategories.join('|'),
    "the category list is the engine's ELEMENT_CATEGORIES",
    elTab.categories.join(','),
  );
  ok(elTab.rows === 3, 'the demo registry renders 3 Elements', String(elTab.rows));
  ok(/3 Element/.test(elTab.count), 'the count line reports 3 Elements', elTab.count);

  console.log('\n[E2] Elements tab — validation is the engine\'s, and it rejects');
  const badPalette = await evaluate(`(() => {
    const el = document.getElementById('e-palette');
    el.value = '0.82,0.61';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      errors: [...document.querySelectorAll('#e-errors .warn-item')].map(e => e.textContent.trim()),
      sidecar: document.getElementById('e-sidecar').textContent.trim(),
    };
  })()`);
  ok(
    badPalette.errors.length === 1 && /three comma-separated/.test(badPalette.errors[0] ?? ''),
    "a two-channel palette entry is rejected with the engine's rule",
    badPalette.errors[0] ?? '(none)',
  );
  ok(badPalette.sidecar === '—', 'no sidecar path is shown for an invalid record', badPalette.sidecar);

  const inverted = await evaluate(`(() => {
    const p = document.getElementById('e-palette');
    p.value = '0.82,0.61,0.55';
    p.dispatchEvent(new Event('input', { bubbles: true }));
    const box = document.getElementById('e-has-bbox');
    box.checked = true;
    box.dispatchEvent(new Event('change', { bubbles: true }));
    const mx = document.getElementById('e-bbox-min-x');
    mx.value = '0.9';
    mx.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      errors: [...document.querySelectorAll('#e-errors .warn-item')].map(e => e.textContent.trim()),
    };
  })()`);
  ok(
    inverted.errors.some((e) => /inverted/.test(e)),
    'an inverted bbox is rejected',
    inverted.errors.join(' | ') || '(none)',
  );

  const validEl = await evaluate(`(() => {
    const mx = document.getElementById('e-bbox-min-x');
    mx.value = '-0.3';
    mx.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      errors: [...document.querySelectorAll('#e-errors .warn-item')].map(e => e.textContent.trim()),
      sidecar: document.getElementById('e-sidecar').textContent.trim(),
      summary: document.getElementById('e-summary').textContent.trim(),
      json: JSON.parse(document.getElementById('e-element-json').textContent),
      measurable: document.getElementById('e-measurable').textContent.trim(),
    };
  })()`);
  ok(
    validEl.errors.length === 1 && /Valid/.test(validEl.errors[0] ?? ''),
    'a valid record is accepted',
    validEl.errors[0] ?? '(none)',
  );
  ok(validEl.sidecar === 'assets/tamsin.element.json', 'the sidecar path is computed', validEl.sidecar);
  ok(
    validEl.json.palette.length === 1 && validEl.json.palette[0].join(',') === '0.82,0.61,0.55',
    'element_json carries the parsed palette',
    JSON.stringify(validEl.json.palette),
  );
  ok(
    Array.isArray(validEl.json.bbox) && validEl.json.bbox.length === 4,
    'element_json carries the bbox',
    JSON.stringify(validEl.json.bbox),
  );
  ok(
    /MEASURABLE/.test(validEl.measurable) && !/NOT MEASURABLE/.test(validEl.measurable),
    'with a palette and a bbox the Element is measurable',
    validEl.measurable.slice(0, 48),
  );

  console.log('\n[E3] Elements tab — adding an Element changes what the other tabs resolve');
  const added = await evaluate(`(() => {
    const n = document.getElementById('e-name');
    n.value = 'the-rooftop';
    n.dispatchEvent(new Event('input', { bubbles: true }));
    const c = document.getElementById('e-category');
    c.value = 'location';
    c.dispatchEvent(new Event('change', { bubbles: true }));
    const p = document.getElementById('e-image-path');
    p.value = 'assets/the-rooftop.png';
    p.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('e-add').click();
    return {
      rows: document.querySelectorAll('#e-registry .registry-item').length,
      directorRegistry: document.getElementById('d-registry').textContent,
      directorCount: window.__cinematographer.directorPanel.getRegistry().length,
    };
  })()`);
  ok(added.rows === 4, 'the new Element appears in the Elements registry', String(added.rows));
  ok(added.directorCount === 4, 'the Director tab shares the same registry', String(added.directorCount));
  ok(
    /the-rooftop/.test(added.directorRegistry),
    'the Director tab shows the new Element',
    added.directorRegistry.trim().slice(0, 60),
  );

  const elReset = await evaluate(`(() => {
    document.getElementById('e-reset').click();
    return {
      rows: document.querySelectorAll('#e-registry .registry-item').length,
      directorCount: window.__cinematographer.directorPanel.getRegistry().length,
    };
  })()`);
  ok(
    elReset.rows === 3 && elReset.directorCount === 3,
    'Reset restores the shipped demo registry on both tabs',
    `${elReset.rows} / ${elReset.directorCount}`,
  );

  // ================= SHOOT TAB (Stage 4 PROMPT) =================
  console.log('\n[S1] Shoot tab — the composed prompt resolves @Element to the API token');
  await evaluate(`document.querySelector('#tabnav [data-tab="shoot"]').click(), true`);
  await sleep(300);
  const shoot = await evaluate(`(() => ({
    visible: !document.getElementById('tab-shoot').classList.contains('hidden'),
    onTab: document.querySelector('#tabnav .tab.on')?.dataset.tab,
    note: document.getElementById('tabnav-note').textContent.trim(),
    action: document.getElementById('s-action').value,
    final: document.getElementById('s-final').textContent,
    attachments: [...document.querySelectorAll('#s-attachments .attach-item')].map(e => e.textContent.trim()),
    unresolved: document.getElementById('s-unresolved').textContent.trim(),
    okBadge: document.getElementById('s-ok').textContent.trim(),
  }))()`);
  ok(shoot.visible && shoot.onTab === 'shoot', 'the Shoot tab becomes visible and is selected');
  ok(/sends nothing/.test(shoot.note), 'the tab bar says the Shoot tab sends nothing', shoot.note);
  ok(/@tamsincamp/.test(shoot.action), 'the action carries an @Element tag', shoot.action);
  ok(/<<<image_1>>>/.test(shoot.final), 'the tag resolved to the API reference token', shoot.final);
  ok(!/@tamsincamp/.test(shoot.final), 'the raw @tag is gone from the composed prompt');
  ok(shoot.attachments.length === 1, 'one attachment is reported', String(shoot.attachments.length));
  ok(/tamsincamp/.test(shoot.attachments[0] ?? ''), 'the attachment names the Element', shoot.attachments[0] ?? '');
  ok(
    /assets\/tamsin\.png/.test(shoot.attachments[0] ?? ''),
    "the attachment shows the node's asset_path field",
    shoot.attachments[0] ?? '',
  );
  ok(/Every tag resolved/.test(shoot.unresolved), 'a fully-resolved prompt says so', shoot.unresolved.slice(0, 48));
  ok(/true/.test(shoot.okBadge), 'the ok output is true', shoot.okBadge);

  console.log('\n[S2] Shoot tab — an unresolved tag is a visible failure, not a silent drop');
  const unresolved = await evaluate(`(() => {
    const a = document.getElementById('s-action');
    a.value = 'A detective crosses the diner, @tamsincamp and @nobody at all';
    a.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      final: document.getElementById('s-final').textContent,
      bad: [...document.querySelectorAll('#s-unresolved .warn-item-bad')].map(e => e.textContent.trim()),
      count: document.getElementById('s-unresolved-count').textContent.trim(),
      okBadge: document.getElementById('s-ok').textContent.trim(),
      chips: [...document.querySelectorAll('#s-tags .tag-chip')].map(e => e.className),
    };
  })()`);
  ok(unresolved.bad.length === 1, 'exactly one unresolved tag is reported', String(unresolved.bad.length));
  ok(
    /no Element named "nobody"/.test(unresolved.bad[0] ?? ''),
    'the reason names the missing Element',
    unresolved.bad[0] ?? '(none)',
  );
  ok(/@nobody/.test(unresolved.final), 'the unresolved tag stays literal in the prompt', unresolved.final);
  ok(/false/.test(unresolved.okBadge), 'the ok output is false', unresolved.okBadge);
  ok(unresolved.chips.includes('tag-chip bad'), 'the tag chip renders in the failure colour', unresolved.chips.join(' '));
  ok(/1 unresolved/.test(unresolved.count), 'the unresolved count is on screen', unresolved.count);

  console.log('\n[S3] Shoot tab — it reuses the Director tab\'s move stack, not a copy');
  const moves = await evaluate(`(() => {
    document.querySelector('#tabnav [data-tab="director"]').click();
    // The Director tab may already carry moves from the earlier [D3] checks, so
    // this measures the DELTA rather than assuming an empty stack.
    const before = window.__cinematographer.directorState.moves.length;
    const sel = document.getElementById('d-move-add');
    sel.value = sel.options[0].value;
    document.getElementById('d-move-add-btn').click();
    const stacked = window.__cinematographer.directorState.moves.slice();
    document.querySelector('#tabnav [data-tab="shoot"]').click();
    return {
      before,
      stacked,
      last: stacked[stacked.length - 1],
      final: document.getElementById('s-final').textContent,
      shown: document.getElementById('s-moves').textContent.trim(),
      fragment: document.getElementById('s-panel-fragment').textContent,
    };
  })()`);
  ok(
    moves.stacked.length === moves.before + 1,
    'the Director tab stacked one more move',
    `${moves.before} -> ${moves.stacked.length}`,
  );
  ok(
    moves.final.trim().endsWith('#' + moves.last),
    "the Shoot tab appends the Director's move tags, in order",
    moves.final.slice(-48),
  );
  ok(moves.shown.includes('#' + moves.last), "the Shoot tab shows the Director's move stack", moves.shown);
  ok(/camera_movement/.test(moves.fragment), 'the panel fragment carries the move group', moves.fragment.slice(0, 56));

  // ================== POST TAB (Stage 5 POST) ==================
  console.log('\n[P1] Post tab — the seven controls are the engine\'s GRADE_PARAMS');
  await evaluate(`document.querySelector('#tabnav [data-tab="post"]').click(), true`);
  await sleep(300);
  const post = await evaluate(`(() => {
    const S = window.__cinematographer.studio;
    const sliders = [...document.querySelectorAll('#p-grade-controls input[type=range]')];
    return {
      visible: !document.getElementById('tab-post').classList.contains('hidden'),
      onTab: document.querySelector('#tabnav .tab.on')?.dataset.tab,
      note: document.getElementById('tabnav-note').textContent.trim(),
      sliderIds: sliders.map(e => e.id.replace('p-grade-', '')),
      engineParams: S.GRADE_PARAMS,
      ranges: sliders.map(e => [e.min, e.max]),
      engineRanges: S.GRADE_PARAMS.map(p => S.GRADE_RANGES[p].map(String)),
      neutral: document.getElementById('p-neutral').textContent.trim(),
      summary: document.getElementById('p-summary').textContent.trim(),
      json: JSON.parse(document.getElementById('p-grade-json').textContent),
      checks: [...document.querySelectorAll('#p-checks .rule-name')].map(e => e.textContent),
      engineRules: S.POST_RULES,
      weights: [...document.querySelectorAll('#p-checks .rule-weight')].map(e => e.textContent.trim()),
      overall: document.getElementById('p-overall').textContent.trim(),
    };
  })()`);
  ok(post.visible && post.onTab === 'post', 'the Post tab becomes visible and is selected');
  ok(/CinemaGradeApply/.test(post.note), 'the tab bar names the node that actually changes pixels', post.note);
  ok(
    post.sliderIds.join('|') === post.engineParams.join('|'),
    'the seven sliders are GRADE_PARAMS in order',
    post.sliderIds.join(','),
  );
  ok(
    JSON.stringify(post.ranges) === JSON.stringify(post.engineRanges),
    "every slider range is the engine's GRADE_RANGES",
    JSON.stringify(post.ranges),
  );
  ok(/true/.test(post.neutral), 'a fresh grade is neutral', post.neutral);
  ok(post.summary === 'grade: neutral (no deltas)', "the neutral summary is the engine's string", post.summary);
  ok(post.json.count === 0 && post.json.is_noop === true, 'the neutral grade_json has no deltas', JSON.stringify(post.json));
  ok(
    post.checks.join('|') === post.engineRules.join('|'),
    'the four POST rules render in engine order',
    post.checks.join(','),
  );
  ok(post.weights.join('|') === 'w 1.0|w 1.0|w 1.0|w 0.5', "the audit weights are the engine's", post.weights.join('|'));
  ok(/PASS/.test(post.overall), 'a neutral plan passes the POST audit', post.overall);

  console.log('\n[P2] Post tab — a moved control becomes a delta, computed by the engine');
  const graded = await evaluate(`(() => {
    const S = window.__cinematographer.studio;
    const el = document.getElementById('p-grade-temperature');
    el.value = '0.5';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      json: JSON.parse(document.getElementById('p-grade-json').textContent),
      summary: document.getElementById('p-summary').textContent.trim(),
      engineSummary: S.gradeSummary(S.applyGrade({ temperature: 0.5 })),
      neutral: document.getElementById('p-neutral').textContent.trim(),
      out: document.getElementById('p-grade-temperature-out').textContent.trim(),
    };
  })()`);
  ok(graded.json.count === 1, 'one delta is reported', String(graded.json.count));
  ok(
    graded.json.deltas[0].param === 'temperature' && graded.json.deltas[0].direction === 'up',
    'the delta names the control and its direction',
    JSON.stringify(graded.json.deltas[0]),
  );
  ok(graded.summary === graded.engineSummary, "the summary matches the engine's own string", graded.summary);
  ok(/false/.test(graded.neutral), 'is_neutral flips to false', graded.neutral);
  ok(graded.out === '+0.50', 'the control readout follows the slider', graded.out);

  console.log('\n[P3] Post tab — the JUDGE -> POST gate carries the live judge verdict');
  const gate = await evaluate(`(() => {
    const S = window.__cinematographer.studio;
    // Put the Judge back on its defaults, which FAIL, so there IS a verdict to carry.
    document.querySelector('#tabnav [data-tab="judge"]').click();
    document.getElementById('reset').click();
    const report = window.__cinematographer.compute().report;
    document.querySelector('#tabnav [data-tab="post"]').click();
    return {
      shown: document.getElementById('p-corrections').textContent.trim(),
      engine: S.correctionsText(report),
      engineLines: S.correctionsFromReport(report).length,
      badge: document.getElementById('p-gate').textContent.trim(),
      badgeClass: document.getElementById('p-gate').className,
      failing: report.scores.filter(s => !s.pass).map(s => s.rule),
      failingWithLever: report.scores.filter(s => !s.pass && s.correction).length,
      overall: document.getElementById('overall-value').textContent,
    };
  })()`);
  ok(gate.overall === 'FAIL', 'the Judge is back on its failing default frame', gate.overall);
  ok(gate.failing.length > 0, 'the default frame has failing rules to carry', gate.failing.join(','));
  ok(
    gate.shown === gate.engine,
    'the gate text is exactly what CinematographerCorrection would produce',
    gate.shown.split('\n')[0] ?? '(empty)',
  );
  ok(
    gate.engineLines === gate.failingWithLever,
    'one correction line per failing rule that has a lever',
    `${gate.engineLines} lines / ${gate.failingWithLever} levers`,
  );
  ok(/carrying \d+ correction/.test(gate.badge), 'the gate badge reports the carry count', gate.badge);
  ok(/open/.test(gate.badgeClass), 'the gate badge is in the open state', gate.badgeClass);

  console.log('\n[P4] Post tab — the gate follows the Judge tab live');
  const gateLive = await evaluate(`(() => {
    const S = window.__cinematographer.studio;
    document.querySelector('#tabnav [data-tab="judge"]').click();
    const before = S.correctionsFromReport(window.__cinematographer.compute().report).length;
    document.getElementById('autoframe').click();
    const report = window.__cinematographer.compute().report;
    const after = S.correctionsFromReport(report).length;
    const overall = document.getElementById('overall-value').textContent;
    document.querySelector('#tabnav [data-tab="post"]').click();
    return {
      before, after, overall,
      engine: S.correctionsText(report),
      shown: document.getElementById('p-corrections').textContent.trim(),
      badge: document.getElementById('p-gate').textContent.trim(),
    };
  })()`);
  ok(gateLive.overall === 'PASS', 'Auto-Frame flips the judge to overall PASS', gateLive.overall);
  ok(
    gateLive.after < gateLive.before,
    'Auto-Frame reduces the corrections the gate carries',
    `${gateLive.before} -> ${gateLive.after}`,
  );
  ok(
    gateLive.shown ===
      (gateLive.engine || '(empty — the judge found no failing rule, so there is nothing to correct)'),
    'the Post tab re-reads the gate on show',
    gateLive.shown.slice(0, 56),
  );
  ok(
    gateLive.after > 0 ? /carrying/.test(gateLive.badge) : /no corrections/.test(gateLive.badge),
    'the gate badge matches the carried count',
    gateLive.badge,
  );

  console.log('\n[E4] the three new tabs screenshot');
  for (const [tab, suffix] of [['elements', 'elements'], ['shoot', 'shoot'], ['post', 'post']]) {
    await evaluate(`document.querySelector('#tabnav [data-tab="${tab}"]').click(), true`);
    await sleep(250);
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    const file = SHOT.replace(/\.png$/, `-${suffix}.png`);
    writeFileSync(file, Buffer.from(shot.data, 'base64'));
    ok(existsSync(file), `${tab} tab screenshot written`, file);
  }

  const lateErrors = await evaluate('JSON.stringify(window.__panelErrors || [])');
  ok(lateErrors === '[]', 'no JS errors after exercising all six tabs', lateErrors);

  // Leave the panel where the rest of this check expects it.
  await evaluate(`document.querySelector('#tabnav [data-tab="judge"]').click(), true`);
  await sleep(200);

  // -------------------------------------------------------------------------
  // Stage 6 — the Run tab: export an API prompt, and run it live
  // -------------------------------------------------------------------------

  console.log('\n[R1] Run tab — the affordance exists and the exported prompt is real');

  const affordance = await evaluate(`(() => {
    const btn = document.querySelector('#tabnav [data-tab="run"]');
    if (!btn) return { found: false };
    btn.click();
    return {
      found: true,
      visible: !document.getElementById('tab-run').classList.contains('hidden'),
      hasRun: !!document.getElementById('r-run'),
      hasBase: !!document.getElementById('r-base-url'),
      hasJson: !!document.getElementById('r-json'),
      hasTaps: !!document.getElementById('r-taps'),
      base: document.getElementById('r-base-url').value,
      note: document.getElementById('tabnav-note').textContent.trim(),
    };
  })()`);
  ok(affordance.found, 'the Run tab button exists');
  ok(affordance.visible, 'clicking it shows the Run panel');
  ok(
    affordance.hasRun && affordance.hasBase && affordance.hasJson && affordance.hasTaps,
    'the affordance is complete — Run button, base URL, prompt JSON, results list',
  );
  ok(
    affordance.base === CC.DEFAULT_BASE_URL,
    'the base URL defaults to the local ComfyUI',
    affordance.base,
  );
  ok(
    /generates no image and no video/.test(affordance.note),
    'the tab note still says a run generates no image and no video',
    affordance.note.slice(0, 72),
  );

  const exported = await evaluate(`(() => {
    const shown = document.getElementById('r-json').textContent;
    let graph;
    try { graph = JSON.parse(shown); } catch (e) { return { parseError: String(e.message) }; }
    const RP = window.__cinematographer.runPanel;
    const CC = window.__cinematographer.comfyClient;
    const fresh = JSON.stringify(CC.buildGraph(RP.collect()).graph, null, 2);
    const nodes = Object.values(graph);
    const collected = RP.collect();
    return {
      graph,
      nodeCount: nodes.length,
      classes: [...new Set(nodes.map((n) => n.class_type))].sort(),
      previews: nodes.filter((n) => n.class_type === 'PreviewAny').length,
      isFresh: fresh === shown,
      stats: document.getElementById('r-graph-stats').textContent.trim(),
      // The panel spells the emotion wheel as slugs; the node's COMBO is Title
      // Case and ComfyUI validates a COMBO by exact membership. Sending the slug
      // makes the server drop the node and everything downstream of it while
      // still answering HTTP 200 — a silent partial run.
      panelEmotion: (collected.director.emotions ?? [])[0]?.emotion ?? null,
      sentEmotion: graph['1']?.inputs?.emotion ?? null,
      engineEmotions: [...CC.ENGINE_EMOTIONS],
    };
  })()`);
  ok(!exported.parseError, 'the prompt pane holds parseable JSON', exported.parseError ?? '');
  ok(
    exported.isFresh,
    'the pane is the live graph, not a stale copy — it rebuilds byte-identical from current state',
    `${exported.nodeCount} nodes`,
  );
  ok(
    exported.classes.every((c) => c === CC.PREVIEW_NODE || c.startsWith('Cinema')),
    "every class_type is one of the pack's own nodes or the stock output node",
    exported.classes.join(', '),
  );
  ok(
    exported.previews >= 1,
    'the graph terminates in a stock output node, so ComfyUI will accept it',
    `${exported.previews} ${CC.PREVIEW_NODE} taps`,
  );
  // The emotion the panel puts on the wire must be the node's exact COMBO
  // member, never the panel's own slug.
  ok(
    exported.sentEmotion === 'auto' || exported.engineEmotions.includes(exported.sentEmotion),
    "the emotion sent to CinemaDirectorPanel is the node's exact COMBO member",
    `panel slug ${JSON.stringify(exported.panelEmotion)} -> sent ${JSON.stringify(exported.sentEmotion)}`,
  );
  if (exported.panelEmotion) {
    const want = exported.engineEmotions.find(
      (e) => e.toLowerCase() === String(exported.panelEmotion).toLowerCase(),
    );
    ok(
      exported.sentEmotion === want,
      'an emotion chosen in the Director tab is translated, not passed through raw',
      `${JSON.stringify(exported.panelEmotion)} -> ${JSON.stringify(exported.sentEmotion)}`,
    );
  }

  // The live server decides whether the live half runs. Probed from Node, so a
  // skip is a fact about the machine rather than a swallowed browser failure.
  let serverUp = false;
  let objectInfo = null;
  let serverWhy = `no ComfyUI answered at ${COMFY} within 4000 ms`;
  try {
    const stats = await fetch(`${COMFY}/system_stats`, { signal: AbortSignal.timeout(4000) });
    serverUp = stats.ok;
    if (serverUp) {
      const oi = await fetch(`${COMFY}/object_info`, { signal: AbortSignal.timeout(30000) });
      if (oi.ok) objectInfo = await oi.json();
    } else {
      serverWhy = `${COMFY}/system_stats -> HTTP ${stats.status}`;
    }
  } catch (err) {
    serverWhy = `${COMFY} unreachable — ${err?.message ?? err}`;
  }

  if (objectInfo) {
    const unknown = exported.classes.filter((c) => !(c in objectInfo));
    ok(
      unknown.length === 0,
      'the server knows every class_type in the exported prompt',
      unknown.length ? unknown.join(', ') : `${exported.classes.length} classes checked`,
    );
  } else {
    ok(true, `class_type check against /object_info skipped — ${serverWhy}`, 'the pack ships these classes');
  }

  console.log('\n[R2] Run tab — prompt_no_outputs is reported, not swallowed');
  if (serverUp) {
    const stripped = Object.fromEntries(
      Object.entries(exported.graph ?? {}).filter(([, n]) => n.class_type !== CC.PREVIEW_NODE),
    );
    ok(
      Object.keys(stripped).length === exported.nodeCount - exported.previews,
      'the stripped graph really is the prompt minus its taps',
      `${Object.keys(stripped).length} of ${exported.nodeCount} nodes kept`,
    );
    const res = await fetch(`${COMFY}/prompt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: stripped, client_id: 'cine-browser-check' }),
      signal: AbortSignal.timeout(20000),
    });
    const body = await res.json();
    ok(
      res.status === 400 && body?.error?.type === 'prompt_no_outputs',
      'stripping the taps reproduces the real prompt_no_outputs 400',
      `HTTP ${res.status} ${body?.error?.type ?? '?'}`,
    );
    const sentence = CC.describeSubmitFailure({
      ok: false,
      status: res.status,
      error: body?.error ?? null,
      node_errors: body?.node_errors ?? {},
    });
    ok(
      /prompt_no_outputs/.test(sentence) && /PreviewAny/.test(sentence),
      'the panel turns that failure into a sentence that names the cause',
      sentence.slice(0, 88),
    );
  } else {
    ok(true, `prompt_no_outputs check skipped — ${serverWhy}`, 'start ComfyUI to exercise this path');
  }

  console.log('\n[R3] Run tab — a real POST, poll and render');
  if (!serverUp) {
    ok(
      true,
      `live run skipped — ${serverWhy}`,
      'the exported prompt JSON above is complete and needs no server',
    );
    const skipped = await evaluate(
      `document.getElementById('r-run-status').textContent.trim()`,
    );
    ok(
      /Nothing has been sent/.test(skipped),
      'with no server, the panel claims nothing — the status line is still the initial one',
      skipped,
    );

    // The panel's own no-server path, exercised for real rather than skipped:
    // point it at a port nothing can be listening on and click Run. It must say
    // so on screen and send nothing — no fabricated success.
    await evaluate(`(() => {
      const f = document.getElementById('r-base-url');
      f.value = 'http://127.0.0.1:1';
      f.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('r-run').click();
      return true;
    })()`);
    await waitFor(
      `document.getElementById('r-run-status').textContent.includes('No ComfyUI answered')`,
      'the panel to report the dead server',
      30000,
    );
    const refused = await evaluate(
      `document.getElementById('r-run-status').textContent.trim()`,
    );
    ok(
      /No ComfyUI answered at/.test(refused),
      'the panel says on screen that no server answered, and names the address',
      refused.slice(0, 120),
    );
    ok(
      /Nothing was sent/.test(refused),
      'the panel states plainly that nothing was sent',
      refused.slice(0, 120),
    );
    const tapsAfter = await evaluate(`document.querySelectorAll('#r-taps .tap-item').length`);
    ok(
      tapsAfter === 0,
      'no taps are rendered, because no run happened',
      `${tapsAfter} tap blocks`,
    );
  } else {
    await evaluate(`document.getElementById('r-run').click(), true`);
    await waitFor(
      `(() => {
        const t = document.getElementById('r-run-status').textContent;
        return /taps returned output in this record|it failed|Nothing was sent|rejected|does not know|threw|nothing is claimed/.test(t);
      })()`,
      'the run to settle',
      240000,
    );

    const result = await evaluate(`(() => {
      const RP = window.__cinematographer.runPanel;
      const C = window.__cinematographer.engine;
      const P = window.__cinematographer.panel;
      const state = window.__cinematographer.state;
      const report = P.compute(state).report;
      const taps = [...document.querySelectorAll('#r-taps .tap-item')].map((n) => ({
        head: n.querySelector('.tap-head').textContent.trim(),
        text: n.querySelector('.plan-pre')?.textContent ?? null,
        note: n.querySelector('.card-foot')?.textContent.trim() ?? null,
      }));
      const rec = RP.lastRecord();
      const cachedMsg = (rec?.status?.messages ?? []).find((m) => m[0] === 'execution_cached');
      return {
        status: document.getElementById('r-run-status').textContent.trim(),
        ran: document.getElementById('r-ran').textContent.trim(),
        reconcile: document.getElementById('r-reconcile').textContent.trim(),
        errors: document.getElementById('r-errors').textContent.trim(),
        footer: document.getElementById('provenance-live').textContent.trim(),
        taps,
        panelSummary: C.summary(report),
        outputKeys: Object.keys(rec?.outputs ?? {}),
        cachedNodes: cachedMsg?.[1]?.nodes ?? null,
        nodeErrors: Object.keys(RP.lastNodeErrors() ?? {}),
      };
    })()`);

    const diag =
      `outputs=${JSON.stringify(result.outputKeys)} cached=${JSON.stringify(result.cachedNodes)} `
      + `node_errors=${JSON.stringify(result.nodeErrors)}`;

    ok(
      /taps returned output in this record/.test(result.status),
      'the panel reports the run it actually received',
      result.status.slice(0, 110),
    );
    ok(
      /^7 \/ 7 taps returned output in this record/.test(result.ran),
      'all seven taps returned output — the graph ran whole',
      `${result.ran} · ${diag}`,
    );
    // The direct check for a silent partial run. ComfyUI answers 200 with a
    // `prompt_id` even when it has dropped output nodes at validation, naming
    // them only in `node_errors`. A non-empty set here means the panel ran a
    // graph the server had already rejected in part.
    ok(
      result.nodeErrors.length === 0,
      'ComfyUI accepted every node — nothing was dropped at validation',
      diag,
    );
    ok(
      result.taps.length === 7 &&
        result.taps.every((t) => t.text !== null || (t.note ?? '').length > 20),
      'every tap either shows its value or states on screen why it has none',
      `${result.taps.filter((t) => t.text !== null).length} with values, `
        + `${result.taps.filter((t) => t.text === null).length} explained · ${diag}`,
    );
    ok(
      result.taps.filter((t) => t.text === null).length === 0,
      'no tap came back empty on this run',
      diag,
    );

    // The strongest check available: the string the SERVER returned for the
    // framing verdict must equal the string the panel's own mirror computes.
    const evaluateTap = result.taps.find((t) => /CinematographerEvaluate/.test(t.head));
    ok(
      evaluateTap?.text === result.panelSummary,
      "the server's framing verdict is byte-identical to the panel's own mirror",
      `${JSON.stringify(evaluateTap?.text)} vs ${JSON.stringify(result.panelSummary)}`,
    );
    ok(
      /^(\d+) of \1 comparable strings are identical/.test(result.reconcile),
      'the reconcile card reports every comparable string as identical',
      result.reconcile.slice(0, 90),
    );
    ok(
      result.errors === '',
      'no execution errors were returned',
      result.errors.slice(0, 90),
    );
    ok(
      /Last run: prompt .+ status_str "success"/.test(result.footer),
      'the footer records the real run instead of claiming no render is wired',
      result.footer.slice(0, 110),
    );

    await evaluate(`document.querySelector('#tabnav [data-tab="run"]').click(), true`);
    await sleep(250);
    const runShot = await send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: true,
    });
    const runFile = SHOT.replace(/\.png$/, '-run.png');
    writeFileSync(runFile, Buffer.from(runShot.data, 'base64'));
    ok(existsSync(runFile), 'run tab screenshot written', runFile);
  }

  console.log('\n[R4] Run tab — a node ComfyUI drops at validation is surfaced, not hidden');
  if (!serverUp) {
    ok(
      true,
      `silent-drop check skipped — ${serverWhy}`,
      'this path needs a live server to reject the node',
    );
  } else {
    // Force a value the node's COMBO cannot accept. `engineEmotion` passes an
    // unrecognised slug through unchanged on purpose — the server, not the
    // panel, should be the one to reject it. ComfyUI answers 200 with a
    // `prompt_id` anyway and drops the node plus everything downstream of it,
    // naming them only in `node_errors`. The panel must not call that a clean
    // run.
    const injected = await evaluate(`(() => {
      const DP = window.__cinematographer.directorPanel;
      const before = (DP.directorState.emotions ?? []).map((e) => ({ ...e }));
      DP.directorState.emotions = [{ element: 'tamsincamp', emotion: 'ennui', intensity: 1 }];
      const RP = window.__cinematographer.runPanel;
      const CC = window.__cinematographer.comfyClient;
      const graph = CC.buildGraph(RP.collect()).graph;
      return { before, sent: graph['1'].inputs.emotion };
    })()`);
    ok(
      injected.sent === 'ennui',
      'an unrecognised emotion is passed through for the server to reject, not silently dropped',
      JSON.stringify(injected.sent),
    );

    await evaluate(`document.getElementById('r-build').click(), true`);
    await sleep(200);
    await evaluate(`document.getElementById('r-run').click(), true`);
    await waitFor(
      `(() => {
        const t = document.getElementById('r-run-status').textContent;
        return /taps returned output in this record|it failed|Nothing was sent|does not know|threw/.test(t);
      })()`,
      'the panel to settle on the partial run',
      120000,
    );

    const dropped = await evaluate(`(() => ({
      status: document.getElementById('r-run-status').textContent.trim(),
      errors: document.getElementById('r-errors').textContent.trim(),
      ran: document.getElementById('r-ran').textContent.trim(),
      nodeErrors: Object.keys(window.__cinematographer.runPanel.lastNodeErrors() ?? {}),
    }))()`);
    ok(
      /were rejected at validation and never ran/.test(dropped.status),
      'the panel says the prompt was accepted but nodes were rejected',
      dropped.status.slice(0, 130),
    );
    ok(
      /partial run, not a clean one/.test(dropped.status),
      'the panel refuses to call a partial run clean',
      dropped.status.slice(-100),
    );
    ok(
      /^3 \/ 7 taps returned output in this record/.test(dropped.ran),
      'the tap count reflects the nodes ComfyUI dropped, not the graph that was sent',
      dropped.ran,
    );
    ok(
      dropped.nodeErrors.length > 0,
      'the panel kept the server\'s node_errors rather than discarding them',
      JSON.stringify(dropped.nodeErrors),
    );
    ok(
      /CinemaDirectorPanel|emotion/i.test(dropped.errors),
      "the engine's own reason is on screen, verbatim",
      dropped.errors.slice(0, 130),
    );

    // Put the Director tab back the way it was.
    await evaluate(`(() => {
      const DP = window.__cinematographer.directorPanel;
      DP.directorState.emotions = ${JSON.stringify(injected.before)};
      document.getElementById('r-build').click();
      return true;
    })()`);
    await sleep(200);
    const restored = await evaluate(
      `window.__cinematographer.comfyClient.buildGraph(
         window.__cinematographer.runPanel.collect()).graph['1'].inputs.emotion`,
    );
    ok(
      restored !== 'ennui',
      'the Director tab was restored after the check',
      JSON.stringify(restored),
    );
  }

  // ===================== STUDIO TAB (the front door) =====================
  console.log('\n[S1] Studio tab — their shape, our engine');
  const studioTab = await evaluate(`(() => {
    const btn = document.querySelector('#tabnav .tab[data-tab="studio"]');
    const panel = document.getElementById('tab-studio');
    window.__cinematographer.showTab('studio');
    const SP = window.__cinematographer.studioPanel;
    const opts = (id) => [...document.getElementById(id).options].map((o) => o.value);
    return {
      hasButton: !!btn,
      hasPanel: !!panel,
      tabs: [...document.querySelectorAll('#tabnav .tab')].map((b) => b.dataset.tab),
      shot: opts('st-shot'),
      camera: opts('st-camera'),
      light: opts('st-light'),
      look: opts('st-look'),
      mappingErrors: SP.MAPPING_ERRORS,
      expected: {
        shot: SP.SHOT_CHOICES, camera: SP.CAMERA_CHOICES,
        light: SP.LIGHT_CHOICES, look: SP.LOOK_CHOICES,
      },
    };
  })()`);
  ok(studioTab.hasButton && studioTab.hasPanel, 'the Studio tab is in the bar and reachable',
    studioTab.tabs.join(' → '));
  ok(
    studioTab.shot.length === 5 && studioTab.camera.length === 4
      && studioTab.light.length === 4 && studioTab.look.length === 4,
    "the four dropdowns carry Comfy Org's own vocabulary, at their own lengths",
    `${studioTab.shot.length}/${studioTab.camera.length}/${studioTab.light.length}/${studioTab.look.length}`,
  );
  ok(
    JSON.stringify(studioTab.shot) === JSON.stringify(studioTab.expected.shot)
      && JSON.stringify(studioTab.camera) === JSON.stringify(studioTab.expected.camera)
      && JSON.stringify(studioTab.light) === JSON.stringify(studioTab.expected.light)
      && JSON.stringify(studioTab.look) === JSON.stringify(studioTab.expected.look),
    'the rendered options are the module\'s own lists, in order',
  );
  ok(
    studioTab.mappingErrors.length === 0,
    'every one of their words maps to a real engine enum member',
    studioTab.mappingErrors.length ? studioTab.mappingErrors.join(' | ') : '0 mapping errors',
  );

  console.log('\n[S2] Studio tab — the verdict is measured, and the preview is the real parser');
  const studioVerdict = await evaluate(`(() => {
    const SP = window.__cinematographer.studioPanel;
    const D = window.__cinematographer.director;
    const DP = window.__cinematographer.directorPanel;
    const v = SP.studioVerdict();
    const rows = [...document.querySelectorAll('#st-verdict tbody tr')];

    // Change all four, the way a stranger would, and re-read.
    const scene = 'A lone astronaut finds a field of flowers on Mars';
    document.getElementById('st-scene').value = scene;
    document.getElementById('st-shot').value = 'Low-angle shot';
    document.getElementById('st-camera').value = '85mm portrait lens, soft background';
    document.getElementById('st-light').value = 'Golden-hour backlight';
    const look = document.getElementById('st-look');
    look.value = 'High-contrast noir';
    look.dispatchEvent(new Event('change', { bubbles: true }));

    const shown = document.getElementById('st-prompt').textContent;
    const direct = D.composePrompt({
      text: scene, moves: DP.directorState.moves, registry: DP.getRegistry(),
    }).prompt;

    // Measure the frame the four choices produce, then pull the lever.
    const preSolve = SP.studioVerdict();
    const before = JSON.stringify(window.__cinematographer.directorState);
    document.getElementById('st-autoframe').click();
    const solved = SP.isSolved();
    const after = SP.studioVerdict();

    return {
      v, rowCount: rows.length,
      badges: rows.map((r) => r.querySelector('.gate-badge')?.textContent.trim()),
      head: document.getElementById('st-verdict-head').textContent.trim(),
      shown, direct, scene,
      t: SP.studioTranslation(),
      solved,
      directorUnchanged: before === JSON.stringify(window.__cinematographer.directorState),
      afterWeighted: after.weighted_failures,
      beforeWeighted: preSolve.weighted_failures,
      status: document.getElementById('st-status').textContent.trim(),
    };
  })()`);
  ok(studioVerdict.rowCount === 9, 'the verdict table has all 9 rules', String(studioVerdict.rowCount));
  ok(
    studioVerdict.badges.length === 9
      && studioVerdict.badges.every((b) => b === 'pass' || b === 'fail'),
    'every rule carries a pass/fail badge',
    studioVerdict.badges.join(','),
  );
  ok(
    studioVerdict.v.rules.length === 9
      && studioVerdict.v.rules.every((r) => typeof r.value === 'number'),
    'every rule has a computed numeric measurement, not a label',
  );
  ok(
    /^(PASS|FAIL) (closeup|medium|wide) on '/.test(studioVerdict.v.summary),
    "the verdict is the engine's own summary format",
    studioVerdict.v.summary,
  );
  ok(
    /reliability (green|yellow|red)/.test(studioVerdict.head),
    'the reliability zone is on screen beside it',
    (studioVerdict.head.match(/reliability \w+/) ?? [''])[0],
  );
  ok(
    studioVerdict.shown === studioVerdict.direct && studioVerdict.shown.includes(studioVerdict.scene),
    'the preview is byte-identical to director.js composePrompt() — one parser, not two',
    studioVerdict.shown.slice(0, 70),
  );
  ok(
    studioVerdict.t.shot_type === 'medium' && studioVerdict.t.angle === 'low'
      && studioVerdict.t.focal_mm === 85 && studioVerdict.t.light === 'contre-jour'
      && studioVerdict.t.color_palette === 'neon-rain-at-midnight',
    'all four choices reach the engine as real values',
    JSON.stringify(studioVerdict.t),
  );
  ok(studioVerdict.solved, 'Auto-frame solves a camera and adopts it');
  ok(
    studioVerdict.afterWeighted.length <= studioVerdict.beforeWeighted.length,
    'the solve does not make the weighted verdict worse',
    `${studioVerdict.beforeWeighted.join(',') || 'none'} → ${studioVerdict.afterWeighted.join(',') || 'none'}`,
  );
  ok(
    studioVerdict.directorUnchanged,
    "the solve is local to this tab — the Director tab's state is untouched",
  );
  ok(
    /converged|did NOT converge/.test(studioVerdict.status),
    'the convergence flag is on screen, not implied',
    studioVerdict.status,
  );

  console.log('\n[S3] Studio tab — the @-tag divergence is reported, not hidden');
  const greedyTag = await evaluate(`(() => {
    const D = window.__cinematographer.director;
    const DP = window.__cinematographer.directorPanel;
    const SP = window.__cinematographer.studioPanel;
    const scene = document.getElementById('st-scene');
    const compose = (text) => D.composePrompt({
      text, moves: DP.directorState.moves, registry: DP.getRegistry(),
    });
    const clean = compose(SP.SCENE_DEFAULT);
    scene.value = 'A lone astronaut finds a field of flowers on Mars, @tamsincamp in the doorway';
    scene.dispatchEvent(new Event('input', { bubbles: true }));
    const greedy = compose(scene.value);
    const detail = document.getElementById('st-prompt-detail').textContent;
    scene.value = SP.SCENE_DEFAULT;
    scene.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      defaultScene: SP.SCENE_DEFAULT,
      cleanUnresolved: clean.unresolved,
      cleanAttachments: clean.attachments.length,
      panelGreedyUnresolved: greedy.unresolved,
      panelGreedyPrompt: greedy.prompt,
      detail,
    };
  })()`);
  ok(
    !/@/.test(greedyTag.defaultScene),
    'the default scene carries no @tag, so it cannot fail to resolve on any server',
    greedyTag.defaultScene,
  );
  ok(
    greedyTag.cleanUnresolved === 0 && greedyTag.cleanAttachments === 0,
    "the tab's default scene composes clean — a stranger's first Generate is clean",
    `${greedyTag.cleanAttachments} attachment(s), ${greedyTag.cleanUnresolved} unresolved`,
  );
  ok(
    greedyTag.panelGreedyUnresolved === 0 && /<<<image_1>>>/.test(greedyTag.panelGreedyPrompt),
    'the panel reads @tamsincamp non-greedily and resolves it',
    `unresolved=${greedyTag.panelGreedyUnresolved}`,
  );
  ok(
    /engine does not/.test(greedyTag.detail) && /registry/.test(greedyTag.detail),
    'the tab says on screen that the engine resolves against a server registry file, not this list',
  );

  console.log('\n[S4] Studio tab — Generate runs the real graph');
  if (!serverUp) {
    ok(true, `live studio run skipped — ${serverWhy}`,
      'the verdict, the preview and the mapping above are all local and all passed');
  } else {
    // The server publishes its own default registry path; ask it rather than
    // hardcoding one, because `registry_path: ""` is a silent no-op.
    const registryDefault =
      objectInfo?.CinemaElementSave?.input?.optional?.registry_path?.[1]?.default ?? '';
    await evaluate(`(() => {
      const f = document.getElementById('r-base-url');
      f.value = ${JSON.stringify(COMFY)};
      f.dispatchEvent(new Event('input', { bubbles: true }));
      const path = document.getElementById('r-registry-path');
      if (!path.value.trim()) path.value = ${JSON.stringify(registryDefault ?? '')};
      // The tab's own default, untouched: this is what a stranger's first
      // Generate actually sends.
      const SP = window.__cinematographer.studioPanel;
      document.getElementById('st-scene').value = SP.SCENE_DEFAULT;
      document.getElementById('st-scene').dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('st-generate').click();
      return true;
    })()`);
    await waitFor(
      `(() => {
        const s = document.getElementById('st-status').textContent;
        return /taps returned output in this record|it failed|Nothing was sent|does not know|threw|No ComfyUI/.test(s);
      })()`,
      'the studio run to settle',
      180000,
    );

    const studioRun = await evaluate(`(() => {
      const SP = window.__cinematographer.studioPanel;
      const CC = window.__cinematographer.comfyClient;
      const res = SP.lastStudioRun();
      const out = {
        ok: res?.ok ?? false,
        stage: res?.stage ?? null,
        promptId: res?.submit?.prompt_id ?? null,
        nodeErrors: Object.keys(SP.studioNodeErrors()),
        ran: document.getElementById('st-ran').textContent.trim(),
        reconcile: document.getElementById('st-reconcile').textContent.trim(),
        status: document.getElementById('st-status').textContent.trim(),
        taps: [],
        record: null,
      };
      if (res?.ok) {
        out.taps = CC.readTaps(res.record, res.built.taps).map((t) => ({
          key: t.key, ran: t.ran, text: (t.text ?? '').slice(0, 200),
        }));
        out.record = {
          status_str: res.record?.status?.status_str,
          completed: res.record?.status?.completed,
          outputNodes: Object.keys(res.record?.outputs ?? {}),
        };
      }
      return out;
    })()`);

    ok(studioRun.ok, 'the Studio tab really executed the graph', `stage ${studioRun.stage}`);
    ok(studioRun.promptId !== null, 'ComfyUI assigned a prompt_id', studioRun.promptId);
    ok(studioRun.nodeErrors.length === 0, 'node_errors is empty — no node was silently dropped',
      studioRun.nodeErrors.length ? studioRun.nodeErrors.join(',') : '{}');
    ok(studioRun.record?.status_str === 'success' && studioRun.record?.completed === true,
      'the run reports success and completion',
      `status_str "${studioRun.record?.status_str}", completed ${studioRun.record?.completed}`);
    ok(/^7 \/ 7 taps returned output in this record/.test(studioRun.ran),
      'all seven taps returned output — the graph ran whole', studioRun.ran);
    const studioByKey = Object.fromEntries(studioRun.taps.map((t) => [t.key, t.text]));
    ok(!!studioByKey.evaluate && !!studioByKey.corrections && !!studioByKey.final_prompt,
      "the engine returned its own verdict, corrections and prompt",
      studioByKey.evaluate);
    ok(/of \d+ comparable strings are identical/.test(studioRun.reconcile),
      'the panel and the engine were compared, not assumed equal',
      (studioRun.reconcile.match(/\d+ of \d+ comparable strings are identical/) ?? [''])[0]);
    ok(!/partial run/.test(studioRun.status),
      'a clean run is not described as partial', studioRun.status.slice(0, 90));
    ok((studioByKey.unresolved ?? '').trim() === '[]',
      "the tab's default scene came back with nothing unresolved — the first run is clean",
      studioByKey.unresolved);
    ok(/@tags: the panel and the engine agree/.test(studioRun.reconcile),
      'the reconcile card reports the tag comparison, not just the three strings',
      (studioRun.reconcile.match(/@tags:[^.]*\./) ?? [''])[0]);
    await evaluate(`window.__cinematographer.showTab('studio')`);
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
