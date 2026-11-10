// Win32 bits Tauri does not give: the overlay's window styles and z-order (and the shell events that tell when the
// taskbar may have come over it), the panel's place and the clicks outside it, the theme, the clock's format, links in
// the browser, screen pixels for the self-test, the Windows version, CPU times and memory.

use std::mem::size_of;
use std::sync::atomic::{AtomicIsize, Ordering};
use std::sync::OnceLock;

use windows::core::{w, HSTRING, PCWSTR};
use windows::Win32::Foundation::{CloseHandle, FILETIME, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::Globalization::{GetTimeFormatEx, TIME_NOSECONDS};
use windows::Win32::Graphics::Dwm::{DwmSetWindowAttribute, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND};
use windows::Win32::Graphics::Gdi::{
    BitBlt, ClientToScreen, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC, GetDIBits,
    ReleaseDC, SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, CAPTUREBLT, DIB_RGB_COLORS, SRCCOPY,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::ProcessStatus::{GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS, PROCESS_MEMORY_COUNTERS_EX};
use windows::Win32::System::SystemInformation::GetLocalTime;
use windows::Win32::System::Threading::{
    GetCurrentProcessId, GetProcessTimes, GetSystemTimes, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_VM_READ,
};
use windows::Win32::UI::Accessibility::{SetWinEventHook, UnhookWinEvent, HWINEVENTHOOK};
use windows::Win32::UI::Shell::ShellExecuteW;
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, FindWindowExW, FindWindowW, GetClientRect, GetWindow, GetWindowLongPtrW, GetWindowRect,
    SetForegroundWindow, SetWindowLongPtrW, SetWindowPos, SetWindowsHookExW, ShowWindow, UnhookWindowsHookEx, GWL_EXSTYLE, GW_HWNDPREV, HC_ACTION, HHOOK,
    HWND_TOPMOST, MSLLHOOKSTRUCT, SWP_ASYNCWINDOWPOS, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOOWNERZORDER,
    SWP_NOSIZE, SWP_NOZORDER, SWP_SHOWWINDOW, SW_HIDE, SW_SHOWNORMAL, WH_MOUSE_LL, WINEVENT_OUTOFCONTEXT,
    WINEVENT_SKIPOWNPROCESS, WM_LBUTTONDOWN, WM_MBUTTONDOWN, WM_RBUTTONDOWN, WS_EX_APPWINDOW, WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
};

use crate::place::Rect;

fn hwnd(h: isize) -> HWND {
    HWND(h as *mut core::ffi::c_void)
}

/// The show window as an overlay, after Tauri set it up hidden (transparent, no frame, no shadow, topmost, not
/// focusable = WS_EX_NOACTIVATE, clicks through = WS_EX_TRANSPARENT | WS_EX_LAYERED): a tool window (no taskbar button,
/// not in Alt+Tab), placed in physical px and shown without taking the focus. Tao recomputes the styles whenever one
/// of its own setters runs, so nothing of tao's may change the window's style after this.
pub fn make_overlay(h: isize, r: Rect) -> Result<(), String> {
    unsafe {
        let w = hwnd(h);
        let ex = GetWindowLongPtrW(w, GWL_EXSTYLE) as u32;
        let ex = (ex | WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0 | WS_EX_TOPMOST.0) & !WS_EX_APPWINDOW.0;
        SetWindowLongPtrW(w, GWL_EXSTYLE, ex as isize);
        SetWindowPos(w, Some(HWND_TOPMOST), r.x, r.y, r.w as i32, r.h as i32,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED)
            .map_err(|e| format!("SetWindowPos: {e}"))
    }
}

pub fn ex_style(h: isize) -> u32 {
    unsafe { GetWindowLongPtrW(hwnd(h), GWL_EXSTYLE) as u32 }
}

/// The window just above `h` in the z-order that is the taskbar, if the taskbar is above `h`.
fn taskbar_above(h: isize) -> Option<HWND> {
    unsafe {
        let bar = FindWindowW(w!("Shell_TrayWnd"), None).ok()?;
        let mut cur = hwnd(h);
        for _ in 0..512 {
            match GetWindow(cur, GW_HWNDPREV) {
                Ok(prev) if !prev.0.is_null() => {
                    if prev == bar {
                        return Some(bar);
                    }
                    cur = prev;
                }
                _ => return None,
            }
        }
        None
    }
}

pub fn is_taskbar_above(h: isize) -> bool {
    taskbar_above(h).is_some()
}

/// The taskbar is topmost too and comes to the top of the topmost band when it is clicked: then the show goes back
/// over it (as the Mac's statusBar level is always over the Dock), placed right above the taskbar, so open menus and
/// the Start menu that came up with it stay over the car. Returns true when it had to move the window.
pub fn keep_over_taskbar(h: isize) -> bool {
    let Some(bar) = taskbar_above(h) else { return false };
    unsafe {
        // SetWindowPos puts a window under hWndInsertAfter: under the window that is over the taskbar, or at the top
        let after = match GetWindow(bar, GW_HWNDPREV) {
            Ok(w) if !w.0.is_null() => w,
            _ => HWND_TOPMOST,
        };
        let _ = SetWindowPos(hwnd(h), Some(after), 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS);
    }
    true
}

// The shell events after which the taskbar may be over the show: something came to the foreground (the taskbar, the
// Start menu, a window), a menu opened or closed, the mouse was captured or let go (a click on the taskbar that is
// already in front). Out of context: the calls come to the main thread's message loop, only when such a thing happens.
static WIN_EVENT_HOOK: AtomicIsize = AtomicIsize::new(0);
static WIN_EVENT_SINK: OnceLock<fn(u32)> = OnceLock::new();
pub const EVENT_FIRST: u32 = 0x0003; // EVENT_SYSTEM_FOREGROUND
pub const EVENT_LAST: u32 = 0x0009; // EVENT_SYSTEM_CAPTUREEND

pub fn event_name(e: u32) -> &'static str {
    match e {
        3 => "foreground",
        4 => "menu start",
        5 => "menu end",
        6 => "popup menu start",
        7 => "popup menu end",
        8 => "capture start",
        9 => "capture end",
        _ => "event",
    }
}

