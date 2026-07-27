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
        self.assertEqual(self.manifest["schemaVersion"], "rag-ime.persona-assets.v12")
        portraits = [
            asset for asset in self.manifest["assets"].values()
            if isinstance(asset.get("source"), str)
        ]
        self.assertEqual(len(portraits), 4)
        self.assertNotIn("scenes", self.manifest)
        self.assertNotIn("contactSheet", self.manifest)

        for asset in portraits:
            path = PUBLIC_ROOT / asset["source"].lstrip("/")
            content = path.read_bytes()
            self.assertEqual(len(content), asset["bytes"], path)
            self.assertEqual(hashlib.sha256(content).hexdigest(), asset["sha256"], path)
            self.assertEqual(_webp_dimensions(content), (asset["width"], asset["height"]), path)

        referenced_sources = _referenced_sources(self.manifest)
        self.assertEqual(len(referenced_sources), 7)
        for source in referenced_sources:
            path = PUBLIC_ROOT / source.lstrip("/")
            content = path.read_bytes()
            self.assertEqual(_webp_dimensions(content), (640, 640), path)

    def test_rejected_animal_pack_is_not_referenced(self) -> None:
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        self.assertNotIn("wisdom-weasel-", manifest_text)
        self.assertNotIn("RagImeCompanion", manifest_text)
        self.assertFalse(any((PUBLIC_ROOT / "companions" / "personas").glob("wisdom-weasel-*.webp")))

    def test_functional_empty_state_scene_pack_is_removed(self) -> None:
        self.assertFalse((PUBLIC_ROOT / "companions" / "scenes").exists())
        self.assertFalse((REPO_ROOT / "eval" / "room-v2" / "art").exists())

    def test_generated_pack_stays_within_delivery_budgets(self) -> None:
        budgets = self.manifest["budgets"]
        sources = _referenced_sources(self.manifest)
        sizes = [(PUBLIC_ROOT / source.lstrip("/")).stat().st_size for source in sources]
        self.assertTrue(all(size <= budgets["portraitMaxBytes"] for size in sizes))
        self.assertLessEqual(
            sum(sizes),
            budgets["generatedPackMaxBytes"],
        )


def _referenced_sources(manifest: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    for asset in manifest["assets"].values():
        if isinstance(asset.get("source"), str):
            sources.add(asset["source"])
        states = asset.get("states")
        if isinstance(states, dict):
            sources.update(value for value in states.values() if isinstance(value, str))
    return sources


def _webp_dimensions(content: bytes) -> tuple[int, int]:
    if content[:4] != b"RIFF" or content[8:12] != b"WEBP" or content[12:16] != b"VP8 ":
        raise AssertionError("expected a simple lossy VP8 WebP")
    if content[23:26] != bytes((0x9D, 0x01, 0x2A)):
        raise AssertionError("invalid VP8 key-frame header")
    width, height = struct.unpack_from("<HH", content, 26)
    return width & 0x3FFF, height & 0x3FFF


if __name__ == "__main__":
    unittest.main()
