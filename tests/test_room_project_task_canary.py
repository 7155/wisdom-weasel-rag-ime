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
            patch = self._approval(
                workspace,
                tool_id="workspace_patch",
                action={
                    "path": str(workspace / "calculator.py"),
                    "oldText": CANARY.PATCH_OLD_TEXT,
                    "newText": CANARY.PATCH_NEW_TEXT,
                    "expectedOccurrences": 1,
                },
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

            parsed_patch = CANARY.validate_project_approval(
                patch,
                session_id="agent:project",
                workspace=workspace,
            )
            parsed_shell = CANARY.validate_project_approval(
                shell,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed_patch["toolId"], "workspace_patch")
        self.assertEqual(parsed_shell["toolId"], "workspace_shell")

    def test_native_approval_allowlist_accepts_local_identifier_renames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_patch",
                action={
                    "path": str(workspace / "calculator.py"),
                    "oldText": CANARY.PATCH_OLD_TEXT,
                    "newText": (
                        "    if not values:\n"
                        "        return []\n"
                        "    min_val = min(values)\n"
                        "    return [v - min_val for v in values]"
                    ),
                    "expectedOccurrences": 1,
                },
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_patch")

    def test_native_approval_allowlist_accepts_bounded_formatting_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_patch",
                action={
                    "path": str(workspace / "calculator.py"),
                    "oldText": f"{CANARY.PATCH_OLD_TEXT}\n",
                    "newText": (
                        "    if not values:\n"
                        "        return []\n\n"
                        "    minimum = min(values)\n"
                        "    return [value - minimum for value in values]\n"
                    ),
                    "expectedOccurrences": 1,
                },
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_patch")

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
                tool_id="workspace_patch",
                action={
                    "path": str(workspace / "calculator.py"),
                    "oldText": old_function,
                    "newText": new_function,
                    "expectedOccurrences": 1,
                },
            )

            parsed = CANARY.validate_project_approval(
                approval,
                session_id="agent:project",
                workspace=workspace,
            )

        self.assertEqual(parsed["toolId"], "workspace_patch")

    def test_native_approval_allowlist_rejects_extra_patch_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            CANARY.seed_project_workspace(workspace)
            approval = self._approval(
                workspace,
                tool_id="workspace_patch",
                action={
                    "path": str(workspace / "calculator.py"),
                    "oldText": CANARY.PATCH_OLD_TEXT,
                    "newText": (
                        "    print(values)\n"
                        "    minimum = min(values)\n"
                        "    return [value - minimum for value in values]"
                    ),
                    "expectedOccurrences": 1,
                },
            )

            with self.assertRaisesRegex(RuntimeError, "approved implementation shape"):
                CANARY.validate_project_approval(
                    approval,
                    session_id="agent:project",
                    workspace=workspace,
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
                tool_id="workspace_patch",
                action={
                    "path": str(workspace / "calculator.py"),
                    "oldText": CANARY.PATCH_OLD_TEXT,
                    "newText": CANARY.PATCH_NEW_TEXT,
                    "expectedOccurrences": 1,
                },
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
