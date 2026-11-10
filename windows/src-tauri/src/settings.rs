// What the panel keeps, in %APPDATA%\com.valentinste.roadster\settings.json, with the Mac's UserDefaults key names
// (mac/Sources/Settings.swift); the schedule (modes.rs) follows them. As on the Mac, the pomodoro's run is not kept
// across launches (it waits for Start). TrayIcon is Windows' own (tray.rs). An older version's file: the missing keys
// take their defaults, so an install over 0.2.0 keeps everything.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(rename_all = "PascalCase", default)]
pub struct Settings {
    pub enabled: bool,
    pub mode: String, // pomodoro | hourly | random
    pub muted: bool,
    pub pomodoro_work_minutes: u32,
    pub pomodoro_break_minutes: u32,
    pub random_from_minutes: u32,
    pub random_to_minutes: u32,
    /// The Open at login switch as the user left it. An update over 0.1.0 runs the old uninstaller, which deletes the
    /// HKCU Run value: at the next launch the app puts it back when this says on (main.rs, login_item).
    pub open_at_login: bool,
    pub login_item_set_on_first_launch: bool,
    /// The panel opened by itself once, at the first launch (main.rs, OPEN_PANEL_ON_FIRST_RUN).
    pub first_run_panel_shown: bool,
    /// The tray icon's variant (tray.rs).
    pub tray_icon: String,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            enabled: true,
            mode: "pomodoro".into(),
            muted: false,
            pomodoro_work_minutes: 25,
            pomodoro_break_minutes: 5,
            random_from_minutes: 30,
            random_to_minutes: 90,
            open_at_login: true,
            login_item_set_on_first_launch: false,
            first_run_panel_shown: false,
            tray_icon: crate::tray::DEFAULT.into(),
        }
    }
}

pub const MODES: [&str; 3] = ["pomodoro", "hourly", "random"];

impl Settings {
    pub fn load(file: &Option<PathBuf>) -> Settings {
        let mut s: Settings = file
            .as_ref()
            .and_then(|f| std::fs::read_to_string(f).ok())
            .and_then(|t| serde_json::from_str(&t).ok())
            .unwrap_or_default();
        s.clean();
        s
    }

    /// Written whole to a temporary file, then renamed over the old one: a crash never leaves half a file.
    pub fn save(&self, file: &Option<PathBuf>) {
        let Some(f) = file else { return };
        if let Some(d) = f.parent() {
            let _ = std::fs::create_dir_all(d);
        }
        let tmp = f.with_extension("json.tmp");
        if let Ok(text) = serde_json::to_string_pretty(self) {
            if std::fs::write(&tmp, text + "\n").is_ok() {
                let _ = std::fs::rename(&tmp, f);
            }
        }
    }

    /// Numbers within the panel's ranges (Work 1-180, Break 1-60, Random 1-600 with from <= to), a known mode.
    pub fn clean(&mut self) {
        if !MODES.contains(&self.mode.as_str()) {
            self.mode = "pomodoro".into();
        }
        self.pomodoro_work_minutes = self.pomodoro_work_minutes.clamp(1, 180);
        self.pomodoro_break_minutes = self.pomodoro_break_minutes.clamp(1, 60);
        self.random_from_minutes = self.random_from_minutes.clamp(1, 600);
        self.random_to_minutes = self.random_to_minutes.clamp(1, 600);
        if self.random_from_minutes > self.random_to_minutes {
            self.random_to_minutes = self.random_from_minutes;
        }
    }
}
