// Roadster for Windows: a tray icon (tray.rs); a left click opens the panel (panel.rs, design v1), a right click a small
// menu (Play now, Quit; in test builds, windows/build.sh --test, also Self-test, Mode check and the tray icon's
// variants); the schedule of the three modes (modes.rs + windows/schedule), the show (show.rs). Between the panel and
// the shows no WebView2 window lives: the app is the tray icon, a timer thread and a thread for Windows' events.
#![windows_subsystem = "windows"]

mod events;
mod modes;
mod panel;
mod place;
mod settings;
mod show;
mod sys;
mod tray;

use std::sync::OnceLock;
use std::thread::ThreadId;

use tauri::menu::{CheckMenuItem, IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Wry};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

use crate::place::Rect;

/// Windows hides a new tray icon under the ^ arrow, so the panel opens by itself once, at the first launch (also the
/// first after the update from 0.1.0), to show where Roadster lives. To drop it: false.
const OPEN_PANEL_ON_FIRST_RUN: bool = true;
/// Test builds (windows/build.sh --test) have Self-test, Mode check and the icon's variants in the tray menu.
const SELFTEST: bool = option_env!("ROADSTER_SELFTEST").is_some();

static MAIN_THREAD: OnceLock<ThreadId> = OnceLock::new();

/// Every WebView2 window is made off the main thread. WebView2 finishes making a window through the main thread's
/// message loop: made ON the main thread (a synchronous command, a menu or window event handler), the window waits for
/// that loop forever and the whole app freezes - that was 0.2.0's About (made in the synchronous command panel_action:
/// the panel hid, About never came, the tray icon stopped answering). Tauri's docs say the same ("deadlocks when used
/// in a synchronous command or event handlers"). The panel and the shows are made on threads of their own; this
/// refuses, instead of freezing, if one ever is not.
pub fn assert_off_main(what: &str) -> Result<(), String> {
    if MAIN_THREAD.get() == Some(&std::thread::current().id()) {
        let e = format!("{what}: refused on the main thread (it would freeze the app)");
        modes::log(e.clone());
        return Err(e);
    }
    Ok(())
}

/// The icon variants' items (test builds), to tick the chosen one.
struct IconItems(Vec<CheckMenuItem<Wry>>);

/// Open at login, on by default (as on the Mac): switched on at the first launch; after that the panel's switch decides
/// (settings.json keeps it). Updating over 0.1.0 runs the old uninstaller, which deletes the Run value: put it back.
fn login_item(app: &AppHandle) {
    let s = panel::settings(app);
    let al = app.autolaunch();
    if !s.login_item_set_on_first_launch || (s.open_at_login && !al.is_enabled().unwrap_or(false)) {
        let _ = al.enable();
    }
    panel::update(app, |s| s.login_item_set_on_first_launch = true);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // a second launch (the Start menu, the installer's "Run"): no second icon, the panel opens
            panel::open(app, panel::Anchor::Tray, "second launch");
        }))
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, Some(vec!["--autostart"])))
        .manage(show::Shows::default())
        .invoke_handler(tauri::generate_handler![
            show::show_event,
            show::pause_capture,
            show::show_done,
            panel::panel_hello,
            panel::panel_ready,
            panel::panel_painted,
            panel::panel_set,
            panel::panel_action,
            panel::panel_bye,
            panel::open_url,
        ])
        .setup(|app| {
            let _ = MAIN_THREAD.set(std::thread::current().id());
            let file = app.path().app_config_dir().ok().map(|d| d.join("settings.json"));
            app.manage(panel::Panel::new(file));
            panel::init(app.handle());
            show::init(app.handle());
            modes::log(format!("Roadster {} ({}, built {}){}", env!("CARGO_PKG_VERSION"), env!("ROADSTER_GIT"),
                               env!("ROADSTER_BUILD_TIME"), if SELFTEST { ", test build" } else { "" }));
            modes::init(app.handle(), &panel::settings(app.handle()));
            login_item(app.handle());

            let play = MenuItem::with_id(app, "play", "Play now", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let menu = if SELFTEST {
                let test = MenuItem::with_id(app, "selftest", "Self-test", true, None::<&str>)?;
                let check = MenuItem::with_id(app, "modecheck", "Mode check (test, ~25 s)", true, None::<&str>)?;
                let now = tray::variant(app.handle());
                let items = tray::VARIANTS
                    .iter()
                    .map(|(k, t)| CheckMenuItem::with_id(app, format!("icon:{k}"), *t, true, now == *k, None::<&str>))
                    .collect::<tauri::Result<Vec<_>>>()?;
                let refs: Vec<&dyn IsMenuItem<Wry>> = items.iter().map(|i| i as &dyn IsMenuItem<Wry>).collect();
                let icons = Submenu::with_items(app, "Icon variant (test)", true, &refs)?;
                app.manage(IconItems(items));
                let sep2 = PredefinedMenuItem::separator(app)?;
                Menu::with_items(app, &[&play, &sep2, &test, &check, &icons, &sep, &quit])?
            } else {
                Menu::with_items(app, &[&play, &sep, &quit])?
            };
            TrayIconBuilder::with_id("roadster")
                .icon(tray::icon_now(app.handle()))
                .tooltip("Roadster")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "play" => {
                        panel::close(app);
                        modes::play_now(app, "tray menu");
                    }
                    "selftest" => show::selftest(app),
                    "modecheck" => modes::mode_check(app),
                    "quit" => app.exit(0),
                    id if id.starts_with("icon:") => {
                        let v = id.trim_start_matches("icon:").to_string();
                        panel::update(app, |s| s.tray_icon = v.clone());
                        for item in &app.state::<IconItems>().0 {
                            let _ = item.set_checked(item.id().as_ref() == id);
                        }
                        tray::refresh(app);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, rect, .. } = event {
                        let p = rect.position.to_physical::<i32>(1.0);
                        let s = rect.size.to_physical::<u32>(1.0);
                        let icon = Rect { x: p.x, y: p.y, w: s.width, h: s.height };
                        panel::open(tray.app_handle(), panel::Anchor::Icon(icon), "click");
                    }
                })
                .build(app)?;
            tray::refresh(app.handle());

            if OPEN_PANEL_ON_FIRST_RUN && !panel::settings(app.handle()).first_run_panel_shown {
                panel::update(app.handle(), |s| s.first_run_panel_shown = true);
                panel::open(app.handle(), panel::Anchor::Tray, "first run");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the app")
        .run(|_app, event| {
            // a tray app: the show window closing is not the end (only Quit, which gives an exit code, is)
            if let RunEvent::ExitRequested { api, code: None, .. } = event {
                api.prevent_exit();
            }
        });
}
