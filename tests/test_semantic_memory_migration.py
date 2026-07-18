from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.db.migration_runner import DEFAULT_MIGRATIONS_DIR, apply_database_migrations
from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.memory_projection import (
    RETRIEVAL_DOCS_PROJECTION,
    enqueue_memory_projection,
)
from rag_ime.semantic_memory_migration import (
    _timeline_conservation_errors,
    migrate_semantic_memory_database,
    preview_semantic_memory_migration,
    verify_semantic_memory_database,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "wisdom-weasel-rag-ime"


class SemanticMemoryMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-semantic-v2-")
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "rag-ime.sqlite"
        migrations_0058 = self.root / "migrations-0058"
        migrations_0058.mkdir()
        for source in DEFAULT_MIGRATIONS_DIR.glob("*.sql"):
            if source.name < "0059_":
                shutil.copy2(source, migrations_0058 / source.name)
        with closing(sqlite3.connect(self.db_path)) as conn:
            apply_database_migrations(conn, migrations_dir=migrations_0058)
            self._seed(conn)
        os.chmod(self.db_path, 0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_preview_is_read_only_and_reports_decisions(self) -> None:
        before = self.db_path.read_bytes()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            preview = preview_semantic_memory_migration(conn, project=PROJECT)

        self.assertEqual(self.db_path.read_bytes(), before)
        self.assertEqual(preview["legacyItems"]["active"], 2)
        self.assertEqual(preview["legacyItems"]["promotable"], 1)
        self.assertEqual(preview["legacyItems"]["quarantined"], 1)
        self.assertEqual(preview["legacyTimelineDrafts"]["count"], 1)
        self.assertEqual(preview["missingAtomClaimKeys"], 2)

    def test_timeline_conservation_accepts_logical_and_physical_counts(self) -> None:
        segment = {
            "segmentId": "segment:reviewed",
            "eventCount": 1,
            "physicalEventCount": 2,
            "sourceEventIds": [1, 2],
        }
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """INSERT INTO daily_activity_timelines(
                       timeline_id, project, timeline_date, timezone, status,
                       source_event_ids_json, source_event_hash, segments_json,
                       summary_text, event_count, segment_count, metadata_json,
                       created_at_ms, updated_at_ms
                   ) VALUES ('timeline:reviewed', ?, '2026-07-18', 'Asia/Shanghai',
                             'approved', '[1,2]', ?, ?, '整理后的活动', 1, 1, ?, 1, 1)""",
                (
                    PROJECT,
                    "c" * 64,
                    json.dumps([segment], ensure_ascii=False),
                    json.dumps({"segmentationMode": "semantic_task_v2"}),
                ),
            )
            errors = _timeline_conservation_errors(conn, project=PROJECT)

        self.assertFalse(
            any(item["timelineId"] == "timeline:reviewed" for item in errors)
        )

    def test_verification_rejects_active_artifacts_without_source_evidence(self) -> None:
        report = migrate_semantic_memory_database(
            self.db_path,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
        )
        self.assertTrue(report["verification"]["ok"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            timeline_id = str(
                conn.execute(
                    """SELECT timeline_id FROM daily_activity_timelines
                       WHERE project = ? AND status = 'draft'""",
                    (PROJECT,),
                ).fetchone()[0]
            )
            conn.execute(
                """UPDATE memory_atoms SET source_event_ids_json = '[]'
                   WHERE id = 'atom:new'"""
            )
            conn.execute(
                """INSERT INTO memory_books(
                       book_id, book_type, book_key, title, summary,
                       normalized_text, project, source_event_ids_json,
                       memory_atom_ids_json, status, confidence, quality_score,
                       created_at_ms, updated_at_ms, metadata_json
                   ) VALUES ('book:unbacked', 'topic', 'unbacked',
                             '无来源主题', '这条主题书没有事实来源。',
                             '无来源主题', ?, '[]', '[]', 'active',
                             0.9, 0.9, 1, 1, '{}')""",
                (PROJECT,),
            )
            conn.execute(
                """INSERT INTO memory_items(
                       memory_id, kind, text, normalized_text, summary,
                       source_event_id, project, status, created_at_ms,
                       updated_at_ms, metadata_json
                   ) VALUES ('phrase:unbacked', 'phrase', '无来源短语',
                             '无来源短语', '', NULL, ?, 'active', 1, 1, '{}')""",
                (PROJECT,),
            )
            conn.execute(
                """UPDATE daily_activity_timelines
                   SET status = 'approved', source_event_ids_json = '[]',
                       segments_json = '[]', event_count = 0, segment_count = 0
                   WHERE project = ? AND status = 'draft'""",
                (PROJECT,),
            )

            verification = verify_semantic_memory_database(conn, project=PROJECT)

        self.assertFalse(verification["ok"])
        self.assertIn("active_artifact_evidence_errors=4", verification["errors"])
        self.assertEqual(
            {
                (item["artifactType"], item["artifactId"], item["reason"])
                for item in verification["activeArtifactEvidenceErrors"]
            },
            {
                ("atom", "atom:new", "missing_source_evidence"),
                ("book", "book:unbacked", "missing_source_evidence"),
                ("phrase", "phrase:unbacked", "missing_source_evidence"),
                ("timeline", timeline_id, "missing_source_evidence"),
            },
        )

    def test_verification_rejects_governed_evidence_not_fully_remembered(self) -> None:
        report = migrate_semantic_memory_database(
            self.db_path,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
        )
        self.assertTrue(report["verification"]["ok"])
        sessions = AgentSessionStore(self.db_path)
        session = sessions.create(title="mixed-governance", created_at_ms=1)
        sources = AgentMemorySourceStore(self.db_path, project=PROJECT)
        sources.checkpoint_user_message(
            session_id=str(session["id"]),
            pi_entry_id="entry:mixed",
            turn_id="turn:mixed",
            text="治理测试来源。",
            created_at_ms=1_800_000_000_000,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """UPDATE agent_memory_sources
                   SET input_event_id = 2, disposition = 'not_for_memory',
                       disposition_reason = 'manual_review_excluded'
                   WHERE pi_entry_id = 'entry:mixed'"""
            )

            verification = verify_semantic_memory_database(conn, project=PROJECT)

        self.assertFalse(verification["ok"])
        self.assertTrue(
            any(
                item["artifactType"] == "atom"
                and item["artifactId"] == "atom:new"
                and item["reason"] == "source_disposition_not_fully_remembered"
                and item["eventIds"] == [2]
                for item in verification["activeArtifactEvidenceErrors"]
            )
        )

    def test_verification_accepts_remembered_evidence_when_raw_row_is_hidden(self) -> None:
        report = migrate_semantic_memory_database(
            self.db_path,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
        )
        self.assertTrue(report["verification"]["ok"])
        sessions = AgentSessionStore(self.db_path)
        session = sessions.create(title="hidden-raw-evidence", created_at_ms=1)
        sources = AgentMemorySourceStore(self.db_path, project=PROJECT)
        sources.checkpoint_user_message(
            session_id=str(session["id"]),
            pi_entry_id="entry:hidden-raw-evidence",
            turn_id="turn:hidden-raw-evidence",
            text="隐藏原始输入不等于遗忘已整理事实。",
            created_at_ms=1_800_000_000_000,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """UPDATE agent_memory_sources
                   SET input_event_id = 2, disposition = 'remember',
                       disposition_reason = 'manual_review_remembered'
                   WHERE pi_entry_id = 'entry:hidden-raw-evidence'"""
            )
            conn.execute("UPDATE memory_state SET deleted = 1 WHERE event_id = 2")

            verification = verify_semantic_memory_database(conn, project=PROJECT)

        self.assertTrue(verification["ok"], verification["errors"])
        self.assertEqual(verification["activeArtifactEvidenceErrors"], [])

    def test_migration_translates_reviewed_item_and_rebuilds_only_draft(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            input_before = [tuple(row) for row in conn.execute("SELECT * FROM input_events ORDER BY id")]

        report = migrate_semantic_memory_database(
            self.db_path,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            input_after = [tuple(row) for row in conn.execute("SELECT * FROM input_events ORDER BY id")]
            item_rows = conn.execute(
                "SELECT memory_id, status, metadata_json FROM memory_items ORDER BY memory_id"
            ).fetchall()
            migrated_atom = conn.execute(
                """SELECT * FROM memory_atoms
                   WHERE source_memory_ids_json LIKE '%stable:reviewed%'"""
            ).fetchone()
            lineage = {
                str(row["id"]): row
                for row in conn.execute(
                """SELECT id, status, claim_key, lineage_id, claim_state, supersedes_id
                   FROM memory_atoms WHERE id IN ('atom:old', 'atom:new') ORDER BY id"""
                ).fetchall()
            }
            timeline = conn.execute(
                """SELECT status, segment_count, metadata_json
                   FROM daily_activity_timelines WHERE status = 'draft'"""
            ).fetchone()
            doc_types = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT doc_type, COUNT(*) FROM memory_retrieval_docs GROUP BY doc_type"
                )
            }

        self.assertEqual(input_after, input_before)
        self.assertTrue(report["verification"]["ok"])
        self.assertEqual(report["migration"]["currentVersion"], 60)
        self.assertEqual(report["legacyItems"]["promoted"], 1)
        self.assertEqual(report["legacyItems"]["quarantined"], 1)
        self.assertFalse(report["verification"]["vectorGateRequired"])
        self.assertFalse(report["verification"]["activationEligible"])
        self.assertTrue(all(str(row["status"]) == "hidden" for row in item_rows))
        self.assertEqual(
            json.loads(str(item_rows[0]["metadata_json"]))["semanticV2Migration"]["status"],
            "quarantined",
        )
        self.assertIsNotNone(migrated_atom)
        self.assertEqual(str(migrated_atom["status"]), "approved")
        self.assertEqual(str(lineage["atom:old"]["status"]), "superseded")
        self.assertEqual(
            str(lineage["atom:old"]["claim_key"]),
            str(lineage["atom:new"]["claim_key"]),
        )
        self.assertEqual(
            str(lineage["atom:old"]["lineage_id"]),
            str(lineage["atom:new"]["lineage_id"]),
        )
        self.assertEqual(str(lineage["atom:new"]["claim_state"]), "current")
        self.assertEqual(str(lineage["atom:new"]["supersedes_id"]), "atom:old")
        self.assertEqual(str(timeline["status"]), "draft")
        self.assertEqual(
            json.loads(str(timeline["metadata_json"]))["segmentationMode"],
            "semantic_task_v2",
        )
        self.assertLess(int(timeline["segment_count"]), 99)
        self.assertNotIn("item", doc_types)
        self.assertGreaterEqual(doc_types.get("atom", 0), 2)

    def test_copy_cli_and_atomic_activation_keep_rollback(self) -> None:
        candidate = self.root / "candidate.sqlite"
        rollback = self.root / "rollback.sqlite"
        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        report_path = candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json")
        migration_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(
            migration_report["candidateSha256"],
            hashlib.sha256(candidate.read_bytes()).hexdigest(),
        )
        self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)
        activate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "activate_semantic_memory_candidate.py"),
                "--target",
                str(self.db_path),
                "--candidate",
                str(candidate),
                "--rollback",
                str(rollback),
                "--report",
                str(report_path),
                "--confirm",
                "ACTIVATE_SEMANTIC_MEMORY_V2",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(activate.returncode, 0, activate.stderr)
        self.assertTrue(rollback.is_file())
        self.assertEqual(candidate.stat().st_mode & 0o777, 0o600)
        self.assertEqual(rollback.stat().st_mode & 0o777, 0o600)
        receipt = rollback.with_suffix(rollback.suffix + ".activation.json")
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        activation_receipt = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(
            activation_receipt["candidateSha256"],
            hashlib.sha256(candidate.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            activation_receipt["rollbackSha256"],
            hashlib.sha256(rollback.read_bytes()).hexdigest(),
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            current = int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
        with closing(sqlite3.connect(rollback)) as conn:
            previous = int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
        self.assertEqual(current, 60)
        self.assertEqual(previous, 58)

    def test_copy_cli_accepts_sidecars_materialized_by_read_only_wal_backup(self) -> None:
        candidate = self.root / "wal-candidate.sqlite"
        with closing(sqlite3.connect(self.db_path)) as conn:
            mode = str(conn.execute("PRAGMA journal_mode = WAL").fetchone()[0])
        self.assertEqual(mode.lower(), "wal")

        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )

        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        report_path = candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIsNotNone(report["sourceState"]["database"])
        self.assertTrue(report["verification"]["activationEligible"])

    def test_apply_rejects_disabled_embedding_provider(self) -> None:
        candidate = self.root / "disabled-provider.sqlite"
        environment = self._embedding_environment()
        environment["RAG_IME_EMBEDDING_PROVIDER"] = "none"

        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        self.assertNotEqual(migrate.returncode, 0)
        self.assertIn("resolved to a disabled provider", migrate.stderr)
        self.assertFalse(candidate.exists())

    def test_activation_stop_proof_detects_every_runtime_signal(self) -> None:
        script = ROOT / "scripts" / "activate_semantic_memory_candidate.py"
        spec = importlib.util.spec_from_file_location(
            "test_activate_semantic_memory_candidate",
            script,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if args[:2] == ["launchctl", "print"]:
                loaded = str(args[-1]).endswith("/com.rag-ime.sidecar")
                return subprocess.CompletedProcess(args, 0 if loaded else 1, "", "")
            if args[:2] == ["lsof", "-nP"] and "-iTCP:8766" in args:
                return subprocess.CompletedProcess(args, 0, "42\n", "")
            if args[:3] == ["lsof", "-nP", "--"]:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\npython 42 u 3u REG x 0 1 db\n",
                    "",
                )
            if args[:2] == ["pgrep", "-fl"] and "agImeControl" in str(args[-1]):
                return subprocess.CompletedProcess(args, 0, "43 RagImeControl\n", "")
            return subprocess.CompletedProcess(args, 1, "", "")

        with mock.patch.object(module.subprocess, "run", side_effect=fake_run), mock.patch.object(
            module,
            "_command_available",
            return_value=True,
        ):
            proof = module._runtime_stop_verification(self.db_path, required=True)

        self.assertFalse(proof["ok"])
        self.assertIn("loaded_launch_agents=com.rag-ime.sidecar", proof["errors"])
        self.assertIn("listening_runtime_ports=8766", proof["errors"])
        self.assertIn("database_open_handles=1", proof["errors"])
        self.assertIn("orphan_runtime_processes=1", proof["errors"])
        self.assertEqual(proof["orphanRuntimeProcesses"], ["43 RagImeControl"])

    def test_strict_verification_rejects_missing_stale_and_uncaught_up_vectors(self) -> None:
        provider = HashingEmbeddingProvider(dimensions=16)
        report = migrate_semantic_memory_database(
            self.db_path,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            embedding_provider=provider,
            require_vector_freshness=True,
        )
        self.assertTrue(report["verification"]["activationEligible"])
        self.assertEqual(
            report["verification"]["expectedRetrievalDocuments"],
            report["verification"]["activeRetrievalDocuments"],
        )
        self.assertEqual(report["verification"]["missingProjectedDocIds"], [])
        self.assertEqual(report["verification"]["unexpectedActiveDocIds"], [])

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            doc_id = str(
                conn.execute(
                    "SELECT doc_id FROM memory_retrieval_docs ORDER BY doc_id LIMIT 1"
                ).fetchone()[0]
            )
            conn.execute(
                """UPDATE memory_retrieval_doc_vectors
                   SET updated_at_ms = 0
                   WHERE doc_id = ? AND provider_fingerprint = ?""",
                (doc_id, provider.fingerprint),
            )
            stale = verify_semantic_memory_database(
                conn,
                project=PROJECT,
                provider_fingerprint=provider.fingerprint,
                require_vector_freshness=True,
            )
            conn.execute(
                """DELETE FROM memory_retrieval_doc_vectors
                   WHERE doc_id = ? AND provider_fingerprint = ?""",
                (doc_id, provider.fingerprint),
            )
            missing = verify_semantic_memory_database(
                conn,
                project=PROJECT,
                provider_fingerprint=provider.fingerprint,
                require_vector_freshness=True,
            )
            outbox_id = enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="project",
                aggregate_id=PROJECT,
                operation="test_pending_gate",
                project=PROJECT,
            )
            pending = verify_semantic_memory_database(
                conn,
                project=PROJECT,
                provider_fingerprint=provider.fingerprint,
                require_vector_freshness=True,
            )
            conn.execute(
                """UPDATE memory_projection_outbox
                   SET state = 'failed' WHERE outbox_id = ?""",
                (outbox_id,),
            )
            failed = verify_semantic_memory_database(
                conn,
                project=PROJECT,
                provider_fingerprint=provider.fingerprint,
                require_vector_freshness=True,
            )
            conn.execute(
                """UPDATE memory_projection_outbox
                   SET state = 'dead' WHERE outbox_id = ?""",
                (outbox_id,),
            )
            dead = verify_semantic_memory_database(
                conn,
                project=PROJECT,
                provider_fingerprint=provider.fingerprint,
                require_vector_freshness=True,
            )

        self.assertIn("retrieval_vectors_stale=1", stale["errors"])
        self.assertTrue(
            any(error.startswith("retrieval_vector_parity=") for error in missing["errors"])
        )
        self.assertIn("retrieval_vectors_missing=1", missing["errors"])
        self.assertIn("projection_outbox_pending=1", pending["errors"])
        self.assertTrue(
            any(error.startswith("retrieval_docs_checkpoint_lag=") for error in pending["errors"])
        )
        self.assertIn("projection_outbox_failed=1", failed["errors"])
        self.assertIn("projection_outbox_dead=1", dead["errors"])

    def test_strict_verification_compares_expected_projected_document_ids(self) -> None:
        provider = HashingEmbeddingProvider(dimensions=16)
        report = migrate_semantic_memory_database(
            self.db_path,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            embedding_provider=provider,
            require_vector_freshness=True,
        )
        self.assertTrue(report["verification"]["activationEligible"])

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            timestamp = int(datetime.now(tz=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
            conn.execute(
                """
                INSERT INTO memory_items(
                    memory_id, kind, text, normalized_text, project, status,
                    privacy_class, created_at_ms, updated_at_ms, metadata_json
                ) VALUES (
                    'phrase:unprojected-source', 'phrase', '尚未投影的新短语',
                    '尚未投影的新短语', ?, 'approved', 'local', ?, ?, '{}'
                )
                """,
                (PROJECT, timestamp, timestamp),
            )
            conn.execute(
                """
                INSERT INTO memory_retrieval_docs(
                    doc_id, doc_type, source_id, raw_text, tags_text, aliases_text,
                    surface_hints_text, query_expansions_text, time_key, project,
                    app, owner_kind, owner_id, status, updated_at_ms, metadata_json
                ) VALUES (
                    'phrase:orphan-projection', 'phrase', 'orphan-projection',
                    '没有治理来源的投影', '', '', '没有治理来源的投影', '', '',
                    ?, '', 'user', 'default', 'active', ?, '{}'
                )
                """,
                (PROJECT, timestamp),
            )
            verification = verify_semantic_memory_database(
                conn,
                project=PROJECT,
                provider_fingerprint=provider.fingerprint,
                require_vector_freshness=True,
            )

        self.assertFalse(verification["activationEligible"])
        self.assertIn("retrieval_docs_missing_from_projection=1", verification["errors"])
        self.assertIn("retrieval_docs_unexpected_active=1", verification["errors"])
        self.assertEqual(
            verification["missingProjectedDocIds"],
            ["phrase:phrase:unprojected-source"],
        )
        self.assertEqual(
            verification["unexpectedActiveDocIds"],
            ["phrase:orphan-projection"],
        )

    def test_activation_revalidates_tampered_candidate_before_replacement(self) -> None:
        candidate = self.root / "tampered-candidate.sqlite"
        rollback = self.root / "tampered-rollback.sqlite"
        report_path = candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json")
        source_before = self.db_path.read_bytes()
        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        with closing(sqlite3.connect(candidate)) as conn:
            conn.execute(
                """DELETE FROM memory_retrieval_doc_vectors
                   WHERE rowid = (SELECT rowid FROM memory_retrieval_doc_vectors LIMIT 1)"""
            )
            conn.commit()

        activate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "activate_semantic_memory_candidate.py"),
                "--target",
                str(self.db_path),
                "--candidate",
                str(candidate),
                "--rollback",
                str(rollback),
                "--report",
                str(report_path),
                "--confirm",
                "ACTIVATE_SEMANTIC_MEMORY_V2",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(activate.returncode, 0)
        self.assertIn("candidate content does not match its migration report", activate.stderr)
        self.assertEqual(self.db_path.read_bytes(), source_before)
        self.assertFalse(rollback.exists())

    def test_activation_failure_after_replace_restores_rollback_database(self) -> None:
        candidate = self.root / "restore-candidate.sqlite"
        rollback = self.root / "restore-rollback.sqlite"
        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        report_path = candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json")

        script = ROOT / "scripts" / "activate_semantic_memory_candidate.py"
        spec = importlib.util.spec_from_file_location(
            "test_activate_semantic_memory_restore",
            script,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original_verify = module._verify_semantic_database
        calls = 0

        def fail_after_replace(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced post-replace verification failure")
            return original_verify(*args, **kwargs)

        with mock.patch.object(
            module,
            "_verify_semantic_database",
            side_effect=fail_after_replace,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "forced post-replace verification failure",
            ):
                module.activate_candidate(
                    target=self.db_path,
                    candidate=candidate,
                    rollback=rollback,
                    report_path=report_path,
                )

        receipt = rollback.with_suffix(rollback.suffix + ".activation.json")
        self.assertTrue(rollback.is_file())
        self.assertFalse(receipt.exists())
        self.assertEqual(rollback.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(self.db_path)) as conn:
            restored_version = int(
                conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            )
            restored_inputs = conn.execute(
                "SELECT id, committed_text FROM input_events ORDER BY id"
            ).fetchall()
        self.assertEqual(restored_version, 58)
        self.assertEqual(
            restored_inputs,
            [
                (1, "通过 CAS 切换 Codex 账号"),
                (2, "继续完成输入法记忆迁移"),
            ],
        )

    def test_cli_rejects_source_and_output_symlinks(self) -> None:
        source_link = self.root / "source-link.sqlite"
        source_link.symlink_to(self.db_path)
        preview = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(source_link),
                "--project",
                PROJECT,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(preview.returncode, 0)
        self.assertIn("must not be a symlink", preview.stderr)

        output_link = self.root / "candidate-link.sqlite"
        output_link.symlink_to(self.root / "missing-candidate.sqlite")
        apply = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(output_link),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertNotEqual(apply.returncode, 0)
        self.assertIn("already exists or is a symlink", apply.stderr)
        self.assertFalse((self.root / "missing-candidate.sqlite").exists())

    def test_cli_and_activation_reject_hard_link_aliases(self) -> None:
        source_alias = self.root / "source-hard-link.sqlite"
        os.link(self.db_path, source_alias)
        preview = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--project",
                PROJECT,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(preview.returncode, 0)
        self.assertIn("must have exactly one hard link", preview.stderr)
        source_alias.unlink()

        candidate = self.root / "hard-link-candidate.sqlite"
        rollback = self.root / "hard-link-rollback.sqlite"
        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        report_path = candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json")

        for protected, alias, label in (
            (self.db_path, self.root / "target-alias.sqlite", "target database"),
            (candidate, self.root / "candidate-alias.sqlite", "candidate database"),
            (report_path, self.root / "report-alias.json", "migration report"),
        ):
            with self.subTest(label=label):
                os.link(protected, alias)
                activate = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "activate_semantic_memory_candidate.py"),
                        "--target",
                        str(self.db_path),
                        "--candidate",
                        str(candidate),
                        "--rollback",
                        str(rollback),
                        "--report",
                        str(report_path),
                        "--confirm",
                        "ACTIVATE_SEMANTIC_MEMORY_V2",
                    ],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(activate.returncode, 0)
                self.assertIn(
                    f"{label} must have exactly one hard link",
                    activate.stderr,
                )
                self.assertFalse(rollback.exists())
                alias.unlink()

    def test_activation_rejects_symlink_paths_and_permissive_candidate(self) -> None:
        candidate = self.root / "secure-candidate.sqlite"
        rollback = self.root / "secure-rollback.sqlite"
        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        report_path = candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json")

        target_link = self.root / "target-link.sqlite"
        target_link.symlink_to(self.db_path)
        candidate_link = self.root / "candidate-link.sqlite"
        candidate_link.symlink_to(candidate)
        report_link = self.root / "report-link.json"
        report_link.symlink_to(report_path)
        broken_rollback_link = self.root / "rollback-link.sqlite"
        broken_rollback_link.symlink_to(self.root / "missing-rollback.sqlite")
        cases = (
            (target_link, candidate, report_path, rollback),
            (self.db_path, candidate_link, report_path, rollback),
            (self.db_path, candidate, report_link, rollback),
            (self.db_path, candidate, report_path, broken_rollback_link),
        )
        for target_path, candidate_path, candidate_report, rollback_path in cases:
            with self.subTest(
                target=target_path,
                candidate=candidate_path,
                report=candidate_report,
                rollback=rollback_path,
            ):
                activate = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "activate_semantic_memory_candidate.py"),
                        "--target",
                        str(target_path),
                        "--candidate",
                        str(candidate_path),
                        "--rollback",
                        str(rollback_path),
                        "--report",
                        str(candidate_report),
                        "--confirm",
                        "ACTIVATE_SEMANTIC_MEMORY_V2",
                    ],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(activate.returncode, 0)
                self.assertIn("must not be a symlink", activate.stderr)
                self.assertFalse(rollback.exists())

        os.chmod(candidate, 0o644)
        permissive = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "activate_semantic_memory_candidate.py"),
                "--target",
                str(self.db_path),
                "--candidate",
                str(candidate),
                "--rollback",
                str(rollback),
                "--report",
                str(report_path),
                "--confirm",
                "ACTIVATE_SEMANTIC_MEMORY_V2",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(permissive.returncode, 0)
        self.assertIn("must not be accessible by group or others", permissive.stderr)
        self.assertFalse(rollback.exists())

    def test_activation_accepts_strict_manual_candidate_report(self) -> None:
        candidate, semantic_report_path = self._build_activation_candidate("manual")
        rollback = self.root / "manual-rollback.sqlite"
        module = self._load_activation_module("test_manual_candidate_activation")
        manual_report_path = self._write_manual_activation_report(
            module,
            candidate=candidate,
            semantic_report_path=semantic_report_path,
        )
        semantic_report_path.unlink()

        with mock.patch.object(
            module,
            "_runtime_stop_verification",
            return_value=self._stopped_runtime_proof(),
        ):
            receipt = module.activate_candidate(
                target=self.db_path,
                candidate=candidate,
                rollback=rollback,
            )

        self.assertEqual(
            receipt["candidateReportSchemaVersion"],
            "rag-ime.manual-memory-candidate-report.v1",
        )
        self.assertEqual(receipt["beforeState"]["project"], PROJECT)
        self.assertEqual(
            receipt["migrationReportPath"],
            str(manual_report_path.resolve()),
        )
        self.assertTrue(receipt["verification"]["ok"])
        self.assertTrue(rollback.is_file())

    def test_activation_rejects_manual_report_when_full_input_history_drifts(self) -> None:
        candidate, semantic_report_path = self._build_activation_candidate("manual-drift")
        rollback = self.root / "manual-drift-rollback.sqlite"
        module = self._load_activation_module("test_manual_candidate_drift")
        manual_report_path = self._write_manual_activation_report(
            module,
            candidate=candidate,
            semantic_report_path=semantic_report_path,
        )
        # This event has no agent_memory_source.  Project evidence remains the
        # same, while the full immutable input history fingerprint must change.
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """INSERT INTO input_events(
                       created_at_ms, source, committed_text, app, project, tags_json
                   ) VALUES (9999999999999, 'test', 'unreviewed input drift',
                             'test.app', 'unrelated-project', '[]')"""
            )
            conn.commit()

        with mock.patch.object(
            module,
            "_runtime_stop_verification",
            return_value=self._stopped_runtime_proof(),
        ):
            with self.assertRaisesRegex(RuntimeError, "inputEventsFingerprint"):
                module.activate_candidate(
                    target=self.db_path,
                    candidate=candidate,
                    rollback=rollback,
                    report_path=manual_report_path,
                )

        self.assertFalse(rollback.exists())
        self.assertFalse(
            rollback.with_suffix(rollback.suffix + ".activation.json").exists()
        )

    def test_activation_rejects_incomplete_manual_before_state(self) -> None:
        candidate, semantic_report_path = self._build_activation_candidate(
            "manual-incomplete"
        )
        rollback = self.root / "manual-incomplete-rollback.sqlite"
        module = self._load_activation_module("test_manual_candidate_incomplete")
        manual_report_path = self._write_manual_activation_report(
            module,
            candidate=candidate,
            semantic_report_path=semantic_report_path,
        )
        report = json.loads(manual_report_path.read_text(encoding="utf-8"))
        del report["beforeState"]["governanceFingerprint"]
        manual_report_path.write_text(
            json.dumps(report, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(manual_report_path, 0o600)

        with self.assertRaisesRegex(ValueError, "governanceFingerprint"):
            module.activate_candidate(
                target=self.db_path,
                candidate=candidate,
                rollback=rollback,
                report_path=manual_report_path,
            )
        self.assertFalse(rollback.exists())

    def test_activation_live_gate_rejects_unbacked_active_artifact(self) -> None:
        candidate, semantic_report_path = self._build_activation_candidate(
            "manual-unbacked"
        )
        rollback = self.root / "manual-unbacked-rollback.sqlite"
        module = self._load_activation_module("test_manual_candidate_unbacked")
        manual_report_path = self._write_manual_activation_report(
            module,
            candidate=candidate,
            semantic_report_path=semantic_report_path,
        )
        target_before = self.db_path.read_bytes()
        with closing(sqlite3.connect(candidate)) as conn:
            conn.execute(
                """UPDATE memory_atoms SET source_event_ids_json = '[]'
                   WHERE id = 'atom:new'"""
            )
            conn.commit()
        report = json.loads(manual_report_path.read_text(encoding="utf-8"))
        # Keep all static report checks satisfied. The activation path must not
        # trust the old report's semanticVerification; it must re-open and
        # verify the exact candidate bytes immediately before replacement.
        report["candidateSha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        manual_report_path.write_text(
            json.dumps(report, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(manual_report_path, 0o600)

        with mock.patch.object(
            module,
            "_runtime_stop_verification",
            return_value=self._stopped_runtime_proof(),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "active_artifact_evidence_errors",
            ):
                module.activate_candidate(
                    target=self.db_path,
                    candidate=candidate,
                    rollback=rollback,
                    report_path=manual_report_path,
                )

        self.assertEqual(self.db_path.read_bytes(), target_before)
        self.assertFalse(rollback.exists())

    def _build_activation_candidate(self, name: str) -> tuple[Path, Path]:
        candidate = self.root / f"{name}-candidate.sqlite"
        migrate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "migrate_semantic_memory_v2.py"),
                "--source",
                str(self.db_path),
                "--output",
                str(candidate),
                "--project",
                PROJECT,
                "--embedding-from-env",
                "--apply",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=self._embedding_environment(),
        )
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        return (
            candidate,
            candidate.with_suffix(candidate.suffix + ".semantic-v2-report.json"),
        )

    def _write_manual_activation_report(
        self,
        module: object,
        *,
        candidate: Path,
        semantic_report_path: Path,
    ) -> Path:
        semantic_report = json.loads(
            semantic_report_path.read_text(encoding="utf-8")
        )
        before_state = module._manual_before_state(self.db_path, project=PROJECT)
        application = {
            "ok": True,
            "project": PROJECT,
            "candidatePath": str(candidate.resolve()),
            "beforeState": before_state,
            "evidenceFingerprint": before_state["evidenceFingerprint"],
            "memoryCatalogFingerprintBefore": before_state[
                "memoryCatalogFingerprint"
            ],
            "governanceFingerprintBefore": before_state["governanceFingerprint"],
            "inputEventsFingerprint": before_state["inputEventsFingerprint"],
            "verification": {"ok": True, "errors": []},
        }
        report = {
            "schemaVersion": "rag-ime.manual-memory-candidate-report.v1",
            "ok": True,
            "beforeState": before_state,
            "candidatePath": str(candidate.resolve()),
            "candidateSha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "providerFingerprint": semantic_report["verification"][
                "vectorProviderFingerprint"
            ],
            "application": application,
            "manualVerification": {"ok": True, "errors": []},
            "semanticVerification": semantic_report["verification"],
        }
        path = candidate.with_suffix(candidate.suffix + ".manual-review-report.json")
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    @staticmethod
    def _load_activation_module(name: str) -> object:
        script = ROOT / "scripts" / "activate_semantic_memory_candidate.py"
        spec = importlib.util.spec_from_file_location(name, script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _stopped_runtime_proof(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.runtime-stop-verification.v1",
            "required": True,
            "ok": True,
            "targetPath": str(self.db_path),
            "loadedLaunchAgents": [],
            "listeningPorts": [],
            "databaseOpenHandles": [],
            "orphanRuntimeProcesses": [],
            "errors": [],
        }

    def _seed(self, conn: sqlite3.Connection) -> None:
        tz = ZoneInfo("Asia/Shanghai")
        first_ms = int(datetime(2026, 7, 17, 9, 0, tzinfo=tz).timestamp() * 1000)
        second_ms = int(datetime(2026, 7, 17, 9, 20, tzinfo=tz).timestamp() * 1000)
        conn.executemany(
            """
            INSERT INTO input_events(
                id, created_at_ms, source, committed_text, app, project,
                context_group_id, tags_json
            ) VALUES (?, ?, 'squirrel_input_segment', ?, ?, ?, ?, '[]')
            """,
            (
                (1, first_ms, "通过 CAS 切换 Codex 账号", "com.mitchellh.ghostty", PROJECT, "app:terminal"),
                (2, second_ms, "继续完成输入法记忆迁移", "com.openai.codex", PROJECT, "app:codex"),
            ),
        )
        conn.executemany(
            """
            INSERT INTO memory_items(
                memory_id, kind, text, normalized_text, source_event_id,
                project, status, privacy_class, created_at_ms, updated_at_ms,
                metadata_json
            ) VALUES (?, 'stable_memory', ?, ?, ?, ?, 'approved', 'local', ?, ?, ?)
            """,
            (
                (
                    "stable:reviewed",
                    "记忆迁移必须保留来源并经过验证后再激活。",
                    "记忆迁移必须保留来源并经过验证后再激活。",
                    1,
                    PROJECT,
                    first_ms,
                    first_ms,
                    json.dumps(
                        {
                            "confidence": 0.9,
                            "reason": "用户已明确确认这条工程约束。",
                            "evidenceEventIds": [1],
                            "tags": ["project_requirement"],
                        },
                        ensure_ascii=False,
                    ),
                ),
                (
                    "stable:fragment",
                    "那么",
                    "那么",
                    2,
                    PROJECT,
                    second_ms,
                    second_ms,
                    json.dumps(
                        {"confidence": 0.7, "evidenceEventIds": [2]},
                        ensure_ascii=False,
                    ),
                ),
            ),
        )
        for atom_id, text, status, event_ids, created in (
            ("atom:old", "旧模型为 0.8B。", "active", "[1]", first_ms),
            ("atom:new", "当前模型为 100M。", "active", "[2]", second_ms),
        ):
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    source_memory_ids_json, scope_project, confidence,
                    quality_score, echo_risk, privacy_level, status,
                    created_at_ms, updated_at_ms
                ) VALUES (?, 'project_fact', ?, ?, ?, '[]', ?, 0.9, 0.9,
                          0.0, 'local', ?, ?, ?)
                """,
                (atom_id, text, text, event_ids, PROJECT, status, created, created),
            )
        conn.execute(
            """
            INSERT INTO memory_supersessions(
                supersession_id, old_memory_id, new_memory_id, reason,
                source_event_ids_json, status, created_at_ms
            ) VALUES ('supersession:model', 'atom:old', 'atom:new',
                      '模型切换', '[2]', 'active', ?)
            """,
            (second_ms,),
        )
        legacy_segments = [
            {
                "segmentId": "legacy:1",
                "position": 0,
                "app": "multiple",
                "sourceKinds": ["squirrel_input_segment"],
                "contextGroupIds": ["app:terminal", "app:codex"],
                "startMs": first_ms,
                "endMs": second_ms,
                "eventCount": 2,
                "sourceEventIds": [1, 2],
                "sourceEventHash": "a" * 64,
                "summary": "旧应用级时间线",
                "redactedEventCount": 0,
            }
        ]
        conn.execute(
            """
            INSERT INTO daily_activity_timelines(
                timeline_id, project, timeline_date, timezone, status,
                source_event_ids_json, source_event_hash, segments_json,
                summary_text, event_count, segment_count, metadata_json,
                created_at_ms, updated_at_ms
            ) VALUES ('timeline:legacy', ?, '2026-07-17', 'Asia/Shanghai',
                      'draft', '[1,2]', ?, ?, '旧时间线', 2, 99, ?, ?, ?)
            """,
            (
                PROJECT,
                "b" * 64,
                json.dumps(legacy_segments, ensure_ascii=False),
                json.dumps({"segmentationMode": "app_interval_v1"}),
                first_ms,
                first_ms,
            ),
        )
        conn.commit()

    @staticmethod
    def _embedding_environment() -> dict[str, str]:
        return {
            **os.environ,
            "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
            "RAG_IME_EMBEDDING_DIMENSIONS": "16",
        }


if __name__ == "__main__":
    unittest.main()
