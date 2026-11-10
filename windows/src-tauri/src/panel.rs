// The panel (ui/panel.html, design v1: design/panel.html + roadster.css), About inside it (design/about.html; Back
// returns), every state of the modes as the schedule (modes.rs) has it.
//
// No window waits hidden: WebView2 costs ~230 MB and a little CPU while it lives (0.2.0's report), so the panel's
// window is made when it is asked for (a left click on the tray icon, a second launch, the first run) and destroyed
// when it closes; with no show on, WebView2 then exits (Valentin, 10.11). The window is made on a thread of its own:
// WebView2 finishes making a window through the main thread's message loop, and a window made ON the main thread (a
// synchronous command, an event handler) waits for that loop forever - 0.2.0's About froze the whole app so (see
// crate::make_off_main). The page gets the state (render), answers (panel_ready), and only then the window appears
// over the icon, at the edge of the work area on the taskbar's side (place.rs), 344 x 506 CSS px at the monitor's
// scale. It closes on a click outside it, on losing the focus, on Esc and on a second click on the icon; a number being
// typed is kept (the page commits it and says bye), then the window goes.
//
// The settings (settings.rs) live here, behind one lock; the panel's commands change them, the schedule follows
// (modes::apply), and they return the new state. Lock order: the schedule's lock may take this one (Start while off
// switches the app on), never the other way round.

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_autostart::ManagerExt;

use crate::place::{self, Rect};
use crate::settings::{Settings, MODES};
use crate::{modes, show, sys};

static APP: OnceLock<AppHandle> = OnceLock::new();
const ABOUT_LINKS: [&str; 4] = [
    "https://x.com/valentinste_dev",
    "https://sketchfab.com/3d-models/tesla-roadster-2020-1fbf29e297bd4a17ac39a00a378441d8",
    "https://sketchfab.com/metarex.4d",
    "https://creativecommons.org/licenses/by/4.0/",
];

#[derive(Clone, Copy)]
pub enum Anchor {
    Icon(Rect), // the click's icon rectangle
    Tray,       // ask the tray icon where it is (a second launch, the first run)
}

struct Request {
    seq: u64,
    at: Instant,
    anchor: Anchor,
    why: &'static str,
    cold: bool,              // WebView2 was not running at the click (its processes gone)
    made_ms: Option<f64>,    // the window made (hidden), from the click
}

struct Open {
    why: &'static str,
    cold: bool,
    made_ms: Option<f64>,
    ready_ms: f64,
    shown_ms: f64,
    painted_ms: Option<f64>,
    at: Instant,
    seq: u64,
    focused: bool,
}

pub struct Panel {
    s: Mutex<State>,
}

struct State {
    settings: Settings,
    file: Option<PathBuf>,
    seq: u64,
    pending: Option<Request>,
    label: Option<String>,             // the panel's window now (panel-<seq>), hidden until the page is ready
    unload_after_show: Option<String>, // closed while a show's window was being made: goes once it is made
    visible: bool,
    closed_at: Option<Instant>,
    rect: Option<Rect>,
    opens: Vec<Open>,
    fonts: Value,
    layout: Value,
    placement: String,
}

impl Panel {
    pub fn new(file: Option<PathBuf>) -> Panel {
        let settings = Settings::load(&file);
        Panel {
            s: Mutex::new(State {
                settings,
                file,
                seq: 0,
                pending: None,
                label: None,
                unload_after_show: None,
                visible: false,
                closed_at: None,
                rect: None,
                opens: Vec::new(),
                fonts: Value::Null,
                layout: Value::Null,
                placement: String::new(),
            }),
        }
    }
}

fn st(app: &AppHandle) -> std::sync::MutexGuard<'_, State> {
    app.state::<Panel>().inner().s.lock().unwrap()
}

pub fn settings(app: &AppHandle) -> Settings {
    st(app).settings.clone()
}

pub fn update(app: &AppHandle, f: impl FnOnce(&mut Settings)) {
    let mut g = st(app);
    f(&mut g.settings);
    g.settings.clean();
    g.settings.save(&g.file);
}

pub fn muted(app: &AppHandle) -> bool {
    st(app).settings.muted
}

fn ms(since: Instant) -> f64 {
    since.elapsed().as_secs_f64() * 1000.0
}

pub fn init(app: &AppHandle) {
    let _ = APP.set(app.clone());
}

