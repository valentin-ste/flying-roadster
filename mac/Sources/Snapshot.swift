import AppKit
import SwiftUI

// --snapshot <dir>: the panel in every state of the three modes, on and off, and the About window, light and dark,
// rendered offscreen to PNG (2x) to compare with design/shots; the log gives each one's size in points (the panel keeps
// one height in all of them). The settings and the switch are set for the picture and put back; "Open at login" is
// drawn on, as after the install from Applications, wherever the app runs from.
@MainActor
enum Snapshot {
    static func run(_ dir: String) {
        let s = Settings.shared
        LoginItem.shared.showAsInstalled()
        let keep = (s.mode, s.enabled, s.randomFrom, s.randomTo)
        let sch = ModeTimer.shared.scheduler
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let now = ModeTimer.shared.now
        for (lookName, look) in [("light", NSAppearance.Name.aqua), ("dark", NSAppearance.Name.darkAqua)] {
            func panel(_ name: String, _ shown: Scheduler.Pomodoro? = nil) {
                let v = PanelView(onSize: { _ in }, onPlay: {}, onAbout: {}, onQuit: {}, shown: shown)
                    .environmentObject(s).environmentObject(LoginItem.shared).environmentObject(ModeTimer.shared)
                    .environmentObject(PanelClock())
                shoot(AnyView(v), look, "\(dir)/panel-\(name)-\(lookName).png")
            }
            func turn(_ on: Bool) { s.enabled = on; sch.setEnabled(on) }
            for m in Mode.allCases {
                s.mode = m
                panel(m.rawValue)
                turn(false)
                panel("\(m.rawValue)-off")       // the pomodoro: before Start
                turn(true)
            }
            (s.randomFrom, s.randomTo) = (600, 600)  // Random's longest note
            s.mode = .random
            panel("random-600")
            (s.randomFrom, s.randomTo) = (keep.2, keep.3)
            // the pomodoro's states (design/panel.html: pomo-work, paused, off), the break, and the widest line
            s.mode = .pomodoro
            sch.setMode(.pomodoro)
            sch.start()
            panel("pomodoro-work")
            sch.pause()
            panel("pomodoro-paused")
            sch.resume()
            turn(false)
            panel("pomodoro-work-off")             // a started pomodoro stands: paused, Resume
            turn(true)
            sch.reset()
            panel("pomodoro-break", Scheduler.Pomodoro(run: .running, phase: .rest, deadline: now + 299, left: 0))
            panel("pomodoro-break-paused", Scheduler.Pomodoro(run: .paused, phase: .rest, deadline: nil, left: 299))
            panel("pomodoro-widest", PanelView.widest)
            shoot(AnyView(AboutView()), look, "\(dir)/about-\(lookName).png")
        }
        (s.mode, s.enabled) = (keep.0, keep.1)
    }

    private static func shoot(_ view: AnyView, _ look: NSAppearance.Name, _ path: String) {
        let host = NSHostingView(rootView: view)
        host.appearance = NSAppearance(named: look)
        let size = host.fittingSize
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless], backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.appearance = NSAppearance(named: look)
        w.contentView = host
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
        host.cacheDisplay(in: host.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
        Log.say(String(format: "snapshot %@: %.0fx%.0f pt", (path as NSString).lastPathComponent, size.width, size.height))
    }
}
