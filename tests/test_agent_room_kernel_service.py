from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import subprocess
import threading
import time
import unittest
from collections.abc import Mapping
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

from rag_ime.agent_background_jobs import AgentBackgroundJobError
from rag_ime.agent_room_kernel import RoomKernelFenceError
from rag_ime.agent_room_skills import RoomSkillEpochRevoked
from rag_ime.agent_blocks import normalize_trusted_agent_blocks
from rag_ime.agent_room_capabilities import ToolAuthorizationError
from rag_ime.agent_room_application import _resolve_room_answer_display
from rag_ime.agent_room_kernel_application import _collaboration_tool_result
from rag_ime.agent_room_settlement import RoomCommitProposalError
from rag_ime.agent_room_runtime_coordinator import _effective_dispatch_role_id
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
from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_runtime import PiRuntimeConfig
from tests.test_pi_runtime_v2 import FAKE_HOST
from rag_ime.agent_room_skills import RoomSkillPolicy


class KernelRuntime:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.default_model_profile = "pi/test"
        self.dispatched: list[str] = []
        self.dispatch_attempts: list[int] = []
        self.cancelled: list[tuple[str, str, int]] = []
        self.surface_state = "terminated"
        self.stopped = False
        policy_root = Path(__file__).resolve().parents[1] / "integrations" / "pi"
        self.skill_policy = RoomSkillPolicy(
            policy_root / "room-skill-policy.json",
            policy_root / "skills",
        )
        self.omit_required_skill = False
        self.active_alignment_classifier = None

    def runtime_status(self):
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "status": "ready",
            "capabilities": {"runtimePrimitives": {"roomTypes": True}},
        }

    def dispatch_room(
        self,
        payload,
        *,
        message: str,
        lease_token: str,
        record_intent,
    ):
        del message, lease_token
        record_intent()
        self.dispatched.append(str(payload["dispatchId"]))
        self.dispatch_attempts.append(int(payload.get("attempt") or 0))
        intent = str(payload.get("intentKind") or "")
        stage = {
            "align": "requirements",
            "execute": "implementation",
            "review": "vision-review",
            "revise": "feedback",
            "retry": "debugging",
            "resume": "implementation",
            "wake": "implementation",
            "callback": "handoff",
            "close": "closure",
        }.get(intent, "implementation")
        if (
            self.active_alignment_classifier is not None
            and self.active_alignment_classifier(str(payload["dispatchId"]))
        ):
            stage = "requirements"
        selection = self.skill_policy.select_stage(stage)
        receipt = {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
            "capabilityEpoch": payload["capabilityEpoch"],
            "sessionId": payload["targetSessionId"],
            "turnId": (
                f"turn:{payload['dispatchId']}:"
                f"{int(payload.get('attempt') or 0) + 1}"
            ),
        }
        if (
            selection["selection"] == "required"
            and not self.omit_required_skill
        ):
            skill_id = str(selection["skillId"])
            receipt["roomSkillLoad"] = {
                "name": skill_id,
                "contentRevision": self.skill_policy.skill_hash(skill_id),
                "catalogRevision": "0" * 64,
            }
        return receipt

    def cancel_room(
        self,
        *,
        cancel_id: str,
        session_id: str,
        root_id: str,
        dispatch_id: str,
        generation: int,
        turn_id: str,
        capability_epoch: int,
    ):
        self.cancelled.append((session_id, root_id, generation))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "cancelId": cancel_id,
            "sessionId": session_id,
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "generation": generation,
            "turnId": turn_id,
            "capabilityEpoch": capability_epoch,
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

    def create(self, *args, **kwargs):
        if kwargs.get("purpose") == "delegated" and args:
            context = args[0]
            return _CompletingDelegatedRuntime(
                sessions=context.sessions,
                events=context.events,
            )
        return self.runtime

    def apply_policy(self, _policy):
        return None

    def reconfigure(self, _config):
        return None


class _CompletingDelegatedRuntime:
    def __init__(self, *, sessions, events) -> None:
        self.sessions = sessions
        self.events = events

    def prompt(self, session_id: str, _message: str) -> dict[str, object]:
        turn_id = f"turn:nested:{session_id}"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": f"message:{turn_id}",
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [
                        {
                            "id": f"text:{turn_id}",
                            "type": "text",
                            "status": "completed",
                            "presentationKind": "markdown",
                            "data": {"text": "已完成有界的私有核验。"},
                        }
                    ],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 10,
                    "completedAtMs": 11,
                },
                "usage": {"totalTokens": 32},
            },
            turn_id=turn_id,
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=turn_id,
        )
        return {"accepted": True, "turnId": turn_id}

    def abort(self, _session_id: str) -> None:
        return None

    def stop(self) -> None:
        return None


class RoomKernelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-kernel-service-")
        self.root = Path(self.tmp.name)
        subprocess.run(
            ["git", "init", "-q", str(self.root)],
            check=True,
            capture_output=True,
        )
        (self.root / ".gitignore").write_text(
            (
                "*.sqlite\n*.sqlite-*\nsessions/\nrooms/\n"
                "room-workspaces/\nagent-artifacts/\n"
            ),
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            "Room kernel service fixture.\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "add", ".gitignore", "README.md"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Room Tests",
                "-c",
                "user.email=room-tests@example.invalid",
                "commit",
                "-q",
                "-m",
                "fixture",
            ],
            check=True,
            capture_output=True,
        )
        self.factory = KernelRuntimeFactory(self.root)
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_factory=self.factory,
            room_kernel_mode="cohort",
            room_kernel_poll_seconds=60,
        )
        self.service.room_kernel_worker_loop.close()
        self.factory.runtime.active_alignment_classifier = (
            self.service.room_kernel.dispatch_is_runtime_alignment
        )
        room = self.service.create_room(
            {
                "title": "Kernel cohort",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
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
        self.service.room_kernel.create_root_with_task(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:service",
                "roomId": self.room_id,
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": str(self.participant["id"]),
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement-anchor:service@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "independentReviewRequired": False,
                "createdAtMs": 1,
            },
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:service",
                "rootId": "root:service",
                "parentTaskId": None,
                "taskKind": "work",
                "currentOwnerParticipantId": str(self.participant["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Execute a bounded service test.",
                "expectedOutput": "A typed receipt.",
                "requirementItemIds": ["requirement:service"],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "active",
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        # root:service is the suite's typed Kernel compatibility fixture. It
        # does not model product intake; product-path tests create fresh Roots
        # through post_room_message and retain the authoritative intake fence.
        with sqlite3.connect(self.service.db_path) as conn:
            rows = conn.execute(
                "SELECT receipt_id,payload_json FROM room_kernel_receipts "
                "WHERE root_id='root:service' AND receipt_kind='accepted'"
            ).fetchall()
            intake_ids = []
            for receipt_id, payload_json in rows:
                payload = json.loads(str(payload_json))
                details = payload.get("details")
                if (
                    isinstance(details, dict)
                    and details.get("purpose") == "intake_phase"
                ):
                    intake_ids.append(str(receipt_id))
            conn.executemany(
                "DELETE FROM room_kernel_receipts WHERE receipt_id=?",
                [(receipt_id,) for receipt_id in intake_ids],
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
        owner_participant_id: str | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, object]:
        return self.service.create_room_work_item(
            self.room_id,
            {
                "objective": objective,
                "expectedOutput": expected_output,
                "acceptanceCriteria": acceptance_criteria
                or ["结果满足目标并附带可复核证据"],
                "currentOwnerParticipantId": (
                    owner_participant_id
                    or str(self.participant["id"])
                ),
                "clientMessageId": (
                    client_message_id
                    or f"work:{suffix}"
                ),
            },
        )["workItem"]

    def _complete_legacy_alignment_fixture(
        self,
        accepted: dict[str, object],
    ) -> list[dict[str, object]]:
        # These older tests exercise downstream runtime/cancellation behavior,
        # not current product intake. Convert their already-materialized Root
        # to the typed legacy compatibility shape before using the historical
        # align-deliver fixture. Fresh product tests above require room_define.
        with sqlite3.connect(self.service.db_path) as conn:
            rows = conn.execute(
                "SELECT receipt_id,payload_json FROM room_kernel_receipts "
                "WHERE root_id=? AND receipt_kind='accepted'",
                (str(accepted["rootId"]),),
            ).fetchall()
            intake_receipt_ids = []
            for receipt_id, payload_json in rows:
                payload = json.loads(str(payload_json))
                details = payload.get("details")
                if (
                    isinstance(details, dict)
                    and details.get("purpose") == "intake_phase"
                ):
                    intake_receipt_ids.append(str(receipt_id))
            conn.executemany(
                "DELETE FROM room_kernel_receipts WHERE receipt_id=?",
                [(receipt_id,) for receipt_id in intake_receipt_ids],
            )
        stages = list(accepted["alignmentDispatches"])
        stage_ids = {
            str(item["dispatchId"])
            for item in stages
        }
        remaining = set(stage_ids)
        execution_ids = {
            str(item["dispatchId"])
            for item in accepted["dispatches"]
        }
        confirmations: list[dict[str, object]] = []
        for _stage in stages:
            self.assertTrue(self.service.room_kernel_worker.run_once())
            dispatch_id = str(self.factory.runtime.dispatched[-1])
            self.assertIn(dispatch_id, remaining)
            remaining.remove(dispatch_id)
            self.assertTrue(
                execution_ids.isdisjoint(self.factory.runtime.dispatched)
            )
            dispatch = self.service.room_kernel.dispatch(dispatch_id)
            session_id = str(dispatch["targetSessionId"])
            ordinal = int(dispatch["alignmentOrdinal"])
            self.assertEqual(dispatch["intentKind"], "align")
            self.assertEqual(
                [
                    item["name"]
                    for item in self.service._runtime_tool_manifest(
                        {"id": session_id}
                    )
                ],
                ["room_state", "room_post", "room_commit", "room_define"],
            )
            state_load = self.service.room_capability_tool_load(
                {
                    "sessionId": session_id,
                    "receiptId": f"load:{dispatch_id}:state",
                    "toolName": "room_state",
                    "createdAtMs": 5 + ordinal,
                }
            )["result"]
            state = self.service.execute_room_capability_tool(
                session_id,
                "room_state",
                {},
                tool_call_id=f"call:{dispatch_id}:state",
                load_receipt_id=str(state_load["receiptId"]),
            )["result"]
            commit_load = self.service.room_capability_tool_load(
                {
                    "sessionId": session_id,
                    "receiptId": f"load:{dispatch_id}:commit",
                    "toolName": "room_commit",
                    "createdAtMs": 5 + ordinal,
                }
            )["result"]
            summary = (
                f"第 {ordinal + 1} 位伙伴已读取原始请求，确认目标、交付、"
                "验收、禁区与当前无须澄清的歧义。"
            )
            self.service.execute_room_capability_tool(
                session_id,
                "room_commit",
                {
                    "decision": "deliver",
                    "summary": summary,
                    "publicSummary": summary,
                    "evidence": [
                        {
                            "acceptance": "AC-1",
                            "refs": [state["evidenceRef"]],
                        }
                    ],
                    "residualRisks": [],
                },
                tool_call_id=f"call:{dispatch_id}:commit",
                load_receipt_id=str(commit_load["receiptId"]),
            )
            settled = self.service.room_settle_lifecycle.settle(
                {
                    "sessionId": session_id,
                    "dispatchId": dispatch_id,
                    "rootId": accepted["rootId"],
                    "generation": dispatch["generation"],
                    "capabilityEpoch": dispatch["capabilityEpoch"],
                    "settleScopeId": f"scope:{dispatch_id}",
                    "settleAttempt": 1,
                    "runtimeTurnId": f"turn:{dispatch_id}:1",
                    "dispatchAttempt": dispatch["attempt"],
                    "resourceUsage": {},
                }
            )
            self.assertEqual(settled["state"], "committed")
            self.assertEqual(
                self.service.room_kernel.dispatch(dispatch_id)["state"],
                "committed",
            )
            confirmations.append(settled)
        self.assertFalse(remaining)
        posts = [
            post
            for post in self.service.room_kernel_snapshot(
                str(accepted["roomId"])
            )["posts"]
            if (
                post.get("rootId") == accepted["rootId"]
                and post.get("kind") == "alignment"
            )
        ]
        self.assertEqual(len(posts), len(stages))
        self.assertTrue(
            all(
                post["publicationSource"]["kind"] == "room_commit"
                for post in posts
            )
        )
        return confirmations

    def _open_legacy_execution_fixture(
        self,
        accepted: dict[str, object],
    ) -> list[dict[str, object]]:
        confirmations = self._complete_legacy_alignment_fixture(accepted)
        self.factory.runtime.dispatched.clear()
        self.factory.runtime.dispatch_attempts.clear()
        return confirmations

    def test_parallel_room_keeps_reviewer_out_of_the_implementation_wave(
        self,
    ) -> None:
        room = self.service.create_room(
            {
                "title": "分工明确的并行验收",
                "routingPolicy": "parallel",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {
                        "roleId": "companion-present-v1",
                        "roleVersion": "1",
                        "collaborationRole": "coordinator",
                    },
                    {
                        "roleId": "companion-firstlight-v1",
                        "roleVersion": "1",
                        "collaborationRole": "implementer",
                    },
                    {
                        "roleId": "companion-future-v1",
                        "roleVersion": "1",
                        "collaborationRole": "reviewer",
                    },
                ],
            }
        )["room"]
        facilitator, implementer, reviewer = room["participants"]
        work_item = self.service.create_room_work_item(
            str(room["id"]),
            {
                "objective": "实施者完成改动，主持者集成后再决定是否独立复核。",
                "expectedOutput": "集成后的可验证结果。",
                "acceptanceCriteria": [
                    "主持者负责权威工作区集成",
                    "实施者完成自己负责的实现与验证",
                ],
                "currentOwnerParticipantId": facilitator["id"],
                "clientMessageId": (
                    "managed-room-ingress:v2:parallel:1:"
                    "role-separated-room"
                ),
            },
        )["workItem"]

        accepted = self.service.post_room_message(
            str(room["id"]),
            {
                "message": "实施与集成并行推进；Reviewer 只在集成完成后进入。",
                "clientMessageId": "client:role-separated-room",
                "workItemId": work_item["id"],
            },
        )

        self.assertEqual(len(accepted["dispatches"]), 1)
        self.assertEqual(len(accepted["participants"]), 1)
        self.assertEqual(
            accepted["participants"][0]["id"],
            facilitator["id"],
        )
        self.assertNotEqual(
            accepted["participants"][0]["id"],
            implementer["id"],
        )
        self.assertNotEqual(
            accepted["participants"][0]["id"],
            reviewer["id"],
        )
        execution_decisions = [
            decision
            for decision in accepted["routeDecisions"]
            if decision["phase"] == "execution"
        ]
        self.assertEqual(len(execution_decisions), 1)
        task = self.service.room_kernel.task(
            str(execution_decisions[0]["taskId"])
        )
        self.assertEqual(
            task["currentOwnerParticipantId"],
            facilitator["id"],
        )
        self.assertNotIn("分工任务（独立审查）", str(task["objective"]))

        root = self.service.room_kernel.root(str(accepted["rootId"]))
        facilitator_dispatch = self.service.room_kernel.dispatch(
            str(accepted["dispatches"][0]["dispatchId"])
        )
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "room_collaborate",
        ):
            self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
                decision="deliver",
                root=root,
                task=task,
                dispatch=facilitator_dispatch,
            )

    def test_unbound_room_request_starts_one_alignment_dispatch(
        self,
    ) -> None:
        roots_before = set(self.service.room_kernel.root_ids(self.room_id))
        with patch.object(self.service, "prompt") as prompt:
            accepted = self.service.post_room_message(
                self.room_id,
                {
                    "message": "请先回答这个普通问题，不要隐式并行分工。",
                    "clientMessageId": "client:ordinary-conversation",
                },
            )

        prompt.assert_not_called()
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["executionOwner"], "kernel")
        self.assertNotIn("workItem", accepted)
        self.assertEqual(len(accepted["alignmentDispatches"]), 1)
        self.assertEqual(accepted["dispatches"], [])
        self.assertEqual(len(accepted["participants"]), 1)
        self.assertEqual(len(accepted["routeDecisions"]), 1)
        self.assertEqual(
            accepted["routeDecisions"][0]["targetParticipantId"],
            accepted["participant"]["id"],
        )
        self.assertEqual(
            accepted["routeDecisions"][0]["routingPolicy"],
            "requirement_alignment",
        )
        self.assertEqual(
            set(self.service.room_kernel.root_ids(self.room_id))
            - roots_before,
            {accepted["rootId"]},
        )
        self.assertEqual(
            accepted["alignmentDispatches"][0]["participantId"],
            accepted["participant"]["id"],
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        self.assertEqual(
            self.factory.runtime.dispatched,
            [accepted["alignmentDispatches"][0]["dispatchId"]],
        )
        alignment_dispatch = self.service.room_kernel.dispatch(
            str(accepted["alignmentDispatches"][0]["dispatchId"])
        )
        alignment_task = self.service.room_kernel.task(
            str(alignment_dispatch["taskId"])
        )
        self.assertIn(
            "请求完整时不要索要确认",
            alignment_task["objective"],
        )
        self.assertIn("直接用 room_define", alignment_task["objective"])
        self.assertIn(
            "有实质歧义时用 room_commit wait 一次只提出一个最小必要问题",
            alignment_task["objective"],
        )
        self.assertIn(
            "定义后由 Facilitator 先执行",
            alignment_task["expectedOutput"],
        )

    def test_product_alignment_dispatch_cannot_deliver_before_room_define(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "请求完整时直接定义，再进入实现。",
                "clientMessageId": "client:align-cannot-deliver",
            },
        )
        dispatch_id = str(
            accepted["alignmentDispatches"][0]["dispatchId"]
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        dispatch = self.service.room_kernel.dispatch(dispatch_id)
        session_id = str(dispatch["targetSessionId"])
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": "load:align-cannot-deliver:state",
                "toolName": "room_state",
                "createdAtMs": 5,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            session_id,
            "room_state",
            {},
            tool_call_id="call:align-cannot-deliver:state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        commit_load = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": "load:align-cannot-deliver:commit",
                "toolName": "room_commit",
                "createdAtMs": 6,
            }
        )["result"]

        self.service.execute_room_capability_tool(
            session_id,
            "room_commit",
            {
                "decision": "deliver",
                "summary": "需求完整，直接完成本轮。",
                "publicSummary": "需求完整，直接完成本轮。",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": [state["evidenceRef"]],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:align-cannot-deliver:commit",
            load_receipt_id=str(commit_load["receiptId"]),
        )
        with self.assertRaisesRegex(RoomKernelFenceError, "room_define"):
            self.service.room_settle_lifecycle.settle(
                {
                    "sessionId": session_id,
                    "dispatchId": dispatch_id,
                    "rootId": accepted["rootId"],
                    "generation": dispatch["generation"],
                    "capabilityEpoch": dispatch["capabilityEpoch"],
                    "settleScopeId": f"scope:{dispatch_id}",
                    "settleAttempt": 1,
                    "runtimeTurnId": f"turn:{dispatch_id}:1",
                    "dispatchAttempt": dispatch["attempt"],
                    "resourceUsage": {},
                }
            )

        self.assertEqual(
            self.service.room_kernel.dispatch(dispatch_id)["state"],
            "running",
        )

    def test_authoritative_intake_without_definition_cannot_open_report(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "模拟历史上跳过 room_define 的已完成产品 Root。",
                "clientMessageId": "client:intake-without-definition",
            },
        )
        root_id = str(accepted["rootId"])
        dispatch_id = str(
            accepted["alignmentDispatches"][0]["dispatchId"]
        )
        task_id = str(
            self.service.room_kernel.dispatch(dispatch_id)["taskId"]
        )
        # Materialize the historical bad state directly: the authoritative
        # intake receipt exists, but the alignment Task was terminalized
        # without ever writing the room_define fence.
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='committed' "
                "WHERE dispatch_id=?",
                (dispatch_id,),
            )
            conn.execute(
                "UPDATE room_kernel_outbox SET state='completed' "
                "WHERE dispatch_id=?",
                (dispatch_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='completed' "
                "WHERE task_id=?",
                (task_id,),
            )
            conn.execute(
                "UPDATE room_kernel_roots SET acceptance_criteria_json='[]', "
                "covered_criteria_json='[]' WHERE root_id=?",
                (root_id,),
            )

        readiness = self.service.room_kernel.report_readiness(root_id)
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["reason"], "definition_required")
        self.assertEqual(
            readiness["lanePlan"]["fences"],
            [{"reason": "definition_required"}],
        )

        root = self.service.room_kernel.root(root_id)
        reporter_id = str(root["reporterParticipantId"])
        reporter = self.service.rooms.participant(reporter_id)
        report = self.service.room_kernel.ensure_report_dispatch(
            root_id,
            reporter_participant_id=reporter_id,
            reporter_session_id=str(reporter["sessionId"]),
            workspace={
                "workspacePolicy": "read_only",
                "workspaceSnapshotRef": "workspace-snapshot:no-definition",
            },
            now_ms=30,
        )
        self.assertFalse(report["created"])
        self.assertEqual(
            report["receipt"]["details"]["reason"],
            "definition_required",
        )

    def test_required_stage_skill_omission_cancels_root_fail_closed(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "核对必要阶段技能缺失时的安全退出。",
                "clientMessageId": "client:missing-required-stage-skill",
            },
        )
        self.factory.runtime.omit_required_skill = True

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "omitted the Skill required",
        ):
            self.service.room_kernel_worker.run_once()

        self.assertEqual(
            self.service.room_kernel.root(str(accepted["rootId"]))["state"],
            "cancelled",
        )

    def test_single_explicit_participant_selects_opening_facilitator_without_bypassing_alignment(
        self,
    ) -> None:
        requested = self.service.rooms.get(self.room_id)["participants"][2]
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": f"@{requested['displayName']} 请直接回答这个问题",
                "clientMessageId": "client:explicit-conversation",
                "participantIds": [str(requested["id"])],
            },
        )

        self.assertNotIn("workItem", accepted)
        self.assertEqual(len(accepted["alignmentDispatches"]), 1)
        self.assertEqual(accepted["dispatches"], [])
        self.assertEqual(accepted["participants"], [requested])
        self.assertEqual(accepted["participant"]["id"], requested["id"])
        dispatch = self.service.room_kernel.dispatch(
            str(accepted["alignmentDispatches"][0]["dispatchId"])
        )
        self.assertEqual(
            dispatch["targetParticipantId"],
            requested["id"],
        )
        self.assertEqual(dispatch["targetParticipantId"], requested["id"])

    def test_single_opening_mention_can_select_the_companion_whose_default_job_is_reviewer(
        self,
    ) -> None:
        room = self.service.create_room(
            {
                "title": "开场点名覆盖默认接手人",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {
                        "roleId": "companion-future-v1",
                        "roleVersion": "1",
                        "collaborationRole": "coordinator",
                    },
                    {
                        "roleId": "companion-present-v1",
                        "roleVersion": "1",
                        "collaborationRole": "implementer",
                    },
                    {
                        "roleId": "companion-firstlight-v1",
                        "roleVersion": "1",
                        "collaborationRole": "reviewer",
                    },
                ],
            }
        )["room"]
        requested = next(
            participant
            for participant in room["participants"]
            if participant["collaborationRole"] == "reviewer"
        )

        accepted = self.service.post_room_message(
            str(room["id"]),
            {
                "message": f"@{requested['displayName']} 请接手这个任务。",
                "clientMessageId": "client:explicit-reviewer-default-job",
                "participantIds": [str(requested["id"])],
            },
        )

        self.assertEqual(
            accepted["root"]["facilitatorParticipantId"],
            requested["id"],
        )
        self.assertEqual(
            accepted["alignmentDispatches"][0]["participantId"],
            requested["id"],
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        with sqlite3.connect(self.service.db_path) as conn:
            binding_payload = json.loads(
                str(
                    conn.execute(
                        "SELECT participant_binding_json "
                        "FROM room_v2_capability_runtime_bindings "
                        "WHERE session_id=?",
                        (str(requested["sessionId"]),),
                    ).fetchone()[0]
                )
            )
        self.assertIn(
            "/coordinator?",
            str(binding_payload["collaborationRoleRef"]),
        )
        defined = self.service.room_application.define_room(
            str(room["id"]),
            dispatch_id=str(
                accepted["alignmentDispatches"][0]["dispatchId"]
            ),
            invocation_receipt_id="invoke:explicit-reviewer-default-job",
            arguments={
                "objective": "完成被点名的任务",
                "expectedOutput": "由开场点名伙伴负责的可验证结果",
                "requirements": ["开场点名决定本轮接手人"],
                "acceptanceCriteria": [
                    {
                        "statement": "被点名伙伴进入实施阶段",
                        "fullNameZh": "开场点名伙伴完成接手",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
            },
        )
        self.assertEqual(
            defined["executionDispatch"]["targetParticipantId"],
            requested["id"],
        )

    def test_dispatch_job_overrides_roster_defaults_after_opening_facilitator_changes(
        self,
    ) -> None:
        root = {"facilitatorParticipantId": "firstlight"}
        self.assertEqual(
            _effective_dispatch_role_id(
                dispatch={
                    "intentKind": "align",
                    "targetParticipantId": "firstlight",
                },
                task={"taskKind": "work"},
                root=root,
            ),
            "coordinator",
        )
        self.assertEqual(
            _effective_dispatch_role_id(
                dispatch={
                    "intentKind": "execute",
                    "targetParticipantId": "future-default-coordinator",
                },
                task={
                    "taskKind": "work",
                    "workspacePolicy": "isolated_writable",
                },
                root=root,
            ),
            "implementer",
        )
        self.assertEqual(
            _effective_dispatch_role_id(
                dispatch={
                    "intentKind": "execute",
                    "targetParticipantId": "present",
                },
                task={"taskKind": "work", "workspacePolicy": "read_only"},
                root=root,
            ),
            "researcher",
        )
        self.assertEqual(
            _effective_dispatch_role_id(
                dispatch={
                    "intentKind": "review",
                    "targetParticipantId": "present",
                },
                task={"taskKind": "review", "workspacePolicy": "read_only"},
                root=root,
            ),
            "reviewer",
        )

    def test_default_companion_is_initial_facilitator_without_a_mention(self) -> None:
        room = self.service.create_room(
            {
                "title": "默认主持伙伴",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        future = next(
            participant
            for participant in room["participants"]
            if participant["roleId"] == "companion-future-v1"
        )
        self.assertEqual(future["displayName"], "澄·远")
        self.assertEqual(future["collaborationRole"], "coordinator")

        accepted = self.service.post_room_message(
            str(room["id"]),
            {
                "message": "我要完成一个终端工具。",
                "clientMessageId": "client:default-facilitator",
            },
        )

        self.assertEqual(
            accepted["root"]["facilitatorParticipantId"],
            future["id"],
        )
        self.assertEqual(
            accepted["alignmentDispatches"][0]["participantId"],
            future["id"],
        )

    def test_explicit_multi_participant_request_still_aligns_once(self) -> None:
        room = self.service.create_room(
            {
                "title": "显式提及并行",
                "routingPolicy": "parallel",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        participants = list(room["participants"])
        requested = [
            str(participants[0]["id"]),
            str(participants[1]["id"]),
        ]

        accepted = self.service.post_room_message(
            str(room["id"]),
            {
                "message": "请这两位伙伴分别回答。",
                "clientMessageId": "client:explicit-fanout",
                "participantIds": requested,
            },
        )

        self.assertNotIn("workItem", accepted)
        self.assertEqual(len(accepted["alignmentDispatches"]), 1)
        self.assertEqual(accepted["dispatches"], [])
        default_facilitator = next(
            participant
            for participant in participants
            if participant["roleId"] == "companion-future-v1"
        )
        self.assertEqual(
            accepted["alignmentDispatches"][0]["participantId"],
            str(default_facilitator["id"]),
        )
        self.assertEqual(
            [item["routingPolicy"] for item in accepted["routeDecisions"]],
            ["requirement_alignment"],
        )

    def test_auto_managed_root_cannot_claim_delivery_without_partner_receipts(
        self,
    ) -> None:
        default_facilitator_id = str(
            next(
                participant
                for participant in self.service.rooms.get(self.room_id)[
                    "participants"
                ]
                if participant["roleId"] == "companion-future-v1"
            )["id"]
        )
        work_item = self._create_work_item(
            "managed-receipt-fence",
            objective="并行拆分实现和复核。",
            owner_participant_id=default_facilitator_id,
            client_message_id=(
                "managed-room-ingress:v2:natural:2:"
                "managed-receipt-fence"
            ),
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": (
                    "并行拆分实现和复核，等待伙伴完成后综合一个网页小游戏。"
                ),
                "clientMessageId": "client:auto-managed-receipt-fence",
                "workItemId": work_item["id"],
            },
        )
        dispatch_id = str(accepted["dispatches"][0]["dispatchId"])
        dispatch = self.service.room_kernel.dispatch(dispatch_id)
        root = self.service.room_kernel.root(
            str(accepted["rootId"])
        )
        task = self.service.room_kernel.task(
            str(accepted["taskId"])
        )

        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "公开结果尚未到齐",
        ):
            self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
                decision="deliver",
                root=root,
                task=task,
                dispatch=dispatch,
            )

        self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
            decision="blocked",
            root=root,
            task=task,
            dispatch=dispatch,
        )

    def test_managed_collaboration_counts_only_published_child_results(
        self,
    ) -> None:
        room = self.service.rooms.get(self.room_id)
        moderator_id = str(room["moderatorParticipantId"])
        peers = [
            participant
            for participant in room["participants"]
            if str(participant["id"]) != moderator_id
        ]
        removed_peer = peers[-1]
        self.service.rooms.remove_participant(
            self.room_id,
            str(removed_peer["id"]),
        )
        work_item = self._create_work_item(
            "public-child-result-fence",
            objective="等待伙伴公开结果后综合交付。",
            owner_participant_id=moderator_id,
            client_message_id=(
                "managed-room-ingress:v2:natural:1:"
                "public-child-result-fence"
            ),
        )
        private_target = peers[0]
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": (
                    "让唯一伙伴完成独立检查，等待公开结果后再综合交付。"
                ),
                "clientMessageId": "client:public-child-result-fence",
                "workItemId": work_item["id"],
            },
        )
        public_target = self.service.add_room_participant(
            self.room_id,
            {
                "roleId": removed_peer["roleId"],
                "roleVersion": removed_peer["roleVersion"],
            },
        )["participant"]
        self._open_legacy_execution_fixture(accepted)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        parent_dispatch = self.service.room_kernel.dispatch(
            str(accepted["dispatches"][0]["dispatchId"])
        )
        coordinator_session_id = str(
            parent_dispatch["targetSessionId"]
        )
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": coordinator_session_id,
                "receiptId": "load:public-child-state",
                "toolName": "room_state",
                "createdAtMs": 5,
            }
        )["result"]
        collaborate_load = self.service.room_capability_tool_load(
            {
                "sessionId": coordinator_session_id,
                "receiptId": "load:public-child-collaborate",
                "toolName": "room_collaborate",
                "createdAtMs": 5,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            coordinator_session_id,
            "room_state",
            {},
            tool_call_id="call:public-child-state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        private_target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if str(item["displayName"])
            == str(private_target["displayName"])
        )
        public_target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if str(item["displayName"])
            == str(public_target["displayName"])
        )
        private_result = self.service.execute_room_capability_tool(
            coordinator_session_id,
            "room_collaborate",
            {
                "targetParticipantRef": private_target_ref,
                "objective": "独立检查 private",
                "expectedOutput": "公开、可复核的检查结果",
                "intent": "execute",
                "acceptance": ["AC-1"],
                "workspacePolicy": "read_only",
            },
            tool_call_id="call:public-child:private",
            load_receipt_id=str(collaborate_load["receiptId"]),
        )["result"]
        self.assertTrue(private_result["accepted"])

        children = self.service.room_kernel.collaboration_children(
            str(accepted["rootId"])
        )
        self.assertEqual(len(children), 1)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        private_child = self.service.room_kernel.collaboration_children(
            str(accepted["rootId"])
        )[0]
        private_criterion = str(
            self.service.room_kernel.task(
                str(private_child["taskId"])
            )["acceptanceCriterionIds"][0]
        )

        private_commit_id = "commit:public-child:private"
        self.service.room_kernel.apply_commit(
            {
                "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
                "commitId": private_commit_id,
                "dispatchId": private_child["dispatchId"],
                "action": "complete",
                "contentHash": "sha256:public-child-private",
                "postProposal": None,
                "qualityGateReceipt": {
                    "schemaVersion": (
                        "wisdom-weasel.room-quality-gate-receipt.v1"
                    ),
                    "receiptId": f"quality:{private_commit_id}",
                    "rootId": accepted["rootId"],
                    "taskId": private_child["taskId"],
                    "dispatchId": private_child["dispatchId"],
                    "generation": 0,
                    "originalRequestChecked": True,
                    "verdict": "ready_to_deliver",
                    "items": [
                        {
                            "criterionId": private_criterion,
                            "status": "pass",
                            "evidenceRefs": ["verification:private-child"],
                        }
                    ],
                    "residualRisks": [],
                    "createdAtMs": 10,
                },
                "evidenceRefs": ["verification:private-child"],
                "requirementCoverage": [private_criterion],
                "createdAtMs": 10,
            },
            generation=0,
            now_ms=10,
        )
        root = self.service.room_kernel.root(str(accepted["rootId"]))
        task = self.service.room_kernel.task(str(accepted["taskId"]))
        private_projection = (
            self.service.room_kernel.collaboration_children(
                str(accepted["rootId"])
            )
        )
        self.assertFalse(private_projection[0]["resultPublic"])
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "已公开 0 位",
        ):
            self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
                decision="deliver",
                root=root,
                task=task,
                dispatch=parent_dispatch,
            )

        public_result = self.service.execute_room_capability_tool(
            coordinator_session_id,
            "room_collaborate",
            {
                "targetParticipantRef": public_target_ref,
                "objective": "独立检查 public",
                "expectedOutput": "公开、可复核的检查结果",
                "intent": "execute",
                "acceptance": ["AC-1"],
                "workspacePolicy": "read_only",
            },
            tool_call_id="call:public-child:public",
            load_receipt_id=str(collaborate_load["receiptId"]),
        )["result"]
        self.assertTrue(public_result["accepted"])
        children = self.service.room_kernel.collaboration_children(
            str(accepted["rootId"])
        )
        self.assertEqual(len(children), 2)
        public_child = children[1]
        self.assertTrue(self.service.room_kernel_worker.run_once())
        public_criterion = str(
            self.service.room_kernel.task(
                str(public_child["taskId"])
            )["acceptanceCriterionIds"][0]
        )

        public_commit_id = "commit:public-child:published"
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:public-child:published",
            "roomId": self.room_id,
            "rootId": accepted["rootId"],
            "generation": 0,
            "taskId": public_child["taskId"],
            "dispatchId": public_child["dispatchId"],
            "authorActorRef": public_child["targetParticipantId"],
            "kind": "work_result",
            "visibility": "room",
            "content": "伙伴公开提交了一项可复核检查结果。",
            "idempotencyKey": "post:public-child:published",
            "publicationSource": {
                "kind": "room_commit",
                "ref": public_commit_id,
            },
            "createdAtMs": 11,
        }
        self.service.room_kernel.apply_commit(
            {
                "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
                "commitId": public_commit_id,
                "dispatchId": public_child["dispatchId"],
                "action": "post",
                "contentHash": "sha256:public-child-published",
                "postProposal": post,
                "continuation": {"decision": "complete"},
                "qualityGateReceipt": {
                    "schemaVersion": (
                        "wisdom-weasel.room-quality-gate-receipt.v1"
                    ),
                    "receiptId": f"quality:{public_commit_id}",
                    "rootId": accepted["rootId"],
                    "taskId": public_child["taskId"],
                    "dispatchId": public_child["dispatchId"],
                    "generation": 0,
                    "originalRequestChecked": True,
                    "verdict": "ready_to_deliver",
                    "items": [
                        {
                            "criterionId": public_criterion,
                            "status": "pass",
                            "evidenceRefs": ["verification:public-child"],
                        }
                    ],
                    "residualRisks": [],
                    "createdAtMs": 11,
                },
                "evidenceRefs": ["verification:public-child"],
                "requirementCoverage": [public_criterion],
                "createdAtMs": 11,
            },
            generation=0,
            now_ms=11,
            post_proposal=post,
        )
        before_publication = (
            self.service.room_kernel.collaboration_children(
                str(accepted["rootId"])
            )
        )
        self.assertEqual(
            [child["resultPublic"] for child in before_publication],
            [False, False],
        )

        _published, created = (
            self.service.room_context_ledger.publish_post(post)
        )
        self.assertTrue(created)
        _replayed, replay_created = (
            self.service.room_context_ledger.publish_post(post)
        )
        self.assertFalse(replay_created)
        after_publication = (
            self.service.room_kernel.collaboration_children(
                str(accepted["rootId"])
            )
        )
        self.assertEqual(
            [child["resultPublic"] for child in after_publication],
            [False, True],
        )
        public_participants = {
            str(child["targetParticipantId"])
            for child in after_publication
            if child["resultPublic"] is True
        }
        self.assertEqual(
            public_participants,
            {str(public_target["id"])},
        )
        self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
            decision="deliver",
            root=self.service.room_kernel.root(str(accepted["rootId"])),
            task=task,
            dispatch=parent_dispatch,
        )

    def test_kernel_intake_creates_alignment_before_any_execution(
        self,
    ) -> None:
        roots_before = self.service.room_kernel.root_ids(self.room_id)
        message = "没有预建任务卡时，普通消息先进入需求对齐。"

        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": message,
                "clientMessageId": "client:ordinary-first-message",
            },
        )

        self.assertNotIn("workItem", accepted)
        self.assertEqual(len(accepted["alignmentDispatches"]), 1)
        self.assertEqual(accepted["dispatches"], [])
        self.assertEqual(len(accepted["participants"]), 1)
        self.assertEqual(
            accepted["participant"]["id"],
            accepted["alignmentDispatches"][0]["participantId"],
        )
        roots_after = self.service.room_kernel.root_ids(self.room_id)
        self.assertEqual(
            set(roots_after) - set(roots_before),
            {accepted["rootId"]},
        )
        self.assertEqual(len(roots_after), len(roots_before) + 1)
        self.assertEqual(self.factory.runtime.dispatched, [])

    def test_one_opening_mention_selects_initial_facilitator(
        self,
    ) -> None:
        requested_participant_id = str(self.participant["id"])

        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "请指定伙伴直接核对恢复链路。",
                "clientMessageId": "client:explicit-conversation-target",
                "participantIds": [requested_participant_id],
            },
        )

        self.assertNotIn("workItem", accepted)
        self.assertEqual(len(accepted["alignmentDispatches"]), 1)
        self.assertEqual(accepted["dispatches"], [])
        facilitator_id = str(accepted["root"]["facilitatorParticipantId"])
        self.assertEqual(accepted["participant"]["id"], requested_participant_id)
        self.assertEqual(
            accepted["alignmentDispatches"][0]["participantId"],
            requested_participant_id,
        )
        self.assertEqual(facilitator_id, requested_participant_id)



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
        route_count = (
            len(accepted["alignmentDispatches"])
            + len(accepted["dispatches"])
        )
        self.assertEqual(
            [event["eventType"] for event in accepted["timelineEvents"]],
            ["user_message", *(["route_decision"] * route_count)],
        )
        participant_names = {
            str(item["id"]): str(item["displayName"])
            for item in self.service.rooms.get(self.room_id)["participants"]
        }
        self.assertEqual(
            [
                event["payload"].get("summary")
                for event in accepted["timelineEvents"][1:]
            ],
            [
                *[
                    f"{participant_names[str(item['participantId'])]} "
                    "正在判断是否需要澄清"
                    for item in accepted["alignmentDispatches"]
                ],
                f"{self.participant['displayName']} 已进入执行队列",
            ],
        )
        self.assertEqual(self.factory.runtime.dispatched, [])
        alignment_dispatch = self.service.room_kernel.dispatch(
            str(accepted["alignmentDispatches"][0]["dispatchId"])
        )
        alignment_task = self.service.room_kernel.task(
            str(alignment_dispatch["taskId"])
        )
        self.assertIn(
            "请求完整时不要索要确认",
            alignment_task["objective"],
        )
        self.assertIn("直接用 room_define", alignment_task["objective"])
        self.assertNotIn("room_commit deliver", alignment_task["objective"])
        self.assertNotIn("执行前门禁", alignment_task["objective"])
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
        self.assertEqual(replay["rootId"], accepted["rootId"])
        self.assertEqual(replay["timelineEvents"], accepted["timelineEvents"])
        self.assertEqual(
            len(self.service.room_kernel_snapshot(self.room_id)["posts"]),
            len(snapshot["posts"]),
        )

    def test_agent_and_room_entry_race_is_rejected_before_creating_a_root(self) -> None:
        roots_before = self.service.room_kernel.root_ids(self.room_id)
        work_item_ids_before = {
            str(item["id"])
            for item in self.service.room_work.list(room_id=self.room_id)
        }
        room = self.service.rooms.get(self.room_id)
        moderator = next(
            participant
            for participant in room["participants"]
            if participant["id"] == room["moderatorParticipantId"]
        )

        with self.service._direct_agent_entry(
            str(moderator["sessionId"])
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Room 成员 Session 正在接收 Agent 消息",
            ):
                self.service.post_room_message(
                    self.room_id,
                    {
                        "message": "不要与 Agent 输入并发抢同一个 Session",
                        "clientMessageId": "client:mode-race",
                        "participantIds": [
                            str(moderator["id"])
                        ],
                    },
                )

        self.assertEqual(
            self.service.room_kernel.root_ids(self.room_id),
            roots_before,
        )
        self.assertEqual(
            {
                str(item["id"])
                for item in self.service.room_work.list(room_id=self.room_id)
            },
            work_item_ids_before,
        )

    def test_terminal_root_never_retains_session_ownership(self) -> None:
        self.service.room_kernel.enqueue_dispatch(
            self._dispatch(),
            now_ms=3,
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        self.assertIsNotNone(
            self.service.room_kernel.session_binding(self.session_id)
        )

        for terminal_state in (
            "cancelled",
            "cancelled_with_unknowns",
            "completed",
            "failed",
        ):
            with self.subTest(terminal_state=terminal_state):
                with sqlite3.connect(self.service.db_path) as conn:
                    conn.execute(
                        """UPDATE room_kernel_roots
                           SET state = ?
                           WHERE root_id = 'root:service'""",
                        (terminal_state,),
                    )
                self.assertIsNone(
                    self.service.room_kernel.session_binding(
                        self.session_id
                    )
                )
                self.assertEqual(
                    self.service.room_kernel.room_active_runtime_targets(
                        self.room_id
                    ),
                    [],
                )

    def test_faulted_unbound_participant_remains_recoverable(self) -> None:
        target = next(
            item
            for item in self.service.rooms.get(self.room_id)[
                "participants"
            ]
            if item["status"] == "active"
            and item["id"] != self.participant["id"]
        )
        target_session_id = str(target["sessionId"])
        self.assertIsNone(
            self.service.room_kernel.session_binding(target_session_id)
        )
        self.service.sessions.set_status(
            target_session_id,
            "faulted",
        )

        self.service.room_application._assert_targets_available(
            [target]
        )
        self.assertEqual(
            self.service.sessions.get(target_session_id)["status"],
            "faulted",
        )

    def test_room_collaborate_retires_orphaned_target_capability(
        self,
    ) -> None:
        self._set_parent_acceptance("criterion:service")
        room = self.service.rooms.get(self.room_id)
        target = next(
            item
            for item in room["participants"]
            if item["status"] == "active"
            and item["id"] != self.participant["id"]
        )
        target_session_id = str(target["sessionId"])
        stale_root_id = "root:stale-target"
        stale_task_id = "task:stale-target"
        stale_dispatch_id = "dispatch:stale-target"
        self.service.room_kernel.create_root_with_task(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": stale_root_id,
                "roomId": self.room_id,
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": str(target["id"]),
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": (
                    "requirement-anchor:stale-target@sha256:test"
                ),
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "independentReviewRequired": False,
                "createdAtMs": 3,
            },
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": stale_task_id,
                "rootId": stale_root_id,
                "parentTaskId": None,
                "taskKind": "work",
                "currentOwnerParticipantId": str(target["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Leave a crash-interrupted capability.",
                "expectedOutput": "A recoverable target Session.",
                "requirementItemIds": ["requirement:stale"],
                "acceptanceCriterionIds": ["criterion:stale"],
                "revision": 0,
                "state": "active",
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("criterion:stale",),
            now_ms=3,
        )
        self.service.room_kernel.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": stale_dispatch_id,
                "rootId": stale_root_id,
                "taskId": stale_task_id,
                "parentDispatchId": None,
                "generation": 0,
                "hopCount": 0,
                "depth": 0,
                "budgetCost": 1,
                "targetSessionId": target_session_id,
                "targetParticipantId": str(target["id"]),
                "triggerId": "trigger:stale-target",
                "intentKind": "execute",
                "idempotencyKey": stale_dispatch_id,
                "attempt": 0,
                "capabilityEpoch": 2,
                "runtimeProfileRevision": (
                    "runtime-profile:stale-target"
                ),
                "state": "pending",
            },
            now_ms=5,
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        stale_binding = self.service.room_capabilities.runtime_binding(
            target_session_id
        )
        self.assertIsNotNone(stale_binding)
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                """UPDATE room_kernel_roots
                   SET state = 'cancelled'
                   WHERE root_id = ?""",
                (stale_root_id,),
            )
        self.assertIsNone(
            self.service.room_kernel.session_binding(
                target_session_id
            )
        )

        self.service.room_kernel.enqueue_dispatch(
            self._dispatch(),
            now_ms=6,
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:orphan-recovery-state",
                "toolName": "room_state",
                "createdAtMs": 7,
            }
        )["result"]
        collaborate_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:orphan-recovery-collaborate",
                "toolName": "room_collaborate",
                "createdAtMs": 7,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:orphan-recovery-state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if item["displayName"] == target["displayName"]
        )
        with patch(
            "rag_ime.agent_room_kernel_application.time.time",
            return_value=0.008,
        ):
            collaboration = self.service.execute_room_capability_tool(
                self.session_id,
                "room_collaborate",
                {
                    "targetParticipantRef": target_ref,
                    "objective": (
                        "Resume work after a Runtime Host restart."
                    ),
                    "expectedOutput": "A managed child result.",
                    "intent": "execute",
                    "acceptance": ["AC-1"],
                    "workspacePolicy": "read_only",
                },
                tool_call_id="call:orphan-recovery-collaborate",
                load_receipt_id=str(
                    collaborate_load["receiptId"]
                ),
            )

        self.assertTrue(collaboration["result"]["accepted"])
        with sqlite3.connect(self.service.db_path) as conn:
            stale_state = conn.execute(
                """SELECT state
                   FROM room_v2_capability_runtime_bindings
                   WHERE session_id = ? AND manifest_id = ?""",
                (
                    target_session_id,
                    str(stale_binding["manifestId"]),
                ),
            ).fetchone()
        self.assertEqual(stale_state[0], "revoked")

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
        self._open_legacy_execution_fixture(accepted)
        self.service.room_kernel_worker.run_once()
        runtime_turn = f"turn:{dispatch['dispatchId']}:1"
        self.service.events.publish(
            self.session_id,
            "text_delta",
            {"messageId": "draft:live", "delta": "正在检查"},
            turn_id=runtime_turn,
        )
        self.service.events.publish(
            self.session_id,
            "tool_started",
            {"toolCallId": "tool:live", "toolName": "workspace_read"},
            turn_id=runtime_turn,
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
            turn_id=runtime_turn,
        )
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "draft:live",
                    "sessionId": self.session_id,
                    "turnId": runtime_turn,
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 20,
                    "completedAtMs": 21,
                }
            },
            turn_id=runtime_turn,
        )
        self.assertTrue(self.service.events.flush())

        runtime_events = [
            event
            for event in self.service.rooms.list_events(self.room_id)
            if (
                event["turnId"] == accepted["rootId"]
                and event.get("payload", {}).get("data", {}).get(
                    "dispatchId"
                ) == dispatch["dispatchId"]
            )
        ]
        self.assertEqual(
            [event["eventType"] for event in runtime_events],
            [
                "participant_delta",
                "participant_activity",
                "participant_activity",
                "participant_activity",
            ],
        )
        self.assertEqual(
            runtime_events[-1]["payload"]["data"]["status"],
            "draft_ready",
        )
        self.assertNotIn(
            "participant_message",
            [event["eventType"] for event in runtime_events],
        )
        self.assertNotIn(
            "room_post",
            [event["eventType"] for event in runtime_events],
        )

    def test_managed_runtime_failure_blocks_then_operator_continues_failed_work(self) -> None:
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
        self._open_legacy_execution_fixture(accepted)
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
            turn_id=f"turn:{dispatch_id}:1",
            created_at_ms=30,
        )
        self.assertTrue(self.service.events.flush())

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
            runtime_turn_id=f"turn:{dispatch_id}:1",
            dispatch_attempt=0,
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

        retry_receipt = self.service.apply_room_kernel_command(
            self.room_id,
            {
                "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
                "commandId": "command:retry-runtime-failure",
                "rootId": root_id,
                "roomId": self.room_id,
                "commandKind": "retry_root",
                "targetKind": "root",
                "targetId": root_id,
                "sourceKind": "control_center",
                "sourceId": "test",
                "idempotencyKey": "retry-runtime-failure:v1",
                "generation": int(root["generation"]),
                "payload": {},
                "createdAtMs": 40,
            },
            caller_authorized=True,
        )
        retried_dispatch_id = str(
            retry_receipt["details"]["retriedDispatchIds"][0]
        )
        self.assertEqual(retry_receipt["receiptKind"], "root_retried")
        self.assertEqual(retry_receipt["status"], "applied")
        self.assertNotEqual(retried_dispatch_id, dispatch_id)
        self.assertEqual(
            self.service.room_kernel.root(root_id)["state"],
            "running",
        )
        self.assertEqual(
            self.service.room_kernel.task(task_id)["state"],
            "active",
        )
        self.assertEqual(
            self.service.room_kernel.dispatch(retried_dispatch_id)["state"],
            "pending",
        )
        self.assertEqual(
            self.service.room_kernel.outbox(retried_dispatch_id)["state"],
            "pending",
        )
        self.assertEqual(
            self.service.room_work.get(
                str(work_item["id"]),
                room_id=self.room_id,
            )["state"],
            "active",
        )

        resumed = self.service.room_kernel_worker.run_once()
        self.assertEqual(
            resumed["details"]["dispatchId"],
            retried_dispatch_id,
        )
        self.assertEqual(self.factory.runtime.dispatched[-1], retried_dispatch_id)
        self.assertEqual(self.factory.runtime.dispatch_attempts[-1], 1)

    def test_transient_provider_failure_without_tools_reuses_managed_dispatch(
        self,
    ) -> None:
        work_item = self._create_work_item(
            "runtime-retry",
            objective="在无工具副作用时恢复一次瞬时 Provider 中断",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "在无工具副作用时恢复一次瞬时 Provider 中断",
                "clientMessageId": "client:runtime-retry",
                "participantIds": [str(self.participant["id"])],
                "workItemId": work_item["id"],
            },
        )
        dispatch = accepted["dispatches"][0]
        dispatch_id = str(dispatch["dispatchId"])
        self._open_legacy_execution_fixture(accepted)
        self.service.room_kernel_worker.run_once()
        self.assertEqual(self.factory.runtime.dispatched, [dispatch_id])
        binding_before = self.service.room_capabilities.runtime_binding(
            self.session_id
        )
        self.assertIsNotNone(binding_before)

        self.service.events.publish(
            self.session_id,
            "turn_failed",
            {
                "error": "fetch failed",
                "failureKind": "transient_provider_failure",
                "reasonCode": "provider_transport_failure",
                "retryable": True,
                "hadToolActivity": False,
            },
            turn_id=f"turn:{dispatch_id}:1",
            created_at_ms=30,
        )
        self.assertTrue(self.service.events.flush())

        stored = self.service.room_kernel.dispatch(dispatch_id)
        outbox = self.service.room_kernel.outbox(dispatch_id)
        self.assertEqual(stored["state"], "retry_wait")
        self.assertEqual(outbox["state"], "retry_wait")
        self.assertEqual(
            self.service.room_kernel.root(str(stored["rootId"]))["state"],
            "running",
        )
        self.assertEqual(
            self.service.room_kernel.task(str(stored["taskId"]))["state"],
            "active",
        )
        self.assertEqual(
            self.service.room_kernel.resource_limits(
                str(stored["rootId"])
            )["retry_used"],
            1,
        )
        self.assertEqual(
            self.service.room_kernel.counts(str(stored["rootId"]))[
                "deadLetters"
            ],
            0,
        )
        binding_waiting = self.service.room_capabilities.runtime_binding(
            self.session_id
        )
        self.assertIsNotNone(binding_waiting)
        self.assertEqual(
            binding_waiting["manifestHash"],
            binding_before["manifestHash"],
        )
        public = [
            item
            for item in self.service.rooms.list_events(self.room_id)
            if item["turnId"] == str(stored["rootId"])
            and item["eventType"] == "participant_activity"
        ]
        self.assertEqual(len(public), 1)
        self.assertEqual(
            public[0]["payload"]["data"]["status"],
            "retry_wait",
        )
        self.assertNotIn("fetch failed", str(public[0]))

        self.service.room_kernel_worker.clock_ms = (
            lambda: int(outbox["availableAtMs"])
        )
        retried = self.service.room_kernel_worker.run_once()

        self.assertIsNotNone(retried)
        self.assertEqual(
            self.factory.runtime.dispatched,
            [dispatch_id, dispatch_id],
        )
        self.assertEqual(
            self.factory.runtime.dispatch_attempts,
            [0, 1],
        )
        self.assertEqual(
            self.service.room_kernel.dispatch(dispatch_id)["state"],
            "running",
        )
        self.assertEqual(
            self.service.room_kernel.lease(dispatch_id)["state"],
            "accepted",
        )

    def test_late_attempt_one_failure_and_settle_cannot_fence_attempt_two(
        self,
    ) -> None:
        work_item = self._create_work_item(
            "runtime-attempt-fence",
            objective="迟到事件不得回退已接受的重试尝试",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "验证 Room 运行尝试围栏",
                "clientMessageId": "client:runtime-attempt-fence",
                "participantIds": [str(self.participant["id"])],
                "workItemId": work_item["id"],
            },
        )
        dispatch_id = str(accepted["dispatches"][0]["dispatchId"])
        self._open_legacy_execution_fixture(accepted)
        self.service.room_kernel_worker.run_once()
        attempt_one_turn = f"turn:{dispatch_id}:1"
        self.service.events.publish(
            self.session_id,
            "turn_failed",
            {
                "failureKind": "transient_provider_failure",
                "reasonCode": "provider_transport_failure",
                "retryable": True,
                "hadToolActivity": False,
            },
            turn_id=attempt_one_turn,
            created_at_ms=30,
        )
        self.assertTrue(self.service.events.flush())
        first_retry = self.service.room_kernel.outbox(dispatch_id)
        self.service.room_kernel_worker.clock_ms = (
            lambda: int(first_retry["availableAtMs"])
        )
        self.service.room_kernel_worker.run_once()

        attempt_two_turn = f"turn:{dispatch_id}:2"
        binding = self.service.room_kernel.session_binding(
            self.session_id
        )
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding["runtimeTurnId"], attempt_two_turn)
        self.assertEqual(binding["attempt"], 1)
        root_id = str(binding["rootId"])
        dispatch_before = self.service.room_kernel.dispatch(dispatch_id)
        root_before = self.service.room_kernel.root(root_id)
        lease_before = self.service.room_kernel.lease(dispatch_id)
        limits_before = self.service.room_kernel.resource_limits(root_id)

        self.service.events.publish(
            self.session_id,
            "turn_failed",
            {
                "failureKind": "transient_provider_failure",
                "reasonCode": "provider_transport_failure",
                "retryable": True,
                "hadToolActivity": False,
            },
            turn_id=attempt_one_turn,
            created_at_ms=31,
        )
        self.assertTrue(self.service.events.flush())
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "active runtime turn",
        ):
            self.service.settle_room_runtime(
                {
                    "schemaVersion": (
                        "wisdom-weasel.room-runtime-settle-request.v1"
                    ),
                    "sessionId": self.session_id,
                    "dispatchId": dispatch_id,
                    "rootId": root_id,
                    "generation": int(dispatch_before["generation"]),
                    "capabilityEpoch": int(
                        dispatch_before["capabilityEpoch"]
                    ),
                    "runtimeTurnId": attempt_one_turn,
                    "dispatchAttempt": 0,
                    "settleScopeId": "scope:attempt-one:late",
                    "settleAttempt": 1,
                    "resourceUsage": {},
                }
            )

        self.assertEqual(
            self.service.room_kernel.dispatch(dispatch_id),
            dispatch_before,
        )
        self.assertEqual(
            self.service.room_kernel.root(root_id),
            root_before,
        )
        self.assertEqual(
            self.service.room_kernel.lease(dispatch_id),
            lease_before,
        )
        self.assertEqual(
            self.service.room_kernel.resource_limits(root_id)["retry_used"],
            limits_before["retry_used"],
        )
        self.assertEqual(
            self.factory.runtime.dispatch_attempts,
            [0, 1],
        )

        self.service.events.publish(
            self.session_id,
            "turn_failed",
            {
                "failureKind": "transient_provider_failure",
                "reasonCode": "provider_transport_failure",
                "retryable": True,
                "hadToolActivity": False,
            },
            turn_id=attempt_two_turn,
            created_at_ms=32,
        )
        self.assertTrue(self.service.events.flush())
        matching_failure = self.service.room_kernel.dispatch(dispatch_id)
        self.assertEqual(matching_failure["state"], "retry_wait")
        self.assertEqual(matching_failure["attempt"], 2)
        self.assertEqual(
            self.service.room_kernel.resource_limits(root_id)["retry_used"],
            2,
        )
        self.assertEqual(
            self.factory.runtime.dispatch_attempts,
            [0, 1],
        )

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

    def test_compaction_recovers_only_unfinished_room_continuity(self) -> None:
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

        self._open_legacy_execution_fixture(accepted)
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
        self.assertNotIn("<execution-mode", static_prompt)
        self.assertEqual(static_prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(static_prompt.count("memory_capture"), 1)
        self.assertNotIn(str(self.root.resolve()), static_prompt)
        self.assertNotIn(str(self.root.resolve()), room_context)
        for expected in (original, objective, criterion, blocker):
            self.assertIn(expected, room_context)
        self.assertNotIn('"continuation"', room_context)
        initial_runtime_context = self.service._runtime_session_context(
            self.service.sessions.get(self.session_id)
        )
        self.assertEqual(
            str(initial_runtime_context["sessionContext"]).count(
                '<execution-mode mode="workspace_managed">'
            ),
            1,
        )
        resource_limits = initial_runtime_context["roomResourceLimits"]
        self.assertNotIn("maxInputTokens", resource_limits)
        self.assertNotIn("maxToolCalls", resource_limits)
        self.assertEqual(resource_limits["maxOutputTokens"], 16_000)
        initial_recovery = initial_runtime_context["roomRecoveryContext"]
        for expected in (criterion, blocker):
            self.assertEqual(initial_recovery.count(expected), 1)
        self.assertNotIn(original, initial_recovery)
        self.assertNotIn(objective, initial_recovery)
        initial_packet = json.loads(initial_recovery)
        self.assertEqual(
            initial_packet["authoritativeProjectionRef"]["rootId"],
            str(accepted["rootId"]),
        )
        self.assertEqual(
            initial_packet["authoritativeProjectionRef"]["taskId"],
            str(dispatch["taskId"]),
        )
        self.assertEqual(
            initial_packet["nextAction"]["acceptanceAlias"],
            "AC-1",
        )

        skill_receipt = self.service.room_skill_receipts.latest_for_session(
            self.session_id
        )
        self.assertIsNotNone(skill_receipt)
        assert skill_receipt is not None
        catalog_revision = str(skill_receipt["catalogRevision"])
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
        for expected in (criterion, blocker):
            self.assertEqual(recovery_context.count(expected), 1)
        self.assertNotIn(original, recovery_context)
        self.assertNotIn(objective, recovery_context)
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
            now_ms=int(time.time() * 1000) + 1,
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
        for expected in (criterion, blocker):
            self.assertEqual(sealed_context.count(expected), 1)
        self.assertNotIn(original, sealed_context)
        self.assertNotIn(objective, sealed_context)
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
        for expected in (criterion, blocker):
            self.assertEqual(
                ordinary_session_context.count(expected),
                1,
            )
        self.assertNotIn(original, ordinary_session_context)
        self.assertNotIn(objective, ordinary_session_context)
        self.assertIn(
            "当前 Kernel 投影是任务状态的唯一权威",
            ordinary_session_context,
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
            "publicSummary": content,
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
            "kind": "summary",
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
                    "facilitatorParticipantId": str(self.participant["id"]),
                    "reporterParticipantId": None,
                    "reporterSelectionReceiptId": None,
                    "requirementAnchorRef": "requirement-anchor:product@sha256:test",
                    "createdByActorRef": "user:local",
                    "terminalReceiptId": None,
                    "activeProfileRef": None,
                    "budgetPolicyRef": "room-budget:test-v1",
                    "independentReviewRequired": False,
                    "createdAtMs": int(time.time() * 1000),
                },
                "task": {
                    "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                    "taskId": task_id,
                    "rootId": root_id,
                    "parentTaskId": None,
                    "taskKind": "work",
                    "currentOwnerParticipantId": str(self.participant["id"]),
                    "ownershipRevision": 0,
                    "ownershipReceiptId": None,
                    "invitationId": None,
                    "reviewState": "not_required",
                    "reviewOfTaskIds": [],
                    "reviewAuthorParticipantIds": [],
                    "contextEvidenceRefs": [],
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
    def test_authorized_cancel_then_finalize_preserves_review_fence(self) -> None:
        with sqlite3.connect(self.service.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id='task:service'"
            ).fetchone()
            payload = json.loads(str(row[0]))
            payload.update(
                {
                    "taskKind": "review",
                    "reviewState": "required",
                    "reviewFindings": [],
                }
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=?,updated_at_ms=? WHERE task_id='task:service'",
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    21,
                ),
            )
        cancelled = self.service.apply_room_kernel_command(
            self.room_id,
            {
                "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
                "commandId": "command:cancel-review-target",
                "rootId": "root:service",
                "roomId": self.room_id,
                "commandKind": "cancel_target",
                "targetKind": "task",
                "targetId": "task:service",
                "sourceKind": "control_center",
                "sourceId": "control-center:test",
                "idempotencyKey": "cancel:review-target",
                "generation": 0,
                "payload": {},
                "createdAtMs": 22,
            },
            caller_authorized=True,
        )
        self.assertEqual(cancelled["receiptKind"], "target_cancelled")
        final = self.service.finalize_room_kernel_route(
            self.room_id,
            {"rootId": "root:service"},
            caller_authorized=True,
        )
        self.assertEqual(final["receipt"]["status"], "rejected")
        self.assertEqual(final["receipt"]["details"]["reason"], "review_cancelled")
        self.assertNotEqual(
            self.service.room_kernel.root("root:service")["state"],
            "completed",
        )


    def test_runtime_failure_and_user_correction_are_automatic_incidents(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)

        def fail_dispatch(*_args, **kwargs):
            kwargs["record_intent"]()
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
        binding = self.service.room_kernel.session_binding(
            self.session_id
        )
        self.assertIsNotNone(binding)
        runtime_turn_id = str(binding["runtimeTurnId"])
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
                    "turnId": runtime_turn_id,
                    "role": "assistant",
                    "status": "completed",
                    "blocks": blocks,
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 5,
                }
            },
            turn_id=runtime_turn_id,
        )
        self.assertEqual(
            self.service.agent_blocks.blocks_for_message(self.session_id, "message:late"),
            [],
        )

    def test_stop_cancels_once_fences_late_event_and_allows_fresh_alignment(
        self,
    ) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        binding = self.service.room_kernel.session_binding(self.session_id)
        self.assertIsNotNone(binding)
        runtime_turn_id = str(binding["runtimeTurnId"])

        cancelled = self.service.abort_room_turn(
            self.room_id,
            {
                "roomTurnId": "root:service",
                "clientRequestId": "cancel:stop-once",
            },
        )
        self.assertEqual(cancelled["status"], "terminated")
        self.assertEqual(len(self.factory.runtime.cancelled), 1)

        late_blocks = list(
            normalize_trusted_agent_blocks(
                [
                    {
                        "id": "status:late-stop",
                        "type": "status",
                        "data": {"title": "过期停止结果"},
                    }
                ],
                source_kind="pi_runtime_event",
                source_ref=f"{self.session_id}:message:late-stop",
            )
        )
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "message:late-stop",
                    "sessionId": self.session_id,
                    "turnId": runtime_turn_id,
                    "role": "assistant",
                    "status": "completed",
                    "blocks": late_blocks,
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 5,
                }
            },
            turn_id=runtime_turn_id,
        )
        self.assertTrue(self.service.events.flush())
        self.assertEqual(
            self.service.agent_blocks.blocks_for_message(
                self.session_id,
                "message:late-stop",
            ),
            [],
        )

        repeated = self.service.abort_room_turn(
            self.room_id,
            {
                "roomTurnId": "root:service",
                "clientRequestId": "cancel:stop-again",
            },
        )
        self.assertEqual(repeated["status"], "terminated")
        self.assertEqual(len(self.factory.runtime.cancelled), 1)

        resent = self.service.post_room_message(
            self.room_id,
            {
                "message": "停止后重新发送，必须创建全新的需求对齐。",
                "clientMessageId": "client:after-stop",
                "participantIds": [str(self.participant["id"])],
            },
        )
        self.assertEqual(resent["dispatches"], [])
        self.assertEqual(len(resent["alignmentDispatches"]), 1)
        self.assertNotEqual(resent["rootId"], "root:service")
        self.assertEqual(
            resent["alignmentDispatches"][0]["participantId"],
            resent["participant"]["id"],
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
                "kind": "work_result",
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
                    },
                    "runtimeTurnId": "turn:dispatch:no-commit:1",
                    "dispatchAttempt": 0,
                },
                caller_authorized=True,
            )
            for attempt in range(1, 6)
        ]

        self.assertTrue(all(result["retryRequired"] for result in results[:4]))
        self.assertTrue(results[4]["blocked"])
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
        self.service.room_kernel_worker.run_once()
        before = len(self.service.rooms.list_events(self.room_id, limit=200))
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "private reasoning"}]}},
            turn_id="turn:dispatch:service:1",
        )
        self.assertTrue(self.service.events.flush())
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
            turn_id="turn:dispatch:service:1",
        )
        self.assertTrue(self.service.events.flush())
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
            turn_id="turn:dispatch:service:1",
        )
        self.assertTrue(self.service.events.flush())
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

    def test_projection_sync_skips_kernel_roots_for_deleted_rooms(self) -> None:
        stale_room_id = "room:deleted"
        self.service.room_kernel.create_root_with_task(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:deleted",
                "roomId": stale_room_id,
                "generation": 0,
                "state": "completed",
                "facilitatorParticipantId": str(self.participant["id"]),
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement-anchor:deleted@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": "terminal:deleted",
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "independentReviewRequired": False,
                "createdAtMs": 1,
            },
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:deleted",
                "rootId": "root:deleted",
                "parentTaskId": None,
                "taskKind": "work",
                "currentOwnerParticipantId": str(self.participant["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Preserve a deleted Room projection fixture.",
                "expectedOutput": "No projection event.",
                "requirementItemIds": ["requirement:deleted"],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "completed",
            },
            budget=1,
            max_hops=1,
            max_depth=1,
            acceptance_criteria=(),
            now_ms=1,
        )

        self.service._sync_all_room_kernel_projections()

        self.assertEqual(
            self.service.room_kernel_projection.snapshot(stale_room_id)[
                "lastSequence"
            ],
            0,
        )

    def test_capability_manifest_exposes_only_one_canonical_kernel_path(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        tools = (
            "room_state",
            "room_post",
            "room_commit",
            "room_define",
            "room_collaborate",
            "room_integrate",
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
            "room_state/room_post/room_commit/room_define/room_collaborate/room_integrate",
        ):
            self.service.execute_room_capability_tool(
                self.session_id,
                "room_send",
                {"content": "deliver"},
                tool_call_id="call:legacy-service",
                load_receipt_id=str(loaded["receiptId"]),
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "must be rewritten for users",
        ):
            self.service.execute_room_capability_tool(
                self.session_id,
                "room_post",
                {
                    "kind": "progress",
                    "content": "检查完成，dispatchId 为 dispatch:service。",
                },
                tool_call_id="call:private-post",
                load_receipt_id=str(loaded["receiptId"]),
            )
        canonical = self.service.execute_room_capability_tool(
            self.session_id,
            "room_post",
            {"kind": "progress", "content": "正在核对受管工具路径，下一步继续检查会话边界。"},
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
            ["正在核对受管工具路径，下一步继续检查会话边界。"],
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
                root_id="root:service",
                task_id="task:service",
                dispatch_id="dispatch:service",
                generation=0,
                capability_epoch=7,
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
            "intent": "execute",
            "acceptance": ["AC-1"],
            "workspacePolicy": "isolated_writable",
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
            with self.assertRaisesRegex(
                RoomKernelFenceError,
                "already has active matching Room work",
            ):
                self.service.execute_room_capability_tool(
                    self.session_id,
                    "room_collaborate",
                    {
                        **arguments,
                        "objective": "再次检查同一边界并回报结论",
                        "expectedOutput": "再次给出同一边界的复核结论",
                    },
                    tool_call_id="call:room-collaborate-active-duplicate",
                    load_receipt_id=str(loaded["receiptId"]),
                )


        result = first["result"]
        self.assertTrue(result["accepted"])
        self.assertTrue(result["enqueued"])
        self.assertFalse(result["deduplicated"])
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
            child_task["currentOwnerParticipantId"],
            target["id"],
        )
        self.assertEqual(child_task["ownershipRevision"], 0)
        self.assertEqual(child_dispatch["taskId"], child_task["taskId"])
        self.assertEqual(child_dispatch["parentDispatchId"], "dispatch:service")
        self.assertEqual(child_dispatch["hopCount"], 1)
        self.assertEqual(child_dispatch["depth"], 1)
        self.assertEqual(child_dispatch["intentKind"], "execute")
        self.assertEqual(
            child_dispatch["capabilityEpoch"],
            parent["capabilityEpoch"],
        )
        self.assertEqual(child_dispatch["state"], "pending")
        self.assertEqual(
            self.service.room_kernel.counts("root:service")["dispatches"],
            2,
        )
        receipt_children = (
            self.service.room_kernel.collaboration_children(
                "root:service"
            )
        )
        self.assertEqual(
            [item["dispatchId"] for item in receipt_children],
            [child_dispatch["dispatchId"]],
        )
        self.assertFalse(receipt_children[0]["resultPublic"])
        self.assertTrue(
            receipt_children[0]["collaborationReceiptId"]
        )
        self.assertEqual(result["targetParticipantRef"], target_ref)
        self.assertEqual(result["childTaskId"], child_task["taskId"])
        self.assertEqual(result["childDispatchId"], child_dispatch["dispatchId"])
        self.assertEqual(result["workspacePolicy"], "isolated_writable")
        started_task = self.service.room_kernel.task(
            str(child_task["taskId"])
        )
        self.assertTrue(started_task["workspaceBindingId"])
        self.assertEqual(
            started_task["workspaceLifecycleState"],
            "work_started",
        )
        self.assertFalse(started_task["workspaceAttentionRequired"])
        started_binding = self.service.room_workspaces.ledger.binding(
            str(started_task["workspaceBindingId"])
        )
        self.assertEqual(
            started_binding["workspaceLifecycleState"],
            "work_started",
        )
        self.assertEqual(
            started_binding["dispatchId"],
            child_dispatch["dispatchId"],
        )

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
        cancelled_task = self.service.room_kernel.task(
            str(child_task["taskId"])
        )
        self.assertEqual(
            cancelled_task["workspaceLifecycleState"],
            "cancelled",
        )
        self.assertEqual(
            cancelled_task["workspaceCleanupState"],
            "retained",
        )
        self.assertTrue(cancelled_task["workspaceAttentionRequired"])
        self.assertTrue(Path(str(cancelled_task["workspaceRoot"])).is_dir())
        cancelled_binding = self.service.room_workspaces.ledger.binding(
            str(cancelled_task["workspaceBindingId"])
        )
        self.assertEqual(
            cancelled_binding["workspaceLifecycleState"],
            "cancelled",
        )
        self.assertTrue(cancelled_binding["attentionRequired"])

    def test_retained_isolated_workspace_retries_then_abandons_with_receipts(
        self,
    ) -> None:
        self._set_parent_acceptance("criterion:service")
        original = "保留隔离实现现场，并允许有回执地重试或放弃。"
        anchor, _ = self.service.room_requirements.append_anchor(
            anchor_id="requirement-anchor:service@sha256:test",
            root_id="root:service",
            original_content=original,
            created_by="user:local",
            provenance={"source": "test-user-request"},
            created_at_ms=2,
        )
        self.service.room_requirements.revise_catalog(
            catalog_revision_id="catalog:retained-workspace",
            root_id="root:service",
            expected_current_revision=0,
            anchor_refs=[anchor["anchorId"]],
            items=[
                {
                    "itemId": "requirement:service",
                    "kind": "explicit_user_requirement",
                    "statement": original,
                    "origin": "user",
                    "state": "active",
                    "sourceSpans": [
                        {
                            "anchorId": anchor["anchorId"],
                            "startByte": 0,
                            "endByte": len(original.encode("utf-8")),
                        }
                    ],
                }
            ],
            acceptance_criteria=[
                {
                    "criterionId": "criterion:service",
                    "itemId": "requirement:service",
                    "acceptanceCriterionFullNameZh": "隔离现场可恢复处理",
                    "criterionKind": "requirement",
                    "expectedReceiptTypes": ["test"],
                    "statement": "阻塞后可重试或有回执地放弃",
                }
            ],
            change_reason="冻结隔离工作区恢复验收",
            provenance={"source": "test"},
            created_by="user:local",
            created_at_ms=2,
        )
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        room = self.service.rooms.get(self.room_id)
        target = next(
            item
            for item in room["participants"]
            if item["status"] == "active"
            and item["id"] != self.participant["id"]
        )
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:retained-workspace-state",
                "toolName": "room_state",
                "createdAtMs": 4,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            self.session_id,
            "room_state",
            {},
            tool_call_id="call:retained-workspace-state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if item["displayName"] == target["displayName"]
        )
        collaborate_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:retained-workspace-collaborate",
                "toolName": "room_collaborate",
                "createdAtMs": 5,
            }
        )["result"]
        with patch(
            "rag_ime.agent_room_kernel_application.time.time",
            return_value=0.006,
        ):
            collaboration = self.service.execute_room_capability_tool(
                self.session_id,
                "room_collaborate",
                {
                    "targetParticipantRef": target_ref,
                    "objective": "在隔离工作区完成可恢复实现",
                    "expectedOutput": "带验证证据的独立实现",
                    "intent": "execute",
                    "acceptance": ["AC-1"],
                    "workspacePolicy": "isolated_writable",
                },
                tool_call_id="call:retained-workspace-collaborate",
                load_receipt_id=str(collaborate_load["receiptId"]),
            )["result"]
        child_task_id = str(collaboration["childTaskId"])
        child_dispatch_id = str(collaboration["childDispatchId"])
        child_dispatch = self.service.room_kernel.dispatch(
            child_dispatch_id
        )
        child_task = self.service.room_kernel.task(child_task_id)
        workspace_path = Path(str(child_task["workspaceRoot"]))
        self.assertTrue(workspace_path.is_dir())

        self.service.room_kernel_worker.run_once()
        child_binding = self.service.room_kernel.session_binding(
            str(target["sessionId"])
        )
        self.assertIsNotNone(child_binding)
        assert child_binding is not None
        self.service.room_kernel_application.record_runtime_failure(
            room_id=self.room_id,
            dispatch_id=child_dispatch_id,
            generation=0,
            source_event_id="event:retained-workspace-first-failure",
            runtime_turn_id=str(child_binding["runtimeTurnId"]),
            dispatch_attempt=int(child_binding["attempt"]),
            created_at_ms=6,
            retryable=False,
            had_tool_activity=True,
            reason_code="initial_validation_failed",
        )
        initially_failed = self.service.room_kernel.task(child_task_id)
        self.assertEqual(
            initially_failed["workspaceLifecycleState"],
            "failed",
        )
        self.assertTrue(initially_failed["workspaceAttentionRequired"])
        self.service.room_kernel_application._retain_isolated_task(
            initially_failed,
            state="blocked",
            reason="blocked Task retained for Facilitator recovery",
            actor_ref="system:test-blocked-settlement",
            now_ms=6,
        )
        blocked_task = self.service.room_kernel.task(child_task_id)
        self.assertEqual(blocked_task["workspaceLifecycleState"], "blocked")
        self.assertEqual(blocked_task["workspaceCleanupState"], "retained")
        self.assertTrue(blocked_task["workspaceAttentionRequired"])
        self.assertTrue(workspace_path.is_dir())

        retry_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:retained-workspace-retry",
                "toolName": "room_integrate",
                "createdAtMs": 7,
            }
        )["result"]
        retry_args = {
            "childTaskId": child_task_id,
            "action": "retry",
            "reason": "Facilitator inspected the retained evidence and retried",
            "targetParticipantRef": target_ref,
        }
        forged_mapping = {
            "workspaceBindingId": str(blocked_task["workspaceBindingId"]),
            "workspaceLifecycleState": "retry_bound",
            "attentionRequired": False,
            "retryEpoch": 999,
            "retryLeaseToken": "forged-retry-token",
            "retryLeaseTokenSha256": hashlib.sha256(
                b"forged-retry-token"
            ).hexdigest(),
            "retryBoundReceiptId": "room-workspace-event:forged",
            "retryBoundReceiptSha256": "f" * 64,
            "targetParticipantRef": target_ref,
        }
        with patch.object(
            self.service.room_workspaces,
            "retry_retained",
            return_value=forged_mapping,
        ):
            with self.assertRaisesRegex(
                RoomKernelFenceError,
                "exact durable retry lease",
            ):
                self.service.execute_room_capability_tool(
                    self.session_id,
                    "room_integrate",
                    retry_args,
                    tool_call_id="call:retained-workspace-retry-forged",
                    load_receipt_id=str(retry_load["receiptId"]),
                )
        self.assertTrue(
            self.service.room_kernel.task(child_task_id)[
                "workspaceAttentionRequired"
            ]
        )
        with patch(
            "rag_ime.agent_room_kernel_application.time.time",
            return_value=0.007,
        ):
            with patch.object(
                self.service.room_capabilities,
                "record_runtime_execution",
                side_effect=RuntimeError("injected retry execution receipt crash"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "injected retry execution receipt crash",
                ):
                    self.service.execute_room_capability_tool(
                        self.session_id,
                        "room_integrate",
                        retry_args,
                        tool_call_id="call:retained-workspace-retry",
                        load_receipt_id=str(retry_load["receiptId"]),
                    )
            revision_after_kernel_commit = int(
                self.service.room_kernel.task(child_task_id)["revision"]
            )
            self.assertTrue(self.service.room_kernel_worker.run_once())
            retry_dispatch = self.service.room_kernel.dispatch(
                self.factory.runtime.dispatched[-1]
            )
            self.assertEqual(retry_dispatch["taskId"], child_task_id)
            self.assertEqual(retry_dispatch["intentKind"], "retry")
            self.assertEqual(retry_dispatch["state"], "running")

            retry_runtime = self.service.room_kernel.session_binding(
                str(target["sessionId"])
            )
            self.assertIsNotNone(retry_runtime)
            assert retry_runtime is not None
            self.service.room_kernel_application.record_runtime_failure(
                room_id=self.room_id,
                dispatch_id=str(retry_dispatch["dispatchId"]),
                generation=0,
                source_event_id="event:retained-workspace-retry-failed",
                runtime_turn_id=str(retry_runtime["runtimeTurnId"]),
                dispatch_attempt=int(retry_runtime["attempt"]),
                created_at_ms=8,
                retryable=False,
                had_tool_activity=True,
                reason_code="retry_validation_failed",
            )
            failed_task = self.service.room_kernel.task(child_task_id)
            revision_after_progress = int(failed_task["revision"])
            self.assertGreater(
                revision_after_progress,
                revision_after_kernel_commit,
            )
            self.assertEqual(failed_task["workspaceLifecycleState"], "failed")
            self.assertTrue(failed_task["workspaceAttentionRequired"])
            retry = self.service.execute_room_capability_tool(
                self.session_id,
                "room_integrate",
                retry_args,
                tool_call_id="call:retained-workspace-retry",
                load_receipt_id=str(retry_load["receiptId"]),
            )
            retry_replay = self.service.execute_room_capability_tool(
                self.session_id,
                "room_integrate",
                retry_args,
                tool_call_id="call:retained-workspace-retry",
                load_receipt_id=str(retry_load["receiptId"]),
            )
        self.assertEqual(retry["result"], retry_replay["result"])
        self.assertEqual(
            retry["result"]["workspaceLifecycleState"],
            "retry_bound",
            "runtime receipt repair must replay the canonical Kernel outcome",
        )
        self.assertEqual(
            self.service.room_kernel.task(child_task_id)["revision"],
            revision_after_progress,
        )
        retried_binding = self.service.room_workspaces.ledger.binding(
            str(failed_task["workspaceBindingId"])
        )
        self.assertEqual(
            retried_binding["workspaceLifecycleState"], "failed"
        )
        self.assertTrue(retried_binding["attentionRequired"])
        self.assertEqual(
            retried_binding["currentOwnerSessionId"],
            target["sessionId"],
        )
        retry_bound_event = next(
            event
            for event in reversed(
                self.service.room_workspaces.ledger.events(
                    str(failed_task["workspaceBindingId"])
                )
            )
            if event["eventKind"] == "retry_bound"
        )
        self.assertEqual(
            retry_bound_event["payload"]["participantRef"],
            target_ref,
        )
        self.assertTrue(workspace_path.is_dir())

        abandon_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:retained-workspace-abandon",
                "toolName": "room_integrate",
                "createdAtMs": 9,
            }
        )["result"]
        abandon_args = {
            "childTaskId": child_task_id,
            "action": "abandon",
            "reason": "Facilitator accepted a scoped abandonment after inspection",
            "acceptance": ["AC-1"],
        }
        original_remove_worktree = (
            self.service.room_workspaces._remove_worktree
        )
        self.service.room_workspaces._remove_worktree = (  # type: ignore[method-assign]
            lambda base, source: subprocess.CompletedProcess(
                args=[str(base), str(source)],
                returncode=1,
                stdout=b"",
                stderr=b"injected abandonment cleanup failure",
            )
        )
        try:
            abandon = self.service.execute_room_capability_tool(
                self.session_id,
                "room_integrate",
                abandon_args,
                tool_call_id="call:retained-workspace-abandon",
                load_receipt_id=str(abandon_load["receiptId"]),
            )
        finally:
            self.service.room_workspaces._remove_worktree = (  # type: ignore[method-assign]
                original_remove_worktree
            )
        events_before_replay = self.service.room_workspaces.ledger.events(
            str(failed_task["workspaceBindingId"])
        )
        abandon_replay = self.service.execute_room_capability_tool(
            self.session_id,
            "room_integrate",
            abandon_args,
            tool_call_id="call:retained-workspace-abandon",
            load_receipt_id=str(abandon_load["receiptId"]),
        )
        self.assertEqual(abandon["result"], abandon_replay["result"])
        self.assertEqual(
            self.service.room_workspaces.ledger.events(
                str(failed_task["workspaceBindingId"])
            ),
            events_before_replay,
        )
        abandoned_task = self.service.room_kernel.task(child_task_id)
        self.assertEqual(
            abandoned_task["workspaceLifecycleState"],
            "cleanup_failed",
        )
        self.assertEqual(
            abandoned_task["workspaceCleanupState"],
            "failed",
        )
        self.assertTrue(abandoned_task["workspaceAttentionRequired"])
        cleanup_receipt = self.service.room_workspaces.ledger.cleanup_receipt(
            str(abandoned_task["workspaceBindingId"])
        )
        self.assertIsNotNone(cleanup_receipt)
        assert cleanup_receipt is not None
        retained_workspace = Path(
            str(cleanup_receipt["payload"]["retainedWorkspaceRoot"])
        )
        self.assertFalse(workspace_path.exists())
        self.assertTrue(retained_workspace.exists())
        abandoned_binding = self.service.room_workspaces.ledger.binding(
            str(abandoned_task["workspaceBindingId"])
        )
        self.assertEqual(
            abandoned_binding["workspaceLifecycleState"],
            "cleanup_failed",
        )
        self.assertTrue(abandoned_binding["attentionRequired"])
        self.assertTrue(abandon["result"]["abandonmentAuthorized"])
        self.assertFalse(abandon["result"]["physicalCleanupCompleted"])
        self.assertTrue(abandon["result"]["attentionRequired"])
        self.assertEqual(abandon["result"]["cleanupState"], "failed")
        abandonment_event = next(
            item
            for item in events_before_replay
            if item["eventKind"] == "abandoned"
        )
        self.assertRegex(
            str(abandonment_event["payload"]["workspaceSnapshotSha256"]),
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(
            str(abandonment_event["payloadSha256"]),
            r"^[0-9a-f]{64}$",
        )
        public_result = json.dumps(abandon["result"], ensure_ascii=False)
        self.assertNotIn(str(workspace_path), public_result)
        self.assertNotRegex(public_result, r"\b[0-9a-f]{64}\b")

    def _exercise_pending_integration_recovery(
        self,
        *,
        recovery_tool_call_id: str,
    ) -> tuple[str, str]:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": (
                    f"load:pending-integration:{recovery_tool_call_id}"
                ),
                "toolName": "room_integrate",
                "createdAtMs": 4,
            }
        )["result"]
        task = {
            **self.service.room_kernel.task("task:service"),
            "state": "completed",
            "workspacePolicy": "isolated_writable",
            "workspaceBindingId": "workspace-binding:application-recovery",
            "workspaceIntegrationState": "pending",
            "workspaceIntegrationRef": None,
            "workspaceLifecycleState": "delivered",
            "workspaceCleanupState": "not_authorized",
            "workspaceAttentionRequired": False,
        }
        calls: list[str] = []

        def integrate(
            _task: object,
            *,
            integration_ref: str,
            actor_ref: str,
            now_ms: int,
        ) -> dict[str, object]:
            del _task, actor_ref, now_ms
            calls.append(integration_ref)
            cleanup_failed = len(calls) == 1
            return {
                "integrated": True,
                "workspaceBindingId": task["workspaceBindingId"],
                "integrationRef": integration_ref,
                "integrationPatchSha256": "a" * 64,
                "integratedRevision": "git:application-recovery",
                "integratedSnapshotSha256": "b" * 64,
                "workspaceLifecycleState": (
                    "cleanup_failed" if cleanup_failed else "cleaned"
                ),
                "cleanupState": "failed" if cleanup_failed else "cleaned",
                "attentionRequired": cleanup_failed,
            }

        authority = patch.object(
            self.service.room_kernel,
            "workspace_integration_authority",
            create=True,
            return_value={"status": "ready", "integrationRef": None},
        )
        with (
            patch.object(self.service.room_kernel, "task", return_value=task),
            patch.object(
                self.service.room_workspaces,
                "integrate",
                side_effect=integrate,
            ),
            patch.object(
                self.service.room_kernel,
                "record_workspace_integration",
                return_value=task,
            ),
            authority as authority_mock,
        ):
            first = self.service.execute_room_capability_tool(
                self.session_id,
                "room_integrate",
                {"childTaskId": "task:service", "action": "integrate"},
                tool_call_id="call:pending-integration:first",
                load_receipt_id=str(loaded["receiptId"]),
            )
            self.assertNotIn(
                "executionReceipt",
                first,
                "cleanup_failed is pending authority, not terminal execution",
            )
            self.assertEqual(first["result"]["cleanupState"], "failed")
            authority_mock.return_value = {
                "status": "pending_cleanup",
                "integrationRef": calls[0],
            }
            recovered = self.service.execute_room_capability_tool(
                self.session_id,
                "room_integrate",
                {"childTaskId": "task:service", "action": "integrate"},
                tool_call_id=recovery_tool_call_id,
                load_receipt_id=str(loaded["receiptId"]),
            )
        self.assertEqual(recovered["result"]["cleanupState"], "cleaned")
        self.assertEqual(recovered["executionReceipt"]["status"], "applied")
        self.assertEqual(len(calls), 2)
        return calls[0], calls[1]

    def test_room_integrate_same_invocation_resumes_pending_cleanup(self) -> None:
        first_ref, recovered_ref = self._exercise_pending_integration_recovery(
            recovery_tool_call_id="call:pending-integration:first",
        )
        self.assertEqual(recovered_ref, first_ref)

    def test_room_integrate_fresh_invocation_preserves_pending_ref(self) -> None:
        first_ref, recovered_ref = self._exercise_pending_integration_recovery(
            recovery_tool_call_id="call:pending-integration:fresh",
        )
        self.assertEqual(recovered_ref, first_ref)

    def test_room_integrate_prior_replay_revalidates_canonical_authority(
        self,
    ) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:integration-authority-replay",
                "toolName": "room_integrate",
                "createdAtMs": 4,
            }
        )["result"]
        integration_ref = "room-workspace-integration:canonical"
        task = {
            **self.service.room_kernel.task("task:service"),
            "state": "completed",
            "workspacePolicy": "isolated_writable",
            "workspaceBindingId": "workspace-binding:authority-replay",
            "workspaceIntegrationState": "applied",
            "workspaceIntegrationRef": integration_ref,
            "workspaceLifecycleState": "cleaned",
            "workspaceCleanupState": "cleaned",
            "workspaceAttentionRequired": False,
        }
        authority = patch.object(
            self.service.room_kernel,
            "workspace_integration_authority",
            create=True,
            return_value={
                "status": "accepted",
                "integrationRef": integration_ref,
            },
        )
        with (
            patch.object(self.service.room_kernel, "task", return_value=task),
            patch.object(
                self.service.room_workspaces,
                "integrate",
                return_value={
                    "integrated": True,
                    "workspaceBindingId": task["workspaceBindingId"],
                    "integrationRef": integration_ref,
                    "integrationPatchSha256": "a" * 64,
                    "integratedRevision": "git:authority-replay",
                    "integratedSnapshotSha256": "b" * 64,
                    "workspaceLifecycleState": "cleaned",
                    "cleanupState": "cleaned",
                    "attentionRequired": False,
                },
            ),
            patch.object(
                self.service.room_kernel,
                "record_workspace_integration",
                return_value=task,
            ),
            authority as authority_mock,
        ):
            first = self.service.execute_room_capability_tool(
                self.session_id,
                "room_integrate",
                {"childTaskId": "task:service", "action": "integrate"},
                tool_call_id="call:integration-authority-replay",
                load_receipt_id=str(loaded["receiptId"]),
            )
            self.assertEqual(first["executionReceipt"]["status"], "applied")
            authority_mock.return_value = {
                "status": "invalid",
                "integrationRef": integration_ref,
            }
            with self.assertRaisesRegex(
                RoomKernelFenceError,
                "canonical integration authority",
            ):
                self.service.execute_room_capability_tool(
                    self.session_id,
                    "room_integrate",
                    {"childTaskId": "task:service", "action": "integrate"},
                    tool_call_id="call:integration-authority-replay",
                    load_receipt_id=str(loaded["receiptId"]),
                )

    def test_non_facilitator_room_collaboration_is_side_effect_free(self) -> None:
        self._set_parent_acceptance("criterion:service")
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        room = self.service.rooms.get(self.room_id)
        target = next(
            item
            for item in room["participants"]
            if item["status"] == "active"
            and str(item["id"]) != str(self.participant["id"])
        )
        target_task_id = "task:non-facilitator-collaboration"
        self.service.room_kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": target_task_id,
                "rootId": "root:service",
                "parentTaskId": "task:service",
                "taskKind": "work",
                "currentOwnerParticipantId": str(target["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Run a bounded worker continuation.",
                "expectedOutput": "A bounded worker result.",
                "requirementItemIds": ["requirement:service"],
                "acceptanceCriterionIds": ["criterion:service"],
                "revision": 0,
                "state": "active",
            },
            now_ms=4,
        )
        target_dispatch_id = "dispatch:non-facilitator-collaboration"
        self.service.room_kernel.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": target_dispatch_id,
                "rootId": "root:service",
                "taskId": target_task_id,
                "parentDispatchId": "dispatch:service",
                "generation": 0,
                "hopCount": 1,
                "depth": 1,
                "budgetCost": 1,
                "targetSessionId": str(target["sessionId"]),
                "targetParticipantId": str(target["id"]),
                "triggerId": "trigger:non-facilitator-collaboration",
                "intentKind": "execute",
                "idempotencyKey": target_dispatch_id,
                "attempt": 0,
                "capabilityEpoch": 7,
                "runtimeProfileRevision": "runtime-profile:service-v1",
                "state": "pending",
            },
            now_ms=5,
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": str(target["sessionId"]),
                "receiptId": "load:non-facilitator-state",
                "toolName": "room_state",
                "createdAtMs": 6,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            str(target["sessionId"]),
            "room_state",
            {},
            tool_call_id="call:non-facilitator-state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        target_ref = next(
            str(item["participantRef"])
            for item in state["participants"]
            if str(item["displayName"]) == str(target["displayName"])
        )
        collaboration_load = self.service.room_capability_tool_load(
            {
                "sessionId": str(target["sessionId"]),
                "receiptId": "load:non-facilitator-collaboration",
                "toolName": "room_collaborate",
                "createdAtMs": 6,
            }
        )["result"]
        children_before = self.service.room_kernel.collaboration_children(
            "root:service"
        )
        dispatched_before = list(self.factory.runtime.dispatched)
        with patch.object(
            self.service.room_workspaces,
            "prepare",
            side_effect=AssertionError(
                "unauthorized collaboration prepared a workspace"
            ),
        ):
            with self.assertRaisesRegex(
                RoomKernelFenceError,
                "Root Facilitator or Reporter",
            ):
                self.service.execute_room_capability_tool(
                    str(target["sessionId"]),
                    "room_collaborate",
                    {
                        "targetParticipantRef": target_ref,
                        "objective": "Fan out from a worker",
                        "expectedOutput": "A child result",
                        "intent": "execute",
                        "acceptance": ["AC-1"],
                        "workspacePolicy": "read_only",
                    },
                    tool_call_id="call:non-facilitator-collaboration",
                    load_receipt_id=str(collaboration_load["receiptId"]),
                )
        self.assertEqual(
            self.service.room_kernel.collaboration_children("root:service"),
            children_before,
        )
        self.assertEqual(self.factory.runtime.dispatched, dispatched_before)
        self.assertIsNone(
            self.service.room_capabilities.execution_receipt(
                "invoke:call:non-facilitator-collaboration"
            )
        )

    def test_room_collaborate_result_distinguishes_enqueue_from_duplicate(self) -> None:
        invocation = {
            "canonicalCommand": {
                "arguments": {
                    "targetParticipantRef": "participant:reviewer",
                },
            },
        }
        details = {
            "childTaskId": "task:child",
            "childDispatchId": "dispatch:child",
        }

        applied = _collaboration_tool_result(
            invocation,
            {
                "receiptKind": "accepted",
                "status": "applied",
                "details": details,
            },
        )
        duplicate = _collaboration_tool_result(
            invocation,
            {
                "receiptKind": "duplicate",
                "status": "noop",
                "details": details,
            },
        )

        self.assertEqual(
            applied,
            {
                "accepted": True,
                "enqueued": True,
                "deduplicated": False,
                "childTaskId": "task:child",
                "childDispatchId": "dispatch:child",
                "workspacePolicy": None,
                "targetParticipantRef": "participant:reviewer",
                "currentResponsibilityContinues": True,
            },
        )
        self.assertEqual(
            duplicate,
            {
                "accepted": True,
                "enqueued": False,
                "deduplicated": True,
                "childTaskId": "task:child",
                "childDispatchId": "dispatch:child",
                "workspacePolicy": None,
                "targetParticipantRef": "participant:reviewer",
                "currentResponsibilityContinues": True,
            },
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
            "intent": "execute",
            "acceptance": ["AC-1"],
            "workspacePolicy": "read_only",
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
        self.assertEqual(replay["result"]["childDispatchId"], child["dispatchId"])
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
                    "intent": "execute",
                    "acceptance": ["AC-1"],
                    "workspacePolicy": "read_only",
                },
                tool_call_id="call:parallel-collaboration",
                load_receipt_id=str(collaboration_load["receiptId"]),
            )["result"]
        self.assertTrue(collaboration["childDispatchId"])
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

        parent_skill = "implementation-execution"
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
                "publicSummary": f"waiting:{dispatch_id}",
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
            "continuation": {
                "decision": "wait",
                "waitingFor": "external",
                "resumeCondition": "test explicitly resumes the fixture",
            },
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
            names[:5],
            [
                "room_state",
                "room_post",
                "room_commit",
                "room_define",
                "room_collaborate",
            ],
        )
        for name in (
            "planning",
            "configuration",
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
        self.assertEqual(workflow["todo"]["revision"], 0)
        self.assertEqual(workflow["todo"]["counts"]["total"], 0)
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

    def test_room_workspace_job_runs_in_background_and_root_cancel_owns_it(self) -> None:
        self._use_per_action_execution()
        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            workspace_harness=self.service.background_jobs.workspace_harness,
            background_jobs=self.service.background_jobs,
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-workspace-job",
                "toolName": "workspace_job",
                "createdAtMs": 5,
            }
        )["result"]

        prepared = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_job",
                "toolCallId": "tool:room-workspace-job",
                "loadReceiptId": loaded["receiptId"],
                "args": {
                    "op": "start",
                    "command": (
                        "python3 -c \"import time; "
                        "print('room-job-ready', flush=True); time.sleep(30)\""
                    ),
                    "cwd": str(self.root),
                    "timeoutSeconds": 60,
                    "label": "Room managed background job",
                },
            }
        )
        approval = prepared["result"]["approval"]
        self.assertTrue(approval["causalMetadata"]["roomBound"])
        self.assertEqual(
            approval["causalMetadata"]["turnId"],
            "root:service",
        )
        decided = self.service.sessions.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        started = gateway.apply_approval(decided)
        job_id = str(started["job"]["jobId"])

        deadline = time.monotonic() + 5
        log_text = ""
        while time.monotonic() < deadline:
            log_text = str(
                self.service.background_jobs.logs(
                    self.session_id,
                    job_id,
                    cursor=0,
                )["text"]
            )
            if "room-job-ready" in log_text:
                break
            time.sleep(0.02)
        self.assertIn("room-job-ready", log_text)
        with self.assertRaisesRegex(
            AgentBackgroundJobError,
            "Room/Root owner",
        ):
            self.service.background_jobs.cancel(
                self.session_id,
                job_id,
            )

        self.service.events.publish(
            self.session_id,
            "turn_failed",
            {"error": "provider stopped after launching the background job"},
            turn_id="turn:dispatch:service:1",
            created_at_ms=6,
        )
        self.assertTrue(self.service.events.flush())
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:service")["state"],
            "failed",
        )
        self.assertEqual(
            self.service.room_kernel.active_runtime_targets("root:service"),
            [],
        )

        cancelled = self.service.abort_room_turn(
            self.room_id,
            {
                "roomTurnId": "root:service",
                "clientRequestId": "cancel:room-workspace-job",
            },
        )
        job = self.service.background_jobs.status(
            self.session_id,
            job_id,
        )["job"]

        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["causalMetadata"]["turnId"], "root:service")
        self.assertEqual(
            [item["job"]["jobId"] for item in cancelled["backgroundJobReceipts"]],
            [job_id],
        )
        self.assertEqual(cancelled["status"], "terminated")

    def test_workspace_managed_failure_keeps_the_original_error_and_one_receipt(
        self,
    ) -> None:
        session = self.service.sessions.get(self.session_id)
        self.service.sessions.set_runtime_policy(
            self.session_id,
            mode=str(session.get("mode") or "coordinator"),
            tool_profile_version=str(
                session.get("toolProfileVersion") or "control-center-v1"
            ),
            execution_mode="workspace_managed",
            grant_workspace_scope=True,
            allowed_tools=(
                list(session.get("allowedTools") or [])
                if session.get("toolAllowlistMode") == "explicit"
                else None
            ),
            workspace_roots=[str(self.root)],
        )

        attempted_commands: list[object] = []

        def reject_command(prepared):
            attempted_commands.append(prepared)
            raise RuntimeError("test executor rejected this command")

        gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=SimpleNamespace(),
            core=SimpleNamespace(),
            project="wisdom-weasel-rag-ime",
            workspace_harness=WorkspaceHarness(executor=reject_command),
            collaboration=self.service,
        )
        self.service.bind_tool_manifest_provider(gateway.runtime_manifests)
        self.service.bind_approval_executor(gateway.apply_approval)
        gateway.bind_auto_approval_executor(
            self.service.auto_approve_pending
        )
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-failed-shell",
                "toolName": "workspace_shell",
                "createdAtMs": 5,
            }
        )["result"]

        response = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_shell",
                "toolCallId": "tool:room-failed-shell",
                "loadReceiptId": loaded["receiptId"],
                "args": {
                    "op": "run",
                    "command": "printf ok",
                    "cwd": str(self.root),
                    "allowNetwork": False,
                },
            }
        )

        self.assertTrue(response["result"]["autoApproved"])
        self.assertEqual(
            response["result"]["approval"]["state"],
            "failed",
        )
        self.assertIn(
            "test executor rejected this command",
            response["result"]["receipt"]["error"],
        )
        execution = response["roomExecutionReceipt"]
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(
            self.service.room_capabilities.execution_receipt(
                str(execution["invocationReceiptId"])
            ),
            execution,
        )
        repeated_call = {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": self.session_id,
            "tool": "workspace_shell",
            "toolCallId": "tool:room-failed-shell",
            "loadReceiptId": loaded["receiptId"],
            "args": {
                "op": "run",
                "command": "printf ok",
                "cwd": str(self.root),
                "allowNetwork": False,
            },
        }
        with self.assertRaisesRegex(
            ToolAuthorizationError,
            "already has a terminal execution receipt",
        ):
            gateway.execute(repeated_call)
        self.assertEqual(len(attempted_commands), 1)

        repeated_call = {
            **repeated_call,
            "toolCallId": "tool:room-failed-shell-replay",
        }
        with self.assertRaisesRegex(
            ToolAuthorizationError,
            "duplicate failed Room Tool command blocked",
        ):
            gateway.execute(repeated_call)
        self.assertEqual(len(attempted_commands), 1)
        rejected = self.service.room_capabilities.execution_receipt(
            "invoke:tool:room-failed-shell-replay"
        )
        self.assertIsNotNone(rejected)
        self.assertEqual(rejected["status"], "rejected")

        evidence_target = self.root / "new-evidence.txt"
        evidence_target.write_text("new evidence\n", encoding="utf-8")
        read_load = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:room-replay-evidence",
                "toolName": "workspace_read",
                "createdAtMs": 6,
            }
        )["result"]
        read_response = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": self.session_id,
                "tool": "workspace_read",
                "toolCallId": "tool:room-replay-evidence",
                "loadReceiptId": read_load["receiptId"],
                "args": {
                    "op": "read",
                    "path": str(evidence_target),
                },
            }
        )
        self.assertEqual(
            read_response["result"]["content"],
            "new evidence\n",
        )
        repeated_call["toolCallId"] = "tool:room-failed-shell-after-evidence"
        retried = gateway.execute(repeated_call)
        self.assertEqual(
            retried["roomExecutionReceipt"]["status"],
            "failed",
        )
        self.assertEqual(len(attempted_commands), 2)

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

        self.assertEqual(
            product_tools,
            normal_agent_tools,
            [
                (
                    item.get("name"),
                    item.get("operation"),
                    item.get("authorized"),
                    item.get("deniedBy"),
                )
                for item in manifest["tools"]
            ],
        )
        self.assertTrue(
            {
                "workspace_read",
                "workspace_search",
                "workspace_patch",
                "workspace_shell",
                "memory",
                "browser",
                "desktop_semantic",
            }.issubset(product_tools)
        )
        self.assertIn("work_documents", product_tools)
        self.assertTrue(
            all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in product_tools)
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
                "publicSummary": "当前需要你补充下一步目标后才能继续。",
                "evidence": [],
                "residualRisks": ["尚未获得外部输入"],
                "waitingFor": "user",
                "resumeCondition": "用户补充下一步目标",
                "question": "下一步希望优先处理什么？",
                "questionKind": "unbounded",
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

    def test_kernel_rejects_non_facilitator_wait_for_user(self) -> None:
        room = self.service.rooms.get(self.room_id)
        facilitator = next(
            item
            for item in room["participants"]
            if str(item["id"]) != str(self.participant["id"])
        )
        with sqlite3.connect(self.service.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_roots WHERE root_id=?",
                ("root:service",),
            ).fetchone()
            assert row is not None
            root_payload = json.loads(str(row[0]))
            root_payload["facilitatorParticipantId"] = str(
                facilitator["id"]
            )
            conn.execute(
                """UPDATE room_kernel_roots
                   SET facilitator_participant_id=?,payload_json=?
                   WHERE root_id=?""",
                (
                    str(facilitator["id"]),
                    json.dumps(
                        root_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "root:service",
                ),
            )
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        commit_id = "commit:non-facilitator-user-wait"

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "only the Root Facilitator may wait for user input",
        ):
            self.service.room_kernel.apply_commit(
                {
                    "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
                    "commitId": commit_id,
                    "dispatchId": "dispatch:service",
                    "action": "wait",
                    "contentHash": "sha256:non-facilitator-user-wait",
                    "postProposal": None,
                    "continuation": {
                        "decision": "wait",
                        "waitingFor": "user",
                        "resumeCondition": "用户回答当前问题",
                        "question": "是否继续？",
                        "questionOptions": [
                            {"value": "yes", "label": "继续"},
                            {"value": "no", "label": "停止"},
                        ],
                    },
                    "qualityGateReceipt": {
                        "schemaVersion": (
                            "wisdom-weasel.room-quality-gate-receipt.v1"
                        ),
                        "receiptId": "quality:non-facilitator-user-wait",
                        "rootId": "root:service",
                        "taskId": "task:service",
                        "dispatchId": "dispatch:service",
                        "generation": 0,
                        "originalRequestChecked": True,
                        "verdict": "not_ready",
                        "items": [],
                        "residualRisks": ["等待用户输入"],
                        "createdAtMs": 10,
                    },
                    "evidenceRefs": [],
                    "requirementCoverage": [],
                    "createdAtMs": 10,
                },
                generation=0,
                now_ms=10,
            )
        self.assertIsNone(
            self.service.room_kernel.pending_user_wait(self.room_id)
        )

    def test_managed_dispatch_preparation_replays_after_crash_before_lease(self) -> None:
        dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(dispatch, now_ms=3)

        first = self.service._prepare_managed_room_dispatch(dispatch, 3)
        prepared = self.service.room_capabilities.runtime_binding(
            self.session_id, active_only=False
        )
        self.assertEqual(prepared["state"], "prepared")
        task_context = self.service.task_context.resolve(self.session_id)
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

    def test_room_private_session_projection_reuses_todo_owner_and_sse_hash(
        self,
    ) -> None:
        work_item = self._create_work_item(
            "todo-lineage",
            objective="Bind Todo to the exact Room WorkItem.",
        )
        with sqlite3.connect(self.service.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                ("task:service",),
            ).fetchone()
            assert row is not None
            task_payload = json.loads(str(row[0]))
            task_payload["workItemId"] = str(work_item["id"])
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(
                        task_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "task:service",
                ),
            )
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        before = self.service.room_kernel_snapshot(self.room_id)
        before_sequence = int(before["lastSequence"])
        self.service.sessions.mutate_agent_todo(
            self.session_id,
            {
                "op": "init",
                "list": [
                    {
                        "phase": "Room delivery",
                        "items": ["Inspect the exact WorkItem delivery"],
                    }
                ],
            },
            actor="agent-runtime",
            updated_at_ms=10,
        )
        self.service.publish_workflow_state(
            self.session_id,
            reason="todo:init",
        )
        after = self.service.room_kernel_snapshot(self.room_id)
        projected = next(
            item
            for item in after["sessions"]
            if item["sessionId"] == self.session_id
        )
        self.assertEqual(projected["participantId"], self.participant["id"])
        self.assertEqual(projected["todo"]["id"], f"todo:{self.session_id}")
        self.assertEqual(projected["todo"]["revision"], 1)
        self.assertEqual(
            projected["todo"]["roomLineage"],
            {
                "schemaVersion": "wisdom-weasel.room-todo-lineage.v1",
                "roomId": self.room_id,
                "rootId": "root:service",
                "taskId": "task:service",
                "workItemId": str(work_item["id"]),
                "dispatchId": "dispatch:service",
                "sessionId": self.session_id,
                "participantId": str(self.participant["id"]),
                "generation": 0,
                "taskRevision": 0,
                "ownershipRevision": 0,
                "workItemRevision": 0,
            },
        )
        self.assertEqual(
            projected["todo"]["phases"][0]["tasks"][0]["content"],
            "Inspect the exact WorkItem delivery",
        )
        self.assertNotEqual(after["snapshotHash"], before["snapshotHash"])
        todo_events = [
            event
            for event in self.service.room_kernel_projection.events(
                self.room_id,
                after_sequence=before_sequence,
            )
            if event["eventKind"] == "session_projection"
            and event["entityId"] == self.session_id
        ]
        self.assertEqual(len(todo_events), 1)
        self.assertEqual(
            todo_events[0]["payload"]["session"]["todo"]["revision"],
            1,
        )

    def test_room_todo_lineage_cannot_leak_across_work_items_in_one_session(
        self,
    ) -> None:
        first_work = self._create_work_item(
            "todo-first",
            objective="First exact WorkItem.",
        )
        with sqlite3.connect(self.service.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_tasks WHERE task_id=?",
                ("task:service",),
            ).fetchone()
            assert row is not None
            first_task = json.loads(str(row[0]))
            first_task["workItemId"] = str(first_work["id"])
            conn.execute(
                "UPDATE room_kernel_tasks SET payload_json=? WHERE task_id=?",
                (
                    json.dumps(first_task, sort_keys=True, separators=(",", ":")),
                    "task:service",
                ),
            )
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.assertTrue(self.service.room_kernel_worker.run_once())
        first_todo = self.service.sessions.mutate_agent_todo(
            self.session_id,
            {
                "op": "init",
                "list": [{"phase": "First", "items": ["First task"]}],
            },
            updated_at_ms=10,
        )["todo"]
        self.assertEqual(
            first_todo["roomLineage"]["workItemId"],
            first_work["id"],
        )

        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='committed', updated_at_ms=11 WHERE dispatch_id=?",
                ("dispatch:service",),
            )
        second_work = self._create_work_item(
            "todo-second",
            objective="Second exact WorkItem.",
        )
        self.service.room_kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:todo-second",
                "rootId": "root:service",
                "parentTaskId": None,
                "taskKind": "work",
                "workItemId": str(second_work["id"]),
                "currentOwnerParticipantId": str(self.participant["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Second exact WorkItem.",
                "expectedOutput": "A second exact result.",
                "requirementItemIds": [],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "active",
            },
            now_ms=12,
        )
        self.service.room_kernel.enqueue_dispatch(
            {
                **self._dispatch("dispatch:todo-second"),
                "taskId": "task:todo-second",
                "idempotencyKey": "dispatch:todo-second",
            },
            now_ms=13,
        )

        mismatched = self.service.room_kernel_snapshot(self.room_id)
        projected = next(
            item
            for item in mismatched["sessions"]
            if item["sessionId"] == self.session_id
        )
        self.assertEqual(projected["taskId"], "task:todo-second")
        self.assertEqual(projected["workItemId"], second_work["id"])
        self.assertEqual(projected["dispatchId"], "dispatch:todo-second")
        self.assertEqual(
            projected["todo"]["roomLineage"]["workItemId"],
            first_work["id"],
        )
        with self.assertRaisesRegex(ValueError, "lineage changed"):
            self.service.sessions.mutate_agent_todo(
                self.session_id,
                {"op": "start", "task": "First task"},
                updated_at_ms=14,
            )

        rebound = self.service.sessions.mutate_agent_todo(
            self.session_id,
            {
                "op": "init",
                "list": [{"phase": "Second", "items": ["Second task"]}],
            },
            updated_at_ms=15,
        )["todo"]
        self.assertEqual(rebound["revision"], 2)
        self.assertEqual(
            rebound["roomLineage"]["workItemId"],
            second_work["id"],
        )
        self.assertEqual(rebound["roomLineage"]["taskId"], "task:todo-second")
        refreshed = self.service.room_kernel_snapshot(self.room_id)
        self.assertNotEqual(refreshed["snapshotHash"], mismatched["snapshotHash"])

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

        task_context = self.service.task_context.resolve(self.session_id)

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
        work_item = self._create_work_item(
            "kernel-terminal-projection",
            objective="将 Kernel 终态投影回受管 WorkItem",
        )
        self.service.room_work.claim_dispatch(
            str(work_item["id"]),
            room_id=self.room_id,
            owner_participant_id=str(self.participant["id"]),
            assignment_key=str(work_item["assignmentKey"]),
            previous_accepted_turn_id="",
            room_turn_id="root:service",
            claimed_at_ms=2,
        )
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
        # The Root must declare the criterion too: the Kernel refuses a terminal
        # transition for a Root that has no acceptance criteria of its own.
        self._set_parent_acceptance("criterion:service")

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
                "kind": "work_result",
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
                "publicSummary": "当前责任已经完成并通过对应验证。",
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
        report_ready = self.service.finalize_room_kernel_root(
            "root:service",
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            target_commit="commit:test",
            blind_review_status="passed",
            now_ms=7,
        )
        report_dispatch = report_ready["reportDispatch"]
        self.assertEqual(report_dispatch["intentKind"], "close")
        self.assertEqual(report_dispatch["state"], "pending")
        report_task = self.service.room_kernel.task(
            str(report_dispatch["taskId"])
        )
        self.assertEqual(report_task["taskKind"], "report")
        report_snapshot = self.service.room_kernel_snapshot(self.room_id)
        self.assertEqual(
            [
                item["taskId"]
                for item in report_snapshot["tasks"]
                if item.get("taskKind") == "report"
            ],
            [report_dispatch["taskId"]],
        )
        gate = report_ready["deliveryGateObservation"]
        self.assertEqual(gate["gateStatus"], "observed_pass")
        self.assertTrue(gate["gateReceiptId"])
        self.assertFalse(gate["enforcementApplied"])

        self.service.room_kernel_worker.run_once()
        report_binding = self.service.room_kernel.session_binding(
            self.session_id
        )
        self.assertIsNotNone(report_binding)
        assert report_binding is not None
        todo_before_report = self.service.sessions.agent_todo(self.session_id)
        with self.assertRaisesRegex(
            ValueError,
            "ReportDispatch does not own a Room Todo",
        ):
            self.service.sessions.mutate_agent_todo(
                self.session_id,
                {
                    "op": "init",
                    "list": [
                        {
                            "phase": "Report",
                            "items": ["Must not overwrite peer WorkItem Todo"],
                        }
                    ],
                },
                updated_at_ms=8,
            )
        self.assertEqual(
            self.service.sessions.agent_todo(self.session_id),
            todo_before_report,
        )
        loaded_report = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:e2e-report",
                "toolName": "room_commit",
                "createdAtMs": 8,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": "deliver",
                "summary": "汇总已验证结果",
                "publicSummary": "工作结果与验证情况已经整理完毕，可以交付。",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": ["verification:service"],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:e2e-report",
            load_receipt_id=str(loaded_report["receiptId"]),
        )
        report_settled = self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": self.session_id,
                "dispatchId": str(report_dispatch["dispatchId"]),
                "rootId": "root:service",
                "generation": 0,
                "capabilityEpoch": int(report_dispatch["capabilityEpoch"]),
                "runtimeTurnId": str(report_binding["runtimeTurnId"]),
                "dispatchAttempt": int(report_dispatch["attempt"]),
                "settleScopeId": "scope:e2e-report",
                "settleAttempt": 1,
                "resourceUsage": {
                    "inputTokens": 60,
                    "outputTokens": 20,
                    "toolCalls": 1,
                    "toolCost": 1,
                    "retryCount": 0,
                    "repairCount": 0,
                },
            }
        )["result"]
        self.assertEqual(report_settled["state"], "committed")
        final = self.service.finalize_room_kernel_root(
            "root:service",
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            target_commit="commit:test",
            blind_review_status="passed",
            now_ms=9,
        )
        terminal_gate = final["receipt"]["details"][
            "deliveryGateObservation"
        ]
        self.assertEqual(terminal_gate["gateStatus"], "observed_pass")
        posts = self.service.room_kernel_snapshot(self.room_id)["posts"]
        self.assertEqual(posts[0]["postId"], "post:e2e")
        self.assertEqual(
            [post["kind"] for post in posts],
            ["work_result", "result"],
        )
        terminal_root = self.service.room_kernel.root("root:service")
        settled_work = self.service.room_work.get(str(work_item["id"]))
        self.assertEqual(settled_work["state"], "done")
        self.assertIn(
            terminal_root["terminalReceiptId"],
            settled_work["evidenceRefs"],
        )
        work_activities = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=500,
            )
            if (
                event["eventType"] == "participant_activity"
                and event["payload"].get("activityKind") == "work"
                and event["payload"].get("work", {}).get("id")
                == work_item["id"]
            )
        ]
        self.assertEqual(
            [
                event["payload"]["phase"]
                for event in work_activities
                if event["payload"]["phase"] == "completed"
            ],
            ["completed"],
        )
        replayed = self.service.finalize_room_kernel_root(
            "root:service",
            catalog_revision_id=str(catalog["catalogRevisionId"]),
            target_commit="commit:test",
            blind_review_status="passed",
            now_ms=10,
        )
        self.assertEqual(replayed, final)
        replayed_work_activities = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=500,
            )
            if (
                event["eventType"] == "participant_activity"
                and event["payload"].get("activityKind") == "work"
                and event["payload"].get("work", {}).get("id")
                == work_item["id"]
            )
        ]
        self.assertEqual(
            [event["eventId"] for event in replayed_work_activities],
            [event["eventId"] for event in work_activities],
        )

    def test_requirement_proof_observation_reaches_terminal_without_enforcement(self) -> None:
        self._exercise_requirement_proof_observation_to_terminal()

    @requires_process_identity
    def test_named_cohort_crosses_process_boundary_through_the_full_managed_chain(self) -> None:
        self.service.close()
        runtime_root = self.root / "rooms" / "process-runtime"
        runtime_root.mkdir(parents=True)
        host = runtime_root / "room-v2-process-host"
        host.write_text(FAKE_HOST, encoding="utf-8")
        host.chmod(0o755)
        config = PiRuntimeConfig(
            enabled=True,
            executable=host,
            agent_dir=runtime_root / "agent",
            session_dir=runtime_root / "sessions",
            logs_dir=runtime_root / "logs",
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
            db_path=runtime_root / "process.sqlite",
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
        # Session. The canonical closure lane is a Product-owned stage change,
        # so it closes the implementation Session and opens one fresh Reporter
        # Session; ordinary implementation Dispatches keep the resident journal.
        self.assertEqual(methods.count("session.open"), 2, methods)
        self.assertEqual(methods.count("session.close"), 1, methods)
        self.assertLess(methods.index("session.open"), methods.index("room.dispatch"))
        opened = next(request for request in requests if request["method"] == "session.open")
        reporter_open = [
            request for request in requests if request["method"] == "session.open"
        ][1]
        self.assertIn("<room-prompt-plan", opened["params"]["systemPrompt"])
        self.assertNotIn("运行时工具渐进披露规则", opened["params"]["systemPrompt"])
        session_context = opened["params"]["sessionContext"]
        room_context = opened["params"]["roomContext"]
        room_recovery = json.loads(
            opened["params"]["roomRecoveryContext"]
        )
        self.assertNotIn("schemaVersion", room_recovery)
        self.assertEqual(
            room_recovery["authoritativeProjectionRef"]["rootId"],
            "root:service",
        )
        self.assertEqual(
            room_recovery["authoritativeProjectionRef"]["taskId"],
            "task:service",
        )
        self.assertNotIn("currentTask", room_recovery)
        # No relevant governed memory was seeded for this process test. The
        # execution policy remains, but the RAG lane adds no placeholder.
        self.assertEqual(
            session_context.count('<execution-mode mode="workspace_managed">'),
            1,
        )
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
            "implementation-execution",
        )
        self.assertEqual(
            reporter_open["params"]["roomSkillPolicy"]["skillId"],
            "quality-gate",
        )
        self.assertEqual(methods.count("room.dispatch"), 3, methods)
        room_dispatches = [
            request
            for request in requests
            if request["method"] == "room.dispatch"
        ]
        dispatch_ids = [
            str(request["params"]["dispatchId"])
            for request in room_dispatches
        ]
        self.assertEqual(
            dispatch_ids[:2],
            ["dispatch:service", "dispatch:complete"],
        )
        self.assertTrue(
            dispatch_ids[2].startswith("room-report-dispatch:"),
            dispatch_ids,
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
            )["authoritativeProjectionRef"]["taskId"],
            "task:service",
        )
        second_dispatch_request = room_dispatches[1]
        self.assertEqual(
            second_dispatch_request["params"]["roomCapability"]["contextEpoch"],
            first_dispatch_request["params"]["roomCapability"]["contextEpoch"],
        )
        self.assertEqual(
            json.loads(
                second_dispatch_request["params"]["roomRecoveryContext"]
            )["authoritativeProjectionRef"]["taskId"],
            "task:service",
        )
        skill_receipt = self.service.room_skill_receipts.latest_for_session(self.session_id)
        self.assertIsNotNone(skill_receipt)
        self.assertEqual(skill_receipt["skillId"], "quality-gate")
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


    def test_full_auto_intake_preserves_anchor_single_alignment_and_reporter_receipt(
        self,
    ) -> None:
        message = "原始字节需求：保留换行\n并且只建立一个对齐派发。"
        roots_before = set(self.service.room_kernel.root_ids(self.room_id))
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": message,
                "clientMessageId": "client:full-auto-anchor",
            },
        )
        self.assertEqual(len(accepted["alignmentDispatches"]), 1)
        self.assertEqual(accepted["dispatches"], [])
        self.assertEqual(
            set(self.service.room_kernel.root_ids(self.room_id)) - roots_before,
            {accepted["rootId"]},
        )
        anchor = accepted["requirementAnchor"]
        self.assertEqual(
            self.service.room_requirements.original_bytes(anchor["anchorId"]),
            message.encode("utf-8"),
        )
        catalog = accepted["requirementCatalog"]
        item = catalog["items"][0]
        self.assertEqual(item["sourceSpans"][0]["startByte"], 0)
        self.assertEqual(
            item["sourceSpans"][0]["endByte"],
            len(message.encode("utf-8")),
        )
        root = self.service.room_kernel.root(accepted["rootId"])
        self.assertEqual(
            root["reporterParticipantId"],
            root["facilitatorParticipantId"],
        )
        with sqlite3.connect(self.service.db_path) as conn:
            receipt = conn.execute(
                "SELECT receipt_id FROM room_kernel_receipts WHERE receipt_id=?",
                (root["reporterSelectionReceiptId"],),
            ).fetchone()
        self.assertIsNotNone(receipt)
        self.assertEqual(
            self.service.room_kernel.intake_state(accepted["rootId"])["phase"],
            "aligning",
        )

    def test_room_define_is_idempotent_and_binds_one_work_item_atomically(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "请先完成需求澄清，再交给实现伙伴。",
                "clientMessageId": "client:define-intake",
            },
        )
        alignment = accepted["alignmentDispatches"][0]
        self.service.room_kernel_worker.run_once()
        target = self.service.rooms.get(self.room_id)["participants"][2]
        arguments = {
            "objective": "完成最终实现",
            "expectedOutput": "可验证的实现结果",
            "requirements": ["保留用户原始需求", "实现最终行为"],
            "acceptanceCriteria": [
                {
                    "statement": "实现结果通过验证",
                    "fullNameZh": "实现结果通过验证",
                    "expectedReceiptTypes": ["evidence"],
                }
            ],
            "implementationParticipantRef": "P3",
        }
        defined = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=alignment["dispatchId"],
            invocation_receipt_id="invoke:room-define",
            arguments=arguments,
        )
        replay = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=alignment["dispatchId"],
            invocation_receipt_id="invoke:room-define",
            arguments=arguments,
        )
        self.assertTrue(defined["created"])
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(
            defined["definitionReceipt"]["receiptId"],
            replay["definitionReceipt"]["receiptId"],
        )
        work_items = self.service.room_work.list_for_room(self.room_id)
        self.assertEqual(
            [
                item for item in work_items
                if item["id"] == defined["workItem"]["id"]
            ],
            [defined["workItem"]],
        )
        self.assertEqual(
            defined["workItem"]["accountableParticipantId"],
            accepted["root"]["facilitatorParticipantId"],
        )
        execute = defined["executionDispatch"]
        self.assertIsNotNone(execute)
        self.assertEqual(execute["intentKind"], "execute")
        self.assertEqual(
            execute["targetParticipantId"],
            accepted["root"]["facilitatorParticipantId"],
        )
        self.assertEqual(
            execute["capabilityEpoch"],
            self.service.room_kernel.dispatch(alignment["dispatchId"])[
                "capabilityEpoch"
            ]
            + 1,
        )
        self.assertEqual(
            self.service.room_kernel.dispatch(alignment["dispatchId"])["state"],
            "committed",
        )
        self.assertEqual(defined["intake"]["phase"], "executing")
        with sqlite3.connect(self.service.db_path) as conn:
            execute_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM room_kernel_dispatches "
                    "WHERE root_id=? AND intent_kind='execute'",
                    (str(accepted["rootId"]),),
                ).fetchone()[0]
            )
        self.assertEqual(execute_count, 1)
        report_readiness = self.service.room_kernel.report_readiness(
            str(accepted["rootId"])
        )
        self.assertEqual(
            report_readiness["lanePlan"]["fences"],
            [],
            "room_define must gate the lanes actually split at runtime, not "
            "a hard-coded implementation participant",
        )
        with sqlite3.connect(self.service.db_path) as conn:
            close_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM room_kernel_dispatches "
                    "WHERE root_id=? AND intent_kind='close'",
                    (str(accepted["rootId"]),),
                ).fetchone()[0]
            )
        self.assertEqual(close_count, 0)

    def test_room_define_defaults_to_facilitator_without_fake_peer(self) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "这是一个小型单写任务，不需要虚构并行伙伴。",
                "clientMessageId": "client:define-facilitator-only",
            },
        )
        alignment = accepted["alignmentDispatches"][0]
        self.service.room_kernel_worker.run_once()
        defined = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=alignment["dispatchId"],
            invocation_receipt_id="invoke:define-facilitator-only",
            arguments={
                "objective": "完成小型单写任务",
                "expectedOutput": "主持伙伴直接给出可验证结果",
                "requirements": ["不创建虚假的 Worker 分工"],
                "acceptanceCriteria": [
                    {
                        "statement": "只产生主持伙伴的首个执行任务",
                        "fullNameZh": "主持伙伴单写执行",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
            },
        )
        facilitator_id = str(accepted["root"]["facilitatorParticipantId"])
        self.assertEqual(
            defined["implementationParticipant"]["id"], facilitator_id
        )
        self.assertEqual(defined["implementationParticipantRef"], "")
        self.assertEqual(
            defined["executionDispatch"]["targetParticipantId"],
            facilitator_id,
        )
        with sqlite3.connect(self.service.db_path) as conn:
            execute_targets = conn.execute(
                "SELECT target_participant_id FROM room_kernel_dispatches "
                "WHERE root_id=? AND intent_kind='execute'",
                (str(accepted["rootId"]),),
            ).fetchall()
        self.assertEqual(execute_targets, [(facilitator_id,)])

    def test_room_define_accepts_explicit_facilitator_as_implementation_owner(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "由主持伙伴完成这项只读核对。",
                "clientMessageId": "client:define-explicit-facilitator",
            },
        )
        alignment = accepted["alignmentDispatches"][0]
        self.service.room_kernel_worker.run_once()
        facilitator_id = str(accepted["root"]["facilitatorParticipantId"])
        defined = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=alignment["dispatchId"],
            invocation_receipt_id="invoke:define-explicit-facilitator",
            arguments={
                "objective": "完成只读核对",
                "expectedOutput": "主持伙伴的核对结果",
                "requirements": ["不分配无意义的并行工作"],
                "acceptanceCriteria": [
                    {
                        "statement": "主持伙伴完成核对",
                        "fullNameZh": "主持伙伴核对完成",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
                "implementationParticipantRef": facilitator_id,
            },
        )
        self.assertEqual(
            defined["implementationParticipant"]["id"], facilitator_id
        )
        self.assertEqual(
            defined["executionDispatch"]["targetParticipantId"],
            facilitator_id,
        )

    def test_room_define_tool_fences_alignment_before_fresh_execute_dispatch(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "按完整目标直接定义并开始行动。",
                "clientMessageId": "client:define-tool-execute",
            },
        )
        alignment_id = str(
            accepted["alignmentDispatches"][0]["dispatchId"]
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        alignment = self.service.room_kernel.dispatch(alignment_id)
        session_id = str(alignment["targetSessionId"])
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": "load:define-tool",
                "toolName": "room_define",
                "createdAtMs": 20,
            }
        )["result"]
        target = self.service.rooms.get(self.room_id)["participants"][2]
        executed = self.service.execute_room_capability_tool(
            session_id,
            "room_define",
            {
                "objective": "实现完整目标",
                "expectedOutput": "可验证的实现结果",
                "requirements": ["保留完整目标", "提供验证结果"],
                "acceptanceCriteria": [
                    {
                        "statement": "实现结果可被验证",
                        "fullNameZh": "实现结果验证",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
                "implementationParticipantRef": str(target["id"]),
            },
            tool_call_id="call:define-tool",
            load_receipt_id=str(loaded["receiptId"]),
        )["result"]
        execute_id = str(executed["executionDispatch"]["dispatchId"])

        self.assertTrue(executed["terminalForModelTurn"])
        self.assertFalse(executed["requiresStartAction"])
        self.assertNotIn("alignmentPost", executed)
        self.assertFalse(
            any(
                event["eventType"] == "room_post"
                and event["payload"]["post"].get("rootId")
                == accepted["rootId"]
                and event["payload"]["post"].get("kind") == "alignment"
                for event in self.service.rooms.list_events(
                    self.room_id,
                    limit=500,
                )
            )
        )
        self.assertEqual(
            self.service.room_kernel.dispatch(alignment_id)["state"],
            "committed",
        )
        with sqlite3.connect(self.service.db_path) as conn:
            runtime_effect_state = conn.execute(
                "SELECT state FROM room_kernel_runtime_effects "
                "WHERE dispatch_id=?",
                (alignment_id,),
            ).fetchone()[0]
            abort_scope_state = conn.execute(
                "SELECT state FROM room_kernel_abort_scopes "
                "WHERE dispatch_id=?",
                (alignment_id,),
            ).fetchone()[0]
        self.assertEqual(runtime_effect_state, "completed")
        self.assertEqual(abort_scope_state, "completed")
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "does not belong to this Room alignment",
        ):
            self.service.room_application.define_room(
                self.room_id,
                dispatch_id=alignment_id,
                invocation_receipt_id="invoke:late-define",
                arguments={
                    "objective": "迟到定义",
                    "expectedOutput": "不得生效",
                    "requirements": ["不得生效"],
                    "acceptanceCriteria": [
                        {
                            "statement": "迟到调用被拒绝",
                            "fullNameZh": "迟到调用拒绝",
                            "expectedReceiptTypes": ["evidence"],
                        }
                    ],
                    "implementationParticipantRef": str(target["id"]),
                },
            )
        settled = self.service.room_settle_lifecycle.settle(
            {
                "sessionId": session_id,
                "dispatchId": alignment_id,
                "rootId": accepted["rootId"],
                "generation": alignment["generation"],
                "capabilityEpoch": alignment["capabilityEpoch"],
                "settleScopeId": "scope:define-tool",
                "settleAttempt": 1,
                "runtimeTurnId": "turn:define-tool",
                "dispatchAttempt": alignment["attempt"],
                "resourceUsage": {},
            }
        )
        self.assertEqual(settled["state"], "committed")
        self.assertTrue(self.service.room_kernel_worker.run_once())
        self.assertEqual(
            self.factory.runtime.dispatched[-1],
            execute_id,
        )

    def test_defined_root_runs_two_peer_lanes_with_nested_lineage_before_one_report(
        self,
    ) -> None:
        room = self.service.create_room(
            {
                "title": "双伙伴与私有子任务闭环",
                "routingPolicy": "parallel",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {
                        "roleId": "companion-present-v1",
                        "roleVersion": "1",
                        "collaborationRole": "coordinator",
                    },
                    {
                        "roleId": "companion-firstlight-v1",
                        "roleVersion": "1",
                        "collaborationRole": "implementer",
                    },
                    {
                        "roleId": "companion-future-v1",
                        "roleVersion": "1",
                        "collaborationRole": "researcher",
                    },
                    {
                        "roleId": "companion-flash-v1",
                        "roleVersion": "1",
                        "collaborationRole": "reviewer",
                    },
                ],
            }
        )["room"]
        facilitator, first_peer, second_peer, _reviewer = room["participants"]
        room_id = str(room["id"])
        accepted = self.service.post_room_message(
            room_id,
            {
                "message": "请两位伙伴分别完成实现核对和边界研究，再汇总一个结果。",
                "clientMessageId": "client:two-peer-nested-report",
            },
        )
        root_id = str(accepted["rootId"])
        alignment_id = str(
            accepted["alignmentDispatches"][0]["dispatchId"]
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        alignment = self.service.room_kernel.dispatch(alignment_id)
        facilitator_session = str(alignment["targetSessionId"])
        define_load = self.service.room_capability_tool_load(
            {
                "sessionId": facilitator_session,
                "receiptId": "load:two-peer:define",
                "toolName": "room_define",
                "createdAtMs": 20,
            }
        )["result"]
        defined = self.service.execute_room_capability_tool(
            facilitator_session,
            "room_define",
            {
                "objective": "并行核对实现与边界后交付一个已验证结果",
                "expectedOutput": "两位伙伴的独立结果、私有核验和最终汇总",
                "requirements": ["两位伙伴独立工作", "最终只发布一个结果"],
                "acceptanceCriteria": [
                    {
                        "statement": "两条独立工作线均有可核验证据",
                        "fullNameZh": "双工作线验收证据",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
                "implementationParticipantRef": str(first_peer["id"]),
            },
            tool_call_id="call:two-peer:define",
            load_receipt_id=str(define_load["receiptId"]),
        )["result"]
        execute_id = str(defined["executionDispatch"]["dispatchId"])
        self.assertTrue(self.service.room_kernel_worker.run_once())
        execute = self.service.room_kernel.dispatch(execute_id)
        self.assertEqual(execute["targetParticipantId"], facilitator["id"])

        state_load = self.service.room_capability_tool_load(
            {
                "sessionId": facilitator_session,
                "receiptId": "load:two-peer:state",
                "toolName": "room_state",
                "createdAtMs": 21,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            facilitator_session,
            "room_state",
            {},
            tool_call_id="call:two-peer:state",
            load_receipt_id=str(state_load["receiptId"]),
        )["result"]
        refs = {
            str(item["displayName"]): str(item["participantRef"])
            for item in state["participants"]
        }
        collaborate_load = self.service.room_capability_tool_load(
            {
                "sessionId": facilitator_session,
                "receiptId": "load:two-peer:collaborate",
                "toolName": "room_collaborate",
                "createdAtMs": 22,
            }
        )["result"]
        child_ids: list[str] = []
        for ordinal, peer in enumerate((first_peer, second_peer), start=1):
            collaboration = self.service.execute_room_capability_tool(
                facilitator_session,
                "room_collaborate",
                {
                    "targetParticipantRef": refs[str(peer["displayName"])],
                    "objective": f"独立完成第 {ordinal} 条工作线并提交证据",
                    "expectedOutput": f"第 {ordinal} 条工作线的核验结果",
                    "intent": "execute",
                    "acceptance": ["AC-1"],
                    "workspacePolicy": "read_only",
                    "evidenceRefs": [state["evidenceRef"]],
                },
                tool_call_id=f"call:two-peer:collaborate:{ordinal}",
                load_receipt_id=str(collaborate_load["receiptId"]),
            )["result"]
            child_ids.append(str(collaboration["childDispatchId"]))
        self.assertEqual(
            self.service.room_kernel.dispatch(execute_id)["state"],
            "running",
        )
        self.assertEqual(len(set(child_ids)), 2)

        def state_evidence(
            session_id: str,
            dispatch_id: str,
            suffix: str,
        ) -> str:
            loaded = self.service.room_capability_tool_load(
                {
                    "sessionId": session_id,
                    "receiptId": f"load:{suffix}:state",
                    "toolName": "room_state",
                    "createdAtMs": 30,
                }
            )["result"]
            result = self.service.execute_room_capability_tool(
                session_id,
                "room_state",
                {},
                tool_call_id=f"call:{suffix}:state",
                load_receipt_id=str(loaded["receiptId"]),
            )["result"]
            self.assertTrue(result["stateRevision"])
            return str(result["evidenceRef"])

        def deliver(
            session_id: str,
            dispatch_id: str,
            suffix: str,
            evidence_ref: str,
        ) -> dict[str, object]:
            dispatch = self.service.room_kernel.dispatch(dispatch_id)
            task = self.service.room_kernel.task(str(dispatch["taskId"]))
            if task.get("workspacePolicy") == "read_only":
                observed_snapshot = (
                    self.service.room_workspaces.task_snapshot_digest(task)
                )
                self.assertEqual(
                    observed_snapshot,
                    task.get("workspaceSnapshotSha256"),
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.root),
                            "status",
                            "--porcelain=v1",
                            "--untracked-files=all",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout,
                )
            loaded = self.service.room_capability_tool_load(
                {
                    "sessionId": session_id,
                    "receiptId": f"load:{suffix}:commit",
                    "toolName": "room_commit",
                    "createdAtMs": 31,
                }
            )["result"]
            self.service.execute_room_capability_tool(
                session_id,
                "room_commit",
                {
                    "decision": "deliver",
                    "summary": f"{suffix} 已完成",
                    "publicSummary": f"{suffix} 已完成并附带可核验证据。",
                    "evidence": [
                        {"acceptance": "AC-1", "refs": [evidence_ref]}
                    ],
                    "residualRisks": [],
                },
                tool_call_id=f"call:{suffix}:commit",
                load_receipt_id=str(loaded["receiptId"]),
            )
            settled = self.service.room_settle_lifecycle.settle(
                {
                    "sessionId": session_id,
                    "dispatchId": dispatch_id,
                    "rootId": root_id,
                    "generation": dispatch["generation"],
                    "capabilityEpoch": dispatch["capabilityEpoch"],
                    "settleScopeId": f"scope:{suffix}",
                    "settleAttempt": 1,
                    "runtimeTurnId": f"turn:{dispatch_id}:1",
                    "dispatchAttempt": dispatch["attempt"],
                    "resourceUsage": {},
                }
            )
            self.assertEqual(settled["state"], "committed", settled)
            return settled

        nested_batches: list[dict[str, object]] = []
        for ordinal, child_id in enumerate(child_ids, start=1):
            self.assertTrue(self.service.room_kernel_worker.run_once())
            child = self.service.room_kernel.dispatch(child_id)
            child_session = str(child["targetSessionId"])
            nested = self.service.delegate_tasks(
                child_session,
                {
                    "agent": "researcher",
                    "task": f"为第 {ordinal} 条工作线执行一次私有有界核验",
                    "expectedOutput": "返回有界核验结果供所属伙伴验证",
                    "acceptanceCriteria": ["结果回到所属伙伴且不直接发布到 Room"],
                },
            )["batch"]
            nested_batches.append(nested)
            self.assertEqual(nested["state"], "completed")
            self.assertEqual(len(nested["runs"]), 1)
            self.assertEqual(
                nested["causalMetadata"],
                {
                    "todoId": f"todo:{child_session}",
                    "todoRevision": 0,
                    "goalId": "",
                    "goalRevision": 0,
                    "roomBound": True,
                    "roomId": room_id,
                    "rootId": root_id,
                    "taskId": child["taskId"],
                    "dispatchId": child_id,
                    "generation": child["generation"],
                },
            )
            evidence_ref = state_evidence(
                child_session,
                child_id,
                f"two-peer:{ordinal}",
            )
            deliver(
                child_session,
                child_id,
                f"第 {ordinal} 条工作线",
                evidence_ref,
            )
        self.assertEqual(
            len(
                {
                    batch["causalMetadata"]["dispatchId"]
                    for batch in nested_batches
                }
            ),
            2,
        )
        child_projection = self.service.room_kernel.collaboration_children(
            root_id
        )
        self.assertEqual(len(child_projection), 2)
        self.assertTrue(all(item["resultPublic"] for item in child_projection))
        defined_work_item_id = str(defined["workItem"]["id"])
        for child in child_projection:
            delivered_task = self.service.room_kernel.task(
                str(child["taskId"])
            )
            self.assertEqual(
                delivered_task["workItemId"],
                defined_work_item_id,
            )
            self.assertIn("已完成并附带可核验证据", delivered_task["resultSummary"])
            self.assertEqual(delivered_task["resultKind"], "complete")
            self.assertEqual(delivered_task["verificationCount"], 1)
            self.assertEqual(
                delivered_task["verifications"],
                [
                    {
                        "label": "验收项 1",
                        "result": "pass",
                        "source": "quality_gate",
                    }
                ],
            )
            public_verifications = json.dumps(
                delivered_task["verifications"], ensure_ascii=False
            )
            self.assertNotIn("AC-", public_verifications)
            self.assertNotIn("criterionId", public_verifications)
            self.assertNotIn("workspaceDelivery", delivered_task)
        quiescence = self.service._room_root_child_quiescence(
            root_id,
            int(execute["generation"]),
            execute_id,
        )
        self.assertTrue(quiescence["quiescent"], quiescence)

        execute_evidence = state_evidence(
            facilitator_session,
            execute_id,
            "two-peer:facilitator",
        )
        deliver(
            facilitator_session,
            execute_id,
            "伙伴结果汇总",
            execute_evidence,
        )
        report_state = self.service.room_kernel.report_readiness(root_id)
        report = report_state["existing"]
        report_dispatch = report["dispatch"]
        report_details = report["receipt"]["details"]
        self.assertEqual(report_dispatch["intentKind"], "close")
        self.assertEqual(report["task"]["workspacePolicy"], "read_only")
        self.assertEqual(
            set(report_details["lanePlanDispatchIds"]),
            set(child_ids),
        )
        self.assertEqual(
            set(report_details["workerDeliveryDispatchIds"]),
            set(child_ids),
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        report_evidence = state_evidence(
            facilitator_session,
            str(report_dispatch["dispatchId"]),
            "two-peer:report",
        )
        deliver(
            facilitator_session,
            str(report_dispatch["dispatchId"]),
            "最终汇总",
            report_evidence,
        )
        terminal_root = self.service.room_kernel.root(root_id)
        self.assertEqual(terminal_root["state"], "completed")
        snapshot = self.service.room_kernel_snapshot(room_id)
        close_dispatches = [
            item
            for item in snapshot["dispatches"]
            if item.get("rootId") == root_id and item["intentKind"] == "close"
        ]
        final_posts = [
            item
            for item in snapshot["posts"]
            if item.get("rootId") == root_id and item["kind"] == "result"
        ]
        self.assertEqual(len(close_dispatches), 1)
        self.assertEqual(len(final_posts), 1)
        report_task = self.service.room_kernel.task(
            str(report_dispatch["taskId"])
        )
        self.assertEqual(report_task["taskKind"], "report")
        self.assertEqual(report_task["workItemId"], defined_work_item_id)
        self.assertIn("最终汇总", report_task["resultSummary"])
        projected_work_item = self.service.room_work.get(
            defined_work_item_id
        )
        self.assertIn("最终汇总", projected_work_item["resultSummary"])

    def test_room_define_cannot_assign_reviewer_as_implementation_partner(
        self,
    ) -> None:
        reviewer = self.service.rooms.get(self.room_id)["participants"][2]
        self.service.rooms.update_participant_role(
            self.room_id,
            str(reviewer["id"]),
            "reviewer",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "先定义实现范围，最终再做独立复核。",
                "clientMessageId": "client:define-reviewer-fence",
            },
        )
        alignment = accepted["alignmentDispatches"][0]
        self.assertTrue(self.service.room_kernel_worker.run_once())

        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "Reviewer enters only after integration",
        ):
            self.service.room_application.define_room(
                self.room_id,
                dispatch_id=str(alignment["dispatchId"]),
                invocation_receipt_id="invoke:reviewer-as-implementer",
                arguments={
                    "objective": "完成实现并经过独立复核",
                    "expectedOutput": "可验证的最终结果",
                    "requirements": ["Reviewer 不参与实现"],
                    "acceptanceCriteria": [
                        {
                            "statement": "实现完成后独立复核",
                            "fullNameZh": "实现完成后独立复核",
                            "expectedReceiptTypes": ["evidence"],
                        }
                    ],
                    "implementationParticipantRef": "P3",
                },
            )

        self.assertIsNone(
            self.service.room_kernel.definition_fence(
                root_id=str(accepted["rootId"]),
                dispatch_id=str(alignment["dispatchId"]),
            )
        )

    def test_active_reviewer_roster_does_not_infer_root_review_policy(
        self,
    ) -> None:
        reviewer = self.service.rooms.get(self.room_id)["participants"][2]
        self.service.rooms.update_participant_role(
            self.room_id,
            str(reviewer["id"]),
            "reviewer",
        )
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "先定义，再由实现伙伴执行和 Reviewer 独立复核。",
                "clientMessageId": "client:define-requires-review",
            },
        )
        alignment = accepted["alignmentDispatches"][0]
        self.assertFalse(accepted["root"]["independentReviewRequired"])
        self.assertTrue(self.service.room_kernel_worker.run_once())

        defined = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=str(alignment["dispatchId"]),
            invocation_receipt_id="invoke:definition-review-policy",
            arguments={
                "objective": "完成实现并经过独立复核",
                "expectedOutput": "可验证的最终结果",
                "requirements": ["实现与复核责任分离"],
                "acceptanceCriteria": [
                    {
                        "statement": "实现完成后由 Reviewer 独立复核",
                        "fullNameZh": "独立复核结果",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
                "implementationParticipantRef": "P2",
            },
        )

        self.assertFalse(
            self.service.room_kernel.root(
                str(accepted["rootId"])
            )["independentReviewRequired"]
        )
        self.assertFalse(
            defined["definitionReceipt"]["details"][
                "independentReviewRequired"
            ]
        )

    def test_user_answer_resumes_same_alignment_once_and_replays_idempotently(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "请先向我确认一个必要澄清。",
                "clientMessageId": "client:wait-intake",
            },
        )
        alignment = accepted["alignmentDispatches"][0]
        root_id = accepted["rootId"]
        task_id = accepted["taskId"]
        parent_id = alignment["dispatchId"]
        continuation_id = "continuation:test-user-wait"
        now_ms = 100
        parent_dispatch = self.service.room_kernel.dispatch(parent_id)
        self.service.room_requirements.prepare_dispatch_binding(
            dispatch_id=parent_id,
            root_id=root_id,
            task_id=task_id,
            session_id=str(parent_dispatch["targetSessionId"]),
            generation=int(parent_dispatch["generation"]),
            requirement_anchor_ref=str(
                accepted["root"]["requirementAnchorRef"]
            ),
            created_at_ms=now_ms,
        )
        continuation_payload = {
            "decision": "wait",
            "waitingFor": "user",
            "resumeCondition": "answer",
            "question": "请确认",
            "questionOptions": [
                {
                    "value": "continue",
                    "label": "继续执行",
                },
                {
                    "value": "stop",
                    "label": "停止",
                },
            ],
        }
        commit_payload = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:test-user-wait",
            "dispatchId": parent_id,
            "action": "wait",
            "contentHash": "sha256:test-user-wait",
            "postProposal": None,
            "continuation": continuation_payload,
            "qualityGateReceipt": {
                "schemaVersion": (
                    "wisdom-weasel.room-quality-gate-receipt.v1"
                ),
                "receiptId": "quality:test-user-wait",
                "rootId": root_id,
                "taskId": task_id,
                "dispatchId": parent_id,
                "generation": int(parent_dispatch["generation"]),
                "originalRequestChecked": True,
                "verdict": "not_ready",
                "items": [],
                "residualRisks": ["Waiting for a user answer."],
                "createdAtMs": now_ms,
            },
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": now_ms,
        }
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                """
                INSERT INTO room_kernel_commits(
                    commit_id,root_id,dispatch_id,generation,payload_json,
                    created_at_ms
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    "commit:test-user-wait",
                    root_id,
                    parent_id,
                    int(parent_dispatch["generation"]),
                    json.dumps(commit_payload, ensure_ascii=False),
                    now_ms,
                ),
            )
            conn.execute(
                """
                INSERT INTO room_kernel_continuations(
                    continuation_id,root_id,task_id,parent_dispatch_id,
                    child_dispatch_id,commit_id,decision,state,payload_json,
                    created_at_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    continuation_id,
                    root_id,
                    task_id,
                    parent_id,
                    None,
                    "commit:test-user-wait",
                    "wait",
                    "applied",
                    json.dumps(
                        continuation_payload,
                        ensure_ascii=False,
                    ),
                    now_ms,
                ),
            )
            conn.execute(
                "UPDATE room_kernel_dispatches SET state='committed' WHERE dispatch_id=?",
                (parent_id,),
            )
            conn.execute(
                "UPDATE room_kernel_tasks SET state='waiting' WHERE task_id=?",
                (task_id,),
            )
            conn.execute(
                "UPDATE room_kernel_roots SET state='waiting' WHERE root_id=?",
                (root_id,),
            )
        pending_wait = self.service.room_kernel.pending_user_wait(
            self.room_id
        )
        self.assertIsNotNone(pending_wait)
        assert pending_wait is not None
        question_post_id = str(pending_wait["questionPostId"])
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "does not match an active question and Root",
        ):
            self.service.post_room_message(
                self.room_id,
                {
                    "message": "continue",
                    "clientMessageId": "client:wrong-question-answer",
                    "answerToPostId": "room-post:wrong-question",
                    "answerToRootId": root_id,
                },
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "does not match an active question and Root",
        ):
            self.service.post_room_message(
                self.room_id,
                {
                    "message": "continue",
                    "clientMessageId": "client:wrong-root-answer",
                    "answerToPostId": question_post_id,
                    "answerToRootId": "room-root:wrong",
                },
            )
        ordinary = self.service.post_room_message(
            self.room_id,
            {
                "message": "这是一条普通消息，不是对澄清问题的回答。",
                "clientMessageId": "client:ordinary-during-wait",
            },
        )
        self.assertFalse(ordinary.get("resumed", False))
        self.assertNotEqual(ordinary["rootId"], root_id)
        still_pending = self.service.room_kernel.pending_user_wait(
            self.room_id,
            root_id=root_id,
            question_post_id=question_post_id,
        )
        self.assertIsNotNone(still_pending)
        self.service.room_kernel.cancel_root(
            str(ordinary["rootId"]),
            now_ms=101,
        )
        answered = self.service.post_room_message(
            self.room_id,
            {
                "message": "continue",
                "clientMessageId": "client:wait-answer",
                "answerKind": "option",
                "answerToPostId": question_post_id,
                "answerToRootId": root_id,
            },
        )
        self.assertTrue(answered["resumed"])
        self.assertEqual(answered["rootId"], root_id)
        self.assertEqual(answered["taskId"], task_id)
        self.assertEqual(
            answered["dispatches"][0]["participantId"],
            accepted["alignmentDispatches"][0]["participantId"],
        )
        answer_event = next(
            event
            for event in answered["timelineEvents"]
            if event["eventType"] == "user_message"
        )
        self.assertEqual(
            answer_event["payload"]["answerToPostId"],
            question_post_id,
        )
        self.assertEqual(answer_event["payload"]["text"], "继续执行")
        self.assertNotIn("displayText", answer_event["payload"])
        self.assertEqual(answered["post"]["content"], "继续执行")
        self.assertEqual(
            answered["requirementCatalog"]["items"][-1]["statement"],
            "继续执行",
        )
        self.assertEqual(
            answered["requirementAnchor"]["provenance"]["answerValue"],
            "continue",
        )
        self.assertEqual(
            answered["requirementAnchor"]["provenance"][
                "answerDisplayText"
            ],
            "继续执行",
        )
        self.assertEqual(
            answered["requirementAnchor"]["provenance"]["answerKind"],
            "option",
        )
        replay = self.service.post_room_message(
            self.room_id,
            {
                "message": "continue",
                "clientMessageId": "client:wait-answer",
                "answerKind": "option",
                "answerToPostId": question_post_id,
                "answerToRootId": root_id,
            },
        )
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(
            replay["dispatches"][0]["dispatchId"],
            answered["dispatches"][0]["dispatchId"],
        )
        self.assertIsNone(self.service.room_kernel.pending_user_wait(self.room_id))
        reconnected_rooms = type(self.service.rooms)(self.service.db_path)
        reconnected_rooms.initialize()
        durable_answer = next(
            event
            for event in reconnected_rooms.list_events(
                self.room_id,
                limit=500,
            )
            if event["eventType"] == "user_message"
            and event["payload"].get("postId") == answered["post"]["postId"]
        )
        self.assertEqual(
            durable_answer["payload"]["answerToPostId"],
            question_post_id,
        )
        resumed_dispatch_id = str(answered["dispatches"][0]["dispatchId"])
        self.assertTrue(self.service.room_kernel_worker.run_once())
        self.assertTrue(
            self.service.room_kernel.dispatch_is_active_alignment(
                resumed_dispatch_id
            )
        )
        resumed_session_id = str(
            self.service.room_kernel.dispatch(resumed_dispatch_id)[
                "targetSessionId"
            ]
        )
        resumed_skill = self.service.room_skill_receipts.latest_for_session(
            resumed_session_id
        )
        self.assertIsNotNone(resumed_skill)
        assert resumed_skill is not None
        self.assertEqual(resumed_skill["skillId"], "alignment-and-decision")
        runtime_manifest = self.service.room_capabilities.manifest_for_runtime(
            resumed_session_id
        )
        self.assertIsNotNone(runtime_manifest)
        assert runtime_manifest is not None
        self.assertEqual(
            {str(tool["name"]) for tool in runtime_manifest[0]["tools"]},
            {"room_state", "room_post", "room_commit", "room_define"},
        )
        target = self.service.rooms.get(self.room_id)["participants"][2]
        defined = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=resumed_dispatch_id,
            invocation_receipt_id="invoke:resumed-room-define",
            arguments={
                "objective": "按用户回答完成最终实现",
                "expectedOutput": "可验证的实现结果",
                "requirements": ["保留原请求和澄清回答"],
                "acceptanceCriteria": [
                    {
                        "statement": "实现结果通过验证",
                        "fullNameZh": "实现结果通过验证",
                        "expectedReceiptTypes": ["evidence"],
                    }
                ],
                "implementationParticipantRef": "P3",
            },
        )
        self.assertEqual(defined["dispatchId"], resumed_dispatch_id)
        self.assertEqual(
            defined["workItem"]["accountableParticipantId"],
            accepted["root"]["facilitatorParticipantId"],
        )

    def test_answer_kind_preserves_custom_text_that_matches_option_value(
        self,
    ) -> None:
        options = [
            {"value": "continue", "label": "继续执行"},
            {"value": "stop", "label": "停止"},
        ]
        self.assertEqual(
            _resolve_room_answer_display(
                "continue",
                answer_kind="custom",
                question_options=options,
            ),
            ("continue", "custom"),
        )
        self.assertEqual(
            _resolve_room_answer_display(
                "continue",
                answer_kind="option",
                question_options=options,
            ),
            ("继续执行", "option"),
        )
        with self.assertRaisesRegex(ValueError, "does not match a presented option"):
            _resolve_room_answer_display(
                "missing",
                answer_kind="option",
                question_options=options,
            )

    def test_answer_kind_requires_clarification_identity(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "answerKind requires answerToPostId and answerToRootId",
        ):
            self.service.post_room_message(
                self.room_id,
                {
                    "message": "custom answer",
                    "clientMessageId": "client:answer-kind-without-question",
                    "answerKind": "custom",
                },
            )

    def test_clarified_definition_waits_for_one_typed_start_action(
        self,
    ) -> None:
        accepted = self.service.post_room_message(
            self.room_id,
            {
                "message": "请先确认输出边界，再开始实现。",
                "clientMessageId": "client:typed-start-intake",
            },
        )
        alignment_id = str(
            accepted["alignmentDispatches"][0]["dispatchId"]
        )
        self.assertTrue(self.service.room_kernel_worker.run_once())
        alignment = self.service.room_kernel.dispatch(alignment_id)
        session_id = str(alignment["targetSessionId"])
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": "load:typed-start:commit",
                "toolName": "room_commit",
                "createdAtMs": 10,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            session_id,
            "room_commit",
            {
                "decision": "wait",
                "summary": "需要确认最终输出边界",
                "publicSummary": "请确认最终结果需要包含实现和验证记录吗？",
                "evidence": [],
                "residualRisks": ["输出边界尚未确认"],
                "waitingFor": "user",
                "resumeCondition": "用户确认输出边界",
                "question": "最终结果需要包含实现和验证记录吗？",
                "questionKind": "bounded",
                "questionOptions": [
                    {"label": "需要", "value": "yes"},
                    {"label": "不需要", "value": "no"},
                ],
            },
            tool_call_id="call:typed-start:wait",
            load_receipt_id=str(loaded["receiptId"]),
        )
        settled = self.service.room_settle_lifecycle.settle(
            {
                "sessionId": session_id,
                "dispatchId": alignment_id,
                "rootId": accepted["rootId"],
                "generation": alignment["generation"],
                "capabilityEpoch": alignment["capabilityEpoch"],
                "settleScopeId": "scope:typed-start:wait",
                "settleAttempt": 1,
                "runtimeTurnId": "turn:typed-start:wait",
                "dispatchAttempt": alignment["attempt"],
                "resourceUsage": {},
            }
        )
        self.assertEqual(settled["state"], "committed")
        self.assertEqual(
            self.service.room_kernel.intake_state(accepted["rootId"])["phase"],
            "clarifying",
        )

        pending = self.service.room_kernel.pending_user_wait(self.room_id)
        self.assertIsNotNone(pending)
        assert pending is not None
        answer_payload = {
            "message": "yes",
            "clientMessageId": "client:typed-start-answer",
            "answerToPostId": pending["questionPostId"],
            "answerToRootId": pending["rootId"],
            "answerKind": "option",
        }
        with patch.object(
            self.service.room_public_timeline,
            "publish_ingress",
            side_effect=RuntimeError("crash before answer publication"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "crash before answer publication",
            ):
                self.service.post_room_message(
                    self.room_id,
                    answer_payload,
                )
        self.assertFalse(self.service.room_kernel_worker.run_once())
        self.assertIsNotNone(
            self.service.room_kernel.pending_user_wait(
                self.room_id,
                root_id=str(pending["rootId"]),
                question_post_id=str(pending["questionPostId"]),
            )
        )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "different prepared answer",
        ):
            self.service.post_room_message(
                self.room_id,
                {
                    **answer_payload,
                    "message": "no",
                    "clientMessageId": "client:typed-start-answer-racer",
                },
            )
        with patch.object(
            self.service.room_kernel,
            "resume_user_wait_after_public_in_transaction",
            side_effect=RuntimeError("crash after answer publication"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "crash after answer publication",
            ):
                self.service.post_room_message(
                    self.room_id,
                    answer_payload,
                )
        self.assertFalse(self.service.room_kernel_worker.run_once())
        self.assertIsNotNone(
            self.service.room_kernel.pending_user_wait(
                self.room_id,
                root_id=str(pending["rootId"]),
                question_post_id=str(pending["questionPostId"]),
            )
        )
        staged_answer_events = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=500,
            )
            if event["eventType"] == "user_message"
            and event["payload"].get("clientMessageId")
            == answer_payload["clientMessageId"]
        ]
        self.assertEqual(len(staged_answer_events), 1)
        original_publish_ingress = (
            self.service.room_public_timeline.publish_ingress
        )

        def fail_answer_route_projection(*args, **kwargs):
            if kwargs.get("route_decisions"):
                raise RuntimeError("crash after answer resume")
            return original_publish_ingress(*args, **kwargs)

        with patch.object(
            self.service.room_public_timeline,
            "publish_ingress",
            side_effect=fail_answer_route_projection,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "crash after answer resume",
            ):
                self.service.post_room_message(
                    self.room_id,
                    answer_payload,
                )
        resume_preparation = self.service.room_kernel.pending_user_wait(
            self.room_id,
            root_id=str(pending["rootId"]),
            question_post_id=str(pending["questionPostId"]),
        )
        self.assertIsNotNone(resume_preparation)
        assert resume_preparation is not None
        self.assertEqual(resume_preparation["state"], "resumed")
        self.assertTrue(self.service.room_kernel_worker.run_once())

        answered = self.service.post_room_message(
            self.room_id,
            answer_payload,
        )
        replayed_answer_event = next(
            event
            for event in answered["timelineEvents"]
            if event["eventType"] == "user_message"
        )
        self.assertEqual(
            replayed_answer_event["payload"]["answerToPostId"],
            pending["questionPostId"],
        )
        self.assertEqual(
            replayed_answer_event["payload"]["answerKind"],
            "option",
        )
        self.assertEqual(
            replayed_answer_event["payload"]["text"],
            "需要",
        )
        resume_id = str(answered["dispatches"][0]["dispatchId"])
        self.assertEqual(
            resume_id,
            resume_preparation["payload"]["resumeDispatchId"],
        )
        self.assertEqual(
            answered["resumeReceipt"]["receiptId"],
            resume_preparation["payload"]["resumeReceiptId"],
        )
        self.assertTrue(
            self.service.room_kernel.dispatch_is_active_alignment(
                resume_id
            )
        )
        target = self.service.rooms.get(self.room_id)["participants"][2]
        define_arguments = {
            "objective": "完成实现并附验证记录",
            "expectedOutput": "实现结果和验证记录",
            "requirements": ["实现目标行为", "保留验证记录"],
            "acceptanceCriteria": [
                {
                    "statement": "实现和验证记录均可核验",
                    "fullNameZh": "实现与验证记录",
                    "expectedReceiptTypes": ["evidence"],
                }
            ],
            "implementationParticipantRef": str(target["id"]),
        }
        define_loaded = self.service.room_capability_tool_load(
            {
                "sessionId": str(
                    self.service.room_kernel.dispatch(resume_id)[
                        "targetSessionId"
                    ]
                ),
                "receiptId": "load:typed-start:define",
                "toolName": "room_define",
                "createdAtMs": 20,
            }
        )["result"]
        defined = self.service.execute_room_capability_tool(
            str(self.service.room_kernel.dispatch(resume_id)["targetSessionId"]),
            "room_define",
            define_arguments,
            tool_call_id="call:typed-start:define",
            load_receipt_id=str(define_loaded["receiptId"]),
        )["result"]
        self.assertTrue(defined["requiresStartAction"])
        self.assertIsNone(defined["executionDispatch"])
        self.assertEqual(defined["intake"]["phase"], "awaiting_start")
        alignment_post = defined["alignmentPost"]
        self.assertEqual(alignment_post["kind"], "alignment")
        self.assertEqual(
            alignment_post["publicationSource"]["kind"],
            "room_post",
        )
        self.assertEqual(
            alignment_post["content"],
            "已经对齐：目标是“完成实现并附验证记录”，"
            "交付边界是“实现结果和验证记录”。",
        )
        self.assertNotRegex(
            alignment_post["content"],
            r"rootId|dispatchId|schemaVersion|room-root:|room-dispatch:|\{",
        )
        replayed_definition = self.service.room_application.define_room(
            self.room_id,
            dispatch_id=resume_id,
            invocation_receipt_id="invoke:call:typed-start:define",
            arguments=define_arguments,
        )
        self.assertTrue(replayed_definition["idempotentReplay"])
        self.assertEqual(
            replayed_definition["alignmentPost"],
            alignment_post,
        )
        self.service.room_public_timeline.publish_post(
            replayed_definition["alignmentPost"],
            participant_id=str(alignment["targetParticipantId"]),
            source_session_id=str(alignment["targetSessionId"]),
            topic_id=str(
                self.service.rooms.get(self.room_id).get("activeTopicId")
                or ""
            ),
        )
        alignment_events = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=500,
            )
            if event["eventType"] == "room_post"
            and event["payload"]["post"].get("rootId")
            == accepted["rootId"]
            and event["payload"]["post"].get("kind") == "alignment"
        ]
        self.assertEqual(len(alignment_events), 1)
        self.assertEqual(
            alignment_events[0]["payload"]["post"],
            alignment_post,
        )
        kernel_alignment_posts = [
            post
            for post in self.service.room_kernel_snapshot(self.room_id)["posts"]
            if post.get("rootId") == accepted["rootId"]
            and post.get("kind") == "alignment"
        ]
        self.assertEqual(kernel_alignment_posts, [alignment_post])
        context_alignment_posts = [
            post
            for post in self.service.room_context_ledger.recent_posts(
                str(accepted["rootId"]),
                limit=20,
            )
            if post.get("kind") == "alignment"
        ]
        self.assertEqual(len(context_alignment_posts), 1)
        self.assertEqual(
            context_alignment_posts[0]["postId"],
            alignment_post["postId"],
        )

        planned_dispatch_id = str(
            defined["definitionReceipt"]["details"]["plannedExecuteDispatch"][
                "dispatchId"
            ]
        )
        defined_task_id = str(
            defined["definitionReceipt"]["details"]["plannedExecuteDispatch"][
                "taskId"
            ]
        )
        start_payload = {
            "action": "start_execution",
            "rootId": accepted["rootId"],
            "clientActionId": "action:typed-start",
        }
        with patch.object(
            self.service.room_public_timeline,
            "publish_ingress",
            side_effect=RuntimeError("public timeline unavailable"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "public timeline unavailable",
            ):
                self.service.start_room_execution(
                    self.room_id,
                    start_payload,
                )
        self.assertEqual(
            self.service.room_kernel.root(accepted["rootId"])["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.task(defined_task_id)["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.intake_state(accepted["rootId"])[
                "phase"
            ],
            "awaiting_start",
        )
        with self.assertRaises(KeyError):
            self.service.room_kernel.dispatch(planned_dispatch_id)
        start_events_after_publication_failure = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=500,
            )
            if event["eventType"] == "user_message"
            and event["payload"].get("text") == "开始行动"
        ]
        self.assertEqual(start_events_after_publication_failure, [])

        with patch.object(
            self.service.room_kernel,
            "start_defined_execution",
            side_effect=RuntimeError("crash before CAS release"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "crash before CAS release",
            ):
                self.service.start_room_execution(
                    self.room_id,
                    start_payload,
                )
        self.assertEqual(
            self.service.room_kernel.root(accepted["rootId"])["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.task(defined_task_id)["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.intake_state(accepted["rootId"])[
                "phase"
            ],
            "awaiting_start",
        )
        with self.assertRaises(KeyError):
            self.service.room_kernel.dispatch(planned_dispatch_id)
        durable_start_events = [
            event
            for event in self.service.rooms.list_events(
                self.room_id,
                limit=500,
            )
            if event["eventType"] == "user_message"
            and event["payload"].get("text") == "开始行动"
        ]
        self.assertEqual(len(durable_start_events), 1)
        retained_start_event = durable_start_events[0]
        start_projection_key = (
            f"room-post:{retained_start_event['payload']['postId']}"
        )
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                "DELETE FROM agent_room_events WHERE event_id=?",
                (retained_start_event["eventId"],),
            )
            projection_receipt = conn.execute(
                """SELECT event_id FROM agent_room_public_projection_receipts
                   WHERE projection_key=?""",
                (start_projection_key,),
            ).fetchone()
        self.assertIsNotNone(projection_receipt)
        assert projection_receipt is not None
        self.assertEqual(
            str(projection_receipt[0]),
            retained_start_event["eventId"],
        )
        rolled_back_start_posts = [
            post
            for post in self.service.room_kernel_snapshot(self.room_id)[
                "posts"
            ]
            if post.get("rootId") == accepted["rootId"]
            and post.get("content") == "开始行动"
        ]
        self.assertEqual(rolled_back_start_posts, [])

        original_receipt = self.service.room_kernel._receipt

        def fail_final_start_receipt(*args, **kwargs):
            details = kwargs.get("details")
            if (
                isinstance(details, Mapping)
                and details.get("purpose") == "typed_start_action"
            ):
                raise RuntimeError("crash after dispatch enqueue")
            return original_receipt(*args, **kwargs)

        with patch.object(
            self.service.room_kernel,
            "_receipt",
            side_effect=fail_final_start_receipt,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "crash after dispatch enqueue",
            ):
                self.service.start_room_execution(
                    self.room_id,
                    start_payload,
                )
        self.assertEqual(
            self.service.room_kernel.root(accepted["rootId"])["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.task(defined_task_id)["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.intake_state(accepted["rootId"])[
                "phase"
            ],
            "awaiting_start",
        )
        with self.assertRaises(KeyError):
            self.service.room_kernel.dispatch(planned_dispatch_id)
        self.assertEqual(
            [
                post
                for post in self.service.room_kernel_snapshot(self.room_id)[
                    "posts"
                ]
                if post.get("rootId") == accepted["rootId"]
                and post.get("content") == "开始行动"
            ],
            [],
        )

        started = self.service.start_room_execution(
            self.room_id,
            start_payload,
        )
        replay = self.service.start_room_execution(
            self.room_id,
            {
                **start_payload,
                "clientActionId": "action:typed-start-retry-with-new-id",
            },
        )
        self.assertTrue(started["created"])
        self.assertFalse(replay["created"])
        self.assertEqual(started["post"]["content"], "开始行动")
        self.assertEqual(replay["post"], started["post"])
        chronology = started["post"]["chronology"]
        self.assertEqual(
            chronology["afterPostId"],
            alignment_post["postId"],
        )
        self.assertRegex(
            chronology["orderKey"],
            r"^room-event:[0-9]{20}$",
        )
        start_user_event = retained_start_event
        self.assertEqual(
            start_user_event["sequence"],
            chronology["roomEventSequence"],
        )
        self.assertEqual(
            start_user_event["payload"]["afterPostId"],
            alignment_post["postId"],
        )
        reconnected_projection = type(self.service.room_kernel_projection)(
            self.service.db_path
        )
        reconnected_projection.initialize()
        reconnected_start_post = next(
            post
            for post in reconnected_projection.snapshot(self.room_id)["posts"]
            if post["postId"] == started["post"]["postId"]
        )
        self.assertEqual(reconnected_start_post["chronology"], chronology)
        self.assertEqual(started["intake"]["phase"], "executing")
        self.assertEqual(
            started["dispatch"]["dispatchId"],
            replay["dispatch"]["dispatchId"],
        )
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                """DELETE FROM agent_room_public_projection_receipts
                   WHERE projection_key=?""",
                (start_projection_key,),
            )
        with self.assertRaisesRegex(
            RoomKernelFenceError,
            "no durable public authorization",
        ):
            self.service.start_room_execution(
                self.room_id,
                {
                    **start_payload,
                    "clientActionId": "action:typed-start-unproven-legacy",
                },
            )


    def test_root_child_aggregate_blocks_manual_finalize(self) -> None:
        active_delegation = {
            "schemaVersion": "rag-ime.root-child-quiescence.v1",
            "owner": "delegation",
            "rootId": "root:service",
            "generation": 0,
            "dispatchId": "",
            "state": "pending",
            "quiescent": False,
            "pendingCount": 1,
            "unknownCount": 0,
            "counts": {"queued": 0, "running": 1, "cancelling": 0, "total": 1},
            "pendingTargets": [
                {
                    "targetKind": "delegationRun",
                    "targetId": "run:room-child",
                    "state": "running",
                    "rootId": "root:service",
                    "generation": 0,
                    "dispatchId": "dispatch:room-child",
                }
            ],
            "errors": [],
        }
        active_background = {
            **active_delegation,
            "owner": "backgroundJob",
            "counts": {"queued": 0, "running": 1, "cancelling": 0, "total": 1},
            "pendingTargets": [
                {
                    "targetKind": "backgroundJob",
                    "targetId": "bg:room-child",
                    "state": "running",
                    "rootId": "root:service",
                    "generation": 0,
                    "dispatchId": "dispatch:room-child",
                }
            ],
        }
        quiescent = {
            **active_delegation,
            "state": "quiescent",
            "quiescent": True,
            "pendingCount": 0,
            "counts": {"queued": 0, "running": 0, "cancelling": 0, "total": 0},
            "pendingTargets": [],
        }
        with patch.object(
            self.service.delegation,
            "root_child_quiescence",
            return_value=active_delegation,
        ), patch.object(
            self.service.background_jobs,
            "root_child_quiescence",
            return_value=active_background,
        ):
            with self.assertRaisesRegex(
                RoomKernelFenceError,
                "active or unknown causal children",
            ):
                self.service.finalize_room_kernel_root("root:service")

        with patch.object(
            self.service.delegation,
            "root_child_quiescence",
            return_value=quiescent,
        ), patch.object(
            self.service.background_jobs,
            "root_child_quiescence",
            return_value={
                **quiescent,
                "owner": "backgroundJob",
            },
        ):
            permitted = self.service.finalize_room_kernel_root("root:service")
        self.assertIn("receipt", permitted)
        self.assertTrue(permitted["childQuiescence"]["quiescent"])

    def test_root_cancel_fans_out_room_child_owners(self) -> None:
        delegation_receipt = {
            "schemaVersion": "rag-ime.root-child-cancellation.v1",
            "owner": "delegation",
            "requestId": "room-root-cancel:root:service:0",
            "rootId": "root:service",
            "generation": 0,
            "state": "terminated",
            "targetIds": ["run:room-child"],
            "pendingTargets": [],
        }
        background_receipt = {
            **delegation_receipt,
            "owner": "backgroundJob",
            "targetIds": ["bg:room-child"],
        }
        quiescent = {
            "schemaVersion": "rag-ime.root-child-quiescence.v1",
            "owner": "roomRoot",
            "rootId": "root:service",
            "generation": 0,
            "dispatchId": "",
            "state": "quiescent",
            "quiescent": True,
            "pendingCount": 0,
            "unknownCount": 0,
            "counts": {"queued": 0, "running": 0, "cancelling": 0, "total": 0},
            "pendingTargets": [],
            "errors": [],
        }
        with patch.object(
            self.service.delegation,
            "cancel_root_children",
            return_value=delegation_receipt,
        ), patch.object(
            self.service.background_jobs,
            "cancel_root_children",
            return_value=background_receipt,
        ), patch.object(
            self.service.delegation,
            "root_child_quiescence",
            return_value={**quiescent, "owner": "delegation"},
        ), patch.object(
            self.service.background_jobs,
            "root_child_quiescence",
            return_value={**quiescent, "owner": "backgroundJob"},
        ):
            result = self.service.room_kernel_application.cancel_root(
                self.room_id,
                "root:service",
            )
        self.assertEqual(result["status"], "terminated")
        self.assertEqual(
            result["childCancellation"]["targetIds"],
            ["run:room-child", "bg:room-child"],
        )

if __name__ == "__main__":
    unittest.main()
