import AppKit
import ApplicationServices

final class GlobalVoiceHotkey {
    enum MonitoringMode: String {
        case unavailable
        case eventTap = "event_tap"
        case passiveMiddleMouse = "passive_middle_mouse"
    }

    var onPress: (() -> Void)?
    var onRelease: (() -> Void)?
    var onCancel: (() -> Void)?

    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var globalMouseMonitor: Any?
    private var pressed = false
    private var activeChoice: VoiceHotkeyChoice?
    private var suppressedReleaseChoice: VoiceHotkeyChoice?
    private var configuration = VoiceHotkeyConfigStore.read()

    private let middleMouseButton: Int64 = 2
    private(set) var monitoringMode: MonitoringMode = .unavailable

    deinit { stop() }

    @discardableResult
    func start() -> Bool {
        if eventTap != nil || globalMouseMonitor != nil { return true }
        configuration = VoiceHotkeyConfigStore.read()

        // The default middle-mouse hotkey never needs a filtering event tap.
        // A stalled filter can delay every keyboard event in the login session,
        // while this passive monitor cannot block input in other applications.
        if configuration.choice == .middleMouse {
            return startPassiveMiddleMouseMonitor()
        }

        if AXIsProcessTrusted(), startListenOnlyEventTap() {
            monitoringMode = .eventTap
            return true
        }
        monitoringMode = .unavailable
        return false
    }

    private func startPassiveMiddleMouseMonitor() -> Bool {
        globalMouseMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.otherMouseDown, .otherMouseUp]
        ) { [weak self] event in
            let isDown = event.type == .otherMouseDown
            let buttonNumber = Int64(event.buttonNumber)
            DispatchQueue.main.async { [weak self] in
                self?.handlePassiveMiddleMouse(isDown: isDown, buttonNumber: buttonNumber)
            }
        }
        monitoringMode = globalMouseMonitor == nil ? .unavailable : .passiveMiddleMouse
        return globalMouseMonitor != nil
    }

    private func startListenOnlyEventTap() -> Bool {
        let mask = (CGEventMask(1) << CGEventType.keyDown.rawValue)
            | (CGEventMask(1) << CGEventType.keyUp.rawValue)
            | (CGEventMask(1) << CGEventType.flagsChanged.rawValue)
            | (CGEventMask(1) << CGEventType.tapDisabledByTimeout.rawValue)
            | (CGEventMask(1) << CGEventType.tapDisabledByUserInput.rawValue)
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: voiceHotkeyEventCallback,
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        ) else { return false }
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        eventTap = tap
        runLoopSource = source
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        return true
    }

    func stop() {
        if let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes)
        }
        if let eventTap { CGEvent.tapEnable(tap: eventTap, enable: false) }
        if let globalMouseMonitor { NSEvent.removeMonitor(globalMouseMonitor) }
        runLoopSource = nil
        eventTap = nil
        globalMouseMonitor = nil
        pressed = false
        activeChoice = nil
        suppressedReleaseChoice = nil
        monitoringMode = .unavailable
    }

    func reloadConfiguration() {
        if pressed {
            cancelActivePress()
            DispatchQueue.main.async { [weak self] in self?.onCancel?() }
        }
        stop()
        _ = start()
    }

    private func handlePassiveMiddleMouse(isDown: Bool, buttonNumber: Int64) {
        guard configuration.choice == .middleMouse, buttonNumber == middleMouseButton else { return }
        if isDown, !pressed {
            beginPress(.middleMouse)
        } else if !isDown, pressed, activeChoice == .middleMouse {
            finishPress()
        }
    }

    fileprivate func handle(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let eventTap { CGEvent.tapEnable(tap: eventTap, enable: true) }
            return Unmanaged.passUnretained(event)
        }
        let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
        let mouseButton = event.getIntegerValueField(.mouseEventButtonNumber)
        if keyCode == 53, type == .keyDown, pressed {
            cancelActivePress()
            DispatchQueue.main.async { [weak self] in self?.onCancel?() }
            return Unmanaged.passUnretained(event)
        }

        if let suppressedChoice = suppressedReleaseChoice,
           isRelease(of: suppressedChoice, type: type, keyCode: keyCode, mouseButton: mouseButton, flags: event.flags) {
            suppressedReleaseChoice = nil
            return Unmanaged.passUnretained(event)
        }

        if configuration.choice == .middleMouse {
            guard mouseButton == middleMouseButton,
                  type == .otherMouseDown || type == .otherMouseUp else {
                return Unmanaged.passUnretained(event)
            }
            if type == .otherMouseDown, !pressed {
                beginPress(.middleMouse)
            } else if type == .otherMouseUp, pressed, activeChoice == .middleMouse {
                finishPress()
            }
            return Unmanaged.passUnretained(event)
        }

        if configuration.choice == .rightOption {
            guard keyCode == 61, type == .flagsChanged else { return Unmanaged.passUnretained(event) }
            if event.flags.contains(.maskAlternate) {
                if !pressed {
                    beginPress(.rightOption)
                }
            } else if pressed, activeChoice == .rightOption {
                finishPress()
            }
            return Unmanaged.passUnretained(event)
        }

        guard keyCode == 49 else { return Unmanaged.passUnretained(event) }
        if type == .keyDown, event.flags.contains(.maskAlternate) {
            if !pressed {
                beginPress(.optionSpace)
            }
            return Unmanaged.passUnretained(event)
        }
        if type == .keyUp, pressed, activeChoice == .optionSpace {
            finishPress()
            return Unmanaged.passUnretained(event)
        }
        return Unmanaged.passUnretained(event)
    }

    private func beginPress(_ choice: VoiceHotkeyChoice) {
        pressed = true
        activeChoice = choice
        suppressedReleaseChoice = nil
        DispatchQueue.main.async { [weak self] in self?.onPress?() }
    }

    private func finishPress() {
        pressed = false
        activeChoice = nil
        DispatchQueue.main.async { [weak self] in self?.onRelease?() }
    }

    private func cancelActivePress() {
        suppressedReleaseChoice = activeChoice
        pressed = false
        activeChoice = nil
    }

    private func isRelease(
        of choice: VoiceHotkeyChoice,
        type: CGEventType,
        keyCode: Int64,
        mouseButton: Int64,
        flags: CGEventFlags
    ) -> Bool {
        switch choice {
        case .middleMouse:
            return type == .otherMouseUp && mouseButton == middleMouseButton
        case .rightOption:
            return type == .flagsChanged && keyCode == 61 && !flags.contains(.maskAlternate)
        case .optionSpace:
            return type == .keyUp && keyCode == 49
        }
    }
}

private let voiceHotkeyEventCallback: CGEventTapCallBack = { _, type, event, userInfo in
    guard let userInfo else { return Unmanaged.passUnretained(event) }
    let monitor = Unmanaged<GlobalVoiceHotkey>.fromOpaque(userInfo).takeUnretainedValue()
    return monitor.handle(type: type, event: event)
}
