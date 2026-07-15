import Foundation

struct OverviewResponse: Decodable {
    let schemaVersion: String
    let settingsRevision: String
    let runtimeRevision: Int
    let ok: Bool
    let profile: String
    let aiPaused: Bool
    let components: [String: ComponentStatus]
    let canonicalSquirrel: CanonicalSquirrel
    let memory: MemorySummary
    let lastPrediction: LastPrediction
}

struct CanonicalSquirrel: Decodable {
    let ok: Bool
    let path: String
    let duplicateSystemBundle: Bool
}

struct ComponentStatus: Decodable, Identifiable {
    let id: String
    let ok: Bool
    let status: String
    let detail: String
}

struct MemorySummary: Decodable {
    let eventCount: Int
    let memoryItemCount: Int
    let memoryBookCount: Int
    let memoryAtomCount: Int
    let retrievalDocCount: Int
    let pendingCompileEvents: Int
}

struct PlanningDashboardResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let date: String
    let plan: PlanningPlanItem
    let tasks: [PlanningTaskItem]
    let goals: [PlanningGoalItem]
    let pendingCompletionSuggestions: [PlanningCompletionSuggestion]
    let recentDetectedCompletion: PlanningDetectedCompletion?
    let conversation: [PlanningConversationMessage]
    let summary: PlanningSummary
    let assistant: PlanningAssistantSummary
}

struct PlanningDetectedCompletion: Decodable {
    let eventId: String
    let sourceEventId: Int
    let createdAtMs: Int
    let task: PlanningTaskItem
    let message: String
    let undoAvailable: Bool
}

struct PlanningPlanItem: Decodable {
    let id: String
    let date: String
    let project: String
    let intention: String
    let notes: String
    let reflection: String
    let assistantSummary: String
}

struct PlanningTaskItem: Decodable, Identifiable {
    let id: String
    let date: String
    let title: String
    let detail: String
    let status: String
    let priority: Int
    let dueAtMs: Int?
    let project: String
    let goalId: String
    let source: String
    let confidence: Double
    let completedAtMs: Int?
}

struct PlanningGoalItem: Decodable, Identifiable {
    let id: String
    let title: String
    let detail: String
    let horizon: String
    let status: String
    let priority: Int
    let targetDate: String
    let project: String
    let completedAtMs: Int?
}

struct PlanningCompletionSuggestion: Decodable, Identifiable {
    let id: String
    let sourceEventId: Int?
    let candidateTasks: [PlanningTaskItem]
    let createdAtMs: Int
}

struct PlanningConversationMessage: Decodable, Identifiable {
    let id: String
    let role: String
    let content: String
    let createdAtMs: Int
}

struct PlanningSummary: Decodable {
    let taskCount: Int
    let openTaskCount: Int
    let completedTaskCount: Int
    let goalCount: Int
    let progress: Double
}

struct PlanningAssistantSummary: Decodable {
    let message: String
    let tone: String
}

struct PlanningMutationResponse: Decodable {
    let ok: Bool
    let task: PlanningTaskItem?
    let goal: PlanningGoalItem?
    let eventId: String?
    let undoAvailable: Bool?
    let error: String?
}

struct PlanningAssistantResponse: Decodable {
    let ok: Bool
    let reply: String
    let dashboard: PlanningDashboardResponse
    let modelUsed: Bool
}

struct ConfigurationPreviewResponse: Decodable {
    let ok: Bool
    let valid: Bool
    let errors: [String]
    let warnings: [String]
    let settingCount: Int
    let providers: [String: JSONValue]
    let requiresRemoteModelConfirmation: Bool
    let secretsEchoed: Bool
}

struct PortableBackupResponse: Decodable {
    let ok: Bool
    let path: String
    let sizeBytes: Int
    let rimeFileCount: Int
    let secretsIncluded: Bool
}

struct PortableRestorePreviewResponse: Decodable {
    let ok: Bool
    let valid: Bool
    let path: String
    let restoreToken: String
    let createdAtMs: Int
    let databaseCounts: [String: Int]
    let databaseMigrationVersion: Int
    let rimeFileCount: Int
    let exclusions: [String]
    let requiresConfirmation: String
    let requiresRestart: Bool
}

struct PortableRestoreApplyResponse: Decodable {
    let ok: Bool
    let path: String
    let rollbackPath: String
    let databaseCounts: [String: Int]
    let requiresRestart: Bool
    let secretsChanged: Bool
}

