"""Focused checks for the staged generation UI in the assistant overlay card.

The explicit-generation card renders four stage rows (context acquisition,
recent history, RAG recall, model answer). Their presentation model,
``RagImeGenerationStagePlanner``, must interpret exactly the progress stages
the rag_ime sidecar reports through ``_active_rag_progress_payload`` and must
expose pending/active/done/failed states that stay honest at a glance.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD_SOURCE = ROOT / "squirrel-patches" / "sources" / "RagImeSuggestionCardView.swift"
PATCH = ROOT / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch"
SIDECAR_SERVICE = ROOT / "rag_ime" / "active_rag_service.py"


def _sidecar_progress_stages(service_text: str) -> set[str]:
    """Extract the stage vocabulary emitted by _active_rag_progress_payload."""
    match = re.search(
        r"def _active_rag_progress_payload\(.*?\n(?=\ndef |\nclass )",
        service_text,
        re.DOTALL,
    )
    assert match is not None, "sidecar progress payload function not found"
    body = match.group(0)
    stages = set(re.findall(r'stage = "([a-z_]+)"', body))
    status_set = re.search(r'session\.status in \{([^}]+)\}', body)
    if status_set:
        stages.update(re.findall(r'"([a-z_]+)"', status_set.group(1)))
    return stages


class AssistantGenerationStagePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.card_text = CARD_SOURCE.read_text(encoding="utf-8")
        self.patch_text = PATCH.read_text(encoding="utf-8")
        self.service_text = SIDECAR_SERVICE.read_text(encoding="utf-8")

    def _planner_block(self) -> str:
        start = self.card_text.index("enum RagImeGenerationStagePlanner {")
        end = self.card_text.index("final class RagImeSuggestionCardView")
        return self.card_text[start:end].rstrip()

    def test_planner_covers_every_stage_the_sidecar_actually_emits(self) -> None:
        stages = _sidecar_progress_stages(self.service_text)
        self.assertIn("capturing_context", stages)
        self.assertIn("retrieval_complete", stages)
        self.assertIn("error", stages)
        planner = self._planner_block()
        for stage in sorted(stages):
            self.assertIn(
                f'"{stage}"',
                planner,
                f"planner must interpret sidecar stage {stage!r}",
            )

    def test_planner_does_not_invent_a_retrieving_stage(self) -> None:
        stages = _sidecar_progress_stages(self.service_text)
        self.assertNotIn("retrieving", stages)
        self.assertNotIn('stage == "retrieving"', self.card_text)
        self.assertNotIn('"retrieving"', self._planner_block())

    def test_stage_rows_expose_pending_active_done_and_failed_states(self) -> None:
        for case in ("case pending", "case active", "case done", "case failed"):
            self.assertIn(case, self.card_text)
        # Failure is readable at a glance: distinct icon, tint, and label word.
        self.assertIn('symbol = "exclamationmark.triangle.fill"', self.card_text)
        self.assertIn("color = .systemOrange", self.card_text)
        self.assertIn('case .failed: return "未完成"', self.card_text)
        self.assertIn("model.state.accessibilityWord", self.card_text)

    def test_terminal_failure_stages_render_honest_titles(self) -> None:
        planner = self._planner_block()
        self.assertIn('failureStages: Set<String> = ["error", "cancelled", "stale_dropped"]', planner)
        self.assertIn('case "error": title = "生成未完成"', planner)
        self.assertIn('case "cancelled": title = "已停止生成"', planner)
        self.assertIn('case "stale_dropped": title = "输入已更新，本轮已作废"', planner)
        # An interrupted run marks the first unfinished step, not finished ones.
        self.assertIn("let contextInterrupted = interrupted && !contextDone", planner)
        self.assertIn("let retrievalInterrupted = interrupted && contextDone && !retrievalDone", planner)
        self.assertIn(
            "let modelInterrupted = interrupted && contextDone && retrievalDone && !modelDone",
            planner,
        )

    def test_done_or_hidden_rows_never_keep_an_active_indicator(self) -> None:
        # resolve() gives failed > done > active priority, so a completed row
        # can never render as in-flight again.
        planner = self._planner_block()
        self.assertIn("if failed { return .failed }", planner)
        self.assertIn("if done { return .done }", planner)
        self.assertIn("if active { return .active }", planner)
        self.assertIn("active = model.state == .active", self.card_text)
        self.assertIn("let animate = active && visible", self.card_text)
        self.assertIn("progressRows.forEach { $0.stopActivity() }", self.card_text)
        self.assertNotIn("CAGradientLayer", self.card_text)

    def test_card_delegates_rows_to_the_planner_with_stable_stage_titles(self) -> None:
        self.assertIn("let plan = RagImeGenerationStagePlanner.plan(input)", self.card_text)
        self.assertIn("row.apply(model: plan.rows[index])", self.card_text)
        self.assertIn("progressSummaryText = plan.summary", self.card_text)
        for title in ("理解当前内容", "补充近期上下文", "查找相关记忆", "组织回答"):
            self.assertIn(title, self.card_text)
        # Context capture failure stays visible without stopping later stages.
        self.assertIn('input.diagnosticStatus.contains("context_missing")', self.card_text)
        self.assertIn("未读取到前台内容，仅使用已有输入", self.card_text)

    def test_patch_ships_the_same_planner_as_the_canonical_source(self) -> None:
        expected = "\n".join(f"+{line}" for line in self._planner_block().splitlines())
        self.assertIn(
            expected,
            self.patch_text,
            "run scripts/sync_assistant_overlay_patch_sources.py after editing the card source",
        )


if __name__ == "__main__":
    unittest.main()
