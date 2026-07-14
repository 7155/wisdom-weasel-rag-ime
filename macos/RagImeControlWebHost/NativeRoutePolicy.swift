import Foundation

enum NativeTransportScope {
    case local
    case remote
}

enum NativeRoutePolicyError: LocalizedError {
    case unknownPathId(String)
    case routeNotRemoteSafe(String)
    case missingParameter(String)
    case unexpectedParameter(String)
    case invalidParameter(String)
    case unexpectedQuery(String)
    case invalidBody
    case subscriptionRequired(String)
    case requestRequired(String)
    case invalidURL

    var errorDescription: String? {
        switch self {
        case .unknownPathId(let value): return "Unknown pathId: \(value)"
        case .routeNotRemoteSafe(let value): return "Route is not available remotely: \(value)"
        case .missingParameter(let value): return "Missing route parameter: \(value)"
        case .unexpectedParameter(let value): return "Unexpected route parameter: \(value)"
        case .invalidParameter(let value): return "Invalid route parameter: \(value)"
        case .unexpectedQuery(let value): return "Unexpected query parameter: \(value)"
        case .invalidBody: return "Request body is not valid JSON"
        case .subscriptionRequired(let value): return "Route requires subscribe(): \(value)"
        case .requestRequired(let value): return "Route does not support subscribe(): \(value)"
        case .invalidURL: return "Unable to build allowlisted route URL"
        }
    }
}

struct NativeResolvedRoute {
    let pathId: String
    var request: URLRequest
    let isSubscription: Bool
    let remoteSafe: Bool
}

private struct NativeRouteDefinition {
    let method: String
    let localPath: String
    let gatewayPath: String
    let allowedQuery: Set<String>
    let requiredQuery: Set<String>
    let remoteSafe: Bool
    let subscription: Bool
    let allowedBodyKeys: Set<String>
    let requiredBodyKeys: Set<String>
}

final class NativeRoutePolicy {
    private static let facadePathIds: Set<String> = ["control.bootstrap", "control.capabilities"]
    static let knownPathIds: Set<String> = Set(routes.keys).union(facadePathIds)

