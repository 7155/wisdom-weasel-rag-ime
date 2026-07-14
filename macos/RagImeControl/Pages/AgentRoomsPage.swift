import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct AgentRoomsPage: View {
    @EnvironmentObject private var store: AgentRoomWorkspaceStore
    @EnvironmentObject private var conversationStore: AgentWorkspaceStore
    @EnvironmentObject private var centerNavigation: AgentCenterNavigationModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var searchText = ""
    @State private var showsRoomRail = true
    @State private var showsNewRoom = false
    @FocusState private var composerFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            HStack(spacing: 0) {
                if showsRoomRail {
                    roomRail
                        .frame(width: 224)
                    Divider()
                }
                roomPane
                    .frame(minWidth: 540, maxWidth: .infinity)
            }
        }
        .task { await store.activate() }
        .onDisappear { store.suspendStream() }
        .onChange(of: store.showArchived) { _ in
            Task { await store.reloadRooms() }
        }
        .sheet(isPresented: $showsNewRoom) {
            AgentNewRoomSheet(roles: store.roleCatalog) { title, roles, policy, moderatorRoleId in
                await store.createRoom(
                    title: title,
                    roles: roles,
                    routingPolicy: policy,
                    moderatorRoleId: moderatorRoleId
                )
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Button {
                showsRoomRail.toggle()
            } label: {
                Image(systemName: "sidebar.left")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(showsRoomRail ? ControlDesign.brand : Color.secondary)
            .help(showsRoomRail ? "收起群组" : "展开群组")

            AgentRoomAvatarStack(
                participants: store.selectedRoom?.participants ?? [],
                roleCatalog: store.roleCatalog,
                activeParticipantId: store.conversation.activeParticipantId,
                size: 30
            )

            VStack(alignment: .leading, spacing: 1) {
                Text(store.selectedRoom?.title ?? "Agent 群组")
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                HStack(spacing: 5) {
                    AgentStatusDot(color: presenceColor, animated: store.isRoomBusy)
                        .scaleEffect(0.72)
                        .frame(width: 9, height: 9)
                    Text(presenceHeadline)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .contentTransition(.opacity)
                }
            }

            Spacer()

            if let room = store.selectedRoom {
                Label(
                    room.routingPolicy == "moderator" ? "主持路由" : "手动点名",
                    systemImage: room.routingPolicy == "moderator" ? "person.wave.2" : "at"
                )
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
            }

            Button {
                showsNewRoom = true
            } label: {
                Image(systemName: "plus.bubble")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .help("新建群组")

            if store.conversation.status == "waiting", let activeParticipant {
                Button {
                    openIndependentSession(activeParticipant)
                } label: {
                    Image(systemName: "checkmark.shield")
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.orange)
                .help("打开\(activeParticipant.displayName)的独立会话并确认操作")
            }

            if let room = store.selectedRoom {
                Button {
                    Task { await store.archiveSelected(room.status != "archived") }
                } label: {
                    Image(systemName: room.status == "archived" ? "tray.and.arrow.up" : "archivebox")
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .help(room.status == "archived" ? "恢复群组" : "归档群组")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(Color(nsColor: .windowBackgroundColor))
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: store.conversation.status)
    }

    private var roomRail: some View {
        VStack(spacing: 0) {
            HStack {
                Text("群组")
                    .font(.callout.weight(.semibold))
                Spacer()
                Button {
                    showsNewRoom = true
                } label: {
                    Image(systemName: "plus")
                        .frame(width: 24, height: 24)
                }
                .buttonStyle(.borderless)
                .help("新建群组")
            }
            .padding(.horizontal, 12)
            .frame(height: 46)

            HStack(spacing: 7) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.tertiary)
                TextField("搜索群组", text: $searchText)
                    .textFieldStyle(.plain)
            }
            .padding(.horizontal, 9)
            .frame(height: 32)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
            .padding(.horizontal, 9)
            .padding(.bottom, 8)

            if filteredRooms.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "person.3")
                        .font(.system(size: 27))
                        .foregroundStyle(.tertiary)
                    Text("还没有群组")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(filteredRooms) { room in
                            roomRow(room)
                        }
                    }
                    .padding(8)
                }
            }

            Divider()
            Toggle("显示已归档", isOn: $store.showArchived)
                .toggleStyle(.checkbox)
                .font(.caption)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
        }
        .background(Color(nsColor: .underPageBackgroundColor))
    }

    private func roomRow(_ room: AgentRoomSummary) -> some View {
        Button {
            store.selectRoomInteractively(room.id)
        } label: {
            HStack(alignment: .top, spacing: 9) {
                AgentRoomAvatarStack(
                    participants: room.participants,
                    roleCatalog: store.roleCatalog,
                    activeParticipantId: nil,
                    size: 26
                )
                .frame(width: 43, alignment: .leading)

                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(room.title)
                            .font(.callout.weight(.medium))
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(roomTimestamp(room.updatedAtMs))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    Text(room.participants.map(\.displayName).joined(separator: "、"))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 9)
            .padding(.vertical, 8)
            .background(
                room.id == store.selectedRoomId
                    ? ControlDesign.brand.opacity(0.095)
                    : Color.clear
            )
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(alignment: .leading) {
                if room.id == store.selectedRoomId {
                    Capsule()
                        .fill(ControlDesign.brand)
                        .frame(width: 3, height: 30)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var roomPane: some View {
        VStack(spacing: 0) {
            if !store.errorMessage.isEmpty {
                HStack(spacing: 9) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    Text(store.errorMessage)
                        .font(.caption)
                        .lineLimit(2)
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 9)
                .background(Color.orange.opacity(0.08))
            }

            if let room = store.selectedRoom {
                participantBar(room)
                Divider()
            }

            if store.selectedRoomId.isEmpty {
                emptyRoom
            } else if !store.canUseRuntime {
                unavailableRoom
            } else if transcriptRows.isEmpty {
                roomWelcome
            } else {
                AgentTranscriptSurface(
                    sessionId: store.selectedRoomId,
                    persona: .fallbackZhiyou,
                    rows: transcriptRows,
                    autoScrollRevision: timelineRevision,
                    isStreaming: isStreaming,
                    reduceMotion: reduceMotion,
                    onApprovalDecision: { _, _ in },
                    onPrepareUndo: { _ in },
                    onContinueExternal: { _ in }
                )
            }
            composer
        }
        .background(Color(nsColor: .textBackgroundColor))
    }

    private func participantBar(_ room: AgentRoomSummary) -> some View {
        HStack(spacing: 8) {
            ForEach(room.participants) { participant in
                Button {
                    store.insertMention(participant)
                    composerFocused = true
                } label: {
                    HStack(spacing: 6) {
                        AgentPersonaMark(
                            persona: store.persona(for: participant),
                            state: participant.id == store.conversation.activeParticipantId ? .thinking : .idle,
                            size: 24,
                            animates: false
                        )
                        VStack(alignment: .leading, spacing: 1) {
                            Text(participant.displayName)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.primary)
                            Text(participant.id == room.moderatorParticipantId ? "主持" : "待命")
                                .font(.system(size: 9, weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.horizontal, 7)
                    .frame(height: 36)
                    .background(
                        participant.id == store.conversation.activeParticipantId
                            ? agentRoomAccent(store.persona(for: participant)).opacity(0.09)
                            : Color.clear
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("点名 @\(participant.displayName)")
                .contextMenu {
                    Button("打开独立对话", systemImage: "arrow.up.right.square") {
                        openIndependentSession(participant)
                    }
                }
            }
            Spacer()
            Text(room.routingPolicy == "moderator" ? "可直接发给主持人" : "每轮点名一位角色")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 14)
        .frame(height: 48)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var composer: some View {
        AgentComposerStateHost(state: store.composerState) { composerState in
            VStack(spacing: 7) {
                VStack(spacing: 0) {
                    ZStack(alignment: .topLeading) {
                        if composerState.draft.isEmpty {
                            Text(composerPlaceholder)
                                .foregroundStyle(.tertiary)
                                .padding(.horizontal, 13)
                                .padding(.vertical, 11)
                        }
                        TextEditor(text: Binding(
                            get: { composerState.draft },
                            set: { composerState.draft = $0 }
                        ))
                        .font(.body)
                        .scrollContentBackground(.hidden)
                        .scrollIndicators(.hidden)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 5)
                        .focused($composerFocused)
                    }
                    .frame(height: 54)

                    HStack(alignment: .center, spacing: 7) {
                        Button(action: choosePaths) {
                            Image(systemName: "plus")
                                .font(.system(size: 17, weight: .regular))
                                .frame(width: 24, height: 24)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                        .frame(width: 30, height: 30)
                        .contentShape(Rectangle())
                        .disabled(store.selectedRoomId.isEmpty || store.sending)
                        .help("添加文件或文件夹路径")

                        Menu {
                            ForEach(store.selectedRoom?.participants ?? []) { participant in
                                Button("@\(participant.displayName)") {
                                    store.insertMention(participant)
                                    composerFocused = true
                                }
                            }
                        } label: {
                            Image(systemName: "at")
                                .font(.system(size: 14, weight: .semibold))
                                .frame(width: 24, height: 24)
                        }
                        .menuStyle(.borderlessButton)
                        .fixedSize()
                        .help("点名发言者")

                        if !store.canRouteDraft,
                           !composerState.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                           store.selectedRoom?.routingPolicy == "manual_mentions" {
                            Label("请点名一位角色", systemImage: "at")
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.orange)
                        } else {
                            Text(activeRoutingLabel)
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }

                        Spacer(minLength: 8)

                        Button {
                            Task { await store.send() }
                        } label: {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(nsColor: .windowBackgroundColor))
                                .frame(width: 32, height: 32)
                                .background(Color.primary)
                                .clipShape(Circle())
                        }
                        .buttonStyle(.plain)
                        .disabled(!store.canSend)
                        .help("发送")
                    }
                    .padding(.horizontal, 9)
                    .padding(.bottom, 8)
                }
                .background(Color(nsColor: .windowBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(
                            composerFocused ? ControlDesign.brand.opacity(0.48) : ControlDesign.hairline,
                            lineWidth: composerFocused ? 1 : 0.7
                        )
                )
                .shadow(color: Color.black.opacity(0.09), radius: 14, y: 4)
                .onDrop(
                    of: [UTType.fileURL.identifier, UTType.utf8PlainText.identifier],
                    isTargeted: nil,
                    perform: acceptComposerDrop
                )
            }
            .frame(maxWidth: 820)
            .padding(.horizontal, 20)
            .padding(.top, 7)
            .padding(.bottom, 14)
            .frame(maxWidth: .infinity)
        }
    }

    private var roomWelcome: some View {
        VStack(spacing: 18) {
            AgentRoomAvatarStack(
                participants: store.selectedRoom?.participants ?? [],
                roleCatalog: store.roleCatalog,
                activeParticipantId: nil,
                size: 58
            )
            .frame(height: 64)

            VStack(spacing: 6) {
                Text("让不同角色各自保留上下文")
                    .font(.system(size: 21, weight: .semibold))
                Text(store.selectedRoom?.routingPolicy == "moderator"
                    ? "直接发送会交给主持人，也可以 @ 指定其他角色。"
                    : "点击上方角色，或在消息里 @ 一位成员开始。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            HStack(spacing: 8) {
                ForEach(store.selectedRoom?.participants ?? []) { participant in
                    Button {
                        store.insertMention(participant)
                        composerFocused = true
                    } label: {
                        Label("问\(participant.displayName)", systemImage: "at")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var emptyRoom: some View {
        VStack(spacing: 17) {
            Image(systemName: "person.3.sequence")
                .font(.system(size: 48, weight: .light))
                .foregroundStyle(ControlDesign.brand)
            Text("建立一个 Agent 群组")
                .font(.title3.weight(.semibold))
            Button {
                showsNewRoom = true
            } label: {
                Label("新建群组", systemImage: "plus")
            }
            .buttonStyle(.borderedProminent)
            .tint(ControlDesign.brand)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var unavailableRoom: some View {
        VStack(spacing: 15) {
            Image(systemName: "bolt.slash")
                .font(.system(size: 42, weight: .light))
                .foregroundStyle(.orange)
            Text("Pi 群聊运行时尚未就绪")
                .font(.title3.weight(.semibold))
            Text("群组和成员 Session 会保留；Pi 恢复后可以从原事件序列继续。")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var transcriptRows: [AgentTranscriptRow] {
        var rows: [AgentTranscriptRow] = []
        let activityStart = store.conversation.activity.first?.createdAtMs
        var insertedActivity = false
        for entry in store.conversation.messages {
            if !insertedActivity,
               let activityStart,
               entry.message.role == "assistant",
               entry.message.createdAtMs >= activityStart {
                rows.append(.activity(items: store.conversation.activity, status: store.conversation.status))
                insertedActivity = true
            }
            if let participantId = entry.participantId,
               let participant = store.selectedRoom?.participants.first(where: { $0.id == participantId }) {
                rows.append(.participantMessage(entry.message, store.persona(for: participant)))
            } else {
                rows.append(.message(entry.message))
            }
        }
        if !insertedActivity, !store.conversation.activity.isEmpty {
            rows.append(.activity(items: store.conversation.activity, status: store.conversation.status))
        }
        return rows
    }

    private var timelineRevision: String {
        let last = store.conversation.messages.last?.message
        let textLength = last?.blocks.reduce(0) { total, block in
            total + (block.data.objectValue["text"]?.stringValue.count ?? 0)
        } ?? 0
        let bucket = last?.status == "streaming" ? textLength / 72 : textLength
        return "\(store.conversation.messages.count):\(store.conversation.activity.count):\(bucket):\(store.conversation.status)"
    }

    private var isStreaming: Bool {
        store.conversation.messages.contains(where: { $0.message.status == "streaming" })
    }

    private var filteredRooms: [AgentRoomSummary] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return store.rooms }
        return store.rooms.filter { room in
            room.title.localizedCaseInsensitiveContains(query)
                || room.participants.contains(where: { $0.displayName.localizedCaseInsensitiveContains(query) })
        }
    }

    private var presenceHeadline: String {
        if let participant = activeParticipant {
            switch store.conversation.status {
            case "routing": return "正在把问题交给\(participant.displayName)"
            case "responding": return "\(participant.displayName)正在回答"
            case "working", "analyzing", "busy": return "\(participant.displayName)正在查找和核对"
            case "waiting": return "\(participant.displayName)在等待确认"
            default: break
            }
        }
        if store.conversation.status == "failed" { return "这轮没有完成" }
        return store.selectedRoom == nil ? "建立可恢复的多角色对话" : "成员上下文彼此独立"
    }

    private var presenceColor: Color {
        if store.conversation.status == "failed" { return .orange }
        if store.isRoomBusy { return ControlDesign.brand }
        return store.selectedRoom == nil ? .gray : .green
    }

    private var activeParticipant: AgentRoomParticipant? {
        guard let id = store.conversation.activeParticipantId else { return nil }
        return store.selectedRoom?.participants.first(where: { $0.id == id })
    }

    private var composerPlaceholder: String {
        store.selectedRoom?.routingPolicy == "moderator"
            ? "输入消息，或 @ 指定其他角色…"
            : "@一位角色，然后输入消息或粘贴路径…"
    }

    private var activeRoutingLabel: String {
        if let activeParticipant { return "\(activeParticipant.displayName)正在发言" }
        return store.selectedRoom?.routingPolicy == "moderator" ? "发送给主持人" : "一次一位角色"
    }

    private func roomTimestamp(_ timestampMs: Int) -> String {
        let date = Date(timeIntervalSince1970: Double(timestampMs) / 1_000)
        if Calendar.current.isDateInToday(date) {
            return date.formatted(date: .omitted, time: .shortened)
        }
        return date.formatted(date: .numeric, time: .omitted)
    }

    private func choosePaths() {
        let panel = NSOpenPanel()
        panel.title = "把路径加入群聊"
        panel.prompt = "加入"
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.begin { response in
            guard response == .OK else { return }
            store.appendPaths(panel.urls.map(\.path))
            composerFocused = true
        }
    }

    private func acceptComposerDrop(_ providers: [NSItemProvider]) -> Bool {
        var accepted = false
        for provider in providers {
            if provider.canLoadObject(ofClass: URL.self) {
                accepted = true
                _ = provider.loadObject(ofClass: URL.self) { object, _ in
                    guard let url = object else { return }
                    DispatchQueue.main.async {
                        store.appendPaths([url.path])
                        composerFocused = true
                    }
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.utf8PlainText.identifier) {
                accepted = true
                provider.loadItem(forTypeIdentifier: UTType.utf8PlainText.identifier) { item, _ in
                    let text = (item as? Data).flatMap { String(data: $0, encoding: .utf8) } ?? item as? String
                    guard let text else { return }
                    DispatchQueue.main.async {
                        store.appendPaths([text])
                        composerFocused = true
                    }
                }
            }
        }
        return accepted
    }

    private func openIndependentSession(_ participant: AgentRoomParticipant) {
        centerNavigation.section = .conversations
        Task { await conversationStore.focusExternalSession(participant.sessionId) }
    }
}

private struct AgentRoomAvatarStack: View {
    let participants: [AgentRoomParticipant]
    let roleCatalog: [AgentRoleSummary]
    let activeParticipantId: String?
    let size: CGFloat

    var body: some View {
        HStack(spacing: -size * 0.28) {
            ForEach(participants.prefix(4)) { participant in
                AgentPersonaMark(
                    persona: persona(participant),
                    state: participant.id == activeParticipantId ? .thinking : .idle,
                    size: size,
                    animates: false
                )
                .overlay(
                    RoundedRectangle(cornerRadius: min(8, size * 0.24))
                        .stroke(Color(nsColor: .windowBackgroundColor), lineWidth: 1.5)
                )
                .zIndex(participant.id == activeParticipantId ? 4 : Double(3 - participant.ordinal))
            }
        }
        .fixedSize()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(participants.map(\.displayName).joined(separator: "、"))
    }

    private func persona(_ participant: AgentRoomParticipant) -> AgentRoleSummary {
        roleCatalog.first(where: {
            $0.roleId == participant.roleId && $0.version == participant.roleVersion
        }) ?? AgentRoleSummary(
            schemaVersion: nil,
            roleId: participant.roleId,
            version: participant.roleVersion,
            displayName: participant.displayName,
            tagline: "群聊成员",
            summary: nil,
            traits: nil,
            visualProfile: nil,
            defaults: nil,
            safetyPolicyVersion: nil,
            selectableModes: ["assistant"]
        )
    }
}

struct AgentNewRoomSheet: View {
    let roles: [AgentRoleSummary]
    let onCreate: (String, [AgentRoleSummary], String, String) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var title = "新群聊"
    @State private var selectedIds: Set<String>
    @State private var routingPolicy = "manual_mentions"
    @State private var moderatorRoleId = ""
    @State private var creating = false

    init(
        roles: [AgentRoleSummary],
        onCreate: @escaping (String, [AgentRoleSummary], String, String) async -> Bool
    ) {
        self.roles = roles
        self.onCreate = onCreate
        let available = roles.filter { $0.supports(mode: "assistant") }
        _selectedIds = State(initialValue: Set(available.prefix(3).map(\.id)))
        _moderatorRoleId = State(initialValue: available.first?.roleId ?? "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                Image(systemName: "person.3.sequence")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(ControlDesign.brand)
                    .frame(width: 46, height: 46)
                    .background(ControlDesign.brand.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 3) {
                    Text("新建 Agent 群组")
                        .font(.title3.weight(.semibold))
                    Text("每位成员使用独立、可恢复的 Pi Session")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            VStack(alignment: .leading, spacing: 7) {
                Text("名称")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                TextField("群组名称", text: $title)
                    .textFieldStyle(.roundedBorder)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("成员")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("\(selectedRoles.count)/4")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                VStack(spacing: 0) {
                    ForEach(Array(availableRoles.enumerated()), id: \.element.id) { index, role in
                        roleRow(role)
                        if index < availableRoles.count - 1 {
                            Divider().padding(.leading, 50)
                        }
                    }
                }
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("发言路由")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Picker("发言路由", selection: $routingPolicy) {
                    Label("手动 @", systemImage: "at").tag("manual_mentions")
                    Label("主持人", systemImage: "person.wave.2").tag("moderator")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }

            if routingPolicy == "moderator" {
                HStack {
                    Text("主持人")
                        .font(.callout.weight(.medium))
                    Spacer()
                    Picker("主持人", selection: $moderatorRoleId) {
                        ForEach(selectedRoles) { role in
                            Text(role.displayName).tag(role.roleId)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 180)
                }
            }

            Label("角色不会扩大工具、Shell、文件或审批权限", systemImage: "lock.shield")
                .font(.caption2)
                .foregroundStyle(.secondary)

            Divider()

            HStack {
                Button("取消", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button {
                    Task {
                        creating = true
                        let created = await onCreate(
                            normalizedTitle,
                            selectedRoles,
                            routingPolicy,
                            routingPolicy == "moderator" ? moderatorRoleId : ""
                        )
                        creating = false
                        if created { dismiss() }
                    }
                } label: {
                    if creating {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("创建群组")
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(ControlDesign.brand)
                .keyboardShortcut(.defaultAction)
                .disabled(creating || normalizedTitle.isEmpty || selectedRoles.count < 2)
            }
        }
        .padding(24)
        .frame(width: 520)
        .onChange(of: selectedIds) { _ in
            if !selectedRoles.contains(where: { $0.roleId == moderatorRoleId }) {
                moderatorRoleId = selectedRoles.first?.roleId ?? ""
            }
        }
    }

    private func roleRow(_ role: AgentRoleSummary) -> some View {
        let selected = selectedIds.contains(role.id)
        return Button {
            if selected {
                guard selectedIds.count > 2 else { return }
                selectedIds.remove(role.id)
            } else {
                guard selectedIds.count < 4 else { return }
                selectedIds.insert(role.id)
            }
        } label: {
            HStack(spacing: 10) {
                AgentPersonaMark(persona: role, state: .idle, size: 34, animates: false)
                VStack(alignment: .leading, spacing: 3) {
                    Text(role.displayName)
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.primary)
                    Text(role.tagline)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(selected ? ControlDesign.brand : Color.gray.opacity(0.52))
            }
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var availableRoles: [AgentRoleSummary] {
        let values = roles.filter { $0.supports(mode: "assistant") }
        return values.isEmpty ? [.fallbackZhiyou] : values
    }

    private var selectedRoles: [AgentRoleSummary] {
        availableRoles.filter { selectedIds.contains($0.id) }
    }

    private var normalizedTitle: String {
        String(title.split(whereSeparator: \Character.isWhitespace).joined(separator: " ").prefix(120))
    }
}

private func agentRoomAccent(_ persona: AgentRoleSummary) -> Color {
    switch persona.visualProfile?.accentToken {
    case "blue": .blue
    case "rose": Color(red: 0.84, green: 0.28, blue: 0.46)
    case "neutral": .secondary
    default: ControlDesign.brand
    }
}
