"""Landing, checkpoint 2: the four lift jets on the car and the cloud they push out along the floor, over
the whole landing of out/landing/motion.json.

The scene is three approved pieces put together, none of them changed in look:
  - the car: tools/blender/car_shot.py --build-only (runpy): the car keyed from motion.json, the camera
    (orthographic, the floor at the bottom edge, --ppm px per metre), light look a, render settings;
  - the jets: the V2 jet of tools/blender/jet_probe_a2.py (--preset v2 --look a --flow 0.75 --shimmer 6,
    the settings of the approved draft clip A3) — its VDB preparation and its material, run first with
    --build-only for its functions (car_shot.py then clears the scene and builds its own). One jet per
    lift nozzle (the 'down' group of src/models.js), the exit at the nozzle, no bell: it comes straight
    out from under the body and turns with the car. Four changes that are not look:
      * the floor: the gas is cut at the real floor (world z = 0, the same 2 cm band as A2), so a jet from
        a nozzle lower than 3 m stops at the floor; the jet's own end (A2 cut it at 3.0-3.02 m below the
        exit, where its floor was) fades out over 3.0-3.5 m instead, so from higher than 3 m it ends in
        the air (the prepared VDB holds gas to ~3.7 m);
      * the strength: both components (core and haze) times thrust / hover thrust of that nozzle
        (motion.json, linear: the gas a choked nozzle lets out goes with its thrust); a change of thrust
        travels down the jet in --jet-delay s (0.15: the asset's front reaches 3 m in ~0.15 s, probe A3),
        so the weight goes from 'now' at the exit to 'then' at 3 m;
      * the streaks differ per jet (an offset of the streaky noise), so four jets are not one copied;
      * the timing is the asset's (as A3): switched on at VDB 0 (it reaches 3 m at ~18), the on-run blended
        into the off-run over VDB 40-80 (A3: output frames 25-45 at 30 fps), the valve closing at VDB 383
        on the frame the valves close in the physics (touchdown), the tail gone at 414. motion.json is
        60 frames/s like the asset: one VDB frame per frame. The lift jets burn from the first frame
        of the landing (motion.json 'on_at_start'): here they switch on at frame 0.
  - the cloud: the cloud of probe B (tools/blender/cloud_probe_b.py) at the approved middle height —
    the low variant (Chaotic x0.055, Rolling x0.12, after a second R 2.7 m, H 1.3 m) and the taller one
    (x0.1, x0.2, R 3.5, H 2.5) averaged: Chaotic x0.0775 m per VDB unit, Rolling x0.16, R 3.1, H 1.9 —
    with its material law (120 rho^2 per VDB unit, albedo 0.985) and envelopes (front R, height cap H,
    hole, erode). Per lift jet one source where its axis meets the floor: a Chaotic copy centred on
    it (each turned by a quarter more, each at another frame of the loop) and a Rolling copy rolling
    outwards along the floor — forward from the front jets, backward from the rear ones; between the
    front and rear jets the flows meet and the four sources merge into one cloud. No gas inside the car
    (CAR_BOXES: the body, the nose and the cabin in the chassis frame): the volumes pass through the body,
    and through the glass the cabin showed full of fog.
Pushed out, not appearing: the young cloud is a small dense copy of the grown one and grows about its
source — the copies scale by size(tau), so every billow moves outwards, the loops play one VDB frame per
frame (60/s, the Chaotic loop then runs at the speed of its gas at this scale: Froude, time ~ sqrt(size))
and the Rolling copies roll away from the jets; its density is never faded in. tau is the time the jets
have been hitting the floor, counted with their thrust at the floor (a weak jet feeds less); the laws go
through probe B's moments: born (tau 0.1 s: size 0.45, R 0.9 m, H 0.7 m) and steady (tau 1.1 s: size 1,
R 3.1, H 1.9), size ~ tau^(1/3) (volume ~ the gas let out), R ~ tau^0.52, H ~ tau^0.42; later the cloud
spreads more than it grows (size +0.08/s, R +0.5 m/s, H +0.1 m/s: cold heavy gas). When the jets stop
reaching the floor it melts towards probe B's 'off' moment 1 s later (R x1.33, H x0.54, density x0.05,
erode 0.01, the middle cleared within 0.9 m of each source, the rolling outer cloud x4), every value
moving linearly with e = (1 - exp(-t / 0.35 s)) / (1 - exp(-1 / 0.35)): half the way in 0.24 s.
The four volumes at a jet's foot are loaded one by one (see loaded()): Blender 5.2 deadlocked once loading
several VDB files in one depsgraph update.
Show B (01.11): a cloud per stretch of frames the lift jets reach the floor (the take-off, the landing; --cloud-gap), each
with its own tau and melting, gone once melted. Its car moves on the diagonal, so a cloud lies where it was blown and does
not follow the car: per jet its copies sit at the mean of the jet's feet so far (weighted by the gas let out), its
envelope reaches along the path of the feet (r: the distance to that segment); once the jets leave the floor it stays.
The rear jets of the dash and the side jets of the flip make no cloud.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/landing_jets.py -- \
        out/landing/stills-jets [--frames born=24,steady=86,melting=200 --samples 48 --step-rate 3 --px 2160]
      14-22 min a frame on an M1 Pro (2160x936, 48 samples, step rate 3, 8 volume bounces; the car alone: ~3 s).
      Draft clip (Cycles, every second frame, ~35 s a frame at 108 px/m):
        ... -- out/landing/preview-jets --clip --range 0:210:2 --ppm 108 --px 1080 --samples 8 --step-rate 8 --stamp
      Eevee (~2 s a frame, but the cloud grey and soft: no multiple scattering): --engine eevee --samples 16
      Car silhouettes for the desktop shadow (white, Eevee, no jets or cloud), the same frames:
        ... -- out/landing/stills-jets --mask    (or --clip --mask ...)
      --no-jets / --no-cloud / --no-car for checks and measurements (the cloud alone for tools/jet_measure.py cloud);
      --list prints the timeline in numbers and renders nothing.
      Layers (31.10, tools/landing_final.sh runs them all): --layer car-lit --exr --samples 16 --step-rate 16 (the car,
      full size, lit by the gas, ~35 s a frame on average) and --layer smoke --scale 50 --exr --samples 8 (the gas at
      108 px/m, the car a holdout, ~70 s), merged by tools/landing_merge.py; --layer car: the car alone (~3 s).
Out:  OUT/<frame>-<name>.png, RGBA, transparent, the floor at the bottom edge (--mask: <frame>-<name>-mask.png);
      --clip: OUT/clip/<frame>.png (--mask: OUT/clip-mask/<frame>.png). tools/landing_jets_sheet.py puts them over
      the wallpaper with and without the desktop shadow.
"""
import argparse
import json
import math
import os
import runpy
import subprocess
import sys
import time

import bpy
import numpy as np
import openvdb as vdb
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
# the downloaded assets and the caches, outside git: $ROADSTER_WORK, or work/ in this repository (README)
WORK = os.environ.get("ROADSTER_WORK") or os.path.join(ROOT, "work")
ap = argparse.ArgumentParser(prog="landing_jets.py")
ap.add_argument("out")
ap.add_argument("--motion", default=os.path.join(ROOT, "out", "landing", "motion.json"))
ap.add_argument("--frames", default="born=24,steady=86,melting=200", help="name=frame or marks of motion.json, comma-separated")
ap.add_argument("--clip", action="store_true", help="render every frame (or --range) to OUT/clip/")
ap.add_argument("--range", default="", help="first:last[:step] frames for --clip")
ap.add_argument("--mask", action="store_true", help="the car's silhouette only: white, opaque, Eevee (the desktop shadow)")
ap.add_argument("--layer", default="full", choices=["full", "car", "smoke", "car-lit"],
                help="full: everything in one render (checkpoint 2); car: the car alone; smoke: the jets and the cloud, the car "
                     "a holdout (unseen, but hiding the gas behind it and shadowing it); car-lit: the car with the jets and the "
                     "cloud lighting it, mirrored in it and seen through its glass, but unseen by the camera rays themselves. "
                     "--clip writes a layer to OUT/<layer>/ (tools/landing_merge.py puts smoke over car or car-lit)")
