import AppKit

final class RagImeAssistantPanelController {
  typealias TraceHandler = (_ event: String, _ fields: [String: Any]) -> Void
  private let panel: RagImeNonActivatingPanel
  private let cardView: RagImeSuggestionCardView
  private var currentPayload: RagImeAssistantOverlayPayload?
  private var currentState: RagImeAssistantSurfaceState = .hidden
  private var renderedSnapshotId = ""
  private var renderedStableIds: [String] = []
  private var expandedSnapshotId = ""
  private var pendingUpdate: DispatchWorkItem?
  private var lastReliableCaretAnchor: NSPoint?
  private var lastPositionedAnchor: NSPoint?
  private var visibleSince: Date?
  private var didTraceCreation = false
  private var onSelect: ((RagImeDisplayCandidate, Int) -> Void)?
  private var onAction: ((RagImeAssistantAction) -> Void)?
  private var onTrace: TraceHandler?

  init() {
    panel = RagImeNonActivatingPanel(
      contentRect: NSRect(x: 0, y: 0, width: 360, height: 40),
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
    cardView.onSelect = { [weak self] candidate, index in self?.onSelect?(candidate, index) }
    cardView.onAction = { [weak self] action in self?.handle(action) }
  }

  var isVisible: Bool { panel.isVisible }

  func update(
    _ payload: RagImeAssistantOverlayPayload?,
    anchor: NSPoint?,
    onSelect: ((RagImeDisplayCandidate, Int) -> Void)?,
    onAction: ((RagImeAssistantAction) -> Void)? = nil,
    onTrace: TraceHandler? = nil
  ) {
    self.onSelect = onSelect
    self.onAction = onAction
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
    currentState = .transientConfirmation
    cardView.apply(state: .transientConfirmation, payload: payload)
    panel.ignoresMouseEvents = true
    panel.setContentSize(NSSize(width: 280, height: 40))
    trace("assistant_surface_state_changed", [
      "surfaceState": RagImeAssistantSurfaceState.transientConfirmation.rawValue,
      "snapshotId": payload.snapshotId,
      "reason": "candidate_accepted",
    ])
    DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(700)) { [weak self] in
      guard self?.currentState == .transientConfirmation else { return }
      self?.dismiss(reason: "confirmation_finished")
    }
  }

  func dismiss(reason: String) {
    pendingUpdate?.cancel()
    pendingUpdate = nil
    let duration = visibleSince.map { Int(Date().timeIntervalSince($0) * 1000) } ?? 0
    currentPayload = nil
    currentState = .hidden
    renderedSnapshotId = ""
    renderedStableIds = []
    expandedSnapshotId = ""
    visibleSince = nil
    if panel.isVisible { panel.orderOut(nil) }
    trace("assistant_panel_dismissed", ["reason": reason, "visibleDurationMs": duration])
    trace("assistant_surface_state_changed", ["surfaceState": RagImeAssistantSurfaceState.hidden.rawValue, "reason": reason])
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
    let stableIds = payload.candidates.filter(RagImeSuggestionCardView.isRealCandidate).map {
      $0.candidateStableId ?? "\($0.sourceType):\($0.insertText)"
    }
    if payload.snapshotId == renderedSnapshotId && stableIds == renderedStableIds && state == currentState && !forceContent {
      trace("assistant_panel_reused", ["snapshotId": payload.snapshotId, "reason": "same_snapshot_stable_ids"])
      return false
    }
    let wasVisible = panel.isVisible
    currentPayload = payload
    currentState = state
    renderedSnapshotId = payload.snapshotId
    renderedStableIds = stableIds
    cardView.apply(state: state, payload: payload)
    panel.ignoresMouseEvents = state == .compactPrediction
    panel.setContentSize(contentSize(for: state, payload: payload))
    position(state: state, anchor: anchor)
    if !wasVisible {
      visibleSince = Date()
      panel.alphaValue = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? 1 : 0
      panel.orderFront(nil)
      if !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
        NSAnimationContext.runAnimationGroup { context in
          context.duration = 0.1
          panel.animator().alphaValue = 1
        }
      }
      trace("assistant_panel_first_visible", ["surfaceState": state.rawValue, "snapshotId": payload.snapshotId])
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
    if explicit { return realCandidates.isEmpty ? .explicitGenerating : .explicitResult }
    guard !realCandidates.isEmpty else { return .hidden }
    if expandedSnapshotId == payload.snapshotId && realCandidates.count > 1 { return .expandedPredictions }
    return .compactPrediction
  }

  private func contentSize(for state: RagImeAssistantSurfaceState, payload: RagImeAssistantOverlayPayload) -> NSSize {
    let realCandidates = payload.candidates.filter(RagImeSuggestionCardView.isRealCandidate)
    let longest = realCandidates.map { $0.text.isEmpty ? $0.insertText : $0.text }.max(by: { $0.count < $1.count }) ?? ""
    let measuredWidth = (longest as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 13.5)]).width + 108
    let width = min(520, max(280, min(420, measuredWidth)))
    switch state {
    case .compactPrediction: return NSSize(width: width, height: RagImeSuggestionCardView.compactHeight)
    case .expandedPredictions: return NSSize(width: width, height: RagImeSuggestionCardView.rowHeight * CGFloat(min(3, realCandidates.count)))
    case .explicitGenerating: return NSSize(width: max(360, width), height: RagImeSuggestionCardView.thinkingHeight)
    case .explicitResult:
      let text = realCandidates.first.map { $0.text.isEmpty ? $0.insertText : $0.text } ?? ""
      let rect = (text as NSString).boundingRect(
        with: NSSize(width: max(336, width - 24), height: 1000),
        options: [.usesLineFragmentOrigin, .usesFontLeading],
        attributes: [.font: NSFont.systemFont(ofSize: 13.5)]
      )
      return NSSize(width: max(360, width), height: min(220, max(96, ceil(rect.height) + 74)))
    case .transientConfirmation, .hidden: return NSSize(width: 280, height: 40)
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
    if let lastPositionedAnchor,
      abs(lastPositionedAnchor.x - point.x) <= 8,
      abs(lastPositionedAnchor.y - point.y) <= 8,
      panel.isVisible { return }
    lastPositionedAnchor = point
    guard let screen = (NSScreen.screens.first { $0.visibleFrame.contains(point) } ?? NSScreen.main)?.visibleFrame else { return }
    let size = panel.frame.size
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
    case .insert, .replace:
      guard let payload = currentPayload,
        let index = payload.candidates.firstIndex(where: RagImeSuggestionCardView.isRealCandidate) else { return }
      onSelect?(payload.candidates[index], index)
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
    for title in ["记住", "不再推荐"] {
      let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
      item.isEnabled = false
      menu.addItem(item)
    }
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

  private func traceCreationIfNeeded() {
    guard !didTraceCreation else { return }
    didTraceCreation = true
    trace("assistant_panel_created", ["createCount": 1])
  }

  private func trace(_ event: String, _ fields: [String: Any]) { onTrace?(event, fields) }
}
