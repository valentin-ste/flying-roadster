"""Jet probe A2: the Pipe Leak jet made long (down to the floor, 3 m), a bright core inside a faint
bluish haze, smeared by motion; night stage with a red floor light, and the day desktop. No car,
stills only.

Builds on tools/blender/jet_probe.py (probe A): the same asset, its measurements (source, axis,
densest value), the same nozzle bell and voxel -> world mapping. Read that docstring first.
What is new, and why:
  - The asset's centre is saturated: density sits at its maximum 0.048 over the first ~100 voxels,
    so a threshold on density alone (probe A) gives an opaque flat-topped column with hard edges,
    and there is no structure inside it to show. A2 splits the gas into two components of one
    material:
      core = Kc * smoothstep(n; lo, hi) * exp(-(r / rc)^2) * fade(d) * exp(-d / decay) * cells(d)
             white, the dense centre narrowed by a Gaussian around the nozzle axis (rc from
             --core-r[0] at the exit to --core-r[1] at the end of the fade), gone by ~1 m; cells —
             bright beads every 0.42 m, as Tesla's jets show at 34.5 s (shock cells):
             floor + (1 - floor) * ((1 + cos(2 pi (d - first) / period)) / 2)^2;
      haze = Kh * smoothstep(h; lo, hi) (or h^p) * streaks * (1 -> --haze-end at the floor)
             no threshold below lo, a blue albedo (white haze vanishes on a light desktop and next
             to the white core), streaks — noise stretched along the flow (~3 cm x 40 cm): the
             averaged gas alone is a smooth cone, Tesla's jets are streaky;
    n = density / 0.048, h = haze / 0.048, r — distance from the nozzle axis, d — below the exit.
  - The VDBs are prepared once per moment with Blender's own openvdb + numpy and cached in
    WORK/jet-probe-a2/vdb/ (outside git): --smear consecutive simulation frames
    averaged (motion smear: the eddies travel ~3.5 voxels per frame, measured by correlating frames
    200-211), a box blur along the axis (--axial, radius in voxels) that closes the gaps between the
    averaged copies, and a second grid 'haze' = that field blurred across and along (--haze-sigma,
    Gaussian from 3 box passes). ~0.5 s per moment, one volume object, so the smear costs no render
    time; --copies N renders N overlapping objects instead, the cost of probe A's live --smear.
  - Long jet: 1.25 cm per voxel across, stretch 2.4 along (3 cm per voxel). The asset's measured
    widths (time-averaged) then give ~10 cm at the exit and ~45-50 cm at the floor (half maximum
    of the rendered brightness), like Tesla's jets at 34.5 s of The Kickflip.
  - The frame ends at the floor, --floor metres below the exit; the gas is cut there.
  - Look b, the night stage of probe A, bluer and dimmer, the stage spot aimed at the upper jet,
    plus a red disk light lying on the floor under the jet shining up (Tesla's stage: a red LED
    strip and a red-lit floor that turn the lower jets pink; E ~ 1/(R^2 + h^2) fades it upwards).
    Look a, the studio light of probe A (key made bigger), for the desktop wallpaper.
  - Presets v1-v3 (--preset): what differs is haze density and core sharpness.

Clip (probe A3, --clip): the jet switches on, runs steady and switches off, with the asset's own
timing: the asset is 60 frames/s, so at --fps 30 every second VDB frame. The asset holds the jet for
6.4 s (switched on at VDB frame ~2, reaches the floor 3 m down at ~18, the valve closes at ~383, the
tail clears the 3 m by ~414; it starts a second puff at ~418), so the clip plays the switching-on
from VDB 0 and the switching-off backwards from --off-end, and blends the two runs of the steady jet
into each other over --blend output frames (density weighted, smoothstep). --flow moves the streaky
noise along the axis (m/s, + = away from the nozzle), --shimmer changes it with time (the 4th noise
dimension per second): Tesla's streaks stand nearly still and change from frame to frame (see
tools/jet_measure.py speed). The cells stay put: Tesla's are standing shock cells.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/jet_probe_a2.py -- \
        out/jet-probe-a2 --preset v2 --look b [--moments on=6,steady=200,off=389 --samples 128 ...]
      Drafts: --px 210 --ppm 108 --samples 24 (a quarter of the pixels, ~12 s a frame on an M1 Pro).
      Clip: ... -- out/jet-probe-a3 --preset v2 --look b --clip --flow 0.75 --shimmer 6 --samples 24 --step-rate 4
            [--frames 30-34] (~15 s a frame; step rate 4 changes the profile by under 2%, tools/jet_measure.py)
Out:  OUT/<tag>-<look>-<moment>.png, 420x728 RGBA with a transparent background, the floor at the
      bottom edge; a clip: OUT/<tag>-<look>-clip/0000.png ...
"""
import argparse
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np
import openvdb as vdb
from mathutils import Matrix, Vector

