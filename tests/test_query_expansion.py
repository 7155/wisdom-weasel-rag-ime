from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.models import InputEvent
from rag_ime.query_expansion import build_query_expansion
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import now_ms


class QueryExpansionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-query-expansion-")
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

    def test_query_expansion_matches_alias_typo_qianwen_to_qwen3(self) -> None:
        event_id = self._record_event("本地 Qwen3 输入法模型", tags=("输入法", "大模型"))
        with self.connect() as conn:
            apply_memory_book_plan(
                conn,
                memory_book_plan_from_compile_output(
                    qwen_compile_output(event_id),
                    project="wisdom-weasel-rag-ime",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                ),
            )
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")

            expansion = build_query_expansion(conn, query_text="千文三", project="wisdom-weasel-rag-ime")

        self.assertEqual(expansion.primary_query, "千文三")
        self.assertIn("千文三", expansion.matched_aliases)
        self.assertIn("千问三", expansion.matched_aliases)
        self.assertIn("Qwen3", expansion.matched_aliases)
        self.assertIn("大模型", expansion.activated_tags)
        self.assertIn("本地模型", expansion.activated_tags)
        self.assertIn("Qwen", expansion.activated_tags)
        self.assertIn("输入法", expansion.activated_tags)
        self.assertIn("千问三", expansion.expansion_terms)
        self.assertIn("Qwen3", expansion.expansion_terms)

    def test_query_expansion_uses_rime_top_candidate(self) -> None:
        self._record_event("候选展示", recent_context="输入法 RAG 候选展示", tags=("输入法", "RAG", "候选", "本地模型"))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")

            expansion = build_query_expansion(
                conn,
                query_text="houxuan",
                raw_input="houxuan",
                preedit="houxuan",
                rime_candidates=("候选展示", "候选"),
                project="wisdom-weasel-rag-ime",
            )

        self.assertEqual(expansion.primary_query, "houxuan")
        self.assertIn("houxuan", expansion.lexical_terms)
        self.assertIn("输入法", expansion.activated_tags)
        self.assertIn("RAG", expansion.activated_tags)
        self.assertIn("候选", expansion.activated_tags)

    def test_query_expansion_activates_project_tags(self) -> None:
        self._record_event(
            "输入法候选需要本地模型和 RAG 一起工作",
            recent_context="Rime Squirrel 候选 本地模型",
            tags=("输入法", "RAG", "Rime", "Squirrel", "候选", "本地模型"),
        )
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")

            expansion = build_query_expansion(conn, query_text="输入法", project="wisdom-weasel-rag-ime")

        for tag in ("输入法", "RAG", "Rime", "Squirrel", "候选", "本地模型"):
            self.assertIn(tag, expansion.activated_tags)

    def test_query_expansion_negative_tags_from_backspace_feedback(self) -> None:
        self._record_event("大模型候选", recent_context="Qwen 本地模型", tags=("大模型", "Qwen", "本地模型"))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            conn.execute(
                """
                INSERT INTO candidate_feedback(
                    created_at_ms, query_hash, candidate_text, source_type, memory_id, action, app, project, metadata_json
                )
                VALUES (?, 'q', '大模型候选', 'rag', 'phrase:大模型候选', 'backspace_after_accept', '', 'wisdom-weasel-rag-ime', '{}')
                """,
                (now_ms(),),
            )

            expansion = build_query_expansion(conn, query_text="大模型", project="wisdom-weasel-rag-ime")

        self.assertIn("大模型", expansion.negative_tags)
        self.assertIn("Qwen", expansion.negative_tags)
        self.assertNotIn("大模型", expansion.activated_tags)
        self.assertNotIn("Qwen", expansion.expansion_terms)

    def _record_event(self, text: str, *, recent_context: str = "", tags: tuple[str, ...] = ()) -> int:
        memory_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text=text,
                recent_context=recent_context,
                project="wisdom-weasel-rag-ime",
                tags=tags,
            )
        )
        return int(memory_id.split(":", 1)[1])


def qwen_compile_output(event_id: int) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.memory-book-compile.v1",
        "dailyBooks": [],
        "memoryAtoms": [
            {
                "atomId": "atom:qwen3-local-model",
                "kind": "project_fact",
                "canonicalText": "Qwen3 是输入法本地模型候选实验的一部分。",
                "summary": "用户会把千问三、千文三都指向 Qwen3 本地模型。",
                "tags": ["大模型", "本地模型", "LLM", "Qwen", "输入法"],
                "aliases": ["千文三", "千问三", "Qwen3"],
                "surfaceHints": ["本地模型", "Qwen3"],
                "queryExpansions": ["千问三", "Qwen3", "大模型"],
                "sourceEventIds": [event_id],
                "directCandidateAllowed": False,
                "confidence": 0.9,
                "qualityScore": 0.86,
            }
        ],
        "tagEdges": [
            {"src": "输入法", "dst": "大模型", "edgeType": "related", "weight": 0.8, "evidenceEventIds": [event_id]},
            {"src": "大模型", "dst": "本地模型", "edgeType": "related", "weight": 0.8, "evidenceEventIds": [event_id]},
        ],
        "phraseCandidates": [],
        "warnings": [],
    }


if __name__ == "__main__":
    unittest.main()
