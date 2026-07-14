import Foundation

enum AgentRoomEventKind: Equatable, Codable {
    case userMessage
    case routeDecision
    case participantStatus
    case participantDelta
    case participantActivity
    case participantMessage
    case turnCompleted
    case turnFailed
    case snapshotRequired
    case unknown(String)

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = switch raw {
        case "user_message": .userMessage
        case "route_decision": .routeDecision
        case "participant_status": .participantStatus
        case "participant_delta": .participantDelta
        case "participant_activity": .participantActivity
        case "participant_message": .participantMessage
        case "turn_completed": .turnCompleted
        case "turn_failed": .turnFailed
        case "snapshot_required": .snapshotRequired
        default: .unknown(raw)
        }
    }

    func encode(to encoder: Encoder) throws {
        try rawValue.encode(to: encoder)
    }

    var rawValue: String {
        switch self {
        case .userMessage: "user_message"
        case .routeDecision: "route_decision"
        case .participantStatus: "participant_status"
        case .participantDelta: "participant_delta"
        case .participantActivity: "participant_activity"
        case .participantMessage: "participant_message"
        case .turnCompleted: "turn_completed"
        case .turnFailed: "turn_failed"
        case .snapshotRequired: "snapshot_required"
        case let .unknown(raw): raw
        }
    }
}

struct AgentRoomParticipant: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let id: String
    let roomId: String
    let sessionId: String
    let roleId: String
    let roleVersion: String
    let displayName: String
    let status: String
    let ordinal: Int
    let createdAtMs: Int
    let lastSpokeAtMs: Int?
}

struct AgentRoomSummary: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let id: String
    let title: String
    let status: String
    let routingPolicy: String
    let moderatorParticipantId: String
    let createdAtMs: Int
    let updatedAtMs: Int
    let lastEventSequence: Int
    let participants: [AgentRoomParticipant]
}

struct AgentRoomEventEnvelope: Codable, Equatable, Identifiable {
    let schemaVersion: String
    let eventId: String
    let roomId: String
    let sequence: Int
    let turnId: String
    let eventType: AgentRoomEventKind
    let participantId: String?
    let sourceSessionId: String
    let createdAtMs: Int
    let payload: JSONValue
    let resumeToken: String

    var id: String { eventId }
}

struct AgentRoomListResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let items: [AgentRoomSummary]
}

struct AgentRoomGetResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let room: AgentRoomSummary
}

struct AgentRoomMutationResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let room: AgentRoomSummary
    let event: AgentRoomEventEnvelope?
}

struct AgentRoomMessageResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let accepted: Bool
    let roomId: String
    let roomTurnId: String
    let participant: AgentRoomParticipant
    let sessionTurnId: String
}
