//! The mode check (the Windows test build's tray menu, "Mode check"; tests/schedule.rs runs it on the Mac 600 times
//! faster): a scheduler of its own on a clock `scale` times faster than real time, a pretend show of 14 s of that clock
//! (the Mac's TimeScale + -TestScript + -TestFakeShow), driven by the same timer as the app's (driver.rs), through a
//! script of the panel's buttons, the switch and a pretend lock. It returns the moments planned, the moments the timer
//! fired, and verdicts. The app's own schedule and settings are not touched.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::driver::{Driver, Hooks};
use crate::{Mode, Scheduler, Time};

/// A step: the schedule's minute (= the real second at x60) and the action.
pub const SCRIPT: &[(f64, &str)] = &[
    (0.0, "work 1 1"),
    (0.0, "start"),
    (4.5, "pause"),
    (5.5, "resume"),
    (6.25, "off"),
    (7.25, "on"),
    (8.5, "lock"),
    (9.5, "unlock"),
    (10.25, "play"),
    (10.5, "reset"),
    (10.75, "range 1 2"),
    (10.75, "mode random"),
    (16.0, "mode hourly"),
    (19.5, "end"),
];
/// The pomodoro's moments the script gives (minutes from the start): work 1 + break 1 round, Pause 4.5-5.5 moves the
/// end from 5 to 6, Off 6.25-7.25 from 7 to 8, the lock 8.5-9.5 from 9 to 10. The steps come a few real ms late (the
/// OS's sleep: up to ~16 ms on Windows, a second of the check's clock at x60), so the verdict counts the expected
/// moments from when each step really came, to TOLERANCE_MIN.
pub const EXPECT_POMODORO: [f64; 7] = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0];
pub const TOLERANCE_MIN: f64 = 0.01;
/// Every hour: the check's clock starts 18 minutes before an o'clock.
pub const EXPECT_HOURLY: f64 = 18.0;

pub struct CheckOut {
    pub lines: Vec<String>,
    pub ok: bool,
    pub fires: u32,
}

/// "N times, mean +x ms, from a to b ms" of a list of milliseconds.
pub fn stats_line(v: &[f64]) -> String {
    if v.is_empty() {
        return "none yet".into();
    }
    let mean = v.iter().sum::<f64>() / v.len() as f64;
    let max = v.iter().cloned().fold(f64::MIN, f64::max);
    let min = v.iter().cloned().fold(f64::MAX, f64::min);
    format!("{} times, mean {mean:+.1} ms, from {min:+.1} to {max:+.1} ms", v.len())
}

struct State {
    shows: Vec<(String, Time, Time)>, // what, planned, fired (the check's clock)
    show_until: Time,
    acted: Vec<(&'static str, Time)>, // each step and when it really came (the check's clock)
    log: Vec<String>,
}

