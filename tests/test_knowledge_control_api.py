from __future__ import annotations

import json
import hashlib
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.knowledge_control import KnowledgeControlFacade
from rag_ime.knowledge_library import HttpKnowledgeClient, KnowledgeLibraryConfig, KnowledgeLibraryService
from rag_ime.knowledge_library.worker import KnowledgeWorkerServer


class _DirectWorker:
    def __init__(self, client: HttpKnowledgeClient) -> None:
        self.client = client

    def management_call(self, operation: str, *args: object, **kwargs: object) -> dict[str, Any]:
        handler = getattr(self.client, operation)
        return handler(*args, **kwargs)


class KnowledgeControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-control-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)

        library = KnowledgeLibraryService(KnowledgeLibraryConfig(root / "Knowledge"))
        self.worker_server = KnowledgeWorkerServer(("127.0.0.1", 0), library)
        self.worker_thread = threading.Thread(target=self.worker_server.serve_forever, daemon=True)
        self.worker_thread.start()
        worker_client = HttpKnowledgeClient(f"http://127.0.0.1:{self.worker_server.server_port}")

        self.service = DebugImeService(
            DebugServerConfig(
                db_path=root / "control.sqlite",
                seed_if_empty=False,
                knowledge_client=worker_client,
            )
        )
        self.service.knowledge_control = KnowledgeControlFacade(
            worker=_DirectWorker(worker_client),  # type: ignore[arg-type]
            work_contract=self.service.management.work_contract,
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = root
        self.control_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.control_thread = threading.Thread(target=self.control_server.serve_forever, daemon=True)
        self.control_thread.start()
        self.base_url = f"http://127.0.0.1:{self.control_server.server_port}/api/knowledge-bases"

    def tearDown(self) -> None:
        self.control_server.shutdown()
        self.control_server.server_close()
        self.control_thread.join(timeout=2)
        self.worker_server.shutdown()
        self.worker_server.server_close()
        self.worker_thread.join(timeout=2)
        self.service.pi_provider_auth.close()
        self.service.agent.close()
        self.service.management.close()

    def test_document_library_management_and_agent_tool_round_trip(self) -> None:
        listed = self._json_request("GET", self.base_url)
        self.assertEqual([], listed["items"])

        created = self._json_request(
            "POST",
            self.base_url,
            {
                "name": "Project papers",
                "description": "Large external documents",
                "chunkingConfig": {
                    "strategy": "markdown",
                    "size": 800,
                    "overlap": 80,
                    "respectHeadings": True,
                    "respectPageBoundaries": True,
                },
                "retrievalConfig": {"mode": "hybrid", "topK": 8, "threshold": 0.0},
            },
        )["base"]
        self.assertEqual(800, created["chunkingConfig"]["size"])
        kb_id = created["id"]
        updated = self._json_request(
            "PATCH",
            f"{self.base_url}/{quote(kb_id)}",
            {
                "agentEnabled": True,
                "retrievalConfig": {"mode": "lexical", "topK": 6, "threshold": 0.1},
                "expectedRevision": created["revision"],
            },
        )["base"]
        self.assertTrue(updated["agentEnabled"])

        data = (
            "# Field report\n\nThe grounding line retreated during the winter survey.\n"
            + "\n".join(f"Observation line {index}" for index in range(1, 451))
        ).encode("utf-8")
        query = urlencode(
            {
                "fileName": "field-report.md",
                "mimeType": "text/markdown",
                "parserProvider": "builtin",
            }
        )
        imported = self._raw_request(
            f"{self.base_url}/{quote(kb_id)}/documents/import?{query}",
            data,
            "text/markdown",
        )
        receipt = imported["receipt"]
        self.assertEqual("ready", receipt["status"])

        documents = self._json_request("GET", f"{self.base_url}/{quote(kb_id)}/documents")
        self.assertEqual(receipt["documentId"], documents["items"][0]["id"])
        detail = self._json_request(
            "GET",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}?offset=0&limit=10",
        )
        self.assertTrue(detail["artifact"]["available"])
        self.assertIn("Field report", detail["contentWindow"]["items"][0]["content"])
        self.assertTrue(detail["chunks"]["items"])
        later_lines = self._json_request(
            "GET",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}"
            "?offset=0&limit=1&lineOffset=200&lineLimit=25",
        )
        self.assertEqual(201, later_lines["contentWindow"]["items"][0]["lineNumber"])
        self.assertIn("Observation line", later_lines["contentWindow"]["items"][0]["content"])
        self.assertEqual(25, len(later_lines["contentWindow"]["items"]))
        self.assertTrue(later_lines["contentWindow"]["hasMore"])
        source, source_headers = self._binary_request(
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}/source"
        )
        self.assertEqual(data, source)
        self.assertEqual(f'"{receipt["sha256"]}"', source_headers["ETag"])
        chunk_preview = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}/chunk-preview",
            {
                "chunkingConfig": {
                    "strategy": "fixed",
                    "size": 200,
                    "overlap": 20,
                    "separator": "\n\n",
                    "respectHeadings": True,
                    "respectPageBoundaries": True,
                },
                "limit": 2,
            },
        )
        self.assertEqual(receipt["documentId"], chunk_preview["fileId"])
        self.assertGreater(chunk_preview["total"], 0)

        asset_data = b"\x89PNG\r\n\x1a\nfacade-asset"
        asset_id = hashlib.sha256(asset_data).hexdigest()
        asset_path = self.worker_server.service.config.assets_dir / f"{asset_id}.png"
        asset_path.write_bytes(asset_data)
        self.worker_server.service.store.add_asset(
            sha256=asset_id,
            media_type="image/png",
            byte_size=len(asset_data),
            stored_path=str(asset_path),
        )
        self.worker_server.service.store.link_asset(
            document_id=receipt["documentId"],
            asset_sha256=asset_id,
            original_name="figure.png",
        )
        asset, asset_headers = self._binary_request(
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}/assets/{asset_id}"
        )
        self.assertEqual(asset_data, asset)
        self.assertEqual("image/png", asset_headers["Content-Type"])
        self.assertEqual(f'"{asset_id}"', asset_headers["ETag"])
        search = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/search",
            {"query": "grounding line", "topK": 5},
        )
        self.assertIn("grounding line", search["items"][0]["content"])

        session = self.service.agent.create_session({"title": "Knowledge control test"})["session"]
        tool_result = self.service.agent_tools.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": session["id"],
                "tool": "ime_knowledge",
                "toolCallId": "tool:knowledge-control-test",
                "args": {"op": "search", "kbId": kb_id, "query": "winter"},
            }
        )
        self.assertTrue(tool_result["ok"])
        self.assertEqual(receipt["documentId"], tool_result["result"]["items"][0]["fileId"])
        self.assertNotIn("path", json.dumps(tool_result))

        opened = self._json_request(
            "GET",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}/content?lines=20",
        )
        self.assertTrue(any("grounding line" in item["content"] for item in opened["chunks"]))
        found = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}/find",
            {"query": "Field report", "lineWindow": 20},
        )
        self.assertEqual(receipt["documentId"], found["items"][0]["fileId"])
        self.assertIn("Field report", found["items"][0]["content"])
        self.assertTrue(self._json_request("GET", f"{self.base_url}/{quote(kb_id)}/jobs")["items"])
        self.assertTrue(self._json_request("GET", f"{self.base_url}/health")["available"])
        parser_ids = {item["id"] for item in self._json_request("GET", f"{self.base_url}/parsers")["items"]}
        self.assertEqual({"auto", "builtin", "mineru_local_http"}, parser_ids)

        current_for_reindex = self._json_request("GET", f"{self.base_url}/{quote(kb_id)}")["base"]
        stale = self._json_request(
            "PATCH",
            f"{self.base_url}/{quote(kb_id)}",
            {
                "expectedRevision": current_for_reindex["revision"],
                "chunkingConfig": {
                    "strategy": "fixed",
                    "size": 300,
                    "overlap": 30,
                    "respectHeadings": False,
                    "respectPageBoundaries": True,
                },
            },
        )["base"]
        self.assertTrue(stale["reindexRequired"])
        reindex_preview = self._json_request("GET", f"{self.base_url}/{quote(kb_id)}/reindex-preview")
        rebuilt = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/rebuild",
            {
                "previewToken": reindex_preview["previewToken"],
                "payloadSha256": reindex_preview["payloadSha256"],
                "expectedRevision": reindex_preview["configRevision"],
                "confirmText": "REBUILD",
            },
        )
        self.assertEqual(1, rebuilt["ready"])

        retried = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}/retry",
            {"stage": "parse", "expectedRevision": documents["items"][0]["revision"]},
        )
        self.assertEqual("ready", retried["document"]["status"])
        deleted = self._json_request(
            "DELETE",
            f"{self.base_url}/{quote(kb_id)}/documents/{quote(receipt['documentId'])}",
        )
        self.assertTrue(deleted["deleted"])

        current = self._json_request("GET", f"{self.base_url}/{quote(kb_id)}")["base"]
        preview = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/delete/preview",
            {"expectedRevision": current["revision"]},
        )
        applied = self._json_request(
            "POST",
            f"{self.base_url}/{quote(kb_id)}/delete/apply",
            {
                "expectedRevision": current["revision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "delete",
            },
        )
        self.assertTrue(applied["ok"])
        self.assertEqual([], self._json_request("GET", self.base_url)["items"])

    @staticmethod
    def _json_request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _raw_request(url: str, data: bytes, mime_type: str) -> dict[str, Any]:
        request = Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": mime_type, "Accept": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _binary_request(url: str) -> tuple[bytes, dict[str, str]]:
        with urlopen(Request(url, method="GET"), timeout=10) as response:
            return response.read(), {key: value for key, value in response.headers.items()}


if __name__ == "__main__":
    unittest.main()
