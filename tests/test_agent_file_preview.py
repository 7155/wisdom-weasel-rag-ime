from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_file_preview import (
    MAX_TEXT_PREVIEW_BYTES,
    AgentFilePreviewReader,
    language_for,
    preview_kind_for,
)
from rag_ime.agent_media import AgentMediaStore
from rag_ime.agent_sessions import AgentSessionStore


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class AgentFilePreviewReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-file-preview-")
        root = Path(self.tmp.name)
        db_path = root / "rag-ime.sqlite"
        sessions = AgentSessionStore(db_path)
        sessions.initialize()
        self.first = str(sessions.create(title="preview one")["id"])
        self.second = str(sessions.create(title="preview two")["id"])
        self.media = AgentMediaStore(db_path, root=root / "media")
        self.media.initialize()
        self.reader = AgentFilePreviewReader(self.media)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_classifies_supported_types_without_a_second_file_protocol(self) -> None:
        cases = (
            ("README.md", "text/plain", "markdown", ""),
            ("main.ts", "text/plain", "code", "typescript"),
            ("change.patch", "text/plain", "diff", ""),
            ("report.html", "text/plain", "html", ""),
            ("photo.webp", "image/webp", "image", ""),
            ("manual.pdf", "application/pdf", "unsupported", ""),
        )
        for file_name, mime_type, kind, language in cases:
            with self.subTest(file_name=file_name):
                self.assertEqual(preview_kind_for(file_name=file_name, mime_type=mime_type), kind)
                if kind == "code":
                    self.assertEqual(language_for(file_name), language)

    def test_reads_markdown_with_session_and_digest_authority(self) -> None:
        receipt = self.media.import_bytes(
            session_id=self.first,
            data="# 交付\n\n- 已验证".encode(),
            mime_type="text/markdown",
            file_name="handoff.md",
        )
        preview = self.reader.read(
            str(receipt["mediaId"]),
            session_id=self.first,
            expected_sha256=str(receipt["sha256"]),
        )

        self.assertEqual(preview["schemaVersion"], "rag-ime.agent-file-preview.v1")
        self.assertEqual(preview["content"], "# 交付\n\n- 已验证")
        descriptor = preview["descriptor"]
        self.assertIsInstance(descriptor, dict)
        assert isinstance(descriptor, dict)
        self.assertEqual(descriptor["previewKind"], "markdown")
        self.assertIn(str(receipt["mediaId"]), descriptor["contentUrl"])
        self.assertFalse(preview["truncated"])

        with self.assertRaises(KeyError):
            self.reader.read(str(receipt["mediaId"]), session_id=self.second)
        with self.assertRaisesRegex(ValueError, "digest"):
            self.reader.read(
                str(receipt["mediaId"]),
                session_id=self.first,
                expected_sha256="f" * 64,
            )

    def test_text_preview_is_bounded_after_full_blob_verification(self) -> None:
        raw = ("你" * (MAX_TEXT_PREVIEW_BYTES // 3 + 100)).encode()
        receipt = self.media.import_bytes(
            session_id=self.first,
            data=raw,
            mime_type="text/plain",
            file_name="large.py",
        )
        preview = self.reader.read(str(receipt["mediaId"]), session_id=self.first)
        self.assertTrue(preview["truncated"])
        self.assertLessEqual(preview["previewByteSize"], MAX_TEXT_PREVIEW_BYTES)
        self.assertLess(len(str(preview["content"]).encode()), len(raw))

    def test_image_preview_returns_only_an_authorized_content_url(self) -> None:
        receipt = self.media.import_bytes(
            session_id=self.first,
            data=PNG_1X1,
            mime_type="image/png",
            file_name="proof.png",
        )
        preview = self.reader.read(str(receipt["mediaId"]), session_id=self.first)
        descriptor = preview["descriptor"]
        assert isinstance(descriptor, dict)
        self.assertEqual(descriptor["previewKind"], "image")
        self.assertIsNone(preview["content"])
        self.assertTrue(str(descriptor["contentUrl"]).startswith("/api/agent/media/"))


if __name__ == "__main__":
    unittest.main()
