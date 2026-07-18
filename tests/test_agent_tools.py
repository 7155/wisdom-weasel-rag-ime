from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.agent_workspace import WorkspaceHarness, WorkspaceHarnessError


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
                    "pendingSourceCount": 0,
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
            "source": {"bundleHash": "sha256:bundle", "eventCount": 7},
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
        memory = next(item for item in manifests if item["name"] == "ime_memory")
        parameters = memory["parameters"]
        branches = parameters["oneOf"]
        by_operation = {
            branch["properties"]["op"]["const"]: branch
            for branch in branches
        }

        self.assertIn("curation_prepare", by_operation)
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
            ["incremental", "global"],
        )
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
        self.assertIn("Session 启动快照只在首轮注入一次", memory["description"])
        self.assertIn("Timeline 不能单独证明稳定事实", memory["description"])
        self.assertIn("无事实问题", memory["description"])
        self.assertIn("失败回执", memory["description"])
        self.assertIn("禁止原样复制长输入", memory["description"])
        self.assertNotIn("changes", str(parameters))

        role_book = next(
            item for item in manifests if item["name"] == "agent_role_book"
        )
        self.assertIn("随 Session 固定版本注入系统提示词", role_book["description"])
        self.assertIn("propose_revision 只保存 draft", role_book["description"])

    def test_runtime_knowledge_and_plan_tools_keep_static_and_backend_schemas_aligned(self) -> None:
        manifests = self.gateway.runtime_manifests(self.session)
        knowledge = next(item for item in manifests if item["name"] == "ime_knowledge")
        plan = next(item for item in manifests if item["name"] == "agent_plan")

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

        plan_branches = {
            branch["properties"]["op"]["const"]: branch
            for branch in plan["parameters"]["oneOf"]
        }
        self.assertCountEqual(
            plan_branches["update"]["anyOf"],
            [{"required": ["itemId"]}, {"required": ["title"]}],
        )
        self.assertFalse(plan_branches["update"]["additionalProperties"])

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
            allowed_tools=["ime_overview"],
        )
        manifests = self.gateway.manifests(session_id=str(self.session["id"]))
        overview = next(item for item in manifests["items"] if item["id"] == "ime_overview")
        memory = next(item for item in manifests["items"] if item["id"] == "ime_memory")

        self.assertTrue(overview["enabled"])
        self.assertFalse(memory["enabled"])
        self.assertEqual(manifests["sessionPolicy"]["allowedTools"], ["ime_overview"])
        self.gateway.execute(self._tool_call("ime_overview", "status"))
        with self.assertRaisesRegex(ValueError, "tool profile"):
            self.gateway.execute(self._call("catalog"))

    def test_manifests_expose_workspace_shell_only_for_coordinator_sessions(self) -> None:
        manifests = self.gateway.manifests()["items"]
        self.assertEqual(
            [manifest["id"] for manifest in manifests],
            [
                "ime_overview",
                "ime_input",
                "ime_voice",
                "ime_planning",
                "agent_schedule",
                "ime_memory",
                "agent_role_book",
                "ime_knowledge",
                "ime_models",
                "ime_runtime",
                "ime_configuration",
                "ime_agents",
                "ime_browser",
                "agent_plan",
                "ime_plugins",
                "desktop_semantic",
                "workspace_list",
                "workspace_read",
                "workspace_search",
                "workspace_patch",
                "workspace_shell",
            ],
        )
        planning = next(manifest for manifest in manifests if manifest["id"] == "ime_planning")
        self.assertEqual(planning["riskLevel"], "R1")
        self.assertEqual(
            planning["operationRisks"],
            {"dashboard": "R0", "task_action": "R1", "undo_task_event": "R1"},
        )
        memory = next(manifest for manifest in manifests if manifest["id"] == "ime_memory")
        self.assertEqual(memory["riskLevel"], "R1")
        self.assertEqual(memory["operationRisks"]["maintenance_preview"], "R0")
        self.assertEqual(memory["operationRisks"]["maintenance_apply"], "R1")
        self.assertEqual(memory["operationRisks"]["maintenance_rollback"], "R1")
        knowledge = next(manifest for manifest in manifests if manifest["id"] == "ime_knowledge")
        self.assertEqual(
            knowledge["operations"],
            ["list_bases", "search", "find", "open", "status"],
        )
        input_tool = next(manifest for manifest in manifests if manifest["id"] == "ime_input")
        self.assertEqual(input_tool["riskLevel"], "R1")
        self.assertEqual(input_tool["operationRisks"]["preview_settings"], "R0")
        self.assertEqual(input_tool["operationRisks"]["apply_settings"], "R1")
        self.assertEqual(input_tool["operationRisks"]["lexicon_apply"], "R1")
        voice_tool = next(manifest for manifest in manifests if manifest["id"] == "ime_voice")
        self.assertEqual(voice_tool["riskLevel"], "R1")
        self.assertEqual(voice_tool["operationRisks"]["provider_preview"], "R0")
        self.assertEqual(voice_tool["operationRisks"]["provider_apply"], "R1")
        self.assertEqual(voice_tool["operationRisks"]["provider_rollback"], "R1")
        runtime_tool = next(manifest for manifest in manifests if manifest["id"] == "ime_runtime")
        self.assertEqual(runtime_tool["riskLevel"], "R2")
        self.assertEqual(runtime_tool["operationRisks"]["diagnose"], "R0")
        self.assertEqual(runtime_tool["operationRisks"]["pause_ai"], "R1")
        self.assertEqual(runtime_tool["operationRisks"]["restart_sidecar"], "R2")
        self.assertEqual(runtime_tool["operationRisks"]["restart_predictor"], "R2")
        model_tool = next(manifest for manifest in manifests if manifest["id"] == "ime_models")
        self.assertEqual(model_tool["riskLevel"], "R1")
        self.assertEqual(model_tool["operationRisks"]["profiles"], "R0")
        self.assertEqual(model_tool["operationRisks"]["profile_apply"], "R1")
        self.assertEqual(model_tool["operationRisks"]["profile_rollback"], "R1")
        configuration_tool = next(
            manifest for manifest in manifests if manifest["id"] == "ime_configuration"
        )
        self.assertEqual(configuration_tool["riskLevel"], "R3")
        self.assertEqual(configuration_tool["operationRisks"]["export_preview"], "R0")
        self.assertEqual(configuration_tool["operationRisks"]["export"], "R1")
        self.assertEqual(configuration_tool["operationRisks"]["restore_preview"], "R0")
        self.assertEqual(configuration_tool["operationRisks"]["restore_apply"], "R3")
        browser_tool = next(manifest for manifest in manifests if manifest["id"] == "ime_browser")
        self.assertEqual(browser_tool["riskLevel"], "R1")
        self.assertEqual(browser_tool["operationRisks"]["snapshot"], "R0")
        self.assertEqual(browser_tool["operationRisks"]["screenshot"], "R0")
        self.assertEqual(browser_tool["operationRisks"]["navigate"], "R1")
        self.assertEqual(browser_tool["operationRisks"]["type"], "R1")
        workspace_shell = next(
            manifest for manifest in manifests if manifest["id"] == "workspace_shell"
        )
        self.assertEqual(workspace_shell["sessionModes"], ["coordinator"])
        self.assertEqual(workspace_shell["operationRisks"], {"run": "R2"})
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
                    "ime_input",
                    "ime_voice",
                    "ime_planning",
                    "agent_schedule",
                    "ime_memory",
                    "ime_models",
                    "ime_runtime",
                    "ime_configuration",
                    "ime_browser",
                    "desktop_semantic",
                    "workspace_patch",
                    "workspace_shell",
                }
            )
        )
        assistant_call = self._tool_call("workspace_list", "list")
        with self.assertRaisesRegex(ValueError, "session mode"):
            self.gateway.execute(assistant_call)

    def test_agent_plan_is_session_local_and_readonly_profile_safe(self) -> None:
        created = self.gateway.execute(
            self._tool_call(
                "agent_plan",
                "update",
                title="验证权限模式",
                status="pending",
            )
        )["result"]
        item_id = created["event"]["itemId"]

        self.assertEqual(created["presentationKind"], "task_plan")
        self.assertEqual(created["items"][0]["title"], "验证权限模式")
        self.session = self.store.set_runtime_policy(
            str(self.session["id"]),
            mode="assistant",
            tool_profile_version="subagent-readonly-v1",
            allowed_tools=["agent_plan"],
        )
        updated = self.gateway.execute(
            self._tool_call(
                "agent_plan",
                "update",
                itemId=item_id,
                status="in_progress",
            )
        )["result"]
        self.assertEqual(updated["plan"]["counts"]["inProgress"], 1)

        other = self.store.create(title="other session", created_at_ms=2)
        other_plan = self.gateway.execute(
            {
                **self._tool_call("agent_plan", "list"),
                "sessionId": other["id"],
            }
        )["result"]
        self.assertEqual(other_plan["items"], [])

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
                "ime_planning",
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
        self.assertEqual(target.read_text(encoding="utf-8"), "print('after')\n")

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

    def test_task_action_requires_native_approval_then_returns_rollback_receipt(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "ime_planning",
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
                "ime_planning",
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
            self._tool_call("ime_input", "preview_settings", changes=changes)
        )["result"]
        self.assertEqual(preview["changeCount"], 2)
        self.assertTrue(preview["approvalRequiredForApply"])

        prepared = self.gateway.execute(
            self._tool_call("ime_input", "apply_settings", changes=changes)
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
                "ime_input",
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
                "ime_input",
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
            self._tool_call("ime_input", "lexicon_review")
        )["result"]
        review_key = review["entries"][0]["reviewKey"]
        self.assertNotIn("must-not-reach-pi", str(review))

        prepared = self.gateway.execute(
            self._tool_call(
                "ime_input",
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
                "ime_input",
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
            self._tool_call("ime_runtime", "pause_ai")
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
            self._tool_call("ime_runtime", "resume_ai")
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
            self._tool_call("ime_runtime", "restart_predictor")
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
            self._tool_call("ime_runtime", "restart_sidecar")
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
            self._tool_call("ime_runtime", "restart_predictor")
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
            self._tool_call("ime_models", "profiles")
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
            self._tool_call("ime_models", "profile_preview", **requested)
        )["result"]
        self.assertEqual(preview["restartComponent"], "predictor")
        self.assertTrue(preview["secretsPreserved"])
        self.assertEqual(len(preview["changes"]), 3)

        prepared = self.gateway.execute(
            self._tool_call("ime_models", "profile_apply", **requested)
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
                "ime_models",
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
                "ime_voice",
                "provider_preview",
                provider="realtime_websocket",
            )
        )["result"]
        self.assertTrue(preview["approvalRequiredForApply"])
        self.assertTrue(preview["secretsPreserved"])

        prepared = self.gateway.execute(
            self._tool_call(
                "ime_voice",
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
                "ime_voice",
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
                    "ime_voice",
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
            self._tool_call("ime_models", "profile_apply", **requested)
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
                    "ime_models",
                    "profile_preview",
                    **requested,
                    apiKey="must-not-enter-pi-tool",
                )
            )

    def test_model_profile_apply_fails_closed_after_configuration_change(self) -> None:
        prepared = self.gateway.execute(
            self._tool_call(
                "ime_models",
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
            self._tool_call("ime_configuration", "export_preview")
        )["result"]
        self.assertFalse(preview["secretsIncluded"])
        self.assertTrue(preview["approvalRequiredForExport"])

        prepared = self.gateway.execute(
            self._tool_call("ime_configuration", "export")
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
                "ime_configuration",
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
                "ime_configuration",
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
                "ime_planning",
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
                "ime_planning",
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
                    "ime_planning",
                    "undo_task_event",
                    eventId=action_receipt["taskEventId"],
                )
            )

    def test_overview_planning_document_knowledge_and_models_use_scoped_services(self) -> None:
        overview = self.gateway.execute(self._tool_call("ime_overview", "status"))["result"]
        planning = self.gateway.execute(self._tool_call("ime_planning", "dashboard"))["result"]
        bases = self.gateway.execute(self._tool_call("ime_knowledge", "list_bases"))["result"]
        knowledge = self.gateway.execute(
            self._tool_call(
                "ime_knowledge",
                "search",
                kbId="kb:project-docs",
                query="为什么普通生成不经过 Pi",
                topK=6,
            )
        )["result"]
        models = self.gateway.execute(self._tool_call("ime_models", "status"))["result"]

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
                "ime_knowledge",
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
            self._tool_call("ime_knowledge", "list_bases"),
            self._tool_call(
                "ime_knowledge",
                "search",
                kbId="kb:project-docs",
                query="Agent Loop",
            ),
            self._tool_call(
                "ime_knowledge",
                "find",
                kbId="kb:project-docs",
                fileId="file:1",
                patterns=["热路径"],
            ),
            self._tool_call(
                "ime_knowledge",
                "open",
                kbId="kb:project-docs",
                fileId="file:1",
                line=41,
                windowSize=20,
            ),
            self._tool_call("ime_knowledge", "status"),
        ]

        for call in calls:
            result = self.gateway.execute(call)["result"]
            self.assertIsInstance(result, dict)
        self.assertEqual(
            ["list_bases", "search", "find", "open", "status"],
            [operation for operation, _payload in self.knowledge.calls[-5:]],
        )
        manifest = next(
            item for item in self.gateway.manifests()["items"] if item["id"] == "ime_knowledge"
        )
        self.assertEqual(("list_bases", "search", "find", "open", "status"), tuple(manifest["operations"]))

    def test_write_operations_knowledge_management_and_secrets_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not agent-manageable"):
            self.gateway.execute(
                self._tool_call(
                    "ime_input",
                    "apply_settings",
                    changes=[{"key": "privacy.debugIncludeText", "value": True}],
                )
            )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.gateway.execute(self._tool_call("ime_knowledge", "import", kbId="kb:project-docs"))
        audit = self.gateway.execute(self._tool_call("ime_configuration", "audit"))["result"]
        lexicon = self.gateway.execute(self._tool_call("ime_input", "lexicon_review"))["result"]
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

        status = gateway.execute(self._tool_call("ime_knowledge", "status"))["result"]
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "knowledge_client_not_configured")
        with self.assertRaisesRegex(ValueError, "document knowledge library is unavailable"):
            gateway.execute(
                self._tool_call(
                    "ime_knowledge",
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
            "node:fs",
            "node:child_process",
            "registerCommand(",
            "execSync(",
            "spawn(",
        ]
        for marker in forbidden:
            self.assertNotIn(marker, extension)
        for tool in (
            "ime_overview",
            "ime_input",
            "ime_voice",
            "ime_planning",
            "agent_schedule",
            "ime_memory",
            "agent_role_book",
            "ime_knowledge",
            "ime_models",
            "ime_runtime",
            "ime_configuration",
            "ime_agents",
            "agent_plan",
            "workspace_list",
            "workspace_read",
            "workspace_search",
            "workspace_patch",
            "workspace_shell",
        ):
            self.assertEqual(extension.count(f'name: "{tool}"'), 1)
        self.assertIn("RAG_IME_AGENT_TOOL_TOKEN", extension)
        self.assertIn("RAG_IME_AGENT_SESSION_MODE", extension)
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

    def test_room_tool_uses_trusted_session_identity_and_drops_forged_source_fields(self) -> None:
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
        response = gateway.execute(
            self._tool_call(
                "ime_agents",
                "room_send",
                targetParticipantId="participant:reviewer",
                clientMessageId="turn-7-message-1",
                content="请复核这条结论",
                sourceSessionId="forged-session",
                sourceParticipantId="forged-participant",
            )
        )

        self.assertTrue(response["result"]["ok"])
        self.assertEqual(calls[0][0], self.session["id"])
        self.assertNotIn("sourceSessionId", calls[0][1])
        self.assertNotIn("sourceParticipantId", calls[0][1])
        self.assertEqual(calls[0][1]["kind"], "send")

        assignment = gateway.execute(
            self._tool_call(
                "ime_agents",
                "room_assign",
                targetParticipantId="participant:reviewer",
                clientMessageId="turn-7-work-1",
                objective="复核网关边界",
                expectedOutput="证据与结论",
                acceptanceCriteria=["包含测试回执"],
                sourceSessionId="forged-session",
            )
        )
        self.assertTrue(assignment["result"]["ok"])
        self.assertEqual(calls[1][0], self.session["id"])
        self.assertNotIn("sourceSessionId", calls[1][1])

    def test_agent_can_create_validate_and_propose_but_cannot_apply_a_plugin(self) -> None:
        calls: list[tuple[str, object]] = []

        class _Extensions:
            def list(self):
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
                "ime_plugins",
                "create_draft",
                draftId="draft-1",
                manifest={"id": "log-helper"},
                files={"index.ts": "export default function () {}"},
            )
        )
        validation = self.gateway.execute(
            self._tool_call(
                "ime_plugins",
                "validate",
                sourcePath=draft["result"]["draft"]["sourcePath"],
            )
        )
        proposal = self.gateway.execute(
            self._tool_call(
                "ime_plugins",
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
            item for item in self.gateway.manifests()["items"] if item["id"] == "ime_plugins"
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

    def _call(self, operation: str, **args):
        return self._tool_call("ime_memory", operation, **args)

    def _tool_call(self, tool: str, operation: str, **args):
        return {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": self.session["id"],
            "tool": tool,
            "toolCallId": "tool:1",
            "args": {"op": operation, **args},
        }


if __name__ == "__main__":
    unittest.main()
