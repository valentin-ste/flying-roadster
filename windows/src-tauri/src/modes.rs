// The modes: the app's side of the schedule (roadster-schedule, windows/schedule: the Mac's Schedule.swift), as the
// Mac's ModeTimer.swift. The settings go in, one strict timer waits for the next moment (the schedule crate's driver.rs:
// a thread asleep on a condition variable until then - no polling: idle CPU is the app's own zero), Windows' events
// (events.rs) stand it, the show comes out. The panel only shows the state and sends the buttons (panel.rs): everything lives here, in Rust, so the
// panel's WebView2 can be unloaded while it is closed.
//
// The show's window is made SHOW_LEAD_S before a moment of the schedule (hidden, its video loaded), so the first frame
// comes on time: WebView2 is not running between shows (cold start ~0.5 s in the probe's report). If the moment goes
// (Pause, Off, sleep, a new mode), so does the window.
//
// Test builds: "Mode check (test)" runs the schedule crate's check.rs - a scheduler of its own on a clock 60 times
// faster with a pretend show (the Mac's TimeScale + -TestScript + -TestFakeShow) through this same timer - and writes
// the moments planned and the moments the timer fired to Roadster-modes.txt on the desktop. The app's own schedule and
// settings are not touched.

use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use roadster_schedule::check::stats_line;
use roadster_schedule::driver::{Driver, Hooks};
use roadster_schedule::{Mode, Pomodoro, Scheduler, Time};
use tauri::{AppHandle, Manager};

use crate::events::Ev;
use crate::settings::Settings;
use crate::{panel, show, sys, tray};

/// Seconds (real) before a moment of the schedule that the show's window is made, hidden, its video loading. The probe
/// measured ~0.5 s from a cold start to the first frame (0.1.0 report: 486 ms); the self-test measures it again after
/// the engine is unloaded (its "[scheduled show]" lines). 3 s leaves room for a slow disk after a wake.
pub const SHOW_LEAD_S: f64 = 3.0;
/// Windows says a full-screen game, a full-screen video, a presentation or its quiet time is on
/// (SHQueryUserNotificationState): true would skip a show of the schedule then. Valentin, 10.11: false - the shows play
/// over full-screen games, presentations and films too (a pomodoro's user may want the signal; whoever minds switches
/// it off). On his Windows 10 the state also read "busy" with no full-screen app and after the lock, which skipped
/// every show of the schedule (0.3.0).
pub const SKIP_WHEN_QUIET: bool = false;
const LOG_LINES: usize = 500;

pub fn real_now() -> Time {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

// ---- the app's schedule ----

static APP: OnceLock<AppHandle> = OnceLock::new();
static DRIVER: OnceLock<Arc<Driver>> = OnceLock::new();
static LOG: Mutex<VecDeque<String>> = Mutex::new(VecDeque::new());
static EVENTS: Mutex<BTreeMap<&'static str, u32>> = Mutex::new(BTreeMap::new());
static SHOWS: [AtomicU32; 4] = [AtomicU32::new(0), AtomicU32::new(0), AtomicU32::new(0), AtomicU32::new(0)];
static FIRST_FRAMES: Mutex<Vec<f64>> = Mutex::new(Vec::new());
static STARTED: OnceLock<Instant> = OnceLock::new();

/// A line of the app's log (the self-test prints it): local time, then the line.
pub fn log(line: String) {
    // the schedule's show lines, counted: played, skipped (a show on), skipped (quiet), not played (found late)
    if let Some(rest) = line.strip_prefix("show: ") {
        let i = if rest.contains("not played") {
            3
        } else if rest.contains("skipped, a show is on") {
            1
        } else if rest.contains("skipped,") {
            2
        } else {
            0
        };
        SHOWS[i].fetch_add(1, Ordering::Relaxed);
    }
    let mut g = LOG.lock().unwrap();
    g.push_back(format!("{} {line}", sys::local_stamp(real_now())));
    while g.len() > LOG_LINES {
        g.pop_front();
    }
}

fn driver() -> Option<&'static Arc<Driver>> {
    DRIVER.get()
}

fn mode_of(s: &Settings) -> Mode {
    Mode::from_key(&s.mode).unwrap_or(Mode::Pomodoro)
}

