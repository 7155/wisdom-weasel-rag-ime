#!/usr/bin/env python3
"""Run one real A -> (B collaboration, C handoff) Room project with auditable context."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from room_context_epoch_canary import (
    JsonRequester,
    accepted_root_id,
    cancel_root,
    debug_evidence,
    encoded,
    latest_transition,
    progressive_discovery_check,
    request_json,
    tool_receipt_evidence,
    transcript_evidence,
)
from room_project_task_canary import (
    MISSING_READ_PATH,
    TEST_COMMAND,
    _approved_project_source,
    _independent_project_verification,
)


SCHEMA_VERSION = "wisdom-weasel.room-three-member-canary.v2"
MARKERS = {
    "A": "COLLAB-A-IMPLEMENTED",
    "B": "COLLAB-B-REVIEWED",
    "C": "COLLAB-C-ACCEPTED",
}
COMMIT_RESULTS = {
    "A": "COLLAB-A-COMMIT-RESULT",
    "B": "COLLAB-B-COMMIT-RESULT",
    "C": "COLLAB-C-COMMIT-RESULT",
}
EXPECTED_SKILLS = {
    "A": "room-test-driven-implementation",
    "B": "room-independent-vision-review",
    "C": "room-delivery-closure",
}
EXPECTED_INTENTS = ("execute", "review", "close")
SESSION_CONTINUITY_PROMPT = "SESSION-CONTINUITY-AFTER-ROOM"
SESSION_CONTINUITY_REPLY = "SESSION-CONTINUITY-OK"
_PROJECT_MEMORY_SIGNAL_GROUPS = (
    ("代码任务",),
    ("最小改动", "最小修改"),
    ("测试",),
    ("交付", "证据"),
)


def _is_useful_project_memory(block: str) -> bool:
    """Require concrete code-delivery preferences, not a retrieval score."""

    return all(
        any(signal in block for signal in alternatives)
        for alternatives in _PROJECT_MEMORY_SIGNAL_GROUPS
    )


def bounded_useful_rag_check(
    contexts: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Require useful recalled blocks while allowing a true zero-hit member."""

    memories = [
        value.get("sessionMemory")
        if isinstance(value.get("sessionMemory"), Mapping)
        else {}
        for value in contexts.values()
    ]
    return (
        any(int(memory.get("blockCount") or 0) > 0 for memory in memories)
        and all(
            not memory.get("forbiddenMetadata")
            and all(
                _is_useful_project_memory(str(block))
                for block in memory.get("blocks") or []
            )
            for memory in memories
        )
    )


def _configure_session(
    base_url: str,
    *,
    requester: JsonRequester,
    session_id: str,
    model_provider: str,
    model_id: str,
    thinking_level: str,
) -> None:
    if model_provider and model_id:
        requester(
            base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/model",
            {"provider": model_provider, "modelId": model_id},
        )
    if thinking_level:
        requester(
            base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/thinking",
            {"level": thinking_level},
        )


