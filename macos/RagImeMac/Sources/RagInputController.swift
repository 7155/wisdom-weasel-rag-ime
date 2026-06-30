import AppKit
import InputMethodKit

@objc(RagInputController)
final class RagInputController: IMKInputController {
    private var composition = ""
    private var latestModelPredictions: [ModelPrediction] = []
    private var latestSuggestions: [RagSuggestion] = []
    private let bridge = RagBridgeClient()
    private var pendingRefresh: DispatchWorkItem?

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
        latestModelPredictions.map(\.text) + latestSuggestions.map(\.surfaceText)
    }

    override func hidePalettes() {
        RagCandidatePanel.shared.hide()
    }

    private func isPrintableInput(_ string: String) -> Bool {
        guard string.count == 1, let scalar = string.unicodeScalars.first else {
            return false
        }
        return !CharacterSet.controlCharacters.contains(scalar)
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

    private func commit(text: String, client: IMKTextInput, selectedSuggestion: RagSuggestion?, rank: Int?) {
        let finalText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !finalText.isEmpty else {
            cancelCurrentComposition(client: client)
            return
        }

        client.insertText(finalText, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        let query = composition
        composition = ""
        latestModelPredictions = []
        latestSuggestions = []
        pendingRefresh?.cancel()
        RagCandidatePanel.shared.hide()

        let bridge = self.bridge
        DispatchQueue.global(qos: .utility).async {
            if let selectedSuggestion {
                _ = try? bridge.apply(actionType: "accepted", suggestion: selectedSuggestion, query: query)
            }
            try? bridge.recordCommit(text: finalText, recentContext: query, preedit: query, source: "macos_inputmethod")
        }
    }

    private func cancelCurrentComposition(client: IMKTextInput) {
        composition = ""
        latestModelPredictions = []
        latestSuggestions = []
        pendingRefresh?.cancel()
        client.setMarkedText(
            "",
            selectionRange: NSRange(location: 0, length: 0),
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound)
        )
        RagCandidatePanel.shared.hide()
    }

    private func scheduleSuggestionRefresh(client providedClient: IMKTextInput? = nil) {
        pendingRefresh?.cancel()
        let inputSnapshot = composition
        guard inputSnapshot.count >= 2 else {
            latestModelPredictions = []
            latestSuggestions = []
            RagCandidatePanel.shared.hide()
            return
        }

        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            do {
                let response = try self.bridge.suggest(currentInput: inputSnapshot)
                DispatchQueue.main.async { [weak self] in
                    guard let self else {
                        return
                    }
                    guard self.composition == inputSnapshot else {
                        return
                    }
                    let visiblePredictions = Array((response.modelPredictions ?? []).prefix(3))
                    let visibleSuggestions = Array(response.suggestions.prefix(3))
                    self.latestModelPredictions = visiblePredictions
                    self.latestSuggestions = visibleSuggestions
                    if visiblePredictions.isEmpty && visibleSuggestions.isEmpty {
                        RagCandidatePanel.shared.hide()
                        return
                    }
                    let anchor = self.panelAnchor(client: providedClient ?? self.client())
                    RagCandidatePanel.shared.show(
                        modelPredictions: visiblePredictions,
                        suggestions: visibleSuggestions,
                        currentInput: inputSnapshot,
                        anchor: anchor,
                        onSelectModel: { [weak self] prediction, index in
                            guard let self, let client = self.client() else {
                                return
                            }
                            self.commit(text: prediction.text, client: client, selectedSuggestion: nil, rank: index + 1)
                        },
                        onSelect: { [weak self] suggestion, index in
                            guard let self, let client = self.client() else {
                                return
                            }
                            self.commit(text: suggestion.insertText, client: client, selectedSuggestion: suggestion, rank: visiblePredictions.count + index + 1)
                        },
                        onAction: { [weak self] action, suggestion in
                            self?.handlePanelAction(action, suggestion: suggestion, query: inputSnapshot)
                        }
                    )
                }
            } catch {
                DispatchQueue.main.async { [weak self] in
                    self?.latestModelPredictions = []
                    self?.latestSuggestions = []
                    RagCandidatePanel.shared.hide()
                }
                NSLog("RAG IME suggest failed: \(error.localizedDescription)")
            }
        }
        pendingRefresh = work
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 0.18, execute: work)
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
