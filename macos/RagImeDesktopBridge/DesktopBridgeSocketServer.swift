import Darwin
import Foundation

enum DesktopBridgeError: Error {
    case invalidRequest(String)
    case permissionDenied(String)
    case unavailable(String)
    case stale(String)
    case actionFailed(String)
    case internalFailure(String)

    var code: String {
        switch self {
        case .invalidRequest: return "invalid_request"
        case .permissionDenied: return "permission_denied"
        case .unavailable: return "unavailable"
        case .stale: return "stale_state"
        case .actionFailed: return "action_failed"
        case .internalFailure: return "internal_failure"
        }
    }

    var message: String {
        switch self {
        case .invalidRequest(let value),
             .permissionDenied(let value),
             .unavailable(let value),
             .stale(let value),
             .actionFailed(let value),
             .internalFailure(let value):
            return value
        }
    }
}

final class DesktopBridgeSocketServer {
    static let maximumMessageBytes = 1_048_576

    private let service: DesktopAccessibilityService
    private let socketPath: String
    private let acceptQueue = DispatchQueue(label: "com.rag-ime.desktop-bridge.accept")
    private let requestQueue = DispatchQueue(
        label: "com.rag-ime.desktop-bridge.requests",
        qos: .userInitiated
    )
    private var listenerFD: Int32 = -1
    private var source: DispatchSourceRead?

    init(
        service: DesktopAccessibilityService,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) {
        self.service = service
        self.socketPath = Self.resolveSocketPath(environment: environment)
    }

    func start() throws {
        guard listenerFD < 0 else { return }
        let parent = URL(fileURLWithPath: socketPath).deletingLastPathComponent()
        let parentAlreadyExisted = FileManager.default.fileExists(atPath: parent.path)
        try FileManager.default.createDirectory(
            at: parent,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        if !parentAlreadyExisted {
            _ = chmod(parent.path, 0o700)
        }
        unlink(socketPath)

        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else {
            throw DesktopBridgeError.internalFailure("socket_create_failed")
        }
        do {
            try bindSocket(fd)
            guard listen(fd, 16) == 0 else {
                throw DesktopBridgeError.internalFailure("socket_listen_failed")
            }
            guard chmod(socketPath, 0o600) == 0 else {
                throw DesktopBridgeError.internalFailure("socket_permissions_failed")
            }
            _ = fcntl(fd, F_SETFL, O_NONBLOCK)
            listenerFD = fd
            let source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: acceptQueue)
            source.setEventHandler { [weak self] in self?.acceptAvailableClients() }
            source.setCancelHandler {
                Darwin.close(fd)
            }
            self.source = source
            source.resume()
        } catch {
            Darwin.close(fd)
            unlink(socketPath)
            throw error
        }
    }

    func stop() {
        source?.cancel()
        source = nil
        listenerFD = -1
        unlink(socketPath)
    }

