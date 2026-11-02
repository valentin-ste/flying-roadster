#!/usr/bin/env python3
"""PNGs of the design mock-ups (2x, as on a Retina screen) and of the menu bar icon (@1x, @2x).

  .venv/bin/python3 design/shoot.py            # everything
  .venv/bin/python3 design/shoot.py icons      # only the icon PNGs -> design/icon/png/
  .venv/bin/python3 design/shoot.py shots      # only the mock-ups  -> design/shots/
  .venv/bin/python3 design/shoot.py shots 04 09   # only the shots whose names start so

The pages are plain HTML (roadster.css + mock.js) opened from disk; the icon SVGs come from
design/icon/make_icons.py. If Chromium for Playwright is missing: .venv/bin/python3 -m playwright install chromium
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent

SHOTS = [
    ("01-icons", "icons.html"),
    ("02-panel-1-off", "panel.html?state=off"),
    ("03-panel-2-pomodoro-start", "panel.html?state=pomo-ready"),
    ("04-panel-3-pomodoro-work", "panel.html?state=pomo-work"),
    ("05-panel-4-pomodoro-break", "panel.html?state=pomo-break"),
    ("06-panel-5-every-hour", "panel.html?state=hourly"),
    ("07-panel-6-random", "panel.html?state=random"),
    ("08-panel-7-mute", "panel.html?state=mute"),
    ("09-panel-3-dark", "panel.html?state=pomo-work&theme=dark"),
    ("10-panel-1-dark", "panel.html?state=off&theme=dark"),
    ("11-panel-3-radio", "panel.html?state=pomo-work&mode=radio"),
    ("12-first-run", "first-run.html"),
    ("13-about", "about.html"),
]
ICONS = ["solid", "wheels", "outline"]

READY = """async () => {
  await document.fonts.ready;
  await Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })));
}"""


def shots(browser, only):
    out = HERE / "shots"
    out.mkdir(exist_ok=True)
    page = browser.new_page(device_scale_factor=2, viewport={"width": 1200, "height": 1000})
    for name, url in SHOTS:
        if only and not any(name.startswith(o) for o in only):
            continue
        page.goto((HERE / url.split("?")[0]).as_uri() + ("?" + url.split("?")[1] if "?" in url else ""))
        page.evaluate(READY)
        f = out / f"{name}.png"
        page.locator("#board").screenshot(path=str(f))
        print(f)
    page.close()


def icons(browser):
    out = HERE / "icon" / "png"
    out.mkdir(exist_ok=True)
    for scale, tail in ((1, ""), (2, "@2x")):
        page = browser.new_page(device_scale_factor=scale, viewport={"width": 200, "height": 100})
        for v in ICONS:
            page.goto((HERE / "icon" / f"roadster-{v}.svg").as_uri())
            f = out / f"roadster-{v}{tail}.png"
            page.locator("svg").first.screenshot(path=str(f), omit_background=True)
            print(f)
        page.close()


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        if what in ("all", "icons"):
            icons(browser)
        if what in ("all", "shots"):
            shots(browser, sys.argv[2:])
        browser.close()


if __name__ == "__main__":
    main()
