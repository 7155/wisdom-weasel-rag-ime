import Foundation

enum AgentEventKind: Equatable, Codable {
    case snapshot
    case textDelta
    case reasoningSummary
    case statusChanged
    case toolStarted
    case toolProgress
    case toolFinished
    case approvalRequired
    case approvalResolved
    case memoryCheckpointed
    case memoryMaintenanceUpdated
    case userInputRequired
    case messageCompleted
    case turnCompleted
    case turnFailed
    case snapshotRequired
    case heartbeat
    case unknown(String)

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = switch raw {
        case "snapshot": .snapshot
        case "text_delta": .textDelta
        case "reasoning_summary": .reasoningSummary
        case "status_changed": .statusChanged
        case "tool_started": .toolStarted
        case "tool_progress": .toolProgress
        case "tool_finished": .toolFinished
        case "approval_required": .approvalRequired
        case "approval_resolved": .approvalResolved
        case "memory_checkpointed": .memoryCheckpointed
        case "memory_maintenance_updated": .memoryMaintenanceUpdated
        case "user_input_required": .userInputRequired
        case "message_completed": .messageCompleted
        case "turn_completed": .turnCompleted
        case "turn_failed": .turnFailed
        case "snapshot_required": .snapshotRequired
        case "heartbeat": .heartbeat
        default: .unknown(raw)
        }
    }

    func encode(to encoder: Encoder) throws {
        try rawValue.encode(to: encoder)
    }

    var rawValue: String {
        switch self {
        case .snapshot: "snapshot"
        case .textDelta: "text_delta"
        case .reasoningSummary: "reasoning_summary"
        case .statusChanged: "status_changed"
        case .toolStarted: "tool_started"
        case .toolProgress: "tool_progress"
        case .toolFinished: "tool_finished"
        case .approvalRequired: "approval_required"
        case .approvalResolved: "approval_resolved"
        case .memoryCheckpointed: "memory_checkpointed"
        case .memoryMaintenanceUpdated: "memory_maintenance_updated"
        case .userInputRequired: "user_input_required"
        case .messageCompleted: "message_completed"
        case .turnCompleted: "turn_completed"
        case .turnFailed: "turn_failed"
        case .snapshotRequired: "snapshot_required"
        case .heartbeat: "heartbeat"
        case let .unknown(raw): raw
        }
    }
}

struct AgentEventEnvelope: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let eventId: String
    let sessionId: String
    let turnId: String
    let sequence: Int
    let createdAtMs: Int
    let eventType: AgentEventKind
    let payload: JSONValue
    let resumeToken: String

    var id: String { eventId }
}

enum AgentBlockKind: Equatable, Codable {
    case text
    case code
    case reasoningSummary
    case progress
    case toolCall
    case toolResult
    case citation
    case image
    case audio
    case file
    case sticker
    case taskPlan
    case diff
    case approval
    case error
    case unknown(String)

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = switch raw {
        case "text": .text
        case "code": .code
        case "reasoning_summary": .reasoningSummary
        case "progress": .progress
        case "tool_call": .toolCall
        case "tool_result": .toolResult
        case "citation": .citation
        case "image": .image
        case "audio": .audio
        case "file": .file
        case "sticker": .sticker
        case "task_plan": .taskPlan
        case "diff": .diff
        case "approval": .approval
        case "error": .error
        default: .unknown(raw)
        }
    }

    func encode(to encoder: Encoder) throws {
        try rawValue.encode(to: encoder)
    }

    var rawValue: String {
        switch self {
        case .text: "text"
        case .code: "code"
        case .reasoningSummary: "reasoning_summary"
        case .progress: "progress"
        case .toolCall: "tool_call"
        case .toolResult: "tool_result"
        case .citation: "citation"
        case .image: "image"
        case .audio: "audio"
        case .file: "file"
        case .sticker: "sticker"
        case .taskPlan: "task_plan"
        case .diff: "diff"
        case .approval: "approval"
        case .error: "error"
        case let .unknown(raw): raw
        }
    }
}

