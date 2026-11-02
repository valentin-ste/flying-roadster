import AppKit
import SwiftUI

// The panel under the menu bar icon (design/panel.html): a borderless panel that takes the keyboard (the minute
// fields) without bringing the app forward, closes on Esc, on a click elsewhere and on a second click on the icon.

final class FloatingPanel: NSPanel {
    var onCancel: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override func cancelOperation(_ sender: Any?) { onCancel?() }
}

@MainActor
final class PanelController: NSObject, NSWindowDelegate {
    private let statusItem: NSStatusItem
    private let panel: FloatingPanel
    private let host: NSHostingView<AnyView>
    private var clickMonitor: Any?
    private var closedAt = Date.distantPast
    private let clock = PanelClock()
    private var ticker: Timer?

    init(statusItem: NSStatusItem) {
        self.statusItem = statusItem
        panel = FloatingPanel(contentRect: NSRect(x: 0, y: 0, width: 344, height: 480),
                              styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: true)
        host = NSHostingView(rootView: AnyView(EmptyView()))
        super.init()
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .popUpMenu
        panel.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary, .transient, .ignoresCycle]
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.animationBehavior = .utilityWindow
        panel.delegate = self
        panel.onCancel = { [weak self] in self?.close() }
        host.rootView = makeView(onSize: { [weak self] in self?.fit($0) })
        host.sizingOptions = []          // the panel's frame is ours: anchored at the top, see fit()
        panel.contentView = host
    }

    private func makeView(onSize: @escaping (CGSize) -> Void) -> AnyView {
        AnyView(PanelView(
            onSize: onSize,
            onPlay: { [weak self] in self?.play() },
            onAbout: { [weak self] in
                self?.close()
                AboutWindow.shared.show()
            },
            onQuit: { NSApp.terminate(nil) })
            .environmentObject(Settings.shared)
            .environmentObject(LoginItem.shared)
            .environmentObject(ModeTimer.shared)
            .environmentObject(clock))
    }

    // the panel's size for what it shows now (the hosting view itself has no size until it is laid out)
    private func measure() -> CGSize {
        NSHostingController(rootView: makeView(onSize: { _ in })).sizeThatFits(in: CGSize(width: 344, height: 4000))
    }

    func toggle() {
        if panel.isVisible { close() } else if Date().timeIntervalSince(closedAt) > 0.3 { open() }
    }

    func open() {
        LoginItem.shared.refresh()
        clock.now = ModeTimer.shared.now
        guard place(measure()) else { return }
        panel.makeKeyAndOrderFront(nil)
        panel.invalidateShadow()
        statusItem.button?.highlight(true)
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in self?.close() }
        }
        tick()
    }

    // the countdown and "Next show at" live while the panel is open: a tick on each of the pomodoro's whole seconds
    private func tick() {
        ticker?.invalidate()
        clock.now = ModeTimer.shared.now
        ticker = Timer.scheduledTimer(withTimeInterval: ModeTimer.shared.nextFlip(), repeats: false) { [weak self] _ in
            Task { @MainActor in if self?.panel.isVisible == true { self?.tick() } }
        }
    }

    func close() {
        guard panel.isVisible else { return }
        NotificationCenter.default.post(name: MinutesField.commitNote, object: nil)   // a number being typed is kept
        panel.makeFirstResponder(nil)
        ticker?.invalidate()
        ticker = nil
        panel.orderOut(nil)
        statusItem.button?.highlight(false)
        closedAt = Date()
        if let m = clickMonitor { NSEvent.removeMonitor(m) }
        clickMonitor = nil
    }

    func windowDidResignKey(_ n: Notification) { close() }

    // The panel's frame: its top 6 pt under the menu bar, under the icon, within the screen. The top is found from the
    // icon every time, never from the panel's last frame: the panel never moves up.
    private func place(_ size: CGSize) -> Bool {
        guard let bw = statusItem.button?.window else { return false }
        let r = bw.frame
        let sf = (bw.screen ?? NSScreen.main ?? NSScreen.screens[0]).frame
        let x = max(sf.minX + 8, min(r.minX, sf.maxX - 8 - size.width))
        panel.setFrame(NSRect(x: x, y: r.minY - 6 - size.height, width: size.width, height: size.height), display: true)
        Log.say(String(format: "panel: %.0fx%.0f pt, top-left (%.0f, %.0f) from the screen's top-left, the icon at x %.0f-%.0f",
                       size.width, size.height, x - sf.minX, sf.maxY - (r.minY - 6), r.minX - sf.minX, r.maxX - sf.minX))
        return true
    }

    // The content keeps one height in every mode and state (PanelView); should it ever ask for another, the top stays.
    private func fit(_ size: CGSize) {
        guard panel.isVisible, size.height > 0 else { return }
        let f = panel.frame
        guard abs(f.height - size.height) > 0.5 || abs(f.width - size.width) > 0.5 else { return }
        Log.say("panel: the content asks for another size")
        if place(size) { panel.invalidateShadow() }
    }

    private func play() {
        let screen = statusItem.button?.window?.screen
        close()
        ModeTimer.shared.playNow(on: screen)
    }
}

