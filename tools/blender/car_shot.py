"""Car shot: the Roadster in Blender, moved by our physics. No jets, no clouds (the next stage adds them
to this scene: run this script with --build-only through runpy, as cloud_probe_b.py runs jet_probe_a2.py).

The motion comes from tools/export_motion.mjs (out/<show>/motion.json, 60 frames/s, Blender axes): per
frame the chassis frame (pos + quat), per wheel its spin and suspension offset; they become keyframes,
linear between frames, so Cycles' motion blur sees the real motion.

The car:
  - assets/models/roadster/tesla-roadster-2020.glb (metarex.4d, CC BY 4.0, CREDITS.md). Blender's glTF
    importer turns the file Z-up itself (forward -y, the car's left +x); an empty 'yaw' under the chassis
    turns it to face +x (models.js yaw, about z here as about y in three.js), scales it to the real 4.2 m
    (models.js scale 0.908) and lifts it by models.js lift. The chassis frame is the one of models.js in
    Blender axes: origin on the floor under the car at ride height, x forward, y the car's left (away
    from the camera), z up.
  - Wheels as in src/main.js: each TR.DEF-Wheel.* (tyre, rim, disc) turns about its own centre (the
    bounding box of its meshes) inside an empty that rides the suspension; the calipers
    (TR.DEF-WheelBrake.*) ride the suspension only. The wheel centre sits at the physics' wheel radius
    above the chassis origin (models.js r): the file's rear wheels are 8.7 mm higher than its front
    ones, so without this the rear tyres would float 2 px above the floor at ride height.
  - Materials: the model's own (the paint is the original silver: white base, metallic 0.48), only for
    realism: the paint's clear coat polished (coat roughness 0.117 -> --coat-roughness), the tinted glass
    smooth (its coat roughness 0.157 in the file frosts the key light's reflection into a grey haze over
    the whole window), the indicators off (they glow orange in the file), the lamps' emission tamed
    (--lamps: 10 in the file burns them to flat white).
Light: look a of the jet and cloud probes (neutral, for the desktop wallpaper): the studio HDRI
studio_small_09 at 0.8 and the big key from the front-left above, placed against the floor as in
cloud_probe_b.py (5.6 m up, aimed 1.5 m above the floor at the car's middle). The tinted glass is
excluded from the key (light linking, --glass-key brings it back): the 3 m softbox mirrors in the side
windows as big white patches, a studio would flag it off the glass.
Camera: orthographic from the side, --ppm pixels per metre (216 for frames, 108 for drafts), the floor at
the bottom edge, the car's middle at frame 0 in the middle; transparent background.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/blender/car_shot.py -- \
        out/landing/stills [--motion out/landing/motion.json --frames hover,descent_mid,deepest --samples 48]
      ~3 s a frame on an M1 Pro (1600x936, 48 samples, Metal). Drafts: --ppm 108 --samples 16.
      Eevee preview of the whole motion (0.4 s a frame), then tools/landing_sheet.py --video:
        ... -- out/landing/preview --engine eevee --clip --ppm 108 --samples 16 --stamp
      --frames takes the marks of motion.json (hover, descent_mid, touchdown, deepest, still) or frame numbers.
Out:  OUT/<frame>-<mark>.png, RGBA, transparent, floor at the bottom edge; --clip: OUT/clip/<frame>.png
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ap = argparse.ArgumentParser(prog="car_shot.py")
ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "out", "landing", "stills"))
ap.add_argument("--motion", default=os.path.join(ROOT, "out", "landing", "motion.json"))
ap.add_argument("--frames", default="hover,descent_mid,deepest", help="marks of motion.json or frame numbers, comma-separated")
ap.add_argument("--ppm", type=float, default=216.0, help="pixels per metre (variant B: 108 pt/m, x2 on Retina)")
ap.add_argument("--px", type=int, default=0, help="frame width, px (0: 7.41 m, 1600 px at 216 px/m)")
ap.add_argument("--top", type=float, default=0.0, help="the frame's top edge above the floor, m (0: the car's highest point + 0.35 m)")
ap.add_argument("--py", type=int, default=0, help="frame height, px, exactly (show B: 1964 = the whole 3024x1964 screen at 216 px/m; "
                "0: from --top, rounded up to 8 px)")
ap.add_argument("--cx", type=float, default=None, help="the frame's middle, m (default: the car's middle at frame 0)")
ap.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])
ap.add_argument("--samples", type=int, default=48)
ap.add_argument("--blur", type=float, default=0.5, help="motion blur shutter in frames (0: off)")
ap.add_argument("--coat-roughness", type=float, default=0.03, help="the paint's clear coat (the file: 0.117)")
ap.add_argument("--lamps", type=float, default=2.0, help="emission strength of the head and tail lamps (the file: 10)")
ap.add_argument("--glass-key", action="store_true", help="let the key light reflect in the tinted glass (off by default)")
ap.add_argument("--clip", action="store_true", help="render every frame (or --range) to OUT/clip/")
ap.add_argument("--range", default="", help="first:last[:step] frames for --clip")
ap.add_argument("--stamp", action="store_true", help="burn time and phase into the image (previews)")
ap.add_argument("--build-only", action="store_true", help="build the scene and stop (for runpy)")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

OUT = os.path.abspath(args.out)
M = json.load(open(args.motion))
FPS = M["fps"]
CAR = M["car"]
FR = M["frames"]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 0, len(FR) - 1
bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"


def empty(name, parent=None, loc=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.2
    scene.collection.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    return ob


# --- the car: chassis -> yaw/scale/lift -> the file's own hierarchy ---
t0 = time.time()
car = empty("car")
car.rotation_mode = "QUATERNION"
yaw = empty("yaw", car, (0, 0, CAR["lift"]))
yaw.rotation_euler = (0, 0, CAR["yaw"])
yaw.scale = (CAR["scale"],) * 3
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(ROOT, CAR["url"]))
imported = [o for o in bpy.data.objects if o not in before]
for o in imported:
    if o.parent is None:
        o.parent = yaw
bpy.context.view_layer.update()


def mesh_box(obs):
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for o in obs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo, hi = Vector(map(min, lo, w)), Vector(map(max, hi, w))
    return lo, hi


# --- wheels: a suspension empty at the wheel's centre, a spin empty inside it ---
WHEELS = []
for w in M["wheels"]:
    node = bpy.data.objects[w["node"]]
    lo, hi = mesh_box([node] + list(node.children_recursive))
    centre = (lo + hi) / 2
    susp = empty(f"susp {w['node']}", car, centre)
    spin = empty(f"spin {w['node']}", susp)
    spin.rotation_mode = "XYZ"
    bpy.context.view_layer.update()
    for ob, holder in ((node, spin), (bpy.data.objects.get(w["caliper"]), susp)):
        if ob is None:
            continue
        mw = ob.matrix_world.copy()
        ob.parent = holder
        ob.matrix_parent_inverse.identity()
        ob.matrix_world = mw
    base = Vector((centre.x, centre.y, w["r"]))  # the physics' wheel centre height at ride height
    WHEELS.append(dict(susp=susp, spin=spin, base=base, node=node, visual=centre.copy(), r=(hi.z - lo.z) / 2))
    print(f"car_shot: {w['node']}: centre {tuple(round(v, 4) for v in centre)}, physics {tuple(w['pos'])}, "
          f"radius {(hi.z - lo.z) / 2:.4f} (physics {w['r']}), base moved {100 * (w['r'] - centre.z):+.2f} cm")

# --- materials: the model's own, a few realism fixes ---
for m in bpy.data.materials:
    if not m.node_tree:
        continue
    p = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if p is None:
        continue
    if m.name == "car_main_paint":
        p.inputs["Coat Roughness"].default_value = args.coat_roughness
        p.inputs["Coat IOR"].default_value = 1.5
    elif m.name in ("Glass_mid_tint", "Glass_Tint_max"):  # the tinted windows and roof: smooth glass, not frosted
        p.inputs["Roughness"].default_value = 0.0
        p.inputs["Coat Roughness"].default_value = 0.0
    elif m.name in ("indicator_left", "indicator_right"):
        p.inputs["Emission Strength"].default_value = 0.0
    elif p.inputs["Emission Strength"].default_value >= 5.0:  # head lamps, running lights, tail lamps
        p.inputs["Emission Strength"].default_value = args.lamps

# --- keyframes from the motion ---
for fr in FR:
    f = fr["f"]
    car.location = fr["pos"]
    car.rotation_quaternion = fr["quat"]
    car.keyframe_insert("location", frame=f)
    car.keyframe_insert("rotation_quaternion", frame=f)
    for W, wf in zip(WHEELS, fr["wheels"]):
        W["susp"].location = W["base"] + Vector((0, 0, wf["up"]))
        W["susp"].keyframe_insert("location", frame=f)
        W["spin"].rotation_euler = (0, wf["spin"], 0)  # about the axle (+y): + rolls forward (+x)
        W["spin"].keyframe_insert("rotation_euler", index=1, frame=f)
print(f"car_shot: car built and keyed ({len(FR)} frames) in {time.time() - t0:.1f} s")


# --- the rig in numbers: a wheel must turn about its own centre ---
def wheel_centre(W):
    lo, hi = mesh_box([W["node"]] + list(W["node"].children_recursive))
    return (lo + hi) / 2


scene.frame_set(0)
W0 = WHEELS[0]
c0 = wheel_centre(W0)
W0["spin"].rotation_euler[1] += 1.0
bpy.context.view_layer.update()
c1 = wheel_centre(W0)
W0["spin"].rotation_euler[1] -= 1.0
bpy.context.view_layer.update()
print(f"car_shot: rig check — {W0['node'].name} centre moves {1000 * (c1 - c0).length:.2f} mm when it turns 1 rad")

# --- camera: orthographic, from the side, the floor at the bottom edge ---
cx = args.cx if args.cx is not None else round(FR[0]["pos"][0] + CAR["pivot"][0], 3)
top = args.py / args.ppm if args.py else args.top
if top <= 0:
    hi_z = 0.0
    for f in sorted({0, len(FR) - 1} | {fr["f"] for fr in FR if fr["f"] % 10 == 0}):
        scene.frame_set(f)
        hi_z = max(hi_z, mesh_box(imported)[1].z)
    top = hi_z + 0.35
PX = args.px or round(7.4074 * args.ppm / 8) * 8
PY = args.py or int(math.ceil(top * args.ppm / 8) * 8)
view_h = PY / args.ppm
cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.sensor_fit = "VERTICAL"
cam_data.ortho_scale = view_h
cam_data.clip_end = 100
cam = bpy.data.objects.new("cam", cam_data)
cam.location = (cx, -30, view_h / 2)
cam.rotation_euler = (math.radians(90), 0, 0)
scene.collection.objects.link(cam)
scene.camera = cam


# --- light: look a of the probes (neutral, for the wallpaper) ---
def aim(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat("-Z", "Y").to_euler()


world = bpy.data.worlds.new("world")
scene.world = world
wn = world.node_tree.nodes
bg = wn.get("Background")
env = wn.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(os.path.join(ROOT, "assets", "hdri", "studio_small_09_1k.hdr"))
world.node_tree.links.new(env.outputs["Color"], bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.8
key_data = bpy.data.lights.new("key", "AREA")
key_data.energy = 1100
key_data.color = (1.0, 0.98, 0.96)
key_data.size = 3.0
key = bpy.data.objects.new("key", key_data)
key.location = (cx - 1.6, -2.6, 5.6)
scene.collection.objects.link(key)
aim(key, (cx, 0, 1.5))
# the tinted glass does not see the key (light linking): a 3 m softbox mirrors in the side windows as
# big white patches, a studio flags it off the glass with a black card; the paint keeps its reflection
GLASS = {"Glass_mid_tint", "Glass_Tint_max"}
if args.glass_key:
    flagged = []
else:
    flagged = [o for o in imported if o.type == "MESH" and {s.material.name for s in o.material_slots if s.material} & GLASS]
    receivers = bpy.data.collections.new("key receivers")
    for o in flagged:
        receivers.objects.link(o)
    key.light_linking.receiver_collection = receivers
    for co in receivers.collection_objects:
        co.light_linking.link_state = "EXCLUDE"

# --- render settings ---
r = scene.render
r.film_transparent = True
r.resolution_x, r.resolution_y, r.resolution_percentage = PX, PY, 100
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGBA"
r.use_motion_blur = args.blur > 0
r.motion_blur_shutter = max(args.blur, 0.01)
for vt in ("AgX", "Standard"):
    try:
        scene.view_settings.view_transform = vt
        break
    except TypeError:
        pass
if args.engine == "cycles":
    r.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == "METAL"
        scene.cycles.device = "GPU"
    except Exception as e:  # CPU works too, slower
        print("car_shot: GPU setup failed, CPU:", e)
    c = scene.cycles
    c.samples = args.samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.02
    c.use_denoising = True
    try:
        c.denoiser = "OPENIMAGEDENOISE"
        c.denoising_use_gpu = True
    except Exception as e:
        print("car_shot: denoiser:", e)
    c.max_bounces = 12
    c.glossy_bounces = 6
    c.transmission_bounces = 12
    c.transparent_max_bounces = 16
    c.film_transparent_glass = True  # the desktop shows through the windows
    # no persistent data (01.11): kept between frames with motion blur on, Cycles 5.2 now and then lost the light in
    # the glass of a car standing almost still (the springs settling by micrometres): the windows went black on one
    # frame, which one depending on the frames rendered before it (show B 568, 577 or 580); every frame built afresh
    # is clean (520-660 frame by frame), ~0.6 s a frame more
    r.use_persistent_data = False
else:
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            r.engine = eng
            break
        except TypeError:
            pass
    scene.eevee.taa_render_samples = args.samples
if args.stamp:
    r.use_stamp = True
    for k in dir(r):
        if k.startswith("use_stamp_") and k not in ("use_stamp_note", "use_stamp_labels"):
            try:
                setattr(r, k, False)
            except (AttributeError, TypeError):
                pass
    r.use_stamp_note = True
    r.stamp_font_size = max(12, int(14 * args.ppm / 108))

    def note(sc, *_):
        fr = FR[min(max(sc.frame_current, 0), len(FR) - 1)]
        sc.render.stamp_note_text = f"{fr['f']:3d}  {fr['t']:.2f} s  {fr['phase']}"

    bpy.app.handlers.frame_change_pre.append(note)

print(f"car_shot: {PX}x{PY} at {args.ppm} px/m ({PX / args.ppm:.2f} x {view_h:.2f} m), middle x {cx}, engine {args.engine}, "
      f"samples {args.samples}, blur {args.blur}, glass flagged off the key: {len(flagged)} objects")
# --- render (nothing with --build-only: a script that runs this one through runpy adds to the scene) ---
names = {v: k for k, v in M["marks"].items() if v is not None}
if args.build_only:
    pass
elif args.clip:
    a, b, step = 0, len(FR) - 1, 1
    if args.range:
        parts = [int(x) for x in args.range.split(":")]
        a, b = parts[0], parts[1]
        step = parts[2] if len(parts) > 2 else 1
    folder = os.path.join(OUT, "clip")
    os.makedirs(folder, exist_ok=True)  # the frames are numbered by motion.json frame
    t0 = time.time()
    for f in range(a, b + 1, step):
        scene.frame_set(f)
        r.filepath = os.path.join(folder, f"{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    n = len(range(a, b + 1, step))
    print(f"car_shot: clip {n} frames in {time.time() - t0:.1f} s ({(time.time() - t0) / n:.2f} s a frame) -> {folder}")
else:
    os.makedirs(OUT, exist_ok=True)
    for tok in args.frames.split(","):
        f = int(tok) if tok.strip().isdigit() else M["marks"][tok.strip()]
        name = names.get(f, "frame")
        scene.frame_set(f)
        r.filepath = os.path.join(OUT, f"{f:03d}-{name}.png")
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"car_shot: frame {f} ({name}, {FR[f]['t']:.2f} s, {FR[f]['phase']}) rendered in {time.time() - t1:.1f} s -> {r.filepath}")
