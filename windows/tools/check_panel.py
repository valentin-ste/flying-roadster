#!/usr/bin/env python3
"""The Windows panel (About inside it) in headless Chromium, as Windows would draw it: every state of design v1 and of
the modes in both themes, with Selawik (Microsoft's open font made to Segoe UI's widths) standing in for Segoe UI, the
content's height against the window's 506 CSS px - with Selawik's own line metrics and again with Segoe UI's Windows
metrics (ascent 2210, descent 514 of 2048: Chromium on Windows takes those for "normal", the Mac takes hhea) - the
pomodoro's widest line not overlapping, a few clicks through the stand-in state, and one sheet next to the design's
shots (design/shots/).

  .venv/bin/python3 windows/tools/check_panel.py [--fonts DIR] [--out DIR]

--fonts: Selawik's TTFs (selawk, selawksb, selawkb, selawkl, selawksl), from
         https://github.com/microsoft/Selawik/releases/download/1.01/Selawik_Release.zip
         (default work/windows-probe/downloads/selawik/extracted)
--out:   the shots and the sheet (default work/windows-probe/round2)
Needs windows/ui/roadster.css and app-icon.svg (windows/build.sh copies them from design/; so does this script).
"""
import argparse
import base64
import pathlib
import shutil

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
UI = ROOT / "windows" / "ui"
SHOTS = ROOT / "design" / "shots"
HOME = pathlib.Path.home()
STATES = ["off", "pomo-ready", "pomo-work", "pomo-break", "pomo-paused", "pomo-widest", "hourly", "hourly-off", "random",
          "mute", "about"]
DESIGN = {  # the design's shot for each state (light), and the dark ones it has
    "off": "02-panel-1-off", "pomo-ready": "03-panel-2-pomodoro-start", "pomo-work": "04-panel-3-pomodoro-work",
    "pomo-break": "05-panel-4-pomodoro-break", "hourly": "06-panel-5-every-hour", "random": "07-panel-6-random",
    "mute": "08-panel-7-mute",
}
DESIGN_DARK = {"off": "10-panel-1-dark", "pomo-work": "09-panel-3-dark"}
# Segoe UI's Windows line metrics on Selawik (whose hhea gives 1.2): what Chromium on Windows takes for "normal"
WIN_METRICS = "ascent-override: 107.91%; descent-override: 25.10%; line-gap-override: 0%;"
FACES = [("selawkl", 300), ("selawksl", 350), ("selawk", 400), ("selawksb", 600), ("selawkb", 700)]


def font_css(fonts: pathlib.Path, extra: str = "") -> str:
    """Selawik as "Segoe UI" (Windows 10 has no Segoe UI Variable: the stack falls to Segoe UI)."""
    out = []
    for name, weight in FACES:
        data = base64.b64encode((fonts / f"{name}.ttf").read_bytes()).decode()
        out.append(f'@font-face {{ font-family: "Segoe UI"; font-weight: {weight}; {extra} '
                   f'src: url(data:font/ttf;base64,{data}) format("truetype"); }}')
    return "\n".join(out)


# the pomodoro's line: the time must end before the buttons; nothing inside the panel wider than it; About not clipped
GEOMETRY = """() => {
  const r = s => { const e = document.querySelector(s); return e ? e.getBoundingClientRect() : null; };
  const time = r('#time'), btns = r('#btns'), card = r('.timer-line');
  const about = document.querySelector('.about-panel');
  const body = document.querySelector('.about-body');
  return {
    overlap: !!(time && btns && time.width && btns.width && time.right > btns.left - 4),
    wide: document.documentElement.scrollWidth > innerWidth,
    btnsOut: !!(btns && card && btns.width && btns.right > card.right),
    aboutClipped: !!(about && !about.hidden && body.scrollHeight > body.clientHeight + 1),
    aboutFoot: about && !about.hidden ? document.querySelector('.about-panel .foot').getBoundingClientRect().bottom : null,
  };
}"""


READY = """async () => {
  await document.fonts.ready;
  await Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })));
}"""


