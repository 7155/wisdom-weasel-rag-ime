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

    def test_long_planning_content_moves_into_real_native_sheets(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/PlanningPage.swift").read_text(encoding="utf-8")

        for surface in (
            "PlanningDailyPlanEditor",
            "PlanningTaskDetailSheet",
            "PlanningGoalDetailSheet",
            "PlanningAssistantSheet",
            "PlanningCompletionReviewSheet",
        ):
            self.assertIn(surface, page)
        self.assertIn("@State private var taskDetail", page)
        self.assertIn("@State private var goalDetail", page)
        self.assertIn("@State private var assistantPresented", page)
        self.assertIn("@State private var completionReviewPresented", page)
        self.assertIn(".lineLimit(1)", page)
        self.assertIn(".lineLimit(2)", page)

    def test_planning_controls_call_existing_backend_actions_without_fake_delete(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/PlanningPage.swift").read_text(encoding="utf-8")
        model = (ROOT / "macos/RagImeControl/AppModel.swift").read_text(encoding="utf-8")

        for call in (
            "model.loadPlanning()",
            "model.saveDailyPlan(",
            "model.savePlanningTask(",
            "model.savePlanningGoal(",
            "model.performPlanningTaskAction(",
            "model.resolvePlanningSuggestion(",
            "model.sendPlanningAssistantMessage(",
        ):
            self.assertIn(call, page)
        self.assertIn('action: "cancel"', page)
        self.assertIn('status: "archived"', page)
        self.assertNotIn("api/planning/task/delete", model)
        self.assertNotIn("api/planning/goal/delete", model)

    def test_planning_text_uses_shared_readable_font_floor(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/PlanningPage.swift").read_text(encoding="utf-8")
        components = (ROOT / "macos/RagImeControl/Components/ControlComponents.swift").read_text(encoding="utf-8")

        self.assertIn("static let bodyFont = Font.system(size: 15)", components)
        self.assertIn("static let detailFont = Font.system(size: 14)", components)
        self.assertIn("static let metadataFont = Font.system(size: 13)", components)
        self.assertNotIn(".caption2", page)
        self.assertNotIn(".font(.caption", page)


if __name__ == "__main__":
    unittest.main()
