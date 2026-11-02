import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var panel: PanelController?
    static let openPanelNote = Notification.Name("com.valentinste.roadster.open-panel")

    nonisolated override init() { super.init() }

    func applicationDidFinishLaunching(_ n: Notification) {
        Log.say("launch: Roadster \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "?") from \(Bundle.main.bundlePath)")
        if let i = CommandLine.arguments.firstIndex(of: "--snapshot"), i + 1 < CommandLine.arguments.count {
            Snapshot.run(CommandLine.arguments[i + 1])
            exit(0)
        }
        if CommandLine.arguments.contains("--selftest") {
            SelfTest.run()
            return
        }
        // one copy at a time: a second launch opens the running copy's panel and quits
        let me = ProcessInfo.processInfo.processIdentifier
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "")
            .filter { $0.processIdentifier != me }
        if !others.isEmpty {
            Log.say("launch: already running (pid \(others.map { "\($0.processIdentifier)" }.joined(separator: ", "))), opening its panel")
            DistributedNotificationCenter.default().postNotificationName(Self.openPanelNote, object: nil, userInfo: nil, deliverImmediately: true)
            NSApp.terminate(nil)
            return
        }
        DistributedNotificationCenter.default().addObserver(forName: Self.openPanelNote, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.panel?.open() }
        }

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let b = item.button {
            let img = Bundle.main.image(forResource: "MenuBarIcon") ?? NSImage(systemSymbolName: "car.side.fill", accessibilityDescription: nil)!
            img.isTemplate = true
            img.size = NSSize(width: 32, height: 18)
            b.image = img
            b.imagePosition = .imageOnly
            b.toolTip = "Roadster"
            b.setAccessibilityLabel("Roadster")
        }
        statusItem = item
        let pc = PanelController(statusItem: item)
        panel = pc
        item.button?.target = self
        item.button?.action = #selector(togglePanel)
        item.button?.sendAction(on: [.leftMouseDown, .rightMouseDown])
        ModeTimer.shared.begin()

        DispatchQueue.main.async {
            Mover.checkOnLaunch()
            LoginItem.shared.registerOnFirstLaunch()
            if UserDefaults.standard.bool(forKey: "TestOpenPanel") {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.panel?.open() }
            }
            if let s = UserDefaults.standard.string(forKey: "TestQuitAfter"), let t = Double(s) {
                Log.say("test: quitting in \(t) s")
                DispatchQueue.main.asyncAfter(deadline: .now() + t) { NSApp.terminate(nil) }
            }
        }
    }

    @objc private func togglePanel() { panel?.toggle() }

    func applicationWillTerminate(_ n: Notification) { Log.say("quit") }
}
