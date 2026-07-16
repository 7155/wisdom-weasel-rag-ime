from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore


class AgentMemorySourceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-memory-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.session = self.sessions.create(title="记忆检查点", created_at_ms=1)
        self.store = AgentMemorySourceStore(self.db_path, project="wisdom-weasel-rag-ime")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_final_user_message_is_idempotent_and_does_not_touch_phrase_frequency(self) -> None:
        first = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:user:1",
            turn_id="turn:1",
            text="把 Pi 的普通生成和深度检索分开",
            created_at_ms=100,
        )
        duplicate = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:user:1",
            turn_id="turn:1",
            text="把 Pi 的普通生成和深度检索分开",
            created_at_ms=200,
        )

        self.assertTrue(first["stored"])
        self.assertEqual(duplicate["status"], "already_checkpointed")
        self.assertEqual(first["source"]["sourceRole"], "user")
        self.assertEqual(first["source"]["sourceKind"], "user_final")
        self.assertEqual(
            (first["source"]["ownerKind"], first["source"]["ownerId"]),
            ("user", "default"),
        )
        self.assertEqual(first["source"]["disposition"], "pending")
        with closing(sqlite3.connect(self.db_path)) as conn:
            event = conn.execute(
                "SELECT source, committed_text, project FROM input_events WHERE id = ?",
                (first["source"]["inputEventId"],),
            ).fetchone()
            phrase_count = conn.execute("SELECT COUNT(*) FROM phrase_stats").fetchone()[0]
            raw = conn.execute(
                "SELECT kind, status FROM memory_items WHERE source_event_id = ?",
                (first["source"]["inputEventId"],),
            ).fetchone()
        self.assertEqual(event, ("pi_agent_user", "把 Pi 的普通生成和深度检索分开", "wisdom-weasel-rag-ime"))
        self.assertEqual(phrase_count, 0)
        self.assertEqual(raw, ("raw_event", "hidden"))

    def test_sensitive_message_and_unapplied_receipt_never_create_source_events(self) -> None:
        sensitive = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:sensitive",
            turn_id="turn:sensitive",
            text="API key=sk-super-secret-value",
        )
        unapplied = self.store.checkpoint_tool_receipt(
            {
                "approvalId": "approval:rejected",
                "sessionId": self.session["id"],
                "state": "rejected",
                "receipt": {"mutationApplied": False, "summary": "没有执行"},
            }
        )

        self.assertEqual(sensitive["status"], "skipped_sensitive")
        self.assertEqual(unapplied["status"], "skipped_unapplied")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0], 0)

    def test_transient_subagent_input_and_compaction_never_become_role_memory(self) -> None:
        child = self.sessions.create(
            title="临时研究子 Agent",
            role_id="zhiyou-v1",
            session_kind="subagent_runtime",
            created_at_ms=250,
        )

        user = self.store.checkpoint_user_message(
            session_id=str(child["id"]),
            pi_entry_id="pi-entry:delegated-task",
            turn_id="turn:delegated-task",
            text="请临时检查这段实现",
            created_at_ms=251,
        )
        compaction = self.store.checkpoint_compaction(
            session_id=str(child["id"]),
            result={"summary": "临时子任务认为需要调整实现。"},
            trigger="automatic",
            created_at_ms=252,
        )

        self.assertEqual(user["status"], "skipped_transient_session")
        self.assertEqual(compaction["status"], "skipped_transient_session")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0], 0)

    def test_only_applied_tool_receipt_is_checkpointed(self) -> None:
        result = self.store.checkpoint_tool_receipt(
            {
                "approvalId": "approval:applied",
                "sessionId": self.session["id"],
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "summary": "已将《接入 Pi》标记为已完成",
                },
            },
            created_at_ms=300,
        )

        self.assertTrue(result["stored"])
        self.assertEqual(result["source"]["sourceRole"], "tool_receipt")
        self.assertEqual(result["source"]["sourceKind"], "tool_receipt")
        self.assertEqual(
            (result["source"]["ownerKind"], result["source"]["ownerId"]),
            ("shared", "wisdom-weasel-rag-ime"),
        )
        listed = self.store.list_for_session(str(self.session["id"]))
        self.assertEqual([item["sourceId"] for item in listed], [result["source"]["sourceId"]])

    def test_compaction_summary_is_role_owned_and_idempotent(self) -> None:
        first = self.store.checkpoint_compaction(
            session_id=str(self.session["id"]),
            result={
                "summary": "用户决定把桌面感知改为 Accessibility Tree，并保留截图兜底。",
                "firstKeptEntryId": "pi-entry:user:9",
                "tokensBefore": 12_000,
                "estimatedTokensAfter": 2_400,
            },
            trigger="automatic",
            created_at_ms=400,
        )
        duplicate = self.store.checkpoint_compaction(
            session_id=str(self.session["id"]),
            result={
                "summary": "用户决定把桌面感知改为 Accessibility Tree，并保留截图兜底。",
                "firstKeptEntryId": "pi-entry:user:9",
                "tokensBefore": 12_000,
                "estimatedTokensAfter": 2_400,
            },
            trigger="manual",
            created_at_ms=500,
        )

        self.assertTrue(first["stored"])
        self.assertEqual(duplicate["status"], "already_checkpointed")
        source = first["source"]
        self.assertEqual(source["sourceKind"], "session_compaction")
        self.assertEqual(source["trustClass"], "session_summary")
        self.assertEqual(
            (source["ownerKind"], source["ownerId"]),
            ("agent", self.session["roleId"]),
        )
        self.assertEqual(source["coverageEndEntryId"], "pi-entry:user:9")
        self.assertTrue(source["metadata"]["coverageEndExclusive"])

    def test_not_for_memory_is_reversible_and_audited(self) -> None:
        checkpoint = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:noise",
            turn_id="turn:noise",
            text="嗯嗯那个这个测试一下",
            created_at_ms=600,
        )
        source_id = str(checkpoint["source"]["sourceId"])

        forgotten = self.store.set_disposition(
            source_id,
            disposition="not_for_memory",
            reason_code="input_noise_filler",
            actor_kind="rule",
            run_id="curation:1",
            created_at_ms=700,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane,
                    last_source_created_at_ms, last_source_id, next_due_at_ms,
                    status, updated_at_ms
                ) VALUES (
                    'user', 'default', 'wisdom-weasel-rag-ime', 'daily',
                    600, ?, 999999, 'idle', 700
                )
                """,
                (source_id,),
            )
        restored = self.store.set_disposition(
            source_id,
            disposition="pending",
            reason_code="user_restored",
            actor_kind="rollback",
            run_id="curation:rollback:1",
            created_at_ms=800,
        )

        self.assertEqual(forgotten["source"]["disposition"], "not_for_memory")
        self.assertEqual(restored["source"]["disposition"], "pending")
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(
                """
                SELECT last_source_created_at_ms, last_source_id, next_due_at_ms
                FROM memory_curation_cursors
                WHERE owner_kind = 'user' AND owner_id = 'default'
                """
            ).fetchone()
            transitions = conn.execute(
                """
                SELECT previous_disposition, new_disposition, reason_code, actor_kind
                FROM memory_source_disposition_events
                WHERE source_id = ?
                ORDER BY created_at_ms
                """,
                (source_id,),
            ).fetchall()
        self.assertEqual(cursor, (0, "", 0))
        self.assertEqual(
            transitions,
            [
                ("", "pending", "checkpoint_created", "system"),
                ("pending", "not_for_memory", "input_noise_filler", "rule"),
                ("not_for_memory", "pending", "user_restored", "rollback"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
