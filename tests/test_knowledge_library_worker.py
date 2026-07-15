from __future__ import annotations

import socket
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

from rag_ime.knowledge_library import HttpKnowledgeClient, KnowledgeLibraryConfig, KnowledgeLibraryError, KnowledgeLibraryService
from rag_ime.knowledge_library.identity import knowledge_worker_fingerprint
from rag_ime.knowledge_library.worker import IMPORT_SCHEMA_VERSION, KnowledgeWorkerServer
from rag_ime.knowledge_worker_supervisor import (
    KnowledgeWorkerSupervisor,
    _knowledge_python_runtime,
    _knowledge_worker_env,
)


class KnowledgeWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        service = KnowledgeLibraryService(KnowledgeLibraryConfig(Path(self.temporary.name) / "Knowledge"))
        self.base = service.create_base("Worker documents", agent_enabled=True)
        self.server = KnowledgeWorkerServer(("127.0.0.1", 0), service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.client = HttpKnowledgeClient(f"http://127.0.0.1:{self.server.server_port}")

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_raw_import_receipt_and_agent_mapping_round_trip(self) -> None:
        data = b"# Worker import\n\nThe calving front advanced during the winter observation window."
        imported = self.client.management_import_document(
            self.base["id"],
            data,
            file_name="winter-notes.md",
            mime_type="text/markdown",
        )
        self.assertEqual(IMPORT_SCHEMA_VERSION, imported["schemaVersion"])
        self.assertTrue(imported["ok"])
        receipt = imported["receipt"]
        self.assertEqual(self.base["id"], receipt["kbId"])
        self.assertEqual("winter-notes.md", receipt["fileName"])
        self.assertEqual(len(data), receipt["byteSize"])
        self.assertEqual("ready", receipt["status"])

        result = self.client.search({"query": "calving front", "topK": 3})
        self.assertEqual(1, len(result["items"]))
        self.assertEqual(receipt["documentId"], result["items"][0]["fileId"])
        opened = self.client.open({"fileId": receipt["documentId"], "topK": 2})
        self.assertEqual(receipt["documentId"], opened["fileId"])
        self.assertIn("calving front", opened["items"][0]["content"])
        stored = Path(self.server.service.store.get_document(receipt["documentId"])["stored_path"])
        self.assertEqual(0o700, (self.server.service.config.root_dir / "incoming").stat().st_mode & 0o777)
        self.assertEqual(0o600, stored.stat().st_mode & 0o777)

    def test_health_exposes_worker_identity_without_ambiguity(self) -> None:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/v1/health",
            timeout=1.0,
        ) as response:
            payload = json.load(response)

        self.assertEqual("ok", payload["status"])
        self.assertEqual(str(self.server.service.config.root_dir.resolve()), payload["root"])
        self.assertRegex(payload["configFingerprint"], r"^[a-f0-9]{64}$")
        self.assertRegex(payload["owner"], r"^standalone:\d+$")

    def test_management_jobs_find_and_status(self) -> None:
        self.client.management_import_document(
            self.base["id"],
            b"# Inventory\n\nAnnual mass balance table.",
            file_name="mass-balance.md",
            mime_type="text/markdown",
        )
        jobs = self.client.management_jobs(self.base["id"])
        self.assertEqual("succeeded", jobs["items"][0]["status"])
        found = self.client.management_find({"query": "mass-balance", "kbId": self.base["id"]})
        self.assertEqual(1, found["total"])
        status = self.client.management_status()
        self.assertEqual(1, status["readyDocumentCount"])

    def test_management_chunk_preview_and_job_cancel_round_trip(self) -> None:
        imported = self.client.management_import_document(
            self.base["id"],
            b"# Preview\n\nOne paragraph.\n\nTwo paragraphs.",
            file_name="preview.md",
            mime_type="text/markdown",
        )
        file_id = imported["receipt"]["documentId"]
        preview = self.client.management_preview_chunking(
            self.base["id"],
            file_id,
            {
                "chunkingConfig": {
                    "strategy": "fixed",
                    "size": 200,
                    "overlap": 20,
                    "separator": "\n\n",
                    "respectHeadings": True,
                    "respectPageBoundaries": True,
                },
                "limit": 3,
            },
        )
        self.assertEqual(file_id, preview["fileId"])
        self.assertGreater(preview["total"], 0)

        row = self.server.service.store.get_document(file_id)
        revision = int(row["revision"]) + 1
        self.server.service.store.update_document(file_id, {"revision": revision, "status": "queued"})
        job_id = uuid.uuid4().hex
        timestamp = int(time.time() * 1_000)
        self.server.service.store.insert_job({
            "id": job_id,
            "document_id": file_id,
            "revision": revision,
            "kind": "reindex",
            "parser_mode": "builtin",
            "status": "queued",
            "stage": "queued",
            "created_at_ms": timestamp,
            "updated_at_ms": timestamp,
        })
        cancelled = self.client.management_cancel_job(job_id)
        self.assertEqual("cancelled", cancelled["job"]["status"])

    def test_document_detail_source_and_asset_binary_round_trip(self) -> None:
        imported = self.client.management_import_document(
            self.base["id"],
            b"# Material\n\nParsed artifact preview.",
            file_name="material.md",
            mime_type="text/markdown",
        )
        file_id = imported["receipt"]["documentId"]
        image = b"\x89PNG\r\n\x1a\nasset"
        asset_id = hashlib.sha256(image).hexdigest()
        path = self.server.service.config.assets_dir / f"{asset_id}.png"
        path.write_bytes(image)
        self.server.service.store.add_asset(
            sha256=asset_id,
            media_type="image/png",
            byte_size=len(image),
            stored_path=str(path),
        )
        self.server.service.store.link_asset(
            document_id=file_id,
            asset_sha256=asset_id,
            original_name="figure.png",
        )

        detail = self.client.management_document_detail(self.base["id"], file_id, line_limit=1)
        self.assertEqual(file_id, detail["document"]["documentId"])
        self.assertTrue(detail["artifact"]["available"])
        self.assertEqual(asset_id, detail["assets"][0]["assetId"])
        self.assertEqual(image, self.client.management_read_asset(self.base["id"], file_id, asset_id).data)
        source = self.client.management_read_source(self.base["id"], file_id)
        self.assertEqual(b"# Material\n\nParsed artifact preview.", source.data)
        self.assertEqual("text/markdown", source.media_type)

    def test_reindex_preview_and_rebuild_round_trip(self) -> None:
        self.client.management_import_document(
            self.base["id"],
            b"# Rebuild\n\nConfiguration-sensitive chunks.",
            file_name="rebuild.md",
            mime_type="text/markdown",
        )
        current = self.client.management_get_base(self.base["id"])
        updated = self.client.management_update_base(
            self.base["id"],
            {
                "expectedRevision": current["revision"],
                "chunkingConfig": {
                    "strategy": "paragraph",
                    "size": 300,
                    "overlap": 30,
                    "respectHeadings": True,
                    "respectPageBoundaries": True,
                },
            },
        )
        self.assertTrue(updated["reindexRequired"])
        preview = self.client.management_reindex_preview(self.base["id"])
        rebuilt = self.client.management_rebuild(
            self.base["id"],
            {
                "previewToken": preview["previewToken"],
                "expectedRevision": preview["configRevision"],
                "confirmText": "REBUILD",
                "payloadSha256": "f" * 64,
            },
        )
        self.assertEqual(1, rebuilt["ready"])


