import AppKit
import InputMethodKit

@objc(RagInputController)
final class RagInputController: IMKInputController {
    private struct ActivePanelSession {
        let requestSeq: Int
        let sessionFingerprint: String
        let phase: String
        let committedContext: String
        let composition: String
        let expiresAt: Date?
    }

    private var composition = ""
    private var latestModelPredictions: [ModelPrediction] = []
    private var latestSuggestions: [RagSuggestion] = []
    private var latestDisplayCandidates: [RimeDisplayCandidate] = []
    private var latestAssistantOverlay: RagImeAssistantOverlayPayload?
    private var latestPredictionSession: RimePredictionSessionPayload?
    private var latestKeyPolicy: RimeKeyPolicyPayload?
    private var activePanelSession: ActivePanelSession?
    private var committedContext = ""
    private let bridge = RagBridgeClient()
    private let rimeCandidateProvider = RimeDictionaryCandidateProvider()
    private let sessionId = "rag-ime-mac-\(UUID().uuidString)"
    private var requestSeq = 0
    private var lastRenderedRequestSeq = 0
    private var pendingRefresh: DispatchWorkItem?
    private var pendingProgressiveFollowUp: DispatchWorkItem?
    private var panelExpiration: DispatchWorkItem?
    private let committedContextLimit = 900
    private let postCommitPanelTtlSeconds: TimeInterval = 8.0

    override func handle(_ event: NSEvent!, client sender: Any!) -> Bool {
        guard let event, event.type == .keyDown, let client = sender as? IMKTextInput else {
            return false
        }

        clearExpiredPanelIfNeeded()

        let modifiers = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        let hasCommandLikeModifier = modifiers.contains(.command)
            || modifiers.contains(.control)
            || modifiers.contains(.option)

        if event.keyCode == 51 && !hasCommandLikeModifier {
            return handleBackspace(client: client)
        }

        if event.keyCode == 53 && RagImeAssistantPanelController.shared.isVisible {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return true
        }

        if event.keyCode == 48 && !modifiers.contains(.command) && !modifiers.contains(.control) {
            if selectFirstOverlayCandidateIfNeeded(client: client) {
                return true
            }
        }

        if modifiers.contains(.option),
           let key = event.charactersIgnoringModifiers,
           selectOverlayCandidateIfNeeded(key, client: client) {
            return true
        }

        if let key = event.charactersIgnoringModifiers,
           selectionNumber(forKey: key) != nil,
           !hasCommandLikeModifier {
            let hadVisiblePanel = RagCandidatePanel.shared.isVisible || !latestDisplayCandidates.isEmpty
            if selectCandidateIfNeeded(key, client: client) {
                return true
            }
            if hadVisiblePanel {
                clearCandidateState()
                clearVisiblePredictionPanel()
                return true
            }
            return false
        }

        guard !hasCommandLikeModifier, let text = event.characters, !text.isEmpty else {
            return false
        }
        return inputText(text, client: sender)
    }

    override func inputText(_ string: String!, client sender: Any!) -> Bool {
        guard let string, let client = sender as? IMKTextInput else {
            return false
        }

        clearExpiredPanelIfNeeded()

        if selectCandidateIfNeeded(string, client: client) {
            return true
        }

        if isBackspaceText(string) {
            return handleBackspace(client: client)
        }

        if string == "\u{1b}" {
            cancelCurrentComposition(client: client)
            return true
        }

        if string == "\n" || string == "\r" {
            commit(text: composition, client: client, selectedSuggestion: nil, rank: nil)
            return true
        }

        if string == " " {
            if selectFirstCandidateIfAvailable(client: client) {
                return true
            }
            if isLikelyRawPassthroughComposition(composition) {
                commitRawText(text: "\(composition) ", preedit: composition, client: client)
                return true
            }
        }

        if isPrintableInput(string) {
            if composition.isEmpty && latestDisplayCandidates.isEmpty && isDigit(string) {
                return false
            }
            clearPostCommitPredictionPanelBeforeTyping()
            composition += string
            updateMarkedText(client: client)
            showLocalRimeFallbackCandidates(for: composition, client: client)
            scheduleSuggestionRefresh(client: client)
            return true
        }

        return false
    }

    private func selectOverlayCandidateIfNeeded(_ string: String, client: IMKTextInput) -> Bool {
        guard latestKeyPolicy?.optionNumber == "select_prediction_by_ordinal",
              let number = selectionNumber(forKey: string),
              canRouteNumberToVisiblePanel(),
              let candidate = displayCandidate(matchingSelectionNumber: number, selectionKey: string) else {
            return false
        }
        let query = composition.isEmpty ? candidate.text : composition
        commit(
            text: candidate.insertText,
            client: client,
            selectedDisplayCandidate: candidate,
            selectedSuggestion: nil,
            rank: candidate.selectionRank ?? number,
            queryOverride: query
        )
        return true
    }

