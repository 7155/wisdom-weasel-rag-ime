//
//  RagImeInputCaptureOutbox.swift
//  Squirrel
//

import Foundation

struct RagImeInputCaptureBoundary {
  let kind: String
  let confidence: String
  let nativeCompositionBefore: Bool
  let rimeHandled: Bool
  let hostForwarded: Bool
  let modifiedReturn: Bool
  let finalCommitted: Bool
}

struct RagImeInputCaptureIdentity {
  let captureId: String
  let transactionId: String
  let sequence: Int
  let controllerEpoch: Int
  let focusEpoch: Int
  let occurredStartMs: Int
  let occurredEndMs: Int
  let fieldIdentitySha256: String
}

struct RagImeInputCaptureReceipt: Codable {
  let schemaVersion: String
  let captureId: String
  let transactionId: String
  let sequence: Int
  let channel: String
  let boundaryKind: String
  let boundaryConfidence: String
  let contentSha256: String
  let eventId: String
  let outcome: String
  let reason: String
  let duplicate: Bool

  func validate(expectedCaptureId: String) throws {
    guard schemaVersion == "rag-ime.input-capture-receipt.v2",
          captureId == expectedCaptureId,
          ["stored", "no_store", "quarantined"].contains(outcome) else {
      throw RagImeSidecarError.transport("invalid input capture receipt")
    }
  }
}

private struct RagImeForegroundCommitResponse: Decodable {
  let schemaVersion: String
  let ok: Bool
  let captureReceipt: RagImeInputCaptureReceipt?
}

private struct RagImePendingInputCapture: Codable {
  let payload: RagImeCommitPayload
  let queuedAtMs: Int
  var attempts: Int
  var lastFailureCode: String
}

/// A bounded, owner-only retry queue for finalized input that the host has
/// already committed. Entries are written before HTTP delivery; the server's
/// captureId receipt makes replay safe after either process crashes.
final class RagImeInputCaptureOutbox {
  static let shared = RagImeInputCaptureOutbox()

  private let queue = DispatchQueue(label: "im.rime.input-capture-outbox")
  private let fileManager: FileManager
  private let outboxURL: URL
  private let maximumEntries = 64
  private let maximumBytes = 2 * 1024 * 1024

