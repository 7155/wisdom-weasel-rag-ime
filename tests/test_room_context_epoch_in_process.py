from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


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
    def test_room_work_policy_override_is_isolated_and_restored(self) -> None:
        canonical = RUNNER.work_policy_prompt()
        replacement = canonical.replace(
            "任务的当前状态与下一步以最新用户消息和本轮动态状态投影为准。",
            "测试变体只服从当前动态状态。",
        )
        original = (
            RUNNER.agent_room_runtime_coordinator.core_agent_policy_prompt
        )
        with tempfile.TemporaryDirectory() as directory:
            policy_file = Path(directory) / "variant-a.txt"
            policy_file.write_text(replacement, encoding="utf-8")
            with RUNNER._room_work_policy_override(
                policy_file,
                variant_label="A",
            ) as evidence:
                rendered = (
                    RUNNER.agent_room_runtime_coordinator
                    .core_agent_policy_prompt(
                        "SAFE",
                        {},
                        managed_work=False,
                    )
                )

        self.assertEqual(evidence["variant"], "A")
        self.assertIn("测试变体只服从当前动态状态", rendered)
        self.assertNotIn("<managed-work>", rendered)
        self.assertIs(
            RUNNER.agent_room_runtime_coordinator.core_agent_policy_prompt,
            original,
        )

    def test_current_room_work_policy_can_be_labeled_without_override(
        self,
    ) -> None:
        original = (
            RUNNER.agent_room_runtime_coordinator.core_agent_policy_prompt
        )
        with RUNNER._room_work_policy_override(
            None,
            variant_label="B",
        ) as evidence:
            self.assertEqual(
                evidence["policySource"],
                "canonical-current",
            )
            self.assertEqual(
                evidence["_replacement"],
                RUNNER.work_policy_prompt(),
            )
        self.assertIs(
            RUNNER.agent_room_runtime_coordinator.core_agent_policy_prompt,
            original,
        )

    def test_room_work_policy_override_rejects_managed_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            policy_file = Path(directory) / "invalid.txt"
            policy_file.write_text(
                "<work-policy><managed-work></managed-work></work-policy>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "one <work-policy>"):
                with RUNNER._room_work_policy_override(
                    policy_file,
                    variant_label="A",
                ):
                    pass

    def test_room_work_policy_prompts_reads_only_provider_prompts(self) -> None:
        report = {
            "epochs": [
                {
                    "beforeCompaction": {
                        "currentProviderContext": {
                            "systemPrompt": "provider prompt"
                        }
                    }
                },
                {"beforeCompaction": {"currentProviderContext": {}}},
            ]
        }

        self.assertEqual(
            RUNNER._room_work_policy_prompts(report),
            ["provider prompt"],
        )

    def test_isolated_shell_rejection_tells_the_model_not_to_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            prepared = SimpleNamespace(
                command="git status --short",
                cwd=workspace,
                roots=(workspace,),
                allow_network=False,
            )

            with self.assertRaisesRegex(RuntimeError, "do not retry"):
                RUNNER._isolated_project_command_executor(
                    prepared,
                    workspace=workspace,
                )

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
        self.assertTrue(
            RUNNER._configured_model_available(
                runtime,
                provider="openai-codex",
                model="gpt-5.6-luna",
            )
        )

    def test_openai_codex_oauth_staging_is_private_and_provider_scoped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_agent_dir = root / "installed-agent"
            target_agent_dir = root / "isolated-agent"
            source_agent_dir.mkdir()
            source = source_agent_dir / "auth.json"
            source.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "codex-access-sentinel",
                            "refresh": "codex-refresh-sentinel",
                            "expires": 123,
                            "accountId": "account-sentinel",
                        },
                        "unrelated-provider": {
                            "type": "api_key",
                            "key": "unrelated-secret-sentinel",
                        },
                    }
                ),
                encoding="utf-8",
            )
            source.chmod(0o600)

            staged = RUNNER._stage_openai_codex_oauth(
                source_agent_dir,
                target_agent_dir,
            )
            staged_payload = json.loads(staged.read_text(encoding="utf-8"))
            staged_text = staged.read_text(encoding="utf-8")

            self.assertEqual(set(staged_payload), {"openai-codex"})
            self.assertEqual(staged_payload["openai-codex"]["type"], "oauth")
            self.assertNotIn("unrelated-secret-sentinel", staged_text)
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target_agent_dir.stat().st_mode), 0o700)

    def test_openai_codex_oauth_staging_rejects_public_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_agent_dir = root / "installed-agent"
            source_agent_dir.mkdir()
            source = source_agent_dir / "auth.json"
            source.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "access",
                            "refresh": "refresh",
                        }
                    }
                ),
                encoding="utf-8",
            )
            source.chmod(0o644)

            with self.assertRaisesRegex(RuntimeError, "private owned file"):
                RUNNER._stage_openai_codex_oauth(
                    source_agent_dir,
                    root / "isolated-agent",
                )

    def test_file_fetch_bridge_survives_late_fetch_install(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "network.jsonl"
            environment = {
                **os.environ,
                "RAG_IME_EXTERNAL_NETWORK_AUDIT_PATH": str(audit_path),
            }
            script = """
const replacement = async () => {
  globalThis.__downstreamCalls = (globalThis.__downstreamCalls || 0) + 1;
  return { status: 204 };
};
globalThis.fetch = replacement;
(async () => {
  const exposedFetch = globalThis.fetch;
  const response = await exposedFetch(
    "https://api.example.test/v1/responses",
    { method: "POST" },
  );
  process.stdout.write(JSON.stringify({
    downstreamCalls: globalThis.__downstreamCalls || 0,
    bridgeStillInstalled: exposedFetch !== replacement,
    status: response.status,
  }));
})().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exitCode = 1;
});
"""
            completed = subprocess.run(
                [
                    node,
                    "--require",
                    str(SCRIPTS / "pi_file_fetch_bridge.cjs"),
                    "-e",
                    script,
                ],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            result = json.loads(completed.stdout)
            audit = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["downstreamCalls"], 1)
        self.assertTrue(result["bridgeStillInstalled"])
        self.assertEqual(result["status"], 204)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["host"], "api.example.test")
        self.assertEqual(audit[0]["pathname"], "/v1/responses")
        self.assertEqual(audit[0]["status"], 204)

    def test_file_fetch_bridge_audits_late_websocket_transport(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "network.jsonl"
            environment = {
                **os.environ,
                "RAG_IME_EXTERNAL_NETWORK_AUDIT_PATH": str(audit_path),
            }
            script = """
class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.listeners = new Map();
    setTimeout(() => this.emit("open", {}), 0);
  }
  addEventListener(name, callback) {
    const values = this.listeners.get(name) || [];
    values.push(callback);
    this.listeners.set(name, values);
  }
  removeEventListener() {}
  emit(name, event) {
    for (const callback of this.listeners.get(name) || []) callback(event);
  }
  close() { this.emit("close", {}); }
}
globalThis.WebSocket = FakeWebSocket;
(async () => {
  const exposed = globalThis.WebSocket;
  const socket = new exposed("wss://chatgpt.com/backend-api/codex/responses");
  await new Promise((resolve) => setTimeout(resolve, 40));
  process.stdout.write(JSON.stringify({
    bridgeStillInstalled: exposed !== FakeWebSocket,
    url: socket.url,
  }));
})().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exitCode = 1;
});
"""
            completed = subprocess.run(
                [
                    node,
                    "--require",
                    str(SCRIPTS / "pi_file_fetch_bridge.cjs"),
                    "-e",
                    script,
                ],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            result = json.loads(completed.stdout)
            audit = [
                json.loads(line)
                for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertTrue(result["bridgeStillInstalled"])
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["transport"], "websocket")
        self.assertEqual(audit[0]["protocol"], "wss:")
        self.assertEqual(audit[0]["host"], "chatgpt.com")
        self.assertEqual(audit[0]["status"], 101)

    def test_external_network_audit_accepts_successful_provider_websocket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.jsonl"
            path.write_text(
                json.dumps({
                    "requestId": "request-ws",
                    "transport": "websocket",
                    "protocol": "wss:",
                    "host": "chatgpt.com",
                    "pathname": "/backend-api/codex/responses",
                    "method": "WEBSOCKET",
                    "status": 101,
                }) + "\n",
                encoding="utf-8",
            )

            evidence = RUNNER._external_network_audit(
                path,
                expected_endpoint="https://chatgpt.com",
            )

        self.assertEqual(evidence["matchingRequestCount"], 1)
        self.assertEqual(evidence["successfulMatchingRequestCount"], 1)
        self.assertTrue(evidence["terminalMatchingRequestSucceeded"])
        self.assertEqual(evidence["requests"][0]["transport"], "websocket")

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
