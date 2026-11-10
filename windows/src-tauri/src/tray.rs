// The tray icon: Windows gives it a square slot of its small icon size at the taskbar's DPI (16 px at 100%, 20 at 125%,
// 24 at 150%, 32 at 200%) and scales whatever it is handed into it. One 32 px PNG scaled down by Windows made the car a
// blur ~20 x 7 px at 125% (Valentin, 10.11). So every variant comes as PNGs made for each slot (16, 20, 24, 32, 40, 48;
// windows/tools/make_icons.py renders them from design/icon/'s SVGs, the car's edges on whole pixels), and the app
// hands Windows the one for the slot it has now, again when the scale, the monitors or the theme change (events.rs).
//
// Variants (Valentin picks one in a test build: the tray menu's "Icon variant (test)"; the choice is kept in
// settings.json as TrayIcon):
//   tight  A: the silhouette now in the tray (design/icon/roadster-solid.svg, silver, a dark edge), edge to edge
//   tall   B: the same, its body 1.3 times taller and its wheels 1.2 times bigger on the floor line
//   plate  C: the car across a dark rounded plate, as in the app's icon
//   mono   D: B without an edge, white on a dark taskbar and black on a light one, as Windows' own tray icons

use std::sync::Mutex;

use tauri::image::Image;
use tauri::AppHandle;

use crate::{modes, panel, sys};

pub const VARIANTS: [(&str, &str); 4] = [
    ("tight", "A: silhouette, edge to edge"),
    ("tall", "B: taller, bigger wheels"),
    ("plate", "C: on a dark plate"),
    ("mono", "D: white/black like Windows' own"),
];
pub const DEFAULT: &str = "mono"; // Valentin, 10.11: D
const SIZES: [u32; 6] = [16, 20, 24, 32, 40, 48];

macro_rules! icons {
    ($($name:literal),* $(,)?) => { &[$(($name, include_bytes!(concat!("../icons/tray/", $name, ".png")) as &[u8])),*] };
}
static ICONS: &[(&str, &[u8])] = icons!(
    "tight-16", "tight-20", "tight-24", "tight-32", "tight-40", "tight-48",
    "tall-16", "tall-20", "tall-24", "tall-32", "tall-40", "tall-48",
    "plate-16", "plate-20", "plate-24", "plate-32", "plate-40", "plate-48",
    "mono-dark-16", "mono-dark-20", "mono-dark-24", "mono-dark-32", "mono-dark-40", "mono-dark-48",
    "mono-light-16", "mono-light-20", "mono-light-24", "mono-light-32", "mono-light-40", "mono-light-48",
);

static LAST: Mutex<Option<String>> = Mutex::new(None);

pub fn variant(app: &AppHandle) -> String {
    if option_env!("ROADSTER_SELFTEST").is_none() {
        return DEFAULT.into(); // the variants are a test build's; a normal build has D only
    }
    let v = panel::settings(app).tray_icon;
    if VARIANTS.iter().any(|(k, _)| *k == v) { v } else { DEFAULT.into() }
}

/// The PNG for a slot: the one made for that size, else the next bigger (Windows scales it down), else the biggest.
fn pick(v: &str, slot: u32, light: bool) -> (String, &'static [u8]) {
    let size = SIZES.iter().copied().find(|&s| s >= slot).unwrap_or(48);
    let name = if v == "mono" {
        format!("mono-{}-{size}", if light { "light" } else { "dark" })
    } else {
        format!("{v}-{size}")
    };
    let bytes = ICONS.iter().find(|(n, _)| *n == name).map(|(_, b)| *b).unwrap_or(ICONS[0].1);
    (name, bytes)
}

pub fn icon_now(app: &AppHandle) -> Image<'static> {
    let (slot, _) = sys::tray_slot();
    let (_, bytes) = pick(&variant(app), slot, sys::taskbar_light());
    Image::from_bytes(bytes).expect("tray icon PNG")
}

/// Hands the tray the icon for its slot now; true if it changed.
pub fn refresh(app: &AppHandle) -> bool {
    let (slot, dpi) = sys::tray_slot();
    let light = sys::taskbar_light();
    let v = variant(app);
    let (name, bytes) = pick(&v, slot, light);
    let key = format!("{name} for a {slot} px slot at {dpi} dpi, {} taskbar", if light { "light" } else { "dark" });
    {
        let mut last = LAST.lock().unwrap();
        if last.as_deref() == Some(key.as_str()) {
            return false;
        }
        *last = Some(key.clone());
    }
    if let (Some(tray), Ok(img)) = (app.tray_by_id("roadster"), Image::from_bytes(bytes)) {
        let _ = tray.set_icon(Some(img));
    }
    modes::log(format!("tray icon: {key}"));
    true
}

pub fn report_line(app: &AppHandle) -> String {
    let (slot, dpi) = sys::tray_slot();
    format!("tray icon: variant {} ({}); slot {slot} px at {dpi} dpi; {} taskbar; now {}", variant(app),
            VARIANTS.iter().find(|(k, _)| *k == variant(app)).map(|(_, t)| *t).unwrap_or(""),
            if sys::taskbar_light() { "light" } else { "dark" },
            LAST.lock().unwrap().clone().unwrap_or("-".into()))
}
