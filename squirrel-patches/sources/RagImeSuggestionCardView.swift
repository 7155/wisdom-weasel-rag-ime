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
  static let inspectorTitle = NSFont.systemFont(ofSize: 15, weight: .semibold)
  static let inspectorSubtitle = NSFont.systemFont(ofSize: 11.5, weight: .regular)
  static let inspectorSection = NSFont.systemFont(ofSize: 12, weight: .semibold)
  static let inspectorBody = NSFont.systemFont(ofSize: 13.5, weight: .regular)

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

enum RagImeAssistantMetrics {
  static let spacingS: CGFloat = 8
  static let spacingL: CGFloat = 16
  static let minimumHitTarget: CGFloat = 44
  static let panelCornerRadius: CGFloat = 8
  static let inspectorCornerRadius: CGFloat = 10
}

enum RagImeAssistantMarkdownRenderer {
  private static let presentationIntentKey = NSAttributedString.Key("NSPresentationIntent")
  private static let inlinePresentationIntentKey = NSAttributedString.Key("NSInlinePresentationIntent")
  private struct BlockDescriptor {
    let identity: Int
    let headingLevel: Int?
    let isCodeBlock: Bool
    let isBlockQuote: Bool
    let isThematicBreak: Bool
    let listOrdinal: Int?
    let isUnorderedList: Bool
    let listDepth: Int
    let tableRowIdentity: Int?
    let isTableHeader: Bool

    init(intent: PresentationIntent?, fallbackIdentity: Int) {
      identity = intent?.components.first?.identity ?? fallbackIdentity
      var headingLevel: Int?
      var isCodeBlock = false
      var isBlockQuote = false
      var isThematicBreak = false
      var listOrdinal: Int?
      var isUnorderedList = false
      var listDepth = 0
      var tableRowIdentity: Int?
      var isTableHeader = false
      for component in intent?.components ?? [] {
        switch component.kind {
        case .header(let level): headingLevel = level
        case .codeBlock: isCodeBlock = true
        case .blockQuote: isBlockQuote = true
        case .thematicBreak: isThematicBreak = true
        case .listItem(let ordinal): listOrdinal = ordinal
        case .unorderedList:
          isUnorderedList = true
          listDepth += 1
        case .orderedList: listDepth += 1
        case .tableHeaderRow:
          tableRowIdentity = component.identity
          isTableHeader = true
        case .tableRow: tableRowIdentity = component.identity
        default: break
        }
      }
      self.headingLevel = headingLevel
      self.isCodeBlock = isCodeBlock
      self.isBlockQuote = isBlockQuote
      self.isThematicBreak = isThematicBreak
      self.listOrdinal = listOrdinal
      self.isUnorderedList = isUnorderedList
      self.listDepth = listDepth
      self.tableRowIdentity = tableRowIdentity
      self.isTableHeader = isTableHeader
    }

    var prefix: String {
      var value = isBlockQuote ? "▎ " : ""
      guard let listOrdinal else { return value }
      value += String(repeating: "  ", count: max(0, listDepth - 1))
      value += isUnorderedList ? "• " : "\(listOrdinal). "
      return value
    }
  }

  static func render(_ markdown: String) -> NSAttributedString {
    guard !markdown.isEmpty else { return NSAttributedString(string: "") }
    let parsed: AttributedString
    do {
      parsed = try AttributedString(
        markdown: markdown,
        options: .init(
          interpretedSyntax: .full,
          failurePolicy: .returnPartiallyParsedIfPossible
        )
      )
    } catch {
      return NSAttributedString(string: markdown, attributes: RagImeAssistantTypography.resultAttributes())
    }
    let semantic = NSAttributedString(parsed)
    guard semantic.length > 0 else {
      return NSAttributedString(string: markdown, attributes: RagImeAssistantTypography.resultAttributes())
    }

    let result = NSMutableAttributedString(string: "")
    var previousBlockIdentity: Int?
    var previousTableRowIdentity: Int?
    semantic.enumerateAttributes(
      in: NSRange(location: 0, length: semantic.length),
      options: []
    ) { rawAttributes, range, _ in
      let intent = rawAttributes[presentationIntentKey] as? PresentationIntent
      let block = BlockDescriptor(intent: intent, fallbackIdentity: range.location)
      if previousBlockIdentity != block.identity {
        appendBoundary(
          to: result,
          previousTableRowIdentity: previousTableRowIdentity,
          block: block
        )
        if !block.prefix.isEmpty {
          result.append(
            NSAttributedString(
              string: block.prefix,
              attributes: displayAttributes(rawAttributes: [:], block: block, prefix: true)
            )
          )
        }
        previousBlockIdentity = block.identity
        previousTableRowIdentity = block.tableRowIdentity
      }
      let fragment = semantic.attributedSubstring(from: range).string
      result.append(
        NSAttributedString(
          string: fragment,
          attributes: displayAttributes(rawAttributes: rawAttributes, block: block, prefix: false)
        )
      )
    }
    return result
  }

  private static func appendBoundary(
    to result: NSMutableAttributedString,
    previousTableRowIdentity: Int?,
    block: BlockDescriptor
  ) {
    guard result.length > 0 else { return }
    let sameTableRow = block.tableRowIdentity != nil
      && block.tableRowIdentity == previousTableRowIdentity
    let separator = sameTableRow ? "  |  " : (result.string.hasSuffix("\n") ? "" : "\n")
    guard !separator.isEmpty else { return }
    result.append(
      NSAttributedString(
        string: separator,
        attributes: RagImeAssistantTypography.resultAttributes()
      )
    )
  }

