// Physics regression: runs the approved shows (the tricks a and b, the landing) without rendering
// and compares them frame by frame with the saved references in tools/physics_regress/<show>.json
// (in git). About a second. Run it after any change to the physics (src/physics.js, the physics
// numbers in src/models.js, Rapier's version):
//   node tools/physics_regress.mjs           -> one line per show and OK, or each show's first divergence (exit 1)
//   node tools/physics_regress.mjs --update  -> rewrites the references: only after the change is approved
// Per frame (60 fps, the Roadster): the phase, the body x, y, pitch theta, roll phi, each wheel's
// suspension length and spin, each nozzle's thrust (0..1 of its maximum, the frame's mean).
// Tolerance 1e-4 in metres, radians and thrust fractions: the physics is deterministic (seeded
// gusts, Rapier in WebAssembly), so the same code gives the same numbers to the last digit.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import RAPIER from '@dimforge/rapier3d-compat';
import { CarPhysics, SHOWS } from '../src/physics.js';
import { MODELS } from '../src/models.js';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIR = path.join(ROOT, 'tools', 'physics_regress');
const RUNS = { a: 600, b: 750, landing: 210 }; // frames: a leaves the screen at ~556, b (01.11: stops, stands 3.4 s) at ~735 with its jets, the landing is motion.json's 3.5 s
const MODEL = 'roadster';
const FPS = 60;
const TOL = 1e-4;
const update = process.argv.includes('--update');
const rapierVersion = JSON.parse(fs.readFileSync(path.join(ROOT, 'node_modules/@dimforge/rapier3d-compat/package.json'), 'utf8')).version;
const r6 = (v) => Math.round(v * 1e6) / 1e6;

const t0 = performance.now();
await RAPIER.init();
const model = MODELS[MODEL];
const wheelNames = model.wheels.map((w) => `${w.front ? 'f' : 'r'}${w.z < 0 ? 'l' : 'r'}`);
const fields = ['x', 'y', 'theta', 'phi', ...wheelNames.map((n) => `susp.${n}`), ...wheelNames.map((n) => `spin.${n}`), ...model.nozzles.map((n) => `thrust.${n.name}`)];

function run(show, frames) {
  const sim = new CarPhysics(RAPIER, model, SHOWS[show]);
  const data = [];
  const phases = [];
  for (let f = 0; f < frames; f++) {
    const s = sim.step(1 / FPS);
    if (!phases.length || phases[phases.length - 1][1] !== s.phase) phases.push([f, s.phase]);
    data.push([s.x, s.y, s.theta, s.phi, ...s.wheels.map((w) => w.susp), ...s.wheels.map((w) => w.spin), ...s.nozzles.map((n) => n.thrust)].map(r6));
  }
  return { phases, data };
}

// the phase of every frame from the run-length list [[first frame, phase], ...]
const phaseAt = (phases, f) => phases.reduce((p, [g, name]) => (g <= f ? name : p), null);
const fmt = (v) => (typeof v === 'number' ? v.toFixed(6) : v);

let failed = false;
for (const [show, frames] of Object.entries(RUNS)) {
  const cur = run(show, frames);
  const file = path.join(DIR, `${show}.json`);
  if (update) {
    fs.mkdirSync(DIR, { recursive: true });
    const doc = { format: 'roadster-physics-regress/1', show, model: MODEL, fps: FPS, frames, rapier: rapierVersion, fields, phases: cur.phases, data: cur.data };
    // one frame per line: a change shows in git diff as the frames it moved
    fs.writeFileSync(file, JSON.stringify(doc).replace('"data":[[', '"data":[\n[').replaceAll('],[', '],\n[') + '\n');
    console.log(`${show}: reference written, ${frames} frames -> ${path.relative(ROOT, file)} (${(fs.statSync(file).size / 1024).toFixed(0)} KB)`);
    continue;
  }
  if (!fs.existsSync(file)) {
    console.log(`${show}: no reference ${path.relative(ROOT, file)} — make it with --update`);
    failed = true;
    continue;
  }
  const ref = JSON.parse(fs.readFileSync(file, 'utf8'));
  const note = ref.rapier !== rapierVersion ? ` (the reference was made with Rapier ${ref.rapier}, now ${rapierVersion})` : '';
  if (ref.fields.join() !== fields.join() || ref.frames !== frames) {
    console.log(`${show}: the reference's fields or length differ from this tool — remake it with --update after checking why`);
    failed = true;
    continue;
  }
  let worst = 0;
  let first = null;
  for (let f = 0; f < frames && !first; f++) {
    const [pr, pc] = [phaseAt(ref.phases, f), phaseAt(cur.phases, f)];
    const bad = [];
    if (pr !== pc) bad.push(`phase ${pc}, reference ${pr}`);
    fields.forEach((name, i) => {
      const d = Math.abs(cur.data[f][i] - ref.data[f][i]);
      worst = Math.max(worst, d);
      if (!(d <= TOL)) bad.push(`${name} ${fmt(cur.data[f][i])}, reference ${fmt(ref.data[f][i])} (off by ${d.toExponential(1)})`);
    });
    if (bad.length) first = { f, phase: pc, bad };
  }
  if (first) {
    failed = true;
    const more = first.bad.length > 4 ? `; and ${first.bad.length - 4} more` : '';
    console.log(`${show}: DIVERGES at frame ${first.f} (t=${((first.f + 1) / FPS).toFixed(3)} s, phase ${first.phase}): ${first.bad.slice(0, 4).join('; ')}${more}${note}`);
  } else {
    console.log(`${show}: ${frames} frames match, largest difference ${worst.toExponential(1)} (tolerance ${TOL})`);
  }
}
const secs = ((performance.now() - t0) / 1000).toFixed(1);
console.log(update ? `references written in ${secs} s` : failed ? `FAIL (${secs} s)` : `OK (${secs} s)`);
process.exit(failed ? 1 : 0);
