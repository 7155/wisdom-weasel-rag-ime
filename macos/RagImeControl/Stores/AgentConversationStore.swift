import Foundation

struct AgentActivityReference: Equatable, Identifiable {
    enum Kind: String, Equatable {
        case book
        case group
        case tag
        case recent
        case source
    }

    let kind: Kind
    let label: String

    var id: String { "\(kind.rawValue):\(label)" }
}

struct AgentActivityItem: Equatable, Identifiable {
    enum State: String, Equatable {
        case running
        case completed
        case failed
        case waiting
    }

    let id: String
    var title: String
    var detail: String
    var state: State
    let createdAtMs: Int
    var turnId: String = ""
    var references: [AgentActivityReference] = []
}

struct AgentConversationState: Equatable {
    var messages: [AgentMessage] = []
    var activity: [AgentActivityItem] = []
    var status = "idle"
    var lastEventId = ""
    var lastSequence = 0
    var needsSnapshot = false
    var failureMessage = ""
}

enum AgentConversationReduction: Equatable {
    case applied
    case ignored
    case reloadSnapshot
}

enum AgentConversationReducer {
    static func reduce(
        state: inout AgentConversationState,
        event: AgentEventEnvelope
    ) -> AgentConversationReduction {
        if event.sequence <= state.lastSequence {
            return .ignored
        }
        if state.lastSequence > 0, event.sequence != state.lastSequence + 1 {
            state.lastSequence = event.sequence
            state.lastEventId = event.resumeToken
            state.needsSnapshot = true
            return .reloadSnapshot
        }
        state.lastSequence = event.sequence
        state.lastEventId = event.resumeToken

        let payload = event.payload.objectValue
        switch event.eventType {
        case .textDelta:
            applyTextDelta(state: &state, event: event, payload: payload)
        case .reasoningSummary:
            let summary = payload["summary"]?.stringValue ?? payload["text"]?.stringValue ?? ""
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):reasoning-summary",
                    title: "分析摘要",
                    detail: clipped(summary),
                    state: .completed,
                    createdAtMs: event.createdAtMs
                )
            )
        case .statusChanged:
            applyStatus(state: &state, event: event, payload: payload)
        case .toolStarted, .toolProgress, .toolFinished:
            applyToolEvent(state: &state, event: event, payload: payload)
        case .approvalRequired:
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: payload["approvalId"]?.stringValue ?? "\(event.turnId):approval",
                    title: "等待确认",
                    detail: clipped(payload["summary"]?.stringValue ?? "有一项操作需要你确认"),
                    state: .waiting,
                    createdAtMs: event.createdAtMs
                )
            )
            state.status = "waiting"
        case .approvalResolved:
            let approvalId = payload["approvalId"]?.stringValue ?? ""
            let approvalState = payload["state"]?.stringValue ?? "rejected"
            let externalPending = approvalState == "external_pending"
            let externalFinalized = payload["externalFinalized"]?.boolValue == true
            let applied = approvalState == "applied" || approvalState == "approved"
            if let index = state.activity.firstIndex(where: { $0.id == approvalId }) {
                state.activity[index].title = externalPending
                    ? "已批准，等待外部执行"
                    : applied
                    ? "操作已应用"
                    : resolutionTitle(approvalState)
                state.activity[index].detail = externalPending
                    ? "Pi 先完成当前回答，随后由原生监督器执行"
                    : applied
                    ? (payload["summary"]?.stringValue ?? "变更已记录回执，Pi 将继续当前任务")
                    : resolutionDetail(approvalState)
                state.activity[index].state = externalPending ? .waiting : applied ? .completed : .failed
            }
            state.status = externalFinalized ? "idle" : (applied || externalPending) ? "working" : "responding"
        case .memoryCheckpointed:
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "\(event.turnId):memory:\(payload["sourceRole"]?.stringValue ?? "source")",
                    title: "已保存记忆来源",
                    detail: clipped(
                        payload["summary"]?.stringValue
                            ?? "最终内容已进入本地检查点，等待异步整理"
                    ),
                    state: .completed,
                    createdAtMs: event.createdAtMs
                )
            )
        case .memoryMaintenanceUpdated:
            let due = payload["due"]?.boolValue == true
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: "memory-maintenance:\(payload["trigger"]?.stringValue ?? "lifecycle")",
                    title: due ? "记忆整理已就绪" : "已检查记忆整理状态",
                    detail: clipped(
                        payload["summary"]?.stringValue
                            ?? "已在会话生命周期检查长期记忆整理条件"
                    ),
                    state: .completed,
                    createdAtMs: event.createdAtMs
                )
            )
        case .userInputRequired:
            upsertActivity(
                state: &state,
                item: AgentActivityItem(
                    id: payload["requestId"]?.stringValue ?? "\(event.turnId):input",
                    title: "等待补充信息",
                    detail: clipped(payload["message"]?.stringValue ?? "需要更多信息才能继续"),
                    state: .waiting,
                    createdAtMs: event.createdAtMs
                )
            )
            state.status = "waiting"
        case .messageCompleted:
            if let message: AgentMessage = decode(payload["message"]) {
                upsertMessage(state: &state, message: message)
                if message.role == "assistant" {
                    if message.status == "failed" || message.blocks.contains(where: { $0.type == .error }) {
                        let error = message.blocks.first(where: { $0.type == .error })?
                            .data.objectValue["message"]?.stringValue ?? "模型请求失败，请重试"
                        replacePendingWithFailure(
                            state: &state,
                            title: "模型请求失败",
                            detail: error
                        )
                        completeRunningActivity(state: &state, failed: true)
                        state.status = "failed"
                        state.failureMessage = error
                    } else {
                        completeRunningActivity(state: &state)
                        state.status = "finishing"
                    }
                }
            }
        case .turnCompleted:
            completeRunningActivity(state: &state)
            completeQueuedUserMessages(state: &state)
            state.status = "idle"
            state.failureMessage = ""
        case .turnFailed:
            let error = clipped(payload["error"]?.stringValue ?? "本轮没有完成")
            completeRunningActivity(state: &state, failed: true)
            if !replacePendingWithFailure(
                state: &state,
                title: "本轮没有完成",
                detail: error
            ) {
                upsertActivity(
                    state: &state,
                    item: AgentActivityItem(
                        id: "\(event.turnId):failure",
                        title: "本轮没有完成",
                        detail: error,
                        state: .failed,
                        createdAtMs: event.createdAtMs,
                        turnId: event.turnId
                    )
                )
            }
            state.status = "failed"
            state.failureMessage = error
        case .snapshotRequired:
            state.needsSnapshot = true
            return .reloadSnapshot
        case .snapshot, .heartbeat, .unknown:
            break
        }
        return .applied
    }

    static func replaceMessages(
        state: inout AgentConversationState,
        messages: [AgentMessage],
        lastSequence: Int? = nil,
        resumeToken: String? = nil
    ) {
        state.messages = deduplicated(messages)
        if let lastSequence {
            state.lastSequence = max(0, lastSequence)
            state.lastEventId = resumeToken ?? ""
        }
        state.needsSnapshot = false
    }

    static func appendOptimisticUser(
        state: inout AgentConversationState,
        sessionId: String,
        text: String,
        attachments: [AgentMediaReceipt] = [],
        nowMs: Int
    ) -> String {
        let id = "local:\(UUID().uuidString)"
        var blocks = [
            AgentBlock(
                id: "\(id):text",
                type: .text,
                status: "completed",
                presentationKind: "plain_text",
                data: .object(["text": .string(text)])
            )
        ]
        blocks.append(contentsOf: attachments.enumerated().map { index, media in
            AgentBlock(
                id: "\(id):image:\(index)",
                type: .image,
                status: "completed",
                presentationKind: "image",
                data: .object([
                    "mediaId": .string(media.mediaId),
                    "fileName": .string(media.fileName ?? "图片"),
                    "mimeType": .string(media.mimeType),
                ])
            )
        })
        state.messages.append(
            AgentMessage(
                schemaVersion: "rag-ime.agent-message.v1",
                id: id,
                sessionId: sessionId,
                turnId: id,
                role: "user",
                status: "queued",
                blocks: blocks,
                attachments: attachments.map(\.mediaId),
                citations: [],
                createdAtMs: nowMs,
                completedAtMs: nil
            )
        )
        state.activity = [
            AgentActivityItem(
                id: "\(id):thinking",
                title: "正在思考",
                detail: "正在等待 Pi 接收请求",
                state: .running,
                createdAtMs: nowMs,
                turnId: id
            )
        ]
        state.status = "busy"
        state.failureMessage = ""
        return id
    }

    static func markOptimisticFailure(
        state: inout AgentConversationState,
        messageId: String,
        error: String
    ) {
        guard let index = state.messages.firstIndex(where: { $0.id == messageId }) else { return }
        state.messages[index] = replacingStatus(state.messages[index], status: "failed")
        _ = replacePendingWithFailure(
            state: &state,
            title: "发送失败",
            detail: clipped(error)
        )
        state.status = "failed"
        state.failureMessage = clipped(error)
    }

    private static func applyStatus(
        state: inout AgentConversationState,
        event: AgentEventEnvelope,
        payload: [String: JSONValue]
    ) {
        let status = payload["status"]?.stringValue ?? ""
        if !status.isEmpty { state.status = status }
        switch status {
        case "busy":
            if let index = pendingActivityIndex(state) {
                state.activity[index].title = "正在思考"
                state.activity[index].detail = "Pi 已接收请求"
                state.activity[index].turnId = event.turnId
            } else {
                upsertActivity(
                    state: &state,
                    item: AgentActivityItem(
                        id: "\(event.turnId):understand",
                        title: "正在思考",
                        detail: "Pi 已接收请求",
                        state: .running,
                        createdAtMs: event.createdAtMs,
                        turnId: event.turnId
                    )
                )
            }
        case "analyzing":
            if let index = pendingActivityIndex(state) {
                state.activity[index].title = "整理检索线索中…"
                state.activity[index].detail = "正在选择需要查询的工具书、近期对话与知识"
                state.activity[index].turnId = event.turnId
            } else {
                upsertActivity(
                    state: &state,
                    item: AgentActivityItem(
                        id: "\(event.turnId):analyzing",
                        title: "整理检索线索中…",
                        detail: "正在选择需要查询的工具书、近期对话与知识",
                        state: .running,
                        createdAtMs: event.createdAtMs,
                        turnId: event.turnId
                    )
                )
            }
        case "ready", "idle", "stopped":
            completeRunningActivity(state: &state)
        default:
            break
        }
    }

    private static func applyTextDelta(
        state: inout AgentConversationState,
        event: AgentEventEnvelope,
        payload: [String: JSONValue]
    ) {
        let messageId = payload["messageId"]?.stringValue ?? "\(event.turnId):assistant"
        let blockId = payload["blockId"]?.stringValue ?? "\(messageId):text"
        let delta = payload["delta"]?.stringValue ?? ""
        let replaceBlock = payload["replaceBlock"]?.boolValue == true
        guard !delta.isEmpty else { return }
        completePendingActivity(state: &state)
        let now = event.createdAtMs
        if let index = state.messages.firstIndex(where: { $0.id == messageId }) {
            var blocks = state.messages[index].blocks
            if let blockIndex = blocks.firstIndex(where: { $0.id == blockId || $0.type == .text }) {
                let existing = replaceBlock
                    ? ""
                    : (blocks[blockIndex].data.objectValue["text"]?.stringValue ?? "")
                blocks[blockIndex] = AgentBlock(
                    id: blocks[blockIndex].id,
                    type: .text,
                    status: "running",
                    presentationKind: "markdown",
                    data: .object(["text": .string(existing + delta)])
                )
            } else {
                blocks.append(textBlock(id: blockId, text: delta, status: "running"))
            }
            let message = state.messages[index]
            state.messages[index] = AgentMessage(
                schemaVersion: message.schemaVersion,
                id: message.id,
                sessionId: message.sessionId,
                turnId: message.turnId,
                role: message.role,
                status: "streaming",
                blocks: blocks,
                attachments: message.attachments,
                citations: message.citations,
                createdAtMs: message.createdAtMs,
                completedAtMs: nil
            )
        } else {
            state.messages.append(
                AgentMessage(
                    schemaVersion: "rag-ime.agent-message.v1",
                    id: messageId,
                    sessionId: event.sessionId,
                    turnId: event.turnId,
                    role: "assistant",
                    status: "streaming",
                    blocks: [textBlock(id: blockId, text: delta, status: "running")],
                    attachments: [],
                    citations: [],
                    createdAtMs: now,
                    completedAtMs: nil
                )
            )
        }
        state.status = "responding"
    }

    private static func applyToolEvent(
        state: inout AgentConversationState,
        event: AgentEventEnvelope,
        payload: [String: JSONValue]
    ) {
        let toolCallId = payload["toolCallId"]?.stringValue ?? "\(event.turnId):tool"
        let toolName = payload["toolName"]?.stringValue ?? ""
        let operation = payload["args"]?.objectValue["op"]?.stringValue ?? ""
        let finished = event.eventType == .toolFinished
        let failed = payload["isError"]?.boolValue == true
        let title = toolActivityTitle(toolName: toolName, operation: operation, finished: finished)
        let detail = toolActivityDetail(payload: payload, operation: operation, finished: finished)
        let references = toolActivityReferences(payload: payload, operation: operation, finished: finished)
        completePendingActivity(state: &state)
        if failed,
           let duplicate = state.activity.first(where: {
               $0.id != toolCallId
                   && $0.turnId == event.turnId
                   && $0.state == .failed
                   && $0.title == title
           }) {
            state.activity.removeAll(where: { $0.id == toolCallId })
            if let duplicateIndex = state.activity.firstIndex(where: { $0.id == duplicate.id }) {
                state.activity[duplicateIndex].detail = detail
                state.activity[duplicateIndex].references = mergedReferences(
                    state.activity[duplicateIndex].references,
                    references
                )
            }
            state.status = "failed"
            return
        }
        upsertActivity(
            state: &state,
            item: AgentActivityItem(
                id: toolCallId,
                title: title,
                detail: detail,
                state: failed ? .failed : (finished ? .completed : .running),
                createdAtMs: event.createdAtMs,
                turnId: event.turnId,
                references: references
            )
        )
        state.status = failed ? "failed" : "working"
    }

    private static func upsertMessage(state: inout AgentConversationState, message: AgentMessage) {
        // Tool results are model context. Their typed tool events already feed
        // the expandable activity row and must never become chat bubbles.
        guard message.role == "user" || message.role == "assistant" else { return }
        if message.role == "user",
           let optimistic = state.messages.firstIndex(where: {
               $0.role == "user" && $0.status == "queued" && plainText($0) == plainText(message)
           }) {
            state.messages[optimistic] = message
            return
        }
        if let index = state.messages.firstIndex(where: { $0.id == message.id }) {
            state.messages[index] = message
        } else {
            state.messages.append(message)
        }
        state.messages = deduplicated(state.messages)
    }

    private static func upsertActivity(state: inout AgentConversationState, item: AgentActivityItem) {
        if let index = state.activity.firstIndex(where: { $0.id == item.id }) {
            state.activity[index] = item
        } else {
            state.activity.append(item)
        }
        if state.activity.count > 12 {
            state.activity.removeFirst(state.activity.count - 12)
        }
    }

    private static func pendingActivityIndex(_ state: AgentConversationState) -> Int? {
        state.activity.firstIndex(where: {
            $0.state == .running
                && ($0.id.hasSuffix(":thinking")
                    || $0.title == "正在思考"
                    || $0.title == "理解问题中…")
        })
    }

    private static func completePendingActivity(state: inout AgentConversationState) {
        guard let index = pendingActivityIndex(state) else { return }
        state.activity[index].state = .completed
        state.activity[index].title = completedTitle(state.activity[index].title)
    }

    @discardableResult
    private static func replacePendingWithFailure(
        state: inout AgentConversationState,
        title: String,
        detail: String
    ) -> Bool {
        let index = state.activity.firstIndex(where: {
            $0.id.hasSuffix(":thinking")
                || ["正在思考", "已思考", "理解问题中…", "模型请求失败", "发送失败", "本轮没有完成"]
                    .contains($0.title)
        })
        guard let index else { return false }
        state.activity[index].title = title
        state.activity[index].detail = clipped(detail)
        state.activity[index].state = .failed
        return true
    }

    private static func mergedReferences(
        _ existing: [AgentActivityReference],
        _ incoming: [AgentActivityReference]
    ) -> [AgentActivityReference] {
        var seen = Set<String>()
        return (existing + incoming).filter { seen.insert($0.id).inserted }
    }

    private static func completeRunningActivity(state: inout AgentConversationState, failed: Bool = false) {
        for index in state.activity.indices where state.activity[index].state == .running {
            state.activity[index].state = failed ? .failed : .completed
            state.activity[index].title = completedTitle(state.activity[index].title)
        }
    }

    private static func completeQueuedUserMessages(state: inout AgentConversationState) {
        for index in state.messages.indices where state.messages[index].status == "queued" {
            state.messages[index] = replacingStatus(state.messages[index], status: "completed")
        }
    }

    private static func replacingStatus(_ message: AgentMessage, status: String) -> AgentMessage {
        AgentMessage(
            schemaVersion: message.schemaVersion,
            id: message.id,
            sessionId: message.sessionId,
            turnId: message.turnId,
            role: message.role,
            status: status,
            blocks: message.blocks,
            attachments: message.attachments,
            citations: message.citations,
            createdAtMs: message.createdAtMs,
            completedAtMs: message.completedAtMs
        )
    }

    private static func textBlock(id: String, text: String, status: String) -> AgentBlock {
        AgentBlock(
            id: id,
            type: .text,
            status: status,
            presentationKind: "markdown",
            data: .object(["text": .string(text)])
        )
    }

    private static func decode<T: Decodable>(_ value: JSONValue?) -> T? {
        guard let value, let data = try? JSONEncoder().encode(value) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    private static func deduplicated(_ messages: [AgentMessage]) -> [AgentMessage] {
        var seen: Set<String> = []
        return messages.filter { seen.insert($0.id).inserted }
    }

    private static func plainText(_ message: AgentMessage) -> String {
        message.blocks
            .filter { $0.type == .text }
            .map { $0.data.objectValue["text"]?.stringValue ?? "" }
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func toolActivityTitle(toolName: String, operation: String, finished: Bool) -> String {
        let running: String
        switch (toolName, operation) {
        case ("ime_overview", "status"): running = "正在检查控制中心状态"
        case ("ime_overview", "capabilities"): running = "正在读取可用能力"
        case ("ime_overview", "recent_activity"): running = "正在查看近期活动"
        case ("ime_input", "get_settings"): running = "正在读取输入法设置"
        case ("ime_input", "preview_settings"): running = "正在比较输入设置差异"
        case ("ime_input", "apply_settings"): running = "正在准备输入设置审批"
        case ("ime_input", "rollback_settings"): running = "正在核对输入设置撤销点"
        case ("ime_input", "profile"): running = "正在检查当前输入方案"
        case ("ime_input", "candidate_explain"): running = "正在解释候选来源"
        case ("ime_input", "lexicon_review"): running = "正在检查待审词条"
        case ("ime_input", "lexicon_apply"): running = "正在准备个人词表审批"
        case ("ime_input", "lexicon_rollback"): running = "正在核对个人词表回滚点"
        case ("ime_voice", "status"): running = "正在检查语音输入"
        case ("ime_voice", "privacy_policy"): running = "正在核对语音隐私边界"
        case ("ime_voice", "provider_status"): running = "正在检查语音 Provider"
        case ("ime_voice", "provider_preview"): running = "正在比较语音 Provider 差异"
        case ("ime_voice", "provider_apply"): running = "正在准备语音 Provider 审批"
        case ("ime_voice", "provider_rollback"): running = "正在核对语音 Provider 回滚点"
        case ("ime_planning", "dashboard"): running = "正在查看计划与任务"
        case ("ime_memory", "catalog"): running = "查找相关工具书中…"
        case ("ime_memory", "read"): running = "翻工具书中…"
        case ("ime_memory", "recent"): running = "查近期对话中…"
        case ("ime_memory", "trace"): running = "正在核对记忆来源"
        case ("ime_memory", "maintenance_status"): running = "正在检查记忆整理任务"
        case ("ime_memory", "maintenance_preview"): running = "正在比较证据并生成记忆草案"
        case ("ime_memory", "maintenance_review"): running = "正在逐项审阅记忆草案"
        case ("ime_memory", "maintenance_apply"): running = "正在准备应用记忆草案"
        case ("ime_memory", "maintenance_rollback"): running = "正在准备回滚记忆整理"
        case ("ime_memory", "list"): running = "正在浏览记忆目录"
        case ("ime_memory", "search"): running = "检索长期记忆中…"
        case ("ime_knowledge", "recall"): running = "检索相关记录中…"
        case ("ime_knowledge", "deep_recall"): running = "扩大检索范围中…"
        case ("ime_knowledge", "route_status"): running = "正在检查知识检索路由"
        case ("ime_models", "status"): running = "正在检查模型状态"
        case ("ime_models", "profiles"): running = "正在读取非密钥 Provider 配置"
        case ("ime_models", "profile_preview"): running = "正在比较 Provider 配置差异"
        case ("ime_models", "profile_apply"): running = "正在准备 Provider 配置审批"
        case ("ime_models", "profile_rollback"): running = "正在核对 Provider 配置回滚点"
        case ("ime_models", "probe"): running = "正在探测模型能力"
        case ("ime_models", "cache_stats"): running = "正在读取模型缓存统计"
        case ("ime_runtime", "health"): running = "正在检查运行时健康度"
        case ("ime_runtime", "components"): running = "正在读取运行组件"
        case ("ime_runtime", "diagnose"): running = "正在分析未就绪组件"
        case ("ime_runtime", "pause_ai"): running = "正在准备暂停 AI 辅助"
        case ("ime_runtime", "resume_ai"): running = "正在准备恢复 AI 辅助"
        case ("ime_runtime", "restart_sidecar"): running = "正在准备 Sidecar 两阶段重启"
        case ("ime_runtime", "restart_predictor"): running = "正在准备重启本地预测器"
        case ("ime_runtime", "redeploy_rime"): running = "正在准备重新部署 Rime"
        case ("ime_configuration", "history"): running = "正在读取隐私化历史"
        case ("ime_configuration", "audit"): running = "正在读取管理审计"
        case ("ime_configuration", "export_preview"): running = "正在核对便携备份范围"
        case ("ime_configuration", "export"): running = "正在准备无密钥备份"
        case ("ime_configuration", "restore_preview"): running = "正在验证受管备份"
        case ("ime_configuration", "restore_apply"): running = "正在准备两阶段恢复审批"
        case ("workspace_list", "list"): running = "正在浏览授权工作区"
        case ("workspace_read", "read"): running = "正在读取工作区文件"
        case ("workspace_shell", "run"): running = "正在运行受控命令"
        default: running = "正在调用 \(toolDisplayName(toolName))"
        }
        return finished ? completedTitle(running) : running
    }

    private static func toolActivityDetail(
        payload: [String: JSONValue],
        operation: String,
        finished: Bool
    ) -> String {
        let args = payload["args"]?.objectValue ?? [:]
        let details = toolResultDetails(payload: payload, finished: finished)
        let items = details["items"]?.arrayValue ?? details["sources"]?.arrayValue ?? []
        let names = items.prefix(5).compactMap { item -> String? in
            let object = item.objectValue
            let name = ["title", "bookTitle", "group", "tag", "label", "evidence", "text"]
                .compactMap { object[$0]?.stringValue }
                .first(where: { !$0.isEmpty })
            guard let name else { return nil }
            switch object["kind"]?.stringValue {
            case "book": return "书《\(name)》"
            case "group": return "Group「\(name)」"
            case "tag": return "Tag #\(name)"
            default: return name
            }
        }
        if let summary = details["summary"]?.stringValue, !summary.isEmpty {
            return clipped(names.isEmpty ? summary : "\(summary)：\(names.joined(separator: "、"))")
        }
        if !items.isEmpty {
            let prefix = names.isEmpty ? "" : "：\(names.joined(separator: "、"))"
            return "找到 \(items.count) 项\(prefix)"
        }
        if let count = details["count"]?.numberValue, count > 0 {
            return "找到 \(Int(count)) 项相关内容"
        }
        if let count = details["entryCount"]?.numberValue, count > 0 {
            return "有 \(Int(count)) 条内容等待审阅"
        }
        if let count = details["toolCount"]?.numberValue, count > 0 {
            return "已连接 \(Int(count)) 个受控工具领域"
        }
        let labels = ["bookTitle", "group", "tag", "project"]
            .compactMap { key -> String? in
                let value = args[key]?.stringValue ?? ""
                return value.isEmpty ? nil : value
            }
        if !labels.isEmpty { return clipped(labels.joined(separator: " · ")) }
        if operation == "recall" || operation == "deep_recall" {
            return finished ? "近期对话与时间记忆已召回" : "正在匹配近期对话与时间记忆"
        }
        return ""
    }

    private static func toolActivityReferences(
        payload: [String: JSONValue],
        operation: String,
        finished: Bool
    ) -> [AgentActivityReference] {
        let details = toolResultDetails(payload: payload, finished: finished)
        let items = details["items"]?.arrayValue ?? details["sources"]?.arrayValue ?? []
        var references = items.compactMap { item -> AgentActivityReference? in
            let object = item.objectValue
            let label = ["title", "bookTitle", "group", "tag", "label", "evidence", "text"]
                .compactMap { object[$0]?.stringValue }
                .first(where: { !$0.isEmpty })
            guard let label else { return nil }
            let kind: AgentActivityReference.Kind
            switch operation == "recent" ? "recent" : object["kind"]?.stringValue {
            case "book": kind = .book
            case "group": kind = .group
            case "tag": kind = .tag
            case "recent": kind = .recent
            default: kind = .source
            }
            return AgentActivityReference(kind: kind, label: clipped(label))
        }
        for item in items {
            for tag in item.objectValue["tags"]?.arrayValue ?? [] {
                let label = tag.stringValue
                guard !label.isEmpty else { continue }
                references.append(AgentActivityReference(kind: .tag, label: clipped(label)))
            }
        }
        references = deduplicatedReferences(references)
        if !references.isEmpty { return Array(references.prefix(8)) }
        if operation == "recent" {
            let count = Int(details["count"]?.numberValue ?? 0)
            if count > 0 {
                return [AgentActivityReference(kind: .recent, label: "\(count) 段近期对话")]
            }
        }
        return []
    }

    private static func toolResultDetails(
        payload: [String: JSONValue],
        finished: Bool
    ) -> [String: JSONValue] {
        let resultKey = finished ? "result" : "partialResult"
        let outer = payload[resultKey]?.objectValue ?? [:]
        let extensionDetails = outer["details"]?.objectValue ?? outer
        // The audited Pi extension returns the typed gateway envelope as
        // ToolResult.details; the domain payload lives one level deeper.
        return extensionDetails["result"]?.objectValue ?? extensionDetails
    }

    private static func deduplicatedReferences(
        _ references: [AgentActivityReference]
    ) -> [AgentActivityReference] {
        var seen: Set<String> = []
        return references.filter { seen.insert($0.id).inserted }
    }

    private static func toolDisplayName(_ name: String) -> String {
        switch name {
        case "ime_memory": return "记忆"
        case "ime_knowledge": return "知识库"
        case "ime_planning": return "规划"
        case "ime_overview": return "概览"
        case "ime_input": return "输入法设置"
        case "ime_voice": return "语音输入"
        case "ime_models": return "模型服务"
        case "ime_runtime": return "运行组件"
        case "ime_configuration": return "配置"
        case "workspace_list": return "工作区浏览"
        case "workspace_read": return "工作区读取"
        case "workspace_shell": return "Command Harness"
        default: return "工具"
        }
    }

    private static func completedTitle(_ title: String) -> String {
        if title.hasSuffix("中…") {
            let base = title.dropLast(2)
            return base.hasPrefix("正在") ? "已\(base.dropFirst(2))" : "已\(base)"
        }
        return title.hasPrefix("正在") ? "已\(title.dropFirst(2))" : title
    }

    private static func resolutionTitle(_ state: String) -> String {
        switch state {
        case "failed": return "操作执行失败"
        case "expired": return "审批已过期"
        case "stale": return "审批内容已变化"
        default: return "已拒绝操作"
        }
    }

    private static func resolutionDetail(_ state: String) -> String {
        switch state {
        case "failed": return "未应用变更，可查看执行回执"
        case "expired": return "60 秒确认窗口已关闭，未应用变更"
        case "stale": return "目标状态已变化，需要重新生成差异"
        default: return "当前操作不会执行"
        }
    }

    private static func clipped(_ text: String) -> String {
        let compact = text.split(whereSeparator: \Character.isWhitespace).joined(separator: " ")
        return String(compact.prefix(180))
    }
}

@MainActor
final class AgentComposerState: ObservableObject {
    @Published var draft = ""
    @Published var commandFeedback = ""
}

@MainActor
final class AgentWorkspaceStore: ObservableObject {
    @Published private(set) var runtime: AgentRuntimeStatus?
    @Published private(set) var sessions: [AgentSessionSummary] = []
    @Published private(set) var toolCatalog: [AgentToolManifest] = []
    @Published private(set) var roleCatalog: [AgentRoleSummary] = []
    @Published private(set) var modelCatalog: AgentModelCatalogResponse?
    @Published private(set) var approvals: [AgentApproval] = []
    @Published private(set) var memorySources: [AgentMemorySource] = []
    @Published private(set) var memoryMaintenance: AgentMemoryMaintenanceStatus?
    @Published private(set) var pendingAttachments: [AgentMediaReceipt] = []
    @Published var selectedSessionId = ""
    @Published var conversation = AgentConversationState()
    @Published var loading = false
    @Published var sending = false
    @Published var showArchived = false
    @Published var errorMessage = ""
    @Published private(set) var approvalActionId = ""
    @Published private(set) var importingAttachments = false
    @Published private(set) var switchingModel = false
    @Published private(set) var switchingThinkingLevel = false
    @Published private(set) var switchingSessionMode = false

    private let api: AgentAPIClient
    let composerState = AgentComposerState()
    private var streamTask: Task<Void, Never>?
    private var deltaFlushTask: Task<Void, Never>?
    private var modelCatalogTask: Task<Void, Never>?
    private var bufferedTextDeltaEvents: [AgentEventEnvelope] = []
    private var activated = false

    // Pi can emit many small text fragments per display frame. Applying every
    // fragment to the published conversation makes the whole workspace redraw.
    // Keep streamed text aligned with a 60 Hz display budget. The transcript
    // surface appends only the visible suffix, so a frame-paced flush remains
    // cheaper than visibly stepping at the previous 25 Hz cadence.
    private let deltaFlushNanoseconds: UInt64 = 16_666_667

    init(api: AgentAPIClient = AgentAPIClient()) {
        self.api = api
    }

    var draft: String {
        get { composerState.draft }
        set { composerState.draft = newValue }
    }

    private var commandFeedback: String {
        get { composerState.commandFeedback }
        set { composerState.commandFeedback = newValue }
    }

    var selectedSession: AgentSessionSummary? {
        sessions.first(where: { $0.id == selectedSessionId })
    }

    var selectedModel: AgentModelOption? {
        modelCatalog?.selected
    }

    var selectedThinkingLevel: String {
        modelCatalog?.thinkingLevel ?? "off"
    }

    var canSwitchModel: Bool {
        canUseRuntime
            && !selectedSessionId.isEmpty
            && !sending
            && !switchingModel
            && !switchingThinkingLevel
            && ["idle", "ready", "failed"].contains(conversation.status)
    }

    var canSwitchSessionMode: Bool {
        !selectedSessionId.isEmpty
            && !sending
            && !switchingSessionMode
            && ["idle", "ready", "failed"].contains(conversation.status)
    }

    var canUseRuntime: Bool {
        guard let runtime else { return false }
        let capabilities = runtime.capabilities.objectValue
        return runtime.enabled
            && capabilities["rpc"]?.boolValue == true
            && capabilities["modelConfigured"]?.boolValue != false
            && (
                selectedSession?.mode != "coordinator"
                    || capabilities["coordinator"]?.boolValue == true
            )
    }

    var canSend: Bool {
        let hasContent = !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !pendingAttachments.isEmpty
        return canUseRuntime && !selectedSessionId.isEmpty && hasContent && !sending && !importingAttachments
    }

    var pendingApprovals: [AgentApproval] {
        approvals.filter { $0.state == "pending" }
    }

    var recentApprovalReceipts: [AgentApproval] {
        Array(
            approvals
                .filter {
                    ["external_pending", "applied", "failed", "rejected", "expired", "stale"]
                        .contains($0.state)
                }
                .prefix(3)
        )
    }

    func rollbackConsumed(for approval: AgentApproval) -> Bool {
        if approval.toolId == "ime_memory" {
            let runId = approval.receipt?.objectValue["runId"]?.stringValue ?? ""
            guard !runId.isEmpty else { return false }
            return approvals.contains { item in
                item.receipt?.objectValue["revertedRunId"]?.stringValue == runId
            }
        }
        if approval.toolId == "ime_input", approval.operation == "apply_settings" {
            return approvals.contains { item in
                item.receipt?.objectValue["revertedSettingsApprovalId"]?.stringValue == approval.approvalId
            }
        }
        if approval.toolId == "ime_input", approval.operation == "lexicon_apply" {
            return approvals.contains { item in
                item.receipt?.objectValue["revertedLexiconApprovalId"]?.stringValue == approval.approvalId
            }
        }
        if approval.toolId == "ime_models", approval.operation == "profile_apply" {
            return approvals.contains { item in
                item.receipt?.objectValue["revertedModelProfileApprovalId"]?.stringValue == approval.approvalId
            }
        }
        if approval.toolId == "ime_voice", approval.operation == "provider_apply" {
            return approvals.contains { item in
                item.receipt?.objectValue["revertedVoiceProviderApprovalId"]?.stringValue == approval.approvalId
            }
        }
        let eventId = approval.receipt?.objectValue["taskEventId"]?.stringValue ?? ""
        guard !eventId.isEmpty else { return false }
        return approvals.contains { item in
            item.receipt?.objectValue["revertedTaskEventId"]?.stringValue == eventId
        }
    }

    func prepareUndo(for approval: AgentApproval) {
        let receipt = approval.receipt?.objectValue ?? [:]
        guard receipt["undoAvailable"]?.boolValue == true else { return }
        if approval.toolId == "ime_memory" {
            let runId = receipt["runId"]?.stringValue ?? ""
            guard !runId.isEmpty else { return }
            draft = "请回滚刚才应用的记忆整理草案 \(runId)。"
            return
        }
        if approval.toolId == "ime_input", approval.operation == "apply_settings" {
            draft = "请撤销刚才应用的输入法设置变更。"
            return
        }
        if approval.toolId == "ime_input", approval.operation == "lexicon_apply" {
            draft = "请回滚刚才应用的个人词表变更。"
            return
        }
        if approval.toolId == "ime_models", approval.operation == "profile_apply" {
            draft = "请回滚刚才保存的模型 Provider 配置。"
            return
        }
        if approval.toolId == "ime_voice", approval.operation == "provider_apply" {
            draft = "请回滚刚才保存的语音 Provider 选择。"
            return
        }
        let task = receipt["task"]?.objectValue ?? [:]
        let title = task["title"]?.stringValue ?? "这个任务"
        draft = "请撤销刚才对《\(title)》的任务状态变更。"
    }

    func activate(preferredSessionId: String = "") async {
        loading = true
        defer { loading = false }
        do {
            async let runtimeRequest = api.runtimeStatus()
            async let sessionsRequest = api.sessions(includeArchived: showArchived)
            async let toolsRequest = api.tools()
            async let rolesRequest = api.roles()
            let (runtime, response, tools, roles) = try await (
                runtimeRequest,
                sessionsRequest,
                toolsRequest,
                rolesRequest
            )
            self.runtime = runtime
            self.sessions = response.items
            self.toolCatalog = tools.items
            self.roleCatalog = roles.items
            let externallyPreferred = preferredSessionId.isEmpty
                ? nil
                : sessions.first(where: { $0.id == preferredSessionId })?.id
            if externallyPreferred != nil
                || selectedSessionId.isEmpty
                || !sessions.contains(where: { $0.id == selectedSessionId }) {
                selectedSessionId = externallyPreferred ?? response.activeSessionId.flatMap { active in
                    sessions.contains(where: { $0.id == active }) ? active : nil
                } ?? sessions.first?.id ?? ""
                conversation = AgentConversationState()
                approvals = []
                memorySources = []
                modelCatalog = nil
                pendingAttachments = []
            }
            activated = true
            errorMessage = ""
            await reloadMemoryMaintenance()
            if canUseRuntime, !selectedSessionId.isEmpty {
                await loadConversationAndStream()
            } else {
                suspendStream()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func focusExternalSession(_ sessionId: String) async {
        guard !sessionId.isEmpty else { return }
        _ = prepareSessionSelection(sessionId)
        await activate(preferredSessionId: sessionId)
    }

    func reloadSessions() async {
        do {
            let response = try await api.sessions(includeArchived: showArchived)
            sessions = response.items
            if !selectedSessionId.isEmpty, !sessions.contains(where: { $0.id == selectedSessionId }) {
                selectedSessionId = sessions.first?.id ?? ""
                conversation = AgentConversationState()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @discardableResult
    func createSession(
        title: String = "新对话",
        mode: String = "assistant",
        roleId: String = "zhiyou-v1",
        roleVersion: String = "1",
        workspaceRoots: [String] = []
    ) async -> Bool {
        do {
            let response = try await api.createSession(
                title: title,
                mode: mode,
                roleId: roleId,
                roleVersion: roleVersion,
                workspaceRoots: workspaceRoots
            )
            await reloadSessions()
            await selectSession(response.session.id)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func setRuntimeEnabled(_ enabled: Bool) async {
        do {
            _ = try await api.setEnabled(enabled)
            runtime = try await api.runtimeStatus()
            errorMessage = ""
            if enabled, canUseRuntime, !selectedSessionId.isEmpty {
                await loadConversationAndStream()
            } else {
                suspendStream()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func selectSession(_ id: String) async {
        guard prepareSessionSelection(id) else { return }
        if canUseRuntime, !id.isEmpty {
            await loadConversationAndStream(expectedSessionId: id)
        }
    }

    /// Commits the visual selection before any transcript or catalog request.
    /// This is the click path used by the session rail: the row responds in the
    /// current AppKit event instead of waiting for a Task to be scheduled.
    func selectSessionInteractively(_ id: String) {
        guard prepareSessionSelection(id) else { return }
        guard canUseRuntime, !id.isEmpty else { return }
        Task { [weak self] in
            await self?.loadConversationAndStream(expectedSessionId: id)
        }
    }

    private func prepareSessionSelection(_ id: String) -> Bool {
        guard id != selectedSessionId || !activated else { return false }
        suspendStream()
        selectedSessionId = id
        conversation = AgentConversationState()
        approvals = []
        memorySources = []
        modelCatalog = nil
        pendingAttachments = []
        errorMessage = ""
        return true
    }

    func renameSelected(_ title: String) async {
        guard !selectedSessionId.isEmpty else { return }
        do {
            _ = try await api.updateSession(id: selectedSessionId, title: title)
            await reloadSessions()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func archiveSelected(_ archived: Bool) async {
        guard !selectedSessionId.isEmpty else { return }
        do {
            _ = try await api.updateSession(id: selectedSessionId, archived: archived)
            suspendStream()
            selectedSessionId = ""
            conversation = AgentConversationState()
            pendingAttachments = []
            await reloadSessions()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func switchSessionMode(_ mode: String) async {
        guard canSwitchSessionMode,
              let session = selectedSession,
              session.mode != mode else { return }
        switchingSessionMode = true
        defer { switchingSessionMode = false }
        do {
            let response = try await api.updateSession(
                id: session.id,
                mode: mode,
                workspaceRoots: mode == "coordinator" ? session.workspaceRoots : []
            )
            if let index = sessions.firstIndex(where: { $0.id == response.session.id }) {
                sessions[index] = response.session
            }
            runtime = try await api.runtimeStatus()
            await loadConversationAndStream(expectedSessionId: session.id)
            errorMessage = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteSelected() async {
        guard !selectedSessionId.isEmpty else { return }
        do {
            _ = try await api.deleteSession(id: selectedSessionId)
            suspendStream()
            selectedSessionId = ""
            conversation = AgentConversationState()
            pendingAttachments = []
            await reloadSessions()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func send() async {
        let input = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        if input.hasPrefix("/") {
            await executeSlashCommand(input)
        } else {
            await sendMessage(draft)
        }
    }

    func importImages(_ urls: [URL]) async {
        guard canUseRuntime, !selectedSessionId.isEmpty, !urls.isEmpty, !importingAttachments else { return }
        let remaining = max(0, 8 - pendingAttachments.count)
        guard remaining > 0 else {
            errorMessage = "一条消息最多附加 8 张图片"
            return
        }
        importingAttachments = true
        defer { importingAttachments = false }
        for url in urls.prefix(remaining) {
            let accessing = url.startAccessingSecurityScopedResource()
            defer { if accessing { url.stopAccessingSecurityScopedResource() } }
            do {
                let data = try Data(contentsOf: url, options: [.mappedIfSafe])
                guard data.count <= 20 * 1024 * 1024 else {
                    throw APIClientError.server(413, "图片超过 20 MB")
                }
                let response = try await api.importMedia(
                    sessionId: selectedSessionId,
                    fileName: url.lastPathComponent,
                    mimeType: imageMimeType(for: url),
                    data: data
                )
                pendingAttachments.append(response.media)
                errorMessage = ""
            } catch {
                errorMessage = "\(url.lastPathComponent)：\(error.localizedDescription)"
            }
        }
    }

    func removePendingAttachment(_ mediaId: String) {
        pendingAttachments.removeAll(where: { $0.mediaId == mediaId })
    }

    func selectModel(_ model: AgentModelOption) async {
        await selectModel(model, thinkingLevel: nil)
    }

    func selectModel(_ model: AgentModelOption, thinkingLevel: String?) async {
        guard canSwitchModel else { return }
        let sessionId = selectedSessionId
        switchingModel = true
        defer { switchingModel = false }
        do {
            if model.selectionId != selectedModel?.selectionId {
                let response = try await api.selectModel(
                    sessionId: sessionId,
                    provider: model.provider,
                    modelId: model.id
                )
                guard selectedSessionId == sessionId else { return }
                if let index = sessions.firstIndex(where: { $0.id == sessionId }) {
                    sessions[index] = response.session
                }
            }
            if let thinkingLevel {
                _ = try await api.selectThinkingLevel(sessionId: sessionId, level: thinkingLevel)
            }
            await reloadModelCatalog(sessionId: sessionId)
            errorMessage = ""
        } catch {
            guard selectedSessionId == sessionId else { return }
            errorMessage = error.localizedDescription
        }
    }

    func selectThinkingLevel(_ level: String) async {
        guard let model = selectedModel else { return }
        await selectModel(model, thinkingLevel: level)
    }

    func sendSuggestion(_ suggestion: String) async {
        guard draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        await sendMessage(suggestion)
    }

    private func sendMessage(_ input: String) async {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let attachments = pendingAttachments
        let text = trimmed.isEmpty && !attachments.isEmpty ? "请查看这些图片。" : trimmed
        guard canUseRuntime, !selectedSessionId.isEmpty, !text.isEmpty, !sending else { return }
        sending = true
        commandFeedback = ""
        draft = ""
        pendingAttachments = []
        let sessionId = selectedSessionId
        let localId = AgentConversationReducer.appendOptimisticUser(
            state: &conversation,
            sessionId: sessionId,
            text: text,
            attachments: attachments,
            nowMs: Int(Date().timeIntervalSince1970 * 1000)
        )
        do {
            _ = try await api.prompt(
                sessionId: sessionId,
                message: text,
                attachments: attachments.map(\.mediaId)
            )
            errorMessage = ""
        } catch {
            draft = text
            pendingAttachments = attachments
            AgentConversationReducer.markOptimisticFailure(
                state: &conversation,
                messageId: localId,
                error: error.localizedDescription
            )
            errorMessage = error.localizedDescription
        }
        sending = false
    }

    private func executeSlashCommand(_ input: String) async {
        let parts = input.split(maxSplits: 1, whereSeparator: \Character.isWhitespace)
        let command = parts.first.map(String.init)?.lowercased() ?? ""
        let argument = parts.count > 1
            ? String(parts[1]).trimmingCharacters(in: .whitespacesAndNewlines)
            : ""
        switch command {
        case "/new":
            let current = selectedSession
            draft = ""
            let created = await createSession(
                title: argument.isEmpty ? "新对话" : String(argument.prefix(120)),
                mode: current?.mode ?? "assistant",
                roleId: current?.roleId ?? "zhiyou-v1",
                roleVersion: current?.roleVersion ?? "1",
                workspaceRoots: current?.workspaceRoots ?? []
            )
            commandFeedback = created ? "已创建连续对话" : "新建对话失败"
        case "/compact":
            guard !selectedSessionId.isEmpty, !sending else { return }
            sending = true
            draft = ""
            defer { sending = false }
            do {
                _ = try await api.compact(sessionId: selectedSessionId)
                commandFeedback = "上下文已压缩，会话会继续保留"
                errorMessage = ""
            } catch {
                errorMessage = error.localizedDescription
            }
        case "/stop":
            draft = ""
            await abort()
            commandFeedback = "已发送停止请求"
        case "/status":
            draft = ""
            let runtimeStatus = runtime?.status ?? "unknown"
            commandFeedback = "Pi \(runtimeStatus) · \(conversation.messages.count) 条消息"
        case "/memory":
            draft = ""
            let query = argument.isEmpty ? "请检查当前会话相关的记忆工具书和近期对话。" : "请在记忆工具书和近期对话中查找：\(argument)"
            await sendMessage(query)
        case "/read":
            guard !argument.isEmpty else {
                commandFeedback = "在 /read 后粘贴文件或文件夹路径"
                return
            }
            draft = ""
            await sendMessage("请读取并处理这个路径：\(argument)")
        case "/model":
            guard !argument.isEmpty else {
                commandFeedback = "当前模型：\(selectedModel?.selectionId ?? "Pi 默认") · 思考 \(selectedThinkingLevel)"
                return
            }
            let modelParts = argument.split(whereSeparator: \Character.isWhitespace).map(String.init)
            let reference = modelParts[0]
            let level = modelParts.count > 1 ? modelParts[1].lowercased() : nil
            let models = modelCatalog?.providers.flatMap(\.models) ?? []
            guard let model = models.first(where: {
                $0.selectionId.caseInsensitiveCompare(reference) == .orderedSame
                    || $0.id.caseInsensitiveCompare(reference) == .orderedSame
            }) else {
                commandFeedback = "没有找到模型 \(reference)"
                return
            }
            if let level, !model.thinkingLevels.contains(level) {
                commandFeedback = "\(model.name) 支持：\(model.thinkingLevels.joined(separator: ", "))"
                return
            }
            draft = ""
            await selectModel(model, thinkingLevel: level)
            commandFeedback = "已切换到 \(model.name)\(level.map { " · 思考 \($0)" } ?? "")"
        case "/thinking":
            let level = argument.lowercased()
            guard let model = selectedModel, model.thinkingLevels.contains(level) else {
                commandFeedback = "当前模型支持：\(selectedModel?.thinkingLevels.joined(separator: ", ") ?? "off")"
                return
            }
            draft = ""
            await selectThinkingLevel(level)
            commandFeedback = "思考强度已调整为 \(level)"
        case "/permission":
            let mode: String
            switch argument.lowercased() {
            case "assistant", "safe", "controlled", "受控": mode = "assistant"
            case "coordinator", "sandbox", "协调": mode = "coordinator"
            default:
                commandFeedback = "用法：/permission assistant 或 /permission coordinator"
                return
            }
            draft = ""
            await switchSessionMode(mode)
            commandFeedback = mode == "coordinator" ? "已切换为运行协调模式" : "已切换为受控模式"
        case "/help":
            draft = ""
            commandFeedback = "/new /model /thinking /permission /compact /memory /read /stop"
        default:
            commandFeedback = "未知命令。输入 /help 查看可用命令"
        }
    }

    private func imageMimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "gif": return "image/gif"
        case "webp": return "image/webp"
        default: return "application/octet-stream"
        }
    }

    func abort() async {
        guard !selectedSessionId.isEmpty else { return }
        do {
            _ = try await api.abort(sessionId: selectedSessionId)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func decideApproval(_ approval: AgentApproval, approved: Bool) async {
        guard approval.state == "pending", approvalActionId.isEmpty else { return }
        approvalActionId = approval.approvalId
        defer { approvalActionId = "" }
        do {
            let response = try await api.decideApproval(
                id: approval.approvalId,
                payloadSha256: approval.payloadSha256,
                approved: approved
            )
            replaceApproval(response.approval)
            if response.approval.state == "external_pending" {
                let finalized = try await resumeExternalApproval(response.approval)
                replaceApproval(finalized)
            }
            errorMessage = ""
        } catch {
            errorMessage = error.localizedDescription
            await reloadApprovals()
        }
    }

    func continueExternalApproval(_ approval: AgentApproval) async {
        guard approval.state == "external_pending", approvalActionId.isEmpty else { return }
        approvalActionId = approval.approvalId
        defer { approvalActionId = "" }
        do {
            let finalized = try await resumeExternalApproval(approval)
            replaceApproval(finalized)
            errorMessage = ""
        } catch {
            errorMessage = error.localizedDescription
            await reloadApprovals()
        }
    }

    private func resumeExternalApproval(_ approval: AgentApproval) async throws -> AgentApproval {
        try await waitForPiTurnToFinish(sessionId: approval.sessionId)

        // A previous launchctl run may already have restarted Sidecar while the
        // final receipt POST was interrupted. Let the new process close the
        // durable receipt without causing a second restart.
        if let recovered = try? await api.finalizeExternalApproval(
            approval: approval,
            succeeded: true,
            exitCode: 0,
            timedOut: false
        ) {
            return recovered.approval
        }

        let receipt = approval.receipt?.objectValue ?? [:]
        let action = receipt["externalAction"]?.stringValue ?? ""
        guard ["restart_sidecar", "restore_backup"].contains(action) else {
            throw APIClientError.server(409, "当前外部审批动作不受控制中心监督器支持")
        }
        guard case .array(let values)? = receipt["externalCommand"] else {
            throw ExternalRuntimeSupervisorError.missingCommand(action)
        }
        var command: [String] = []
        for value in values {
            guard case .string(let argument) = value else {
                throw ExternalRuntimeSupervisorError.rejectedCommand("externalCommand 必须是纯字符串数组")
            }
            command.append(argument)
        }

        let execution = try await ExternalRuntimeSupervisor.execute(
            action: action,
            command: command,
            timeoutSeconds: action == "restore_backup" ? 180 : 90,
            expectedPlanSha256: action == "restore_backup"
                ? receipt["externalPlanSha256"]?.stringValue
                : nil
        )
        guard execution.succeeded else {
            // A restore helper may have committed the database and restarted a
            // new Sidecar even if its final process exit was interrupted. Ask
            // the new process to verify the durable result before recording a
            // failed receipt that could misrepresent an applied restore.
            if action == "restore_backup",
               let recovered = try? await api.finalizeExternalApproval(
                   approval: approval,
                   succeeded: true,
                   exitCode: 0,
                   timedOut: false
               ) {
                return recovered.approval
            }
            let error = execution.timedOut
                ? "外部监督器执行超时"
                : "外部监督器退出码 \(execution.exitCode)"
            let failed = try await api.finalizeExternalApproval(
                approval: approval,
                succeeded: false,
                exitCode: execution.exitCode,
                timedOut: execution.timedOut,
                error: error
            )
            return failed.approval
        }

        var lastError: Error = APIClientError.server(503, "等待新 Sidecar 确认重启回执")
        for _ in 0..<120 {
            do {
                let finalized = try await api.finalizeExternalApproval(
                    approval: approval,
                    succeeded: true,
                    exitCode: execution.exitCode,
                    timedOut: false
                )
                return finalized.approval
            } catch {
                lastError = error
                try await Task.sleep(for: .milliseconds(250))
            }
        }
        throw lastError
    }

    private func waitForPiTurnToFinish(sessionId: String) async throws {
        for attempt in 0..<480 {
            if selectedSessionId == sessionId, ["idle", "failed"].contains(conversation.status) {
                return
            }
            if attempt.isMultiple(of: 4) {
                let response = try await api.sessions(includeArchived: true)
                if let session = response.items.first(where: { $0.id == sessionId }),
                   ["idle", "faulted", "archived"].contains(session.status) {
                    return
                }
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw APIClientError.server(
            409,
            "Pi 当前回合尚未结束；重启仍处于待执行状态，可稍后点击继续执行"
        )
    }

    func reloadApprovals() async {
        guard !selectedSessionId.isEmpty else {
            approvals = []
            return
        }
        do {
            let response = try await api.approvals(sessionId: selectedSessionId)
            approvals = response.items
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func suspendStream() {
        modelCatalogTask?.cancel()
        modelCatalogTask = nil
        deltaFlushTask?.cancel()
        deltaFlushTask = nil
        _ = flushBufferedTextDeltas()
        streamTask?.cancel()
        streamTask = nil
    }

    func stop() {
        suspendStream()
        Task { await api.invalidate() }
    }

    private func loadConversationAndStream(expectedSessionId: String? = nil) async {
        let sessionId = expectedSessionId ?? selectedSessionId
        guard !sessionId.isEmpty, selectedSessionId == sessionId else { return }
        do {
            async let messageRequest = api.messages(sessionId: sessionId)
            async let approvalRequest = api.approvals(sessionId: sessionId)
            async let memorySourceRequest = api.memorySources(sessionId: sessionId)
            async let runtimeRequest = api.runtimeStatus()
            let (response, approvalResponse, memorySourceResponse, runtimeStatus) = try await (
                messageRequest,
                approvalRequest,
                memorySourceRequest,
                runtimeRequest
            )
            guard selectedSessionId == sessionId, !Task.isCancelled else { return }
            AgentConversationReducer.replaceMessages(
                state: &conversation,
                messages: response.items,
                lastSequence: response.lastSequence,
                resumeToken: response.resumeToken
            )
            bufferedTextDeltaEvents.removeAll(keepingCapacity: true)
            approvals = approvalResponse.items
            memorySources = memorySourceResponse.items
            runtime = runtimeStatus
            await reloadMemoryMaintenance()
            guard selectedSessionId == sessionId, !Task.isCancelled else { return }
            startStream(sessionId: sessionId)
            scheduleModelCatalogLoad(sessionId: sessionId)
            errorMessage = ""
        } catch {
            guard selectedSessionId == sessionId else { return }
            errorMessage = error.localizedDescription
        }
    }

    private func startStream(sessionId: String) {
        suspendStream()
        streamTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.selectedSessionId == sessionId else { return }
                let resumeToken = self.conversation.lastEventId
                do {
                    try await self.api.streamEvents(
                        sessionId: sessionId,
                        afterEventId: resumeToken
                    ) { [weak self] event in
                        await self?.receive(event, expectedSessionId: sessionId)
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

    private func scheduleModelCatalogLoad(sessionId: String) {
        modelCatalogTask?.cancel()
        modelCatalogTask = Task { [weak self] in
            await self?.reloadModelCatalog(sessionId: sessionId)
        }
    }

    private func reloadModelCatalog(sessionId: String) async {
        guard selectedSessionId == sessionId else { return }
        do {
            let response = try await api.models(sessionId: sessionId)
            guard selectedSessionId == sessionId, !Task.isCancelled else { return }
            modelCatalog = response
        } catch is CancellationError {
            return
        } catch {
            // The transcript remains usable if Pi cannot enumerate models.
            guard selectedSessionId == sessionId else { return }
            modelCatalog = nil
        }
    }

    private func receive(_ event: AgentEventEnvelope, expectedSessionId: String) async {
        guard selectedSessionId == expectedSessionId, event.sessionId == expectedSessionId else { return }

        if event.eventType == .textDelta {
            bufferedTextDeltaEvents.append(event)
            scheduleTextDeltaFlush(sessionId: expectedSessionId)
            return
        }

        let bufferedReduction = flushBufferedTextDeltas()
        if bufferedReduction == .reloadSnapshot {
            await reloadConversationSnapshot(sessionId: expectedSessionId)
        }
        let reduction = AgentConversationReducer.reduce(state: &conversation, event: event)
        if reduction == .reloadSnapshot {
            await reloadConversationSnapshot(sessionId: expectedSessionId)
        }
        if event.eventType == .turnCompleted || event.eventType == .turnFailed {
            await reloadSessions()
            runtime = try? await api.runtimeStatus()
        }
        if event.eventType == .approvalRequired || event.eventType == .approvalResolved {
            await reloadApprovals()
        }
        if event.eventType == .memoryCheckpointed {
            await reloadMemorySources()
            await reloadMemoryMaintenance()
        }
        if event.eventType == .memoryMaintenanceUpdated {
            await reloadMemoryMaintenance()
        }
    }

    private func scheduleTextDeltaFlush(sessionId: String) {
        guard deltaFlushTask == nil else { return }
        deltaFlushTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: self?.deltaFlushNanoseconds ?? 16_666_667)
            } catch {
                return
            }
            guard let self, self.selectedSessionId == sessionId else { return }
            self.deltaFlushTask = nil
            let reduction = self.flushBufferedTextDeltas()
            if reduction == .reloadSnapshot {
                await self.reloadConversationSnapshot(sessionId: sessionId)
            }
        }
    }

    @discardableResult
    private func flushBufferedTextDeltas() -> AgentConversationReduction {
        guard !bufferedTextDeltaEvents.isEmpty else { return .ignored }
        let events = bufferedTextDeltaEvents
        bufferedTextDeltaEvents.removeAll(keepingCapacity: true)
        var next = conversation
        var result: AgentConversationReduction = .ignored
        for event in events {
            let reduction = AgentConversationReducer.reduce(state: &next, event: event)
            if reduction == .reloadSnapshot {
                result = .reloadSnapshot
                break
            }
            if reduction == .applied { result = .applied }
        }
        // `AgentConversationState ==` walks the full transcript. A delta batch
        // already tells us whether it changed state, so avoid an O(history)
        // comparison on every display update.
        if result != .ignored { conversation = next }
        return result
    }

    private func reloadConversationSnapshot(sessionId: String) async {
        guard selectedSessionId == sessionId else { return }
        do {
            let response = try await api.messages(sessionId: sessionId)
            AgentConversationReducer.replaceMessages(
                state: &conversation,
                messages: response.items,
                lastSequence: response.lastSequence,
                resumeToken: response.resumeToken
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func replaceApproval(_ approval: AgentApproval) {
        if let index = approvals.firstIndex(where: { $0.approvalId == approval.approvalId }) {
            approvals[index] = approval
        } else {
            approvals.insert(approval, at: 0)
        }
    }

    private func reloadMemorySources() async {
        guard !selectedSessionId.isEmpty else {
            memorySources = []
            return
        }
        do {
            memorySources = try await api.memorySources(sessionId: selectedSessionId).items
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reloadMemoryMaintenance() async {
        do {
            let status = try await api.memoryMaintenance()
            memoryMaintenance = status.ok ? status : nil
        } catch {
            // Memory maintenance is an auxiliary status surface; conversation loading must remain usable.
            memoryMaintenance = nil
        }
    }
}
