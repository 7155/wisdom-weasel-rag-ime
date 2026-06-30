import Foundation

struct RimeSidecarRequest: Codable {
    let sessionId: String
    let requestSeq: Int
    let rawInput: String
    let preedit: String
    let committedContext: String
    let maxVisibleCandidates: Int
    let maxSideCandidates: Int
    let rimeContext: RimeContextPayload
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
    let committedContext: String
    let semanticQuery: String
    let queryBasis: String
    let historyContext: String
    let latencyBudgetMs: Int
    let rimeContext: RimeContextPayload
    let modelPredictions: [ModelPrediction]
    let ragCandidates: [RagSuggestion]
    let displayCandidates: [RimeDisplayCandidate]
    let selectionActions: RimeSelectionActions
    let mergePolicy: RimeMergePolicy
}

struct RimeDisplayCandidate: Codable, Hashable {
    let label: String
    let text: String
    let insertText: String
    let sourceType: String
    let selectionAction: String
    let sourceIndex: Int
    let comment: String
    let evidencePreview: String
    let suggestionId: String
    let memoryId: String
    let rimeIndex: Int?
    let metadata: [String: JSONValue]
}

struct RimeSelectionActions: Codable {
    let rime: String
    let side: String
}

struct RimeMergePolicy: Codable {
    let rimeFirst: Bool
    let maxVisibleCandidates: Int
    let maxSideCandidates: Int
    let rawPinyinFallback: Bool
}
