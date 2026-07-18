from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.agent_context_runtime import RUNTIME_PROMPT_ENVELOPE_PREFIX
from rag_ime.agent_service import AgentService, pi_runtime_config_from_settings
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.pi_runtime import PiRuntimeConfig, PiRuntimeError


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _GatewayRuntime:
    runtime_kind = "gateway_http"
    driver_id = "test-gateway"

    def __init__(self, session_root: Path):
        self.session_root = session_root
        self.default_model_profile = "gateway/default"
        self.stopped = False

    def runtime_status(self):
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "managed": True,
            "status": "ready",
            "driverId": self.driver_id,
            "runtimeKind": self.runtime_kind,
            "runtimeVersion": "test-1",
            "piVersion": "",
            "idleTimeoutSeconds": 0,
            "activeSessionId": None,
            "lastError": "",
            "capabilities": {"sessions": True, "modelConfigured": True},
        }

    def stop(self):
        self.stopped = True


class _GatewayRuntimeFactory:
    runtime_kind = "gateway_http"
    driver_id = "test-gateway"
    default_model_profile = "gateway/default"

    def __init__(self, root: Path):
        self.session_root = root / "gateway-sessions"
        self.working_root = root / "gateway-work"
        self.created_for: list[str] = []
        self.runtime: _GatewayRuntime | None = None

    def create(self, _context, *, purpose, session_context_provider=None):
        del session_context_provider
        self.created_for.append(purpose)
        self.runtime = _GatewayRuntime(self.session_root)
        return self.runtime

    def reconfigure(self, _config):
        return None

    def apply_policy(self, _policy):
        return None


class _ForkRuntime:
    def __init__(self, sessions, root: Path, *, fail: bool = False):
        self.sessions = sessions
        self.root = root
        self.fail = fail
        self.target_session_id = ""

    def fork_candidates(self, session_id: str):
        return [
            {
                "entryId": "entry-user-1",
                "text": "保留这个节点",
                "role": "user",
                "createdAtMs": 0,
            }
        ]

    def fork_session(self, source_session_id: str, target_session_id: str, *, entry_id: str):
        self.target_session_id = target_session_id
        if self.fail:
            raise PiRuntimeError("fork failed")
        transcript = self.root / f"{target_session_id.replace(':', '-')}.jsonl"
        transcript.touch()
        session = self.sessions.bind_runtime_session(
            target_session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id="pi-fork-1",
            transcript_ref=str(transcript),
            branch_anchor=entry_id,
            message_count=3,
        )
        return {
            "sourceSessionId": source_session_id,
            "targetSessionId": target_session_id,
            "entryId": entry_id,
            "selectedText": "保留这个节点",
            "session": self.sessions.set_status(target_session_id, "idle"),
        }

    def stop(self):
        return None


class AgentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-service-")
        self.root = Path(self.tmp.name)
        self.process_id = 100
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
            process_id_provider=lambda: self.process_id,
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def test_runtime_and_session_crud_are_typed(self) -> None:
        runtime = self.service.runtime_status()
        self.assertEqual(runtime["schemaVersion"], "rag-ime.agent-runtime.v1")
        self.assertEqual(runtime["status"], "disabled")
        roles = self.service.list_roles()
        self.assertEqual(roles["items"][0]["displayName"], "智鼬·此刻")
        self.assertEqual(
            [item["roleId"] for item in roles["items"]],
            ["zhiyou-v1", "hermes-v1", "vcp-v1"],
        )
        self.assertNotIn("systemPrompt", roles["items"][0])

        created = self.service.create_session({"title": " 连续   对话 "})
        session = created["session"]
        session_id = str(session["id"])
        self.assertEqual(session["title"], "连续 对话")
        self.assertTrue(session["projectContextEnabled"])
        self.assertFalse(session["piSkillsEnabled"])
        self.assertFalse(session["codexSkillsEnabled"])

        listed = self.service.list_sessions()
        self.assertEqual(listed["items"][0]["id"], session_id)
        renamed = self.service.update_session(session_id, {"title": "检索会话"})
        self.assertEqual(renamed["session"]["title"], "检索会话")
        archived = self.service.update_session(session_id, {"archived": True})
        self.assertEqual(archived["session"]["status"], "archived")
        restored = self.service.update_session(session_id, {"archived": False})
        self.assertEqual(restored["session"]["status"], "idle")
        coordinator = self.service.update_session(
            session_id,
            {"mode": "coordinator", "workspaceRoots": [self.root.as_posix()]},
        )
        self.assertEqual(coordinator["session"]["mode"], "coordinator")
        self.assertEqual(coordinator["session"]["shellPolicyVersion"], "coordinator-per-command-v1")
        controlled = self.service.update_session(session_id, {"mode": "assistant"})
        self.assertEqual(controlled["session"]["mode"], "assistant")
        self.assertEqual(controlled["session"]["workspaceRoots"], [])
        restricted = self.service.update_session(
            session_id,
            {
                "mode": "assistant",
                "toolProfileVersion": "subagent-readonly-v1",
                "allowedTools": ["ime_overview", "ime_memory"],
            },
        )["session"]
        self.assertEqual(restricted["toolProfileVersion"], "subagent-readonly-v1")
        self.assertEqual(restricted["toolAllowlistMode"], "explicit")
        self.assertEqual(restricted["allowedTools"], ["ime_overview", "ime_memory"])
        restored_profile = self.service.update_session(
            session_id,
            {
                "mode": "assistant",
                "toolProfileVersion": "control-center-v1",
                "toolAllowlistMode": "profile",
            },
        )["session"]
        self.assertEqual(restored_profile["toolProfileVersion"], "control-center-v1")
        self.assertEqual(restored_profile["toolAllowlistMode"], "profile")
        self.assertEqual(restored_profile["allowedTools"], [])
        context_disabled = self.service.update_session(
            session_id,
            {"mode": "assistant", "projectContextEnabled": False},
        )["session"]
        self.assertFalse(context_disabled["projectContextEnabled"])
        external_skills_enabled = self.service.update_session(
            session_id,
            {
                "mode": "assistant",
                "piSkillsEnabled": True,
                "codexSkillsEnabled": True,
            },
        )["session"]
        self.assertTrue(external_skills_enabled["piSkillsEnabled"])
        self.assertTrue(external_skills_enabled["codexSkillsEnabled"])
        self.assertFalse(external_skills_enabled["projectContextEnabled"])
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            self.service.update_session(
                session_id,
                {"mode": "assistant", "projectContextEnabled": "false"},
            )
        with self.assertRaisesRegex(ValueError, "codexSkillsEnabled must be a boolean"):
            self.service.update_session(
                session_id,
                {"mode": "assistant", "codexSkillsEnabled": "true"},
            )
        with self.assertRaisesRegex(ValueError, "explicit native confirmation"):
            self.service.update_session(
                session_id,
                {
                    "mode": "coordinator",
                    "workspaceRoots": [self.root.as_posix()],
                    "toolProfileVersion": "control-center-auto-approve-v1",
                },
            )
        dangerous = self.service.update_session(
            session_id,
            {
                "mode": "coordinator",
                "workspaceRoots": [self.root.as_posix()],
                "toolProfileVersion": "control-center-auto-approve-v1",
                "dangerousModeConfirmation": "AUTO_APPROVE_ALL",
            },
        )["session"]
        self.assertEqual(dangerous["toolProfileVersion"], "control-center-auto-approve-v1")
        self.service.update_session(
            session_id,
            {
                "mode": "assistant",
                "toolProfileVersion": "control-center-v1",
                "toolAllowlistMode": "profile",
            },
        )
        with self.assertRaisesRegex(ValueError, "unsupported Agent tool allowlist mode"):
            self.service.update_session(
                session_id,
                {"mode": "assistant", "toolAllowlistMode": "unrestricted"},
            )
        with self.assertRaisesRegex(ValueError, "unknown Agent tool"):
            self.service.update_session(
                session_id,
                {"mode": "assistant", "allowedTools": ["untrusted_tool"]},
            )

        deleted = self.service.delete_session(session_id)
        self.assertTrue(deleted["ok"])
        self.assertEqual(self.service.list_sessions()["items"], [])

    def test_delete_stops_a_runtime_that_still_has_the_session_open(self) -> None:
        session = self.service.create_session({"title": "打开中的会话"})["session"]
        session_id = str(session["id"])
        with (
            patch.object(
                self.service,
                "runtime_status",
                return_value={
                    "activeSessionId": None,
                    "openSessionIds": [session_id],
                },
            ),
            patch.object(self.service.runtime, "stop") as stop,
        ):
            deleted = self.service.delete_session(session_id)

        self.assertTrue(deleted["ok"])
        stop.assert_called_once_with()

    def test_dangerous_auto_approval_applies_and_audits_a_hash_bound_preview(self) -> None:
        session = self.service.create_session({"title": "完全信任测试"})["session"]
        session_id = str(session["id"])
        self.service.update_session(
            session_id,
            {
                "mode": "coordinator",
                "workspaceRoots": [self.root.as_posix()],
                "toolProfileVersion": "control-center-auto-approve-v1",
                "dangerousModeConfirmation": "AUTO_APPROVE_ALL",
            },
        )
        approval = self.service.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_planning",
            operation="task_action",
            payload_sha256="a" * 64,
            preview={"title": "测试预览", "summary": "自动批准测试"},
            risk_level="R1",
        )
        self.service.bind_approval_executor(
            lambda decided: {
                "schemaVersion": "rag-ime.agent-operation-receipt.v1",
                "mutationApplied": True,
                "approvalId": decided["approvalId"],
                "toolId": decided["toolId"],
                "operation": decided["operation"],
                "summary": "自动批准已应用",
            }
        )

        result = self.service.auto_approve_pending(approval)

        self.assertTrue(result["autoApproved"])
        self.assertFalse(result["approvalRequired"])
        self.assertEqual(result["approval"]["state"], "applied")
        self.assertIsNotNone(
            self.service.sessions.get_approval(str(approval["approvalId"]))["decidedAtMs"]
        )

    def test_new_session_gets_one_query_free_bootstrap_and_chat_becomes_evidence(self) -> None:
        created = self.service.create_session({"title": "个人上下文"})
        session = created["session"]
        session_id = str(session["id"])

        self.assertTrue(session["roleBookRevisionId"])
        self.assertTrue(created["memoryBootstrap"]["ok"])
        pending = self.service.context_runtime.list_items(session_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["sourceKind"], "memory_bootstrap")

        accepted_values = [
            {
                "accepted": True,
                "turnId": "turn:bootstrap:1",
                "piEntryId": "entry:bootstrap:1",
                "response": {"success": True},
            },
            {
                "accepted": True,
                "turnId": "turn:bootstrap:2",
                "piEntryId": "entry:bootstrap:2",
                "response": {"success": True},
            },
        ]
        with patch.object(
            self.service.runtime,
            "prompt",
            side_effect=accepted_values,
        ) as runtime_prompt:
            first = self.service.prompt(session_id, {"message": "第一轮"})
            second = self.service.prompt(session_id, {"message": "第二轮"})

        self.assertEqual(first["contextItemsDelivered"], 1)
        self.assertEqual(second["contextItemsDelivered"], 0)
        first_runtime_message = runtime_prompt.call_args_list[0].args[1]
        first_envelope = json.loads(
            first_runtime_message.removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX)
        )
        self.assertIn('"queryFree":true', first_envelope["transientContext"])
        self.assertTrue(first["memoryEvidence"]["stored"])
        self.assertTrue(second["memoryEvidence"]["stored"])
        consumed = self.service.context_runtime.list_items(
            session_id,
            status="consumed",
        )
        self.assertEqual(len(consumed), 1)

        self.service.events.publish(
            session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "entry:assistant:1",
                    "sessionId": session_id,
                    "turnId": "turn:bootstrap:2",
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [
                        {
                            "id": "text:assistant:1",
                            "type": "text",
                            "status": "completed",
                            "presentationKind": "markdown",
                            "data": {"text": "这是最终回答"},
                        }
                    ],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 10,
                    "completedAtMs": 11,
                }
            },
            turn_id="turn:bootstrap:2",
        )
        evidence = self.service.memory_evidence.list(
            role_id=str(session["roleId"]),
            session_id=session_id,
        )
        self.assertEqual(
            [item["sourceKind"] for item in evidence],
            ["assistant_message", "user_message", "user_message"],
        )
        self.assertTrue(all(item["maySupportLongTermFact"] is False for item in evidence))

    def test_session_use_repairs_create_time_bootstrap_enqueue_failure(self) -> None:
        with patch.object(
            self.service.memory_bootstrap,
            "build",
            side_effect=RuntimeError("temporary bootstrap failure"),
        ):
            created = self.service.create_session({"title": "可恢复启动上下文"})

        session_id = str(created["session"]["id"])
        self.assertEqual(created["memoryBootstrap"]["status"], "enqueue_failed")
        self.assertEqual(self.service.context_runtime.list_items(session_id), [])

        with self.assertRaises(PiRuntimeError):
            self.service.ensure_runtime({"sessionId": session_id})

        repaired = self.service.context_runtime.list_items(session_id)
        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0]["sourceKind"], "memory_bootstrap")
        self.assertEqual(repaired[0]["status"], "pending")

    def test_new_command_after_lost_runtime_response_does_not_reinject_bootstrap(self) -> None:
        session = self.service.create_session({"title": "响应丢失"})["session"]
        session_id = str(session["id"])
        sent_messages: list[str] = []

        def lose_response(
            _session_id: str,
            message: str,
            **_kwargs: object,
        ) -> dict[str, object]:
            sent_messages.append(message)
            raise RuntimeError("response lost after dispatch")

        with patch.object(self.service.runtime, "prompt", side_effect=lose_response):
            with self.assertRaisesRegex(RuntimeError, "response lost"):
                self.service.prompt(
                    session_id,
                    {
                        "message": "第一轮",
                        "clientMessageId": "client-bootstrap-loss",
                    },
                )

        consumed = self.service.context_runtime.list_items(
            session_id,
            status="consumed",
        )
        self.assertEqual(len(consumed), 1)
        self.assertEqual(
            consumed[0]["deliveredTurnId"],
            "dispatch:client:client-bootstrap-loss",
        )

        with patch.object(
            self.service.runtime,
            "prompt",
            return_value={
                "accepted": True,
                "turnId": "turn:bootstrap:retry",
                "piEntryId": "entry:bootstrap:retry",
                "response": {"success": True},
            },
        ) as retried:
            accepted = self.service.prompt(
                session_id,
                {
                    "message": "第一轮",
                    "clientMessageId": "client-bootstrap-retry",
                },
            )

        first_envelope = json.loads(
            sent_messages[0].removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX)
        )
        self.assertIn('"queryFree":true', first_envelope["transientContext"])
        self.assertNotIn('"queryFree":true', retried.call_args.args[1])
        self.assertEqual(accepted["contextItemsDelivered"], 0)

    def test_corrupt_role_book_falls_back_to_base_persona_without_blocking_chat(self) -> None:
        with patch.object(
            self.service.role_books,
            "ensure_seeded",
            side_effect=ValueError("corrupt role book revision"),
        ):
            created = self.service.create_session({"title": "降级对话"})
            session = created["session"]
            self.assertEqual(session["roleBookRevisionId"], "")
            self.assertFalse(created["roleBook"]["ok"])
            self.assertEqual(
                created["roleBook"]["status"],
                "base_persona_fallback",
            )
            with patch.object(
                self.service.runtime,
                "prompt",
                return_value={
                    "accepted": True,
                    "turnId": "turn:fallback",
                    "piEntryId": "entry:fallback",
                    "response": {"success": True},
                },
            ):
                accepted = self.service.prompt(
                    str(session["id"]),
                    {"message": "继续工作"},
                )
        self.assertTrue(accepted["ok"])
        self.assertEqual(accepted["contextItemsDelivered"], 1)
    def test_conversation_fork_clones_identity_policy_and_returns_new_session(self) -> None:
        source = self.service.create_session(
            {
                "title": "原对话",
                "mode": "assistant",
                "roleId": "hermes-v1",
                "roleVersion": "1",
                "modelProfile": "gpt/test-model",
                "toolProfileVersion": "subagent-readonly-v1",
            }
        )["session"]
        source = self.service.update_session(
            str(source["id"]),
            {
                "mode": "assistant",
                "toolProfileVersion": "subagent-readonly-v1",
                "allowedTools": ["ime_overview", "ime_memory"],
            },
        )["session"]
        runtime = _ForkRuntime(self.service.sessions, self.root)
        self.service.runtime = runtime

        catalog = self.service.fork_candidates(str(source["id"]))
        forked = self.service.fork_session(
            str(source["id"]),
            {"entryId": "entry-user-1", "title": "新路线"},
        )

        self.assertEqual(catalog["items"][0]["entryId"], "entry-user-1")
        target = forked["session"]
        self.assertNotEqual(target["id"], source["id"])
        self.assertEqual(target["title"], "新路线")
        for key in (
            "mode",
            "roleId",
            "roleVersion",
            "modelProfile",
            "toolProfileVersion",
            "toolAllowlistMode",
            "allowedTools",
            "workspaceRoots",
            "shellPolicyVersion",
        ):
            self.assertEqual(target[key], source[key], key)
        self.assertEqual(self.service.sessions.get(str(source["id"])), source)
        self.assertIsNotNone(self.service.sessions.runtime_binding(str(target["id"])))

    def test_failed_conversation_fork_removes_provisional_product_session(self) -> None:
        source = self.service.create_session({"title": "原对话"})["session"]
        runtime = _ForkRuntime(self.service.sessions, self.root, fail=True)
        self.service.runtime = runtime

        with self.assertRaisesRegex(PiRuntimeError, "fork failed"):
            self.service.fork_session(
                str(source["id"]),
                {"entryId": "entry-user-1"},
            )

        self.assertEqual([item["id"] for item in self.service.sessions.list()], [source["id"]])
        self.assertTrue(runtime.target_session_id)

    def test_conversation_fork_is_rejected_before_runtime_when_source_is_not_idle(self) -> None:
        source = self.service.create_session({"title": "正在运行"})["session"]
        self.service.sessions.set_status(str(source["id"]), "busy")
        runtime = _ForkRuntime(self.service.sessions, self.root)
        self.service.runtime = runtime

        with self.assertRaisesRegex(ValueError, "only available for idle"):
            self.service.fork_candidates(str(source["id"]))
        with self.assertRaisesRegex(ValueError, "only available for idle"):
            self.service.fork_session(
                str(source["id"]),
                {"entryId": "entry-user-1"},
            )

        self.assertFalse(runtime.target_session_id)

    def test_conversation_fork_accepts_quiescent_open_session(self) -> None:
        source = self.service.create_session({"title": "已打开但空闲"})["session"]
        session_id = str(source["id"])
        transcript = self.root / "open-idle-source.jsonl"
        transcript.touch()
        self.service.sessions.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id="pi-open-idle-source",
            transcript_ref=str(transcript),
            message_count=1,
        )
        runtime = _ForkRuntime(self.service.sessions, self.root)
        self.service.runtime = runtime

        catalog = self.service.fork_candidates(session_id)

        self.assertEqual(catalog["items"][0]["entryId"], "entry-user-1")

    def test_conversation_rewrite_rewinds_same_session_and_resets_live_projection(self) -> None:
        session = self.service.create_session({"title": "原位修改"})["session"]
        session_id = str(session["id"])
        old_event = self.service.events.publish(
            session_id,
            "message_completed",
            {"message": {"id": "old-branch-message"}},
        )
        with (
            patch.object(
                self.service.runtime,
                "rewind_session",
                return_value={"entryId": "entry-user-1", "leafId": "parent-entry"},
            ) as rewind,
            patch.object(
                self.service.runtime,
                "prompt",
                return_value={
                    "accepted": True,
                    "turnId": "turn:rewrite:1",
                    "piEntryId": "pi-entry:rewrite:1",
                    "response": {"success": True},
                },
            ) as prompt,
        ):
            response = self.service.rewrite_session(
                session_id,
                {
                    "entryId": "entry-user-1",
                    "message": "修改后的问题",
                    "clientMessageId": "rewrite-command-1",
                },
            )

        self.assertEqual(response["schemaVersion"], "rag-ime.agent-session-rewrite.v1")
        self.assertEqual(response["sessionId"], session_id)
        self.assertEqual(response["entryId"], "entry-user-1")
        rewind.assert_called_once_with(session_id, entry_id="entry-user-1")
        self.assertEqual(prompt.call_args.args[0], session_id)
        rewrite_envelope = json.loads(
            prompt.call_args.args[1].removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX)
        )
        self.assertEqual(rewrite_envelope["message"], "修改后的问题")
        replay, gap = self.service.events.replay(session_id)
        self.assertFalse(gap)
        self.assertNotIn(old_event.event_id, [event.event_id for event in replay])
        self.assertEqual(
            [event.payload["message"]["id"] for event in replay if event.event_type == "message_completed"],
            ["pi-entry:rewrite:1"],
        )

        with (
            patch.object(self.service.runtime, "rewind_session") as replay_rewind,
            patch.object(self.service.runtime, "prompt") as replay_prompt,
        ):
            replay_response = self.service.rewrite_session(
                session_id,
                {
                    "entryId": "entry-user-1",
                    "message": "修改后的问题",
                    "clientMessageId": "rewrite-command-1",
                },
            )
        replay_rewind.assert_not_called()
        replay_prompt.assert_not_called()
        self.assertTrue(replay_response["idempotentReplay"])

    def test_kernel_configuration_drives_new_sessions_and_runtime_policy(self) -> None:
        initial = self.service.configuration()["configuration"]
        defaults = self.service.update_configuration(
            {
                "expectedRevision": initial["revision"],
                "changes": {
                    "sessionDefaults.roleId": "hermes-v1",
                    "sessionDefaults.modelProfile": "deepseek/deepseek-chat",
                },
                "updatedBy": "mac-control",
            }
        )
        session = self.service.create_session({"title": "默认角色"})["session"]
        self.assertEqual(session["roleId"], "hermes-v1")
        self.assertEqual(session["modelProfile"], "deepseek/deepseek-chat")

        runtime = self.service.update_configuration(
            {
                "expectedRevision": defaults["configuration"]["revision"],
                "changes": {
                    "runtime.enabled": True,
                    "runtime.idleTimeoutSeconds": 321,
                },
                "updatedBy": "phone-control",
            }
        )
        self.assertTrue(runtime["ok"])
        self.assertEqual(runtime["configuration"]["sync"]["state"], "synchronized")
        self.assertTrue(self.service.runtime_status()["enabled"])
        self.assertEqual(self.service.runtime_status()["idleTimeoutSeconds"], 321)

    def test_service_depends_on_runtime_driver_contract_not_pi_manager(self) -> None:
        factory = _GatewayRuntimeFactory(self.root)
        service = AgentService(
            db_path=self.root / "gateway.sqlite",
            runtime_factory=factory,
        )
        try:
            runtime = service.runtime_status()
            session = service.create_session({"title": "网关会话"})["session"]

            self.assertEqual(runtime["runtimeKind"], "gateway_http")
            self.assertEqual(runtime["driverId"], "test-gateway")
            self.assertEqual(session["modelProfile"], "gateway/default")
            self.assertEqual(factory.created_for, ["interactive"])
        finally:
            service.close()
        self.assertTrue(factory.runtime and factory.runtime.stopped)

    def test_direct_chat_persona_is_immutable_session_metadata(self) -> None:
        created = self.service.create_session(
            {
                "title": "Hermes 任务",
                "mode": "assistant",
                "roleId": "hermes-v1",
                "roleVersion": "1",
            }
        )["session"]

        self.assertEqual(created["roleId"], "hermes-v1")
        self.assertEqual(created["roleVersion"], "1")
        self.assertEqual(created["modelProfile"], "pi/default")
        self.assertEqual(created["toolProfileVersion"], "control-center-v1")
        renamed = self.service.update_session(str(created["id"]), {"title": "推进任务"})["session"]
        self.assertEqual(renamed["roleId"], "hermes-v1")
        self.assertEqual(renamed["roleVersion"], "1")

        coordinator = self.service.create_session(
            {
                "title": "未来协调",
                "mode": "coordinator",
                "roleId": "vcp-v1",
                "roleVersion": "1",
                "workspaceRoots": [self.root.as_posix()],
            }
        )["session"]
        self.assertEqual(coordinator["mode"], "coordinator")
        self.assertEqual(coordinator["workspaceRoots"], [str(self.root.resolve())])

    def test_scheduled_thread_wake_stays_running_until_agent_settles(self) -> None:
        session = self.service.create_session({"title": "定时整理"})["session"]
        wake_at_ms = int(time.time() * 1000) + 2_000
        schedule = self.service.create_wake_schedule(
            {
                "title": "整理今日工作",
                "instruction": "列出完成项并汇报",
                "targetType": "session",
                "targetSessionId": session["id"],
                "wakeAtMs": wake_at_ms,
                "planningTaskId": "task:today",
                "confirmText": "schedule",
            }
        )["schedule"]
        claim = self.service.wake_schedules.claim_due(now_ms=wake_at_ms)[0]

        with patch.object(
            self.service,
            "prompt",
            return_value={"accepted": True, "turnId": "turn:wake"},
        ) as prompt:
            self.service._dispatch_scheduled_wake(claim)

        message = prompt.call_args.args[1]["message"]
        self.assertEqual(message, "预约任务已到期：整理今日工作")
        context_items = self.service.list_context_items(str(session["id"]))["items"]
        self.assertEqual(context_items[0]["sourceKind"], "wake_schedule")
        self.assertEqual(context_items[0]["lane"], "schedule")
        self.assertEqual(
            self.service.get_wake_schedule(str(schedule["id"]))["status"],
            "running",
        )

        self.service.events.publish(
            str(session["id"]),
            "turn_completed",
            {},
            turn_id="turn:wake",
        )
        finished = self.service.get_wake_schedule(str(schedule["id"]))
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["latestRun"]["state"], "completed")

    def test_scheduled_role_wake_creates_visible_persona_session(self) -> None:
        wake_at_ms = int(time.time() * 1000) + 2_000
        schedule = self.service.create_wake_schedule(
            {
                "title": "研究任务",
                "instruction": "核对今天的研究结论",
                "targetType": "role",
                "targetRoleId": "hermes-v1",
                "targetRoleVersion": "1",
                "wakeAtMs": wake_at_ms,
                "confirmText": "schedule",
            }
        )["schedule"]
        claim = self.service.wake_schedules.claim_due(now_ms=wake_at_ms)[0]

        with patch.object(
            self.service,
            "prompt",
            return_value={"accepted": True, "turnId": "turn:role-wake"},
        ) as prompt:
            self.service._dispatch_scheduled_wake(claim)

        created_session_id = prompt.call_args.args[0]
        created = self.service.sessions.get(created_session_id)
        self.assertEqual(created["title"], "预约 · 研究任务")
        self.assertEqual(created["roleId"], "hermes-v1")
        running = self.service.get_wake_schedule(str(schedule["id"]))
        self.assertEqual(running["latestRun"]["sessionId"], created_session_id)

    def test_busy_scheduled_thread_is_deferred_without_consuming_run(self) -> None:
        session = self.service.create_session({"title": "正在执行"})["session"]
        wake_at_ms = int(time.time() * 1000) + 2_000
        schedule = self.service.create_wake_schedule(
            {
                "title": "稍后继续",
                "instruction": "继续现有任务",
                "targetType": "session",
                "targetSessionId": session["id"],
                "wakeAtMs": wake_at_ms,
                "confirmText": "schedule",
            }
        )["schedule"]
        claim = self.service.wake_schedules.claim_due(now_ms=wake_at_ms)[0]
        self.service.sessions.set_status(str(session["id"]), "busy")

        with patch.object(self.service, "prompt") as prompt:
            self.service._dispatch_scheduled_wake(claim)

        prompt.assert_not_called()
        deferred = self.service.get_wake_schedule(str(schedule["id"]))
        self.assertEqual(deferred["status"], "scheduled")
        self.assertEqual(deferred["runCount"], 0)
        self.assertEqual(deferred["latestRun"]["state"], "deferred")

    def test_agent_can_preview_a_wake_for_its_current_thread_without_repeating_id(self) -> None:
        session = self.service.create_session({"title": "当前 Agent"})["session"]

        preview = self.service.preview_wake_schedule(
            {
                "title": "稍后继续",
                "instruction": "继续整理当前结论",
                "targetType": "session",
                "wakeAtMs": int(time.time() * 1000) + 60_000,
            },
            requested_by_session_id=str(session["id"]),
        )

        self.assertEqual(preview["schedule"]["targetSessionId"], session["id"])
        self.assertEqual(preview["schedule"]["targetDisplayName"], "当前 Agent")

    def test_user_created_persona_can_start_a_real_session(self) -> None:
        created_role = self.service.create_role(
            {
                "displayName": "智鼬·雨天",
                "tagline": "在安静的雨天陪你整理",
                "summary": "偏向温和复盘与日常记录。",
                "traits": ["温和", "善于复盘"],
                "timelineModel": "terra",
                "selectableModes": ["assistant", "coordinator"],
            }
        )["role"]

        self.assertTrue(str(created_role["roleId"]).startswith("persona-"))
        for internal_key in (
            "personaPrompt",
            "systemPrompt",
            "safetyPolicyPrompt",
            "toolPolicy",
            "origin",
        ):
            self.assertNotIn(internal_key, created_role)
        self.assertEqual(self.service.list_roles()["items"][-1], created_role)
        private_role = self.service.personas.resolve(created_role["roleId"], created_role["version"])
        self.assertIn("智鼬·雨天", private_role.system_prompt)
        self.assertIn("只有受控审批回执有效", private_role.system_prompt)
        session = self.service.create_session(
            {
                "title": "雨天整理",
                "mode": "coordinator",
                "roleId": created_role["roleId"],
                "roleVersion": created_role["version"],
            }
        )["session"]
        self.assertEqual(session["roleId"], created_role["roleId"])
        self.assertEqual(session["roleVersion"], "1")
        self.assertEqual(session["modelProfile"], "pi/default")
        self.assertEqual(session["toolProfileVersion"], "control-center-v1")

        room = self.service.create_room(
            {
                "title": "雨天协作",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": created_role["roleId"], "roleVersion": "1"},
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        self.assertEqual(room["participants"][0]["roleId"], created_role["roleId"])

        with self.assertRaisesRegex(ValueError, "tool policy cannot be overridden"):
            self.service.create_session(
                {
                    "title": "越权工具策略",
                    "roleId": created_role["roleId"],
                    "roleVersion": "1",
                    "toolProfileVersion": "subagent-readonly-v1",
                }
            )

    def test_room_intercom_delivery_uses_pi_transcript_without_memory_checkpoint(self) -> None:
        room = self.service.create_room(
            {
                "title": "边界讨论",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                    {"roleId": "vcp-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        source, target = room["participants"]
        source_session = self.service.sessions.get(str(source["sessionId"]))
        target_session = self.service.sessions.get(str(target["sessionId"]))
        self.assertEqual(source_session["modelProfile"], "pi/default")
        self.assertEqual(target_session["modelProfile"], "pi/default")
        item = {
            "id": "room-message:test",
            "kind": "ask",
            "sourceParticipantId": source["id"],
            "targetParticipantId": target["id"],
            "sourceSessionId": source["sessionId"],
            "targetSessionId": target["sessionId"],
            "replyTo": "",
            "content": "控制面板是否只是配置客户端？",
        }

        with (
            patch.object(self.service, "_room_target_idle", return_value=True),
            patch.object(
                self.service.runtime,
                "prompt",
                return_value={"accepted": True, "turnId": "turn:intercom"},
            ) as prompt,
            patch.object(
                self.service.memory_sources,
                "checkpoint_user_message",
            ) as checkpoint,
        ):
            accepted = self.service._deliver_room_intercom(item)

        self.assertEqual(accepted["turnId"], "turn:intercom")
        self.assertIn("房间协作消息", prompt.call_args.args[1])
        self.assertIn("ime_agents.room_reply", prompt.call_args.args[1])
        checkpoint.assert_not_called()

    def test_message_snapshot_returns_event_resume_cursor(self) -> None:
        session = self.service.create_session({"title": "恢复游标"})["session"]
        session_id = str(session["id"])
        event = self.service.events.publish(session_id, "status_changed", {"status": "ready"})
        with patch.object(self.service.runtime, "messages", return_value=[]):
            response = self.service.messages(session_id)

        self.assertEqual(response["lastSequence"], event.sequence)
        self.assertEqual(response["resumeToken"], event.resume_token)
        self.assertEqual(response["status"], "idle")
        self.assertEqual(response["liveEvents"], [event.to_payload()])

    def test_message_snapshot_keeps_completed_tools_after_replay_eviction(self) -> None:
        session = self.service.create_session({"title": "工具历史恢复"})["session"]
        session_id = str(session["id"])
        self.service.events.publish(
            session_id,
            "tool_started",
            {"toolCallId": "tool-1", "toolName": "workspace_read", "args": {}},
            turn_id="history:user-1",
        )
        history = [
            AgentEventEnvelope(
                event_id=f"{session_id}:history:start",
                session_id=session_id,
                turn_id="history:user-1",
                sequence=1,
                created_at_ms=100,
                event_type="tool_started",
                payload={"toolCallId": "tool-1", "toolName": "workspace_read", "args": {"path": "README.md"}},
                resume_token=f"{session_id}:history:start",
            ).to_payload(),
            AgentEventEnvelope(
                event_id=f"{session_id}:history:finish",
                session_id=session_id,
                turn_id="history:user-1",
                sequence=2,
                created_at_ms=101,
                event_type="tool_finished",
                payload={"toolCallId": "tool-1", "toolName": "workspace_read", "args": {}, "result": {"summary": "读取完成"}},
                resume_token=f"{session_id}:history:finish",
            ).to_payload(),
        ]
        with patch.object(
            self.service.runtime,
            "session_snapshot",
            create=True,
            return_value={
                "messages": [],
                "toolHistoryEvents": history,
                "telemetry": None,
                "messageQueue": None,
            },
        ):
            response = self.service.messages(session_id)

        tool_events = [
            event for event in response["liveEvents"]
            if event["eventType"] in {"tool_started", "tool_finished"}
        ]
        self.assertEqual([event["eventType"] for event in tool_events], ["tool_started", "tool_finished"])
        self.assertEqual(tool_events[0]["payload"]["args"], {"path": "README.md"})
        self.assertEqual(tool_events[1]["payload"]["result"], {"summary": "读取完成"})

    def test_message_snapshot_treats_open_transcript_as_idle_without_a_live_turn(self) -> None:
        session = self.service.create_session({"title": "旧会话恢复"})["session"]
        session_id = str(session["id"])
        self.service.sessions.set_status(session_id, "active")
        with (
            patch.object(self.service.runtime, "messages", return_value=[]),
            patch.object(
                self.service.runtime,
                "runtime_status",
                return_value={
                    "status": "ready",
                    "activeSessionId": session_id,
                    "activeSessionIds": [],
                    "openSessionIds": [session_id],
                },
            ),
        ):
            response = self.service.messages(session_id)

        self.assertEqual(response["status"], "idle")
        self.assertEqual(self.service.sessions.get(session_id)["status"], "idle")

    def test_message_snapshot_keeps_the_exact_runtime_turn_busy(self) -> None:
        session = self.service.create_session({"title": "当前回合"})["session"]
        session_id = str(session["id"])
        self.service.sessions.set_status(session_id, "active")
        with (
            patch.object(self.service.runtime, "messages", return_value=[]),
            patch.object(
                self.service.runtime,
                "runtime_status",
                return_value={
                    "status": "busy",
                    "activeSessionId": session_id,
                    "activeSessionIds": [session_id],
                    "openSessionIds": [session_id],
                },
            ),
        ):
            response = self.service.messages(session_id)

        self.assertEqual(response["status"], "busy")
        self.assertEqual(self.service.sessions.get(session_id)["status"], "busy")

    def test_message_snapshot_reconstructs_durable_pending_approval(self) -> None:
        session = self.service.create_session({"title": "待审批恢复"})["session"]
        session_id = str(session["id"])
        approval = self.service.sessions.create_approval(
            session_id=session_id,
            tool_name="workspace_write_file",
            operation="写入 README.md",
            payload_sha256="a" * 64,
            preview={"path": "README.md"},
            risk_level="R2",
            ttl_ms=120_000,
        )
        with patch.object(self.service.runtime, "messages", return_value=[]):
            response = self.service.messages(session_id)

        pending = [
            event
            for event in response["liveEvents"]
            if event["eventType"] == "approval_required"
        ]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["payload"]["approvalId"], approval["approvalId"])
        self.assertEqual(pending[0]["payload"]["payloadSha256"], "a" * 64)
        self.assertEqual(pending[0]["turnId"], f"approval:{approval['approvalId']}")

    def test_message_snapshot_does_not_duplicate_replayed_pending_approval(self) -> None:
        session = self.service.create_session({"title": "审批事件去重"})["session"]
        session_id = str(session["id"])
        approval = self.service.sessions.create_approval(
            session_id=session_id,
            tool_name="workspace_write_file",
            operation="写入 README.md",
            payload_sha256="b" * 64,
            preview={"path": "README.md"},
            risk_level="R2",
            ttl_ms=120_000,
        )
        event = self.service.events.publish(
            session_id,
            "approval_required",
            approval,
            turn_id="turn:approval",
        )
        with patch.object(self.service.runtime, "messages", return_value=[]):
            response = self.service.messages(session_id)

        pending = [
            item
            for item in response["liveEvents"]
            if item["eventType"] == "approval_required"
        ]
        self.assertEqual(pending, [event.to_payload()])

    def test_model_catalog_and_selection_are_owned_by_pi_session(self) -> None:
        session = self.service.create_session({"title": "模型切换"})["session"]
        session_id = str(session["id"])
        model = {
            "provider": "openrouter",
            "id": "anthropic/claude-sonnet",
            "name": "Claude Sonnet",
            "api": "openai-completions",
            "reasoning": True,
            "thinkingLevels": ["off", "low", "medium", "high"],
            "supportsImages": True,
            "contextWindow": 200000,
            "maxTokens": 16384,
        }
        with patch.object(
            self.service.runtime,
            "model_catalog",
            return_value={"selected": model, "models": [model], "thinkingLevel": "medium"},
        ):
            catalog = self.service.model_catalog(session_id)

        self.assertEqual(catalog["providers"][0]["displayName"], "OpenRouter")
        self.assertEqual(catalog["selected"]["id"], "anthropic/claude-sonnet")
        self.assertEqual(catalog["thinkingLevel"], "medium")
        self.assertNotIn("apiKey", json.dumps(catalog))

        with patch.object(
            self.service.runtime,
            "model_catalog",
            return_value={"selected": model, "models": [], "thinkingLevel": "medium"},
        ):
            partial_catalog = self.service.model_catalog(session_id)
        self.assertEqual(partial_catalog["providers"][0]["models"][0]["id"], model["id"])

        selected_session = self.service.sessions.set_model_profile(
            session_id,
            "openrouter/anthropic/claude-sonnet",
        )
        with patch.object(
            self.service.runtime,
            "set_model",
            return_value={"selected": model, "session": selected_session},
        ) as select:
            response = self.service.select_model(
                session_id,
                {"provider": "openrouter", "modelId": "anthropic/claude-sonnet"},
            )

        select.assert_called_once_with(
            session_id,
            provider="openrouter",
            model_id="anthropic/claude-sonnet",
        )

        self.assertEqual(response["session"]["modelProfile"], "openrouter/anthropic/claude-sonnet")

        with patch.object(
            self.service.runtime,
            "set_thinking_level",
            return_value={"thinkingLevel": "high", "selected": model},
        ) as set_thinking:
            thinking = self.service.select_thinking_level(session_id, {"level": "high"})
        set_thinking.assert_called_once_with(session_id, level="high")
        self.assertEqual(thinking["thinkingLevel"], "high")

        events, gap = self.service.events.replay(session_id)
        self.assertFalse(gap)
        configuration_events = [
            event for event in events if event.event_type == "session_configuration_changed"
        ]
        self.assertEqual(
            [event.payload["kind"] for event in configuration_events],
            ["model", "thinking"],
        )

    def test_role_runtime_defaults_are_listed_saved_and_inherited_by_new_sessions(self) -> None:
        runtime_config = PiRuntimeConfig(
            enabled=False,
            executable=None,
            agent_dir=self.root / "role-agent-config",
            session_dir=self.root / "role-sessions",
            logs_dir=self.root / "role-logs",
            provider="deepseek",
            model="deepseek-v4-flash",
            model_providers={
                "deepseek": {
                    "models": [
                        {
                            "id": "deepseek-v4-flash",
                            "name": "DeepSeek V4 Flash",
                            "reasoning": False,
                        }
                    ]
                }
            },
        )
        service = AgentService(
            db_path=self.root / "role-defaults.sqlite",
            runtime_config=runtime_config,
            process_id_provider=lambda: self.process_id,
        )
        available_models = [
            {
                "provider": "gpt",
                "id": "gpt-5.6-luna",
                "name": "GPT-5.6 Luna",
                "thinkingLevels": ["off", "max"],
            },
            {
                "provider": "gpt",
                "id": "gpt-5.6-terra",
                "name": "GPT-5.6 Terra",
                "thinkingLevels": ["off", "max"],
            },
            {
                "provider": "gpt",
                "id": "gpt-5.6-sol",
                "name": "GPT-5.6 Sol",
                "thinkingLevels": ["off", "xhigh"],
            },
        ]
        with patch.object(service.runtime, "available_models", return_value=available_models):
            initial_roles = {
                item["roleId"]: item["defaults"] for item in service.list_roles()["items"]
            }
        self.assertEqual(
            initial_roles["hermes-v1"],
            {
                "modelPolicy": "runtime-default",
                "memoryPolicy": "personal-evidence-v1",
                "toolProfileVersion": "control-center-v1",
                "modelProfile": "gpt/gpt-5.6-luna",
                "thinkingLevel": "max",
            },
        )
        self.assertEqual(initial_roles["zhiyou-v1"]["modelProfile"], "gpt/gpt-5.6-terra")
        self.assertEqual(initial_roles["zhiyou-v1"]["thinkingLevel"], "max")
        self.assertEqual(initial_roles["vcp-v1"]["modelProfile"], "gpt/gpt-5.6-sol")
        self.assertEqual(initial_roles["vcp-v1"]["thinkingLevel"], "xhigh")
        with patch.object(service.runtime, "available_models", return_value=available_models):
            catalog = service.role_model_catalog()
        self.assertEqual(catalog["providers"][0]["models"][0]["name"], "GPT-5.6 Luna")
        with patch.object(service.runtime, "available_models", return_value=available_models):
            response = service.update_role_runtime_defaults(
                {
                    "roleId": "zhiyou-v1",
                    "roleVersion": "1",
                    "provider": "gpt",
                    "modelId": "gpt-5.6-luna",
                    "thinkingLevel": "max",
                }
            )
        self.assertEqual(response["role"]["defaults"]["thinkingLevel"], "max")
        self.assertEqual(
            service.list_roles()["items"][0]["defaults"]["modelProfile"],
            "gpt/gpt-5.6-luna",
        )
        with patch.object(service.runtime, "set_thinking_level") as set_thinking:
            session = service.create_session(
                {"title": "继承角色默认", "roleId": "zhiyou-v1", "roleVersion": "1"}
            )["session"]
        self.assertEqual(session["modelProfile"], "gpt/gpt-5.6-luna")
        self.assertEqual(session["thinkingLevel"], "max")
        set_thinking.assert_not_called()

        explicit = service.create_session(
            {
                "title": "本轮显式模型",
                "roleId": "zhiyou-v1",
                "roleVersion": "1",
                "modelProfile": "gpt/gpt-5.6-sol",
            }
        )["session"]
        self.assertEqual(explicit["modelProfile"], "gpt/gpt-5.6-sol")
        self.assertEqual(explicit["thinkingLevel"], "")

    def test_command_catalog_exposes_only_pi_prompt_commands_and_degrades_cleanly(self) -> None:
        session = self.service.create_session({"title": "命令目录"})["session"]
        session_id = str(session["id"])
        pi_commands = [
            {
                "name": "review",
                "invocation": "/review",
                "description": "Review the active change",
                "source": "extension",
            }
        ]
        with patch.object(
            self.service.runtime,
            "command_catalog",
            return_value=pi_commands,
        ):
            response = self.service.command_catalog(session_id)

        self.assertTrue(response["runtimeAvailable"])
        self.assertEqual(response["items"], pi_commands)

        with patch.object(
            self.service.runtime,
            "command_catalog",
            side_effect=PiRuntimeError("private runtime path"),
        ):
            unavailable = self.service.command_catalog(session_id)

        self.assertFalse(unavailable["runtimeAvailable"])
        self.assertEqual(unavailable["items"], [])
        self.assertNotIn("private runtime path", json.dumps(unavailable))

    def test_session_lifecycle_probes_memory_due_without_running_the_organizer(self) -> None:
        session = self.service.create_session({"title": "生命周期"})["session"]
        session_id = str(session["id"])
        triggers: list[str] = []

        def probe(payload):
            triggers.append(str(payload["trigger"]))
            return {
                "schemaVersion": "rag-ime.agent-memory-maintenance-status.v1",
                "ok": True,
                "policy": "review",
                "autoApply": False,
                "due": True,
                "dueReason": "idle",
                "compileState": {"pendingEventCount": 4},
                "pendingDraftCount": 1,
                "runs": [],
            }

        self.service.bind_memory_maintenance_probe(probe)
        with patch.object(
            self.service.runtime,
            "ensure",
            return_value={"state": {"sessionId": "pi-test"}, "session": session},
        ):
            ensured = self.service.ensure_runtime({"sessionId": session_id})
        archived = self.service.update_session(session_id, {"archived": True})
        with patch.object(self.service.runtime, "compact", return_value={"compacted": True}):
            compacted = self.service.compact(session_id, {})

        self.assertEqual(triggers, ["session_switch", "session_archive", "compaction"])
        self.assertEqual(ensured["memoryMaintenance"]["trigger"], "session_switch")
        self.assertEqual(archived["memoryMaintenance"]["trigger"], "session_archive")
        self.assertEqual(compacted["memoryMaintenance"]["trigger"], "compaction")
        events, gap = self.service.events.replay(session_id)
        self.assertFalse(gap)
        self.assertEqual(
            [event.event_type for event in events],
            ["memory_maintenance_updated"] * 3,
        )
        self.assertTrue(all(event.payload["due"] is True for event in events))

    def test_session_input_and_runtime_capabilities_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "workspaceRoots must be an array"):
            self.service.create_session({"title": "bad", "workspaceRoots": self.root.as_posix()})
        with self.assertRaisesRegex(ValueError, "unsupported agent role"):
            self.service.create_session({"title": "bad", "roleId": "model-injected-role"})
        with self.assertRaisesRegex(ValueError, "cannot carry workspace roots"):
            self.service.create_session({"title": "bad", "workspaceRoots": [self.root.as_posix()]})

        coordinator = self.service.create_session(
            {
                "title": "运行协调",
                "mode": "coordinator",
                "workspaceRoots": [self.root.as_posix()],
            }
        )["session"]
        self.assertEqual(coordinator["mode"], "coordinator")
        with self.assertRaisesRegex(PiRuntimeError, "disabled"):
            self.service.ensure_runtime({"sessionId": coordinator["id"]})

    def test_delete_only_removes_session_file_inside_managed_root(self) -> None:
        inside = self.service.create_session({"title": "inside"})["session"]
        session_root = self.service.runtime.config.session_dir
        session_root.mkdir(parents=True)
        inside_file = session_root / "inside.jsonl"
        inside_file.write_text("{}\n", encoding="utf-8")
        self.service.sessions.bind_pi_session(
            str(inside["id"]),
            pi_session_id="pi-inside",
            session_file=str(inside_file),
        )
        deleted = self.service.delete_session(str(inside["id"]))
        self.assertTrue(deleted["sessionFileDeleted"])
        self.assertFalse(inside_file.exists())

        outside = self.service.create_session({"title": "outside"})["session"]
        outside_file = self.root / "outside.jsonl"
        outside_file.write_text("{}\n", encoding="utf-8")
        self.service.sessions.bind_pi_session(
            str(outside["id"]),
            pi_session_id="pi-outside",
            session_file=str(outside_file),
        )
        deleted = self.service.delete_session(str(outside["id"]))
        self.assertFalse(deleted["sessionFileDeleted"])
        self.assertTrue(outside_file.exists())

    def test_managed_image_is_bound_to_prompt_and_deleted_with_session(self) -> None:
        session = self.service.create_session({"title": "图片对话"})["session"]
        session_id = str(session["id"])
        imported = self.service.import_media(
            session_id=session_id,
            data=PNG_1X1,
            mime_type="image/png",
            file_name="screen.png",
        )["media"]

        with (
            patch.object(
                self.service.runtime,
                "model_catalog",
                return_value={"selected": {"supportsImages": True}},
            ),
            patch.object(
                self.service.runtime,
                "prompt",
                return_value={
                    "accepted": True,
                    "turnId": "turn:image:1",
                    "piEntryId": "pi-entry:image:1",
                    "response": {"success": True},
                },
            ) as prompt,
        ):
            response = self.service.prompt(
                session_id,
                {
                    "message": "这张图里有什么",
                    "attachments": [imported["mediaId"]],
                    "clientMessageId": "web-image-1",
                },
            )

        images = prompt.call_args.kwargs["images"]
        self.assertEqual(images[0]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(images[0]["data"]), PNG_1X1)
        self.assertEqual(prompt.call_args.kwargs["client_message_id"], "web-image-1")
        self.assertEqual(response["attachments"][0]["mediaId"], imported["mediaId"])
        self.assertEqual(
            self.service.media.attachments_for_entry(
                session_id=session_id,
                pi_entry_id="pi-entry:image:1",
            )[0]["mediaId"],
            imported["mediaId"],
        )
        events, _ = self.service.events.replay(session_id)
        user_event = next(event for event in events if event.event_type == "message_completed")
        self.assertEqual(user_event.payload["clientMessageId"], "web-image-1")
        self.assertEqual(user_event.payload["message"]["id"], "pi-entry:image:1")
        self.assertEqual(user_event.payload["message"]["clientMessageId"], "web-image-1")
        image_block = user_event.payload["message"]["blocks"][1]
        self.assertEqual(image_block["type"], "image")
        self.assertIn("/api/agent/media/", image_block["data"]["receiptUrl"])

        deleted = self.service.delete_session(session_id)
        self.assertEqual(deleted["mediaFilesDeleted"], 1)
        self.assertEqual(list(self.service.media.root.glob("*.blob")), [])

    def test_prompt_client_message_id_is_durable_and_idempotent(self) -> None:
        session = self.service.create_session({"title": "多端幂等"})["session"]
        session_id = str(session["id"])
        payload = {"message": "只执行一次", "clientMessageId": "device-command-1"}
        with patch.object(
            self.service.runtime,
            "prompt",
            return_value={
                "accepted": True,
                "turnId": "turn:idempotent:1",
                "piEntryId": "pi-entry:idempotent:1",
                "response": {"success": True},
            },
        ) as prompt:
            first = self.service.prompt(session_id, payload)

        prompt.assert_called_once()
        completed, _ = self.service.events.replay(session_id)
        self.assertEqual(
            len(
                [
                    event
                    for event in completed
                    if event.event_type == "message_completed"
                    and event.payload.get("clientMessageId") == "device-command-1"
                ]
            ),
            1,
        )
        self.service.close()
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
            process_id_provider=lambda: self.process_id,
        )
        with patch.object(self.service.runtime, "prompt") as replay_prompt:
            replay = self.service.prompt(session_id, payload)
        replay_prompt.assert_not_called()
        self.assertNotIn("idempotentReplay", first)
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay["turnId"], first["turnId"])
        with self.assertRaisesRegex(ValueError, "different command payload"):
            self.service.prompt(
                session_id,
                {"message": "不能复用标识", "clientMessageId": "device-command-1"},
            )
        with self.assertRaisesRegex(ValueError, "different command payload"):
            self.service.prompt(
                session_id,
                {
                    "message": "只执行一次",
                    "delivery": "steer",
                    "clientMessageId": "device-command-1",
                },
            )

    def test_text_only_pi_model_rejects_managed_image_before_prompt(self) -> None:
        session = self.service.create_session({"title": "文本模型"})["session"]
        session_id = str(session["id"])
        imported = self.service.import_media(
            session_id=session_id,
            data=PNG_1X1,
            mime_type="image/png",
            file_name="screen.png",
        )["media"]

        with (
            patch.object(
                self.service.runtime,
                "model_catalog",
                return_value={"selected": {"supportsImages": False}},
            ),
            patch.object(self.service.runtime, "prompt") as prompt,
        ):
            with self.assertRaisesRegex(ValueError, "当前模型不支持图片"):
                self.service.prompt(
                    session_id,
                    {"message": "看看图片", "attachments": [imported["mediaId"]]},
                )
        prompt.assert_not_called()

    def test_steer_and_follow_up_delivery_reuse_the_active_turn_and_are_visible(self) -> None:
        session = self.service.create_session({"title": "排队消息"})["session"]
        session_id = str(session["id"])
        for delivery in ("steer", "followUp"):
            client_message_id = f"web-{delivery}"
            with patch.object(
                self.service.runtime,
                "prompt",
                return_value={
                    "accepted": True,
                    "queued": True,
                    "delivery": delivery,
                    "turnId": "turn:active:1",
                    "piEntryId": f"queue:{client_message_id}",
                    "response": {"success": True},
                },
            ) as prompt:
                result = self.service.prompt(
                    session_id,
                    {
                        "message": f"{delivery} message",
                        "delivery": delivery,
                        "clientMessageId": client_message_id,
                    },
                )

            self.assertEqual(prompt.call_args.kwargs["delivery"], delivery)
            self.assertEqual(result["turnId"], "turn:active:1")

        events, _ = self.service.events.replay(session_id)
        user_messages = [
            event.payload["message"] for event in events
            if event.event_type == "message_completed"
        ]
        self.assertEqual(
            [message["blocks"][0]["data"]["delivery"] for message in user_messages],
            ["steer", "followUp"],
        )
        self.assertEqual({message["turnId"] for message in user_messages}, {"turn:active:1"})
        with self.assertRaisesRegex(ValueError, "delivery"):
            self.service.prompt(session_id, {"message": "bad", "delivery": "later"})

    def test_persisted_runtime_toggle_is_used_unless_development_env_overrides_it(self) -> None:
        settings = {"agent": {"pi": {"enabled": True, "idleTimeoutSeconds": 321}}}
        with patch.dict("os.environ", {}, clear=True):
            configured = pi_runtime_config_from_settings(settings)
        self.assertTrue(configured.enabled)
        self.assertEqual(configured.idle_timeout_seconds, 321)

        with patch.dict(
            "os.environ",
            {"RAG_IME_PI_ENABLED": "false", "RAG_IME_PI_IDLE_TIMEOUT_SECONDS": "12"},
            clear=True,
        ):
            overridden = pi_runtime_config_from_settings(settings)
        self.assertFalse(overridden.enabled)
        self.assertEqual(overridden.idle_timeout_seconds, 12)

    def test_approval_api_lists_and_rejects_but_cannot_fake_an_approval(self) -> None:
        session = self.service.create_session({"title": "审批"})["session"]
        approval = self.service.sessions.create_approval(
            session_id=str(session["id"]),
            tool_name="ime_input",
            operation="apply_settings",
            payload_sha256="a" * 64,
            preview={"summary": "关闭模糊音"},
            risk_level="R1",
        )
        listed = self.service.list_approvals({"sessionId": session["id"]})
        self.assertEqual(listed["items"][0]["approvalId"], approval["approvalId"])

        rejected = self.service.decide_approval(
            str(approval["approvalId"]),
            {"decision": "reject", "payloadSha256": "a" * 64},
        )
        self.assertEqual(rejected["approval"]["state"], "rejected")

        forged = self.service.sessions.create_approval(
            session_id=str(session["id"]),
            tool_name="ime_runtime",
            operation="restart",
            payload_sha256="b" * 64,
            preview={"summary": "重启"},
            risk_level="R2",
        )
        with self.assertRaisesRegex(ValueError, "no longer active in Pi"):
            self.service.decide_approval(
                str(forged["approvalId"]),
                {"decision": "approve", "payloadSha256": "b" * 64},
            )
        self.assertEqual(
            self.service.sessions.get_approval(str(forged["approvalId"]))["state"],
            "pending",
        )

    def test_expired_or_stale_approval_closes_the_pending_pi_request(self) -> None:
        session = self.service.create_session({"title": "审批终态"})["session"]
        session_id = str(session["id"])
        expired = self.service.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_input",
            operation="apply_settings",
            payload_sha256="e" * 64,
            preview={"summary": "过期变更"},
            risk_level="R1",
            requested_at_ms=100,
            ttl_ms=1_000,
        )
        with (
            patch.object(self.service.runtime, "has_pending_approval", return_value=True),
            patch.object(self.service.runtime, "resolve_approval") as resolve_expired,
        ):
            result = self.service.decide_approval(
                str(expired["approvalId"]),
                {"decision": "approve", "payloadSha256": "e" * 64},
            )
        self.assertEqual(result["approval"]["state"], "expired")
        resolve_expired.assert_called_once_with(
            session_id,
            str(expired["approvalId"]),
            approved=False,
            resolution_state="expired",
        )

        stale = self.service.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_input",
            operation="apply_settings",
            payload_sha256="a" * 64,
            preview={"summary": "哈希已变化"},
            risk_level="R1",
        )
        with (
            patch.object(self.service.runtime, "has_pending_approval", return_value=True),
            patch.object(self.service.runtime, "resolve_approval") as resolve_stale,
        ):
            result = self.service.decide_approval(
                str(stale["approvalId"]),
                {"decision": "approve", "payloadSha256": "b" * 64},
            )
        self.assertEqual(result["approval"]["state"], "stale")
        resolve_stale.assert_called_once_with(
            session_id,
            str(stale["approvalId"]),
            approved=False,
            resolution_state="stale",
        )

    def test_approved_operation_executes_before_pi_is_released_and_returns_receipt(self) -> None:
        session = self.service.create_session({"title": "任务审批"})["session"]
        approval = self.service.sessions.create_approval(
            session_id=str(session["id"]),
            tool_name="ime_planning",
            operation="task_action",
            payload_sha256="c" * 64,
            preview={"summary": "完成接入 Pi"},
            risk_level="R1",
        )
        calls: list[str] = []

        def execute(value):
            calls.append("execute")
            self.assertEqual(value["state"], "approved")
            return {
                "schemaVersion": "rag-ime.agent-operation-receipt.v1",
                "mutationApplied": True,
                "summary": "已完成接入 Pi",
                "auditId": 42,
                "undoAvailable": True,
            }

        self.service.bind_approval_executor(execute)
        with (
            patch.object(self.service.runtime, "has_pending_approval", return_value=True),
            patch.object(self.service.runtime, "resolve_approval") as resolve,
        ):
            result = self.service.decide_approval(
                str(approval["approvalId"]),
                {"decision": "approve", "payloadSha256": "c" * 64},
            )

        self.assertEqual(calls, ["execute"])
        self.assertEqual(result["approval"]["state"], "applied")
        self.assertTrue(result["approval"]["receipt"]["mutationApplied"])
        self.assertTrue(result["runtimeNotified"])
        resolve.assert_called_once_with(
            str(session["id"]),
            str(approval["approvalId"]),
            approved=True,
            resolution_state="applied",
        )
        lookup = self.service.approval_result(
            {"sessionId": session["id"], "approvalId": approval["approvalId"]}
        )
        self.assertEqual(lookup["approval"]["receipt"]["auditId"], 42)

    def test_governed_memory_approval_recovers_from_committed_store_journal(self) -> None:
        session = self.service.create_session({"title": "记忆审批崩溃恢复"})["session"]
        evidence = self.service.memory_evidence.record_user_message(
            session_id=str(session["id"]),
            pi_entry_id="message:memory-recovery",
            text="用户明确决定验证审批崩溃恢复",
            role_id=str(session["roleId"]),
        )["evidence"]
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=object(),
            core=object(),
            project=self.service.project,
            role_books=self.service.role_books,
        )

        preview = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": session["id"],
                "tool": "ime_memory",
                "toolCallId": "tool:memory-recovery:preview",
                "args": {
                    "op": "remember_preview",
                    "text": "当前要验证审批崩溃恢复",
                    "memoryKind": "decision",
                    "evidenceIds": [evidence["evidenceId"]],
                },
            }
        )["result"]
        prepared = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": session["id"],
                "tool": "ime_memory",
                "toolCallId": "tool:memory-recovery:apply",
                "args": {
                    "op": "remember_apply",
                    "proposalId": preview["proposalId"],
                },
            }
        )["result"]
        approval = prepared["approval"]
        decided = self.service.sessions.decide_approval(
            str(approval["approvalId"]),
            approved=True,
            payload_sha256=str(approval["payloadSha256"]),
        )

        committed_receipt = gateway.apply_approval(decided)
        self.assertTrue(committed_receipt["mutationApplied"])
        self.assertEqual(
            self.service.sessions.get_approval(str(approval["approvalId"]))["state"],
            "approved",
        )
        self.service.bind_approval_executor(gateway.apply_approval)
        with (
            patch.object(self.service.runtime, "has_pending_approval", return_value=False),
            self.assertRaisesRegex(ValueError, "payload is stale"),
        ):
            self.service.decide_approval(
                str(approval["approvalId"]),
                {"decision": "approve", "payloadSha256": "d" * 64},
            )
        self.assertEqual(
            self.service.sessions.get_approval(str(approval["approvalId"]))["state"],
            "approved",
        )

        with patch.object(
            self.service.runtime,
            "has_pending_approval",
            return_value=False,
        ):
            recovered = self.service.decide_approval(
                str(approval["approvalId"]),
                {
                    "decision": "approve",
                    "payloadSha256": approval["payloadSha256"],
                },
            )

        self.assertEqual(recovered["approval"]["state"], "applied")
        self.assertTrue(recovered["approval"]["receipt"]["mutationApplied"])
        self.assertTrue(recovered["approval"]["receipt"]["idempotentReplay"])
        with sqlite3.connect(self.service.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE text = ?",
                    ("当前要验证审批崩溃恢复",),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT status
                    FROM memory_governance_proposals
                    WHERE proposal_id = ?
                    """,
                    (preview["proposalId"],),
                ).fetchone()[0],
                "applied",
            )

    def test_memory_review_decision_resumes_the_active_pi_turn(self) -> None:
        session = self.service.create_session({"title": "记忆草案审阅"})["session"]
        session_id = str(session["id"])
        with (
            patch.object(self.service.runtime, "has_pending_review", return_value=True),
            patch.object(self.service.runtime, "resolve_review") as resolve,
        ):
            result = self.service.resolve_review(
                session_id,
                {"runId": "memory-run-1", "decision": "deferred"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"], "deferred")
        resolve.assert_called_once_with(
            session_id,
            "memory-run-1",
            reviewed=False,
        )

        with self.assertRaisesRegex(ValueError, "reviewed or deferred"):
            self.service.resolve_review(
                session_id,
                {"runId": "memory-run-1", "decision": "approve"},
            )

    def test_sidecar_restart_is_released_to_pi_then_finalized_by_new_process(self) -> None:
        session = self.service.create_session({"title": "Sidecar 两阶段重启"})["session"]
        approval = self.service.sessions.create_approval(
            session_id=str(session["id"]),
            tool_name="ime_runtime",
            operation="restart_sidecar",
            payload_sha256="d" * 64,
            preview={"summary": "重启 Sidecar"},
            risk_level="R2",
        )
        command = ["launchctl", "kickstart", "-k", "gui/501/com.rag-ime.sidecar"]
        command_sha256 = hashlib.sha256(
            json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

        self.service.bind_approval_executor(
            lambda value: {
                "schemaVersion": "rag-ime.agent-operation-receipt.v1",
                "mutationApplied": False,
                "externalActionPending": True,
                "approvalId": value["approvalId"],
                "toolId": "ime_runtime",
                "operation": "restart_sidecar",
                "summary": "等待 Pi 回合结束",
                "externalAction": "restart_sidecar",
                "externalCommand": command,
                "externalCommandSha256": command_sha256,
            }
        )
        with (
            patch.object(self.service.runtime, "has_pending_approval", return_value=True),
            patch.object(self.service.runtime, "resolve_approval") as resolve,
        ):
            pending = self.service.decide_approval(
                str(approval["approvalId"]),
                {"decision": "approve", "payloadSha256": "d" * 64},
            )

        self.assertEqual(pending["approval"]["state"], "external_pending")
        self.assertEqual(pending["approval"]["receipt"]["originProcessId"], 100)
        self.assertFalse(pending["approval"]["receipt"]["mutationApplied"])
        resolve.assert_called_once_with(
            str(session["id"]),
            str(approval["approvalId"]),
            approved=True,
            resolution_state="external_pending",
        )
        finalize_payload = {
            "payloadSha256": "d" * 64,
            "externalAction": "restart_sidecar",
            "externalCommandSha256": command_sha256,
            "succeeded": True,
            "exitCode": 0,
            "timedOut": False,
        }
        with self.assertRaisesRegex(ValueError, "new Sidecar process"):
            self.service.finalize_external_approval(str(approval["approvalId"]), finalize_payload)

        self.process_id = 101
        finalized = self.service.finalize_external_approval(
            str(approval["approvalId"]),
            finalize_payload,
        )
        self.assertEqual(finalized["approval"]["state"], "applied")
        self.assertTrue(finalized["approval"]["receipt"]["mutationApplied"])
        self.assertFalse(finalized["approval"]["receipt"]["externalActionPending"])
        self.assertEqual(finalized["approval"]["receipt"]["finalProcessId"], 101)
        events, _ = self.service.events.replay(str(session["id"]))
        self.assertEqual(events[-1].event_type, "approval_resolved")
        self.assertTrue(events[-1].payload["externalFinalized"])

    def test_final_user_prompt_creates_private_source_checkpoint_without_activity(self) -> None:
        session = self.service.create_session({"title": "连续记忆"})["session"]
        with patch.object(
            self.service.runtime,
            "prompt",
            return_value={
                "accepted": True,
                "turnId": "turn:memory:1",
                "piEntryId": "pi-entry:user:1",
                "response": {"success": True},
            },
        ):
            result = self.service.prompt(
                str(session["id"]),
                {"message": "记住普通生成和深度检索要分开"},
            )

        self.assertTrue(result["memoryCheckpoint"]["stored"])
        sources = self.service.list_memory_sources({"sessionId": session["id"]})["items"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["sourceRole"], "user")
        events, _ = self.service.events.replay(str(session["id"]))
        self.assertNotIn("memory_checkpointed", [event.event_type for event in events])

    def test_input_method_deep_search_reuses_daily_assistant_and_checkpoints_only_question(self) -> None:
        runtime_status = {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "status": "ready",
            "activeSessionId": None,
            "capabilities": {"rpc": True, "modelConfigured": True},
        }
        prompt_receipt = {
            "accepted": True,
            "turnId": "turn:deep:1",
            "piEntryId": "pi-entry:deep:1",
            "response": {"success": True},
        }
        payload = {
            "query": "最近我在做什么？",
            "context": "前面还讨论了 Pi Session 和双闪电入口。",
            "contextSource": "text_input_client",
            "frontAppBundleId": "com.example.editor",
            "privacyDisposition": "allowed",
            "evidence": [
                {
                    "sourceType": "memory",
                    "title": "Pi 控制中心",
                    "memoryId": "book:pi",
                    "evidencePreview": "控制中心使用连续 Pi Session。",
                }
            ],
        }

        with (
            patch.object(self.service, "runtime_status", return_value=runtime_status),
            patch.object(self.service.runtime, "prompt", return_value=prompt_receipt) as prompt,
        ):
            first = self.service.deep_search(payload)
            second = self.service.deep_search(payload)

        self.assertTrue(first["accepted"])
        self.assertTrue(first["sessionCreated"])
        self.assertFalse(second["sessionCreated"])
        self.assertEqual(first["sessionId"], second["sessionId"])
        self.assertTrue(str(first["session"]["title"]).startswith("输入助手 "))
        self.assertEqual(first["evidenceCount"], 1)
        sent = prompt.call_args_list[0].args[1]
        self.assertTrue(sent.startswith(RUNTIME_PROMPT_ENVELOPE_PREFIX))
        sent_envelope = json.loads(sent.removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX))
        self.assertIn(
            "<rag-ime-user-query>\n最近我在做什么？\n</rag-ime-user-query>",
            sent_envelope["message"],
        )
        self.assertIn("控制中心使用连续 Pi Session", sent_envelope["message"])
        self.assertIn("任何写操作仍必须经过原生审批", sent_envelope["message"])
        self.assertIn('"queryFree":true', sent_envelope["transientContext"])
        sources = self.service.list_memory_sources({"sessionId": first["sessionId"]})["items"]
        self.assertEqual(
            [item["canonicalTextSha256"] for item in sources],
            [hashlib.sha256("最近我在做什么？".encode()).hexdigest()],
        )

    def test_input_method_deep_search_fails_before_creating_session_when_pi_is_unavailable(self) -> None:
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.service.deep_search(
                {
                    "query": "深度查找",
                    "privacyDisposition": "allowed",
                    "evidence": [],
                }
            )
        self.assertEqual(self.service.list_sessions()["items"], [])


if __name__ == "__main__":
    unittest.main()