unsafe extern "system" fn on_win_event(_: HWINEVENTHOOK, event: u32, _: HWND, _: i32, _: i32, _: u32, _: u32) {
    if let Some(f) = WIN_EVENT_SINK.get() {
        f(event);
    }
}

/// On the main thread (the hook calls back on the thread that set it, through its message loop).
pub fn watch_shell_events(sink: fn(u32)) -> Result<(), String> {
    let _ = WIN_EVENT_SINK.set(sink);
    if WIN_EVENT_HOOK.load(Ordering::SeqCst) != 0 {
        return Ok(());
    }
    let h = unsafe {
        SetWinEventHook(EVENT_FIRST, EVENT_LAST, None, Some(on_win_event), 0, 0,
                        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
    };
    if h.0.is_null() {
        return Err("SetWinEventHook failed".into());
    }
    WIN_EVENT_HOOK.store(h.0 as isize, Ordering::SeqCst);
    Ok(())
}

/// On the main thread, as watch_shell_events.
pub fn unwatch_shell_events() {
    let h = WIN_EVENT_HOOK.swap(0, Ordering::SeqCst);
    if h != 0 {
        unsafe {
            let _ = UnhookWinEvent(HWINEVENTHOOK(h as *mut core::ffi::c_void));
        }
    }
}

// Clicks anywhere while the panel is open (a low-level mouse hook, only while it is open): a click outside closes it
// even when Windows did not give it the focus (so no focus loss would come).
static MOUSE_HOOK: AtomicIsize = AtomicIsize::new(0);
static MOUSE_SINK: OnceLock<fn(i32, i32)> = OnceLock::new();

unsafe extern "system" fn on_mouse(code: i32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    if code == HC_ACTION as i32 && matches!(wp.0 as u32, WM_LBUTTONDOWN | WM_RBUTTONDOWN | WM_MBUTTONDOWN) {
        let m = unsafe { &*(lp.0 as *const MSLLHOOKSTRUCT) };
        if let Some(f) = MOUSE_SINK.get() {
            f(m.pt.x, m.pt.y);
        }
    }
    unsafe { CallNextHookEx(None, code, wp, lp) }
}

/// On the main thread (a low-level hook calls back on the thread that set it).
pub fn watch_clicks(sink: fn(i32, i32)) {
    let _ = MOUSE_SINK.set(sink);
    if MOUSE_HOOK.load(Ordering::SeqCst) != 0 {
        return;
    }
    unsafe {
        let module = GetModuleHandleW(PCWSTR::null()).ok().map(|m| m.into());
        if let Ok(h) = SetWindowsHookExW(WH_MOUSE_LL, Some(on_mouse), module, 0) {
            MOUSE_HOOK.store(h.0 as isize, Ordering::SeqCst);
        }
    }
}

pub fn unwatch_clicks() {
    let h = MOUSE_HOOK.swap(0, Ordering::SeqCst);
    if h != 0 {
        unsafe {
            let _ = UnhookWindowsHookEx(HHOOK(h as *mut core::ffi::c_void));
        }
    }
}

/// The panel as a flyout: a tool window (no taskbar button, not in Alt+Tab) with the system's rounded corners on
/// Windows 11 (asked for explicitly: Windows does not round every kind of window by itself; Windows 10 ignores it).
/// Shown and hidden by panel_show / panel_hide only, never by tao's setters, which would rewrite the styles.
pub fn make_flyout(h: isize) {
    unsafe {
        let w = hwnd(h);
        let ex = GetWindowLongPtrW(w, GWL_EXSTYLE) as u32;
        SetWindowLongPtrW(w, GWL_EXSTYLE, ((ex | WS_EX_TOOLWINDOW.0) & !WS_EX_APPWINDOW.0) as isize);
        let round = DWMWCP_ROUND;
        let _ = DwmSetWindowAttribute(w, DWMWA_WINDOW_CORNER_PREFERENCE, &round as *const _ as *const core::ffi::c_void,
                                      std::mem::size_of_val(&round) as u32);
        let _ = SetWindowPos(w, None, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    }
}

/// Shows the panel on top and gives it the focus; false if Windows kept the focus elsewhere.
pub fn panel_show(h: isize) -> bool {
    unsafe {
        let w = hwnd(h);
        let _ = SetWindowPos(w, Some(HWND_TOPMOST), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        SetForegroundWindow(w).as_bool()
    }
}

pub fn panel_hide(h: isize) {
    unsafe {
        let _ = ShowWindow(hwnd(h), SW_HIDE);
    }
}

/// Puts a window's client area (what the page fills) at `r` in physical px. An undecorated window with a shadow keeps
/// invisible resize borders around its client area (tao), so the window's own rectangle is larger by them.
pub fn place_client(h: isize, r: Rect) -> Result<(), String> {
    unsafe {
        let w = hwnd(h);
        let (mut wr, mut cr, mut tl) = (RECT::default(), RECT::default(), POINT::default());
        GetWindowRect(w, &mut wr).map_err(|e| format!("GetWindowRect: {e}"))?;
        GetClientRect(w, &mut cr).map_err(|e| format!("GetClientRect: {e}"))?;
        let _ = ClientToScreen(w, &mut tl);
        let (l, t) = (tl.x - wr.left, tl.y - wr.top);
        let (rt, b) = (wr.right - (tl.x + cr.right), wr.bottom - (tl.y + cr.bottom));
        SetWindowPos(w, None, r.x - l, r.y - t, r.w as i32 + l + rt, r.h as i32 + t + b,
                     SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER)
            .map_err(|e| format!("SetWindowPos: {e}"))
    }
}

/// The client area in screen px.
pub fn client_rect(h: isize) -> Option<Rect> {
    unsafe {
        let w = hwnd(h);
        let (mut cr, mut tl) = (RECT::default(), POINT::default());
        GetClientRect(w, &mut cr).ok()?;
        let _ = ClientToScreen(w, &mut tl);
        Some(Rect { x: tl.x, y: tl.y, w: cr.right as u32, h: cr.bottom as u32 })
    }
}

/// The notification area of the taskbar (the tray icons, the ^ arrow and the clock): where the panel goes when the
/// icon's own rectangle is not known (the icon is hidden under the ^ arrow).
pub fn notify_area() -> Option<Rect> {
    unsafe {
        let bar = FindWindowW(w!("Shell_TrayWnd"), None).ok()?;
        let tray = FindWindowExW(Some(bar), None, w!("TrayNotifyWnd"), None).ok()?;
        window_rect(tray.0 as isize).filter(|r| r.w > 0 && r.h > 0)
    }
}

/// Windows' "app mode" (Settings > Personalization > Colors): AppsUseLightTheme 0 = dark.
pub fn apps_dark() -> bool {
    windows_registry::CURRENT_USER
        .open(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        .and_then(|k| k.get_u32("AppsUseLightTheme"))
        .map(|v| v == 0)
        .unwrap_or(false)
}

/// The next whole hour in the user's time format (17:00, 5:00 PM), as the Mac's DateFormatter .short.
pub fn next_hour_text() -> String {
    unsafe {
        let mut t = GetLocalTime();
        t.wHour = (t.wHour + 1) % 24;
        t.wMinute = 0;
        t.wSecond = 0;
        t.wMilliseconds = 0;
        let mut buf = [0u16; 64];
        let n = GetTimeFormatEx(PCWSTR::null(), TIME_NOSECONDS, Some(&t), PCWSTR::null(), Some(&mut buf));
        if n > 1 {
            String::from_utf16_lossy(&buf[..(n - 1) as usize])
        } else {
            format!("{}:00", t.wHour)
        }
    }
}

/// A link in the default browser.
pub fn open_url(url: &str) {
    let u = HSTRING::from(url);
    unsafe {
        ShellExecuteW(None, w!("open"), PCWSTR(u.as_ptr()), PCWSTR::null(), PCWSTR::null(), SW_SHOWNORMAL);
    }
}

pub fn window_rect(h: isize) -> Option<Rect> {
    let mut r = RECT::default();
    unsafe { GetWindowRect(hwnd(h), &mut r).ok()? };
    Some(Rect { x: r.left, y: r.top, w: (r.right - r.left) as u32, h: (r.bottom - r.top) as u32 })
}

/// Screen pixels of a rectangle (virtual-screen physical px) as BGRA rows, through GDI: BitBlt from the screen DC
/// reads what DWM composed (CAPTUREBLT adds layered windows).
pub fn capture(r: Rect) -> Result<Vec<u8>, String> {
    unsafe {
        let screen = GetDC(None);
        if screen.is_invalid() {
            return Err("GetDC failed".into());
        }
        let mem = CreateCompatibleDC(Some(screen));
        let bmp = CreateCompatibleBitmap(screen, r.w as i32, r.h as i32);
        let old = SelectObject(mem, bmp.into());
        let blt = BitBlt(mem, 0, 0, r.w as i32, r.h as i32, Some(screen), r.x, r.y, SRCCOPY | CAPTUREBLT);
        let mut bi = BITMAPINFO::default();
        bi.bmiHeader = BITMAPINFOHEADER {
            biSize: size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: r.w as i32,
            biHeight: -(r.h as i32),
            biPlanes: 1,
            biBitCount: 32,
            biCompression: BI_RGB.0,
            ..Default::default()
        };
        let mut buf = vec![0u8; r.w as usize * r.h as usize * 4];
        SelectObject(mem, old);
        let lines = GetDIBits(mem, bmp, 0, r.h, Some(buf.as_mut_ptr() as *mut _), &mut bi, DIB_RGB_COLORS);
        let _ = DeleteObject(bmp.into());
        let _ = DeleteDC(mem);
        ReleaseDC(None, screen);
        blt.map_err(|e| format!("BitBlt: {e}"))?;
        if lines != r.h as i32 {
            return Err(format!("GetDIBits returned {lines} of {} lines", r.h));
        }
        Ok(buf)
    }
}

/// The build number (22000 and up is Windows 11).
pub fn windows_build() -> u32 {
    windows_registry::LOCAL_MACHINE
        .open(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
        .and_then(|k| k.get_string("CurrentBuildNumber"))
        .ok()
        .and_then(|b| b.parse().ok())
        .unwrap_or(0)
}

/// "Windows 11 Pro 24H2, build 26100.2314" from the registry (ProductName says Windows 10 on 11: build >= 22000 is 11).
pub fn windows_version() -> String {
    let Ok(k) = windows_registry::LOCAL_MACHINE.open(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") else {
        return "unknown (registry)".into();
    };
    let s = |n: &str| k.get_string(n).unwrap_or_default();
    let build = s("CurrentBuildNumber");
    let ubr = k.get_u32("UBR").map(|u| format!(".{u}")).unwrap_or_default();
    let mut name = s("ProductName");
    if build.parse::<u32>().unwrap_or(0) >= 22000 {
        name = name.replace("Windows 10", "Windows 11");
    }
    format!("{name} {}, build {build}{ubr}", s("DisplayVersion"))
}

fn ft(f: FILETIME) -> u64 {
    ((f.dwHighDateTime as u64) << 32) | f.dwLowDateTime as u64
}

/// CPU time of this process and every process under it (WebView2's browser, GPU, renderer, audio...), in 100 ns, the
/// number of processes, and the whole system's busy and total times.
#[derive(Clone, Copy, Debug)]
pub struct Cpu {
    pub tree: u64,
    pub procs: usize,
    pub sys_busy: u64,
    pub sys_total: u64,
    pub at: std::time::Instant,
}

/// This process and every WebView2 process under it (the browser, GPU, renderer, audio...).
fn tree_pids() -> Vec<u32> {
    unsafe {
        let me = GetCurrentProcessId();
        let mut all: Vec<(u32, u32)> = Vec::new();
        if let Ok(snap) = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) {
            let mut e = PROCESSENTRY32W { dwSize: size_of::<PROCESSENTRY32W>() as u32, ..Default::default() };
            if Process32FirstW(snap, &mut e).is_ok() {
                loop {
                    // WebView2's processes only (a Notepad the self-test opened is our child too)
                    let n = e.szExeFile.iter().position(|&c| c == 0).unwrap_or(e.szExeFile.len());
                    let name = String::from_utf16_lossy(&e.szExeFile[..n]).to_ascii_lowercase();
                    if name == "msedgewebview2.exe" || e.th32ProcessID == me {
                        all.push((e.th32ProcessID, e.th32ParentProcessID));
                    }
                    if Process32NextW(snap, &mut e).is_err() {
                        break;
                    }
                }
            }
            let _ = CloseHandle(snap);
        }
        let mut ours = vec![me];
        let mut i = 0;
        while i < ours.len() {
            let p = ours[i];
            for &(pid, parent) in &all {
                if parent == p && pid != p && !ours.contains(&pid) {
                    ours.push(pid);
                }
            }
            i += 1;
        }
        ours
    }
}

pub fn cpu() -> Cpu {
    let at = std::time::Instant::now();
    let (mut tree, mut procs) = (0u64, 0usize);
    unsafe {
        for pid in tree_pids() {
            if let Ok(h) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
                let (mut c, mut x, mut k, mut u) = Default::default();
                if GetProcessTimes(h, &mut c, &mut x, &mut k, &mut u).is_ok() {
                    tree += ft(k) + ft(u);
                    procs += 1;
                }
                let _ = CloseHandle(h);
            }
        }
        let (mut idle, mut kern, mut user) = Default::default();
        let _ = GetSystemTimes(Some(&mut idle), Some(&mut kern), Some(&mut user));
        let total = ft(kern) + ft(user); // kernel time includes idle
        Cpu { tree, procs, sys_busy: total.saturating_sub(ft(idle)), sys_total: total, at }
    }
}

/// Memory of the same process tree: private bytes (commit, what Task Manager calls "Memory" is close to the private
/// working set) and the working set, in bytes.
#[derive(Clone, Copy, Debug, Default)]
pub struct Mem {
    pub private: u64,
    pub working: u64,
    pub procs: usize,
}

pub fn mem() -> Mem {
    let mut m = Mem::default();
    unsafe {
        for pid in tree_pids() {
            let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, false, pid)
                .or_else(|_| OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid));
            if let Ok(h) = h {
                let mut c = PROCESS_MEMORY_COUNTERS_EX { cb: size_of::<PROCESS_MEMORY_COUNTERS_EX>() as u32, ..Default::default() };
                if GetProcessMemoryInfo(h, &mut c as *mut _ as *mut PROCESS_MEMORY_COUNTERS, c.cb).is_ok() {
                    m.private += c.PrivateUsage as u64;
                    m.working += c.WorkingSetSize as u64;
                    m.procs += 1;
                }
                let _ = CloseHandle(h);
            }
        }
    }
    m
}

// ---- round 2: the modes' clock and what stands the schedule ----

/// The local clock's offset from UTC at a moment (seconds since 1970 UTC), with that moment's summer time: what the
/// schedule's o'clock and its log go by (Schedule's utc_offset). Windows' own time zone rules, no database of our own.
pub fn utc_offset(t: f64) -> f64 {
    use windows::Win32::Foundation::SYSTEMTIME;
    use windows::Win32::System::Time::{FileTimeToSystemTime, SystemTimeToFileTime, SystemTimeToTzSpecificLocalTime};
    const EPOCH_1601: f64 = 11_644_473_600.0;
    let whole = t.floor();
    let ticks = ((whole + EPOCH_1601) * 1e7) as u64;
    let src = FILETIME { dwLowDateTime: ticks as u32, dwHighDateTime: (ticks >> 32) as u32 };
    unsafe {
        let (mut utc, mut local, mut back) = (SYSTEMTIME::default(), SYSTEMTIME::default(), FILETIME::default());
        if FileTimeToSystemTime(&src, &mut utc).is_err()
            || SystemTimeToTzSpecificLocalTime(None, &utc, &mut local).is_err()
            || SystemTimeToFileTime(&local, &mut back).is_err()
        {
            return 0.0;
        }
        (ft(back) as f64 - ticks as f64) / 1e7
    }
}

/// The reasons Windows can be asked about (at launch and after any return, so a missed notice cannot stand the
/// schedule): the lock (the session's flag), another session on the screen, the screensaver running.
pub fn query_away() -> Vec<(&'static str, bool)> {
    use windows::core::PWSTR;
    use windows::Win32::System::RemoteDesktop::{
        ProcessIdToSessionId, WTSActive, WTSFreeMemory, WTSQuerySessionInformationW, WTSSessionInfoEx, WTSINFOEXW,
        WTS_CURRENT_SESSION,
    };
    let mut out = Vec::new();
    unsafe {
        let mut id = WTS_CURRENT_SESSION;
        let _ = ProcessIdToSessionId(GetCurrentProcessId(), &mut id); // WTSSessionInfoEx wants the session's own id
        let (mut buf, mut n) = (PWSTR::null(), 0u32);
        if WTSQuerySessionInformationW(None, id, WTSSessionInfoEx, &mut buf, &mut n).is_ok() && !buf.is_null() {
            let info = &*(buf.0 as *const WTSINFOEXW);
            if info.Level == 1 {
                let l1 = info.Data.WTSInfoExLevel1;
                out.push(("lock", l1.SessionFlags == 0)); // WTS_SESSIONSTATE_LOCK 0, UNLOCK 1, unknown -1
                out.push(("session", l1.SessionState != WTSActive));
            }
            WTSFreeMemory(buf.0 as *mut core::ffi::c_void);
        }
    }
    out.push(("screensaver", screensaver_running()));
    out
}

pub fn screensaver_running() -> bool {
    use windows::Win32::UI::WindowsAndMessaging::{SystemParametersInfoW, SPI_GETSCREENSAVERRUNNING, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS};
    let mut on = windows::core::BOOL(0);
    unsafe {
        let _ = SystemParametersInfoW(SPI_GETSCREENSAVERRUNNING, 0, Some(&mut on as *mut _ as *mut core::ffi::c_void),
                                      SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0));
    }
    on.as_bool()
}

