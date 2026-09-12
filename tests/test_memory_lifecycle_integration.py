"""Smoke tests against PAW's REAL migrations and owning APIs.

These are deliberately skipped in the patch-only review bundle. A skip is not
integration verification: run them in the full checkout before merging.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from rag_ime.memory_lifecycle.common import connect
from rag_ime.memory_lifecycle.daily import generate
from rag_ime.memory_lifecycle.portability import export_project, import_bundle, records_bundle

FULL_CHECKOUT = importlib.util.find_spec("rag_ime.local_sqlite_core") is not None


@unittest.skipUnless(FULL_CHECKOUT, "full PAW checkout required; patch-only fixture is not integration verification")
class MemoryLifecycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        from rag_ime.local_sqlite_core import LocalSqliteCoreClient
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "paw.sqlite"
        self.core = LocalSqliteCoreClient(self.path)
        self.core.initialize(perform_maintenance=False)

    def test_real_migrations_and_private_core_input(self):
        from rag_ime.models import InputEvent
        event = InputEvent(
            event_id=None, created_at_ms=1789142400000,
            source="manual", committed_text="private sentinel must not enter Memory",
            privacy_disposition="allowed", project="PAW",
            capture_metadata={"privateWindow": True},
        )
        self.assertEqual(self.core.record_event(event), "skipped:private_context")
        with connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM agent_memory_evidence").fetchone()[0], 0)
            self.assertGreaterEqual(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 201)

    def test_real_evidence_owner_denies_session_only(self):
        from rag_ime.personal_context import AgentMemoryEvidenceStore
        store = AgentMemoryEvidenceStore(self.path, project="PAW")
        result = store.record(
            source_kind="user_message", source_id="private-message-1", text="session-only sentinel",
            metadata={"memoryRetention": "session_only"},
        )
        self.assertFalse(result["stored"])
        with connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM agent_memory_evidence").fetchone()[0], 0)

    def test_real_import_review_state_and_read_only_daily_report(self):
        packet = records_bundle(
            records=[{"id": "work-1", "text": "完成模块测试", "occurredAtMs": 1789142400000}],
            namespace="integration-fixture", project="PAW",
        )
        with connect(self.path) as conn:
            imported = import_bundle(conn, packet, target_project="PAW", dry_run=False)
            self.assertTrue(imported["ok"])
            self.assertEqual(conn.execute("SELECT admission_state FROM agent_memory_evidence").fetchone()[0], "needs_review")
            self.assertEqual(conn.execute("SELECT count(*) FROM memory_atoms").fetchone()[0], 0)
            replay = import_bundle(conn, packet, target_project="PAW", dry_run=False)
            self.assertTrue(replay["ok"])
            self.assertEqual(len(export_project(conn, project="PAW")["evidence"]), 1)
            before = conn.total_changes
            report = generate(conn, project="PAW", day="2026-09-11", timezone="UTC", include_timeline=False)
            self.assertEqual(report["evidence"], [])  # Import does not auto-admit.
            self.assertFalse(report["metadata"]["writesBackToMemory"])
            self.assertEqual(before, conn.total_changes)
