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
    @Published var historyRows: [[String: JSONValue]] = []
    @Published var historyNextCursor = ""
    @Published var queryLabText = ""
    @Published var queryLabResult: QueryLabResponse?
    @Published var errorMessage = ""
    @Published var showingError = false

    let api = ManagementAPIClient()
    private lazy var schemaClient = SettingsSchemaClient(api: api)
    private var eventTask: Task<Void, Never>?

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
            pendingApplyModes.removeAll()
            try? await Task.sleep(for: .milliseconds(350))
            await refreshOverview()
        } catch {
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
                "rag.lanes.tagMemo": .bool(false),
                "rag.lanes.timeDailyBook": .bool(false),
                "activeRag.allowRemoteModel": .bool(false),
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
                "activeRag.allowRemoteModel": .bool(false),
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

    func openAccessibilitySettings() async {
        await run(action: "open_accessibility_settings")
    }

    private func loadDestination() async {
        switch destination {
        case .memory: await loadMemory()
        case .history: await loadHistory()
        case .diagnostics:
            do { runtime = try await api.get("api/runtime/status") } catch { present(error) }
        default: break
        }
    }

    private func present(_ error: Error) {
        errorMessage = error.localizedDescription
        showingError = true
    }
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
