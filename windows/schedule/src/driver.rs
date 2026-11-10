//! The timer that drives a Scheduler on a real clock (the app's: windows/src-tauri/src/modes.rs; the mode check's;
//! the tests'): one wait for the next thing due - the show's window `lead` real seconds before a moment, the moment
//! itself, or a minute while something stands the schedule - on a condition variable, then round again; set again
//! whenever anything changes (`with`). No polling. Pure Rust, no Windows: tests/schedule.rs runs it on the Mac too.

use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use crate::{Scheduler, Time};

/// While something stands the schedule (sleep, the lock, the screensaver...), the timer asks again this often whether
/// it still does, so a missed notice cannot stand it for good (as on the Mac).
pub const AWAY_RECHECK_S: f64 = 60.0;

pub struct Hooks {
    /// A show's window for the moment, made now (hidden).
    pub prepare: Box<dyn Fn(Time) + Send + Sync>,
    /// The window made for a moment that will not show (the moment went, the show was skipped).
    pub drop_ready: Box<dyn Fn() + Send + Sync>,
    /// The state changed (the panel, if open, shows it).
    pub changed: Box<dyn Fn() + Send + Sync>,
    /// What Windows says about the reasons it can be asked about.
    pub query: Box<dyn Fn() -> Vec<(&'static str, bool)> + Send + Sync>,
    pub say: Box<dyn Fn(String) + Send + Sync>,
}

#[derive(Default, Clone)]
pub struct Stats {
    pub fires: u32,
    pub late_ms: Vec<f64>, // the timer's lateness, ms, the last 100
    pub prepared: u32,
    pub dropped: u32,
}

struct Core {
    s: Scheduler,
    gen: u64,
    prepared_for: Option<Time>,
    stop: bool,
    stats: Stats,
}

pub struct Driver {
    core: Mutex<Core>,
    cv: Condvar,
    /// The schedule's clock runs this many times faster than real time (1 in the app; 60 in the mode check).
    pub scale: f64,
    lead: f64,
    hooks: Hooks,
}

impl Driver {
    pub fn new(s: Scheduler, scale: f64, lead: f64, hooks: Hooks) -> Arc<Driver> {
        Arc::new(Driver { core: Mutex::new(Core { s, gen: 0, prepared_for: None, stop: false, stats: Stats::default() }),
                          cv: Condvar::new(), scale, lead, hooks })
    }

    pub fn start(self: &Arc<Driver>, name: &str) {
        let d = self.clone();
        let _ = std::thread::Builder::new().name(name.into()).spawn(move || d.run());
    }

    pub fn stop(&self) {
        self.core.lock().unwrap().stop = true;
        self.cv.notify_all();
    }

    /// Something for the scheduler (a button, a setting, an event); the timer is set again.
    pub fn with<T>(&self, f: impl FnOnce(&mut Scheduler) -> T) -> T {
        let r = {
            let mut g = self.core.lock().unwrap();
            let r = f(&mut g.s);
            g.gen += 1;
            r
        };
        self.cv.notify_all();
        (self.hooks.changed)();
        r
    }

    pub fn read<T>(&self, f: impl FnOnce(&Scheduler, &Stats) -> T) -> T {
        let g = self.core.lock().unwrap();
        f(&g.s, &g.stats)
    }

    pub fn away(&self, why: &str) {
        self.with(|s| s.suspend(why));
    }

    /// Any of these means the PC is awake; the reasons that can be asked about are asked again, so a missed notice
    /// cannot stand the schedule until the next launch (as on the Mac).
    pub fn back(&self, why: &str) {
        let q = (self.hooks.query)();
        self.with(|s| {
            s.wake(why);
            s.wake("sleep");
            for (w, on) in q {
                if !on {
                    s.wake(w);
                }
            }
        });
    }

    /// The timer: one wait for the next thing due (the show's window SHOW_LEAD_S before a moment, the moment itself,
    /// or a minute while something stands the schedule), then round again; set again whenever anything changes.
    fn run(self: Arc<Driver>) {
        let mut g = self.core.lock().unwrap();
        loop {
            if g.stop {
                return;
            }
            let gen = g.gen;
            let due = g.s.next_wake();
            if g.prepared_for.is_some() && g.prepared_for != due {
                g.prepared_for = None;
                g.stats.dropped += 1;
                (self.hooks.drop_ready)();
            }
            let now = g.s.now();
            let wait = match due {
                Some(t) => {
                    let to_due = (t - now) / self.scale;
                    if self.lead > 0.0 && g.prepared_for.is_none() && to_due > 0.0 && to_due <= self.lead {
                        g.prepared_for = Some(t);
                        g.stats.prepared += 1;
                        (self.hooks.prepare)(t);
                        continue;
                    }
                    if self.lead > 0.0 && g.prepared_for.is_none() && to_due > self.lead {
                        Some(to_due - self.lead)
                    } else {
                        Some(to_due.max(0.0))
                    }
                }
                None if g.s.asleep() => Some(AWAY_RECHECK_S),
                None => None,
            };
            let timed_out = match wait {
                Some(w) if w > 0.0005 => {
                    let (g2, r) = self.cv.wait_timeout(g, Duration::from_secs_f64(w)).unwrap();
                    g = g2;
                    r.timed_out()
                }
                Some(_) => true,
                None => {
                    g = self.cv.wait(g).unwrap();
                    false
                }
            };
            if g.stop {
                return;
            }
            if g.gen != gen || !timed_out {
                continue;
            }
            let now = g.s.now();
            match due {
                Some(t) if now < t => continue, // the window's moment, or a wake a hair early: round again
                Some(t) => {
                    let late = (now - t) / self.scale * 1000.0;
                    g.stats.fires += 1;
                    g.stats.late_ms.push(late);
                    if g.stats.late_ms.len() > 100 {
                        g.stats.late_ms.remove(0);
                    }
                    (self.hooks.say)(format!("timer: {late:.1} ms after the moment"));
                }
                None => {}
            }
            if g.s.asleep() {
                for (w, on) in (self.hooks.query)() {
                    if !on && g.s.has_reason(w) {
                        g.s.wake(w);
                    }
                }
            }
            g.s.tick();
            if g.prepared_for.is_some() && g.prepared_for == due {
                g.prepared_for = None; // taken by the show, or the show was skipped: then it goes
                (self.hooks.drop_ready)();
            }
            drop(g);
            (self.hooks.changed)();
            g = self.core.lock().unwrap();
        }
    }
}