# Parameter sets of the probe (what differs: haze density and core sharpness); the rest is common.
PRESETS = {
    "v1": dict(core_gain=350.0, core_r="0.035,0.02", cells="0.42,0.08,0.08", haze_gain=0.7,
               haze_sigma="1,2", haze_edge="0.05,0.7", streaks="0.35,3,40"),  # sharp core, light haze
    "v2": dict(core_gain=300.0, core_r="0.04,0.025", cells="0.42,0.08,0.1", haze_gain=1.0,
               haze_sigma="1,2", haze_edge="0.05,0.7", streaks="0.35,3,40"),  # the middle
    "v3": dict(core_gain=200.0, core_r="0.05,0.03", cells="0.42,0.08,0.25", haze_gain=1.6,
               haze_sigma="1.5,3", haze_edge="", haze_power=0.7, streaks="0.25,3,40"),  # soft core, dense soft haze
}
# the downloaded assets and the caches, outside git: $ROADSTER_WORK, or work/ in this repository (README)
WORK = os.environ.get("ROADSTER_WORK") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "work")
ap = argparse.ArgumentParser(prog="jet_probe_a2.py")
ap.add_argument("out")
ap.add_argument("--preset", default="v2", choices=sorted(PRESETS), help="parameter set; the options below override it")
ap.add_argument("--vdb", default=os.path.join(WORK, "blendkit/pipe-leak/extracted/caches/(A) Pipe Leak"))
ap.add_argument("--cache", default=os.path.join(WORK, "jet-probe-a2", "vdb"))
ap.add_argument("--look", default="b", choices=["a", "b"])
ap.add_argument("--tag", default=None, help="file name prefix (default: the preset)")
ap.add_argument("--moments", default="steady=200", help="name=VDB frame (the middle of the smear), comma-separated; "
                "switching on: on=6, off: off=389")
ap.add_argument("--vox", type=float, default=0.0125, help="metres per voxel across the jet")
ap.add_argument("--stretch", type=float, default=2.4, help="stretch along the axis")
ap.add_argument("--exit-r", type=float, default=0.08, help="nozzle exit radius, m (src/models.js)")
ap.add_argument("--exit-d", type=float, default=14.0, help="voxels from the point source to the exit")
ap.add_argument("--floor", type=float, default=3.0, help="floor below the exit, m: the bottom edge of the frame")
ap.add_argument("--smear", type=int, default=3, help="simulation frames averaged into one (motion smear)")
ap.add_argument("--axial", type=int, default=1, help="box blur radius along the axis, voxels")
ap.add_argument("--haze-sigma", default="1,2", help="haze blur, across,along, voxels")
ap.add_argument("--core-gain", type=float, default=300.0, help="core extinction per metre at full weight")
ap.add_argument("--core-lo", type=float, default=0.3, help="core smoothstep on n = density/0.048: from")
ap.add_argument("--core-hi", type=float, default=0.9, help="... to")
ap.add_argument("--core-r", default="0.04,0.025", help="core Gaussian radius at the exit and at the end of its fade, m")
ap.add_argument("--core-fade", default="0.0,1.3", help="the core fades out between these distances below the exit, m")
ap.add_argument("--core-decay", type=float, default=0.35, help="and decays as exp(-d / this), m (0: off)")
ap.add_argument("--cells", default="0.42,0.08,0.1", help="bright cells along the core like Tesla's (shock diamonds): "
                "period,first peak,floor, m (0: off)")
