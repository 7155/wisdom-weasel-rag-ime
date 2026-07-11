import AppKit
import QuartzCore

final class RagImeAssistantPanelController {
  typealias TraceHandler = (_ event: String, _ fields: [String: Any]) -> Void
  private static weak var activeOwner: RagImeAssistantPanelController?
  private static var activeOwnerGeneration = 0
  private let panel: RagImeNonActivatingPanel
  private let cardView: RagImeSuggestionCardView
  private var currentPayload: RagImeAssistantOverlayPayload?
  private var currentState: RagImeAssistantSurfaceState = .hidden
  private var renderedSnapshotId = ""
  private var renderedStableIds: [String] = []
  private var renderedContentSignature = ""
  private var expandedSnapshotId = ""
  private var pendingUpdate: DispatchWorkItem?
  private var ttlDismissWorkItem: DispatchWorkItem?
  private var lastReliableCaretAnchor: NSPoint?
  private var lastPositionedAnchor: NSPoint?
  private var lastPositionedSize: NSSize?
  private var visibleSince: Date?
  private var generatingTimer: Timer?
  private var generatingFrame = 0
  private var didTraceCreation = false
  private var presentationGeneration = 0
  private var ownershipGeneration = 0
  private var onSelect: ((RagImeDisplayCandidate, Int, RagImeAssistantCommitMode) -> Void)?
  private var onAction: ((RagImeAssistantAction) -> Void)?
  private var onDismiss: ((String) -> Void)?
  private var onTrace: TraceHandler?

