// Packs show B's two clips into the movies the Mac app plays and checks them against the frames in numbers.
//
//   show_video encode --show out/show-b/final-cloud --sound out/show-b/sound/b --out out/show-b/app
//   show_video check  --show out/show-b/final-cloud --out out/show-b/app [--step 1]
//
// encode: the PNG frames of each clip (split.json: first/last of clip1, clip2) -> <out>/clip1.mov, clip2.mov:
//   HEVC with alpha (VideoToolbox, the decoder every Mac since 10.15 has) with premultiplied alpha, tagged
//   BT.709 primaries + sRGB transfer (the PNGs are sRGB, so the Mac shows the movie like the PNG), 60/s, and the
//   clip's sound as AAC 256 kbit/s. clip2's sound is longer than its picture (the tail after the car is gone):
//   the movie keeps it, the app plays it out. split.json goes next to the movies (the app reads pause_s from it).
//   --quality / --alpha-quality: VideoToolbox's colour and alpha quality (0..1); --range A:B and --no-audio
//   for quick tries (writes <out>/try-A-B.mov from frames A..B of the whole show). Defaults 0.75 / 0.85 (02.11: the
//   whole show 18 MB; smoke and shadow over black or white off by 1.2/255 on average, alpha alone 0.4/255).
// check: decodes each movie the way the Mac does (AVAssetReader, BGRA) and compares it with the frames, both
//   premultiplied: the colour over the worst desktop (black or white behind) per zone - the car (alpha 255), the
//   smoke, shadow and edges (0 < alpha < 255), the empty screen (alpha 0: any alpha there is a smudge on the
//   desktop) - mean, 99th percentile and max in 1/255; also the durations, the alpha tags and the sizes.
import AVFoundation
import Accelerate
import Foundation
import ImageIO
import VideoToolbox

setvbuf(stdout, nil, _IOLBF, 0)

struct Split: Codable {
    struct Clip: Codable { let first: Int; let last: Int }
    let fps: Int; let frames: String?; let cut: Int; let clip1: Clip; let clip2: Clip; let pause_s: Double
}

func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(1) }

var args = Array(CommandLine.arguments.dropFirst())
guard let cmd = args.first else { die("usage: show_video encode|check --show DIR [--sound DIR] --out DIR") }
args.removeFirst()
func opt(_ k: String, _ d: String? = nil) -> String? {
    if let i = args.firstIndex(of: k), i + 1 < args.count { return args[i + 1] }
    return d
}
let showDir = URL(fileURLWithPath: opt("--show", "out/show-b/final-cloud")!)
let outDir = URL(fileURLWithPath: opt("--out", "out/show-b/app")!)
let framesSub = opt("--frames", "rgba-shadow")!
let quality = Double(opt("--quality", "0.75")!)!
let alphaQuality = Double(opt("--alpha-quality", "0.85")!)!
let step = Int(opt("--step", "1")!)!
let encoderSpec: [String: Any] = {
    switch opt("--hw", "auto")! {
    case "require": return [kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder as String: true]
    case "off": return [kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder as String: false]
    default: return [:]
    }
}()
let split = try! JSONDecoder().decode(Split.self, from: Data(contentsOf: showDir.appendingPathComponent("split.json")))
let fps = Int32(split.fps)

// ---------- frames: PNG (straight RGBA 8 bit) -> premultiplied BGRA ----------

struct Frame { let w: Int; let h: Int; var px: [UInt8] }  // BGRA premultiplied, rows packed (w * 4)

func loadFrame(_ i: Int) -> Frame {
    let url = showDir.appendingPathComponent(framesSub).appendingPathComponent(String(format: "%04d.png", i))
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCache: false] as CFDictionary)
    else { die("cannot read \(url.path)") }
    guard img.bitsPerComponent == 8, img.bitsPerPixel == 32, img.alphaInfo == .last,
          let data = img.dataProvider?.data, let base = CFDataGetBytePtr(data)
    else { die("\(url.path): expected 8-bit straight RGBA, got \(img.bitsPerPixel) bpp, alpha \(img.alphaInfo.rawValue)") }
    let w = img.width, h = img.height
    var out = [UInt8](repeating: 0, count: w * h * 4)
    out.withUnsafeMutableBytes { o in
        var s = vImage_Buffer(data: UnsafeMutableRawPointer(mutating: base), height: vImagePixelCount(h),
                              width: vImagePixelCount(w), rowBytes: img.bytesPerRow)
        var d = vImage_Buffer(data: o.baseAddress!, height: vImagePixelCount(h), width: vImagePixelCount(w), rowBytes: w * 4)
        vImagePremultiplyData_RGBA8888(&s, &d, vImage_Flags(kvImageNoFlags))
        let map: [UInt8] = [2, 1, 0, 3]
        vImagePermuteChannels_ARGB8888(&d, &d, map, vImage_Flags(kvImageNoFlags))
    }
    return Frame(w: w, h: h, px: out)
}

