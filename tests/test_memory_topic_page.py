from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_graph_read import _load_book_nodes, read_memory_entity
from rag_ime.text_utils import now_ms


class MemoryTopicPageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "memory.sqlite"
        LocalSqliteCoreClient(self.db_path).initialize()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.time = now_ms()
        self.atom("atom:old", "旧方案已经失效", state="superseded", status="superseded",
                  lineage="line:decision", valid_from=100, valid_to=200)
        self.atom("atom:new", "当前采用新方案", lineage="line:decision",
                  supersedes="atom:old", valid_from=200)
        self.atom("atom:constraint", "本项目保留原有输入内核", kind="project_constraint")
        self.atom("atom:question", "是否需要增加离线模式？", kind="project_question")
        self.book(["atom:old", "atom:constraint", "atom:question"], stale=True)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temporary.cleanup()

    def atom(self, atom_id, text, *, kind="project_fact", state="current", status="active",
             lineage="", supersedes="", valid_from=1, valid_to=None, project="project-a",
             privacy="local", owner="default"):
        self.conn.execute("""
            INSERT INTO memory_atoms(id,kind,text,canonical_text,scope_project,privacy_level,
                status,claim_state,lineage_id,supersedes_id,valid_from_ms,valid_to_ms,
                owner_kind,owner_id,created_at_ms,updated_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'user', ?,?,?)
        """, (atom_id,kind,text,text,project,privacy,status,state,lineage,supersedes,
              valid_from,valid_to,owner,valid_from,valid_from))

    def book(self, ids, *, stale=False, status="active", book_id="book:topic-a"):
        self.conn.execute("""
            INSERT INTO memory_books(book_id,book_type,book_key,title,summary,project,
                memory_atom_ids_json,status,metadata_json,created_at_ms,updated_at_ms)
            VALUES(?, 'topic', ?, '主题 A', ?,'project-a',?,?,?,1,1)
            ON CONFLICT(book_id) DO UPDATE SET memory_atom_ids_json=excluded.memory_atom_ids_json,
                metadata_json=excluded.metadata_json, status=excluded.status
        """, (book_id, book_id.removeprefix("book:"), "旧摘要仍主张失效方案。" * 100,
               json.dumps(ids), status, json.dumps({"retrievalStale":stale})))

    def page(self):
        result = read_memory_entity(self.conn, "book", "book:topic-a", {}, default_project="project-a")
        validate_contract({**result, "settingsRevision":"test", "runtimeRevision":1}, "memory-entity.v1.json")
        return result

    def test_stale_book_uses_live_current_atoms_and_moves_replaced_claim_to_history(self):
        result = self.page()
        page = result["topicPage"]
        self.assertEqual(page["freshness"], "needs_refresh")
        self.assertEqual([e["id"] for e in page["sections"]["current"]], ["atom:new"])
        self.assertEqual([e["id"] for e in page["sections"]["constraints"]], ["atom:constraint"])
        self.assertEqual([e["id"] for e in page["sections"]["openQuestions"]], ["atom:question"])
        self.assertEqual([e["id"] for e in page["sections"]["history"]], ["atom:old"])
        self.assertEqual(page["sections"]["history"][0]["supersededByIds"], ["atom:new"])
        self.assertNotIn("旧摘要", json.dumps(page, ensure_ascii=False))
        self.assertNotIn("旧方案", page["summary"])
        self.assertIn("当前采用新方案", page["summary"])
        for rows in page["sections"].values():
            for entry in rows:
                self.assertIsNone(entry["reason"])
                self.assertEqual(entry["atomIds"], [entry["id"]])
                self.assertEqual(entry["references"][0]["kind"], "atom")

    def test_withdrawn_hidden_sensitive_cross_scope_and_future_atoms_never_become_current(self):
        hidden = [
            ("atom:forgotten", {"state":"retracted", "status":"tombstoned"}),
            ("atom:hidden", {"status":"hidden"}),
            ("atom:private", {"privacy":"sensitive"}),
            ("atom:other", {"project":"project-b"}),
            ("atom:owner", {"owner":"other-owner"}),
            ("atom:future", {"valid_from":self.time + 86_400_000}),
        ]
        for atom_id, kwargs in hidden:
            self.atom(atom_id, "EXCLUDED_BODY_" + atom_id, **kwargs)
        self.book(["atom:new", *(atom_id for atom_id, _ in hidden)])
        page = self.page()["topicPage"]
        self.assertNotIn("EXCLUDED_BODY", json.dumps(page))
        self.assertGreaterEqual(page["coverage"]["omittedAtomCount"], len(hidden))
        self.assertFalse(page["sections"]["constraints"])
        self.assertFalse(page["sections"]["openQuestions"])

    def test_atom_revision_changes_page_without_writing_book_or_source_tables(self):
        first = self.page()
        self.conn.execute("UPDATE memory_atoms SET canonical_text='当前采用进一步修订方案',updated_at_ms=301 WHERE id='atom:new'")
        self.conn.commit()
        before = list(self.conn.iterdump())
        second = self.page()
        self.assertNotEqual(first["entityRevision"], second["entityRevision"])
        self.assertNotEqual(first["topicPage"]["revision"], second["topicPage"]["revision"])
        self.assertIn("进一步修订", second["topicPage"]["summary"])
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_expired_atom_and_late_import_cannot_replace_the_current_claim(self):
        self.atom("atom:late-import", "较晚入库的旧方案", state="superseded", status="superseded",
                  lineage="line:decision", valid_from=50, valid_to=200)
        self.conn.execute("UPDATE memory_atoms SET updated_at_ms=? WHERE id='atom:late-import'", (self.time,))
        self.atom("atom:expired", "已经到期的临时安排", valid_from=1, valid_to=self.time - 1)
        self.book(["atom:old", "atom:expired"])
        page = self.page()["topicPage"]
        self.assertEqual([e["id"] for e in page["sections"]["current"]], ["atom:new"])
        history_ids = {e["id"] for e in page["sections"]["history"]}
        self.assertTrue({"atom:late-import", "atom:expired"}.issubset(history_ids))
        self.assertNotIn("旧方案", page["summary"])

    def test_chapter_body_is_independent_of_the_short_summary_budget(self):
        body = "有来源边界的当前内容。" * 150 + "尾部的关键条件仍应保留。"
        self.conn.execute("UPDATE memory_atoms SET canonical_text=? WHERE id='atom:new'", (body,))
        page = self.page()["topicPage"]
        self.assertLessEqual(len(page["summary"]), 900)
        self.assertTrue(page["sections"]["current"][0]["text"].endswith("尾部的关键条件仍应保留。"))

    def test_default_request_keeps_lineage_inside_the_book_project(self):
        self.atom("atom:foreign-lineage", "OTHER_PROJECT_BODY", project="project-b", lineage="line:decision")
        self.atom("atom:global", "全局有效约束", project="", kind="project_constraint")
        self.book(["atom:old", "atom:global", "atom:foreign-lineage"], stale=True)
        page = read_memory_entity(self.conn, "book", "book:topic-a", {}, default_project="")["topicPage"]
        self.assertNotIn("OTHER_PROJECT_BODY", json.dumps(page))
        self.assertEqual([entry["id"] for entry in page["sections"]["current"]], ["atom:new"])
        self.assertEqual([entry["id"] for entry in page["sections"]["constraints"]], ["atom:global"])

    def test_history_replacement_links_only_point_to_visible_atoms(self):
        self.atom("atom:future-replacement", "尚未生效的新方案", supersedes="atom:old",
                  valid_from=self.time + 86_400_000)
        page = self.page()["topicPage"]
        history = next(entry for entry in page["sections"]["history"] if entry["id"] == "atom:old")
        self.assertEqual(history["supersededByIds"], ["atom:new"])

    def test_superseded_detail_is_historical_but_stays_out_of_current_catalog(self):
        self.book(["atom:old", "atom:constraint", "atom:question"], stale=True, status="superseded")
        self.book(["atom:new"], status="superseded", book_id="book:catalog-superseded")

        result = self.page()
        page = result["topicPage"]
        self.assertEqual(result["entity"]["status"], "superseded")
        self.assertEqual(page["freshness"], "needs_refresh")
        self.assertEqual([entry["id"] for entry in page["sections"]["current"]], ["atom:new"])
        self.assertEqual([entry["id"] for entry in page["sections"]["history"]], ["atom:old"])
        self.assertNotIn("旧摘要", json.dumps(page, ensure_ascii=False))

        catalog_nodes = _load_book_nodes(
            self.conn,
            ["book:topic-a", "book:catalog-superseded"],
            project="project-a",
        )
        self.assertNotIn("book:topic-a", catalog_nodes)
        self.assertNotIn("book:catalog-superseded", catalog_nodes)


if __name__ == "__main__":
    unittest.main()
