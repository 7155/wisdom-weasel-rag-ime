import AppKit
import SwiftUI

struct ShortcutRecorder: NSViewRepresentable {
    @Binding var value: String

    func makeNSView(context: Context) -> ShortcutRecorderButton {
        let button = ShortcutRecorderButton()
        button.onChange = { value = $0 }
        button.shortcut = value
        return button
    }

    func updateNSView(_ nsView: ShortcutRecorderButton, context: Context) {
        nsView.shortcut = value
    }
}

final class ShortcutRecorderButton: NSButton {
    var onChange: ((String) -> Void)?
    var shortcut = "" { didSet { if !recording { title = shortcut.isEmpty ? "录制快捷键" : shortcut } } }
    private var recording = false

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        bezelStyle = .rounded
        target = self
        action = #selector(beginRecording)
    }

    required init?(coder: NSCoder) { nil }
    override var acceptsFirstResponder: Bool { true }

    @objc private func beginRecording() {
        recording = true
        title = "请按快捷键"
        window?.makeFirstResponder(self)
    }

    override func keyDown(with event: NSEvent) {
        guard recording else { return super.keyDown(with: event) }
        if event.keyCode == 53 {
            recording = false
            title = shortcut.isEmpty ? "录制快捷键" : shortcut
            return
        }
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        var parts: [String] = []
        if flags.contains(.control) { parts.append("ctrl") }
        if flags.contains(.option) { parts.append("option") }
        if flags.contains(.shift) { parts.append("shift") }
        if flags.contains(.command) { parts.append("command") }
        guard let key = event.charactersIgnoringModifiers?.lowercased(), !key.isEmpty else { return }
        parts.append(key)
        shortcut = parts.joined(separator: "+")
        recording = false
        onChange?(shortcut)
        window?.makeFirstResponder(nil)
    }
}
