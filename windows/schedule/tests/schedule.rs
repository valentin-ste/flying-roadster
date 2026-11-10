// The schedule (src/lib.rs) on a clock of its own: hours of the three modes in milliseconds. The Mac's checks
// (mac/Tests/ScheduleTests.swift) case for case, then the Windows-only ones (quiet: a full-screen app).
//   cargo test --manifest-path windows/schedule/Cargo.toml [-- -v]
// windows/build.sh runs it before every build; exit 0 = all checks hold. -v prints the schedule's log.
// Time zones without a database: Moscow +3, Kolkata +5:30, Berlin with the EU's summer time (last Sundays of March and
// October, 01:00 UTC).

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use std::time::{Duration, Instant};

use roadster_schedule::driver::{Driver, Hooks};
use roadster_schedule::{check, minutes, mmss, Mode, Phase, Run, Scheduler, Time};

static CHECKS: AtomicUsize = AtomicUsize::new(0);
static FAILURES: AtomicUsize = AtomicUsize::new(0);

fn check_at(ok: bool, what: impl FnOnce() -> String, line: u32) {
    CHECKS.fetch_add(1, Ordering::SeqCst);
    if !ok {
        FAILURES.fetch_add(1, Ordering::SeqCst);
        println!("FAIL (line {line}): {}", what());
    }
}

macro_rules! check {
    ($ok:expr, $what:expr) => {
        check_at($ok, || $what.to_string(), line!())
    };
}
macro_rules! eq {
    ($a:expr, $b:expr, $what:expr) => {{
        let (a, b) = ($a, $b);
        let ok = a == b;
        check_at(ok, || format!("{}: {:?}, expected {:?}", $what, a, b), line!())
    }};
}

fn test(name: &str, body: impl FnOnce()) {
    let f = FAILURES.load(Ordering::SeqCst);
    body();
    let ok = FAILURES.load(Ordering::SeqCst) == f;
    println!("{}  {name}", if ok { "ok    " } else { "FAILED" });
}

// ---- time zones and dates ----

#[derive(Clone, Copy)]
enum Zone {
    Moscow,
    Berlin,
    Kolkata,
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn year_of(days: i64) -> i64 {
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    yoe + era * 400 + if mp >= 10 { 1 } else { 0 }
}

fn last_sunday(y: i64, m: i64) -> i64 {
    let d = days_from_civil(y, m, 31);
    d - (d + 4).rem_euclid(7) // 1970-01-01 was a Thursday: (days + 4) % 7 == 0 on Sundays
}

fn offset(z: Zone, t: Time) -> f64 {
    match z {
        Zone::Moscow => 3.0 * 3600.0,
        Zone::Kolkata => 5.5 * 3600.0,
        Zone::Berlin => {
            let y = year_of((t / 86400.0).floor() as i64);
            let start = (last_sunday(y, 3) * 86400 + 3600) as f64;
            let end = (last_sunday(y, 10) * 86400 + 3600) as f64;
            if t >= start && t < end { 7200.0 } else { 3600.0 }
        }
    }
}

/// "2026-11-02 10:25:00" or "10:25:00" (that day), local to the time zone.
fn at_tz(tz: Zone, text: &str) -> Time {
    let full = if text.len() > 8 { text.to_string() } else { format!("2026-11-02 {text}") };
    let n: Vec<i64> = full.split(|c| c == '-' || c == ' ' || c == ':').map(|p| p.parse().unwrap()).collect();
    let local = (days_from_civil(n[0], n[1], n[2]) * 86400 + n[3] * 3600 + n[4] * 60 + n[5]) as f64;
    let o = offset(tz, local - offset(tz, local));
    let utc = local - o;
    if offset(tz, utc) == o { utc } else { local - offset(tz, utc) }
}

// ---- the world: a scheduler, its clock, a stage where every show takes 14 s (as the real one), Random's draws ----

struct State {
    now: Time,
    shows: Vec<(Time, String)>,
    show_until: Time,
    draws: Vec<f64>,
}

struct World {
    st: Arc<Mutex<State>>,
    s: Scheduler,
    tz: Zone,
}

fn verbose() -> bool {
    std::env::args().any(|a| a == "-v")
}

impl World {
    fn new(start: &str, mode: Mode) -> World {
        World::with(start, mode, Zone::Moscow, &[0.5], true)
    }

