import Foundation

enum APIClientError: LocalizedError {
    case invalidResponse
    case server(Int, String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse: return "本地管理服务返回了无法识别的响应"
        case .server(let code, let message): return "本地管理服务错误（\(code)）：\(message)"
        }
    }
}

actor ManagementAPIClient {
    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL = URL(string: "http://127.0.0.1:8766")!) {
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 5
        configuration.timeoutIntervalForResource = 24 * 60 * 60
        self.session = URLSession(configuration: configuration)
    }

    func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        var components = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        components.queryItems = query.isEmpty ? nil : query
        let (data, response) = try await session.data(from: components.url!)
        return try decode(data, response: response)
    }

    func post<T: Decodable>(_ path: String, body: [String: JSONValue]) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await session.data(for: request)
        return try decode(data, response: response)
    }

    func streamEvents(onEvent: @escaping @Sendable (String) async -> Void) async throws {
        let request = URLRequest(url: baseURL.appendingPathComponent("api/events/stream"))
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw APIClientError.invalidResponse }
        for try await line in bytes.lines {
            try Task.checkCancellation()
            if line.hasPrefix("data: ") {
                await onEvent(String(line.dropFirst(6)))
            }
        }
    }

    func invalidate() {
        session.invalidateAndCancel()
    }

    private func decode<T: Decodable>(_ data: Data, response: URLResponse) throws -> T {
        guard let http = response as? HTTPURLResponse else { throw APIClientError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw APIClientError.server(http.statusCode, message ?? "未知错误")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
