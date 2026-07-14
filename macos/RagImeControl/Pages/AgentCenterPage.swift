import SwiftUI

enum AgentCenterSection: String, CaseIterable, Identifiable {
    case conversations
    case rooms
    case personas

    var id: String { rawValue }

    var title: String {
        switch self {
        case .conversations: "对话"
        case .rooms: "群组"
        case .personas: "角色"
        }
    }

    var symbol: String {
        switch self {
        case .conversations: "bubble.left.and.bubble.right"
        case .rooms: "person.3"
        case .personas: "person.crop.square"
        }
    }
}

@MainActor
final class AgentCenterNavigationModel: ObservableObject {
    @Published var section: AgentCenterSection = .conversations
}

struct AgentCenterPage: View {
    @EnvironmentObject private var navigation: AgentCenterNavigationModel
    @EnvironmentObject private var conversationStore: AgentWorkspaceStore
    @EnvironmentObject private var roomStore: AgentRoomWorkspaceStore

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Label("Agent 控制中心", systemImage: "sparkles.rectangle.stack")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(.secondary)

                Spacer()

                Picker("Agent 视图", selection: $navigation.section) {
                    ForEach(AgentCenterSection.allCases) { section in
                        Label(section.title, systemImage: section.symbol)
                            .tag(section)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 276)

                Spacer()

                Color.clear.frame(width: 132, height: 1)
            }
            .padding(.horizontal, 14)
            .frame(height: 42)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()

            Group {
                switch navigation.section {
                case .conversations:
                    AgentConversationPage()
                case .rooms:
                    AgentRoomsPage()
                case .personas:
                    AgentPersonaDirectoryPage()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .transaction { transaction in
                // Navigation must commit in the current click, not after an
                // animated teardown of a live transcript surface.
                transaction.animation = nil
            }
        }
        .onChange(of: navigation.section) { section in
            if section != .conversations { conversationStore.suspendStream() }
            if section != .rooms { roomStore.suspendStream() }
        }
        .onDisappear {
            conversationStore.suspendStream()
            roomStore.suspendStream()
        }
    }
}

private struct AgentPersonaDirectoryPage: View {
    @EnvironmentObject private var store: AgentRoomWorkspaceStore
    @State private var selectedPersonaId = AgentRoleSummary.fallbackZhiyou.id

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                HStack {
                    Text("角色目录")
                        .font(.callout.weight(.semibold))
                    Spacer()
                    Text("\(personas.count)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 13)
                .frame(height: 48)

                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(personas) { persona in
                            Button {
                                selectedPersonaId = persona.id
                            } label: {
                                HStack(spacing: 10) {
                                    AgentPersonaMark(persona: persona, state: .idle, size: 34, animates: false)
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(persona.displayName)
                                            .font(.callout.weight(.semibold))
                                            .foregroundStyle(.primary)
                                        Text(persona.tagline)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                    Spacer(minLength: 4)
                                }
                                .padding(.horizontal, 9)
                                .frame(maxWidth: .infinity, minHeight: 54, alignment: .leading)
                                .background(
                                    selectedPersonaId == persona.id
                                        ? ControlDesign.brand.opacity(0.095)
                                        : Color.clear
                                )
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(8)
                }
            }
            .frame(width: 246)
            .background(Color(nsColor: .underPageBackgroundColor))

            Divider()

            personaDetail
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .textBackgroundColor))
        }
        .task {
            await store.loadPersonaCatalog()
            if !personas.contains(where: { $0.id == selectedPersonaId }) {
                selectedPersonaId = personas.first?.id ?? AgentRoleSummary.fallbackZhiyou.id
            }
        }
    }

    private var personaDetail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .center, spacing: 16) {
                    AgentPersonaMark(persona: selectedPersona, state: .idle, size: 64)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(selectedPersona.displayName)
                            .font(.system(size: 24, weight: .semibold))
                        Text(selectedPersona.tagline)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text("v\(selectedPersona.version)")
                        .font(.caption.monospacedDigit().weight(.medium))
                        .foregroundStyle(.secondary)
                }

                Text(selectedPersona.summary ?? selectedPersona.tagline)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Divider()

                detailSection("表达风格") {
                    HStack(spacing: 8) {
                        ForEach(selectedPersona.traits ?? [], id: \.self) { trait in
                            Label(trait, systemImage: "checkmark")
                                .font(.caption.weight(.medium))
                                .foregroundStyle(ControlDesign.brand)
                        }
                    }
                }

                detailSection("运行默认值") {
                    VStack(alignment: .leading, spacing: 9) {
                        detailRow("模型", selectedPersona.defaults?.modelPolicy ?? "session-selected")
                        detailRow("记忆", selectedPersona.defaults?.memoryPolicy ?? "personal-evidence-v1")
                        detailRow("工具", selectedPersona.defaults?.toolProfileVersion ?? "control-center-v1")
                    }
                }

                detailSection("安全边界") {
                    Label(
                        "角色只改变表达与呈现；Session 模式、工具、审批和工作区权限保持独立。",
                        systemImage: "lock.shield"
                    )
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: 720, alignment: .leading)
            .padding(.horizontal, 38)
            .padding(.vertical, 34)
            .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private var personas: [AgentRoleSummary] {
        store.roleCatalog.isEmpty ? [.fallbackZhiyou] : store.roleCatalog
    }

    private var selectedPersona: AgentRoleSummary {
        personas.first(where: { $0.id == selectedPersonaId }) ?? personas[0]
    }

    private func detailSection<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 11) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            Text(label)
                .foregroundStyle(.secondary)
                .frame(width: 54, alignment: .leading)
            Text(value)
                .textSelection(.enabled)
        }
        .font(.callout)
    }
}
