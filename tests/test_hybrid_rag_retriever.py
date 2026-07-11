from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.models import InputEvent
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import now_ms


class HybridRagRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-hybrid-rag-")
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

    def test_bm25_raw_exact_keyword_hit(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG", "检索"))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="多路召回", project="wisdom-weasel-rag-ime"))

        texts = [item["text"] for item in payload["candidates"]]
        self.assertTrue(any(text.startswith("多路召回") for text in texts), texts)
        self.assertGreaterEqual(payload["lanes"]["bm25_raw"]["count"], 1)

    def test_bm25_tags_hits_alias_when_raw_text_misses(self) -> None:
        event_id = self._record_event("本地模型实验", tags=("输入法",))
        with self.connect() as conn:
            apply_memory_book_plan(conn, memory_book_plan_from_compile_output(qwen_compile_output(event_id), project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash"))
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="千文三", project="wisdom-weasel-rag-ime"))

        self.assertGreaterEqual(payload["lanes"]["bm25_tags"]["count"], 1)
        self.assertIn("Qwen3", payload["query"]["matchedAliases"])

    def test_tagmemo_graph_unlocks_related_topic(self) -> None:
        event_id = self._record_event("本地模型实验", tags=("输入法",))
        with self.connect() as conn:
            apply_memory_book_plan(conn, memory_book_plan_from_compile_output(qwen_compile_output(event_id), project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash"))
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="输入法", project="wisdom-weasel-rag-ime"))

        self.assertIn("大模型", payload["query"]["activatedTags"])
        self.assertGreaterEqual(payload["lanes"]["tagmemo"]["count"], 1)

    def test_time_lane_promotes_daily_book_topic(self) -> None:
        event_id = self._record_event("RAG 输入法多路召回方案", tags=("RAG",))
        with self.connect() as conn:
            apply_memory_book_plan(conn, memory_book_plan_from_compile_output(book_compile_output(event_id), project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash"))
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="Daily Book", project="wisdom-weasel-rag-ime"))

        self.assertGreaterEqual(payload["lanes"]["time"]["count"], 1)
        self.assertIn("多路召回", [item["text"] for item in payload["candidates"]])
        self.assertNotIn("RAG 输入法多路召回方案", [item["text"] for item in payload["candidates"]])

    def test_feedback_lane_promotes_accepted_phrase(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG",))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            conn.execute(
                """
                INSERT INTO candidate_feedback(created_at_ms, query_hash, candidate_text, source_type, memory_id, action, app, project, metadata_json)
                VALUES (?, 'q', '多路召回', 'phrase', 'phrase:多路召回', 'accepted', '', 'wisdom-weasel-rag-ime', '{}')
                """,
                (now_ms(),),
            )
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="检索", project="wisdom-weasel-rag-ime"))

        self.assertGreaterEqual(payload["lanes"]["feedback"]["count"], 1)
        first = payload["candidates"][0]
        self.assertEqual(first["text"], "多路召回")
        self.assertIn("feedback_bonus", first["debug_features"])

    def test_hybrid_retrieval_does_not_surface_raw_sentence(self) -> None:
        self._record_event("这是一个很长的历史输入句子，不应该直接复读出来", recent_context="RAG 输入法", tags=("RAG",))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="历史输入句子", project="wisdom-weasel-rag-ime"))

        self.assertNotIn("这是一个很长的历史输入句子，不应该直接复读出来", [item["text"] for item in payload["candidates"]])

    def test_hybrid_retrieval_respects_tombstone_and_suppression(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG",))
        self._record_event("TagMemo", recent_context="RAG 输入法", tags=("RAG",))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            conn.execute(
                "INSERT INTO memory_tombstones(created_at_ms, target_type, target_value, reason, active, metadata_json) VALUES (?, 'memory_id', 'phrase:多路召回', 'test', 1, '{}')",
                (now_ms(),),
            )
            conn.execute(
                "INSERT INTO memory_candidate_suppressions(id, match_type, match_value, action, reason, strength, created_at_ms) VALUES ('s1', 'memory_id', 'phrase:TagMemo', 'block', 'test', 1.0, ?)",
                (now_ms(),),
            )
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="RAG", project="wisdom-weasel-rag-ime"))

        texts = [item["text"] for item in payload["candidates"]]
        self.assertFalse(any(text.startswith("多路召回") for text in texts), texts)
        self.assertFalse(any(text.startswith("TagMemo") for text in texts), texts)

    def test_hybrid_retrieval_stays_under_budget(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG",))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="多路召回", project="wisdom-weasel-rag-ime", latency_budget_ms=1000))

        self.assertLessEqual(payload["elapsedMs"], 1000)
        self.assertFalse(payload["overBudget"])

    def test_disabled_lane_is_not_executed_and_vector_lanes_report_unavailable(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG",))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="多路召回",
                    project="wisdom-weasel-rag-ime",
                    enabled_lanes=(("bm25_raw", False), ("bm25_tags", True)),
                ),
            )

        self.assertFalse(payload["lanes"]["bm25_raw"]["enabled"])
        self.assertEqual(payload["lanes"]["bm25_raw"]["count"], 0)
        self.assertEqual(
            payload["lanes"]["bm25_raw"]["skippedReason"],
            "disabled_by_effective_runtime_config",
        )
        self.assertFalse(payload["lanes"]["vector_raw"]["available"])
        self.assertEqual(
            payload["lanes"]["vector_raw"]["skippedReason"],
            "embedding_provider_not_wired",
        )
        self.assertTrue(all(item["source_lane"] != "bm25_raw" for item in payload["hits"]))
        self.assertTrue(payload["lanes"]["bm25_tags"]["lexicalFallback"])
        self.assertFalse(payload["lanes"]["bm25_tags"]["fts5Bm25"])
        self.assertEqual(
            payload["lanes"]["bm25_tags"]["implementation"],
            "lexical_substring_fallback",
        )

    def test_group_compatibility_prioritizes_exact_and_rejects_other_short_term(self) -> None:
        with self.connect() as conn:
            docs = [
                ("phrase:exact", "phrase:exact", "完成前台闭环", "wisdom-weasel-rag-ime", "com.apple.TextEdit", '{"contextGroupId":"doc:a","shortTerm":true}'),
                ("phrase:project", "phrase:project", "限制模型调用", "wisdom-weasel-rag-ime", "com.apple.TextEdit", '{"contextGroupId":"doc:b"}'),
                ("phrase:blocked-short", "phrase:blocked-short", "其他文档短期内容", "wisdom-weasel-rag-ime", "com.apple.TextEdit", '{"contextGroupId":"doc:b","shortTerm":true}'),
                ("phrase:global", "phrase:global", "保持普通拼音稳定", "", "", '{"contextGroupId":"global"}'),
            ]
            for doc_id, source_id, hint, project, app, metadata in docs:
                conn.execute(
                    """
                    INSERT INTO memory_retrieval_docs(
                        doc_id, doc_type, source_id, raw_text, tags_text, aliases_text,
                        surface_hints_text, query_expansions_text, time_key, project, app,
                        status, updated_at_ms, metadata_json
                    ) VALUES (?, 'phrase', ?, '前台上下文', '前台', '', ?, '', '', ?, ?, 'active', ?, ?)
                    """,
                    (doc_id, source_id, hint, project, app, now_ms(), metadata),
                )
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="前台",
                    project="wisdom-weasel-rag-ime",
                    app="com.apple.TextEdit",
                    context_group_id="doc:a",
                    context_group_level="document",
                ),
            )

        texts = [item["text"] for item in payload["candidates"]]
        self.assertEqual(texts[0], "完成前台闭环")
        self.assertIn("限制模型调用", texts)
        self.assertIn("保持普通拼音稳定", texts)
        self.assertNotIn("其他文档短期内容", texts)
        compatibility = {item["text"]: item["metadata"]["groupCompatibility"] for item in payload["candidates"]}
        self.assertEqual(compatibility["完成前台闭环"], 1.0)
        self.assertEqual(compatibility["限制模型调用"], 0.75)
        self.assertEqual(compatibility["保持普通拼音稳定"], 0.2)

    def _record_event(self, text: str, *, recent_context: str = "", tags: tuple[str, ...] = ()) -> int:
        memory_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text=text,
                privacy_disposition="allowed",
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
                "surfaceHints": ["Qwen3"],
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


def book_compile_output(event_id: int) -> dict[str, object]:
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
        "memoryAtoms": [],
        "tagEdges": [],
        "phraseCandidates": [],
        "warnings": [],
    }


if __name__ == "__main__":
    unittest.main()
