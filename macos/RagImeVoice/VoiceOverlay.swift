import AppKit
import QuartzCore
import SwiftUI

private enum VoiceOverlayMetrics {
    static let compactWidth: CGFloat = 74
    static let expandedWidth: CGFloat = 408
    static let height: CGFloat = 72
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

struct VoiceOverlayView: View {
    @ObservedObject var model: VoiceOverlayModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: model.isCompact ? 0 : 11) {
            RagImeAnimeCompanion(
                state: companionState,
                level: model.level,
                size: model.isCompact ? 62 : 50
            )
            if !model.isCompact {
                VStack(alignment: .leading, spacing: 5) {
                    Text(model.message)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Text(model.transcript.isEmpty ? fallbackText : model.transcript)
                        .font(.system(size: 14.5, weight: .regular))
                        .lineLimit(2)
                        .truncationMode(.tail)
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
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: VoiceOverlayMetrics.cornerRadius))
        .overlay(
            RoundedRectangle(cornerRadius: VoiceOverlayMetrics.cornerRadius)
                .stroke(.primary.opacity(0.13), lineWidth: 0.7)
        )
        .overlay(alignment: .leading) {
            if !model.isCompact {
                Capsule()
                    .fill(companionState.accent)
                    .frame(width: 3, height: 52)
                    .padding(.leading, 1)
            }
        }
        .animation(reduceMotion ? nil : .spring(response: 0.24, dampingFraction: 0.86), value: model.isCompact)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(model.message)，\(model.transcript)")
    }

    private var companionState: RagImeCompanionState {
        switch model.phase {
        case .listening: return .listening
        case .finalizing: return .thinking
        case .done: return .done
        case .error: return .warning
        }
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
    private var currentWidth = VoiceOverlayMetrics.compactWidth

    func showListening(anchor: NSPoint?) {
        dismissWorkItem?.cancel()
        model.phase = .listening
        model.message = "听着呢"
        model.transcript = ""
        anchorPoint = anchor
        show(anchor: anchor, width: VoiceOverlayMetrics.compactWidth)
    }

    func updateTranscript(_ text: String) {
        model.transcript = String(text.suffix(240))
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
        model.transcript = String(text.suffix(240))
        resize(width: VoiceOverlayMetrics.expandedWidth)
        scheduleDismiss(after: 2.2)
    }

    func showError(_ message: String, anchor: NSPoint? = nil) {
        model.phase = .error
        let permissionNeeded = message.contains("辅助功能") || message.contains("麦克风权限")
        model.message = permissionNeeded ? "还差一步" : "语音输入未完成"
        model.transcript = permissionNeeded ? permissionMessage(message) : message
        anchorPoint = anchor ?? anchorPoint
        show(anchor: anchorPoint, width: VoiceOverlayMetrics.expandedWidth)
        scheduleDismiss(after: permissionNeeded ? 4.5 : 3.2)
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
        currentWidth = width
        position(panel: panel, anchor: anchorPoint ?? NSEvent.mouseLocation, width: width, animated: false)
        panel.orderFrontRegardless()
    }

    private func resize(width: CGFloat) {
        guard let panel else {
            show(anchor: anchorPoint, width: width)
            return
        }
        let shouldAnimate = abs(currentWidth - width) > 1
        currentWidth = width
        position(
            panel: panel,
            anchor: anchorPoint ?? NSEvent.mouseLocation,
            width: width,
            animated: shouldAnimate
        )
    }

    private func position(panel: NSPanel, anchor: NSPoint, width: CGFloat, animated: Bool) {
        let screen = NSScreen.screens.first(where: { NSMouseInRect(anchor, $0.frame, false) }) ?? NSScreen.main
        let target = NSSize(width: width, height: VoiceOverlayMetrics.height)
        let frame = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = min(max(anchor.x - width / 2, frame.minX + 12), frame.maxX - width - 12)
        let y = min(max(anchor.y + 18, frame.minY + 12), frame.maxY - target.height - 12)
        let targetFrame = NSRect(origin: NSPoint(x: x, y: y), size: target)
        let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        guard animated, !reduceMotion, panel.isVisible else {
            panel.setFrame(targetFrame, display: true, animate: false)
            return
        }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().setFrame(targetFrame, display: true)
        }
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

    private func permissionMessage(_ message: String) -> String {
        if message.contains("辅助功能") { return "若开关已开启，请关闭后重新开启 RagImeVoice" }
        if message.contains("麦克风") { return "请在系统设置中允许使用麦克风" }
        return message
    }
}
