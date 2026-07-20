from __future__ import annotations

import hashlib
import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.db.migration_runner import (
    DEFAULT_MIGRATIONS_DIR,
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
                    31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
                    41, 42, 43, 44, 45, 46, 47,
                    51, 52, 53, 54, 55, 56, 57, 58, 59, 60,
                    61, 62, 63, 64, 65, 66, 67, 70, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 86,
                ),
            )
            self.assertEqual(second.applied_versions, ())
            self.assertEqual(status["currentVersion"], 86)
            self.assertEqual(status["pendingVersions"], [])
            self.assertTrue(status["ok"])
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("schema_migrations", tables)
            self.assertIn("memory_feedback_events", tables)
            self.assertIn("memory_compile_state", tables)
            self.assertIn("runtime_config_state", tables)
            self.assertIn("management_settings", tables)
            self.assertIn("input_events", tables)
            self.assertIn("collaboration_profile_versions", tables)
            self.assertIn("collaboration_profile_active_pointers", tables)
            self.assertIn("room_v2_prompt_compile_receipts", tables)
            self.assertIn("room_v2_prompt_compare_diffs", tables)
            self.assertIn("room_v2_capability_manifests", tables)
            self.assertIn("room_v2_tool_disclosure_receipts", tables)
            self.assertIn("room_v2_tool_invocation_receipts", tables)
            self.assertIn("room_v2_requirement_anchors", tables)
            self.assertIn("room_v2_requirement_catalog_revisions", tables)
            self.assertIn("room_v2_verification_receipts", tables)
            self.assertIn("room_v2_delivery_gate_receipts", tables)
            self.assertIn("room_v2_peer_judgment_rounds", tables)
            self.assertIn("room_v2_peer_judgments", tables)
            self.assertIn("room_v2_conflict_matrix_revisions", tables)
            self.assertIn("room_v2_delivery_gate_preview_receipts", tables)
            self.assertIn("room_v2_incidents", tables)
            self.assertIn("room_v2_lesson_candidates", tables)
            self.assertIn("room_v2_guard_candidates", tables)
            self.assertIn("room_v2_guard_activation_receipts", tables)
            self.assertIn("room_v2_promotion_candidates", tables)
            self.assertIn("room_v2_knowledge_claim_versions", tables)
            self.assertIn("room_v2_knowledge_retrieval_receipts", tables)
            self.assertIn("room_v2_external_import_intakes", tables)
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
            self.assertIn("agent_subagent_controls", tables)
            self.assertIn("agent_subagent_inbox", tables)
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
            self.assertIn("agent_plan_state_events", tables)
            self.assertIn("agent_thread_goal_events", tables)
            self.assertIn("agent_goal_completion_audits", tables)
            self.assertIn("agent_goal_usage_receipts", tables)
            self.assertIn("agent_context_traces", tables)
            self.assertIn("agent_context_trace_nodes", tables)
            self.assertIn("agent_context_items", tables)
            self.assertIn("agent_wake_schedules", tables)
            self.assertIn("agent_wake_runs", tables)
            self.assertIn("agent_observation_events", tables)
            self.assertIn("agent_command_receipts", tables)
            self.assertIn("agent_room_work_items", tables)
            self.assertIn("agent_room_work_events", tables)
            self.assertIn("agent_room_delivery_cursors", tables)
            self.assertIn("agent_role_books", tables)
            self.assertIn("daily_activity_timelines", tables)
            self.assertIn("personal_context_draft_decisions", tables)
            self.assertIn("agent_role_book_revisions", tables)
            self.assertIn("agent_role_book_activation_events", tables)
            self.assertIn("agent_memory_evidence", tables)
            self.assertIn("personal_context_consolidation_runs", tables)
            self.assertIn("personal_context_consolidation_cursors", tables)
            self.assertIn("memory_governance_proposals", tables)
            self.assertIn("memory_atom_evidence_links", tables)
            self.assertIn("memory_legacy_atom_migration_audit", tables)
            self.assertIn("agent_lifecycle_hook_policies", tables)
            self.assertIn("agent_lifecycle_hook_events", tables)
            self.assertIn("room_v2_shadow_observations", tables)
            self.assertIn("room_v2_shadow_legacy_refs", tables)
            self.assertIn("room_v2_shadow_quarantine", tables)
            self.assertIn("room_v2_context_entries", tables)
            self.assertIn("room_v2_posts", tables)
            self.assertIn("room_v2_provider_projection_journals", tables)
            self.assertIn("room_v2_provider_projection_items", tables)
            self.assertIn("room_v2_provider_projection_receipts", tables)
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
            self.assertIn("agent_observation_events", tables)
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
                    "role_id",
                    "role_version",
                }.issubset(memory_source_columns)
            )
            self.assertIn("project_context_enabled", session_columns)
            self.assertIn("pi_skills_enabled", session_columns)
            self.assertIn("codex_skills_enabled", session_columns)
            self.assertIn("role_book_revision_id", session_columns)
            for table, primary_key in (
                ("memory_items", "memory_id"),
                ("memory_atoms", "id"),
                ("memory_books", "book_id"),
                ("memory_retrieval_docs", "doc_id"),
            ):
                with self.subTest(table=table, primary_key=primary_key):
                    columns = {
                        row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                    }
                    self.assertIn(primary_key, columns)

                    self.assertIn("owner_kind", columns)
                    self.assertIn("owner_id", columns)
            command_receipt_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_command_receipts'"
            ).fetchone()[0]
            self.assertIn("'session_rewrite'", command_receipt_sql)
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

    def test_production_0062_history_stays_immutable_and_workflow_migrations_append(self) -> None:
        expected_history = {
            61: (
                "separate_activity_timeline_index",
                "fd7b2767870341e6551d232819d10edfab5a68b1e70ac89957e4672059a19b7c",
            ),
            62: (
                "retire_owner_umbrella_topic_books",
                "54207aee24349ffe2598b791208aa793500094c71dd317f3d68a678cda400baf",
            ),
        }
        with tempfile.TemporaryDirectory(prefix="rag-ime-production-0062-") as temporary:
            migrations_0062 = Path(temporary) / "migrations"
            migrations_0062.mkdir()
            for source in DEFAULT_MIGRATIONS_DIR.glob("*.sql"):
                version = int(source.name.split("_", 1)[0])
                if version <= 62:
                    shutil.copy2(source, migrations_0062 / source.name)

            with closing(sqlite3.connect(":memory:")) as conn:
                initial = apply_database_migrations(conn, migrations_dir=migrations_0062)
                self.assertEqual(initial.current_version, 62)
                for version, (name, checksum) in expected_history.items():
                    source = next(migrations_0062.glob(f"{version:04d}_*.sql"))
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), checksum)
                    self.assertEqual(
                        conn.execute(
                            "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                            (version,),
                        ).fetchone(),
                        (name, checksum),
                    )

                appended = apply_database_migrations(conn)
                self.assertEqual(appended.applied_versions, (63, 64, 65, 66, 67, 70, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 86))
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                status = migration_status(conn)
                self.assertTrue(status["ok"])
                self.assertEqual(status["currentVersion"], 86)

    def test_legacy_atoms_preserve_supersession_lineage_and_require_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-migrations-0058-") as temporary:
            migrations_0058 = Path(temporary) / "migrations"
            migrations_0058.mkdir()
            for source in DEFAULT_MIGRATIONS_DIR.glob("*.sql"):
                if source.name < "0059_":
                    shutil.copy2(source, migrations_0058 / source.name)

            with closing(sqlite3.connect(":memory:")) as conn:
                apply_database_migrations(conn, migrations_dir=migrations_0058)
                conn.executemany(
                    """
                    INSERT INTO input_events(
                        id, created_at_ms, source, committed_text, project
                    ) VALUES (?, ?, 'test', ?, 'wisdom-weasel-rag-ime')
                    """,
                    (
                        (1, 100, "旧事实证据"),
                        (2, 200, "新事实证据"),
                        (3, 300, "已遗忘证据"),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO memory_tombstones(
                        created_at_ms, target_type, target_value, reason, active
                    ) VALUES (350, 'source_event_id', '3', '测试遗忘', 1)
                    """
                )
                for atom_id, status, updated_at_ms, event_ids in (
                    ("atom:legacy-old", "active", 200, "[1]"),
                    ("atom:legacy-successor", "active", 300, "[2]"),
                    ("atom:legacy-tombstoned", "active", 400, "[3]"),
                    ("atom:legacy-unsupported", "active", 500, "[]"),
                    ("atom:legacy-hidden", "hidden", 600, "[]"),
                ):
                    conn.execute(
                        """
                        INSERT INTO memory_atoms(
                            id, kind, text, source_event_ids_json,
                            source_memory_ids_json, confidence, quality_score,
                            echo_risk, privacy_level, status,
                            created_at_ms, updated_at_ms
                        ) VALUES (?, 'project_fact', ?, ?, '[]', 0.8, 0.8,
                                  0.0, 'local', ?, 100, ?)
                        """,
                        (atom_id, atom_id, event_ids, status, updated_at_ms),
                    )
                conn.execute(
                    """
                    INSERT INTO memory_supersessions(
                        supersession_id, old_memory_id, new_memory_id, reason,
                        status, created_at_ms
                    ) VALUES (
                        'supersession:test', 'atom:legacy-old',
                        'atom:legacy-successor', '事实更新', 'active', 250
                    )
                    """
                )

                result = apply_database_migrations(conn)
                rows = {
                    str(row[0]): tuple(row[1:])
                    for row in conn.execute(
                        """
                        SELECT id, status, claim_key, lineage_id, claim_state,
                               valid_from_ms, valid_to_ms, supersedes_id
                        FROM memory_atoms
                        ORDER BY id
                        """
                    )
                }
                audit_rows = {
                    str(row[0]): tuple(row[1:])
                    for row in conn.execute(
                        """
                        SELECT atom_id, previous_status, previous_claim_state,
                               disposition, representation_status,
                               representation_claim_state, reason, created_at_ms
                        FROM memory_legacy_atom_migration_audit
                        WHERE migration_version = 59
                        ORDER BY atom_id
                        """
                    )
                }

            self.assertEqual(
                result.applied_versions,
                (59, 60, 61, 62, 63, 64, 65, 66, 67, 70, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 86),
            )
            self.assertEqual(
                rows["atom:legacy-old"],
                (
                    "superseded",
                    "legacy:atom:legacy-successor",
                    "lineage:legacy:atom:legacy-successor",
                    "superseded",
                    100,
                    250,
                    None,
                ),
            )
            self.assertEqual(
                rows["atom:legacy-successor"],
                (
                    "active",
                    "legacy:atom:legacy-successor",
                    "lineage:legacy:atom:legacy-successor",
                    "current",
                    100,
                    None,
                    "atom:legacy-old",
                ),
            )
            self.assertEqual(rows["atom:legacy-tombstoned"][0], "hidden")
            self.assertEqual(rows["atom:legacy-tombstoned"][3], "retracted")
            self.assertEqual(rows["atom:legacy-unsupported"][0], "hidden")
            self.assertEqual(rows["atom:legacy-unsupported"][3], "retracted")
            self.assertEqual(rows["atom:legacy-hidden"][3:6], ("retracted", 100, 600))
            self.assertEqual(set(audit_rows), set(rows))
            self.assertEqual(
                {
                    value[2]
                    for value in audit_rows.values()
                },
                {
                    "quarantined_missing_visible_evidence",
                    "current_evidence_backed",
                    "superseded_history",
                },
            )
            self.assertEqual(
                audit_rows["atom:legacy-old"][:5],
                (
                    "active",
                    "current",
                    "superseded_history",
                    "superseded",
                    "superseded",
                ),
            )
            self.assertEqual(
                audit_rows["atom:legacy-successor"][:5],
                (
                    "active",
                    "current",
                    "current_evidence_backed",
                    "active",
                    "current",
                ),
            )
            quarantined = audit_rows["atom:legacy-unsupported"]
            self.assertEqual(
                quarantined[:5],
                (
                    "active",
                    "current",
                    "quarantined_missing_visible_evidence",
                    "hidden",
                    "retracted",
                ),
            )
            self.assertIn("not a user withdrawal", str(quarantined[5]))
            self.assertGreater(int(quarantined[6]), 0)

    def test_atom_first_migration_supersedes_preexisting_memory_book_draft(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-migrations-v38-") as tmp, closing(
            sqlite3.connect(":memory:")
        ) as conn, conn:
            migrations = Path(__file__).resolve().parents[1] / "rag_ime" / "db" / "migrations"
            migrations_v38 = Path(tmp)
            for source in sorted(migrations.glob("*.sql")):
                if int(source.name.split("_", 1)[0]) <= 38:
                    shutil.copy2(source, migrations_v38 / source.name)
            apply_database_migrations(
                conn,
                migrations_dir=migrations_v38,
            )
            conn.execute(
                """
                INSERT INTO memory_cleanup_runs(
                    run_id, created_at_ms, provider, model, status, summary, metadata_json
                ) VALUES (
                    'memory_book_legacy', 1, 'deepseek', 'legacy', 'draft', '旧草案',
                    '{"project":"wisdom-weasel-rag-ime"}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO memory_cleanup_diffs(
                    run_id, op, payload_json, status, created_at_ms
                ) VALUES ('memory_book_legacy', 'upsert_memory_atom', '{}', 'pending', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO memory_compile_state(
                    project, last_compiled_event_id, last_run_ms, pending_event_count,
                    last_bundle_hash, last_drafted_event_id, last_draft_ms,
                    last_draft_bundle_hash, last_draft_run_id
                ) VALUES (
                    'wisdom-weasel-rag-ime', 7, 1, 2, 'old', 9, 2, 'draft', 'memory_book_legacy'
                )
                """
            )

            result = apply_database_migrations(
                conn,
                migrations_dir=migrations,
            )

            self.assertEqual(
                result.applied_versions,
                (
                    39, 40, 41, 42, 43, 44, 45, 46, 47,
                    51, 52, 53, 54, 55, 56, 57, 58, 59, 60,
                    61, 62, 63, 64, 65, 66, 67, 70, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 86,
                ),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM memory_cleanup_runs WHERE run_id = 'memory_book_legacy'"
                ).fetchone()[0],
                "superseded",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM memory_cleanup_diffs WHERE run_id = 'memory_book_legacy'"
                ).fetchone()[0],
                "rejected",
            )
            state = conn.execute(
                """
                SELECT last_drafted_event_id, last_draft_ms,
                       last_draft_bundle_hash, last_draft_run_id
                FROM memory_compile_state
                WHERE project = 'wisdom-weasel-rag-ime'
                """
            ).fetchone()
            self.assertEqual(state, (0, 0, "", ""))

    def test_timeline_migration_archives_daily_books_and_enqueues_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-migrations-0061-") as temporary:
            migrations_0060 = Path(temporary) / "migrations"
            migrations_0060.mkdir()
            for source in DEFAULT_MIGRATIONS_DIR.glob("*.sql"):
                if source.name < "0061_":
                    shutil.copy2(source, migrations_0060 / source.name)

            with closing(sqlite3.connect(":memory:")) as conn:
                apply_database_migrations(conn, migrations_dir=migrations_0060)
                conn.execute(
                    """
                    INSERT INTO memory_books(
                        book_id, book_type, book_key, title, summary,
                        project, status, created_at_ms, updated_at_ms
                    ) VALUES (
                        'book:daily:test', 'daily', 'activity:2026-07-18',
                        '2026-07-18 活动时间线', '旧 Daily Book',
                        'wisdom-weasel-rag-ime', 'active', 10, 20
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO daily_activity_timelines(
                        timeline_id, project, timeline_date, status,
                        source_event_hash, approved_book_id,
                        created_at_ms, updated_at_ms
                    ) VALUES (
                        'timeline:test', 'wisdom-weasel-rag-ime',
                        '2026-07-18', 'approved', 'hash:test',
                        'book:daily:test', 10, 20
                    )
                    """
                )

                result = apply_database_migrations(conn)

                self.assertEqual(
                    result.applied_versions,
                    (61, 62, 63, 64, 65, 66, 67, 70, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 86),
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT status, archived_at_ms, archive_reason
                        FROM memory_books
                        WHERE book_id = 'book:daily:test'
                        """
                    ).fetchone(),
                    ("archived", 20, "migrated_to_timeline_index"),
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT approved_book_id
                        FROM daily_activity_timelines
                        WHERE timeline_id = 'timeline:test'
                        """
                    ).fetchone()[0],
                    "",
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT projection_kind, aggregate_type, aggregate_id,
                               operation, revision, state
                        FROM memory_projection_outbox
                        WHERE aggregate_id = '0061_separate_activity_timeline_index'
                        """
                    ).fetchone(),
                    (
                        "retrieval_docs",
                        "schema_migration",
                        "0061_separate_activity_timeline_index",
                        "rebuild",
                        61,
                        "pending",
                    ),
                )

    def test_thematic_book_migration_retires_only_redundant_owner_umbrella(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-migrations-0062-") as temporary:
            migrations_0061 = Path(temporary) / "migrations"
            migrations_0061.mkdir()
            for source in DEFAULT_MIGRATIONS_DIR.glob("*.sql"):
                if source.name < "0062_":
                    shutil.copy2(source, migrations_0061 / source.name)

            with closing(sqlite3.connect(":memory:")) as conn:
                apply_database_migrations(conn, migrations_dir=migrations_0061)
                conn.executemany(
                    """
                    INSERT INTO memory_books(
                        book_id, book_type, book_key, title, summary, project,
                        owner_kind, owner_id, status, created_at_ms, updated_at_ms
                    ) VALUES (?, 'topic', ?, ?, ?, ?, 'user', ?, 'active', 10, 20)
                    """,
                    (
                        (
                            "book:owner:with-topics",
                            "owner-with-topics",
                            "个人长期记忆",
                            "旧总书",
                            "wisdom-weasel-rag-ime",
                            "default",
                        ),
                        (
                            "book:owner:with-topics:topic:rag",
                            "owner-with-topics-topic-rag",
                            "记忆与 RAG 治理",
                            "主题书",
                            "wisdom-weasel-rag-ime",
                            "default",
                        ),
                        (
                            "book:owner:only-book",
                            "owner-only-book",
                            "个人长期记忆",
                            "唯一总书",
                            "other-project",
                            "other-user",
                        ),
                    ),
                )

                result = apply_database_migrations(conn)

                self.assertEqual(
                    result.applied_versions,
                    (62, 63, 64, 65, 66, 67, 70, 71, 72, 73, 74, 75, 76, 77, 80, 81, 82, 83, 84, 86),
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT status, archived_at_ms, archive_reason
                        FROM memory_books
                        WHERE book_id = 'book:owner:with-topics'
                        """
                    ).fetchone(),
                    (
                        "archived",
                        20,
                        "migrated_to_thematic_topic_books",
                    ),
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT status
                        FROM memory_books
                        WHERE book_id = 'book:owner:only-book'
                        """
                    ).fetchone()[0],
                    "active",
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT operation, revision, state
                        FROM memory_projection_outbox
                        WHERE aggregate_id =
                              '0062_retire_owner_umbrella_topic_books'
                        """
                    ).fetchone(),
                    ("rebuild", 62, "pending"),
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
            self.assertEqual(columns["capture_metadata_json"][4], "'{}'")
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
