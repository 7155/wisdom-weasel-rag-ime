import AppKit

@main
final class RagImeControlWebApp: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var webHost: WebHostViewController?

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
    }

    func applicationWillTerminate(_ notification: Notification) {
        webHost?.shutdown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
