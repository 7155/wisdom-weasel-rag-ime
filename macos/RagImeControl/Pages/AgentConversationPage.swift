import AppKit
import AVFoundation
import Combine
import QuickLookUI
import SwiftUI
import UniformTypeIdentifiers

private enum AgentInspectorSection: String, CaseIterable, Identifiable {
    case activity = "轨迹"
    case sources = "来源"
    case tools = "工具"
    case session = "会话"

    var id: String { rawValue }
}

private struct AgentComposerCommand: Identifiable {
    let command: String
    let title: String
    let detail: String
    let symbol: String

    var id: String { command }
}

struct AgentConversationPage: View {
    @EnvironmentObject private var store: AgentWorkspaceStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var renameTitle = ""
    @State private var confirmingDelete = false
    @State private var searchText = ""
    @State private var showsSessionRail = false
    @State private var showsInspector = false
    @State private var inspectorSection: AgentInspectorSection = .activity
    @State private var showsNewSession = false
    @FocusState private var composerFocused: Bool

    var body: some View {
        ZStack(alignment: .trailing) {
            VStack(spacing: 0) {
                header
                Divider()
                HStack(spacing: 0) {
                    if showsSessionRail {
                        sessionRail
                            .frame(width: 224)
                            .transition(.move(edge: .leading).combined(with: .opacity))
                        Divider()
                    }
                    conversationPane
                        .frame(minWidth: 520, maxWidth: .infinity)
                }
            }

            if showsInspector {
                inspector
                    .frame(width: 286)
                    .frame(maxHeight: .infinity)
                    .background(.regularMaterial)
                    .overlay(Rectangle().fill(ControlDesign.hairline).frame(width: 1), alignment: .leading)
                    .shadow(color: Color.black.opacity(0.12), radius: 16, x: -4)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
                    .zIndex(2)
            }
        }
        .animation(RagImeMotion.spring(reduceMotion: reduceMotion), value: showsSessionRail)
        .animation(RagImeMotion.spring(reduceMotion: reduceMotion), value: showsInspector)
        .task {
            // The page is already visible; Pi startup and transcript recovery
            // continue without holding the navigation transition.
            await store.activate()
            renameTitle = store.selectedSession?.title ?? ""
        }
        .onDisappear {
            store.suspendStream()
        }
        .onChange(of: store.selectedSessionId) { _ in
            renameTitle = store.selectedSession?.title ?? ""
        }
        .onChange(of: store.showArchived) { _ in
            Task { await store.reloadSessions() }
        }
        .confirmationDialog(
            "删除这个对话？",
            isPresented: $confirmingDelete,
            titleVisibility: .visible
        ) {
            Button("删除", role: .destructive) {
                Task { await store.deleteSelected() }
            }
            Button("取消", role: .cancel) { }
        } message: {
            Text("对话索引和受管理的 Pi Session 文件会一起删除。")
        }
        .sheet(isPresented: $showsNewSession) {
            AgentNewSessionSheet(roles: store.roleCatalog) { title, mode, roleId, roleVersion, workspaceRoots in
                await store.createSession(
                    title: title,
                    mode: mode,
                    roleId: roleId,
                    roleVersion: roleVersion,
                    workspaceRoots: workspaceRoots
                )
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Button {
                showsSessionRail.toggle()
            } label: {
                Image(systemName: "sidebar.left")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(showsSessionRail ? ControlDesign.brand : Color.secondary)
            .help(showsSessionRail ? "收起会话" : "展开会话")

            AgentPersonaMark(persona: selectedPersona, state: companionState, size: 31)

            VStack(alignment: .leading, spacing: 1) {
                Text(store.selectedSession?.title ?? "智鼬")
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                HStack(spacing: 5) {
                    AgentStatusDot(color: companionState.accent, animated: isConversationRunning)
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
            runtimeBadge
            if store.selectedSession?.mode == "coordinator" {
                Image(systemName: "terminal")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.orange)
                    .frame(width: 28, height: 28)
                    .help("此 Session 可提出工作区命令；每条命令仍需原生批准并经过 Harness")
            }
            Button {
                showsNewSession = true
            } label: {
                Image(systemName: "square.and.pencil")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .help("新建对话")
            Button {
                showsInspector.toggle()
            } label: {
                Image(systemName: "info.circle")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(showsInspector ? ControlDesign.brand : Color.secondary)
            .help(showsInspector ? "收起会话详情" : "展开会话详情")
            if store.conversation.status != "idle", store.conversation.status != "ready" {
                Button {
                    Task { await store.abort() }
                } label: {
                    Image(systemName: "stop.fill")
                        .frame(width: 24, height: 24)
                }
                .buttonStyle(.borderless)
                .help("停止本轮")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(Color(nsColor: .windowBackgroundColor))
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: store.conversation.status)
    }

    private var runtimeBadge: some View {
        HStack(spacing: 7) {
            AgentStatusDot(color: runtimeColor, animated: store.runtime?.status == "starting")
            Text(runtimeLabel)
                .font(.caption2.weight(.medium))
        }
        .foregroundStyle(runtimeColor)
        .accessibilityElement(children: .combine)
    }

    private var sessionRail: some View {
        VStack(spacing: 0) {
            HStack {
                Text("会话")
                    .font(.callout.weight(.semibold))
                Spacer()
                Button {
                    showsNewSession = true
                } label: {
                    Image(systemName: "plus")
                        .frame(width: 24, height: 24)
                }
                .buttonStyle(.borderless)
                .help("新建对话")
            }
            .padding(.horizontal, 12)
            .frame(height: 46)

            HStack(spacing: 7) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.tertiary)
                TextField("搜索对话", text: $searchText)
                    .textFieldStyle(.plain)
            }
            .padding(.horizontal, 9)
            .frame(height: 32)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
            .padding(.horizontal, 9)
            .padding(.bottom, 8)

            if filteredSessions.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.system(size: 27))
                        .foregroundStyle(.tertiary)
                    Text("还没有对话")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(filteredSessions) { session in
                            sessionRow(session)
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

    private func sessionRow(_ session: AgentSessionSummary) -> some View {
        Button {
            store.selectSessionInteractively(session.id)
        } label: {
            HStack(alignment: .top, spacing: 9) {
                ZStack(alignment: .bottomTrailing) {
                    AgentPersonaMark(
                        persona: persona(for: session),
                        state: session.status == "faulted" ? .warning : .idle,
                        size: 31,
                        animates: false
                    )
                    Circle()
                        .fill(sessionStatusColor(session.status))
                        .frame(width: 7, height: 7)
                        .overlay(Circle().stroke(Color(nsColor: .underPageBackgroundColor), lineWidth: 1.5))
                }
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(session.title)
                            .font(.callout.weight(.medium))
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(sessionTimestamp(session.updatedAtMs))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    if !session.lastMessagePreview.isEmpty {
                        Text(session.lastMessagePreview)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    } else {
                        Text(session.mode == "coordinator" ? "运行协调" : "新对话")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 9)
            .padding(.vertical, 8)
            .background(
                session.id == store.selectedSessionId
                    ? ControlDesign.brand.opacity(0.095)
                    : Color.clear
            )
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(alignment: .leading) {
                if session.id == store.selectedSessionId {
                    Capsule()
                        .fill(ControlDesign.brand)
                        .frame(width: 3, height: 30)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            // A plain macOS button otherwise hit-tests only its painted
            // children. The complete visible session row must be clickable.
            .contentShape(Rectangle())
        }
        .buttonStyle(RagImePressButtonStyle())
        .frame(maxWidth: .infinity, alignment: .leading)
        .contextMenu {
            Button(session.status == "archived" ? "恢复" : "归档") {
                Task {
                    if session.id != store.selectedSessionId { await store.selectSession(session.id) }
                    await store.archiveSelected(session.status != "archived")
                }
            }
        }
    }

    private var conversationPane: some View {
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

            if store.selectedSessionId.isEmpty {
                emptyConversation
            } else if !store.canUseRuntime {
                unavailableConversation
            } else {
                timeline
            }
            composer
        }
        .background(Color(nsColor: .textBackgroundColor))
    }

    private var timeline: some View {
        Group {
            if transcriptRows.isEmpty {
                ScrollView {
                    conversationWelcome
                        .padding(.horizontal, 22)
                        .padding(.vertical, 22)
                }
            } else {
                AgentTranscriptSurface(
                    sessionId: store.selectedSessionId,
                    persona: selectedPersona,
                    rows: transcriptRows,
                    autoScrollRevision: timelineRevision,
                    isStreaming: store.conversation.messages.last?.status == "streaming",
                    reduceMotion: reduceMotion,
                    onApprovalDecision: { approval, approved in
                        Task { await store.decideApproval(approval, approved: approved) }
                    },
                    onPrepareUndo: { approval in
                        store.prepareUndo(for: approval)
                    },
                    onContinueExternal: { approval in
                        Task { await store.continueExternalApproval(approval) }
                    }
                )
            }
        }
    }

    private var conversationWelcome: some View {
        VStack(spacing: 20) {
            AgentPersonaWelcomeMark(persona: selectedPersona, state: .idle, size: 124)

            VStack(spacing: 6) {
                Text("今天想先从哪里开始？")
                    .font(.system(size: 22, weight: .semibold))
                Text("\(selectedPersona.displayName)会保留这段对话，需要时再查工具书、近期对话和控制中心。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: 168, maximum: 248), spacing: 9)],
                alignment: .leading,
                spacing: 9
            ) {
                ForEach(promptSuggestions, id: \.prompt) { suggestion in
                    Button {
                        Task { await store.sendSuggestion(suggestion.prompt) }
                    } label: {
                        HStack(spacing: 9) {
                            Image(systemName: suggestion.symbol)
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(ControlDesign.brand)
                                .frame(width: 20)
                            Text(suggestion.title)
                                .font(.callout.weight(.medium))
                                .foregroundStyle(.primary)
                                .lineLimit(2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Image(systemName: "arrow.up.right")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.horizontal, 11)
                        .frame(minHeight: 43)
                        .background(Color(nsColor: .controlBackgroundColor).opacity(0.82))
                        .clipShape(RoundedRectangle(cornerRadius: 7))
                        .overlay(
                            RoundedRectangle(cornerRadius: 7)
                                .stroke(ControlDesign.hairline, lineWidth: 0.7)
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!store.canUseRuntime || store.sending)
                }
            }
        }
        .padding(.vertical, 24)
        .frame(maxWidth: 620, alignment: .center)
        .frame(maxWidth: .infinity, alignment: .center)
    }

    private var composer: some View {
        AgentComposerStateHost(state: store.composerState) { composerState in
            VStack(spacing: 7) {
                if !matchingSlashCommands(for: composerState.draft).isEmpty {
                    AgentSlashCommandPalette(commands: matchingSlashCommands(for: composerState.draft)) { command in
                        composerState.draft = command.command + (command.command == "/read" || command.command == "/memory" || command.command == "/new" ? " " : "")
                        composerFocused = true
                    }
                    .transition(.opacity)
                }
                VStack(spacing: 0) {
                    if !store.pendingAttachments.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(store.pendingAttachments) { media in
                                    AgentPendingAttachmentChip(media: media) {
                                        store.removePendingAttachment(media.mediaId)
                                    }
                                }
                                .padding(.horizontal, 1)
                            }
                        }
                        .frame(height: 39)
                        .padding(.horizontal, 10)
                        .padding(.top, 7)
                        .transition(.opacity)
                    }

                    ZStack(alignment: .topLeading) {
                        if composerState.draft.isEmpty {
                            Text("输入消息、/ 命令，或直接粘贴路径…")
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
                        Button(action: chooseImages) {
                            if store.importingAttachments {
                                ProgressView()
                                    .controlSize(.small)
                                    .frame(width: 18, height: 18)
                            } else {
                                Image(systemName: "plus")
                                    .font(.system(size: 17, weight: .regular))
                                    .frame(width: 24, height: 24)
                            }
                        }
                        .buttonStyle(RagImePressButtonStyle())
                        .foregroundStyle(.secondary)
                        .frame(width: 30, height: 30)
                        .contentShape(Rectangle())
                        .disabled(!store.canUseRuntime || store.selectedSessionId.isEmpty || store.importingAttachments || store.sending)
                        .help("添加图片或文件路径")

                        sessionPermissionMenu

                        piModelMenu

                        Spacer(minLength: 8)

                        Button {
                            Task {
                                if isConversationRunning {
                                    await store.abort()
                                } else {
                                    await store.send()
                                }
                            }
                        } label: {
                            Image(systemName: isConversationRunning ? "stop.fill" : "arrow.up")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(nsColor: .windowBackgroundColor))
                                .frame(width: 32, height: 32)
                                .background(isConversationRunning ? Color.orange : Color.primary)
                                .clipShape(Circle())
                        }
                        .buttonStyle(RagImePressButtonStyle())
                        .disabled(!isConversationRunning && !store.canSend)
                        .help(isConversationRunning ? "停止本轮" : "发送")
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
                .onDrop(of: [UTType.fileURL.identifier, UTType.utf8PlainText.identifier], isTargeted: nil) { providers in
                    acceptComposerDrop(providers)
                }

                if !composerState.commandFeedback.isEmpty {
                    Text(composerState.commandFeedback)
                        .font(.caption2)
                        .lineLimit(1)
                        .foregroundStyle(ControlDesign.brand)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .frame(maxWidth: 820)
            .padding(.horizontal, 20)
            .padding(.top, 7)
            .padding(.bottom, 14)
            .frame(maxWidth: .infinity)
        }
    }

    private var piModelMenu: some View {
        Menu {
            if let catalog = store.modelCatalog, !catalog.providers.isEmpty {
                ForEach(catalog.providers) { provider in
                    Menu(provider.displayName) {
                        ForEach(provider.models) { model in
                            if model.thinkingLevels.count > 1 {
                                Menu(model.name) {
                                    ForEach(model.thinkingLevels, id: \.self) { level in
                                        Button {
                                            Task { await store.selectModel(model, thinkingLevel: level) }
                                        } label: {
                                            if model.selectionId == store.selectedModel?.selectionId,
                                               level == store.selectedThinkingLevel {
                                                Label(thinkingLevelLabel(level), systemImage: "checkmark")
                                            } else {
                                                Text(thinkingLevelLabel(level))
                                            }
                                        }
                                    }
                                }
                            } else {
                                Button {
                                    Task { await store.selectModel(model) }
                                } label: {
                                    if model.selectionId == store.selectedModel?.selectionId {
                                        Label(model.name, systemImage: "checkmark")
                                    } else {
                                        Text(model.name)
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                Text("Pi 暂无可选模型")
            }
        } label: {
            HStack(spacing: 5) {
                if store.switchingModel {
                    ProgressView().controlSize(.mini)
                }
                Text(currentPiModelLabel)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .frame(maxWidth: 154)
            .frame(height: 30)
            .contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton)
        .fixedSize(horizontal: true, vertical: false)
        .disabled(store.modelCatalog == nil || !store.canSwitchModel)
        .help("切换当前 Pi Session 的对话模型")
    }

    private var currentPiModelLabel: String {
        if let model = store.selectedModel {
            return model.reasoning
                ? "\(model.name) · \(thinkingLevelLabel(store.selectedThinkingLevel))"
                : model.name
        }
        let fallback = store.selectedSession?.modelProfile ?? ""
        if fallback == "pi/default" || fallback.isEmpty { return "Pi 模型" }
        return fallback.split(separator: "/").last.map(String.init) ?? fallback
    }

    private var sessionPermissionMenu: some View {
        Menu {
            Button {
                Task { await store.switchSessionMode("assistant") }
            } label: {
                if store.selectedSession?.mode == "assistant" {
                    Label("受控模式", systemImage: "checkmark")
                } else {
                    Label("受控模式", systemImage: "lock.shield")
                }
            }
            Button {
                Task { await store.switchSessionMode("coordinator") }
            } label: {
                if store.selectedSession?.mode == "coordinator" {
                    Label("运行协调", systemImage: "checkmark")
                } else {
                    Label("运行协调", systemImage: "terminal")
                }
            }
            .disabled(
                !selectedPersona.supports(mode: "coordinator")
                    || store.runtime?.capabilities.objectValue["coordinator"]?.boolValue != true
            )
            Divider()
            Text("写入与命令始终经过 Harness 和原生批准")
        } label: {
            Image(systemName: store.selectedSession?.mode == "coordinator" ? "terminal" : "lock.shield")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(store.selectedSession?.mode == "coordinator" ? Color.orange : Color.secondary)
                .frame(width: 24, height: 24)
        }
        .menuStyle(.borderlessButton)
        .frame(width: 30, height: 30)
        .disabled(!store.canSwitchSessionMode)
        .help(store.selectedSession?.mode == "coordinator" ? "运行协调：沙盒命令逐次批准" : "受控模式：不提供 Shell")
    }

    private func thinkingLevelLabel(_ level: String) -> String {
        switch level {
        case "minimal": return "最低"
        case "low": return "低"
        case "medium": return "中"
        case "high": return "高"
        case "xhigh": return "最高"
        default: return "关闭思考"
        }
    }

    private func matchingSlashCommands(for draft: String) -> [AgentComposerCommand] {
        let input = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard input.hasPrefix("/"), !input.contains(where: \Character.isWhitespace) else { return [] }
        let query = input.lowercased()
        return slashCommands.filter { query == "/" || $0.command.hasPrefix(query) }
    }

    private var slashCommands: [AgentComposerCommand] {
        [
            AgentComposerCommand(command: "/new", title: "新建对话", detail: "保留当前模式，创建独立 Session", symbol: "plus.bubble"),
            AgentComposerCommand(command: "/compact", title: "压缩上下文", detail: "缩短上下文但保留连续会话", symbol: "arrow.down.right.and.arrow.up.left"),
            AgentComposerCommand(command: "/memory", title: "查找记忆", detail: "检索工具书与近期对话", symbol: "books.vertical"),
            AgentComposerCommand(command: "/model", title: "切换模型", detail: "输入 provider/model 和可选思考强度", symbol: "cpu"),
            AgentComposerCommand(command: "/thinking", title: "思考强度", detail: "off、low、medium、high 或 xhigh", symbol: "brain"),
            AgentComposerCommand(command: "/permission", title: "运行权限", detail: "在受控模式与运行协调之间切换", symbol: "lock.shield"),
            AgentComposerCommand(command: "/read", title: "读取路径", detail: "后面直接粘贴文件或文件夹路径", symbol: "doc.text.magnifyingglass"),
            AgentComposerCommand(command: "/status", title: "运行状态", detail: "查看 Pi 与当前 Session 状态", symbol: "waveform.path.ecg"),
            AgentComposerCommand(command: "/stop", title: "停止本轮", detail: "中止正在运行的 Agent Loop", symbol: "stop.fill"),
            AgentComposerCommand(command: "/help", title: "命令帮助", detail: "显示当前可用的本地命令", symbol: "questionmark.circle"),
        ]
    }

    private func acceptComposerDrop(_ providers: [NSItemProvider]) -> Bool {
        var accepted = false
        for provider in providers {
            if provider.canLoadObject(ofClass: URL.self) {
                accepted = true
                _ = provider.loadObject(ofClass: URL.self) { object, _ in
                    guard let url = object else { return }
                    DispatchQueue.main.async { appendComposerPath(url.path) }
                }
                continue
            }
            if provider.hasItemConformingToTypeIdentifier(UTType.utf8PlainText.identifier) {
                accepted = true
                provider.loadItem(forTypeIdentifier: UTType.utf8PlainText.identifier) { item, _ in
                    let text: String?
                    if let data = item as? Data { text = String(data: data, encoding: .utf8) }
                    else { text = item as? String }
                    guard let text, !text.isEmpty else { return }
                    DispatchQueue.main.async { appendComposerPath(text) }
                }
            }
        }
        return accepted
    }

    private func appendComposerPath(_ value: String) {
        let path = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else { return }
        if store.draft.isEmpty {
            store.draft = path
        } else if store.draft.hasSuffix(" ") || store.draft.hasSuffix("\n") {
            store.draft += path
        } else {
            store.draft += " \(path)"
        }
        composerFocused = true
    }

    private func chooseImages() {
        let panel = NSOpenPanel()
        panel.title = "选择要交给\(selectedPersona.displayName)查看的图片"
        panel.prompt = "附加"
        panel.allowedContentTypes = [.png, .jpeg, .gif, .image]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.canCreateDirectories = false
        panel.begin { response in
            guard response == .OK else { return }
            let urls = panel.urls
            Task { await store.importImages(urls) }
        }
    }

    private var emptyConversation: some View {
        VStack(spacing: 18) {
            AgentPersonaWelcomeMark(persona: .fallbackZhiyou, state: .idle, size: 168)
            VStack(spacing: 6) {
                Text("开始一段连续对话")
                    .font(.title2.weight(.semibold))
                Text("选择一个角色开始连续对话、检索和整理")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            Button {
                showsNewSession = true
            } label: {
                Label("新建对话", systemImage: "plus")
            }
            .buttonStyle(.borderedProminent)
            .tint(ControlDesign.brand)
        }
        .padding(34)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var unavailableConversation: some View {
        VStack(spacing: 18) {
            RagImeFullBodyCompanion(state: .warning, size: 160)
            VStack(spacing: 6) {
                Text(runtimeLabel)
                    .font(.title3.weight(.semibold))
                Text(unavailableHint)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 410)
            }
            if let error = store.runtime?.lastError, !error.isEmpty {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 360)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var inspector: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("对话检查器")
                    .font(.headline)
                Spacer()
                Toggle(
                    "",
                    isOn: Binding(
                        get: { store.runtime?.enabled == true },
                        set: { enabled in Task { await store.setRuntimeEnabled(enabled) } }
                    )
                )
                .toggleStyle(.switch)
                .labelsHidden()
                .help("连接 Pi")
                Button {
                    showsInspector = false
                } label: {
                    Image(systemName: "xmark")
                        .frame(width: 22, height: 22)
                }
                .buttonStyle(.borderless)
                .help("收起检查器")
            }

            Picker("检查内容", selection: $inspectorSection) {
                ForEach(AgentInspectorSection.allCases) { section in
                    Text(section.rawValue).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            Divider()
            inspectorContent
        }
        .padding(18)
    }

    @ViewBuilder
    private var inspectorContent: some View {
        switch inspectorSection {
        case .activity:
            activityInspector
        case .sources:
            sourcesInspector
        case .tools:
            toolsInspector
        case .session:
            sessionInspector
        }
    }

    private var activityInspector: some View {
        Group {
            if store.conversation.activity.isEmpty {
                inspectorEmpty(symbol: "waveform.path.ecg", title: "本轮还没有工具活动")
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 13) {
                        ForEach(store.conversation.activity) { item in
                            HStack(alignment: .top, spacing: 9) {
                                AgentActivityGlyph(state: item.state, tint: ControlDesign.brand)
                                    .frame(width: 18, height: 18)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item.title).font(.caption.weight(.semibold))
                                    if !item.detail.isEmpty {
                                        Text(item.detail)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(4)
                                    }
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private var sourcesInspector: some View {
        Group {
            if inspectorReferences.isEmpty,
               store.memorySources.isEmpty,
               store.memoryMaintenance == nil {
                inspectorEmpty(symbol: "books.vertical", title: "本轮还没有召回来源")
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if let maintenance = store.memoryMaintenance {
                            memoryMaintenanceBand(maintenance)
                        }
                        if !inspectorReferences.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("本轮使用")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                ForEach(inspectorReferences) { reference in
                                    AgentReferenceChip(reference: reference)
                                }
                            }
                        }
                        if !store.memorySources.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("记忆来源检查点")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                ForEach(store.memorySources.prefix(8)) { source in
                                    HStack(alignment: .top, spacing: 9) {
                                        Image(
                                            systemName: source.sourceRole == "user"
                                                ? "person.text.rectangle"
                                                : "checkmark.seal"
                                        )
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(ControlDesign.brand)
                                        .frame(width: 19)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(
                                                source.sourceRole == "user"
                                                    ? "最终用户消息"
                                                    : "已应用工具回执"
                                            )
                                            .font(.caption.weight(.medium))
                                            Text("等待异步整理 · \(memorySourceDate(source.createdAtMs))")
                                                .font(.caption2)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    .padding(.vertical, 2)
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    private func memoryMaintenanceBand(_ status: AgentMemoryMaintenanceStatus) -> some View {
        let tint = memoryMaintenanceTint(status)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: status.pendingDraftCount > 0 ? "doc.badge.clock" : "books.vertical.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 30, height: 30)
                    .background(tint.opacity(0.1))
                    .clipShape(RoundedRectangle(cornerRadius: 7))

                VStack(alignment: .leading, spacing: 3) {
                    Text(memoryMaintenanceHeadline(status))
                        .font(.caption.weight(.semibold))
                    Text(memoryMaintenanceDetail(status))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Button {
                    Task { await store.reloadMemoryMaintenance() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .frame(width: 22, height: 22)
                }
                .buttonStyle(.borderless)
                .help("刷新记忆整理状态")
            }

            HStack(spacing: 12) {
                Label(
                    "\(status.compileState.pendingEventCount) 条新记录",
                    systemImage: "text.badge.plus"
                )
                Label(
                    "\(status.pendingDraftCount) 份待审草案",
                    systemImage: "doc.text.magnifyingglass"
                )
            }
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)

            Label(
                status.autoApply
                    ? "警告：定时任务允许自动应用变更"
                    : "定时任务只生成草案，不会自动应用",
                systemImage: status.autoApply ? "exclamationmark.triangle.fill" : "lock.shield"
            )
            .font(.caption2.weight(.medium))
            .foregroundStyle(status.autoApply ? Color.red : Color.secondary)

            if let draftRun = status.runs.first(where: { $0.status == "draft" }) {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text("最近草案")
                            .font(.caption2.weight(.semibold))
                        Spacer(minLength: 4)
                        Text("\(draftRun.diffCount) 项")
                            .font(.caption2.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    Text(draftRun.summary.isEmpty ? draftRun.runId : draftRun.summary)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                HStack(spacing: 8) {
                    Button("让\(selectedPersona.displayName)审阅", systemImage: "text.magnifyingglass") {
                        stageMemoryCommand(
                            "请调用 ime_memory.maintenance_review 审阅记忆草案 \(draftRun.runId)，逐项说明变更和证据范围，不要应用。"
                        )
                    }
                    .buttonStyle(.borderless)
                    Button("申请应用", systemImage: "checkmark.shield") {
                        stageMemoryCommand(
                            "请先审阅记忆草案 \(draftRun.runId)，然后请求应用；真正写入前必须让我在原生审批卡确认。"
                        )
                    }
                    .buttonStyle(.borderless)
                }
                .font(.caption2.weight(.semibold))
            } else if status.due {
                Button("生成审阅草案", systemImage: "wand.and.stars") {
                    stageMemoryCommand(
                        "请根据当前新增的最终内容生成一份记忆整理草案，只生成可审阅草案，不要应用。"
                    )
                }
                .buttonStyle(.borderless)
                .font(.caption2.weight(.semibold))
            }
        }
        .padding(11)
        .background(tint.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .overlay(RoundedRectangle(cornerRadius: 7).stroke(tint.opacity(0.16), lineWidth: 0.7))
    }

    private func stageMemoryCommand(_ command: String) {
        store.draft = command
        showsInspector = false
        composerFocused = true
    }

    private func memoryMaintenanceHeadline(_ status: AgentMemoryMaintenanceStatus) -> String {
        if status.pendingDraftCount > 0 { return "有记忆草案等待审阅" }
        if status.due { return "已达到异步整理条件" }
        if status.compileState.pendingEventCount > 0 { return "正在收集可整理的最终内容" }
        return "长期记忆已经同步"
    }

    private func memoryMaintenanceDetail(_ status: AgentMemoryMaintenanceStatus) -> String {
        if status.pendingDraftCount > 0 {
            let changes = status.runs.first(where: { $0.status == "draft" })?.diffCount ?? 0
            return changes > 0
                ? "最近草案包含 \(changes) 项建议，可在记忆工作台逐项确认。"
                : "草案已准备好，可在记忆工作台逐项确认。"
        }
        if status.due {
            switch status.dueReason {
            case "pending_events": return "新增记录已达到批量整理阈值。"
            case "idle": return "对话进入空闲窗口，可以开始后台整理。"
            case "daily": return "已经进入每日记忆整理窗口。"
            default: return "后台任务会在下一次调度时生成审阅草案。"
            }
        }
        if status.compileState.pendingEventCount > 0 {
            return "内容会继续累积，达到阈值或进入空闲窗口后再整理。"
        }
        return "当前没有等待整理的最终消息或工具回执。"
    }

    private func memoryMaintenanceTint(_ status: AgentMemoryMaintenanceStatus) -> Color {
        if status.autoApply { return .red }
        if status.pendingDraftCount > 0 || status.due { return .orange }
        if status.compileState.pendingEventCount == 0 { return .green }
        return ControlDesign.brand
    }

    private func memorySourceDate(_ timestampMs: Int) -> String {
        Date(timeIntervalSince1970: Double(timestampMs) / 1_000).formatted(
            date: .abbreviated,
            time: .shortened
        )
    }

    private var toolsInspector: some View {
        Group {
            if visibleToolCatalog.isEmpty {
                inspectorEmpty(symbol: "wrench.and.screwdriver", title: "没有可用的受控工具")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(visibleToolCatalog.enumerated()), id: \.element.id) { index, tool in
                            HStack(alignment: .top, spacing: 10) {
                                Image(systemName: toolSymbol(tool.domain))
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(ControlDesign.brand)
                                    .frame(width: 26, height: 26)
                                    .background(ControlDesign.brand.opacity(0.08))
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(spacing: 6) {
                                        Text(tool.displayName)
                                            .font(.caption.weight(.semibold))
                                        Spacer(minLength: 4)
                                        Text(
                                            tool.approvalOperationCount == 0
                                                ? "只读"
                                                : "\(tool.approvalOperationCount) 项需确认"
                                        )
                                            .font(.caption2.weight(.semibold))
                                            .foregroundStyle(tool.approvalOperationCount == 0 ? Color.green : Color.orange)
                                    }
                                    Text(tool.description)
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                    HStack(spacing: 5) {
                                        Circle()
                                            .fill(tool.availability == "online" ? Color.green : Color.gray)
                                            .frame(width: 6, height: 6)
                                        Text(tool.availability == "online" ? "在线" : "不可用")
                                        Text("·")
                                        Text("\(tool.operations.count) 个动作")
                                    }
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                                }
                            }
                            .padding(.vertical, 10)
                            if index < visibleToolCatalog.count - 1 {
                                Divider().padding(.leading, 36)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    @ViewBuilder
    private var sessionInspector: some View {
        if let session = store.selectedSession {
            VStack(alignment: .leading, spacing: 13) {
                VStack(alignment: .leading, spacing: 7) {
                    Text("名称").font(.caption).foregroundStyle(.secondary)
                    HStack(spacing: 6) {
                        TextField("对话名称", text: $renameTitle)
                        Button {
                            Task { await store.renameSelected(renameTitle) }
                        } label: {
                            Image(systemName: "checkmark").frame(width: 22, height: 22)
                        }
                        .buttonStyle(.borderless)
                        .disabled(renameTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || renameTitle == session.title)
                        .help("保存名称")
                    }
                }
                Divider()
                inspectorRow("模式", value: session.mode == "coordinator" ? "运行协调" : "助手")
                inspectorRow("角色", value: roleDescription(session))
                VStack(alignment: .leading, spacing: 6) {
                    Text("Pi 对话模型")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    piModelMenu
                }
                inspectorRow("工具", value: session.toolProfileVersion)
                inspectorRow("消息", value: "\(session.messageCount)")
                Spacer()
                HStack {
                    Button {
                        Task { await store.archiveSelected(session.status != "archived") }
                    } label: {
                        Image(systemName: session.status == "archived" ? "tray.and.arrow.up" : "archivebox")
                            .frame(width: 24, height: 24)
                    }
                    .buttonStyle(.borderless)
                    .help(session.status == "archived" ? "恢复" : "归档")
                    Spacer()
                    Button(role: .destructive) {
                        confirmingDelete = true
                    } label: {
                        Image(systemName: "trash").frame(width: 24, height: 24)
                    }
                    .buttonStyle(.borderless)
                    .help("删除")
                }
            }
        } else {
            inspectorEmpty(symbol: "bubble.left", title: "未选择会话")
        }
    }

    private func inspectorEmpty(symbol: String, title: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 24))
                .foregroundStyle(.tertiary)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func inspectorRow(_ label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.callout).lineLimit(2)
        }
    }

    private func toolSymbol(_ domain: String) -> String {
        switch domain {
        case "overview": return "gauge"
        case "input": return "keyboard"
        case "voice": return "waveform"
        case "planning": return "checklist"
        case "memory": return "books.vertical"
        case "knowledge": return "doc.text.magnifyingglass"
        case "models": return "cpu"
        case "runtime": return "stethoscope"
        case "configuration": return "clock.arrow.circlepath"
        case "workspace": return "folder.badge.gearshape"
        default: return "wrench.and.screwdriver"
        }
    }

    private var visibleToolCatalog: [AgentToolManifest] {
        let mode = store.selectedSession?.mode ?? "assistant"
        return store.toolCatalog.filter { $0.sessionModes.contains(mode) }
    }

    private var filteredSessions: [AgentSessionSummary] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return store.sessions }
        return store.sessions.filter {
            $0.title.localizedCaseInsensitiveContains(query)
                || $0.lastMessagePreview.localizedCaseInsensitiveContains(query)
        }
    }

    private var inspectorReferences: [AgentActivityReference] {
        var seen: Set<String> = []
        return store.conversation.activity
            .flatMap(\.references)
            .filter { seen.insert($0.id).inserted }
    }

    private var isConversationRunning: Bool {
        ["busy", "analyzing", "working", "responding", "finishing", "aborting"]
            .contains(store.conversation.status)
    }

    private var hasRunningActivity: Bool {
        store.conversation.activity.contains { $0.state == .running }
    }

    private var presenceHeadline: String {
        switch store.conversation.status {
        case "busy": return "正在理解你的问题"
        case "analyzing": return "正在想一想"
        case "working": return "正在翻阅相关资料"
        case "responding": return "正在组织回答"
        case "finishing": return "正在收尾"
        case "aborting": return "正在停止"
        case "failed": return "这次没有完成"
        default:
            return store.conversation.messages.last?.role == "assistant" ? "已经整理好了" : "随时可以开始"
        }
    }

    private var presenceDetail: String {
        if let running = store.conversation.activity.last(where: { $0.state == .running }) {
            return running.detail.isEmpty ? running.title : running.detail
        }
        if let latest = store.conversation.activity.last, !latest.detail.isEmpty {
            return latest.detail
        }
        if store.selectedSessionId.isEmpty {
            return "新建会话后，我会保留前后文并按需调用受控工具"
        }
        return isConversationRunning ? "只展示可核对的活动摘要，不展示模型内部思维" : "连续会话、记忆检索与受控工具"
    }

    private var unavailableHint: String {
        if store.selectedSession?.mode == "coordinator",
           store.runtime?.capabilities.objectValue["coordinator"]?.boolValue != true {
            return "当前受管理 Pi 组件还没有安装 Command Harness 工具。普通助手对话和输入法仍可继续使用。"
        }
        switch store.runtime?.status {
        case "disabled": return "打开右上角会话详情中的 Pi 开关后，才会按需启动连续对话。"
        case "not_installed": return "受管理的 Pi 运行组件尚未安装，普通输入法与快速生成不会受影响。"
        case "needs_configuration": return "先在“RAG 与模型”中配置知识生成模型；凭据只会短暂传给隔离的 Pi 进程。"
        case "faulted": return "Pi 运行组件需要检查；普通输入法仍可继续使用。"
        default: return "运行组件准备好后，这个会话会从原来的上下文继续。"
        }
    }

    private var activityInsertionMessageId: String? {
        guard let started = store.conversation.activity.first?.createdAtMs else { return nil }
        return store.conversation.messages.last(where: {
            $0.role == "assistant" && $0.createdAtMs >= started
        })?.id
    }

    private var transcriptRows: [AgentTranscriptRow] {
        var rows: [AgentTranscriptRow] = []
        rows.reserveCapacity(
            store.conversation.messages.count
                + store.pendingApprovals.count
                + store.recentApprovalReceipts.count
                + (store.conversation.activity.isEmpty ? 0 : 1)
        )
        let activityMessageId = activityInsertionMessageId
        for message in store.conversation.messages {
            if activityMessageId == message.id {
                rows.append(
                    .activity(
                        items: store.conversation.activity,
                        status: store.conversation.status
                    )
                )
            }
            rows.append(.message(message))
        }
        if activityMessageId == nil, !store.conversation.activity.isEmpty {
            rows.append(
                .activity(
                    items: store.conversation.activity,
                    status: store.conversation.status
                )
            )
        }
        for approval in store.pendingApprovals {
            rows.append(
                .approval(
                    approval,
                    working: store.approvalActionId == approval.approvalId
                )
            )
        }
        for approval in store.recentApprovalReceipts {
            rows.append(
                .receipt(
                    approval,
                    rollbackConsumed: store.rollbackConsumed(for: approval),
                    externalActionWorking: store.approvalActionId == approval.approvalId
                )
            )
        }
        return rows
    }

    private var timelineRevision: String {
        let last = store.conversation.messages.last
        let textLength = last?.blocks.reduce(0) { total, block in
            total + (block.data.objectValue["text"]?.stringValue.count ?? 0)
        } ?? 0
        // Do not animate-scroll on every token. A coarse bucket keeps the latest
        // answer visible without forcing layout work for every streamed fragment.
        let streamScrollBucket = last?.status == "streaming" ? textLength / 72 : textLength
        return "\(store.conversation.messages.count):\(store.conversation.activity.count):\(store.approvals.count):\(streamScrollBucket):\(store.conversation.status)"
    }

    private var companionState: RagImeCompanionState {
        if !store.errorMessage.isEmpty || store.conversation.status == "failed" { return .warning }
        if ["busy", "analyzing", "working", "responding", "finishing"].contains(store.conversation.status) {
            return .thinking
        }
        if store.conversation.messages.last?.role == "assistant" { return .done }
        return .idle
    }

    private var runtimeLabel: String {
        if store.selectedSession?.mode == "coordinator",
           store.runtime?.capabilities.objectValue["coordinator"]?.boolValue != true {
            return "协调组件待更新"
        }
        guard let runtime = store.runtime else { return "检查 Pi" }
        switch runtime.status {
        case "disabled": return "Pi 未启用"
        case "not_installed": return "Pi 未安装"
        case "needs_configuration": return "对话模型待配置"
        case "stopped": return "Pi 待启动"
        case "starting": return "Pi 启动中"
        case "ready": return "Pi 已就绪"
        case "busy": return "Pi 工作中"
        case "faulted": return "Pi 需要检查"
        default: return "Pi \(runtime.status)"
        }
    }

    private var runtimeColor: Color {
        switch store.runtime?.status {
        case "ready": return .green
        case "busy", "starting": return ControlDesign.brand
        case "faulted", "not_installed", "needs_configuration": return .orange
        default: return .gray
        }
    }

    private func sessionStatusColor(_ status: String) -> Color {
        switch status {
        case "busy": return ControlDesign.brand
        case "faulted": return .orange
        case "archived": return .gray
        default: return .green
        }
    }

    private func sessionTimestamp(_ timestampMs: Int) -> String {
        let date = Date(timeIntervalSince1970: Double(timestampMs) / 1_000)
        if Calendar.current.isDateInToday(date) {
            return date.formatted(date: .omitted, time: .shortened)
        }
        return date.formatted(date: .numeric, time: .omitted)
    }

    private var selectedPersona: AgentRoleSummary {
        guard let session = store.selectedSession else { return .fallbackZhiyou }
        return persona(for: session)
    }

    private func persona(for session: AgentSessionSummary) -> AgentRoleSummary {
        store.roleCatalog.first(where: {
            $0.roleId == session.roleId && $0.version == session.roleVersion
        }) ?? (session.roleId == "zhiyou-v1" ? .fallbackZhiyou : AgentRoleSummary(
            schemaVersion: nil,
            roleId: session.roleId,
            version: session.roleVersion,
            displayName: session.roleId,
            tagline: "已保存的角色版本",
            summary: nil,
            traits: nil,
            visualProfile: nil,
            defaults: nil,
            safetyPolicyVersion: nil,
            selectableModes: nil
        ))
    }

    private func roleDescription(_ session: AgentSessionSummary) -> String {
        let role = persona(for: session)
        return "\(role.displayName) · \(role.tagline)"
    }

    private var promptSuggestions: [(symbol: String, title: String, prompt: String)] {
        switch selectedPersona.roleId {
        case "hermes-v1":
            return [
                ("scope", "精确查证", "检索与当前问题最相关的证据，先给结论，再说明还缺什么。"),
                ("arrow.triangle.branch", "梳理下一步", "结合最近进展和未完成任务，给出最值得先做的三个动作。"),
                ("stethoscope", "诊断状态", "检查控制中心、模型和运行组件，只列异常、影响和下一步。"),
                ("doc.text.magnifyingglass", "形成执行摘要", "把最近输入和相关工具书整理成一份简洁的执行摘要。"),
            ]
        case "vcp-v1":
            return [
                ("point.3.connected.trianglepath.dotted", "串联资料", "查找相关 Book、Group、Tag 和近期对话，说明它们之间的关系。"),
                ("books.vertical", "展开多条线索", "围绕当前主题从不同工具书和近期对话展开检索，并标出证据来源。"),
                ("tag", "整理知识关系", "把最近讨论按主题、Group 和 Tag 整理，指出重复与缺口。"),
                ("clock.arrow.circlepath", "回顾最近变化", "比较最近几次相关记录，说明有哪些新增、修正或仍未解决的部分。"),
            ]
        default:
            return [
                ("calendar", "回顾今天", "根据今天的最终输入和计划，帮我回顾今天做了什么，并标出证据来源。"),
                ("clock.arrow.circlepath", "找最近进展", "查找最近与输入法项目有关的对话和工具书，告诉我最新进展。"),
                ("checklist", "看看未完成任务", "查看今天的计划、目标和未完成任务，帮我排一下接下来先做什么。"),
                ("stethoscope", "检查运行状态", "检查控制中心、模型和运行组件状态，只报告需要我注意的问题。"),
            ]
        }
    }
}

enum AgentTranscriptRow: Equatable, Identifiable {
    case message(AgentMessage)
    case participantMessage(AgentMessage, AgentRoleSummary)
    case activity(items: [AgentActivityItem], status: String)
    case approval(AgentApproval, working: Bool)
    case receipt(
        AgentApproval,
        rollbackConsumed: Bool,
        externalActionWorking: Bool
    )

    var id: String {
        switch self {
        case let .message(message):
            return "message:\(message.id)"
        case let .participantMessage(message, persona):
            return "participant-message:\(persona.id):\(message.id)"
        case .activity:
            return "activity"
        case let .approval(approval, _):
            return "approval:\(approval.approvalId)"
        case let .receipt(approval, _, _):
            return "receipt:\(approval.approvalId)"
        }
    }
}

struct AgentTranscriptActions {
    let onApprovalDecision: (AgentApproval, Bool) -> Void
    let onPrepareUndo: (AgentApproval) -> Void
    let onContinueExternal: (AgentApproval) -> Void
    let activityExpanded: Bool
    let onActivityExpansionChange: (Bool) -> Void

    static let noop = AgentTranscriptActions(
        onApprovalDecision: { _, _ in },
        onPrepareUndo: { _ in },
        onContinueExternal: { _ in },
        activityExpanded: false,
        onActivityExpansionChange: { _ in }
    )
}

/// AppKit owns transcript scrolling, row reuse and height estimation. SwiftUI is
/// hosted only for visible typed rows, so a streaming suffix cannot invalidate a
/// 500-message view tree.
struct AgentTranscriptSurface: NSViewRepresentable {
    let sessionId: String
    let persona: AgentRoleSummary
    let rows: [AgentTranscriptRow]
    let autoScrollRevision: String
    let isStreaming: Bool
    let reduceMotion: Bool
    let onApprovalDecision: (AgentApproval, Bool) -> Void
    let onPrepareUndo: (AgentApproval) -> Void
    let onContinueExternal: (AgentApproval) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = Self.configuredScrollView()
        guard let tableView = scrollView.documentView as? NSTableView else {
            return scrollView
        }
        context.coordinator.attach(tableView: tableView, scrollView: scrollView)
        return scrollView
    }

    static func configuredScrollView() -> NSScrollView {
        let tableView = AgentTranscriptTableView()
        tableView.headerView = nil
        tableView.backgroundColor = .clear
        tableView.gridStyleMask = []
        tableView.intercellSpacing = .zero
        tableView.rowHeight = 96
        tableView.usesAutomaticRowHeights = true
        tableView.selectionHighlightStyle = .none
        tableView.allowsEmptySelection = true
        tableView.allowsMultipleSelection = false
        tableView.allowsColumnSelection = false
        tableView.allowsTypeSelect = false
        tableView.focusRingType = .none
        tableView.setAccessibilityLabel("对话记录")

        let column = NSTableColumn(identifier: .agentTranscriptColumn)
        column.minWidth = 1
        column.resizingMask = .autoresizingMask
        tableView.addTableColumn(column)

        let scrollView = NSScrollView()
        scrollView.borderType = .noBorder
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.scrollerStyle = .overlay
        scrollView.documentView = tableView
        tableView.autoresizingMask = [.width]
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        context.coordinator.apply(
            sessionId: sessionId,
            persona: persona,
            rows: rows,
            actions: AgentTranscriptActions(
                onApprovalDecision: onApprovalDecision,
                onPrepareUndo: onPrepareUndo,
                onContinueExternal: onContinueExternal,
                activityExpanded: false,
                onActivityExpansionChange: { _ in }
            ),
            autoScrollRevision: autoScrollRevision,
            isStreaming: isStreaming,
            reduceMotion: reduceMotion
        )
    }

    static func dismantleNSView(_ nsView: NSScrollView, coordinator: Coordinator) {
        coordinator.detach()
    }

    final class Coordinator: NSObject, NSTableViewDataSource, NSTableViewDelegate {
        private weak var tableView: NSTableView?
        private weak var scrollView: NSScrollView?
        private var sessionId = ""
        private var persona = AgentRoleSummary.fallbackZhiyou
        private var rows: [AgentTranscriptRow] = []
        private var actions = AgentTranscriptActions.noop
        private var autoScrollRevision = ""
        private var scheduledScrollRevision = ""
        private var activityExpansionBySession: [String: Bool] = [:]

        func attach(tableView: NSTableView, scrollView: NSScrollView) {
            self.tableView = tableView
            self.scrollView = scrollView
            tableView.dataSource = self
            tableView.delegate = self
        }

        func detach() {
            tableView?.dataSource = nil
            tableView?.delegate = nil
            tableView = nil
            scrollView = nil
            rows = []
        }

        func apply(
            sessionId newSessionId: String,
            persona newPersona: AgentRoleSummary,
            rows newRows: [AgentTranscriptRow],
            actions newActions: AgentTranscriptActions,
            autoScrollRevision newAutoScrollRevision: String,
            isStreaming: Bool,
            reduceMotion: Bool
        ) {
            guard let tableView, let scrollView else { return }
            let wasNearBottom = isNearBottom(scrollView)
            let sessionChanged = sessionId != newSessionId
            let oldRows = rows
            let oldIds = oldRows.map(\.id)
            let newIds = newRows.map(\.id)

            sessionId = newSessionId
            persona = newPersona
            rows = newRows
            actions = newActions
            synchronizeColumnWidth(tableView: tableView, scrollView: scrollView)

            if sessionChanged {
                tableView.reloadData()
            } else if oldIds == newIds {
                refreshChangedVisibleRows(oldRows: oldRows, tableView: tableView)
            } else if newIds.starts(with: oldIds) {
                refreshChangedVisibleRows(oldRows: oldRows, tableView: tableView)
                let inserted = IndexSet(integersIn: oldRows.count..<newRows.count)
                performRowUpdate(animated: !reduceMotion && !isStreaming) {
                    tableView.insertRows(
                        at: inserted,
                        withAnimation: !reduceMotion && !isStreaming ? .effectFade : []
                    )
                }
            } else if oldIds.starts(with: newIds) {
                let removed = IndexSet(integersIn: newRows.count..<oldRows.count)
                performRowUpdate(animated: false) {
                    tableView.removeRows(at: removed, withAnimation: [])
                }
                refreshChangedVisibleRows(oldRows: Array(oldRows.prefix(newRows.count)), tableView: tableView)
            } else {
                // Tool/approval rows may move relative to a completed message.
                // Structural changes are infrequent; reloadData remains virtualized.
                tableView.reloadData()
            }

            tableView.layoutSubtreeIfNeeded()
            let revisionChanged = autoScrollRevision != newAutoScrollRevision
            autoScrollRevision = newAutoScrollRevision
            if sessionChanged || (revisionChanged && wasNearBottom) {
                scheduleScrollToBottom(
                    revision: newAutoScrollRevision,
                    animated: !sessionChanged && !isStreaming && !reduceMotion
                )
            }
        }

        func numberOfRows(in tableView: NSTableView) -> Int {
            rows.count
        }

        func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
            guard rows.indices.contains(row) else { return nil }
            let cell = tableView.makeView(
                withIdentifier: .agentTranscriptCell,
                owner: nil
            ) as? AgentTranscriptCellView ?? AgentTranscriptCellView()
            cell.identifier = .agentTranscriptCell
            cell.configure(
                row: rows[row],
                persona: persona,
                actions: rowActions(),
                isFirst: row == 0,
                isLast: row == rows.count - 1
            )
            return cell
        }

        func tableView(_ tableView: NSTableView, shouldSelectRow row: Int) -> Bool {
            false
        }

        private func refreshChangedVisibleRows(
            oldRows: [AgentTranscriptRow],
            tableView: NSTableView
        ) {
            let visible = tableView.rows(in: tableView.visibleRect)
            guard visible.location != NSNotFound, visible.length > 0 else { return }
            let lower = max(0, visible.location)
            let upper = min(rows.count, visible.location + visible.length)
            guard lower < upper else { return }

            var heightChanges = IndexSet()
            for index in lower..<upper {
                let changed = !oldRows.indices.contains(index) || oldRows[index] != rows[index]
                guard changed else { continue }
                if let cell = tableView.view(
                    atColumn: 0,
                    row: index,
                    makeIfNecessary: false
                ) as? AgentTranscriptCellView {
                    cell.configure(
                        row: rows[index],
                        persona: persona,
                        actions: rowActions(),
                        isFirst: index == 0,
                        isLast: index == rows.count - 1
                    )
                    heightChanges.insert(index)
                }
            }
            if !heightChanges.isEmpty {
                tableView.noteHeightOfRows(withIndexesChanged: heightChanges)
            }
        }

        private func synchronizeColumnWidth(
            tableView: NSTableView,
            scrollView: NSScrollView
        ) {
            guard let column = tableView.tableColumns.first else { return }
            let width = max(1, scrollView.contentSize.width)
            guard abs(column.width - width) > 0.5 else { return }
            column.width = width
            let visible = tableView.rows(in: tableView.visibleRect)
            if visible.location != NSNotFound, visible.length > 0 {
                tableView.noteHeightOfRows(
                    withIndexesChanged: IndexSet(
                        integersIn: visible.location..<(visible.location + visible.length)
                    )
                )
            }
        }

        private func performRowUpdate(animated: Bool, changes: () -> Void) {
            guard animated else {
                changes()
                return
            }
            NSAnimationContext.runAnimationGroup { context in
                context.duration = RagImeMotion.Duration.entrance
                context.timingFunction = RagImeMotion.timingFunction(.easeOut)
                changes()
            }
        }

        private func rowActions() -> AgentTranscriptActions {
            let base = actions
            return AgentTranscriptActions(
                onApprovalDecision: base.onApprovalDecision,
                onPrepareUndo: base.onPrepareUndo,
                onContinueExternal: base.onContinueExternal,
                activityExpanded: activityExpansionBySession[sessionId] ?? false,
                onActivityExpansionChange: { [weak self] expanded in
                    self?.setActivityExpanded(expanded)
                }
            )
        }

        private func setActivityExpanded(_ expanded: Bool) {
            guard let tableView else { return }
            activityExpansionBySession[sessionId] = expanded
            guard let index = rows.firstIndex(where: {
                if case .activity = $0 { return true }
                return false
            }) else { return }
            if let cell = tableView.view(
                atColumn: 0,
                row: index,
                makeIfNecessary: false
            ) as? AgentTranscriptCellView {
                cell.configure(
                    row: rows[index],
                    persona: persona,
                    actions: rowActions(),
                    isFirst: index == 0,
                    isLast: index == rows.count - 1
                )
            }
            tableView.noteHeightOfRows(withIndexesChanged: IndexSet(integer: index))
        }

        private func isNearBottom(_ scrollView: NSScrollView) -> Bool {
            guard let documentView = scrollView.documentView else { return true }
            let distance = documentView.bounds.maxY - scrollView.contentView.bounds.maxY
            return distance <= 96
        }

        private func scheduleScrollToBottom(revision: String, animated: Bool) {
            scheduledScrollRevision = revision
            DispatchQueue.main.async { [weak self] in
                guard let self,
                      self.scheduledScrollRevision == revision,
                      let tableView = self.tableView,
                      let scrollView = self.scrollView else { return }
                tableView.layoutSubtreeIfNeeded()
                let clipView = scrollView.contentView
                let target = NSPoint(
                    x: clipView.bounds.origin.x,
                    y: max(0, tableView.bounds.height - clipView.bounds.height)
                )
                guard animated else {
                    clipView.setBoundsOrigin(target)
                    scrollView.reflectScrolledClipView(clipView)
                    return
                }
                NSAnimationContext.runAnimationGroup { context in
                    context.duration = RagImeMotion.Duration.transition
                    context.timingFunction = RagImeMotion.timingFunction(.easeOut)
                    clipView.animator().setBoundsOrigin(target)
                } completionHandler: {
                    scrollView.reflectScrolledClipView(clipView)
                }
            }
        }
    }
}

private struct AgentTranscriptRowHost: View {
    let row: AgentTranscriptRow
    let persona: AgentRoleSummary
    let actions: AgentTranscriptActions
    let isFirst: Bool
    let isLast: Bool

    @ViewBuilder
    var rowContent: some View {
        switch row {
        case let .message(message):
            AgentMessageView(message: message, persona: persona)
                .equatable()
        case let .participantMessage(message, participantPersona):
            AgentMessageView(message: message, persona: participantPersona)
                .equatable()
        case let .activity(items, status):
            AgentActivityPanel(
                items: items,
                status: status,
                expanded: actions.activityExpanded,
                onExpansionChange: actions.onActivityExpansionChange
            )
                .equatable()
        case let .approval(approval, working):
            AgentApprovalCard(
                approval: approval,
                working: working,
                onApprove: { actions.onApprovalDecision(approval, true) },
                onReject: { actions.onApprovalDecision(approval, false) }
            )
        case let .receipt(approval, rollbackConsumed, externalActionWorking):
            AgentApprovalReceiptCard(
                approval: approval,
                rollbackConsumed: rollbackConsumed,
                externalActionWorking: externalActionWorking,
                onPrepareUndo: { actions.onPrepareUndo(approval) },
                onContinueExternal: { actions.onContinueExternal(approval) }
            )
        }
    }

    var body: some View {
        rowContent
            .frame(maxWidth: 840, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.horizontal, 24)
            .padding(.top, isFirst ? 26 : 0)
            .padding(.bottom, isLast ? 26 : 18)
            .transaction { transaction in
                transaction.animation = nil
            }
    }
}

private final class AgentTranscriptCellView: NSTableCellView {
    private var hostingView: NSHostingView<AgentTranscriptRowHost>?

    func configure(
        row: AgentTranscriptRow,
        persona: AgentRoleSummary,
        actions: AgentTranscriptActions,
        isFirst: Bool,
        isLast: Bool
    ) {
        let rootView = AgentTranscriptRowHost(
            row: row,
            persona: persona,
            actions: actions,
            isFirst: isFirst,
            isLast: isLast
        )
        if let hostingView {
            hostingView.rootView = rootView
            hostingView.invalidateIntrinsicContentSize()
            hostingView.needsLayout = true
            invalidateIntrinsicContentSize()
            needsLayout = true
            return
        }

        let hostingView = NSHostingView(rootView: rootView)
        hostingView.translatesAutoresizingMaskIntoConstraints = false
        hostingView.setContentHuggingPriority(.required, for: .vertical)
        hostingView.setContentCompressionResistancePriority(.required, for: .vertical)
        addSubview(hostingView)
        NSLayoutConstraint.activate([
            hostingView.leadingAnchor.constraint(equalTo: leadingAnchor),
            hostingView.trailingAnchor.constraint(equalTo: trailingAnchor),
            hostingView.topAnchor.constraint(equalTo: topAnchor),
            hostingView.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
        self.hostingView = hostingView
    }
}

private final class AgentTranscriptTableView: NSTableView {
    override func viewDidEndLiveResize() {
        super.viewDidEndLiveResize()
        let visible = rows(in: visibleRect)
        guard visible.location != NSNotFound, visible.length > 0 else { return }
        noteHeightOfRows(
            withIndexesChanged: IndexSet(
                integersIn: visible.location..<(visible.location + visible.length)
            )
        )
    }
}

private extension NSUserInterfaceItemIdentifier {
    static let agentTranscriptColumn = NSUserInterfaceItemIdentifier("rag-ime-agent-transcript-column")
    static let agentTranscriptCell = NSUserInterfaceItemIdentifier("rag-ime-agent-transcript-cell")
}

private func agentPersonaAccent(_ persona: AgentRoleSummary) -> Color {
    switch persona.visualProfile?.accentToken {
    case "blue": return .blue
    case "rose": return Color(red: 0.84, green: 0.28, blue: 0.46)
    case "neutral": return .secondary
    default: return ControlDesign.brand
    }
}

private func agentPersonaSymbol(_ persona: AgentRoleSummary) -> String {
    let value = persona.visualProfile?.symbolName.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    return value.isEmpty ? "sparkles" : value
}

struct AgentPersonaMark: View {
    let persona: AgentRoleSummary
    let state: RagImeCompanionState
    let size: CGFloat
    var animates = true

    var body: some View {
        if persona.roleId == "zhiyou-v1" {
            AgentCompanionHalo(state: state, size: size, animates: animates)
        } else {
            ZStack {
                RoundedRectangle(cornerRadius: min(8, size * 0.24))
                    .fill(agentPersonaAccent(persona).opacity(0.10))
                Image(systemName: agentPersonaSymbol(persona))
                    .font(.system(size: size * 0.46, weight: .semibold))
                    .foregroundStyle(state == .warning ? Color.orange : agentPersonaAccent(persona))
                    .frame(width: size, height: size)
            }
            .frame(width: size, height: size)
            .accessibilityLabel(persona.displayName)
        }
    }
}

private struct AgentPersonaWelcomeMark: View {
    let persona: AgentRoleSummary
    let state: RagImeCompanionState
    let size: CGFloat

    var body: some View {
        if persona.roleId == "zhiyou-v1" {
            RagImeFullBodyCompanion(state: state, size: size)
        } else {
            Image(systemName: agentPersonaSymbol(persona))
                .font(.system(size: size * 0.42, weight: .medium))
                .foregroundStyle(agentPersonaAccent(persona))
                .frame(width: size * 0.72, height: size * 0.72)
                .background(agentPersonaAccent(persona).opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(agentPersonaAccent(persona).opacity(0.18), lineWidth: 0.7)
                )
                .accessibilityLabel(persona.displayName)
        }
    }
}

private struct AgentCompanionHalo: View {
    let state: RagImeCompanionState
    let size: CGFloat
    var animates = true

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var orbiting = false

    var body: some View {
        ZStack {
            Circle()
                .fill(state.accent.opacity(0.10))
                .frame(width: size, height: size)
            if isActive {
                Circle()
                    .trim(from: 0.08, to: 0.72)
                    .stroke(state.accent.opacity(0.72), style: StrokeStyle(lineWidth: 1.4, lineCap: .round))
                    .frame(width: size + 5, height: size + 5)
                    .rotationEffect(.degrees(orbiting ? 360 : 0))
            }
            RagImeAnimeCompanion(
                state: state,
                size: size * 0.88,
                animatesAmbientMotion: false
            )
        }
        .frame(width: size + 7, height: size + 7)
        .onAppear { updateAnimation() }
        .onChange(of: state) { _ in updateAnimation() }
        .onChange(of: reduceMotion) { _ in updateAnimation() }
        .accessibilityHidden(true)
    }

    private var isActive: Bool { animates && (state == .thinking || state == .listening) }

    private func updateAnimation() {
        orbiting = false
        guard isActive, !reduceMotion else { return }
        withAnimation(.linear(duration: RagImeMotion.Duration.orbit).repeatForever(autoreverses: false)) {
            orbiting = true
        }
    }
}

struct AgentStatusDot: View {
    let color: Color
    let animated: Bool

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulsing = false

    var body: some View {
        ZStack {
            if animated && !reduceMotion {
                Circle()
                    .stroke(color.opacity(pulsing ? 0 : 0.46), lineWidth: 1)
                    .frame(width: 13, height: 13)
                    .scaleEffect(pulsing ? 1.25 : 0.65)
            }
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
        }
        .frame(width: 14, height: 14)
        .onAppear { updateAnimation() }
        .onChange(of: animated) { _ in updateAnimation() }
        .onChange(of: reduceMotion) { _ in updateAnimation() }
    }

    private func updateAnimation() {
        pulsing = false
        guard animated, !reduceMotion else { return }
        withAnimation(.easeOut(duration: RagImeMotion.Duration.ambientPulse).repeatForever(autoreverses: false)) {
            pulsing = true
        }
    }
}

private struct AgentThinkingIndicator: View {
    let active: Bool
    let color: Color

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var lifted = false

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(active ? color : Color.secondary.opacity(0.52))
                    .frame(width: 4, height: 4)
                    .offset(y: active && lifted ? -2 : 1)
                    .opacity(active ? (lifted ? 1 : 0.48) : 0.72)
                    .animation(
                        reduceMotion || !active
                            ? nil
                            : .easeInOut(duration: RagImeMotion.Duration.thinkingPulse)
                                .repeatForever(autoreverses: true)
                                .delay(Double(index) * RagImeMotion.stagger),
                        value: lifted
                    )
            }
        }
        .frame(width: 25, height: 18)
        .onAppear { lifted = active }
        .onChange(of: active) { value in lifted = value }
        .onChange(of: reduceMotion) { _ in lifted = active }
        .accessibilityHidden(true)
    }
}

private struct AgentActivityGlyph: View {
    let state: AgentActivityItem.State
    let tint: Color

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var spinning = false

    var body: some View {
        ZStack {
            switch state {
            case .running:
                Circle()
                    .stroke(tint.opacity(0.18), lineWidth: 2)
                Circle()
                    .trim(from: 0.10, to: 0.68)
                    .stroke(tint, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                    .rotationEffect(.degrees(spinning ? 360 : 0))
            case .completed:
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            case .failed:
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundStyle(.orange)
            case .waiting:
                Image(systemName: "person.crop.circle.badge.questionmark")
                    .foregroundStyle(tint)
            }
        }
        .font(.system(size: 14, weight: .semibold))
        .onAppear { updateAnimation() }
        .onChange(of: state) { _ in updateAnimation() }
    }

    private func updateAnimation() {
        spinning = false
        guard state == .running, !reduceMotion else { return }
        withAnimation(.linear(duration: RagImeMotion.Duration.progressSpin).repeatForever(autoreverses: false)) {
            spinning = true
        }
    }
}

struct AgentActivityPanel: View, Equatable {
    let items: [AgentActivityItem]
    let status: String
    let expanded: Bool
    let onExpansionChange: (Bool) -> Void

    init(
        items: [AgentActivityItem],
        status: String,
        expanded: Bool = false,
        onExpansionChange: @escaping (Bool) -> Void = { _ in }
    ) {
        self.items = items
        self.status = status
        self.expanded = expanded
        self.onExpansionChange = onExpansionChange
    }

    static func == (lhs: AgentActivityPanel, rhs: AgentActivityPanel) -> Bool {
        lhs.items == rhs.items && lhs.status == rhs.status && lhs.expanded == rhs.expanded
    }

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Button {
                withAnimation(RagImeMotion.spring(reduceMotion: reduceMotion)) {
                    onExpansionChange(!expanded)
                }
            } label: {
                HStack(spacing: 9) {
                    AgentThinkingIndicator(active: isRunning, color: tint)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(isRunning ? activeHeadline : "已核对资料")
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(.primary)
                        Text(isRunning ? activeDetail : completionSummary)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Text("\(completedCount)/\(items.count)")
                        .font(.caption2.monospacedDigit().weight(.medium))
                        .foregroundStyle(.secondary)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(expanded ? 180 : 0))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(RagImePressButtonStyle())

            if expanded {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(visibleItems.enumerated()), id: \.element.id) { index, item in
                        activityRow(item, showsConnector: index < visibleItems.count - 1)
                            .transition(.opacity.combined(with: .move(edge: .top)))
                    }
                }
                .padding(.leading, 5)
                .transition(.opacity.combined(with: .move(edge: .top)))
            } else if !summaryReferences.isEmpty {
                HStack(spacing: 6) {
                    ForEach(summaryReferences.prefix(4)) { reference in
                        AgentReferenceChip(reference: reference)
                    }
                }
                .padding(.leading, 34)
                .transition(.opacity)
            }
        }
        .padding(.vertical, 9)
        .padding(.horizontal, 10)
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(tint.opacity(isRunning ? 0.72 : 0.28))
                .frame(width: 2)
                .padding(.vertical, 8)
        }
        .frame(maxWidth: 720, alignment: .leading)
        .animation(RagImeMotion.stateChange(reduceMotion: reduceMotion), value: isRunning)
    }

    private func activityRow(_ item: AgentActivityItem, showsConnector: Bool) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 0) {
                AgentActivityGlyph(state: item.state, tint: tint)
                    .frame(width: 18, height: 18)
                if showsConnector {
                    Rectangle()
                        .fill(item.state == .completed ? Color.green.opacity(0.30) : ControlDesign.hairline)
                        .frame(width: 1)
                        .frame(minHeight: 25)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(item.state == .failed ? Color.orange : Color.primary)
                if !item.detail.isEmpty {
                    Text(item.detail)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                if !item.references.isEmpty {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 104, maximum: 180), spacing: 6)],
                        alignment: .leading,
                        spacing: 6
                    ) {
                        ForEach(item.references.prefix(6)) { reference in
                            AgentReferenceChip(reference: reference)
                        }
                    }
                    .padding(.top, 3)
                }
            }
            .padding(.bottom, showsConnector ? 7 : 0)
            Spacer(minLength: 0)
        }
    }

    private var visibleItems: [AgentActivityItem] {
        if isRunning { return Array(items.suffix(6)) }
        return items
    }

    private var summaryReferences: [AgentActivityReference] {
        var seen = Set<String>()
        return items.flatMap(\.references).filter { seen.insert($0.id).inserted }
    }

    private var completedCount: Int {
        items.filter { $0.state == .completed }.count
    }

    private var activeHeadline: String {
        items.last(where: { $0.state == .running })?.title ?? "正在查找和核对"
    }

    private var activeDetail: String {
        guard let item = items.last(where: { $0.state == .running }) else {
            return "正在整理可核对的活动"
        }
        return item.detail.isEmpty ? "正在继续处理" : item.detail
    }

    private var completionSummary: String {
        completedCount == 0 ? "本轮没有调用外部资料" : "完成 \(completedCount) 个步骤，可展开查看"
    }

    private var tint: Color { isRunning ? RagImeCompanionState.thinking.accent : Color.green }

    private var isRunning: Bool {
        items.contains(where: { $0.state == .running }) || ["busy", "analyzing", "working"].contains(status)
    }
}

private struct AgentReferenceChip: View {
    let reference: AgentActivityReference

    var body: some View {
        Label(reference.label, systemImage: symbol)
            .font(.caption2.weight(.medium))
            .foregroundStyle(color)
            .lineLimit(1)
            .padding(.horizontal, 7)
            .frame(height: 24)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(color.opacity(0.075))
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(color.opacity(0.18), lineWidth: 0.6))
            .help(helpText)
    }

    private var symbol: String {
        switch reference.kind {
        case .book: return "books.vertical"
        case .group: return "square.grid.2x2"
        case .tag: return "tag"
        case .recent: return "clock.arrow.circlepath"
        case .source: return "doc.text.magnifyingglass"
        }
    }

    private var color: Color {
        switch reference.kind {
        case .book: return ControlDesign.brand
        case .group: return Color.blue
        case .tag: return Color.orange
        case .recent: return Color.green
        case .source: return Color.secondary
        }
    }

    private var helpText: String {
        switch reference.kind {
        case .book: return "召回的记忆工具书"
        case .group: return "匹配到的记忆分组"
        case .tag: return "匹配到的标签"
        case .recent: return "召回的近期最终输入"
        case .source: return "召回来源"
        }
    }
}

private struct AgentApprovalCard: View {
    let approval: AgentApproval
    let working: Bool
    let onApprove: () -> Void
    let onReject: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "checkmark.shield")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(riskColor)
                    .frame(width: 34, height: 34)
                    .background(riskColor.opacity(0.09))
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 3) {
                    Text(previewTitle)
                        .font(.callout.weight(.semibold))
                    Text(previewSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Text(riskLabel)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(riskColor)
            }

            if !changes.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    ForEach(Array(changes.prefix(5).enumerated()), id: \.offset) { index, change in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(change.label)
                                .font(.caption.weight(.medium))
                                .lineLimit(2)
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(change.before)
                                    .strikethrough(!change.before.isEmpty)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Image(systemName: "arrow.right")
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                                Text(change.after)
                                    .fontWeight(.medium)
                                    .lineLimit(2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .font(.caption)
                            if index < min(changes.count, 5) - 1 {
                                Divider()
                            }
                        }
                    }
                    if changes.count > 5 {
                        Text("还有 \(changes.count - 5) 项已纳入同一次审批")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(10)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.7))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(ControlDesign.hairline, lineWidth: 0.7))
            }

            TimelineView(.periodic(from: .now, by: 1)) { context in
                let nowMs = Int(context.date.timeIntervalSince1970 * 1_000)
                let remainingMs = max(0, approval.expiresAtMs - nowMs)
                let remainingSeconds = (remainingMs + 999) / 1_000
                HStack(spacing: 9) {
                    Label(
                        remainingSeconds > 0 ? "\(remainingSeconds) 秒内有效" : "审批已过期",
                        systemImage: "timer"
                    )
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(remainingSeconds > 0 ? Color.secondary : Color.orange)
                    Spacer()
                    Button("拒绝", systemImage: "xmark") { onReject() }
                        .disabled(working || remainingSeconds == 0)
                    Button("批准并继续", systemImage: "checkmark") { onApprove() }
                        .buttonStyle(.borderedProminent)
                        .tint(riskColor)
                        .disabled(working || remainingSeconds == 0)
                    if working {
                        ProgressView().controlSize(.small)
                    }
                }
            }
        }
        .padding(14)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(riskColor.opacity(0.34), lineWidth: 0.9)
        )
        .overlay(alignment: .leading) {
            Capsule()
                .fill(riskColor)
                .frame(width: 3)
                .padding(.vertical, 11)
        }
        .frame(maxWidth: 620, alignment: .leading)
        .accessibilityElement(children: .contain)
    }

    private var preview: [String: JSONValue] { approval.preview.objectValue }

    private var previewTitle: String {
        let title = preview["title"]?.stringValue ?? ""
        return title.isEmpty ? "确认\(toolLabel)操作" : title
    }

    private var previewSummary: String {
        let summary = preview["summary"]?.stringValue ?? ""
        return summary.isEmpty ? "\(toolLabel)将在确认后执行“\(operationLabel)”" : summary
    }

    private var changes: [(label: String, before: String, after: String)] {
        (preview["changes"]?.arrayValue ?? []).compactMap { value in
            let item = value.objectValue
            let label = item["label"]?.stringValue
                ?? item["field"]?.stringValue
                ?? item["path"]?.stringValue
                ?? ""
            guard !label.isEmpty else { return nil }
            return (
                label,
                displayValue(item["before"]),
                displayValue(item["after"])
            )
        }
    }

    private var toolLabel: String {
        switch approval.toolId {
        case "ime_input": return "输入法"
        case "ime_voice": return "语音输入"
        case "ime_planning": return "规划"
        case "ime_memory": return "记忆"
        case "ime_knowledge": return "知识库"
        case "ime_models": return "模型"
        case "ime_runtime": return "运行组件"
        case "ime_configuration": return "配置"
        case "workspace_shell": return "Command Harness"
        default: return "控制中心"
        }
    }

    private var operationLabel: String {
        let text = preview["operationLabel"]?.stringValue ?? ""
        return text.isEmpty ? approval.operation : text
    }

    private var riskLabel: String {
        if approval.toolId == "ime_memory" { return "记忆变更" }
        if approval.toolId == "ime_input", approval.operation.contains("lexicon") { return "词表变更" }
        if approval.toolId == "ime_voice" { return "语音配置变更" }
        if approval.toolId == "ime_models" { return "模型配置变更" }
        if approval.toolId == "ime_runtime" { return "运行组件变更" }
        switch approval.riskLevel {
        case "R1": return "设置变更"
        case "R2": return "重要操作"
        default: return "高风险"
        }
    }

    private var riskColor: Color {
        approval.riskLevel == "R1" ? ControlDesign.brand : Color.orange
    }

    private func displayValue(_ value: JSONValue?) -> String {
        guard let value else { return "未设置" }
        switch value {
        case .bool(let flag): return flag ? "开启" : "关闭"
        case .null: return "未设置"
        default:
            let text = value.stringValue
            return text.isEmpty ? "未设置" : String(text.prefix(80))
        }
    }
}

private struct AgentApprovalReceiptCard: View {
    let approval: AgentApproval
    let rollbackConsumed: Bool
    let externalActionWorking: Bool
    let onPrepareUndo: () -> Void
    let onContinueExternal: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Image(
                systemName: applied
                    ? "checkmark.circle.fill"
                    : externalPending
                    ? externalActionSymbol
                    : "exclamationmark.circle.fill"
            )
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(accent)
                .frame(width: 30, height: 30)
                .background(accent.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 7) {
                    Text(applied ? appliedTitle : stateLabel)
                        .font(.caption.weight(.semibold))
                    if rollbackAvailable {
                        Label("可撤销", systemImage: "arrow.uturn.backward")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(ControlDesign.brand)
                    }
                }
                Text(summary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if !receiptError.isEmpty {
                    Text(receiptError)
                        .font(.caption2)
                        .foregroundStyle(Color.orange)
                        .lineLimit(2)
                }
                if approval.toolId == "workspace_shell", applied {
                    HStack(spacing: 9) {
                        Label("退出码 \(commandExitCode)", systemImage: commandExitCode == 0 ? "checkmark" : "exclamationmark")
                        Text("·")
                        Text("\(commandDurationMs) ms")
                        if receipt["networkAllowed"]?.boolValue == true {
                            Text("·")
                            Label("本次允许网络", systemImage: "network")
                        }
                    }
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(commandExitCode == 0 ? Color.secondary : Color.orange)

                    if !commandOutput.isEmpty {
                        ScrollView([.horizontal, .vertical]) {
                            Text(commandOutput)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(8)
                        }
                        .frame(maxHeight: 128)
                        .background(Color(nsColor: .textBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 5))
                        .overlay(RoundedRectangle(cornerRadius: 5).stroke(ControlDesign.hairline, lineWidth: 0.7))
                    }
                }
                if approval.toolId == "ime_memory", applied {
                    HStack(spacing: 9) {
                        Label("\(memoryDiffCount) 项差异", systemImage: "doc.text.magnifyingglass")
                        Text("·")
                        Text(memoryReceiptStatus)
                    }
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                }
                if approval.toolId == "ime_input", applied, approval.operation.contains("settings") {
                    HStack(spacing: 9) {
                        Label("\(inputSettingChangeCount) 项设置", systemImage: "slider.horizontal.3")
                        if inputRuntimeRevision > 0 {
                            Text("·")
                            Text("运行修订 \(inputRuntimeRevision)")
                        }
                    }
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                }
                if approval.toolId == "ime_input", applied, approval.operation.contains("lexicon") {
                    HStack(spacing: 9) {
                        Label("\(lexiconEntryCount) 条词条", systemImage: "text.book.closed")
                        Text("·")
                        Text(lexiconDeploymentLabel)
                    }
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(lexiconDeploymentReady ? Color.secondary : Color.orange)
                }
                if approval.toolId == "ime_runtime", applied {
                    HStack(spacing: 9) {
                        Label(runtimeReceiptLabel, systemImage: runtimeReceiptSymbol)
                        if runtimeReceiptRevision > 0 {
                            Text("·")
                            Text("运行修订 \(runtimeReceiptRevision)")
                        }
                    }
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                }
                if approval.toolId == "ime_runtime", externalPending {
                    HStack(spacing: 9) {
                        Label("Pi 回合结束后执行", systemImage: "hourglass")
                        Text("·")
                        Text("由原生监督器重启")
                    }
                    .font(.caption2)
                    .foregroundStyle(ControlDesign.brand)
                }
                if approval.toolId == "ime_configuration", approval.operation == "restore_apply", externalPending {
                    HStack(spacing: 9) {
                        Label("Pi 回合结束后执行", systemImage: "hourglass")
                        Text("·")
                        Text("停止 Sidecar · 恢复 · 重新启动")
                    }
                    .font(.caption2)
                    .foregroundStyle(ControlDesign.brand)
                }
                if approval.toolId == "ime_models", applied, approval.operation.contains("profile") {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 9) {
                            Label(modelProfileLabel, systemImage: "cpu")
                            Text("·")
                            Text(modelActivationLabel)
                        }
                        .foregroundStyle(modelActivationReady ? Color.secondary : Color.orange)
                        if receipt["secretsPreserved"]?.boolValue == true {
                            Label("现有密钥保持不变", systemImage: "key.fill")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .font(.caption2)
                }
                if approval.toolId == "ime_voice", applied, approval.operation.contains("provider") {
                    HStack(spacing: 9) {
                        Label(voiceProviderLabel, systemImage: "waveform")
                        Text("·")
                        Text("等待语音代理重启后激活")
                        if receipt["secretsPreserved"]?.boolValue == true {
                            Text("·")
                            Label("凭据未改动", systemImage: "key.fill")
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(Color.orange)
                }
                if approval.toolId == "ime_configuration", applied, approval.operation == "export" {
                    HStack(spacing: 9) {
                        Label(configurationBackupFileName, systemImage: "archivebox")
                        Text("·")
                        Text(configurationBackupSize)
                        Text("·")
                        Label("不含密钥", systemImage: "key.slash")
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
                if approval.toolId == "ime_configuration", applied, approval.operation == "restore_apply" {
                    HStack(spacing: 9) {
                        Label("数据库与安全配置已恢复", systemImage: "externaldrive.badge.checkmark")
                        if !configurationRollbackFileName.isEmpty {
                            Text("·")
                            Text("回滚包已保留")
                        }
                        Text("·")
                        Label("密钥未改动", systemImage: "key.slash")
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
                if rollbackAvailable {
                    Button("准备撤销", systemImage: "arrow.uturn.backward") {
                        onPrepareUndo()
                    }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.medium))
                    .help("先放入输入框，由你确认发送后再创建新的撤销审批")
                }
                if externalPending {
                    Button {
                        onContinueExternal()
                    } label: {
                        Label(
                            externalActionWorking ? "等待 Pi 收尾" : "继续执行",
                            systemImage: externalActionWorking ? "hourglass" : "play.fill"
                        )
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .disabled(externalActionWorking)
                    .help("仅在 Pi 当前回答结束后执行固定白名单监督动作；不会调用任意 Shell")
                }
            }
            Spacer(minLength: 8)
            Text(approval.riskLevel)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(accent)
        }
        .padding(12)
        .background(accent.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .overlay(RoundedRectangle(cornerRadius: 7).stroke(accent.opacity(0.20), lineWidth: 0.8))
        .frame(maxWidth: 620, alignment: .leading)
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private var receipt: [String: JSONValue] {
        approval.receipt?.objectValue ?? [:]
    }

    private var applied: Bool { approval.state == "applied" }
    private var externalPending: Bool { approval.state == "external_pending" }
    private var externalActionSymbol: String {
        approval.operation == "restore_apply"
            ? "externaldrive.badge.timemachine"
            : "arrow.triangle.2.circlepath.circle.fill"
    }
    private var appliedTitle: String {
        if approval.toolId == "workspace_shell" { return "命令已执行" }
        if approval.toolId == "ime_memory" {
            return approval.operation == "maintenance_rollback" ? "记忆整理已回滚" : "记忆草案已应用"
        }
        if approval.toolId == "ime_input" {
            switch approval.operation {
            case "apply_settings": return "输入设置已更新"
            case "rollback_settings": return "输入设置已恢复"
            case "lexicon_apply": return "个人词表已应用"
            case "lexicon_rollback": return "个人词表已回滚"
            default: break
            }
        }
        if approval.toolId == "ime_runtime" {
            switch approval.operation {
            case "pause_ai": return "AI 辅助已暂停"
            case "resume_ai": return "AI 辅助已恢复"
            case "restart_sidecar": return "Sidecar 已重启"
            case "restart_predictor": return "本地预测器已重启"
            case "redeploy_rime": return "Rime 已重新部署"
            default: break
            }
        }
        if approval.toolId == "ime_models" {
            return approval.operation == "profile_rollback" ? "Provider 配置已恢复" : "Provider 配置已保存"
        }
        if approval.toolId == "ime_voice" {
            return approval.operation == "provider_rollback" ? "语音 Provider 已恢复" : "语音 Provider 已保存"
        }
        if approval.toolId == "ime_configuration" {
            if approval.operation == "export" { return "便携备份已导出" }
            if approval.operation == "restore_apply" { return "便携备份已恢复" }
        }
        return "操作已应用"
    }
    private var accent: Color {
        applied ? Color.green : externalPending ? ControlDesign.brand : Color.orange
    }
    private var rollbackAvailable: Bool {
        receipt["undoAvailable"]?.boolValue == true && !rollbackConsumed
    }

    private var summary: String {
        let value = receipt["summary"]?.stringValue ?? ""
        if !value.isEmpty { return value }
        return applied ? "变更已写入并保存执行回执。" : "没有应用任何变更。"
    }

    private var receiptError: String {
        receipt["error"]?.stringValue ?? receipt["warning"]?.stringValue ?? ""
    }

    private var commandExitCode: Int {
        Int(receipt["exitCode"]?.numberValue ?? -1)
    }

    private var commandDurationMs: Int {
        Int(receipt["durationMs"]?.numberValue ?? 0)
    }

    private var commandOutput: String {
        String((receipt["output"]?.stringValue ?? "").prefix(12_000))
    }

    private var memoryDiffCount: Int {
        Int(receipt["diffCount"]?.numberValue ?? 0)
    }

    private var memoryReceiptStatus: String {
        switch receipt["status"]?.stringValue {
        case "applied": return "已写入并重建检索索引"
        case "rolled_back": return "已恢复并重建检索索引"
        case "partial": return "部分差异已应用"
        default: return "回执已保存"
        }
    }

    private var inputSettingChangeCount: Int {
        Int(receipt["changeCount"]?.numberValue ?? 0)
    }

    private var inputRuntimeRevision: Int {
        Int(receipt["runtimeRevision"]?.numberValue ?? 0)
    }

    private var lexiconEntryCount: Int {
        Int(receipt["entryCount"]?.numberValue ?? 0)
    }

    private var lexiconDeploymentReady: Bool {
        receipt["deploymentStatus"]?.stringValue == "succeeded"
    }

    private var lexiconDeploymentLabel: String {
        switch receipt["deploymentStatus"]?.stringValue {
        case "succeeded": return "Rime 已重新部署"
        case "timed_out": return "重新部署超时"
        case "failed": return "重新部署失败"
        default: return "重新部署状态未知"
        }
    }

    private var runtimeReceiptRevision: Int {
        Int(receipt["runtimeRevision"]?.numberValue ?? 0)
    }

    private var runtimeReceiptLabel: String {
        switch approval.operation {
        case "pause_ai": return "普通拼音继续可用"
        case "resume_ai": return "AI 候选与生成已恢复"
        case "restart_sidecar": return "新 Sidecar 进程已确认"
        case "restart_predictor": return "预测进程已换新"
        case "redeploy_rime": return "输入方案已重新加载"
        default: return "运行组件已更新"
        }
    }

    private var runtimeReceiptSymbol: String {
        switch approval.operation {
        case "pause_ai": return "pause.fill"
        case "resume_ai": return "play.fill"
        case "restart_sidecar": return "arrow.triangle.2.circlepath"
        case "restart_predictor": return "cpu"
        case "redeploy_rime": return "keyboard"
        default: return "wrench.and.screwdriver"
        }
    }

    private var modelProfileLabel: String {
        let profile = receipt["afterProfile"]?.objectValue ?? [:]
        let provider = profile["provider"]?.stringValue ?? "Provider"
        let model = profile["model"]?.stringValue ?? ""
        return model.isEmpty ? provider : "\(provider) · \(model)"
    }

    private var modelActivationReady: Bool {
        receipt["activationStatus"]?.stringValue == "succeeded"
    }

    private var modelActivationLabel: String {
        switch receipt["activationStatus"]?.stringValue {
        case "succeeded": return "已激活"
        case "pending_external_restart": return "等待 Sidecar 重启后激活"
        case "failed": return "重启失败，配置已保存"
        case "timed_out": return "重启超时，配置已保存"
        default: return "激活状态待确认"
        }
    }

    private var voiceProviderLabel: String {
        let provider = receipt["afterProvider"]?.stringValue ?? ""
        switch provider {
        case "native_streaming": return "原生流式语音"
        case "realtime_websocket": return "实时 WebSocket"
        case "http_transcription": return "HTTP 转写"
        default: return provider.isEmpty ? "语音 Provider" : provider
        }
    }

    private var stateLabel: String {
        switch approval.state {
        case "external_pending":
            return approval.operation == "restore_apply" ? "等待外部恢复" : "等待外部重启"
        case "failed": return "操作未执行"
        case "expired": return "审批已过期"
        case "stale": return "目标已变化"
        default: return "操作已拒绝"
        }
    }

    private var configurationBackupFileName: String {
        let name = receipt["fileName"]?.stringValue ?? ""
        return name.isEmpty ? "RAG-IME 便携备份" : name
    }

    private var configurationBackupSize: String {
        let bytes = Int64(receipt["sizeBytes"]?.numberValue ?? 0)
        return ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }

    private var configurationRollbackFileName: String {
        receipt["rollbackFileName"]?.stringValue ?? ""
    }
}

private struct AgentMessageView: View, Equatable {
    let message: AgentMessage
    let persona: AgentRoleSummary

    static func == (lhs: AgentMessageView, rhs: AgentMessageView) -> Bool {
        lhs.message == rhs.message && lhs.persona == rhs.persona
    }

    @ViewBuilder
    var body: some View {
        if message.role == "user" {
            HStack(alignment: .top) {
                Spacer(minLength: 96)
                blockStack
                    .padding(.horizontal, 13)
                    .padding(.vertical, 10)
                    .background(ControlDesign.brand.opacity(0.105))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(ControlDesign.brand.opacity(0.16), lineWidth: 0.7)
                    )
                    .frame(maxWidth: 560, alignment: .leading)
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        } else {
            HStack(alignment: .top, spacing: 11) {
                AgentPersonaMark(
                    persona: persona,
                    state: message.status == "failed" ? .warning : (message.status == "streaming" ? .thinking : .done),
                    size: 32,
                    animates: false
                )
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 6) {
                        Text(persona.displayName)
                            .font(.caption.weight(.semibold))
                        if message.status == "streaming" {
                            AgentThinkingIndicator(
                                active: true,
                                color: agentPersonaAccent(persona)
                            )
                        }
                    }
                    .foregroundStyle(.secondary)
                    blockStack
                }
                .frame(maxWidth: 740, alignment: .leading)
                Spacer(minLength: 24)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var blockStack: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(message.blocks) { block in
                AgentBlockView(block: block, sessionId: message.sessionId)
                    .equatable()
            }
        }
    }
}

private struct AgentStreamingText: View, Equatable {
    let value: String

    static func == (lhs: AgentStreamingText, rhs: AgentStreamingText) -> Bool {
        lhs.value == rhs.value
    }

    var body: some View {
        AgentIncrementalTextSurface(text: value)
            .frame(maxWidth: .infinity, alignment: .leading)
        .transaction { transaction in
            transaction.animation = nil
        }
    }
}

private struct AgentIncrementalTextSurface: NSViewRepresentable {
    let text: String

    func makeNSView(context: Context) -> AgentIncrementalTextView {
        AgentIncrementalTextView()
    }

    func updateNSView(_ nsView: AgentIncrementalTextView, context: Context) {
        nsView.updateStreamingText(text)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        nsView: AgentIncrementalTextView,
        context: Context
    ) -> CGSize? {
        let width = max(80, proposal.width ?? 620)
        return CGSize(width: width, height: nsView.measuredHeight(for: width))
    }
}

private final class AgentIncrementalTextView: NSTextView {
    private let streamingCaret = CALayer()
    private let bodyFont = NSFont.systemFont(ofSize: NSFont.systemFontSize)

    init() {
        let storage = NSTextStorage()
        let layoutManager = NSLayoutManager()
        let container = NSTextContainer(containerSize: NSSize(width: 620, height: CGFloat.greatestFiniteMagnitude))
        container.widthTracksTextView = true
        container.heightTracksTextView = false
        container.lineFragmentPadding = 0
        layoutManager.addTextContainer(container)
        storage.addLayoutManager(layoutManager)
        super.init(frame: .zero, textContainer: container)
        isEditable = false
        isSelectable = true
        drawsBackground = false
        isHorizontallyResizable = false
        isVerticallyResizable = true
        textContainerInset = .zero
        font = bodyFont
        textColor = .labelColor
        wantsLayer = true
        streamingCaret.backgroundColor = NSColor.controlAccentColor.cgColor
        streamingCaret.cornerRadius = 1
        layer?.addSublayer(streamingCaret)
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            streamingCaret.opacity = 0.72
        } else {
            let pulse = CABasicAnimation(keyPath: "opacity")
            pulse.fromValue = 0.22
            pulse.toValue = 0.92
            pulse.duration = RagImeMotion.Duration.thinkingPulse
            pulse.autoreverses = true
            pulse.repeatCount = .infinity
            pulse.timingFunction = RagImeMotion.timingFunction(.easeInEaseOut)
            streamingCaret.add(pulse, forKey: "rag-ime-stream-caret")
        }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func updateStreamingText(_ value: String) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: bodyFont,
            .foregroundColor: NSColor.labelColor,
        ]
        if value.hasPrefix(string) {
            let suffix = String(value.dropFirst(string.count))
            if !suffix.isEmpty {
                textStorage?.append(NSAttributedString(string: suffix, attributes: attributes))
            }
        } else if value != string {
            textStorage?.setAttributedString(NSAttributedString(string: value, attributes: attributes))
        }
        invalidateIntrinsicContentSize()
        needsLayout = true
    }

    func measuredHeight(for width: CGFloat) -> CGFloat {
        guard let textContainer, let layoutManager else { return 20 }
        textContainer.containerSize = NSSize(width: max(1, width), height: CGFloat.greatestFiniteMagnitude)
        layoutManager.ensureLayout(for: textContainer)
        return max(20, ceil(layoutManager.usedRect(for: textContainer).height))
    }

    override func layout() {
        super.layout()
        positionStreamingCaret()
    }

    private func positionStreamingCaret() {
        guard let textContainer, let layoutManager else { return }
        layoutManager.ensureLayout(for: textContainer)
        let glyphCount = layoutManager.numberOfGlyphs
        if glyphCount == 0 {
            streamingCaret.frame = NSRect(x: 0, y: 2, width: 2, height: bodyFont.ascender - bodyFont.descender)
            return
        }
        let glyphRange = NSRange(location: glyphCount - 1, length: 1)
        let rect = layoutManager.boundingRect(forGlyphRange: glyphRange, in: textContainer)
        let origin = textContainerOrigin
        streamingCaret.frame = NSRect(
            x: min(bounds.width - 2, origin.x + rect.maxX + 2),
            y: origin.y + rect.minY,
            width: 2,
            height: max(12, rect.height)
        )
    }
}

private struct AgentMarkdownBlock: Equatable, Identifiable {
    enum Kind: Equatable {
        case paragraph
        case heading(Int)
        case bullet
        case numbered(String)
        case quote
        case code(String)
        case divider
    }

    let id: Int
    let kind: Kind
    let text: String
}

/// A small block renderer keeps conversation output native and fast while still
/// preserving the visual hierarchy that SwiftUI's single Text view flattens.
private struct AgentMarkdownView: View, Equatable {
    let source: String

    private var blocks: [AgentMarkdownBlock] {
        Self.parse(source)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(blocks) { block in
                blockView(block)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder
    private func blockView(_ block: AgentMarkdownBlock) -> some View {
        switch block.kind {
        case let .heading(level):
            inlineText(block.text)
                .font(level == 1 ? .title3.weight(.bold) : .headline.weight(.semibold))
                .foregroundStyle(level == 1 ? ControlDesign.brand : Color.primary)
                .padding(.top, level == 1 ? 3 : 1)
        case .paragraph:
            inlineText(block.text)
                .font(.body)
                .lineSpacing(3)
        case .bullet:
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Circle()
                    .fill(ControlDesign.brand.opacity(0.75))
                    .frame(width: 5, height: 5)
                inlineText(block.text)
                    .font(.body)
                    .lineSpacing(3)
            }
        case let .numbered(marker):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(marker)
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .foregroundStyle(ControlDesign.brand)
                    .frame(minWidth: 18, alignment: .trailing)
                inlineText(block.text)
                    .font(.body)
                    .lineSpacing(3)
            }
        case .quote:
            HStack(alignment: .top, spacing: 10) {
                RoundedRectangle(cornerRadius: 1)
                    .fill(ControlDesign.brand.opacity(0.42))
                    .frame(width: 3)
                inlineText(block.text)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineSpacing(3)
            }
            .padding(.vertical, 2)
        case let .code(language):
            VStack(alignment: .leading, spacing: 5) {
                if !language.isEmpty {
                    Text(language.uppercased())
                        .font(.caption2.monospaced().weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    Text(block.text)
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: true, vertical: true)
                }
            }
            .padding(10)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(ControlDesign.hairline, lineWidth: 0.7))
        case .divider:
            Divider().padding(.vertical, 2)
        }
    }

    private func inlineText(_ value: String) -> Text {
        if let attributed = try? AttributedString(markdown: value) {
            return Text(attributed)
        }
        return Text(value)
    }

    private static func parse(_ source: String) -> [AgentMarkdownBlock] {
        let normalized = source.replacingOccurrences(of: "\r\n", with: "\n")
        var result: [AgentMarkdownBlock] = []
        var paragraph: [String] = []
        var code: [String] = []
        var codeLanguage = ""
        var inCode = false

        func append(_ kind: AgentMarkdownBlock.Kind, _ text: String = "") {
            result.append(AgentMarkdownBlock(id: result.count, kind: kind, text: text))
        }

        func flushParagraph() {
            let value = paragraph.joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
            if !value.isEmpty { append(.paragraph, value) }
            paragraph.removeAll(keepingCapacity: true)
        }

        for rawLine in normalized.components(separatedBy: "\n") {
            let trimmed = rawLine.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("```") {
                if inCode {
                    append(.code(codeLanguage), code.joined(separator: "\n"))
                    code.removeAll(keepingCapacity: true)
                    codeLanguage = ""
                    inCode = false
                } else {
                    flushParagraph()
                    codeLanguage = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                    inCode = true
                }
                continue
            }
            if inCode {
                code.append(rawLine)
                continue
            }
            if trimmed.isEmpty {
                flushParagraph()
                continue
            }
            if trimmed == "---" || trimmed == "***" {
                flushParagraph()
                append(.divider)
                continue
            }
            if let heading = headingParts(trimmed) {
                flushParagraph()
                append(.heading(heading.level), heading.text)
                continue
            }
            if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                flushParagraph()
                append(.bullet, String(trimmed.dropFirst(2)))
                continue
            }
            if let numbered = numberedParts(trimmed) {
                flushParagraph()
                append(.numbered(numbered.marker), numbered.text)
                continue
            }
            if trimmed.hasPrefix("> ") {
                flushParagraph()
                append(.quote, String(trimmed.dropFirst(2)))
                continue
            }
            paragraph.append(trimmed)
        }
        if inCode { append(.code(codeLanguage), code.joined(separator: "\n")) }
        flushParagraph()
        return result.isEmpty ? [AgentMarkdownBlock(id: 0, kind: .paragraph, text: source)] : result
    }

    private static func headingParts(_ line: String) -> (level: Int, text: String)? {
        let prefix = line.prefix(while: { $0 == "#" })
        guard !prefix.isEmpty, prefix.count <= 3 else { return nil }
        let remainder = line.dropFirst(prefix.count)
        guard remainder.first == " " else { return nil }
        return (prefix.count, String(remainder.dropFirst()))
    }

    private static func numberedParts(_ line: String) -> (marker: String, text: String)? {
        guard let dot = line.firstIndex(of: ".") else { return nil }
        let digits = line[..<dot]
        guard !digits.isEmpty, digits.allSatisfy(\.isNumber) else { return nil }
        let remainder = line[line.index(after: dot)...]
        guard remainder.first == " " else { return nil }
        return ("\(digits).", String(remainder.dropFirst()))
    }
}

private struct AgentBlockView: View, Equatable {
    let block: AgentBlock
    let sessionId: String

    static func == (lhs: AgentBlockView, rhs: AgentBlockView) -> Bool {
        lhs.block == rhs.block && lhs.sessionId == rhs.sessionId
    }

    var body: some View {
        switch block.type {
        case .text:
            if block.status == "running" {
                AgentStreamingText(value: block.data.objectValue["text"]?.stringValue ?? "")
            } else {
                AgentMarkdownView(source: block.data.objectValue["text"]?.stringValue ?? "")
                    .textSelection(.enabled)
            }
        case .code:
            ScrollView(.horizontal) {
                Text(block.data.objectValue["code"]?.stringValue ?? block.data.objectValue["text"]?.stringValue ?? "")
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(10)
            }
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
        case .progress, .reasoningSummary:
            Label(
                block.data.objectValue["label"]?.stringValue
                    ?? block.data.objectValue["summary"]?.stringValue
                    ?? "处理中",
                systemImage: "sparkles"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
        case .toolCall, .toolResult:
            HStack(spacing: 8) {
                Image(systemName: block.type == .toolCall ? "wrench.and.screwdriver" : "checkmark.circle")
                    .foregroundStyle(ControlDesign.brand)
                Text(toolLabel)
                    .font(.caption.weight(.medium))
                Spacer()
            }
            .padding(9)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
        case .citation:
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "quote.opening")
                    .foregroundStyle(ControlDesign.brand)
                VStack(alignment: .leading, spacing: 2) {
                    Text(block.data.objectValue["title"]?.stringValue ?? "引用来源")
                        .font(.caption.weight(.semibold))
                    Text(block.data.objectValue["snippet"]?.stringValue ?? "")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
            }
        case .image:
            AgentImageBlockView(sessionId: sessionId, block: block)
        case .audio:
            AgentAudioBlockView(sessionId: sessionId, block: block)
        case .file:
            AgentFileBlockView(sessionId: sessionId, block: block)
        case .sticker:
            AgentStickerBlockView(sessionId: sessionId, block: block)
        case .taskPlan:
            mediaPlaceholder(symbol: "checklist", label: "任务计划")
        case .diff:
            mediaPlaceholder(symbol: "arrow.left.arrow.right", label: "变更预览")
        case .approval:
            mediaPlaceholder(symbol: "checkmark.shield", label: "等待确认")
        case .error:
            VStack(alignment: .leading, spacing: 3) {
                Label(userFacingErrorTitle, systemImage: "exclamationmark.triangle")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.orange)
                Text(userFacingErrorDetail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .help(rawErrorMessage)
        case .unknown:
            Label("此内容需要更新后查看", systemImage: "questionmark.square.dashed")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var toolLabel: String {
        let data = block.data.objectValue
        let name = data["displayName"]?.stringValue ?? data["toolName"]?.stringValue ?? "工具"
        return name.hasPrefix("ime_") ? "已调用受控工具" : name
    }

    private var rawErrorMessage: String {
        let value = block.data.objectValue["message"]?.stringValue ?? ""
        return value.isEmpty ? "内容生成失败" : value
    }

    private var userFacingErrorTitle: String {
        let normalized = rawErrorMessage.lowercased()
        if normalized.contains("401") || normalized.contains("403") || normalized.contains("unauthorized") {
            return "模型连接需要检查"
        }
        if normalized.contains("timeout") || normalized.contains("timed out") {
            return "这次等待超时了"
        }
        return "这次没有完成"
    }

    private var userFacingErrorDetail: String {
        let normalized = rawErrorMessage.lowercased()
        if normalized.contains("401") || normalized.contains("403") || normalized.contains("unauthorized") {
            return "请在模型设置中检查当前服务；原始错误可悬停查看。"
        }
        if normalized.contains("timeout") || normalized.contains("timed out") {
            return "可以直接重试，已保存的对话不会丢失。"
        }
        return "上游模型暂时没有返回可用结果，可以稍后重试。"
    }

    private func mediaPlaceholder(symbol: String, label: String) -> some View {
        Label(label, systemImage: symbol)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(9)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

struct AgentNewSessionSheet: View {
    let roles: [AgentRoleSummary]
    let onCreate: (String, String, String, String, [String]) async -> Bool

    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var title = "新对话"
    @State private var mode = "assistant"
    @State private var selectedPersonaId: String
    @State private var workspaceRoots: [URL] = []
    @State private var creating = false

    init(
        roles: [AgentRoleSummary],
        onCreate: @escaping (String, String, String, String, [String]) async -> Bool
    ) {
        self.roles = roles
        self.onCreate = onCreate
        let initial = roles.first(where: { $0.supports(mode: "assistant") }) ?? .fallbackZhiyou
        _selectedPersonaId = State(initialValue: initial.id)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .center, spacing: 12) {
                AgentPersonaMark(
                    persona: mode == "coordinator" ? .fallbackZhiyou : selectedPersona,
                    state: mode == "coordinator" ? .thinking : .idle,
                    size: 46
                )
                VStack(alignment: .leading, spacing: 3) {
                    Text(mode == "coordinator" ? "新建运行协调" : "新建\(selectedPersona.displayName)对话")
                        .font(.title3.weight(.semibold))
                    Text(mode == "coordinator" ? "独立的工作区协调 Session" : "连续对话、检索和控制中心工具")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            VStack(alignment: .leading, spacing: 7) {
                Text("名称")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                TextField("对话名称", text: $title)
                    .textFieldStyle(.roundedBorder)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("模式")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Picker("模式", selection: $mode) {
                    Label("助手", systemImage: "sparkles").tag("assistant")
                    Label("运行协调", systemImage: "terminal").tag("coordinator")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }

            if mode == "assistant" {
                VStack(alignment: .leading, spacing: 8) {
                    Text("角色")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    VStack(spacing: 0) {
                        ForEach(Array(availablePersonas.enumerated()), id: \.element.id) { index, persona in
                            personaSelectionRow(persona)
                            if index < availablePersonas.count - 1 {
                                Divider().padding(.leading, 48)
                            }
                        }
                    }
                    .background(Color(nsColor: .controlBackgroundColor))
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                    .overlay(
                        RoundedRectangle(cornerRadius: 7)
                            .stroke(ControlDesign.hairline, lineWidth: 0.7)
                    )

                    Text(selectedPersona.summary ?? selectedPersona.tagline)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .transition(.opacity)
            }

            if mode == "coordinator" {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("授权工作区")
                                .font(.callout.weight(.semibold))
                            Text("Pi 只能浏览这里；命令仍需逐条批准并经过 macOS Harness")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button(action: chooseWorkspace) {
                            Image(systemName: "folder.badge.plus")
                                .frame(width: 26, height: 26)
                        }
                        .buttonStyle(.borderless)
                        .help("添加工作区")
                    }

                    if workspaceRoots.isEmpty {
                        Label("至少选择一个项目文件夹", systemImage: "folder")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .frame(maxWidth: .infinity, minHeight: 38, alignment: .leading)
                    } else {
                        VStack(spacing: 0) {
                            ForEach(workspaceRoots, id: \.path) { root in
                                HStack(spacing: 9) {
                                    Image(systemName: "folder.fill")
                                        .foregroundStyle(ControlDesign.brand)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(root.lastPathComponent)
                                            .font(.caption.weight(.semibold))
                                        Text(root.deletingLastPathComponent().path)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                            .truncationMode(.middle)
                                    }
                                    Spacer()
                                    Button {
                                        workspaceRoots.removeAll(where: { $0.path == root.path })
                                    } label: {
                                        Image(systemName: "xmark")
                                            .frame(width: 22, height: 22)
                                    }
                                    .buttonStyle(.borderless)
                                    .help("移除工作区")
                                }
                                .frame(height: 44)
                                if root.path != workspaceRoots.last?.path { Divider() }
                            }
                        }
                        .padding(.horizontal, 10)
                        .background(Color(nsColor: .controlBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 7))
                        .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
                    }

                    Label(
                        "提权、Keychain、TCC、破坏性命令和秘密参数在首版直接拒绝",
                        systemImage: "lock.shield"
                    )
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

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
                            mode,
                            creationPersona.roleId,
                            creationPersona.version,
                            mode == "coordinator" ? workspaceRoots.map(\.path) : []
                        )
                        creating = false
                        if created { dismiss() }
                    }
                } label: {
                    if creating {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("创建", systemImage: "plus")
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(mode == "coordinator" ? Color.orange : ControlDesign.brand)
                .disabled(!canCreate || creating)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: 540)
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: mode)
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: selectedPersonaId)
    }

    private var availablePersonas: [AgentRoleSummary] {
        let values = roles.filter { $0.supports(mode: "assistant") }
        return values.isEmpty ? [.fallbackZhiyou] : values
    }

    private var selectedPersona: AgentRoleSummary {
        availablePersonas.first(where: { $0.id == selectedPersonaId }) ?? availablePersonas[0]
    }

    private var creationPersona: AgentRoleSummary {
        mode == "coordinator" ? .fallbackZhiyou : selectedPersona
    }

    private func personaSelectionRow(_ persona: AgentRoleSummary) -> some View {
        Button {
            selectedPersonaId = persona.id
        } label: {
            HStack(spacing: 10) {
                Image(systemName: agentPersonaSymbol(persona))
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(agentPersonaAccent(persona))
                    .frame(width: 30, height: 30)
                    .background(agentPersonaAccent(persona).opacity(0.09))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 7) {
                        Text(persona.displayName)
                            .font(.callout.weight(.semibold))
                        if let traits = persona.traits, !traits.isEmpty {
                            Text(traits.joined(separator: " · "))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                                .lineLimit(1)
                        }
                    }
                    Text(persona.tagline)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                Image(systemName: selectedPersonaId == persona.id ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(selectedPersonaId == persona.id ? agentPersonaAccent(persona) : Color.secondary)
            }
            .padding(.horizontal, 9)
            .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading)
            .background(
                selectedPersonaId == persona.id
                    ? agentPersonaAccent(persona).opacity(0.055)
                    : Color.clear
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(persona.displayName)，\(persona.tagline)")
        .accessibilityValue(selectedPersonaId == persona.id ? "已选择" : "未选择")
    }

    private var normalizedTitle: String {
        String(
            title
                .split(whereSeparator: { $0.isWhitespace })
                .joined(separator: " ")
                .prefix(120)
        )
    }

    private var canCreate: Bool {
        !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (mode == "assistant" || !workspaceRoots.isEmpty)
    }

    private func chooseWorkspace() {
        let panel = NSOpenPanel()
        panel.title = "选择运行协调工作区"
        panel.prompt = "授权"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.canCreateDirectories = false
        panel.begin { response in
            guard response == .OK else { return }
            for url in panel.urls {
                let standardized = url.standardizedFileURL
                if !workspaceRoots.contains(where: { $0.path == standardized.path }) {
                    workspaceRoots.append(standardized)
                }
            }
        }
    }
}

private struct AgentPendingAttachmentChip: View {
    let media: AgentMediaReceipt
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: "photo")
                .font(.caption.weight(.semibold))
                .foregroundStyle(ControlDesign.brand)
            Text(displayName)
                .font(.caption.weight(.medium))
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: 180, alignment: .leading)
            Button(action: onRemove) {
                Image(systemName: "xmark.circle.fill")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(width: 18, height: 18)
            }
            .buttonStyle(.plain)
            .help("移除附件")
        }
        .padding(.horizontal, 9)
        .frame(height: 32)
        .background(ControlDesign.brand.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .stroke(ControlDesign.brand.opacity(0.18), lineWidth: 0.7)
        )
        .accessibilityElement(children: .combine)
    }

    private var displayName: String {
        let name = media.fileName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? "图片附件" : name
    }
}

private struct AgentSlashCommandPalette: View {
    let commands: [AgentComposerCommand]
    let onSelect: (AgentComposerCommand) -> Void

    var body: some View {
        VStack(spacing: 0) {
            ForEach(commands.prefix(6)) { command in
                Button {
                    onSelect(command)
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: command.symbol)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(ControlDesign.brand)
                            .frame(width: 22)
                        Text(command.command)
                            .font(.system(.caption, design: .monospaced).weight(.semibold))
                            .foregroundStyle(.primary)
                            .frame(width: 72, alignment: .leading)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(command.title)
                                .font(.caption.weight(.semibold))
                            Text(command.detail)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 8)
                    }
                    .padding(.horizontal, 11)
                    .frame(height: 42)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                if command.id != commands.prefix(6).last?.id {
                    Divider().padding(.leading, 115)
                }
            }
        }
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(ControlDesign.hairline, lineWidth: 0.7))
        .shadow(color: Color.black.opacity(0.10), radius: 9, y: 3)
    }
}

struct AgentComposerStateHost<Content: View>: View {
    @ObservedObject var state: AgentComposerState
    let content: (AgentComposerState) -> Content

    var body: some View {
        content(state)
    }
}

@MainActor
private final class AgentMediaBlockModel: ObservableObject {
    @Published private(set) var resource: AgentMediaResource?
    @Published private(set) var loading = false
    @Published private(set) var errorMessage = ""

    private var requestedKey = ""

    func load(sessionId: String, mediaId: String) async {
        let key = "\(sessionId):\(mediaId)"
        guard !sessionId.isEmpty, !mediaId.isEmpty else {
            resource = nil
            errorMessage = "附件标识无效"
            loading = false
            return
        }
        guard requestedKey != key || resource == nil else { return }
        requestedKey = key
        resource = nil
        errorMessage = ""
        loading = true
        do {
            let loaded = try await AgentMediaCache.shared.resource(
                sessionId: sessionId,
                mediaId: mediaId
            )
            guard requestedKey == key else { return }
            resource = loaded
        } catch is CancellationError {
            return
        } catch {
            guard requestedKey == key else { return }
            errorMessage = "附件暂时无法读取"
        }
        if requestedKey == key {
            loading = false
        }
    }
}

private struct AgentImageBlockView: View {
    let sessionId: String
    let block: AgentBlock
    var compact = false

    @StateObject private var model = AgentMediaBlockModel()
    @State private var showsPreview = false

    var body: some View {
        Group {
            if mediaId.isEmpty {
                AgentMediaFailureView(symbol: "photo", message: "图片附件无效", compact: compact)
            } else if let image = renderedImage {
                Button {
                    showsPreview = !compact
                } label: {
                    ZStack(alignment: .bottomLeading) {
                        Color.black.opacity(0.035)
                        Image(nsImage: image)
                            .resizable()
                            .scaledToFit()
                            .padding(compact ? 4 : 8)
                        if !compact {
                            Label("查看原图", systemImage: "arrow.up.left.and.arrow.down.right")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(.primary)
                                .padding(.horizontal, 8)
                                .frame(height: 25)
                                .background(.regularMaterial)
                                .clipShape(RoundedRectangle(cornerRadius: 5))
                                .padding(8)
                        }
                    }
                    .frame(width: frameSize.width, height: frameSize.height)
                    .clipShape(RoundedRectangle(cornerRadius: compact ? 7 : 8))
                    .overlay(
                        RoundedRectangle(cornerRadius: compact ? 7 : 8)
                            .stroke(ControlDesign.hairline, lineWidth: 0.7)
                    )
                }
                .buttonStyle(.plain)
                .help(compact ? "贴纸" : "打开图片预览")
                .sheet(isPresented: $showsPreview) {
                    AgentImageLightbox(image: image, title: displayName)
                }
            } else if !model.errorMessage.isEmpty {
                AgentMediaFailureView(symbol: "photo.badge.exclamationmark", message: model.errorMessage, compact: compact)
            } else {
                AgentMediaLoadingView(symbol: "photo", label: "正在读取图片", compact: compact)
            }
        }
        .task(id: cacheKey) {
            await model.load(sessionId: sessionId, mediaId: mediaId)
        }
    }

    private var mediaId: String {
        block.data.objectValue["mediaId"]?.stringValue ?? ""
    }

    private var cacheKey: String { "\(sessionId):\(mediaId)" }

    private var renderedImage: NSImage? {
        guard let data = model.resource?.data else { return nil }
        return NSImage(data: data)
    }

    private var frameSize: CGSize {
        compact ? CGSize(width: 132, height: 132) : CGSize(width: 380, height: 238)
    }

    private var displayName: String {
        let name = model.resource?.receipt.fileName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? "图片" : name
    }
}

private struct AgentImageLightbox: View {
    let image: NSImage
    let title: String

    @Environment(\.dismiss) private var dismiss
    @State private var settledScale: CGFloat = 1
    @GestureState private var gestureScale: CGFloat = 1

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color(nsColor: .windowBackgroundColor)
                .ignoresSafeArea()
            ScrollView([.horizontal, .vertical]) {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
                    .scaleEffect(effectiveScale)
                    .frame(minWidth: 600, minHeight: 430)
                    .padding(44)
            }
            .gesture(
                MagnificationGesture()
                    .updating($gestureScale) { value, state, _ in state = value }
                    .onEnded { value in
                        settledScale = min(max(settledScale * value, 0.5), 4)
                    }
            )

            HStack(spacing: 8) {
                Text(title)
                    .font(.caption.weight(.medium))
                    .lineLimit(1)
                    .frame(maxWidth: 260)
                Button {
                    settledScale = 1
                } label: {
                    Image(systemName: "arrow.counterclockwise")
                        .frame(width: 26, height: 26)
                }
                .buttonStyle(.borderless)
                .help("恢复缩放")
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark")
                        .frame(width: 26, height: 26)
                }
                .buttonStyle(.borderless)
                .help("关闭预览")
            }
            .padding(14)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .padding(14)
        }
        .frame(minWidth: 720, minHeight: 540)
    }

    private var effectiveScale: CGFloat {
        min(max(settledScale * gestureScale, 0.5), 4)
    }
}

@MainActor
private final class AgentAudioPlayerModel: ObservableObject {
    @Published private(set) var receipt: AgentMediaReceipt?
    @Published private(set) var loading = false
    @Published private(set) var playing = false
    @Published private(set) var currentTime: TimeInterval = 0
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var errorMessage = ""

    private var player: AVAudioPlayer?
    private var requestedKey = ""

    func load(sessionId: String, mediaId: String) async {
        let key = "\(sessionId):\(mediaId)"
        guard !sessionId.isEmpty, !mediaId.isEmpty else {
            errorMessage = "音频附件无效"
            return
        }
        guard requestedKey != key || player == nil else { return }
        requestedKey = key
        stop()
        receipt = nil
        errorMessage = ""
        loading = true
        do {
            let resource = try await AgentMediaCache.shared.resource(
                sessionId: sessionId,
                mediaId: mediaId
            )
            guard requestedKey == key else { return }
            let nextPlayer = try AVAudioPlayer(data: resource.data)
            nextPlayer.prepareToPlay()
            player = nextPlayer
            receipt = resource.receipt
            duration = nextPlayer.duration
        } catch is CancellationError {
            return
        } catch {
            guard requestedKey == key else { return }
            errorMessage = "音频暂时无法播放"
        }
        if requestedKey == key {
            loading = false
        }
    }

    func togglePlayback() {
        guard let player else { return }
        if player.isPlaying {
            player.pause()
        } else {
            if duration > 0, player.currentTime >= duration - 0.05 {
                player.currentTime = 0
            }
            player.play()
        }
        refresh()
    }

    func seek(to value: TimeInterval) {
        guard let player else { return }
        player.currentTime = min(max(value, 0), max(duration, 0))
        refresh()
    }

    func refresh() {
        guard let player else { return }
        currentTime = player.currentTime
        playing = player.isPlaying
    }

    func stop() {
        player?.stop()
        player = nil
        playing = false
        currentTime = 0
        duration = 0
    }
}

private struct AgentAudioBlockView: View {
    let sessionId: String
    let block: AgentBlock

    @StateObject private var model = AgentAudioPlayerModel()
    private let refreshTimer = Timer.publish(every: 0.2, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            if mediaId.isEmpty {
                AgentMediaFailureView(symbol: "waveform", message: "音频附件无效")
            } else if model.loading {
                AgentMediaLoadingView(symbol: "waveform", label: "正在读取音频")
            } else if !model.errorMessage.isEmpty {
                AgentMediaFailureView(symbol: "speaker.slash", message: model.errorMessage)
            } else {
                HStack(spacing: 11) {
                    Button {
                        model.togglePlayback()
                    } label: {
                        Image(systemName: model.playing ? "pause.fill" : "play.fill")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 30, height: 30)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(ControlDesign.brand)
                    .help(model.playing ? "暂停" : "播放")

                    VStack(alignment: .leading, spacing: 5) {
                        HStack {
                            Text(displayName)
                                .font(.caption.weight(.semibold))
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Spacer()
                            Text("\(durationText(model.currentTime)) / \(durationText(model.duration))")
                                .font(.caption2.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        Slider(
                            value: Binding(
                                get: { model.currentTime },
                                set: { model.seek(to: $0) }
                            ),
                            in: 0...max(model.duration, 0.01)
                        )
                        .controlSize(.small)
                    }
                }
                .padding(10)
                .frame(width: 380, height: 64)
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
            }
        }
        .task(id: cacheKey) {
            await model.load(sessionId: sessionId, mediaId: mediaId)
        }
        .onReceive(refreshTimer) { _ in model.refresh() }
        .onDisappear { model.stop() }
    }

    private var mediaId: String {
        block.data.objectValue["mediaId"]?.stringValue ?? ""
    }

    private var cacheKey: String { "\(sessionId):\(mediaId)" }

    private var displayName: String {
        let name = model.receipt?.fileName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? "语音附件" : name
    }

    private func durationText(_ value: TimeInterval) -> String {
        guard value.isFinite, value >= 0 else { return "0:00" }
        let seconds = Int(value.rounded(.down))
        return "\(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }
}

private struct AgentFileBlockView: View {
    let sessionId: String
    let block: AgentBlock

    @StateObject private var model = AgentMediaBlockModel()
    @State private var previewError = ""

    var body: some View {
        Group {
            if mediaId.isEmpty {
                AgentMediaFailureView(symbol: "doc", message: "文件附件无效")
            } else if let resource = model.resource {
                HStack(spacing: 11) {
                    Image(systemName: fileSymbol(resource.receipt.mimeType))
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(ControlDesign.brand)
                        .frame(width: 34, height: 34)
                        .background(ControlDesign.brand.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(displayName(resource.receipt))
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Text(fileDetail(resource.receipt))
                            .font(.caption2)
                            .foregroundStyle(previewError.isEmpty ? Color.secondary : Color.orange)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Button {
                        Task { await preview() }
                    } label: {
                        Image(systemName: "eye")
                            .frame(width: 26, height: 26)
                    }
                    .buttonStyle(.borderless)
                    .help("快速预览")
                }
                .padding(10)
                .frame(width: 380, height: 60)
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
            } else if !model.errorMessage.isEmpty {
                AgentMediaFailureView(symbol: "doc.badge.ellipsis", message: model.errorMessage)
            } else {
                AgentMediaLoadingView(symbol: "doc", label: "正在读取文件")
            }
        }
        .task(id: cacheKey) {
            await model.load(sessionId: sessionId, mediaId: mediaId)
        }
    }

    private var mediaId: String {
        block.data.objectValue["mediaId"]?.stringValue ?? ""
    }

    private var cacheKey: String { "\(sessionId):\(mediaId)" }

    @MainActor
    private func preview() async {
        previewError = ""
        do {
            let url = try await AgentMediaCache.shared.materializedURL(
                sessionId: sessionId,
                mediaId: mediaId
            )
            AgentQuickLookPresenter.shared.present(url)
        } catch {
            previewError = "暂时无法预览"
        }
    }

    private func displayName(_ receipt: AgentMediaReceipt) -> String {
        let name = receipt.fileName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? "文件附件" : name
    }

    private func fileDetail(_ receipt: AgentMediaReceipt) -> String {
        if !previewError.isEmpty { return previewError }
        return ByteCountFormatter.string(fromByteCount: Int64(receipt.byteSize), countStyle: .file)
    }

    private func fileSymbol(_ mimeType: String) -> String {
        switch mimeType {
        case "application/pdf": return "doc.richtext"
        case "text/plain": return "doc.plaintext"
        default: return "doc"
        }
    }
}

@MainActor
private final class AgentQuickLookPresenter: NSObject, @preconcurrency QLPreviewPanelDataSource {
    static let shared = AgentQuickLookPresenter()

    private var previewURL: URL?

    func present(_ url: URL) {
        previewURL = url
        guard let panel = QLPreviewPanel.shared() else { return }
        panel.dataSource = self
        panel.reloadData()
        panel.currentPreviewItemIndex = 0
        panel.makeKeyAndOrderFront(nil)
    }

    func numberOfPreviewItems(in panel: QLPreviewPanel!) -> Int {
        previewURL == nil ? 0 : 1
    }

    func previewPanel(_ panel: QLPreviewPanel!, previewItemAt index: Int) -> QLPreviewItem! {
        guard index == 0, let previewURL else { return nil }
        return previewURL as NSURL
    }
}

private struct AgentStickerBlockView: View {
    let sessionId: String
    let block: AgentBlock

    var body: some View {
        if !mediaId.isEmpty {
            AgentImageBlockView(sessionId: sessionId, block: block, compact: true)
        } else if let image = bundledImage {
            Image(nsImage: image)
                .resizable()
                .scaledToFit()
                .frame(width: 132, height: 132)
                .padding(4)
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.7))
                .clipShape(RoundedRectangle(cornerRadius: 7))
                .accessibilityLabel("智鼬贴纸")
        } else {
            AgentMediaFailureView(symbol: "face.smiling", message: "贴纸暂不可用", compact: true)
        }
    }

    private var mediaId: String {
        block.data.objectValue["mediaId"]?.stringValue ?? ""
    }

    private var bundledImage: NSImage? {
        let assetId = block.data.objectValue["assetId"]?.stringValue ?? ""
        guard !assetId.isEmpty,
              assetId.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil,
              let url = Bundle.main.url(forResource: assetId, withExtension: "png")
        else {
            return nil
        }
        return NSImage(contentsOf: url)
    }
}

private struct AgentMediaLoadingView: View {
    let symbol: String
    let label: String
    var compact = false

    var body: some View {
        HStack(spacing: 9) {
            ProgressView().controlSize(.small)
            Label(label, systemImage: symbol)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .frame(width: compact ? 132 : 380, height: compact ? 132 : 60)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.72))
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.7))
    }
}

private struct AgentMediaFailureView: View {
    let symbol: String
    let message: String
    var compact = false

    var body: some View {
        Label(message, systemImage: symbol)
            .font(.caption.weight(.medium))
            .foregroundStyle(.orange)
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .frame(width: compact ? 132 : 380, height: compact ? 132 : 60)
            .background(Color.orange.opacity(0.045))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color.orange.opacity(0.20), lineWidth: 0.7))
    }
}
