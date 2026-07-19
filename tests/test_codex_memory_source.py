from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from rag_ime import codex_memory_source
from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.codex_memory_source import CodexMemorySourceImporter
from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.owner_memory_curation import (
    MAX_EXTERNAL_MODEL_INPUTS_PER_RUN,
    OwnerMemoryCurator,
    _build_owner_source_bundle,
)
from rag_ime.retrieval_docs import rebuild_retrieval_docs


NOW_MS = int(
    datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc).timestamp() * 1_000
)


class _CodexMemoryOrganizer:
    provider_name = "fixture"

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        inputs = [
            dict(item)
            for item in bundle.get("inputs") or []
            if isinstance(item, dict)
        ]
        event_ids = [
            int(event_id)
            for item in inputs
            for event_id in item.get("sourceEventIds") or []
        ]
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "agent_curated_external_memory",
                    "confidence": 0.5,
                }
                for item in inputs
            ],
            "memoryAtoms": [
                {
                    "canonicalText": "用户希望外部记忆保持分层、可追溯并按当前问题召回。",
                    "summary": "外部记忆采用分层索引和按需召回。",
                    "kind": "durable_preference",
                    "claimKey": "preference:external-memory:layered-recall",
                    "sourceEventIds": event_ids,
                    "confidence": 0.94,
                    "qualityScore": 0.94,
                    "directCandidateAllowed": False,
                }
            ],
            "topicBooks": [
                {
                    "title": "记忆与 RAG 治理",
                    "summary": "token: supersecret",
                    "sourceEventIds": event_ids,
                    "confidence": 0.92,
                    "qualityScore": 0.92,
                }
            ],
        }


class _EmptyCodexMemoryOrganizer:
    provider_name = "fixture"

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "needs_review",
                    "reasonCode": "model_omitted_source",
                    "confidence": 0.0,
                }
                for item in bundle.get("inputs") or []
            ],
            "memoryAtoms": [],
            "topicBooks": [],
        }


class CodexMemorySourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-codex-memory-"
        )
        root = Path(self.temporary.name)
        self.db_path = root / "rag-ime.sqlite"
        self.memory_root = root / "codex-memories"
        self.rollout_root = self.memory_root / "rollout_summaries"
        self.rollout_root.mkdir(parents=True)
        (self.memory_root / "memory_summary.md").write_text(
            """
# Codex Memory
## User preferences
- 用户希望记忆按 Evidence、Atom 与 Topic Book 分层。
- 当前问题应按需召回，不把原始对话直接塞进提示词。
""",
            encoding="utf-8",
        )
        recent_name = "2026-07-18T08-50-53-blU6-recent-memory.md"
        old_name = "2026-03-01T08-00-00-old-memory.md"
        (self.memory_root / "MEMORY.md").write_text(
            "\n".join(
                [
                    "# Registry",
                    (
                        f"- rollout_summaries/{recent_name} "
                        "(updated_at=2026-07-18T09:00:00+00:00, "
                        "thread_id=019f-test-recent, "
                        "rollout_path=/private/raw/recent.jsonl)"
                    ),
                    (
                        f"- rollout_summaries/{old_name} "
                        "(updated_at=2026-07-18T09:00:00+00:00, "
                        "thread_id=019f-test-old, "
                        "rollout_path=/private/raw/old.jsonl)"
                    ),
                ]
            ),
            encoding="utf-8",
        )
        (self.rollout_root / recent_name).write_text(
            """
# Persistent memory injection
Outcome: success
Key steps:
- 新 Session 将已治理记忆放进高优先级上下文。
- Timeline 只在明确时间意图时召回。
References:
- /Users/example/raw/session.jsonl
""",
            encoding="utf-8",
        )
        (self.rollout_root / old_name).write_text(
            "# Old memory\n- 三个月以前的内容不应导入。\n",
            encoding="utf-8",
        )
        (self.memory_root / "raw_memories.md").write_text(
            "RAW_TRANSCRIPT_MUST_NOT_BE_IMPORTED",
            encoding="utf-8",
        )
        summary_timestamp = NOW_MS / 1_000
        os.utime(
            self.memory_root / "memory_summary.md",
            (summary_timestamp, summary_timestamp),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _importer(
        self,
        *,
        include_rollout_summaries: bool = True,
        clock_ms: int = NOW_MS,
        lookback_days: int = 90,
    ) -> CodexMemorySourceImporter:
        return CodexMemorySourceImporter(
            self.db_path,
            project="wisdom-weasel-rag-ime",
            root=self.memory_root,
            lookback_days=lookback_days,
            include_rollout_summaries=include_rollout_summaries,
            clock_ms=lambda: clock_ms,
        )

    def test_imports_top_index_and_recent_rollout_without_raw_transcript(self) -> None:
        first = self._importer().run()
        second = self._importer(clock_ms=NOW_MS + 1_000).run()

        self.assertTrue(first["ok"], first)
        self.assertEqual(first["discoveredCount"], 2)
        self.assertEqual(first["storedCount"], 2)
        self.assertTrue(first["topIndexUsed"])
        self.assertTrue(first["registryUsed"])
        self.assertFalse(first["rawTranscriptImported"])
        self.assertEqual(second["storedCount"], 0)
        self.assertEqual(second["unchangedCount"], 2)
        self.assertEqual(second["contentReadCount"], 0)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT e.committed_text, e.tags_json, s.metadata_json, s.status
                FROM agent_memory_sources AS s
                JOIN input_events AS e ON e.id = s.input_event_id
                ORDER BY s.created_at_ms, s.source_id
                """
            ).fetchall()
        serialized = json.dumps(
            [dict(row) for row in rows],
            ensure_ascii=False,
        )
        self.assertEqual(len(rows), 2)
        self.assertIn("019f-test-recent", serialized)
        self.assertIn("codex", serialized)
        self.assertNotIn("三个月以前", serialized)
        self.assertNotIn("RAW_TRANSCRIPT_MUST_NOT_BE_IMPORTED", serialized)
        self.assertNotIn("/private/raw/recent.jsonl", serialized)
        self.assertNotIn("/Users/example/raw/session.jsonl", serialized)

    def test_incremental_run_only_opens_registry_when_sources_are_unchanged(
        self,
    ) -> None:
        first = self._importer().run()
        original_reader = codex_memory_source._read_bounded_text

        def registry_only(path: Path, *, maximum_bytes: int) -> str:
            if path.name != "MEMORY.md":
                raise AssertionError(f"unchanged content was reopened: {path.name}")
            return original_reader(path, maximum_bytes=maximum_bytes)

        with mock.patch.object(
            codex_memory_source,
            "_read_bounded_text",
            side_effect=registry_only,
        ):
            second = self._importer(clock_ms=NOW_MS + 1_000).run()

        self.assertEqual(first["contentReadCount"], 2)
        self.assertEqual(second["syncMode"], "incremental")
        self.assertEqual(second["discoveredCount"], 2)
        self.assertEqual(second["contentReadCount"], 0)
        self.assertEqual(second["storedCount"], 0)
        self.assertEqual(second["unchangedCount"], 2)

    def test_incremental_run_reads_only_new_rollout_summary(self) -> None:
        self._importer().run()
        new_name = "2026-07-19T02-00-00-new-memory.md"
        registry_path = self.memory_root / "MEMORY.md"
        registry_path.write_text(
            registry_path.read_text(encoding="utf-8")
            + "\n"
            + (
                f"- rollout_summaries/{new_name} "
                "(updated_at=2026-07-19T02:05:00+00:00, "
                "thread_id=019f-test-new)"
            ),
            encoding="utf-8",
        )
        (self.rollout_root / new_name).write_text(
            "# New memory\n- 后续同步只编译新增或发生变化的 Codex 摘要。\n",
            encoding="utf-8",
        )

        second = self._importer(clock_ms=NOW_MS + 1_000).run()

        self.assertEqual(second["discoveredCount"], 3)
        self.assertEqual(second["contentReadCount"], 1)
        self.assertEqual(second["storedCount"], 1)
        self.assertEqual(second["unchangedCount"], 2)
        self.assertEqual(
            [item["externalRef"] for item in second["items"]],
            [f"rollout_summaries/{new_name}"],
        )

    def test_shorter_window_expires_previously_imported_rollout_evidence(
        self,
    ) -> None:
        middle_name = "2026-05-20T08-00-00-middle-memory.md"
        registry_path = self.memory_root / "MEMORY.md"
        registry_path.write_text(
            registry_path.read_text(encoding="utf-8")
            + "\n"
            + (
                f"- rollout_summaries/{middle_name} "
                "(updated_at=2026-07-18T09:00:00+00:00, "
                "thread_id=019f-test-middle)"
            ),
            encoding="utf-8",
        )
        (self.rollout_root / middle_name).write_text(
            "# Middle memory\n- 这条摘要在九十天内，但不在最近三十天内。\n",
            encoding="utf-8",
        )
        first = self._importer(lookback_days=90).run()

        second = self._importer(
            lookback_days=30,
            clock_ms=NOW_MS + 1_000,
        ).run()

        self.assertEqual(first["discoveredCount"], 3)
        self.assertEqual(second["discoveredCount"], 2)
        self.assertEqual(second["expiredCount"], 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            expired = conn.execute(
                """
                SELECT s.status, s.disposition, i.status AS item_status
                FROM agent_memory_sources AS s
                JOIN memory_items AS i ON i.source_event_id = s.input_event_id
                WHERE json_extract(s.metadata_json, '$.externalRef') = ?
                """,
                (f"rollout_summaries/{middle_name}",),
            ).fetchone()
        self.assertEqual(expired["status"], "superseded")
        self.assertEqual(expired["disposition"], "expired")
        self.assertEqual(expired["item_status"], "superseded")

    def test_updated_top_index_supersedes_prior_source_revision(self) -> None:
        self._importer(include_rollout_summaries=False).run()
        (self.memory_root / "memory_summary.md").write_text(
            """
# Codex Memory
## User preferences
- 用户要求外部记忆只导入最近三个月，并保留 Codex 来源标记。
""",
            encoding="utf-8",
        )

        report = self._importer(
            include_rollout_summaries=False,
            clock_ms=NOW_MS + 2_000,
        ).run()

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["storedCount"], 1)
        self.assertEqual(report["supersededCount"], 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sources = conn.execute(
                """
                SELECT status, disposition
                FROM agent_memory_sources
                ORDER BY created_at_ms, source_id
                """
            ).fetchall()
            item_statuses = [
                str(row[0])
                for row in conn.execute(
                    "SELECT status FROM memory_items ORDER BY created_at_ms, id"
                ).fetchall()
            ]
        self.assertEqual(
            sorted((row["status"], row["disposition"]) for row in sources),
            [("active", "pending"), ("superseded", "expired")],
        )
        self.assertIn("superseded", item_statuses)

    def test_same_summary_with_corrected_occurrence_time_creates_revision(
        self,
    ) -> None:
        first = self._importer(include_rollout_summaries=False).run()
        corrected_timestamp = (NOW_MS - 2 * 24 * 60 * 60 * 1_000) / 1_000
        os.utime(
            self.memory_root / "memory_summary.md",
            (corrected_timestamp, corrected_timestamp),
        )

        second = self._importer(
            include_rollout_summaries=False,
            clock_ms=NOW_MS + 2_000,
        ).run()

        self.assertEqual(first["storedCount"], 1)
        self.assertEqual(second["storedCount"], 1)
        self.assertEqual(second["supersededCount"], 1)

    def test_agent_curated_source_omitted_by_model_is_kept_without_review(
        self,
    ) -> None:
        imported = self._importer(include_rollout_summaries=False).run()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_EmptyCodexMemoryOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
            clock_ms=lambda: NOW_MS + 5_000,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            current_ms=NOW_MS + 5_000,
        )

        self.assertEqual(imported["storedCount"], 1)
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            report["results"][0]["modelDecisions"][0]["disposition"],
            "remember",
        )
        self.assertEqual(
            report["results"][0]["modelDecisions"][0]["reasonCode"],
            "agent_curated_external_memory",
        )
        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute(
                """
                SELECT disposition, disposition_reason
                FROM agent_memory_sources
                WHERE status = 'active'
                """
            ).fetchone()
        self.assertEqual(stored[0], "remember")
        self.assertEqual(stored[1], "agent_curated_external_memory")

    def test_owner_bundle_caps_external_summaries_per_model_run(self) -> None:
        store = AgentMemorySourceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        store.initialize()
        for index in range(MAX_EXTERNAL_MODEL_INPUTS_PER_RUN + 4):
            store.checkpoint_external_summary(
                provider="codex",
                external_ref=f"rollout_summaries/2026-07-{index + 1:02d}.md",
                text=f"Codex 已整理摘要 {index + 1}：保留来源并按需召回。",
                tier="rollout-summary",
                source_occurred_at_ms=NOW_MS - index * 1_000,
                created_at_ms=NOW_MS,
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = _build_owner_source_bundle(
                conn,
                owner_kind="user",
                owner_id="default",
                project="wisdom-weasel-rag-ime",
                limit=64,
            )

        self.assertEqual(
            len(bundle["inputs"]),
            MAX_EXTERNAL_MODEL_INPUTS_PER_RUN,
        )
        self.assertTrue(
            all(item["externalProvider"] == "codex" for item in bundle["inputs"])
        )

    def test_codex_provenance_is_carried_to_atoms_and_topic_books(self) -> None:
        imported = self._importer(include_rollout_summaries=False).run()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_CodexMemoryOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
            clock_ms=lambda: NOW_MS + 5_000,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            current_ms=NOW_MS + 5_000,
        )

        self.assertEqual(imported["storedCount"], 1)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["results"][0]["runStatus"], "applied")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            atom_tags = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT tag.tag
                    FROM memory_atom_tags AS atom_tag
                    JOIN memory_tags AS tag
                      ON CAST(tag.id AS TEXT) = CAST(atom_tag.tag_id AS TEXT)
                    """
                ).fetchall()
            }
            book_tags = [
                value
                for row in conn.execute(
                    "SELECT tags_json FROM memory_books WHERE status = 'active'"
                ).fetchall()
                for value in json.loads(str(row[0]))
            ]
            book_summaries = [
                str(row[0])
                for row in conn.execute(
                    "SELECT summary FROM memory_books WHERE status = 'active'"
                ).fetchall()
            ]
            rebuild_retrieval_docs(
                conn,
                project="wisdom-weasel-rag-ime",
            )
            recalled = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="外部记忆如何分层并按需召回",
                    project="wisdom-weasel-rag-ime",
                ),
            )
        self.assertIn("Codex", atom_tags)
        self.assertIn("external-memory", atom_tags)
        self.assertIn("Codex", book_tags)
        self.assertFalse(
            any("supersecret" in summary for summary in book_summaries),
            book_summaries,
        )
        codex_hits = [
            item
            for item in recalled["memoryHits"]
            if "codex" in {
                str(tag).casefold()
                for tag in item.get("tags") or []
            }
        ]
        self.assertTrue(codex_hits, recalled)
        self.assertTrue(
            any(item["doc_type"] in {"atom", "book"} for item in codex_hits),
            codex_hits,
        )

    def test_replaced_codex_source_immediately_hides_stale_atoms_and_books(
        self,
    ) -> None:
        self._importer(include_rollout_summaries=False).run()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_CodexMemoryOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
            clock_ms=lambda: NOW_MS + 5_000,
        )
        curator.initialize()
        applied = curator.run_due(
            manual=True,
            current_ms=NOW_MS + 5_000,
        )
        self.assertTrue(applied["ok"], applied)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            before = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="外部记忆如何分层并按需召回",
                    project="wisdom-weasel-rag-ime",
                ),
            )
        self.assertTrue(
            any(
                item["doc_type"] in {"atom", "book"}
                and "codex"
                in {str(tag).casefold() for tag in item.get("tags") or []}
                for item in before["memoryHits"]
            ),
            before,
        )

        summary_path = self.memory_root / "memory_summary.md"
        summary_path.write_text(
            "# Codex Memory\n- 新版本改为仅增量同步已整理记忆。\n",
            encoding="utf-8",
        )
        revised_timestamp = (NOW_MS + 1_000) / 1_000
        os.utime(summary_path, (revised_timestamp, revised_timestamp))
        revised = self._importer(
            include_rollout_summaries=False,
            clock_ms=NOW_MS + 2_000,
        ).run()
        self.assertEqual(revised["storedCount"], 1)
        self.assertEqual(revised["supersededCount"], 1)

        # Do not rebuild memory_retrieval_docs here. Query-time governance must
        # reject the stale derived rows as soon as their source is superseded.
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            after = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="外部记忆如何分层并按需召回",
                    project="wisdom-weasel-rag-ime",
                ),
            )
        stale_codex_hits = [
            item
            for item in after["memoryHits"]
            if item["doc_type"] in {"atom", "book"}
            and "codex"
            in {str(tag).casefold() for tag in item.get("tags") or []}
        ]
        self.assertEqual(stale_codex_hits, [], after)


if __name__ == "__main__":
    unittest.main()
