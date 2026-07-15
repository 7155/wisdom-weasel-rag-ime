import AppKit

@main
final class RagImeControlWebApp: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var webHost: WebHostViewController?
    private var openAgentObserver: NSObjectProtocol?

    static func main() {
        let application = NSApplication.shared
        let delegate = RagImeControlWebApp()
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        application.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let host = WebHostViewController()
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "智鼬"
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
}
