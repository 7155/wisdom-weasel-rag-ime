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
    def test_detects_terminal_plan_with_unapproved_gate_as_a_contradiction(
        self,
    ) -> None:
        contradictory = "\n".join(
            (
                "<workflow-state>",
                "当前任务：完成验收",
                "计划：全部完成",
                "行动状态：计划尚未获得用户批准，不得执行写操作。",
                "</workflow-state>",
            )
        )
        consistent = contradictory.replace(
            "计划尚未获得用户批准，不得执行写操作。",
            "当前计划已经完成；开始新任务前请创建并审批新计划。",
        )

        self.assertEqual(
            AUDIT._workflow_control_contradictions([consistent]),
            [],
        )
        self.assertEqual(
            AUDIT._workflow_control_contradictions([contradictory]),
            [
                {
                    "promptIndex": 1,
                    "blockIndex": 1,
                    "planStatus": "completed",
                    "contradictoryMarker": "计划尚未获得用户批准",
                }
            ],
        )

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
                    "<workflow-state>workflow</workflow-state>",
                    '<rag-ime-context type="room_context">task</rag-ime-context>',
                    '<rag-ime-context type="session_memory">memory</rag-ime-context>',
                )
            )
            read_details = {
                "offset": 0,
                "offsetUnit": "utf8_bytes",
                "byteSize": 4,
                "requestedLimitBytes": 65536,
                "contentLimitBytes": 51200,
                "lineLimit": 2000,
                "modelResultLimitBytes": 51200,
                "content": "work",
                "contentChars": 4,
                "contentBytes": 4,
                "contentLines": 1,
                "truncated": False,
                "truncatedBy": None,
                "modelResultBounded": False,
                "nextOffset": 4,
            }
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
                                    "payload": {
                                        "input": [
                                            {
                                                "role": "developer",
                                                "content": prompt,
                                            },
                                            {
                                                "role": "user",
                                                "content": "work",
                                            },
                                        ],
                                        "tools": [{"name": "tool_search"}],
                                    },
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
                    "toolExecutions": [
                        {
                            "toolCallId": "read-1",
                            "toolName": "workspace_read",
                            "args": {
                                "path": "requirements.md",
                                "offset": 0,
                                "limit": 65536,
                            },
                            "status": "completed",
                            "isError": False,
                            "startedAtMs": 1,
                            "endedAtMs": 2,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps(
                                            read_details,
                                            ensure_ascii=False,
                                            separators=(",", ":"),
                                        ),
                                    }
                                ],
                                "details": read_details,
                            },
                        }
                    ],
                    "toolBatches": [],
                },
            )
            ordinary_prompt = "\n".join(
                (
                    "base",
                    "<workflow-state>workflow</workflow-state>",
                    '<rag-ime-context type="session_memory">memory</rag-ime-context>',
                )
            )
            _write_json(
                state
                / "context-inspection"
                / "agent-1"
                / "2-turn-after-room.json",
                {
                    "schemaVersion": "rag-ime.context-inspection.v2",
                    "sessionId": "agent-1",
                    "turnId": "turn-after-room",
                    "capturedAtMs": 2,
                    "modelCalls": [
                        {
                            "index": 1,
                            "capturedAtMs": 2,
                            "completedAtMs": 3,
                            "providerContext": {
                                "systemPrompt": ordinary_prompt,
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": "continue after Room",
                                    }
                                ],
                                "tools": [{"name": "tool_search"}],
                            },
                            "contextDelta": {"addedMessageCount": 1},
                            "assistantMessage": {
                                "role": "assistant",
                                "usage": {
                                    "input": 6,
                                    "output": 2,
                                    "cacheRead": 4,
                                },
                            },
                            "providerExchanges": [
                                {
                                    "index": 1,
                                    "status": 200,
                                    "payload": {
                                        "input": [
                                            {
                                                "role": "developer",
                                                "content": ordinary_prompt,
                                            },
                                            {
                                                "role": "user",
                                                "content": "continue after Room",
                                            },
                                        ],
                                        "tools": [{"name": "tool_search"}],
                                    },
                                }
                            ],
                        }
                    ],
                    "providerRequestReceipts": [
                        {"index": 1, "model": {"id": "gpt-test"}}
                    ],
                    "cacheEvidence": [
                        {"requestIndex": 1, "cacheReadTokens": 4}
                    ],
                    "toolExecutions": [],
                    "toolBatches": [],
                },
            )
            _write_json(
                state
                / "context-inspection"
                / "agent-1"
                / "3-compaction.json",
                {
                    "schemaVersion": "rag-ime.context-inspection.v2",
                    "sessionId": "agent-1",
                    "turnId": "lifecycle:compaction:1",
                    "capturedAtMs": 3,
                    "lifecycle": {
                        "kind": "compaction",
                        "status": "completed",
                        "reason": "manual",
                    },
                    "modelCalls": [],
                    "providerRequestReceipts": [],
                    "cacheEvidence": [],
                    "toolExecutions": [],
                    "toolBatches": [],
                },
            )
            network_path = state / "external-network-audit.jsonl"
            network_path.parent.mkdir(parents=True, exist_ok=True)
            network_path.write_text(
                "".join(
                    json.dumps(
                        {
                            "host": "provider.example",
                            "pathname": "/v1/responses",
                            "status": 200,
                            "startedAtMs": index,
                            "completedAtMs": index + 10,
                        }
                    )
                    + "\n"
                    for index in (1, 2)
                ),
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
            checks = {"completeRoomScenario": True}
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
                    "schemaVersion": "wisdom-weasel.room-three-member-canary.v2",
                    "checks": checks,
                    "promptChecks": {
                        "progressiveDiscovery": True,
                        "providerPrefixStable": True,
                    },
                    "transcriptIsolation": {"passed": True},
                    "sessionContinuity": {
                        "accepted": {"turnId": "turn-after-room"}
                    },
                    "compaction": {
                        "A": {
                            "passed": True,
                            "after": {
                                "currentProviderContext": {
                                    "systemPrompt": recovery_prompt
                                }
                            },
                        }
                    },
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
            self.assertEqual(result["providerCallCount"], 2)
            self.assertEqual(result["turnCount"], 3)
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
            self.assertEqual(
                exact_call["contextViews"]["providerContext"],
                "normalized effective context",
            )
            self.assertTrue(result["checks"]["exactWirePayloadsCaptured"])
            self.assertTrue(result["checks"]["normalizedPromptMatchesWire"])
            self.assertTrue(
                result["checks"]["effectiveToolSetMatchesWireDisclosure"]
            )
            self.assertEqual(result["toolExecutionCount"], 1)
            self.assertTrue(result["checks"]["workspaceReadResultsBounded"])
            self.assertEqual(
                json.loads(
                    (
                        output
                        / "objects"
                        / "turn-01-call-001"
                        / "messages.json"
                    ).read_text()
                ),
                [{"role": "user", "content": "work"}],
            )
            object_summary = json.loads(
                (
                    output
                    / "objects"
                    / "turn-01-call-001"
                    / "summary.json"
                ).read_text()
            )
            self.assertEqual(object_summary["messagesContentUtf8Bytes"], 4)
            self.assertEqual(
                object_summary["messagesJsonBytes"],
                AUDIT._json_bytes([{"role": "user", "content": "work"}]),
            )
            self.assertEqual(
                object_summary["toolsJsonBytes"],
                AUDIT._json_bytes([{"name": "tool_search"}]),
            )
            self.assertIn(
                "Message content B",
                (output / "README.md").read_text(),
            )
            tool_receipt = json.loads(
                (
                    output
                    / "tool-executions"
                    / "turn-01-execution-001-workspace_read.json"
                ).read_text()
            )
            self.assertEqual(
                tool_receipt["summary"]["workspaceRead"]["nextOffset"],
                4,
            )
            self.assertNotIn("private", (output / "README.md").read_text())

    def test_wire_tool_names_merge_top_level_and_tool_search_outputs(self) -> None:
        call = {
            "providerExchanges": [
                {
                    "payload": {
                        "input": [
                            {
                                "type": "tool_search_output",
                                "tools": [
                                    {"name": "workspace_read"},
                                    {"name": "room_post"},
                                ],
                            }
                        ],
                        "tools": [
                            {"name": "tool_search"},
                            {"name": "workspace_read"},
                        ],
                    }
                }
            ]
        }

        self.assertEqual(
            AUDIT._wire_tool_names(call),
            ["tool_search", "workspace_read", "room_post"],
        )

    def test_chat_completions_wire_prompt_and_function_tools(self) -> None:
        call = {
            "providerExchanges": [
                {
                    "payload": {
                        "messages": [
                            {"role": "system", "content": "room prompt"},
                            {"role": "user", "content": "work"},
                        ],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "tool_search",
                                    "parameters": {"type": "object"},
                                },
                            },
                            {
                                "type": "function",
                                "function": {
                                    "name": "workspace_read",
                                    "parameters": {"type": "object"},
                                },
                            },
                        ],
                    }
                }
            ]
        }

        self.assertEqual(AUDIT._wire_system_prompt(call), "room prompt")
        self.assertEqual(
            AUDIT._wire_tool_names(call),
            ["tool_search", "workspace_read"],
        )

    def test_skill_load_keeps_prompt_bytes_and_restores_exact_body_next_epoch(
        self,
    ) -> None:
        prompt = "稳定前缀\n用户原始字节"
        loaded = (
            '<loaded_skill name="quality-gate" revision="sha256:abc">\n'
            "exact body\n"
            "</loaded_skill>"
        )
        calls = [
            (
                1,
                1,
                {
                    "index": 1,
                    "capturedAtMs": 1,
                    "providerContext": {
                        "systemPrompt": prompt,
                        "messages": [{"role": "user", "content": "work"}],
                    },
                    "assistantMessage": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "id": "load-1",
                                "name": "skill_load",
                                "arguments": {"name": "quality-gate"},
                            }
                        ],
                    },
                },
            ),
            (
                1,
                2,
                {
                    "index": 2,
                    "capturedAtMs": 2,
                    "providerContext": {
                        "systemPrompt": prompt,
                        "messages": [
                            {"role": "user", "content": "work"},
                            {
                                "role": "toolResult",
                                "toolName": "skill_load",
                                "toolCallId": "load-1",
                                "content": [{"type": "text", "text": loaded}],
                            },
                        ],
                    },
                    "assistantMessage": {
                        "role": "assistant",
                        "content": [],
                    },
                },
            ),
        ]

        evidence, append_only, restored = (
            AUDIT._skill_load_context_epoch_evidence(
                calls,
                [f"new epoch prefix\n\n{loaded}"],
            )
        )

        self.assertTrue(append_only)
        self.assertTrue(restored)
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0]["promptBytesUnchanged"])
        self.assertEqual(
            evidence[0]["promptBeforeSha256"],
            evidence[0]["promptAfterSha256"],
        )
        self.assertEqual(
            evidence[0]["recoveryPromptExactOccurrenceCounts"],
            [1],
        )


if __name__ == "__main__":
    unittest.main()
