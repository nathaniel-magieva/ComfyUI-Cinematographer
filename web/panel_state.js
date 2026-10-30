/**
 * Cinematographer — panel state and the compute pipeline.
 *
 * Deliberately free of DOM and three.js: `app.js` renders this, and
 * `tools/smoke_test.mjs` drives the very same functions headlessly. If the
 * panel's numbers were computed anywhere else, the smoke test would be testing a
 * copy instead of the panel.
 *
 * Every number here comes from `./cinematographer.js` (the engine mirror).
 */

import * as C from './cinematographer.js';

/** The panel's opening state — an imperfect frame, so the demo has something to fix. */
export const DEFAULTS = {
  subject: C.subject({ name: 'Maya', base: [0, 0, 0], height: 1.75, facing_yaw_deg: 0 }),
  shotType: 'medium',
  azimuthDeg: 12,
  distance: 3.2,
  height: 1.61,
  aim: { x: 0, y: 0, z: 0 },
  focalMm: 35,
  rollDeg: 0,
  dutchDeg: 0,
  lensMode: 'focal', // 'focal' (focal_mm path) | 'fov' (solver path)
  fovDeg: 0,
  comp: 'thirds-left', // 'centered' | 'thirds-left' | 'thirds-right'
  angle: 'eye', // 'low' | 'eye' | 'high'
  shots: [{ az: 12 }, { az: 30 }, { az: -25 }],
};

export function createState() {
  return structuredClone(DEFAULTS);
}

export function resetState(state) {
  Object.assign(state, structuredClone(DEFAULTS));
  return state;
}

/** The ShotIntent the engine consumes, built from the panel's toggles. */
export function currentIntent(state) {
  return C.shotIntent({
    angle: state.angle,
    center: state.comp === 'centered',
    side: state.comp === 'thirds-right' ? 'right' : 'left',
    dutch_deg: state.dutchDeg,
    azimuth_deg: 0,
  });
}

/** The CamPose the engine consumes, built from the orbit controls. */
export function currentCamera(state) {
  return C.poseFromOrbit(state.subject, {
    azimuthDeg: state.azimuthDeg,
    distance: state.distance,
    height: state.height,
    aim: state.aim,
    focalMm: state.focalMm,
    rollDeg: state.rollDeg,
    fovDeg: state.lensMode === 'fov' ? state.fovDeg : 0,
  });
}

/** Everything the panel shows, computed once per change. */
export function compute(state) {
  const camera = currentCamera(state);
  const intent = currentIntent(state);
  const report = C.evaluateFraming(state.subject, camera, state.shotType, intent);
  const zone = C.cameraReliabilityZone(camera, state.subject);
  return { camera, intent, report, zone, weightedFails: C.weightedFailures(report) };
}

/** A continuity-strip camera for one bearing, sharing the panel's lens and aim. */
export function shotCamera(state, az) {
  return C.poseFromOrbit(state.subject, {
    azimuthDeg: az,
    distance: state.distance,
    height: state.height,
    aim: state.aim,
    focalMm: state.focalMm,
    rollDeg: 0,
    fovDeg: state.lensMode === 'fov' ? state.fovDeg : 0,
  });
}

/** The three shots Choros compares. Shot 1 follows the panel camera. */
export function continuityShots(state) {
  const azes = [state.azimuthDeg, state.shots[1].az, state.shots[2].az];
  return azes.map((az, i) => ({
    shot_number: i + 1,
    base: state.subject.base,
    yaw_deg: state.subject.facing_yaw_deg,
    camera: shotCamera(state, az),
  }));
}

/**
 * Run the solver and write the solved pose back into the panel state.
 *
 * The user's chosen bearing is preserved: the solver's `azimuth_deg` is an
 * offset from the subject's front, so we pass the difference rather than
 * teleporting the camera to the front.
 */
export function applyAutoFrame(state) {
  const intent = currentIntent(state);
  intent.azimuth_deg = state.azimuthDeg - state.subject.facing_yaw_deg;

  const result = C.autoFrameCamera(state.subject, state.shotType, intent);

  const orbit = C.orbitFromPose(state.subject, result.camera);
  state.azimuthDeg = orbit.azimuthDeg;
  state.distance = orbit.distance;
  state.height = orbit.height;
  state.aim = orbit.aim;
  state.rollDeg = result.camera.roll_deg;
  state.lensMode = 'fov';
  state.fovDeg = result.camera.fov;

  return result;
}
