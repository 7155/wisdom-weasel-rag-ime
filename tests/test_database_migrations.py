from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.db.migration_runner import (
    MigrationChecksumError,
    apply_database_migrations,
    migration_status,
)


class DatabaseMigrationTests(unittest.TestCase):
    def test_empty_database_applies_all_migrations_idempotently(self) -> None:
        with closing(sqlite3.connect(":memory:")) as conn, conn:
            first = apply_database_migrations(conn, applied_at_ms=123)
            second = apply_database_migrations(conn, applied_at_ms=456)
            status = migration_status(conn)

            self.assertEqual(
                first.applied_versions,
                (
                    1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                    11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
                    21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
                    31, 32, 33, 34, 35, 36, 37, 40, 41,
                    42, 43, 44,
                ),
            )
            self.assertEqual(second.applied_versions, ())
            self.assertEqual(status["currentVersion"], 44)
            self.assertEqual(status["pendingVersions"], [])
            self.assertTrue(status["ok"])
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("schema_migrations", tables)
            self.assertIn("memory_feedback_events", tables)
            self.assertIn("memory_compile_state", tables)
            self.assertIn("runtime_config_state", tables)
            self.assertIn("management_settings", tables)
            self.assertIn("input_events", tables)
            self.assertIn("memory_items", tables)
            self.assertIn("memory_books", tables)
            self.assertIn("memory_group_overrides", tables)
            self.assertIn("memory_tag_profiles", tables)
            self.assertIn("memory_semantic_groups", tables)
            self.assertIn("memory_semantic_group_members", tables)
            self.assertIn("planning_daily", tables)
            self.assertIn("planning_assistant_messages", tables)
            self.assertIn("memory_supersessions", tables)
            self.assertIn("agent_sessions", tables)
            self.assertIn("agent_approvals", tables)
            self.assertIn("agent_runtime_events", tables)
            self.assertIn("agent_memory_sources", tables)
            self.assertIn("memory_source_disposition_events", tables)
            self.assertIn("memory_curation_cursors", tables)
            self.assertIn("agent_media", tables)
            self.assertIn("agent_message_media", tables)
            self.assertIn("agent_rooms", tables)
            self.assertIn("agent_room_participants", tables)
            self.assertIn("agent_room_events", tables)
            self.assertIn("agent_room_topics", tables)
            self.assertIn("agent_room_artifacts", tables)
            self.assertIn("agent_subagent_batches", tables)
            self.assertIn("agent_subagent_runs", tables)
            self.assertIn("agent_subagent_events", tables)
            self.assertIn("agent_runtime_bindings", tables)
            self.assertIn("agent_configuration_state", tables)
            self.assertIn("agent_control_events", tables)
            self.assertIn("agent_artifacts", tables)
            self.assertIn("agent_artifact_snapshots", tables)
            self.assertIn("agent_room_intercom_messages", tables)
            self.assertIn("management_work_previews", tables)
            self.assertIn("management_work_receipts", tables)
            self.assertIn("agent_personas", tables)
            self.assertIn("agent_role_runtime_preferences", tables)
            self.assertIn("agent_session_tool_policies", tables)
            self.assertIn("agent_plan_events", tables)
            self.assertIn("agent_context_traces", tables)
            self.assertIn("agent_context_trace_nodes", tables)
            self.assertIn("agent_context_items", tables)
            self.assertIn("agent_wake_schedules", tables)
            self.assertIn("agent_wake_runs", tables)
            self.assertIn("agent_command_receipts", tables)
            room_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(agent_rooms)")
            }
            participant_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(agent_room_participants)")
            }
            self.assertIn("workspace_roots_json", room_columns)
            self.assertIn("routing_mode", room_columns)
            self.assertIn("active_topic_id", room_columns)
            self.assertIn("collaboration_role", participant_columns)
            session_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(agent_sessions)")
            }
            self.assertIn("session_kind", session_columns)
            memory_source_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(agent_memory_sources)")
            }
            self.assertTrue(
                {
                    "owner_kind",
                    "owner_id",
                    "source_kind",
                    "trust_class",
                    "disposition",
                    "coverage_end_entry_id",
                }.issubset(memory_source_columns)
            )
            run_foreign_keys = {
                str(row[3]): (str(row[2]), str(row[6]))
                for row in conn.execute("PRAGMA foreign_key_list(agent_subagent_runs)")
            }
            self.assertNotIn("child_session_id", run_foreign_keys)
            self.assertEqual(run_foreign_keys["batch_id"], ("agent_subagent_batches", "CASCADE"))
            persona_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(agent_personas)")
            }
            self.assertTrue(
                {
                    "persona_prompt",
                    "safety_policy_prompt",
                    "tool_policy_json",
                    "tool_profile_version",
                }.issubset(persona_columns)
            )

    def test_legacy_feedback_table_is_rebuilt_without_losing_rows(self) -> None:
        with closing(sqlite3.connect(":memory:")) as conn, conn:
            conn.execute(
                """
                CREATE TABLE memory_feedback_events (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT,
                    candidate_text TEXT NOT NULL,
                    candidate_source TEXT NOT NULL,
                    action TEXT NOT NULL,
                    context_hash TEXT,
                    front_app_bundle_id TEXT,
                    raw_input TEXT,
                    preedit TEXT,
                    committed_tail TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO memory_feedback_events(id, candidate_text, candidate_source, action, created_at_ms) VALUES ('one', '候选', 'rag', 'shown', 7)"
            )

            apply_database_migrations(conn)

            row = conn.execute(
                "SELECT id, candidate_text, candidate_source FROM memory_feedback_events"
            ).fetchone()
            self.assertEqual(row, ("one", "候选", "rag"))
            columns = {item[1]: item for item in conn.execute("PRAGMA table_info(memory_feedback_events)")}
            self.assertEqual(columns["candidate_text"][4], "''")
            self.assertEqual(columns["candidate_source"][4], "'unknown'")

    def test_legacy_input_events_gain_context_group_columns_without_data_loss(self) -> None:
        with closing(sqlite3.connect(":memory:")) as conn, conn:
            conn.execute(
                """
                CREATE TABLE input_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_ms INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    committed_text TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO input_events(created_at_ms, source, committed_text) VALUES (1, 'legacy', '保留内容')"
            )

            apply_database_migrations(conn)

            columns = {item[1]: item for item in conn.execute("PRAGMA table_info(input_events)")}
            self.assertEqual(columns["context_group_id"][4], "''")
            self.assertEqual(columns["context_group_level"][4], "'app'")
            self.assertEqual(conn.execute("SELECT committed_text FROM input_events").fetchone()[0], "保留内容")

    def test_checksum_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-migrations-") as tmp:
            root = Path(tmp)
            migration = root / "0001_initial.sql"
            migration.write_text("CREATE TABLE sample(id INTEGER PRIMARY KEY);\n", encoding="utf-8")
            with closing(sqlite3.connect(":memory:")) as conn, conn:
                apply_database_migrations(conn, migrations_dir=root)
                migration.write_text("CREATE TABLE changed(id INTEGER PRIMARY KEY);\n", encoding="utf-8")

                with self.assertRaises(MigrationChecksumError):
                    apply_database_migrations(conn, migrations_dir=root)


if __name__ == "__main__":
    unittest.main()
