import Foundation

actor AgentAPIClient {
    private let baseURL: URL
    private let session: URLSession

    init(baseURL: URL = URL(string: "http://127.0.0.1:8766")!) {
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 24 * 60 * 60
        self.session = URLSession(configuration: configuration)
    }

    func runtimeStatus() async throws -> AgentRuntimeStatus {
        try await get(path: ["api", "agent", "runtime"])
    }

    func sessions(includeArchived: Bool) async throws -> AgentSessionListResponse {
        try await get(
            path: ["api", "agent", "sessions"],
            query: [URLQueryItem(name: "includeArchived", value: includeArchived ? "true" : "false")]
        )
    }

    func tools() async throws -> AgentToolListResponse {
        try await get(path: ["api", "agent", "tools"])
    }

    func roles() async throws -> AgentRoleListResponse {
        try await get(path: ["api", "agent", "roles"])
    }

    func rooms(includeArchived: Bool) async throws -> AgentRoomListResponse {
        try await get(
            path: ["api", "agent", "rooms"],
            query: [URLQueryItem(name: "includeArchived", value: includeArchived ? "true" : "false")]
        )
    }

    func room(id: String) async throws -> AgentRoomGetResponse {
        try await get(path: ["api", "agent", "rooms", id])
    }

    func createRoom(
        title: String,
        participants: [AgentRoleSummary],
        routingPolicy: String,
        moderatorRoleId: String
    ) async throws -> AgentRoomMutationResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "rooms"],
            body: [
                "title": .string(title),
                "routingPolicy": .string(routingPolicy),
                "moderatorRoleId": .string(moderatorRoleId),
                "participants": .array(participants.map { role in
                    .object([
                        "roleId": .string(role.roleId),
                        "roleVersion": .string(role.version),
                    ])
                }),
            ]
        )
    }

    func updateRoom(id: String, archived: Bool) async throws -> AgentRoomMutationResponse {
        try await request(
            method: "PATCH",
            path: ["api", "agent", "rooms", id],
            body: ["archived": .bool(archived)]
        )
    }

    func postRoomMessage(id: String, message: String) async throws -> AgentRoomMessageResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "rooms", id, "messages"],
            body: ["message": .string(message)]
        )
    }

    func models(sessionId: String) async throws -> AgentModelCatalogResponse {
        try await get(path: ["api", "agent", "sessions", sessionId, "models"])
    }

    func selectModel(
        sessionId: String,
        provider: String,
        modelId: String
    ) async throws -> AgentModelSelectionResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "sessions", sessionId, "model"],
            body: [
                "provider": .string(provider),
                "modelId": .string(modelId),
            ]
        )
    }

    func selectThinkingLevel(
        sessionId: String,
        level: String
    ) async throws -> AgentThinkingSelectionResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "sessions", sessionId, "thinking"],
            body: ["level": .string(level)]
        )
    }

    func approvals(sessionId: String) async throws -> AgentApprovalListResponse {
        try await get(
            path: ["api", "agent", "approvals"],
            query: [URLQueryItem(name: "sessionId", value: sessionId)]
        )
    }

    func memorySources(sessionId: String) async throws -> AgentMemorySourceListResponse {
        try await get(
            path: ["api", "agent", "memory-sources"],
            query: [URLQueryItem(name: "sessionId", value: sessionId)]
        )
    }

    func memoryMaintenance(project: String = "", limit: Int = 8) async throws -> AgentMemoryMaintenanceStatus {
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if !project.isEmpty {
            query.append(URLQueryItem(name: "project", value: project))
        }
        return try await get(
            path: ["api", "agent", "memory-maintenance"],
            query: query
        )
    }

    func media(sessionId: String) async throws -> AgentMediaListResponse {
        try await get(
            path: ["api", "agent", "media"],
            query: [URLQueryItem(name: "sessionId", value: sessionId)]
        )
    }

    func importMedia(
        sessionId: String,
        fileName: String,
        mimeType: String,
        data: Data
    ) async throws -> AgentMediaImportResponse {
        var components = URLComponents(url: url(path: ["api", "agent", "media", "import"]), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "sessionId", value: sessionId),
            URLQueryItem(name: "fileName", value: fileName),
        ]
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.setValue(mimeType, forHTTPHeaderField: "Content-Type")
        request.httpBody = data
        let (responseData, response) = try await session.data(for: request)
        return try decode(responseData, response: response)
    }

    func mediaReceipt(mediaId: String, sessionId: String) async throws -> AgentMediaReceipt {
        let response: AgentMediaGetResponse = try await get(
            path: ["api", "agent", "media", mediaId, "receipt"],
            query: [URLQueryItem(name: "sessionId", value: sessionId)]
        )
        return response.media
    }

    func mediaData(mediaId: String, sessionId: String) async throws -> Data {
        var components = URLComponents(
            url: url(path: ["api", "agent", "media", mediaId, "content"]),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "sessionId", value: sessionId)]
        let (data, response) = try await session.data(from: components.url!)
        guard let http = response as? HTTPURLResponse else { throw APIClientError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw APIClientError.server(http.statusCode, message ?? "媒体读取失败")
        }
        return data
    }

    func decideApproval(
        id: String,
        payloadSha256: String,
        approved: Bool
    ) async throws -> AgentApprovalDecisionResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "approvals", id, "decision"],
            body: [
                "decision": .string(approved ? "approve" : "reject"),
                "payloadSha256": .string(payloadSha256),
            ],
            timeoutInterval: approved ? 110 : nil
        )
    }

    func finalizeExternalApproval(
        approval: AgentApproval,
        succeeded: Bool,
        exitCode: Int32,
        timedOut: Bool,
        error: String = ""
    ) async throws -> AgentApprovalDecisionResponse {
        let receipt = approval.receipt?.objectValue ?? [:]
        let action = receipt["externalAction"]?.stringValue ?? ""
        let commandSha256 = receipt["externalCommandSha256"]?.stringValue ?? ""
        guard !action.isEmpty, commandSha256.count == 64 else {
            throw APIClientError.server(409, "外部审批回执缺少受管动作或命令摘要")
        }
        return try await request(
            method: "POST",
            path: ["api", "agent", "approvals", approval.approvalId, "external-result"],
            body: [
                "payloadSha256": .string(approval.payloadSha256),
                "externalAction": .string(action),
                "externalCommandSha256": .string(commandSha256),
                "succeeded": .bool(succeeded),
                "exitCode": .number(Double(exitCode)),
                "timedOut": .bool(timedOut),
                "error": .string(String(error.prefix(240))),
            ],
            timeoutInterval: 15
        )
    }

    func createSession(
        title: String,
        mode: String = "assistant",
        roleId: String = "zhiyou-v1",
        roleVersion: String = "1",
        workspaceRoots: [String] = []
    ) async throws -> AgentSessionMutationResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "sessions"],
            body: [
                "title": .string(title),
                "mode": .string(mode),
                "roleId": .string(roleId),
                "roleVersion": .string(roleVersion),
                "workspaceRoots": .array(workspaceRoots.map(JSONValue.string)),
            ]
        )
    }

    func setEnabled(_ enabled: Bool) async throws -> MutationResponse {
        try await request(
            method: "POST",
            path: ["api", "settings", "update"],
            body: [
                "agent.pi.enabled": .bool(enabled),
                "updatedBy": .string("native-agent-workspace"),
            ]
        )
    }

    func updateSession(
        id: String,
        title: String? = nil,
        archived: Bool? = nil,
        mode: String? = nil,
        workspaceRoots: [String]? = nil
    ) async throws -> AgentSessionMutationResponse {
        var body: [String: JSONValue] = [:]
        if let title { body["title"] = .string(title) }
        if let archived { body["archived"] = .bool(archived) }
        if let mode { body["mode"] = .string(mode) }
        if let workspaceRoots { body["workspaceRoots"] = .array(workspaceRoots.map(JSONValue.string)) }
        return try await request(
            method: "PATCH",
            path: ["api", "agent", "sessions", id],
            body: body
        )
    }

    func deleteSession(id: String) async throws -> AgentSessionDeleteResponse {
        try await request(
            method: "DELETE",
            path: ["api", "agent", "sessions", id],
            body: [:]
        )
    }

    func messages(sessionId: String) async throws -> AgentMessageListResponse {
        try await get(path: ["api", "agent", "sessions", sessionId, "messages"])
    }

    func prompt(
        sessionId: String,
        message: String,
        attachments: [String] = []
    ) async throws -> AgentPromptAcceptedResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "sessions", sessionId, "prompt"],
            body: [
                "message": .string(message),
                "attachments": .array(attachments.map(JSONValue.string)),
            ]
        )
    }

    func abort(sessionId: String) async throws -> AgentSimpleResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "sessions", sessionId, "abort"],
            body: [:]
        )
    }

    func compact(sessionId: String) async throws -> AgentSimpleResponse {
        try await request(
            method: "POST",
            path: ["api", "agent", "sessions", sessionId, "compact"],
            body: [:]
        )
    }

    func streamEvents(
        sessionId: String,
        afterEventId: String,
        onEvent: @escaping @Sendable (AgentEventEnvelope) async -> Void
    ) async throws {
        var request = URLRequest(url: url(path: ["api", "agent", "sessions", sessionId, "events"]))
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if !afterEventId.isEmpty {
            request.setValue(afterEventId, forHTTPHeaderField: "Last-Event-ID")
        }
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw APIClientError.invalidResponse
        }
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard line.hasPrefix("data: ") else { continue }
            let payload = Data(line.dropFirst(6).utf8)
            let event = try JSONDecoder().decode(AgentEventEnvelope.self, from: payload)
            await onEvent(event)
        }
    }

    func streamRoomEvents(
        roomId: String,
        afterEventId: String,
        onEvent: @escaping @Sendable (AgentRoomEventEnvelope) async -> Void
    ) async throws {
        var request = URLRequest(url: url(path: ["api", "agent", "rooms", roomId, "events"]))
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if !afterEventId.isEmpty {
            request.setValue(afterEventId, forHTTPHeaderField: "Last-Event-ID")
        }
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw APIClientError.invalidResponse
        }
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard line.hasPrefix("data: ") else { continue }
            let payload = Data(line.dropFirst(6).utf8)
            let event = try JSONDecoder().decode(AgentRoomEventEnvelope.self, from: payload)
            await onEvent(event)
        }
    }

    func invalidate() {
        session.invalidateAndCancel()
    }

    private func get<T: Decodable>(path: [String], query: [URLQueryItem] = []) async throws -> T {
        var components = URLComponents(url: url(path: path), resolvingAgainstBaseURL: false)!
        components.queryItems = query.isEmpty ? nil : query
        let (data, response) = try await session.data(from: components.url!)
        return try decode(data, response: response)
    }

    private func request<T: Decodable>(
        method: String,
        path: [String],
        body: [String: JSONValue],
        timeoutInterval: TimeInterval? = nil
    ) async throws -> T {
        var request = URLRequest(url: url(path: path))
        request.httpMethod = method
        if let timeoutInterval { request.timeoutInterval = timeoutInterval }
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await session.data(for: request)
        return try decode(data, response: response)
    }

    private func url(path: [String]) -> URL {
        path.reduce(baseURL) { partial, component in
            partial.appendingPathComponent(component)
        }
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
