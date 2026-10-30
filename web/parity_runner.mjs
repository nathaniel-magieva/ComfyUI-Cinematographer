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

const HERE = dirname(fileURLToPath(import.meta.url));
const fixturesPath = process.argv[2] ? resolve(process.argv[2]) : resolve(HERE, 'parity_fixtures.json');
const fixtures = JSON.parse(readFileSync(fixturesPath, 'utf8'));

const asSubject = (d) => subject(d);
const asCamera = (d) => camPose(d);
const asIntent = (d) => shotIntent(d);

const out = { framing: [], continuity: [], reliability: [], autoframe: [] };

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

process.stdout.write(JSON.stringify(out));
