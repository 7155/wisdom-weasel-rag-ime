from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "run_room_context_epoch_in_process",
    SCRIPTS / "run_room_context_epoch_in_process.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RoomContextEpochInProcessTest(unittest.TestCase):
    def test_report_session_ids_cover_every_collaboration_member(self) -> None:
        report = {
            "members": {
                "A": {"sessionId": "session:a"},
                "B": {"sessionId": "session:b"},
                "C": {"sessionId": "session:c"},
            },
            "sessionId": "legacy:fallback",
        }

        self.assertEqual(
            RUNNER._report_session_ids(report),
            ("session:a", "session:b", "session:c"),
        )

    def test_report_session_ids_reject_missing_identity(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no Session"):
            RUNNER._report_session_ids({})

    def test_compaction_audit_setting_is_explicit_and_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent_dir = Path(directory) / "agent"
            RUNNER._configure_compaction_for_audit(
                agent_dir,
                auto_compaction_enabled=False,
            )

            settings = json.loads(
                (agent_dir / "settings.json").read_text(encoding="utf-8")
            )

        self.assertEqual(settings, {"compaction": {"enabled": False}})

    def test_collaboration_compaction_audit_can_use_a_minimal_keep_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent_dir = Path(directory) / "agent"
            RUNNER._configure_compaction_for_audit(
                agent_dir,
                auto_compaction_enabled=True,
                keep_recent_tokens=(
                    RUNNER.COLLABORATION_COMPACTION_KEEP_RECENT_TOKENS
                ),
            )

            settings = json.loads(
                (agent_dir / "settings.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            settings,
            {
                "compaction": {
                    "enabled": True,
                    "keepRecentTokens": (
                        RUNNER.COLLABORATION_COMPACTION_KEEP_RECENT_TOKENS
                    ),
                }
            },
        )

    def test_external_network_audit_matches_endpoint_without_request_secrets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "requestId": "request-1",
                        "protocol": "https:",
                        "host": "api.example.test",
                        "pathname": "/v1/chat/completions",
                        "method": "POST",
                        "status": 200,
                        "startedAtMs": 100,
                        "completedAtMs": 145,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            evidence = RUNNER._external_network_audit(
                path,
                expected_endpoint="https://api.example.test",
            )

        self.assertEqual(evidence["matchingRequestCount"], 1)
        self.assertEqual(evidence["successfulMatchingRequestCount"], 1)
        self.assertEqual(evidence["failedMatchingRequestCount"], 0)
        self.assertTrue(evidence["allMatchingRequestsSucceeded"])
        self.assertTrue(evidence["terminalMatchingRequestSucceeded"])
        self.assertFalse(evidence["recoveredAfterFailure"])
        self.assertEqual(evidence["requests"][0]["durationMs"], 45)
        serialized = json.dumps(evidence)
        self.assertNotIn("authorization", serialized.lower())
        self.assertNotIn("api_key", serialized.lower())

    def test_external_network_audit_rejects_another_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "requestId": "request-1",
                        "protocol": "https:",
                        "host": "other.example.test",
                        "pathname": "/v1/chat/completions",
                        "method": "POST",
                        "status": 200,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            evidence = RUNNER._external_network_audit(
                path,
                expected_endpoint="https://api.example.test",
            )

        self.assertEqual(evidence["matchingRequestCount"], 0)
        self.assertFalse(evidence["allMatchingRequestsSucceeded"])
        self.assertFalse(evidence["terminalMatchingRequestSucceeded"])

    def test_openai_codex_network_audit_uses_chatgpt_backend(self) -> None:
        runtime = RUNNER.PiRuntimeConfig(
            enabled=True,
            executable=None,
            agent_dir=Path("/tmp/agent"),
            session_dir=Path("/tmp/sessions"),
            logs_dir=Path("/tmp/logs"),
            provider="openai-codex",
            model="gpt-5.6-luna",
        )

        self.assertEqual(
            RUNNER._provider_endpoint(runtime),
            "https://chatgpt.com",
        )

    def test_configured_model_validation_accepts_builtin_catalogs(self) -> None:
        runtime = RUNNER.PiRuntimeConfig(
            enabled=True,
            executable=None,
            agent_dir=Path("/tmp/agent"),
            session_dir=Path("/tmp/sessions"),
            logs_dir=Path("/tmp/logs"),
            provider="deepseek",
            model="deepseek-v4-flash",
            model_providers={
                "deepseek": {
                    "baseUrl": "https://api.example.test",
                    "apiKey": "$DEEPSEEK_API_KEY",
                },
                "gpt": {
                    "baseUrl": "https://gateway.example.test",
                    "apiKey": "$RAG_IME_PI_GPT_API_KEY",
                    "models": [{"id": "gpt-5.6-luna"}],
                },
            },
        )

        self.assertTrue(
            RUNNER._configured_model_available(
                runtime,
                provider="deepseek",
                model="deepseek-v4-flash",
            )
        )
        self.assertTrue(
            RUNNER._configured_model_available(
                runtime,
                provider="gpt",
                model="gpt-5.6-luna",
            )
        )
        self.assertFalse(
            RUNNER._configured_model_available(
                runtime,
                provider="gpt",
                model="gpt-5.6-sol",
            )
        )
        self.assertFalse(
            RUNNER._configured_model_available(
                runtime,
                provider="missing",
                model="any",
            )
        )

    def test_external_network_audit_keeps_transient_failure_and_recovery_visible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.jsonl"
            entries = [
                {
                    "requestId": "request-1",
                    "protocol": "https:",
                    "host": "api.example.test",
                    "pathname": "/v1/responses",
                    "method": "POST",
                    "status": 502,
                },
                {
                    "requestId": "request-2",
                    "protocol": "https:",
                    "host": "api.example.test",
                    "pathname": "/v1/responses",
                    "method": "POST",
                    "status": 200,
                },
            ]
            path.write_text(
                "".join(json.dumps(entry) + "\n" for entry in entries),
                encoding="utf-8",
            )

            evidence = RUNNER._external_network_audit(
                path,
                expected_endpoint="https://api.example.test",
            )

        self.assertEqual(evidence["successfulMatchingRequestCount"], 1)
        self.assertEqual(evidence["failedMatchingRequestCount"], 1)
        self.assertFalse(evidence["allMatchingRequestsSucceeded"])
        self.assertTrue(evidence["terminalMatchingRequestSucceeded"])
        self.assertTrue(evidence["recoveredAfterFailure"])


if __name__ == "__main__":
    unittest.main()
