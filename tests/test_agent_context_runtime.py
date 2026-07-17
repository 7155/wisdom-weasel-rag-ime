from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.agent_context_runtime import (
    RUNTIME_PROMPT_ENVELOPE_PREFIX,
    AgentContextRuntime,
    compose_runtime_prompt,
)
from rag_ime.agent_sessions import AgentSessionStore


class AgentContextRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-context-runtime-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        self.session = sessions.create(title="Context runtime test")
        self.session_id = str(self.session["id"])
        self.runtime = AgentContextRuntime(self.db_path)
        self.runtime.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_context_items_are_deduplicated_budgeted_and_consumed_once(self) -> None:
        first = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="room_intercom",
            source_id="message-1",
            lane="room",
            lifecycle="once",
            dedupe_key="room:message-1",
            title="协作消息",
            summary="另一个角色提交了结论",
            payload={"content": "结论正文", "privateToken": "only-for-runtime"},
        )
        repeated = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="room_intercom",
            source_id="message-1",
            lane="room",
            lifecycle="once",
            dedupe_key="room:message-1",
            title="不会重复创建",
        )

        self.assertEqual(first["itemId"], repeated["itemId"])
        materialized = self.runtime.materialize(self.session_id)
        self.assertEqual(materialized["itemIds"], [first["itemId"]])
        self.assertIn("结论正文", str(materialized["prompt"]))
        self.assertIn("<rag_ime_context_items", str(materialized["prompt"]))

        self.runtime.mark_delivered(
            list(materialized["itemIds"]),
            turn_id="turn-1",
        )
        self.assertEqual(self.runtime.materialize(self.session_id)["itemIds"], [])
        item = self.runtime.list_items(self.session_id)[0]
        self.assertEqual(item["status"], "consumed")
        self.assertEqual(item["deliveredTurnId"], "turn-1")
        self.assertNotIn("privateToken", json.dumps(item))

    def test_until_ack_items_reappear_without_duplicate_storage(self) -> None:
        item = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="long_task",
            source_id="research-1",
            lane="status",
            lifecycle="until_ack",
            dedupe_key="research-1:complete",
            title="研究任务已完成",
            payload={"result": "可复核摘要"},
        )
        first = self.runtime.materialize(self.session_id)
        self.runtime.mark_delivered(first["itemIds"], turn_id="turn-1")
        second = self.runtime.materialize(self.session_id)

        self.assertEqual(second["itemIds"], [item["itemId"]])
        acknowledged = self.runtime.acknowledge(self.session_id, str(item["itemId"]))
        self.assertEqual(acknowledged["status"], "acknowledged")
        self.assertEqual(self.runtime.materialize(self.session_id)["itemIds"], [])

    def test_once_delivery_is_reserved_before_runtime_acceptance(self) -> None:
        item = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="memory_bootstrap",
            lane="fact",
            lifecycle="once",
            dedupe_key=f"memory-bootstrap:{self.session_id}:v1",
            title="启动上下文",
            payload={"queryFree": True},
        )

        reserved = self.runtime.materialize_for_delivery(
            self.session_id,
            delivery_id="dispatch:client:one",
        )
        self.assertEqual(reserved["itemIds"], [item["itemId"]])
        self.assertEqual(self.runtime.materialize(self.session_id)["itemIds"], [])
        consumed = self.runtime.list_items(self.session_id, status="consumed")
        self.assertEqual(consumed[0]["deliveredTurnId"], "dispatch:client:one")

        self.runtime.mark_delivered(
            reserved["itemIds"],
            turn_id="turn:accepted",
            expected_delivery_id="dispatch:client:one",
        )
        confirmed = self.runtime.list_items(self.session_id, status="consumed")
        self.assertEqual(confirmed[0]["deliveredTurnId"], "turn:accepted")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE agent_context_items SET updated_at_ms = 0 WHERE item_id = ?",
                (item["itemId"],),
            )
        restarted = AgentContextRuntime(self.db_path)
        restarted.initialize()
        self.assertIsNotNone(
            restarted.item_by_dedupe_key(
                self.session_id,
                f"memory-bootstrap:{self.session_id}:v1",
            )
        )

    def test_trace_is_a_public_dag_without_raw_prompt_or_paths(self) -> None:
        trace_id = self.runtime.begin_trace(self.session_id, source_kind="user")
        input_node = self.runtime.add_trace_node(
            trace_id,
            stage="input",
            label="用户消息",
            source_kind="user",
            summary="/Users/undo/private.txt api_key=secret-value",
            content="不能出现在公开 trace 的原始正文",
        )
        final_node = self.runtime.add_trace_node(
            trace_id,
            stage="runtime_request",
            label="Pi 请求",
            source_kind="gateway",
            parents=[input_node],
            content={"message": "最终运行时正文"},
            metadata={"messageCount": 1, "systemPrompt": "must not leak"},
        )
        self.runtime.finalize_trace(
            trace_id,
            status="accepted",
            turn_id="turn-1",
            final_content="最终运行时正文",
        )

        trace = self.runtime.trace(trace_id)
        self.assertEqual(trace["status"], "accepted")
        self.assertEqual(trace["turnId"], "turn-1")
        self.assertEqual(trace["edges"], [{"source": input_node, "target": final_node}])
        serialized = json.dumps(trace, ensure_ascii=False)
        self.assertNotIn("不能出现在", serialized)
        self.assertNotIn("最终运行时正文", serialized)
        self.assertNotIn("/Users/undo", serialized)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("systemPrompt", serialized)
        self.assertIn("sha256:", serialized)

    def test_runtime_prompt_keeps_context_distinct_from_current_message(self) -> None:
        prompt = compose_runtime_prompt("用户现在的问题", "<context>异步结果</context>")
        self.assertTrue(prompt.startswith(RUNTIME_PROMPT_ENVELOPE_PREFIX))
        envelope = json.loads(prompt.removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX))
        self.assertEqual(envelope["message"], "用户现在的问题")
        self.assertEqual(envelope["transientContext"], "<context>异步结果</context>")

    def test_maintenance_bounds_terminal_payloads_and_trace_history(self) -> None:
        item = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="room_intercom",
            lane="room",
            lifecycle="once",
            title="旧的一次性消息",
            payload={"content": "不应无限占用数据库"},
        )
        materialized = self.runtime.materialize(self.session_id)
        self.runtime.mark_delivered(materialized["itemIds"], turn_id="old-turn")
        trace_id = self.runtime.begin_trace(self.session_id, source_kind="user")
        self.runtime.finalize_trace(trace_id, status="accepted", turn_id="old-turn")

        now_ms = int(time.time() * 1_000)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE agent_context_items SET updated_at_ms = 0 WHERE item_id = ?",
                (item["itemId"],),
            )
            conn.execute(
                """
                UPDATE agent_context_traces
                SET created_at_ms = 0, updated_at_ms = 0
                WHERE trace_id = ?
                """,
                (trace_id,),
            )
            conn.executemany(
                """
                INSERT INTO agent_context_traces(
                    trace_id, session_id, source_kind, status,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'user', 'accepted', ?, ?)
                """,
                [
                    (
                        f"context-trace:bounded-{index:03d}",
                        self.session_id,
                        now_ms + index,
                        now_ms + index,
                    )
                    for index in range(505)
                ],
            )

        restarted = AgentContextRuntime(self.db_path)
        restarted.initialize()
        self.assertEqual(restarted.list_items(self.session_id), [])
        with self.assertRaises(KeyError):
            restarted.trace(trace_id)
        with sqlite3.connect(self.db_path) as conn:
            trace_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_context_traces WHERE session_id = ?",
                    (self.session_id,),
                ).fetchone()[0]
            )
        self.assertEqual(trace_count, 500)


if __name__ == "__main__":
    unittest.main()
