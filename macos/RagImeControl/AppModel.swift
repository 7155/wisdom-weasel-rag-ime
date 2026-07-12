import AppKit
import Foundation

@MainActor
final class AppModel: ObservableObject {
    @Published var destination: ControlDestination = .overview {
        didSet { Task { await loadDestination() } }
    }
    @Published var overview: OverviewResponse?
    @Published var runtime: RuntimeResponse?
    @Published var schemaSections: [SettingsSection] = []
    @Published var settings: JSONValue = .object([:])
    @Published var connected = false
    @Published var loading = false
    @Published var expertMode = false
    @Published var pendingApplyModes: Set<String> = []
    @Published var memoryKind = "books"
    @Published var memoryRows: [[String: JSONValue]] = []
    @Published var memoryNextCursor = ""
    @Published var memorySaving = false
    @Published var historyRows: [[String: JSONValue]] = []
    @Published var historyNextCursor = ""
    @Published var rimeLexiconReview: RimeLexiconReviewResponse?
    @Published var selectedRimeLexiconKeys: Set<String> = []
    @Published var rimeLexiconRollbackId = ""
    @Published var rimeLexiconStatus = ""
    @Published var rimeLexiconBusy = false
    @Published var queryLabText = ""
    @Published var queryLabResult: QueryLabResponse?
    @Published var knowledgeMode: KnowledgeWorkbenchMode = .knowledgeAnswer
    @Published var knowledgeQuestion = ""
    @Published var knowledgeOrganizationInstruction = ""
    @Published var knowledgeContext = ""
    @Published var knowledgeIncludeNotion = false
    @Published var knowledgeResponse: KnowledgeWorkbenchResponse?
    @Published var knowledgeDraftRun: JSONValue?
    @Published var knowledgeRoute: KnowledgeRouteResponse?
    @Published var knowledgeRunning = false
    @Published var knowledgeDatabaseActionStatus = ""
    @Published var lastRuntimeActionReport = ""
    @Published var showingRuntimeActionReport = false
    @Published var errorMessage = ""
    @Published var showingError = false

    let api = ManagementAPIClient()
    private lazy var schemaClient = SettingsSchemaClient(api: api)
    private var eventTask: Task<Void, Never>?
    private var knowledgeGeneration = 0

