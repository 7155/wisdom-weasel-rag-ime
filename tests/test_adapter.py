from __future__ import annotations

import unittest

from rag_ime.adapter import InputMethodAdapter, SuggestionRequest
from rag_ime.agent_hook import build_first_run_injection
from rag_ime.cli import run_acceptance
from rag_ime.core_client import FixtureCoreClient
from rag_ime.renderer import render_candidate_bar, render_expanded_evidence, render_terminal_panel
from rag_ime.scenarios import SCENARIOS, get_scenario
from rag_ime.suggestion_compiler import classify_suggestion
from rag_ime.trigger_policy import TypingState, should_refresh_rag


class InputMethodAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core = FixtureCoreClient()
        self.adapter = InputMethodAdapter(self.core)

    def test_three_ui_scenarios_have_short_candidates_and_evidence(self) -> None:
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario.scenario_id):
                suggestions = self.adapter.suggest(
                    SuggestionRequest(
                        current_input=scenario.current_input,
                        recent_context=scenario.recent_context,
                        project=scenario.project,
                        top_k=5,
                    )
                )
                self.assertGreaterEqual(len(suggestions), 3)
                self.assertLessEqual(max(len(item.surface_text) for item in suggestions), 42)
                self.assertTrue(all(item.evidence_preview for item in suggestions))
                self.assertTrue({"commit", "expand", "pin", "downrank", "delete"}.issubset(suggestions[0].actions))
                panel = render_terminal_panel(
                    title=scenario.title,
                    current_input=scenario.current_input,
                    recent_context=scenario.recent_context,
                    suggestions=suggestions,
                )
                self.assertIn("candidate_bar:", panel)
                self.assertIn("evidence_preview:", panel)
                self.assertIn("expanded_evidence:", panel)

    def test_action_feedback_changes_later_ranking(self) -> None:
        scenario = get_scenario("technical-plan")
        request = SuggestionRequest(
            current_input=scenario.current_input,
            recent_context=scenario.recent_context,
            project=scenario.project,
            top_k=4,
        )
        before = self.adapter.suggest(request)
        self.adapter.pin(before[-1], query=scenario.current_input)
        self.adapter.delete(before[0], query=scenario.current_input)
        after = self.adapter.suggest(request)
        self.assertNotIn(before[0].surface_text, [item.surface_text for item in after])
        self.assertEqual(after[0].surface_text, before[-1].surface_text)

    def test_agent_hook_builds_project_memory_block(self) -> None:
        injection = build_first_run_injection(self.adapter, project="wisdom-weasel-rag-ime", top_k=3)
        self.assertIn("PROJECT_MEMORY_BLOCK", injection.block)
        self.assertIn("local-first", injection.block)
        self.assertGreaterEqual(len(injection.source_event_ids), 1)

    def test_commit_event_is_forwarded_to_core(self) -> None:
        event_id = self.adapter.commit_text(
            "默认本地完成, 不上传个人输入历史",
            recent_context="隐私边界",
            preedit="moren bendi",
            tags=("privacy",),
        )
        self.assertEqual(event_id, "event:1")
        self.assertEqual(self.core.events[0].committed_text, "默认本地完成, 不上传个人输入历史")
        self.assertEqual(self.core.events[0].preedit, "moren bendi")

    def test_sensitive_or_disabled_commit_is_not_recorded(self) -> None:
        sensitive = self.adapter.commit_text("银行卡密码", field_is_sensitive=True)
        disabled = self.adapter.commit_text("暂停记录", recording_enabled=False)
        self.assertEqual(sensitive, "skipped:sensitive_field")
        self.assertEqual(disabled, "skipped:recording_disabled")
        self.assertEqual(self.core.events, [])

    def test_renderer_keeps_full_evidence_out_of_candidate_bar(self) -> None:
        scenario = get_scenario("project-term-agent-hook")
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input=scenario.current_input,
                recent_context=scenario.recent_context,
                project=scenario.project,
                top_k=3,
            )
        )
        candidate_bar = render_candidate_bar(suggestions)
        expanded = render_expanded_evidence(suggestions[0])
        self.assertNotIn("source_ref", candidate_bar)
        self.assertIn("memory_id", expanded)

    def test_acceptance_report_passes_required_gates(self) -> None:
        report = run_acceptance(self.adapter)
        self.assertTrue(report["local_first"])
        self.assertFalse(report["cloud_default"])
        self.assertFalse(report["fine_tuning"])
        self.assertTrue(report["action_result"]["deleted_removed"])
        self.assertTrue(report["agent_hook"]["has_project_memory_block"])
        self.assertFalse(report["trigger_policy"]["single_char"])
        self.assertTrue(report["trigger_policy"]["idle_semantic"])
        self.assertFalse(report["trigger_policy"]["sensitive"])

    def test_suggestion_compiler_keeps_insert_text_and_source_metadata(self) -> None:
        scenario = get_scenario("technical-plan")
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input=scenario.current_input,
                recent_context=scenario.recent_context,
                project=scenario.project,
                top_k=5,
            )
        )
        structure = next(item for item in suggestions if item.metadata["memory_id"] == "mem-structure-plan")
        self.assertEqual(structure.suggestion_type, "structure")
        self.assertIn("insert_text", structure.metadata)
        self.assertIn("sources", structure.metadata)
        self.assertLessEqual(len(structure.surface_text), 42)

    def test_suggestion_type_classification(self) -> None:
        self.assertEqual(classify_suggestion("固定短语"), "phrase")
        self.assertEqual(classify_suggestion("这是一句超过二十四个字符的候选表达, 适合直接插入"), "sentence")
        self.assertEqual(classify_suggestion("第一步先验证 FTS5, 第二步接 embedding"), "structure")
        self.assertEqual(classify_suggestion("保持面试表达简洁", ("style",)), "style_hint")
        self.assertEqual(classify_suggestion("原文引用", ("quote",)), "quote")

    def test_trigger_policy_is_not_word_by_word_or_privacy_blind(self) -> None:
        self.assertFalse(should_refresh_rag(TypingState(current_input="项", idle_ms=500)).should_refresh)
        self.assertTrue(should_refresh_rag(TypingState(current_input="这个项目", idle_ms=300)).should_refresh)
        self.assertTrue(should_refresh_rag(TypingState(current_input="这个项目，", idle_ms=0)).should_refresh)
        self.assertTrue(should_refresh_rag(TypingState(current_input="hi", explicit_request=True)).should_refresh)
        sensitive = should_refresh_rag(TypingState(current_input="银行卡密码", idle_ms=800, field_is_sensitive=True))
        self.assertFalse(sensitive.should_refresh)
        self.assertIn("sensitive", sensitive.reason)


if __name__ == "__main__":
    unittest.main()
