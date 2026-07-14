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
        listed = self.store.list_for_session(str(self.session["id"]))
        self.assertEqual([item["sourceId"] for item in listed], [result["source"]["sourceId"]])


if __name__ == "__main__":
    unittest.main()
