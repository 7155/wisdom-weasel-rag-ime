import Foundation

struct RimeSidecarRequest: Codable {
    let schemaVersion: String
    let frontendBuild: String
    let sessionId: String
    let requestSeq: Int
    let rawInput: String
    let preedit: String
    let commitTextPreview: String
    let committedContext: String
    let project: String?
    let app: String?
    let idleMs: Int
    let latencyBudgetMs: Int
    let forceSideCandidates: Bool
    let predictionFirstMerge: Bool
    let maxVisibleCandidates: Int
    let maxSideCandidates: Int
    let rimeContext: RimeContextPayload

    init(
        schemaVersion: String = "rag-ime.native-macos-request.v1",
        frontendBuild: String = "rag-ime.native-macos.prediction-session.v1",
        sessionId: String,
        requestSeq: Int,
        rawInput: String,
        preedit: String,
        commitTextPreview: String = "",
        committedContext: String,
        project: String? = nil,
        app: String? = "RagImeMac",
        idleMs: Int = 0,
        latencyBudgetMs: Int = 3200,
        forceSideCandidates: Bool = false,
        predictionFirstMerge: Bool = true,
        maxVisibleCandidates: Int,
        maxSideCandidates: Int,
        rimeContext: RimeContextPayload
    ) {
        self.schemaVersion = schemaVersion
        self.frontendBuild = frontendBuild
        self.sessionId = sessionId
        self.requestSeq = requestSeq
        self.rawInput = rawInput
        self.preedit = preedit
        self.commitTextPreview = commitTextPreview
        self.committedContext = committedContext
        self.project = project
        self.app = app
        self.idleMs = idleMs
        self.latencyBudgetMs = latencyBudgetMs
        self.forceSideCandidates = forceSideCandidates
        self.predictionFirstMerge = predictionFirstMerge
        self.maxVisibleCandidates = maxVisibleCandidates
        self.maxSideCandidates = maxSideCandidates
        self.rimeContext = rimeContext
    }
}

struct RimeContextPayload: Codable {
    let candidates: [RimeCandidatePayload]
    let highlightedIndex: Int
    let page: Int
    let isLastPage: Bool
}

struct RimeCandidatePayload: Codable {
    let label: String
    let text: String
    let comment: String
    let index: Int?
}

struct RimeSidecarResponse: Codable {
    let schemaVersion: String
    let sessionId: String
    let requestSeq: Int
    let project: String
    let rawInput: String
    let preedit: String
    let commitTextPreview: String?
    let committedContext: String
    let semanticQuery: String
    let queryBasis: String
    let triggerDecision: RimeTriggerDecision?
    let historyContext: String
    let latencyBudgetMs: Int
    let rimeContext: RimeContextPayload
    let modelPredictions: [ModelPrediction]
    let ragCandidates: [RagSuggestion]
    let displayCandidates: [RimeDisplayCandidate]
    let predictionFirst: RimePredictionFirstPayload?
    let predictionSession: RimePredictionSessionPayload?
    let selectionActions: RimeSelectionActions
    let mergePolicy: RimeMergePolicy
}

struct RimeTriggerDecision: Codable {
    let shouldRefresh: Bool
    let reason: String
    let idleMs: Int
    let semanticSignalLength: Int
    let forceSideCandidates: Bool
}

struct RimeDisplayCandidate: Codable, Hashable {
    let label: String
    let selectionKey: String?
    let selectionRank: Int?
    let text: String
    let insertText: String
    let sourceType: String
    let selectionAction: String
    let sourceIndex: Int
    let comment: String
    let evidencePreview: String
    let expandedEvidence: String?
    let suggestionId: String
    let memoryId: String
    let sourceEventId: Int?
    let rimeIndex: Int?
    let displayLayout: String?
    let displayLane: String?
    let metadata: [String: JSONValue]
}

struct RimePredictionFirstPayload: Codable {
    let enabled: Bool
    let mode: String
    let pinyinPrefix: String
    let policy: [String: JSONValue]
}

struct RimePredictionSessionPayload: Codable {
    let phase: String
    let inputMode: String
    let pinyinPrefix: String
    let candidatePanelVisible: Bool
    let predictionPanelVisible: Bool
    let shouldClearPredictionPanel: Bool
    let clearReason: String
    let selectionScope: String
    let rimeCompositionOwnedByRime: Bool
    let sideCandidateCount: Int?
    let rimeCandidateCount: Int?
    let rawCommitCount: Int?
    let sessionFingerprint: String?
    let contextFingerprint: String?
    let requestSeq: Int?
    let expiresAfterMs: Int?
}

struct RimeSelectRequest: Codable {
    let candidate: RimeDisplayCandidate
    let shownCandidates: [RimeDisplayCandidate]
    let query: String
    let recentContext: String
    let preedit: String
    let project: String?
    let app: String
    let sessionId: String
    let requestSeq: Int
    let source: String
    let providerName: String
    let dryRun: Bool
}

struct RimeSelectResponse: Codable {
    let schemaVersion: String
    let ok: Bool
    let dryRun: Bool
    let eventId: String
    let project: String
    let sourceType: String
    let insertText: String
    let recordedAction: Bool
}

struct RimeSelectionActions: Codable {
    let rime: String
    let side: String
}

struct RimeMergePolicy: Codable {
    let rimeFirst: Bool
    let maxVisibleCandidates: Int
    let maxSideCandidates: Int
    let maxModelSideCandidates: Int?
    let ragKeepsRemainingSideSlots: Bool?
    let rawPinyinFallback: Bool
    let sideCandidatesEnabled: Bool?
}
