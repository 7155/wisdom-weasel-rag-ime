from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.agent_service import AgentService


class _Runtime:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.default_model_profile = "pi/test"

    def runtime_status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "status": "ready",
            "capabilities": {"runtimePrimitives": {"roomTypes": True}},
        }

    def dispatch_room(
        self,
        payload: dict[str, object],
        *,
        message: str,
        lease_token: str,
    ) -> dict[str, object]:
        del message, lease_token
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
            "capabilityEpoch": payload["capabilityEpoch"],
            "sessionId": payload["targetSessionId"],
            "turnId": f"turn:{payload['dispatchId']}",
        }

    def cancel_room(self, **payload: object) -> dict[str, object]:
        return {"status": "applied", **payload}

    def stop(self) -> None:
        return None


class _RuntimeFactory:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"
    default_model_profile = "pi/test"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.runtime = _Runtime(root)

    def create(self, *_args: object, **_kwargs: object) -> _Runtime:
        return self.runtime

    def apply_policy(self, _policy: object) -> None:
        return None

    def reconfigure(self, _config: object) -> None:
        return None


class RoomSettleLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-settle-lifecycle-")
        root = Path(self.tmp.name)
        self.service = AgentService(
            db_path=root / "rag-ime.sqlite",
            runtime_factory=_RuntimeFactory(root),
            room_kernel_mode="cohort",
            room_kernel_poll_seconds=60,
        )
        self.service.room_kernel_worker_loop.close()
        room = self.service.create_room(
            {
                "title": "Settle lifecycle",
                "workspaceRoots": [str(root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        self.room_id = str(room["id"])
        self.target = room["participants"][0]
        self.owner = room["participants"][1]
        self.session_id = str(self.owner["sessionId"])
        self.now_ms = int(time.time() * 1000)
        self._seed_running_dispatch()

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def _seed_running_dispatch(self) -> None:
        self.service.room_kernel.create_root(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:settle",
                "roomId": self.room_id,
                "generation": 0,
                "state": "running",
                "owner": str(self.owner["id"]),
                "requirementAnchorRef": "requirement-anchor:settle@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "createdAtMs": self.now_ms,
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("criterion:settle",),
            now_ms=self.now_ms,
        )
        self.service.room_kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:settle",
                "rootId": "root:settle",
                "parentTaskId": None,
                "ownerParticipantId": str(self.owner["id"]),
                "assigneeParticipantId": str(self.owner["id"]),
                "objective": "Verify the governed settle lifecycle.",
                "expectedOutput": "A canonical Post and continuation.",
                "requirementItemIds": ["requirement:settle"],
                "acceptanceCriterionIds": ["criterion:settle"],
                "revision": 0,
                "state": "active",
            },
            now_ms=self.now_ms + 1,
        )
        self.service.room_kernel.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": "dispatch:settle",
                "rootId": "root:settle",
                "taskId": "task:settle",
                "parentDispatchId": None,
                "generation": 0,
                "hopCount": 0,
                "depth": 0,
                "budgetCost": 1,
                "targetSessionId": self.session_id,
                "targetParticipantId": str(self.owner["id"]),
                "triggerId": "trigger:settle",
                "intentKind": "execute",
                "idempotencyKey": "dispatch:settle",
                "attempt": 0,
                "capabilityEpoch": 7,
                "runtimeProfileRevision": "runtime-profile:settle-v1",
                "state": "pending",
            },
            now_ms=self.now_ms + 2,
        )
        self.service.room_kernel_worker.run_once()

    def _invoke_commit(
        self,
        decision: str,
        **extra: object,
    ) -> dict[str, object]:
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": f"load:commit:{decision}",
                "toolName": "room_commit",
                "createdAtMs": 10,
            }
        )["result"]
        result = self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": decision,
                "result": f"result:{decision}",
                "evidenceRefs": ["evidence:settle"],
                "requirementCoverage": ["criterion:settle"],
                **extra,
            },
            tool_call_id=f"call:commit:{decision}",
            load_receipt_id=str(loaded["receiptId"]),
        )
        assert result is not None
        return result

    def _invoke_post(self, content: str) -> dict[str, object]:
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:post",
                "toolName": "room_post",
                "createdAtMs": 9,
            }
        )["result"]
        result = self.service.execute_room_capability_tool(
            self.session_id,
            "room_post",
            {"content": content},
            tool_call_id="call:post",
            load_receipt_id=str(loaded["receiptId"]),
        )
        assert result is not None
        return result

    def _settle(self, attempt: int = 1) -> dict[str, object]:
        return self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": self.session_id,
                "dispatchId": "dispatch:settle",
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": 7,
                "settleScopeId": "scope:settle",
                "settleAttempt": attempt,
                "resourceUsage": {
                    "inputTokens": 120,
                    "outputTokens": 30,
                    "toolCalls": 1,
                    "toolCost": 1,
                    "retryCount": 0,
                    "repairCount": attempt - 1,
                },
            }
        )["result"]

    def test_deliver_creates_one_post_and_complete_continuation(self) -> None:
        self._invoke_commit("deliver")

        settled = self._settle()
        replay = self._settle()

        self.assertEqual(settled["state"], "committed")
        self.assertTrue(replay["replayed"])
        receipt = settled["settleResult"]["receipt"]
        commit_id = str(receipt["details"]["commitId"])
        self.assertEqual(
            self.service.room_kernel.continuation(commit_id)["decision"],
            "complete",
        )
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "committed",
        )
        root = self.service.room_kernel.root("root:settle")
        self.assertEqual(root["state"], "completed")
        self.assertTrue(root["terminalReceiptId"])
        posts = self.service.room_kernel_snapshot(self.room_id)["posts"]
        self.assertEqual([post["content"] for post in posts], ["result:deliver"])
        public_events = self.service.room_snapshot(self.room_id)["events"]
        terminal_events = [
            event
            for event in public_events
            if event["eventType"] == "turn_completed"
            and event["participantId"] is None
        ]
        self.assertEqual(len(terminal_events), 1)
        self.assertEqual(
            self.service.room_capabilities.runtime_binding(
                self.session_id,
                active_only=False,
            )["state"],
            "revoked",
        )

    def test_staged_room_post_is_the_single_published_body(self) -> None:
        staged = self._invoke_post("public evidence from room_post")
        self._invoke_commit("deliver")

        settled = self._settle()

        self.assertEqual(
            settled["settleResult"]["post"]["content"],
            "public evidence from room_post",
        )
        posts = self.service.room_kernel_snapshot(self.room_id)["posts"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["content"], "public evidence from room_post")
        invocation_id = str(staged["invocationReceipt"]["receiptId"])
        self.assertEqual(
            self.service.room_capabilities.execution_receipt(invocation_id)["status"],
            "applied",
        )

    def test_handoff_creates_one_bounded_child_dispatch(self) -> None:
        self._invoke_commit(
            "handoff",
            targetParticipantId=str(self.target["id"]),
            nextTask="独立复核证据并回传结论",
            nextIntentKind="review",
        )

        settled = self._settle()

        receipt = settled["settleResult"]["receipt"]
        child_task_id = str(receipt["details"]["childTaskId"])
        child_id = str(receipt["details"]["childDispatchId"])
        child_task = self.service.room_kernel.task(child_task_id)
        child = self.service.room_kernel.dispatch(child_id)
        self.assertNotEqual(child_task_id, "task:settle")
        self.assertEqual(child_task["parentTaskId"], "task:settle")
        self.assertEqual(child_task["objective"], "独立复核证据并回传结论")
        self.assertEqual(child_task["assigneeParticipantId"], self.target["id"])
        self.assertEqual(child["taskId"], child_task_id)
        self.assertEqual(child["parentDispatchId"], "dispatch:settle")
        self.assertEqual(child["targetParticipantId"], self.target["id"])
        self.assertEqual(child["targetSessionId"], self.target["sessionId"])
        self.assertEqual(child["hopCount"], 1)
        self.assertEqual(child["intentKind"], "review")
        self.assertEqual(child["capabilityEpoch"], 8)
        self.assertEqual(child["state"], "pending")
        self.assertEqual(
            self.service.room_kernel.task("task:settle")["state"],
            "completed",
        )
        self.assertEqual(
            self.service.room_kernel.continuation(
                str(receipt["details"]["commitId"])
            )["decision"],
            "dispatch",
        )
        skill_id = "room-independent-vision-review"
        pinned, created = self.service.room_skill_receipts.pin_skill(
            receipt_id="skill:handoff-child",
            root_id="root:settle",
            task_id=child_task_id,
            dispatch_id=child_id,
            session_id=str(self.target["sessionId"]),
            skill_id=skill_id,
            skill_hash=self.service.room_skill_policy.skill_hash(skill_id),
            catalog_revision="c" * 64,
            load_reason="stage_required",
            capability_epoch=8,
            idempotency_key=f"{child_id}/review",
            created_at_ms=self.now_ms + 20,
        )
        self.assertTrue(created)
        self.assertEqual(pinned["capabilityEpoch"], 8)

    def test_wait_decision_moves_root_and_task_to_waiting(self) -> None:
        self._invoke_commit("wait")

        settled = self._settle()

        self.assertEqual(settled["state"], "committed")
        self.assertEqual(
            self.service.room_kernel.root("root:settle")["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel_snapshot(self.room_id)["posts"][0]["kind"],
            "wait",
        )

    def test_blocked_decision_moves_root_and_task_to_blocked(self) -> None:
        self._invoke_commit("blocked")

        settled = self._settle()

        self.assertEqual(settled["state"], "committed")
        self.assertEqual(
            self.service.room_kernel.root("root:settle")["state"],
            "blocked",
        )
        self.assertEqual(
            self.service.room_kernel_snapshot(self.room_id)["posts"][0]["kind"],
            "blocked",
        )

    def test_missing_commit_continues_twice_then_blocks_and_replays_exact_attempt(self) -> None:
        first = self._settle(1)
        first_replay = self._settle(1)
        second = self._settle(2)
        third = self._settle(3)
        third_replay = self._settle(3)

        self.assertEqual(first["state"], "continue")
        self.assertIn(
            '<managed-task-follow-up origin="room-kernel" kind="continue">',
            first["message"],
        )
        self.assertIn("不是用户提出了新需求", first["message"])
        self.assertIn("一次模型回答结束不等于任务完成", first["message"])
        self.assertIn("能够产生新证据", first["message"])
        self.assertIn(
            "若没有这种合法新动作，立即选择 handoff、wait 或 blocked",
            first["message"],
        )
        self.assertIn("建议接手的参与者或模型能力", first["message"])
        self.assertIn("只向用户提出一个最小必要问题", first["message"])
        self.assertIn("续作次数是硬预算", first["message"])
        self.assertIn("不得重复同一失败动作", first["message"])
        self.assertTrue(first["followUpKey"])
        self.assertEqual(first_replay["guardReceipt"], first["guardReceipt"])
        self.assertEqual(second["guardReceipt"]["details"]["attempt"], 2)
        self.assertEqual(third["state"], "blocked")
        self.assertEqual(third_replay["guardReceipt"], third["guardReceipt"])
        self.assertEqual(third["guardReceipt"]["details"]["attempt"], 3)
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "failed",
        )
        self.assertEqual(
            self.service.room_kernel.outbox("dispatch:settle")["state"],
            "dead_letter",
        )
        self.assertEqual(
            self.service.room_kernel.lease("dispatch:settle")["state"],
            "completed",
        )

    def test_deliver_cannot_forge_acceptance_coverage(self) -> None:
        self._invoke_commit(
            "deliver",
            requirementCoverage=["criterion:not-owned-by-this-task"],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertTrue(settled["followUpKey"])
        self.assertIn("outside the current Task", settled["reason"])
        self.assertIn(
            'acceptanceCriterionIds=["criterion:settle"]',
            settled["message"],
        )
        self.assertIn('kind="repair_commit"', settled["message"])
        self.assertIn("不得填写 requirementItemIds", settled["message"])
        self.assertIn(
            "若当前模型无法完成且没有合法新动作",
            settled["message"],
        )
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "running",
        )
        self.assertEqual(self.service.room_kernel_snapshot(self.room_id)["posts"], [])


if __name__ == "__main__":
    unittest.main()
