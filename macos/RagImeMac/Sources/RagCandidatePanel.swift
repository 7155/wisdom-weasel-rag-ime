import AppKit

final class RagCandidatePanel {
    static let shared = RagCandidatePanel()

    private let panel: NSPanel
    private let contentStack = NSStackView()
    private var sleeves: [ClosureSleeve] = []

    private init() {
        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 260),
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
        backdrop.layer?.cornerRadius = 16
        backdrop.layer?.masksToBounds = true
        backdrop.translatesAutoresizingMaskIntoConstraints = false

        contentStack.orientation = .vertical
        contentStack.alignment = .leading
        contentStack.spacing = 10
        contentStack.edgeInsets = NSEdgeInsets(top: 14, left: 14, bottom: 14, right: 14)
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
        suggestions: [RagSuggestion],
        currentInput: String,
        anchor: NSPoint? = nil,
        onSelect: @escaping (RagSuggestion, Int) -> Void,
        onAction: @escaping (String, RagSuggestion) -> Void
    ) {
        sleeves.removeAll()
        rebuild(suggestions: suggestions, currentInput: currentInput, onSelect: onSelect, onAction: onAction)
        let size = fittingSize(suggestionCount: suggestions.count)
        panel.setContentSize(size)
        positionPanel(anchor: anchor)
        panel.orderFrontRegardless()
    }

    func hide() {
        panel.orderOut(nil)
        sleeves.removeAll()
    }

    private func rebuild(
        suggestions: [RagSuggestion],
        currentInput: String,
        onSelect: @escaping (RagSuggestion, Int) -> Void,
        onAction: @escaping (String, RagSuggestion) -> Void
    ) {
        contentStack.arrangedSubviews.forEach { view in
            contentStack.removeArrangedSubview(view)
            view.removeFromSuperview()
        }

        contentStack.addArrangedSubview(header(currentInput: currentInput, count: suggestions.count))
        if suggestions.isEmpty {
            contentStack.addArrangedSubview(emptyState())
            return
        }

        for (index, suggestion) in suggestions.prefix(5).enumerated() {
            contentStack.addArrangedSubview(candidateRow(suggestion: suggestion, number: index + 1) {
                onSelect(suggestion, index)
            })
        }
        contentStack.addArrangedSubview(evidenceCard(suggestion: suggestions[0], onAction: onAction))
    }

    private func header(currentInput: String, count: Int) -> NSView {
        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false

        let title = NSTextField(labelWithString: "RAG IME")
        title.font = .systemFont(ofSize: 12, weight: .semibold)
        title.textColor = .secondaryLabelColor

        let query = NSTextField(labelWithString: currentInput.isEmpty ? "waiting for input" : currentInput)
        query.font = .systemFont(ofSize: 13, weight: .medium)
        query.textColor = .labelColor
        query.lineBreakMode = .byTruncatingTail
        query.maximumNumberOfLines = 1

        let badge = NSTextField(labelWithString: "\(count) local")
        badge.font = .systemFont(ofSize: 11, weight: .medium)
        badge.textColor = .white
        badge.alignment = .center
        badge.wantsLayer = true
        badge.layer?.cornerRadius = 8
        badge.layer?.backgroundColor = NSColor.systemTeal.cgColor

        stack.addArrangedSubview(title)
        stack.addArrangedSubview(query)
        stack.addArrangedSubview(NSView())
        stack.addArrangedSubview(badge)
        badge.widthAnchor.constraint(greaterThanOrEqualToConstant: 54).isActive = true
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
        button.layer?.cornerRadius = 9
        button.layer?.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(number == 1 ? 0.28 : 0.14).cgColor

        let sleeve = ClosureSleeve(action)
        sleeves.append(sleeve)
        button.target = sleeve
        button.action = #selector(ClosureSleeve.invoke)

        let label = NSMutableAttributedString()
        label.append(NSAttributedString(
            string: "\(number) ",
            attributes: [.foregroundColor: NSColor.systemTeal, .font: NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .semibold)]
        ))
        label.append(NSAttributedString(
            string: suggestion.surfaceText,
            attributes: [.foregroundColor: NSColor.labelColor, .font: NSFont.systemFont(ofSize: 15, weight: .medium)]
        ))
        label.append(NSAttributedString(
            string: "  \(suggestion.suggestionType)",
            attributes: [.foregroundColor: NSColor.secondaryLabelColor, .font: NSFont.systemFont(ofSize: 11, weight: .regular)]
        ))
        button.attributedTitle = label
        button.heightAnchor.constraint(equalToConstant: 34).isActive = true
        button.widthAnchor.constraint(equalToConstant: 612).isActive = true
        return button
    }

    private func evidenceCard(suggestion: RagSuggestion, onAction: @escaping (String, RagSuggestion) -> Void) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.wantsLayer = true
        stack.layer?.cornerRadius = 12
        stack.layer?.backgroundColor = NSColor.textBackgroundColor.withAlphaComponent(0.22).cgColor

        let preview = NSTextField(wrappingLabelWithString: suggestion.evidencePreview)
        preview.font = .systemFont(ofSize: 12, weight: .regular)
        preview.textColor = .labelColor
        preview.maximumNumberOfLines = 3

        let meta = NSTextField(labelWithString: "confidence \(String(format: "%.2f", suggestion.confidence))  memory \(suggestion.memoryId)")
        meta.font = .monospacedDigitSystemFont(ofSize: 10, weight: .regular)
        meta.textColor = .secondaryLabelColor

        let actions = NSStackView()
        actions.orientation = .horizontal
        actions.spacing = 6
        for action in ["pin", "downrank", "delete", "expand"] where suggestion.actions.contains(action) {
            actions.addArrangedSubview(actionButton(title: action, suggestion: suggestion, onAction: onAction))
        }

        stack.addArrangedSubview(preview)
        stack.addArrangedSubview(meta)
        stack.addArrangedSubview(actions)
        stack.widthAnchor.constraint(equalToConstant: 612).isActive = true
        return stack
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
        label.font = .systemFont(ofSize: 13, weight: .regular)
        label.textColor = .secondaryLabelColor
        label.widthAnchor.constraint(equalToConstant: 612).isActive = true
        return label
    }

    private func fittingSize(suggestionCount: Int) -> NSSize {
        let rowHeight = max(1, min(5, suggestionCount)) * 44
        return NSSize(width: 640, height: CGFloat(126 + rowHeight))
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
