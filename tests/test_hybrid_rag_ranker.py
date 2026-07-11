from __future__ import annotations

import unittest

from rag_ime.hybrid_rag_models import HybridRagHit
from rag_ime.hybrid_rag_ranker import rank_hybrid_hits, rrf


class HybridRagRankerTests(unittest.TestCase):
    def test_hybrid_ranker_uses_rrf_not_raw_score_addition(self) -> None:
        self.assertAlmostEqual(rrf(1), 1.0 / 61.0)
        raw_giant = HybridRagHit(
            doc_id="doc:giant",
            doc_type="phrase",
            source_id="phrase:巨分",
            text="巨分",
            surface_hints=("巨分",),
            tags=("RAG",),
            source_lane="bm25_raw",
            rank=10,
            raw_score=9999.0,
        )
        multi_lane_a = HybridRagHit(
            doc_id="doc:multi",
            doc_type="phrase",
            source_id="phrase:多路召回",
            text="多路召回",
            surface_hints=("多路召回",),
            tags=("RAG",),
            source_lane="bm25_raw",
            rank=1,
            raw_score=1.0,
        )
        multi_lane_b = HybridRagHit(
            doc_id="doc:multi",
            doc_type="phrase",
            source_id="phrase:多路召回",
            text="多路召回",
            surface_hints=("多路召回",),
            tags=("RAG",),
            source_lane="tagmemo",
            rank=1,
            raw_score=1.0,
        )

        candidates = rank_hybrid_hits([raw_giant, multi_lane_a, multi_lane_b], top_k=2)

        self.assertEqual(candidates[0].text, "多路召回")
        self.assertIn("bm25_raw", candidates[0].debug_features)
        self.assertIn("tagmemo", candidates[0].debug_features)

    def test_runtime_lane_weights_change_real_candidate_order(self) -> None:
        raw = HybridRagHit(
            doc_id="doc:raw",
            doc_type="phrase",
            source_id="phrase:原文优先",
            text="原文优先",
            surface_hints=("原文优先",),
            tags=(),
            source_lane="bm25_raw",
            rank=1,
            raw_score=1.0,
        )
        tag = HybridRagHit(
            doc_id="doc:tag",
            doc_type="phrase",
            source_id="phrase:标签优先",
            text="标签优先",
            surface_hints=("标签优先",),
            tags=("RAG",),
            source_lane="tagmemo",
            rank=1,
            raw_score=1.0,
        )

        default_order = rank_hybrid_hits([raw, tag], top_k=2)
        configured_order = rank_hybrid_hits(
            [raw, tag],
            top_k=2,
            lane_weights={"bm25_raw": 5.0, "tagmemo": 0.1},
        )

        self.assertEqual(default_order[0].text, "标签优先")
        self.assertEqual(configured_order[0].text, "原文优先")
        self.assertGreater(
            configured_order[0].debug_features["bm25_raw"],
            configured_order[1].debug_features["tagmemo"],
        )


if __name__ == "__main__":
    unittest.main()
