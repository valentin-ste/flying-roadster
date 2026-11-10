// Where the frame goes, as in the Mac app (mac/Sources/Show.swift, showRect): the whole frame (never cropped) at the
// largest size that fits the screen, centred left to right, standing on the floor = the bottom edge of the screen
// (the car drives over the taskbar, as over the Dock on the Mac). Everything in physical pixels: the window is placed
// in them, so the DPI scale changes nothing here (the page inside sees the same rectangle in CSS px = px / scale).
//
// And where the panel goes (panel_rect): over the tray icon, at the edge of the work area on the taskbar's side.
// Checked without Windows: rustc --edition 2021 --test src/place.rs -o /tmp/place && /tmp/place --nocapture

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
}

/// The show's frame on a monitor at (mx, my) of mw x mh physical px; fw x fh = the video's frame.
pub fn show_rect(mx: i32, my: i32, mw: u32, mh: u32, fw: u32, fh: u32) -> Rect {
    let aspect = fw as f64 / fh as f64;
    let (mut w, mut h) = (mw as f64, mw as f64 / aspect);
    if h > mh as f64 {
        h = mh as f64;
        w = h * aspect;
    }
    let (w, h) = (w.round() as u32, h.round() as u32);
    Rect { x: mx + ((mw - w) as f64 / 2.0).round() as i32, y: my + (mh - h) as i32, w, h }
}

