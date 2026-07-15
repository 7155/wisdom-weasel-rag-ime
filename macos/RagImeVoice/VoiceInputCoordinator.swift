import ApplicationServices
import Foundation

@MainActor
final class VoiceInputCoordinator {
    enum State {
        case idle
        case starting
        case recording
        case finalizing
    }

    private enum InteractionSource: String {
        case hotkey
        case agentComposer = "agent_composer"
    }

    var onStateChanged: (() -> Void)?

    private let hotkey = GlobalVoiceHotkey()
    private let recorder = VoiceAudioRecorder()
    private let overlay = VoiceOverlayController()
    private var credentials: VoiceASRCredentials?
    private var hotwordConfig = VoiceASRHotwordConfig.disabled
    private var asr: VoiceStreamingASRClient?
    private var insertion: VoiceTextInsertionSession?
    private var reconciler = VoiceTranscriptReconciler()
    private var state: State = .idle
    private var hotkeyPressed = false
    private var hotkeyInstalled = false
    private var sessionGeneration = 0
    private var finalTimeout: DispatchWorkItem?
    private var telemetry = VoiceSessionTelemetry.idle
    private var releasedAtMs: Int?
    private var committedVoiceTextRecorded = false
    private var interactionSource: InteractionSource = .hotkey

    init() {
        credentials = VoiceKeychainStore.loadCredentials(allowLegacyFallback: true)
        hotwordConfig = VoiceHotwordConfigStore.read()
        hotkey.onPress = { [weak self] in self?.press(source: .hotkey) }
        hotkey.onRelease = { [weak self] in self?.release() }
        hotkey.onCancel = { [weak self] in self?.cancel(reason: "用户取消") }
    }

    var isReady: Bool {
        credentials?.isComplete == true && AXIsProcessTrusted() && hotkeyInstalled
    }

    var statusText: String {
        if credentials?.isComplete != true { return "未配置语音服务" }
        if !AXIsProcessTrusted() {
            return hotkeyInstalled ? "中键监听已就绪，写入需辅助功能权限" : "等待辅助功能权限"
        }
        if !hotkeyInstalled { return "语音快捷键未启动" }
        switch state {
        case .idle: return VoiceAudioRecorder.permissionGranted ? "语音输入已就绪" : "首次使用时申请麦克风权限"
        case .starting: return "正在启动语音输入"
        case .recording: return interactionSource == .agentComposer ? "正在向智鼬输入" : "正在听写"
        case .finalizing: return interactionSource == .agentComposer ? "正在整理对话草稿" : "正在等待最终定稿"
        }
    }

    func agentStatus() -> VoiceAgentStatus {
        VoiceAgentStatus(
            schemaVersion: VoiceAgentStatus.schemaVersion,
            processID: ProcessInfo.processInfo.processIdentifier,
            running: true,
            accessibilityTrusted: AXIsProcessTrusted(),
            microphoneAuthorization: VoiceAudioRecorder.authorizationName,
            credentialsConfigured: credentials?.isComplete == true,
            hotkeyMode: hotkey.monitoringMode.rawValue,
            hotwordsEnabled: hotwordConfig.enabled,
            hotwordCount: hotwordConfig.effectiveWords.count,
            hotkeyInstalled: hotkeyInstalled,
            state: stateName,
            interactionSource: state == .idle ? "none" : interactionSource.rawValue,
            statusText: statusText,
            recognition: .current,
            telemetry: telemetry,
            updatedAtMs: Int(Date().timeIntervalSince1970 * 1000)
        )
    }

    private var stateName: String {
        switch state {
        case .idle: return "idle"
        case .starting: return "starting"
        case .recording: return "recording"
        case .finalizing: return "finalizing"
        }
    }

    func startHotkeyMonitor() {
        guard !hotkeyInstalled else { return }
        hotkeyInstalled = hotkey.start()
        onStateChanged?()
    }

    func restartHotkeyMonitor() {
        hotkey.stop()
        hotkeyInstalled = hotkey.start()
        onStateChanged?()
    }

    func reloadConfiguration() {
        credentials = VoiceKeychainStore.loadCredentials(allowLegacyFallback: true)
        hotwordConfig = VoiceHotwordConfigStore.read()
        hotkey.reloadConfiguration()
        onStateChanged?()
    }

    func shutdown() {
        hotkey.stop()
        hotkeyInstalled = false
        cancel(reason: "语音代理退出", showMessage: false)
    }

    func beginAgentComposerSession() {
        press(source: .agentComposer)
    }

    func finishAgentComposerSession() {
        guard interactionSource == .agentComposer else { return }
        release()
    }

    func cancelAgentComposerSession() {
        guard interactionSource == .agentComposer else { return }
        cancel(reason: "已取消对话语音输入", showMessage: false)
    }

