import AppKit
import QuartzCore

enum RagImeAssistantTypography {
  static let defaultCandidateSize: CGFloat = 14
  static let source = NSFont.systemFont(ofSize: 11, weight: .semibold)
  static let shortcut = NSFont.systemFont(ofSize: 11, weight: .medium)
  static let action = NSFont.systemFont(ofSize: 12.5, weight: .medium)
  static let status = NSFont.systemFont(ofSize: 14, weight: .medium)
  static let diagnostic = NSFont.systemFont(ofSize: 11.5, weight: .regular)
  static let resultHeader = NSFont.systemFont(ofSize: 12.5, weight: .semibold)
  static let resultBody = NSFont.systemFont(ofSize: 14, weight: .regular)
  static let confirmation = NSFont.systemFont(ofSize: 13.5, weight: .medium)

  static func candidate(pointSize: CGFloat = defaultCandidateSize, primary: Bool) -> NSFont {
    .systemFont(ofSize: pointSize, weight: primary ? .medium : .regular)
  }

  static func resultParagraphStyle() -> NSParagraphStyle {
    let style = NSMutableParagraphStyle()
    style.lineSpacing = 4
    style.paragraphSpacing = 0
    return style
  }

  static func resultAttributes() -> [NSAttributedString.Key: Any] {
    [
      .font: resultBody,
      .foregroundColor: NSColor.labelColor,
      .paragraphStyle: resultParagraphStyle(),
    ]
  }
}

enum RagImeAssistantAction {
  case stop
  case close
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
  static let compactHeight: CGFloat = 38
  static let pendingHeight: CGFloat = 44
  static let thinkingHeight: CGFloat = 64
  static let errorHeight: CGFloat = 82
  static let rowHeight: CGFloat = 44
  static let actionHeight: CGFloat = 40
  static let maximumPredictionCandidates = 4
  static let minimumPredictionWidth: CGFloat = 320
  static let preferredPredictionWidth: CGFloat = 392
  static let maximumPredictionWidth: CGFloat = 460
  static let minimumExplicitResultHeight: CGFloat = 176
  static let maximumExplicitResultHeight: CGFloat = 300
  static let explicitResultChromeHeight: CGFloat = 112
  static let explicitResultBodyBottom: CGFloat = 48
  static let explicitResultDiagnosticBottomInset: CGFloat = 54

