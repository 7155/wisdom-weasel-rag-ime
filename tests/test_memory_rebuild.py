from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_rebuild import preview_memory_rebuild, rebuild_memory_database
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms


class MemoryRebuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-memory-rebuild-")
        self.core = LocalSqliteCoreClient(Path(self.temporary.name) / "rag-ime.sqlite")
        self.core.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rebuild_archives_fragments_without_guessing_missing_enter_boundaries(self) -> None:
        base = now_ms()
        event_ids = [
            self._event("我们正在", base, source="squirrel_rime_commit_burst"),
            self._event("彻底重建记忆功能。", base + 500, source="squirrel_rime_commit_burst"),
            self._event("ai", base + 10_000, source="squirrel_rime_commit_burst"),
        ]

        with self.core._connect() as conn:
            preview = preview_memory_rebuild(conn)
            self.assertEqual(preview["planned"]["legacyFragmentsToArchive"], 3)
            self.assertEqual(preview["planned"]["historicalSegmentsToCreate"], 0)
            report = rebuild_memory_database(conn)

            segments = conn.execute(
                "SELECT committed_text, app, tags_json FROM input_events WHERE source = 'squirrel_input_segment'"
            ).fetchall()
            deleted = conn.execute(
                "SELECT event_id FROM memory_state WHERE deleted = 1 ORDER BY event_id"
            ).fetchall()

        self.assertEqual(len(segments), 0)
        self.assertEqual([int(row["event_id"]) for row in deleted], event_ids)
        self.assertEqual(
            report["changes"]["inputSegments"]["recoveryPolicy"],
            "quarantined_without_enter_boundary",
        )

    def test_rebuild_preserves_but_quarantines_codex_history(self) -> None:
        event_id = self._event(
            "这是旧 Codex 会话原文，不应进入输入法索引。",
            now_ms(),
            source="codex_history",
        )
        with self.core._connect() as conn:
            timestamp = now_ms()
            conn.execute(
                """
                INSERT INTO memory_items(
                    memory_id, kind, text, normalized_text, source_event_id,
                    project, status, privacy_class, created_at_ms, updated_at_ms,
                    metadata_json
                ) VALUES (
                    'stable:codex-history', 'stable_memory',
                    '旧 Codex 会话记忆', '旧 codex 会话记忆', ?,
                    'wisdom-weasel-rag-ime', 'approved', 'local', ?, ?, '{}'
                )
                """,
                (event_id, timestamp, timestamp),
            )

            preview = preview_memory_rebuild(conn)
            report = rebuild_memory_database(conn)
            event_row = conn.execute(
                """
                SELECT e.id, s.deleted
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            item_status = conn.execute(
                "SELECT status FROM memory_items WHERE memory_id = 'stable:codex-history'"
            ).fetchone()[0]
            indexed = conn.execute(
                "SELECT COUNT(*) FROM memory_retrieval_docs WHERE source_id = 'stable:codex-history'"
            ).fetchone()[0]

        self.assertEqual(preview["planned"]["disabledSourceEventsToQuarantine"], 1)
        self.assertEqual(preview["planned"]["disabledSourceMemoryItemsToHide"], 1)
        self.assertEqual(int(event_row["id"]), event_id)
        self.assertEqual(int(event_row["deleted"]), 1)
        self.assertEqual(item_status, "hidden")
        self.assertEqual(indexed, 0)
        self.assertEqual(report["changes"]["disabledSources"]["eventsQuarantined"], 1)
        self.assertEqual(report["after"]["activeDisabledContextSourceEvents"], 0)

    def test_rebuild_cleans_transport_tags_without_hiding_semantic_atoms(self) -> None:
        event_id = self._event("用户要求普通 Agent 上下文不能包含单词碎片。", now_ms())
        with self.core._connect() as conn:
            timestamp = now_ms()
            conn.executemany(
                """
                INSERT INTO memory_tags(
                    tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms,
                    description, source, status, metadata_json
                ) VALUES (?, ?, 'concept', ?, ?, ?, ?, ?, ?, '{}')
                """,
                (
                    ("legacy-noise", "legacy-noise", 0.55, timestamp, timestamp, "", "legacy_auto", "hidden"),
                    ("rime-commit", "rime-commit", 0.55, timestamp, timestamp, "", "dsv4", "active"),
                    ("获取", "获取", 0.55, timestamp, timestamp, "", "dsv4", "active"),
                    ("输入法", "输入法", 0.55, timestamp, timestamp, "", "dsv4", "active"),
                ),
            )
            self._atom(
                conn,
                "archive-noise",
                kind="source_event_archive",
                text="弹出",
                source_event_ids=[event_id],
                quality=0.55,
            )
            self._atom(
                conn,
                "transient",
                kind="project_fact",
                text="究竟拿到前台上下文没有",
                source_event_ids=[event_id],
                quality=0.6,
            )
            self._atom(
                conn,
                "requirement",
                kind="project_fact",
                text="用户要求普通 Agent 上下文不能包含单词碎片。",
                source_event_ids=[event_id],
                quality=0.5,
            )

            report = rebuild_memory_database(conn)
            tags = {
                str(row["tag"]): str(row["status"])
                for row in conn.execute("SELECT tag, status FROM memory_tags").fetchall()
            }
            atoms = {
                str(row["id"]): (str(row["status"]), str(row["scope_app"] or ""))
                for row in conn.execute("SELECT id, status, scope_app FROM memory_atoms").fetchall()
            }

        self.assertNotIn("legacy-noise", tags)
        self.assertNotIn("rime-commit", tags)
        self.assertEqual(tags["获取"], "hidden")
        self.assertEqual(tags["输入法"], "active")
        self.assertEqual(atoms["archive-noise"][0], "hidden")
        self.assertEqual(atoms["transient"], ("active", "com.openai.codex"))
        self.assertEqual(atoms["requirement"], ("active", "com.openai.codex"))
        self.assertEqual(
            report["changes"]["atoms"]["reviewCandidateAtomIds"],
            ["transient"],
        )
        self.assertEqual(report["after"]["transportTagCount"], 0)

    def test_rebuild_merges_only_exact_duplicate_atoms_and_moves_references(self) -> None:
        event_id = self._event("这是用于验证完全重复原子合并的完整输入。", now_ms())
        with self.core._connect() as conn:
            self._atom(
                conn,
                "atom-a",
                kind="project_fact",
                text="普通 Agent 上下文不得注入单词碎片。",
                canonical="普通 Agent 上下文不得注入单词碎片。",
                source_event_ids=[event_id],
                quality=0.9,
            )
            self._atom(
                conn,
                "atom-b",
                kind="project_fact",
                text="普通 Agent 上下文不得注入单词碎片。",
                canonical="普通 Agent 上下文不得注入单词碎片。",
                source_event_ids=[event_id + 1],
                quality=0.7,
            )
            conn.execute(
                """
                INSERT INTO memory_aliases(id, memory_atom_id, alias, alias_type, weight, created_at_ms)
                VALUES ('alias-b', 'atom-b', '碎片门禁', 'keyword', 0.8, ?)
                """,
                (now_ms(),),
            )

            report = rebuild_memory_database(conn)
            atoms = conn.execute("SELECT id, source_event_ids_json FROM memory_atoms ORDER BY id").fetchall()
            alias_owner = conn.execute("SELECT memory_atom_id FROM memory_aliases WHERE id = 'alias-b'").fetchone()[0]

        self.assertEqual([str(row["id"]) for row in atoms], ["atom-a"])
        self.assertEqual(json.loads(atoms[0]["source_event_ids_json"]), [event_id, event_id + 1])
        self.assertEqual(alias_owner, "atom-a")
        self.assertEqual(report["changes"]["atoms"]["exactDuplicateAtomsRemoved"], 1)

    def test_rebuild_hides_transport_and_sentence_like_lexicon_phrases(self) -> None:
        with self.core._connect() as conn:
            timestamp = now_ms()
            conn.executemany(
                """
                INSERT INTO memory_items(
                    memory_id, kind, text, normalized_text, project, status,
                    privacy_class, created_at_ms, updated_at_ms, metadata_json
                ) VALUES (?, 'phrase', ?, ?, 'wisdom-weasel-rag-ime', 'approved',
                          'local', ?, ?, ?)
                """,
                (
                    (
                        "phrase:stable",
                        "候选稳定",
                        "候选稳定",
                        timestamp,
                        timestamp,
                        '{"source":"curated"}',
                    ),
                    (
                        "phrase:transport",
                        "弹出",
                        "弹出",
                        timestamp,
                        timestamp,
                        '{"tags":["rime-commit"]}',
                    ),
                    (
                        "phrase:sentence",
                        "闪电联想临时读取输入缓冲但不得直接写入长期记忆",
                        "闪电联想临时读取输入缓冲但不得直接写入长期记忆",
                        timestamp,
                        timestamp,
                        '{"source":"curated"}',
                    ),
                ),
            )

            preview = preview_memory_rebuild(conn)
            report = rebuild_memory_database(conn)
            statuses = {
                str(row["memory_id"]): str(row["status"])
                for row in conn.execute(
                    "SELECT memory_id, status FROM memory_items ORDER BY memory_id"
                ).fetchall()
            }

        self.assertEqual(preview["planned"]["transportPhraseFragmentsToHide"], 1)
        self.assertEqual(preview["planned"]["sentenceLikePhrasesToHide"], 1)
        self.assertEqual(statuses["phrase:stable"], "approved")
        self.assertEqual(statuses["phrase:transport"], "hidden")
        self.assertEqual(statuses["phrase:sentence"], "hidden")
        self.assertEqual(report["changes"]["phrases"]["transportFragmentsHidden"], 1)
        self.assertEqual(report["changes"]["phrases"]["sentenceLikePhrasesHidden"], 1)
        self.assertEqual(report["after"]["approvedPhraseItems"], 1)

    def test_rebuild_supersedes_draft_made_against_old_catalog(self) -> None:
        with self.core._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_cleanup_runs(
                    run_id, created_at_ms, provider, model, status, summary, metadata_json
                ) VALUES (
                    'memory_book_before_rebuild', 1, 'deepseek', 'legacy', 'draft',
                    '旧目录草案', '{"project":"wisdom-weasel-rag-ime"}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO memory_cleanup_diffs(
                    run_id, op, payload_json, status, created_at_ms
                ) VALUES (
                    'memory_book_before_rebuild', 'upsert_memory_atom', '{}', 'pending', 1
                )
                """
            )

            preview = preview_memory_rebuild(conn)
            report = rebuild_memory_database(conn)
            run_status = conn.execute(
                """
                SELECT status
                FROM memory_cleanup_runs
                WHERE run_id = 'memory_book_before_rebuild'
                """
            ).fetchone()[0]
            diff_status = conn.execute(
                """
                SELECT status
                FROM memory_cleanup_diffs
                WHERE run_id = 'memory_book_before_rebuild'
                """
            ).fetchone()[0]

        self.assertEqual(preview["planned"]["staleDraftsToSupersede"], 1)
        self.assertEqual(run_status, "superseded")
        self.assertEqual(diff_status, "rejected")
        self.assertEqual(report["after"]["pendingMemoryDrafts"], 0)
        self.assertEqual(report["changes"]["drafts"]["supersededDraftCount"], 1)

    def _event(self, text: str, created_at_ms: int, *, source: str = "manual") -> int:
        value = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=created_at_ms,
                source=source,
                committed_text=text,
                privacy_disposition="allowed",
                app="com.openai.codex",
                project="wisdom-weasel-rag-ime",
                context_group_id="app:codex",
            )
        )
        return int(value.split(":", 1)[1])

    @staticmethod
    def _atom(
        conn: object,
        atom_id: str,
        *,
        kind: str,
        text: str,
        source_event_ids: list[int],
        quality: float,
        canonical: str = "",
    ) -> None:
        timestamp = now_ms()
        conn.execute(
            """
            INSERT INTO memory_atoms(
                id, kind, text, canonical_text, source_event_ids_json, source_memory_ids_json,
                scope_app, scope_project, confidence, quality_score, echo_risk, privacy_level,
                status, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, '[]', '', 'wisdom-weasel-rag-ime', ?, ?, 0, 'local', 'active', ?, ?)
            """,
            (
                atom_id,
                kind,
                text,
                canonical,
                json.dumps(source_event_ids),
                quality,
                quality,
                timestamp,
                timestamp,
            ),
        )


if __name__ == "__main__":
    unittest.main()