    fn with(start: &str, mode: Mode, tz: Zone, draws: &[f64], enabled: bool) -> World {
        let st = Arc::new(Mutex::new(State { now: 0.0, shows: Vec::new(), show_until: f64::MIN, draws: draws.to_vec() }));
        let c = st.clone();
        let mut s = Scheduler::new(Box::new(move || c.lock().unwrap().now), mode, enabled);
        s.utc_offset = Box::new(move |t| offset(tz, t));
        st.lock().unwrap().now = at_tz(tz, start);
        let c = st.clone();
        s.show_is_on = Box::new(move || {
            let g = c.lock().unwrap();
            g.now < g.show_until
        });
        let c = st.clone();
        s.play = Box::new(move |what, _due| {
            let mut g = c.lock().unwrap();
            let now = g.now;
            g.shows.push((now, what.to_string()));
            g.show_until = now + 14.0;
        });
        let c = st.clone();
        s.random = Box::new(move |lo, hi| {
            let mut g = c.lock().unwrap();
            let x = if g.draws.len() > 1 { g.draws.remove(0) } else { g.draws[0] };
            lo + (hi - lo) * x
        });
        s.log = Box::new(|line| {
            if verbose() {
                println!("    {line}");
            }
        });
        s.begin();
        World { st, s, tz }
    }

    fn at(&self, text: &str) -> Time {
        at_tz(self.tz, text)
    }

    fn local(&self, t: Time) -> String {
        let s = ((t + offset(self.tz, t)).floor() as i64).rem_euclid(86400);
        format!("{:02}:{:02}:{:02}", s / 3600, s / 60 % 60, s % 60)
    }

    fn now(&self) -> Time {
        self.st.lock().unwrap().now
    }

    fn set_now(&self, t: Time) {
        self.st.lock().unwrap().now = t;
    }

    fn set_show_until(&self, t: Time) {
        self.st.lock().unwrap().show_until = t;
    }

    /// The app's timer: fires at every moment the schedule asks for (late by `late` s) until the clock reaches t.
    fn run_late(&mut self, t: Time, late: f64) {
        let mut n = 0;
        while let Some(w) = self.s.next_wake() {
            if w + late > t {
                break;
            }
            {
                let mut g = self.st.lock().unwrap();
                g.now = g.now.max(w + late);
            }
            self.s.tick();
            n += 1;
            assert!(n < 10_000, "the schedule does not move on");
        }
        self.set_now(t);
    }

    fn run(&mut self, t: &str) {
        let t = self.at(t);
        self.run_late(t, 0.0);
    }

    fn shows(&self) -> Vec<(Time, String)> {
        self.st.lock().unwrap().shows.clone()
    }

    fn show_count(&self) -> usize {
        self.st.lock().unwrap().shows.len()
    }

    fn show_times(&self) -> Vec<String> {
        self.shows().iter().map(|(t, _)| self.local(*t)).collect()
    }
}

fn strs(v: &[&str]) -> Vec<String> {
    v.iter().map(|s| s.to_string()).collect()
}

fn mac_tests() {
    test("pomodoro: Start, then work and break go round by themselves, a show at every end", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        eq!(w.s.next_wake(), None, "nothing before Start");
        w.run("12:00:00");
        eq!(w.show_count(), 0, "no show before Start");
        w.set_now(w.at("12:00:00"));
        w.s.start();
        w.run("13:00:01");
        eq!(w.show_times(), strs(&["12:25:00", "12:30:00", "12:55:00", "13:00:00"]), "shows");
        eq!(w.s.pomodoro().phase, Phase::Work, "phase");
        eq!(w.s.pomodoro().deadline, Some(w.at("13:25:00")), "the work's end");
    });

