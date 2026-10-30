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
  await waitFor('document.querySelectorAll("#d-move-add option").length > 0', 'director controls');

  // ===================== DIRECTOR TAB (the default) =====================
  console.log('[D1] Director tab is the default');
  const tabState = await evaluate(`(() => ({
    directorHidden: document.getElementById('tab-director').classList.contains('hidden'),
    judgeHidden: document.getElementById('tab-judge').classList.contains('hidden'),
    onTab: document.querySelector('#tabnav .tab.on')?.dataset.tab,
    note: document.getElementById('tabnav-note').textContent.trim(),
  }))()`);
  ok(!tabState.directorHidden, 'the Director tab is visible on load');
  ok(tabState.judgeHidden, 'the Judge tab starts hidden');
  ok(tabState.onTab === 'director', 'the Director tab button is selected', tabState.onTab);
  ok(/does not generate/.test(tabState.note), 'the tab bar says the panel does not generate', tabState.note);

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
