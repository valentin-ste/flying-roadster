//! The schedule of the three modes without Windows: when the car comes, on a clock it is handed. A port of the Mac's
//! mac/Sources/Schedule.swift, case for case. The app drives it (windows/src-tauri/src/modes.rs: one timer at the
//! next moment, the panel's buttons, the switch, sleep, the lock, the screensaver, the screens); the tests
//! (tests/schedule.rs, the Mac's mac/Tests/ScheduleTests.swift; windows/build.sh runs them before every build) drive it
//! with a clock of their own. Every moment is a time on that clock, never a sum of timer intervals: a late timer or a
//! sleeping PC moves nothing.
//!
//! One thing the Mac has not: `quiet` - Windows says a full-screen game, a presentation or "do not disturb" is on, and
//! a show of the schedule is skipped as when a show is already on (the pomodoro's phase changes all the same).

use std::collections::BTreeSet;

pub mod check;
pub mod driver;

/// Seconds since 1970-01-01 UTC on the scheduler's clock (real time in the app; the tests' own clock).
pub type Time = f64;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    Pomodoro,
    Hourly,
    Random,
}

impl Mode {
    pub const ALL: [Mode; 3] = [Mode::Pomodoro, Mode::Hourly, Mode::Random];
    /// The settings' name (settings.json, the Mac's UserDefaults).
    pub fn key(self) -> &'static str {
        match self {
            Mode::Pomodoro => "pomodoro",
            Mode::Hourly => "hourly",
            Mode::Random => "random",
        }
    }
    pub fn from_key(k: &str) -> Option<Mode> {
        Mode::ALL.into_iter().find(|m| m.key() == k)
    }
    pub fn title(self) -> &'static str {
        match self {
            Mode::Pomodoro => "Pomodoro",
            Mode::Hourly => "Every hour",
            Mode::Random => "Random",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Phase {
    Work,
    Rest,
}

impl Phase {
    pub fn title(self) -> &'static str {
        match self {
            Phase::Work => "Work",
            Phase::Rest => "Break",
        }
    }
    pub fn key(self) -> &'static str {
        match self {
            Phase::Work => "work",
            Phase::Rest => "rest",
        }
    }
}

/// What Start, Pause, Resume and Reset asked for.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Run {
    Ready,
    Running,
    Paused,
}