def design_crop(name: str) -> Image.Image:
    """The panel out of a design shot: a 400 px scene at 2x, the panel 8 px from its right, under the 24 px menu bar
    and 6 px, 30 px of desktop under it."""
    im = Image.open(SHOTS / f"{name}.png").convert("RGB")
    return im.crop((96, 60, 784, im.height - 60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", type=pathlib.Path, default=ROOT / "work/windows-probe/downloads/selawik/extracted")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "work/windows-probe/round2")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "design" / "roadster.css", UI / "roadster.css")
    shutil.copy(ROOT / "design" / "icon" / "app-icon-placeholder.svg", UI / "app-icon.svg")
    css = font_css(a.fonts)
    css_win = font_css(a.fonts, WIN_METRICS)
    ours: dict[tuple[str, str], Image.Image] = {}
    problems = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(device_scale_factor=2, viewport={"width": 344, "height": 506})
        for theme, metrics in (("light", "mac"), ("dark", "mac"), ("light", "win")):
            for st in STATES:
                page.goto((UI / "panel.html").as_uri() + f"?state={st}&theme={theme}")
                page.add_style_tag(content=css if metrics == "mac" else css_win)
                page.evaluate(READY)
                lay = page.evaluate("window.__layout()")
                geo = page.evaluate(GEOMETRY)
                foot = geo["aboutFoot"] or page.evaluate("document.querySelector('.foot').getBoundingClientRect().bottom")
                if metrics == "mac":
                    f = a.out / f"panel-{st}-{theme}.png"
                    page.screenshot(path=str(f))
                    ours[(st, theme)] = Image.open(f).convert("RGB")
                bad = [k for k in ("overlap", "wide", "btnsOut", "aboutClipped") if geo[k]]
                content = f"content {lay['content']:.1f} of 506 CSS px" if st != "about" else "About's block not clipped"
                print(f"{st:11s} {theme:5s} {metrics} metrics: {content}, font {lay['font']}, "
                      f"foot bottom {foot:.1f}{'  ' + ', '.join(bad) if bad else ''}")
                if (lay["content"] > 506.01 or abs(foot - (506 - 12)) > 0.5 or bad
                        or lay["font"].strip('"') != "Segoe UI Variable Text"):
                    problems.append(f"{st} {theme} {metrics}: content {lay['content']}, foot {foot}, font {lay['font']}, {bad}")
        # what 0.2.0 had (the font's "normal" line) under Segoe UI's Windows metrics: should come out over 506, as it did
        page.goto((UI / "panel.html").as_uri() + "?state=pomo-ready")
        page.add_style_tag(content=css_win + " body { line-height: normal; }")
        page.evaluate(READY)
        print(f"for comparison, 0.2.0's 'normal' lines with Segoe UI's Windows metrics: content "
              f"{page.evaluate('window.__layout()')['content']:.1f} (Valentin's Windows 10 measured 510)")
        # the font Chromium really drew with (the stack's first face that exists)
        page.goto((UI / "panel.html").as_uri() + "?state=pomo-ready")
        page.add_style_tag(content=css)
        page.evaluate(READY)
        cdp = page.context.new_cdp_session(page)
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        doc = cdp.send("DOM.getDocument")
        for sel in (".brand-name", ".time", ".seg button"):
            node = cdp.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": sel})
            used = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]})["fonts"]
            print(f"drawn with ({sel}): {', '.join(x['familyName'] for x in used)}")
        # clicks through the stand-in: the switches, a mode, a field kept within its range, "from" pushing "to"
        page.click(".head .switch")
        page.fill(".num[data-key=work]", "2.5")
        page.press(".num[data-key=work]", "Enter")
        page.click(".seg button[data-mode=random]")
        page.fill(".num[data-key=from]", "700")
        page.press(".num[data-key=from]", "Enter")
        calls = page.evaluate("window.__calls.filter(c => c[0] !== 'panel_hello')")
        vals = page.evaluate("[...document.querySelectorAll('.num')].map(f => f.dataset.key + '=' + f.value).join(' ')")
        print("calls:", calls)
        print("fields:", vals)
        want = [["panel_set", {"key": "enabled", "value": False}], ["panel_set", {"key": "mode", "value": "random"}],
                ["panel_set", {"key": "from", "value": 600}]]
        if calls != want or "from=600 to=600" not in vals or "work=25" not in vals:
            problems.append(f"clicks: {calls} / {vals}")
        # Start while off switches the app on; then Pause, Resume, Reset send their names and the buttons follow
        page.goto((UI / "panel.html").as_uri() + "?state=pomo-ready")
        page.click(".head .switch")
        page.click("#btns .btn.go")
        on = page.evaluate("document.querySelector('.head .switch').getAttribute('aria-checked')")
        seen = [page.evaluate("[...document.querySelectorAll('#btns button')].map(b => b.textContent).join('+')")]
        for name in ("pause", "resume", "reset"):
            page.click(f"#btns button[data-action={name}]")
            page.wait_for_timeout(50)
            seen.append(page.evaluate("[...document.querySelectorAll('#btns button')].map(b => b.textContent).join('+')"))
        acts = page.evaluate("window.__calls.filter(c => c[0] === 'panel_action').map(c => c[1].name)")
        print("Start while off -> on:", on, "| buttons:", " -> ".join(seen), "| sent:", acts)
        if on != "true" or seen != ["Pause+Reset", "Resume+Reset", "Pause+Reset", "Start"] or acts != ["start", "pause", "resume", "reset"]:
            problems.append(f"pomodoro buttons: on {on}, {seen}, {acts}")
        # About and Back inside the panel; its links go to the app (the browser), the window stays
        page.click("a[data-action=about]")
        shown = page.evaluate("[!document.querySelector('.main-panel').hidden, !document.querySelector('.about-panel').hidden]")
        page.click(".about-body a.brandline")
        page.click("a[data-action=back]")
        back = page.evaluate("[!document.querySelector('.main-panel').hidden, !document.querySelector('.about-panel').hidden]")
        urls = page.evaluate("window.__calls.filter(c => c[0] === 'open_url').map(c => c[1].url)")
        print("About -> [main, about] shown:", shown, "| Back ->", back, "| links sent to the browser:", urls)
        if shown != [False, True] or back != [True, False] or urls != ["https://x.com/valentinste_dev"]:
            problems.append(f"About/Back: {shown} {back} {urls}")
        b.close()

    # the sheet: a column per state; rows: the design, Windows light, Windows dark (+ the design's dark where it has one)
    s = 0.26
    cols = STATES
    tw = int(688 * s)
    rows = ["design v1", "Windows, light", "Windows, dark", "design v1, dark"]
    th = int(1012 * s) + 10
    head, left = 40, 170
    sheet = Image.new("RGB", (left + len(cols) * (tw + 12), head + len(rows) * (th + 8)), "white")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(a.fonts / "selawk.ttf"), 18)
    except OSError:
        font = ImageFont.load_default()
    for i, c in enumerate(cols):
        d.text((left + i * (tw + 12), 10), c, fill="black", font=font)
    for j, r in enumerate(rows):
        d.text((8, head + j * (th + 8) + 8), r, fill="black", font=font)

    def put(im, i, j):
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        sheet.paste(im, (left + i * (tw + 12), head + j * (th + 8)))

    for i, c in enumerate(cols):
        if c == "about":
            put(Image.open(SHOTS / "13-about.png").convert("RGB").crop((70, 120, 810, 860)), i, 0)
        elif c in DESIGN:
            put(design_crop(DESIGN[c]), i, 0)
            if c in DESIGN_DARK:
                put(design_crop(DESIGN_DARK[c]), i, 3)
        put(ours[(c, "light")], i, 1)
        put(ours[(c, "dark")], i, 2)
    out = a.out / "sheet-panel-vs-design.png"
    sheet.save(out)
    print(out, sheet.size)
    print("PROBLEMS:" if problems else "OK", *problems, sep="\n  ")


if __name__ == "__main__":
    main()
