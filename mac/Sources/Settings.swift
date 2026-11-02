import Foundation
import ServiceManagement

// Everything the panel shows is kept in UserDefaults (com.valentinste.roadster); the schedule follows it through
// ModeTimer (Schedule.swift). The pomodoro's run is not kept: after a launch it waits for Start. Not in the panel, for
// Valentin to try with `defaults write`:
//   FloorAboveDock  0 = the car's floor is the bottom edge of the screen (default), 1 = the top of the Dock
//   TimeScale       a check: the schedule runs this many times faster (60: a minute a second), read at launch
@MainActor
final class Settings: ObservableObject {
    static let shared = Settings()
    private let d = UserDefaults.standard

    @Published var enabled: Bool { didSet { d.set(enabled, forKey: "Enabled") } }
    @Published var mode: Mode { didSet { d.set(mode.rawValue, forKey: "Mode") } }
    @Published var workMinutes: Int { didSet { d.set(workMinutes, forKey: "PomodoroWorkMinutes") } }
    @Published var breakMinutes: Int { didSet { d.set(breakMinutes, forKey: "PomodoroBreakMinutes") } }
    @Published var randomFrom: Int { didSet { d.set(randomFrom, forKey: "RandomFromMinutes") } }
    @Published var randomTo: Int { didSet { d.set(randomTo, forKey: "RandomToMinutes") } }
    @Published var muted: Bool {
        didSet {
            d.set(muted, forKey: "Muted")
            ShowPlayer.shared.setMuted(muted)
        }
    }
    var floorAboveDock: Bool { d.integer(forKey: "FloorAboveDock") != 0 }

    private init() {
        d.register(defaults: ["Enabled": true, "Mode": Mode.pomodoro.rawValue, "PomodoroWorkMinutes": 25,
                              "PomodoroBreakMinutes": 5, "RandomFromMinutes": 30, "RandomToMinutes": 90,
                              "Muted": false, "FloorAboveDock": 0])
        enabled = d.bool(forKey: "Enabled")
        mode = Mode(rawValue: d.string(forKey: "Mode") ?? "") ?? .pomodoro
        workMinutes = d.integer(forKey: "PomodoroWorkMinutes")
        breakMinutes = d.integer(forKey: "PomodoroBreakMinutes")
        randomFrom = d.integer(forKey: "RandomFromMinutes")
        randomTo = d.integer(forKey: "RandomToMinutes")
        muted = d.bool(forKey: "Muted")
    }
}

// Open at login through SMAppService.mainApp (macOS 13+; works for an ad-hoc signed app, checked 02.11). Only from
// /Applications: a login item that points at a temporary copy or at Downloads breaks when the copy goes away.
@MainActor
final class LoginItem: ObservableObject {
    static let shared = LoginItem()
    @Published private(set) var isOn = false
    @Published private(set) var available = false

    func refresh() {
        available = Mover.isInApplications
        isOn = available && SMAppService.mainApp.status == .enabled
    }

    // --snapshot draws the switch as it is after the install (from Applications, on); the system is not asked or changed
    func showAsInstalled() { (available, isOn) = (true, true) }

    func set(_ on: Bool) {
        guard Mover.testDir == nil else { Log.say("login item: test mode, untouched"); return }
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            Log.say("login item: \(on ? "register" : "unregister") failed: \(error.localizedDescription)")
        }
        let st = SMAppService.mainApp.status
        Log.say("login item: \(Self.name(st))")
        if on && st == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
        refresh()
    }

    // The first launch from /Applications turns it on by itself (Valentin, 02.11: on by default); after that the
    // switch in the panel decides.
    func registerOnFirstLaunch() {
        refresh()
        let k = "LoginItemSetOnFirstLaunch"
        guard available, Mover.testDir == nil, !UserDefaults.standard.bool(forKey: k) else {
            Log.say("login item: \(Self.name(SMAppService.mainApp.status)) (from Applications: \(available))")
            return
        }
        UserDefaults.standard.set(true, forKey: k)
        set(true)
    }

    static func name(_ s: SMAppService.Status) -> String {
        switch s {
        case .enabled: return "enabled"
        case .notRegistered: return "not registered"
        case .requiresApproval: return "requires approval in System Settings"
        case .notFound: return "not found"
        @unknown default: return "status \(s.rawValue)"
        }
    }
}
