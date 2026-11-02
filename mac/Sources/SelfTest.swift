import AVFoundation
import AppKit
import MediaToolbox
import os

// --selftest: the show once, with numbers in the log instead of a look at the screen.
// Picture: an AVPlayerItemVideoOutput on the same item as the window's layer takes every frame the player shows,
// with its alpha: how many frames came, which frame of the show each is, the mean alpha (0..255) of some of them
// (the frames' own values from the PNGs are printed by tools for comparison), the frame on screen in the pause.
// Sound: a processing tap on each sound track measures what the player renders: from when to when there was sound
// and how loud (the tap sits before the volume and mute).

final class SoundMeter {
    let name: String
    private var lock = os_unfair_lock()
    private var first = -1.0, last = -1.0, peak: Float = 0, frames = 0
    init(_ name: String) { self.name = name }

    func record(start: Double, duration: Double, peak p: Float, frames n: Int) {
        os_unfair_lock_lock(&lock)
        frames += n
        if p > 0.001 {   // -60 dBFS
            if first < 0 { first = start }
            last = start + duration
        }
        peak = max(peak, p)
        os_unfair_lock_unlock(&lock)
    }

    var line: String {
        os_unfair_lock_lock(&lock)
        defer { os_unfair_lock_unlock(&lock) }
        if frames == 0 { return "\(name): no sound rendered" }
        return String(format: "%@: %.2f s rendered, sound above -60 dBFS from %.3f to %.3f s, peak %.1f dBFS",
                      name, Double(frames) / 48000, first, last, 20 * log10(Double(max(peak, 1e-9))))
    }
}

func makeTap(_ meter: SoundMeter) -> MTAudioProcessingTap? {
    var cb = MTAudioProcessingTapCallbacks(
        version: kMTAudioProcessingTapCallbacksVersion_0,
        clientInfo: Unmanaged.passRetained(meter).toOpaque(),
        init: { _, clientInfo, storageOut in storageOut.pointee = clientInfo },
        finalize: { tap in Unmanaged<SoundMeter>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).release() },
        prepare: nil, unprepare: nil,
        process: { tap, numberFrames, _, bufferList, numberFramesOut, flagsOut in
            var range = CMTimeRange()
            guard MTAudioProcessingTapGetSourceAudio(tap, numberFrames, bufferList, flagsOut, &range, numberFramesOut) == noErr
            else { return }
            let m = Unmanaged<SoundMeter>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).takeUnretainedValue()
            var peak: Float = 0
            for b in UnsafeMutableAudioBufferListPointer(bufferList) {
                guard let d = b.mData else { continue }
                let p = d.assumingMemoryBound(to: Float.self)
                for i in 0..<Int(b.mDataByteSize) / 4 { peak = max(peak, abs(p[i])) }
            }
            m.record(start: CMTimeGetSeconds(range.start), duration: CMTimeGetSeconds(range.duration), peak: peak,
                     frames: Int(numberFramesOut.pointee))
        })
    var tap: MTAudioProcessingTap?
    guard MTAudioProcessingTapCreate(kCFAllocatorDefault, &cb, kMTAudioProcessingTapCreationFlag_PostEffects, &tap) == noErr
    else { return nil }
    return tap
}

