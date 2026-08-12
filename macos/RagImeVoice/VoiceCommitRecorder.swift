import CryptoKit
import Foundation

enum VoiceCommitDelivery: Sendable {
    case acknowledged(outcome: String, duplicate: Bool)
    case queued
    case failed
}

enum VoiceCommitRecorder {
    private static let endpoint = URL(string: "http://127.0.0.1:8766/api/commit")!
    private static let queue = DispatchQueue(label: "com.rag-ime.voice.commit-outbox")
    private static let processEpochMs = Int(Date().timeIntervalSince1970 * 1_000)
    private static let maximumEntries = 64
    private static let maximumBytes = 2 * 1024 * 1024

    static func retryPending() {
        queue.async {
            do {
                var entries = try loadEntries(nowMs: Int(Date().timeIntervalSince1970 * 1_000))
                guard !entries.isEmpty else { return }
                _ = try deliverPending(&entries, observingCaptureID: nil)
            } catch {
                // The owner-only outbox remains intact for the next bounded retry.
            }
        }
    }

    static func record(
        text: String,
        recentContext: String,
        appBundleIdentifier: String,
        captureID: String,
        occurredStartMs: Int,
        completion: @escaping @Sendable (VoiceCommitDelivery) -> Void
    ) {
        let value = compactWhitespace(text)
        guard !value.isEmpty, !captureID.isEmpty else {
            completion(.failed)
            return
        }
        let app = appBundleIdentifier.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedApp = app.isEmpty ? "unknown" : app
        let boundedContext = String(compactWhitespace(recentContext).suffix(1_600))
        let nowMs = Int(Date().timeIntervalSince1970 * 1_000)
        let metadata = CaptureMetadata(
            schemaVersion: "rag-ime.input-capture.v2",
            captureId: captureID,
            transactionId: captureID,
            sequence: 1,
            channel: "voice",
            boundaryKind: "voice_final",
            boundaryConfidence: "strong",
            nativeCompositionBefore: false,
            rimeHandled: false,
            hostForwarded: true,
            modifiedReturn: false,
            finalCommitted: true,
            controllerEpoch: processEpochMs,
            focusEpoch: 0,
            appBundleId: resolvedApp,
            fieldIdentitySha256: sha256("\(resolvedApp)\u{001f}\(captureID)"),
            privacyRevision: "voice-insertion-policy.v1",
            occurredStartMs: max(0, occurredStartMs),
            occurredEndMs: max(max(0, occurredStartMs), nowMs),
            contentSha256: sha256(value),
            captureSource: "voice_insertion",
            fallbackReason: boundedContext.isEmpty ? "ax_context_unavailable" : "",
            fieldContextChars: boundedContext.count,
            imeBufferChars: 0,
            selectionRule: boundedContext.isEmpty
                ? "inserted_voice_final_no_context"
                : "inserted_voice_final_with_ax_context"
        )
        let payload = CommitPayload(
            text: value,
            recentContext: boundedContext,
            project: "wisdom-weasel-rag-ime",
            app: resolvedApp,
            providerName: "voice_streaming_asr",
            tags: ["voice-input", "recent-input", "finalized", "capture-v2"],
            source: "voice_final",
            privacyDisposition: "allowed",
            sensitiveField: false,
            secureInput: false,
            captureMetadata: metadata
        )

        queue.async {
            let nowMs = Int(Date().timeIntervalSince1970 * 1_000)
            do {
                var entries = try loadEntries(nowMs: nowMs)
                if let existing = entries.first(where: {
                    $0.payload.captureMetadata.captureId == captureID
                }) {
                    guard existing.payload.captureMetadata.contentSha256 == metadata.contentSha256 else {
                        completion(.failed)
                        return
                    }
                } else {
                    entries.append(PendingCommit(payload: payload, queuedAtMs: nowMs, attempts: 0))
                }
                entries = try bounded(entries)
                try persist(entries)

                let currentReceipt: CaptureReceipt?
                do {
                    currentReceipt = try deliverPending(
                        &entries,
                        observingCaptureID: captureID
                    )
                } catch {
                    completion(.queued)
                    return
                }
                guard let currentReceipt else {
                    completion(.failed)
                    return
                }
                completion(
                    .acknowledged(
                        outcome: currentReceipt.outcome,
                        duplicate: currentReceipt.duplicate
                    )
                )
            } catch {
                completion(.failed)
            }
        }
    }

    private static func deliverPending(
        _ entries: inout [PendingCommit],
        observingCaptureID: String?
    ) throws -> CaptureReceipt? {
        var observedReceipt: CaptureReceipt?
        while !entries.isEmpty {
            entries[0].attempts += 1
            try persist(entries)
            let response = try post(entries[0].payload)
            let receipt = try response.validatedReceipt(
                expectedCaptureID: entries[0].payload.captureMetadata.captureId
            )
            if receipt.captureId == observingCaptureID {
                observedReceipt = receipt
            }
            entries.removeFirst()
            try persist(entries)
        }
        return observedReceipt
    }

    private static var outboxURL: URL {
        if let configured = ProcessInfo.processInfo.environment["RAG_IME_VOICE_COMMIT_OUTBOX_PATH"],
           !configured.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return URL(fileURLWithPath: configured)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme/VoiceInput", isDirectory: true)
            .appendingPathComponent("pending-commits-v2.json", isDirectory: false)
    }