  private static func displayAttributes(
    rawAttributes: [NSAttributedString.Key: Any],
    block: BlockDescriptor,
    prefix: Bool
  ) -> [NSAttributedString.Key: Any] {
    let inlineRaw = (rawAttributes[inlinePresentationIntentKey] as? NSNumber)?.intValue ?? 0
    let inlineIntent = InlinePresentationIntent(rawValue: UInt(max(0, inlineRaw)))
    var attributes = RagImeAssistantTypography.resultAttributes()
    attributes[.font] = font(block: block, inlineIntent: inlineIntent)
    attributes[.paragraphStyle] = paragraphStyle(block: block)
    if block.isBlockQuote || prefix {
      attributes[.foregroundColor] = NSColor.secondaryLabelColor
    }
    if block.isThematicBreak {
      attributes[.foregroundColor] = NSColor.tertiaryLabelColor
    }
    if block.isCodeBlock || inlineIntent.contains(.code) {
      attributes[.backgroundColor] = NSColor.quaternaryLabelColor.withAlphaComponent(
        block.isCodeBlock ? 0.34 : 0.24
      )
    }
    if inlineIntent.contains(.strikethrough) {
      attributes[.strikethroughStyle] = NSUnderlineStyle.single.rawValue
    }
    if let link = rawAttributes[.link] {
      attributes[.link] = link
      attributes[.foregroundColor] = NSColor.linkColor
      attributes[.underlineStyle] = NSUnderlineStyle.single.rawValue
    }
    return attributes
  }

  private static func font(
    block: BlockDescriptor,
    inlineIntent: InlinePresentationIntent
  ) -> NSFont {
    let isCode = block.isCodeBlock || inlineIntent.contains(.code)
    let isStrong = inlineIntent.contains(.stronglyEmphasized) || block.isTableHeader
    let base: NSFont
    if isCode {
      base = NSFont.monospacedSystemFont(ofSize: 12.5, weight: isStrong ? .semibold : .regular)
    } else if let level = block.headingLevel {
      let size: CGFloat = level == 1 ? 18 : (level == 2 ? 16 : 14.5)
      base = NSFont.systemFont(ofSize: size, weight: .semibold)
    } else {
      base = NSFont.systemFont(ofSize: 14, weight: isStrong ? .semibold : .regular)
    }
    guard inlineIntent.contains(.emphasized) else { return base }
    return NSFontManager.shared.convert(base, toHaveTrait: .italicFontMask)
  }