ap.add_argument("--haze-gain", type=float, default=1.0, help="haze extinction per metre per unit of h")
ap.add_argument("--haze-power", type=float, default=1.0, help="haze = h^power (when no --haze-edge)")
ap.add_argument("--haze-edge", default="0.05,0.7", help="lo,hi: haze = smoothstep(h; lo, hi) instead of h^power - the "
                "outline of the gas shows (fluffy edges); empty: off")
ap.add_argument("--streaks", default="0.35,3,40", help="amp,across,along: streaky noise on the haze, feature sizes in cm; "
                "empty: off")
ap.add_argument("--haze-end", type=float, default=0.9, help="haze weight at the floor (1 at the exit)")
ap.add_argument("--haze-color", default="b4ccf0", help="haze albedo, sRGB hex: blue, so the haze stays blue next to the "
                "white core and reads on a light desktop")
ap.add_argument("--aniso", type=float, default=0.2, help="core anisotropy")
ap.add_argument("--haze-aniso", type=float, default=0.3)
ap.add_argument("--copies", type=int, default=1, help="render the volume as N overlapping objects (cost of a live smear)")
ap.add_argument("--samples", type=int, default=128)
ap.add_argument("--bounces", type=int, default=8, help="volume bounces: steam is white from multiple scattering")
ap.add_argument("--px", type=int, default=420, help="frame width, px")
ap.add_argument("--ppm", type=float, default=216.0, help="pixels per metre (variant B: 108 pt/m, x2 on Retina)")
ap.add_argument("--key", type=float, default=1.0, help="key light multiplier")
ap.add_argument("--rim", type=float, default=1.0, help="rim (back) light multiplier (look b)")
ap.add_argument("--red", type=float, default=1.0, help="red floor light multiplier (look b)")
ap.add_argument("--unbiased", action="store_true", help="Cycles' unbiased volumes: grainy alpha below ~256 samples")
ap.add_argument("--step-rate", type=float, default=1.0, help="Cycles volume step rate (bigger: faster, coarser)")
ap.add_argument("--clip", action="store_true", help="render a clip (switch on, steady, switch off) instead of --moments")
ap.add_argument("--fps", type=int, default=30, help="clip frame rate")
ap.add_argument("--vdb-fps", type=int, default=60, help="the asset's frame rate (VDB frames per second)")
ap.add_argument("--length", type=int, default=75, help="clip length, output frames")
ap.add_argument("--on-at", type=int, default=5, help="output frame that shows VDB frame 0 (empty frames before it)")
ap.add_argument("--off-end", type=int, default=414, help="VDB frame of the last output frame (the tail just cleared)")
ap.add_argument("--blend", default="25,45", help="output frames over which the switching-on run blends into the "
                "switching-off run")
ap.add_argument("--flow", type=float, default=0.0, help="the streaky noise moves along the axis at this speed, m/s")
ap.add_argument("--shimmer", type=float, default=0.0, help="the streaky noise changes at this rate (4D noise W per "
                "second); 0: 3D noise as in the stills")
ap.add_argument("--frames", default="", help="render only these output frames of the clip, e.g. 30-34")
ap.add_argument("--build-only", action="store_true", help="set up the scene and render nothing: for scripts that run this "
                "one and add to its scene (tools/blender/cloud_probe_b.py), so the jet stays exactly this one")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap.set_defaults(**PRESETS[ap.parse_known_args(argv)[0].preset])
args = ap.parse_args(argv)
args.tag = args.tag or args.preset
OUT = os.path.abspath(args.out)
os.makedirs(OUT, exist_ok=True)

# --- the asset, measured (tools/blender/jet_probe.py) ---
VOXEL = 0.1  # VDB units per voxel
SRC_IJK = (159.5, 63.0, 116.0)  # the jet's point source, voxel index
ORIGIN = Vector((-16.0, -22.4, 0.0))  # voxel (0, 0, 0) in VDB units
SRC = ORIGIN + Vector(SRC_IJK) * VOXEL
AXIS = Vector((-0.003, 1.0, -0.166)).normalized()
RHO_MAX = 0.048

