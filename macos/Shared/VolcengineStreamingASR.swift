import Foundation

enum VoiceASREvent: Equatable {
    case partial(String)
    case final(String)
    case failure(String)
    case transport(String)
}

enum VoiceASRMessageType: UInt8 {
    case fullClientRequest = 0x1
    case audioOnlyRequest = 0x2
    case fullServerResponse = 0x9
    case error = 0xF
}

enum VoiceASRFlags: UInt8 {
    case none = 0x0
    case positiveSequence = 0x1
    case lastPacket = 0x2
    case negativeSequence = 0x3
}

struct VoiceASRParsedFrame: Equatable {
    let messageType: VoiceASRMessageType?
    let flags: UInt8
    let sequence: Int32?
    let errorCode: UInt32?
    let payload: Data

    var isFinal: Bool {
        flags == VoiceASRFlags.lastPacket.rawValue
            || flags == VoiceASRFlags.negativeSequence.rawValue
            || (sequence ?? 0) < 0
    }
}

enum VoiceASRFrame {
    static func build(
        messageType: VoiceASRMessageType,
        flags: VoiceASRFlags,
        serializationJSON: Bool,
        payload: Data,
        sequence: Int32? = nil
    ) -> Data {
        var data = Data([0x11, (messageType.rawValue << 4) | flags.rawValue, serializationJSON ? 0x10 : 0x00, 0x00])
        if flags == .positiveSequence || flags == .negativeSequence, let sequence {
            appendBigEndian(sequence, to: &data)
        }
        appendBigEndian(UInt32(payload.count), to: &data)
        data.append(payload)
        return data
    }

    static func parse(_ data: Data) -> VoiceASRParsedFrame? {
        let bytes = [UInt8](data)
        guard bytes.count >= 8 else { return nil }
        let headerSize = Int(bytes[0] & 0x0F) * 4
        guard headerSize >= 4, bytes.count >= headerSize + 4 else { return nil }
        let messageType = VoiceASRMessageType(rawValue: (bytes[1] >> 4) & 0x0F)
        let flags = bytes[1] & 0x0F
        let compression = bytes[2] & 0x0F
        guard compression == 0 else { return nil }

        var offset = headerSize
        var sequence: Int32?
        if flags == VoiceASRFlags.positiveSequence.rawValue || flags == VoiceASRFlags.negativeSequence.rawValue {
            guard let raw: UInt32 = readBigEndian(bytes, at: offset) else { return nil }
            sequence = Int32(bitPattern: raw)
            offset += 4
        }

        if messageType == .error {
            guard let code: UInt32 = readBigEndian(bytes, at: offset),
                  let size: UInt32 = readBigEndian(bytes, at: offset + 4) else { return nil }
            offset += 8
            guard bytes.count >= offset + Int(size) else { return nil }
            return VoiceASRParsedFrame(
                messageType: messageType,
                flags: flags,
                sequence: sequence,
                errorCode: code,
                payload: Data(bytes[offset..<(offset + Int(size))])
            )
        }

        guard let size: UInt32 = readBigEndian(bytes, at: offset) else { return nil }
        offset += 4
        guard bytes.count >= offset + Int(size) else { return nil }
        return VoiceASRParsedFrame(
            messageType: messageType,
            flags: flags,
            sequence: sequence,
            errorCode: nil,
            payload: Data(bytes[offset..<(offset + Int(size))])
        )
    }

    private static func appendBigEndian<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
        var bigEndian = value.bigEndian
        withUnsafeBytes(of: &bigEndian) { data.append(contentsOf: $0) }
    }

    private static func readBigEndian<T: FixedWidthInteger>(_ bytes: [UInt8], at offset: Int) -> T? {
        let width = MemoryLayout<T>.size
        guard offset >= 0, bytes.count >= offset + width else { return nil }
        return bytes[offset..<(offset + width)].reduce(T.zero) { ($0 << 8) | T($1) }
    }
}

struct VoiceTranscriptRevision: Equatable {
    let replacementUTF16Length: Int
    let text: String
    let isFinal: Bool
}

struct VoiceTranscriptReconciler {
    private(set) var currentText = ""

    mutating func revise(to text: String, isFinal: Bool) -> VoiceTranscriptRevision? {
        guard !text.isEmpty, text != currentText || isFinal else { return nil }
        let revision = VoiceTranscriptRevision(
            replacementUTF16Length: currentText.utf16.count,
            text: text,
            isFinal: isFinal
        )
        currentText = text
        return revision
    }

    mutating func clear() -> VoiceTranscriptRevision? {
        guard !currentText.isEmpty else { return nil }
        let revision = VoiceTranscriptRevision(
            replacementUTF16Length: currentText.utf16.count,
            text: "",
            isFinal: true
        )
        currentText = ""
        return revision
    }
}

