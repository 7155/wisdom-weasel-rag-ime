import Foundation

struct VoiceAgentStatus: Codable, Equatable {
    static let schemaVersion = "rag-ime.voice-agent-status.v2"

    let schemaVersion: String
    let processID: Int32
    let running: Bool
    let accessibilityTrusted: Bool
    let microphoneAuthorization: String
    let credentialsConfigured: Bool
    let hotkeyInstalled: Bool
    let state: String
    let statusText: String
    let telemetry: VoiceSessionTelemetry
    let updatedAtMs: Int
}

struct VoiceSessionTelemetry: Codable, Equatable {
    let networkState: String
    let sessionActive: Bool
    let sessionStartedAtMs: Int?
    let firstPartialLatencyMs: Int?
    let finalLatencyMs: Int?
    let pcmFrameCount: Int
    let droppedPCMFrameCount: Int
    let partialRevisionCount: Int
    let finalReceived: Bool

    static let idle = VoiceSessionTelemetry(
        networkState: "idle",
        sessionActive: false,
        sessionStartedAtMs: nil,
        firstPartialLatencyMs: nil,
        finalLatencyMs: nil,
        pcmFrameCount: 0,
        droppedPCMFrameCount: 0,
        partialRevisionCount: 0,
        finalReceived: false
    )
}

enum VoiceAgentStatusStore {
    static var fileURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-agent-status.json", isDirectory: false)
    }

    static func read() -> VoiceAgentStatus? {
        guard let data = try? Data(contentsOf: fileURL),
              let status = try? JSONDecoder().decode(VoiceAgentStatus.self, from: data),
              status.schemaVersion == VoiceAgentStatus.schemaVersion else {
            return nil
        }
        return status
    }

    static func write(_ status: VoiceAgentStatus) {
        do {
            let directory = fileURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let data = try JSONEncoder().encode(status)
            try data.write(to: fileURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
        } catch {
            // Status is diagnostic only; voice input must remain usable if this write fails.
        }
    }

    static func remove() {
        try? FileManager.default.removeItem(at: fileURL)
    }
}
