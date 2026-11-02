// Runs the physics alone (no rendering) and prints the trajectory, so a show can be tuned in
// seconds: node tools/tune_physics.mjs [a|b|landing] [frames] [roadster|ferrari]
// The model defaults to the Roadster, the product's car (until 26.10 this tool always ran the
// Ferrari placeholder). A show that starts in the air (the landing) also prints its numbers:
// the nozzles' height, descent and touchdown speed, how far the suspension travels and when the
// car is still.
import RAPIER from '@dimforge/rapier3d-compat';
import { CarPhysics, SHOWS } from '../src/physics.js';
import { MODELS } from '../src/models.js';

await RAPIER.init();
const variant = process.argv[2] || 'a';
const show = SHOWS[variant];
const landing = show.start === 'hover';
const frames = Number(process.argv[3] || (landing ? 200 : 560));
const model = MODELS[process.argv[4] || 'roadster'];
const sim = new CarPhysics(RAPIER, model, show);
const FPS = 60;
const ON = 0.012; // a jet counts as burning above this fraction of its maximum (as src/jet3d.js)
const eq = model.suspension.eq;
const rest = model.suspension.rest;
const deg = (r, d = 0) => ((r * 180) / Math.PI).toFixed(d);
const cm = (m) => (m * 100).toFixed(1);
let maxY = -Infinity;
let offAt = null;
const screenW = 1512 / show.px;
const L = { vMax: 0, touch: null, out: null, minS: Infinity, minAt: null, reb: -Infinity, still: null, calmFrom: null };
for (let f = 0; f < frames; f++) {
  const s = sim.step(1 / FPS);
  maxY = Math.max(maxY, s.y);
  if (offAt === null && s.phase === 'launch' && s.x - 2.4 > screenW) offAt = f;
  const downs = s.nozzles.filter((n) => n.group === 'down');
  if (landing) {
    if (f === 0) [L.nozzles, L.prevY] = [downs.map((n) => n.y), s.y];
    L.vMax = Math.max(L.vMax, -s.vy);
    const lens = s.wheels.map((w) => w.susp);
    if (!L.touch && sim.anyWheelDown()) L.touch = { f, t: s.t, vy: s.vy };
    if (L.touch && !L.out && Math.max(...downs.map((n) => n.thrust)) < ON) L.out = s.t;
    if (L.touch && Math.min(...lens) < L.minS) [L.minS, L.minAt] = [Math.min(...lens), s.t];
    if (L.minAt !== null && s.t > L.minAt) L.reb = Math.max(L.reb, ...lens);
    // still: from here on for 0.2 s the body moves under 1 cm/s up or down (by its position: on the
    // ground Rapier's velocity keeps a residue of 1-2 cm/s) and the wheels are within 4 mm of the ride height
    const calm = L.touch && f > L.touch.f && Math.abs((s.y - L.prevY) * FPS) < 0.01 && lens.every((x) => Math.abs(x - eq) < 0.004);
    L.prevY = s.y;
    if (!calm) L.calmFrom = null;
    else if (L.calmFrom === null) L.calmFrom = s.t;
    if (!L.still && L.calmFrom !== null && s.t - L.calmFrom >= 0.2 - 1e-6) L.still = L.calmFrom;
  }
  if (f % (landing ? 6 : 15) === 0) {
    const down = downs.map((n) => n.thrust.toFixed(landing ? 3 : 2)).join('/');
    const back = s.nozzles.find((n) => n.group === 'back').thrust.toFixed(2);
    const tail = landing
      ? `nozzles=${(downs.reduce((a, n) => a + n.y, 0) / downs.length).toFixed(2)} susp(cm up)=${s.wheels.map((w) => cm(eq - w.susp)).join('/')}`
      : `back=${back}`;
    console.log(
      `f${String(f).padStart(3)} t=${s.t.toFixed(2)} ${s.phase.padEnd(7)} x=${s.x.toFixed(2)} y=${s.y.toFixed(2)} h=${s.clearance.toFixed(2)} ` +
        `pitch=${deg(s.theta, landing ? 1 : 0)} roll=${deg(s.phi)} vx=${s.vx.toFixed(2)} vy=${s.vy.toFixed(2)} down=${down} ${tail}`,
    );
  }
}
console.log('events', sim.events.map((e) => `${e.phase}@${e.t.toFixed(2)}${e.x !== undefined ? ` x=${e.x.toFixed(2)}` : ''}`).join(' '));
console.log('maxY', maxY.toFixed(2), 'screen', screenW.toFixed(1), 'm wide; car off-screen at frame', offAt);
if (landing && L.touch) {
  console.log(
    `landing: lift nozzles ${Math.min(...L.nozzles).toFixed(2)}-${Math.max(...L.nozzles).toFixed(2)} m above the floor at the start; ` +
      `descent up to ${L.vMax.toFixed(2)} m/s; touchdown at ${L.touch.t.toFixed(2)} s, ${(-L.touch.vy).toFixed(2)} m/s; ` +
      `jets under ${ON * 100}% ${((L.out ?? NaN) - L.touch.t).toFixed(2)} s after it`,
  );
  console.log(
    `suspension: hanging ${cm(rest - eq)} cm below the ride height in the air; deepest ${cm(rest - L.minS)} cm from hanging = ` +
      `${cm(eq - L.minS)} cm past the ride height, ${(L.minAt - L.touch.t).toFixed(2)} s after touchdown; rebound ` +
      `${cm(L.reb - eq)} cm over the ride height; still (for 0.2 s under 1 cm/s, wheels within 4 mm) from ${L.still?.toFixed(2) ?? '-'} s`,
  );
}
