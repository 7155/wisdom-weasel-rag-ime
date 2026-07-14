import Foundation

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        FileHandle.standardError.write(Data("FAIL: \(message)\n".utf8))
        exit(1)
    }
}

private func expectThrows(_ message: String, _ operation: () throws -> Void) {
    do {
        try operation()
        FileHandle.standardError.write(Data("FAIL: expected rejection: \(message)\n".utf8))
        exit(1)
    } catch {}
}

@main
struct NativeRoutePolicyTests {
    static func main() throws {
        let policy = NativeRoutePolicy(
            sidecarBaseURL: URL(string: "http://127.0.0.1:8766")!,
            gatewayBaseURL: URL(string: "http://127.0.0.1:8768")!,
            preferGateway: false
        )

        let health = try policy.resolveRequest(
            pathId: "system.health",
            parameters: [:],
            query: [:],
            body: nil
        )
        expect(health.request.url?.absoluteString == "http://127.0.0.1:8766/api/health", "health route")
        expect(health.request.httpMethod == "GET", "health method")

        let session = try policy.resolveRequest(
            pathId: "agent.session.prompt",
            parameters: ["sessionId": "session:alpha"],
            query: [:],
            body: ["message": "hello"]
        )
        expect(session.request.url?.absoluteString.contains("session:alpha/prompt") == true, "session path encoding")
        expect(session.request.httpMethod == "POST", "prompt method")

        let subscription = try policy.resolveSubscription(
            pathId: "agent.session.events",
            parameters: ["sessionId": "session-a"],
            query: [:],
            lastEventId: "session-a:41"
        )
        expect(subscription.request.value(forHTTPHeaderField: "Last-Event-ID") == "session-a:41", "resume cursor")

        let controlEvents = try policy.resolveSubscription(
            pathId: "control.events",
            parameters: [:],
            query: [:],
            lastEventId: "agent-control:9"
        )
        expect(controlEvents.request.url?.path == "/api/agent/events", "canonical control event route")

        let roomSnapshot = try policy.resolveRequest(
            pathId: "agent.room.snapshot",
            parameters: ["roomId": "room:alpha"],
            query: [:],
            body: nil
        )
        expect(roomSnapshot.request.url?.absoluteString.contains("room:alpha/snapshot") == true, "room snapshot route")
        expect(roomSnapshot.request.httpMethod == "GET", "room snapshot method")

        let artifact = try policy.resolveRequest(
            pathId: "agent.artifact.get",
            parameters: ["artifactId": "artifact:alpha"],
            query: ["sessionId": "session:alpha", "limit": "5"],
            body: nil
        )
        expect(artifact.request.url?.path.contains("/api/agent/artifacts/artifact:alpha") == true, "artifact route")

        _ = try policy.resolveRequest(
            pathId: "memory.pages",
            parameters: ["kind": "books"],
            query: ["limit": "50", "cursor": "next"],
            body: nil,
            scope: .remote
        )

        let memoryGraph = try policy.resolveRequest(
            pathId: "memory.graph.get",
            parameters: [:],
            query: ["plane": "groups", "nodeLimit": "80", "edgeLimit": "160"],
            body: nil,
            scope: .remote
        )
        expect(memoryGraph.request.url?.path == "/api/memory/graph", "bounded memory graph route")

        let memoryEntity = try policy.resolveRequest(
            pathId: "memory.entity.get",
            parameters: ["kind": "group", "entityId": "group:input-method"],
            query: ["membersLimit": "50"],
            body: nil,
            scope: .remote
        )
        expect(memoryEntity.request.url?.path == "/api/memory/entities/group/group:input-method", "bounded memory entity route")

        let planningPreview = try policy.resolveRequest(
            pathId: "planning.mutation.preview",
            parameters: [:],
            query: [:],
            body: [
                "kind": "task.save",
                "payload": ["date": "2026-07-14", "title": "整理记忆图"],
                "expectedRuntimeRevision": "runtime:1",
            ]
        )
        expect(planningPreview.request.url?.path == "/api/planning/mutation/preview", "planning WorkContract preview")

        let knowledgeApply = try policy.resolveRequest(
            pathId: "knowledge.database.apply",
            parameters: [:],
            query: [:],
            body: [
                "runId": "run:1",
                "confirm": "apply",
                "previewToken": "preview-token",
                "payloadSha256": String(repeating: "a", count: 64),
                "expectedRuntimeRevision": "runtime:1",
            ]
        )
        expect(knowledgeApply.request.url?.path == "/api/knowledge/database/apply", "knowledge WorkContract apply")

        expectThrows("unknown pathId") {
            _ = try policy.resolveRequest(pathId: "debug.anything", parameters: [:], query: [:], body: nil)
        }
        expectThrows("unsafe remote route") {
            _ = try policy.resolveRequest(
                pathId: "agent.runtime.ensure",
                parameters: [:],
                query: [:],
                body: [:],
                scope: .remote
            )
        }
        expectThrows("session mode body allowlist") {
            _ = try policy.resolveRequest(
                pathId: "agent.session.mode.update",
                parameters: ["sessionId": "session-a"],
                query: [:],
                body: ["title": "not allowed"]
            )
        }
        expectThrows("path traversal") {
            _ = try policy.resolveRequest(
                pathId: "agent.session.snapshot",
                parameters: ["sessionId": "../private"],
                query: [:],
                body: nil
            )
        }
        expectThrows("unlisted query") {
            _ = try policy.resolveRequest(
                pathId: "system.health",
                parameters: [:],
                query: ["url": "http://example.com"],
                body: nil
            )
        }
        expectThrows("artifact ownership query") {
            _ = try policy.resolveRequest(
                pathId: "agent.artifact.get",
                parameters: ["artifactId": "artifact:alpha"],
                query: [:],
                body: nil
            )
        }
        expectThrows("knowledge apply requires the preview hash") {
            _ = try policy.resolveRequest(
                pathId: "knowledge.database.apply",
                parameters: [:],
                query: [:],
                body: [
                    "runId": "run:1",
                    "confirm": "apply",
                    "previewToken": "preview-token",
                    "expectedRuntimeRevision": "runtime:1",
                ]
            )
        }
        expectThrows("intercom source identity injection") {
            _ = try policy.resolveRequest(
                pathId: "agent.session.intercom.send",
                parameters: ["sessionId": "session-a"],
                query: [:],
                body: [
                    "kind": "send",
                    "clientMessageId": "message-a",
                    "content": "hello",
                    "sourceSessionId": "session-b",
                ]
            )
        }
        expectThrows("deep search is local only") {
            _ = try policy.resolveRequest(
                pathId: "agent.deep-search",
                parameters: [:],
                query: [:],
                body: ["query": "hello", "privacyDisposition": "allowed"],
                scope: .remote
            )
        }
        expectThrows("remote configuration audit identity injection") {
            _ = try policy.resolveRequest(
                pathId: "agent.configuration.update",
                parameters: [:],
                query: [:],
                body: [
                    "expectedRevision": 4,
                    "changes": ["defaultModel": "local"],
                    "updatedBy": "spoofed-device",
                ],
                scope: .remote
            )
        }
        expectThrows("invalid memory kind") {
            _ = try policy.resolveRequest(
                pathId: "memory.pages",
                parameters: ["kind": "../../etc"],
                query: [:],
                body: nil
            )
        }
        expectThrows("missing memory graph plane") {
            _ = try policy.resolveRequest(
                pathId: "memory.graph.get",
                parameters: [:],
                query: [:],
                body: nil
            )
        }
        expectThrows("invalid memory entity kind") {
            _ = try policy.resolveRequest(
                pathId: "memory.entity.get",
                parameters: ["kind": "book", "entityId": "book-1"],
                query: [:],
                body: nil
            )
        }

        print("NativeRoutePolicyTests: OK")
    }
}
