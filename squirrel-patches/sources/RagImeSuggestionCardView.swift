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

extension RagImeDisplayCandidate {
  /// Stable IDs identify a candidate across streaming frames, not its visible content.
  var assistantPresentationSignature: String {
    let flags = ["streamingPartial", "partialRecovered", "streamInterrupted"].map {
      "\($0)=\(String(describing: metadata[$0]))"
    }
    return ([candidateStableId ?? suggestionId, sourceType, text, insertText,
             selectionAction, String(describing: isSelectable)] + flags).joined(separator: "\u{1f}")
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

enum RagImeGenerationStageState: String {
  case pending
  case active
  case done
  case failed
  case skipped

  var accessibilityWord: String {
    switch self {
    case .pending: return "等待"
    case .active: return "进行中"
    case .done: return "已完成"
    case .failed: return "未完成"
    case .skipped: return "未使用"
    }
  }
}

struct RagImeGenerationStageRowModel: Equatable {
  let title: String
  let detail: String
  let state: RagImeGenerationStageState
}

struct RagImeGenerationStagePlan: Equatable {
  let title: String
  let rows: [RagImeGenerationStageRowModel]
  let summary: String
}

/// Pure presentation model for one explicit generation. It only interprets the
/// progress stages the rag_ime sidecar actually reports through
/// `_active_rag_progress_payload` (rag_ime/active_rag_service.py):
/// capturing_context → retrieval_complete → generating → streaming →
/// quality_retry → ready, plus the terminal failure statuses error, cancelled,
/// and stale_dropped. It must not invent stages the backend never emits.
enum RagImeGenerationStagePlanner {
  struct Input {
    var stage = ""
    var diagnosticStatus = ""
    var foregroundChars = 0
    var windowNodes = 0
    var recentCount = 0
    var recentChars = 0
    var recentUsed = false
    var evidenceCount = 0
    var retrievalAttempted = false
    var firstTokenMs = 0
    var qualityRetry = false
    var recalledTitles: [String] = []
  }

  static let contextStages: Set<String> = ["capturing_context"]
  static let retrievalHandoffStages: Set<String> = ["retrieval_complete"]
  static let modelStages: Set<String> = ["generating", "streaming", "quality_retry"]
  static let readyStages: Set<String> = ["ready"]
  static let failureStages: Set<String> = ["error", "cancelled", "stale_dropped"]

  static func plan(_ input: Input) -> RagImeGenerationStagePlan {
    let stage = input.stage
    let interrupted = failureStages.contains(stage)
    let hasContext = input.foregroundChars > 0 || input.windowNodes > 0
    let passedContext = input.retrievalAttempted || retrievalHandoffStages.contains(stage)
      || modelStages.contains(stage) || readyStages.contains(stage)
    let contextDone = hasContext || passedContext
    let historyDone = input.retrievalAttempted || input.recentCount > 0 || input.recentChars > 0
    let retrievalDone = input.retrievalAttempted
    let modelDone = readyStages.contains(stage)
    let captureFailed = input.diagnosticStatus.contains("context_missing")
      || input.diagnosticStatus.contains("capture_failed")

    // During capturing_context the sidecar has not confirmed retrieval yet;
    // history selection and RAG recall run inside the same retrieval pass.
    let contextActive = !interrupted && contextStages.contains(stage) && !contextDone
    let retrievalActive = !interrupted && contextStages.contains(stage) && contextDone && !retrievalDone
    let modelActive = !interrupted
      && (modelStages.contains(stage) || retrievalHandoffStages.contains(stage))
      && !modelDone

    // An interrupted run stops at the first step that never produced data.
    // Steps that already finished keep their honest done state.
    let contextInterrupted = interrupted && !contextDone
    let retrievalInterrupted = interrupted && contextDone && !retrievalDone
    let modelInterrupted = interrupted && contextDone && retrievalDone && !modelDone

    func resolve(done: Bool, active: Bool, failed: Bool) -> RagImeGenerationStageState {
      if failed { return .failed }
      if done { return .done }
      if active { return .active }
      return .pending
    }

    let contextState: RagImeGenerationStageState = (captureFailed || !hasContext) && passedContext ? .skipped : resolve(
      done: hasContext && !captureFailed,
      active: contextActive,
      failed: captureFailed || contextInterrupted
    )
    let historyState = resolve(done: historyDone, active: retrievalActive, failed: retrievalInterrupted && !historyDone)
    let retrievalState = resolve(done: retrievalDone, active: retrievalActive, failed: retrievalInterrupted)
    let modelState = resolve(done: modelDone, active: modelActive, failed: modelInterrupted)

    let failureDetail: String
    switch stage {
    case "cancelled": failureDetail = "已停止，未继续生成"
    case "stale_dropped": failureDetail = "输入已更新，本轮结果不再使用"
    default: failureDetail = "生成未完成，可重试"
    }

    let contextDetail: String
    if contextState == .skipped {
      contextDetail = "未读取到前台内容，仅使用已有输入"
    } else if contextState == .failed {
      contextDetail = captureFailed ? "未读取到前台内容，仅使用已有输入" : failureDetail
    } else if input.windowNodes > 0 {
      contextDetail = "已读取当前输入和界面信息"
    } else if input.foregroundChars > 0 {
      contextDetail = "已读取当前输入 \(input.foregroundChars) 字"
    } else if contextState == .active {
      contextDetail = "正在读取当前输入与界面信息"
    } else {
      contextDetail = "等待当前输入"
    }

    let historyDetail: String
    if historyState == .failed {
      historyDetail = failureDetail
    } else if input.recentCount > 0 {
      historyDetail = input.recentUsed ? "已使用 \(input.recentCount) 条近期输入" : "本次未使用近期输入"
    } else if input.recentChars > 0 {
      historyDetail = input.recentUsed ? "已补充近期内容" : "本次无需补充"
    } else if input.retrievalAttempted {
      historyDetail = "本次没有可用历史"
    } else if historyState == .active {
      historyDetail = "正在选择最近输入"
    } else {
      historyDetail = "等待上下文就绪"
    }

    let recalledTitles = input.recalledTitles.filter { !$0.isEmpty }.prefix(2)
    let retrievalDetail: String
    if retrievalState == .failed {
      retrievalDetail = failureDetail
    } else if !recalledTitles.isEmpty {
      retrievalDetail = "已找到 " + recalledTitles.joined(separator: "、")
    } else if input.evidenceCount > 0 {
      retrievalDetail = "已找到 \(input.evidenceCount) 条相关资料"
    } else if input.retrievalAttempted {
      retrievalDetail = "没有额外依据，继续使用当前上下文"
    } else if retrievalState == .active {
      retrievalDetail = "正在检索记忆、计划与资料"
    } else {
      retrievalDetail = "等待上下文就绪"
    }

    let qualityRetry = input.qualityRetry || stage == "quality_retry"
    let modelDetail: String
    if modelState == .failed {
      modelDetail = failureDetail
    } else if modelDone {
      modelDetail = "回答已生成"
    } else if qualityRetry {
      modelDetail = "正在调整表达，避免重复原文"
    } else if stage == "streaming" || input.firstTokenMs > 0 {
      modelDetail = "首段内容已到达，正在继续"
    } else if modelState == .active {
      modelDetail = retrievalHandoffStages.contains(stage) ? "正在准备生成请求" : "等待模型返回首段内容"
    } else {
      modelDetail = "等待检索结果"
    }

    let title: String
    switch stage {
    case "quality_retry": title = "正在优化回答"
    case "streaming": title = "正在接收内容"
    case "generating": title = "正在生成回答"
    case "retrieval_complete": title = "正在准备回答"
    case "ready": title = "已生成"
    case "error": title = "生成未完成"
    case "cancelled": title = "已停止生成"
    case "stale_dropped": title = "输入已更新，本轮已作废"
    case "capturing_context": title = hasContext ? "正在查找相关资料" : "正在读取当前输入"
    default: title = "正在连接生成服务"
    }

    var summaryParts: [String] = []
    if input.foregroundChars > 0 { summaryParts.append("当前输入 \(input.foregroundChars) 字") }
    else if input.windowNodes > 0 { summaryParts.append("已读取当前界面") }
    if input.recentUsed && input.recentCount > 0 { summaryParts.append("近期输入 \(input.recentCount) 条") }
    if input.evidenceCount > 0 { summaryParts.append("参考资料 \(input.evidenceCount) 条") }
    else if input.retrievalAttempted { summaryParts.append("未找到额外资料") }
    if interrupted { summaryParts.append(title) }
    let summary = summaryParts.isEmpty ? "等待输入与检索结果" : summaryParts.joined(separator: " · ")

    return RagImeGenerationStagePlan(
      title: title,
      rows: [
        RagImeGenerationStageRowModel(title: "理解当前内容", detail: contextDetail, state: contextState),
        RagImeGenerationStageRowModel(title: "补充近期上下文", detail: historyDetail, state: historyState),
        RagImeGenerationStageRowModel(title: "查找相关记忆", detail: retrievalDetail, state: retrievalState),
        RagImeGenerationStageRowModel(title: qualityRetry ? "优化回答" : "组织回答", detail: modelDetail, state: modelState),
      ],
      summary: summary
    )
  }
}

final class RagImeSuggestionCardView: NSVisualEffectView {
  static let compactHeight: CGFloat = 38
  static let pendingHeight: CGFloat = 44
  static let thinkingHeight: CGFloat = 112
  static let expandedThinkingHeight: CGFloat = 296
  static let thinkingWidth: CGFloat = 380
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
  private let progressSummaryLabel = NSTextField(labelWithString: "")
  private let progressElapsedLabel = NSTextField(labelWithString: "")
  private let progressDetailsButton = NSButton(title: "查看步骤", target: nil, action: nil)
  private let progressContainer = NSView()
  private let progressRows = (0..<4).map { _ in RagImeGenerationProgressRowView(frame: .zero) }
  private let progressHandoffLabel = NSTextField(labelWithString: "")
  private let stopButton = NSButton(title: "停止", target: nil, action: nil)
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
  private var generationSnapshotId = ""
  private var generationStartedAt: TimeInterval?
  private var generationAnimationsEnabled = true
  private(set) var generationDetailsExpanded = false
  var generationHeight: CGFloat { generationDetailsExpanded ? Self.expandedThinkingHeight : Self.thinkingHeight }
  var onLayoutChange: (() -> Void)?
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
    progressTitleLabel.lineBreakMode = .byTruncatingTail
    progressSummaryLabel.font = RagImeAssistantTypography.diagnostic
    progressSummaryLabel.textColor = .secondaryLabelColor
    progressSummaryLabel.lineBreakMode = .byTruncatingTail
    progressElapsedLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .regular)
    progressElapsedLabel.textColor = .secondaryLabelColor
    progressElapsedLabel.lineBreakMode = .byTruncatingTail
    progressDetailsButton.identifier = NSUserInterfaceItemIdentifier("ragIme.assistant.generationDetails")
    configureActionButton(progressDetailsButton, action: #selector(toggleGenerationDetails), symbol: "chevron.down", toolTip: "查看生成步骤")
    progressDetailsButton.imagePosition = .imageTrailing
    progressDetailsButton.font = RagImeAssistantTypography.diagnostic
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
    stopButton.font = RagImeAssistantTypography.action
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
    [progressSummaryLabel, progressElapsedLabel, progressDetailsButton].forEach(addSubview)
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
      progressTitleLabel.frame = NSRect(x: 16, y: bounds.height - 35, width: max(80, bounds.width - 108), height: 22)
      stopButton.frame = NSRect(
        x: bounds.width - 84,
        y: bounds.height - 46,
        width: 72,
        height: RagImeAssistantMetrics.minimumHitTarget
      )
      progressSummaryLabel.frame = NSRect(x: 16, y: bounds.height - 65, width: max(0, bounds.width - 32), height: 20)
      progressElapsedLabel.frame = NSRect(x: 16, y: bounds.height - 98, width: max(0, bounds.width - 130), height: 18)
      progressDetailsButton.frame = NSRect(x: bounds.width - 108, y: bounds.height - 108, width: 96, height: 36)
      progressContainer.frame = NSRect(x: 12, y: 8, width: max(0, bounds.width - 24), height: 176)
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
          width: 72,
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
    setAccessibilityLabel(nil)
    toolTip = nil
    if state == .explicitGenerating {
      let now = ProcessInfo.processInfo.systemUptime
      let elapsedMs = intValue(in: [payload.frontendTransaction ?? [:]], keys: ["progressElapsedMs"]) ?? 0
      let observedStart = now - Double(max(0, elapsedMs)) / 1000
      if generationSnapshotId != payload.snapshotId || generationStartedAt == nil {
        generationSnapshotId = payload.snapshotId
        generationStartedAt = observedStart
        generationDetailsExpanded = false
      } else if let started = generationStartedAt {
        generationStartedAt = min(started, observedStart)
      }
    } else {
      generationStartedAt = nil
    }
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
    generationAnimationsEnabled = !reduceMotion
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
      applyGenerationProgress(payload, reduceMotion: reduceMotion)
      [progressTitleLabel, progressContainer, stopButton].forEach { $0.isHidden = false }
      [progressSummaryLabel, progressElapsedLabel, progressDetailsButton].forEach { $0.isHidden = false }
      progressContainer.isHidden = !generationDetailsExpanded
      updateGenerationDisclosure()
      updateGenerationElapsed()
      toolTip = "\(progressTitleLabel.stringValue)；可随时停止生成"
      setAccessibilityLabel("\(progressTitleLabel.stringValue)。\(progressSummaryText)")
    case .explicitNoSuggestion:
      statusIcon.image = companionImage(named: "RagImeCompanionIdle")
      statusLabel.stringValue = payload.statusText.isEmpty ? "这次没有合适建议" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel, diagnosticLabel, retryButton, closeButton].forEach { $0.isHidden = false }
    case .explicitError:
      statusIcon.image = companionImage(named: "RagImeCompanionWarning")
      statusLabel.stringValue = payload.statusText.isEmpty ? "暂未完成，可以重试" : providerNeutralStatus(payload.statusText)
      [statusHalo, statusIcon, statusLabel, diagnosticLabel, retryButton, closeButton].forEach { $0.isHidden = false }
    case .explicitResult:
      let streaming = boolValue(in: [payload.frontendTransaction ?? [:]], keys: ["workerPending"]) == true || (candidates.first.map { candidate in
        if case .bool(let value)? = candidate.metadata["streamingPartial"] { return value }
        return false
      } ?? false)
      isStreamingResult = streaming
      let copyOnly = candidates.first.map { candidate in
        if case .string(let placement)? = candidate.metadata["placement"] { return placement == "show_only" }
        return false
      } ?? false
      insertButton.title = copyOnly ? "复制" : "插入"
      insertButton.toolTip = copyOnly ? "复制结果" : "插入到光标"
      resultShortcutLabel.stringValue = copyOnly ? "Tab 复制" : "Tab 插入"
      resultShortcutLabel.toolTip = copyOnly ? "按 Tab 复制结果" : "结果就绪后按 Tab 插入"
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
      if !streaming, boolValue(in: candidates.map(\.metadata), keys: ["streamInterrupted", "partialRecovered"]) == true {
        resultHeader.stringValue = "生成已中断 · 已保留完整片段"
      }
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

  func setConfirmationText(_ text: String) { confirmationLabel.stringValue = text }

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
    generationAnimationsEnabled = !reduceMotion
    progressRows.forEach { $0.setActivityVisible(surfaceState == .explicitGenerating && generationDetailsExpanded && !reduceMotion) }
    updateGenerationElapsed()
  }

