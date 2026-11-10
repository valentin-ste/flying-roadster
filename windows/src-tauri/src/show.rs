// The show: a transparent, click-through, topmost window without a taskbar button or focus over the primary monitor's
// frame rectangle (place.rs, as on the Mac), the page ui/index.html playing the video once, then the window goes - and
// with it WebView2, when the panel is closed too (Valentin, 10.11: the engine is unloaded between shows).
// The window is Tauri's transparent one (variant A of the probe, accepted 10.11).
//
// Play now makes the window when it is clicked (from the panel: while the panel's WebView2 still runs, so it starts
// warm). A show of the schedule gets its window SHOW_LEAD_S before its moment (modes.rs), hidden, the video loaded, and
// it is shown at the moment; if the moment goes, so does the window (drop_ready). Windows are made on threads of their
// own, never the main thread (crate::assert_off_main).
//
// Over the taskbar: the taskbar is topmost too and comes over the car when it is clicked. The car goes back over it
// on the shell's events (sys::watch_shell_events), not on a timer.
//
// Self-test (test builds only, the tray menu): WebView2's processes gone after the windows closed, memory and CPU idle
// without them, then a show the way the schedule plays one (its window made cold SHOW_LEAD_S before a moment, shown at
// the moment) measured in full; a report on the desktop (Roadster-report.txt) opened in Notepad.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};

use crate::modes::{self, real_now, SHOW_LEAD_S};
use crate::place::{self, Rect};
use crate::{panel, sys, tray};

pub const FRAME_W: u32 = 2016;
pub const FRAME_H: u32 = 1310;
pub const SHOW_S: f64 = 13.741;
// wry's own defaults (it drops them when given arguments) + sound without a click: WebView2 is Chromium, and
// Chromium's autoplay policy refuses play() with sound until the user interacts with the page
pub const BROWSER_ARGS: &str =
    "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required";
const IDLE_S: u64 = 10;

static APP: OnceLock<AppHandle> = OnceLock::new();
/// When the last WebView2 window went (the panel's or a show's): the self-test waits for the processes after it.
static LAST_GONE: Mutex<Option<Instant>> = Mutex::new(None);

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Play,
    Test, // the self-test's show
}

struct Run {
    id: u64,
    kind: Kind,
    clicked: Instant,
    label: String,
    started: Option<Instant>, // the window shown (and, for a ready window, told to play)
    ready_window: bool,       // made in advance, hidden, waiting for go()
    ready: bool,              // the page has the video and waits
    made: bool,               // the window exists (or could not be made)
    made_ms: Option<f64>,     // made, from the claim
    ready_ms: Option<f64>,    // the page ready (the video loaded), from the claim
    procs_at_claim: usize,    // the app's processes when it began (1: WebView2 was not running: a cold start)
    planned: Option<f64>,     // a show of the schedule: its moment (real time)
    shown: bool,
    hwnd: isize,
    monitor: Vec<String>,
    rect: Option<Rect>,
    before: Option<Result<Vec<u8>, String>>,
    first_frame: Option<(f64, f64)>,
    first_frame_at: Option<Instant>,
    first_frame_real: Option<f64>,
    transparency: Vec<String>,
    verdict: String,
    taskbar_at_pause: Option<bool>,
    cpu0: Option<sys::Cpu>,
    shell_events: u32,
    raises: Vec<(Instant, u32)>,
    idle: Vec<String>,
    events: Vec<String>,
}

#[derive(Default)]
pub struct Shows {
    run: Mutex<Option<Run>>,
    next: AtomicU64,
    testing: AtomicBool,
    report: Mutex<Option<String>>,
}

pub fn init(app: &AppHandle) {
    let _ = APP.set(app.clone());
}

fn ms(since: Instant) -> f64 {
    since.elapsed().as_secs_f64() * 1000.0
}

fn with_run<T>(app: &AppHandle, id: u64, f: impl FnOnce(&mut Run) -> T) -> Option<T> {
    let shows = app.state::<Shows>();
    let mut g = shows.run.lock().unwrap();
    g.as_mut().filter(|r| r.id == id).map(f)
}

fn note(app: &AppHandle, id: u64, what: String) {
    with_run(app, id, |r| r.events.push(what));
}

