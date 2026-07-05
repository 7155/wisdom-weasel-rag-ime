from __future__ import annotations

import unittest

from rag_ime.memory_optimizer import MemoryOptimizerConfig, RagMemoryOptimizer
from rag_ime.memory_optimizer_models import ContextFrame, RawRetrievalHit


class MemoryOptimizerScoringTests(unittest.TestCase):
    def test_prefix_pinyin_and_feedback_can_beat_higher_base_score(self) -> None:
        optimizer = RagMemoryOptimizer(MemoryOptimizerConfig(enabled=True, trace_enabled=True, max_ms=15))
        context = ContextFrame(
            session_id="scoring-test",
            request_seq=1,
            front_app_bundle_id="com.apple.TextEdit",
            input_mode="pinyin_composition",
            raw_input="lxyc",
            preedit="lxyc",
            committed_tail="我们继续做输入法排序",
            selected_rime_candidates=["连续预测"],
            semantic_query="连续预测",
            semantic_query_source="rime_candidate",
            composition_hash="scoring-compose",
            context_hash="scoring-context",
            active_tags=["连续预测", "输入法", "排序"],
            project_scope="wisdom-weasel-rag-ime",
            timestamp_ms=1,
        )
        strong_match = RawRetrievalHit(
            id="phrase:连续预测",
            text="连续预测",
            source="phrase",
            score=0.55,
            memory_atom_id="phrase:连续预测",
            evidence="高频短语",
            metadata={
                "source_type": "memory",
                "tags": ["phrase-memory", "连续预测"],
                "pinyin_prefixes": ["lxyc"],
                "pinyin_initials": "lxyc",
                "score_breakdown": {
                    "components": {"accepted": 0.9},
                    "rawSignals": {"acceptedCount": 3},
                    "total": 0.55,
                },
            },
        )
        weak_match = RawRetrievalHit(
            id="stable:候选排序",
            text="候选排序",
            source="stable_memory",
            score=0.78,
            memory_atom_id="stable:候选排序",
            evidence="项目背景",
            metadata={
                "source_type": "memory",
                "tags": ["memory", "候选排序"],
            },
        )

        result = optimizer.optimize_memory_candidates(
            context,
            [weak_match, strong_match],
            top_k=3,
            latency_budget_ms=15,
            governance={},
        )

        self.assertEqual([item.id for item in result.candidates], ["phrase:连续预测", "stable:候选排序"])
        self.assertGreater(result.candidates[0].score, result.candidates[1].score)
        self.assertGreater(result.candidates[0].debug_features["pinyinMatch"], result.candidates[1].debug_features["pinyinMatch"])
        self.assertGreater(result.candidates[0].debug_features["acceptedBonus"], result.candidates[1].debug_features["acceptedBonus"])
