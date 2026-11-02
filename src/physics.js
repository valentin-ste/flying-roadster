// Car physics, look test 2: drive in → vertical take-off on four jets → kickflip (a full roll
// about the long axis) on short attitude pulses → catch and hover → slow powered descent into
// its own cloud → dash off on the rear jets.
//
// Units are real: metres, seconds, kilograms, g = 9.81. A car that obeys real gravity at its
// real size reads as a car; scale the gravity and it reads as a toy on a table.
//
// Frame: x — along the screen to the right, y — up, z — towards the viewer. Rapier moves the
// body in x/y and pitches it about z (suspension, braking dive, squat). The roll of the
// kickflip is a separate 1-DOF rotation about the long axis through the centre of mass: it only
// happens in the air, where it does not touch the suspension, and it tilts the thrust of the
// nozzles, so a car on its side gets no lift from them.
//
// The autopilot is deliberately imperfect: it sees the state 40 ms late, the jets spool up
// with a lag, the flip is flown with discrete pulses and small gusts push the car around.

const G = 9.81;
const TAU = Math.PI * 2;
const LAG_STEPS = 10; // 10 substeps at 240 Hz = 42 ms of sensing delay
const PULSE = 0.05; // s: attitude thrusters fire in pulses of at least this length

export const SHOWS = {
  // A: as in look test 1 — a ~325 px car
  a: {
    px: 72, camDist: 60, camHeight: 2.4,
    x0: -2.6, v0: 7.5, xLift: 4.3, vDrift: 1.1,
    liftUp: 7.5, vCut: 6.6, flipDelay: 0.1, flipTime: 1.25,
    hover: 2.4, hoverTime: 0.45, descent: 1.1,
    launch: 26000, engineOut: 3000,
  },
  // B: camera closer, the car ~490 px, the tricks higher and sharper. After the touchdown (01.11) it brakes
  // smoothly to a full stop (stop: at most decel m/s², easing to |v| / tau + min as it slows, so the stop itself is
  // gentle), stands until rest s after the touchdown — the landing cloud has melted by then (3 s from the jets
  // leaving the floor, tools/blender/landing_jets.py --melt-time) with a margin — and only then dashes off from
  // a standstill. Before the touchdown it is the show of look test 3 to the last digit (tools/physics_regress.mjs)
  b: {
    px: 108, camDist: 40, camHeight: 1.6,
    x0: -2.4, v0: 7.5, xLift: 3.2, vDrift: 0.55,
    liftUp: 10, vCut: 7.1, flipDelay: 0.22, flipTime: 1.1,
    hover: 3.2, hoverTime: 0.35, descent: 1.5,
    stop: { decel: 1.2, tau: 0.25, min: 0.1 }, rest: 3.4,
    launch: 26000, engineOut: 2500,
  },
  // Landing, the first Blender clip: it starts already hanging on the four lift jets with the
  // nozzles 3 m above the floor (hover is the wheels' clearance: nozzles 0.12 m above the chassis
  // origin, the hanging wheels 0.07 m below it), hovers, comes down under control at 2 m/s,
  // flares below nearH to vTouch, touches, the valves close on the first wheel contact (cutLag,
  // s) and the car settles on its springs. No drive-in, no tricks, no dash. The car's middle at
  // x = 7 m, the middle of the 14 m screen of framing B. Numbers: node tools/tune_physics.mjs landing
  landing: {
    px: 108, camDist: 40, camHeight: 1.6,
    start: 'hover', x0: 6.933, v0: 0,
    hover: 2.81, hoverTime: 0.5, descent: 2.0, nearH: 0.9, vTouch: 0.8, cutLag: 0.025, settle: 0.7,
  },
};

const smoother = (t) => t * t * t * (t * (t * 6 - 15) + 10);
const smoother1 = (t) => 30 * t * t * (t - 1) * (t - 1);
const smoother2 = (t) => 60 * t * (2 * t * t - 3 * t + 1);
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

function wrapPi(a) {
  return a - TAU * Math.floor((a + Math.PI) / TAU);
}

