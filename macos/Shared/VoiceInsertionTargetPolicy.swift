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

enum VoiceInsertionTargetPolicy {
    static func resolveApplication(
        focused: VoiceInsertionApplicationIdentity?,
        frontmost: VoiceInsertionApplicationIdentity
    ) -> VoiceInsertionApplicationIdentity {
        guard let focused,
              !focused.bundleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
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
        currentLength: Int
    ) -> Bool {
        currentLocation == origin + insertedUTF16Length && currentLength == 0
    }

    private static func prefersFinalPaste(bundleIdentifier: String) -> Bool {
        let bundle = bundleIdentifier.lowercased()
        let webEditorPrefixes = [
            "com.openai.codex",
            "com.openai.chat",
            "com.google.chrome",
            "com.microsoft.edgemac",
            "com.apple.safari",
            "com.brave.browser",
            "com.vivaldi.vivaldi",
            "company.thebrowser.browser",
            "org.mozilla.firefox",
        ]
        return webEditorPrefixes.contains { bundle == $0 || bundle.hasPrefix($0 + ".") }
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
