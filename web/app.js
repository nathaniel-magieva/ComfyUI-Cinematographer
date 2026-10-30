/**
 * Cinematographer — Director's Panel.
 *
 * All arithmetic comes from `./cinematographer.js`, which is a line-by-line
 * mirror of the Python engine at `cinematographer/`. This file only wires
 * that engine to the DOM, to a 2D frame preview, and to a three.js viewport.
 *
 * Nothing here invents a number. If a value is on screen, `evaluateFraming`,
 * `autoFrameCamera`, `evaluateContinuity` or `cameraReliabilityZone` produced it.
 */

import * as C from './cinematographer.js';
import * as P from './panel_state.js';
import * as D from './director.js';
import * as DP from './director_panel.js';
import * as S from './studio.js';
import * as EP from './elements_panel.js';
import * as SP from './shoot_panel.js';
import * as PP from './post_panel.js';
import * as RP from './run_panel.js';
import * as CC from './comfy_client.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = P.createState();

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const el = {
  overallBadge: $('overall-badge'),
  overallValue: $('overall-value'),
  overallNote: $('overall-note'),
  reliabilityBadge: $('reliability-badge'),
  reliabilityValue: $('reliability-value'),
  zoneSwatch: $('zone-swatch'),
  zoneReason: $('zone-reason'),
  rules: $('rules'),
  solverBadge: $('solver-badge'),
  solverNote: $('solver-note'),
  autoframe: $('autoframe'),
  reset: $('reset'),
  frame: $('frame'),
  jsonCamera: $('json-camera'),
  jsonReport: $('json-report'),
  shots: $('shots'),
  continuityOut: $('continuity-out'),
  checkContinuity: $('check-continuity'),
  lensNote: $('lens-note'),
  threeStatus: $('three-status'),
  chipEye: $('chip-eye'),
  chipTarget: $('chip-target'),
  chipFov: $('chip-fov'),
  viewport: $('viewport'),
  gl: $('gl'),
};

const RULE_LABELS = {
  in_frame: 'in_frame',
  rule_of_thirds: 'rule_of_thirds',
  headroom: 'headroom',
  shot_size: 'shot_size',
  lead_room: 'lead_room',
  negative_space: 'negative_space',
  camera_angle: 'camera_angle',
  level: 'level',
  direct_address: 'direct_address',
};

// ---------------------------------------------------------------------------
// Rendering — rule panel
// ---------------------------------------------------------------------------

function renderRules(report) {
  const frag = document.createDocumentFragment();
  for (const sc of report.scores) {
    const informational = C.INFORMATIONAL_RULES.includes(sc.rule);
    const cls = informational ? 'info' : sc.pass ? 'pass' : 'fail';
    const verdict = informational ? 'INFO' : sc.pass ? 'PASS' : 'FAIL';

    const row = document.createElement('div');
    row.className = `rule ${cls}`;

    const head = document.createElement('div');
    head.className = 'rule-head';
    head.innerHTML =
      `<span class="rule-name">${RULE_LABELS[sc.rule] ?? sc.rule}</span>` +
      `<span class="rule-weight">w ${sc.weight.toFixed(1)}</span>` +
      `<span class="rule-badge">${verdict}</span>`;

    const body = document.createElement('div');
    body.className = 'rule-body';
    body.innerHTML =
      `<span class="rule-value">${sc.value.toFixed(3)}</span>` +
      `<span class="rule-target">${escapeHtml(sc.target)}</span>`;

    row.append(head, body);

    if (sc.correction) {
      const lever = document.createElement('div');
      lever.className = 'rule-lever';
      lever.textContent = sc.correction;
      row.append(lever);
    }
    frag.append(row);
  }
  el.rules.replaceChildren(frag);
}

function renderOverall(report, weightedFails) {
  const pass = report.overall_pass;
  el.overallBadge.className = `badge ${pass ? 'badge-pass' : 'badge-fail'}`;
  el.overallValue.textContent = pass ? 'PASS' : 'FAIL';
  if (pass) {
    el.overallNote.textContent =
      'Every rule with weight ≥ 0.8 passes. Informational rules (negative_space, camera_angle, ' +
      'direct_address) describe the frame and cannot fail.';
  } else {
    const bits = weightedFails.map((s) => `${s.rule}=${s.value.toFixed(3)}`);
    el.overallNote.textContent =
      `Weighted rules still failing: ${bits.join(', ')}. ` +
      'Overall pass requires every rule with weight ≥ 0.8 to pass.';
  }
}