@MainActor
final class ShowProbe {
    private let output = AVPlayerItemVideoOutput(pixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
    private var timer: Timer?
    private var meters: [SoundMeter] = []
    private let fps: Double, cut: Int, holdStart: Double, holdEnd: Double
    private var frames = 0, withAlpha = 0, opaque = 0, lastFrame = -1, skipped = 0
    private var seen = Set<Int>()
    private var notes: [String] = []
    private var pauseFrames: [Int: Int] = [:]
    private static let watch: Set<Int> = [30, 60, 174, 400, 660, 700, 730, 736]

    init(fps: Double, cut: Int, holdStart: Double, holdEnd: Double) {
        self.fps = fps; self.cut = cut; self.holdStart = holdStart; self.holdEnd = holdEnd
    }

    func attach(item: AVPlayerItem, sound: [(String, AVMutableCompositionTrack)]) {
        item.add(output)
        let mix = AVMutableAudioMix()
        mix.inputParameters = sound.compactMap { name, track in
            let m = SoundMeter("sound \(name)")
            guard let tap = makeTap(m) else { return nil }
            meters.append(m)
            let p = AVMutableAudioMixInputParameters(track: track)
            p.audioTapProcessor = tap
            return p
        }
        item.audioMix = mix
        let t = Timer(timeInterval: 1.0 / 240, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.poll() }
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    // the show's time -> the frame of the whole show (0...736)
    private func frameAt(_ t: Double) -> Int {
        if t < holdStart - 0.001 { return Int((t * fps).rounded()) }
        if t < holdEnd - 0.001 { return cut }
        return cut + 1 + Int(((t - holdEnd) * fps).rounded())
    }

    private func poll() {
        let now = output.itemTime(forHostTime: CACurrentMediaTime())
        guard output.hasNewPixelBuffer(forItemTime: now) else { return }
        var shown = CMTime.zero
        guard let pb = output.copyPixelBuffer(forItemTime: now, itemTimeForDisplay: &shown) else { return }
        let t = CMTimeGetSeconds(shown)
        let fr = frameAt(t)
        frames += 1
        if lastFrame >= 0 && fr > lastFrame + 1 { skipped += fr - lastFrame - 1 }
        lastFrame = max(lastFrame, fr)
        seen.insert(fr)
        let a = meanAlpha(pb)
        if a > 0 && a < 255 { withAlpha += 1 }
        if a >= 254.5 { opaque += 1 }
        if t >= holdStart && t < holdEnd - 0.001 { pauseFrames[fr, default: 0] += 1 }
        if Self.watch.contains(fr) && !notes.contains(where: { $0.hasPrefix("frame \(fr) ") }) {
            notes.append(String(format: "frame %d at %.3f s: mean alpha %.3f", fr, t, a))
        }
    }

    // mean alpha over every 4th pixel each way, 0..255
    private func meanAlpha(_ pb: CVPixelBuffer) -> Double {
        CVPixelBufferLockBaseAddress(pb, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
        let w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb), rb = CVPixelBufferGetBytesPerRow(pb)
        guard let base = CVPixelBufferGetBaseAddress(pb)?.assumingMemoryBound(to: UInt8.self) else { return -1 }
        var sum = 0, n = 0
        for y in stride(from: 0, to: h, by: 4) {
            let row = base + y * rb
            for x in stride(from: 0, to: w, by: 4) { sum += Int(row[x * 4 + 3]); n += 1 }
        }
        return Double(sum) / Double(max(n, 1))
    }

    // What the window server shows of our own window (no screen recording permission needed for one's own window):
    // CGWindowListCreateImage is gone from the macOS 15 SDK headers, so it is looked up at run time.
    func captureWindow(_ number: Int, label: String) {
        typealias Fn = @convention(c) (CGRect, UInt32, UInt32, UInt32) -> Unmanaged<CGImage>?
        guard let sym = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "CGWindowListCreateImage") else {
            Log.say("selftest window \(label): CGWindowListCreateImage not available"); return
        }
        // kCGWindowListOptionIncludingWindow = 8, kCGWindowImageBoundsIgnoreFraming | BestResolution = 1 | 8
        guard let img = unsafeBitCast(sym, to: Fn.self)(.null, 8, UInt32(number), 1 | 8)?.takeRetainedValue() else {
            Log.say("selftest window \(label): no image"); return
        }
        let w = img.width, h = img.height
        var px = [UInt8](repeating: 0, count: w * h * 4)
        let ok = px.withUnsafeMutableBytes { b -> Bool in
            guard let ctx = CGContext(data: b.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                      space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return false }
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard ok else { return }
        var sum = 0, n = 0, clear = 0, solid = 0, rows = [Int](repeating: 0, count: 4)
        for y in stride(from: 0, to: h, by: 2) {
            for x in stride(from: 0, to: w, by: 2) {
                let a = Int(px[(y * w + x) * 4 + 3])
                sum += a; n += 1
                if a == 0 { clear += 1 }
                if a == 255 { solid += 1; rows[min(3, y * 4 / h)] += 1 }
            }
        }
        Log.say(String(format: "selftest window %@: %dx%d px, mean alpha %.3f, clear %.2f%%, opaque %.2f%% (by quarter of the height, top first: %@)",
                       label, w, h, Double(sum) / Double(n), Double(clear) * 100 / Double(n), Double(solid) * 100 / Double(n),
                       rows.map { String(format: "%.2f%%", Double($0) * 100 / Double(n)) }.joined(separator: " ")))
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func report() {
        Log.say("selftest picture: \(frames) frames taken from the player, \(seen.count) different frames of the show (0...\(lastFrame)), "
                + "\(skipped) skipped, \(withAlpha) with partial alpha, \(opaque) fully opaque")
        Log.say("selftest pause: frames taken while the pause was on screen: "
                + (pauseFrames.isEmpty ? "none (one frame held, no new frames: expected)" : pauseFrames.map { "\($0.key) x\($0.value)" }.joined(separator: ", ")))
        for n in notes.sorted(by: { Int($0.split(separator: " ")[1])! < Int($1.split(separator: " ")[1])! }) {
            Log.say("selftest \(n)")
        }
        for m in meters { Log.say("selftest \(m.line)") }
    }
}

// Runs the show once and quits: 0 if it played to the end, 1 if not.
@MainActor
enum SelfTest {
    static func run() {
        Log.say("selftest: \(Bundle.main.bundlePath), macOS \(ProcessInfo.processInfo.operatingSystemVersionString), muted \(Settings.shared.muted)")
        let p = ShowPlayer.shared
        p.selfTest = true
        p.onFinish = { ok in
            Log.say("selftest: \(ok ? "OK" : "FAILED")")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { exit(ok ? 0 : 1) }
        }
        p.play()
    }
}