@MainActor
final class PanelClock: ObservableObject {
    @Published var now = Date()
}

private struct SizeKey: PreferenceKey {
    static var defaultValue: CGSize = .zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) { value = nextValue() }
}

struct PanelView: View {
    let onSize: (CGSize) -> Void
    let onPlay: () -> Void
    let onAbout: () -> Void
    let onQuit: () -> Void
    var shown: Scheduler.Pomodoro? = nil    // --snapshot: a pomodoro the scheduler is not in (the break, the widest)
    @EnvironmentObject private var s: Settings
    @EnvironmentObject private var login: LoginItem
    @EnvironmentObject private var timer: ModeTimer
    @EnvironmentObject private var clock: PanelClock
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let t = Theme(scheme)
        VStack(alignment: .leading, spacing: 16) {
            head(t)
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 7) {
                    groupTitle("Mode", t)
                    Segments(mode: $s.mode)
                }
                // the mode's block is as high as the pomodoro in its widest state (an invisible copy under it) in every
                // mode and state: the panel never changes height (Valentin, 02.11); a shorter mode sits at the top
                ZStack(alignment: .topLeading) {
                    VStack(alignment: .leading, spacing: 7) { pomodoroBody(t, sizing: true) }
                        .hidden().accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 7) { modeBody(t) }
                }
            }
            .opacity(s.enabled ? 1 : 0.45)
            .animation(.easeInOut(duration: 0.25), value: s.enabled)
            card(t) {
                line {
                    Button(action: onPlay) {
                        HStack(spacing: 7) {
                            PlayGlyph().fill(t.text).frame(width: 13, height: 14)
                            Text("Play now").font(.system(size: 15, weight: .semibold))
                        }
                        .padding(.leading, 13).padding(.trailing, 16).frame(height: 36)
                        .background(Capsule().fill(t.btn))
                        .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    Spacer(minLength: 0)
                    Text("Mute").font(.system(size: 16))
                    PillSwitch(isOn: $s.muted)
                }
            }
            card(t) {
                line {
                    Text("Open at login").font(.system(size: 16)).opacity(login.available ? 1 : 0.45)
                    Spacer(minLength: 0)
                    PillSwitch(isOn: Binding(get: { login.isOn }, set: { login.set($0) }), enabled: login.available)
                }
            }
            .help(login.available ? "" : "Roadster can open at login once it is in the Applications folder")
            HStack {
                Button("About", action: onAbout).buttonStyle(.plain)
                    .font(.system(size: 12)).foregroundColor(t.sub)
                Spacer()
                Button(action: onQuit) {
                    Text("Quit").font(.system(size: 14, weight: .medium)).padding(.vertical, 4).padding(.horizontal, 8)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            .padding(.leading, 14).padding(.trailing, 6).frame(minHeight: 24)
        }
        .foregroundColor(t.text)
        .padding(.top, 16).padding(.horizontal, 14).padding(.bottom, 12)
        .frame(width: 344)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(t.bg))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(t.ring, lineWidth: 0.5))
        .fixedSize(horizontal: false, vertical: true)
        .background(GeometryReader { g in Color.clear.preference(key: SizeKey.self, value: g.size) })
        .onPreferenceChange(SizeKey.self) { onSize($0) }
    }

    private func head(_ t: Theme) -> some View {
        HStack(spacing: 10) {
            Image(nsImage: NSApp.applicationIconImage).resizable().interpolation(.high)
                .frame(width: 36, height: 36).padding(-2)
            VStack(alignment: .leading, spacing: 2) {
                Text("Roadster").font(.system(size: 17, weight: .bold)).tracking(-0.2)
                Text("by VALENTIN STE").font(.system(size: 13)).foregroundColor(t.sub)
            }
            Spacer(minLength: 0)
            PillSwitch(isOn: $s.enabled)
        }
        .padding(.leading, 2)
    }

    private func groupTitle(_ s: String, _ t: Theme) -> some View {
        Text(s).font(.system(size: 13)).textCase(.uppercase).tracking(0.4).foregroundColor(t.sub).padding(.horizontal, 14)
    }

    private func note(_ s: String, _ t: Theme) -> some View {
        Text(s).font(.system(size: 13)).foregroundColor(t.sub).lineSpacing(2)
            .fixedSize(horizontal: false, vertical: true).padding(.horizontal, 14)
    }

    @ViewBuilder private func modeBody(_ t: Theme) -> some View {
        switch s.mode {
        case .pomodoro:
            pomodoroBody(t, sizing: false)
        case .hourly:
            card(t) {
                line {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.enabled ? "Next show at \(nextHour)" : "Paused").font(.system(size: 16))
                        Text("On the hour, every hour").font(.system(size: 13)).foregroundColor(t.sub)
                    }
                    Spacer(minLength: 0)
                }
            }
        case .random:
            card(t) {
                line {
                    HStack(spacing: 7) {
                        Text("Every")
                        MinutesField(value: Binding(get: { s.randomFrom }, set: {
                            s.randomFrom = $0
                            if s.randomTo < $0 { s.randomTo = $0 }     // "from" never above "to": the other follows
                        }), range: 1...600)
                        Text("–")
                        MinutesField(value: Binding(get: { s.randomTo }, set: {
                            s.randomTo = $0
                            if s.randomFrom > $0 { s.randomFrom = $0 }
                        }), range: 1...600)
                        Text("min")
                    }
                    .font(.system(size: 16))
                    Spacer(minLength: 0)
                }
            }
            note("The car comes at a random moment, from \(s.randomFrom) to \(s.randomTo) minutes after the last show.", t)
        }
    }

    // The widest the timer's line gets: the longer phase paused, the longest work, two buttons (not a state it can be in:
    // a break is 60 min at most), for the copy that holds the block's height.
    static let widest = Scheduler.Pomodoro(run: .paused, phase: .rest, deadline: nil, left: 180 * 60)

    // the pomodoro's card and note; `sizing`: the invisible copy in the widest state, its fields boxes of their size
    // (a second live field would put its old number back when the panel closes)
    @ViewBuilder private func pomodoroBody(_ t: Theme, sizing: Bool) -> some View {
        card(t) {
            VStack(spacing: 0) {
                line(minHeight: 76) { pomodoroTimer(t, sizing ? Self.widest : shown ?? timer.scheduler.pomodoro) }
                separator(t)
                line(leading: 0) {
                    HStack(spacing: 7) {
                        Text("Work")
                        field($s.workMinutes, 1...180, sizing)
                        Text("min")
                        Color.clear.frame(width: 14, height: 1)
                        Text("Break")
                        field($s.breakMinutes, 1...60, sizing)
                        Text("min")
                    }
                    .font(.system(size: 16))
                    Spacer(minLength: 0)
                }
                .padding(.leading, 14)
            }
        }
        note("The car flies out when work ends and when the break ends.", t)
    }

    @ViewBuilder private func field(_ v: Binding<Int>, _ range: ClosedRange<Int>, _ sizing: Bool) -> some View {
        if sizing {
            Color.clear.frame(width: MinutesField.size.width, height: MinutesField.size.height)
        } else {
            MinutesField(value: v, range: range)
        }
    }

    // the phase, the time (live), the buttons; off, a started pomodoro shows as paused; Start and Resume switch the app
    // on (Schedule.swift), so no button is ever greyed
    @ViewBuilder private func pomodoroTimer(_ t: Theme, _ p: Scheduler.Pomodoro) -> some View {
        let ready = p.run == .ready
        let paused = p.run == .paused || (!ready && !s.enabled)
        let left = ready ? TimeInterval(s.workMinutes * 60) : p.left(at: timer.now)
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 6) {
                Circle().fill(ready ? t.chev : p.phase == .work ? t.work : t.green).frame(width: 8, height: 8)
                Text(p.phase.title + (paused ? " · paused" : "")).font(.system(size: 13)).textCase(.uppercase)
                    .tracking(0.4).foregroundColor(t.sub).fixedSize()
            }
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(Scheduler.mmss(left)).font(.system(size: 30, weight: .semibold).monospacedDigit())
                    .tracking(-0.5).foregroundColor(ready ? t.sub : t.text)
                if !ready { Text("left").font(.system(size: 15)).foregroundColor(t.sub) }
            }
            .fixedSize()
        }
        // the free width goes to this column (no Spacer: its two gaps would not leave room for 180:00 and two buttons)
        .frame(maxWidth: .infinity, alignment: .leading)
        HStack(spacing: 8) {
            if ready {
                pill("Start", t, go: true) { timer.start() }
            } else {
                if paused { pill("Resume", t) { timer.resume() } } else { pill("Pause", t) { timer.pause() } }
                pill("Reset", t) { timer.reset() }
            }
        }
        .layoutPriority(1)
    }

    // the mock-up's .btn: 32 pt high, 14 pt semibold; Start (.go) green with white letters
    private func pill(_ title: String, _ t: Theme, go: Bool = false, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.system(size: 14, weight: .semibold)).foregroundColor(go ? .white : t.text).fixedSize()
                .padding(.horizontal, go ? 20 : 14).frame(height: 32)
                .background(Capsule().fill(go ? t.green : t.btn))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private var nextHour: String {
        let f = DateFormatter()
        f.timeStyle = .short
        f.dateStyle = .none
        return f.string(from: timer.scheduler.nextHour(after: clock.now))
    }

    private func card<C: View>(_ t: Theme, @ViewBuilder _ c: () -> C) -> some View {
        c().frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(t.card))
    }

    private func line<C: View>(minHeight: CGFloat = 52, leading: CGFloat = 14, @ViewBuilder _ c: () -> C) -> some View {
        HStack(spacing: 10) { c() }
            .padding(EdgeInsets(top: 6, leading: leading, bottom: 6, trailing: 8))
            .frame(maxWidth: .infinity, minHeight: minHeight, alignment: .leading)
    }

    private func separator(_ t: Theme) -> some View {
        Rectangle().fill(t.sep).frame(height: 1).padding(.leading, 14)
    }
}