function renderReliability(zone) {
  el.reliabilityBadge.className = `badge badge-zone-${zone.zone}`;
  el.reliabilityValue.textContent = zone.zone.toUpperCase();
  el.zoneSwatch.className = `zone-swatch zone-${zone.zone}`;
  el.zoneSwatch.textContent = zone.zone;
  el.zoneReason.textContent =
    `${zone.reason} (azimuth ${zone.azimuth_deg.toFixed(1)}°, elevation ${zone.elevation_deg.toFixed(1)}°)`;
}

function renderLensNote(camera) {
  const vfov = C.verticalFovDeg(camera);
  if (state.lensMode === 'fov') {
    const equiv = C.focalForVerticalFov(state.fovDeg);
    el.lensNote.textContent =
      `Solver lens: ${state.fovDeg.toFixed(1)}° vertical FOV (≈${equiv.toFixed(1)} mm equivalent). ` +
      'Moving the focal slider returns the camera to the focal-length path.';
  } else {
    el.lensNote.textContent =
      `Lens: ${state.focalMm.toFixed(0)} mm on a 36 mm sensor at 16:9 → ${vfov.toFixed(2)}° vertical FOV.`;
  }
}

function renderJson(camera, report) {
  el.jsonCamera.textContent = JSON.stringify(camera, null, 2);
  el.jsonReport.textContent = JSON.stringify(report, null, 2);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// ---------------------------------------------------------------------------
// Rendering — 2D frame preview
// ---------------------------------------------------------------------------

function renderFramePreview(camera, report) {
  const cv = el.frame;
  const ctx = cv.getContext('2d');
  const W = cv.width;
  const H = cv.height;
  const M = 14; // margin for the off-frame gutter
  const iw = W - 2 * M;
  const ih = H - 2 * M;

  const px = (x) => M + ((x + 1) / 2) * iw;
  const py = (y) => M + ((1 - y) / 2) * ih;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#070a0f';
  ctx.fillRect(0, 0, W, H);

  // frame
  ctx.fillStyle = '#0d1219';
  ctx.fillRect(M, M, iw, ih);

  // headroom band: head = 1 - ndcY(top) in [lo, hi]  =>  ndcY(top) in [1-hi, 1-lo]
  const [lo, hi] = C.headroomBand(state.shotType);
  const bandTop = py(1 - lo);
  const bandBottom = py(1 - hi);
  ctx.fillStyle = 'rgba(47, 191, 113, 0.10)';
  ctx.fillRect(M, bandTop, iw, bandBottom - bandTop);
  ctx.strokeStyle = 'rgba(47, 191, 113, 0.35)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(M, bandTop);
  ctx.lineTo(M + iw, bandTop);
  ctx.moveTo(M, bandBottom);
  ctx.lineTo(M + iw, bandBottom);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(47, 191, 113, 0.75)';
  ctx.font = '11px ui-monospace, monospace';
  ctx.fillText(`headroom band [${lo.toFixed(2)}, ${hi.toFixed(2)}]`, M + 6, bandTop - 4);

  // thirds
  ctx.strokeStyle = 'rgba(124, 140, 255, 0.35)';
  ctx.beginPath();
  for (const t of [-1 / 3, 1 / 3]) {
    ctx.moveTo(px(t), M);
    ctx.lineTo(px(t), M + ih);
    ctx.moveTo(M, py(t));
    ctx.lineTo(M + iw, py(t));
  }
  ctx.stroke();

  // frame border
  ctx.strokeStyle = '#3a465c';
  ctx.lineWidth = 1;
  ctx.strokeRect(M + 0.5, M + 0.5, iw - 1, ih - 1);

  // centre / aim crosshair (the camera's target always projects to NDC 0,0)
  ctx.strokeStyle = 'rgba(232, 237, 245, 0.5)';
  ctx.beginPath();
  ctx.moveTo(px(0) - 7, py(0));
  ctx.lineTo(px(0) + 7, py(0));
  ctx.moveTo(px(0), py(0) - 7);
  ctx.lineTo(px(0), py(0) + 7);
  ctx.stroke();

  // subject: base -> top, plus the eye anchor
  const proj = C.projector(camera);
  const [bx, by, , bIn] = proj(C.base3(state.subject));
  const [ex, ey, , eIn] = proj(C.eyePt(state.subject));
  const [tx, ty, , tIn] = proj(C.topPt(state.subject));

  const clampX = (v) => Math.max(-1, Math.min(1, v));
  const clampY = (v) => Math.max(-1, Math.min(1, v));

  ctx.lineWidth = 3;
  ctx.strokeStyle = report.overall_pass ? '#2fbf71' : '#ef4d5a';
  ctx.beginPath();
  ctx.moveTo(px(clampX(bx)), py(clampY(by)));
  ctx.lineTo(px(clampX(tx)), py(clampY(ty)));
  ctx.stroke();

  const dot = (x, y, inFront, colour, label) => {
    const cx = px(clampX(x));
    const cy = py(clampY(y));
    const off = Math.abs(x) > 1 || Math.abs(y) > 1 || !inFront;
    ctx.beginPath();
    ctx.arc(cx, cy, 5, 0, Math.PI * 2);
    ctx.fillStyle = off ? 'transparent' : colour;
    ctx.strokeStyle = colour;
    ctx.lineWidth = 2;
    if (off) ctx.stroke();
    else ctx.fill();
    ctx.fillStyle = colour;
    ctx.font = '11px ui-monospace, monospace';
    ctx.fillText(label, cx + 8, cy - 6);
  };

  dot(bx, by, bIn, '#8b98ad', 'base');
  dot(tx, ty, tIn, '#8b98ad', 'top');
  dot(ex, ey, eIn, '#7c8cff', 'eye 0.92h');

  // readouts
  ctx.font = '12px ui-monospace, monospace';
  ctx.fillStyle = '#c3cddd';
  ctx.fillText(`ndcX(eye) ${ex.toFixed(3)}`, M + 6, M + ih - 8);
  ctx.fillText(`ndcY(top) ${ty.toFixed(3)}`, M + 6, M + ih - 24);
  if (!eIn) {
    ctx.fillStyle = '#ef4d5a';
    ctx.fillText('eye anchor is BEHIND the camera', M + 6, M + 22);
  }
}

// ---------------------------------------------------------------------------
// Rendering — continuity strip
// ---------------------------------------------------------------------------

function renderShots() {
  const azes = [state.azimuthDeg, state.shots[1].az, state.shots[2].az];
  const frag = document.createDocumentFragment();

  azes.forEach((az, i) => {
    const cam = P.shotCamera(state, az);
    const side = C.axisSide(state.subject.base, state.subject.facing_yaw_deg, cam.eye);
    const bearing = C.camAzimuthDeg(state.subject.base, cam.eye);

    const card = document.createElement('div');
    card.className = 'shot';
    card.innerHTML =
      `<div class="shot-head">` +
      `<span class="shot-title">shot ${i + 1}</span>` +
      `<span class="shot-meta">bearing ${bearing.toFixed(1)}° · side ${side > 0 ? '+1' : '−1'}` +
      `${i === 0 ? ' · follows the panel camera' : ''}</span>` +
      `</div>`;

    if (i > 0) {
      const input = document.createElement('input');
      input.type = 'range';
      input.min = '-180';
      input.max = '180';
      input.step = '1';
      input.value = String(az);
      input.addEventListener('input', () => {
        state.shots[i].az = Number(input.value);
        renderShots();
        renderContinuity();
      });
      card.append(input);
    }
    frag.append(card);
  });

  el.shots.replaceChildren(frag);
}

function renderContinuity() {
  const shots = P.continuityShots(state);
  const issues = C.evaluateContinuity(shots);
  const frag = document.createDocumentFragment();

  for (let i = 1; i < shots.length; i++) {
    const pair = issues.filter((x) => x.shot_a === i && x.shot_b === i + 1);
    const cut = document.createElement('div');
    cut.className = 'cut';
    cut.innerHTML = `<div class="cut-title">cut ${i} → ${i + 1}</div>`;
    for (const issue of pair) {
      const row = document.createElement('div');
      row.className = `issue ${issue.pass ? 'pass' : 'fail'}`;
      row.innerHTML =
        `<span class="issue-rule">${issue.rule}</span>` +
        `<span class="issue-badge">${issue.pass ? 'PASS' : 'FAIL'}</span>` +
        `<span class="issue-detail">${escapeHtml(issue.detail)}</span>`;
      cut.append(row);
    }
    frag.append(cut);
  }

  const summary = document.createElement('div');
  const allPass = issues.every((x) => x.pass);
  summary.className = `continuity-summary ${allPass ? 'pass' : 'fail'}`;
  summary.textContent = C.continuitySummary(issues);
  frag.append(summary);

  el.continuityOut.replaceChildren(frag);
}

// ---------------------------------------------------------------------------
// three.js viewport (optional — the panel works without it)
// ---------------------------------------------------------------------------

const THREE_URLS = [
  'https://unpkg.com/three@0.160.0/build/three.module.js',
  'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js',
];

let three = null;
let view = null;

async function loadThree() {
  for (const url of THREE_URLS) {
    try {
      return await import(/* webpackIgnore: true */ url);
    } catch (err) {
      // try the next mirror
    }
  }
  return null;
}

function initViewport(THREE) {
  const renderer = new THREE.WebGLRenderer({ canvas: el.gl, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070a0f);
  scene.fog = new THREE.Fog(0x070a0f, 12, 34);

  const viewer = new THREE.PerspectiveCamera(45, 16 / 9, 0.05, 200);
  const target = new THREE.Vector3(0, 1, 0);
  const orbit = { theta: 0.9, phi: 1.15, radius: 7.5 };

  scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x0a0f16, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.2);
  key.position.set(4, 8, 6);
  scene.add(key);

  const grid = new THREE.GridHelper(24, 24, 0x2a3a52, 0x1b2230);
  scene.add(grid);

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(24, 24),
    new THREE.MeshStandardMaterial({ color: 0x0e131b, roughness: 1, metalness: 0 }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.001;
  scene.add(ground);

  // subject figure + eye anchor + action line
  const subjectGroup = new THREE.Group();
  scene.add(subjectGroup);

  const actionLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineBasicMaterial({ color: 0x2fbf71 }),
  );
  scene.add(actionLine);

  const facingArrow = new THREE.ArrowHelper(
    new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(0, 0.06, 0),
    1.1,
    0x2fbf71,
    0.22,
    0.12,
  );
  scene.add(facingArrow);

  // shot camera + frustum
  const shotCam = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 60);
  scene.add(shotCam);
  let helper = new THREE.CameraHelper(shotCam);
  scene.add(helper);

  const camBody = new THREE.Mesh(
    new THREE.BoxGeometry(0.22, 0.16, 0.3),
    new THREE.MeshStandardMaterial({ color: 0x7c8cff, roughness: 0.4, metalness: 0.3 }),
  );
  scene.add(camBody);

  function resize() {
    // The Judge panel starts hidden, so the container can measure 0×0. Fall back
    // to a sane size and re-measure for real when the tab is shown.
    const w = el.viewport.clientWidth || 640;
    const h = el.viewport.clientHeight || 360;
    renderer.setSize(w, h, false);
    viewer.aspect = w / h;
    viewer.updateProjectionMatrix();
  }

  // minimal viewer orbit
  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  el.gl.addEventListener('pointerdown', (e) => {
    dragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
    el.gl.setPointerCapture(e.pointerId);
  });
  el.gl.addEventListener('pointerup', (e) => {
    dragging = false;
    if (el.gl.hasPointerCapture(e.pointerId)) el.gl.releasePointerCapture(e.pointerId);
  });
  el.gl.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    orbit.theta -= (e.clientX - lastX) * 0.008;
    orbit.phi = Math.max(0.12, Math.min(1.5, orbit.phi - (e.clientY - lastY) * 0.006));
    lastX = e.clientX;
    lastY = e.clientY;
  });
  el.gl.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      orbit.radius = Math.max(2.2, Math.min(28, orbit.radius * (1 + Math.sign(e.deltaY) * 0.08)));
    },
    { passive: false },
  );

  window.addEventListener('resize', resize);
  resize();

  view = {
    THREE,
    renderer,
    scene,
    viewer,
    orbit,
    target,
    subjectGroup,
    actionLine,
    facingArrow,
    shotCam,
    camBody,
    helper,
    resize,
    update(camera, report) {
      const s = state.subject;
      const [base, eyeAnchor] = C.anchors(s);

      // subject figure
      subjectGroup.clear();
      const radius = Math.max(0.12, Math.min(0.28, s.height * 0.11));
      const body = new THREE.Mesh(
        new THREE.CapsuleGeometry(radius, Math.max(0.05, s.height - 2 * radius), 6, 14),
        new THREE.MeshStandardMaterial({
          color: report.overall_pass ? 0x2fbf71 : 0xef4d5a,
          roughness: 0.55,
          metalness: 0.05,
        }),
      );
      body.position.set(base[0], base[1] + s.height / 2, base[2]);
      subjectGroup.add(body);

      const head = new THREE.Mesh(
        new THREE.SphereGeometry(radius * 1.05, 16, 12),
        new THREE.MeshStandardMaterial({ color: 0x7c8cff, roughness: 0.35 }),
      );
      head.position.set(eyeAnchor[0], eyeAnchor[1], eyeAnchor[2]);
      subjectGroup.add(head);

      // action line through the subject along its facing direction
      const yaw = (s.facing_yaw_deg * Math.PI) / 180;
      const dir = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
      const p0 = new THREE.Vector3(base[0], base[1] + 0.02, base[2]).addScaledVector(dir, -3.5);
      const p1 = new THREE.Vector3(base[0], base[1] + 0.02, base[2]).addScaledVector(dir, 3.5);
      actionLine.geometry.dispose();
      actionLine.geometry = new THREE.BufferGeometry().setFromPoints([p0, p1]);

      facingArrow.position.set(base[0], base[1] + 0.06, base[2]);
      facingArrow.setDirection(dir);

      // shot camera
      shotCam.fov = C.verticalFovDeg(camera);
      shotCam.aspect = camera.aspect;
      shotCam.position.set(camera.eye[0], camera.eye[1], camera.eye[2]);
      shotCam.up.set(0, 1, 0);
      shotCam.lookAt(camera.target[0], camera.target[1], camera.target[2]);
      shotCam.rotateZ((camera.roll_deg * Math.PI) / 180);
      shotCam.updateProjectionMatrix();

      scene.remove(helper);
      helper.dispose();
      helper = new THREE.CameraHelper(shotCam);
      scene.add(helper);
      view.helper = helper;

      camBody.position.copy(shotCam.position);
      camBody.quaternion.copy(shotCam.quaternion);

      // keep the viewer centred on the subject
      target.set(base[0], base[1] + s.height * 0.55, base[2]);

      el.chipEye.textContent =
        `eye ${camera.eye.map((v) => v.toFixed(2)).join(', ')}`;
      el.chipTarget.textContent =
        `target ${camera.target.map((v) => v.toFixed(2)).join(', ')}`;
      el.chipFov.textContent = `vFOV ${C.verticalFovDeg(camera).toFixed(1)}°`;

      render();
    },
  };

  function render() {
    const { theta, phi, radius } = orbit;
    viewer.position.set(
      target.x + radius * Math.sin(phi) * Math.sin(theta),
      target.y + radius * Math.cos(phi),
      target.z + radius * Math.sin(phi) * Math.cos(theta),
    );
    viewer.lookAt(target);
    renderer.render(scene, viewer);
  }

  return view;
}

