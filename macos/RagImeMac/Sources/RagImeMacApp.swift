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
        if arguments.contains("--print-config") {
            runPrintConfig()
            return
        }
        if arguments.contains("--preview-json") {
            runPreviewJSON()
            return
        }
        if arguments.contains("--preview-rime-sidecar-json") {
            runPreviewRimeSidecarJSON()
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

    private static func runPrintConfig() {
        let config = RagBridgeConfig.load()
        do {
            let data = try JSONSerialization.data(
                withJSONObject: config.dictionary(),
                options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            )
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("RagImeMac config print failed: \(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }

    private static func runPreviewJSON() {
        do {
            let bridge = RagBridgeClient()
            try bridge.initializeDatabase()
            let response = try bridge.suggest(currentInput: "SQLite 和 FTS5 第一版", recentContext: "MVP 先 local-first")
            let data = try JSONEncoder.pretty.encode(response)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("RagImeMac preview failed: \(error.localizedDescription)\n".utf8))
            exit(1)
        }
    }

    private static func runPreviewRimeSidecarJSON() {
        do {
            let bridge = RagBridgeClient()
            try bridge.initializeDatabase()
            let request = RimeSidecarRequest(
                sessionId: "squirrel-preview",
                requestSeq: 1,
                rawInput: "jiubiruwopinshishur",
                preedit: "jiubiruwopinshishur",
                committedContext: "用户正在写 RAG 输入法设计",
                maxVisibleCandidates: 5,
                maxSideCandidates: 2,
                rimeContext: RimeContextPayload(
                    candidates: [
                        RimeCandidatePayload(label: "1", text: "就比如", comment: "rime", index: 0),
                        RimeCandidatePayload(label: "2", text: "我平时输入", comment: "rime", index: 1),
                    ],
                    highlightedIndex: 0,
                    page: 0,
                    isLastPage: true
                )
            )
            let response = try bridge.rimeSuggest(request: request)
            let data = try JSONEncoder.pretty.encode(response)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("RagImeMac Rime sidecar preview failed: \(error.localizedDescription)\n".utf8))
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
            let request = RimeSidecarRequest(
                sessionId: "rag-ime-mac-preview-panel",
                requestSeq: 1,
                rawInput: "",
                preedit: "",
                commitTextPreview: "我想",
                committedContext: "我想做一个预测优先的本地 RAG 输入法",
                idleMs: 80,
                maxVisibleCandidates: 8,
                maxSideCandidates: 8,
                rimeContext: RimeContextPayload(candidates: [], highlightedIndex: 0, page: 0, isLastPage: true)
            )
            let response = try bridge.rimeSuggest(request: request)
            let anchor = NSScreen.main.map { screen in
                NSPoint(x: screen.visibleFrame.midX - 320, y: screen.visibleFrame.midY + 140)
            }
            RagCandidatePanel.shared.show(
                displayCandidates: response.displayCandidates,
                currentInput: response.semanticQuery,
                anchor: anchor,
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
