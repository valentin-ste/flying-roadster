#!/usr/bin/env python3
"""Icons of the Windows app, rendered from the Mac app's SVGs in design/icon/ with headless Chromium.

  .venv/bin/python3 windows/tools/make_icons.py [--sheet PNG]

-> windows/src-tauri/icons/
   icon.ico (16-256 px), 32x32.png, 128x128.png   the program's icon: design/icon/app-icon-placeholder.svg, as on the Mac
   tray/<variant>-<size>.png                      the tray icon's variants, one PNG per slot Windows gives it (16, 20,
                                                  24, 32, 40, 48 px: 100% to 300%), each drawn for that size
-> the sheet (default work/windows-probe/round2/tray-icons-sheet.png): every variant at its natural
   size on Windows' light and dark taskbars, the 20 px ones (125%, Valentin's) also 6 times bigger, next to 0.2.0's icon

The car is design/icon/roadster-solid.svg (the Mac's menu bar silhouette: the render's body 1.35 times taller, wheels
1.1 times bigger), no new drawing:
   tight  A: as in 0.2.0's tray (silver, a dark edge) but edge to edge of the slot (0.2.0 left a margin round it)
   tall   B: the same, its body a further 1.3 times taller about the floor line, the wheels 1.2 times bigger on it
   plate  C: B in silver across a dark rounded plate (the app icon's colours), so the slot reads as a solid square
   mono   D: B without an edge, white on a dark taskbar, black on a light one, as Windows' own tray icons
Each size is drawn on its own grid: the car's ends and its floor line fall on whole pixels.
"""
import argparse
import io
import pathlib
import re

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
ICON = ROOT / "design" / "icon"
OUT = ROOT / "windows" / "src-tauri" / "icons"
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
TRAY_SIZES = [16, 20, 24, 32, 40, 48]
VARIANTS = ["tight", "tall", "plate", "mono"]
HOME = pathlib.Path.home()
SILVER, EDGE = "#c9cdd3", "#1c1c1c"
# taskbars: Windows 10 dark / light, Windows 11 dark / light (their usual colours without transparency)
BARS = [("Windows 10 dark", (16, 16, 16)), ("Windows 11 dark", (32, 32, 32)),
        ("Windows 10 light", (238, 238, 238)), ("Windows 11 light", (243, 243, 243))]