    test("pomodoro: new lengths count from the next phase; before Start at once", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.set_lengths(20, 4);
        w.s.start();
        eq!(w.s.pomodoro().deadline, Some(w.at("10:20:00")), "a length set before Start counts at once");
        w.run("10:10:00");
        w.s.set_lengths(10, 2);
        eq!(w.s.pomodoro().deadline, Some(w.at("10:20:00")), "the running work keeps its end");
        w.run("10:40:00");
        eq!(w.show_times(), strs(&["10:20:00", "10:22:00", "10:32:00", "10:34:00"]), "shows");
    });

    test("pomodoro: Pause stands the time, Resume goes on, Reset waits for Start", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.start();
        w.run("10:10:00");
        w.s.pause();
        w.run("10:17:00");
        eq!(w.s.pomodoro().run, Run::Paused, "run");
        eq!(w.s.pomodoro().left_at(w.now()), 900.0, "15 min left while paused");
        eq!(w.s.next_wake(), None, "nothing due while paused");
        w.s.resume();
        eq!(w.s.pomodoro().deadline, Some(w.at("10:32:00")), "the end after 7 min of pause");
        w.run("10:40:00");
        w.s.reset();
        eq!(w.s.pomodoro().run, Run::Ready, "run after Reset");
        eq!(w.s.pomodoro().phase, Phase::Work, "phase after Reset");
        w.run("13:00:00");
        eq!(w.show_times(), strs(&["10:32:00", "10:37:00"]), "shows (the break ended at 10:37, before Reset)");
    });

    test("switch: Off stands a running pomodoro, On lets it go on by itself; a paused one stays paused", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.start();
        w.run("10:10:00");
        w.s.set_enabled(false);
        w.run("11:10:00");
        eq!(w.show_count(), 0, "no shows while off");
        eq!(w.s.pomodoro().left_at(w.now()), 900.0, "15 min left");
        w.s.set_enabled(true);
        eq!(w.s.pomodoro().run, Run::Running, "runs again");
        w.run("11:25:00");
        eq!(w.show_times(), strs(&["11:25:00"]), "shows");
        w.s.pause();
        w.s.set_enabled(false);
        w.s.set_enabled(true);
        eq!(w.s.pomodoro().run, Run::Paused, "paused before Off: still paused after On");
        eq!(w.s.next_wake(), None, "nothing due");
    });

    test("switch: Start while off switches the app on and the work runs at once; the app's switch follows", || {
        let mut w = World::with("10:00:00", Mode::Pomodoro, Zone::Moscow, &[0.5], false);
        let told = Arc::new(AtomicUsize::new(0));
        let t = told.clone();
        w.s.switched_on = Box::new(move || {
            t.fetch_add(1, Ordering::SeqCst);
        });
        w.run("11:00:00");
        w.s.start();
        eq!(w.s.enabled(), true, "on");
        eq!(told.load(Ordering::SeqCst), 1, "the app's switch told");
        eq!(w.s.pomodoro().run, Run::Running, "runs");
        eq!(w.s.pomodoro().deadline, Some(w.at("11:25:00")), "the work's end from Start");
        w.run("11:30:01");
        eq!(w.show_times(), strs(&["11:25:00", "11:30:00"]), "shows");
        w.s.set_mode(Mode::Hourly);
        w.s.set_enabled(false);
        w.s.start();
        eq!(w.s.enabled(), false, "no Start in another mode: stays off");
        eq!(told.load(Ordering::SeqCst), 1, "nothing told");
    });

    test("switch: Resume while off switches the app on and goes on, paused before Off or only stood by it", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        let told = Arc::new(AtomicUsize::new(0));
        let t = told.clone();
        w.s.switched_on = Box::new(move || {
            t.fetch_add(1, Ordering::SeqCst);
        });
        w.s.start();
        w.run("10:10:00");
        w.s.set_enabled(false); // the panel shows it paused, with Resume
        w.run("10:30:00");
        eq!(w.show_count(), 0, "no shows while off");
        w.s.resume();
        eq!(w.s.enabled(), true, "on");
        eq!(w.s.pomodoro().run, Run::Running, "runs");
        eq!(w.s.pomodoro().deadline, Some(w.at("10:45:00")), "15 min left, from Resume");
        w.s.pause();
        w.s.set_enabled(false);
        w.run("11:00:00");
        w.s.resume();
        eq!(w.s.enabled(), true, "on again");
        eq!(w.s.pomodoro().deadline, Some(w.at("11:15:00")), "paused, then off: Resume goes on from now");
        eq!(told.load(Ordering::SeqCst), 2, "the app's switch told each time");
        w.s.resume();
        eq!(told.load(Ordering::SeqCst), 2, "Resume while on and running: nothing to do");
        w.run("11:15:01");
        eq!(w.show_times(), strs(&["11:15:00"]), "shows");
        w.s.reset();
        w.s.set_enabled(false);
        w.s.resume();
        eq!(w.s.enabled(), false, "nothing to resume after Reset: stays off");
        w.s.reset();
        eq!(w.s.enabled(), false, "Reset while off: stays off");
    });

    test("screensaver: as the lock; the pomodoro stands and goes on after it, no shows meanwhile, none of them later", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.start();
        w.run("10:20:00");
        w.s.suspend("screensaver");
        w.run("10:40:00");
        eq!(w.show_count(), 0, "the work's end (10:25) inside the screensaver: no show");
        eq!(w.s.pomodoro().left_at(w.now()), 300.0, "5 min left, standing");
        w.s.wake("screensaver");
        eq!(w.s.pomodoro().run, Run::Running, "runs");
        eq!(w.s.pomodoro().deadline, Some(w.at("10:45:00")), "goes on from its end");
        w.run("10:45:01");
        eq!(w.show_times(), strs(&["10:45:00"]), "shows");
        w.run("10:47:00");
        w.s.suspend("screens"); // the screens off without the lock: the same
        w.run("11:00:00");
        eq!(w.s.pomodoro().left_at(w.now()), 180.0, "the break stands with its 3 min");
        w.s.wake("screens");
        eq!(w.s.pomodoro().deadline, Some(w.at("11:03:00")), "and goes on");

        let mut h = World::new("10:50:00", Mode::Hourly);
        h.s.suspend("screensaver");
        h.run("12:10:00");
        h.s.wake("screensaver");
        h.run("12:59:00");
        eq!(h.show_count(), 0, "11:00 and 12:00 inside the screensaver: not played, not later");
        eq!(h.s.next_wake(), Some(h.at("13:00:00")), "every hour: the next o'clock");

        let mut r = World::new("10:00:00", Mode::Random); // 30-90 min, the draw in the middle: 11:00
        eq!(r.s.next_wake(), Some(r.at("11:00:00")), "random's moment");
        r.s.suspend("screensaver");
        r.run("11:30:00");
        r.s.wake("screensaver");
        eq!(r.show_count(), 0, "random: its moment inside the screensaver not played");
        eq!(r.s.next_wake(), Some(r.at("12:30:00")), "drawn again from its end");
    });

    test("sleep and lock: the pomodoro stands while any reason lasts and goes on after the last", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.start();
        w.run("10:20:00");
        w.s.suspend("sleep");
        w.run("10:30:00");
        w.s.suspend("lock");
        w.run("10:40:00");
        w.s.wake("sleep");
        w.run("10:45:00");
        eq!(w.s.pomodoro().deadline, None, "still locked: stands");
        w.s.wake("lock");
        eq!(w.s.pomodoro().deadline, Some(w.at("10:50:00")), "5 min left from the unlock");
        w.run("10:51:00");
        eq!(w.show_times(), strs(&["10:50:00"]), "shows");
        w.s.set_enabled(false);
        w.s.suspend("lock");
        w.s.wake("lock");
        eq!(w.s.pomodoro().deadline, None, "unlocked but off: stands");
    });

    test("every hour: on the hour; none while off or asleep, and none of those come later", || {
        let mut w = World::new("14:23:10", Mode::Hourly);
        eq!(w.s.hourly_next(), Some(w.at("15:00:00")), "the first");
        w.run("17:30:00");
        eq!(w.show_times(), strs(&["15:00:00", "16:00:00", "17:00:00"]), "shows");
        w.s.set_enabled(false);
        w.run("19:10:00");
        w.s.set_enabled(true);
        eq!(w.s.hourly_next(), Some(w.at("20:00:00")), "after On");
        w.run("20:50:00");
        w.s.suspend("sleep");
        w.run("22:05:00");
        w.s.wake("sleep");
        eq!(w.s.hourly_next(), Some(w.at("23:00:00")), "after the wake");
        w.run("23:10:00");
        eq!(w.show_times(), strs(&["15:00:00", "16:00:00", "17:00:00", "20:00:00", "23:00:00"]), "shows");
    });

    test("every hour: a timer late by 2 s still plays, a moment found an hour late (sleep without notice) does not", || {
        let mut w = World::new("14:23:10", Mode::Hourly);
        let t = w.at("15:30:00");
        w.run_late(t, 2.0);
        eq!(w.show_times(), strs(&["15:00:02"]), "the late timer");
        eq!(w.s.hourly_next(), Some(w.at("16:00:00")), "the next stays on the hour");
        w.set_now(w.at("17:05:00"));
        w.s.tick();
        eq!(w.show_count(), 1, "no show for 16:00 found at 17:05");
        eq!(w.s.hourly_next(), Some(w.at("18:00:00")), "next");
    });

    test("random: within [from, to] after the last show or the mode's start; Play now counts; a new range draws again", || {
        let mut w = World::with("10:00:00", Mode::Random, Zone::Moscow, &[0.0, 1.0, 0.5, 0.25, 0.0, 0.0], true);
        eq!(w.s.random_next(), Some(w.at("10:30:00")), "draw 0 of 30-90: 30 min after the start");
        w.run("13:01:00");
        eq!(w.show_times(), strs(&["10:30:00", "12:00:00", "13:00:00"]), "draws 1 (90 min), 0.5 (60 min)");
        eq!(w.s.random_next(), Some(w.at("13:45:00")), "draw 0.25: 45 min");
        w.set_now(w.at("13:20:00"));
        w.s.note_show("Play now");
        eq!(w.s.random_next(), Some(w.at("13:50:00")), "Play now: 30 min from it");
        w.set_now(w.at("13:30:00"));
        w.s.set_range(1, 2);
        eq!(w.s.random_next(), Some(w.at("13:31:00")), "the new range from now");
        w.s.set_range(1, 2);
        eq!(w.s.random_next(), Some(w.at("13:31:00")), "the same range: no new draw");
    });

    test("random: Off and On before its moment keep it; a moment that went by while off or asleep is drawn again", || {
        let mut w = World::with("10:00:00", Mode::Random, Zone::Moscow, &[0.5, 0.0, 0.0], true);
        eq!(w.s.random_next(), Some(w.at("11:00:00")), "60 min");
        w.run("10:10:00");
        w.s.set_enabled(false);
        w.run("10:20:00");
        w.s.set_enabled(true);
        eq!(w.s.random_next(), Some(w.at("11:00:00")), "kept");
        w.s.suspend("screens");
        w.run("11:20:00");
        w.s.wake("screens");
        eq!(w.show_count(), 0, "none while the screens slept");
        eq!(w.s.random_next(), Some(w.at("11:50:00")), "drawn from the wake: 30 min");
    });

    test("a show already on: the next one is skipped, the pomodoro's phase changes all the same", || {
        let mut w = World::new("14:00:00", Mode::Hourly);
        w.set_now(w.at("14:59:50"));
        w.set_show_until(w.at("15:00:04")); // Play now 10 s before
        w.run("16:00:30");
        eq!(w.show_times(), strs(&["16:00:00"]), "15:00 skipped");
        let mut p = World::new("10:00:00", Mode::Pomodoro);
        p.s.start();
        p.run("10:24:55");
        p.set_show_until(p.at("10:25:09"));
        p.run("10:25:30");
        eq!(p.show_count(), 0, "skipped");
        eq!(p.s.pomodoro().phase, Phase::Rest, "the break began");
        eq!(p.s.pomodoro().deadline, Some(p.at("10:30:00")), "and ends on time");
    });

    test("a new mode drops the old schedule", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.start();
        w.run("10:10:00");
        w.s.set_mode(Mode::Hourly);
        eq!(w.s.pomodoro().run, Run::Ready, "the pomodoro is reset");
        eq!(w.s.hourly_next(), Some(w.at("11:00:00")), "hourly");
        w.s.set_mode(Mode::Random);
        eq!(w.s.hourly_next(), None, "hourly dropped");
        check!(w.s.random_next().is_some(), "random drawn");
        w.s.set_mode(Mode::Pomodoro);
        eq!(w.s.random_next(), None, "random dropped");
        eq!(w.s.next_wake(), None, "the pomodoro waits for Start");
        w.s.start();
        w.s.set_mode(Mode::Pomodoro);
        eq!(w.s.pomodoro().run, Run::Running, "the same mode again changes nothing");
        w.s.set_mode(Mode::Hourly);
        w.run("12:30:00");
        eq!(w.show_times(), strs(&["11:00:00", "12:00:00"]), "shows");
    });

    test("no drift: a timer late by 0.4 s every time, 20 cycles, the ends stay on the minute", || {
        let mut w = World::new("09:00:00", Mode::Pomodoro);
        w.s.start();
        let t = w.at("19:00:01");
        w.run_late(t, 0.4);
        eq!(w.show_count(), 40, "shows");
        eq!(w.s.pomodoro().deadline, Some(w.at("19:25:00")), "the 41st end");
        check!(w.shows().iter().all(|(t, _)| ((t % 60.0) - 0.4).abs() < 1e-6), "every show 0.4 s after a whole minute");
    });

    test("every hour: summer time and a half-hour time zone", || {
        for (day, tz, name) in [("2026-10-25", Zone::Berlin, "Europe/Berlin"), ("2026-03-29", Zone::Berlin, "Europe/Berlin"),
                                ("2026-11-02", Zone::Kolkata, "Asia/Kolkata")] {
            let mut w = World::with(&format!("{day} 00:10:00"), Mode::Hourly, tz, &[0.5], true);
            let t = w.at(&format!("{day} 05:30:00"));
            w.run_late(t, 0.0);
            let shows = w.shows();
            let gaps: Vec<f64> = shows.windows(2).map(|p| p[1].0 - p[0].0).collect();
            check!(gaps.iter().all(|&g| g == 3600.0), format!("{name} {day}: hours apart, {gaps:?}"));
            let times = w.show_times();
            check!(times.iter().all(|t| t.ends_with(":00:00")), format!("{name} {day}: on the hour, {times:?}"));
        }
    });

    test("the fields: whole minutes within the range", || {
        let (lo, hi) = (1, 600);
        eq!(minutes("45", lo, hi), Some(45), "45");
        eq!(minutes(" 7 ", lo, hi), Some(7), "spaces");
        eq!(minutes("0", lo, hi), Some(1), "0");
        eq!(minutes("-5", lo, hi), Some(1), "-5");
        eq!(minutes("700", lo, hi), Some(600), "700");
        eq!(minutes("2.5", lo, hi), None, "2.5");
        eq!(minutes("abc", lo, hi), None, "abc");
        eq!(minutes("", lo, hi), None, "empty");
        eq!(mmss(1500.0), "25:00", "25:00");
        eq!(mmss(299.2), "5:00", "rounded up");
        eq!(mmss(0.4), "0:01", "the last second");
        eq!(mmss(180.0 * 60.0), "180:00", "180 min");
    });
}

