import AppKit
import QuartzCore

final class RagImeAssistantPanelController {
  typealias TraceHandler = (_ event: String, _ fields: [String: Any]) -> Void
  private static weak var activeOwner: RagImeAssistantPanelController?
  private static var activeOwnerGeneration = 0
  private let panel: RagImeNonActivatingPanel
  private let cardView: RagImeSuggestionCardView
  private var currentPayload: RagImeAssistantOverlayPayload?
  private var currentRestore: (() -> Void)?
  private var currentState: RagImeAssistantSurfaceState = .hidden
  private var renderedSnapshotId = ""
  private var renderedStableIds: [String] = []
  private var renderedContentSignature = ""
  private var expandedSnapshotId = ""
  private var pendingUpdate: DispatchWorkItem?
  private var pendingSnapshotId = ""
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
  private weak var contextMenuAnchor: NSView?
  private var contextPopover: NSPopover?

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

  func dismissPendingPrediction(snapshotId: String, reason: String) {
    if pendingSnapshotId == snapshotId {
      pendingUpdate?.cancel()
      pendingUpdate = nil
      pendingSnapshotId = ""
    }
    guard currentState == .pendingPrediction,
      currentPayload?.snapshotId == snapshotId else { return }
    dismiss(reason: reason)
  }

  deinit {
    pendingUpdate?.cancel()
    ttlDismissWorkItem?.cancel()
    generatingTimer?.invalidate()
    contextPopover?.close()
    panel.orderOut(nil)
    if Self.activeOwner === self { Self.activeOwner = nil }
  }

