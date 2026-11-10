// Windows' events for the schedule, the Mac's NSWorkspace notices (mac/Sources/ModeTimer.swift) in Windows terms, on a
// thread of their own with a hidden window (never shown, not in Alt+Tab) and its message loop: Windows sends these only
// to top-level windows, and the app's WebView2 windows come and go (the engine is unloaded while the panel is closed).
//
//   sleep / wake               WM_POWERBROADCAST: PBT_APMSUSPEND / PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND
//   the screens off / on       WM_POWERBROADCAST: PBT_POWERSETTINGCHANGE of GUID_CONSOLE_DISPLAY_STATE (0 off, 1 on,
//                              2 dimmed = on); Windows sends the current state at once on registering
//   the lock / unlock          WM_WTSSESSION_CHANGE: WTS_SESSION_LOCK / WTS_SESSION_UNLOCK
//   another session            WM_WTSSESSION_CHANGE: console or remote disconnect / connect
//   the screensaver            no notice of its own: on a desktop switch (a password-protected saver runs on its own
//                              desktop) or a new foreground window (any other saver) the app asks
//                              SPI_GETSCREENSAVERRUNNING; while it runs the schedule asks again every minute
//   the clock or time zone     WM_TIMECHANGE
//   theme, scale, monitors     WM_SETTINGCHANGE, WM_DISPLAYCHANGE, WM_DPICHANGED: the tray icon is picked again
//
// Nothing polls: the thread sleeps in GetMessageW until Windows sends something.

use std::sync::OnceLock;

