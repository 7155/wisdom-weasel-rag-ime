import AppKit
import InputMethodKit

final class RagImeAppDelegate: NSObject, NSApplicationDelegate {
    private var server: IMKServer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let bundle = Bundle.main
        let connectionName = bundle.object(forInfoDictionaryKey: "InputMethodConnectionName") as? String
            ?? "dev.local.inputmethod.RagImeMac_Connection"
        server = IMKServer(name: connectionName, bundleIdentifier: bundle.bundleIdentifier)
        NSApp.setActivationPolicy(.accessory)
        NSLog("RAG IME InputMethodKit server started: \(connectionName)")
    }

    func applicationWillTerminate(_ notification: Notification) {
        RagCandidatePanel.shared.hide()
    }
}

@main
enum RagImeMacMain {
    static func main() {
        let arguments = Set(CommandLine.arguments.dropFirst())
        if arguments.contains("--preview-json") {
            runPreviewJSON()
            return
        }
        if arguments.contains("--preview-panel") {
            runPreviewPanel()
            return
        }

        let app = NSApplication.shared
        let delegate = RagImeAppDelegate()
        app.delegate = delegate
        app.run()
        _ = delegate
    }

    private static func runPreviewJSON() {
        do {
            let bridge = RagBridgeClient()
            try bridge.initializeDatabase()
            try bridge.seedDemo(reset: true)
            let response = try bridge.suggest(currentInput: "SQLite 和 FTS5 第一版", recentContext: "MVP 先 local-first")
            let data = try JSONEncoder.pretty.encode(response)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("RagImeMac preview failed: \(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }

    private static func runPreviewPanel() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        app.activate(ignoringOtherApps: true)

        do {
            let bridge = RagBridgeClient()
            try bridge.initializeDatabase()
            try bridge.seedDemo(reset: true)
            let response = try bridge.suggest(currentInput: "SQLite 和 FTS5 第一版", recentContext: "MVP 先 local-first")
            let anchor = NSScreen.main.map { screen in
                NSPoint(x: screen.visibleFrame.midX - 320, y: screen.visibleFrame.midY + 140)
            }
            RagCandidatePanel.shared.show(
                modelPredictions: response.modelPredictions ?? [],
                suggestions: response.suggestions,
                currentInput: response.currentInput,
                anchor: anchor,
                onSelectModel: { _, _ in },
                onSelect: { _, _ in },
                onAction: { _, _ in }
            )
            DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
                app.terminate(nil)
            }
            app.run()
        } catch {
            FileHandle.standardError.write(Data("RagImeMac panel preview failed: \(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }
}

private extension JSONEncoder {
    static var pretty: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return encoder
    }
}