ap.add_argument("--scale", type=int, default=100, help="resolution %% of --px with the same camera (the smoke layer: 50 = 108 px/m)")
ap.add_argument("--exr", action="store_true", help="linear premultiplied half-float EXR instead of PNG (layers to merge)")
ap.add_argument("--seed", type=int, default=0, help="Cycles noise seed")
ap.add_argument("--wait-ac", action="store_true", help="--clip: before each frame wait while the Mac is on battery (pmset)")
ap.add_argument("--list", action="store_true", help="print the timeline (jets, cloud) and render nothing")
ap.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])
ap.add_argument("--samples", type=int, default=48)
ap.add_argument("--step-rate", type=float, default=3.0, help="Cycles volume step rate (NOTES rule 8: 3 for probes)")
ap.add_argument("--bounces", type=int, default=8, help="volume bounces (the jet and cloud probes: 8)")
ap.add_argument("--unbiased", action="store_true", help="Cycles unbiased volumes (null scattering) instead of ray marching")
ap.add_argument("--ppm", type=float, default=216.0)
ap.add_argument("--px", type=int, default=2160, help="frame width, px (10 m at 216 px/m; car_shot.py alone: 1600)")
ap.add_argument("--py", type=int, default=0, help="frame height, px, exactly (show B: 1964 at 216 px/m; 0: car_shot.py's own)")
ap.add_argument("--cx", type=float, default=None, help="the frame's middle, m (car_shot.py: the car's middle at frame 0; show B: 7)")
ap.add_argument("--gas", default="rigid", choices=["rigid", "straight"],
                help="a jet on a turning car: rigid (fixed to its nozzle: all of it turns with the car, as so far) or straight "
                "(the proposal of 01.11: gas that has left flies on as it left — on frames where the jet's gas left over more "
                "than 3 deg of turn, it goes in --gas-pieces pieces along its length, each turned as the nozzle was when its "
                "gas left and moved with the car since)")
ap.add_argument("--gas-pieces", type=int, default=6, help="--gas straight: at most this many pieces a jet")
ap.add_argument("--gas-turn", type=float, default=20.0, help="--gas straight: one piece per this many degrees of spread")
ap.add_argument("--groups", default="down", help="nozzle groups with jets: down (lift, the landing), side (roll), back (dash)")
ap.add_argument("--stamp", action="store_true")
ap.add_argument("--blur", type=float, default=0.5, help="car_shot.py's motion blur shutter, frames (0: off)")
ap.add_argument("--glass-key", action="store_true", help="car_shot.py: the key light reflects in the tinted glass")
ap.add_argument("--no-jets", action="store_true")
ap.add_argument("--no-cloud", action="store_true")
ap.add_argument("--no-car", action="store_true", help="hide the car (cloud-only renders for tools/jet_measure.py cloud)")
ap.add_argument("--jet-cache", default=os.path.join(WORK, "jet-probe-a3", "vdb"), help="prepared jet VDBs (shared with A3)")
ap.add_argument("--jet-delay", type=float, default=0.15, help="s for a change of thrust to reach 3 m down the jet")
ap.add_argument("--blend", default="40,80", help="VDB frames of the on-run over which it blends into the off-run (A3)")
# the cloud: probe B at the middle height
ap.add_argument("--chaotic", default=os.path.join(WORK, "blendkit/chaotic-ground-smoke/extracted/caches/(L) Ground Smoke/Ground Smoke_{:03d}.vdb"))
ap.add_argument("--rolling", default=os.path.join(WORK, "blendkit/rolling-ground-smoke/extracted/caches/(L) Rolling Ground Smoke/Rolling Ground Smoke_{:03d}.vdb"))
ap.add_argument("--chaotic-scale", type=float, default=0.0775, help="m per VDB unit at size 1 (probe B: low 0.055, taller 0.1)")
ap.add_argument("--rolling-scale", type=float, default=0.16, help="m per VDB unit at size 1 (probe B: low 0.12, taller 0.2)")
ap.add_argument("--R", type=float, default=3.1, help="the front 1.1 s after the jets hit the floor, m (probe B: 2.7 / 3.5)")
ap.add_argument("--H", type=float, default=1.0, help="the height cap then, m (approved 27.10: 1.0; was 1.9; probe B: 1.3 / 2.5)")
ap.add_argument("--rolling-start", type=float, default=0.35)
ap.add_argument("--rolling-cut", default="-23.4,-21.0")
ap.add_argument("--chaotic-gain", type=float, default=0.5, help="density (approved 27.10: 0.5; was 1.0)")
ap.add_argument("--rolling-gain", type=float, default=0.5, help="density (approved 27.10: 0.5; was 1.0)")
ap.add_argument("--albedo", type=float, default=0.985)
ap.add_argument("--aniso", type=float, default=0.3)
ap.add_argument("--soft", type=float, default=0.3)
ap.add_argument("--jitter", type=float, default=0.3)
ap.add_argument("--hole-floor", type=float, default=0.2)
ap.add_argument("--melt", type=float, default=0.15, help="melting time constant, s (approved 27.10: 0.15; was 0.35 = probe B's 'off' 1 s after)")
ap.add_argument("--melt-time", type=float, default=3.0, help="s: smooth melting (approved 01.11: 3.0): the density fades to nothing, "
                "the front spreads, starting and ending gently, over this time (0: the 27.10 melting above, done in 1 s, a thin fog left)")
ap.add_argument("--settle-time", type=float, default=1.5, help="s, with --melt-time: the top settles to its low height (approved 01.11: 1.5; 0: = --melt-time)")
ap.add_argument("--cloud-gap", type=float, default=0.5, help="s: the lift jets leaving the floor for less than this "
                "feed the same cloud (show B: a cloud at the take-off, another at the landing)")
ap.add_argument("--hole-time", type=float, default=1.2, help="s, with --melt-time: the middle around the car clears (approved 01.11: 1.2; 0: = --melt-time)")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
OUT = os.path.abspath(args.out)
if args.mask:
    args.engine, args.no_jets, args.no_cloud = "eevee", True, True
if args.layer == "car":
    args.no_jets, args.no_cloud = True, True
if args.layer != "full" and (args.mask or args.no_car or args.engine != "cycles"):
    raise SystemExit("landing_jets: --layer is a Cycles layer of the whole scene (not with --mask, --no-car or Eevee)")

# --- 1. the approved jet: its functions (VDB preparation, material); its scene is replaced below ---
sys.argv = [sys.argv[0], "--", OUT, "--preset", "v2", "--look", "a", "--cache", args.jet_cache, "--flow", "0.75",
            "--shimmer", "6", "--build-only"]
J = runpy.run_path(os.path.join(HERE, "jet_probe_a2.py"), run_name="jet_probe_a2")
JA = J["args"]
JET_FLOOR = J["FLOOR"]  # 3.0: the jet was made and approved reaching a floor 3 m below the exit
AXIS, SRC, VOXEL, EXIT_D, AX_VOX = J["AXIS"], J["SRC"], J["VOXEL"], J["EXIT_D"], J["AX_VOX"]
VDB_ON, VDB_FLOOR, VDB_CLOSE, VDB_GONE = 2, 18, 383, 414  # the asset: on, at 3 m, valve closes, tail past 3 m

# --- 2. the car, camera, light and render settings (car_shot.py clears the scene first) ---
sys.argv = [sys.argv[0], "--", OUT, "--motion", args.motion, "--ppm", str(args.ppm), "--px", str(args.px),
            "--engine", args.engine, "--samples", str(args.samples), "--build-only", "--blur", str(args.blur)] + (["--stamp"] if args.stamp else []) \
    + (["--glass-key"] if args.glass_key else []) \
    + (["--py", str(args.py)] if args.py else []) + (["--cx", str(args.cx)] if args.cx is not None else [])
C = runpy.run_path(os.path.join(HERE, "car_shot.py"), run_name="car_shot")
scene, car, M, FR = C["scene"], C["car"], C["M"], C["FR"]
NF = len(FR)
if args.no_car:
    for ob in C["imported"]:
        ob.hide_render = True
FPS = M["fps"]
DOWN = [i for i, n in enumerate(M["nozzles"]) if n["group"] == "down"]
GROUPS = args.groups.split(",")
JETN = [i for i, n in enumerate(M["nozzles"]) if n["group"] in GROUPS]  # the nozzles that get a jet
c = scene.cycles
c.volume_bounces = args.bounces
c.max_bounces = max(c.max_bounces, args.bounces + 4)
c.volume_biased = not args.unbiased  # ray-marched (step rate) unless --unbiased (null scattering)
c.volume_step_rate = args.step_rate
c.seed = args.seed
if args.gas == "straight":  # every piece's bounds are two transparent crossings for a ray: room for a dozen pieces
    c.transparent_max_bounces = max(c.transparent_max_bounces, 32)