    private func selectFirstOverlayCandidateIfNeeded(client: IMKTextInput) -> Bool {
        guard latestKeyPolicy?.tab == "accept_top_prediction",
              canRouteNumberToVisiblePanel(),
              let candidate = firstVisibleDisplayCandidate(),
              candidate.sourceType != "rime" else {
            return false
        }
        let query = composition.isEmpty ? candidate.text : composition
        commit(
            text: candidate.insertText,
            client: client,
            selectedDisplayCandidate: candidate,
            selectedSuggestion: nil,
            rank: candidate.selectionRank ?? 1,
            queryOverride: query
        )
        return true
    }

    override func commitComposition(_ sender: Any!) {
        guard let client = sender as? IMKTextInput else {
            return
        }
        commit(text: composition, client: client, selectedSuggestion: nil, rank: nil)
    }

    override func composedString(_ sender: Any!) -> Any! {
        composition
    }

    override func originalString(_ sender: Any!) -> NSAttributedString! {
        NSAttributedString(string: composition)
    }

    override func candidates(_ sender: Any!) -> [Any]! {
        if !latestDisplayCandidates.isEmpty {
            return latestDisplayCandidates.map(displayTextForSystemCandidate)
        }
        return latestModelPredictions.map(\.text) + latestSuggestions.map(\.surfaceText)
    }

    override func hidePalettes() {
        cancelPendingRefresh(invalidateResponses: true)
        clearCandidateState()
        clearVisiblePredictionPanel()
    }

    override func activateServer(_ sender: Any!) {
        super.activateServer(sender)
        clearExpiredPanelIfNeeded()
        rimeCandidateProvider.warmUp()
    }

    override func deactivateServer(_ sender: Any!) {
        super.deactivateServer(sender)
        composition = ""
        cancelPendingRefresh(invalidateResponses: true)
        clearCandidateState()
        if let client = sender as? IMKTextInput {
            clearMarkedText(client: client)
        }
        clearVisiblePredictionPanel()
    }

    private func isPrintableInput(_ string: String) -> Bool {
        guard string.count == 1, let scalar = string.unicodeScalars.first else {
            return false
        }
        return !CharacterSet.controlCharacters.contains(scalar)
    }

    private func isDigit(_ string: String) -> Bool {
        string.count == 1 && string.unicodeScalars.allSatisfy { CharacterSet.decimalDigits.contains($0) }
    }

    private func isBackspaceText(_ string: String) -> Bool {
        string == "\u{8}" || string == "\u{7f}"
    }

