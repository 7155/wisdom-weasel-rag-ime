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
                id: "understand",
                title: "已经理解问题",
                detail: "正在确定需要查询的记忆范围",
                state: .completed,
                createdAtMs: 1
            ),
            AgentActivityItem(
                id: "catalog",
                title: "正在查看工具书目录",
                detail: "筛选与输入法项目相关的工具书、Group 和 Tag",
                state: .running,
                createdAtMs: 2,
                references: [
                    AgentActivityReference(kind: .book, label: "RAG-IME 设计记录"),
                    AgentActivityReference(kind: .group, label: "输入法项目"),
                    AgentActivityReference(kind: .tag, label: "Pi Agent"),
                ]
            ),
            AgentActivityItem(
                id: "recent",
                title: "等待核对近期对话",
                detail: "目录不足时会继续检索最近会话",
                state: .waiting,
                createdAtMs: 3
            ),
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