scene.render.resolution_percentage = args.scale  # the same camera: 50 = every pixel of the full frame's 2 x 2
if args.layer == "smoke":
    # a holdout, not hidden: camera rays that reach the car end there with alpha 0 (the gas in front of it stays,
    # the gas behind it is hidden), every other ray sees the car as in the full render (its shadow on the cloud,
    # its paint lighting the gas)
    for ob in C["imported"]:
        ob.is_holdout = True
if args.exr:
    s = scene.render.image_settings
    s.file_format = "OPEN_EXR"
    s.color_depth = "16"
    s.exr_codec = "ZIP"
    s.color_mode = "RGBA"
EXT = ".exr" if args.exr else ".png"
if args.engine == "eevee":
    e = scene.eevee
    e.use_volumetric_shadows = True
    e.volumetric_tile_size = "2"
    e.volumetric_samples = 128
    e.volumetric_shadow_samples = 16
    e.use_volume_custom_range = True  # the camera is 30 m away: froxels only over the scene's depth
    e.volumetric_start, e.volumetric_end = 25.0, 36.0
    e.volumetric_light_clamp = 0.0


# --- the timeline in numbers ---
def nozzle_world(i, f):
    """World position and direction of nozzle i at frame f (the chassis frame of motion.json)."""
    fr = FR[f]
    rq = Quaternion(fr["quat"])
    p = Vector(fr["pos"]) + rq @ Vector(M["nozzles"][i]["pos"])
    d = rq @ Vector(M["nozzles"][i]["dir"])
    return p, d


def height(i, f):
    p, d = nozzle_world(i, f)
    return p.z / max(-d.z, 1e-3) if d.z < -0.3 else 99.0


ON = 0.012
on0 = set(M.get("on_at_start", []))
names = [n["name"] for n in M["nozzles"]]
touch = next((e["frame"] for e in M["events"] if e["type"] == "touchdown"), None)
TAIL = VDB_GONE - VDB_CLOSE  # 31 frames: after the valve closes the asset's last gas falls 3 m


def burns_of(i):
    """[(ignite, close)] of nozzle i: its VDB 0 frame and the frame its valve closes (None: burning at the end). The
    valve closes on the frame the thrust starts to fall to zero: the first frame from the touchdown (if it falls in
    the burn) or 3 frames before the cutoff on whose thrust is below 95% of the frame before (the physics closes them
    in 25 ms on the first wheel contact; a pulse of the flip ends within a frame)."""
    out, g = [], (0 if names[i] in on0 else None)
    for e in sorted((e for e in M["events"] if e.get("nozzle") == names[i]), key=lambda e: e["frame"]):
        if e["type"] == "ignite":
            g = e["frame"]
        elif e["type"] == "cutoff" and g is not None:
            cut = e["frame"]
            f0 = touch if touch is not None and g < touch <= cut else cut - 3
            out.append((g, next((f for f in range(max(f0, g + 1, 1), cut + 1) if FR[f]["thrust"][i] < 0.95 * FR[f - 1]["thrust"][i]), cut)))
            g = None
    if g is not None:
        out.append((g, None))
    return out


BURNS = {i: burns_of(i) for i in sorted(set(DOWN) | set(JETN))}
ignite = {i: (BURNS[i][0][0] if BURNS[i] else None) for i in DOWN}  # the landing's one burn, for the printout
close = {i: (BURNS[i][-1][1] if BURNS[i] else None) for i in DOWN}
hover_thrust = {i: float(np.median([FR[f]["thrust"][i] for f in range(NF) if FR[f]["phase"] == "hover"] or [0.1035])) for i in DOWN}
# the side and rear jets: thrust in newtons over a lift jet's at the hover (their maxima differ: 70 and 45 kN)
HOVER_N = float(np.mean([hover_thrust[i] * M["nozzles"][i]["max"] for i in DOWN]))
B0, B1 = (int(v) for v in args.blend.split(","))


def burn_spec(burn, f):
    """(frame, frame_b, w, tail) of the prepared VDB of one burn at frame f, or None (no gas): tail is how far below
    the exit the gas starts, m (0: at the exit). A long burn (from B1 + 20 frames, the landing) goes as A3: the on-run
    blended into the asset's own off-run, the valve closing at VDB 383 on the closing frame. A shorter one (show B:
    the take-off, the flip's pulses) keeps playing its on-run after the valve closes and the gas leaves the exit from
    the top, its upper end falling as the asset's last gas does (3 m in 31 frames)."""
    g, c = burn
    if f < g:
        return None
    a = f - g  # the on-run: VDB 0 at the ignition
    if c is None:
        if a > VDB_CLOSE - 5:
            raise SystemExit("landing_jets: a burn longer than the asset's run without a cutoff is not handled")
        return (a, None, 0.0, 0.0)
    if c - g >= B1 + 20:
        b = VDB_CLOSE + (f - c)  # the off-run: the valve closes at VDB 383 on the closing frame
        if b > VDB_GONE:
            return None
        if a < B0:
            return (a, None, 0.0, 0.0)
        if a >= B1:
            return (b, None, 0.0, 0.0)
        x = (a - B0) / (B1 - B0)
        return (a, b, round(x * x * (3 - 2 * x), 3), 0.0)
    tail = max(f - c, 0) * JET_FLOOR / TAIL
    return None if tail > JET_FLOOR + 0.5 else (a, None, 0.0, round(tail, 4))


def burn_at(i, f):
    """The burn of nozzle i ignited last by frame f, or None."""
    return next((b for b in reversed(BURNS[i]) if b[0] <= f), None)


def gas(i, f):
    """[(burn index, spec)] of nozzle i at frame f: the gas of every burn still out (a new burn's head may meet the
    last one's tail)."""
    out = []
    for k, b in enumerate(BURNS[i]):
        spec = burn_spec(b, f)
        if spec is not None:
            out.append((k, spec))
    return out


def jet_vdb(i, f):
    """(frame, frame_b, w) of the newest gas of jet i at frame f, or None (the landing's printout)."""
    sp = gas(i, f)
    return sp[-1][1][:3] if sp else None


def weight(i, f, burn=None):
    """Jet i's strength at frame f: thrust / hover thrust (the side and rear jets: in newtons over a lift jet's at the
    hover), held from the ignition through the closing (the asset closes it), at most 2."""
    g, c = burn or burn_at(i, f) or (0, None)
    if c is not None and f >= c:
        f = c - 1
    f = min(max(f, g, 0), NF - 1)
    if i in hover_thrust:
        return min(FR[f]["thrust"][i] / hover_thrust[i], 2.0)
    return min(FR[f]["thrust"][i] * M["nozzles"][i]["max"] / HOVER_N, 2.0)


DELAY = round(args.jet_delay * FPS)


def front(i, f):
    """How far below the exit the jet's gas reaches at frame f, m (the asset: 3 m from VDB 2 to 18)."""
    b = burn_at(i, f)
    spec = burn_spec(b, f) if b else None
    if spec is None:
        return 0.0
    v = spec[0] if spec[1] is None else max(spec[0], spec[1])
    if b[1] is not None and f >= b[1]:
        return 9.0  # the tail: handled by 'feeding'
    return JET_FLOOR * (v - VDB_ON) / (VDB_FLOOR - VDB_ON)


def feeding(i, f):
    """The jet's gas reaching the floor at frame f: 0..2 (its thrust at the floor, 0 if it ends in the air)."""
    b = burn_at(i, f)
    if b is None:
        return 0.0
    h = height(i, f)
    if b[1] is not None and f >= b[1]:  # the last gas leaves the nozzle: the tail falls ~3 m in 31 frames
        if (f - b[1]) * JET_FLOOR / (VDB_GONE - VDB_CLOSE) > h:
            return 0.0
    elif front(i, f) < h:
        return 0.0
    reach = 1.0 - min(max((h - JET_FLOOR) / 0.5, 0.0), 1.0)
    return weight(i, f - DELAY) * reach


# the clouds: one per stretch of frames the lift jets reach the floor (a break under --cloud-gap s is the same stretch):
# the landing has one, show B two — the take-off's (it melts while the car is in the air) and the landing's. Each has
# its own tau (seconds of feeding at hover thrust, from its first frame) and its own melting after its last fed frame
feed = [sum(feeding(i, f) for i in DOWN) / len(DOWN) for f in range(NF)]
CLOUDS = []
for f in range(NF):
    if feed[f] > 0:
        if CLOUDS and f - CLOUDS[-1]["last"] <= round(args.cloud_gap * FPS):
            CLOUDS[-1]["last"] = f
        else:
            CLOUDS.append(dict(first=f, last=f))
