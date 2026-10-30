/**
 * Cinematographer — browser port of the deterministic geometry engine.
 *
 * This file is a **line-by-line mirror** of the Python package at
 * `cinematographer/` (which is itself a faithful port of a production
 * cinematography engine). Every function cites the Python
 * function it mirrors, and `parity_check.py` proves the two agree on fixtures.
 *
 * If you change a number here, change it there too — or the panel lies.
 *
 * Conventions (identical to the engine):
 *   - world distances in metres, angles in degrees at this boundary
 *   - NDC x, y in [-1, 1], frame edges at +/-1, y is up (screen-top = +1)
 *   - the subject's eye anchor is at 0.92 * height (load-bearing, not a rounding
 *     choice)
 *   - reported values are rounded to 3 dp
 *
 * No dependencies. Loads as an ES module in the browser and in Node >= 18.
 */

// ---------------------------------------------------------------------------
// Constants — mirror cinematographer/geometry.py
// ---------------------------------------------------------------------------

export const SHOT_TYPES = ['closeup', 'medium', 'wide'];

/** The nine per-shot rule keys, in evaluation order (framing.py:42-52). */
export const FRAMING_RULES = [
  'in_frame',
  'rule_of_thirds',
  'headroom',
  'shot_size',
  'lead_room',
  'negative_space',
  'camera_angle',
  'level',
  'direct_address',
];

/** Rules that describe rather than judge — they never fail (framing.py:55). */
export const INFORMATIONAL_RULES = ['negative_space', 'camera_angle', 'direct_address'];

/** rule -> {shot_type -> weight}. Mirrors RULE_WEIGHTS (geometry.py:316-347). */
export const RULE_WEIGHTS = {
  closeup: {
    in_frame: 1,
    rule_of_thirds: 1.0,
    headroom: 1.0,
    shot_size: 1.0,
    lead_room: 0.4,
    negative_space: 0.3,
    camera_angle: 0.3,
    level: 0.5,
  },
  medium: {
    in_frame: 1,
    rule_of_thirds: 0.8,
    headroom: 0.7,
    shot_size: 1.0,
    lead_room: 0.4,
    negative_space: 0.3,
    camera_angle: 0.3,
    level: 0.5,
  },
  wide: {
    in_frame: 1,
    rule_of_thirds: 0.6,
    headroom: 0.4,
    shot_size: 1.0,
    lead_room: 0.3,
    negative_space: 0.4,
    camera_angle: 0.3,
    level: 0.5,
  },
};

/** A rule at or above this weight must pass for the frame to pass overall. */
export const OVERALL_PASS_WEIGHT = 0.8;

/** The solver's fixed vertical FOV and aspect (autoframe.py:41-42). */
export const SOLVER_FOV_DEG = 40.0;
export const SOLVER_ASPECT = 16.0 / 9.0;

/** The original's iteration budget — kept, but no longer relied on. */
export const MAX_ITERATIONS = 24;

/** Minimum camera distance, in metres. */
export const MIN_DISTANCE = 0.3;

/** Reliability envelope (reliability.py:22-28). */
export const GREEN_AZIMUTH_DEG = 45.0;
export const YELLOW_AZIMUTH_DEG = 60.0;
export const YELLOW_ELEVATION_DEG = 30.0;

/** The two rules Choros enforces across a cut (continuity.py:31). */
export const CONTINUITY_RULES = ['180_axis', '30_degree'];

/** Minimum camera-angle change between consecutive shots, in degrees. */
export const MIN_ANGLE_CHANGE_DEG = 30.0;

/** Default camera pose fields (geometry.py CamPose defaults). */
export const DEFAULT_FOCAL_MM = 35.0;
export const DEFAULT_SENSOR_MM = 36.0;
export const DEFAULT_ASPECT = 16.0 / 9.0;

// ---------------------------------------------------------------------------
// Vector helpers — mirror geometry.py:32-66
// ---------------------------------------------------------------------------