// The mode picker as segments (Valentin, 02.11): the switch's colours, the chosen one white with a shadow.
struct Segments: View {
    @Binding var mode: Mode
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let t = Theme(scheme)
        HStack(spacing: 0) {
            ForEach(Mode.allCases, id: \.self) { m in
                let on = m == mode
                Button { mode = m } label: {
                    Text(m.title).font(.system(size: 14, weight: on ? .semibold : .medium)).lineLimit(1)
                        .padding(.horizontal, 4)
                        .frame(maxWidth: .infinity).frame(height: 32)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(on ? t.segOn : .clear)
                                .shadow(color: .black.opacity(on ? 0.14 : 0), radius: 2, x: 0, y: 2))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(2)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(t.off))
    }
}

// A minutes field: 46x30, right-aligned figures, the panel's background inside the card, a thin inner border. The
// number is kept on Return, on leaving the field and when the panel closes: whole minutes within its range (700 -> 600,
// 0 -> 1); anything else (2.5, letters, empty) puts the kept number back. The field always shows what is kept.
struct MinutesField: View {
    static let commitNote = Notification.Name("com.valentinste.roadster.commit-minutes")
    static let size = CGSize(width: 46, height: 30)
    @Binding var value: Int
    let range: ClosedRange<Int>
    @State private var text = ""
    @FocusState private var focused: Bool
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let t = Theme(scheme)
        TextField("", text: $text)
            .focused($focused)
            .onSubmit(commit)
            .onChange(of: focused) { if !$0 { commit() } }
            .onChange(of: value) { if !focused { text = String($0) } }
            .onReceive(NotificationCenter.default.publisher(for: Self.commitNote)) { _ in commit() }
            .onAppear { text = String(value) }
            .textFieldStyle(.plain)
            .multilineTextAlignment(.trailing)
            .font(.system(size: 15).monospacedDigit())
            .padding(.horizontal, 8)
            .frame(width: Self.size.width, height: Self.size.height)
            .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(t.bg))
            .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).strokeBorder(t.fieldBorder, lineWidth: 1))
    }

    private func commit() {
        if let n = Scheduler.minutes(text, in: range), n != value { value = n }
        text = String(value)
    }
}

// The play glyph of the mock-up (design/mock.js), 13x14.
struct PlayGlyph: Shape {
    func path(in r: CGRect) -> Path {
        let sx = r.width / 13, sy = r.height / 14
        func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: r.minX + x * sx, y: r.minY + y * sy) }
        var path = Path()
        path.move(to: p(2, 1.6))
        path.addLine(to: p(2, 12.4))
        path.addCurve(to: p(3.6, 13.3), control1: p(2, 13.2), control2: p(2.9, 13.7))
        path.addLine(to: p(12.2, 7.9))
        path.addCurve(to: p(12.2, 6.2), control1: p(12.8, 7.5), control2: p(12.8, 6.6))
        path.addLine(to: p(3.6, 0.8))
        path.addCurve(to: p(2, 1.6), control1: p(2.9, 0.3), control2: p(2, 0.8))
        path.closeSubpath()
        return path
    }
}
