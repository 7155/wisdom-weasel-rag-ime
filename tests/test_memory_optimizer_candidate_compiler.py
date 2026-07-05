from __future__ import annotations

import unittest

from rag_ime.memory_optimizer import MemoryOptimizerConfig, RagMemoryOptimizer
from rag_ime.memory_optimizer_models import ContextFrame, RawRetrievalHit


class MemoryOptimizerCandidateCompilerTests(unittest.TestCase):
    def test_long_memory_is_compiled_into_short_query_focused_candidate(self) -> None:
        optimizer = RagMemoryOptimizer(MemoryOptimizerConfig(enabled=True, trace_enabled=True, max_ms=15))
        context = ContextFrame(
            session_id="compiler-test",
            request_seq=1,
            front_app_bundle_id="com.apple.TextEdit",
            input_mode="post_commit_continuation",
            raw_input="",
            preedit="",
            committed_tail="我们要把前台稳定性和候选排序都做好",
            selected_rime_candidates=["前台稳定性"],
            semantic_query="前台稳定性",
            semantic_query_source="rime_candidate",
            composition_hash="compiler-compose",
            context_hash="compiler-context",
            active_tags=["前台稳定性", "候选排序", "RAG-IME"],
            project_scope="wisdom-weasel-rag-ime",
            timestamp_ms=1,
        )
        hit = RawRetrievalHit(
            id="stable:product-focus",
            text="用户长期关注 RAG-IME、MLX、本地输入法、候选排序、前台稳定性。",
            source="stable_memory",
            score=0.72,
            memory_atom_id="stable:product-focus",
            evidence="长期项目背景",
            metadata={
                "source_type": "memory",
                "tags": ["memory", "RAG-IME", "候选排序", "前台稳定性"],
            },
        )

        result = optimizer.optimize_memory_candidates(
            context,
            [hit],
            top_k=3,
            latency_budget_ms=15,
            governance={},
        )

        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.text, "前台稳定性")
        self.assertEqual(candidate.lane, "memory")
        self.assertEqual(candidate.source_type, "memory")
        self.assertEqual(candidate.debug_features["compiledCandidate"], 1.0)
        self.assertLessEqual(len(candidate.text), 12)
        self.assertNotIn("用户长期关注 RAG-IME、MLX、本地输入法、候选排序、前台稳定性。", candidate.evidence_preview or "")
