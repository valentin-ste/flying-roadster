// Everything that depends on the car model lives here, so a new model is one more entry:
// the file, how to turn it to face +x, the wheels, the suspension, the body and the nozzles.
//
// Chassis frame (metres): x — forward, y — up, z — lateral, +z is the side facing the viewer.
// Origin — the ground point under the car at design ride height.

export const MODELS = {
  // placeholder: the Ferrari 458 from the three.js examples
  ferrari: {
    url: 'assets/models/ferrari.glb',
    draco: true,
    groundShadow: 'assets/models/ferrari_ao.png', // baked contact shadow, 5.2 x 2.62 m
    yaw: -Math.PI / 2, // the model faces -z
    paint: 0xc00a0a,
    wheels: [
      { node: 'wheel_fl', x: 1.155, z: -0.84, front: true },
      { node: 'wheel_fr', x: 1.155, z: 0.83, front: true },
      { node: 'wheel_rl', x: -1.496, z: -0.82, front: false },
      { node: 'wheel_rr', x: -1.496, z: 0.82, front: false },
    ],
    wheelRadius: 0.358,
    suspension: { rest: 0.2, eq: 0.13, stiffness: 35, dampComp: 2.4, dampRelax: 3.0, travel: 0.16 },
    body: { mass: 1800, box: { hx: 2.2, hy: 0.28, hz: 0.95, cx: -0.17, cy: 0.55 }, height: 1.2 },
    // As on the real car: four nozzles under the floor next to the wheels blowing down, four
    // round ones low in the rear blowing back, and side jets that hold the orientation (the long
    // sideways jet in the ramp video). A side jet pushes along z, out of the screen plane, so
    // here it only rolls the car — the kickflip needs no lift from it.
    nozzles: [
      { name: 'fl', group: 'down', x: 1.155, y: 0.16, z: -0.6, jet: [0, -1, 0] },
      { name: 'fr', group: 'down', x: 1.155, y: 0.16, z: 0.6, jet: [0, -1, 0] },
      { name: 'rl', group: 'down', x: -1.496, y: 0.16, z: -0.6, jet: [0, -1, 0] },
      { name: 'rr', group: 'down', x: -1.496, y: 0.16, z: 0.6, jet: [0, -1, 0] },
      { name: 'b1', group: 'back', x: -2.22, y: 0.32, z: -0.48, jet: [-1, 0, 0] },
      { name: 'b2', group: 'back', x: -2.24, y: 0.32, z: -0.16, jet: [-1, 0, 0] },
      { name: 'b3', group: 'back', x: -2.24, y: 0.32, z: 0.16, jet: [-1, 0, 0] },
      { name: 'b4', group: 'back', x: -2.22, y: 0.32, z: 0.48, jet: [-1, 0, 0] },
      { name: 'sl', group: 'side', x: -0.2, y: 0.18, z: -0.97, jet: [0, 0, -1] },
      { name: 'sr', group: 'side', x: -0.2, y: 0.18, z: 0.97, jet: [0, 0, 1] },
    ],
    nozzleMax: 45000, // N per nozzle
    sideMax: 70000, // N per side jet: the long sideways attitude jets
    // meshes to recolour after loading: name -> material key (see main.js)
    materials: {
      body: 'paint',
      rim_fl: 'rim', rim_fr: 'rim', rim_rr: 'rim', rim_rl: 'rim',
      trim: 'rim',
      glass: 'glass',
      // the wheel-arch liners are in this mesh, but it carries the light interior material:
      // a pale ring around every tyre
      interior_dark: 'arch',
    },
  },

  // Tesla Roadster 2020 by metarex.4d, Sketchfab, CC BY 4.0 (CREDITS.md) — the 2017 design.
  // The file is in centimetres under a 0.01 root scale: 4.63 m long, wheels 0.65 / 0.69 m. The
  // real car is about 4.2 m, so the whole model is scaled by 0.908.
  roadster: {
    url: 'assets/models/roadster/tesla-roadster-2020.glb',
    draco: false,
    scale: 0.908,
    lift: 0.011, // the tyres reach 1.1 cm below the file's origin
    yaw: Math.PI / 2, // the model faces +z
    spinSign: 1,
    paint: 0xe9e9e5, // white pearl, as the car at the show (a touch below pure white, so reflections show)
    // wheel groups pivot on their own bounding-box centre; calipers follow the suspension only
    wheels: [
      { node: 'TR.DEF-Wheel.Ft.L', caliper: 'TR.DEF-WheelBrake.Ft.L', x: 1.393, z: -0.707, r: 0.295, front: true },
      { node: 'TR.DEF-Wheel.Ft.R', caliper: 'TR.DEF-WheelBrake.Ft.R', x: 1.393, z: 0.707, r: 0.295, front: true },
      { node: 'TR.DEF-Wheel.Bk.L', caliper: 'TR.DEF-WheelBrake.Bk.L', x: -1.259, z: -0.715, r: 0.312, front: false },
      { node: 'TR.DEF-Wheel.Bk.R', caliper: 'TR.DEF-WheelBrake.Bk.R', x: -1.259, z: 0.715, r: 0.312, front: false },
    ],
    wheelRadius: 0.3,
    suspension: { rest: 0.2, eq: 0.13, stiffness: 35, dampComp: 2.4, dampRelax: 3.0, travel: 0.16 },
    body: { mass: 1900, box: { hx: 2.08, hy: 0.25, hz: 0.84, cx: 0.067, cy: 0.5 }, height: 1.07, length: 4.2, width: 1.72 },
    // Lift nozzles sit under the floor inboard of the wheels — where the jet comes from must be
    // obvious, not out of a wheel. Four round ones in the rear diffuser for the dash, small side
    // jets for the roll. r — exit radius, m.
    nozzles: [
      { name: 'fl', group: 'down', x: 0.95, y: 0.12, z: -0.42, r: 0.08, jet: [0, -1, 0] },
      { name: 'fr', group: 'down', x: 0.95, y: 0.12, z: 0.42, r: 0.08, jet: [0, -1, 0] },
      { name: 'rl', group: 'down', x: -0.81, y: 0.12, z: -0.42, r: 0.08, jet: [0, -1, 0] },
      { name: 'rr', group: 'down', x: -0.81, y: 0.12, z: 0.42, r: 0.08, jet: [0, -1, 0] },
      { name: 'b1', group: 'back', x: -1.98, y: 0.27, z: -0.36, r: 0.065, jet: [-1, 0, 0] },
      { name: 'b2', group: 'back', x: -1.98, y: 0.27, z: -0.12, r: 0.065, jet: [-1, 0, 0] },
      { name: 'b3', group: 'back', x: -1.98, y: 0.27, z: 0.12, r: 0.065, jet: [-1, 0, 0] },
      { name: 'b4', group: 'back', x: -1.98, y: 0.27, z: 0.36, r: 0.065, jet: [-1, 0, 0] },
      { name: 'sl', group: 'side', x: 0.067, y: 0.16, z: -0.86, r: 0.035, jet: [0, 0, -1] },
      { name: 'sr', group: 'side', x: 0.067, y: 0.16, z: 0.86, r: 0.035, jet: [0, 0, 1] },
    ],
    nozzleMax: 45000,
    sideMax: 70000,
    // by material name: the paint and the cabin glass get our materials; any other glass with
    // transmission becomes a plain translucent cover (transmission costs a whole extra pass)
    materialNames: {
      car_main_paint: 'paint',
      Glass_mid_tint: 'darkGlass',
      Glass_Tint_max: 'darkGlass',
    },
  },
};
