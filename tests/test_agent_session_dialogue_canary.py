from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "agent_session_dialogue_canary.py"
SPEC = importlib.util.spec_from_file_location("agent_session_dialogue_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)
from room_project_task_canary import (  # noqa: E402
    CALCULATOR_BEFORE,
    PATCH_NEW_TEXT,
    PATCH_OLD_TEXT,
)


class AgentSessionDialogueCanaryTest(unittest.TestCase):
    def test_debug_context_reads_exact_turn_and_model_context_memory(self) -> None:
        paths: list[str] = []

        def requester(
            _base_url: str,
            _method: str,
            path: str,
            _payload: object = None,
            *,
            timeout: float = 0,
        ) -> dict[str, object]:
            del timeout
            paths.append(path)
            prompt = (
                "<agent-role-book>伙伴定义</agent-role-book>\n"
                '<rag-ime-context type="session_memory">'
                "## Session 记忆\n代码任务使用真实测试和证据化交付"
                "</rag-ime-context>"
            )
            return {
                "turnId": "turn:first",
                "context": {
                    "modelCalls": [
                        {
                            "providerContext": {
                                "systemPrompt": prompt,
                                "messages": [],
                                "tools": [],
                            },
                            "contextDelta": {
                                "baseCallIndex": None,
                                "commonPrefixMessages": 0,
                                "removedMessageCount": 0,
                                "addedMessageCount": 0,
                                "prefixBytes": 0,
                                "prefixSha256": "0" * 64,
                                "currentBytes": 2,
                                "deltaBytes": 2,
                                "duplicateBytes": 0,
                            },
                        }
                    ],
                    "providerRequestReceipts": [],
                    "providerRequests": [],
                    "toolExecutions": [],
                },
                "currentProviderContext": {"systemPrompt": prompt},
                "transcript": {},
            }

        evidence = CANARY._debug_context(
            "http://127.0.0.1:8766",
            "session:1",
            requester=requester,
            timeout=5,
            turn_id="turn:first",
        )

        self.assertEqual(
            paths,
            ["/api/agent/sessions/session%3A1/debug-context?turnId=turn%3Afirst"],
        )
        self.assertTrue(evidence["memory"]["usefulProjectPreference"])
        self.assertEqual(len(evidence["memory"]["blocks"]), 1)

    def test_aggregate_debug_contexts_audits_all_task_turns(self) -> None:
        def context(
            turn_id: str,
            tool_name: str,
            memory: str,
        ) -> dict[str, object]:
            governance = {
                "catalogBlocksExactlyOnceEveryCall": True,
                "routingCardFieldContractEveryCall": True,
                "routingCardContentCompleteEveryCall": True,
                "initialProductSchemaNames": [tool_name],
                "loadedProductSchemasBeforeFirstCapture": [tool_name],
                "invalidRoutingCardCount": 0,
                "truncatedRoutingCardValueCount": 0,
            }
            return {
                "turnId": turn_id,
                "model": {"id": "deterministic"},
                "modelCallCount": 2,
                "cacheReads": [],
                "positiveCacheRead": False,
                "providerPrefix": {"passed": True},
                "promptGovernance": governance,
                "progressiveDiscovery": True,
                "systemPromptChecks": {
                    "roleBookExactlyOnce": True,
                    "noRoomAuthority": True,
                },
                "memory": {
                    "blocks": [memory],
                    "usefulProjectPreference": "代码任务" in memory,
                    "forbiddenMetadata": [],
                },
                "toolExecutions": [
                    {
                        "toolName": tool_name,
                        "args": {},
                        "isError": False,
                    }
                ],
                "loadedSkillReceipts": [],
                "activeTools": [tool_name],
                "currentProviderContext": {"turn": turn_id},
                "transcript": {"turn": turn_id},
            }

        aggregated = CANARY._aggregate_debug_contexts(
            [
                context(
                    "turn:read",
                    "workspace_read",
                    "代码任务使用真实测试和证据化交付",
                ),
                context("turn:write", "workspace_patch", "当前任务继续"),
            ]
        )

        self.assertEqual(
            aggregated["turnIds"],
            ["turn:read", "turn:write"],
        )
        self.assertEqual(aggregated["modelCallCount"], 4)
        self.assertEqual(
            [item["toolName"] for item in aggregated["toolExecutions"]],
            ["workspace_read", "workspace_patch"],
        )
        self.assertTrue(aggregated["memory"]["usefulProjectPreference"])
        self.assertTrue(aggregated["providerPrefix"]["passed"])
        self.assertTrue(aggregated["progressiveDiscovery"])

    def test_failed_assistant_is_a_visible_terminal_failure_not_a_timeout(self) -> None:
        snapshot = {
            "items": [
                {
                    "role": "assistant",
                    "status": "failed",
                    "blocks": [
                        {
                            "type": "error",
                            "data": {"message": "Connection error."},
                        }
                    ],
                }
            ]
        }

        self.assertEqual(
            CANARY._assistant_failures(snapshot),
            ["Connection error."],
        )
        self.assertEqual(CANARY._assistant_texts(snapshot), [])

    def test_agent_approval_accepts_exact_project_patch_without_room_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "calculator.py"
            target.write_text(CALCULATOR_BEFORE, encoding="utf-8")
            approval = {
                "approvalId": "approval:1",
                "sessionId": "session:1",
                "state": "pending",
                "toolId": "workspace_patch",
                "payloadSha256": hashlib.sha256(b"approval").hexdigest(),
                "preview": {
                    "actionPayload": {
                        "path": str(target),
                        "oldText": PATCH_OLD_TEXT,
                        "newText": PATCH_NEW_TEXT,
                        "expectedOccurrences": 1,
                    },
                    "baseState": {},
                },
            }

            parsed = CANARY.validate_agent_project_approval(
                approval,
                session_id="session:1",
                workspace=workspace,
            )

            self.assertEqual(parsed["toolId"], "workspace_patch")

    def test_agent_approval_rejects_valid_but_unapproved_patch_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "calculator.py"
            target.write_text(CALCULATOR_BEFORE, encoding="utf-8")
            approval = {
                "approvalId": "approval:wrong-shape",
                "sessionId": "session:1",
                "state": "pending",
                "toolId": "workspace_patch",
                "payloadSha256": hashlib.sha256(b"wrong-shape").hexdigest(),
                "preview": {
                    "actionPayload": {
                        "path": str(target),
                        "oldText": PATCH_OLD_TEXT,
                        "newText": "    return [value for value in values]",
                        "expectedOccurrences": 1,
                    },
                    "baseState": {},
                },
            }

            with self.assertRaises(CANARY.AgentProjectPolicyRejection):
                CANARY.validate_agent_project_approval(
                    approval,
                    session_id="session:1",
                    workspace=workspace,
                )

    def test_tool_checks_reject_room_calls_and_duplicate_missing_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            executions = [
                {"toolName": "skill_load", "args": {"name": CANARY.EXPECTED_SKILL}, "isError": False},
                *[
                    {"toolName": "tool_load", "args": {"name": name}, "isError": False}
                    for name in CANARY.EXPECTED_TOOLS
                ],
                {"toolName": "workspace_read", "args": {"path": str(workspace / CANARY.MISSING_READ_PATH)}, "isError": True},
                {"toolName": "workspace_read", "args": {"path": str(workspace / "calculator.py")}, "isError": False},
                {"toolName": "workspace_read", "args": {"path": str(workspace / "test_calculator.py")}, "isError": False},
                {"toolName": "workspace_list", "args": {"path": "."}, "isError": False},
                {"toolName": "workspace_search", "args": {"path": "."}, "isError": False},
                {"toolName": "workspace_patch", "args": {}, "isError": False},
                {"toolName": "workspace_shell", "args": {}, "isError": True},
                {"toolName": "workspace_shell", "args": {}, "isError": False},
            ]
            evidence = {"toolExecutions": executions}

            self.assertTrue(all(CANARY._tool_checks(evidence, workspace).values()))
            executions.append({"toolName": "room_post", "args": {}, "isError": False})
            self.assertFalse(
                CANARY._tool_checks(evidence, workspace)["noRoomOrDelegationCalls"]
            )

            executions.pop()
            executions.insert(
                -3,
                {"toolName": "workspace_patch", "args": {}, "isError": True},
            )
            self.assertTrue(
                CANARY._tool_checks(evidence, workspace)["patchOnce"]
            )

    def test_tool_checks_accept_relative_project_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            executions = [
                {"toolName": "skill_load", "args": {"name": CANARY.EXPECTED_SKILL}, "isError": False},
                *[
                    {"toolName": "tool_load", "args": {"name": name}, "isError": False}
                    for name in CANARY.EXPECTED_TOOLS
                ],
                {"toolName": "workspace_read", "args": {"path": str(workspace / CANARY.MISSING_READ_PATH)}, "isError": True},
                {"toolName": "workspace_read", "args": {"path": "calculator.py"}, "isError": False},
                {"toolName": "workspace_read", "args": {"path": "test_calculator.py"}, "isError": False},
                {"toolName": "workspace_list", "args": {"path": "."}, "isError": False},
                {"toolName": "workspace_search", "args": {"path": "."}, "isError": False},
                {"toolName": "workspace_patch", "args": {}, "isError": False},
                {"toolName": "workspace_shell", "args": {}, "isError": True},
                {"toolName": "workspace_shell", "args": {}, "isError": False},
            ]

            self.assertTrue(
                CANARY._tool_checks(
                    {"toolExecutions": executions}, workspace
                )["projectFilesReadOnce"]
            )


if __name__ == "__main__":
    unittest.main()
