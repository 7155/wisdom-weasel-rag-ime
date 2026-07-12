import AppKit
import SwiftUI

private enum VoiceOverlayMetrics {
    static let compactWidth: CGFloat = 60
    static let expandedWidth: CGFloat = 392
    static let height: CGFloat = 64
    static let cornerRadius: CGFloat = 8
}

@MainActor
final class VoiceOverlayModel: ObservableObject {
    enum Phase: Equatable {
        case listening
        case finalizing
        case done
        case error
    }

    @Published var phase: Phase = .listening
    @Published var transcript = ""
    @Published var message = "听着呢"
    @Published var level = 0.12

    var isCompact: Bool { transcript.isEmpty && phase == .listening }
}

private struct VoiceCompanionGlyph: View {
    let phase: VoiceOverlayModel.Phase
    let level: Double
    let reduceMotion: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(accent.opacity(0.12))
                .frame(width: 48, height: 48)
                .scaleEffect(phase == .listening && !reduceMotion ? 0.96 + min(level, 1) * 0.08 : 1)
                .animation(reduceMotion ? nil : .easeOut(duration: 0.14), value: level)

            RoundedRectangle(cornerRadius: 7)
                .fill(accent.gradient)
                .frame(width: 34, height: 30)
                .rotationEffect(.degrees(phase == .listening && !reduceMotion ? (level - 0.35) * 4 : 0))
                .animation(reduceMotion ? nil : .spring(response: 0.2, dampingFraction: 0.72), value: level)

            HStack(spacing: 2) {
                RoundedRectangle(cornerRadius: 3).fill(.white.opacity(0.92)).frame(width: 13, height: 20)
                RoundedRectangle(cornerRadius: 3).fill(.white.opacity(0.92)).frame(width: 13, height: 20)
            }
            .offset(y: -1)

            HStack(spacing: 7) {
                Circle().fill(Color.black.opacity(0.62)).frame(width: 2.8, height: 2.8)
                Circle().fill(Color.black.opacity(0.62)).frame(width: 2.8, height: 2.8)
            }
            .offset(y: -3)

            Capsule()
                .fill(Color.black.opacity(0.5))
                .frame(width: phase == .error ? 6 : 8, height: 2)
                .offset(y: 4)

            RoundedRectangle(cornerRadius: 1.5)
                .fill(Color(red: 0.98, green: 0.46, blue: 0.34))
                .frame(width: 4, height: 13)
                .offset(x: 13, y: 8)

            phaseMark
                .offset(x: 18, y: -18)
        }
        .frame(width: 54, height: 54)
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var phaseMark: some View {
        switch phase {
        case .listening:
            HStack(spacing: 1.5) {
                ForEach(0..<3, id: \.self) { index in
                    Capsule()
                        .fill(accent)
                        .frame(width: 2.5, height: 5 + min(level, 1) * Double(4 + index * 3))
                }
            }
        case .finalizing:
            ProgressView().controlSize(.mini).tint(accent)
        case .done:
            Image(systemName: "checkmark.circle.fill").foregroundStyle(accent)
        case .error:
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(accent)
        }
    }

    private var accent: Color {
        switch phase {
        case .listening: return Color(red: 0.05, green: 0.67, blue: 0.62)
        case .finalizing: return Color(red: 0.31, green: 0.42, blue: 0.86)
        case .done: return Color(red: 0.18, green: 0.67, blue: 0.36)
        case .error: return Color(red: 0.93, green: 0.49, blue: 0.20)
        }
    }
}