  private let rows = (0..<RagImeSuggestionCardView.maximumPredictionCandidates).map {
    _ in RagImeSuggestionRowView(frame: .zero)
  }
  private let stateTint = NSView()
  private let accentRail = NSView()
  private let actionSeparator = NSView()
  private let deepSeekButton = NSButton(title: "生成", target: nil, action: nil)
  private let deepSeekShortcutPlate = NSView()
  private let deepSeekShortcutLabel = NSTextField(labelWithString: "⌃.")
  private let statusHalo = NSView()
  private let statusIcon = NSTextField(labelWithString: "✦")
  private let statusLabel = NSTextField(labelWithString: "正在生成...")
  private let diagnosticLabel = NSTextField(labelWithString: "")
  private let stopButton = NSButton(title: "", target: nil, action: nil)
  private let closeButton = NSButton(title: "", target: nil, action: nil)
  private let resultHeader = NSTextField(labelWithString: "已生成")
  private let resultShortcutPlate = NSView()
  private let resultShortcutLabel = NSTextField(labelWithString: "Tab 插入")
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
  private var isStreamingResult = false
  private var contentSignature = ""
  private var candidateFontSize = RagImeAssistantTypography.defaultCandidateSize
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
    stateTint.wantsLayer = true
    stateTint.layer?.backgroundColor = NSColor.clear.cgColor
    stateTint.autoresizingMask = [.width, .height]
    addSubview(stateTint, positioned: .below, relativeTo: nil)
    accentRail.wantsLayer = true
    accentRail.layer?.cornerRadius = 1.5
    accentRail.isHidden = true
    addSubview(accentRail)
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
    deepSeekButton.font = RagImeAssistantTypography.action
    deepSeekButton.alignment = .left
    deepSeekButton.image = NSImage(systemSymbolName: "bolt.horizontal.fill", accessibilityDescription: "知识生成")
    deepSeekButton.imagePosition = .imageLeading
    deepSeekButton.contentTintColor = .systemIndigo
    deepSeekButton.target = self
    deepSeekButton.action = #selector(startActiveRag)
    deepSeekButton.toolTip = "用当前上下文和检索证据生成内容"
    deepSeekButton.setAccessibilityLabel("生成长文本")
    deepSeekShortcutLabel.font = RagImeAssistantTypography.shortcut
    deepSeekShortcutLabel.textColor = .tertiaryLabelColor
    deepSeekShortcutLabel.alignment = .right
    deepSeekShortcutPlate.wantsLayer = true
    deepSeekShortcutPlate.layer?.cornerRadius = 5
    deepSeekShortcutPlate.layer?.borderWidth = 0.5
    deepSeekShortcutPlate.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.58).cgColor
    deepSeekShortcutPlate.layer?.backgroundColor = NSColor.systemIndigo.withAlphaComponent(0.05).cgColor
    [actionSeparator, deepSeekButton, deepSeekShortcutPlate, deepSeekShortcutLabel].forEach(addSubview)
    statusHalo.wantsLayer = true
    statusHalo.layer?.cornerRadius = 12
    statusHalo.layer?.backgroundColor = NSColor.controlAccentColor.withAlphaComponent(0.10).cgColor
    statusIcon.font = .systemFont(ofSize: 13, weight: .semibold)
    statusIcon.textColor = .systemIndigo
    statusIcon.alignment = .center
    statusLabel.font = RagImeAssistantTypography.status
    statusLabel.textColor = .labelColor
    diagnosticLabel.font = RagImeAssistantTypography.diagnostic
    diagnosticLabel.textColor = .secondaryLabelColor
    diagnosticLabel.lineBreakMode = .byTruncatingTail
    resultHeader.font = RagImeAssistantTypography.resultHeader
    resultHeader.textColor = .secondaryLabelColor
    resultShortcutLabel.font = RagImeAssistantTypography.shortcut
    resultShortcutLabel.textColor = .controlAccentColor
    resultShortcutLabel.alignment = .center
    resultShortcutLabel.toolTip = "结果就绪后按 Tab 插入"
    resultShortcutPlate.wantsLayer = true
    resultShortcutPlate.layer?.cornerRadius = 5
    resultShortcutPlate.layer?.borderWidth = 0.5
    resultShortcutPlate.layer?.borderColor = NSColor.controlAccentColor.withAlphaComponent(0.42).cgColor
    resultShortcutPlate.layer?.backgroundColor = NSColor.controlAccentColor.withAlphaComponent(0.07).cgColor
    resultText.isEditable = false
    resultText.isSelectable = true
    resultText.drawsBackground = false
    resultText.isHorizontallyResizable = false
    resultText.isVerticallyResizable = true
    resultText.autoresizingMask = [.width]
    resultText.minSize = .zero
    resultText.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
    resultText.font = RagImeAssistantTypography.resultBody
    resultText.textColor = .labelColor
    resultText.textContainerInset = .zero
    resultText.textContainer?.widthTracksTextView = true
    resultText.textContainer?.heightTracksTextView = false
    resultText.defaultParagraphStyle = RagImeAssistantTypography.resultParagraphStyle()
    resultScroll.drawsBackground = false
    resultScroll.hasVerticalScroller = true
    resultScroll.autohidesScrollers = true
    resultScroll.scrollerStyle = .overlay
    resultScroll.documentView = resultText
    configureActionButton(stopButton, action: #selector(stop), symbol: "stop.fill", toolTip: "停止生成")
    configureActionButton(closeButton, action: #selector(close), symbol: "xmark", toolTip: "关闭结果")
    configureActionButton(insertButton, action: #selector(insert), symbol: "arrow.down.to.line", toolTip: "插入到光标")
    configureActionButton(replaceButton, action: #selector(replace), symbol: "arrow.triangle.2.circlepath", toolTip: "替换选中文本")
    configureActionButton(retryButton, action: #selector(retry), symbol: "arrow.clockwise", toolTip: "重新生成")
    configureActionButton(moreButton, action: #selector(more), symbol: "ellipsis", toolTip: "更多操作")
    confirmationLabel.font = RagImeAssistantTypography.confirmation
    confirmationLabel.textColor = .secondaryLabelColor
    confirmationLabel.alignment = .center
    [statusHalo, statusIcon, statusLabel, diagnosticLabel, stopButton, closeButton, resultHeader, resultShortcutPlate, resultShortcutLabel, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach(addSubview)
    hideAll()
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    layer?.borderColor = NSColor.separatorColor.cgColor
    layer?.backgroundColor = NSColor.clear.cgColor
    deepSeekShortcutPlate.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.58).cgColor
    resultShortcutPlate.layer?.borderColor = NSColor.controlAccentColor.withAlphaComponent(0.42).cgColor
    updateThemeChrome(for: surfaceState)
  }

  override func layout() {
    super.layout()
    stateTint.frame = bounds
    accentRail.frame = NSRect(x: 0, y: 8, width: 3, height: max(0, bounds.height - 16))
    switch surfaceState {
    case .pendingPrediction:
      statusHalo.frame = NSRect(x: 12, y: 10, width: 24, height: 24)
      statusIcon.frame = NSRect(x: 15, y: 12, width: 18, height: 18)
      statusLabel.frame = NSRect(x: 44, y: 10, width: max(80, bounds.width - 96), height: 24)
      deepSeekButton.frame = NSRect(x: bounds.width - 42, y: 7, width: 32, height: 30)
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
        actionSeparator.frame = NSRect(x: 60, y: Self.actionHeight - 1, width: max(0, bounds.width - 72), height: 1)
        deepSeekShortcutPlate.frame = NSRect(x: 12, y: 8, width: 38, height: 24)
        deepSeekShortcutLabel.frame = NSRect(x: 14, y: 10, width: 34, height: 20)
        deepSeekButton.frame = NSRect(x: 60, y: 5, width: max(76, bounds.width - 72), height: 30)
      }
    case .explicitGenerating:
      statusHalo.frame = NSRect(x: 8, y: 18, width: 28, height: 28)
      statusIcon.frame = NSRect(x: 13, y: 23, width: 18, height: 18)
      stopButton.frame = NSRect(x: 41, y: 17, width: 30, height: 30)
    case .explicitError:
      statusHalo.frame = NSRect(x: 12, y: 43, width: 26, height: 26)
      statusIcon.frame = NSRect(x: 16, y: 47, width: 18, height: 18)
      statusLabel.frame = NSRect(x: 46, y: 44, width: max(60, bounds.width - 92), height: 24)
      diagnosticLabel.frame = NSRect(x: 46, y: 24, width: max(60, bounds.width - 60), height: 18)
      retryButton.frame = NSRect(x: 40, y: 2, width: 64, height: 26)
      closeButton.frame = NSRect(x: bounds.width - 38, y: 42, width: 30, height: 30)
    case .explicitResult:
      let headerX: CGFloat = isStreamingResult ? 14 : 98
      resultHeader.frame = NSRect(x: headerX, y: bounds.height - 31, width: max(80, bounds.width - headerX - 46), height: 19)
      resultShortcutPlate.frame = NSRect(x: 14, y: bounds.height - 36, width: 74, height: 24)
      resultShortcutLabel.frame = NSRect(x: 18, y: bounds.height - 34, width: 66, height: 20)
      closeButton.frame = NSRect(x: bounds.width - 38, y: bounds.height - 39, width: 30, height: 30)
      diagnosticLabel.frame = NSRect(
        x: 14,
        y: bounds.height - Self.explicitResultDiagnosticBottomInset,
        width: bounds.width - 28,
        height: 18
      )
      resultScroll.frame = NSRect(
        x: 14,
        y: Self.explicitResultBodyBottom,
        width: bounds.width - 28,
        height: max(48, bounds.height - Self.explicitResultChromeHeight)
      )
      layoutResultText()
      if isStreamingResult {
        stopButton.frame = NSRect(x: 10, y: 8, width: 32, height: 30)
      } else {
        insertButton.frame = NSRect(x: 10, y: 8, width: 60, height: 30)
        replaceButton.frame = NSRect(x: 74, y: 8, width: 60, height: 30)
        retryButton.frame = NSRect(x: canReplaceSelection ? 138 : 74, y: 8, width: 60, height: 30)
        moreButton.frame = NSRect(x: bounds.width - 50, y: 8, width: 40, height: 30)
      }
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
    updateThemeChrome(for: state)
    self.canReplaceSelection = canReplaceSelection
    let indexedCandidates = Array(payload.candidates.enumerated())
    let realCandidates = indexedCandidates
      .filter { Self.isRealCandidate($0.element) }
      .prefix(Self.maximumPredictionCandidates)
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
    isStreamingResult = false
    diagnosticLabel.stringValue = diagnosticText(for: payload)
    hideAll()
    switch state {
    case .pendingPrediction:
      statusIcon.stringValue = "✦"
      statusIcon.textColor = .controlAccentColor
      statusLabel.stringValue = payload.statusText.isEmpty ? "正在联想" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel].forEach { $0.isHidden = false }
      deepSeekButton.imagePosition = .imageOnly
      deepSeekButton.isHidden = actionCandidate == nil
    case .compactPrediction, .expandedPredictions:
      deepSeekButton.imagePosition = .imageLeading
      let visibleCount = min(Self.maximumPredictionCandidates, candidates.count)
      for index in rows.indices where index < visibleCount {
        let shortcut = index == 0 ? "Tab" : "⌥\(index + 1)"
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
      statusIcon.stringValue = "✦"
      statusIcon.textColor = .systemIndigo
      statusLabel.stringValue = payload.statusText.isEmpty ? "正在生成..." : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, stopButton].forEach { $0.isHidden = false }
      toolTip = "\(statusLabel.stringValue)；点击停止"
      setAccessibilityLabel(statusLabel.stringValue)
    case .explicitError:
      statusIcon.stringValue = "!"
      statusIcon.textColor = .systemOrange
      statusLabel.stringValue = payload.statusText.isEmpty ? "生成失败，请重试" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel, diagnosticLabel, retryButton, closeButton].forEach { $0.isHidden = false }
    case .explicitResult:
      let streaming = candidates.first.map { candidate in
        if case .bool(let value)? = candidate.metadata["streamingPartial"] { return value }
        return false
      } ?? false
      isStreamingResult = streaming
      [resultHeader, diagnosticLabel, resultScroll].forEach { $0.isHidden = false }
      if streaming {
        stopButton.isHidden = false
      } else {
        [resultShortcutPlate, resultShortcutLabel, closeButton, insertButton, retryButton, moreButton].forEach { $0.isHidden = false }
        replaceButton.isHidden = !canReplaceSelection
        replaceButton.isEnabled = canReplaceSelection
      }
      resultHeader.stringValue = streaming ? "✦ 正在生成" : "✦ 已生成"
      let result = candidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
      resultText.textStorage?.setAttributedString(
        NSAttributedString(string: result, attributes: RagImeAssistantTypography.resultAttributes())
      )
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
    guard surfaceState == .pendingPrediction || surfaceState == .explicitGenerating else { return }
    let frames = reduceMotion ? ["✦"] : ["✦", "✧", "✦", "·"]
    statusIcon.stringValue = frames[frame % frames.count]
  }

  func setGeneratingPulse(active: Bool, reduceMotion: Bool) {
    statusIcon.wantsLayer = true
    statusIcon.layer?.removeAnimation(forKey: "rag-ime-thinking-pulse")
    statusHalo.layer?.removeAnimation(forKey: "rag-ime-companion-breathe")
    guard active, !reduceMotion else { return }
    let pulse = CABasicAnimation(keyPath: "opacity")
    pulse.fromValue = 0.45
    pulse.toValue = 1
    pulse.duration = 0.65
    pulse.autoreverses = true
    pulse.repeatCount = .infinity
    pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
    statusIcon.layer?.add(pulse, forKey: "rag-ime-thinking-pulse")
    let breathe = CABasicAnimation(keyPath: "transform.scale")
    breathe.fromValue = 0.92
    breathe.toValue = 1.06
    breathe.duration = 0.8
    breathe.autoreverses = true
    breathe.repeatCount = .infinity
    breathe.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
    statusHalo.layer?.add(breathe, forKey: "rag-ime-companion-breathe")
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
    rowHeight * CGFloat(max(0, min(maximumPredictionCandidates, candidateCount)))
      + (hasAction ? actionHeight : 0)
  }

  static func explicitResultHeight(text: String, width: CGFloat) -> CGFloat {
    let measured = (text as NSString).boundingRect(
      with: NSSize(width: max(240, width - 28), height: CGFloat.greatestFiniteMagnitude),
      options: [.usesLineFragmentOrigin, .usesFontLeading],
      attributes: RagImeAssistantTypography.resultAttributes()
    )
    return min(
      maximumExplicitResultHeight,
      max(minimumExplicitResultHeight, ceil(measured.height) + explicitResultChromeHeight)
    )
  }

  private func hideAll() {
    rows.forEach {
      $0.isHidden = true
      $0.showsSeparator = false
    }
    [actionSeparator, deepSeekButton, deepSeekShortcutPlate, deepSeekShortcutLabel].forEach { $0.isHidden = true }
    [statusHalo, statusIcon, statusLabel, diagnosticLabel, stopButton, closeButton, resultHeader, resultShortcutPlate, resultShortcutLabel, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach { $0.isHidden = true }
  }

  private func updateThemeChrome(for state: RagImeAssistantSurfaceState) {
    let tint: NSColor
    let rail: NSColor
    switch state {
    case .explicitGenerating:
      tint = NSColor.systemIndigo.withAlphaComponent(0.035)
      rail = .systemIndigo
      statusHalo.layer?.backgroundColor = NSColor.systemIndigo.withAlphaComponent(0.11).cgColor
    case .explicitError:
      tint = NSColor.systemOrange.withAlphaComponent(0.045)
      rail = .systemOrange
      statusHalo.layer?.backgroundColor = NSColor.systemOrange.withAlphaComponent(0.12).cgColor
    case .explicitResult:
      tint = NSColor.systemTeal.withAlphaComponent(0.025)
      rail = .systemTeal
      statusHalo.layer?.backgroundColor = NSColor.systemTeal.withAlphaComponent(0.10).cgColor
    default:
      tint = .clear
      rail = .clear
      statusHalo.layer?.backgroundColor = NSColor.controlAccentColor.withAlphaComponent(0.10).cgColor
    }
    stateTint.layer?.backgroundColor = tint.cgColor
    accentRail.layer?.backgroundColor = rail.withAlphaComponent(0.82).cgColor
    accentRail.isHidden = !state.isExplicit
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

    let contextChars = intValue(in: [transaction, metadata], keys: ["effectiveContextChars", "contextChars", "selectedTextChars"])
    let foregroundChars = intValue(in: [transaction, metadata], keys: ["foregroundContextChars"])
    let recentInputChars = intValue(in: [transaction, metadata], keys: ["timelineRecentInputChars"])
    let recentInputUsed = boolValue(in: [transaction, metadata], keys: ["timelineRecentInputUsedForGeneration"])
    let evidenceCount = intValue(in: [transaction, metadata], keys: ["evidenceCount", "retrievedCount"])
      ?? (payload.sourceCards.isEmpty ? nil : payload.sourceCards.count)
    let retrievalAttempted = boolValue(in: [transaction, metadata], keys: ["retrievalAttempted"])
    let remoteReady = boolValue(in: [transaction, metadata], keys: ["remoteModelReady"])
    var parts: [String] = []
    if let foregroundChars, foregroundChars > 0 {
      parts.append("当前输入 \(foregroundChars) 字")
    } else if let contextChars, contextChars > 0 {
      parts.append("上下文 \(contextChars) 字")
    } else if boolValue(in: [transaction, metadata], keys: ["contextCaptured"]) == false {
      parts.append("未读取上下文")
    }
    if let recentInputChars, recentInputChars > 0 {
      parts.append(recentInputUsed == true ? "历史补充 \(recentInputChars) 字" : "历史已记录，本次未引用")
    }
    if let evidenceCount, evidenceCount > 0 {
      parts.append("RAG \(evidenceCount) 条")
    } else if retrievalAttempted == true {
      parts.append("未检索到证据")
    }
    if remoteReady == false {
      parts.append("远程模型未启用")
    } else {
      parts.append("知识生成")
    }
    diagnosticLabel.toolTip = stringValue(in: [transaction, metadata], keys: ["contextSource"])
    return parts.joined(separator: " · ")
  }

  private func providerNeutralStatus(_ value: String) -> String {
    var result = value
    for name in ["DeepSeek", "deepseek", "MiniMind", "minimind", "豆包", "Doubao", "doubao", "DS"] {
      result = result.replacingOccurrences(of: name, with: "")
    }
    let compact = result.replacingOccurrences(of: "  ", with: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    return compact.isEmpty ? "正在生成..." : compact
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
    let measured = (resultText.string as NSString).boundingRect(
      with: NSSize(width: width, height: CGFloat.greatestFiniteMagnitude),
      options: [.usesLineFragmentOrigin, .usesFontLeading],
      attributes: RagImeAssistantTypography.resultAttributes()
    )
    resultText.textContainer?.containerSize = NSSize(width: width, height: CGFloat.greatestFiniteMagnitude)
    resultText.frame = NSRect(x: 0, y: 0, width: width, height: max(viewport.height, ceil(measured.height) + 4))
  }

  private func configureActionButton(_ button: NSButton, action: Selector, symbol: String, toolTip: String) {
    button.isBordered = false
    button.font = RagImeAssistantTypography.action
    button.contentTintColor = .controlAccentColor
    button.image = NSImage(systemSymbolName: symbol, accessibilityDescription: toolTip)
    button.imagePosition = button.title.isEmpty ? .imageOnly : .imageLeading
    button.toolTip = toolTip
    button.setAccessibilityLabel(toolTip)
    button.target = self
    button.action = action
  }

  @objc private func stop() { onAction?(.stop) }
  @objc private func close() { onAction?(.close) }
  @objc private func insert() { onAction?(.insert) }
  @objc private func replace() { onAction?(.replace) }
  @objc private func retry() { onAction?(.retry) }
  @objc private func more() { onAction?(.more(moreButton)) }

  @objc private func startActiveRag() {
    guard let actionCandidate, let actionCandidateIndex else { return }
    onSelect?(actionCandidate, actionCandidateIndex, .insert)
  }
}
