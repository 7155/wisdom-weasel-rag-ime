from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from rag_ime.debug_server import DebugImeService, DebugServerConfig
from rag_ime.voice_control import (
    VoiceHotwordConfig,
    VoiceHotwordConfigStore,
    VoiceHotwordValidationError,
    normalize_voice_hotwords,
    read_voice_control_status,
)


class VoiceHotwordValidationTests(unittest.TestCase):
    def test_technical_hotwords_are_normalized_without_being_auto_enabled(self) -> None:
        words = normalize_voice_hotwords(
            [" GPT-5.6 ", "API   Key", "SK", "C++", "gpt-5.6"],
            enabled=False,
        )

        self.assertEqual(words, ("GPT-5.6", "API Key", "SK", "C++"))

    def test_unsupported_or_unbounded_hotwords_are_rejected(self) -> None:
        for word in ("A", "1234567890", "bad|word", "bad{json", "语音🎙"):
            with self.subTest(word=word), self.assertRaises(VoiceHotwordValidationError):
                normalize_voice_hotwords([word], enabled=False)
        with self.assertRaises(VoiceHotwordValidationError):
            normalize_voice_hotwords([], enabled=True)
        with self.assertRaises(VoiceHotwordValidationError):
            normalize_voice_hotwords([f"词{i:02d}" for i in range(33)], enabled=False)

    def test_store_is_atomic_private_and_status_tracks_the_running_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-voice-control-") as tmp:
            support = Path(tmp)
            store = VoiceHotwordConfigStore(support)
            store.write(VoiceHotwordConfig(enabled=True, words=("GPT-5.6", "API Key")))
            (support / "voice-agent-status.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.voice-agent-status.v4",
                        "running": True,
                        "processID": os.getpid(),
                        "state": "idle",
                        "hotkeyMode": "middle_mouse",
                        "hotwordsEnabled": True,
                        "hotwordCount": 2,
                        "credentialsConfigured": True,
                        "microphoneAuthorization": "authorized",
                        "accessibilityTrusted": True,
                        "updatedAtMs": 1_900_000_000_000,
                        "recognition": {
                            "finalSecondPass": True,
                            "semanticSmoothing": True,
                            "fullResultReplacement": True,
                            "providerResponseMetadata": True,
                            "thirdPassRefinement": True,
                        },
                        "telemetry": {
                            "finalReceived": True,
                            "finalLatencyMs": 116,
                            "finalRevisedPartial": True,
                            "providerFinalRevisedPartial": False,
                            "localSmoothingApplied": True,
                            "providerResponseStage": "nonstream",
                            "providerResponseStages": ["stream_snapshot", "nonstream"],
                            "providerResponseCount": 2,
                            "providerResponseSequence": -17,
                            "providerFinalFrame": True,
                            "providerResultFields": ["additions", "utterances"],
                            "providerUtteranceMetadata": [
                                {"start_time": "0", "end_time": "116", "definite": "true"}
                            ],
                            "providerAdditionFields": {
                                "duration": "116",
                                "result_type": "nonstream",
                            },
                            "thirdPassRequested": True,
                            "thirdPassApplied": True,
                            "thirdPassChanged": True,
                            "thirdPassLatencyMs": 842,
                            "thirdPassModel": "gpt/gpt-5.6-luna",
                            "partialRevisionCount": 42,
                            "droppedPCMFrameCount": 0,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            binary = support / "RagImeVoice"
            binary.write_bytes(b"enable_nonstream enable_ddc result_type full")

            status = read_voice_control_status(support, binary_path=binary)

            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(store.read().words, ("GPT-5.6", "API Key"))
            self.assertEqual(status["hotwords"]["applyState"], "loaded")
            self.assertTrue(status["hotwords"]["inSync"])
            self.assertTrue(status["recognition"]["deployed"]["secondPass"])
            self.assertTrue(status["recognition"]["deployed"]["semanticSmoothing"])
            self.assertTrue(status["recognition"]["deployed"]["fullResultReplacement"])
            self.assertTrue(status["recognition"]["deployed"]["providerResponseMetadata"])
            self.assertTrue(status["recognition"]["deployed"]["thirdPassRefinement"])
            self.assertEqual(status["recognition"]["deployed"]["state"], "ready")
            self.assertTrue(status["recognition"]["deployed"]["reportedByAgent"])
            self.assertEqual(status["recognition"]["lastSession"]["finalLatencyMs"], 116)
            self.assertTrue(status["recognition"]["lastSession"]["finalRevisedPartial"])
            self.assertFalse(
                status["recognition"]["lastSession"]["providerFinalRevisedPartial"]
            )
            self.assertTrue(status["recognition"]["lastSession"]["localSmoothingApplied"])
            last = status["recognition"]["lastSession"]
            self.assertEqual(last["providerResponseStage"], "nonstream")
            self.assertEqual(last["providerResponseStages"], ["stream_snapshot", "nonstream"])
            self.assertEqual(last["providerResponseSequence"], -17)
            self.assertEqual(last["providerUtteranceMetadata"][0]["end_time"], "116")
            self.assertEqual(last["providerAdditionFields"]["duration"], "116")
            self.assertTrue(last["thirdPassApplied"])
            self.assertEqual(last["thirdPassModel"], "gpt/gpt-5.6-luna")

    def test_old_binary_explains_missing_final_replacement_instead_of_hiding_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-voice-old-build-") as tmp:
            support = Path(tmp)
            binary = support / "RagImeVoice"
            binary.write_bytes(b"enable_nonstream")

            status = read_voice_control_status(support, binary_path=binary)
            deployed = status["recognition"]["deployed"]

            self.assertTrue(deployed["secondPass"])
            self.assertFalse(deployed["semanticSmoothing"])
            self.assertFalse(deployed["fullResultReplacement"])
            self.assertFalse(deployed["providerResponseMetadata"])
            self.assertFalse(deployed["thirdPassRefinement"])
            self.assertEqual(deployed["state"], "outdated")
            self.assertIn("complete final-result contract", deployed["reason"])

    def test_new_build_marker_distinguishes_installed_from_running_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-voice-marker-") as tmp:
            support = Path(tmp)
            binary = support / "Contents" / "MacOS" / "RagImeVoice"
            resources = support / "Contents" / "Resources"
            binary.parent.mkdir(parents=True)
            resources.mkdir(parents=True)
            binary.write_bytes(b"optimized-binary-without-readable-symbols")
            (resources / "rag-ime-voice-build-marker.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.voice-build-marker.v1",
                        "gitCommit": "a" * 40,
                        "gitDirty": False,
                        "capabilities": {
                            "finalSecondPass": True,
                            "semanticSmoothing": True,
                            "fullResultReplacement": True,
                            "providerResponseMetadata": True,
                            "thirdPassRefinement": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            deployed = read_voice_control_status(support, binary_path=binary)["recognition"]["deployed"]

            self.assertEqual(deployed["state"], "restart_required")
            self.assertTrue(deployed["buildMarkerFound"])
            self.assertEqual(deployed["sourceCommit"], "a" * 40)


class VoiceHotwordWorkContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-voice-work-")
        self.db_path = Path(self.tmp.name) / "voice.sqlite"
        self.service = DebugImeService(
            DebugServerConfig(db_path=self.db_path, seed_if_empty=False)
        )

    def tearDown(self) -> None:
        self.service.agent.close()
        self.service.management.close()
        self.tmp.cleanup()

    def test_preview_apply_and_rollback_write_the_voice_agent_file(self) -> None:
        changes = {
            "voice.hotwordsEnabled": True,
            "voice.hotwords": ["GPT-5.6", "API Key", "智鼬"],
        }
        initial = self.service.settings()
        preview = self.service.configuration_settings_preview(
            {
                "changes": changes,
                "expectedRuntimeRevision": initial["runtimeConfig"]["runtimeRevision"],
            }
        )
        applied = self.service.configuration_settings_apply(
            {
                "changes": changes,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )

        hotword_path = Path(self.tmp.name) / "voice-hotwords.json"
        saved = json.loads(hotword_path.read_text(encoding="utf-8"))
        current = self.service.settings()

        self.assertTrue(applied["ok"])
        self.assertEqual(
            applied["rollbackAuthority"],
            {"settingKeys": ["voice.hotwords", "voice.hotwordsEnabled"]},
        )
        self.assertEqual(saved["words"], ["GPT-5.6", "API Key", "智鼬"])
        self.assertTrue(saved["enabled"])
        self.assertEqual(hotword_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(current["settings"]["voice"]["hotwords"], saved["words"])
        self.assertEqual(current["voiceControl"]["hotwords"]["applyState"], "next_session")

        rolled_back = self.service.configuration_settings_rollback(
            {
                "receiptId": applied["receiptId"],
                "rollbackToken": applied["rollbackToken"],
                "payloadSha256": applied["payloadSha256"],
                "confirmText": "rollback",
            }
        )
        restored = json.loads(hotword_path.read_text(encoding="utf-8"))

        self.assertTrue(rolled_back["ok"])
        self.assertEqual(restored["words"], [])
        self.assertFalse(restored["enabled"])
        self.assertEqual(self.service.settings()["settings"]["voice"]["hotwords"], [])

    def test_invalid_hotword_is_rejected_before_a_preview_is_issued(self) -> None:
        denied = self.service.configuration_settings_preview(
            {
                "changes": {
                    "voice.hotwordsEnabled": True,
                    "voice.hotwords": ["bad|word"],
                },
                "expectedRuntimeRevision": self.service.settings()["runtimeConfig"]["runtimeRevision"],
            }
        )

        self.assertFalse(denied["ok"])
        self.assertEqual(denied["errorCode"], "invalid_request")
        self.assertFalse((Path(self.tmp.name) / "voice-hotwords.json").exists())

    def test_provider_and_hotkey_apply_incrementally_and_rollback(self) -> None:
        changes = {
            "voice.provider": "realtime_websocket",
            "voice.hotkey": "option_space",
        }
        initial = self.service.settings()
        preview = self.service.configuration_settings_preview(
            {
                "changes": changes,
                "expectedRuntimeRevision": initial["runtimeConfig"]["runtimeRevision"],
            }
        )
        applied = self.service.configuration_settings_apply(
            {
                "changes": changes,
                "expectedRuntimeRevision": preview["expectedRevision"]["runtimeRevision"],
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "confirmText": "apply",
            }
        )

        provider_path = Path(self.tmp.name) / "voice-provider.json"
        hotkey_path = Path(self.tmp.name) / "voice-hotkey.json"
        provider_payload = json.loads(provider_path.read_text(encoding="utf-8"))
        hotkey_payload = json.loads(hotkey_path.read_text(encoding="utf-8"))
        current = self.service.settings()

        self.assertTrue(applied["ok"])
        self.assertEqual(
            set(applied["rollbackAuthority"]["settingKeys"]),
            {"voice.provider", "voice.hotkey"},
        )
        self.assertEqual(provider_payload["provider"], "realtime_websocket")
        self.assertEqual(hotkey_payload["choice"], "option_space")
        self.assertEqual(provider_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hotkey_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(current["settings"]["voice"]["provider"], "realtime_websocket")
        self.assertEqual(current["settings"]["voice"]["hotkey"], "option_space")
        self.assertEqual(current["voiceControl"]["provider"], "realtime_websocket")
        self.assertEqual(current["voiceControl"]["hotkey"], "option_space")

        rolled_back = self.service.configuration_settings_rollback(
            {
                "receiptId": applied["receiptId"],
                "rollbackToken": applied["rollbackToken"],
                "payloadSha256": applied["payloadSha256"],
                "confirmText": "rollback",
            }
        )
        restored_provider = json.loads(provider_path.read_text(encoding="utf-8"))
        restored_hotkey = json.loads(hotkey_path.read_text(encoding="utf-8"))

        self.assertTrue(rolled_back["ok"])
        self.assertEqual(restored_provider["provider"], "native_streaming")
        self.assertEqual(restored_hotkey["choice"], "middle_mouse")


if __name__ == "__main__":
    unittest.main()