impl Rect {
    fn right(&self) -> i32 {
        self.x + self.w as i32
    }
    fn bottom(&self) -> i32 {
        self.y + self.h as i32
    }
    fn contains(&self, x: i32, y: i32) -> bool {
        x >= self.x && x < self.right() && y >= self.y && y < self.bottom()
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Edge {
    Bottom,
    Top,
    Left,
    Right,
}

/// The taskbar's edge: the side where the work area leaves the widest band of the monitor. None (an auto-hidden
/// taskbar): the edge nearest the anchor, else the bottom.
pub fn taskbar_edge(mon: Rect, work: Rect, anchor: Option<(i32, i32)>) -> Edge {
    let bands = [
        (Edge::Bottom, mon.bottom() - work.bottom()),
        (Edge::Top, work.y - mon.y),
        (Edge::Left, work.x - mon.x),
        (Edge::Right, mon.right() - work.right()),
    ];
    let (edge, band) = bands.iter().copied().max_by_key(|&(_, b)| b).unwrap();
    if band > 0 {
        return edge;
    }
    let Some((x, y)) = anchor else { return Edge::Bottom };
    [
        (Edge::Bottom, mon.bottom() - y),
        (Edge::Top, y - mon.y),
        (Edge::Left, x - mon.x),
        (Edge::Right, mon.right() - x),
    ]
    .into_iter()
    .min_by_key(|&(_, d)| d)
    .unwrap()
    .0
}

/// Is a point on the taskbar (between the work area and the monitor's edge on the taskbar's side)? An auto-hidden
/// taskbar leaves no band: then within 1/8 of the monitor from that edge. An icon hidden under the ^ arrow reports a
/// rectangle in the overflow window over the work area, or nothing: that is no anchor.
pub fn on_taskbar(mon: Rect, work: Rect, edge: Edge, (x, y): (i32, i32)) -> bool {
    if !mon.contains(x, y) {
        return false;
    }
    let (band_start, depth) = match edge {
        Edge::Bottom => (mon.bottom() - y, mon.bottom() - work.bottom()),
        Edge::Top => (y - mon.y, work.y - mon.y),
        Edge::Left => (x - mon.x, work.x - mon.x),
        Edge::Right => (mon.right() - x, mon.right() - work.right()),
    };
    let reach = if depth > 0 { depth } else { (mon.h.min(mon.w) / 8) as i32 };
    band_start <= reach
}

fn clamp(v: i32, lo: i32, hi: i32) -> i32 {
    if hi < lo { lo } else { v.max(lo).min(hi) }
}

/// The panel (w x h physical px) on the monitor `mon` with the work area `work`: on the taskbar's side, `gap` px from
/// the work area's edge (0 on Windows 10, whose flyouts sit on the taskbar; 12 px x scale on Windows 11), centred on
/// the anchor (the tray icon's centre) along the taskbar and kept `gap` px inside the work area. No anchor on the
/// taskbar: the end of the taskbar where the clock and the tray are (the right end, or the bottom of a side taskbar).
pub fn panel_rect(mon: Rect, work: Rect, anchor: Option<(i32, i32)>, w: u32, h: u32, gap: i32) -> (Rect, Edge) {
    let edge = taskbar_edge(mon, work, anchor);
    let (cx, cy) = match anchor.filter(|&a| on_taskbar(mon, work, edge, a)) {
        Some(a) => a,
        None => match edge {
            Edge::Bottom | Edge::Top => (work.right(), 0),
            Edge::Left | Edge::Right => (0, work.bottom()),
        },
    };
    let (wi, hi) = (w as i32, h as i32);
    let along_x = clamp(cx - wi / 2, work.x + gap, work.right() - gap - wi);
    let along_y = clamp(cy - hi / 2, work.y + gap, work.bottom() - gap - hi);
    let (x, y) = match edge {
        Edge::Bottom => (along_x, work.bottom() - gap - hi),
        Edge::Top => (along_x, work.y + gap),
        Edge::Right => (work.right() - gap - wi, along_y),
        Edge::Left => (work.x + gap, along_y),
    };
    (Rect { x, y, w, h }, edge)
}

/// The panel's size in physical px for a scale: 344 x 506 CSS px, the Mac panel's points (design/panel.html).
pub const PANEL_CSS: (f64, f64) = (344.0, 506.0);

pub fn panel_size(scale: f64) -> (u32, u32) {
    ((PANEL_CSS.0 * scale).round() as u32, (PANEL_CSS.1 * scale).round() as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FW: u32 = 2016;
    const FH: u32 = 1310;

    #[test]
    fn valentins_monitor_and_others() {
        // (monitor px, scale): the scale only changes what the page sees in CSS px
        for &(mw, mh, scale) in &[(1920u32, 1200u32, 1.0f64), (1920, 1200, 1.25), (1920, 1200, 1.5), (1920, 1080, 1.0),
                                   (2560, 1440, 1.25), (3840, 2160, 1.5), (1280, 1024, 1.0)] {
            let r = show_rect(0, 0, mw, mh, FW, FH);
            println!(
                "{mw}x{mh} @{:.0}%: window {}x{} px at ({}, {}), {:.1}x{:.1} CSS px, {:.4} screen px per frame px, empty {} px left/right, {} px above",
                scale * 100.0, r.w, r.h, r.x, r.y, r.w as f64 / scale, r.h as f64 / scale,
                r.h as f64 / FH as f64, r.x, r.y
            );
            assert!(r.w <= mw && r.h <= mh);
            assert_eq!(r.y as u32 + r.h, mh, "the floor is the bottom edge");
            assert!((r.x as i64 * 2 + r.w as i64 - mw as i64).abs() <= 1, "centred");
            assert!(r.w == mw || r.h == mh, "the largest that fits");
            let a = r.w as f64 / r.h as f64;
            assert!((a - FW as f64 / FH as f64).abs() < 0.002, "the frame's proportions");
        }
        assert_eq!(show_rect(0, 0, 1920, 1200, FW, FH), Rect { x: 37, y: 0, w: 1847, h: 1200 });
        assert_eq!(show_rect(0, 0, 1920, 1080, FW, FH), Rect { x: 129, y: 0, w: 1662, h: 1080 });
        // a narrow screen: full width, standing on the floor
        assert_eq!(show_rect(0, 0, 1280, 1024, FW, FH), Rect { x: 0, y: 192, w: 1280, h: 832 });
        // a primary monitor not at (0, 0) of the desktop
        assert_eq!(show_rect(-1920, 100, 1920, 1200, FW, FH), Rect { x: -1883, y: 100, w: 1847, h: 1200 });
    }

    fn r(x: i32, y: i32, w: u32, h: u32) -> Rect {
        Rect { x, y, w, h }
    }

    /// Valentin's monitor (1920x1200) with the taskbar at the bottom, the top and the right, at 100% (taskbar 40 px,
    /// tray icon 24x40) and 125% (50 px, as in his self-test; icon 30x50), on Windows 10 (gap 0) and 11 (gap 12 px).
    #[test]
    fn panel_over_the_tray_icon() {
        let mon = r(0, 0, 1920, 1200);
        for &scale in &[1.0f64, 1.25] {
            let (w, h) = panel_size(scale);
            let bar = (40.0 * scale) as i32;
            let icon = ((24.0 * scale) as i32, (40.0 * scale) as i32); // icon w x h on a horizontal taskbar
            for &(gap_css, os) in &[(0, "Windows 10"), (12, "Windows 11")] {
                let gap = (gap_css as f64 * scale).round() as i32;
                // bottom: the icon 300 px from the right end
                let work = r(0, 0, 1920, 1200 - bar as u32);
                let ic = r(1920 - 300, 1200 - bar, icon.0 as u32, icon.1 as u32);
                let a = (ic.x + ic.w as i32 / 2, ic.y + ic.h as i32 / 2);
                let (p, e) = panel_rect(mon, work, Some(a), w, h, gap);
                println!("{os} {:.0}%, taskbar bottom {bar} px, icon centre {a:?}: panel {}x{} at ({}, {}), {:?}",
                         scale * 100.0, p.w, p.h, p.x, p.y, e);
                assert_eq!(e, Edge::Bottom);
                assert_eq!(p.bottom(), work.bottom() - gap, "on the taskbar, gap above it");
                assert!((p.x + w as i32 / 2 - a.0).abs() <= 1 || p.right() == work.right() - gap, "over the icon");
                assert!(p.right() <= work.right() - gap && p.x >= gap);
                // bottom, the icon at the very right end: the panel stops `gap` px from the screen's edge
                let a2 = (1920 - 12, 1200 - bar / 2);
                let (p2, _) = panel_rect(mon, work, Some(a2), w, h, gap);
                assert_eq!(p2.right(), 1920 - gap);
                // top
                let work = r(0, bar, 1920, 1200 - bar as u32);
                let a = (1920 - 300 + icon.0 / 2, bar / 2);
                let (p, e) = panel_rect(mon, work, Some(a), w, h, gap);
                println!("{os} {:.0}%, taskbar top {bar} px, icon centre {a:?}: panel {}x{} at ({}, {}), {:?}",
                         scale * 100.0, p.w, p.h, p.x, p.y, e);
                assert_eq!(e, Edge::Top);
                assert_eq!(p.y, bar + gap, "under the taskbar");
                // right: a side taskbar is wider (62 px at 100%), the tray icons near its bottom
                let side = (62.0 * scale) as i32;
                let work = r(0, 0, 1920 - side as u32, 1200);
                let a = (1920 - side / 2, 1200 - (80.0 * scale) as i32);
                let (p, e) = panel_rect(mon, work, Some(a), w, h, gap);
                println!("{os} {:.0}%, taskbar right {side} px, icon centre {a:?}: panel {}x{} at ({}, {}), {:?}",
                         scale * 100.0, p.w, p.h, p.x, p.y, e);
                assert_eq!(e, Edge::Right);
                assert_eq!(p.right(), 1920 - side - gap, "left of the taskbar");
                assert_eq!(p.bottom(), 1200 - gap, "the icon is low: the panel stops at the work area's bottom");
                // left
                let work = r(side, 0, 1920 - side as u32, 1200);
                let (p, e) = panel_rect(mon, work, Some((side / 2, 1200 - 100)), w, h, gap);
                assert_eq!((e, p.x), (Edge::Left, side + gap));
            }
        }
        assert_eq!(panel_size(1.0), (344, 506));
        assert_eq!(panel_size(1.25), (430, 633));
        assert_eq!(panel_size(1.5), (516, 759));
    }

    #[test]
    fn panel_without_an_anchor() {
        let mon = r(0, 0, 1920, 1200);
        let work = r(0, 0, 1920, 1150);
        let (w, h) = panel_size(1.25);
        // an icon under the ^ arrow: its rectangle is in the overflow window over the work area -> the tray's end
        for a in [None, Some((1700, 900)), Some((5000, 5000))] {
            let (p, e) = panel_rect(mon, work, a, w, h, 0);
            assert_eq!((e, p.right(), p.bottom()), (Edge::Bottom, 1920, 1150), "{a:?}");
        }
        // auto-hidden taskbar (no band): the edge nearest the icon
        let (p, e) = panel_rect(mon, mon, Some((1700, 1190)), w, h, 0);
        assert_eq!((e, p.bottom()), (Edge::Bottom, 1200));
        let (p, e) = panel_rect(mon, mon, Some((1910, 600)), w, h, 0);
        assert_eq!((e, p.right()), (Edge::Right, 1920));
        // a second monitor left of the primary, taskbar at its bottom
        let mon2 = r(-1920, 0, 1920, 1080);
        let work2 = r(-1920, 0, 1920, 1040);
        let (p, _) = panel_rect(mon2, work2, Some((-1000, 1060)), 344, 506, 0);
        assert_eq!(p, r(-1172, 534, 344, 506));
    }
}
