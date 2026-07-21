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

    def test_product_message_uses_one_async_kernel_fanout_path(self) -> None:
        room = self.service.room(self.room_id)["room"]
        participant_ids = [
            str(participant["id"])
            for participant in room["participants"]
            if participant["status"] == "active"
        ]
        client_message_id = "client:kernel-fanout"
        message = "请两位分别检查实现与测试，再汇总可验证结论。"

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
                    "participantIds": participant_ids,
                },
            )

        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["status"], "queued")
        self.assertEqual(accepted["executionOwner"], "kernel")
        self.assertEqual(len(accepted["dispatches"]), len(participant_ids))
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
                "participantIds": participant_ids,
            },
        )
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay["rootId"], accepted["rootId"])
        self.assertEqual(
            len(self.service.room_kernel_snapshot(self.room_id)["posts"]),
            len(snapshot["posts"]),
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
                "receiptId": f"load:{binding['manifestId']}:room_post",
                "toolName": "room_post",
                "createdAtMs": 29,
            }
        )["result"]
        arguments: dict[str, object] = {"content": content}
        if blocks is not None:
            arguments["blocks"] = blocks
        result = self.service.execute_room_capability_tool(
            self.session_id,
            "room_post",
            arguments,
            tool_call_id=call_id,
            load_receipt_id=str(loaded["receiptId"]),
        )
        return str(result["invocationReceipt"]["receiptId"])

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
        self.assertIn("wisdom-weasel.room-context-omission.v1", provider_text)
        self.assertIn("表格：历史矩阵，1 行 1 列", provider_text)
        self.assertNotIn("raw-history-secret-7ab2", provider_text)
        self.assertNotIn('"rows"', provider_text)

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

    def test_kernel_bound_message_completion_never_enters_legacy_room_timeline(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        before = len(self.service.rooms.list_events(self.room_id, limit=200))
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "private reasoning"}]}},
            turn_id="turn:private",
        )
        after = self.service.rooms.list_events(self.room_id, limit=200)

        self.assertEqual(len(after), before)
        self.assertNotIn("private reasoning", str(self.service.room_kernel_snapshot(self.room_id)))

    def test_worker_lifecycle_is_stoppable(self) -> None:
        self.service.room_kernel_worker_loop.start()
        self.assertTrue(self.service.room_kernel_worker_loop.running)
        self.service.room_kernel_worker_loop.close()
        self.assertFalse(self.service.room_kernel_worker_loop.running)

    def test_capability_manifest_exposes_only_one_canonical_kernel_path(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        tools = ("room_state", "room_post", "room_commit")
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
            "room_state/room_post/room_commit",
        ):
            self.service.execute_room_capability_tool(
                self.session_id,
                "room_send",
                {"content": "deliver"},
                tool_call_id="call:legacy-service",
                load_receipt_id=str(loaded["receiptId"]),
            )
        canonical = self.service.execute_room_capability_tool(
            self.session_id, "room_post", {"content": "deliver"},
            tool_call_id="call:service", load_receipt_id=str(loaded["receiptId"]),
        )
        self.assertFalse(canonical["result"]["executionPerformed"])
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:capability-service",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:deliver",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:capability-service",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "deliver",
                "idempotencyKey": "post:capability-service",
                "publicationSource": {"kind": "room_commit", "ref": "commit:capability-service"},
                "createdAtMs": 6,
            },
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 6,
        }
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:capability-service",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 6,
        }
        settle_payload = {
            "settleReceipt": settle,
            "commit": commit,
            "invocationReceiptId": canonical["invocationReceipt"]["receiptId"],
        }
        first_settle = self.service.settle_room_kernel_dispatch(
            self.room_id, settle_payload, caller_authorized=True,
        )
        replayed_settle = self.service.settle_room_kernel_dispatch(
            self.room_id, settle_payload, caller_authorized=True,
        )
        self.assertEqual(first_settle["receipt"], replayed_settle["receipt"])
        self.assertEqual(
            first_settle["executionReceipt"]["kernelReceiptId"],
            first_settle["receipt"]["receiptId"],
        )
        self.assertEqual(first_settle["executionReceipt"], replayed_settle["executionReceipt"])
        self.assertIsNone(self.service.execute_room_capability_tool(
            "ordinary-session", "room_post", {"content": "ordinary"}, tool_call_id="call:ordinary", load_receipt_id=""
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
                {"content": "late delivery"},
                tool_call_id="call:after-cancel",
                load_receipt_id=str(loaded["receiptId"]),
            )
        self.assertEqual(
            self.service.room_capabilities.runtime_binding(self.session_id, active_only=False)["state"],
            "revoked",
        )
        with self.assertRaises(ToolAuthorizationError):
            self.service.room_capabilities.authorize_runtime_invocation(
                session_id=self.session_id, receipt_id="invoke:revoked", invocation_key="call:revoked",
                load_receipt_id=str(loaded["receiptId"]), tool_name="room_post", arguments={"content": "no"}, created_at_ms=7,
            )

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
        self.assertIn("## Session 记忆", generic_rag)
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
                "result": "完成",
                "evidenceRefs": ["verification:service"],
                "requirementCoverage": ["criterion:service"],
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
        gate = final["receipt"]["details"]["deliveryGateObservation"]
        self.assertEqual(gate["gateStatus"], "observed_pass")
        self.assertTrue(gate["gateObservationRef"])
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
        self.assertLess(methods.index("session.open"), methods.index("room.dispatch"))
        opened = next(request for request in requests if request["method"] == "session.open")
        self.assertIn("<room-prompt-plan", opened["params"]["systemPrompt"])
        self.assertNotIn("运行时工具渐进披露规则", opened["params"]["systemPrompt"])
        session_context = opened["params"]["sessionContext"]
        room_context = opened["params"]["roomContext"]
        self.assertIn("Session 记忆", session_context)
        self.assertNotIn('"objective":"Execute a bounded service test."', session_context)
        self.assertIn('"objective":"Execute a bounded service test."', room_context)
        for internal_label in ('"dispatchId"', '"taskId"', '"rootId"', '"receiptId"'):
            self.assertNotIn(internal_label, room_context)
        self.assertEqual(
            opened["params"]["roomSkillPolicy"]["skillId"],
            "room-test-driven-implementation",
        )
        self.assertEqual(methods.count("room.dispatch"), 2)
        self.assertEqual(
            [request["params"]["dispatchId"] for request in requests if request["method"] == "room.dispatch"],
            ["dispatch:service", "dispatch:complete"],
        )
        first_dispatch_request = next(
            request
            for request in requests
            if request["method"] == "room.dispatch"
        )
        self.assertIn(
            "Session 记忆",
            first_dispatch_request["params"]["sessionContext"],
        )
        self.assertIn(
            '"objective":"Execute a bounded service test."',
            first_dispatch_request["params"]["roomContext"],
        )
        skill_receipt = self.service.room_skill_receipts.latest_for_session(self.session_id)
        self.assertIsNotNone(skill_receipt)
        self.assertEqual(skill_receipt["skillId"], "room-test-driven-implementation")
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