/// Runs the script (19.5 minutes of the check's clock: 19.5 s real at x60). `utc_offset`: the local clock's (Windows'
/// time zone in the app); `real_now`: seconds since 1970 now.
pub fn run(scale: f64, utc_offset: fn(f64) -> f64, real_now: f64) -> CheckOut {
    let t0 = Instant::now();
    let off = utc_offset(real_now);
    let sched0 = ((real_now + off) / 3600.0).floor() * 3600.0 - off + 3600.0 - EXPECT_HOURLY * 60.0;
    let clock = move || sched0 + t0.elapsed().as_secs_f64() * scale;
    let st = Arc::new(Mutex::new(State { shows: Vec::new(), show_until: f64::MIN, acted: Vec::new(), log: Vec::new() }));
    let mut s = Scheduler::new(Box::new(clock), Mode::Pomodoro, true);
    s.utc_offset = Box::new(utc_offset);
    s.late_limit = 60.0 * scale;
    let c = st.clone();
    s.show_is_on = Box::new(move || clock() < c.lock().unwrap().show_until);
    let c = st.clone();
    s.play = Box::new(move |what, due| {
        let mut g = c.lock().unwrap();
        let now = clock();
        g.shows.push((what.to_string(), due, now));
        g.show_until = now + 14.0; // the pretend show: 14 s of the check's clock
    });
    let stamp = move || format!("min {:6.3} (real {:7.3} s)", (clock() - sched0) / 60.0, t0.elapsed().as_secs_f64());
    let c = st.clone();
    s.log = Box::new(move |line| c.lock().unwrap().log.push(format!("{} {line}", stamp())));
    let c = st.clone();
    let say = move |line: String| c.lock().unwrap().log.push(format!("{} {line}", stamp()));
    let hooks = Hooks {
        prepare: Box::new(|_| {}),
        drop_ready: Box::new(|| {}),
        changed: Box::new(|| {}),
        query: Box::new(Vec::new),
        say: Box::new(say.clone()),
    };
    s.begin();
    let d = Driver::new(s, scale, 0.0, hooks);
    d.start("roadster-check");
    for &(minute, action) in SCRIPT {
        let at = Duration::from_secs_f64(minute * 60.0 / scale);
        if let Some(w) = at.checked_sub(t0.elapsed()) {
            std::thread::sleep(w);
        }
        st.lock().unwrap().acted.push((action, clock()));
        say(format!("check: {action}"));
        let w: Vec<&str> = action.split(' ').collect();
        let n = |i: usize| w.get(i).and_then(|x| x.parse::<u32>().ok()).unwrap_or(1);
        match w[0] {
            "work" => d.with(|s| s.set_lengths(n(1), n(2))),
            "start" => d.with(|s| s.start()),
            "pause" => d.with(|s| s.pause()),
            "resume" => d.with(|s| s.resume()),
            "reset" => d.with(|s| s.reset()),
            "off" => d.with(|s| s.set_enabled(false)),
            "on" => d.with(|s| s.set_enabled(true)),
            "lock" => d.away("test-lock"),
            "unlock" => d.back("test-lock"),
            "range" => d.with(|s| s.set_range(n(1), n(2))),
            "mode" => {
                let m = Mode::from_key(w[1]).unwrap_or(Mode::Pomodoro);
                d.with(|s| s.set_mode(m))
            }
            "play" => {
                let now = clock();
                let mut g = st.lock().unwrap();
                if now < g.show_until {
                    g.log.push("check: Play now: a show is on, ignored".into());
                } else {
                    g.shows.push(("Play now".into(), now, now));
                    g.show_until = now + 14.0;
                    drop(g);
                    d.with(|s| s.note_show("Play now"));
                }
            }
            _ => {}
        }
    }
    d.stop();
    let fires = d.read(|_, st| st.fires);
    let g = st.lock().unwrap();
    let m = |t: Time| (t - sched0) / 60.0;
    let mut o = vec![
        format!("the check's own clock, {scale:.0} times faster than real time, a pretend show of 14 s of that clock; \
                 the app's own schedule and settings untouched"),
        String::new(),
        "[script, minutes of the check's clock: planned -> when the step really came]".into(),
    ];
    o.push(SCRIPT.iter().zip(g.acted.iter()).map(|((p, a), (_, t))| format!("{p} {a} ({:.3})", m(*t)))
        .collect::<Vec<_>>().join("; "));
    o.push(String::new());
    o.push("[shows: planned -> the timer fired, minutes of the check's clock; real ms late]".into());
    for (what, planned, fired) in g.shows.iter() {
        o.push(format!("{what:28} planned {:7.3}  fired {:7.3}  late {:6.1} ms real", m(*planned), m(*fired),
                       (fired - planned) / scale * 1000.0));
    }
    o.push(String::new());
    o.push("[verdict]".into());
    let when = |name: &str| g.acted.iter().find(|a| a.0 == name).map(|a| m(a.1)).unwrap_or(0.0);
    // the expected moments from the steps' real times: what each stand (Pause, Off, the lock) left, from its end
    let s0 = when("start");
    let mut expect: Vec<f64> = (1..=4).map(|k| s0 + k as f64).collect();
    let e1 = when("resume") + (s0 + 5.0 - when("pause"));
    let e2 = when("on") + (e1 + 1.0 - when("off"));
    let e3 = when("unlock") + (e2 + 1.0 - when("lock"));
    expect.extend([e1, e2, e3]);
    let pomo: Vec<f64> = g.shows.iter().filter(|s| s.0.starts_with("pomodoro")).map(|s| m(s.1)).collect();
    let pomo_ok = pomo.len() == expect.len() && pomo.iter().zip(&expect).all(|(a, b)| (a - b).abs() <= TOLERANCE_MIN);
    let r3 = |v: &[f64]| v.iter().map(|x| (x * 1000.0).round() / 1000.0).collect::<Vec<_>>();
    o.push(format!("pomodoro: moments {:?}; expected {:?} from the steps' real times (nominally {EXPECT_POMODORO:?}), \
                    each within {TOLERANCE_MIN} min: {}", r3(&pomo), r3(&expect), if pomo_ok { "OK" } else { "WRONG" }));
    let late: Vec<f64> = g.shows.iter().filter(|s| s.0 != "Play now").map(|s| (s.2 - s.1) / scale * 1000.0).collect();
    let late_ok = !late.is_empty() && late.iter().all(|&l| (0.0..100.0).contains(&l));
    o.push(format!("the timer after each moment: {} (each 0-100 ms: {})", stats_line(&late), if late_ok { "OK" } else { "NO" }));
    // Random: from the step that turned it on, each moment 1-2 min after the last show - after the moment it really
    // fired, as the schedule draws the next one then (measured from the planned one, a fast clock's few ms late made a
    // 1.99 min draw read 2.03)
    let mut last = g.acted.iter().find(|a| a.0 == "mode random").map(|a| m(a.1)).unwrap_or(10.75);
    let mut rnd = Vec::new();
    let mut rnd_ok = true;
    for s in g.shows.iter().filter(|s| s.0 == "random") {
        let gap = m(s.1) - last;
        rnd_ok &= (0.99..=2.01).contains(&gap);
        rnd.push(format!("{gap:.2}"));
        last = m(s.2);
    }
    rnd_ok &= !rnd.is_empty();
    o.push(format!("random: {} shows, minutes after the last show [{}], each within 1-2: {}", rnd.len(), rnd.join(", "),
                   if rnd_ok { "OK" } else { "NO" }));
    let hourly: Vec<f64> = g.shows.iter().filter(|s| s.0.starts_with("hourly")).map(|s| m(s.1)).collect();
    let hourly_ok = hourly.len() == 1 && (hourly[0] - EXPECT_HOURLY).abs() < 1e-6;
    o.push(format!("every hour: {:?}, expected [{EXPECT_HOURLY}] (that clock's o'clock): {}",
                   hourly.iter().map(|x| (x * 1000.0).round() / 1000.0).collect::<Vec<_>>(), if hourly_ok { "OK" } else { "WRONG" }));
    let away = [(when("pause"), when("resume")), (when("off"), when("on")), (when("lock"), when("unlock"))];
    let quiet_ok = !g.shows.iter().any(|s| away.iter().any(|&(a, b)| m(s.1) > a && m(s.1) < b));
    o.push(format!("no show while paused, off or locked: {}", if quiet_ok { "OK" } else { "NO" }));
    let ok = pomo_ok && late_ok && rnd_ok && hourly_ok && quiet_ok;
    o.push(format!("ALL: {}", if ok { "OK" } else { "SOMETHING IS WRONG (see above)" }));
    o.push(format!("the timer fired {fires} times; the check took {:.1} s real", t0.elapsed().as_secs_f64()));
    o.push(String::new());
    o.push("[the check's log]".into());
    o.extend(g.log.iter().cloned());
    CheckOut { lines: o, ok, fires }
}
