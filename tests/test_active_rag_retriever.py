from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.active_rag_models import ActiveRagFrame
from rag_ime.active_rag_retriever import (
    _diversify_active_rag_evidence,
    _relevant_active_rag_candidates,
    retrieve_active_rag_evidence,
)
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

    def test_active_rag_keeps_relevant_atom_and_topic_book_in_final_evidence(self) -> None:
        atoms = [
            _memory_hit(
                hit_id=f"hit:atom:{index}",
                doc_type="atom",
                text=f"记忆召回事实 {index}",
                score=1.0 - index / 100,
            )
            for index in range(14)
        ]
        book = _memory_hit(
            hit_id="hit:book:memory-governance",
            doc_type="book",
            text="记忆治理主题书汇总 Atom、来源证据和召回边界。",
            score=0.78,
        )

        selected = _diversify_active_rag_evidence([*atoms, book], limit=12)

        self.assertEqual(len(selected), 12)
        self.assertTrue(any(item.doc_type == "atom" for item in selected))
        self.assertTrue(any(item.doc_type == "book" for item in selected))
        self.assertEqual(selected[-1].hit_id, "hit:book:memory-governance")

    def test_active_rag_excludes_untyped_legacy_memory_item_grounding(self) -> None:
        frame = ActiveRagFrame.from_text("输入法混合检索链路", intent="answer", max_candidates=1)
        legacy = _memory_hit(
            hit_id="hit:item:legacy",
            doc_type="item",
            text="输入法使用混合检索。 输入法使用混合检索。",
            score=0.98,
        )
        atom = _memory_hit(
            hit_id="hit:atom:hybrid",
            doc_type="atom",
            text="输入法使用混合检索提供事实依据。",
            score=0.91,
        )

        selected = _relevant_active_rag_candidates([legacy, atom], frame=frame)

        self.assertEqual(selected, [atom])


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


def _memory_hit(
    *,
    hit_id: str,
    doc_type: str,
    text: str,
    score: float,
) -> MemoryHit:
    source_id = hit_id.removeprefix("hit:")
    return MemoryHit(
        hit_id=hit_id,
        doc_id=source_id,
        doc_type=doc_type,
        source_id=source_id,
        text=text,
        surface_hints=(),
        source_type="memory",
        source_lane="bm25_raw",
        score=score,
        confidence=0.9,
        tags=("记忆",),
        memory_ids=(source_id,),
        atom_ids=(source_id,) if doc_type == "atom" else (),
        book_ids=(source_id,) if doc_type == "book" else (),
        evidence_event_ids=(1,),
        evidence_preview=text,
        metadata={"lanes": ["bm25_raw"], "rawScores": {"bm25_raw": -2.0}},
    )


if __name__ == "__main__":
    unittest.main()
