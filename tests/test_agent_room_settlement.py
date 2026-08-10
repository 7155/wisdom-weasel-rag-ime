from __future__ import annotations

import json
import sqlite3
import subprocess
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
from rag_ime.agent_room_kernel import RoomKernelFenceError
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
from rag_ime.agent_room_skills import RoomSkillPolicy


class _Runtime:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.default_model_profile = "pi/test"
        policy_root = Path(__file__).resolve().parents[1] / "integrations" / "pi"
        self.skill_policy = RoomSkillPolicy(
            policy_root / "room-skill-policy.json",
            policy_root / "skills",
        )

    def runtime_status(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "managed": True,
            "status": "ready",
            "piVersion": "test",
            "idleTimeoutSeconds": 0,
            "capabilities": {"runtimePrimitives": {"roomTypes": True}},
        }

    def dispatch_room(
        self,
        payload: dict[str, object],
        *,
        message: str,
        lease_token: str,
        record_intent,
    ) -> dict[str, object]:
        del message, lease_token
        record_intent()
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
        }.get(str(payload.get("intentKind") or ""), "implementation")
        skill_id = str(self.skill_policy.select_stage(stage)["skillId"])
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
            "roomSkillLoad": {
                "name": skill_id,
                "contentRevision": self.skill_policy.skill_hash(skill_id),
                "catalogRevision": "0" * 64,
            },
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
        self.workspace_root = root / "workspace"
        self.workspace_root.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "room-tests@example.invalid")
        self._git("config", "user.name", "Room Tests")
        (self.workspace_root / "README.md").write_text("Room\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-qm", "initial")
        self.service = AgentService(
            db_path=root / "rag-ime.sqlite",
            runtime_factory=_RuntimeFactory(root),
            room_kernel_mode="cohort",
            room_kernel_poll_seconds=60,
        )
        self.service.room_kernel_worker_loop.close()
        self.service.bind_tool_manifest_provider(
            lambda _session: [
                {
                    "name": "workspace_read",
                    "description": "读取当前受管工作区",
                    "when": ["需要核对当前工作区内容"],
                    "notFor": ["不需要读取工作区时"],
                    "input": "受管路径",
                    "output": "读取结果",
                    "does": "只读取受管工作区",
                    "risk": "R0",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                }
            ]
        )
        room = self.service.create_room(
            {
                "title": "Settle lifecycle",
                "workspaceRoots": [str(self.workspace_root)],
                "participants": [
                    {
                        "roleId": "companion-present-v1",
                        "roleVersion": "1",
                        "collaborationRole": "reviewer",
                    },
                    {
                        "roleId": "companion-firstlight-v1",
                        "roleVersion": "1",
                        "collaborationRole": "coordinator",
                    },
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

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.workspace_root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _seed_running_dispatch(self) -> None:
        # Settlement tests exercise the typed Kernel lifecycle directly, not
        # product intake. Seed the explicit legacy shape without an
        # authoritative intake receipt; product Roots must use room_define.
        legacy_mode = patch.object(self.service.room_kernel, "mode", "test")
        legacy_mode.start()
        self.service.room_kernel.create_root(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:settle",
                "roomId": self.room_id,
                "generation": 0,
                "state": "running",
                "facilitatorParticipantId": str(self.owner["id"]),
                "reporterParticipantId": str(self.owner["id"]),
                "reporterSelectionReceiptId": None,
                "requirementAnchorRef": "requirement-anchor:settle@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "independentReviewRequired": False,
                "createdAtMs": self.now_ms,
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("criterion:settle",),
            now_ms=self.now_ms,
        )
        legacy_mode.stop()
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
            now_ms=self.now_ms,
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

    def _seed_workspace_retry(self) -> tuple[str, str]:
        task_id = "task:workspace-retry-wait-target"
        dispatch_id = "dispatch:workspace-retry-wait-target"
        parent_task = self.service.room_kernel.task("task:settle")
        self.service.room_kernel.create_task(
            {
                **parent_task,
                "taskId": task_id,
                "parentTaskId": "task:settle",
                "taskKind": "work",
                "currentOwnerParticipantId": str(self.target["id"]),
                "ownershipRevision": 1,
                "ownershipReceiptId": None,
                "reviewState": "not_required",
                "reviewOfTaskIds": [],
                "reviewAuthorParticipantIds": [],
                "objective": "Retry one retained isolated implementation.",
                "expectedOutput": "A delivered retry result.",
                "workspacePolicy": "isolated_writable",
                "workspaceRoot": str(self.workspace_root / "retry-child"),
                "workspaceBindingId": "binding:workspace-retry-wait-target",
                "workspaceLifecycleState": "retry_bound",
                "workspaceCleanupState": "not_authorized",
                "workspaceAttentionRequired": False,
                "workspaceTerminalReason": "",
                "workspaceIntegrationState": "pending",
                "revision": int(parent_task.get("revision") or 0) + 1,
                "state": "active",
            },
            now_ms=self.now_ms + 3,
        )
        self.service.room_kernel.enqueue_dispatch(
            {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": dispatch_id,
                "rootId": "root:settle",
                "taskId": task_id,
                "parentDispatchId": "dispatch:settle",
                "generation": 0,
                "hopCount": 1,
                "depth": 1,
                "budgetCost": 1,
                "targetSessionId": str(self.target["sessionId"]),
                "targetParticipantId": str(self.target["id"]),
                "triggerId": "invoke:workspace-retry-wait-target",
                "intentKind": "retry",
                "idempotencyKey": dispatch_id,
                "attempt": 0,
                "capabilityEpoch": 7,
                "runtimeProfileRevision": "runtime-profile:settle-v1",
                "state": "pending",
            },
            now_ms=self.now_ms + 4,
        )
        return task_id, dispatch_id

    def _pin_independent_review(
        self,
        *,
        dispatch_id: str,
        session_id: str,
        suffix: str,
    ) -> None:
        dispatch = self.service.room_kernel.dispatch(dispatch_id)
        skill_id = "independent-review"
        self.service.room_skill_receipts.pin_skill(
            receipt_id=f"skill:{suffix}",
            root_id="root:settle",
            task_id=str(dispatch["taskId"]),
            dispatch_id=dispatch_id,
            session_id=session_id,
            skill_id=skill_id,
            skill_hash=self.service.room_skill_policy.skill_hash(skill_id),
            catalog_revision="d" * 64,
            load_reason="stage_required",
            capability_epoch=int(dispatch["capabilityEpoch"]),
            idempotency_key=f"{dispatch_id}/review",
            created_at_ms=self.now_ms + 20,
        )

    def _commit_and_settle_dispatch(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        decision: str,
        suffix: str,
        evidence_ref: str,
        **extra: object,
    ) -> dict[str, object]:
        dispatch = self.service.room_kernel.dispatch(dispatch_id)
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": f"load:{suffix}",
                "toolName": "room_commit",
                "createdAtMs": self.now_ms + 30,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            session_id,
            "room_commit",
            {
                "decision": decision,
                "summary": f"settlement:{suffix}",
                "publicSummary": (
                    "独立复核发现问题，现按证据交回主持者修正。"
                    if decision == "handoff"
                    else "当前阶段已经完成，并取得了新的验证证据。"
                ),
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": [evidence_ref],
                    }
                ],
                "residualRisks": (
                    ["review_changes_requested"]
                    if decision == "handoff"
                    else []
                ),
                **extra,
            },
            tool_call_id=f"call:{suffix}",
            load_receipt_id=str(loaded["receiptId"]),
        )
        return self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": session_id,
                "dispatchId": dispatch_id,
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": dispatch["capabilityEpoch"],
                "runtimeTurnId": f"turn:{dispatch_id}",
                "dispatchAttempt": dispatch["attempt"],
                "settleScopeId": f"scope:{suffix}",
                "settleAttempt": 1,
                "resourceUsage": {
                    "inputTokens": 80,
                    "outputTokens": 20,
                    "toolCalls": 1,
                    "toolCost": 1,
                    "retryCount": 0,
                    "repairCount": 0,
                },
            }
        )["result"]

    def _handoff_and_complete_review_axis(
        self,
        *,
        facilitator_dispatch_id: str,
        review_axis: str,
        suffix: str,
        source_evidence_ref: str,
        review_findings: list[dict[str, object]] | None = None,
        expected_next_review_axis: str | None = None,
    ) -> dict[str, str]:
        """Run one explicit review axis and return its exact resume lineage."""

        facilitator_evidence_ref = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix=f"{suffix}-facilitator",
        )
        handoff = self._commit_and_settle_dispatch(
            session_id=self.session_id,
            dispatch_id=facilitator_dispatch_id,
            decision="handoff",
            suffix=f"{suffix}-handoff",
            evidence_ref=facilitator_evidence_ref,
            targetParticipantRef="P1",
            intent="review",
            reviewAxis=review_axis,
            nextTask=f"独立完成 {review_axis} 角度复核",
            expectedOutput="公开复核结论与本轮新鲜证据",
            acceptanceAliases=["AC-1"],
        )
        self.assertEqual(handoff["state"], "committed", handoff)
        receipt = handoff["settleResult"]["receipt"]
        review_task_id = str(receipt["details"]["childTaskId"])
        review_dispatch_id = str(receipt["details"]["childDispatchId"])
        self.assertEqual(
            self.service.room_kernel.task(review_task_id)["reviewAxis"],
            review_axis,
        )
        review_task = self.service.room_kernel.task(review_task_id)
        self.assertEqual(
            set(review_task["reviewOfTaskIds"]),
            set(
                self.service.room_kernel.required_review_task_ids(
                    "root:settle"
                )
            ),
            {
                "reviewTask": review_task,
                "children": self.service.room_kernel.collaboration_children(
                    "root:settle"
                ),
            },
        )

        self._pin_independent_review(
            dispatch_id=review_dispatch_id,
            session_id=str(self.target["sessionId"]),
            suffix=f"{suffix}-{review_axis}",
        )
        self.service.room_kernel_worker.run_once()
        review_evidence_ref = self._record_workspace_evidence(
            session_id=str(self.target["sessionId"]),
            suffix=f"{suffix}-{review_axis}-evidence",
        )
        reviewed = self._commit_and_settle_dispatch(
            session_id=str(self.target["sessionId"]),
            dispatch_id=review_dispatch_id,
            decision="deliver",
            suffix=f"{suffix}-{review_axis}-deliver",
            evidence_ref=review_evidence_ref,
            reviewFindings=list(review_findings or ()),
        )
        self.assertEqual(reviewed["state"], "committed", reviewed)
        resume_ids = reviewed["settleResult"]["receipt"]["details"][
            "resumedDispatchIds"
        ]
        if expected_next_review_axis is None:
            self.assertEqual(len(resume_ids), 1)
            facilitator_resume_dispatch_id = str(resume_ids[0])
            next_review_task_id = ""
            next_review_dispatch_id = ""
        else:
            self.assertEqual(resume_ids, [])
            attempts = self.service.room_kernel.latest_review_attempts(
                "root:settle"
            )
            next_attempt = next(
                attempt
                for attempt in attempts
                if attempt["payload"].get("reviewAxis")
                == expected_next_review_axis
            )
            next_review_task_id = str(next_attempt["taskId"])
            next_review_dispatch_id = str(
                next_attempt["dispatch"]["dispatchId"]
            )
            self.assertEqual(next_attempt["taskState"], "active")
            self.assertEqual(next_attempt["dispatch"]["state"], "pending")
            facilitator_resume_dispatch_id = ""
        return {
            "reviewTaskId": review_task_id,
            "reviewDispatchId": review_dispatch_id,
            "reviewEvidenceRef": review_evidence_ref,
            "sourceEvidenceRef": source_evidence_ref,
            "facilitatorEvidenceRef": facilitator_evidence_ref,
            "facilitatorResumeDispatchId": facilitator_resume_dispatch_id,
            "nextReviewTaskId": next_review_task_id,
            "nextReviewDispatchId": next_review_dispatch_id,
        }

    def test_completed_review_axis_deterministically_starts_the_missing_axis(
        self,
    ) -> None:
        technical = self._handoff_and_complete_review_axis(
            facilitator_dispatch_id="dispatch:settle",
            review_axis="technical",
            suffix="automatic-review-technical",
            source_evidence_ref="evidence:settle",
            expected_next_review_axis="requirements",
        )
        requirements_task_id = technical["nextReviewTaskId"]
        requirements_dispatch_id = technical["nextReviewDispatchId"]
        requirements_task = self.service.room_kernel.task(
            requirements_task_id
        )
        self.assertEqual(requirements_task["reviewAxis"], "requirements")
        self.assertEqual(requirements_task["workspacePolicy"], "read_only")
        self.assertEqual(
            requirements_task["reviewOfTaskIds"],
            self.service.room_kernel.task(technical["reviewTaskId"])[
                "reviewOfTaskIds"
            ],
        )
        self.assertEqual(
            self.service.room_kernel.task("task:settle")["state"],
            "waiting",
        )

        self._pin_independent_review(
            dispatch_id=requirements_dispatch_id,
            session_id=str(self.target["sessionId"]),
            suffix="automatic-review-requirements",
        )
        self.service.room_kernel_worker.run_once()
        requirements_evidence = self._record_workspace_evidence(
            session_id=str(self.target["sessionId"]),
            suffix="automatic-review-requirements-evidence",
        )
        requirements = self._commit_and_settle_dispatch(
            session_id=str(self.target["sessionId"]),
            dispatch_id=requirements_dispatch_id,
            decision="deliver",
            suffix="automatic-review-requirements-deliver",
            evidence_ref=requirements_evidence,
            reviewFindings=[],
        )

        self.assertEqual(requirements["state"], "committed", requirements)
        resume_ids = requirements["settleResult"]["receipt"]["details"][
            "resumedDispatchIds"
        ]
        self.assertEqual(
            len(resume_ids),
            1,
            self.service.room_kernel.latest_review_attempts("root:settle"),
        )
        self.assertEqual(
            self.service.room_kernel.task("task:settle")["state"],
            "active",
        )
        self.assertEqual(
            {
                attempt["payload"].get("reviewAxis")
                for attempt in self.service.room_kernel.latest_review_attempts(
                    "root:settle"
                )
                if attempt["taskState"] == "completed"
                and attempt["payload"].get("reviewState")
                in {"accepted", "accepted_with_notes"}
            },
            {"technical", "requirements"},
        )

    def _complete_materialized_review_axis(
        self,
        *,
        review_dispatch_id: str,
        suffix: str,
        review_findings: list[dict[str, object]] | None = None,
    ) -> dict[str, str]:
        """Complete a Kernel-chained review axis and return its resume."""

        self._pin_independent_review(
            dispatch_id=review_dispatch_id,
            session_id=str(self.target["sessionId"]),
            suffix=suffix,
        )
        self.service.room_kernel_worker.run_once()
        evidence_ref = self._record_workspace_evidence(
            session_id=str(self.target["sessionId"]),
            suffix=f"{suffix}-evidence",
        )
        settled = self._commit_and_settle_dispatch(
            session_id=str(self.target["sessionId"]),
            dispatch_id=review_dispatch_id,
            decision="deliver",
            suffix=f"{suffix}-deliver",
            evidence_ref=evidence_ref,
            reviewFindings=list(review_findings or ()),
        )
        self.assertEqual(settled["state"], "committed", settled)
        resume_ids = settled["settleResult"]["receipt"]["details"][
            "resumedDispatchIds"
        ]
        self.assertEqual(len(resume_ids), 1)
        return {
            "reviewEvidenceRef": evidence_ref,
            "facilitatorResumeDispatchId": str(resume_ids[0]),
        }

    def test_review_required_root_cannot_bypass_after_room_policy_mutation(self) -> None:
        self.service.update_room(
            self.room_id,
            {"routingPolicy": "parallel"},
        )
        with sqlite3.connect(self.service.room_kernel.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_kernel_roots WHERE root_id=?",
                ("root:settle",),
            ).fetchone()
            assert row is not None
            payload = json.loads(str(row[0]))
            payload["independentReviewRequired"] = True
            conn.execute(
                "UPDATE room_kernel_roots SET payload_json=? WHERE root_id=?",
                (json.dumps(payload, sort_keys=True), "root:settle"),
            )
        self.service.update_room(
            self.room_id,
            {"routingPolicy": "natural"},
        )
        self.service.update_room_participant_role(
            self.room_id,
            {
                "participantId": str(self.target["id"]),
                "collaborationRole": "coordinator",
            },
        )

        self._invoke_commit("deliver")
        settled = self._settle()
        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("独立复核", settled["reason"])

        policy_root = {
            "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
            "rootId": "root:review-policy",
            "roomId": self.room_id,
            "generation": 0,
            "state": "running",
            "facilitatorParticipantId": str(self.owner["id"]),
            "reporterParticipantId": str(self.owner["id"]),
            "reporterSelectionReceiptId": None,
            "requirementAnchorRef": "requirement-anchor:review-policy",
            "createdByActorRef": "user:local",
            "terminalReceiptId": None,
            "activeProfileRef": None,
            "budgetPolicyRef": "room-budget:test-v1",
            "independentReviewRequired": True,
            "createdAtMs": self.now_ms + 100,
        }
        self.service.room_kernel.create_root_with_task(
            policy_root,
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:review-policy",
                "rootId": "root:review-policy",
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
                "objective": "Exercise the independent review terminal fence.",
                "expectedOutput": "A rejected terminal receipt.",
                "requirementItemIds": ["requirement:review-policy"],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "completed",
            },
            budget=10,
            max_hops=3,
            max_depth=3,
            acceptance_criteria=(),
            now_ms=self.now_ms + 100,
        )
        rejected = self.service.room_kernel.finalize_root(
            "root:review-policy",
            now_ms=self.now_ms + 101,
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(
            rejected["details"]["reason"],
            "independent_review_required",
        )

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
        self.assertEqual(root["state"], "running")
        self.assertIsNone(root["terminalReceiptId"])
        report = self.service.room_kernel.report_readiness(
            "root:settle"
        )["existing"]
        self.assertEqual(report["dispatch"]["intentKind"], "close")
        self.assertEqual(report["dispatch"]["state"], "pending")
        self.assertEqual(report["task"]["workspacePolicy"], "read_only")
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
        self.assertEqual(len(terminal_events), 0)
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

    def test_committed_room_turn_is_terminal_in_recent_session_snapshot(
        self,
    ) -> None:
        turn_id = "turn:dispatch:settle"
        self.service.events.publish(
            self.session_id,
            "status_changed",
            {"status": "working", "phase": "analyzing"},
            turn_id=turn_id,
        )
        self.service.events.publish(
            self.session_id,
            "reasoning_summary",
            {"summary": "已核对当前工作并准备提交", "state": "completed"},
            turn_id=turn_id,
        )
        self._invoke_commit("deliver")

        settled = self._settle()
        # Match the installed failure: Pi is already idle and the Room child
        # is committed, while the recent partial window still lacks the
        # Provider turn's terminal event.
        self.service.sessions.set_status(self.session_id, "idle")
        recent = self.service.message_snapshot.messages(
            self.session_id,
            view="recent",
        )

        self.assertEqual(settled["state"], "committed")
        self.assertEqual(recent["status"], "idle")
        self.assertTrue(recent["partial"])
        terminal_events = [
            event
            for event in recent["liveEvents"]
            if event["turnId"] == turn_id
            and event["eventType"] in {"turn_completed", "turn_failed"}
        ]
        self.assertEqual(len(terminal_events), 1)
        self.assertEqual(
            terminal_events[0]["payload"]["terminalEvent"],
            "room_commit_settlement",
        )
        replayed = self._settle()
        replay_recent = self.service.message_snapshot.messages(
            self.session_id,
            view="recent",
        )
        self.assertTrue(replayed["replayed"])
        self.assertEqual(
            len(
                [
                    event
                    for event in replay_recent["liveEvents"]
                    if event["turnId"] == turn_id
                    and event["eventType"]
                    in {"turn_completed", "turn_failed"}
                ]
            ),
            1,
        )

    def test_settle_rejects_a_turn_outside_the_accepted_runtime_attempt(
        self,
    ) -> None:
        self._invoke_commit("deliver")

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
                    "dispatchId": "dispatch:settle",
                    "rootId": "root:settle",
                    "generation": 0,
                    "capabilityEpoch": 7,
                    "runtimeTurnId": "turn:newer-or-unrelated",
                    "dispatchAttempt": 0,
                    "settleScopeId": "scope:wrong-turn",
                    "settleAttempt": 1,
                    "resourceUsage": {},
                }
            )

        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "running",
        )
        self.assertIsNone(
            self.service.sessions.runtime_turn_terminal_event(
                self.session_id,
                "turn:newer-or-unrelated",
            )
        )

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
    def _record_workspace_evidence(
        self,
        *,
        session_id: str,
        suffix: str,
    ) -> str:
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": session_id,
                "receiptId": f"load:workspace-read:{suffix}",
                "toolName": "workspace_read",
                "createdAtMs": self.now_ms + 10,
            }
        )["result"]
        authorized = self.service.authorize_room_product_tool(
            session_id,
            "workspace_read",
            {"op": "read", "path": str(self.workspace_root)},
            tool_call_id=f"call:workspace-read:{suffix}",
            load_receipt_id=str(loaded["receiptId"]),
        )
        assert authorized is not None
        invocation_id = str(
            authorized["invocationReceipt"]["receiptId"]
        )
        recorded = self.service.record_room_product_tool_execution(
            session_id,
            invocation_id,
            status="applied",
            result_hash="c" * 64,
        )
        return str(
            recorded["executionReceipt"]["executionReceiptId"]
        )


    def test_review_handoff_resumes_facilitator_for_reporter_delivery(self) -> None:
        facilitator_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="facilitator",
        )
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P1",
            intent="review",
            nextTask="独立复核已集成结果并回传结论",
            expectedOutput="公开复核结论与新鲜证据",
            acceptanceAliases=["AC-1"],
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": [
                        "evidence:settle",
                        facilitator_evidence,
                    ],
                }
            ],
        )

        settled = self._settle()
        self.assertEqual(
            settled["settleResult"]["post"]["content"],
            "当前阶段已经完成，现转交另一位伙伴独立复核后再给出结论。",
        )
        self.assertEqual(
            settled["settleResult"]["post"]["mentions"],
            [str(self.target["id"])],
        )
        receipt = settled["settleResult"]["receipt"]
        self.assertIsNone(receipt["details"]["transferredTaskId"])
        review_task_id = str(receipt["details"]["childTaskId"])
        review_dispatch_id = str(receipt["details"]["childDispatchId"])
        parent_task = self.service.room_kernel.task("task:settle")
        review_task = self.service.room_kernel.task(review_task_id)
        initial_review_target_revision = str(
            review_task["reviewTargetRevision"]
        )
        review_dispatch = self.service.room_kernel.dispatch(
            review_dispatch_id
        )
        self.assertEqual(parent_task["state"], "waiting")
        self.assertEqual(
            parent_task["currentOwnerParticipantId"],
            self.owner["id"],
        )
        self.assertEqual(review_task["parentTaskId"], "task:settle")
        self.assertEqual(review_task["taskKind"], "review")
        self.assertEqual(review_task["reviewAxis"], "technical")
        self.assertEqual(
            self.service.room_kernel.root("root:settle")[
                "requiredReviewAxes"
            ],
            ["technical", "requirements"],
        )
        self.assertEqual(
            review_task["currentOwnerParticipantId"],
            self.target["id"],
        )
        self.assertEqual(
            review_task["reviewAuthorParticipantIds"],
            [self.owner["id"]],
        )
        self.assertEqual(
            review_task["reviewOfTaskIds"],
            ["task:settle"],
        )
        self.assertEqual(review_task["workspacePolicy"], "read_only")
        self.assertIn(
            facilitator_evidence,
            review_task["contextEvidenceRefs"],
        )
        self.assertEqual(review_dispatch["intentKind"], "review")
        self.assertEqual(review_dispatch["state"], "pending")
        self.assertEqual(
            self.service.room_kernel.counts("root:settle")["tasks"],
            2,
        )
        continuation = self.service.room_kernel.continuation(
            str(receipt["details"]["commitId"])
        )
        self.assertEqual(continuation["decision"], "dispatch")
        self.assertEqual(
            continuation["payload"]["waitingForDispatchId"],
            review_dispatch_id,
        )
        self.assertNotIn(
            "resumeDispatchId",
            continuation["payload"],
        )

    def test_review_handoff_accepts_an_independent_peer_without_reserved_reviewer_role(
        self,
    ) -> None:
        self.service.update_room_participant_role(
            self.room_id,
            {
                "participantId": str(self.target["id"]),
                "collaborationRole": "implementer",
            },
        )
        facilitator_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="peer-review",
        )
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P1",
            intent="review",
            nextTask="独立复核自己未参与实现或集成的范围",
            expectedOutput="公开复核结论与新鲜证据",
            acceptanceAliases=["AC-1"],
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": ["evidence:settle", facilitator_evidence],
                }
            ],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "committed", settled)
        receipt = settled["settleResult"]["receipt"]
        review_task_id = str(receipt["details"]["childTaskId"])
        review_dispatch_id = str(receipt["details"]["childDispatchId"])
        review_task = self.service.room_kernel.task(review_task_id)
        initial_review_target_revision = str(
            review_task["reviewTargetRevision"]
        )
        self.assertEqual(review_task["taskKind"], "review")
        self.assertEqual(
            review_task["currentOwnerParticipantId"],
            self.target["id"],
        )
        self.assertEqual(
            self.service.rooms.participant(str(self.target["id"]))[
                "collaborationRole"
            ],
            "implementer",
        )

        skill_id = "independent-review"
        self.service.room_skill_receipts.pin_skill(
            receipt_id="skill:handoff-child",
            root_id="root:settle",
            task_id=review_task_id,
            dispatch_id=review_dispatch_id,
            session_id=str(self.target["sessionId"]),
            skill_id=skill_id,
            skill_hash=self.service.room_skill_policy.skill_hash(skill_id),
            catalog_revision="c" * 64,
            load_reason="stage_required",
            capability_epoch=8,
            idempotency_key=f"{review_dispatch_id}/review",
            created_at_ms=self.now_ms + 20,
        )
        self.service.room_kernel_worker.run_once()
        reviewer_evidence = self._record_workspace_evidence(
            session_id=str(self.target["sessionId"]),
            suffix="reviewer",
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
                        "refs": [reviewer_evidence],
                    }
                ],
                "residualRisks": [],
                "reviewFindings": [
                    {
                        "findingId": "Advisory-1",
                        "gateEffect": "advisory",
                        "impact": "normal",
                        "category": "maintainability",
                        "scope": {"acceptance": "AC-1"},
                        "observation": "复核发现一处不阻断交付的命名问题",
                        "expected": "后续维护时统一命名",
                        "userImpact": "不影响当前用户结果",
                        "evidenceRefs": [reviewer_evidence],
                        "reproduction": ["读取相关实现并核对命名"],
                        "state": "dismissed",
                        "dispositionRationale": (
                            "已确认不影响当前验收，明确转入后续维护 backlog"
                        ),
                    }
                ],
            },
            tool_call_id="call:handoff-child-commit",
            load_receipt_id=str(loaded_commit["receiptId"]),
        )
        child_settled = self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": str(self.target["sessionId"]),
                "dispatchId": review_dispatch_id,
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": 8,
                "runtimeTurnId": f"turn:{review_dispatch_id}",
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
        self.assertEqual(child_settled["state"], "committed", child_settled)
        self.assertEqual(
            child_settled["settleResult"]["post"]["kind"],
            "review_result",
        )
        self.assertEqual(
            child_settled["settleResult"]["post"]["authorActorRef"],
            self.target["id"],
        )
        resumed = child_settled["settleResult"]["receipt"]["details"][
            "resumedDispatchIds"
        ]
        self.assertEqual(resumed, [])
        self.assertEqual(
            self.service.room_kernel.task(review_task_id)["reviewState"],
            "accepted_with_notes",
        )
        accepted_review_task = self.service.room_kernel.task(review_task_id)
        self.assertEqual(
            accepted_review_task["reviewTargetRevision"],
            initial_review_target_revision,
        )
        accepted_review_commit = self.service.room_kernel.latest_task_commit(
            review_task_id
        )
        assert accepted_review_commit is not None
        self.assertEqual(
            accepted_review_commit["reviewEvidenceBinding"]["dispatchId"],
            review_dispatch_id,
        )
        self.assertEqual(
            self.service.room_kernel.task("task:settle")["state"],
            "waiting",
        )
        self.assertEqual(
            self.service.room_kernel.root("root:settle")["state"],
            "running",
        )
        requirements_attempt = next(
            attempt
            for attempt in self.service.room_kernel.latest_review_attempts(
                "root:settle"
            )
            if attempt["payload"].get("reviewAxis") == "requirements"
        )
        requirements_dispatch_id = str(
            requirements_attempt["dispatch"]["dispatchId"]
        )
        resumed_continuation = self.service.room_kernel.continuation(
            str(receipt["details"]["commitId"])
        )
        self.assertEqual(
            resumed_continuation["payload"]["waitingForDispatchId"],
            requirements_dispatch_id,
        )
        requirements_review = self._complete_materialized_review_axis(
            review_dispatch_id=requirements_dispatch_id,
            suffix="peer-review-requirements",
        )
        requirements_evidence = requirements_review["reviewEvidenceRef"]
        resume_dispatch_id = requirements_review[
            "facilitatorResumeDispatchId"
        ]
        self.service.room_kernel_worker.run_once()
        resume_dispatch = self.service.room_kernel.dispatch(
            resume_dispatch_id
        )
        final_facilitator_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="peer-review-final-facilitator",
        )
        loaded_final = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:reporter-final",
                "toolName": "room_commit",
                "createdAtMs": self.now_ms + 30,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": "deliver",
                "summary": "Facilitator 汇总复核证据并交付",
                "publicSummary": "实现与独立复核均已完成，现由主持人汇总交付。",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        # The final proposal owns fresh Facilitator evidence.
                        # Accepted review-axis refs remain Kernel-owned and do
                        # not need to be copied into this presentation layer.
                        "refs": [final_facilitator_evidence],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:reporter-final",
            load_receipt_id=str(loaded_final["receiptId"]),
        )
        final_settled = self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": self.session_id,
                "dispatchId": resume_dispatch_id,
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": resume_dispatch["capabilityEpoch"],
                "runtimeTurnId": f"turn:{resume_dispatch_id}",
                "dispatchAttempt": resume_dispatch["attempt"],
                "settleScopeId": "scope:reporter-final",
                "settleAttempt": 1,
                "resourceUsage": {
                    "inputTokens": 90,
                    "outputTokens": 30,
                    "toolCalls": 1,
                    "toolCost": 1,
                    "retryCount": 0,
                    "repairCount": 0,
                },
            }
        )["result"]
        self.assertEqual(final_settled["state"], "committed")
        pending_root = self.service.room_kernel.root("root:settle")
        self.assertEqual(pending_root["state"], "running")
        report_state = self.service.room_kernel.report_readiness(
            "root:settle"
        )
        report = report_state["existing"]
        report_dispatch = report["dispatch"]
        self.assertEqual(report_dispatch["intentKind"], "close")
        self.assertEqual(report_dispatch["state"], "pending")
        self.assertEqual(report["task"]["workspacePolicy"], "read_only")
        self.service.room_kernel_worker.run_once()
        loaded_internal_report = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:canonical-report-internal",
                "toolName": "room_commit",
                "createdAtMs": self.now_ms + 39,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": "deliver",
                "summary": "Reporter 尝试暴露内部协议",
                "publicSummary": (
                    "Kernel 读取 Root、Dispatch、Task 与 AC 后，"
                    "输出 Receipt ID。"
                ),
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": [reviewer_evidence, requirements_evidence],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:canonical-report-internal",
            load_receipt_id=str(loaded_internal_report["receiptId"]),
        )
        rejected_report = self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": self.session_id,
                "dispatchId": report_dispatch["dispatchId"],
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": report_dispatch["capabilityEpoch"],
                "runtimeTurnId": f"turn:{report_dispatch['dispatchId']}",
                "dispatchAttempt": report_dispatch["attempt"],
                "settleScopeId": "scope:canonical-report",
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
        self.assertEqual(rejected_report["state"], "repair_commit")
        self.assertIn(
            "must be rewritten for users",
            rejected_report["reason"],
        )
        loaded_report = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": "load:canonical-report",
                "toolName": "room_commit",
                "createdAtMs": self.now_ms + 40,
            }
        )["result"]
        self.service.execute_room_capability_tool(
            self.session_id,
            "room_commit",
            {
                "decision": "deliver",
                "summary": "Reporter 汇总完成",
                "publicSummary": "实现和独立复核都已完成，结果可以交付。",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": [reviewer_evidence, requirements_evidence],
                    }
                ],
                "residualRisks": [],
            },
            tool_call_id="call:canonical-report",
            load_receipt_id=str(loaded_report["receiptId"]),
        )
        report_settled = self.service.settle_room_runtime(
            {
                "schemaVersion": "wisdom-weasel.room-runtime-settle-request.v1",
                "sessionId": self.session_id,
                "dispatchId": report_dispatch["dispatchId"],
                "rootId": "root:settle",
                "generation": 0,
                "capabilityEpoch": report_dispatch["capabilityEpoch"],
                "runtimeTurnId": f"turn:{report_dispatch['dispatchId']}",
                "dispatchAttempt": report_dispatch["attempt"],
                "settleScopeId": "scope:canonical-report",
                "settleAttempt": 2,
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
        self.assertEqual(report_settled["state"], "committed", report_settled)
        root = self.service.room_kernel.root("root:settle")
        self.assertEqual(root["state"], "completed")
        self.assertTrue(root["terminalReceiptId"])
        posts = self.service.room_context_ledger.recent_posts(
            "root:settle",
            limit=10,
        )
        final_posts = [
            post for post in posts if post["kind"] == "result"
        ]
        self.assertEqual(len(final_posts), 1)
        execution_posts = [
            post for post in posts if post["kind"] == "work_result"
        ]
        self.assertEqual(len(execution_posts), 1)
        review_posts = [
            post for post in posts if post["kind"] == "review_result"
        ]
        self.assertEqual(len(review_posts), 2)
        self.assertTrue(
            all(
                post["authorActorRef"] == self.target["id"]
                for post in review_posts
            )
        )
        self.assertEqual(
            final_posts[0]["authorActorRef"],
            self.owner["id"],
        )
        replay = self.service.finalize_room_kernel_root(
            "root:settle",
            now_ms=self.now_ms + 50,
        )
        self.assertEqual(replay["receipt"]["receiptId"], root["terminalReceiptId"])
        report_dispatches = [
            item
            for item in self.service.room_kernel_snapshot(self.room_id)[
                "dispatches"
            ]
            if item["intentKind"] == "close"
        ]
        self.assertEqual(len(report_dispatches), 1)

    def test_review_finding_revises_then_rechecks_before_final_delivery(
        self,
    ) -> None:
        facilitator_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="revision-loop-facilitator",
        )
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P1",
            intent="review",
            nextTask="独立复核已集成结果并回传结论",
            expectedOutput="公开复核结论与新鲜证据",
            acceptanceAliases=["AC-1"],
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": ["evidence:settle", facilitator_evidence],
                }
            ],
        )
        review_handoff = self._settle()
        review_receipt = review_handoff["settleResult"]["receipt"]
        review_task_id = str(review_receipt["details"]["childTaskId"])
        review_dispatch_id = str(
            review_receipt["details"]["childDispatchId"]
        )

        self._pin_independent_review(
            dispatch_id=review_dispatch_id,
            session_id=str(self.target["sessionId"]),
            suffix="revision-loop-review-1",
        )
        self.service.room_kernel_worker.run_once()
        first_review_evidence = self._record_workspace_evidence(
            session_id=str(self.target["sessionId"]),
            suffix="revision-loop-finding",
        )
        revision_handoff = self._commit_and_settle_dispatch(
            session_id=str(self.target["sessionId"]),
            dispatch_id=review_dispatch_id,
            decision="handoff",
            suffix="revision-loop-review-handoff",
            evidence_ref=first_review_evidence,
            targetParticipantRef="P2",
            intent="revise",
            nextTask="按独立复核证据修正集成结果",
            expectedOutput="修正后的产物与新验证证据",
            acceptanceAliases=["AC-1"],
            reviewFindings=[
                {
                    "findingId": "Finding-1",
                    "gateEffect": "blocking",
                    "impact": "critical",
                    "category": "correctness",
                    "scope": {"acceptance": "AC-1"},
                    "observation": "集成结果在边界输入下仍返回旧值",
                    "expected": "边界输入应返回修正后的值",
                    "userImpact": "用户会收到错误结果",
                    "evidenceRefs": [first_review_evidence],
                    "reproduction": ["运行边界输入检查并观察旧值"],
                    "state": "open",
                    "ownerParticipantRef": "P2",
                },
                {
                    "findingId": "Regression-1",
                    "gateEffect": "blocking",
                    "impact": "critical",
                    "category": "regression",
                    "scope": {"acceptance": "AC-1"},
                    "observation": "修复后的边界行为在回归检查中仍需确认",
                    "expected": "回归检查应保持修复后的边界行为",
                    "userImpact": "未来回归可能重新暴露错误",
                    "evidenceRefs": [first_review_evidence],
                    "reproduction": ["运行回归检查并观察边界行为"],
                    "state": "open",
                    "ownerParticipantRef": "P2",
                },
            ],
        )
        self.assertEqual(
            revision_handoff["state"],
            "committed",
            revision_handoff,
        )
        revision_receipt = revision_handoff["settleResult"]["receipt"]
        revision_dispatch_id = str(
            revision_receipt["details"]["childDispatchId"]
        )
        revision_task_id = str(
            revision_receipt["details"]["childTaskId"]
        )
        review_task = self.service.room_kernel.task(review_task_id)
        revision_task = self.service.room_kernel.task(revision_task_id)
        initial_review_target_revision = str(
            review_task["reviewTargetRevision"]
        )
        self.assertEqual(review_task["reviewState"], "changes_requested")
        self.assertEqual(review_task["state"], "waiting")
        self.assertEqual(
            revision_task["currentOwnerParticipantId"],
            self.owner["id"],
        )
        self.assertEqual(
            revision_task["workspacePolicy"],
            "shared_single_writer",
        )

        started_revision = self.service.room_kernel_worker.run_once()
        self.assertIsNotNone(started_revision)
        assert started_revision is not None
        self.assertEqual(
            started_revision["details"]["dispatchId"],
            revision_dispatch_id,
        )
        self.assertEqual(
            self.service.room_kernel.dispatch(revision_dispatch_id)["state"],
            "running",
        )
        revision_manifest = self.service.room_capabilities.manifest_for_runtime(
            self.session_id,
            active_only=False,
        )
        self.assertIsNotNone(revision_manifest)
        assert revision_manifest is not None
        self.assertEqual(
            revision_manifest[0]["dispatchId"],
            revision_dispatch_id,
        )
        stale_revision_settled = self._commit_and_settle_dispatch(
            session_id=self.session_id,
            dispatch_id=revision_dispatch_id,
            decision="deliver",
            suffix="revision-loop-stale-evidence",
            evidence_ref=first_review_evidence,
            reviewFindingResponses=[
                {
                    "findingId": "Finding-1",
                    "action": "fixed",
                    "rationale": "尝试复用修正前的复核证据",
                    "evidenceRefs": [first_review_evidence],
                }
            ],
        )
        self.assertEqual(
            stale_revision_settled["state"],
            "repair_commit",
            stale_revision_settled,
        )
        revision_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="revision-loop-fix",
        )
        revision_settled = self._commit_and_settle_dispatch(
            session_id=self.session_id,
            dispatch_id=revision_dispatch_id,
            decision="deliver",
            suffix="revision-loop-fix-deliver",
            evidence_ref=revision_evidence,
            reviewFindingResponses=[
                {
                    "findingId": "Finding-1",
                    "action": "fixed",
                    "rationale": "已修正边界分支并重新验证",
                    "evidenceRefs": [revision_evidence],
                },
                {
                    "findingId": "Regression-1",
                    "action": "fixed",
                    "rationale": "已补充边界行为回归检查",
                    "evidenceRefs": [revision_evidence],
                },
            ],
        )
        self.assertEqual(
            revision_settled["state"],
            "committed",
            revision_settled,
        )
        review_resume_ids = revision_settled["settleResult"]["receipt"][
            "details"
        ]["resumedDispatchIds"]
        self.assertEqual(len(review_resume_ids), 1)
        review_resume_id = str(review_resume_ids[0])
        self.assertEqual(
            self.service.room_kernel.task(review_task_id)["reviewState"],
            "in_review",
        )

        self._pin_independent_review(
            dispatch_id=review_resume_id,
            session_id=str(self.target["sessionId"]),
            suffix="revision-loop-review-2",
        )
        self.service.room_kernel_worker.run_once()
        final_review_evidence = self._record_workspace_evidence(
            session_id=str(self.target["sessionId"]),
            suffix="revision-loop-pass",
        )
        review_settled = self._commit_and_settle_dispatch(
            session_id=str(self.target["sessionId"]),
            dispatch_id=review_resume_id,
            decision="deliver",
            suffix="revision-loop-review-deliver",
            evidence_ref=final_review_evidence,
            reviewFindings=[
                {
                    "findingId": "Finding-1",
                    "gateEffect": "blocking",
                    "impact": "critical",
                    "category": "correctness",
                    "scope": {"acceptance": "AC-1"},
                    "observation": "集成结果在边界输入下仍返回旧值",
                    "expected": "边界输入应返回修正后的值",
                    "userImpact": "用户会收到错误结果",
                    "evidenceRefs": [final_review_evidence],
                    "reproduction": ["运行边界输入检查并确认新值"],
                    "state": "resolved",
                },
                {
                    "findingId": "Regression-1",
                    "gateEffect": "blocking",
                    "impact": "critical",
                    "category": "regression",
                    "scope": {"acceptance": "AC-1"},
                    "observation": "修复后的边界行为在回归检查中仍需确认",
                    "expected": "回归检查应保持修复后的边界行为",
                    "userImpact": "未来回归可能重新暴露错误",
                    "evidenceRefs": [final_review_evidence],
                    "reproduction": ["运行回归检查并确认边界行为"],
                    "state": "resolved",
                },
            ],
        )
        self.assertIn("settleResult", review_settled, review_settled)
        facilitator_resume_ids = review_settled["settleResult"]["receipt"][
            "details"
        ]["resumedDispatchIds"]
        self.assertEqual(facilitator_resume_ids, [])
        self.assertEqual(
            self.service.room_kernel.task(review_task_id)["reviewState"],
            "accepted",
        )
        final_review_task = self.service.room_kernel.task(review_task_id)
        self.assertNotEqual(
            final_review_task["reviewTargetRevision"],
            initial_review_target_revision,
        )
        regression_finding = next(
            finding
            for finding in final_review_task["reviewFindings"]
            if finding["findingId"] == "Regression-1"
        )
        self.assertEqual(regression_finding["category"], "regression")
        self.assertEqual(regression_finding["gateEffect"], "blocking")
        final_review_commit = self.service.room_kernel.latest_task_commit(
            review_task_id
        )
        assert final_review_commit is not None
        binding = final_review_commit["reviewEvidenceBinding"]
        self.assertEqual(
            binding["reviewTargetRevision"],
            final_review_task["reviewTargetRevision"],
        )
        self.assertEqual(binding["taskId"], review_task_id)
        self.assertEqual(binding["dispatchId"], review_resume_id)
        self.assertEqual(binding["evidenceRefs"], [final_review_evidence])
        self.assertEqual(
            binding["notBeforeMs"],
            final_review_task["reviewEvidenceNotBeforeMs"],
        )
        requirements_attempt = next(
            attempt
            for attempt in self.service.room_kernel.latest_review_attempts(
                "root:settle"
            )
            if attempt["payload"].get("reviewAxis") == "requirements"
        )
        requirements_review = self._complete_materialized_review_axis(
            review_dispatch_id=str(
                requirements_attempt["dispatch"]["dispatchId"]
            ),
            suffix="revision-loop-requirements",
        )
        final_resume_id = requirements_review[
            "facilitatorResumeDispatchId"
        ]
        requirements_evidence = requirements_review["reviewEvidenceRef"]
        self.service.room_kernel_worker.run_once()
        final_facilitator_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="revision-loop-final-facilitator",
        )
        final_settled = self._commit_and_settle_dispatch(
            session_id=self.session_id,
            dispatch_id=final_resume_id,
            decision="deliver",
            suffix="revision-loop-final",
            evidence_ref=requirements_evidence,
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": [
                        final_review_evidence,
                        requirements_evidence,
                        final_facilitator_evidence,
                    ],
                }
            ],
        )
        self.assertEqual(final_settled["state"], "committed", final_settled)
        root = self.service.room_kernel.root("root:settle")
        self.assertEqual(root["state"], "running")
        self.assertIsNone(root["terminalReceiptId"])
        report = self.service.room_kernel.report_readiness(
            "root:settle"
        )["existing"]
        self.assertEqual(report["dispatch"]["intentKind"], "close")
        self.assertEqual(report["dispatch"]["state"], "pending")
        self.assertEqual(report["task"]["workspacePolicy"], "read_only")

    def test_reviewer_revision_handoff_returns_writable_lane_to_facilitator(
        self,
    ) -> None:
        base_task = self.service.room_kernel.task("task:settle")
        review_task = {
            **base_task,
            "taskId": "task:review-revision",
            "parentTaskId": "task:settle",
            "taskKind": "review",
            "currentOwnerParticipantId": str(self.target["id"]),
            "reviewState": "required",
            "reviewOfTaskIds": ["task:settle"],
            "reviewAuthorParticipantIds": [str(self.owner["id"])],
            "reviewTargetRevision": self.service.room_kernel.review_target_revision(
                root_id="root:settle",
                task_ids=["task:settle"],
            ),
            "reviewRound": 1,
            "reviewFindings": [],
            "workspacePolicy": "read_only",
            "workspaceRoot": str(self.workspace_root),
            "workspaceBaseRoot": str(self.workspace_root),
            "workspaceIntegrationState": "not_required",
        }
        revision_task = {
            **base_task,
            "taskId": "task:review-revision:child",
            "parentTaskId": "task:review-revision",
            "taskKind": "work",
            "currentOwnerParticipantId": str(self.owner["id"]),
            "objective": "按独立复核证据修正集成结果",
            "expectedOutput": "修正后的产物与新验证证据",
            "reviewState": "not_required",
            "reviewOfTaskIds": [],
            "reviewAuthorParticipantIds": [],
        }

        prepared = (
            self.service.room_kernel_application.prepare_revision_handoff_task(
                parent_dispatch={
                    "rootId": "root:settle",
                    "targetParticipantId": str(self.target["id"]),
                },
                parent_task=review_task,
                target_participant_id=str(self.owner["id"]),
                child_task=revision_task,
                review_findings=[],
            )
        )

        self.assertEqual(
            prepared["currentOwnerParticipantId"],
            self.owner["id"],
        )
        self.assertEqual(
            prepared["workspacePolicy"],
            "shared_single_writer",
        )
        self.assertEqual(
            prepared["workspaceRoot"],
            str(self.workspace_root.resolve()),
        )
        self.assertEqual(
            prepared["reviewOfTaskIds"],
            ["task:settle"],
        )


    def test_reviewer_handoff_rejects_non_revision_intent(self) -> None:
        review_task = {
            **self.service.room_kernel.task("task:settle"),
            "taskKind": "review",
            "reviewState": "in_review",
        }
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P-2",
            intent="execute",
            nextTask="绕过复核链继续实现",
            expectedOutput="另一条实现结果",
            acceptanceAliases=["AC-1"],
        )

        with patch.object(
            self.service.room_kernel,
            "task",
            return_value=review_task,
        ):
            settled = self._settle()
        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("intent=revise", settled["reason"])

    def test_verified_isolated_child_must_deliver_before_integration(
        self,
    ) -> None:
        child_task = {
            **self.service.room_kernel.task("task:settle"),
            "parentTaskId": "task:parent",
            "workspacePolicy": "isolated_writable",
            "workspaceIntegrationState": "pending",
        }
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P1",
            intent="execute",
            nextTask="请 Facilitator 集成已经完成的独立工作区",
            expectedOutput="集成后的最终结果",
            acceptanceAliases=["AC-1"],
        )

        with patch.object(
            self.service.room_kernel,
            "task",
            return_value=child_task,
        ):
            settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("必须用 deliver 返回 Facilitator", settled["reason"])

    def test_receipted_clean_abandonment_does_not_block_final_delivery(
        self,
    ) -> None:
        root = self.service.room_kernel.root("root:settle")
        task = self.service.room_kernel.task("task:settle")
        dispatch = self.service.room_kernel.dispatch("dispatch:settle")
        abandoned = {
            "taskId": "task:abandoned-child",
            "state": "cancelled",
            "workspacePolicy": "isolated_writable",
            "workspaceLifecycleState": "abandoned",
            "workspaceCleanupState": "cleaned",
            "workspaceAttentionRequired": False,
            "workspaceIntegrationState": "pending",
        }
        child = {
            "taskId": "task:abandoned-child",
            "intentKind": "revise",
            "targetParticipantId": str(self.target["id"]),
            "resultPublic": False,
        }
        with (
            patch.object(
                self.service.room_kernel,
                "collaboration_children",
                return_value=[child],
            ),
            patch.object(
                self.service.room_kernel,
                "task",
                return_value=abandoned,
            ),
            patch.object(
                self.service.room_kernel,
                "task_has_canonical_abandonment",
                return_value=True,
            ),
        ):
            self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
                decision="deliver",
                root=root,
                task=task,
                dispatch=dispatch,
            )

        with (
            patch.object(
                self.service.room_kernel,
                "collaboration_children",
                return_value=[child],
            ),
            patch.object(
                self.service.room_kernel,
                "task",
                return_value=abandoned,
            ),
            patch.object(
                self.service.room_kernel,
                "task_has_canonical_abandonment",
                return_value=False,
            ),
            self.assertRaisesRegex(
                RoomCommitProposalError,
                "子任务没有完成",
            ),
        ):
            self.service.room_settle_lifecycle._assert_managed_collaboration_ready(
                decision="deliver",
                root=root,
                task=task,
                dispatch=dispatch,
            )


    def test_non_reviewer_handoff_rejects_revision_intent(self) -> None:
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P-2",
            intent="revise",
            nextTask="没有 Reviewer finding 的普通修正",
            expectedOutput="普通实现结果",
            acceptanceAliases=["AC-1"],
        )

        settled = self._settle()
        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn(
            "reserved for an active Reviewer",
            settled["reason"],
        )

    def test_wait_decision_moves_root_and_task_to_waiting(self) -> None:
        self._invoke_commit(
            "wait",
            waitingFor="user",
            resumeCondition="用户提供自由文本澄清",
            question="请补充必要信息。",
            questionKind="unbounded",
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
        self.assertEqual(
            self.service.room_kernel_snapshot(self.room_id)["posts"][0]["question"],
            {"prompt": "请补充必要信息。", "options": []},
        )

    def test_user_wait_preserves_completed_acceptance_evidence(self) -> None:
        self._invoke_commit(
            "wait",
            evidence=[
                {"acceptance": "AC-1", "refs": ["evidence:settle"]}
            ],
            waitingFor="user",
            resumeCondition="用户补充下一阶段所需选择",
            question="下一阶段采用哪个方向？",
            questionKind="unbounded",
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "committed")
        self.assertEqual(
            self.service.room_kernel.root("root:settle")["state"],
            "waiting",
        )
        receipt = settled["settleResult"]["receipt"]
        self.assertEqual(
            receipt["details"]["qualityGateVerdict"],
            "ready_to_deliver",
        )
        post = self.service.room_kernel_snapshot(self.room_id)["posts"][0]
        self.assertEqual(post["kind"], "wait")
        self.assertEqual(
            post["question"]["prompt"],
            "下一阶段采用哪个方向？",
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
            questionKind="bounded",
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
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "questionKind",
        ):
            settlement._canonical_question_options(
                None,
                decision="wait",
                waiting_for="user",
                question="采用哪个方案？",
                question_kind=None,
            )
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "bounded questions require",
        ):
            settlement._canonical_question_options(
                None,
                decision="wait",
                waiting_for="user",
                question="采用哪个方案？",
                question_kind="bounded",
            )
        self.assertIsNone(
            settlement._canonical_question_options(
                None,
                decision="wait",
                waiting_for="user",
                question="请描述你的目标。",
                question_kind="unbounded",
            )
        )
        cases = (
            {
                "value": options,
                "decision": "deliver",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "question_kind": "bounded",
                "message": "wait-for-user",
            },
            {
                "value": options,
                "decision": "wait",
                "waiting_for": "external",
                "question": "采用哪个方案？",
                "question_kind": "bounded",
                "message": "wait-for-user",
            },
            {
                "value": options[:1],
                "decision": "wait",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "question_kind": "bounded",
                "message": "between 2 and 5",
            },
            {
                "value": [*options, *options, *options],
                "decision": "wait",
                "waiting_for": "user",
                "question": "采用哪个方案？",
                "question_kind": "bounded",
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
                "question_kind": "bounded",
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
                "question_kind": "bounded",
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
                    question_kind=case["question_kind"],
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


    def test_repair_commit_allows_four_follow_ups_then_blocks(self) -> None:
        self._invoke_commit(
            "deliver",
            publicSummary=(
                "工作已完成；内部 rootId 为 root:settle，"
                "evidenceRef 为 evidence:settle。"
            ),
        )

        first = self._settle(1)
        replay = self._settle(1)
        second = self._settle(2)
        third = self._settle(3)
        fourth = self._settle(4)
        blocked = self._settle(5)

        self.assertEqual(first["state"], "repair_commit")
        self.assertTrue(first["followUpKey"])
        self.assertEqual(replay["guardReceipt"], first["guardReceipt"])
        self.assertEqual(second["state"], "repair_commit")
        self.assertEqual(third["state"], "repair_commit")
        self.assertEqual(fourth["state"], "repair_commit")
        self.assertEqual(fourth["guardReceipt"]["details"]["attempt"], 4)
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["guardReceipt"]["details"]["attempt"], 5)
        self.assertEqual(
            blocked["guardReceipt"]["details"]["maxAttempts"],
            5,
        )
        self.assertEqual(
            self.service.room_kernel.dispatch("dispatch:settle")["state"],
            "failed",
        )

    def test_repair_follow_ups_respect_budget_used_by_an_earlier_dispatch(self) -> None:
        self._invoke_commit(
            "deliver",
            publicSummary=(
                "工作已完成；内部 rootId 为 root:settle，"
                "evidenceRef 为 evidence:settle。"
            ),
        )
        with sqlite3.connect(self.service.room_kernel.db_path) as connection:
            connection.execute(
                "UPDATE room_kernel_root_limits SET repair_used=1 "
                "WHERE root_id='root:settle'"
            )

        first = self._settle(1)
        second = self._settle(2)
        third = self._settle(3)
        blocked = self._settle(4)

        self.assertEqual(first["state"], "repair_commit")
        self.assertEqual(second["state"], "repair_commit")
        self.assertEqual(third["state"], "repair_commit")
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["guardReceipt"]["details"]["attempt"], 4)
        self.assertEqual(blocked["guardReceipt"]["details"]["maxAttempts"], 4)
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

    def test_external_wait_for_one_workspace_retry_is_exact_participant_wait(
        self,
    ) -> None:
        _task_id, retry_dispatch_id = self._seed_workspace_retry()
        self._invoke_commit("wait")

        settled = self._settle()

        self.assertEqual(settled["state"], "committed")
        commit_id = str(
            settled["settleResult"]["receipt"]["details"]["commitId"]
        )
        continuation = self.service.room_kernel.continuation(commit_id)
        self.assertEqual(
            continuation["payload"]["waitingFor"],
            "participant",
        )
        self.assertEqual(
            continuation["payload"]["waitingForParticipantId"],
            self.target["id"],
        )
        self.assertEqual(
            continuation["payload"]["waitingForDispatchId"],
            retry_dispatch_id,
        )

    def test_old_external_wait_resumes_after_exact_workspace_retry_completes(
        self,
    ) -> None:
        task_id, retry_dispatch_id = self._seed_workspace_retry()
        self._invoke_commit("wait")
        with patch.object(
            self.service.room_kernel,
            "workspace_retry_wait_target",
            return_value=None,
        ):
            settled = self._settle()
        self.assertEqual(settled["state"], "committed")
        commit_id = str(
            settled["settleResult"]["receipt"]["details"]["commitId"]
        )
        self.assertEqual(
            self.service.room_kernel.continuation(commit_id)["payload"][
                "waitingFor"
            ],
            "external",
        )

        with sqlite3.connect(self.service.room_kernel.db_path) as connection:
            wait_created_at_ms = int(
                connection.execute(
                    "SELECT created_at_ms FROM room_kernel_continuations "
                    "WHERE commit_id=?",
                    (commit_id,),
                ).fetchone()[0]
            )
            task = self.service.room_kernel.task(task_id)
            completed_task = {
                **task,
                "workspaceLifecycleState": "delivered",
                "revision": int(task["revision"]) + 1,
                "state": "completed",
            }
            connection.execute(
                "UPDATE room_kernel_tasks SET state='completed',payload_json=? "
                "WHERE task_id=?",
                (
                    json.dumps(
                        completed_task,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    task_id,
                ),
            )
            connection.execute(
                "UPDATE room_kernel_dispatches "
                "SET state='committed',updated_at_ms=? "
                "WHERE dispatch_id=?",
                (wait_created_at_ms + 1, retry_dispatch_id),
            )
            connection.execute(
                "UPDATE room_kernel_outbox SET state='committed' "
                "WHERE dispatch_id=?",
                (retry_dispatch_id,),
            )

        resumed = self.service.room_kernel.pending_dispatch(
            now_ms=self.now_ms + 10,
        )
        self.assertIsNotNone(resumed)
        assert resumed is not None
        self.assertEqual(resumed["intentKind"], "resume")
        continuation = self.service.room_kernel.continuation(commit_id)
        self.assertEqual(continuation["state"], "resumed")
        self.assertEqual(continuation["childDispatchId"], resumed["dispatchId"])
        all_resumes = [
            item
            for item in self.service.room_kernel_snapshot(self.room_id)[
                "dispatches"
            ]
            if item["intentKind"] == "resume"
            and item["parentDispatchId"] == "dispatch:settle"
        ]
        self.assertEqual(len(all_resumes), 1)

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

    def test_missing_commit_continues_four_times_then_blocks_and_replays_exact_attempt(self) -> None:
        first = self._settle(1)
        first_replay = self._settle(1)
        second = self._settle(2)
        third = self._settle(3)
        fourth = self._settle(4)
        fifth = self._settle(5)
        fifth_replay = self._settle(5)

        self.assertEqual(first["state"], "continue")
        self.assertIn(
            '<room-work-follow-up source="system" kind="continue">',
            first["message"],
        )
        self.assertIn("不是用户提出了新需求", first["message"])
        self.assertIn("一次回答结束不等于工作完成", first["message"])
        self.assertIn("能产生新结果", first["message"])
        self.assertIn(
            "若没有这种新动作，立即选择 handoff、wait 或 blocked",
            first["message"],
        )
        self.assertIn("建议接手的伙伴或所需能力", first["message"])
        self.assertIn(
            "waitingFor=user 时才向用户提出一个最小必要问题",
            first["message"],
        )
        self.assertIn("可继续次数有限", first["message"])
        self.assertIn("不得重复同一失败动作", first["message"])
        self.assertTrue(first["followUpKey"])
        self.assertEqual(first_replay["guardReceipt"], first["guardReceipt"])
        self.assertEqual(second["guardReceipt"]["details"]["attempt"], 2)
        self.assertEqual(third["state"], "continue")
        self.assertEqual(fourth["state"], "continue")
        self.assertEqual(fifth["state"], "blocked")
        self.assertEqual(fifth_replay["guardReceipt"], fifth["guardReceipt"])
        self.assertEqual(fifth["guardReceipt"]["details"]["attempt"], 5)
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
        self.assertIn("当前工作卡片之外的验收短名", settled["reason"])
        self.assertIn('["AC-1"]', settled["message"])
        self.assertIn('kind="repair_commit"', settled["message"])
        self.assertIn("不要填写内部 criterionId", settled["message"])
        self.assertIn("不要自行填写 pass 或 verdict", settled["message"])
        self.assertIn(
            "如果自己无法继续且没有新的合法动作",
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
        staged = self._invoke_commit(
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
        self.assertIn("AC-1 使用了无法核实的 evidenceRef", settled["reason"])
        self.assertIn("删除这些位置的旧引用", settled["reason"])
        self.assertIn("最小成功工具结果", settled["reason"])
        invocation_id = str(staged["invocationReceipt"]["receiptId"])
        execution = self.service.room_capabilities.execution_receipt(
            invocation_id
        )
        self.assertIsNotNone(execution)
        assert execution is not None
        self.assertEqual(execution["status"], "rejected")
        replay = self._settle()
        self.assertEqual(replay["state"], "repair_commit")
        self.assertEqual(replay["guardReceipt"], settled["guardReceipt"])
        self.assertEqual(
            self.service.room_capabilities.execution_receipt(invocation_id)[
                "status"
            ],
            "rejected",
        )

    def test_final_aggregation_uses_exact_kernel_accepted_evidence(self) -> None:
        with patch.object(
            self.service.room_kernel,
            "accepted_evidence_by_criterion",
            return_value={"criterion:settle": ["evidence:settle"]},
        ):
            self._invoke_commit(
                "deliver",
                evidence=[
                    {
                        "acceptance": "AC-1",
                        "refs": ["evidence:settle-with-transcription-error"],
                    }
                ],
            )
            settled = self._settle()

        self.assertEqual(settled["state"], "committed", settled)
        receipt = settled["settleResult"]["receipt"]
        committed = self.service.room_kernel.commit(
            str(receipt["details"]["commitId"])
        )
        self.assertEqual(committed["evidenceRefs"], ["evidence:settle"])
        self.assertEqual(
            committed["qualityGateReceipt"]["items"][0]["evidenceRefs"],
            ["evidence:settle"],
        )

    def test_handoff_drops_unverifiable_refs_and_still_creates_review(self) -> None:
        current_evidence = self._record_workspace_evidence(
            session_id=self.session_id,
            suffix="handoff-prunes-stale",
        )
        self._invoke_commit(
            "handoff",
            targetParticipantRef="P1",
            intent="review",
            nextTask="独立复核当前结果",
            expectedOutput="复核结论",
            acceptanceAliases=["AC-1"],
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": [
                        "execution:stale-transcript-ref",
                        current_evidence,
                    ],
                }
            ],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "committed", settled)
        receipt = settled["settleResult"]["receipt"]
        self.assertEqual(receipt["details"]["settleDecision"], "dispatch")
        self.assertTrue(receipt["details"]["childTaskId"])
        self.assertTrue(receipt["details"]["childDispatchId"])
        committed = self.service.room_kernel.commit(
            str(receipt["details"]["commitId"])
        )
        self.assertEqual(
            committed["qualityGateReceipt"]["verdict"],
            "ready_to_deliver",
        )
        self.assertEqual(committed["evidenceRefs"], [current_evidence])

    def test_non_passing_quality_gate_cannot_deliver(self) -> None:
        self._invoke_commit(
            "deliver",
            evidence=[],
        )

        settled = self._settle()

        self.assertEqual(settled["state"], "repair_commit")
        self.assertIn("每个验收项都有成功工具结果支持", settled["reason"])

    def test_writer_quiescence_recovers_legacy_rejected_commit_invocation(
        self,
    ) -> None:
        staged = self._invoke_commit(
            "deliver",
            evidence=[
                {
                    "acceptance": "AC-1",
                    "refs": ["evidence:not-committed"],
                }
            ],
        )
        first = self._settle()
        self.assertEqual(first["state"], "repair_commit")
        invocation_id = str(staged["invocationReceipt"]["receiptId"])
        with sqlite3.connect(self.service.db_path) as conn:
            conn.execute(
                "DELETE FROM room_v2_tool_execution_receipts "
                "WHERE invocation_receipt_id=?",
                (invocation_id,),
            )

        self._invoke_commit("wait")
        committed = self._settle(attempt=2)
        self.assertEqual(committed["state"], "committed")

        quiescence = self.service._room_workspace_writer_quiescence(
            {
                "workspaceBindingId": "binding:legacy-rejected-commit",
                "rootId": "root:settle",
                "taskId": "task:settle",
                "dispatchId": "dispatch:settle",
                "ownerSessionId": self.session_id,
            }
        )
        foreground = quiescence["foregroundMutatingInvocations"]
        self.assertEqual(foreground["activeCount"], 0, foreground)
        self.assertEqual(
            foreground["settleRejectedInvocationReceiptIds"],
            [invocation_id],
        )


