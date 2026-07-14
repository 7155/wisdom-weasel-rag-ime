import Foundation

struct AgentRoomMessageEntry: Equatable, Identifiable {
    let participantId: String?
    var message: AgentMessage

    var id: String {
        participantId.map { "\($0):\(message.id)" } ?? "user:\(message.id)"
    }
}

struct AgentRoomConversationState: Equatable {
    var messages: [AgentRoomMessageEntry] = []
    var activity: [AgentActivityItem] = []
    var status = "idle"
    var activeParticipantId: String?
    var lastEventId = ""
    var lastSequence = 0
    var failureMessage = ""
}

enum AgentRoomConversationReduction: Equatable {
    case applied
    case ignored
    case reloadFromBeginning
}

enum AgentRoomConversationReducer {
    static func reduce(
        state: inout AgentRoomConversationState,
        event: AgentRoomEventEnvelope,
        participantName: String
    ) -> AgentRoomConversationReduction {
        if event.sequence <= state.lastSequence { return .ignored }
        if state.lastSequence > 0, event.sequence != state.lastSequence + 1 {
            state.status = "reconnecting"
            return .reloadFromBeginning
        }
        state.lastSequence = event.sequence
        state.lastEventId = event.resumeToken

        let payload = event.payload.objectValue
        switch event.eventType {
        case .userMessage:
            applyUserMessage(state: &state, event: event, payload: payload)
        case .routeDecision:
            let targetName = payload["targetDisplayName"]?.stringValue ?? participantName
            state.activeParticipantId = event.participantId
            state.status = "routing"
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):route",
                    title: "已交给\(targetName)",
                    detail: "单路发言，其他角色保持待命",
                    state: .running,
                    createdAtMs: event.createdAtMs
                )
            )
        case .participantStatus:
            let status = payload["status"]?.stringValue ?? ""
            if status == "room_archived" { state.status = "archived" }
            if status == "room_restored" { state.status = "idle" }
        case .participantDelta:
            applyParticipantDelta(
                state: &state,
                event: event,
                data: payload["data"]?.objectValue ?? [:]
            )
        case .participantActivity:
            applyParticipantActivity(
                state: &state,
                event: event,
                participantName: participantName,
                payload: payload
            )
        case .participantMessage:
            applyParticipantMessage(state: &state, event: event, payload: payload)
        case .turnCompleted:
            completeRunningActivity(state: &state)
            state.status = "idle"
            state.activeParticipantId = nil
            state.failureMessage = ""
        case .turnFailed:
            let error = clipped(payload["error"]?.stringValue ?? "本轮没有完成")
            completeRunningActivity(state: &state, failed: true)
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):failed",
                    title: "\(participantName)没有完成这轮",
                    detail: error,
                    state: .failed,
                    createdAtMs: event.createdAtMs
                )
            )
            state.status = "failed"
            state.activeParticipantId = nil
            state.failureMessage = error
        case .snapshotRequired:
            state.status = "reconnecting"
            state.failureMessage = "群聊事件需要重新同步"
            return .reloadFromBeginning
        case .unknown:
            break
        }
        return .applied
    }

    @discardableResult
    static func appendOptimisticUser(
        state: inout AgentRoomConversationState,
        roomId: String,
        text: String,
        nowMs: Int
    ) -> String {
        let id = "local:\(UUID().uuidString)"
        state.messages.append(
            AgentRoomMessageEntry(
                participantId: nil,
                message: textMessage(
                    id: id,
                    sessionId: roomId,
                    turnId: id,
                    role: "user",
                    text: text,
                    status: "queued",
                    createdAtMs: nowMs
                )
            )
        )
        state.activity = [
            AgentActivityItem(
                id: "\(id):route",
                title: "正在选择发言者…",
                detail: "解析 @角色与房间路由策略",
                state: .running,
                createdAtMs: nowMs
            )
        ]
        state.status = "routing"
        state.failureMessage = ""
        return id
    }

    static func markOptimisticFailure(
        state: inout AgentRoomConversationState,
        messageId: String,
        error: String
    ) {
        guard let index = state.messages.firstIndex(where: { $0.message.id == messageId }) else { return }
        let old = state.messages[index]
        state.messages[index] = AgentRoomMessageEntry(
            participantId: old.participantId,
            message: replacingStatus(old.message, status: "failed")
        )
        completeRunningActivity(state: &state, failed: true)
        state.status = "failed"
        state.failureMessage = clipped(error)
    }

    private static func applyUserMessage(
        state: inout AgentRoomConversationState,
        event: AgentRoomEventEnvelope,
        payload: [String: JSONValue]
    ) {
        let text = payload["text"]?.stringValue ?? ""
        guard !text.isEmpty else { return }
        if let optimistic = state.messages.lastIndex(where: {
            $0.message.role == "user"
                && $0.message.status == "queued"
                && messageText($0.message) == text
        }) {
            state.messages.remove(at: optimistic)
        }
        state.messages.append(
            AgentRoomMessageEntry(
                participantId: nil,
                message: textMessage(
                    id: event.eventId,
                    sessionId: event.roomId,
                    turnId: event.turnId,
                    role: "user",
                    text: text,
                    status: "completed",
                    createdAtMs: event.createdAtMs
                )
            )
        )
        state.activity = []
        state.status = "routing"
        state.failureMessage = ""
    }

    private static func applyParticipantDelta(
        state: inout AgentRoomConversationState,
        event: AgentRoomEventEnvelope,
        data: [String: JSONValue]
    ) {
        guard let participantId = event.participantId else { return }
        let sourceMessageId = data["messageId"]?.stringValue ?? "\(event.turnId):assistant"
        let messageId = "room:\(participantId):\(sourceMessageId)"
        let blockId = data["blockId"]?.stringValue ?? "\(messageId):text"
        let delta = data["delta"]?.stringValue ?? ""
        guard !delta.isEmpty else { return }

        if let index = state.messages.firstIndex(where: { $0.message.id == messageId }) {
            let old = state.messages[index]
            var blocks = old.message.blocks
            if let blockIndex = blocks.firstIndex(where: { $0.id == blockId || $0.type == .text }) {
                let text = blocks[blockIndex].data.objectValue["text"]?.stringValue ?? ""
                blocks[blockIndex] = textBlock(id: blocks[blockIndex].id, text: text + delta, status: "running")
            } else {
                blocks.append(textBlock(id: blockId, text: delta, status: "running"))
            }
            state.messages[index] = AgentRoomMessageEntry(
                participantId: participantId,
                message: replacingBlocks(old.message, blocks: blocks, status: "streaming")
            )
        } else {
            state.messages.append(
                AgentRoomMessageEntry(
                    participantId: participantId,
                    message: AgentMessage(
                        schemaVersion: "rag-ime.agent-message.v1",
                        id: messageId,
                        sessionId: event.sourceSessionId,
                        turnId: event.turnId,
                        role: "assistant",
                        status: "streaming",
                        blocks: [textBlock(id: blockId, text: delta, status: "running")],
                        attachments: [],
                        citations: [],
                        createdAtMs: event.createdAtMs,
                        completedAtMs: nil
                    )
                )
            )
        }
        state.activeParticipantId = participantId
        state.status = "responding"
    }

    private static func applyParticipantActivity(
        state: inout AgentRoomConversationState,
        event: AgentRoomEventEnvelope,
        participantName: String,
        payload: [String: JSONValue]
    ) {
        let sourceType = payload["sourceEventType"]?.stringValue ?? ""
        let data = payload["data"]?.objectValue ?? [:]
        state.activeParticipantId = event.participantId

        switch sourceType {
        case "status_changed":
            let status = data["status"]?.stringValue ?? "working"
            state.status = status
            let title = switch status {
            case "busy": "\(participantName)正在理解问题…"
            case "analyzing": "\(participantName)正在整理检索线索…"
            case "working": "\(participantName)正在翻工具书…"
            case "responding": "\(participantName)正在组织回答…"
            case "finishing": "\(participantName)正在收尾…"
            default: "\(participantName)正在处理…"
            }
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):presence",
                    title: title,
                    detail: activityDetail(status: status),
                    state: ["idle", "ready", "stopped"].contains(status) ? .completed : .running,
                    createdAtMs: event.createdAtMs
                )
            )
        case "tool_started", "tool_progress", "tool_finished":
            let toolName = data["toolName"]?.stringValue
                ?? data["displayName"]?.stringValue
                ?? data["label"]?.stringValue
                ?? "受控工具"
            let callId = data["callId"]?.stringValue ?? data["toolCallId"]?.stringValue ?? toolName
            let finished = sourceType == "tool_finished"
            let failed = data["status"]?.stringValue == "failed" || data["ok"]?.boolValue == false
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):tool:\(callId)",
                    title: finished ? "\(participantName)已完成\(toolName)" : "\(participantName)正在使用\(toolName)…",
                    detail: clipped(
                        data["summary"]?.stringValue
                            ?? data["message"]?.stringValue
                            ?? "只展示可核对的工具活动摘要"
                    ),
                    state: failed ? .failed : finished ? .completed : .running,
                    createdAtMs: event.createdAtMs,
                    references: activityReferences(data)
                )
            )
            state.status = finished ? "working" : "working"
        case "reasoning_summary":
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):summary",
                    title: "\(participantName)已整理分析摘要",
                    detail: clipped(data["summary"]?.stringValue ?? data["text"]?.stringValue ?? ""),
                    state: .completed,
                    createdAtMs: event.createdAtMs
                )
            )
        case "approval_required":
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):approval",
                    title: "\(participantName)在等待你的确认",
                    detail: clipped(data["summary"]?.stringValue ?? "有一项写操作需要原生审批"),
                    state: .waiting,
                    createdAtMs: event.createdAtMs
                )
            )
            state.status = "waiting"
        default:
            break
        }
    }

    private static func applyParticipantMessage(
        state: inout AgentRoomConversationState,
        event: AgentRoomEventEnvelope,
        payload: [String: JSONValue]
    ) {
        guard let participantId = event.participantId,
              let value = payload["data"]?.objectValue["message"],
              let message: AgentMessage = decode(value),
              message.role != "user" else { return }

        let entry = AgentRoomMessageEntry(participantId: participantId, message: message)
        if let index = state.messages.firstIndex(where: {
            $0.participantId == participantId
                && ($0.message.id == message.id || $0.message.turnId == message.turnId)
        }) {
            state.messages[index] = entry
        } else {
            state.messages.append(entry)
        }
        completeRunningActivity(state: &state)
        state.status = message.status == "failed" ? "failed" : "finishing"
    }

    private static func activityDetail(status: String) -> String {
        switch status {
        case "analyzing": return "选择需要查询的工具书、近期对话与知识"
        case "working": return "正在核对可引用的本地证据"
        case "responding": return "证据已就绪，正在生成可见回答"
        default: return "房间只允许一位角色在本轮发言"
        }
    }

    private static func activityReferences(_ data: [String: JSONValue]) -> [AgentActivityReference] {
        var values: [AgentActivityReference] = []
        for (key, kind) in [
            ("books", AgentActivityReference.Kind.book),
            ("groups", .group),
            ("tags", .tag),
            ("recent", .recent),
        ] {
            guard case let .array(items)? = data[key] else { continue }
            values.append(contentsOf: items.compactMap { item in
                let label = item.stringValue
                guard !label.isEmpty else { return nil }
                return AgentActivityReference(kind: kind, label: String(label.prefix(80)))
            })
        }
        return Array(values.prefix(8))
    }

    private static func upsertActivity(state: inout AgentRoomConversationState, item: AgentActivityItem) {
        if let index = state.activity.firstIndex(where: { $0.id == item.id }) {
            state.activity[index] = item
        } else {
            state.activity.append(item)
        }
        if state.activity.count > 12 {
            state.activity.removeFirst(state.activity.count - 12)
        }
    }

    private static func completeRunningActivity(
        state: inout AgentRoomConversationState,
        failed: Bool = false
    ) {
        for index in state.activity.indices where state.activity[index].state == .running {
            state.activity[index].state = failed ? .failed : .completed
        }
    }

    private static func textMessage(
        id: String,
        sessionId: String,
        turnId: String,
        role: String,
        text: String,
        status: String,
        createdAtMs: Int
    ) -> AgentMessage {
        AgentMessage(
            schemaVersion: "rag-ime.agent-message.v1",
            id: id,
            sessionId: sessionId,
            turnId: turnId,
            role: role,
            status: status,
            blocks: [textBlock(id: "\(id):text", text: text, status: status)],
            attachments: [],
            citations: [],
            createdAtMs: createdAtMs,
            completedAtMs: status == "completed" ? createdAtMs : nil
        )
    }

    private static func textBlock(id: String, text: String, status: String) -> AgentBlock {
        AgentBlock(
            id: id,
            type: .text,
            status: status,
            presentationKind: status == "running" ? "markdown" : "plain_text",
            data: .object(["text": .string(text)])
        )
    }

    private static func replacingBlocks(
        _ message: AgentMessage,
        blocks: [AgentBlock],
        status: String
    ) -> AgentMessage {
        AgentMessage(
            schemaVersion: message.schemaVersion,
            id: message.id,
            sessionId: message.sessionId,
            turnId: message.turnId,
            role: message.role,
            status: status,
            blocks: blocks,
            attachments: message.attachments,
            citations: message.citations,
            createdAtMs: message.createdAtMs,
            completedAtMs: message.completedAtMs
        )
    }

    private static func replacingStatus(_ message: AgentMessage, status: String) -> AgentMessage {
        replacingBlocks(message, blocks: message.blocks, status: status)
    }

    private static func messageText(_ message: AgentMessage) -> String {
        message.blocks.compactMap { block in
            block.type == .text ? block.data.objectValue["text"]?.stringValue : nil
        }.joined()
    }

    private static func decode<T: Decodable>(_ value: JSONValue) -> T? {
        guard let data = try? JSONEncoder().encode(value) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    private static func clipped(_ text: String) -> String {
        let compact = text.split(whereSeparator: \Character.isWhitespace).joined(separator: " ")
        return String(compact.prefix(220))
    }
}

