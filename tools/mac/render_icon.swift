// Renders an SVG (NSImage reads SVG on the build Mac) into an .iconset for iconutil: 16..512 pt at 1x and 2x.
//   render_icon design/icon/app-icon-placeholder.svg out/AppIcon.iconset
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let img = NSImage(contentsOfFile: args[1]) else {
    FileHandle.standardError.write("usage: render_icon <svg> <dir.iconset>\n".data(using: .utf8)!); exit(1)
}
let dir = URL(fileURLWithPath: args[2])
try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
for pt in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let px = pt * scale
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4,
                                   hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = NSSize(width: pt, height: pt)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current?.imageInterpolation = .high
        img.draw(in: NSRect(x: 0, y: 0, width: pt, height: pt))
        NSGraphicsContext.restoreGraphicsState()
        let name = "icon_\(pt)x\(pt)" + (scale == 2 ? "@2x" : "") + ".png"
        try! rep.representation(using: .png, properties: [:])!.write(to: dir.appendingPathComponent(name))
    }
}