/// The panel's window, hidden, its page loading: on a thread of its own (never the main thread: see the top).
fn create(app: &AppHandle, seq: u64) -> Result<(), String> {
    crate::assert_off_main("the panel's window")?;
    let label = format!("panel-{seq}");
    let dark = sys::apps_dark();
    let bg = if dark { tauri::window::Color(0, 0, 0, 255) } else { tauri::window::Color(0xF2, 0xF2, 0xF7, 255) };
    let win = WebviewWindowBuilder::new(app, &label, WebviewUrl::App("panel.html".into()))
        .title("Roadster")
        .inner_size(place::PANEL_CSS.0, place::PANEL_CSS.1)
        .decorations(false)
        .shadow(true) // Windows 11: the system's rounded corners and shadow; Windows 10: a thin border and the shadow
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .skip_taskbar(true)
        .always_on_top(true)
        .visible(false)
        .focused(false)
        .background_color(bg)
        .additional_browser_args(show::BROWSER_ARGS) // the shows' arguments: both share one WebView2 browser process
        .on_navigation(local_only)
        .build()
        .map_err(|e| format!("the panel's window: {e}"))?;
    if let Ok(h) = win.hwnd() {
        sys::make_flyout(h.0 as isize);
    }
    let a = app.clone();
    win.on_window_event(move |e| {
        if let WindowEvent::Focused(false) = e {
            close(&a);
        }
    });
    let mut g = st(app);
    if let Some(r) = g.pending.as_mut().filter(|r| r.seq == seq) {
        r.made_ms = Some(ms(r.at));
    }
    Ok(())
}

/// The app's own pages only (http://tauri.localhost on Windows); links go to the browser (open_url).
fn local_only(url: &tauri::Url) -> bool {
    matches!(url.host_str(), Some("tauri.localhost") | Some("localhost")) || url.scheme() == "tauri"
}

fn state_json(app: &AppHandle, s: &Settings) -> Value {
    json!({
        "enabled": s.enabled,
        "mode": s.mode,
        "muted": s.muted,
        "work": s.pomodoro_work_minutes,
        "break": s.pomodoro_break_minutes,
        "from": s.random_from_minutes,
        "to": s.random_to_minutes,
        "login": app.autolaunch().is_enabled().unwrap_or(false),
        "dark": sys::apps_dark(),
        "nextHour": sys::next_hour_text(),
        "pomo": pomo_json(),
        "version": env!("CARGO_PKG_VERSION"),
    })
}

/// The pomodoro as the schedule has it: the page counts `left` down only while `ticking` (its end is set).
fn pomo_json() -> Value {
    match modes::view() {
        Some(v) => json!({
            "run": v.pomodoro.run.key(),
            "phase": v.pomodoro.phase.key(),
            "left": v.left,
            "ticking": v.pomodoro.deadline.is_some(),
        }),
        None => json!({ "run": "ready", "phase": "work", "left": 0, "ticking": false }),
    }
}

/// A left click on the tray icon, a second launch, the first run.
pub fn open(app: &AppHandle, anchor: Anchor, why: &'static str) {
    let mut g = st(app);
    if g.visible {
        if matches!(anchor, Anchor::Icon(_)) {
            drop(g);
            close(app); // a second click on the icon
        } else if let Some(Ok(h)) = g.label.as_ref().and_then(|l| app.get_webview_window(l)).map(|w| w.hwnd()) {
            sys::panel_show(h.0 as isize);
        }
        return;
    }
    // the click on the icon that has just closed the panel (by taking its focus) must not open it again
    if matches!(anchor, Anchor::Icon(_)) && g.closed_at.is_some_and(|t| t.elapsed().as_millis() < 300) {
        return;
    }
    // a window being made: it comes (a stuck one is given up after 8 s)
    if g.pending.as_ref().is_some_and(|r| r.at.elapsed().as_secs() < 8) {
        return;
    }
    g.seq += 1;
    let seq = g.seq;
    let cold = sys::tree_count() <= 1;
    g.pending = Some(Request { seq, at: Instant::now(), anchor, why, cold, made_ms: None });
    let old = g.label.replace(format!("panel-{seq}"));
    drop(g);
    if let Some(old) = old {
        unload(app, old);
    }
    let a = app.clone();
    std::thread::spawn(move || {
        if let Err(e) = create(&a, seq) {
            modes::log(format!("panel: {e}"));
            let mut g = st(&a);
            if g.pending.as_ref().is_some_and(|r| r.seq == seq) {
                g.pending = None;
            }
        }
    });
}