struct AgentBlock: Codable, Equatable, Identifiable {
    let id: String
    let type: AgentBlockKind
    let status: String
    let presentationKind: String
    let data: JSONValue
}

struct AgentMessage: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let id: String
    let sessionId: String
    let turnId: String
    let role: String
    let status: String
    let blocks: [AgentBlock]
    let attachments: [String]
    let citations: [String]
    let createdAtMs: Int
    let completedAtMs: Int?
}

struct AgentMediaReceipt: Codable, Equatable, Identifiable, Sendable {
    let schemaVersion: String
    let mediaId: String
    let sessionId: String
    let fileName: String?
    let mimeType: String
    let byteSize: Int
    let sha256: String
    let width: Int?
    let height: Int?
    let durationMs: Int?
    let thumbnailMediaId: String?
    let origin: String
    let originTool: String?
    let originReceiptId: String?
    let createdAtMs: Int

    var id: String { mediaId }
}

struct AgentSessionSummary: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let id: String
    let piSessionId: String?
    let sessionFile: String?
    let runtimeBinding: AgentRuntimeBinding?
    let title: String
    let mode: String
    let status: String
    let roleId: String
    let roleVersion: String
    let modelProfile: String
    let toolProfileVersion: String
    let createdAtMs: Int
    let updatedAtMs: Int
    let lastOpenedAtMs: Int
    let archivedAtMs: Int?
    let messageCount: Int
    let lastMessagePreview: String
    let workspaceRoots: [String]
    let shellPolicyVersion: String
}

struct AgentRuntimeBinding: Codable, Equatable {
    let schemaVersion: String
    let driverId: String
    let runtimeKind: String
    let externalSessionId: String?
    let branchAnchor: String?
    let generation: Int
    let state: String
    let createdAtMs: Int
    let updatedAtMs: Int
}

struct AgentRuntimeStatus: Decodable, Equatable {
    let schemaVersion: String
    let enabled: Bool
    let managed: Bool
    let status: String
    let driverId: String?
    let runtimeKind: String?
    let runtimeVersion: String?
    let piVersion: String
    let idleTimeoutSeconds: Int
    let activeSessionId: String?
    let lastError: String?
    let capabilities: JSONValue
}

struct AgentModelOption: Codable, Equatable, Identifiable {
    let provider: String
    let id: String
    let name: String
    let api: String
    let reasoning: Bool
    let thinkingLevels: [String]
    let supportsImages: Bool
    let contextWindow: Int
    let maxTokens: Int

    var selectionId: String { "\(provider)/\(id)" }
}

struct AgentModelProvider: Codable, Equatable, Identifiable {
    let id: String
    let displayName: String
    let models: [AgentModelOption]
}

struct AgentModelCatalogResponse: Decodable, Equatable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let selected: AgentModelOption?
    let thinkingLevel: String
    let providers: [AgentModelProvider]
}

struct AgentModelSelectionResponse: Decodable, Equatable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let selected: AgentModelOption
    let session: AgentSessionSummary
}

struct AgentThinkingSelectionResponse: Decodable, Equatable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let thinkingLevel: String
    let selected: AgentModelOption?
}

struct AgentSessionListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let items: [AgentSessionSummary]
    let activeSessionId: String?
}

struct AgentSessionMutationResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let session: AgentSessionSummary
}

struct AgentSessionDeleteResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let sessionFileDeleted: Bool
}

struct AgentMessageListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let items: [AgentMessage]
    let lastSequence: Int?
    let resumeToken: String?
}

struct AgentMediaImportResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let media: AgentMediaReceipt
}

struct AgentMediaGetResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let media: AgentMediaReceipt
}

struct AgentMediaListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let items: [AgentMediaReceipt]
}

struct AgentPromptAcceptedResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let accepted: Bool
    let turnId: String
}

struct AgentSimpleResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
}

