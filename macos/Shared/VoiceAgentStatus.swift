import Foundation

struct VoiceAgentStatus: Codable, Equatable {
    static let schemaVersion = "rag-ime.voice-agent-status.v4"

    let schemaVersion: String
    let processID: Int32
    let running: Bool
    let accessibilityTrusted: Bool
    let microphoneAuthorization: String
    let credentialsConfigured: Bool
    let hotkeyMode: String?
    let hotwordsEnabled: Bool
    let hotwordCount: Int
    let hotkeyInstalled: Bool
    let state: String
    let interactionSource: String
    let statusText: String
    let recognition: VoiceRecognitionContract?
    let telemetry: VoiceSessionTelemetry
    let updatedAtMs: Int
}

struct VoiceRecognitionContract: Codable, Equatable {
    let finalSecondPass: Bool
    let semanticSmoothing: Bool
    let fullResultReplacement: Bool
    let providerResponseMetadata: Bool?
    let thirdPassRefinement: Bool?

    static let current = VoiceRecognitionContract(
        finalSecondPass: true,
        semanticSmoothing: true,
        fullResultReplacement: true,
        providerResponseMetadata: true,
        thirdPassRefinement: true
    )
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
    var finalRevisedPartial: Bool? = nil
    var localSmoothingApplied: Bool? = nil
    var providerResponseStage: String? = nil
    var providerResponseStages: [String]? = nil
    var providerResponseCount: Int? = nil
    var providerResponseSequence: Int? = nil
    var providerFinalFrame: Bool? = nil
    var providerResultFields: [String]? = nil
    var providerUtteranceMetadata: [[String: String]]? = nil
    var providerAdditionFields: [String: String]? = nil
    var thirdPassRequested: Bool? = nil
    var thirdPassApplied: Bool? = nil
    var thirdPassChanged: Bool? = nil
    var thirdPassLatencyMs: Int? = nil
    var thirdPassModel: String? = nil
    var thirdPassError: String? = nil

    static let idle = VoiceSessionTelemetry(
        networkState: "idle",
        sessionActive: false,
        sessionStartedAtMs: nil,
        firstPartialLatencyMs: nil,
        finalLatencyMs: nil,
        pcmFrameCount: 0,
        droppedPCMFrameCount: 0,
        partialRevisionCount: 0,
        finalReceived: false,
        finalRevisedPartial: nil,
        localSmoothingApplied: nil
    )
}

enum VoiceAgentStatusStore {
    private struct LegacyVoiceAgentStatusV3: Codable {
        let schemaVersion: String
        let processID: Int32
        let running: Bool
        let accessibilityTrusted: Bool
        let microphoneAuthorization: String
        let credentialsConfigured: Bool
        let hotkeyMode: String?
        let hotwordsEnabled: Bool
        let hotwordCount: Int
        let hotkeyInstalled: Bool
        let state: String
        let statusText: String
        let telemetry: VoiceSessionTelemetry
        let updatedAtMs: Int

        var upgraded: VoiceAgentStatus {
            VoiceAgentStatus(
                schemaVersion: VoiceAgentStatus.schemaVersion,
                processID: processID,
                running: running,
                accessibilityTrusted: accessibilityTrusted,
                microphoneAuthorization: microphoneAuthorization,
                credentialsConfigured: credentialsConfigured,
                hotkeyMode: hotkeyMode,
                hotwordsEnabled: hotwordsEnabled,
                hotwordCount: hotwordCount,
                hotkeyInstalled: hotkeyInstalled,
                state: state,
                interactionSource: state == "idle" ? "none" : "hotkey",
                statusText: statusText,
                recognition: nil,
                telemetry: telemetry,
                updatedAtMs: updatedAtMs
            )
        }
    }

    private struct LegacyVoiceAgentStatusV2: Codable {
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

        var upgraded: VoiceAgentStatus {
            VoiceAgentStatus(
                schemaVersion: VoiceAgentStatus.schemaVersion,
                processID: processID,
                running: running,
                accessibilityTrusted: accessibilityTrusted,
                microphoneAuthorization: microphoneAuthorization,
                credentialsConfigured: credentialsConfigured,
                hotkeyMode: nil,
                hotwordsEnabled: false,
                hotwordCount: 0,
                hotkeyInstalled: hotkeyInstalled,
                state: state,
                interactionSource: state == "idle" ? "none" : "hotkey",
                statusText: statusText,
                recognition: nil,
                telemetry: telemetry,
                updatedAtMs: updatedAtMs
            )
        }
    }

    static var fileURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-agent-status.json", isDirectory: false)
    }

    static func read() -> VoiceAgentStatus? {
        guard let data = try? Data(contentsOf: fileURL) else { return nil }
        if let status = try? JSONDecoder().decode(VoiceAgentStatus.self, from: data),
           status.schemaVersion == VoiceAgentStatus.schemaVersion {
            return status
        }
        if let legacy = try? JSONDecoder().decode(LegacyVoiceAgentStatusV3.self, from: data),
           legacy.schemaVersion == "rag-ime.voice-agent-status.v3" {
            return legacy.upgraded
        }
        if let legacy = try? JSONDecoder().decode(LegacyVoiceAgentStatusV2.self, from: data),
           legacy.schemaVersion == "rag-ime.voice-agent-status.v2" {
            return legacy.upgraded
        }
        return nil
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