export function sub(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function cross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

export function dot(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/** Normalise. A degenerate vector returns [0, 0, 1], matching the Go source. */
export function norm(a) {
  const length = Math.sqrt(dot(a, a));
  if (length < 1e-9) return [0.0, 0.0, 1.0];
  return [a[0] / length, a[1] / length, a[2] / length];
}

export function clamp(v, lo, hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

/**
 * Python's `round()`: nearest, ties to even. The engine is Python, so the panel
 * mirrors Python's rounding rather than JavaScript's `Math.round` (ties away
 * from zero) — otherwise a value sitting exactly on a .5 boundary would print
 * differently on screen than the engine reports it.
 */
export function pyRound(x) {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** Round to 3 dp — the reported precision of every measured value. */
export function round3(v) {
  return pyRound(v * 1000) / 1000;
}

/** Mirror Python's `format(x, '.Nf')` (ties to even, and it keeps the sign of -0). */
export function pyFixed(x, digits) {
  const scale = Math.pow(10, digits);
  const r = pyRound(x * scale) / scale;
  let s = Math.abs(r).toFixed(digits);
  // Python prints -0.0 and -0.001 as '-0.00' at 2 dp; JS toFixed drops the sign.
  if (x < 0 || Object.is(x, -0)) s = `-${s}`;
  return s;
}

/** Mirror Python's `format(x, 'g')` with the default precision of 6. */
export function pyG(x, precision = 6) {
  if (!Number.isFinite(x)) return String(x);
  if (Object.is(x, -0)) return '-0';
  if (x === 0) return '0';
  const exp = Math.floor(Math.log10(Math.abs(x)));
  if (exp < -4 || exp >= precision) {
    let s = x.toExponential(precision - 1);
    s = s.replace(/\.?0+e/, 'e');
    s = s.replace(/e([+-])(\d)$/, 'e$10$2');
    return s;
  }
  const decimals = Math.max(0, precision - 1 - exp);
  let s = x.toFixed(decimals);
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s;
}

// ---------------------------------------------------------------------------
// Scene primitives — mirror geometry.py:74-170
// ---------------------------------------------------------------------------

/** A camera placement to evaluate (any keyframe of a move). */
export function camPose(partial = {}) {
  return {
    eye: partial.eye ? [...partial.eye] : [0, 0, 0],
    target: partial.target ? [...partial.target] : [0, 0, 0],
    focal_mm: partial.focal_mm ?? DEFAULT_FOCAL_MM,
    sensor_mm: partial.sensor_mm ?? DEFAULT_SENSOR_MM,
    aspect: partial.aspect ?? DEFAULT_ASPECT,
    roll_deg: partial.roll_deg ?? 0.0,
    fov: partial.fov ?? 0.0,
  };
}

/** The framed entity, from the scene graph (feet position + height). */
export function subject(partial = {}) {
  return {
    name: partial.name ?? 'subject',
    base: partial.base ? [...partial.base] : [0, 0, 0],
    height: partial.height ?? 1.7,
    facing_yaw_deg: partial.facing_yaw_deg ?? 0.0,
  };
}

/** The director's intent — so the DP does not flag deliberate choices. */
export function shotIntent(partial = {}) {
  return {
    angle: partial.angle ?? 'eye',
    side: partial.side ?? 'center',
    center: partial.center ?? false,
    dutch_deg: partial.dutch_deg ?? 0.0,
    azimuth_deg: partial.azimuth_deg ?? 0.0,
  };
}

// ---------------------------------------------------------------------------
// Projection — mirror geometry.py:239-306
// ---------------------------------------------------------------------------

/**
 * Map a world point to NDC (x, y in [-1, 1]) plus depth and an in-front flag.
 * Returns a function `(p) => [ndcX, ndcY, depth, inFront]`.
 */
export function projector(cam) {
  const eye = cam.eye;
  const fwd = norm(sub(cam.target, eye));
  let right = norm(cross(fwd, [0.0, 1.0, 0.0]));
  let up = cross(right, fwd);

  const aspect = cam.aspect > 0 ? cam.aspect : DEFAULT_ASPECT;
  const sensor = cam.sensor_mm > 0 ? cam.sensor_mm : DEFAULT_SENSOR_MM;
  const focal = cam.focal_mm > 0 ? cam.focal_mm : DEFAULT_FOCAL_MM;

  if (cam.roll_deg !== 0) {
    // Dutch: rotate the right/up basis about the optical axis.
    const r = (cam.roll_deg * Math.PI) / 180;
    const cs = Math.cos(r);
    const sn = Math.sin(r);
    const nr = [
      right[0] * cs + up[0] * sn,
      right[1] * cs + up[1] * sn,
      right[2] * cs + up[2] * sn,
    ];
    const nu = [
      -right[0] * sn + up[0] * cs,
      -right[1] * sn + up[1] * cs,
      -right[2] * sn + up[2] * cs,
    ];
    right = nr;
    up = nu;
  }

  let vfov = 2 * Math.atan(sensor / aspect / (2 * focal));
  if (cam.fov > 0) vfov = (cam.fov * Math.PI) / 180;
  const f = 1.0 / Math.tan(vfov / 2);

  return function project(p) {
    const d = sub(p, eye);
    const cx = dot(d, right);
    const cy = dot(d, up);
    const cz = dot(d, fwd);
    if (cz <= 1e-4) return [0.0, 0.0, cz, false];
    return [(cx / cz) * (f / aspect), (cy / cz) * f, cz, true];
  };
}

/**
 * Return [base, eye, top] world anchors.
 *
 * The eye anchor is at **0.92 x height** — the Go source's constant. Changing it
 * changes every framing measurement, so it is deliberately not configurable.
 */
export function anchors(s) {
  const base = s.base;
  const eye = [s.base[0], s.base[1] + 0.92 * s.height, s.base[2]];
  const top = [s.base[0], s.base[1] + s.height, s.base[2]];
  return [base, eye, top];
}

export function base3(s) {
  return anchors(s)[0];
}

export function eyePt(s) {
  return anchors(s)[1];
}

export function topPt(s) {
  return anchors(s)[2];
}

// ---------------------------------------------------------------------------
// Shot-type bands — mirror geometry.py:353-379
// ---------------------------------------------------------------------------

export function shotWeights(shotType) {
  return RULE_WEIGHTS[shotType] ?? RULE_WEIGHTS.medium;
}

export function headroomBand(shotType) {
  if (shotType === 'closeup') return [0.05, 0.3];
  if (shotType === 'wide') return [0.2, 0.7];
  return [0.1, 0.45];
}

export function shotSizeOk(frac, shotType) {
  // The engine's target strings are the Go source's verbatim, unicode included
  // (geometry.py shot_size_ok). Escapes keep them byte-exact whatever the
  // transport encoding does.
  if (shotType === 'closeup') return [frac >= 0.7, 'subject \u226570% of frame height (CU)'];
  if (shotType === 'wide') return [frac >= 0.15 && frac <= 0.45, 'subject 15\u201345% of frame height (WS)'];
  return [frac >= 0.4 && frac <= 0.75, 'subject 40\u201375% of frame height (MS)'];
}

/** Desired subject screen-height fraction per shot type (the solver's target). */
export function sizeTargetMid(shotType) {
  if (shotType === 'closeup') return 0.85;
  if (shotType === 'wide') return 0.3;
  return 0.55;
}

// ---------------------------------------------------------------------------
// EvaluateFraming — mirror framing.py:73-228
// ---------------------------------------------------------------------------

function headroomCorrection(head, lo, hi) {
  if (head < lo) return 'too tight / clipped top: lower the camera target or pull back';
  return 'too much headroom: raise the camera target or push in';
}

/** Positive when the subject looks into the frame's negative space. */
function leadRoom(s, ndcX) {
  const faceRight = Math.sin((s.facing_yaw_deg * Math.PI) / 180) > 0;
  return faceRight ? -ndcX : ndcX;
}

/**
 * Score the deterministic cinematography rules for one subject and camera.
 * Returns {subject, shot_type, scores: [...], overall_pass}.
 */
export function evaluateFraming(s, cam, shotType = 'medium', intent = null) {
  const it = intent ?? shotIntent();
  const proj = projector(cam);

  const by = proj(base3(s))[1];
  const [ex, ey, , eIn] = proj(eyePt(s));
  const ty = proj(topPt(s))[1];

  const w = shotWeights(shotType);
  const scores = [];

  const add = (rule, passed, val, target, corr = '') => {
    const score = {
      rule,
      pass: passed,
      value: round3(val),
      target,
      weight: w[rule] ?? 0.0,
    };
    // The engine omits `correction` entirely when there is none
    // (FramingScore.to_dict), so the panel mirrors that shape exactly.
    if (corr) score.correction = corr;
    scores.push(score);
  };

  // 1. in_frame — the subject's FACE is in front of the camera and within the
  //    frame. Feet need not be visible: a close-up crops the body.
  const inFrame = eIn && Math.abs(ex) <= 1 && Math.abs(ey) <= 1;
  add(
    'in_frame',
    inFrame,
    inFrame ? 1.0 : 0.0,
    "subject's face within frame & in front",
    inFrame ? '' : "re-aim/pull back: subject's face is off-frame or behind camera",
  );

  // 2. rule_of_thirds — the eye anchor near a vertical third line (+/-1/3 NDC),
  //    unless the shot is intentionally centred, where centred is correct.
  if (it.center) {
    const centered = Math.abs(ex) <= 0.12;
    add(
      'rule_of_thirds',
      centered,
      ex,
      'centered (symmetry intended)',
      centered ? '' : 'center the subject (ndcX~0)',
    );
  } else {
    const thirdDist = Math.min(Math.abs(ex - 1.0 / 3), Math.abs(ex + 1.0 / 3));
    const thirdsPass = thirdDist <= 0.12;
    add(
      'rule_of_thirds',
      thirdsPass,
      ex,
      'eyes near x=\u00b10.33 (not centered)',
      thirdsPass
        ? ''
        : `offset subject to a third: shift camera x / aim (eyes at ndcX=${pyFixed(ex, 2)})`,
    );
  }

  // 3. headroom — the gap from the subject's top to the frame top (ndcY=1).
  const head = 1 - ty;
  const [headLo, headHi] = headroomBand(shotType);
  const headPass = headLo <= head && head <= headHi;
  add(
    'headroom',
    headPass,
    head,
    `top gap in [${pyFixed(headLo, 2)}, ${pyFixed(headHi, 2)}]`,
    headPass ? '' : headroomCorrection(head, headLo, headHi),
  );

  // 4. shot_size — the subject's screen-height fraction, classified vs intent.
  const frac = (ty - by) / 2;
  const [sizePass, sizeTgt] = shotSizeOk(frac, shotType);
  add(
    'shot_size',
    sizePass,
    frac,
    sizeTgt,
    sizePass
      ? ''
      : `dolly/zoom to hit ${shotType} (subject fills ${pyFixed(frac * 100, 0)}% of height)`,
  );

  // 5. lead_room — the subject should look INTO the frame.
  const lead = leadRoom(s, ex);
  const leadPass = lead >= -0.05;
  add(
    'lead_room',
    leadPass,
    lead,
    'gaze leads into frame',
    leadPass ? '' : 'flip composition: leave space in the direction the subject faces',
  );

  // 6. negative_space — the fraction of frame NOT covered by the subject.
  //    Informational: >0.7 reads isolated, ~0.5 balanced.
  const subH = Math.max(0.0, ty - by) / 2;
  const subArea = Math.min(1.0, subH * (0.38 * subH + 0.05));
  add('negative_space', true, 1 - subArea, '>0.7 reads isolated; ~0.5 balanced');

  // 7. camera_angle <-> power: pitch sign plus camera height vs the eye-line.
  //    Informational.
  const fwd = norm(sub(cam.target, cam.eye));
  const pitch = (Math.asin(clamp(fwd[1], -1.0, 1.0)) * 180) / Math.PI;
  const dh = cam.eye[1] - (s.base[1] + 0.92 * s.height);
  let angleClass = 'eye-level (neutral)';
  if (dh < -0.1 && pitch > 2) angleClass = 'low (power/heroic)';
  else if (dh > 0.1 && pitch < -2) angleClass = 'high (vulnerable)';
  add('camera_angle', true, dh, angleClass);

  // 8. level / Dutch — the roll should match the intended Dutch (0 = level).
  const levelPass = Math.abs(cam.roll_deg - it.dutch_deg) < 1;
  let levelTgt = 'roll\u22480 (level)';
  if (it.dutch_deg !== 0) levelTgt = `Dutch ${pyG(it.dutch_deg)}\u00b0 (unease intended)`;
  add('level', levelPass, cam.roll_deg, levelTgt, levelPass ? '' : 'match the intended camera roll');

  // 9. direct_address — the angle between the subject's gaze and the
  //    camera->subject axis. <8 deg looks down the lens. Informational register.
  const gaze = norm([
    Math.sin((s.facing_yaw_deg * Math.PI) / 180),
    0.0,
    Math.cos((s.facing_yaw_deg * Math.PI) / 180),
  ]);
  const toCam = norm(sub(cam.eye, eyePt(s)));
  const addr = (Math.acos(clamp(dot(gaze, toCam), -1.0, 1.0)) * 180) / Math.PI;
  let addrClass = 'off-lens (observational)';
  if (addr < 8) addrClass = 'direct address (down the lens)';
  else if (addr < 25) addrClass = 'near-lens (engaged)';
  add('direct_address', true, addr, addrClass);

  // Overall: every rule at or above the weight threshold must pass.
  const overallPass = scores.every((sc) => !(sc.weight >= OVERALL_PASS_WEIGHT) || sc.pass);

  return { subject: s.name, shot_type: shotType, scores, overall_pass: overallPass };
}

/** The report's score for one rule, or null. */
export function scoreOf(report, rule) {
  return report.scores.find((sc) => sc.rule === rule) ?? null;
}

/** The report's measured value for one rule (0 when absent), as the solver reads it. */
export function scoreValue(report, rule) {
  const sc = scoreOf(report, rule);
  return sc ? sc.value : 0.0;
}

/** Failing scores, in rule order. */
export function failures(report) {
  return report.scores.filter((sc) => !sc.pass);
}

/** The correction levers for every failing rule that has one. */
export function corrections(report) {
  return report.scores.filter((sc) => !sc.pass && sc.correction).map((sc) => sc.correction);
}

/** A one-line, human-readable verdict (framing.py:231-240). */
export function summary(report) {
  const verdict = report.overall_pass ? 'PASS' : 'FAIL';
  const bits = [`${verdict} ${report.shot_type} on '${report.subject}'`];
  const fails = failures(report);
  if (!fails.length) bits.push('all weighted rules pass');
  for (const sc of fails) bits.push(`${sc.rule}=${pyG(sc.value)}`);
  return bits.join(' | ');
}

// ---------------------------------------------------------------------------
// AutoFrameCamera — mirror autoframe.py:95-188 (including the convergence fix)
// ---------------------------------------------------------------------------

/**
 * Solve a camera pose that frames the subject per shot type and intent.
 *
 * Returns {camera, report, converged, iterations, residual}. **Check
 * `converged` before claiming the frame is compliant** — that flag is the fix
 * this port adds over the original, which returned the 24th iterate
 * unconditionally.
 */
export function autoFrameCamera(s, shotType = 'medium', intent = null, maxIterations = MAX_ITERATIONS) {
  const it = intent ?? shotIntent();
  const f = 1.0 / Math.tan((SOLVER_FOV_DEG * Math.PI) / 180 / 2);
  const eyeHeight = s.base[1] + 0.92 * s.height;
  const targetFrac = sizeTargetMid(shotType);
  let dist = Math.max(MIN_DISTANCE, (s.height * f) / (2 * targetFrac));
  const azR = ((s.facing_yaw_deg + it.azimuth_deg) * Math.PI) / 180;

  let heightY = eyeHeight;
  if (it.angle === 'low') heightY = s.base[1] + 0.4;
  else if (it.angle === 'high') heightY = eyeHeight + 0.8;

  let desired = 1.0 / 3;
  if (it.center) desired = 0.0;
  else if (it.side === 'left') desired = -1.0 / 3;

  const [lo, hi] = headroomBand(shotType);
  const midHead = (lo + hi) / 2;

  const look = [s.base[0], eyeHeight, s.base[2]];
  let offX = 0.0;
  let offY = 0.0;
  let cam = camPose({ eye: look, target: look });
  let rep = evaluateFraming(s, cam, shotType, it);
  let iterations = 0;

  for (let i = 0; i < maxIterations; i++) {
    iterations = i + 1;
    const eye = [
      s.base[0] + Math.sin(azR) * dist,
      heightY,
      s.base[2] + Math.cos(azR) * dist,
    ];
    const fwd = norm(sub(look, eye));
    const right = norm(cross(fwd, [0.0, 1.0, 0.0]));
    const up = cross(right, fwd);
    const target = [
      look[0] + right[0] * offX + up[0] * offY,
      look[1] + right[1] * offX + up[1] * offY,
      look[2] + right[2] * offX + up[2] * offY,
    ];
    cam = camPose({
      eye,
      target,
      fov: SOLVER_FOV_DEG,
      roll_deg: it.dutch_deg,
      aspect: SOLVER_ASPECT,
    });
    rep = evaluateFraming(s, cam, shotType, it);

    // --- the fix: stop as soon as the frame is actually compliant ---
    if (rep.overall_pass) break;

    const ex = scoreValue(rep, 'rule_of_thirds');
    const head = scoreValue(rep, 'headroom');
    const frac = scoreValue(rep, 'shot_size');

    if (frac > 0.01) dist *= 1 + 0.6 * (frac / targetFrac - 1);
    dist = Math.max(MIN_DISTANCE, dist);

    offX += (0.6 * (ex - desired) * dist * SOLVER_ASPECT) / f;
    offY += (0.6 * (midHead - head) * dist) / f;
    offX = clamp(offX, -0.8 * dist, 0.8 * dist);
    offY = clamp(offY, -0.6 * dist, 0.6 * dist);
  }

  const residual = failures(rep)
    .filter((sc) => sc.weight >= 0.8)
    .map((sc) => `${sc.rule}=${pyG(sc.value)}`);

  return { camera: cam, report: rep, converged: rep.overall_pass, iterations, residual };
}

/** A one-line account of the solve — including when it did not converge. */
export function autoframeSummary(result) {
  if (result.converged) {
    return (
      `CONVERGED in ${result.iterations} iteration(s) - ` +
      `${result.report.shot_type} frame passes all weighted rules`
    );
  }
  return (
    `NOT CONVERGED after ${result.iterations} iteration(s) - ` +
    `still failing: ${result.residual.join(', ') || 'unknown'}`
  );
}

// ---------------------------------------------------------------------------
// Choros continuity — mirror continuity.py:84-155
// ---------------------------------------------------------------------------

/** The camera's bearing around the subject (0 = camera on +Z of the subject). */
export function camAzimuthDeg(base, eye) {
  return (Math.atan2(eye[0] - base[0], eye[2] - base[2]) * 180) / Math.PI;
}

/** Which side of the subject's facing line the camera is on: +1 or -1. */
export function axisSide(base, yawDeg, eye) {
  const fx = Math.sin((yawDeg * Math.PI) / 180);
  const fz = Math.cos((yawDeg * Math.PI) / 180);
  const nx = fz;
  const nz = -fx;
  const d = (eye[0] - base[0]) * nx + (eye[2] - base[2]) * nz;
  return d >= 0 ? 1.0 : -1.0;
}

/** The smallest absolute angle between two bearings, in [0, 180]. */
export function angDelta(a, b) {
  let d = Math.abs(a - b) % 360;
  if (d > 180) d = 360 - d;
  return d;
}

/** Check each consecutive pair for the 180-degree axis rule and the 30-degree rule. */
export function evaluateContinuity(shots) {
  const out = [];
  for (let i = 1; i < shots.length; i++) {
    const a = shots[i - 1];
    const b = shots[i];

    const sideA = axisSide(a.base, a.yaw_deg, a.camera.eye);
    const sideB = axisSide(b.base, b.yaw_deg, b.camera.eye);
    const axisPass = sideA === sideB;
    out.push({
      rule: '180_axis',
      shot_a: a.shot_number,
      shot_b: b.shot_number,
      pass: axisPass,
      detail: axisPass
        ? 'camera stays on one side of the action line'
        : "axis crossed - the subject's screen direction flips between the cuts",
    });

    const d = angDelta(
      camAzimuthDeg(a.base, a.camera.eye),
      camAzimuthDeg(b.base, b.camera.eye),
    );
    const degPass = d >= MIN_ANGLE_CHANGE_DEG;
    out.push({
      rule: '30_degree',
      shot_a: a.shot_number,
      shot_b: b.shot_number,
      pass: degPass,
      detail:
        `camera angle changed ${pyFixed(d, 0)} deg ` +
        `(need >=${pyFixed(MIN_ANGLE_CHANGE_DEG, 0)} deg to avoid a jump cut)`,
    });
  }
  return out;
}

/** A one-line verdict across the whole sequence. */
export function continuitySummary(issues) {
  if (!issues.length) return 'no consecutive shots to check';
  const failed = issues.filter((i) => !i.pass);
  if (!failed.length) {
    return `PASS - ${issues.length} continuity checks across ${Math.floor(issues.length / 2)} cut(s)`;
  }
  const parts = failed.map((i) => `${i.rule} (shot ${i.shot_a}->${i.shot_b})`);
  return `FAIL - ${failed.length} of ${issues.length} checks: ${parts.join(', ')}`;
}

// ---------------------------------------------------------------------------
// Reliability zone — mirror reliability.py:49-103
// ---------------------------------------------------------------------------

/**
 * Grade a requested camera pose against the view-steering training envelope.
 *
 * If azimuth/elevation are not supplied they are derived from the camera pose
 * relative to the subject, exactly as the engine does.
 */
export function cameraReliabilityZone(camera, s, azimuthDeg = null, elevationDeg = null) {
  let az = azimuthDeg;
  let el = elevationDeg;
  if (az === null || az === undefined) az = camAzimuthDeg(s.base, camera.eye);
  if (el === null || el === undefined) {
    const eyeY = camera.eye[1];
    const eyeHeight = s.base[1] + 0.92 * s.height;
    const horiz = Math.max(
      1e-6,
      Math.sqrt(
        (camera.eye[0] - s.base[0]) ** 2 + (camera.eye[2] - s.base[2]) ** 2,
      ),
    );
    el = (Math.atan2(eyeY - eyeHeight, horiz) * 180) / Math.PI;
  }

  const absAz = Math.abs(az);
  const absEl = Math.abs(el);

  if (absAz <= GREEN_AZIMUTH_DEG && absEl <= YELLOW_ELEVATION_DEG) {
    return {
      zone: 'green',
      reason:
        `inside the trained range (azimuth ${pyFixed(absAz, 0)} deg <= ` +
        `${pyFixed(GREEN_AZIMUTH_DEG, 0)} deg, elevation ${pyFixed(absEl, 0)} deg <= ` +
        `${pyFixed(YELLOW_ELEVATION_DEG, 0)} deg)`,
      azimuth_deg: round3(az),
      elevation_deg: round3(el),
    };
  }

  if (absAz <= YELLOW_AZIMUTH_DEG && absEl <= YELLOW_ELEVATION_DEG) {
    return {
      zone: 'yellow',
      reason:
        `extrapolating on azimuth (${pyFixed(absAz, 0)} deg > ` +
        `${pyFixed(GREEN_AZIMUTH_DEG, 0)} deg) - the model is guessing beyond its trained range`,
      azimuth_deg: round3(az),
      elevation_deg: round3(el),
    };
  }

  let reason;
  if (absAz > YELLOW_AZIMUTH_DEG) {
    reason =
      `azimuth ${pyFixed(absAz, 0)} deg is beyond the trained range ` +
      `(${pyFixed(YELLOW_AZIMUTH_DEG, 0)} deg) - the hidden side will be invented`;
  } else {
    reason =
      `elevation ${pyFixed(absEl, 0)} deg is beyond the trained range ` +
      `(${pyFixed(YELLOW_ELEVATION_DEG, 0)} deg) - the hidden side will be invented`;
  }
  return { zone: 'red', reason, azimuth_deg: round3(az), elevation_deg: round3(el) };
}

// ---------------------------------------------------------------------------
// Panel helpers — derived from the engine's own maths, not invented here
// ---------------------------------------------------------------------------

/**
 * Build a CamPose from the panel's orbit controls.
 *
 * `azimuthDeg` is the camera's bearing around the subject (0 = on the subject's
 * +Z), which is exactly what `camAzimuthDeg` measures — so the reliability badge
 * and the continuity strip read the same quantity the sliders show.
 */
export function poseFromOrbit(s, { azimuthDeg, distance, height, aim, focalMm, rollDeg, fovDeg }) {
  const [base, eyeAnchor] = anchors(s);
  const azR = (azimuthDeg * Math.PI) / 180;
  const eye = [
    base[0] + Math.sin(azR) * distance,
    height,
    base[2] + Math.cos(azR) * distance,
  ];
  const target = [
    eyeAnchor[0] + (aim?.x ?? 0),
    eyeAnchor[1] + (aim?.y ?? 0),
    eyeAnchor[2] + (aim?.z ?? 0),
  ];
  const pose = camPose({ eye, target, roll_deg: rollDeg ?? 0 });
  if (fovDeg && fovDeg > 0) {
    pose.fov = fovDeg;
    pose.focal_mm = 0;
  } else {
    pose.focal_mm = focalMm ?? DEFAULT_FOCAL_MM;
    pose.fov = 0;
  }
  return pose;
}

/** The elevation of a camera eye above the subject's eye anchor, in degrees. */
export function elevationDeg(s, eye) {
  const eyeHeight = s.base[1] + 0.92 * s.height;
  const horiz = Math.max(
    1e-6,
    Math.sqrt((eye[0] - s.base[0]) ** 2 + (eye[2] - s.base[2]) ** 2),
  );
  return (Math.atan2(eye[1] - eyeHeight, horiz) * 180) / Math.PI;
}

/** The camera eye height that realises a given elevation, in metres. */
export function heightForElevation(s, elevation, distance) {
  const eyeHeight = s.base[1] + 0.92 * s.height;
  return eyeHeight + distance * Math.tan((elevation * Math.PI) / 180);
}

/** The effective vertical FOV of a pose, in degrees (mirrors projector()). */
export function verticalFovDeg(cam) {
  if (cam.fov > 0) return cam.fov;
  const aspect = cam.aspect > 0 ? cam.aspect : DEFAULT_ASPECT;
  const sensor = cam.sensor_mm > 0 ? cam.sensor_mm : DEFAULT_SENSOR_MM;
  const focal = cam.focal_mm > 0 ? cam.focal_mm : DEFAULT_FOCAL_MM;
  return (2 * Math.atan(sensor / aspect / (2 * focal)) * 180) / Math.PI;
}

/** The focal length equivalent to a vertical FOV, in mm (inverse of the above). */
export function focalForVerticalFov(fovDeg, aspect = DEFAULT_ASPECT, sensor = DEFAULT_SENSOR_MM) {
  return sensor / aspect / (2 * Math.tan((fovDeg * Math.PI) / 180 / 2));
}

/** Recover the orbit controls from a solved camera pose (used by Auto-Frame). */
export function orbitFromPose(s, cam) {
  const [base, eyeAnchor] = anchors(s);
  const dx = cam.eye[0] - base[0];
  const dz = cam.eye[2] - base[2];
  return {
    azimuthDeg: (Math.atan2(dx, dz) * 180) / Math.PI,
    distance: Math.sqrt(dx * dx + dz * dz),
    height: cam.eye[1],
    aim: {
      x: cam.target[0] - eyeAnchor[0],
      y: cam.target[1] - eyeAnchor[1],
      z: cam.target[2] - eyeAnchor[2],
    },
  };
}

/** The weighted rules that are failing — the ones that decide `overall_pass`. */
export function weightedFailures(report) {
  return report.scores.filter((sc) => sc.weight >= OVERALL_PASS_WEIGHT && !sc.pass);
}