struct LastPrediction: Decodable {
    var triggerReason: String?
    var contextSource: String?
    var visibleCandidate: String?
    var totalLatencyMs: Double?
    var providerCallCount: Int?
    var sourceTypes: [String]?
}

struct RuntimeResponse: Decodable {
    let settingsRevision: String
    let runtimeRevision: Int
    let ok: Bool
    let components: [String: ComponentStatus]
}

struct SettingsSchemaResponse: Decodable {
    let schemaVersion: String
    let sections: [SettingsSection]
    let defaults: JSONValue
}

struct SettingsSection: Decodable, Identifiable {
    let id: String
    let label: String
    let fields: [SettingsField]
}

struct SettingsField: Decodable, Identifiable {
    var id: String { key }
    let key: String
    let type: String
    let label: String
    let description: String
    let applyMode: String
    let risk: String
    let expert: Bool
    let min: Double?
    let max: Double?
    let step: Double?
    let unit: String
    let restartComponent: String
    let options: [String]?
    let `default`: JSONValue
}

struct SettingsResponse: Decodable {
    let settings: JSONValue
    let settingsRevision: String?
    let runtimeRevision: Int?
}

struct MutationResponse: Decodable {
    let ok: Bool
    let settingsRevision: String?
    let runtimeRevision: Int?
    let auditId: Int?
    let jobId: String?
    let error: String?
}

struct ProviderConfigurationResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let configurationHash: String
    let providers: ProviderConfigurationSlots
}

struct ProviderConfigurationSlots: Decodable {
    let instant: ProviderConfigurationSlot
    let knowledge: ProviderConfigurationSlot
    let voice: ProviderConfigurationSlot
    let secretsIncluded: Bool
}

struct ProviderConfigurationSlot: Decodable {
    let provider: String
    let endpoint: String?
    let model: String?
}

struct ProviderConfigurationApplyResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let configurationHash: String
    let slot: String
    let after: ProviderConfigurationSlot
    let requiresRestart: Bool
    let restartComponent: String
    let secretsEchoed: Bool
    let existingSecretPreserved: Bool
}

struct PageResponse: Decodable {
    let ok: Bool
    let items: [[String: JSONValue]]
    let nextCursor: String
    let limit: Int
}

struct MemoryGraphResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let asOfMs: Int
    let query: String
    let entities: [MemoryGraphEntity]
    let relations: [MemoryGraphRelation]
    let summary: MemoryGraphSummary
    let filters: MemoryGraphFilters
}

struct MemoryGraphEntity: Decodable, Identifiable, Equatable {
    var id: String { entityId }
    let entityId: String
    let entityType: String
    let canonicalName: String
    let description: String
    let aliases: [String]
    let ownerKind: String
    let ownerId: String
    let project: String
    let status: String
    let revision: Int
    let confidence: Double
    let createdAtMs: Int
    let updatedAtMs: Int
    let sources: [MemoryGraphSourceRef]
    let relationCount: Int
}

struct MemoryGraphRelation: Decodable, Identifiable, Equatable {
    var id: String { relationId }
    let relationId: String
    let sourceEntityId: String
    let targetEntityId: String
    let sourceName: String
    let targetName: String
    let sourceType: String
    let targetType: String
    let relationType: String
    let fact: String
    let ownerKind: String
    let ownerId: String
    let project: String
    let validFromMs: Int
    let validToMs: Int?
    let status: String
    let revision: Int
    let confidence: Double
    let createdAtMs: Int
    let updatedAtMs: Int
    let sources: [MemoryGraphSourceRef]
    let sourceCount: Int
}

struct MemoryGraphSourceRef: Decodable, Equatable {
    let sourceType: String
    let sourceId: String
    let sourceRevision: Int
}

struct MemoryGraphSummary: Decodable {
    let visibleEntityCount: Int
    let visibleRelationCount: Int
    let evidenceCount: Int
    let projectionPendingCount: Int
}

struct MemoryGraphFilters: Decodable {
    let entityTypes: [MemoryGraphFilterOption]
    let ownerKinds: [String]
}

struct MemoryGraphFilterOption: Decodable, Identifiable {
    var id: String { value }
    let value: String
    let count: Int
}

struct MemoryGraphSourcesResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sources: [MemoryGraphEvidence]
    let count: Int
}

struct MemoryGraphEvidence: Decodable, Identifiable {
    var id: String { "\(sourceType):\(sourceId):\(sourceRevision)" }
    let sourceType: String
    let sourceId: String
    let sourceRevision: Int
    let text: String
    let createdAtMs: Int
    let project: String
    let app: String
    let relationIds: [String]
}