/// Why Windows asks apps to keep quiet now (SHQueryUserNotificationState: what it holds its own notifications for),
/// None when it would show them. modes.rs skips the schedule's shows then (SKIP_WHEN_QUIET); Play now always plays.
pub fn quiet() -> Option<String> {
    use windows::Win32::UI::Shell::{
        SHQueryUserNotificationState, QUNS_APP, QUNS_BUSY, QUNS_NOT_PRESENT, QUNS_PRESENTATION_MODE, QUNS_QUIET_TIME,
        QUNS_RUNNING_D3D_FULL_SCREEN,
    };
    let s = unsafe { SHQueryUserNotificationState() }.ok()?;
    let why = match s {
        QUNS_RUNNING_D3D_FULL_SCREEN => "a full-screen Direct3D app (a game) is on",
        QUNS_BUSY => "a full-screen app is on (a game, a video in full screen) or the presentation settings",
        QUNS_PRESENTATION_MODE => "presentation mode is on",
        QUNS_APP => "a full-screen Store app is on",
        QUNS_QUIET_TIME => "Windows' quiet time (the first hour after an upgrade)",
        QUNS_NOT_PRESENT => "nobody at the screen (Windows says: locked, screensaver or another user)",
        _ => return None,
    };
    Some(why.to_string())
}

