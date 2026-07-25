from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import Request, urlopen

from tests.runtime_capabilities import (
    requires_loopback_bind,
    requires_process_identity,
)

from rag_ime.agent_room_kernel import RoomKernelFenceError
from rag_ime.agent_room_skills import RoomSkillEpochRevoked
from rag_ime.agent_blocks import normalize_trusted_agent_blocks
from rag_ime.agent_room_capabilities import ToolAuthorizationError
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.agent_service import AgentService, _room_kernel_mode_from_environment
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_runtime import PiRuntimeConfig
from tests.test_pi_runtime_v2 import FAKE_HOST


class KernelRuntime:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.default_model_profile = "pi/test"
        self.dispatched: list[str] = []
        self.cancelled: list[tuple[str, str, int]] = []
        self.surface_state = "terminated"
        self.stopped = False

    def runtime_status(self):
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "status": "ready",
            "capabilities": {"runtimePrimitives": {"roomTypes": True}},
        }

    def dispatch_room(self, payload, *, message: str, lease_token: str):
        del message, lease_token
        self.dispatched.append(str(payload["dispatchId"]))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
            "capabilityEpoch": payload["capabilityEpoch"],
            "sessionId": payload["targetSessionId"],
            "turnId": "turn:kernel",
        }

    def cancel_room(self, *, session_id: str, root_id: str, generation: int):
        self.cancelled.append((session_id, root_id, generation))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "sessionId": session_id,
            "rootId": root_id,
            "generation": generation,
            "cancellationSurfaces": {surface: {
                "schemaVersion": "wisdom-weasel.runtime-surface-termination-receipt.v1",
                "surface": surface, "state": self.surface_state,
                "targetIds": [f"{surface}:test"] if self.surface_state == "unknown" else [],
            } for surface in (
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session")},
            "pendingTargets": ([
                "provider", "tool", "exec", "retry", "compaction",
                "branch_summary", "timer", "continuation", "session",
            ] if self.surface_state == "unknown" else []),
        }

    def stop(self):
        self.stopped = True


class KernelRuntimeFactory:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"
    default_model_profile = "pi/test"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.runtime = KernelRuntime(root)

    def create(self, *_args, **_kwargs):
        return self.runtime

    def apply_policy(self, _policy):
        return None

    def reconfigure(self, _config):
        return None


class RoomKernelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-kernel-service-")
        self.root = Path(self.tmp.name)
        self.factory = KernelRuntimeFactory(self.root)
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_factory=self.factory,
            room_kernel_mode="cohort",
            room_kernel_poll_seconds=60,
        )
        self.service.room_kernel_worker_loop.close()
        room = self.service.create_room(
            {
                "title": "Kernel cohort",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        self.room_id = str(room["id"])
        self.participant = room["participants"][1]
        self.session_id = str(self.participant["sessionId"])
        self._seed()

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def test_passive_service_does_not_start_room_runtime_worker(self) -> None:
        passive = AgentService(
            db_path=self.root / "passive.sqlite",
            runtime_factory=KernelRuntimeFactory(self.root / "passive"),
            room_kernel_mode="cohort",
            room_kernel_worker_enabled=False,
            room_kernel_poll_seconds=0.01,
        )
        try:
            self.assertFalse(passive.room_kernel_worker_loop.running)
            self.assertFalse(
                passive.room_kernel_commands.runtime_effects_enabled
            )
        finally:
            passive.close()

    def _seed(self) -> None:
        self.service.room_kernel.create_root(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:service",
                "roomId": self.room_id,
                "generation": 0,
                "state": "running",
                "owner": str(self.participant["id"]),
                "requirementAnchorRef": "requirement-anchor:service@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "createdAtMs": 1,
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        self.service.room_kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:service",
                "rootId": "root:service",
                "parentTaskId": None,
                "ownerParticipantId": str(self.participant["id"]),
                "assigneeParticipantId": str(self.participant["id"]),
                "objective": "Execute a bounded service test.",
                "expectedOutput": "A typed receipt.",
                "requirementItemIds": ["requirement:service"],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "active",
            },
            now_ms=2,
        )
    def _use_per_action_execution(self) -> None:
        session = self.service.sessions.get(self.session_id)
        self.service.sessions.set_runtime_policy(
            self.session_id,
            mode=str(session.get("mode") or "coordinator"),
            tool_profile_version=str(
                session.get("toolProfileVersion") or "control-center-v1"
            ),
            execution_mode="per_action",
            allowed_tools=(
                list(session.get("allowedTools") or [])
                if session.get("toolAllowlistMode") == "explicit"
                else None
            ),
            workspace_roots=list(session.get("workspaceRoots") or []),
        )

    def _create_work_item(
        self,
        suffix: str,
        *,
        objective: str,
        expected_output: str = "提交可复核的结果与证据。",
        acceptance_criteria: list[str] | None = None,
    ) -> dict[str, object]:
        return self.service.create_room_work_item(
            self.room_id,
            {
                "objective": objective,
                "expectedOutput": expected_output,
                "acceptanceCriteria": acceptance_criteria
                or ["结果满足目标并附带可复核证据"],
                "currentOwnerParticipantId": self.participant["id"],
                "clientMessageId": f"work:{suffix}",
            },
        )["workItem"]

    def test_unbound_room_message_stays_in_session_alignment(self) -> None:
        roots_before = self.service.room_kernel.root_ids(self.room_id)
        participant_id = str(self.participant["id"])

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:alignment"},
        ) as prompt:
            accepted = self.service.post_room_message(
                self.room_id,
                {
                    "message": "先和我对齐范围与验收，不要开工。",
                    "clientMessageId": "client:alignment",
                    "participantIds": [participant_id],
                },
            )

        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["executionOwner"], "session")
        self.assertEqual(accepted["phase"], "alignment")
        self.assertEqual(
            self.service.room_kernel.root_ids(self.room_id),
            roots_before,
        )
        request = prompt.call_args.args[1]
        self.assertEqual(request["_contextSource"], "room")
        self.assertIn("当前阶段：需求对齐", request["_transientContext"])
        self.assertIn("requirement-alignment", request["_transientContext"])
        self.assertNotIn("当前受管任务", request["_transientContext"])

    def test_kernel_execution_entry_rejects_an_unconfirmed_message(self) -> None:
        roots_before = self.service.room_kernel.root_ids(self.room_id)

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "requires a confirmed WorkItem",
        ):
            self.service.room_application.post_message(
                self.room_id,
                message="没有确认任务时不得从内部入口偷偷开工。",
                client_message_id="client:missing-work-item",
                requested_participant_ids=[str(self.participant["id"])],
                work_item_id="",
            )

        self.assertEqual(
            self.service.room_kernel.root_ids(self.room_id),
            roots_before,
        )
        self.assertEqual(self.factory.runtime.dispatched, [])

    def test_alignment_turn_is_mirrored_once_and_unregistered_late_events_stay_private(
        self,
    ) -> None:
        participant_id = str(self.participant["id"])
        session_turn_id = "turn:alignment-events"
        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": session_turn_id},
        ):
            accepted = self.service.post_room_message(
                self.room_id,
                {
                    "message": "先澄清验收，不要创建任务。",
                    "clientMessageId": "client:alignment-events",
                    "participantIds": [participant_id],
                },
            )

        room_turn_id = str(accepted["roomTurnId"])
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "message:alignment-events",
                    "sessionId": self.session_id,
                    "turnId": session_turn_id,
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [
                        {
                            "id": "text:alignment-events",
                            "type": "text",
                            "status": "completed",
                            "presentationKind": "markdown",
                            "data": {
                                "text": "需要确认交付物格式和验收命令。"
                            },
                        }
                    ],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 20,
                    "completedAtMs": 21,
                }
            },
            turn_id=session_turn_id,
        )
        self.service.events.publish(
            self.session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=session_turn_id,
        )

        projected = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=200,
            )
            if event["turnId"] == room_turn_id
        ]
        self.assertEqual(
            [event["eventType"] for event in projected],
            [
                "user_message",
                "route_decision",
                "participant_message",
                "turn_completed",
            ],
        )
        self.assertIn("需要确认交付物格式", str(projected[2]))

        count_before_late_event = len(
            self.service.rooms.list_events(self.room_id, limit=200)
        )
        self.service.events.publish(
            self.session_id,
            "text_delta",
            {"messageId": "late", "delta": "不应公开"},
            turn_id="turn:unregistered-late",
        )
        self.assertEqual(
            len(self.service.rooms.list_events(self.room_id, limit=200)),
            count_before_late_event,
        )

    def test_confirmed_work_item_uses_one_async_kernel_path(self) -> None:
        participant_id = str(self.participant["id"])
        client_message_id = "client:kernel-fanout"
        message = "请两位分别检查实现与测试，再汇总可验证结论。"
        work_item = self._create_work_item(
            "kernel-fanout",
            objective=message,
        )

        with patch.object(
            self.service,
            "prompt",
            side_effect=AssertionError("legacy synchronous prompt path must not run"),
        ):
            accepted = self.service.post_room_message(
                self.room_id,
                {
                    "message": message,
                    "clientMessageId": client_message_id,
                    "participantIds": [participant_id],
                    "workItemId": work_item["id"],
                },
            )

        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["status"], "queued")
        self.assertEqual(accepted["executionOwner"], "kernel")
        self.assertEqual(len(accepted["dispatches"]), 1)
        self.assertEqual(
            [event["eventType"] for event in accepted["timelineEvents"]],
            ["user_message", "route_decision"],
        )
        self.assertEqual(
            [
                event["payload"].get("summary")
                for event in accepted["timelineEvents"][1:]
            ],
            [f"{self.participant['displayName']} 已接手"],
        )
        self.assertEqual(self.factory.runtime.dispatched, [])
        self.assertEqual(
            {
                self.service.room_kernel.outbox(str(item["dispatchId"]))["state"]
                for item in accepted["dispatches"]
            },
            {"pending"},
        )
        self.assertEqual(
            self.service.room_requirements.original_bytes(
                str(accepted["requirementAnchor"]["anchorId"])
            ),
            message.encode("utf-8"),
        )
        snapshot = self.service.room_kernel_snapshot(self.room_id)
        user_posts = [
            post
            for post in snapshot["posts"]
            if post["publicationSource"]["kind"] == "user"
        ]
        self.assertEqual([post["content"] for post in user_posts], [message])

        replay = self.service.post_room_message(
            self.room_id,
            {
                "message": message,
                "clientMessageId": client_message_id,
                "participantIds": [participant_id],
                "workItemId": work_item["id"],
            },
        )
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay["rootId"], accepted["rootId"])
        self.assertEqual(replay["timelineEvents"], accepted["timelineEvents"])
        self.assertEqual(
            len(self.service.room_kernel_snapshot(self.room_id)["posts"]),
            len(snapshot["posts"]),
        )

    def test_agent_and_room_entry_race_is_rejected_before_creating_a_root(self) -> None:
        roots_before = self.service.room_kernel.root_ids(self.room_id)

        with self.service._direct_agent_entry(self.session_id):
            with self.assertRaisesRegex(
                ValueError,
                "currently busy",
            ):
                self.service.post_room_message(
                    self.room_id,
                    {
                        "message": "不要与 Agent 输入并发抢同一个 Session",
                        "clientMessageId": "client:mode-race",
                        "participantIds": [
                            str(self.participant["id"])
                        ],
                    },
                )

        self.assertEqual(
            self.service.room_kernel.root_ids(self.room_id),
            roots_before,
        )

    def test_pending_room_dispatch_rejects_direct_agent_prompt_cleanly(self) -> None:
        work_item = self._create_work_item(
            "room-owns-session",
            objective="Room 先占用这个 Session",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "Room 先占用这个 Session",
                "clientMessageId": "client:room-owns-session",
                "participantIds": [
                    str(self.participant["id"])
                ],
                "workItemId": work_item["id"],
            },
        )
        self.assertEqual(accepted["status"], "queued")

        with self.assertRaisesRegex(
            ValueError,
            "正在执行 Room 任务",
        ):
            self.service.prompt(
                self.session_id,
                {"message": "Agent 页面同时发送"},
            )

    def test_managed_runtime_projects_live_text_and_tools_without_auto_publishing_a_post(self) -> None:
        work_item = self._create_work_item(
            "live-projection",
            objective="检查实时投影",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "检查实时投影",
                "clientMessageId": "client:live-projection",
                "participantIds": [str(self.participant["id"])],
                "workItemId": work_item["id"],
            },
        )
        dispatch = accepted["dispatches"][0]
        self.service.room_kernel_worker.run_once()
        self.service.events.publish(
            self.session_id,
            "text_delta",
            {"messageId": "draft:live", "delta": "正在检查"},
            turn_id="turn:live",
        )
        self.service.events.publish(
            self.session_id,
            "tool_started",
            {"toolCallId": "tool:live", "toolName": "workspace_read"},
            turn_id="turn:live",
        )
        self.service.events.publish(
            self.session_id,
            "tool_finished",
            {
                "toolCallId": "tool:live",
                "toolName": "workspace_read",
                "result": {"summary": "已读取目标文件"},
                "isError": False,
            },
            turn_id="turn:live",
        )
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "draft:live",
                    "sessionId": self.session_id,
                    "turnId": "turn:live",
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 20,
                    "completedAtMs": 21,
                }
            },
            turn_id="turn:live",
        )

        public = [
            event
            for event in self.service.rooms.list_events(self.room_id)
            if event["turnId"] == accepted["rootId"]
        ]
        self.assertEqual(
            [event["eventType"] for event in public],
            [
                "user_message",
                "route_decision",
                "participant_delta",
                "participant_activity",
                "participant_activity",
                "participant_activity",
            ],
        )
        runtime_events = public[2:]
        self.assertTrue(
            all(
                event["payload"]["data"]["dispatchId"]
                == dispatch["dispatchId"]
                for event in runtime_events
            )
        )
        self.assertEqual(
            runtime_events[-1]["payload"]["data"]["status"],
            "draft_ready",
        )
        self.assertNotIn(
            "participant_message",
            [event["eventType"] for event in public],
        )
        self.assertNotIn("room_post", [event["eventType"] for event in public])

    def test_managed_runtime_failure_blocks_kernel_and_revokes_capability(self) -> None:
        work_item = self._create_work_item(
            "runtime-failure",
            objective="触发一次可审计的 Provider 失败",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "触发一次可审计的 Provider 失败",
                "clientMessageId": "client:runtime-failure",
                "participantIds": [str(self.participant["id"])],
                "workItemId": work_item["id"],
            },
        )
        dispatch = accepted["dispatches"][0]
        self.service.room_kernel_worker.run_once()
        dispatch_id = str(dispatch["dispatchId"])
        stored_before_failure = self.service.room_kernel.dispatch(dispatch_id)
        root_id = str(stored_before_failure["rootId"])
        task_id = str(stored_before_failure["taskId"])
        self.assertIsNotNone(
            self.service.room_capabilities.runtime_binding(self.session_id)
        )

        event = self.service.events.publish(
            self.session_id,
            "turn_failed",
            {
                "error": (
                    "POST https://secret.example/v1/responses failed "
                    "with token sk-never-publish"
                )
            },
            turn_id="turn:provider-failure",
            created_at_ms=30,
        )

        root = self.service.room_kernel.root(root_id)
        task = self.service.room_kernel.task(task_id)
        stored_dispatch = self.service.room_kernel.dispatch(dispatch_id)
        self.assertEqual(root["state"], "blocked")
        self.assertEqual(task["state"], "blocked")
        self.assertEqual(stored_dispatch["state"], "failed")
        self.assertEqual(
            self.service.room_kernel.outbox(dispatch_id)["state"],
            "dead_letter",
        )
        self.assertEqual(
            self.service.room_kernel.lease(dispatch_id)["state"],
            "completed",
        )
        self.assertEqual(
            self.service.room_kernel.abort_scope(dispatch_id)["state"],
            "failed",
        )
        self.assertIsNone(
            self.service.room_kernel.session_binding(self.session_id)
        )
        self.assertIsNone(
            self.service.room_capabilities.runtime_binding(self.session_id)
        )
        receipt = self.service.room_kernel.record_runtime_failure(
            dispatch_id,
            generation=int(stored_before_failure["generation"]),
            source_event_id=event.event_id,
            now_ms=30,
        )
        self.assertEqual(receipt["receiptKind"], "runtime_failed")
        self.assertEqual(receipt["status"], "applied")
        self.assertEqual(
            self.service.room_kernel.counts(root_id)["deadLetters"],
            1,
        )
        public = [
            item
            for item in self.service.rooms.list_events(self.room_id)
            if item["turnId"] == root_id
            and item["eventType"] == "turn_failed"
        ]
        self.assertEqual(len(public), 1)
        encoded = json.dumps(public[0], ensure_ascii=False)
        self.assertIn("任务已暂停等待恢复", encoded)
        self.assertNotIn("secret.example", encoded)
        self.assertNotIn("sk-never-publish", encoded)

    def test_public_projection_rejects_a_post_after_the_durable_root_fence(self) -> None:
        before = self.service.rooms.list_events(self.room_id, limit=500)
        with sqlite3.connect(self.root / "rag-ime.sqlite") as connection:
            connection.execute(
                """
                UPDATE room_kernel_roots
                SET state = 'completed', terminal_receipt_id = ?, updated_at_ms = ?
                WHERE root_id = ?
                """,
                ("receipt:terminal", 20, "root:service"),
            )
        late_post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:late-after-terminal",
            "roomId": self.room_id,
            "rootId": "root:service",
            "generation": 0,
            "taskId": "task:service",
            "dispatchId": "dispatch:late",
            "authorActorRef": str(self.participant["id"]),
            "kind": "result",
            "visibility": "room",
            "content": "迟到公开结果",
            "idempotencyKey": "post:late-after-terminal",
            "publicationSource": {
                "kind": "room_commit",
                "ref": "commit:late-after-terminal",
            },
            "createdAtMs": 21,
        }

        projected = self.service.room_public_timeline.publish_post(
            late_post,
            participant_id=str(self.participant["id"]),
            source_session_id=self.session_id,
        )

        self.assertIsNone(projected)
        self.assertEqual(
            self.service.rooms.list_events(self.room_id, limit=500),
            before,
        )

    def test_product_work_item_becomes_provider_only_kernel_task_context(self) -> None:
        objective = "检查 Room 增量上下文是否保持稳定前缀"
        expected_output = "给出前缀哈希与连续两轮缓存证据"
        criteria = ["旧前缀不得删除或重排", "不得把内部相关度注入模型"]
        work_item = self.service.create_room_work_item(
            self.room_id,
            {
                "objective": objective,
                "expectedOutput": expected_output,
                "acceptanceCriteria": criteria,
                "currentOwnerParticipantId": self.participant["id"],
                "clientMessageId": "work:kernel-context",
            },
        )["workItem"]

        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "开始",
                "clientMessageId": "client:kernel-work-context",
                "workItemId": work_item["id"],
            },
        )

        self.assertEqual(accepted["task"]["objective"], objective)
        self.assertEqual(accepted["task"]["expectedOutput"], expected_output)
        criterion_ids = accepted["task"]["acceptanceCriterionIds"]
        self.assertEqual(len(criterion_ids), len(criteria))
        self.assertTrue(all(str(value).startswith("acceptance:") for value in criterion_ids))
        entries = self.service.room_context_ledger.replay_root(
            str(accepted["rootId"])
        )
        work_entries = [
            entry for entry in entries if entry["entryKind"] == "work_item"
        ]
        self.assertEqual(len(work_entries), 1)
        work_context = json.loads(str(work_entries[0]["content"]))
        self.assertEqual(work_context["authority"], "task-only")
        self.assertEqual(work_context["objective"], objective)
        self.assertEqual(
            [
                value["statement"]
                for value in work_context["acceptanceCriteria"]
            ],
            criteria,
        )
        self.assertEqual(
            self.service.room_requirements.original_bytes(
                str(accepted["requirementAnchor"]["anchorId"])
            ),
            "开始".encode("utf-8"),
        )
        catalog = accepted["requirementCatalog"]
        self.assertEqual(catalog["anchorRefs"], [
            accepted["requirementAnchor"]["anchorId"]
        ])
        self.assertEqual(
            [
                value["statement"]
                for value in catalog["acceptanceCriteria"]
            ],
            criteria,
        )

    def test_compaction_recovers_room_requirements_and_exact_skill_tool_receipts(self) -> None:
        original = "原始需求：压缩后继续交付；原因：用户要求跨回合保持责任。"
        objective = "当前任务：验证 Room 压缩恢复"
        criterion = "验收：原始需求、阻塞和交接不得遗忘"
        blocker = "阻塞：等待正式安装环境"
        work_item = self.service.create_room_work_item(
            self.room_id,
            {
                "objective": objective,
                "expectedOutput": "给出可复核的恢复证据",
                "acceptanceCriteria": [criterion],
                "currentOwnerParticipantId": self.participant["id"],
                "clientMessageId": "work:compaction-recovery",
            },
        )["workItem"]
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": original,
                "clientMessageId": "client:compaction-recovery",
                "workItemId": work_item["id"],
            },
        )
        dispatch = self.service.room_kernel.dispatch(
            str(accepted["dispatches"][0]["dispatchId"])
        )
        catalog = accepted["requirementCatalog"]
        self.service.room_requirements.record_obstacle(
            obstacle_id="blocker:compaction",
            root_id=str(accepted["rootId"]),
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            obstacle_kind="blocker",
            statement=blocker,
            created_at_ms=10,
        )

        self.service.room_kernel_worker.run_once()
        binding = self.service.room_capabilities.runtime_binding(
            self.session_id
        )
        self.assertIsNotNone(binding)
        provider_payload = self.service.room_prompt_plans.provider_payload(
            str(binding["promptCompileReceiptId"])
        )
        static_prompt = str(provider_payload["stableSystemPrompt"])
        room_context = str(provider_payload["providerContext"])
        self.assertEqual(
            static_prompt.count('<execution-mode mode="workspace_managed">'),
            1,
        )
        self.assertEqual(static_prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(static_prompt.count("memory_capture"), 1)
        self.assertNotIn(str(self.root.resolve()), static_prompt)
        self.assertNotIn(str(self.root.resolve()), room_context)
        for expected in (original, objective, criterion, blocker):
            self.assertIn(expected, room_context)
        self.assertNotIn('"continuation"', room_context)
        initial_recovery = self.service._runtime_session_context(
            self.service.sessions.get(self.session_id)
        )["roomRecoveryContext"]
        for expected in (original, objective, criterion, blocker):
            self.assertEqual(initial_recovery.count(expected), 1)

        skill_id = "test-driven-implementation"
        catalog_revision = "c" * 64
        skill_receipt, _ = self.service.room_skill_receipts.pin_skill(
            receipt_id="skill:compaction-recovery",
            root_id=str(dispatch["rootId"]),
            task_id=str(dispatch["taskId"]),
            dispatch_id=str(dispatch["dispatchId"]),
            session_id=self.session_id,
            skill_id=skill_id,
            skill_hash=self.service.room_skill_policy.skill_hash(skill_id),
            catalog_revision=catalog_revision,
            load_reason="stage_required",
            capability_epoch=int(dispatch["capabilityEpoch"]),
            idempotency_key="compaction-recovery/implementation",
            created_at_ms=11,
        )
        tool_receipt = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:compaction-recovery:room_state",
                "toolName": "room_state",
                "createdAtMs": 12,
            }
        )["result"]

        refreshed = self.service.refresh_session_context(
            {
                "sessionId": self.session_id,
                "trigger": "compaction",
                "compactionEntryId": "compaction:recovery:1",
                "expectedContextEpoch": 1,
                "summary": "上一轮完成了上下文管线检查，尚未正式安装。",
                "recentMessages": [
                    {"role": "user", "text": "继续完成压缩恢复测试"}
                ],
                "roomSkillRecovery": {
                    "catalogRevision": catalog_revision,
                },
                "roomToolRecovery": {
                    "schemaVersion": "rag-ime.room-tool-recovery.v1",
                    "items": [
                        {
                            "name": "room_state",
                            "receiptId": tool_receipt["receiptId"],
                        }
                    ],
                },
            }
        )["result"]

        self.assertEqual(
            refreshed["roomContextRecovery"]["restoredFromReceiptId"],
            skill_receipt["receiptId"],
        )
        self.assertEqual(
            refreshed["roomToolRecovery"]["items"][0]["receiptId"],
            tool_receipt["receiptId"],
        )
        recovery_context = refreshed["roomRecoveryContext"]
        for expected in (original, objective, criterion, blocker):
            self.assertEqual(recovery_context.count(expected), 1)
        self.assertEqual(
            recovery_context.count(skill_receipt["receiptId"]),
            1,
        )
        self.assertEqual(
            recovery_context.count(tool_receipt["receiptId"]),
            1,
        )
        self.assertNotIn(original, refreshed["sessionContext"])
        self.assertNotIn(criterion, refreshed["sessionContext"])

        self.service.room_capabilities.revoke_runtime(
            self.session_id,
            capability_epoch=int(binding["capabilityEpoch"]) + 1,
            now_ms=13,
        )
        sealed_refresh = self.service.refresh_session_context(
            {
                "sessionId": self.session_id,
                "trigger": "compaction",
                "compactionEntryId": "compaction:recovery:2",
                "expectedContextEpoch": 2,
                "summary": "Room 已结算，只允许从封存能力记录恢复上下文。",
                "recentMessages": [
                    {"role": "user", "text": "继续核对封存后的压缩恢复"}
                ],
                "roomSkillRecovery": {
                    "catalogRevision": catalog_revision,
                },
                "roomToolRecovery": {
                    "schemaVersion": "rag-ime.room-tool-recovery.v1",
                    "items": [
                        {
                            "name": "room_state",
                            "receiptId": tool_receipt["receiptId"],
                        }
                    ],
                },
            }
        )["result"]
        sealed_context = sealed_refresh["roomRecoveryContext"]
        for expected in (original, objective, criterion, blocker):
            self.assertEqual(sealed_context.count(expected), 1)
        self.assertEqual(
            sealed_context.count(skill_receipt["receiptId"]),
            1,
        )
        self.assertEqual(
            sealed_context.count(tool_receipt["receiptId"]),
            1,
        )
        continued_context = self.service._runtime_session_context(
            self.service.sessions.get(self.session_id)
        )
        self.assertEqual(
            continued_context["roomCapability"]["status"],
            "revoked",
        )
        ordinary_session_context = continued_context["sessionContext"]
        for expected in (original, objective, criterion, blocker):
            self.assertEqual(
                ordinary_session_context.count(expected),
                1,
            )
        self.assertEqual(
            ordinary_session_context.count(skill_receipt["receiptId"]),
            1,
        )
        self.assertEqual(
            ordinary_session_context.count(tool_receipt["receiptId"]),
            1,
        )

    def _dispatch(
        self,
        dispatch_id: str = "dispatch:service",
        *,
        capability_epoch: int = 7,
        runtime_profile_revision: str = "runtime-profile:service-v1",
    ) -> dict[str, object]:
        return {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": dispatch_id,
            "rootId": "root:service",
            "taskId": "task:service",
            "parentDispatchId": None,
            "generation": 0,
            "hopCount": 0,
            "depth": 0,
            "budgetCost": 1,
            "targetSessionId": self.session_id,
            "targetParticipantId": str(self.participant["id"]),
            "triggerId": "trigger:service",
            "intentKind": "execute",
            "idempotencyKey": dispatch_id,
            "attempt": 0,
            "capabilityEpoch": capability_epoch,
            "runtimeProfileRevision": runtime_profile_revision,
            "state": "pending",
        }

    def _set_parent_acceptance(self, *criterion_ids: str) -> None:
        criteria = list(criterion_ids)
        with sqlite3.connect(self.service.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id = ?",
                ("task:service",),
            ).fetchone()
            assert row is not None
            task = json.loads(str(row[0]))
            task["acceptanceCriterionIds"] = criteria
            conn.execute(
                """UPDATE room_kernel_tasks
                   SET payload_json = ?
                   WHERE task_id = ?""",
                (
                    json.dumps(
                        task,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "task:service",
                ),
            )
            conn.execute(
                """UPDATE room_kernel_roots
                   SET acceptance_criteria_json = ?
                   WHERE root_id = ?""",
                (
                    json.dumps(
                        sorted(set(criteria)),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "root:service",
                ),
            )

    def _quality_gate_receipt(
        self,
        commit_id: str,
        dispatch_id: str,
        *,
        action: str,
        task_id: str = "task:service",
        criteria: tuple[str, ...] = (),
        coverage: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        created_at_ms: int,
    ) -> dict[str, object]:
        passed = set(coverage)
        verdict = (
            "ready_to_deliver"
            if action == "complete"
            else "not_ready"
        )
        return {
            "schemaVersion": "wisdom-weasel.room-quality-gate-receipt.v1",
            "receiptId": f"quality:{commit_id}",
            "rootId": "root:service",
            "taskId": task_id,
            "dispatchId": dispatch_id,
            "generation": 0,
            "originalRequestChecked": True,
            "verdict": verdict,
            "items": [
                {
                    "criterionId": criterion_id,
                    "status": (
                        "pass"
                        if criterion_id in passed
                        else "not_verified"
                    ),
                    "evidenceRefs": (
                        list(evidence_refs)
                        if criterion_id in passed
                        else []
                    ),
                }
                for criterion_id in criteria
            ],
            "residualRisks": (
                []
                if verdict == "ready_to_deliver"
                else ["continuation_pending"]
            ),
            "createdAtMs": created_at_ms,
        }

    @staticmethod
    def _quality_gate_proposal(
        *,
        verdict: str,
        criteria: tuple[str, ...] = (),
        coverage: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> dict[str, object]:
        passed = set(coverage)
        return {
            "originalRequestChecked": True,
            "verdict": verdict,
            "items": [
                {
                    "criterionId": criterion_id,
                    "status": (
                        "pass"
                        if criterion_id in passed
                        else "not_verified"
                    ),
                    "evidenceRefs": (
                        list(evidence_refs)
                        if criterion_id in passed
                        else []
                    ),
                }
                for criterion_id in criteria
            ],
            "residualRisks": (
                []
                if verdict == "ready_to_deliver"
                else ["continuation_pending"]
            ),
        }

    def _cancel_command(self, *, generation: int = 0) -> dict[str, object]:
        return {
            "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
            "commandId": f"command:cancel:{generation}",
            "rootId": "root:service",
            "roomId": self.room_id,
            "commandKind": "cancel_root",
            "targetKind": "root",
            "targetId": "root:service",
            "sourceKind": "control_center",
            "sourceId": "control-center:test",
            "idempotencyKey": f"cancel:service:{generation}",
            "generation": generation,
            "payload": {},
            "createdAtMs": 20,
        }

    def _room_tool_invocation(
        self, call_id: str, content: str, *, blocks: list[dict[str, object]] | None = None
    ) -> str:
        binding = self.service.room_capabilities.runtime_binding(self.session_id)
        assert binding is not None
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": f"load:{binding['manifestId']}:room_commit",
                "toolName": "room_commit",
                "createdAtMs": 29,
            }
        )["result"]
        arguments: dict[str, object] = {
            "decision": "wait",
            "summary": content,
            "evidence": [],
            "residualRisks": ["test fixture stages a non-terminal commit"],
            "waitingFor": "external",
            "resumeCondition": "test supplies the canonical Kernel commit",
        }
        if blocks is not None:
            arguments["blocks"] = blocks
        result = self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            arguments,
            tool_call_id=call_id,
            load_receipt_id=str(loaded["receiptId"]),
        )
        return str(result["invocationReceipt"]["receiptId"])

    def test_service_loads_one_to_four_room_tools_in_one_atomic_batch(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()

        result = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "loads": [
                    {
                        "receiptId": "load:batch:state",
                        "toolName": "room_state",
                    },
                    {
                        "receiptId": "load:batch:post",
                        "toolName": "room_post",
                    },
                ],
                "createdAtMs": 4,
            }
        )["result"]

        self.assertEqual(
            result["schemaVersion"],
            "wisdom-weasel.room-tool-load-batch-receipt.v1",
        )
        self.assertTrue(result["created"])
        self.assertEqual(
            [item["toolName"] for item in result["items"]],
            ["room_state", "room_post"],
        )

    def test_rich_post_crosses_real_settle_commit_snapshot_and_provider_journal(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        private = list(normalize_trusted_agent_blocks(
            [{
                "id": "table:delivery",
                "type": "table",
                "data": {
                    "title": "交付矩阵",
                    "columns": ["项目", "状态"],
                    "rows": [["raw-row-secret-9f31", "完成"]],
                },
            }],
            source_kind="pi_session_message",
            source_ref="session:private:message:1",
        ))
        proposal = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:rich",
            "roomId": self.room_id,
            "rootId": "root:service",
            "generation": 0,
            "dispatchId": "dispatch:service",
            "authorActorRef": str(self.participant["id"]),
            "kind": "result",
            "visibility": "room",
            "content": "结构化交付",
            "idempotencyKey": "post:rich",
            "publicationSource": {"kind": "room_commit", "ref": "commit:rich"},
            "createdAtMs": 30,
        }
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:rich",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:rich",
            "postProposal": {**proposal, "blocks": private},
            "qualityGateReceipt": self._quality_gate_receipt(
                "commit:rich",
                "dispatch:service",
                action="post",
                created_at_ms=30,
            ),
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 30,
        }
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:rich",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 30,
        }
        plain_invocation = self._room_tool_invocation("call:rich-private", "结构化交付")
        with self.assertRaisesRegex(RoomKernelFenceError, "authorized structured tool"):
            self.service.settle_room_kernel_dispatch(
                self.room_id,
                {"settleReceipt": settle, "commit": commit, "invocationReceiptId": plain_invocation},
                caller_authorized=True,
            )

        tool_blocks = [{
            "id": "table:delivery",
            "type": "table",
            "data": private[0]["data"],
        }]
        media_receipt = self.service.media.import_bytes(
            session_id=self.session_id,
            data=b"# Managed Room delivery\n",
            mime_type="text/markdown",
            file_name="delivery.md",
            origin="tool_result",
            origin_tool="workspace_patch",
            origin_receipt_id="approval:rich",
        )
        media_id = str(media_receipt["mediaId"])
        file_block = {
            "id": "file:delivery",
            "type": "file",
            "data": {
                "mediaId": media_id,
                "sessionId": self.session_id,
                "fileName": media_receipt["fileName"],
                "mimeType": media_receipt["mimeType"],
                "byteSize": media_receipt["byteSize"],
                "sha256": media_receipt["sha256"],
                "receiptUrl": (
                    f"/api/agent/media/{quote(media_id, safe='')}/content"
                    f"?sessionId={quote(self.session_id, safe='')}"
                ),
            },
        }
        with self.assertRaisesRegex(RoomKernelFenceError, "another Session"):
            self._room_tool_invocation(
                "call:rich-forged-file",
                "结构化交付",
                blocks=[
                    {
                        **file_block,
                        "data": {**file_block["data"], "sessionId": "session:other"},
                    }
                ],
            )
        tool_blocks.append(file_block)
        invocation = self._room_tool_invocation(
            "call:rich-structured", "结构化交付", blocks=tool_blocks
        )
        commit["postProposal"] = proposal
        result = self.service.settle_room_kernel_dispatch(
            self.room_id,
            {"settleReceipt": settle, "commit": commit, "invocationReceiptId": invocation},
            caller_authorized=True,
        )

        published = result["post"]["blocks"][0]
        self.assertEqual(published["source"], {"kind": "room_commit", "ref": "commit:rich"})
        self.assertEqual(published["visibility"], "room_post")
        self.assertEqual(published["generation"], 0)
        self.assertTrue(str(published["ref"]).startswith("block:"))
        self.assertEqual(published["digest"], private[0]["digest"])
        published_file = result["post"]["blocks"][1]
        self.assertEqual(published_file["type"], "file")
        self.assertEqual(published_file["data"]["mediaId"], media_id)
        preview = self.service.file_previews.read(
            media_id,
            session_id=self.session_id,
            expected_sha256=str(media_receipt["sha256"]),
        )
        self.assertEqual(preview["descriptor"]["previewKind"], "markdown")
        snapshot_block = self.service.room_kernel_snapshot(self.room_id)["posts"][0]["blocks"][0]
        self.assertEqual(snapshot_block["data"]["rows"][0][0], "raw-row-secret-9f31")
        self.assertEqual(snapshot_block, published)

        self.service.room_kernel.enqueue_dispatch(
            self._dispatch("dispatch:after-rich", capability_epoch=8), now_ms=31
        )
        self.service.room_kernel_worker.run_once()
        projection = self.service.room_projection_journals.projection(
            "room-journal:dispatch:after-rich", expected_generation=0
        )
        provider_text = projection["projectionBytes"].decode("utf-8")
        self.assertIn("表格：交付矩阵，1 行 2 列", provider_text)
        self.assertIn(str(published["ref"]), provider_text)
        self.assertNotIn("raw-row-secret-9f31", provider_text)
        self.assertNotIn('"rows"', provider_text)

    def test_provider_journal_bounds_fifty_public_posts_without_losing_current_task(self) -> None:
        rich = list(normalize_trusted_agent_blocks(
            [{
                "id": "table:history",
                "type": "table",
                "data": {
                    "title": "历史矩阵",
                    "columns": ["键"],
                    "rows": [["raw-history-secret-7ab2"]],
                },
            }],
            source_kind="user",
            source_ref="user:test",
            visibility="room_post",
            generation=0,
        ))
        for index in range(55):
            post: dict[str, object] = {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": f"post:history:{index}",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "authorActorRef": "user:test",
                "kind": "message",
                "visibility": "room",
                "content": f"公开历史 {index}",
                "idempotencyKey": f"post:history:{index}",
                "publicationSource": {"kind": "user", "ref": "user:test"},
                "createdAtMs": 100 + index,
            }
            if index == 54:
                post["blocks"] = rich
            self.service.room_context_ledger.publish_post(post)

        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=200)
        self.service.room_kernel_worker.run_once()
        projection = self.service.room_projection_journals.projection(
            "room-journal:dispatch:service", expected_generation=0
        )
        provider_text = projection["projectionBytes"].decode("utf-8")

        self.assertLessEqual(len(projection["pendingTail"]), 24)
        self.assertLessEqual(len(projection["projectionBytes"]), 64 * 1024)
        self.assertIn("Execute a bounded service test.", provider_text)
        self.assertIn("requirement:service", provider_text)
        self.assertNotIn("wisdom-weasel.room-context-omission.v1", provider_text)
        self.assertIn("表格：历史矩阵，1 行 1 列", provider_text)
        self.assertNotIn("raw-history-secret-7ab2", provider_text)
        self.assertNotIn('"rows"', provider_text)
        omission_audits = [
            json.loads(str(entry["content"]))
            for entry in self.service.room_context_ledger.replay_root("root:service")
            if entry["entryKind"] == "recovery_packet"
            and "room-context-omission" in str(entry["content"])
        ]
        self.assertEqual(len(omission_audits), 1)
        self.assertGreater(omission_audits[0]["omittedEntryCount"], 0)

    def test_provider_projection_keeps_original_once_and_audits_duplicate_post(self) -> None:
        original = "同一条用户原始要求在 Provider 上下文中只出现一次。"
        self.service.room_requirements.append_anchor(
            anchor_id="requirement-anchor:service",
            root_id="root:service",
            original_content=original,
            created_by="user:local",
            provenance={"roomEventId": "event:dedupe"},
            created_at_ms=10,
        )
        self.service.room_requirements.revise_catalog(
            catalog_revision_id="catalog:dedupe",
            root_id="root:service",
            expected_current_revision=0,
            anchor_refs=("requirement-anchor:service",),
            items=(
                {
                    "itemId": "requirement:service",
                    "kind": "explicit_user_requirement",
                    "statement": original,
                    "origin": "derived_catalog",
                    "state": "active",
                    "sourceSpans": [
                        {
                            "anchorId": "requirement-anchor:service",
                            "startByte": 0,
                            "endByte": len(original.encode("utf-8")),
                        }
                    ],
                    "supersedes": [],
                    "ambiguity": "",
                    "confirmation": "user-confirmed",
                },
            ),
            acceptance_criteria=(
                {
                    "criterionId": "criterion:dedupe",
                    "itemId": "requirement:service",
                    "acceptanceCriterionFullNameZh": "上下文去重验收条件",
                    "criterionKind": "requirement",
                    "expectedReceiptTypes": ["test"],
                    "statement": "原文只投影一次",
                },
            ),
            change_reason="建立可修订需求目录",
            provenance={"derivedFrom": ["requirement-anchor:service"]},
            created_by="agent:requirements",
            created_at_ms=11,
        )
        self.service.room_context_ledger.publish_post(
            {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:dedupe",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "taskId": "task:service",
                "dispatchId": "dispatch:dedupe",
                "authorActorRef": "user:local",
                "kind": "message",
                "visibility": "room",
                "content": original,
                "idempotencyKey": "post:dedupe",
                "publicationSource": {"kind": "user", "ref": "user:local"},
                "createdAtMs": 12,
            }
        )
        self.service.room_kernel.enqueue_dispatch(
            self._dispatch("dispatch:dedupe"),
            now_ms=13,
        )

        self.service.room_kernel_worker.run_once()

        projection = self.service.room_projection_journals.projection(
            "room-journal:dispatch:dedupe",
            expected_generation=0,
        )
        provider_text = projection["projectionBytes"].decode("utf-8")
        self.assertEqual(provider_text.count(original), 1)
        self.assertIn('"statementSource":"original[0]"', provider_text)
        self.assertNotIn('<room-fact kind="room_post">' + original, provider_text)
        audits = [
            json.loads(str(entry["content"]))
            for entry in self.service.room_context_ledger.replay_root("root:service")
            if entry["entryKind"] == "recovery_packet"
            and "room-context-omission" in str(entry["content"])
        ]
        self.assertEqual(audits[-1]["deduplicatedEntryCount"], 1)
        self.assertGreater(audits[-1]["deduplicatedContentBytes"], 0)

    def test_command_requires_server_authorization_and_current_room_generation(self) -> None:
        with self.assertRaises(PermissionError):
            self.service.apply_room_kernel_command(self.room_id, self._cancel_command())
        with self.assertRaisesRegex(RoomKernelFenceError, "generation is stale"):
            self.service.apply_room_kernel_command(
                self.room_id,
                self._cancel_command(generation=1),
                caller_authorized=True,
            )

        receipt = self.service.apply_room_kernel_command(
            self.room_id, self._cancel_command(), caller_authorized=True
        )

        self.assertEqual(receipt["receiptKind"], "root_cancelled")
        self.assertEqual(receipt["generation"], 1)
        snapshot = self.service.room_kernel_snapshot(self.room_id)
        self.assertEqual(snapshot["roots"][0]["state"], "cancelled")
        self.assertTrue(any(item["receiptId"] == receipt["receiptId"] for item in snapshot["receipts"]))

    def test_environment_cohort_requires_the_named_test_opt_in(self) -> None:
        with patch.dict("os.environ", {"RAG_IME_ROOM_KERNEL_MODE": "cohort"}, clear=True):
            self.assertEqual(_room_kernel_mode_from_environment(), "shadow")
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_ROOM_KERNEL_MODE": "cohort",
                "RAG_IME_ROOM_KERNEL_COHORT_ID": "room-v2-test",
            },
            clear=True,
        ):
            self.assertEqual(_room_kernel_mode_from_environment(), "cohort")

    def test_environment_accepts_kernel_only_without_a_cohort_gate(self) -> None:
        with patch.dict(
            "os.environ",
            {"RAG_IME_ROOM_KERNEL_MODE": "kernel_only"},
            clear=True,
        ):
            self.assertEqual(_room_kernel_mode_from_environment(), "kernel_only")

    def test_product_create_dispatch_and_finalize_use_command_bus(self) -> None:
        root_id = "root:product-route"
        task_id = "task:product-route"
        created = self.service.create_room_kernel_root(
            self.room_id,
            {
                "rootExecution": {
                    "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                    "rootId": root_id,
                    "roomId": self.room_id,
                    "generation": 0,
                    "state": "running",
                    "owner": str(self.participant["id"]),
                    "requirementAnchorRef": "requirement-anchor:product@sha256:test",
                    "createdByActorRef": "user:local",
                    "terminalReceiptId": None,
                    "activeProfileRef": None,
                    "budgetPolicyRef": "room-budget:test-v1",
                    "createdAtMs": int(time.time() * 1000),
                },
                "task": {
                    "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                    "taskId": task_id,
                    "rootId": root_id,
                    "parentTaskId": None,
                    "ownerParticipantId": str(self.participant["id"]),
                    "assigneeParticipantId": str(self.participant["id"]),
                    "objective": "Exercise the product Kernel API.",
                    "expectedOutput": "A typed receipt.",
                    "requirementItemIds": ["requirement:product"],
                    "acceptanceCriterionIds": [],
                    "revision": 0,
                    "state": "active",
                },
                "budget": 10,
                "maxHops": 3,
                "maxDepth": 2,
            },
            caller_authorized=True,
        )
        self.assertEqual(created["task"]["rootId"], created["root"]["rootId"])
        envelope = {**self._dispatch("dispatch:product-route"), "rootId": root_id, "taskId": task_id}
        dispatched = self.service.dispatch_room_kernel(
            self.room_id, envelope, caller_authorized=True
        )
        self.assertTrue(dispatched["created"])
        final = self.service.finalize_room_kernel_route(
            self.room_id, {"rootId": root_id}, caller_authorized=True
        )
        self.assertEqual(final["receipt"]["status"], "rejected")

    def test_runtime_failure_and_user_correction_are_automatic_incidents(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)

        def fail_dispatch(*_args, **_kwargs):
            raise ConnectionError("Pi host exited")

        self.factory.runtime.dispatch_room = fail_dispatch
        with self.assertRaisesRegex(ConnectionError, "Pi host exited"):
            self.service.room_kernel_worker.run_once()
        with sqlite3.connect(self.service.db_path) as conn:
            incident = conn.execute(
                "SELECT taxonomy,evidence_refs_json FROM room_v2_incidents WHERE taxonomy='tool_failure'"
            ).fetchone()
        self.assertEqual(incident[0], "tool_failure")
        self.assertTrue(json.loads(incident[1]))

        self.service.observe_room_user_correction(
            room_id=self.room_id,
            root_id="root:service",
            dispatch_id="dispatch:service",
            correction_ref="room-post:user-correction",
            caller_authorized=True,
            now_ms=5,
        )
        with sqlite3.connect(self.service.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM room_v2_incidents WHERE taxonomy='user_correction'"
                ).fetchone()[0],
                1,
            )

    def test_durable_managed_cancel_reaches_kernel_and_pi_abort_once(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                """INSERT INTO room_v2_managed_cancel_outbox(
                   cancel_id,source_kind,source_receipt_id,root_id,state,created_at_ms,updated_at_ms)
                   VALUES ('cancel:test','profile_revoke','profile-receipt:test','root:service','pending',4,4)"""
            )
        self.service._run_room_learning_maintenance()
        self.assertEqual(self.service.room_kernel.root("root:service")["state"], "cancelled")
        self.assertEqual(len(self.factory.runtime.cancelled), 1)
        with sqlite3.connect(self.service.db_path) as conn:
            state, kernel_receipt_id = conn.execute(
                "SELECT state,kernel_receipt_id FROM room_v2_managed_cancel_outbox WHERE cancel_id='cancel:test'"
            ).fetchone()
        self.assertEqual(state, "applied")
        self.assertTrue(kernel_receipt_id)
        self.service._run_room_learning_maintenance()
        self.assertEqual(len(self.factory.runtime.cancelled), 1)

    def test_cancelled_root_rejects_late_rich_sidecar_writeback(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        self.service.room_kernel_worker.cancel_root("root:service")
        blocks = list(normalize_trusted_agent_blocks(
            [{"id": "status:late", "type": "status", "data": {"title": "过期结果"}}],
            source_kind="pi_runtime_event",
            source_ref=f"{self.session_id}:message:late",
        ))
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "message:late",
                    "sessionId": self.session_id,
                    "turnId": "turn:late",
                    "role": "assistant",
                    "status": "completed",
                    "blocks": blocks,
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 5,
                }
            },
            turn_id="turn:late",
        )
        self.assertEqual(
            self.service.agent_blocks.blocks_for_message(self.session_id, "message:late"),
            [],
        )

    def test_unknown_cancel_snapshot_stays_nonterminal_with_pending_targets(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        self.factory.runtime.surface_state = "unknown"
        self.service.room_kernel_worker.cancel_root("root:service")

        snapshot = self.service.room_kernel_snapshot(self.room_id)
        projected_root = next(item for item in snapshot["roots"] if item["rootId"] == "root:service")
        self.assertEqual(projected_root["state"], "cancelled_with_unknowns")
        self.assertIsNone(projected_root["terminalReceiptId"])
        self.assertEqual(len(snapshot["pendingTargets"]), 9)
        self.assertEqual({item["state"] for item in snapshot["pendingTargets"]}, {"unknown"})
        root_events = [
            event
            for event in self.service.rooms.list_events(self.room_id)
            if event["turnId"] == "root:service"
            and event["eventType"] in {"turn_completed", "turn_failed"}
        ]
        self.assertEqual(root_events, [])

    def test_knowledge_caller_is_built_from_authenticated_live_participant_binding(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        captured = {}

        def search(**kwargs):
            captured.update(kwargs)
            caller = kwargs["caller"]
            return {"retrievalReceiptId": kwargs["retrieval_receipt_id"], "groups": [], "bindingId": caller.binding_id if caller else None}

        self.service.knowledge_promotion.search = search
        result = self.service.room_knowledge_search(
            {"query": "bounded fact", "retrievalReceiptId": "retrieval:service"},
            authenticated_session_id=self.session_id,
        )
        self.assertEqual(result["bindingId"], "participant-binding:dispatch:service")
        self.assertEqual(captured["caller"].room_id, self.room_id)
        with self.assertRaisesRegex(PermissionError, "server-derived"):
            self.service.room_knowledge_search(
                {"query": "bounded fact", "scopeId": self.room_id},
                authenticated_session_id=self.session_id,
            )
        ordinary = self.service.room_knowledge_search(
            {"query": "bounded fact", "retrievalReceiptId": "retrieval:ordinary"},
            authenticated_session_id="ordinary-session-with-no-room",
        )
        self.assertIsNone(ordinary["bindingId"])

        memory_context = self.service.memory_context_application
        memory_context.remember_query(self.session_id, "stale query")
        memory_context.replace_recent_messages(
            self.session_id,
            [{"role": "user", "content": "stale"}],
        )
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                """INSERT INTO room_v2_knowledge_cache_tombstones(
                   tombstone_id,scope_key,knowledge_epoch,session_id,reason,created_at_ms)
                   VALUES ('cache:test','room_public:room:1',2,?,'revoke',10)""",
                (self.session_id,),
            )
        self.assertEqual(self.service._consume_room_knowledge_cache_tombstones(), 1)
        self.assertEqual(memory_context.recall_query(self.session_id), "")
        self.assertEqual(memory_context.recent_messages(self.session_id), [])
        with sqlite3.connect(self.service.db_path) as conn:
            self.assertGreater(conn.execute("SELECT consumed_at_ms FROM room_v2_knowledge_cache_tombstones WHERE tombstone_id='cache:test'").fetchone()[0], 0)

    def test_settle_bridge_requires_matching_settle_and_explicit_post(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:service",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:service",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:service",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "taskId": "task:service",
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "This text was explicitly committed.",
                "idempotencyKey": "post:service",
                "publicationSource": {"kind": "room_commit", "ref": "commit:service"},
                "createdAtMs": 30,
            },
            "qualityGateReceipt": self._quality_gate_receipt(
                "commit:service",
                "dispatch:service",
                action="post",
                created_at_ms=30,
            ),
            "evidenceRefs": ["test:service"],
            "requirementCoverage": [],
            "createdAtMs": 30,
        }
        bad_settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:service",
            "eventKind": "message_completed",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 30,
        }
        with self.assertRaisesRegex(RoomKernelFenceError, "agent_settled"):
            self.service.settle_room_kernel_dispatch(
                self.room_id,
                {"settleReceipt": bad_settle, "commit": commit},
                caller_authorized=True,
            )
        settle = {**bad_settle, "eventKind": "agent_settled"}
        invocation_receipt_id = self._room_tool_invocation(
            "call:settle-service", "This text was explicitly committed."
        )

        result = self.service.settle_room_kernel_dispatch(
            self.room_id,
            {"settleReceipt": settle, "commit": commit, "invocationReceiptId": invocation_receipt_id},
            caller_authorized=True,
        )

        self.assertEqual(result["receipt"]["status"], "applied")
        snapshot = self.service.room_kernel_snapshot(self.room_id)
        self.assertEqual([post["postId"] for post in snapshot["posts"]], ["post:service"])
        public_posts = [
            event
            for event in self.service.rooms.list_events(self.room_id)
            if event["eventType"] == "room_post"
        ]
        self.assertEqual(len(public_posts), 1)
        self.assertEqual(
            public_posts[0]["payload"]["post"]["postId"],
            "post:service",
        )
        self.assertNotIn("This text", str(snapshot["sessions"]))
        self.assertEqual(
            snapshot["requirementsByRootId"]["root:service"]["projectionSource"],
            "canonical_read_projection",
        )

    def test_settle_rejects_invalid_post_before_persisting_commit(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:invalid-post",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:invalid-post",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:wrong-room",
                "roomId": "room:wrong",
                "rootId": "root:service",
                "generation": 0,
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "Must not be committed.",
                "idempotencyKey": "post:wrong-room",
                "publicationSource": {"kind": "room_commit", "ref": "commit:invalid-post"},
                "createdAtMs": 31,
            },
            "qualityGateReceipt": self._quality_gate_receipt(
                "commit:invalid-post",
                "dispatch:service",
                action="post",
                created_at_ms=31,
            ),
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 31,
        }
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:invalid-post",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 31,
        }
        invocation_receipt_id = self._room_tool_invocation(
            "call:invalid-post", "Must not be committed."
        )

        with self.assertRaisesRegex(RoomKernelFenceError, "RoomPost proposal"):
            self.service.settle_room_kernel_dispatch(
                self.room_id,
                {"settleReceipt": settle, "commit": commit, "invocationReceiptId": invocation_receipt_id},
                caller_authorized=True,
            )

        self.assertEqual(self.service.room_kernel.dispatch("dispatch:service")["state"], "running")
        self.assertEqual(self.service.room_kernel_snapshot(self.room_id)["posts"], [])

    def test_agent_settled_without_commit_retries_then_blocks_deterministically(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch("dispatch:no-commit"), now_ms=3)
        self.service.room_kernel_worker.run_once()
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:no-commit",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:no-commit",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 31,
        }

        results = [
            self.service.settle_room_kernel_dispatch(
                self.room_id,
                {
                    "settleReceipt": {
                        **settle,
                        "settleReceiptId": f"settle:no-commit:{attempt}",
                    }
                },
                caller_authorized=True,
            )
            for attempt in range(1, 4)
        ]

        self.assertTrue(results[0]["retryRequired"])
        self.assertTrue(results[2]["blocked"])
        self.assertEqual(self.service.room_kernel.root("root:service")["state"], "blocked")
        self.assertIsNone(self.service.room_capabilities.runtime_binding(self.session_id))

    def test_canonical_governance_read_models_are_available_without_mutation(self) -> None:
        governance = self.service.governance_read_model()
        knowledge = self.service.knowledge_governance_read_model()
        self.assertEqual(governance["schemaVersion"], "wisdom-weasel.governance-read-model.v1")
        self.assertEqual(knowledge["schemaVersion"], "wisdom-weasel.knowledge-governance-read-model.v1")
        self.assertIn("activePointers", governance["governance"])
        self.assertIn("promotionCandidates", knowledge["knowledge"])

    def test_kernel_bound_completion_projects_only_public_lifecycle_metadata(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        before = len(self.service.rooms.list_events(self.room_id, limit=200))
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "private reasoning"}]}},
            turn_id="turn:private",
        )
        after = self.service.rooms.list_events(self.room_id, limit=200)

        self.assertEqual(len(after), before + 1)
        projected = after[-1]
        self.assertEqual(projected["eventType"], "participant_activity")
        self.assertEqual(projected["payload"]["data"]["status"], "draft_ready")
        self.assertNotIn("private reasoning", str(projected))
        self.assertNotIn("private reasoning", str(self.service.room_kernel_snapshot(self.room_id)))

        self.service.events.publish(
            self.session_id,
            "message_completed",
            {
                "message": {
                    "role": "assistant",
                    "status": "failed",
                    "blocks": [
                        {
                            "type": "error",
                            "status": "failed",
                            "data": {
                                "message": "private upstream endpoint and credential",
                            },
                        }
                    ],
                }
            },
            turn_id="turn:provider-error",
        )
        failed = self.service.rooms.list_events(self.room_id, limit=200)[-1]
        failed_data = failed["payload"]["data"]
        self.assertEqual(failed["eventType"], "participant_activity")
        self.assertEqual(failed_data["status"], "provider_error")
        self.assertEqual(
            failed_data["summary"],
            "模型响应中断，正在按运行策略处理",
        )
        self.assertTrue(failed_data["isError"])
        self.assertTrue(str(failed_data["requestId"]).endswith(":provider"))
        self.assertNotIn("private upstream", str(failed))

        self.service.events.publish(
            self.session_id,
            "turn_failed",
            {
                "error": "Pi Runtime Host exited with code -9",
                "failureKind": "runtime_host_exit",
                "exitCode": -9,
            },
            turn_id="turn:runtime-host-exit",
        )
        runtime_failed = self.service.rooms.list_events(
            self.room_id,
            limit=200,
        )[-1]
        runtime_failed_data = runtime_failed["payload"]["data"]
        self.assertEqual(
            runtime_failed_data["status"],
            "runtime_error",
        )
        self.assertEqual(
            runtime_failed_data["summary"],
            "Agent 运行时中断，任务已暂停等待恢复",
        )
        self.assertTrue(
            str(runtime_failed_data["requestId"]).endswith(
                ":runtime"
            )
        )
        self.assertNotIn("code -9", str(runtime_failed))

    def test_worker_lifecycle_is_stoppable(self) -> None:
        self.service.room_kernel_worker_loop.start()
        self.assertTrue(self.service.room_kernel_worker_loop.running)
        self.service.room_kernel_worker_loop.close()
        self.assertFalse(self.service.room_kernel_worker_loop.running)

    def test_capability_manifest_exposes_only_one_canonical_kernel_path(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        tools = (
            "room_state",
            "room_post",
            "room_commit",
            "room_collaborate",
        )
        bound = self.service.room_capabilities.manifest_for_runtime(self.session_id)
        self.assertIsNotNone(bound)
        self.assertEqual(bound[0]["dispatchId"], "dispatch:service")
        self.assertEqual(bound[1]["promptCompileReceiptId"], "prompt-compile:dispatch:service")
        runtime_tools = self.service._runtime_tool_manifest({"id": self.session_id})
        self.assertEqual(
            [item["name"] for item in runtime_tools],
            list(tools),
        )
        for item in runtime_tools:
            self.assertEqual(
                set(item),
                {
                    "name", "description", "parameters", "when", "notFor",
                    "input", "output", "does", "profile", "risk",
                },
            )
            for key in ("when", "notFor", "input", "output", "does"):
                self.assertTrue(item[key], f"{item['name']}.{key}")
        loaded = self.service.room_capability_tool_load(
            {"sessionId": self.session_id, "receiptId": "load:service", "toolName": "room_post", "createdAtMs": 5}
        )["result"]
        with self.assertRaisesRegex(
            ValueError,
            "room_state/room_collaborate/room_post/room_commit",
        ):
            self.service.execute_room_capability_tool(
                self.session_id,
                "room_send",
                {"content": "deliver"},
                tool_call_id="call:legacy-service",
                load_receipt_id=str(loaded["receiptId"]),
            )
        canonical = self.service.execute_room_capability_tool(
            self.session_id,
            "room_post",
            {"kind": "progress", "content": "deliver"},
            tool_call_id="call:service", load_receipt_id=str(loaded["receiptId"]),
        )
        self.assertTrue(canonical["result"]["published"])
        self.assertTrue(canonical["result"]["currentResponsibilityContinues"])
        self.assertEqual(canonical["executionReceipt"]["status"], "applied")
        self.assertEqual(
            [
                item["content"]
                for item in self.service.room_context_ledger.recent_posts(
                    "root:service"
                )
            ],
            ["deliver"],
        )
        self.assertIsNone(self.service.execute_room_capability_tool(
            "ordinary-session",
            "room_post",
            {"kind": "notice", "content": "ordinary"},
            tool_call_id="call:ordinary",
            load_receipt_id="",
        ))
        self.service.apply_room_kernel_command(
            self.room_id,
            self._cancel_command(),
            caller_authorized=True,
        )
        with self.assertRaises((RoomKernelFenceError, ToolAuthorizationError)):
            self.service.execute_room_capability_tool(
                self.session_id,
                "room_post",
                {"kind": "notice", "content": "late delivery"},
                tool_call_id="call:after-cancel",
                load_receipt_id=str(loaded["receiptId"]),
            )
        self.assertEqual(
            self.service.room_capabilities.runtime_binding(
                self.session_id,
                active_only=False,
            )["state"],
            "revoked",
        )
        with self.assertRaises(ToolAuthorizationError):
            self.service.room_capabilities.authorize_runtime_invocation(
                session_id=self.session_id,
                receipt_id="invoke:revoked",
                invocation_key="call:revoked",
                load_receipt_id=str(loaded["receiptId"]),
                tool_name="room_post",
                arguments={"kind": "notice", "content": "no"},
                created_at_ms=7,
            )

    def test_room_state_returns_bounded_participant_directory_for_handoff(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-state-directory",
                "toolName": "room_state",
                "createdAtMs": 5,
            }
        )["result"]

        response = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:room-state-directory",
            load_receipt_id=str(loaded["receiptId"]),
        )
        state = response["result"]

        self.assertEqual(
            state["schemaVersion"],
            "wisdom-weasel.room-state-tool.v1",
        )
        self.assertEqual(
            state["evidenceRef"],
            response["executionReceipt"]["executionReceiptId"],
        )
        self.assertIn(
            state["evidenceRef"],
            self.service.room_capabilities.runtime_evidence_refs(
                session_id=self.session_id,
                dispatch_id="dispatch:service",
            ),
        )
        expected = {
            f"P{index}": {
                "displayName": str(item["displayName"]),
                "capabilitySummary": str(item["collaborationRole"]),
            }
            for index, item in enumerate(
                (
                    item
                    for item in self.service.rooms.get(self.room_id)["participants"]
                    if item["status"] == "active"
                ),
                start=1,
            )
            if item["status"] == "active"
        }
        actual = {
            str(item["participantRef"]): {
                "displayName": str(item["displayName"]),
                "capabilitySummary": str(item["capabilitySummary"]),
            }
            for item in state["participants"]
        }
        self.assertEqual(actual, expected)
        current = [
            item
            for item in state["participants"]
            if item["availability"] == "current"
        ]
        current_ref = next(
            ref
            for ref, item in expected.items()
            if item["displayName"] == self.participant["displayName"]
        )
        self.assertEqual(
            [item["participantRef"] for item in current],
            [current_ref],
        )
        self.assertFalse(state["unchanged"])
        repeated = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:room-state-directory-repeat",
            load_receipt_id=str(loaded["receiptId"]),
        )["result"]
        self.assertTrue(repeated["unchanged"])
        serialized = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("requirementsByRootId", serialized)
        self.assertNotIn("receiptAssessments", serialized)
        self.assertNotIn("sessionId", serialized)
        self.assertNotIn("participantId", serialized)
        self.assertLess(len(serialized.encode("utf-8")), 10_000)

    def test_room_collaborate_enqueues_child_task_without_settling_parent(self) -> None:
        self._set_parent_acceptance("criterion:service")
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        room = self.service.rooms.get(self.room_id)
        target = next(
            item
            for item in room["participants"]
            if item["status"] == "active" and item["id"] != self.participant["id"]
        )
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-collaborate",
                "toolName": "room_collaborate",
                "createdAtMs": 5,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:room-state-for-collaboration",
            load_receipt_id=str(
                self.service.room_capability_tool_load(
                    {
                        "sessionId": self.session_id,
                        "receiptId": "load:state-for-collaboration",
                        "toolName": "room_state",
                        "createdAtMs": 5,
                    }
                )["result"]["receiptId"]
            ),
        )["result"]
        target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if item["displayName"] == target["displayName"]
        )
        arguments = {
            "targetParticipantRef": target_ref,
            "objective": "独立检查边界条件并回报结论",
            "expectedOutput": "一条带证据的边界检查结论",
            "intent": "review",
            "acceptance": ["AC-1"],
        }

        with patch(
            "rag_ime.agent_room_kernel_application.time.time",
            return_value=0.006,
        ):
            first = self.service.execute_room_capability_tool(
                self.session_id,
                "room_collaborate",
                arguments,
                tool_call_id="call:room-collaborate",
                load_receipt_id=str(loaded["receiptId"]),
            )
            replay = self.service.execute_room_capability_tool(
                self.session_id,
                "room_collaborate",
                arguments,
                tool_call_id="call:room-collaborate",
                load_receipt_id=str(loaded["receiptId"]),
            )

        result = first["result"]
        self.assertTrue(result["currentResponsibilityContinues"])
        self.assertEqual(result, replay["result"])
        self.assertEqual(first["executionReceipt"], replay["executionReceipt"])
        parent = self.service.room_kernel.dispatch("dispatch:service")
        child_dispatch = next(
            item
            for item in self.service.room_kernel_snapshot(self.room_id)[
                "dispatches"
            ]
            if item["dispatchId"] != "dispatch:service"
        )
        child_task = self.service.room_kernel.task(
            str(child_dispatch["taskId"])
        )
        self.assertEqual(parent["state"], "running")
        self.assertEqual(child_task["parentTaskId"], "task:service")
        self.assertEqual(
            child_task["ownerParticipantId"],
            self.participant["id"],
        )
        self.assertEqual(child_task["assigneeParticipantId"], target["id"])
        self.assertEqual(child_dispatch["taskId"], child_task["taskId"])
        self.assertEqual(child_dispatch["parentDispatchId"], "dispatch:service")
        self.assertEqual(child_dispatch["hopCount"], 1)
        self.assertEqual(child_dispatch["depth"], 1)
        self.assertEqual(child_dispatch["intentKind"], "review")
        self.assertEqual(
            child_dispatch["capabilityEpoch"],
            parent["capabilityEpoch"],
        )
        self.assertEqual(child_dispatch["state"], "pending")
        self.assertEqual(
            self.service.room_kernel.counts("root:service")["dispatches"],
            2,
        )
        self.assertEqual(result["targetParticipantRef"], target_ref)
        self.assertNotIn("childTaskId", result)
        self.assertNotIn("childDispatchId", result)

        cancelled = self.service.room_kernel_application.cancel_root(
            self.room_id,
            "root:service",
        )

        self.assertEqual(cancelled["status"], "terminated")
        self.assertEqual(
            self.service.room_kernel.root("root:service")["state"],
            "cancelled",
        )
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:service")["state"],
            "cancelled",
        )

    def test_room_collaborate_replay_repairs_missing_execution_receipt(self) -> None:
        self._set_parent_acceptance("criterion:service")
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        target = next(
            item
            for item in self.service.rooms.get(self.room_id)["participants"]
            if item["status"] == "active" and item["id"] != self.participant["id"]
        )
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-collaborate-repair",
                "toolName": "room_collaborate",
                "createdAtMs": 5,
            }
        )["result"]
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:state-collaborate-repair",
                "toolName": "room_state",
                "createdAtMs": 5,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:state-collaborate-repair",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if item["displayName"] == target["displayName"]
        )
        arguments = {
            "targetParticipantRef": target_ref,
            "objective": "独立复核一次边界条件",
            "expectedOutput": "一条受管协作结论",
            "intent": "review",
            "acceptance": ["AC-1"],
        }
        with patch.object(
            self.service.room_capabilities,
            "record_runtime_execution",
            side_effect=RuntimeError("injected execution receipt failure"),
        ):
            with patch(
                "rag_ime.agent_room_kernel_application.time.time",
                return_value=0.006,
            ):
                with self.assertRaisesRegex(RuntimeError, "injected execution receipt"):
                    self.service.execute_room_capability_tool(
                        self.session_id,
                        "room_collaborate",
                        arguments,
                        tool_call_id="call:room-collaborate-repair",
                        load_receipt_id=str(loaded["receiptId"]),
                    )

        self.service.room_kernel_worker.run_once()
        child = next(
            item
            for item in self.service.room_kernel_snapshot(self.room_id)["dispatches"]
            if item["dispatchId"] != "dispatch:service"
        )
        self.assertEqual(child["state"], "running")
        self.assertIsNone(
            self.service.room_capabilities.execution_receipt(
                "invoke:call:room-collaborate-repair"
            )
        )

        replay = self.service.execute_room_capability_tool(
            self.session_id,
            "room_collaborate",
            arguments,
            tool_call_id="call:room-collaborate-repair",
            load_receipt_id=str(loaded["receiptId"]),
        )

        self.assertEqual(
            replay["result"]["targetParticipantRef"],
            target_ref,
        )
        self.assertNotIn("childDispatchId", replay["result"])
        self.assertTrue(
            replay["result"]["currentResponsibilityContinues"]
        )
        self.assertEqual(
            self.service.room_kernel.counts("root:service")["dispatches"],
            2,
        )
        self.assertEqual(replay["executionReceipt"]["status"], "applied")

    def test_parallel_collaboration_revoke_keeps_peer_skill_epoch_live(self) -> None:
        self._set_parent_acceptance("criterion:service")
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        target = next(
            item
            for item in self.service.rooms.get(self.room_id)["participants"]
            if item["status"] == "active" and item["id"] != self.participant["id"]
        )
        collaboration_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:parallel-collaboration",
                "toolName": "room_collaborate",
                "createdAtMs": 5,
            }
        )["result"]
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:parallel-state",
                "toolName": "room_state",
                "createdAtMs": 5,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:parallel-state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if item["displayName"] == target["displayName"]
        )
        with patch(
            "rag_ime.agent_room_kernel_application.time.time",
            return_value=0.006,
        ):
            collaboration = self.service.execute_room_capability_tool(
                self.session_id,
                "room_collaborate",
                {
                    "targetParticipantRef": target_ref,
                    "objective": "并行复核后回报",
                    "expectedOutput": "一条独立结论",
                    "intent": "review",
                    "acceptance": ["AC-1"],
                },
                tool_call_id="call:parallel-collaboration",
                load_receipt_id=str(collaboration_load["receiptId"]),
            )["result"]
        self.assertNotIn("childDispatchId", collaboration)
        child_id = str(
            next(
                item
                for item in self.service.room_kernel_snapshot(self.room_id)[
                    "dispatches"
                ]
                if item["dispatchId"] != "dispatch:service"
            )["dispatchId"]
        )
        child = self.service.room_kernel.dispatch(child_id)
        self.assertEqual(child["capabilityEpoch"], 7)

        parent_skill = "test-driven-implementation"
        self.service.room_skill_receipts.pin_skill(
            receipt_id="skill:parallel-parent",
            root_id="root:service",
            task_id="task:service",
            dispatch_id="dispatch:service",
            session_id=self.session_id,
            skill_id=parent_skill,
            skill_hash=self.service.room_skill_policy.skill_hash(parent_skill),
            catalog_revision="d" * 64,
            load_reason="stage_required",
            capability_epoch=7,
            idempotency_key="dispatch:service/implementation",
            created_at_ms=6,
        )

        self._settle_running_dispatch(
            session_id=self.session_id,
            dispatch_id="dispatch:service",
            capability_epoch=7,
            scope_id="scope:parallel-parent",
        )
        self.assertEqual(
            self.service.room_skill_receipts.latest_for_session(self.session_id)[
                "state"
            ],
            "revoked",
        )
        self.assertEqual(self.service.room_kernel.dispatch(child_id)["state"], "pending")

        self.service.room_kernel_worker.run_once()
        child_session_id = str(target["sessionId"])
        child_skill = "independent-review"
        pinned, _ = self.service.room_skill_receipts.pin_skill(
            receipt_id="skill:parallel-child",
            root_id="root:service",
            task_id=str(child["taskId"]),
            dispatch_id=child_id,
            session_id=child_session_id,
            skill_id=child_skill,
            skill_hash=self.service.room_skill_policy.skill_hash(child_skill),
            catalog_revision="d" * 64,
            load_reason="stage_required",
            capability_epoch=7,
            idempotency_key=f"{child_id}/review",
            created_at_ms=7,
        )
        self.assertEqual(pinned["state"], "active")

        self._settle_running_dispatch(
            session_id=child_session_id,
            dispatch_id=child_id,
            capability_epoch=7,
            scope_id="scope:parallel-child",
        )
        self.assertEqual(
            self.service.room_skill_receipts.latest_for_session(child_session_id)[
                "state"
            ],
            "revoked",
        )
        with self.assertRaises(RoomSkillEpochRevoked):
            self.service.room_skill_receipts.pin_skill(
                receipt_id="skill:stale-parallel-wave",
                root_id="root:service",
                task_id=str(child["taskId"]),
                dispatch_id=child_id,
                session_id=child_session_id,
                skill_id=child_skill,
                skill_hash=self.service.room_skill_policy.skill_hash(child_skill),
                catalog_revision="d" * 64,
                load_reason="stage_required",
                capability_epoch=7,
                idempotency_key=f"{child_id}/stale-review",
                created_at_ms=8,
            )

    def _settle_running_dispatch(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        capability_epoch: int,
        scope_id: str,
    ) -> dict[str, object]:
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": f"load:{dispatch_id}:commit",
                "toolName": "room_commit",
                "createdAtMs": 10,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            session_id,
            "room_commit",
            {
                "decision": "wait",
                "summary": f"waiting:{dispatch_id}",
                "evidence": [],
                "residualRisks": ["test fixture leaves acceptance unverified"],
                "waitingFor": "external",
                "resumeCondition": "test explicitly resumes the fixture",
            },
            tool_call_id=f"call:{dispatch_id}:commit",
            load_receipt_id=str(loaded["receiptId"]),
        )
        dispatch = self.service.room_kernel.dispatch(dispatch_id)
        task = self.service.room_kernel.task(str(dispatch["taskId"]))
        criteria = tuple(
            str(value)
            for value in task.get("acceptanceCriterionIds", [])
            if str(value).strip()
        )
        commit_id = f"commit:{scope_id}"
        post_id = f"post:{scope_id}"
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": commit_id,
            "dispatchId": dispatch_id,
            "action": "post",
            "contentHash": f"sha256:{scope_id}",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": post_id,
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "taskId": dispatch["taskId"],
                "dispatchId": dispatch_id,
                "authorActorRef": dispatch["targetParticipantId"],
                "kind": "wait",
                "visibility": "room",
                "content": f"waiting:{dispatch_id}",
                "idempotencyKey": post_id,
                "publicationSource": {
                    "kind": "room_commit",
                    "ref": commit_id,
                },
                "createdAtMs": 10,
            },
            "continuation": {"decision": "wait"},
            "qualityGateReceipt": self._quality_gate_receipt(
                commit_id,
                dispatch_id,
                action="post",
                task_id=str(dispatch["taskId"]),
                criteria=criteria,
                created_at_ms=10,
            ),
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 10,
        }
        return self.service.settle_room_kernel_dispatch(
            self.room_id,
            {
                "settleReceipt": {
                    "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
                    "settleReceiptId": f"settle:{scope_id}",
                    "eventKind": "agent_settled",
                    "status": "settled",
                    "dispatchId": dispatch_id,
                    "sessionId": session_id,
                    "generation": 0,
                    "capabilityEpoch": capability_epoch,
                    "createdAtMs": 10,
                },
                "commit": commit,
                "invocationReceiptId": (
                    f"invoke:call:{dispatch_id}:commit"
                ),
            },
            caller_authorized=True,
        )

    def test_room_dispatch_uses_the_normal_agent_tool_catalog_and_gateway(self) -> None:
        target = self.root / "room-product-tool.txt"
        target.write_text("Room product Tool is live.\n", encoding="utf-8")
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()

        runtime_tools = self.service._runtime_tool_manifest(
            {"id": self.session_id}
        )
        names = [str(item["name"]) for item in runtime_tools]
        self.assertEqual(
            names[:4],
            ["room_state", "room_post", "room_commit", "room_collaborate"],
        )
        for name in (
            "ime_planning",
            "ime_configuration",
            "workspace_read",
            "workspace_patch",
            "workspace_shell",
        ):
            self.assertIn(name, names)
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-workspace-read",
                "toolName": "workspace_read",
                "createdAtMs": 5,
            }
        )["result"]
        response = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_read",
                "toolCallId": "tool:room-workspace-read",
                "loadReceiptId": loaded["receiptId"],
                "args": {"op": "read", "path": str(target)},
            }
        )

        self.assertEqual(
            response["result"]["content"],
            "Room product Tool is live.\n",
        )
        execution = response["roomExecutionReceipt"]
        self.assertEqual(execution["toolName"], "workspace_read")
        self.assertEqual(execution["status"], "applied")
        self.assertEqual(
            self.service.room_capabilities.execution_receipt(
                str(execution["invocationReceiptId"])
            ),
            execution,
        )

    def test_room_dispatch_can_prepare_and_apply_a_native_approved_workspace_patch(self) -> None:
        self._use_per_action_execution()
        target = self.root / "room-approved-patch.txt"
        target.write_text("before\n", encoding="utf-8")
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-workspace-patch",
                "toolName": "workspace_patch",
                "createdAtMs": 5,
            }
        )["result"]

        workflow = self.service.workflow_state(self.session_id)
        prepared = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_patch",
                "toolCallId": "tool:room-workspace-patch",
                "loadReceiptId": loaded["receiptId"],
                "args": {
                    "op": "apply",
                    "path": str(target),
                    "oldText": "before",
                    "newText": "after",
                    "expectedOccurrences": 1,
                },
            }
        )

        self.assertTrue(workflow["actGate"]["allowed"])
        self.assertEqual(workflow["plan"]["status"], "draft")
        self.assertTrue(prepared["result"]["approvalRequired"])
        self.assertIn("roomInvocationReceipt", prepared)
        self.assertNotIn("roomExecutionReceipt", prepared)
        approval = prepared["result"]["approval"]
        decided = self.service.sessions.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = gateway.apply_approval(decided)

        self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
        self.assertEqual(receipt["replacementCount"], 1)
        self.assertEqual(
            receipt["roomExecutionReceipt"]["status"],
            "applied",
        )

    def test_room_dispatch_exposes_the_complete_normal_agent_tool_surface(self) -> None:
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        session = self.service.sessions.get(self.session_id)
        normal_agent_tools = {
            str(item["name"])
            for item in gateway.runtime_manifests(session)
        }

        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        bound = self.service.room_capabilities.manifest_for_runtime(
            self.session_id
        )
        self.assertIsNotNone(bound)
        manifest, _binding = bound
        product_tools = {
            str(item["name"])
            for item in manifest["tools"]
            if str(item.get("operation") or "").startswith("product.")
            and item.get("authorized") is True
        }

        self.assertEqual(product_tools, normal_agent_tools)
        self.assertTrue(
            {
                "workspace_read",
                "workspace_search",
                "workspace_patch",
                "workspace_shell",
                "ime_memory",
                "ime_browser",
                "desktop_semantic",
            }.issubset(product_tools)
        )

    def test_rejected_room_tool_approval_seals_a_rejected_execution_receipt(self) -> None:
        self._use_per_action_execution()
        target = self.root / "room-rejected-patch.txt"
        target.write_text("before\n", encoding="utf-8")
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:rejected-room-workspace-patch",
                "toolName": "workspace_patch",
                "createdAtMs": 5,
            }
        )["result"]
        prepared = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_patch",
                "toolCallId": "tool:rejected-room-workspace-patch",
                "loadReceiptId": loaded["receiptId"],
                "args": {
                    "op": "apply",
                    "path": str(target),
                    "oldText": "before",
                    "newText": "rejected",
                    "expectedOccurrences": 1,
                },
            }
        )
        invocation_receipt_id = str(
            prepared["roomInvocationReceipt"]["receiptId"]
        )
        approval = prepared["result"]["approval"]
        rejected = self.service.sessions.decide_approval(
            str(approval["approvalId"]),
            approved=False,
            payload_sha256=str(approval["payloadSha256"]),
        )

        decision = self.service.approval_application.finish_decision(
            rejected,
            pending_in_pi=False,
        )
        execution = self.service.room_capabilities.execution_receipt(
            invocation_receipt_id
        )

        self.assertEqual(decision["approval"]["state"], "rejected")
        self.assertEqual(decision["runtimeWarning"], "")
        self.assertEqual(execution["status"], "rejected")
        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_cancelled_room_dispatch_rejects_a_late_approved_workspace_patch(self) -> None:
        self._use_per_action_execution()
        target = self.root / "room-cancelled-patch.txt"
        target.write_text("before\n", encoding="utf-8")
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:cancelled-room-workspace-patch",
                "toolName": "workspace_patch",
                "createdAtMs": 5,
            }
        )["result"]
        prepared = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_patch",
                "toolCallId": "tool:cancelled-room-workspace-patch",
                "loadReceiptId": loaded["receiptId"],
                "args": {
                    "op": "apply",
                    "path": str(target),
                    "oldText": "before",
                    "newText": "late",
                    "expectedOccurrences": 1,
                },
            }
        )["result"]
        approval = prepared["approval"]
        decided = self.service.sessions.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.service.apply_room_kernel_command(
            self.room_id,
            self._cancel_command(),
            caller_authorized=True,
        )

        with self.assertRaises(RoomKernelFenceError):
            gateway.apply_approval(decided)
        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_cancelled_room_dispatch_invalidates_its_pending_workspace_approval(self) -> None:
        self._use_per_action_execution()
        target = self.root / "room-pending-cancelled-patch.txt"
        target.write_text("before\n", encoding="utf-8")
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:pending-cancelled-room-workspace-patch",
                "toolName": "workspace_patch",
                "createdAtMs": 5,
            }
        )["result"]
        prepared = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_patch",
                "toolCallId": "tool:pending-cancelled-room-workspace-patch",
                "loadReceiptId": loaded["receiptId"],
                "args": {
                    "op": "apply",
                    "path": str(target),
                    "oldText": "before",
                    "newText": "late",
                    "expectedOccurrences": 1,
                },
            }
        )["result"]
        approval = prepared["approval"]

        cancelled = self.service.room_kernel_application.cancel_root(
            self.room_id,
            "root:service",
        )
        stale = self.service.sessions.get_approval(approval["approvalId"])

        self.assertEqual(cancelled["status"], "terminated")
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["receipt"]["reason"], "room_root_cancelled")
        self.assertFalse(stale["receipt"]["mutationApplied"])
        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")
        runtime_receipt = cancelled["sessionReceipts"][0]
        self.assertEqual(
            runtime_receipt["approvalCancellation"]["cancelledApprovalIds"],
            [approval["approvalId"]],
        )
        replayed = self.service.sessions.invalidate_room_approvals(
            self.session_id,
            "root:service",
            "dispatch:service",
            100,
        )
        self.assertEqual(
            replayed["cancelledApprovalIds"],
            [approval["approvalId"]],
        )

    def test_room_commit_receipt_is_an_explicit_model_turn_boundary(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:terminal-commit",
                "toolName": "room_commit",
                "createdAtMs": 5,
            }
        )["result"]

        staged = self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": "wait",
                "summary": "等待下一步输入",
                "evidence": [],
                "residualRisks": ["尚未获得外部输入"],
                "waitingFor": "user",
                "resumeCondition": "用户补充下一步目标",
                "question": "下一步希望优先处理什么？",
            },
            tool_call_id="call:terminal-commit",
            load_receipt_id=str(loaded["receiptId"]),
        )["result"]

        self.assertFalse(staged["executionPerformed"])
        self.assertTrue(staged["settlementStaged"])
        self.assertTrue(staged["terminalForModelTurn"])
        self.assertEqual(
            staged["next"],
            "end_model_turn_for_before_agent_settle",
        )
        self.assertIn("立即结束本轮", staged["modelInstruction"])

    def test_managed_dispatch_preparation_replays_after_crash_before_lease(self) -> None:
        dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(dispatch, now_ms=3)

        first = self.service._prepare_managed_room_dispatch(dispatch, 3)
        prepared = self.service.room_capabilities.runtime_binding(
            self.session_id, active_only=False
        )
        self.assertEqual(prepared["state"], "prepared")
        task_context = self.service._memory_task_context(self.session_id)
        self.assertEqual(task_context["kind"], "room_kernel_task")
        self.assertEqual(task_context["objective"], "Execute a bounded service test.")
        self.assertEqual(task_context["expectedOutput"], "A typed receipt.")
        with self.assertRaises(KeyError):
            self.service.room_kernel.lease("dispatch:service")
        self.assertEqual(self.factory.runtime.dispatched, [])

        replayed = self.service._prepare_managed_room_dispatch(dispatch, 99)
        self.assertEqual(first, replayed)
        with sqlite3.connect(self.service.db_path) as conn:
            pin = conn.execute(
                """SELECT profile_id,profile_version,pointer_revision,guard_epoch,
                          bundle_content_hash,definition_content_hash
                   FROM room_v2_root_profile_pins WHERE root_id='root:service'"""
            ).fetchone()
        self.assertEqual(pin[:4], ("standard-room", "1", 0, 0))
        self.assertTrue(str(pin[4]).startswith("sha256:"))
        self.assertTrue(str(pin[5]).startswith("sha256:"))
        with self.assertRaisesRegex(RoomKernelFenceError, "cannot hot-swap"):
            self.service._resolve_room_collaboration_profile(
                {**self.service.room_kernel.root("root:service"), "activeProfileRef": "evidence-review"},
                pinned_at_ms=100,
            )
        self.service.room_kernel_worker.run_once()
        active = self.service.room_capabilities.runtime_binding(self.session_id)
        self.assertEqual(active["manifestHash"], first["manifestHash"])
        self.assertEqual(self.factory.runtime.dispatched, ["dispatch:service"])

        snapshot = self.service.room_kernel_snapshot(self.room_id)
        projected = next(item for item in snapshot["sessions"] if item["sessionId"] == self.session_id)
        self.assertEqual(projected["capabilityManifest"]["manifestHash"], first["manifestHash"])
        self.assertEqual(projected["capabilityManifest"]["status"], "active")

    def test_room_session_recall_uses_immutable_original_requirement(self) -> None:
        original = "原始需求永久保留；Room Agent 只能按自己的 Task 召回。"
        self.service.room_requirements.append_anchor(
            anchor_id="requirement-anchor:service",
            root_id="root:service",
            original_content=original,
            created_by="user:local",
            provenance={"surface": "test"},
            created_at_ms=2,
        )
        dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(dispatch, now_ms=3)
        self.service._prepare_managed_room_dispatch(dispatch, 3)

        task_context = self.service._memory_task_context(self.session_id)

        self.assertEqual(task_context["kind"], "room_kernel_task")
        self.assertEqual(task_context["originalRequirements"], [original])
        refreshed = self.service.refresh_session_context(
            {
                "sessionId": self.session_id,
                "trigger": "session_start",
                "queryText": "继续自己的任务",
                "recentMessages": [{"role": "user", "text": "继续自己的任务"}],
            }
        )
        generic_rag = refreshed["result"]["sessionContext"]
        self.assertEqual(generic_rag, "")
        self.assertEqual(refreshed["result"]["sourceCount"], 0)
        self.assertNotIn("原始需求（不可改写）", generic_rag)
        self.assertNotIn(original, generic_rag)
        binding = self.service.room_capabilities.runtime_binding(
            self.session_id,
            active_only=False,
        )
        room_context = self.service.room_prompt_plans.provider_payload(
            str(binding["promptCompileReceiptId"])
        )["providerContext"]
        self.assertIn(original, room_context)
        self.assertIn("Execute a bounded service test.", room_context)

    def test_failed_room_recovery_keeps_previous_memory_bootstrap_active(self) -> None:
        dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(dispatch, now_ms=3)
        prepared = self.service._prepare_managed_room_dispatch(dispatch, 3)
        lease = self.service.room_kernel.lease_next(
            now_ms=4,
            ttl_ms=30_000,
            dispatch_id=str(dispatch["dispatchId"]),
            prepared_session_id=str(prepared["sessionId"]),
            prepared_manifest_hash=str(prepared["manifestHash"]),
        )
        self.assertIsNotNone(lease)
        self.assertEqual(
            self.service.room_capabilities.runtime_binding(
                self.session_id
            )["state"],
            "active",
        )

        self.service.refresh_session_context(
            {
                "sessionId": self.session_id,
                "trigger": "session_start",
                "queryText": "建立一份有效上下文",
                "recentMessages": [
                    {"role": "user", "text": "建立一份有效上下文"}
                ],
            }
        )
        before = (
            self.service.memory_context_application
            .context_runtime.materialize(self.session_id)
        )
        self.assertTrue(
            any(
                item.get("sourceKind") == "memory_bootstrap"
                for item in before["items"]
            )
        )

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "Skill receipt that is not pinned",
        ):
            self.service.refresh_session_context(
                {
                    "sessionId": self.session_id,
                    "trigger": "session_start",
                    "queryText": "这次错误请求不得覆盖旧上下文",
                    "recentMessages": [
                        {
                            "role": "user",
                            "text": "这次错误请求不得覆盖旧上下文",
                        }
                    ],
                    "roomSkillRecovery": {
                        "catalogRevision": "c" * 64,
                    },
                }
            )

        after = (
            self.service.memory_context_application
            .context_runtime.materialize(self.session_id)
        )
        self.assertEqual(after, before)

    def test_room_binding_rejects_legacy_intercom_before_it_can_enqueue(self) -> None:
        dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(dispatch, now_ms=3)
        self.service.room_kernel_worker.run_once()
        target = next(
            participant
            for participant in self.service.rooms.get(self.room_id)["participants"]
            if participant["id"] != self.participant["id"]
        )

        with self.assertRaisesRegex(RoomKernelFenceError, "owned by Kernel"):
            self.service.send_room_intercom(
                self.session_id,
                {
                    "kind": "send",
                    "targetParticipantId": target["id"],
                    "clientMessageId": "legacy-after-binding",
                    "content": "must not enter the legacy queue",
                },
            )
        self.assertEqual(
            self.service.list_room_intercom(self.session_id)["items"],
            [],
        )

    def _exercise_requirement_proof_observation_to_terminal(self) -> None:
        original = "必须发布结果并完成任务"
        anchor, _ = self.service.room_requirements.append_anchor(
            anchor_id="requirement-anchor:service",
            root_id="root:service",
            original_content=original,
            created_by="user:local",
            provenance={"source": "test-user-request"},
            created_at_ms=2,
        )
        catalog, _ = self.service.room_requirements.revise_catalog(
            catalog_revision_id="catalog:service:1",
            root_id="root:service",
            expected_current_revision=0,
            anchor_refs=[anchor["anchorId"]],
            items=[{
                "itemId": "requirement:service",
                "kind": "explicit_user_requirement",
                "statement": original,
                "origin": "user",
                "state": "active",
                "sourceSpans": [{"anchorId": anchor["anchorId"], "startByte": 0, "endByte": len(original.encode("utf-8"))}],
            }],
            acceptance_criteria=[{
                "criterionId": "criterion:service",
                "itemId": "requirement:service",
                "acceptanceCriterionFullNameZh": "用户端完整交付链路",
                "criterionKind": "user_journey",
                "expectedReceiptTypes": ["test"],
                "statement": "Post 与终态回执可追踪",
            }],
            change_reason="建立原始需求目录",
            provenance={"source": "test"},
            created_by="user:local",
            created_at_ms=2,
        )
        verification = {
            "schemaVersion": "wisdom-weasel.typed-verification-receipt.v1",
            "receiptId": "verification:service",
            "rootId": "root:service",
            "catalogRevisionId": catalog["catalogRevisionId"],
            "receiptType": "test",
            "sourceCommit": "commit:test",
            "environment": "room-v2-test",
            "commandOrAction": "managed cohort e2e",
            "exitStatus": 0,
            "outputHash": "a" * 64,
            "artifactHash": "b" * 64,
            "verifier": "managed-test-runner",
            "createdAtMs": 2,
        }
        self.service.room_requirements.record_verification_receipt(verification)
        self.service.room_requirements.link_proof(
            proof_id="proof:service",
            root_id="root:service",
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            criterion_id="criterion:service",
            receipt_id="verification:service",
            linked_by="managed-test-runner",
            created_at_ms=2,
        )
        with sqlite3.connect(self.service.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id = ?",
                ("task:service",),
            ).fetchone()
            assert row is not None
            task_payload = json.loads(str(row[0]))
            task_payload["acceptanceCriterionIds"] = ["criterion:service"]
            conn.execute(
                """UPDATE room_kernel_tasks
                   SET payload_json = ?
                   WHERE task_id = ?""",
                (
                    json.dumps(
                        task_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "task:service",
                ),
            )

        first_dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(first_dispatch, now_ms=3)
        self.service.room_kernel_worker.run_once()
        observation = self.service.room_requirements.dispatch_binding("dispatch:service")
        self.assertEqual(observation["anchorRefs"], ["requirement-anchor:service"])
        self.assertEqual(observation["proofReceiptRefs"], ["verification:service"])
        self.assertEqual(observation["state"], "active")

        invocation_id = self._room_tool_invocation("call:e2e-post", "公开交付")
        post_commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:e2e-post",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:e2e-post",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:e2e",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "公开交付",
                "idempotencyKey": "post:e2e",
                "publicationSource": {"kind": "room_commit", "ref": "commit:e2e-post"},
                "createdAtMs": 4,
            },
            "qualityGateReceipt": self._quality_gate_receipt(
                "commit:e2e-post",
                "dispatch:service",
                action="post",
                criteria=("criterion:service",),
                coverage=("criterion:service",),
                evidence_refs=("verification:service",),
                created_at_ms=4,
            ),
            "evidenceRefs": ["verification:service"],
            "requirementCoverage": ["criterion:service"],
            "createdAtMs": 4,
        }
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:e2e-post",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 4,
        }
        self.service.settle_room_kernel_dispatch(
            self.room_id,
            {"settleReceipt": settle, "commit": post_commit, "invocationReceiptId": invocation_id},
            caller_authorized=True,
        )

        second = self._dispatch(
            "dispatch:complete",
            capability_epoch=8,
            runtime_profile_revision="runtime-profile:service-v2",
        )
        self.service.room_kernel.enqueue_dispatch(second, now_ms=5)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load({
            "sessionId": self.session_id,
            "receiptId": "load:e2e-complete",
            "toolName": "room_commit",
            "createdAtMs": 6,
        })["result"]
        invoked = self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": "deliver",
                "summary": "完成",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": ["verification:service"],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:e2e-complete",
            load_receipt_id=str(loaded["receiptId"]),
        )
        complete_commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:e2e-complete",
            "dispatchId": "dispatch:complete",
            "action": "complete",
            "contentHash": "sha256:e2e-complete",
            "postProposal": None,
            "qualityGateReceipt": self._quality_gate_receipt(
                "commit:e2e-complete",
                "dispatch:complete",
                action="complete",
                criteria=("criterion:service",),
                coverage=("criterion:service",),
                evidence_refs=("verification:service",),
                created_at_ms=6,
            ),
            "evidenceRefs": ["verification:service"],
            "requirementCoverage": ["criterion:service"],
            "createdAtMs": 6,
        }
        complete_settle = {
            **settle,
            "settleReceiptId": "settle:e2e-complete",
            "dispatchId": "dispatch:complete",
            "capabilityEpoch": 8,
            "createdAtMs": 6,
        }
        self.service.settle_room_kernel_dispatch(
            self.room_id,
            {
                "settleReceipt": complete_settle,
                "commit": complete_commit,
                "invocationReceiptId": invoked["invocationReceipt"]["receiptId"],
            },
            caller_authorized=True,
        )
        final = self.service.finalize_room_kernel_root(
            "root:service",
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            target_commit="commit:test",
            blind_review_status="passed",
            now_ms=7,
        )
        terminal_gate = final["receipt"]["details"][
            "deliveryGateObservation"
        ]
        self.assertEqual(terminal_gate["gateStatus"], "not_observed")
        gate = final["deliveryGateObservation"]
        self.assertEqual(gate["gateStatus"], "observed_pass")
        self.assertTrue(gate["gateReceiptId"])
        self.assertFalse(gate["enforcementApplied"])
        self.assertEqual(self.service.room_kernel_snapshot(self.room_id)["posts"][0]["postId"], "post:e2e")
        replayed = self.service.finalize_room_kernel_root(
            "root:service",
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            target_commit="commit:test",
            blind_review_status="passed",
            now_ms=9,
        )
        self.assertEqual(replayed, final)

    def test_requirement_proof_observation_reaches_terminal_without_enforcement(self) -> None:
        self._exercise_requirement_proof_observation_to_terminal()

    @requires_process_identity
    def test_named_cohort_crosses_process_boundary_through_the_full_managed_chain(self) -> None:
        self.service.close()
        host = self.root / "room-v2-process-host"
        host.write_text(FAKE_HOST, encoding="utf-8")
        host.chmod(0o755)
        config = PiRuntimeConfig(
            enabled=True,
            executable=host,
            agent_dir=self.root / "process-agent",
            session_dir=self.root / "process-sessions",
            logs_dir=self.root / "process-logs",
            idle_timeout_seconds=0,
            command_timeout_seconds=5,
            provider="gpt",
            model="gpt-5.6-luna",
            provider_environment={"TEST_ROOM_TYPES": "1"},
            pi_version="0.80.7",
            protocol_version="2",
            max_sessions=4,
        )
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_ROOM_KERNEL_MODE": "cohort",
                "RAG_IME_ROOM_KERNEL_COHORT_ID": "room-v2-test",
            },
            clear=True,
        ):
            mode = _room_kernel_mode_from_environment()
        self.service = AgentService(
            db_path=self.root / "process.sqlite",
            runtime_config=config,
            room_kernel_mode=mode,
            room_kernel_poll_seconds=60,
        )
        self.service.room_kernel_worker_loop.close()
        room = self.service.create_room(
            {
                "title": "room-v2-test process cohort",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        self.room_id = str(room["id"])
        self.participant = room["participants"][1]
        self.session_id = str(self.participant["sessionId"])
        self._seed()

        self._exercise_requirement_proof_observation_to_terminal()

        requests = [
            json.loads(line)
            for line in (config.agent_dir / "host-requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        methods = [str(request["method"]) for request in requests]
        self.assertEqual(methods[0], "hello")
        self.assertIn("session.open", methods)
        # Capability and PromptPlan ownership can rotate inside one idle Room
        # Session. Only a Product-owned context epoch transition may rebase the
        # Provider prefix; a new Dispatch must not discard the resident journal.
        self.assertEqual(methods.count("session.open"), 1)
        self.assertEqual(methods.count("session.close"), 0)
        self.assertLess(methods.index("session.open"), methods.index("room.dispatch"))
        opened = next(request for request in requests if request["method"] == "session.open")
        self.assertIn("<room-prompt-plan", opened["params"]["systemPrompt"])
        self.assertNotIn("运行时工具渐进披露规则", opened["params"]["systemPrompt"])
        session_context = opened["params"]["sessionContext"]
        room_context = opened["params"]["roomContext"]
        room_recovery = json.loads(
            opened["params"]["roomRecoveryContext"]
        )
        self.assertNotIn("schemaVersion", room_recovery)
        self.assertEqual(
            room_recovery["currentTask"]["objective"],
            "Execute a bounded service test.",
        )
        # No relevant governed memory was seeded for this process test. An empty
        # RAG lane stays empty instead of spending Provider tokens on a placeholder.
        self.assertEqual(session_context, "")
        self.assertNotIn('"objective":"Execute a bounded service test."', session_context)
        self.assertIn("目标：Execute a bounded service test.", room_context)
        for internal_label in (
            '"dispatchId"',
            '"taskId"',
            '"rootId"',
            '"receiptId"',
            "schemaVersion",
            "catalogRevision",
            "generation",
            "sha256",
        ):
            self.assertNotIn(internal_label, room_context)
        self.assertEqual(
            opened["params"]["roomSkillPolicy"]["skillId"],
            "test-driven-implementation",
        )
        self.assertEqual(methods.count("room.dispatch"), 2)
        room_dispatches = [
            request
            for request in requests
            if request["method"] == "room.dispatch"
        ]
        self.assertEqual(
            [request["params"]["dispatchId"] for request in room_dispatches],
            ["dispatch:service", "dispatch:complete"],
        )
        first_dispatch_request = room_dispatches[0]
        self.assertNotIn("sessionContext", first_dispatch_request["params"])
        self.assertIn(
            "目标：Execute a bounded service test.",
            first_dispatch_request["params"]["roomContext"],
        )
        self.assertEqual(
            json.loads(
                first_dispatch_request["params"]["roomRecoveryContext"]
            )["currentTask"]["objective"],
            "Execute a bounded service test.",
        )
        second_dispatch_request = room_dispatches[1]
        self.assertEqual(
            second_dispatch_request["params"]["roomCapability"]["contextEpoch"],
            first_dispatch_request["params"]["roomCapability"]["contextEpoch"],
        )
        self.assertEqual(
            json.loads(
                second_dispatch_request["params"]["roomRecoveryContext"]
            )["currentTask"]["objective"],
            "Execute a bounded service test.",
        )
        skill_receipt = self.service.room_skill_receipts.latest_for_session(self.session_id)
        self.assertIsNotNone(skill_receipt)
        self.assertEqual(skill_receipt["skillId"], "test-driven-implementation")
        self.assertEqual(skill_receipt["state"], "revoked")
        projection = self.service.room_projection_journals.projection(
            "room-journal:dispatch:service", expected_generation=0
        )
        self.assertEqual(projection["pendingTail"], [])
        self.assertEqual(projection["sealedThroughSequence"], 1)

    @requires_loopback_bind
    def test_real_http_snapshot_command_and_sse_gap_routes(self) -> None:
        wrapper = SimpleNamespace(
            agent=self.service,
            management_security_settings=lambda: {
                "postRequiresJson": True,
                "sameOriginOnly": True,
                "requireToken": False,
            },
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = wrapper
        Handler.static_dir = self.root
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        room_path = quote(self.room_id, safe="")
        base = f"http://127.0.0.1:{server.server_port}/api/agent/rooms/{room_path}/kernel"
        try:
            with urlopen(f"{base}/snapshot", timeout=5) as response:
                snapshot = json.load(response)
            self.assertEqual(snapshot["roots"][0]["rootId"], "root:service")

            request = Request(
                f"{base}/commands",
                data=json.dumps(self._cancel_command()).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                receipt = json.load(response)
            self.assertEqual(receipt["receiptKind"], "root_cancelled")

            gap_token = quote(f"{self.room_id}#999", safe="")
            with urlopen(f"{base}/events?afterEventId={gap_token}", timeout=5) as response:
                lines = []
                while True:
                    line = response.readline().decode("utf-8")
                    lines.append(line)
                    if line == "\n":
                        break
                event_stream = "".join(lines)
            self.assertIn("event: snapshot_required", event_stream)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
