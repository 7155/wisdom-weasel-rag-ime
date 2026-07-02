import AppKit
import InputMethodKit

@objc(RagInputController)
final class RagInputController: IMKInputController {
    private var composition = ""
    private var latestModelPredictions: [ModelPrediction] = []
    private var latestSuggestions: [RagSuggestion] = []
    private var latestDisplayCandidates: [RimeDisplayCandidate] = []
    private var latestPredictionSession: RimePredictionSessionPayload?
    private var committedContext = ""
    private let bridge = RagBridgeClient()
    private let sessionId = "rag-ime-mac-\(UUID().uuidString)"
    private var requestSeq = 0
    private var pendingRefresh: DispatchWorkItem?
    private var panelExpiration: DispatchWorkItem?
    private let postCommitPanelTtlSeconds: TimeInterval = 1.15

    override func inputText(_ string: String!, client sender: Any!) -> Bool {
        guard let string, let client = sender as? IMKTextInput else {
            return false
        }

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

        if isPrintableInput(string) {
            if composition.isEmpty && latestDisplayCandidates.isEmpty && isDigit(string) {
                return false
            }
            if latestPredictionSession?.phase == "post_commit" {
                clearCandidateState()
                clearVisiblePredictionPanel()
            }
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
        clearCandidateState()
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
        if RagCandidatePanel.shared.isVisible,
           let number = Int(string),
           number >= 1,
           number <= latestDisplayCandidates.count {
            let candidate = latestDisplayCandidates[number - 1]
            let query = composition.isEmpty ? candidate.text : composition
            commit(text: candidate.insertText, client: client, selectedDisplayCandidate: candidate, selectedSuggestion: nil, rank: number, queryOverride: query)
            return true
        }

        let totalCount = latestModelPredictions.count + latestSuggestions.count
        guard let number = Int(string), number >= 1, number <= totalCount else {
            return false
        }
        let predictionIndex = number - 1
        if predictionIndex < latestModelPredictions.count {
            let prediction = latestModelPredictions[predictionIndex]
            commit(text: prediction.text, client: client, selectedSuggestion: nil, rank: number)
            return true
        }
        let suggestionIndex = predictionIndex - latestModelPredictions.count
        let suggestion = latestSuggestions[suggestionIndex]
        commit(text: suggestion.insertText, client: client, selectedSuggestion: suggestion, rank: number)
        return true
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
        pendingRefresh?.cancel()
        panelExpiration?.cancel()
        RagCandidatePanel.shared.hide()

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

    private func cancelCurrentComposition(client: IMKTextInput) {
        composition = ""
        clearCandidateState()
        pendingRefresh?.cancel()
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
                    guard self.composition == inputSnapshot, self.committedContext == contextSnapshot else {
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
                    guard self.composition.isEmpty, self.committedContext == contextSnapshot else {
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
        latestPredictionSession = response.predictionSession
        if response.predictionSession?.shouldClearPredictionPanel == true || response.displayCandidates.isEmpty {
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
                let query = self.composition.isEmpty ? response.semanticQuery : self.composition
                self.commit(text: candidate.insertText, client: client, selectedDisplayCandidate: candidate, selectedSuggestion: nil, rank: index + 1, queryOverride: query)
            }
        )
        if postCommit || response.predictionSession?.phase == "post_commit" {
            schedulePanelExpiration(expectedContext: committedContext)
        }
    }

    private func schedulePanelExpiration(expectedContext: String) {
        panelExpiration?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            guard self.composition.isEmpty, self.committedContext == expectedContext else {
                return
            }
            self.clearCandidateState()
            self.clearVisiblePredictionPanel()
        }
        panelExpiration = work
        DispatchQueue.main.asyncAfter(deadline: .now() + postCommitPanelTtlSeconds, execute: work)
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
        RimeSidecarRequest(
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
            rimeContext: RimeContextPayload(candidates: [], highlightedIndex: 0, page: 0, isLastPage: true)
        )
    }

    private func nextRequestSeq() -> Int {
        requestSeq += 1
        return requestSeq
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
        RagCandidatePanel.shared.hide()
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
        let fallbackRange = NSRange(location: max(0, composition.utf16.count), length: 0)
        let range = selectedRange.location == NSNotFound ? fallbackRange : selectedRange
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
}
