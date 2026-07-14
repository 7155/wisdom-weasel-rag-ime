from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlanningUIContractTests(unittest.TestCase):
    def test_primary_planning_actions_are_visible_and_reachable(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/PlanningPage.swift").read_text(encoding="utf-8")

        self.assertIn('DatePicker("日期"', page)
        self.assertIn('Label("保存计划", systemImage: "square.and.arrow.down")', page)
        self.assertIn('Label("新建任务", systemImage: "plus")', page)
        self.assertIn('Label("新建目标", systemImage: "plus")', page)
        self.assertIn('Label("拆成任务", systemImage: "arrow.turn.down.right")', page)
        self.assertIn('Label("发送", systemImage: "arrow.up")', page)
        self.assertIn("PlanningEmptyAction", page)
        self.assertIn("PlanningGoalRow", page)

    def test_planning_requests_ignore_stale_day_responses_and_double_sends(self) -> None:
        model = (ROOT / "macos/RagImeControl/AppModel.swift").read_text(encoding="utf-8")

        self.assertIn("private var planningLoadGeneration = 0", model)
        self.assertIn("guard generation == planningLoadGeneration else { return }", model)
        self.assertIn("func sendPlanningAssistantMessage(_ proposedMessage: String? = nil) async", model)
        self.assertIn("guard !message.isEmpty, !planningBusy else { return }", model)


if __name__ == "__main__":
    unittest.main()
