from __future__ import annotations

import unittest

from rag_ime.memory_optimizer import MemoryOptimizerConfig, build_query_plan
from rag_ime.memory_optimizer_models import ContextFrame


def _context(*, input_mode: str, preedit: str = "sj", semantic_query: str = "设计", active_tags: list[str] | None = None) -> ContextFrame:
    return ContextFrame(
        session_id="query-plan-test",
        request_seq=1,
        front_app_bundle_id="com.apple.TextEdit",
        input_mode=input_mode,
        raw_input=preedit,
        preedit=preedit,
        committed_tail="我想继续写输入法",
        selected_rime_candidates=["设计"],
        semantic_query=semantic_query,
        semantic_query_source="rime_candidate",
        composition_hash="composition-hash",
        context_hash="context-hash",
        active_tags=list(active_tags or ["输入法", "设计"]),
        project_scope="wisdom-weasel-rag-ime",
        timestamp_ms=1,
    )


class MemoryOptimizerQueryPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MemoryOptimizerConfig(enabled=True, trace_enabled=True, max_ms=15)

    def test_pinyin_composition_prefers_phrase_fts_and_tag_graph(self) -> None:
        plan = build_query_plan(
            context=_context(input_mode="pinyin_composition", preedit="sj", semantic_query="设计"),
            config=self.config,
            top_k=5,
            latency_budget_ms=15,
        )

        self.assertEqual(plan.retrievers, ["phrase", "stable_memory", "fts", "tag_graph"])
        self.assertEqual(plan.echo_risk_level, "high")
        self.assertEqual(plan.pinyin_terms, ["sj"])
        self.assertFalse(plan.allow_cold_knowledge)

    def test_post_commit_continuation_uses_feedback_retriever(self) -> None:
        plan = build_query_plan(
            context=_context(input_mode="post_commit_continuation", preedit="", semantic_query="连续预测"),
            config=self.config,
            top_k=3,
            latency_budget_ms=12,
        )

        self.assertEqual(plan.retrievers, ["phrase", "stable_memory", "tag_graph", "rime_feedback"])
        self.assertEqual(plan.echo_risk_level, "medium")
        self.assertEqual(plan.max_candidates, 3)
        self.assertEqual(plan.latency_budget_ms, 12)

    def test_code_mode_downranks_broad_rag_retrievers(self) -> None:
        plan = build_query_plan(
            context=_context(input_mode="code", preedit="git", semantic_query="git status"),
            config=self.config,
            top_k=4,
            latency_budget_ms=15,
        )

        self.assertEqual(plan.retrievers, ["phrase", "stable_memory"])
        self.assertEqual(plan.echo_risk_level, "low")

    def test_number_mode_disables_rag_retrievers(self) -> None:
        plan = build_query_plan(
            context=_context(input_mode="number", preedit="123", semantic_query="123"),
            config=self.config,
            top_k=2,
            latency_budget_ms=15,
        )

        self.assertEqual(plan.retrievers, [])
        self.assertEqual(plan.echo_risk_level, "low")

