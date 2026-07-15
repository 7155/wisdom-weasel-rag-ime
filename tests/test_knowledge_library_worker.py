from __future__ import annotations

import socket
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

from rag_ime.knowledge_library import HttpKnowledgeClient, KnowledgeLibraryConfig, KnowledgeLibraryService
from rag_ime.knowledge_library.worker import IMPORT_SCHEMA_VERSION, KnowledgeWorkerServer
from rag_ime.knowledge_worker_supervisor import KnowledgeWorkerSupervisor


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


if __name__ == "__main__":
    unittest.main()
