from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import _active_docs, retrieve_hybrid_rag_candidates
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.models import InputEvent
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.retrieval_vector_index import rebuild_retrieval_doc_vectors, warm_retrieval_doc_vector_cache
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
        self.assertEqual(payload["lanes"]["bm25_raw"]["implementation"], "sqlite_fts5_bm25")
        self.assertTrue(payload["lanes"]["bm25_raw"]["fts5Bm25"])
        raw_hits = [item for item in payload["hits"] if item["source_lane"] == "bm25_raw"]
        self.assertTrue(raw_hits)
        self.assertLess(raw_hits[0]["raw_score"], 0.0)

    def test_bm25_tags_hits_alias_when_raw_text_misses(self) -> None:
        event_id = self._record_event("本地模型实验", tags=("输入法",))
        with self.connect() as conn:
            apply_memory_book_plan(conn, memory_book_plan_from_compile_output(qwen_compile_output(event_id), project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash"))
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="千文三", project="wisdom-weasel-rag-ime"))

        self.assertGreaterEqual(payload["lanes"]["bm25_tags"]["count"], 1)
        self.assertIn("Qwen3", payload["query"]["matchedAliases"])
        self.assertEqual(payload["lanes"]["bm25_tags"]["implementation"], "sqlite_fts5_bm25")

    def test_tagmemo_graph_unlocks_related_topic(self) -> None:
        event_id = self._record_event("本地模型实验", tags=("输入法",))
        with self.connect() as conn:
            apply_memory_book_plan(conn, memory_book_plan_from_compile_output(qwen_compile_output(event_id), project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash"))
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="输入法", project="wisdom-weasel-rag-ime"))

        self.assertIn("大模型", payload["query"]["activatedTags"])
        details = {item["tag"]: item for item in payload["query"]["activatedTagDetails"]}
        self.assertEqual(details["大模型"]["hop"], 1)
        self.assertEqual(details["大模型"]["path"], ["输入法", "大模型"])
        self.assertEqual(details["本地模型"]["hop"], 2)
        self.assertEqual(details["本地模型"]["path"], ["输入法", "大模型", "本地模型"])
        self.assertGreaterEqual(payload["lanes"]["tagmemo"]["count"], 1)
        self.assertEqual(payload["lanes"]["tagmemo"]["implementation"], "sqlite_fts5_bm25")

    def test_bm25_reports_substring_fallback_only_when_fts_table_is_unavailable(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG", "检索"))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            conn.execute("DROP TABLE memory_retrieval_docs_fts")
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(query_text="多路召回", project="wisdom-weasel-rag-ime"),
            )

        lane = payload["lanes"]["bm25_raw"]
        self.assertGreaterEqual(lane["count"], 1)
        self.assertEqual(lane["implementation"], "lexical_substring_fallback")
        self.assertTrue(lane["lexicalFallback"])
        self.assertFalse(lane["fts5Bm25"])

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
            payload = retrieve_hybrid_rag_candidates(conn, HybridRagQuery(query_text="多路召回", project="wisdom-weasel-rag-ime"))

        self.assertGreaterEqual(payload["lanes"]["feedback"]["count"], 1)
        first = payload["candidates"][0]
        self.assertEqual(first["text"], "多路召回")
        self.assertIn("feedback_bonus", first["debug_features"])

    def test_feedback_lane_does_not_promote_unrelated_accepted_memory(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG", "检索"))
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            conn.execute(
                """
                INSERT INTO candidate_feedback(created_at_ms, query_hash, candidate_text, source_type, memory_id, action, app, project, metadata_json)
                VALUES (?, 'q', '多路召回', 'phrase', 'phrase:多路召回', 'accepted', '', 'wisdom-weasel-rag-ime', '{}')
                """,
                (now_ms(),),
            )
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(query_text="语音二遍识别", project="wisdom-weasel-rag-ime"),
            )

        self.assertEqual(payload["lanes"]["feedback"]["count"], 0)

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

    def test_private_agent_docs_are_filtered_before_lane_ranking(self) -> None:
        sessions = AgentSessionStore(self.db_path)
        owner = sessions.create(title="owner", role_id="agent-owner", created_at_ms=10)
        # A role is only a reusable persona template; it must not grant another
        # Agent instance access to the owner's private receipts.
        reader = sessions.create(title="reader", role_id="agent-owner", created_at_ms=11)
        sources = AgentMemorySourceStore(self.db_path, project="wisdom-weasel-rag-ime")
        for index in range(120):
            sources.checkpoint_tool_receipt(
                {
                    "state": "applied",
                    "sessionId": str(owner["id"]),
                    "approvalId": f"private-{index}",
                    "receipt": {
                        "mutationApplied": True,
                        "summary": f"目标词 高分私有工具结果 {index}",
                    },
                },
                created_at_ms=20 + index,
            )
        self._record_event("目标词公开内容")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET kind = 'stable_memory', status = 'approved', quality_score = 0.9
                WHERE source_event_id IN (
                    SELECT input_event_id FROM agent_memory_sources WHERE source_role = 'tool_receipt'
                )
                """
            )
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            private_memory_ids = [
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT mi.memory_id
                    FROM memory_items AS mi
                    JOIN agent_memory_sources AS ams ON ams.input_event_id = mi.source_event_id
                    WHERE ams.source_role = 'tool_receipt' AND mi.status = 'approved'
                    """
                ).fetchall()
            ]
            for index, memory_id in enumerate(private_memory_ids):
                conn.executemany(
                    """
                    INSERT INTO candidate_feedback(
                        created_at_ms, query_hash, candidate_text, source_type,
                        memory_id, action, app, project, metadata_json
                    ) VALUES (?, ?, '目标词', 'item', ?, 'accepted', '', 'wisdom-weasel-rag-ime', '{}')
                    """,
                    ((1000 + index * 3 + offset, f"private-{index}-{offset}", memory_id) for offset in range(3)),
                )
            conn.execute(
                """
                INSERT INTO candidate_feedback(
                    created_at_ms, query_hash, candidate_text, source_type,
                    memory_id, action, app, project, metadata_json
                ) VALUES (9999, 'public', '目标词公开内容', 'phrase', 'phrase:目标词公开内容',
                          'accepted', '', 'wisdom-weasel-rag-ime', '{}')
                """
            )
            visible = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="目标词",
                    project="wisdom-weasel-rag-ime",
                    top_k=1,
                    reader_session_id=str(reader["id"]),
                    reader_agent_id=str(reader["agentId"]),
                ),
            )
            owner_view = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="私有工具结果",
                    project="wisdom-weasel-rag-ime",
                    top_k=2,
                    reader_session_id=str(owner["id"]),
                    reader_agent_id=str(owner["agentId"]),
                ),
            )
            conn.execute(
                "UPDATE agent_memory_sources SET status = 'archived' WHERE source_role = 'tool_receipt'"
            )
            archived_owner_view = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="私有工具结果",
                    project="wisdom-weasel-rag-ime",
                    top_k=2,
                    reader_session_id=str(owner["id"]),
                    reader_agent_id=str(owner["agentId"]),
                ),
            )
            conn.execute("DELETE FROM agent_memory_sources WHERE source_role = 'tool_receipt'")
            orphaned_owner_view = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="私有工具结果",
                    project="wisdom-weasel-rag-ime",
                    top_k=2,
                    reader_session_id=str(owner["id"]),
                    reader_agent_id=str(owner["agentId"]),
                ),
            )

        self.assertTrue(any("公开内容" in item["text"] for item in visible["hits"]))
        self.assertFalse(any("私有工具结果" in item["text"] for item in visible["hits"]))
        self.assertGreaterEqual(visible["lanes"]["feedback"]["count"], 1)
        self.assertTrue(any("私有工具结果" in item["text"] for item in owner_view["hits"]))
        self.assertFalse(any("私有工具结果" in item["text"] for item in archived_owner_view["hits"]))
        self.assertFalse(any("私有工具结果" in item["text"] for item in orphaned_owner_view["hits"]))

    def test_private_doc_cannot_seed_query_expansion_or_tag_diagnostics(self) -> None:
        sessions = AgentSessionStore(self.db_path)
        owner = sessions.create(title="owner", role_id="agent-owner", created_at_ms=10)
        reader = sessions.create(title="reader", role_id="agent-reader", created_at_ms=11)
        private = AgentMemorySourceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        ).checkpoint_tool_receipt(
            {
                "state": "applied",
                "sessionId": str(owner["id"]),
                "approvalId": "private-expansion",
                "receipt": {"mutationApplied": True, "summary": "触发词 私有工具内容"},
            },
            created_at_ms=20,
        )
        self._record_event("触发词公开内容")
        private_event_id = int(private["source"]["inputEventId"])
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE memory_items
                SET kind = 'stable_memory', status = 'approved', quality_score = 0.9
                WHERE source_event_id = ?
                """,
                (private_event_id,),
            )
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            private_doc = conn.execute(
                "SELECT doc_id FROM memory_retrieval_docs WHERE json_extract(metadata_json, '$.sourceEventId') = ?",
                (private_event_id,),
            ).fetchone()
            self.assertIsNotNone(private_doc)
            conn.execute(
                """
                UPDATE memory_retrieval_docs
                SET tags_text = '私有标签', query_expansions_text = '触发词 私有扩展'
                WHERE doc_id = ?
                """,
                (str(private_doc["doc_id"]),),
            )
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text="触发词",
                    project="wisdom-weasel-rag-ime",
                    reader_session_id=str(reader["id"]),
                    reader_agent_id=str(reader["agentId"]),
                ),
            )

        self.assertNotIn("私有标签", payload["query"]["activatedTags"])
        self.assertNotIn("私有扩展", payload["query"]["expansionTerms"])
        self.assertFalse(any("私有工具内容" in item["text"] for item in payload["hits"]))

    def test_active_doc_acl_uses_constant_number_of_sql_queries(self) -> None:
        event_id = self._record_event("批量 ACL 公共来源")
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO memory_retrieval_docs(
                    doc_id, doc_type, source_id, raw_text, tags_text, aliases_text,
                    surface_hints_text, query_expansions_text, time_key, project, app,
                    status, updated_at_ms, metadata_json
                ) VALUES (?, 'synthetic', ?, '批量文档', '', '', '', '', '',
                          'wisdom-weasel-rag-ime', '', 'active', 1, ?)
                """,
                (
                    (
                        f"synthetic:{index}",
                        f"synthetic:{index}",
                        '{"sourceEventId":' + str(event_id) + '}',
                    )
                    for index in range(1000)
                ),
            )
            statements: list[str] = []
            conn.set_trace_callback(statements.append)
            docs = _active_docs(
                conn,
                query=HybridRagQuery(
                    query_text="批量",
                    project="wisdom-weasel-rag-ime",
                ),
            )
            conn.set_trace_callback(None)

        selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        self.assertGreaterEqual(len(docs), 1000)
        self.assertLessEqual(len(selects), 4, selects)

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
        self.assertFalse(payload["lanes"]["bm25_tags"]["lexicalFallback"])
        self.assertTrue(payload["lanes"]["bm25_tags"]["fts5Bm25"])
        self.assertEqual(
            payload["lanes"]["bm25_tags"]["implementation"],
            "sqlite_fts5_bm25",
        )

    def test_precomputed_vector_lanes_run_in_parallel(self) -> None:
        self._record_event("苹果电脑输入方案", tags=("输入法", "本地模型"))
        provider = SemanticFakeProvider()
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            stats = rebuild_retrieval_doc_vectors(conn, provider, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(query_text="Mac 上怎么打字", project="wisdom-weasel-rag-ime"),
                provider,
            )

        self.assertGreater(stats["documents"], 0)
        self.assertTrue(payload["parallelExecution"])
        self.assertGreater(payload["vectorIndexDocuments"], 0)
        self.assertTrue(payload["lanes"]["vector_raw"]["available"])
        self.assertGreater(payload["lanes"]["vector_raw"]["count"], 0)
        self.assertEqual(payload["lanes"]["vector_tag_boost"]["implementation"], "precomputed_cosine")

    def test_vector_tag_boost_uses_graph_activated_query_vector(self) -> None:
        provider = TagBoostSemanticFakeProvider()
        with self.connect() as conn:
            pressure_id = int(conn.execute(
                """
                INSERT INTO memory_tags(
                    tag, normalized_tag, tag_type, quality_score,
                    created_at_ms, updated_at_ms, source, status
                ) VALUES ('压力', '压力', 'concept', 0.9, 1, 1, 'dsv4', 'active')
                """
            ).lastrowid)
            exam_id = int(conn.execute(
                """
                INSERT INTO memory_tags(
                    tag, normalized_tag, tag_type, quality_score,
                    created_at_ms, updated_at_ms, source, status
                ) VALUES ('考试', '考试', 'concept', 0.8, 1, 1, 'dsv4', 'active')
                """
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO memory_tag_edges(
                    src_tag_id, dst_tag_id, edge_type, weight, direction_bias,
                    evidence_count, updated_at_ms, metadata_json
                ) VALUES (?, ?, 'related', 0.9, 0.0, 2, 1, '{}')
                """,
                (pressure_id, exam_id),
            )
            item_id = int(conn.execute(
                """
                INSERT INTO memory_items(
                    memory_id, kind, text, normalized_text, project, status,
                    privacy_class, created_at_ms, updated_at_ms, metadata_json
                ) VALUES (
                    'phrase:复试提醒', 'phrase', '复试提醒', '复试提醒',
                    'wisdom-weasel-rag-ime', 'approved', 'local', 1, 1,
                    '{"direct_candidate_allowed":true}'
                )
                """
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence)
                VALUES (?, ?, 1.0, 0, 'test')
                """,
                (item_id, exam_id),
            )
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            stats = rebuild_retrieval_doc_vectors(conn, provider, project="wisdom-weasel-rag-ime")
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(query_text="压力", project="wisdom-weasel-rag-ime"),
                provider,
            )

        boost = payload["query"]["tagBoost"]
        self.assertTrue(boost["applied"])
        self.assertEqual(boost["tagVectorCount"], 2)
        self.assertEqual(stats["tagVectors"], 2)
        self.assertIn("考试", boost["usedTags"])
        raw_doc_ids = {
            item["doc_id"] for item in payload["hits"] if item["source_lane"] == "vector_raw"
        }
        boosted_doc_ids = {
            item["doc_id"] for item in payload["hits"] if item["source_lane"] == "vector_tag_boost"
        }
        self.assertNotIn("phrase:phrase:复试提醒", raw_doc_ids)
        self.assertIn("phrase:phrase:复试提醒", boosted_doc_ids)

    def test_vector_warmup_populates_provider_cache_for_first_query(self) -> None:
        self._record_event("苹果电脑输入方案", tags=("输入法", "本地模型"))
        provider = SemanticFakeProvider()
        with self.connect() as conn:
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
            rebuild_retrieval_doc_vectors(conn, provider, project="wisdom-weasel-rag-ime")
            warmup = warm_retrieval_doc_vector_cache(
                conn,
                provider.fingerprint,
                project="wisdom-weasel-rag-ime",
            )
            with patch("rag_ime.retrieval_vector_index._vector", side_effect=AssertionError("cold parse")):
                payload = retrieve_hybrid_rag_candidates(
                    conn,
                    HybridRagQuery(query_text="Mac 上怎么打字", project="wisdom-weasel-rag-ime"),
                    provider,
                )

        self.assertTrue(warmup["ok"])
        self.assertGreater(warmup["documents"], 0)
        self.assertGreater(payload["vectorIndexDocuments"], 0)

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
        self.assertEqual(payload["lanes"]["bm25_raw"]["implementation"], "lexical_substring_fallback")

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
        event_id = int(memory_id.split(":", 1)[1])
        with self.connect() as conn:
            apply_memory_book_plan(
                conn,
                memory_book_plan_from_compile_output(
                    {
                        "phraseCandidates": [
                            {"text": text, "tags": list(tags), "sourceEventIds": [event_id], "weight": 0.8}
                        ]
                    },
                    project="wisdom-weasel-rag-ime",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                ),
            )
        return event_id


class SemanticFakeProvider:
    fingerprint = "test-semantic:v1"

    def embed(self, text: str) -> list[float]:
        semantic = any(term in text for term in ("苹果电脑", "输入方案", "输入法", "本地模型"))
        return [1.0, 0.0] if semantic else [0.0, 1.0]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if "Mac" in text or "打字" in text else [0.0, 1.0]


class TagBoostSemanticFakeProvider:
    fingerprint = "test-tag-boost:v1"

    def embed(self, text: str) -> list[float]:
        if text.strip() == "压力":
            return [1.0, 0.0]
        if "考试" in text or "复试" in text:
            return [0.0, 1.0]
        return [0.0, 0.0]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if "压力" in text else [0.0, 1.0]


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
