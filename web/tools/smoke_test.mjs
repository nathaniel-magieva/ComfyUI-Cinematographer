/**
 * Headless smoke test for the director's panel.
 *
 *   node web/tools/smoke_test.mjs
 *
 * It drives the *real* panel pipeline (`panel_state.js` → `cinematographer.js`),
 * not a copy, and checks the acceptance criteria that do not need a browser:
 *
 *   1. every DOM id `app.js` queries exists in `index.html`
 *   2. the rule panel has all 9 rules, in order, with the spec's weights
 *   3. the default frame is imperfect (the demo needs something to fix)
 *   4. Auto-Frame converges and the panel then reports overall PASS
 *   5. the panel's re-derived report matches the solver's own report
 *   6. the continuity strip flags a jump cut and an axis cross by default
 *   7. the reliability badge moves green → yellow → red with azimuth
 *   8. orbit ↔ pose round-trips, and the camera's target always projects to NDC (0,0)
 *
 * Exit code 0 = all checks passed.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import * as C from '../cinematographer.js';
import * as P from '../panel_state.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, '..');

let failures = 0;
let checks = 0;

function ok(cond, label, detail = '') {
  checks++;
  if (cond) {
    console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`);
  } else {
    failures++;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function near(a, b, tol = 1e-9) {
  return Math.abs(a - b) <= tol;
}

// ---------------------------------------------------------------------------
console.log('panel smoke test\n');

// 1. DOM ids ---------------------------------------------------------------
console.log('[1] index.html ↔ app.js wiring');
const html = readFileSync(resolve(WEB, 'index.html'), 'utf8');
const appjs = readFileSync(resolve(WEB, 'app.js'), 'utf8');

const queried = new Set();
for (const m of appjs.matchAll(/\$\('([^']+)'\)/g)) queried.add(m[1]);
for (const m of appjs.matchAll(/getElementById\('([^']+)'\)/g)) queried.add(m[1]);

const htmlIds = new Set();
for (const m of html.matchAll(/\bid="([^"]+)"/g)) htmlIds.add(m[1]);

const missing = [...queried].filter((id) => !htmlIds.has(id));
ok(missing.length === 0, `all ${queried.size} queried element ids exist`, missing.join(', '));
ok(html.includes('./styles.css'), 'index.html links styles.css');
ok(html.includes('./app.js'), 'index.html loads app.js as a module');
ok(/type="module"/.test(html), 'app.js is loaded as type="module"');

// 2. the nine rules --------------------------------------------------------
console.log('\n[2] rule panel shape');
const state = P.createState();
let data = P.compute(state);
ok(data.report.scores.length === 9, 'nine rules are evaluated', `${data.report.scores.length}`);
ok(
  data.report.scores.map((s) => s.rule).join(',') === C.FRAMING_RULES.join(','),
  'rules are in the engine order',
  data.report.scores.map((s) => s.rule).join(','),
);
const weightsOk = data.report.scores.every(
  (s) => s.weight === (C.RULE_WEIGHTS[state.shotType][s.rule] ?? 0),
);
ok(weightsOk, `weights match RULE_WEIGHTS['${state.shotType}']`);
ok(
  data.report.scores.every((s) => Number.isFinite(s.value)),
  'every measured value is a finite number',
);
ok(
  data.report.scores.every((s) => typeof s.target === 'string' && s.target.length > 0),
  'every rule reports a target',
);
ok(
  data.report.scores.filter((s) => !s.pass).every((s) => s.correction),
  'every failing rule carries a correction lever',
);
ok(
  C.INFORMATIONAL_RULES.every((r) => data.report.scores.find((s) => s.rule === r).pass),
  'informational rules always pass',
);

// 3. the default frame is imperfect ---------------------------------------
console.log('\n[3] default frame (the demo needs something to fix)');
ok(!data.report.overall_pass, 'default frame is NOT overall-pass', data.weightedFails.map((s) => `${s.rule}=${s.value.toFixed(3)}`).join(', '));
ok(data.weightedFails.length > 0, 'at least one weighted rule fails by default');

// 4. Auto-Frame ------------------------------------------------------------
console.log('\n[4] Auto-Frame');
const before = { az: state.azimuthDeg, dist: state.distance };
const result = P.applyAutoFrame(state);
ok(result.converged, 'solver reports converged', `${result.iterations} iteration(s)`);
ok(result.iterations >= 1 && result.iterations <= C.MAX_ITERATIONS, 'iteration count is within budget', `${result.iterations}`);
ok(result.report.overall_pass, "solver's own report passes overall");
data = P.compute(state);
ok(data.report.overall_pass, 'panel re-derives overall PASS after Auto-Frame');
ok(near(state.azimuthDeg, before.az, 1e-6), 'Auto-Frame preserves the chosen bearing', `${before.az}° → ${state.azimuthDeg.toFixed(3)}°`);
ok(state.distance !== before.dist, 'Auto-Frame moved the camera', `${before.dist} m → ${state.distance.toFixed(3)} m`);
ok(state.lensMode === 'fov' && state.fovDeg === C.SOLVER_FOV_DEG, 'solver lens (40° vFOV) is applied');

// 5. panel report == solver report ----------------------------------------
console.log('\n[5] panel report vs solver report');
const solverVals = new Map(result.report.scores.map((s) => [s.rule, s.value]));
let maxDiff = 0;
for (const s of data.report.scores) {
  maxDiff = Math.max(maxDiff, Math.abs(s.value - solverVals.get(s.rule)));
}
ok(maxDiff < 1e-6, 're-derived rule values match the solver', `max |Δ| = ${maxDiff.toExponential(2)}`);

// 6. continuity strip -----------------------------------------------------
console.log('\n[6] continuity strip');
const fresh = P.createState();
const issues = C.evaluateContinuity(P.continuityShots(fresh));
ok(issues.length === 4, 'three shots produce four verdicts', `${issues.length}`);
ok(issues.some((i) => i.rule === '180_axis' && !i.pass), 'a deliberate axis cross is flagged');
ok(issues.some((i) => i.rule === '30_degree' && !i.pass), 'a deliberate <30° jump cut is flagged');
ok(issues.some((i) => i.pass), 'at least one cut passes (the strip is not all red)');
ok(C.continuitySummary(issues).startsWith('FAIL'), 'summary reports FAIL', C.continuitySummary(issues));

// 7. reliability zone -----------------------------------------------------
console.log('\n[7] reliability zone');
const zoneAt = (az, el) => {
  const s = P.createState();
  s.azimuthDeg = az;
  s.distance = 3;
  s.height = C.heightForElevation(s.subject, el, s.distance);
  return C.cameraReliabilityZone(P.currentCamera(s), s.subject).zone;
};
ok(zoneAt(0, 0) === 'green', 'azimuth 0°, elevation 0° → green');
ok(zoneAt(45, 30) === 'green', 'azimuth 45°, elevation 30° → green (boundary)');
ok(zoneAt(50, 0) === 'yellow', 'azimuth 50°, elevation 0° → yellow');
ok(zoneAt(60, 0) === 'yellow', 'azimuth 60°, elevation 0° → yellow (boundary)');
ok(zoneAt(70, 0) === 'red', 'azimuth 70° → red');
ok(zoneAt(0, 40) === 'red', 'elevation 40° → red');

// 8. geometry invariants --------------------------------------------------
console.log('\n[8] geometry invariants');
const s2 = P.createState();
s2.azimuthDeg = -37;
s2.distance = 4.1;
s2.height = 2.3;
s2.aim = { x: 0.2, y: -0.1, z: 0.05 };
const cam = P.currentCamera(s2);
const back = C.orbitFromPose(s2.subject, cam);
ok(near(back.azimuthDeg, -37, 1e-9), 'orbit azimuth round-trips', `${back.azimuthDeg.toFixed(6)}`);
ok(near(back.distance, 4.1, 1e-9), 'orbit distance round-trips');
ok(near(back.height, 2.3, 1e-9), 'orbit height round-trips');
ok(
  near(back.aim.x, 0.2, 1e-9) && near(back.aim.y, -0.1, 1e-9) && near(back.aim.z, 0.05, 1e-9),
  'aim offsets round-trip',
);
const t = C.projector(cam)(cam.target);
ok(near(t[0], 0, 1e-9) && near(t[1], 0, 1e-9), 'the camera target projects to NDC (0,0)', `(${t[0].toExponential(1)}, ${t[1].toExponential(1)})`);
const eyeAnchor = C.anchors(s2.subject)[1];
ok(near(eyeAnchor[1], s2.subject.base[1] + 0.92 * s2.subject.height, 1e-12), 'eye anchor is at 0.92 × height');

// ---------------------------------------------------------------------------
console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} — ${checks - failures}/${checks} checks passed`);
process.exit(failures === 0 ? 0 : 1);
