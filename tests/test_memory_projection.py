from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import (
    apply_memory_book_plan,
    memory_book_plan_from_compile_output,
)
from rag_ime.memory_ingest import normalize_text, upsert_memory_item
from rag_ime.memory_projection import (
    DEFAULT_PROCESSING_LEASE_MS,
    MemoryProjectionWorker,
    RETRIEVAL_DOCS_PROJECTION,
    enqueue_memory_projection,
    memory_projection_freshness,
    process_memory_projection_outbox,
)
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms


class MemoryProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-memory-projection-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.provider = HashingEmbeddingProvider(dimensions=16)
        self.core = LocalSqliteCoreClient(
            self.db_path,
            embedding_provider=self.provider,
        )
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_materializes_documents_then_vectors_and_reports_freshness(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self._insert_phrase(conn, memory_id="phrase:projection", text="异步投影")
            docs_outbox_id = enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_item",
                aggregate_id="phrase:projection",
                operation="upsert",
                project="project-a",
            )

        worker = MemoryProjectionWorker(
            self.core._connect,  # type: ignore[arg-type]
            embedding_provider=self.provider,
        )
        report = worker.run_once()

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                """
                SELECT outbox_id, projection_kind, state
                FROM memory_projection_outbox
                ORDER BY outbox_id
                """
            ).fetchall()
            doc_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_retrieval_docs "
                    "WHERE source_id = 'phrase:projection'"
                ).fetchone()[0]
            )
            vector_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_retrieval_doc_vectors "
                    "WHERE provider_fingerprint = ?",
                    (self.provider.fingerprint,),
                ).fetchone()[0]
            )

        self.assertIn(docs_outbox_id, report["applied"])
        self.assertEqual(
            [(row["projection_kind"], row["state"]) for row in rows],
            [("retrieval_docs", "applied"), ("retrieval_vectors", "applied")],
        )
        self.assertEqual(doc_count, 1)
        self.assertEqual(vector_count, 1)
        self.assertTrue(report["freshness"]["fresh"])
        self.assertEqual(report["freshness"]["vectorCoverage"], 1.0)
        self.assertTrue(report["freshness"]["checkpointCaughtUp"])
        self.assertEqual(worker.status()["lastError"], "")

    def test_retry_is_bounded_and_poison_event_moves_to_dead(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_item",
                aggregate_id="phrase:broken",
                operation="upsert",
            )

        first_ms = now_ms() + 10
        with self.core._connect() as conn, patch(  # type: ignore[attr-defined]
            "rag_ime.retrieval_docs.rebuild_retrieval_docs",
            side_effect=RuntimeError("projection failed"),
        ):
            first = process_memory_projection_outbox(
                conn,
                embedding_provider=self.provider,
                max_attempts=2,
                current_ms=first_ms,
            )
            second = process_memory_projection_outbox(
                conn,
                embedding_provider=self.provider,
                max_attempts=2,
                current_ms=first_ms + 1_000,
            )
            row = conn.execute(
                "SELECT state, attempts, last_error FROM memory_projection_outbox"
            ).fetchone()
            freshness = memory_projection_freshness(
                conn,
                provider_fingerprint=self.provider.fingerprint,
            )

        self.assertEqual(len(first["failed"]), 1)
        self.assertEqual(len(second["dead"]), 1)
        self.assertEqual(row["state"], "dead")
        self.assertEqual(row["attempts"], 2)
        self.assertIn("projection failed", row["last_error"])
        self.assertEqual(freshness["dead"], 1)
        self.assertFalse(freshness["fresh"])

    def test_expired_processing_lease_is_recovered_and_replayed(self) -> None:
        outbox_id: int
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self._insert_phrase(conn, memory_id="phrase:lease", text="租约恢复")
            outbox_id = enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_item",
                aggregate_id="phrase:lease",
                operation="upsert",
            )
            conn.execute(
                """
                UPDATE memory_projection_outbox
                SET state = 'processing', attempts = 1, updated_at_ms = 1000
                WHERE outbox_id = ?
                """,
                (outbox_id,),
            )

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            report = process_memory_projection_outbox(
                conn,
                embedding_provider=self.provider,
                max_attempts=3,
                processing_lease_ms=DEFAULT_PROCESSING_LEASE_MS,
                current_ms=1000 + DEFAULT_PROCESSING_LEASE_MS + 1,
            )
            row = conn.execute(
                "SELECT state, attempts FROM memory_projection_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()

        self.assertEqual(report["recovered"], [outbox_id])
        self.assertIn(outbox_id, report["applied"])
        self.assertEqual(row["state"], "applied")
        self.assertEqual(row["attempts"], 2)

    def test_checkpoint_does_not_jump_over_failed_event(self) -> None:
        from rag_ime.retrieval_docs import rebuild_retrieval_docs as real_rebuild

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            first_id = enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="project",
                aggregate_id="broken",
                operation="rebuild",
                project="broken",
            )
            second_id = enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="project",
                aggregate_id="healthy",
                operation="rebuild",
                project="healthy",
            )

        def fail_only_first(conn, *, project="", **kwargs):
            if project == "broken":
                raise RuntimeError("first event failed")
            return real_rebuild(conn, project=project, **kwargs)

        timestamp = now_ms() + 10
        with self.core._connect() as conn, patch(  # type: ignore[attr-defined]
            "rag_ime.retrieval_docs.rebuild_retrieval_docs",
            side_effect=fail_only_first,
        ):
            first_report = process_memory_projection_outbox(
                conn,
                max_events=2,
                max_attempts=3,
                current_ms=timestamp,
            )
            checkpoint = conn.execute(
                "SELECT last_outbox_id FROM memory_projection_checkpoints "
                "WHERE projection_kind = 'retrieval_docs'"
            ).fetchone()

        self.assertEqual(first_report["failed"], [first_id])
        self.assertIn(second_id, first_report["applied"])
        self.assertIsNone(checkpoint)

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            process_memory_projection_outbox(
                conn,
                max_events=1,
                max_attempts=3,
                current_ms=timestamp + 1_000,
            )
            checkpoint = conn.execute(
                "SELECT last_outbox_id FROM memory_projection_checkpoints "
                "WHERE projection_kind = 'retrieval_docs'"
            ).fetchone()
        self.assertEqual(int(checkpoint[0]), second_id)

    def test_enabling_provider_enqueues_vector_catchup_after_disabled_run(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self._insert_phrase(
                conn,
                memory_id="phrase:provider-switch",
                text="向量补偿",
            )
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_item",
                aggregate_id="phrase:provider-switch",
                operation="upsert",
            )

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            disabled = process_memory_projection_outbox(
                conn,
                embedding_provider=None,
            )
            vector_count = conn.execute(
                "SELECT COUNT(*) FROM memory_retrieval_doc_vectors"
            ).fetchone()[0]
        self.assertTrue(disabled["freshness"]["fresh"])
        self.assertEqual(vector_count, 0)

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            enabled = process_memory_projection_outbox(
                conn,
                embedding_provider=self.provider,
            )
            vector_count = conn.execute(
                "SELECT COUNT(*) FROM memory_retrieval_doc_vectors "
                "WHERE provider_fingerprint = ?",
                (self.provider.fingerprint,),
            ).fetchone()[0]

        self.assertTrue(
            any(
                item.get("projectionKind") == "retrieval_vectors"
                for item in enabled["results"]
            )
        )
        self.assertEqual(vector_count, 1)
        self.assertTrue(enabled["freshness"]["fresh"])

    def test_curated_source_and_outbox_share_one_transaction(self) -> None:
        event = InputEvent(
            event_id=None,
            created_at_ms=now_ms(),
            source="manual",
            committed_text="同事务投影",
            privacy_disposition="allowed",
            project="project-a",
            tags=("compiled-phrase",),
        )
        with patch(
            "rag_ime.local_sqlite_core.enqueue_memory_projection",
            side_effect=RuntimeError("outbox unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
                self.core.record_event(event)

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_projection_outbox").fetchone()[0],
                0,
            )

        self.core.record_event(event)
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 1)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0], 0)
            outbox = conn.execute(
                "SELECT projection_kind, state FROM memory_projection_outbox"
            ).fetchone()
        self.assertEqual((outbox["projection_kind"], outbox["state"]), ("retrieval_docs", "pending"))

    def test_memory_book_apply_and_outbox_share_one_transaction(self) -> None:
        event_id = self._record_source_event()
        plan = self._phrase_plan(event_id, text="编译器事务投影")

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            apply_memory_book_plan(conn, plan)
            phrase_count = conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE text = '编译器事务投影'"
            ).fetchone()[0]
            outbox = conn.execute(
                """
                SELECT aggregate_type, aggregate_id, operation, state
                FROM memory_projection_outbox
                WHERE aggregate_type = 'memory_book_run'
                """
            ).fetchone()

        self.assertEqual(phrase_count, 1)
        self.assertEqual(outbox["aggregate_id"], plan["runId"])
        self.assertEqual(
            (outbox["operation"], outbox["state"]),
            ("apply", "pending"),
        )

    def test_memory_book_apply_rolls_back_when_outbox_enqueue_fails(self) -> None:
        event_id = self._record_source_event()
        plan = self._phrase_plan(event_id, text="不应部分提交")

        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            with self.core._connect() as conn, patch(  # type: ignore[attr-defined]
                "rag_ime.memory_book_compiler.enqueue_memory_projection",
                side_effect=RuntimeError("outbox unavailable"),
            ):
                apply_memory_book_plan(conn, plan)

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_items WHERE text = '不应部分提交'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_cleanup_runs WHERE run_id = ?",
                    (plan["runId"],),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_projection_outbox "
                    "WHERE aggregate_id = ?",
                    (plan["runId"],),
                ).fetchone()[0],
                0,
            )

    def test_project_scoped_materializer_keeps_other_project_and_fts_rows(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            self._insert_phrase(
                conn,
                memory_id="phrase:project-a",
                text="甲项目候选",
                project="project-a",
            )
            self._insert_phrase(
                conn,
                memory_id="phrase:project-b",
                text="乙项目候选",
                project="project-b",
            )
            for project in ("project-a", "project-b"):
                enqueue_memory_projection(
                    conn,
                    projection_kind=RETRIEVAL_DOCS_PROJECTION,
                    aggregate_type="project",
                    aggregate_id=project,
                    operation="rebuild",
                    project=project,
                )

        worker = MemoryProjectionWorker(
            self.core._connect,  # type: ignore[arg-type]
            embedding_provider=self.provider,
        )
        worker.run_once()
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            docs = conn.execute(
                "SELECT source_id FROM memory_retrieval_docs ORDER BY source_id"
            ).fetchall()
            fts_rows = int(
                conn.execute("SELECT COUNT(*) FROM memory_retrieval_docs_fts").fetchone()[0]
            )

        self.assertEqual(
            [row["source_id"] for row in docs],
            ["phrase:project-a", "phrase:project-b"],
        )
        self.assertEqual(fts_rows, 2)

    def _insert_phrase(
        self,
        conn: sqlite3.Connection,
        *,
        memory_id: str,
        text: str,
        project: str = "project-a",
    ) -> None:
        timestamp = now_ms()
        upsert_memory_item(
            conn,
            memory_id=memory_id,
            kind="phrase",
            text=text,
            normalized_text=normalize_text(text),
            summary="",
            source_event_id=None,
            project=project,
            app="",
            confidence=0.9,
            quality_score=0.9,
            status="approved",
            privacy_class="normal",
            created_at_ms=timestamp,
            updated_at_ms=timestamp,
            metadata={},
            tags=("RAG",),
            embedding_provider=None,
            tag_source="manual",
        )

    def _record_source_event(self) -> int:
        memory_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text="编译器来源证据",
                privacy_disposition="allowed",
                project="project-a",
            )
        )
        return int(memory_id.split(":", 1)[1])

    def _phrase_plan(self, event_id: int, *, text: str) -> dict[str, object]:
        return memory_book_plan_from_compile_output(
            {
                "schemaVersion": "rag-ime.memory-book-compile.v1",
                "phraseCandidates": [
                    {
                        "text": text,
                        "tags": ["RAG"],
                        "sourceEventIds": [event_id],
                        "weight": 0.8,
                    }
                ],
            },
            project="project-a",
            provider="test",
            model="test-model",
        )


if __name__ == "__main__":
    unittest.main()
