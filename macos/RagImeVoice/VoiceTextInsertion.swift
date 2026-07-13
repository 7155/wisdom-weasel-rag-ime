import AppKit
import ApplicationServices
import Carbon
import Foundation

final class VoiceTextInsertionSession {
    let anchorPoint: NSPoint?
    let appBundleIdentifier: String
    private enum InsertionMode {
        case accessibility
        case finalPaste
    }

    private let element: AXUIElement?
    private let origin: Int
    private let originalSelectionLength: Int
    private let insertionMode: InsertionMode
    private var insertedUTF16Length = 0
    private var hasAppliedRevision = false

    private init(
        element: AXUIElement?,
        range: CFRange?,
        anchorPoint: NSPoint?,
        appBundleIdentifier: String,
        insertionMode: InsertionMode
    ) {
        self.element = element
        origin = range?.location ?? 0
        originalSelectionLength = range?.length ?? 0
        self.anchorPoint = anchorPoint
        self.appBundleIdentifier = appBundleIdentifier
        self.insertionMode = insertionMode
    }

    static func capture() throws -> VoiceTextInsertionSession {
        guard AXIsProcessTrusted() else { throw VoiceInsertionError.accessibilityUnavailable }
        if IsSecureEventInputEnabled() { throw VoiceInsertionError.sensitiveField }
        let application = frontmostApplicationIdentity()
        if VoicePrivacyPolicy.denies(
            bundleIdentifier: application.bundleIdentifier,
            applicationName: application.name,
            metadata: ""
        ) {
            throw VoiceInsertionError.sensitiveField
        }
        guard let focused = focusedElement() else {
            return finalPasteSession(application: application)
        }
        try validatePrivacy(of: focused, fallbackApplication: application)
        let range = selectedRange(focused)
        if prefersFinalPaste(bundleIdentifier: application.bundleIdentifier) {
            return finalPasteSession(
                application: application,
                anchorPoint: range.flatMap { caretPoint(focused, range: $0) }
            )
        }
        guard let range else {
            return finalPasteSession(application: application)
        }
        var selectedTextSettable = DarwinBoolean(false)
        var selectedRangeSettable = DarwinBoolean(false)
        AXUIElementIsAttributeSettable(focused, kAXSelectedTextAttribute as CFString, &selectedTextSettable)
        AXUIElementIsAttributeSettable(focused, kAXSelectedTextRangeAttribute as CFString, &selectedRangeSettable)
        guard selectedTextSettable.boolValue, selectedRangeSettable.boolValue else {
            return finalPasteSession(
                application: application,
                anchorPoint: caretPoint(focused, range: range)
            )
        }
        return VoiceTextInsertionSession(
            element: focused,
            range: range,
            anchorPoint: caretPoint(focused, range: range),
            appBundleIdentifier: application.bundleIdentifier,
            insertionMode: .accessibility
        )
    }

    func validateForAudioTransmission() throws {
        if IsSecureEventInputEnabled() { throw VoiceInsertionError.sensitiveField }
        guard AXIsProcessTrusted() else { throw VoiceInsertionError.accessibilityUnavailable }
    }

