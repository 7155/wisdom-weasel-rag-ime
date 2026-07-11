from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.debug_server import DebugImeService, DebugServerConfig
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.management_service import page_request
from rag_ime.models import InputEvent


class ManagementPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-control-pagination-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.service = DebugImeService(DebugServerConfig(db_path=self.db_path, seed_if_empty=False))
        for index in range(125):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=1_900_000_000_000 + index,
                    source="manual",
                    committed_text=f"不能默认返回的真实历史正文 {index}",
                    privacy_disposition="allowed",
                    recent_context=f"private context {index}",
                    app="TextEdit",
                    project="wisdom-weasel-rag-ime",
                    context_group_id="document:test",
                    context_group_level="document",
                )
            )

    def tearDown(self) -> None:
        self.service.management.close()
        self.tmp.cleanup()

    def test_history_clamps_limit_and_uses_cursor(self) -> None:
        first = self.service.management.history_page(page_request({"limit": 500}))
        second = self.service.management.history_page(page_request({"limit": 20, "cursor": first["nextCursor"]}))

        self.assertEqual(first["limit"], 100)
        self.assertEqual(len(first["items"]), 100)
        self.assertEqual(len(second["items"]), 20)
        self.assertLess(second["items"][0]["id"], first["items"][-1]["id"])
        self.assertNotIn("text", first["items"][0])
        self.assertNotIn("recentContext", first["items"][0])
        self.assertTrue(first["items"][0]["textHash"].startswith("sha256:"))

    def test_memory_groups_are_paginated_and_do_not_return_raw_events(self) -> None:
        result = self.service.management.memory_page("groups", page_request({"limit": 10}))

        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["items"]), 10)
        self.assertFalse(result["rawTextVisible"])
        self.assertNotIn("committed_text", result["items"][0])


if __name__ == "__main__":
    unittest.main()
