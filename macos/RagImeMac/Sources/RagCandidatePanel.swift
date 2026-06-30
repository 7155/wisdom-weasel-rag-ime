import AppKit

final class RagCandidatePanel {
    static let shared = RagCandidatePanel()

    private let panel: NSPanel
    private let contentStack = NSStackView()
    private var sleeves: [ClosureSleeve] = []

    private init() {
        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 170),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isReleasedWhenClosed = false
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hasShadow = true
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]

        let backdrop = NSVisualEffectView()
        backdrop.material = .hudWindow
        backdrop.blendingMode = .behindWindow
        backdrop.state = .active
        backdrop.wantsLayer = true
        backdrop.layer?.cornerRadius = 10
        backdrop.layer?.masksToBounds = true
        backdrop.translatesAutoresizingMaskIntoConstraints = false

        contentStack.orientation = .vertical
        contentStack.alignment = .leading
        contentStack.spacing = 6
        contentStack.edgeInsets = NSEdgeInsets(top: 8, left: 10, bottom: 9, right: 10)
        contentStack.translatesAutoresizingMaskIntoConstraints = false

        backdrop.addSubview(contentStack)
        panel.contentView = backdrop
        NSLayoutConstraint.activate([
            contentStack.leadingAnchor.constraint(equalTo: backdrop.leadingAnchor),
            contentStack.trailingAnchor.constraint(equalTo: backdrop.trailingAnchor),
            contentStack.topAnchor.constraint(equalTo: backdrop.topAnchor),
            contentStack.bottomAnchor.constraint(equalTo: backdrop.bottomAnchor),
        ])
    }

    func show(
        modelPredictions: [ModelPrediction] = [],
        suggestions: [RagSuggestion],
        currentInput: String,
        anchor: NSPoint? = nil,
        onSelectModel: @escaping (ModelPrediction, Int) -> Void = { _, _ in },
        onSelect: @escaping (RagSuggestion, Int) -> Void,
        onAction: @escaping (String, RagSuggestion) -> Void
    ) {
        sleeves.removeAll()
        rebuild(
            modelPredictions: modelPredictions,
            suggestions: suggestions,
            currentInput: currentInput,
            onSelectModel: onSelectModel,
            onSelect: onSelect,
            onAction: onAction
        )
        let size = fittingSize(predictionCount: modelPredictions.count, suggestionCount: suggestions.count)
        panel.setContentSize(size)
        positionPanel(anchor: anchor)
        panel.orderFrontRegardless()
    }

    func hide() {
        panel.orderOut(nil)
        sleeves.removeAll()
    }

    private func rebuild(
        modelPredictions: [ModelPrediction],
        suggestions: [RagSuggestion],
        currentInput: String,
        onSelectModel: @escaping (ModelPrediction, Int) -> Void,
        onSelect: @escaping (RagSuggestion, Int) -> Void,
        onAction: @escaping (String, RagSuggestion) -> Void
    ) {
        contentStack.arrangedSubviews.forEach { view in
            contentStack.removeArrangedSubview(view)
            view.removeFromSuperview()
        }

        let visiblePredictions = Array(modelPredictions.prefix(3))
        let visibleSuggestions = Array(suggestions.prefix(3))
        let totalCount = visiblePredictions.count + visibleSuggestions.count

        contentStack.addArrangedSubview(header(currentInput: currentInput, count: totalCount))
        if !visiblePredictions.isEmpty {
            contentStack.addArrangedSubview(modelPredictionRow(predictions: visiblePredictions) { prediction, index in
                onSelectModel(prediction, index)
            })
        }

        if visibleSuggestions.isEmpty {
            if visiblePredictions.isEmpty {
                contentStack.addArrangedSubview(emptyState())
            }
            return
        }

        let numberOffset = visiblePredictions.count
        for (index, suggestion) in visibleSuggestions.enumerated() {
            contentStack.addArrangedSubview(candidateRow(suggestion: suggestion, number: numberOffset + index + 1) {
                onSelect(suggestion, index)
            })
        }
        contentStack.addArrangedSubview(evidenceCard(suggestion: visibleSuggestions[0], onAction: onAction))
    }

    private func header(currentInput: String, count: Int) -> NSView {
        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false

        let title = NSTextField(labelWithString: "RAG")
        title.font = .systemFont(ofSize: 11, weight: .semibold)
        title.textColor = .secondaryLabelColor

        let query = NSTextField(labelWithString: currentInput.isEmpty ? "waiting for input" : currentInput)
        query.font = .systemFont(ofSize: 12, weight: .medium)
        query.textColor = .labelColor
        query.lineBreakMode = .byTruncatingTail
        query.maximumNumberOfLines = 1

        let badge = NSTextField(labelWithString: "\(min(count, 6))")
        badge.font = .systemFont(ofSize: 10, weight: .semibold)
        badge.textColor = .white
        badge.alignment = .center
        badge.wantsLayer = true
        badge.layer?.cornerRadius = 6
        badge.layer?.backgroundColor = NSColor.systemBlue.cgColor

        stack.addArrangedSubview(title)
        stack.addArrangedSubview(query)
        stack.addArrangedSubview(NSView())
        stack.addArrangedSubview(badge)
        badge.widthAnchor.constraint(greaterThanOrEqualToConstant: 24).isActive = true
        return stack
    }

    private func modelPredictionRow(
        predictions: [ModelPrediction],
        onSelect: @escaping (ModelPrediction, Int) -> Void
    ) -> NSView {
        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 6
        stack.translatesAutoresizingMaskIntoConstraints = false

        let visible = Array(predictions.prefix(3))
        let width = (438 - CGFloat(max(0, visible.count - 1)) * 6) / CGFloat(max(1, visible.count))
        for (index, prediction) in visible.enumerated() {
            let button = NSButton()
            button.isBordered = false
            button.alignment = .left
            button.setButtonType(.momentaryChange)
            button.translatesAutoresizingMaskIntoConstraints = false
            button.wantsLayer = true
            button.layer?.cornerRadius = 6
            button.layer?.backgroundColor = NSColor.systemBlue.withAlphaComponent(index == 0 ? 0.22 : 0.14).cgColor
            button.cell?.lineBreakMode = .byTruncatingTail

            let sleeve = ClosureSleeve { onSelect(prediction, index) }
            sleeves.append(sleeve)
            button.target = sleeve
            button.action = #selector(ClosureSleeve.invoke)

            let label = NSMutableAttributedString()
            label.append(NSAttributedString(
                string: "\(index + 1) ",
                attributes: [.foregroundColor: NSColor.systemBlue, .font: NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .semibold)]
            ))
            label.append(NSAttributedString(
                string: prediction.text,
                attributes: [.foregroundColor: NSColor.labelColor, .font: NSFont.systemFont(ofSize: 12, weight: .medium)]
            ))
            button.attributedTitle = label
            button.heightAnchor.constraint(equalToConstant: 26).isActive = true
            button.widthAnchor.constraint(equalToConstant: width).isActive = true
            stack.addArrangedSubview(button)
        }
        stack.widthAnchor.constraint(equalToConstant: 438).isActive = true
        return stack
    }

    private func candidateRow(suggestion: RagSuggestion, number: Int, action: @escaping () -> Void) -> NSView {
        let button = NSButton()
        button.isBordered = false
        button.alignment = .left
        button.bezelStyle = .regularSquare
        button.setButtonType(.momentaryChange)
        button.translatesAutoresizingMaskIntoConstraints = false
        button.wantsLayer = true
        button.layer?.cornerRadius = 6
        button.layer?.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(number == 1 ? 0.24 : 0.12).cgColor

        let sleeve = ClosureSleeve(action)
        sleeves.append(sleeve)
        button.target = sleeve
        button.action = #selector(ClosureSleeve.invoke)

        let label = NSMutableAttributedString()
        label.append(NSAttributedString(
            string: "\(number) ",
            attributes: [.foregroundColor: NSColor.systemBlue, .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)]
        ))
        label.append(NSAttributedString(
            string: suggestion.surfaceText,
            attributes: [.foregroundColor: NSColor.labelColor, .font: NSFont.systemFont(ofSize: 13, weight: .medium)]
        ))
        button.attributedTitle = label
        button.heightAnchor.constraint(equalToConstant: 28).isActive = true
        button.widthAnchor.constraint(equalToConstant: 438).isActive = true
        return button
    }

    private func evidenceCard(suggestion: RagSuggestion, onAction _: @escaping (String, RagSuggestion) -> Void) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 4
        stack.edgeInsets = NSEdgeInsets(top: 7, left: 8, bottom: 7, right: 8)
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.wantsLayer = true
        stack.layer?.cornerRadius = 7
        stack.layer?.backgroundColor = NSColor.textBackgroundColor.withAlphaComponent(0.16).cgColor

        let meta = NSTextField(labelWithString: sourceHint(for: suggestion))
        meta.font = .monospacedDigitSystemFont(ofSize: 9, weight: .regular)
        meta.textColor = .secondaryLabelColor

        let preview = NSTextField(wrappingLabelWithString: suggestion.evidencePreview)
        preview.font = .systemFont(ofSize: 11, weight: .regular)
        preview.textColor = .secondaryLabelColor
        preview.maximumNumberOfLines = 1
        preview.lineBreakMode = .byTruncatingTail

        stack.addArrangedSubview(meta)
        stack.addArrangedSubview(preview)
        stack.widthAnchor.constraint(equalToConstant: 438).isActive = true
        return stack
    }

    private func sourceHint(for suggestion: RagSuggestion) -> String {
        if case .array(let sources)? = suggestion.metadata["sources"], let first = sources.first {
            if case .string(let value) = first {
                return "RAG · \(value)"
            }
        }
        return "RAG · local memory"
    }

    private func actionButton(title: String, suggestion: RagSuggestion, onAction: @escaping (String, RagSuggestion) -> Void) -> NSButton {
        let button = NSButton(title: title, target: nil, action: nil)
        button.bezelStyle = .rounded
        button.controlSize = .small
        button.font = .systemFont(ofSize: 11, weight: .medium)
        let sleeve = ClosureSleeve { onAction(title, suggestion) }
        sleeves.append(sleeve)
        button.target = sleeve
        button.action = #selector(ClosureSleeve.invoke)
        return button
    }

    private func emptyState() -> NSView {
        let label = NSTextField(wrappingLabelWithString: "No local memory matched. Keep typing or commit text to build the local memory base.")
        label.font = .systemFont(ofSize: 12, weight: .regular)
        label.textColor = .secondaryLabelColor
        label.widthAnchor.constraint(equalToConstant: 438).isActive = true
        return label
    }

    private func fittingSize(predictionCount: Int, suggestionCount: Int) -> NSSize {
        let predictionHeight = predictionCount > 0 ? 32 : 0
        let visibleRows = suggestionCount > 0 ? min(3, suggestionCount) : 0
        let rowHeight = visibleRows * 34
        let emptyHeight = predictionCount == 0 && suggestionCount == 0 ? 34 : 0
        let previewHeight = suggestionCount > 0 ? 45 : 0
        return NSSize(width: 460, height: CGFloat(42 + predictionHeight + rowHeight + emptyHeight + previewHeight))
    }

    private func positionPanel(anchor: NSPoint?) {
        let point = anchor ?? NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(point, $0.frame, false) } ?? NSScreen.main
        let visible = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        let x = min(max(point.x, visible.minX + 16), visible.maxX - panel.frame.width - 16)
        let y = min(max(point.y - 28, visible.minY + panel.frame.height + 16), visible.maxY - 16)
        panel.setFrameTopLeftPoint(NSPoint(x: x, y: y))
    }
}

private final class ClosureSleeve: NSObject {
    private let closure: () -> Void

    init(_ closure: @escaping () -> Void) {
        self.closure = closure
    }

    @objc func invoke() {
        closure()
    }
}
