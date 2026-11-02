import AppKit
import Combine
import CoreGraphics

// The modes' clock: real time, or sped up for checks: `defaults write com.valentinste.roadster TimeScale 60` (a minute
// of the schedule a second; the show itself plays at its own speed), read at launch; `defaults delete ... TimeScale`.
final class AppClock: Clock {
    let scale: Double
    private let base = Date()
    init(scale: Double) { self.scale = scale }
    var now: Date { scale == 1 ? Date() : base.addingTimeInterval(Date().timeIntervalSince(base) * scale) }
}

// The app's side of the schedule (Schedule.swift): the settings go in, one timer is set to the next moment, sleep, the
// screens' sleep, the screensaver, the lock and another user's session stand it, the show comes out. The panel reads it
// for the countdown.
@MainActor
final class ModeTimer: ObservableObject {
    static let shared = ModeTimer()
    let clock: AppClock
    let scheduler: Scheduler
    private var timer: DispatchSourceTimer?
    private var due: Date?
    private var subs: [AnyCancellable] = []
    private var observers: [(NotificationCenter, NSObjectProtocol)] = []
    private var notices: [Notice] = []
    private var begun = false

    private init() {
        let scale = UserDefaults.standard.double(forKey: "TimeScale")
        clock = AppClock(scale: scale > 0 ? scale : 1)
        let s = Settings.shared
        scheduler = Scheduler(clock: clock, mode: s.mode, enabled: s.enabled)
        scheduler.setLengths(work: s.workMinutes, rest: s.breakMinutes)
        scheduler.setRange(s.randomFrom, s.randomTo)
        scheduler.lateLimit = 60 * clock.scale
        scheduler.showIsOn = { ShowPlayer.shared.isPlaying }
        scheduler.play = { _ in ShowPlayer.shared.play() }
        scheduler.log = { Log.say($0) }
        scheduler.switchedOn = { Settings.shared.enabled = true }    // the sink finds the schedule on already
    }

    var now: Date { clock.now }

    func begin() {
        guard !begun else { return }
        begun = true
        if clock.scale != 1 { Log.say("time: TimeScale \(clock.scale) (a debug setting): the schedule runs \(clock.scale) times faster") }
        // the state at launch (a launch at login behind a locked screen, say)
        for (why, on) in Self.queryAway() where on { scheduler.suspend(why) }
        scheduler.begin()
        let s = Settings.shared
        subs = [
            s.$mode.sink { [weak self] in self?.scheduler.setMode($0); self?.arm() },
            s.$enabled.sink { [weak self] in self?.scheduler.setEnabled($0); self?.arm() },
            s.$workMinutes.combineLatest(s.$breakMinutes).sink { [weak self] in self?.scheduler.setLengths(work: $0, rest: $1) },
            s.$randomFrom.combineLatest(s.$randomTo).sink { [weak self] in self?.scheduler.setRange($0, $1); self?.arm() },
        ]
        let ws = NSWorkspace.shared.notificationCenter
        observe(ws, NSWorkspace.willSleepNotification) { $0.away("sleep") }
        observe(ws, NSWorkspace.didWakeNotification) { $0.back("sleep") }
        observe(ws, NSWorkspace.screensDidSleepNotification) { $0.away("screens") }
        observe(ws, NSWorkspace.screensDidWakeNotification) { $0.back("screens") }
        observe(ws, NSWorkspace.sessionDidResignActiveNotification) { $0.away("session") }
        observe(ws, NSWorkspace.sessionDidBecomeActiveNotification) { $0.back("session") }
        notices = [
            Notice("com.apple.screenIsLocked") { [weak self] in self?.away("lock") },
            Notice("com.apple.screenIsUnlocked") { [weak self] in self?.back("lock") },
            Notice("com.apple.screensaver.didstart") { [weak self] in self?.away("screensaver") },
            Notice("com.apple.screensaver.didstop") { [weak self] in self?.back("screensaver") },
        ]
        observe(NotificationCenter.default, .NSSystemClockDidChange) { $0.clockChanged() }
        observe(NotificationCenter.default, .NSSystemTimeZoneDidChange) { $0.clockChanged() }
        testScript()
        arm()
    }

    // The pomodoro's buttons.
    func start() { scheduler.start(); arm() }
    func pause() { scheduler.pause(); arm() }
    func resume() { scheduler.resume(); arm() }
    func reset() { scheduler.reset(); arm() }

    // Play now works always, off as well; Random counts its minutes from it.
    func playNow(on screen: NSScreen?) {
        guard !ShowPlayer.shared.isPlaying else { Log.say("Play now: a show is on, ignored"); return }
        Log.say("Play now")
        ShowPlayer.shared.play(on: screen)
        scheduler.noteShow("Play now")
        arm()
    }

    // When the panel's countdown changes next, in real seconds: on the pomodoro's whole seconds, else once a second.
    func nextFlip() -> TimeInterval {
        guard let d = scheduler.pomodoro.deadline else { return 1 }
        let r = d.timeIntervalSince(clock.now)
        let f = r - r.rounded(.down)
        return min(1, max(0.05, (f < 0.001 ? 1 : f) / clock.scale + 0.01))
    }

    // MARK: - the timer

    private func arm() {
        objectWillChange.send()
        let t = timer ?? makeTimer()
        due = scheduler.nextWake
        if let d = due {
            t.schedule(wallDeadline: .now() + max(0, d.timeIntervalSince(clock.now) / clock.scale), leeway: .milliseconds(5))
        } else if scheduler.asleep {
            t.schedule(wallDeadline: .now() + 60, leeway: .seconds(5))    // asks again whether the lock or the screens' sleep lasts
        } else {
            t.schedule(deadline: .distantFuture)
        }
    }