/// Windows only: a full-screen game, a presentation or "do not disturb" (SHQueryUserNotificationState) skips the
/// shows of the schedule as a show already on does; the timer goes on.
fn windows_tests() {
    test("quiet (a full-screen app): the schedule's shows are skipped, the pomodoro and the hours go on", || {
        let quiet = Arc::new(Mutex::new(None::<String>));
        let mut p = World::new("10:00:00", Mode::Pomodoro);
        let q = quiet.clone();
        p.s.quiet = Box::new(move || q.lock().unwrap().clone());
        p.s.start();
        *quiet.lock().unwrap() = Some("a full-screen Direct3D app".into());
        p.run("10:26:00");
        eq!(p.show_count(), 0, "the work's end inside a game: skipped");
        eq!(p.s.pomodoro().phase, Phase::Rest, "the break began all the same");
        eq!(p.s.pomodoro().deadline, Some(p.at("10:30:00")), "and ends on time");
        *quiet.lock().unwrap() = None;
        p.run("10:30:01");
        eq!(p.show_times(), strs(&["10:30:00"]), "the game over: the next end shows");

        let mut h = World::new("14:20:00", Mode::Hourly);
        let q = quiet.clone();
        h.s.quiet = Box::new(move || q.lock().unwrap().clone());
        *quiet.lock().unwrap() = Some("presentation mode".into());
        h.run("15:30:00");
        *quiet.lock().unwrap() = None;
        h.run("16:00:01");
        eq!(h.show_times(), strs(&["16:00:00"]), "15:00 skipped, 16:00 shown");

        let mut r = World::with("10:00:00", Mode::Random, Zone::Moscow, &[0.0, 0.5], true);
        let q = quiet.clone();
        r.s.quiet = Box::new(move || q.lock().unwrap().clone());
        *quiet.lock().unwrap() = Some("a full-screen app".into());
        r.run("10:31:00");
        eq!(r.show_count(), 0, "random: skipped");
        eq!(r.s.random_next(), Some(r.at("11:30:00")), "and drawn again from its moment");
    });

    test("the scale of a sped-up clock: late_limit and the moments are the clock's, not the timer's", || {
        let mut w = World::new("10:00:00", Mode::Pomodoro);
        w.s.late_limit = 60.0 * 60.0; // TimeScale 60: a real minute late
        w.s.set_lengths(1, 1);
        w.s.start();
        let t = w.at("10:03:00");
        w.run_late(t, 30.0); // 0.5 s real at x60
        eq!(w.show_times(), strs(&["10:01:30", "10:02:30"]), "late by 30 s of the clock: shown");
        eq!(w.s.pomodoro().deadline, Some(w.at("10:03:00")), "the ends stay on the minute");
    });
}

