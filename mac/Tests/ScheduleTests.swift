import Foundation

// The schedule (mac/Sources/Schedule.swift) on a clock of its own: hours of the three modes in milliseconds.
//   xcrun swiftc -parse-as-library mac/Sources/Schedule.swift mac/Tests/ScheduleTests.swift -o /tmp/st && /tmp/st [-v]
// tools/build_mac_app.sh runs it before every build; exit 0 = all checks hold. -v prints the schedule's log.

final class FakeClock: Clock {
    var now: Date
    init(_ d: Date) { now = d }
}

// A scheduler, its clock, a stage where every show takes 14 s (as the real one), and the draws Random gets (0...1).
final class World {
    let clock: FakeClock
    let s: Scheduler
    var shows: [(at: Date, what: String)] = []
    var showUntil = Date.distantPast
    var draws: [Double]
    let tz: TimeZone

    init(_ start: String, _ mode: Mode, tz: String = "Europe/Moscow", draws: [Double] = [0.5], enabled: Bool = true) {
        self.tz = TimeZone(identifier: tz)!
        self.draws = draws
        clock = FakeClock(Date())
        s = Scheduler(clock: clock, mode: mode, enabled: enabled)
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = self.tz
        s.calendar = cal
        clock.now = at(start)
        s.showIsOn = { [unowned self] in clock.now < showUntil }
        s.play = { [unowned self] what in
            shows.append((clock.now, what))
            showUntil = clock.now.addingTimeInterval(14)
        }
        s.random = { [unowned self] r in
            let x = self.draws.count > 1 ? self.draws.removeFirst() : self.draws[0]
            return r.lowerBound + (r.upperBound - r.lowerBound) * x
        }
        s.log = { line in if CommandLine.arguments.contains("-v") { print("    \(line)") } }
        s.begin()
    }

    // "2026-11-02 10:25:00" or "10:25:00" (that day), local to the world's time zone
    func at(_ s: String) -> Date {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = tz
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.date(from: s.count > 8 ? s : "2026-11-02 " + s)!
    }

    func local(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = tz
        f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }

    // the app's timer: fires at every moment the schedule asks for (late by `late` s) until the clock reaches t
    func run(to t: Date, late: TimeInterval = 0) {
        var n = 0
        while let w = s.nextWake, w.addingTimeInterval(late) <= t {
            clock.now = max(clock.now, w.addingTimeInterval(late))
            s.tick()
            n += 1
            precondition(n < 10_000, "the schedule does not move on")
        }
        clock.now = t
    }
    func run(to t: String, late: TimeInterval = 0) { run(to: at(t), late: late) }

    var showTimes: [String] { shows.map { local($0.at) } }
}

@main
enum ScheduleTests {
    static var checks = 0, failures = 0

    static func check(_ ok: Bool, _ what: @autoclosure () -> String, line: UInt = #line) {
        checks += 1
        if !ok { failures += 1; print("FAIL (line \(line)): \(what())") }
    }

    static func eq<T: Equatable>(_ a: T, _ b: T, _ what: String, line: UInt = #line) {
        check(a == b, "\(what): \(a), expected \(b)", line: line)
    }

    static func test(_ name: String, _ body: () -> Void) {
        let f = failures
        body()
        print((failures == f ? "ok    " : "FAILED") + "  " + name)
    }