R_EXIT = args.exit_r
BELL = R_EXIT * 1.9
AX_VOX = args.vox * args.stretch  # metres per voxel along the axis
EXIT_D = args.exit_d
FLOOR = args.floor
TOP = BELL + 0.22  # frame top above the exit, m (as probe A)


# --- VDB preparation: smear in time, blur along the axis, a blurred 'haze' grid ---
def box(a, r, axis):
    """Box blur of radius r (voxels) along one axis, zero outside."""
    if r < 1:
        return a
    a = np.moveaxis(a, axis, 0)
    c = np.concatenate([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0, dtype=np.float64)], axis=0)
    i = np.arange(a.shape[0])
    lo, hi = np.clip(i - r, 0, a.shape[0]), np.clip(i + r + 1, 0, a.shape[0])
    return np.moveaxis(((c[hi] - c[lo]) / (2 * r + 1)).astype(np.float32), 0, axis)


def gauss(a, sigma, axis):
    """Gaussian blur from three box passes: 3 (w^2 - 1) / 12 = sigma^2, w = 2r + 1."""
    r = round((math.sqrt(4 * sigma * sigma + 1) - 1) / 2)
    for _ in range(3):
        a = box(a, r, axis)
    return a


Y_END = min(448, int(SRC_IJK[1] + EXIT_D + FLOOR / AX_VOX + 24))  # past the floor, room for the blur
B0, B1 = (60, 50, 30), (260, Y_END, 230)  # dense box in voxel index space (the jet: x 80-230, z 49-193)
HS = [float(v) for v in args.haze_sigma.split(",")]


def smeared(frame, shape):
    acc = np.zeros(shape, np.float32)
    first = max(0, frame - args.smear // 2)
    xform = None
    for f in range(first, first + args.smear):
        g = vdb.read(os.path.join(args.vdb, f"Pipe Leak{f:03d}.vdb"), "density")
        xform = xform or g.transform
        a = np.zeros(shape, np.float32)
        g.copyToArray(a, ijk=B0)
        acc += a
    return acc / args.smear, xform


def prepared(frame, frame_b=None, w=0.0):
    """The cached VDB of a moment; with frame_b, (1 - w) * frame + w * frame_b (a blend of two moments)."""
    key = f"f{frame:03d}-n{args.smear}-ax{args.axial}-h{HS[0]:g}x{HS[1]:g}-y{Y_END}"
    if frame_b is not None:
        key = f"f{frame:03d}+f{frame_b:03d}w{w:.3f}" + key[4:]
    path = os.path.join(args.cache, key + ".vdb")
    if os.path.exists(path):
        return path
    t0 = time.time()
    shape = tuple(b - a for a, b in zip(B0, B1))
    acc, xform = smeared(frame, shape)
    if frame_b is not None:
        acc = (1 - w) * acc + w * smeared(frame_b, shape)[0]
    acc = box(acc, args.axial, 1)  # VDB +y is the axis to within 9 deg
    haze = gauss(gauss(gauss(acc, HS[0], 0), HS[1], 1), HS[0], 2)
    grids = []
    for name, arr in (("density", acc), ("haze", haze)):
        g = vdb.FloatGrid()
        g.copyFromArray(np.ascontiguousarray(arr, np.float32), ijk=B0, tolerance=2e-5)  # it reads the raw buffer
        g.name = name
        g.transform = xform
        grids.append(g)
    os.makedirs(args.cache, exist_ok=True)
    vdb.write(path, grids=grids)
    print(f"jet_probe_a2: prepared {key} in {time.time() - t0:.1f} s")
    return path


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 60


def linear(hex_rgb):
    c = [((hex_rgb >> s) & 255) / 255 for s in (16, 8, 0)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c) + (1.0,)


def metal(name, hex_rgb, metallic, roughness):
    m = bpy.data.materials.new(name)
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = linear(hex_rgb)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = roughness
    return m


# --- the nozzle bell (as probe A): exit at the origin, throat BELL above, the jet goes down (-z) ---
def lathe(name, profile, mat, inward):
    bm = bmesh.new()
    seg = 48
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new((r * math.cos(2 * math.pi * k / seg), r * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)])
    for a, b in zip(rings, rings[1:]):
        for k in range(seg):
            f = (a[k], a[(k + 1) % seg], b[(k + 1) % seg], b[k])
            bm.faces.new(f[::-1] if inward else f)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob


