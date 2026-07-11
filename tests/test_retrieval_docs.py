from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager, redirect_stdout
from pathlib import Path

from rag_ime.cli import main
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.models import InputEvent
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import now_ms


class RetrievalDocsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-retrieval-docs-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def test_retrieval_docs_include_memory_item_tags_aliases(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text="连续预测",
                privacy_disposition="allowed",
                recent_context="RAG 输入法需要连续预测候选",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory", "RAG"),
            )
        )

        with self.connect() as conn:
            report = rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            row = conn.execute(
                "SELECT * FROM memory_retrieval_docs WHERE doc_type = 'phrase' AND source_id = 'phrase:连续预测'"
            ).fetchone()

        self.assertGreaterEqual(report["counts"]["phrase"], 1)
        self.assertIsNotNone(row)
        self.assertIn("连续预测", row["raw_text"])
        self.assertIn("phrase-memory", row["tags_text"])
        self.assertIn("RAG", row["tags_text"])
        self.assertIn("连续预测", row["surface_hints_text"])

    def test_retrieval_docs_include_memory_books(self) -> None:
        event_id = self._record_seed_event()
        plan = memory_book_plan_from_compile_output(
            sample_compile_output(event_id),
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        with self.connect() as conn:
            apply_memory_book_plan(conn, plan)
            report = rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            row = conn.execute("SELECT * FROM memory_retrieval_docs WHERE doc_type = 'book'").fetchone()

        self.assertEqual(report["counts"]["book"], 1)
        self.assertIsNotNone(row)
        self.assertIn("RAG 输入法多路召回方案", row["raw_text"])
        self.assertIn("VCP", row["tags_text"])
        self.assertIn("多路召回", row["surface_hints_text"])
        self.assertIn("Daily Book", row["query_expansions_text"])
        self.assertEqual(row["time_key"], "daily:2026-07-06")

    def test_retrieval_docs_include_surface_hints_and_query_expansions(self) -> None:
        event_id = self._record_seed_event()
        plan = memory_book_plan_from_compile_output(
            sample_compile_output(event_id),
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        with self.connect() as conn:
            apply_memory_book_plan(conn, plan)
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            row = conn.execute("SELECT * FROM memory_retrieval_docs WHERE doc_type = 'atom'").fetchone()

        self.assertIsNotNone(row)
        self.assertIn("RAG core 应使用", row["raw_text"])
        self.assertIn("RAG core", row["tags_text"])
        self.assertIn("VCP式RAG", row["aliases_text"])
        self.assertIn("混合召回", row["surface_hints_text"])
        self.assertIn("千问三 Qwen3", row["query_expansions_text"])

    def test_retrieval_docs_exclude_tombstoned_and_sensitive(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text="Bearer sk-secret-value",
                privacy_disposition="allowed",
                recent_context="敏感信息",
                project="wisdom-weasel-rag-ime",
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text="噪声短语",
                privacy_disposition="allowed",
                recent_context="应该被 tombstone 排除",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_tombstones(created_at_ms, target_type, target_value, reason, active, metadata_json)
                VALUES (?, 'memory_id', 'phrase:噪声短语', 'test', 1, '{}')
                """,
                (now_ms(),),
            )
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            texts = [row["raw_text"] for row in conn.execute("SELECT raw_text FROM memory_retrieval_docs").fetchall()]

        self.assertFalse(any("sk-secret-value" in text for text in texts))
        self.assertFalse(any("噪声短语" in text for text in texts))

    def test_retrieval_docs_rebuild_is_idempotent(self) -> None:
        self._record_seed_event()

        with self.connect() as conn:
            first = rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            first_rows = conn.execute("SELECT COUNT(*) FROM memory_retrieval_docs").fetchone()[0]
            second = rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            second_rows = conn.execute("SELECT COUNT(*) FROM memory_retrieval_docs").fetchone()[0]

        self.assertEqual(first["docCount"], second["docCount"])
        self.assertEqual(first_rows, second_rows)

    def test_rebuild_retrieval_docs_cli(self) -> None:
        self._record_seed_event()
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            code = main(["--db-path", str(self.db_path), "rebuild-retrieval-docs", "--project", "wisdom-weasel-rag-ime"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "rag-ime.retrieval-docs-rebuild.v1")
        self.assertGreaterEqual(payload["docCount"], 1)

    def _record_seed_event(self) -> int:
        memory_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text="RAG 输入法多路召回方案",
                privacy_disposition="allowed",
                recent_context="BM25 向量 TagMemo Time DeepSeek",
                project="wisdom-weasel-rag-ime",
                tags=("RAG", "输入法"),
            )
        )
        return int(memory_id.split(":", 1)[1])


def sample_compile_output(event_id: int) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.memory-book-compile.v1",
        "dailyBooks": [
            {
                "bookKey": "2026-07-06",
                "title": "RAG 输入法多路召回方案",
                "summary": "用户希望借鉴 VCP 的 BM25、向量、TagMemo 和 Time。",
                "tags": ["RAG", "输入法", "VCP"],
                "surfaceHints": ["多路召回", "TagMemo"],
                "queryExpansions": ["VCP RAG", "Daily Book"],
                "sourceEventIds": [event_id],
                "confidence": 0.86,
            }
        ],
        "memoryAtoms": [
            {
                "atomId": "atom:vcp-style-rag-core",
                "kind": "project_fact",
                "canonicalText": "RAG core 应使用 BM25、向量、TagMemo 和 Time 多路召回。",
                "summary": "用户希望底层 RAG core 成为通用上下文预测层。",
                "tags": ["RAG core", "BM25", "TagMemo"],
                "aliases": ["VCP式RAG"],
                "surfaceHints": ["混合召回", "语义图召回"],
                "queryExpansions": ["输入法 RAG", "千问三 Qwen3"],
                "sourceEventIds": [event_id],
                "directCandidateAllowed": False,
                "confidence": 0.88,
                "qualityScore": 0.82,
            }
        ],
        "tagEdges": [
            {"src": "输入法", "dst": "大模型", "edgeType": "related", "weight": 0.72, "evidenceEventIds": [event_id]}
        ],
        "phraseCandidates": [
            {"text": "多路召回", "tags": ["RAG", "检索"], "sourceEventIds": [event_id], "weight": 0.74}
        ],
        "warnings": [],
    }


if __name__ == "__main__":
    unittest.main()