  init(
    fileManager: FileManager = .default,
    outboxURL: URL? = nil
  ) {
    self.fileManager = fileManager
    if let outboxURL {
      self.outboxURL = outboxURL
    } else if let configured = ProcessInfo.processInfo.environment["RAG_IME_INPUT_CAPTURE_OUTBOX_PATH"],
              !configured.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      self.outboxURL = URL(fileURLWithPath: configured)
    } else {
      self.outboxURL = fileManager.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/RagIme/InputCapture", isDirectory: true)
        .appendingPathComponent("pending-v2.json", isDirectory: false)
    }
  }

  func deliver(
    _ payload: RagImeCommitPayload,
    using client: RagImeSidecarClient
  ) throws -> RagImeInputCaptureReceipt {
    try queue.sync {
      guard let metadata = payload.captureMetadata else {
        throw RagImeSidecarError.transport("v2 input capture metadata missing")
      }

      let nowMs = Int(Date().timeIntervalSince1970 * 1_000)
      var entries = try loadEntries(nowMs: nowMs)
      if let index = entries.firstIndex(where: {
        $0.payload.captureMetadata?.captureId == metadata.captureId
      }) {
        guard entries[index].payload.captureMetadata?.contentSha256 == metadata.contentSha256 else {
          throw RagImeSidecarError.transport("captureId reused with different content")
        }
      } else {
        entries.append(
          RagImePendingInputCapture(
            payload: payload,
            queuedAtMs: nowMs,
            attempts: 0,
            lastFailureCode: ""
          )
        )
      }
      entries = try bounded(entries)
      try persist(entries)
      let (currentReceipt, _) = try drain(
        &entries,
        using: client,
        observingCaptureId: metadata.captureId
      )
      guard let currentReceipt else {
        throw RagImeSidecarError.transport("finalized input receipt was not observed")
      }
      return currentReceipt
    }
  }

  func retryPending(using client: RagImeSidecarClient) throws -> Int {
    try queue.sync {
      var entries = try loadEntries(nowMs: Int(Date().timeIntervalSince1970 * 1_000))
      guard !entries.isEmpty else { return 0 }
      let (_, deliveredCount) = try drain(
        &entries,
        using: client,
        observingCaptureId: nil
      )
      return deliveredCount
    }
  }

  func contains(captureId: String) -> Bool {
    queue.sync {
      guard fileManager.fileExists(atPath: outboxURL.path),
            let data = try? Data(contentsOf: outboxURL, options: [.mappedIfSafe]),
            let entries = try? JSONDecoder().decode([RagImePendingInputCapture].self, from: data) else {
        return false
      }
      return entries.contains {
        $0.payload.captureMetadata?.captureId == captureId
      }
    }
  }

  private func loadEntries(nowMs: Int) throws -> [RagImePendingInputCapture] {
    guard fileManager.fileExists(atPath: outboxURL.path) else { return [] }
    do {
      let data = try Data(contentsOf: outboxURL, options: [.mappedIfSafe])
      return try JSONDecoder().decode([RagImePendingInputCapture].self, from: data)
    } catch {
      let quarantineURL = outboxURL.deletingLastPathComponent().appendingPathComponent(
        "pending-v2.corrupt-\(nowMs).json"
      )
      try? fileManager.moveItem(at: outboxURL, to: quarantineURL)
      try? hardenPermissions(at: quarantineURL, permissions: 0o600)
      return []
    }
  }

  private func bounded(
    _ entries: [RagImePendingInputCapture]
  ) throws -> [RagImePendingInputCapture] {
    guard entries.count <= maximumEntries,
          try JSONEncoder().encode(entries).count <= maximumBytes else {
      throw RagImeSidecarError.transport("input capture exceeds bounded outbox capacity")
    }
    return entries
  }

  private func drain(
    _ entries: inout [RagImePendingInputCapture],
    using client: RagImeSidecarClient,
    observingCaptureId: String?
  ) throws -> (RagImeInputCaptureReceipt?, Int) {
    guard let sidecarURL = client.sidecarURL else {
      throw RagImeSidecarError.transport("sidecar_url missing; finalized input queued for retry")
    }
    var observedReceipt: RagImeInputCaptureReceipt?
    var deliveredCount = 0
    while !entries.isEmpty {
      entries[0].attempts += 1
      entries[0].lastFailureCode = "delivery_in_progress"
      try persist(entries)
      let pending = entries[0]
      guard let pendingMetadata = pending.payload.captureMetadata else {
        entries.removeFirst()
        try persist(entries)
        continue
      }
      do {
        let data = try client.postFinalizedInputCapture(
          pending.payload,
          to: sidecarURL
        )
        let response = try JSONDecoder().decode(RagImeForegroundCommitResponse.self, from: data)
        guard response.schemaVersion == "rag-ime.foreground-commit.v1",
              response.ok,
              let receipt = response.captureReceipt else {
          throw RagImeSidecarError.transport("finalized input response has no capture receipt")
        }
        try receipt.validate(expectedCaptureId: pendingMetadata.captureId)
        if pendingMetadata.captureId == observingCaptureId {
          observedReceipt = receipt
        }
        entries.removeFirst()
        deliveredCount += 1
        try persist(entries)
      } catch {
        entries[0].lastFailureCode = "delivery_failed"
        try persist(entries)
        throw error
      }
    }
    return (observedReceipt, deliveredCount)
  }

  private func persist(_ entries: [RagImePendingInputCapture]) throws {
    let directory = outboxURL.deletingLastPathComponent()
    try fileManager.createDirectory(
      at: directory,
      withIntermediateDirectories: true,
      attributes: [.posixPermissions: NSNumber(value: 0o700)]
    )
    try hardenPermissions(at: directory, permissions: 0o700)
    let data = try JSONEncoder().encode(entries)
    try data.write(to: outboxURL, options: .atomic)
    try hardenPermissions(at: outboxURL, permissions: 0o600)
  }

  private func hardenPermissions(at url: URL, permissions: Int) throws {
    try fileManager.setAttributes(
      [.posixPermissions: NSNumber(value: permissions)],
      ofItemAtPath: url.path
    )
  }
}