class RoomQualityGateDiagnosticTests(unittest.TestCase):
    def test_independent_review_prunes_stale_refs_when_current_proof_exists(
        self,
    ) -> None:
        criterion_id = "criterion:review"
        gate = canonicalize_quality_gate(
            evidence_proposal=[
                {
                    "acceptance": "AC-1",
                    "refs": [
                        "execution:current-review",
                        "execution:stale-one",
                        "execution:stale-two",
                    ],
                }
            ],
            residual_risks=[],
            decision="deliver",
            root_id="root:review-pruning",
            task_id="task:review-pruning",
            dispatch_id="dispatch:review-pruning",
            generation=0,
            task_criteria=(criterion_id,),
            acceptance_aliases={"AC-1": criterion_id},
            requirement_context={
                "originalRequirements": ["完成独立复核"],
                "catalog": {
                    "acceptanceCriteria": [
                        {"criterionId": criterion_id, "proofs": []}
                    ]
                },
            },
            accepted_evidence_by_criterion={},
            runtime_evidence_refs=["execution:current-review"],
            invocation_receipt_id="invoke:review-pruning",
            now_ms=100,
            prune_unverifiable_refs=True,
        )

        self.assertEqual(
            gate.evidence_refs,
            ("execution:current-review",),
        )
        self.assertEqual(
            gate.receipt["items"][0]["evidenceRefs"],
            ["execution:current-review"],
        )

    def test_independent_review_still_rejects_when_no_current_proof_exists(
        self,
    ) -> None:
        criterion_id = "criterion:review"
        with self.assertRaisesRegex(
            RoomQualityGateError,
            "无法核实的 evidenceRef",
        ):
            canonicalize_quality_gate(
                evidence_proposal=[
                    {
                        "acceptance": "AC-1",
                        "refs": ["execution:stale-only"],
                    }
                ],
                residual_risks=[],
                decision="deliver",
                root_id="root:review-pruning",
                task_id="task:review-pruning",
                dispatch_id="dispatch:review-pruning",
                generation=0,
                task_criteria=(criterion_id,),
                acceptance_aliases={"AC-1": criterion_id},
                requirement_context={
                    "originalRequirements": ["完成独立复核"],
                    "catalog": {
                        "acceptanceCriteria": [
                            {"criterionId": criterion_id, "proofs": []}
                        ]
                    },
                },
                accepted_evidence_by_criterion={},
                runtime_evidence_refs=[],
                invocation_receipt_id="invoke:review-pruning",
                now_ms=100,
                prune_unverifiable_refs=True,
            )

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
        self.assertIn("最新 room_state", message)
        self.assertIn("AC-2 的 refs 第 1 项", message)
        self.assertIn("AC-3 的 refs 第 1 项", message)
        self.assertIn("不要在新引用旁继续保留它们", message)
        self.assertNotIn("evidence:mistyped", message)


    def test_cross_criterion_refs_explain_how_to_unmerge_evidence(self) -> None:
        criteria = ("criterion:one", "criterion:two")
        with self.assertRaises(RoomQualityGateError) as raised:
            canonicalize_quality_gate(
                evidence_proposal=[
                    {
                        "acceptance": "AC-1",
                        "refs": ["evidence:accepted:two"],
                    }
                ],
                residual_risks=[],
                decision="deliver",
                root_id="root:misassigned",
                task_id="task:misassigned",
                dispatch_id="dispatch:misassigned",
                generation=0,
                task_criteria=criteria,
                acceptance_aliases={
                    "AC-1": criteria[0],
                    "AC-2": criteria[1],
                },
                requirement_context={
                    "originalRequirements": ["逐项验证两个验收条件"],
                    "catalog": {
                        "acceptanceCriteria": [
                            {"criterionId": criteria[0], "proofs": []},
                            {"criterionId": criteria[1], "proofs": []},
                        ]
                    },
                },
                accepted_evidence_by_criterion={
                    criteria[1]: ["evidence:accepted:two"]
                },
                runtime_evidence_refs=[],
                invocation_receipt_id="invoke:misassigned",
                now_ms=100,
            )

        message = str(raised.exception)
        self.assertIn("AC-1", message)
        self.assertIn("只属于其他验收项", message)
        self.assertIn("不要把多个 AC 的 refs 合并到一项", message)
        self.assertNotIn("evidence:accepted:two", message)


    def test_one_runtime_receipt_cannot_cover_multiple_acceptance_items(
        self,
    ) -> None:
        criteria = ("criterion:one", "criterion:two")
        with self.assertRaises(RoomQualityGateError) as raised:
            canonicalize_quality_gate(
                evidence_proposal=[
                    {
                        "acceptance": "AC-1",
                        "refs": ["execution:shared"],
                    },
                    {
                        "acceptance": "AC-2",
                        "refs": ["execution:shared"],
                    },
                ],
                residual_risks=[],
                decision="deliver",
                root_id="root:runtime-reuse",
                task_id="task:runtime-reuse",
                dispatch_id="dispatch:runtime-reuse",
                generation=0,
                task_criteria=criteria,
                acceptance_aliases={
                    "AC-1": criteria[0],
                    "AC-2": criteria[1],
                },
                requirement_context={
                    "originalRequirements": ["逐项验证两个验收条件"],
                    "catalog": {
                        "acceptanceCriteria": [
                            {"criterionId": criteria[0], "proofs": []},
                            {"criterionId": criteria[1], "proofs": []},
                        ]
                    },
                },
                accepted_evidence_by_criterion={},
                runtime_evidence_refs=["execution:shared"],
                invocation_receipt_id="invoke:runtime-reuse",
                now_ms=100,
            )

        message = str(raised.exception)
        self.assertIn("AC-1, AC-2", message)
        self.assertIn("每次成功工具执行只能直接证明一个验收项", message)
        self.assertNotIn("execution:shared", message)

    def test_shared_room_state_ref_uses_exact_accepted_child_evidence(
        self,
    ) -> None:
        criteria = ("criterion:one", "criterion:two")
        gate = canonicalize_quality_gate(
            evidence_proposal=[
                {
                    "acceptance": "AC-1",
                    "refs": ["execution:room-state"],
                },
                {
                    "acceptance": "AC-2",
                    "refs": ["execution:room-state"],
                },
            ],
            residual_risks=[],
            decision="deliver",
            root_id="root:accepted-child",
            task_id="task:accepted-child",
            dispatch_id="dispatch:accepted-child",
            generation=0,
            task_criteria=criteria,
            acceptance_aliases={
                "AC-1": criteria[0],
                "AC-2": criteria[1],
            },
            requirement_context={
                "originalRequirements": ["逐项验证两个验收条件"],
                "catalog": {
                    "acceptanceCriteria": [
                        {"criterionId": criteria[0], "proofs": []},
                        {"criterionId": criteria[1], "proofs": []},
                    ]
                },
            },
            accepted_evidence_by_criterion={
                criteria[0]: ["execution:accepted-one"],
                criteria[1]: ["execution:accepted-two"],
            },
            runtime_evidence_refs=["execution:room-state"],
            invocation_receipt_id="invoke:accepted-child",
            now_ms=100,
        )

        self.assertEqual(gate.receipt["verdict"], "ready_to_deliver")
        self.assertEqual(
            gate.evidence_refs,
            ("execution:accepted-one", "execution:accepted-two"),
        )
        self.assertEqual(
            [item["evidenceRefs"] for item in gate.receipt["items"]],
            [["execution:accepted-one"], ["execution:accepted-two"]],
        )

    def test_distinct_runtime_receipts_can_cover_distinct_acceptance_items(
        self,
    ) -> None:
        criteria = ("criterion:one", "criterion:two")
        gate = canonicalize_quality_gate(
            evidence_proposal=[
                {
                    "acceptance": "AC-1",
                    "refs": ["execution:one"],
                },
                {
                    "acceptance": "AC-2",
                    "refs": ["execution:two"],
                },
            ],
            residual_risks=[],
            decision="deliver",
            root_id="root:runtime-distinct",
            task_id="task:runtime-distinct",
            dispatch_id="dispatch:runtime-distinct",
            generation=0,
            task_criteria=criteria,
            acceptance_aliases={
                "AC-1": criteria[0],
                "AC-2": criteria[1],
            },
            requirement_context={
                "originalRequirements": ["逐项验证两个验收条件"],
                "catalog": {
                    "acceptanceCriteria": [
                        {"criterionId": criteria[0], "proofs": []},
                        {"criterionId": criteria[1], "proofs": []},
                    ]
                },
            },
            accepted_evidence_by_criterion={},
            runtime_evidence_refs=["execution:one", "execution:two"],
            invocation_receipt_id="invoke:runtime-distinct",
            now_ms=100,
        )

        self.assertEqual(gate.receipt["verdict"], "ready_to_deliver")
        self.assertEqual(gate.requirement_coverage, criteria)


class ReviewFindingAdmissibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RoomSettleLifecycleService.__new__(
            RoomSettleLifecycleService
        )
        self.service.rooms = _ReviewFindingRooms()
        self.task = {
            "taskKind": "review",
            "reviewTargetRevision": f"sha256:{'a' * 64}",
            "reviewRound": 1,
            "reviewFindings": [],
        }

    @staticmethod
    def _finding(
        *,
        gate_effect: str = "blocking",
        impact: str = "critical",
        category: str = "correctness",
        scope: dict[str, object] | None = None,
        state: str = "open",
    ) -> dict[str, object]:
        finding: dict[str, object] = {
            "findingId": "Finding-1",
            "gateEffect": gate_effect,
            "impact": impact,
            "category": category,
            "scope": scope or {"acceptance": "AC-1"},
            "observation": "复核发现一个可复现问题",
            "expected": "当前验收条件与治理约束必须保持成立",
            "userImpact": "可能导致用户收到错误结果",
            "evidenceRefs": ["evidence:review"],
            "reproduction": ["运行独立复核检查"],
            "state": state,
        }
        if state in {"dismissed", "accepted_risk"}:
            finding["dispositionRationale"] = "已明确处置并记录原因"
        return finding

    def _canonical(
        self,
        finding: dict[str, object],
        *,
        decision: str,
    ) -> list[dict[str, object]]:
        return self.service._canonical_review_findings(
            value=[finding],
            task=self.task,
            root={"roomId": "room:admissibility"},
            decision=decision,
            acceptance_aliases={"AC-1": "criterion:one"},
            evidence_refs=["evidence:review"],
            runtime_evidence_refs={"evidence:review"},
        )

    def test_deliver_without_findings_normalizes_to_empty_array(self) -> None:
        self.assertEqual(
            self.service._canonical_review_findings(
                value=None,
                task=self.task,
                root={"roomId": "room:admissibility"},
                decision="deliver",
                acceptance_aliases={"AC-1": "criterion:one"},
                evidence_refs=["evidence:review"],
                runtime_evidence_refs={"evidence:review"},
            ),
            [],
        )

    def test_deliver_cannot_omit_prior_open_p0_findings(self) -> None:
        self.task["reviewFindings"] = [self._finding()]

        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "complete reviewFindings array",
        ):
            self.service._canonical_review_findings(
                value=None,
                task=self.task,
                root={"roomId": "room:admissibility"},
                decision="deliver",
                acceptance_aliases={"AC-1": "criterion:one"},
                evidence_refs=["evidence:review"],
                runtime_evidence_refs={"evidence:review"},
            )

    def test_non_p0_requested_blockers_are_recorded_as_advisory(self) -> None:
        normal = self._canonical(
            self._finding(impact="normal"),
            decision="deliver",
        )
        maintainability = self._canonical(
            self._finding(
                impact="high",
                category="maintainability",
            ),
            decision="deliver",
        )

        self.assertEqual(normal[0]["gateEffect"], "advisory")
        self.assertEqual(normal[0]["impact"], "normal")
        self.assertEqual(
            maintainability[0]["gateEffect"],
            "advisory",
        )
        self.assertEqual(maintainability[0]["impact"], "high")
        self.assertIn(
            "Advisory",
            str(maintainability[0]["dispositionRationale"]),
        )

    def test_static_finding_field_errors_are_reported_together(self) -> None:
        findings = [
            {
                **self._finding(),
                "findingId": "Finding-evidence",
                "evidenceRefs": [],
            },
            {
                **self._finding(),
                "findingId": "Finding-impact",
                "impact": "severe",
            },
            {
                **self._finding(),
                "findingId": "Finding-category",
                "category": "unknown",
            },
            {
                **self._finding(),
                "findingId": "Finding-gate-effect",
                "gateEffect": "stop",
            },
        ]

        with self.assertRaises(RoomCommitProposalError) as raised:
            self.service._canonical_review_findings(
                value=findings,
                task=self.task,
                root={"roomId": "room:admissibility"},
                decision="handoff",
                acceptance_aliases={"AC-1": "criterion:one"},
                evidence_refs=["evidence:review"],
                runtime_evidence_refs={"evidence:review"},
            )

        message = str(raised.exception)
        self.assertIn(
            "reviewFindings[0].evidenceRefs must not be empty",
            message,
        )
        self.assertIn("reviewFindings[1].impact is invalid", message)
        self.assertIn("reviewFindings[2].category is invalid", message)
        self.assertIn("reviewFindings[3].gateEffect is invalid", message)

    def test_static_finding_field_feedback_is_bounded(self) -> None:
        findings = [
            {
                **self._finding(),
                "findingId": f"Finding-{index}",
                "impact": "severe",
            }
            for index in range(9)
        ]

        with self.assertRaises(RoomCommitProposalError) as raised:
            self.service._canonical_review_findings(
                value=findings,
                task=self.task,
                root={"roomId": "room:admissibility"},
                decision="handoff",
                acceptance_aliases={"AC-1": "criterion:one"},
                evidence_refs=["evidence:review"],
                runtime_evidence_refs={"evidence:review"},
            )

        message = str(raised.exception)
        self.assertEqual(message.count(".impact is invalid"), 8)
        self.assertNotIn("reviewFindings[8].impact is invalid", message)

    def test_blocker_invariant_scope_must_be_governed(self) -> None:
        non_governed = self._canonical(
            self._finding(scope={"invariantId": "opinion:clean-code"}),
            decision="deliver",
        )
        self.assertEqual(non_governed[0]["gateEffect"], "advisory")

        canonical = self._canonical(
            self._finding(
                category="security",
                scope={"invariantId": "room-governance:security"},
            ),
            decision="handoff",
        )
        self.assertEqual(canonical[0]["gateEffect"], "blocking")
        self.assertEqual(
            canonical[0]["scope"],
            {"invariantId": "room-governance:security"},
        )

    def test_open_advisory_is_delivered_with_notes(self) -> None:
        open_advisory = self._canonical(
            self._finding(
                gate_effect="advisory",
                impact="normal",
                category="maintainability",
            ),
            decision="deliver",
        )
        self.assertEqual(open_advisory[0]["state"], "open")
        self.assertEqual(open_advisory[0]["gateEffect"], "advisory")

        canonical = self._canonical(
            self._finding(
                gate_effect="advisory",
                impact="normal",
                category="maintainability",
                state="dismissed",
            ),
            decision="deliver",
        )
        self.assertEqual(canonical[0]["state"], "dismissed")

    def test_blocking_terminal_state_requires_fix_or_arbiter_lineage(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "verified fix lineage",
        ):
            self._canonical(
                self._finding(state="resolved"),
                decision="deliver",
            )
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "independent arbiter",
        ):
            self._canonical(
                self._finding(state="dismissed"),
                decision="deliver",
            )


class ReviewScopeLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RoomSettleLifecycleService.__new__(
            RoomSettleLifecycleService
        )
        self.service.rooms = _ReviewFindingRooms()
        self.task = {
            "taskKind": "review",
            "reviewTargetRevision": f"sha256:{'a' * 64}",
            "reviewRound": 2,
            "reviewFindings": [
                {
                    "findingId": "Finding-1",
                    "fingerprint": f"sha256:{'b' * 64}",
                    "gateEffect": "blocking",
                    "impact": "critical",
                    "category": "correctness",
                    "scope": {"criterionId": "criterion:one"},
                    "state": "resolved",
                    "failedRechecks": 0,
                    "response": {"action": "fixed"},
                }
            ],
        }

    def _finding(
        self,
        *,
        category: str,
        acceptance: str,
    ) -> dict[str, object]:
        return {
            "findingId": "Finding-2",
            "gateEffect": "blocking",
            "impact": "critical",
            "category": category,
            "scope": {"acceptance": acceptance},
            "observation": "后续复核发现一个新问题",
            "expected": "该问题应满足既定要求",
            "userImpact": "可能影响用户结果",
            "evidenceRefs": ["evidence:late"],
            "reproduction": ["执行后续复核检查"],
            "state": "open",
        }

    def _canonical(
        self,
        finding: dict[str, object],
        *,
        decision: str,
    ) -> list[dict[str, object]]:
        return self.service._canonical_review_findings(
            value=[finding],
            task=self.task,
            root={"roomId": "room:scope-lock"},
            decision=decision,
            acceptance_aliases={
                "AC-1": "criterion:one",
                "AC-2": "criterion:two",
            },
            evidence_refs=["evidence:late"],
            runtime_evidence_refs={"evidence:late"},
        )
    def test_late_unrelated_blocker_becomes_non_blocking_advisory(
        self,
    ) -> None:
        finding = self._finding(category="ux", acceptance="AC-2")

        open_advisory = self._canonical(finding, decision="deliver")
        self.assertEqual(open_advisory[0]["gateEffect"], "advisory")
        self.assertEqual(open_advisory[0]["state"], "open")
        disposed = {
            **finding,
            "state": "dismissed",
            "dispositionRationale": "不属于当前验收范围，明确转入 backlog",
        }
        canonical = self._canonical(disposed, decision="deliver")

        self.assertEqual(canonical[0]["gateEffect"], "advisory")
        self.assertEqual(canonical[0]["impact"], "normal")
        self.assertIn(
            "明确转入 backlog",
            str(canonical[0]["dispositionRationale"]),
        )
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "requires an open Blocking Finding",
        ):
            self._canonical(finding, decision="handoff")

    def test_late_repair_scope_and_safety_exception_can_still_block(
        self,
    ) -> None:
        repaired_scope = self._canonical(
            self._finding(category="correctness", acceptance="AC-1"),
            decision="handoff",
        )
        safety_exception = self._canonical(
            self._finding(category="security", acceptance="AC-2"),
            decision="handoff",
        )

        self.assertEqual(repaired_scope[0]["gateEffect"], "blocking")
        self.assertEqual(safety_exception[0]["gateEffect"], "blocking")


class ReviewFindingContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RoomSettleLifecycleService.__new__(
            RoomSettleLifecycleService
        )
        self.service.rooms = _ReviewFindingRooms()
        self.target_revision = f"sha256:{'a' * 64}"
        self.finding = {
            "findingId": "Finding-1",
            "gateEffect": "blocking",
            "impact": "critical",
            "category": "correctness",
            "scope": {"acceptance": "AC-1"},
            "observation": "边界输入仍返回旧值",
            "expected": "边界输入返回新值",
            "userImpact": "用户会收到错误结果",
            "evidenceRefs": ["evidence:review"],
            "reproduction": ["运行边界输入检查"],
            "state": "open",
        }
        self.fingerprint = (
            "sha256:"
            + settlement._sha256_json(
                {
                    "category": self.finding["category"],
                    "scope": {"criterionId": "criterion:one"},
                    "observation": self.finding["observation"],
                    "expected": self.finding["expected"],
                    "userImpact": self.finding["userImpact"],
                }
            )
        )
        self.task = {
            "taskKind": "review",
            "reviewTargetRevision": self.target_revision,
            "reviewRound": 2,
            "reviewFindings": [
                {
                    **self.finding,
                    "scope": {"criterionId": "criterion:one"},
                    "fingerprint": self.fingerprint,
                    "firstSeenRevision": f"sha256:{'b' * 64}",
                    "lastCheckedRevision": f"sha256:{'c' * 64}",
                    "failedRechecks": 0,
                    "response": {"action": "fixed"},
                }
            ],
        }

    def _canonical(
        self,
        value: object,
        *,
        decision: str,
    ) -> list[dict[str, object]]:
        return self.service._canonical_review_findings(
            value=value,
            task=self.task,
            root={"roomId": "room:continuity"},
            decision=decision,
            acceptance_aliases={"AC-1": "criterion:one"},
            evidence_refs=["evidence:review"],
            runtime_evidence_refs={"evidence:review"},
        )

    def test_round_two_regression_remains_a_blocking_finding(self) -> None:
        self.task["reviewFindings"] = []
        finding = {
            **self.finding,
            "findingId": "Finding-2",
            "category": "regression",
            "scope": {"acceptance": "AC-1"},
        }
        canonical = self._canonical([finding], decision="handoff")
        self.assertEqual(canonical[0]["category"], "regression")
        self.assertEqual(canonical[0]["gateEffect"], "blocking")

    def test_re_review_omission_changed_id_and_content_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "every prior open Blocking Finding",
        ):
            self._canonical([], decision="handoff")

        changed_id = {**self.finding, "findingId": "Finding-2"}
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "every prior open Blocking Finding",
        ):
            self._canonical([changed_id], decision="handoff")

        changed_content = {
            **self.finding,
            "observation": "边界输入仍返回旧值，且错误被静默吞掉",
        }
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "findingId and fingerprint",
        ):
            self._canonical([changed_content], decision="handoff")

    def test_verified_resolution_is_the_only_blocker_removal(self) -> None:
        resolved = {**self.finding, "state": "resolved"}
        canonical = self._canonical([resolved], decision="deliver")
        self.assertEqual(canonical[0]["findingId"], "Finding-1")
        self.assertEqual(canonical[0]["fingerprint"], self.fingerprint)
        self.assertEqual(canonical[0]["state"], "resolved")

    def test_contested_prior_is_retained_as_blocking(self) -> None:
        self.task["reviewFindings"][0]["state"] = "contested"
        self.task["reviewFindings"][0]["response"] = {
            "action": "contest"
        }
        canonical = self._canonical([self.finding], decision="handoff")
        self.assertEqual(canonical[0]["state"], "contested")
        self.assertEqual(canonical[0]["gateEffect"], "blocking")


class ReviewEvidenceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.review_task = {
            "taskId": "task:review",
            "reviewTargetRevision": f"sha256:{'a' * 64}",
            "reviewEvidenceNotBeforeMs": 42,
        }
        self.review_dispatch = {
            "dispatchId": "dispatch:review",
            "intentKind": "review",
            "taskId": "task:review",
        }
        self.commit: dict[str, object] = {
            "qualityGateReceipt": {
                "items": [
                    {
                        "status": "pass",
                        "evidenceRefs": ["execution:review"],
                    }
                ]
            }
        }
        self.service = RoomSettleLifecycleService.__new__(
            RoomSettleLifecycleService
        )
        self.service.kernel = _ReviewEvidenceKernel(
            dispatch=self.review_dispatch,
            task=self.review_task,
            commit=self.commit,
        )
        self.arguments = {
            "decision": "deliver",
            "root": {
                "rootId": "root:review",
                "facilitatorParticipantId": "participant:facilitator",
            },
            "task": {"parentTaskId": None},
            "dispatch": {
                "targetParticipantId": "participant:facilitator",
            },
            "evidence_refs": ["execution:review"],
        }

    def test_final_delivery_rejects_unbound_review_evidence(self) -> None:
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "reviewTargetRevision",
        ):
            self.service._assert_review_evidence_ready(**self.arguments)

    def test_final_delivery_accepts_exact_revision_evidence_binding(self) -> None:
        self.commit["reviewEvidenceBinding"] = {
            "reviewTargetRevision": self.review_task[
                "reviewTargetRevision"
            ],
            "taskId": "task:review",
            "dispatchId": "dispatch:review",
            "evidenceRefs": ["execution:review"],
            "notBeforeMs": 42,
        }

        self.service._assert_review_evidence_ready(**self.arguments)


