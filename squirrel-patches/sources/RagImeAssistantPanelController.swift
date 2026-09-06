import AppKit
import QuartzCore

final class RagImeAssistantPanelController: NSObject {
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
  private var generatingMotionSuppressed = false
  private var didTraceCreation = false
  private var presentationGeneration = 0
  private var ownershipGeneration = 0
  private var onSelect: ((RagImeDisplayCandidate, Int, RagImeAssistantCommitMode) -> Void)?
  private var onAction: ((RagImeAssistantAction) -> Void)?
  private var onDismiss: ((String) -> Void)?
  private var onTrace: TraceHandler?
  private weak var contextMenuAnchor: NSView?
  private var contextInspectorWindowController: NSWindowController?
  private var contextMenuDocument: RagImeAssistantContextInspectorDocument?
  private var contextInspectorPresentation: ContextInspectorPresentation?

  private struct ContextInspectorPresentation {
    let snapshotId: String
    let panelFrame: NSRect
    let resultViewport: RagImeSuggestionCardView.ResultViewportSnapshot?
  }

  override init() {
    panel = RagImeNonActivatingPanel(
      contentRect: NSRect(x: 0, y: 0, width: 240, height: RagImeSuggestionCardView.compactHeight),
      styleMask: [.borderless, .nonactivatingPanel],
      backing: .buffered,
      defer: false
    )
    cardView = RagImeSuggestionCardView(frame: panel.contentView?.bounds ?? .zero)
    super.init()
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
    cardView.onLayoutChange = { [weak self] in
      guard let self, self.currentState == .explicitGenerating,
        let payload = self.currentPayload else { return }
      _ = self.applyVisible(payload, state: .explicitGenerating, anchor: self.lastReliableCaretAnchor, forceContent: true)
    }
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
    let inspectorWindowController = contextInspectorWindowController
    let window = panel
    let closeUI = {
      inspectorWindowController?.close()
      window.orderOut(nil)
    }
    if Thread.isMainThread {
      closeUI()
    } else {
      DispatchQueue.main.async(execute: closeUI)
    }
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

  func showConfirmation(text: String = "✓ 已插入") {
    guard let payload = currentPayload else { return }
    let reduceMotion = !fadeAnimationEnabled(for: payload) || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    currentState = .transientConfirmation
    cardView.setConfirmationText(text)
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
    let reduceMotion = !fadeAnimationEnabled(for: payload) || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    generatingMotionSuppressed = reduceMotion
    cardView.updateGeneratingFrame(generatingFrame, reduceMotion: reduceMotion)
    cardView.setGeneratingPulse(active: state == .pendingPrediction, reduceMotion: reduceMotion)
    trace("assistant_generating_animation_started", [
      "intervalMs": 1000,
      "reduceMotion": reduceMotion,
      "surfaceState": state.rawValue,
    ])
    // Elapsed time is status information, so it remains live under reduced motion.
    guard (state == .explicitGenerating || !reduceMotion), generatingTimer == nil else { return }
    let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
      guard let self,
        self.currentState == .explicitGenerating || self.currentState == .pendingPrediction else { return }
      self.generatingFrame = (self.generatingFrame + 1) % 4
      let motionSuppressed = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        || !(self.currentPayload.map(self.fadeAnimationEnabled(for:)) ?? true)
      if motionSuppressed != self.generatingMotionSuppressed {
        self.generatingMotionSuppressed = motionSuppressed
        self.cardView.setGeneratingPulse(active: self.currentState == .pendingPrediction, reduceMotion: motionSuppressed)
      }
      self.cardView.updateGeneratingFrame(self.generatingFrame, reduceMotion: motionSuppressed)
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
    cardView.stopGenerationProgress()
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
        height: cardView.generationHeight
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
    contextMenuDocument = currentPayload.map {
      RagImeAssistantContextInspectorDocument.make(payload: $0)
    }
    let unavailableReason = contextMenuDocument?.unavailableReason
      ?? "当前结果已失效，请重新生成后再查看"
    let menu = NSMenu()
    menu.autoenablesItems = false

    let copy = NSMenuItem(title: "复制", action: #selector(copyResult), keyEquivalent: "")
    copy.target = self
    copy.isEnabled = currentPayload?.candidates.contains(where: RagImeSuggestionCardView.isRealCandidate) == true
    menu.addItem(copy)

    let context = NSMenuItem(title: "查看输入与依据", action: #selector(showContextInspector), keyEquivalent: "e")
    context.keyEquivalentModifierMask = [.command, .option]
    context.target = self
    context.isEnabled = contextMenuDocument != nil
    context.toolTip = contextMenuDocument?.isAvailable == true
      ? "查看本轮实际输入、连续历史与知识依据"
      : "打开后查看本轮输入或依据为何不可用"
    context.setAccessibilityLabel("查看本轮输入与依据")
    menu.addItem(context)
    if contextMenuDocument?.isAvailable != true {
      let reason = NSMenuItem(title: "内容状态：\(unavailableReason)", action: nil, keyEquivalent: "")
      reason.isEnabled = false
      reason.toolTip = unavailableReason
      menu.addItem(reason)
    }

    menu.addItem(.separator())
    let remember = NSMenuItem(title: "记住", action: #selector(rememberResult), keyEquivalent: "")
    remember.target = self
    remember.isEnabled = true
    menu.addItem(remember)
    let suppress = NSMenuItem(title: "不再推荐", action: #selector(suppressResult), keyEquivalent: "")
    suppress.target = self
    suppress.isEnabled = true
    menu.addItem(suppress)
    menu.popUp(positioning: nil, at: NSPoint(x: 0, y: sourceView.bounds.height), in: sourceView)
  }

  @objc private func copyResult() {
    guard let candidate = currentPayload?.candidates.first(where: RagImeSuggestionCardView.isRealCandidate) else { return }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(candidate.text.isEmpty ? candidate.insertText : candidate.text, forType: .string)
  }

  @objc private func showContextInspector() {
    let document = contextMenuDocument ?? currentPayload.map {
      RagImeAssistantContextInspectorDocument.make(payload: $0)
    }
    contextMenuDocument = nil
    guard let document else {
      trace("assistant_context_inspector_unavailable", [
        "reason": "current_result_missing",
        "traceIncludesText": false,
      ])
      return
    }
    if let previousWindowController = contextInspectorWindowController {
      closeContextInspector(previousWindowController, reason: "replaced")
    }
    contextInspectorPresentation = ContextInspectorPresentation(
      snapshotId: document.snapshotId,
      panelFrame: panel.frame,
      resultViewport: cardView.captureResultViewport()
    )
    let inspectorPanel = RagImeNonActivatingPanel(
      contentRect: NSRect(origin: .zero, size: RagImeAssistantContextInspectorViewController.preferredSize),
      styleMask: [.borderless, .nonactivatingPanel],
      backing: .buffered,
      defer: false
    )
    inspectorPanel.isReleasedWhenClosed = false
    inspectorPanel.isFloatingPanel = true
    inspectorPanel.level = .floating
    inspectorPanel.backgroundColor = .clear
    inspectorPanel.isOpaque = false
    inspectorPanel.hasShadow = true
    inspectorPanel.hidesOnDeactivate = false
    inspectorPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient, .ignoresCycle]
    let windowController = NSWindowController(window: inspectorPanel)
    let viewController = RagImeAssistantContextInspectorViewController(
      document: document,
      onClose: { [weak self, weak windowController] in
        guard let self, let windowController,
          self.contextInspectorWindowController === windowController else { return }
        self.closeContextInspector(windowController, reason: "explicit_close")
      },
      onRetry: { [weak self, weak windowController] in
        guard let self, let windowController,
          self.contextInspectorWindowController === windowController else { return }
        self.closeContextInspector(windowController, reason: "retry")
        self.onAction?(.retry)
      }
    )
    inspectorPanel.contentViewController = viewController
    contextInspectorWindowController = windowController
    let anchor = contextMenuAnchor ?? cardView
    DispatchQueue.main.async { [weak self] in
      guard let self,
        self.contextInspectorWindowController === windowController else { return }
      self.positionContextInspector(inspectorPanel, relativeTo: anchor)
      inspectorPanel.orderFront(nil)
      self.trace("assistant_context_inspector_opened", [
        "snapshotId": document.snapshotId,
        "contextSource": document.source,
        "contentState": document.state.rawValue,
        "sectionCount": document.sectionCount,
        "traceIncludesText": false,
      ])
    }
  }

  private func positionContextInspector(_ inspectorPanel: NSPanel, relativeTo anchor: NSView) {
    let size = RagImeAssistantContextInspectorViewController.preferredSize
    let anchorFrame = anchor.window.map {
      $0.convertToScreen(anchor.convert(anchor.bounds, to: nil))
    } ?? panel.frame
    let visibleFrame = (anchor.window?.screen ?? panel.screen ?? NSScreen.main)?.visibleFrame
      ?? NSRect(origin: .zero, size: size)
    let spacing: CGFloat = 8
    var x = anchorFrame.maxX + spacing
    if x + size.width > visibleFrame.maxX {
      x = anchorFrame.minX - size.width - spacing
    }
    x = min(max(x, visibleFrame.minX), max(visibleFrame.minX, visibleFrame.maxX - size.width))
    let y = min(
      max(anchorFrame.maxY - size.height, visibleFrame.minY),
      max(visibleFrame.minY, visibleFrame.maxY - size.height)
    )
    inspectorPanel.setFrame(NSRect(x: x, y: y, width: size.width, height: size.height), display: true)
  }

  private func closeContextInspector(_ windowController: NSWindowController, reason: String) {
    guard contextInspectorWindowController === windowController else { return }
    let presentation = contextInspectorPresentation
    contextInspectorWindowController = nil
    contextInspectorPresentation = nil
    windowController.close()
    if let presentation,
      currentPayload?.snapshotId == presentation.snapshotId,
      panel.isVisible {
      panel.setFrame(presentation.panelFrame, display: false)
      cardView.restoreResultViewport(presentation.resultViewport)
    }
    trace("assistant_context_inspector_closed", [
      "reason": reason,
      "traceIncludesText": false,
    ])
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
    if currentState.isExplicit && currentState != .explicitGenerating {
      trace("assistant_explicit_surface_pinned", [
        "snapshotId": payload.snapshotId,
        "surfaceState": currentState.rawValue,
        "dismissPolicy": "accept_close_retry_or_focus_change",
      ])
      return
    }
    let fallbackMs = 4_000
    let requestedMs = Int(payload.overlayConfigNumber("expiresAfterMs") ?? Double(payload.expiresAfterMs))
    let hasRealCandidate = payload.candidates.contains(where: RagImeSuggestionCardView.isRealCandidate)
    let pendingWithoutResult = currentState == .pendingPrediction
    let explicitGeneration = currentState == .explicitGenerating
    let isNoResultFeedback = payload.statusText.contains("没有合适")
    let maximumMs = hasRealCandidate
      ? 30_000
      : (explicitGeneration ? 30_000 : (pendingWithoutResult && !isNoResultFeedback ? 12_000 : 2_000))
    let boundedMs = min(
      max(requestedMs > 0 ? requestedMs : fallbackMs, 500),
      maximumMs
    )
    // The setting controls a ready result, not an in-flight request. Keep the
    // pending prediction guard alive for its bounded request window so a
    // 4-second result preference cannot hide work that is still generating.
    // New typing, focus changes, Escape, and stale guards remain immediate.
    let expiresAfterMs = pendingWithoutResult && !isNoResultFeedback
      ? max(12_000, boundedMs)
      : boundedMs
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
          : (explicitGeneration
            ? "active_rag_budget"
            : (pendingWithoutResult && !isNoResultFeedback ? "pending_feedback_guard" : "no_result_guard")),
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
        candidate.assistantPresentationSignature,
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
      payload.animation.kind,
      String(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion),
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
    if case .string("sensitive_field_blocked")? = payload.frontendTransaction?["diagnosticStatus"] {
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

private enum RagImeAssistantContextInspectorState: String {
  case content
  case loading
  case empty
  case error

  var title: String {
    switch self {
    case .content: return "本轮输入与依据"
    case .loading: return "正在准备输入与依据"
    case .empty: return "没有可显示的输入与依据"
    case .error: return "输入与依据暂不可用"
    }
  }

  var accessibilityLabel: String {
    switch self {
    case .content: return "输入与依据已就绪"
    case .loading: return "输入与依据正在加载"
    case .empty: return "输入与依据为空"
    case .error: return "输入与依据加载失败"
    }
  }
}

private struct RagImeAssistantContextInspectorDocument {
  let snapshotId: String
  let attributedText: NSAttributedString
  let plainText: String
  let source: String
  let summary: String
  let sectionCount: Int
  let state: RagImeAssistantContextInspectorState
  let isAvailable: Bool
  let unavailableReason: String

  static func make(payload: RagImeAssistantOverlayPayload) -> RagImeAssistantContextInspectorDocument {
    let transaction = payload.frontendTransaction ?? [:]
    let contextView = object(transaction["contextView"])
    let source = string(contextView["source"])
    let attributed = NSMutableAttributedString(string: "")
    var plainSections: [String] = []
    var sectionCount = 0
    var inputCount = 0
    var historyCount = 0
    var ragCount = 0
    var knowledgeCount = 0
    var evidenceStateOnly = false
    let diagnosticStatus = string(transaction["diagnosticStatus"]).lowercased()
    let progressStage = string(transaction["progressStage"]).lowercased()

    func appendSection(_ title: String, _ body: String) {
      let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !trimmed.isEmpty else { return }
      let headingStyle = NSMutableParagraphStyle()
      headingStyle.paragraphSpacingBefore = sectionCount == 0 ? 0 : 16
      headingStyle.paragraphSpacing = 6
      attributed.append(NSAttributedString(
        string: "\(title.uppercased())\n",
        attributes: [
          .font: RagImeAssistantTypography.inspectorSection,
          .foregroundColor: NSColor.secondaryLabelColor,
          .paragraphStyle: headingStyle,
        ]
      ))
      let bodyStyle = NSMutableParagraphStyle()
      bodyStyle.lineSpacing = 3
      bodyStyle.paragraphSpacing = 2
      attributed.append(NSAttributedString(
        string: trimmed + "\n",
        attributes: [
          .font: RagImeAssistantTypography.inspectorBody,
          .foregroundColor: NSColor.labelColor,
          .paragraphStyle: bodyStyle,
        ]
      ))
      plainSections.append("\(title)\n\(trimmed)")
      sectionCount += 1
    }

    let currentRequest = boundedParagraph(string(contextView["currentRequest"]), limit: 2_400)
    let currentContext = boundedParagraph(string(contextView["currentContext"]), limit: 4_800)
    let selectedText = boundedParagraph(string(contextView["selectedText"]), limit: 2_400)
    if !currentRequest.isEmpty {
      appendSection("本轮输入", currentRequest)
      inputCount += 1
    }
    if !selectedText.isEmpty, selectedText != currentRequest {
      appendSection("选中文本", selectedText)
      inputCount += 1
    }
    if !currentContext.isEmpty, currentContext != currentRequest, currentContext != selectedText {
      appendSection("前台承接文本", currentContext)
      inputCount += 1
    }

    let windowContext = object(contextView["windowContext"])
    if !windowContext.isEmpty {
      let windowNodes = array(windowContext["nodes"])
      let sourceNodeCount = integer(windowContext["sourceNodeCount"])
      let windowApplication = object(windowContext["application"])
      var windowLines: [String] = []
      let appName = compactLine(string(windowApplication["name"]), limit: 80)
      let windowTitle = compactLine(string(windowApplication["windowTitle"]), limit: 160)
      if !appName.isEmpty || !windowTitle.isEmpty {
        windowLines.append([appName, windowTitle].filter { !$0.isEmpty }.joined(separator: " · "))
      }

      let applicationSemantics = object(windowContext["applicationSemantics"])
      if string(applicationSemantics["source"]) == "zed_workspace_state" {
        let projectName = compactLine(string(applicationSemantics["projectName"]), limit: 120)
        let activeFile = compactLine(string(applicationSemantics["activeFile"]), limit: 180)
        let contentOrigin = string(applicationSemantics["contentOrigin"])
        let excerptStartLine = integer(applicationSemantics["editorExcerptStartLine"])
        let editorExcerpt = boundedParagraph(string(applicationSemantics["editorExcerpt"]), limit: 1_600)
        windowLines.append("Zed 工作区 · 只读本地语义，可能滞后")
        if !projectName.isEmpty { windowLines.append("项目：\(projectName)") }
        if !activeFile.isEmpty { windowLines.append("活动文件：\(activeFile)") }
        if !editorExcerpt.isEmpty {
          let lineLabel = excerptStartLine > 0 ? "（第 \(excerptStartLine) 行附近）" : ""
          windowLines.append("编辑区\(lineLabel)：\n\(editorExcerpt)")
        }
        if contentOrigin == "workspace_file" {
          windowLines.append("内容来源：磁盘文件；未保存修改可能尚未包含")
        } else if contentOrigin == "zed_recovery_buffer" {
          windowLines.append("内容来源：Zed 恢复缓冲")
        } else if contentOrigin == "sensitive_file_blocked" {
          windowLines.append("内容来源：敏感文件，正文未读取")
        }
      }

      let readableNodes = windowNodes.prefix(4).compactMap { value -> String? in
        let node = object(value)
        let label = compactLine(string(node["label"]), limit: 120)
        let valueText = boundedParagraph(string(node["value"]), limit: 480)
        if bool(node["secure"]) {
          return label.isEmpty ? "• 安全字段，内容未读取" : "• \(label)：安全字段，内容未读取"
        }
        if label.isEmpty { return valueText.isEmpty ? nil : "• \(valueText)" }
        if valueText.isEmpty || valueText == label { return "• \(label)" }
        return "• \(label)：\(valueText)"
      }
      if !readableNodes.isEmpty {
        windowLines.append("可读前台内容：\n" + readableNodes.joined(separator: "\n"))
      } else {
        let semanticText = boundedParagraph(string(windowContext["semanticText"]), limit: 900)
        if !semanticText.isEmpty { windowLines.append(semanticText) }
      }
      if sourceNodeCount > readableNodes.count {
        windowLines.append(
          "从 \(sourceNodeCount) 个 AX 元素中仅展示 \(readableNodes.count) 个可读文本片段；控件、动作与内部节点未发送给模型。"
        )
      }
      if windowLines.isEmpty {
        let captureMode = compactLine(string(windowContext["captureMode"]), limit: 80)
        windowLines.append(captureMode.isEmpty
          ? "当前窗口没有返回可读文本"
          : "当前窗口没有返回可读文本（\(captureMode)）")
      }
      appendSection("窗口语义", windowLines.joined(separator: "\n"))
    }

    let planning = object(contextView["planning"])
    let planningLines = array(planning["items"]).prefix(4).compactMap { value -> String? in
      let text = evidenceDisplayText(value)
      return text.isEmpty ? nil : "• \(text)"
    }
    if !planningLines.isEmpty {
      appendSection("当前规划与任务", planningLines.joined(separator: "\n"))
      historyCount += planningLines.count
    }

    let activityTimeline = object(contextView["activityTimeline"])
    let timelineFallback = object(contextView["timeline"])
    let timelineItems = firstNonEmptyArray(
      activityTimeline.isEmpty ? timelineFallback : activityTimeline,
      keys: ["recentActivities", "semanticTasks", "items", "recentDecisions"]
    )
    let timelineLines = timelineItems.prefix(4).compactMap { value -> String? in
      let text = evidenceDisplayText(value)
      return text.isEmpty ? nil : "• \(text)"
    }
    if !timelineLines.isEmpty {
      appendSection("最近批准时间线", timelineLines.joined(separator: "\n"))
      historyCount += timelineLines.count
    }

    let groundingEvidence = array(contextView["groundingEvidence"])
    var factLines: [String] = []
    var bookLines: [String] = []
    var otherEvidenceLines: [String] = []
    var seenEvidence = Set<String>()
    for value in groundingEvidence.prefix(8) {
      let item = object(value)
      let text = evidenceDisplayText(item)
      let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !normalized.isEmpty, seenEvidence.insert(normalized).inserted else { continue }
      let sourceType = firstNonEmptyString(
        item,
        keys: ["documentType", "docType", "sourceType", "sourceLane"]
      ).lowercased()
      if sourceType.contains("atom") || sourceType.contains("fact") {
        factLines.append("• \(normalized)")
      } else if sourceType.contains("book") {
        bookLines.append("• \(normalized)")
      } else {
        otherEvidenceLines.append("• \(normalized)")
      }
    }

    if groundingEvidence.isEmpty {
      for value in array(contextView["evidenceHints"]).prefix(6) {
        let item = object(value)
        let text = item.isEmpty
          ? compactLine(string(value), limit: 520)
          : evidenceDisplayText(item)
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !normalized.isEmpty, seenEvidence.insert(normalized).inserted {
          otherEvidenceLines.append("• \(normalized)")
        }
      }
    }
    if factLines.isEmpty && bookLines.isEmpty && otherEvidenceLines.isEmpty {
      for card in payload.sourceCards.prefix(6) {
        let title = compactLine(card.title, limit: 140)
        let preview = boundedParagraph(card.evidencePreview, limit: 520)
        let text = [title, preview].filter { !$0.isEmpty }.joined(separator: "：")
        if !text.isEmpty, seenEvidence.insert(text).inserted {
          otherEvidenceLines.append("• \(text)")
        }
      }
    }
    if factLines.isEmpty && bookLines.isEmpty && otherEvidenceLines.isEmpty {
      let candidates = payload.candidates
        .filter(RagImeSuggestionCardView.isRealCandidate)
        .prefix(6)
      for candidate in candidates {
        let preview = boundedParagraph(candidate.evidencePreview, limit: 520)
        if !preview.isEmpty, seenEvidence.insert(preview).inserted {
          otherEvidenceLines.append("• \(preview)")
        }
      }
    }

    if !factLines.isEmpty {
      appendSection("知识库事实 · Atom", factLines.joined(separator: "\n"))
      knowledgeCount += factLines.count
    }
    if !bookLines.isEmpty {
      appendSection("知识主题 · Book", bookLines.joined(separator: "\n"))
      knowledgeCount += bookLines.count
    }
    if !otherEvidenceLines.isEmpty {
      appendSection("RAG 依据", otherEvidenceLines.joined(separator: "\n"))
      ragCount += otherEvidenceLines.count
    } else {
      let evidenceCount = integer(transaction["evidenceCount"])
      let retrievalAttempted = bool(transaction["retrievalAttempted"])
      if evidenceCount > 0 {
        appendSection("RAG 依据", "已召回 \(evidenceCount) 条依据，但本轮没有返回可安全显示的来源片段。")
        ragCount += evidenceCount
      } else if retrievalAttempted {
        appendSection("依据状态", "本轮没有召回可显示的知识依据；结果仅使用已授权的输入与上下文。")
        evidenceStateOnly = true
      }
    }

    let recentLines = array(contextView["recentCompleteInputs"]).prefix(3).compactMap { value -> String? in
      let text = boundedParagraph(evidenceDisplayText(value), limit: 600)
      return text.isEmpty ? nil : "• \(text)"
    }
    if !recentLines.isEmpty {
      appendSection("最近完整输入 · 仅用于承接", recentLines.joined(separator: "\n"))
      historyCount += recentLines.count
    } else {
      let reportedCount = integer(transaction["timelineRecentInputRecordCount"])
      if reportedCount > 0 {
        appendSection(
          "最近完整输入 · 仅用于承接",
          "记录了 \(reportedCount) 条最近输入，但本轮模型请求没有注入可显示原文。"
        )
        historyCount += reportedCount
      }
    }

    let substantiveSectionCount = max(0, sectionCount - (evidenceStateOnly ? 1 : 0))
    let loadingStages: Set<String> = [
      "capturing_context",
      "retrieving",
      "retrieval_complete",
      "generating",
      "streaming",
      "quality_retry",
    ]
    let contextSchemaVersion = string(contextView["schemaVersion"])
    let contextSchemaUnsupported = !contextSchemaVersion.isEmpty
      && contextSchemaVersion != "rag-ime.active-rag-context-view.v1"
    let state: RagImeAssistantContextInspectorState
    if substantiveSectionCount > 0 {
      state = .content
    } else if diagnosticStatus.contains("error")
      || diagnosticStatus.contains("failed")
      || contextSchemaUnsupported {
      state = .error
    } else if loadingStages.contains(progressStage) {
      state = .loading
    } else {
      state = .empty
    }
    let isAvailable = state == .content
    let unavailableReason: String
    switch state {
    case .content:
      unavailableReason = ""
    case .loading:
      unavailableReason = "本轮授权快照仍在准备，请稍后重新打开。"
    case .error:
      unavailableReason = contextSchemaUnsupported
        ? "本轮输入与依据使用了不受支持的快照格式，请重新生成。"
        : "本轮授权快照读取失败，请重新生成后再试。"
    case .empty:
      unavailableReason = contextView.isEmpty
        ? "本轮结果没有附带可安全显示的输入或依据快照。"
        : "本轮快照没有返回可安全显示的输入或来源片段。"
    }
    if state != .content {
      let noticeStyle = NSMutableParagraphStyle()
      noticeStyle.lineSpacing = 3
      noticeStyle.paragraphSpacingBefore = sectionCount == 0 ? 0 : RagImeAssistantMetrics.spacingL
      attributed.append(NSAttributedString(
        string: unavailableReason,
        attributes: [
          .font: RagImeAssistantTypography.inspectorBody,
          .foregroundColor: state == .error ? NSColor.systemRed : NSColor.secondaryLabelColor,
          .paragraphStyle: noticeStyle,
        ]
      ))
      plainSections.append("状态\n\(unavailableReason)")
    }
    var summaryParts: [String] = []
    if inputCount > 0 { summaryParts.append("\(inputCount) 段输入") }
    if historyCount > 0 { summaryParts.append("\(historyCount) 条连续历史") }
    if knowledgeCount > 0 { summaryParts.append("\(knowledgeCount) 条知识来源") }
    if ragCount > 0 { summaryParts.append("\(ragCount) 条 RAG 依据") }
    return RagImeAssistantContextInspectorDocument(
      snapshotId: payload.snapshotId,
      attributedText: attributed,
      plainText: plainSections.joined(separator: "\n\n"),
      source: source.isEmpty ? "unknown" : source,
      summary: summaryParts.isEmpty ? state.accessibilityLabel : summaryParts.joined(separator: " · "),
      sectionCount: sectionCount,
      state: state,
      isAvailable: isAvailable,
      unavailableReason: unavailableReason
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

  private static func firstNonEmptyArray(
    _ object: [String: RagImeJSONValue],
    keys: [String]
  ) -> [RagImeJSONValue] {
    for key in keys {
      let values = array(object[key])
      if !values.isEmpty { return values }
    }
    return []
  }

  private static func boundedParagraph(_ text: String, limit: Int) -> String {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard trimmed.count > limit else { return trimmed }
    return String(trimmed.prefix(limit)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
  }

  private static func compactLine(_ text: String, limit: Int) -> String {
    boundedParagraph(
      text.split(whereSeparator: \.isWhitespace).joined(separator: " "),
      limit: limit
    )
  }

  private static func evidenceDisplayText(_ value: RagImeJSONValue) -> String {
    switch value {
    case .string(let text):
      return boundedParagraph(text, limit: 560)
    case .object(let item):
      return evidenceDisplayText(item)
    case .array(let values):
      var seen = Set<String>()
      return values.prefix(4).compactMap { value -> String? in
        let text = evidenceDisplayText(value).trimmingCharacters(in: .whitespacesAndNewlines)
        return !text.isEmpty && seen.insert(text).inserted ? text : nil
      }.joined(separator: " · ")
    case .number, .bool, .null:
      return ""
    }
  }

  private static func evidenceDisplayText(_ item: [String: RagImeJSONValue]) -> String {
    let title = compactLine(firstNonEmptyString(item, keys: ["title", "label"]), limit: 140)
    let detail = boundedParagraph(
      firstNonEmptyString(item, keys: ["evidencePreview", "preview", "textPreview", "text", "summary", "detail"]),
      limit: 560
    )
    let sourceLane = compactLine(firstNonEmptyString(item, keys: ["sourceLane", "sourceType"]), limit: 80)
    let sourceReference = boundedParagraph(
      firstNonEmptyString(item, keys: ["ref", "citation", "source", "id"]),
      limit: 800
    )
    let reference = [sourceLane, sourceReference]
      .filter { !$0.isEmpty }
      .joined(separator: " · ")
    let body: String
    if title.isEmpty {
      body = detail
    } else if detail.isEmpty || detail == title || detail.contains(title) {
      body = detail.isEmpty ? title : detail
    } else if title.contains(detail) {
      body = title
    } else {
      body = "\(title)：\(detail)"
    }
    guard !body.isEmpty else { return "" }
    return reference.isEmpty ? body : "\(body)\n  来源：\(reference)"
  }
}
private final class RagImeAssistantContextInspectorRootView: NSVisualEffectView {
  override init(frame frameRect: NSRect) {
    super.init(frame: frameRect)
    wantsLayer = true
    updateDynamicChrome()
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidChangeEffectiveAppearance() {
    super.viewDidChangeEffectiveAppearance()
    updateDynamicChrome()
  }

  private func updateDynamicChrome() {
    layer?.borderWidth = NSWorkspace.shared.accessibilityDisplayShouldIncreaseContrast ? 1 : 0.5
    layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.72).cgColor
  }
}


private final class RagImeAssistantContextInspectorViewController: NSViewController {
  static let preferredSize = NSSize(width: 520, height: 480)
  private let document: RagImeAssistantContextInspectorDocument
  private let onClose: () -> Void
  private let onRetry: (() -> Void)?
  private let titleLabel = NSTextField(labelWithString: "")
  private let stateIcon = NSImageView()
  private let subtitleLabel = NSTextField(labelWithString: "")
  private let copyButton = NSButton(title: "复制全部", target: nil, action: nil)
  private let retryButton = NSButton(title: "重新生成", target: nil, action: nil)
  private let closeButton = NSButton()
  private let divider = NSBox(frame: .zero)
  private let scrollView = NSScrollView()
  private let textView = NSTextView(frame: .zero)
  init(
    document: RagImeAssistantContextInspectorDocument,
    onClose: @escaping () -> Void,
    onRetry: (() -> Void)? = nil
  ) {
    self.document = document
    self.onClose = onClose
    self.onRetry = onRetry
    super.init(nibName: nil, bundle: nil)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func loadView() {
    let root = RagImeAssistantContextInspectorRootView(
      frame: NSRect(origin: .zero, size: Self.preferredSize)
    )
    root.material = .contentBackground
    root.blendingMode = .withinWindow
    root.state = .inactive
    root.layer?.cornerRadius = RagImeAssistantMetrics.inspectorCornerRadius
    root.layer?.masksToBounds = true
    root.setAccessibilityLabel(document.state.title)
    view = root

    titleLabel.stringValue = document.state.title
    titleLabel.font = RagImeAssistantTypography.inspectorTitle
    titleLabel.textColor = .labelColor
    subtitleLabel.font = RagImeAssistantTypography.inspectorSubtitle
    subtitleLabel.textColor = .secondaryLabelColor
    let sourceLabel = document.source == "provider_request"
      ? "实际模型请求"
      : (document.source == "frontend_request" ? "前台授权快照" : "授权来源未标明")
    subtitleLabel.stringValue = "\(sourceLabel) · \(document.summary)"
    subtitleLabel.lineBreakMode = .byTruncatingTail
    stateIcon.imageScaling = .scaleProportionallyDown
    stateIcon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 14, weight: .semibold)
    switch document.state {
    case .content:
      stateIcon.image = NSImage(systemSymbolName: "checkmark.circle.fill", accessibilityDescription: nil)
      stateIcon.contentTintColor = .systemGreen
    case .loading:
      stateIcon.image = NSImage(systemSymbolName: "clock", accessibilityDescription: nil)
      stateIcon.contentTintColor = .controlAccentColor
    case .empty:
      stateIcon.image = NSImage(systemSymbolName: "tray", accessibilityDescription: nil)
      stateIcon.contentTintColor = .secondaryLabelColor
    case .error:
      stateIcon.image = NSImage(systemSymbolName: "exclamationmark.triangle.fill", accessibilityDescription: nil)
      stateIcon.contentTintColor = .systemRed
    }
    stateIcon.setAccessibilityLabel(document.state.accessibilityLabel)

    copyButton.isBordered = false
    copyButton.bezelStyle = .inline
    copyButton.focusRingType = .exterior
    copyButton.font = RagImeAssistantTypography.action
    copyButton.image = NSImage(systemSymbolName: "doc.on.doc", accessibilityDescription: "复制可读输入与依据")
    copyButton.imagePosition = .imageLeading
    copyButton.toolTip = document.isAvailable
      ? "复制当前显示的可读输入与依据"
      : document.unavailableReason
    copyButton.setAccessibilityLabel("复制全部可读输入与依据")
    copyButton.isEnabled = document.isAvailable
    copyButton.target = self
    copyButton.action = #selector(copyAllContext)

    retryButton.isBordered = false
    retryButton.bezelStyle = .inline
    retryButton.focusRingType = .exterior
    retryButton.font = RagImeAssistantTypography.action
    retryButton.image = NSImage(
      systemSymbolName: "arrow.clockwise",
      accessibilityDescription: "重新生成输入与依据"
    )
    retryButton.imagePosition = .imageLeading
    retryButton.toolTip = "重新生成本轮结果后再次查看输入与依据"
    retryButton.setAccessibilityLabel("重新生成本轮输入与依据")
    retryButton.isHidden = document.state != .error
    retryButton.isEnabled = document.state == .error && onRetry != nil
    retryButton.target = self
    retryButton.action = #selector(retryInspector)

    closeButton.isBordered = false
    closeButton.bezelStyle = .inline
    closeButton.focusRingType = .exterior
    closeButton.image = NSImage(systemSymbolName: "xmark", accessibilityDescription: "关闭输入与依据")
    closeButton.toolTip = "关闭输入与依据"
    closeButton.setAccessibilityLabel("关闭输入与依据")
    closeButton.target = self
    closeButton.action = #selector(closeInspector)

    divider.boxType = .separator
    scrollView.drawsBackground = false
    scrollView.borderType = .noBorder
    scrollView.hasVerticalScroller = true
    scrollView.hasHorizontalScroller = false
    scrollView.autohidesScrollers = true
    scrollView.scrollerStyle = .overlay
    textView.isEditable = false
    textView.isSelectable = true
    textView.drawsBackground = false
    textView.textContainerInset = NSSize(width: 8, height: 10)
    textView.isHorizontallyResizable = false
    textView.isVerticallyResizable = true
    textView.autoresizingMask = [.width]
    textView.textContainer?.lineBreakMode = .byCharWrapping
    textView.textContainer?.widthTracksTextView = true
    textView.textContainer?.containerSize = NSSize(width: 0, height: CGFloat.greatestFiniteMagnitude)
    textView.textStorage?.setAttributedString(document.attributedText)
    textView.setAccessibilityLabel("本轮授权输入与依据正文")
    scrollView.setAccessibilityLabel("本轮授权输入与依据")
    scrollView.documentView = textView

    [titleLabel, stateIcon, subtitleLabel, copyButton, retryButton, closeButton, divider, scrollView].forEach {
      root.addSubview($0)
    }
  }


  override func viewDidLayout() {
    super.viewDidLayout()
    let inset = RagImeAssistantMetrics.spacingL
    let bounds = view.bounds
    let gap = RagImeAssistantMetrics.spacingS
    let hitTarget = RagImeAssistantMetrics.minimumHitTarget
    let closeX = bounds.width - inset - hitTarget
    let copyWidth: CGFloat = 92
    let copyX = closeX - gap - copyWidth
    let retryWidth: CGFloat = 96
    let retryX = copyX - gap - retryWidth
    let actionStartX = retryButton.isHidden ? copyX : retryX
    titleLabel.frame = NSRect(
      x: inset,
      y: bounds.height - 38,
      width: max(120, closeX - gap - inset),
      height: 20
    )
    stateIcon.frame = NSRect(x: inset, y: bounds.height - 62, width: 16, height: 16)
    subtitleLabel.frame = NSRect(
      x: inset + 24,
      y: bounds.height - 64,
      width: max(96, actionStartX - gap - inset - 24),
      height: 18
    )
    retryButton.frame = NSRect(x: retryX, y: bounds.height - 60, width: retryWidth, height: hitTarget)
    copyButton.frame = NSRect(x: copyX, y: bounds.height - 60, width: copyWidth, height: hitTarget)
    closeButton.frame = NSRect(x: closeX, y: bounds.height - 60, width: hitTarget, height: hitTarget)
    divider.frame = NSRect(x: inset, y: bounds.height - 76, width: bounds.width - inset * 2, height: 1)
    scrollView.frame = NSRect(
      x: RagImeAssistantMetrics.spacingS,
      y: RagImeAssistantMetrics.spacingS,
      width: bounds.width - RagImeAssistantMetrics.spacingL,
      height: bounds.height - 92
    )
    let contentWidth = max(0, scrollView.contentSize.width)
    if let textContainer = textView.textContainer, let layoutManager = textView.layoutManager {
      textContainer.containerSize = NSSize(width: max(0, contentWidth - 16), height: CGFloat.greatestFiniteMagnitude)
      layoutManager.ensureLayout(for: textContainer)
      let contentHeight = ceil(layoutManager.usedRect(for: textContainer).height) + 20
      textView.frame = NSRect(
        x: 0,
        y: 0,
        width: contentWidth,
        height: max(scrollView.contentSize.height, contentHeight)
      )
    }
  }

  @objc private func copyAllContext() {
    guard document.isAvailable else { return }
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(document.plainText, forType: .string)
  }

  @objc private func retryInspector() {
    guard document.state == .error, let onRetry else { return }
    onRetry()
  }

  @objc private func closeInspector() {
    onClose()
  }
}
