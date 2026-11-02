"""The landing in layers, merged: the smoke layer (the jets and the cloud, the car a holdout, rendered at half
size) scaled up to the full frame and put over the car layer, in linear light, then turned into the PNG Blender
itself writes (view AgX, display sRGB, straight alpha, dithered) — the frame of one full render, made of layers.

Why linear: the layers are half-float EXRs (tools/blender/landing_jets.py --layer car|car-lit|smoke --exr),
premultiplied scene-linear light. Laid over each other as PNGs, after AgX, half-transparent gas over the car
comes out wrong by up to ~40/255 (AgX is not linear); over in linear light and AgX after it is what Cycles does
inside one render. The smoke layer is scaled up premultiplied (no dark fringe: a transparent pixel is black with
alpha 0 and weighs nothing), with --filter (OIIO resize, lanczos3 by default), then clipped to alpha 0..1 and
colour >= 0 (the filter's negative lobes).

Blender's PNG, checked against its own render (out/landing/layers/check/086-steady-car.png): colour =
AgX(rgb / alpha) with straight alpha, +-0.5/255 dither; this script matches it to 0.35/255 on average.

Run with Blender's Python (it has OpenImageIO and OpenColorIO; the project's .venv does not):
  PY=/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13
  $PY tools/landing_merge.py CAR.exr SMOKE.exr OUT.png            one frame
  $PY tools/landing_merge.py --dir out/landing/final [--car car]    every DIR/<car>/NNNN.exr with DIR/smoke/NNNN.exr
                                                                    -> DIR/rgba/NNNN.png (kept if there: --force)
"""
import argparse
import glob
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as ocio

# Blender's own colour config (AgX), next to the Python that runs this: <Blender>/Contents/Resources/5.2/python/bin/
CONFIG = os.path.normpath(os.path.join(os.path.dirname(sys.executable), "..", "..", "datafiles", "colormanagement", "config.ocio"))
_cpu = None


def agx():
    global _cpu
    if _cpu is None:
        cfg = ocio.Config.CreateFromFile(CONFIG)
        t = ocio.DisplayViewTransform(src=ocio.ROLE_SCENE_LINEAR, display="sRGB", view="AgX")
        _cpu = cfg.getProcessor(t).getDefaultCPUProcessor()
    return _cpu


def read(path):
    """HxWx4 float32, as stored (an EXR from Blender: premultiplied scene-linear)."""
    buf = oiio.ImageBuf(path)
    if buf.has_error:
        raise SystemExit(f"landing_merge: {path}: {buf.geterror()}")
    px = buf.get_pixels(oiio.FLOAT)
    if px.shape[2] != 4:
        raise SystemExit(f"landing_merge: {path}: RGBA expected, {px.shape[2]} channels")
    return px