// ---------- encode ----------

func readPCM(_ wav: URL) -> (reader: AVAssetReader, output: AVAssetReaderTrackOutput) {
    let asset = AVURLAsset(url: wav)
    guard let track = asset.tracks(withMediaType: .audio).first else { die("no audio in \(wav.path)") }
    let reader = try! AVAssetReader(asset: asset)
    let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
        AVFormatIDKey: kAudioFormatLinearPCM, AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true,
        AVLinearPCMIsNonInterleaved: false, AVLinearPCMIsBigEndianKey: false])
    reader.add(output)
    return (reader, output)
}

func setProp(_ s: VTCompressionSession, _ k: CFString, _ v: CFTypeRef) {
    let st = VTSessionSetProperty(s, key: k, value: v)
    if st != noErr { die("VT property \(k): \(st)") }
}

// VideoToolbox directly (not AVAssetWriter's own encoder): every property is set and read back before the first
// frame. Through AVAssetWriter the alpha quality took hold only in some runs (the same settings gave 1.5 or 3 MB).
func compress(first: Int, last: Int, probe: Frame) -> [CMSampleBuffer] {
    let W = probe.w, H = probe.h
    var session: VTCompressionSession?
    let st = VTCompressionSessionCreate(allocator: nil, width: Int32(W), height: Int32(H),
                                        codecType: kCMVideoCodecType_HEVCWithAlpha,
                                        encoderSpecification: encoderSpec as CFDictionary, imageBufferAttributes: nil,
                                        compressedDataAllocator: nil, outputCallback: nil, refcon: nil,
                                        compressionSessionOut: &session)
    guard st == noErr, let session else { die("VTCompressionSessionCreate: \(st)") }
    setProp(session, kVTCompressionPropertyKey_RealTime, kCFBooleanFalse)
    setProp(session, kVTCompressionPropertyKey_Quality, quality as CFNumber)
    setProp(session, kVTCompressionPropertyKey_TargetQualityForAlpha, alphaQuality as CFNumber)
    setProp(session, kVTCompressionPropertyKey_AlphaChannelMode, kVTAlphaChannelMode_PremultipliedAlpha)
    setProp(session, kVTCompressionPropertyKey_ExpectedFrameRate, Int(fps) as CFNumber)
    setProp(session, kVTCompressionPropertyKey_MaxKeyFrameInterval, Int(fps) as CFNumber)
    setProp(session, kVTCompressionPropertyKey_ColorPrimaries, kCVImageBufferColorPrimaries_ITU_R_709_2)
    setProp(session, kVTCompressionPropertyKey_TransferFunction, kCVImageBufferTransferFunction_sRGB)
    setProp(session, kVTCompressionPropertyKey_YCbCrMatrix, kCVImageBufferYCbCrMatrix_ITU_R_709_2)
    VTCompressionSessionPrepareToEncodeFrames(session)
    func get(_ k: CFString) -> String {
        var v: CFTypeRef?
        _ = withUnsafeMutablePointer(to: &v) { VTSessionCopyProperty(session, key: k, allocator: nil, valueOut: $0) }
        return v.map { "\($0)" } ?? "-"
    }
    var hw: CFTypeRef?
    _ = withUnsafeMutablePointer(to: &hw) {
        VTSessionCopyProperty(session, key: kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder, allocator: nil, valueOut: $0)
    }
    print("  encoder: quality \(get(kVTCompressionPropertyKey_Quality)), alpha quality "
          + "\(get(kVTCompressionPropertyKey_TargetQualityForAlpha)), hardware \(hw.map { "\($0)" } ?? "-")")
    var pool: CVPixelBufferPool?
    CVPixelBufferPoolCreate(nil, nil, [kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_32BGRA,
                                       kCVPixelBufferWidthKey: W, kCVPixelBufferHeightKey: H,
                                       kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &pool)
    var out = [CMSampleBuffer]()
    let lock = NSLock()
    let t0 = Date()
    for i in first...last {
        let f = i == first ? probe : loadFrame(i)
        var pb: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool!, &pb)
        guard let pb else { die("no pixel buffer") }
        CVPixelBufferLockBaseAddress(pb, [])
        let rb = CVPixelBufferGetBytesPerRow(pb), base = CVPixelBufferGetBaseAddress(pb)!
        f.px.withUnsafeBytes { s in
            for y in 0..<H { memcpy(base + y * rb, s.baseAddress! + y * W * 4, W * 4) }
        }
        CVPixelBufferUnlockBaseAddress(pb, [])
        CVBufferSetAttachment(pb, kCVImageBufferAlphaChannelModeKey, kCVImageBufferAlphaChannelMode_PremultipliedAlpha, .shouldPropagate)
        CVBufferSetAttachment(pb, kCVImageBufferColorPrimariesKey, kCVImageBufferColorPrimaries_ITU_R_709_2, .shouldPropagate)
        CVBufferSetAttachment(pb, kCVImageBufferTransferFunctionKey, kCVImageBufferTransferFunction_sRGB, .shouldPropagate)
        CVBufferSetAttachment(pb, kCVImageBufferYCbCrMatrixKey, kCVImageBufferYCbCrMatrix_ITU_R_709_2, .shouldPropagate)
        let pts = CMTime(value: CMTimeValue(i - first), timescale: fps)
        let e = VTCompressionSessionEncodeFrame(session, imageBuffer: pb, presentationTimeStamp: pts,
                                                duration: CMTime(value: 1, timescale: fps), frameProperties: nil,
                                                infoFlagsOut: nil) { status, _, sb in
            guard status == noErr, let sb else { die("encode frame \(i): \(status)") }
            lock.lock(); out.append(sb); lock.unlock()
        }
        if e != noErr { die("encode frame \(i): \(e)") }
        if (i - first) % 120 == 0 { print(String(format: "  frame %d (%.0f s)", i, Date().timeIntervalSince(t0))) }
    }
    VTCompressionSessionCompleteFrames(session, untilPresentationTimeStamp: .invalid)
    VTCompressionSessionInvalidate(session)
    lock.lock(); defer { lock.unlock() }
    // the encoder hands frames out in decode order: the order the file needs
    return out
}

