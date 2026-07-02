from __future__ import annotations

import unittest
from pathlib import Path


class NativeInputControllerSourceTests(unittest.TestCase):
    def test_space_selects_first_candidate_before_printable_fallback(self) -> None:
        source = _controller_source()

        space_branch = source.index('if string == " "')
        printable_branch = source.index("if isPrintableInput(string)")
        self.assertLess(space_branch, printable_branch)
        self.assertIn("selectFirstCandidateIfAvailable(client: client)", source)
        self.assertIn('commitRawText(text: "\\(composition) ", preedit: composition, client: client)', source)

    def test_raw_passthrough_space_does_not_trigger_post_commit_prediction(self) -> None:
        source = _controller_source()

        raw_commit_start = source.index("private func commitRawText")
        raw_commit_end = source.index("private func cancelCurrentComposition")
        raw_commit_body = source[raw_commit_start:raw_commit_end]
        self.assertIn("source: \"macos_inputmethod_raw\"", raw_commit_body)
        self.assertNotIn("schedulePostCommitPrediction", raw_commit_body)

    def test_sidecar_clear_policy_hides_native_panel(self) -> None:
        source = _controller_source()

        should_show_start = source.index("private func shouldShowCandidatePanel")
        should_show_end = source.index("private func handlePanelAction")
        should_show_body = source[should_show_start:should_show_end]
        self.assertIn("session.shouldClearPredictionPanel", should_show_body)
        self.assertIn("return false", should_show_body)

    def test_panel_anchor_uses_marked_text_range_while_composing(self) -> None:
        source = _controller_source()

        anchor_start = source.index("private func panelAnchor")
        anchor_body = source[anchor_start:]
        self.assertIn("markedCaretRange", anchor_body)
        self.assertIn("if !composition.isEmpty", anchor_body)
        self.assertIn("range = markedCaretRange", anchor_body)

    def test_candidate_panel_extracts_inline_model_candidates_even_after_rag(self) -> None:
        source = _panel_source()

        self.assertIn("visible.filter { isInlineCandidate($0) }.prefix(5)", source)
        self.assertIn("visible.filter { !isInlineCandidate($0) }", source)
        self.assertIn("candidate.selectionRank", source)
        self.assertIn("candidate.selectionKey", source)

    def test_native_frontend_selects_by_backend_selection_rank(self) -> None:
        source = _controller_source()

        self.assertIn("displayCandidate(matchingSelectionNumber:", source)
        self.assertIn("candidate.selectionRank == number", source)
        self.assertIn("candidate.selectionKey == \"\\(number)\"", source)

    def test_native_frontend_keeps_ime_latency_budget_for_streaming_mlx(self) -> None:
        source = _controller_source()
        models_source = _models_source()

        self.assertIn("latencyBudgetMs: 300", source)
        self.assertIn("latencyBudgetMs: Int = 300", models_source)


def _controller_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RagInputController.swift").read_text(encoding="utf-8")


def _panel_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RagCandidatePanel.swift").read_text(encoding="utf-8")


def _models_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RimeSidecarModels.swift").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
