from __future__ import annotations

import unittest

from rag_ime.agent_memory_context import _session_todo_projection


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


if __name__ == "__main__":
    unittest.main()
