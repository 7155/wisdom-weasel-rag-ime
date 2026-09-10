from pathlib import Path
import unittest

from scripts.refresh_paw_dock import refresh_tiles


class PawDockTests(unittest.TestCase):
    def test_refresh_preserves_other_pins_order_and_binary_metadata(self) -> None:
        other = {"tile-data": {"bundle-identifier": "example.other", "book": b"other"}}
        paw = {"GUID": 12, "tile-data": {
            "bundle-identifier": "com.rag-ime.control", "file-label": "RagImeControl",
            "book": b"old-alias", "file-data": {"_CFURLString": "old"},
        }}
        app = Path("/Users/example/Applications/Personal Agent Workbench.app")
        result = refresh_tiles([other, paw], app)
        self.assertEqual(result[0], other)
        self.assertEqual(result[1]["GUID"], 12)
        self.assertEqual(result[1]["tile-data"]["file-label"], "Personal Agent Workbench")
        self.assertIn("Personal%20Agent%20Workbench.app", result[1]["tile-data"]["file-data"]["_CFURLString"])
        self.assertNotIn("book", result[1]["tile-data"])
        self.assertEqual(paw["tile-data"]["book"], b"old-alias")
        self.assertEqual(refresh_tiles(result, app), result)

    def test_does_not_add_a_pin(self) -> None:
        self.assertEqual(refresh_tiles([], Path("/Applications/Personal Agent Workbench.app")), [])