struct VoiceOverlayView: View {
    @ObservedObject var model: VoiceOverlayModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: model.isCompact ? 0 : 9) {
            VoiceCompanionGlyph(phase: model.phase, level: model.level, reduceMotion: reduceMotion)
            if !model.isCompact {
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.message)
                        .font(.system(size: 11.5, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Text(model.transcript.isEmpty ? fallbackText : model.transcript)
                        .font(.system(size: 14, weight: .regular))
                        .lineLimit(2)
                        .truncationMode(.head)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                Spacer(minLength: 4)
            }
        }
        .padding(.horizontal, model.isCompact ? 3 : 10)
        .frame(
            width: model.isCompact ? VoiceOverlayMetrics.compactWidth : VoiceOverlayMetrics.expandedWidth,
            height: VoiceOverlayMetrics.height
        )
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: VoiceOverlayMetrics.cornerRadius))
        .overlay(
            RoundedRectangle(cornerRadius: VoiceOverlayMetrics.cornerRadius)
                .stroke(.primary.opacity(0.13), lineWidth: 0.7)
        )
        .overlay(alignment: .leading) {
            if !model.isCompact {
                Capsule()
                    .fill(Color(red: 0.05, green: 0.67, blue: 0.62))
                    .frame(width: 3, height: 46)
                    .padding(.leading, 1)
            }
        }
        .animation(reduceMotion ? nil : .spring(response: 0.24, dampingFraction: 0.86), value: model.isCompact)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(model.message)，\(model.transcript)")
    }

    private var fallbackText: String {
        switch model.phase {
        case .listening: return ""
        case .finalizing: return "正在用最终结果替换临时稿"
        case .done: return "已写入当前光标"
        case .error: return "本次听写没有完成"
        }
    }
}

@MainActor
final class VoiceOverlayController {
    private let model = VoiceOverlayModel()
    private var panel: NSPanel?
    private var dismissWorkItem: DispatchWorkItem?
    private var anchorPoint: NSPoint?

    func showListening(anchor: NSPoint?) {
        dismissWorkItem?.cancel()
        model.phase = .listening
        model.message = "听着呢"
        model.transcript = ""
        anchorPoint = anchor
        show(anchor: anchor, width: VoiceOverlayMetrics.compactWidth)
    }

    func updateTranscript(_ text: String) {
        model.transcript = String(text.suffix(120))
        if !model.transcript.isEmpty { resize(width: VoiceOverlayMetrics.expandedWidth) }
    }

    func updateLevel(_ level: Double) { model.level = level }

    func showFinalizing() {
        model.phase = .finalizing
        model.message = "我在校正"
        resize(width: VoiceOverlayMetrics.expandedWidth)
    }

    func showDone(_ text: String) {
        model.phase = .done
        model.message = "已经整理好"
        model.transcript = String(text.suffix(120))
        resize(width: VoiceOverlayMetrics.expandedWidth)
        scheduleDismiss(after: 1.4)
    }

    func showError(_ message: String, anchor: NSPoint? = nil) {
        model.phase = .error
        model.message = "语音输入未完成"
        model.transcript = message
        anchorPoint = anchor ?? anchorPoint
        show(anchor: anchorPoint, width: VoiceOverlayMetrics.expandedWidth)
        scheduleDismiss(after: 3.2)
    }

    func dismiss() {
        dismissWorkItem?.cancel()
        dismissWorkItem = nil
        panel?.orderOut(nil)
    }

    private func show(anchor: NSPoint?, width: CGFloat) {
        let panel = panel ?? makePanel()
        self.panel = panel
        anchorPoint = anchor ?? anchorPoint
        position(panel: panel, anchor: anchorPoint ?? NSEvent.mouseLocation, width: width)
        panel.orderFrontRegardless()
    }

    private func resize(width: CGFloat) {
        guard let panel else {
            show(anchor: anchorPoint, width: width)
            return
        }
        position(panel: panel, anchor: anchorPoint ?? NSEvent.mouseLocation, width: width)
    }

    private func position(panel: NSPanel, anchor: NSPoint, width: CGFloat) {
        let screen = NSScreen.screens.first(where: { NSMouseInRect(anchor, $0.frame, false) }) ?? NSScreen.main
        let target = NSSize(width: width, height: VoiceOverlayMetrics.height)
        let frame = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = min(max(anchor.x - width / 2, frame.minX + 12), frame.maxX - width - 12)
        let y = min(max(anchor.y + 18, frame.minY + 12), frame.maxY - target.height - 12)
        panel.setFrame(NSRect(origin: NSPoint(x: x, y: y), size: target), display: true, animate: false)
    }

    private func makePanel() -> NSPanel {
        let panel = NSPanel(
            contentRect: NSRect(
                x: 0,
                y: 0,
                width: VoiceOverlayMetrics.compactWidth,
                height: VoiceOverlayMetrics.height
            ),
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
