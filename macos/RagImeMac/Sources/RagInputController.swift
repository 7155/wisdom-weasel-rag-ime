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
    private var latestPredictionSession: RimePredictionSessionPayload?
    private var activePanelSession: ActivePanelSession?
    private var committedContext = ""
    private let bridge = RagBridgeClient()
    private let rimeCandidateProvider = RimeDictionaryCandidateProvider()
    private let sessionId = "rag-ime-mac-\(UUID().uuidString)"
    private var requestSeq = 0
    private var lastRenderedRequestSeq = 0
    private var pendingRefresh: DispatchWorkItem?
    private var panelExpiration: DispatchWorkItem?
    private let postCommitPanelTtlSeconds: TimeInterval = 0.85

    override func inputText(_ string: String!, client sender: Any!) -> Bool {
        guard let string, let client = sender as? IMKTextInput else {
            return false
        }

        clearExpiredPanelIfNeeded()

        if selectCandidateIfNeeded(string, client: client) {
            return true
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
            scheduleSuggestionRefresh(client: client)
            return true
        }

        return false
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
            return latestDisplayCandidates.map(\.text)
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

    private func updateMarkedText(client: IMKTextInput) {
        let range = NSRange(location: composition.utf16.count, length: 0)
        client.setMarkedText(
            composition,
            selectionRange: range,
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound)
        )
    }

    private func selectCandidateIfNeeded(_ string: String, client: IMKTextInput) -> Bool {
        if canRouteNumberToVisiblePanel(),
           let number = Int(string),
           number >= 1,
           let candidate = displayCandidate(matchingSelectionNumber: number) {
            let query = composition.isEmpty ? candidate.text : composition
            commit(text: candidate.insertText, client: client, selectedDisplayCandidate: candidate, selectedSuggestion: nil, rank: number, queryOverride: query)
            return true
        }

        return false
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
        if let candidate = rimeCandidateProvider.candidates(for: composition, maxCount: 1).first {
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

        let previousContext = committedContext
        let query = queryOverride ?? composition
        client.insertText(finalText, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        clearMarkedText(client: client)
        committedContext = appendingContext(previousContext, finalText)
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
                let request = RimeSelectRequest(
                    candidate: selectedDisplayCandidate,
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

        let previousContext = committedContext
        client.insertText(text, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        clearMarkedText(client: client)
        committedContext = appendingContext(previousContext, text.trimmingCharacters(in: .whitespacesAndNewlines))
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

    private func scheduleSuggestionRefresh(client providedClient: IMKTextInput? = nil) {
        pendingRefresh?.cancel()
        let inputSnapshot = composition
        guard inputSnapshot.count >= 1 else {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return
        }
        let contextSnapshot = committedContext
        let requestSeq = nextRequestSeq()

        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            do {
                let response = try self.bridge.rimeSuggest(request: self.makeRimeSuggestRequest(
                    requestSeq: requestSeq,
                    rawInput: inputSnapshot,
                    preedit: inputSnapshot,
                    commitTextPreview: "",
                    committedContext: contextSnapshot,
                    idleMs: 180,
                    forceSideCandidates: false
                ))
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
                        postCommit: false
                    )
                }
            } catch {
                DispatchQueue.main.async { [weak self] in
                    self?.clearCandidateState()
                    self?.clearVisiblePredictionPanel()
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
        let contextSnapshot = committedContext
        guard !contextSnapshot.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return
        }
        let requestSeq = nextRequestSeq()
        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            do {
                let response = try self.bridge.rimeSuggest(request: self.makeRimeSuggestRequest(
                    requestSeq: requestSeq,
                    rawInput: "",
                    preedit: "",
                    commitTextPreview: committedText,
                    committedContext: contextSnapshot,
                    idleMs: 80,
                    forceSideCandidates: false
                ))
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
                        postCommit: true
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
        postCommit: Bool
    ) {
        guard response.sessionId == sessionId else {
            return
        }
        guard response.requestSeq >= lastRenderedRequestSeq else {
            return
        }
        lastRenderedRequestSeq = response.requestSeq
        latestPredictionSession = response.predictionSession
        if !shouldShowCandidatePanel(response) {
            clearCandidateState()
            clearVisiblePredictionPanel()
            return
        }
        latestDisplayCandidates = response.displayCandidates
        latestModelPredictions = response.modelPredictions
        latestSuggestions = response.ragCandidates
        let anchor = panelAnchor(client: providedClient ?? client())
        RagCandidatePanel.shared.show(
            displayCandidates: response.displayCandidates,
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

    private func activatePanelSession(response: RimeSidecarResponse, postCommit: Bool) {
        let phase = response.predictionSession?.phase ?? ""
        activePanelSession = ActivePanelSession(
            requestSeq: response.requestSeq,
            sessionFingerprint: response.predictionSession?.sessionFingerprint ?? "",
            phase: phase,
            committedContext: committedContext,
            composition: composition,
            expiresAt: panelExpirationDate(phase: phase, postCommit: postCommit)
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

    private func panelExpirationDate(phase: String, postCommit: Bool) -> Date? {
        if postCommit || phase == "post_commit" || composition.isEmpty || phase.isEmpty {
            return Date().addingTimeInterval(postCommitPanelTtlSeconds)
        }
        return nil
    }

    private func shouldShowCandidatePanel(_ response: RimeSidecarResponse) -> Bool {
        guard !response.displayCandidates.isEmpty else {
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
        if trimmed.count >= 4, rimeCandidateProvider.candidates(for: trimmed, maxCount: 1).isEmpty {
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
        let rimeCandidates = rimeCandidateProvider.candidates(for: preedit.isEmpty ? rawInput : preedit, maxCount: 8)
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
            latencyBudgetMs: 300,
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
        guard RagCandidatePanel.shared.isVisible, let session = activePanelSession else {
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

    private func displayCandidate(matchingSelectionNumber number: Int) -> RimeDisplayCandidate? {
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
        latestPredictionSession = nil
    }

    private func clearVisiblePredictionPanel() {
        panelExpiration?.cancel()
        panelExpiration = nil
        activePanelSession = nil
        RagCandidatePanel.shared.hide()
    }

    private func cancelPendingRefresh(invalidateResponses: Bool) {
        pendingRefresh?.cancel()
        pendingRefresh = nil
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
        if next.count <= 900 {
            return next
        }
        return String(next.suffix(900))
    }

    private func panelAnchor(client: IMKTextInput?) -> NSPoint? {
        guard let client else {
            return nil
        }
        var actualRange = NSRange(location: NSNotFound, length: 0)
        let selectedRange = client.selectedRange()
        let markedCaretRange = NSRange(location: max(0, composition.utf16.count), length: 0)
        let range: NSRange
        if !composition.isEmpty {
            range = markedCaretRange
        } else {
            range = selectedRange.location == NSNotFound ? NSRange(location: 0, length: 0) : selectedRange
        }
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