  private static func paragraphStyle(block: BlockDescriptor) -> NSParagraphStyle {
    let style = RagImeAssistantTypography.resultParagraphStyle().mutableCopy() as! NSMutableParagraphStyle
    style.paragraphSpacing = 6
    if block.headingLevel != nil {
      style.paragraphSpacingBefore = 5
      style.paragraphSpacing = 4
    }
    if block.listOrdinal != nil {
      let indent = CGFloat(max(1, block.listDepth)) * 16
      style.firstLineHeadIndent = CGFloat(max(0, block.listDepth - 1)) * 16
      style.headIndent = indent
    }
    if block.isBlockQuote {
      style.firstLineHeadIndent += 10
      style.headIndent += 10
    }
    if block.isCodeBlock {
      style.firstLineHeadIndent = 8
      style.headIndent = 8
      style.tailIndent = -8
      style.lineSpacing = 2
      style.paragraphSpacing = 8
    }
    if block.isThematicBreak {
      style.alignment = .center
      style.paragraphSpacing = 8
    }
    return style
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
  static let thinkingHeight: CGFloat = 174
  static let thinkingWidth: CGFloat = 440
  static let errorHeight: CGFloat = 82
  static let rowHeight: CGFloat = 40
  static let actionHeight: CGFloat = 40
  static let maximumPredictionCandidates = 4
  static let minimumPredictionWidth: CGFloat = 196
  static let pendingPredictionWidth: CGFloat = 248
  static let actionPredictionWidth: CGFloat = 264
  static let maximumPredictionWidth: CGFloat = 460
  static let minimumExplicitResultHeight: CGFloat = 176
  static let maximumExplicitResultHeight: CGFloat = 300
  static let explicitResultChromeHeight: CGFloat = 112
  static let explicitResultBodyBottom: CGFloat = 48
  static let explicitResultDiagnosticBottomInset: CGFloat = 54

  struct ResultViewportSnapshot {
    let selectedRange: NSRange
    let scrollOrigin: NSPoint
  }
  private let rows = (0..<RagImeSuggestionCardView.maximumPredictionCandidates).map {
    _ in RagImeSuggestionRowView(frame: .zero)
  }
  private let stateTint = NSView()
  private let accentRail = NSView()
  private let actionSeparator = NSView()
  private let actionContainer = NSView()
  private let actionDividerLeading = NSView()
  private let quickGenerateButton = NSButton(title: "生成", target: nil, action: nil)
  private let deepSearchButton = NSButton(title: "深度", target: nil, action: nil)
  private let statusHalo = NSView()
  private let statusIcon = NSImageView()
  private let statusLabel = NSTextField(labelWithString: "正在生成...")
  private let diagnosticLabel = NSTextField(labelWithString: "")
  private let progressTitleLabel = NSTextField(labelWithString: "正在准备回答")
  private let progressContainer = NSView()
  private let progressRows = (0..<4).map { _ in RagImeGenerationProgressRowView(frame: .zero) }
  private let progressHandoffLabel = NSTextField(labelWithString: "")
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
  private var quickActionCandidate: RagImeDisplayCandidate?
  private var quickActionCandidateIndex: Int?
  private var deepActionCandidate: RagImeDisplayCandidate?
  private var deepActionCandidateIndex: Int?
  private var canReplaceSelection = false
  private var isStreamingResult = false
  private var isProgressHandoffVisible = false
  private var progressSummaryText = ""
  private var pendingResultText = ""
  private var visibleResultMarkdown = ""
  private var resultRevealTimer: Timer?
  private var progressHandoffWorkItem: DispatchWorkItem?
  private var contentSignature = ""
  private var candidateFontSize = RagImeAssistantTypography.defaultCandidateSize
  var onSelect: ((RagImeDisplayCandidate, Int, RagImeAssistantCommitMode) -> Void)?
  var onAction: ((RagImeAssistantAction) -> Void)?
  var diagnosticStatusText: String { diagnosticLabel.stringValue }

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    material = .contentBackground
    blendingMode = .withinWindow
    state = .inactive
    wantsLayer = true
    layer?.cornerRadius = RagImeAssistantMetrics.panelCornerRadius
    layer?.borderWidth = NSWorkspace.shared.accessibilityDisplayShouldIncreaseContrast ? 1 : 0.5
    layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.72).cgColor
    layer?.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(0.96).cgColor
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
    actionContainer.wantsLayer = true
    actionContainer.layer?.cornerRadius = 0
    actionContainer.layer?.masksToBounds = false
    actionDividerLeading.wantsLayer = true
    quickGenerateButton.isBordered = false
    quickGenerateButton.focusRingType = .none
    quickGenerateButton.font = RagImeAssistantTypography.action
    quickGenerateButton.alignment = .left
    quickGenerateButton.image = NSImage(systemSymbolName: "bolt.fill", accessibilityDescription: "文字生成")
    quickGenerateButton.imagePosition = .imageLeading
    quickGenerateButton.contentTintColor = .systemIndigo
    quickGenerateButton.wantsLayer = true
    quickGenerateButton.layer?.cornerRadius = 6
    quickGenerateButton.target = self
    quickGenerateButton.action = #selector(startActiveRag)
    quickGenerateButton.toolTip = "快速生成：结合当前界面与相关记忆生成一次回复"
    quickGenerateButton.setAccessibilityLabel("文字生成")
    deepSearchButton.isBordered = false
    deepSearchButton.focusRingType = .none
    deepSearchButton.font = RagImeAssistantTypography.action
    deepSearchButton.alignment = .center
    deepSearchButton.image = NSImage(systemSymbolName: "sparkles", accessibilityDescription: "深度查找")
    deepSearchButton.imagePosition = .imageLeading
    deepSearchButton.contentTintColor = .systemIndigo
    deepSearchButton.wantsLayer = true
    deepSearchButton.layer?.cornerRadius = 6
    deepSearchButton.target = self
    deepSearchButton.action = #selector(startAgentDeepSearch)
    deepSearchButton.toolTip = "深度查找：在连续会话中分步检索和处理"
    deepSearchButton.setAccessibilityLabel("深度查找")
    updateActionGroupChrome()
    actionContainer.addSubview(quickGenerateButton)
    actionContainer.addSubview(actionDividerLeading)
    actionContainer.addSubview(deepSearchButton)
    [actionSeparator, actionContainer].forEach(addSubview)
    statusHalo.wantsLayer = true
    statusHalo.layer?.backgroundColor = NSColor.clear.cgColor
    statusIcon.imageScaling = .scaleProportionallyDown
    statusLabel.font = RagImeAssistantTypography.status
    statusLabel.textColor = .labelColor
    diagnosticLabel.font = RagImeAssistantTypography.diagnostic
    diagnosticLabel.textColor = .secondaryLabelColor
    diagnosticLabel.lineBreakMode = .byTruncatingTail
    progressTitleLabel.font = RagImeAssistantTypography.resultHeader
    progressTitleLabel.textColor = .labelColor
    progressContainer.wantsLayer = true
    progressContainer.layer?.cornerRadius = 7
    progressContainer.layer?.backgroundColor = NSColor.controlBackgroundColor.withAlphaComponent(0.12).cgColor
    progressRows.forEach(progressContainer.addSubview)
    progressHandoffLabel.font = RagImeAssistantTypography.diagnostic
    progressHandoffLabel.textColor = .secondaryLabelColor
    progressHandoffLabel.lineBreakMode = .byTruncatingTail
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
    resultText.isRichText = true
    resultText.linkTextAttributes = [
      .foregroundColor: NSColor.linkColor,
      .underlineStyle: NSUnderlineStyle.single.rawValue,
    ]
    resultText.textContainer?.lineFragmentPadding = 0
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
    moreButton.identifier = NSUserInterfaceItemIdentifier("ragIme.assistant.more")
    moreButton.toolTip = "更多操作，包括查看输入与依据"
    moreButton.setAccessibilityLabel("更多操作，包括查看输入与依据")
    confirmationLabel.font = RagImeAssistantTypography.confirmation
    confirmationLabel.textColor = .secondaryLabelColor
    confirmationLabel.alignment = .center
    [statusHalo, statusIcon, statusLabel, diagnosticLabel, progressTitleLabel, progressContainer, progressHandoffLabel, stopButton, closeButton, resultHeader, resultShortcutPlate, resultShortcutLabel, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach(addSubview)
    hideAll()
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    layer?.borderColor = NSColor.separatorColor.cgColor
    layer?.backgroundColor = NSColor.clear.cgColor
    resultShortcutPlate.layer?.borderColor = NSColor.controlAccentColor.withAlphaComponent(0.42).cgColor
    updateActionGroupChrome()
    updateThemeChrome(for: surfaceState)
  }