impl Run {
    pub fn key(self) -> &'static str {
        match self {
            Run::Ready => "ready",
            Run::Running => "running",
            Run::Paused => "paused",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Pomodoro {
    pub run: Run,
    pub phase: Phase,
    /// The phase's end while its time runs.
    pub deadline: Option<Time>,
    /// The time left while it stands (Pause; Off, sleep or the lock).
    pub left: f64,
}

impl Default for Pomodoro {
    fn default() -> Self {
        Pomodoro { run: Run::Ready, phase: Phase::Work, deadline: None, left: 0.0 }
    }
}

impl Pomodoro {
    pub fn left_at(&self, now: Time) -> f64 {
        self.deadline.map(|d| (d - now).max(0.0)).unwrap_or(self.left)
    }
}

pub struct Scheduler {
    pub clock: Box<dyn Fn() -> Time + Send>,
    /// The local clock's offset from UTC at a moment, in seconds (the time zone and summer time): o'clock, the log.
    pub utc_offset: Box<dyn Fn(Time) -> f64 + Send>,
    /// A moment found later than this went by in a sleep nobody announced: no show.
    pub late_limit: f64,
    pub random: Box<dyn FnMut(f64, f64) -> f64 + Send>,
    pub show_is_on: Box<dyn Fn() -> bool + Send>,
    /// Why a show of the schedule is not wanted now (Windows: a full-screen game, a presentation); None: show it.
    pub quiet: Box<dyn Fn() -> Option<String> + Send>,
    /// The show: what it is and the moment it was due.
    pub play: Box<dyn FnMut(&str, Time) + Send>,
    pub log: Box<dyn FnMut(String) + Send>,
    /// Start or Resume turned the app on: its switch follows.
    pub switched_on: Box<dyn FnMut() + Send>,

    mode: Mode,
    enabled: bool,
    work_minutes: u32, // a new length counts from the next phase
    break_minutes: u32,
    random_from: u32,
    random_to: u32,
    reasons: BTreeSet<String>, // why nobody would see the car: sleep, screens, screensaver, lock, session
    pomodoro: Pomodoro,
    hourly_next: Option<Time>,
    random_next: Option<Time>,
}

impl Scheduler {
    pub fn new(clock: Box<dyn Fn() -> Time + Send>, mode: Mode, enabled: bool) -> Scheduler {
        Scheduler {
            clock,
            utc_offset: Box::new(|_| 0.0),
            late_limit: 60.0,
            random: Box::new(|lo, hi| lo + (hi - lo) * pseudo_random()),
            show_is_on: Box::new(|| false),
            quiet: Box::new(|| None),
            play: Box::new(|_, _| {}),
            log: Box::new(|_| {}),
            switched_on: Box::new(|| {}),
            mode,
            enabled,
            work_minutes: 25,
            break_minutes: 5,
            random_from: 30,
            random_to: 90,
            reasons: BTreeSet::new(),
            pomodoro: Pomodoro::default(),
            hourly_next: None,
            random_next: None,
        }
    }

    pub fn mode(&self) -> Mode {
        self.mode
    }
    pub fn enabled(&self) -> bool {
        self.enabled
    }
    pub fn pomodoro(&self) -> Pomodoro {
        self.pomodoro
    }
    pub fn hourly_next(&self) -> Option<Time> {
        self.hourly_next
    }
    pub fn random_next(&self) -> Option<Time> {
        self.random_next
    }
    pub fn reasons(&self) -> Vec<String> {
        self.reasons.iter().cloned().collect()
    }
    pub fn has_reason(&self, why: &str) -> bool {
        self.reasons.contains(why)
    }
    pub fn lengths(&self) -> (u32, u32) {
        (self.work_minutes, self.break_minutes)
    }
    pub fn asleep(&self) -> bool {
        !self.reasons.is_empty()
    }
    pub fn blocked(&self) -> bool {
        !self.enabled || self.asleep()
    }
    pub fn now(&self) -> Time {
        (self.clock)()
    }

    /// The next moment something is due (the app sets its timer to it); None: nothing comes until something changes.
    pub fn next_wake(&self) -> Option<Time> {
        if self.blocked() {
            return None;
        }
        match self.mode {
            Mode::Pomodoro => self.pomodoro.deadline,
            Mode::Hourly => self.hourly_next,
            Mode::Random => self.random_next,
        }
    }

    /// The app's start: the pomodoro waits for Start (nothing is kept across launches), the others count from now.
    pub fn begin(&mut self) {
        let line = format!("schedule: mode {}, switch {}", self.mode.key(), if self.enabled { "on" } else { "off" });
        self.say(line);
        self.set_up();
    }

    pub fn set_lengths(&mut self, work: u32, rest: u32) {
        if (work, rest) == (self.work_minutes, self.break_minutes) {
            return;
        }
        self.work_minutes = work;
        self.break_minutes = rest;
        let tail = if self.pomodoro.run == Run::Ready { "" } else { ", from the next phase" };
        self.say(format!("pomodoro: {work} + {rest} min{tail}"));
    }

    pub fn set_range(&mut self, from: u32, to: u32) {
        if (from, to) == (self.random_from, self.random_to) {
            return;
        }
        self.random_from = from;
        self.random_to = to;
        if self.mode == Mode::Random {
            let now = self.now();
            self.draw(now, "new range");
        }
    }

    /// A new mode drops the old one's schedule.
    pub fn set_mode(&mut self, m: Mode) {
        if m == self.mode {
            return;
        }
        self.tick();
        self.say(format!("mode: {} -> {}", self.mode.key(), m.key()));
        self.mode = m;
        self.pomodoro = Pomodoro::default();
        self.hourly_next = None;
        self.random_next = None;
        self.set_up();
    }

    /// The switch in the panel: Off stops the shows and stands the pomodoro; On brings back what was there.
    pub fn set_enabled(&mut self, on: bool) {
        if on == self.enabled {
            return;
        }
        self.tick();
        let was = self.blocked();
        self.enabled = on;
        self.say(format!("switch: {}", if on { "on" } else { "off" }));
        self.block_changed(was);
    }

    /// Sleep, the screens' sleep, the screensaver, the lock, another user's session: no shows meanwhile, the pomodoro
    /// stands; a moment that went by meanwhile is not played later.
    pub fn suspend(&mut self, why: &str) {
        if self.reasons.contains(why) {
            return;
        }
        self.tick();
        let was = self.blocked();
        self.reasons.insert(why.to_string());
        let all = self.reasons_text();
        self.say(format!("away: {why} ({all})"));
        self.block_changed(was);
    }

    pub fn wake(&mut self, why: &str) {
        if !self.reasons.contains(why) {
            return;
        }
        let was = self.blocked();
        self.reasons.remove(why);
        let tail = if self.reasons.is_empty() { String::new() } else { format!(" (still away: {})", self.reasons_text()) };
        self.say(format!("back: {why}{tail}"));
        self.block_changed(was);
    }

    /// The pomodoro's buttons. Start and Resume while off switch the app on (Valentin, 02.11): no greyed buttons.
    pub fn start(&mut self) {
        self.tick();
        if self.mode != Mode::Pomodoro || self.pomodoro.run != Run::Ready {
            return;
        }
        self.switch_on("Start");
        self.pomodoro = Pomodoro { run: Run::Running, phase: Phase::Work, deadline: None, left: self.length(Phase::Work) };
        let tail = if self.blocked() { " (stands until back)" } else { "" };
        self.say(format!("pomodoro: Start, work {} min{tail}", self.work_minutes));
        self.sync_pomodoro();
    }

    pub fn pause(&mut self) {
        self.tick();
        if self.pomodoro.run != Run::Running {
            return;
        }
        self.pomodoro.run = Run::Paused;
        self.say("pomodoro: Pause".into());
        self.sync_pomodoro();
    }

    /// Off shows a started pomodoro as paused: Resume then goes on with it whether it was paused or not.
    pub fn resume(&mut self) {
        self.tick();
        if !(self.pomodoro.run == Run::Paused || (self.pomodoro.run == Run::Running && !self.enabled)) {
            return;
        }
        self.switch_on("Resume");
        if self.pomodoro.run == Run::Paused {
            self.pomodoro.run = Run::Running;
            self.say("pomodoro: Resume".into());
        }
        self.sync_pomodoro();
    }

    pub fn reset(&mut self) {
        self.tick();
        if self.pomodoro.run == Run::Ready {
            return;
        }
        self.pomodoro = Pomodoro::default();
        self.say("pomodoro: Reset, waits for Start".into());
    }

    /// A show that did not come from the schedule (Play now): Random counts its minutes from the last show.
    pub fn note_show(&mut self, what: &str) {
        if self.mode != Mode::Random {
            return;
        }
        let now = self.now();
        self.draw(now, &format!("after {what}"));
    }

    /// The clock was set or the time zone changed: the next o'clock is found again.
    pub fn clock_changed(&mut self) {
        let Some(h) = self.hourly_next.filter(|_| self.mode == Mode::Hourly) else { return };
        let n = self.next_hour(self.now());
        if n == h {
            return;
        }
        self.hourly_next = Some(n);
        let t = self.hm(n);
        self.say(format!("hourly: the clock changed, next show at {t}"));
    }

    /// What is due now comes: the app calls it when its timer fires, the tests when their clock gets there.
    pub fn tick(&mut self) {
        if self.blocked() {
            return;
        }
        let now = self.now();
        match self.mode {
            Mode::Pomodoro => {
                let Some(due) = self.pomodoro.deadline else { return };
                if self.pomodoro.run != Run::Running || now < due {
                    return;
                }
                let ended = self.pomodoro.phase;
                let next = if ended == Phase::Work { Phase::Rest } else { Phase::Work };
                let len = self.length(next);
                let mut end = due + len; // from the moment, not from the late timer: no drift
                if end <= now {
                    end = now + len;
                }
                self.pomodoro.phase = next;
                self.pomodoro.deadline = Some(end);
                let line = format!("pomodoro: {} is over, {} {} until {}", ended.title().to_lowercase(),
                                   next.title().to_lowercase(), mmss(len), self.hms(end));
                self.say(line);
                self.show(&format!("pomodoro, {} over", ended.title().to_lowercase()), due, now);
            }
            Mode::Hourly => {
                let Some(due) = self.hourly_next else { return };
                if now < due {
                    return;
                }
                let n = self.next_hour(now);
                self.hourly_next = Some(n);
                let what = format!("hourly, {}", self.hm(due));
                self.show(&what, due, now);
                let line = format!("hourly: next show at {}", self.hm(n));
                self.say(line);
            }
            Mode::Random => {
                let Some(due) = self.random_next else { return };
                if now < due {
                    return;
                }
                self.show("random", due, now);
                self.draw(now, "after the last one");
            }
        }
    }

    /// The start of the next hour on the local clock (after a change of the time zone or of summer time as well).
    pub fn next_hour(&self, t: Time) -> Time {
        let off = (self.utc_offset)(t);
        ((t + off) / 3600.0).floor() * 3600.0 - off + 3600.0
    }

    // ---- private ----

    fn say(&mut self, line: String) {
        (self.log)(line);
    }

    fn reasons_text(&self) -> String {
        self.reasons.iter().cloned().collect::<Vec<_>>().join(", ")
    }

    fn set_up(&mut self) {
        let now = self.now();
        let later = if self.blocked() { " (once on)" } else { "" };
        match self.mode {
            Mode::Pomodoro => {
                let line = format!("pomodoro: ready, waits for Start ({} + {} min)", self.work_minutes, self.break_minutes);
                self.say(line);
            }
            Mode::Hourly => {
                let n = self.next_hour(now);
                self.hourly_next = Some(n);
                let line = format!("hourly: next show at {}{later}", self.hm(n));
                self.say(line);
            }
            Mode::Random => self.draw(now, &format!("mode on{later}")),
        }
    }

    fn switch_on(&mut self, by: &str) {
        if self.enabled {
            return;
        }
        self.say(format!("{by} while off: the switch goes on"));
        self.set_enabled(true);
        (self.switched_on)();
    }

    fn block_changed(&mut self, was: bool) {
        let now = self.now();
        self.sync_pomodoro();
        if was == self.blocked() {
            return;
        }
        if self.blocked() {
            let why = if self.enabled { "away" } else { "off" };
            self.say(format!("shows: stopped ({why})"));
            return;
        }
        match self.mode {
            Mode::Pomodoro => {}
            Mode::Hourly => {
                if let Some(h) = self.hourly_next.filter(|&h| h <= now) {
                    let line = format!("hourly: {} went by meanwhile, not played", self.hm(h));
                    self.say(line);
                }
                let n = self.next_hour(now);
                self.hourly_next = Some(n);
                let line = format!("hourly: next show at {}", self.hm(n));
                self.say(line);
            }
            Mode::Random => {
                if self.random_next.is_some_and(|r| r > now) {
                    self.say("random: the next moment is still ahead, kept".into());
                } else {
                    if self.random_next.is_some() {
                        self.say("random: its moment went by meanwhile, not played".into());
                    }
                    self.draw(now, "back");
                }
            }
        }
    }

    /// The pomodoro's time runs only while it is running and nothing stands it.
    fn sync_pomodoro(&mut self) {
        let now = self.now();
        let runs = self.mode == Mode::Pomodoro && self.pomodoro.run == Run::Running && !self.blocked();
        let name = self.pomodoro.phase.title().to_lowercase();
        if runs && self.pomodoro.deadline.is_none() {
            let end = now + self.pomodoro.left;
            self.pomodoro.deadline = Some(end);
            let line = format!("pomodoro: {name} runs, {} left, until {}", mmss(self.pomodoro.left), self.hms(end));
            self.say(line);
        } else if !runs {
            if let Some(end) = self.pomodoro.deadline {
                self.pomodoro.left = (end - now).max(0.0);
                self.pomodoro.deadline = None;
                let line = format!("pomodoro: {name} stands, {} left", mmss(self.pomodoro.left));
                self.say(line);
            }
        }
    }

    fn show(&mut self, what: &str, due: Time, now: Time) {
        let late = now - due;
        if late > self.late_limit {
            self.say(format!("show: {what}: not played, found {late:.0} s after its moment (an unannounced sleep?)"));
        } else if (self.show_is_on)() {
            self.say(format!("show: {what}: skipped, a show is on"));
        } else if let Some(why) = (self.quiet)() {
            self.say(format!("show: {what}: skipped, {why}"));
        } else {
            self.say(format!("show: {what} ({late:.3} s after its moment)"));
            (self.play)(what, due);
        }
    }

    fn draw(&mut self, now: Time, why: &str) {
        let lo = self.random_from.min(self.random_to) as f64;
        let hi = self.random_from.max(self.random_to) as f64;
        let m = (self.random)(lo, hi);
        let at = now + m * 60.0;
        self.random_next = Some(at);
        let line = format!("random: next in {m:.2} min ({}-{}), at {}, {why}", self.random_from, self.random_to, self.hms(at));
        self.say(line);
    }

    fn length(&self, p: Phase) -> f64 {
        (if p == Phase::Work { self.work_minutes } else { self.break_minutes }) as f64 * 60.0
    }

    /// HH:MM:SS / HH:MM on the local clock.
    pub fn hms(&self, t: Time) -> String {
        let s = ((t + (self.utc_offset)(t)).floor() as i64).rem_euclid(86400);
        format!("{:02}:{:02}:{:02}", s / 3600, s / 60 % 60, s % 60)
    }
    pub fn hm(&self, t: Time) -> String {
        self.hms(t)[..5].to_string()
    }
}

/// Whole minutes typed into a field, kept within the range; None for anything else (the field goes back).
pub fn minutes(text: &str, lo: i64, hi: i64) -> Option<i64> {
    let t = text.trim();
    let digits = t.strip_prefix(['+', '-']).unwrap_or(t);
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let n: i64 = t.parse().unwrap_or(if t.starts_with('-') { i64::MIN } else { i64::MAX });
    Some(n.clamp(lo, hi))
}

/// 25:00, 4:59, 0:01: whole seconds rounded up, so a phase shows its full length at its start.
pub fn mmss(t: f64) -> String {
    let s = t.max(0.0).ceil() as i64;
    format!("{}:{:02}", s / 60, s % 60)
}

/// A draw in 0..1 for Random without a crate: the clock's nanoseconds through splitmix64.
fn pseudo_random() -> f64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    static STATE: AtomicU64 = AtomicU64::new(0);
    let seed = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(1);
    let mut z = STATE.fetch_add(0x9E37_79B9_7F4A_7C15, Ordering::Relaxed).wrapping_add(seed);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    (z >> 11) as f64 / (1u64 << 53) as f64
}
