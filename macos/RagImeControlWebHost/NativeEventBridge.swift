import Foundation

final class NativeEventBridge: NSObject, URLSessionDataDelegate {
    private final class SubscriptionState {
        let subscriptionId: String
        var buffer = Data()
        var lastEventId: String

        init(subscriptionId: String, lastEventId: String) {
            self.subscriptionId = subscriptionId
            self.lastEventId = lastEventId
        }
    }

    typealias EventEmitter = ([String: Any]) -> Void

    private let emit: EventEmitter
    private let lock = NSLock()
    private let delegateQueue: OperationQueue
    private var statesByTaskId: [Int: SubscriptionState] = [:]
    private var tasksBySubscriptionId: [String: URLSessionDataTask] = [:]
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 24 * 60 * 60
        configuration.httpMaximumConnectionsPerHost = 4
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration, delegate: self, delegateQueue: delegateQueue)
    }()

    init(emit: @escaping EventEmitter) {
        self.emit = emit
        self.delegateQueue = OperationQueue()
        self.delegateQueue.name = "com.rag-ime.control.native-events"
        self.delegateQueue.maxConcurrentOperationCount = 1
        self.delegateQueue.qualityOfService = .userInitiated
        super.init()
    }

    func subscribe(subscriptionId: String, request: URLRequest, lastEventId: String) throws {
        guard !subscriptionId.isEmpty, subscriptionId.utf8.count <= 160 else {
            throw NativeRoutePolicyError.invalidParameter("subscriptionId")
        }
        lock.lock()
        defer { lock.unlock() }
        guard tasksBySubscriptionId[subscriptionId] == nil else {
            throw NativeRoutePolicyError.invalidParameter("duplicate subscriptionId")
        }
        let task = session.dataTask(with: request)
        statesByTaskId[task.taskIdentifier] = SubscriptionState(
            subscriptionId: subscriptionId,
            lastEventId: lastEventId
        )
        tasksBySubscriptionId[subscriptionId] = task
        task.resume()
    }

    @discardableResult
    func cancel(subscriptionId: String) -> Bool {
        lock.lock()
        let task = tasksBySubscriptionId.removeValue(forKey: subscriptionId)
        if let task {
            statesByTaskId.removeValue(forKey: task.taskIdentifier)
        }
        lock.unlock()
        task?.cancel()
        return task != nil
    }

    func cancelAll() {
        lock.lock()
        let tasks = Array(tasksBySubscriptionId.values)
        tasksBySubscriptionId.removeAll()
        statesByTaskId.removeAll()
        lock.unlock()
        tasks.forEach { $0.cancel() }
        session.invalidateAndCancel()
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode),
              http.mimeType == "text/event-stream" else {
            if let state = state(for: dataTask.taskIdentifier) {
                emit(errorEnvelope(
                    subscriptionId: state.subscriptionId,
                    code: "invalid_sse_response",
                    message: "Subscription endpoint rejected the stream"
                ))
            }
            completionHandler(.cancel)
            return
        }
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard let state = state(for: dataTask.taskIdentifier) else { return }
        state.buffer.append(data)
        guard state.buffer.count <= 1_048_576 else {
            emit(errorEnvelope(
                subscriptionId: state.subscriptionId,
                code: "sse_buffer_overflow",
                message: "Subscription buffer exceeded 1 MiB"
            ))
            dataTask.cancel()
            return
        }

        let delimiter = Data("\n\n".utf8)
        while let range = state.buffer.range(of: delimiter) {
            let eventData = state.buffer.subdata(in: state.buffer.startIndex..<range.lowerBound)
            state.buffer.removeSubrange(state.buffer.startIndex..<range.upperBound)
            guard eventData.count <= 262_144 else {
                emit(errorEnvelope(
                    subscriptionId: state.subscriptionId,
                    code: "sse_event_overflow",
                    message: "Subscription event exceeded 256 KiB"
                ))
                dataTask.cancel()
                return
            }
            if let envelope = parse(eventData, state: state) {
                emit(envelope)
            }
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        guard let state = removeState(for: task.taskIdentifier) else { return }
        if let error = error as NSError?, error.code != NSURLErrorCancelled {
            emit(errorEnvelope(
                subscriptionId: state.subscriptionId,
                code: "subscription_disconnected",
                message: error.localizedDescription,
                retryable: true
            ))
        } else {
            emit([
                "subscriptionId": state.subscriptionId,
                "kind": "complete",
                "lastEventId": state.lastEventId,
            ])
        }
    }

    private func parse(_ data: Data, state: SubscriptionState) -> [String: Any]? {
        guard let text = String(data: data, encoding: .utf8) else { return nil }
        var dataLines: [String] = []
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = rawLine.last == "\r" ? rawLine.dropLast() : rawLine[...]
            if line.hasPrefix("id:") {
                let value = line.dropFirst(3).trimmingCharacters(in: .whitespaces)
                if value.utf8.count <= 512, !value.contains("\0") {
                    state.lastEventId = value
                }
            } else if line.hasPrefix("data:") {
                dataLines.append(line.dropFirst(5).trimmingCharacters(in: .whitespaces))
            }
        }
        guard !dataLines.isEmpty else { return nil }
        let payloadText = dataLines.joined(separator: "\n")
        let payloadData = Data(payloadText.utf8)
        let payload = (try? JSONSerialization.jsonObject(with: payloadData)) ?? ["text": payloadText]
        return [
            "subscriptionId": state.subscriptionId,
            "kind": "event",
            "event": payload,
            "lastEventId": state.lastEventId,
        ]
    }

    private func state(for taskId: Int) -> SubscriptionState? {
        lock.lock()
        defer { lock.unlock() }
        return statesByTaskId[taskId]
    }

    private func removeState(for taskId: Int) -> SubscriptionState? {
        lock.lock()
        defer { lock.unlock() }
        guard let state = statesByTaskId.removeValue(forKey: taskId) else { return nil }
        tasksBySubscriptionId.removeValue(forKey: state.subscriptionId)
        return state
    }

    private func errorEnvelope(
        subscriptionId: String,
        code: String,
        message: String,
        retryable: Bool = false
    ) -> [String: Any] {
        [
            "subscriptionId": subscriptionId,
            "kind": "error",
            "error": [
                "code": code,
                "message": message,
                "retryable": retryable,
            ],
        ]
    }
}