/// Mute: the running show follows at once (the next show starts muted from its URL).
pub fn set_muted(app: &AppHandle, muted: bool) {
    let label = app.state::<Shows>().run.lock().unwrap().as_ref().map(|r| r.label.clone());
    if let Some(w) = label.and_then(|l| app.get_webview_window(&l)) {
        let _ = w.eval(format!("window.setMuted && window.setMuted({muted})"));
    }
}

/// Play now. A show or a self-test already on: ignored (as on the Mac). A window made ahead for the schedule's next
/// moment starts at once (that moment then finds a show on and skips).
pub fn play(app: &AppHandle) {
    let shows = app.state::<Shows>();
    if shows.testing.load(Ordering::SeqCst) {
        return;
    }
    let waiting = {
        let mut g = shows.run.lock().unwrap();
        g.as_mut().filter(|r| r.kind == Kind::Play && r.ready_window && !r.shown && r.started.is_none()).map(|r| {
            r.clicked = Instant::now();
            r.started = Some(r.clicked); // taken: a second Play now while it starts is ignored
            r.planned = None;            // a window made for the schedule's moment, taken by Play now
            r.id
        })
    };
    if let Some(id) = waiting {
        let app = app.clone();
        std::thread::spawn(move || {
            if let Err(e) = reveal(&app, id) {
                note(&app, id, format!("cannot start: {e}"));
                finish(&app, id, None, Vec::new());
            }
        });
        return;
    }
    if let Some(id) = claim(app, Kind::Play, false) {
        let app = app.clone();
        std::thread::spawn(move || {
            if let Err(e) = build(&app, id).and_then(|_| reveal(&app, id)) {
                note(&app, id, format!("cannot start: {e}"));
                finish(&app, id, None, Vec::new());
            }
        });
    }
}

/// A show of the schedule or Play now is on (a window made ahead and still waiting is not a show yet).
pub fn is_on(app: &AppHandle) -> bool {
    let shows = app.state::<Shows>();
    shows.testing.load(Ordering::SeqCst)
        || shows.run.lock().unwrap().as_ref().is_some_and(|r| !(r.ready_window && r.started.is_none()))
}

/// A show's window is being made (the panel's WebView2 must wait for it: panel::release).
pub fn making_window(app: &AppHandle) -> bool {
    app.state::<Shows>().run.lock().unwrap().as_ref().is_some_and(|r| !r.made)
}

/// A WebView2 window was destroyed.
pub fn webview_gone() {
    *LAST_GONE.lock().unwrap() = Some(Instant::now());
}

/// SHOW_LEAD_S before a moment of the schedule (modes.rs, its timer thread: nothing here may wait for the main thread):
/// the window, hidden, its video loading.
pub fn prepare_scheduled(app: &AppHandle, planned: f64) {
    if let Some(id) = claim(app, Kind::Play, true) {
        with_run(app, id, |r| r.planned = Some(planned));
        let app = app.clone();
        std::thread::spawn(move || {
            if let Err(e) = build(&app, id) {
                modes::log(format!("show: the window for the moment could not be made: {e}"));
                finish(&app, id, None, Vec::new());
            }
        });
    }
}

/// The moment of the schedule (its timer thread): the window made ahead is shown, or one is made now.
pub fn play_scheduled(app: &AppHandle, due: f64) {
    let shows = app.state::<Shows>();
    let id = {
        let mut g = shows.run.lock().unwrap();
        g.as_mut().filter(|r| r.ready_window && r.started.is_none()).map(|r| {
            r.clicked = Instant::now();
            r.started = Some(r.clicked);
            r.planned = Some(due);
            r.id
        })
    };
    if let Some(id) = id {
        let app = app.clone();
        std::thread::spawn(move || {
            if let Err(e) = reveal(&app, id) {
                note(&app, id, format!("cannot start: {e}"));
                finish(&app, id, None, Vec::new());
            }
        });
        return;
    }
    modes::log("show: no window made ahead (made now)".into());
    if let Some(id) = claim(app, Kind::Play, false) {
        with_run(app, id, |r| r.planned = Some(due));
        let app = app.clone();
        std::thread::spawn(move || {
            if let Err(e) = build(&app, id).and_then(|_| reveal(&app, id)) {
                note(&app, id, format!("cannot start: {e}"));
                finish(&app, id, None, Vec::new());
            }
        });
    }
}

