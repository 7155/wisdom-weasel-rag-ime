import AppKit
import SwiftUI

@main
struct AgentActivityPanelSnapshot {
    @MainActor
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            throw SnapshotError.missingOutputPath
        }

        let items = [
            AgentActivityItem(
                id: "local:test:thinking",
                title: "正在思考",
                detail: "正在等待 Pi 接收请求",
                state: .running,
                createdAtMs: 1
            )
        ]

        let root = AgentActivityPanel(items: items, status: "working")
            .padding(24)
            .frame(width: 780, alignment: .leading)
            .background(Color(nsColor: .textBackgroundColor))
        let hostingView = NSHostingView(rootView: root)
        hostingView.frame = NSRect(x: 0, y: 0, width: 780, height: 260)
        hostingView.layoutSubtreeIfNeeded()

        guard let bitmap = hostingView.bitmapImageRepForCachingDisplay(in: hostingView.bounds) else {
            throw SnapshotError.renderFailed
        }
        hostingView.cacheDisplay(in: hostingView.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else {
            throw SnapshotError.renderFailed
        }
        try data.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
    }
}

private enum SnapshotError: Error {
    case missingOutputPath
    case renderFailed
}
