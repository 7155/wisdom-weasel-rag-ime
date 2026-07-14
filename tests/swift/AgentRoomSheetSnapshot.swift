import AppKit
import SwiftUI

@main
struct AgentRoomSheetSnapshot {
    @MainActor
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            throw AgentRoomSnapshotError.missingOutputPath
        }

        let roles = [
            persona(
                id: "zhiyou-v1",
                name: "智鼬",
                tagline: "热心、灵动，关键时刻可靠",
                symbol: "sparkles",
                accent: "teal"
            ),
            persona(
                id: "hermes-v1",
                name: "Hermes",
                tagline: "直接、精确，善于把事情推进",
                symbol: "scope",
                accent: "blue"
            ),
            persona(
                id: "vcp-v1",
                name: "VCP",
                tagline: "善于串联资料、角色与工具",
                symbol: "point.3.connected.trianglepath.dotted",
                accent: "rose"
            ),
        ]

        let root = AgentNewRoomSheet(roles: roles) { _, _, _, _ in false }
            .padding(18)
            .background(Color(nsColor: .windowBackgroundColor))
        let hostingView = NSHostingView(rootView: root)
        hostingView.frame = NSRect(x: 0, y: 0, width: 556, height: 650)
        hostingView.layoutSubtreeIfNeeded()

        guard let bitmap = hostingView.bitmapImageRepForCachingDisplay(in: hostingView.bounds) else {
            throw AgentRoomSnapshotError.renderFailed
        }
        hostingView.cacheDisplay(in: hostingView.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else {
            throw AgentRoomSnapshotError.renderFailed
        }
        try data.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
    }

    private static func persona(
        id: String,
        name: String,
        tagline: String,
        symbol: String,
        accent: String
    ) -> AgentRoleSummary {
        AgentRoleSummary(
            schemaVersion: "rag-ime.agent-persona.v1",
            roleId: id,
            version: "1",
            displayName: name,
            tagline: tagline,
            summary: tagline,
            traits: [],
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

private enum AgentRoomSnapshotError: Error {
    case missingOutputPath
    case renderFailed
}