final class VolcengineStreamingASRClient: NSObject, URLSessionWebSocketDelegate, VoiceStreamingASRClient, @unchecked Sendable {
    static let endpoint = URL(string: "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async")!
    static let audioChunkBytes = 6_400

    private let credentials: VoiceASRCredentials
    private let hotwordConfig: VoiceASRHotwordConfig
    private let callback: @Sendable (VoiceASREvent) -> Void
    private let queue = DispatchQueue(label: "com.rag-ime.voice.volcengine")
    private let cancellationLock = NSLock()
    private var cancellationRequested = false
    private var urlSession: URLSession?
    private var webSocket: URLSessionWebSocketTask?
    private var outboundFrames: [Data] = []
    private var sending = false
    private var nextSequence: Int32 = 1
    private var pendingAudio = Data()
    private var lastTranscript = ""
    private var terminated = false

    init(
        credentials: VoiceASRCredentials,
        hotwordConfig: VoiceASRHotwordConfig = .disabled,
        callback: @escaping @Sendable (VoiceASREvent) -> Void
    ) {
        self.credentials = credentials
        self.hotwordConfig = hotwordConfig
        self.callback = callback
        super.init()
    }

    func start() {
        guard !wasCancellationRequested() else { return }
        queue.async { [weak self] in self?.startOnQueue() }
    }

    func appendPCM(_ data: Data) {
        guard !data.isEmpty, !wasCancellationRequested() else { return }
        queue.async { [weak self] in self?.appendPCMOnQueue(data) }
    }

    func finish() {
        guard !wasCancellationRequested() else { return }
        queue.async { [weak self] in self?.finishOnQueue() }
    }

