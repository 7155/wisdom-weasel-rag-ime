from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_context_runtime import AgentContextRuntime
from rag_ime.agent_media import AgentMediaStore
from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tool_artifacts import AgentToolArtifactProjector
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.agent_workspace import WorkspaceHarness, WorkspaceHarnessError
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.work_documents import WorkDocumentService


class _Management:
    def __init__(self):
        self.task_events = {}
        self.runtime_jobs = {}
        self.memory_requests = []
        self.ai_paused = False
        self.runtime_revision = 1
        self.provider_configuration_revision = 1
        self.provider_profiles = {
            "instant": {
                "provider": "mlx",
                "endpoint": "http://127.0.0.1:8767",
                "model": "",
            },
            "knowledge": {
                "provider": "deepseek",
                "endpoint": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
            },
            "voice": {"provider": "native_streaming"},
        }
        self.tasks = [
            {
                "id": "task:1",
                "date": "2026-07-13",
                "title": "接入 Pi",
                "status": "todo",
                "project": "wisdom-weasel-rag-ime",
                "updatedAtMs": 20,
            },
            {
                "id": "task:2",
                "date": "2026-07-13",
                "title": "协议测试",
                "status": "done",
                "project": "wisdom-weasel-rag-ime",
                "updatedAtMs": 19,
            },
        ]

    def overview(self):
        return {
            "settingsRevision": "settings:1",
            "runtimeRevision": self.runtime_revision,
            "aiPaused": self.ai_paused,
            "components": {"sidecar": {"ok": True}, "predictor": {"ok": False}},
            "memory": {"memoryBookCount": 2},
            "lastPrediction": {"visibleCandidate": "继续实现"},
        }

    def runtime_status(self):
        return {
            "ok": True,
            "runtimeRevision": self.runtime_revision,
            "components": {"sidecar": {"ok": True}, "predictor": {"ok": False}},
        }

    def runtime_components(self):
        return {"ok": True, "items": [{"id": "sidecar", "ok": True}]}

    def start_runtime_action(self, payload):
        if payload["action"] == "restart_sidecar":
            self.runtime_jobs["runtime:1"] = {
                "jobId": "runtime:1",
                "action": payload["action"],
                "status": "external-supervisor-required",
                "error": "external supervisor required",
                "result": {
                    "externalCommand": [
                        "launchctl",
                        "kickstart",
                        "-k",
                        f"gui/{os.getuid()}/com.rag-ime.sidecar",
                    ]
                },
            }
            return {"ok": True, "jobId": "runtime:1", "job": self.runtime_jobs["runtime:1"]}
        if payload["action"] == "stop_ai":
            self.ai_paused = True
        elif payload["action"] == "resume_ai":
            self.ai_paused = False
        self.runtime_revision += 1
        self.runtime_jobs["runtime:1"] = {
            "jobId": "runtime:1",
            "action": payload["action"],
            "status": "succeeded",
            "error": "",
        }
        return {"ok": True, "jobId": "runtime:1", "job": self.runtime_jobs["runtime:1"]}

    def runtime_job(self, job_id):
        return {"ok": True, "jobId": job_id, "job": self.runtime_jobs[job_id]}

    def history_page(self, request):
        return {
            "items": [{"id": 1, "textPreview": "把普通生成和深度检索分开", "rawTextVisible": False}][
                : request.limit
            ],
            "nextCursor": "",
        }

    def portable_backup_export(self, payload):
        target = Path(payload["destination"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"portable-backup-fixture")
        return {
            "ok": True,
            "path": str(target),
            "sizeBytes": target.stat().st_size,
            "databaseCounts": {"memory_books": 2, "agent_sessions": 1},
            "rimeFileCount": 3,
            "secretsIncluded": False,
            "auditId": 61,
        }

    def portable_restore_preview(self, payload):
        source = Path(payload["path"])
        if not source.is_file():
            raise ValueError("backup not found")
        return {
            "ok": True,
            "valid": True,
            "path": str(source),
            "restoreToken": "7" * 64,
            "createdAtMs": 1_700_000_000_000,
            "databaseCounts": {"memory_books": 2, "agent_sessions": 1},
            "databaseMigrationVersion": 18,
            "rimeFileCount": 3,
            "requiresConfirmation": "RESTORE RAG-IME",
            "requiresRestart": True,
        }

    def provider_configuration(self):
        return {
            "ok": True,
            "configurationHash": f"provider:{self.provider_configuration_revision}",
            "settingsRevision": "settings:1",
            "runtimeRevision": self.runtime_revision,
            "providers": {
                **{slot: dict(profile) for slot, profile in self.provider_profiles.items()},
                "secretsIncluded": False,
            },
        }

    def provider_configuration_apply(self, payload):
        if payload["expectedConfigurationHash"] != f"provider:{self.provider_configuration_revision}":
            raise ValueError("provider configuration changed after the approval preview was created")
        slot = payload["slot"]
        before = dict(self.provider_profiles[slot])
        after = {"provider": payload["provider"]}
        if slot != "voice":
            after.update({"endpoint": payload["endpoint"], "model": payload["model"]})
        self.provider_profiles[slot] = after
        self.provider_configuration_revision += 1
        self.runtime_revision += 1
        return {
            "ok": True,
            "auditId": 62,
            "slot": slot,
            "before": before,
            "after": dict(after),
            "configurationHash": f"provider:{self.provider_configuration_revision}",
            "settingsRevision": "settings:1",
            "runtimeRevision": self.runtime_revision,
            "restartComponent": "predictor" if slot == "instant" else "sidecar",
            "existingSecretPreserved": True,
        }

    def planning_dashboard(self, *, plan_date, project):
        return {
            "date": plan_date or "2026-07-13",
            "project": project,
            "tasks": [dict(task) for task in self.tasks if task["date"] == (plan_date or "2026-07-13")],
            "goals": [],
        }

    def planning_task_action(self, payload):
        target = {
            "complete": "done",
            "start": "in_progress",
            "reopen": "todo",
            "cancel": "cancelled",
        }[payload["action"]]
        task = next(item for item in self.tasks if item["id"] == payload["taskId"])
        previous = task["status"]
        task["status"] = target
        task["updatedAtMs"] += 1
        event_id = f"task-event:{len(self.task_events) + 1}"
        self.task_events[event_id] = {"taskId": task["id"], "previous": previous}
        return {
            "ok": True,
            "auditId": 42,
            "eventId": event_id,
            "task": dict(task),
            "undoAvailable": True,
        }

    def planning_undo_task_event(self, payload):
        event = self.task_events[payload["eventId"]]
        task = next(item for item in self.tasks if item["id"] == event["taskId"])
        task["status"] = event["previous"]
        task["updatedAtMs"] += 1
        return {"ok": True, "auditId": 43, "task": dict(task)}

    def memory_page(self, kind, request):
        self.memory_requests.append((kind, request))
        if kind == "apps":
            return {
                "items": [
                    {
                        "id": "com.openai.codex",
                        "title": "Codex",
                        "eventCount": 12,
                        "atomCount": 3,
                        "bookCount": 1,
                    }
                ],
                "nextCursor": "",
            }
        if kind == "books":
            return {
                "items": [
                    {
                        "id": "book:1",
                        "title": "输入法项目",
                        "summary": "记录输入法 Agent 与 RAG 的设计决定",
                        "tags": ["输入法", "Agent"],
                        "atomCount": 2,
                        "updated_at_ms": 20,
                        "sourceStartMs": 10,
                        "sourceEndMs": 20,
                        "memories": [
                            {
                                "id": "atom:decision:1",
                                "type": "decision",
                                "text": "普通生成不经过 Pi",
                                "updatedAtMs": 20,
                            }
                        ],
                        "ref": {
                            "kind": "book",
                            "id": "book:1",
                            "referenceKind": "book",
                            "referenceId": "book:1",
                        },
                        "evidenceRefs": [
                            {
                                "kind": "event",
                                "id": "7",
                                "referenceKind": "event",
                                "referenceId": "7",
                            }
                        ],
                    }
                ]
            }
        if kind == "groups":
            return {
                "items": [
                    {
                        "title": "Agent Runtime",
                        "note": "Pi RPC 和 Session",
                        "tags": ["Pi"],
                        "event_count": 4,
                        "updated_at_ms": 19,
                    }
                ]
            }
        if kind == "tags":
            return {
                "items": [
                    {
                        "tag": "Pi",
                        "description": "Pi 运行时",
                        "item_count": 3,
                        "updated_at_ms": 18,
                    }
                ]
            }
        if kind == "evidence":
            if request.status != "remember":
                return {"items": []}
            return {
                "items": [
                    {
                        "id": "memory-source:7",
                        "type": "user_final",
                        "transportSource": "rime",
                        "source": {"kind": "input_event", "id": "7"},
                        "ref": {
                            "kind": "evidence",
                            "id": "memory-source:7",
                            "referenceKind": "evidence",
                            "referenceId": "memory-source:7",
                        },
                        "evidenceRefs": [
                            {
                                "kind": "event",
                                "id": "7",
                                "referenceKind": "event",
                                "referenceId": "7",
                            }
                        ],
                        "text": "把普通生成和深度检索分开",
                        "app": "Codex",
                        "project": "wisdom-weasel-rag-ime",
                        "ownerKind": "user",
                        "ownerId": "default",
                        "disposition": "remember",
                        "createdAtMs": 30,
                    },
                    {
                        "id": "memory-source:noise",
                        "type": "voice_final",
                        "source": "voice_streaming_asr",
                        "text": "嗯嗯那个这个",
                        "app": "Voice",
                        "project": "wisdom-weasel-rag-ime",
                        "ownerKind": "user",
                        "ownerId": "default",
                        "disposition": "not_for_memory",
                        "createdAtMs": 31,
                    },
                ]
            }
        raise AssertionError(kind)


class _Core:
    def list_memory_events(self, *, project, query, limit):
        return {
            "items": [
                {
                    "eventId": 7,
                    "createdAtMs": 30,
                    "source": "rime",
                    "text": "把普通生成和深度检索分开",
                    "app": "Codex",
                    "project": project,
                    "tags": ["Agent"],
                }
            ][:limit]
        }

    def retrieve_memories(self, *, current_input, project, top_k):
        return [
            SimpleNamespace(
                memory_id="stable:1",
                text="Pi 只负责 Agent Loop",
                source_ref="event:7",
                score=0.91,
                reason="hybrid retrieval",
                evidence_preview="输入法快速链路不经过 Pi",
                project=project,
                tags=("Pi",),
                source_event_id="7",
                created_at_ms=30,
            )
        ][:top_k]

    def suggestion_cache_stats(self):
        return {"hits": 3, "misses": 1}


class _KnowledgeClient:
    def __init__(self):
        self.calls = []

    def list_bases(self, payload):
        self.calls.append(("list_bases", dict(payload)))
        return {
            "items": [
                {
                    "kbId": "kb:project-docs",
                    "name": "项目资料",
                    "agentEnabled": True,
                    "indexedDocumentCount": 2,
                }
            ]
        }

    def search(self, payload):
        self.calls.append(("search", dict(payload)))
        return {
            "schemaVersion": "rag-ime.document-knowledge-search.v1",
            "kbId": payload["kbId"],
            "query": payload["query"],
            "items": [
                {
                    "chunkId": "chunk:1",
                    "fileId": "file:1",
                    "fileName": "architecture.md",
                    "content": "Pi 只负责 Agent Loop；输入法热路径保持独立。",
                    "sourcePath": "/private/project/architecture.md",
                    "citation": {"page": None, "startLine": 41, "endLine": 42},
                }
            ],
        }

    def find(self, payload):
        self.calls.append(("find", dict(payload)))
        return {"items": [{"line": 41, "content": "输入法热路径保持独立。"}]}

    def open(self, payload):
        self.calls.append(("open", dict(payload)))
        return {"fileId": payload["fileId"], "startLine": 41, "content": "引用窗口"}

    def status(self, payload):
        self.calls.append(("status", dict(payload)))
        return {"available": True, "state": "ready", "workerUrl": "http://127.0.0.1:8769"}


class _Facade:
    def __init__(self):
        self.memory_run_status = "draft"
        self.memory_prepare_no_run = False
        self.memory_prepare_pending_count = 0
        self.memory_prepare_batch_count = 1
        self.memory_prepare_drain_limited = False
        self.memory_maintenance_requests = []
        self.memory_run_owner = ("user", "default")
        self.settings_revision = 1
        self.settings_payload = {
            "interaction": {"postCommit": {"enabled": True, "idleTriggerMs": 420}},
            "display": {"fadeAnimation": True},
            "activeRag": {"enabled": True, "localOnlyDefault": True},
            "pinyin": {"fuzzyProfile": "sichuan-mild", "pairs": {"nL": False}},
            "privacy": {"allowRemoteModelForActiveRag": False},
            "providers": {"knowledge": {"apiKey": "must-not-leak"}},
        }
        self.lexicon_applied = False

    def settings(self):
        return {
            "settings": self.settings_payload,
            "settingsHash": f"settings:{self.settings_revision}",
            "runtimeConfig": {"profile": "default"},
        }

    def settings_update(self, payload):
        changed = []
        for key, value in payload.items():
            if key == "updatedBy":
                continue
            cursor = self.settings_payload
            parts = key.split(".")
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            if cursor.get(parts[-1]) != value:
                cursor[parts[-1]] = value
                changed.append(key)
        self.settings_revision += 1
        return {
            "ok": True,
            "auditId": 51,
            "changedKeys": sorted(changed),
            "settingsRevision": f"settings:{self.settings_revision}",
            "runtimeRevision": self.settings_revision,
        }

    def frontend_capabilities(self):
        return {"frontend": "squirrel", "postCommit": True}

    def input_source_status(self):
        return {"ok": True, "selected": True}

    def candidate_explain(self, payload):
        return {"ok": True, "queryPreview": payload["query"], "candidates": [{"text": "继续"}]}

    def rime_lexicon_review(self, payload):
        entries = [] if self.lexicon_applied else [
            {
                "text": "派会话",
                "pinyin": "pai hui hua",
                "reviewKey": "派会话\tpai hui hua",
                "selected": True,
            }
        ]
        return {
            "ok": True,
            "reviewToken": "must-not-reach-pi",
            "confirmText": "must-not-reach-pi",
            "entries": entries,
        }

    def rime_lexicon_apply(self, payload):
        if payload["reviewToken"] != "must-not-reach-pi":
            return {"ok": False, "reason": "review_token_stale"}
        self.lexicon_applied = True
        return {
            "ok": True,
            "applied": True,
            "entryCount": len(payload["selectedKeys"]),
            "rollbackId": "lexicon:1",
            "requiresRedeploy": True,
        }

    def rime_lexicon_rollback(self, payload):
        if payload["rollbackId"] != "lexicon:1":
            return {"ok": False, "reason": "rollback_manifest_missing"}
        self.lexicon_applied = False
        return {"ok": True, "rolledBack": True, "rollbackId": "lexicon:1", "requiresRedeploy": True}

    def memory_optimizer_trace(self, payload):
        return {"ok": True, "traceId": payload["traceId"], "decision": "keep"}

    def agent_memory_maintenance_status(self, payload):
        self.memory_maintenance_requests.append(("status", dict(payload)))
        return {
            "schemaVersion": "rag-ime.agent-memory-maintenance-status.v1",
            "ok": True,
            "policy": "review",
            "autoApply": False,
            "compileState": {"pendingEventCount": 7},
            "pendingDraftCount": 1,
            "runs": [{"runId": "memory_book_draft", "status": "draft", "diffCount": 3}],
            "limit": payload["limit"],
        }

    def agent_memory_maintenance_prepare(self, payload):
        self.memory_maintenance_requests.append(("prepare", dict(payload)))
        if self.memory_prepare_no_run:
            return {
                "ok": True,
                "storedDraft": False,
                "reusedDraft": False,
                "source": {
                    "ownerKind": payload["ownerKind"],
                    "ownerId": payload["ownerId"],
                    "pendingSourceCount": self.memory_prepare_pending_count,
                    "batchCount": self.memory_prepare_batch_count,
                    "drainLimited": self.memory_prepare_drain_limited,
                },
                "validation": {"ok": True, "errors": []},
                "storedRun": {},
                "curation": {
                    "results": [
                        {
                            "ownerKind": payload["ownerKind"],
                            "ownerId": payload["ownerId"],
                            "skipped": True,
                            "reason": "no_sources",
                        }
                    ]
                },
            }
        self.memory_run_owner = (payload["ownerKind"], payload["ownerId"])
        return {
            "ok": True,
            "storedDraft": True,
            "reusedDraft": False,
            "source": {
                "bundleHash": "sha256:bundle",
                "eventCount": 7,
                "pendingSourceCount": self.memory_prepare_pending_count,
                "batchCount": self.memory_prepare_batch_count,
                "drainLimited": self.memory_prepare_drain_limited,
            },
            "validation": {"ok": True, "errors": []},
            "storedRun": {
                "runId": "memory_book_draft",
                "status": "draft",
                "ownerKind": payload["ownerKind"],
                "ownerId": payload["ownerId"],
            },
            "instruction": payload["instruction"],
        }

    def agent_memory_maintenance_run(self, payload):
        status = self.memory_run_status
        diff_count = 0 if status == "empty" else 3
        return {
            "ok": True,
            "revisionHash": f"sha256:{status}",
            "stale": False,
            "canApply": status == "draft",
            "canRollback": status == "applied",
            "run": {
                "runId": payload["runId"],
                "status": status,
                "summary": "Pi 记忆整理草案",
                "ownerKind": self.memory_run_owner[0],
                "ownerId": self.memory_run_owner[1],
                "runKind": "manual_curation",
                "bundleHash": "sha256:bundle",
                "sourceCursor": {"fromEventId": 10, "toEventId": 16},
                "diffCount": diff_count,
                "pendingDiffCount": diff_count if status == "draft" else 0,
                "appliedDiffCount": diff_count if status == "applied" else 0,
                "operationCounts": (
                    {
                        "upsert_memory_book": 1,
                        "upsert_memory_atom": 2,
                    }
                    if diff_count
                    else {}
                ),
                "changes": [
                    {
                        "diffId": 1,
                        "operation": "upsert_memory_book",
                        "operationLabel": "更新工具书",
                        "status": "pending" if status == "draft" else status,
                        "selected": True,
                        "title": "Pi 控制中心",
                        "detail": "记录审批和记忆整理边界",
                        "sourceCount": 3,
                    }
                ],
            },
        }

    def knowledge_workbench_database_apply(self, payload):
        self.memory_run_status = "applied"
        return {"ok": True, "action": "apply", "run": {"runId": payload["runId"]}}

    def knowledge_workbench_database_rollback(self, payload):
        self.memory_run_status = "rolled_back"
        return {"ok": True, "action": "rollback", "run": {"runId": payload["runId"]}}

    def knowledge_workbench_route_status(self):
        return {"ok": True, "deepseekReady": False, "skipReason": "credentials_missing"}

    def models_status(self):
        return {
            "ok": True,
            "predictor": {"ok": True},
            "activeRagRoute": {"remoteReady": False, "skipReason": "credentials_missing"},
        }

    def model_probe(self, payload):
        return {"ok": True, "dryRun": True, "predictor": {"ok": True}}

    def management_audit(self, payload):
        return {"ok": True, "items": [{"action": "settings_update", "apiKey": "must-not-leak"}]}


class ControlToolGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-tools-")
        self.previous_support_dir = os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        os.environ["RAG_IME_APP_SUPPORT_DIR"] = str(Path(self.tmp.name) / "support")
        self.store = AgentSessionStore(Path(self.tmp.name) / "rag-ime.sqlite")
        self.store.initialize()
        self.session = self.store.create(title="tool test", created_at_ms=1)
        self.management = _Management()
        self.facade = _Facade()
        self.knowledge = _KnowledgeClient()
        self.gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            knowledge_client=self.knowledge,
        )

    def tearDown(self) -> None:
        if self.previous_support_dir is None:
            os.environ.pop("RAG_IME_APP_SUPPORT_DIR", None)
        else:
            os.environ["RAG_IME_APP_SUPPORT_DIR"] = self.previous_support_dir
        self.tmp.cleanup()

    def test_catalog_exposes_named_books_groups_and_tags_without_database_access(self) -> None:
        response = self.gateway.execute(self._call("catalog", query="Pi"))
        result = response["result"]

        self.assertEqual(result["counts"], {"books": 1, "groups": 1, "tags": 1})
        self.assertIn("1 本工具书", result["summary"])
        self.assertEqual([item["kind"] for item in result["items"]], ["book", "group", "tag"])
        self.assertEqual(result["items"][0]["ref"]["referenceKind"], "book")
        self.assertEqual(result["items"][0]["ref"]["type"], "book")
        self.assertEqual(result["items"][0]["evidenceRefs"][0]["kind"], "event")
        self.assertNotIn("sourceEventIds", str(response))

    def test_read_and_recent_return_bounded_evidence(self) -> None:
        read = self.gateway.execute(self._call("read", bookId="book:1"))["result"]
        recent = self.gateway.execute(self._call("recent", query="深度检索", limit=8))["result"]

        self.assertEqual(read["book"]["title"], "输入法项目")
        self.assertEqual(read["book"]["memories"][0]["text"], "普通生成不经过 Pi")
        self.assertEqual(read["book"]["ref"]["referenceKind"], "book")
        self.assertEqual(read["book"]["memories"][0]["ref"]["referenceKind"], "atom")
        self.assertEqual(read["book"]["evidenceRefs"][0]["referenceKind"], "event")
        self.assertEqual(recent["count"], 1)
        self.assertEqual(recent["items"][0]["text"], "把普通生成和深度检索分开")
        self.assertEqual(recent["items"][0]["disposition"], "remember")
        self.assertEqual(recent["items"][0]["source"], "rime")
        self.assertEqual(recent["items"][0]["sourceRef"]["kind"], "input_event")
        self.assertEqual(recent["items"][0]["ref"]["referenceKind"], "evidence")
        self.assertEqual(recent["items"][0]["evidenceRefs"][0]["referenceKind"], "event")
        self.assertNotIn("嗯嗯那个这个", str(recent))
        evidence_requests = [
            request
            for kind, request in self.management.memory_requests
            if kind == "evidence"
        ]
        self.assertEqual(
            [request.status for request in evidence_requests],
            ["remember", "consolidated"],
        )
        self.assertTrue(all(request.visible_owners for request in evidence_requests))

    def test_memory_read_compatibility_normalizes_missing_operation_without_enabling_writes(self) -> None:
        recent = self.gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session["id"],
                "tool": "memory",
                "toolCallId": "tool:legacy-recent",
                "args": {
                    "query": "RAG IME 昨天进展",
                    "scope": "recent",
                },
            }
        )["result"]

        self.assertEqual(recent["count"], 1)
        self.assertEqual(recent["items"][0]["text"], "把普通生成和深度检索分开")
        with self.assertRaisesRegex(ValueError, "unsupported memory operation"):
            self.gateway.execute(
                {
                    "schemaVersion": "rag-ime.agent-tool-call.v1",
                    "sessionId": self.session["id"],
                    "tool": "memory",
                    "toolCallId": "tool:legacy-write",
                    "args": {
                        "text": "不能凭缺失 op 猜写操作",
                        "scope": "global",
                    },
                }
            )

    def test_memory_tools_include_the_active_room_owner_in_visibility(self) -> None:
        participant_calls = []

        class _Rooms:
            def participant_for_session(self, session_id):
                participant_calls.append(session_id)
                return {"roomId": "room:architecture"}

        class _Collaboration:
            rooms = _Rooms()

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            collaboration=_Collaboration(),
        )

        gateway.execute(self._call("recent", limit=3))

        evidence_requests = [
            request
            for kind, request in self.management.memory_requests
            if kind == "evidence"
        ]
        self.assertEqual(participant_calls, [self.session["id"]])
        self.assertEqual(len(evidence_requests), 2)
        self.assertTrue(
            all(
                ("room", "room:architecture") in request.visible_owners
                for request in evidence_requests
            )
        )
        self.assertTrue(
            all(
                ("session", self.session["id"]) in request.visible_owners
                for request in evidence_requests
            )
        )

    def test_memory_maintenance_status_exposes_review_only_drafts(self) -> None:
        result = self.gateway.execute(self._call("maintenance_status", limit=8))["result"]

        self.assertEqual(result["summary"], "有 7 条来源待整理、1 份草案待审阅")
        self.assertEqual(result["maintenance"]["policy"], "review")
        self.assertFalse(result["maintenance"]["autoApply"])
        self.assertEqual(result["maintenance"]["runs"][0]["status"], "draft")
        request = self.facade.memory_maintenance_requests[-1][1]
        self.assertEqual(
            (request["ownerKind"], request["ownerId"]),
            ("user", "default"),
        )

    def test_runtime_memory_tool_discloses_operation_specific_schema(self) -> None:
        manifests = self.gateway.runtime_manifests(self.session)
        memory = next(item for item in manifests if item["name"] == "memory")
        parameters = memory["parameters"]
        branches = parameters["oneOf"]
        by_operation = {
            branch["properties"]["op"]["const"]: branch
            for branch in branches
            if "op" in branch.get("properties", {})
        }

        self.assertIn("curation_prepare", by_operation)
        self.assertIn("capture", by_operation)
        self.assertEqual(
            memory["runtimeProjections"],
            [{"name": "memory_capture", "operation": "capture"}],
        )
        self.assertEqual(
            by_operation["capture"]["required"],
            [
                "op",
                "kind",
                "claim",
                "captureScope",
                "basis",
                "futureUse",
            ],
        )
        self.assertEqual(
            parameters["properties"]["basis"]["enum"],
            [
                "explicit_user_request",
                "explicit_user_statement",
                "user_correction",
                "repeated_user_signal",
                "verified_outcome",
            ],
        )
        self.assertEqual(parameters["properties"]["futureUse"]["maxLength"], 300)
        self.assertIn(
            "至少两条独立用户表达",
            parameters["properties"]["basis"]["description"],
        )
        self.assertIn(
            "已应用工具回执",
            parameters["properties"]["basis"]["description"],
        )
        self.assertIn(
            "若只影响当前任务或当前会话",
            parameters["properties"]["futureUse"]["description"],
        )
        self.assertIn("一轮最多三条", parameters["description"])
        self.assertIn("Room 私有过程", parameters["description"])
        self.assertIn("失败不循环重试", parameters["description"])
        self.assertEqual(
            by_operation["curation_prepare"]["required"],
            ["op", "trigger"],
        )
        self.assertEqual(
            parameters["properties"]["trigger"]["enum"],
            ["task_completion", "explicit_request", "idle_batch"],
        )
        self.assertEqual(
            parameters["properties"]["scope"]["enum"],
            [
                "incremental",
                "global",
                "recent",
                "current",
                "historical",
                "change",
            ],
        )
        compatibility = next(
            branch
            for branch in branches
            if "op" not in branch.get("properties", {})
        )
        self.assertEqual(compatibility["required"], ["query"])
        self.assertEqual(compatibility["not"], {"required": ["op"]})
        self.assertEqual(
            compatibility["properties"]["scope"]["enum"],
            ["recent", "current", "historical", "change"],
        )
        self.assertNotIn("。。", memory["description"])

        self.assertEqual(
            parameters["properties"]["policy"]["enum"],
            ["conservative"],
        )
        self.assertEqual(
            by_operation["maintenance_review"]["required"],
            ["op", "runId"],
        )
        self.assertEqual(
            by_operation["remember_preview"]["required"],
            ["op", "text"],
        )

        self.assertEqual(
            by_operation["correct_preview"]["required"],
            ["op", "targetId", "text"],
        )
        self.assertEqual(
            by_operation["forget_preview"]["required"],
            ["op", "targetId", "reason"],
        )
        self.assertEqual(
            by_operation["remember_apply"]["required"],
            ["op", "proposalId"],
        )
        self.assertCountEqual(
            by_operation["get"]["anyOf"],
            [{"required": ["targetId"]}, {"required": ["draftId"]}],
        )
        for field in (
            "targetId",
            "text",
            "reason",
            "memoryKind",
            "evidenceIds",
            "claimKey",
            "idempotencyKey",
            "proposalId",
            "draftId",
            "mode",
        ):
            self.assertIn(field, parameters["properties"])
        self.assertEqual(memory["description"], "个人上下文记忆")
        self.assertIn("工具回执", memory["notFor"][0])
        self.assertNotIn("changes", str(parameters))

        role_book = next(
            item for item in manifests if item["name"] == "agent_role_book"
        )
        self.assertIn("随 Session 固定版本注入系统提示词", role_book["does"])
        self.assertIn("待审草案", role_book["output"])

    def test_overview_tool_describes_the_agent_product_before_input_sources(self) -> None:
        manifests = self.gateway.runtime_manifests(self.session)
        overview = next(item for item in manifests if item["name"] == "overview")

        self.assertEqual(overview["description"], "控制中心概览")
        self.assertNotIn("查看输入法、模型", overview["does"])
        self.assertIn("Agent、模型、记忆、输入", overview["output"])

    def test_workspace_shell_card_routes_edits_and_room_waits_to_their_owners(
        self,
    ) -> None:
        coordinator = self.store.create(
            title="workspace tool card",
            mode="coordinator",
            workspace_roots=[self.tmp.name],
            created_at_ms=2,
        )
        manifests = self.gateway.runtime_manifests(coordinator)
        shell = next(item for item in manifests if item["name"] == "workspace_shell")

        self.assertTrue(any("workspace_patch" in value for value in shell["notFor"]))
        self.assertTrue(any("apply_patch" in value for value in shell["notFor"]))
        self.assertTrue(
            any("sleep" in value and "Room" in value for value in shell["notFor"])
        )

    def test_workspace_root_path_accepts_an_omitted_or_empty_value(self) -> None:
        coordinator = self.store.create(
            title="workspace root schema",
            mode="coordinator",
            workspace_roots=[self.tmp.name],
            created_at_ms=2,
        )
        manifests = {
            item["name"]: item
            for item in self.gateway.runtime_manifests(coordinator)
        }

        for name in ("workspace_list", "workspace_search"):
            path_schema = manifests[name]["parameters"]["properties"]["path"]
            self.assertNotIn("minLength", path_schema)
            self.assertIn("空字符串", path_schema["description"])

    def test_workspace_gateway_targets_are_hidden_behind_native_runtime_tools(
        self,
    ) -> None:
        coordinator = self.store.create(
            title="native workspace projections",
            mode="coordinator",
            workspace_roots=[self.tmp.name],
            created_at_ms=2,
        )
        manifests = {
            item["name"]: item
            for item in self.gateway.runtime_manifests(coordinator)
        }

        expected = {
            "workspace_list": [{"name": "ls", "operation": "list"}],
            "workspace_read": [{"name": "read", "operation": "read"}],
            "workspace_search": [
                {"name": "grep", "operation": "search"},
                {"name": "find", "operation": "search"},
            ],
            "workspace_edit": [{"name": "edit", "operation": "apply"}],
            "workspace_write": [{"name": "write", "operation": "apply"}],
            "workspace_shell": [{"name": "bash", "operation": "run"}],
        }
        for target, projections in expected.items():
            with self.subTest(target=target):
                self.assertIs(manifests[target]["modelVisible"], False)
                self.assertEqual(
                    manifests[target]["runtimeProjections"],
                    projections,
                )
        for target in ("workspace_edit", "workspace_write"):
            with self.subTest(contract_target=target):
                validate_contract(
                    {
                        "schemaVersion": "rag-ime.agent-tool-call.v1",
                        "sessionId": coordinator["id"],
                        "tool": target,
                        "toolCallId": f"tool:{target}",
                        "args": {},
                    },
                    "agent-tool-call.v1.json",
                )
                validate_contract(
                    {
                        "schemaVersion": "rag-ime.agent-tool-result.v1",
                        "ok": True,
                        "tool": target,
                        "operation": "apply",
                        "result": {},
                    },
                    "agent-tool-result.v1.json",
                )
        self.assertIs(manifests["workspace_patch"]["modelVisible"], False)
        self.assertNotIn("runtimeProjections", manifests["workspace_patch"])
        self.assertNotIn("modelVisible", manifests["workspace_lsp"])
        self.assertNotIn("runtimeProjections", manifests["workspace_lsp"])
        for operation in (
            "status",
            "symbols",
            "hover",
            "definition",
            "references",
            "diagnostics",
            "rename",
            "code_action_apply",
        ):
            validate_contract(
                {
                    "schemaVersion": "rag-ime.agent-tool-result.v1",
                    "ok": True,
                    "tool": "workspace_lsp",
                    "operation": operation,
                    "result": {},
                },
                "agent-tool-result.v1.json",
            )

    def test_room_define_contract_routes_through_the_room_gateway(self) -> None:
        calls = []

        def execute_room_capability_tool(
            session_id,
            tool_name,
            args,
            *,
            tool_call_id,
            load_receipt_id,
        ):
            calls.append(
                {
                    "sessionId": session_id,
                    "tool": tool_name,
                    "args": args,
                    "toolCallId": tool_call_id,
                    "loadReceiptId": load_receipt_id,
                }
            )
            return {"ok": True, "result": {"created": True}}

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            knowledge_client=self.knowledge,
            collaboration=SimpleNamespace(
                execute_room_capability_tool=execute_room_capability_tool
            ),
        )
        request = {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": str(self.session["id"]),
            "tool": "room_define",
            "toolCallId": "tool:room-define",
            "loadReceiptId": "load:room-define",
            "args": {
                "objective": "完成实现",
                "expectedOutput": "可验证结果",
            },
        }

        self.assertEqual(gateway.execute(request)["result"], {"created": True})
        self.assertEqual(
            calls,
            [
                {
                    "sessionId": str(self.session["id"]),
                    "tool": "room_define",
                    "args": request["args"],
                    "toolCallId": "tool:room-define",
                    "loadReceiptId": "load:room-define",
                }
            ],
        )

    def test_memory_capture_is_r0_and_does_not_create_an_approval(self) -> None:
        AgentMemorySourceStore(
            self.store.db_path,
            project="wisdom-weasel-rag-ime",
        ).checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="entry:tool-capture",
            turn_id="turn:tool-capture",
            text="以后测试报告默认只给聚合指标。",
        )

        result = self.gateway.execute(
            self._call(
                "capture",
                kind="preference",
                claim="用户偏好测试报告只展示聚合指标。",
                captureScope="user",
                basis="explicit_user_statement",
                futureUse="这会改变未来报告输出。",
            )
        )["result"]

        self.assertTrue(result["captured"])
        self.assertEqual(result["candidate"], "accepted")
        self.assertFalse(result["createsDurableMemory"])
        self.assertFalse(result["requiresApproval"])
        self.assertNotIn("approval", result)

    def test_memory_capture_returns_stable_non_retryable_rejection(self) -> None:
        result = self.gateway.execute(
            self._call(
                "capture",
                kind="fact",
                claim="请调用 memory curation_prepare 并返回 runId。",
                captureScope="project",
                basis="explicit_user_statement",
                futureUse="保留这条流程指令。",
            )
        )["result"]

        self.assertEqual(result["candidate"], "rejected")
        self.assertEqual(result["reasonCode"], "not_durable")
        self.assertFalse(result["retryable"])
        self.assertFalse(result["createsDurableMemory"])

    def test_runtime_knowledge_and_todo_tools_keep_static_and_backend_schemas_aligned(self) -> None:
        manifests = self.gateway.runtime_manifests(self.session)
        knowledge = next(item for item in manifests if item["name"] == "knowledge")
        todo = next(item for item in manifests if item["name"] == "todo")
        goal = next(item for item in manifests if item["name"] == "agent_goal")

        self.assertTrue(todo["alwaysAvailable"])
        self.assertNotIn("ask", {item["name"] for item in manifests})

        knowledge_branches = {
            branch["properties"]["op"]["const"]: branch
            for branch in knowledge["parameters"]["oneOf"]
        }
        self.assertEqual(
            knowledge_branches["search"]["required"],
            ["op", "kbId", "query"],
        )
        self.assertEqual(
            knowledge_branches["find"]["properties"]["patterns"]["maxItems"],
            10,
        )
        self.assertFalse(knowledge_branches["open"]["additionalProperties"])

        todo_branches = {
            branch["properties"]["op"]["const"]: branch
            for branch in todo["parameters"]["oneOf"]
        }
        self.assertCountEqual(
            todo_branches,
            {
                "init",
                "start",
                "done",
                "drop",
                "block",
                "unblock",
                "append",
                "view",
                "rm",
            },
        )
        self.assertCountEqual(
            todo_branches["init"]["oneOf"],
            [{"required": ["list"]}, {"required": ["items"]}],
        )
        self.assertEqual(todo_branches["start"]["required"], ["op", "task"])
        self.assertCountEqual(
            todo_branches["block"]["oneOf"],
            [{"required": ["task"]}, {"required": ["phase"]}],
        )
        self.assertEqual(
            todo["parameters"]["properties"]["reason"]["maxLength"],
            500,
        )
        self.assertEqual(
            todo_branches["append"]["required"],
            ["op", "phase", "items"],
        )
        self.assertFalse(todo_branches["append"]["additionalProperties"])

        goal_branches = {
            branch["properties"]["op"]["const"]: branch
            for branch in goal["parameters"]["oneOf"]
        }
        self.assertEqual(
            goal_branches["confirm_setup"]["required"],
            ["op", "confirmed", "objective"],
        )
        self.assertEqual(
            goal_branches["complete"]["required"],
            ["op", "summary", "evidence"],
        )
        self.assertEqual(
            goal_branches["complete"]["properties"]["evidence"]["minItems"],
            1,
        )

    def test_memory_list_exposes_app_as_provenance_not_a_semantic_tag(self) -> None:
        result = self.gateway.execute(self._call("list", kind="apps", limit=8))["result"]

        self.assertEqual(result["kind"], "apps")
        self.assertEqual(result["items"][0]["id"], "com.openai.codex")
        self.assertEqual(result["items"][0]["eventCount"], 12)

    def test_unknown_operations_and_archived_sessions_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.gateway.execute(self._call("write"))
        with self.assertRaisesRegex(ValueError, "unsupported memory list kind"):
            self.gateway.execute(self._call("list", kind="negative"))
        self.store.archive(str(self.session["id"]))
        with self.assertRaisesRegex(ValueError, "archived"):
            self.gateway.execute(self._call("catalog"))

    def test_explicit_tool_allowlist_filters_manifests_and_execution(self) -> None:
        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="assistant",
            tool_profile_version="control-center-v1",
            allowed_tools=["overview"],
        )
        manifests = self.gateway.manifests(session_id=str(self.session["id"]))
        overview = next(item for item in manifests["items"] if item["id"] == "overview")
        memory = next(item for item in manifests["items"] if item["id"] == "memory")

        self.assertTrue(overview["enabled"])
        self.assertFalse(memory["enabled"])
        self.assertEqual(manifests["sessionPolicy"]["allowedTools"], ["overview"])
        self.gateway.execute(self._tool_call("overview", "status"))
        with self.assertRaisesRegex(ValueError, "tool profile"):
            self.gateway.execute(self._call("catalog"))

    def test_public_manifests_expose_one_canonical_native_coding_tool_each(self) -> None:
        manifests = self.gateway.manifests()["items"]
        self.assertEqual(
            [manifest["id"] for manifest in manifests],
            [
                "overview",
                "input",
                "voice",
                "planning",
                "agent_schedule",
                "memory",
                "agent_role_book",
                "knowledge",
                "models",
                "runtime",
                "configuration",
                "agents",
                "browser",
                "todo",
                "agent_goal",
                "plugins",
                "desktop_semantic",
                "read",
                "edit",
                "write",
                "bash",
                "ask",
            ],
        )
        public_ids = [str(manifest["id"]) for manifest in manifests]
        self.assertFalse(any(tool_id.startswith("workspace_") for tool_id in public_ids))
        self.assertNotIn("write_file", public_ids)
        for tool_id in ("read", "edit", "write", "bash"):
            with self.subTest(tool_id=tool_id):
                self.assertEqual(public_ids.count(tool_id), 1)
                native = next(item for item in manifests if item["id"] == tool_id)
                self.assertEqual(native["canonicalId"], f"tool:{tool_id}")
                self.assertEqual(native["runtimeOwner"], "pi_host")
        planning = next(manifest for manifest in manifests if manifest["id"] == "planning")
        self.assertEqual(planning["riskLevel"], "R1")
        self.assertEqual(
            planning["operationRisks"],
            {"dashboard": "R0", "task_action": "R1", "undo_task_event": "R1"},
        )
        memory = next(manifest for manifest in manifests if manifest["id"] == "memory")
        self.assertEqual(memory["riskLevel"], "R1")
        self.assertEqual(memory["operationRisks"]["maintenance_preview"], "R0")
        self.assertEqual(memory["operationRisks"]["maintenance_apply"], "R1")
        self.assertEqual(memory["operationRisks"]["maintenance_rollback"], "R1")
        knowledge = next(manifest for manifest in manifests if manifest["id"] == "knowledge")
        self.assertEqual(
            knowledge["operations"],
            ["list_bases", "search", "find", "open", "status"],
        )
        input_tool = next(manifest for manifest in manifests if manifest["id"] == "input")
        self.assertEqual(input_tool["riskLevel"], "R1")
        self.assertEqual(input_tool["operationRisks"]["preview_settings"], "R0")
        self.assertEqual(input_tool["operationRisks"]["apply_settings"], "R1")
        self.assertEqual(input_tool["operationRisks"]["lexicon_apply"], "R1")
        voice_tool = next(manifest for manifest in manifests if manifest["id"] == "voice")
        self.assertEqual(voice_tool["riskLevel"], "R1")
        self.assertEqual(voice_tool["operationRisks"]["provider_preview"], "R0")
        self.assertEqual(voice_tool["operationRisks"]["provider_apply"], "R1")
        self.assertEqual(voice_tool["operationRisks"]["provider_rollback"], "R1")
        runtime_tool = next(manifest for manifest in manifests if manifest["id"] == "runtime")
        self.assertEqual(runtime_tool["riskLevel"], "R2")
        self.assertEqual(runtime_tool["operationRisks"]["diagnose"], "R0")
        self.assertEqual(runtime_tool["operationRisks"]["pause_ai"], "R1")
        self.assertEqual(runtime_tool["operationRisks"]["restart_sidecar"], "R2")
        self.assertEqual(runtime_tool["operationRisks"]["restart_predictor"], "R2")
        model_tool = next(manifest for manifest in manifests if manifest["id"] == "models")
        self.assertEqual(model_tool["riskLevel"], "R1")
        self.assertEqual(model_tool["operationRisks"]["profiles"], "R0")
        self.assertEqual(model_tool["operationRisks"]["profile_apply"], "R1")
        self.assertEqual(model_tool["operationRisks"]["profile_rollback"], "R1")
        configuration_tool = next(
            manifest for manifest in manifests if manifest["id"] == "configuration"
        )
        self.assertEqual(configuration_tool["riskLevel"], "R3")
        self.assertEqual(configuration_tool["operationRisks"]["export_preview"], "R0")
        self.assertEqual(configuration_tool["operationRisks"]["export"], "R1")
        self.assertEqual(configuration_tool["operationRisks"]["restore_preview"], "R0")
        self.assertEqual(configuration_tool["operationRisks"]["restore_apply"], "R3")
        browser_tool = next(manifest for manifest in manifests if manifest["id"] == "browser")
        self.assertEqual(browser_tool["riskLevel"], "R1")
        self.assertEqual(browser_tool["operationRisks"]["snapshot"], "R0")
        self.assertEqual(browser_tool["operationRisks"]["screenshot"], "R0")
        self.assertEqual(browser_tool["operationRisks"]["navigate"], "R1")
        self.assertEqual(browser_tool["operationRisks"]["type"], "R1")
        bash = next(manifest for manifest in manifests if manifest["id"] == "bash")
        self.assertEqual(bash["sessionModes"], ["coordinator"])
        self.assertEqual(bash["operationRisks"], {"run": "R2"})
        desktop = next(manifest for manifest in manifests if manifest["id"] == "desktop_semantic")
        self.assertEqual(desktop["riskLevel"], "R2")
        self.assertEqual(
            desktop["operationRisks"],
            {"status": "R0", "list": "R0", "inspect": "R0", "act": "R2"},
        )
        self.assertTrue(
            all(
                manifest["riskLevel"] == "R0"
                for manifest in manifests
                if manifest["id"] not in {
                    "input",
                    "voice",
                    "planning",
                    "agent_schedule",
                    "memory",
                    "models",
                    "runtime",
                    "configuration",
                    "browser",
                    "desktop_semantic",
                    "edit",
                    "write",
                    "bash",
                    "work_documents",
                    "workspace_patch",
                    "workspace_lsp",
                    "workspace_edit",
                    "workspace_write",
                    "workspace_shell",
                    "workspace_job",
                }
            )
        )
        assistant_call = self._tool_call("workspace_list", "list")
        with self.assertRaisesRegex(ValueError, "session mode"):
            self.gateway.execute(assistant_call)

    def test_runtime_workspace_job_is_discoverable_after_progressive_tool_load(self) -> None:
        coordinator = self.store.create(
            title="workspace job disclosure",
            mode="coordinator",
            workspace_roots=[self.tmp.name],
            created_at_ms=2,
        )
        background_jobs = AgentBackgroundJobService(
            Path(self.tmp.name) / "rag-ime.sqlite",
            events=lambda *_args, **_kwargs: None,
        )
        background_jobs.initialize()
        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            knowledge_client=self.knowledge,
            workspace_harness=background_jobs.workspace_harness,
            background_jobs=background_jobs,
        )
        try:
            manifests = {
                item["name"]: item
                for item in gateway.runtime_manifests(coordinator)
            }
            workspace_job = manifests["workspace_job"]
            operations = {
                branch["properties"]["op"]["const"]
                for branch in workspace_job["parameters"]["oneOf"]
            }

            self.assertNotIn("modelVisible", workspace_job)
            self.assertEqual(
                operations,
                {"start", "list", "status", "logs", "cancel"},
            )
            self.assertIs(manifests["workspace_read"]["modelVisible"], False)
        finally:
            background_jobs.close()

    def test_agent_goal_lifecycle_is_model_manageable_and_audited(self) -> None:
        initial = self.gateway.execute(
            self._tool_call("agent_goal", "list")
        )["result"]
        self.assertFalse(initial["goal"]["configured"])

        configured = self.gateway.execute(
            self._tool_call(
                "agent_goal",
                "confirm_setup",
                confirmed=True,
                objective="验证长期目标工具",
                successCriteria="状态与完成证据写入同一权威工作流",
                evidenceExpectations=["工具回执"],
                tokenBudget=10_000,
            )
        )["result"]
        self.assertEqual(configured["goal"]["status"], "active")
        self.assertEqual(configured["goal"]["objective"], "验证长期目标工具")
        self.assertEqual(configured["goal"]["budget"]["tokenLimit"], 10_000)

        completed = self.gateway.execute(
            self._tool_call(
                "agent_goal",
                "complete",
                summary="Goal 工具端到端验证完成",
                evidence=[
                    {
                        "kind": "receipt",
                        "summary": "Gateway 返回持久化完成状态",
                        "reference": "tool:agent-goal:test",
                    }
                ],
            )
        )["result"]
        self.assertEqual(completed["goal"]["status"], "completed")
        self.assertEqual(
            completed["goal"]["completionAudit"]["evidence"][0]["reference"],
            "tool:agent-goal:test",
        )
        self.assertEqual(
            self.store.workflow_state(str(self.session["id"]))["goal"]["status"],
            "completed",
        )

        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="assistant",
            tool_profile_version="subagent-readonly-v1",
            allowed_tools=["agent_goal"],
        )
        self.assertEqual(
            self.gateway.execute(self._tool_call("agent_goal", "list"))["result"]["goal"]["status"],
            "completed",
        )
        with self.assertRaisesRegex(ValueError, "not enabled"):
            self.gateway.execute(
                self._tool_call(
                    "agent_goal",
                    "cancel",
                    reason="只读配置不得改写 Goal",
                )
            )

    def test_todo_is_session_local_and_never_grants_work_authority(self) -> None:
        initialized = self.gateway.execute(
            self._tool_call(
                "todo",
                "init",
                phase="执行",
                items=["验证权限模式"],
            )
        )["result"]

        self.assertEqual(initialized["presentationKind"], "todo")
        self.assertEqual(
            initialized["todo"]["phases"][0]["tasks"],
            [{"content": "验证权限模式", "status": "in_progress"}],
        )
        self.assertEqual(
            self.store.workflow_state(str(self.session["id"]))["actGate"]["reason"],
            "user_execution_request",
        )

        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="assistant",
            tool_profile_version="subagent-readonly-v1",
            allowed_tools=["todo"],
        )
        readable = self.gateway.execute(
            self._tool_call("todo", "view")
        )["result"]
        self.assertEqual(readable["todo"], initialized["todo"])

        started = self.gateway.execute(
            self._tool_call("todo", "start", task="验证权限模式")
        )["result"]
        self.assertEqual(started["todo"]["counts"]["inProgress"], 1)
        completed = self.gateway.execute(
            self._tool_call("todo", "done", task="验证权限模式")
        )["result"]
        self.assertEqual(completed["todo"]["counts"]["completed"], 1)
        workflow = self.store.workflow_state(str(self.session["id"]))
        self.assertTrue(workflow["actGate"]["allowed"])
        self.assertEqual(workflow["actGate"]["reason"], "user_execution_request")
        self.assertEqual(
            workflow["actGate"]["todoRevision"],
            completed["todo"]["revision"],
        )

        other = self.store.create(title="other session", created_at_ms=2)
        other_todo = self.gateway.execute(
            {
                **self._tool_call("todo", "view"),
                "sessionId": other["id"],
            }
        )["result"]
        self.assertEqual(other_todo["todo"]["phases"], [])

    def test_coordinator_workspace_read_and_shell_use_hash_bound_native_approval(self) -> None:
        workspace = Path(self.tmp.name) / "workspace"
        workspace.mkdir()
        (workspace / "README.md").write_text("coordinator proof\n", encoding="utf-8")
        coordinator = self.store.create(
            title="coordinator",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=2,
        )
        self._start_todo(str(coordinator["id"]))
        executed = []

        def fake_execute(prepared):
            executed.append(prepared)
            return {
                "schemaVersion": "rag-ime.workspace-command-receipt.v1",
                "mutationApplied": True,
                "summary": "命令执行完成，退出码 0",
                "exitCode": 0,
                "output": "ok\n",
                "undoAvailable": False,
            }

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=_Facade(),
            workspace_harness=WorkspaceHarness(executor=fake_execute),
        )
        listed = gateway.execute(
            {
                **self._tool_call("workspace_list", "list", path=str(workspace)),
                "sessionId": coordinator["id"],
            }
        )["result"]
        read = gateway.execute(
            {
                **self._tool_call("workspace_read", "read", path=str(workspace / "README.md")),
                "sessionId": coordinator["id"],
            }
        )["result"]
        prepared = gateway.execute(
            {
                **self._tool_call(
                    "workspace_shell",
                    "run",
                    command="pwd",
                    cwd=str(workspace),
                    timeoutSeconds=10,
                ),
                "sessionId": coordinator["id"],
            }
        )["result"]

        self.assertIn("README.md", str(listed))
        self.assertEqual(read["content"], "coordinator proof\n")
        self.assertTrue(prepared["approvalRequired"])
        self.assertEqual(
            self.store.agent_todo(str(coordinator["id"]))["counts"]["inProgress"],
            1,
        )
        self.assertEqual(executed, [])
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = gateway.apply_approval(decided)

        self.assertEqual(receipt["exitCode"], 0)
        self.assertEqual(receipt["auditId"], approval["approvalId"])
        self.assertEqual(len(executed), 1)
        self.assertEqual(
            self.store.agent_todo(str(coordinator["id"]))["counts"]["inProgress"],
            1,
        )

    def test_workspace_read_routes_managed_resource_refs_to_authoritative_owners(self) -> None:
        coordinator = self.store.create(
            title="resource coordinator",
            mode="coordinator",
            workspace_roots=[],
            created_at_ms=3,
        )
        calls: list[tuple[object, ...]] = []
        delegation = SimpleNamespace(
            inspect_artifact=lambda session_id, artifact_id, limit: (
                calls.append(("artifact", session_id, artifact_id, limit))
                or {"artifact": {"id": artifact_id}, "records": []}
            )
        )
        governed_skills = SimpleNamespace(
            load_exact=lambda skill_id: (
                calls.append(("skill", skill_id))
                or {
                    "name": skill_id,
                    "description": "managed",
                    "body": "first\nsecond\n",
                    "contentRevision": "revision:1",
                }
            )
        )
        rooms = SimpleNamespace(
            participant_for_session=lambda session_id: {
                "sessionId": session_id,
                "roomId": "room:managed",
            }
        )
        collaboration = SimpleNamespace(
            rooms=rooms,
            media_receipt=lambda media_id, session_id: (
                calls.append(("media", session_id, media_id))
                or {"media": {"mediaId": media_id, "mimeType": "image/png"}}
            ),
            room_snapshot=lambda room_id: (
                calls.append(("room", room_id))
                or {"room": {"id": room_id}, "events": []}
            ),
        )
        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            delegation=delegation,
            collaboration=collaboration,
            governed_skills=governed_skills,
        )

        def read(resource_ref: str, **args: object) -> dict[str, object]:
            return gateway.execute(
                {
                    **self._tool_call(
                        "workspace_read",
                        "read",
                        resourceRef=resource_ref,
                        **args,
                    ),
                    "sessionId": coordinator["id"],
                }
            )["result"]

        artifact = read("artifact://artifact:one")
        media = read("media://media_abcdefghijkl")
        skill = read("skill://structured-handoff", limit=6)
        room = read("room://room:managed")

        self.assertEqual(artifact["resourceKind"], "artifact")
        self.assertIn("artifact:one", artifact["content"])
        self.assertEqual(media["metadata"]["owner"], "AgentMediaStore")
        self.assertEqual(skill["content"], "first\n")
        self.assertEqual(skill["nextOffset"], 6)
        self.assertEqual(room["resourceRevision"], room["resourceRevision"].lower())
        self.assertEqual(
            [call[0] for call in calls],
            ["artifact", "media", "skill", "room"],
        )
        with self.assertRaisesRegex(ValueError, "does not belong"):
            read("room://room:other")

    def test_workspace_job_starts_only_after_hash_bound_approval_and_exposes_logs(self) -> None:
        workspace = Path(self.tmp.name) / "background-workspace"
        workspace.mkdir()
        coordinator = self.store.create(
            title="background coordinator",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=3,
        )
        self._start_todo(str(coordinator["id"]))
        events = []
        background_jobs = AgentBackgroundJobService(
            Path(self.tmp.name) / "rag-ime.sqlite",
            events=lambda *args, **kwargs: events.append((args, kwargs)),
        )
        background_jobs.initialize()
        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=_Facade(),
            workspace_harness=background_jobs.workspace_harness,
            background_jobs=background_jobs,
        )
        try:
            pending = gateway.execute(
                {
                    **self._tool_call(
                        "workspace_job",
                        "start",
                        command="python3 -c \"print('background-tool-ok')\"",
                        cwd=str(workspace),
                        timeoutSeconds=10,
                        label="工具后台任务",
                    ),
                    "sessionId": coordinator["id"],
                }
            )["result"]
            self.assertTrue(pending["approvalRequired"])
            self.assertEqual(background_jobs.list(str(coordinator["id"]))["items"], [])

            approval = pending["approval"]
            self.assertEqual(approval["toolCallId"], "tool:1")
            decided = self.store.decide_approval(
                approval["approvalId"],
                approved=True,
                payload_sha256=approval["payloadSha256"],
            )
            receipt = gateway.apply_approval(decided)
            job_id = receipt["job"]["jobId"]
            deadline = time.monotonic() + 5
            job = receipt["job"]
            while time.monotonic() < deadline and job["status"] == "running":
                job = background_jobs.status(str(coordinator["id"]), job_id)["job"]
                time.sleep(0.05)

            logs = gateway.execute(
                {
                    **self._tool_call("workspace_job", "logs", jobId=job_id),
                    "sessionId": coordinator["id"],
                }
            )["result"]
            listed = gateway.execute(
                {
                    **self._tool_call("workspace_job", "list"),
                    "sessionId": coordinator["id"],
                }
            )["result"]

            self.assertEqual(job["status"], "completed")
            self.assertIn("background-tool-ok", logs["text"])
            self.assertEqual(listed["items"][0]["jobId"], job_id)
            self.assertEqual(receipt["auditId"], approval["approvalId"])
            self.assertEqual(
                receipt["job"]["causalMetadata"],
                decided["causalMetadata"],
            )
            self.assertTrue(any(args[1] == "background_job_completed" for args, _ in events))
        finally:
            background_jobs.close()

    def test_read_only_keeps_workspace_reads_and_creates_no_write_approval(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-read-only"
        workspace.mkdir()
        target = workspace / "README.md"
        target.write_text("只读证据\n", encoding="utf-8")
        session = self.store.create(
            title="read only coordinator",
            mode="coordinator",
            execution_mode="read_only",
            workspace_roots=[str(workspace)],
            created_at_ms=20,
        )

        read = self.gateway.execute(
            {
                **self._tool_call("workspace_read", "read", path=str(target)),
                "sessionId": session["id"],
            }
        )["result"]
        self.assertEqual(read["content"], "只读证据\n")

        for call in (
            self._tool_call(
                "workspace_patch",
                "apply",
                path=str(target),
                oldText="只读证据",
                newText="不得写入",
            ),
            self._tool_call(
                "workspace_shell",
                "run",
                command="pwd",
                cwd=str(workspace),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "not enabled|read-only"):
                self.gateway.execute({**call, "sessionId": session["id"]})
        self.assertEqual(target.read_text(encoding="utf-8"), "只读证据\n")
        self.assertEqual(
            self.store.list_approvals(session_id=str(session["id"])),
            [],
        )

    def test_workspace_managed_user_request_auto_applies_in_scope_without_todo_authority(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-managed"
        outside = Path(self.tmp.name) / "workspace-outside"
        workspace.mkdir()
        outside.mkdir()
        target = workspace / "main.py"
        target.write_text("value = 'before'\n", encoding="utf-8")
        outside_target = outside / "outside.py"
        outside_target.write_text("value = 'outside'\n", encoding="utf-8")
        session = self.store.create(
            title="managed coordinator",
            mode="coordinator",
            execution_mode="workspace_managed",
            workspace_roots=[str(workspace)],
            created_at_ms=21,
        )
        executed = []

        def fake_execute(prepared):
            executed.append(prepared)
            return {
                "schemaVersion": "rag-ime.workspace-command-receipt.v1",
                "mutationApplied": True,
                "summary": "命令执行完成，退出码 0",
                "exitCode": 0,
                "output": "managed\n",
                "undoAvailable": False,
            }

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=_Facade(),
            workspace_harness=WorkspaceHarness(executor=fake_execute),
        )
        automatic_approvals = []

        def auto_approve(approval):
            automatic_approvals.append(dict(approval))
            decided = self.store.decide_approval(
                str(approval["approvalId"]),
                approved=True,
                payload_sha256=str(approval["payloadSha256"]),
                decided_by="execution-policy:workspace_managed",
            )
            receipt = gateway.apply_approval(decided)
            return {
                "summary": receipt["summary"],
                "approvalRequired": False,
                "autoApproved": True,
                "approvalId": approval["approvalId"],
                "receipt": receipt,
            }

        gateway.bind_auto_approval_executor(auto_approve)
        patch_result = gateway.execute(
            {
                **self._tool_call(
                    "workspace_patch",
                    "apply",
                    path=str(target),
                    oldText="before",
                    newText="after",
                ),
                "sessionId": session["id"],
            }
        )["result"]
        shell_result = gateway.execute(
            {
                **self._tool_call(
                    "workspace_shell",
                    "run",
                    command="pwd",
                    cwd=str(workspace),
                ),
                "sessionId": session["id"],
            }
        )["result"]

        self.assertTrue(patch_result["autoApproved"])
        self.assertTrue(shell_result["autoApproved"])
        self.assertEqual(target.read_text(encoding="utf-8"), "value = 'after'\n")
        self.assertEqual(len(executed), 1)
        self.assertEqual(len(automatic_approvals), 2)

        with self.assertRaisesRegex(WorkspaceHarnessError, "outside"):
            gateway.execute(
                {
                    **self._tool_call(
                        "workspace_patch",
                        "apply",
                        path=str(outside_target),
                        oldText="outside",
                        newText="escaped",
                    ),
                    "sessionId": session["id"],
                }
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "system or privilege"):
            gateway.execute(
                {
                    **self._tool_call(
                        "workspace_shell",
                        "run",
                        command="sudo echo escaped",
                        cwd=str(workspace),
                    ),
                    "sessionId": session["id"],
                }
            )
        self.assertEqual(outside_target.read_text(encoding="utf-8"), "value = 'outside'\n")
        self.assertEqual(len(automatic_approvals), 2)

    def test_full_trust_model_arbitrates_every_gate_but_keeps_scope_and_system_fences(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-full-trust"
        outside = Path(self.tmp.name) / "outside-full-trust"
        workspace.mkdir()
        outside.mkdir()
        outside_target = outside / "outside.py"
        outside_target.write_text("value = 'outside'\n", encoding="utf-8")
        session = self.store.create(
            title="full trust coordinator",
            mode="coordinator",
            execution_mode="full_trust",
            workspace_roots=[str(workspace)],
            created_at_ms=22,
        )
        self._start_todo(str(session["id"]))
        auto_approvals = []

        def auto_approve(approval):
            auto_approvals.append(dict(approval))
            decided = self.store.decide_approval(
                str(approval["approvalId"]),
                approved=True,
                payload_sha256=str(approval["payloadSha256"]),
                decided_by="approval-model:test",
            )
            receipt = self.gateway.apply_approval(decided)
            return {
                "summary": receipt["summary"],
                "approvalRequired": False,
                "autoApproved": True,
                "approvalId": approval["approvalId"],
                "receipt": receipt,
                "modelDecided": True,
                "decisionMode": "model",
            }

        self.gateway.bind_auto_approval_executor(auto_approve)
        routine = self.gateway.execute(
            {
                **self._tool_call(
                    "planning",
                    "task_action",
                    taskId="task:1",
                    action="complete",
                    date="2026-07-13",
                ),
                "sessionId": session["id"],
            }
        )["result"]
        protected = self.gateway.execute(
            {
                **self._tool_call("runtime", "restart_sidecar"),
                "sessionId": session["id"],
            }
        )["result"]

        self.assertTrue(routine["autoApproved"])
        self.assertTrue(protected["autoApproved"])
        self.assertEqual(auto_approvals[1]["operation"], "restart_sidecar")
        with self.assertRaisesRegex(WorkspaceHarnessError, "outside"):
            self.gateway.execute(
                {
                    **self._tool_call(
                        "workspace_patch",
                        "apply",
                        path=str(outside_target),
                        oldText="outside",
                        newText="escaped",
                    ),
                    "sessionId": session["id"],
                }
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "system or privilege"):
            self.gateway.execute(
                {
                    **self._tool_call(
                        "workspace_shell",
                        "run",
                        command="sudo echo escaped",
                        cwd=str(workspace),
                    ),
                    "sessionId": session["id"],
                }
            )
        self.assertEqual(
            outside_target.read_text(encoding="utf-8"),
            "value = 'outside'\n",
        )
        self.assertEqual(len(auto_approvals), 2)
        applied = self.store.get_approval(str(routine["approvalId"]))
        self.assertEqual(applied["state"], "approved")
        self.assertEqual(applied["decidedBy"], "approval-model:test")

    def test_dangerous_profile_auto_approves_through_the_bound_service_bridge(self) -> None:
        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-auto-approve-v1",
            allowed_tools=None,
            workspace_roots=[self.tmp.name],
        )
        received = []

        def auto_approve(approval):
            received.append(dict(approval))
            return {
                "summary": "已自动批准并完成任务",
                "approvalRequired": False,
                "autoApproved": True,
                "approvalId": approval["approvalId"],
            }

        self.gateway.bind_auto_approval_executor(auto_approve)
        response = self.gateway.execute(
            self._tool_call(
                "planning",
                "task_action",
                taskId="task:1",
                action="complete",
                date="2026-07-13",
            )
        )

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["state"], "pending")
        self.assertTrue(response["result"]["autoApproved"])
        self.assertFalse(response["result"]["approvalRequired"])

    def test_room_per_action_tool_keeps_native_approval_and_seals_a_receipt(self) -> None:
        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="per_action",
            allowed_tools=None,
        )
        auto_approvals: list[dict[str, object]] = []
        executions: list[dict[str, object]] = []

        class _RoomCollaboration:
            def authorize_room_product_tool(
                self,
                _session_id,
                _tool,
                _args,
                *,
                tool_call_id,
                load_receipt_id,
            ):
                if not load_receipt_id:
                    raise AssertionError("Room product Tool requires a load receipt")
                return {
                    "invocationReceipt": {
                        "receiptId": f"invoke:{tool_call_id}",
                        "canonicalCommand": {"rootId": "root:room-planning"},
                    }
                }

            def record_room_product_tool_execution(
                self,
                session_id,
                invocation_receipt_id,
                *,
                status,
                result_hash,
            ):
                receipt = {
                    "sessionId": session_id,
                    "invocationReceiptId": invocation_receipt_id,
                    "status": status,
                    "resultHash": result_hash,
                }
                executions.append(receipt)
                return {"executionReceipt": receipt}

            def validate_room_product_tool_approval(
                self,
                session_id,
                invocation_receipt_id,
                *,
                tool_name,
            ):
                return {
                    "sessionId": session_id,
                    "receiptId": invocation_receipt_id,
                    "tool": tool_name,
                }

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            collaboration=_RoomCollaboration(),
        )
        gateway.bind_auto_approval_executor(
            lambda approval: auto_approvals.append(dict(approval))
            or {"autoApproved": True}
        )

        response = gateway.execute(
            {
                **self._tool_call(
                    "planning",
                    "task_action",
                    taskId="task:1",
                    action="complete",
                    date="2026-07-13",
                ),
                "toolCallId": "tool:room-planning",
                "loadReceiptId": "load:room-planning",
            }
        )

        self.assertTrue(response["result"]["approvalRequired"])
        self.assertEqual(auto_approvals, [])
        self.assertEqual(executions, [])
        self.assertIn("roomInvocationReceipt", response)
        self.assertNotIn("roomExecutionReceipt", response)
        approval = response["result"]["approval"]
        self.assertEqual(
            approval["preview"]["baseState"]["roomInvocationReceiptId"],
            "invoke:tool:room-planning",
        )
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = gateway.apply_approval(decided)

        self.assertEqual(executions[0]["status"], "applied")
        self.assertEqual(len(str(executions[0]["resultHash"])), 64)
        self.assertEqual(
            receipt["roomExecutionReceipt"]["invocationReceiptId"],
            "invoke:tool:room-planning",
        )

    def test_room_workspace_managed_auto_approval_seals_exactly_one_execution_receipt(self) -> None:
        workspace = Path(self.tmp.name) / "room-managed"
        workspace.mkdir()
        target = workspace / "room.py"
        target.write_text("state = 'before'\n", encoding="utf-8")
        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="coordinator",
            tool_profile_version="control-center-v1",
            execution_mode="workspace_managed",
            grant_workspace_scope=True,
            allowed_tools=None,
            workspace_roots=[str(workspace)],
        )
        executions: list[dict[str, object]] = []

        class _RoomCollaboration:
            def authorize_room_product_tool(
                self,
                _session_id,
                _tool,
                _args,
                *,
                tool_call_id,
                load_receipt_id,
            ):
                if not load_receipt_id:
                    raise AssertionError("Room product Tool requires a load receipt")
                return {
                    "invocationReceipt": {
                        "receiptId": f"invoke:{tool_call_id}",
                        "canonicalCommand": {"rootId": "root:room-managed"},
                    }
                }

            def validate_room_product_tool_approval(
                self,
                session_id,
                invocation_receipt_id,
                *,
                tool_name,
            ):
                return {
                    "sessionId": session_id,
                    "receiptId": invocation_receipt_id,
                    "tool": tool_name,
                }

            def record_room_product_tool_execution(
                self,
                session_id,
                invocation_receipt_id,
                *,
                status,
                result_hash,
            ):
                receipt = {
                    "sessionId": session_id,
                    "invocationReceiptId": invocation_receipt_id,
                    "status": status,
                    "resultHash": result_hash,
                }
                executions.append(receipt)
                return {"executionReceipt": receipt}

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            collaboration=_RoomCollaboration(),
        )

        def auto_approve(approval):
            decided = self.store.decide_approval(
                str(approval["approvalId"]),
                approved=True,
                payload_sha256=str(approval["payloadSha256"]),
                decided_by="execution-policy:workspace_managed",
            )
            receipt = gateway.apply_approval(decided)
            return {
                "summary": receipt["summary"],
                "approvalRequired": False,
                "autoApproved": True,
                "approvalId": approval["approvalId"],
                "receipt": receipt,
            }

        gateway.bind_auto_approval_executor(auto_approve)
        response = gateway.execute(
            {
                **self._tool_call(
                    "workspace_patch",
                    "apply",
                    path=str(target),
                    oldText="before",
                    newText="after",
                ),
                "toolCallId": "tool:room-managed-patch",
                "loadReceiptId": "load:room-managed-patch",
            }
        )

        self.assertTrue(response["result"]["autoApproved"])
        self.assertEqual(target.read_text(encoding="utf-8"), "state = 'after'\n")
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["status"], "applied")
        self.assertEqual(
            executions[0]["invocationReceiptId"],
            "invoke:tool:room-managed-patch",
        )
        self.assertEqual(
            response["roomExecutionReceipt"]["invocationReceiptId"],
            "invoke:tool:room-managed-patch",
        )
        self.assertNotIn("roomInvocationReceipt", response)

    def test_failed_room_approval_records_a_failed_execution_receipt(self) -> None:
        executions: list[dict[str, object]] = []

        class _RoomCollaboration:
            def record_room_product_tool_execution(
                self,
                session_id,
                invocation_receipt_id,
                *,
                status,
                result_hash,
            ):
                receipt = {
                    "sessionId": session_id,
                    "invocationReceiptId": invocation_receipt_id,
                    "status": status,
                    "resultHash": result_hash,
                }
                executions.append(receipt)
                return {"executionReceipt": receipt}

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            collaboration=_RoomCollaboration(),
        )

        result = gateway._seal_room_approval_execution(
            approval={
                "sessionId": self.session["id"],
                "preview": {
                    "baseState": {
                        "roomInvocationReceiptId": "invoke:failed-shell",
                    }
                },
            },
            result={"mutationApplied": False, "exitCode": 71},
        )

        self.assertEqual(executions[0]["status"], "failed")
        self.assertEqual(
            result["roomExecutionReceipt"]["invocationReceiptId"],
            "invoke:failed-shell",
        )

    def test_coordinator_search_and_patch_require_native_hash_bound_approval(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-patch"
        workspace.mkdir()
        target = workspace / "main.py"
        target.write_text("print('before')\n", encoding="utf-8")
        coordinator = self.store.create(
            title="coordinator patch",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=3,
        )
        media = AgentMediaStore(
            Path(self.tmp.name) / "rag-ime.sqlite",
            root=Path(self.tmp.name) / "tool-media",
        )
        self.gateway.artifact_projector = AgentToolArtifactProjector(media)
        self._start_todo(str(coordinator["id"]))
        found = self.gateway.execute(
            {
                **self._tool_call("workspace_search", "search", query="before"),
                "sessionId": coordinator["id"],
            }
        )["result"]
        prepared = self.gateway.execute(
            {
                **self._tool_call(
                    "workspace_patch",
                    "apply",
                    path=str(target),
                    oldText="before",
                    newText="after",
                ),
                "sessionId": coordinator["id"],
            }
        )["result"]

        self.assertEqual(found["matches"][0]["lineNumber"], 1)
        self.assertEqual(target.read_text(encoding="utf-8"), "print('before')\n")
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.assertEqual(receipt["replacementCount"], 1)
        self.assertEqual(receipt["artifactProjection"], {"status": "available", "count": 2})
        self.assertEqual(
            [block["data"]["mimeType"] for block in receipt["agentBlocks"]],
            ["text/plain", "text/x-diff"],
        )
        self.assertEqual(target.read_text(encoding="utf-8"), "print('after')\n")
        self.assertEqual(
            self.store.agent_todo(str(coordinator["id"]))["counts"]["inProgress"],
            1,
        )

    def test_workspace_patch_fails_closed_if_file_changes_after_native_approval(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-stale"
        workspace.mkdir()
        target = workspace / "main.py"
        target.write_text("old\n", encoding="utf-8")
        coordinator = self.store.create(
            title="coordinator stale patch",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=4,
        )
        self._start_todo(str(coordinator["id"]))
        prepared = self.gateway.execute(
            {
                **self._tool_call(
                    "workspace_patch",
                    "apply",
                    path=str(target),
                    oldText="old",
                    newText="new",
                ),
                "sessionId": coordinator["id"],
            }
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        target.write_text("changed\n", encoding="utf-8")

        with self.assertRaisesRegex(WorkspaceHarnessError, "changed"):
            self.gateway.apply_approval(decided)
        self.assertEqual(target.read_text(encoding="utf-8"), "changed\n")
        self.assertEqual(
            self.store.agent_todo(str(coordinator["id"]))["counts"]["inProgress"],
            1,
        )

    def test_user_request_reaches_existing_action_approval_policy_without_todo(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-gated"
        workspace.mkdir()
        (workspace / "README.md").write_text("readable\n", encoding="utf-8")
        coordinator = self.store.create(
            title="coordinator gated",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=5,
        )
        listed = self.gateway.execute(
            {
                **self._tool_call("workspace_list", "list", path=str(workspace)),
                "sessionId": coordinator["id"],
            }
        )["result"]
        self.assertIn("README.md", str(listed))
        prepared = self.gateway.execute(
            {
                **self._tool_call(
                    "workspace_shell",
                    "run",
                    command="pwd",
                    cwd=str(workspace),
                ),
                "sessionId": coordinator["id"],
            }
        )["result"]
        self.assertTrue(prepared["approvalRequired"])
        self.assertEqual(prepared["approval"]["riskLevel"], "R2")
        todo = self.store.agent_todo(str(coordinator["id"]))
        self.assertEqual(todo["revision"], 0)
        self.assertTrue(
            self.store.workflow_state(str(coordinator["id"]))["actGate"]["allowed"]
        )

    def test_workspace_write_receipt_registers_hash_bound_work_document(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-work-document"
        workspace.mkdir()
        coordinator = self.store.create(
            title="work document coordinator",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=6,
        )
        session_id = str(coordinator["id"])
        self._start_todo(session_id)
        todo = self.store.agent_todo(session_id)
        documents = WorkDocumentService(
            self.store.db_path,
            sessions=self.store,
            context_runtime=AgentContextRuntime(self.store.db_path),
        )
        documents.initialize()
        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=_Facade(),
            work_documents=documents,
        )
        prepared = gateway.execute(
            {
                **self._tool_call(
                    "workspace_write",
                    "apply",
                    path="docs/work.md",
                    resourceRevision="missing",
                    content="# Canonical work\n",
                    workDocument={
                        "authorityKind": "session_todo",
                        "authorityId": session_id,
                        "authorityRevision": todo["revision"],
                        "title": "Canonical work",
                    },
                ),
                "sessionId": session_id,
            }
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        tampered = dict(decided)
        tampered_preview = dict(tampered["preview"])
        tampered_action = dict(tampered_preview["actionPayload"])
        tampered_binding = dict(tampered_action["workDocument"])
        tampered_binding["authorityRevision"] = int(todo["revision"]) + 1
        tampered_action["workDocument"] = tampered_binding
        tampered_preview["actionPayload"] = tampered_action
        tampered["preview"] = tampered_preview
        with self.assertRaisesRegex(ValueError, "payload no longer matches"):
            gateway.apply_approval(tampered)

        receipt = gateway.apply_approval(decided)
        registration = receipt["workDocumentRegistration"]
        self.assertEqual(registration["operation"], "register")
        self.assertEqual(registration["document"]["authorityId"], session_id)
        self.assertEqual(registration["document"]["contentSha256"], receipt["postimageSha256"])
        listed = gateway.execute(
            {
                **self._tool_call("work_documents", "list", limit=10),
                "sessionId": session_id,
            }
        )["result"]
        self.assertEqual(listed["schemaVersion"], "rag-ime.work-document-list.v1")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(
            gateway.execute(
                {
                    **self._tool_call(
                        "work_documents",
                        "get",
                        documentId=registration["document"]["documentId"],
                    ),
                    "sessionId": session_id,
                }
            )["result"]["document"]["documentId"],
            registration["document"]["documentId"],
        )

    def test_workspace_harness_failure_keeps_native_approval_out_of_execution(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-failing"
        workspace.mkdir()
        coordinator = self.store.create(
            title="coordinator failing",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=6,
        )
        self._start_todo(str(coordinator["id"]))

        def fail_execute(_prepared):
            raise WorkspaceHarnessError("runner unavailable")

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=_Facade(),
            workspace_harness=WorkspaceHarness(executor=fail_execute),
        )
        prepared = gateway.execute(
            {
                **self._tool_call(
                    "workspace_shell",
                    "run",
                    command="pwd",
                    cwd=str(workspace),
                ),
                "sessionId": coordinator["id"],
            }
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )

        with self.assertRaisesRegex(WorkspaceHarnessError, "runner unavailable"):
            gateway.apply_approval(decided)
        self.assertEqual(
            self.store.agent_todo(str(coordinator["id"]))["counts"]["inProgress"],
            1,
        )

    def test_failed_timeout_or_limited_shell_receipt_does_not_change_todo_authority(self) -> None:
        cases = (
            {"mutationApplied": False, "exitCode": 1, "timedOut": False, "outputLimited": False},
            {"mutationApplied": False, "exitCode": -15, "timedOut": True, "outputLimited": False},
            {"mutationApplied": False, "exitCode": -15, "timedOut": False, "outputLimited": True},
        )
        for index, receipt_fields in enumerate(cases):
            with self.subTest(receipt=receipt_fields):
                workspace = Path(self.tmp.name) / f"workspace-unsuccessful-{index}"
                workspace.mkdir()
                coordinator = self.store.create(
                    title=f"coordinator unsuccessful {index}",
                    mode="coordinator",
                    workspace_roots=[str(workspace)],
                    created_at_ms=10 + index,
                )
                self._start_todo(str(coordinator["id"]))

                def execute(_prepared, fields=receipt_fields):
                    return {
                        "schemaVersion": "rag-ime.workspace-command-receipt.v1",
                        "summary": "command did not complete successfully",
                        "output": "",
                        "undoAvailable": False,
                        **fields,
                    }

                gateway = ControlToolGateway(
                    sessions=self.store,
                    management=self.management,
                    core=_Core(),
                    project="wisdom-weasel-rag-ime",
                    facade=_Facade(),
                    workspace_harness=WorkspaceHarness(executor=execute),
                )
                prepared = gateway.execute(
                    {
                        **self._tool_call(
                            "workspace_shell",
                            "run",
                            command="false",
                            cwd=str(workspace),
                        ),
                        "sessionId": coordinator["id"],
                    }
                )["result"]
                approval = prepared["approval"]
                decided = self.store.decide_approval(
                    approval["approvalId"],
                    approved=True,
                    payload_sha256=approval["payloadSha256"],
                )

                result = gateway.apply_approval(decided)
                self.assertFalse(result["mutationApplied"])
                self.assertEqual(
                    self.store.agent_todo(str(coordinator["id"]))["counts"]["inProgress"],
                    1,
                )

    def test_task_action_requires_native_approval_then_returns_rollback_receipt(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "planning",
                "task_action",
                taskId="task:1",
                date="2026-07-13",
                action="complete",
            )
        )["result"]
        approval = prepared["approval"]

        self.assertTrue(prepared["approvalRequired"])
        self.assertEqual(self.management.tasks[0]["status"], "todo")
        self.assertEqual(approval["preview"]["changes"][0]["after"], "已完成")

        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)

        self.assertTrue(receipt["mutationApplied"])
        self.assertTrue(receipt["undoAvailable"])
        self.assertEqual(receipt["rollback"]["operation"], "undo_task_event")
        self.assertEqual(self.management.tasks[0]["status"], "done")

    def test_memory_preview_apply_and_rollback_use_native_approval_and_revision_hash(self) -> None:
        preview = self.gateway.execute(
            self._call(
                "maintenance_preview",
                trigger="explicit_request",
                instruction="整理本次 Pi 会话的最终事实",
            )
        )["result"]
        self.assertTrue(preview["reviewRequired"])
        self.assertTrue(preview["needsReview"])
        self.assertEqual(preview["runId"], "memory_book_draft")
        self.assertEqual(preview["counts"]["upsert_memory_book"], 1)
        self.assertNotIn("run", preview)
        self.assertEqual(self.facade.memory_run_status, "draft")

        review = self.gateway.execute(
            self._call("maintenance_review", runId="memory_book_draft")
        )["result"]
        self.assertTrue(review["reviewRequired"])
        self.assertTrue(review["canApply"])
        self.assertEqual(review["diffCount"], 3)
        self.assertNotIn("changes", review)
        self.assertNotIn("run", review)

        prepared = self.gateway.execute(
            self._call("maintenance_apply", runId="memory_book_draft")
        )["result"]
        approval = prepared["approval"]
        self.assertTrue(prepared["approvalRequired"])
        self.assertEqual(approval["preview"]["changes"][0]["after"], "已应用")
        self.assertIn("Pi 控制中心", [item["label"] for item in approval["preview"]["changes"]])
        self.assertEqual(self.facade.memory_run_status, "draft")

        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        applied = self.gateway.apply_approval(decided)
        self.store.complete_approval(approval["approvalId"], state="applied", receipt=applied)
        self.assertEqual(self.facade.memory_run_status, "applied")
        self.assertTrue(applied["undoAvailable"])
        self.assertEqual(applied["diffCount"], 3)

        rollback = self.gateway.execute(
            self._call("maintenance_rollback", runId="memory_book_draft")
        )["result"]["approval"]
        rollback_decided = self.store.decide_approval(
            rollback["approvalId"],
            approved=True,
            payload_sha256=rollback["payloadSha256"],
        )
        rolled_back = self.gateway.apply_approval(rollback_decided)
        self.assertEqual(self.facade.memory_run_status, "rolled_back")
        self.assertEqual(rolled_back["revertedRunId"], "memory_book_draft")
        self.assertFalse(rolled_back["undoAvailable"])

    def test_memory_curation_prepare_returns_compact_no_change_receipt(self) -> None:
        self.facade.memory_run_status = "empty"

        result = self.gateway.execute(
            self._call(
                "curation_prepare",
                trigger="task_completion",
                scope="incremental",
                policy="conservative",
            )
        )["result"]

        self.assertEqual(result["runId"], "memory_book_draft")
        self.assertEqual(result["counts"], {})
        self.assertEqual(result["diffCount"], 0)
        self.assertFalse(result["needsReview"])
        self.assertFalse(result["reviewRequired"])
        self.assertFalse(result["storedDraft"])
        self.assertNotIn("run", result)
        self.assertNotIn("changes", result)
        request = next(
            payload
            for operation, payload in self.facade.memory_maintenance_requests
            if operation == "prepare"
        )
        self.assertEqual(
            (request["ownerKind"], request["ownerId"]),
            ("user", "default"),
        )
        self.assertEqual(request["trigger"], "task_completion")

    def test_memory_curation_prepare_does_not_report_completion_with_backlog(self) -> None:
        self.facade.memory_run_status = "empty"
        self.facade.memory_prepare_pending_count = 3
        self.facade.memory_prepare_batch_count = 8
        self.facade.memory_prepare_drain_limited = True

        result = self.gateway.execute(
            self._call(
                "curation_prepare",
                trigger="explicit_request",
                scope="incremental",
                policy="conservative",
            )
        )["result"]

        self.assertEqual(result["pendingSourceCount"], 3)
        self.assertEqual(result["batchCount"], 8)
        self.assertTrue(result["drainLimited"])
        self.assertIn("仍有 3 条", result["summary"])
        self.assertNotIn("全部新增证据已完成整理", result["summary"])

    def test_memory_curation_prepare_rejects_ordinary_chat_without_completion_trigger(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "requires trigger"):
            self.gateway.execute(self._call("curation_prepare"))
        with self.assertRaisesRegex(ValueError, "requires trigger"):
            self.gateway.execute(
                self._call("curation_prepare", trigger="ordinary_chat")
            )
        self.assertEqual(self.facade.memory_maintenance_requests, [])

    def test_memory_curation_prepare_treats_no_sources_as_success(self) -> None:
        self.facade.memory_prepare_no_run = True

        result = self.gateway.execute(
            self._call(
                "curation_prepare",
                trigger="explicit_request",
                scope="incremental",
                policy="conservative",
            )
        )["result"]

        self.assertEqual(result["runId"], "")
        self.assertEqual(result["diffCount"], 0)
        self.assertFalse(result["needsReview"])
        self.assertFalse(result["reviewRequired"])
        self.assertFalse(result["storedDraft"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "no_sources")

    def test_memory_apply_fails_closed_when_draft_changes_after_preview(self) -> None:
        prepared = self.gateway.execute(
            self._call("maintenance_apply", runId="memory_book_draft")
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.facade.memory_run_status = "applied"

        with self.assertRaisesRegex(ValueError, "changed after"):
            self.gateway.apply_approval(decided)

    def test_task_action_fails_closed_when_task_changes_after_preview(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "planning",
                "task_action",
                taskId="task:1",
                date="2026-07-13",
                action="start",
            )
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.management.tasks[0]["updatedAtMs"] += 1

        with self.assertRaisesRegex(ValueError, "changed after"):
            self.gateway.apply_approval(decided)
        self.assertEqual(self.management.tasks[0]["status"], "todo")

    def test_input_settings_preview_apply_and_rollback_are_hash_bound(self) -> None:
        changes = [
            {"key": "interaction.postCommit.idleTriggerMs", "value": 650},
            {"key": "pinyin.pairs.nL", "value": True},
        ]
        preview = self.gateway.execute(
            self._tool_call("input", "preview_settings", changes=changes)
        )["result"]
        self.assertEqual(preview["changeCount"], 2)
        self.assertTrue(preview["approvalRequiredForApply"])

        prepared = self.gateway.execute(
            self._tool_call("input", "apply_settings", changes=changes)
        )["result"]
        approval = prepared["approval"]
        self.assertEqual(self.facade.settings_payload["pinyin"]["pairs"]["nL"], False)
        self.assertEqual(approval["preview"]["changes"][0]["before"], 420)

        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.store.complete_approval(approval["approvalId"], state="applied", receipt=receipt)
        self.assertEqual(self.facade.settings_payload["interaction"]["postCommit"]["idleTriggerMs"], 650)
        self.assertEqual(self.facade.settings_payload["pinyin"]["pairs"]["nL"], True)
        self.assertTrue(receipt["undoAvailable"])

        rollback = self.gateway.execute(
            self._tool_call(
                "input",
                "rollback_settings",
                sourceApprovalId=approval["approvalId"],
            )
        )["result"]["approval"]
        rollback_decided = self.store.decide_approval(
            rollback["approvalId"],
            approved=True,
            payload_sha256=rollback["payloadSha256"],
        )
        rollback_receipt = self.gateway.apply_approval(rollback_decided)
        self.assertEqual(self.facade.settings_payload["interaction"]["postCommit"]["idleTriggerMs"], 420)
        self.assertEqual(self.facade.settings_payload["pinyin"]["pairs"]["nL"], False)
        self.assertEqual(rollback_receipt["revertedSettingsApprovalId"], approval["approvalId"])

    def test_input_settings_apply_fails_closed_after_any_settings_revision_change(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "input",
                "apply_settings",
                changes=[{"key": "display.fadeAnimation", "value": False}],
            )
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.facade.settings_revision += 1

        with self.assertRaisesRegex(ValueError, "changed after"):
            self.gateway.apply_approval(decided)
        self.assertTrue(self.facade.settings_payload["display"]["fadeAnimation"])

    def test_lexicon_apply_hides_review_token_redeploys_and_can_rollback(self) -> None:
        review = self.gateway.execute(
            self._tool_call("input", "lexicon_review")
        )["result"]
        review_key = review["entries"][0]["reviewKey"]
        self.assertNotIn("must-not-reach-pi", str(review))

        prepared = self.gateway.execute(
            self._tool_call(
                "input",
                "lexicon_apply",
                selectedKeys=[review_key],
            )
        )["result"]
        approval = prepared["approval"]
        self.assertNotIn("must-not-reach-pi", str(prepared))
        self.assertFalse(self.facade.lexicon_applied)

        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.store.complete_approval(approval["approvalId"], state="applied", receipt=receipt)
        self.assertTrue(self.facade.lexicon_applied)
        self.assertEqual(receipt["deploymentStatus"], "succeeded")
        self.assertTrue(receipt["undoAvailable"])

        rollback = self.gateway.execute(
            self._tool_call(
                "input",
                "lexicon_rollback",
                sourceApprovalId=approval["approvalId"],
            )
        )["result"]["approval"]
        rollback_decided = self.store.decide_approval(
            rollback["approvalId"],
            approved=True,
            payload_sha256=rollback["payloadSha256"],
        )
        rollback_receipt = self.gateway.apply_approval(rollback_decided)
        self.assertFalse(self.facade.lexicon_applied)
        self.assertEqual(rollback_receipt["revertedLexiconApprovalId"], approval["approvalId"])
        self.assertFalse(rollback_receipt["undoAvailable"])

    def test_runtime_pause_resume_and_restart_require_native_approval(self) -> None:
        pause = self.gateway.execute(
            self._tool_call("runtime", "pause_ai")
        )["result"]["approval"]
        self.assertEqual(pause["riskLevel"], "R1")
        self.assertFalse(self.management.ai_paused)
        pause_decided = self.store.decide_approval(
            pause["approvalId"],
            approved=True,
            payload_sha256=pause["payloadSha256"],
        )
        paused = self.gateway.apply_approval(pause_decided)
        self.assertTrue(paused["mutationApplied"])
        self.assertTrue(paused["aiPaused"])
        self.assertTrue(self.management.ai_paused)

        resume = self.gateway.execute(
            self._tool_call("runtime", "resume_ai")
        )["result"]["approval"]
        resume_decided = self.store.decide_approval(
            resume["approvalId"],
            approved=True,
            payload_sha256=resume["payloadSha256"],
        )
        resumed = self.gateway.apply_approval(resume_decided)
        self.assertTrue(resumed["mutationApplied"])
        self.assertFalse(resumed["aiPaused"])

        restart = self.gateway.execute(
            self._tool_call("runtime", "restart_predictor")
        )["result"]["approval"]
        self.assertEqual(restart["riskLevel"], "R2")
        restart_decided = self.store.decide_approval(
            restart["approvalId"],
            approved=True,
            payload_sha256=restart["payloadSha256"],
        )
        restarted = self.gateway.apply_approval(restart_decided)
        self.assertTrue(restarted["mutationApplied"])
        self.assertEqual(restarted["status"], "succeeded")

        sidecar = self.gateway.execute(
            self._tool_call("runtime", "restart_sidecar")
        )["result"]["approval"]
        self.assertEqual(sidecar["riskLevel"], "R2")
        sidecar_decided = self.store.decide_approval(
            sidecar["approvalId"],
            approved=True,
            payload_sha256=sidecar["payloadSha256"],
        )
        external = self.gateway.apply_approval(sidecar_decided)
        self.assertFalse(external["mutationApplied"])
        self.assertTrue(external["externalActionPending"])
        self.assertEqual(external["externalAction"], "restart_sidecar")
        self.assertEqual(external["status"], "external-supervisor-required")
        self.assertEqual(
            external["externalCommand"],
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.rag-ime.sidecar"],
        )
        self.assertEqual(len(external["externalCommandSha256"]), 64)

    def test_runtime_action_fails_closed_when_runtime_revision_changes(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call("runtime", "restart_predictor")
        )["result"]["approval"]
        decided = self.store.decide_approval(
            prepared["approvalId"],
            approved=True,
            payload_sha256=prepared["payloadSha256"],
        )
        self.management.runtime_revision += 1
        with self.assertRaisesRegex(ValueError, "changed after"):
            self.gateway.apply_approval(decided)

    def test_model_profile_preview_apply_and_rollback_preserve_secrets(self) -> None:
        profiles = self.gateway.execute(
            self._tool_call("models", "profiles")
        )["result"]
        self.assertEqual(profiles["profiles"]["instant"]["provider"], "mlx")
        self.assertFalse(profiles["secretsVisible"])

        requested = {
            "slot": "instant",
            "provider": "ollama",
            "endpoint": "http://127.0.0.1:11434/v1",
            "model": "qwen3:0.6b",
        }
        preview = self.gateway.execute(
            self._tool_call("models", "profile_preview", **requested)
        )["result"]
        self.assertEqual(preview["restartComponent"], "predictor")
        self.assertTrue(preview["secretsPreserved"])
        self.assertEqual(len(preview["changes"]), 3)

        prepared = self.gateway.execute(
            self._tool_call("models", "profile_apply", **requested)
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.store.complete_approval(approval["approvalId"], state="applied", receipt=receipt)
        self.assertEqual(self.management.provider_profiles["instant"]["provider"], "ollama")
        self.assertEqual(receipt["activationStatus"], "succeeded")
        self.assertTrue(receipt["secretsPreserved"])

        rollback = self.gateway.execute(
            self._tool_call(
                "models",
                "profile_rollback",
                sourceApprovalId=approval["approvalId"],
            )
        )["result"]["approval"]
        rollback_decided = self.store.decide_approval(
            rollback["approvalId"],
            approved=True,
            payload_sha256=rollback["payloadSha256"],
        )
        rolled_back = self.gateway.apply_approval(rollback_decided)
        self.assertEqual(self.management.provider_profiles["instant"]["provider"], "mlx")
        self.assertEqual(rolled_back["revertedModelProfileApprovalId"], approval["approvalId"])

    def test_voice_provider_switch_and_rollback_only_change_the_provider_choice(self) -> None:
        preview = self.gateway.execute(
            self._tool_call(
                "voice",
                "provider_preview",
                provider="realtime_websocket",
            )
        )["result"]
        self.assertTrue(preview["approvalRequiredForApply"])
        self.assertTrue(preview["secretsPreserved"])

        prepared = self.gateway.execute(
            self._tool_call(
                "voice",
                "provider_apply",
                provider="realtime_websocket",
            )
        )["result"]["approval"]
        decided = self.store.decide_approval(
            prepared["approvalId"],
            approved=True,
            payload_sha256=prepared["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.store.complete_approval(prepared["approvalId"], state="applied", receipt=receipt)
        self.assertEqual(self.management.provider_profiles["voice"]["provider"], "realtime_websocket")
        self.assertEqual(receipt["activationStatus"], "pending_external_restart")
        self.assertTrue(receipt["secretsPreserved"])

        rollback = self.gateway.execute(
            self._tool_call(
                "voice",
                "provider_rollback",
                sourceApprovalId=prepared["approvalId"],
            )
        )["result"]["approval"]
        rollback_decided = self.store.decide_approval(
            rollback["approvalId"],
            approved=True,
            payload_sha256=rollback["payloadSha256"],
        )
        rolled_back = self.gateway.apply_approval(rollback_decided)
        self.assertEqual(self.management.provider_profiles["voice"]["provider"], "native_streaming")
        self.assertEqual(rolled_back["revertedVoiceProviderApprovalId"], prepared["approvalId"])

        with self.assertRaisesRegex(ValueError, "unsupported voice provider field"):
            self.gateway.execute(
                self._tool_call(
                    "voice",
                    "provider_preview",
                    provider="http_transcription",
                    endpoint="https://must-not-enter-agent-tool.example/v1",
                )
            )

    def test_knowledge_provider_save_is_honest_about_pending_sidecar_restart(self) -> None:
        requested = {
            "slot": "knowledge",
            "provider": "openai-compatible",
            "endpoint": "https://models.example.test/v1",
            "model": "knowledge-v2",
        }
        prepared = self.gateway.execute(
            self._tool_call("models", "profile_apply", **requested)
        )["result"]["approval"]
        decided = self.store.decide_approval(
            prepared["approvalId"],
            approved=True,
            payload_sha256=prepared["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.assertTrue(receipt["mutationApplied"])
        self.assertEqual(receipt["activationStatus"], "pending_external_restart")
        self.assertIn("外部 Supervisor", receipt["summary"])

        with self.assertRaisesRegex(ValueError, "unsupported model profile field"):
            self.gateway.execute(
                self._tool_call(
                    "models",
                    "profile_preview",
                    **requested,
                    apiKey="must-not-enter-pi-tool",
                )
            )

    def test_model_profile_apply_fails_closed_after_configuration_change(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "models",
                "profile_apply",
                slot="instant",
                provider="ollama",
                endpoint="http://127.0.0.1:11434/v1",
                model="qwen3:0.6b",
            )
        )["result"]["approval"]
        decided = self.store.decide_approval(
            prepared["approvalId"],
            approved=True,
            payload_sha256=prepared["payloadSha256"],
        )
        self.management.provider_configuration_revision += 1
        with self.assertRaisesRegex(ValueError, "changed after"):
            self.gateway.apply_approval(decided)

    def test_configuration_export_and_restore_are_hash_bound_and_supervised(self) -> None:
        preview = self.gateway.execute(
            self._tool_call("configuration", "export_preview")
        )["result"]
        self.assertFalse(preview["secretsIncluded"])
        self.assertTrue(preview["approvalRequiredForExport"])

        prepared = self.gateway.execute(
            self._tool_call("configuration", "export")
        )["result"]
        approval = prepared["approval"]
        backup_root = Path(os.environ["RAG_IME_APP_SUPPORT_DIR"]) / "Backups"
        self.assertFalse(backup_root.exists())
        self.assertNotIn(str(Path.home()), str(prepared))

        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)
        self.store.complete_approval(approval["approvalId"], state="applied", receipt=receipt)

        target = Path(os.environ["RAG_IME_APP_SUPPORT_DIR"]) / str(
            receipt["managedRelativePath"]
        )
        self.assertTrue(target.is_file())
        self.assertFalse(receipt["secretsIncluded"])
        self.assertNotIn(str(Path.home()), str(receipt))

        restore = self.gateway.execute(
            self._tool_call(
                "configuration",
                "restore_preview",
                sourceApprovalId=approval["approvalId"],
            )
        )["result"]
        self.assertTrue(restore["valid"])
        self.assertTrue(restore["requiresRestart"])
        self.assertTrue(restore["restoreApplyAvailable"])
        self.assertEqual(restore["restoreApplyRisk"], "R3")
        self.assertTrue(restore["externalSupervisorRequired"])
        self.assertNotIn("restoreToken", str(restore))
        self.assertNotIn(str(Path.home()), str(restore))

        restore_prepared = self.gateway.execute(
            self._tool_call(
                "configuration",
                "restore_apply",
                sourceApprovalId=approval["approvalId"],
            )
        )["result"]
        restore_approval = restore_prepared["approval"]
        self.assertEqual(restore_approval["riskLevel"], "R3")
        self.assertNotIn("restoreToken", str(restore_prepared))

        restore_decided = self.store.decide_approval(
            restore_approval["approvalId"],
            approved=True,
            payload_sha256=restore_approval["payloadSha256"],
        )
        restore_receipt = self.gateway.apply_approval(restore_decided)
        self.assertFalse(restore_receipt["mutationApplied"])
        self.assertTrue(restore_receipt["externalActionPending"])
        self.assertEqual(restore_receipt["externalAction"], "restore_backup")
        self.assertEqual(restore_receipt["status"], "external-supervisor-required")

    def test_applied_task_receipt_can_prepare_and_execute_one_approved_undo(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "planning",
                "task_action",
                taskId="task:1",
                date="2026-07-13",
                action="complete",
            )
        )["result"]
        action_approval = prepared["approval"]
        decided = self.store.decide_approval(
            action_approval["approvalId"],
            approved=True,
            payload_sha256=action_approval["payloadSha256"],
        )
        action_receipt = self.gateway.apply_approval(decided)
        self.store.complete_approval(
            action_approval["approvalId"], state="applied", receipt=action_receipt
        )

        undo = self.gateway.execute(
            self._tool_call(
                "planning",
                "undo_task_event",
                eventId=action_receipt["taskEventId"],
            )
        )["result"]["approval"]
        undo_decided = self.store.decide_approval(
            undo["approvalId"],
            approved=True,
            payload_sha256=undo["payloadSha256"],
        )
        undo_receipt = self.gateway.apply_approval(undo_decided)

        self.assertEqual(self.management.tasks[0]["status"], "todo")
        self.assertEqual(undo_receipt["revertedTaskEventId"], action_receipt["taskEventId"])
        self.assertFalse(undo_receipt["undoAvailable"])

        self.store.complete_approval(undo["approvalId"], state="applied", receipt=undo_receipt)
        with self.assertRaisesRegex(ValueError, "already been rolled back"):
            self.gateway.execute(
                self._tool_call(
                    "planning",
                    "undo_task_event",
                    eventId=action_receipt["taskEventId"],
                )
            )

    def test_overview_planning_document_knowledge_and_models_use_scoped_services(self) -> None:
        overview = self.gateway.execute(self._tool_call("overview", "status"))["result"]
        planning = self.gateway.execute(self._tool_call("planning", "dashboard"))["result"]
        bases = self.gateway.execute(self._tool_call("knowledge", "list_bases"))["result"]
        knowledge = self.gateway.execute(
            self._tool_call(
                "knowledge",
                "search",
                kbId="kb:project-docs",
                query="为什么普通生成不经过 Pi",
                topK=6,
            )
        )["result"]
        models = self.gateway.execute(self._tool_call("models", "status"))["result"]

        self.assertEqual(overview["unhealthyComponents"], ["predictor"])
        self.assertIn("1 个未完成任务", planning["summary"])
        self.assertEqual(bases["items"][0]["kbId"], "kb:project-docs")
        self.assertIn("Pi 只负责 Agent Loop", knowledge["items"][0]["content"])
        self.assertNotIn("/private/project", str(knowledge))
        self.assertEqual(self.knowledge.calls[-1][0], "search")
        self.assertEqual("hybrid", self.knowledge.calls[-1][1]["mode"])
        self.assertNotIn("searchMode", self.knowledge.calls[-1][1])
        self.assertIn("深度知识模型当前不可用", models["summary"])

    def test_document_knowledge_search_normalizes_mode_and_preserves_file_name_scope(self) -> None:
        self.gateway.execute(
            self._tool_call(
                "knowledge",
                "search",
                kbId="kb:project-docs",
                query="Agent Loop",
                searchMode="dense",
                fileName="architecture.md",
            )
        )
        operation, payload = self.knowledge.calls[-1]
        self.assertEqual("search", operation)
        self.assertEqual("dense", payload["mode"])
        self.assertEqual("architecture.md", payload["fileName"])

    def test_document_knowledge_exposes_only_five_read_operations_end_to_end(self) -> None:
        calls = [
            self._tool_call("knowledge", "list_bases"),
            self._tool_call(
                "knowledge",
                "search",
                kbId="kb:project-docs",
                query="Agent Loop",
            ),
            self._tool_call(
                "knowledge",
                "find",
                kbId="kb:project-docs",
                fileId="file:1",
                patterns=["热路径"],
            ),
            self._tool_call(
                "knowledge",
                "open",
                kbId="kb:project-docs",
                fileId="file:1",
                line=41,
                windowSize=20,
            ),
            self._tool_call("knowledge", "status"),
        ]

        for call in calls:
            result = self.gateway.execute(call)["result"]
            self.assertIsInstance(result, dict)
        self.assertEqual(
            ["list_bases", "search", "find", "open", "status"],
            [operation for operation, _payload in self.knowledge.calls[-5:]],
        )
        manifest = next(
            item for item in self.gateway.manifests()["items"] if item["id"] == "knowledge"
        )
        self.assertEqual(("list_bases", "search", "find", "open", "status"), tuple(manifest["operations"]))

    def test_write_operations_knowledge_management_and_secrets_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not agent-manageable"):
            self.gateway.execute(
                self._tool_call(
                    "input",
                    "apply_settings",
                    changes=[{"key": "privacy.debugIncludeText", "value": True}],
                )
            )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.gateway.execute(self._tool_call("knowledge", "import", kbId="kb:project-docs"))
        audit = self.gateway.execute(self._tool_call("configuration", "audit"))["result"]
        lexicon = self.gateway.execute(self._tool_call("input", "lexicon_review"))["result"]
        self.assertNotIn("must-not-leak", str(audit))
        self.assertNotIn("must-not-reach-pi", str(lexicon))

    def test_document_knowledge_never_falls_back_to_personal_memory(self) -> None:
        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
        )

        status = gateway.execute(self._tool_call("knowledge", "status"))["result"]
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "knowledge_client_not_configured")
        with self.assertRaisesRegex(ValueError, "document knowledge library is unavailable"):
            gateway.execute(
                self._tool_call(
                    "knowledge",
                    "search",
                    kbId="kb:project-docs",
                    query="Pi",
                )
            )

    def test_pi_extension_delegates_coordinator_shell_without_node_escape_hatch(self) -> None:
        extension = (
            Path(__file__).parents[1] / "integrations" / "pi" / "rag-ime-control.ts"
        ).read_text(encoding="utf-8")

        forbidden = [
            "child_process",
            "node:child_process",
            "registerCommand(",
            "execSync(",
            "spawn(",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, extension)
        for tool in (
            "overview",
            "input",
            "voice",
            "planning",
            "agent_schedule",
            "memory",
            "agent_role_book",
            "knowledge",
            "models",
            "runtime",
            "configuration",
            "agents",
            "todo",
            "agent_goal",
            "ls",
            "read",
            "grep",
            "find",
            "edit",
            "write",
            "workspace_patch",
            "workspace_lsp",
            "bash",
        ):
            self.assertEqual(extension.count(f'name: "{tool}"'), 1)
        self.assertIn("RAG_IME_AGENT_TOOL_TOKEN", extension)
        self.assertIn("RAG_IME_AGENT_SESSION_MODE", extension)
        self.assertIn("RAG_IME_AGENT_ROOM_BOUND", extension)
        self.assertIn('if (roomBound) return selectedSpecs.filter((spec) => spec.name !== "ask")', extension)
        self.assertIn('sessionMode === "coordinator"', extension)
        self.assertIn("/tool/approval-result", extension)
        self.assertIn('const reviewTitlePrefix = "RAG-IME-REVIEW:"', extension)
        self.assertIn("const memoryParameterSchema", extension)
        self.assertIn('"curation_prepare"', extension)
        self.assertIn("parameterSchema: memoryParameterSchema", extension)
        self.assertIn("parameterSchema: roleBookParameterSchema", extension)
        for operation in (
            "remember_preview",
            "correct_preview",
            "forget_preview",
            "remember_apply",
            "correct_apply",
            "forget_apply",
            "governance_rollback",
            "propose_revision",
        ):
            self.assertIn(f'"{operation}"', extension)
        self.assertIn('"timelines"', extension)
        self.assertIn('"evidence"', extension)
        self.assertNotIn('enum: ["apps", "books", "atoms", "tags", "phrases", "groups", "negative"]', extension)
        self.assertIn("result.reviewRequired === true", extension)
        self.assertIn("resolvedReviewRunIds.has(runId)", extension)
        self.assertIn('executionMode: spec.executionMode ?? "sequential"', extension)
        for read_only_tool in (
            "overview",
            "knowledge",
            "ls",
            "read",
            "grep",
            "find",
        ):
            declaration = extension.index(f'name: "{read_only_tool}"')
            next_tool = extension.find("\n  {", declaration + 1)
            tool_block = extension[
                declaration : next_tool if next_tool >= 0 else len(extension)
            ]
            self.assertIn('executionMode: "parallel"', tool_block)
        for stateful_tool in (
            "memory",
            "todo",
            "workspace_patch",
            "agent_goal",
            "workspace_lsp",
            "edit",
            "write",
            "bash",
            "workspace_job",
        ):
            declaration = extension.index(f'name: "{stateful_tool}"')
            next_tool = extension.find("\n  {", declaration + 1)
            tool_block = extension[
                declaration : next_tool if next_tool >= 0 else len(extension)
            ]
            self.assertNotIn('executionMode: "parallel"', tool_block)
        self.assertIn("class GatewayToolError extends Error", extension)
        self.assertIn("recentNonRetryableFailures", extension)
        self.assertIn("同一工具与参数刚刚已被判定为不可重试", extension)
        self.assertIn(
            'operations: ["init", "start", "done", "drop", "block", "unblock", "append", "view", "rm"]',
            extension,
        )
        self.assertIn('operations: ["list", "confirm_setup", "update", "pause", "resume", "complete", "cancel"]', extension)
        self.assertIn('error.errorCode === "workflow_gate_closed"', extension)
        self.assertIn('requiredAction: "review_workflow_state"', extension)
        self.assertIn(
            "这是当前 Session 唯一的任务状态，不是用户的长期记忆或每日规划，也不构成额外执行许可。",
            extension,
        )
        self.assertNotIn("wait for user approval before calling edit", extension)
        for gateway_name in (
            "workspace_list",
            "workspace_read",
            "workspace_search",
            "workspace_lsp",
            "workspace_edit",
            "workspace_write",
            "workspace_shell",
            "workspace_job",
        ):
            self.assertIn(f'gatewayName: "{gateway_name}"', extension)
        self.assertIn("gatewayParamsFor(spec, params)", extension)
        self.assertIn("const maxInlineToolResultBytes = 24 * 1024", extension)
        self.assertIn('const toolOutputPrefix = "tool-output://"', extension)
        self.assertIn("function boundedToolResult(", extension)
        self.assertIn("function readStoredToolOutput(", extension)
        self.assertIn("fullOutputRef", extension)
        self.assertIn("writeFileSync(filePath, body, { mode: 0o600 })", extension)
        self.assertIn('spec.name === "read"', extension)
        self.assertIn('{ required: ["resourceRef"] }', extension)
        self.assertIn("selectorCursor: params.selectorCursor", extension)
        self.assertIn("resourceRef,", extension)
        self.assertIn('required: ["path", "resourceRevision", "edits"]', extension)
        self.assertIn('required: ["path", "resourceRevision", "content"]', extension)
        self.assertIn("resourceRevision: params.resourceRevision", extension)
        self.assertIn('todoTask: { type: "string", minLength: 1, maxLength: 240 }', extension)
        self.assertIn("主持伙伴必须按验收条件核对结果", extension)

    def test_retired_room_operations_cannot_reenter_through_ime_agents(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class _Collaboration:
            def send_room_intercom(self, session_id, payload):
                calls.append((session_id, dict(payload)))
                return {"ok": True, "message": {"id": "room-message:1"}}

            def list_room_intercom(self, session_id, payload):
                return {"ok": True, "sessionId": session_id, "items": [], **dict(payload)}

            def assign_room_work(self, session_id, payload):
                calls.append((session_id, dict(payload)))
                return {"ok": True, "work": {"id": "room-work:1"}}

        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=self.facade,
            collaboration=_Collaboration(),
        )
        for operation in ("room_send", "room_assign"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    ValueError,
                    "unsupported agents operation",
                ):
                    gateway.execute(
                        self._tool_call(
                            "agents",
                            operation,
                            content="retired",
                        )
                    )
        self.assertEqual(calls, [])

    def test_agent_can_create_validate_and_propose_but_cannot_apply_a_plugin(self) -> None:
        calls: list[tuple[str, object]] = []

        class _Extensions:
            def list(self):
                return {"ok": True, "items": []}

            def catalog(self):
                return {"ok": True, "items": []}

            def create_draft(self, payload):
                calls.append(("create", dict(payload)))
                return {"ok": True, "draft": {"sourcePath": "/managed/inbox/draft-1"}}

            def validate(self, payload):
                calls.append(("validate", dict(payload)))
                return {"ok": True, "validationToken": "validation-1"}

            def preview(self, payload):
                calls.append(("preview", dict(payload)))
                return {"ok": True, "proposalId": "proposal-1", "requiredConfirm": "apply"}

        self.gateway.extensions = _Extensions()
        draft = self.gateway.execute(
            self._tool_call(
                "plugins",
                "create_draft",
                draftId="draft-1",
                manifest={"id": "log-helper"},
                files={"index.ts": "export default function () {}"},
            )
        )
        validation = self.gateway.execute(
            self._tool_call(
                "plugins",
                "validate",
                sourcePath=draft["result"]["draft"]["sourcePath"],
            )
        )
        proposal = self.gateway.execute(
            self._tool_call(
                "plugins",
                "propose_install",
                validationToken=validation["result"]["validationToken"],
                enable=True,
            )
        )

        self.assertEqual(proposal["result"]["proposalId"], "proposal-1")
        self.assertEqual(
            calls[-1][1],
            {"action": "install", "validationToken": "validation-1", "enable": True},
        )
        plugin_manifest = next(
            item for item in self.gateway.manifests()["items"] if item["id"] == "plugins"
        )
        self.assertNotIn("apply", plugin_manifest["operations"])

    def test_agent_schedule_requires_approval_and_applies_the_bound_preview(self) -> None:
        calls: list[tuple[str, object]] = []

        class _Scheduling:
            def preview_wake_schedule(self, payload, *, requested_by_session_id=""):
                calls.append(("preview", requested_by_session_id))
                return {
                    "ok": True,
                    "schedule": {
                        **dict(payload),
                        "title": "明早复盘",
                        "targetDisplayName": "当前线程",
                        "targetType": "session",
                        "targetSessionId": requested_by_session_id,
                        "targetRoleId": "",
                        "targetRoleVersion": "",
                        "planningTaskId": "",
                        "timezone": "Asia/Shanghai",
                        "recurrenceKind": "once",
                        "recurrenceInterval": 1,
                        "maxRuns": 1,
                    },
                }

            def create_wake_schedule(self, payload, *, created_by_session_id="", require_confirmation=True):
                calls.append(("create", dict(payload)))
                self.created_by_session_id = created_by_session_id
                self.require_confirmation = require_confirmation
                return {
                    "ok": True,
                    "schedule": {"id": "wake:1", "title": payload["title"], "status": "scheduled"},
                }

            def list_wake_schedules(self, payload):
                return {"ok": True, "schedulerActive": True, "items": []}

        scheduling = _Scheduling()
        self.gateway.scheduling = scheduling
        listed = self.gateway.execute(
            self._tool_call("agent_schedule", "list")
        )["result"]
        prepared = self.gateway.execute(
            self._tool_call(
                "agent_schedule",
                "schedule",
                title="明早复盘",
                instruction="整理今天的结果",
                targetType="session",
                targetSessionId=self.session["id"],
                wakeAtMs=1_900_000_000_000,
            )
        )["result"]

        self.assertTrue(listed["schedulerActive"])
        self.assertTrue(prepared["approvalRequired"])
        self.assertEqual(prepared["approval"]["riskLevel"], "R2")
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)

        self.assertTrue(receipt["mutationApplied"])
        self.assertEqual(receipt["schedule"]["id"], "wake:1")
        self.assertEqual(scheduling.created_by_session_id, self.session["id"])
        self.assertFalse(scheduling.require_confirmation)

    def test_workspace_lsp_readonly_and_governed_writes_use_canonical_gateway(self) -> None:
        workspace = Path(self.tmp.name) / "workspace-lsp"
        workspace.mkdir()
        target = workspace / "main.py"
        target.write_text("foo = 1\n", encoding="utf-8")

        class _LspHarness:
            def __init__(self) -> None:
                self.read_calls = []
                self.apply_calls = []

            def lsp_status(self, session, args):
                self.read_calls.append(("status", dict(args)))
                return {
                    "schemaVersion": "rag-ime.workspace-lsp-status.v1",
                    "runtimeInstanceId": "workspace-lsp-00000000000000000000000000000001",
                    "runtimeEpoch": 7,
                    "observedAtMs": 1_000,
                    "heartbeatExpiresAtMs": 31_000,
                    "current": True,
                    "summary": "fake LSP available",
                    "state": "available",
                    "roots": [],
                }

            def lsp_read(self, session, operation, args):
                self.read_calls.append((operation, dict(args)))
                return {
                    "schemaVersion": "rag-ime.workspace-lsp-result.v1",
                    "summary": "fake readonly result",
                    "operation": operation,
                    "root": str(workspace),
                    "server": "fake",
                    "items": [],
                }

            def prepare_lsp_mutation(self, session, operation, args):
                return {"operation": operation, "args": dict(args)}

            def lsp_mutation_preview(self, prepared):
                return {
                    "title": "确认重命名符号",
                    "summary": "重命名符号将修改 1 个工作区文件",
                    "operationLabel": "重命名符号",
                    "changes": [
                        {
                            "label": "main.py",
                            "before": "foo = 1",
                            "after": "bar = 1",
                        }
                    ],
                    "actionPayload": {
                        "path": str(target),
                        "newName": prepared["args"]["newName"],
                        "files": [{"path": str(target), "content": "bar = 1\n"}],
                    },
                    "baseState": {
                        "workspaceRoot": str(workspace),
                        "workspaceRootSha256": "a" * 64,
                        "server": "fake",
                        "files": [],
                    },
                }

            def apply_lsp_mutation(
                self,
                session,
                operation,
                action_payload,
                base_state,
            ):
                self.apply_calls.append((operation, dict(action_payload), dict(base_state)))
                preimage = target.read_bytes()
                preimage_sha256 = hashlib.sha256(preimage).hexdigest()
                target.write_text(
                    str(action_payload["files"][0]["content"]),
                    encoding="utf-8",
                )
                postimage_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
                return {
                    "schemaVersion": "rag-ime.workspace-lsp-mutation-receipt.v1",
                    "mutationApplied": True,
                    "summary": "workspace_lsp 已修改 1 个文件",
                    "operation": operation,
                    "root": str(workspace),
                    "server": "fake",
                    "changedFiles": [
                        {
                            "path": str(target),
                            "preimageSha256": preimage_sha256,
                            "postimageSha256": postimage_sha256,
                        }
                    ],
                    **(
                        {
                            "referencesEvidence": {
                                "root": str(workspace),
                                "path": str(target),
                                "relativePath": "main.py",
                                "line": 1,
                                "column": 1,
                                "server": "fake",
                                "resourceRevision": "sha256:" + preimage_sha256,
                                "preimageSha256": preimage_sha256,
                                "count": 0,
                                "truncated": False,
                                "items": [],
                            }
                        }
                        if operation == "rename"
                        else {}
                    ),
                    "undoAvailable": False,
                }

        harness = _LspHarness()
        gateway = ControlToolGateway(
            sessions=self.store,
            management=self.management,
            core=_Core(),
            project="wisdom-weasel-rag-ime",
            facade=_Facade(),
            workspace_harness=harness,
        )
        readonly = self.store.create(
            title="readonly LSP",
            mode="coordinator",
            execution_mode="read_only",
            workspace_roots=[str(workspace)],
            created_at_ms=30,
        )
        target_manifests = gateway._manifest_items(
            readonly,
            include_runtime_projection=True,
        )
        lsp_capability = next(
            item for item in target_manifests if item["id"] == "workspace_lsp"
        )
        authoritative = lsp_capability["runtimeProjection"]
        self.assertTrue(authoritative["current"])
        self.assertEqual(authoritative["runtimeEpoch"], 7)
        self.assertEqual(authoritative["heartbeatExpiresAtMs"], 31_000)

        status = gateway.execute(
            {
                **self._tool_call("workspace_lsp", "status"),
                "sessionId": readonly["id"],
            }
        )["result"]
        hover = gateway.execute(
            {
                **self._tool_call(
                    "workspace_lsp",
                    "hover",
                    path=str(target),
                    line=1,
                    column=1,
                ),
                "sessionId": readonly["id"],
            }
        )["result"]
        self.assertEqual(status["state"], "available")
        self.assertEqual(hover["operation"], "hover")
        self.assertEqual(
            self.store.list_approvals(session_id=str(readonly["id"])),
            [],
        )
        with self.assertRaisesRegex(ValueError, "not enabled|read-only"):
            gateway.execute(
                {
                    **self._tool_call(
                        "workspace_lsp",
                        "rename",
                        path=str(target),
                        line=1,
                        column=1,
                        newName="bar",
                    ),
                    "sessionId": readonly["id"],
                }
            )
        self.assertEqual(
            self.store.list_approvals(session_id=str(readonly["id"])),
            [],
        )

        governed = self.store.create(
            title="governed LSP",
            mode="coordinator",
            workspace_roots=[str(workspace)],
            created_at_ms=31,
        )
        self._start_todo(str(governed["id"]))
        pending = gateway.execute(
            {
                **self._tool_call(
                    "workspace_lsp",
                    "rename",
                    path=str(target),
                    line=1,
                    column=1,
                    newName="bar",
                ),
                "sessionId": governed["id"],
            }
        )["result"]
        self.assertTrue(pending["approvalRequired"])
        self.assertEqual(pending["approval"]["riskLevel"], "R2")
        self.assertEqual(target.read_text(encoding="utf-8"), "foo = 1\n")
        approval = pending["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = gateway.apply_approval(decided)
        self.assertTrue(receipt["mutationApplied"])
        self.assertEqual(receipt["toolId"], "workspace_lsp")
        self.assertEqual(target.read_text(encoding="utf-8"), "bar = 1\n")
        self.assertEqual(len(harness.apply_calls), 1)

    def _call(self, operation: str, **args):
        return self._tool_call("memory", operation, **args)

    def _tool_call(self, tool: str, operation: str, **args):
        return {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": self.session["id"],
            "tool": tool,
            "toolCallId": "tool:1",
            "args": {"op": operation, **args},
        }

    def _start_todo(self, session_id: str) -> dict[str, object]:
        task = "执行工作区变更"
        self.store.mutate_agent_todo(
            session_id,
            {
                "op": "init",
                "phase": "受控工作区执行",
                "items": [task],
            },
            actor="test-user",
        )
        return self.store.mutate_agent_todo(
            session_id,
            {"op": "start", "task": task},
            actor="test-user",
        )["todo"]


if __name__ == "__main__":
    unittest.main()
