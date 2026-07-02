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


def _controller_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RagInputController.swift").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