t = R_EXIT * 0.62
prof = [(t, BELL), (t * 1.03, BELL * 0.72), (R_EXIT * 0.86, BELL * 0.3), (R_EXIT, 0.0)]
lathe("bell-inner", prof, metal("inner", 0x141518, 0.85, 0.35), inward=True)
lathe("bell-outer", [(r + R_EXIT * 0.12, z) for r, z in prof], metal("outer", 0x5C5F66, 0.95, 0.3), inward=False)
bpy.ops.mesh.primitive_torus_add(major_radius=R_EXIT * 1.06, minor_radius=R_EXIT * 0.09, major_segments=64, minor_segments=12)
rim = bpy.context.active_object
rim.data.materials.append(metal("rim", 0xD2D5DB, 1.0, 0.16))
for p in rim.data.polygons:
    p.use_smooth = True
bpy.ops.mesh.primitive_circle_add(vertices=32, radius=t * 1.05, fill_type="NGON", location=(0, 0, BELL * 0.98))
throat = bpy.context.active_object
tm = bpy.data.materials.new("throat")
tb = tm.node_tree.nodes.get("Principled BSDF")
tb.inputs["Base Color"].default_value = (0.002, 0.002, 0.002, 1)
tb.inputs["Roughness"].default_value = 1.0
throat.data.materials.append(tm)

# --- the jet: VDB space -> world (as probe A). Point source above the exit, AXIS -> -z ---
e3 = AXIS
e1 = (Vector((1, 0, 0)) - e3 * e3.x).normalized()
e2 = e3.cross(e1)
rot = Matrix((e1, -e2, -e3))
if rot.determinant() < 0:
    rot = Matrix((e1, e2, -e3))
s = args.vox / VOXEL  # metres per VDB unit across
LOCAL = rot.to_4x4() @ Matrix.Scale(s, 4) @ Matrix.Translation(-SRC)
src_frame = bpy.data.objects.new("source-frame", None)
src_frame.location = (0, 0, EXIT_D * AX_VOX)
src_frame.scale = (1, 1, args.stretch)
scene.collection.objects.link(src_frame)