fn current(app: &AppHandle) -> Option<WebviewWindow> {
    let label = st(app).label.clone()?;
    app.get_webview_window(&label)
}

fn send_state(app: &AppHandle, seq: u64) {
    let s = settings(app);
    let state = state_json(app, &s);
    if let Some(w) = current(app) {
        let _ = w.eval(format!("window.render({state}, {seq})"));
    }
}

/// The schedule changed (a moment came, an event, a button): the open panel shows it.
pub fn refresh(app: &AppHandle) {
    if !st(app).visible {
        return;
    }
    let state = state_json(app, &settings(app));
    if let Some(w) = current(app) {
        let _ = w.eval(format!("window.render && window.render({state})"));
    }
}

/// Where the panel goes now: over the icon, or over the tray's end of the taskbar.
fn placement(app: &AppHandle, anchor: Anchor) -> Option<(Rect, String)> {
    let icon = match anchor {
        Anchor::Icon(r) => Some(r),
        Anchor::Tray => app.tray_by_id("roadster").and_then(|t| t.rect().ok().flatten()).map(|r| {
            let p = r.position.to_physical::<i32>(1.0);
            let s = r.size.to_physical::<u32>(1.0);
            Rect { x: p.x, y: p.y, w: s.width, h: s.height }
        }),
    };
    let tray = sys::notify_area();
    let centre = |r: Rect| (r.x + r.w as i32 / 2, r.y + r.h as i32 / 2);
    let point = icon.or(tray).map(centre);
    let monitors = app.available_monitors().unwrap_or_default();
    let inside = |m: &tauri::Monitor, (x, y): (i32, i32)| {
        let (p, s) = (m.position(), m.size());
        x >= p.x && y >= p.y && x < p.x + s.width as i32 && y < p.y + s.height as i32
    };
    let mon = point
        .and_then(|pt| monitors.iter().find(|m| inside(m, pt)).cloned())
        .or_else(|| app.primary_monitor().ok().flatten())?;
    let scale = mon.scale_factor();
    let (p, s, wa) = (mon.position(), mon.size(), mon.work_area());
    let mrect = Rect { x: p.x, y: p.y, w: s.width, h: s.height };
    let work = Rect { x: wa.position.x, y: wa.position.y, w: wa.size.width, h: wa.size.height };
    let (w, h) = place::panel_size(scale);
    let win11 = sys::windows_build() >= 22000;
    let gap = if win11 { (12.0 * scale).round() as i32 } else { 0 };
    // the icon's own centre; if Windows hid it under the ^ arrow, panel_rect drops it and the tray's end is used
    let anchor_pt = icon.map(centre).or(tray.map(|r| (r.x + r.w as i32, r.y + r.h as i32 / 2)));
    let (r, edge) = place::panel_rect(mrect, work, anchor_pt, w, h, gap);
    let text = format!(
        "monitor {}x{} at ({}, {}), scale {:.0}%, work area {}x{} at ({}, {}); icon {}; tray area {}; taskbar {:?}; \
         gap {gap} px ({}); panel {}x{} px at ({}, {})",
        s.width, s.height, p.x, p.y, scale * 100.0, wa.size.width, wa.size.height, wa.position.x, wa.position.y,
        icon.map(|r| format!("{}x{} at ({}, {})", r.w, r.h, r.x, r.y)).unwrap_or("unknown".into()),
        tray.map(|r| format!("{}x{} at ({}, {})", r.w, r.h, r.x, r.y)).unwrap_or("unknown".into()),
        edge, if win11 { "Windows 11" } else { "Windows 10" }, r.w, r.h, r.x, r.y
    );
    Some((r, text))
}

/// The page has the state: place the window, show it, take the focus, watch for clicks outside.
#[tauri::command]
pub fn panel_ready(app: AppHandle, seq: u64) {
    let req = {
        let mut g = st(&app);
        match g.pending.take() {
            Some(r) if r.seq == seq => r,
            other => {
                g.pending = other;
                return;
            }
        }
    };
    let ready_ms = ms(req.at);
    let Some(win) = current(&app) else { return };
    let Ok(h) = win.hwnd().map(|h| h.0 as isize) else { return };
    let Some((rect, text)) = placement(&app, req.anchor) else { return };
    sys::make_flyout(h); // again (idempotent): the page may answer before create() got to it
    // twice: moving onto a monitor of another scale makes Windows resize the window for it once
    for _ in 0..2 {
        let _ = sys::place_client(h, rect);
    }
    let focused = sys::panel_show(h);
    sys::watch_clicks(on_click);
    let shown_ms = ms(req.at);
    {
        let mut g = st(&app);
        g.visible = true;
        g.rect = sys::client_rect(h).or(Some(rect));
        g.placement = text;
        g.opens.push(Open {
            why: req.why,
            cold: req.cold,
            made_ms: req.made_ms,
            ready_ms,
            shown_ms,
            painted_ms: None,
            at: req.at,
            seq,
            focused,
        });
        if g.opens.len() > 12 {
            g.opens.remove(1); // keep the first one
        }
    }
    let _ = win.eval(format!("window.painted && window.painted({seq})"));
}