/// The window made for a moment that will not show: it goes.
pub fn drop_ready(app: &AppHandle) {
    let id = app.state::<Shows>().run.lock().unwrap().as_ref()
        .filter(|r| r.kind == Kind::Play && r.ready_window && r.started.is_none()).map(|r| r.id);
    if let Some(id) = id {
        let app = app.clone();
        std::thread::spawn(move || {
            modes::log("show: the window made ahead is not needed, it goes".into());
            finish(&app, id, None, Vec::new());
        });
    }
}

fn claim(app: &AppHandle, kind: Kind, ready_window: bool) -> Option<u64> {
    let shows = app.state::<Shows>();
    let mut g = shows.run.lock().unwrap();
    if g.is_some() {
        return None;
    }
    let id = shows.next.fetch_add(1, Ordering::SeqCst) + 1;
    *g = Some(Run {
        id,
        kind,
        clicked: Instant::now(),
        label: format!("show-{id}"),
        started: None,
        ready_window,
        ready: false,
        made: false,
        made_ms: None,
        ready_ms: None,
        procs_at_claim: sys::tree_count(),
        planned: None,
        shown: false,
        hwnd: 0,
        monitor: Vec::new(),
        rect: None,
        before: None,
        first_frame: None,
        first_frame_at: None,
        first_frame_real: None,
        transparency: Vec::new(),
        verdict: "no screenshot in the pause".into(),
        taskbar_at_pause: None,
        cpu0: None,
        shell_events: 0,
        raises: Vec::new(),
        idle: Vec::new(),
        events: Vec::new(),
    });
    Some(id)
}

/// The window, hidden: placed, click-through, its page loading. A ready window's page loads the video and waits.
fn build(app: &AppHandle, id: u64) -> Result<(), String> {
    let res = make_window(app, id);
    with_run(app, id, |r| {
        r.made = true;
        r.made_ms = Some(ms(r.clicked));
    });
    panel::release(app); // a panel closed meanwhile (Play now) goes now
    res
}

fn make_window(app: &AppHandle, id: u64) -> Result<(), String> {
    crate::assert_off_main("a show's window")?;
    let (kind, ready_window) = with_run(app, id, |r| (r.kind, r.ready_window)).ok_or("the show was stopped")?;
    let mon = app.primary_monitor().map_err(|e| e.to_string())?.ok_or("no primary monitor")?;
    let (pos, size, scale) = (*mon.position(), *mon.size(), mon.scale_factor());
    let wa = mon.work_area();
    let rect = place::show_rect(pos.x, pos.y, size.width, size.height, FRAME_W, FRAME_H);
    let (top, left) = (wa.position.y - pos.y, wa.position.x - pos.x);
    let bottom = size.height as i32 - top - wa.size.height as i32;
    let right = size.width as i32 - left - wa.size.width as i32;
    let monitor = vec![
        format!("monitor (primary{}): {}x{} px at ({}, {}), scale {:.0}% ({:.0} dpi)",
                mon.name().map(|n| format!(", {n}")).unwrap_or_default(),
                size.width, size.height, pos.x, pos.y, scale * 100.0, scale * 96.0),
        format!("work area: {}x{} px; the taskbar takes top {top}, bottom {bottom}, left {left}, right {right} px",
                wa.size.width, wa.size.height),
    ];
    let label = with_run(app, id, |r| {
        r.monitor = monitor;
        r.rect = Some(rect);
        r.label.clone()
    })
    .ok_or("the show was stopped")?;
    let muted = panel::muted(app);
    let url = format!("index.html?id={id}&selftest={}&ready={}&muted={}",
                      (kind == Kind::Test) as u8, ready_window as u8, muted as u8);
    let win = WebviewWindowBuilder::new(app, &label, WebviewUrl::App(url.into()))
        .title("Roadster")
        .transparent(true)
        .decorations(false)
        .shadow(false)
        .resizable(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .focusable(false)
        .visible(false)
        .position(rect.x as f64 / scale, rect.y as f64 / scale)
        .inner_size(rect.w as f64 / scale, rect.h as f64 / scale)
        .additional_browser_args(BROWSER_ARGS)
        .build()
        .map_err(|e| format!("window: {e}"))?;
    win.set_ignore_cursor_events(true).map_err(|e| format!("click-through: {e}"))?;
    let h = win.hwnd().map_err(|e| format!("hwnd: {e}"))?.0 as isize;
    if with_run(app, id, |r| r.hwnd = h).is_none() {
        // the show went while its window was being made (a moment dropped, the lock): no hidden window may stay behind
        let _ = win.destroy();
        webview_gone();
        return Err("the show was stopped while its window was made".into());
    }
    Ok(())
}

/// Shows the window over everything (and starts watching the shell for the taskbar), then closes it if the page
/// never says the show is over. A ready window is also told to play.
fn reveal(app: &AppHandle, id: u64) -> Result<(), String> {
    let (h, rect, ready_window, label, started) =
        with_run(app, id, |r| {
            let started = *r.started.get_or_insert_with(Instant::now);
            (r.hwnd, r.rect, r.ready_window, r.label.clone(), started)
        })
        .ok_or("the show was stopped")?;
    let rect = rect.ok_or("no place")?;
    let a = app.clone();
    app.run_on_main_thread(move || {
        let res = sys::make_overlay(h, rect);
        let watch = sys::watch_shell_events(on_shell_event);
        with_run(&a, id, |r| {
            r.shown = true;
            for e in [res.err(), watch.err()].into_iter().flatten() {
                r.events.push(e);
            }
            r.events.push(format!("window shown in {:.0} ms", ms(started)));
        });
    })
    .map_err(|e| e.to_string())?;
    if ready_window {
        if let Some(w) = app.get_webview_window(&label) {
            w.eval("window.go && window.go()").map_err(|e| format!("go: {e}"))?;
        }
    }
    let a = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs_f64(SHOW_S + 12.0));
        if with_run(&a, id, |_| ()).is_some() {
            note(&a, id, format!("no end from the page {:.0} s after the start: closed", SHOW_S + 12.0));
            finish(&a, id, None, Vec::new());
        }
    });
    Ok(())
}