@MainActor
final class AgentRoomWorkspaceStore: ObservableObject {
    @Published private(set) var runtime: AgentRuntimeStatus?
    @Published private(set) var rooms: [AgentRoomSummary] = []
    @Published private(set) var roleCatalog: [AgentRoleSummary] = []
    @Published var selectedRoomId = ""
    @Published var conversation = AgentRoomConversationState()
    @Published var loading = false
    @Published var sending = false
    @Published var showArchived = false
    @Published var errorMessage = ""

    let composerState = AgentComposerState()

    private let api: AgentAPIClient
    private var streamTask: Task<Void, Never>?
    private var deltaFlushTask: Task<Void, Never>?
    private var bufferedDeltaEvents: [AgentRoomEventEnvelope] = []
    private var activated = false
    private let deltaFlushNanoseconds: UInt64 = 16_666_667

    init(api: AgentAPIClient = AgentAPIClient()) {
        self.api = api
    }

    var selectedRoom: AgentRoomSummary? {
        rooms.first(where: { $0.id == selectedRoomId })
    }

    var draft: String {
        get { composerState.draft }
        set { composerState.draft = newValue }
    }

    var canUseRuntime: Bool {
        guard let runtime else { return false }
        let capabilities = runtime.capabilities.objectValue
        return runtime.enabled
            && capabilities["rpc"]?.boolValue == true
            && capabilities["modelConfigured"]?.boolValue != false
    }

