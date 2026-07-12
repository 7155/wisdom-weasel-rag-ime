import AppKit
import ApplicationServices
import Carbon
import Foundation

final class VoiceTextInsertionSession {
    let anchorPoint: NSPoint?
    let appBundleIdentifier: String
    private let element: AXUIElement
    private let origin: Int
    private let originalSelectionLength: Int
    private var insertedUTF16Length = 0
    private var hasAppliedRevision = false

    private init(element: AXUIElement, range: CFRange, anchorPoint: NSPoint?, appBundleIdentifier: String) {
        self.element = element
        origin = range.location
        originalSelectionLength = range.length
        self.anchorPoint = anchorPoint
        self.appBundleIdentifier = appBundleIdentifier
    }

    static func capture() throws -> VoiceTextInsertionSession {
        guard AXIsProcessTrusted() else { throw VoiceInsertionError.accessibilityUnavailable }
        let focused = try focusedElement()
        try validatePrivacy(of: focused)
        let application = try applicationIdentity(for: focused)
        guard let range = selectedRange(focused) else { throw VoiceInsertionError.selectionUnavailable }
        var selectedTextSettable = DarwinBoolean(false)
        var selectedRangeSettable = DarwinBoolean(false)
        AXUIElementIsAttributeSettable(focused, kAXSelectedTextAttribute as CFString, &selectedTextSettable)
        AXUIElementIsAttributeSettable(focused, kAXSelectedTextRangeAttribute as CFString, &selectedRangeSettable)
        guard selectedTextSettable.boolValue, selectedRangeSettable.boolValue else {
            throw VoiceInsertionError.selectionUnavailable
        }
        return VoiceTextInsertionSession(
            element: focused,
            range: range,
            anchorPoint: caretPoint(focused, range: range),
            appBundleIdentifier: application.bundleIdentifier
        )
    }

    func validateForAudioTransmission() throws {
        if IsSecureEventInputEnabled() { throw VoiceInsertionError.sensitiveField }
        guard AXIsProcessTrusted() else { throw VoiceInsertionError.accessibilityUnavailable }
        let focused = try Self.focusedElement()
        try Self.validatePrivacy(of: focused)
        guard CFEqual(focused, element) else { throw VoiceInsertionError.focusChanged }
    }

    func apply(_ revision: VoiceTranscriptRevision) throws {
        try validateForAudioTransmission()
        if hasAppliedRevision {
            guard let current = Self.selectedRange(element) else {
                throw VoiceInsertionError.privacyStateUnknown
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

    private static func focusedElement() throws -> AXUIElement {
        let system = AXUIElementCreateSystemWide()
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(
            system,
            kAXFocusedUIElementAttribute as CFString,
            &value
        ) == .success,
              let value,
              CFGetTypeID(value) == AXUIElementGetTypeID() else {
            throw VoiceInsertionError.privacyStateUnknown
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

    private static func stringAttribute(
        _ name: CFString,
        element: AXUIElement,
        required: Bool = false
    ) throws -> String {
        var value: AnyObject?
        let result = AXUIElementCopyAttributeValue(element, name, &value)
        switch result {
        case .success:
            guard let text = value as? String else { throw VoiceInsertionError.privacyStateUnknown }
            let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if required, normalized.isEmpty { throw VoiceInsertionError.privacyStateUnknown }
            return normalized
        case .attributeUnsupported, .noValue:
            if required { throw VoiceInsertionError.privacyStateUnknown }
            return ""
        default:
            throw VoiceInsertionError.privacyStateUnknown
        }
    }

    private static func validatePrivacy(of element: AXUIElement) throws {
        if IsSecureEventInputEnabled() { throw VoiceInsertionError.sensitiveField }
        let application = try applicationIdentity(for: element)
        let role = try stringAttribute(kAXRoleAttribute as CFString, element: element, required: true)
        let subrole = try stringAttribute(kAXSubroleAttribute as CFString, element: element)
        let fieldMetadata = [
            role,
            subrole,
            try stringAttribute(kAXTitleAttribute as CFString, element: element),
            try stringAttribute(kAXDescriptionAttribute as CFString, element: element),
            try stringAttribute(kAXHelpAttribute as CFString, element: element),
            try stringAttribute("AXPlaceholderValue" as CFString, element: element),
            try stringAttribute("AXIdentifier" as CFString, element: element),
        ].joined(separator: " ")
        let metadata = [fieldMetadata, try windowMetadata(for: element)]
            .joined(separator: " ")
            .lowercased()
        let tokens = [
            "securetextfield", "secure text", "password", "passcode", "one-time", "one time",
            "verification code", "username", "user name", "account", "login", "sign in", "pin",
            "密码", "验证码", "账号", "帐号", "账户", "登录", "用户名", "口令",
        ]
        if tokens.contains(where: metadata.contains) { throw VoiceInsertionError.sensitiveField }
        if VoicePrivacyPolicy.denies(
            bundleIdentifier: application.bundleIdentifier,
            applicationName: application.name,
            metadata: metadata
        ) {
            throw VoiceInsertionError.sensitiveField
        }
    }

    private static func applicationIdentity(
        for element: AXUIElement
    ) throws -> (bundleIdentifier: String, name: String) {
        var processID: pid_t = 0
        guard AXUIElementGetPid(element, &processID) == .success,
              processID > 0,
              let application = NSRunningApplication(processIdentifier: processID),
              let bundleIdentifier = application.bundleIdentifier?.trimmingCharacters(in: .whitespacesAndNewlines),
              !bundleIdentifier.isEmpty else {
            throw VoiceInsertionError.privacyStateUnknown
        }
        return (bundleIdentifier, application.localizedName ?? "")
    }

    private static func windowMetadata(for element: AXUIElement) throws -> String {
        var value: AnyObject?
        let result = AXUIElementCopyAttributeValue(element, kAXWindowAttribute as CFString, &value)
        switch result {
        case .attributeUnsupported, .noValue:
            return ""
        case .success:
            guard let value, CFGetTypeID(value) == AXUIElementGetTypeID() else {
                throw VoiceInsertionError.privacyStateUnknown
            }
            let window = value as! AXUIElement
            return try [
                stringAttribute(kAXTitleAttribute as CFString, element: window),
                stringAttribute(kAXDescriptionAttribute as CFString, element: window),
                stringAttribute(kAXHelpAttribute as CFString, element: window),
                stringAttribute(kAXDocumentAttribute as CFString, element: window),
                stringAttribute("AXIdentifier" as CFString, element: window),
            ].joined(separator: " ")
        default:
            throw VoiceInsertionError.privacyStateUnknown
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
        case .sensitiveField: return "账号、密码或 Secure Input 场景已阻止语音记录"
        case .accessibilityUnavailable: return "需要辅助功能权限才能写入当前光标"
        case .privacyStateUnknown: return "无法确认当前输入框是否安全，本次语音已停止"
        case .selectionUnavailable: return "当前输入框不支持流式替换"
        case .focusChanged: return "输入焦点已改变，本次语音已停止"
        case .cursorMoved: return "检测到光标移动，本次语音已停止"
        case .writeFailed: return "当前应用拒绝了流式写入"
        }
    }
}