def car():
    """The silhouette's body (points) and wheels (cx, cy, r) in its 32 x 18 box; the floor line is the wheels' bottom."""
    src = (ICON / "roadster-solid.svg").read_text()
    d = re.search(r'<path d="([^"]+)"', src).group(1)
    pts = [tuple(map(float, p.split())) for p in re.findall(r"[\d.]+ [\d.]+", d)]
    wheels = [tuple(float(c.group(i)) for i in (1, 2, 3))
              for c in re.finditer(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', src)]
    return pts, wheels


def shape(tall: bool):
    pts, wheels = car()
    floor = max(cy + r for _, cy, r in wheels)
    if tall:
        pts = [(x, floor - (floor - y) * 1.3) for x, y in pts]
        wheels = [(cx, floor - r * 1.2, r * 1.2) for cx, _, r in wheels]
    xs = [p[0] for p in pts]
    top = min(min(p[1] for p in pts), min(cy - r for _, cy, r in wheels))
    return pts, wheels, min(xs), max(xs), top, floor


def car_svg(size: int, tall: bool, fill: str, edge: float, edge_colour: str, margin: float, plate: bool = False) -> str:
    """The car across the slot: its ends `margin` px in (plus the edge), its floor line on a whole pixel, centred."""
    pts, wheels, x0, x1, top, floor = shape(tall)
    k = (size - 2 * margin - 2 * edge) / (x1 - x0)
    h = (floor - top) * k
    floor_px = round((size + h) / 2)
    tx = margin + edge - x0 * k
    ty = floor_px - floor * k
    d = "M" + " L".join(f"{tx + x * k:.3f} {ty + y * k:.3f}" for x, y in pts) + " Z"
    discs = "".join(f'<circle cx="{tx + cx * k:.3f}" cy="{ty + cy * k:.3f}" r="{r * k:.3f}"/>' for cx, cy, r in wheels)
    body = ""
    if plate:
        rad = size * 0.22
        body += (f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4A505A"/>'
                 f'<stop offset="1" stop-color="#16181C"/></linearGradient></defs>'
                 f'<rect x="0" y="0" width="{size}" height="{size}" rx="{rad:.2f}" fill="url(#g)"/>'
                 f'<rect x="0.5" y="0.5" width="{size - 1}" height="{size - 1}" rx="{rad - 0.5:.2f}" fill="none" '
                 f'stroke="rgba(255,255,255,0.22)" stroke-width="1"/>')
    if edge > 0:
        body += (f'<g fill="{edge_colour}" stroke="{edge_colour}" stroke-width="{2 * edge}" stroke-linejoin="round">'
                 f'<path d="{d}"/>{discs}</g>')
    body += f'<g fill="{fill}"><path d="{d}"/>{discs}</g>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">{body}</svg>'


def tray_svgs(size: int) -> dict[str, str]:
    edge = 1.0 if size <= 32 else 2.0
    return {
        "tight": car_svg(size, False, SILVER, edge, EDGE, 0),
        "tall": car_svg(size, True, SILVER, edge, EDGE, 0),
        "plate": car_svg(size, True, "#E6E8EB", 0, "", max(1.0, round(size / 12)), plate=True),
        "mono-dark": car_svg(size, True, "#FFFFFF", 0, "", 0),
        "mono-light": car_svg(size, True, "#000000", 0, "", 0),
    }


def render(page, svg: str, size: int) -> Image.Image:
    svg = re.sub(r'width="[\d.]+" height="[\d.]+"', f'width="{size}" height="{size}"', svg, count=1)
    page.set_content(f"<html><body style='margin:0;background:transparent'>{svg}</body></html>")
    png = page.locator("svg").first.screenshot(omit_background=True)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def sheet(icons: dict[str, Image.Image], path: pathlib.Path):
    """Rows: 0.2.0's icon and the variants; columns: the taskbars; in each cell the six sizes at natural size and the
    20 px one six times bigger (nearest neighbour: the pixels as they are)."""
    old = Image.open(OUT / "tray-32.png").convert("RGBA")
    names = ["0.2.0"] + VARIANTS
    labels = {"0.2.0": "0.2.0 (one 32 px PNG,", "tight": "A tight", "tall": "B tall", "plate": "C plate", "mono": "D mono"}
    cell_w, cell_h, left, head = 360, 150, 190, 40
    im = Image.new("RGB", (left + cell_w * len(BARS), head + cell_h * len(names)), "white")
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(str(ROOT / "work/windows-probe/downloads/selawik/extracted/selawk.ttf"), 15)
    except OSError:
        font = ImageFont.load_default()
    for j, (bar, _) in enumerate(BARS):
        dr.text((left + j * cell_w + 8, 12), bar, fill="black", font=font)
    for i, n in enumerate(names):
        y0 = head + i * cell_h
        dr.text((8, y0 + 8), labels[n], fill="black", font=font)
        if n == "0.2.0":
            dr.text((8, y0 + 28), "Windows scales it)", fill="black", font=font)
        for j, (bar, rgb) in enumerate(BARS):
            x0 = left + j * cell_w
            dr.rectangle((x0, y0, x0 + cell_w - 6, y0 + cell_h - 6), fill=rgb)
            light = sum(rgb) > 380
            x = x0 + 10
            for s in TRAY_SIZES:
                if n == "0.2.0":
                    ic = old.resize((s, s), Image.BOX)
                elif n == "mono":
                    ic = icons[f"mono-{'light' if light else 'dark'}-{s}"]
                else:
                    ic = icons[f"{n}-{s}"]
                im.paste(ic, (x, y0 + 12 + (48 - s) // 2), ic)
                x += s + 8
            big = (old.resize((20, 20), Image.BOX) if n == "0.2.0"
                   else icons[f"mono-{'light' if light else 'dark'}-20" if n == "mono" else f"{n}-20"])
            big = big.resize((120, 120), Image.NEAREST)
            im.paste(big, (x0 + cell_w - 136, y0 + 12), big)
            grey = (150, 150, 150)
            dr.text((x0 + 10, y0 + 70), "16 20 24 32 40 48 px", fill=grey, font=font)
            dr.text((x0 + 10, y0 + 92), "right: 20 px (125%) x6", fill=grey, font=font)
    im.save(path)
    return im.size


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", type=pathlib.Path, default=ROOT / "work/windows-probe/round2/tray-icons-sheet.png")
    a = ap.parse_args()
    (OUT / "tray").mkdir(parents=True, exist_ok=True)
    a.sheet.parent.mkdir(parents=True, exist_ok=True)
    app_svg = (ICON / "app-icon-placeholder.svg").read_text()
    icons: dict[str, Image.Image] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=1)
        imgs = {s: render(page, app_svg, s) for s in ICO_SIZES}
        for s in TRAY_SIZES:
            for name, svg in tray_svgs(s).items():
                icons[f"{name}-{s}"] = render(page, svg, s)
        browser.close()
    imgs[256].save(OUT / "icon.ico", sizes=[(s, s) for s in ICO_SIZES],
                   append_images=[imgs[s] for s in ICO_SIZES if s != 256])
    imgs[32].save(OUT / "32x32.png")
    imgs[128].save(OUT / "128x128.png")
    for name, im in icons.items():
        im.save(OUT / "tray" / f"{name}.png", optimize=True)
    for name in ("tight-20", "tall-20", "plate-20", "mono-dark-20"):
        bbox = icons[name].getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
        print(f"{name}: covers {bbox[2] - bbox[0]} x {bbox[3] - bbox[1]} px of 20 x 20")
    print("tray PNGs:", len(icons), "->", OUT / "tray")
    print("sheet:", a.sheet, sheet(icons, a.sheet))


if __name__ == "__main__":
    main()
