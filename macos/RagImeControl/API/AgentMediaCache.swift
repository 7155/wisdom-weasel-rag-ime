import Foundation

struct AgentMediaResource: Sendable {
    let receipt: AgentMediaReceipt
    let data: Data
}

actor AgentMediaCache {
    static let shared = AgentMediaCache()

    private let api = AgentAPIClient()
    private var resources: [String: AgentMediaResource] = [:]
    private var order: [String] = []
    private var byteSize = 0
    private let maximumObjects = 96
    private let maximumBytes = 64 * 1024 * 1024

    func resource(sessionId: String, mediaId: String) async throws -> AgentMediaResource {
        let key = "\(sessionId):\(mediaId)"
        if let cached = resources[key] {
            touch(key)
            return cached
        }
        async let receiptRequest = api.mediaReceipt(mediaId: mediaId, sessionId: sessionId)
        async let dataRequest = api.mediaData(mediaId: mediaId, sessionId: sessionId)
        let (receipt, data) = try await (receiptRequest, dataRequest)
        let resource = AgentMediaResource(receipt: receipt, data: data)
        resources[key] = resource
        order.append(key)
        byteSize += resource.data.count
        trim()
        return resource
    }

    func materializedURL(sessionId: String, mediaId: String) async throws -> URL {
        let resource = try await resource(sessionId: sessionId, mediaId: mediaId)
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("RagImeControlMedia", isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let target = root.appendingPathComponent(mediaId + extensionFor(resource.receipt.mimeType))
        try resource.data.write(to: target, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
        return target
    }

    private func touch(_ key: String) {
        order.removeAll(where: { $0 == key })
        order.append(key)
    }

    private func trim() {
        while resources.count > maximumObjects || byteSize > maximumBytes {
            guard let key = order.first else { break }
            order.removeFirst()
            if let removed = resources.removeValue(forKey: key) {
                byteSize -= removed.data.count
            }
        }
    }

    private func extensionFor(_ mimeType: String) -> String {
        switch mimeType {
        case "image/png": return ".png"
        case "image/jpeg": return ".jpg"
        case "image/gif": return ".gif"
        case "image/webp": return ".webp"
        case "audio/mpeg": return ".mp3"
        case "audio/mp4": return ".m4a"
        case "audio/wav": return ".wav"
        case "application/pdf": return ".pdf"
        case "text/plain": return ".txt"
        default: return ".bin"
        }
    }
}
