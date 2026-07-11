import AppKit
import SwiftUI

@MainActor
final class VoiceOverlayModel: ObservableObject {
    enum Phase {
        case listening
        case finalizing
        case done
        case error
    }

    @Published var phase: Phase = .listening
    @Published var transcript = ""
    @Published var message = "正在聆听"
    @Published var level = 0.12
}

struct VoiceOverlayView: View {
    @ObservedObject var model: VoiceOverlayModel

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 7)
                    .fill(iconColor.opacity(0.14))
                    .frame(width: 36, height: 36)
                if model.phase == .listening {
                    HStack(spacing: 2) {
                        ForEach(0..<3, id: \.self) { index in
                            Capsule()
                                .fill(iconColor)
                                .frame(width: 3, height: 7 + model.level * Double(7 + index * 4))
                                .animation(.easeInOut(duration: 0.12), value: model.level)
                        }
                    }
                } else {
                    Image(systemName: phaseSymbol).foregroundStyle(iconColor)
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(model.message)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(model.transcript.isEmpty ? "说话时文字会直接出现在光标处" : model.transcript)
                    .font(.system(size: 14, weight: .medium))
                    .lineLimit(1)
                    .truncationMode(.head)
            }
            Spacer(minLength: 8)
            Text(model.phase == .listening ? "松开定稿" : "")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 12)
        .frame(width: 430, height: 58)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(.primary.opacity(0.12)))
    }

    private var iconColor: Color {
        switch model.phase {
        case .listening: return .red
        case .finalizing: return .blue
        case .done: return .green
        case .error: return .orange
        }
    }

    private var phaseSymbol: String {
        switch model.phase {
        case .listening: return "waveform"
        case .finalizing: return "ellipsis"
        case .done: return "checkmark"
        case .error: return "exclamationmark"
        }
    }
}

@MainActor
final class VoiceOverlayController {
    private let model = VoiceOverlayModel()
    private var panel: NSPanel?
    private var dismissWorkItem: DispatchWorkItem?

    func showListening(anchor: NSPoint?) {
        dismissWorkItem?.cancel()
        model.phase = .listening
        model.message = "正在聆听"
        model.transcript = ""
        show(anchor: anchor)
    }

    func updateTranscript(_ text: String) {
        model.transcript = String(text.suffix(80))
    }

    func updateLevel(_ level: Double) { model.level = level }

    func showFinalizing() {
        model.phase = .finalizing
        model.message = "豆包正在定稿"
    }

    func showDone(_ text: String) {
        model.phase = .done
        model.message = "已写入"
        model.transcript = String(text.suffix(80))
        scheduleDismiss(after: 0.8)
    }

    func showError(_ message: String, anchor: NSPoint? = nil) {
        model.phase = .error
        model.message = "语音输入未完成"
        model.transcript = message
        show(anchor: anchor)
        scheduleDismiss(after: 2.8)
    }

    func dismiss() {
        dismissWorkItem?.cancel()
        dismissWorkItem = nil
        panel?.orderOut(nil)
    }

    private func show(anchor: NSPoint?) {
        let panel = panel ?? makePanel()
        self.panel = panel
        let point = anchor ?? NSEvent.mouseLocation
        let screen = NSScreen.screens.first(where: { NSMouseInRect(point, $0.frame, false) }) ?? NSScreen.main
        if let frame = screen?.visibleFrame {
            let x = min(max(point.x - 215, frame.minX + 12), frame.maxX - 442)
            let y = min(max(point.y + 18, frame.minY + 12), frame.maxY - 70)
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }
        panel.orderFrontRegardless()
    }

    private func makePanel() -> NSPanel {
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 430, height: 58),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.level = .statusBar
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        panel.ignoresMouseEvents = true
        panel.contentView = NSHostingView(rootView: VoiceOverlayView(model: model))
        return panel
    }

    private func scheduleDismiss(after delay: TimeInterval) {
        dismissWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.dismiss() }
        dismissWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }
}