/// What SHQueryUserNotificationState says now, for the report.
pub fn notification_state() -> String {
    match unsafe { windows::Win32::UI::Shell::SHQueryUserNotificationState() } {
        Ok(s) => format!("{} ({})", s.0, quiet().unwrap_or_else(|| "accepts notifications".into())),
        Err(e) => format!("unknown ({e})"),
    }
}

/// The tray icon's slot: Windows' small icon at the taskbar's DPI (16 px at 100%, 20 at 125%, 24 at 150%...).
pub fn tray_slot() -> (u32, u32) {
    use windows::Win32::UI::HiDpi::{GetDpiForSystem, GetDpiForWindow, GetSystemMetricsForDpi};
    use windows::Win32::UI::WindowsAndMessaging::SM_CXSMICON;
    unsafe {
        let bar = FindWindowW(w!("Shell_TrayWnd"), None).ok();
        let dpi = bar.map(|b| GetDpiForWindow(b)).filter(|&d| d > 0).unwrap_or_else(|| GetDpiForSystem());
        let px = GetSystemMetricsForDpi(SM_CXSMICON, dpi);
        (if px > 0 { px as u32 } else { (16 * dpi + 48) / 96 }, dpi)
    }
}

/// Windows' "mode" for the taskbar and the Start menu (SystemUsesLightTheme 1 = light), not the apps'.
pub fn taskbar_light() -> bool {
    windows_registry::CURRENT_USER
        .open(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        .and_then(|k| k.get_u32("SystemUsesLightTheme"))
        .map(|v| v == 1)
        .unwrap_or(false)
}

/// The local time of a moment as HH:MM:SS.mmm, for the logs.
pub fn local_stamp(t: f64) -> String {
    let l = t + utc_offset(t);
    let ms = ((l - l.floor()) * 1000.0) as u32;
    let s = (l.floor() as i64).rem_euclid(86400);
    format!("{:02}:{:02}:{:02}.{ms:03}", s / 3600, s / 60 % 60, s % 60)
}

/// The processes of the app's tree right now (1 = only the app: WebView2 is gone).
pub fn tree_count() -> usize {
    tree_pids().len()
}