// ---------------------------------------------------------------------------
// Master render
// ---------------------------------------------------------------------------

let last = null;

function render() {
  const data = P.compute(state);
  last = data;
  renderRules(data.report);
  renderOverall(data.report, data.weightedFails);
  renderReliability(data.zone);
  renderLensNote(data.camera);
  renderFramePreview(data.camera, data.report);
  renderJson(data.camera, data.report);
  renderShots();
  renderContinuity();
  syncControls();
  if (view) view.update(data.camera, data.report);
}

// ---------------------------------------------------------------------------
// Control wiring
// ---------------------------------------------------------------------------

const sliderMap = [
  ['in-az', 'out-az', () => state.azimuthDeg, (v) => { state.azimuthDeg = v; }, (v) => `${v.toFixed(0)}°`],
  ['in-dist', 'out-dist', () => state.distance, (v) => { state.distance = v; }, (v) => `${v.toFixed(2)} m`],
  ['in-height', 'out-height', () => state.height, (v) => { state.height = v; }, (v) => `${v.toFixed(2)} m`],
  ['in-elev', 'out-elev', () => C.elevationDeg(state.subject, P.currentCamera(state).eye), (v) => {
    state.height = C.heightForElevation(state.subject, v, state.distance);
  }, (v) => `${v.toFixed(1)}°`],
  ['in-focal', 'out-focal', () => state.focalMm, (v) => {
    state.focalMm = v;
    state.lensMode = 'focal';
    state.fovDeg = 0;
  }, (v) => `${v.toFixed(0)} mm`],
  ['in-roll', 'out-roll', () => state.rollDeg, (v) => { state.rollDeg = v; }, (v) => `${v.toFixed(1)}°`],
  ['in-dutch', 'out-dutch', () => state.dutchDeg, (v) => { state.dutchDeg = v; }, (v) => `${v.toFixed(1)}°`],
  ['in-aimx', 'out-aimx', () => state.aim.x, (v) => { state.aim.x = v; }, (v) => `${v.toFixed(2)} m`],
  ['in-aimy', 'out-aimy', () => state.aim.y, (v) => { state.aim.y = v; }, (v) => `${v.toFixed(2)} m`],
  ['in-yaw', 'out-yaw', () => state.subject.facing_yaw_deg, (v) => { state.subject.facing_yaw_deg = v; }, (v) => `${v.toFixed(0)}°`],
  ['in-sheight', 'out-sheight', () => state.subject.height, (v) => { state.subject.height = v; }, (v) => `${v.toFixed(2)} m`],
];