/// The app's start (setup): the schedule from the settings, the state Windows is in (a launch at login behind a locked
/// screen, say), the timer, Windows' events.
pub fn init(app: &AppHandle, st: &Settings) {
    let _ = APP.set(app.clone());
    let _ = STARTED.set(Instant::now());
    let mut s = Scheduler::new(Box::new(real_now), mode_of(st), st.enabled);
    s.utc_offset = Box::new(sys::utc_offset);
    s.set_lengths(st.pomodoro_work_minutes, st.pomodoro_break_minutes);
    s.set_range(st.random_from_minutes, st.random_to_minutes);
    let a = app.clone();
    s.show_is_on = Box::new(move || show::is_on(&a));
    s.quiet = Box::new(|| if SKIP_WHEN_QUIET { sys::quiet() } else { None });
    let a = app.clone();
    s.play = Box::new(move |_what, due| show::play_scheduled(&a, due));
    s.log = Box::new(log);
    let a = app.clone();
    s.switched_on = Box::new(move || panel::update(&a, |s| s.enabled = true)); // the switch follows Start/Resume
    let a1 = app.clone();
    let a2 = app.clone();
    let a3 = app.clone();
    let hooks = Hooks {
        prepare: Box::new(move |t| show::prepare_scheduled(&a1, t)),
        drop_ready: Box::new(move || show::drop_ready(&a2)),
        changed: Box::new(move || panel::refresh(&a3)),
        query: Box::new(sys::query_away),
        say: Box::new(log),
    };
    for (why, on) in sys::query_away() {
        if on {
            s.suspend(why);
        }
    }
    s.begin();
    let d = Driver::new(s, 1.0, SHOW_LEAD_S, hooks);
    d.start("roadster-timer");
    let _ = DRIVER.set(d);
    match crate::events::start(on_event) {
        Ok(()) => log("events: sleep, the screens, the lock, the session, the screensaver, the clock: watched".into()),
        Err(e) => log(format!("events: {e}")),
    }
}

fn count(what: &'static str) {
    *EVENTS.lock().unwrap().entry(what).or_insert(0) += 1;
}

pub const EVENT_NAMES: [&str; 12] = ["sleep", "wake", "screens off", "screens on", "lock", "unlock", "session away",
                                     "session back", "screensaver on", "screensaver off", "clock changed", "look changed"];

/// Windows' events (events.rs, its own thread).
fn on_event(e: Ev) {
    let Some(d) = driver() else { return };
    match e {
        Ev::Suspend => {
            count("sleep");
            log("event: sleep (PBT_APMSUSPEND)".into());
            d.away("sleep");
        }
        Ev::Resume => {
            count("wake");
            log("event: wake (PBT_APMRESUME*)".into());
            d.back("sleep");
        }
        Ev::ScreensOff => {
            count("screens off");
            log("event: the screens off (GUID_CONSOLE_DISPLAY_STATE 0)".into());
            d.away("screens");
        }
        Ev::ScreensOn => {
            // Windows sends the state once on registering: only a change is an event
            if d.read(|s, _| s.has_reason("screens")) {
                count("screens on");
                log("event: the screens on (GUID_CONSOLE_DISPLAY_STATE 1/2)".into());
                d.back("screens");
            }
        }
        Ev::Lock => {
            count("lock");
            log("event: lock (WTS_SESSION_LOCK)".into());
            d.away("lock");
        }
        Ev::Unlock => {
            count("unlock");
            log("event: unlock (WTS_SESSION_UNLOCK)".into());
            d.back("lock");
        }
        Ev::SessionAway => {
            count("session away");
            log("event: the session left the screen (WTS_*_DISCONNECT)".into());
            d.away("session");
        }
        Ev::SessionBack => {
            count("session back");
            log("event: the session is on the screen again (WTS_*_CONNECT)".into());
            d.back("session");
        }
        Ev::SaverCheck => {
            let on = sys::screensaver_running();
            let had = d.read(|s, _| s.has_reason("screensaver"));
            if on && !had {
                count("screensaver on");
                log("event: the screensaver runs (SPI_GETSCREENSAVERRUNNING)".into());
                d.away("screensaver");
            } else if !on && had {
                count("screensaver off");
                log("event: the screensaver is over".into());
                d.back("screensaver");
            }
        }
        Ev::TimeChanged => {
            count("clock changed");
            log("event: the clock or the time zone changed (WM_TIMECHANGE)".into());
            d.with(|s| s.clock_changed());
        }
        Ev::Look => {
            if let Some(app) = APP.get() {
                if tray::refresh(app) {
                    count("look changed");
                }
            }
        }
    }
}

/// The settings changed in the panel: the schedule follows (as the Mac's Combine sinks).
pub fn apply(st: &Settings) {
    let Some(d) = driver() else { return };
    let m = mode_of(st);
    d.with(|s| {
        s.set_mode(m);
        s.set_enabled(st.enabled);
        s.set_lengths(st.pomodoro_work_minutes, st.pomodoro_break_minutes);
        s.set_range(st.random_from_minutes, st.random_to_minutes);
    });
}

/// The pomodoro's buttons.
pub fn button(name: &str) {
    let Some(d) = driver() else { return };
    d.with(|s| match name {
        "start" => s.start(),
        "pause" => s.pause(),
        "resume" => s.resume(),
        "reset" => s.reset(),
        _ => {}
    });
}