    private func press(source: InteractionSource) {
        guard state == .idle else { return }
        // The Web Control Center writes the same bounded JSON file consumed by
        // the native agent. Reload at the session boundary so a saved list is
        // effective even when a distributed notification was missed.
        hotwordConfig = VoiceHotwordConfigStore.read()
        interactionSource = source
        hotkeyPressed = true
        guard let credentials, credentials.isComplete else {
            overlay.showError("请先在控制中心配置语音服务凭据")
            interactionSource = .hotkey
            return
        }
        let insertion: VoiceTextInsertionSession
        do {
            insertion = try VoiceTextInsertionSession.capture()
        } catch {
            overlay.showError(error.localizedDescription)
            interactionSource = .hotkey
            return
        }
        guard source != .agentComposer || insertion.appBundleIdentifier == "com.rag-ime.control" else {
            overlay.showError("请先把光标放回智鼬对话输入框")
            interactionSource = .hotkey
            return
        }
        state = .starting
        sessionGeneration += 1
        let generation = sessionGeneration
        self.insertion = insertion
        reconciler = VoiceTranscriptReconciler()
        releasedAtMs = nil
        committedVoiceTextRecorded = false
        telemetry = VoiceSessionTelemetry(
            networkState: "starting",
            sessionActive: true,
            sessionStartedAtMs: nowMs,
            firstPartialLatencyMs: nil,
            finalLatencyMs: nil,
            pcmFrameCount: 0,
            droppedPCMFrameCount: 0,
            partialRevisionCount: 0,
            finalReceived: false
        )
        overlay.showListening(anchor: insertion.anchorPoint)
        onStateChanged?()

        VoiceAudioRecorder.requestPermission { [weak self] granted in
            DispatchQueue.main.async {
                guard let self, generation == self.sessionGeneration, self.hotkeyPressed else { return }
                guard granted else {
                    self.fail("麦克风权限未开启")
                    return
                }
                self.beginRecording(credentials: credentials, generation: generation)
            }
        }
    }

    private func beginRecording(credentials: VoiceASRCredentials, generation: Int) {
        do {
            _ = try requireSafeInsertionTarget()
        } catch {
            abortForUnsafeTarget(error)
            return
        }
        let client = VoiceStreamingASRFactory.make(
            credentials: credentials,
            hotwordConfig: credentials.provider.supportsHotwords ? hotwordConfig : .disabled
        ) { [weak self] event in
            DispatchQueue.main.async {
                guard let self, generation == self.sessionGeneration else { return }
                self.handle(event)
            }
        }
        asr = client
        recorder.onPCM = { [weak self, weak client] data in
            DispatchQueue.main.async {
                guard let self, let client else { return }
                self.forwardPCMIfSafe(data, to: client, generation: generation)
            }
        }
        recorder.onLevel = { [weak self] level in
            DispatchQueue.main.async { self?.overlay.updateLevel(level) }
        }
        client.start()
        do {
            try recorder.start()
            state = .recording
            overlay.showRecording()
            onStateChanged?()
        } catch {
            client.cancel()
            fail(error.localizedDescription)
        }
    }

    private func release() {
        hotkeyPressed = false
        switch state {
        case .starting:
            cancel(reason: "录音尚未开始", showMessage: false)
        case .recording:
            recorder.stop()
            do {
                _ = try requireSafeInsertionTarget()
            } catch {
                abortForUnsafeTarget(error)
                return
            }
            state = .finalizing
            releasedAtMs = nowMs
            overlay.showFinalizing()
            asr?.finish()
            scheduleFinalTimeout()
            onStateChanged?()
        case .idle, .finalizing:
            break
        }
    }

    private func handle(_ event: VoiceASREvent) {
        switch event {
        case .partial(let text):
            let firstLatency = telemetry.firstPartialLatencyMs ?? elapsedSinceSessionStart
            telemetry = updatingTelemetry(
                networkState: "streaming",
                firstPartialLatencyMs: firstLatency,
                partialRevisionCount: telemetry.partialRevisionCount + 1
            )
            apply(text: text, isFinal: false)
        case .final(let text):
            finalTimeout?.cancel()
            finalTimeout = nil
            guard !text.isEmpty else {
                fail("没有识别到语音")
                return
            }
            guard apply(text: text, isFinal: true) else { return }
            telemetry = updatingTelemetry(
                networkState: "completed",
                finalLatencyMs: releasedAtMs.map { max(0, nowMs - $0) },
                finalReceived: true
            )
            if interactionSource == .hotkey {
                recordCommittedVoiceTextIfNeeded(text)
            }
            overlay.showDone(text)
            finishSession()
        case .failure(let message):
            telemetry = updatingTelemetry(networkState: "failed")
            finalTimeout?.cancel()
            finalTimeout = nil
            if reconciler.currentText.isEmpty {
                fail(message)
            } else {
                // A partial transcript may stay visible for the user to recover,
                // but it is never promoted into history/memory without a Final.
                overlay.showError("网络中断，临时稿未记入历史")
                finishSession()
            }
        case .transport(let networkState):
            telemetry = updatingTelemetry(networkState: networkState)
            onStateChanged?()
        }
    }