function syncControls() {
  for (const [inputId, outputId, get, , fmt] of sliderMap) {
    const input = $(inputId);
    const output = $(outputId);
    const value = get();
    if (document.activeElement !== input) input.value = String(value);
    output.textContent = fmt(value);
  }
  // The elevation slider is derived, so it must be re-read after height changes.
  const elev = C.elevationDeg(state.subject, P.currentCamera(state).eye);
  const elevInput = $('in-elev');
  if (document.activeElement !== elevInput) elevInput.value = String(elev);
  $('out-elev').textContent = `${elev.toFixed(1)}°`;

  // segmented controls
  for (const [id, key] of [['seg-shot', 'shotType'], ['seg-comp', 'comp'], ['seg-angle', 'angle']]) {
    for (const btn of $(id).querySelectorAll('button')) {
      btn.classList.toggle('on', btn.dataset.value === state[key]);
    }
  }
}

function wireControls() {
  for (const [inputId, , , set] of sliderMap) {
    const input = $(inputId);
    input.addEventListener('input', () => {
      set(Number(input.value));
      render();
    });
  }

  const segments = [
    ['seg-shot', (v) => { state.shotType = v; }],
    ['seg-comp', (v) => { state.comp = v; }],
    ['seg-angle', (v) => { state.angle = v; }],
  ];
  for (const [id, apply] of segments) {
    $(id).addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      apply(btn.dataset.value);
      render();
    });
  }

  el.reset.addEventListener('click', () => {
    P.resetState(state);
    el.solverBadge.className = 'badge badge-muted';
    el.solverBadge.querySelector('.badge-value').textContent = 'idle';
    el.solverNote.textContent =
      'Solves a pose that satisfies the weighted rules, then reports honestly whether it ' +
      'converged — the original returned its 24th iterate unconditionally.';
    render();
  });

  el.autoframe.addEventListener('click', runAutoFrame);
  el.checkContinuity.addEventListener('click', renderContinuity);
}

