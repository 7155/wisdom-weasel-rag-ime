from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BuildPatchedSquirrelScriptTests(unittest.TestCase):
    def test_squirrel_patch_contains_side_first_mixed_layout_hooks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_text = (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")

        self.assertIn("fallback: 5, range: 0...10", patch_text)
        self.assertIn("fallback: 900, range: 30...3000", patch_text)
        self.assertIn("fallback: 1200, range: 30...3000", patch_text)
        self.assertIn("sidecar_url missing; passive input path does not run CLI fallback", patch_text)
        self.assertIn("passive CLI fallback disabled", patch_text)
        self.assertIn("case circuitOpen(Int)", patch_text)
        self.assertNotIn("RAG IME sidecar HTTP request failed, falling back to CLI", patch_text)
        self.assertIn("let displayLayout: String?", patch_text)
        self.assertIn("let displayLane: String?", patch_text)
        self.assertIn("let badge: String?", patch_text)
        self.assertIn("let sourceBadge: String?", patch_text)
        self.assertIn("let colorToken: String?", patch_text)
        self.assertIn("let sourceStability: String?", patch_text)
        self.assertIn("let candidateOrdinal: Int?", patch_text)
        self.assertIn("let candidateStableId: String?", patch_text)
        self.assertIn("let snapshotId: String?", patch_text)
        self.assertIn("let hardContextAnchor: String?", patch_text)
        self.assertIn("let queryAnchor: String?", patch_text)
        self.assertIn("let displayAnchor: String?", patch_text)
        self.assertIn("let keyPolicy: RagImeKeyPolicyPayload?", patch_text)
        self.assertIn("let predictionTraceEvents: [RagImePredictionTraceEvent]?", patch_text)
        self.assertIn("struct RagImeKeyPolicyPayload: Codable", patch_text)
        self.assertIn("struct RagImePredictionTraceEvent: Codable", patch_text)
        self.assertIn("struct RagImeRefreshDecision: Codable", patch_text)
        self.assertIn("struct RagImeShowDecision: Codable", patch_text)
        self.assertIn("func candidateSeparator(before index: Int) -> String", patch_text)
        self.assertIn('currentLayout == "inline", previousLayout == "inline"', patch_text)
        self.assertIn("private var ragImePanelUsesDisplayCandidates: Bool = false", patch_text)
        self.assertIn("private var ragImeDisplaySessionFingerprint: String = \"\"", patch_text)
        self.assertIn("private var ragImeDisplaySnapshotId: String = \"\"", patch_text)
        self.assertIn("private var ragImeDisplayNumberKeyPolicy: String = \"\"", patch_text)
        self.assertIn("private var ragImeDisplayTabPolicy: String = \"\"", patch_text)
        self.assertIn("private var ragImeDisplayOptionNumberPolicy: String = \"\"", patch_text)
        self.assertIn("private var ragImeDisplayExpiresAt: Date?", patch_text)
        self.assertIn("func ragImePanelForcesHorizontalLayout() -> Bool", patch_text)
        self.assertIn("func ragImePanelUsesSideDisplay() -> Bool", patch_text)
        self.assertIn("func ragImeDisplaySourceType(at index: Int) -> String?", patch_text)
        self.assertIn("private var ragImeInputGeneration: Int = 0", patch_text)
        self.assertIn("private let ragImeActiveResponseApplyWindowMs: Int = 9000", patch_text)
        self.assertIn("private let ragImePostCommitResponseApplyWindowMs: Int = 12000", patch_text)
        self.assertIn("var ragImePanelLinear: Bool", patch_text)
        self.assertIn("view.textView.setLayoutOrientation(ragImePanelVertical ? .vertical : .horizontal)", patch_text)
        self.assertIn("var candidateSeparators = [String]()", patch_text)
        self.assertIn('traceRagImeFrontendEvent("panel_text_layout"', patch_text)
        self.assertIn("traceRagImePanelTextLayout(", patch_text)
        self.assertIn('case "model":', patch_text)
        self.assertIn('return "模"', patch_text)
        self.assertIn('return "查"', patch_text)
        self.assertIn('return "忆"', patch_text)
        self.assertIn('return "词"', patch_text)
        self.assertIn('return "input"', patch_text)
        self.assertIn('case "action":', patch_text)
        self.assertIn('return "生成"', patch_text)
        self.assertIn('case "model", "rag", "memory", "status", "action":', patch_text)
        self.assertIn("return .systemBlue", patch_text)
        self.assertIn("let maxTextHeight = ragImePanelVertical", patch_text)
        self.assertIn("let maxWidth = if ragImePanelVertical", patch_text)
        self.assertIn("var ragImePanelUsesSideDisplay: Bool", patch_text)
        self.assertIn("let readableCap: CGFloat = min(screenRect.width - 48, 560)", patch_text)
        self.assertIn("if theme.translucency && !ragImePanelUsesSideDisplay", patch_text)
        self.assertIn("alphaValue = ragImePanelUsesSideDisplay ? 1 : theme.alpha", patch_text)
        self.assertIn("return NSView()", patch_text)
        self.assertIn("RAG_IME_ASSISTANT_OVERLAY_AUTO_PENDING", patch_text)
        self.assertIn("post_commit_pending_overlay_disabled", patch_text)
        self.assertIn("assistant_overlay_local_placeholder_suppressed", patch_text)
        self.assertIn("打开 RAG-IME 控制中心...", patch_text)
        self.assertIn('urlForApplication(withBundleIdentifier: "com.rag-ime.control")', patch_text)
        self.assertIn('performRagImeControlAction("stop_ai")', patch_text)
        self.assertIn('performRagImeControlAction("restart_sidecar")', patch_text)
        overlay_sources = root / "squirrel-patches" / "sources"
        controller_text = (overlay_sources / "RagImeAssistantPanelController.swift").read_text(encoding="utf-8")
        card_text = (overlay_sources / "RagImeSuggestionCardView.swift").read_text(encoding="utf-8")
        row_text = (overlay_sources / "RagImeSuggestionRowView.swift").read_text(encoding="utf-8")
        state_text = (overlay_sources / "RagImeAssistantSurfaceState.swift").read_text(encoding="utf-8")
        panel_text = (overlay_sources / "RagImeNonActivatingPanel.swift").read_text(encoding="utf-8")
        combined_overlay_text = "\n".join([controller_text, card_text, row_text, state_text, panel_text])
        self.assertNotIn("panel.appearance = NSAppearance(named: .aqua)", combined_overlay_text)
        self.assertNotIn("calibratedWhite", combined_overlay_text)
        self.assertNotIn("NSStackView", combined_overlay_text)
        self.assertNotIn("fittingSize", combined_overlay_text)
        self.assertNotIn("arrangedSubviews", combined_overlay_text)
        self.assertIn("case compactPrediction", state_text)
        self.assertIn("case explicitGenerating", state_text)
        self.assertIn("override var canBecomeKey: Bool { false }", panel_text)
        self.assertIn("override var canBecomeMain: Bool { false }", panel_text)
        self.assertIn("panel.ignoresMouseEvents = false", controller_text)
        self.assertIn("passive_anchor_missing", controller_text)
        self.assertIn("same_snapshot_stable_ids", controller_text)
        self.assertIn("assistant_panel_created", controller_text)
        self.assertIn("assistant_panel_update_coalesced", controller_text)
        self.assertIn("RagImeSuggestionCardView.minimumPredictionWidth", controller_text)
        self.assertIn("RagImeSuggestionCardView.maximumPredictionWidth", controller_text)
        self.assertIn("static let minimumPredictionWidth: CGFloat = 304", card_text)
        self.assertIn("static let preferredPredictionWidth: CGFloat = 360", card_text)
        self.assertIn("static let maximumPredictionWidth: CGFloat = 420", card_text)
        self.assertIn("static let rowHeight: CGFloat = 36", card_text)
        self.assertIn("static let actionHeight: CGFloat = 31", card_text)
        self.assertIn("let visibleCount = min(3, candidates.count)", card_text)
        self.assertIn('let shortcut = index == 0 ? "Tab   ⌥1" : "⌥\\(index + 1)"', card_text)
        self.assertIn("DS · 深度补全", card_text)
        self.assertIn("predictionHeight(candidateCount: realCandidates.count, hasAction: hasAction)", controller_text)
        self.assertIn("rowHeight * CGFloat(max(0, min(3, candidateCount))) + (hasAction ? actionHeight : 0)", card_text)
        self.assertIn("same_snapshot_stable_ids", controller_text)
        self.assertNotIn("state == .compactPrediction ? min(1, candidates.count)", card_text)
        self.assertNotIn("min(520, max(280, measuredWidth))", controller_text)
        self.assertIn("case .insert:", controller_text)
        self.assertIn("case .replace:", controller_text)
        self.assertIn("canReplaceSelection(in: payload)", controller_text)
        self.assertIn('#selector(rememberResult)', controller_text)
        self.assertIn('#selector(suppressResult)', controller_text)
        self.assertNotIn('for title in ["记住", "不再推荐"]', controller_text)
        self.assertIn("replaceButton.isHidden = !canReplaceSelection", card_text)
        self.assertIn("DispatchQueue.main.async", controller_text)
        self.assertIn("final class RagImeSuggestionCardView: NSVisualEffectView", card_text)
        self.assertIn("material = .popover", card_text)
        self.assertIn("layer?.backgroundColor = NSColor.clear.cgColor", card_text)
        self.assertIn("NSColor.separatorColor", card_text)
        self.assertIn("accessibilityDisplayShouldReduceMotion", controller_text)
        self.assertIn("accessibilityDisplayShouldIncreaseContrast", card_text)
        self.assertIn("Timer(timeInterval: 0.5, repeats: true)", controller_text)
        self.assertIn("RunLoop.main.add(timer, forMode: .common)", controller_text)
        self.assertIn("assistant_generating_animation_started", controller_text)
        self.assertIn("assistant_generating_animation_stopped", controller_text)
        self.assertIn("func updateGeneratingFrame", card_text)
        self.assertIn('["◜", "◝", "◞", "◟"]', card_text)
        self.assertIn("RagImeSuggestionRowView", row_text)
        self.assertIn('return "DS"', row_text)
        self.assertIn('case "rag": return .systemTeal', row_text)
        self.assertIn('case "memory": return .systemOrange', row_text)
        self.assertIn('return "sparkles"', row_text)
        self.assertIn('return "doc.text.magnifyingglass"', row_text)
        self.assertIn('return "clock.arrow.circlepath"', row_text)
        self.assertIn("private let sourceBar = NSView()", row_text)
        self.assertIn("private let shortcutPlate = NSView()", row_text)
        self.assertIn("sourceLabel.font = .systemFont", row_text)
        self.assertIn("[actionSeparator, deepSeekButton, deepSeekShortcutPlate, deepSeekShortcutLabel]", card_text)
        self.assertIn("ragImePrivacyDisposition == \"allowed\"", patch_text)
        self.assertIn("let privacyDisposition: String", patch_text)
        self.assertIn("request.privacyDisposition == \"allowed\"", patch_text)
        self.assertIn('"--privacy-disposition"', patch_text)
        self.assertNotIn("badgeView", row_text)
        self.assertIn("func animateContentIn", row_text)
        self.assertIn("func animateAccepted", row_text)
        self.assertIn("setGeneratingPulse", card_text)
        self.assertIn("assistant_panel_present_animation_started", controller_text)
        self.assertIn("assistant_candidate_content_transition_started", controller_text)
        self.assertIn("assistant_candidate_group_exit_animation_started", controller_text)
        self.assertIn("assistant_context_diagnostics_rendered", controller_text)
        self.assertIn("private static weak var activeOwner", controller_text)
        self.assertIn("claimSingletonOwnership", controller_text)
        self.assertIn("scheduleTTL(for: payload)", controller_text)
        self.assertIn("assistant_overlay_singleton_replaced", controller_text)
        self.assertIn("assistant_overlay_ttl_expired", controller_text)
        self.assertIn('dismiss(reason: "ttl_expired")', controller_text)
        self.assertIn('"ttlSource": requestedMs > 0 ? "payload" : "fail_safe"', controller_text)
        self.assertIn("renderedContentSignature", controller_text)
        self.assertIn("scheduleTTL(for: payload)", controller_text)
        self.assertIn("onDismiss: ((String) -> Void)?", controller_text)
        self.assertIn("layoutResultText()", card_text)
        self.assertIn("applyConfiguration(candidateFontSize:", card_text)
        self.assertIn('payload.overlayConfigBool("fadeAnimation")', controller_text)
        self.assertIn('payload.overlayConfigNumber("maxWidth")', controller_text)
        self.assertIn('payload.overlayConfigNumber("expiresAfterMs")', controller_text)
        self.assertIn("let overlayConfig: [String: RagImeJSONValue]?", patch_text)
        self.assertIn('payload.overlayConfigKeyPolicy("tab")', patch_text)
        self.assertIn("private var ragImeActiveRagGeneration: Int = 0", patch_text)
        self.assertIn("private var ragImeActiveRagPollWorkItem: DispatchWorkItem?", patch_text)
        self.assertIn("func beginRagImeActiveRagSession", patch_text)
        self.assertIn("func cancelRagImeActiveRagSession", patch_text)
        self.assertIn("func ragImeActiveRagSessionIsLive", patch_text)
        self.assertIn('cancelRagImeActiveRagSession(reason: "sensitive_field")', patch_text)
        self.assertIn("cancelRagImeActiveRagSession(reason: reason)", patch_text)
        self.assertIn('"start_callback_generation_changed"', patch_text)
        self.assertIn('"status_callback_generation_changed"', patch_text)
        self.assertIn("request.frontAppBundleId == currentApp", patch_text)
        self.assertIn("request.frontendRevision == ragImeFrontendRevision", patch_text)
        self.assertIn("liveInputSourceId == ragImeActiveRagInputSourceId", patch_text)
        self.assertIn("ragImeActiveRagPollWorkItem?.cancel()", patch_text)
        self.assertIn("generation: generation", patch_text)
        self.assertIn("func requireRagImeActiveRagEnabled", patch_text)
        self.assertIn('userDefaultsKey: "RagImeActiveRagEnabled"', patch_text)
        self.assertIn('"reason": "active_rag_disabled"', patch_text)
        self.assertIn('guard requireRagImeActiveRagEnabled(trigger: "shortcut") else { return false }', patch_text)
        self.assertIn('guard requireRagImeActiveRagEnabled(trigger: "selection") else { return false }', patch_text)
        self.assertIn('guard requireRagImeActiveRagEnabled(trigger: "context") else { return false }', patch_text)
        self.assertIn("reduceMotion: Bool", row_text)
        self.assertIn('"contextChars": .number(Double(request.contextChars))', patch_text)
        self.assertIn('"evidenceCount": .number(Double(response.evidenceCount))', patch_text)
        self.assertIn('"traceIncludesText": false', patch_text)
        self.assertNotIn('"selectedTextPreview": request.selectedTextPreview', patch_text)
        self.assertIn('let postCommitIdleMs: Int', patch_text)
        self.assertIn('"rag_ime/post_commit_idle_ms", fallback: 420, range: 40...1000', patch_text)
        self.assertIn('request.foregroundText.source == "ime_commit_ledger"', patch_text)
        self.assertIn('request.foregroundText.commitTextMatched', patch_text)
        self.assertIn('["text_input_client", "accessibility", "ime_commit_ledger"]', patch_text)
        self.assertIn('if reason == "front_app_changed"', patch_text)
        self.assertIn("let idleMs = acceptedCandidate ? 0 : sidecarClient.postCommitIdleMs", patch_text)
        self.assertIn("IsSecureEventInputEnabled()", patch_text)
        self.assertIn('reason: "ax_secure_text_field"', patch_text)
        self.assertIn('reason: "sensitive_field_metadata"', patch_text)
        self.assertIn('reason: "privacy_unknown_app_bundle_missing"', patch_text)
        self.assertIn('reason: "privacy_unknown_ax_not_trusted"', patch_text)
        self.assertIn('reason: "privacy_unknown_focused_element_missing"', patch_text)
        self.assertIn('reason: "privacy_unknown_metadata_read_failed"', patch_text)
        self.assertIn('reason: "privacy_unknown_text_field_metadata_missing"', patch_text)
        self.assertIn('reason: "sensitive_application_bundle"', patch_text)
        self.assertIn('"com.apple.passwords"', patch_text)
        self.assertIn('"org.torproject.torbrowser"', patch_text)
        self.assertIn('"RAG_IME_SENSITIVE_APP_BUNDLE_IDS"', patch_text)
        self.assertIn('"RAG_IME_SENSITIVE_APP_BUNDLE_TOKENS"', patch_text)
        self.assertIn('"RagImeSensitiveAppBundleIds"', patch_text)
        self.assertIn('"RagImeSensitiveAppBundleTokens"', patch_text)
        self.assertIn('"password", "passcode", "one-time"', patch_text)
        self.assertIn('"密码", "验证码", "账号"', patch_text)
        self.assertIn("func enforceRagImeSensitiveFieldGuard() -> Bool", patch_text)
        self.assertIn("func clearRagImeSensitiveRuntimeState()", patch_text)
        self.assertIn("ragImeCommittedContext = \"\"", patch_text)
        self.assertIn("ragImeCommitBurstTexts = []", patch_text)
        self.assertIn("ragImeLastForegroundTextSnapshot = nil", patch_text)
        self.assertIn('invalidateRagImeForegroundTransaction(reason: "deactivate_server")', patch_text)
        self.assertIn('dismiss(reason: "input_controller_deinit")', patch_text)
        self.assertIn("guard !ragImeSensitiveFieldActive else { return }", patch_text)
        self.assertNotIn("let includeText = !sensitiveField", patch_text)
        self.assertIn("private let ragImeDisplayHoldoverDuration: TimeInterval = 2.6", patch_text)
        self.assertIn("private let ragImePostCommitDisplayHoldoverDuration: TimeInterval = 8.0", patch_text)
        self.assertIn("func canUseRagImeDisplayHoldover(", patch_text)
        self.assertIn("func canUseRagImePostCommitDisplayHoldover(", patch_text)
        self.assertIn("func canSelectCurrentRagImeDisplayCandidates(", patch_text)
        self.assertIn("func canSelectRagImeDisplayCandidate(_ candidate: RagImeDisplayCandidate) -> Bool", patch_text)
        self.assertIn("func ragImeDisplayCandidateSessionFingerprint(_ candidate: RagImeDisplayCandidate) -> String", patch_text)
        self.assertIn("func ragImeJSONValueString(_ value: RagImeJSONValue?) -> String?", patch_text)
        self.assertIn("func ragImeDisplayTraceTransactionFields() -> [String: Any]", patch_text)
        self.assertIn('if event == "panel_display_candidates"', patch_text)
        self.assertIn("postCommitHoldover", patch_text)
        self.assertIn("ragImePostCommitDisplayHoldoverDuration", patch_text)
        self.assertIn("let predictionSession: RagImePredictionSessionPayload?", patch_text)
        self.assertIn("let progressive: RagImeProgressivePayload?", patch_text)
        self.assertIn("let progressiveFollowUp: Bool", patch_text)
        self.assertIn("struct RagImePredictionSessionPayload: Codable", patch_text)
        self.assertIn("init(from decoder: Decoder) throws", patch_text)
        self.assertIn("decodeIfPresent(String.self, forKey: .pinyinPrefix) ?? \"\"", patch_text)
        self.assertIn("decodeIfPresent(Bool.self, forKey: .shouldClearPredictionPanel) ?? false", patch_text)
        self.assertIn("struct RagImeProgressivePayload: Codable", patch_text)
        self.assertIn("let sessionFingerprint: String?", patch_text)
        self.assertIn("let expiresAfterMs: Int?", patch_text)
        self.assertIn("let stablePanelAction: String?", patch_text)
        self.assertIn("let stablePanelReason: String?", patch_text)
        self.assertIn("guard !ragImeDisplayCandidates.isEmpty else { return false }", patch_text)
        self.assertNotIn('ragImeDisplayQueryBasis == "committedContext"', patch_text)
        self.assertIn("let forceSideCandidates = rawInput.isEmpty && preedit.isEmpty", patch_text)
        self.assertIn("let hasPostCommitCaptureSeed = commitBurstReady", patch_text)
        self.assertIn("guard commitBurstReady || acceptedCandidateContinuation", patch_text)
        self.assertIn('"reason": "empty_commit"', patch_text)
        self.assertIn("forceSideCandidates: forceSideCandidates", patch_text)
        self.assertIn("let frontendBuild: String", patch_text)
        self.assertIn("let schemaVersion: String", patch_text)
        self.assertIn("let predictionFirstMerge: Bool", patch_text)
        self.assertIn('frontendBuild: "rag-ime.foreground-trace.v2"', patch_text)
        self.assertIn('schemaVersion: "rag-ime.squirrel-frontend-trace.v1"', patch_text)
        self.assertIn("predictionFirstMerge: true", patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_request_scheduled"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_empty_response_cleared"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_clear_response_applied"', patch_text)
        self.assertIn("response.predictionSession?.shouldClearPredictionPanel == true", patch_text)
        self.assertIn("let shouldClearEmptyResponse = response.predictionSession?.shouldClearPredictionPanel == true", patch_text)
        self.assertNotIn("if overlayVisible {", patch_text)
        self.assertIn("scheduleRagImeProgressiveFollowUpIfNeeded(\n+        response: response", patch_text)
        self.assertIn("let shouldKeepFingerprintForFollowUp = response.progressive?.enabled == true", patch_text)
        self.assertIn("keepLastFingerprint: shouldKeepFingerprintForFollowUp", patch_text)
        self.assertIn('"keptExistingPanel": !shouldClearEmptyResponse', patch_text)
        self.assertIn("displayCandidatesToApply.allSatisfy({ ragImeDisplayCandidateSessionFingerprint($0) == responseSessionFingerprint })", patch_text)
        self.assertIn("clearRagImeDisplayCandidates()", patch_text)
        self.assertIn("rag-ime.foreground-trace.v2", patch_text)
        self.assertIn("struct RagImeForegroundTextSnapshot: Codable", patch_text)
        self.assertIn("captureForegroundTextForSidecar", patch_text)
        self.assertIn("RagImeSelectedTextProvider.swift in Sources", patch_text)
        self.assertIn("private let ragImeSelectedTextProvider = RagImeSelectedTextProvider()", patch_text)
        self.assertIn("kAXSelectedTextRangeAttribute", patch_text)
        self.assertIn("kAXStringForRangeParameterizedAttribute", patch_text)
        self.assertIn("kAXValueAttribute", patch_text)
        self.assertIn('source: "accessibility"', patch_text)
        self.assertIn("let wholeValueHash: String", patch_text)
        self.assertIn("let wholeValueChars: Int", patch_text)
        self.assertIn("let warnings: [String]", patch_text)
        self.assertIn("foregroundText: foregroundText", patch_text)
        self.assertIn("foregroundText: request.foregroundText", patch_text)
        self.assertIn('let textInputClientContext = (!rawInput.isEmpty || !preedit.isEmpty)', patch_text)
        self.assertIn('"text_input_client"', patch_text)
        self.assertIn('"ime_commit_ledger"', patch_text)
        self.assertIn('"text_input_client_context"', patch_text)
        self.assertNotIn("allowAccessibility: false", patch_text)
        self.assertIn("RagImeForegroundContextResolver", patch_text)
        self.assertIn("foreground_context_capture_scheduled", patch_text)
        self.assertIn("foreground_context_capture_resolved", patch_text)
        self.assertIn("foreground_context_capture_failed", patch_text)
        self.assertIn("capturedAtMs", patch_text)
        self.assertIn("captureFailureReason", patch_text)
        self.assertIn("assistant_overlay_candidate_visible", patch_text)
        self.assertIn("side_candidate_feedback_recorded", patch_text)
        self.assertIn('"foregroundTextSource": foregroundText.source', patch_text)
        self.assertIn('"foregroundTextSource": foregroundText.source', patch_text)
        self.assertIn("selectedTextHash: \"\"", patch_text)
        self.assertIn("selectedTextPreview: \"\"", patch_text)
        self.assertIn("canReplaceSelection: false", patch_text)
        self.assertIn("guard !displayCandidatesToApply.isEmpty else {", patch_text)
        self.assertIn("committedContext: ragImeCommittedContext", patch_text)
        self.assertIn("removeLastRagImeCommittedContextCharacterIfNoComposition()", patch_text)
        self.assertIn("func removeLastRagImeCommittedContextCharacter()", patch_text)
        self.assertIn("func boundedRagImeCommittedContext(_ text: String) -> String", patch_text)
        self.assertIn("func syncRagImeCommittedContextFromClient(excludingMarkedText markedText: String = \"\") -> String", patch_text)
        self.assertIn("client.attributedSubstring(from: range)", patch_text)
        self.assertIn("func invalidateRagImeDisplayForInputChange(reason: String, keyCode: UInt16)", patch_text)
        self.assertIn("committed_context_resynced_after_delete", patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_response_dropped_stale"', patch_text)
        self.assertIn('"input_generation_changed"', patch_text)
        self.assertIn('"response_too_late_for_foreground"', patch_text)
        self.assertIn("func ragImeResponseContainsRimeFallback(_ response: RagImeSidecarResponse) -> Bool", patch_text)
        self.assertIn("func ragImeDisplayCandidatesContainComposableSideCandidate() -> Bool", patch_text)
        self.assertIn('selectionScope == "mixed_prediction_first"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_rime_candidate_change_allowed"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_rime_fallback_stripped"', patch_text)
        self.assertIn('candidate.sourceType != "rime" && candidate.selectionAction != "select_rime_candidate"', patch_text)
        self.assertIn("displayCandidatesToApply = sideOnlyCandidates", patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_stale_fingerprint_allowed"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_input_generation_change_allowed"', patch_text)
        self.assertIn("let canApplySideOnlyAcrossGeneration = !responseContainsRimeFallback", patch_text)
        self.assertIn("&& currentRawInput == request.rawInput", patch_text)
        self.assertIn("&& ragImeCommittedContext == request.committedContext", patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_progressive_generation_change_allowed"', patch_text)
        self.assertIn('dropRagImeSidecarResponse("rime_candidates_changed"', patch_text)
        self.assertIn('dropRagImeSidecarResponse("raw_input_changed"', patch_text)
        self.assertIn("currentRagImeContextMatches(request, requireRimeFallback: responseContainsRimeFallback)", patch_text)
        self.assertIn("private var ragImePendingRequestFingerprint: String = \"\"", patch_text)
        self.assertIn("private var ragImeDisplayExpiryWorkItem: DispatchWorkItem?", patch_text)
        self.assertIn("private var ragImePendingContinuationCandidate: RagImeDisplayCandidate?", patch_text)
        self.assertIn("private var ragImePendingContinuationCommittedText: String = \"\"", patch_text)
        self.assertIn("private var ragImePendingContinuationPreviousContextHash: String = \"\"", patch_text)
        self.assertIn("fingerprint == ragImeLastRequestFingerprint || fingerprint == ragImePendingRequestFingerprint", patch_text)
        self.assertIn("guard response.requestSeq == request.requestSeq else {", patch_text)
        self.assertIn("guard response.committedContext == request.committedContext else {", patch_text)
        self.assertIn("guard ragImeCommittedContext == request.committedContext else {", patch_text)
        self.assertIn("func completeRagImeSidecarRequest(fingerprint: String, keepLastFingerprint: Bool)", patch_text)
        self.assertIn("func scheduleRagImeDisplayExpiry()", patch_text)
        self.assertIn("func scheduleRagImeProgressiveFollowUpIfNeeded(", patch_text)
        self.assertIn("func ragImeTraceProgressive(_ progressive: RagImeProgressivePayload?) -> [String: Any]", patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_progressive_followup_scheduled"', patch_text)
        self.assertIn("ragImeLastRequestFingerprint = fingerprint\n+    ragImePendingRequestFingerprint = fingerprint", patch_text)
        self.assertIn("text_input_client_synchronous_fallback_after_", patch_text)
        self.assertIn('traceRagImeFrontendEvent("foreground_context_captured_after_commit"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("sidecar_progressive_followup_sent"', patch_text)
        self.assertIn("progressiveFollowUp: true", patch_text)
        self.assertIn('"progressive": ragImeTraceProgressive(response.progressive)', patch_text)
        self.assertIn('"panelUsesDisplayCandidates": ragImePanelUsesDisplayCandidates', patch_text)
        self.assertIn("ragImePanelUsesDisplayCandidates = !displayCandidatesToApply.isEmpty", patch_text)
        self.assertIn("func ragImeDisplayStateFingerprint() -> String", patch_text)
        self.assertIn('traceRagImeFrontendEvent("panel_expired_cleared"', patch_text)
        self.assertIn("ragImeDisplayExpiryWorkItem?.cancel()", patch_text)
        self.assertIn("rimeUpdate(clearReservedComments: false, requestSidecar: false)", patch_text)
        self.assertIn("func scheduleRagImePostCommitContinuation(committedText: String, sourceCandidate: RagImeDisplayCandidate)", patch_text)
        self.assertIn("func observeRagImePostCommitContinuationIfReady()", patch_text)
        self.assertIn('traceRagImeFrontendEvent("side_candidate_commit_pending"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("side_candidate_continuation_scheduled"', patch_text)
        self.assertIn("showRagImeAssistantOverlayPending(request: request)", patch_text)
        self.assertIn('uiMode: "post_commit_pending"', patch_text)
        self.assertIn('traceEvent: "assistant_overlay_post_commit_pending"', patch_text)
        self.assertIn('text: "DeepSeek 生成"', patch_text)
        self.assertIn("ragImePendingContinuationCandidate = sourceCandidate", patch_text)
        self.assertIn("guard committedContextHash != ragImePendingContinuationPreviousContextHash || committedContext.contains(committedText) else {", patch_text)
        self.assertIn("scheduleRagImePostCommitContinuation(committedText: insertText, sourceCandidate: candidate)", patch_text)
        self.assertIn('commitTextPreview: committedText', patch_text)
        self.assertIn("immediate: Bool = false", patch_text)
        self.assertIn("let delay = TimeInterval(immediate ? 16 : sidecarClient.debounceMs) / 1000", patch_text)
        self.assertIn("immediate: true", patch_text)
        self.assertIn("let frontendTrace: Bool", patch_text)
        self.assertIn("rag_ime/frontend_trace", patch_text)
        self.assertIn("func traceRagImeFrontendEvent(_ event: String, fields: [String: Any])", patch_text)
        self.assertIn("guard ragImeSidecarClient?.frontendTrace == true else { return }", patch_text)
        self.assertIn("ragImePrepareFrontendTraceLog", patch_text)
        self.assertIn(".posixPermissions: 0o600", patch_text)
        self.assertIn('appendingPathExtension("1")', patch_text)
        self.assertIn("let contextAnchor = ragImeStableTextHash(context)", patch_text)
        self.assertIn("queryAnchor: contextAnchor", patch_text)
        self.assertIn("displayAnchor: contextAnchor", patch_text)
        self.assertIn('traceRagImeFrontendEvent("panel_display_candidates"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("side_candidate_commit"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("candidate_snapshot_selection_accepted"', patch_text)
        self.assertIn('traceRagImeFrontendEvent("candidate_snapshot_selection_rejected_stale"', patch_text)
        self.assertIn("shownCandidates: ragImeDisplayCandidates", patch_text)
        self.assertIn("let shownCandidates: [RagImeDisplayCandidate]", patch_text)
        self.assertIn("traceRagImePredictionEvents(response.predictionTraceEvents)", patch_text)
        self.assertIn("func traceRagImePredictionEvents(_ events: [RagImePredictionTraceEvent]?)", patch_text)
        self.assertIn("func ragImeJSONValueDictionary(_ dictionary: [String: RagImeJSONValue]) -> [String: Any]", patch_text)
        self.assertIn("func ragImeJSONValueToAny(_ value: RagImeJSONValue) -> Any", patch_text)
        self.assertNotIn('ragImeDisplayNumberKeyPolicy == "select_visible_candidate"', patch_text)
        self.assertIn('ragImeDisplayNumberKeyPolicy = response.keyPolicy?.numberKeys ?? ""', patch_text)
        self.assertIn('ragImeDisplayTabPolicy = response.keyPolicy?.tab ?? ""', patch_text)
        self.assertIn('ragImeDisplayOptionNumberPolicy = response.keyPolicy?.optionNumber ?? ""', patch_text)
        self.assertIn('ragImeOverlayTabPolicy == "accept_top_prediction"', patch_text)
        self.assertIn('selectRagImeOverlayCandidate(atOrdinal: 1, route: "tab", key: "tab")', patch_text)
        self.assertIn('ragImeOverlayOptionNumberPolicy == "select_prediction_by_ordinal"', patch_text)
        self.assertIn('selectRagImeOverlayCandidate(forKey: String(char), route: "option_number")', patch_text)
        self.assertIn("RagImeAssistantPanelController.swift in Sources", patch_text)
        self.assertIn("func applyRagImeAssistantOverlay(", patch_text)
        self.assertIn("func commitRagImeAssistantCandidate(", patch_text)
        self.assertIn("replaceSelection: Bool = false", patch_text)
        self.assertIn("func replaceRagImeAssistantSelection(with text: String", patch_text)
        self.assertIn('client.insertText(text, replacementRange: selectedRange)', patch_text)
        self.assertIn('endpoint("assistant-candidate-action", base: sidecarURL)', patch_text)
        self.assertIn('recordRagImeAssistantCandidateAction("remember")', patch_text)
        self.assertIn('recordRagImeAssistantCandidateAction("suppress")', patch_text)
        self.assertIn('replacingOccurrences(of: "sha256:", with: "")', patch_text)
        self.assertIn("assistant_overlay_candidate_accepted", patch_text)
        self.assertIn("response.candidatePanel?.candidates", patch_text)
        self.assertIn("func selectRagImePredictionCandidate(forKey key: String, route: String) -> Bool", patch_text)
        self.assertIn("func selectRagImePredictionCandidate(atOrdinal ordinal: Int, route: String, key: String) -> Bool", patch_text)
        self.assertIn('traceRagImeFrontendEvent(eventName, fields: [', patch_text)
        self.assertIn('let eventName = route == "tab" ? "tab_key_route" : "option_number_route"', patch_text)
        self.assertIn('candidate.sourceType != "raw_english" && candidate.sourceType != "rime"', patch_text)
        self.assertIn('"candidateOrdinal": candidate.candidateOrdinal ?? 0', patch_text)
        self.assertIn('"candidateStableId": candidate.candidateStableId ?? ""', patch_text)
        self.assertIn('"snapshotId": candidate.snapshotId ?? ""', patch_text)
        self.assertIn('"sourceStability": candidate.sourceStability ?? ""', patch_text)
        self.assertIn("func ragImeCandidateSourceBadgesEnabled() -> Bool", patch_text)
        self.assertIn("func ragImeCandidateSourceColorsEnabled() -> Bool", patch_text)
        self.assertIn("func ragImeCandidateDiagnosticsEnabled() -> Bool", patch_text)
        self.assertIn("func ragImeDisplayBadge(for candidate: RagImeDisplayCandidate) -> String", patch_text)
        self.assertIn("func ragImeDisplayText(for candidate: RagImeDisplayCandidate) -> String", patch_text)
        self.assertIn("func ragImeStripSourceSuffix(_ text: String) -> String", patch_text)
        self.assertIn("let visibleCandidates = ragImeDisplayCandidates.filter", patch_text)
        self.assertIn("visibleCandidates.map { ragImeDisplayText(for: $0) }", patch_text)
        self.assertIn("let text = candidate.text.trimmingCharacters(in: .whitespacesAndNewlines)", patch_text)
        self.assertIn("let base = ragImeStripSourceSuffix(text.isEmpty ? candidate.insertText : text)", patch_text)
        self.assertIn('case "model", "rag", "memory", "status", "action":', patch_text)
        self.assertIn('return "[\\(badge)] \\(base)"', patch_text)
        self.assertIn("let insertText = ragImeStripSourceSuffix(candidate.insertText.isEmpty ? candidate.text : candidate.insertText)", patch_text)
        self.assertIn("if !stripped.isEmpty", patch_text)
        self.assertIn("func ragImeDisplayComment(for candidate: RagImeDisplayCandidate) -> String", patch_text)
        self.assertIn(
            "+  func ragImeDisplayComment(for candidate: RagImeDisplayCandidate) -> String {\n"
            '+    return ""\n'
            "   }",
            patch_text,
        )
        self.assertNotIn('return "\\(badge)·\\(candidate.comment)"', patch_text)
        self.assertNotIn("ragImeDisplayCandidates.map { $0.text }", patch_text)
        self.assertIn("RAG_IME_CANDIDATE_SOURCE_BADGES", patch_text)
        self.assertIn("RAG_IME_CANDIDATE_SOURCE_COLORS", patch_text)
        self.assertIn("RAG_IME_CANDIDATE_DIAGNOSTICS", patch_text)
        self.assertIn("func ragImeSourceColor(_ sourceType: String) -> NSColor?", patch_text)
        self.assertIn("return .systemBlue", patch_text)
        self.assertIn("return .systemTeal", patch_text)
        self.assertIn("return .systemPurple", patch_text)
        self.assertIn("return .systemOrange", patch_text)
        self.assertIn("return .systemGray", patch_text)
        build_script = (root / "scripts" / "build_patched_squirrel.sh").read_text(encoding="utf-8")
        self.assertIn('"displayTextPrefersCleanText": True', build_script)
        self.assertNotIn('"displayTextUsesInsertText": True', build_script)
        self.assertIn(
            "+    committedContext: String,\n"
            "+    foregroundText: RagImeForegroundTextSnapshot,\n"
            "+    page: Int,\n"
            "+    highlighted: Int,\n"
            "+    candidates: [RagImeRimeCandidatePayload]\n"
            "+  ) -> String {\n"
            "+    return [\n"
            "+      rawInput,\n"
            "+      preedit,\n"
            "+      commitTextPreview,\n"
            "+      committedContext,",
            patch_text,
        )
        self.assertIn("+      ragImeStableTextHash(foregroundText.surroundingBefore),", patch_text)
        self.assertIn("+      ragImeStableTextHash(foregroundText.surroundingAfter),", patch_text)
        self.assertIn("+      foregroundText.wholeValueHash,", patch_text)
        self.assertIn(
            "+  func selectRagImeSideCandidate(forKey key: String) -> Bool {\n"
            "+    guard ragImePanelUsesDisplayCandidates else {\n"
            "+      return false\n"
            "+    }\n"
            "+    guard canSelectCurrentRagImeDisplayCandidates() else {\n"
            "+      traceRagImeFrontendEvent(\"stale_candidate_selection_rejected\", fields: [",
            patch_text,
        )
        self.assertIn("+    guard let index = ragImeDisplayCandidates.firstIndex(where: { ragImeSelectionKey(for: $0) == key }) else {", patch_text)
        self.assertIn('traceRagImeFrontendEvent("number_key_route"', patch_text)
        self.assertIn('guard ragImeDisplayCandidates[index].sourceType == "rime" else {', patch_text)
        self.assertEqual(patch_text.count("selectRagImeSideCandidate("), 1)
        self.assertIn("func ragImeDisplayCandidateMatchesTransaction(_ candidate: RagImeDisplayCandidate, response: RagImeSidecarResponse) -> Bool", patch_text)
        self.assertIn("let responseSnapshotId = response.predictionSession?.snapshotId ?? response.predictionSession?.stableSnapshotId ?? \"\"", patch_text)
        self.assertIn("candidate.snapshotId != responseSnapshotId", patch_text)
        self.assertIn("candidate.snapshotId == ragImeDisplaySnapshotId", patch_text)
        self.assertIn("ragImeDisplayCandidates[ordinal - 1].candidateStableId == candidate.candidateStableId", patch_text)
        self.assertIn("let nowMs = Int(Date().timeIntervalSince1970 * 1000)", patch_text)
        self.assertIn("guard nowMs <= expiresAtMs else { return false }", patch_text)
        self.assertIn("func ragImeSanitizedTraceValue(_ value: Any, key: String, includeText: Bool) -> Any", patch_text)
        self.assertIn('ProcessInfo.processInfo.environment["RAG_IME_TRACE_INCLUDE_TEXT"] == "1"', patch_text)
        self.assertIn("guard canSelectRagImeDisplayCandidate(ragImeDisplayCandidates[index]) else {", patch_text)
        self.assertIn("guard canSelectRagImeDisplayCandidate(candidate) else {", patch_text)
        self.assertIn("+    return selectCandidate(index)", patch_text)
        self.assertIn("ragImeDisplayTabPolicy = \"\"", patch_text)
        self.assertIn("ragImeDisplayOptionNumberPolicy = \"\"", patch_text)
        self.assertIn("observeRagImePostCommitContinuationIfReady()", patch_text)
        self.assertIn("showRagImePostCommitActionPlaceholder(request: request)", patch_text)
        self.assertIn("rime_composition_started", patch_text)
        self.assertIn("rime_composition_candidates_visible", patch_text)
        self.assertIn("let evidencePreview: String\n+  let confidence: Double?\n+  let suggestionId: String\n+  let memoryId: String", patch_text)
        self.assertIn("composition_ai_suppressed", patch_text)
        self.assertIn("reason\": \"rime_composition_phase", patch_text)
        self.assertIn("if forceSideCandidates {", patch_text)
        self.assertIn("assistant_overlay_post_commit_pending", patch_text)
        self.assertIn('numberKeys: "pass_through"', patch_text)
        self.assertIn("require_trace_event_field()", build_script)
        self.assertIn("assistant_overlay_active_rag_thinking", build_script)
        self.assertIn("active_rag_status_poll_scheduled", build_script)
        self.assertIn('"frontAppBundleId": currentApp', build_script)
        self.assertIn('"selectedTextChars": request.selectedTextChars', build_script)
        self.assertIn('"traceIncludesText": false', build_script)

    def test_native_rime_selection_feedback_is_local_source_only_and_sensitive_guarded(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_text = (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")
        prepare_script = (root / "scripts" / "prepare_squirrel_workspace.sh").read_text(encoding="utf-8")
        build_script = (root / "scripts" / "build_patched_squirrel.sh").read_text(encoding="utf-8")

        self.assertIn('endpoint("rime-rank-feedback", base: sidecarURL)', patch_text)
        self.assertIn('sourceType: "rime"', patch_text)
        self.assertIn('selectionSource: "patched_squirrel"', patch_text)
        self.assertIn("guard !enforceRagImeSensitiveFieldGuard() else { return }", patch_text)

        consume_start = patch_text.index("func rimeConsumeCommittedText()")
        consume_body = patch_text[consume_start : consume_start + 1800]
        self.assertLess(consume_body.index("rimeAPI.get_commit"), consume_body.index("privacyRestricted"))
        self.assertLess(
            consume_body.index("discardRagImeSensitiveNativeLearningTransaction()"),
            consume_body.index("commit(string: String(cString: text), privacyRestricted: privacyRestricted)"),
        )
        self.assertLess(
            consume_body.index("commit(string: String(cString: text), privacyRestricted: privacyRestricted)"),
            consume_body.index("rimeAPI.free_commit"),
        )
        self.assertIn("if privacyRestricted {", consume_body)
        self.assertIn("guard rimeAPI.get_status(session, &status) else { return false }", patch_text)
        self.assertIn("guard !isComposing else { return false }", patch_text)
        self.assertIn("rimeAPI.process_key(session, Int32(XK_BackSpace), 0)", patch_text)
        self.assertIn("return !backspaceHandled", patch_text)
        self.assertIn('"forwardedToClient": false', patch_text)
        self.assertIn('"traceIncludesText": false', patch_text)
        self.assertIn("func commit(string: String, privacyRestricted: Bool? = nil) -> Bool", patch_text)
        self.assertIn("let isPrivacyRestricted = privacyRestricted ?? enforceRagImeSensitiveFieldGuard()", patch_text)
        self.assertIn("func rimeConsumeCommittedText()", patch_text)
        ordinary_key_route_start = patch_text.index("handled = processKey(rimeKeycode, modifiers: rimeModifiers)")
        self.assertIn("rimeUpdate()", patch_text[ordinary_key_route_start : ordinary_key_route_start + 200])
        self.assertIn("ragImeNativeSelectionSnapshot(at: index)", patch_text)
        self.assertIn('traceRagImeFrontendEvent("native_rime_rank_feedback_recorded"', patch_text)
        for script_text in (prepare_script, build_script):
            self.assertIn('"rime-rank-feedback"', script_text)
            self.assertIn('"ragImeNativeSelectionSnapshot"', script_text)
            self.assertIn('"native_rime_rank_feedback_recorded"', script_text)
            self.assertIn('"guard !enforceRagImeSensitiveFieldGuard() else { return }"', script_text)
        normal_start = patch_text.index("let nativeSelection = ragImeNativeSelectionSnapshot(at: index)")
        normal_selection = patch_text[normal_start : normal_start + 500]
        self.assertLess(
            normal_selection.index("let success = rimeAPI.select_candidate_on_current_page(session, index)"),
            normal_selection.index("recordRagImeNativeSelection(nativeSelection)"),
        )

    def test_sensitive_app_policy_guards_capture_send_and_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_text = (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")
        prepare_script = (root / "scripts" / "prepare_squirrel_workspace.sh").read_text(encoding="utf-8")
        build_script = (root / "scripts" / "build_patched_squirrel.sh").read_text(encoding="utf-8")

        status_start = patch_text.index("func sensitiveFieldStatus(sourceAppBundleId: String = \"\")")
        status_body = patch_text[status_start : status_start + 5000]
        self.assertLess(status_body.index("sensitiveApplicationReason"), status_body.index("AXIsProcessTrusted"))
        self.assertIn("sensitiveFieldStatus(sourceAppBundleId: sourceAppBundleId)", patch_text)
        self.assertIn("sensitiveFieldStatus(sourceAppBundleId: currentApp)", patch_text)
        self.assertIn("sourceAppBundleId: currentApp", patch_text)
        self.assertIn('guard !enforceRagImeSensitiveFieldGuard(), ragImePrivacyDisposition == "allowed" else { return false }', patch_text)
        self.assertIn("guard !enforceRagImeSensitiveFieldGuard() else { return }", patch_text)

        trace_start = patch_text.index("func traceRagImeFrontendEvent(_ event: String, fields: [String: Any])")
        trace_body = patch_text[trace_start : trace_start + 1000]
        self.assertLess(
            trace_body.index("guard !ragImeSensitiveFieldActive else { return }"),
            trace_body.index("ragImeSanitizedTraceFields"),
        )
        for script_text in (prepare_script, build_script):
            self.assertIn('"privacy_unknown_ax_not_trusted"', script_text)
            self.assertIn('"sensitive_application_bundle"', script_text)
            self.assertIn('"guard !ragImeSensitiveFieldActive else { return }"', script_text)
            self.assertIn('"RAG_IME_SENSITIVE_APP_BUNDLE_IDS"', script_text)
            self.assertIn('"discardRagImeSensitiveNativeLearningTransaction"', script_text)
            self.assertIn('"rimeAPI.process_key(session, Int32(XK_BackSpace), 0)"', script_text)
            self.assertIn('"guard !isComposing else { return false }"', script_text)

    def test_assistant_overlay_single_and_three_candidate_geometry_is_stable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        overlay_sources = root / "squirrel-patches" / "sources"
        card_text = (overlay_sources / "RagImeSuggestionCardView.swift").read_text(encoding="utf-8")
        controller_text = (overlay_sources / "RagImeAssistantPanelController.swift").read_text(encoding="utf-8")
        row_height_match = re.search(r"static let rowHeight: CGFloat = ([0-9.]+)", card_text)
        action_height_match = re.search(r"static let actionHeight: CGFloat = ([0-9.]+)", card_text)

        self.assertIsNotNone(row_height_match)
        self.assertIsNotNone(action_height_match)
        row_height = float(row_height_match.group(1))
        action_height = float(action_height_match.group(1))
        self.assertEqual(row_height * min(3, 1), 36)
        self.assertEqual(row_height * min(3, 3), 108)
        self.assertEqual(row_height * min(3, 1) + action_height, 67)
        self.assertEqual(row_height * min(3, 3) + action_height, 139)
        self.assertIn("payload.snapshotId == renderedSnapshotId", controller_text)
        self.assertIn("stableIds == renderedStableIds", controller_text)
        self.assertIn("same_snapshot_stable_ids", controller_text)
        self.assertIn("RagImeSuggestionCardView.preferredPredictionWidth", controller_text)
        self.assertNotIn("let longest = realCandidates.map", controller_text)
        self.assertIn('resultHeader.stringValue = streaming ? "DS · 生成中" : "DS · 已生成"', card_text)
        self.assertNotIn("sourceLabel.isHidden = true", (overlay_sources / "RagImeSuggestionRowView.swift").read_text(encoding="utf-8"))

    def test_squirrel_patch_contains_active_rag_selected_text_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_text = (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")

        self.assertIn("RagImeSelectedTextProvider.swift", patch_text)
        self.assertIn("RagImeSelectedTextProvider.swift in Sources", patch_text)
        self.assertIn("struct RagImeActiveRagRequest: Codable", patch_text)
        self.assertIn("struct RagImeActiveRagResponse: Codable", patch_text)
        self.assertIn("func captureSelectedTextForActiveRag", patch_text)
        self.assertIn("allowAccessibility: Bool = true", patch_text)
        self.assertIn("allowClipboardFallback: Bool = true", patch_text)
        self.assertIn("captureSelectedTextViaAccessibility", patch_text)
        self.assertIn("kAXFocusedUIElementAttribute", patch_text)
        self.assertIn("kAXSelectedTextAttribute", patch_text)
        self.assertIn("captureSelectedTextViaClipboardFallbackPreservingPasteboard", patch_text)
        self.assertIn("NSPasteboard.general", patch_text)
        self.assertIn("restorePasteboardItems", patch_text)
        self.assertIn("clipboard_fallback_restores_clipboard_contract", patch_text)
        self.assertIn("ragImeActiveRagAccessibilityCaptureEnabled()", patch_text)
        self.assertIn("ragImeActiveRagClipboardFallbackEnabled()", patch_text)
        self.assertIn('RAG_IME_ACTIVE_RAG_CAPTURE_ACCESSIBILITY', patch_text)
        self.assertIn('RAG_IME_ACTIVE_RAG_CAPTURE_CLIPBOARD_FALLBACK', patch_text)

    def test_squirrel_patch_declares_active_rag_shortcut_and_endpoint(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_text = (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")

        self.assertIn("matchesRagImeActiveRagShortcut(keyCode, modifiers: modifiers)", patch_text)
        self.assertIn('UserDefaults.standard.string(forKey: "RagImeActiveRagShortcut")', patch_text)
        self.assertIn('ProcessInfo.processInfo.environment["RAG_IME_ACTIVE_RAG_SHORTCUT"]', patch_text)
        self.assertIn("} else if modifiers.contains(.shift)", patch_text)
        self.assertIn('return raw.isEmpty ? "ctrl+."', patch_text)
        self.assertIn("ragImeShortcutKeyMatches", patch_text)
        self.assertIn('case ".", "period", "dot": return [47]', patch_text)
        self.assertIn('case "enter": return [36, 76]', patch_text)
        self.assertIn('case "r": return [15]', patch_text)
        self.assertIn("startRagImeActiveRagAssistFromShortcut", patch_text)
        self.assertIn("startRagImeActiveRagAssistFromSelection", patch_text)
        self.assertIn("startRagImeActiveRagAssistFromContext", patch_text)
        self.assertIn("active_rag_shortcut_context_fallback", patch_text)
        self.assertIn("func startRagImeActiveRagAssistFromContext(actionCandidate: RagImeDisplayCandidate? = nil)", patch_text)
        self.assertIn('candidate.selectionAction == "start_active_rag_from_context"', patch_text)
        self.assertIn("ragImeDisplayCandidateIsShortcutOnlyAction", patch_text)
        self.assertIn('numberKeys: "pass_through"', patch_text)
        self.assertIn('"requiresExplicitSelection": .bool(true)', patch_text)
        self.assertIn('selectionKey: nil', patch_text)
        self.assertIn('candidateOrdinal: 1', patch_text)
        self.assertIn('"active_rag_shortcut_action_button_route"', patch_text)
        self.assertIn("active_rag_context_button_triggered", patch_text)
        self.assertIn("postActiveRagStatus", patch_text)
        self.assertIn("active_rag_status_poll_scheduled", patch_text)
        self.assertIn("response.pollAfterMs", patch_text)
        self.assertIn("postActiveRagStart", patch_text)
        self.assertIn('endpoint("active-rag/start"', patch_text)
        self.assertIn("active_rag_thinking_displayed", patch_text)
        self.assertIn("showRagImeActiveRagThinkingPlaceholder(request: request)", patch_text)
        self.assertIn("assistant_overlay_active_rag_thinking", patch_text)
        self.assertIn('"selectedTextChars": request.selectedTextChars', patch_text)
        self.assertIn('"frontAppBundleId": request.frontAppBundleId', patch_text)
        self.assertIn('"traceIncludesText": false', patch_text)
        self.assertIn("active_rag_ready_displayed", patch_text)
        self.assertIn("active_rag_response_dropped_stale", patch_text)
        self.assertIn("active_rag_candidate_committed", patch_text)

    def test_build_script_dry_run_reports_resolved_commands(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-build-") as tmp:
            workdir = Path(tmp) / "squirrel"
            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh"), "build"],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_BUILD_DRY_RUN": "1",
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_SQUIRREL_SCHEME": "SquirrelTest",
                    "RAG_IME_SQUIRREL_CONFIGURATION": "Debug",
                },
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn(f"workdir={workdir}", result.stdout)
        self.assertIn("scheme=SquirrelTest", result.stdout)
        self.assertIn("configuration=Debug", result.stdout)
        self.assertIn("list_command=", result.stdout)
        self.assertIn("build_command=", result.stdout)
        self.assertIn("CODE_SIGNING_ALLOWED=NO build", result.stdout)
        self.assertIn("enable_pref_repair=0", result.stdout)
        self.assertIn("auto_select=0", result.stdout)

    def test_branded_install_pref_repair_and_auto_select_are_explicit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "build_patched_squirrel.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_SQUIRREL_ENABLE_PREF_REPAIR", source)
        self.assertIn("RAG_IME_SQUIRREL_AUTO_SELECT", source)
        self.assertIn('if bool_true "$ENABLE_PREF_REPAIR"', source)
        self.assertIn('if bool_true "$AUTO_SELECT"', source)
        self.assertIn("preference repair is disabled", source)
        self.assertIn("not selecting branded input source automatically", source)
        self.assertIn("audit_canonical_squirrel_bundles.py", source)
        self.assertIn("--preinstall", source)
        self.assertIn('pkill -f "$TARGET_APP/Contents/MacOS/Squirrel"', source)
        self.assertIn("killall imklaunchagent TextInputMenuAgent TextInputSwitcher", source)
        self.assertIn('open -a "$TARGET_APP"', source)
        self.assertIn("traceRagImeProcessEvent", source)
        self.assertIn('elif [[ "$PREINSTALL" == "auto" ]]; then', source)
        self.assertIn("if ! deps_ready; then", source)
        self.assertNotIn('[[ "$PREINSTALL" == "auto" && ! deps_ready ]]', source)

    def test_build_script_uses_xcodebuild_list_and_build(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-build-") as tmp:
            tmp_path = Path(tmp)
            workdir = _fake_patched_squirrel_workdir(tmp_path)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_log = tmp_path / "xcodebuild.log"
            fake_xcodebuild = fake_bin / "xcodebuild"
            fake_xcodebuild.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "printf '%s\\n' \"$*\" >> \"$FAKE_XCODEBUILD_LOG\"",
                        "if [[ \"$1\" == \"-version\" ]]; then",
                        "  echo 'Xcode 16.0'",
                        "  echo 'Build version 16A000'",
                        "  exit 0",
                        "fi",
                        "if [[ \"$1\" == \"-project\" && \"$3\" == \"-list\" ]]; then",
                        "  echo 'Targets:'",
                        "  echo '  Squirrel'",
                        "  exit 0",
                        "fi",
                        "if [[ \"$1\" == \"-project\" && \"$*\" == *' CODE_SIGNING_ALLOWED=NO build'* ]]; then",
                        "  echo 'Build succeeded'",
                        "  exit 0",
                        "fi",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_xcodebuild.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_XCODEBUILD_LOG": str(fake_log),
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_SQUIRREL_DERIVED_DATA": str(tmp_path / "derived-data"),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            xcodebuild_log = fake_log.read_text(encoding="utf-8")
        self.assertIn("[OK] xcodebuild can inspect patched Squirrel project", result.stdout)
        self.assertIn("[OK] xcodebuild build succeeded", result.stdout)
        self.assertIn("-list", xcodebuild_log)
        self.assertIn("-scheme Squirrel", xcodebuild_log)
        self.assertIn("CODE_SIGNING_ALLOWED=NO build", xcodebuild_log)

    def test_install_action_copies_app_and_installs_rag_config(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-install-") as tmp:
            tmp_path = Path(tmp)
            workdir = _fake_patched_squirrel_workdir(tmp_path)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_xcodebuild = fake_bin / "xcodebuild"
            fake_xcodebuild.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "if [[ \"$1\" == \"-version\" ]]; then",
                        "  echo 'Xcode 16.0'",
                        "  echo 'Build version 16A000'",
                        "  exit 0",
                        "fi",
                        "if [[ \"$1\" == \"-project\" && \"$3\" == \"-list\" ]]; then",
                        "  echo 'Targets:'",
                        "  echo '  Squirrel'",
                        "  exit 0",
                        "fi",
                        "derived=''",
                        "previous=''",
                        "for arg in \"$@\"; do",
                        "  if [[ \"$previous\" == \"-derivedDataPath\" ]]; then derived=\"$arg\"; fi",
                        "  previous=\"$arg\"",
                        "done",
                        "if [[ \"$*\" == *' CODE_SIGNING_ALLOWED=NO build'* ]]; then",
                        "  mkdir -p \"$derived/Build/Products/Release/Squirrel.app/Contents/MacOS\"",
                        "  mkdir -p \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport\"",
                        "  printf 'schema_list:\\n  - schema: luna_pinyin\\n' > \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport/default.yaml\"",
                        "  printf 'schema:\\n  schema_id: luna_pinyin\\n' > \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport/luna_pinyin.schema.yaml\"",
                        "  printf -- '---\\nname: luna_pinyin\\n...\\n' > \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport/luna_pinyin.dict.yaml\"",
                        "  cat > \"$derived/Build/Products/Release/Squirrel.app/Contents/MacOS/Squirrel\" <<'SH'",
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        "if [[ \"${1:-}\" == \"--build\" ]]; then",
                        "  mkdir -p build",
                        "  printf 'default\\n' > build/default.yaml",
                        "  printf 'schema\\n' > build/luna_pinyin.schema.yaml",
                        "  printf 'table\\n' > build/luna_pinyin.table.bin",
                        "  exit 0",
                        "fi",
                        "if [[ \"${1:-}\" == \"--reload\" ]]; then exit 0; fi",
                        "exit 0",
                        "SH",
                        "  chmod +x \"$derived/Build/Products/Release/Squirrel.app/Contents/MacOS/Squirrel\"",
                        "  exit 0",
                        "fi",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_xcodebuild.chmod(0o755)
            install_dir = tmp_path / "Input Methods"
            system_install_dir = tmp_path / "System Input Methods"
            system_install_dir.mkdir()
            quarantine_root = tmp_path / "disabled-input-method-backups"
            (install_dir / "RAG-IME.app" / "Contents" / "MacOS").mkdir(parents=True)
            (install_dir / "RagIme.app" / "Contents" / "MacOS").mkdir(parents=True)
            rime_dir = tmp_path / "Rime"
            install_env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SQUIRREL_DERIVED_DATA": str(tmp_path / "derived-data"),
                "RAG_IME_SQUIRREL_INSTALL_DIR": str(install_dir),
                "RAG_IME_SQUIRREL_SYSTEM_INPUT_METHOD_DIR": str(system_install_dir),
                "RAG_IME_SQUIRREL_CANONICAL_QUARANTINE_DIR": str(quarantine_root),
                "RAG_IME_RIME_USER_DIR": str(rime_dir),
                "RAG_IME_SQUIRREL_SKIP_CODESIGN": "1",
                "RAG_IME_SQUIRREL_SKIP_POSTINSTALL": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh"), "install"],
                cwd=root,
                env=install_env,
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("[OK] installed patched Squirrel.app", result.stdout)
            self.assertIn("quarantined noncanonical input method app", result.stdout)
            self.assertIn("canonical input method bundle enforced", result.stdout)
            self.assertTrue((install_dir / "Squirrel.app" / "Contents" / "MacOS" / "Squirrel").is_file())
            self.assertFalse((install_dir / "RAG-IME.app").exists())
            self.assertFalse((install_dir / "RagIme.app").exists())
            self.assertIn(str(quarantine_root), result.stdout)
            self.assertTrue((workdir / "librime" / "include" / "rime_api_stdbool.h").is_file())
            config = (rime_dir / "squirrel.custom.yaml").read_text(encoding="utf-8")
            self.assertIn('"rag_ime/enabled": true', config)
            self.assertIn('"rag_ime/sidecar_url": "http://127.0.0.1:19866/api"', config)
            self.assertIn('"rag_ime/frontend_trace": true', config)
            self.assertIn("skipped Squirrel user-data bootstrap and postinstall", result.stderr)
            self.assertFalse((rime_dir / "build" / "luna_pinyin.table.bin").exists())

            target_executable = install_dir / "Squirrel.app" / "Contents" / "MacOS" / "Squirrel"
            target_executable.write_text("preflight-must-not-replace\n", encoding="utf-8")
            _write_same_bundle_app(system_install_dir / "LegacySquirrel.app")
            conflict = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh"), "install"],
                cwd=root,
                env=install_env,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("[ERROR] preinstall same-bundle conflict", conflict.stderr)
            self.assertEqual(target_executable.read_text(encoding="utf-8"), "preflight-must-not-replace\n")

    def test_build_script_fails_clearly_when_workdir_is_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-build-") as tmp:
            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_XCODEBUILD": sys.executable,
                    "RAG_IME_SQUIRREL_WORKDIR": str(Path(tmp) / "missing-squirrel"),
                },
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Squirrel workdir not prepared", result.stderr)
        self.assertIn("Run scripts/prepare_squirrel_workspace.sh first", result.stderr)


def _fake_patched_squirrel_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "squirrel"
    workdir.mkdir()
    subprocess.run(["git", "init"], cwd=workdir, check=True, capture_output=True, text=True)
    (workdir / "sources").mkdir()
    (workdir / "sources" / "RagImeSidecarModels.swift").write_text(
        "struct Request { let privacyDisposition: String }\n",
        encoding="utf-8",
    )
    (workdir / "sources" / "RagImeSidecarClient.swift").write_text(
        '// client endpoint("rime-rank-feedback", base: sidecarURL)\n'
        '// request.privacyDisposition == "allowed"\n',
        encoding="utf-8",
    )
    (workdir / "sources" / "RagImeSelectedTextProvider.swift").write_text(
        (
            "import ApplicationServices\n"
            "final class RagImeForegroundContextResolver {}\n"
            "final class RagImeSelectedTextProvider { "
            "func captureForegroundTextForSidecar() { "
            "_ = kAXSelectedTextRangeAttribute; "
            "_ = kAXStringForRangeParameterizedAttribute; "
            "_ = kAXValueAttribute } }\n"
            "// privacy_unknown_app_bundle_missing privacy_unknown_ax_not_trusted\n"
            "// privacy_unknown_focused_element_missing privacy_unknown_metadata_read_failed\n"
            "// privacy_unknown_text_field_metadata_missing sensitive_application_bundle\n"
            "// RAG_IME_SENSITIVE_APP_BUNDLE_IDS RagImeSensitiveAppBundleTokens\n"
        ),
        encoding="utf-8",
    )
    (workdir / "sources" / "SquirrelInputController.swift").write_text(
        (
            'final class SquirrelInputController { func ragImePanelForcesHorizontalLayout() -> Bool { false }; '
            'func ragImePanelUsesSideDisplay() -> Bool { false }; '
            '// ragImePrivacyDisposition == "allowed"; privacyDisposition: ragImePrivacyDisposition; '
            'func traceRagImeFrontendEvent() {}; '
            '// guard ragImeSidecarClient?.frontendTrace == true else { return }; '
            '// guard !ragImeSensitiveFieldActive else { return }; '
            '// ragImePrepareFrontendTraceLog .posixPermissions: 0o600 appendingPathExtension("1"); '
            '// let contextAnchor = ragImeStableTextHash(context); '
            '// queryAnchor: contextAnchor displayAnchor: contextAnchor; '
            'func traceRagImePanelTextLayout() { _ = "panel_text_layout" }; '
            'func traceSidecarRequestScheduled() { _ = "sidecar_request_scheduled" }; '
            'func traceSidecarEmptyResponseCleared() { _ = "sidecar_empty_response_cleared" }; '
            'func traceV2() { _ = "rag-ime.foreground-trace.v2" }; '
            'func forceSideCandidates() { let forceSideCandidates = rawInput.isEmpty && preedit.isEmpty; _ = "forceSideCandidates: forceSideCandidates" }; '
            'func compositionAISuppressed() { _ = "composition_ai_suppressed" }; '
            'func traceRimeComposition() { _ = "rime_composition_started"; _ = "rime_composition_candidates_visible" }; '
            'func controlCenterMenu() { _ = "打开 RAG-IME 控制中心..."; _ = "com.rag-ime.control" }; '
            'func suppressPostCommitOverlay() { _ = "RAG_IME_ASSISTANT_OVERLAY_AUTO_PENDING"; _ = "assistant_overlay_local_placeholder_suppressed" }; '
            'func foregroundSnapshot() { _ = "ragImeSelectedTextProvider.captureForegroundTextForSidecar" }; '
            'func foregroundCaptureResolved() { _ = "foreground_context_capture_resolved" }; '
            'func foregroundCaptureFailed() { _ = "foreground_context_capture_failed" }; '
            'func sideCandidateFeedbackRecorded() { _ = "side_candidate_feedback_recorded" }; '
            'func nativeRimeFeedback() { _ = "ragImeNativeSelectionSnapshot"; '
            '_ = "native_rime_rank_feedback_recorded"; '
            'guard !enforceRagImeSensitiveFieldGuard() else { return } }; '
            '// discardRagImeSensitiveNativeLearningTransaction; '
            '// guard rimeAPI.get_status(session, &status) else { return false }; '
            '// guard !isComposing else { return false }; return !backspaceHandled; '
            '// rimeAPI.process_key(session, Int32(XK_BackSpace), 0); '
            '// "forwardedToClient": false; '
            'func assistantOverlayCandidateVisible() { _ = "assistant_overlay_candidate_visible" }; '
            'func activeRagLocalThinkingTrace(request: Request) { _ = "assistant_overlay_active_rag_thinking"; traceRagImeFrontendEvent("active_rag_thinking_displayed", fields: ["selectedTextHash": request.selectedTextHash, "selectedTextChars": request.selectedTextChars, "frontAppBundleId": currentApp, "traceIncludesText": false]) }; '
            'func activeRagPollTrace(request: Request) { traceRagImeFrontendEvent("active_rag_status_poll_scheduled", fields: ["selectedTextHash": request.selectedTextHash, "selectedTextChars": request.selectedTextChars, "frontAppBundleId": request.frontAppBundleId, "traceIncludesText": false]) }; '
            'func ragImeDisplayComment() { _ = "candidate.sourceType == \\"model\\"" } }\n'
        ),
        encoding="utf-8",
    )
    (workdir / "sources" / "SquirrelPanel.swift").write_text(
        "final class SquirrelPanel { var ragImePanelLinear: Bool { true }; var ragImePanelUsesSideDisplay: Bool { false }; func nonGlassBackground() { _ = \"return NSView()\" }; func candidateSeparator(before index: Int) -> String { \" \" }; func traceRagImePanelTextLayout() {} }\n",
        encoding="utf-8",
    )
    (workdir / "sources" / "Main.swift").write_text(
        "struct SquirrelApp { static func traceRagImeProcessEvent() {} }\n",
        encoding="utf-8",
    )
    (workdir / "Squirrel.xcodeproj").mkdir()
    (workdir / "Squirrel.xcodeproj" / "project.pbxproj").write_text("// pbxproj\n", encoding="utf-8")
    (workdir / "librime" / "dist" / "include").mkdir(parents=True)
    (workdir / "librime" / "dist" / "include" / "rime_api_stdbool.h").write_text("// rime api\n", encoding="utf-8")
    (workdir / "rag-ime.squirrel.custom.yaml").write_text(
        "\n".join(
            [
                "rag_ime:",
                "  enabled: true",
                "  sidecar_url: http://127.0.0.1:19866/api",
                "  python: /usr/bin/python3",
                f"  repo_root: {tmp_path}",
                f"  db_path: {tmp_path / 'rag-ime.sqlite'}",
                "  project: offline-test",
                "  max_visible_candidates: 8",
                "  max_side_candidates: 5",
                "  latency_budget_ms: 300",
                "  debounce_ms: 80",
                "  timeout_ms: 250",
                "  frontend_trace: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workdir


def _write_same_bundle_app(path: Path) -> None:
    executable = path / "Contents" / "MacOS" / "Squirrel"
    executable.parent.mkdir(parents=True)
    (path / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleIdentifier": "im.rime.inputmethod.Squirrel"})
    )
    executable.write_text("legacy\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
