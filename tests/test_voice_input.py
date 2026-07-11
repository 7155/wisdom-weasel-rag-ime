from __future__ import annotations

import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VoiceInputTests(unittest.TestCase):
    def test_voice_agent_bundle_and_build_contract(self) -> None:
        with (ROOT / "macos/RagImeVoice/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        build = (ROOT / "scripts/build_voice_input.sh").read_text(encoding="utf-8")
        launch = (ROOT / "scripts/install_voice_input_launch_agent.sh").read_text(encoding="utf-8")

        self.assertEqual(info["CFBundleIdentifier"], "com.rag-ime.voice")
        self.assertTrue(info["LSUIElement"])
        self.assertIn("NSMicrophoneUsageDescription", info)
        for framework in ("AVFoundation", "ApplicationServices", "Carbon", "Security"):
            self.assertIn(f"-framework {framework}", build)
        self.assertIn("scripts/support/build_app_icon.sh", build)
        self.assertNotIn("RagImeMac.app", build)
        self.assertIn("RunAtLoad bool true", launch)
        self.assertIn("KeepAlive:SuccessfulExit bool false", launch)

    def test_credentials_are_keychain_only_and_sensitive_fields_are_blocked(self) -> None:
        keychain = (ROOT / "macos/Shared/VoiceKeychainStore.swift").read_text(encoding="utf-8")
        insertion = (ROOT / "macos/RagImeVoice/VoiceTextInsertion.swift").read_text(encoding="utf-8")
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")
        configure = (ROOT / "scripts/configure_volcengine_asr.sh").read_text(encoding="utf-8")

        self.assertIn("SecItemCopyMatching", keychain)
        self.assertIn("SecItemUpdate", keychain)
        self.assertIn("IsSecureEventInputEnabled", insertion)
        for marker in ("securetextfield", "password", "验证码", "账号"):
            self.assertIn(marker, insertion)
        self.assertNotIn("history", coordinator.lower())
        self.assertIn("security add-generic-password", configure)
        self.assertIn('-T "$VOICE_BIN"', configure)
        self.assertIn('-T "$CONTROL_BIN"', configure)

        delegate = (ROOT / "macos/RagImeVoice/VoiceApplicationDelegate.swift").read_text(encoding="utf-8")
        self.assertNotIn("AXIsProcessTrustedWithOptions", delegate)
        self.assertIn("Never trigger a TCC prompt", delegate)
        self.assertNotIn("NSStatusItem", delegate)
        self.assertNotIn("NSStatusBar", delegate)

        page = (ROOT / "macos/RagImeControl/Pages/VoiceInputPage.swift").read_text(encoding="utf-8")
        self.assertIn("停止语音代理", page)
        self.assertIn("启动语音代理", page)
        self.assertIn("VoiceAgentStatusStore.read()", page)
        self.assertNotIn("AXIsProcessTrusted", page)
        self.assertNotIn("AVCaptureDevice.authorizationStatus", page)

        status = (ROOT / "macos/Shared/VoiceAgentStatus.swift").read_text(encoding="utf-8")
        self.assertIn("rag-ime.voice-agent-status.v2", status)
        self.assertIn("voice-agent-status.json", status)
        self.assertIn(".posixPermissions: 0o600", status)
        for marker in (
            "networkState",
            "firstPartialLatencyMs",
            "finalLatencyMs",
            "pcmFrameCount",
            "droppedPCMFrameCount",
            "partialRevisionCount",
        ):
            self.assertIn(marker, status)
        self.assertIn("仅记录状态、数量与时延，不保存音频或转写文本", page)
        self.assertIn("VoiceAgentStatusStore.write", delegate)

    def test_pcm_privacy_gate_revalidates_and_cancellation_drops_queued_audio(self) -> None:
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")
        insertion = (ROOT / "macos/RagImeVoice/VoiceTextInsertion.swift").read_text(encoding="utf-8")
        policy = (ROOT / "macos/RagImeVoice/VoicePrivacyPolicy.swift").read_text(encoding="utf-8")
        asr = (ROOT / "macos/Shared/VolcengineStreamingASR.swift").read_text(encoding="utf-8")

        forward_start = coordinator.index("private func forwardPCMIfSafe")
        forward_end = coordinator.index("private func requireSafeInsertionTarget", forward_start)
        forward = coordinator[forward_start:forward_end]
        self.assertLess(forward.index("try requireSafeInsertionTarget()"), forward.index("client.appendPCM(data)"))
        self.assertGreaterEqual(coordinator.count("try requireSafeInsertionTarget()"), 4)
        self.assertIn("abortForUnsafeTarget(error)", coordinator)

        self.assertIn("func validateForAudioTransmission() throws", insertion)
        self.assertIn("VoiceInsertionError.privacyStateUnknown", insertion)
        self.assertIn("AXUIElementGetPid", insertion)
        self.assertIn("VoicePrivacyPolicy.denies", insertion)
        self.assertIn("case .attributeUnsupported, .noValue", insertion)

        for marker in ("com.1password", "com.icbc", "org.torproject.torbrowser", "incognito", "无痕"):
            self.assertIn(marker, policy.lower())
        self.assertIn("RAG_IME_VOICE_DENIED_BUNDLE_IDS", policy)

        cancel_start = asr.index("func cancel()")
        cancel_end = asr.index("private func startOnQueue", cancel_start)
        cancel_body = asr[cancel_start:cancel_end]
        self.assertLess(cancel_body.index("requestCancellation()"), cancel_body.index("queue.async"))
        self.assertIn("!wasCancellationRequested()", asr)
        self.assertIn("outboundFrames.removeAll()", asr)
        self.assertIn("pendingAudio.removeAll()", asr)

    def test_protocol_and_revision_state_machine_in_swift(self) -> None:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")
        harness = r'''
import Foundation

@main
enum Harness {
    static func main() {
        let payload = Data("hello".utf8)
        let frame = VoiceASRFrame.build(
            messageType: .fullClientRequest,
            flags: .positiveSequence,
            serializationJSON: true,
            payload: payload,
            sequence: 1
        )
        precondition(Array(frame.prefix(4)) == [0x11, 0x11, 0x10, 0x00])
        let parsed = VoiceASRFrame.parse(frame)!
        precondition(parsed.sequence == 1)
        precondition(parsed.payload == payload)
        precondition(!parsed.isFinal)

        let final = VoiceASRFrame.build(
            messageType: .audioOnlyRequest,
            flags: .negativeSequence,
            serializationJSON: false,
            payload: Data(),
            sequence: -4
        )
        precondition(VoiceASRFrame.parse(final)!.isFinal)

        var reconciler = VoiceTranscriptReconciler()
        let first = reconciler.revise(to: "你好", isFinal: false)!
        precondition(first.replacementUTF16Length == 0)
        let second = reconciler.revise(to: "你好世界", isFinal: false)!
        precondition(second.replacementUTF16Length == 2)
        let done = reconciler.revise(to: "你好，世界。", isFinal: true)!
        precondition(done.replacementUTF16Length == 4)
        precondition(done.isFinal)

        let json: [String: Any] = ["result": ["utterances": [["text": "边说"], ["text": "边写"]]]]
        precondition(VolcengineStreamingASRClient.transcript(from: json) == "边说边写")

        precondition(VoicePrivacyPolicy.denies(
            bundleIdentifier: "com.1Password.1Password",
            applicationName: "1Password",
            metadata: "",
            environment: [:]
        ))
        precondition(VoicePrivacyPolicy.denies(
            bundleIdentifier: "com.example.browser",
            applicationName: "Browser",
            metadata: "Incognito Window",
            environment: [:]
        ))
        precondition(VoicePrivacyPolicy.denies(
            bundleIdentifier: "com.example.private-notes",
            applicationName: "Notes",
            metadata: "",
            environment: [VoicePrivacyPolicy.additionalBundleIDsEnvironmentKey: "com.example.private-notes"]
        ))
        precondition(!VoicePrivacyPolicy.denies(
            bundleIdentifier: "com.example.editor",
            applicationName: "Editor",
            metadata: "document",
            environment: [:]
        ))

        let telemetry = VoiceSessionTelemetry(
            networkState: "streaming",
            sessionActive: true,
            sessionStartedAtMs: 100,
            firstPartialLatencyMs: 42,
            finalLatencyMs: nil,
            pcmFrameCount: 7,
            droppedPCMFrameCount: 0,
            partialRevisionCount: 2,
            finalReceived: false
        )
        let encoded = try! JSONEncoder().encode(telemetry)
        precondition(try! JSONDecoder().decode(VoiceSessionTelemetry.self, from: encoded) == telemetry)
        precondition(String(data: encoded, encoding: .utf8)?.contains("边说") == false)
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="rag-ime-voice-test-") as directory:
            temp = Path(directory)
            harness_path = temp / "Harness.swift"
            binary = temp / "voice-protocol-test"
            harness_path.write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                [
                    swiftc,
                    "-parse-as-library",
                    str(ROOT / "macos/Shared/VoiceKeychainStore.swift"),
                    str(ROOT / "macos/Shared/VoiceAgentStatus.swift"),
                    str(ROOT / "macos/Shared/VolcengineStreamingASR.swift"),
                    str(ROOT / "macos/RagImeVoice/VoicePrivacyPolicy.swift"),
                    str(harness_path),
                    "-framework",
                    "Security",
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
            self.assertEqual(executed.returncode, 0, executed.stderr)


if __name__ == "__main__":
    unittest.main()