/// The shell's events (main thread): the car goes back over the taskbar if the taskbar came over it.
fn on_shell_event(event: u32) {
    let Some(app) = APP.get() else { return };
    let shows = app.state::<Shows>();
    let Some((id, h)) = shows.run.lock().unwrap().as_mut().filter(|r| r.shown && r.hwnd != 0).map(|r| {
        r.shell_events += 1;
        (r.id, r.hwnd)
    }) else {
        return;
    };
    // not under the lock: moving the window calls its window procedure right here
    if sys::keep_over_taskbar(h) {
        with_run(app, id, |r| r.raises.push((Instant::now(), event)));
    }
}

/// Self-test: WebView2's processes gone, memory and CPU idle without them, then a show the way the schedule plays one:
/// its window made cold SHOW_LEAD_S before a moment and shown at the moment, measured in full.
pub fn selftest(app: &AppHandle) {
    let shows = app.state::<Shows>();
    // a window made ahead for the schedule goes (the schedule finds a show on and skips); a show on: no self-test
    let waiting = shows.run.lock().unwrap().as_ref().filter(|r| r.ready_window && r.started.is_none()).map(|r| r.id);
    if let Some(id) = waiting {
        finish(app, id, None, Vec::new());
    }
    if shows.run.lock().unwrap().is_some() || shows.testing.swap(true, Ordering::SeqCst) {
        return;
    }
    let app = app.clone();
    std::thread::spawn(move || {
        let shows = app.state::<Shows>();
        *shows.report.lock().unwrap() = None;
        std::thread::sleep(Duration::from_millis(1500)); // the tray menu goes, the app settles
        let mut pre = Vec::new();
        let t = Instant::now();
        let before = sys::tree_count();
        while sys::tree_count() > 1 && t.elapsed() < Duration::from_secs(30) {
            std::thread::sleep(Duration::from_millis(250));
        }
        let after = sys::tree_count();
        let gone = LAST_GONE.lock().unwrap().map(|g| g.elapsed().as_secs_f64() - t.elapsed().as_secs_f64());
        pre.push(format!(
            "processes of the app: {before} when the self-test began, {after} after waiting {:.1} s ({}); the last \
             WebView2 window had gone {} before the self-test began",
            t.elapsed().as_secs_f64(),
            if after <= 1 { "WebView2 exited: only the app is left" } else { "WebView2 still running after 30 s" },
            gone.map(|g| format!("{g:.1} s")).unwrap_or("- (no window since the launch)".into())
        ));
        pre.push(idle_line("idle, the panel closed, no window, WebView2 unloaded", &idle_measure()));
        let id = claim(&app, Kind::Test, true);
        if let Some(id) = id {
            let planned = real_now() + SHOW_LEAD_S + 1.0;
            with_run(&app, id, |r| r.planned = Some(planned));
            sleep_until(planned - SHOW_LEAD_S);
            let procs = sys::tree_count();
            with_run(&app, id, |r| {
                r.clicked = Instant::now();
                r.procs_at_claim = procs;
            });
            let t = Instant::now();
            match build(&app, id) {
                Err(e) => note(&app, id, format!("cannot make the window: {e}")),
                Ok(()) => {
                    while t.elapsed() < Duration::from_secs(15) && with_run(&app, id, |r| r.ready) == Some(false) {
                        std::thread::sleep(Duration::from_millis(20));
                    }
                }
            }
            let rect = with_run(&app, id, |r| r.rect).flatten();
            let before = rect.map(sys::capture);
            with_run(&app, id, |r| {
                r.idle = pre;
                r.before = before;
            });
            let early = planned - real_now();
            sleep_until(planned);
            with_run(&app, id, |r| {
                r.clicked = Instant::now();
                r.started = Some(r.clicked);
                r.events.push(format!("the window was ready {:.2} s before the moment", early));
            });
            if let Err(e) = reveal(&app, id) {
                note(&app, id, format!("cannot start: {e}"));
                finish(&app, id, None, Vec::new());
            }
            let end = Instant::now() + Duration::from_secs_f64(SHOW_S + 20.0);
            while Instant::now() < end && with_run(&app, id, |_| ()).is_some() {
                std::thread::sleep(Duration::from_millis(100));
            }
        }
        let text = shows.report.lock().unwrap().take().unwrap_or_else(|| "Roadster self-test: no report\n".into());
        let path = app.path().desktop_dir().unwrap_or_else(|_| std::env::temp_dir()).join("Roadster-report.txt");
        if std::fs::write(&path, text.replace('\n', "\r\n")).is_ok() {
            let _ = std::process::Command::new("notepad.exe").arg(&path).spawn();
        }
        shows.testing.store(false, Ordering::SeqCst);
    });
}

