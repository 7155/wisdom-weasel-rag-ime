import Foundation

struct VoiceThirdPassResult: Equatable {
    let text: String
    let changed: Bool
    let model: String
}

enum VoiceThirdPassRefiner {
    static let enabledDefaultsKey = "thirdPassRefinementEnabled"
    static var isEnabled: Bool {
        UserDefaults.standard.object(forKey: enabledDefaultsKey) as? Bool ?? false
    }

    private static let endpoint = URL(string: "http://127.0.0.1:8768/api/agent/surface/refine-voice")!
    private static let latencyBudgetMs = 12_000

    @discardableResult
    static func refine(
        transcript: String,
        appBundleIdentifier: String,
        hotwords: [String],
        requestID: String,
        completion: @escaping @Sendable (Result<VoiceThirdPassResult, Error>) -> Void
    ) -> URLSessionDataTask? {
        let payload: [String: Any] = [
            "schemaVersion": "rag-ime.voice-refinement-request.v1",
            "requestId": requestID,
            "frontAppBundleId": appBundleIdentifier,
            "privacyDisposition": "allowed",
            "transcript": transcript,
            "hotwords": Array(hotwords.prefix(32)),
            "latencyBudgetMs": latencyBudgetMs,
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            completion(.failure(VoiceThirdPassError.invalidRequest))
            return nil
        }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 14
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        let task = URLSession(configuration: .ephemeral).dataTask(with: request) { data, response, error in
            if let error {
                completion(.failure(error))
                return
            }
            guard let http = response as? HTTPURLResponse,
                  (200..<300).contains(http.statusCode),
                  let data,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  payload["ok"] as? Bool == true,
                  let text = payload["text"] as? String,
                  !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                completion(.failure(VoiceThirdPassError.invalidResponse))
                return
            }
            completion(.success(VoiceThirdPassResult(
                text: text.trimmingCharacters(in: .whitespacesAndNewlines),
                changed: payload["changed"] as? Bool == true,
                model: payload["model"] as? String ?? ""
            )))
        }
        task.resume()
        return task
    }
}

enum VoiceThirdPassError: LocalizedError {
    case invalidRequest
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .invalidRequest:
            return "无法生成第三遍校对请求"
        case .invalidResponse:
            return "第三遍校对没有返回可用文本"
        }
    }
}