    private func updateMarkedText(client: IMKTextInput) {
        let range = NSRange(location: composition.utf16.count, length: 0)
        client.setMarkedText(
            composition,
            selectionRange: range,
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound)
        )
    }

    private func selectCandidateIfNeeded(_ string: String, client: IMKTextInput) -> Bool {
        guard let number = selectionNumber(forKey: string) else {
            return false
        }
        if canRouteNumberToVisiblePanel(),
           latestKeyPolicy?.numberKeys == "select_visible_candidate",
           let candidate = displayCandidate(matchingSelectionNumber: number, selectionKey: string) {
            let query = composition.isEmpty ? candidate.text : composition
            commit(text: candidate.insertText, client: client, selectedDisplayCandidate: candidate, selectedSuggestion: nil, rank: number, queryOverride: query)
            return true
        }

        return false
    }

    private func selectionNumber(forKey key: String) -> Int? {
        guard key.count == 1, let scalar = key.unicodeScalars.first else {
            return nil
        }
        guard CharacterSet.decimalDigits.contains(scalar) else {
            return nil
        }
        if key == "0" {
            return 10
        }
        return Int(key)
    }

    private func selectFirstCandidateIfAvailable(client: IMKTextInput) -> Bool {
        clearExpiredPanelIfNeeded()
        if canRouteNumberToVisiblePanel(), let candidate = firstVisibleDisplayCandidate() {
            let query = composition.isEmpty ? candidate.text : composition
            commit(text: candidate.insertText, client: client, selectedDisplayCandidate: candidate, selectedSuggestion: nil, rank: candidate.selectionRank ?? 1, queryOverride: query)
            return true
        }
        guard !composition.isEmpty else {
            return false
        }
        if let candidate = rimeCandidateProvider.candidates(for: composition, maxCount: 1, allowColdLoad: false).first {
            commit(text: candidate.text, client: client, selectedSuggestion: nil, rank: 1, queryOverride: composition)
            return true
        }
        return false
    }

    private func commit(
        text: String,
        client: IMKTextInput,
        selectedDisplayCandidate: RimeDisplayCandidate? = nil,
        selectedSuggestion: RagSuggestion?,
        rank: Int?,
        queryOverride: String? = nil
    ) {
        let finalText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !finalText.isEmpty else {
            cancelCurrentComposition(client: client)
            return
        }

        let previousContext = actualCommittedContext(client: client, fallback: committedContext, excludingMarkedText: composition)
        committedContext = previousContext
        let query = queryOverride ?? composition
        let shownDisplayCandidates = latestDisplayCandidates
        let shouldRecordSelectedDisplayCandidate = selectedDisplayCandidate.map(shouldRecordSideCandidateSelection) ?? false
        client.insertText(finalText, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        clearMarkedText(client: client)
        committedContext = actualCommittedContext(client: client, fallback: appendingContext(previousContext, finalText))
        composition = ""
        clearCandidateState()
        cancelPendingRefresh(invalidateResponses: true)
        clearVisiblePredictionPanel()

        let bridge = self.bridge
        let sessionId = self.sessionId
        let requestSeq = self.requestSeq
        let project = self.bridge.project
        DispatchQueue.global(qos: .utility).async {
            if let selectedDisplayCandidate {
                if shouldRecordSelectedDisplayCandidate {
                    let request = RimeSelectRequest(
                        candidate: selectedDisplayCandidate,
                        shownCandidates: shownDisplayCandidates,
                        query: query,
                        recentContext: previousContext,
                        preedit: query,
                        project: project,
                        app: "RagImeMac",
                        sessionId: sessionId,
                        requestSeq: requestSeq,
                        source: "rag-ime-mac-native",
                        providerName: "rag-ime-mac:\(selectedDisplayCandidate.sourceType)",
                        dryRun: false
                    )
                    _ = try? bridge.rimeSelect(request: request)
                } else {
                    try? bridge.recordCommit(text: finalText, recentContext: previousContext, preedit: query, source: "macos_inputmethod_rime")
                }
            } else if let selectedSuggestion {
                _ = try? bridge.apply(actionType: "accepted", suggestion: selectedSuggestion, query: query)
                try? bridge.recordCommit(text: finalText, recentContext: previousContext, preedit: query, source: "macos_inputmethod")
            } else {
                try? bridge.recordCommit(text: finalText, recentContext: previousContext, preedit: query, source: "macos_inputmethod")
            }
        }

        schedulePostCommitPrediction(client: client, committedText: finalText)
    }

    private func commitRawText(text: String, preedit: String, client: IMKTextInput) {
        guard !text.isEmpty else {
            cancelCurrentComposition(client: client)
            return
        }

        let previousContext = actualCommittedContext(client: client, fallback: committedContext, excludingMarkedText: composition)
        committedContext = previousContext
        client.insertText(text, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        clearMarkedText(client: client)
        committedContext = actualCommittedContext(
            client: client,
            fallback: appendingContext(previousContext, text.trimmingCharacters(in: .whitespacesAndNewlines))
        )
        composition = ""
        clearCandidateState()
        cancelPendingRefresh(invalidateResponses: true)
        clearVisiblePredictionPanel()

        let bridge = self.bridge
        DispatchQueue.global(qos: .utility).async {
            try? bridge.recordCommit(text: text.trimmingCharacters(in: .whitespacesAndNewlines), recentContext: previousContext, preedit: preedit, source: "macos_inputmethod_raw")
        }
    }

    private func cancelCurrentComposition(client: IMKTextInput) {
        composition = ""
        clearCandidateState()
        cancelPendingRefresh(invalidateResponses: true)
        panelExpiration?.cancel()
        clearMarkedText(client: client)
        clearVisiblePredictionPanel()
    }

    private func handleBackspace(client: IMKTextInput) -> Bool {
        clearCandidateState()
        cancelPendingRefresh(invalidateResponses: true)
        clearVisiblePredictionPanel()

        guard !composition.isEmpty else {
            removeLastCommittedContextCharacter()
            return false
        }

        composition.removeLast()
        if composition.isEmpty {
            clearMarkedText(client: client)
            return true
        }
        updateMarkedText(client: client)
        showLocalRimeFallbackCandidates(for: composition, client: client)
        scheduleSuggestionRefresh(client: client)
        return true
    }

    private func scheduleSuggestionRefresh(client providedClient: IMKTextInput? = nil) {
        pendingRefresh?.cancel()
        let inputSnapshot = composition
        guard inputSnapshot.count >= 1 else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return
        }
        let contextSnapshot = syncCommittedContextFromClient(providedClient ?? client(), excludingMarkedText: inputSnapshot)
        let requestSeq = nextRequestSeq()

        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            do {
                let request = self.makeRimeSuggestRequest(
                    requestSeq: requestSeq,
                    rawInput: inputSnapshot,
                    preedit: inputSnapshot,
                    commitTextPreview: "",
                    committedContext: contextSnapshot,
                    idleMs: 180,
                    forceSideCandidates: !contextSnapshot.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
                let response = try self.bridge.rimeSuggest(request: request)
                DispatchQueue.main.async { [weak self] in
                    guard let self else {
                        return
                    }
                    guard
                        response.requestSeq == requestSeq,
                        requestSeq == self.requestSeq,
                        self.composition == inputSnapshot,
                        self.committedContext == contextSnapshot
                    else {
                        return
                    }
                    self.renderSidecarResponse(
                        response,
                        currentInput: inputSnapshot,
                        client: providedClient ?? self.client(),
                        postCommit: false,
                        originalRequest: request
                    )
                }
            } catch {
                DispatchQueue.main.async { [weak self] in
                    guard
                        let self,
                        self.composition == inputSnapshot,
                        self.committedContext == contextSnapshot
                    else {
                        return
                    }
                    self.showLocalRimeFallbackCandidates(for: inputSnapshot, client: providedClient ?? self.client())
                }
                NSLog("RAG IME suggest failed: \(error.localizedDescription)")
            }
        }
        pendingRefresh = work
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 0.18, execute: work)
    }

    private func schedulePostCommitPrediction(client providedClient: IMKTextInput, committedText: String) {
        pendingRefresh?.cancel()
        panelExpiration?.cancel()
        let contextSnapshot = syncCommittedContextFromClient(providedClient)
        guard !contextSnapshot.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return
        }
        let requestSeq = nextRequestSeq()
        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            do {
                let request = self.makeRimeSuggestRequest(
                    requestSeq: requestSeq,
                    rawInput: "",
                    preedit: "",
                    commitTextPreview: committedText,
                    committedContext: contextSnapshot,
                    idleMs: 80,
                    forceSideCandidates: true
                )
                let response = try self.bridge.rimeSuggest(request: request)
                DispatchQueue.main.async { [weak self] in
                    guard let self else {
                        return
                    }
                    guard
                        response.requestSeq == requestSeq,
                        requestSeq == self.requestSeq,
                        self.composition.isEmpty,
                        self.committedContext == contextSnapshot
                    else {
                        return
                    }
                    self.renderSidecarResponse(
                        response,
                        currentInput: committedText,
                        client: providedClient,
                        postCommit: true,
                        originalRequest: request
                    )
                }
            } catch {
                DispatchQueue.main.async { [weak self] in
                    self?.clearVisiblePredictionPanel()
                }
                NSLog("RAG IME post-commit prediction failed: \(error.localizedDescription)")
            }
        }
        pendingRefresh = work
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 0.08, execute: work)
    }

    private func renderSidecarResponse(
        _ response: RimeSidecarResponse,
        currentInput: String,
        client providedClient: IMKTextInput?,
        postCommit: Bool,
        originalRequest: RimeSidecarRequest
    ) {
        guard response.sessionId == sessionId else {
            return
        }
        guard response.requestSeq >= lastRenderedRequestSeq else {
            return
        }
        lastRenderedRequestSeq = response.requestSeq
        latestPredictionSession = response.predictionSession
        latestKeyPolicy = response.keyPolicy
        scheduleProgressiveFollowUpIfNeeded(
            response: response,
            originalRequest: originalRequest,
            currentInput: currentInput,
            client: providedClient,
            postCommit: postCommit
        )
        let anchor = panelAnchor(client: providedClient ?? client())
        let overlayCandidates = response.assistantOverlay?.candidates ?? []
        renderAssistantOverlay(response: response, anchor: anchor)

        let panelDisplayCandidates = response.candidatePanel?.candidates ?? response.displayCandidates.filter { $0.sourceType == "rime" }
        if panelDisplayCandidates.isEmpty {
            latestDisplayCandidates = overlayCandidates
            latestModelPredictions = response.modelPredictions
            latestSuggestions = response.ragCandidates
            if response.predictionSession?.shouldClearPredictionPanel == true {
                clearCandidateState()
                clearVisiblePredictionPanel()
            }
            if response.assistantOverlay?.visible == true {
                activatePanelSession(response: response, postCommit: postCommit)
            } else {
                RagCandidatePanel.shared.hide()
            }
            return
        }
        if !shouldShowCandidatePanel(response, panelDisplayCandidates: panelDisplayCandidates) {
            clearCandidateState()
            RagCandidatePanel.shared.hide()
            return
        }
        latestDisplayCandidates = overlayCandidates.isEmpty ? panelDisplayCandidates : overlayCandidates
        latestModelPredictions = response.modelPredictions
        latestSuggestions = response.ragCandidates
        RagCandidatePanel.shared.show(
            displayCandidates: panelDisplayCandidates,
            currentInput: currentInput.isEmpty ? response.semanticQuery : currentInput,
            anchor: anchor,
            onSelect: { [weak self] candidate, index in
                guard let self, let client = self.client() else {
                    return
                }
                guard self.canSelectPanelCandidate(candidate, response: response) else {
                    return
                }
                let query = self.composition.isEmpty ? response.semanticQuery : self.composition
                self.commit(text: candidate.insertText, client: client, selectedDisplayCandidate: candidate, selectedSuggestion: nil, rank: index + 1, queryOverride: query)
            }
        )
        activatePanelSession(response: response, postCommit: postCommit)
    }

    private func renderAssistantOverlay(response: RimeSidecarResponse, anchor: NSPoint?) {
        latestAssistantOverlay = response.assistantOverlay
        RagImeAssistantPanelController.shared.update(payload: response.assistantOverlay, anchor: anchor) { [weak self] candidate, index in
            guard let self, let client = self.client() else {
                return
            }
            guard self.canSelectPanelCandidate(candidate, response: response) else {
                return
            }
            let query = self.composition.isEmpty ? response.semanticQuery : self.composition
            self.commit(
                text: candidate.insertText,
                client: client,
                selectedDisplayCandidate: candidate,
                selectedSuggestion: nil,
                rank: candidate.selectionRank ?? index + 1,
                queryOverride: query
            )
        }
    }

    private func scheduleProgressiveFollowUpIfNeeded(
        response: RimeSidecarResponse,
        originalRequest: RimeSidecarRequest,
        currentInput: String,
        client providedClient: IMKTextInput?,
        postCommit: Bool
    ) {
        guard let progressive = response.progressive,
              progressive.enabled,
              progressive.shouldFollowUp else {
            return
        }
        let retryAfterMs = max(80, min(1500, progressive.retryAfterMs))
        pendingProgressiveFollowUp?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            guard originalRequest.requestSeq == self.requestSeq else {
                return
            }
            guard self.committedContext == originalRequest.committedContext else {
                return
            }
            if postCommit {
                guard self.composition.isEmpty else {
                    return
                }
            } else {
                let liveInput = originalRequest.preedit.isEmpty ? originalRequest.rawInput : originalRequest.preedit
                guard self.composition == liveInput else {
                    return
                }
            }
            do {
                let followUp = try self.bridge.rimeSuggest(request: originalRequest)
                DispatchQueue.main.async { [weak self] in
                    guard let self else {
                        return
                    }
                    guard originalRequest.requestSeq == self.requestSeq,
                          self.committedContext == originalRequest.committedContext else {
                        return
                    }
                    if postCommit {
                        guard self.composition.isEmpty else {
                            return
                        }
                    } else {
                        let liveInput = originalRequest.preedit.isEmpty ? originalRequest.rawInput : originalRequest.preedit
                        guard self.composition == liveInput else {
                            return
                        }
                    }
                    self.renderSidecarResponse(
                        followUp,
                        currentInput: currentInput,
                        client: providedClient ?? self.client(),
                        postCommit: postCommit,
                        originalRequest: originalRequest
                    )
                }
            } catch {
                NSLog("RAG IME progressive follow-up failed: \(error.localizedDescription)")
            }
        }
        pendingProgressiveFollowUp = work
        DispatchQueue.global(qos: .userInitiated).asyncAfter(
            deadline: .now() + TimeInterval(retryAfterMs) / 1000.0,
            execute: work
        )
    }

    private func showLocalRimeFallbackCandidates(for input: String, client providedClient: IMKTextInput?) {
        let candidates = rimeCandidateProvider.candidates(for: input, maxCount: 8, allowColdLoad: false)
        guard !candidates.isEmpty else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return
        }
        latestDisplayCandidates = candidates.enumerated().map { index, candidate in
            RimeDisplayCandidate(
                label: candidate.label.isEmpty ? "\(index + 1)" : candidate.label,
                selectionKey: "\(index + 1)",
                selectionRank: index + 1,
                text: candidate.text,
                insertText: candidate.text,
                sourceType: "rime",
                selectionAction: "select_rime_candidate",
                sourceIndex: candidate.index ?? index,
                comment: candidate.comment,
                evidencePreview: candidate.comment.isEmpty ? "local dictionary" : candidate.comment,
                expandedEvidence: nil,
                suggestionId: "",
                memoryId: "",
                sourceEventId: nil,
                rimeIndex: candidate.index ?? index,
                displayLayout: "inline",
                displayLane: "rime",
                metadata: [:]
            )
        }
        latestModelPredictions = []
        latestSuggestions = []
        latestPredictionSession = nil
        latestKeyPolicy = nil
        activePanelSession = ActivePanelSession(
            requestSeq: requestSeq,
            sessionFingerprint: "local-rime-\(input)",
            phase: "anchor_composing",
            committedContext: committedContext,
            composition: input,
            expiresAt: nil
        )
        panelExpiration?.cancel()
        panelExpiration = nil
        RagCandidatePanel.shared.show(
            displayCandidates: latestDisplayCandidates,
            currentInput: input,
            anchor: panelAnchor(client: providedClient),
            onSelect: { [weak self] candidate, index in
                guard let self, let client = self.client() else {
                    return
                }
                guard self.composition == input else {
                    return
                }
                self.commit(
                    text: candidate.insertText,
                    client: client,
                    selectedDisplayCandidate: candidate,
                    selectedSuggestion: nil,
                    rank: candidate.selectionRank ?? index + 1,
                    queryOverride: input
                )
            }
        )
    }

    private func activatePanelSession(response: RimeSidecarResponse, postCommit: Bool) {
        let predictionSession = response.predictionSession
        let phase = predictionSession?.phase ?? ""
        activePanelSession = ActivePanelSession(
            requestSeq: response.requestSeq,
            sessionFingerprint: predictionSession?.sessionFingerprint ?? "",
            phase: phase,
            committedContext: response.committedContext,
            composition: composition,
            expiresAt: panelExpirationDate(session: predictionSession, postCommit: postCommit)
        )
        schedulePanelExpiration()
    }

    private func schedulePanelExpiration() {
        panelExpiration?.cancel()
        guard let session = activePanelSession, let expiresAt = session.expiresAt else {
            panelExpiration = nil
            return
        }
        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            guard
                let current = self.activePanelSession,
                current.requestSeq == session.requestSeq,
                current.sessionFingerprint == session.sessionFingerprint,
                current.phase == session.phase,
                current.committedContext == session.committedContext,
                current.composition == session.composition
            else {
                return
            }
            self.clearCandidateState()
            self.clearVisiblePredictionPanel()
        }
        panelExpiration = work
        DispatchQueue.main.asyncAfter(deadline: .now() + max(0.05, expiresAt.timeIntervalSinceNow), execute: work)
    }

    private func panelExpirationDate(session: RimePredictionSessionPayload?, postCommit: Bool) -> Date? {
        if let expiresAfterMs = session?.expiresAfterMs, expiresAfterMs > 0 {
            return Date().addingTimeInterval(TimeInterval(expiresAfterMs) / 1000.0)
        }
        let phase = session?.phase ?? ""
        if postCommit || phase == "post_commit" || composition.isEmpty || phase.isEmpty {
            return Date().addingTimeInterval(postCommitPanelTtlSeconds)
        }
        return nil
    }

    private func shouldShowCandidatePanel(_ response: RimeSidecarResponse, panelDisplayCandidates: [RimeDisplayCandidate]? = nil) -> Bool {
        let candidates = panelDisplayCandidates ?? response.displayCandidates
        guard !candidates.isEmpty else {
            return false
        }
        guard let session = response.predictionSession else {
            return !composition.isEmpty
        }
        if session.shouldClearPredictionPanel {
            return false
        }
        switch session.phase {
        case "post_commit":
            return session.predictionPanelVisible && composition.isEmpty
        case "prefix_constrained":
            return session.candidatePanelVisible && !composition.isEmpty
        case "anchor_composing":
            return session.candidatePanelVisible && !composition.isEmpty
        case "raw_passthrough", "hidden":
            return false
        default:
            return session.candidatePanelVisible || session.predictionPanelVisible
        }
    }

    private func isLikelyRawPassthroughComposition(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return false
        }
        guard trimmed.unicodeScalars.allSatisfy({ scalar in
            scalar.isASCII && !CharacterSet.controlCharacters.contains(scalar)
        }) else {
            return false
        }
        if trimmed.contains("/") || trimmed.contains(".") || trimmed.contains("_") || trimmed.contains("-") {
            return true
        }
        if trimmed.rangeOfCharacter(from: .decimalDigits) != nil {
            return true
        }
        if trimmed.count >= 4,
           rimeCandidateProvider.isReady,
           rimeCandidateProvider.candidates(for: trimmed, maxCount: 1, allowColdLoad: false).isEmpty {
            return true
        }
        return false
    }

    private func handlePanelAction(_ action: String, suggestion: RagSuggestion, query: String) {
        if action == "expand" {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(suggestion.expandedEvidence, forType: .string)
            return
        }
        let bridge = self.bridge
        DispatchQueue.global(qos: .utility).async { [weak self, bridge] in
            _ = try? bridge.apply(actionType: action, suggestion: suggestion, query: query)
            DispatchQueue.main.async {
                self?.scheduleSuggestionRefresh()
            }
        }
    }

    private func makeRimeSuggestRequest(
        requestSeq: Int,
        rawInput: String,
        preedit: String,
        commitTextPreview: String,
        committedContext: String,
        idleMs: Int,
        forceSideCandidates: Bool
    ) -> RimeSidecarRequest {
        let rimeCandidates = rimeCandidateProvider.candidates(for: preedit.isEmpty ? rawInput : preedit, maxCount: 8, allowColdLoad: false)
        return RimeSidecarRequest(
            sessionId: sessionId,
            requestSeq: requestSeq,
            rawInput: rawInput,
            preedit: preedit,
            commitTextPreview: commitTextPreview,
            committedContext: committedContext,
            project: bridge.project,
            app: "RagImeMac",
            idleMs: idleMs,
            latencyBudgetMs: 3200,
            forceSideCandidates: forceSideCandidates,
            predictionFirstMerge: true,
            maxVisibleCandidates: 8,
            maxSideCandidates: 8,
            rimeContext: RimeContextPayload(candidates: rimeCandidates, highlightedIndex: 0, page: 0, isLastPage: true)
        )
    }

    private func nextRequestSeq() -> Int {
        requestSeq += 1
        return requestSeq
    }

    private func canRouteNumberToVisiblePanel() -> Bool {
        guard RagCandidatePanel.shared.isVisible || !latestDisplayCandidates.isEmpty else {
            return false
        }
        guard let session = activePanelSession else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return false
        }
        if let expiresAt = session.expiresAt, expiresAt <= Date() {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return false
        }
        guard session.committedContext == committedContext else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return false
        }
        if let currentFingerprint = latestPredictionSession?.sessionFingerprint,
           !currentFingerprint.isEmpty,
           session.sessionFingerprint != currentFingerprint {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return false
        }
        switch session.phase {
        case "post_commit":
            return composition.isEmpty
        case "prefix_constrained", "anchor_composing":
            return !composition.isEmpty && session.composition == composition
        default:
            return false
        }
    }

    private func displayCandidate(matchingSelectionNumber number: Int, selectionKey: String? = nil) -> RimeDisplayCandidate? {
        if let selectionKey,
           let candidate = latestDisplayCandidates.first(where: { $0.selectionKey == selectionKey }) {
            return candidate
        }
        if let candidate = latestDisplayCandidates.first(where: { candidate in
            if candidate.selectionRank == number {
                return true
            }
            if candidate.selectionKey == "\(number)" {
                return true
            }
            return false
        }) {
            return candidate
        }
        if latestDisplayCandidates.indices.contains(number - 1) {
            return latestDisplayCandidates[number - 1]
        }
        return nil
    }

    private func displayTextForSystemCandidate(_ candidate: RimeDisplayCandidate) -> String {
        let insertText = candidate.insertText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !insertText.isEmpty {
            return stripSourceSuffix(insertText)
        }
        return stripSourceSuffix(candidate.text)
    }

    private func stripSourceSuffix(_ text: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for suffix in ["_model", "_rag", "_memory", " [LLM]", " [RAG]", " LLM", " RAG", " 模", " 查", " 忆"] {
            if value.hasSuffix(suffix) {
                value = String(value.dropLast(suffix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
                break
            }
        }
        return value
    }

    private func canSelectPanelCandidate(_ candidate: RimeDisplayCandidate, response: RimeSidecarResponse) -> Bool {
        clearExpiredPanelIfNeeded()
        guard let session = activePanelSession else {
            return false
        }
        guard session.requestSeq == response.requestSeq else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return false
        }
        if let responseFingerprint = response.predictionSession?.sessionFingerprint, !responseFingerprint.isEmpty {
            guard session.sessionFingerprint == responseFingerprint else {
                clearCandidateState()
                clearVisiblePredictionPanel()
                return false
            }
            if let candidateFingerprint = metadataString(candidate, key: "sessionFingerprint"),
               !candidateFingerprint.isEmpty,
               candidateFingerprint != responseFingerprint {
                clearCandidateState()
                clearVisiblePredictionPanel()
                return false
            }
        }
        guard session.committedContext == committedContext else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return false
        }
        switch session.phase {
        case "post_commit":
            return composition.isEmpty
        case "prefix_constrained", "anchor_composing":
            return !composition.isEmpty && session.composition == composition
        default:
            return false
        }
    }

    private func shouldRecordSideCandidateSelection(_ candidate: RimeDisplayCandidate) -> Bool {
        if candidate.selectionAction == "select_rime_candidate" || candidate.sourceType == "rime" {
            return false
        }
        return true
    }

    private func firstVisibleDisplayCandidate() -> RimeDisplayCandidate? {
        latestDisplayCandidates.min {
            ($0.selectionRank ?? Int.max) < ($1.selectionRank ?? Int.max)
        } ?? latestDisplayCandidates.first
    }

    private func clearExpiredPanelIfNeeded() {
        guard let session = activePanelSession, let expiresAt = session.expiresAt, expiresAt <= Date() else {
            return
        }
        clearCandidateState()
        clearVisiblePredictionPanel()
    }

    private func clearPostCommitPredictionPanelBeforeTyping() {
        guard activePanelSession?.phase == "post_commit" || latestPredictionSession?.phase == "post_commit" else {
            return
        }
        clearCandidateState()
        clearVisiblePredictionPanel()
    }

    private func clearMarkedText(client: IMKTextInput) {
        client.setMarkedText(
            "",
            selectionRange: NSRange(location: 0, length: 0),
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound)
        )
    }

    private func clearCandidateState() {
        latestModelPredictions = []
        latestSuggestions = []
        latestDisplayCandidates = []
        latestAssistantOverlay = nil
        latestPredictionSession = nil
        latestKeyPolicy = nil
    }

    private func clearVisiblePredictionPanel() {
        pendingProgressiveFollowUp?.cancel()
        pendingProgressiveFollowUp = nil
        panelExpiration?.cancel()
        panelExpiration = nil
        activePanelSession = nil
        RagCandidatePanel.shared.hide()
        RagImeAssistantPanelController.shared.dismiss(reason: "clear_visible_prediction_panel")
    }

    private func cancelPendingRefresh(invalidateResponses: Bool) {
        pendingRefresh?.cancel()
        pendingRefresh = nil
        pendingProgressiveFollowUp?.cancel()
        pendingProgressiveFollowUp = nil
        if invalidateResponses {
            requestSeq += 1
        }
    }

    private func appendingContext(_ context: String, _ text: String) -> String {
        let next: String
        if context.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            next = text
        } else {
            next = "\(context) \(text)"
        }
        return boundedContext(next)
    }

    private func removeLastCommittedContextCharacter() {
        var context = committedContext.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !context.isEmpty else {
            committedContext = ""
            return
        }
        context.removeLast()
        committedContext = context.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    @discardableResult
    private func syncCommittedContextFromClient(_ client: IMKTextInput?, excludingMarkedText markedText: String = "") -> String {
        let actualContext = actualCommittedContext(client: client, fallback: committedContext, excludingMarkedText: markedText)
        committedContext = actualContext
        return actualContext
    }

    private func actualCommittedContext(
        client: IMKTextInput?,
        fallback: String,
        excludingMarkedText markedText: String = ""
    ) -> String {
        guard let client else {
            return boundedContext(fallback)
        }
        let selectedRange = client.selectedRange()
        guard selectedRange.location != NSNotFound, selectedRange.location > 0 else {
            return boundedContext(fallback)
        }

        let readLimit = committedContextLimit + markedText.utf16.count
        let length = min(selectedRange.location, readLimit)
        let range = NSRange(location: selectedRange.location - length, length: length)
        guard let attributed = client.attributedSubstring(from: range) else {
            return boundedContext(fallback)
        }

        var text = attributed.string.trimmingCharacters(in: .whitespacesAndNewlines)
        if !markedText.isEmpty, text.hasSuffix(markedText) {
            text.removeLast(markedText.count)
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        guard !text.isEmpty else {
            return boundedContext(fallback)
        }
        return boundedContext(text)
    }

    private func boundedContext(_ text: String) -> String {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized.count > committedContextLimit else {
            return normalized
        }
        return String(normalized.suffix(committedContextLimit))
    }

    private func panelAnchor(client: IMKTextInput?) -> NSPoint? {
        guard let client else {
            return nil
        }
        var actualRange = NSRange(location: NSNotFound, length: 0)
        let selectedRange = client.selectedRange()
        let range = selectedRange.location == NSNotFound
            ? NSRange(location: NSNotFound, length: 0)
            : NSRange(location: selectedRange.location, length: 0)
        let rect = client.firstRect(forCharacterRange: range, actualRange: &actualRange)
        guard
            rect.origin.x.isFinite,
            rect.origin.y.isFinite,
            rect.size.width.isFinite,
            rect.size.height.isFinite
        else {
            return nil
        }
        guard rect != .zero else {
            return nil
        }
        return NSPoint(x: rect.minX, y: rect.minY)
    }

    private func metadataString(_ candidate: RimeDisplayCandidate, key: String) -> String? {
        guard let value = candidate.metadata[key] else {
            return nil
        }
        switch value {
        case .string(let text):
            return text
        case .number(let number):
            return String(Int(number))
        default:
            return nil
        }
    }
}
