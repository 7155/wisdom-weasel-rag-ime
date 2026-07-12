import Foundation

enum VoiceCommitRecorder {
    private static let endpoint = URL(string: "http://127.0.0.1:8766/api/commit")!

    static func record(text: String, appBundleIdentifier: String) {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        let payload: [String: Any] = [
            "text": value,
            "project": "wisdom-weasel-rag-ime",
            "app": appBundleIdentifier,
            "providerName": "voice_streaming_asr",
            "tags": ["voice-input", "recent-input"],
            "source": "voice_streaming_asr",
            "privacyDisposition": "allowed",
            "sensitiveField": false,
            "secureInput": false,
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 1.5
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        URLSession(configuration: .ephemeral).dataTask(with: request).resume()
    }
}
