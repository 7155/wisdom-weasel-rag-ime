from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_lifecycle import archive_inactive_memory_books, set_memory_book_archive_status
from rag_ime.retrieval_docs import rebuild_retrieval_docs


class MemoryBookLifecycleTests(unittest.TestCase):
    def test_inactive_topic_books_archive_without_a_hard_book_limit_and_can_restore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-book-lifecycle-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            current_ms = 2_000_000_000_000
            old_ms = current_ms - 120 * 86_400_000
            with core._connect() as conn:
                _insert_book(conn, "book:topic:old", "旧主题", old_ms=old_ms)
                _insert_book(conn, "book:topic:pinned", "固定主题", old_ms=old_ms, pinned=True)

                preview = archive_inactive_memory_books(
                    conn,
                    inactive_days=60,
                    current_ms=current_ms,
                    dry_run=True,
                )
                applied = archive_inactive_memory_books(
                    conn,
                    inactive_days=60,
                    current_ms=current_ms,
                    dry_run=False,
                )
                statuses = dict(conn.execute("SELECT book_id, status FROM memory_books").fetchall())

                restored = set_memory_book_archive_status(
                    conn,
                    book_id="book:topic:old",
                    archived=False,
                    current_ms=current_ms + 1,
                )

        self.assertEqual(preview["candidateCount"], 1)
        self.assertEqual(applied["archivedBookIds"], ["book:topic:old"])
        self.assertEqual(statuses["book:topic:old"], "archived")
        self.assertEqual(statuses["book:topic:pinned"], "active")
        self.assertEqual(restored["book"]["status"], "active")
        self.assertEqual(restored["book"]["archivedAtMs"], 0)
        self.assertGreater(restored["book"]["lastActiveAtMs"], old_ms)

    def test_explicit_old_project_search_is_read_only_for_archived_topic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-book-reactivation-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            with core._connect() as conn:
                _insert_book(conn, "book:topic:legacy-ime", "旧输入法主题", old_ms=1_700_000_000_000)
                set_memory_book_archive_status(
                    conn,
                    book_id="book:topic:legacy-ime",
                    archived=True,
                    current_ms=1_800_000_000_000,
                )
                rebuild_retrieval_docs(conn)

                payload = retrieve_hybrid_rag_candidates(
                    conn,
                    HybridRagQuery(
                        query_text="查找最初需求里的旧输入法主题",
                        top_k=5,
                        latency_budget_ms=1000,
                    ),
                )
                status = conn.execute(
                    "SELECT status, archive_reason FROM memory_books WHERE book_id = ?",
                    ("book:topic:legacy-ime",),
                ).fetchone()
                retrieval_metadata = json.loads(
                    conn.execute(
                        "SELECT metadata_json FROM memory_retrieval_docs WHERE source_id = ?",
                        ("book:topic:legacy-ime",),
                    ).fetchone()[0]
                )

        self.assertEqual(payload["reactivatedBookIds"], [])
        self.assertEqual(payload["historicalBookIds"], ["book:topic:legacy-ime"])
        self.assertEqual(status["status"], "archived")
        self.assertNotEqual(status["archive_reason"], "")
        self.assertTrue(retrieval_metadata["archived"])
        self.assertTrue(any(item["source_id"] == "book:topic:legacy-ime" for item in payload["hits"]))

    def test_manual_review_discard_is_not_projected_for_retrieval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-book-discard-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            with core._connect() as conn:
                _insert_book(conn, "book:topic:raw-tool-log", "请调用工具的原始日志", old_ms=1_700_000_000_000)
                conn.execute(
                    """UPDATE memory_books
                       SET status = 'archived', archive_reason = 'discarded_by_manual_review',
                           archived_at_ms = ?
                       WHERE book_id = 'book:topic:raw-tool-log'""",
                    (1_800_000_000_000,),
                )
                rebuild_retrieval_docs(conn)
                count = conn.execute(
                    "SELECT COUNT(*) FROM memory_retrieval_docs WHERE source_id = ?",
                    ("book:topic:raw-tool-log",),
                ).fetchone()[0]

        self.assertEqual(count, 0)


def _insert_book(conn, book_id: str, title: str, *, old_ms: int, pinned: bool = False) -> None:
    conn.execute(
        """
        INSERT INTO memory_books(
            book_id, book_type, book_key, title, summary, normalized_text,
            project, app, tags_json, surface_hints_json, query_expansions_json,
            source_event_ids_json, memory_atom_ids_json, status, confidence,
            quality_score, created_at_ms, updated_at_ms, metadata_json,
            archived_at_ms, last_active_at_ms, archive_reason
        ) VALUES (?, 'topic', ?, ?, ?, ?, '', '', '[]', '[]', '[]', '[]', '[]',
                  'active', 0.8, 0.8, ?, ?, ?, NULL, ?, '')
        """,
        (
            book_id,
            book_id,
            title,
            f"{title}的长期摘要",
            title,
            old_ms,
            old_ms,
            json.dumps({"pinned": pinned}),
            old_ms,
        ),
    )


if __name__ == "__main__":
    unittest.main()