func encode(first: Int, last: Int, wav: URL?, to dst: URL) {
    try? FileManager.default.removeItem(at: dst)
    let t0 = Date()
    let samples = compress(first: first, last: last, probe: loadFrame(first))
    guard let fmt = samples.first.flatMap({ CMSampleBufferGetFormatDescription($0) }) else { die("nothing encoded") }
    let writer = try! AVAssetWriter(outputURL: dst, fileType: .mov)
    writer.shouldOptimizeForNetworkUse = true
    let vin = AVAssetWriterInput(mediaType: .video, outputSettings: nil, sourceFormatHint: fmt)
    vin.expectsMediaDataInRealTime = false
    writer.add(vin)
    var audio: (reader: AVAssetReader, output: AVAssetReaderTrackOutput, input: AVAssetWriterInput)?
    if let wav {
        let (r, o) = readPCM(wav)
        let ain = AVAssetWriterInput(mediaType: .audio, outputSettings: [
            AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 48000, AVNumberOfChannelsKey: 2, AVEncoderBitRateKey: 256_000])
        ain.expectsMediaDataInRealTime = false
        writer.add(ain)
        audio = (r, o, ain)
    }
    guard writer.startWriting() else { die("writer: \(String(describing: writer.error))") }
    writer.startSession(atSourceTime: .zero)
    audio?.reader.startReading()
    let group = DispatchGroup()
    group.enter()
    var k = 0
    vin.requestMediaDataWhenReady(on: DispatchQueue(label: "video")) {
        while vin.isReadyForMoreMediaData {
            if k == samples.count { vin.markAsFinished(); group.leave(); return }
            if !vin.append(samples[k]) { die("append video \(k): \(String(describing: writer.error))") }
            k += 1
        }
    }
    if let audio {
        group.enter()
        audio.input.requestMediaDataWhenReady(on: DispatchQueue(label: "audio")) {
            while audio.input.isReadyForMoreMediaData {
                guard let sb = audio.output.copyNextSampleBuffer() else {
                    audio.input.markAsFinished(); group.leave(); return
                }
                audio.input.append(sb)
            }
        }
    }
    group.wait()
    let done = DispatchSemaphore(value: 0)
    writer.finishWriting { done.signal() }
    done.wait()
    guard writer.status == .completed else { die("writer: \(String(describing: writer.error))") }
    let size = (try? FileManager.default.attributesOfItem(atPath: dst.path)[.size] as? Int) ?? 0
    print(String(format: "-> %@: %d frames, %.2f MB, %.0f s", dst.lastPathComponent, last - first + 1,
                 Double(size) / 1e6, Date().timeIntervalSince(t0)))
}