  func update(
    _ payload: RagImeAssistantOverlayPayload?,
    anchor: NSPoint?,
    onSelect: ((RagImeDisplayCandidate, Int, RagImeAssistantCommitMode) -> Void)?,
    onAction: ((RagImeAssistantAction) -> Void)? = nil,
    onRestore: (() -> Void)? = nil,
    onDismiss: ((String) -> Void)? = nil,
    onTrace: TraceHandler? = nil
  ) {
    self.onSelect = onSelect
    self.onAction = onAction
    self.onDismiss = onDismiss
    self.onTrace = onTrace
    traceCreationIfNeeded()
    pendingUpdate?.cancel()
    pendingSnapshotId = payload?.snapshotId ?? ""
    let work = DispatchWorkItem { [weak self] in
      self?.pendingSnapshotId = ""
      self?.apply(payload, anchor: anchor, incomingRestore: onRestore)
    }
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
    let transitionDelay = reduceMotion ? 0 : Int(RagImeAssistantMotion.Duration.micro * 1000)
    DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(transitionDelay)) { [weak self] in
      guard let self, self.currentState == .transientConfirmation else { return }
      self.cardView.apply(state: .transientConfirmation, payload: payload)
      self.panel.setContentSize(NSSize(width: 224, height: RagImeSuggestionCardView.compactHeight))
    }
    DispatchQueue.main.asyncAfter(
      deadline: .now() + .milliseconds(RagImeAssistantMotion.confirmationHoldMilliseconds)
    ) { [weak self] in
      guard self?.currentState == .transientConfirmation else { return }
      self?.dismiss(reason: "confirmation_finished")
    }
  }

  func dismiss(reason: String) {
    if currentState.isExplicit && shouldKeepExplicitSurface(reason: reason) {
      trace("assistant_explicit_dismiss_suppressed", [
        "reason": reason,
        "snapshotId": currentPayload?.snapshotId ?? "",
        "surfaceState": currentState.rawValue,
      ])
      return
    }
    let hadPresentation = panel.isVisible || currentPayload != nil
    let fadeAnimation = currentPayload.map(fadeAnimationEnabled(for:)) ?? true
    pendingUpdate?.cancel()
    pendingUpdate = nil
    pendingSnapshotId = ""
    ttlDismissWorkItem?.cancel()
    ttlDismissWorkItem = nil
    let duration = visibleSince.map { Int(Date().timeIntervalSince($0) * 1000) } ?? 0
    currentPayload = nil
    currentRestore = nil
    contextPopover?.close()
    contextPopover = nil
    contextMenuAnchor = nil
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
        context.duration = RagImeAssistantMotion.Duration.micro
        context.timingFunction = RagImeAssistantMotion.timingFunction(.easeIn)
        panel.animator().alphaValue = 0
      } completionHandler: { [weak self] in
        guard let self else { return }
        if self.presentationGeneration == generation {
          self.panel.orderOut(nil)
        }
        self.panel.alphaValue = 1
      }
      trace("assistant_candidate_group_exit_animation_started", [
        "durationMs": Int(RagImeAssistantMotion.Duration.micro * 1000),
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

  private func apply(
    _ payload: RagImeAssistantOverlayPayload?,
    anchor: NSPoint?,
    incomingRestore: (() -> Void)?
  ) {
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
    if currentState.isExplicit && !state.isExplicit {
      trace("assistant_passive_update_suppressed_while_explicit", [
        "incomingSnapshotId": payload.snapshotId,
        "snapshotId": currentPayload?.snapshotId ?? "",
        "surfaceState": currentState.rawValue,
      ])
      return
    }
    currentRestore = incomingRestore
    if let anchor { lastReliableCaretAnchor = anchor }
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
    updateGeneratingAnimation(for: state, payload: payload)
    panel.ignoresMouseEvents = false
    let previousFrame = panel.frame
    let targetSize = contentSize(for: state, payload: payload)
    panel.setContentSize(targetSize)
    cardView.frame = NSRect(origin: .zero, size: targetSize)
    cardView.needsLayout = true
    cardView.layoutSubtreeIfNeeded()
    panel.contentView?.layoutSubtreeIfNeeded()
    position(state: state, anchor: anchor)
    let positionedFrame = panel.frame
    let reduceMotion = !animationsEnabled || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    let isPassivePrediction = state == .pendingPrediction
      || state == .compactPrediction
      || state == .expandedPredictions
    let shouldMorphFrame = wasVisible
      && !reduceMotion
      && !isPassivePrediction
      && (abs(previousFrame.width - positionedFrame.width) > 0.5
        || abs(previousFrame.height - positionedFrame.height) > 0.5)
    if shouldMorphFrame {
      panel.setFrame(previousFrame, display: false)
      NSAnimationContext.runAnimationGroup { context in
        context.duration = RagImeAssistantMotion.Duration.transition
        context.timingFunction = RagImeAssistantMotion.timingFunction()
        panel.animator().setFrame(positionedFrame, display: true)
      }
      trace("assistant_panel_frame_transition_started", [
        "durationMs": Int(RagImeAssistantMotion.Duration.transition * 1000),
        "fromWidth": previousFrame.width,
        "fromHeight": previousFrame.height,
        "toWidth": positionedFrame.width,
        "toHeight": positionedFrame.height,
        "surfaceState": state.rawValue,
      ])
    }
    scheduleTTL(for: payload)
    if !wasVisible {
      visibleSince = Date()
      let finalOrigin = panel.frame.origin
      panel.alphaValue = reduceMotion ? 1 : 0
      if !reduceMotion {
        panel.setFrameOrigin(NSPoint(
          x: finalOrigin.x,
          y: finalOrigin.y + RagImeAssistantMotion.Distance.tiny
        ))
      }
      panel.orderFront(nil)
      if !reduceMotion {
        let scale = CABasicAnimation(keyPath: "transform.scale")
        scale.fromValue = 0.985
        scale.toValue = 1
        scale.duration = RagImeAssistantMotion.Duration.entrance
        scale.timingFunction = RagImeAssistantMotion.timingFunction()
        cardView.layer?.add(scale, forKey: "rag-ime-panel-scale-in")
        NSAnimationContext.runAnimationGroup { context in
          context.duration = RagImeAssistantMotion.Duration.entrance
          context.timingFunction = RagImeAssistantMotion.timingFunction()
          panel.animator().alphaValue = 1
          panel.animator().setFrameOrigin(finalOrigin)
        }
      }
      trace("assistant_panel_present_animation_started", [
        "durationMs": reduceMotion ? 0 : Int(RagImeAssistantMotion.Duration.entrance * 1000),
        "style": reduceMotion ? "none" : "fade_translate_scale",
        "reduceMotion": reduceMotion,
      ])
      trace("assistant_panel_first_visible", ["surfaceState": state.rawValue, "snapshotId": payload.snapshotId])
    }
    if contentAnimated {
      trace("assistant_candidate_content_transition_started", [
        "durationMs": Int(RagImeAssistantMotion.Duration.entrance * 1000),
        "staggerMs": Int(RagImeAssistantMotion.stagger * 1000),
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
    if explicit {
      if explicitError(in: payload) { return .explicitError }
      if explicitNoSuggestion(in: payload) { return .explicitNoSuggestion }
      return realCandidates.isEmpty ? .explicitGenerating : .explicitResult
    }
    // A ready completion must win over a still-pending secondary lane. Otherwise
    // an already usable result collapses back to the 44pt waiting surface.
    if !realCandidates.isEmpty {
      if expandedSnapshotId == payload.snapshotId && realCandidates.count > 1 { return .expandedPredictions }
      return .compactPrediction
    }
    if payload.uiMode.contains("pending") || payload.inputMode == "post_commit_predicting" {
      return .pendingPrediction
    }
    return hasAction ? .compactPrediction : .hidden
  }

  private func updateGeneratingAnimation(for state: RagImeAssistantSurfaceState, payload: RagImeAssistantOverlayPayload) {
    let shouldAnimate = state == .explicitGenerating
      || (state == .pendingPrediction && payload.animation.kind != "none")
    guard shouldAnimate else {
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
      guard let self,
        self.currentState == .explicitGenerating || self.currentState == .pendingPrediction else { return }
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
    let predictionWidth = compactPredictionWidth(
      candidates: realCandidates,
      hasAction: hasAction,
      maximumWidth: configuredMaximumWidth,
      fontSize: candidateFontSize(for: payload)
    )
    switch state {
    case .pendingPrediction:
      return NSSize(
        width: min(configuredMaximumWidth, RagImeSuggestionCardView.pendingPredictionWidth),
        height: RagImeSuggestionCardView.pendingHeight
      )
    case .compactPrediction, .expandedPredictions:
      return NSSize(
        width: predictionWidth,
        height: RagImeSuggestionCardView.predictionHeight(candidateCount: realCandidates.count, hasAction: hasAction)
      )
    case .explicitGenerating:
      return NSSize(
        width: min(configuredMaximumWidth, RagImeSuggestionCardView.thinkingWidth),
        height: RagImeSuggestionCardView.thinkingHeight
      )
    case .explicitNoSuggestion, .explicitError:
      return NSSize(width: max(320, predictionWidth), height: RagImeSuggestionCardView.errorHeight)
    case .explicitResult:
      let text = realCandidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
      let resultWidth = min(configuredMaximumWidth, max(440, predictionWidth))
      return NSSize(
        width: max(RagImeSuggestionCardView.minimumPredictionWidth, resultWidth),
        height: RagImeSuggestionCardView.explicitResultHeight(text: text, width: resultWidth)
      )
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
    } else if let lastReliableCaretAnchor {
      resolved = (lastReliableCaretAnchor, state.isExplicit ? "last_reliable_caret" : "last_passive_caret")
    } else if state.isExplicit {
      let mouse = NSEvent.mouseLocation
      if NSScreen.screens.contains(where: { $0.visibleFrame.contains(mouse) }) {
        resolved = (mouse, "mouse")
      } else if let screen = NSScreen.main?.visibleFrame {
        resolved = (NSPoint(x: screen.midX, y: screen.midY), "screen_center")
      } else { resolved = nil }
    } else if let lastPositionedAnchor {
      resolved = (lastPositionedAnchor, "last_panel_anchor")
    } else {
      let mouse = NSEvent.mouseLocation
      if NSScreen.screens.contains(where: { $0.visibleFrame.contains(mouse) }) {
        resolved = (mouse, "passive_mouse_fallback")
      } else if let screen = NSScreen.main?.visibleFrame {
        resolved = (NSPoint(x: screen.midX, y: screen.midY), "passive_screen_center")
      } else { resolved = nil }
    }
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
    case .close:
      dismiss(reason: "user_close")
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

  private func shouldKeepExplicitSurface(reason: String) -> Bool {
    [
      "clear_display_candidates",
      "composition",
      "hidden",
      "passive_pending_or_status_only",
      "post_commit_overlay_hidden",
    ].contains(reason)
  }

  private func showMoreMenu(relativeTo sourceView: NSView) {
    contextMenuAnchor = sourceView
    let menu = NSMenu()
    let copy = NSMenuItem(title: "复制", action: #selector(copyResult), keyEquivalent: "")
    copy.target = self
    menu.addItem(copy)
    let context = NSMenuItem(title: "查看输入与依据", action: #selector(showContextInspector), keyEquivalent: "")
    context.target = self
    menu.addItem(context)
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

  @objc private func showContextInspector() {
    guard let payload = currentPayload else { return }
    let document = RagImeAssistantContextInspectorDocument.make(payload: payload)
    let viewController = RagImeAssistantContextInspectorViewController(document: document)
    let popover = NSPopover()
    popover.behavior = .transient
    popover.animates = !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    popover.contentSize = RagImeAssistantContextInspectorViewController.preferredSize
    popover.contentViewController = viewController
    contextPopover?.close()
    contextPopover = popover
    let anchor = contextMenuAnchor ?? cardView
    DispatchQueue.main.async { [weak self] in
      guard let self, anchor.window != nil, self.contextPopover === popover else { return }
      popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minX)
      self.trace("assistant_context_inspector_opened", [
        "snapshotId": payload.snapshotId,
        "contextSource": document.source,
        "sectionCount": document.sectionCount,
        "traceIncludesText": false,
      ])
    }
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
    if currentState.isExplicit {
      trace("assistant_explicit_result_pinned", [
        "snapshotId": payload.snapshotId,
        "surfaceState": currentState.rawValue,
        "dismissPolicy": "accept_close_retry_or_focus_change",
      ])
      return
    }
    let fallbackMs = 8_000
    let requestedMs = Int(payload.overlayConfigNumber("expiresAfterMs") ?? Double(payload.expiresAfterMs))
    let hasRealCandidate = payload.candidates.contains(where: RagImeSuggestionCardView.isRealCandidate)
    let pendingWithoutResult = currentState == .pendingPrediction
    let isNoResultFeedback = payload.statusText.contains("没有合适")
    let maximumMs = hasRealCandidate ? 30_000 : (pendingWithoutResult && !isNoResultFeedback ? 12_000 : 2_000)
    let boundedMs = min(max(requestedMs > 0 ? requestedMs : fallbackMs, 500), maximumMs)
    // A ready completion should not vanish while the user is deciding whether
    // to press Tab. New typing, focus changes, Escape, and stale guards still
    // dismiss it immediately.
    let expiresAfterMs = hasRealCandidate ? max(12_000, boundedMs) : boundedMs
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
        "ttlSource": hasRealCandidate
          ? (requestedMs > 0 ? "payload" : "fail_safe")
          : (pendingWithoutResult && !isNoResultFeedback ? "pending_feedback_guard" : "no_result_guard"),
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

  private func explicitError(in payload: RagImeAssistantOverlayPayload) -> Bool {
    if let transaction = payload.frontendTransaction,
      case .string(let status)? = transaction["diagnosticStatus"],
      status.contains("error") || status.contains("failed") {
      return true
    }
    let status = payload.statusText.lowercased()
    return status.contains("失败") || status.contains("error") || status.contains("failed")
  }

  private func explicitNoSuggestion(in payload: RagImeAssistantOverlayPayload) -> Bool {
    if let transaction = payload.frontendTransaction,
      case .string(let status)? = transaction["diagnosticStatus"],
      status == "no_suitable_suggestion" {
      return true
    }
    return payload.statusText.contains("没有合适")
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

  private func compactPredictionWidth(
    candidates: [RagImeDisplayCandidate],
    hasAction: Bool,
    maximumWidth: CGFloat,
    fontSize: CGFloat
  ) -> CGFloat {
    let attributes: [NSAttributedString.Key: Any] = [
      .font: RagImeAssistantTypography.candidate(pointSize: fontSize, primary: true),
    ]
    let widestText = candidates.map { candidate -> CGFloat in
      let text = candidate.text.isEmpty ? candidate.insertText : candidate.text
      return ceil((text as NSString).size(withAttributes: attributes).width)
    }.max() ?? 0
    let rowWidth = 56 + widestText + 16
    let actionWidth = hasAction ? RagImeSuggestionCardView.actionPredictionWidth : 0
    let contentWidth = max(
      RagImeSuggestionCardView.minimumPredictionWidth,
      max(rowWidth, actionWidth)
    )
    return min(maximumWidth, contentWidth)
  }

  private func fadeAnimationEnabled(for payload: RagImeAssistantOverlayPayload) -> Bool {
    payload.overlayConfigBool("fadeAnimation") ?? true
  }

  private func trace(_ event: String, _ fields: [String: Any]) { onTrace?(event, fields) }
}

private struct RagImeAssistantContextInspectorDocument {
  let attributedText: NSAttributedString
  let plainText: String
  let source: String
  let sectionCount: Int

  static func make(payload: RagImeAssistantOverlayPayload) -> RagImeAssistantContextInspectorDocument {
    let transaction = payload.frontendTransaction ?? [:]
    let contextView = object(transaction["contextView"])
    let source = string(contextView["source"])
    let attributed = NSMutableAttributedString(string: "")
    var plainSections: [String] = []
    var sectionCount = 0

    func appendSection(_ title: String, _ body: String) {
      let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmed.isEmpty else { return }
      let headingStyle = NSMutableParagraphStyle()
      headingStyle.paragraphSpacingBefore = sectionCount == 0 ? 0 : 14
      headingStyle.paragraphSpacing = 6
      attributed.append(NSAttributedString(
        string: "\(title)\n",
        attributes: [
          .font: NSFont.systemFont(ofSize: 12.5, weight: .semibold),
          .foregroundColor: NSColor.secondaryLabelColor,
          .paragraphStyle: headingStyle,
        ]
      ))
      let bodyStyle = NSMutableParagraphStyle()
      bodyStyle.lineSpacing = 3
      bodyStyle.paragraphSpacing = 0
      attributed.append(NSAttributedString(
        string: trimmed + "\n",
        attributes: [
          .font: NSFont.systemFont(ofSize: 13.5, weight: .regular),
          .foregroundColor: NSColor.labelColor,
          .paragraphStyle: bodyStyle,
        ]
      ))
      plainSections.append("\(title)\n\(trimmed)")
      sectionCount += 1
    }

    let currentRequest = string(contextView["currentRequest"])
    let currentContext = string(contextView["currentContext"])
    appendSection("本轮请求", currentRequest.isEmpty ? "本轮请求文本未返回" : currentRequest)
    appendSection("前台文本", currentContext.isEmpty ? "前台文本未返回" : currentContext)

    let windowContext = object(contextView["windowContext"])
    let windowNodes = array(windowContext["nodes"])
    let windowApplication = object(windowContext["application"])
    var windowLines: [String] = []
    let appName = string(windowApplication["name"])
    let windowTitle = string(windowApplication["windowTitle"])
    if !appName.isEmpty || !windowTitle.isEmpty {
      windowLines.append([appName, windowTitle].filter { !$0.isEmpty }.joined(separator: " · "))
    }
    for (index, value) in windowNodes.enumerated() {
      let node = object(value)
      let role = string(node["role"])
      let label = string(node["label"])
      let nodeValue = string(node["value"])
      let focused = bool(node["focused"])
      let secure = bool(node["secure"])
      let nodeRef = string(node["nodeRef"])
      var heading = "\(index + 1). \(role.isEmpty ? "AX 节点" : role)"
      if focused { heading += " · 焦点" }
      if !nodeRef.isEmpty { heading += " · \(nodeRef)" }
      windowLines.append(heading)
      if !label.isEmpty { windowLines.append("   标签：\(label)") }
      if secure {
        windowLines.append("   内容：安全字段，未读取")
      } else if !nodeValue.isEmpty {
        windowLines.append("   内容：\(nodeValue)")
      }
      let actions = array(node["actions"]).map { string($0) }.filter { !$0.isEmpty }
      if !actions.isEmpty { windowLines.append("   动作：\(actions.joined(separator: ", "))") }
    }
    if windowNodes.isEmpty {
      let semanticText = string(windowContext["semanticText"])
      if !semanticText.isEmpty { windowLines.append(semanticText) }
    }
    if windowLines.isEmpty {
      let captureMode = string(windowContext["captureMode"])
      let nodeCount = integer(windowContext["nodeCount"])
      let detail = captureMode.isEmpty ? "AX 未返回可读节点" : "AX 未返回可读节点（\(captureMode)，\(nodeCount) 个节点）"
      windowLines.append(detail)
    }
    appendSection("AX 窗口上下文", windowLines.joined(separator: "\n"))

    let recentInputs = array(contextView["recentCompleteInputs"])
    var recentLines: [String] = []
    for (index, value) in recentInputs.enumerated() {
      let item = object(value)
      let text = firstNonEmptyString(item, keys: ["textPreview", "text", "summary", "title"])
      if !text.isEmpty { recentLines.append("\(index + 1). \(text)") }
    }
    if recentLines.isEmpty {
      let reportedCount = integer(transaction["timelineRecentInputRecordCount"])
      recentLines.append(reportedCount > 0
        ? "Pi 报告使用了 \(reportedCount) 条历史补充，但本轮未返回可显示文本"
        : "本轮没有追加历史输入")
    }
    appendSection("历史补充", recentLines.joined(separator: "\n"))

    let planning = object(contextView["planning"])
    let planningItems = array(planning["items"])
    var planningLines: [String] = []
    for (index, value) in planningItems.enumerated() {
      let item = object(value)
      let title = firstNonEmptyString(item, keys: ["title", "detail", "notes"])
      if !title.isEmpty { planningLines.append("\(index + 1). \(title)") }
    }
    if !planningLines.isEmpty { appendSection("计划与任务", planningLines.joined(separator: "\n")) }

    var evidenceLines: [String] = []
    var seenEvidence = Set<String>()
    for value in array(contextView["evidenceHints"]) {
      let item = object(value)
      let text = item.isEmpty ? string(value) : firstNonEmptyString(item, keys: ["text", "preview", "title"])
      let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
      if !normalized.isEmpty, seenEvidence.insert(normalized).inserted {
        evidenceLines.append("\(evidenceLines.count + 1). \(normalized)")
      }
    }
    if evidenceLines.isEmpty {
      for card in payload.sourceCards {
        let text = [card.title, card.evidencePreview].filter { !$0.isEmpty }.joined(separator: "：")
        if !text.isEmpty, seenEvidence.insert(text).inserted {
          evidenceLines.append("\(evidenceLines.count + 1). \(text)")
        }
      }
    }
    if evidenceLines.isEmpty {
      let evidenceCount = integer(transaction["evidenceCount"])
      evidenceLines.append(evidenceCount > 0
        ? "已召回 \(evidenceCount) 条依据，但本轮未返回可显示片段"
        : "本轮没有注入 RAG 依据")
    }
    appendSection("RAG 依据", evidenceLines.joined(separator: "\n"))

    if sectionCount == 0 { appendSection("上下文", "本轮上下文不可用") }
    return RagImeAssistantContextInspectorDocument(
      attributedText: attributed,
      plainText: plainSections.joined(separator: "\n\n"),
      source: source.isEmpty ? "unknown" : source,
      sectionCount: sectionCount
    )
  }

  private static func string(_ value: RagImeJSONValue?) -> String {
    guard case .string(let text)? = value else { return "" }
    return text
  }

  private static func object(_ value: RagImeJSONValue?) -> [String: RagImeJSONValue] {
    guard case .object(let object)? = value else { return [:] }
    return object
  }

  private static func array(_ value: RagImeJSONValue?) -> [RagImeJSONValue] {
    guard case .array(let values)? = value else { return [] }
    return values
  }

  private static func bool(_ value: RagImeJSONValue?) -> Bool {
    guard case .bool(let result)? = value else { return false }
    return result
  }

  private static func integer(_ value: RagImeJSONValue?) -> Int {
    guard case .number(let result)? = value else { return 0 }
    return Int(result)
  }

  private static func firstNonEmptyString(
    _ object: [String: RagImeJSONValue],
    keys: [String]
  ) -> String {
    for key in keys {
      let value = string(object[key]).trimmingCharacters(in: .whitespacesAndNewlines)
      if !value.isEmpty { return value }
    }
    return ""
  }
}

private final class RagImeAssistantContextInspectorViewController: NSViewController {
  static let preferredSize = NSSize(width: 560, height: 520)
  private let document: RagImeAssistantContextInspectorDocument
  private let titleLabel = NSTextField(labelWithString: "本轮输入与依据")
  private let subtitleLabel = NSTextField(labelWithString: "")
  private let copyButton = NSButton()
  private let scrollView = NSScrollView()
  private let textView = NSTextView(frame: .zero)

  init(document: RagImeAssistantContextInspectorDocument) {
    self.document = document
    super.init(nibName: nil, bundle: nil)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func loadView() {
    let root = NSView(frame: NSRect(origin: .zero, size: Self.preferredSize))
    root.wantsLayer = true
    view = root

    titleLabel.font = NSFont.systemFont(ofSize: 14, weight: .semibold)
    titleLabel.textColor = .labelColor
    subtitleLabel.font = NSFont.systemFont(ofSize: 11.5, weight: .regular)
    subtitleLabel.textColor = .secondaryLabelColor
    subtitleLabel.stringValue = document.source == "provider_request"
      ? "本轮实际模型请求 · 仅保留于当前结果"
      : "前台请求快照 · 模型上下文尚未返回"

    copyButton.isBordered = false
    copyButton.bezelStyle = .inline
    copyButton.image = NSImage(systemSymbolName: "doc.on.doc", accessibilityDescription: "复制全部上下文")
    copyButton.toolTip = "复制全部上下文"
    copyButton.target = self
    copyButton.action = #selector(copyAllContext)

    scrollView.drawsBackground = false
    scrollView.borderType = .noBorder
    scrollView.hasVerticalScroller = true
    scrollView.autohidesScrollers = true
    textView.isEditable = false
    textView.isSelectable = true
    textView.drawsBackground = false
    textView.textContainerInset = NSSize(width: 8, height: 8)
    textView.isHorizontallyResizable = false
    textView.isVerticallyResizable = true
    textView.autoresizingMask = [.width]
    textView.textContainer?.widthTracksTextView = true
    textView.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
    textView.textStorage?.setAttributedString(document.attributedText)
    scrollView.documentView = textView

    [titleLabel, subtitleLabel, copyButton, scrollView].forEach { root.addSubview($0) }
  }

  override func viewDidLayout() {
    super.viewDidLayout()
    let bounds = view.bounds
    titleLabel.frame = NSRect(x: 16, y: bounds.height - 32, width: bounds.width - 72, height: 18)
    subtitleLabel.frame = NSRect(x: 16, y: bounds.height - 52, width: bounds.width - 72, height: 16)
    copyButton.frame = NSRect(x: bounds.width - 44, y: bounds.height - 45, width: 28, height: 28)
    scrollView.frame = NSRect(x: 8, y: 8, width: bounds.width - 16, height: bounds.height - 68)
    let contentWidth = max(0, scrollView.contentSize.width)
    if let textContainer = textView.textContainer, let layoutManager = textView.layoutManager {
      textContainer.containerSize = NSSize(width: max(0, contentWidth - 16), height: CGFloat.greatestFiniteMagnitude)
      layoutManager.ensureLayout(for: textContainer)
      let contentHeight = ceil(layoutManager.usedRect(for: textContainer).height) + 16
      textView.frame = NSRect(
        x: 0,
        y: 0,
        width: contentWidth,
        height: max(scrollView.contentSize.height, contentHeight)
      )
    }
  }

  @objc private func copyAllContext() {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(document.plainText, forType: .string)
  }
}