struct RimeLexiconReviewResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let project: String
    let entryCount: Int
    let entries: [RimeLexiconReviewEntry]
    let reviewToken: String
    let confirmText: String
    let applySupported: Bool
    let reviewRequired: Bool
}

struct RimeLexiconReviewEntry: Decodable, Identifiable {
    var id: String { reviewKey }
    let reviewKey: String
    let text: String
    let pinyin: String
    let weight: Int
    let positiveCount: Int
    let negativeCount: Int
    let lastUsedAtMs: Int
    let reasons: [String]
    let reviewSource: String?
    let reviewReason: String?
    let selected: Bool
}

struct RimeLexiconMutationResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let applied: Bool?
    let rolledBack: Bool?
    let entryCount: Int?
    let rollbackId: String?
    let requiresRedeploy: Bool?
    let reason: String?
    let confirmText: String?
}

struct QueryLabResponse: Decodable {
    let ok: Bool
    let candidates: [[String: JSONValue]]?
    let blocked: [[String: JSONValue]]?
    let error: String?
}

enum KnowledgeWorkbenchMode: String, CaseIterable, Identifiable {
    case knowledgeAnswer = "knowledge_answer"
    case longForm = "long_form"
    case recall
    case organizeDatabase = "organize_database"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .knowledgeAnswer: return "知识问答"
        case .longForm: return "长文生成"
        case .recall: return "帮我回忆"
        case .organizeDatabase: return "整理数据库"
        }
    }

    var symbol: String {
        switch self {
        case .knowledgeAnswer: return "text.magnifyingglass"
        case .longForm: return "doc.text"
        case .recall: return "clock.arrow.trianglehead.counterclockwise.rotate.90"
        case .organizeDatabase: return "cylinder.split.1x2"
        }
    }

    var maxChars: Double {
        switch self {
        case .knowledgeAnswer, .longForm, .recall, .organizeDatabase: return 0
        }
    }
}

struct KnowledgeWorkbenchResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String?
    let queryId: String?
    let status: String
    let stage: String?
    let mode: String?
    let generation: Int?
    let contextHash: String?
    let answer: String?
    let localDraft: String?
    let sources: [[String: JSONValue]]?
    let evidence: [[String: JSONValue]]?
    let notion: JSONValue?
    let result: JSONValue?
    let diagnostics: JSONValue?
    let error: String?
}

struct KnowledgeRouteResponse: Decodable {
    let schemaVersion: String
    let deepseekReady: Bool
    let defaultOrganizationInstruction: String?
    let notion: NotionRouteStatus
}

struct KnowledgeDatabaseActionResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let action: String?
    let run: JSONValue?
    let error: String?
}

struct NotionRouteStatus: Decodable {
    let submitConfigured: Bool
    let pollConfigured: Bool
    let ready: Bool
    let pollMode: String
    let missing: [String]?
}

enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value") }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var stringValue: String {
        switch self {
        case .string(let value): return value
        case .number(let value): return value.rounded() == value ? String(Int(value)) : String(value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return ""
        case .array(let value): return value.map(\.stringValue).joined(separator: ", ")
        case .object: return ""
        }
    }

    var boolValue: Bool {
        if case .bool(let value) = self { return value }
        return false
    }

    var numberValue: Double {
        if case .number(let value) = self { return value }
        return 0
    }

    var objectValue: [String: JSONValue] {
        if case .object(let value) = self { return value }
        return [:]
    }

    var arrayValue: [JSONValue] {
        if case .array(let value) = self { return value }
        return []
    }
}

extension JSONValue {
    func value(at dottedKey: String) -> JSONValue? {
        var current = self
        for part in dottedKey.split(separator: ".").map(String.init) {
            guard case .object(let object) = current, let next = object[part] else { return nil }
            current = next
        }
        return current
    }
}

struct TableRow: Identifiable {
    let id: String
    let values: [String]

    init(index: Int, payload: [String: JSONValue], columns: [String]) {
        id = payload["id"]?.stringValue ?? payload["bookId"]?.stringValue ?? "row-\(index)-\(payload.hashDescription)"
        values = columns.map { payload[$0]?.stringValue ?? "" }
    }
}

private extension Dictionary where Key == String, Value == JSONValue {
    var hashDescription: String {
        keys.sorted().map { "\($0)=\(self[$0]?.stringValue ?? "")" }.joined(separator: "|")
    }
}