    var isRoomBusy: Bool {
        ["routing", "busy", "analyzing", "working", "responding", "finishing", "waiting"]
            .contains(conversation.status)
    }

    var canSend: Bool {
        let hasText = !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return canUseRuntime
            && selectedRoom?.status == "active"
            && hasText
            && canRouteDraft
            && !sending
            && !isRoomBusy
    }

    var canRouteDraft: Bool {
        guard let room = selectedRoom else { return false }
        if room.routingPolicy == "moderator" { return true }
        let lowered = draft.lowercased()
        let matches = room.participants.filter { participant in
            lowered.contains("@\(participant.displayName.lowercased())")
                || lowered.contains("@\(participant.roleId.lowercased())")
        }
        return matches.count == 1
    }

    func persona(for participant: AgentRoomParticipant) -> AgentRoleSummary {
        roleCatalog.first(where: {
            $0.roleId == participant.roleId && $0.version == participant.roleVersion
        }) ?? AgentRoleSummary(
            schemaVersion: nil,
            roleId: participant.roleId,
            version: participant.roleVersion,
            displayName: participant.displayName,
            tagline: "已保存的角色版本",
            summary: nil,
            traits: nil,
            visualProfile: nil,
            defaults: nil,
            safetyPolicyVersion: nil,
            selectableModes: ["assistant"]
        )
    }

