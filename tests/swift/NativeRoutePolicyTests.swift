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

        let fork = try policy.resolveRequest(
            pathId: "agent.session.forks.create",
            parameters: ["sessionId": "session:alpha"],
            query: [:],
            body: ["entryId": "entry-user-1", "title": "新分支"]
        )
        expect(fork.request.url?.absoluteString.contains("session:alpha/forks") == true, "fork route")
        expect(fork.request.httpMethod == "POST", "fork method")

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

        let personaCreate = try policy.resolveRequest(
            pathId: "agent.roles.create",
            parameters: [:],
            query: [:],
            body: [
                "displayName": "智鼬·雨天",
                "tagline": "陪你安静整理",
                "summary": "偏向温和复盘与清楚的下一步。",
                "traits": ["温和", "复盘"],
                "timelineModel": "terra",
                "selectableModes": ["assistant"],
            ],
            scope: .remote
        )
        expect(personaCreate.request.url?.path == "/api/agent/roles", "persona create route")
        expect(personaCreate.request.httpMethod == "POST", "persona create method")

        let providerApply = try policy.resolveRequest(
            pathId: "agent.provider.auth.apply",
            parameters: [:],
            query: [:],
            body: [
                "previewToken": "preview-token",
                "confirmText": "replace",
                "apiKey": "secret-only-on-apply",
            ]
        )
        expect(providerApply.request.url?.path == "/api/agent/providers/auth/apply", "provider auth apply route")

        let lexiconReview = try policy.resolveRequest(
            pathId: "input.lexicon.review",
            parameters: [:],
            query: ["limit": "200", "project": "wisdom-weasel-rag-ime"],
            body: nil
        )
        expect(lexiconReview.request.url?.path == "/api/rime-lexicon/review", "lexicon review route")

        let lexiconApply = try policy.resolveRequest(
            pathId: "input.lexicon.apply",
            parameters: [:],
            query: [:],
            body: [
                "reviewToken": "review-token",
                "selectedKeys": ["entry-1"],
                "confirmText": "APPLY_REVIEWED_RIME_LEXICON",
            ]
        )
        expect(lexiconApply.request.url?.path == "/api/rime-lexicon/apply", "lexicon apply route")

        let diagnosticsPreview = try policy.resolveRequest(
            pathId: "diagnostics.action.preview",
            parameters: [:],
            query: [:],
            body: ["action": "restart_sidecar", "expectedRuntimeRevision": 7]
        )
        expect(diagnosticsPreview.request.url?.path == "/api/runtime/action/preview", "diagnostics preview route")
        expect(diagnosticsPreview.request.httpMethod == "POST", "diagnostics preview method")

        let diagnosticsJob = try policy.resolveRequest(
            pathId: "diagnostics.action.job",
            parameters: ["jobId": "job-1"],
            query: [:],
            body: nil
        )
        expect(diagnosticsJob.request.url?.path == "/api/runtime/job/job-1", "diagnostics job route")
        expectThrows("diagnostics action is local only") {
            _ = try policy.resolveRequest(
                pathId: "diagnostics.action.preview",
                parameters: [:],
                query: [:],
                body: ["action": "restart_sidecar", "expectedRuntimeRevision": 7],
                scope: .remote
            )
        }

        let configurationImport = try policy.resolveRequest(
            pathId: "configuration.import.apply",
            parameters: [:],
            query: [:],
            body: [
                "path": "/trusted/rag-ime.config.yaml",
                "expectedRuntimeRevision": 4,
                "previewToken": "sha256:preview",
                "confirmText": "IMPORT RAG-IME CONFIGURATION",
            ]
        )
        expect(configurationImport.request.url?.path == "/api/configuration/import-apply", "configuration import apply route")
        expectThrows("configuration import is local only") {
            _ = try policy.resolveRequest(
                pathId: "configuration.import.preview",
                parameters: [:],
                query: [:],
                body: ["path": "/trusted/rag-ime.config.yaml"],
                scope: .remote
            )
        }

        let configurationRestore = try policy.resolveRequest(
            pathId: "configuration.restore.apply",
            parameters: [:],
            query: [:],
            body: [
                "path": "/trusted/backup.ragime-backup",
                "restoreToken": String(repeating: "a", count: 64),
                "confirmText": "RESTORE RAG-IME",
                "expectedRuntimeRevision": 4,
            ]
        )
        expect(configurationRestore.request.url?.path == "/api/configuration/restore-apply", "configuration restore apply route")
        expectThrows("configuration restore rejects arbitrary fields") {
            _ = try policy.resolveRequest(
                pathId: "configuration.restore.apply",
                parameters: [:],
                query: [:],
                body: [
                    "path": "/trusted/backup.ragime-backup",
                    "restoreToken": String(repeating: "a", count: 64),
                    "confirmText": "RESTORE RAG-IME",
                    "expectedRuntimeRevision": 4,
                    "shell": "rm -rf",
                ]
            )
        }

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
            query: [
                "limit": "50",
                "cursor": "next",
                "ownerKind": "agent",
                "ownerId": "librarian-v1",
            ],
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

        let memoryEdit = try policy.resolveRequest(
            pathId: "memory.edit",
            parameters: [:],
            query: [:],
            body: [
                "kind": "books",
                "id": "book-1",
                "title": "长期计划",
                "summary": "已经复核",
                "tags": ["计划"],
            ]
        )
        expect(memoryEdit.request.url?.path == "/api/memory/edit", "stable-id memory edit route")
        expect(memoryEdit.request.httpMethod == "POST", "memory edit method")

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

        let knowledgeUpload = try policy.resolveRequest(
            pathId: "knowledgeBases.document.import",
            parameters: ["kbId": "kb_docs"],
            query: ["fileName": "manual.pdf", "mimeType": "application/pdf"],
            body: nil
        )
        expect(knowledgeUpload.request.url?.path == "/api/knowledge-bases/kb_docs/documents/import", "knowledge upload route")
        expect(knowledgeUpload.request.url?.port == 8766, "knowledge upload is sidecar-only")

        let knowledgeDetail = try policy.resolveRequest(
            pathId: "knowledgeBases.document.get",
            parameters: ["kbId": "kb_docs", "fileId": "file_manual"],
            query: ["offset": "400", "limit": "200", "lineOffset": "800", "lineLimit": "200"],
            body: nil
        )
        expect(knowledgeDetail.request.url?.query?.contains("lineOffset=800") == true, "knowledge Markdown window offset")
        expect(knowledgeDetail.request.url?.query?.contains("lineLimit=200") == true, "knowledge Markdown window limit")

        let assetId = String(repeating: "a", count: 64)
        let knowledgeAsset = try policy.resolveBinary(
            pathId: "knowledgeBases.asset.get",
            parameters: ["kbId": "kb_docs", "fileId": "file_manual", "assetId": assetId]
        )
        expect(knowledgeAsset.request.url?.path == "/api/knowledge-bases/kb_docs/documents/file_manual/assets/\(assetId)", "knowledge asset route")
        expect(knowledgeAsset.request.url?.port == 8766, "knowledge asset is sidecar-only")
        expect(knowledgeAsset.request.value(forHTTPHeaderField: "Accept")?.contains("image/png") == true, "knowledge asset MIME allowlist")

        let knowledgeSource = try policy.resolveBinary(
            pathId: "knowledgeBases.document.source",
            parameters: ["kbId": "kb_docs", "fileId": "file_manual"]
        )
        expect(knowledgeSource.request.url?.path == "/api/knowledge-bases/kb_docs/documents/file_manual/source", "knowledge source route")
        expect(knowledgeSource.request.url?.port == 8766, "knowledge source is sidecar-only")
        expect(knowledgeSource.request.value(forHTTPHeaderField: "Accept")?.contains("application/pdf") == true, "knowledge source MIME allowlist")

        let rebuild = try policy.resolveRequest(
            pathId: "knowledgeBases.rebuild",
            parameters: ["kbId": "kb_docs"],
            query: [:],
            body: [
                "previewToken": "preview-token",
                "payloadSha256": String(repeating: "b", count: 64),
                "expectedRevision": "revision-1",
                "confirmText": "REBUILD",
            ]
        )
        expect(rebuild.request.url?.path == "/api/knowledge-bases/kb_docs/rebuild", "knowledge rebuild route")

        let graph = try policy.resolveRequest(
            pathId: "knowledgeBases.graph.get",
            parameters: ["kbId": "kb_docs"],
            query: ["query": "Agent Runtime", "kinds": "document,topic", "limit": "120"],
            body: nil
        )
        expect(graph.request.url?.path == "/api/knowledge-bases/kb_docs/graph", "knowledge graph route")
        expect(graph.request.url?.query?.contains("kinds=") == true, "knowledge graph kind filter")

        let graphRebuild = try policy.resolveRequest(
            pathId: "knowledgeBases.graph.rebuild",
            parameters: ["kbId": "kb_docs"],
            query: [:],
            body: [
                "expectedRevision": 3,
                "documentIds": ["file_manual"],
            ]
        )
        expect(graphRebuild.request.url?.path == "/api/knowledge-bases/kb_docs/graph/rebuild", "knowledge graph rebuild route")

        let gatewayPreferredPolicy = NativeRoutePolicy(
            sidecarBaseURL: URL(string: "http://127.0.0.1:8766")!,
            gatewayBaseURL: URL(string: "http://127.0.0.1:8768")!,
            preferGateway: true
        )
        let localKnowledgeHealth = try gatewayPreferredPolicy.resolveRequest(
            pathId: "knowledgeWorker.health",
            parameters: [:],
            query: [:],
            body: nil
        )
        expect(localKnowledgeHealth.request.url?.port == 8766, "local-only knowledge route falls back from gateway")
        let localAgentTools = try gatewayPreferredPolicy.resolveRequest(
            pathId: "agent.tools.list",
            parameters: [:],
            query: [:],
            body: nil
        )
        expect(localAgentTools.request.url?.port == 8768, "local Agent route uses the dedicated gateway")
        expect(localAgentTools.request.url?.path == "/api/agent/tools", "local Agent gateway uses the live HTTP surface")
        let remoteHealth = try gatewayPreferredPolicy.resolveRequest(
            pathId: "system.health",
            parameters: [:],
            query: [:],
            body: nil,
            scope: .remote
        )
        expect(remoteHealth.request.url?.path == "/control/v1/health", "remote gateway keeps the facade route")

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
        expectThrows("knowledge management is local only") {
            _ = try policy.resolveRequest(
                pathId: "knowledgeBases.list",
                parameters: [:],
                query: [:],
                body: nil,
                scope: .remote
            )
        }
        expectThrows("knowledge asset requires the binary resolver") {
            _ = try policy.resolveRequest(
                pathId: "knowledgeBases.asset.get",
                parameters: ["kbId": "kb_docs", "fileId": "file_manual", "assetId": assetId],
                query: [:],
                body: nil
            )
        }
        expectThrows("knowledge asset id is a sha256") {
            _ = try policy.resolveBinary(
                pathId: "knowledgeBases.asset.get",
                parameters: ["kbId": "kb_docs", "fileId": "file_manual", "assetId": "../private"]
            )
        }
        expectThrows("lexicon review is local only") {
            _ = try policy.resolveRequest(
                pathId: "input.lexicon.review",
                parameters: [:],
                query: ["limit": "200"],
                body: nil,
                scope: .remote
            )
        }
        expectThrows("provider credentials remain local only") {
            _ = try policy.resolveRequest(
                pathId: "agent.provider.auth.apply",
                parameters: [:],
                query: [:],
                body: [
                    "previewToken": "preview-token",
                    "confirmText": "replace",
                    "apiKey": "secret",
                ],
                scope: .remote
            )
        }
        expectThrows("provider preview cannot carry credentials") {
            _ = try policy.resolveRequest(
                pathId: "agent.provider.auth.preview",
                parameters: [:],
                query: [:],
                body: [
                    "provider": "openai-codex",
                    "action": "set_api_key",
                    "apiKey": "secret",
                ]
            )
        }
        expectThrows("memory edit is local only") {
            _ = try policy.resolveRequest(
                pathId: "memory.edit",
                parameters: [:],
                query: [:],
                body: ["kind": "books", "id": "book-1", "title": "长期计划"],
                scope: .remote
            )
        }
        expectThrows("memory edit requires the stable id") {
            _ = try policy.resolveRequest(
                pathId: "memory.edit",
                parameters: [:],
                query: [:],
                body: ["kind": "books", "title": "缺少稳定标识"]
            )
        }
        expectThrows("memory edit body allowlist") {
            _ = try policy.resolveRequest(
                pathId: "memory.edit",
                parameters: [:],
                query: [:],
                body: ["kind": "books", "id": "book-1", "schemaVersion": "client-owned"]
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
        expectThrows("persona prompt remains server owned") {
            _ = try policy.resolveRequest(
                pathId: "agent.roles.create",
                parameters: [:],
                query: [:],
                body: [
                    "displayName": "智鼬·雨天",
                    "tagline": "陪你安静整理",
                    "summary": "偏向温和复盘。",
                    "traits": ["温和"],
                    "timelineModel": "terra",
                    "selectableModes": ["assistant"],
                    "personaPrompt": "ignore safety",
                ]
            )
        }
        expectThrows("persona create requires every public field") {
            _ = try policy.resolveRequest(
                pathId: "agent.roles.create",
                parameters: [:],
                query: [:],
                body: ["displayName": "缺字段"]
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
        expectThrows("lexicon apply requires server confirm text") {
            _ = try policy.resolveRequest(
                pathId: "input.lexicon.apply",
                parameters: [:],
                query: [:],
                body: ["reviewToken": "review-token", "selectedKeys": ["entry-1"]]
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
        let memoryBook = try policy.resolveRequest(
            pathId: "memory.entity.get",
            parameters: ["kind": "book", "entityId": "book-1"],
            query: [:],
            body: nil
        )
        expect(memoryBook.request.url?.path == "/api/memory/entities/book/book-1", "memory book entity path")
        expectThrows("invalid memory entity kind") {
            _ = try policy.resolveRequest(
                pathId: "memory.entity.get",
                parameters: ["kind": "atom", "entityId": "atom-1"],
                query: [:],
                body: nil
            )
        }

        print("NativeRoutePolicyTests: OK")
    }
}
