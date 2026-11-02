// Exports a show's motion for Blender, frame by frame at 60 fps, without rendering (the physics of
// src/physics.js, as tools/tune_physics.mjs runs it):
//   node tools/export_motion.mjs [show=landing] [seconds=3.5] [out=out/<show>/motion.json] [model=roadster]
//
// Blender's axes and units: x — along the screen to the right (the car's forward), y — away from the
// camera, z — up; metres, radians. The physics is y-up with z towards the viewer: (x, y, z) -> (x, -z, y).
// Per frame: time, autopilot phase, the chassis frame (pos — the floor point under the car at ride
// height, quat — w, x, y, z), per wheel its spin about the axle (+ = rolling forward), up (the wheel
// centre's offset from its ride-height place along the chassis z: + pushed up into the arch, − hanging)
// and contact, and the thrust of every nozzle as a fraction of its maximum (0..1, the mean over the
// frame, as the three.js engine uses it). Events: phase changes, ignite/cutoff of each nozzle
// (thrust crossing 1.2%, as src/jet3d.js), touchdown (the first wheel contact). Marks: the frames the
// stills and the next stages need (hover, descent_mid, touchdown, deepest, still).
import fs from 'node:fs';
import path from 'node:path';
import RAPIER from '@dimforge/rapier3d-compat';
import { CarPhysics, SHOWS } from '../src/physics.js';
import { MODELS } from '../src/models.js';

const showName = process.argv[2] || 'landing';
const seconds = Number(process.argv[3] || 3.5);
const out = process.argv[4] || `out/${showName}/motion.json`;
const modelName = process.argv[5] || 'roadster';
const FPS = 60;
const ON = 0.012;

await RAPIER.init();
const show = SHOWS[showName];
const model = MODELS[modelName];
const sim = new CarPhysics(RAPIER, model, show);
const su = model.suspension;
const r6 = (v) => Math.round(v * 1e6) / 1e6;
const b3 = (x, y, z) => [r6(x), r6(-z), r6(y)]; // physics vector -> Blender

// chassis frame of the physics (roll phi about the long axis through the pivot, then pitch theta
// about z) as a Blender position + quaternion
function chassis(s) {
  const py = sim.pivot[1]; // the pivot is on the centre line (z = 0) and the roll keeps x
  const [cp, sp, ct, st] = [Math.cos(s.phi), Math.sin(s.phi), Math.cos(s.theta), Math.sin(s.theta)];
  // origin = body + Rz(theta) (pivot - Rx(phi) pivot) = body + Rz(theta) (0, py (1 - cos phi), -py sin phi)
  const ry = py * (1 - cp);
  const wx = s.x - ry * st;
  const wy = s.y + ry * ct;
  const wz = -py * sp;
  const [cz, sz, cx, sx] = [Math.cos(s.theta / 2), Math.sin(s.theta / 2), Math.cos(s.phi / 2), Math.sin(s.phi / 2)];
  const q3 = [cz * cx, cz * sx, sz * sx, sz * cx]; // Rz(theta) * Rx(phi), w x y z
  return { pos: b3(wx, wy, wz), quat: [r6(q3[0]), r6(q3[1]), r6(-q3[3]), r6(q3[2])] };
}

const frames = [];
const events = sim.events.slice(0, 1).map((e) => ({ frame: 0, t: 0, type: 'phase', phase: e.phase }));
const n = Math.round(seconds * FPS);
const vzs = []; // the body's vertical speed per frame, m/s
let prevQ = null;
let prevOn = null;
let touched = false;
// the touchdown is the first wheel contact after the car has been in the air: a show that drives in (b) touches
// the floor from its first step and leaves it at the take-off; frame 0 (no contacts computed yet) counts as in the
// air only for a show that starts hanging (the landing)
const startsInAir = (show.start ?? 'drive') === 'hover';
let airborne = startsInAir;
for (let f = 0; f <= n; f++) {
  // frame 0 is the start before any step: Rapier has no suspension lengths and no thrust yet, so
  // its wheels hang at the rest length (in the air) and its thrust is the first frame's
  const s = f === 0 ? sim.state() : sim.step(1 / FPS);
  const c = chassis(s);
  if (prevQ && c.quat.reduce((a, v, i) => a + v * prevQ[i], 0) < 0) c.quat = c.quat.map((v) => -v); // keep the sign continuous
  prevQ = c.quat;
  const contact = model.wheels.map((_, i) => sim.vehicle.wheelIsInContact(i));
  const wheels = s.wheels.map((w, i) => {
    const len = f === 0 && !contact[i] ? su.rest : w.susp;
    return { spin: r6(w.spin), up: r6(su.eq - len), contact: contact[i] };
  });
  frames.push({ f, t: r6(f / FPS), phase: s.phase, pos: c.pos, quat: c.quat, wheels, thrust: s.nozzles.map((m) => r6(m.thrust)) });
  vzs.push(s.vy);
  if (f === 1) frames[0].thrust = frames[1].thrust;
}
// events: phases at the first frame that shows them, jets switching, touchdown
for (const e of sim.events.slice(1)) {
  const f = Math.ceil(e.t * FPS - 1e-6);
  if (f <= n) events.push({ frame: f, t: r6(f / FPS), type: 'phase', phase: e.phase, at: r6(e.t) });
}
frames.forEach((fr) => {
  const on = fr.thrust.map((v) => v > ON);
  if (prevOn) {
    on.forEach((o, i) => {
      if (o !== prevOn[i]) {
        const nz = model.nozzles[i];
        events.push({ frame: fr.f, t: fr.t, type: o ? 'ignite' : 'cutoff', nozzle: nz.name, group: nz.group });
      }
    });
  }
  prevOn = on;
  const down = fr.wheels.some((w) => w.contact);
  if (!down && (fr.f > 0 || startsInAir)) airborne = true;
  if (!touched && down && airborne) {
    touched = true;
    events.push({ frame: fr.f, t: fr.t, type: 'touchdown', wheels: model.wheels.filter((_, i) => fr.wheels[i].contact).map((w) => w.node), vz: r6(vzs[fr.f]) });
  }
});
events.sort((a, b) => a.frame - b.frame);