def jet_material(weight):
    m = bpy.data.materials.new("jet")
    m.cycles.volume_interpolation = "CUBIC"
    nt = m.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new

    def put(sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            L(v, sock)
        else:
            sock.default_value = v

    def op(kind, a, b=None, clamp=False):
        x = N("ShaderNodeMath")
        x.operation = kind
        x.use_clamp = clamp
        put(x.inputs[0], a)
        if b is not None:
            put(x.inputs[1], b)
        return x.outputs[0]

    def vop(kind, a, b=None):
        x = N("ShaderNodeVectorMath")
        x.operation = kind
        put(x.inputs[0], a)
        if b is not None:
            put(x.inputs[1], b)
        return x.outputs["Value"] if kind in ("DOT_PRODUCT", "LENGTH") else x.outputs["Vector"]

    def ramp(v, a0, a1, b0, b1, smooth=False):
        x = N("ShaderNodeMapRange")
        x.interpolation_type = "SMOOTHSTEP" if smooth else "LINEAR"
        put(x.inputs["Value"], v)
        for name, val in (("From Min", a0), ("From Max", a1), ("To Min", b0), ("To Max", b1)):
            put(x.inputs[name], val)
        return x.outputs["Result"]

    def attr(name):
        x = N("ShaderNodeAttribute")
        x.attribute_name = name
        return x.outputs["Fac"]

    tc = N("ShaderNodeTexCoord")
    v = vop("SUBTRACT", tc.outputs["Object"], SRC)
    along = vop("DOT_PRODUCT", v, AXIS)  # VDB units
    sc = N("ShaderNodeVectorMath")
    sc.operation = "SCALE"
    sc.inputs[0].default_value = AXIS
    L(along, sc.inputs["Scale"])
    r_m = op("MULTIPLY", vop("LENGTH", vop("SUBTRACT", v, sc.outputs["Vector"])), s)  # metres from the axis
    d_m = op("MULTIPLY", op("SUBTRACT", op("DIVIDE", along, VOXEL), EXIT_D), AX_VOX)  # metres below the exit
    # nothing above the exit (the bell hides it, the source's wisps would stick out), nothing below the floor
    mask = op("MULTIPLY", ramp(d_m, -AX_VOX, 0.0, 0.0, 1.0), ramp(d_m, FLOOR, FLOOR + 0.02, 1.0, 0.0))

    c0, c1 = (float(x) for x in args.core_fade.split(","))
    r0, r1 = (float(x) for x in args.core_r.split(","))
    n = op("DIVIDE", attr("density"), RHO_MAX)
    rc = ramp(d_m, 0.0, c1, r0, r1)
    gauss_r = op("EXPONENT", op("MULTIPLY", op("POWER", op("DIVIDE", r_m, rc), 2.0), -1.0))
    core = op("MULTIPLY", ramp(n, args.core_lo, args.core_hi, 0.0, 1.0, smooth=True), gauss_r)
    core = op("MULTIPLY", core, ramp(d_m, c0, c1, 1.0, 0.0, smooth=True))
    if args.core_decay > 0:
        core = op("MULTIPLY", core, op("EXPONENT", op("MULTIPLY", d_m, -1.0 / args.core_decay)))
    cells = [float(x) for x in args.cells.split(",")]
    if cells[0] > 0:  # floor + (1 - floor) * ((1 + cos(2 pi (d - first) / period)) / 2)^2
        period, first, low = cells
        wave = op("COSINE", op("MULTIPLY", op("SUBTRACT", d_m, first), 2 * math.pi / period))
        wave = op("POWER", op("MULTIPLY", op("ADD", wave, 1.0), 0.5), 2.0)
        core = op("MULTIPLY", core, op("ADD", op("MULTIPLY", wave, 1.0 - low), low))
    core = op("MULTIPLY", op("MULTIPLY", core, mask), args.core_gain * weight)

    h = op("DIVIDE", attr("haze"), RHO_MAX)
    if args.haze_edge:
        lo, hi = (float(x) for x in args.haze_edge.split(","))
        h = ramp(h, lo, hi, 0.0, 1.0, smooth=True)
    elif args.haze_power != 1.0:
        h = op("POWER", op("MAXIMUM", h, 0.0), args.haze_power)
    if args.streaks:  # noise in VDB space stretched along the axis (VDB +y): fast-flow streaks
        amp, across_cm, along_cm = (float(x) for x in args.streaks.split(","))
        flow = N("ShaderNodeVectorMath")  # the clip moves the noise along the axis: Object - AXIS * offset
        flow.operation = "SUBTRACT"
        flow.name = "flow"
        L(tc.outputs["Object"], flow.inputs[0])
        flow.inputs[1].default_value = (0.0, 0.0, 0.0)
        sc3 = N("ShaderNodeVectorMath")
        sc3.operation = "MULTIPLY"
        L(flow.outputs["Vector"], sc3.inputs[0])
        k_across = s * 100 / across_cm  # features per VDB unit (s metres across, s * stretch along)
        k_along = s * args.stretch * 100 / along_cm
        sc3.inputs[1].default_value = (k_across, k_along, k_across)
        noise = N("ShaderNodeTexNoise")
        noise.name = "streaks"
        if args.shimmer > 0:
            noise.noise_dimensions = "4D"
        noise.inputs["Scale"].default_value = 1.0
        noise.inputs["Detail"].default_value = 3.0
        noise.inputs["Roughness"].default_value = 0.55
        L(sc3.outputs["Vector"], noise.inputs["Vector"])
        mod = op("ADD", op("MULTIPLY", op("SUBTRACT", noise.outputs["Fac"], 0.5), 4.0 * amp), 1.0)
        h = op("MULTIPLY", h, op("MAXIMUM", mod, 0.0))
    haze = op("MULTIPLY", h, ramp(d_m, 0.0, FLOOR, 1.0, args.haze_end))
    haze = op("MULTIPLY", op("MULTIPLY", haze, mask), args.haze_gain * weight)

    out = N("ShaderNodeOutputMaterial")
    add = N("ShaderNodeAddShader")
    for i, (dens, color, aniso) in enumerate(((core, (1, 1, 1, 1), args.aniso),
                                              (haze, linear(int(args.haze_color, 16)), args.haze_aniso))):
        vol = N("ShaderNodeVolumePrincipled")
        vol.inputs["Color"].default_value = color
        vol.inputs["Density Attribute"].default_value = ""  # density computed above
        vol.inputs["Anisotropy"].default_value = aniso
        L(dens, vol.inputs["Density"])
        L(vol.outputs["Volume"], add.inputs[i])
    L(add.outputs[0], out.inputs["Volume"])
    return m


JET_MAT = jet_material(1.0 / max(args.copies, 1))


def jet_objects(path):
    obs = []
    for k in range(max(args.copies, 1)):
        v = bpy.data.volumes.new(f"jet{k}")
        v.filepath = path
        v.render.precision = "FULL"
        v.materials.append(JET_MAT)
        ob = bpy.data.objects.new(f"jet{k}", v)
        ob.parent = src_frame
        ob.matrix_basis = LOCAL
        scene.collection.objects.link(ob)
        obs.append(ob)
    return obs


# --- camera: side view, orthographic; the bell near the top, the floor at the bottom edge ---
PY = round((TOP + FLOOR) * args.ppm)
view_h = PY / args.ppm
cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.sensor_fit = "VERTICAL"
cam_data.ortho_scale = view_h
cam = bpy.data.objects.new("cam", cam_data)
cam.location = (0, -20, TOP - view_h / 2)
cam.rotation_euler = (math.radians(90), 0, 0)
scene.collection.objects.link(cam)
scene.camera = cam


def aim(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat("-Z", "Y").to_euler()


def light(kind, name, loc, target, energy, color, **kw):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    for k, v in kw.items():
        setattr(ld, k, v)
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    scene.collection.objects.link(ob)
    aim(ob, target)
    return ob


world = bpy.data.worlds.new("world")
scene.world = world
wn = world.node_tree.nodes
bg = wn.get("Background")
mid = (0, 0, -FLOOR / 2)
if args.look == "a":
    # neutral studio (probe A), the key made bigger for the longer jet
    hdr = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "hdri", "studio_small_09_1k.hdr")
    env = wn.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(os.path.abspath(hdr))
    world.node_tree.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.8
    light("AREA", "key", (-1.6, -2.6, 2.6), mid, 1100 * args.key, (1.0, 0.98, 0.96), size=3.0)
else:
    # night stage: no ambient, a cool spot from above-side, a blue rim light from behind (the steam
    # scatters forward), a weak blue fill, and the red strip on the floor shining up
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1)
    bg.inputs["Strength"].default_value = 0.0
    light("SPOT", "stage", (-2.8, -0.8, 3.2), (0, 0, -0.9), 4200 * args.key, (0.6, 0.78, 1.0), spot_size=math.radians(55), spot_blend=0.6, shadow_soft_size=0.15)
    light("SPOT", "rim", (0.9, 3.0, 0.6), mid, 800 * args.rim, (0.55, 0.72, 1.0), spot_size=math.radians(65), spot_blend=0.5, shadow_soft_size=0.3)
    light("AREA", "fill", (1.5, -3.0, -1.0), mid, 90 * args.key, (0.6, 0.72, 1.0), size=2.0)
    # the red light of the stage floor (Tesla's frame: a red LED strip, the floor glowing red): a small
    # disk on the floor under the jet shining up, so it fades over the lower metre or two (E ~ 1/(R^2 + h^2))
    light("AREA", "floor", (0, 0, -FLOOR - 0.05), (0, 0, 0), 84 * args.red, (1.0, 0.04, 0.06), shape="DISK", size=1.6)

