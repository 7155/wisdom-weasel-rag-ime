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
            body: ["message": "hello", "delivery": "prompt"]
        )
        expect(session.request.url?.absoluteString.contains("session:alpha/prompt") == true, "session path encoding")
        expect(session.request.httpMethod == "POST", "prompt method")

        let fork = try policy.resolveRequest(
            pathId: "agent.session.forks.create",
            parameters: ["sessionId": "session:alpha"],
            query: [:],
            body: ["entryId": "entry-user-1", "title": "新分支"]
        )
        expect(fork.request.url?.port == 8768, "fork route always uses the dedicated Pi gateway")
        expect(fork.request.url?.absoluteString.contains("session:alpha/forks") == true, "fork route")
        expect(fork.request.httpMethod == "POST", "fork method")
        let participantSteer = try policy.resolveRequest(
            pathId: "agent.room.participant.steer",
            parameters: ["roomId": "room:alpha"],
            query: [:],
            body: [
                "action": "steer_participant",
                "rootId": "root:alpha",
                "participantId": "participant:alpha",
                "clientActionId": "action:alpha",
                "message": "请立即收敛并返回当前结果",
            ]
        )
        expect(participantSteer.request.url?.path == "/api/agent/rooms/room:alpha/steer", "participant steer route")
        expect(participantSteer.request.httpMethod == "POST", "participant steer method")
        let guidedGoal = try policy.resolveRequest(
            pathId: "agent.session.goal.mutate",
            parameters: ["sessionId": "session:alpha"],
            query: [:],
            body: [
                "action": "confirm_setup",
                "expectedRevision": 0,
                "confirmed": true,
                "objective": "Ship the governed workflow",
                "successCriteria": "All receipts validate",
                "evidenceExpectations": ["migration receipt"],
                "tokenBudget": 1000,
                "timeBudgetMs": 60000,
                "reason": "required for cancellation parity",
            ]
        )
        expect(guidedGoal.request.url?.path.contains("/session:alpha/goal") == true, "guided Goal route")
        expect(guidedGoal.request.httpMethod == "POST", "guided Goal method")

        let capabilityPolicy = try policy.resolveRequest(
            pathId: "agent.session.capability-policy.update",
            parameters: ["sessionId": "session:alpha"],
            query: [:],
            body: ["capabilityDisclosurePreferences": ["workspace.read": "enabled"]]
        )
        expect(capabilityPolicy.request.url?.path == "/api/agent/sessions/session:alpha", "capability policy route")
        expect(capabilityPolicy.request.httpMethod == "PATCH", "capability policy method")

        let backgroundJobs = try policy.resolveRequest(
            pathId: "agent.session.backgroundJobs.list",
            parameters: ["sessionId": "session:alpha"],
            query: ["limit": "20", "status": "running"],
            body: nil
        )
        expect(backgroundJobs.request.url?.path == "/api/agent/sessions/session:alpha/background-jobs", "background jobs list route")
        expect(backgroundJobs.request.url?.query?.contains("limit=20") == true, "background jobs limit query")
        expect(backgroundJobs.request.url?.query?.contains("status=running") == true, "background jobs status query")

        let backgroundJob = try policy.resolveRequest(
            pathId: "agent.session.backgroundJob.get",
            parameters: ["sessionId": "session:alpha", "jobId": "bg_123"],
            query: [:],
            body: nil
        )
        expect(backgroundJob.request.url?.path == "/api/agent/sessions/session:alpha/background-jobs/bg_123", "background job detail route")

        let backgroundJobLogs = try policy.resolveRequest(
            pathId: "agent.session.backgroundJob.logs",
            parameters: ["sessionId": "session:alpha", "jobId": "bg_123"],
            query: ["cursor": "64", "limitBytes": "4096"],
            body: nil
        )
        expect(backgroundJobLogs.request.url?.path == "/api/agent/sessions/session:alpha/background-jobs/bg_123/logs", "background job logs route")
        expect(backgroundJobLogs.request.url?.query?.contains("cursor=64") == true, "background job logs cursor")
        expect(backgroundJobLogs.request.url?.query?.contains("limitBytes=4096") == true, "background job logs bound")

        let backgroundJobCancel = try policy.resolveRequest(
            pathId: "agent.session.backgroundJob.cancel",
            parameters: ["sessionId": "session:alpha", "jobId": "bg_123"],
            query: [:],
            body: ["reason": "user-request"]
        )
        expect(backgroundJobCancel.request.url?.path == "/api/agent/sessions/session:alpha/background-jobs/bg_123/cancel", "background job cancel route")
        expect(backgroundJobCancel.request.httpMethod == "POST", "background job cancel method")

        let workDocumentsList = try policy.resolveRequest(
            pathId: "workDocuments.list",
            parameters: [:],
            query: ["limit": "25"],
            body: nil
        )
        expect(workDocumentsList.request.url?.path == "/api/agent/work-documents", "work documents list route")

        let workDocumentsHistory = try policy.resolveRequest(
            pathId: "workDocuments.history.search",
            parameters: [:],
            query: ["query": "release", "limit": "10"],
            body: nil
        )
        expect(workDocumentsHistory.request.url?.path == "/api/agent/work-documents/history/search", "work documents history route")

        let documentParameters = ["documentId": "workdoc_123"]
        let workDocument = try policy.resolveRequest(
            pathId: "workDocuments.get",
            parameters: documentParameters,
            query: [:],
            body: nil
        )
        expect(workDocument.request.url?.path == "/api/agent/work-documents/workdoc_123", "work document detail route")

        let workDocumentRegister = try policy.resolveRequest(
            pathId: "workDocuments.register",
            parameters: [:],
            query: [:],
            body: [
                "authorityKind": "session_todo",
                "authorityId": "session:alpha",
                "authorityRevision": 2,
                "workspaceRoot": "/tmp/workspace",
                "sourcePath": "docs/agent/work.md",
                "title": "Work",
            ]
        )
        expect(workDocumentRegister.request.url?.path == "/api/agent/work-documents", "work document register route")
        expect(workDocumentRegister.request.httpMethod == "POST", "work document register method")

        let workDocumentArchive = try policy.resolveRequest(
            pathId: "workDocuments.archive",
            parameters: documentParameters,
            query: [:],
            body: ["terminalReceiptId": "receipt-terminal"]
        )
        expect(workDocumentArchive.request.url?.path == "/api/agent/work-documents/workdoc_123/archive", "work document archive route")

        let workDocumentRepair = try policy.resolveRequest(
            pathId: "workDocuments.repair",
            parameters: documentParameters,
            query: [:],
            body: [:]
        )
        expect(workDocumentRepair.request.url?.path == "/api/agent/work-documents/workdoc_123/repair", "work document repair route")

        let workDocumentReopen = try policy.resolveRequest(
            pathId: "workDocuments.reopen",
            parameters: documentParameters,
            query: [:],
            body: ["authorityRevision": 3, "transitionReceiptId": "receipt-reopen"]
        )
        expect(workDocumentReopen.request.url?.path == "/api/agent/work-documents/workdoc_123/reopen", "work document reopen route")

        let workDocumentErasePreview = try policy.resolveRequest(
            pathId: "workDocuments.erase.preview",
            parameters: documentParameters,
            query: [:],
            body: ["sessionId": "session:alpha"]
        )
        expect(workDocumentErasePreview.request.url?.path == "/api/agent/work-documents/workdoc_123/erase-preview", "work document erase preview route")

        let workDocumentErase = try policy.resolveRequest(
            pathId: "workDocuments.erase",
            parameters: documentParameters,
            query: [:],
            body: [
                "sessionId": "session:alpha",
                "approvalId": "approval-1",
                "payloadSha256": String(repeating: "a", count: 64),
            ]
        )
        expect(workDocumentErase.request.url?.path == "/api/agent/work-documents/workdoc_123/erase", "work document erase route")

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

        let observationSnapshot = try policy.resolveRequest(
            pathId: "observability.snapshot",
            parameters: [:],
            query: ["sessionId": "session-a", "limit": "100"],
            body: nil
        )
        expect(observationSnapshot.request.url?.path == "/api/observability/snapshot", "observation snapshot route")

        let observationEvents = try policy.resolveSubscription(
            pathId: "observability.events",
            parameters: [:],
            query: ["sessionId": "session-a"],
            lastEventId: "observation:41"
        )
        expect(observationEvents.request.url?.path == "/api/observability/events", "observation event route")
        expect(observationEvents.request.value(forHTTPHeaderField: "Last-Event-ID") == "observation:41", "observation resume cursor")

        let roomSnapshot = try policy.resolveRequest(
            pathId: "agent.room.snapshot",
            parameters: ["roomId": "room:alpha"],
            query: [:],
            body: nil
        )
        expect(roomSnapshot.request.url?.absoluteString.contains("room:alpha/snapshot") == true, "room snapshot route")
        expect(roomSnapshot.request.httpMethod == "GET", "room snapshot method")

        let roomCreate = try policy.resolveRequest(
            pathId: "agent.rooms.create",
            parameters: [:],
            query: [:],
            body: [
                "title": "前端优化",
                "roomKind": "collaboration",
                "participants": [
                    ["roleId": "role-a", "roleVersion": "1"],
                    ["roleId": "role-b", "roleVersion": "1"],
                ],
                "workspaceRoots": ["/tmp/project"],
                "executionMode": "workspace_managed",
                "workspaceScopeConfirmation": "APPROVE_WORKSPACE_SCOPE",
            ]
        )
        expect(roomCreate.request.url?.path == "/api/agent/rooms", "room create route accepts governed workspace fields")
        expect(roomCreate.request.httpMethod == "POST", "room create method")

        let roomUpdate = try policy.resolveRequest(
            pathId: "agent.room.archive",
            parameters: ["roomId": "room:alpha"],
            query: [:],
            body: [
                "executionMode": "full_trust",
                "dangerousModeConfirmation": "ENABLE_FULL_TRUST",
            ]
        )
        expect(roomUpdate.request.url?.absoluteString.contains("room:alpha") == true, "room update accepts governed execution fields")

        let personaCreate = try policy.resolveRequest(
            pathId: "agent.roles.create",
            parameters: [:],
            query: [:],
            body: [
                "displayName": "澄·雨天",
                "tagline": "陪你安静整理",
                "summary": "偏向温和复盘与清楚的下一步。",
                "traits": ["温和", "复盘"],
                "timelineModel": "terra",
                "selectableModes": ["assistant"],
                "suitableTasks": ["温和复盘", "整理下一步"],
                "unsuitableTasks": ["高风险独立决定"],
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

        let activityTimelineCalendar = try policy.resolveRequest(
            pathId: "memory.activityTimeline.calendar",
            parameters: [:],
            query: ["month": "2026-08"],
            body: nil,
            scope: .remote
        )
        expect(activityTimelineCalendar.request.url?.path == "/api/memory/activity-timeline/calendar", "activity timeline calendar remote route")
        expect(activityTimelineCalendar.request.url?.query?.contains("month=2026-08") == true, "activity timeline calendar month")

        let activityTimelineCatchUp = try policy.resolveRequest(
            pathId: "memory.activityTimeline.build",
            parameters: [:],
            query: [:],
            body: ["date": "2026-08-12", "throughToday": true],
            scope: .remote
        )
        expect(activityTimelineCatchUp.request.url?.path == "/api/memory/activity-timeline/build", "activity timeline catch-up route")
        let activityTimelineCatchUpBody = try JSONSerialization.jsonObject(with: activityTimelineCatchUp.request.httpBody ?? Data()) as? [String: Any]
        expect(activityTimelineCatchUpBody?["throughToday"] as? Bool == true, "activity timeline catch-up body")

        let memoryMaintenanceStatus = try policy.resolveRequest(
            pathId: "agent.memoryMaintenance.run",
            parameters: [:],
            query: ["limit": "12", "project": "wisdom-weasel-rag-ime"],
            body: nil
        )
        expect(memoryMaintenanceStatus.request.url?.path == "/api/agent/memory-maintenance", "memory maintenance status route")
        expect(memoryMaintenanceStatus.request.url?.query?.contains("limit=12") == true, "memory maintenance status limit")

        let memoryMaintenanceRun = try policy.resolveRequest(
            pathId: "agent.memoryMaintenance.run",
            parameters: [:],
            query: ["runId": "memory_book_user_1", "project": "wisdom-weasel-rag-ime"],
            body: nil
        )
        expect(memoryMaintenanceRun.request.url?.query?.contains("runId=memory_book_user_1") == true, "memory maintenance detail runId")

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
        let debugContext = try policy.resolveRequest(
            pathId: "agent.session.debugContext.get",
            parameters: ["sessionId": "session:alpha"],
            query: ["turnId": "turn:one"],
            body: nil
        )
        expect(debugContext.request.url?.port == 8768, "debug context always uses the Pi gateway")
        expect(debugContext.request.url?.path == "/api/agent/sessions/session:alpha/debug-context", "debug context keeps the local gateway route")
        expect(debugContext.request.url?.query == "turnId=turn:one", "debug context forwards the turn identifier")
        expectThrows("debug context stays local only") {
            _ = try gatewayPreferredPolicy.resolveRequest(
                pathId: "agent.session.debugContext.get",
                parameters: ["sessionId": "session:alpha"],
                query: [:],
                body: nil,
                scope: .remote
            )
        }
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
        _ = try policy.resolveRequest(
            pathId: "agent.session.mode.update",
            parameters: ["sessionId": "session-a"],
            query: [:],
            body: [
                "mode": "coordinator",
                "executionMode": "workspace_managed",
                "toolProfileVersion": "control-center-auto-approve-v1",
                "toolAllowlistMode": "profile",
                "workspaceRoots": ["/tmp/project"],
                "workspaceScopeConfirmation": "APPROVE_WORKSPACE_SCOPE",
                "dangerousModeConfirmation": "ENABLE_FULL_TRUST",
                "projectContextEnabled": false,
                "piSkillsEnabled": true,
                "codexSkillsEnabled": true,
            ]
        )
        expectThrows("persona prompt remains server owned") {
            _ = try policy.resolveRequest(
                pathId: "agent.roles.create",
                parameters: [:],
                query: [:],
                body: [
                    "displayName": "澄·雨天",
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
        expectThrows("participant steer requires a user message") {
            _ = try policy.resolveRequest(
                pathId: "agent.room.participant.steer",
                parameters: ["roomId": "room:alpha"],
                query: [:],
                body: [
                    "action": "steer_participant",
                    "rootId": "root:alpha",
                    "clientActionId": "action:alpha",
                ]
            )
        }
        expectThrows("obsolete Room Kernel routes are unavailable") {
            _ = try policy.resolveRequest(
                pathId: "agent.room.kernel.snapshot",
                parameters: ["roomId": "room:alpha"],
                query: [:],
                body: nil
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