// marks: hover = the start; descent_mid = halfway down in height; touchdown = the first contact;
// deepest = the suspension most compressed after it; still = from here on for 0.2 s no motion
// (the chassis moves under 1 cm/s up or down, the wheels within 4 mm of the ride height)
const zs = frames.map((fr) => fr.pos[2]);
const xs = frames.map((fr) => fr.pos[0]);
const touch = events.find((e) => e.type === 'touchdown')?.frame ?? null;
const phaseFrame = (p) => events.find((e) => e.type === 'phase' && e.phase === p)?.frame ?? null;
// a show that drives in (b): the phases, the apex, and halfway down from the descent's start to the touchdown;
// after the touchdown also stop (it stands: under 5 mm/s), still (also no x motion), launch and cut = 2 frames
// before the launch (the end of the first clip and the start of the second, the frame the program holds: the
// launch's first frame and the motion blur of the one before it already move)
const marks = startsInAir ? { hover: 0 } : { drive: 0 };
if (!startsInAir) {
  for (const p of ['lift', 'flip', 'catch', 'hover', 'descend']) marks[p] = phaseFrame(p);
  marks.apex = zs.indexOf(Math.max(...zs));
}
if (touch !== null) {
  const from = startsInAir ? 0 : marks.descend ?? 0;
  const half = (zs[from] + zs[touch]) / 2;
  marks.descent_mid = frames.findIndex((fr, f) => f >= from && fr.pos[2] <= half);
  marks.touchdown = touch;
  let deep = touch;
  const deepTo = startsInAir ? frames.length : (phaseFrame('launch') ?? frames.length); // b: not the dash's squat
  for (let f = touch; f < deepTo; f++) if (Math.max(...frames[f].wheels.map((w) => w.up)) > Math.max(...frames[deep].wheels.map((w) => w.up))) deep = f;
  marks.deepest = deep;
  // by the motion itself: on the ground Rapier's body velocity keeps a residue of 1-2 cm/s while the
  // position stands still
  const moves = (f) => !startsInAir && Math.abs((xs[f] - xs[f - 1]) * FPS) >= 0.01;
  const calm = (f) => Math.abs((zs[f] - zs[f - 1]) * FPS) < 0.01 && frames[f].wheels.every((w) => Math.abs(w.up) < 0.004) && !moves(f);
  const still = frames.findIndex((_, f) => f > touch && f + 12 < frames.length && Array.from({ length: 13 }, (_, k) => calm(f + k)).every(Boolean));
  marks.still = still >= 0 ? still : null;
  if (!startsInAir) {
    marks.stop = frames.findIndex((_, f) => f > touch && Math.abs((xs[f] - xs[f - 1]) * FPS) < 0.005);
    const launch = events.find((e) => e.type === 'phase' && e.phase === 'launch' && e.frame > touch)?.frame ?? null;
    marks.launch = launch;
    marks.cut = launch !== null ? launch - 2 : null;
    if (marks.cut !== null && (marks.still === null || marks.still > marks.cut)) console.log(`WARNING: the car is not still before the cut (still ${marks.still}, cut ${marks.cut})`);
    else if (marks.cut !== null) {
      const bad = Array.from({ length: marks.cut - marks.still + 1 }, (_, k) => marks.still + k).filter((f) => !calm(f));
      if (bad.length) console.log(`WARNING: motion between still and cut at frames ${bad.join(',')}`);
    }
  }
}

const doc = {
  format: 'roadster-motion/1',
  show: showName,
  model: modelName,
  fps: FPS,
  frames_count: frames.length,
  axes: 'Blender: x right (the car forward), y away from the camera, z up; metres, radians, quat = w x y z',
  chassis: 'pos/quat place the chassis frame of src/models.js in Blender axes: origin on the floor under the car at ride height, x forward, y to the car\'s left (away from the camera), z up',
  car: {
    url: model.url,
    scale: model.scale ?? 1,
    yaw: model.yaw, // about z, turns the file's forward (-y after glTF import) to +x
    lift: model.lift ?? 0,
    pivot: b3(...sim.pivot),
    suspension: su,
  },
  wheels: model.wheels.map((w) => ({ node: w.node, caliper: w.caliper, pos: b3(w.x, (w.r ?? model.wheelRadius), w.z), r: w.r ?? model.wheelRadius, front: w.front })),
  nozzles: model.nozzles.map((m) => ({ name: m.name, group: m.group, pos: b3(m.x, m.y, m.z), dir: b3(...m.jet), r: m.r, max: m.group === 'side' ? model.sideMax : model.nozzleMax })),
  on_at_start: model.nozzles.filter((_, i) => frames[0].thrust[i] > ON).map((m) => m.name),
  marks,
  events,
  frames,
};
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(doc));
const ev = (type) => events.filter((e) => e.type === type).map((e) => `${e.nozzle ?? e.phase ?? ''}@${e.frame}`).join(' ');
console.log(`${out}: ${frames.length} frames (0..${((frames.length - 1) / FPS).toFixed(2)} s), ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
console.log('marks', JSON.stringify(marks));
console.log('phases', ev('phase'), '| ignite', ev('ignite') || '-', '| cutoff', ev('cutoff') || '-', '| touchdown', JSON.stringify(events.find((e) => e.type === 'touchdown')));
