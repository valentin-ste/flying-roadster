import AppKit

// Moving to /Applications. A downloaded app opened from Downloads runs from a temporary read-only copy (App
// Translocation, checked 02.11), so it could not open at login. Every launch from outside /Applications asks (no
// "don't ask again", Valentin 02.11); "Move to Applications" moves the original (for a temporary copy, the path it
// came from, via Security.framework's SecTranslocate functions, the way the LetsMove library finds it), clears the
// quarantine flag (the user already let it run; with the flag macOS would run the moved app from a temporary copy
// again), starts the moved copy and quits.
// Checks without touching /Applications: -TestApplicationsDir <dir> stands for /Applications, -TestAnswer move|later
// answers the question, -TestQuitAfter <s> quits the started copy, -TestLogFile <file> collects both copies' logs.
@MainActor
enum Mover {
    static var testDir: String? { UserDefaults.standard.string(forKey: "TestApplicationsDir") }
    static var applicationsDir: URL { URL(fileURLWithPath: testDir ?? "/Applications", isDirectory: true).resolvingSymlinksInPath() }

    static var isInApplications: Bool {
        Bundle.main.bundleURL.resolvingSymlinksInPath().path.hasPrefix(applicationsDir.path + "/")
    }

    private static let translocation: (on: Bool, original: URL?) = {
        let url = Bundle.main.bundleURL as CFURL
        typealias IsFn = @convention(c) (CFURL, UnsafeMutablePointer<Bool>, UnsafeMutablePointer<Unmanaged<CFError>?>?) -> Bool
        typealias OrigFn = @convention(c) (CFURL, UnsafeMutablePointer<Unmanaged<CFError>?>?) -> Unmanaged<CFURL>?
        let byPath = Bundle.main.bundlePath.contains("/AppTranslocation/")
        guard let h = dlopen("/System/Library/Frameworks/Security.framework/Security", RTLD_LAZY),
              let a = dlsym(h, "SecTranslocateIsTranslocatedURL"),
              let b = dlsym(h, "SecTranslocateCreateOriginalPathForURL") else { return (byPath, nil) }
        var on = false
        guard unsafeBitCast(a, to: IsFn.self)(url, &on, nil), on else { return (byPath, nil) }
        return (true, unsafeBitCast(b, to: OrigFn.self)(url, nil)?.takeRetainedValue() as URL?)
    }()

    static func checkOnLaunch() {
        guard !isInApplications else {
            Log.say("location: \(Bundle.main.bundlePath) (in Applications)")
            return
        }
        let t = translocation
        Log.say("location: \(Bundle.main.bundlePath) outside \(applicationsDir.path); temporary copy: \(t.on)"
                + (t.original.map { ", original \($0.path)" } ?? ""))
        let move: Bool
        if let a = UserDefaults.standard.string(forKey: "TestAnswer") {
            move = a == "move"
        } else {
            move = ask(temporary: t.on)
        }
        Log.say("location: answer \(move ? "Move to Applications" : "Not Now")")
        guard move else { return }
        do {
            try moveAndRelaunch()
        } catch {
            Log.say("move failed: \(error.localizedDescription)")
            let a = NSAlert()
            a.alertStyle = .warning
            a.messageText = "Roadster couldn’t move itself"
            a.informativeText = "\(error.localizedDescription)\n\nDrag Roadster to the Applications folder in Finder, then open it from there."
            a.addButton(withTitle: "OK")
            activateApp()
            a.runModal()
        }
    }

    private static func ask(temporary: Bool) -> Bool {
        let a = NSAlert()
        a.icon = NSApp.applicationIconImage
        a.messageText = "Move Roadster to Applications?"
        a.informativeText = (temporary
            ? "macOS is running a temporary copy of Roadster, so it can’t open at login."
            : "Roadster is outside the Applications folder, so it can’t open at login.")
            + " Roadster will move itself to the Applications folder and start again."
        a.addButton(withTitle: "Move to Applications")
        a.addButton(withTitle: "Not Now").keyEquivalent = "\u{1b}"
        activateApp()
        return a.runModal() == .alertFirstButtonReturn
    }

    private static func moveAndRelaunch() throws {
        let fm = FileManager.default
        let running = Bundle.main.bundleURL
        let t = translocation
        let source = t.original ?? running
        let dest = applicationsDir.appendingPathComponent(source.lastPathComponent)
        if fm.fileExists(atPath: dest.path) {
            var trashed: NSURL?
            try fm.trashItem(at: dest, resultingItemURL: &trashed)
            Log.say("move: the old \(dest.path) went to the Trash")
        }
        if t.on && t.original == nil {
            try fm.copyItem(at: running, to: dest)     // the original is unknown: copy the temporary one
            Log.say("move: copied the temporary copy to \(dest.path)")
        } else {
            do {
                try fm.moveItem(at: source, to: dest)
                Log.say("move: moved \(source.path) to \(dest.path)")
            } catch {
                try fm.copyItem(at: source, to: dest)
                var trashed: NSURL?
                try? fm.trashItem(at: source, resultingItemURL: &trashed)
                Log.say("move: copied \(source.path) to \(dest.path), the original went to the Trash")
            }
        }
        clearQuarantine(dest)
        var pass: [String] = []
        let d = UserDefaults.standard
        if let v = testDir { pass += ["-TestApplicationsDir", v] }
        if let v = d.string(forKey: "TestLogFile") { pass += ["-TestLogFile", v] }
        if let v = d.string(forKey: "TestQuitAfter") { pass += ["-TestQuitAfter", v] }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", "while /bin/kill -0 \(ProcessInfo.processInfo.processIdentifier) 2>/dev/null; do /bin/sleep 0.1; done; "
                       + "exec /usr/bin/open -n \"$0\" --args \"$@\"", dest.path] + pass
        try p.run()
        Log.say("move: starting \(dest.path) once this copy has quit")
        NSApp.terminate(nil)
    }

    private static func clearQuarantine(_ app: URL) {
        var n = 0
        let paths = [app.path] + (FileManager.default.enumerator(atPath: app.path)?.compactMap { $0 as? String }.map { app.path + "/" + $0 } ?? [])
        for p in paths where removexattr(p, "com.apple.quarantine", XATTR_NOFOLLOW) == 0 { n += 1 }
        Log.say("move: quarantine flag cleared on \(n) files")
    }
}

@MainActor
func activateApp() {
    if #available(macOS 14.0, *) { NSApp.activate() } else { NSApp.activate(ignoringOtherApps: true) }
}