    func activate() async {
        loading = true
        defer { loading = false }
        do {
            async let runtimeRequest = api.runtimeStatus()
            async let roomRequest = api.rooms(includeArchived: showArchived)
            async let roleRequest = api.roles()
            let (runtime, response, roles) = try await (runtimeRequest, roomRequest, roleRequest)
            self.runtime = runtime
            rooms = response.items
            roleCatalog = roles.items
            if selectedRoomId.isEmpty || !rooms.contains(where: { $0.id == selectedRoomId }) {
                selectedRoomId = rooms.first?.id ?? ""
                conversation = AgentRoomConversationState()
            }
            activated = true
            errorMessage = ""
            if canUseRuntime, !selectedRoomId.isEmpty {
                startStream(roomId: selectedRoomId, fromBeginning: conversation.lastEventId.isEmpty)
            } else {
                suspendStream()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadPersonaCatalog() async {
        guard roleCatalog.isEmpty else { return }
        do {
            roleCatalog = try await api.roles().items
            errorMessage = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reloadRooms() async {
        do {
            let response = try await api.rooms(includeArchived: showArchived)
            rooms = response.items
            if !selectedRoomId.isEmpty, !rooms.contains(where: { $0.id == selectedRoomId }) {
                suspendStream()
                selectedRoomId = rooms.first?.id ?? ""
                conversation = AgentRoomConversationState()
                if canUseRuntime, !selectedRoomId.isEmpty {
                    startStream(roomId: selectedRoomId, fromBeginning: true)
                }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @discardableResult
    func createRoom(
        title: String,
        roles: [AgentRoleSummary],
        routingPolicy: String,
        moderatorRoleId: String
    ) async -> Bool {
        do {
            let response = try await api.createRoom(
                title: title,
                participants: roles,
                routingPolicy: routingPolicy,
                moderatorRoleId: moderatorRoleId
            )
            await reloadRooms()
            selectRoomInteractively(response.room.id)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func selectRoomInteractively(_ id: String) {
        guard id != selectedRoomId || !activated else { return }
        suspendStream()
        selectedRoomId = id
        conversation = AgentRoomConversationState()
        errorMessage = ""
        guard canUseRuntime, !id.isEmpty else { return }
        startStream(roomId: id, fromBeginning: true)
    }

    func archiveSelected(_ archived: Bool) async {
        guard !selectedRoomId.isEmpty else { return }
        do {
            _ = try await api.updateRoom(id: selectedRoomId, archived: archived)
            suspendStream()
            selectedRoomId = ""
            conversation = AgentRoomConversationState()
            await reloadRooms()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func insertMention(_ participant: AgentRoomParticipant) {
        let mention = "@\(participant.displayName) "
        if draft.isEmpty {
            draft = mention
        } else if !draft.localizedCaseInsensitiveContains("@\(participant.displayName)") {
            draft = draft.hasSuffix(" ") ? draft + mention : draft + " " + mention
        }
    }

    func appendPaths(_ paths: [String]) {
        let clean = paths.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        guard !clean.isEmpty else { return }
        let value = clean.joined(separator: " ")
        draft = draft.isEmpty || draft.hasSuffix(" ") ? draft + value : draft + " " + value
    }

    func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canSend, let room = selectedRoom, !text.isEmpty else { return }
        sending = true
        draft = ""
        let localId = AgentRoomConversationReducer.appendOptimisticUser(
            state: &conversation,
            roomId: room.id,
            text: text,
            nowMs: Int(Date().timeIntervalSince1970 * 1_000)
        )
        do {
            _ = try await api.postRoomMessage(id: room.id, message: text)
            errorMessage = ""
        } catch {
            draft = text
            AgentRoomConversationReducer.markOptimisticFailure(
                state: &conversation,
                messageId: localId,
                error: error.localizedDescription
            )
            errorMessage = error.localizedDescription
        }
        sending = false
    }

    func suspendStream() {
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        _ = flushBufferedDeltas()
        streamTask?.cancel()
        streamTask = nil
    }

    func stop() {
        suspendStream()
        Task { await api.invalidate() }
    }

    private func startStream(roomId: String, fromBeginning: Bool) {
        suspendStream()
        if fromBeginning {
            conversation = AgentRoomConversationState()
            bufferedDeltaEvents.removeAll(keepingCapacity: true)
        }
        streamTask = Task { [weak self] in
            var firstConnection = true
            while !Task.isCancelled {
                guard let self, self.selectedRoomId == roomId else { return }
                let cursor = firstConnection && fromBeginning ? "" : self.conversation.lastEventId
                let startedFromBeginning = cursor.isEmpty
                firstConnection = false
                do {
                    try await self.api.streamRoomEvents(
                        roomId: roomId,
                        afterEventId: cursor
                    ) { [weak self] event in
                        guard let self else { return }
                        await self.receive(
                            event,
                            expectedRoomId: roomId,
                            startedFromBeginning: startedFromBeginning
                        )
                    }
                } catch is CancellationError {
                    return
                } catch {
                    guard !Task.isCancelled else { return }
                    self.errorMessage = error.localizedDescription
                    try? await Task.sleep(for: .seconds(1))
                }
            }
        }
    }

    private func receive(
        _ event: AgentRoomEventEnvelope,
        expectedRoomId: String,
        startedFromBeginning: Bool
    ) async {
        guard selectedRoomId == expectedRoomId, event.roomId == expectedRoomId else { return }
        if event.eventType == .participantDelta {
            bufferedDeltaEvents.append(event)
            scheduleDeltaFlush(roomId: expectedRoomId)
            return
        }
        let buffered = flushBufferedDeltas()
        if buffered == .reloadFromBeginning {
            if !startedFromBeginning {
                startStream(roomId: expectedRoomId, fromBeginning: true)
            }
            return
        }
        let result = reduce(event)
        if event.eventType == .turnCompleted || event.eventType == .turnFailed {
            await reloadRooms()
            runtime = try? await api.runtimeStatus()
        }
        if result == .reloadFromBeginning {
            if startedFromBeginning {
                errorMessage = "群聊历史存在保留窗口缺口；已展示当前可恢复事件"
                return
            }
            conversation = AgentRoomConversationState()
            startStream(roomId: expectedRoomId, fromBeginning: true)
        }
    }

    private func scheduleDeltaFlush(roomId: String) {
        guard deltaFlushTask == nil else { return }
        deltaFlushTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: self?.deltaFlushNanoseconds ?? 16_666_667)
            } catch {
                return
            }
            guard let self, self.selectedRoomId == roomId else { return }
            self.deltaFlushTask = nil
            let result = self.flushBufferedDeltas()
            if result == .reloadFromBeginning {
                self.startStream(roomId: roomId, fromBeginning: true)
            }
        }
    }

    @discardableResult
    private func flushBufferedDeltas() -> AgentRoomConversationReduction {
        guard !bufferedDeltaEvents.isEmpty else { return .ignored }
        let events = bufferedDeltaEvents
        bufferedDeltaEvents.removeAll(keepingCapacity: true)
        var next = conversation
        var result: AgentRoomConversationReduction = .ignored
        for event in events {
            let participantName = participantName(for: event.participantId)
            let reduction = AgentRoomConversationReducer.reduce(
                state: &next,
                event: event,
                participantName: participantName
            )
            if reduction == .reloadFromBeginning {
                result = .reloadFromBeginning
                break
            }
            if reduction == .applied { result = .applied }
        }
        if result != .ignored { conversation = next }
        return result
    }

    private func reduce(_ event: AgentRoomEventEnvelope) -> AgentRoomConversationReduction {
        AgentRoomConversationReducer.reduce(
            state: &conversation,
            event: event,
            participantName: participantName(for: event.participantId)
        )
    }

    private func participantName(for id: String?) -> String {
        guard let id else { return "Agent" }
        return selectedRoom?.participants.first(where: { $0.id == id })?.displayName ?? "Agent"
    }
}
