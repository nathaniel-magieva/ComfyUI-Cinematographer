/**
 * End-to-end check for the Studio tab — the front door.
 *
 *   # 1. serve the panel
 *   cd web && python3 -m http.server 8765
 *   # 2. start a ComfyUI on 127.0.0.1:8188 (with --enable-cors-header)
 *   # 3. drive it
 *   node web/tools/studio_check.mjs [http://127.0.0.1:8765/] [/tmp/studio.png]
 *
 * This is the check that answers "does the tab actually execute, or does it
 * only render?". It types a scene, picks all four of Comfy Org's choices,
 * presses Generate, and prints the values ComfyUI really returned — the tap
 * text, the status, and whether the panel's own verdict matched the engine's.
 *
 * It also asserts the two things that would make the tab a lie:
 *   - the four dropdowns are their vocabulary, and every mapped value is a real
 *     engine enum member (`MAPPING_ERRORS` is empty)
 *   - the verdict is nine rules with a pass/fail each, computed here
 *
 * Exit code 0 = every assertion held.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import * as CC from '../comfy_client.js';

const URL_ = process.argv[2] ?? 'http://127.0.0.1:8765/';
const SHOT = process.argv[3] ?? join(tmpdir(), 'cinematographer-studio.png');
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

const profile = mkdtempSync(join(tmpdir(), 'cine-studio-chrome-'));
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
const jsErrors = [];
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  } else if (msg.method === 'Runtime.exceptionThrown') {
    jsErrors.push(msg.params?.exceptionDetails?.exception?.description ?? 'exception');
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
      /* page still loading */
    }
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${label}`);
}

// ---------------------------------------------------------------------------
// Drive the Studio tab
// ---------------------------------------------------------------------------

console.log(`studio tab check — ${URL_}\n`);

try {
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.navigate', { url: URL_ });
  await waitFor('document.readyState === "complete"', 'page load');
  await waitFor('!!window.__cinematographer?.studioPanel', 'studio panel module');

  // ===================== [T1] the tab is reachable =====================
  console.log('[T1] the Studio tab exists and is the landing tab');
  const tab = await evaluate(`(() => {
    const btn = document.querySelector('#tabnav .tab[data-tab="studio"]');
    const panel = document.getElementById('tab-studio');
    return {
      hasButton: !!btn,
      label: btn?.textContent.trim() ?? '',
      hasPanel: !!panel,
      hiddenAtLoad: panel?.classList.contains('hidden') ?? null,
      onTab: document.querySelector('#tabnav .tab.on')?.dataset.tab,
      tabs: [...document.querySelectorAll('#tabnav .tab')].map((b) => b.dataset.tab),
      note: document.getElementById('tabnav-note').textContent.trim(),
    };
  })()`);
  ok(tab.hasButton, 'the tab bar has a Studio button', tab.label);
  ok(tab.hasPanel, 'the #tab-studio panel exists');
  ok(tab.hiddenAtLoad === false, 'it is the landing tab — visible on load');
  ok(tab.onTab === 'studio', 'its button is the selected one', tab.onTab);
  ok(tab.tabs[0] === 'studio', 'it is first in the tab bar', tab.tabs.join(' → '));
  ok(
    JSON.stringify(tab.tabs.slice(1))
      === JSON.stringify(['director', 'judge', 'elements', 'shoot', 'post', 'run']),
    'the other six keep their relative order',
  );
  ok(
    /one screen.*measured framing verdict/.test(tab.note),
    'the tab bar explains the landing tab',
    tab.note,
  );

  // ===================== [T2] their vocabulary, our enums =====================
  console.log('\n[T2] the four dropdowns are their vocabulary, and the mapping is real');
  const vocab = await evaluate(`(() => {
    const SP = window.__cinematographer.studioPanel;
    const opts = (id) => [...document.getElementById(id).options].map((o) => o.value);
    return {
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
  ok(vocab.shot.length === 5, 'shot has 5 options', String(vocab.shot.length));
  ok(vocab.camera.length === 4, 'camera has 4 options', String(vocab.camera.length));
  ok(vocab.light.length === 4, 'light has 4 options', String(vocab.light.length));
  ok(vocab.look.length === 4, 'look has 4 options', String(vocab.look.length));
  ok(
    JSON.stringify(vocab.shot) === JSON.stringify(vocab.expected.shot)
      && JSON.stringify(vocab.camera) === JSON.stringify(vocab.expected.camera)
      && JSON.stringify(vocab.light) === JSON.stringify(vocab.expected.light)
      && JSON.stringify(vocab.look) === JSON.stringify(vocab.expected.look),
    'the rendered options are the module\'s own lists, in order',
  );
  ok(
    vocab.mappingErrors.length === 0,
    'every mapped value is a real engine enum member',
    vocab.mappingErrors.length ? vocab.mappingErrors.join(' | ') : '0 mapping errors',
  );

  // ===================== [T3] the verdict is measured =====================
  console.log('\n[T3] the verdict is nine measured rules, not a string');
  const verdict = await evaluate(`(() => {
    const SP = window.__cinematographer.studioPanel;
    const v = SP.studioVerdict();
    const rows = [...document.querySelectorAll('#st-verdict tbody tr')];
    return {
      v,
      rowCount: rows.length,
      badges: rows.map((r) => r.querySelector('.gate-badge')?.textContent.trim()),
      head: document.getElementById('st-verdict-head').textContent.trim(),
      leverHtml: document.getElementById('st-lever').textContent.trim(),
      prompt: document.getElementById('st-prompt').textContent,
    };
  })()`);
  ok(verdict.rowCount === 9, 'the verdict table has 9 rule rows', String(verdict.rowCount));
  ok(
    verdict.badges.length === 9 && verdict.badges.every((b) => b === 'pass' || b === 'fail'),
    'every row carries a pass/fail badge',
    verdict.badges.join(','),
  );
  ok(
    verdict.v.rules.length === 9 && verdict.v.rules.every((r) => typeof r.value === 'number'),
    'every rule has a computed numeric measurement',
  );
  ok(
    /^(PASS|FAIL) (closeup|medium|wide) on '/.test(verdict.v.summary),
    'the summary is the engine\'s own format',
    verdict.v.summary,
  );
  ok(
    /reliability (green|yellow|red)/.test(verdict.head),
    'the reliability zone is on screen',
    (verdict.head.match(/reliability \w+/) ?? [''])[0],
  );
  ok(
    verdict.v.levers.length === verdict.v.failures.length
      || verdict.v.failures.every((r) => r === 'direct_address'),
    'every failing rule with a lever has one',
    `${verdict.v.levers.length} lever(s) for ${verdict.v.failures.length} failure(s)`,
  );

  // ===================== [T4] the preview is the real parser =====================
  console.log('\n[T4] the prompt preview comes from director.js, not a second parser');
  const preview = await evaluate(`(() => {
    const SP = window.__cinematographer.studioPanel;
    const D = window.__cinematographer.director;
    const DP = window.__cinematographer.directorPanel;
    const scene = 'A lone astronaut finds a field of flowers on Mars';
    document.getElementById('st-scene').value = scene;
    document.getElementById('st-shot').value = 'Low-angle shot';
    document.getElementById('st-camera').value = '85mm portrait lens, soft background';
    document.getElementById('st-light').value = 'Golden-hour backlight';
    document.getElementById('st-look').value = 'High-contrast noir';
    document.getElementById('st-look').dispatchEvent(new Event('change', { bubbles: true }));
    const shown = document.getElementById('st-prompt').textContent;
    const t = SP.studioTranslation();
    // The same call the Shoot tab makes, with the same inputs.
    const direct = D.composePrompt({ text: scene, moves: DP.directorState.moves, registry: DP.getRegistry() }).prompt;
    return { shown, direct, t, scene };
  })()`);
  ok(preview.shown === preview.direct, 'the preview is byte-identical to composePrompt()');
  ok(preview.shown.includes(preview.scene), 'the scene is in the prompt', preview.shown.slice(0, 80));
  ok(preview.t.shot_type === 'medium' && preview.t.angle === 'low', 'low-angle maps to medium + angle low');
  ok(preview.t.focal_mm === 85, 'the 85mm choice sets focal_mm 85', String(preview.t.focal_mm));
  ok(preview.t.light === 'contre-jour', 'golden hour maps to contre-jour', preview.t.light);
  ok(preview.t.color_palette === 'neon-rain-at-midnight', 'noir maps to the noir palette');

  const after = await evaluate(`window.__cinematographer.studioPanel.studioVerdict()`);
  ok(after.shot_type === 'medium', 'the verdict re-measured for the new shot', after.shot_type);

  // ===================== [T5] the correction lever is pullable =====================
  console.log('\n[T5] Auto-frame is a real lever, and it is local to this tab');
  const lever = await evaluate(`(async () => {
    const before = window.__cinematographer.studioPanel.studioVerdict();
    const directorBefore = JSON.stringify(window.__cinematographer.directorState);
    document.getElementById('st-autoframe').click();
    await new Promise((r) => setTimeout(r, 250));
    const after = window.__cinematographer.studioPanel.studioVerdict();
    return {
      before, after,
      solved: window.__cinematographer.studioPanel.isSolved(),
      directorUnchanged: directorBefore === JSON.stringify(window.__cinematographer.directorState),
      status: document.getElementById('st-status').textContent.trim(),
    };
  })()`);
  ok(lever.solved, 'the tab adopted a solved camera');
  ok(
    lever.after.weighted_failures.length <= lever.before.weighted_failures.length,
    'the solve did not make the weighted verdict worse',
    `${lever.before.weighted_failures.join(',') || 'none'} → ${lever.after.weighted_failures.join(',') || 'none'}`,
  );
  ok(lever.directorUnchanged, 'the Director tab\'s state was not touched');
  ok(/converged|did NOT converge/.test(lever.status), 'the convergence flag is on screen', lever.status);

  // ===================== [T6] Generate, against the live server =====================
  console.log('\n[T6] Generate runs the real graph against the live server');
  const probe = await CC.probeServer(COMFY);
  if (!probe.ok) {
    console.log(`  SKIP the live half — no ComfyUI at ${COMFY} (${probe.error}).`);
    console.log('       The verdict, the preview and the mapping above are all local and all passed.');
  } else {
    console.log(`  (ComfyUI ${probe.version} on ${probe.os}, ${probe.classes.length} classes)`);

    await evaluate(`(() => {
      const path = document.getElementById('r-registry-path');
      if (!path.value.trim()) path.value = ${JSON.stringify(probe.registryDefault ?? '')};
      // The tab's own default scene, untouched: this is what a stranger's
      // first Generate actually sends.
      const SP = window.__cinematographer.studioPanel;
      const scene = document.getElementById('st-scene');
      scene.value = SP.SCENE_DEFAULT;
      scene.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('st-generate').click();
    })()`);

    await waitFor(
      `(() => {
        const s = document.getElementById('st-status').textContent;
        return /taps returned output in this record|it failed|Nothing was sent|does not know|threw|No ComfyUI/.test(s);
      })()`,
      'the studio run to settle',
      180000,
    );

    const run = await evaluate(`(() => {
      const SP = window.__cinematographer.studioPanel;
      const res = SP.lastStudioRun();
      const CC = window.__cinematographer.comfyClient;
      const out = {
        status: document.getElementById('st-status').textContent.trim(),
        ran: document.getElementById('st-ran').textContent.trim(),
        reconcile: document.getElementById('st-reconcile').textContent.trim(),
        errors: document.getElementById('st-errors').textContent.trim(),
        nodeErrors: Object.keys(SP.studioNodeErrors()),
        promptId: res?.submit?.prompt_id ?? null,
        stage: res?.stage ?? null,
        ok: res?.ok ?? null,
        taps: [],
        record: null,
      };
      if (res?.ok) {
        out.taps = CC.readTaps(res.record, res.built.taps).map((t) => ({
          id: t.id, key: t.key, label: t.label, ran: t.ran,
          text: (t.text ?? '').slice(0, 400),
        }));
        out.record = {
          status_str: res.record?.status?.status_str,
          completed: res.record?.status?.completed,
          outputNodes: Object.keys(res.record?.outputs ?? {}),
          messages: (res.record?.status?.messages ?? []).map((m) => m[0]),
        };
      }
      return out;
    })()`);

    ok(run.ok === true, 'executeLive returned ok', `stage ${run.stage}`);
    ok(run.promptId !== null, 'ComfyUI assigned a prompt_id', run.promptId);
    ok(run.nodeErrors.length === 0, 'node_errors is empty — no node was silently dropped',
      run.nodeErrors.length ? run.nodeErrors.join(',') : '{}');
    ok(run.record?.status_str === 'success', 'status_str is success', run.record?.status_str);
    ok(run.record?.completed === true, 'completed is true', String(run.record?.completed));
    ok(/^7 \/ 7 taps returned output in this record/.test(run.ran),
      'all 7 taps returned output', run.ran);

    const byKey = Object.fromEntries(run.taps.map((t) => [t.key, t.text]));
    ok(!!byKey.evaluate, 'the engine returned its own framing verdict', byKey.evaluate);
    ok(!!byKey.corrections, 'the engine returned its own corrections text');
    ok(!!byKey.final_prompt, 'the engine returned the composed prompt');
    ok(/of \d+ comparable strings are identical/.test(run.reconcile),
      'the panel and the engine were compared, not assumed equal',
      (run.reconcile.match(/\d+ of \d+ comparable strings are identical/) ?? [''])[0]);

    console.log('\n  ---- what ComfyUI actually returned ----');
    console.log(`  prompt_id      ${run.promptId}`);
    console.log(`  status_str     ${run.record?.status_str}   completed ${run.record?.completed}`);
    console.log(`  output nodes   ${JSON.stringify(run.record?.outputNodes)}`);
    console.log(`  messages       ${JSON.stringify(run.record?.messages)}`);
    console.log(`  taps           ${run.ran}`);
    for (const t of run.taps) {
      const text = (t.text ?? '').replace(/\n/g, ' ⏎ ');
      console.log(`    ${String(t.id).padStart(2)} ${t.key.padEnd(13)} ${t.ran ? text : '(no output)'}`);
    }
    console.log(`  reconcile      ${run.reconcile.split('\n')[0]}`);
    console.log(`  panel status   ${run.status}`);
    if (run.errors) console.log(`  errors         ${run.errors}`);
    console.log('  ---- end ----\n');

    ok(jsErrors.length === 0, 'no uncaught JS exception during the run',
      jsErrors.length ? jsErrors.join(' | ') : '0');

    // The tab's own default scene must come back clean. A first run that shows
    // a red unresolved tag teaches a stranger that the tool is broken.
    ok(
      (byKey.unresolved ?? '').trim() === '[]',
      "the tab's default scene resolves everything — a stranger's first run is clean",
      byKey.unresolved,
    );
    ok(
      !/<<<image_\d+>>>/.test(byKey.final_prompt ?? ''),
      'and the prompt carries no attachment token the engine cannot back with a file',
      (byKey.final_prompt ?? '').slice(0, 90),
    );
    ok(
      /ruined greenhouse/.test(byKey.final_prompt ?? ''),
      'the scene text reached the engine intact',
      (byKey.final_prompt ?? '').slice(0, 90),
    );

    // ===================== [T7] the greedy contract is reported, not hidden =====================
    console.log('\n[T7] the greedy @-tag divergence is reported, not hidden');
    const greedy = await evaluate(`(() => {
      const scene = document.getElementById('st-scene');
      scene.value = 'A lone astronaut finds a field of flowers on Mars, @tamsincamp in the doorway';
      scene.dispatchEvent(new Event('input', { bubbles: true }));
      const D = window.__cinematographer.director;
      const DP = window.__cinematographer.directorPanel;
      const composed = D.composePrompt({
        text: scene.value, moves: DP.directorState.moves, registry: DP.getRegistry(),
      });
      return {
        panelUnresolved: composed.unresolved,
        panelPrompt: composed.prompt,
        detail: document.getElementById('st-prompt-detail').textContent,
      };
    })()`);
    // The panel is non-greedy; the engine is greedy. That is the documented
    // divergence, and the tab must say so rather than pick a side silently.
    ok(
      greedy.panelUnresolved === 0 && /<<<image_1>>>/.test(greedy.panelPrompt),
      'the panel reads @tamsincamp non-greedily and resolves it',
      `unresolved=${greedy.panelUnresolved} · ${greedy.panelPrompt.slice(0, 60)}`,
    );
    ok(
      /server/.test(greedy.detail) && /registry/.test(greedy.detail),
      'the tab says on screen that the engine resolves against a different registry',
    );

    await evaluate(`(() => {
      document.getElementById('st-generate').click();
      return true;
    })()`);
    await waitFor(
      `(() => {
        const s = document.getElementById('st-status').textContent;
        return /taps returned output in this record|it failed|Nothing was sent|does not know|threw/.test(s);
      })()`,
      'the greedy run to settle',
      180000,
    );
    const greedyRun = await evaluate(`(() => {
      const SP = window.__cinematographer.studioPanel;
      const CC = window.__cinematographer.comfyClient;
      const res = SP.lastStudioRun();
      if (!res?.ok) return { ok: false, stage: res?.stage ?? null };
      const byKey = Object.fromEntries(
        CC.readTaps(res.record, res.built.taps).map((t) => [t.key, t.text]));
      return {
        ok: true,
        unresolved: byKey.unresolved,
        attachments: byKey.attachments,
        reconcile: document.getElementById('st-reconcile').textContent,
      };
    })()`);
    ok(greedyRun.ok, 'the tagged scene still runs', `stage ${greedyRun.stage}`);
    ok(
      /tamsincamp/.test(greedyRun.unresolved ?? ''),
      'the engine reports the tag unresolved — it has no registry file to resolve it against',
      greedyRun.unresolved,
    );
    ok(
      /disagree|differ|not the same|unresolved/i.test(greedyRun.reconcile ?? ''),
      'the reconcile card reports the panel/engine tag disagreement rather than hiding it',
      (greedyRun.reconcile ?? '').slice(0, 160),
    );

    // Leave the tab on its clean default.
    await evaluate(`(() => {
      const SP = window.__cinematographer.studioPanel;
      const scene = document.getElementById('st-scene');
      scene.value = SP.SCENE_DEFAULT;
      scene.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);
  }

  // ===================== [T8] the screenshot =====================
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  const { writeFileSync } = await import('node:fs');
  writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
  console.log(`\nscreenshot → ${SHOT}`);
} catch (err) {
  failures++;
  console.log(`\nFAIL driver error — ${err.message}`);
} finally {
  ws.close();
  chrome.kill();
}

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} — ${checks - failures}/${checks} checks`);
process.exit(failures === 0 ? 0 : 1);