    func cancel() {
        requestCancellation()
        queue.async { [weak self] in self?.terminate(closeCode: .goingAway) }
    }

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        queue.async { [weak self] in
            guard let self, !self.terminated, !self.wasCancellationRequested() else { return }
            self.callback(.transport("connected"))
        }
    }

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        queue.async { [weak self] in
            guard let self, !self.wasCancellationRequested() else { return }
            self.callback(.transport(closeCode == .normalClosure ? "closed" : "disconnected"))
        }
    }

    private func startOnQueue() {
        guard !terminated, !wasCancellationRequested(), webSocket == nil else { return }
        var request = URLRequest(url: Self.endpoint)
        request.timeoutInterval = 5
        request.setValue(credentials.appID, forHTTPHeaderField: "X-Api-App-Key")
        request.setValue(credentials.accessToken, forHTTPHeaderField: "X-Api-Access-Key")
        request.setValue(credentials.resourceID, forHTTPHeaderField: "X-Api-Resource-Id")
        let connectID = UUID().uuidString.lowercased()
        request.setValue(connectID, forHTTPHeaderField: "X-Api-Connect-Id")

        let session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)
        let task = session.webSocketTask(with: request)
        urlSession = session
        webSocket = task
        task.resume()
        callback(.transport("connecting"))

        let payload = Self.initialRequestPayload(connectID: connectID, hotwordConfig: hotwordConfig)
        do {
            let body = try JSONSerialization.data(withJSONObject: payload)
            enqueue(VoiceASRFrame.build(
                messageType: .fullClientRequest,
                flags: .positiveSequence,
                serializationJSON: true,
                payload: body,
                sequence: allocateSequence()
            ))
            receiveNext()
        } catch {
            fail("ASR 请求编码失败")
        }
    }

    static func initialRequestPayload(
        connectID: String,
        hotwordConfig: VoiceASRHotwordConfig
    ) -> [String: Any] {
        var request: [String: Any] = [
            "model_name": "bigmodel",
            "enable_itn": true,
            "enable_punc": true,
            // DDC removes filler words, stutters and semantic repetition from
            // the provider's revised transcript. It complements the final
            // non-streaming pass below; enable_nonstream alone only asks for
            // the more accurate second recognition pass.
            "enable_ddc": true,
            // Full snapshots let the final second-pass result replace earlier
            // text instead of being appended to it.
            "enable_nonstream": true,
            "result_type": "full",
            "show_utterances": true,
        ]
        if let context = hotwordConfig.requestContextJSONString() {
            // Volcengine's request-level hotword contract expects a JSON
            // string in request.context rather than a nested JSON object.
            request["context"] = context
        }
        return [
            "user": ["uid": connectID],
            "audio": ["format": "pcm", "rate": 16_000, "bits": 16, "channel": 1, "codec": "raw"],
            "request": request,
        ]
    }

    private func appendPCMOnQueue(_ data: Data) {
        guard !terminated, !wasCancellationRequested() else { return }
        pendingAudio.append(data)
        while pendingAudio.count >= Self.audioChunkBytes {
            let chunk = pendingAudio.prefix(Self.audioChunkBytes)
            pendingAudio.removeFirst(Self.audioChunkBytes)
            enqueueAudio(Data(chunk))
        }
    }

    private func finishOnQueue() {
        guard !terminated, !wasCancellationRequested() else { return }
        if !pendingAudio.isEmpty {
            enqueueAudio(pendingAudio)
            pendingAudio.removeAll(keepingCapacity: false)
        }
        let finalSequence = -allocateSequence()
        enqueue(VoiceASRFrame.build(
            messageType: .audioOnlyRequest,
            flags: .negativeSequence,
            serializationJSON: false,
            payload: Data(),
            sequence: finalSequence
        ))
    }

    private func enqueueAudio(_ data: Data) {
        enqueue(VoiceASRFrame.build(
            messageType: .audioOnlyRequest,
            flags: .positiveSequence,
            serializationJSON: false,
            payload: data,
            sequence: allocateSequence()
        ))
    }

    private func allocateSequence() -> Int32 {
        defer { nextSequence += 1 }
        return nextSequence
    }

    private func enqueue(_ frame: Data) {
        guard !wasCancellationRequested() else { return }
        outboundFrames.append(frame)
        sendNextIfNeeded()
    }

    private func sendNextIfNeeded() {
        guard !sending,
              !outboundFrames.isEmpty,
              let webSocket,
              !terminated,
              !wasCancellationRequested() else { return }
        sending = true
        let frame = outboundFrames.removeFirst()
        webSocket.send(.data(frame)) { [weak self] error in
            guard let self else { return }
            self.queue.async {
                self.sending = false
                if error != nil {
                    self.fail("ASR 网络发送失败")
                    return
                }
                self.sendNextIfNeeded()
            }
        }
    }

    private func requestCancellation() {
        cancellationLock.lock()
        cancellationRequested = true
        cancellationLock.unlock()
    }

    private func wasCancellationRequested() -> Bool {
        cancellationLock.lock()
        defer { cancellationLock.unlock() }
        return cancellationRequested
    }

    private func receiveNext() {
        guard let webSocket, !terminated else { return }
        webSocket.receive { [weak self] result in
            guard let self else { return }
            self.queue.async {
                switch result {
                case .failure:
                    if !self.terminated { self.fail("ASR 连接中断") }
                case .success(let message):
                    switch message {
                    case .data(let data): self.handle(data)
                    case .string(let text): self.handle(Data(text.utf8))
                    @unknown default: break
                    }
                    if !self.terminated { self.receiveNext() }
                }
            }
        }
    }

    private func handle(_ data: Data) {
        guard let frame = VoiceASRFrame.parse(data) else { return }
        if frame.messageType == .error {
            let detail = String(data: frame.payload, encoding: .utf8) ?? ""
            fail("ASR 服务错误 \(frame.errorCode ?? 0)\(detail.isEmpty ? "" : "：\(detail.prefix(80))")")
            return
        }
        guard frame.messageType == .fullServerResponse,
              let json = try? JSONSerialization.jsonObject(with: frame.payload) as? [String: Any] else { return }
        let text = Self.transcript(from: json)
        if !text.isEmpty { lastTranscript = text }
        if frame.isFinal {
            callback(.final(text.isEmpty ? lastTranscript : text))
            terminate(closeCode: .normalClosure)
        } else if !text.isEmpty {
            callback(.partial(text))
        }
    }

    static func transcript(from json: [String: Any]) -> String {
        let result: [String: Any]?
        if let object = json["result"] as? [String: Any] {
            result = object
        } else if let array = json["result"] as? [[String: Any]] {
            result = array.first
        } else if json["text"] is String {
            result = json
        } else {
            result = nil
        }
        guard let result else { return "" }
        if let text = result["text"] as? String, !text.isEmpty {
            return text
        }
        if let utterances = result["utterances"] as? [[String: Any]] {
            let joined = utterances.compactMap { $0["text"] as? String }.joined()
            if !joined.isEmpty { return joined }
        }
        return ""
    }

    private func fail(_ message: String) {
        guard !terminated else { return }
        callback(.failure(message))
        terminate(closeCode: .goingAway)
    }

    private func terminate(closeCode: URLSessionWebSocketTask.CloseCode) {
        guard !terminated else { return }
        terminated = true
        outboundFrames.removeAll()
        pendingAudio.removeAll()
        webSocket?.cancel(with: closeCode, reason: nil)
        webSocket = nil
        urlSession?.invalidateAndCancel()
        urlSession = nil
    }
}