fn sleep_until(t: f64) {
    let w = t - real_now();
    if w > 0.0 {
        std::thread::sleep(Duration::from_secs_f64(w));
    }
}

struct Idle {
    mem: sys::Mem,
    cpu: f64,
    procs: usize,
}

fn idle_measure() -> Idle {
    let c0 = sys::cpu();
    std::thread::sleep(Duration::from_secs(IDLE_S));
    let c1 = sys::cpu();
    let wall = c1.at.duration_since(c0.at).as_secs_f64();
    Idle { mem: sys::mem(), cpu: c1.tree.saturating_sub(c0.tree) as f64 / 1e7 / wall * 100.0, procs: c1.procs }
}

fn idle_line(what: &str, m: &Idle) -> String {
    format!("{what}: memory {:.1} MB private, {:.1} MB working set ({} processes); CPU over {IDLE_S} s {:.2}% of one core",
            m.mem.private as f64 / 1048576.0, m.mem.working as f64 / 1048576.0, m.procs.max(m.mem.procs), m.cpu)
}

#[tauri::command]
pub async fn show_event(app: AppHandle, id: u64, kind: String) {
    match kind.as_str() {
        "first_frame" => {
            let at = real_now();
            let cpu = sys::cpu();
            let planned = with_run(&app, id, |r| {
                r.first_frame = Some((ms(r.clicked), r.started.map(ms).unwrap_or(0.0)));
                r.first_frame_at = Some(Instant::now());
                r.first_frame_real = Some(at);
                r.cpu0 = Some(cpu);
                r.planned.filter(|_| r.kind == Kind::Play)
            })
            .flatten();
            if let Some(p) = planned {
                modes::first_frame(p, at);
            }
        }
        "ready" => {
            with_run(&app, id, |r| {
                r.ready = true;
                r.ready_ms = Some(ms(r.clicked));
            });
        }
        _ => note(&app, id, kind),
    }
}

