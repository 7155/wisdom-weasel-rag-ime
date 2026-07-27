import AppKit

@main
final class RagImeControlWebApp: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var webHost: WebHostViewController?
    private var openAgentObserver: NSObjectProtocol?
    private var editShortcutMonitor: Any?

    static func main() {
        let application = NSApplication.shared
        let delegate = RagImeControlWebApp()
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        application.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMainMenu()
        installControlEditShortcuts()
        let host = WebHostViewController()
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "澄"
        window.titlebarAppearsTransparent = false
        window.titleVisibility = .visible
        window.isMovable = true
        window.minSize = NSSize(width: 900, height: 640)
        window.contentViewController = host
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        self.webHost = host
        self.window = window
        openAgentObserver = DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.rag-ime.control.open-agent"),
            object: nil,
            queue: .main
        ) { [weak self] notification in
            let sessionId = notification.userInfo?["sessionId"] as? String ?? ""
            self?.webHost?.openAgent(sessionId: sessionId)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let openAgentObserver {
            DistributedNotificationCenter.default().removeObserver(openAgentObserver)
            self.openAgentObserver = nil
        }
        if let editShortcutMonitor {
            NSEvent.removeMonitor(editShortcutMonitor)
            self.editShortcutMonitor = nil
        }
        webHost?.shutdown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        guard let window else { return true }
        if window.isMiniaturized {
            window.deminiaturize(nil)
        }
        window.makeKeyAndOrderFront(nil)
        return true
    }

    private func installMainMenu() {
        let mainMenu = NSMenu()

        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu(title: "澄")
        applicationMenu.addItem(withTitle: "关于澄", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(NSMenuItem.separator())
        applicationMenu.addItem(withTitle: "退出澄", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        mainMenu.addItem(applicationItem)

        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        mainMenu.addItem(editItem)

        NSApplication.shared.mainMenu = mainMenu
    }

    private func installControlEditShortcuts() {
        editShortcutMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let modifiers = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            guard modifiers.contains(.control),
                  !modifiers.contains(.command),
                  !modifiers.contains(.option),
                  let key = event.charactersIgnoringModifiers?.lowercased() else {
                return event
            }
            let action: Selector?
            switch key {
            case "c": action = #selector(NSText.copy(_:))
            case "v": action = #selector(NSText.paste(_:))
            case "x": action = #selector(NSText.cut(_:))
            case "a": action = #selector(NSText.selectAll(_:))
            case "z": action = modifiers.contains(.shift) ? Selector(("redo:")) : Selector(("undo:"))
            default: action = nil
            }
            guard let action else { return event }
            let application = NSApplication.shared
            guard let target = event.window?.firstResponder ?? application.keyWindow?.firstResponder else {
                return event
            }
            return application.sendAction(action, to: target, from: nil) ? nil : event
        }
    }
}
