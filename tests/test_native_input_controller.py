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

    def test_native_frontend_clears_panel_when_input_server_deactivates(self) -> None:
        source = _controller_source()

        deactivate_start = source.index("override func deactivateServer")
        deactivate_end = source.index("private func isPrintableInput")
        deactivate_body = source[deactivate_start:deactivate_end]
        self.assertIn("composition = \"\"", deactivate_body)
        self.assertIn("cancelPendingRefresh(invalidateResponses: true)", deactivate_body)
        self.assertIn("clearCandidateState()", deactivate_body)
        self.assertIn("clearMarkedText(client: client)", deactivate_body)
        self.assertIn("clearVisiblePredictionPanel()", deactivate_body)

    def test_native_frontend_invalidates_async_responses_when_panel_is_hidden(self) -> None:
        source = _controller_source()

        hide_start = source.index("override func hidePalettes")
        hide_end = source.index("override func activateServer")
        hide_body = source[hide_start:hide_end]
        self.assertIn("cancelPendingRefresh(invalidateResponses: true)", hide_body)
        self.assertIn("clearVisiblePredictionPanel()", hide_body)

        cancel_start = source.index("private func cancelPendingRefresh")
        cancel_body = source[cancel_start:]
        self.assertIn("pendingRefresh?.cancel()", cancel_body)
        self.assertIn("pendingRefresh = nil", cancel_body)
        self.assertIn("requestSeq += 1", cancel_body)

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

    def test_native_frontend_uses_backend_prediction_session_expiration(self) -> None:
        source = _controller_source()

        activate_start = source.index("private func activatePanelSession")
        activate_end = source.index("private func schedulePanelExpiration")
        activate_body = source[activate_start:activate_end]
        self.assertIn("let predictionSession = response.predictionSession", activate_body)
        self.assertIn("panelExpirationDate(session: predictionSession, postCommit: postCommit)", activate_body)

        expiration_start = source.index("private func panelExpirationDate")
        expiration_end = source.index("private func shouldShowCandidatePanel")
        expiration_body = source[expiration_start:expiration_end]
        self.assertIn("session?.expiresAfterMs", expiration_body)
        self.assertIn("expiresAfterMs > 0", expiration_body)
        self.assertIn("TimeInterval(expiresAfterMs) / 1000.0", expiration_body)
        self.assertIn("postCommitPanelTtlSeconds", expiration_body)

    def test_native_frontend_drops_stale_async_responses(self) -> None:
        source = _controller_source()

        self.assertIn("response.requestSeq == requestSeq", source)
        self.assertIn("requestSeq == self.requestSeq", source)

    def test_native_frontend_binds_mouse_selection_to_panel_session(self) -> None:
        source = _controller_source()
        models_source = _models_source()

        self.assertIn("canSelectPanelCandidate(candidate, response: response)", source)
        self.assertIn("candidateFingerprint != responseFingerprint", source)
        self.assertIn("sessionFingerprint: String", source)
        self.assertIn("let sessionFingerprint: String?", models_source)

    def test_native_frontend_routes_only_side_candidates_to_rime_select_feedback(self) -> None:
        source = _controller_source()
        models_source = _models_source()

        commit_start = source.index("private func commit(")
        commit_end = source.index("private func commitRawText")
        commit_body = source[commit_start:commit_end]
        self.assertIn("let shownDisplayCandidates = latestDisplayCandidates", commit_body)
        self.assertIn("let shouldRecordSelectedDisplayCandidate = selectedDisplayCandidate.map(shouldRecordSideCandidateSelection) ?? false", commit_body)
        self.assertIn("if shouldRecordSelectedDisplayCandidate", commit_body)
        self.assertIn("shownCandidates: shownDisplayCandidates", commit_body)
        self.assertIn('source: "macos_inputmethod_rime"', commit_body)

        helper_start = source.index("private func shouldRecordSideCandidateSelection")
        helper_body = source[helper_start:]
        self.assertIn('candidate.selectionAction == "select_rime_candidate"', helper_body)
        self.assertIn('candidate.sourceType == "rime"', helper_body)

        self.assertIn("let shownCandidates: [RimeDisplayCandidate]", models_source)

    def test_native_bridge_prefers_http_sidecar_for_rime_requests(self) -> None:
        source = _bridge_source()

        rime_suggest_start = source.index("func rimeSuggest(request:")
        rime_suggest_end = source.index("func rimeSelect(request:")
        rime_suggest_body = source[rime_suggest_start:rime_suggest_end]
        self.assertIn('postSidecar(path: "/rime-suggest"', rime_suggest_body)
        self.assertLess(
            rime_suggest_body.index('postSidecar(path: "/rime-suggest"'),
            rime_suggest_body.index('"rime-suggest-json"'),
        )

        rime_select_start = source.index("func rimeSelect(request:")
        rime_select_end = source.index("func recordCommit(")
        rime_select_body = source[rime_select_start:rime_select_end]
        self.assertIn('postSidecar(path: "/rime-select"', rime_select_body)
        self.assertLess(
            rime_select_body.index('postSidecar(path: "/rime-select"'),
            rime_select_body.index('"rime-select-json"'),
        )
        self.assertIn("sidecarBaseUrl", source)


def _controller_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RagInputController.swift").read_text(encoding="utf-8")


def _panel_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RagCandidatePanel.swift").read_text(encoding="utf-8")


def _models_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RimeSidecarModels.swift").read_text(encoding="utf-8")


def _bridge_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RagBridgeClient.swift").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