function mulberry(seed) {
  let s = seed | 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// chassis vector -> world: roll phi about x, then pitch theta about z
export function rotate(theta, phi, x, y, z) {
  const cp = Math.cos(phi);
  const sp = Math.sin(phi);
  const y1 = y * cp - z * sp;
  const z1 = y * sp + z * cp;
  const ct = Math.cos(theta);
  const st = Math.sin(theta);
  return [x * ct - y1 * st, x * st + y1 * ct, z1];
}

export class CarPhysics {
  constructor(RAPIER, model, show, seed = 11) {
    this.m = model;
    this.s = show;
    this.rand = mulberry(seed);
    const b = model.body.box;
    this.mass = model.body.mass;
    this.pivot = [b.cx, b.cy, 0];
    this.Ip = (this.mass * ((2 * b.hx) ** 2 + (2 * b.hy) ** 2)) / 12;
    this.Ir = (this.mass * ((2 * b.hz) ** 2 + model.body.height ** 2)) / 12;

    const world = new RAPIER.World({ x: 0, y: -G, z: 0 });
    world.timestep = 1 / 240;
    this.world = world;
    world.createCollider(RAPIER.ColliderDesc.cuboid(500, 1, 50).setTranslation(0, -1, 0).setFriction(1));

    // a show either drives in (the default) or starts hanging on the lift jets at its hover clearance
    const start = show.start ?? 'drive';
    const su0 = model.suspension;
    const y0 = start === 'hover' ? show.hover + su0.rest - su0.eq : 0;
    const body = world.createRigidBody(
      RAPIER.RigidBodyDesc.dynamic().setTranslation(show.x0, y0, 0).setLinvel(show.v0, 0, 0).setCanSleep(false),
    );
    body.setEnabledTranslations(true, true, false, true);
    body.setEnabledRotations(false, false, true, true);
    world.createCollider(
      RAPIER.ColliderDesc.cuboid(b.hx, b.hy, b.hz)
        .setTranslation(b.cx, b.cy, 0)
        .setDensity(this.mass / (8 * b.hx * b.hy * b.hz))
        .setFriction(0.6)
        .setRestitution(0.05),
      body,
    );
    this.body = body;

    const su = model.suspension;
    const vehicle = world.createVehicleController(body);
    model.wheels.forEach((w, i) => {
      const r = w.r ?? model.wheelRadius;
      vehicle.addWheel({ x: w.x, y: r + su.eq, z: w.z }, { x: 0, y: -1, z: 0 }, { x: 0, y: 0, z: 1 }, su.rest, r);
      vehicle.setWheelSuspensionStiffness(i, su.stiffness);
      vehicle.setWheelSuspensionCompression(i, su.dampComp);
      vehicle.setWheelSuspensionRelaxation(i, su.dampRelax);
      vehicle.setWheelMaxSuspensionTravel(i, su.travel);
      vehicle.setWheelMaxSuspensionForce(i, 1e7);
      vehicle.setWheelFrictionSlip(i, 4);
    });
    this.vehicle = vehicle;

    this.down = model.nozzles.filter((n) => n.group === 'down');
    this.back = model.nozzles.filter((n) => n.group === 'back');
    this.side = model.nozzles.filter((n) => n.group === 'side');
    // roll torque per newton of each side jet: the car is pushed against the jet, along z
    this.sideArm = this.side.map((n) => (n.y - this.pivot[1]) * n.jet[2]);
    this.t = 0;
    this.phase = start;
    this.phaseT = 0;
    this.events = [{ t: 0, phase: start }];
    this.theta = 0;
    this.thetaWrapped = 0;
    this.phi = 0;
    this.phiRate = 0;
    this.rollTarget = 0;
    this.lift = start === 'hover' ? this.mass * G : 0; // hanging: the jets already carry the car
    this.hist = [];
    this.pulseUntil = -1;
    this.pulseForces = this.down.map(() => 0);
    this.pulseSide = [];
    this.gust = [0, 0];
    this.thrust = model.nozzles.map(() => 0);
    this.wheelSpin = model.wheels.map(() => 0);
    this.wheelRate = model.wheels.map(() => 0);
  }

  setPhase(p) {
    this.phase = p;
    this.phaseT = 0;
    const q = this.body.translation();
    this.events.push({ t: this.t, phase: p, x: q.x, y: q.y, vy: this.body.linvel().y, vx: this.body.linvel().x });
  }

  // chassis point -> world, rolling about the long axis through the centre of mass
  toWorld(x, y, z) {
    const [px, py, pz] = this.pivot;
    const [rx, ry, rz] = rotate(this.theta, this.phi, x - px, y - py, z - pz);
    const [ox, oy] = rotate(this.theta, 0, px, py, pz);
    const b = this.body.translation();
    return [b.x + ox + rx, b.y + oy + ry, rz + pz];
  }

  // lowest point of the hanging wheels above the floor
  clearance() {
    const m = this.m;
    let h = Infinity;
    for (const w of m.wheels) {
      const r = w.r ?? m.wheelRadius;
      const [, y] = this.toWorld(w.x, r + m.suspension.eq - m.suspension.rest, w.z);
      h = Math.min(h, y - r * Math.abs(Math.cos(this.phi)));
    }
    return h;
  }

  anyWheelDown() {
    for (let i = 0; i < this.m.wheels.length; i++) if (this.vehicle.wheelIsInContact(i)) return true;
    return false;
  }

  // forces of the four down nozzles for lift L (along the car's up) and torques about the centre
  // of mass: tp pitch (nose up > 0), tr roll; least-squares mixing, clipped to what jets can do
  mix(L, tp, tr) {
    const cx = this.pivot[0];
    let sx = 0;
    let sz = 0;
    for (const n of this.down) {
      sx += (n.x - cx) ** 2;
      sz += n.z ** 2;
    }
    return this.down.map((n) => clamp(L / this.down.length + (tp * (n.x - cx)) / sx - (tr * n.z) / sz, 0, this.m.nozzleMax));
  }

  substep(dt) {
    const s = this.s;
    const v = this.body.linvel();
    const p = this.body.translation();
    const h = this.clearance();
    this.hist.push({ phi: this.phi, phiRate: this.phiRate, theta: this.theta, omega: this.body.angvel().z, h, vy: v.y });
    if (this.hist.length > LAG_STEPS) this.hist.shift();
    const sen = this.hist[0];

    let L = 0;
    let tp = 0;
    let tr = 0;
    let back = 0;
    let engine = 0;
    let pulsed = false;
    const holdPitch = () => this.Ip * (36 * (0 - sen.theta) - 7.2 * sen.omega);
    const holdRoll = () => this.Ir * (49 * (this.rollTarget - sen.phi) - 7.7 * sen.phiRate);
    // cascaded: height error -> wanted climb rate (bounded) -> acceleration; jets can only push
    const altitude = (hd, vd, vMax = 3) => {
      const vc = clamp(1.6 * (hd - sen.h) + vd, -vMax, vMax);
      const a = clamp(4 * (vc - sen.vy), -G, 22);
      return (this.mass * (G + a)) / Math.max(Math.cos(sen.phi) * Math.cos(sen.theta), 0.5);
    };

    switch (this.phase) {
      case 'drive': {
        // brake to the take-off spot, still rolling a little: the car drifts while it flies
        const a = (v.x * v.x - s.vDrift * s.vDrift) / (2 * Math.max(s.xLift - p.x, 0.05));
        engine = (-this.mass * clamp(a, 0, 7)) / 4;
        if (p.x >= s.xLift) this.setPhase('lift');
        break;
      }
      case 'lift':
        L = this.mass * (G + s.liftUp) * Math.min(this.phaseT / 0.2, 1);
        tp = holdPitch();
        tr = holdRoll();
        if (v.y >= s.vCut) this.setPhase('coast');
        break;
      case 'coast':
        if (this.phaseT >= s.flipDelay) {
          this.flipFrom = this.t;
          this.setPhase('flip');
        }
        break;
      case 'flip': {
        // roll -360°: underside towards the viewer first
        const k = clamp((this.t - this.flipFrom) / s.flipTime, 0, 1);
        const phd = -TAU * smoother(k);
        const wd = (-TAU * smoother1(k)) / s.flipTime;
        const ad = (-TAU * smoother2(k)) / (s.flipTime * s.flipTime);
        tr = this.Ir * (ad + 60 * (phd - sen.phi) + 6 * (wd - sen.phiRate));
        tp = holdPitch();
        pulsed = true;
        if (k >= 1 && (Math.abs(this.phi + TAU) < 0.3 || (h < s.hover * 0.6 && v.y < 0))) {
          this.rollTarget = -TAU;
          this.setPhase('catch');
        }
        break;
      }
      case 'catch':
        L = altitude(s.hover, 0);
        tp = holdPitch();
        tr = holdRoll();
        if (this.phaseT > 0.4 && Math.abs(v.y) < 0.35) this.setPhase('hover');
        break;
      case 'hover':
        L = altitude(s.hover, 0);
        tp = holdPitch();
        tr = holdRoll();
        if (this.phaseT >= s.hoverTime) this.setPhase('descend');
        break;
      case 'descend': {
        const vTouch = s.vTouch ?? 0.55;
        const near = sen.h < (s.nearH ?? 0.6);
        const vd = near ? -vTouch : -s.descent;
        const hd = near ? sen.h : Math.max(s.hover - s.descent * this.phaseT, 0);
        L = altitude(hd, vd, near ? vTouch : s.descent);
        tp = holdPitch();
        tr = holdRoll();
        if (this.phaseT > 0.3 && this.anyWheelDown()) this.setPhase('settle');
        break;
      }
      case 'settle':
        if (s.rest) {
          // on the brakes (below) to a stop, standing until rest s after the touchdown
          if (this.phaseT >= s.rest) this.setPhase('launch');
          break;
        }
        if (this.phaseT >= (s.settle ?? 0.35)) this.setPhase(s.launch ? 'launch' : 'rest');
        break;
      case 'launch':
        back = s.launch * Math.min(this.phaseT / 0.08, 1);
        engine = s.engineOut;
        break;
      default:
        break;
    }

    // jets spool up and down with a lag; on touchdown a show may close the valves faster (cutLag)
    const lag = this.phase === 'settle' ? (s.cutLag ?? 0.06) : 0.06;
    this.lift += (L - this.lift) * Math.min(dt / lag, 1);
    let forces;
    let sideForces;
    if (pulsed) {
      // attitude in the air: discrete pulses, re-decided every PULSE. Roll goes to the side
      // jets first (pure torque); what they cannot give goes to the down nozzles.
      if (this.t >= this.pulseUntil) {
        const sideMax = this.m.sideMax ?? this.m.nozzleMax;
        this.pulseSide = this.side.map((n, i) => {
          const f = tr / this.sideArm[i];
          return f > 2500 ? clamp(Math.max(f, 7000), 0, sideMax) : 0;
        });
        const given = this.pulseSide.reduce((acc, f, i) => acc + f * this.sideArm[i], 0);
        this.pulseForces = this.mix(0, tp, tr - given).map((f) => (f > 2500 ? Math.max(f, 7000) : 0));
        this.pulseUntil = this.t + PULSE;
      }
      forces = this.pulseForces;
      sideForces = this.pulseSide;
    } else {
      forces = this.mix(this.lift, tp, tr);
      sideForces = this.side.map(() => 0);
    }

    // gusts while airborne: filtered noise, small, the autopilot corrects them
    const airborne = !this.anyWheelDown();
    for (let i = 0; i < 2; i++) this.gust[i] += ((this.rand() - 0.5) * 2 - this.gust[i]) * 0.02;
    const gustRoll = airborne ? this.gust[0] * 900 : 0;
    const gustPitch = airborne ? this.gust[1] * 1600 : 0;

    let rollTorque = gustRoll;
    this.down.forEach((n, i) => {
      const f = forces[i];
      this.thrust[this.m.nozzles.indexOf(n)] = f;
      if (f <= 0) return;
      const [wx, wy, wz] = this.toWorld(n.x, n.y, n.z);
      const [dx, dy] = rotate(this.theta, this.phi, -n.jet[0], -n.jet[1], -n.jet[2]);
      this.body.applyImpulseAtPoint({ x: dx * f * dt, y: dy * f * dt, z: 0 }, { x: wx, y: wy, z: wz }, true);
      rollTorque += -n.z * f;
    });
    this.back.forEach((n) => {
      const f = back / this.back.length;
      this.thrust[this.m.nozzles.indexOf(n)] = f;
      if (f <= 0) return;
      const [wx, wy, wz] = this.toWorld(n.x, n.y, n.z);
      const [dx, dy] = rotate(this.theta, this.phi, -n.jet[0], -n.jet[1], -n.jet[2]);
      this.body.applyImpulseAtPoint({ x: dx * f * dt, y: dy * f * dt, z: 0 }, { x: wx, y: wy, z: wz }, true);
    });
    this.side.forEach((n, i) => {
      const f = sideForces[i];
      this.thrust[this.m.nozzles.indexOf(n)] = f;
      rollTorque += f * this.sideArm[i];
    });
    if (gustPitch) this.body.applyTorqueImpulse({ x: 0, y: 0, z: gustPitch * dt }, true);

    // roll: free in the air, held by the wheels on the ground
    if (airborne) {
      this.phiRate += (rollTorque / this.Ir) * dt;
      this.phi += this.phiRate * dt;
    } else {
      this.phiRate *= 0.5;
      this.phi += (this.rollTarget - this.phi) * 0.2;
    }

    if (s.rest && (this.phase === 'settle' || this.phase === 'launch')) {
      // B on the ground after the touchdown: the brakes come on over 0.15 s, the deceleration eases off as the car
      // slows; Rapier's brake is the most impulse a wheel's rolling friction may take, so it stops the car and holds
      // it without ever pushing it back. Released for the dash
      let a = 0;
      if (this.phase === 'settle') {
        const st = s.stop;
        a = Math.min(st.decel, Math.abs(v.x) / st.tau + st.min) * smoother(Math.min(this.phaseT / 0.15, 1));
      }
      const imp = (this.mass * a * dt) / this.m.wheels.length;
      this.m.wheels.forEach((w, i) => this.vehicle.setWheelBrake(i, imp));
    }
    this.m.wheels.forEach((w, i) => this.vehicle.setWheelEngineForce(i, w.front && engine > 0 ? 0 : engine));
    this.vehicle.updateVehicle(dt);
    this.world.step();

    const q = this.body.rotation();
    const wrapped = 2 * Math.atan2(q.z, q.w);
    this.theta += wrapPi(wrapped - this.thetaWrapped);
    this.thetaWrapped = wrapped;

    const lv = this.body.linvel();
    const vx = lv.x * Math.cos(this.theta) + lv.y * Math.sin(this.theta);
    this.m.wheels.forEach((w, i) => {
      if (this.vehicle.wheelIsInContact(i)) this.wheelRate[i] = vx / (w.r ?? this.m.wheelRadius);
      else this.wheelRate[i] *= Math.exp(-dt / 1.2);
      this.wheelSpin[i] += this.wheelRate[i] * dt;
    });

    this.t += dt;
    this.phaseT += dt;
  }

  pose() {
    const b = this.body.translation();
    return {
      x: b.x,
      y: b.y,
      theta: this.theta,
      phi: this.phi,
      wheels: this.m.wheels.map((w, i) => ({
        node: w.node,
        susp: this.vehicle.wheelSuspensionLength(i) ?? this.m.suspension.rest,
        spin: this.wheelSpin[i],
      })),
    };
  }

  // one video frame; poses = the frame start plus every substep, for motion blur
  step(frameDt) {
    const n = Math.round(frameDt / this.world.timestep);
    const acc = this.m.nozzles.map(() => 0);
    const poses = [this.lastPose ?? this.pose()];
    for (let k = 0; k < n; k++) {
      this.substep(this.world.timestep);
      this.thrust.forEach((f, i) => (acc[i] += f / n));
      poses.push(this.pose());
    }
    this.lastPose = poses[poses.length - 1];
    const st = this.state(acc);
    st.poses = poses;
    return st;
  }

  state(meanThrust = this.thrust) {
    const b = this.body.translation();
    const v = this.body.linvel();
    return {
      t: this.t,
      phase: this.phase,
      x: b.x,
      y: b.y,
      theta: this.theta,
      phi: this.phi,
      vx: v.x,
      vy: v.y,
      omega: this.body.angvel().z,
      phiRate: this.phiRate,
      clearance: this.clearance(),
      wheels: this.pose().wheels,
      nozzles: this.m.nozzles.map((n, i) => {
        const [x, y, z] = this.toWorld(n.x, n.y, n.z);
        const [dx, dy, dz] = rotate(this.theta, this.phi, n.jet[0], n.jet[1], n.jet[2]);
        const max = n.group === 'side' ? (this.m.sideMax ?? this.m.nozzleMax) : this.m.nozzleMax;
        return { name: n.name, group: n.group, x, y, z, dx, dy, dz, thrust: meanThrust[i] / max };
      }),
    };
  }
}
