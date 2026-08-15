import AppKit

final class DesktopSmokeTargetDelegate: NSObject, NSApplicationDelegate {
    private let input = NSTextField(string: "")
    private let status = NSTextField(labelWithString: "idle")
    private let stepper = NSStepper()
    private var window: NSWindow?
    private var applyCount = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        input.placeholderString = "Smoke input"
        input.setAccessibilityIdentifier("smoke-input")
        input.setAccessibilityLabel("Smoke input")

        status.setAccessibilityIdentifier("smoke-status")
        status.setAccessibilityLabel("Smoke status")

        let apply = NSButton(title: "Apply", target: self, action: #selector(applyInput))
        apply.bezelStyle = .rounded
        apply.setAccessibilityIdentifier("smoke-apply")
        let contextMenu = NSMenu(title: "Smoke context menu")
        contextMenu.addItem(withTitle: "Context item", action: nil, keyEquivalent: "")
        apply.menu = contextMenu

        stepper.minValue = 0
        stepper.maxValue = 10
        stepper.increment = 1
        stepper.doubleValue = 1
        stepper.setAccessibilityIdentifier("smoke-stepper")
        stepper.setAccessibilityLabel("Smoke stepper")

        let menu = NSPopUpButton(frame: .zero, pullsDown: false)
        menu.addItems(withTitles: ["One", "Two", "Three"])
        menu.setAccessibilityIdentifier("smoke-menu")
        menu.setAccessibilityLabel("Smoke menu")

        let document = NSTextView(frame: NSRect(x: 0, y: 0, width: 420, height: 900))
        document.isEditable = false
        document.string = (1...60).map { "Semantic desktop smoke row \($0)" }.joined(separator: "\n")
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 420, height: 130))
        scroll.hasVerticalScroller = true
        scroll.documentView = document
        scroll.setAccessibilityIdentifier("smoke-scroll")
        scroll.setAccessibilityLabel("Smoke scroll area")

        let stack = NSStackView(views: [
            NSTextField(labelWithString: "RagIme semantic desktop smoke target"),
            input,
            apply,
            status,
            stepper,
            menu,
            scroll,
        ])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        input.widthAnchor.constraint(equalToConstant: 420).isActive = true
        scroll.widthAnchor.constraint(equalToConstant: 420).isActive = true
        scroll.heightAnchor.constraint(equalToConstant: 130).isActive = true

        let content = NSView()
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 24),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -24),
        ])

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 430),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "RagIme Desktop Semantic Smoke Target"
        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    @objc private func applyInput() {
        applyCount += 1
        status.stringValue = "applied#\(applyCount):\(input.stringValue)"
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let application = NSApplication.shared
let delegate = DesktopSmokeTargetDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
