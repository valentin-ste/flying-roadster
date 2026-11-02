import AppKit
import SwiftUI

// The tokens of design/roadster.css (Just the Video's popup), light and dark; sizes in the views are the CSS px as pt.
struct Theme {
    let bg, card, text, sub, sep, off, btn, green, work, fieldBorder, chev, blue, segOn, ring: Color

    init(_ scheme: ColorScheme) {
        if scheme == .dark {
            bg = .hex(0x000000); card = .hex(0x1C1C1E); text = .hex(0xF5F5F7); sub = .hex(0x98989F)
            sep = .hex(0x38383A); off = .hex(0x39393D); btn = .hex(0x3A3A3C); green = .hex(0x30D158); work = .hex(0xFF7A5C)
            fieldBorder = .white.opacity(0.16); chev = .hex(0x6E6E73); blue = .hex(0x0A84FF)
            segOn = .hex(0x636366); ring = .white.opacity(0.12)
        } else {
            bg = .hex(0xF2F2F7); card = .white; text = .hex(0x1C1C1E); sub = .hex(0x6B6B70)
            sep = .hex(0xE5E5EA); off = .hex(0xE3E3E8); btn = .hex(0xE3E3E8); green = .hex(0x34C759); work = .hex(0xFF6B4A)
            fieldBorder = .black.opacity(0.16); chev = .hex(0x8A8A8F); blue = .hex(0x007AFF)
            segOn = .white; ring = .black.opacity(0.08)
        }
    }
}

extension Color {
    static func hex(_ v: UInt32) -> Color {
        Color(.sRGB, red: Double(v >> 16 & 0xFF) / 255, green: Double(v >> 8 & 0xFF) / 255, blue: Double(v & 0xFF) / 255, opacity: 1)
    }
}

// Just the Video's switch: a 51x31 track (green when on), a white 27 pt knob with its shadow, a 60x40 target.
struct PillSwitch: View {
    @Binding var isOn: Bool
    var enabled = true
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let t = Theme(scheme)
        Button {
            withAnimation(.easeOut(duration: 0.18)) { isOn.toggle() }
        } label: {
            ZStack(alignment: isOn ? .trailing : .leading) {
                Capsule().fill(isOn ? t.green : t.off).frame(width: 51, height: 31)
                Circle().fill(Color.white).frame(width: 27, height: 27)
                    .shadow(color: .black.opacity(0.22), radius: 2, x: 0, y: 2)
                    .padding(2)
            }
            .frame(width: 60, height: 40)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.45)
        .accessibilityValue(isOn ? "on" : "off")
    }
}