# --- Cycles on the GPU, transparent background (as probe A) ---
scene.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
try:
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "METAL"
    scene.cycles.device = "GPU"
    print("jet_probe_a2: Cycles on", [d.name for d in prefs.devices if d.use])
except Exception as e:  # CPU works too, slower
    print("GPU setup failed, CPU:", e)
c = scene.cycles
c.samples = args.samples
c.use_adaptive_sampling = True
c.adaptive_threshold = 0.02
c.use_denoising = True
try:
    c.denoiser = "OPENIMAGEDENOISE"
    c.denoising_use_gpu = True
except Exception as e:
    print("denoiser:", e)
c.max_bounces = max(12, args.bounces + 4)
c.volume_bounces = args.bounces
c.transparent_max_bounces = 8
c.volume_biased = not args.unbiased
c.volume_step_rate = args.step_rate
scene.render.use_persistent_data = args.clip  # keep the scene on the GPU between the clip's frames
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = args.px, PY
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
for vt in ("AgX", "Standard"):
    try:
        scene.view_settings.view_transform = vt
        break
    except TypeError:
        pass
print(f"jet_probe_a2: {args.tag} look {args.look}, {args.px}x{PY} at {args.ppm} px/m, vox {args.vox * 100:.2f} cm x{args.stretch} along, "
      f"smear {args.smear} (+axial {args.axial}), haze sigma {HS}, core {args.core_gain} {args.core_lo}-{args.core_hi} r {args.core_r} "
      f"fade {args.core_fade}, haze {args.haze_gain} end {args.haze_end}, copies {args.copies}, samples {args.samples}")


