import AppKit
import QuartzCore

final class RagImeSuggestionRowView: NSView {
  private let sourceBar = NSView()
  private let sourceIcon = NSImageView()
  private let sourceLabel = NSTextField(labelWithString: "")
  private let candidateLabel = NSTextField(labelWithString: "")
  private let shortcutPlate = NSView()
  private let shortcutLabel = NSTextField(labelWithString: "")
  private let separatorView = NSView()
  private let hitButton = NSButton()
  private var candidate: RagImeDisplayCandidate?
  private var sourceTint: NSColor = .systemBlue
  private var isPrimary = false
  private var isHovered = false
  private var trackingArea: NSTrackingArea?
  var showsSeparator = false {
    didSet { separatorView.isHidden = !showsSeparator }
  }
  var onSelect: ((RagImeDisplayCandidate) -> Void)?

  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    wantsLayer = true
    layer?.cornerRadius = 5
    sourceBar.wantsLayer = true
    sourceBar.layer?.cornerRadius = 1
    sourceIcon.imageScaling = .scaleProportionallyDown
    sourceIcon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 11, weight: .medium)
    sourceLabel.font = .systemFont(ofSize: 10.5, weight: .semibold)
    sourceLabel.lineBreakMode = .byTruncatingTail
    sourceLabel.maximumNumberOfLines = 1
    candidateLabel.font = .systemFont(ofSize: 14)
    candidateLabel.textColor = .labelColor
    candidateLabel.lineBreakMode = .byTruncatingTail
    candidateLabel.maximumNumberOfLines = 1
    shortcutLabel.font = .systemFont(ofSize: 10.5, weight: .medium)
    shortcutLabel.textColor = .tertiaryLabelColor
    shortcutLabel.lineBreakMode = .byClipping
    shortcutLabel.alignment = .right
    shortcutPlate.wantsLayer = true
    shortcutPlate.layer?.cornerRadius = 5
    shortcutPlate.layer?.borderWidth = 0.5
    separatorView.wantsLayer = true
    separatorView.layer?.backgroundColor = NSColor.separatorColor.withAlphaComponent(0.48).cgColor
    separatorView.isHidden = true
    hitButton.isBordered = false
    hitButton.title = ""
    hitButton.focusRingType = .none
    hitButton.target = self
    hitButton.action = #selector(selectCandidate)
    [sourceBar, sourceIcon, sourceLabel, candidateLabel, shortcutPlate, shortcutLabel, separatorView, hitButton].forEach(addSubview)
    updateAppearance()
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func layout() {
    super.layout()
    sourceBar.frame = NSRect(x: 0, y: 8, width: 3, height: 20)
    sourceIcon.frame = NSRect(x: 12, y: 10, width: 16, height: 16)
    sourceLabel.frame = NSRect(x: 33, y: 9, width: 34, height: 18)
    shortcutPlate.frame = NSRect(x: bounds.width - 80, y: 7, width: 68, height: 22)
    shortcutLabel.frame = NSRect(x: bounds.width - 76, y: 9, width: 60, height: 18)
    candidateLabel.frame = NSRect(x: 76, y: 7, width: max(52, bounds.width - 164), height: 22)
    separatorView.frame = NSRect(x: 76, y: 0, width: max(0, bounds.width - 88), height: 1)
    hitButton.frame = bounds
  }

  override func updateTrackingAreas() {
    super.updateTrackingAreas()
    if let trackingArea { removeTrackingArea(trackingArea) }
    let area = NSTrackingArea(
      rect: bounds,
      options: [.mouseEnteredAndExited, .activeAlways],
      owner: self,
      userInfo: nil
    )
    addTrackingArea(area)
    trackingArea = area
  }

  override func mouseEntered(with event: NSEvent) {
    isHovered = true
    updateAppearance(animated: true)
  }

  override func mouseExited(with event: NSEvent) {
    isHovered = false
    updateAppearance(animated: true)
  }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    separatorView.layer?.backgroundColor = NSColor.separatorColor.withAlphaComponent(0.48).cgColor
    shortcutPlate.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.58).cgColor
    updateAppearance()
  }

  func apply(candidate: RagImeDisplayCandidate, shortcut: String, isPrimary: Bool) {
    self.candidate = candidate
    self.isPrimary = isPrimary
    let text = candidate.text.trimmingCharacters(in: .whitespacesAndNewlines)
    candidateLabel.stringValue = text.isEmpty ? candidate.insertText : text
    sourceLabel.stringValue = sourceLabelText(for: candidate)
    sourceIcon.image = NSImage(systemSymbolName: sourceSymbolName(for: candidate), accessibilityDescription: sourceLabel.stringValue)
    sourceTint = sourceColor(for: candidate)
    shortcutLabel.stringValue = shortcut
    sourceLabel.textColor = sourceTint
    shortcutLabel.textColor = isPrimary ? .controlAccentColor : .secondaryLabelColor
    candidateLabel.font = .systemFont(ofSize: candidateLabel.font?.pointSize ?? 14, weight: isPrimary ? .medium : .regular)
    let contextHint = modelContextHint(for: candidate)
    toolTip = contextHint ?? (candidate.evidencePreview.isEmpty ? nil : candidate.evidencePreview)
    sourceIcon.toolTip = contextHint ?? sourceLabel.stringValue
    hitButton.setAccessibilityLabel("\(sourceLabel.stringValue) \(candidateLabel.stringValue), \(shortcut)")
    updateAppearance()
  }

  func applyCandidateFontSize(_ pointSize: CGFloat) {
    let clamped = min(max(pointSize, 11), 18)
    let weight = candidateLabel.font?.fontDescriptor.symbolicTraits.contains(.bold) == true
      ? NSFont.Weight.medium
      : NSFont.Weight.regular
    candidateLabel.font = .systemFont(ofSize: clamped, weight: weight)
  }

  func animateContentIn(delay: TimeInterval, reduceMotion: Bool) {
    layer?.removeAnimation(forKey: "rag-ime-row-content-in")
    guard !reduceMotion else { return }
    let opacity = CABasicAnimation(keyPath: "opacity")
    opacity.fromValue = 0
    opacity.toValue = 1
    let translation = CABasicAnimation(keyPath: "transform.translation.y")
    translation.fromValue = 3
    translation.toValue = 0
    let group = CAAnimationGroup()
    group.animations = [opacity, translation]
    group.beginTime = CACurrentMediaTime() + delay
    group.duration = 0.13
    group.timingFunction = CAMediaTimingFunction(name: .easeOut)
    group.isRemovedOnCompletion = true
    layer?.add(group, forKey: "rag-ime-row-content-in")
  }

  func animateAccepted(reduceMotion: Bool) {
    layer?.removeAnimation(forKey: "rag-ime-row-accepted")
    guard !reduceMotion else { return }
    let opacity = CABasicAnimation(keyPath: "opacity")
    opacity.fromValue = 1
    opacity.toValue = 0
    let translation = CABasicAnimation(keyPath: "transform.translation.x")
    translation.fromValue = 0
    translation.toValue = 5
    let group = CAAnimationGroup()
    group.animations = [opacity, translation]
    group.duration = 0.08
    group.timingFunction = CAMediaTimingFunction(name: .easeIn)
    layer?.add(group, forKey: "rag-ime-row-accepted")
  }

  @objc private func selectCandidate() {
    guard let candidate else { return }
    onSelect?(candidate)
  }

  private func sourceLabelText(for candidate: RagImeDisplayCandidate) -> String {
    let configured = (candidate.sourceBadge ?? candidate.badge ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let normalized = configured.lowercased()
    if normalized.contains("deepseek") || normalized == "ds" || configured.contains("生成") { return "DS" }
    switch candidate.sourceType {
    case "model": return "模型"
    case "rag": return "RAG"
    case "memory": return "记忆"
    case "deepseek", "ds": return "DS"
    default:
      if !configured.isEmpty { return String(configured.prefix(2)) }
      return "AI"
    }
  }

  private func modelContextHint(for candidate: RagImeDisplayCandidate) -> String? {
    guard candidate.sourceType == "model" else { return nil }
    guard case .number(let total)? = candidate.metadata["modelContextChars"], total > 0 else {
      return "MiniMind · 当前输入上下文"
    }
    let groupChars: Int
    if case .number(let value)? = candidate.metadata["groupContextChars"] {
      groupChars = max(0, Int(value))
    } else {
      groupChars = 0
    }
    if groupChars > 0 {
      return "MiniMind · 上下文 \(Int(total)) 字，含连续输入 \(groupChars) 字"
    }
    return "MiniMind · 上下文 \(Int(total)) 字"
  }

  private func sourceSymbolName(for candidate: RagImeDisplayCandidate) -> String {
    switch sourceLabelText(for: candidate) {
    case "DS": return "bolt.horizontal.circle"
    case "RAG": return "doc.text.magnifyingglass"
    case "记忆": return "clock.arrow.circlepath"
    default: return "sparkles"
    }
  }

  private func sourceColor(for candidate: RagImeDisplayCandidate) -> NSColor {
    let configured = (candidate.sourceBadge ?? candidate.badge ?? "").lowercased()
    if configured.contains("deepseek") || configured == "ds" || configured.contains("生成") {
      return .systemIndigo
    }
    switch candidate.sourceType {
    case "rag": return .systemTeal
    case "memory": return .systemOrange
    case "deepseek", "ds": return .systemIndigo
    default: return .systemBlue
    }
  }

  private func updateAppearance(animated: Bool = false) {
    let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    CATransaction.begin()
    CATransaction.setDisableActions(!animated || reduceMotion)
    CATransaction.setAnimationDuration(0.08)
    CATransaction.setAnimationTimingFunction(CAMediaTimingFunction(name: .easeOut))
    let backgroundAlpha: CGFloat = isHovered ? 0.11 : (isPrimary ? 0.045 : 0)
    layer?.backgroundColor = sourceTint.withAlphaComponent(backgroundAlpha).cgColor
    sourceBar.layer?.backgroundColor = sourceTint.withAlphaComponent(isPrimary ? 0.9 : 0.68).cgColor
    sourceIcon.contentTintColor = sourceTint
    shortcutPlate.layer?.backgroundColor = sourceTint.withAlphaComponent(isPrimary ? 0.08 : 0.035).cgColor
    shortcutPlate.layer?.borderColor = (isPrimary ? sourceTint : NSColor.separatorColor)
      .withAlphaComponent(isPrimary ? 0.28 : 0.58).cgColor
    CATransaction.commit()
  }
}
