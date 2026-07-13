import AppKit
import QuartzCore
import SwiftUI

private enum VoiceOverlayMetrics {
    static let width: CGFloat = 396
    static let height: CGFloat = 92
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
    @Published var message = "准备听写"
    @Published var level = 0.12
    @Published var levelHistory = Array(repeating: 0.04, count: 28)
}

struct VoiceOverlayView: View {
    @ObservedObject var model: VoiceOverlayModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: 12) {
            RagImeAnimeCompanion(
                state: companionState,
                level: model.level,
                size: 54
            )
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 7) {
                    Circle()
                        .fill(companionState.accent)
                        .frame(width: 7, height: 7)
                        .opacity(model.phase == .listening ? 1 : 0.72)
                    Text(model.message)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(phaseLabel)
                        .font(.system(size: 10.5, weight: .medium))
                        .foregroundStyle(companionState.accent)
                }
                Text(model.transcript.isEmpty ? fallbackText : model.transcript)
                    .font(.system(size: 14.5, weight: .medium))
                    .lineLimit(2)
                    .truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
                VoiceLevelWaveform(samples: model.levelHistory, color: companionState.accent)
                    .frame(height: 18)
            }
        }
        .padding(.horizontal, 12)
        .frame(width: VoiceOverlayMetrics.width, height: VoiceOverlayMetrics.height)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.98))
        .clipShape(RoundedRectangle(cornerRadius: VoiceOverlayMetrics.cornerRadius))
        .overlay(
            RoundedRectangle(cornerRadius: VoiceOverlayMetrics.cornerRadius)
                .stroke(.primary.opacity(0.13), lineWidth: 0.7)
        )
        .overlay(alignment: .leading) {
            Capsule()
                .fill(companionState.accent)
                .frame(width: 3, height: 68)
                .padding(.leading, 1)
        }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: model.phase)
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
        case .listening: return "请开始说话…"
        case .finalizing: return "正在用最终结果替换临时稿"
        case .done: return "已写入当前光标"
        case .error: return "本次听写没有完成"
        }
    }

    private var phaseLabel: String {
        switch model.phase {
        case .listening: return "LIVE"
        case .finalizing: return "FINAL"
        case .done: return "DONE"
        case .error: return "STOP"
        }
    }
}

private struct VoiceLevelWaveform: View {
    let samples: [Double]
    let color: Color

    var body: some View {
        Canvas { context, size in
            guard !samples.isEmpty else { return }
            let centerY = size.height / 2
            let step = size.width / CGFloat(max(1, samples.count - 1))
            let amplitudes = samples.map { sample in
                max(1.4, pow(CGFloat(min(1, max(0.02, sample))), 0.72) * centerY * 0.92)
            }
            var area = Path()
            area.move(to: CGPoint(x: 0, y: centerY - amplitudes[0]))
            for index in amplitudes.indices.dropFirst() {
                area.addLine(to: CGPoint(x: CGFloat(index) * step, y: centerY - amplitudes[index]))
            }
            for index in amplitudes.indices.reversed() {
                area.addLine(to: CGPoint(x: CGFloat(index) * step, y: centerY + amplitudes[index]))
            }
            area.closeSubpath()

            var ridge = Path()
            ridge.move(to: CGPoint(x: 0, y: centerY - amplitudes[0]))
            for index in amplitudes.indices.dropFirst() {
                ridge.addLine(to: CGPoint(x: CGFloat(index) * step, y: centerY - amplitudes[index]))
            }
            var mirrored = Path()
            mirrored.move(to: CGPoint(x: 0, y: centerY + amplitudes[0]))
            for index in amplitudes.indices.dropFirst() {
                mirrored.addLine(to: CGPoint(x: CGFloat(index) * step, y: centerY + amplitudes[index]))
            }

            var centerLine = Path()
            centerLine.move(to: CGPoint(x: 0, y: centerY))
            centerLine.addLine(to: CGPoint(x: size.width, y: centerY))
            context.stroke(centerLine, with: .color(color.opacity(0.14)), lineWidth: 1)
            context.fill(
                area,
                with: .linearGradient(
                    Gradient(colors: [color.opacity(0.08), color.opacity(0.34), color.opacity(0.08)]),
                    startPoint: .zero,
                    endPoint: CGPoint(x: size.width, y: 0)
                )
            )
            context.drawLayer { layer in
                layer.addFilter(.blur(radius: 2.5))
                layer.stroke(ridge, with: .color(color.opacity(0.34)), lineWidth: 3)
                layer.stroke(mirrored, with: .color(color.opacity(0.34)), lineWidth: 3)
            }
            context.stroke(ridge, with: .color(color.opacity(0.92)), lineWidth: 1.35)
            context.stroke(mirrored, with: .color(color.opacity(0.72)), lineWidth: 1.1)
        }
        .accessibilityHidden(true)
    }
}

