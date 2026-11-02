import AppKit
import SwiftUI

// About (design/about.html): the credits the CC BY licence of the car model asks for (CREDITS.md), the brand.
@MainActor
final class AboutWindow {
    static let shared = AboutWindow()
    private var window: NSWindow?

    func show() {
        if window == nil {
            let host = NSHostingView(rootView: AboutView())
            let size = host.fittingSize
            let w = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                             styleMask: [.titled, .closable, .fullSizeContentView], backing: .buffered, defer: false)
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.title = "About Roadster"
            w.isMovableByWindowBackground = true
            w.isReleasedWhenClosed = false
            w.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
            w.contentView = host
            w.setContentSize(size)
            w.center()
            window = w
        }
        activateApp()
        window?.makeKeyAndOrderFront(nil)
        window?.orderFrontRegardless()
    }
}

struct AboutView: View {
    @Environment(\.colorScheme) private var scheme
    private let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"

    var body: some View {
        let t = Theme(scheme)
        VStack(spacing: 0) {
            Color.clear.frame(height: 28)   // the title bar with its three buttons
            Image(nsImage: NSApp.applicationIconImage).resizable().interpolation(.high)
                .frame(width: 80, height: 80).padding(.top, 2).padding(.bottom, 8)
            Text("Roadster").font(.system(size: 15, weight: .bold))
            Text("Version \(version)").font(.system(size: 11)).foregroundColor(t.sub).padding(.top, 3).padding(.bottom, 12)
            VStack(spacing: 7) {
                Link(destination: URL(string: "https://x.com/valentinste_dev")!) {
                    Text("VALENTIN STE").font(.system(size: 12, weight: .semibold)).tracking(0.6).foregroundColor(t.blue)
                }
                Text(.init("Car model: “[Tesla Roadster 2020](https://sketchfab.com/3d-models/tesla-roadster-2020-1fbf29e297bd4a17ac39a00a378441d8)” by [metarex.4d](https://sketchfab.com/metarex.4d) on Sketchfab, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Changed: scaled, wheels rigged, materials tuned."))
                Text("Sounds: Freesound, CC0.")
                Text("Not affiliated with Tesla, Inc.")
            }
            .font(.system(size: 11))
            .lineSpacing(2.5)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 10).padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(t.card))
            .padding(.horizontal, 18)
            Text("© 2026 VALENTIN STE").font(.system(size: 10.5)).foregroundColor(t.sub).padding(.top, 10)
        }
        .padding(.bottom, 18)
        .frame(width: 300)
        .foregroundColor(t.text)
        .tint(t.blue)
        .accentColor(t.blue)
        .background(t.bg)
        .ignoresSafeArea()
    }
}