def clip():
    """Switch on (VDB from 0), steady (the two runs blended), switch off (VDB up to --off-end)."""
    step = args.vdb_fps // args.fps
    b0, b1 = (int(v) for v in args.blend.split(","))
    folder = os.path.join(OUT, f"{args.tag}-{args.look}-clip")
    os.makedirs(folder, exist_ok=True)
    todo = range(args.length)
    if args.frames:
        a, b = (int(v) for v in args.frames.split("-"))
        todo = range(a, b + 1)
    blank = None
    noise = JET_MAT.node_tree.nodes.get("streaks")
    flow = JET_MAT.node_tree.nodes.get("flow")
    per_m = VOXEL / AX_VOX  # VDB units per metre along the axis
    t_all = time.time()
    for i in todo:
        out = os.path.join(folder, f"{i:04d}.png")
        if i < args.on_at:  # nothing yet: one render of the bare nozzle, copied
            if blank is None:
                scene.render.filepath = os.path.join(folder, "blank.png")
                bpy.ops.render.render(write_still=True)
                blank = scene.render.filepath
            with open(blank, "rb") as fi, open(out, "wb") as fo:
                fo.write(fi.read())
            continue
        t = i / args.fps
        va = (i - args.on_at) * step
        vb = args.off_end - (args.length - 1 - i) * step
        x = min(max((i - b0) / max(b1 - b0, 1), 0.0), 1.0)
        w = x * x * (3 - 2 * x)
        t0 = time.time()
        path = prepared(va) if w <= 0 else prepared(vb) if w >= 1 else prepared(va, vb, round(w, 3))
        if flow is not None:
            flow.inputs[1].default_value = tuple(AXIS * (args.flow * t * per_m))
        if noise is not None and args.shimmer > 0:
            noise.inputs["W"].default_value = args.shimmer * t
        obs = jet_objects(path)
        scene.render.filepath = out
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"jet_probe_a2: clip {i:04d} t={t:.3f} s VDB {va}/{vb} w={w:.2f} prepared {t1 - t0:.1f} s, rendered in {time.time() - t1:.1f} s")
        for ob in obs:
            v = ob.data
            bpy.data.objects.remove(ob)
            bpy.data.volumes.remove(v)
    print(f"jet_probe_a2: clip {len(todo)} frames in {time.time() - t_all:.0f} s -> {folder}")


if args.clip and not args.build_only:
    clip()
for item in ([] if args.clip or args.build_only else args.moments.split(",")):
    name, frame = item.split("=")
    t0 = time.time()
    path = prepared(int(frame))
    obs = jet_objects(path)
    scene.render.filepath = os.path.join(OUT, f"{args.tag}-{args.look}-{name}.png")
    t1 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"jet_probe_a2: {args.tag}-{args.look}-{name} (VDB {frame}) prepared {t1 - t0:.1f} s, rendered in {time.time() - t1:.1f} s -> {scene.render.filepath}")
    for ob in obs:
        v = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.volumes.remove(v)