struct AgentToolManifest: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let id: String
    let domain: String
    let displayName: String
    let description: String
    let category: String
    let riskLevel: String
    let operationRisks: [String: String]?
    let sessionModes: [String]
    let operations: [String]
    let resultPresentation: String
    let availability: String
    let version: String

    var approvalOperationCount: Int {
        (operationRisks ?? [:]).values.filter { $0 != "R0" }.count
    }
}

struct AgentToolListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let items: [AgentToolManifest]
}

struct AgentPersonaVisualProfile: Codable, Equatable {
    let avatarAssetId: String
    let symbolName: String
    let accentToken: String
}

struct AgentPersonaDefaults: Codable, Equatable {
    let modelPolicy: String
    let memoryPolicy: String
    let toolProfileVersion: String
}

struct AgentRoleSummary: Codable, Equatable, Identifiable {
    let schemaVersion: String?
    let roleId: String
    let version: String
    let displayName: String
    let tagline: String
    let summary: String?
    let traits: [String]?
    let visualProfile: AgentPersonaVisualProfile?
    let defaults: AgentPersonaDefaults?
    let safetyPolicyVersion: String?
    let selectableModes: [String]?

    var id: String { "\(roleId)@\(version)" }

    func supports(mode: String) -> Bool {
        selectableModes?.contains(mode) ?? (roleId == "zhiyou-v1")
    }

    static let fallbackZhiyou = AgentRoleSummary(
        schemaVersion: "rag-ime.agent-persona.v1",
        roleId: "zhiyou-v1",
        version: "1",
        displayName: "智鼬",
        tagline: "热心、灵动，关键时刻可靠",
        summary: "熟悉个人输入与知识库的长期伙伴，适合回顾、检索和日常整理。",
        traits: ["自然", "温暖", "证据优先"],
        visualProfile: AgentPersonaVisualProfile(
            avatarAssetId: "rag-ime-companion-v1",
            symbolName: "sparkles",
            accentToken: "teal"
        ),
        defaults: AgentPersonaDefaults(
            modelPolicy: "session-selected",
            memoryPolicy: "personal-evidence-v1",
            toolProfileVersion: "control-center-v1"
        ),
        safetyPolicyVersion: "control-center-safe-v1",
        selectableModes: ["assistant", "coordinator"]
    )
}

struct AgentRoleListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let items: [AgentRoleSummary]
}

struct AgentApproval: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let approvalId: String
    let sessionId: String
    let toolId: String
    let operation: String
    let payloadSha256: String
    let preview: JSONValue
    let riskLevel: String
    let state: String
    let requestedAtMs: Int
    let expiresAtMs: Int
    let decidedAtMs: Int?
    let receipt: JSONValue?

    var id: String { approvalId }
}

struct AgentApprovalListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let items: [AgentApproval]
}

struct AgentApprovalDecisionResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let approval: AgentApproval
}

struct AgentMemorySource: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let sourceId: String
    let sessionId: String
    let piEntryId: String
    let inputEventId: Int
    let sourceRole: String
    let sourceRevision: Int
    let canonicalTextSha256: String
    let status: String
    let createdAtMs: Int
    let supersededAtMs: Int?

    var id: String { sourceId }
}

struct AgentMemorySourceListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let sessionId: String
    let items: [AgentMemorySource]
}

struct AgentMemoryCompileState: Codable, Equatable {
    let project: String
    let lastCompiledEventId: Int
    let lastRunMs: Int
    let pendingEventCount: Int
    let lastBundleHash: String
}

struct AgentMemoryMaintenanceRun: Codable, Equatable, Identifiable {
    let runId: String
    let createdAtMs: Int
    let status: String
    let summary: String
    let diffCount: Int
    let bundleHash: String
    let sourceCursor: JSONValue

    var id: String { runId }
}

struct AgentMemoryMaintenanceStatus: Codable, Equatable {
    let schemaVersion: String
    let ok: Bool
    let policy: String
    let autoApply: Bool
    let scheduledDraftOnly: Bool
    let due: Bool
    let dueReason: String
    let idleMs: Int
    let compileState: AgentMemoryCompileState
    let pendingDraftCount: Int
    let runs: [AgentMemoryMaintenanceRun]
}
