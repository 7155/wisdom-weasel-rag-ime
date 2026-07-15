from __future__ import annotations

import io
import tempfile
import threading
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path

from rag_ime.knowledge_library import (
    KnowledgeConflictError,
    KnowledgeLibraryConfig,
    KnowledgeLibraryService,
    KnowledgeNotFoundError,
    LocalKnowledgeClient,
    ParsedAsset,
    ParsedDocument,
)
from rag_ime.knowledge_library.models import DocumentParseError
from rag_ime.knowledge_library.parsers import BuiltinDocumentParser, MinerULocalParser, ZipSafetyLimits, inspect_mineru_zip


class KnowledgeLibraryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = KnowledgeLibraryService(
            KnowledgeLibraryConfig(self.root / "Knowledge", chunk_chars=400, chunk_overlap_chars=40)
        )

    def _document(self, name: str = "field-notes.md") -> Path:
        path = self.root / name
        path.write_text(
            "# Glacier field notes\n\n"
            "The grounding line retreated after a sustained ocean warming event.\n\n"
            "## Evidence\n\n"
            "Satellite velocity and elevation observations agree with the field log.\n",
            encoding="utf-8",
        )
        return path

    def test_import_search_open_and_jobs_use_isolated_store(self) -> None:
        base = self.service.create_base("Glacier papers", agent_enabled=True)
        document = self.service.import_document(base["id"], self._document())

        self.assertEqual("ready", document["status"])
        self.assertGreater(document["chunkCount"], 0)
        self.assertTrue((self.root / "Knowledge" / "knowledge.sqlite").exists())
        self.assertTrue(Path(self.service.store.get_document(document["documentId"])["stored_path"]).is_file())

        client = LocalKnowledgeClient(self.service)
        result = client.search({"query": "grounding line", "topK": 5})
        self.assertEqual(1, result["total"])
        hit = result["items"][0]
        self.assertEqual(base["id"], hit["kbId"])
        self.assertEqual(document["documentId"], hit["fileId"])
        self.assertIn("grounding line", hit["content"])

        opened = client.open({"fileId": hit["fileId"], "topK": 3})
        self.assertEqual(hit["fileId"], opened["fileId"])
        self.assertTrue(opened["items"])
        self.assertEqual("succeeded", self.service.list_jobs(base_id=base["id"])["jobs"][0]["status"])

        found = client.find(
            {
                "kbId": base["id"],
                "fileId": hit["fileId"],
                "patterns": ["grounding line", "satellite velocity"],
                "maxWindows": 4,
                "windowSize": 8,
            }
        )
        self.assertEqual(hit["fileId"], found["items"][0]["fileId"])
        self.assertIn("grounding line", found["items"][0]["content"])
        self.assertNotIn("path", str(found))

    def test_find_rejects_unsafe_regex(self) -> None:
        base = self.service.create_base("Regex papers", agent_enabled=True)
        document = self.service.import_document(base["id"], self._document())
        client = LocalKnowledgeClient(self.service)

        with self.assertRaisesRegex(Exception, "unsafe regular expression"):
            client.find(
                {
                    "kbId": base["id"],
                    "fileId": document["documentId"],
                    "patterns": ["(a+)+$"],
                    "useRegex": True,
                }
            )

    def test_agent_client_filters_disabled_bases_and_non_ready_documents(self) -> None:
        base = self.service.create_base("Private imports", agent_enabled=False)
        document = self.service.import_document(base["id"], self._document())
        client = LocalKnowledgeClient(self.service)

        self.assertEqual([], client.list_bases({})["items"])
        self.assertEqual([], client.search({"query": "satellite"})["items"])
        with self.assertRaises(KnowledgeNotFoundError):
            client.open({"fileId": document["documentId"]})

        self.service.update_base(base["id"], agent_enabled=True)
        self.assertEqual(1, len(client.list_bases({})["items"]))
        self.assertEqual(1, len(client.search({"query": "satellite"})["items"]))

    def test_fts_scores_preserve_bm25_order_instead_of_flattening_every_hit(self) -> None:
        base = self.service.create_base("Ranking papers", agent_enabled=True)
        strong = self.root / "strong.md"
        weak = self.root / "weak.md"
        strong.write_text(("glacier " * 20) + ("neutral " * 20), encoding="utf-8")
        weak.write_text("glacier " + ("neutral " * 39), encoding="utf-8")
        self.service.import_document(base["id"], strong)
        self.service.import_document(base["id"], weak)

        hits = LocalKnowledgeClient(self.service).search({"query": "glacier", "topK": 5})["items"]

        self.assertEqual(["strong.md", "weak.md"], [hit["fileName"] for hit in hits])
        self.assertEqual(1.0, hits[0]["score"])
        self.assertLess(hits[1]["score"], hits[0]["score"])

    def test_duplicate_import_is_rejected_without_overwriting_existing_record(self) -> None:
        base = self.service.create_base("Duplicates")
        source = self._document()
        first = self.service.import_document(base["id"], source)
        with self.assertRaises(KnowledgeConflictError):
            self.service.import_document(base["id"], source)
        self.assertEqual(first["documentId"], self.service.list_documents(base["id"])["documents"][0]["documentId"])

    def test_image_without_mineru_becomes_failed_document_and_can_be_retried_later(self) -> None:
        base = self.service.create_base("Scans")
        image = self.root / "scan.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
        document = self.service.import_document(base["id"], image)

        self.assertEqual("failed", document["status"])
        self.assertEqual("mineru_disabled", document["error"]["code"])
        self.assertEqual("failed", self.service.list_jobs(base_id=base["id"])["jobs"][0]["status"])

    def test_builtin_parser_extracts_modern_office_packages(self) -> None:
        fixtures = {
            ".docx": {
                "word/document.xml": b'<w:document xmlns:w="urn:w"><w:body><w:p><w:r><w:t>Document knowledge</w:t></w:r></w:p></w:body></w:document>',
            },
            ".pptx": {
                "ppt/slides/slide1.xml": b'<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><a:t>Slide evidence</a:t></p:sld>',
            },
            ".xlsx": {
                "xl/sharedStrings.xml": b'<sst xmlns="urn:x"><si><t>Mass balance</t></si></sst>',
                "xl/worksheets/sheet1.xml": b'<worksheet xmlns="urn:x"><sheetData><row><c t="s"><v>0</v></c><c><v>2026</v></c></row></sheetData></worksheet>',
            },
        }
        parser = BuiltinDocumentParser()
        expected = {".docx": "Document knowledge", ".pptx": "Slide evidence", ".xlsx": "Mass balance"}
        for suffix, entries in fixtures.items():
            path = self.root / f"office{suffix}"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, value in entries.items():
                    archive.writestr(name, value)
            with self.subTest(suffix=suffix):
                parsed = parser.parse(path)
                self.assertIn(expected[suffix], parsed.text)

    def test_builtin_office_parser_rejects_path_traversal(self) -> None:
        path = self.root / "unsafe.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../word/document.xml", "unsafe")
        with self.assertRaises(DocumentParseError):
            BuiltinDocumentParser().parse(path)

    def test_detail_exposes_bounded_artifact_chunks_pages_and_owned_assets(self) -> None:
        image_data = b"\x89PNG\r\n\x1a\npreview"

        class AssetParser:
            def parse(self, path: Path, *, mode: str = "auto") -> ParsedDocument:
                return ParsedDocument(
                    text="# Parsed\n\nA table image follows.\n\n![table](images/table.png)",
                    provider="mineru_local_http",
                    provider_version="test",
                    assets=(
                        ParsedAsset(
                            name="table.png",
                            media_type="image/png",
                            sha256=__import__("hashlib").sha256(image_data).hexdigest(),
                            data=image_data,
                        ),
                    ),
                    metadata={"archiveSha256": "a" * 64},
                )

        service = KnowledgeLibraryService(
            KnowledgeLibraryConfig(self.root / "AssetKnowledge", chunk_chars=300, chunk_overlap_chars=20),
            parser_router=AssetParser(),
        )
        base = service.create_base("Parsed materials")
        document = service.import_document(base["id"], self._document("material.md"))

        detail = service.document_detail(base["id"], document["documentId"], limit=1, line_limit=2)
        self.assertTrue(detail["artifact"]["available"])
        self.assertEqual(2, len(detail["contentWindow"]["items"]))
        self.assertEqual(1, detail["chunks"]["total"])
        self.assertEqual([], detail["tables"])
        asset = detail["assets"][0]
        self.assertEqual("image/png", asset["mimeType"])
        self.assertNotIn(str(self.root), str(detail))
        self.assertEqual(
            f"/api/knowledge-bases/{base['id']}/documents/{document['documentId']}/assets/{asset['assetId']}",
            asset["readPath"],
        )
        blob = service.read_document_asset(base["id"], document["documentId"], asset["assetId"])
        self.assertEqual(image_data, blob.data)

        other_base = service.create_base("Other")
        other_document = service.import_document(other_base["id"], self._document("other.md"))
        service.store.clear_document_asset_links(other_document["documentId"])
        with self.assertRaises(KnowledgeNotFoundError):
            service.read_document_asset(other_base["id"], other_document["documentId"], asset["assetId"])

    def test_background_jobs_return_before_a_slow_parser_finishes(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class SlowParser:
            def parse(self, path: Path, *, mode: str = "auto") -> ParsedDocument:
                started.set()
                if not release.wait(timeout=2):
                    raise RuntimeError("test parser was not released")
                return ParsedDocument(text="# Parsed\n\nBackground result", provider="slow", provider_version="test")

        service = KnowledgeLibraryService(
            KnowledgeLibraryConfig(self.root / "BackgroundKnowledge"),
            parser_router=SlowParser(),
            background_jobs=True,
        )
        self.addCleanup(service.close)
        base = service.create_base("Background imports")

        document = service.import_document(base["id"], self._document("background.md"))

        self.assertIn(document["status"], {"queued", "parsing"})
        self.assertTrue(started.wait(timeout=1))
        self.assertIn(service.list_jobs(base_id=base["id"])["items"][0]["status"], {"queued", "running"})
        release.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if service.get_document(document["documentId"])["status"] == "ready":
                break
            time.sleep(0.01)
        self.assertEqual("ready", service.get_document(document["documentId"])["status"])

    def test_chunking_config_marks_documents_stale_and_confirmed_rebuild_indexes_again(self) -> None:
        base = self.service.create_base("Configurable", agent_enabled=True)
        document = self.service.import_document(base["id"], self._document())
        updated = self.service.update_base(
            base["id"],
            expected_revision=base["revision"],
            chunking_config={
                "strategy": "fixed",
                "size": 240,
                "overlap": 20,
                "respectHeadings": False,
                "respectPageBoundaries": True,
            },
            retrieval_config={"mode": "dense", "topK": 7, "threshold": 0.1},
        )
        self.assertTrue(updated["reindexRequired"])
        self.assertEqual("stale", self.service.get_document(document["documentId"])["status"])
        preview = self.service.reindex_preview(base["id"])
        with self.assertRaisesRegex(Exception, "confirmText"):
            self.service.rebuild_base(
                base["id"],
                preview_token=preview["previewToken"],
                expected_revision=preview["configRevision"],
                confirm_text="no",
            )
        rebuilt = self.service.rebuild_base(
            base["id"],
            preview_token=preview["previewToken"],
            expected_revision=preview["configRevision"],
            confirm_text="REBUILD",
        )
        self.assertEqual(1, rebuilt["ready"])
        self.assertEqual("reindex", self.service.list_jobs(base_id=base["id"])["items"][0]["kind"])
        dense = LocalKnowledgeClient(self.service).search(
            {"kbId": base["id"], "query": "satellite velocity", "mode": "dense", "topK": 3}
        )
        self.assertTrue(dense["items"])
        self.assertTrue(self.service.status()["dense"]["available"])

    def test_chunking_and_retrieval_configuration_are_strictly_validated(self) -> None:
        with self.assertRaisesRegex(Exception, "overlap"):
            self.service.create_base(
                "Invalid overlap",
                chunking_config={"size": 300, "overlap": 300},
            )
        with self.assertRaisesRegex(Exception, "unknown retrievalConfig"):
            self.service.create_base("Invalid retrieval", retrieval_config={"reranker": True})


class MinerUArchiveSafetyTests(unittest.TestCase):
    def _archive(self, entries: dict[str, bytes]) -> bytes:
        target = io.BytesIO()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
        return target.getvalue()

    def test_reads_full_markdown_and_content_addressed_assets(self) -> None:
        payload = self._archive({"result/full.md": b"# Parsed\n\nMinerU output", "result/images/chart.png": b"png"})
        text, assets, archive_hash = inspect_mineru_zip(payload)
        self.assertIn("MinerU output", text)
        self.assertEqual("chart.png", assets[0].name)
        self.assertEqual(64, len(assets[0].sha256))
        self.assertEqual(64, len(archive_hash))

    def test_rejects_path_traversal_and_archive_bombs(self) -> None:
        with self.assertRaises(DocumentParseError) as traversal:
            inspect_mineru_zip(self._archive({"../full.md": b"unsafe"}))
        self.assertEqual("unsafe_archive", traversal.exception.code)

        bomb = self._archive({"full.md": b"A" * 10_000})
        with self.assertRaises(DocumentParseError) as ratio:
            inspect_mineru_zip(bomb, limits=ZipSafetyLimits(max_compression_ratio=2.0))
        self.assertEqual("unsafe_archive", ratio.exception.code)

    def test_rejects_symlinks_and_nested_archives(self) -> None:
        target = io.BytesIO()
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("full.md", "safe")
            symlink = zipfile.ZipInfo("images/link.png")
            symlink.create_system = 3
            symlink.external_attr = 0o120777 << 16
            archive.writestr(symlink, "destination")
        with self.assertRaises(DocumentParseError):
            inspect_mineru_zip(target.getvalue())

        with self.assertRaises(DocumentParseError):
            inspect_mineru_zip(self._archive({"full.md": b"safe", "nested.zip": b"PK"}))

    def test_mineru_344_multipart_uses_supported_backend_language_and_effort(self) -> None:
        captured: dict[str, bytes] = {}
        zip_payload = self._archive({"full.md": b"# Parsed\n\nMinerU 3.4.4"})

        class Response:
            status = 200
            headers = {"Content-Type": "application/zip"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit: int = -1) -> bytes:
                return zip_payload

        def urlopen(request, **_kwargs):
            captured["body"] = request.data
            return Response()

        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "paper.pdf"
            pdf.write_bytes(b"pdf")
            parsed = MinerULocalParser(urlopen=urlopen).parse(pdf)
        body = captured["body"]
        self.assertIn(b'hybrid-engine', body)
        self.assertNotIn(b'hybrid-auto-engine', body)
        self.assertIn(b'name="lang_list"\r\n\r\nch\r\n', body)
        self.assertNotIn(b'["ch"]', body)
        self.assertIn(b'name="effort"\r\n\r\nmedium\r\n', body)
        self.assertIn("MinerU 3.4.4", parsed.text)

    def test_mineru_http_422_is_reported_as_parser_contract_error(self) -> None:
        captured: dict[str, bytes] = {}

        def urlopen(request, **_kwargs):
            captured["body"] = request.data
            raise urllib.error.HTTPError(
                request.full_url,
                422,
                "unprocessable",
                {},
                io.BytesIO(b'{"detail":"invalid backend"}'),
            )

        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "scan.png"
            image.write_bytes(b"png")
            with self.assertRaises(DocumentParseError) as raised:
                MinerULocalParser(urlopen=urlopen).parse(image)
        self.assertEqual("mineru_http_error", raised.exception.code)
        self.assertIn("422", str(raised.exception))
        self.assertIn(b'name="effort"\r\n\r\nhigh\r\n', captured["body"])


if __name__ == "__main__":
    unittest.main()
