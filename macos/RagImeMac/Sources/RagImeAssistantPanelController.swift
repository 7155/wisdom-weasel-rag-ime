import AppKit
import SwiftUI

final class RagImeAssistantPanelController {
    static let shared = RagImeAssistantPanelController()

    private let panel: NSPanel

    private init() {
        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 360, height: 140),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isReleasedWhenClosed = false
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hasShadow = false
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
    }

    var isVisible: Bool {
        panel.isVisible
    }

    func update(
        payload: RagImeAssistantOverlayPayload?,
        anchor: NSPoint?,
        onSelect: @escaping (RimeDisplayCandidate, Int) -> Void
    ) {
        guard let payload, payload.visible else {
            dismiss(reason: payload?.dismissReason ?? "hidden")
            return
        }
        let view = RagImeAssistantOverlayView(payload: payload, onSelect: onSelect)
        let hosting = NSHostingView(rootView: view)
        hosting.frame = NSRect(origin: .zero, size: hosting.fittingSize)
        panel.contentView = hosting
        panel.setContentSize(hosting.fittingSize)
        positionPanel(anchor: anchor)
        panel.orderFrontRegardless()
    }

    func dismiss(reason _: String) {
        panel.orderOut(nil)
    }

    private func positionPanel(anchor: NSPoint?) {
        let point = anchor ?? fallbackAnchor()
        let size = panel.frame.size
        panel.setFrameOrigin(NSPoint(x: point.x, y: point.y - size.height - 10))
    }

    private func fallbackAnchor() -> NSPoint {
        if let mouse = NSScreen.main?.frame {
            return NSPoint(x: mouse.midX - 180, y: mouse.midY + 120)
        }
        return NSPoint(x: 240, y: 560)
    }
}