    static func main() {
        test("pomodoro: Start, then work and break go round by themselves, a show at every end") {
            let w = World("10:00:00", .pomodoro)
            eq(w.s.nextWake, nil, "nothing before Start")
            w.run(to: "12:00:00")
            eq(w.shows.count, 0, "no show before Start")
            w.clock.now = w.at("12:00:00")
            w.s.start()
            w.run(to: "13:00:01")
            eq(w.showTimes, ["12:25:00", "12:30:00", "12:55:00", "13:00:00"], "shows")
            eq(w.s.pomodoro.phase, .work, "phase")
            eq(w.s.pomodoro.deadline, w.at("13:25:00"), "the work's end")
        }

        test("pomodoro: new lengths count from the next phase; before Start at once") {
            let w = World("10:00:00", .pomodoro)
            w.s.setLengths(work: 20, rest: 4)
            w.s.start()
            eq(w.s.pomodoro.deadline, w.at("10:20:00"), "a length set before Start counts at once")
            w.run(to: "10:10:00")
            w.s.setLengths(work: 10, rest: 2)
            eq(w.s.pomodoro.deadline, w.at("10:20:00"), "the running work keeps its end")
            w.run(to: "10:40:00")
            eq(w.showTimes, ["10:20:00", "10:22:00", "10:32:00", "10:34:00"], "shows")
        }

        test("pomodoro: Pause stands the time, Resume goes on, Reset waits for Start") {
            let w = World("10:00:00", .pomodoro)
            w.s.start()
            w.run(to: "10:10:00")
            w.s.pause()
            w.run(to: "10:17:00")
            eq(w.s.pomodoro.run, .paused, "run")
            eq(w.s.pomodoro.left(at: w.clock.now), 900, "15 min left while paused")
            eq(w.s.nextWake, nil, "nothing due while paused")
            w.s.resume()
            eq(w.s.pomodoro.deadline, w.at("10:32:00"), "the end after 7 min of pause")
            w.run(to: "10:40:00")
            w.s.reset()
            eq(w.s.pomodoro.run, .ready, "run after Reset")
            eq(w.s.pomodoro.phase, .work, "phase after Reset")
            w.run(to: "13:00:00")
            eq(w.showTimes, ["10:32:00", "10:37:00"], "shows (the break ended at 10:37, before Reset)")
        }

        test("switch: Off stands a running pomodoro, On lets it go on by itself; a paused one stays paused") {
            let w = World("10:00:00", .pomodoro)
            w.s.start()
            w.run(to: "10:10:00")
            w.s.setEnabled(false)
            w.run(to: "11:10:00")
            eq(w.shows.count, 0, "no shows while off")
            eq(w.s.pomodoro.left(at: w.clock.now), 900, "15 min left")
            w.s.setEnabled(true)
            eq(w.s.pomodoro.run, .running, "runs again")
            w.run(to: "11:25:00")
            eq(w.showTimes, ["11:25:00"], "shows")
            w.s.pause()
            w.s.setEnabled(false)
            w.s.setEnabled(true)
            eq(w.s.pomodoro.run, .paused, "paused before Off: still paused after On")
            eq(w.s.nextWake, nil, "nothing due")
        }

        test("switch: Start while off switches the app on and the work runs at once; the app's switch follows") {
            let w = World("10:00:00", .pomodoro, enabled: false)
            var told = 0
            w.s.switchedOn = { told += 1 }
            w.run(to: "11:00:00")
            w.s.start()
            eq(w.s.enabled, true, "on")
            eq(told, 1, "the app's switch told")
            eq(w.s.pomodoro.run, .running, "runs")
            eq(w.s.pomodoro.deadline, w.at("11:25:00"), "the work's end from Start")
            w.run(to: "11:30:01")
            eq(w.showTimes, ["11:25:00", "11:30:00"], "shows")
            w.s.setMode(.hourly)
            w.s.setEnabled(false)
            w.s.start()
            eq(w.s.enabled, false, "no Start in another mode: stays off")
            eq(told, 1, "nothing told")
        }

        test("switch: Resume while off switches the app on and goes on, paused before Off or only stood by it") {
            let w = World("10:00:00", .pomodoro)
            var told = 0
            w.s.switchedOn = { told += 1 }
            w.s.start()
            w.run(to: "10:10:00")
            w.s.setEnabled(false)          // the panel shows it paused, with Resume
            w.run(to: "10:30:00")
            eq(w.shows.count, 0, "no shows while off")
            w.s.resume()
            eq(w.s.enabled, true, "on")
            eq(w.s.pomodoro.run, .running, "runs")
            eq(w.s.pomodoro.deadline, w.at("10:45:00"), "15 min left, from Resume")
            w.s.pause()
            w.s.setEnabled(false)
            w.run(to: "11:00:00")
            w.s.resume()
            eq(w.s.enabled, true, "on again")
            eq(w.s.pomodoro.deadline, w.at("11:15:00"), "paused, then off: Resume goes on from now")
            eq(told, 2, "the app's switch told each time")
            w.s.resume()
            eq(told, 2, "Resume while on and running: nothing to do")
            w.run(to: "11:15:01")
            eq(w.showTimes, ["11:15:00"], "shows")
            w.s.reset()
            w.s.setEnabled(false)
            w.s.resume()
            eq(w.s.enabled, false, "nothing to resume after Reset: stays off")
            w.s.reset()
            eq(w.s.enabled, false, "Reset while off: stays off")
        }

        test("screensaver: as the lock; the pomodoro stands and goes on after it, no shows meanwhile, none of them later") {
            let w = World("10:00:00", .pomodoro)
            w.s.start()
            w.run(to: "10:20:00")
            w.s.suspend("screensaver")
            w.run(to: "10:40:00")
            eq(w.shows.count, 0, "the work's end (10:25) inside the screensaver: no show")
            eq(w.s.pomodoro.left(at: w.clock.now), 300, "5 min left, standing")
            w.s.wake("screensaver")
            eq(w.s.pomodoro.run, .running, "runs")
            eq(w.s.pomodoro.deadline, w.at("10:45:00"), "goes on from its end")
            w.run(to: "10:45:01")
            eq(w.showTimes, ["10:45:00"], "shows")
            w.run(to: "10:47:00")
            w.s.suspend("screens")          // the screens off without the lock: the same
            w.run(to: "11:00:00")
            eq(w.s.pomodoro.left(at: w.clock.now), 180, "the break stands with its 3 min")
            w.s.wake("screens")
            eq(w.s.pomodoro.deadline, w.at("11:03:00"), "and goes on")

            let h = World("10:50:00", .hourly)
            h.s.suspend("screensaver")
            h.run(to: "12:10:00")
            h.s.wake("screensaver")
            h.run(to: "12:59:00")
            eq(h.shows.count, 0, "11:00 and 12:00 inside the screensaver: not played, not later")
            eq(h.s.nextWake, h.at("13:00:00"), "every hour: the next o'clock")

            let r = World("10:00:00", .random)      // 30-90 min, the draw in the middle: 11:00
            eq(r.s.nextWake, r.at("11:00:00"), "random's moment")
            r.s.suspend("screensaver")
            r.run(to: "11:30:00")
            r.s.wake("screensaver")
            eq(r.shows.count, 0, "random: its moment inside the screensaver not played")
            eq(r.s.nextWake, r.at("12:30:00"), "drawn again from its end")
        }

        test("sleep and lock: the pomodoro stands while any reason lasts and goes on after the last") {
            let w = World("10:00:00", .pomodoro)
            w.s.start()
            w.run(to: "10:20:00")
            w.s.suspend("sleep")
            w.run(to: "10:30:00")
            w.s.suspend("lock")
            w.run(to: "10:40:00")
            w.s.wake("sleep")
            w.run(to: "10:45:00")
            eq(w.s.pomodoro.deadline, nil, "still locked: stands")
            w.s.wake("lock")
            eq(w.s.pomodoro.deadline, w.at("10:50:00"), "5 min left from the unlock")
            w.run(to: "10:51:00")
            eq(w.showTimes, ["10:50:00"], "shows")
            w.s.setEnabled(false)
            w.s.suspend("lock")
            w.s.wake("lock")
            eq(w.s.pomodoro.deadline, nil, "unlocked but off: stands")
        }

        test("every hour: on the hour; none while off or asleep, and none of those come later") {
            let w = World("14:23:10", .hourly)
            eq(w.s.hourlyNext, w.at("15:00:00"), "the first")
            w.run(to: "17:30:00")
            eq(w.showTimes, ["15:00:00", "16:00:00", "17:00:00"], "shows")
            w.s.setEnabled(false)
            w.run(to: "19:10:00")
            w.s.setEnabled(true)
            eq(w.s.hourlyNext, w.at("20:00:00"), "after On")
            w.run(to: "20:50:00")
            w.s.suspend("sleep")
            w.run(to: "22:05:00")
            w.s.wake("sleep")
            eq(w.s.hourlyNext, w.at("23:00:00"), "after the wake")
            w.run(to: "23:10:00")
            eq(w.showTimes, ["15:00:00", "16:00:00", "17:00:00", "20:00:00", "23:00:00"], "shows")
        }

        test("every hour: a timer late by 2 s still plays, a moment found an hour late (sleep without notice) does not") {
            let w = World("14:23:10", .hourly)
            w.run(to: "15:30:00", late: 2)
            eq(w.showTimes, ["15:00:02"], "the late timer")
            eq(w.s.hourlyNext, w.at("16:00:00"), "the next stays on the hour")
            w.clock.now = w.at("17:05:00")
            w.s.tick()
            eq(w.shows.count, 1, "no show for 16:00 found at 17:05")
            eq(w.s.hourlyNext, w.at("18:00:00"), "next")
        }

        test("random: within [from, to] after the last show or the mode's start; Play now counts; a new range draws again") {
            let w = World("10:00:00", .random, draws: [0, 1, 0.5, 0.25, 0, 0])
            eq(w.s.randomNext, w.at("10:30:00"), "draw 0 of 30-90: 30 min after the start")
            w.run(to: "13:01:00")
            eq(w.showTimes, ["10:30:00", "12:00:00", "13:00:00"], "draws 1 (90 min), 0.5 (60 min)")
            eq(w.s.randomNext, w.at("13:45:00"), "draw 0.25: 45 min")
            w.clock.now = w.at("13:20:00")
            w.s.noteShow("Play now")
            eq(w.s.randomNext, w.at("13:50:00"), "Play now: 30 min from it")
            w.clock.now = w.at("13:30:00")
            w.s.setRange(1, 2)
            eq(w.s.randomNext, w.at("13:31:00"), "the new range from now")
            w.s.setRange(1, 2)
            eq(w.s.randomNext, w.at("13:31:00"), "the same range: no new draw")
        }

        test("random: Off and On before its moment keep it; a moment that went by while off or asleep is drawn again") {
            let w = World("10:00:00", .random, draws: [0.5, 0, 0])
            eq(w.s.randomNext, w.at("11:00:00"), "60 min")
            w.run(to: "10:10:00")
            w.s.setEnabled(false)
            w.run(to: "10:20:00")
            w.s.setEnabled(true)
            eq(w.s.randomNext, w.at("11:00:00"), "kept")
            w.s.suspend("screens")
            w.run(to: "11:20:00")
            w.s.wake("screens")
            eq(w.shows.count, 0, "none while the screens slept")
            eq(w.s.randomNext, w.at("11:50:00"), "drawn from the wake: 30 min")
        }

        test("a show already on: the next one is skipped, the pomodoro's phase changes all the same") {
            let w = World("14:00:00", .hourly)
            w.clock.now = w.at("14:59:50")
            w.showUntil = w.at("15:00:04")          // Play now 10 s before
            w.run(to: "16:00:30")
            eq(w.showTimes, ["16:00:00"], "15:00 skipped")
            let p = World("10:00:00", .pomodoro)
            p.s.start()
            p.run(to: "10:24:55")
            p.showUntil = p.at("10:25:09")
            p.run(to: "10:25:30")
            eq(p.shows.count, 0, "skipped")
            eq(p.s.pomodoro.phase, .rest, "the break began")
            eq(p.s.pomodoro.deadline, p.at("10:30:00"), "and ends on time")
        }

        test("a new mode drops the old schedule") {
            let w = World("10:00:00", .pomodoro)
            w.s.start()
            w.run(to: "10:10:00")
            w.s.setMode(.hourly)
            eq(w.s.pomodoro.run, .ready, "the pomodoro is reset")
            eq(w.s.hourlyNext, w.at("11:00:00"), "hourly")
            w.s.setMode(.random)
            eq(w.s.hourlyNext, nil, "hourly dropped")
            check(w.s.randomNext != nil, "random drawn")
            w.s.setMode(.pomodoro)
            eq(w.s.randomNext, nil, "random dropped")
            eq(w.s.nextWake, nil, "the pomodoro waits for Start")
            w.s.start()
            w.s.setMode(.pomodoro)
            eq(w.s.pomodoro.run, .running, "the same mode again changes nothing")
            w.s.setMode(.hourly)
            w.run(to: "12:30:00")
            eq(w.showTimes, ["11:00:00", "12:00:00"], "shows")
        }

        test("no drift: a timer late by 0.4 s every time, 20 cycles, the ends stay on the minute") {
            let w = World("09:00:00", .pomodoro)
            w.s.start()
            w.run(to: "19:00:01", late: 0.4)
            eq(w.shows.count, 40, "shows")
            eq(w.s.pomodoro.deadline, w.at("19:25:00"), "the 41st end")
            check(w.shows.allSatisfy { abs($0.at.timeIntervalSince1970.truncatingRemainder(dividingBy: 60) - 0.4) < 1e-6 },
                  "every show 0.4 s after a whole minute")
        }

        test("every hour: summer time and a half-hour time zone") {
            for (day, tz) in [("2026-10-25", "Europe/Berlin"), ("2026-03-29", "Europe/Berlin"), ("2026-11-02", "Asia/Kolkata")] {
                let w = World("\(day) 00:10:00", .hourly, tz: tz)
                w.run(to: w.at("\(day) 05:30:00"))
                let gaps = zip(w.shows.dropFirst(), w.shows).map { $0.at.timeIntervalSince($1.at) }
                check(gaps.allSatisfy { $0 == 3600 }, "\(tz) \(day): hours apart, \(gaps)")
                check(w.showTimes.allSatisfy { $0.hasSuffix(":00:00") }, "\(tz) \(day): on the hour, \(w.showTimes)")
            }
        }

        test("the fields: whole minutes within the range") {
            let r = 1...600
            eq(Scheduler.minutes("45", in: r), 45, "45")
            eq(Scheduler.minutes(" 7 ", in: r), 7, "spaces")
            eq(Scheduler.minutes("0", in: r), 1, "0")
            eq(Scheduler.minutes("-5", in: r), 1, "-5")
            eq(Scheduler.minutes("700", in: r), 600, "700")
            eq(Scheduler.minutes("2.5", in: r), nil, "2.5")
            eq(Scheduler.minutes("abc", in: r), nil, "abc")
            eq(Scheduler.minutes("", in: r), nil, "empty")
            eq(Scheduler.mmss(1500), "25:00", "25:00")
            eq(Scheduler.mmss(299.2), "5:00", "rounded up")
            eq(Scheduler.mmss(0.4), "0:01", "the last second")
            eq(Scheduler.mmss(180 * 60), "180:00", "180 min")
        }

        print("\(checks - failures)/\(checks) checks hold")
        exit(failures == 0 ? 0 : 1)
    }
}