/// In the held frame: the screen now against the desktop before the show, judged by the frame's alpha.
#[tauri::command]
pub async fn pause_capture(app: AppHandle, id: u64, mask: String, cols: u32, rows: u32, media_time: f64) {
    let Some((Some(planned), hwnd)) = with_run(&app, id, |r| (r.rect, r.hwnd)) else { return };
    // the window's real rectangle, if Windows moved it
    let rect = sys::window_rect(hwnd).filter(|r| r.w > 0 && r.h > 0).unwrap_or(planned);
    let t = Instant::now();
    let during = sys::capture(rect);
    let took = ms(t);
    let taskbar = sys::is_taskbar_above(hwnd);
    let before = with_run(&app, id, |r| r.before.take()).flatten();
    let mut lines = vec![format!(
        "screenshots: GDI BitBlt of the window's {}x{} px, before the show and at {media_time:.3} s ({took:.0} ms)",
        rect.w, rect.h
    )];
    let verdict = match (before, during) {
        (Some(Ok(b)), Ok(d)) if rect == planned => {
            let (l, v) = compare(&b, &d, rect, mask.as_bytes(), cols, rows);
            lines.extend(l);
            v
        }
        (Some(Ok(_)), Ok(_)) => format!("not compared: the window is at {rect:?}, the desktop was taken at {planned:?}"),
        (Some(Err(e)), _) | (_, Err(e)) => format!("not compared: screenshot failed: {e}"),
        (None, _) => "not compared: no screenshot before the show".into(),
    };
    lines.push(format!("verdict: {verdict}"));
    with_run(&app, id, |r| {
        r.transparency = lines;
        r.verdict = verdict;
        r.taskbar_at_pause = Some(taskbar);
    });
}

/// Pixels the frame leaves clear (cells of alpha 0 whose 8 neighbours are clear too) must be the desktop's; pixels of
/// the car (alpha 255, the same margin) must differ from it. Max of |B|, |G|, |R| differences.
fn compare(before: &[u8], during: &[u8], r: Rect, mask: &[u8], cols: u32, rows: u32) -> (Vec<String>, String) {
    let (cols, rows) = (cols as usize, rows as usize);
    if mask.len() != cols * rows || cols < 3 || rows < 3 {
        return (Vec::new(), format!("not compared: the mask is {} cells for {cols}x{rows}", mask.len()));
    }
    let cls = |x: usize, y: usize| mask[y * cols + x];
    let mut inner = vec![b'1'; cols * rows];
    for y in 0..rows {
        for x in 0..cols {
            let c = cls(x, y);
            let mut same = true;
            for dy in -1i64..=1 {
                for dx in -1i64..=1 {
                    let (nx, ny) = (x as i64 + dx, y as i64 + dy);
                    if nx >= 0 && ny >= 0 && (nx as usize) < cols && (ny as usize) < rows && cls(nx as usize, ny as usize) != c {
                        same = false;
                    }
                }
            }
            if same {
                inner[y * cols + x] = c;
            }
        }
    }
    let (mut n0, mut same2, mut same8, mut n2, mut diff8) = (0u64, 0u64, 0u64, 0u64, 0u64);
    let (mut sum_b, mut sum_d) = ([0u64; 3], [0u64; 3]);
    for py in 0..r.h as usize {
        let cy = ((py as f64 + 0.5) * rows as f64 / r.h as f64) as usize;
        for px in 0..r.w as usize {
            let cx = ((px as f64 + 0.5) * cols as f64 / r.w as f64) as usize;
            let c = inner[cy.min(rows - 1) * cols + cx.min(cols - 1)];
            if c == b'1' {
                continue;
            }
            let i = (py * r.w as usize + px) * 4;
            let d = (0..3).map(|k| (before[i + k] as i32 - during[i + k] as i32).unsigned_abs()).max().unwrap();
            if c == b'0' {
                n0 += 1;
                same2 += (d <= 2) as u64;
                same8 += (d <= 8) as u64;
                for k in 0..3 {
                    sum_b[k] += before[i + k] as u64;
                    sum_d[k] += during[i + k] as u64;
                }
            } else {
                n2 += 1;
                diff8 += (d > 8) as u64;
            }
        }
    }
    let pct = |a: u64, n: u64| if n == 0 { 0.0 } else { a as f64 * 100.0 / n as f64 };
    let rgb = |s: [u64; 3]| if n0 == 0 { "-".to_string() } else { format!("({}, {}, {})", s[2] / n0, s[1] / n0, s[0] / n0) };
    let (clear, car) = (pct(same2, n0), pct(diff8, n2));
    let verdict = if n0 == 0 || n2 == 0 {
        "UNKNOWN: no clear or no car pixels to compare".to_string()
    } else if car < 20.0 && clear > 98.0 {
        format!("CAR NOT SEEN ({car:.1}% of the car differs): the window is invisible, or GDI does not see it")
    } else if clear > 98.0 && car > 80.0 {
        format!("TRANSPARENT (empty places {clear:.1}% the desktop, the car {car:.1}% drawn over it)")
    } else if clear <= 98.0 {
        format!("NOT TRANSPARENT ({:.1}% of the empty places differ from the desktop, mean RGB {})", 100.0 - clear, rgb(sum_d))
    } else {
        format!("UNCLEAR (empty places {clear:.1}% the desktop, car {car:.1}% differs)")
    };
    let lines = vec![
        format!("empty places (alpha 0): {n0} px, same as the desktop {clear:.2}% (diff <= 2), {:.2}% (diff <= 8); \
                 mean RGB before {} / in the pause {}", pct(same8, n0), rgb(sum_b), rgb(sum_d)),
        format!("car (alpha 255): {n2} px, differ from the desktop {car:.2}% (diff > 8)"),
    ];
    (lines, verdict)
}