/// The timer (driver.rs) on a real clock, sped up: what the app and the mode check run, here on the Mac.
fn timer_tests() {
    test("the timer: the mode check's script on a clock 600 times faster: all its verdicts OK", || {
        let out = check::run(600.0, |_| 3.0 * 3600.0, 1_794_000_000.0);
        if !out.ok || verbose() {
            out.lines.iter().take_while(|l| !l.starts_with("[the check's log]")).for_each(|l| println!("    {l}"));
        }
        check!(out.ok, "the mode check: ALL OK");
    });

    test("the timer: the show's window made `lead` before the moment, the show at the moment; the window dropped when \
          the moment goes", || {
        let t0 = Instant::now();
        let real = move || t0.elapsed().as_secs_f64();
        let clock = move || 1_794_000_000.0 + real() * 60.0; // a minute a second
        let ev = Arc::new(Mutex::new(Vec::<(&'static str, f64)>::new()));
        let mut s = Scheduler::new(Box::new(clock), Mode::Pomodoro, true);
        s.set_lengths(1, 1);
        let e = ev.clone();
        s.play = Box::new(move |_, _| e.lock().unwrap().push(("play", real())));
        let (e1, e2) = (ev.clone(), ev.clone());
        let hooks = Hooks {
            prepare: Box::new(move |_| e1.lock().unwrap().push(("prepare", real()))),
            drop_ready: Box::new(move || e2.lock().unwrap().push(("drop", real()))),
            changed: Box::new(|| {}),
            query: Box::new(Vec::new),
            say: Box::new(|line| if verbose() { println!("    {line}") }),
        };
        s.begin();
        let d = Driver::new(s, 60.0, 0.4, hooks);
        d.start("test-timer");
        d.with(|s| s.start()); // the work ends 1 s (real) from now: the window at 0.6 s, the show at 1.0 s
        std::thread::sleep(Duration::from_secs_f64(1.75));
        d.with(|s| s.pause()); // the break's end (2.0 s) goes: its window, made at 1.6 s, goes now
        std::thread::sleep(Duration::from_secs_f64(0.6));
        d.stop();
        let ev = ev.lock().unwrap().clone();
        let at = |name: &str, n: usize| ev.iter().filter(|e| e.0 == name).nth(n).map(|e| e.1);
        let near = |t: Option<f64>, want: f64| t.is_some_and(|t| (t - want).abs() < 0.08);
        check!(near(at("prepare", 0), 0.6), format!("the first window at 0.6 s: {ev:?}"));
        check!(near(at("play", 0), 1.0), format!("the show at 1.0 s: {ev:?}"));
        check!(near(at("prepare", 1), 1.6), format!("the second window at 1.6 s: {ev:?}"));
        check!(at("drop", 1).is_some_and(|t| t >= 1.75 && t < 1.9), format!("dropped on Pause at 1.75 s: {ev:?}"));
        eq!(ev.iter().filter(|e| e.0 == "play").count(), 1, "no show for the moment Pause took away");
    });
}

fn main() {
    mac_tests();
    let mac = (CHECKS.load(Ordering::SeqCst), FAILURES.load(Ordering::SeqCst));
    windows_tests();
    timer_tests();
    let (checks, failures) = (CHECKS.load(Ordering::SeqCst), FAILURES.load(Ordering::SeqCst));
    println!("the Mac's checks: {}/{} hold; Windows' own: {}/{} hold; all {}/{}",
             mac.0 - mac.1, mac.0, (checks - mac.0) - (failures - mac.1), checks - mac.0, checks - failures, checks);
    std::process::exit(if failures == 0 { 0 } else { 1 });
}
