import AppKit
import SwiftUI

@main
struct AgentPersonaSheetSnapshot {
    @MainActor
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            throw SnapshotError.missingOutputPath
        }

        let roles = [
            persona(
                id: "zhiyou-v1",
                name: "智鼬",
                tagline: "热心、灵动，关键时刻可靠",
                summary: "熟悉个人输入与知识库的长期伙伴，适合回顾、检索和日常整理。",
                traits: ["自然", "温暖", "证据优先"],
                symbol: "sparkles",
                accent: "teal"
            ),
            persona(
                id: "hermes-v1",
                name: "Hermes",
                tagline: "直接、精确，善于把事情推进",
                summary: "执行导向的工作伙伴，适合诊断状态、拆解任务和形成下一步动作。",
                traits: ["直接", "克制", "行动导向"],
                symbol: "scope",
                accent: "blue"
            ),
            persona(
                id: "vcp-v1",
                name: "VCP",
                tagline: "善于串联资料、角色与工具",
                summary: "来源感更强的研究伙伴，适合展开多条线索并整理知识关系。",
                traits: ["活跃", "结构化", "多来源"],
                symbol: "point.3.connected.trianglepath.dotted",
                accent: "rose"
            ),
        ]

        let root = AgentNewSessionSheet(roles: roles) { _, _, _, _, _ in false }
            .frame(width: 540)
            .padding(18)
            .background(Color(nsColor: .windowBackgroundColor))
        let hostingView = NSHostingView(rootView: root)
        hostingView.frame = NSRect(x: 0, y: 0, width: 576, height: 620)
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

    private static func persona(
        id: String,
        name: String,
        tagline: String,
        summary: String,
        traits: [String],
        symbol: String,
        accent: String
    ) -> AgentRoleSummary {
        AgentRoleSummary(
            schemaVersion: "rag-ime.agent-persona.v1",
            roleId: id,
            version: "1",
            displayName: name,
            tagline: tagline,
            summary: summary,
            traits: traits,
            visualProfile: AgentPersonaVisualProfile(
                avatarAssetId: "rag-ime-companion-v1",
                symbolName: symbol,
                accentToken: accent
            ),
            defaults: AgentPersonaDefaults(
                modelPolicy: "session-selected",
                memoryPolicy: "personal-evidence-v1",
                toolProfileVersion: "control-center-v1"
            ),
            safetyPolicyVersion: "control-center-safe-v1",
            selectableModes: ["assistant"]
        )
    }
}

private enum SnapshotError: Error {
    case missingOutputPath
    case renderFailed
}
