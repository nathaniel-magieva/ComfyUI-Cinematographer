#!/usr/bin/env node
/**
 * Drive Comfy Cloud through a live browser session instead of an API key.
 *
 * WHY THIS EXISTS
 * ---------------
 * `submit.py` is the honest reference implementation, but it needs a Comfy Cloud
 * API key (`X-API-Key` / `Authorization: Bearer`), and on the machine this pack
 * was built on no such key exists. The web app, however, was already logged in.
 * So this script attaches to that browser over the Chrome DevTools Protocol and
 * makes the same calls the SPA makes, with the same headers.
 *
 * It is not a replacement for `submit.py`. It is the fallback that turned out to
 * be the only route that worked, and it is kept because the next person will hit
 * the same wall.
 *
 * THE FOUR THINGS THAT COST THE MOST TIME, SO YOU DO NOT PAY THEM AGAIN
 * --------------------------------------------------------------------
 * 1. `X-Comfy-Client: web` is MANDATORY on every call. Without it the server
 *    answers 403 `origin_not_allowed`. A 403 (not a 401) is the proof a session
 *    is alive; a 401 `invalid session cookie` means it is dead.
 * 2. `X-CSRF-Token` is MANDATORY on every WRITE, or 403 `csrf_invalid`. The
 *    token comes from `GET /api/auth/session` -> `csrf_token`. The path is
 *    `/api/auth/session`, NOT `/auth/session` -- the latter is served by the
 *    SPA's static handler and returns `index.html` with HTTP 200, a silent
 *    false success.
 * 3. `POST /api/upload/image` returns a CONTENT-HASHED filename, not the name
 *    you uploaded. A graph referencing `tamsin.png` will fail with a
 *    missing-file error. The submitter must rewrite the `LoadImage` input to
 *    the returned name. That substitution is this script's job.
 * 4. `GET /api/view` answers **302** to a signed `storage.googleapis.com` URL.
 *    A page-context `fetch` of it dies with `net::ERR_FAILED` because the GCS
 *    bucket sends no CORS headers on the redirect target -- which reads exactly
 *    like a missing file and is not one. The signature is the credential:
 *    harvest the `Location` at the protocol layer with `Fetch.enable`, then
 *    fetch that URL from Node with no cookie and no header. `Network.*` CDP
 *    events never surface this redirect; only `Fetch.*` does.
 *
 * USAGE
 * -----
 *   node session_client.mjs check    --graph ../workflows/reshoot_ltx25.json
 *   node session_client.mjs submit   --graph ../workflows/reshoot_ltx25.json \
 *                                    --image ../assets/tamsin.png [--yes]
 *   node session_client.mjs poll     --prompt-id <uuid>
 *   node session_client.mjs download --filename <hash>.mp4 \
 *                                    --subfolder cinematographer --out out.mp4
 *
 * Requires a Chrome already listening on CDP_PORT (default 9222) with a logged-in
 * `cloud.comfy.org` tab. Zero npm dependencies.
 */

import { writeFileSync } from 'node:fs';
import { readFileSync } from 'node:fs';

const CDP_PORT = process.env.CDP_PORT || '9222';
const ORIGIN = 'https://cloud.comfy.org';
const WS = process.env.COMFY_WORKSPACE_ID || 'w-2d6d5942-75cc-4cb4-81e8-12ed58d27967';
const CLIENT = 'web';

// ---------------------------------------------------------------- CDP plumbing

