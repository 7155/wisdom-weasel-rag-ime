import AppKit
import ApplicationServices

final class GlobalVoiceHotkey {
    var onPress: (() -> Void)?
    var onRelease: (() -> Void)?
    var onCancel: (() -> Void)?

    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var pressed = false

    deinit { stop() }

    @discardableResult
    func start() -> Bool {
        guard eventTap == nil, AXIsProcessTrusted() else { return false }
        let mask = (CGEventMask(1) << CGEventType.keyDown.rawValue)
            | (CGEventMask(1) << CGEventType.keyUp.rawValue)
            | (CGEventMask(1) << CGEventType.tapDisabledByTimeout.rawValue)
            | (CGEventMask(1) << CGEventType.tapDisabledByUserInput.rawValue)
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
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
        runLoopSource = nil
        eventTap = nil
        pressed = false
    }

    fileprivate func handle(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let eventTap { CGEvent.tapEnable(tap: eventTap, enable: true) }
            return Unmanaged.passUnretained(event)
        }
        let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
        if keyCode == 53, type == .keyDown, pressed {
            pressed = false
            DispatchQueue.main.async { [weak self] in self?.onCancel?() }
            return nil
        }
        guard keyCode == 49 else { return Unmanaged.passUnretained(event) }
        let hasOption = event.flags.contains(.maskAlternate)
        if type == .keyDown, hasOption {
            if !pressed {
                pressed = true
                DispatchQueue.main.async { [weak self] in self?.onPress?() }
            }
            return nil
        }
        if type == .keyUp, pressed {
            pressed = false
            DispatchQueue.main.async { [weak self] in self?.onRelease?() }
            return nil
        }
        return Unmanaged.passUnretained(event)
    }
}

private let voiceHotkeyEventCallback: CGEventTapCallBack = { _, type, event, userInfo in
    guard let userInfo else { return Unmanaged.passUnretained(event) }
    let monitor = Unmanaged<GlobalVoiceHotkey>.fromOpaque(userInfo).takeUnretainedValue()
    return monitor.handle(type: type, event: event)
}