    private func makeTimer() -> DispatchSourceTimer {
        let t = DispatchSource.makeTimerSource(flags: .strict, queue: .main)   // strict: App Nap may not put it off
        t.setEventHandler { [weak self] in Task { @MainActor in self?.fired() } }
        t.resume()
        timer = t
        return t
    }

    private func fired() {
        if let d = due {
            Log.say(String(format: "timer: %.1f ms after the moment", clock.now.timeIntervalSince(d) / clock.scale * 1000))
        }
        if scheduler.asleep { recheck() }
        scheduler.tick()
        arm()
    }

    // MARK: - sleep, the screens, the lock, the session

    private func observe(_ c: NotificationCenter, _ name: Notification.Name, _ f: @escaping (ModeTimer) -> Void) {
        let o = c.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in if let self { f(self) } }
        }
        observers.append((c, o))
    }

    private func away(_ why: String) {
        scheduler.suspend(why)
        arm()
    }

    // Any of these means the Mac is awake; the reasons that can be asked about are asked again, so a missed notice
    // cannot stand the schedule until the next launch. The screensaver cannot be asked about: any return ends it.
    private func back(_ why: String) {
        scheduler.wake(why)
        scheduler.wake("sleep")
        scheduler.wake("screensaver")
        recheck()
        arm()
    }

    private func recheck() {
        for (why, on) in Self.queryAway() where !on && scheduler.reasons.contains(why) { scheduler.wake(why) }
    }

    private func clockChanged() {
        scheduler.clockChanged()
        arm()
    }

    // lock: the session's flag; screens: every display asleep; session: this user's session is not on the screen
    static func queryAway() -> [(String, Bool)] {
        let d = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
        let locked = (d["CGSSessionScreenIsLocked"] as? Bool) ?? false
        let onConsole = (d["kCGSSessionOnConsoleKey"] as? Bool) ?? true
        var n: UInt32 = 0
        CGGetOnlineDisplayList(0, nil, &n)
        var ids = [CGDirectDisplayID](repeating: 0, count: Int(n))
        CGGetOnlineDisplayList(n, &ids, &n)
        let screensAsleep = !ids.isEmpty && ids.allSatisfy { CGDisplayIsAsleep($0) != 0 }
        return [("lock", locked), ("screens", screensAsleep), ("session", !onConsole)]
    }

    // MARK: - checks

    // A one-off strict timer on the main queue (asyncAfter may come ~5% late: half a second on a 10-s wait).
    static func after(_ seconds: Double, _ f: @escaping @MainActor () -> Void) {
        let t = DispatchSource.makeTimerSource(flags: .strict, queue: .main)
        t.schedule(wallDeadline: .now() + seconds, leeway: .milliseconds(1))
        t.setEventHandler { t.cancel(); Task { @MainActor in f() } }   // holds itself until it fires
        t.resume()
    }

    // -TestScript "2 start; 30 off; 40 on; 50 mode hourly; 300 quit": actions at real seconds after the launch, through
    // the panel's paths (settings, buttons, Play now) and the notices' paths (sleep/wake, lock/unlock, screens-off/-on).
    // The pretend lock and screens have names of their own, so asking the system (recheck) leaves them be.
    private func testScript() {
        guard let script = UserDefaults.standard.string(forKey: "TestScript") else { return }
        let steps = script.split(separator: ";").map { $0.split(separator: " ").map(String.init) }
        for w in steps {
            guard w.count >= 2, let t = Double(w[0]) else { Log.say("test: cannot read \(w)"); continue }
            Self.after(t) { self.act(Array(w.dropFirst())) }
        }
        Log.say("test: a script of \(steps.count) steps")
    }

    private func act(_ w: [String]) {
        Log.say("test: \(w.joined(separator: " "))")
        let s = Settings.shared
        let n = w.count > 1 ? Int(w[1]) ?? 0 : 0
        switch w[0] {
        case "start": start()
        case "pause": pause()
        case "resume": resume()
        case "reset": reset()
        case "off": s.enabled = false
        case "on": s.enabled = true
        case "mode": if let m = Mode(rawValue: w[1]) { s.mode = m }
        case "work": s.workMinutes = n
        case "break": s.breakMinutes = n
        case "range": s.randomFrom = n; s.randomTo = w.count > 2 ? Int(w[2]) ?? n : n
        case "play": playNow(on: nil)
        case "sleep": away("sleep")
        case "wake": back("sleep")
        case "lock": away("test-lock")
        case "unlock": back("test-lock")
        case "screens-off": away("test-screens")
        case "screens-on": back("test-screens")
        case "saver-on": away("test-saver")
        case "saver-off": back("test-saver")
        case "quit": NSApp.terminate(nil)
        default: Log.say("test: unknown action \(w[0])")
        }
    }
}

// A distributed notice delivered at once: AppKit holds them while the app is not active, and a menu bar app hardly
// ever is (NSDistributedNotificationCenter.h, `suspended`).
private final class Notice: NSObject {
    private let f: @MainActor () -> Void
    init(_ name: String, _ f: @escaping @MainActor () -> Void) {
        self.f = f
        super.init()
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(got), name: Notification.Name(name),
                                                            object: nil, suspensionBehavior: .deliverImmediately)
    }
    @objc private func got() { Task { @MainActor in f() } }
}