for cl in CLOUDS:
    cl["tau"] = list(np.cumsum([feed[f] if cl["first"] <= f <= cl["last"] else 0.0 for f in range(NF)]) / FPS)
    # the first frame nothing is left (the smooth melting ends at density 0; the 27.10 one leaves a thin fog for good)
    cl["gone"] = cl["last"] + math.ceil(args.melt_time * FPS - 1e-6) if args.melt_time > 0 else None
first_feed = CLOUDS[0]["first"] if CLOUDS else None
last = CLOUDS[-1]["last"] if CLOUDS else None


def foot_of(i, f):
    """Where the axis of lift jet i meets the floor at frame f."""
    p, d = nozzle_world(i, f)
    foot = p + d * (p.z / max(-d.z, 1e-3))
    foot.z = 0.0
    return foot


# a cloud lies on the floor where it was blown, along the path of the jets' feet (show B's car moves on the diagonal):
# per lift jet the feet of its fed frames and the gas it let out there
for cl in CLOUDS:
    cl["feet"] = {i: [(f, w, foot_of(i, f)) for f in range(cl["first"], cl["last"] + 1) for w in [feeding(i, f)] if w > 0]
                  for i in DOWN}


def lay(k, i, f):
    """(anchor, start, end) of cloud k at lift jet i at frame f: the anchor of its copies is the mean of the jet's feet
    so far weighted by the gas let out there (the gas already out stays where it landed); its envelope reaches along
    the path of the feet from the first to the latest (a point when the car only goes up and down)."""
    fs = [(w, p) for g, w, p in CLOUDS[k]["feet"][i] if g <= f]
    if not fs:
        p = foot_of(i, CLOUDS[k]["first"])
        return p, p, p
    sw = sum(w for w, _ in fs)
    return sum((p * w for w, p in fs), Vector()) / sw, fs[0][1], fs[-1][1]


def grow(t):
    t = max(t, 1e-4)
    if t <= 1.1:
        return (t / 1.1) ** (1 / 3), args.R * (t / 1.1) ** 0.52, args.H * (t / 1.1) ** 0.42
    return 1.0 + 0.08 * (t - 1.1), args.R + 0.5 * (t - 1.1), args.H + 0.1 * (t - 1.1)


def cloud_state(f, k=0):
    """size, R, H, gain, erode, hole, rgain of cloud k at frame f (see the docstring), None before it or once gone."""
    if k >= len(CLOUDS) or f < CLOUDS[k]["first"] or (CLOUDS[k]["gone"] is not None and f >= CLOUDS[k]["gone"]):
        return None
    cl = CLOUDS[k]
    off = (f - cl["last"]) / FPS if f > cl["last"] else 0.0
    size, R, H = grow(cl["tau"][f])
    st = dict(size=size, R=R, H=H, gain=1.0, erode=0.0, hole=0.0, rgain=1.0)
    if off > 0:
        if args.melt_time > 0:  # 01.11: smooth melting, every part on its own smoothstep, all gone at the end
            def ease(T):
                u = min(off / T, 1.0)
                return u * u * (3 - 2 * u)
            e, es, eh = ease(args.melt_time), ease(args.settle_time or args.melt_time), ease(args.hole_time or args.melt_time)
            st.update(R=R * (1 + 0.33 * e), H=H * (1 - 0.46 * es), gain=1 - e, erode=0.01 * e,
                      hole=0.9 * eh, rgain=1 + 3 * e)
        else:
            e = min((1 - math.exp(-off / args.melt)) / (1 - math.exp(-1 / args.melt)), 1.0)
            st.update(R=R * (1 + 0.33 * e), H=H * (1 - 0.46 * e), gain=1 - 0.95 * e, erode=0.01 * e,
                      hole=0.9 * e, rgain=1 + 3 * e)
    return st


def clouds_at(f):
    """{k: state} of the clouds there at frame f."""
    return {k: st for k in range(len(CLOUDS)) for st in [cloud_state(f, k)] if st is not None}


print(f"landing_jets: lift nozzles {[names[i] for i in DOWN]}, ignite {ignite}, valves close {close}, touchdown {touch}, "
      f"hover thrust {[round(hover_thrust[i], 4) for i in DOWN]}, jets hit the floor from frame {first_feed}, last fed {last}, "
      f"clouds {[(cl['first'], cl['last'], cl['gone']) for cl in CLOUDS]} (first fed, last fed, gone)")
SHOW = "cut" in M["marks"]  # a whole show (B: drive in ... dash off), not the landing alone
V_GAS = JET_FLOOR / max(DELAY, 1)  # m per frame down the jet: a change of thrust reaches 3 m in --jet-delay
FAR = JET_FLOOR + 0.5  # the jet's end fades out by 3.5 m


def emitted(i, f, kb, spec):
    """The frames the gas of burn kb of jet i out at frame f left the nozzle (its upper end to its lower end)."""
    g, c = BURNS[i][kb]
    if c is not None and f >= c:  # after the valve closed: the gas below the tail, the newest right under it
        return range(max(g, c - 1 - math.floor(max(FAR - spec[3], 0.0) / V_GAS)), c)
    return range(max(g, math.ceil(f - FAR / V_GAS)), f + 1)


def bend(i, f):
    """The most the gas out of jet i at frame f left the nozzle turned from its axis now, degrees: a jet fixed to
    the car turns all of it with the car, gas that has left flies on as it left (V_GAS m per frame)."""
    d = nozzle_world(i, f)[1]
    return max([math.degrees(d.angle(nozzle_world(i, e)[1], 0.0)) for kb, spec in gas(i, f) for e in emitted(i, f, kb, spec)] + [0.0])


def summary():
    """Show B: the burns, the cloud's melting against the cut, the car against the frame's top, the rotating jets."""
    for i in JETN:
        print(f"  jet {names[i]}: burns " + ", ".join(f"{g}-{c} ({'-' if c is None else c - g} fr)" for g, c in BURNS[i]))
    mk = M["marks"]
    cut, launch = mk.get("cut"), mk.get("launch")
    print(f"  the lift jets reach the floor in {len(CLOUDS)} stretch(es), a cloud each (--melt-time {args.melt_time}, "
          f"--cloud-gap {args.cloud_gap}){'' if not args.no_cloud else ' (not rendered: --no-cloud)'}:")
    for k, cl in enumerate(CLOUDS):
        a, b = cl["first"], cl["last"]
        size, R, H = grow(cl["tau"][b])
        path = max((lay(k, i, b)[2] - lay(k, i, b)[1]).length for i in DOWN)
        moved = max((lay(k, i, b)[0] - lay(k, i, a)[0]).length for i in DOWN)
        car_dx = Vector(FR[b]["pos"]) - Vector(FR[a]["pos"])
        print(f"    cloud {k + 1}: fed {a}-{b} ({(b - a + 1) / FPS:.2f} s; the jet {names[DOWN[0]]} {height(DOWN[0], a):.2f} -> "
              f"{height(DOWN[0], b):.2f} m above the floor; the car moved {car_dx.x:+.2f} m in x, {car_dx.z:+.2f} m in z), tau "
              f"{cl['tau'][b]:.2f} s: size {size:.2f}, R {R:.2f} m, H {H:.2f} m; the feet's path at most {path:.2f} m, the "
              f"copies' anchor moved at most {moved:.2f} m (then stays); melts {b + 1}-{cl['gone']} "
              f"({'gone at ' + str(cl['gone']) if cl['gone'] is not None else 'a thin fog stays'})")
    melt_end = CLOUDS[-1]["gone"] if CLOUDS else None
    there = [k + 1 for k in range(len(CLOUDS)) if cloud_state(cut, k) is not None]
    print(f"  still {mk.get('still')}, cut {cut}, launch {launch}: the last cloud gone at {melt_end}, margin "
          + (f"{(cut - melt_end) / FPS:.2f} s" if melt_end is not None else "-")
          + (f"  <-- CLOUD {there} IS THERE AT THE CUT" if there else ", no cloud at the cut"))
    out_at_cut = [names[i] for i in JETN if gas(i, cut)]
    print(f"  gas out at the cut: {out_at_cut or 'none'}")
    cam = scene.camera
    r = scene.render
    view_h = cam.data.ortho_scale
    view_w = view_h * r.resolution_x / r.resolution_y
    right = cam.location.x + view_w / 2
    hi, hi_f, exit_f = -1.0, None, None
    for f in range(NF):
        scene.frame_set(f)
        lo_b, hi_b = C["mesh_box"](C["imported"])
        if hi_b.z > hi:
            hi, hi_f = hi_b.z, f
        if launch is not None and f > launch and exit_f is None:
            tail_x = min([nozzle_world(i, f)[0].x - FAR for i in JETN if gas(i, f) and M["nozzles"][i]["group"] == "back"] + [lo_b.x])
            if tail_x > right + 0.1:
                exit_f = f
    print(f"  frame {r.resolution_x}x{r.resolution_y}: {view_w:.3f} x {view_h:.3f} m, x {cam.location.x - view_w / 2:.2f}..{right:.2f}; "
          f"the car's top {hi:.3f} m at frame {hi_f} ({view_h - hi:.2f} m below the frame's top)")
    print(f"  off the screen (the car and its rear jets' 3.5 m past x {right:.2f} + 0.1): frame {exit_f}")
    runs = {}
    for i in JETN:
        for f in range(NF):
            if gas(i, f):
                a = bend(i, f)
                if a > 10:
                    runs.setdefault(names[i], []).append((f, a))
    for n, fa in runs.items():
        spans, start, prev = [], fa[0][0], fa[0][0]
        for f, _ in fa[1:] + [(None, 0)]:
            if f != (prev + 1 if prev is not None else None):
                spans.append(f"{start}-{prev}")
                start = f
            prev = f
        print(f"  jet {n} turned with the car by more than 10 deg on {len(fa)} frames ({', '.join(spans)}), at most {max(a for _, a in fa):.0f} deg")
    if not runs:
        print("  no jet turns with the car by more than 10 deg")
    straight = sorted({f for i in JETN for f in range(NF) if gas(i, f) and bend(i, f) > 3.0})
    doc = dict(format="roadster-show-timeline/1", motion=os.path.relpath(args.motion, ROOT), fps=FPS, frames=NF,
               px=[r.resolution_x, r.resolution_y], ppm=args.ppm, cut=cut, launch=launch, still=mk.get("still"),
               touchdown=touch, melt_end=melt_end, melt_time=args.melt_time, exit=exit_f, car_top_m=round(hi, 3),
               clouds=[dict(first=cl["first"], last=cl["last"], gone=cl["gone"]) for cl in CLOUDS],
               frame_top_m=round(view_h, 3), straight_frames=[straight[0], straight[-1]] if straight else None,
               burns={names[i]: BURNS[i] for i in JETN})
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "timeline.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"  frames where --gas straight differs: {doc['straight_frames']} -> {os.path.join(OUT, 'timeline.json')}")
    return exit_f