def box(x, r):
    """Mean over a (2r+1)^2 window (edges repeated)."""
    k = 2 * r + 1
    c = np.pad(np.cumsum(np.cumsum(np.pad(x, r, mode="edge"), 0), 1), ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def alpha_denoise(px, r=2, eps=1e-3):
    """The smoke layer's alpha, denoised. Cycles' denoiser cleans the colour, not the alpha, and a volume's alpha is
    a coin toss per sample (the camera ray scatters or passes through: k / samples, checked), so at 8 samples thin
    gas is speckled with holes and opaque dots. A guided filter (He et al.) with the denoised colour's luminance
    as the guide: alpha = a * L + b fitted in every (2r+1)^2 window, so it follows the gas's own edges (the car's
    hole, the jets) instead of blurring them. 8 samples: |alpha - 48-sample alpha| in thin gas 0.081 -> 0.032."""
    L = (px[..., :3] @ np.array([0.2126, 0.7152, 0.0722])).astype(np.float64)
    p = px[..., 3].astype(np.float64)
    mL, mp = box(L, r), box(p, r)
    a = (box(L * p, r) - mL * mp) / (box(L * L, r) - mL * mL + eps)
    b = mp - a * mL
    out = px.copy()
    out[..., 3] = np.clip(box(a, r) * L + box(b, r), 0.0, 1.0)
    return out


def upscale(px, w, h, filt="lanczos3"):
    """A premultiplied RGBA image scaled to w x h (the same picture: pixel i of a half-size frame covers 2i..2i+2)."""
    if px.shape[1] == w and px.shape[0] == h:
        return px
    src = oiio.ImageBuf(oiio.ImageSpec(px.shape[1], px.shape[0], 4, oiio.FLOAT))
    src.set_pixels(oiio.ROI(), np.ascontiguousarray(px))
    dst = oiio.ImageBufAlgo.resize(src, filtername=filt, roi=oiio.ROI(0, w, 0, h, 0, 1, 0, 4))
    out = dst.get_pixels(oiio.FLOAT)
    out[..., 3] = np.clip(out[..., 3], 0.0, 1.0)
    out[..., :3] = np.maximum(out[..., :3], 0.0)
    return out


def over(fg, bg):
    """Premultiplied fg over bg."""
    return fg + (1.0 - fg[..., 3:4]) * bg


def display(px, dither=1.0, seed=0):
    """Premultiplied scene-linear RGBA -> uint8 RGBA as Blender saves a render: AgX of the straight colour, straight alpha."""
    a = np.clip(px[..., 3:4], 0.0, 1.0)
    rgb = np.where(a > 1e-6, px[..., :3] / np.maximum(a, 1e-6), 0.0).astype(np.float32)
    flat = np.ascontiguousarray(rgb.reshape(-1, 3))
    agx().applyRGB(flat)
    rgb = flat.reshape(rgb.shape)
    if dither:
        rgb = rgb + (np.random.default_rng(seed).random(rgb.shape, dtype=np.float32) - 0.5) * (dither / 255.0)
    out = np.concatenate([rgb, a], axis=2)
    return np.clip(np.rint(out * 255.0), 0, 255).astype(np.uint8)


def write_png(rgba8, path):
    spec = oiio.ImageSpec(rgba8.shape[1], rgba8.shape[0], 4, oiio.UINT8)
    spec.attribute("oiio:UnassociatedAlpha", 1)  # the colour is straight already: OIIO must not divide it again
    spec.attribute("png:compressionLevel", 6)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    out = oiio.ImageOutput.create(path)
    out.open(path, spec)
    out.write_image(np.ascontiguousarray(rgba8))
    out.close()


def merge(car, smoke, dst, filt="lanczos3", seed=0, alpha=(2, 1e-3)):
    base = read(car)
    h, w = base.shape[:2]
    top = read(smoke)
    if alpha:
        top = alpha_denoise(top, *alpha)
    top = upscale(top, w, h, filt)
    write_png(display(over(top, base), seed=seed), dst)
    return dst


def _job(t):
    return merge(*t)


def main():
    ap = argparse.ArgumentParser(prog="landing_merge.py")
    ap.add_argument("files", nargs="*", help="CAR.exr SMOKE.exr OUT.png")
    ap.add_argument("--dir", help="a layer folder: <dir>/<car>/NNNN.exr + <dir>/smoke/NNNN.exr -> <dir>/rgba/NNNN.png")
    ap.add_argument("--car", default="car", help="--dir: the car layer's folder (car or car-lit)")
    ap.add_argument("--smoke", default="smoke")
    ap.add_argument("--out", default="rgba")
    ap.add_argument("--filter", default="lanczos3", help="OIIO filter for the smoke layer's upscale")
    ap.add_argument("--alpha", default="2,0.001", help="the smoke alpha's guided filter: radius (px of the layer),eps; 0: off")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--force", action="store_true", help="--dir: redo frames already merged")
    a = ap.parse_args()
    alpha = None if a.alpha.strip() in ("0", "") else (int(a.alpha.split(",")[0]), float(a.alpha.split(",")[1]))
    if a.dir:
        cars = sorted(glob.glob(os.path.join(a.dir, a.car, "[0-9]*.exr")))
        todo = []
        for c in cars:
            n = os.path.basename(c)[:-4]
            s = os.path.join(a.dir, a.smoke, n + ".exr")
            d = os.path.join(a.dir, a.out, n + ".png")
            if not os.path.exists(s):
                print(f"landing_merge: no smoke layer for {n}, skipped")
                continue
            if a.force or not os.path.exists(d):
                todo.append((c, s, d, a.filter, int(n), alpha))
        with ProcessPoolExecutor(a.jobs) as ex:
            for d in ex.map(_job, todo):
                pass
        print(f"landing_merge: {len(todo)} frames merged ({len(cars)} car frames) -> {os.path.join(a.dir, a.out)}")
    elif len(a.files) == 3:
        print("landing_merge:", merge(*a.files, a.filter, alpha=alpha))
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
