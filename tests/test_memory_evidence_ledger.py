from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_evidence_ledger import (
    INPUT_MEMORY_LEDGER_SESSION_ID,
    backfill_input_event_evidence,
)
from rag_ime.models import InputEvent


class MemoryEvidenceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-input-ledger-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_final_foreground_input_is_checkpointed_but_generated_text_is_not(self) -> None:
        user_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=100,
                source="squirrel_rime_commit_burst",
                committed_text="记忆整理必须允许撤销遗忘",
                privacy_disposition="allowed",
                project="ime",
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=101,
                source="squirrel_rime_sidecar",
                committed_text="这是模型生成后被选中的候选，不反向学习",
                privacy_disposition="allowed",
                project="ime",
            )
        )
        explicit_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=102,
                source="squirrel_assistant_remember",
                committed_text="用户明确要求记住这个约束",
                privacy_disposition="allowed",
                project="ime",
            )
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT input_event_id, source_kind, trust_class, owner_kind,
                       owner_id, disposition
                FROM agent_memory_sources
                ORDER BY input_event_id
                """
            ).fetchall()
            session = conn.execute(
                "SELECT session_kind, status FROM agent_sessions WHERE id = ?",
                (INPUT_MEMORY_LEDGER_SESSION_ID,),
            ).fetchone()

        self.assertEqual(
            [int(row["input_event_id"]) for row in rows],
            [
                int(user_event.split(":", 1)[1]),
                int(explicit_event.split(":", 1)[1]),
            ],
        )
        self.assertEqual(
            [
                (
                    row["source_kind"],
                    row["trust_class"],
                    row["owner_kind"],
                    row["owner_id"],
                    row["disposition"],
                )
                for row in rows
            ],
            [
                ("user_final", "user_claim", "user", "default", "pending"),
                (
                    "explicit_memory",
                    "explicit_command",
                    "user",
                    "default",
                    "pending",
                ),
            ],
        )
        self.assertEqual(tuple(session), ("subagent_runtime", "archived"))
        self.assertEqual(AgentSessionStore(self.db_path).list(), [])

    def test_sensitive_final_input_is_reversibly_excluded_before_model_curation(self) -> None:
        event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=200,
                source="manual_commit",
                committed_text="临时 token=sk-abcdefghijk 不要记忆",
                privacy_disposition="allowed",
                project="ime",
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT disposition, disposition_reason, processed_at_ms
                FROM agent_memory_sources
                WHERE input_event_id = ?
                """,
                (int(event.split(":", 1)[1]),),
            ).fetchone()
            audit = conn.execute(
                """
                SELECT new_disposition, reason_code, actor_kind
                FROM memory_source_disposition_events
                """
            ).fetchone()

        self.assertEqual(row["disposition"], "not_for_memory")
        self.assertEqual(row["disposition_reason"], "sensitive_input")
        self.assertEqual(int(row["processed_at_ms"]), 200)
        self.assertEqual(
            tuple(audit),
            ("not_for_memory", "sensitive_input", "rule"),
        )

    def test_historical_backfill_is_idempotent_and_project_scoped(self) -> None:
        with self.core._connect() as conn:
            first = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (300, 'debug_page_commit', '项目 A 的长期约束', 'a')
                """
            )
            second = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (301, 'voice_final', '项目 B 的长期约束', 'b')
                """
            )
            conn.execute(
                "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 300)",
                (int(first.lastrowid),),
            )
            conn.execute(
                "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 301)",
                (int(second.lastrowid),),
            )
            first_report = backfill_input_event_evidence(conn, project="a")
            second_report = backfill_input_event_evidence(conn, project="a")

        self.assertEqual(first_report["storedCount"], 1)
        self.assertEqual(first_report["remainingCount"], 0)
        self.assertEqual(second_report["storedCount"], 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT e.project
                FROM agent_memory_sources AS s
                JOIN input_events AS e ON e.id = s.input_event_id
                ORDER BY e.project
                """
            ).fetchall()
        self.assertEqual(rows, [("a",)])

    def test_blank_historical_input_does_not_block_later_backfill_batches(self) -> None:
        with self.core._connect() as conn:
            conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (400, 'manual_commit', ' \n\t ', 'a')
                """
            )
            valid = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (401, 'manual_commit', '后面的有效长期约束', 'a')
                """
            )
            valid_event_id = int(valid.lastrowid)
            report = backfill_input_event_evidence(conn, project="a", limit=1)

        self.assertEqual(report["scannedCount"], 1)
        self.assertEqual(report["storedCount"], 1)
        self.assertEqual(report["remainingCount"], 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            event_ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT input_event_id FROM agent_memory_sources ORDER BY input_event_id"
                ).fetchall()
            ]
        self.assertEqual(event_ids, [valid_event_id])


if __name__ == "__main__":
    unittest.main()
