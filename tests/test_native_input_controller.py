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
        self.assertIn("selectedRange.location == NSNotFound", anchor_body)
        self.assertIn("NSRange(location: NSNotFound, length: 0)", anchor_body)
        self.assertNotIn("composition.utf16.count", anchor_body)

    def test_native_frontend_shows_local_rime_candidates_before_async_sidecar(self) -> None:
        source = _controller_source()

        printable_start = source.index("if isPrintableInput(string)")
        printable_end = source.index("override func commitComposition")
        printable_body = source[printable_start:printable_end]
        self.assertIn("showLocalRimeFallbackCandidates(for: composition, client: client)", printable_body)
        self.assertLess(
            printable_body.index("showLocalRimeFallbackCandidates(for: composition, client: client)"),
            printable_body.index("scheduleSuggestionRefresh(client: client)"),
        )

        local_start = source.index("private func showLocalRimeFallbackCandidates")
        local_end = source.index("private func activatePanelSession")
        local_body = source[local_start:local_end]
        self.assertIn('sourceType: "rime"', local_body)
        self.assertIn('selectionAction: "select_rime_candidate"', local_body)
        self.assertIn('phase: "anchor_composing"', local_body)
        self.assertIn("RagCandidatePanel.shared.show", local_body)

    def test_native_frontend_does_not_cold_load_wanxiang_on_input_thread(self) -> None:
        source = _controller_source()
        provider_source = _dictionary_provider_source()

        self.assertIn("rimeCandidateProvider.warmUp()", source)
        self.assertIn("allowColdLoad: false", source)
        self.assertIn("rimeCandidateProvider.isReady", source)
        self.assertIn("func warmUp()", provider_source)
        self.assertIn("var isReady: Bool", provider_source)
        self.assertIn("startWarmUpIfNeeded()", provider_source)

    def test_native_frontend_keeps_local_rime_candidates_when_sidecar_fails(self) -> None:
        source = _controller_source()

        refresh_start = source.index("private func scheduleSuggestionRefresh")
        refresh_end = source.index("private func schedulePostCommitPrediction")
        refresh_body = source[refresh_start:refresh_end]
        self.assertIn("catch", refresh_body)
        self.assertIn("self.composition == inputSnapshot", refresh_body)
        self.assertIn("self.committedContext == contextSnapshot", refresh_body)
        self.assertIn("self.showLocalRimeFallbackCandidates(for: inputSnapshot", refresh_body)
        self.assertNotIn("self?.clearCandidateState()", refresh_body)

    def test_candidate_panel_extracts_inline_model_candidates_even_after_rag(self) -> None:
        source = _panel_source()

        self.assertIn("visible.filter { isInlineCandidate($0) }.prefix(5)", source)
        self.assertIn("visible.filter { !isInlineCandidate($0) }", source)
        self.assertIn("candidate.selectionRank", source)
        self.assertIn("candidate.selectionKey", source)

    def test_native_candidate_text_does_not_append_source_suffixes(self) -> None:
        controller = _controller_source()
        panel = _panel_source()

        self.assertIn("latestDisplayCandidates.map(displayTextForSystemCandidate)", controller)
        self.assertIn("private func stripSourceSuffix", controller)
        self.assertIn('"_model"', controller)
        self.assertIn('"_rag"', controller)
        self.assertIn("candidateDisplayText(candidate)", panel)
        self.assertIn("source: \"\"", panel)
        self.assertNotIn("source: candidate.sourceType", panel)
        self.assertNotIn("source: sourceBadge(candidate)", panel)

    def test_native_frontend_selects_by_backend_selection_rank(self) -> None:
        source = _controller_source()

        self.assertIn("displayCandidate(matchingSelectionNumber:", source)
        self.assertIn('latestKeyPolicy?.numberKeys == "select_visible_candidate"', source)
        self.assertIn("candidate.selectionRank == number", source)
        self.assertIn("candidate.selectionKey == \"\\(number)\"", source)
        self.assertIn("selectionNumber(forKey:", source)
        self.assertIn('if key == "0"', source)
        self.assertIn("return 10", source)

    def test_native_frontend_routes_digits_from_raw_keydown_before_text_insertion(self) -> None:
        source = _controller_source()

        handle_start = source.index("override func handle")
        handle_end = source.index("override func inputText")
        handle_body = source[handle_start:handle_end]
        self.assertIn("event.type == .keyDown", handle_body)
        self.assertIn("event.charactersIgnoringModifiers", handle_body)
        self.assertIn("selectCandidateIfNeeded(key, client: client)", handle_body)
        self.assertIn("hadVisiblePanel", handle_body)
        self.assertIn("return true", handle_body)
        self.assertIn("return inputText(text, client: sender)", handle_body)

    def test_native_frontend_backspace_updates_composition_or_committed_context(self) -> None:
        source = _controller_source()

        handle_start = source.index("override func handle")
        handle_end = source.index("override func inputText")
        handle_body = source[handle_start:handle_end]
        self.assertIn("event.keyCode == 51", handle_body)
        self.assertIn("handleBackspace(client: client)", handle_body)

        input_start = source.index("override func inputText")
        input_end = source.index("override func commitComposition")
        input_body = source[input_start:input_end]
        self.assertIn("isBackspaceText(string)", input_body)
        self.assertIn("handleBackspace(client: client)", input_body)

        backspace_start = source.index("private func handleBackspace")
        backspace_end = source.index("private func scheduleSuggestionRefresh")
        backspace_body = source[backspace_start:backspace_end]
        self.assertIn("removeLastCommittedContextCharacter()", backspace_body)
        self.assertIn("return false", backspace_body)
        self.assertIn("composition.removeLast()", backspace_body)
        self.assertIn("scheduleSuggestionRefresh(client: client)", backspace_body)
        self.assertIn("clearVisiblePredictionPanel()", backspace_body)

        context_start = source.index("private func removeLastCommittedContextCharacter")
        context_body = source[context_start:]
        self.assertIn("context.removeLast()", context_body)
        self.assertIn("committedContext = context.trimmingCharacters", context_body)

    def test_native_frontend_syncs_committed_context_from_actual_client_text(self) -> None:
        source = _controller_source()

        commit_start = source.index("private func commit(")
        commit_end = source.index("private func commitRawText")
        commit_body = source[commit_start:commit_end]
        self.assertIn("actualCommittedContext(client: client, fallback: committedContext, excludingMarkedText: composition)", commit_body)
        self.assertIn("actualCommittedContext(client: client, fallback: appendingContext(previousContext, finalText))", commit_body)

        refresh_start = source.index("private func scheduleSuggestionRefresh")
        refresh_end = source.index("private func schedulePostCommitPrediction")
        refresh_body = source[refresh_start:refresh_end]
        self.assertIn("syncCommittedContextFromClient(providedClient ?? client(), excludingMarkedText: inputSnapshot)", refresh_body)

        post_start = source.index("private func schedulePostCommitPrediction")
        post_end = source.index("private func renderSidecarResponse")
        post_body = source[post_start:post_end]
        self.assertIn("syncCommittedContextFromClient(providedClient)", post_body)

        actual_start = source.index("private func actualCommittedContext")
        actual_end = source.index("private func boundedContext")
        actual_body = source[actual_start:actual_end]
        self.assertIn("client.selectedRange()", actual_body)
        self.assertIn("client.attributedSubstring(from: range)", actual_body)
        self.assertIn("text.hasSuffix(markedText)", actual_body)
        self.assertIn("text.removeLast(markedText.count)", actual_body)

    def test_native_frontend_empty_sidecar_response_keeps_existing_panel_unless_clear_requested(self) -> None:
        source = _controller_source()

        render_start = source.index("private func renderSidecarResponse")
        render_end = source.index("private func showLocalRimeFallbackCandidates")
        render_body = source[render_start:render_end]
        empty_index = render_body.index("if panelDisplayCandidates.isEmpty")
        should_show_index = render_body.index("if !shouldShowCandidatePanel(response, panelDisplayCandidates: panelDisplayCandidates)")
        self.assertLess(empty_index, should_show_index)
        empty_body = render_body[empty_index:should_show_index]
        self.assertIn("response.predictionSession?.shouldClearPredictionPanel == true", empty_body)
        self.assertIn("clearCandidateState()", empty_body)
        self.assertIn("clearVisiblePredictionPanel()", empty_body)
        self.assertIn("return", empty_body)

    def test_native_frontend_keeps_ime_latency_budget_for_streaming_mlx(self) -> None:
        source = _controller_source()
        models_source = _models_source()

        self.assertIn("latencyBudgetMs: 3200", source)
        self.assertIn("latencyBudgetMs: Int = 3200", models_source)

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
        self.assertIn("private let postCommitPanelTtlSeconds: TimeInterval = 8.0", source)

    def test_native_frontend_schedules_progressive_follow_up_for_pending_model_lane(self) -> None:
        source = _controller_source()
        models_source = _models_source()

        self.assertIn("let progressive: RimeProgressivePayload?", models_source)
        self.assertIn("struct RimeProgressivePayload: Codable", models_source)
        self.assertIn("private var pendingProgressiveFollowUp", source)
        self.assertIn("scheduleProgressiveFollowUpIfNeeded(", source)

        render_start = source.index("private func renderSidecarResponse")
        render_end = source.index("private func showLocalRimeFallbackCandidates")
        render_body = source[render_start:render_end]
        self.assertIn("scheduleProgressiveFollowUpIfNeeded(", render_body)
        self.assertLess(
            render_body.index("scheduleProgressiveFollowUpIfNeeded("),
            render_body.index("if panelDisplayCandidates.isEmpty"),
        )

        follow_start = source.index("private func scheduleProgressiveFollowUpIfNeeded")
        follow_end = source.index("private func showLocalRimeFallbackCandidates")
        follow_body = source[follow_start:follow_end]
        self.assertIn("progressive.shouldFollowUp", follow_body)
        self.assertIn("let retryAfterMs = max(80, min(1500, progressive.retryAfterMs))", follow_body)
        self.assertIn("originalRequest.requestSeq == self.requestSeq", follow_body)
        self.assertIn("try self.bridge.rimeSuggest(request: originalRequest)", follow_body)
        self.assertIn("originalRequest.committedContext", follow_body)
        self.assertIn("self.renderSidecarResponse(", follow_body)

        cancel_start = source.index("private func cancelPendingRefresh")
        cancel_body = source[cancel_start:]
        self.assertIn("pendingProgressiveFollowUp?.cancel()", cancel_body)

    def test_native_frontend_forces_side_candidates_for_post_commit_and_contextual_prefix(self) -> None:
        source = _controller_source()

        refresh_start = source.index("private func scheduleSuggestionRefresh")
        refresh_end = source.index("private func schedulePostCommitPrediction")
        refresh_body = source[refresh_start:refresh_end]
        self.assertIn("forceSideCandidates: !contextSnapshot.trimmingCharacters", refresh_body)

        post_start = source.index("private func schedulePostCommitPrediction")
        post_end = source.index("private func renderSidecarResponse")
        post_body = source[post_start:post_end]
        self.assertIn("forceSideCandidates: true", post_body)

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


def _dictionary_provider_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "macos" / "RagImeMac" / "Sources" / "RimeDictionaryCandidateProvider.swift").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
