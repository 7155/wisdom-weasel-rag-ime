import Foundation

struct VoiceInsertionApplicationIdentity: Equatable {
    let bundleIdentifier: String
    let name: String

    static let unknown = VoiceInsertionApplicationIdentity(bundleIdentifier: "", name: "")
}

enum VoiceInsertionTargetMode: Equatable {
    case accessibility
    case finalPaste
}

struct VoiceInsertionSelection: Equatable {
    let location: Int
    let length: Int
}

enum VoiceInsertionTargetPolicy {
    static func resolveApplication(
        focused: VoiceInsertionApplicationIdentity?,
        frontmost: VoiceInsertionApplicationIdentity
    ) -> VoiceInsertionApplicationIdentity {
        guard let focused,
              !focused.bundleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return frontmost
        }
        let focusedBundle = normalizedBundle(focused.bundleIdentifier)
        let frontmostBundle = normalizedBundle(frontmost.bundleIdentifier)
        if !frontmostBundle.isEmpty,
           !isTransientVoiceHelper(frontmostBundle),
           !sameBundleFamily(focusedBundle, frontmostBundle) {
            // System-wide AX focus can lag behind an actual app switch. Prefer
            // the real foreground app so stale editors cannot select the wrong
            // streaming insertion strategy.
            return frontmost
        }
        return focused
    }

    static func mode(
        for application: VoiceInsertionApplicationIdentity,
        accessibilityWritable: Bool
    ) -> VoiceInsertionTargetMode {
        if prefersFinalPaste(bundleIdentifier: application.bundleIdentifier) {
            return .finalPaste
        }
        return accessibilityWritable ? .accessibility : .finalPaste
    }

    static func isSameApplication(
        captured: VoiceInsertionApplicationIdentity,
        focused: VoiceInsertionApplicationIdentity?,
        frontmost: VoiceInsertionApplicationIdentity
    ) -> Bool {
        let capturedBundle = normalizedBundle(captured.bundleIdentifier)
        let focusedBundle = normalizedBundle(focused?.bundleIdentifier ?? "")
        let frontmostBundle = normalizedBundle(frontmost.bundleIdentifier)
        guard !capturedBundle.isEmpty else {
            return true
        }
        if !focusedBundle.isEmpty, !sameBundleFamily(capturedBundle, focusedBundle) {
            return false
        }
        if frontmostBundle.isEmpty
            || sameBundleFamily(capturedBundle, frontmostBundle)
            || isTransientVoiceHelper(frontmostBundle) {
            return true
        }
        // A stale focused AX element must not hide a real foreground app switch.
        return false
    }

    static func selectionMatchesOwnRevision(
        origin: Int,
        insertedUTF16Length: Int,
        currentLocation: Int,
        currentLength: Int,
        observedAfterWrite: VoiceInsertionSelection? = nil
    ) -> Bool {
        let current = VoiceInsertionSelection(location: currentLocation, length: currentLength)
        let caretAfterRevision = VoiceInsertionSelection(
            location: origin + insertedUTF16Length,
            length: 0
        )
        let selectedRevision = VoiceInsertionSelection(
            location: origin,
            length: insertedUTF16Length
        )
        return current == caretAfterRevision
            || current == selectedRevision
            || current == observedAfterWrite
    }

    private static func prefersFinalPaste(bundleIdentifier: String) -> Bool {
        let bundle = bundleIdentifier.lowercased()
        let finalPastePrefixes = [
            "com.openai.codex",
            "com.openai.chat",
            "com.google.chrome",
            "com.microsoft.edgemac",
            "com.apple.safari",
            "com.brave.browser",
            "com.vivaldi.vivaldi",
            "company.thebrowser.browser",
            "org.mozilla.firefox",
            // Terminal accessibility trees expose scrollback selection, not a
            // replaceable document caret. Streaming AX replacement is unsafe.
            "com.apple.terminal",
            "com.googlecode.iterm2",
            "com.mitchellh.ghostty",
            "com.github.wez.wezterm",
            "net.kovidgoyal.kitty",
            "org.alacritty",
            "io.alacritty",
            "dev.warp.warp",
            "dev.warp.warp-stable",
        ]
        return finalPastePrefixes.contains { bundle == $0 || bundle.hasPrefix($0 + ".") }
    }

    private static func normalizedBundle(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private static func sameBundleFamily(_ lhs: String, _ rhs: String) -> Bool {
        lhs == rhs || lhs.hasPrefix(rhs + ".") || rhs.hasPrefix(lhs + ".")
    }

    private static func isTransientVoiceHelper(_ bundleIdentifier: String) -> Bool {
        sameBundleFamily(bundleIdentifier, "com.rag-ime.voice")
    }
}