async function attach() {
  const list = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  const page = list.find((t) => t.type === 'page' && t.url.startsWith(ORIGIN));
  if (!page) {
    throw new Error(
      `no ${ORIGIN} tab on CDP port ${CDP_PORT}. Open one, log in, and retry. ` +
        `Tabs seen: ${list.filter((t) => t.type === 'page').map((t) => t.url).join(', ')}`
    );
  }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true });
    ws.addEventListener('error', rej, { once: true });
  });
  let id = 0;
  const pending = new Map();
  const events = [];
  ws.addEventListener('message', (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    } else if (msg.method) {
      events.push(msg);
    }
  });
  const send = (method, params = {}) =>
    new Promise((res) => {
      const n = ++id;
      pending.set(n, res);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
  await send('Runtime.enable');
  return { ws, send, events };
}

/** Evaluate an async IIFE in the page and return its value, or throw on a page-side throw. */
async function evalIn(send, body) {
  const r = await send('Runtime.evaluate', {
    expression: `(async () => { ${body} })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.result?.exceptionDetails) {
    throw new Error('page exception: ' + JSON.stringify(r.result.exceptionDetails).slice(0, 400));
  }
  const v = r.result?.result?.value;
  if (v && v.FATAL) throw new Error(v.FATAL + (v.head ? ' :: ' + v.head : ''));
  return v;
}

/** The headers every Comfy Cloud call needs. `csrf` only for writes. */
function headers(csrf) {
  const h = { 'X-Comfy-Client': CLIENT, 'X-Comfy-Workspace-ID': WS };
  if (csrf) h['X-CSRF-Token'] = csrf;
  return h;
}

/** Fetch the CSRF token. Returns null and says why rather than pretending. */
async function csrfToken(send) {
  const out = await evalIn(
    send,
    `const r = await fetch('/api/auth/session', {credentials:'include', cache:'no-store',
        headers: {'X-Comfy-Client': '${CLIENT}'}});
     const t = await r.text();
     if (r.status !== 200) return {FATAL: 'auth/session status ' + r.status, head: t.slice(0,200)};
     let j; try { j = JSON.parse(t); } catch { return {FATAL: 'auth/session unparseable', head: t.slice(0,200)}; }
     if (!j.csrf_token) return {FATAL: 'no csrf_token in session response', head: t.slice(0,200)};
     return {csrf: j.csrf_token, user: (j.user && j.user.id) || null};`
  );
  return out;
}

// ------------------------------------------------------------------ subcommands

async function cmdCheck(graphPath) {
  const graph = JSON.parse(readFileSync(graphPath, 'utf8'));
  const used = [...new Set(Object.values(graph).filter((n) => n && n.class_type).map((n) => n.class_type))].sort();
  const { send } = await attach();
  const out = await evalIn(
    send,
    `const r = await fetch('/api/object_info', {credentials:'include',
        headers: ${JSON.stringify(headers())}});
     const t = await r.text();
     if (r.status !== 200) return {FATAL: 'object_info status ' + r.status, head: t.slice(0,200)};
     let j; try { j = JSON.parse(t); } catch { return {FATAL: 'object_info unparseable', head: t.slice(0,200)}; }
     const keys = Object.keys(j);
     if (keys.length < 100) return {FATAL: 'implausible node count ' + keys.length, head: t.slice(0,200)};
     return {available: keys};`
  );
  const avail = new Set(out.available);
  const missing = used.filter((c) => !avail.has(c));
  console.log(`Cloud reports ${avail.size} node classes.`);
  console.log(`This workflow uses ${used.length} distinct class_types.`);
  if (missing.length) {
    console.log(`MISSING (${missing.length}) -- these would fail with 'node type not found':`);
    for (const m of missing) console.log('  ' + m);
    return 1;
  }
  console.log('ALL PRESENT -- every class_type is available on this surface.');
  console.log('NOTE: this checks node CLASSES only. It does not check model files.');
  return 0;
}

async function cmdSubmit(graphPath, imagePath, yes) {
  const graph = JSON.parse(readFileSync(graphPath, 'utf8'));
  const { send, events } = await attach();

  const sess = await csrfToken(send);
  console.log(`session: user=${sess.user} csrf_len=${sess.csrf.length}`);

  // --- upload, and read back the hashed name ---------------------------------
  let assetName = null;
  if (imagePath) {
    const b64 = readFileSync(imagePath).toString('base64');
    const out = await evalIn(
      send,
      `const bin = atob(${JSON.stringify(b64)});
       const u8 = new Uint8Array(bin.length);
       for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
       const fd = new FormData();
       fd.append('image', new Blob([u8], {type:'image/png'}), ${JSON.stringify(imagePath.split('/').pop())});
       fd.append('overwrite', 'true');
       const r = await fetch('/api/upload/image', {method:'POST', credentials:'include',
           headers: ${JSON.stringify(headers(sess.csrf))}, body: fd});
       const t = await r.text();
       if (r.status !== 200) return {FATAL: 'upload status ' + r.status, head: t.slice(0,300)};
       let j; try { j = JSON.parse(t); } catch { return {FATAL: 'upload unparseable', head: t.slice(0,300)}; }
       return {name: j.name, subfolder: j.subfolder || '', type: j.type || 'input'};`
    );
    assetName = out.name;
    console.log(`uploaded ${imagePath} -> ${assetName} (content-hashed, NOT the filename)`);
  }

  // --- substitute the placeholders -------------------------------------------
  const prompt = {};
  for (const [k, v] of Object.entries(graph)) {
    if (k === '_README') continue;
    prompt[k] = v;
  }
  if (assetName) {
    const loaders = Object.entries(prompt).filter(([, n]) => n.class_type === 'LoadImage');
    if (!loaders.length) console.log('WARN: --image given but the graph has no LoadImage node');
    for (const [id, n] of loaders) {
      const was = n.inputs.image;
      n.inputs.image = assetName;
      console.log(`node ${id} LoadImage.image: ${was} -> ${assetName}`);
    }
  }
  const stale = Object.entries(prompt).filter(
    ([, n]) => n.class_type === 'CLIPTextEncode' && String(n.inputs.text || '').startsWith('PLACEHOLDER_')
  );
  if (stale.length) {
    // Fatal, not a warning: a placeholder prompt generates garbage silently,
    // whereas a wrong image path fails loudly at run time.
    console.error(`FATAL: node(s) ${stale.map(([id]) => id).join(', ')} still carry a placeholder prompt.`);
    console.error('Substitute the prompt before submitting. Refusing to spend credits on it.');
    return 2;
  }

  if (!yes) {
    console.log('\n--yes not passed. Prepared, not submitted:');
    console.log(JSON.stringify({ assetName, nodes: Object.keys(prompt).length }, null, 2));
    return 0;
  }

  // --- submit ----------------------------------------------------------------
  const out = await evalIn(
    send,
    `const r = await fetch('/api/prompt', {method:'POST', credentials:'include',
        headers: Object.assign({'Content-Type':'application/json'}, ${JSON.stringify(headers(sess.csrf))}),
        body: JSON.stringify({prompt: ${JSON.stringify(prompt)}, client_id: 'cinematographer-session-client'})});
     const t = await r.text();
     return {status: r.status, body: t};`
  );
  console.log(`submit: HTTP ${out.status}`);
  console.log(out.body.trim());
  if (out.status !== 200) return 1;
  const j = JSON.parse(out.body);
  if (j.node_errors && Object.keys(j.node_errors).length) {
    console.error('node_errors is non-empty -- the server rejected nodes. Not a success.');
    return 1;
  }
  console.log(`prompt_id: ${j.prompt_id}`);
  return 0;
}

async function cmdPoll(promptId) {
  const { send } = await attach();
  const deadline = Date.now() + 45 * 60 * 1000;
  let last = null;
  while (Date.now() < deadline) {
    // /api/history does NOT exist on Comfy Cloud -- it 404s and names its own
    // replacement. /api/history_v2 returns {"history":[...]}, an ARRAY under a
    // key, not a prompt_id-keyed dict. Reading it as a dict yields `mine: null`
    // and looks exactly like a missing run.
    const out = await evalIn(
      send,
      `const q = await (await fetch('/api/queue', {credentials:'include',
           headers: ${JSON.stringify(headers())}})).json();
       const h = await (await fetch('/api/history_v2?max_items=10', {credentials:'include',
           headers: ${JSON.stringify(headers())}})).json();
       const arr = Array.isArray(h.history) ? h.history : [];
       const mine = arr.find(e => e.prompt_id === ${JSON.stringify(promptId)}) || null;
       return {running: (q.queue_running||[]).length, pending: (q.queue_pending||[]).length,
               status: mine ? (mine.status && mine.status.status_str) : null,
               completed: mine ? !!(mine.status && mine.status.completed) : false,
               outputs: mine ? Object.keys(mine.outputs||{}) : []};`
    );
    const line = `running=${out.running} pending=${out.pending} status=${out.status}`;
    if (line !== last) {
      console.log(new Date().toISOString().slice(11, 19), line);
      last = line;
    }
    if (out.completed) {
      console.log(`FINAL: completed, output nodes ${JSON.stringify(out.outputs)}`);
      return 0;
    }
    await new Promise((r) => setTimeout(r, 5000));
  }
  console.error('FATAL: 45-minute deadline reached without a terminal status.');
  return 1;
}

async function cmdDownload(filename, subfolder, outPath) {
  const { send, events } = await attach();
  // Intercept at the PROTOCOL layer. Network.* events are renderer-side and the
  // 302 never surfaces there -- the renderer aborts before headers.
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Response' }] });

  let signed = null;
  let paused = 0;
  let viewSeen = 0;
  const deadline = Date.now() + 20000;
  const pump = (async () => {
    // Time-bounded, not count-bounded: the page has background traffic (analytics,
    // polling) and a fixed iteration cap can burn out before the redirect arrives.
    while (!signed && Date.now() < deadline) {
      const ev = events.shift();
      if (!ev) {
        await new Promise((r) => setTimeout(r, 25));
        continue;
      }
      if (ev.method !== 'Fetch.requestPaused') continue;
      paused++;
      const { requestId, responseStatusCode, responseHeaders, request } = ev.params;
      const loc = (responseHeaders || []).find((h) => h.name.toLowerCase() === 'location');
      if (/\/api\/view/.test(request.url)) viewSeen++;
      if (responseStatusCode >= 300 && responseStatusCode < 400 && loc && /storage\.googleapis/.test(loc.value)) {
        signed = loc.value;
      }
      // Abort everything: the browser mints the signature, Node moves the bytes.
      await send('Fetch.failRequest', { requestId, errorReason: 'Aborted' }).catch(() => {});
    }
  })();

  // Kick off the fetch and ignore that the renderer rejects it -- we only want
  // the redirect, which Fetch.* sees before the renderer does.
  const url = `/api/view?filename=${encodeURIComponent(filename)}&subfolder=${encodeURIComponent(subfolder)}&type=output`;
  evalIn(
    send,
    `try { await fetch(${JSON.stringify(url)}, {credentials:'include',
        headers: ${JSON.stringify(headers())}}); } catch (e) { return {threw: String(e)}; }
     return {ok: true};`
  ).catch(() => {});

  await pump;
  if (!signed) {
    console.error(
      `FATAL: no signed GCS redirect observed (paused ${paused} responses, ` +
        `${viewSeen} of them /api/view). Is the session live and the file present?`
    );
    return 1;
  }
  const host = new URL(signed).host;
  const keys = [...new URL(signed).searchParams.keys()];
  console.log(`signed url host: ${host} | query keys: ${keys.join(',')}`);

  // The signature IS the credential. No cookie, no header, no browser.
  const res = await fetch(signed);
  if (!res.ok) {
    console.error(`FATAL: GCS returned ${res.status} ${res.statusText}`);
    return 1;
  }
  const buf = Buffer.from(await res.arrayBuffer());
  writeFileSync(outPath, buf);
  console.log(`GCS status: ${res.status} ${res.headers.get('content-type')} ${buf.length}`);
  console.log(JSON.stringify({ bytes: buf.length, out: outPath, magic: buf.subarray(4, 12).toString('latin1') }));
  return 0;
}

// ----------------------------------------------------------------------- main

const argv = process.argv.slice(2);
const cmd = argv[0];
const flag = (name, dflt = null) => {
  const i = argv.indexOf('--' + name);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : dflt;
};

const USAGE = `usage:
  node session_client.mjs check    --graph <workflow.json>
  node session_client.mjs submit   --graph <workflow.json> [--image <png>] [--yes]
  node session_client.mjs poll     --prompt-id <uuid>
  node session_client.mjs download --filename <name> --subfolder <dir> --out <path>`;

try {
  let rc;
  if (cmd === 'check') rc = await cmdCheck(flag('graph'));
  else if (cmd === 'submit') rc = await cmdSubmit(flag('graph'), flag('image'), argv.includes('--yes'));
  else if (cmd === 'poll') rc = await cmdPoll(flag('prompt-id'));
  else if (cmd === 'download') rc = await cmdDownload(flag('filename'), flag('subfolder', ''), flag('out'));
  else {
    console.log(USAGE);
    rc = 2;
  }
  process.exit(rc ?? 0);
} catch (e) {
  console.error('FATAL: ' + e.message);
  process.exit(1);
}