class KnowledgeWorkerSupervisorTests(unittest.TestCase):
    def test_worker_environment_is_allowlisted_and_drops_sidecar_secrets(self) -> None:
        environment = _knowledge_worker_env(
            {
                "HOME": "/Users/test",
                "PATH": "/usr/bin:/bin",
                "TMPDIR": "/tmp",
                "RAG_IME_EMBEDDING_PROVIDER": "openai-compatible",
                "RAG_IME_EMBEDDING_API_KEY": "embedding-only-secret",
                "RAG_IME_KNOWLEDGE_DENSE_BACKEND": "usearch",
                "RAG_IME_DEEPSEEK_API_KEY": "must-not-leak",
                "RAG_IME_PREDICTOR_API_KEY": "must-not-leak",
                "RAG_IME_AGENT_TOOL_TOKEN": "must-not-leak",
                "PYTHONPATH": "/unsafe/inherited/path",
                "PYTHONHOME": "/unsafe/python-home",
                "__PYVENV_LAUNCHER__": "/wrong/python",
                "AWS_SECRET_ACCESS_KEY": "must-not-leak",
            }
        )

        self.assertEqual("openai-compatible", environment["RAG_IME_EMBEDDING_PROVIDER"])
        self.assertEqual("embedding-only-secret", environment["RAG_IME_EMBEDDING_API_KEY"])
        self.assertEqual("usearch", environment["RAG_IME_KNOWLEDGE_DENSE_BACKEND"])
        self.assertEqual("1", environment["PYTHONUNBUFFERED"])
        for key in (
            "RAG_IME_DEEPSEEK_API_KEY",
            "RAG_IME_PREDICTOR_API_KEY",
            "RAG_IME_AGENT_TOOL_TOKEN",
            "PYTHONPATH",
            "PYTHONHOME",
            "__PYVENV_LAUNCHER__",
            "AWS_SECRET_ACCESS_KEY",
        ):
            self.assertNotIn(key, environment)

    def test_process_launch_receives_sanitized_worker_environment(self) -> None:
        captured: dict[str, object] = {}

        class ExitedProcess:
            def poll(self) -> int:
                return 17

        def fake_popen(command: list[str], **kwargs: object) -> ExitedProcess:
            captured["command"] = command
            captured.update(kwargs)
            return ExitedProcess()

        with tempfile.TemporaryDirectory(prefix="rag-ime-worker-env-") as tmp:
            supervisor = KnowledgeWorkerSupervisor(
                settings_provider=_disabled_mineru_settings,
                root_dir=Path(tmp) / "Knowledge",
                base_url=f"http://127.0.0.1:{_free_port()}",
                popen=fake_popen,
            )
            with mock.patch.dict(
                os.environ,
                {
                    "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
                    "PYTHONHOME": "/unsafe/python-home",
                    "__PYVENV_LAUNCHER__": "/wrong/python",
                },
                clear=False,
            ):
                with self.assertRaises(KnowledgeLibraryError) as raised:
                    supervisor.ensure_running()

        self.assertEqual("worker_start_failed", raised.exception.code)
        self.assertEqual(supervisor.python_executable, captured["command"][0])
        environment = captured["env"]
        self.assertIsInstance(environment, dict)
        self.assertEqual("local-hash", environment["RAG_IME_EMBEDDING_PROVIDER"])
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("__PYVENV_LAUNCHER__", environment)

    def test_lazily_starts_isolated_worker_on_configured_loopback_port(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-supervisor-") as tmp:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            supervisor = KnowledgeWorkerSupervisor(
                settings_provider=lambda: {
                    "knowledgeLibrary": {"parser": {"mineru": {"enabled": False, "port": 30_001}}}
                },
                root_dir=Path(tmp) / "Knowledge",
                base_url=f"http://127.0.0.1:{port}",
            )
            self.addCleanup(supervisor.close)

            created = supervisor.management_call(
                "management_create_base",
                {"name": "Supervisor documents", "agentEnabled": True},
            )
            listed = supervisor.management_call("management_list_bases")

            self.assertEqual(created["id"], listed["bases"][0]["id"])
            self.assertEqual("ready", supervisor.status({})["status"])
            self.assertTrue((Path(tmp) / "Knowledge" / "knowledge.sqlite").is_file())
            self.assertTrue(Path(supervisor.python_executable).is_absolute())
            self.assertEqual(os.getpid(), supervisor._worker_health()["parentPid"])

    def test_worker_identity_changes_with_embedding_and_dense_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-runtime-") as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
                    "RAG_IME_EMBEDDING_MODEL": "model-a",
                    "RAG_IME_KNOWLEDGE_DENSE_BACKEND": "sqlite-exact",
                },
                clear=False,
            ):
                supervisor = KnowledgeWorkerSupervisor(
                    settings_provider=_disabled_mineru_settings,
                    root_dir=Path(tmp) / "Knowledge",
                    base_url=f"http://127.0.0.1:{_free_port()}",
                )
                first = supervisor._worker_settings()[0]
                os.environ["RAG_IME_EMBEDDING_MODEL"] = "model-b"
                second = supervisor._worker_settings()[0]
                os.environ["RAG_IME_KNOWLEDGE_DENSE_BACKEND"] = "usearch"
                third = supervisor._worker_settings()[0]

            self.assertNotEqual(first, second)
            self.assertNotEqual(second, third)

    def test_worker_identity_distinguishes_virtualenv_paths(self) -> None:
        common = {
            "mineru_enabled": False,
            "mineru_port": 30_001,
            "idle_seconds": 900,
            "python_version": "3.13.12",
            "embedding_provider": "local-bge-mlx",
            "embedding_model": "model",
            "dense_backend": "usearch",
        }
        first = knowledge_worker_fingerprint(
            Path("/tmp/Knowledge"),
            python_executable="/tmp/runtime-a/.venv/bin/python",
            **common,
        )
        second = knowledge_worker_fingerprint(
            Path("/tmp/Knowledge"),
            python_executable="/tmp/runtime-b/.venv/bin/python",
            **common,
        )

        self.assertNotEqual(first, second)

    def test_relative_worker_python_is_rejected_before_process_launch(self) -> None:
        with mock.patch.dict(os.environ, {"RAG_IME_KNOWLEDGE_PYTHON": "python3"}, clear=False):
            with self.assertRaises(KnowledgeLibraryError) as raised:
                KnowledgeWorkerSupervisor(
                    settings_provider=_disabled_mineru_settings,
                    base_url=f"http://127.0.0.1:{_free_port()}",
                )
        self.assertEqual("invalid_worker_python", raised.exception.code)

    def test_worker_python_preserves_virtualenv_symlink_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-worker-python-") as tmp:
            linked_python = Path(tmp) / "python"
            linked_python.symlink_to(sys.executable)
            with mock.patch.dict(
                os.environ,
                {"RAG_IME_KNOWLEDGE_PYTHON": str(linked_python)},
                clear=False,
            ):
                executable, version = _knowledge_python_runtime()

        self.assertEqual(str(linked_python), executable)
        self.assertRegex(version, r"^\d+\.\d+\.\d+")

    def test_close_reaps_the_worker_owned_by_the_supervisor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-close-") as tmp:
            port = _free_port()
            supervisor = KnowledgeWorkerSupervisor(
                settings_provider=_disabled_mineru_settings,
                root_dir=Path(tmp) / "Knowledge",
                base_url=f"http://127.0.0.1:{port}",
            )
            supervisor.ensure_running()
            process = supervisor._process
            self.assertIsNotNone(process)

            supervisor.close()

            self.assertIsNotNone(process.poll())

    def test_matching_worker_can_be_adopted_but_mismatched_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-identity-") as tmp:
            port = _free_port()
            first = KnowledgeWorkerSupervisor(
                settings_provider=_disabled_mineru_settings,
                root_dir=Path(tmp) / "Knowledge-A",
                base_url=f"http://127.0.0.1:{port}",
            )
            first.ensure_running()
            self.addCleanup(first.close)

            matching = KnowledgeWorkerSupervisor(
                settings_provider=_disabled_mineru_settings,
                root_dir=Path(tmp) / "Knowledge-A",
                base_url=f"http://127.0.0.1:{port}",
            )
            matching.ensure_running()
            self.assertIsNone(matching._process)
            self.assertEqual(first._owner, matching._adopted_owner)

            mismatched = KnowledgeWorkerSupervisor(
                settings_provider=_disabled_mineru_settings,
                root_dir=Path(tmp) / "Knowledge-B",
                base_url=f"http://127.0.0.1:{port}",
            )
            with self.assertRaises(KnowledgeLibraryError) as raised:
                mismatched.ensure_running()
            self.assertEqual("worker_identity_mismatch", raised.exception.code)

    def test_restart_does_not_adopt_worker_bound_to_a_dead_parent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-stale-parent-") as tmp:
            port = _free_port()
            root = Path(tmp) / "Knowledge"
            stale = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "rag_ime.knowledge_library.worker",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--root",
                    str(root),
                    "--owner",
                    "sidecar:stale",
                    "--parent-pid",
                    "99999999",
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.addCleanup(_stop_process, stale)
            time.sleep(0.3)
            supervisor = KnowledgeWorkerSupervisor(
                settings_provider=_disabled_mineru_settings,
                root_dir=root,
                base_url=f"http://127.0.0.1:{port}",
            )
            self.addCleanup(supervisor.close)

            created = supervisor.management_call(
                "management_create_base",
                {"name": "Restart-safe documents", "agentEnabled": False},
            )

            self.assertEqual("Restart-safe documents", created["name"])
            self.assertIsNotNone(supervisor._process)
            self.assertEqual(os.getpid(), supervisor._worker_health()["parentPid"])
            stale.wait(timeout=2.0)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _disabled_mineru_settings() -> dict[str, object]:
    return {"knowledgeLibrary": {"parser": {"mineru": {"enabled": False, "port": 30_001}}}}


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