def _root_snapshot(
    snapshot: dict[str, Any],
    root_id: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    roots = [
        item
        for item in snapshot.get("roots") or []
        if isinstance(item, dict) and item.get("rootId") == root_id
    ]
    dispatches = [
        item
        for item in snapshot.get("dispatches") or []
        if isinstance(item, dict) and item.get("rootId") == root_id
    ]
    dispatches.sort(
        key=lambda item: (
            int(item.get("hopCount") or 0),
            str(item.get("dispatchId") or ""),
        )
    )
    task_by_id = {
        str(item.get("taskId") or ""): item
        for item in snapshot.get("tasks") or []
        if isinstance(item, dict) and item.get("rootId") == root_id
    }
    tasks = [
        task_by_id[str(item.get("taskId") or "")]
        for item in dispatches
        if str(item.get("taskId") or "") in task_by_id
    ]
    return roots, tasks, dispatches


def wait_for_three_member_settlement(
    base_url: str,
    room_id: str,
    root_id: str,
    *,
    requester: JsonRequester,
    sessions: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    pending_first_seen: dict[str, float] = {}
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        active_pending_ids: set[str] = set()
        for member, session_id in sessions.items():
            pending = requester(
                base_url,
                "GET",
                f"/api/agent/approvals?sessionId={encoded(session_id)}&state=pending&limit=20",
                timeout=10,
            )
            now = time.monotonic()
            stale_pending = []
            for item in pending.get("items") or []:
                if not isinstance(item, dict):
                    continue
                approval_id = str(item.get("approvalId") or "")
                if not approval_id:
                    continue
                active_pending_ids.add(approval_id)
                first_seen = pending_first_seen.setdefault(
                    approval_id,
                    now,
                )
                if now - first_seen >= 5:
                    stale_pending.append(item)
            if stale_pending:
                raise RuntimeError(
                    "workspace-managed Room approval remained pending beyond "
                    "the automatic execution grace period: "
                    f"member={member} approvals={stale_pending}"
                )
        pending_first_seen = {
            approval_id: first_seen
            for approval_id, first_seen in pending_first_seen.items()
            if approval_id in active_pending_ids
        }
        snapshot = requester(
            base_url,
            "GET",
            f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
            timeout=10,
        )
        roots, tasks, dispatches = _root_snapshot(snapshot, root_id)
        states = [str(item.get("state") or "") for item in dispatches]
        last = {
            "rootState": str(roots[0].get("state") or "") if roots else "",
            "dispatchStates": states,
            "dispatchIds": [str(item.get("dispatchId") or "") for item in dispatches],
            "dispatchCount": len(dispatches),
            "taskCount": len(tasks),
        }
        if len(dispatches) > 3:
            raise RuntimeError(f"Room collaboration created extra Dispatches: {last}")
        failed = [state for state in states if state in {"blocked", "failed", "cancelled"}]
        if failed:
            raise RuntimeError(f"Room collaboration terminated before delivery: {last}")
        if len(dispatches) == 3 and states == ["committed", "committed", "committed"]:
            return {
                **last,
                "snapshot": snapshot,
                "tasks": tasks,
                "dispatches": dispatches,
            }
        if last["rootState"] in {
            "blocked",
            "waiting",
            "completed",
            "failed",
            "cancelled",
            "cancelled_with_unknowns",
        }:
            raise RuntimeError(f"Room collaboration Root terminated with an incomplete chain: {last}")
        time.sleep(0.1)
    raise TimeoutError(f"Room collaboration did not settle: {last}")


def managed_approval_evidence(
    base_url: str,
    *,
    requester: JsonRequester,
    session_ids: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for member, session_id in session_ids.items():
        listed = requester(
            base_url,
            "GET",
            f"/api/agent/approvals?sessionId={encoded(session_id)}&limit=100",
            timeout=10,
        )
        items = [
            dict(item)
            for item in listed.get("items") or []
            if isinstance(item, dict)
        ]
        items.sort(
            key=lambda item: (
                int(item.get("requestedAtMs") or 0),
                str(item.get("approvalId") or ""),
            )
        )
        result[member] = items
    return result


def managed_approval_checks(
    approvals: dict[str, list[dict[str, Any]]],
) -> dict[str, bool]:
    expected = {
        "A": [
            ("workspace_shell", "failed"),
            ("workspace_patch", "applied"),
            ("workspace_shell", "applied"),
        ],
        "B": [],
        "C": [("workspace_shell", "applied")],
    }
    actual = {
        member: [
            (str(item.get("toolId") or ""), str(item.get("state") or ""))
            for item in approvals.get(member, [])
        ]
        for member in ("A", "B", "C")
    }
    return {
        "exactToolsAndStates": actual == expected,
        "policyOwned": all(
            str(item.get("decidedBy") or "")
            == "execution-policy:workspace_managed"
            for values in approvals.values()
            for item in values
        ),
        "nothingPending": all(
            str(item.get("state") or "") != "pending"
            for values in approvals.values()
            for item in values
        ),
        "receiptsPresent": all(
            isinstance(item.get("receipt"), dict)
            for values in approvals.values()
            for item in values
        ),
    }


def dispatch_chain_evidence(
    tasks: list[dict[str, Any]],
    dispatches: list[dict[str, Any]],
    *,
    participant_ids: dict[str, str],
    session_ids: dict[str, str],
) -> dict[str, Any]:
    ordered_members = ("A", "B", "C")
    if len(dispatches) != len(ordered_members) or len(tasks) != len(ordered_members):
        return {
            "passed": False,
            "reason": "task_or_dispatch_count",
            "tasks": tasks,
            "items": dispatches,
        }
    dispatch_by_member = {
        member: next(
            (
                item
                for item in dispatches
                if str(item.get("targetParticipantId") or "")
                == participant_ids[member]
                and str(item.get("targetSessionId") or "") == session_ids[member]
            ),
            None,
        )
        for member in ordered_members
    }
    if any(item is None for item in dispatch_by_member.values()):
        return {
            "passed": False,
            "reason": "member_dispatch_binding",
            "tasks": tasks,
            "items": dispatches,
        }
    ordered_dispatches = [dispatch_by_member[member] for member in ordered_members]
    assert all(item is not None for item in ordered_dispatches)
    dispatch_items = [item for item in ordered_dispatches if item is not None]
    task_by_id = {str(item.get("taskId") or ""): item for item in tasks}
    ordered_tasks = [
        task_by_id.get(str(item.get("taskId") or "")) for item in dispatch_items
    ]
    if any(item is None for item in ordered_tasks):
        return {
            "passed": False,
            "reason": "member_task_binding",
            "tasks": tasks,
            "items": dispatches,
        }
    task_items = [item for item in ordered_tasks if item is not None]
    ids = [str(item.get("dispatchId") or "") for item in dispatch_items]
    task_ids = [str(item.get("taskId") or "") for item in task_items]
    checks = {
        "targets": [str(item.get("targetParticipantId") or "") for item in dispatch_items]
        == [participant_ids[member] for member in ordered_members],
        "sessions": [str(item.get("targetSessionId") or "") for item in dispatch_items]
        == [session_ids[member] for member in ordered_members],
        "parents": [item.get("parentDispatchId") for item in dispatch_items]
        == [None, ids[0], ids[0]],
        "taskBindings": [str(item.get("taskId") or "") for item in dispatch_items]
        == task_ids,
        "distinctTasks": len(set(task_ids)) == 3,
        "taskParents": [item.get("parentTaskId") for item in task_items]
        == [None, task_ids[0], task_ids[0]],
        # A collaboration keeps responsibility with the caller while assigning
        # the child work to the peer. A formal handoff transfers both ownership
        # and assignment. Treating both paths as ownership transfer would hide
        # the exact semantic difference this canary is meant to prove.
        "taskOwners": [str(item.get("ownerParticipantId") or "") for item in task_items]
        == [participant_ids["A"], participant_ids["A"], participant_ids["C"]],
        "taskAssignees": [
            str(item.get("assigneeParticipantId") or "") for item in task_items
        ]
        == [participant_ids[member] for member in ordered_members],
        "tasksCompleted": [str(item.get("state") or "") for item in task_items]
        == ["completed", "completed", "completed"],
        "hops": [int(item.get("hopCount") or 0) for item in dispatch_items] == [0, 1, 1],
        "depths": [int(item.get("depth") or 0) for item in dispatch_items] == [0, 1, 0],
        "intents": [str(item.get("intentKind") or "") for item in dispatch_items]
        == list(EXPECTED_INTENTS),
        "committed": [str(item.get("state") or "") for item in dispatch_items]
        == ["committed", "committed", "committed"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "items": [
            {
                "member": member,
                "taskId": task_ids[index],
                "parentTaskId": task_items[index].get("parentTaskId"),
                "taskState": task_items[index].get("state"),
                "dispatchId": ids[index],
                "parentDispatchId": dispatch_items[index].get("parentDispatchId"),
                "hopCount": dispatch_items[index].get("hopCount"),
                "depth": dispatch_items[index].get("depth"),
                "intentKind": dispatch_items[index].get("intentKind"),
                "state": dispatch_items[index].get("state"),
                "capabilityEpoch": dispatch_items[index].get("capabilityEpoch"),
            }
            for index, member in enumerate(ordered_members)
        ],
    }


def skill_receipt_evidence(
    db_path: Path,
    dispatches: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    dispatch_ids = [str(item.get("dispatchId") or "") for item in dispatches]
    placeholders = ",".join("?" for _ in dispatch_ids)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT receipt_id, dispatch_id, session_id, skill_id, skill_hash,
                   load_reason, capability_epoch, state
            FROM room_v2_skill_load_receipts
            WHERE dispatch_id IN ({placeholders})
            ORDER BY created_at_ms, receipt_id
            """,
            dispatch_ids,
        ).fetchall()
    by_dispatch: dict[str, list[dict[str, Any]]] = {value: [] for value in dispatch_ids}
    for row in rows:
        by_dispatch.setdefault(str(row[1]), []).append(
            {
                "receiptId": str(row[0]),
                "dispatchId": str(row[1]),
                "sessionId": str(row[2]),
                "skillId": str(row[3]),
                "skillHash": str(row[4]),
                "loadReason": str(row[5]),
                "capabilityEpoch": int(row[6]),
                "state": str(row[7]),
            }
        )
    return {
        member: {
            "items": by_dispatch.get(dispatch_ids[index], []),
            "expectedSkillId": EXPECTED_SKILLS[member],
        }
        for index, member in enumerate(("A", "B", "C"))
    }


def _member_tool_receipts(
    db_path: Path,
    *,
    session_ids: dict[str, str],
    dispatches: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    tools = (
        "room_state",
        "room_collaborate",
        "workspace_list",
        "workspace_search",
        "workspace_read",
        "workspace_patch",
        "workspace_shell",
        "room_post",
        "room_commit",
    )
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for index, member in enumerate(("A", "B", "C")):
        dispatch_id = str(dispatches[index]["dispatchId"])
        result[member] = {
            tool: tool_receipt_evidence(
                db_path,
                session_id=session_ids[member],
                dispatch_ids=[dispatch_id],
                tool_name=tool,
            )
            for tool in tools
        }
    return result


def loaded_tool_receipt_evidence(
    db_path: Path,
    *,
    session_ids: dict[str, str],
    dispatches: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Read every governed load so the effective Pi registry can be audited.

    A tool can have bootstrap, Dispatch-rebind, and explicit model-load rows.
    The independent query keeps all of them; compaction comparison later selects
    the newest receipt for each schema that Pi actually exposes to the model.
    """

    result: dict[str, list[dict[str, Any]]] = {}
    with sqlite3.connect(db_path) as connection:
        for index, member in enumerate(("A", "B", "C")):
            rows = connection.execute(
                """
                SELECT disclosure.receipt_id,
                       disclosure.tool_name,
                       disclosure.created_at_ms
                FROM room_v2_tool_disclosure_receipts AS disclosure
                JOIN room_v2_capability_manifests AS manifest
                  ON manifest.manifest_id = disclosure.manifest_id
                JOIN room_v2_capability_runtime_bindings AS binding
                  ON binding.manifest_id = manifest.manifest_id
                WHERE binding.session_id = ?
                  AND manifest.dispatch_id = ?
                  AND disclosure.receipt_kind = 'load'
                ORDER BY disclosure.created_at_ms, disclosure.receipt_id
                """,
                (
                    session_ids[member],
                    str(dispatches[index].get("dispatchId") or ""),
                ),
            ).fetchall()
            result[member] = [
                {
                    "receiptId": str(row[0]),
                    "toolName": str(row[1]),
                    "createdAtMs": int(row[2]),
                }
                for row in rows
            ]
    return result


def quality_gate_commit_evidence(
    db_path: Path,
    *,
    tasks: list[dict[str, Any]],
    dispatches: list[dict[str, Any]],
) -> dict[str, Any]:
    tasks_by_id = {
        str(task.get("taskId") or ""): task
        for task in tasks
        if str(task.get("taskId") or "")
    }
    members: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(db_path) as connection:
        for index, member in enumerate(("A", "B", "C")):
            dispatch = dispatches[index]
            dispatch_id = str(dispatch.get("dispatchId") or "")
            task_id = str(dispatch.get("taskId") or "")
            task = tasks_by_id.get(task_id, {})
            row = connection.execute(
                """
                SELECT payload_json
                FROM room_kernel_commits
                WHERE dispatch_id = ?
                """,
                (dispatch_id,),
            ).fetchone()
            attempt_rows = connection.execute(
                """
                SELECT kernel_receipt_json
                FROM room_kernel_settle_attempt_receipts
                WHERE dispatch_id = ?
                ORDER BY created_at_ms, settle_receipt_id
                """,
                (dispatch_id,),
            ).fetchall()
            payload = (
                json.loads(str(row[0]))
                if row is not None
                else {}
            )
            receipt = payload.get("qualityGateReceipt")
            receipt = receipt if isinstance(receipt, dict) else {}
            items = receipt.get("items")
            items = items if isinstance(items, list) else []
            criteria = {
                str(value)
                for value in task.get("acceptanceCriterionIds") or []
                if str(value)
            }
            item_criteria = {
                str(item.get("criterionId") or "")
                for item in items
                if isinstance(item, dict)
                and str(item.get("criterionId") or "")
            }
            pass_items = [
                item
                for item in items
                if isinstance(item, dict)
                and item.get("status") == "pass"
            ]
            pass_criteria = {
                str(item.get("criterionId") or "")
                for item in pass_items
                if str(item.get("criterionId") or "")
            }
            aggregate_evidence = {
                str(value)
                for value in payload.get("evidenceRefs") or []
                if str(value)
            }
            pass_item_evidence = [
                {
                    str(value)
                    for value in item.get("evidenceRefs") or []
                    if str(value)
                }
                for item in pass_items
            ]
            continuation = payload.get("continuation")
            continuation = (
                continuation if isinstance(continuation, dict) else {}
            )
            decision = str(continuation.get("decision") or "")
            expected_verdict = (
                "ready_to_deliver"
                if decision == "complete"
                else "not_ready"
            )
            checks = {
                "commitSchemaV3": payload.get("schemaVersion")
                == "wisdom-weasel.room-commit.v3",
                "receiptSchemaV1": receipt.get("schemaVersion")
                == "wisdom-weasel.room-quality-gate-receipt.v1",
                "identityBound": (
                    receipt.get("rootId") == dispatch.get("rootId")
                    and receipt.get("taskId") == task_id
                    and receipt.get("dispatchId") == dispatch_id
                    and receipt.get("generation")
                    == dispatch.get("generation")
                ),
                "originalRequestChecked": receipt.get(
                    "originalRequestChecked"
                )
                is True,
                "criterionCoverageExact": (
                    len(items) == len(criteria)
                    and item_criteria == criteria
                    and pass_criteria
                    == {
                        str(value)
                        for value in payload.get(
                            "requirementCoverage"
                        )
                        or []
                        if str(value)
                    }
                ),
                "completeHasOnlyPassingCriteria": (
                    decision != "complete"
                    or len(pass_items) == len(criteria)
                ),
                "passEvidenceCommitted": all(
                    evidence
                    and evidence <= aggregate_evidence
                    for evidence in pass_item_evidence
                ),
                "verdictMatchesExit": receipt.get("verdict")
                == expected_verdict,
                "settleRepairsBounded": len(attempt_rows) <= 2,
            }
            members[member] = {
                "dispatchId": dispatch_id,
                "taskId": task_id,
                "receiptId": str(receipt.get("receiptId") or ""),
                "verdict": str(receipt.get("verdict") or ""),
                "criterionCount": len(criteria),
                "passCount": len(pass_criteria),
                "settleRepairCount": len(attempt_rows),
                "settleRepairReasons": [
                    str(
                        (
                            json.loads(str(attempt[0])).get(
                                "details"
                            )
                            or {}
                        ).get("reason")
                        or ""
                    )
                    for attempt in attempt_rows
                ],
                "checks": checks,
                "passed": bool(receipt.get("receiptId"))
                and all(checks.values()),
            }
    return {
        "members": members,
        "passed": all(
            value["passed"] for value in members.values()
        ),
    }


def _effective_loaded_tool_receipts(
    loaded: list[dict[str, Any]],
    disclosed_names: set[str],
) -> list[dict[str, str]]:
    """Mirror Pi's one-current-receipt-per-disclosed-schema registry contract."""

    latest_by_name: dict[str, dict[str, str]] = {}
    for item in loaded:
        name = str(item.get("toolName") or "")
        receipt_id = str(item.get("receiptId") or "")
        if name in disclosed_names and receipt_id:
            latest_by_name[name] = {
                "receiptId": receipt_id,
                "toolName": name,
            }
    return [latest_by_name[name] for name in sorted(latest_by_name)]


def _statuses(value: dict[str, Any]) -> list[str]:
    return [str(item.get("status") or "") for item in value.get("items") or []]


def _bounded_commit_statuses(value: dict[str, Any]) -> bool:
    statuses = _statuses(value)
    return (
        1 <= len(statuses) <= 3
        and statuses[-1] == "applied"
        and statuses.count("applied") == 1
        and all(status == "" for status in statuses[:-1])
    )


def _bounded_room_state_statuses(value: dict[str, Any]) -> bool:
    statuses = _statuses(value)
    return 1 <= len(statuses) <= 2 and set(statuses) == {"applied"}


def tool_workload_checks(
    receipts: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, bool]:
    a = receipts["A"]
    a_read_statuses = _statuses(a["workspace_read"])
    a_patch_statuses = _statuses(a["workspace_patch"])
    checks = {
        "aRoomState": _statuses(a["room_state"]) == ["applied"],
        "aCollaboratedOnce": _statuses(a["room_collaborate"]) == ["applied"],
        "aListSearch": _statuses(a["workspace_list"]) == ["applied"]
        and _statuses(a["workspace_search"]) == ["applied"],
        "aReadFailureRecoveredWithoutLoop": (
            3 <= len(a_read_statuses) <= 4
            and a_read_statuses[0] == "failed"
            and a_read_statuses.count("failed") == 1
            and 2 <= a_read_statuses.count("applied") <= 3
            and set(a_read_statuses) <= {"failed", "applied"}
        ),
        "aPatchAppliedOnceWithBoundedRepair": (
            1 <= len(a_patch_statuses) <= 2
            and a_patch_statuses[-1] == "applied"
            and a_patch_statuses.count("applied") == 1
            and a_patch_statuses.count("failed") <= 1
            and set(a_patch_statuses) <= {"failed", "applied"}
        ),
        "aTestFailureRecovered": _statuses(a["workspace_shell"])
        == ["failed", "applied"],
        "aPublicCommit": _statuses(a["room_post"]) == ["applied"]
        and _bounded_commit_statuses(a["room_commit"]),
    }
    b = receipts["B"]
    b_commit_bounded = _bounded_commit_statuses(b["room_commit"])
    checks["bRoomState"] = _bounded_room_state_statuses(b["room_state"])
    checks["bIndependentReads"] = _statuses(b["workspace_read"]) == [
        "applied",
        "applied",
    ]
    checks["bStayedReadOnly"] = (
        b["workspace_patch"]["invocationCount"] == 0
        and b["workspace_shell"]["invocationCount"] == 0
    )
    checks["bPublicCommit"] = _statuses(b["room_post"]) == [
        "applied"
    ] and b_commit_bounded
    checks["bCommitValidationPathBounded"] = b_commit_bounded
    c = receipts["C"]
    c_commit_bounded = _bounded_commit_statuses(c["room_commit"])
    checks["cRoomState"] = _bounded_room_state_statuses(c["room_state"])
    checks["cIndependentReads"] = _statuses(c["workspace_read"]) == [
        "applied",
        "applied",
    ]
    checks["cIndependentTest"] = _statuses(c["workspace_shell"]) == ["applied"]
    checks["cNeverPatched"] = c["workspace_patch"]["invocationCount"] == 0
    checks["cPublicCommit"] = _statuses(c["room_post"]) == [
        "applied"
    ] and c_commit_bounded
    checks["cCommitValidationPathBounded"] = c_commit_bounded
    checks["everyInvocationHasOneLoadReceipt"] = all(
        evidence["invocationCount"] == 0 or len(evidence["loadReceiptIds"]) == 1
        for member in receipts.values()
        for evidence in member.values()
    )
    return checks


def _transcript_path(session_dir: Path, expected_sha256: str) -> Path:
    for path in sorted(session_dir.glob("*.jsonl")):
        if hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256:
            return path
    raise RuntimeError(f"No Pi transcript matches {expected_sha256}")


def _collect_tool_call_ids(value: object) -> set[str]:
    if isinstance(value, list):
        return {item for child in value for item in _collect_tool_call_ids(child)}
    if not isinstance(value, dict):
        return set()
    found = {
        str(item)
        for key, item in value.items()
        if key in {"toolCallId", "tool_call_id"} and str(item).strip()
    }
    for child in value.values():
        found.update(_collect_tool_call_ids(child))
    return found


def private_transcript_evidence(
    session_dir: Path,
    contexts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_text: dict[str, str] = {}
    tool_ids: dict[str, set[str]] = {}
    transcript_receipts: dict[str, dict[str, Any]] = {}
    for member, context in contexts.items():
        sha256 = str(context["transcript"].get("sha256") or "")
        path = _transcript_path(session_dir, sha256)
        content = path.read_text(encoding="utf-8")
        raw_text[member] = content
        parsed = [json.loads(line) for line in content.splitlines() if line.strip()]
        tool_ids[member] = _collect_tool_call_ids(parsed)
        transcript_receipts[member] = transcript_evidence(session_dir, sha256)
    a_ids = tool_ids["A"]
    b_ids = tool_ids["B"]
    leaked_a = sorted(item for item in a_ids if item in raw_text["B"] or item in raw_text["C"])
    leaked_b = sorted(item for item in b_ids if item in raw_text["C"])
    return {
        "passed": (
            not leaked_a
            and not leaked_b
            and len({context["transcript"]["sha256"] for context in contexts.values()}) == 3
            and all(item["roomEnvelopeCount"] == 0 for item in transcript_receipts.values())
        ),
        "distinctTranscriptCount": len(
            {context["transcript"]["sha256"] for context in contexts.values()}
        ),
        "toolCallIdCounts": {member: len(values) for member, values in tool_ids.items()},
        "leakedAToolCallIds": leaked_a,
        "leakedBToolCallIds": leaked_b,
        "transcripts": transcript_receipts,
    }


def _compact_members(
    args: argparse.Namespace,
    *,
    requester: JsonRequester,
    session_ids: dict[str, str],
    tool_receipts: dict[str, dict[str, dict[str, Any]]],
    loaded_tool_receipts: dict[str, list[dict[str, Any]]],
    disclosed_tool_names: dict[str, set[str]],
    skill_receipts: dict[str, dict[str, Any]],
    expected_acceptance_counts: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for member, session_id in session_ids.items():
        response = requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/compact",
            {
                "instructions": (
                    "Preserve exactly one bounded recovery packet containing the immutable "
                    "original requirement, current task, acceptance, blockers, handoff, and "
                    "exact Skill/Tool receipts. Do not duplicate that packet."
                )
            },
            timeout=args.turn_timeout,
        )
        after = debug_evidence(
            args.base_url,
            session_id,
            requester=requester,
            timeout=args.turn_timeout,
        )
        transition = latest_transition(args.db_path, session_id)
        effective_tool_receipts = _effective_loaded_tool_receipts(
            loaded_tool_receipts[member],
            disclosed_tool_names[member],
        )
        expected_tool_ids = {
            item["receiptId"] for item in effective_tool_receipts
        }
        expected_tool_names = {
            item["toolName"] for item in effective_tool_receipts
        }
        all_loaded_tool_ids = {
            item["receiptId"] for item in loaded_tool_receipts[member]
        }
        invoked_tool_ids = {
            receipt_id
            for evidence in tool_receipts[member].values()
            for receipt_id in evidence["loadReceiptIds"]
        }
        skill_items = skill_receipts[member]["items"]
        expected_skill_receipt = (
            str(skill_items[0]["receiptId"]) if len(skill_items) == 1 else ""
        )
        compact_result = response.get("result") or {}
        journal_hashes = list(after["journal"]["hashes"])
        journal_entry_count = int(
            after["journal"]["entryCount"] or 0
        )
        checks = {
            "refreshApplied": compact_result.get("contextRefreshApplied") is True,
            "oneRecoveryPacket": (
                after["recoveryPacket"]["valid"] is True
                and after["recoveryPacket"]["roomContextCount"] == 1
                and journal_entry_count == len(journal_hashes)
                and journal_entry_count in {1, 2}
                and len(set(journal_hashes)) == journal_entry_count
            ),
            "transitionBound": transition["reason"] == "compaction"
            and transition["recovery"]["providerHashes"] == after["journal"]["hashes"],
            "requirementsRecovered": int(
                transition["recovery"]["originalRequirements"] or 0
            )
            >= 1
            and transition["recovery"]["currentTask"] is True
            and int(transition["recovery"]["acceptance"] or 0)
            == expected_acceptance_counts[member],
            "handoffRecovered": transition["recovery"]["handoff"] is True,
            "skillReceiptExact": transition["recovery"]["skillReceiptId"]
            == expected_skill_receipt,
            "toolReceiptsExact": expected_tool_ids
            == set(transition["recovery"]["toolReceiptIds"]),
            "toolReceiptNamesExact": expected_tool_names
            == set(transition["recovery"]["toolReceiptNames"]),
        }
        if bool(getattr(args, "require_cache_evidence", True)):
            checks["compactionDoesNotClaimCacheHit"] = (
                after["modelCallCount"] == 0
                and after["positiveCacheRead"] is False
            )
        else:
            checks["deterministicCacheEvidenceNotClaimed"] = (
                after["positiveCacheRead"] is False
            )
        results[member] = {
            "response": compact_result,
            "after": after,
            "transition": transition,
            "expectedSkillReceiptId": expected_skill_receipt,
            "expectedAcceptanceCount": expected_acceptance_counts[member],
            "expectedToolReceiptIds": sorted(expected_tool_ids),
            "expectedToolReceiptNames": sorted(expected_tool_names),
            "loadedWithoutInvocationReceiptIds": sorted(
                expected_tool_ids - invoked_tool_ids
            ),
            "supersededOrHiddenLoadReceiptIds": sorted(
                all_loaded_tool_ids - expected_tool_ids
            ),
            "checks": checks,
            "passed": all(checks.values()),
        }
    return results


def task_acceptance_counts(
    tasks: Sequence[Mapping[str, Any]],
    dispatches: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    task_by_id = {
        str(task.get("taskId") or ""): task
        for task in tasks
        if str(task.get("taskId") or "")
    }
    if len(dispatches) != 3:
        raise RuntimeError("three-member canary requires one terminal Dispatch per member")
    result: dict[str, int] = {}
    for member, dispatch in zip(("A", "B", "C"), dispatches, strict=True):
        task_id = str(dispatch.get("taskId") or "")
        task = task_by_id.get(task_id)
        if task is None:
            raise RuntimeError(
                f"terminal Dispatch for member {member} has no matching Task"
            )
        criterion_ids = task.get("acceptanceCriterionIds")
        if not isinstance(criterion_ids, list):
            raise RuntimeError(
                f"Task {task_id} has no canonical acceptanceCriterionIds array"
            )
        result[member] = len(criterion_ids)
    return result


def _role_texts(
    snapshot: Mapping[str, Any],
    role: str,
) -> list[str]:
    texts: list[str] = []
    for item in snapshot.get("items") or []:
        if not isinstance(item, Mapping) or item.get("role") != role:
            continue
        blocks = item.get("blocks")
        if not isinstance(blocks, list):
            continue
        value = "\n".join(
            str(block.get("data", {}).get("text") or "")
            for block in blocks
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("data"), Mapping)
        ).strip()
        if value:
            texts.append(value)
    return texts


def _assistant_texts(snapshot: Mapping[str, Any]) -> list[str]:
    return _role_texts(snapshot, "assistant")


def _user_texts(snapshot: Mapping[str, Any]) -> list[str]:
    return _role_texts(snapshot, "user")


def _runtime_transcript_ref(db_path: Path, session_id: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT transcript_ref FROM agent_runtime_bindings WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return str(row[0]) if row is not None else ""


def _wait_for_ordinary_reply(
    base_url: str,
    *,
    requester: JsonRequester,
    session_id: str,
    prior_assistant_count: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = requester(
            base_url,
            "GET",
            f"/api/agent/sessions/{encoded(session_id)}/messages",
            timeout=15,
        )
        if (
            str(last.get("status") or "") == "idle"
            and len(_assistant_texts(last)) > prior_assistant_count
        ):
            return last
        time.sleep(0.1)
    raise TimeoutError(
        "ordinary Agent did not resume after Room settlement: "
        f"status={last.get('status')!r}"
    )


def _session_continuity_probe(
    args: argparse.Namespace,
    *,
    requester: JsonRequester,
    session_id: str,
    room_id: str,
    root_id: str,
    public_posts: list[dict[str, Any]],
) -> dict[str, Any]:
    before = requester(
        args.base_url,
        "GET",
        f"/api/agent/sessions/{encoded(session_id)}/messages",
        timeout=15,
    )
    before_serialized = json.dumps(before, ensure_ascii=False, sort_keys=True)
    prior_assistant_count = len(_assistant_texts(before))
    transcript_before = _runtime_transcript_ref(args.db_path, session_id)
    accepted = requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/prompt",
        {
            "message": (
                f"{SESSION_CONTINUITY_PROMPT}：Room 已收工。不要调用工具。"
                "只依据这个 Session 现有上下文确认刚才的三成员任务和测试结果；"
                f"回答必须以 {SESSION_CONTINUITY_REPLY} 开头。"
            ),
            "clientMessageId": (
                f"session-continuity:{root_id}:{session_id}"
            ),
            "delivery": "prompt",
        },
        timeout=30,
    )
    after = _wait_for_ordinary_reply(
        args.base_url,
        requester=requester,
        session_id=session_id,
        prior_assistant_count=prior_assistant_count,
        timeout=args.turn_timeout,
    )
    transcript_after = _runtime_transcript_ref(args.db_path, session_id)
    debug = requester(
        args.base_url,
        "GET",
        (
            f"/api/agent/sessions/{encoded(session_id)}/debug-context"
            f"?turnId={encoded(str(accepted.get('turnId') or ''))}"
        ),
        timeout=args.turn_timeout,
    )
    context = debug.get("context") if isinstance(debug.get("context"), Mapping) else {}
    context_text = json.dumps(
        {
            "systemPrompt": context.get("systemPrompt"),
            "modelCalls": context.get("modelCalls"),
            "providerRequests": context.get("providerRequests"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    assistant_texts = _assistant_texts(after)
    public_a_posts = [
        item
        for item in public_posts
        if MARKERS["A"] in str(item.get("content") or "")
    ]
    provider_mode = str(getattr(args, "provider_mode", "") or "")
    checks = {
        "sameTranscript": bool(transcript_before)
        and transcript_before == transcript_after,
        "publicRoomDeliveryVisibleInAgentWindow": MARKERS["A"]
        in before_serialized,
        "samePublicDeliveryVisibleInRoom": len(public_a_posts) == 1,
        "ordinaryPromptAccepted": accepted.get("accepted") is True,
        "ordinarySessionIdle": str(after.get("status") or "") == "idle",
        "providerSawRoomHistory": (
            SESSION_CONTINUITY_PROMPT in context_text
            and (
                "THREE-MEMBER-ROOM-CANARY" in context_text
                or MARKERS["A"] in context_text
                or COMMIT_RESULTS["A"] in context_text
            )
        ),
        "noDuplicateContinuationPrompt": (
            sum(
                SESSION_CONTINUITY_PROMPT in text
                for text in _user_texts(after)
            )
            == 1
        ),
    }
    if provider_mode == "configured":
        checks["modelConfirmedContinuity"] = bool(assistant_texts) and (
            SESSION_CONTINUITY_REPLY in assistant_texts[-1]
        )
    else:
        checks["deterministicResponseNotClaimedAsSemanticProof"] = (
            SESSION_CONTINUITY_PROMPT in context_text
        )
    return {
        "sessionId": session_id,
        "roomId": room_id,
        "rootId": root_id,
        "accepted": accepted,
        "transcriptRefBefore": transcript_before,
        "transcriptRefAfter": transcript_after,
        "agentWindowBefore": {
            "status": before.get("status"),
            "messageCount": len(before.get("items") or []),
            "assistantCount": prior_assistant_count,
            "containsPrivateRoomTask": "THREE-MEMBER-ROOM-CANARY"
            in before_serialized,
            "containsOwnPublicPost": MARKERS["A"] in before_serialized,
        },
        "agentWindowAfter": {
            "status": after.get("status"),
            "messageCount": len(after.get("items") or []),
            "assistantCount": len(assistant_texts),
            "lastAssistantText": (
                assistant_texts[-1] if assistant_texts else ""
            ),
        },
        "providerContext": {
            "turnId": debug.get("turnId"),
            "modelCallCount": len(context.get("modelCalls") or []),
            "containsRoomTaskOrDelivery": (
                "THREE-MEMBER-ROOM-CANARY" in context_text
                or MARKERS["A"] in context_text
                or COMMIT_RESULTS["A"] in context_text
            ),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def run(
    args: argparse.Namespace,
    *,
    requester: JsonRequester = request_json,
) -> dict[str, Any]:
    stamp = int(time.time() * 1000)
    workspace = args.workspace.expanduser().resolve(strict=True)
    participant_roles = list(args.participant_roles)
    if len(participant_roles) != 3:
        raise RuntimeError("Room collaboration canary requires exactly three role references")
    created = requester(
        args.base_url,
        "POST",
        "/api/agent/rooms",
        {
            "title": f"Three member project canary {stamp}",
            "routingPolicy": "manual_mentions",
            "workspaceRoots": [str(workspace)],
            "executionMode": "workspace_managed",
            "workspaceScopeConfirmation": "APPROVE_WORKSPACE_SCOPE",
            "participants": participant_roles,
        },
    )
    room = created["room"]
    participants = list(room["participants"])
    members = dict(zip(("A", "B", "C"), participants, strict=True))
    participant_ids = {member: str(value["id"]) for member, value in members.items()}
    session_ids = {member: str(value["sessionId"]) for member, value in members.items()}
    room_id = str(room["id"])
    for session_id in session_ids.values():
        _configure_session(
            args.base_url,
            requester=requester,
            session_id=session_id,
            model_provider=args.model_provider,
            model_id=args.model_id,
            thinking_level=args.thinking_level,
        )
    listed_sessions = requester(
        args.base_url,
        "GET",
        "/api/agent/sessions?includeInternal=true&limit=500",
        timeout=10,
    )
    session_by_id = {
        str(item.get("id") or ""): item
        for item in listed_sessions.get("items") or []
        if isinstance(item, dict)
    }
    session_policy_checks = {
        member: (
            session_ids[member] in session_by_id
            and session_by_id[session_ids[member]].get("executionMode")
            == "workspace_managed"
            and session_by_id[session_ids[member]].get("workspaceScopeGranted")
            is True
            and session_by_id[session_ids[member]].get("workspaceRoots")
            == [str(workspace)]
        )
        for member in ("A", "B", "C")
    }

    acceptance_criteria = [
        (
            f"A 先用 workspace_read 读取不存在的 {MISSING_READ_PATH} 一次并失败，"
            "不得同参数重试；随后读取 calculator.py 与 test_calculator.py"
        ),
        (
            f"A 修改前运行 {TEST_COMMAND} 得到非零退出，再仅修改 calculator.py，"
            "修改后同一命令退出码为 0"
        ),
        (
            f"A 在实现前用 room_collaborate 点名 B 做只读测试意图复核，然后继续自己的实现；"
            f"完成后用 room_post 公开 {MARKERS['A']}，再用一次 room_commit 正式交给 C 验收"
        ),
        (
            "B 作为并行 child Task 独立读取 calculator.py 与 test_calculator.py，"
            f"不得调用 workspace_patch 或 workspace_shell；公开 {MARKERS['B']} 后 deliver 自己的 Task"
        ),
        (
            f"C 独立读取两份文件并运行 {TEST_COMMAND} 成功，全程不得调用 workspace_patch；"
            f"公开 {MARKERS['C']}"
        ),
        (
            "同一个 Root 内只有 D1(A,execute)，D1 用 room_collaborate 派生 D2(B,review) 后继续，"
            "再用正式 handoff 从 D1 派生 D3(C,close)；"
            "三人分别调用 room_state、room_post、room_commit，最终 deliver 覆盖全部验收条件"
        ),
    ]
    work = requester(
        args.base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/work-items",
        {
            "currentOwnerParticipantId": participant_ids["A"],
            "createdByParticipantId": participant_ids["C"],
            "clientMessageId": f"three-member-work-{stamp}",
            "objective": "THREE-MEMBER-ROOM-CANARY：三成员完成、复核并验收隔离项目",
            "expectedOutput": (
                "只修改 calculator.py；A 一边实现一边点名 B 做并行只读复核，"
                "A 再正式交给 C 独立验收；"
                "公开三条唯一 RoomPost 并由 C 完成最终 deliver"
            ),
            "acceptanceCriteria": acceptance_criteria,
            "state": "active",
        },
    )["workItem"]

    a_name = str(members["A"]["displayName"])
    b_name = str(members["B"]["displayName"])
    c_name = str(members["C"]["displayName"])
    message = (
        f"@{a_name} 执行 THREE-MEMBER-ROOM-CANARY。先调用 room_state 一次，"
        f"从返回的成员列表按 displayName 找到并行审查员 {b_name} 和最终验收者 {c_name}。"
        "精确加载 room_collaborate，并只调用一次：targetParticipantId 使用 B 的稳定 id，"
        "intentKind=review，acceptanceCriterionIds=[]；objective 必须要求 B 先 room_state，"
        "再独立加载 workspace_read 并读取 calculator.py 与 test_calculator.py，"
        "不得调用 workspace_patch 或 workspace_shell；随后 room_post 的 content 以 "
        f"{MARKERS['B']} 开头，最后 room_commit decision=deliver、"
        f"result={COMMIT_RESULTS['B']}、requirementCoverage=[]、evidenceRefs 至少一项。"
        "expectedOutput 必须写明 B 交付只读测试意图复核与文件证据。"
        "room_collaborate 返回后你必须继续当前 Dispatch，不得等待 B，也不得把它当责任移交。"
        f"精确加载 workspace_read，只读取不存在的 {workspace / MISSING_READ_PATH} 一次，"
        "收到失败后不得同参数重试；再加载 workspace_list 查看目录，加载 workspace_search 搜索 "
        "ROOM_PROJECT_TASK，然后读取 calculator.py 和 test_calculator.py。"
        f"加载 workspace_shell 并只运行 {TEST_COMMAND}，allowNetwork=false；工作区托管会在范围内自动执行，"
        "确认修改前测试非零退出；再加载 workspace_patch，只修改 calculator.py 实现 "
        "normalize_scores；随后再次运行同一测试命令，确认退出码为 0。"
        f"调用 room_post，content 必须以 {MARKERS['A']} 开头，只写公开结果。"
        "然后只调用一次 room_commit：decision=handoff，"
        f"result={COMMIT_RESULTS['A']}，requirementCoverage=[]，targetParticipantId 必须使用 "
        f"room_state 中 {c_name} 的稳定 id，nextIntentKind=close。nextTask 必须要求 C："
        "先 room_state，独立加载 workspace_read 并读取 calculator.py、test_calculator.py；"
        f"运行 {TEST_COMMAND}，不得调用 workspace_patch，room_post 以 {MARKERS['C']} 开头，"
        f"最后 room_commit decision=deliver、result={COMMIT_RESULTS['C']}，"
        "从 Room task context 原样覆盖全部 acceptance.criteria[].criterionId。"
        "每次 room_commit 后立即结束本轮。"
    )
    message_payload = {
        "message": message,
        "clientMessageId": f"three-member-message-{stamp}",
        "workItemId": work["id"],
    }
    accepted = requester(
        args.base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/messages",
        message_payload,
    )
    root_id = accepted_root_id(accepted)
    duplicate_root_id = accepted_root_id(
        requester(
            args.base_url,
            "POST",
            f"/api/agent/rooms/{encoded(room_id)}/messages",
            message_payload,
        )
    )
    try:
        settled = wait_for_three_member_settlement(
            args.base_url,
            room_id,
            root_id,
            requester=requester,
            sessions=session_ids,
            timeout=args.turn_timeout,
        )
    except BaseException:
        cancel_root(
            args.base_url,
            room_id,
            root_id,
            requester=requester,
            timeout=max(70, args.turn_timeout),
        )
        raise

    finalized = requester(
        args.base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/finalize",
        {"rootId": root_id},
        timeout=30,
    )
    terminal_snapshot = requester(
        args.base_url,
        "GET",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
        timeout=10,
    )
    terminal_roots, terminal_tasks, terminal_dispatches = _root_snapshot(
        terminal_snapshot,
        root_id,
    )
    chain = dispatch_chain_evidence(
        terminal_tasks,
        terminal_dispatches,
        participant_ids=participant_ids,
        session_ids=session_ids,
    )
    ordered_terminal_dispatches = [
        next(
            (
                item
                for item in terminal_dispatches
                if str(item.get("targetParticipantId") or "")
                == participant_ids[member]
                and str(item.get("targetSessionId") or "") == session_ids[member]
            ),
            {},
        )
        for member in ("A", "B", "C")
    ]
    tool_receipts = _member_tool_receipts(
        args.db_path,
        session_ids=session_ids,
        dispatches=ordered_terminal_dispatches,
    )
    loaded_tool_receipts = loaded_tool_receipt_evidence(
        args.db_path,
        session_ids=session_ids,
        dispatches=ordered_terminal_dispatches,
    )
    quality_gate_receipts = quality_gate_commit_evidence(
        args.db_path,
        tasks=terminal_tasks,
        dispatches=ordered_terminal_dispatches,
    )
    tool_checks = tool_workload_checks(tool_receipts)
    approvals = managed_approval_evidence(
        args.base_url,
        requester=requester,
        session_ids=session_ids,
    )
    approval_checks = managed_approval_checks(approvals)
    skill_receipts = skill_receipt_evidence(
        args.db_path,
        ordered_terminal_dispatches,
    )
    skill_checks: dict[str, bool] = {}
    for index, member in enumerate(("A", "B", "C")):
        value = skill_receipts[member]
        skill_checks[member] = (
            len(value["items"]) == 1
            and value["items"][0]["skillId"] == EXPECTED_SKILLS[member]
            and value["items"][0]["sessionId"] == session_ids[member]
            and value["items"][0]["loadReason"] == "stage_required"
            and value["items"][0]["capabilityEpoch"]
            == int(ordered_terminal_dispatches[index].get("capabilityEpoch") or -1)
        )
    before = {
        member: debug_evidence(
            args.base_url,
            session_id,
            requester=requester,
            timeout=args.turn_timeout,
            text_markers=MARKERS,
            governed_tool_receipts=loaded_tool_receipts[member],
        )
        for member, session_id in session_ids.items()
    }
    public_posts = [
        item
        for item in terminal_snapshot.get("posts") or []
        if isinstance(item, dict)
        and item.get("rootId") == root_id
        and isinstance(item.get("publicationSource"), dict)
        and item["publicationSource"].get("kind") == "room_commit"
    ]
    posts_by_member = {
        member: [
            item
            for item in public_posts
            if str(item.get("authorActorRef") or "") == participant_ids[member]
        ]
        for member in ("A", "B", "C")
    }
    public_post_checks = {
        "exactCount": len(public_posts) == 3,
        "onePerMember": all(len(posts_by_member[member]) == 1 for member in posts_by_member),
        "stagedBodiesPublished": all(
            MARKERS[member] in str(posts_by_member[member][0].get("content") or "")
            and COMMIT_RESULTS[member]
            not in str(posts_by_member[member][0].get("content") or "")
            for member in ("A", "B", "C")
        )
        if all(len(posts_by_member[member]) == 1 for member in posts_by_member)
        else False,
    }
    visibility = {
        member: value["providerRoomPostVisibility"]
        for member, value in before.items()
    }

    def provider_saw(member: str, marker: str) -> bool:
        evidence = visibility[member].get(marker) or {}
        return evidence.get("seen") is True

    cache_usage_observed = all(
        value["positiveCacheRead"] for value in before.values()
    )
    prompt_checks = {
        "formalHandoffDeltaVisible": provider_saw("C", "A"),
        "futurePostsNotBackfilled": (
            not provider_saw("A", "C")
            and not provider_saw("B", "C")
        ),
        "providerPrefixStable": all(value["providerPrefix"]["passed"] for value in before.values()),
        "agentMdDefaultOff": all(
            value["promptGovernance"]["projectContextBlockCount"] == 0
            for value in before.values()
        ),
        "managedAuthorityClear": all(
            value["promptGovernance"]["managedRoomAuthorityEveryCall"] is True
            and not value["promptGovernance"]["conflictingWorkflowMarkers"]
            and value["promptGovernance"]["lifecycleHookBlockCount"] == 0
            for value in before.values()
        ),
        "roomProjectionDeduplicated": all(
            value["promptGovernance"][
                "originalRequirementProjectionDeduplicatedEveryCall"
            ]
            is True
            and value["promptGovernance"]["roomFactFramingValidEveryCall"] is True
            for value in before.values()
        ),
        "progressiveDiscovery": all(
            value["promptGovernance"]["stableRoomBootstrapSchemasExact"]
            is True
            and progressive_discovery_check([value["promptGovernance"]])
            for value in before.values()
        ),
        "boundedUsefulRag": bounded_useful_rag_check(before),
        "queuesDrained": all(value["pendingContinuations"] == 0 for value in before.values()),
    }
    if bool(getattr(args, "require_cache_evidence", True)):
        prompt_checks["cacheUsageObserved"] = cache_usage_observed
    else:
        prompt_checks["deterministicCacheEvidenceNotClaimed"] = (
            not cache_usage_observed
        )
    transcript = private_transcript_evidence(args.pi_session_dir, before)
    a_commit_repair_count = _statuses(
        tool_receipts["A"]["room_commit"]
    ).count("")
    tool_checks["aRepairContinuationBounded"] = (
        int(
            transcript["transcripts"]["A"][
                "repairContinuationCount"
            ]
        )
        == a_commit_repair_count
    )
    b_commit_repair_count = _statuses(
        tool_receipts["B"]["room_commit"]
    ).count("")
    tool_checks["bRepairContinuationBounded"] = (
        int(
            transcript["transcripts"]["B"][
                "repairContinuationCount"
            ]
        )
        == b_commit_repair_count
    )
    c_commit_repair_count = _statuses(
        tool_receipts["C"]["room_commit"]
    ).count("")
    tool_checks["cRepairContinuationBounded"] = (
        int(
            transcript["transcripts"]["C"][
                "repairContinuationCount"
            ]
        )
        == c_commit_repair_count
    )
    independent = _independent_project_verification(workspace)
    final_source = (workspace / "calculator.py").read_text(encoding="utf-8")
    compaction = _compact_members(
        args,
        requester=requester,
        session_ids=session_ids,
        tool_receipts=tool_receipts,
        loaded_tool_receipts=loaded_tool_receipts,
        disclosed_tool_names={
            member: {
                str(name)
                for name in (
                    before[member]["currentProviderContext"].get(
                        "disclosedBackendTools"
                    )
                    or []
                )
                if str(name).strip()
            }
            for member in ("A", "B", "C")
        },
        skill_receipts=skill_receipts,
        expected_acceptance_counts=task_acceptance_counts(
            terminal_tasks,
            ordered_terminal_dispatches,
        ),
    )
    continuity = _session_continuity_probe(
        args,
        requester=requester,
        session_id=session_ids["A"],
        room_id=room_id,
        root_id=root_id,
        public_posts=public_posts,
    )
    terminal_receipt = finalized.get("receipt") or {}
    checks = {
        "workspaceManagedOnceForAllMembers": (
            room.get("executionMode") == "workspace_managed"
            and all(session_policy_checks.values())
        ),
        "idempotentUserIngress": duplicate_root_id == root_id,
        "singleBoundedDispatchChain": chain["passed"] is True,
        "rootCompleted": (
            len(terminal_roots) == 1
            and terminal_roots[0].get("state") == "completed"
            and terminal_receipt.get("status") == "applied"
            and terminal_receipt.get("receiptKind") == "terminal"
        ),
        "publicPostsExact": all(public_post_checks.values()),
        "toolWorkloadExact": all(tool_checks.values()),
        "skillsExact": all(skill_checks.values()),
        "qualityGateReceiptsValid": quality_gate_receipts[
            "passed"
        ]
        is True,
        "providerContextsValid": all(prompt_checks.values()),
        "privateSessionHistories": transcript["passed"] is True,
        "projectImplementationApproved": _approved_project_source(final_source),
        "independentTestsPass": independent["exitCode"] == 0,
        "workspaceManagedApprovalsExact": all(approval_checks.values()),
        "threeRecoveryPacketsValid": all(value["passed"] for value in compaction.values()),
        "sameSessionContinuesAfterRoom": continuity["passed"] is True,
    }
    if bool(getattr(args, "require_cache_evidence", True)):
        checks["realProviderKvCacheObserved"] = prompt_checks[
            "cacheUsageObserved"
        ]
    else:
        checks["deterministicCacheEvidenceNotClaimed"] = (
            prompt_checks["deterministicCacheEvidenceNotClaimed"]
            and all(
                value["checks"]["deterministicCacheEvidenceNotClaimed"]
                for value in compaction.values()
            )
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "roomId": room_id,
        "rootId": root_id,
        "workItemId": str(work["id"]),
        "members": {
            member: {
                "participantId": participant_ids[member],
                "sessionId": session_ids[member],
                "displayName": str(members[member]["displayName"]),
                "collaborationRole": str(members[member]["collaborationRole"]),
            }
            for member in ("A", "B", "C")
        },
        "sessionPolicyChecks": session_policy_checks,
        "dispatch": settled,
        "chain": chain,
        "terminal": {
            "receipt": terminal_receipt,
            "root": terminal_roots[0] if terminal_roots else None,
        },
        "publicPosts": public_posts,
        "publicPostChecks": public_post_checks,
        "approvals": approvals,
        "approvalChecks": approval_checks,
        "toolReceipts": tool_receipts,
        "loadedToolReceipts": loaded_tool_receipts,
        "toolChecks": tool_checks,
        "skillReceipts": skill_receipts,
        "skillChecks": skill_checks,
        "qualityGateReceipts": quality_gate_receipts,
        "beforeCompaction": before,
        "promptChecks": prompt_checks,
        "transcriptIsolation": transcript,
        "compaction": compaction,
        "sessionContinuity": continuity,
        "project": {
            "workspace": str(workspace),
            "calculatorSha256": hashlib.sha256(final_source.encode("utf-8")).hexdigest(),
            "calculatorBytes": len(final_source.encode("utf-8")),
            "independentTest": independent,
        },
        "checks": checks,
    }
if __name__ == "__main__":
    raise SystemExit(
        "Use run_room_context_epoch_in_process.py --scenario project-collaboration"
    )
