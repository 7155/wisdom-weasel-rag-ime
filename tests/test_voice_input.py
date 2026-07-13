from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
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
        self.assertIn("CompanionStates", build)
        self.assertNotIn("RagImeMac.app", build)
        self.assertIn("RunAtLoad bool true", launch)
        self.assertIn("KeepAlive:SuccessfulExit bool false", launch)

    def test_credentials_avoid_repeat_prompts_and_sensitive_fields_are_blocked(self) -> None:
        keychain = (ROOT / "macos/Shared/VoiceKeychainStore.swift").read_text(encoding="utf-8")
        insertion = (ROOT / "macos/RagImeVoice/VoiceTextInsertion.swift").read_text(encoding="utf-8")
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")
        configure = (ROOT / "scripts/configure_volcengine_asr.sh").read_text(encoding="utf-8")

        self.assertIn("SecItemCopyMatching", keychain)
        self.assertIn("SecItemUpdate", keychain)
        self.assertIn("VoiceCredentialFileStore.loadCredentials(provider: provider)", keychain)
        self.assertIn('"voice-credentials-\\(provider.rawValue).json"', keychain)
        self.assertIn("voice-credentials.json", keychain)
        self.assertIn(".posixPermissions: 0o600", keychain)
        self.assertIn("IsSecureEventInputEnabled", insertion)
        for marker in ("securetextfield", "password", "验证码", "账号"):
            self.assertIn(marker, insertion)
        self.assertNotIn("HistoryStore", coordinator)
        self.assertIn("VoiceCommitRecorder.record", coordinator)
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
        self.assertIn('openPrivacyPane("Privacy_Accessibility")', page)
        self.assertIn('openPrivacyPane("Privacy_Microphone")', page)
        self.assertIn('Button("打开辅助功能设置"', page)
        self.assertIn('Button("请求麦克风权限"', page)
        self.assertIn('不需要单独的“光标”权限', page)
        self.assertIn("com.rag-ime.voice.request-microphone-permission", page)
        self.assertIn("com.rag-ime.voice.request-microphone-permission", delegate)
        self.assertIn("VoiceAudioRecorder.requestPermission", delegate)

        status = (ROOT / "macos/Shared/VoiceAgentStatus.swift").read_text(encoding="utf-8")
        self.assertIn("rag-ime.voice-agent-status.v3", status)
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

    def test_final_voice_commit_enters_recent_context_without_recording_partials(self) -> None:
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")
        recorder = (ROOT / "macos/RagImeVoice/VoiceCommitRecorder.swift").read_text(encoding="utf-8")
        insertion = (ROOT / "macos/RagImeVoice/VoiceTextInsertion.swift").read_text(encoding="utf-8")
        build = (ROOT / "scripts/build_voice_input.sh").read_text(encoding="utf-8")

        partial_start = coordinator.index("case .partial(let text):")
        final_start = coordinator.index("case .final(let text):", partial_start)
        failure_start = coordinator.index("case .failure(let message):", final_start)
        self.assertNotIn("recordCommittedVoiceTextIfNeeded", coordinator[partial_start:final_start])
        self.assertIn("recordCommittedVoiceTextIfNeeded(text)", coordinator[final_start:failure_start])
        self.assertIn("appBundleIdentifier", insertion)
        self.assertIn("http://127.0.0.1:8766/api/commit", recorder)
        self.assertIn('"voice-input"', recorder)
        self.assertIn('"recent-input"', recorder)
        self.assertIn('find "$SHARED" "$SRC"', build)
        failure_start = coordinator.index("case .failure(let message):")
        failure_end = coordinator.index("case .transport(let networkState):", failure_start)
        timeout_start = coordinator.index("private func scheduleFinalTimeout()")
        self.assertNotIn("recordCommittedVoiceTextIfNeeded", coordinator[failure_start:failure_end])
        self.assertNotIn("recordCommittedVoiceTextIfNeeded", coordinator[timeout_start:])
        self.assertIn("临时稿未记入历史", coordinator)

    def test_voice_provider_credentials_and_adapters_are_isolated(self) -> None:
        keychain = (ROOT / "macos/Shared/VoiceKeychainStore.swift").read_text(encoding="utf-8")
        adapters = (ROOT / "macos/Shared/VoiceStreamingASR.swift").read_text(encoding="utf-8")
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")
        page = (ROOT / "macos/RagImeControl/Pages/VoiceInputPage.swift").read_text(encoding="utf-8")

        self.assertIn("enum VoiceASRProvider", keychain)
        self.assertIn('case nativeStreaming = "native_streaming"', keychain)
        self.assertIn('case realtimeWebSocket = "realtime_websocket"', keychain)
        self.assertIn('"com.rag-ime.voice.\\(provider.rawValue)"', keychain)
        self.assertIn("voice-provider.json", keychain)
        self.assertIn("voice-credentials-\\(provider.rawValue).json", keychain)
        self.assertIn("VoiceStreamingASRFactory.make", coordinator)
        self.assertIn("VolcengineStreamingASRClient", adapters)
        self.assertIn("RealtimeWebSocketASRClient", adapters)
        self.assertIn('"input_audio_buffer.append"', adapters)
        self.assertIn('"input_audio_buffer.commit"', adapters)
        self.assertIn("ForEach(VoiceASRProvider.allCases)", page)
        self.assertIn("provider.supportsHotwords", page)

    def test_middle_mouse_is_default_push_to_talk_and_keyboard_fallbacks_remain_configurable(self) -> None:
        config = (ROOT / "macos/Shared/VoiceHotkeyConfig.swift").read_text(encoding="utf-8")
        hotkey = (ROOT / "macos/RagImeVoice/GlobalVoiceHotkey.swift").read_text(encoding="utf-8")
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")
        page = (ROOT / "macos/RagImeControl/Pages/VoiceInputPage.swift").read_text(encoding="utf-8")
        configure = (ROOT / "scripts/configure_voice_hotkey.sh").read_text(encoding="utf-8")

        self.assertIn('case middleMouse = "middle_mouse"', config)
        self.assertIn('case rightOption = "right_option"', config)
        self.assertIn('case optionSpace = "option_space"', config)
        self.assertIn("choice: .middleMouse", config)
        self.assertIn("voice-hotkey.json", config)
        self.assertIn(".posixPermissions: 0o600", config)
        self.assertIn("CGEventType.otherMouseDown", hotkey)
        self.assertIn("CGEventType.otherMouseUp", hotkey)
        self.assertIn("mouseEventButtonNumber", hotkey)
        self.assertIn("middleMouseButton: Int64 = 2", hotkey)
        self.assertIn("CGEventType.flagsChanged", hotkey)
        self.assertIn("keyCode == 61", hotkey)
        self.assertIn("suppressedReleaseChoice", hotkey)
        self.assertIn("NSEvent.addGlobalMonitorForEvents", hotkey)
        self.assertIn("passiveMiddleMouse", hotkey)
        self.assertIn("hotkey.reloadConfiguration()", coordinator)
        self.assertIn("restartHotkeyMonitor", coordinator)
        self.assertIn("ForEach(VoiceHotkeyChoice.allCases)", page)
        self.assertIn("按住鼠标滚轮中键", page)
        self.assertIn("中键监听", page)
        self.assertIn("middle_mouse|right_option|option_space", configure)

        delegate = (ROOT / "macos/RagImeVoice/VoiceApplicationDelegate.swift").read_text(encoding="utf-8")
        self.assertLess(delegate.index("coordinator?.startHotkeyMonitor()"), delegate.index("if AXIsProcessTrusted()"))

        overlay = (ROOT / "macos/RagImeVoice/VoiceOverlay.swift").read_text(encoding="utf-8")
        companion = (ROOT / "macos/Shared/RagImeCompanionMark.swift").read_text(encoding="utf-8")
        state_assets = ROOT / "macos/Shared/Assets/CompanionStates"
        self.assertIn("RagImeAnimeCompanion", overlay)
        self.assertIn("An original book-shaped companion", companion)
        self.assertIn("Original anime companion artwork", companion)
        for state in ("Idle", "Listening", "Thinking", "Done", "Warning"):
            self.assertIn(f"RagImeCompanion{state}", companion)
            asset = state_assets / f"RagImeCompanion{state}.png"
            self.assertTrue(asset.is_file())
            self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertNotIn("Circle()\n                .fill(state.accent.opacity(0.09))", companion)
        self.assertIn("RagImeCompanionState", companion)
        self.assertIn('model.message = "听着呢"', overlay)
        self.assertIn("请关闭后重新开启 RagImeVoice", overlay)
        self.assertIn("VoiceOverlayMetrics.compactWidth", overlay)
        self.assertIn("panel.animator().setFrame", overlay)
        self.assertIn("scheduleDismiss(after: 2.2)", overlay)
        self.assertIn('credentialLabel("Access Token")', page)
        self.assertIn("Grid(alignment: .leading", page)
        self.assertIn('.help("打开辅助功能设置")', page)

        with tempfile.TemporaryDirectory(prefix="rag-ime-voice-hotkey-") as directory:
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/configure_voice_hotkey.sh"), "middle_mouse"],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "HOME": directory},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            path = Path(directory) / "Library/Application Support/RagIme/voice-hotkey.json"
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"schemaVersion": "rag-ime.voice-hotkey.v1", "choice": "middle_mouse"},
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_hotwords_are_explicit_bounded_and_not_derived_from_rime(self) -> None:
        config = (ROOT / "macos/Shared/VoiceHotwordConfig.swift").read_text(encoding="utf-8")
        asr = (ROOT / "macos/Shared/VolcengineStreamingASR.swift").read_text(encoding="utf-8")
        page = (ROOT / "macos/RagImeControl/Pages/VoiceInputPage.swift").read_text(encoding="utf-8")
        coordinator = (ROOT / "macos/RagImeVoice/VoiceInputCoordinator.swift").read_text(encoding="utf-8")

        self.assertIn("maxWordCount = 32", config)
        self.assertIn("minCharactersPerWord = 2", config)
        self.assertIn("maxCharactersPerWord = 9", config)
        self.assertIn("voice-hotwords.json", config)
        self.assertIn(".posixPermissions: 0o600", config)
        self.assertIn('request["context"] = context', asr)
        self.assertIn('"hotwords": effectiveWords.map', config)
        self.assertIn("VoiceHotwordConfigStore.read()", coordinator)
        self.assertIn("仅发送此处显式保存的词，不读取 Rime 用户词典", page)
        self.assertNotIn("rime", config.lower())

        status = (ROOT / "macos/Shared/VoiceAgentStatus.swift").read_text(encoding="utf-8")
        self.assertIn("let hotwordsEnabled: Bool", status)
        self.assertIn("let hotwordCount: Int", status)
        self.assertNotIn("let hotwords:", status)

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
        self.assertIn("value as? URL", insertion)
        self.assertIn("url.absoluteString", insertion)
        self.assertIn("Unknown optional metadata types", insertion)
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

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS Security framework")
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
        precondition(VoiceHotkeyConfig.default.choice == .middleMouse)
        precondition(VoiceHotkeyChoice.allCases.first == .middleMouse)
        precondition(VoiceHotkeyChoice.allCases.contains(.rightOption))
        precondition(VoiceHotkeyChoice.allCases.contains(.optionSpace))
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

        var secondPass = VoiceTranscriptReconciler()
        _ = secondPass.revise(to: "豆包", isFinal: false)!
        let corrected = secondPass.revise(to: "豆包 API 已修正。", isFinal: true)!
        precondition(corrected.replacementUTF16Length == 2)
        precondition(corrected.text == "豆包 API 已修正。")

        let json: [String: Any] = ["result": ["utterances": [["text": "边说"], ["text": "边写"]]]]
        precondition(VolcengineStreamingASRClient.transcript(from: json) == "边说边写")
        let secondPassJSON: [String: Any] = [
            "result": ["text": "豆包 API 已修正。", "utterances": [["text": "豆包"]]]
        ]
        precondition(VolcengineStreamingASRClient.transcript(from: secondPassJSON) == "豆包 API 已修正。")

        let hotwords = try! VoiceASRHotwordConfig.validated(
            enabled: true,
            rawLines: "MiniMind\nDeepSeek\nminimind\n火山语音"
        )
        precondition(hotwords.words == ["MiniMind", "DeepSeek", "火山语音"])
        let requestPayload = VolcengineStreamingASRClient.initialRequestPayload(
            connectID: "test-connect-id",
            hotwordConfig: hotwords
        )
        let request = requestPayload["request"] as! [String: Any]
        precondition(request["enable_nonstream"] as? Bool == true)
        precondition(request["result_type"] as? String == "full")
        let context = request["context"] as! String
        let contextData = context.data(using: .utf8)!
        let contextJSON = try! JSONSerialization.jsonObject(with: contextData) as! [String: Any]
        let requestHotwords = contextJSON["hotwords"] as! [[String: String]]
        precondition(requestHotwords.map { $0["word"]! } == hotwords.words)

        let disabledPayload = VolcengineStreamingASRClient.initialRequestPayload(
            connectID: "test-connect-id",
            hotwordConfig: .disabled
        )
        let disabledRequest = disabledPayload["request"] as! [String: Any]
        precondition(disabledRequest["context"] == nil)
        precondition((try? VoiceASRHotwordConfig.validated(enabled: true, rawLines: "RAG-IME")) == nil)
        precondition((try? VoiceASRHotwordConfig.validated(enabled: true, rawLines: "用")) == nil)

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
                    str(ROOT / "macos/Shared/VoiceHotkeyConfig.swift"),
                    str(ROOT / "macos/Shared/VoiceKeychainStore.swift"),
                    str(ROOT / "macos/Shared/VoiceAgentStatus.swift"),
                    str(ROOT / "macos/Shared/VoiceHotwordConfig.swift"),
                    str(ROOT / "macos/Shared/VoiceStreamingASR.swift"),
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