use windows::core::w;
use windows::Win32::Foundation::{HANDLE, HWND, LPARAM, LRESULT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Power::{RegisterPowerSettingNotification, POWERBROADCAST_SETTING};
use windows::Win32::System::RemoteDesktop::{WTSRegisterSessionNotification, NOTIFY_FOR_THIS_SESSION};
use windows::Win32::System::SystemServices::GUID_CONSOLE_DISPLAY_STATE;
use windows::Win32::UI::Accessibility::{SetWinEventHook, HWINEVENTHOOK};
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW, RegisterClassW, TranslateMessage,
    DEVICE_NOTIFY_WINDOW_HANDLE, MSG, PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, PBT_APMSUSPEND,
    PBT_POWERSETTINGCHANGE, WINEVENT_OUTOFCONTEXT, WM_DISPLAYCHANGE, WM_DPICHANGED, WM_POWERBROADCAST,
    WM_SETTINGCHANGE, WM_TIMECHANGE, WM_WTSSESSION_CHANGE, WNDCLASSW, WS_EX_TOOLWINDOW, WS_POPUP,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ev {
    Suspend,
    Resume,
    ScreensOff,
    ScreensOn,
    Lock,
    Unlock,
    SessionAway,
    SessionBack,
    SaverCheck,
    TimeChanged,
    Look, // the theme, the scale or the monitors may have changed
}

static SINK: OnceLock<fn(Ev)> = OnceLock::new();

const EVENT_SYSTEM_FOREGROUND: u32 = 0x0003;
const EVENT_SYSTEM_DESKTOPSWITCH: u32 = 0x0020;
const WTS_CONSOLE_CONNECT: usize = 0x1;
const WTS_CONSOLE_DISCONNECT: usize = 0x2;
const WTS_REMOTE_CONNECT: usize = 0x3;
const WTS_REMOTE_DISCONNECT: usize = 0x4;
const WTS_SESSION_LOCK: usize = 0x7;
const WTS_SESSION_UNLOCK: usize = 0x8;

fn send(e: Ev) {
    if let Some(f) = SINK.get() {
        f(e);
    }
}

unsafe extern "system" fn wndproc(h: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    match msg {
        WM_POWERBROADCAST => {
            match wp.0 as u32 {
                PBT_APMSUSPEND => send(Ev::Suspend),
                PBT_APMRESUMEAUTOMATIC | PBT_APMRESUMESUSPEND => send(Ev::Resume),
                PBT_POWERSETTINGCHANGE if lp.0 != 0 => {
                    let s = unsafe { &*(lp.0 as *const POWERBROADCAST_SETTING) };
                    if s.PowerSetting == GUID_CONSOLE_DISPLAY_STATE && s.DataLength >= 1 {
                        send(if s.Data[0] == 0 { Ev::ScreensOff } else { Ev::ScreensOn });
                    }
                }
                _ => {}
            }
            LRESULT(1)
        }
        WM_WTSSESSION_CHANGE => {
            match wp.0 {
                WTS_SESSION_LOCK => send(Ev::Lock),
                WTS_SESSION_UNLOCK => send(Ev::Unlock),
                WTS_CONSOLE_DISCONNECT | WTS_REMOTE_DISCONNECT => send(Ev::SessionAway),
                WTS_CONSOLE_CONNECT | WTS_REMOTE_CONNECT => send(Ev::SessionBack),
                _ => {}
            }
            LRESULT(0)
        }
        WM_TIMECHANGE => {
            send(Ev::TimeChanged);
            LRESULT(0)
        }
        WM_SETTINGCHANGE | WM_DISPLAYCHANGE | WM_DPICHANGED => {
            send(Ev::Look);
            unsafe { DefWindowProcW(h, msg, wp, lp) }
        }
        _ => unsafe { DefWindowProcW(h, msg, wp, lp) },
    }
}

unsafe extern "system" fn on_win_event(_: HWINEVENTHOOK, _event: u32, _: HWND, _: i32, _: i32, _: u32, _: u32) {
    send(Ev::SaverCheck);
}

/// Starts the thread (once). The sink runs on that thread: it must not wait for the app's main thread for long.
pub fn start(sink: fn(Ev)) -> Result<(), String> {
    if SINK.set(sink).is_err() {
        return Ok(());
    }
    let (tx, rx) = std::sync::mpsc::channel::<Result<(), String>>();
    std::thread::Builder::new()
        .name("roadster-events".into())
        .spawn(move || unsafe {
            let inst = GetModuleHandleW(None).map(|m| m.into()).ok();
            let class = w!("RoadsterEvents");
            let wc = WNDCLASSW { lpfnWndProc: Some(wndproc), hInstance: inst.unwrap_or_default(), lpszClassName: class,
                                 ..Default::default() };
            RegisterClassW(&wc);
            let h = match CreateWindowExW(WS_EX_TOOLWINDOW, class, w!("Roadster events"), WS_POPUP, 0, 0, 0, 0, None,
                                          None, inst, None) {
                Ok(h) => h,
                Err(e) => {
                    let _ = tx.send(Err(format!("the events window: {e}")));
                    return;
                }
            };
            let mut problems = Vec::new();
            if let Err(e) = WTSRegisterSessionNotification(h, NOTIFY_FOR_THIS_SESSION) {
                problems.push(format!("session notices: {e}"));
            }
            if let Err(e) = RegisterPowerSettingNotification(HANDLE(h.0), &GUID_CONSOLE_DISPLAY_STATE, DEVICE_NOTIFY_WINDOW_HANDLE) {
                problems.push(format!("display notices: {e}"));
            }
            for ev in [EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_DESKTOPSWITCH] {
                if SetWinEventHook(ev, ev, None, Some(on_win_event), 0, 0, WINEVENT_OUTOFCONTEXT).0.is_null() {
                    problems.push(format!("event hook 0x{ev:04X} failed"));
                }
            }
            let _ = tx.send(if problems.is_empty() { Ok(()) } else { Err(problems.join("; ")) });
            let mut msg = MSG::default();
            while GetMessageW(&mut msg, None, 0, 0).as_bool() {
                let _ = TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
        })
        .map_err(|e| format!("the events thread: {e}"))?;
    rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap_or_else(|_| Err("the events thread did not answer".into()))
}
