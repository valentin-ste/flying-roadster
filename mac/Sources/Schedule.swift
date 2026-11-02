import Foundation

// The schedule of the three modes without AppKit: when the car comes, on a clock it is handed. The app drives it
// (ModeTimer.swift: one timer at the next moment, the panel's buttons, the switch, sleep and the lock); the tests
// (mac/Tests/ScheduleTests.swift, run by tools/build_mac_app.sh before the build) drive it with a clock of their own.
// Every moment is a Date on that clock, never a sum of timer intervals: a late timer or a sleeping Mac moves nothing.

enum Mode: String, CaseIterable {
    case pomodoro, hourly, random
    var title: String {
        switch self {
        case .pomodoro: return "Pomodoro"
        case .hourly: return "Every hour"
        case .random: return "Random"
        }
    }
}

protocol Clock: AnyObject { var now: Date { get } }

final class Scheduler {
    enum Phase: String {
        case work, rest
        var title: String { self == .work ? "Work" : "Break" }
    }
    enum Run: String { case ready, running, paused }   // what Start, Pause, Resume and Reset asked for

    struct Pomodoro: Equatable {
        var run = Run.ready
        var phase = Phase.work
        var deadline: Date?            // the phase's end while its time runs
        var left: TimeInterval = 0     // the time left while it stands (Pause; Off, sleep or the lock)
        func left(at now: Date) -> TimeInterval { deadline.map { max(0, $0.timeIntervalSince(now)) } ?? left }
    }

    let clock: Clock
    var calendar = Calendar.autoupdatingCurrent
    var lateLimit: TimeInterval = 60   // a moment found later than this went by in a sleep nobody announced: no show
    var random: (ClosedRange<Double>) -> Double = { Double.random(in: $0) }
    var showIsOn: () -> Bool = { false }
    var play: (String) -> Void = { _ in }
    var log: (String) -> Void = { _ in }
    var switchedOn: () -> Void = {}    // Start or Resume turned the app on: its switch follows

    private(set) var mode: Mode
    private(set) var enabled: Bool
    private(set) var workMinutes = 25, breakMinutes = 5   // a new length counts from the next phase
    private(set) var randomFrom = 30, randomTo = 90
    private(set) var reasons = Set<String>()               // why nobody would see the car: sleep, screens, screensaver,
                                                           // lock, session
    private(set) var pomodoro = Pomodoro()
    private(set) var hourlyNext: Date?
    private(set) var randomNext: Date?

    var asleep: Bool { !reasons.isEmpty }
    var blocked: Bool { !enabled || asleep }

    init(clock: Clock, mode: Mode, enabled: Bool) {
        self.clock = clock
        self.mode = mode
        self.enabled = enabled
    }

    // The next moment something is due (the app sets its timer to it); nil: nothing comes until something changes.
    var nextWake: Date? {
        guard !blocked else { return nil }
        switch mode {
        case .pomodoro: return pomodoro.deadline
        case .hourly: return hourlyNext
        case .random: return randomNext
        }
    }

    // The app's start: the pomodoro waits for Start (nothing is kept across launches), the others count from now.
    func begin() {
        log("schedule: mode \(mode.rawValue), switch \(enabled ? "on" : "off")")
        setUp()
    }

    func setLengths(work: Int, rest: Int) {
        guard (work, rest) != (workMinutes, breakMinutes) else { return }
        workMinutes = work
        breakMinutes = rest
        log("pomodoro: \(work) + \(rest) min" + (pomodoro.run == .ready ? "" : ", from the next phase"))
    }

    func setRange(_ from: Int, _ to: Int) {
        guard (from, to) != (randomFrom, randomTo) else { return }
        randomFrom = from
        randomTo = to
        if mode == .random { draw(clock.now, "new range") }
    }

    // A new mode drops the old one's schedule.
    func setMode(_ m: Mode) {
        guard m != mode else { return }
        tick()
        log("mode: \(mode.rawValue) -> \(m.rawValue)")
        mode = m
        pomodoro = Pomodoro()
        hourlyNext = nil
        randomNext = nil
        setUp()
    }

