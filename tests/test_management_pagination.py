from __future__ import annotations

import json
import sqlite3
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

    def test_memory_groups_are_paginated_human_readable_and_do_not_return_raw_events(self) -> None:
        result = self.service.management.memory_page("groups", page_request({"limit": 10}))

        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["items"]), 10)
        self.assertTrue(result["rawTextVisible"])
        self.assertNotIn("committed_text", result["items"][0])

        edited = self.service.management.memory_edit(
            {
                "kind": "group",
                "id": result["items"][0]["id"],
                "title": "输入法前台测试",
                "note": "只汇总这个文档中的输入",
                "color": "teal",
            }
        )
        refreshed = self.service.management.memory_page("groups", page_request({"limit": 10}))

        self.assertTrue(edited["ok"])
        self.assertEqual(refreshed["items"][0]["title"], "输入法前台测试")
        self.assertEqual(refreshed["items"][0]["note"], "只汇总这个文档中的输入")
        self.assertEqual(refreshed["items"][0]["color_token"], "teal")

    def test_tags_expose_profiles_and_merge_without_losing_relations(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            first = conn.execute(
                "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms) "
                "VALUES ('输入法', '输入法', 'topic', 0.9, 1, 1)"
            ).lastrowid
            second = conn.execute(
                "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms) "
                "VALUES ('IME', 'ime', 'alias', 0.8, 1, 1)"
            ).lastrowid
            conn.execute(
                "INSERT INTO memory_atoms(id, kind, text, source_event_ids_json, source_memory_ids_json, privacy_level, status, created_at_ms, updated_at_ms) "
                "VALUES ('atom:one', 'fact', '输入法项目', '[]', '[]', 'local', 'active', 1, 1)"
            )
            conn.execute(
                "INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source) VALUES ('atom:one', ?, 0.8, 'test')",
                (str(second),),
            )

        edited = self.service.management.memory_edit(
            {
                "kind": "tags",
                "id": str(second),
                "title": "IME",
                "type": "alias",
                "aliases": ["智能输入"],
                "color": "purple",
                "mergeIntoId": str(first),
            }
        )
        page = self.service.management.memory_page("tags", page_request({"limit": 20}))
        merged = next(item for item in page["items"] if item["id"] == str(first))

        self.assertTrue(edited["ok"])
        self.assertTrue(edited["changes"]["merged"])
        self.assertEqual(merged["color_token"], "purple")
        self.assertIn("IME", merged["aliases"])
        self.assertIn("智能输入", merged["aliases"])
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_tags WHERE id = ?", (second,)).fetchone()[0], 0)
            self.assertEqual(
                conn.execute(
                    "SELECT CAST(tag_id AS TEXT) FROM memory_atom_tags WHERE memory_atom_id = 'atom:one'"
                ).fetchone()[0],
                str(first),
            )

    def test_atom_merge_tombstones_source_and_updates_book_membership(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for atom_id, text, event_id in (("atom:source", "旧表述", 1), ("atom:target", "保留表述", 2)):
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                        id, kind, text, canonical_text, source_event_ids_json,
                        source_memory_ids_json, privacy_level, status, confidence,
                        quality_score, created_at_ms, updated_at_ms
                    ) VALUES (?, 'fact', ?, ?, ?, '[]', 'local', 'active', 0.8, 0.8, 1, 1)
                    """,
                    (atom_id, text, text, json.dumps([event_id])),
                )
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, memory_atom_ids_json,
                    created_at_ms, updated_at_ms
                ) VALUES ('book:one', 'topic', 'one', '输入法', ?, 1, 1)
                """,
                (json.dumps(["atom:source"]),),
            )

        result = self.service.management.memory_edit(
            {"kind": "atoms", "id": "atom:source", "mergeIntoId": "atom:target"}
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"]["mergedIntoId"], "atom:target")
        with sqlite3.connect(self.db_path) as conn:
            source_status = conn.execute("SELECT status FROM memory_atoms WHERE id = 'atom:source'").fetchone()[0]
            target_events = json.loads(
                conn.execute("SELECT source_event_ids_json FROM memory_atoms WHERE id = 'atom:target'").fetchone()[0]
            )
            book_atoms = json.loads(
                conn.execute("SELECT memory_atom_ids_json FROM memory_books WHERE book_id = 'book:one'").fetchone()[0]
            )
        self.assertEqual(source_status, "tombstoned")
        self.assertEqual(target_events, [2, 1])
        self.assertEqual(book_atoms, ["atom:target"])


if __name__ == "__main__":
    unittest.main()