    private func bindSocket(_ fd: Int32) throws {
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let bytes = Array(socketPath.utf8CString)
        let capacity = MemoryLayout.size(ofValue: address.sun_path)
        guard bytes.count <= capacity else {
            throw DesktopBridgeError.internalFailure("socket_path_too_long")
        }
        withUnsafeMutablePointer(to: &address.sun_path) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: capacity) { destination in
                for (index, byte) in bytes.enumerated() {
                    destination[index] = byte
                }
            }
        }
        let length = socklen_t(
            MemoryLayout.size(ofValue: address.sun_len)
                + MemoryLayout.size(ofValue: address.sun_family)
                + bytes.count
        )
        address.sun_len = UInt8(min(Int(UInt8.max), Int(length)))
        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(fd, $0, length)
            }
        }
        guard result == 0 else {
            throw DesktopBridgeError.internalFailure("socket_bind_failed_\(errno)")
        }
    }

    private func acceptAvailableClients() {
        while listenerFD >= 0 {
            let clientFD = Darwin.accept(listenerFD, nil, nil)
            if clientFD < 0 {
                if errno == EINTR { continue }
                return
            }
            requestQueue.async { [weak self] in
                self?.handleClient(clientFD)
            }
        }
    }

    private func handleClient(_ fd: Int32) {
        defer { Darwin.close(fd) }
        let currentFlags = fcntl(fd, F_GETFL, 0)
        if currentFlags >= 0 {
            _ = fcntl(fd, F_SETFL, currentFlags & ~O_NONBLOCK)
        }
        var peerUID: uid_t = 0
        var peerGID: gid_t = 0
        guard getpeereid(fd, &peerUID, &peerGID) == 0, peerUID == geteuid() else {
            writeResponse(
                [
                    "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                    "ok": false,
                    "error": [
                        "code": "permission_denied",
                        "message": "peer_uid_mismatch",
                    ],
                ],
                to: fd
            )
            return
        }
        var timeout = timeval(tv_sec: 2, tv_usec: 0)
        _ = setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        _ = setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))

        var requestID = ""
        do {
            let request = try readRequest(from: fd)
            requestID = boundedString(request["requestId"], maximum: 160)
            guard !requestID.isEmpty else {
                throw DesktopBridgeError.invalidRequest("requestId is required")
            }
            guard request["schemaVersion"] as? String == "rag-ime.desktop-bridge-request.v1" else {
                throw DesktopBridgeError.invalidRequest("unsupported_schema_version")
            }
            guard let operation = request["op"] as? String, !operation.isEmpty else {
                throw DesktopBridgeError.invalidRequest("op is required")
            }
            let result = try service.handle(operation: operation, request: request)
            writeResponse(
                [
                    "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                    "requestId": requestID,
                    "ok": true,
                    "result": result,
                ],
                to: fd
            )
        } catch let error as DesktopBridgeError {
            writeResponse(
                [
                    "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                    "requestId": requestID,
                    "ok": false,
                    "error": ["code": error.code, "message": error.message],
                ],
                to: fd
            )
        } catch {
            writeResponse(
                [
                    "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                    "requestId": requestID,
                    "ok": false,
                    "error": ["code": "internal_failure", "message": "request_failed"],
                ],
                to: fd
            )
        }
    }

    private func readRequest(from fd: Int32) throws -> [String: Any] {
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while data.count <= Self.maximumMessageBytes {
            let count = Darwin.read(fd, &buffer, buffer.count)
            if count > 0 {
                if let newline = buffer[..<Int(count)].firstIndex(of: 0x0A) {
                    data.append(contentsOf: buffer[..<newline])
                    break
                }
                data.append(contentsOf: buffer[..<Int(count)])
                continue
            }
            if count == 0 { break }
            if errno == EINTR { continue }
            throw DesktopBridgeError.invalidRequest("socket_read_failed")
        }
        guard !data.isEmpty else {
            throw DesktopBridgeError.invalidRequest("empty_request")
        }
        guard data.count <= Self.maximumMessageBytes else {
            throw DesktopBridgeError.invalidRequest("request_too_large")
        }
        let object = try JSONSerialization.jsonObject(with: data)
        guard let request = object as? [String: Any] else {
            throw DesktopBridgeError.invalidRequest("request_must_be_object")
        }
        return request
    }

    private func writeResponse(_ response: [String: Any], to fd: Int32) {
        guard JSONSerialization.isValidJSONObject(response),
              var data = try? JSONSerialization.data(withJSONObject: response) else {
            return
        }
        data.append(0x0A)
        if data.count > Self.maximumMessageBytes { return }
        data.withUnsafeBytes { rawBuffer in
            guard let base = rawBuffer.baseAddress else { return }
            var offset = 0
            while offset < rawBuffer.count {
                let count = Darwin.write(fd, base.advanced(by: offset), rawBuffer.count - offset)
                if count > 0 {
                    offset += count
                } else if count < 0 && errno == EINTR {
                    continue
                } else {
                    break
                }
            }
        }
    }

    private static func resolveSocketPath(environment: [String: String]) -> String {
        if let configured = environment["RAG_IME_DESKTOP_BRIDGE_SOCKET"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !configured.isEmpty {
            return NSString(string: configured).expandingTildeInPath
        }
        let support = environment["RAG_IME_APP_SUPPORT_DIR"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let base = support.flatMap { $0.isEmpty ? nil : NSString(string: $0).expandingTildeInPath }
            ?? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/RagIme")
                .path
        return URL(fileURLWithPath: base).appendingPathComponent("desktop-bridge.sock").path
    }
}

func boundedString(_ value: Any?, maximum: Int) -> String {
    let text = (value as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    return String(text.prefix(maximum))
}
