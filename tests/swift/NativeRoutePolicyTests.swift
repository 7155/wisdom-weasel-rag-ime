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

        let roomSnapshot = try policy.resolveRequest(
            pathId: "agent.room.snapshot",
            parameters: ["roomId": "room:alpha"],
            query: [:],
            body: nil
        )
        expect(roomSnapshot.request.url?.absoluteString.contains("room:alpha/snapshot") == true, "room snapshot route")
        expect(roomSnapshot.request.httpMethod == "GET", "room snapshot method")

        _ = try policy.resolveRequest(
            pathId: "memory.pages",
            parameters: ["kind": "books"],
            query: ["limit": "50", "cursor": "next"],
            body: nil,
            scope: .remote
        )

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
        expectThrows("invalid memory kind") {
            _ = try policy.resolveRequest(
                pathId: "memory.pages",
                parameters: ["kind": "../../etc"],
                query: [:],
                body: nil
            )
        }

        print("NativeRoutePolicyTests: OK")
    }
}