    private static func post(_ payload: CommitPayload) throws -> CommitResponse {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 1.5
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)

        let semaphore = DispatchSemaphore(value: 0)
        let box = VoiceCommitResponseBox()
        URLSession(configuration: .ephemeral).dataTask(with: request) { data, response, error in
            box.store(data: data, response: response, error: error)
            semaphore.signal()
        }.resume()
        guard semaphore.wait(timeout: .now() + 1.7) == .success else {
            throw VoiceCommitRecorderError.timeout
        }
        let result = box.load()
        if let error = result.error { throw error }
        guard let response = result.response as? HTTPURLResponse,
              (200..<300).contains(response.statusCode),
              let data = result.data else {
            throw VoiceCommitRecorderError.badResponse
        }
        return try JSONDecoder().decode(CommitResponse.self, from: data)
    }

    private static func loadEntries(nowMs: Int) throws -> [PendingCommit] {
        let url = outboxURL
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        do {
            let data = try Data(contentsOf: url, options: [.mappedIfSafe])
            return try JSONDecoder().decode([PendingCommit].self, from: data)
        } catch {
            let quarantine = url.deletingLastPathComponent().appendingPathComponent(
                "pending-commits-v2.corrupt-\(nowMs).json"
            )
            try? FileManager.default.moveItem(at: url, to: quarantine)
            try? hardenPermissions(at: quarantine, permissions: 0o600)
            return []
        }
    }

    private static func bounded(_ entries: [PendingCommit]) throws -> [PendingCommit] {
        guard entries.count <= maximumEntries,
              try JSONEncoder().encode(entries).count <= maximumBytes else {
            throw VoiceCommitRecorderError.capacity
        }
        return entries
    }

    private static func persist(_ entries: [PendingCommit]) throws {
        let url = outboxURL
        let directory = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: NSNumber(value: 0o700)]
        )
        try hardenPermissions(at: directory, permissions: 0o700)
        try JSONEncoder().encode(entries).write(to: url, options: .atomic)
        try hardenPermissions(at: url, permissions: 0o600)
    }

    private static func hardenPermissions(at url: URL, permissions: Int) throws {
        try FileManager.default.setAttributes(
            [.posixPermissions: NSNumber(value: permissions)],
            ofItemAtPath: url.path
        )
    }

    private static func compactWhitespace(_ value: String) -> String {
        value.components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(compactWhitespace(value).utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}

private struct PendingCommit: Codable {
    let payload: CommitPayload
    let queuedAtMs: Int
    var attempts: Int
}

private struct CommitPayload: Codable {
    let text: String
    // Optional keeps queued v2 commits written by an older build decodable.
    // New captures always encode the bounded AX context when it is available.
    let recentContext: String?
    let project: String
    let app: String
    let providerName: String
    let tags: [String]
    let source: String
    let privacyDisposition: String
    let sensitiveField: Bool
    let secureInput: Bool
    let captureMetadata: CaptureMetadata
}

private struct CaptureMetadata: Codable {
    let schemaVersion: String
    let captureId: String
    let transactionId: String
    let sequence: Int
    let channel: String
    let boundaryKind: String
    let boundaryConfidence: String
    let nativeCompositionBefore: Bool
    let rimeHandled: Bool
    let hostForwarded: Bool
    let modifiedReturn: Bool
    let finalCommitted: Bool
    let controllerEpoch: Int
    let focusEpoch: Int
    let appBundleId: String
    let fieldIdentitySha256: String
    let privacyRevision: String
    let occurredStartMs: Int
    let occurredEndMs: Int
    let contentSha256: String
    let captureSource: String
    let fallbackReason: String
    let fieldContextChars: Int
    let imeBufferChars: Int
    let selectionRule: String
}

private struct CommitResponse: Decodable {
    let schemaVersion: String
    let ok: Bool
    let captureReceipt: CaptureReceipt?

    func validatedReceipt(expectedCaptureID: String) throws -> CaptureReceipt {
        guard schemaVersion == "rag-ime.foreground-commit.v1",
              ok,
              let captureReceipt,
              captureReceipt.schemaVersion == "rag-ime.input-capture-receipt.v2",
              captureReceipt.captureId == expectedCaptureID,
              ["stored", "no_store", "quarantined"].contains(captureReceipt.outcome) else {
            throw VoiceCommitRecorderError.badResponse
        }
        return captureReceipt
    }
}

private struct CaptureReceipt: Decodable {
    let schemaVersion: String
    let captureId: String
    let outcome: String
    let duplicate: Bool
}

private final class VoiceCommitResponseBox: @unchecked Sendable {
    private let lock = NSLock()
    private var value: (data: Data?, response: URLResponse?, error: Error?) = (nil, nil, nil)

    func store(data: Data?, response: URLResponse?, error: Error?) {
        lock.lock()
        value = (data, response, error)
        lock.unlock()
    }

    func load() -> (data: Data?, response: URLResponse?, error: Error?) {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

private enum VoiceCommitRecorderError: Error {
    case timeout
    case badResponse
    case capacity
}
