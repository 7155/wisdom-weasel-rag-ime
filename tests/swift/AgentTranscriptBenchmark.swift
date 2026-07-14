import AppKit
import Foundation

@main
struct AgentTranscriptBenchmark {
    @MainActor
    static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.prohibited)

        let coordinator = AgentTranscriptSurface.Coordinator()
        let scrollView = AgentTranscriptSurface.configuredScrollView()
        guard let tableView = scrollView.documentView as? NSTableView else {
            fatalError("transcript surface did not create an NSTableView")
        }
        coordinator.attach(tableView: tableView, scrollView: scrollView)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 920, height: 620),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isReleasedWhenClosed = false
        window.alphaValue = 0
        window.ignoresMouseEvents = true
        window.contentView = scrollView
        scrollView.frame = window.contentView?.bounds ?? .zero
        scrollView.autoresizingMask = [.width, .height]
        window.orderFrontRegardless()

        var rows = (0..<520).map { index in
            AgentTranscriptRow.message(
                message(
                    index: index,
                    status: "completed",
                    blockStatus: "completed",
                    text: "第 \(index + 1) 条长会话消息，用来验证时间线只创建可见行，而不是一次绘制全部五百二十行。"
                )
            )
        }

        let initialStart = CFAbsoluteTimeGetCurrent()
        coordinator.apply(
            sessionId: "agent:transcript-benchmark",
            persona: .fallbackZhiyou,
            rows: rows,
            actions: .noop,
            autoScrollRevision: "initial",
            isStreaming: false,
            reduceMotion: true
        )
        window.contentView?.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        let initialLayoutMs = (CFAbsoluteTimeGetCurrent() - initialStart) * 1_000
        settle(window: window, seconds: 0.16)
        let realizedAtStart = realizedRowCount(tableView)

        let streamStart = CFAbsoluteTimeGetCurrent()
        for update in 1...120 {
            rows[rows.count - 1] = .message(
                message(
                    index: rows.count - 1,
                    status: "streaming",
                    blockStatus: "running",
                    text: String(repeating: "流式增量内容", count: update)
                )
            )
            coordinator.apply(
                sessionId: "agent:transcript-benchmark",
                persona: .fallbackZhiyou,
                rows: rows,
                actions: .noop,
                autoScrollRevision: "stream:\(update / 12)",
                isStreaming: true,
                reduceMotion: true
            )
            tableView.layoutSubtreeIfNeeded()
            _ = RunLoop.current.run(mode: .default, before: Date())
        }
        let streamTotalMs = (CFAbsoluteTimeGetCurrent() - streamStart) * 1_000
        settle(window: window, seconds: 0.08)
        let realizedAfterStream = realizedRowCount(tableView)

        let payload: [String: Any] = [
            "schemaVersion": "rag-ime.agent-transcript-benchmark.v1",
            "rows": tableView.numberOfRows,
            "realizedRowsInitial": realizedAtStart,
            "realizedRowsAfterStream": realizedAfterStream,
            "initialLayoutMs": rounded(initialLayoutMs),
            "streamUpdates": 120,
            "streamUpdateTotalMs": rounded(streamTotalMs),
            "streamUpdateAverageMs": rounded(streamTotalMs / 120),
            "viewport": ["width": 920, "height": 620],
        ]
        let data = try! JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))

        precondition(tableView.numberOfRows == 520, "benchmark lost transcript rows")
        precondition(realizedAtStart < 64, "initial render created too many row views")
        precondition(realizedAfterStream < 64, "streaming created too many row views")
        precondition(initialLayoutMs < 500, "initial transcript layout exceeded 500 ms")
        precondition(streamTotalMs / 120 < 12, "stream update work exceeded 12 ms on average")
        window.orderOut(nil)
        coordinator.detach()
    }

    private static func message(
        index: Int,
        status: String,
        blockStatus: String,
        text: String
    ) -> AgentMessage {
        AgentMessage(
            schemaVersion: "rag-ime.agent-message.v1",
            id: "message:\(index)",
            sessionId: "agent:transcript-benchmark",
            turnId: "turn:\(index)",
            role: "user",
            status: status,
            blocks: [
                AgentBlock(
                    id: "block:\(index)",
                    type: .text,
                    status: blockStatus,
                    presentationKind: blockStatus == "running" ? "live_text" : "markdown",
                    data: .object(["text": .string(text)])
                )
            ],
            attachments: [],
            citations: [],
            createdAtMs: 1_780_000_000_000 + index,
            completedAtMs: status == "completed" ? 1_780_000_000_000 + index : nil
        )
    }

    @MainActor
    private static func settle(window: NSWindow, seconds: TimeInterval) {
        window.contentView?.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        RunLoop.current.run(until: Date(timeIntervalSinceNow: seconds))
        window.contentView?.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
    }

    @MainActor
    private static func realizedRowCount(_ tableView: NSTableView) -> Int {
        (0..<tableView.numberOfRows).reduce(into: 0) { count, row in
            if tableView.view(atColumn: 0, row: row, makeIfNecessary: false) != nil {
                count += 1
            }
        }
    }

    private static func rounded(_ value: Double) -> Double {
        (value * 100).rounded() / 100
    }
}
