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
    case binaryTransportRequired(String)
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
        case .binaryTransportRequired(let value): return "Route requires the typed binary transport: \(value)"
        case .invalidURL: return "Unable to build allowlisted route URL"
        }
    }
}

struct NativeResolvedRoute {
    let pathId: String
    var request: URLRequest
    let isSubscription: Bool
    let remoteSafe: Bool
    let isBinary: Bool
}

private struct NativeRouteDefinition {
    let method: String
    let localPath: String
    let gatewayPath: String?
    let requiresGateway: Bool
    let allowedQuery: Set<String>
    let requiredQuery: Set<String>
    let remoteSafe: Bool
    let subscription: Bool
    let allowedBodyKeys: Set<String>
    let requiredBodyKeys: Set<String>
    let binary: Bool
}

final class NativeRoutePolicy {
    private static let facadePathIds: Set<String> = ["control.bootstrap", "control.capabilities"]
    static let knownPathIds: Set<String> = Set(routes.keys).union(facadePathIds)

    private static let routes: [String: NativeRouteDefinition] = {
        func route(
            _ method: String,
            _ localPath: String,
            _ gatewayPath: String?,
            query: Set<String> = [],
            requiredQuery: Set<String> = [],
            remoteSafe: Bool = false,
            subscription: Bool = false,
            bodyKeys: Set<String> = [],
            requiredBodyKeys: Set<String> = [],
            binary: Bool = false,
            requiresGateway: Bool = false
        ) -> NativeRouteDefinition {
            NativeRouteDefinition(
                method: method,
                localPath: localPath,
                gatewayPath: gatewayPath,
                requiresGateway: requiresGateway,
                allowedQuery: query,
                requiredQuery: requiredQuery,
                remoteSafe: remoteSafe,
                subscription: subscription,
                allowedBodyKeys: bodyKeys,
                requiredBodyKeys: requiredBodyKeys,
                binary: binary
            )
        }

        return [
            "control.events": route("GET", "/api/agent/events", "/control/v1/events", remoteSafe: true, subscription: true),
            "system.health": route("GET", "/api/health", "/control/v1/health", remoteSafe: true),
            "overview.get": route("GET", "/api/overview", "/control/v1/overview", remoteSafe: true),
            "input.source.get": route("GET", "/api/input-source", "/control/v1/input/source", remoteSafe: true),
            "input.lexicon.review": route("GET", "/api/rime-lexicon/review", "/control/v1/input/lexicon/review", query: ["limit", "project"]),
            "input.lexicon.apply": route("POST", "/api/rime-lexicon/apply", "/control/v1/input/lexicon/apply", bodyKeys: ["reviewToken", "selectedKeys", "confirmText", "project", "limit"], requiredBodyKeys: ["reviewToken", "selectedKeys", "confirmText"]),
            "input.lexicon.rollback": route("POST", "/api/rime-lexicon/rollback", "/control/v1/input/lexicon/rollback", bodyKeys: ["rollbackId"], requiredBodyKeys: ["rollbackId"]),
            "observability.snapshot": route("GET", "/api/observability/snapshot", "/control/v1/observability/snapshot", query: ["limit", "beforeSequence", "sessionId", "roomId", "traceId", "category", "status"], remoteSafe: true),
            "observability.events": route("GET", "/api/observability/events", "/control/v1/observability/events", query: ["sessionId", "roomId", "traceId", "category", "status"], remoteSafe: true, subscription: true),
            "agent.runtime.get": route("GET", "/api/agent/runtime", "/control/v1/agent/runtime", remoteSafe: true),
            "agent.runtime.ensure": route("POST", "/api/agent/runtime/ensure", "/control/v1/agent/runtime/ensure", bodyKeys: ["sessionId"], requiredBodyKeys: ["sessionId"]),
            "agent.providers.get": route("GET", "/api/agent/providers", "/control/v1/agent/providers"),
            "agent.provider.auth.preview": route("POST", "/api/agent/providers/auth/preview", "/control/v1/agent/providers/auth/preview", bodyKeys: ["provider", "action"], requiredBodyKeys: ["provider", "action"]),
            "agent.provider.auth.apply": route("POST", "/api/agent/providers/auth/apply", "/control/v1/agent/providers/auth/apply", bodyKeys: ["previewToken", "confirmText", "apiKey"], requiredBodyKeys: ["previewToken", "confirmText"]),
            "agent.provider.oauth.status": route("GET", "/api/agent/providers/oauth/status", "/control/v1/agent/providers/oauth/status", query: ["loginId"], requiredQuery: ["loginId"]),
            "agent.provider.oauth.cancel": route("POST", "/api/agent/providers/oauth/cancel", "/control/v1/agent/providers/oauth/cancel", bodyKeys: ["loginId"], requiredBodyKeys: ["loginId"]),
            "agent.configuration.get": route("GET", "/api/agent/configuration", "/control/v1/agent/configuration", remoteSafe: true),
            "agent.configuration.update": route("POST", "/api/agent/configuration", "/control/v1/agent/configuration", remoteSafe: true, bodyKeys: ["expectedRevision", "changes", "updatedBy"], requiredBodyKeys: ["expectedRevision", "changes"]),
            "agent.sessions.list": route("GET", "/api/agent/sessions", "/control/v1/agent/sessions", query: ["includeArchived", "includeInternal", "limit"], remoteSafe: true),
            "agent.sessions.create": route("POST", "/api/agent/sessions", "/control/v1/agent/sessions", remoteSafe: true, bodyKeys: ["title", "mode", "roleId", "roleVersion", "modelProfile", "toolProfileVersion", "workspaceRoots"]),
            "agent.session.snapshot": route("GET", "/api/agent/sessions/{sessionId}/messages", "/control/v1/agent/sessions/{sessionId}/snapshot", remoteSafe: true),
            "agent.session.rename": route("PATCH", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", remoteSafe: true, bodyKeys: ["title"], requiredBodyKeys: ["title"]),
            "agent.session.archive": route("PATCH", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", remoteSafe: true, bodyKeys: ["archived"], requiredBodyKeys: ["archived"]),
            "agent.session.mode.update": route("PATCH", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", bodyKeys: ["mode", "workspaceRoots", "toolProfileVersion", "toolAllowlistMode", "allowedTools", "dangerousModeConfirmation", "projectContextEnabled", "piSkillsEnabled", "codexSkillsEnabled"], requiredBodyKeys: ["mode"]),
            "agent.session.delete": route("DELETE", "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}"),
            "agent.session.prompt": route("POST", "/api/agent/sessions/{sessionId}/prompt", "/control/v1/agent/sessions/{sessionId}/prompt", remoteSafe: true, bodyKeys: ["message", "attachments", "clientMessageId", "delivery"], requiredBodyKeys: ["message"]),
            "agent.session.rewrite": route("POST", "/api/agent/sessions/{sessionId}/rewrite", "/control/v1/agent/sessions/{sessionId}/rewrite", remoteSafe: true, bodyKeys: ["entryId", "message", "attachments", "clientMessageId"], requiredBodyKeys: ["entryId", "message"]),
            "agent.session.forks.list": route("GET", "/api/agent/sessions/{sessionId}/forks", "/control/v1/agent/sessions/{sessionId}/forks", remoteSafe: true),
            "agent.session.forks.create": route("POST", "/api/agent/sessions/{sessionId}/forks", "/control/v1/agent/sessions/{sessionId}/forks", remoteSafe: true, bodyKeys: ["entryId", "title"], requiredBodyKeys: ["entryId"]),
            "agent.session.abort": route("POST", "/api/agent/sessions/{sessionId}/abort", "/control/v1/agent/sessions/{sessionId}/abort", remoteSafe: true),
            "agent.session.review.resolve": route("POST", "/api/agent/sessions/{sessionId}/review", "/control/v1/agent/sessions/{sessionId}/review", bodyKeys: ["runId", "decision"], requiredBodyKeys: ["runId", "decision"]),
            "agent.session.compact": route("POST", "/api/agent/sessions/{sessionId}/compact", "/control/v1/agent/sessions/{sessionId}/compact", bodyKeys: ["instructions"]),
            "agent.session.commands": route("GET", "/api/agent/sessions/{sessionId}/commands", "/control/v1/agent/sessions/{sessionId}/commands", remoteSafe: true),
            "agent.session.models": route("GET", "/api/agent/sessions/{sessionId}/models", "/control/v1/agent/sessions/{sessionId}/models", remoteSafe: true),
            "agent.session.model.select": route("POST", "/api/agent/sessions/{sessionId}/model", "/control/v1/agent/sessions/{sessionId}/model", remoteSafe: true, bodyKeys: ["provider", "modelId"], requiredBodyKeys: ["provider", "modelId"]),
            "agent.session.thinking.select": route("POST", "/api/agent/sessions/{sessionId}/thinking", "/control/v1/agent/sessions/{sessionId}/thinking", remoteSafe: true, bodyKeys: ["level"], requiredBodyKeys: ["level"]),
            "agent.session.events": route("GET", "/api/agent/sessions/{sessionId}/events", "/control/v1/agent/sessions/{sessionId}/events", remoteSafe: true, subscription: true),
            "agent.session.intercom.list": route("GET", "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", query: ["status", "limit"], remoteSafe: true),
            "agent.session.intercom.send": route("POST", "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", remoteSafe: true, bodyKeys: ["kind", "targetParticipantId", "clientMessageId", "replyTo", "content"], requiredBodyKeys: ["kind", "clientMessageId", "content"]),
            "agent.session.contextItems.list": route("GET", "/api/agent/sessions/{sessionId}/context-items", "/control/v1/agent/sessions/{sessionId}/context-items", query: ["status", "limit"], remoteSafe: true),
            "agent.session.contextItems.ack": route("POST", "/api/agent/sessions/{sessionId}/context-items/{itemId}/ack", "/control/v1/agent/sessions/{sessionId}/context-items/{itemId}/ack", remoteSafe: true),
            "agent.session.contextTraces.list": route("GET", "/api/agent/sessions/{sessionId}/context-traces", "/control/v1/agent/sessions/{sessionId}/context-traces", query: ["limit"], remoteSafe: true),
            "agent.session.contextTrace.get": route("GET", "/api/agent/sessions/{sessionId}/context-traces/{traceId}", "/control/v1/agent/sessions/{sessionId}/context-traces/{traceId}", remoteSafe: true),
            "agent.session.debugContext.get": route(
                "GET",
                "/api/agent/sessions/{sessionId}/debug-context",
                nil,
                query: ["turnId"],
                requiresGateway: true
            ),
            "agent.artifact.get": route("GET", "/api/agent/artifacts/{artifactId}", "/control/v1/agent/artifacts/{artifactId}", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.media.list": route("GET", "/api/agent/media", "/control/v1/agent/media", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.deep-search": route("POST", "/api/agent/deep-search", "/control/v1/agent/deep-search", bodyKeys: ["query", "privacyDisposition", "context", "frontAppBundleId", "contextSource", "evidence"], requiredBodyKeys: ["query", "privacyDisposition"]),
            "agent.rooms.list": route("GET", "/api/agent/rooms", "/control/v1/agent/rooms", query: ["includeArchived", "limit"], remoteSafe: true),
            "agent.rooms.create": route("POST", "/api/agent/rooms", "/control/v1/agent/rooms", remoteSafe: true, bodyKeys: ["title", "roomKind", "avatar", "description", "scenarioPrompt", "participants", "routingPolicy", "routingConfig", "moderatorRoleId", "workspaceRoots"], requiredBodyKeys: ["participants"]),
            "agent.room.get": route("GET", "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", remoteSafe: true),
            "agent.room.snapshot": route("GET", "/api/agent/rooms/{roomId}/snapshot", "/control/v1/agent/rooms/{roomId}/snapshot", remoteSafe: true),
            "agent.room.archive": route("PATCH", "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", remoteSafe: true, bodyKeys: ["archived", "title", "roomKind", "avatar", "description", "scenarioPrompt", "routingPolicy", "routingConfig", "moderatorParticipantId"]),
            "agent.room.message": route("POST", "/api/agent/rooms/{roomId}/messages", "/control/v1/agent/rooms/{roomId}/messages", remoteSafe: true, bodyKeys: ["message", "clientMessageId", "participantIds", "workItemId"], requiredBodyKeys: ["message"]),
            "agent.room.events": route("GET", "/api/agent/rooms/{roomId}/events", "/control/v1/agent/rooms/{roomId}/events", remoteSafe: true, subscription: true),
            "agent.room.topics": route("GET", "/api/agent/rooms/{roomId}/topics", "/control/v1/agent/rooms/{roomId}/topics", query: ["includeArchived"], remoteSafe: true),
            "agent.room.topic.create": route("POST", "/api/agent/rooms/{roomId}/topics", "/control/v1/agent/rooms/{roomId}/topics", remoteSafe: true, bodyKeys: ["title", "summary"], requiredBodyKeys: ["title"]),
            "agent.room.topic.update": route("PATCH", "/api/agent/rooms/{roomId}/topics", "/control/v1/agent/rooms/{roomId}/topics", remoteSafe: true, bodyKeys: ["topicId", "title", "summary", "activate", "archived"], requiredBodyKeys: ["topicId"]),
            "agent.room.artifacts": route("GET", "/api/agent/rooms/{roomId}/artifacts", "/control/v1/agent/rooms/{roomId}/artifacts", query: ["includeArchived", "topicId", "limit"], remoteSafe: true),
            "agent.room.artifact.add": route("POST", "/api/agent/rooms/{roomId}/artifacts", "/control/v1/agent/rooms/{roomId}/artifacts", remoteSafe: true, bodyKeys: ["path", "displayName", "topicId", "mediaType", "participantId"], requiredBodyKeys: ["path"]),
            "agent.room.artifact.update": route("PATCH", "/api/agent/rooms/{roomId}/artifacts", "/control/v1/agent/rooms/{roomId}/artifacts", remoteSafe: true, bodyKeys: ["artifactId", "archived"], requiredBodyKeys: ["artifactId", "archived"]),
            "agent.room.workItems.list": route("GET", "/api/agent/rooms/{roomId}/work-items", "/control/v1/agent/rooms/{roomId}/work-items", query: ["state", "ownerParticipantId", "limit"], remoteSafe: true),
            "agent.room.workItem.create": route("POST", "/api/agent/rooms/{roomId}/work-items", "/control/v1/agent/rooms/{roomId}/work-items", bodyKeys: ["objective", "expectedOutput", "currentOwnerParticipantId", "createdByParticipantId", "clientMessageId", "accountableParticipantId", "topicId", "rootTurnId", "parentWorkId", "acceptanceCriteria", "state", "depth"], requiredBodyKeys: ["objective", "expectedOutput", "currentOwnerParticipantId", "clientMessageId"]),
            "agent.room.workItem.get": route("GET", "/api/agent/rooms/{roomId}/work-items/{workItemId}", "/control/v1/agent/rooms/{roomId}/work-items/{workItemId}", remoteSafe: true),
            "agent.room.workItem.reassign": route("POST", "/api/agent/rooms/{roomId}/work-items/{workItemId}/reassign", "/control/v1/agent/rooms/{roomId}/work-items/{workItemId}/reassign", bodyKeys: ["actorParticipantId", "targetParticipantId", "reason"], requiredBodyKeys: ["actorParticipantId", "targetParticipantId"]),
            "agent.roles.list": route("GET", "/api/agent/roles", "/control/v1/agent/roles", remoteSafe: true),
            "agent.roles.create": route("POST", "/api/agent/roles", "/control/v1/agent/roles", remoteSafe: true, bodyKeys: ["displayName", "tagline", "summary", "traits", "timelineModel", "selectableModes"], requiredBodyKeys: ["displayName", "tagline", "summary", "traits", "timelineModel", "selectableModes"]),
            "agent.role.models": route("GET", "/api/agent/roles/models", "/control/v1/agent/roles/models", remoteSafe: true),
            "agent.role.runtimeDefaults.update": route("POST", "/api/agent/roles/runtime-defaults", "/control/v1/agent/roles/runtime-defaults", remoteSafe: true, bodyKeys: ["roleId", "roleVersion", "provider", "modelId", "thinkingLevel"], requiredBodyKeys: ["roleId", "roleVersion", "provider", "modelId", "thinkingLevel"]),
            "agent.roleBook.get": route("GET", "/api/agent/role-book", "/control/v1/agent/role-book", query: ["roleId", "roleVersion", "limit"], requiredQuery: ["roleId", "roleVersion"], remoteSafe: true),
            "agent.roleBook.activation.preview": route("POST", "/api/agent/role-book/activation/preview", "/control/v1/agent/role-book/activation/preview", remoteSafe: true, bodyKeys: ["roleId", "roleVersion", "revisionId", "draftId", "traitIndexes", "capabilityIndexes"], requiredBodyKeys: ["roleId", "roleVersion"]),
            "agent.roleBook.activation.apply": route("POST", "/api/agent/role-book/activation/apply", "/control/v1/agent/role-book/activation/apply", remoteSafe: true, bodyKeys: ["roleId", "roleVersion", "revisionId", "draftId", "traitIndexes", "capabilityIndexes", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["roleId", "roleVersion", "previewToken", "payloadSha256", "confirmText"]),
            "agent.roleBook.activation.rollback": route("POST", "/api/agent/role-book/activation/rollback", "/control/v1/agent/role-book/activation/rollback", remoteSafe: true, bodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "agent.roleBook.draft.decision": route("POST", "/api/agent/role-book/drafts/decision", "/control/v1/agent/role-book/drafts/decision", remoteSafe: true, bodyKeys: ["roleId", "roleVersion", "draftId", "decision"], requiredBodyKeys: ["roleId", "roleVersion", "draftId", "decision"]),
            "agent.personalContext.observability": route("GET", "/api/agent/personal-context/observability", "/control/v1/agent/personal-context/observability", query: ["sessionId", "roleId", "limit"], remoteSafe: true),
            "agent.tools.list": route("GET", "/api/agent/tools", "/control/v1/agent/tools", query: ["sessionId"]),
            "agent.extensions.list": route("GET", "/api/agent/extensions", "/control/v1/agent/extensions"),
            "agent.extensions.create": route("POST", "/api/agent/extensions/drafts", "/control/v1/agent/extensions/drafts", bodyKeys: ["draftId", "manifest", "files"], requiredBodyKeys: ["draftId", "manifest", "files"]),
            "agent.extensions.proposals": route("GET", "/api/agent/extensions/proposals", "/control/v1/agent/extensions/proposals"),
            "agent.extensions.validate": route("POST", "/api/agent/extensions/validate", "/control/v1/agent/extensions/validate", bodyKeys: ["sourcePath"], requiredBodyKeys: ["sourcePath"]),
            "agent.extensions.preview": route("POST", "/api/agent/extensions/preview", "/control/v1/agent/extensions/preview", bodyKeys: ["action", "validationToken", "pluginId", "enable"], requiredBodyKeys: ["action"]),
            "agent.extensions.apply": route("POST", "/api/agent/extensions/apply", "/control/v1/agent/extensions/apply", bodyKeys: ["previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["previewToken", "payloadSha256", "confirmText"]),
            "agent.approvals.list": route("GET", "/api/agent/approvals", "/control/v1/agent/approvals", query: ["sessionId", "state", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.approval.get": route("GET", "/api/agent/approvals/{approvalId}", "/control/v1/agent/approvals/{approvalId}", remoteSafe: true),
            "agent.approval.decide": route("POST", "/api/agent/approvals/{approvalId}/decision", "/control/v1/agent/approvals/{approvalId}/decision", remoteSafe: true, bodyKeys: ["decision", "payloadSha256"], requiredBodyKeys: ["decision", "payloadSha256"]),
            "agent.memoryMaintenance.run": route("GET", "/api/agent/memory-maintenance", "/control/v1/agent/memory-maintenance", query: ["runId", "project", "limit"]),
            "agent.subagents.templates": route("GET", "/api/agent/subagents/templates", "/control/v1/agent/subagents/templates", remoteSafe: true),
            "agent.subagents.list": route("GET", "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.subagents.create": route("POST", "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", remoteSafe: true, bodyKeys: ["sessionId", "tasks", "agent", "version", "task", "contextMode", "wait"], requiredBodyKeys: ["sessionId"]),
            "agent.subagent.get": route("GET", "/api/agent/subagents/runs/{runId}", "/control/v1/agent/subagents/runs/{runId}", query: ["sessionId"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.subagent.abort": route("POST", "/api/agent/subagents/runs/{runId}/abort", "/control/v1/agent/subagents/runs/{runId}/abort", remoteSafe: true, bodyKeys: ["sessionId"], requiredBodyKeys: ["sessionId"]),
            "agent.memorySources.list": route("GET", "/api/agent/memory-sources", "/control/v1/agent/memory-sources", query: ["sessionId", "limit"], requiredQuery: ["sessionId"], remoteSafe: true),
            "agent.wakeSchedules.list": route("GET", "/api/agent/wake-schedules", "/control/v1/agent/wake-schedules", query: ["status", "targetType", "targetId", "createdBySessionId", "limit"], remoteSafe: true),
            "agent.wakeSchedules.create": route("POST", "/api/agent/wake-schedules", "/control/v1/agent/wake-schedules", remoteSafe: true, bodyKeys: ["title", "instruction", "targetType", "targetSessionId", "targetRoleId", "targetRoleVersion", "wakeAtMs", "timezone", "recurrenceKind", "recurrenceInterval", "maxRuns", "planningTaskId", "confirmText"], requiredBodyKeys: ["instruction", "targetType", "wakeAtMs", "confirmText"]),
            "agent.wakeSchedule.runs": route("GET", "/api/agent/wake-schedules/{scheduleId}/runs", "/control/v1/agent/wake-schedules/{scheduleId}/runs", query: ["limit"], remoteSafe: true),
            "agent.wakeSchedule.action": route("POST", "/api/agent/wake-schedules/{scheduleId}/action", "/control/v1/agent/wake-schedules/{scheduleId}/action", remoteSafe: true, bodyKeys: ["action", "confirmText"], requiredBodyKeys: ["action", "confirmText"]),
            "browser.status": route("GET", "/api/browser/status", "/control/v1/browser/status"),
            "browser.pairing": route("GET", "/api/browser/pairing", "/control/v1/browser/pairing"),
            "browser.tabs": route("GET", "/api/browser/tabs", "/control/v1/browser/tabs"),
            "browser.snapshot.latest": route("GET", "/api/browser/snapshots/latest", "/control/v1/browser/snapshots/latest", query: ["deviceId", "tabId", "includeMarkdown"]),
            "browser.snapshot.image": route("GET", "/api/browser/snapshots/{snapshotId}/image", "/control/v1/browser/snapshots/{snapshotId}/image", binary: true),
            "browser.traces": route("GET", "/api/browser/traces", "/control/v1/browser/traces", query: ["limit"]),
            "browser.permissions": route("GET", "/api/browser/permissions", "/control/v1/browser/permissions", query: ["limit"]),
            "browser.permission.get": route("GET", "/api/browser/permissions/{promptId}", "/control/v1/browser/permissions/{promptId}"),
            "browser.permission.decide": route("POST", "/api/browser/permissions/{promptId}/decision", "/control/v1/browser/permissions/{promptId}/decision", bodyKeys: ["decision"], requiredBodyKeys: ["decision"]),
            "browser.mode.update": route("POST", "/api/browser/mode", "/control/v1/browser/mode", bodyKeys: ["mode"], requiredBodyKeys: ["mode"]),
            "browser.pairing.rotate": route("POST", "/api/browser/pairing/rotate", "/control/v1/browser/pairing/rotate"),
            "browser.command": route("POST", "/api/browser/command", "/control/v1/browser/command", bodyKeys: ["action", "deviceId", "tabId", "refId", "url", "text", "clear", "direction", "amount", "timeoutMs", "timeoutSeconds"], requiredBodyKeys: ["action"]),
            "browser.stop": route("POST", "/api/browser/stop", "/control/v1/browser/stop"),
            "browser.managed.start": route("POST", "/api/browser/managed/start", "/control/v1/browser/managed/start"),
            "browser.managed.stop": route("POST", "/api/browser/managed/stop", "/control/v1/browser/managed/stop"),
            "planning.dashboard": route("GET", "/api/planning/dashboard", "/control/v1/planning/dashboard", query: ["date", "project"], remoteSafe: true),
            "planning.mutation.preview": route("POST", "/api/planning/mutation/preview", "/control/v1/planning/mutation/preview", bodyKeys: ["kind", "payload", "expectedRuntimeRevision"], requiredBodyKeys: ["kind", "payload", "expectedRuntimeRevision"]),
            "planning.task.save": route("POST", "/api/planning/task/save", "/control/v1/planning/task/save", bodyKeys: ["taskId", "date", "title", "detail", "priority", "status", "dueAtMs", "goalId", "project", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["date", "title", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "planning.goal.save": route("POST", "/api/planning/goal/save", "/control/v1/planning/goal/save", bodyKeys: ["goalId", "title", "detail", "horizon", "status", "priority", "targetDate", "project", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["title", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "planning.task.action": route("POST", "/api/planning/task/action", "/control/v1/planning/task/action", bodyKeys: ["taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "planning.taskEvent.undo": route("POST", "/api/planning/task-event/undo", "/control/v1/planning/task-event/undo", bodyKeys: ["eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "planning.mutation.rollback": route("POST", "/api/planning/mutation/rollback", "/control/v1/planning/mutation/rollback", bodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "memory.summary": route("GET", "/api/memory/summary", "/control/v1/memory/summary", remoteSafe: true),
            "memory.pages": route("GET", "/api/memory/{kind}", "/control/v1/memory/{kind}", query: ["limit", "cursor", "query", "status", "ownerKind", "ownerId"], remoteSafe: true),
            "memory.reference.get": route("GET", "/api/memory/references/{kind}/{referenceId}", "/control/v1/memory/references/{kind}/{referenceId}", remoteSafe: true),
            "memory.graph.get": route("GET", "/api/memory/graph", "/control/v1/memory/graph", query: ["plane", "project", "status", "query", "focusId", "depth", "nodeLimit", "edgeLimit", "minWeight"], requiredQuery: ["plane"], remoteSafe: true),
            "memory.entity.get": route("GET", "/api/memory/entities/{kind}/{entityId}", "/control/v1/memory/entities/{kind}/{entityId}", query: ["project", "connectionsLimit", "connectionsCursor", "membersLimit", "membersCursor"], remoteSafe: true),
            "memory.edit": route("POST", "/api/memory/edit", "/control/v1/memory/edit", bodyKeys: ["kind", "id", "title", "text", "summary", "note", "description", "tags", "aliases", "type", "color", "reason", "active"], requiredBodyKeys: ["kind", "id"]),
            "memory.source.disposition": route("POST", "/api/memory/source/disposition", "/control/v1/memory/source/disposition", bodyKeys: ["sourceId", "disposition"], requiredBodyKeys: ["sourceId", "disposition"]),
            "memory.book.archive.preview": route("POST", "/api/memory/book/archive/preview", "/control/v1/memory/book/archive/preview", bodyKeys: ["bookId", "archived", "reason", "expectedRuntimeRevision"], requiredBodyKeys: ["bookId", "archived", "expectedRuntimeRevision"]),
            "memory.book.archive.apply": route("POST", "/api/memory/book/archive/apply", "/control/v1/memory/book/archive/apply", bodyKeys: ["bookId", "archived", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["bookId", "archived", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "memory.book.archive.rollback": route("POST", "/api/memory/book/archive/rollback", "/control/v1/memory/book/archive/rollback", bodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "memory.activityTimeline.get": route("GET", "/api/memory/activity-timeline", "/control/v1/memory/activity-timeline", query: ["timelineId", "date", "status"], remoteSafe: true),
            "memory.activityTimeline.build": route("POST", "/api/memory/activity-timeline/build", "/control/v1/memory/activity-timeline/build", remoteSafe: true, bodyKeys: ["date"], requiredBodyKeys: ["date"]),
            "memory.activityTimeline.approve": route("POST", "/api/memory/activity-timeline/approve", "/control/v1/memory/activity-timeline/approve", remoteSafe: true, bodyKeys: ["timelineId", "expectedSourceEventHash", "confirmText"], requiredBodyKeys: ["timelineId", "expectedSourceEventHash", "confirmText"]),
            "memory.activityTimeline.reject": route("POST", "/api/memory/activity-timeline/reject", "/control/v1/memory/activity-timeline/reject", remoteSafe: true, bodyKeys: ["timelineId", "reason", "confirmText"], requiredBodyKeys: ["timelineId", "reason", "confirmText"]),
            "history.page": route("GET", "/api/history/page", "/control/v1/history/page", query: ["limit", "cursor", "query", "filter"], remoteSafe: true),
            "history.detail": route("GET", "/api/history/detail", "/control/v1/history/detail", query: ["eventId"], requiredQuery: ["eventId"], remoteSafe: true),
            "history.tombstone.preview": route("POST", "/api/history/tombstone/preview", "/control/v1/history/tombstone/preview", bodyKeys: ["eventId", "reason", "expectedRuntimeRevision"], requiredBodyKeys: ["eventId", "expectedRuntimeRevision"]),
            "history.tombstone.apply": route("POST", "/api/history/tombstone/apply", "/control/v1/history/tombstone/apply", bodyKeys: ["eventId", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["eventId", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "history.tombstone.rollback": route("POST", "/api/history/tombstone/rollback", "/control/v1/history/tombstone/rollback", bodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "knowledge.start": route("POST", "/api/knowledge/start", "/control/v1/knowledge/start", bodyKeys: ["question", "context", "mode", "includeNotion", "generation", "contextHash", "clientId", "project", "app", "maxChars", "latencyBudgetMs"], requiredBodyKeys: ["question"]),
            "knowledge.cancel": route("POST", "/api/knowledge/cancel", "/control/v1/knowledge/cancel", bodyKeys: ["sessionId", "id"]),
            "knowledge.status": route("GET", "/api/knowledge/status", "/control/v1/knowledge/status", query: ["sessionId", "id"], remoteSafe: true),
            "knowledge.routeStatus": route("GET", "/api/knowledge/route-status", "/control/v1/knowledge/route-status", remoteSafe: true),
            "knowledge.database.apply.preview": route("POST", "/api/knowledge/database/apply-preview", "/control/v1/knowledge/database/apply-preview", bodyKeys: ["runId", "expectedRuntimeRevision"], requiredBodyKeys: ["runId"]),
            "knowledge.database.draft.edit": route("POST", "/api/knowledge/database/draft-edit", "/control/v1/knowledge/database/draft-edit", bodyKeys: ["runId", "diffId", "selected", "payload"], requiredBodyKeys: ["runId", "diffId", "selected"]),
            "knowledge.database.apply": route("POST", "/api/knowledge/database/apply", "/control/v1/knowledge/database/apply", bodyKeys: ["runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"], requiredBodyKeys: ["runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"]),
            "knowledge.database.rollback": route("POST", "/api/knowledge/database/rollback", "/control/v1/knowledge/database/rollback", bodyKeys: ["runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"], requiredBodyKeys: ["runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"]),
            "knowledgeBases.list": route("GET", "/api/knowledge-bases", nil, query: ["limit", "cursor", "query", "status"]),
            "knowledgeBases.create": route("POST", "/api/knowledge-bases", nil, bodyKeys: ["name", "description", "agentEnabled", "parserProvider", "chunkingConfig", "retrievalConfig"], requiredBodyKeys: ["name"]),
            "knowledgeBases.get": route("GET", "/api/knowledge-bases/{kbId}", nil),
            "knowledgeBases.update": route("PATCH", "/api/knowledge-bases/{kbId}", nil, bodyKeys: ["name", "description", "agentEnabled", "parserProvider", "chunkingConfig", "retrievalConfig", "expectedRevision"], requiredBodyKeys: ["expectedRevision"]),
            "knowledgeBases.delete.preview": route("POST", "/api/knowledge-bases/{kbId}/delete/preview", nil, bodyKeys: ["expectedRevision"], requiredBodyKeys: ["expectedRevision"]),
            "knowledgeBases.delete.apply": route("POST", "/api/knowledge-bases/{kbId}/delete/apply", nil, bodyKeys: ["expectedRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["expectedRevision", "previewToken", "payloadSha256", "confirmText"]),
            "knowledgeBases.documents.list": route("GET", "/api/knowledge-bases/{kbId}/documents", nil, query: ["limit", "cursor", "query", "status"]),
            "knowledgeBases.document.import": route("POST", "/api/knowledge-bases/{kbId}/documents/import", nil, query: ["fileName", "mimeType", "parserProvider"], requiredQuery: ["fileName", "mimeType"]),
            "knowledgeBases.document.retry": route("POST", "/api/knowledge-bases/{kbId}/documents/{fileId}/retry", nil, bodyKeys: ["stage", "parserProvider", "expectedRevision"], requiredBodyKeys: ["stage", "expectedRevision"]),
            "knowledgeBases.document.delete": route("DELETE", "/api/knowledge-bases/{kbId}/documents/{fileId}", nil),
            "knowledgeBases.document.get": route("GET", "/api/knowledge-bases/{kbId}/documents/{fileId}", nil, query: ["offset", "limit", "lineOffset", "lineLimit"]),
            "knowledgeBases.document.source": route("GET", "/api/knowledge-bases/{kbId}/documents/{fileId}/source", nil, binary: true),
            "knowledgeBases.asset.get": route("GET", "/api/knowledge-bases/{kbId}/documents/{fileId}/assets/{assetId}", nil, binary: true),
            "knowledgeBases.jobs.list": route("GET", "/api/knowledge-bases/{kbId}/jobs", nil, query: ["limit", "cursor", "status"]),
            "knowledgeBases.job.cancel": route("POST", "/api/knowledge-bases/{kbId}/jobs/{jobId}/cancel", nil, bodyKeys: []),
            "knowledgeBases.chunkPreview": route("POST", "/api/knowledge-bases/{kbId}/documents/{fileId}/chunk-preview", nil, bodyKeys: ["chunkingConfig", "limit"], requiredBodyKeys: ["chunkingConfig"]),
            "knowledgeBases.search": route("POST", "/api/knowledge-bases/{kbId}/search", nil, bodyKeys: ["query", "topK", "mode", "threshold", "fileIds", "fileName"], requiredBodyKeys: ["query"]),
            "knowledgeBases.find": route("POST", "/api/knowledge-bases/{kbId}/documents/{fileId}/find", nil, bodyKeys: ["query", "regex", "lineWindow"], requiredBodyKeys: ["query"]),
            "knowledgeBases.open": route("GET", "/api/knowledge-bases/{kbId}/documents/{fileId}/content", nil, query: ["chunkId", "page", "startLine", "lines"]),
            "knowledgeBases.graph.get": route("GET", "/api/knowledge-bases/{kbId}/graph", nil, query: ["documentId", "query", "kinds", "limit", "depth", "excludeChunks", "focusId"]),
            "knowledgeBases.graph.rebuild": route("POST", "/api/knowledge-bases/{kbId}/graph/rebuild", nil, bodyKeys: ["expectedRevision", "documentIds"], requiredBodyKeys: ["expectedRevision"]),
            "knowledgeBases.reindexPreview": route("GET", "/api/knowledge-bases/{kbId}/reindex-preview", nil),
            "knowledgeBases.rebuild": route("POST", "/api/knowledge-bases/{kbId}/rebuild", nil, bodyKeys: ["previewToken", "payloadSha256", "expectedRevision", "confirmText"], requiredBodyKeys: ["previewToken", "payloadSha256", "expectedRevision", "confirmText"]),
            "knowledgeWorker.health": route("GET", "/api/knowledge-bases/health", nil),
            "knowledgeParsers.list": route("GET", "/api/knowledge-bases/parsers", nil),
            "diagnostics.runtime": route("GET", "/api/runtime/status", "/control/v1/diagnostics/runtime", remoteSafe: true),
            "diagnostics.predictor": route("GET", "/api/predictor/status", "/control/v1/diagnostics/predictor", remoteSafe: true),
            "diagnostics.models": route("GET", "/api/models/status", "/control/v1/diagnostics/models", remoteSafe: true),
            "diagnostics.action.preview": route("POST", "/api/runtime/action/preview", nil, bodyKeys: ["action", "expectedRuntimeRevision"], requiredBodyKeys: ["action", "expectedRuntimeRevision"]),
            "diagnostics.action.start": route("POST", "/api/runtime/action/start", nil, bodyKeys: ["action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "commandSha256", "confirmText"], requiredBodyKeys: ["action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "commandSha256", "confirmText"]),
            "diagnostics.action.job": route("GET", "/api/runtime/job/{jobId}", nil),
            "configuration.settings": route("GET", "/api/settings", "/control/v1/configuration/settings", remoteSafe: true),
            "configuration.schema": route("GET", "/api/settings/schema", "/control/v1/configuration/schema", remoteSafe: true),
            "configuration.settings.preview": route("POST", "/api/settings/preview", "/control/v1/configuration/settings/preview", bodyKeys: ["changes", "expectedRuntimeRevision"], requiredBodyKeys: ["changes", "expectedRuntimeRevision"]),
            "configuration.settings.apply": route("POST", "/api/settings/apply", "/control/v1/configuration/settings/apply", bodyKeys: ["changes", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["changes", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"]),
            "configuration.settings.rollback": route("POST", "/api/settings/rollback", "/control/v1/configuration/settings/rollback", bodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"], requiredBodyKeys: ["receiptId", "rollbackToken", "payloadSha256", "confirmText"]),
            "configuration.import.preview": route("POST", "/api/configuration/import-preview", nil, bodyKeys: ["path"], requiredBodyKeys: ["path"]),
            "configuration.import.apply": route("POST", "/api/configuration/import-apply", nil, bodyKeys: ["path", "expectedRuntimeRevision", "previewToken", "confirmText", "confirmRemoteModel"], requiredBodyKeys: ["path", "expectedRuntimeRevision", "previewToken", "confirmText"]),
            "configuration.backup.export": route("POST", "/api/configuration/backup-export", nil, bodyKeys: ["destination"], requiredBodyKeys: ["destination"]),
            "configuration.restore.preview": route("POST", "/api/configuration/restore-preview", nil, bodyKeys: ["path"], requiredBodyKeys: ["path"]),
            "configuration.restore.apply": route("POST", "/api/configuration/restore-apply", nil, bodyKeys: ["path", "restoreToken", "confirmText", "expectedRuntimeRevision"], requiredBodyKeys: ["path", "restoreToken", "confirmText", "expectedRuntimeRevision"]),
        ]
    }()

    private let sidecarBaseURL: URL
    private let gatewayBaseURL: URL
    private let preferGateway: Bool

    init(
        sidecarBaseURL: URL = URL(string: "http://127.0.0.1:8766")!,
        gatewayBaseURL: URL = URL(string: "http://127.0.0.1:8768")!,
        preferGateway: Bool = ProcessInfo.processInfo.environment["RAG_IME_AGENT_GATEWAY_ENABLED"] != "0"
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
        guard !resolved.isBinary else {
            throw NativeRoutePolicyError.binaryTransportRequired(pathId)
        }
        return resolved
    }

    func resolveBinary(
        pathId: String,
        parameters: [String: String],
        scope: NativeTransportScope = .local
    ) throws -> NativeResolvedRoute {
        let resolved = try resolve(
            pathId: pathId,
            parameters: parameters,
            query: [:],
            body: nil,
            scope: scope
        )
        guard resolved.isBinary else {
            throw NativeRoutePolicyError.requestRequired(pathId)
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

        let useGateway = definition.requiresGateway || (preferGateway && definition.gatewayPath != nil)
        let template = useGateway && scope == .remote
            ? definition.gatewayPath!
            : definition.localPath
        let baseURL = useGateway ? gatewayBaseURL : sidecarBaseURL
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
           !Set(["apps", "books", "atoms", "timelines", "tags", "phrases", "evidence", "groups", "negative"]).contains(kind) {
            throw NativeRoutePolicyError.invalidParameter("kind")
        }
        if pathId == "memory.reference.get",
           let kind = parameters["kind"],
           !Set(["event", "evidence", "atom", "book", "timeline", "role_book_revision"]).contains(kind) {
            throw NativeRoutePolicyError.invalidParameter("kind")
        }
        if pathId == "memory.entity.get",
           let kind = parameters["kind"],
           !Set(["tag", "group", "book"]).contains(kind) {
            throw NativeRoutePolicyError.invalidParameter("kind")
        }
        if pathId == "knowledgeBases.asset.get",
           let assetId = parameters["assetId"],
           assetId.range(of: "^[a-f0-9]{64}$", options: .regularExpression) == nil {
            throw NativeRoutePolicyError.invalidParameter("assetId")
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
        let accept: String
        if definition.subscription {
            accept = "text/event-stream"
        } else if pathId == "knowledgeBases.document.source" {
            accept = "application/pdf, image/png, image/jpeg, image/gif, image/webp, image/bmp, image/tiff, text/plain, text/markdown, text/csv, application/json, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/vnd.openxmlformats-officedocument.presentationml.presentation, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        } else if definition.binary {
            accept = "image/png, image/jpeg, image/gif, image/webp, image/bmp"
        } else {
            accept = "application/json"
        }
        request.setValue(accept, forHTTPHeaderField: "Accept")
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
            remoteSafe: definition.remoteSafe,
            isBinary: definition.binary
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