if args.list and SHOW:
    summary()
elif args.list:
    for f in range(0, NF, 3):
        st = cloud_state(f)
        js = [jet_vdb(i, f) for i in DOWN]
        tau = CLOUDS[0]["tau"][f] if CLOUDS else 0.0
        off = (f - last) / FPS if last is not None and f > last else 0.0
        print(f"  f{f:3d} t={f / FPS:.2f} {FR[f]['phase']:8s} h={height(DOWN[0], f):.2f} jet {js[0]} w={weight(DOWN[0], f):.2f}/"
              f"{weight(DOWN[0], f - DELAY):.2f} feed={feed[f]:.2f} tau={tau:.2f} off={off:.2f} cloud "
              + (" ".join(f"{k}={v:.2f}" for k, v in st.items()) if st else "-"))
if args.list:
    sys.exit(0)


# --- node helpers ---
def node_kit(m):
    nt = m.node_tree
    N, L = nt.nodes.new, nt.links.new

    def put(sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            L(v, sock)
        else:
            sock.default_value = v

    def op(kind, a, b=None):
        x = N("ShaderNodeMath")
        x.operation = kind
        put(x.inputs[0], a)
        if b is not None:
            put(x.inputs[1], b)
        return x.outputs[0]

    def ramp(v, a0, a1, b0, b1, smooth=True, clamp=True):
        x = N("ShaderNodeMapRange")
        x.interpolation_type = "SMOOTHSTEP" if smooth else "LINEAR"
        x.clamp = clamp
        put(x.inputs["Value"], v)
        for name, val in (("From Min", a0), ("From Max", a1), ("To Min", b0), ("To Max", b1)):
            put(x.inputs[name], val)
        return x.outputs["Result"]

    def val(name, v=0.0):
        x = N("ShaderNodeValue")
        x.name = name
        x.outputs[0].default_value = v
        return x.outputs[0]
    return N, L, op, ramp, val


def setv(m, name, v):
    m.node_tree.nodes[name].outputs[0].default_value = v


# --- 3. the jets on the car ---
def jet_material(k, tail=False, suffix="", band=None):
    """The approved V2 material (jet_probe_a2.py) with the floor, the end, the strength and the streaks per jet;
    tail: also the upper end of a burn's gas once its valve has closed (show B's short burns: burn_spec)."""
    m = J["jet_material"](1.0)
    m.name = f"jet-{k}{suffix}"
    nt = m.node_tree
    N, L, op, ramp, val = node_kit(m)
    # its floor cut (d 3.0 -> 3.02 m) becomes the jet's own end: fading over 3.0 -> 3.5 m
    ends = [n for n in nt.nodes if n.type == "MAP_RANGE" and abs(n.inputs["From Min"].default_value - JET_FLOOR) < 1e-6
            and abs(n.inputs["From Max"].default_value - JET_FLOOR - 0.02) < 1e-6 and not n.inputs["From Min"].is_linked]
    assert len(ends) == 1, f"landing_jets: the jet's floor cut not found ({len(ends)})"
    ends[0].interpolation_type = "SMOOTHSTEP"
    ends[0].inputs["From Max"].default_value = JET_FLOOR + 0.5
    # d, metres below the exit, as the material computes it
    tc = N("ShaderNodeTexCoord")
    v = N("ShaderNodeVectorMath")
    v.operation = "SUBTRACT"
    L(tc.outputs["Object"], v.inputs[0])
    v.inputs[1].default_value = SRC
    dot = N("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    L(v.outputs["Vector"], dot.inputs[0])
    dot.inputs[1].default_value = AXIS
    d_m = op("MULTIPLY", op("SUBTRACT", op("DIVIDE", dot.outputs["Value"], VOXEL), EXIT_D), AX_VOX)
    w = ramp(d_m, 0.0, JET_FLOOR, val("w_now", 1.0), val("w_then", 1.0), smooth=False)
    geo = N("ShaderNodeNewGeometry")
    sz = N("ShaderNodeSeparateXYZ")
    L(geo.outputs["Position"], sz.inputs[0])
    floor = ramp(sz.outputs["Z"], -0.02, 0.0, 0.0, 1.0, smooth=False)  # the real floor (A2: the same 2 cm band)
    k_all = op("MULTIPLY", w, floor)
    if tail:  # no gas above tail0, all of it below tail1 (m below the exit); -1.3 / -1.0: from the exit
        k_all = op("MULTIPLY", k_all, ramp(d_m, val("tail0", -1.3), val("tail1", -1.0), 0.0, 1.0))
    if band:  # --gas straight: one piece of the jet, from a0..a1 to b0..b1 m below the exit (smooth overlaps summing to 1)
        k_all = op("MULTIPLY", k_all, ramp(d_m, val("a0", -2.0), val("a1", -1.9), 0.0, 1.0))
        k_all = op("MULTIPLY", k_all, ramp(d_m, val("b0", 9.0), val("b1", 9.1), 1.0, 0.0))
    for vol in [n for n in nt.nodes if n.type == "PRINCIPLED_VOLUME"]:
        src = vol.inputs["Density"].links[0].from_socket
        L(op("MULTIPLY", src, k_all), vol.inputs["Density"])
    return m


JETS = []
if not args.no_jets:
    for k, i in enumerate(JETN):
        nz = M["nozzles"][i]
        assert nz["group"] != "down" or tuple(nz["dir"]) == (0, 0, -1), "landing_jets: lift nozzles point down in the chassis frame"
        holder = bpy.data.objects.new(f"nozzle {nz['name']}", None)
        scene.collection.objects.link(holder)
        holder.parent = car
        holder.location = nz["pos"]
        if tuple(nz["dir"]) != (0, 0, -1):  # the side and rear jets: the same jet turned onto the nozzle's axis
            holder.rotation_mode = "QUATERNION"
            holder.rotation_quaternion = Vector((0, 0, -1)).rotation_difference(Vector(nz["dir"]))
        src = bpy.data.objects.new(f"source {nz['name']}", None)
        scene.collection.objects.link(src)
        src.parent = holder
        src.location = (0, 0, EXIT_D * AX_VOX)
        src.scale = (1, 1, JA.stretch)
        # a material per burn whose gas is out at once (a new burn's head may meet the last one's tail)
        slots = max([len(gas(i, f)) for f in range(NF)] + [1])
        tail = any(c is not None and c - g < B1 + 20 for g, c in BURNS[i])
        mats = [jet_material(k, tail, "" if n == 0 else f"-{n}") for n in range(slots)]
        pieces = []
        if args.gas == "straight":
            pieces = [[jet_material(k, True, f"-s{sl}p{j}", True) for j in range(args.gas_pieces)] for sl in range(slots)]
        local = holder.matrix_basis @ src.matrix_basis  # the jet's source frame in the chassis frame
        JETS.append(dict(i=i, name=nz["name"], src=src, mats=mats, tail=tail, seed=Vector((7.3 * k, 0.0, -5.1 * k)),
                         pieces=pieces, local=local.copy()))
PER_M = VOXEL / AX_VOX  # VDB units per metre along the axis


def loaded(ob):
    """Load a new volume now, alone: Blender 5.2 can deadlock when the depsgraph loads several VDB files at once
    (volume_grid::file_cache mutex held across a TBB wait: one clip hung at frame 28); later loads of the same
    file (the render's own depsgraph) hit the cache."""
    bpy.context.view_layer.update()
    return ob


def jets_at(f):
    obs = []
    t = f / FPS
    vols = {}  # one Volume per prepared VDB (the landing: one for the four jets, one file load), each object its material
    for n, jt in enumerate(JETS):
        i = jt["i"]
        for m in jt["mats"] + [m for sl in jt["pieces"] for m in sl]:
            flow, noise = m.node_tree.nodes.get("flow"), m.node_tree.nodes.get("streaks")
            if flow is not None:  # as A3's clip, plus a per-jet offset of the streaky noise
                flow.inputs[1].default_value = tuple(AXIS * (JA.flow * t * PER_M) + jt["seed"])
            if noise is not None and JA.shimmer > 0:
                noise.inputs["W"].default_value = JA.shimmer * t + 3.7 * n
        straight = jt["pieces"] and bend(i, f) > 3.0
        for kb, spec in gas(i, f):
            burn = BURNS[i][kb]
            todo = straight_pieces(jt, f, kb, spec) if straight else [(jt["mats"][kb % len(jt["mats"])], None, None)]
            for m, e, band in todo:
                setv(m, "w_now", weight(i, f, burn))
                setv(m, "w_then", weight(i, f - DELAY, burn))
                if jt["tail"] or e is not None:
                    tl = spec[3]
                    setv(m, "tail0", tl - 0.15 if tl > 0 else -1.3)
                    setv(m, "tail1", tl + 0.15 if tl > 0 else -1.0)
                key = spec[:3] + (band,)
                if key not in vols:
                    vol = bpy.data.volumes.new("jet")
                    vol.filepath = J["prepared"](spec[0]) if spec[1] is None else J["prepared"](spec[0], spec[1], spec[2])
                    if band is not None:
                        vol.filepath = piece_vdb(vol.filepath, *band)
                    vol.render.precision = "FULL"
                    vol.materials.append(m)
                    vols[key] = vol
                ob = bpy.data.objects.new(f"jet-{jt['name']}" + (f"-{kb}" if len(BURNS[i]) > 1 else "")
                                          + ("" if e is None else f"-at{e}"), vols[key])
                ob.material_slots[0].link = "OBJECT"
                ob.material_slots[0].material = m
                if e is None:
                    ob.parent = jt["src"]
                    ob.matrix_basis = J["LOCAL"]
                else:
                    ob.matrix_world = Matrix.Translation(pivot_world(f) - pivot_world(e)) @ car_world(e) @ jt["local"] @ J["LOCAL"]
                scene.collection.objects.link(ob)
                obs.append(loaded(ob))
    return obs


def straight_pieces(jt, f, kb, spec):
    """--gas straight: [(material, emission frame, crop)] of burn kb of a jet at frame f. The gas out goes in as many
    pieces along the jet as its directions at leaving spread over (one per 12 deg, at most --gas-pieces), each placed
    as the nozzle was when its middle left; a single piece is the whole jet, several are cropped to their stretch of
    the jet (piece_vdb) so that they do not all march the whole jet."""
    i = jt["i"]
    g, c = BURNS[i][kb]
    after = c is not None and f >= c
    tl = spec[3]
    em = list(emitted(i, f, kb, spec)) or [min(f, c - 1) if after else f]
    d0 = nozzle_world(i, em[0])[1]
    spread = max(math.degrees(d0.angle(nozzle_world(i, e)[1], 0.0)) for e in em)
    mats = jt["pieces"][kb % len(jt["pieces"])]
    n = min(max(math.ceil(spread / args.gas_turn), 1), len(mats))
    top = tl if after else 0.0
    edges = [round((top + (FAR - top) * j / n) * 20) / 20 for j in range(n + 1)]  # 5 cm steps: fewer crops to cache
    h = 0.25 * (FAR - top) / n
    out = []
    for j in range(n):
        mid = (edges[j] + edges[j + 1]) / 2
        e = c - 1 - round(max(mid - tl, 0.0) / V_GAS) if after else f - round(mid / V_GAS)
        e = min(max(e, g, 0), f)
        m = mats[j]
        lo, hi = (edges[j] if j else None), (edges[j + 1] if j < n - 1 else None)
        setv(m, "a0", -2.0 if lo is None else lo - h)
        setv(m, "a1", -1.9 if lo is None else lo + h)
        setv(m, "b0", 9.0 if hi is None else hi - h)
        setv(m, "b1", 9.1 if hi is None else hi + h)
        out.append((m, e, None if n == 1 else (lo, hi, round(h, 3))))
    return out


PIECES = os.path.join(args.jet_cache, "pieces")
_D_M = None


def piece_vdb(path, lo, hi, h):
    """The prepared VDB at path with only its gas from lo - h to hi + h m below the exit (None: no end) and a voxel or
    two beyond: Cycles marches a volume over its active voxels, so pieces each holding the whole jet cost a whole jet
    each (a flip frame with 8 pieces a jet took 150-350 s instead of a few)."""
    global _D_M
    key = os.path.basename(path)[:-4] + f"-p{'' if lo is None else f'{lo:.2f}'}_{'' if hi is None else f'{hi:.2f}'}_{h:.3f}.vdb"
    dst = os.path.join(PIECES, key)
    if os.path.exists(dst):
        return dst
    b0, b1 = J["B0"], J["B1"]
    shape = tuple(y - x for x, y in zip(b0, b1))
    if _D_M is None:  # metres below the exit of every voxel of the box, as the material computes it
        idx = [np.arange(x, y, dtype=np.float32) - J["SRC_IJK"][k] for k, (x, y) in enumerate(zip(b0, b1))]
        dv = idx[0][:, None, None] * AXIS.x + idx[1][None, :, None] * AXIS.y + idx[2][None, None, :] * AXIS.z
        _D_M = (dv - EXIT_D) * AX_VOX
    keep = np.ones(shape, np.float32)
    pad = 2 * AX_VOX
    if lo is not None:
        keep[_D_M < lo - h - pad] = 0.0
    if hi is not None:
        keep[_D_M > hi + h + pad] = 0.0
    grids = []
    for name in ("density", "haze"):
        src = vdb.read(path, name)
        a = np.zeros(shape, np.float32)
        src.copyToArray(a, ijk=b0)
        gr = vdb.FloatGrid()
        gr.copyFromArray(np.ascontiguousarray(a * keep), ijk=b0, tolerance=2e-5)
        gr.name = name
        gr.transform = src.transform
        grids.append(gr)
    os.makedirs(PIECES, exist_ok=True)
    vdb.write(dst, grids=grids)
    return dst


def car_world(f):
    """The chassis frame at frame f (car_shot.py keys the 'car' empty with motion.json's pos and quat)."""
    fr = FR[f]
    return Matrix.Translation(fr["pos"]) @ Quaternion(fr["quat"]).to_matrix().to_4x4()


PIVOT = Vector(M["car"]["pivot"])  # the roll axis' point in the chassis frame


def pivot_world(f):
    return car_world(f) @ PIVOT


# --- 4. the cloud: per lift jet a Chaotic copy at its foot and a Rolling copy rolling outwards ---
# the car's inside, chassis frame, m: (x from, to), half width, (z from, to) — the body, the nose and the cabin,
# a few cm inside the model's outline (its side profile: floor 0.10-0.19, nose top 0.42-0.54, roof 1.07)
CAR_BOXES = [((-1.95, 1.55), 0.80, (0.18, 0.72)), ((1.55, 2.05), 0.72, (0.18, 0.46)), ((-1.2, 0.5), 0.70, (0.70, 0.98))]


def cloud_material(name, cut=None):
    """Probe B's law and envelope, every number a Value node set per frame (centre, R, H, ...)."""
    m = bpy.data.materials.new(name)
    m.node_tree.nodes.clear()
    N, L, op, ramp, val = node_kit(m)
    a = N("ShaderNodeAttribute")
    a.attribute_name = "density"
    erode = val("erode")
    rho = op("DIVIDE", op("MAXIMUM", op("SUBTRACT", a.outputs["Fac"], erode), 0.0), op("SUBTRACT", 1.0, erode))
    dens = op("MULTIPLY", op("POWER", op("MAXIMUM", rho, 0.0), 2.0), val("k"))  # 120 / units * gains
    if cut:  # the Rolling asset's emitter slab faded out: object space (VDB units) y
        tc = N("ShaderNodeTexCoord")
        sy = N("ShaderNodeSeparateXYZ")
        L(tc.outputs["Object"], sy.inputs[0])
        dens = op("MULTIPLY", dens, ramp(sy.outputs["Y"], cut[0], cut[1], 0.0, 1.0))
    geo = N("ShaderNodeNewGeometry")
    rel = N("ShaderNodeVectorMath")  # position relative to the source (the jet's first foot), metres
    rel.operation = "SUBTRACT"
    L(geo.outputs["Position"], rel.inputs[0])
    cen = N("ShaderNodeCombineXYZ")
    L(val("cx"), cen.inputs["X"])
    L(val("cy"), cen.inputs["Y"])
    L(cen.outputs["Vector"], rel.inputs[1])
    p = N("ShaderNodeSeparateXYZ")
    L(rel.outputs["Vector"], p.inputs[0])
    # r: the distance along the floor to the path of the jet's feet, a segment from the first foot (cx, cy) along
    # (ux, uy) — a point when the car goes straight up and down (inv_l2 = 1 / its length^2, 0 for a point)
    ux, uy, il2 = val("ux"), val("uy"), val("inv_l2")
    t = op("MULTIPLY", op("ADD", op("MULTIPLY", p.outputs["X"], ux), op("MULTIPLY", p.outputs["Y"], uy)), il2)
    t = op("MINIMUM", op("MAXIMUM", t, 0.0), 1.0)
    ex, ey = op("SUBTRACT", p.outputs["X"], op("MULTIPLY", t, ux)), op("SUBTRACT", p.outputs["Y"], op("MULTIPLY", t, uy))
    r = op("SQRT", op("ADD", op("MULTIPLY", ex, ex), op("MULTIPLY", ey, ey)))
    z = p.outputs["Z"]
    # the uneven front: noise of the size ~R/1.5 about the source (it grows with the cloud), seeded per source
    sc = N("ShaderNodeVectorMath")
    sc.operation = "SCALE"
    L(rel.outputs["Vector"], sc.inputs[0])
    L(val("noise_k"), sc.inputs["Scale"])  # 1.5 / R
    sd = N("ShaderNodeVectorMath")
    sd.operation = "ADD"
    L(sc.outputs["Vector"], sd.inputs[0])
    sd.name = "seed"
    nz = N("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 1.0
    nz.inputs["Detail"].default_value = 2.0
    L(sd.outputs["Vector"], nz.inputs["Vector"])
    n = op("SUBTRACT", nz.outputs["Fac"], 0.5)
    grow = ramp(op("ADD", r, op("MULTIPLY", n, val("jR"))), val("R_lo"), val("R_hi"), 1.0, 0.0)
    cap = ramp(op("ADD", z, op("MULTIPLY", n, val("jH"))), val("H_lo"), val("H_hi"), 1.0, 0.0)
    hole = ramp(op("ADD", r, op("MULTIPLY", n, val("jI"))), val("I_lo", -2.0), val("I_hi", -1.0), args.hole_floor, 1.0)
    dens = op("MULTIPLY", op("MULTIPLY", op("MULTIPLY", dens, grow), cap), hole)
    # no gas inside the car: the cloud's volumes pass through the body, and through the glass the cabin
    # showed full of fog. Two soft boxes in the chassis frame (the car empty: x forward, y left, z up from
    # the floor at ride height): the body and the cabin above it; under the floor the gas stays.
    tcar = N("ShaderNodeTexCoord")
    tcar.object = car
    q = N("ShaderNodeSeparateXYZ")
    L(tcar.outputs["Object"], q.inputs[0])
    inside = None
    for (x0, x1), w, (z0, z1) in CAR_BOXES:
        e = 0.04
        b = op("MULTIPLY", ramp(q.outputs["X"], x0 - e, x0 + e, 0.0, 1.0), ramp(q.outputs["X"], x1 - e, x1 + e, 1.0, 0.0))
        b = op("MULTIPLY", b, ramp(op("ABSOLUTE", q.outputs["Y"]), w - e, w + e, 1.0, 0.0))
        b = op("MULTIPLY", b, op("MULTIPLY", ramp(q.outputs["Z"], z0 - e, z0 + e, 0.0, 1.0), ramp(q.outputs["Z"], z1 - e, z1 + e, 1.0, 0.0)))
        inside = b if inside is None else op("MAXIMUM", inside, b)
    dens = op("MULTIPLY", dens, op("SUBTRACT", 1.0, inside))
    vol = N("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (args.albedo, args.albedo, args.albedo, 1.0)
    vol.inputs["Density Attribute"].default_value = ""
    vol.inputs["Anisotropy"].default_value = args.aniso
    L(dens, vol.inputs["Density"])
    out = N("ShaderNodeOutputMaterial")
    L(vol.outputs["Volume"], out.inputs["Volume"])
    return m


def set_envelope(m, st, start, end, units, gain):
    """The envelope of cloud state st about the path of a jet's feet from start to end (the same point: a circle)."""
    R, H, Ri = st["R"], st["H"], st["hole"]
    u = end - start
    l2 = u.x * u.x + u.y * u.y
    for key, v in (("ux", u.x), ("uy", u.y), ("inv_l2", 1.0 / l2 if l2 > 1e-8 else 0.0)):
        setv(m, key, v)
    for key, v in (("erode", st["erode"]), ("k", 120.0 / units * gain), ("cx", start.x), ("cy", start.y), ("noise_k", 1.5 / R),
                   ("jR", 2 * args.jitter * R), ("R_lo", R * (1 - args.soft)), ("R_hi", R * (1 + args.soft)),
                   ("jH", 0.6 * H), ("H_lo", 0.55 * H), ("H_hi", 1.1 * H)):
        setv(m, key, v)
    if Ri > 1e-3:
        for key, v in (("jI", 2 * args.jitter * Ri), ("I_lo", Ri * (1 - args.soft)), ("I_hi", Ri * (1 + args.soft))):
            setv(m, key, v)
    else:
        for key, v in (("jI", 0.0), ("I_lo", -2.0), ("I_hi", -1.0)):
            setv(m, key, v)


def floor_centre(path, units_up=1.5):
    """Where the Chaotic asset's dense floor blob is (VDB units, x and y): the centroid of rho^2 near the floor."""
    g = vdb.read(path, "density")
    (i0, j0, k0), (i1, j1, k1) = g.evalActiveVoxelBoundingBox()
    kz = max(1, int(units_up / g.transform.voxelSize()[0]))
    a = np.zeros((i1 - i0 + 1, j1 - j0 + 1, kz), np.float32)
    g.copyToArray(a, ijk=(i0, j0, 0))
    w = (a ** 2).sum(axis=2)
    ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
    x, y, _ = g.transform.indexToWorld(((w * ii).sum() / w.sum(), (w * jj).sum() / w.sum(), 0.0))
    return x, y


SOURCES = []  # per cloud: per lift jet a Chaotic and a Rolling copy, each its own materials (the envelope per frame)
if not args.no_cloud:
    cut = [float(v) for v in args.rolling_cut.split(",")]
    # the emitter is fixed in the asset's scene: one centre for all frames (re-centring per frame would jitter)
    cxy = np.mean([floor_centre(args.chaotic.format(fr)) for fr in (0, 100, 200)], axis=0)
    for c in range(len(CLOUDS)):
        srcs = []
        for k, i in enumerate(DOWN):
            nz = M["nozzles"][i]
            side = 1 if nz["pos"][0] > 0 else -1  # front jets roll forward, rear ones backward
            tag = nz["name"] + (f"-{c + 1}" if c else "")
            srcs.append(dict(i=i, name=tag, side=side, rot=k * math.pi / 2, c0=(37 * k) % 300, r0=(75 * k + 150 * (k % 2)) % 300,
                             cmat=cloud_material(f"chaotic-{tag}"), rmat=cloud_material(f"rolling-{tag}", cut)))
            for m, off in ((srcs[-1]["cmat"], 0.0), (srcs[-1]["rmat"], 1.0)):  # another uneven front for every cloud
                m.node_tree.nodes["seed"].inputs[1].default_value = (11.3 * k + off * 5.0 + 23.9 * c, -7.7 * k + 13.1 * c, 3.1 * k)
        SOURCES.append(srcs)
    CXY = cxy
    print(f"landing_jets: Chaotic floor blob centre {tuple(round(v, 2) for v in cxy)} VDB units; {len(CLOUDS)} cloud(s), "
          f"sources {[s['name'] for s in SOURCES[0]] if SOURCES else []}")


def camera_blind(m):
    """--layer car-lit: no gas on the camera rays themselves (density x (1 - Is Camera Ray)); every ray after the
    first bounce (light on the car, reflections in the paint, the view through the glass) sees it as it is. Not
    hidden from the camera (ray visibility): a camera ray must still enter the volumes for a bounce inside them."""
    N, L, op, ramp, val = node_kit(m)
    lp = N("ShaderNodeLightPath")
    keep = op("SUBTRACT", 1.0, lp.outputs["Is Camera Ray"])
    for vol in [n for n in m.node_tree.nodes if n.type == "PRINCIPLED_VOLUME"]:
        src = vol.inputs["Density"].links[0].from_socket
        L(op("MULTIPLY", src, keep), vol.inputs["Density"])


if args.layer == "car-lit":
    for m in [m for jt in JETS for m in jt["mats"] + [m for sl in jt["pieces"] for m in sl]] \
            + [s[key] for srcs in SOURCES for s in srcs for key in ("cmat", "rmat")]:
        camera_blind(m)


def volume(name, path, units, mat, rot_z, loc, precision="HALF"):
    v = bpy.data.volumes.new(name)
    v.filepath = path
    v.render.precision = precision
    v.materials.append(mat)
    ob = bpy.data.objects.new(name, v)
    ob.scale = (units, units, units)
    ob.rotation_euler = (0.0, 0.0, rot_z)
    ob.location = loc
    scene.collection.objects.link(ob)
    return loaded(ob)


def cloud_at(f):
    """The volumes of the clouds there at frame f and {k: state}. Each lies where it was blown (lay): its copies about
    the anchor, its envelope about the path of the feet; it no longer follows the car."""
    obs, states = [], clouds_at(f)
    if args.no_cloud:
        return obs, states
    cut0 = float(args.rolling_cut.split(",")[0])
    for k, st in states.items():
        for s in SOURCES[k]:
            anchor, a, b = lay(k, s["i"], f)
            # Chaotic: its floor blob on the anchor, scaled about it by size
            u = args.chaotic_scale * st["size"]
            set_envelope(s["cmat"], st, a, b, u, args.chaotic_gain * st["gain"])
            rot = s["rot"]
            off = Matrix.Rotation(rot, 3, "Z") @ Vector((u * CXY[0], u * CXY[1], 0.0))
            obs.append(volume(f"chaotic-{s['name']}", args.chaotic.format((s["c0"] + f) % 300), u, s["cmat"], rot, anchor - off))
            # Rolling: from rolling-start (x size) off the anchor outwards along the floor
            u = args.rolling_scale * st["size"]
            set_envelope(s["rmat"], st, a, b, u, args.rolling_gain * st["gain"] * st["rgain"])
            side = s["side"]
            start = args.rolling_start * st["size"]
            loc = anchor + Vector((side * (start - u * cut0), side * u * 0.1, 0.0))
            obs.append(volume(f"rolling-{s['name']}", args.rolling.format((s["r0"] + f) % 300), u, s["rmat"], -side * math.pi / 2, loc))
    return obs, states


# --- 5. render ---
if args.mask:
    white = bpy.data.materials.new("mask")
    nt = white.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1, 1, 1, 1)
    nt.links.new(em.outputs[0], nt.nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    bpy.context.view_layer.material_override = white
    scene.render.use_motion_blur = False
    scene.eevee.taa_render_samples = min(args.samples, 8)


def car_border(margin_px=12):
    """--layer car-lit renders only the car's box on the frame (its camera rays still march through the gas, at no
    density: outside the car that would be all cost and no picture); the frame keeps its size, transparent around."""
    lo, hi = C["mesh_box"](C["imported"])
    r = scene.render
    cam = scene.camera
    w, h = r.resolution_x, r.resolution_y
    ppm = w / (cam.data.ortho_scale * w / h)  # px per metre: the view is ortho_scale high (sensor fit vertical)
    x0 = (lo.x - cam.location.x) * ppm + w / 2 - margin_px
    x1 = (hi.x - cam.location.x) * ppm + w / 2 + margin_px
    y0 = (lo.z - cam.location.z) * ppm + h / 2 - margin_px  # from the bottom, as Blender's border
    y1 = (hi.z - cam.location.z) * ppm + h / 2 + margin_px
    r.use_border, r.use_crop_to_border = True, False
    r.border_min_x, r.border_max_x = max(x0 / w, 0.0), min(x1 / w, 1.0)
    r.border_min_y, r.border_max_y = max(y0 / h, 0.0), min(y1 / h, 1.0)
    if (r.border_max_x - r.border_min_x) * w < 2 or (r.border_max_y - r.border_min_y) * h < 2:
        r.use_border = False  # the car is off the frame (show B drives in from beyond the left edge): an empty border
        # is Blender's 'Image too small'; the whole frame renders transparent (the gas is unseen by this layer's camera)


def render(f, path):
    scene.frame_set(f)
    if args.layer == "car-lit":
        car_border()
    t0 = time.time()
    obs = jets_at(f)
    cobs, sts = cloud_at(f)
    obs += cobs
    scene.render.filepath = path
    t1 = time.time()
    bpy.ops.render.render(write_still=True)
    spec = jet_vdb(DOWN[0], f)
    print(f"landing_jets: frame {f} ({f / FPS:.2f} s, {FR[f]['phase']}) jet {spec} w={weight(DOWN[0], f):.2f} gas objects "
          f"{len(obs) - len(cobs)} "
          + ("; ".join(f"cloud {k + 1} " + " ".join(f"{n}={v:.2f}" for n, v in st.items()) for k, st in sts.items()) or "cloud -")
          + f" | set up {t1 - t0:.1f} s, rendered in {time.time() - t1:.1f} s -> {path}")
    datas = {ob.data for ob in obs}
    for ob in obs:
        bpy.data.objects.remove(ob)
    for data in datas:
        bpy.data.volumes.remove(data)


t_all = time.time()
if args.clip:
    a, b, step = 0, NF - 1, 1
    if args.range:
        parts = [int(x) for x in args.range.split(":")]
        a, b = parts[0], parts[1]
        step = parts[2] if len(parts) > 2 else 1
    folder = os.path.join(OUT, "clip-mask" if args.mask else "clip" if args.layer == "full" else args.layer)
    os.makedirs(folder, exist_ok=True)
    todo = range(a, b + 1, step)
    for f in todo:  # a frame already there is kept: a stopped clip goes on where it stopped
        path = os.path.join(folder, f"{f:04d}{EXT}")
        if not os.path.exists(path):
            while args.wait_ac and "AC Power" not in subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout:
                print(f"landing_jets: {time.strftime('%H:%M')} on battery, frame {f} waits for the charger", flush=True)
                time.sleep(60)
            render(f, path)
    print(f"landing_jets: clip {len(todo)} frames in {time.time() - t_all:.0f} s ({(time.time() - t_all) / len(todo):.1f} s a frame) -> {folder}")
else:
    os.makedirs(OUT, exist_ok=True)
    marks = {v: k for k, v in M["marks"].items() if v is not None}
    for tok in args.frames.split(","):
        name, _, fr = tok.strip().rpartition("=")
        f = int(fr) if fr.isdigit() else M["marks"][fr]
        name = name or marks.get(f, fr if not fr.isdigit() else "frame")
        tag = "-mask" if args.mask else "" if args.layer == "full" else f"-{args.layer}"
        render(f, os.path.join(OUT, f"{f:03d}-{name}{tag}{EXT}"))
    print(f"landing_jets: done in {time.time() - t_all:.0f} s")
