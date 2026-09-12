from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_evidence_ledger import backfill_input_event_evidence
from rag_ime.models import InputEvent


APP = "com.apple.TextEdit"


def capture_metadata(
    text: str,
    *,
    capture_id: str,
    transaction_id: str,
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.input-capture.v2",
        "captureId": capture_id,
        "transactionId": transaction_id,
        "sequence": 1,
        "channel": "input_method",
        "boundaryKind": "host_return",
        "boundaryConfidence": "strong",
        "nativeCompositionBefore": False,
        "rimeHandled": False,
        "hostForwarded": True,
        "modifiedReturn": False,
        "finalCommitted": True,
        "controllerEpoch": 1,
        "focusEpoch": 1,
        "appBundleId": APP,
        "fieldIdentitySha256": hashlib.sha256(b"field").hexdigest(),
        "privacyRevision": "foreground-privacy.v1",
        "occurredStartMs": 1,
        "occurredEndMs": 2,
        "contentSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "captureSource": "text_input_client",
        "fallbackReason": "",
        "fieldContextChars": len(text),
        "imeBufferChars": len(text),
        "selectionRule": "final_committed_segment",
    }


class MemoryEvidenceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-input-ledger-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_only_capture_v2_and_explicit_memory_are_checkpointed(self) -> None:
        legacy_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=100,
                source="squirrel_rime_commit_burst",
                committed_text="旧的提交片段不能证明最终输入。",
                privacy_disposition="allowed",
                project="ime",
            )
        )
        captured_text = "记忆整理必须允许撤销遗忘。"
        captured_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=101,
                source="squirrel_input_segment",
                committed_text=captured_text,
                privacy_disposition="allowed",
                project="ime",
                app=APP,
                capture_metadata=capture_metadata(
                    captured_text,
                    capture_id="capture:ledger:1",
                    transaction_id="transaction:ledger:1",
                ),
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=102,
                source="squirrel_rime_sidecar",
                committed_text="这是模型生成后被选中的候选，不反向学习。",
                privacy_disposition="allowed",
                project="ime",
            )
        )
        explicit_event = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=103,
                source="squirrel_assistant_remember",
                committed_text="用户明确要求记住这个约束。",
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
            evidence = conn.execute(
                """
                SELECT origin_kind, admission_state, project
                FROM agent_memory_evidence
                WHERE evidence_domain = 'personal_memory'
                ORDER BY occurred_at_ms, evidence_id
                """
            ).fetchall()
            session_count = int(
                conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0]
            )

        self.assertEqual(
            [int(row["input_event_id"]) for row in rows],
            [
                int(captured_event.split(":", 1)[1]),
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
                ("explicit_memory", "explicit_command", "user", "default", "pending"),
            ],
        )
        self.assertEqual(
            [tuple(row) for row in evidence],
            [
                ("capture_v2_input", "candidate", "ime"),
                ("explicit_user_memory", "candidate", "ime"),
            ],
        )
        self.assertNotIn(
            int(legacy_event.split(":", 1)[1]),
            [int(row["input_event_id"]) for row in rows],
        )
        self.assertEqual(session_count, 0)

    def test_short_words_and_referential_fragments_never_enter_memory(self) -> None:
        for ordinal, text in enumerate(
            (
                "这",
                "这个",
                "它",
                "继续",
                "改一下",
                "界面",
                "蓝色。",
                "yes",
                "fix it.",
            ),
            start=1,
        ):
            with self.subTest(text=text):
                event = self.core.record_event(
                    InputEvent(
                        event_id=None,
                        created_at_ms=150 + ordinal,
                        source="squirrel_input_segment",
                        committed_text=text,
                        privacy_disposition="allowed",
                        project="ime",
                        app=APP,
                        capture_metadata=capture_metadata(
                            text,
                            capture_id=f"capture:short-word:{ordinal}",
                            transaction_id=f"transaction:short-word:{ordinal}",
                        ),
                    )
                )

                with closing(sqlite3.connect(self.db_path)) as conn:
                    row = conn.execute(
                        """
                        SELECT source.disposition, source.disposition_reason,
                               evidence.admission_state, evidence.admission_reason
                        FROM agent_memory_sources AS source
                        JOIN agent_memory_evidence AS evidence
                          ON evidence.idempotency_key =
                             'canonical-input-event:' || source.input_event_id
                        WHERE source.input_event_id = ?
                        """,
                        (int(event.split(":", 1)[1]),),
                    ).fetchone()

                self.assertIsNotNone(row)
                self.assertEqual(row[0], "not_for_memory")
                self.assertIn(
                    row[1],
                    {
                        "known_low_signal_fragment",
                        "short_cjk_fragment",
                        "isolated_ascii_token",
                        "insufficient_durable_signal",
                    },
                )
                self.assertEqual(row[2], "rejected")
                self.assertEqual(row[3], row[1])

    def test_sensitive_capture_is_rejected_with_receipt_and_audit(self) -> None:
        text = "临时 token=sk-abcdefghijk 不要记忆。"
        event, receipt = self.core.record_event_with_capture_receipt(
            InputEvent(
                event_id=None,
                created_at_ms=200,
                source="squirrel_input_segment",
                committed_text=text,
                privacy_disposition="allowed",
                project="ime",
                app=APP,
                capture_metadata=capture_metadata(
                    text,
                    capture_id="capture:sensitive:1",
                    transaction_id="transaction:sensitive:1",
                ),
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            audit = conn.execute(
                """
                SELECT outcome, reason_code, input_event_id
                FROM input_capture_receipts WHERE capture_id = ?
                """,
                ("capture:sensitive:1",),
            ).fetchone()
            for table in ("input_events", "agent_memory_sources", "agent_memory_evidence", "memory_source_disposition_events"):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

        # Preserve a durable native acknowledgement without copying sensitive
        # text into the input or Memory evidence/audit ledgers.
        self.assertEqual(event, "skipped:typed_capture_requires_no_store")
        self.assertEqual(receipt["outcome"], "no_store")
        self.assertEqual(receipt["reason"], "typed_capture_requires_no_store")
        self.assertNotIn(text, json.dumps(receipt, ensure_ascii=False))
        self.assertEqual(audit, ("no_store", "typed_capture_requires_no_store", None))

    def test_historical_backfill_is_review_only_without_a_receipt(self) -> None:
        text = "项目 A 的长期约束。"
        metadata = capture_metadata(
            text,
            capture_id="capture:backfill:a",
            transaction_id="transaction:backfill:a",
        )
        with self.core._connect() as conn:
            first = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project, app,
                    capture_metadata_json
                ) VALUES (300, 'squirrel_input_segment', ?, 'a', ?, ?)
                """,
                (text, APP, json.dumps(metadata, ensure_ascii=False)),
            )
            conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (301, 'squirrel_assistant_remember',
                          '项目 B 的长期约束。', 'b')
                """
            )
            conn.execute(
                "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 300)",
                (int(first.lastrowid),),
            )
            first_report = backfill_input_event_evidence(conn, project="a")
            second_report = backfill_input_event_evidence(conn, project="a")

        self.assertEqual(first_report["storedCount"], 1)
        self.assertEqual(first_report["remainingCount"], 0)
        self.assertEqual(first_report["invalidCaptureCount"], 0)
        self.assertEqual(second_report["storedCount"], 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT event.project, evidence.admission_state,
                       evidence.admission_reason
                FROM agent_memory_sources AS source
                JOIN input_events AS event ON event.id = source.input_event_id
                JOIN agent_memory_evidence AS evidence
                  ON evidence.idempotency_key =
                     'canonical-input-event:' || event.id
                ORDER BY event.project
                """
            ).fetchall()
        self.assertEqual(rows, [("a", "needs_review", "missing_capture_receipt")])

    def test_blank_historical_input_does_not_block_later_backfill_batches(self) -> None:
        with self.core._connect() as conn:
            conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (400, 'squirrel_assistant_remember', ' \n\t ', 'a')
                """
            )
            valid = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, project
                ) VALUES (401, 'squirrel_assistant_remember',
                          '后面的有效长期约束。', 'a')
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
