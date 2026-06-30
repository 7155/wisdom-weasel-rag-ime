import AppKit
import InputMethodKit

@objc(RagInputController)
final class RagInputController: IMKInputController {
    private var composition = ""
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
            scheduleSuggestionRefresh()
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
        latestSuggestions.map(\.surfaceText)
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
        guard let number = Int(string), number >= 1, number <= latestSuggestions.count else {
            return false
        }
        let suggestion = latestSuggestions[number - 1]
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
        latestSuggestions = []
        pendingRefresh?.cancel()
        client.setMarkedText(
            "",
            selectionRange: NSRange(location: 0, length: 0),
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound)
        )
        RagCandidatePanel.shared.hide()
    }

    private func scheduleSuggestionRefresh() {
        pendingRefresh?.cancel()
        let inputSnapshot = composition
        guard inputSnapshot.count >= 2 else {
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
                    self.latestSuggestions = response.suggestions
                    RagCandidatePanel.shared.show(
                        suggestions: response.suggestions,
                        currentInput: inputSnapshot,
                        onSelect: { [weak self] suggestion, index in
                            guard let self, let client = self.client() else {
                                return
                            }
                            self.commit(text: suggestion.insertText, client: client, selectedSuggestion: suggestion, rank: index + 1)
                        },
                        onAction: { [weak self] action, suggestion in
                            self?.handlePanelAction(action, suggestion: suggestion, query: inputSnapshot)
                        }
                    )
                }
            } catch {
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
}