@MainActor
final class VoiceOverlayController {
    private let model = VoiceOverlayModel()
    private var panel: NSPanel?
    private var dismissWorkItem: DispatchWorkItem?
    private var anchorPoint: NSPoint?
    private var lastLevelUpdateAt = 0.0

    func showListening(anchor: NSPoint?) {
        dismissWorkItem?.cancel()
        model.phase = .listening
        model.message = "准备听写"
        model.transcript = ""
        model.levelHistory = Array(repeating: 0.04, count: 28)
        anchorPoint = anchor
        show(anchor: anchor)
    }

    func showRecording() {
        model.phase = .listening
        model.message = "正在听写"
        ensureVisible()
    }

    func updateTranscript(_ text: String) {
        model.transcript = String(text.suffix(240))
        ensureVisible()
    }

    func updateLevel(_ level: Double) {
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastLevelUpdateAt >= 0.08 else { return }
        lastLevelUpdateAt = now
        let response = level > model.level ? 0.78 : 0.28
        let smoothed = model.level * (1 - response) + level * response
        model.level = smoothed
        model.levelHistory = Array((model.levelHistory + [smoothed]).suffix(28))
    }

    func showFinalizing() {
        model.phase = .finalizing
        model.message = "我在校正"
        ensureVisible()
    }

    func showDone(_ text: String) {
        model.phase = .done
        model.message = "已经整理好"
        model.transcript = String(text.suffix(240))
        ensureVisible()
        scheduleDismiss(after: 1.4)
    }

    func showError(_ message: String, anchor: NSPoint? = nil) {
        model.phase = .error
        let permissionNeeded = message.contains("辅助功能") || message.contains("麦克风权限")
        model.message = permissionNeeded ? "还差一步" : "语音输入未完成"
        model.transcript = permissionNeeded ? permissionMessage(message) : message
        anchorPoint = anchor ?? anchorPoint
        show(anchor: anchorPoint)
        scheduleDismiss(after: permissionNeeded ? 4.5 : 3.2)
    }

    func dismiss() {
        dismissWorkItem?.cancel()
        dismissWorkItem = nil
        panel?.orderOut(nil)
    }

    private func show(anchor: NSPoint?) {
        let panel = panel ?? makePanel()
        self.panel = panel
        anchorPoint = anchor ?? anchorPoint
        position(panel: panel, anchor: anchorPoint ?? NSEvent.mouseLocation, animated: false)
        let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        panel.alphaValue = reduceMotion ? 1 : 0.84
        panel.orderFrontRegardless()
        if !reduceMotion {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.12
                context.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().alphaValue = 1
            }
        }
    }

    private func position(panel: NSPanel, anchor: NSPoint, animated: Bool) {
        let screen = NSScreen.screens.first(where: { NSMouseInRect(anchor, $0.frame, false) }) ?? NSScreen.main
        let target = NSSize(width: VoiceOverlayMetrics.width, height: VoiceOverlayMetrics.height)
        let frame = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = min(max(anchor.x - target.width / 2, frame.minX + 12), frame.maxX - target.width - 12)
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
                width: VoiceOverlayMetrics.width,
                height: VoiceOverlayMetrics.height
            ),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        // Codex and the Squirrel assistant both use elevated transient panels.
        // Keep live voice feedback above them without activating or stealing focus.
        panel.level = NSWindow.Level(rawValue: NSWindow.Level.screenSaver.rawValue + 1)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.ignoresMouseEvents = true
        panel.contentView = NSHostingView(rootView: VoiceOverlayView(model: model))
        return panel
    }

    private func ensureVisible() {
        guard let panel else {
            show(anchor: anchorPoint)
            return
        }
        if !panel.isVisible {
            position(panel: panel, anchor: anchorPoint ?? NSEvent.mouseLocation, animated: false)
            panel.orderFrontRegardless()
        }
    }

    private func scheduleDismiss(after delay: TimeInterval) {
        dismissWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.dismiss() }
        dismissWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func permissionMessage(_ message: String) -> String {
        if message.contains("辅助功能") { return "若开关已开启，请关闭后重新开启智鼬语音" }
        if message.contains("麦克风") { return "请在系统设置中允许使用麦克风" }
        return message
    }
}
