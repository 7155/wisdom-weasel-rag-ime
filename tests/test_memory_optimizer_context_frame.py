from __future__ import annotations

import unittest

from rag_ime.memory_optimizer import MemoryOptimizerConfig, build_context_frame, build_query_plan
from rag_ime.models import FrontendTransaction, RimeCandidate, RimeContextSnapshot


class MemoryOptimizerContextFrameTests(unittest.TestCase):
    def test_build_context_frame_prefers_snapshot_semantic_fields(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="optimizer-session",
            request_seq=7,
            raw_input="sj",
            preedit="sj",
            committed_context="我想设计一个输入法",
            project="wisdom-weasel-rag-ime",
            app="com.apple.TextEdit",
            candidates=(RimeCandidate(text="设计"), RimeCandidate(text="时间")),
            frontend_transaction=FrontendTransaction(
                front_app_bundle_id="com.apple.TextEdit",
                composition_hash="sha256:compose",
                committed_context_hash="sha256:context",
            ),
        )

        context = build_context_frame(
            snapshot=snapshot,
            semantic_query="设计",
            query_basis="rimeCandidate",
            input_mode="pinyin_composition",
        )

        self.assertEqual(context.semantic_query, "设计")
        self.assertEqual(context.semantic_query_source, "rime_candidate")
        self.assertEqual(context.selected_rime_candidates, ["设计", "时间"])
        self.assertEqual(context.input_mode, "pinyin_composition")
        self.assertIn("设计", context.active_tags)

    def test_build_query_plan_disables_cold_knowledge_by_default(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="optimizer-plan",
            request_seq=8,
            raw_input="sj",
            preedit="sj",
            committed_context="我想",
            project="wisdom-weasel-rag-ime",
            candidates=(RimeCandidate(text="设计"),),
        )
        context = build_context_frame(
            snapshot=snapshot,
            semantic_query="设计输入法",
            query_basis="commitPreview",
            input_mode="post_commit_continuation",
        )
        plan = build_query_plan(
            context=context,
            config=MemoryOptimizerConfig(enabled=True),
            top_k=5,
            latency_budget_ms=15,
        )

        self.assertEqual(plan.query_text, "设计输入法")
        self.assertIn("phrase", plan.retrievers)
        self.assertIn("stable_memory", plan.retrievers)
        self.assertFalse(plan.allow_cold_knowledge)
        self.assertEqual(plan.echo_risk_level, "medium")