/// Play now works always, off as well; Random counts its minutes from it. A window made for the next moment of the
/// schedule is taken (it starts at once); that moment then finds a show on and skips.
pub fn play_now(app: &AppHandle, from: &str) {
    if show::is_on(app) {
        log(format!("Play now ({from}): a show is on, ignored"));
        return;
    }
    log(format!("Play now ({from})"));
    show::play(app);
    if let Some(d) = driver() {
        d.with(|s| s.note_show("Play now"));
    }
}

/// The first frame of a show of the schedule, against its moment (show.rs).
pub fn first_frame(planned: Time, at: Time) {
    let ms = (at - planned) * 1000.0;
    log(format!("first frame: {ms:+.0} ms from the moment of the schedule"));
    let mut g = FIRST_FRAMES.lock().unwrap();
    g.push(ms);
    if g.len() > 50 {
        g.remove(0);
    }
}

/// What the panel shows.
pub struct View {
    pub pomodoro: Pomodoro,
    pub left: f64,
}

pub fn view() -> Option<View> {
    let d = driver()?;
    Some(d.read(|s, _| {
        let p = s.pomodoro();
        View { pomodoro: p, left: p.left_at(s.now()) }
    }))
}

/// For the self-test's report: the schedule now, the counters (zeros too), Windows' events, the log.
pub fn report_lines() -> Vec<String> {
    let mut o = Vec::new();
    let Some(d) = driver() else {
        o.push("the schedule is not running".into());
        return o;
    };
    let up = STARTED.get().map(|t| t.elapsed().as_secs_f64() / 60.0).unwrap_or(0.0);
    d.read(|s, st| {
        let p = s.pomodoro();
        let (w, b) = s.lengths();
        o.push(format!("mode {}, switch {}, running {up:.0} min; away: {}", s.mode().key(),
                       if s.enabled() { "on" } else { "off" },
                       if s.asleep() { s.reasons().join(", ") } else { "nothing".into() }));
        o.push(format!("pomodoro: {} {} ({w} + {b} min), {} left{}", p.run.key(), p.phase.key(),
                       roadster_schedule::mmss(p.left_at(s.now())),
                       p.deadline.map(|t| format!(", ends at {}", s.hms(t))).unwrap_or_default()));
        o.push(format!("next moment: {}", s.next_wake().map(|t| sys::local_stamp(t)).unwrap_or("none (waits)".into())));
        o.push(format!("timer fired: {} (lateness {}); show windows made ahead {SHOW_LEAD_S} s: {}, dropped unused: {}",
                       st.fires, stats_line(&st.late_ms), st.prepared, st.dropped));
    });
    o.push(format!("shows of the schedule: played {}, skipped (a show on) {}, skipped (Windows quiet) {}, not played \
                    (found late, an unannounced sleep) {}",
                   SHOWS[0].load(Ordering::Relaxed), SHOWS[1].load(Ordering::Relaxed), SHOWS[2].load(Ordering::Relaxed),
                   SHOWS[3].load(Ordering::Relaxed)));
    o.push(format!("first frame of a show of the schedule against its moment: {}", stats_line(&FIRST_FRAMES.lock().unwrap())));
    let ev = EVENTS.lock().unwrap();
    o.push(format!("Windows' events: {}", EVENT_NAMES.iter().map(|n| format!("{n} {}", ev.get(n).unwrap_or(&0)))
        .collect::<Vec<_>>().join(", ")));
    o.push(format!("Windows now: notification state {}; skip the schedule's shows when quiet: {}",
                   sys::notification_state(), if SKIP_WHEN_QUIET { "yes" } else { "no" }));
    o
}

pub fn log_lines() -> Vec<String> {
    LOG.lock().unwrap().iter().cloned().collect()
}


// ---- the mode check (test builds) ----

pub fn mode_check(app: &AppHandle) {
    static RUNNING: AtomicU32 = AtomicU32::new(0);
    if RUNNING.swap(1, Ordering::SeqCst) == 1 {
        return;
    }
    let app = app.clone();
    std::thread::spawn(move || {
        let real0 = real_now();
        let out = roadster_schedule::check::run(60.0, sys::utc_offset, real0);
        let mut lines = vec![
            format!("Roadster mode check (test build {}, {}, built {})", env!("CARGO_PKG_VERSION"), env!("ROADSTER_GIT"),
                    env!("ROADSTER_BUILD_TIME")),
            format!("windows: {}; started {}", sys::windows_version(), sys::local_stamp(real0)),
        ];
        lines.extend(out.lines);
        log(format!("mode check: {}", if out.ok { "all OK" } else { "SOMETHING IS WRONG" }));
        let path = app.path().desktop_dir().unwrap_or_else(|_| std::env::temp_dir()).join("Roadster-modes.txt");
        if std::fs::write(&path, (lines.join("\n") + "\n").replace('\n', "\r\n")).is_ok() {
            let _ = std::process::Command::new("notepad.exe").arg(&path).spawn();
        }
        RUNNING.store(0, Ordering::SeqCst);
    });
}
