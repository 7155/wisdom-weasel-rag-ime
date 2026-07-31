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
    render_context_items,
)
from rag_ime.agent_memory_context_support import recall_messages
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

    def test_recall_window_preserves_original_requirement_with_recent_turns(self) -> None:
        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": "原始需求：完成一个三成员 Room 项目并逐项验证。",
            },
        ]
        for index in range(1, 6):
            messages.extend([
                {
                    "role": "assistant",
                    "content": f"阶段 {index} 已完成。",
                },
                {
                    "role": "user",
                    "content": f"继续阶段 {index + 1}。",
                },
            ])

        recalled = recall_messages(messages)

        self.assertEqual(len(recalled), 8)
        self.assertEqual(
            recalled[0]["text"],
            "原始需求：完成一个三成员 Room 项目并逐项验证。",
        )
        self.assertEqual(recalled[-1]["text"], "继续阶段 6。")
        self.assertNotIn(
            "阶段 1 已完成。",
            [item["text"] for item in recalled],
        )

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
        self.assertIn("## room_intercom: 协作消息", str(materialized["prompt"]))
        self.assertNotIn("privateToken", str(materialized["prompt"]))
        self.assertNotIn("来源类型", str(materialized["prompt"]))
        self.assertNotIn("生命周期", str(materialized["prompt"]))

        self.runtime.mark_delivered(
            list(materialized["itemIds"]),
            turn_id="turn-1",
        )
        self.assertEqual(self.runtime.materialize(self.session_id)["itemIds"], [])
        item = self.runtime.list_items(self.session_id)[0]
        self.assertEqual(item["status"], "consumed")
        self.assertEqual(item["deliveredTurnId"], "turn-1")
        self.assertNotIn("privateToken", json.dumps(item))

    def test_delegated_terminal_result_uses_deduplicated_result_lane(self) -> None:
        notification = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="schedule",
            lane="notification",
            lifecycle="once",
            dedupe_key="schedule:one",
            title="普通提醒",
        )
        batch = {"id": "subagent-batch:one"}
        run = {
            "id": "subagent-run:one",
            "batchId": "subagent-batch:one",
            "childSessionId": "session:child",
            "templateId": "reviewer",
            "templateVersion": "1",
            "task": "核对结果",
            "expectedOutput": "一份可复核报告",
            "acceptanceCriteria": ["引用真实产物", "列出未决风险"],
            "outputSchema": {
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
            "planItemId": "plan-item:one",
            "planItemTitle": "核对子 Agent 证据",
            "state": "completed",
            "result": {
                "summary": "已取得 artifact://one",
                "deliveryStatus": "returned",
                "verificationStatus": "unverified",
                "authority": "evidence_only",
            },
            "error": "",
            "artifact": {"artifactId": "artifact:one"},
            "completedAtMs": 42,
        }

        first = self.runtime.enqueue_delegated_result(
            parent_session_id=self.session_id,
            batch=batch,
            run=run,
        )
        repeated = self.runtime.enqueue_delegated_result(
            parent_session_id=self.session_id,
            batch=batch,
            run=run,
        )
        materialized = self.runtime.materialize(self.session_id)

        self.assertEqual(first["itemId"], repeated["itemId"])
        self.assertEqual(
            materialized["itemIds"],
            [first["itemId"], notification["itemId"]],
        )
        result_item = materialized["items"][0]
        self.assertEqual(result_item["lane"], "result")
        self.assertEqual(result_item["payload"]["deliveryStatus"], "returned")
        self.assertEqual(
            result_item["payload"]["verificationStatus"],
            "unverified",
        )
        self.assertEqual(result_item["payload"]["authority"], "evidence_only")
        self.assertEqual(
            result_item["payload"]["acceptanceCriteria"],
            ["引用真实产物", "列出未决风险"],
        )
        self.assertIn("do not auto-accept", materialized["prompt"])

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

    def test_query_free_legacy_bootstrap_is_expired_before_new_recall(self) -> None:
        legacy = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="memory_bootstrap",
            lane="fact",
            lifecycle="once",
            dedupe_key=f"memory-bootstrap:{self.session_id}:v1",
            title="旧启动快照",
            payload={"queryFree": True},
        )

        expired = self.runtime.expire_legacy_memory_bootstrap(
            self.session_id,
            current_dedupe_key=f"memory-bootstrap:{self.session_id}:v3",
        )

        self.assertEqual(expired, 1)
        items = self.runtime.list_items(self.session_id, status="expired")
        self.assertEqual([item["itemId"] for item in items], [legacy["itemId"]])
        self.assertEqual(self.runtime.materialize(self.session_id)["itemIds"], [])

    def test_persistent_memory_context_is_atomically_superseded(self) -> None:
        original = self.runtime.enqueue(
            session_id=self.session_id,
            source_kind="memory_bootstrap",
            source_id="recall:first",
            lane="fact",
            lifecycle="persistent",
            dedupe_key=f"memory-bootstrap:{self.session_id}:v3",
            title="初始记忆",
            payload={"content": "初始正文"},
        )

        refreshed = self.runtime.replace_active(
            session_id=self.session_id,
            source_kind="memory_bootstrap",
            source_id="recall:compaction",
            lane="fact",
            lifecycle="persistent",
            dedupe_key=f"memory-bootstrap:{self.session_id}:v4:summary",
            title="压缩后记忆",
            payload={"content": "压缩后正文"},
        )

        active = self.runtime.materialize(self.session_id)
        self.assertEqual(active["itemIds"], [refreshed["itemId"]])
        self.assertIn("压缩后正文", active["prompt"])
        self.assertNotIn("初始正文", active["prompt"])
        expired = self.runtime.list_items(self.session_id, status="expired")
        self.assertEqual([item["itemId"] for item in expired], [original["itemId"]])

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
        self.assertEqual(envelope["sessionContext"], "")
        self.assertEqual(envelope["transientContext"], "<context>异步结果</context>")

    def test_session_memory_renders_independent_timeline_as_timeline(self) -> None:
        rendered = render_context_items(
            [
                {
                    "sourceKind": "memory_bootstrap",
                    "payload": {
                        "schemaVersion": "rag-ime.session-memory-recall.v1",
                        "retrieval": {"temporalIntent": True},
                        "items": [
                            {
                                "sourceId": "timeline:2026-07-18",
                                "sourceType": "memory_timeline",
                                "title": "2026-07-18 活动时间线",
                                "text": "完成 Timeline 独立索引。",
                            },
                            {
                                "sourceId": "atom:preference",
                                "sourceType": "memory_atom",
                                "title": "偏好",
                                "text": "解释先给结论。",
                            },
                        ],
                    },
                }
            ]
        )

        self.assertIn("### 近期时间线", rendered)
        self.assertIn("#### 2026-07-18 活动时间线", rendered)
        self.assertIn("完成 Timeline 独立索引。", rendered)
        self.assertIn("### 事实与偏好", rendered)
        self.assertIn("- **偏好**: 解释先给结论。", rendered)
        self.assertNotIn("- **2026-07-18 活动时间线**", rendered)

    def test_session_memory_does_not_repeat_book_title_in_its_body(self) -> None:
        rendered = render_context_items(
            [
                {
                    "sourceKind": "memory_bootstrap",
                    "payload": {
                        "schemaVersion": "rag-ime.session-memory-recall.v1",
                        "retrieval": {"temporalIntent": False},
                        "items": [
                            {
                                "sourceId": "book:delivery",
                                "sourceType": "memory_book",
                                "title": "代码任务交付偏好",
                                "text": "代码任务交付偏好 先读测试，再做最小改动。",
                            }
                        ],
                    },
                }
            ]
        )

        self.assertIn("#### 代码任务交付偏好", rendered)
        self.assertIn("先读测试，再做最小改动。", rendered)
        self.assertEqual(rendered.count("代码任务交付偏好"), 1)

    def test_compaction_history_cannot_override_current_task_or_plan(self) -> None:
        rendered = render_context_items(
            [
                {
                    "sourceKind": "memory_bootstrap",
                    "payload": {
                        "schemaVersion": "rag-ime.session-memory-recall.v1",
                        "retrieval": {"temporalIntent": False},
                        "compactionRecovery": {
                            "schemaVersion": (
                                "rag-ime.agent-compaction-recovery.v2"
                            ),
                            "summaryPresent": True,
                            "summarySha256": "d" * 64,
                            "summaryChars": 321,
                            "skills": [],
                            "tools": [],
                        },
                        "task": {
                            "objective": "只执行当前修复",
                            "acceptanceCriteria": ["CURRENT-AC"],
                        },
                        "plan": [
                            {
                                "status": "completed",
                                "title": "CURRENT-PLAN",
                            }
                        ],
                        "items": [],
                    },
                }
            ]
        )

        self.assertIn(
            "## 压缩恢复回执（非任务状态）",
            rendered,
        )
        self.assertIn("Pi 的压缩摘要已经作为会话历史消息提供", rendered)
        self.assertIn("sha256:" + "d" * 64, rendered)
        self.assertIn("321 字符", rendered)
        self.assertIn("## 当前任务（本轮权威投影）", rendered)
        self.assertIn("只执行当前修复", rendered)
        self.assertIn("CURRENT-AC", rendered)
        self.assertIn("## 当前计划（本轮权威投影）", rendered)
        self.assertIn("- [已完成] CURRENT-PLAN", rendered)
        self.assertNotIn("OLD-STATE", rendered)

    def test_empty_session_memory_does_not_consume_provider_context(self) -> None:
        rendered = render_context_items(
            [
                {
                    "sourceKind": "memory_bootstrap",
                    "payload": {
                        "schemaVersion": "rag-ime.session-memory-recall.v1",
                        "retrieval": {"temporalIntent": False},
                        "items": [],
                    },
                }
            ]
        )

        self.assertEqual(rendered, "")
        self.assertNotIn("没有召回", rendered)

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
