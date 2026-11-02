"""Show B in Blender (01.11): the video over the desktop, the two clips and their boundary, the jet variants side by side.

The show is cut in two where nothing in the frame moves: motion.json's mark 'cut', two frames before the dash (the car
stands, its springs settled, the jets out, the landing cloud melted: tools/blender/landing_jets.py --list checks all of
it and writes DIR/timeline.json). Clip 1 runs from the drive-in to the cut, clip 2 from the cut to off the screen; the
cut frame is the last of clip 1 and the first of clip 2, and the program holds it pause_s seconds between them
(split.json: a number changed without rendering anything).

Run (.venv/bin/python3, README):
  tools/show_b.py video DIR [--frames clip] [--pause 1] [--name show-b-draft] [--ppm 54]
      DIR/<frames>/NNNN.png (+ the desktop shadow from DIR/clip-mask/NNNN.png) over the wallpaper, 60 frames/s: a
      frame not rendered holds the one before it (the 30/s stretches, the still stretch of the draft), the cut frame
      held --pause s -> out/show-b/NAME.mp4; also DIR/split.json
  tools/show_b.py split DIR --frames rgba,shadow [--pause 1]
      DIR/split.json and DIR/clip1/<layer>/, DIR/clip2/<layer>/: each clip's frames from 0000 (symlinks into DIR/<layer>/)
  tools/show_b.py compare OUT.mp4 --col "label=DIR" --col "label=DIR2" [--fallback DIR] [--range 140:260]
                  [--crop 0.5,9.5,0,9.093] [--slow 2] [--ppm 54]
      the same stretch side by side, cropped to --crop (x from, x to, z from, z to, m), over the wallpaper with the
      shadow (the silhouettes of --fallback), played --slow times slower; a frame missing in a column is taken from
      --fallback (the variants differ only on some frames)
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from desktop import FONT, shadow, wall_at  # noqa: E402

FPS = 60
_WALL = {}


def frames_in(folder):
    return {int(os.path.basename(p)[:4]): p for p in glob.glob(os.path.join(folder, "[0-9][0-9][0-9][0-9].png"))}


def seen(png, mask, ppm):
    """A frame as it is seen: the wallpaper, the desktop shadow, the frame."""
    im = Image.open(png).convert("RGBA")
    if im.size not in _WALL:
        _WALL[im.size] = wall_at(*im.size, ppm).convert("RGBA")
    out = _WALL[im.size].copy()
    if mask and os.path.exists(mask):
        out.alpha_composite(shadow(mask, im.size, ppm))
    out.alpha_composite(im)
    return out


def _wall_job(job):
    png, mask, ppm, dst = job
    seen(png, mask, ppm).convert("RGB").save(dst, quality=93)
    return dst


def timeline(d):
    path = os.path.join(d, "timeline.json")
    if not os.path.exists(path):
        sys.exit(f"show_b: no {path} (landing_jets.py ... --list writes it)")
    with open(path) as fh:
        return json.load(fh)


def write_split(d, tl, pause, frames):
    doc = {
        "format": "roadster-show-split/1",
        "fps": FPS,
        "frames": frames,
        "cut": tl["cut"],
        "clip1": {"first": 0, "last": tl["cut"]},
        "clip2": {"first": tl["cut"], "last": tl["exit"]},
        "pause_s": pause,
        "note": "the cut frame ends clip 1 and starts clip 2; the program holds it pause_s seconds between them",
    }
    with open(os.path.join(d, "split.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
    return doc


def ffmpeg(seq, fps, dst):
    # an odd height (491 px at 54 px/m) loses its top row: the floor is at the bottom edge
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps:g}", "-i", os.path.join(seq, "%05d.jpg"),
                    "-vf", "crop=iw-mod(iw\\,2):ih-mod(ih\\,2):mod(iw\\,2):mod(ih\\,2),format=yuv420p", "-c:v", "libx264",
                    "-crf", "16", "-preset", "slow", "-movflags", "+faststart", dst], check=True)


def link_seq(seq, srcs):
    shutil.rmtree(seq, ignore_errors=True)
    os.makedirs(seq)
    for k, src in enumerate(srcs):
        os.symlink(os.path.relpath(src, seq), os.path.join(seq, f"{k:05d}.jpg"))


def video(a):
    tl = timeline(a.dir)
    have = frames_in(os.path.join(a.dir, a.frames))
    if not have:
        sys.exit(f"show_b: no frames in {os.path.join(a.dir, a.frames)}")
    wall = os.path.join(a.dir, "wall")
    os.makedirs(wall, exist_ok=True)
    masks = os.path.join(a.dir, "clip-mask")
    jobs = [(p, os.path.join(masks, f"{f:04d}.png"), a.ppm, os.path.join(wall, f"{f:04d}.jpg")) for f, p in sorted(have.items())
            if a.force or not os.path.exists(os.path.join(wall, f"{f:04d}.jpg"))]
    with ProcessPoolExecutor(6) as ex:
        list(ex.map(_wall_job, jobs))
    last = tl["exit"]
    srcs, cur = [], None
    for f in range(0, last + 1):
        if f in have:
            cur = f
        if cur is None:
            sys.exit(f"show_b: no frame at or before {f}")
        srcs.append(os.path.join(wall, f"{cur:04d}.jpg"))
        if f == tl["cut"]:
            srcs += [os.path.join(wall, f"{cur:04d}.jpg")] * round(a.pause * FPS)
    held = sum(1 for f in range(last + 1) if f not in have)
    link_seq(os.path.join(wall, "seq"), srcs)
    dst = os.path.join(ROOT, "out", "show-b", f"{a.name}.mp4")
    ffmpeg(os.path.join(wall, "seq"), FPS, dst)
    write_split(a.dir, tl, a.pause, a.frames)
    print(f"show_b: {len(have)} frames rendered, {held} held, the cut {tl['cut']} held {a.pause:g} s, "
          f"{len(srcs) / FPS:.2f} s at {FPS}/s -> {dst}")


def split(a):
    tl = timeline(a.dir)
    layers = a.frames.split(",")
    doc = write_split(a.dir, tl, a.pause, layers)
    for layer in layers:
        have = frames_in(os.path.join(a.dir, layer))
        for name in ("clip1", "clip2"):
            c = doc[name]
            dst = os.path.join(a.dir, name, layer)
            shutil.rmtree(dst, ignore_errors=True)
            os.makedirs(dst)
            missing = [f for f in range(c["first"], c["last"] + 1) if f not in have]
            if missing:
                sys.exit(f"show_b: {name} misses {layer} frames {missing[:5]}...")
            for k, f in enumerate(range(c["first"], c["last"] + 1)):
                os.symlink(os.path.relpath(have[f], dst), os.path.join(dst, f"{k:04d}.png"))
            print(f"show_b: {name} {layer} frames {c['first']}-{c['last']} ({c['last'] - c['first'] + 1}) -> {dst}")
    print(f"show_b: pause {a.pause:g} s at frame {doc['cut']} -> {os.path.join(a.dir, 'split.json')}")


def compare(a):
    cols = []
    for spec in a.col:
        label, _, folder = spec.partition("=")
        cols.append((label, frames_in(os.path.join(folder, "clip"))))
    fb = frames_in(os.path.join(a.fallback, "clip")) if a.fallback else {}
    first, last = (int(v) for v in a.range.split(":"))
    x0, x1, z0, z1 = (float(v) for v in a.crop.split(","))
    font = ImageFont.truetype(FONT, 22)
    out_dir = os.path.splitext(a.out)[0] + "-frames"
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    srcs = []
    gap, k = 6, None
    for f in range(first, last + 1):
        panels = []
        for label, have in cols:
            png = have.get(f) or fb.get(f)
            if png is None:
                break
            mask = os.path.join(a.fallback or os.path.dirname(os.path.dirname(png)), "clip-mask", f"{f:04d}.png")
            im = seen(png, mask, a.ppm)
            h = im.height
            box = (round(x0 * a.ppm), round(h - z1 * a.ppm), round(x1 * a.ppm), round(h - z0 * a.ppm))
            p = im.crop(box).convert("RGB")
            p = p.resize((round(p.width * a.zoom), round(p.height * a.zoom)), Image.LANCZOS)
            d = ImageDraw.Draw(p)
            d.text((12, 10), label, fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
            d.text((12, 38), f"{f / FPS:.3f} s, frame {f}", fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
            panels.append(p)
        if len(panels) != len(cols):
            continue
        sheet = Image.new("RGB", (sum(p.width for p in panels) + gap * (len(panels) - 1), panels[0].height), (0, 0, 0))
        x = 0
        for p in panels:
            sheet.paste(p, (x, 0))
            x += p.width + gap
        k = len(srcs)
        dst = os.path.join(out_dir, f"{k:05d}.jpg")
        sheet.save(dst, quality=92)
        srcs.append(dst)
    if not srcs:
        sys.exit("show_b: nothing to compare")
    link_seq(os.path.join(out_dir, "seq"), srcs)
    ffmpeg(os.path.join(out_dir, "seq"), FPS / a.slow, a.out)
    print(f"show_b: {len(srcs)} frames {first}-{last}, {len(cols)} columns, x{a.slow:g} slower -> {a.out}")


def main():
    ap = argparse.ArgumentParser(prog="show_b.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("video")
    p.add_argument("dir")
    p.add_argument("--frames", default="clip", help="the frames' folder in DIR (the draft: clip; the final: rgba)")
    p.add_argument("--pause", type=float, default=1.0, help="s the cut frame is held (the program's pause)")
    p.add_argument("--name", default="show-b-draft")
    p.add_argument("--ppm", type=float, default=54.0)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("split")
    p.add_argument("dir")
    p.add_argument("--frames", default="rgba,shadow", help="the layers' folders in DIR, comma-separated")
    p.add_argument("--pause", type=float, default=1.0)
    p = sub.add_parser("compare")
    p.add_argument("out")
    p.add_argument("--col", action="append", required=True, help="label=DIR (its frames in DIR/clip), left to right")
    p.add_argument("--fallback", default=None, help="DIR whose frames stand in for missing ones (and give the shadow)")
    p.add_argument("--range", default="140:260")
    p.add_argument("--crop", default="0.5,9.5,0,9.093", help="x from, x to, z from, z to, m")
    p.add_argument("--zoom", type=float, default=1.0)
    p.add_argument("--slow", type=float, default=2.0)
    p.add_argument("--ppm", type=float, default=54.0)
    a = ap.parse_args()
    {"video": video, "split": split, "compare": compare}[a.cmd](a)


if __name__ == "__main__":
    main()
