import AppKit

final class RagImeSuggestionRowView: NSView {
  private let badgeView = NSTextField(labelWithString: "")
  private let candidateLabel = NSTextField(labelWithString: "")
  private let shortcutLabel = NSTextField(labelWithString: "")
  private let hitButton = NSButton()
  private var candidate: RagImeDisplayCandidate?
  var onSelect: ((RagImeDisplayCandidate) -> Void)?

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    wantsLayer = true
    badgeView.alignment = .center
    badgeView.font = .systemFont(ofSize: 10, weight: .semibold)
    badgeView.textColor = .white
    badgeView.wantsLayer = true
    badgeView.layer?.cornerRadius = 5
    badgeView.layer?.masksToBounds = true
    candidateLabel.font = .systemFont(ofSize: 13.5)
    candidateLabel.textColor = .labelColor
    candidateLabel.lineBreakMode = .byTruncatingTail
    candidateLabel.maximumNumberOfLines = 1
    shortcutLabel.font = .monospacedSystemFont(ofSize: 11, weight: .medium)
    shortcutLabel.textColor = .tertiaryLabelColor
    shortcutLabel.alignment = .right
    hitButton.isBordered = false
    hitButton.title = ""
    hitButton.target = self
    hitButton.action = #selector(selectCandidate)
    [badgeView, candidateLabel, shortcutLabel, hitButton].forEach(addSubview)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func layout() {
    super.layout()
    badgeView.frame = NSRect(x: 12, y: 11, width: 18, height: 18)
    shortcutLabel.frame = NSRect(x: bounds.width - 48, y: 11, width: 36, height: 18)
    candidateLabel.frame = NSRect(x: 40, y: 9, width: max(40, bounds.width - 94), height: 22)
    hitButton.frame = bounds
  }

  func apply(candidate: RagImeDisplayCandidate, shortcut: String) {
    self.candidate = candidate
    let text = candidate.text.trimmingCharacters(in: .whitespacesAndNewlines)
    candidateLabel.stringValue = text.isEmpty ? candidate.insertText : text
    badgeView.stringValue = sourceBadge(for: candidate)
    badgeView.layer?.backgroundColor = sourceColor(for: candidate).cgColor
    shortcutLabel.stringValue = shortcut
    toolTip = candidate.evidencePreview.isEmpty ? nil : candidate.evidencePreview
  }

  @objc private func selectCandidate() {
    guard let candidate else { return }
    onSelect?(candidate)
  }

  private func sourceBadge(for candidate: RagImeDisplayCandidate) -> String {
    let configured = (candidate.sourceBadge ?? candidate.badge ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if !configured.isEmpty { return String(configured.prefix(1)) }
    switch candidate.sourceType {
    case "model": return "模"
    case "rag": return "查"
    case "memory": return "忆"
    default: return "AI"
    }
  }

  private func sourceColor(for candidate: RagImeDisplayCandidate) -> NSColor {
    switch candidate.sourceType {
    case "rag": return .systemTeal
    case "memory": return .systemPurple
    default: return .systemBlue
    }
  }
}
