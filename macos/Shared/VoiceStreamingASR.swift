import Foundation

protocol VoiceStreamingASRClient: AnyObject {
    func start()
    func appendPCM(_ data: Data)
    func finish()
    func cancel()
}

enum VoiceStreamingASRFactory {
    static func make(
        credentials: VoiceASRCredentials,
        hotwordConfig: VoiceASRHotwordConfig,
        callback: @escaping @Sendable (VoiceASREvent) -> Void
    ) -> VoiceStreamingASRClient {
        switch credentials.provider {
        case .nativeStreaming:
            return VolcengineStreamingASRClient(
                credentials: credentials,
                hotwordConfig: hotwordConfig,
                callback: callback
            )
        case .realtimeWebSocket:
            return RealtimeWebSocketASRClient(credentials: credentials, callback: callback)
        }
    }
}

final class RealtimeWebSocketASRClient: NSObject, URLSessionWebSocketDelegate, VoiceStreamingASRClient, @unchecked Sendable {
    private let credentials: VoiceASRCredentials
    private let callback: @Sendable (VoiceASREvent) -> Void
    private let queue = DispatchQueue(label: "com.rag-ime.voice.realtime-websocket")
    private var session: URLSession?
    private var socket: URLSessionWebSocketTask?
    private var queuedPCM: [Data] = []
    private var opened = false
    private var terminated = false
    private var transcript = ""

    init(credentials: VoiceASRCredentials, callback: @escaping @Sendable (VoiceASREvent) -> Void) {
        self.credentials = credentials
        self.callback = callback
        super.init()
    }

    func start() { queue.async { [weak self] in self?.startOnQueue() } }
    func appendPCM(_ data: Data) {
        guard !data.isEmpty else { return }
        queue.async { [weak self] in self?.appendOnQueue(data) }
    }
    func finish() { queue.async { [weak self] in self?.finishOnQueue() } }
    func cancel() { queue.async { [weak self] in self?.terminate(code: .goingAway) } }

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        queue.async { [weak self] in
            guard let self, !self.terminated else { return }
            self.opened = true
            self.callback(.transport("connected"))
            self.send([
                "type": "session.update",
                "session": [
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": ["model": self.credentials.model],
                ],
            ])
            let waiting = self.queuedPCM
            self.queuedPCM.removeAll(keepingCapacity: false)
            waiting.forEach { self.sendAudio($0) }
        }
    }

    func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        queue.async { [weak self] in
            guard let self, !self.terminated else { return }
            self.callback(.transport(closeCode == .normalClosure ? "closed" : "disconnected"))
        }
    }

    private func startOnQueue() {
        guard !terminated,
              socket == nil,
              let endpoint = URL(string: credentials.endpoint),
              ["wss", "ws"].contains(endpoint.scheme?.lowercased() ?? "") else {
            fail("语音服务端点无效")
            return
        }
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = 8
        request.setValue("Bearer \(credentials.accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("realtime=v1", forHTTPHeaderField: "OpenAI-Beta")
        let session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)
        let socket = session.webSocketTask(with: request)
        self.session = session
        self.socket = socket
        callback(.transport("connecting"))
        socket.resume()
        receiveNext()
    }

    private func appendOnQueue(_ data: Data) {
        guard !terminated else { return }
        if opened { sendAudio(data) } else { queuedPCM.append(data) }
    }

    private func sendAudio(_ data: Data) {
        send(["type": "input_audio_buffer.append", "audio": data.base64EncodedString()])
    }

    private func finishOnQueue() {
        guard !terminated else { return }
        send(["type": "input_audio_buffer.commit"])
    }

    private func send(_ object: [String: Any]) {
        guard !terminated,
              let socket,
              let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        socket.send(.string(text)) { [weak self] error in
            guard error != nil else { return }
            self?.queue.async { self?.fail("语音服务发送失败") }
        }
    }

    private func receiveNext() {
        guard let socket, !terminated else { return }
        socket.receive { [weak self] result in
            guard let self else { return }
            self.queue.async {
                switch result {
                case .failure:
                    self.fail("语音服务连接中断")
                case .success(let message):
                    let data: Data
                    switch message {
                    case .data(let value): data = value
                    case .string(let value): data = Data(value.utf8)
                    @unknown default: data = Data()
                    }
                    self.handle(data)
                    if !self.terminated { self.receiveNext() }
                }
            }
        }
    }

    private func handle(_ data: Data) {
        guard let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        let type = event["type"] as? String ?? ""
        if type == "error" {
            let error = event["error"] as? [String: Any]
            fail((error?["message"] as? String).map { "语音服务错误：\($0)" } ?? "语音服务返回错误")
            return
        }
        if Self.deltaEventTypes.contains(type), let delta = event["delta"] as? String, !delta.isEmpty {
            transcript += delta
            callback(.partial(transcript))
            return
        }
        if Self.completedEventTypes.contains(type) {
            let final = (event["transcript"] as? String)
                ?? (event["text"] as? String)
                ?? transcript
            callback(.final(final))
            terminate(code: .normalClosure)
        }
    }

    static let deltaEventTypes: Set<String> = [
        "conversation.item.input_audio_transcription.delta",
        "transcription.delta",
        "response.audio_transcript.delta",
    ]
    static let completedEventTypes: Set<String> = [
        "conversation.item.input_audio_transcription.completed",
        "transcription.completed",
        "transcript.final",
    ]

    private func fail(_ message: String) {
        guard !terminated else { return }
        callback(.failure(message))
        terminate(code: .goingAway)
    }

    private func terminate(code: URLSessionWebSocketTask.CloseCode) {
        guard !terminated else { return }
        terminated = true
        queuedPCM.removeAll(keepingCapacity: false)
        socket?.cancel(with: code, reason: nil)
        socket = nil
        session?.invalidateAndCancel()
        session = nil
    }
}
