from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rag_ime import agent_room_settlement as settlement
from rag_ime.agent_definitions import collaboration_role
from rag_ime.agent_room_settlement import (
    RoomCommitProposalError,
    RoomSettleLifecycleService,
)
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.agent_room_quality_gate import (
    RoomQualityGateError,
    canonicalize_quality_gate,
)
from rag_ime.agent_room_references import (
    participant_ref_map,
    ref_for_participant,
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
                "facilitatorParticipantId": str(self.owner["id"]),
                "reporterParticipantId": None,
                "reporterSelectionReceiptId": None,
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
                "taskKind": "work",
                "currentOwnerParticipantId": str(self.owner["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
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
        self.service.room_requirements.append_anchor(
            anchor_id="requirement-anchor:settle",
            root_id="root:settle",
            original_content="完成受管 Room 任务并以证据通过验收。",
            created_by="user:local",
            provenance={"roomEventId": "event:settle"},
            created_at_ms=self.now_ms,
        )
        self.service.room_requirements.revise_catalog(
            catalog_revision_id="catalog:settle",
            root_id="root:settle",
            expected_current_revision=0,
            anchor_refs=("requirement-anchor:settle",),
            items=(
                {
                    "itemId": "requirement:settle",
                    "kind": "explicit_user_requirement",
                    "statement": "完成受管 Room 任务",
                    "origin": "derived_catalog",
                    "state": "active",
                    "sourceSpans": [
                        {
                            "anchorId": "requirement-anchor:settle",
                            "startByte": 0,
                            "endByte": len(
                                "完成受管 Room 任务并以证据通过验收。".encode()
                            ),
                        }
                    ],
                    "supersedes": [],
                    "ambiguity": "",
                    "confirmation": "user-confirmed",
                },
            ),
            acceptance_criteria=(
                {
                    "criterionId": "criterion:settle",
                    "itemId": "requirement:settle",
                    "acceptanceCriterionFullNameZh": "受管任务验收标准",
                    "criterionKind": "requirement",
                    "expectedReceiptTypes": ["test"],
                    "statement": "受管任务测试通过",
                },
            ),
            change_reason="测试冻结的验收目录",
            provenance={
                "derivedFrom": ["requirement-anchor:settle"],
                "notOriginalText": True,
            },
            created_by="agent:requirements",
            created_at_ms=self.now_ms + 1,
        )
        self.service.room_requirements.record_verification_receipt(
            {
                "schemaVersion": "wisdom-weasel.typed-verification-receipt.v1",
                "receiptId": "evidence:settle",
                "rootId": "root:settle",
                "catalogRevisionId": "catalog:settle",
                "receiptType": "test",
                "sourceCommit": "commit:settle",
                "environment": "local-test",
                "commandOrAction": "python -m unittest",
                "exitStatus": 0,
                "outputHash": "a" * 64,
                "artifactHash": "b" * 64,
                "verifier": "managed-test-runner",
                "createdAtMs": self.now_ms + 2,
            }
        )
        self.service.room_requirements.link_proof(
            proof_id="proof:settle",
            root_id="root:settle",
            catalog_revision_id="catalog:settle",
            criterion_id="criterion:settle",
            receipt_id="evidence:settle",
            linked_by="managed-test-runner",
            created_at_ms=self.now_ms + 2,
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
        evidence = extra.pop(
            "evidence",
            (
                [{"acceptance": "AC-1", "refs": ["evidence:settle"]}]
                if decision in {"deliver", "handoff"}
                else []
            ),
        )
        decision_fields: dict[str, object] = {}
        if decision == "wait":
            decision_fields = {
                "waitingFor": "external",
                "resumeCondition": "外部依赖恢复",
            }
        elif decision == "blocked":
            decision_fields = {
                "blocker": "当前环境无法继续",
                "attemptedAlternatives": ["已验证本地替代方案"],
                "unlockCondition": "提供可用环境",
            }
        public_summaries = {
            "deliver": "检查与验证均已完成，结果可以交付；当前没有已知残余风险。",
            "handoff": "当前阶段已经完成，现转交另一位伙伴独立复核后再给出结论。",
            "wait": "当前仍在等待外部依赖恢复；收到信号后会继续处理。",
            "blocked": "当前工作受环境条件阻塞；已说明尝试过的方法和恢复条件。",
        }
        result = self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": decision,
                "summary": f"result:{decision}",
                "publicSummary": public_summaries[decision],
                "evidence": evidence,
                "residualRisks": (
                    []
                    if decision == "deliver"
                    else [f"lifecycle_exit:{decision}"]
                ),
                **decision_fields,
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
            {"kind": "progress", "content": content},
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
                "runtimeTurnId": "turn:dispatch:settle",
                "dispatchAttempt": 0,
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
        posts = self.service.room_context_ledger.recent_posts(
            "root:settle",
            limit=10,
        )
        self.assertEqual(
            [post["content"] for post in posts],
            ["检查与验证均已完成，结果可以交付；当前没有已知残余风险。"],
        )
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
        self.assertEqual(
            receipt["details"]["qualityGateVerdict"],
            "ready_to_deliver",
        )
        self.assertTrue(receipt["details"]["qualityGateReceiptId"])

    def test_room_post_is_immediate_and_commit_publishes_final_summary(self) -> None:
        published = self._invoke_post("public evidence from room_post")
        self._invoke_commit("deliver")

        settled = self._settle()

        self.assertEqual(
            settled["settleResult"]["post"]["content"],
            "检查与验证均已完成，结果可以交付；当前没有已知残余风险。",
        )
        posts = self.service.room_context_ledger.recent_posts(
            "root:settle",
            limit=10,
        )
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["content"], "public evidence from room_post")
        self.assertEqual(
            posts[1]["content"],
            "检查与验证均已完成，结果可以交付；当前没有已知残余风险。",
        )
        invocation_id = str(published["invocationReceipt"]["receiptId"])
        self.assertEqual(
            self.service.room_capabilities.execution_receipt(invocation_id)["status"],
            "applied",
        )

    def test_handoff_transfers_one_task_and_enqueues_one_dispatch(self) -> None:
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P1",
            intent="review",
            nextTask="独立复核证据并回传结论",
            expectedOutput="公开复核结论与证据",
            acceptanceAliases=["AC-1"],
        )

        settled = self._settle()
        self.assertEqual(
            settled["settleResult"]["post"]["content"],
            "当前阶段已经完成，现转交另一位伙伴独立复核后再给出结论。",
        )
        self.assertNotIn(
            "独立复核证据并回传结论",
            settled["settleResult"]["post"]["content"],
        )

        receipt = settled["settleResult"]["receipt"]
        transferred_task_id = str(receipt["details"]["transferredTaskId"])
        child_id = str(receipt["details"]["childDispatchId"])
        transferred_task = self.service.room_kernel.task(transferred_task_id)
        child = self.service.room_kernel.dispatch(child_id)
        self.assertEqual(transferred_task_id, "task:settle")
        self.assertIsNone(transferred_task["parentTaskId"])
        self.assertEqual(
            transferred_task["objective"],
            "独立复核证据并回传结论",
        )
        self.assertEqual(
            transferred_task["currentOwnerParticipantId"],
            self.target["id"],
        )
        self.assertEqual(transferred_task["ownershipRevision"], 1)
        self.assertEqual(
            transferred_task["ownershipReceiptId"],
            receipt["details"]["ownershipReceiptId"],
        )
        self.assertEqual(child["taskId"], transferred_task_id)
        self.assertEqual(child["parentDispatchId"], "dispatch:settle")
        self.assertEqual(child["targetParticipantId"], self.target["id"])
        self.assertEqual(child["targetSessionId"], self.target["sessionId"])
        self.assertEqual(child["hopCount"], 1)
        self.assertEqual(child["intentKind"], "review")
        self.assertEqual(child["capabilityEpoch"], 8)
        self.assertEqual(child["state"], "pending")
        self.assertEqual(
            transferred_task["contextEvidenceRefs"],
            ["evidence:settle"],
        )
        self.assertEqual(transferred_task["state"], "active")
        self.assertEqual(
            self.service.room_kernel.counts("root:settle")["tasks"],
            1,
        )
        self.assertEqual(
            self.service.room_kernel.continuation(
                str(receipt["details"]["commitId"])
            )["decision"],
            "dispatch",
        )
        skill_id = "independent-review"
        pinned, created = self.service.room_skill_receipts.pin_skill(
            receipt_id="skill:handoff-child",
            root_id="root:settle",
            task_id=transferred_task_id,
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

        self.service.room_kernel_worker.run_once()
        loaded_state = self.service.room_capability_tool_load(
            {
                "sessionId": str(self.target["sessionId"]),
                "receiptId": "load:handoff-child-state",
                "toolName": "room_state",
                "createdAtMs": self.now_ms + 21,
            }
        )["result"]
        state = self.service.execute_room_capability_tool(
            str(self.target["sessionId"]),
            "room_state",
            {},
            tool_call_id="call:handoff-child-state",
            load_receipt_id=str(loaded_state["receiptId"]),
        )["result"]
        self.assertEqual(
            state["acceptanceAliases"],
            [
                {
                    "acceptance": "AC-1",
                    "statement": "受管任务测试通过",
                    "verified": True,
                    "evidenceRefs": ["evidence:settle"],
                }
            ],
        )

        loaded_commit = self.service.room_capability_tool_load(
            {
                "sessionId": str(self.target["sessionId"]),
                "receiptId": "load:handoff-child-commit",
                "toolName": "room_commit",
                "createdAtMs": self.now_ms + 22,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            str(self.target["sessionId"]),
            "room_commit",
            {
                "decision": "deliver",
                "summary": "独立复核完成",
                "publicSummary": "独立复核已经完成，相关检查通过。",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": ["evidence:settle"],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:handoff-child-commit",
            load_receipt_id=str(loaded_commit["receiptId"]),
        )
        child_settled = self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": str(self.target["sessionId"]),
                "dispatchId": child_id,
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": 8,
                "runtimeTurnId": f"turn:{child_id}",
                "dispatchAttempt": 0,
                "settleScopeId": "scope:handoff-child",
                "settleAttempt": 1,
                "resourceUsage": {
                    "inputTokens": 80,
                    "outputTokens": 20,
                    "toolCalls": 2,
                    "toolCost": 2,
                    "retryCount": 0,
                    "repairCount": 0,
                },
            }
        )["result"]
        self.assertEqual(child_settled["state"], "committed")
        self.assertEqual(
            self.service.room_kernel.root("root:settle")["state"],
            "completed",
        )

    def test_wait_decision_moves_root_and_task_to_waiting(self) -> None:
        self._invoke_commit(
            "wait",
            waitingFor="user",
            resumeCondition="用户提供自由文本澄清",
            question="请补充必要信息。",
        )

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
        commit_id = str(
            settled["settleResult"]["receipt"]["details"]["commitId"]
        )
        continuation = self.service.room_kernel.continuation(commit_id)[
            "payload"
        ]
        self.assertNotIn("questionOptions", continuation)
        self.assertEqual(continuation["question"], "请补充必要信息。")
        self.assertNotIn(
            "question",
            self.service.room_kernel_snapshot(self.room_id)["posts"][0],
        )

    def test_user_wait_canonicalizes_structured_question_into_post_and_continuation(
        self,
    ) -> None:
        options = [
            {
                "value": "  safe  ",
                "label": "  稳妥   方案 ",
                "description": " 保留   当前边界 ",
                "recommended": True,
            },
            {
                "value": "fast",
                "label": "快速方案",
                "recommended": False,
            },
        ]
        normalized = [
            {
                "value": "safe",
                "label": "稳妥 方案",
                "description": "保留 当前边界",
                "recommended": True,
            },
            {
                "value": "fast",
                "label": "快速方案",
                "recommended": False,
            },
        ]
        self._invoke_commit(
            "wait",
            waitingFor="user",
            resumeCondition="用户选择一个方案",
            question="采用哪个方案？",
            questionOptions=options,
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "committed")
        commit_id = str(
            settled["settleResult"]["receipt"]["details"]["commitId"]
        )
        continuation = self.service.room_kernel.continuation(commit_id)[
            "payload"
        ]
        self.assertEqual(continuation["question"], "采用哪个方案？")
        self.assertEqual(continuation["questionOptions"], normalized)
        post = self.service.room_kernel_snapshot(self.room_id)["posts"][0]
        self.assertEqual(
            post["question"],
            {
                "prompt": "采用哪个方案？",
                "options": normalized,
            },
        )

    def test_structured_question_validator_fails_closed(self) -> None:
        options = [
            {"value": "safe", "label": "稳妥方案"},
            {"value": "fast", "label": "快速方案"},
        ]
        cases = (
            {
                "value": options,
                "decision": "deliver",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "message": "wait-for-user",
            },
            {
                "value": options,
                "decision": "wait",
                "waiting_for": "external",
                "question": "采用哪个方案？",
                "message": "wait-for-user",
            },
            {
                "value": options[:1],
                "decision": "wait",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "message": "between 2 and 5",
            },
            {
                "value": [*options, *options, *options],
                "decision": "wait",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "message": "between 2 and 5",
            },
            {
                "value": [
                    options[0],
                    {"value": " safe ", "label": "重复方案"},
                ],
                "decision": "wait",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "message": "unique after normalization",
            },
            {
                "value": [
                    {**options[0], "recommended": True},
                    {**options[1], "recommended": True},
                ],
                "decision": "wait",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "message": "at most one recommended",
            },
        )
        for case in cases:
            with self.assertRaisesRegex(
                RoomCommitProposalError,
                str(case["message"]),
            ):
                settlement._canonical_question_options(
                    case["value"],
                    decision=str(case["decision"]),
                    waiting_for=str(case["waiting_for"]),
                    question=case["question"],
                )

    def test_terminal_public_summary_rejects_internal_protocol_fields(self) -> None:
        self._invoke_commit(
            "deliver",
            publicSummary=(
                "工作已完成；内部 rootId 为 root:settle，"
                "evidenceRef 为 evidence:settle。"
            ),
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("must be rewritten for users", settled["reason"])


    def test_repair_commit_allows_one_follow_up_then_blocks(self) -> None:
        self._invoke_commit(
            "deliver",
            publicSummary=(
                "工作已完成；内部 rootId 为 root:settle，"
                "evidenceRef 为 evidence:settle。"
            ),
        )

        first = self._settle(1)
        replay = self._settle(1)
        blocked = self._settle(2)

        self.assertEqual(first["state"], "repair_commit")
        self.assertTrue(first["followUpKey"])
        self.assertEqual(replay["guardReceipt"], first["guardReceipt"])
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["guardReceipt"]["details"]["attempt"], 2)
        self.assertEqual(
            blocked["guardReceipt"]["details"]["maxAttempts"],
            2,
        )
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "failed",
        )

    def test_wait_public_summary_cannot_claim_unverified_success(self) -> None:
        self._invoke_commit(
            "wait",
            publicSummary="测试全部通过，只需等待部署窗口。",
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("authoritative evidence", settled["reason"])

    def test_participant_wait_binds_one_exact_dispatch(self) -> None:
        target_task_id = "task:participant-wait-target"
        target_dispatch_id = "dispatch:participant-wait-target"
        self.service.room_kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": target_task_id,
                "rootId": "root:settle",
                "parentTaskId": "task:settle",
                "taskKind": "review",
                "currentOwnerParticipantId": str(self.target["id"]),
                "ownershipRevision": 0,
                "ownershipReceiptId": None,
                "invitationId": None,
                "reviewState": "required",
                "reviewOfTaskIds": ["task:settle"],
                "reviewAuthorParticipantIds": [],
                "contextEvidenceRefs": [],
                "objective": "Publish one independent review.",
                "expectedOutput": "A public review result.",
                "requirementItemIds": ["requirement:settle"],
                "acceptanceCriterionIds": ["criterion:settle"],
                "revision": 0,
                "state": "active",
            },
            now_ms=self.now_ms + 3,
        )
        self.service.room_kernel.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": target_dispatch_id,
                "rootId": "root:settle",
                "taskId": target_task_id,
                "parentDispatchId": "dispatch:settle",
                "generation": 0,
                "hopCount": 1,
                "depth": 1,
                "budgetCost": 1,
                "targetSessionId": str(self.target["sessionId"]),
                "targetParticipantId": str(self.target["id"]),
                "triggerId": "trigger:participant-wait-target",
                "intentKind": "review",
                "idempotencyKey": target_dispatch_id,
                "attempt": 0,
                "capabilityEpoch": 7,
                "runtimeProfileRevision": "runtime-profile:settle-v1",
                "state": "pending",
            },
            now_ms=self.now_ms + 4,
        )
        self.service.room_kernel_worker.clock_ms = lambda: self.now_ms + 5
        peer_dispatch = self.service.room_kernel_worker.run_once()
        self.assertIsNotNone(peer_dispatch)
        self.assertEqual(
            self.service.room_kernel.dispatch(target_dispatch_id)["state"],
            "running",
        )
        refs = participant_ref_map(
            self.service.rooms.get(self.room_id)["participants"]
        )
        target_ref = ref_for_participant(self.target["id"], refs)
        self.assertIsNotNone(target_ref)
        self._invoke_commit(
            "wait",
            waitingFor="participant",
            waitingForParticipantRef=target_ref,
            resumeCondition="独立复核结果已公开",
        )

        settled = self._settle()

        commit_id = str(
            settled["settleResult"]["receipt"]["details"]["commitId"]
        )
        continuation = self.service.room_kernel.continuation(commit_id)
        self.assertEqual(
            continuation["payload"]["waitingForParticipantId"],
            self.target["id"],
        )
        self.assertEqual(
            continuation["payload"]["waitingForDispatchId"],
            target_dispatch_id,
        )

    def test_commit_wakes_worker_after_public_projection(self) -> None:
        order: list[str] = []
        original_publish = self.service.room_context_ledger.publish_post
        original_sync = self.service.room_kernel_projection.sync_room

        def publish(post: dict[str, object]):
            order.append("post")
            return original_publish(post)

        def sync(room_id: str, **kwargs: object):
            order.append("projection")
            return original_sync(room_id, **kwargs)

        self.service.room_kernel_application.context.publish_post = publish
        self.service.room_kernel_application.projection.sync_room = sync
        self.service.room_kernel_application.wake_worker = (
            lambda: order.append("wake")
        )
        self._invoke_commit("deliver")

        self._settle()

        self.assertLess(order.index("post"), order.index("projection"))
        self.assertLess(order.index("projection"), order.index("wake"))

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
        self.assertIn(
            "waitingFor=user 时才向用户提出一个最小必要问题",
            first["message"],
        )
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
            evidence=[
                {
                    "acceptance": "AC-9",
                    "refs": ["evidence:settle"],
                }
            ],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertTrue(settled["followUpKey"])
        self.assertIn("outside the current Task", settled["reason"])
        self.assertIn('["AC-1"]', settled["message"])
        self.assertIn('kind="repair_commit"', settled["message"])
        self.assertIn("不要填写数据库 criterionId", settled["message"])
        self.assertIn("不要自报 pass 或 verdict", settled["message"])
        self.assertIn(
            "若当前模型无法完成且没有合法新动作",
            settled["message"],
        )
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "running",
        )
        self.assertEqual(self.service.room_kernel_snapshot(self.room_id)["posts"], [])

    def test_tool_boundary_rejects_missing_structured_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence"):
            self._invoke_commit("deliver", evidence=None)

    def test_quality_gate_pass_requires_fresh_committed_evidence(self) -> None:
        self._invoke_commit(
            "deliver",
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": ["evidence:not-committed"],
                }
            ],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("non-authoritative refs for AC-1", settled["reason"])
        self.assertIn("byte-for-byte evidenceRefs", settled["reason"])

    def test_non_passing_quality_gate_cannot_deliver(self) -> None:
        self._invoke_commit(
            "deliver",
            evidence=[],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("every AC", settled["reason"])


class RoomQualityGateDiagnosticTests(unittest.TestCase):
    def test_unknown_refs_report_every_affected_acceptance_alias(self) -> None:
        criteria = ("criterion:one", "criterion:two", "criterion:three")
        with self.assertRaises(RoomQualityGateError) as raised:
            canonicalize_quality_gate(
                evidence_proposal=[
                    {
                        "acceptance": "AC-1",
                        "refs": ["evidence:valid:one"],
                    },
                    {
                        "acceptance": "AC-2",
                        "refs": ["evidence:mistyped:two"],
                    },
                    {
                        "acceptance": "AC-3",
                        "refs": ["evidence:mistyped:three"],
                    },
                ],
                residual_risks=[],
                decision="deliver",
                root_id="root:diagnostic",
                task_id="task:diagnostic",
                dispatch_id="dispatch:diagnostic",
                generation=0,
                task_criteria=criteria,
                acceptance_aliases={
                    "AC-1": criteria[0],
                    "AC-2": criteria[1],
                    "AC-3": criteria[2],
                },
                requirement_context={
                    "originalRequirements": ["完成三个验收条件"],
                    "catalog": {
                        "acceptanceCriteria": [
                            {
                                "criterionId": criteria[0],
                                "proofs": [
                                    {
                                        "receiptId": "evidence:valid:one",
                                        "exitStatus": 0,
                                    }
                                ],
                            },
                            {"criterionId": criteria[1], "proofs": []},
                            {"criterionId": criteria[2], "proofs": []},
                        ]
                    },
                },
                accepted_evidence_by_criterion={},
                runtime_evidence_refs=[],
                invocation_receipt_id="invoke:diagnostic",
                now_ms=100,
            )

        message = str(raised.exception)
        self.assertNotIn("AC-1", message)
        self.assertIn("AC-2, AC-3", message)
        self.assertIn("latest room_state", message)
        self.assertNotIn("evidence:mistyped", message)


class RoleCommitDecisionFenceTests(unittest.TestCase):
    """`allowedCommitDecisions` must be a fence, not catalog prose.

    Every builtin role currently permits all four lifecycle exits, so this
    exercises the fence with a deliberately narrowed role: the point is that a
    narrower declaration is enforced rather than silently ignored.
    """

    def _service(self, role: object) -> RoomSettleLifecycleService:
        service = RoomSettleLifecycleService.__new__(RoomSettleLifecycleService)
        service.rooms = _StubRooms(role_id="reviewer")
        return service

    def test_declared_exit_is_allowed_and_undeclared_exit_is_refused(self) -> None:
        narrowed = replace(
            collaboration_role("reviewer"),
            allowed_commit_decisions=("handoff", "blocked"),
        )
        service = self._service(narrowed)
        dispatch = {"targetParticipantId": "participant:reviewer"}

        with patch.object(settlement, "collaboration_role", return_value=narrowed):
            service._assert_decision_allowed("handoff", dispatch)
            with self.assertRaises(RoomCommitProposalError) as raised:
                service._assert_decision_allowed("deliver", dispatch)

        self.assertIn("deliver", str(raised.exception))
        self.assertIn("handoff", str(raised.exception))

    def test_unknown_participant_or_role_does_not_block_settlement(self) -> None:
        # The fence narrows behaviour; it must never become a new way for a
        # Dispatch to get stuck with no lifecycle exit at all.
        service = RoomSettleLifecycleService.__new__(RoomSettleLifecycleService)
        service.rooms = _StubRooms(role_id=None, missing=True)

        service._assert_decision_allowed("deliver", {"targetParticipantId": "gone"})
        service._assert_decision_allowed("deliver", {})

    def test_every_builtin_role_still_permits_all_four_exits(self) -> None:
        service = RoomSettleLifecycleService.__new__(RoomSettleLifecycleService)
        for role_id in ("coordinator", "researcher", "implementer", "reviewer", "specialist"):
            service.rooms = _StubRooms(role_id=role_id)
            for decision in ("deliver", "handoff", "wait", "blocked"):
                with self.subTest(role=role_id, decision=decision):
                    service._assert_decision_allowed(
                        decision, {"targetParticipantId": f"participant:{role_id}"}
                    )


class _StubRooms:
    def __init__(self, *, role_id: str | None, missing: bool = False) -> None:
        self.role_id = role_id
        self.missing = missing

    def participant(self, participant_id: str) -> dict[str, object]:
        if self.missing:
            raise KeyError(participant_id)
        return {"id": participant_id, "collaborationRole": self.role_id}


if __name__ == "__main__":
    unittest.main()
