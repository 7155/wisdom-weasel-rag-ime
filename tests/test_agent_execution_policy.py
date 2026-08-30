from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_execution_policy import (
    APPROVAL_ASK,
    APPROVAL_AUTO,
    APPROVAL_DENY,
    APPROVAL_MODEL,
    FULL_TRUST_EXECUTION_MODE,
    PER_ACTION_EXECUTION_MODE,
    READ_ONLY_EXECUTION_MODE,
    ROOM_UNRESTRICTED_EXECUTION_MODE,
    WORKSPACE_MANAGED_EXECUTION_MODE,
    approval_strategy,
    canonical_tool_profile,
    execution_policy_prompt,
    normalize_execution_mode,
    workspace_scope_is_granted,
    workspace_scope_sha256,
)
from rag_ime.agent_workspace import WorkspaceHarness


class AgentExecutionPolicyTests(unittest.TestCase):
    def test_legacy_profiles_only_translate_at_the_compatibility_boundary(self) -> None:
        self.assertEqual(
            normalize_execution_mode(
                None,
                tool_profile_version="subagent-readonly-v1",
            ),
            READ_ONLY_EXECUTION_MODE,
        )
        self.assertEqual(
            normalize_execution_mode(
                None,
                tool_profile_version="control-center-auto-approve-v1",
            ),
            FULL_TRUST_EXECUTION_MODE,
        )
        self.assertEqual(
            canonical_tool_profile(
                "control-center-auto-approve-v1",
                execution_mode=FULL_TRUST_EXECUTION_MODE,
            ),
            "control-center-v1",
        )

    def test_scope_grant_is_bound_to_the_exact_normalized_root_set(self) -> None:
        roots = ["/workspace/b", "/workspace/a", "/workspace/a"]
        digest = workspace_scope_sha256(roots)
        session = {
            "workspaceRoots": ["/workspace/a", "/workspace/b"],
            "workspaceScopeSha256": digest,
            "workspaceScopeGrantedAtMs": 100,
        }

        self.assertTrue(workspace_scope_is_granted(session))
        self.assertFalse(
            workspace_scope_is_granted(
                {**session, "workspaceRoots": ["/workspace/a", "/workspace/c"]}
            )
        )

    def test_four_modes_have_distinct_runtime_approval_behavior(self) -> None:
        base = {
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": ["/workspace/project"],
            "workspaceScopeSha256": workspace_scope_sha256(
                ["/workspace/project"]
            ),
            "workspaceScopeGrantedAtMs": 100,
        }
        workspace_effects = (
            ("workspace_patch", "apply"),
            ("workspace_shell", "run"),
            ("workspace_lsp", "rename"),
            ("workspace_lsp", "code_action_apply"),
        )

        for tool, operation in workspace_effects:
            self.assertEqual(
                approval_strategy(
                    {**base, "executionMode": READ_ONLY_EXECUTION_MODE},
                    tool=tool,
                    operation=operation,
                ),
                APPROVAL_DENY,
            )
            self.assertEqual(
                approval_strategy(
                    {**base, "executionMode": PER_ACTION_EXECUTION_MODE},
                    tool=tool,
                    operation=operation,
                ),
                APPROVAL_ASK,
            )
            self.assertEqual(
                approval_strategy(
                    {**base, "executionMode": WORKSPACE_MANAGED_EXECUTION_MODE},
                    tool=tool,
                    operation=operation,
                ),
                APPROVAL_AUTO,
            )
            self.assertEqual(
                approval_strategy(
                    {**base, "executionMode": FULL_TRUST_EXECUTION_MODE},
                    tool=tool,
                    operation=operation,
                ),
                APPROVAL_MODEL,
            )

        ungranted = {
            **base,
            "executionMode": WORKSPACE_MANAGED_EXECUTION_MODE,
            "workspaceScopeGrantedAtMs": 0,
        }
        self.assertEqual(
            approval_strategy(
                ungranted,
                tool="workspace_patch",
                operation="apply",
            ),
            APPROVAL_ASK,
        )
        self.assertEqual(
            approval_strategy(
                {**ungranted, "executionMode": FULL_TRUST_EXECUTION_MODE},
                tool="workspace_patch",
                operation="apply",
            ),
            APPROVAL_DENY,
        )
        self.assertEqual(
            approval_strategy(
                {**base, "executionMode": WORKSPACE_MANAGED_EXECUTION_MODE},
                tool="planning",
                operation="task_action",
            ),
            APPROVAL_ASK,
        )
        self.assertEqual(
            approval_strategy(
                {**base, "executionMode": FULL_TRUST_EXECUTION_MODE},
                tool="planning",
                operation="task_action",
            ),
            APPROVAL_MODEL,
        )

    def test_confirmed_room_unrestricted_skips_per_tool_approval_within_fences(self) -> None:
        roots = ["/workspace/project"]
        session = {
            "executionMode": PER_ACTION_EXECUTION_MODE,
            "roomExecutionMode": ROOM_UNRESTRICTED_EXECUTION_MODE,
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": roots,
            "workspaceScopeSha256": workspace_scope_sha256(roots),
            "workspaceScopeGrantedAtMs": 100,
        }

        self.assertEqual(
            approval_strategy(
                session,
                tool="planning",
                operation="task_action",
            ),
            APPROVAL_AUTO,
        )
        self.assertEqual(
            approval_strategy(
                session,
                tool="workspace_patch",
                operation="apply",
            ),
            APPROVAL_AUTO,
        )
        self.assertEqual(
            approval_strategy(
                session,
                tool="runtime",
                operation="restart_sidecar",
            ),
            APPROVAL_ASK,
        )
        self.assertEqual(
            approval_strategy(
                {**session, "workspaceScopeGrantedAtMs": 0},
                tool="workspace_patch",
                operation="apply",
            ),
            APPROVAL_DENY,
        )
        self.assertIn(
            "room_unrestricted",
            execution_policy_prompt(session),
        )

    def test_full_auto_only_skips_review_for_scoped_ordinary_commands(self) -> None:
        roots = ["/workspace/project"]
        session = {
            "executionMode": FULL_TRUST_EXECUTION_MODE,
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": roots,
            "workspaceScopeSha256": workspace_scope_sha256(roots),
            "workspaceScopeGrantedAtMs": 100,
        }
        base_state = {
            "workspaceRootsSha256": "f" * 64,
            "workspaceScopeSha256": session["workspaceScopeSha256"],
        }
        self.assertEqual(
            approval_strategy(
                session,
                tool="workspace_shell",
                operation="run",
                preview={
                    "actionPayload": {
                        "command": "printf 'ok'",
                        "cwd": "/workspace/project",
                        "allowNetwork": False,
                    },
                    "baseState": base_state,
                },
                risk_level="R2",
            ),
            APPROVAL_AUTO,
        )
        with tempfile.TemporaryDirectory(prefix="paw-background-policy-") as directory:
            root = Path(directory).resolve()
            job_roots = [str(root)]
            job_session = {
                **session,
                "mode": "coordinator",
                "workspaceRoots": job_roots,
                "workspaceScopeSha256": workspace_scope_sha256(job_roots),
            }
            harness = WorkspaceHarness(executor=lambda _prepared: {})
            prepared_job = harness.prepare_background_command(
                job_session,
                {
                    "command": "python3 -m http.server 4187 -d dist",
                    "cwd": str(root),
                    "allowNetwork": False,
                },
            )
            self.assertEqual(
                approval_strategy(
                    job_session,
                    tool="workspace_job",
                    operation="start",
                    preview=harness.preview(prepared_job),
                    risk_level="R2",
                ),
                APPROVAL_AUTO,
            )
        for command in (
            "rm -rf /workspace/project/cache",
            "cat /workspace/project/.env",
            "curl https://example.test",
        ):
            self.assertEqual(
                approval_strategy(
                    session,
                    tool="workspace_shell",
                    operation="run",
                    preview={
                        "actionPayload": {
                            "command": command,
                            "cwd": "/workspace/project",
                            "allowNetwork": False,
                        },
                        "baseState": base_state,
                    },
                    risk_level="R2",
                ),
                APPROVAL_MODEL,
            )
        self.assertEqual(
            approval_strategy(
                session,
                tool="workspace_shell",
                operation="run",
                preview={
                    "actionPayload": {
                        "command": "printf 'ok'",
                        "cwd": "/tmp",
                        "allowNetwork": False,
                    },
                    "baseState": base_state,
                },
                risk_level="R2",
            ),
            APPROVAL_MODEL,
        )

    def test_full_auto_skips_model_review_for_scoped_prepared_text_edits(self) -> None:
        roots = ["/workspace/project"]
        session = {
            "executionMode": FULL_TRUST_EXECUTION_MODE,
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": roots,
            "workspaceScopeSha256": workspace_scope_sha256(roots),
            "workspaceScopeGrantedAtMs": 100,
        }
        preview = {
            "actionPayload": {
                "path": "/workspace/project/customer_directory/import_preview.py",
                "edits": [{"oldText": "old", "newText": "new"}],
            },
            "baseState": {
                "workspaceRootSha256": "f" * 64,
                "workspaceScopeSha256": session["workspaceScopeSha256"],
                "preimageSha256": "a" * 64,
                "postimageSha256": "b" * 64,
            },
        }

        self.assertEqual(
            approval_strategy(
                session,
                tool="workspace_edit",
                operation="apply",
                preview=preview,
                risk_level="R2",
            ),
            APPROVAL_AUTO,
        )
        self.assertEqual(
            approval_strategy(
                session,
                tool="workspace_edit",
                operation="apply",
                preview=preview,
                risk_level="R3",
            ),
            APPROVAL_MODEL,
        )
        self.assertEqual(
            approval_strategy(
                session,
                tool="workspace_edit",
                operation="apply",
                preview={
                    **preview,
                    "actionPayload": {
                        **preview["actionPayload"],
                        "path": "/workspace/project/.env",
                    },
                },
                risk_level="R2",
            ),
            APPROVAL_MODEL,
        )

    def test_full_trust_uses_only_the_scoped_prepared_command_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="room-full-trust-commit-") as directory:
            root = Path(directory).resolve()
            roots = [str(root)]
            session = {
                "mode": "coordinator",
                "executionMode": FULL_TRUST_EXECUTION_MODE,
                "toolProfileVersion": "control-center-v1",
                "workspaceRoots": roots,
                "workspaceScopeSha256": workspace_scope_sha256(roots),
                "workspaceScopeGrantedAtMs": 100,
            }
            args = {
                "command": 'git commit -m "room acceptance"',
                "cwd": str(root),
                "allowNetwork": False,
            }

            # Raw model arguments have not crossed the workspace harness and
            # therefore do not contain a server-generated scope/fence preview.
            self.assertEqual(
                approval_strategy(
                    session,
                    tool="workspace_shell",
                    operation="run",
                    preview=args,
                    risk_level="R2",
                ),
                APPROVAL_MODEL,
            )

            prepared = WorkspaceHarness(executor=lambda _prepared: {}).prepare_command(
                session,
                args,
            )
            preview = WorkspaceHarness(executor=lambda _prepared: {}).preview(prepared)

            self.assertEqual(
                approval_strategy(
                    session,
                    tool="workspace_shell",
                    operation="run",
                    preview=preview,
                    risk_level="R2",
                ),
                APPROVAL_AUTO,
            )
            ordinary = {
                **preview,
                "actionPayload": {
                    **preview["actionPayload"],
                    "command": "python3 -m unittest tests.test_customers",
                },
            }
            self.assertEqual(
                approval_strategy(
                    session,
                    tool="workspace_shell",
                    operation="run",
                    preview=ordinary,
                    risk_level="R2",
                ),
                APPROVAL_AUTO,
            )

            for command in (
                "git push origin main",
                'git commit -m "ok" && git push origin main',
                "rm -rf build",
            ):
                unsafe = {
                    **preview,
                    "actionPayload": {
                        **preview["actionPayload"],
                        "command": command,
                    },
                }
                with self.subTest(command=command):
                    self.assertEqual(
                        approval_strategy(
                            session,
                            tool="workspace_shell",
                            operation="run",
                            preview=unsafe,
                            risk_level="R2",
                        ),
                        APPROVAL_MODEL,
                    )

            networked = {
                **preview,
                "actionPayload": {
                    **preview["actionPayload"],
                    "allowNetwork": True,
                },
            }
            self.assertEqual(
                approval_strategy(
                    session,
                    tool="workspace_shell",
                    operation="run",
                    preview=networked,
                    risk_level="R2",
                ),
                APPROVAL_MODEL,
            )
            self.assertEqual(
                approval_strategy(
                    session,
                    tool="workspace_shell",
                    operation="run",
                    preview=preview,
                    risk_level="R3",
                ),
                APPROVAL_MODEL,
            )

            self.assertEqual(
                approval_strategy(
                    {**session, "executionMode": PER_ACTION_EXECUTION_MODE},
                    tool="workspace_shell",
                    operation="run",
                    preview=preview,
                    risk_level="R2",
                ),
                APPROVAL_ASK,
            )

    def test_full_trust_routes_every_approval_gate_to_the_model_arbiter(self) -> None:
        session = {
            "executionMode": FULL_TRUST_EXECUTION_MODE,
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": ["/workspace/project"],
            "workspaceScopeSha256": workspace_scope_sha256(
                ["/workspace/project"]
            ),
            "workspaceScopeGrantedAtMs": 100,
        }
        for tool, operation in (
            ("runtime", "restart_sidecar"),
            ("runtime", "restart_predictor"),
            ("runtime", "redeploy_rime"),
            ("configuration", "restore_apply"),
        ):
            self.assertEqual(
                approval_strategy(
                    session,
                    tool=tool,
                    operation=operation,
                ),
                APPROVAL_MODEL,
            )
        self.assertEqual(
            approval_strategy(
                session,
                tool="desktop_semantic",
                operation="act",
            ),
            APPROVAL_MODEL,
        )

    def test_prompt_describes_the_mode_without_leaking_internal_credentials(self) -> None:
        ungranted = execution_policy_prompt(
            {
                "executionMode": WORKSPACE_MANAGED_EXECUTION_MODE,
                "toolProfileVersion": "control-center-v1",
            }
        )
        roots = ["/workspace/project"]
        granted_session = {
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": roots,
            "workspaceScopeSha256": workspace_scope_sha256(roots),
            "workspaceScopeGrantedAtMs": 100,
        }
        managed = execution_policy_prompt(
            {
                **granted_session,
                "executionMode": WORKSPACE_MANAGED_EXECUTION_MODE,
            }
        )
        trusted_without_scope = execution_policy_prompt(
            {
                "executionMode": FULL_TRUST_EXECUTION_MODE,
                "toolProfileVersion": "control-center-v1",
            }
        )
        trusted = execution_policy_prompt(
            {
                **granted_session,
                "executionMode": FULL_TRUST_EXECUTION_MODE,
            }
        )

        self.assertIn('<execution-mode mode="workspace_managed">', ungranted)
        self.assertIn("工作区范围尚未确认", ungranted)
        self.assertIn("等待一次原生范围批准", ungranted)
        self.assertIn("已批准工作区内", managed)
        self.assertIn("全自动", trusted_without_scope)
        self.assertIn("工作区边界尚未确认", trusted_without_scope)
        self.assertIn("工作区变更会失败关闭", trusted_without_scope)
        self.assertIn("所有原本需要审批的操作都由独立的 Luna Max 模型判定", trusted)
        self.assertIn("不接收本 Agent 的输出或推理", trusted)
        self.assertIn("不要原样重试，也不要转为人工审批", trusted)
        self.assertIn("删库、灾难性破坏和敏感数据外传由代码硬阻止", trusted)
        for prompt in (ungranted, managed, trusted_without_scope, trusted):
            self.assertIn("取消、审计和迟到写入保护", prompt)
            self.assertNotIn("sha256", prompt.lower())
            self.assertNotIn("token", prompt.lower())


if __name__ == "__main__":
    unittest.main()
