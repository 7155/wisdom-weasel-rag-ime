from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from rag_ime.db import apply_database_migrations
from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.memory_shadow_recovery import (
    MemoryShadowRecoveryError,
    build_memory_pipeline_shadow,
    recover_memory_history_into_candidate,
    shadow_recovery_summary,
)
from rag_ime.text_utils import compact_whitespace


PRIVATE_TEXT = "private recovery fixture must never appear in a report"


class MemoryShadowRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-memory-shadow-"
        )
        self.root = Path(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.backup = self.root / "historical.sqlite"
        self.current = self.root / "current.sqlite"
        self._create_backup(self.backup)
        shutil.copyfile(self.backup, self.current)
        os.chmod(self.current, 0o600)
        with sqlite3.connect(self.current) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM memory_capture_hints")
            conn.execute("DELETE FROM memory_source_disposition_events")
            conn.execute("DELETE FROM agent_memory_sources")
            conn.execute(
                """UPDATE schema_migrations
                   SET name='room_requirement_alignment', checksum=?
                   WHERE version=127""",
                ("f" * 64,),
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_recovery_is_session_independent_and_idempotent(self) -> None:
        first = recover_memory_history_into_candidate(self.current, self.backup)
        second = recover_memory_history_into_candidate(self.current, self.backup)

        self.assertEqual(first["insertedSourceRows"], 1)
        self.assertEqual(first["insertedAuditRows"], 1)
        self.assertEqual(first["insertedHintRows"], 1)
        self.assertEqual(first["insertedEvidenceRows"], 1)
        self.assertEqual(first["insertedEvidenceLinkRows"], 1)
        self.assertEqual(first["insertedAdmissionRows"], 2)
        self.assertFalse(first["receiptReused"])
        self.assertEqual(second["insertedSourceRows"], 0)
        self.assertEqual(second["insertedAuditRows"], 0)
        self.assertEqual(second["insertedHintRows"], 0)
        self.assertEqual(second["insertedEvidenceRows"], 0)
        self.assertEqual(second["insertedEvidenceLinkRows"], 0)
        self.assertEqual(second["insertedAdmissionRows"], 0)
        self.assertTrue(second["receiptReused"])
        self.assertEqual(second["receiptId"], first["receiptId"])
        self.assertNotIn(PRIVATE_TEXT, json.dumps(first, ensure_ascii=False))

        with sqlite3.connect(self.current) as conn:
            conn.row_factory = sqlite3.Row
            session_foreign_keys = [
                row
                for row in conn.execute(
                    "PRAGMA foreign_key_list(agent_memory_sources)"
                )
                if str(row["from"]) == "session_id"
            ]
            evidence = conn.execute(
                """SELECT evidence_domain, origin_kind, admission_state,
                          content_sha256
                   FROM agent_memory_evidence
                   WHERE evidence_id='evidence:source:historical-1'"""
            ).fetchone()
            links = conn.execute(
                """SELECT COUNT(*) FROM memory_evidence_input_event_links
                   WHERE evidence_id='evidence:source:historical-1'"""
            ).fetchone()[0]
            receipts = conn.execute(
                "SELECT COUNT(*) FROM memory_pipeline_recovery_receipts"
            ).fetchone()[0]
            foreign_key_violations = list(conn.execute("PRAGMA foreign_key_check"))

        self.assertEqual(session_foreign_keys, [])
        self.assertEqual(
            tuple(evidence),
            (
                "personal_memory",
                "legacy_untyped_input",
                "needs_review",
                _text_sha256(PRIVATE_TEXT),
            ),
        )
        self.assertEqual(links, 1)
        self.assertEqual(receipts, 1)
        self.assertEqual(foreign_key_violations, [])

    def test_event_mismatch_fails_without_partial_import(self) -> None:
        with sqlite3.connect(self.current) as conn:
            conn.execute(
                "UPDATE input_events SET committed_text='different' WHERE id=1"
            )

        with self.assertRaisesRegex(
            MemoryShadowRecoveryError,
            "input-event prefix",
        ):
            recover_memory_history_into_candidate(self.current, self.backup)

        with sqlite3.connect(self.current) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_pipeline_recovery_receipts"
                ).fetchone()[0],
                0,
            )

    def test_source_identity_conflict_fails_closed(self) -> None:
        with sqlite3.connect(self.current) as conn:
            conn.execute(
                """INSERT INTO agent_memory_sources(
                       source_id, session_id, pi_entry_id, input_event_id,
                       source_role, canonical_text_sha256, created_at_ms
                   ) VALUES ('different-source', 'deleted-session',
                             'entry:historical', 1, 'user', ?, 100)""",
                (_text_sha256(PRIVATE_TEXT),),
            )

        with self.assertRaisesRegex(
            MemoryShadowRecoveryError,
            "exact-row conflict",
        ):
            recover_memory_history_into_candidate(self.current, self.backup)

        with sqlite3.connect(self.current) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_memory_sources"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_source_disposition_events"
                ).fetchone()[0],
                0,
            )

    def test_full_shadow_build_acknowledges_only_known_collision(self) -> None:
        output = self.root / "shadow.sqlite"
        rollback = self.root / "rollback.sqlite"
        report_path = self.root / "shadow-report.json"

        report = build_memory_pipeline_shadow(
            self.current,
            self.backup,
            output_db=output,
            rollback_db=rollback,
            report_path=report_path,
            embedding_provider=HashingEmbeddingProvider(dimensions=16),
            allowed_applied_checksum_mismatch_versions=(127,),
        )
        summary = shadow_recovery_summary(report)

        self.assertEqual(report["status"], "verified")
        self.assertEqual(
            report["migration"]["acknowledgedChecksumMismatchVersions"],
            [127],
        )
        self.assertTrue(report["inputEvents"]["unchanged"])
        self.assertTrue(report["rollbackExercise"]["performed"])
        self.assertTrue(report["rollbackExercise"]["candidateUnchanged"])
        self.assertTrue(report["semanticMigration"]["verificationOk"])
        self.assertEqual(report["repeatRecovery"]["insertedSourceRows"], 0)
        self.assertTrue(report["repeatRecovery"]["receiptReused"])
        self.assertFalse(report["productionApplyPerformed"])
        self.assertEqual(summary["recoveredSourceRows"], 1)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(rollback.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertNotIn(PRIVATE_TEXT, report_path.read_text(encoding="utf-8"))

        with sqlite3.connect(output) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0],
                1,
            )
        with sqlite3.connect(rollback) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0],
                0,
            )

    def test_full_shadow_build_rejects_unacknowledged_collision(self) -> None:
        output = self.root / "blocked-shadow.sqlite"
        rollback = self.root / "blocked-rollback.sqlite"
        report_path = self.root / "blocked-report.json"

        with self.assertRaisesRegex(
            MemoryShadowRecoveryError,
            "unacknowledged migration checksum mismatch",
        ):
            build_memory_pipeline_shadow(
                self.current,
                self.backup,
                output_db=output,
                rollback_db=rollback,
                report_path=report_path,
                embedding_provider=HashingEmbeddingProvider(dimensions=16),
            )

        self.assertFalse(output.exists())
        self.assertTrue(rollback.exists())
        self.assertFalse(report_path.exists())

    def test_full_shadow_build_detaches_copied_runtime_host_lease(self) -> None:
        with sqlite3.connect(self.current) as conn:
            conn.execute(
                """INSERT INTO room_v2_runtime_host_processes(
                       host_identity, owner_instance_id, pid, process_group_id,
                       job_identity, process_birth_token, executable_ref, state,
                       registered_at_ms, updated_at_ms, owner_process_id,
                       owner_process_birth_token
                   ) VALUES (
                       'pi-host:source-live', 'runtime:source-owner', 424242,
                       424242, 'pi-job:source-live', 'birth:source-live',
                       '/private/source/runtime-host', 'running', 100, 100,
                       31337, 'birth:source-owner'
                   )"""
            )

        output = self.root / "runtime-isolated-shadow.sqlite"
        rollback = self.root / "runtime-isolated-rollback.sqlite"
        report_path = self.root / "runtime-isolated-report.json"
        report = build_memory_pipeline_shadow(
            self.current,
            self.backup,
            output_db=output,
            rollback_db=rollback,
            report_path=report_path,
            embedding_provider=HashingEmbeddingProvider(dimensions=16),
            allowed_applied_checksum_mismatch_versions=(127,),
        )

        with sqlite3.connect(self.current) as conn:
            source_state = conn.execute(
                """SELECT state FROM room_v2_runtime_host_processes
                   WHERE host_identity='pi-host:source-live'"""
            ).fetchone()[0]
        with sqlite3.connect(rollback) as conn:
            rollback_state = conn.execute(
                """SELECT state FROM room_v2_runtime_host_processes
                   WHERE host_identity='pi-host:source-live'"""
            ).fetchone()[0]
        with sqlite3.connect(output) as conn:
            shadow_state = conn.execute(
                """SELECT state FROM room_v2_runtime_host_processes
                   WHERE host_identity='pi-host:source-live'"""
            ).fetchone()[0]
            kill_receipts = conn.execute(
                "SELECT COUNT(*) FROM room_v2_runtime_host_kill_receipts"
            ).fetchone()[0]

        self.assertEqual(source_state, "running")
        self.assertEqual(rollback_state, "running")
        self.assertEqual(shadow_state, "unknown")
        self.assertEqual(kill_receipts, 0)
        self.assertEqual(
            report["runtimeHostLeaseIsolation"],
            {
                "detachedRunningLeaseCount": 1,
                "detachedState": "unknown",
                "processSignalsSent": False,
                "sourceDatabaseMutation": False,
            },
        )

    def _create_backup(self, path: Path) -> None:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            apply_database_migrations(conn)
            conn.execute(
                """INSERT INTO input_events(
                       id, created_at_ms, source, committed_text, project, app,
                       tags_json
                   ) VALUES (1, 100, 'pi_agent_user', ?, '', 'fixture', '[]')""",
                (PRIVATE_TEXT,),
            )
            conn.execute(
                """INSERT INTO agent_memory_sources(
                       source_id, session_id, pi_entry_id, input_event_id,
                       source_role, canonical_text_sha256, created_at_ms,
                       disposition, disposition_reason,
                       disposition_updated_at_ms
                   ) VALUES ('historical-1', 'deleted-session',
                             'entry:historical', 1, 'user', ?, 100,
                             'remember', 'historical_model_keep', 110)""",
                (_text_sha256(PRIVATE_TEXT),),
            )
            conn.execute(
                """INSERT INTO memory_source_disposition_events(
                       event_id, source_id, previous_disposition,
                       new_disposition, reason_code, actor_kind, run_id,
                       created_at_ms
                   ) VALUES ('audit:historical-1', 'historical-1', 'pending',
                             'remember', 'durable_preference', 'model',
                             'run:historical', 110)"""
            )
            conn.execute(
                """INSERT INTO memory_capture_hints(
                       hint_id, source_id, kind, normalized_claim, scope,
                       reason, created_at_ms, updated_at_ms
                   ) VALUES ('hint:historical-1', 'historical-1', 'preference',
                             'redacted normalized fixture', 'user',
                             'explicit statement', 100, 100)"""
            )
        os.chmod(path, 0o600)


def _text_sha256(text: str) -> str:
    return hashlib.sha256(compact_whitespace(text).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