  override func layout() {
    super.layout()
    stateTint.frame = bounds
    accentRail.frame = NSRect(x: 0, y: 8, width: 3, height: max(0, bounds.height - 16))
    switch surfaceState {
    case .pendingPrediction:
      layoutActionBar(frame: NSRect(x: 8, y: 7, width: 108, height: 30), compact: true)
      statusHalo.frame = NSRect(x: 120, y: 4, width: 38, height: 36)
      statusIcon.frame = statusHalo.frame
      statusLabel.frame = NSRect(x: 160, y: 10, width: max(80, bounds.width - 170), height: 24)
    case .compactPrediction, .expandedPredictions:
      let hasAction = quickActionCandidate != nil || deepActionCandidate != nil
      let actionOffset = hasAction ? Self.actionHeight : 0
      let visibleCount = min(Self.maximumPredictionCandidates, candidates.count)
      for (index, row) in rows.enumerated() {
        row.frame = NSRect(
          x: 0,
          y: actionOffset + CGFloat(max(0, visibleCount - index - 1)) * Self.rowHeight,
          width: bounds.width,
          height: Self.rowHeight
        )
      }
      if hasAction {
        actionSeparator.frame = NSRect(x: 12, y: Self.actionHeight - 1, width: max(0, bounds.width - 24), height: 1)
        layoutActionBar(frame: NSRect(x: 12, y: 5, width: max(0, bounds.width - 24), height: 30), compact: false)
      }
    case .explicitGenerating:
      progressTitleLabel.frame = NSRect(x: 16, y: bounds.height - 35, width: max(120, bounds.width - 76), height: 20)
      stopButton.frame = NSRect(
        x: bounds.width - 54,
        y: bounds.height - 50,
        width: RagImeAssistantMetrics.minimumHitTarget,
        height: RagImeAssistantMetrics.minimumHitTarget
      )
      progressContainer.frame = NSRect(x: 12, y: 10, width: max(0, bounds.width - 24), height: bounds.height - 52)
      layoutProgressRows()
    case .explicitNoSuggestion, .explicitError:
      statusHalo.frame = NSRect(x: 7, y: 34, width: 44, height: 42)
      statusIcon.frame = statusHalo.frame
      statusLabel.frame = NSRect(x: 57, y: 44, width: max(60, bounds.width - 103), height: 24)
      diagnosticLabel.frame = NSRect(x: 57, y: 24, width: max(60, bounds.width - 71), height: 18)
      retryButton.frame = NSRect(x: 40, y: 2, width: 64, height: 26)
      closeButton.frame = NSRect(
        x: bounds.width - 52,
        y: bounds.height - 48,
        width: RagImeAssistantMetrics.minimumHitTarget,
        height: RagImeAssistantMetrics.minimumHitTarget
      )
    case .explicitResult:
      let headerX: CGFloat = isStreamingResult ? 14 : 98
      resultHeader.frame = NSRect(x: headerX, y: bounds.height - 31, width: max(80, bounds.width - headerX - 46), height: 19)
      resultShortcutPlate.frame = NSRect(x: 14, y: bounds.height - 36, width: 74, height: 24)
      resultShortcutLabel.frame = NSRect(x: 18, y: bounds.height - 34, width: 66, height: 20)
      closeButton.frame = NSRect(
        x: bounds.width - 52,
        y: bounds.height - 50,
        width: RagImeAssistantMetrics.minimumHitTarget,
        height: RagImeAssistantMetrics.minimumHitTarget
      )
      diagnosticLabel.frame = NSRect(
        x: 14,
        y: bounds.height - Self.explicitResultDiagnosticBottomInset,
        width: bounds.width - 28,
        height: 18
      )
      progressHandoffLabel.frame = NSRect(
        x: 14,
        y: Self.explicitResultBodyBottom,
        width: bounds.width - 28,
        height: 18
      )
      let handoffInset: CGFloat = isProgressHandoffVisible ? 24 : 0
      resultScroll.frame = NSRect(
        x: 14,
        y: Self.explicitResultBodyBottom + handoffInset,
        width: bounds.width - 28,
        height: max(48, bounds.height - Self.explicitResultChromeHeight - handoffInset)
      )
      layoutResultText()
      if isStreamingResult {
        stopButton.frame = NSRect(
          x: 8,
          y: 2,
          width: RagImeAssistantMetrics.minimumHitTarget,
          height: RagImeAssistantMetrics.minimumHitTarget
        )
      } else {
        insertButton.frame = NSRect(x: 8, y: 2, width: 60, height: RagImeAssistantMetrics.minimumHitTarget)
        replaceButton.frame = NSRect(x: 72, y: 2, width: 60, height: RagImeAssistantMetrics.minimumHitTarget)
        retryButton.frame = NSRect(
          x: canReplaceSelection ? 136 : 72,
          y: 2,
          width: 60,
          height: RagImeAssistantMetrics.minimumHitTarget
        )
        moreButton.frame = NSRect(
          x: bounds.width - 52,
          y: 2,
          width: RagImeAssistantMetrics.minimumHitTarget,
          height: RagImeAssistantMetrics.minimumHitTarget
        )
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
    let previousState = surfaceState
    surfaceState = state
    updateThemeChrome(for: state)
    self.canReplaceSelection = canReplaceSelection
    let indexedCandidates = Array(payload.candidates.enumerated())
    let realCandidates = indexedCandidates
      .filter { Self.isRealCandidate($0.element) }
      .prefix(Self.maximumPredictionCandidates)
    candidates = realCandidates.map(\.element)
    candidateIndexes = realCandidates.map(\.offset)
    let quickAction = indexedCandidates.first {
      $0.element.selectionAction == "start_active_rag_from_context"
    }
    quickActionCandidateIndex = quickAction?.offset
    quickActionCandidate = quickAction?.element
    let deepAction = indexedCandidates.first {
      $0.element.selectionAction == "start_agent_deep_search_from_context"
    }
    deepActionCandidateIndex = deepAction?.offset
    deepActionCandidate = deepAction?.element
    quickGenerateButton.isEnabled = quickActionCandidate != nil
    deepSearchButton.isEnabled = deepActionCandidate != nil
    let nextSignature = ([state.rawValue, payload.snapshotId] + candidates.map {
      $0.candidateStableId ?? "\($0.sourceType):\($0.insertText)"
    }).joined(separator: "|")
    let contentChanged = nextSignature != contentSignature
    contentSignature = nextSignature
    let reduceMotion = !animationsEnabled || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    if state != .explicitResult {
      stopResultReveal(reset: true)
      progressHandoffWorkItem?.cancel()
      progressHandoffWorkItem = nil
      isProgressHandoffVisible = false
    }
    isStreamingResult = false
    diagnosticLabel.stringValue = diagnosticText(for: payload)
    hideAll()
    switch state {
    case .pendingPrediction:
      statusIcon.image = companionImage(named: "RagImeCompanionThinking")
      statusLabel.stringValue = payload.statusText.isEmpty ? "正在联想" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel].forEach { $0.isHidden = false }
      quickGenerateButton.imagePosition = .imageOnly
      deepSearchButton.imagePosition = .imageOnly
      actionContainer.isHidden = quickActionCandidate == nil && deepActionCandidate == nil
    case .compactPrediction, .expandedPredictions:
      quickGenerateButton.imagePosition = .imageLeading
      deepSearchButton.imagePosition = .imageLeading
      let visibleCount = min(Self.maximumPredictionCandidates, candidates.count)
      for index in rows.indices where index < visibleCount {
        let shortcut = index == 0 ? "Tab" : "⌥\(index + 1)"
        rows[index].apply(candidate: candidates[index], shortcut: shortcut, isPrimary: index == 0)
        rows[index].showsSeparator = index < visibleCount - 1
        rows[index].isHidden = false
        if contentChanged {
          rows[index].animateContentIn(
            delay: TimeInterval(index) * RagImeAssistantMotion.stagger,
            reduceMotion: reduceMotion
          )
        }
      }
      if quickActionCandidate != nil || deepActionCandidate != nil {
        [actionSeparator, actionContainer].forEach { $0.isHidden = false }
      }
    case .explicitGenerating:
      applyGenerationProgress(payload)
      [progressTitleLabel, progressContainer, stopButton].forEach { $0.isHidden = false }
      toolTip = "\(progressTitleLabel.stringValue)；点击停止"
      setAccessibilityLabel(progressSummaryText)
    case .explicitNoSuggestion:
      statusIcon.image = companionImage(named: "RagImeCompanionIdle")
      statusLabel.stringValue = payload.statusText.isEmpty ? "这次没有合适建议" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel, diagnosticLabel, retryButton, closeButton].forEach { $0.isHidden = false }
    case .explicitError:
      statusIcon.image = companionImage(named: "RagImeCompanionWarning")
      statusLabel.stringValue = payload.statusText.isEmpty ? "暂未完成，可以重试" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel, diagnosticLabel, retryButton, closeButton].forEach { $0.isHidden = false }
    case .explicitResult:
      let streaming = candidates.first.map { candidate in
        if case .bool(let value)? = candidate.metadata["streamingPartial"] { return value }
        return false
      } ?? false
      isStreamingResult = streaming
      [resultHeader, diagnosticLabel, resultScroll].forEach { $0.isHidden = false }
      isProgressHandoffVisible = previousState == .explicitGenerating && !reduceMotion
      if isProgressHandoffVisible {
        progressHandoffLabel.stringValue = progressSummaryText
        progressHandoffLabel.isHidden = false
      }
      if streaming {
        stopButton.isHidden = false
      } else {
        [resultShortcutPlate, resultShortcutLabel, closeButton, insertButton, retryButton, moreButton].forEach { $0.isHidden = false }
        replaceButton.isHidden = !canReplaceSelection
        replaceButton.isEnabled = canReplaceSelection
      }
      resultHeader.stringValue = streaming ? "正在接收内容" : "生成结果"
      let result = candidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
      applyResultText(result, reduceMotion: reduceMotion, startFresh: previousState == .explicitGenerating)
      if contentChanged { animateExplicitResultIn(reduceMotion: reduceMotion) }
      if isProgressHandoffVisible { scheduleProgressHandoff() }
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

  func captureResultViewport() -> ResultViewportSnapshot? {
    guard surfaceState == .explicitResult, !resultScroll.isHidden else { return nil }
    return ResultViewportSnapshot(
      selectedRange: resultText.selectedRange(),
      scrollOrigin: resultScroll.contentView.bounds.origin
    )
  }

  func restoreResultViewport(_ snapshot: ResultViewportSnapshot?) {
    guard let snapshot, surfaceState == .explicitResult, !resultScroll.isHidden else { return }
    let textLength = (resultText.string as NSString).length
    let location = min(max(0, snapshot.selectedRange.location), textLength)
    let length = min(max(0, snapshot.selectedRange.length), textLength - location)
    resultText.setSelectedRange(NSRange(location: location, length: length))
    let documentHeight = resultScroll.documentView?.frame.height ?? 0
    let maximumY = max(0, documentHeight - resultScroll.contentSize.height)
    let origin = NSPoint(
      x: 0,
      y: min(max(0, snapshot.scrollOrigin.y), maximumY)
    )
    resultScroll.contentView.scroll(to: origin)
    resultScroll.reflectScrolledClipView(resultScroll.contentView)
  }

  func updateGeneratingFrame(_ frame: Int, reduceMotion: Bool) {
    guard surfaceState == .pendingPrediction || surfaceState == .explicitGenerating else { return }
    statusIcon.image = companionImage(named: "RagImeCompanionThinking")
  }

  func setGeneratingPulse(active: Bool, reduceMotion: Bool) {
    statusIcon.wantsLayer = true
    statusIcon.layer?.removeAnimation(forKey: "rag-ime-thinking-pulse")
    statusHalo.layer?.removeAnimation(forKey: "rag-ime-companion-breathe")
    guard active, !reduceMotion else { return }
    let pulse = CABasicAnimation(keyPath: "opacity")
    pulse.fromValue = 0.45
    pulse.toValue = 1
    pulse.duration = RagImeAssistantMotion.Duration.ambientPulse
    pulse.autoreverses = true
    pulse.repeatCount = .infinity
    pulse.timingFunction = RagImeAssistantMotion.timingFunction(.easeInEaseOut)
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
    candidate.sourceType == "action"
      || candidate.selectionAction == "start_active_rag_from_context"
      || candidate.selectionAction == "start_agent_deep_search_from_context"
  }

  static func predictionHeight(candidateCount: Int, hasAction: Bool) -> CGFloat {
    rowHeight * CGFloat(max(0, min(maximumPredictionCandidates, candidateCount)))
      + (hasAction ? actionHeight : 0)
  }

  static func explicitResultHeight(text: String, width: CGFloat) -> CGFloat {
    let measured = RagImeAssistantMarkdownRenderer.render(text).boundingRect(
      with: NSSize(width: max(240, width - 28), height: CGFloat.greatestFiniteMagnitude),
      options: [.usesLineFragmentOrigin, .usesFontLeading],
      context: nil
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
    [actionSeparator, actionContainer].forEach { $0.isHidden = true }
    [statusHalo, statusIcon, statusLabel, diagnosticLabel, progressTitleLabel, progressContainer, progressHandoffLabel, stopButton, closeButton, resultHeader, resultShortcutPlate, resultShortcutLabel, resultScroll, insertButton, replaceButton, retryButton, moreButton, confirmationLabel].forEach { $0.isHidden = true }
  }

  private func updateThemeChrome(for state: RagImeAssistantSurfaceState) {
    let tint: NSColor
    let rail: NSColor
    switch state {
    case .explicitGenerating:
      tint = NSColor.systemIndigo.withAlphaComponent(0.035)
      rail = .systemIndigo
    case .explicitNoSuggestion:
      tint = NSColor.systemTeal.withAlphaComponent(0.02)
      rail = .systemTeal
    case .explicitError:
      tint = NSColor.systemOrange.withAlphaComponent(0.045)
      rail = .systemOrange
    case .explicitResult:
      tint = NSColor.systemTeal.withAlphaComponent(0.025)
      rail = .systemTeal
    default:
      tint = .clear
      rail = .clear
    }
    stateTint.layer?.backgroundColor = tint.cgColor
    accentRail.layer?.backgroundColor = rail.withAlphaComponent(0.82).cgColor
    accentRail.isHidden = !state.isExplicit
  }

  private func companionImage(named name: String) -> NSImage? {
    guard let url = Bundle.main.url(forResource: name, withExtension: "png"),
          let image = NSImage(contentsOf: url) else { return nil }
    image.isTemplate = false
    return image
  }

  private func diagnosticText(for payload: RagImeAssistantOverlayPayload) -> String {
    guard payload.phase == "active_rag" || payload.uiMode.contains("active_rag") else { return "" }
    let transaction = payload.frontendTransaction ?? [:]
    let metadata = candidates.first?.metadata ?? [:]
    let status = stringValue(in: [transaction, metadata], keys: ["diagnosticStatus", "captureFailureReason", "remoteModelReason"])
    let remoteUnavailable = status.contains("remote_model_disabled")
      || status.contains("credentials_missing")
      || status.contains("provider_unavailable")
    let contextUnavailable = status.contains("context_missing")
      || status.contains("capture_failed")

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
    } else if contextUnavailable || boolValue(in: [transaction, metadata], keys: ["contextCaptured"]) == false {
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
    if remoteUnavailable || remoteReady == false {
      parts.append("远程模型未启用")
    } else {
      parts.append("知识生成")
    }
    if let firstTokenMs = intValue(in: [transaction, metadata], keys: ["firstTokenMs"]), firstTokenMs > 0 {
      parts.append(String(format: "首字 %.1f 秒", Double(firstTokenMs) / 1000))
    }
    if boolValue(in: [transaction, metadata], keys: ["contentRetryAttempted", "qualityRetry"]) == true {
      parts.append("质量校正 1 次")
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
    return compact.isEmpty ? "正在生成" : compact
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

  private func applyGenerationProgress(_ payload: RagImeAssistantOverlayPayload) {
    let transaction = payload.frontendTransaction ?? [:]
    let stage = stringValue(in: [transaction], keys: ["progressStage"])
    let foregroundChars = intValue(in: [transaction], keys: ["foregroundContextChars", "effectiveContextChars", "contextChars"]) ?? 0
    let windowNodes = intValue(in: [transaction], keys: ["windowContextNodes"]) ?? 0
    let recentCount = intValue(in: [transaction], keys: ["timelineRecentInputRecordCount"]) ?? 0
    let recentChars = intValue(in: [transaction], keys: ["timelineRecentInputChars"]) ?? 0
    let recentUsed = boolValue(in: [transaction], keys: ["timelineRecentInputUsedForGeneration"]) == true
    let evidenceCount = intValue(in: [transaction], keys: ["evidenceCount"]) ?? payload.sourceCards.count
    let retrievalAttempted = boolValue(in: [transaction], keys: ["retrievalAttempted"]) == true
    let firstTokenMs = intValue(in: [transaction], keys: ["firstTokenMs"]) ?? 0
    let qualityRetry = boolValue(in: [transaction], keys: ["contentRetryAttempted", "qualityRetry"]) == true

    switch stage {
    case "quality_retry": progressTitleLabel.stringValue = "正在优化回答"
    case "streaming": progressTitleLabel.stringValue = "正在接收内容"
    case "generating": progressTitleLabel.stringValue = "正在生成"
    default: progressTitleLabel.stringValue = "正在准备"
    }

    let contextDetail: String
    if windowNodes > 0 {
      contextDetail = "已读取当前输入和界面信息"
    } else if foregroundChars > 0 {
      contextDetail = "已读取当前输入"
    } else {
      contextDetail = "等待可访问性上下文"
    }

    let historyDetail: String
    if recentCount > 0 {
      historyDetail = recentUsed ? "已选取相关的近期内容" : "近期内容与本次问题无关"
    } else if recentChars > 0 {
      historyDetail = recentUsed ? "已补充近期内容" : "本次无需补充"
    } else {
      historyDetail = retrievalAttempted ? "本次没有可用历史" : "正在选择最近输入"
    }

    let recalledTitles = payload.sourceCards.prefix(2).map(\.title).filter { !$0.isEmpty }
    let retrievalDetail: String
    if !recalledTitles.isEmpty {
      retrievalDetail = "已找到 " + recalledTitles.prefix(2).joined(separator: "、")
    } else if evidenceCount > 0 {
      retrievalDetail = "已找到相关记忆与资料"
    } else if retrievalAttempted {
      retrievalDetail = "没有额外依据，继续使用当前上下文"
    } else {
      retrievalDetail = "正在检索记忆、计划与资料"
    }

    let modelDetail: String
    if qualityRetry || stage == "quality_retry" {
      modelDetail = "正在调整表达，避免重复原文"
    } else if firstTokenMs > 0 {
      modelDetail = "首段内容已到达，正在继续"
    } else {
      modelDetail = "等待首段内容"
    }

    let modelActive = ["generating", "quality_retry", "streaming"].contains(stage)
    let retrievalActive = stage == "retrieving" || stage == "retrieval_complete"
    progressRows[0].apply(
      title: "理解当前内容",
      detail: contextDetail,
      completed: foregroundChars > 0 || windowNodes > 0,
      active: stage == "capturing_context"
    )
    progressRows[1].apply(
      title: "补充近期上下文",
      detail: historyDetail,
      completed: retrievalAttempted || recentCount > 0 || recentChars > 0,
      active: stage == "retrieving" && recentCount == 0
    )
    progressRows[2].apply(
      title: "查找相关记忆",
      detail: retrievalDetail,
      completed: retrievalAttempted,
      active: retrievalActive
    )
    progressRows[3].apply(
      title: qualityRetry ? "优化回答" : "组织回答",
      detail: modelDetail,
      completed: stage == "ready",
      active: modelActive || (!retrievalActive && retrievalAttempted)
    )

    var summary: [String] = []
    if windowNodes > 0 { summary.append("AX \(windowNodes) 节点") }
    if recentCount > 0 { summary.append("历史 \(recentCount) 条") }
    if !recalledTitles.isEmpty {
      summary.append("召回 " + recalledTitles.prefix(2).joined(separator: "、"))
    } else if evidenceCount > 0 {
      summary.append("召回 \(evidenceCount) 条")
    }
    progressSummaryText = summary.isEmpty ? "上下文与召回已准备" : summary.joined(separator: " · ")
  }

  private func layoutProgressRows() {
    let rowHeight = max(22, floor(progressContainer.bounds.height / CGFloat(progressRows.count)))
    for (index, row) in progressRows.enumerated() {
      row.frame = NSRect(
        x: 0,
        y: progressContainer.bounds.height - CGFloat(index + 1) * rowHeight,
        width: progressContainer.bounds.width,
        height: rowHeight
      )
    }
  }

  private func applyResultText(_ text: String, reduceMotion: Bool, startFresh: Bool) {
    pendingResultText = text
    if reduceMotion || text.count <= 24 {
      stopResultReveal(reset: false)
      setVisibleResultText(text)
      return
    }
    let visible = visibleResultMarkdown
    if startFresh || visible.isEmpty || !text.hasPrefix(visible) {
      let initialCount = min(18, text.count)
      setVisibleResultText(String(text.prefix(initialCount)))
    }
    guard visibleResultMarkdown != pendingResultText else {
      stopResultReveal(reset: false)
      return
    }
    startResultRevealTimer()
  }

  private func startResultRevealTimer() {
    guard resultRevealTimer == nil else { return }
    let timer = Timer(timeInterval: 0.025, repeats: true) { [weak self] timer in
      guard let self else {
        timer.invalidate()
        return
      }
      let visible = self.visibleResultMarkdown
      let target = self.pendingResultText
      guard visible != target else {
        timer.invalidate()
        self.resultRevealTimer = nil
        return
      }
      guard target.hasPrefix(visible) else {
        self.setVisibleResultText(target)
        timer.invalidate()
        self.resultRevealTimer = nil
        return
      }
      let remaining = target.count - visible.count
      let chunk = max(1, min(16, Int(ceil(Double(remaining) / 8))))
      self.setVisibleResultText(String(target.prefix(min(target.count, visible.count + chunk))))
    }
    resultRevealTimer = timer
    RunLoop.main.add(timer, forMode: .common)
  }

  private func stopResultReveal(reset: Bool) {
    resultRevealTimer?.invalidate()
    resultRevealTimer = nil
    if reset {
      pendingResultText = ""
      setVisibleResultText("")
    }
  }

  private func setVisibleResultText(_ text: String) {
    visibleResultMarkdown = text
    resultText.textStorage?.setAttributedString(RagImeAssistantMarkdownRenderer.render(text))
    layoutResultText()
  }

  private func scheduleProgressHandoff() {
    progressHandoffWorkItem?.cancel()
    progressHandoffLabel.wantsLayer = true
    progressHandoffLabel.layer?.removeAllAnimations()
    resultScroll.wantsLayer = true
    let handoffOpacity = CABasicAnimation(keyPath: "opacity")
    handoffOpacity.fromValue = 1
    handoffOpacity.toValue = 0
    let handoffMove = CABasicAnimation(keyPath: "transform.translation.y")
    handoffMove.fromValue = 0
    handoffMove.toValue = -RagImeAssistantMotion.Distance.progressHandoff
    let handoffGroup = CAAnimationGroup()
    handoffGroup.animations = [handoffOpacity, handoffMove]
    handoffGroup.duration = RagImeAssistantMotion.Duration.progressHandoff
    handoffGroup.timingFunction = RagImeAssistantMotion.timingFunction(.easeInEaseOut)
    progressHandoffLabel.layer?.add(handoffGroup, forKey: "rag-ime-progress-handoff-out")

    let resultOpacity = CABasicAnimation(keyPath: "opacity")
    resultOpacity.fromValue = 0.35
    resultOpacity.toValue = 1
    let resultMove = CABasicAnimation(keyPath: "transform.translation.y")
    resultMove.fromValue = -RagImeAssistantMotion.Distance.small
    resultMove.toValue = 0
    let resultGroup = CAAnimationGroup()
    resultGroup.animations = [resultOpacity, resultMove]
    resultGroup.duration = RagImeAssistantMotion.Duration.progressHandoff
    resultGroup.timingFunction = RagImeAssistantMotion.timingFunction()
    resultScroll.layer?.add(resultGroup, forKey: "rag-ime-result-pushes-progress")

    let work = DispatchWorkItem { [weak self] in
      guard let self else { return }
      self.isProgressHandoffVisible = false
      self.progressHandoffLabel.isHidden = true
      self.progressHandoffWorkItem = nil
      self.needsLayout = true
      self.layoutSubtreeIfNeeded()
    }
    progressHandoffWorkItem = work
    DispatchQueue.main.asyncAfter(
      deadline: .now() + RagImeAssistantMotion.Duration.progressHandoff,
      execute: work
    )
  }

  private func animateExplicitResultIn(reduceMotion: Bool) {
    resultScroll.wantsLayer = true
    resultScroll.layer?.removeAnimation(forKey: "rag-ime-explicit-result-in")
    guard !reduceMotion else { return }
    let opacity = CABasicAnimation(keyPath: "opacity")
    opacity.fromValue = 0
    opacity.toValue = 1
    let translation = CABasicAnimation(keyPath: "transform.translation.y")
    translation.fromValue = RagImeAssistantMotion.Distance.tiny
    translation.toValue = 0
    let group = CAAnimationGroup()
    group.animations = [opacity, translation]
    group.duration = RagImeAssistantMotion.Duration.transition
    group.timingFunction = RagImeAssistantMotion.timingFunction()
    resultScroll.layer?.add(group, forKey: "rag-ime-explicit-result-in")
  }

  private func layoutResultText() {
    let viewport = resultScroll.contentSize
    let width = max(40, viewport.width)
    guard let textContainer = resultText.textContainer,
          let layoutManager = resultText.layoutManager else { return }
    textContainer.containerSize = NSSize(width: width, height: CGFloat.greatestFiniteMagnitude)
    layoutManager.ensureLayout(for: textContainer)
    let measuredHeight = layoutManager.usedRect(for: textContainer).height
    resultText.frame = NSRect(
      x: 0,
      y: 0,
      width: width,
      height: max(viewport.height, ceil(measuredHeight) + 4)
    )
  }

  private func layoutActionBar(frame: NSRect, compact: Bool) {
    actionContainer.frame = frame
    let gap: CGFloat = compact ? 4 : 6
    let segment = max(0, floor((frame.width - gap) / 2))
    quickGenerateButton.frame = NSRect(x: 0, y: 0, width: segment, height: frame.height)
    actionDividerLeading.frame = .zero
    deepSearchButton.frame = NSRect(
      x: segment + gap,
      y: 0,
      width: max(0, frame.width - segment - gap),
      height: frame.height
    )
    quickGenerateButton.alignment = .center
    deepSearchButton.alignment = .center
  }

  private func updateActionGroupChrome() {
    let increaseContrast = NSWorkspace.shared.accessibilityDisplayShouldIncreaseContrast
    actionContainer.layer?.borderWidth = 0
    actionContainer.layer?.backgroundColor = NSColor.clear.cgColor
    actionDividerLeading.layer?.backgroundColor = NSColor.clear.cgColor
    let fill = NSColor.controlBackgroundColor
      .withAlphaComponent(increaseContrast ? 0.98 : 0.74)
      .cgColor
    let stroke = NSColor.separatorColor
      .withAlphaComponent(increaseContrast ? 0.92 : 0.46)
      .cgColor
    for button in [quickGenerateButton, deepSearchButton] {
      button.layer?.borderWidth = increaseContrast ? 1 : 0.5
      button.layer?.borderColor = stroke
      button.layer?.backgroundColor = fill
    }
  }

  private func configureActionButton(_ button: NSButton, action: Selector, symbol: String, toolTip: String) {
    button.isBordered = false
    button.focusRingType = .exterior
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
    guard let quickActionCandidate, let quickActionCandidateIndex else { return }
    onSelect?(quickActionCandidate, quickActionCandidateIndex, .insert)
  }

  @objc private func startAgentDeepSearch() {
    guard let deepActionCandidate, let deepActionCandidateIndex else { return }
    onSelect?(deepActionCandidate, deepActionCandidateIndex, .insert)
  }
}

private final class RagImeGenerationProgressRowView: NSView {
  private let iconView = NSImageView()
  private let titleLabel = NSTextField(labelWithString: "")
  private let detailLabel = NSTextField(labelWithString: "")
  private let shimmerLayer = CAGradientLayer()

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    wantsLayer = true
    layer?.cornerRadius = 4
    layer?.masksToBounds = true
    shimmerLayer.startPoint = CGPoint(x: 0, y: 0.5)
    shimmerLayer.endPoint = CGPoint(x: 1, y: 0.5)
    shimmerLayer.colors = [
      NSColor.clear.cgColor,
      NSColor.secondaryLabelColor.withAlphaComponent(0.13).cgColor,
      NSColor.clear.cgColor,
    ]
    shimmerLayer.locations = [-0.8, -0.4, 0]
    shimmerLayer.isHidden = true
    layer?.addSublayer(shimmerLayer)
    iconView.imageScaling = .scaleProportionallyDown
    titleLabel.font = NSFont.systemFont(ofSize: 12, weight: .medium)
    titleLabel.textColor = .labelColor
    titleLabel.lineBreakMode = .byTruncatingTail
    detailLabel.font = NSFont.systemFont(ofSize: 11.5, weight: .regular)
    detailLabel.textColor = .secondaryLabelColor
    detailLabel.lineBreakMode = .byTruncatingTail
    [iconView, titleLabel, detailLabel].forEach(addSubview)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func layout() {
    super.layout()
    shimmerLayer.frame = bounds
    iconView.frame = NSRect(x: 8, y: max(0, (bounds.height - 16) / 2), width: 16, height: 16)
    let titleWidth = min(126, max(92, bounds.width * 0.31))
    titleLabel.frame = NSRect(x: 31, y: max(0, (bounds.height - 18) / 2), width: titleWidth, height: 18)
    detailLabel.frame = NSRect(
      x: 37 + titleWidth,
      y: max(0, (bounds.height - 18) / 2),
      width: max(32, bounds.width - titleWidth - 45),
      height: 18
    )
  }

  func apply(title: String, detail: String, completed: Bool, active: Bool) {
    titleLabel.stringValue = title
    detailLabel.stringValue = detail
    let symbol: String
    let color: NSColor
    if completed {
      symbol = "checkmark.circle.fill"
      color = .systemGreen
    } else if active {
      symbol = "sparkles"
      color = .systemIndigo
    } else {
      symbol = "circle"
      color = .tertiaryLabelColor
    }
    iconView.image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)
    iconView.contentTintColor = color
    layer?.backgroundColor = active
      ? NSColor.selectedContentBackgroundColor.withAlphaComponent(0.055).cgColor
      : NSColor.clear.cgColor
    updateShimmer(active: active && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
    setAccessibilityLabel("\(title)：\(detail)")
  }

  private func updateShimmer(active: Bool) {
    shimmerLayer.removeAnimation(forKey: "rag-ime-progress-shimmer")
    shimmerLayer.isHidden = !active
    guard active else { return }
    let animation = CABasicAnimation(keyPath: "locations")
    animation.fromValue = [-0.8, -0.4, 0]
    animation.toValue = [1, 1.4, 1.8]
    animation.duration = 1.15
    animation.repeatCount = .infinity
    animation.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
    shimmerLayer.add(animation, forKey: "rag-ime-progress-shimmer")
  }
}
