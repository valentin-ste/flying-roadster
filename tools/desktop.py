"""The desktop around the show: the car's shadow on the desktop and the wallpaper behind the frames.

layers DIR [--ppm 216] [--force] [--jobs 6]
    DIR/rgba/NNNN.png (tools/landing_merge.py: the car and the smoke, transparent) and DIR/clip-mask/NNNN.png (the car's
    silhouette, tools/blender/landing_jets.py --mask) ->
      DIR/shadow/NNNN.png       the desktop shadow alone: black, alpha = the silhouette blurred 14 pt, 16 pt down, 38%
                                (as src/dropshadow.js drew it in the browser) — a layer of its own, so the program could
                                switch it off;
      DIR/rgba-shadow/NNNN.png  the shadow under the car and the smoke, one transparent frame: what the Mac app plays;
      DIR/wall/NNNN.jpg         the same over the wallpaper, only for watching (tools/show_b.py video).
    Frames already there are kept (--force to redo).

The wallpaper is assets/bg/tahoe-day.jpg, a frame of Apple's macOS Tahoe wallpaper that tools/fetch_assets.sh takes
from the Mac it runs on (it is never stored in the repository); without it the frames are watched over plain dark grey.

Run:  .venv/bin/python3 tools/desktop.py layers out/show-b/final-cloud
"""
import argparse
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageFilter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WALLPAPER = os.path.join(ROOT, "assets", "bg", "tahoe-day.jpg")
SW, SH = 3024, 1964  # the screen at 2x, 216 px/m
BG = (32, 32, 35)    # behind the frames when there is no wallpaper
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
SHADOW = dict(sigma=14, dy=16, opacity=0.38)  # pt (108 pt per metre), as src/main.js


def wallpaper(w, h):
    """The bottom of the desktop: the wallpaper 'cover' on 3024x1964, a w x h frame centred on the screen."""
    if not os.path.exists(WALLPAPER):
        return Image.new("RGB", (w, h), BG)
    im = Image.open(WALLPAPER).convert("RGB")
    k = max(SW / im.width, SH / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    x0 = (im.width - SW) // 2 + (SW - w) // 2
    y0 = (im.height - SH) // 2
    return im.crop((x0, y0 + SH - h, x0 + w, y0 + SH))


def wall_at(w, h, ppm):
    """The wallpaper behind a w x h frame at ppm px per metre (the screen is 216 px/m at 2x)."""
    k = 216 / ppm
    return wallpaper(round(w * k), round(h * k)).resize((w, h), Image.LANCZOS) if k != 1 else wallpaper(w, h)


def shadow(mask_png, size, ppm):
    """The desktop shadow of the car: black, alpha = blurred silhouette moved down x opacity."""
    a = Image.open(mask_png).convert("RGBA").getchannel("A")
    pt = ppm / 108
    a = a.filter(ImageFilter.GaussianBlur(SHADOW["sigma"] * pt))
    dy = round(SHADOW["dy"] * pt)  # moved down, not wrapped round: ImageChops.offset put the bottom rows at the top
    moved = Image.new("L", a.size, 0)
    moved.paste(a.crop((0, 0, a.width, a.height - dy)), (0, dy))
    a = moved
    a = a.point(lambda v: round(v * SHADOW["opacity"]))
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    sh.putalpha(a)
    return sh


def compose(render_png, ppm, mask_png=None):
    """A frame over the wallpaper, with the desktop shadow when the silhouette is given."""
    im = Image.open(render_png).convert("RGBA")
    out = wall_at(*im.size, ppm).convert("RGBA")
    if mask_png:
        out.alpha_composite(shadow(mask_png, im.size, ppm))
    out.alpha_composite(im)
    return out.convert("RGB")


_WALL = {}


def layer_frame(job):
    rgba, mask, d, n, ppm = job
    im = Image.open(rgba).convert("RGBA")
    sh = shadow(mask, im.size, ppm)
    sh.save(os.path.join(d, "shadow", n + ".png"), optimize=False, compress_level=6)
    both = sh.copy()
    both.alpha_composite(im)
    both.save(os.path.join(d, "rgba-shadow", n + ".png"), compress_level=6)
    if im.size not in _WALL:
        _WALL[im.size] = wall_at(*im.size, ppm).convert("RGBA")
    w = _WALL[im.size].copy()
    w.alpha_composite(both)
    w.convert("RGB").save(os.path.join(d, "wall", n + ".jpg"), quality=95)
    return n


def layers(d, ppm=216.0, force=False, jobs=6):
    """DIR/shadow, DIR/rgba-shadow and DIR/wall from DIR/rgba and DIR/clip-mask; returns the frames of DIR/rgba."""
    frames = sorted(glob.glob(os.path.join(d, "rgba", "[0-9]*.png")))
    if not frames:
        sys.exit(f"desktop: no frames in {os.path.join(d, 'rgba')}")
    for sub in ("shadow", "rgba-shadow", "wall"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    todo = []
    for f in frames:
        n = os.path.basename(f)[:-4]
        mask = os.path.join(d, "clip-mask", n + ".png")
        if not os.path.exists(mask):
            sys.exit(f"desktop: no silhouette {mask} (landing_jets.py --clip --mask)")
        if force or not os.path.exists(os.path.join(d, "wall", n + ".jpg")):
            todo.append((f, mask, d, n, ppm))
    with ProcessPoolExecutor(jobs) as ex:
        list(ex.map(layer_frame, todo))
    print(f"desktop: {len(todo)} frames -> {d}/shadow, rgba-shadow, wall ({len(frames)} in all)")
    return frames


def main():
    ap = argparse.ArgumentParser(prog="desktop.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("layers", help="the shadow layer, the frames with the shadow, the frames over the wallpaper")
    p.add_argument("dir")
    p.add_argument("--ppm", type=float, default=216.0, help="px per metre of the frames")
    p.add_argument("--force", action="store_true")
    p.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    layers(a.dir, a.ppm, a.force, a.jobs)


if __name__ == "__main__":
    main()
