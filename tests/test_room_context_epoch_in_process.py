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
        self.assertTrue(evidence["allMatchingRequestsSucceeded"])
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


if __name__ == "__main__":
    unittest.main()