    private static let routes: [String: NativeRouteDefinition] = {
        func route(
            _ method: String,
            _ localPath: String,
            _ gatewayPath: String,
            query: Set<String> = [],
            requiredQuery: Set<String> = [],
            remoteSafe: Bool = false,
            subscription: Bool = false,
            bodyKeys: Set<String> = [],
            requiredBodyKeys: Set<String> = []
        ) -> NativeRouteDefinition {
            NativeRouteDefinition(
                method: method,
                localPath: localPath,
                gatewayPath: gatewayPath,
                allowedQuery: query,
                requiredQuery: requiredQuery,
                remoteSafe: remoteSafe,
                subscription: subscription,
                allowedBodyKeys: bodyKeys,
                requiredBodyKeys: requiredBodyKeys
            )
        }

        return [
            "control.events": route("GET", "/api/agent/events", "/control/v1/events", remoteSafe: true, subscription: true),
            "system.health": route("GET", "/api/health", "/control/v1/health", remoteSafe: true),
            "overview.get": route("GET", "/api/overview", "/control/v1/overview", remoteSafe: true),
            "input.source.get": route("GET", "/api/input-source", "/control/v1/input/source", remoteSafe: true),
            "agent.runtime.get": route("GET", "/api/agent/runtime", "/control/v1/agent/runtime", remoteSafe: true),
            "agent.runtime.ensure": route("POST", "/api/agent/runtime/ensure", "/control/v1/agent/runtime/ensure", bodyKeys: ["sessionId"], requiredBodyKeys: ["sessionId"]),
            "agent.configuration.get": route("GET", "/api/agent/configuration", "/control/v1/agent/configuration", remoteSafe: true),
            "agent.configuration.update": route("POST", "/api/agent/configuration", "/control/v1/agent/configuration", remoteSafe: true, bodyKeys: ["expectedRevision", "changes", "updatedBy"], requiredBodyKeys: ["expectedRevision", "changes"]),
            "agent.sessions.list": route("GET", "/api/agent/sessions", "/control/v1/agent/sessions", query: ["includeArchived", "includeInternal", "limit"], remoteSafe: true),
            "agent.sessions.create": route("POST", "/api/agent/sessions", "/control/v1/agent/sessions", remoteSafe: true, bodyKeys: ["title", "mode", "roleId", "roleVersion", "modelProfile", "toolProfileVersion", "workspaceRoots"]),
            "agent.session.snapshot": route("GET", "/api/agent/sessions/{sessionId}/messages", "/control/v1/agent/sessions/{sessionId}/snapshot", remoteSafe: true),
            "agent.session.rename": route("PATCH", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", remoteSafe: true, bodyKeys: ["title"], requiredBodyKeys: ["title"]),
            "agent.session.archive": route("PATCH", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", remoteSafe: true, bodyKeys: ["archived"], requiredBodyKeys: ["archived"]),
            "agent.session.mode.update": route("PATCH", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", bodyKeys: ["mode", "workspaceRoots"], requiredBodyKeys: ["mode"]),
            "agent.session.delete": route("DELETE", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}"),
            "agent.session.prompt": route("POST", "/api/agent/sessions/{sessionId}/prompt", "/control/v1/agent/sessions/{sessionId}/prompt", remoteSafe: true, bodyKeys: ["message", "attachments", "clientMessageId"], requiredBodyKeys: ["message"]),
            "agent.session.abort": route("POST", "/api/agent/sessions/{sessionId}/abort", "/control/v1/agent/sessions/{sessionId}/abort", remoteSafe: true),
            "agent.session.compact": route("POST", "/api/agent/sessions/{sessionId}/compact", "/control/v1/agent/sessions/{sessionId}/compact", bodyKeys: ["instructions"]),
            "agent.session.models": route("GET", "/api/agent/sessions/{sessionId}/models", "/control/v1/agent/sessions/{sessionId}/models", remoteSafe: true),
            "agent.session.model.select": route("POST", "/api/agent/sessions/{sessionId}/model", "/control/v1/agent/sessions/{sessionId}/model", remoteSafe: true, bodyKeys: ["provider", "modelId"], requiredBodyKeys: ["provider", "modelId"]),
            "agent.session.thinking.select": route("POST", "/api/agent/sessions/{sessionId}/thinking", "/control/v1/agent/sessions/{sessionId}/thinking", remoteSafe: true, bodyKeys: ["level"], requiredBodyKeys: ["level"]),
            "agent.session.events": route("GET", "/api/agent/sessions/{sessionId}/events", "/control/v1/agent/sessions/{sessionId}/events", remoteSafe: true, subscription: true),
            "agent.session.intercom.list": route("GET", "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", query: ["status", "limit"], remoteSafe: true),
            "agent.session.intercom.send": route("POST", "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", remoteSafe: true, bodyKeys: ["kind", "targetParticipantId", "clientMessageId", "replyTo", "content"], requiredBodyKeys: ["kind", "clientMessageId", "content"]),
            "agent.artifact.get": route("GET", "/api/agent/artifacts/{artifactId}", "/control/v1/agent/artifacts/{artifactId}", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.media.list": route("GET", "/api/agent/media", "/control/v1/agent/media", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.deep-search": route("POST", "/api/agent/deep-search", "/control/v1/agent/deep-search", bodyKeys: ["query", "privacyDisposition", "context", "frontAppBundleId", "contextSource", "evidence"], requiredBodyKeys: ["query", "privacyDisposition"]),
            "agent.rooms.list": route("GET", "/api/agent/rooms", "/control/v1/agent/rooms", query: ["includeArchived", "limit"], remoteSafe: true),
            "agent.rooms.create": route("POST", "/api/agent/rooms", "/control/v1/agent/rooms", remoteSafe: true, bodyKeys: ["title", "participants", "routingPolicy", "moderatorRoleId"], requiredBodyKeys: ["participants"]),
            "agent.room.get": route("GET", "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", remoteSafe: true),
            "agent.room.snapshot": route("GET", "/api/agent/rooms/{roomId}/snapshot", "/control/v1/agent/rooms/{roomId}/snapshot", remoteSafe: true),
            "agent.room.archive": route("PATCH", "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", remoteSafe: true, bodyKeys: ["archived"], requiredBodyKeys: ["archived"]),
            "agent.room.message": route("POST", "/api/agent/rooms/{roomId}/messages", "/control/v1/agent/rooms/{roomId}/messages", remoteSafe: true, bodyKeys: ["message", "clientMessageId"], requiredBodyKeys: ["message"]),
            "agent.room.events": route("GET", "/api/agent/rooms/{roomId}/events", "/control/v1/agent/rooms/{roomId}/events", remoteSafe: true, subscription: true),
            "agent.roles.list": route("GET", "/api/agent/roles", "/control/v1/agent/roles", remoteSafe: true),
            "agent.tools.list": route("GET", "/api/agent/tools", "/control/v1/agent/tools"),
            "agent.approvals.list": route("GET", "/api/agent/approvals", "/control/v1/agent/approvals", query: ["sessionId", "state", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.approval.get": route("GET", "/api/agent/approvals/{approvalId}", "/control/v1/agent/approvals/{approvalId}", remoteSafe: true),
            "agent.approval.decide": route("POST", "/api/agent/approvals/{approvalId}/decision", "/control/v1/agent/approvals/{approvalId}/decision", remoteSafe: true, bodyKeys: ["decision", "payloadSha256"], requiredBodyKeys: ["decision", "payloadSha256"]),
            "agent.subagents.templates": route("GET", "/api/agent/subagents/templates", "/control/v1/agent/subagents/templates", remoteSafe: true),
            "agent.subagents.list": route("GET", "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.subagents.create": route("POST", "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", remoteSafe: true, bodyKeys: ["sessionId", "tasks", "agent", "version", "task", "contextMode", "wait"], requiredBodyKeys: ["sessionId"]),
            "agent.subagent.get": route("GET", "/api/agent/subagents/runs/{runId}", "/control/v1/agent/subagents/runs/{runId}", query: ["sessionId"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.subagent.abort": route("POST", "/api/agent/subagents/runs/{runId}/abort", "/control/v1/agent/subagents/runs/{runId}/abort", remoteSafe: true, bodyKeys: ["sessionId"], requiredBodyKeys: ["sessionId"]),
            "agent.memorySources.list": route("GET", "/api/agent/memory-sources", "/control/v1/agent/memory-sources", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "planning.dashboard": route("GET", "/api/planning/dashboard", "/control/v1/planning/dashboard", query: ["date", "project"], remoteSafe: true),
            "planning.mutation.preview": route("POST", "/api/planning/mutation/preview", "/control/v1/planning/mutation/preview", bodyKeys: ["kind", "payload", "expectedRuntimeRevision"], requiredBodyKeys: ["kind", "payload", "expectedRuntimeRevision"]),
            "planning.task.save": route("POST", "/api/planning/task/save", "/control/v1/planning/task/save", bodyKeys: ["taskId", "date", "title", "detail", "priority", "status", "dueAtMs", "goalId", "project", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["date", "title", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "planning.task.action": route("POST", "/api/planning/task/action", "/control/v1/planning/task/action", bodyKeys: ["taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "planning.taskEvent.undo": route("POST", "/api/planning/task-event/undo", "/control/v1/planning/task-event/undo", bodyKeys: ["eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "planning.mutation.rollback": route("POST", "/api/planning/mutation/rollback", "/control/v1/planning/mutation/rollback", bodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "memory.summary": route("GET", "/api/memory/summary", "/control/v1/memory/summary", remoteSafe: true),
            "memory.pages": route("GET", "/api/memory/{kind}", "/control/v1/memory/{kind}", query: ["limit", "cursor", "query", "status"], remoteSafe: true),
            "memory.graph.get": route("GET", "/api/memory/graph", "/control/v1/memory/graph", query: ["plane", "project", "status", "query", "focusId", "depth", "nodeLimit", "edgeLimit", "minWeight"], requiredQuery: ["plane"], remoteSafe: true),
            "memory.entity.get": route("GET", "/api/memory/entities/{kind}/{entityId}", "/control/v1/memory/entities/{kind}/{entityId}", query: ["project", "connectionsLimit", "connectionsCursor", "membersLimit", "membersCursor"], remoteSafe: true),
            "history.page": route("GET", "/api/history/page", "/control/v1/history/page", query: ["limit", "cursor", "query", "filter"], remoteSafe: true),
            "knowledge.start": route("POST", "/api/knowledge/start", "/control/v1/knowledge/start", bodyKeys: ["question", "context", "mode", "includeNotion", "generation", "contextHash", "clientId", "project", "app", "maxChars", "latencyBudgetMs"], requiredBodyKeys: ["question"]),
            "knowledge.cancel": route("POST", "/api/knowledge/cancel", "/control/v1/knowledge/cancel", bodyKeys: ["sessionId", "id"]),
            "knowledge.status": route("GET", "/api/knowledge/status", "/control/v1/knowledge/status", query: ["sessionId", "id"], remoteSafe: true),
            "knowledge.routeStatus": route("GET", "/api/knowledge/route-status", "/control/v1/knowledge/route-status", remoteSafe: true),
            "knowledge.database.apply.preview": route("POST", "/api/knowledge/database/apply-preview", "/control/v1/knowledge/database/apply-preview", bodyKeys: ["runId", "expectedRuntimeRevision"], requiredBodyKeys: ["runId"]),
            "knowledge.database.apply": route("POST", "/api/knowledge/database/apply", "/control/v1/knowledge/database/apply", bodyKeys: ["runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"], requiredBodyKeys: ["runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"]),
            "knowledge.database.rollback": route("POST", "/api/knowledge/database/rollback", "/control/v1/knowledge/database/rollback", bodyKeys: ["runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"], requiredBodyKeys: ["runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"]),
            "diagnostics.runtime": route("GET", "/api/runtime/status", "/control/v1/diagnostics/runtime", remoteSafe: true),
            "diagnostics.predictor": route("GET", "/api/predictor/status", "/control/v1/diagnostics/predictor", remoteSafe: true),
            "diagnostics.models": route("GET", "/api/models/status", "/control/v1/diagnostics/models", remoteSafe: true),
            "configuration.settings": route("GET", "/api/settings", "/control/v1/configuration/settings", remoteSafe: true),
            "configuration.schema": route("GET", "/api/settings/schema", "/control/v1/configuration/schema", remoteSafe: true),
        ]
    }()

    private let sidecarBaseURL: URL
    private let gatewayBaseURL: URL
    private let preferGateway: Bool

    init(
        sidecarBaseURL: URL = URL(string: "http://127.0.0.1:8766")!,
        gatewayBaseURL: URL = URL(string: "http://127.0.0.1:8768")!,
        preferGateway: Bool = ProcessInfo.processInfo.environment["RAG_IME_AGENT_GATEWAY_ENABLED"] == "1"
    ) {
        self.sidecarBaseURL = sidecarBaseURL
        self.gatewayBaseURL = gatewayBaseURL
        self.preferGateway = preferGateway
    }

    func resolveRequest(
        pathId: String,
        parameters: [String: String],
        query: [String: String],
        body: Any?,
        scope: NativeTransportScope = .local
    ) throws -> NativeResolvedRoute {
        let resolved = try resolve(
            pathId: pathId,
            parameters: parameters,
            query: query,
            body: body,
            scope: scope
        )
        guard !resolved.isSubscription else {
            throw NativeRoutePolicyError.subscriptionRequired(pathId)
        }
        return resolved
    }

    func resolveSubscription(
        pathId: String,
        parameters: [String: String],
        query: [String: String],
        lastEventId: String,
        scope: NativeTransportScope = .local
    ) throws -> NativeResolvedRoute {
        var resolved = try resolve(
            pathId: pathId,
            parameters: parameters,
            query: query,
            body: nil,
            scope: scope
        )
        guard resolved.isSubscription else {
            throw NativeRoutePolicyError.requestRequired(pathId)
        }
        if !lastEventId.isEmpty {
            guard lastEventId.utf8.count <= 512,
                  !lastEventId.contains("\r"),
                  !lastEventId.contains("\n") else {
                throw NativeRoutePolicyError.invalidParameter("lastEventId")
            }
            resolved.request.setValue(lastEventId, forHTTPHeaderField: "Last-Event-ID")
        }
        return resolved
    }

    private func resolve(
        pathId: String,
        parameters: [String: String],
        query: [String: String],
        body: Any?,
        scope: NativeTransportScope
    ) throws -> NativeResolvedRoute {
        guard let definition = Self.routes[pathId] else {
            throw NativeRoutePolicyError.unknownPathId(pathId)
        }
        if scope == .remote, !definition.remoteSafe {
            throw NativeRoutePolicyError.routeNotRemoteSafe(pathId)
        }

        let template = preferGateway ? definition.gatewayPath : definition.localPath
        let baseURL = preferGateway ? gatewayBaseURL : sidecarBaseURL
        let parameterNames = Set(template.split(separator: "/").compactMap { component -> String? in
            guard component.hasPrefix("{"), component.hasSuffix("}") else { return nil }
            return String(component.dropFirst().dropLast())
        })
        for name in parameterNames where parameters[name] == nil {
            throw NativeRoutePolicyError.missingParameter(name)
        }
        if let extra = parameters.keys.first(where: { !parameterNames.contains($0) }) {
            throw NativeRoutePolicyError.unexpectedParameter(extra)
        }
        if pathId == "memory.pages",
           let kind = parameters["kind"],
           !Set(["books", "atoms", "tags", "phrases", "groups", "negative"]).contains(kind) {
            throw NativeRoutePolicyError.invalidParameter("kind")
        }
        if pathId == "memory.entity.get",
           let kind = parameters["kind"],
           !Set(["tag", "group"]).contains(kind) {
            throw NativeRoutePolicyError.invalidParameter("kind")
        }

        let pathSegments = try template.split(separator: "/").map { component -> String in
            let value: String
            if component.hasPrefix("{"), component.hasSuffix("}") {
                let name = String(component.dropFirst().dropLast())
                guard let parameter = parameters[name] else {
                    throw NativeRoutePolicyError.missingParameter(name)
                }
                value = parameter
            } else {
                value = String(component)
            }
            return try encodedPathSegment(value)
        }

        if let unexpected = query.keys.first(where: { !definition.allowedQuery.contains($0) }) {
            throw NativeRoutePolicyError.unexpectedQuery(unexpected)
        }
        if let missing = definition.requiredQuery.first(where: { query[$0] == nil }) {
            throw NativeRoutePolicyError.missingParameter(missing)
        }
        for (name, value) in query where name.utf8.count > 80 || value.utf8.count > 2_048 || value.unicodeScalars.contains(where: { $0.value < 32 }) {
            throw NativeRoutePolicyError.invalidParameter(name)
        }

        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        components?.percentEncodedPath = "/" + pathSegments.joined(separator: "/")
        components?.queryItems = query.isEmpty
            ? nil
            : query.sorted(by: { $0.key < $1.key }).map(URLQueryItem.init(name:value:))
        guard let url = components?.url,
              url.scheme == "http",
              url.host == "127.0.0.1",
              [8766, 8768].contains(url.port ?? -1) else {
            throw NativeRoutePolicyError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = definition.method
        request.timeoutInterval = definition.subscription ? 24 * 60 * 60 : 30
        request.setValue(definition.subscription ? "text/event-stream" : "application/json", forHTTPHeaderField: "Accept")
        if let body {
            guard definition.method != "GET",
                  JSONSerialization.isValidJSONObject(body),
                  let dictionary = body as? [String: Any],
                  dictionary.keys.allSatisfy(definition.allowedBodyKeys.contains),
                  definition.requiredBodyKeys.allSatisfy({ dictionary[$0] != nil }) else {
                throw NativeRoutePolicyError.invalidBody
            }
            if scope == .remote,
               pathId == "agent.configuration.update",
               dictionary["updatedBy"] != nil {
                throw NativeRoutePolicyError.invalidBody
            }
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        } else if !definition.requiredBodyKeys.isEmpty {
            throw NativeRoutePolicyError.invalidBody
        }
        return NativeResolvedRoute(
            pathId: pathId,
            request: request,
            isSubscription: definition.subscription,
            remoteSafe: definition.remoteSafe
        )
    }

    private func encodedPathSegment(_ value: String) throws -> String {
        let allowedScalars = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")
        guard !value.isEmpty,
              value.utf8.count <= 128,
              value.unicodeScalars.first.map(CharacterSet.alphanumerics.contains) == true,
              value.unicodeScalars.allSatisfy(allowedScalars.contains) else {
            throw NativeRoutePolicyError.invalidParameter("path")
        }
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#%")
        guard let encoded = value.addingPercentEncoding(withAllowedCharacters: allowed) else {
            throw NativeRoutePolicyError.invalidParameter("path")
        }
        return encoded
    }
}