    @discardableResult
    private func apply(text: String, isFinal: Bool) -> Bool {
        do {
            _ = try requireSafeInsertionTarget()
        } catch {
            abortForUnsafeTarget(error)
            return false
        }
        guard let revision = reconciler.revise(to: text, isFinal: isFinal) else { return true }
        do {
            try insertion?.apply(revision)
            overlay.updateTranscript(text)
            return true
        } catch {
            abortForUnsafeTarget(error)
            return false
        }
    }

    private func forwardPCMIfSafe(
        _ data: Data,
        to client: VoiceStreamingASRClient,
        generation: Int
    ) {
        guard generation == sessionGeneration,
              state == .recording,
              asr === client else {
            telemetry = updatingTelemetry(droppedPCMFrameCount: telemetry.droppedPCMFrameCount + 1)
            onStateChanged?()
            return
        }
        do {
            _ = try requireSafeInsertionTarget()
        } catch {
            abortForUnsafeTarget(error)
            return
        }
        telemetry = updatingTelemetry(pcmFrameCount: telemetry.pcmFrameCount + 1)
        client.appendPCM(data)
    }

    private func requireSafeInsertionTarget() throws -> VoiceTextInsertionSession {
        guard let insertion else { throw VoiceInsertionError.privacyStateUnknown }
        try insertion.validateForAudioTransmission()
        return insertion
    }

    private func abortForUnsafeTarget(_ error: Error) {
        cancel(reason: error.localizedDescription, showMessage: true)
    }

    private func cancel(reason: String, showMessage: Bool = false) {
        sessionGeneration += 1
        hotkeyPressed = false
        finalTimeout?.cancel()
        finalTimeout = nil
        recorder.stop()
        asr?.cancel()
        if let removal = reconciler.clear() { try? insertion?.apply(removal) }
        if showMessage { overlay.showError(reason) } else { overlay.dismiss() }
        finishSession()
    }

    private func fail(_ message: String) {
        recorder.stop()
        asr?.cancel()
        overlay.showError(message, anchor: insertion?.anchorPoint)
        finishSession()
    }

    private func finishSession() {
        recorder.onPCM = nil
        recorder.onLevel = nil
        asr = nil
        insertion = nil
        reconciler = VoiceTranscriptReconciler()
        state = .idle
        interactionSource = .hotkey
        telemetry = updatingTelemetry(sessionActive: false)
        onStateChanged?()
    }

    private func recordCommittedVoiceTextIfNeeded(_ text: String) {
        guard !committedVoiceTextRecorded, let insertion else { return }
        committedVoiceTextRecorded = true
        VoiceCommitRecorder.record(text: text, appBundleIdentifier: insertion.appBundleIdentifier)
    }

    private func scheduleFinalTimeout() {
        finalTimeout?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.state == .finalizing else { return }
            if self.reconciler.currentText.isEmpty {
                self.fail("语音定稿超时")
            } else {
                self.overlay.showError("定稿超时，临时稿未记入历史")
                self.finishSession()
            }
        }
        finalTimeout = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 12, execute: work)
    }

    private var nowMs: Int { Int(Date().timeIntervalSince1970 * 1000) }

    private var elapsedSinceSessionStart: Int? {
        telemetry.sessionStartedAtMs.map { max(0, nowMs - $0) }
    }

    private func updatingTelemetry(
        networkState: String? = nil,
        sessionActive: Bool? = nil,
        firstPartialLatencyMs: Int? = nil,
        finalLatencyMs: Int? = nil,
        pcmFrameCount: Int? = nil,
        droppedPCMFrameCount: Int? = nil,
        partialRevisionCount: Int? = nil,
        finalReceived: Bool? = nil
    ) -> VoiceSessionTelemetry {
        VoiceSessionTelemetry(
            networkState: networkState ?? telemetry.networkState,
            sessionActive: sessionActive ?? telemetry.sessionActive,
            sessionStartedAtMs: telemetry.sessionStartedAtMs,
            firstPartialLatencyMs: firstPartialLatencyMs ?? telemetry.firstPartialLatencyMs,
            finalLatencyMs: finalLatencyMs ?? telemetry.finalLatencyMs,
            pcmFrameCount: pcmFrameCount ?? telemetry.pcmFrameCount,
            droppedPCMFrameCount: droppedPCMFrameCount ?? telemetry.droppedPCMFrameCount,
            partialRevisionCount: partialRevisionCount ?? telemetry.partialRevisionCount,
            finalReceived: finalReceived ?? telemetry.finalReceived
        )
    }
}
