import Foundation

struct SuggestionResponse: Codable {
    let schemaVersion: String
    let currentInput: String
    let recentContext: String
    let project: String
    let modelPredictions: [ModelPrediction]?
    let suggestions: [RagSuggestion]
}

struct ModelPrediction: Codable, Hashable {
    let text: String
    let rank: Int
    let providerName: String
    let latencyMs: Int
    let confidence: Double
    let metadata: [String: JSONValue]
}

struct RagSuggestion: Codable, Hashable {
    let suggestionId: String
    let surfaceText: String
    let insertText: String
    let suggestionType: String
    let sourceEventId: Int
    let memoryId: String
    let evidencePreview: String
    let expandedEvidence: String
    let confidence: Double
    let actions: [String]
    let metadata: [String: JSONValue]
}

struct ActionResponse: Codable {
    let schemaVersion: String
    let actionId: Int?
    let createdAtMs: Int
    let memoryId: String
    let actionType: String
    let query: String
    let suggestionId: String
    let sourceEventId: Int?
    let metadata: [String: JSONValue]
}

enum JSONValue: Codable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case array([JSONValue])
    case object([String: JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }
}
