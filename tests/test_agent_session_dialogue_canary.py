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


def boundary_read_executions(workspace: Path) -> list[dict[str, object]]:
    path = workspace / CANARY.READ_BOUNDARY_PATH
    source = CANARY.READ_BOUNDARY_SOURCE
    path.write_text(source, encoding="utf-8")
    lines = source.splitlines(keepends=True)
    chunks = [
        (
            index + 1,
            index + len(lines[index : index + 1_000]),
            "".join(lines[index : index + 1_000]),
            (
                index + len(lines[index : index + 1_000]) + 1
                if index + 1_000 < len(lines)
                else None
            ),
        )
        for index in range(0, len(lines), 1_000)
    ]
    return [
        {
            "toolName": "read",
            "args": {
                "path": str(path),
                "offset": start_line,
                "limit": 1_000,
            },
            "isError": False,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            content
                            + (
                                f"\n\n[Showing lines {start_line}-{end_line}. "
                                f"Continue with offset={next_line}.]"
                                if next_line is not None
                                else ""
                            )
                        ),
                    }
                ],
                "details": {
                    "content": content,
                    "startLine": start_line,
                    "endLine": end_line,
                    "nextLineOffset": next_line,
                    "size": len(source.encode("utf-8")),
                    "truncated": next_line is not None,
                },
            },
        }
        for start_line, end_line, content, next_line in chunks
    ]


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
                "<agent-profile>伙伴定义</agent-profile>\n"
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
                "activeDeferredMutuallyExclusiveEveryCall": True,
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
                    "read",
                    "代码任务使用真实测试和证据化交付",
                ),
                context("turn:write", "edit", "当前任务继续"),
            ]
        )

        self.assertEqual(
            aggregated["turnIds"],
            ["turn:read", "turn:write"],
        )
        self.assertEqual(aggregated["modelCallCount"], 4)
        self.assertEqual(
            [item["toolName"] for item in aggregated["toolExecutions"]],
            ["read", "edit"],
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

    def test_agent_approval_accepts_exact_native_edit_without_room_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "calculator.py"
            target.write_text(CALCULATOR_BEFORE, encoding="utf-8")
            approval = {
                "approvalId": "approval:1",
                "sessionId": "session:1",
                "state": "pending",
                "toolId": "workspace_edit",
                "payloadSha256": hashlib.sha256(b"approval").hexdigest(),
                "preview": {
                    "actionPayload": {
                        "path": str(target),
                        "resourceRevision": (
                            "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
                        ),
                        "edits": [
                            {
                                "oldText": PATCH_OLD_TEXT,
                                "newText": PATCH_NEW_TEXT,
                            }
                        ],
                    },
                    "baseState": {},
                },
            }

            parsed = CANARY.validate_agent_project_approval(
                approval,
                session_id="session:1",
                workspace=workspace,
            )

            self.assertEqual(parsed["toolId"], "workspace_edit")

    def test_agent_approval_rejects_valid_but_unapproved_edit_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            target = workspace / "calculator.py"
            target.write_text(CALCULATOR_BEFORE, encoding="utf-8")
            approval = {
                "approvalId": "approval:wrong-shape",
                "sessionId": "session:1",
                "state": "pending",
                "toolId": "workspace_edit",
                "payloadSha256": hashlib.sha256(b"wrong-shape").hexdigest(),
                "preview": {
                    "actionPayload": {
                        "path": str(target),
                        "resourceRevision": (
                            "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
                        ),
                        "edits": [
                            {
                                "oldText": PATCH_OLD_TEXT,
                                "newText": (
                                    "    return [value for value in values]"
                                ),
                            }
                        ],
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

    def _valid_native_evidence(
        self,
        workspace: Path,
        *,
        relative_reads: bool = False,
    ) -> dict[str, object]:
        read_path = (
            (lambda name: name)
            if relative_reads
            else (lambda name: str(workspace / name))
        )
        executions = [
            {
                "toolName": "skill_load",
                "args": {"name": CANARY.EXPECTED_SKILL},
                "isError": False,
            },
            {
                "toolName": "read",
                "args": {"path": str(workspace / CANARY.MISSING_READ_PATH)},
                "isError": True,
            },
            {"toolName": "ls", "args": {"path": "."}, "isError": False},
            {
                "toolName": "grep",
                "args": {"path": ".", "pattern": "ROOM_PROJECT_TASK"},
                "isError": False,
            },
            {
                "toolName": "read",
                "args": {"path": read_path("calculator.py")},
                "isError": False,
            },
            {
                "toolName": "read",
                "args": {"path": read_path("test_calculator.py")},
                "isError": False,
            },
            *boundary_read_executions(workspace),
            {
                "toolName": "tool_load",
                "args": {"name": CANARY.EXPECTED_DEFERRED_TOOL},
                "isError": False,
            },
            {"toolName": "bash", "args": {}, "isError": True},
            {"toolName": "edit", "args": {}, "isError": False},
            {"toolName": "bash", "args": {}, "isError": False},
        ]
        return {
            "toolExecutions": executions,
            "activeTools": sorted(CANARY.EXPECTED_TOOLS),
        }

    def test_tool_checks_accept_native_tools_without_discovery_round_trips(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            evidence = self._valid_native_evidence(workspace)

            self.assertTrue(
                all(CANARY._tool_checks(evidence, workspace).values())
            )

    def test_tool_checks_reject_room_calls_and_native_tool_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            evidence = self._valid_native_evidence(workspace)
            executions = evidence["toolExecutions"]
            assert isinstance(executions, list)
            executions.append(
                {"toolName": "room_post", "args": {}, "isError": False}
            )
            self.assertFalse(
                CANARY._tool_checks(
                    evidence, workspace
                )["noRoomOrDelegationCalls"]
            )

            executions.pop()
            executions.append(
                {
                    "toolName": "tool_load",
                    "args": {"name": "read"},
                    "isError": True,
                }
            )
            self.assertFalse(
                CANARY._tool_checks(
                    evidence, workspace
                )["nativeToolsNeverSearchedOrLoaded"]
            )

    def test_tool_checks_accept_relative_native_project_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            evidence = self._valid_native_evidence(
                workspace,
                relative_reads=True,
            )

            self.assertTrue(
                CANARY._tool_checks(
                    evidence, workspace
                )["projectFilesReadWithBoundedVerification"]
            )

    def test_real_canary_prompt_uses_resident_native_tool_contract(self) -> None:
        workspace = Path("/tmp/agent-session-native-tools")
        prompt = CANARY.agent_session_task_message(workspace)

        for name in CANARY.EXPECTED_TOOLS:
            self.assertIn(name, prompt)
        for hidden_name in (
            "workspace_list",
            "workspace_search",
            "workspace_read",
            "workspace_patch",
            "workspace_edit",
            "workspace_shell",
        ):
            self.assertNotIn(hidden_name, prompt)
        self.assertIn("不得把它们交给 tool_search 或 tool_load", prompt)


if __name__ == "__main__":
    unittest.main()
