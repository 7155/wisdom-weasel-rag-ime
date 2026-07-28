from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "room_project_task_canary.py"
SPEC = importlib.util.spec_from_file_location("room_project_task_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class RoomProjectTaskCanaryTest(unittest.TestCase):
    def test_seeded_project_starts_with_one_exact_implementation_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            receipt = CANARY.seed_project_workspace(workspace)

            calculator = (workspace / "calculator.py").read_text(encoding="utf-8")
            tests = (workspace / "test_calculator.py").read_text(encoding="utf-8")

        self.assertEqual(calculator.count(CANARY.PATCH_OLD_TEXT), 1)
        self.assertIn("normalize_scores([5, 7, 6])", tests)
        self.assertEqual(set(receipt["files"]), {"README.md", "calculator.py", "test_calculator.py"})

    def test_native_approval_allowlist_accepts_the_bounded_implementation_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            edit = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(workspace),
            )
            shell = self._approval(
                workspace,
                tool_id="workspace_shell",
                action={
                    "command": CANARY.TEST_COMMAND,
                    "cwd": str(workspace),
                    "timeoutSeconds": 30,
                    "allowNetwork": False,
                },
            )

            parsed_edit = CANARY.validate_project_approval(
                edit,
                session_id="agent:project",
                workspace=workspace,
            )
            parsed_shell = CANARY.validate_project_approval(
                shell,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed_edit["toolId"], "workspace_edit")
        self.assertEqual(parsed_shell["toolId"], "workspace_shell")

    def test_native_approval_allowlist_accepts_local_identifier_renames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(
                    workspace,
                    new_text=(
                        "    if not values:\n"
                        "        return []\n"
                        "    min_val = min(values)\n"
                        "    return [v - min_val for v in values]"
                    ),
                ),
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_edit")

    def test_native_approval_allowlist_accepts_safe_inline_luna_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(
                    workspace,
                    new_text=(
                        "    return [value - min(values) for value in values] "
                        "if values else []"
                    ),
                ),
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_edit")

    def test_native_approval_allowlist_rejects_inline_side_effects(self) -> None:
        self.assertFalse(
            CANARY._approved_normalize_scores_body(
                "    return [print(value) for value in values] if values else []"
            )
        )

    def test_native_approval_allowlist_accepts_bounded_formatting_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(
                    workspace,
                    old_text=f"{CANARY.PATCH_OLD_TEXT}\n",
                    new_text=(
                        "    if not values:\n"
                        "        return []\n\n"
                        "    minimum = min(values)\n"
                        "    return [value - minimum for value in values]\n"
                    ),
                ),
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_edit")

    def test_native_approval_allowlist_accepts_exact_function_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            old_function = (
                "def normalize_scores(values: list[int]) -> list[int]:\n"
                "    \"\"\"Shift every score so the minimum value becomes zero.\"\"\"\n"
                f"{CANARY.PATCH_OLD_TEXT}\n"
            )
            new_function = (
                "def normalize_scores(values: list[int]) -> list[int]:\n"
                "    \"\"\"Shift every score so the minimum value becomes zero.\"\"\"\n"
                "    if not values:\n"
                "        return []\n\n"
                "    minimum = min(values)\n"
                "    return [value - minimum for value in values]\n"
            )
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(
                    workspace,
                    old_text=old_function,
                    new_text=new_function,
                ),
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_edit")

    def test_native_approval_allowlist_rejects_extra_edit_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(
                    workspace,
                    new_text=(
                        "    print(values)\n"
                        "    minimum = min(values)\n"
                        "    return [value - minimum for value in values]"
                    ),
                ),
            )

            with self.assertRaisesRegex(RuntimeError, "approved implementation shape"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                )

    def test_native_approval_allowlist_rejects_malformed_edit_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action={
                    "path": str(workspace / "calculator.py"),
                    "edits": [{"oldText": CANARY.PATCH_OLD_TEXT}],
                },
            )

            with self.assertRaisesRegex(RuntimeError, "approved implementation shape"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                )

    def test_native_approval_allowlist_rejects_extra_action_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            action = self._edit_action(workspace)
            action["unexpected"] = True
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=action,
            )

            with self.assertRaisesRegex(RuntimeError, "approved implementation shape"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                )

    def test_native_approval_allowlist_rejects_multiple_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            one_edit = {
                "oldText": CANARY.PATCH_OLD_TEXT,
                "newText": CANARY.PATCH_NEW_TEXT,
            }
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action={
                    "path": str(workspace / "calculator.py"),
                    "edits": [one_edit, one_edit],
                },
            )

            with self.assertRaisesRegex(RuntimeError, "approved implementation shape"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                )

    def test_native_approval_allowlist_rejects_nonunique_old_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(workspace, old_text="    "),
            )

            with self.assertRaisesRegex(RuntimeError, "approved implementation shape"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                )

    def test_reviewer_approval_allowlist_rejects_every_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(workspace),
            )

            with self.assertRaisesRegex(RuntimeError, "forbidden edit"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                    allow_edit=False,
                )

    def test_native_approval_allowlist_rejects_extra_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_shell",
                action={
                    "command": "git status",
                    "cwd": str(workspace),
                    "timeoutSeconds": 30,
                    "allowNetwork": False,
                },
            )

            with self.assertRaisesRegex(RuntimeError, "unexpected command"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
                )

    def test_native_approval_allowlist_accepts_a_bounded_test_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_shell",
                action={
                    "command": CANARY.TEST_COMMAND,
                    "cwd": str(workspace),
                    "timeoutSeconds": 120,
                    "allowNetwork": False,
                },
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_shell")

    def test_unbound_room_approval_is_not_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_edit",
                action=self._edit_action(workspace),
            )
            approval["preview"]["baseState"].pop(
                "roomInvocationReceiptId"
            )
            requests: list[tuple[str, str]] = []

            def requester(
                _base_url,
                method,
                path,
                _payload=None,
                *,
                timeout=130,
            ):
                _ = timeout
                requests.append((method, path))
                return {"items": [approval]}

            decisions = CANARY.approve_pending_project_actions(
                "http://in-process.invalid",
                requester=requester,
                session_id="agent:project",
                workspace=workspace,
                decided_ids=set(),
            )

        self.assertEqual(decisions, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0], "GET")

    def test_resilience_probe_accepts_one_expected_failed_test_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_shell",
                action={
                    "command": CANARY.TEST_COMMAND,
                    "cwd": str(workspace),
                    "timeoutSeconds": 30,
                    "allowNetwork": False,
                },
            )

            def requester(
                _base_url,
                method,
                _path,
                _payload=None,
                *,
                timeout=130,
            ):
                _ = timeout
                if method == "GET":
                    return {"items": [approval]}
                return {
                    "approval": {
                        **approval,
                        "state": "failed",
                        "receipt": {
                            "mutationApplied": False,
                            "exitCode": 1,
                            "timedOut": False,
                            "roomExecutionReceipt": {"status": "failed"},
                        },
                    },
                    "runtimeNotified": True,
                    "runtimeWarning": "",
                }

            decisions = CANARY.approve_pending_project_actions(
                "http://in-process.invalid",
                requester=requester,
                session_id="agent:project",
                workspace=workspace,
                decided_ids=set(),
                allow_expected_shell_failure=True,
            )

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["state"], "failed")
        self.assertEqual(decisions[0]["exitCode"], 1)
        self.assertFalse(decisions[0]["mutationApplied"])
        self.assertEqual(decisions[0]["roomExecutionStatus"], "failed")

    @staticmethod
    def _edit_action(
        workspace: Path,
        *,
        old_text: str = CANARY.PATCH_OLD_TEXT,
        new_text: str = CANARY.PATCH_NEW_TEXT,
    ) -> dict[str, object]:
        return {
            "path": str(workspace / "calculator.py"),
            "edits": [{"oldText": old_text, "newText": new_text}],
        }

    @staticmethod
    def _approval(
        workspace: Path,
        *,
        tool_id: str,
        action: dict[str, object],
    ) -> dict[str, object]:
        return {
            "approvalId": f"approval:{tool_id}",
            "sessionId": "agent:project",
            "toolId": tool_id,
            "payloadSha256": "a" * 64,
            "state": "pending",
            "preview": {
                "actionPayload": action,
                "baseState": {
                    "roomInvocationReceiptId": f"invoke:{tool_id}",
                    "workspaceRoot": str(workspace),
                },
            },
        }


if __name__ == "__main__":
    unittest.main()