/// The first frame after the window appeared (requestAnimationFrame), with the page's own measurements.
#[tauri::command]
pub fn panel_painted(app: AppHandle, seq: u64, layout: Value) {
    let mut g = st(&app);
    g.layout = layout;
    if let Some(o) = g.opens.iter_mut().rev().find(|o| o.seq == seq) {
        o.painted_ms = Some(ms(o.at));
    }
}

/// The page is loaded: it says which fonts Windows has; it gets the state.
#[tauri::command]
pub fn panel_hello(app: AppHandle, webview_window: WebviewWindow, fonts: Value) {
    let pending = {
        let mut g = st(&app);
        if g.label.as_deref() != Some(webview_window.label()) {
            return;
        }
        g.fonts = fonts;
        g.pending.as_ref().map(|r| r.seq)
    };
    if let Some(seq) = pending {
        send_state(&app, seq);
    }
}

fn on_click(x: i32, y: i32) {
    let Some(app) = APP.get() else { return };
    let outside = {
        let g = st(app);
        g.visible && g.rect.is_some_and(|r| !(x >= r.x && y >= r.y && x < r.x + r.w as i32 && y < r.y + r.h as i32))
    };
    if outside {
        let a = app.clone();
        let _ = app.run_on_main_thread(move || close(&a));
    }
}

pub fn close(app: &AppHandle) {
    let label = {
        let mut g = st(app);
        if !g.visible {
            return;
        }
        g.visible = false;
        g.closed_at = Some(Instant::now());
        g.label.clone()
    };
    sys::unwatch_clicks();
    let Some(label) = label else { return };
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.eval("window.commit && window.commit(true)"); // a number being typed is kept, then the page says bye
        if let Ok(h) = w.hwnd() {
            sys::panel_hide(h.0 as isize);
        }
    }
    // if the page never says bye, the window goes all the same
    let a = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(1500));
        unload(&a, label);
    });
}

/// The page committed a number being typed (close): its window goes.
#[tauri::command]
pub fn panel_bye(app: AppHandle, webview_window: WebviewWindow) {
    unload(&app, webview_window.label().to_string());
}

/// A closed panel's window is destroyed (WebView2 exits when no window is left). Not while a show's window is being
/// made: Play now takes the panel's running WebView2, and the panel's window goes once the show's is made (release).
fn unload(app: &AppHandle, label: String) {
    {
        let mut g = st(app);
        if g.label.as_deref() == Some(label.as_str()) {
            if g.visible || g.pending.is_some() {
                return; // open, or opening, again
            }
            if show::making_window(app) {
                g.unload_after_show = Some(label);
                return;
            }
            g.label = None;
        }
    }
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.destroy();
        show::webview_gone();
    }
}

/// A show's window is made (or could not be): a panel closed meanwhile goes now.
pub fn release(app: &AppHandle) {
    let label = st(app).unload_after_show.take();
    if let Some(l) = label {
        unload(app, l);
    }
}

