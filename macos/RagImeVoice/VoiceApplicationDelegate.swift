import AppKit
import ApplicationServices

@MainActor
final class VoiceApplicationDelegate: NSObject, NSApplicationDelegate {
    private var coordinator: VoiceInputCoordinator?
    private var permissionRetryTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let coordinator = VoiceInputCoordinator()
        self.coordinator = coordinator
        coordinator.onStateChanged = { [weak self] in
            self?.publishStatus()
            DistributedNotificationCenter.default().post(
                name: Notification.Name("com.rag-ime.voice.status-changed"),
                object: nil
            )
        }
        startHotkeyWhenTrusted()
        publishStatus()

        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(configurationChanged),
            name: Notification.Name("com.rag-ime.voice.configuration-changed"),
            object: nil
        )
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(requestMicrophonePermission),
            name: Notification.Name("com.rag-ime.voice.request-microphone-permission"),
            object: nil
        )
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(requestAccessibilityPermission),
            name: Notification.Name("com.rag-ime.voice.request-accessibility-permission"),
            object: nil
        )
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(beginAgentComposerSession),
            name: Notification.Name("com.rag-ime.voice.agent-composer-begin"),
            object: nil
        )
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(finishAgentComposerSession),
            name: Notification.Name("com.rag-ime.voice.agent-composer-finish"),
            object: nil
        )
        DistributedNotificationCenter.default().addObserver(
            self,
            selector: #selector(cancelAgentComposerSession),
            name: Notification.Name("com.rag-ime.voice.agent-composer-cancel"),
            object: nil
        )
    }

    func applicationWillTerminate(_ notification: Notification) {
        permissionRetryTimer?.invalidate()
        coordinator?.shutdown()
        VoiceAgentStatusStore.remove()
        DistributedNotificationCenter.default().removeObserver(self)
    }

    @objc private func configurationChanged() {
        coordinator?.reloadConfiguration()
    }

    @objc private func requestMicrophonePermission() {
        VoiceAudioRecorder.requestPermission { [weak self] _ in
            DispatchQueue.main.async { self?.publishStatus() }
        }
    }

    @objc private func requestAccessibilityPermission() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        publishStatus()
    }

    @objc private func beginAgentComposerSession() {
        coordinator?.beginAgentComposerSession()
    }

    @objc private func finishAgentComposerSession() {
        coordinator?.finishAgentComposerSession()
    }

    @objc private func cancelAgentComposerSession() {
        coordinator?.cancelAgentComposerSession()
    }

    private func startHotkeyWhenTrusted() {
        coordinator?.startHotkeyMonitor()
        if AXIsProcessTrusted() {
            if coordinator?.agentStatus().hotkeyMode != GlobalVoiceHotkey.MonitoringMode.eventTap.rawValue {
                coordinator?.restartHotkeyMonitor()
            }
            publishStatus()
            permissionRetryTimer?.invalidate()
            permissionRetryTimer = nil
            return
        }
        permissionRetryTimer?.invalidate()
        // Never trigger a TCC prompt from a background launch. The user grants
        // permissions explicitly from System Settings when convenient.
        permissionRetryTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.startHotkeyWhenTrusted() }
        }
        publishStatus()
    }

    private func publishStatus() {
        guard let coordinator else { return }
        VoiceAgentStatusStore.write(coordinator.agentStatus())
    }

}