// ---------- check ----------

struct Zone {
    var n = 0
    var hist = [Int](repeating: 0, count: 256)  // worst-channel composite error over black or white
    var sum = 0
    mutating func add(_ e: Int) { n += 1; sum += e; hist[min(e, 255)] += 1 }
    mutating func merge(_ z: Zone) { n += z.n; sum += z.sum; for k in 0..<256 { hist[k] += z.hist[k] } }
    var mean: Double { n == 0 ? 0 : Double(sum) / Double(n) }
    func pct(_ p: Double) -> Int {
        var acc = 0; let lim = Int(Double(n) * p)
        for k in 0..<256 { acc += hist[k]; if acc > lim { return k } }
        return 255
    }
    var max: Int { hist.lastIndex(where: { $0 > 0 }) ?? 0 }
}

struct Stats {
    var car = Zone(), smoke = Zone(), empty = Zone(), alphaSmoke = Zone()
    var leak2 = 0, leakMax = 0, pixels = 0
    mutating func merge(_ s: Stats) {
        car.merge(s.car); smoke.merge(s.smoke); empty.merge(s.empty); alphaSmoke.merge(s.alphaSmoke)
        leak2 += s.leak2; leakMax = max(leakMax, s.leakMax); pixels += s.pixels
    }
}

func compare(_ src: Frame, _ pb: CVPixelBuffer, straight: Bool) -> Stats {
    var st = Stats()
    CVPixelBufferLockBaseAddress(pb, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
    let rb = CVPixelBufferGetBytesPerRow(pb)
    let base = CVPixelBufferGetBaseAddress(pb)!.assumingMemoryBound(to: UInt8.self)
    let W = src.w, H = src.h
    precondition(CVPixelBufferGetWidth(pb) == W && CVPixelBufferGetHeight(pb) == H, "size differs")
    st.pixels = W * H
    src.px.withUnsafeBufferPointer { s in
        for y in 0..<H {
            let drow = base + y * rb
            for x in 0..<W {
                let si = (y * W + x) * 4, di = x * 4
                let sa = Int(s[si + 3]); var da = Int(drow[di + 3])
                var dc = (Int(drow[di]), Int(drow[di + 1]), Int(drow[di + 2]))
                if straight { dc = ((dc.0 * da + 127) / 255, (dc.1 * da + 127) / 255, (dc.2 * da + 127) / 255) }
                if sa == 0 {
                    if da >= 2 { st.leak2 += 1 }
                    if da > st.leakMax { st.leakMax = da }
                    if da == 0 && dc.0 == 0 && dc.1 == 0 && dc.2 == 0 { continue }
                }
                da = da - sa
                // composite c + (255 - a) * bg / 255: the error is dC - dA * bg / 255, worst at bg 0 or 255
                let d0 = dc.0 - Int(s[si]), d1 = dc.1 - Int(s[si + 1]), d2 = dc.2 - Int(s[si + 2])
                let e = max(abs(d0), abs(d0 - da), abs(d1), abs(d1 - da), abs(d2), abs(d2 - da))
                if sa == 0 { st.empty.add(e) } else if sa == 255 { st.car.add(e) } else {
                    st.smoke.add(e); st.alphaSmoke.add(abs(da))
                }
            }
        }
    }
    return st
}

func check(movie: URL, first: Int, last: Int) {
    let asset = AVURLAsset(url: movie)
    let size = (try? FileManager.default.attributesOfItem(atPath: movie.path)[.size] as? Int) ?? 0
    guard let vt = asset.tracks(withMediaType: .video).first else { die("no video in \(movie.path)") }
    let at = asset.tracks(withMediaType: .audio).first
    let fd = vt.formatDescriptions.first as! CMFormatDescription
    let ext = CMFormatDescriptionGetExtensions(fd) as? [String: Any] ?? [:]
    let codec = CMFormatDescriptionGetMediaSubType(fd)
    let cc = String(bytes: [24, 16, 8, 0].map { UInt8((codec >> $0) & 0xff) }, encoding: .ascii) ?? "?"
    print(String(format: "%@: %.2f MB (%.1f Mbit/s), codec %@, video %.4f s (%d frames expected), audio %@",
                 movie.lastPathComponent, Double(size) / 1e6,
                 Double(size) * 8 / 1e6 / CMTimeGetSeconds(asset.duration), cc,
                 CMTimeGetSeconds(vt.timeRange.duration), last - first + 1,
                 at.map { String(format: "%.4f s", CMTimeGetSeconds($0.timeRange.duration)) } ?? "none"))
    print("  tags: alpha \(ext[kCMFormatDescriptionExtension_AlphaChannelMode as String] ?? "-"), contains alpha "
          + "\(ext[kCMFormatDescriptionExtension_ContainsAlphaChannel as String] ?? "-"), primaries "
          + "\(ext[kCMFormatDescriptionExtension_ColorPrimaries as String] ?? "-"), transfer "
          + "\(ext[kCMFormatDescriptionExtension_TransferFunction as String] ?? "-")")
    let reader = try! AVAssetReader(asset: asset)
    let out = AVAssetReaderTrackOutput(track: vt, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
    out.alwaysCopiesSampleData = false
    reader.add(out)
    reader.startReading()
    var total = Stats(), worst = (frame: -1, mean: -1.0), n = 0, i = first, said = false
    while let sb = out.copyNextSampleBuffer() {
        defer { i += 1 }
        guard let pb = CMSampleBufferGetImageBuffer(sb) else { continue }
        let mode = CVBufferCopyAttachment(pb, kCVImageBufferAlphaChannelModeKey, nil) as? String
        let straight = mode == (kCVImageBufferAlphaChannelMode_StraightAlpha as String)
        if !said { print("  decoded as \(mode ?? "no alpha mode tag") BGRA"); said = true }
        if (i - first) % step != 0 && i != last { continue }
        let s = compare(loadFrame(i), pb, straight: straight)
        if s.smoke.mean > worst.mean { worst = (i, s.smoke.mean) }
        total.merge(s); n += 1
    }
    if i - 1 != last { print("  !! decoded \(i - first) frames, expected \(last - first + 1)") }
    let px = Double(total.pixels)
    func z(_ name: String, _ q: Zone) -> String {
        String(format: "  %@ %.1f%% of pixels: mean %.2f, p99 %d, p99.9 %d, max %d", name, Double(q.n) / px * 100, q.mean,
               q.pct(0.99), q.pct(0.999), q.max)
    }
    print("  \(n) frames compared, composite error over black or white, 1/255:")
    print(z("car (alpha 255)       ", total.car))
    print(z("smoke/shadow/edges    ", total.smoke) + String(format: "; alpha alone: mean %.2f, p99 %d", total.alphaSmoke.mean, total.alphaSmoke.pct(0.99)))
    print(z("empty (alpha 0), noise", total.empty) + String(format: "; alpha >= 2 on %d px (%.4f%%), max alpha %d",
                                                          total.leak2, Double(total.leak2) / px * 100, total.leakMax))
    print(String(format: "  worst frame for the smoke: %d (mean %.2f)", worst.frame, worst.mean))
}

// ---------- main ----------

try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
let soundDir = opt("--sound").map { URL(fileURLWithPath: $0) }
let noAudio = args.contains("--no-audio")
let range = opt("--range").map { $0.split(separator: ":").map { Int($0)! } }

switch cmd {
case "encode":
    print(String(format: "quality %.2f, alpha quality %.2f, frames %@", quality, alphaQuality, framesSub))
    if let r = range {
        encode(first: r[0], last: r[1], wav: nil, to: outDir.appendingPathComponent("try-\(r[0])-\(r[1]).mov"))
    } else {
        for (k, c) in [("clip1", split.clip1), ("clip2", split.clip2)] {
            guard let soundDir else { die("--sound DIR needed") }
            let wav = noAudio ? nil : soundDir.appendingPathComponent("\(k).wav")
            encode(first: c.first, last: c.last, wav: wav, to: outDir.appendingPathComponent("\(k).mov"))
        }
        let sj = outDir.appendingPathComponent("split.json")
        try? FileManager.default.removeItem(at: sj)
        try! FileManager.default.copyItem(at: showDir.appendingPathComponent("split.json"), to: sj)
    }
case "check":
    if let r = range {
        check(movie: outDir.appendingPathComponent("try-\(r[0])-\(r[1]).mov"), first: r[0], last: r[1])
    } else {
        check(movie: outDir.appendingPathComponent("clip1.mov"), first: split.clip1.first, last: split.clip1.last)
        check(movie: outDir.appendingPathComponent("clip2.mov"), first: split.clip2.first, last: split.clip2.last)
    }
default: die("unknown command \(cmd)")
}