/// A switch or a field: the new value kept, the new state back to the page.
#[tauri::command]
pub fn panel_set(app: AppHandle, key: String, value: Value) -> Value {
    let b = value.as_bool().unwrap_or(false);
    let n = value.as_u64().unwrap_or(0) as u32;
    match key.as_str() {
        "enabled" => update(&app, |s| s.enabled = b),
        "mode" => {
            if let Some(m) = value.as_str().filter(|m| MODES.contains(m)) {
                update(&app, |s| s.mode = m.to_string());
            }
        }
        "muted" => {
            update(&app, |s| s.muted = b);
            show::set_muted(&app, b);
        }
        "login" => {
            update(&app, |s| s.open_at_login = b);
            let al = app.autolaunch();
            let _ = if b { al.enable() } else { al.disable() };
        }
        "work" => update(&app, |s| s.pomodoro_work_minutes = n),
        "break" => update(&app, |s| s.pomodoro_break_minutes = n),
        // "from" never above "to": the other follows (as on the Mac)
        "from" => update(&app, |s| {
            s.random_from_minutes = n;
            if s.random_to_minutes < n {
                s.random_to_minutes = n;
            }
        }),
        "to" => update(&app, |s| {
            s.random_to_minutes = n;
            if s.random_from_minutes > n {
                s.random_from_minutes = n;
            }
        }),
        _ => {}
    }
    let s = settings(&app);
    if matches!(key.as_str(), "enabled" | "mode" | "work" | "break" | "from" | "to") {
        modes::apply(&s);
    }
    state_json(&app, &settings(&app))
}

/// Buttons. Returns the new state where the panel stays open. About and Back are the page's own (About is inside it).
#[tauri::command]
pub fn panel_action(app: AppHandle, name: String) -> Value {
    match name.as_str() {
        "play" => {
            modes::play_now(&app, "panel"); // first: the show's window is made while the panel's WebView2 still runs
            close(&app);
        }
        "quit" => app.exit(0),
        "close" => close(&app),
        // the pomodoro: Start and Resume while off switch the app on (Valentin, 02.11; the schedule does it)
        "start" | "pause" | "resume" | "reset" => modes::button(&name),
        _ => {}
    }
    state_json(&app, &settings(&app))
}

#[tauri::command]
pub fn open_url(url: String) {
    if ABOUT_LINKS.contains(&url.as_str()) {
        sys::open_url(&url);
    }
}

/// For the self-test's report.
pub fn report_lines(app: &AppHandle) -> Vec<String> {
    let g = st(app);
    let mut o = vec![format!("theme: {} (Windows app mode); fonts: {}", if sys::apps_dark() { "dark" } else { "light" },
                             g.fonts)];
    o.push(format!("settings: {} (mode {}, switch {}, work {} + break {}, random {}-{}, mute {}); Open at login: the \
                    switch {}, Windows' Run value {}",
                   if g.file.as_ref().is_some_and(|f| f.exists()) { "settings.json kept" } else { "no settings.json yet" },
                   g.settings.mode, if g.settings.enabled { "on" } else { "off" }, g.settings.pomodoro_work_minutes,
                   g.settings.pomodoro_break_minutes, g.settings.random_from_minutes, g.settings.random_to_minutes,
                   if g.settings.muted { "on" } else { "off" }, if g.settings.open_at_login { "on" } else { "off" },
                   if app.autolaunch().is_enabled().unwrap_or(false) { "present" } else { "ABSENT" }));
    if !g.layout.is_null() {
        o.push(format!("last open, as the page saw it: {}", g.layout));
    }
    if !g.placement.is_empty() {
        o.push(format!("last place: {}", g.placement));
    }
    o.push(format!("opened since the launch: {} (each makes its window anew; cold = WebView2 was not running)", g.opens.len()));
    if g.opens.is_empty() {
        o.push("open it a few times with a left click before the self-test".into());
    }
    for (i, op) in g.opens.iter().enumerate() {
        o.push(format!(
            "open {} ({}, {}): window made {}, page ready {:.0} ms, window shown {:.0} ms, first frame painted {} after the {}; \
             focus {}",
            i + 1, op.why, if op.cold { "cold" } else { "WebView2 running" },
            op.made_ms.map(|p| format!("{p:.0} ms")).unwrap_or("-".into()), op.ready_ms, op.shown_ms,
            op.painted_ms.map(|p| format!("{p:.0} ms")).unwrap_or("-".into()),
            if op.why == "click" { "click" } else { "request" },
            if op.focused { "taken" } else { "NOT taken (Windows refused: a click outside still closes it)" }
        ));
    }
    let cold: Vec<f64> = g.opens.iter().filter(|o| o.cold).filter_map(|o| o.painted_ms).collect();
    if !cold.is_empty() {
        let max = cold.iter().cloned().fold(0.0, f64::max);
        let min = cold.iter().cloned().fold(f64::MAX, f64::min);
        o.push(format!("cold opens (WebView2 unloaded before): {} of {}, click -> first frame {min:.0}-{max:.0} ms",
                       cold.len(), g.opens.len()));
    } else {
        o.push(format!("cold opens (WebView2 unloaded before): 0 of {}", g.opens.len()));
    }
    o
}