class RoleCommitDecisionFenceTests(unittest.TestCase):
    """`allowedCommitDecisions` must be a fence, not catalog prose.

    Reviewer handoff is now a governed revision path back to the Facilitator;
    the manifest still remains the authoritative set of legal lifecycle exits.
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

    def test_every_builtin_role_enforces_its_declared_exits(self) -> None:
        service = RoomSettleLifecycleService.__new__(RoomSettleLifecycleService)
        for role_id in ("coordinator", "researcher", "implementer", "reviewer", "specialist"):
            service.rooms = _StubRooms(role_id=role_id)
            allowed = set(collaboration_role(role_id).allowed_commit_decisions)
            for decision in ("deliver", "handoff", "wait", "blocked"):
                with self.subTest(role=role_id, decision=decision):
                    if decision in allowed:
                        service._assert_decision_allowed(
                            decision, {"targetParticipantId": f"participant:{role_id}"}
                        )
                    else:
                        with self.assertRaises(RoomCommitProposalError):
                            service._assert_decision_allowed(
                                decision,
                                {"targetParticipantId": f"participant:{role_id}"},
                            )


class ReviewerHandoffAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facilitator_id = "participant:facilitator"
        self.reviewer_id = "participant:reviewer"
        self.foreign_id = "participant:foreign"
        self.participants = [
            {
                "id": self.reviewer_id,
                "status": "active",
                "collaborationRole": "reviewer",
            },
            {
                "id": self.facilitator_id,
                "status": "active",
                "collaborationRole": "coordinator",
            },
            {
                "id": self.foreign_id,
                "status": "active",
                "collaborationRole": "implementer",
            },
        ]
        self.service = RoomSettleLifecycleService.__new__(
            RoomSettleLifecycleService
        )
        self.service.rooms = _ReviewerHandoffRooms(self.participants)
        self.service.kernel = _ReviewerHandoffKernel(
            dispatch={
                "dispatchId": "dispatch:review",
                "taskId": "task:review",
                "rootId": "root:review",
                "targetParticipantId": self.reviewer_id,
                "intentKind": "review",
            },
            task={
                "taskId": "task:review",
                "rootId": "root:review",
                "taskKind": "review",
                "parentTaskId": "task:root",
                "reviewTargetRevision": f"sha256:{'a' * 64}",
                "reviewOfTaskIds": ["task:root"],
                "reviewEvidenceNotBeforeMs": 10,
                "workspacePolicy": "read_only",
            },
            root={
                "rootId": "root:review",
                "roomId": "room:review",
                "facilitatorParticipantId": self.facilitator_id,
            },
        )

    def _invoke(
        self,
        *,
        intent: str,
        target_ref: str = "P2",
    ) -> None:
        with self.assertRaisesRegex(
            RoomCommitProposalError,
            "Reviewer handoff|Root Facilitator",
        ):
            self.service._canonical_commit(
                manifest={
                    "dispatchId": "dispatch:review",
                    "rootId": "root:review",
                },
                invocation={
                    "receiptId": "invoke:review-handoff",
                    "canonicalCommand": {
                        "arguments": {
                            "decision": "handoff",
                            "summary": "带证据交回修正",
                            "intent": intent,
                            "targetParticipantRef": target_ref,
                        }
                    },
                },
                now_ms=20,
            )

    def test_every_non_revise_reviewer_intent_is_rejected(self) -> None:
        for intent in (
            "execute",
            "review",
            "resume",
            "retry",
            "callback",
            "close",
        ):
            with self.subTest(intent=intent):
                self._invoke(intent=intent)

    def test_revise_to_any_non_facilitator_is_rejected(self) -> None:
        self._invoke(intent="revise", target_ref="P3")


class _ReviewerHandoffKernel:
    def __init__(
        self,
        *,
        dispatch: dict[str, object],
        task: dict[str, object],
        root: dict[str, object],
    ) -> None:
        self._dispatch = dispatch
        self._task = task
        self._root = root

    def dispatch(self, _dispatch_id: str) -> dict[str, object]:
        return self._dispatch

    def task(self, _task_id: str) -> dict[str, object]:
        return self._task

    def root(self, _root_id: str) -> dict[str, object]:
        return self._root


class _ReviewerHandoffRooms:
    def __init__(self, participants: list[dict[str, object]]) -> None:
        self._participants = participants

    def participant(self, participant_id: str) -> dict[str, object]:
        return next(
            participant
            for participant in self._participants
            if participant["id"] == participant_id
        )

    def get(self, _room_id: str) -> dict[str, object]:
        return {"participants": self._participants}


class _ReviewEvidenceKernel:
    def __init__(
        self,
        *,
        dispatch: dict[str, object],
        task: dict[str, object],
        commit: dict[str, object],
    ) -> None:
        self.dispatch = dispatch
        self.review_task = task
        self.commit = commit

    def collaboration_children(
        self,
        _root_id: str,
    ) -> list[dict[str, object]]:
        return [self.dispatch]

    def task(self, _task_id: str) -> dict[str, object]:
        return self.review_task

    def latest_task_commit(
        self,
        _task_id: str,
    ) -> dict[str, object]:
        return self.commit

    def latest_review_attempt(
        self,
        _root_id: str,
    ) -> dict[str, object]:
        return {
            "taskId": str(self.review_task["taskId"]),
            "taskState": str(self.review_task.get("state") or ""),
            "payload": self.review_task,
            "dispatch": self.dispatch,
            "commit": self.commit,
            "commitId": str(self.commit.get("commitId") or ""),
            "resultPublic": True,
        }


class _ReviewFindingRooms:
    @staticmethod
    def get(_room_id: str) -> dict[str, object]:
        return {"participants": []}


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