  private func updateGenerationElapsed() {
    guard surfaceState == .explicitGenerating, let started = generationStartedAt else { return }
    let seconds = max(0, Int(ProcessInfo.processInfo.systemUptime - started))
    progressElapsedLabel.stringValue = seconds < 1 ? "准备中，可随时停止"
      : seconds < 15 ? "已用 \(seconds) 秒" : "已等待 \(seconds) 秒 · 可随时停止"
  }

  func stopGenerationProgress() {
    progressRows.forEach { $0.stopActivity() }
    generationStartedAt = nil
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
    [progressSummaryLabel, progressElapsedLabel, progressDetailsButton].forEach { $0.isHidden = true }
    progressRows.forEach { $0.stopActivity() }
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

  private func applyGenerationProgress(_ payload: RagImeAssistantOverlayPayload, reduceMotion: Bool) {
    let transaction = payload.frontendTransaction ?? [:]
    var input = RagImeGenerationStagePlanner.Input()
    input.stage = stringValue(in: [transaction], keys: ["progressStage"]).lowercased()
    input.diagnosticStatus = stringValue(in: [transaction], keys: ["diagnosticStatus"]).lowercased()
    input.foregroundChars = intValue(in: [transaction], keys: ["foregroundContextChars", "effectiveContextChars", "contextChars"]) ?? 0
    input.windowNodes = intValue(in: [transaction], keys: ["windowContextNodes"]) ?? 0
    input.recentCount = intValue(in: [transaction], keys: ["timelineRecentInputRecordCount"]) ?? 0
    input.recentChars = intValue(in: [transaction], keys: ["timelineRecentInputChars"]) ?? 0
    input.recentUsed = boolValue(in: [transaction], keys: ["timelineRecentInputUsedForGeneration"]) == true
    input.evidenceCount = intValue(in: [transaction], keys: ["evidenceCount"]) ?? payload.sourceCards.count
    input.retrievalAttempted = boolValue(in: [transaction], keys: ["retrievalAttempted"]) == true
    input.firstTokenMs = intValue(in: [transaction], keys: ["firstTokenMs"]) ?? 0
    input.qualityRetry = boolValue(in: [transaction], keys: ["contentRetryAttempted", "qualityRetry"]) == true
    input.recalledTitles = payload.sourceCards.prefix(2).map(\.title).filter { !$0.isEmpty }
    let plan = RagImeGenerationStagePlanner.plan(input)
    progressTitleLabel.stringValue = plan.title
    for (index, row) in progressRows.enumerated() where index < plan.rows.count {
      row.apply(model: plan.rows[index])
      row.setActivityVisible(generationDetailsExpanded && !reduceMotion)
    }
    progressSummaryText = plan.summary
    progressSummaryLabel.stringValue = plan.summary
    progressSummaryLabel.toolTip = plan.summary
  }

  private func updateGenerationDisclosure() {
    progressDetailsButton.title = generationDetailsExpanded ? "收起步骤" : "查看步骤"
    progressDetailsButton.image = NSImage(systemSymbolName: generationDetailsExpanded ? "chevron.up" : "chevron.down", accessibilityDescription: nil)
    progressDetailsButton.setAccessibilityLabel(progressDetailsButton.title)
  }

  @objc private func toggleGenerationDetails() {
    guard surfaceState == .explicitGenerating else { return }
    generationDetailsExpanded.toggle()
    progressContainer.isHidden = !generationDetailsExpanded
    updateGenerationDisclosure()
    progressRows.forEach { $0.setActivityVisible(generationDetailsExpanded && generationAnimationsEnabled && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion) }
    needsLayout = true
    onLayoutChange?()
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
  private let activityIndicator = NSProgressIndicator()
  private var active = false

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    wantsLayer = true
    layer?.cornerRadius = 4
    layer?.masksToBounds = true
    activityIndicator.style = .spinning
    activityIndicator.controlSize = .small
    activityIndicator.isIndeterminate = true
    activityIndicator.isDisplayedWhenStopped = false
    iconView.imageScaling = .scaleProportionallyDown
    titleLabel.font = NSFont.systemFont(ofSize: 12, weight: .medium)
    titleLabel.textColor = .labelColor
    titleLabel.lineBreakMode = .byTruncatingTail
    detailLabel.font = NSFont.systemFont(ofSize: 11.5, weight: .regular)
    detailLabel.textColor = .secondaryLabelColor
    detailLabel.lineBreakMode = .byTruncatingTail
    [iconView, titleLabel, detailLabel, activityIndicator].forEach(addSubview)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func layout() {
    super.layout()
    iconView.frame = NSRect(x: 4, y: bounds.height - 23, width: 14, height: 14)
    activityIndicator.frame = iconView.frame
    titleLabel.frame = NSRect(x: 28, y: bounds.height - 24, width: max(0, bounds.width - 36), height: 18)
    detailLabel.frame = NSRect(
      x: 28,
      y: bounds.height - 43,
      width: max(0, bounds.width - 36),
      height: 18
    )
  }

  func apply(model: RagImeGenerationStageRowModel) {
    titleLabel.stringValue = model.title
    detailLabel.stringValue = model.detail
    detailLabel.toolTip = model.detail
    active = model.state == .active
    let symbol: String
    let color: NSColor
    switch model.state {
    case .done:
      symbol = "checkmark.circle.fill"
      color = .systemGreen
    case .active:
      symbol = "ellipsis.circle"
      color = .systemIndigo
    case .failed:
      symbol = "exclamationmark.triangle.fill"
      color = .systemOrange
    case .pending:
      symbol = "circle"
      color = .tertiaryLabelColor
    case .skipped:
      symbol = "minus.circle"
      color = .secondaryLabelColor
    }
    iconView.image = NSImage(systemSymbolName: symbol, accessibilityDescription: model.title)
    iconView.contentTintColor = color
    titleLabel.textColor = model.state == .pending ? .secondaryLabelColor : .labelColor
    detailLabel.textColor = model.state == .failed ? .systemOrange : .secondaryLabelColor
    switch model.state {
    case .active:
      layer?.backgroundColor = NSColor.selectedContentBackgroundColor.withAlphaComponent(0.055).cgColor
    case .failed:
      layer?.backgroundColor = NSColor.systemOrange.withAlphaComponent(0.05).cgColor
    case .done, .pending, .skipped:
      layer?.backgroundColor = NSColor.clear.cgColor
    }
    setAccessibilityLabel("\(model.title)（\(model.state.accessibilityWord)）：\(model.detail)")
  }

  func setActivityVisible(_ visible: Bool) {
    let animate = active && visible
    iconView.isHidden = animate
    if animate { activityIndicator.startAnimation(nil) }
    else { activityIndicator.stopAnimation(nil) }
  }

  func stopActivity() {
    activityIndicator.stopAnimation(nil)
    iconView.isHidden = false
  }
}