    func start() async {
        guard eventTask == nil else { return }
        await refreshAll()
        eventTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                do {
                    try await api.streamEvents { [weak self] _ in
                        await self?.refreshOverview()
                    }
                } catch is CancellationError {
                    return
                } catch {
                    try? await Task.sleep(for: .seconds(2))
                }
            }
        }
    }

    func stop() {
        eventTask?.cancel()
        eventTask = nil
        Task { await api.invalidate() }
    }

    func refreshAll() async {
        loading = true
        defer { loading = false }
        do {
            async let overviewRequest: OverviewResponse = api.get("api/overview")
            async let schemaRequest = schemaClient.load()
            let (overview, loadedSchema) = try await (overviewRequest, schemaRequest)
            self.overview = overview
            self.schemaSections = loadedSchema.0.sections
            self.settings = loadedSchema.1.settings
            connected = true
            await loadDestination()
        } catch {
            connected = false
            present(error)
        }
    }

    func refreshOverview() async {
        do {
            let response: OverviewResponse = try await api.get("api/overview")
            overview = response
            connected = true
        } catch {
            connected = false
        }
    }

    func sections(ids: Set<String>) -> [SettingsSection] {
        schemaSections.filter { ids.contains($0.id) }
    }

    func value(for field: SettingsField) -> JSONValue {
        settings.value(at: field.key) ?? field.default
    }

    func update(field: SettingsField, value: JSONValue) async {
        do {
            let response = try await schemaClient.update(key: field.key, value: value)
            guard response.ok else { throw APIClientError.server(400, response.error ?? "设置未应用") }
            settings = setting(settings, key: field.key, value: value)
            if field.applyMode != "live" {
                pendingApplyModes.insert(field.applyMode)
            }
            await refreshOverview()
        } catch {
            present(error)
        }
    }

    func run(action: String) async {
        do {
            let response: MutationResponse = try await api.post("api/runtime/action", body: ["action": .string(action)])
            guard response.ok else { throw APIClientError.server(400, response.error ?? "操作未启动") }
            guard let jobId = response.jobId, !jobId.isEmpty else {
                throw APIClientError.server(500, "运行时操作没有返回 jobId")
            }
            try await waitForRuntimeJob(jobId, expectedAction: action)
            pendingApplyModes.removeAll()
            await refreshOverview()
        } catch {
            await refreshOverview()
            present(error)
        }
    }

    func toggleAI() async {
        await run(action: overview?.aiPaused == true ? "resume_ai" : "stop_ai")
    }

    func applyProfile(_ profile: String) async {
        let updates: [String: JSONValue]
        switch profile {
        case "安全模式":
            updates = [
                "interaction.postCommit.enabled": .bool(false),
                "memory.enabled": .bool(false),
                "activeRag.allowRemoteModel": .bool(false),
            ]
        case "标准模式":
            updates = [
                "interaction.postCommit.enabled": .bool(true),
                "memory.enabled": .bool(true),
                "rag.lanes.tagMemo": .bool(true),
                "rag.lanes.timeDailyBook": .bool(true),
            ]
        case "调试模式":
            updates = [
                "interaction.postCommit.enabled": .bool(true),
                "diagnostics.liveTrace": .bool(true),
                "diagnostics.candidateExplain": .bool(true),
                "display.showDiagnosticsInline": .bool(true),
            ]
        default:
            updates = [
                "interaction.postCommit.enabled": .bool(true),
                "memory.enabled": .bool(true),
                "rag.lanes.tagMemo": .bool(true),
                "rag.lanes.timeDailyBook": .bool(true),
            ]
        }
        do {
            let response: MutationResponse = try await api.post("api/settings/update", body: updates.merging(["updatedBy": .string("native-control-center")]) { _, new in new })
            guard response.ok else { throw APIClientError.server(400, response.error ?? "模式切换失败") }
            let loaded = try await schemaClient.load()
            settings = loaded.1.settings
            await refreshOverview()
        } catch {
            present(error)
        }
    }

    func loadMemory(reset: Bool = true) async {
        do {
            let cursor = reset ? "" : memoryNextCursor
            let response: PageResponse = try await api.get(
                "api/memory/\(memoryKind)",
                query: [URLQueryItem(name: "limit", value: "50"), URLQueryItem(name: "cursor", value: cursor)]
            )
            memoryRows = reset ? response.items : memoryRows + response.items
            memoryNextCursor = response.nextCursor
        } catch {
            present(error)
        }
    }

    func editMemoryItem(
        kind: String,
        id: String,
        title: String,
        detail: String,
        tags: [String],
        aliases: [String],
        type: String,
        color: String,
        active: Bool,
        mergeIntoId: String
    ) async -> Bool {
        memorySaving = true
        defer { memorySaving = false }
        do {
            let response: MutationResponse = try await api.post(
                "api/memory/edit",
                body: [
                    "kind": .string(kind),
                    "id": .string(id),
                    "title": .string(title),
                    "text": .string(detail),
                    "summary": .string(detail),
                    "note": .string(detail),
                    "tags": .array(tags.map(JSONValue.string)),
                    "aliases": .array(aliases.map(JSONValue.string)),
                    "type": .string(type),
                    "color": .string(color),
                    "active": .bool(active),
                    "mergeIntoId": .string(mergeIntoId),
                ]
            )
            guard response.ok else { throw APIClientError.server(400, response.error ?? "记忆保存失败") }
            await loadMemory()
            await refreshOverview()
            return true
        } catch {
            present(error)
            return false
        }
    }

    func performMemoryAction(id: String, kind: String, action: String) async -> Bool {
        memorySaving = true
        defer { memorySaving = false }
        do {
            let itemType: String
            switch kind {
            case "books": itemType = "book"
            case "atoms": itemType = "atom"
            case "phrases": itemType = "phrase"
            default: itemType = "memory"
            }
            let response: MutationResponse = try await api.post(
                "api/memory/action",
                body: [
                    "memoryId": .string(id),
                    "itemType": .string(itemType),
                    "action": .string(action),
                    "reason": .string("native_control_center_\(action)"),
                    "updatedBy": .string("native-control-center"),
                ]
            )
            guard response.ok else { throw APIClientError.server(400, response.error ?? "记忆操作失败") }
            await loadMemory()
            await refreshOverview()
            return true
        } catch {
            present(error)
            return false
        }
    }

    func loadHistory(reset: Bool = true) async {
        do {
            let cursor = reset ? "" : historyNextCursor
            let response: PageResponse = try await api.get(
                "api/history/page",
                query: [URLQueryItem(name: "limit", value: "50"), URLQueryItem(name: "cursor", value: cursor)]
            )
            historyRows = reset ? response.items : historyRows + response.items
            historyNextCursor = response.nextCursor
        } catch {
            present(error)
        }
    }

    func loadRimeLexiconReview() async {
        do {
            let response: RimeLexiconReviewResponse = try await api.get(
                "api/rime-lexicon/review",
                query: [URLQueryItem(name: "limit", value: "200")]
            )
            rimeLexiconReview = response
            selectedRimeLexiconKeys = Set(response.entries.filter(\.selected).map(\.reviewKey))
            rimeLexiconStatus = response.entries.isEmpty ? "暂无待审建议" : "待审 \(response.entryCount) 条"
        } catch {
            present(error)
        }
    }

    func setRimeLexiconSelection(_ key: String, selected: Bool) {
        if selected {
            selectedRimeLexiconKeys.insert(key)
        } else {
            selectedRimeLexiconKeys.remove(key)
        }
    }

    func applyRimeLexiconReview() async {
        guard let review = rimeLexiconReview, !selectedRimeLexiconKeys.isEmpty else { return }
        rimeLexiconBusy = true
        defer { rimeLexiconBusy = false }
        do {
            let response: RimeLexiconMutationResponse = try await api.post(
                "api/rime-lexicon/apply",
                body: [
                    "reviewToken": .string(review.reviewToken),
                    "selectedKeys": .array(selectedRimeLexiconKeys.sorted().map(JSONValue.string)),
                    "confirmText": .string(review.confirmText),
                    "project": .string(review.project),
                ]
            )
            guard response.ok, response.applied == true else {
                throw APIClientError.server(409, response.reason ?? "词库建议已变化，请刷新后重试")
            }
            let appliedCount = response.entryCount ?? selectedRimeLexiconKeys.count
            rimeLexiconRollbackId = response.rollbackId ?? ""
            if response.requiresRedeploy == true { await run(action: "redeploy_rime") }
            await loadRimeLexiconReview()
            let remainingCount = rimeLexiconReview?.entryCount ?? 0
            rimeLexiconStatus = "已应用 \(appliedCount) 条 · 剩余 \(remainingCount) 条"
        } catch {
            present(error)
        }
    }

    func rollbackRimeLexiconReview() async {
        guard !rimeLexiconRollbackId.isEmpty else { return }
        rimeLexiconBusy = true
        defer { rimeLexiconBusy = false }
        do {
            let response: RimeLexiconMutationResponse = try await api.post(
                "api/rime-lexicon/rollback",
                body: ["rollbackId": .string(rimeLexiconRollbackId)]
            )
            guard response.ok, response.rolledBack == true else {
                throw APIClientError.server(409, response.reason ?? "词库回滚失败")
            }
            rimeLexiconRollbackId = ""
            if response.requiresRedeploy == true { await run(action: "redeploy_rime") }
            await loadRimeLexiconReview()
            rimeLexiconStatus = "已回滚 · 待审 \(rimeLexiconReview?.entryCount ?? 0) 条"
        } catch {
            present(error)
        }
    }

    func runQueryLab() async {
        let text = queryLabText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        do {
            queryLabResult = try await api.post(
                "api/rag-core-v3/query-preview",
                body: ["query": .string(text), "recentContext": .string(text), "project": .string("wisdom-weasel-rag-ime"), "topK": .number(8)]
            )
        } catch {
            present(error)
        }
    }

    func loadKnowledgeRoute() async {
        do {
            let response: KnowledgeRouteResponse = try await api.get("api/knowledge/route-status")
            knowledgeRoute = response
            if knowledgeOrganizationInstruction.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                knowledgeOrganizationInstruction = response.defaultOrganizationInstruction ?? ""
            }
        } catch {
            knowledgeRoute = nil
        }
    }

    func runKnowledgeWorkbench() async {
        let questionSource = knowledgeMode == .organizeDatabase
            ? knowledgeOrganizationInstruction
            : knowledgeQuestion
        let question = questionSource.trimmingCharacters(in: .whitespacesAndNewlines)
        guard knowledgeMode == .organizeDatabase || !question.isEmpty else { return }
        knowledgeGeneration += 1
        let generation = knowledgeGeneration
        if knowledgeMode == .organizeDatabase {
            knowledgeDatabaseActionStatus = ""
            knowledgeDraftRun = nil
        }
        knowledgeRunning = true
        defer {
            if generation == knowledgeGeneration { knowledgeRunning = false }
        }
        do {
            let started: KnowledgeWorkbenchResponse = try await api.post(
                "api/knowledge/start",
                body: [
                    "question": .string(question),
                    "context": .string(knowledgeContext.trimmingCharacters(in: .whitespacesAndNewlines)),
                    "mode": .string(knowledgeMode.rawValue),
                    "includeNotion": .bool(knowledgeIncludeNotion),
                    "generation": .number(Double(generation)),
                    "clientId": .string("native-control-center"),
                    "project": .string("wisdom-weasel-rag-ime"),
                    "app": .string("com.rag-ime.control"),
                    "maxChars": .number(knowledgeMode.maxChars),
                    "latencyBudgetMs": .number(180_000),
                ]
            )
            knowledgeResponse = started
            captureKnowledgeDraftRun(from: started)
            guard started.ok, let sessionId = started.sessionId, !sessionId.isEmpty else {
                throw APIClientError.server(400, started.error ?? "知识任务未启动")
            }
            for _ in 0..<1_200 {
                guard generation == knowledgeGeneration else { return }
                let response: KnowledgeWorkbenchResponse = try await api.get(
                    "api/knowledge/status",
                    query: [URLQueryItem(name: "sessionId", value: sessionId)]
                )
                knowledgeResponse = response
                captureKnowledgeDraftRun(from: response)
                if ["ready", "error", "cancelled", "blocked"].contains(response.status) {
                    if response.status == "error" {
                        throw APIClientError.server(500, response.error ?? "知识任务失败")
                    }
                    return
                }
                try await Task.sleep(for: .milliseconds(100))
            }
            throw APIClientError.server(504, "知识任务等待超时")
        } catch is CancellationError {
            return
        } catch {
            present(error)
        }
    }

    func cancelKnowledgeWorkbench() async {
        knowledgeGeneration += 1
        knowledgeRunning = false
        guard let sessionId = knowledgeResponse?.sessionId, !sessionId.isEmpty else { return }
        do {
            let response: KnowledgeWorkbenchResponse = try await api.post(
                "api/knowledge/cancel",
                body: ["sessionId": .string(sessionId)]
            )
            knowledgeResponse = response
        } catch {
            present(error)
        }
    }

    func applyKnowledgeDatabasePlan(rollback: Bool = false) async {
        guard let runId = knowledgeResponse?.result?.objectValue["plan"]?.objectValue["runId"]?.stringValue,
              !runId.isEmpty else { return }
        let action = rollback ? "rollback" : "apply"
        do {
            let response: KnowledgeDatabaseActionResponse = try await api.post(
                "api/knowledge/database/\(action)",
                body: ["runId": .string(runId), "confirm": .string(action)]
            )
            guard response.ok else {
                throw APIClientError.server(400, response.error ?? "数据库草案操作失败")
            }
            knowledgeDatabaseActionStatus = response.run?.objectValue["status"]?.stringValue ?? action
            knowledgeDraftRun = response.run
            await refreshOverview()
        } catch {
            present(error)
        }
    }

    func updateKnowledgeDatabaseDraft(
        diffId: Int,
        payload: [String: JSONValue]? = nil,
        selected: Bool
    ) async -> Bool {
        guard let runId = knowledgeResponse?.result?.objectValue["plan"]?.objectValue["runId"]?.stringValue,
              !runId.isEmpty else { return false }
        do {
            var body: [String: JSONValue] = [
                "runId": .string(runId),
                "diffId": .number(Double(diffId)),
                "selected": .bool(selected),
            ]
            if let payload { body["payload"] = .object(payload) }
            let response: KnowledgeDatabaseActionResponse = try await api.post(
                "api/knowledge/database/draft-edit",
                body: body
            )
            guard response.ok else {
                throw APIClientError.server(400, response.error ?? "整理草案更新失败")
            }
            knowledgeDraftRun = response.run
            knowledgeDatabaseActionStatus = response.run?.objectValue["status"]?.stringValue ?? "draft"
            return true
        } catch {
            present(error)
            return false
        }
    }

    private func captureKnowledgeDraftRun(from response: KnowledgeWorkbenchResponse) {
        guard knowledgeMode == .organizeDatabase,
              let run = response.result?.objectValue["storedRun"],
              !run.objectValue.isEmpty else { return }
        knowledgeDraftRun = run
    }

    func openAccessibilitySettings() async {
        await run(action: "open_accessibility_settings")
    }

    private func loadDestination() async {
        switch destination {
        case .inputMethod: await loadRimeLexiconReview()
        case .memory: await loadMemory()
        case .history: await loadHistory()
        case .ragAndModels: await loadKnowledgeRoute()
        case .diagnostics:
            do { runtime = try await api.get("api/runtime/status") } catch { present(error) }
        default: break
        }
    }

    private func waitForRuntimeJob(_ jobId: String, expectedAction: String) async throws {
        for _ in 0..<400 {
            let response: RuntimeJobEnvelope = try await api.get("api/runtime/job/\(jobId)")
            guard response.ok, let job = response.job else {
                throw APIClientError.server(404, response.error ?? "运行时任务不存在")
            }
            switch job.status {
            case "succeeded":
                return
            case "queued", "running":
                try await Task.sleep(for: .milliseconds(250))
            case "external-supervisor-required":
                if let serverAction = job.action, serverAction != expectedAction {
                    throw APIClientError.server(409, "运行时任务 action 不匹配，拒绝执行外部命令")
                }
                let command = try externalCommand(job, action: expectedAction)
                let result = try await ExternalRuntimeSupervisor.execute(action: expectedAction, command: command)
                lastRuntimeActionReport = runtimeSupervisorReport(action: expectedAction, result: result)
                guard result.succeeded else {
                    throw APIClientError.server(
                        result.timedOut ? 504 : 500,
                        lastRuntimeActionReport
                    )
                }
                try await waitForSidecarRecovery(jobId: jobId)
                showingRuntimeActionReport = true
                return
            case "failed", "timed_out", "cancelled", "rejected":
                throw APIClientError.server(500, runtimeJobErrorMessage(job))
            default:
                throw APIClientError.server(500, "运行时任务返回未知状态：\(job.status)")
            }
        }
        throw APIClientError.server(504, "运行时任务等待超时，请查看诊断页")
    }

    private func waitForSidecarRecovery(jobId: String) async throws {
        var lastFailure = "Sidecar 暂时不可连接"
        for _ in 0..<100 {
            let health: HealthEnvelope
            do {
                health = try await api.get("api/health")
            } catch {
                lastFailure = error.localizedDescription
                try await Task.sleep(for: .milliseconds(250))
                continue
            }
            guard health.ok else {
                lastFailure = "Sidecar health 尚未恢复"
                try await Task.sleep(for: .milliseconds(250))
                continue
            }

            // Restarting Sidecar clears its in-memory job table. A missing old job is
            // therefore expected once the new process reports healthy.
            do {
                let jobResponse: RuntimeJobEnvelope = try await api.get("api/runtime/job/\(jobId)")
                guard jobResponse.ok, let recoveredJob = jobResponse.job else { return }
                switch recoveredJob.status {
                case "succeeded", "external-supervisor-required":
                    return
                case "queued", "running":
                    lastFailure = "Sidecar 已恢复，但原任务仍未终止"
                case "failed", "timed_out", "cancelled", "rejected":
                    throw RuntimeRecoveryStateError.terminal(runtimeJobErrorMessage(recoveredJob))
                default:
                    throw RuntimeRecoveryStateError.terminal("恢复后的任务状态未知：\(recoveredJob.status)")
                }
            } catch RuntimeRecoveryStateError.terminal(let message) {
                throw APIClientError.server(500, message)
            } catch {
                lastFailure = error.localizedDescription
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        throw APIClientError.server(504, "外部命令已完成，但 Sidecar 未恢复：\(lastFailure)")
    }

    private func present(_ error: Error) {
        errorMessage = error.localizedDescription
        showingError = true
    }
}

private struct RuntimeJobEnvelope: Decodable {
    let ok: Bool
    let error: String?
    let job: RuntimeJobState?
}

private struct RuntimeJobState: Decodable {
    let action: String?
    let status: String
    let error: String
    let result: [String: JSONValue]
}

private struct HealthEnvelope: Decodable {
    let ok: Bool
}

private enum RuntimeRecoveryStateError: Error {
    case terminal(String)
}

private func externalCommand(_ job: RuntimeJobState, action: String) throws -> [String] {
    guard case .array(let values)? = job.result["externalCommand"] else {
        throw ExternalRuntimeSupervisorError.missingCommand(action)
    }
    var command: [String] = []
    for value in values {
        guard case .string(let argument) = value else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("externalCommand 必须是纯字符串数组")
        }
        command.append(argument)
    }
    guard !command.isEmpty else {
        throw ExternalRuntimeSupervisorError.missingCommand(action)
    }
    return command
}

