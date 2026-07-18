from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.active_rag_models import ActiveRagFrame
from rag_ime.active_rag_retriever import _relevant_active_rag_candidates, retrieve_active_rag_evidence
from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.hybrid_rag_models import HybridRagCandidate, MemoryHit
from rag_ime.local_sqlite_core import LocalSqliteCoreClient


class ActiveRagRetrieverTests(unittest.TestCase):
    def test_active_rag_wires_the_core_embedding_provider_into_hybrid_retrieval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-retriever-") as tmp:
            provider = HashingEmbeddingProvider(dimensions=16)
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag.sqlite", embedding_provider=provider)
            frame = ActiveRagFrame.from_text("检查上下文构建与向量召回", intent="complete", max_candidates=1)
            core.initialize()
            with patch("rag_ime.active_rag_retriever._retrieve_candidates_read_only", return_value=[]) as mocked:
                evidence = retrieve_active_rag_evidence(core, frame)

        self.assertEqual(evidence, ())
        self.assertIs(mocked.call_args.kwargs["embedding_provider"], provider)
        query = mocked.call_args.args[1]
        self.assertNotIn("complete", query.query_text)
        self.assertGreaterEqual(query.top_k, 6)

    def test_active_rag_query_path_is_sqlite_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-read-only-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag.sqlite")
            core.initialize()
            frame = ActiveRagFrame.from_text("检查查询热路径", intent="debug", max_candidates=1)

            def attempt_write(conn, query, embedding_provider=None):
                with self.assertRaisesRegex(Exception, "readonly"):
                    conn.execute("INSERT INTO memory_tombstones(created_at_ms, target_type, target_value) VALUES (1, 'id', 'x')")
                return []

            with patch(
                "rag_ime.active_rag_retriever._retrieve_candidates_read_only",
                side_effect=attempt_write,
            ):
                evidence = retrieve_active_rag_evidence(core, frame)

        self.assertEqual(evidence, ())

    def test_generic_foreground_drops_unrelated_fixed_top_k_hits(self) -> None:
        frame = ActiveRagFrame.from_text("这里是前台上下文测试", intent="continue", max_candidates=1)
        unrelated = _candidate(
            text="推荐初音未来或洛天依",
            lanes=["vector_raw"],
            raw_scores={"vector_raw": 0.51},
        )

        self.assertEqual(_relevant_active_rag_candidates([unrelated], frame=frame), [])

    def test_active_rag_keeps_lexical_or_strong_semantic_evidence(self) -> None:
        frame = ActiveRagFrame.from_text("检查向量召回排序", intent="debug", max_candidates=1)
        lexical = _candidate(
            text="向量召回需要先做归一化",
            lanes=["bm25_raw"],
            raw_scores={"bm25_raw": -2.1},
        )
        semantic = _candidate(
            text="语义检索应比较归一化后的余弦距离",
            lanes=["vector_raw"],
            raw_scores={"vector_raw": 0.81},
        )

        self.assertEqual(_relevant_active_rag_candidates([lexical, semantic], frame=frame), [lexical, semantic])

    def test_active_rag_keeps_atom_body_even_without_ime_surface_hint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-atom-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "active-rag.sqlite")
            core.initialize()
            frame = ActiveRagFrame.from_text("输入法现在使用什么模型", intent="answer", max_candidates=1)
            hit = MemoryHit(
                hit_id="hit:atom:model",
                doc_id="atom:current-model",
                doc_type="atom",
                source_id="atom:current-model",
                text="输入法当前使用 100M 自训练模型，旧 0.8B 配置已经停用。",
                surface_hints=(),
                source_type="memory",
                source_lane="bm25_raw",
                score=0.91,
                confidence=0.93,
                tags=("输入法", "模型"),
                memory_ids=("atom:current-model",),
                atom_ids=("atom:current-model",),
                book_ids=(),
                evidence_event_ids=(7,),
                evidence_preview="当前模型事实",
                metadata={"lanes": ["bm25_raw"], "rawScores": {"bm25_raw": -3.2}},
            )

            with patch(
                "rag_ime.active_rag_retriever._retrieve_candidates_read_only",
                return_value=[hit],
            ):
                evidence = retrieve_active_rag_evidence(core, frame)

        self.assertEqual(len(evidence), 1)
        self.assertIn("100M 自训练模型", evidence[0].text)
        self.assertEqual(evidence[0].atom_ids, ("atom:current-model",))


def _candidate(*, text: str, lanes: list[str], raw_scores: dict[str, float]) -> HybridRagCandidate:
    return HybridRagCandidate(
        candidate_id=f"candidate:{text}",
        text=text,
        insert_text=text,
        source_type="rag",
        source_lane=lanes[0],
        score=0.8,
        confidence=0.9,
        tags=(),
        memory_ids=(),
        atom_ids=("atom:1",),
        book_ids=(),
        evidence_event_ids=(1,),
        evidence_preview=text,
        metadata={"lanes": lanes, "rawScores": raw_scores},
    )


if __name__ == "__main__":
    unittest.main()
