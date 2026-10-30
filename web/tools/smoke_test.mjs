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
 *   9. the Director tab's enums, credit model and @/# prompt parsing
 *
 * Exit code 0 = all checks passed.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import * as C from '../cinematographer.js';
import * as P from '../panel_state.js';
import * as D from '../director.js';

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
// 9. Director's Panel — enums, cost, prompt parsing
// ---------------------------------------------------------------------------
console.log("\n[9] Director's Panel");

const dirPanel = readFileSync(resolve(WEB, 'director_panel.js'), 'utf8');
const dirQueried = new Set();
for (const m of dirPanel.matchAll(/\$\('([^']+)'\)/g)) dirQueried.add(m[1]);
const dirMissing = [...dirQueried].filter((id) => !htmlIds.has(id));
ok(
  dirMissing.length === 0,
  `all ${dirQueried.size} Director-tab element ids exist in index.html`,
  dirMissing.join(', '),
);

// The enums must be the API's closed enumerations, with no duplicates.
const EXPECTED_ENUM_SIZES = {
  genre: 6, era: 5, pacing: 4, camera_model: 4, camera_lens: 5,
  camera_aperture: 3, camera_movement: 33, light: 6, color_palette: 50,
  emotion: 9, aspect_ratio: 6,
};
const sizeProblems = [];
for (const [name, want] of Object.entries(EXPECTED_ENUM_SIZES)) {
  const got = D.ENUMS[name];
  if (!got) sizeProblems.push(`${name}: missing`);
  else if (got.length !== want) sizeProblems.push(`${name}: ${got.length} != ${want}`);
}
ok(sizeProblems.length === 0, 'every enum has the API\'s count', sizeProblems.join('; ') || 'no drift');

const dupes = Object.entries(D.ENUMS)
  .filter(([, v]) => new Set(v).size !== v.length)
  .map(([k]) => k);
ok(dupes.length === 0, 'no enum contains a duplicate value', dupes.join(', '));

// The movement grouping is a presentation aid; it must partition the enum.
const grouped = D.MOVEMENT_GROUPS.flatMap((g) => g.slugs);
ok(
  grouped.length === D.CAMERA_MOVEMENT.length &&
    new Set(grouped).size === grouped.length &&
    D.CAMERA_MOVEMENT.every((m) => grouped.includes(m)),
  'the movement groups partition all 33 moves exactly',
  `${grouped.length} slugs in ${D.MOVEMENT_GROUPS.length} groups`,
);

// The credit model must reproduce every published cell with no residual.
const residuals = D.creditTableResiduals().filter((r) => r.residual !== 0);
ok(
  residuals.length === 0,
  `the linear credit model reproduces all ${D.creditTableResiduals().length} published cells`,
  residuals.length ? JSON.stringify(residuals) : 'rate 3 / 7 / 16 credits per second',
);

const c10 = D.estimateCredits({ duration: 10, resolution: '720p' });
ok(c10.current === 70, '10 s at 720p is 70 credits (published)', String(c10.current));
const c30 = D.estimateCredits({ duration: 30, resolution: '1080p' });
ok(
  c30.list === 480 && c30.current === 360 && c30.discounted,
  '30 s at 1080p lists 480 and discounts to 360',
  `list ${c30.list} → current ${c30.current}`,
);
const c4 = D.estimateCredits({ duration: 4, resolution: '480p' });
ok(c4.current === 12, '4 s at 480p is 12 credits (3/s, interpolated)', String(c4.current));
const c1080 = D.estimateCredits({ duration: 10, resolution: '1080p' });
ok(
  c1080.notes.some((n) => /documented API resolution enum is only/.test(n)),
  'the 1080p contradiction is surfaced, not hidden',
);

// Prompt parsing.
const registry = D.DEMO_REGISTRY;
const toks = D.parsePrompt('@tamsincamp runs, @ghost watches, #dolly-in then #dollyin', registry);
ok(toks.length === 4, 'four tags are parsed', String(toks.length));
ok(
  toks.filter((t) => t.resolved).length === 2,
  'exactly the two real tags resolve',
  toks.filter((t) => t.resolved).map((t) => t.raw).join(','),
);
ok(
  toks.find((t) => t.name === 'dollyin')?.suggestion === 'dolly-in',
  'a misspelled move suggests the real one',
  String(toks.find((t) => t.name === 'dollyin')?.suggestion),
);

const composed = D.composePrompt({
  text: '@tamsincamp waits, @ghost watches',
  moves: ['dolly-in', 'crane-up'],
  registry,
});
ok(
  composed.prompt.includes('<<<image_1>>>') && composed.attachments.length === 1,
  '@Element becomes the API reference token, deduplicated',
  composed.prompt,
);
ok(
  composed.prompt.trim().endsWith('#dolly-in #crane-up'),
  'the moves are appended in stack order',
  composed.moveTags.join(' '),
);
ok(composed.unresolved === 1, 'the unresolved tag is counted', String(composed.unresolved));

// The plan.
const plan = D.directorPlan({ ...D.DEFAULT_DIRECTOR_STATE, prompt: '@tamsincamp waits' });
ok(plan.sends === false, 'the plan declares that it sends nothing');
ok(
  Object.keys(plan.parameters).every((k) => !k.startsWith('_')),
  'the parameter block carries only real API fields',
  Object.keys(plan.parameters).join(','),
);
ok(
  !('focal_mm' in plan.parameters) && plan.extensions.focal_mm === D.FOCAL_DEFAULT,
  'focal length is an engine extension, never an API parameter',
);
ok(D.FOCAL_LENGTH_DROPPED_IN_4_0 === true, 'the engine records that 4.0 dropped focal length');
ok(
  plan.omitted.includes('genre') && plan.omitted.includes('camera_movement'),
  'auto fields are reported as omitted, not sent as "auto"',
  plan.omitted.slice(0, 3).join(','),
);

const set = D.directorPlan({
  ...D.DEFAULT_DIRECTOR_STATE,
  genre: 'noir',
  moves: ['dolly-in'],
  prompt: 'x',
});
ok(set.parameters.genre === 'noir', 'a chosen field reaches the parameter block');
ok(
  !set.omitted.includes('genre') && set.omitted.includes('era'),
  'only the still-auto fields stay omitted',
);

// Emotion intensity is continuous, not an invented three-value enum.
ok(
  D.EMOTION_INTENSITY_MIN === 0 && D.EMOTION_INTENSITY_MAX === 1,
  'emotion intensity is a continuous 0..1 range',
);
ok(
  D.intensityLabel(0) === 'subtle' && D.intensityLabel(1) === 'intense',
  'the three words are descriptors on that scale',
);
ok(
  !('emotion_intensity' in D.ENUMS),
  'intensity is NOT exposed as an enum (the cut points are unsourced)',
);

// ---------------------------------------------------------------------------
console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} — ${checks - failures}/${checks} checks passed`);
process.exit(failures === 0 ? 0 : 1);
