/**
 * Compute the parity fixtures with the browser engine and print the results as
 * JSON on stdout. Invoked by `parity_check.py`; not meant to be run by hand
 * (though it is harmless).
 *
 *   node web/parity_runner.mjs [path/to/parity_fixtures.json]
 *
 * stdout is JSON only — the checker parses it.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  autoFrameCamera,
  cameraReliabilityZone,
  camPose,
  evaluateContinuity,
  evaluateFraming,
  shotIntent,
  subject,
} from './cinematographer.js';
import * as DIR from './director.js';
import * as STUDIO from './studio.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const fixturesPath = process.argv[2] ? resolve(process.argv[2]) : resolve(HERE, 'parity_fixtures.json');
const fixtures = JSON.parse(readFileSync(fixturesPath, 'utf8'));

const asSubject = (d) => subject(d);
const asCamera = (d) => camPose(d);
const asIntent = (d) => shotIntent(d);

const out = {
  framing: [],
  continuity: [],
  reliability: [],
  autoframe: [],
  director: { enums: [], credits: [] },
  studio: {
    constants: [],
    sidecar: [],
    palette: [],
    grade: [],
    grade_summary: [],
    extend: [],
    edit: [],
    post_checks: [],
    corrections: [],
    registry: [],
  },
};

for (const fx of fixtures.framing) {
  const rep = evaluateFraming(
    asSubject(fx.subject),
    asCamera(fx.camera),
    fx.shot_type,
    asIntent(fx.intent),
  );
  out.framing.push({ id: fx.id, actual: rep });
}

for (const fx of fixtures.continuity) {
  const shots = fx.shots.map((s) => ({
    shot_number: s.shot_number,
    base: s.base,
    yaw_deg: s.yaw_deg,
    camera: asCamera(s.camera),
  }));
  out.continuity.push({ id: fx.id, actual: evaluateContinuity(shots) });

}

for (const fx of fixtures.reliability) {
  const zone = cameraReliabilityZone(
    asCamera(fx.camera),
    asSubject(fx.subject),
    fx.azimuth_deg,
    fx.elevation_deg,
  );
  out.reliability.push({ id: fx.id, actual: zone });
}

for (const fx of fixtures.autoframe) {
  const res = autoFrameCamera(asSubject(fx.subject), fx.shot_type, asIntent(fx.intent));
  out.autoframe.push({ id: fx.id, actual: res });
}

// --- Director's Panel -------------------------------------------------------
// The enums are compared verbatim; the credit cells are compared against the
// published table, which is an external fact rather than a value this code
// computed for itself.

for (const fx of fixtures.director.enums) {
  const values = DIR.ENUMS[fx.enum];
  out.director.enums.push({
    id: fx.id,
    enum: fx.enum,
    actual: values ? [...values] : null,
  });
}

for (const fx of fixtures.director.credits) {
  const cost = DIR.estimateCredits({ duration: fx.duration, resolution: fx.resolution });
  out.director.credits.push({
    id: fx.id,
    // `list` is the published table price; `current` may carry the documented
    // limited-time 1080p launch discount.
    actual: cost.list,
    current: cost.current,
    discounted: cost.discounted,
  });
}

// --- Stages 1 / 2 / 4 / 5 (Elements, Shoot, Post) ---------------------------
// `studio.js` mirrors `elements.py`, `post.py` and `nodes.py`. For the cases the
// engine REJECTS, only the decision is compared: the engine raises on the first
// problem and names it in a sentence, while the panel collects every problem so
// a form can show them all. Freezing that prose would freeze the panel's voice.

const studio = fixtures.studio ?? {};

for (const fx of studio.constants ?? []) {
  const value = STUDIO[fx.name];
  out.studio.constants.push({
    id: fx.id,
    name: fx.name,
    actual: value === undefined ? null : JSON.parse(JSON.stringify(value)),
  });
}

for (const fx of studio.sidecar ?? []) {
  out.studio.sidecar.push({ id: fx.id, actual: STUDIO.sidecarPath(fx.asset_path) });
}

for (const fx of studio.palette ?? []) {
  const res = STUDIO.parsePalette(fx.text);
  out.studio.palette.push({ id: fx.id, ok: res.ok, actual: res.ok ? res.palette : null });
}

for (const fx of studio.grade ?? []) {
  out.studio.grade.push({ id: fx.id, actual: STUDIO.applyGrade(fx.settings) });
}

for (const fx of studio.grade_summary ?? []) {
  out.studio.grade_summary.push({
    id: fx.id,
    actual: STUDIO.gradeSummary(STUDIO.applyGrade(fx.settings)),
  });
}

for (const fx of studio.extend ?? []) {
  const res = STUDIO.extendPlan({
    mode: fx.mode,
    duration_s: fx.duration_s,
    overlap_frames: fx.overlap_frames,
  });
  out.studio.extend.push({ id: fx.id, ok: res.ok, actual: res.ok ? res.plan : null });
}

for (const fx of studio.edit ?? []) {
  const res = STUDIO.editRegion({ label: fx.label, bbox: fx.bbox, prompt: fx.prompt });
  out.studio.edit.push({ id: fx.id, ok: res.ok, actual: res.ok ? res.region : null });
}

for (const fx of studio.post_checks ?? []) {
  const grade = STUDIO.applyGrade(fx.grade);
  const ext = fx.extend
    ? STUDIO.extendPlan({
        mode: fx.extend[0],
        duration_s: fx.extend[1],
        overlap_frames: fx.extend[2],
      }).plan
    : null;
  const ed = fx.edit
    ? STUDIO.editRegion({ label: fx.edit[0], bbox: fx.edit[1], prompt: fx.edit[2] }).region
    : null;
  out.studio.post_checks.push({
    id: fx.id,
    actual: STUDIO.postChecks({ grade, extend: ext, edit: ed ? { regions: [ed] } : null }),
  });
}

for (const fx of studio.corrections ?? []) {
  out.studio.corrections.push({ id: fx.id, actual: STUDIO.correctionsFromReport(fx.report) });
}

for (const fx of studio.registry ?? []) {
  // The fixture carries the three constructor arguments; the rest are the
  // engine's own defaults, so they are filled the same way on both sides.
  const elements = fx.elements.map((e) => ({
    name: e.name,
    category: e.category,
    asset_path: e.asset_path,
    description: '',
    seed: 0,
    palette: [],
    bbox: null,
    created_utc: '',
  }));
  out.studio.registry.push({ id: fx.id, actual: STUDIO.registryDoc(elements) });
}

process.stdout.write(JSON.stringify(out));