  init() {
    panel = RagImeNonActivatingPanel(
      contentRect: NSRect(x: 0, y: 0, width: 240, height: RagImeSuggestionCardView.compactHeight),
      styleMask: [.borderless, .nonactivatingPanel],
      backing: .buffered,
      defer: false
    )
    cardView = RagImeSuggestionCardView(frame: panel.contentView?.bounds ?? .zero)
    panel.isReleasedWhenClosed = false
    panel.isFloatingPanel = true
    panel.level = .floating
    panel.backgroundColor = .clear
    panel.isOpaque = false
    panel.hasShadow = true
    panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient, .ignoresCycle]
    panel.contentView = cardView
    cardView.autoresizingMask = [.width, .height]
    cardView.onSelect = { [weak self] candidate, index, mode in self?.onSelect?(candidate, index, mode) }
    cardView.onAction = { [weak self] action in self?.handle(action) }
  }

  var isVisible: Bool { panel.isVisible }

  deinit {
    pendingUpdate?.cancel()
    ttlDismissWorkItem?.cancel()
    generatingTimer?.invalidate()
    panel.orderOut(nil)
    if Self.activeOwner === self { Self.activeOwner = nil }
  }

  func update(
    _ payload: RagImeAssistantOverlayPayload?,
    anchor: NSPoint?,
    onSelect: ((RagImeDisplayCandidate, Int, RagImeAssistantCommitMode) -> Void)?,
    onAction: ((RagImeAssistantAction) -> Void)? = nil,
    onDismiss: ((String) -> Void)? = nil,
    onTrace: TraceHandler? = nil
  ) {
    self.onSelect = onSelect
    self.onAction = onAction
    self.onDismiss = onDismiss
    self.onTrace = onTrace
    traceCreationIfNeeded()
    pendingUpdate?.cancel()
    let work = DispatchWorkItem { [weak self] in self?.apply(payload, anchor: anchor) }
    pendingUpdate = work
    DispatchQueue.main.async(execute: work)
    trace("assistant_panel_update_coalesced", ["reason": "main_runloop"])
  }

  func expandPredictions() -> Bool {
    guard currentState == .compactPrediction, let payload = currentPayload else { return false }
    guard payload.candidates.filter(RagImeSuggestionCardView.isRealCandidate).count > 1 else { return false }
    expandedSnapshotId = payload.snapshotId
    _ = applyVisible(payload, state: .expandedPredictions, anchor: lastReliableCaretAnchor, forceContent: true)
    return true
  }

  func showConfirmation(text _: String = "✓ 已插入") {
    guard let payload = currentPayload else { return }
    let reduceMotion = !fadeAnimationEnabled(for: payload) || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    currentState = .transientConfirmation
    cardView.animateAccepted(reduceMotion: reduceMotion)
    panel.ignoresMouseEvents = true
    trace("assistant_surface_state_changed", [
      "surfaceState": RagImeAssistantSurfaceState.transientConfirmation.rawValue,
      "snapshotId": payload.snapshotId,
      "reason": "candidate_accepted",
    ])
    let transitionDelay = reduceMotion ? 0 : 80
    DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(transitionDelay)) { [weak self] in
      guard let self, self.currentState == .transientConfirmation else { return }
      self.cardView.apply(state: .transientConfirmation, payload: payload)
      self.panel.setContentSize(NSSize(width: 224, height: RagImeSuggestionCardView.compactHeight))
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(360)) { [weak self] in
      guard self?.currentState == .transientConfirmation else { return }
      self?.dismiss(reason: "confirmation_finished")
    }
  }

  func dismiss(reason: String) {
    let hadPresentation = panel.isVisible || currentPayload != nil
    let fadeAnimation = currentPayload.map(fadeAnimationEnabled(for:)) ?? true
    pendingUpdate?.cancel()
    pendingUpdate = nil
    ttlDismissWorkItem?.cancel()
    ttlDismissWorkItem = nil
    let duration = visibleSince.map { Int(Date().timeIntervalSince($0) * 1000) } ?? 0
    currentPayload = nil
    currentState = .hidden
    renderedSnapshotId = ""
    renderedStableIds = []
    renderedContentSignature = ""
    expandedSnapshotId = ""
    visibleSince = nil
    stopGeneratingAnimation()
    if Self.activeOwner === self { Self.activeOwner = nil }
    presentationGeneration += 1
    let generation = presentationGeneration
    let reduceMotion = !fadeAnimation || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    if panel.isVisible && reason == "candidate_accepted" && !reduceMotion {
      cardView.animateAccepted(reduceMotion: false)
      NSAnimationContext.runAnimationGroup { context in
        context.duration = 0.08
        context.timingFunction = CAMediaTimingFunction(name: .easeIn)
        panel.animator().alphaValue = 0
      } completionHandler: { [weak self] in
        guard let self else { return }
        if self.presentationGeneration == generation {
          self.panel.orderOut(nil)
        }
        self.panel.alphaValue = 1
      }
      trace("assistant_candidate_group_exit_animation_started", [
        "durationMs": 80,
        "reduceMotion": false,
        "reason": reason,
      ])
    } else if panel.isVisible {
      panel.orderOut(nil)
      panel.alphaValue = 1
    }
    trace("assistant_panel_dismissed", ["reason": reason, "visibleDurationMs": duration])
    trace("assistant_surface_state_changed", ["surfaceState": RagImeAssistantSurfaceState.hidden.rawValue, "reason": reason])
    if hadPresentation { onDismiss?(reason) }
  }

  private func apply(_ payload: RagImeAssistantOverlayPayload?, anchor: NSPoint?) {
    let start = CFAbsoluteTimeGetCurrent()
    guard let payload, payload.visible else {
      dismiss(reason: payload?.dismissReason ?? "hidden")
      return
    }
    let state = surfaceState(for: payload)
    guard state != .hidden else {
      dismiss(reason: payload.phase == "composition" ? "composition" : "passive_pending_or_status_only")
      return
    }
    if let anchor { lastReliableCaretAnchor = anchor }
    if !state.isExplicit && anchor == nil {
      trace("assistant_panel_anchor_missing", ["surfaceState": state.rawValue, "anchorSource": "missing", "reason": "passive_requires_caret"])
      dismiss(reason: "passive_anchor_missing")
      return
    }
    guard applyVisible(payload, state: state, anchor: anchor, forceContent: false) else { return }
    trace("assistant_panel_content_updated", [
      "surfaceState": state.rawValue,
      "snapshotId": payload.snapshotId,
      "candidateCount": payload.candidates.count,
      "updateDurationMs": (CFAbsoluteTimeGetCurrent() - start) * 1000,
    ])
  }

  @discardableResult
  private func applyVisible(_ payload: RagImeAssistantOverlayPayload, state: RagImeAssistantSurfaceState, anchor: NSPoint?, forceContent: Bool) -> Bool {
    let stableIds = payload.candidates.filter {
      RagImeSuggestionCardView.isRealCandidate($0) || RagImeSuggestionCardView.isActionCandidate($0)
    }.map {
      $0.candidateStableId ?? "\($0.sourceType):\($0.insertText)"
    }
    let contentSignature = renderSignature(for: payload, state: state)
    if payload.snapshotId == renderedSnapshotId,
      stableIds == renderedStableIds,
      contentSignature == renderedContentSignature,
      state == currentState,
      !forceContent {
      currentPayload = payload
      position(state: state, anchor: anchor)
      scheduleTTL(for: payload)
      trace("assistant_panel_reused", ["snapshotId": payload.snapshotId, "reason": "same_snapshot_stable_ids"])
      return false
    }
    claimSingletonOwnership(snapshotId: payload.snapshotId)
    let wasVisible = panel.isVisible
    presentationGeneration += 1
    panel.alphaValue = 1
    currentPayload = payload
    currentState = state
    renderedSnapshotId = payload.snapshotId
    renderedStableIds = stableIds
    renderedContentSignature = contentSignature
    cardView.applyConfiguration(candidateFontSize: candidateFontSize(for: payload))
    let animationsEnabled = fadeAnimationEnabled(for: payload)
    let contentAnimated = cardView.apply(
      state: state,
      payload: payload,
      canReplaceSelection: canReplaceSelection(in: payload),
      animationsEnabled: animationsEnabled
    )
    updateGeneratingAnimation(for: state)
    panel.ignoresMouseEvents = false
    panel.setContentSize(contentSize(for: state, payload: payload))
    position(state: state, anchor: anchor)
    scheduleTTL(for: payload)
    if !wasVisible {
      visibleSince = Date()
      let reduceMotion = !animationsEnabled || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
      let finalOrigin = panel.frame.origin
      panel.alphaValue = reduceMotion ? 1 : 0
      if !reduceMotion {
        panel.setFrameOrigin(NSPoint(x: finalOrigin.x, y: finalOrigin.y + 3))
      }
      panel.orderFront(nil)
      if !reduceMotion {
        let scale = CABasicAnimation(keyPath: "transform.scale")
        scale.fromValue = 0.985
        scale.toValue = 1
        scale.duration = 0.12
        scale.timingFunction = CAMediaTimingFunction(name: .easeOut)
        cardView.layer?.add(scale, forKey: "rag-ime-panel-scale-in")
        NSAnimationContext.runAnimationGroup { context in
          context.duration = 0.12
          context.timingFunction = CAMediaTimingFunction(name: .easeOut)
          panel.animator().alphaValue = 1
          panel.animator().setFrameOrigin(finalOrigin)
        }
      }
      trace("assistant_panel_present_animation_started", [
        "durationMs": reduceMotion ? 0 : 120,
        "style": reduceMotion ? "none" : "fade_translate_scale",
        "reduceMotion": reduceMotion,
      ])
      trace("assistant_panel_first_visible", ["surfaceState": state.rawValue, "snapshotId": payload.snapshotId])
    }
    if contentAnimated {
      trace("assistant_candidate_content_transition_started", [
        "durationMs": 130,
        "staggerMs": 25,
        "candidateCount": stableIds.count,
        "reduceMotion": false,
      ])
    }
    if state.isExplicit {
      trace("assistant_context_diagnostics_rendered", [
        "diagnosticStatus": cardView.diagnosticStatusText,
        "sourceCardCount": payload.sourceCards.count,
        "hasFrontendTransaction": payload.frontendTransaction != nil,
        "traceIncludesText": false,
      ])
    }
    trace("assistant_surface_state_changed", [
      "surfaceState": state.rawValue,
      "snapshotId": payload.snapshotId,
      "candidateStableIds": stableIds,
      "candidateCount": stableIds.count,
      "sourceTypes": payload.candidates.map(\.sourceType),
      "reason": forceContent ? "user_expand" : "payload",
    ])
    return true
  }

  private func surfaceState(for payload: RagImeAssistantOverlayPayload) -> RagImeAssistantSurfaceState {
    if payload.phase == "composition" { return .hidden }
    let explicit = payload.phase == "active_rag" || payload.uiMode.contains("active_rag")
    let realCandidates = payload.candidates.filter(RagImeSuggestionCardView.isRealCandidate)
    let hasAction = payload.candidates.contains(where: RagImeSuggestionCardView.isActionCandidate)
    if explicit { return realCandidates.isEmpty ? .explicitGenerating : .explicitResult }
    guard !realCandidates.isEmpty || hasAction else { return .hidden }
    if expandedSnapshotId == payload.snapshotId && realCandidates.count > 1 { return .expandedPredictions }
    return .compactPrediction
  }

  private func updateGeneratingAnimation(for state: RagImeAssistantSurfaceState) {
    guard state == .explicitGenerating else {
      stopGeneratingAnimation()
      return
    }
    generatingFrame = 0
    let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    cardView.updateGeneratingFrame(generatingFrame, reduceMotion: reduceMotion)
    cardView.setGeneratingPulse(active: true, reduceMotion: reduceMotion)
    trace("assistant_generating_animation_started", [
      "intervalMs": 500,
      "reduceMotion": reduceMotion,
      "surfaceState": state.rawValue,
    ])
    guard !reduceMotion, generatingTimer == nil else { return }
    let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in
      guard let self, self.currentState == .explicitGenerating else { return }
      self.generatingFrame = (self.generatingFrame + 1) % 4
      self.cardView.updateGeneratingFrame(self.generatingFrame, reduceMotion: false)
    }
    generatingTimer = timer
    RunLoop.main.add(timer, forMode: .common)
  }

  private func stopGeneratingAnimation() {
    let wasRunning = generatingTimer != nil
    generatingTimer?.invalidate()
    generatingTimer = nil
    generatingFrame = 0
    cardView.setGeneratingPulse(active: false, reduceMotion: true)
    if wasRunning {
      trace("assistant_generating_animation_stopped", ["reason": "surface_state_changed"])
    }
  }

  private func contentSize(for state: RagImeAssistantSurfaceState, payload: RagImeAssistantOverlayPayload) -> NSSize {
    let realCandidates = payload.candidates.filter(RagImeSuggestionCardView.isRealCandidate)
    let hasAction = payload.candidates.contains(where: RagImeSuggestionCardView.isActionCandidate)
    let configuredMaximumWidth = maximumWidth(for: payload)
    let width = min(
      configuredMaximumWidth,
      max(RagImeSuggestionCardView.minimumPredictionWidth, RagImeSuggestionCardView.preferredPredictionWidth)
    )
    switch state {
    case .compactPrediction, .expandedPredictions:
      return NSSize(
        width: width,
        height: RagImeSuggestionCardView.predictionHeight(candidateCount: realCandidates.count, hasAction: hasAction)
      )
    case .explicitGenerating: return NSSize(width: max(300, width), height: RagImeSuggestionCardView.thinkingHeight)
    case .explicitResult:
      let text = realCandidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
      let rect = (text as NSString).boundingRect(
        with: NSSize(width: max(336, width - 24), height: 1000),
        options: [.usesLineFragmentOrigin, .usesFontLeading],
        attributes: [.font: NSFont.systemFont(ofSize: 13.5)]
      )
      return NSSize(width: max(320, width), height: min(220, max(108, ceil(rect.height) + 88)))
    case .transientConfirmation, .hidden:
      return NSSize(width: 224, height: RagImeSuggestionCardView.compactHeight)
    }
  }

  private func position(state: RagImeAssistantSurfaceState, anchor: NSPoint?) {
    let start = CFAbsoluteTimeGetCurrent()
    let resolved: (NSPoint, String)?
    if let anchor {
      lastReliableCaretAnchor = anchor
      resolved = (anchor, "caret")
    } else if state.isExplicit, let lastReliableCaretAnchor {
      resolved = (lastReliableCaretAnchor, "last_reliable_caret")
    } else if state.isExplicit {
      let mouse = NSEvent.mouseLocation
      if NSScreen.screens.contains(where: { $0.visibleFrame.contains(mouse) }) {
        resolved = (mouse, "mouse")
      } else if let screen = NSScreen.main?.visibleFrame {
        resolved = (NSPoint(x: screen.midX, y: screen.midY), "screen_center")
      } else { resolved = nil }
    } else { resolved = nil }
    guard let (point, source) = resolved else { return }
    let size = panel.frame.size
    if let lastPositionedAnchor,
      let lastPositionedSize,
      abs(lastPositionedAnchor.x - point.x) <= 8,
      abs(lastPositionedAnchor.y - point.y) <= 8,
      abs(lastPositionedSize.width - size.width) < 0.5,
      abs(lastPositionedSize.height - size.height) < 0.5,
      panel.isVisible { return }
    lastPositionedAnchor = point
    lastPositionedSize = size
    guard let screen = (NSScreen.screens.first { $0.visibleFrame.contains(point) } ?? NSScreen.main)?.visibleFrame else { return }
    var origin = NSPoint(x: point.x, y: point.y - size.height - 6)
    if origin.y < screen.minY + 8 { origin.y = point.y + 22 }
    origin.x = min(max(origin.x, screen.minX + 8), screen.maxX - size.width - 8)
    origin.y = min(max(origin.y, screen.minY + 8), screen.maxY - size.height - 8)
    panel.setFrameOrigin(origin)
    trace("assistant_panel_positioned", [
      "surfaceState": state.rawValue,
      "anchorSource": source,
      "positionDurationMs": (CFAbsoluteTimeGetCurrent() - start) * 1000,
    ])
  }

  private func handle(_ action: RagImeAssistantAction) {
    switch action {
    case .insert:
      guard let payload = currentPayload,
        let index = payload.candidates.firstIndex(where: RagImeSuggestionCardView.isRealCandidate) else { return }
      onSelect?(payload.candidates[index], index, .insert)
    case .replace:
      guard let payload = currentPayload,
        canReplaceSelection(in: payload),
        let index = payload.candidates.firstIndex(where: RagImeSuggestionCardView.isRealCandidate) else { return }
      onSelect?(payload.candidates[index], index, .replace)
    case .more(let sourceView): showMoreMenu(relativeTo: sourceView)
    default: onAction?(action)
    }
  }

  private func showMoreMenu(relativeTo sourceView: NSView) {
    let menu = NSMenu()
    let copy = NSMenuItem(title: "复制", action: #selector(copyResult), keyEquivalent: "")
    copy.target = self
    menu.addItem(copy)
    let evidence = NSMenuItem(title: "查看依据", action: #selector(copyEvidence), keyEquivalent: "")
    evidence.target = self
    menu.addItem(evidence)
    menu.addItem(.separator())
    let remember = NSMenuItem(title: "记住", action: #selector(rememberResult), keyEquivalent: "")
    remember.target = self
    menu.addItem(remember)
    let suppress = NSMenuItem(title: "不再推荐", action: #selector(suppressResult), keyEquivalent: "")
    suppress.target = self
    menu.addItem(suppress)
    menu.popUp(positioning: nil, at: NSPoint(x: 0, y: sourceView.bounds.height), in: sourceView)
  }

  @objc private func copyResult() {
    guard let candidate = currentPayload?.candidates.first(where: RagImeSuggestionCardView.isRealCandidate) else { return }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(candidate.text.isEmpty ? candidate.insertText : candidate.text, forType: .string)
  }

  @objc private func copyEvidence() {
    guard let evidence = currentPayload?.candidates.first(where: RagImeSuggestionCardView.isRealCandidate)?.evidencePreview,
      !evidence.isEmpty else { return }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(evidence, forType: .string)
  }

  @objc private func rememberResult() { onAction?(.remember) }

  @objc private func suppressResult() { onAction?(.suppress) }

  private func canReplaceSelection(in payload: RagImeAssistantOverlayPayload) -> Bool {
    guard payload.phase == "active_rag",
      let candidate = payload.candidates.first(where: RagImeSuggestionCardView.isRealCandidate),
      case .string(let placement)? = candidate.metadata["placement"],
      placement == "replace_selection",
      case .string(let selectedTextHash)? = candidate.metadata["selectedTextHash"] else { return false }
    return !selectedTextHash.isEmpty
  }

  private func traceCreationIfNeeded() {
    guard !didTraceCreation else { return }
    didTraceCreation = true
    trace("assistant_panel_created", ["createCount": 1])
  }

  private func claimSingletonOwnership(snapshotId: String) {
    if let previous = Self.activeOwner, previous !== self {
      let previousWasVisible = previous.isVisible
      previous.dismiss(reason: "singleton_replaced")
      trace("assistant_overlay_singleton_replaced", [
        "snapshotId": snapshotId,
        "previousOwnerVisible": previousWasVisible,
      ])
    }
    Self.activeOwnerGeneration += 1
    ownershipGeneration = Self.activeOwnerGeneration
    Self.activeOwner = self
  }

  private func scheduleTTL(for payload: RagImeAssistantOverlayPayload) {
    ttlDismissWorkItem?.cancel()
    ttlDismissWorkItem = nil
    let fallbackMs = currentState.isExplicit ? 20_000 : 8_000
    let requestedMs = Int(payload.overlayConfigNumber("expiresAfterMs") ?? Double(payload.expiresAfterMs))
    let expiresAfterMs = min(max(requestedMs > 0 ? requestedMs : fallbackMs, 500), 30_000)
    let snapshotId = payload.snapshotId
    let generation = ownershipGeneration
    let work = DispatchWorkItem { [weak self] in
      guard let self,
        Self.activeOwner === self,
        self.ownershipGeneration == generation,
        self.currentPayload?.snapshotId == snapshotId else { return }
      self.trace("assistant_overlay_ttl_expired", [
        "snapshotId": snapshotId,
        "expiresAfterMs": expiresAfterMs,
        "ttlSource": requestedMs > 0 ? "payload" : "fail_safe",
      ])
      self.dismiss(reason: "ttl_expired")
    }
    ttlDismissWorkItem = work
    DispatchQueue.main.asyncAfter(
      deadline: .now() + .milliseconds(expiresAfterMs),
      execute: work
    )
  }

  private func renderSignature(for payload: RagImeAssistantOverlayPayload, state: RagImeAssistantSurfaceState) -> String {
    let candidateParts = payload.candidates.filter {
      RagImeSuggestionCardView.isRealCandidate($0) || RagImeSuggestionCardView.isActionCandidate($0)
    }.map { candidate in
      [
        candidate.candidateStableId ?? "",
        candidate.sourceType,
        candidate.text,
        candidate.insertText,
        candidate.evidencePreview,
        canReplaceSelection(in: payload) ? "replace" : "insert",
      ].joined(separator: "\u{1f}")
    }
    let sourceParts = payload.sourceCards.map { card in
      [card.sourceType, card.sourceBadge, card.title, card.evidencePreview].joined(separator: "\u{1f}")
    }
    let transactionParts = (payload.frontendTransaction ?? [:]).keys.sorted().map { key in
      "\(key)=\(String(describing: payload.frontendTransaction?[key]))"
    }
    let headerParts: [String] = [
      state.rawValue,
      payload.snapshotId,
      payload.statusText,
      String(payload.expiresAfterMs),
      payload.dismissReason,
      String(describing: candidateFontSize(for: payload)),
      String(describing: maximumWidth(for: payload)),
      String(fadeAnimationEnabled(for: payload)),
    ]
    let allParts = headerParts + candidateParts + sourceParts + transactionParts
    return allParts.joined(separator: "\u{1e}")
  }

  private func candidateFontSize(for payload: RagImeAssistantOverlayPayload) -> CGFloat {
    min(max(CGFloat(payload.overlayConfigNumber("candidateFontSize") ?? 14), 11), 18)
  }

  private func maximumWidth(for payload: RagImeAssistantOverlayPayload) -> CGFloat {
    min(
      max(CGFloat(payload.overlayConfigNumber("maxWidth") ?? Double(RagImeSuggestionCardView.maximumPredictionWidth)),
          RagImeSuggestionCardView.minimumPredictionWidth),
      520
    )
  }

  private func fadeAnimationEnabled(for payload: RagImeAssistantOverlayPayload) -> Bool {
    payload.overlayConfigBool("fadeAnimation") ?? true
  }

  private func trace(_ event: String, _ fields: [String: Any]) { onTrace?(event, fields) }
}
