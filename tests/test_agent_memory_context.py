from __future__ import annotations

import unittest

from rag_ime.agent_memory_context import (
    AgentMemoryContextService,
    _session_todo_projection,
)


class _TodoSessions:
    def agent_todo(self, session_id: str) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-todo.v1",
            "sessionId": session_id,
            "phases": [
                {
                    "name": "实现",
                    "tasks": [
                        {"content": "修复首次记忆召回", "status": "in_progress"},
                        {"content": "运行真实数据验收", "status": "pending"},
                        {"content": "已经完成的旧步骤", "status": "completed"},
                    ],
                }
            ],
        }


class _ContextSessions:
    db_path = ""

    def get(self, session_id: str) -> dict[str, object]:
        return {"id": session_id, "roleId": "companion-present-v1"}

    def agent_todo(self, _session_id: str) -> dict[str, object]:
        return {"phases": []}


class _ContextRuntime:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []
        self.materialize_calls = 0

    def expire_legacy_memory_bootstrap(self, *_args: object, **_kwargs: object) -> int:
        return 0

    def active_item(self, *_args: object, **_kwargs: object) -> None:
        return None

    def active_dedupe_key(self, *_args: object, **_kwargs: object) -> str:
        return ""

    def enqueue(self, **specification: object) -> dict[str, object]:
        self.enqueued.append(dict(specification))
        return {"itemId": "context-item:1"}

    def materialize(self, _session_id: str) -> dict[str, object]:
        self.materialize_calls += 1
        return {"items": []}


class _ContextBootstrap:
    def __init__(self) -> None:
        self.build_calls = 0

    def dedupe_key(self, session_id: str) -> str:
        return f"memory-bootstrap:{session_id}:v3"

    def build(self, session_id: str, **kwargs: object) -> dict[str, object]:
        self.build_calls += 1
        return {
            "session_id": session_id,
            "source_kind": "memory_bootstrap",
            "source_id": "recall:1",
            "title": "记忆",
            "summary": "测试记忆",
            "payload": {"items": []},
            "lane": "fact",
            "lifecycle": "persistent",
            "dedupe_key": str(kwargs.get("trigger") or "first_user_prompt"),
        }


class _ContextTask:
    def resolve(self, _session_id: str) -> dict[str, object]:
        return {"objective": "测试目标"}

    def room_ids(self, _session_id: str) -> list[str]:
        return []

    def trigger(self, _session_id: str) -> str:
        return "first_user_prompt"


class _ContextRuntimeProvider:
    def session_snapshot(self, _session_id: str) -> dict[str, object]:
        return {"messages": []}


class AgentMemoryContextTests(unittest.TestCase):
    def test_todo_owner_projects_only_unfinished_work_into_recall(self) -> None:
        projection = _session_todo_projection(
            _TodoSessions(),
            "agent:memory-evaluation",
        )

        self.assertEqual(
            projection,
            {
                "items": [
                    {"status": "in_progress", "content": "修复首次记忆召回"},
                    {"status": "pending", "content": "运行真实数据验收"},
                ]
            },
        )

    def test_master_switch_blocks_recall_without_erasing_state_and_restores(self) -> None:
        enabled = False
        runtime = _ContextRuntime()
        bootstrap = _ContextBootstrap()
        service = AgentMemoryContextService(
            sessions=_ContextSessions(),
            memory_bootstrap=bootstrap,
            context_runtime=runtime,
            task_context=_ContextTask(),
            runtime_provider=lambda: _ContextRuntimeProvider(),
            memory_enabled_provider=lambda: enabled,
        )
        session = {"id": "session:1"}

        disabled = service.ensure_bootstrap(session, query_text="首问")
        disabled_refresh = service.refresh(
            {"sessionId": "session:1", "queryText": "刷新"}
        )
        self.assertEqual(disabled["status"], "disabled")
        self.assertFalse(disabled["memoryEnabled"])
        self.assertFalse(disabled_refresh["memoryEnabled"])
        self.assertEqual(bootstrap.build_calls, 0)
        self.assertEqual(runtime.enqueued, [])
        self.assertEqual(service.provider_context("session:1"), "")
        self.assertEqual(runtime.materialize_calls, 0)

        enabled = True
        restored = service.ensure_bootstrap(session, query_text="首问")
        self.assertEqual(restored["status"], "ready")
        self.assertEqual(bootstrap.build_calls, 1)
        self.assertEqual(len(runtime.enqueued), 1)


if __name__ == "__main__":
    unittest.main()
