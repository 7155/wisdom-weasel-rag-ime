import AppKit

enum RagImeAssistantAction {
  case stop
  case insert
  case replace
  case retry
  case more(NSView)
}

final class RagImeSuggestionCardView: NSView {
  static let compactHeight: CGFloat = 40
  static let thinkingHeight: CGFloat = 44
  static let rowHeight: CGFloat = 40

  private let rows = (0..<3).map { _ in RagImeSuggestionRowView(frame: .zero) }
  private let statusIcon = NSTextField(labelWithString: "◌")
  private let statusLabel = NSTextField(labelWithString: "正在生成...")
  private let stopButton = NSButton(title: "■", target: nil, action: nil)
  private let resultHeader = NSTextField(labelWithString: "已生成")
  private let resultScroll = NSScrollView()
  private let resultText = NSTextView()
  private let insertButton = NSButton(title: "插入", target: nil, action: nil)
  private let replaceButton = NSButton(title: "替换", target: nil, action: nil)
  private let retryButton = NSButton(title: "重试", target: nil, action: nil)
  private let moreButton = NSButton(title: "•••", target: nil, action: nil)
  private let confirmationLabel = NSTextField(labelWithString: "✓ 已插入")
  private(set) var state: RagImeAssistantSurfaceState = .hidden
  private var candidates: [RagImeDisplayCandidate] = []
  var onSelect: ((RagImeDisplayCandidate, Int) -> Void)?
  var onAction: ((RagImeAssistantAction) -> Void)?

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    wantsLayer = true
    layer?.cornerRadius = 10
    layer?.borderWidth = NSWorkspace.shared.accessibilityDisplayShouldIncreaseContrast ? 1 : 0.5
    layer?.borderColor = NSColor.separatorColor.cgColor
    layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
    layer?.masksToBounds = true
    for (index, row) in rows.enumerated() {
      row.onSelect = { [weak self] candidate in self?.onSelect?(candidate, index) }
      addSubview(row)
    }
    statusIcon.font = .systemFont(ofSize: 15, weight: .medium)
    statusIcon.textColor = .controlAccentColor
    statusLabel.font = .systemFont(ofSize: 13, weight: .medium)
    statusLabel.textColor = .labelColor
    resultHeader.font = .systemFont(ofSize: 12, weight: .semibold)
    resultHeader.textColor = .secondaryLabelColor
    resultText.isEditable = false
    resultText.isSelectable = true
    resultText.drawsBackground = false
    resultText.font = .systemFont(ofSize: 13.5)
    resultText.textColor = .labelColor
    resultText.textContainerInset = .zero
    resultScroll.drawsBackground = false
    resultScroll.hasVerticalScroller = true
    resultScroll.autohidesScrollers = true
    resultScroll.documentView = resultText
    configureActionButton(stopButton, action: #selector(stop))
    configureActionButton(insertButton, action: #selector(insert))
    configureActionButton(replaceButton, action: #selector(replace))
    configureActionButton(retryButton, action: #selector(retry))
    configureActionButton(moreButton, action: #selector(more))
    confirmationLabel.font = .systemFont(ofSize: 13, weight: .medium)
    confirmationLabel.textColor = .secondaryLabelColor
    confirmationLabel.alignment = .center
    [statusIcon, statusLabel, stopButton, resultHeader, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach(addSubview)
    hideAll()
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    layer?.borderColor = NSColor.separatorColor.cgColor
    layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
  }

  override func layout() {
    super.layout()
    switch state {
    case .compactPrediction, .expandedPredictions:
      for (index, row) in rows.enumerated() {
        row.frame = NSRect(x: 0, y: bounds.height - CGFloat(index + 1) * Self.rowHeight, width: bounds.width, height: Self.rowHeight)
      }
    case .explicitGenerating:
      statusIcon.frame = NSRect(x: 13, y: 13, width: 20, height: 18)
      statusLabel.frame = NSRect(x: 40, y: 11, width: max(60, bounds.width - 88), height: 22)
      stopButton.frame = NSRect(x: bounds.width - 42, y: 7, width: 32, height: 30)
    case .explicitResult:
      resultHeader.frame = NSRect(x: 12, y: bounds.height - 30, width: bounds.width - 24, height: 18)
      resultScroll.frame = NSRect(x: 12, y: 40, width: bounds.width - 24, height: max(38, bounds.height - 74))
      insertButton.frame = NSRect(x: 8, y: 6, width: 48, height: 28)
      replaceButton.frame = NSRect(x: 60, y: 6, width: 48, height: 28)
      retryButton.frame = NSRect(x: 112, y: 6, width: 48, height: 28)
      moreButton.frame = NSRect(x: bounds.width - 48, y: 6, width: 40, height: 28)
    case .transientConfirmation: confirmationLabel.frame = bounds
    case .hidden: break
    }
  }

  func apply(state: RagImeAssistantSurfaceState, payload: RagImeAssistantOverlayPayload) {
    self.state = state
    candidates = payload.candidates.filter(Self.isRealCandidate).prefix(3).map { $0 }
    hideAll()
    switch state {
    case .compactPrediction, .expandedPredictions:
      let visibleCount = state == .compactPrediction ? min(1, candidates.count) : candidates.count
      for index in rows.indices where index < visibleCount {
        rows[index].apply(candidate: candidates[index], shortcut: index == 0 ? "Tab" : "⌥\(index + 1)")
        rows[index].isHidden = false
      }
    case .explicitGenerating:
      [statusIcon, statusLabel, stopButton].forEach { $0.isHidden = false }
    case .explicitResult:
      [resultHeader, resultScroll, insertButton, replaceButton, retryButton, moreButton].forEach { $0.isHidden = false }
      resultText.string = candidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
    case .transientConfirmation: confirmationLabel.isHidden = false
    case .hidden: break
    }
    needsLayout = true
  }

  func updateGeneratingFrame(_ frame: Int, reduceMotion: Bool) {
    guard state == .explicitGenerating else { return }
    let frames = reduceMotion ? ["◌"] : ["◜", "◝", "◞", "◟"]
    statusIcon.stringValue = frames[frame % frames.count]
  }

  static func isRealCandidate(_ candidate: RagImeDisplayCandidate) -> Bool {
    ["model", "rag", "memory"].contains(candidate.sourceType)
      && candidate.isStatus != true
      && !candidate.insertText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }

  private func hideAll() {
    rows.forEach { $0.isHidden = true }
    [statusIcon, statusLabel, stopButton, resultHeader, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach { $0.isHidden = true }
  }

  private func configureActionButton(_ button: NSButton, action: Selector) {
    button.isBordered = false
    button.font = .systemFont(ofSize: 12, weight: .medium)
    button.contentTintColor = .controlAccentColor
    button.target = self
    button.action = action
  }

  @objc private func stop() { onAction?(.stop) }
  @objc private func insert() { onAction?(.insert) }
  @objc private func replace() { onAction?(.replace) }
  @objc private func retry() { onAction?(.retry) }
  @objc private func more() { onAction?(.more(moreButton)) }
}
