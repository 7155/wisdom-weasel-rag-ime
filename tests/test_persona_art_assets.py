from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = REPO_ROOT / "control-center-web" / "public"
MANIFEST_PATH = PUBLIC_ROOT / "companions" / "manifest.json"


class PersonaArtAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_generated_assets_match_manifest_and_webp_dimensions(self) -> None:
        portraits = [
            asset for asset in self.manifest["assets"].values()
            if isinstance(asset.get("source"), str)
        ]
        scenes = list(self.manifest["scenes"].values())
        self.assertEqual(len(portraits), 4)
        self.assertEqual(len(scenes), 6)

        for asset in [*portraits, *scenes]:
            path = PUBLIC_ROOT / asset["source"].lstrip("/")
            content = path.read_bytes()
            self.assertEqual(len(content), asset["bytes"], path)
            self.assertEqual(hashlib.sha256(content).hexdigest(), asset["sha256"], path)
            self.assertEqual(_webp_dimensions(content), (asset["width"], asset["height"]), path)

        contact_sheet = self.manifest["contactSheet"]
        contact_path = REPO_ROOT / contact_sheet["source"]
        contact_content = contact_path.read_bytes()
        self.assertEqual(len(contact_content), contact_sheet["bytes"], contact_path)
        self.assertEqual(hashlib.sha256(contact_content).hexdigest(), contact_sheet["sha256"], contact_path)
        self.assertEqual(
            _webp_dimensions(contact_content),
            (contact_sheet["width"], contact_sheet["height"]),
            contact_path,
        )

    def test_rejected_animal_pack_is_not_referenced(self) -> None:
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        self.assertNotIn("wisdom-weasel-", manifest_text)
        self.assertNotIn("RagImeCompanion", manifest_text)
        self.assertFalse(any((PUBLIC_ROOT / "companions" / "personas").glob("wisdom-weasel-*.webp")))

    def test_generated_pack_stays_within_delivery_budgets(self) -> None:
        budgets = self.manifest["budgets"]
        portraits = [
            asset for asset in self.manifest["assets"].values()
            if isinstance(asset.get("source"), str)
        ]
        scenes = list(self.manifest["scenes"].values())
        self.assertTrue(all(asset["bytes"] <= budgets["portraitMaxBytes"] for asset in portraits))
        self.assertTrue(all(asset["bytes"] <= budgets["sceneMaxBytes"] for asset in scenes))
        self.assertLessEqual(
            sum(asset["bytes"] for asset in [*portraits, *scenes]),
            budgets["generatedPackMaxBytes"],
        )


def _webp_dimensions(content: bytes) -> tuple[int, int]:
    if content[:4] != b"RIFF" or content[8:12] != b"WEBP" or content[12:16] != b"VP8 ":
        raise AssertionError("expected a simple lossy VP8 WebP")
    if content[23:26] != bytes((0x9D, 0x01, 0x2A)):
        raise AssertionError("invalid VP8 key-frame header")
    width, height = struct.unpack_from("<HH", content, 26)
    return width & 0x3FFF, height & 0x3FFF


if __name__ == "__main__":
    unittest.main()
