/**
 * Screenshot every tab of the panel, so a reviewer can see all five stages
 * without clicking. Same CDP approach as browser_check.mjs, no npm deps.
 *
 *   cd web && python3 -m http.server 8765
 *   node web/tools/shoot_tabs.mjs http://127.0.0.1:8765/ /tmp/tabs
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const URL_ = process.argv[2] ?? 'http://127.0.0.1:8765/';
const OUT = process.argv[3] ?? '/tmp/tabs';
mkdirSync(OUT, { recursive: true });

const chromePath = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
].filter(Boolean).find((p) => existsSync(p));
if (!chromePath) { console.log('SKIP — no Chrome found.'); process.exit(0); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), 'cine-tabs-'));
const chrome = spawn(chromePath, [
  '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
  '--enable-unsafe-swiftshader', '--use-gl=angle', '--use-angle=swiftshader',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--window-size=1600,1500', 'about:blank',
], { stdio: 'ignore' });

const portFile = join(profile, 'DevToolsActivePort');
let port = null;
for (let i = 0; i < 100; i++) {
  if (existsSync(portFile)) { port = readFileSync(portFile, 'utf8').split('\n')[0].trim(); if (port) break; }
  await sleep(100);
}
if (!port) { chrome.kill(); console.log('SKIP — no debug port.'); process.exit(0); }

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener('open', res, { once: true });
  ws.addEventListener('error', rej, { once: true });
});

let id = 0;
const pending = new Map();
const events = [];
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else if (m.method) events.push(m);
});
const send = (method, params = {}) => new Promise((res) => {
  const n = ++id; pending.set(n, res);
  ws.send(JSON.stringify({ id: n, method, params }));
});
const evalJs = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return r.result?.result?.value;
};

await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: URL_ });
await sleep(3500);

const errors = events
  .filter((e) => e.method === 'Runtime.exceptionThrown')
  .map((e) => e.params.exceptionDetails?.exception?.description ?? 'unknown');
console.log(`JS errors on load: ${errors.length}`);
for (const e of errors) console.log('  ' + e.split('\n')[0]);

const tabs = await evalJs(`JSON.stringify([...document.querySelectorAll('#tabnav .tab')].map(t => t.dataset.tab))`);
const names = JSON.parse(tabs ?? '[]');
console.log(`tabs found: ${names.join(', ')}`);

for (const name of names) {
  await evalJs(`document.querySelector('#tabnav .tab[data-tab="${name}"]').click()`);
  await sleep(1400);
  const note = await evalJs(`document.getElementById('tabnav-note')?.textContent ?? ''`);
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  const file = join(OUT, `${name}.png`);
  writeFileSync(file, Buffer.from(shot.result.data, 'base64'));
  const bytes = readFileSync(file).length;
  console.log(`  ${name.padEnd(9)} -> ${file}  (${bytes} B)  note: ${note}`);
}

chrome.kill();
console.log('done');
process.exit(0);