// ---------------------------------------------------------------------------
// Auto-Frame
// ---------------------------------------------------------------------------

function runAutoFrame() {
  const result = P.applyAutoFrame(state);

  el.solverBadge.className = `badge ${result.converged ? 'badge-pass' : 'badge-fail'}`;
  el.solverBadge.querySelector('.badge-value').textContent = result.converged
    ? `converged · ${result.iterations} iter`
    : `NOT converged · ${result.iterations} iter`;
  el.solverNote.textContent = result.converged
    ? `Converged in ${result.iterations} of ${C.MAX_ITERATIONS} iterations — the frame now passes ` +
      'every rule with weight ≥ 0.8.'
    : `Did not converge in ${result.iterations} iterations. Still failing: ` +
      `${result.residual.join(', ') || 'unknown'}. The panel says so rather than showing a pose ` +
      'that looks solved.';

  render();
}

// ---------------------------------------------------------------------------
// Tabs — the five stages of Cinema Studio 4.0
// ---------------------------------------------------------------------------
//
//   Director  Stage 3  the parameters
//   Judge     the measurement that gates POST
//   Elements  Stage 1 BUILD + Stage 2 ATTACH
//   Shoot     Stage 4 PROMPT
//   Post      Stage 5 POST
//
// The three later tabs are additive: `showTab` still coerces an unknown name to
// 'director', and the Director and Judge panels are untouched.

