from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.debug_server import DebugImeService, DebugServerConfig


class DebugImeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-debug-test-")
        self.service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "rag-ime.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=True,
            )
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_health_and_seed_use_local_sqlite(self) -> None:
        health = self.service.health()
        self.assertTrue(health["ok"])
        self.assertGreaterEqual(health["eventCount"], 1)
        seeded = self.service.seed()
        self.assertTrue(seeded["ok"])
        self.assertGreaterEqual(seeded["seeded"], 1)

    def test_suggest_returns_native_frontend_payload(self) -> None:
        payload = self.service.suggest(
            {
                "currentInput": "SQLite 和 FTS5 第一版",
                "recentContext": "MVP 先 local-first",
                "topK": 3,
            }
        )
        self.assertEqual(payload["schemaVersion"], "rag-ime.suggestions.v1")
        self.assertEqual(payload["currentInput"], "SQLite 和 FTS5 第一版")
        self.assertGreaterEqual(len(payload["suggestions"]), 1)
        first = payload["suggestions"][0]
        self.assertIn("surfaceText", first)
        self.assertIn("memoryId", first)
        self.assertIn("evidencePreview", first)

    def test_commit_and_action_are_wired_for_debug_page(self) -> None:
        suggestion = self.service.suggest({"currentInput": "FTS5", "topK": 1})["suggestions"][0]
        action = self.service.action(
            {
                "actionType": "pin",
                "memoryId": suggestion["memoryId"],
                "suggestionId": suggestion["suggestionId"],
                "sourceEventId": suggestion["sourceEventId"],
                "query": "FTS5",
                "surfaceText": suggestion["surfaceText"],
            }
        )
        self.assertEqual(action["schemaVersion"], "rag-ime.action.v1")
        self.assertEqual(action["actionType"], "pin")
        committed = self.service.commit(
            {
                "text": "输入法调试页接受了一条候选",
                "recentContext": "debug page",
                "preedit": "debug",
                "candidateRank": 1,
                "tags": ["debug"],
            }
        )
        self.assertTrue(committed["ok"])
        self.assertTrue(str(committed["eventId"]).startswith("event:"))

    def test_rejects_empty_commit_and_bad_action(self) -> None:
        with self.assertRaises(ValueError):
            self.service.commit({"text": " "})
        with self.assertRaises(ValueError):
            self.service.action({"actionType": "unknown", "memoryId": "event:1"})


if __name__ == "__main__":
    unittest.main()
