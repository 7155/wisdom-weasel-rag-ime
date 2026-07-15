from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rag_ime.db.migration_runner import apply_database_migrations
from rag_ime.memory_graph import MemoryGraphStore
from rag_ime.memory_graph_projection import (
    GraphProjectionWorker,
    NullProjectionAdapter,
    ProjectionApplyResult,
)


class _RecordingAdapter:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[dict[str, object]] = []

    def apply(
        self,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        revision: int,
        payload: dict[str, object],
    ) -> ProjectionApplyResult:
        self.calls.append(
            {
                "operation": operation,
                "aggregateType": aggregate_type,
                "aggregateId": aggregate_id,
                "revision": revision,
                "payload": payload,
            }
        )
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("graph backend unavailable")
        return ProjectionApplyResult(external_id=f"graph:{aggregate_type}:{aggregate_id}")


class MemoryGraphProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-graph-projection-")
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "memory.sqlite3"
        with self._connect() as conn:
            apply_database_migrations(conn, applied_at_ms=0)

    def test_applies_bounded_graphiti_batch_and_updates_projection_state(self) -> None:
        first = self._insert(aggregate_id="entity-1", payload={"name": "考试"})
        second = self._insert(aggregate_id="entity-2", payload={"name": "压力"})
        third = self._insert(aggregate_id="entity-3", payload={"name": "睡眠"})
        ignored = self._insert(aggregate_id="fts-1", projection_kind="fts")
        adapter = _RecordingAdapter()
        worker = GraphProjectionWorker(self.db_path, adapter, batch_size=2)

        report = worker.run_once(now_ms=1_000)

        self.assertEqual(report.claimed, 2)
        self.assertEqual(report.applied, 2)
        self.assertEqual([call["aggregateId"] for call in adapter.calls], ["entity-1", "entity-2"])
        with self._connect() as conn:
            states = dict(
                conn.execute(
                    "SELECT outbox_id, state FROM memory_projection_outbox ORDER BY outbox_id"
                ).fetchall()
            )
            self.assertEqual(states[first], "applied")
            self.assertEqual(states[second], "applied")
            self.assertEqual(states[third], "pending")
            self.assertEqual(states[ignored], "pending")
            checkpoint = conn.execute(
                "SELECT last_outbox_id FROM memory_projection_checkpoints WHERE projection_kind = 'graphiti'"
            ).fetchone()
            self.assertEqual(checkpoint, (second,))
            mappings = conn.execute(
                """
                SELECT aggregate_id, external_id, revision
                FROM memory_graph_projection_map
                ORDER BY aggregate_id
                """
            ).fetchall()
            self.assertEqual(
                mappings,
                [
                    ("entity-1", "graph:entity:entity-1", 1),
                    ("entity-2", "graph:entity:entity-2", 1),
                ],
            )

    def test_adapter_failure_is_retried_then_dead_lettered_without_escaping(self) -> None:
        outbox_id = self._insert(aggregate_id="relation-1", aggregate_type="relation")
        adapter = _RecordingAdapter(failures=2)
        worker = GraphProjectionWorker(
            self.db_path,
            adapter,
            max_attempts=2,
            base_backoff_ms=50,
            max_backoff_ms=50,
        )

        first = worker.run_once(now_ms=1_000)
        blocked = worker.run_once(now_ms=1_049)
        second = worker.run_once(now_ms=1_050)

        self.assertEqual((first.failed, first.dead), (1, 0))
        self.assertEqual(blocked.claimed, 0)
        self.assertEqual((second.failed, second.dead), (0, 1))
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT state, attempts, available_at_ms, last_error
                FROM memory_projection_outbox WHERE outbox_id = ?
                """,
                (outbox_id,),
            ).fetchone()
        self.assertEqual(row[:3], ("dead", 2, 1_050))
        self.assertIn("graph backend unavailable", row[3])

    def test_null_adapter_does_not_require_graphiti_or_claim_false_success(self) -> None:
        outbox_id = self._insert(aggregate_id="entity-null")
        worker = GraphProjectionWorker(
            self.db_path,
            NullProjectionAdapter(),
            max_attempts=1,
        )

        report = worker.run_once(now_ms=2_000)

        self.assertEqual((report.applied, report.dead), (0, 1))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, last_error FROM memory_projection_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
            mapping_count = conn.execute("SELECT COUNT(*) FROM memory_graph_projection_map").fetchone()[0]
        self.assertEqual(row[0], "dead")
        self.assertIn("not configured", row[1])
        self.assertEqual(mapping_count, 0)

    def test_recovers_stuck_processing_and_supports_explicit_replay(self) -> None:
        outbox_id = self._insert(
            aggregate_id="entity-stuck",
            state="processing",
            attempts=0,
            updated_at_ms=100,
        )
        adapter = _RecordingAdapter()
        worker = GraphProjectionWorker(
            self.db_path,
            adapter,
            processing_timeout_ms=50,
        )

        recovered = worker.recover_stuck(now_ms=200)
        first = worker.run_once(now_ms=200)
        replayed = worker.replay(outbox_ids=[outbox_id], now_ms=300)
        second = worker.run_once(now_ms=300)

        self.assertEqual(recovered, 1)
        self.assertEqual(first.applied, 1)
        self.assertEqual(replayed, 1)
        self.assertEqual(second.applied, 1)
        self.assertEqual(len(adapter.calls), 2)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, attempts, processed_at_ms FROM memory_projection_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
        self.assertEqual(row, ("applied", 0, 300))

    def test_older_replay_cannot_downgrade_projection_mapping_revision(self) -> None:
        self._insert(aggregate_id="entity-revision", revision=2)
        self._insert(aggregate_id="entity-revision", revision=1)
        adapter = _RecordingAdapter()
        worker = GraphProjectionWorker(self.db_path, adapter, batch_size=2)

        report = worker.run_once(now_ms=400)

        self.assertEqual((report.applied, report.superseded), (1, 1))
        self.assertEqual([call["revision"] for call in adapter.calls], [2])
        with self._connect() as conn:
            revision = conn.execute(
                """
                SELECT revision FROM memory_graph_projection_map
                WHERE projection_kind = 'graphiti'
                  AND aggregate_type = 'entity'
                  AND aggregate_id = 'entity-revision'
                """
            ).fetchone()[0]
        self.assertEqual(revision, 2)

    def test_successful_delete_removes_projection_mapping(self) -> None:
        self._insert(aggregate_id="entity-delete", revision=1)
        worker = GraphProjectionWorker(self.db_path, _RecordingAdapter(), batch_size=1)
        worker.run_once(now_ms=450)
        delete_id = self._insert(
            aggregate_id="entity-delete",
            operation="tombstone",
            revision=2,
        )

        report = worker.run_once(now_ms=451)

        self.assertEqual(report.applied, 1)
        with self._connect() as conn:
            mapping_count = conn.execute(
                """
                SELECT COUNT(*) FROM memory_graph_projection_map
                WHERE projection_kind = 'graphiti'
                  AND aggregate_type = 'entity'
                  AND aggregate_id = 'entity-delete'
                """
            ).fetchone()[0]
            state = conn.execute(
                "SELECT state FROM memory_projection_outbox WHERE outbox_id = ?",
                (delete_id,),
            ).fetchone()[0]
        self.assertEqual(mapping_count, 0)
        self.assertEqual(state, "applied")

    def test_stale_delete_cannot_remove_newer_projection_mapping(self) -> None:
        self._insert(aggregate_id="entity-stale-delete", revision=3)
        self._insert(
            aggregate_id="entity-stale-delete",
            operation="delete",
            revision=2,
        )
        adapter = _RecordingAdapter()
        worker = GraphProjectionWorker(self.db_path, adapter, batch_size=2)

        report = worker.run_once(now_ms=475)

        self.assertEqual((report.applied, report.superseded), (1, 1))
        self.assertEqual(
            [(call["operation"], call["revision"]) for call in adapter.calls],
            [("upsert", 3)],
        )
        with self._connect() as conn:
            mapping = conn.execute(
                """
                SELECT revision FROM memory_graph_projection_map
                WHERE projection_kind = 'graphiti'
                  AND aggregate_type = 'entity'
                  AND aggregate_id = 'entity-stale-delete'
                """
            ).fetchone()
        self.assertEqual(mapping, (3,))

    def test_invalid_payload_is_isolated_as_item_failure(self) -> None:
        outbox_id = self._insert(aggregate_id="bad-payload", payload_json="[]")
        adapter = _RecordingAdapter()
        worker = GraphProjectionWorker(self.db_path, adapter)

        report = worker.run_once(now_ms=500)

        self.assertEqual((report.failed, report.applied), (1, 0))
        self.assertEqual(adapter.calls, [])
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, last_error FROM memory_projection_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertIn("JSON object", row[1])

    def test_worker_converts_dirty_source_into_delete_projection_incrementally(self) -> None:
        with self._connect() as conn:
            event_id = int(
                conn.execute(
                    """
                    INSERT INTO input_events(
                        created_at_ms, source, committed_text, recent_context, preedit,
                        schema_id, app, project, provider_name, tags_json,
                        context_group_id, context_group_level
                    ) VALUES (1000, 'manual', '考试导致压力', '', '', 'default',
                              'test', 'wisdom-weasel-rag-ime', 'local', '[]', '', 'app')
                    """
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 1000)",
                (event_id,),
            )
        store = MemoryGraphStore(self.db_path)
        store.upsert_entity(
            entity_id="entity:projection-exam",
            entity_type="concept",
            name="考试",
            project="wisdom-weasel-rag-ime",
            updated_at_ms=1000,
        )
        store.upsert_entity(
            entity_id="entity:projection-stress",
            entity_type="concept",
            name="压力",
            project="wisdom-weasel-rag-ime",
            updated_at_ms=1000,
        )
        store.upsert_relation(
            relation_id="relation:projection-dirty",
            source_entity_id="entity:projection-exam",
            target_entity_id="entity:projection-stress",
            relation_type="causes",
            fact="考试导致压力",
            idempotency_key="projection-dirty",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project="wisdom-weasel-rag-ime",
            updated_at_ms=1000,
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_state SET deleted = 1 WHERE event_id = ?",
                (event_id,),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_graph_source_dirty").fetchone()[0],
                1,
            )

        adapter = _RecordingAdapter()
        report = GraphProjectionWorker(self.db_path, adapter, batch_size=16).run_once(
            now_ms=10**15
        )

        self.assertEqual((report.applied, report.superseded), (3, 3))
        self.assertEqual({call["operation"] for call in adapter.calls}, {"delete"})
        with self._connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_graph_source_dirty").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM memory_relations WHERE relation_id = 'relation:projection-dirty'"
                ).fetchone()[0],
                "tombstoned",
            )

    def _insert(
        self,
        *,
        aggregate_id: str,
        aggregate_type: str = "entity",
        projection_kind: str = "graphiti",
        operation: str = "upsert",
        revision: int = 1,
        payload: dict[str, object] | None = None,
        payload_json: str | None = None,
        state: str = "pending",
        attempts: int = 0,
        available_at_ms: int = 0,
        updated_at_ms: int = 0,
    ) -> int:
        serialized = payload_json
        if serialized is None:
            serialized = json.dumps(payload or {"id": aggregate_id}, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_projection_outbox(
                    projection_kind, aggregate_type, aggregate_id, operation,
                    revision, payload_json, state, attempts, available_at_ms,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    projection_kind,
                    aggregate_type,
                    aggregate_id,
                    operation,
                    revision,
                    serialized,
                    state,
                    attempts,
                    available_at_ms,
                    updated_at_ms,
                ),
            )
            return int(cursor.lastrowid)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
