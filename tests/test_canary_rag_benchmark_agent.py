from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_ime.pi_runtime import PiRuntimeConfig
from rag_ime.rag_benchmark_agent import RagBenchmarkAgentGateway
from rag_ime.rag_benchmark_sandbox import RagBenchmarkSandbox, RagBenchmarkSandboxTool

from scripts.canary_rag_benchmark_agent import (
    CANARY_VALIDATION_SUITE_ID,
    CANARY_VALIDATION_SUITES,
    REQUIRED_OPERATIONS,
    _canary_prompt,
    _isolated_runtime_config,
    _last_assistant_text,
    _public_tool_diagnostics,
    _start_rag_benchmark_gateway,
    _terminal_failure,
)


class RagBenchmarkAgentCanaryTests(unittest.TestCase):
    def test_isolated_runtime_does_not_reinject_a_bundled_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-canary-runtime-") as temporary:
            root = Path(temporary)
            runtime = root / "runtime-host" / "cli.mjs"
            extension = root / "runtime-host" / "extension-placeholder.mjs"
            runtime.parent.mkdir(parents=True)
            runtime.write_text("", encoding="utf-8")
            extension.write_text("", encoding="utf-8")
            discovered = PiRuntimeConfig(
                enabled=True,
                executable=runtime,
                extension_path=extension,
                agent_dir=root / "source-agent",
                session_dir=root / "source-sessions",
                logs_dir=root / "source-logs",
                node_executable="node",
                provider_environment={"EXISTING_PROVIDER_VALUE": "kept"},
                tools=("agents",),
                pi_version="0.84.2",
                protocol_version="2",
            )
            installation = SimpleNamespace(
                executable=runtime,
                extension_path=extension,
                node_executable="node",
                pi_version="0.84.2",
                protocol_version="2",
                tools=("agents",),
            )

            with (
                patch(
                    "scripts.canary_rag_benchmark_agent.snapshot_managed_pi_runtime",
                    return_value=installation,
                ),
                patch(
                    "scripts.canary_rag_benchmark_agent.PiRuntimeConfig.from_environment",
                    return_value=discovered,
                ),
            ):
                config = _isolated_runtime_config(
                    root / "run",
                    agent_config=root / "run" / "agent" / "config",
                )

        self.assertEqual(
            "kept",
            config.provider_environment["EXISTING_PROVIDER_VALUE"],
        )
        self.assertNotIn("RAG_IME_PI_SKILL_PATHS", config.provider_environment)
        self.assertNotIn(
            "RAG_IME_PI_SKILL_ROUTING_CARDS",
            config.provider_environment,
        )
    def test_canary_requires_blind_validation_before_and_after_rebuild(self) -> None:
        prompt = _canary_prompt(include_skill=True)

        self.assertIn("evaluate_validation", REQUIRED_OPERATIONS)
        self.assertEqual("canary-validation-v1", CANARY_VALIDATION_SUITE_ID)
        self.assertEqual(2, len(CANARY_VALIDATION_SUITES[CANARY_VALIDATION_SUITE_ID]))
        self.assertEqual(2, prompt.count("evaluate_validation"))
        self.assertIn("不得索取 qrels 或逐题结果", prompt)
        self.assertIn("比较两个聚合结果", prompt)
        self.assertIn("北斗项目差旅审批人是林岚", prompt)
        self.assertIn("DELETE_BENCHMARK_RUN", prompt)
        self.assertNotIn('"relevant"', prompt)

    def test_report_uses_only_assistant_text_and_keeps_redacted_terminal_failure(self) -> None:
        events = [
            {
                "eventType": "message_completed",
                "payload": {
                    "message": {
                        "role": "user",
                        "blocks": [
                            {"type": "text", "data": {"text": "林岚只在提示里"}}
                        ],
                    }
                },
            },
            {
                "eventType": "turn_failed",
                "payload": {
                    "error": "provider fetch failed",
                    "category": "provider",
                    "retryable": True,
                    "privateDetail": "must-not-copy",
                },
            },
        ]

        self.assertEqual("", _last_assistant_text(events))
        self.assertEqual(
            {
                "error": "provider fetch failed",
                "category": "provider",
                "retryable": True,
            },
            _terminal_failure(events),
        )

    def test_tool_diagnostics_keep_operation_and_error_without_argument_values(self) -> None:
        events = [
            {
                "eventType": "tool_started",
                "payload": {
                    "toolName": "rag_benchmark",
                    "toolCallId": "private-call-id",
                    "args": {
                        "op": "create_run",
                        "label": "must-not-copy",
                        "apiKey": "must-not-copy",
                    },
                },
            },
            {
                "eventType": "tool_finished",
                "payload": {
                    "toolName": "rag_benchmark",
                    "toolCallId": "private-call-id",
                    "args": {
                        "op": "create_run",
                        "label": "must-not-copy",
                    },
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": "unsupported field: ownerId",
                            }
                        ],
                        "privateDetail": "must-not-copy",
                    },
                    "isError": True,
                },
            },
        ]

        diagnostics = _public_tool_diagnostics(events)

        self.assertEqual(2, len(diagnostics))
        self.assertEqual("create_run", diagnostics[0]["operation"])
        self.assertEqual(["label", "op"], diagnostics[0]["argumentKeys"])
        self.assertNotIn("private-call-id", repr(diagnostics))
        self.assertNotIn("must-not-copy", repr(diagnostics))
        self.assertEqual(
            diagnostics[1]["error"],
            "unsupported field: ownerId",
        )

    def test_gateway_prefers_loopback_and_falls_back_to_private_spool(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-canary-transport-") as temporary:
            root = Path(temporary)
            sandbox = RagBenchmarkSandbox(root / "runs")
            gateway = RagBenchmarkAgentGateway(RagBenchmarkSandboxTool(sandbox))
            self.addCleanup(sandbox.close)

            server = _start_rag_benchmark_gateway(
                gateway,
                spool_dir=root / "spool-loopback",
            )
            self.addCleanup(server.close)
            self.assertIn(
                server.transport,
                {"loopback-http-v1", "private-file-spool-v1"},
            )
            server.close()

            with patch(
                "scripts.canary_rag_benchmark_agent."
                "RagBenchmarkAgentGatewayServer.start",
                side_effect=PermissionError("bind denied"),
            ):
                fallback = _start_rag_benchmark_gateway(
                    gateway,
                    spool_dir=root / "spool-fallback",
                )
            self.addCleanup(fallback.close)
            self.assertEqual("private-file-spool-v1", fallback.transport)


if __name__ == "__main__":
    unittest.main()
