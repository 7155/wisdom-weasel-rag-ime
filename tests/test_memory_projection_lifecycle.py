from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag_ime.debug_server import (
    DebugImeService,
    DebugServerConfig,
    _memory_projection_worker_enabled,
    run_debug_server,
)
from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_ingest import normalize_text, upsert_memory_item
from rag_ime.memory_projection import (
    RETRIEVAL_DOCS_PROJECTION,
    enqueue_memory_projection,
)


class MemoryProjectionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-projection-lifecycle-"
        )
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sidecar_service_starts_real_worker_exposes_freshness_and_stops_it(self) -> None:
        provider = HashingEmbeddingProvider(dimensions=16)
        core = LocalSqliteCoreClient(
            self.db_path,
            embedding_provider=provider,
        )
        core.initialize()
        with core._connect() as conn:  # type: ignore[attr-defined]
            _insert_phrase(conn, "phrase:lifecycle", "生产投影生命周期")
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_item",
                aggregate_id="phrase:lifecycle",
                operation="upsert",
                project="rag-ime",
            )
        service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                project="rag-ime",
                core=core,
                seed_if_empty=False,
                server_name="sidecar server",
                memory_projection_poll_interval_s=0.05,
            )
        )
        self.addCleanup(service.close)

        before = service.memory_projection_status()
        self.assertTrue(before["configured"])
        self.assertFalse(before["running"])

        service.start_background_services()
        self.assertTrue(
            _wait_until(
                lambda: _projection_applied(core, "phrase:lifecycle"),
                timeout_s=3.0,
            )
        )
        health = service.health()
        maintenance = service.agent_memory_maintenance_status(
            {"project": "rag-ime", "limit": 5}
        )

        self.assertTrue(health["ok"])
        projection = health["memoryProjection"]
        self.assertTrue(projection["configured"])
        self.assertTrue(projection["running"])
        self.assertEqual(projection["owner"], "sidecar server")
        self.assertEqual(
            projection["freshness"]["providerFingerprint"],
            provider.fingerprint,
        )
        self.assertTrue(projection["freshness"]["fresh"])
        self.assertTrue(maintenance["projection"]["running"])
        self.assertTrue(maintenance["projection"]["freshness"]["fresh"])

        worker = service.memory_projection_worker
        self.assertIsNotNone(worker)
        service.close()
        assert worker is not None
        self.assertFalse(worker.status()["running"])
        # Idempotent shutdown must not close a component twice.
        service.close()

    def test_worker_start_failure_degrades_status_without_breaking_foreground_health(self) -> None:
        core = LocalSqliteCoreClient(self.db_path)
        failing_worker = _FailingProjectionWorker()
        with patch(
            "rag_ime.debug_server.MemoryProjectionWorker",
            return_value=failing_worker,
        ):
            service = DebugImeService(
                DebugServerConfig(
                    db_path=self.db_path,
                    core=core,
                    seed_if_empty=False,
                    server_name="sidecar server",
                )
            )
        self.addCleanup(service.close)

        service.start_background_services()
        health = service.health()

        self.assertTrue(health["ok"])
        self.assertFalse(health["memoryProjection"]["ok"])
        self.assertFalse(health["memoryProjection"]["running"])
        self.assertIn(
            "thread creation failed",
            health["memoryProjection"]["lastError"],
        )
        service.close()
        self.assertEqual(failing_worker.stop_calls, 1)

    def test_agent_gateway_does_not_compete_for_projection_ownership(self) -> None:
        service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                core=LocalSqliteCoreClient(self.db_path),
                seed_if_empty=False,
                server_name="agent gateway",
            )
        )
        self.addCleanup(service.close)

        service.start_background_services()
        status = service.memory_projection_status()

        self.assertFalse(status["configured"])
        self.assertFalse(status["running"])
        self.assertEqual(status["disabledReason"], "not_projection_owner")

    def test_only_sidecar_is_default_projection_owner(self) -> None:
        sidecar = DebugServerConfig(
            db_path=self.db_path,
            server_name="sidecar server",
        )
        debug = DebugServerConfig(
            db_path=self.db_path,
            server_name="debug server",
        )
        gateway = DebugServerConfig(
            db_path=self.db_path,
            server_name="agent gateway",
        )

        with patch.dict("rag_ime.debug_server.os.environ", {}, clear=True):
            self.assertTrue(_memory_projection_worker_enabled(sidecar))
            self.assertFalse(_memory_projection_worker_enabled(debug))
            self.assertFalse(_memory_projection_worker_enabled(gateway))

        with patch.dict(
            "rag_ime.debug_server.os.environ",
            {"RAG_IME_MEMORY_PROJECTION_WORKER": "1"},
            clear=True,
        ):
            self.assertTrue(_memory_projection_worker_enabled(sidecar))
            self.assertFalse(_memory_projection_worker_enabled(debug))
            self.assertFalse(_memory_projection_worker_enabled(gateway))

        with patch.dict(
            "rag_ime.debug_server.os.environ",
            {"RAG_IME_DEBUG_MEMORY_PROJECTION_WORKER": "1"},
            clear=True,
        ):
            self.assertTrue(_memory_projection_worker_enabled(debug))
            self.assertFalse(_memory_projection_worker_enabled(gateway))

    def test_http_server_lifecycle_starts_and_closes_service(self) -> None:
        service = Mock()
        server = Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        config = DebugServerConfig(
            db_path=self.db_path,
            seed_if_empty=False,
            server_name="sidecar server",
        )
        with (
            patch("rag_ime.debug_server.DebugImeService", return_value=service),
            patch(
                "rag_ime.debug_server.QuietThreadingHTTPServer",
                return_value=server,
            ),
        ):
            run_debug_server(config)

        service.start_background_services.assert_called_once_with()
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()
        service.close.assert_called_once_with()


class _FailingProjectionWorker:
    def __init__(self) -> None:
        self.stop_calls = 0

    def start(self) -> None:
        raise RuntimeError("thread creation failed")

    def stop(self) -> None:
        self.stop_calls += 1

    def status(self) -> dict[str, object]:
        return {
            "running": False,
            "projectionKinds": [],
            "lastRunAtMs": 0,
            "lastError": "",
            "lastReport": {},
        }


def _insert_phrase(conn: sqlite3.Connection, memory_id: str, text: str) -> None:
    timestamp = int(time.time() * 1_000)
    upsert_memory_item(
        conn,
        memory_id=memory_id,
        kind="phrase",
        text=text,
        normalized_text=normalize_text(text),
        summary="",
        source_event_id=None,
        project="rag-ime",
        app="",
        confidence=0.9,
        quality_score=0.9,
        status="active",
        privacy_class="local",
        created_at_ms=timestamp,
        updated_at_ms=timestamp,
        metadata={"source": "lifecycle-test"},
        tags=("projection",),
        embedding_provider=None,
    )


def _projection_applied(core: LocalSqliteCoreClient, source_id: str) -> bool:
    with core._connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM memory_retrieval_docs WHERE source_id = ?),
                (SELECT COUNT(*) FROM memory_projection_outbox WHERE state = 'applied')
            """,
            (source_id,),
        ).fetchone()
    return int(row[0] or 0) == 1 and int(row[1] or 0) >= 1


def _wait_until(predicate: object, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.02)
    return False


if __name__ == "__main__":
    unittest.main()
