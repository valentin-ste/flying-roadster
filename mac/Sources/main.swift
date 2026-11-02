// Roadster for Mac: a menu bar app (no Dock icon, LSUIElement) that flies the Tesla Roadster over the desktop.
// Built by tools/build_mac_app.sh (swiftc, no Xcode project). Flags for checks from the terminal:
//   --selftest   plays the show once, logs the timeline, the frames and the sound in numbers, then quits
//   --log        echoes the log to stderr (the log always goes to the unified log, subsystem com.valentinste.roadster)
import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
