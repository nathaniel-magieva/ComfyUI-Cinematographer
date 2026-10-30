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

const HERE = dirname(fileURLToPath(import.meta.url));
const fixturesPath = process.argv[2] ? resolve(process.argv[2]) : resolve(HERE, 'parity_fixtures.json');
const fixtures = JSON.parse(readFileSync(fixturesPath, 'utf8'));

const asSubject = (d) => subject(d);
const asCamera = (d) => camPose(d);
const asIntent = (d) => shotIntent(d);

const out = { framing: [], continuity: [], reliability: [], autoframe: [], director: { enums: [], credits: [] } };

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

process.stdout.write(JSON.stringify(out));
