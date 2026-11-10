#!/usr/bin/env python3
"""The Windows app's show page (windows/ui) in headless Chromium on the Mac: WebView2 is Chromium too, so this checks
the page itself without Windows: the VP9 video decodes with its alpha, the page paints no background, the length,
the self-test's numbers and the pause mask. Without the app the page only keeps its calls (window.__roadster).

  .venv/bin/python3 windows/tools/check_page.py [--scale 1.25] [--monitor 1920x1200] [--ready] [--muted]
  (--ready: a window made in advance: the page loads the video, says 'ready', plays on go(); --muted: the panel's Mute)
"""
import argparse
import functools
import http.server
import io
import json
import pathlib
import threading

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

UI = pathlib.Path(__file__).resolve().parents[1] / "ui"


def show_rect(mw, mh, fw=2016, fh=1310):     # = src-tauri/src/place.rs
    a = fw / fh
    w, h = mw, mw / a
    if h > mh:
        h, w = mh, mh * a
    w, h = int(w + 0.5), int(h + 0.5)            # Rust's round(): halves away from zero
    return int((mw - w) / 2 + 0.5), mh - h, w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.25)
    ap.add_argument("--monitor", default="1920x1200")
    ap.add_argument("--ready", action="store_true")
    ap.add_argument("--muted", action="store_true")
    args = ap.parse_args()
    mw, mh = map(int, args.monitor.split("x"))
    x, y, w, h = show_rect(mw, mh)
    css = (round(w / args.scale), round(h / args.scale))
    print(f"monitor {mw}x{mh} @{args.scale:.0%}: window {w}x{h} px at ({x}, {y}) -> page viewport {css[0]}x{css[1]} CSS px")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(UI))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/index.html?id=1&selftest=1&ready={int(args.ready)}&muted={int(args.muted)}"

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])   # as the app gives WebView2
        page = b.new_page(viewport={"width": css[0], "height": css[1]}, device_scale_factor=args.scale)
        page.goto(url)
        if args.ready:
            page.wait_for_function("(window.__roadster || []).some(c => c[1] && c[1].kind === 'ready')", timeout=20000)
            page.evaluate("window.go()")
        page.wait_for_function("(window.__roadster || []).some(c => c[0] === 'pause_capture')", timeout=40000)
        shot = Image.open(io.BytesIO(page.screenshot(omit_background=True))).convert("RGBA")
        page.wait_for_function("(window.__roadster || []).some(c => c[0] === 'show_done')", timeout=40000)
        calls = page.evaluate("window.__roadster")
        ended = page.evaluate("[document.getElementById('v').currentTime, document.getElementById('v').muted]")
        b.close()
    srv.shutdown()

    names = [c[0] for c in calls]
    print("calls:", " ".join(dict.fromkeys(names)), f"| show_done at media time {ended[0]:.3f} s, muted {ended[1]}")
    cap = next(c[1] for c in calls if c[0] == "pause_capture")
    m = np.frombuffer(cap["mask"].encode(), np.uint8) - ord("0")
    print(f"pause mask at {cap['mediaTime']:.3f} s: {cap['cols']}x{cap['rows']} cells, alpha 0 {np.mean(m == 0):.2%}, "
          f"partial {np.mean(m == 1):.2%}, 255 {np.mean(m == 2):.2%}")
    a = np.asarray(shot)[..., 3]
    ys, xs = np.nonzero(a == 255)
    print(f"page screenshot in the pause {shot.size[0]}x{shot.size[1]} px: alpha 0 {np.mean(a == 0):.2%}, "
          f"255 {np.mean(a == 255):.2%}; opaque box x {xs.min()}-{xs.max()}, y {ys.min()}-{ys.max()}"
          if len(xs) else "page screenshot: nothing opaque")
    done = next(c[1] for c in calls if c[0] == "show_done")
    for k in ("page", "smooth", "sound"):
        for line in done["lines"].get(k, []):
            print(f"  [{k}] {line}")
    print("  errors:", json.dumps(done["errors"]))


if __name__ == "__main__":
    main()
