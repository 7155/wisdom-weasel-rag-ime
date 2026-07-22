from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_room_provider_context_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "render_room_provider_context_audit",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class RenderRoomProviderContextAuditTest(unittest.TestCase):
    def test_renders_exact_context_network_and_transcript_without_credentials(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            state = root / "state"
            context_path = (
                state
                / "context-inspection"
                / "agent-1"
                / "1-turn-1.json"
            )
            prompt = "\n".join(
                (
                    "base",
                    '<rag-ime-context type="workflow_control">workflow</rag-ime-context>',
                    '<rag-ime-context type="room_context">task</rag-ime-context>',
                    '<rag-ime-context type="session_memory">memory</rag-ime-context>',
                )
            )
            _write_json(
                context_path,
                {
                    "schemaVersion": "rag-ime.context-inspection.v2",
                    "sessionId": "agent-1",
                    "turnId": "turn-1",
                    "capturedAtMs": 1,
                    "modelCalls": [
                        {
                            "index": 1,
                            "capturedAtMs": 1,
                            "completedAtMs": 2,
                            "providerContext": {
                                "systemPrompt": prompt,
                                "messages": [{"role": "user", "content": "work"}],
                                "tools": [{"name": "tool_search"}],
                            },
                            "contextDelta": {"addedMessageCount": 1},
                            "assistantMessage": {
                                "role": "assistant",
                                "usage": {"input": 10, "output": 2, "cacheRead": 8},
                            },
                            "providerExchanges": [
                                {
                                    "index": 1,
                                    "status": 200,
                                    "headers": {"x-request-id": "private"},
                                }
                            ],
                        }
                    ],
                    "providerRequestReceipts": [
                        {"index": 1, "model": {"id": "gpt-test"}}
                    ],
                    "cacheEvidence": [
                        {"requestIndex": 1, "cacheReadTokens": 8}
                    ],
                    "toolExecutions": [],
                    "toolBatches": [],
                },
            )
            network_path = state / "external-network-audit.jsonl"
            network_path.parent.mkdir(parents=True, exist_ok=True)
            network_path.write_text(
                json.dumps(
                    {
                        "host": "provider.example",
                        "pathname": "/v1/responses",
                        "status": 200,
                        "startedAtMs": 1,
                        "completedAtMs": 11,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            session_path = (
                state
                / "app-support"
                / "Agent"
                / "sessions"
                / "session.jsonl"
            )
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps({"type": "compaction", "fromHook": True}) + "\n",
                encoding="utf-8",
            )
            checks = {
                "skillToolDiscoveryIsProgressive": True,
                "providerPrefixesStableWithinEpoch": True,
                "roomContextAbsentFromSessionTranscript": True,
            }
            recovery_packet = {
                "originalRequirements": ["original"],
                "currentTask": {"objective": "task"},
                "acceptance": [{"criterionId": "criterion:1"}],
                "blockers": [],
                "handoff": {"intentKind": "complete"},
                "skillReceipt": {
                    "skillId": "room-test",
                    "restoredFromReceiptId": "skill:1",
                },
                "toolReceipt": {
                    "items": [
                        {"name": "workspace_read", "receiptId": "load:1"}
                    ]
                },
            }
            recovery_prompt = (
                "base\n"
                '<rag-ime-context type="room_context">\n'
                + json.dumps(recovery_packet, ensure_ascii=False)
                + "\n</rag-ime-context>"
            )
            report_path = root / "report.json"
            _write_json(
                report_path,
                {
                    "checks": checks,
                    "epochs": [
                        {
                            "index": 1,
                            "afterCompaction": {
                                "currentProviderContext": {
                                    "systemPrompt": recovery_prompt
                                }
                            },
                        }
                    ],
                    "execution": {
                        "state": str(state),
                        "provider": "gpt",
                        "model": "gpt-test",
                        "providerEndpoint": "https://provider.example",
                        "scenario": "context-epoch",
                    },
                },
            )

            output = root / "audit"
            result = AUDIT.render(report_path, output)

            self.assertTrue(all(result["checks"].values()))
            self.assertEqual(result["providerCallCount"], 1)
            self.assertEqual(result["compactionCount"], 1)
            self.assertEqual(
                result["recoveryPromptFiles"],
                ["compaction-01-recovery-prompt.md"],
            )
            self.assertIn("workflow", (output / "room-contexts.md").read_text())
            exact_call = json.loads(
                (output / "calls" / "turn-01-call-001.json").read_text()
            )
            self.assertEqual(
                exact_call["providerContext"]["systemPrompt"],
                prompt,
            )
            self.assertNotIn("headers", exact_call["providerExchanges"][0])
            self.assertNotIn("private", (output / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
