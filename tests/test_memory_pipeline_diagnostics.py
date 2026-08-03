from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.memory_pipeline_diagnostics import (
    build_memory_pipeline_recovery_preview,
    write_private_recovery_report,
)
from rag_ime.text_utils import compact_whitespace


ROOT = Path(__file__).resolve().parents[1]


class MemoryPipelineDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-memory-p0-")
        self.root = Path(self.temporary.name)
        self.current_db = self.root / "current.sqlite"
        self.backup_db = self.root / "backup.sqlite"
        self.migrations_dir = self.root / "migrations"
        self.migrations_dir.mkdir()
        migration_sql = "CREATE TABLE example(id INTEGER PRIMARY KEY);\n"
        (self.migrations_dir / "0001_example.sql").write_text(
            migration_sql,
            encoding="utf-8",
        )
        self.migration_checksum = hashlib.sha256(
            migration_sql.encode("utf-8")
        ).hexdigest()
        self._create_database(self.backup_db, backup=True)
        self._create_database(self.current_db, backup=False)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_preview_proves_exact_recovery_without_leaking_text(self) -> None:
        current_before = _file_state(self.current_db)
        backup_before = _file_state(self.backup_db)

        report = build_memory_pipeline_recovery_preview(
            self.current_db,
            self.backup_db,
            migrations_dir=self.migrations_dir,
            generated_at_ms=1234,
        )

        self.assertTrue(report["compatibility"]["eventPrefix"]["exact"])
        preview = report["migrationPreview"]
        self.assertEqual(preview["exactRecovery"]["sourceRows"]["count"], 1)
        self.assertEqual(preview["exactRecovery"]["auditRows"]["count"], 1)
        self.assertEqual(preview["newPendingCandidate"]["events"]["count"], 1)
        self.assertEqual(preview["quarantine"]["legacyFragmentEvents"]["count"], 1)
        self.assertEqual(preview["retireRebind"]["atoms"]["count"], 1)
        self.assertEqual(preview["retireRebind"]["books"]["count"], 1)
        self.assertEqual(preview["noOp"]["sourceRowsAlreadyIdentical"]["count"], 1)
        self.assertEqual(preview["noOp"]["auditRowsAlreadyIdentical"]["count"], 1)
        self.assertEqual(preview["noOp"]["currentOnlySourceRowsPreserved"]["count"], 1)
        self.assertTrue(report["readiness"]["zeroMutationProof"])
        self.assertTrue(report["readiness"]["exactRecoveryCompatible"])
        self.assertFalse(report["readiness"]["productionApplyAllowed"])
        self.assertEqual(report["generatedAtMs"], 1234)
        self.assertEqual(_file_state(self.current_db), current_before)
        self.assertEqual(_file_state(self.backup_db), backup_before)

        serialized = json.dumps(report, ensure_ascii=False)
        for private_text in (
            "only the user knows this alpha",
            "new finalized private sentence",
            "legacy partial private sentence",
            "project-specific private atom",
        ):
            self.assertNotIn(private_text, serialized)

    def test_mismatched_event_blocks_exact_source_recovery(self) -> None:
        with sqlite3.connect(self.current_db) as conn, conn:
            conn.execute(
                "UPDATE input_events SET committed_text=? WHERE id=3",
                ("different current private text",),
            )

        report = build_memory_pipeline_recovery_preview(
            self.current_db,
            self.backup_db,
            migrations_dir=self.migrations_dir,
            generated_at_ms=1234,
        )

        self.assertFalse(report["compatibility"]["eventPrefix"]["exact"])
        self.assertEqual(
            report["migrationPreview"]["quarantine"][
                "backupSourcesWithIncompatibleEvent"
            ]["count"],
            1,
        )
        self.assertFalse(report["readiness"]["exactRecoveryCompatible"])

    def test_private_report_is_exclusive_mode_0600(self) -> None:
        report = build_memory_pipeline_recovery_preview(
            self.current_db,
            self.backup_db,
            migrations_dir=self.migrations_dir,
            generated_at_ms=1234,
        )
        output = self.root / "private" / "preview.json"

        written = write_private_recovery_report(output, report)

        self.assertEqual(written, output.resolve())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            write_private_recovery_report(output, report)

    def test_static_zero_wal_bundle_does_not_touch_shared_memory(self) -> None:
        wal = Path(str(self.backup_db) + "-wal")
        shared_memory = Path(str(self.backup_db) + "-shm")
        wal.write_bytes(b"")
        shared_memory.write_bytes(b"settled-shared-memory-marker")
        os.chmod(wal, 0o600)
        os.chmod(shared_memory, 0o600)
        os.utime(shared_memory, ns=(1_000_000_000, 1_000_000_000))
        before = _bundle_state(self.backup_db)

        report = build_memory_pipeline_recovery_preview(
            self.current_db,
            self.backup_db,
            migrations_dir=self.migrations_dir,
            generated_at_ms=1234,
        )

        self.assertTrue(report["databases"]["backup"]["mutationProof"]["ok"])
        self.assertEqual(_bundle_state(self.backup_db), before)

    def test_cli_writes_summary_and_private_report(self) -> None:
        output = self.root / "cli-private" / "preview.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "preview_memory_pipeline_recovery.py"),
                "--current-db",
                str(self.current_db),
                "--backup-db",
                str(self.backup_db),
                "--migrations-dir",
                str(self.migrations_dir),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertTrue(summary["eventPrefixExact"])
        self.assertTrue(summary["zeroMutationProof"])
        self.assertEqual(summary["exactRecoverySourceRows"], 1)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def _create_database(self, path: Path, *, backup: bool) -> None:
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE input_events (
                    id INTEGER PRIMARY KEY,
                    created_at_ms INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    committed_text TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    app TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE agent_sessions (
                    id TEXT PRIMARY KEY
                );
                CREATE TABLE agent_memory_sources (
                    source_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    pi_entry_id TEXT NOT NULL,
                    input_event_id INTEGER NOT NULL REFERENCES input_events(id) ON DELETE CASCADE,
                    source_role TEXT NOT NULL,
                    source_revision INTEGER NOT NULL DEFAULT 1,
                    canonical_text_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at_ms INTEGER NOT NULL,
                    owner_kind TEXT NOT NULL DEFAULT 'user',
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    source_kind TEXT NOT NULL DEFAULT 'user_final',
                    disposition TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE memory_source_disposition_events (
                    event_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES agent_memory_sources(source_id) ON DELETE CASCADE,
                    previous_disposition TEXT NOT NULL,
                    new_disposition TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    actor_kind TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                );
                CREATE TABLE agent_memory_evidence (
                    evidence_id TEXT PRIMARY KEY
                );
                CREATE TABLE memory_atoms (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    scope_project TEXT,
                    owner_kind TEXT NOT NULL DEFAULT 'user',
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    source_event_ids_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE memory_books (
                    book_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    owner_kind TEXT NOT NULL DEFAULT 'user',
                    owner_id TEXT NOT NULL DEFAULT 'default'
                );
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at_ms INTEGER NOT NULL,
                    checksum TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT INTO schema_migrations VALUES (1, 'example', 1, ?)",
                (self.migration_checksum,),
            )
            conn.executemany(
                "INSERT INTO agent_sessions(id) VALUES (?)",
                [("session:backup",), ("session:current",)],
            )
            base_events = [
                (1, 100, "manual_commit", "only the user knows this alpha", "", "app", "[]"),
                (2, 200, "manual_commit", "second exact private row", "", "app", "[]"),
                (3, 300, "voice_final", "third exact private row", "", "app", "[]"),
            ]
            conn.executemany(
                "INSERT INTO input_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                base_events,
            )
            if not backup:
                conn.executemany(
                    "INSERT INTO input_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            4,
                            400,
                            "squirrel_input_segment",
                            "new finalized private sentence",
                            "project-a",
                            "app",
                            '["finalized"]',
                        ),
                        (
                            5,
                            500,
                            "squirrel_rime_commit_burst",
                            "legacy partial private sentence",
                            "project-a",
                            "app",
                            "[]",
                        ),
                        (6, 600, "manual_commit", "current preserved row", "", "app", "[]"),
                    ],
                )

            self._insert_source(
                conn,
                source_id="source:1",
                session_id="session:backup",
                event_id=1,
                text=base_events[0][3],
            )
            self._insert_audit(conn, event_id="audit:1", source_id="source:1")
            if backup:
                self._insert_source(
                    conn,
                    source_id="source:3",
                    session_id="session:backup",
                    event_id=3,
                    text=base_events[2][3],
                )
                self._insert_audit(conn, event_id="audit:3", source_id="source:3")
            else:
                self._insert_source(
                    conn,
                    source_id="current:6",
                    session_id="session:current",
                    event_id=6,
                    text="current preserved row",
                )
                self._insert_audit(conn, event_id="current-audit:6", source_id="current:6")
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                        id, status, scope_project, source_event_ids_json
                    ) VALUES (?, 'active', 'project-a', '[1]')
                    """,
                    ("project-specific private atom",),
                )
                conn.execute(
                    "INSERT INTO memory_books(book_id, status, project) VALUES (?, 'current', 'project-a')",
                    ("project-specific private book",),
                )
        os.chmod(path, 0o600)

    @staticmethod
    def _insert_source(
        conn: sqlite3.Connection,
        *,
        source_id: str,
        session_id: str,
        event_id: int,
        text: str,
    ) -> None:
        digest = hashlib.sha256(compact_whitespace(text).encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO agent_memory_sources(
                source_id, session_id, pi_entry_id, input_event_id,
                source_role, canonical_text_sha256, created_at_ms
            ) VALUES (?, ?, ?, ?, 'user', ?, ?)
            """,
            (source_id, session_id, f"entry:{event_id}", event_id, digest, event_id * 100),
        )

    @staticmethod
    def _insert_audit(
        conn: sqlite3.Connection,
        *,
        event_id: str,
        source_id: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO memory_source_disposition_events(
                event_id, source_id, previous_disposition, new_disposition,
                reason_code, actor_kind, created_at_ms
            ) VALUES (?, ?, '', 'pending', 'checkpoint_created', 'system', 1)
            """,
            (event_id, source_id),
        )


def _file_state(path: Path) -> tuple[int, int, int]:
    metadata = path.stat()
    return metadata.st_size, metadata.st_mtime_ns, metadata.st_ino


def _bundle_state(path: Path) -> tuple[tuple[str, int, int, int], ...]:
    result = []
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        metadata = candidate.stat()
        result.append(
            (suffix, metadata.st_size, metadata.st_mtime_ns, metadata.st_ino)
        )
    return tuple(result)


if __name__ == "__main__":
    unittest.main()
