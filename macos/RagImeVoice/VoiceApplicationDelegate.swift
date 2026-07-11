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

    private func startHotkeyWhenTrusted() {
        if AXIsProcessTrusted() {
            coordinator?.startHotkeyMonitor()
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