#[tauri::command]
pub async fn show_done(app: AppHandle, id: u64, lines: Value, errors: Vec<String>) {
    finish(&app, id, Some(lines), errors);
}

fn finish(app: &AppHandle, id: u64, page: Option<Value>, errors: Vec<String>) {
    let shows = app.state::<Shows>();
    let run = {
        let mut g = shows.run.lock().unwrap();
        if g.as_ref().map(|r| r.id) != Some(id) {
            return;
        }
        g.take().unwrap()
    };
    let cpu1 = sys::cpu();
    let real = if run.hwnd != 0 { sys::window_rect(run.hwnd) } else { None };
    let ex = if run.hwnd != 0 { sys::ex_style(run.hwnd) } else { 0 };
    let _ = app.run_on_main_thread(sys::unwatch_shell_events);
    if let Some(w) = app.get_webview_window(&run.label) {
        let _ = w.destroy();
        webview_gone();
    }
    if run.kind == Kind::Test {
        *shows.report.lock().unwrap() = Some(report(app, &run, page.as_ref(), &errors, real, ex, cpu1));
    }
}

fn ex_text(ex: u32) -> String {
    let yn = |b: bool| if b { "yes" } else { "no" };
    format!(
        "ex-style 0x{ex:08X} (tool window {}, no-activate {}, topmost {}, click-through {}, layered {})",
        yn(ex & 0x80 != 0), yn(ex & 0x0800_0000 != 0), yn(ex & 0x8 != 0), yn(ex & 0x20 != 0), yn(ex & 0x8_0000 != 0)
    )
}