const TABS = ['director', 'judge', 'elements', 'shoot', 'post', 'run'];

const TAB_NOTES = {
  director: 'The Director tab composes a plan. It does not generate anything.',
  judge: 'The Judge tab measures a frame. It does not generate anything either.',
  elements:
    'The Elements tab names the cast and the sets. It writes no file — it shows what the node would write.',
  shoot:
    'The Shoot tab composes the prompt from the Director tab\'s parameters. It sends nothing.',
  post:
    'The Post tab describes a grade. CinemaGradeApply is what changes pixels, and it needs an image this panel does not have.',
  run:
    'The Run tab sends the prompt to a live ComfyUI and shows what the engine returned. It still generates no image and no video.',
};

function showTab(name) {
  if (!TABS.includes(name)) name = 'director';
  for (const t of TABS) {
    const panel = document.getElementById(`tab-${t}`);
    if (panel) panel.classList.toggle('hidden', t !== name);
  }
  for (const btn of document.querySelectorAll('#tabnav .tab')) {
    const on = btn.dataset.tab === name;
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  }
  const note = document.getElementById('tabnav-note');
  if (note) note.textContent = TAB_NOTES[name] ?? TAB_NOTES.director;

  // The viewport canvas has no size while its panel is hidden; re-measure on show.
  if (name === 'judge' && view) {
    view.resize();
    const data = P.compute(state);
    view.update(data.camera, data.report);
  }
  // The later tabs read live state (the Director's moves, the Judge's report),
  // so they re-render on show rather than holding a stale copy.
  if (name === 'elements') EP.renderElements();
  if (name === 'shoot') SP.renderShoot();
  if (name === 'post') PP.renderPost();
  if (name === 'run') RP.renderRun();
}

