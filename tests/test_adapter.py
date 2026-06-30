from __future__ import annotations

import unittest

from rag_ime.adapter import InputMethodAdapter, SuggestionRequest
from rag_ime.agent_hook import build_first_run_injection
from rag_ime.cli import run_acceptance
from rag_ime.core_client import FixtureCoreClient
from rag_ime.renderer import render_candidate_bar, render_expanded_evidence, render_terminal_panel
from rag_ime.scenarios import SCENARIOS, get_scenario


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


if __name__ == "__main__":
    unittest.main()