    // The switch in the panel: Off stops the shows and stands the pomodoro; On brings back what was there.
    func setEnabled(_ on: Bool) {
        guard on != enabled else { return }
        tick()
        let was = blocked
        enabled = on
        log("switch: \(on ? "on" : "off")")
        blockChanged(was)
    }

    // Sleep, the screens' sleep, the screensaver, the lock, another user's session: no shows meanwhile, the pomodoro
    // stands; a moment that went by meanwhile is not played later.
    func suspend(_ why: String) {
        guard !reasons.contains(why) else { return }
        tick()
        let was = blocked
        reasons.insert(why)
        log("away: \(why) (\(reasons.sorted().joined(separator: ", ")))")
        blockChanged(was)
    }

    func wake(_ why: String) {
        guard reasons.contains(why) else { return }
        let was = blocked
        reasons.remove(why)
        log("back: \(why)" + (reasons.isEmpty ? "" : " (still away: \(reasons.sorted().joined(separator: ", ")))"))
        blockChanged(was)
    }

    // The pomodoro's buttons. Start and Resume while off switch the app on (Valentin, 02.11): no greyed buttons.
    func start() {
        tick()
        guard mode == .pomodoro, pomodoro.run == .ready else { return }
        switchOn("Start")
        pomodoro = Pomodoro(run: .running, phase: .work, deadline: nil, left: length(.work))
        log("pomodoro: Start, work \(workMinutes) min" + (blocked ? " (stands until back)" : ""))
        syncPomodoro()
    }

    func pause() {
        tick()
        guard pomodoro.run == .running else { return }
        pomodoro.run = .paused
        log("pomodoro: Pause")
        syncPomodoro()
    }

    // Off shows a started pomodoro as paused: Resume then goes on with it whether it was paused or not.
    func resume() {
        tick()
        guard pomodoro.run == .paused || (pomodoro.run == .running && !enabled) else { return }
        switchOn("Resume")
        if pomodoro.run == .paused {
            pomodoro.run = .running
            log("pomodoro: Resume")
        }
        syncPomodoro()
    }

    func reset() {
        tick()
        guard pomodoro.run != .ready else { return }
        pomodoro = Pomodoro()
        log("pomodoro: Reset, waits for Start")
    }

    // A show that did not come from the schedule (Play now): Random counts its minutes from the last show.
    func noteShow(_ what: String) {
        guard mode == .random else { return }
        draw(clock.now, "after \(what)")
    }

    // The clock was set or the time zone changed: the next o'clock is found again.
    func clockChanged() {
        guard mode == .hourly, let h = hourlyNext else { return }
        let n = nextHour(after: clock.now)
        guard n != h else { return }
        hourlyNext = n
        log("hourly: the clock changed, next show at \(hm(n))")
    }

    // What is due now comes: the app calls it when its timer fires, the tests when their clock gets there.
    func tick() {
        guard !blocked else { return }
        let now = clock.now
        switch mode {
        case .pomodoro:
            guard pomodoro.run == .running, let due = pomodoro.deadline, now >= due else { return }
            let ended = pomodoro.phase
            let next: Phase = ended == .work ? .rest : .work
            let len = length(next)
            var end = due.addingTimeInterval(len)      // from the moment, not from the late timer: no drift
            if end <= now { end = now.addingTimeInterval(len) }
            pomodoro.phase = next
            pomodoro.deadline = end
            log("pomodoro: \(ended.title.lowercased()) is over, \(next.title.lowercased()) \(Self.mmss(len)) until \(hms(end))")
            show("pomodoro, \(ended.title.lowercased()) over", due: due, now: now)
        case .hourly:
            guard let due = hourlyNext, now >= due else { return }
            hourlyNext = nextHour(after: now)
            show("hourly, \(hm(due))", due: due, now: now)
            log("hourly: next show at \(hm(hourlyNext!))")
        case .random:
            guard let due = randomNext, now >= due else { return }
            show("random", due: due, now: now)
            draw(now, "after the last one")
        }
    }

    // The start of the next hour on the local clock (after a change of the time zone or of summer time as well).
    func nextHour(after t: Date) -> Date {
        calendar.dateInterval(of: .hour, for: t)?.end ?? t.addingTimeInterval(3600)
    }

