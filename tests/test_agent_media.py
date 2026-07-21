from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_media import (
    AgentMediaStore,
    detect_media_mime,
    image_dimensions,
    media_mime_matches,
)
from rag_ime.agent_sessions import AgentSessionStore


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class AgentMediaStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-media-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "rag-ime.sqlite"
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        self.first = str(sessions.create(title="media one")["id"])
        self.second = str(sessions.create(title="media two")["id"])
        self.store = AgentMediaStore(self.db_path, root=self.root / "media")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_import_is_session_scoped_hash_verified_and_pi_compatible(self) -> None:
        receipt = self.store.import_bytes(
            session_id=self.first,
            data=PNG_1X1,
            mime_type="image/png",
            file_name="screenshot.png",
            created_at_ms=123,
        )

        self.assertEqual(receipt["schemaVersion"], "rag-ime.agent-media.v1")
        self.assertEqual(receipt["fileName"], "screenshot.png")
        self.assertEqual(receipt["mimeType"], "image/png")
        self.assertEqual((receipt["width"], receipt["height"]), (1, 1))
        stored_receipt, raw = self.store.read(str(receipt["mediaId"]), session_id=self.first)
        self.assertEqual(raw, PNG_1X1)
        self.assertEqual(stored_receipt["sha256"], receipt["sha256"])

        images = self.store.pi_images(self.first, [receipt["mediaId"]])
        self.assertEqual(images[0]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(images[0]["data"]), PNG_1X1)
        self.assertEqual(
            self.store.resolve_pi_image(self.first, "image/png", images[0]["data"]),
            receipt["mediaId"],
        )
        self.assertEqual(self.store.resolve_pi_image(self.second, "image/png", images[0]["data"]), "")

        with self.assertRaises(KeyError):
            self.store.read(str(receipt["mediaId"]), session_id=self.second)

    def test_mime_spoof_oversize_and_non_image_pi_attachment_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "MIME mismatch"):
            self.store.import_bytes(
                session_id=self.first,
                data=PNG_1X1,
                mime_type="image/jpeg",
            )
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.store.import_bytes(
                session_id=self.first,
                data=b"a" * (2 * 1024 * 1024 + 1),
                mime_type="text/plain",
            )

        text_receipt = self.store.import_bytes(
            session_id=self.first,
            data="safe text".encode(),
            mime_type="text/plain",
            file_name="note.txt",
        )
        with self.assertRaisesRegex(ValueError, "managed images only"):
            self.store.pi_images(self.first, [text_receipt["mediaId"]])
        with self.assertRaisesRegex(ValueError, "invalid managed mediaId"):
            self.store.read("../../private.png", session_id=self.first)

    def test_tampered_blob_is_isolated_and_entry_link_is_idempotent(self) -> None:
        receipt = self.store.import_bytes(
            session_id=self.first,
            data=PNG_1X1,
            mime_type="image/png",
        )
        media_id = str(receipt["mediaId"])
        self.store.bind_to_pi_entry(
            session_id=self.first,
            pi_entry_id="entry-1",
            turn_id="turn-1",
            media_ids=[media_id, media_id],
            created_at_ms=456,
        )
        self.store.bind_to_pi_entry(
            session_id=self.first,
            pi_entry_id="entry-1",
            turn_id="turn-1",
            media_ids=[media_id],
            created_at_ms=456,
        )
        self.assertEqual(
            [item["mediaId"] for item in self.store.attachments_for_entry(session_id=self.first, pi_entry_id="entry-1")],
            [media_id],
        )

        blob = next((self.root / "media").glob("*.blob"))
        blob.write_bytes(PNG_1X1 + b"tampered")
        with self.assertRaisesRegex(ValueError, "byte size"):
            self.store.read(media_id, session_id=self.first)

    def test_magic_and_dimensions_are_derived_from_content(self) -> None:
        self.assertEqual(detect_media_mime(PNG_1X1), "image/png")
        self.assertEqual(image_dimensions(PNG_1X1, "image/png"), (1, 1))
        self.assertEqual(detect_media_mime(b"<script>alert(1)</script>"), "text/plain")
        self.assertEqual(detect_media_mime(b"\x00\x01\x02"), "")
        self.assertTrue(media_mime_matches("text/markdown", "text/plain"))
        self.assertFalse(media_mime_matches("text/html", "image/png"))

    def test_utf8_text_subtypes_preserve_their_declared_mime(self) -> None:
        for mime_type, file_name in (
            ("text/markdown", "readme.md"),
            ("text/html", "report.html"),
            ("text/x-diff", "change.diff"),
            ("text/x-patch", "change.patch"),
        ):
            with self.subTest(mime_type=mime_type):
                receipt = self.store.import_bytes(
                    session_id=self.first,
                    data="标题\n正文".encode(),
                    mime_type=mime_type,
                    file_name=file_name,
                )
                stored, raw = self.store.read(str(receipt["mediaId"]), session_id=self.first)
                self.assertEqual(stored["mimeType"], mime_type)
                self.assertEqual(raw.decode(), "标题\n正文")


if __name__ == "__main__":
    unittest.main()
