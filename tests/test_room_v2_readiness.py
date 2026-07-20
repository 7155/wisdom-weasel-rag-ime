from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_room_capabilities import RoomCapabilityManifestStore, room_runtime_registry
from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_service import _room_delivery_gate_enforcement, _room_kernel_mode_from_environment
from rag_ime.db.migration_runner import DEFAULT_MIGRATIONS_DIR, apply_database_migrations, load_migrations


ROOT = Path(__file__).resolve().parents[1]


class RoomV2ReadinessTests(unittest.TestCase):
    def test_clean_upgrade_from_65_to_83(self) -> None:
        with tempfile.TemporaryDirectory(prefix="room-v2-upgrade-") as directory:
            old_migrations = Path(directory) / "migrations-65"
            old_migrations.mkdir()
            for migration in load_migrations():
                if migration.version <= 65:
                    shutil.copy2(migration.path, old_migrations / migration.path.name)
            with closing(sqlite3.connect(":memory:")) as conn:
                baseline = apply_database_migrations(conn, migrations_dir=old_migrations, applied_at_ms=1)
                upgraded = apply_database_migrations(conn, applied_at_ms=2)
                self.assertEqual(baseline.current_version, 65)
                self.assertEqual(upgraded.current_version, 83)
                self.assertEqual(
                    upgraded.applied_versions,
                    tuple(migration.version for migration in load_migrations() if migration.version > 65),
                )
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_all_119_contract_sources_have_stable_hashes(self) -> None:
        schema_paths = sorted((ROOT / "rag_ime" / "contracts" / "json").glob("*.json"))
        hashes = {}
        for path in schema_paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            hashes[path.name] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(len(hashes), 119)
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))

    def test_capability_probe_and_no_binding_smoke(self) -> None:
        with tempfile.TemporaryDirectory(prefix="room-v2-capability-") as directory:
            path = Path(directory) / "ordinary.sqlite"
            result = RoomCapabilityManifestStore(path).compile_manifest(
                manifest_id="none",
                room_binding=None,
                participant_binding=None,
                dispatch_id="dispatch:none",
                runtime_registry=room_runtime_registry(),
                user_authorized=(),
                template_allowed=(),
                role_allowed=(),
                profile_allowed=(),
                state_allowed=(),
                created_at_ms=1,
            )
            self.assertIsNone(result)
            self.assertFalse(path.exists())
            self.assertEqual(tuple(room_runtime_registry()), ("room_state", "room_post", "room_commit"))

    def test_default_off_cohort_gate_and_rollback_switch(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_room_kernel_mode_from_environment(), "off")
        with patch.dict(os.environ, {"RAG_IME_ROOM_KERNEL_MODE": "cohort"}, clear=True):
            self.assertEqual(_room_kernel_mode_from_environment(), "shadow")
        with patch.dict(
            os.environ,
            {"RAG_IME_ROOM_KERNEL_MODE": "cohort", "RAG_IME_ROOM_KERNEL_COHORT_ID": "room-v2-test"},
            clear=True,
        ):
            self.assertEqual(_room_kernel_mode_from_environment(), "cohort")
            self.assertTrue(_room_delivery_gate_enforcement("cohort"))
        with patch.dict(os.environ, {"RAG_IME_ROOM_KERNEL_COHORT_ID": "production"}, clear=True):
            self.assertFalse(_room_delivery_gate_enforcement("cohort"))
        with tempfile.TemporaryDirectory(prefix="room-v2-off-") as directory:
            store = RoomKernelStore(Path(directory) / "off.sqlite", mode="off")
            store.initialize()
            command, created = store.normalize_compatibility_entry(
                {"dispatchId": "dispatch:off"},
                room_binding_ref=None,
                source_kind="tool",
                source_id="tool:off",
                now_ms=1,
            )
            self.assertIsNone(command)
            self.assertFalse(created)
            self.assertIsNone(store.lease_next(now_ms=1, ttl_ms=1000))


if __name__ == "__main__":
    unittest.main()