    // Whole minutes typed into a field, kept within the range; nil for anything else (the field goes back).
    static func minutes(_ text: String, in range: ClosedRange<Int>) -> Int? {
        guard let n = Int(text.trimmingCharacters(in: .whitespaces)) else { return nil }
        return min(max(n, range.lowerBound), range.upperBound)
    }

    // 25:00, 4:59, 0:01: whole seconds rounded up, so a phase shows its full length at its start.
    static func mmss(_ t: TimeInterval) -> String {
        let s = Int(max(0, t).rounded(.up))
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    // MARK: -

    private func setUp() {
        let now = clock.now
        let later = blocked ? " (once on)" : ""
        switch mode {
        case .pomodoro:
            log("pomodoro: ready, waits for Start (\(workMinutes) + \(breakMinutes) min)")
        case .hourly:
            let n = nextHour(after: now)
            hourlyNext = n
            log("hourly: next show at \(hm(n))\(later)")
        case .random:
            draw(now, "mode on\(later)")
        }
    }

    private func switchOn(_ by: String) {
        guard !enabled else { return }
        log("\(by) while off: the switch goes on")
        setEnabled(true)
        switchedOn()
    }

    private func blockChanged(_ was: Bool) {
        let now = clock.now
        syncPomodoro()
        guard was != blocked else { return }
        if blocked {
            log("shows: stopped (\(enabled ? "away" : "off"))")
            return
        }
        switch mode {
        case .pomodoro:
            break
        case .hourly:
            if let h = hourlyNext, h <= now { log("hourly: \(hm(h)) went by meanwhile, not played") }
            let n = nextHour(after: now)
            hourlyNext = n
            log("hourly: next show at \(hm(n))")
        case .random:
            if let r = randomNext, r > now {
                log("random: the next moment is still ahead, kept")
            } else {
                if randomNext != nil { log("random: its moment went by meanwhile, not played") }
                draw(now, "back")
            }
        }
    }

    // The pomodoro's time runs only while it is running and nothing stands it.
    private func syncPomodoro() {
        let now = clock.now
        let runs = mode == .pomodoro && pomodoro.run == .running && !blocked
        let name = pomodoro.phase.title.lowercased()
        if runs, pomodoro.deadline == nil {
            let end = now.addingTimeInterval(pomodoro.left)
            pomodoro.deadline = end
            log("pomodoro: \(name) runs, \(Self.mmss(pomodoro.left)) left, until \(hms(end))")
        } else if !runs, let end = pomodoro.deadline {
            pomodoro.left = max(0, end.timeIntervalSince(now))
            pomodoro.deadline = nil
            log("pomodoro: \(name) stands, \(Self.mmss(pomodoro.left)) left")
        }
    }

    private func show(_ what: String, due: Date, now: Date) {
        let late = now.timeIntervalSince(due)
        if late > lateLimit {
            log(String(format: "show: %@: not played, found %.0f s after its moment (an unannounced sleep?)", what, late))
        } else if showIsOn() {
            log("show: \(what): skipped, a show is on")
        } else {
            log(String(format: "show: %@ (%.3f s after its moment)", what, late))
            play(what)
        }
    }

    private func draw(_ now: Date, _ why: String) {
        let lo = Double(min(randomFrom, randomTo)), hi = Double(max(randomFrom, randomTo))
        let m = random(lo...hi)
        let at = now.addingTimeInterval(m * 60)
        randomNext = at
        log(String(format: "random: next in %.2f min (%d-%d), at %@, %@", m, randomFrom, randomTo, hms(at), why))
    }

    private func length(_ p: Phase) -> TimeInterval { TimeInterval((p == .work ? workMinutes : breakMinutes) * 60) }

    private let fmt: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    private func format(_ d: Date, _ pattern: String) -> String {
        fmt.timeZone = calendar.timeZone
        fmt.dateFormat = pattern
        return fmt.string(from: d)
    }

    private func hms(_ d: Date) -> String { format(d, "HH:mm:ss") }
    private func hm(_ d: Date) -> String { format(d, "HH:mm") }
}
