import AVFoundation
import AppKit

// The show: clip1.mov, its last frame held split.json's pause_s, clip2.mov (its first frame is clip 1's last, so the
// join is invisible), then clip 2's sound plays out its tail after the picture (the last frame is empty) and the
// window closes. One AVMutableComposition, so the pause is exact and the sound stays in step; the movies are HEVC
// with alpha, AVPlayerLayer draws them with their transparency into a clear window that lets every click through.
//
// Where: the frame (3024x1964, made for a 14" MacBook screen) is scaled whole, never cropped, to the largest size that
// fits the screen, centred, standing on the floor: the bottom edge of the screen, or the top of the Dock with
// `defaults write com.valentinste.roadster FloorAboveDock -int 1`.

struct ShowSplit: Decodable {
    struct Clip: Decodable { let first: Int; let last: Int }
    let fps: Int
    let cut: Int
    let clip1: Clip
    let clip2: Clip
    let pause_s: Double
}

final class OverlayWindow: NSPanel {
    init(rect: NSRect) {
        super.init(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        ignoresMouseEvents = true
        // above the Dock (20) and the menu bar (24), below menus that open while the car flies (popUpMenu, 101)
        level = .statusBar
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        isReleasedWhenClosed = false
        hidesOnDeactivate = false
        animationBehavior = .none
        isMovable = false
    }
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class ShowPlayer {
    static let shared = ShowPlayer()

    private var window: OverlayWindow?
    private var player: AVPlayer?
    private var observers: [NSObjectProtocol] = []
    private var timeObserver: Any?
    private var pauseObserver: Any?
    private var safety: DispatchWorkItem?
    private var started = Date()
    private var probe: ShowProbe?
    var selfTest = false
    var onFinish: ((Bool) -> Void)?
    private var busy = false            // from play() on: the window comes only after the movies are loaded
    var isPlaying: Bool { busy }
    // -TestFakeShow <s>: a show without a window or sound that lasts s seconds (the schedule's checks)
    private static let fakeShow = UserDefaults.standard.double(forKey: "TestFakeShow")

    func setMuted(_ m: Bool) { player?.isMuted = m }

    func play(on preferred: NSScreen? = nil) {
        guard !busy else { Log.say("show: already on, ignored"); return }
        busy = true
        if Self.fakeShow > 0 {
            Log.say(String(format: "show: a test show without a window, %.1f s", Self.fakeShow))
            ModeTimer.after(Self.fakeShow) {
                Log.say("show: the test show is over")
                self.busy = false
            }
            return
        }
        let screen = preferred ?? Self.screenUnderMouse()
        Task { @MainActor in
            do { try await start(on: screen) } catch {
                Log.say("show: cannot start: \(error)")
                finish(ok: false)
            }
        }
    }

    static func screenUnderMouse() -> NSScreen {
        let p = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(p, $0.frame, false) } ?? NSScreen.main ?? NSScreen.screens[0]
    }

    // The frame's rectangle on the screen, in points.
    static func showRect(on screen: NSScreen, aboveDock: Bool, aspect: Double) -> NSRect {
        let f = screen.frame
        let floor = aboveDock ? max(f.minY, screen.visibleFrame.minY) : f.minY
        var w = f.width, h = w / aspect
        if h > f.maxY - floor {
            h = f.maxY - floor
            w = h * aspect
        }
        let s = screen.backingScaleFactor
        w = (w * s).rounded() / s
        h = (h * s).rounded() / s
        return NSRect(x: ((f.midX - w / 2) * s).rounded() / s, y: floor, width: w, height: h)
    }

    private func start(on screen: NSScreen) async throws {
        guard let dir = Bundle.main.resourceURL?.appendingPathComponent("show") else { throw ShowError.missing("show folder") }
        let split = try JSONDecoder().decode(ShowSplit.self, from: Data(contentsOf: dir.appendingPathComponent("split.json")))
        let a1 = AVURLAsset(url: dir.appendingPathComponent("clip1.mov"))
        let a2 = AVURLAsset(url: dir.appendingPathComponent("clip2.mov"))
        guard let v1 = try await a1.loadTracks(withMediaType: .video).first,
              let v2 = try await a2.loadTracks(withMediaType: .video).first else { throw ShowError.missing("video track") }
        let s1 = try await a1.loadTracks(withMediaType: .audio).first
        let s2 = try await a2.loadTracks(withMediaType: .audio).first
        let size = try await v1.load(.naturalSize)

        let fps = CMTimeScale(split.fps)
        func f(_ n: Int) -> CMTime { CMTime(value: CMTimeValue(n), timescale: fps) }
        let n1 = split.clip1.last - split.clip1.first + 1, n2 = split.clip2.last - split.clip2.first + 1
        let pause = CMTime(seconds: max(0, split.pause_s), preferredTimescale: 6000)
        let comp = AVMutableComposition()
        guard let cv = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)
        else { throw ShowError.missing("composition track") }
        try cv.insertTimeRange(CMTimeRange(start: .zero, duration: f(n1)), of: v1, at: .zero)
        if pause > .zero {
            cv.scaleTimeRange(CMTimeRange(start: f(n1 - 1), duration: f(1)), toDuration: f(1) + pause)
        }
        let t2 = f(n1 - 1) + pause          // clip 2's frame 0 (= the held frame) in the show's time
        try cv.insertTimeRange(CMTimeRange(start: f(1), duration: f(n2 - 1)), of: v2, at: t2 + f(1))
        let pictureEnd = t2 + f(n2)
        // a sound track per clip: clip 2's runs past the picture by its tail
        var soundTracks: [(String, AVMutableCompositionTrack)] = []
        for (name, track, at) in [("clip1", s1, CMTime.zero), ("clip2", s2, t2)] {
            guard let track, let ct = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
            else { continue }
            let r = try await track.load(.timeRange)
            try ct.insertTimeRange(CMTimeRange(start: .zero, duration: r.duration), of: track, at: at)
            soundTracks.append((name, ct))
        }
        let total = comp.duration

        let item = AVPlayerItem(asset: comp)
        let player = AVPlayer(playerItem: item)
        player.isMuted = Settings.shared.muted
        player.actionAtItemEnd = .pause
        player.preventsDisplaySleepDuringVideoPlayback = false

        let rect = Self.showRect(on: screen, aboveDock: Settings.shared.floorAboveDock,
                                 aspect: Double(size.width / size.height))
        let w = OverlayWindow(rect: rect)
        let view = NSView(frame: NSRect(origin: .zero, size: rect.size))
        view.wantsLayer = true
        let layer = AVPlayerLayer(player: player)
        layer.frame = view.bounds
        layer.videoGravity = .resizeAspect
        layer.backgroundColor = nil
        layer.isOpaque = false
        layer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer?.addSublayer(layer)
        w.contentView = view

        Log.say(String(format: "show: screen %@ %.0fx%.0f pt @%.0fx, frame %.0fx%.0f px -> %.1fx%.1f pt at (%.1f, %.1f), %.3f px of the frame per screen px, floor %@",
                       screen.localizedName, screen.frame.width, screen.frame.height, screen.backingScaleFactor,
                       size.width, size.height, rect.width, rect.height, rect.minX - screen.frame.minX, rect.minY - screen.frame.minY,
                       size.width / (rect.width * screen.backingScaleFactor),
                       Settings.shared.floorAboveDock ? "top of the Dock" : "bottom of the screen")
                + String(format: " (the Dock takes %.0f pt at the bottom)", screen.visibleFrame.minY - screen.frame.minY))
        Log.say(String(format: "show: clip 1 %d frames, hold %.3f s, clip 2 %d frames (the first is the held one): picture %.3f s, sound to %.3f s, muted %@",
                       n1, CMTimeGetSeconds(pause), n2, CMTimeGetSeconds(pictureEnd), CMTimeGetSeconds(total),
                       player.isMuted ? "yes" : "no"))

        self.window = w
        self.player = player
        observers.append(NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.finish(ok: true) }
        })
        observers.append(NotificationCenter.default.addObserver(forName: .AVPlayerItemFailedToPlayToEndTime, object: item, queue: .main) { [weak self] n in
            Task { @MainActor in
                Log.say("show: failed: \(String(describing: n.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey]))")
                self?.finish(ok: false)
            }
        })
        let marks: [(CMTime, String)] = [(f(n1 - 1), "clip 1's last frame, the pause begins"),
                                         (t2 + f(1), "the pause is over, clip 2 goes on"),
                                         (pictureEnd, "the picture is over, the sound plays its tail")]
        timeObserver = player.addBoundaryTimeObserver(forTimes: marks.map { NSValue(time: $0.0) }, queue: .main) { [weak self, weak player] in
            guard let self, let player else { return }
            let now = player.currentTime()
            let m = marks.min { abs(CMTimeGetSeconds($0.0 - now)) < abs(CMTimeGetSeconds($1.0 - now)) }!
            Log.say(String(format: "show: %.3f s (wall %.3f s): %@", CMTimeGetSeconds(now), Date().timeIntervalSince(self.started), m.1))
        }
        if selfTest {
            let p = ShowProbe(fps: Double(split.fps), cut: split.cut, holdStart: CMTimeGetSeconds(f(n1 - 1)),
                              holdEnd: CMTimeGetSeconds(t2 + f(1)))
            p.attach(item: item, sound: soundTracks)
            probe = p
            // the pause: frame 660 stands still on screen for pause_s
            let at = CMTimeGetSeconds(f(n1 - 1)) + max(0.2, split.pause_s / 2)
            let mid = player.addBoundaryTimeObserver(forTimes: [NSValue(time: CMTime(seconds: at, preferredTimescale: 600))], queue: .main) { [weak self] in
                guard let self, let w = self.window else { return }
                self.probe?.captureWindow(w.windowNumber, label: "in the pause (frame \(split.cut))")
            }
            pauseObserver = mid
        }
        let s = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                Log.say("show: no end after the show's length + 5 s, closing")
                self?.finish(ok: false)
            }
        }
        safety = s
        DispatchQueue.main.asyncAfter(deadline: .now() + CMTimeGetSeconds(total) + 5, execute: s)

        w.orderFrontRegardless()
        started = Date()
        player.play()
        Log.say("show: playing")
    }

    private func finish(ok: Bool) {
        let wasOn = window != nil
        busy = false
        safety?.cancel()
        safety = nil
        for o in observers { NotificationCenter.default.removeObserver(o) }
        observers = []
        if let t = timeObserver { player?.removeTimeObserver(t) }
        if let t = pauseObserver { player?.removeTimeObserver(t) }
        timeObserver = nil
        pauseObserver = nil
        player?.pause()
        window?.orderOut(nil)
        window?.contentView = nil
        window = nil
        let probe = self.probe
        self.probe = nil
        probe?.stop()
        player?.replaceCurrentItem(with: nil)
        player = nil
        if wasOn {
            Log.say(String(format: "show: window closed at %.3f s, %@", Date().timeIntervalSince(started), ok ? "played to the end" : "stopped early"))
        }
        probe?.report()
        onFinish?(ok && wasOn)
    }
}

enum ShowError: Error { case missing(String) }