function wireTabs() {
  const nav = document.getElementById('tabnav');
  if (nav) {
    nav.addEventListener('click', (e) => {
      const btn = e.target.closest('.tab');
      if (btn) showTab(btn.dataset.tab);
    });
  }
  showTab('director');
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  // An async boot swallows its own rejections, which is how a typo in this file
  // can leave the panel half-built with nothing on screen. Record them so
  // `tools/browser_check.mjs` can fail loudly instead.
  window.__panelErrors = [];
  window.addEventListener('error', (e) => {
    window.__panelErrors.push(String(e.message || e.error || 'error'));
  });
  window.addEventListener('unhandledrejection', (e) => {
    window.__panelErrors.push(String(e.reason?.message || e.reason || 'unhandled rejection'));
  });

  try {
    wireTabs();
    wireControls();
    render();
    DP.initDirectorPanel();
    // The three later stages. Each reads the earlier tabs' live state rather
    // than a copy, so they are initialised after the Director panel exists.
    EP.initElementsPanel();
    SP.initShootPanel();
    PP.initPostPanel({ getReport: () => P.compute(state).report });
    RP.initRunPanel({ getState: () => state });
  } catch (err) {
    window.__panelErrors.push(`boot: ${err.message}`);
    throw err;
  }

  // Debug/verification hook. `tools/browser_check.mjs` uses it to force a
  // synchronous render and sample real pixels — the only reliable way to prove
  // the viewport draws something under headless WebGL.
  window.__cinematographer = {
    state,
    view: null,
    compute: () => P.compute(state),
    render,
    engine: C,
    panel: P,
    director: D,
    directorState: DP.directorState,
    directorPanel: DP,
    studio: S,
    elementsPanel: EP,
    shootPanel: SP,
    postPanel: PP,
    runPanel: RP,
    comfyClient: CC,
    showTab,
  };

  three = await loadThree();
  if (!three) {
    el.threeStatus.textContent = 'three.js unavailable (offline?) — 2D preview and rules still live';
    const note = document.createElement('div');
    note.className = 'viewport-fallback';
    note.innerHTML =
      'The 3D viewport needs three.js from a CDN.<br />' +
      'The rule panel, frame preview, solver and continuity checks are pure arithmetic and ' +
      'work without it.';
    el.viewport.append(note);
    return;
  }
  try {
    initViewport(three);
    window.__cinematographer.view = view;
    el.threeStatus.textContent = 'three.js r160 · drag to orbit';
    const data = P.compute(state);
    view.update(data.camera, data.report);
  } catch (err) {
    el.threeStatus.textContent = `WebGL unavailable: ${err.message}`;
  }
}

boot();