fn report(app: &AppHandle, run: &Run, page: Option<&Value>, errors: &[String], real: Option<Rect>, ex: u32,
          cpu1: sys::Cpu) -> String {
    let section = |name: &str| -> Vec<String> {
        page.and_then(|p| p.get(name)).and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|s| s.as_str().map(String::from)).collect())
            .unwrap_or_default()
    };
    let mut o: Vec<String> = Vec::new();
    o.push(format!("Roadster self-test, build {} ({}, built {})",
                   env!("CARGO_PKG_VERSION"), env!("ROADSTER_GIT"), env!("ROADSTER_BUILD_TIME")));
    o.push(format!("windows: {}", sys::windows_version()));
    o.push(format!("webview2: {}", tauri::webview_version().unwrap_or_else(|e| format!("unknown ({e})"))));
    o.extend(section("page").into_iter().take(1)); // time
    o.push(String::new());
    o.push("[WebView2 unloaded: the app's processes, memory and CPU with no window]".into());
    o.extend(run.idle.iter().cloned());
    o.push(String::new());
    o.push(format!("[a show the way the schedule plays one: its window made {SHOW_LEAD_S} s before the moment]"));
    o.push(format!(
        "window made {} ({}), the page ready (video loaded) {} from the start of making it",
        run.made_ms.map(|m| format!("{m:.0} ms")).unwrap_or("-".into()),
        if run.procs_at_claim <= 1 { "cold: WebView2 was not running" } else { "WebView2 was running" },
        run.ready_ms.map(|m| format!("{m:.0} ms")).unwrap_or("- (never)".into())
    ));
    match (run.planned, run.first_frame_real) {
        (Some(p), Some(f)) => o.push(format!("first frame {:+.0} ms from the moment planned", (f - p) * 1000.0)),
        _ => o.push("first frame against the moment: no frame came".into()),
    }
    o.push(String::new());
    o.push("[panel]".into());
    o.extend(panel::report_lines(app));
    o.push(tray::report_line(app));
    o.push(String::new());
    o.push("[screen and window]".into());
    o.extend(run.monitor.iter().cloned());
    let fmt = |r: Rect| format!("{}x{} px at ({}, {})", r.w, r.h, r.x, r.y);
    o.push(format!("window: {} (planned {})", real.map(fmt).unwrap_or("-".into()), run.rect.map(fmt).unwrap_or("-".into())));
    o.push(ex_text(ex));
    o.extend(section("page").into_iter().skip(1));
    o.push(String::new());
    o.push("[smoothness]".into());
    o.extend(section("smooth"));
    let from = if run.ready_window { "from Play (the window ready)" } else { "from the window's start" };
    match run.first_frame {
        Some((_, start)) => o.push(format!("Play -> first frame: {start:.0} ms {from}")),
        None => o.push("Play -> first frame: no frame came".into()),
    }
    if let Some(c0) = run.cpu0 {
        let wall = cpu1.at.duration_since(c0.at).as_secs_f64();
        let cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1) as f64;
        let tree = (cpu1.tree.saturating_sub(c0.tree)) as f64 / 1e7 / wall * 100.0;
        let sys_pct = cpu1.sys_busy.saturating_sub(c0.sys_busy) as f64 * 100.0
            / (cpu1.sys_total.saturating_sub(c0.sys_total)).max(1) as f64;
        o.push(format!(
            "cpu over {wall:.1} s of the show: app + WebView2 ({} processes) {tree:.0}% of one core = {:.1}% of {cores:.0}; whole system {sys_pct:.0}%",
            cpu1.procs, tree / cores
        ));
    }
    o.push(String::new());
    o.push("[over the taskbar: on the shell's events, no timer]".into());
    let t0 = run.first_frame_at;
    let at = |t: Instant| match t0 {
        Some(f) if t >= f => format!("{:.2} s", t.duration_since(f).as_secs_f64()),
        Some(f) => format!("-{:.2} s", f.duration_since(t).as_secs_f64()),
        None => "?".into(),
    };
    o.push(format!("shell events during the show: {}; put back over the taskbar: {}", run.shell_events, run.raises.len()));
    if !run.raises.is_empty() {
        let list: Vec<String> = run.raises.iter().map(|&(t, e)| format!("{} ({})", at(t), sys::event_name(e))).collect();
        o.push(format!("put back at (seconds from the first frame): {}", list.join(", ")));
    }
    if let Some(b) = run.taskbar_at_pause {
        o.push(format!("the taskbar over the car at the pause's screenshot: {}", if b { "YES" } else { "no" }));
    }
    o.push(String::new());
    o.push("[sound]".into());
    o.extend(section("sound"));
    o.push(String::new());
    o.push("[transparency: screen pixels in the pause against the desktop before]".into());
    if run.transparency.is_empty() {
        o.push(format!("verdict: {}", run.verdict));
    }
    o.extend(run.transparency.iter().cloned());
    o.push(String::new());
    o.push("[events of this show]".into());
    o.extend(run.events.iter().cloned());
    if errors.is_empty() {
        o.push("page errors: none".into());
    } else {
        o.extend(errors.iter().map(|e| format!("page error: {e}")));
    }
    o.push(String::new());
    o.push("[modes: the schedule, its counters, Windows' events]".into());
    o.extend(modes::report_lines());
    o.push(String::new());
    let log = modes::log_lines();
    o.push(format!("[the app's log since the launch: the last {} lines]", log.len().min(200)));
    o.extend(log.iter().skip(log.len().saturating_sub(200)).cloned());
    o.join("\n") + "\n"
}
