from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_approval_model import ApprovalModelArbiter
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.db import sqlite_connection


class FakeCompletionRuntime:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def complete_once(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(dict(kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return dict(self.response) if isinstance(self.response, dict) else {"text": self.response}


class ApprovalModelArbiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="approval-model-")
        self.db_path = Path(self.temporary.name) / "agent.sqlite3"
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.session = self.sessions.create(
            title="Model arbitration",
            mode="coordinator",
            execution_mode="full_trust",
            workspace_roots=[str(self.workspace)],
            created_at_ms=10,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def approval(self, *, preview: dict[str, object] | None = None) -> dict[str, object]:
        return self.sessions.create_approval(
            session_id=str(self.session["id"]),
            tool_name="workspace_shell",
            operation="run",
            payload_sha256="a" * 64,
            preview=preview or {
                "title": "Run bounded command",
                "summary": "Run printf in the selected workspace",
                "baseState": {"workspaceRootSha256": "b" * 64},
            },
            risk_level="R2",
            requested_at_ms=20,
        )

    def test_luna_max_decision_is_hash_bound_persisted_and_reused(self) -> None:
        runtime = FakeCompletionRuntime(
            {
                "text": json.dumps(
                    {
                        "decision": "approve",
                        "reasonCodes": ["bounded_operation", "authorized_scope"],
                        "rationaleSummary": "操作被限定在已授权工作区。",
                    },
                    ensure_ascii=False,
                )
            }
        )
        ticks = iter((100, 120))
        arbiter = ApprovalModelArbiter(
            self.db_path,
            runtime_provider=lambda: runtime,
            clock_ms=lambda: next(ticks),
        )
        approval = self.approval()

        receipt = arbiter.decide(approval, self.session)
        repeated = arbiter.decide(approval, self.session)

        self.assertEqual(receipt, repeated)
        self.assertEqual(receipt["decision"], "approve")
        self.assertEqual(receipt["status"], "decided")
        self.assertEqual(receipt["modelProfile"], "openai-codex/gpt-5.6-luna")
        self.assertEqual(receipt["thinkingLevel"], "max")
        self.assertEqual(receipt["payloadSha256"], "a" * 64)
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual(request["provider"], "openai-codex")
        self.assertEqual(request["model_id"], "gpt-5.6-luna")
        self.assertEqual(request["thinking_level"], "max")
        with self.assertRaises(sqlite3.IntegrityError):
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    "UPDATE agent_approval_model_decisions SET decision = 'deny' WHERE approval_id = ?",
                    (approval["approvalId"],),
                )

    def test_invalid_or_unavailable_model_fails_closed_without_leaking_secrets(self) -> None:
        runtime = FakeCompletionRuntime(
            {
                "text": json.dumps(
                    {
                        "decision": "approve",
                        "reasonCodes": ["bounded_operation"],
                        "rationaleSummary": "ok",
                        "unexpected": True,
                    }
                )
            }
        )
        arbiter = ApprovalModelArbiter(
            self.db_path,
            runtime_provider=lambda: runtime,
            clock_ms=lambda: 200,
        )
        approval = self.approval(
            preview={
                "title": "Untrusted preview",
                "token": "sk-this-must-not-leak",
                "changes": [
                    {
                        "label": "command",
                        "after": "rm -rf .env",
                    }
                ],
            }
        )

        receipt = arbiter.decide(approval, self.session)

        self.assertEqual(receipt["decision"], "deny")
        self.assertEqual(receipt["status"], "failed_closed")
        self.assertEqual(receipt["reasonCodes"], ["model_invalid_response"])
        prompt = str(runtime.requests[0]["message"])
        self.assertNotIn("sk-this-must-not-leak", prompt)
        self.assertIn("destructive_effect", prompt)
        self.assertIn("sensitive_target", prompt)

    def test_room_history_is_shared_across_sessions_and_excludes_agent_output(self) -> None:
        runtime = FakeCompletionRuntime(
            {
                "text": json.dumps(
                    {
                        "decision": "approve",
                        "reasonCodes": ["bounded_operation"],
                        "rationaleSummary": "当前任务允许该受限操作。",
                    },
                    ensure_ascii=False,
                )
            }
        )
        second_session = self.sessions.create(
            title="Second room participant",
            mode="coordinator",
            execution_mode="full_trust",
            workspace_roots=[str(self.workspace)],
            created_at_ms=11,
        )
        second_approval = self.sessions.create_approval(
            session_id=str(second_session["id"]),
            tool_name="workspace_shell",
            operation="run",
            payload_sha256="b" * 64,
            preview={
                "title": "Second bounded command",
                "summary": "Run another bounded command",
                "baseState": {"workspaceRootSha256": "b" * 64},
            },
            risk_level="R2",
            requested_at_ms=21,
        )

        def room_context(
            approval: dict[str, object],
            session: dict[str, object],
        ) -> dict[str, object]:
            return {
                "contextKind": "room",
                "contextId": "room-shared",
                "userRequests": [
                    {
                        "role": "user",
                        "text": "Only update the bounded workspace.",
                        "createdAtMs": 9,
                    }
                ],
                "currentTask": {
                    "kind": "room_task",
                    "taskId": "task-1",
                    "objective": "Apply the bounded change",
                },
                "actor": {"sessionId": session["id"]},
                "primaryAgentOutput": "PRIMARY_AGENT_MUST_NOT_REACH_ARBITER",
            }

        arbiter = ApprovalModelArbiter(
            self.db_path,
            runtime_provider=lambda: runtime,
            context_provider=room_context,
            clock_ms=lambda: 300 + len(runtime.requests),
        )
        first_approval = self.approval()

        first = arbiter.decide(first_approval, self.session)
        second = arbiter.decide(second_approval, second_session)

        self.assertEqual(first["contextKind"], "room")
        self.assertEqual(first["contextId"], "room-shared")
        self.assertEqual(first["historyEntryCount"], 0)
        self.assertEqual(second["historyEntryCount"], 1)
        second_prompt = str(runtime.requests[1]["message"])
        self.assertNotIn("PRIMARY_AGENT_MUST_NOT_REACH_ARBITER", second_prompt)
        model_input = json.loads(
            second_prompt.split("UNTRUSTED_APPROVAL_EVIDENCE_JSON:\n", 1)[1]
        )
        self.assertEqual(
            model_input["approvalContext"]["userRequests"][0]["text"],
            "Only update the bounded workspace.",
        )
        self.assertEqual(
            model_input["approvalContext"]["currentTask"]["taskId"],
            "task-1",
        )
        self.assertEqual(
            model_input["decisionHistory"][0]["approvalId"],
            first_approval["approvalId"],
        )
        self.assertEqual(
            model_input["decisionHistory"][0]["decision"],
            "approve",
        )

    def test_missing_authoritative_context_fails_closed_before_model_call(self) -> None:
        runtime = FakeCompletionRuntime({"text": "{}"})
        arbiter = ApprovalModelArbiter(
            self.db_path,
            runtime_provider=lambda: runtime,
            context_provider=lambda approval, session: {
                "contextAvailable": False,
                "contextKind": "session",
                "contextId": session["id"],
            },
            clock_ms=lambda: 400,
        )

        receipt = arbiter.decide(self.approval(), self.session)

        self.assertEqual(receipt["decision"], "deny")
        self.assertEqual(receipt["status"], "failed_closed")
        self.assertEqual(
            receipt["failureCode"],
            "APPROVAL_CONTEXT_UNAVAILABLE",
        )
        self.assertEqual(runtime.requests, [])

    def test_pending_full_automation_approval_is_marked_model_owned_and_extended(self) -> None:
        approval = self.approval()

        self.assertEqual(
            approval["preview"]["approvalArbitration"],
            {
                "mode": "model",
                "status": "running",
                "modelProfile": "openai-codex/gpt-5.6-luna",
                "thinkingLevel": "max",
                "promptVersion": "approval-arbiter-v2",
            },
        )
        self.assertEqual(approval["expiresAtMs"], 180_020)


if __name__ == "__main__":
    unittest.main()
