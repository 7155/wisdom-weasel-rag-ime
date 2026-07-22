from __future__ import annotations

import unittest

from rag_ime.hybrid_rag_models import HybridRagHit
from rag_ime.hybrid_rag_ranker import rank_hybrid_hits, rank_hybrid_hits_to_memory_hits, rrf


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

    def test_query_coverage_prevents_broad_tag_from_beating_exact_fact(self) -> None:
        broad = HybridRagHit(
            doc_id="doc:broad",
            doc_type="atom",
            source_id="atom:broad",
            text="输入法相关场景是当前项目的首要产品优先级。",
            surface_hints=(),
            tags=("项目", "评测"),
            source_lane="bm25_tags",
            rank=1,
            raw_score=1.0,
        )
        exact = HybridRagHit(
            doc_id="doc:exact",
            doc_type="atom",
            source_id="atom:exact",
            text="项目评测优先采用社区认可、可复现的公开 Benchmark；私有测试集只作为补充证据。",
            surface_hints=(),
            tags=("公开评测",),
            source_lane="bm25_raw",
            rank=2,
            raw_score=1.0,
        )

        candidates = rank_hybrid_hits_to_memory_hits(
            [broad, exact],
            query_text="项目评测应该优先使用什么测试集",
        )

        self.assertEqual(candidates[0].text, exact.text)
        self.assertGreater(
            candidates[0].debug_features["query_coverage"],
            candidates[1].debug_features["query_coverage"],
        )

    def test_type_specific_decay_favors_stable_preference_over_old_temporary_fact(self) -> None:
        current_ms = 2_000_000_000_000
        sixty_days_ago = current_ms - 60 * 86_400_000
        temporary = HybridRagHit(
            doc_id="doc:temporary",
            doc_type="atom",
            source_id="atom:temporary",
            text="临时任务",
            surface_hints=("临时任务",),
            tags=(),
            source_lane="bm25_raw",
            rank=1,
            raw_score=1.0,
            metadata={"kind": "temporary_task", "sourceUpdatedAtMs": sixty_days_ago},
        )
        stable = HybridRagHit(
            doc_id="doc:stable",
            doc_type="atom",
            source_id="atom:stable",
            text="稳定偏好",
            surface_hints=("稳定偏好",),
            tags=(),
            source_lane="bm25_raw",
            rank=1,
            raw_score=1.0,
            metadata={"kind": "stable_preference", "sourceUpdatedAtMs": sixty_days_ago},
        )

        candidates = rank_hybrid_hits(
            [temporary, stable],
            current_ms=current_ms,
            top_k=2,
            decay_settings={"temporaryHalfLifeDays": 14, "stablePreferenceHalfLifeDays": 365},
        )

        self.assertEqual(candidates[0].text, "稳定偏好")
        by_text = {item.text: item for item in candidates}
        self.assertLess(by_text["临时任务"].metadata["timeDecayFactor"], by_text["稳定偏好"].metadata["timeDecayFactor"])

    def test_explicit_historical_query_bypasses_age_and_archive_decay(self) -> None:
        current_ms = 2_000_000_000_000
        old_archived = HybridRagHit(
            doc_id="doc:archived",
            doc_type="book",
            source_id="book:archived",
            text="旧项目归档",
            surface_hints=("旧项目方向",),
            tags=(),
            source_lane="time",
            rank=1,
            raw_score=1.0,
            metadata={
                "bookType": "topic",
                "sourceUpdatedAtMs": current_ms - 500 * 86_400_000,
                "archived": True,
            },
        )

        ordinary = rank_hybrid_hits([old_archived], current_ms=current_ms, query_text="项目方向")
        historical = rank_hybrid_hits([old_archived], current_ms=current_ms, query_text="去年项目方向")
        initial_requirement = rank_hybrid_hits(
            [old_archived], current_ms=current_ms, query_text="最初需求是什么"
        )

        self.assertLess(ordinary[0].metadata["timeDecayFactor"], 0.1)
        self.assertEqual(historical[0].metadata["timeDecayFactor"], 1.0)
        self.assertEqual(initial_requirement[0].metadata["timeDecayFactor"], 1.0)
        self.assertGreater(historical[0].score, ordinary[0].score)

    def test_metadata_family_is_capped_instead_of_counted_as_three_votes(self) -> None:
        hits = [
            HybridRagHit(
                doc_id="doc:metadata",
                doc_type="atom",
                source_id="atom:metadata",
                text="元数据命中",
                surface_hints=(),
                tags=("tag",),
                source_lane=lane,
                rank=1,
                raw_score=1.0,
            )
            for lane in ("bm25_tags", "tagmemo", "vector_tag_boost")
        ]

        capped = rank_hybrid_hits_to_memory_hits(hits)[0]
        legacy = rank_hybrid_hits_to_memory_hits(
            hits,
            metadata_family_mode="legacy_sum",
        )[0]
        strongest = max(
            capped.debug_features[lane]
            for lane in ("bm25_tags", "tagmemo", "vector_tag_boost")
        )

        self.assertLessEqual(capped.score, strongest * 1.20 + 1e-12)
        self.assertLess(capped.score, legacy.score)
        self.assertLess(
            capped.debug_features["metadata_family_overlap_penalty"],
            0.0,
        )

    def test_metadata_cap_does_not_reduce_independent_raw_families(self) -> None:
        hits = [
            HybridRagHit(
                doc_id="doc:raw",
                doc_type="atom",
                source_id="atom:raw",
                text="独立原始证据",
                surface_hints=(),
                tags=(),
                source_lane=lane,
                rank=1,
                raw_score=1.0,
            )
            for lane in ("bm25_raw", "vector_raw")
        ]

        capped = rank_hybrid_hits_to_memory_hits(hits)[0]
        legacy = rank_hybrid_hits_to_memory_hits(
            hits,
            metadata_family_mode="legacy_sum",
        )[0]

        self.assertAlmostEqual(capped.score, legacy.score)
        self.assertNotIn(
            "metadata_family_overlap_penalty",
            capped.debug_features,
        )


if __name__ == "__main__":
    unittest.main()
