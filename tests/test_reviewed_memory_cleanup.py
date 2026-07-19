from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.db.migration_runner import apply_database_migrations
from rag_ime.reviewed_memory_cleanup import (
    REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION,
    ReviewedMemoryCleanupError,
    apply_reviewed_memory_cleanup,
    reviewed_memory_catalog_fingerprint,
)


PROJECT = "wisdom-weasel-rag-ime"


class ReviewedMemoryCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-reviewed-cleanup-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        with closing(sqlite3.connect(self.db_path)) as conn:
            apply_database_migrations(conn)
            self._seed(conn)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reviewed_cleanup_preserves_raw_governance_and_role_book_state(self) -> None:
        protected_tables = (
            "input_events",
            "agent_memory_evidence",
            "memory_governance_proposals",
            "memory_atom_evidence_links",
            "agent_role_books",
            "agent_role_book_revisions",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            before = {
                table: self._rows(conn, table)
                for table in protected_tables
            }
            result = apply_reviewed_memory_cleanup(
                conn,
                plan=self._plan(conn),
                reviewer_id="test-reviewer",
            )
            after = {
                table: self._rows(conn, table)
                for table in protected_tables
            }

            self.assertTrue(result["ok"])
            self.assertEqual(before, after)
            self.assertEqual(result["verification"]["unclosedSourceCount"], 0)
            self.assertEqual(
                conn.execute(
                    """SELECT COUNT(*) FROM agent_memory_sources
                       WHERE disposition IN ('pending', 'needs_review')"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                tuple(
                    conn.execute(
                        "SELECT status, claim_state FROM memory_atoms WHERE id='atom:duplicate'"
                    ).fetchone()
                ),
                ("superseded", "superseded"),
            )
            book = conn.execute(
                """SELECT summary, memory_atom_ids_json, source_event_ids_json
                   FROM memory_books WHERE book_id='book:memory'"""
            ).fetchone()
            self.assertEqual(book["summary"], "记忆系统只保留可验证的稳定事实。")
            self.assertEqual(json.loads(book["memory_atom_ids_json"]), ["atom:keep"])
            self.assertEqual(json.loads(book["source_event_ids_json"]), [1])
            timeline = conn.execute(
                """SELECT segment_count, source_event_ids_json, summary_text
                   FROM daily_activity_timelines WHERE timeline_id='timeline:day'"""
            ).fetchone()
            self.assertEqual(timeline["segment_count"], 1)
            self.assertEqual(json.loads(timeline["source_event_ids_json"]), [1, 2])
            self.assertEqual(timeline["summary_text"], "完成记忆数据库治理整理。")

    def test_timeline_identity_drift_fails_closed(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            plan = self._plan(conn)
            plan["timelines"][0]["expectedTimelineId"] = "timeline:stale"
            before = {
                "atoms": self._rows(conn, "memory_atoms"),
                "books": self._rows(conn, "memory_books"),
                "timelines": self._rows(conn, "daily_activity_timelines"),
                "sources": self._rows(conn, "agent_memory_sources"),
            }
            with self.assertRaisesRegex(
                ReviewedMemoryCleanupError,
                "timeline identity drifted",
            ):
                apply_reviewed_memory_cleanup(
                    conn,
                    plan=plan,
                    reviewer_id="test-reviewer",
                )
            after = {
                "atoms": self._rows(conn, "memory_atoms"),
                "books": self._rows(conn, "memory_books"),
                "timelines": self._rows(conn, "daily_activity_timelines"),
                "sources": self._rows(conn, "agent_memory_sources"),
            }
            self.assertEqual(before, after)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_cleanup_runs").fetchone()[0],
                0,
            )

    def test_stale_catalog_and_implicit_source_rewrite_are_blocked(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            stale_plan = self._plan(conn)
            conn.execute(
                "UPDATE memory_books SET summary='并发更新后的摘要' WHERE book_id='book:memory'"
            )
            conn.commit()

            with self.assertRaisesRegex(
                ReviewedMemoryCleanupError,
                "catalog drifted",
            ):
                apply_reviewed_memory_cleanup(
                    conn,
                    plan=stale_plan,
                    reviewer_id="test-reviewer",
                )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_cleanup_runs").fetchone()[0],
                0,
            )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            plan = self._plan(conn)
            plan["sourceDispositionPolicy"] = "preserve"
            before = dict(
                conn.execute(
                    "SELECT source_id, disposition FROM agent_memory_sources"
                ).fetchall()
            )
            result = apply_reviewed_memory_cleanup(
                conn,
                plan=plan,
                reviewer_id="test-reviewer",
            )
            after = dict(
                conn.execute(
                    "SELECT source_id, disposition FROM agent_memory_sources"
                ).fetchall()
            )
            self.assertEqual(before, after)
            self.assertEqual(result["sourceDispositions"]["policy"], "preserve")
            self.assertEqual(result["sourceDispositions"]["changed"], 0)

    @staticmethod
    def _rows(conn: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
        return [
            tuple(row[column] for column in columns)
            for row in conn.execute(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}"
            )
        ]

    @staticmethod
    def _plan(conn: sqlite3.Connection) -> dict[str, object]:
        return {
            "schemaVersion": REVIEWED_MEMORY_CLEANUP_SCHEMA_VERSION,
            "project": PROJECT,
            "summary": "reviewed cleanup test",
            "expectedCatalogSha256": reviewed_memory_catalog_fingerprint(
                conn,
                project=PROJECT,
            ),
            "sourceDispositionPolicy": "reconcile_all_active",
            "retireAtoms": [
                {
                    "id": "atom:duplicate",
                    "expectedText": "记忆系统只保留稳定事实。",
                    "mode": "supersede",
                    "replacementId": "atom:keep",
                    "reason": "exact duplicate",
                }
            ],
            "addAtoms": [],
            "books": [
                {
                    "id": "book:memory",
                    "summary": "记忆系统只保留可验证的稳定事实。",
                    "tags": ["记忆治理"],
                }
            ],
            "timelines": [
                {
                    "date": "2026-07-19",
                    "expectedTimelineId": "timeline:day",
                    "summary": "完成记忆数据库治理整理。",
                    "segments": [
                        {
                            "eventIds": [1, 2],
                            "title": "整理记忆数据库",
                            "goal": "清除噪声并保留证据",
                            "actualActions": "合并重复原子并压缩主题书",
                            "resultOrBlocker": "完成候选数据库验证",
                            "period": "day",
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def _seed(conn: sqlite3.Connection) -> None:
        now = 1_784_400_000_000
        texts = ("记忆系统只保留稳定事实。", "重复表达与临时流程不进入长期记忆。")
        for index, text in enumerate(texts, start=1):
            conn.execute(
                """INSERT INTO input_events(
                       id, created_at_ms, source, committed_text, app, project,
                       tags_json, context_group_id, context_group_level,
                       capture_metadata_json
                   ) VALUES (?, ?, 'squirrel_input_segment', ?, 'Codex', ?,
                             '[]', 'app:codex', 'app', '{}')""",
                (index, now + index, text, PROJECT),
            )
        conn.execute(
            """INSERT INTO agent_sessions(
                   id, title, session_mode, role_id, role_version, model_profile,
                   tool_profile_version, created_at_ms, updated_at_ms,
                   last_opened_at_ms, status
               ) VALUES ('session:test', 'test', 'assistant', 'zhiyou-v1', 'v1',
                         'test', 'test', ?, ?, ?, 'idle')""",
            (now, now, now),
        )
        for index, disposition in ((1, "pending"), (2, "needs_review")):
            digest = hashlib.sha256(texts[index - 1].encode("utf-8")).hexdigest()
            conn.execute(
                """INSERT INTO agent_memory_sources(
                       source_id, session_id, pi_entry_id, input_event_id,
                       source_role, canonical_text_sha256, created_at_ms,
                       role_id, role_version, disposition, metadata_json
                   ) VALUES (?, 'session:test', ?, ?, 'user', ?, ?,
                             'zhiyou-v1', 'v1', ?, '{}')""",
                (f"source:{index}", f"entry:{index}", index, digest, now + index, disposition),
            )
        digest = hashlib.sha256(texts[0].encode("utf-8")).hexdigest()
        conn.execute(
            """INSERT INTO agent_memory_evidence(
                   evidence_id, project, role_id, session_id, source_kind,
                   source_id, idempotency_key, content_text, content_sha256,
                   provenance_json, metadata_json, privacy_class, status,
                   occurred_at_ms, recorded_at_ms
               ) VALUES ('evidence:1', ?, 'zhiyou-v1', 'session:test',
                         'user_message', 'entry:1', 'evidence:1', ?, ?,
                         '{"inputEventId":1}', '{}', 'local', 'active', ?, ?)""",
            (PROJECT, texts[0], digest, now, now),
        )
        conn.execute(
            """INSERT INTO memory_governance_proposals(
                   proposal_id, session_id, project, operation, memory_kind,
                   proposed_text, reason, evidence_ids_json,
                   evidence_snapshot_json, action_json, payload_sha256,
                   idempotency_key, status, applied_memory_id,
                   created_at_ms, expires_at_ms, updated_at_ms, applied_at_ms
               ) VALUES ('proposal:1', 'session:test', ?, 'remember_preview',
                         'project_decision', ?, 'reviewed', '["evidence:1"]',
                         '{}', '{}', ?, 'proposal:1', 'applied', 'atom:keep',
                         ?, ?, ?, ?)""",
            (PROJECT, texts[0], "a" * 64, now, now + 1000, now, now),
        )
        for atom_id, claim_key in (
            ("atom:keep", "memory-policy"),
            ("atom:duplicate", "memory-policy-duplicate"),
        ):
            conn.execute(
                """INSERT INTO memory_atoms(
                       id, kind, text, canonical_text, source_event_ids_json,
                       source_memory_ids_json, scope_project, status,
                       created_at_ms, updated_at_ms, claim_key, lineage_id,
                       claim_state, valid_from_ms
                   ) VALUES (?, 'project_decision', ?, ?, '[1]', '["source:1"]',
                             ?, 'active', ?, ?, ?, 'lineage:memory',
                             'current', ?)""",
                (atom_id, texts[0], texts[0], PROJECT, now, now, claim_key, now),
            )
        conn.execute(
            """INSERT INTO memory_atom_evidence_links(
                   memory_atom_id, evidence_id, proposal_id, relation,
                   content_sha256, provenance_json, created_at_ms
               ) VALUES ('atom:keep', 'evidence:1', 'proposal:1', 'supports', ?, '{}', ?)""",
            (digest, now),
        )
        conn.execute(
            """INSERT INTO memory_books(
                   book_id, book_type, book_key, title, summary, normalized_text,
                   project, source_event_ids_json, memory_atom_ids_json, status,
                   created_at_ms, updated_at_ms, metadata_json
               ) VALUES ('book:memory', 'topic', 'memory', '记忆治理', '旧摘要',
                         '旧摘要', ?, '[1]', '["atom:keep","atom:duplicate"]',
                         'active', ?, ?, '{}')""",
            (PROJECT, now, now),
        )
        conn.execute(
            """INSERT INTO daily_activity_timelines(
                   timeline_id, project, timeline_date, timezone, status,
                   source_event_ids_json, source_event_hash, segments_json,
                   summary_text, event_count, segment_count, metadata_json,
                   created_at_ms, updated_at_ms
               ) VALUES ('timeline:day', ?, '2026-07-19', 'Asia/Shanghai',
                         'approved', '[1]', ?, '[]', '旧时间线', 1, 1, '{}', ?, ?)""",
            (PROJECT, "b" * 64, now, now),
        )
        conn.execute(
            """INSERT INTO agent_role_books(
                   role_id, role_version, display_name, mission,
                   base_persona_version, created_at_ms, updated_at_ms
               ) VALUES ('zhiyou-v1', 'v1', '智鼬', '协助用户工作', 'base-v1', ?, ?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO agent_role_book_revisions(
                   revision_id, role_id, role_version, revision_number, status,
                   content_json, change_summary, proposed_by, created_at_ms,
                   activated_at_ms
               ) VALUES ('role-revision:1', 'zhiyou-v1', 'v1', 1, 'active',
                         '{"mission":"协助用户工作"}', 'initial', 'user', ?, ?)""",
            (now, now),
        )
        conn.commit()


if __name__ == "__main__":
    unittest.main()