private func runtimeSupervisorReport(action: String, result: ExternalSupervisorExecutionResult) -> String {
    var details = [
        "action: \(action)",
        "exitCode: \(result.exitCode)",
        "command: \(result.command.joined(separator: " "))",
    ]
    if result.timedOut { details.append("timedOut: true") }
    details.append("stdout:\n\(result.stdout.isEmpty ? "<empty>" : result.stdout)")
    details.append("stderr:\n\(result.stderr.isEmpty ? "<empty>" : result.stderr)")
    return details.joined(separator: "\n")
}

private func runtimeJobErrorMessage(_ job: RuntimeJobState) -> String {
    var details: [String] = []
    if !job.error.isEmpty { details.append(job.error) }
    for key in ["code", "stderr", "stdout", "exitCode"] {
        guard let value = job.result[key] else { continue }
        let rendered = value.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !rendered.isEmpty { details.append("\(key): \(rendered)") }
    }
    return details.isEmpty ? "运行时任务失败（\(job.status)）" : details.joined(separator: "\n")
}

private func setting(_ root: JSONValue, key: String, value: JSONValue) -> JSONValue {
    let parts = key.split(separator: ".").map(String.init)
    guard !parts.isEmpty else { return root }

    func update(_ current: JSONValue, depth: Int) -> JSONValue {
        var object: [String: JSONValue]
        if case .object(let existing) = current { object = existing } else { object = [:] }
        let part = parts[depth]
        if depth == parts.count - 1 { object[part] = value }
        else { object[part] = update(object[part] ?? .object([:]), depth: depth + 1) }
        return .object(object)
    }

    return update(root, depth: 0)
}