    func apply(_ revision: VoiceTranscriptRevision) throws {
        try validateForAudioTransmission()
        if insertionMode == .finalPaste {
            guard revision.isFinal, !revision.text.isEmpty else { return }
            try validateFinalPasteTarget()
            try Self.pasteFinalText(revision.text)
            hasAppliedRevision = true
            return
        }
        guard let element else { throw VoiceInsertionError.writeFailed }
        if hasAppliedRevision {
            guard let current = Self.selectedRange(element) else {
                throw VoiceInsertionError.cursorMoved
            }
            let expected = origin + insertedUTF16Length
            guard current.location == expected, current.length == 0 else {
                throw VoiceInsertionError.cursorMoved
            }
        }
        let replacementLength = hasAppliedRevision ? revision.replacementUTF16Length : originalSelectionLength
        var replacementRange = CFRange(location: origin, length: replacementLength)
        guard let rangeValue = AXValueCreate(.cfRange, &replacementRange),
              AXUIElementSetAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, rangeValue) == .success,
              AXUIElementSetAttributeValue(element, kAXSelectedTextAttribute as CFString, revision.text as CFTypeRef) == .success else {
            throw VoiceInsertionError.writeFailed
        }
        insertedUTF16Length = revision.text.utf16.count
        hasAppliedRevision = true
    }

    private static func finalPasteSession(
        application: (bundleIdentifier: String, name: String),
        anchorPoint: NSPoint? = nil
    ) -> VoiceTextInsertionSession {
        VoiceTextInsertionSession(
            element: nil,
            range: nil,
            anchorPoint: anchorPoint,
            appBundleIdentifier: application.bundleIdentifier,
            insertionMode: .finalPaste
        )
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

    private static func focusedElement() -> AXUIElement? {
        let system = AXUIElementCreateSystemWide()
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(
            system,
            kAXFocusedUIElementAttribute as CFString,
            &value
        ) == .success,
              let value,
              CFGetTypeID(value) == AXUIElementGetTypeID() else {
            return nil
        }
        return (value as! AXUIElement)
    }

    private static func selectedRange(_ element: AXUIElement) -> CFRange? {
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(element, kAXSelectedTextRangeAttribute as CFString, &value) == .success,
              let value,
              CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        let axValue = value as! AXValue
        var range = CFRange(location: 0, length: 0)
        guard AXValueGetValue(axValue, .cfRange, &range), range.location != kCFNotFound else { return nil }
        return range
    }

    private static func stringAttribute(_ name: CFString, element: AXUIElement) -> String {
        var value: AnyObject?
        let result = AXUIElementCopyAttributeValue(element, name, &value)
        guard result == .success else { return "" }
        let text: String
        if let string = value as? String {
            text = string
        } else if let url = value as? URL {
            text = url.absoluteString
        } else {
            // WebView-backed editors often omit attributes or expose values in
            // private types. Under a denylist policy, unreadable metadata is
            // not itself a reason to reject ordinary voice input.
            return ""
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func validatePrivacy(
        of element: AXUIElement,
        fallbackApplication: (bundleIdentifier: String, name: String)
    ) throws {
        if IsSecureEventInputEnabled() { throw VoiceInsertionError.sensitiveField }
        let application = applicationIdentity(for: element, fallback: fallbackApplication)
        let role = stringAttribute(kAXRoleAttribute as CFString, element: element)
        let subrole = stringAttribute(kAXSubroleAttribute as CFString, element: element)
        let fieldMetadata = [
            role,
            subrole,
            stringAttribute(kAXTitleAttribute as CFString, element: element),
            stringAttribute(kAXDescriptionAttribute as CFString, element: element),
            stringAttribute(kAXHelpAttribute as CFString, element: element),
            stringAttribute("AXPlaceholderValue" as CFString, element: element),
            stringAttribute("AXIdentifier" as CFString, element: element),
        ].joined(separator: " ").lowercased()
        let tokens = [
            "securetextfield", "secure text", "password", "passcode", "密码", "口令",
        ]
        if tokens.contains(where: fieldMetadata.contains) { throw VoiceInsertionError.sensitiveField }
        let metadata = [fieldMetadata, windowMetadata(for: element)]
            .joined(separator: " ")
            .lowercased()
        if VoicePrivacyPolicy.denies(
            bundleIdentifier: application.bundleIdentifier,
            applicationName: application.name,
            metadata: metadata
        ) {
            throw VoiceInsertionError.sensitiveField
        }
    }

    private static func frontmostApplicationIdentity() -> (bundleIdentifier: String, name: String) {
        guard let application = NSWorkspace.shared.frontmostApplication else { return ("", "") }
        return (
            application.bundleIdentifier?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "",
            application.localizedName ?? ""
        )
    }

    private static func applicationIdentity(
        for element: AXUIElement,
        fallback: (bundleIdentifier: String, name: String)
    ) -> (bundleIdentifier: String, name: String) {
        var processID: pid_t = 0
        guard AXUIElementGetPid(element, &processID) == .success,
              processID > 0,
              let application = NSRunningApplication(processIdentifier: processID),
              let bundleIdentifier = application.bundleIdentifier?.trimmingCharacters(in: .whitespacesAndNewlines),
              !bundleIdentifier.isEmpty else {
            return fallback
        }
        return (bundleIdentifier, application.localizedName ?? "")
    }

    private static func windowMetadata(for element: AXUIElement) -> String {
        var value: AnyObject?
        let result = AXUIElementCopyAttributeValue(element, kAXWindowAttribute as CFString, &value)
        switch result {
        case .attributeUnsupported, .noValue:
            return ""
        case .success:
            guard let value, CFGetTypeID(value) == AXUIElementGetTypeID() else {
                return ""
            }
            let window = value as! AXUIElement
            return [
                stringAttribute(kAXTitleAttribute as CFString, element: window),
                stringAttribute(kAXDescriptionAttribute as CFString, element: window),
                stringAttribute(kAXHelpAttribute as CFString, element: window),
                stringAttribute(kAXDocumentAttribute as CFString, element: window),
                stringAttribute("AXIdentifier" as CFString, element: window),
            ].joined(separator: " ")
        default:
            return ""
        }
    }

    private func validateFinalPasteTarget() throws {
        let currentApplication = Self.frontmostApplicationIdentity()
        if !appBundleIdentifier.isEmpty,
           !currentApplication.bundleIdentifier.isEmpty,
           currentApplication.bundleIdentifier != appBundleIdentifier {
            throw VoiceInsertionError.focusChanged
        }
        if let focused = Self.focusedElement() {
            try Self.validatePrivacy(of: focused, fallbackApplication: currentApplication)
        }
    }

    private static func pasteFinalText(_ text: String) throws {
        let pasteboard = NSPasteboard.general
        let snapshot = pasteboard.pasteboardItems?.map { item in
            item.types.reduce(into: [NSPasteboard.PasteboardType: Data]()) { values, type in
                values[type] = item.data(forType: type)
            }
        } ?? []
        pasteboard.clearContents()
        guard pasteboard.setString(text, forType: .string) else {
            throw VoiceInsertionError.writeFailed
        }
        let writtenChangeCount = pasteboard.changeCount
        guard let keyDown = CGEvent(
            keyboardEventSource: nil,
            virtualKey: CGKeyCode(kVK_ANSI_V),
            keyDown: true
        ), let keyUp = CGEvent(
            keyboardEventSource: nil,
            virtualKey: CGKeyCode(kVK_ANSI_V),
            keyDown: false
        ) else {
            throw VoiceInsertionError.writeFailed
        }
        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        keyDown.post(tap: .cghidEventTap)
        keyUp.post(tap: .cghidEventTap)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            guard pasteboard.changeCount == writtenChangeCount else { return }
            pasteboard.clearContents()
            let restored = snapshot.map { values -> NSPasteboardItem in
                let item = NSPasteboardItem()
                for (type, data) in values { item.setData(data, forType: type) }
                return item
            }
            if !restored.isEmpty { pasteboard.writeObjects(restored) }
        }
    }

    private static func caretPoint(_ element: AXUIElement, range: CFRange) -> NSPoint? {
        var range = CFRange(location: range.location, length: 0)
        guard let rangeValue = AXValueCreate(.cfRange, &range) else { return nil }
        var value: AnyObject?
        guard AXUIElementCopyParameterizedAttributeValue(
            element,
            kAXBoundsForRangeParameterizedAttribute as CFString,
            rangeValue,
            &value
        ) == .success, let value else { return nil }
        guard CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        let boundsValue = value as! AXValue
        var rect = CGRect.zero
        guard AXValueGetValue(boundsValue, .cgRect, &rect) else { return nil }
        let primaryTop = NSScreen.screens.map(\.frame.maxY).max() ?? 0
        return NSPoint(x: rect.midX, y: primaryTop - rect.maxY)
    }
}

enum VoiceInsertionError: LocalizedError {
    case sensitiveField
    case accessibilityUnavailable
    case privacyStateUnknown
    case selectionUnavailable
    case focusChanged
    case cursorMoved
    case writeFailed

    var errorDescription: String? {
        switch self {
        case .sensitiveField: return "密码框、隐私模式或黑名单应用已阻止语音输入"
        case .accessibilityUnavailable: return "需要辅助功能权限才能写入当前光标"
        case .privacyStateUnknown: return "语音输入会话状态异常，请重试"
        case .selectionUnavailable: return "当前输入框不支持流式替换"
        case .focusChanged: return "输入焦点已改变，本次语音已停止"
        case .cursorMoved: return "检测到光标移动，本次语音已停止"
        case .writeFailed: return "当前应用拒绝了流式写入"
        }
    }
}
