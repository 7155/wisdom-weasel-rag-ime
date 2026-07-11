import AppKit
import QuartzCore

enum RagImeAssistantAction {
  case stop
  case insert
  case replace
  case remember
  case suppress
  case retry
  case more(NSView)
}

enum RagImeAssistantCommitMode: Equatable {
  case insert
  case replace
}

final class RagImeSuggestionCardView: NSVisualEffectView {
  static let compactHeight: CGFloat = 34
  static let thinkingHeight: CGFloat = 52
  static let rowHeight: CGFloat = 36
  static let actionHeight: CGFloat = 31
  static let minimumPredictionWidth: CGFloat = 304
  static let preferredPredictionWidth: CGFloat = 360
  static let maximumPredictionWidth: CGFloat = 420

  private let rows = (0..<3).map { _ in RagImeSuggestionRowView(frame: .zero) }
  private let actionSeparator = NSView()
  private let deepSeekButton = NSButton(title: "DS · 深度补全", target: nil, action: nil)
  private let deepSeekShortcutPlate = NSView()
  private let deepSeekShortcutLabel = NSTextField(labelWithString: "⌃.")
  private let statusIcon = NSTextField(labelWithString: "◌")
  private let statusLabel = NSTextField(labelWithString: "DeepSeek 正在生成...")
  private let diagnosticLabel = NSTextField(labelWithString: "")
  private let stopButton = NSButton(title: "", target: nil, action: nil)
  private let resultHeader = NSTextField(labelWithString: "DS · 已生成")
  private let resultScroll = NSScrollView()
  private let resultText = NSTextView()
  private let insertButton = NSButton(title: "插入", target: nil, action: nil)
  private let replaceButton = NSButton(title: "替换", target: nil, action: nil)
  private let retryButton = NSButton(title: "重试", target: nil, action: nil)
  private let moreButton = NSButton(title: "", target: nil, action: nil)
  private let confirmationLabel = NSTextField(labelWithString: "✓ 已插入")
  private(set) var surfaceState: RagImeAssistantSurfaceState = .hidden
  private var candidates: [RagImeDisplayCandidate] = []
  private var candidateIndexes: [Int] = []
  private var actionCandidate: RagImeDisplayCandidate?
  private var actionCandidateIndex: Int?
  private var canReplaceSelection = false
  private var contentSignature = ""
  private var candidateFontSize: CGFloat = 14
  var onSelect: ((RagImeDisplayCandidate, Int, RagImeAssistantCommitMode) -> Void)?
  var onAction: ((RagImeAssistantAction) -> Void)?
  var diagnosticStatusText: String { diagnosticLabel.stringValue }

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    material = .popover
    blendingMode = .behindWindow
    state = .active
    wantsLayer = true
    layer?.cornerRadius = 8
    layer?.borderWidth = NSWorkspace.shared.accessibilityDisplayShouldIncreaseContrast ? 1 : 0.5
    layer?.borderColor = NSColor.separatorColor.cgColor
    layer?.backgroundColor = NSColor.clear.cgColor
    layer?.masksToBounds = true
    for (index, row) in rows.enumerated() {
      row.onSelect = { [weak self] candidate in
        guard let self, index < self.candidateIndexes.count else { return }
        self.onSelect?(candidate, self.candidateIndexes[index], .insert)
      }
      addSubview(row)
    }
    actionSeparator.wantsLayer = true
    actionSeparator.layer?.backgroundColor = NSColor.separatorColor.withAlphaComponent(0.42).cgColor
    deepSeekButton.isBordered = false
    deepSeekButton.focusRingType = .none
    deepSeekButton.font = .systemFont(ofSize: 11.5, weight: .medium)
    deepSeekButton.alignment = .left
    deepSeekButton.image = NSImage(systemSymbolName: "bolt.horizontal.fill", accessibilityDescription: "DeepSeek")
    deepSeekButton.imagePosition = .imageLeading
    deepSeekButton.contentTintColor = .systemIndigo
    deepSeekButton.target = self
    deepSeekButton.action = #selector(startActiveRag)
    deepSeekButton.toolTip = "用当前上下文和 RAG 证据调用 DeepSeek"
    deepSeekShortcutLabel.font = .systemFont(ofSize: 10.5, weight: .medium)
    deepSeekShortcutLabel.textColor = .tertiaryLabelColor
    deepSeekShortcutLabel.alignment = .right
    deepSeekShortcutPlate.wantsLayer = true
    deepSeekShortcutPlate.layer?.cornerRadius = 5
    deepSeekShortcutPlate.layer?.borderWidth = 0.5
    deepSeekShortcutPlate.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.58).cgColor
    deepSeekShortcutPlate.layer?.backgroundColor = NSColor.systemIndigo.withAlphaComponent(0.05).cgColor
    [actionSeparator, deepSeekButton, deepSeekShortcutPlate, deepSeekShortcutLabel].forEach(addSubview)
    statusIcon.font = .systemFont(ofSize: 15, weight: .medium)
    statusIcon.textColor = .systemIndigo
    statusLabel.font = .systemFont(ofSize: 13, weight: .medium)
    statusLabel.textColor = .labelColor
    diagnosticLabel.font = .systemFont(ofSize: 10.5, weight: .regular)
    diagnosticLabel.textColor = .secondaryLabelColor
    diagnosticLabel.lineBreakMode = .byTruncatingTail
    resultHeader.font = .systemFont(ofSize: 12, weight: .semibold)
    resultHeader.textColor = .secondaryLabelColor
    resultText.isEditable = false
    resultText.isSelectable = true
    resultText.drawsBackground = false
    resultText.isHorizontallyResizable = false
    resultText.isVerticallyResizable = true
    resultText.autoresizingMask = [.width]
    resultText.minSize = .zero
    resultText.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
    resultText.font = .systemFont(ofSize: 13.5)
    resultText.textColor = .labelColor
    resultText.textContainerInset = .zero
    resultText.textContainer?.widthTracksTextView = true
    resultText.textContainer?.heightTracksTextView = false
    let paragraph = NSMutableParagraphStyle()
    paragraph.lineSpacing = 3
    resultText.defaultParagraphStyle = paragraph
    resultScroll.drawsBackground = false
    resultScroll.hasVerticalScroller = true
    resultScroll.autohidesScrollers = true
    resultScroll.documentView = resultText
    configureActionButton(stopButton, action: #selector(stop), symbol: "stop.fill", toolTip: "停止生成")
    configureActionButton(insertButton, action: #selector(insert), symbol: "arrow.down.to.line", toolTip: "插入到光标")
    configureActionButton(replaceButton, action: #selector(replace), symbol: "arrow.triangle.2.circlepath", toolTip: "替换选中文本")
    configureActionButton(retryButton, action: #selector(retry), symbol: "arrow.clockwise", toolTip: "重新生成")
    configureActionButton(moreButton, action: #selector(more), symbol: "ellipsis", toolTip: "更多操作")
    confirmationLabel.font = .systemFont(ofSize: 13, weight: .medium)
    confirmationLabel.textColor = .secondaryLabelColor
    confirmationLabel.alignment = .center
    [statusIcon, statusLabel, diagnosticLabel, stopButton, resultHeader, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach(addSubview)
    hideAll()
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    layer?.borderColor = NSColor.separatorColor.cgColor
    layer?.backgroundColor = NSColor.clear.cgColor
    deepSeekShortcutPlate.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.58).cgColor
  }

  override func layout() {
    super.layout()
    switch surfaceState {
    case .compactPrediction, .expandedPredictions:
      let actionOffset = actionCandidate == nil ? 0 : Self.actionHeight
      for (index, row) in rows.enumerated() {
        row.frame = NSRect(
          x: 0,
          y: actionOffset + CGFloat(max(0, candidates.count - index - 1)) * Self.rowHeight,
          width: bounds.width,
          height: Self.rowHeight
        )
      }
      if actionCandidate != nil {
        actionSeparator.frame = NSRect(x: 76, y: Self.actionHeight - 1, width: max(0, bounds.width - 88), height: 1)
        deepSeekButton.frame = NSRect(x: 11, y: 2, width: max(120, bounds.width - 70), height: 27)
        deepSeekShortcutPlate.frame = NSRect(x: bounds.width - 50, y: 5, width: 38, height: 22)
        deepSeekShortcutLabel.frame = NSRect(x: bounds.width - 46, y: 7, width: 30, height: 18)
      }
    case .explicitGenerating:
      statusIcon.frame = NSRect(x: 11, y: 27, width: 18, height: 18)
      statusLabel.frame = NSRect(x: 36, y: 25, width: max(60, bounds.width - 76), height: 22)
      diagnosticLabel.frame = NSRect(x: 36, y: 7, width: max(60, bounds.width - 48), height: 16)
      stopButton.frame = NSRect(x: bounds.width - 35, y: 20, width: 30, height: 30)
    case .explicitResult:
      resultHeader.frame = NSRect(x: 12, y: bounds.height - 30, width: bounds.width - 24, height: 18)
      diagnosticLabel.frame = NSRect(x: 12, y: bounds.height - 49, width: bounds.width - 24, height: 16)
      resultScroll.frame = NSRect(x: 12, y: 40, width: bounds.width - 24, height: max(38, bounds.height - 92))
      layoutResultText()
      insertButton.frame = NSRect(x: 8, y: 6, width: 58, height: 28)
      replaceButton.frame = NSRect(x: 70, y: 6, width: 58, height: 28)
      retryButton.frame = NSRect(x: canReplaceSelection ? 132 : 70, y: 6, width: 58, height: 28)
      moreButton.frame = NSRect(x: bounds.width - 48, y: 6, width: 40, height: 28)
    case .transientConfirmation: confirmationLabel.frame = bounds
    case .hidden: break
    }
  }

  @discardableResult
  func apply(
    state: RagImeAssistantSurfaceState,
    payload: RagImeAssistantOverlayPayload,
    canReplaceSelection: Bool = false,
    animationsEnabled: Bool = true
  ) -> Bool {
    surfaceState = state
    self.canReplaceSelection = canReplaceSelection
    let indexedCandidates = Array(payload.candidates.enumerated())
    let realCandidates = indexedCandidates.filter { Self.isRealCandidate($0.element) }.prefix(3)
    candidates = realCandidates.map(\.element)
    candidateIndexes = realCandidates.map(\.offset)
    if let action = indexedCandidates.first(where: { Self.isActionCandidate($0.element) }) {
      actionCandidateIndex = action.offset
      actionCandidate = action.element
    } else {
      actionCandidateIndex = nil
      actionCandidate = nil
    }
    let nextSignature = ([state.rawValue, payload.snapshotId] + candidates.map {
      $0.candidateStableId ?? "\($0.sourceType):\($0.insertText)"
    }).joined(separator: "|")
    let contentChanged = nextSignature != contentSignature
    contentSignature = nextSignature
    let reduceMotion = !animationsEnabled || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    diagnosticLabel.stringValue = diagnosticText(for: payload)
    hideAll()
    switch state {
    case .compactPrediction, .expandedPredictions:
      let visibleCount = min(3, candidates.count)
      for index in rows.indices where index < visibleCount {
        let shortcut = index == 0 ? "Tab   ⌥1" : "⌥\(index + 1)"
        rows[index].apply(candidate: candidates[index], shortcut: shortcut, isPrimary: index == 0)
        rows[index].showsSeparator = index < visibleCount - 1
        rows[index].isHidden = false
        if contentChanged {
          rows[index].animateContentIn(delay: TimeInterval(index) * 0.025, reduceMotion: reduceMotion)
        }
      }
      if actionCandidate != nil {
        [actionSeparator, deepSeekButton, deepSeekShortcutPlate, deepSeekShortcutLabel].forEach { $0.isHidden = false }
      }
    case .explicitGenerating:
      statusLabel.stringValue = payload.statusText.isEmpty ? "DeepSeek 正在生成..." : payload.statusText
      [statusIcon, statusLabel, diagnosticLabel, stopButton].forEach { $0.isHidden = false }
    case .explicitResult:
      [resultHeader, diagnosticLabel, resultScroll, insertButton, retryButton, moreButton].forEach { $0.isHidden = false }
      replaceButton.isHidden = !canReplaceSelection
      replaceButton.isEnabled = canReplaceSelection
      let streaming = candidates.first.map { candidate in
        if case .bool(let value)? = candidate.metadata["streamingPartial"] { return value }
        return false
      } ?? false
      resultHeader.stringValue = streaming ? "DS · 生成中" : "DS · 已生成"
      resultText.string = candidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
      if contentChanged { animateExplicitResultIn(reduceMotion: reduceMotion) }
    case .transientConfirmation: confirmationLabel.isHidden = false
    case .hidden: break
    }
    needsLayout = true
    return contentChanged && !reduceMotion
  }

  func applyConfiguration(candidateFontSize: CGFloat) {
    let clamped = min(max(candidateFontSize, 11), 18)
    guard abs(clamped - self.candidateFontSize) > 0.01 else { return }
    self.candidateFontSize = clamped
    rows.forEach { $0.applyCandidateFontSize(clamped) }
  }

  func updateGeneratingFrame(_ frame: Int, reduceMotion: Bool) {
    guard surfaceState == .explicitGenerating else { return }
    let frames = reduceMotion ? ["◌"] : ["◜", "◝", "◞", "◟"]
    statusIcon.stringValue = frames[frame % frames.count]
  }

  func setGeneratingPulse(active: Bool, reduceMotion: Bool) {
    statusIcon.wantsLayer = true
    statusIcon.layer?.removeAnimation(forKey: "rag-ime-thinking-pulse")
    guard active, !reduceMotion else { return }
    let pulse = CABasicAnimation(keyPath: "opacity")
    pulse.fromValue = 0.45
    pulse.toValue = 1
    pulse.duration = 0.65
    pulse.autoreverses = true
    pulse.repeatCount = .infinity
    pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
    statusIcon.layer?.add(pulse, forKey: "rag-ime-thinking-pulse")
  }

  func animateAccepted(reduceMotion: Bool) {
    rows.filter { !$0.isHidden }.forEach { $0.animateAccepted(reduceMotion: reduceMotion) }
  }

  static func isRealCandidate(_ candidate: RagImeDisplayCandidate) -> Bool {
    ["model", "rag", "memory", "deepseek", "ds"].contains(candidate.sourceType)
      && candidate.isStatus != true
      && !candidate.insertText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }

  static func isActionCandidate(_ candidate: RagImeDisplayCandidate) -> Bool {
    candidate.sourceType == "action" || candidate.selectionAction == "start_active_rag_from_context"
  }

  static func predictionHeight(candidateCount: Int, hasAction: Bool) -> CGFloat {
    rowHeight * CGFloat(max(0, min(3, candidateCount))) + (hasAction ? actionHeight : 0)
  }

  private func hideAll() {
    rows.forEach {
      $0.isHidden = true
      $0.showsSeparator = false
    }
    [actionSeparator, deepSeekButton, deepSeekShortcutPlate, deepSeekShortcutLabel].forEach { $0.isHidden = true }
    [statusIcon, statusLabel, diagnosticLabel, stopButton, resultHeader, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach { $0.isHidden = true }
  }

  private func diagnosticText(for payload: RagImeAssistantOverlayPayload) -> String {
    guard payload.phase == "active_rag" || payload.uiMode.contains("active_rag") else { return "" }
    let transaction = payload.frontendTransaction ?? [:]
    let metadata = candidates.first?.metadata ?? [:]
    let status = stringValue(in: [transaction, metadata], keys: ["diagnosticStatus", "captureFailureReason", "remoteModelReason"])
    if status.contains("remote_model_disabled") || status.contains("credentials_missing") || status.contains("provider_unavailable") {
      return "远程模型未启用"
    }
    if status.contains("context_missing") || status.contains("capture_failed") {
      return "未读取上下文"
    }

    let contextChars = intValue(in: [transaction, metadata], keys: ["contextChars", "selectedTextChars"])
    let evidenceCount = intValue(in: [transaction, metadata], keys: ["evidenceCount", "retrievedCount"])
      ?? (payload.sourceCards.isEmpty ? nil : payload.sourceCards.count)
    let retrievalAttempted = boolValue(in: [transaction, metadata], keys: ["retrievalAttempted"])
    let remoteReady = boolValue(in: [transaction, metadata], keys: ["remoteModelReady"])
    var parts: [String] = []
    if let contextChars, contextChars > 0 {
      parts.append("上下文 \(contextChars) 字")
    } else if boolValue(in: [transaction, metadata], keys: ["contextCaptured"]) == false {
      parts.append("未读取上下文")
    }
    if let evidenceCount, evidenceCount > 0 {
      parts.append("RAG \(evidenceCount) 条")
    } else if retrievalAttempted == true {
      parts.append("未检索到证据")
    }
    if remoteReady == false {
      parts.append("远程模型未启用")
    } else {
      parts.append("DeepSeek")
    }
    diagnosticLabel.toolTip = stringValue(in: [transaction, metadata], keys: ["contextSource"])
    return parts.joined(separator: " · ")
  }

  private func stringValue(in maps: [[String: RagImeJSONValue]], keys: [String]) -> String {
    for map in maps {
      for key in keys {
        if case .string(let value)? = map[key], !value.isEmpty { return value }
      }
    }
    return ""
  }

  private func intValue(in maps: [[String: RagImeJSONValue]], keys: [String]) -> Int? {
    for map in maps {
      for key in keys {
        if case .number(let value)? = map[key] { return Int(value) }
      }
    }
    return nil
  }

  private func boolValue(in maps: [[String: RagImeJSONValue]], keys: [String]) -> Bool? {
    for map in maps {
      for key in keys {
        if case .bool(let value)? = map[key] { return value }
      }
    }
    return nil
  }

  private func animateExplicitResultIn(reduceMotion: Bool) {
    resultScroll.wantsLayer = true
    resultScroll.layer?.removeAnimation(forKey: "rag-ime-explicit-result-in")
    guard !reduceMotion else { return }
    let opacity = CABasicAnimation(keyPath: "opacity")
    opacity.fromValue = 0
    opacity.toValue = 1
    let translation = CABasicAnimation(keyPath: "transform.translation.y")
    translation.fromValue = 3
    translation.toValue = 0
    let group = CAAnimationGroup()
    group.animations = [opacity, translation]
    group.duration = 0.15
    group.timingFunction = CAMediaTimingFunction(name: .easeOut)
    resultScroll.layer?.add(group, forKey: "rag-ime-explicit-result-in")
  }

  private func layoutResultText() {
    let viewport = resultScroll.contentSize
    let width = max(40, viewport.width)
    let font = resultText.font ?? .systemFont(ofSize: 13.5)
    let measured = (resultText.string as NSString).boundingRect(
      with: NSSize(width: width, height: CGFloat.greatestFiniteMagnitude),
      options: [.usesLineFragmentOrigin, .usesFontLeading],
      attributes: [.font: font]
    )
    resultText.textContainer?.containerSize = NSSize(width: width, height: CGFloat.greatestFiniteMagnitude)
    resultText.frame = NSRect(x: 0, y: 0, width: width, height: max(viewport.height, ceil(measured.height) + 4))
  }

  private func configureActionButton(_ button: NSButton, action: Selector, symbol: String, toolTip: String) {
    button.isBordered = false
    button.font = .systemFont(ofSize: 12, weight: .medium)
    button.contentTintColor = .controlAccentColor
    button.image = NSImage(systemSymbolName: symbol, accessibilityDescription: toolTip)
    button.imagePosition = button.title.isEmpty ? .imageOnly : .imageLeading
    button.toolTip = toolTip
    button.setAccessibilityLabel(toolTip)
    button.target = self
    button.action = action
  }

  @objc private func stop() { onAction?(.stop) }
  @objc private func insert() { onAction?(.insert) }
  @objc private func replace() { onAction?(.replace) }
  @objc private func retry() { onAction?(.retry) }
  @objc private func more() { onAction?(.more(moreButton)) }

  @objc private func startActiveRag() {
    guard let actionCandidate, let actionCandidateIndex else { return }
    onSelect?(actionCandidate, actionCandidateIndex, .insert)
  }
}
