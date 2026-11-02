"""Frames that blink, found in numbers after a render: a frame clearly unlike both its neighbours while the neighbours
agree with each other, or a stretch of such frames between two jumps with quiet frames around them. Made after the black
windows of 01.11 (Cycles lost the light in the glass of a standing car on one frame, its neighbours fine). Compares the
car's area: the bounding box of its silhouettes (the mask folder next to the frames: clip-mask) or else of the frames'
own alpha, in 16 px tiles; the difference of two frames is their largest tile mean of |a - b| over premultiplied RGB and
alpha, 0..255. Moving frames differ from both neighbours too, but so do the neighbours from each other (twice as much):
only a frame that stands out of quiet neighbours is a suspect. Prints the suspects; changes nothing.

Run (.venv/bin/python3, README):
  tools/frame_blinks.py out/show-b/final/rgba            # the mask from out/show-b/final/clip-mask
  tools/frame_blinks.py out/show-b/draft/clip [--mask DIR] [--ratio 3] [--min 2]
Exit code 0 either way (a list to look at, not a failed render).
"""
import argparse
import glob
import os
import re
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image

TILE = 16


def premult(a):
    a = a.astype(np.float32)
    return np.concatenate([a[..., :3] * a[..., 3:] / 255.0, a[..., 3:]], -1)


def box(alpha_images, margin, shape):
    """The bounding box (y0, y1, x0, x1) of alpha > 8 over the images, grown by margin, in the frames' pixels."""
    h, w = shape
    ys, xs = [], []
    for im in alpha_images:
        a = np.asarray(im)
        sy, sx = h / a.shape[0], w / a.shape[1]
        on = a > 8
        if not on.any():
            continue
        rows, cols = np.flatnonzero(on.any(1)), np.flatnonzero(on.any(0))
        ys += [rows[0] * sy, (rows[-1] + 1) * sy]
        xs += [cols[0] * sx, (cols[-1] + 1) * sx]
    if not ys:
        return None
    return (max(int(min(ys)) - margin, 0), min(int(max(ys)) + margin, h), max(int(min(xs)) - margin, 0), min(int(max(xs)) + margin, w))


def diff(a, b):
    d = np.abs(a - b).mean(-1)
    h, w = (d.shape[0] // TILE) * TILE, (d.shape[1] // TILE) * TILE
    if h == 0 or w == 0:
        return float(d.mean())
    return float(d[:h, :w].reshape(h // TILE, TILE, w // TILE, TILE).mean((1, 3)).max())


def job(args):
    """(D(p, f), D(f, n), D(p, n)) of the frames p, f, n over the box of their silhouettes, or None (no car)."""
    paths, masks = args
    ims = [np.asarray(Image.open(p).convert("RGBA")) for p in paths]  # 8 bit until cropped: a 3024x1964 frame is 24 MB
    shape = ims[0].shape[:2]
    alphas = [Image.open(m).getchannel("A") for m in masks if m and os.path.exists(m)]
    if not alphas:
        alphas = [Image.fromarray(im[..., 3]) for im in ims]
    bx = box(alphas, max(8, shape[1] // 100), shape)
    if bx is None:
        return None
    y0, y1, x0, x1 = bx
    p, f, n = (premult(im[y0:y1, x0:x1]) for im in ims)
    return diff(p, f), diff(f, n), diff(p, n)


def main():
    ap = argparse.ArgumentParser(prog="frame_blinks.py")
    ap.add_argument("frames", help="a folder of NNNN.png frames")
    ap.add_argument("--mask", default=None, help="the car's silhouettes NNNN.png (default: clip-mask next to the frames)")
    ap.add_argument("--ratio", type=float, default=3.0, help="a suspect differs from its neighbours this many times more "
                    "than they differ from each other")
    ap.add_argument("--min", type=float, default=2.0, help="and by at least this much (the largest 16 px tile mean, 0..255)")
    a = ap.parse_args()
    paths = sorted(p for p in glob.glob(os.path.join(a.frames, "*.png")) if re.fullmatch(r"\d+\.png", os.path.basename(p)))
    if len(paths) < 3:
        print(f"frame_blinks: {len(paths)} frames in {a.frames}, nothing to compare")
        return
    mdir = a.mask or os.path.join(os.path.dirname(os.path.normpath(a.frames)), "clip-mask")
    mask_of = (lambda p: os.path.join(mdir, os.path.basename(p))) if os.path.isdir(mdir) else (lambda p: None)
    num = [int(os.path.basename(p)[:-4]) for p in paths]
    jobs = [(paths[k - 1:k + 2], [mask_of(p) for p in paths[k - 1:k + 2]]) for k in range(1, len(paths) - 1)]
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(job, jobs, chunksize=4))
    # j[k]: frame k-1 against frame k; s[k]: frame k-1 against frame k+1
    j, s = [None] * len(paths), [None] * len(paths)
    for k, r in enumerate(res, start=1):
        if r is not None:
            j[k], j[k + 1], s[k] = r[0], r[1], r[2]
    blinks, jumps = [], []
    for k in range(1, len(paths) - 1):
        if s[k] is not None and min(j[k], j[k + 1]) > max(a.min, a.ratio * s[k]):
            blinks.append(k)
    for k in range(2, len(paths) - 1):  # a jump between two quiet steps: the edge of a stretch unlike its surroundings
        if None in (j[k - 1], j[k], j[k + 1]):
            continue
        if j[k] > max(a.min, a.ratio * max(j[k - 1], j[k + 1])):
            jumps.append(k)
    print(f"frame_blinks: {len(paths)} frames {num[0]}-{num[-1]} in {a.frames}, the car's area "
          f"({'silhouettes ' + mdir if os.path.isdir(mdir) else 'the frames alpha'}), {TILE} px tiles, ratio {a.ratio:g}, "
          f"min {a.min:g}: {len(blinks)} blinking frame(s), {len(jumps)} jump(s)")
    for k in blinks:
        print(f"  frame {num[k]}: unlike both neighbours ({num[k - 1]}: {j[k]:.1f}, {num[k + 1]}: {j[k + 1]:.1f}), "
              f"which differ by {s[k]:.1f}")
    k = 0
    while k < len(jumps):  # two jumps close together: the stretch between them; a lone jump: printed as it is
        x = jumps[k]
        y = jumps[k + 1] if k + 1 < len(jumps) else None
        if y is not None and y - x <= 60:
            print(f"  frames {num[x]}-{num[y - 1]}: a stretch unlike the frames around it (a jump in {j[x]:.1f}, out {j[y]:.1f})")
            k += 2
        else:
            print(f"  frame {num[x - 1]} -> {num[x]}: a jump of {j[x]:.1f} between quiet steps")
            k += 1
    if not blinks and not jumps:
        print("  none")


if __name__ == "__main__":
    main()
