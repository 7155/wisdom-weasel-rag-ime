#!/usr/bin/env python3
"""Verify one real three-member full-auto Room lifecycle.

The canary speaks to the Room only as a user.  Its opening bytes are exactly
``写 TUI`` and clarification answers are ordinary natural-language messages;
execution Tools are checked privately from authoritative snapshots and
receipts rather than pre-scripted into model-visible text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from room_context_epoch_canary import (
    JsonRequester,
    accepted_root_id,
    cancel_root,
    encoded,
    request_json,
)

SCHEMA_VERSION = "wisdom-weasel.room-three-member-canary.v2"
OPENING_MESSAGE = "写 TUI"
NATURAL_REQUIREMENT_ANSWERS = (
    "先做一个最小可运行的终端界面：有清晰的标题、输入区和结果区；不用安装新依赖，启动后能直接使用。",
    "优先保证键盘操作、状态反馈和基本错误提示，先不加入网络同步或复杂主题。",
    "交付时保留现有项目约定，只改实现所需内容，并给出可复现的验证结果。",
)
NATURAL_MESSAGE_FORBIDDEN_TERMS = (
    "room_state", "room_post", "room_commit", "room_define", "room_collaborate",
    "workspace_read", "workspace_edit", "workspace_patch", "workspace_shell",
    "participantRef", "evidenceRef", "acceptanceAliases",
)
MEMBERS = ("A", "B", "C")
FACILITATOR_MEMBER = "A"
IMPLEMENTATION_MEMBER = "B"
REVIEWER_MEMBER = "C"
MAX_CLARIFICATION_QUESTIONS = len(NATURAL_REQUIREMENT_ANSWERS)
DEFAULT_WORKFLOW_TIMEOUT_MULTIPLIER = 3.0


def workflow_timeout_seconds(args: argparse.Namespace) -> float:
    explicit = getattr(args, "workflow_timeout", None)
    if explicit is not None:
        value = float(explicit)
        if value <= 0:
            raise ValueError("workflow_timeout must be positive")
        return value
    value = float(getattr(args, "turn_timeout", 0) or 0)
    if value <= 0:
        raise ValueError("turn_timeout must be positive")
    return value * DEFAULT_WORKFLOW_TIMEOUT_MULTIPLIER


def natural_message_leaks(messages: Sequence[str]) -> list[str]:
    text = "\n".join(str(value) for value in messages)
    return sorted(term for term in NATURAL_MESSAGE_FORBIDDEN_TERMS if term in text)


def _root_snapshot(snapshot: Mapping[str, Any], root_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    roots = [dict(item) for item in snapshot.get("roots") or [] if isinstance(item, Mapping) and str(item.get("rootId") or "") == root_id]
    tasks = [dict(item) for item in snapshot.get("tasks") or [] if isinstance(item, Mapping) and str(item.get("rootId") or "") == root_id]
    dispatches = [dict(item) for item in snapshot.get("dispatches") or [] if isinstance(item, Mapping) and str(item.get("rootId") or "") == root_id]
    dispatches.sort(key=lambda item: (int(item.get("generation") or 0), int(item.get("hopCount") or 0), int(item.get("depth") or 0), int(item.get("createdAtMs") or 0), str(item.get("dispatchId") or "")))
    return roots, tasks, dispatches


def _root_requirements(snapshot: Mapping[str, Any], root_id: str) -> dict[str, Any]:
    value = snapshot.get("requirementsByRootId")
    projection = value.get(root_id) if isinstance(value, Mapping) else None
    return dict(projection) if isinstance(projection, Mapping) else {}

def _catalog_is_defined(catalog: object) -> bool:
    if not isinstance(catalog, Mapping) or int(catalog.get("revision") or 0) < 2:
        return False
    items = [item for item in catalog.get("items") or [] if isinstance(item, Mapping)]
    criteria = [item for item in catalog.get("acceptanceCriteria") or [] if isinstance(item, Mapping)]
    return bool(criteria) and any(
        str(item.get("origin") or "") == "room_define"
        and str(item.get("statement") or item.get("text") or "").strip()
        for item in items
    )



def _work_items(response: Mapping[str, Any] | Sequence[Any] | None) -> list[dict[str, Any]]:
    values = response.get("items") or response.get("workItems") or [] if isinstance(response, Mapping) else response or []
    return [dict(item) for item in values if isinstance(item, Mapping)]


def _anchor_text(anchor: Mapping[str, Any]) -> str:
    payload = anchor.get("anchor") if isinstance(anchor.get("anchor"), Mapping) else anchor
    return str(anchor.get("originalText") or anchor.get("content") or payload.get("originalText") or payload.get("content") or "")

def _integer(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



def _anchor_integrity(anchor: Mapping[str, Any], expected: str) -> bool:
    payload = anchor.get("anchor") if isinstance(anchor.get("anchor"), Mapping) else anchor
    if not isinstance(payload, Mapping):
        return False
    return _anchor_text(anchor) == expected and str(payload.get("originalContentSha256") or "") == hashlib.sha256(expected.encode("utf-8")).hexdigest() and int(payload.get("originalByteLength") or -1) == len(expected.encode("utf-8")) and str(anchor.get("integrityStatus") or "verified") == "verified"


def initial_intake_checks(accepted: Mapping[str, Any], snapshot: Mapping[str, Any], *, root_id: str, task_id: str, opening: str, facilitator_id: str, work_items: Sequence[Mapping[str, Any]]) -> dict[str, bool]:
    roots, tasks, dispatches = _root_snapshot(snapshot, root_id)
    accepted_alignment = [
        item
        for item in accepted.get("alignmentDispatches") or []
        if isinstance(item, Mapping)
    ]
    alignment = [
        item
        for item in dispatches
        if str(item.get("intentKind") or "") == "align"
        and not str(item.get("parentDispatchId") or "")
    ]
    execution = [
        item
        for item in dispatches
        if str(item.get("intentKind") or "") in {"execute", "review", "close"}
    ]
    accepted_anchor = accepted.get("requirementAnchor") or accepted.get("anchor")
    accepted_anchor_id = (
        str(accepted_anchor.get("anchorId") or "")
        if isinstance(accepted_anchor, Mapping)
        else ""
    )
    requirements = _root_requirements(snapshot, root_id)
    snapshot_anchors = [
        item
        for item in requirements.get("anchors") or []
        if isinstance(item, Mapping)
    ]
    anchor = next(
        (
            item
            for item in snapshot_anchors
            if str(
                (
                    item.get("anchor")
                    if isinstance(item.get("anchor"), Mapping)
                    else item
                ).get("anchorId")
                or ""
            )
            == accepted_anchor_id
        ),
        accepted_anchor,
    )
    post = accepted.get("post")
    accepted_dispatch_id = (
        str(accepted_alignment[0].get("dispatchId") or "")
        if len(accepted_alignment) == 1
        else ""
    )
    return {
        "openingExact": isinstance(post, Mapping) and str(post.get("content") or post.get("message") or "") == opening == OPENING_MESSAGE,
        "singleRoot": len(roots) == 1 and roots[0].get("rootId") == root_id,
        "singleAlignmentTask": len(tasks) == 1 and tasks[0].get("taskId") == task_id and (not str(accepted.get("taskId") or "") or str(accepted.get("taskId")) == task_id),
        "singleInitialAlignmentDispatch": len(alignment) == 1 and bool(accepted_dispatch_id) and str(alignment[0].get("dispatchId") or "") == accepted_dispatch_id and str(alignment[0].get("rootId") or "") == root_id and str(alignment[0].get("taskId") or "") == task_id and str(alignment[0].get("targetParticipantId") or "") == facilitator_id and str(alignment[0].get("intentKind") or "") == "align",
        "noInitialExecutionFanout": not execution,
        "noWorkItemBeforeDefinition": not accepted.get("workItem") and not list(work_items),
        "openingAnchorBytePreserved": isinstance(anchor, Mapping) and _anchor_integrity(anchor, opening),
        "facilitatorOwnsRoot": bool(roots) and str(roots[0].get("facilitatorParticipantId") or "") == facilitator_id and str(roots[0].get("reporterParticipantId") or facilitator_id) == facilitator_id,
    }


def _new_user_anchor(snapshot: Mapping[str, Any], *, root_id: str, answer: str) -> bool:
    projection = _root_requirements(snapshot, root_id)
    anchors = projection.get("anchors") if isinstance(projection, Mapping) else []
    for item in anchors or []:
        if not isinstance(item, Mapping) or not _anchor_integrity(item, answer):
            continue
        payload = item.get("anchor") if isinstance(item.get("anchor"), Mapping) else item
        if str(payload.get("rootId") or item.get("rootId") or "") == root_id:
            return True
    return False


def clarification_transition_checks(before: Mapping[str, Any], response: Mapping[str, Any], after: Mapping[str, Any], *, root_id: str, task_id: str, waiting_dispatch: Mapping[str, Any], answer: str, work_items_before: Sequence[Mapping[str, Any]], work_items_after: Sequence[Mapping[str, Any]], definition_applied: bool = False) -> dict[str, bool]:
    before_roots, before_tasks, before_dispatches = _root_snapshot(before, root_id)
    after_roots, after_tasks, after_dispatches = _root_snapshot(after, root_id)
    before_ids = {str(item.get("dispatchId") or "") for item in before_dispatches}
    resumed = [item for item in after_dispatches if str(item.get("dispatchId") or "") not in before_ids and str(item.get("intentKind") or "") == "resume"]
    user_posts = [item for item in after.get("posts") or [] if isinstance(item, Mapping) and str(item.get("rootId") or "") == root_id and str((item.get("publicationSource") or {}).get("kind") or "") in {"user", "room_post"}]
    return {
        "answerAccepted": response.get("accepted") is True,
        "sameRoot": str(response.get("rootId") or "") == root_id,
        "sameTask": str(response.get("taskId") or "") in {"", task_id},
        "singleRootPreserved": len(after_roots) == len(before_roots) == 1,
        "singleTaskPreserved": len(after_tasks) == len(before_tasks) == 1 and after_tasks[0].get("taskId") == task_id and before_tasks[0].get("taskId") == task_id,
        "exactlyOneResumeDispatch": len(resumed) == 1,
        "resumeUsesSameParticipantAndTask": len(resumed) == 1 and str(resumed[0].get("rootId") or "") == root_id and str(resumed[0].get("taskId") or "") == task_id and str(resumed[0].get("targetParticipantId") or "") == str(waiting_dispatch.get("targetParticipantId") or "") and str(resumed[0].get("targetSessionId") or "") == str(waiting_dispatch.get("targetSessionId") or ""),
        "answerAnchorPreserved": _new_user_anchor(after, root_id=root_id, answer=answer),
        "answerPublishedUnderSameRoot": any(str(item.get("content") or "") == answer for item in user_posts),
        "noWorkItemBeforeDefinition": not list(work_items_before) and (definition_applied or not list(work_items_after)),
        "noExecutionBeforeDefinition": all(str(item.get("intentKind") or "") not in {"execute", "review", "close"} for item in after_dispatches),
    }


def definition_checks(projection: Mapping[str, Any], work_items: Sequence[Mapping[str, Any]], definition_receipts: Sequence[Mapping[str, Any]], *, root_id: str, facilitator_id: str, implementation_id: str) -> dict[str, bool]:
    catalog = projection.get("catalog") if isinstance(projection, Mapping) else {}
    catalog = catalog if isinstance(catalog, Mapping) else {}
    requirements = [item for item in catalog.get("items") or [] if isinstance(item, Mapping)]
    criteria = [item for item in catalog.get("acceptanceCriteria") or [] if isinstance(item, Mapping)]
    aliases: dict[str, str] = {}
    for receipt in definition_receipts:
        value = receipt.get("acceptanceAliases")
        if isinstance(value, Mapping):
            aliases.update({str(key): str(item) for key, item in value.items()})
    if not aliases and isinstance(catalog.get("acceptanceAliases"), Mapping):
        aliases = {str(key): str(value) for key, value in catalog["acceptanceAliases"].items()}
    expected_alias_names = {f"AC-{index}" for index in range(1, len(criteria) + 1)}
    criterion_ids = {str(item.get("criterionId") or item.get("id") or "") for item in criteria}
    root_items = [item for item in work_items if str(item.get("rootTurnId") or item.get("rootId") or "") == root_id]
    return {
        "catalogRevisionAdvanced": int(catalog.get("revision") or catalog.get("revisionNumber") or 0) >= 2,
        "derivedRequirementsNonEmpty": any(str(item.get("origin") or "") == "room_define" and str(item.get("statement") or item.get("text") or "").strip() for item in requirements),
        "acceptanceCriteriaNonEmpty": bool(criteria),
        "acceptanceCriteriaHaveReceiptTypes": all(isinstance(item.get("expectedReceiptTypes"), list) and bool(item.get("expectedReceiptTypes")) for item in criteria),
        "acceptanceAliasesStableAndComplete": bool(criteria) and set(aliases) == expected_alias_names and set(aliases.values()) == criterion_ids and "" not in criterion_ids,
        "exactlyOneAccountableRootWorkItem": len(root_items) == 1 and str(root_items[0].get("accountableParticipantId") or root_items[0].get("ownerParticipantId") or "") == facilitator_id and str(root_items[0].get("createdByParticipantId") or "") == facilitator_id and str(root_items[0].get("rootWorkId") or "") == str(root_items[0].get("id") or ""),
        "implementationIsNotFacilitator": bool(implementation_id) and implementation_id != facilitator_id,
        "exactlyOneAppliedRoomDefine": sum(str(item.get("toolName") or item.get("canonicalToolName") or "") == "room_define" and str(item.get("status") or "") == "applied" for item in definition_receipts) == 1,
    }


def dispatch_lifecycle_checks(tasks: Sequence[Mapping[str, Any]], dispatches: Sequence[Mapping[str, Any]], *, participant_ids: Mapping[str, str], session_ids: Mapping[str, str]) -> dict[str, bool]:
    participant_for = {value: member for member, value in participant_ids.items() if value}
    initial = [item for item in dispatches if str(item.get("intentKind") or "") == "align" and not str(item.get("parentDispatchId") or "") and str(item.get("targetParticipantId") or "") == participant_ids.get(FACILITATOR_MEMBER)]
    implementation = [item for item in dispatches if str(item.get("intentKind") or "") == "execute" and str(item.get("targetParticipantId") or "") == participant_ids.get(IMPLEMENTATION_MEMBER)]
    reviews = [item for item in dispatches if str(item.get("intentKind") or "") == "review" and str(item.get("targetParticipantId") or "") == participant_ids.get(REVIEWER_MEMBER)]
    impl, review = (implementation[-1] if implementation else {}), (reviews[-1] if reviews else {})
    task_by_id = {str(item.get("taskId") or ""): item for item in tasks}
    impl_task_id, review_task = str(impl.get("taskId") or ""), task_by_id.get(str(review.get("taskId") or ""), {})
    parent_alignment = str(impl.get("parentDispatchId") or "")
    parent = next((item for item in dispatches if str(item.get("dispatchId") or "") == parent_alignment), {})
    review_parent = next((item for item in dispatches if str(item.get("dispatchId") or "") == str(review.get("parentDispatchId") or "")), {})
    return {
        "exactlyOneInitialAlignmentDispatch": len(initial) == 1,
        "alignmentDoesNotFanOut": all(str(item.get("intentKind") or "") != "align" or str(item.get("targetParticipantId") or "") == participant_ids.get(FACILITATOR_MEMBER) for item in dispatches),
        "implementationDispatchDistinctAndBound": len(implementation) == 1 and str(impl.get("targetSessionId") or "") == session_ids.get(IMPLEMENTATION_MEMBER) and str(impl.get("parentDispatchId") or "") == str(parent.get("dispatchId") or "") and str(impl.get("rootId") or "") == str(parent.get("rootId") or ""),
        "exactlyOneBoundedImplementationChild": len(implementation) == 1 and bool(impl_task_id) and str(impl.get("taskId") or "") != str(parent.get("taskId") or "") and str(task_by_id.get(impl_task_id, {}).get("parentTaskId") or "") == str(parent.get("taskId") or "") and _integer(impl.get("hopCount")) == _integer(parent.get("hopCount")) + 1 and _integer(impl.get("depth")) == _integer(parent.get("depth")) + 1,
        "reviewIsDistinctOwnershipHandoff": len(reviews) == 1 and str(review.get("targetParticipantId") or "") == participant_ids.get(REVIEWER_MEMBER) and str(review.get("targetSessionId") or "") == session_ids.get(REVIEWER_MEMBER) and bool(review_task) and str(review.get("taskId") or "") != str(parent.get("taskId") or "") and str(review_task.get("taskKind") or "") == "review" and str(review_task.get("parentTaskId") or "") == str(parent.get("taskId") or "") and str(review_parent.get("targetParticipantId") or "") == participant_ids.get(FACILITATOR_MEMBER) and str(review_parent.get("intentKind") or "") == "resume" and _integer(review.get("hopCount")) == _integer(review_parent.get("hopCount")) + 1 and _integer(review.get("depth")) == _integer(review_parent.get("depth")),
        "reviewTaskRecordsReviewedImplementation": bool(review_task) and impl_task_id in {str(value) for value in review_task.get("reviewOfTaskIds") or []},
        "reviewerOwnershipChanged": bool(review_task) and str(review_task.get("currentOwnerParticipantId") or "") == participant_ids.get(REVIEWER_MEMBER) and participant_ids.get(REVIEWER_MEMBER) not in {str(value) for value in review_task.get("reviewAuthorParticipantIds") or []},
        "allDispatchesHaveDistinctSessionBinding": bool(dispatches) and all(str(item.get("targetParticipantId") or "") in participant_for and str(item.get("targetSessionId") or "") == session_ids.get(participant_for.get(str(item.get("targetParticipantId") or ""), "")) for item in dispatches),
    }


def _reviewed_context_evidence_refs(
    tasks: Sequence[Mapping[str, Any]],
    dispatches: Sequence[Mapping[str, Any]],
    *,
    reviewer_id: str,
) -> tuple[str, ...]:
    review_task_ids = {
        str(item.get("taskId") or "")
        for item in dispatches
        if str(item.get("intentKind") or "") == "review"
        and str(item.get("targetParticipantId") or "") == reviewer_id
        and str(item.get("taskId") or "")
    }
    return tuple(dict.fromkeys(
        str(value)
        for task in tasks
        if str(task.get("taskId") or "") in review_task_ids
        for value in task.get("contextEvidenceRefs") or []
        if str(value)
    ))

def _commit_decision(commit: Mapping[str, Any]) -> str:
    direct = str(commit.get("decision") or "").strip()
    if direct in {"deliver", "handoff"}:
        return direct
    continuation = commit.get("continuation")
    if isinstance(continuation, Mapping):
        value = str(continuation.get("decision") or "").strip()
        if value == "complete":
            return "deliver"
        if value == "dispatch":
            return "handoff"
    return ""


def review_delivery_checks(
    commit_payloads: Sequence[Mapping[str, Any]],
    *,
    reviewer_id: str,
    facilitator_id: str,
    reviewed_evidence_refs: Sequence[str],
    dispatches: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, bool]:
    dispatches = dispatches or {}
    review_dispatch_ids = {
        dispatch_id
        for dispatch_id, item in dispatches.items()
        if str(item.get("intentKind") or "") == "review"
        and str(item.get("targetParticipantId") or "") == reviewer_id
    }
    facilitator_dispatch_ids = {
        dispatch_id
        for dispatch_id, item in dispatches.items()
        if str(item.get("targetParticipantId") or "") == facilitator_id
        and str(item.get("intentKind") or "") != "align"
    }
    implementation_dispatch_ids = {
        dispatch_id
        for dispatch_id, item in dispatches.items()
        if str(item.get("targetParticipantId") or "") not in {reviewer_id, facilitator_id}
        and str(item.get("intentKind") or "") == "execute"
    }
    reviewer_commits = [
        item
        for item in commit_payloads
        if _commit_decision(item) == "deliver"
        and (
            str(item.get("dispatchId") or "") in review_dispatch_ids
            or str(item.get("authorActorRef") or item.get("participantId") or "") == reviewer_id
        )
    ]
    final_deliveries = [
        item
        for item in commit_payloads
        if _commit_decision(item) == "deliver"
        and (
            str(item.get("dispatchId") or "") in facilitator_dispatch_ids
            or str(item.get("authorActorRef") or item.get("participantId") or "") == facilitator_id
        )
    ]
    reviewer_refs = {
        str(value)
        for item in reviewer_commits
        for value in item.get("evidenceRefs") or []
        if str(value)
    }
    implementation_refs = {
        str(value)
        for item in commit_payloads
        if str(item.get("dispatchId") or "") in implementation_dispatch_ids
        for value in item.get("evidenceRefs") or []
        if str(value)
    }
    reviewed_refs = {str(value) for value in reviewed_evidence_refs if str(value)}
    reviewer_refs.update(reviewed_refs)
    final_refs = {
        str(value)
        for item in final_deliveries
        for value in item.get("evidenceRefs") or []
        if str(value)
    }
    review_quality = reviewer_commits[0].get("qualityGateReceipt") if len(reviewer_commits) == 1 else {}
    final_quality = final_deliveries[0].get("qualityGateReceipt") if len(final_deliveries) == 1 else {}
    reporter_resume = any(
        str(item.get("targetParticipantId") or "") == facilitator_id
        and str(item.get("intentKind") or "") == "resume"
        for item in dispatches.values()
    )
    return {
        "exactlyOneReviewerRecommendation": len(reviewer_commits) == 1,
        "reviewerRecommendationIsDeliver": len(reviewer_commits) == 1 and _commit_decision(reviewer_commits[0]) == "deliver",
        "reviewerOwnsRecommendation": (
            len(reviewer_commits) == 1
            and (
                str(reviewer_commits[0].get("authorActorRef") or reviewer_commits[0].get("participantId") or reviewer_id)
                == reviewer_id
                or str(reviewer_commits[0].get("dispatchId") or "") in review_dispatch_ids
            )
            and reviewer_id != facilitator_id
        ),
        "reviewReferencesImplementationEvidence": (
            bool(reviewer_refs)
            and bool(implementation_refs)
            and bool(reviewer_refs.intersection(implementation_refs))
        ),
        "reviewReadyHandoffToReporter": (
            isinstance(review_quality, Mapping)
            and str(review_quality.get("verdict") or "") == "ready_to_deliver"
            and reporter_resume
        ),
        "exactlyOneReporterDelivery": len(final_deliveries) == 1,
        "reporterDeliveryUsesReviewerEvidence": (
            len(final_deliveries) == 1
            and bool(reviewer_refs)
            and bool(final_refs.intersection(reviewer_refs))
        ),
        "reporterDeliveryReady": (
            len(final_deliveries) == 1
            and isinstance(final_quality, Mapping)
            and str(final_quality.get("verdict") or "") == "ready_to_deliver"
        ),
        "noNonReporterFinalDelivery": all(
            str(item.get("authorActorRef") or item.get("participantId") or facilitator_id) == facilitator_id
            or str(item.get("dispatchId") or "") in facilitator_dispatch_ids
            for item in final_deliveries
        ),
    }


def reporter_terminal_summary_checks(public_posts: Sequence[Mapping[str, Any]], *, reporter_id: str, root_id: str, terminal_receipt: Mapping[str, Any]) -> dict[str, bool]:
    terminal = [item for item in public_posts if str(item.get("rootId") or "") == root_id and str(item.get("kind") or "") in {"result", "summary"} and str((item.get("publicationSource") or {}).get("kind") or "") == "room_commit"]
    author = lambda item: str(item.get("authorActorRef") or item.get("participantId") or "")
    return {
        "oneReporterTerminalSummary": len(terminal) == 1 and author(terminal[0]) == reporter_id and bool(str(terminal[0].get("content") or "").strip()),
        "noParticipantAuthoredTerminalSummary": all(author(item) == reporter_id for item in terminal),
        "summaryUsesAcceptedTerminalReceipt": len(terminal) == 1 and bool(str((terminal[0].get("publicationSource") or {}).get("ref") or "")) and bool(str(terminal_receipt.get("receiptId") or "")),
        "terminalReceiptAccepted": str(terminal_receipt.get("status") or "") == "applied" and str(terminal_receipt.get("receiptKind") or "") == "terminal",
    }


def participant_configuration_checks(sessions: Mapping[str, Mapping[str, Any]], model_catalogs: Mapping[str, Mapping[str, Any]], *, expected_provider: str, expected_model: str, expected_thinking: str, workspace: Path) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for member in MEMBERS:
        session, catalog = sessions.get(member, {}), model_catalogs.get(member, {})
        selected = catalog.get("selected") if isinstance(catalog.get("selected"), Mapping) else {}
        provider = str(selected.get("provider") or catalog.get("selectedProvider") or "")
        model = str(selected.get("id") or selected.get("modelId") or catalog.get("selectedModel") or "")
        thinking = str(catalog.get("thinkingLevel") or session.get("thinkingLevel") or "")
        roots = [str(Path(value).expanduser().resolve()) for value in session.get("workspaceRoots") or []]
        checks[f"{member}DistinctSession"] = bool(str(session.get("id") or ""))
        checks[f"{member}ProviderMatches"] = provider == expected_provider
        checks[f"{member}ModelMatches"] = model == expected_model
        checks[f"{member}ThinkingMatches"] = thinking == expected_thinking if expected_thinking else bool(thinking)
        checks[f"{member}WorkspaceScope"] = session.get("executionMode") == "workspace_managed" and session.get("workspaceScopeGranted") is True and roots == [str(workspace)]
    return checks


def _workspace_payload_in_root(value: object, workspace: Path) -> bool:
    if not isinstance(value, Mapping):
        return True
    for key in ("path", "cwd", "workspaceRoot"):
        raw = value.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            candidate.resolve(strict=False).relative_to(workspace)
        except ValueError:
            return False
    return True


def workspace_receipt_checks(
    tool_receipts: Sequence[Mapping[str, Any]],
    *,
    dispatches: Mapping[str, Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
    session_ids: Mapping[str, str],
    workspace: Path,
) -> dict[str, bool]:
    rows = [
        item
        for item in tool_receipts
        if str(item.get("toolName") or "").startswith("workspace_")
    ]
    session_values = {str(value) for value in session_ids.values()}
    tasks_by_id = {
        str(item.get("taskId") or ""): item
        for item in tasks
        if str(item.get("taskId") or "")
    }

    def payload_stays_in_authorized_root(item: Mapping[str, Any]) -> bool:
        dispatch = dispatches.get(str(item.get("dispatchId") or ""), {})
        task = tasks_by_id.get(str(dispatch.get("taskId") or ""), {})
        task_root = str(
            task.get("workspaceRoot")
            or task.get("workspaceBaseRoot")
            or workspace
        )
        return _workspace_payload_in_root(
            item.get("command"),
            Path(task_root).expanduser().resolve(strict=False),
        )

    checks = {
        "workspaceEffectsObserved": bool(rows),
        "workspaceEffectsUseAppliedReceipts": bool(rows) and all(str(item.get("status") or "") == "applied" and len(str(item.get("resultHash") or "")) == 64 for item in rows),
        "workspaceEffectsUseBoundDispatches": bool(rows) and all(str(item.get("dispatchId") or "") in dispatches and str(item.get("sessionId") or "") == str(dispatches[str(item.get("dispatchId") or "")].get("targetSessionId") or "") and str(item.get("sessionId") or "") in session_values for item in rows),
        "workspacePathsStayInAuthorizedRoot": bool(rows) and all(payload_stays_in_authorized_root(item) for item in rows),
        "implementationWorkspaceReceiptObserved": any(str(item.get("sessionId") or "") == str(session_ids.get(IMPLEMENTATION_MEMBER) or "") for item in rows),
        "reviewerWorkspaceReceiptObserved": any(str(item.get("sessionId") or "") == str(session_ids.get(REVIEWER_MEMBER) or "") for item in rows),
    }
    return checks


def terminal_receipt_checks(root: Mapping[str, Any], receipt: Mapping[str, Any], quiescence: Mapping[str, Any]) -> dict[str, bool]:
    receipt_id = str(receipt.get("receiptId") or "")
    return {
        "rootCompleted": str(root.get("state") or "") == "completed",
        "terminalReceiptAccepted": bool(receipt_id) and str(receipt.get("status") or "") == "applied" and str(receipt.get("receiptKind") or "") == "terminal",
        "rootPointsToTerminalReceipt": bool(receipt_id) and str(root.get("terminalReceiptId") or "") == receipt_id,
        "runtimeQuiescent": quiescence.get("passed") is True and not list(quiescence.get("remainingTargetSessionIds") or []),
    }


def _configure_session(base_url: str, *, requester: JsonRequester, session_id: str, model_provider: str, model_id: str, thinking_level: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if model_provider and model_id:
        result["model"] = requester(base_url, "POST", f"/api/agent/sessions/{encoded(session_id)}/model", {"provider": model_provider, "modelId": model_id})
    if thinking_level:
        result["thinking"] = requester(base_url, "POST", f"/api/agent/sessions/{encoded(session_id)}/thinking", {"level": thinking_level})
    return result


def _room_work_items(base_url: str, room_id: str, *, requester: JsonRequester) -> dict[str, Any]:
    return requester(base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/work-items?limit=100", timeout=15)


def _find_wait_post(snapshot: Mapping[str, Any], *, root_id: str, seen_post_ids: set[str]) -> dict[str, Any] | None:
    posts = sorted([dict(item) for item in snapshot.get("posts") or [] if isinstance(item, Mapping)], key=lambda value: (int(value.get("createdAtMs") or 0), str(value.get("postId") or "")))
    for post in reversed(posts):
        question, source, post_id = post.get("question"), post.get("publicationSource"), str(post.get("postId") or "")
        options = question.get("options") if isinstance(question, Mapping) else None
        if post_id and post_id not in seen_post_ids and str(post.get("rootId") or "") == root_id and str(post.get("kind") or "") == "wait" and isinstance(source, Mapping) and str(source.get("kind") or "") == "room_commit" and isinstance(question, Mapping) and str(question.get("prompt") or "").strip() and isinstance(options, list) and len(options) in {0, 2, 3, 4, 5}:
            return post
    return None


def authoritative_wait_post_checks(post: Mapping[str, Any], dispatch: Mapping[str, Any], *, root_id: str, task_id: str) -> dict[str, bool]:
    source, question = post.get("publicationSource"), post.get("question")
    return {
        "canonicalWaitKind": str(post.get("kind") or "") == "wait",
        "canonicalCommitSource": isinstance(source, Mapping) and str(source.get("kind") or "") == "room_commit" and bool(str(source.get("ref") or "")),
        "sameRootAndTask": str(post.get("rootId") or "") == root_id and str(post.get("taskId") or "") in {"", task_id} and str(dispatch.get("rootId") or "") == root_id and str(dispatch.get("taskId") or "") == task_id,
        "alignmentDispatchWaitsForUser": str(dispatch.get("intentKind") or "") in {"align", "resume"} and str(dispatch.get("waitingFor") or dispatch.get("waitingForParticipant") or "") in {"user", "waitingForUser", ""},
        "questionAndOptionsPublished": isinstance(question, Mapping) and bool(str(question.get("prompt") or "").strip()) and isinstance(question.get("options"), list) and len(question["options"]) in {0, 2, 3, 4, 5},
    }


def _wait_for_alignment_question(base_url: str, room_id: str, root_id: str, task_id: str, *, requester: JsonRequester, seen_post_ids: set[str], timeout: float) -> dict[str, Any]:
    deadline, last = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        snapshot = requester(base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot", timeout=15)
        last = snapshot
        post = _find_wait_post(snapshot, root_id=root_id, seen_post_ids=seen_post_ids)
        if post is not None:
            dispatch = next((item for item in snapshot.get("dispatches") or [] if isinstance(item, Mapping) and str(item.get("dispatchId") or "") == str(post.get("dispatchId") or "")), {})
            checks = authoritative_wait_post_checks(post, dispatch, root_id=root_id, task_id=task_id)
            if not all(checks.values()):
                raise RuntimeError(f"invalid authoritative wait-for-user Room post: {checks}")
            return {"kind": "question", "snapshot": snapshot, "post": post, "dispatch": dict(dispatch), "checks": checks}
        time.sleep(0.1)
    raise TimeoutError(f"Room did not publish a wait-for-user question: {last}")


def _wait_for_alignment_progress(base_url: str, room_id: str, root_id: str, task_id: str, *, requester: JsonRequester, seen_post_ids: set[str], timeout: float) -> dict[str, Any]:
    deadline, last = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        snapshot = requester(base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot", timeout=15)
        work = _work_items(_room_work_items(base_url, room_id, requester=requester))
        last = snapshot
        projection, catalog = _root_requirements(snapshot, root_id), None
        if isinstance(projection.get("catalog"), Mapping):
            catalog = projection["catalog"]
        # Snapshot and WorkItem list are separate HTTP reads. A definition may
        # commit between them, so only the next coherent snapshot proves it.
        post = _find_wait_post(snapshot, root_id=root_id, seen_post_ids=seen_post_ids)
        if post is not None:
            dispatch = next((item for item in snapshot.get("dispatches") or [] if isinstance(item, Mapping) and str(item.get("dispatchId") or "") == str(post.get("dispatchId") or "")), {})
            checks = authoritative_wait_post_checks(post, dispatch, root_id=root_id, task_id=task_id)
            if not all(checks.values()):
                raise RuntimeError(f"invalid resumed wait-for-user post: {checks}")
            return {"kind": "question", "snapshot": snapshot, "post": post, "dispatch": dict(dispatch), "workItems": work, "checks": checks}
        if work and _catalog_is_defined(catalog):
            return {"kind": "defined", "snapshot": snapshot, "workItems": work}
        time.sleep(0.1)
    raise TimeoutError(f"Room did not resume or define after ordinary answer: {last}")

def _kernel_receipts(db_path: Path, root_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM room_kernel_receipts WHERE root_id = ? ORDER BY created_at_ms, receipt_id",
            (root_id,),
        ).fetchall()
    receipts: list[dict[str, Any]] = []
    for (encoded_payload,) in rows:
        try:
            payload = json.loads(str(encoded_payload))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            receipts.append(dict(payload))
    return receipts


def authoritative_receipt_checks(
    receipts: Sequence[Mapping[str, Any]],
    *,
    root_id: str,
    reporter_id: str,
    resume_receipt_ids: Sequence[str] = (),
) -> dict[str, bool]:
    root_receipts = [
        item
        for item in receipts
        if str(item.get("rootId") or "") == root_id
        and str(item.get("status") or "") == "applied"
    ]
    selections = [
        item
        for item in root_receipts
        if str((item.get("details") or {}).get("purpose") or "") == "reporter_selection"
    ]
    expected_resume_ids = {str(value) for value in resume_receipt_ids if str(value)}
    resumes = [
        item
        for item in root_receipts
        if str(item.get("receiptId") or "") in expected_resume_ids
        or bool((item.get("details") or {}).get("resumedDispatchId"))
    ]
    return {
        "authoritativeReceiptsObserved": bool(root_receipts),
        "reporterSelectionReceiptAccepted": (
            len(selections) == 1
            and str((selections[0].get("details") or {}).get("reporterParticipantId") or "") == reporter_id
            and str(selections[0].get("receiptKind") or "") == "accepted"
        ),
        "resumeReceiptAccepted": (
            bool(resumes)
            and all(
                str(item.get("receiptKind") or "") == "accepted"
                and isinstance(item.get("details"), Mapping)
                and bool(item.get("details", {}).get("resumedDispatchId"))
                for item in resumes
            )
        ),
    }


def _tool_rows(db_path: Path, root_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("""
            SELECT invocation.receipt_id, invocation.canonical_tool_name, manifest.dispatch_id,
                   manifest.task_id, binding.session_id, invocation.command_json, execution.status,
                   execution.result_hash, execution.payload_json
            FROM room_v2_tool_invocation_receipts AS invocation
            JOIN room_v2_capability_manifests AS manifest ON manifest.manifest_id = invocation.manifest_id AND manifest.manifest_hash = invocation.manifest_hash
            JOIN room_v2_capability_runtime_bindings AS binding ON binding.manifest_id = manifest.manifest_id AND binding.manifest_hash = manifest.manifest_hash
            LEFT JOIN room_v2_tool_execution_receipts AS execution ON execution.invocation_receipt_id = invocation.receipt_id
            WHERE manifest.root_id = ? ORDER BY invocation.created_at_ms, invocation.receipt_id
        """, (root_id,)).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try: command = json.loads(str(row[5] or "{}"))
        except json.JSONDecodeError: command = {}
        try: payload = json.loads(str(row[8] or "{}"))
        except json.JSONDecodeError: payload = {}
        result.append({"invocationReceiptId": str(row[0]), "toolName": str(row[1]), "dispatchId": str(row[2]), "taskId": str(row[3]), "sessionId": str(row[4]), "command": command.get("arguments") if isinstance(command, Mapping) else command, "status": str(row[6] or ""), "resultHash": str(row[7] or ""), "payload": payload})
    return result


def _definition_receipts(
    tool_rows: Sequence[Mapping[str, Any]],
    kernel_receipts: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    result = [
        {
            **dict(row),
            "acceptanceAliases": {},
        }
        for row in tool_rows
        if str(row.get("toolName") or "") == "room_define"
    ]
    for receipt in kernel_receipts:
        details = receipt.get("details")
        if not isinstance(details, Mapping) or str(details.get("operation") or "") != "room_define":
            continue
        invocation_id = str(details.get("invocationReceiptId") or "")
        aliases = dict(details.get("acceptanceAliases") or {})
        matched = next(
            (
                item
                for item in result
                if str(item.get("invocationReceiptId") or "") == invocation_id
            ),
            None,
        )
        if matched is not None:
            matched["status"] = str(receipt.get("status") or matched.get("status") or "")
            matched["acceptanceAliases"] = aliases
        else:
            result.append(
                {
                    "toolName": "room_define",
                    "status": str(receipt.get("status") or ""),
                    "invocationReceiptId": invocation_id,
                    "acceptanceAliases": aliases,
                }
            )
    return result


def _commit_payloads(db_path: Path, root_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT dispatch_id, payload_json FROM room_kernel_commits WHERE root_id = ? ORDER BY created_at_ms, dispatch_id", (root_id,)).fetchall()
    result = []
    for dispatch_id, encoded_payload in rows:
        try: payload = json.loads(str(encoded_payload))
        except json.JSONDecodeError: continue
        if isinstance(payload, Mapping): result.append({"dispatchId": str(dispatch_id), **dict(payload)})
    return result


def wait_for_sessions_quiescent(base_url: str, *, requester: JsonRequester, session_ids: Sequence[str], timeout: float, poll_interval: float = 0.1) -> dict[str, Any]:
    targets, deadline, last, polls = {str(value) for value in session_ids if str(value)}, time.monotonic() + timeout, {}, 0
    while time.monotonic() < deadline:
        last, polls = requester(base_url, "GET", "/api/agent/runtime", timeout=15), polls + 1
        active = {str(value) for value in last.get("activeSessionIds") or [] if str(value)}
        if not targets.intersection(active):
            return {"passed": True, "pollCount": polls, "remainingTargetSessionIds": [], "runtimeStatus": last.get("status")}
        time.sleep(poll_interval)
    raise TimeoutError(f"target Pi sessions did not settle: remaining={sorted(targets & {str(value) for value in last.get('activeSessionIds') or []})}")


def _wait_for_root_terminal(base_url: str, room_id: str, root_id: str, *, requester: JsonRequester, timeout: float) -> dict[str, Any]:
    deadline, last = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        last = requester(base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot", timeout=15)
        roots, _, _ = _root_snapshot(last, root_id)
        if roots and str(roots[0].get("state") or "") in {"completed", "failed", "cancelled", "cancelled_with_unknowns"}:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"Room Root did not reach terminal state: {last}")


def _session_model_catalogs(base_url: str, *, requester: JsonRequester, sessions: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {member: requester(base_url, "GET", f"/api/agent/sessions/{encoded(str(session.get('id') or ''))}/models", timeout=30) for member, session in sessions.items()}


def _provider_usage_checks(base_url: str, *, requester: JsonRequester, session_ids: Mapping[str, str]) -> tuple[dict[str, bool], dict[str, Any]]:
    checks, evidence = {}, {}
    for member, session_id in session_ids.items():
        response = requester(base_url, "GET", f"/api/agent/sessions/{encoded(session_id)}/debug-context", timeout=30)
        context = response.get("context") if isinstance(response.get("context"), Mapping) else response
        receipts = [item for item in context.get("providerRequestReceipts") or [] if isinstance(item, Mapping)]
        receipt_usages = [dict(item["usage"]) for item in receipts if isinstance(item.get("usage"), Mapping)]
        model_call_usages = [
            dict(assistant["usage"])
            for call in context.get("modelCalls") or []
            if isinstance(call, Mapping)
            and isinstance(call.get("assistantMessage"), Mapping)
            for assistant in [call["assistantMessage"]]
            if isinstance(assistant.get("usage"), Mapping)
        ]
        usages = [*receipt_usages, *model_call_usages]
        checks[f"{member}UsageReceiptObserved"] = any(
            any(isinstance(value, (int, float)) and value > 0 for value in usage.values())
            for usage in usages
        )
        evidence[member] = {
            "providerRequestReceiptCount": len(receipts),
            "modelCallUsageCount": len(model_call_usages),
            "usageReceipts": usages,
        }
    return checks, evidence

def _tool_receipt_checks(
    tool_rows: Sequence[Mapping[str, Any]],
    *,
    dispatches: Mapping[str, Mapping[str, Any]],
    facilitator_id: str = "",
) -> dict[str, bool]:
    collaboration_rows = [item for item in tool_rows if str(item.get("toolName") or "") == "room_collaborate"]
    collaboration_dispatch = dispatches.get(str(collaboration_rows[0].get("dispatchId") or ""), {}) if len(collaboration_rows) == 1 else {}
    target_matches = (
        bool(str(collaboration_dispatch.get("targetParticipantId") or ""))
        if not facilitator_id
        else str(collaboration_dispatch.get("targetParticipantId") or "") == facilitator_id
    )
    return {
        "toolReceiptsObservable": bool(tool_rows),
        "toolReceiptsBindDispatches": bool(tool_rows) and all(str(item.get("dispatchId") or "") in dispatches for item in tool_rows),
        "toolExecutionsAccepted": bool(tool_rows) and all(str(item.get("status") or "") == "applied" and len(str(item.get("resultHash") or "")) == 64 for item in tool_rows),
        "exactlyOneRoomDefineInvocation": sum(str(item.get("toolName") or "") == "room_define" for item in tool_rows) == 1,
        "exactlyOneRoomCollaborateInvocation": len(collaboration_rows) == 1,
        "roomCollaborateOnlyFacilitator": len(collaboration_rows) == 1 and str(collaboration_dispatch.get("intentKind") or "") in {"align", "resume"} and target_matches,
        "roomCommitReceiptsObserved": any(str(item.get("toolName") or "") == "room_commit" for item in tool_rows),
    }


def _public_posts_from_timeline_snapshot(snapshot: Mapping[str, Any], *, root_id: str) -> list[dict[str, Any]]:
    posts: dict[str, dict[str, Any]] = {}
    for raw in snapshot.get("posts") or []:
        if isinstance(raw, Mapping) and str(raw.get("rootId") or "") == root_id and str((raw.get("publicationSource") or {}).get("kind") or "") in {"room_post", "room_commit", "user"}:
            posts[str(raw.get("postId") or len(posts))] = dict(raw)
    for event in snapshot.get("events") or []:
        if not isinstance(event, Mapping) or event.get("eventType") != "room_post":
            continue
        payload, post = event.get("payload"), None
        if isinstance(payload, Mapping):
            post = payload.get("post")
        if isinstance(post, Mapping) and str(post.get("rootId") or "") == root_id and str((post.get("publicationSource") or {}).get("kind") or "") in {"room_post", "room_commit", "user"}:
            posts[str(post.get("postId") or len(posts))] = dict(post)
    return sorted(posts.values(), key=lambda item: (int(item.get("createdAtMs") or 0), str(item.get("postId") or "")))


def run(args: argparse.Namespace, *, requester: JsonRequester = request_json) -> dict[str, Any]:
    stamp, workspace = int(time.time() * 1000), args.workspace.expanduser().resolve(strict=True)
    leaks = natural_message_leaks([OPENING_MESSAGE, *NATURAL_REQUIREMENT_ANSWERS])
    if leaks: raise RuntimeError("natural Room messages contain execution vocabulary: " + ", ".join(leaks))
    participant_roles = list(args.participant_roles)
    created = requester(args.base_url, "POST", "/api/agent/rooms", {"title": f"Three member full-auto Room canary {stamp}", "roomKind": "collaboration", "routingPolicy": "natural", "moderatorRoleId": str(participant_roles[0].get("roleId") or ""), "workspaceRoots": [str(workspace)], "executionMode": "workspace_managed", "workspaceScopeConfirmation": "APPROVE_WORKSPACE_SCOPE", "participants": participant_roles})
    room = created.get("room") if isinstance(created.get("room"), Mapping) else {}
    participants = [dict(item) for item in room.get("participants") or [] if isinstance(item, Mapping)]
    if len(participants) != 3: raise RuntimeError("Room creation did not return three configured participants")
    members = {member: participants[index] for index, member in enumerate(MEMBERS)}
    participant_ids = {member: str(value.get("id") or value.get("participantId") or "") for member, value in members.items()}
    session_ids = {member: str(value.get("sessionId") or "") for member, value in members.items()}
    if len(set(participant_ids.values())) != 3 or len(set(session_ids.values())) != 3: raise RuntimeError("Room participant or Session identities are not distinct")
    room_id = str(room.get("id") or "")
    if not room_id: raise RuntimeError("Room creation returned no Room id")
    configuration_responses = {member: _configure_session(args.base_url, requester=requester, session_id=session_ids[member], model_provider=str(args.model_provider or ""), model_id=str(args.model_id or ""), thinking_level=str(args.thinking_level or "")) for member in MEMBERS}
    listed = requester(args.base_url, "GET", "/api/agent/sessions?includeInternal=true&limit=500", timeout=15)
    session_by_id = {str(item.get("id") or ""): dict(item) for item in listed.get("items") or [] if isinstance(item, Mapping)}
    sessions = {member: session_by_id.get(session_ids[member], {}) for member in MEMBERS}
    catalogs = _session_model_catalogs(args.base_url, requester=requester, sessions=sessions)
    configuration_checks = participant_configuration_checks(sessions, catalogs, expected_provider=str(args.model_provider or ""), expected_model=str(args.model_id or ""), expected_thinking=str(args.thinking_level or ""), workspace=workspace)
    opening_response = requester(args.base_url, "POST", f"/api/agent/rooms/{encoded(room_id)}/messages", {"message": OPENING_MESSAGE, "clientMessageId": f"room-full-auto-opening:{stamp}"}, timeout=30)
    root_id = accepted_root_id(dict(opening_response))
    task = opening_response.get("task")
    task_id = str(opening_response.get("taskId") or (task.get("taskId") if isinstance(task, Mapping) else ""))
    if not task_id: raise RuntimeError("Room opening returned no canonical Task id")
    initial_snapshot = requester(args.base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot", timeout=30)
    initial_checks = initial_intake_checks(opening_response, initial_snapshot, root_id=root_id, task_id=task_id, opening=OPENING_MESSAGE, facilitator_id=participant_ids[FACILITATOR_MEMBER], work_items=_work_items(_room_work_items(args.base_url, room_id, requester=requester)))
    if not all(initial_checks.values()): raise RuntimeError(f"Room initial full-auto contract failed: {initial_checks}")
    receipt_checks = authoritative_receipt_checks(
        _kernel_receipts(args.db_path, root_id),
        root_id=root_id,
        reporter_id=participant_ids[FACILITATOR_MEMBER],
    )
    if not receipt_checks["reporterSelectionReceiptAccepted"]:
        raise RuntimeError(f"Room reporter selection receipt missing or invalid: {receipt_checks}")
    resume_receipt_ids: list[str] = []
    seen_wait_post_ids: set[str] = set()
    answers: list[dict[str, Any]] = []
    progress = _wait_for_alignment_question(args.base_url, room_id, root_id, task_id, requester=requester, seen_post_ids=seen_wait_post_ids, timeout=workflow_timeout_seconds(args))
    while True:
        post, index = progress["post"], len(answers)
        seen_wait_post_ids.add(str(post.get("postId") or ""))
        if index >= MAX_CLARIFICATION_QUESTIONS: raise RuntimeError("Room asked more clarification questions than the canary answers")
        answer, before = NATURAL_REQUIREMENT_ANSWERS[index], progress["snapshot"]
        before_work = _work_items(_room_work_items(args.base_url, room_id, requester=requester))
        if before_work: raise RuntimeError("WorkItem exists while a wait-for-user clarification is pending")
        response = requester(args.base_url, "POST", f"/api/agent/rooms/{encoded(room_id)}/messages", {"message": answer, "clientMessageId": f"room-full-auto-answer:{stamp}:{index}"}, timeout=30)
        if accepted_root_id(dict(response)) != root_id: raise RuntimeError("ordinary clarification answer created a new Root")
        resume_receipt = response.get("resumeReceipt")
        if isinstance(resume_receipt, Mapping):
            resume_receipt_ids.append(str(resume_receipt.get("receiptId") or ""))
        receipt_checks = authoritative_receipt_checks(
            _kernel_receipts(args.db_path, root_id),
            root_id=root_id,
            reporter_id=participant_ids[FACILITATOR_MEMBER],
            resume_receipt_ids=resume_receipt_ids,
        )
        if not receipt_checks["resumeReceiptAccepted"]:
            raise RuntimeError(f"Room resume receipt missing or invalid: {receipt_checks}")
        next_progress = _wait_for_alignment_progress(args.base_url, room_id, root_id, task_id, requester=requester, seen_post_ids=seen_wait_post_ids, timeout=workflow_timeout_seconds(args))
        checks = clarification_transition_checks(before, response, next_progress["snapshot"], root_id=root_id, task_id=task_id, waiting_dispatch=progress.get("dispatch") or {}, answer=answer, work_items_before=before_work, work_items_after=next_progress.get("workItems") or [], definition_applied=next_progress.get("kind") == "defined")
        answers.append({"answer": answer, "questionPost": post, "response": response, "checks": checks, "passed": all(checks.values())})
        if not all(checks.values()): raise RuntimeError(f"Room clarification transition failed: {checks}")
        if next_progress.get("kind") == "defined":
            definition_progress = next_progress
            break
        progress = next_progress
    definition_projection = _root_requirements(definition_progress["snapshot"], root_id)
    definition_work_items = list(definition_progress.get("workItems") or [])
    tool_rows_before = _tool_rows(args.db_path, root_id)
    definition_receipts = _definition_receipts(
        tool_rows_before,
        _kernel_receipts(args.db_path, root_id),
    )
    definition_result_checks = definition_checks(definition_projection, definition_work_items, definition_receipts, root_id=root_id, facilitator_id=participant_ids[FACILITATOR_MEMBER], implementation_id=participant_ids[IMPLEMENTATION_MEMBER])
    if not all(definition_result_checks.values()): raise RuntimeError(f"Room definition contract failed: {definition_result_checks}")
    try:
        terminal_snapshot = _wait_for_root_terminal(args.base_url, room_id, root_id, requester=requester, timeout=workflow_timeout_seconds(args))
    except BaseException:
        cancel_root(args.base_url, room_id, root_id, requester=requester, timeout=max(30, float(args.turn_timeout)))
        raise
    terminal_roots, terminal_tasks, terminal_dispatches = _root_snapshot(terminal_snapshot, root_id)
    if len(terminal_roots) != 1: raise RuntimeError("Room terminal snapshot did not contain exactly one Root")
    dispatch_by_id = {str(item.get("dispatchId") or ""): item for item in terminal_dispatches}
    lifecycle_checks = dispatch_lifecycle_checks(terminal_tasks, terminal_dispatches, participant_ids=participant_ids, session_ids=session_ids)
    tool_rows = _tool_rows(args.db_path, root_id)
    tool_checks = _tool_receipt_checks(tool_rows, dispatches=dispatch_by_id, facilitator_id=participant_ids[FACILITATOR_MEMBER])
    workspace_checks = workspace_receipt_checks(
        tool_rows,
        dispatches=dispatch_by_id,
        tasks=terminal_tasks,
        session_ids=session_ids,
        workspace=workspace,
    )
    review_dispatch_ids = {
        str(item.get("dispatchId") or "")
        for item in terminal_dispatches
        if str(item.get("intentKind") or "") == "review"
        and str(item.get("targetParticipantId") or "") == participant_ids[REVIEWER_MEMBER]
    }
    commit_payloads = _commit_payloads(args.db_path, root_id)
    reviewed_refs = _reviewed_context_evidence_refs(
        terminal_tasks,
        terminal_dispatches,
        reviewer_id=participant_ids[REVIEWER_MEMBER],
    )
    delivery_checks = review_delivery_checks(
        commit_payloads,
        reviewer_id=participant_ids[REVIEWER_MEMBER],
        facilitator_id=participant_ids[FACILITATOR_MEMBER],
        reviewed_evidence_refs=reviewed_refs,
        dispatches=dispatch_by_id,
    )
    finalized = requester(args.base_url, "POST", f"/api/agent/rooms/{encoded(room_id)}/kernel/finalize", {"rootId": root_id}, timeout=30)
    terminal_receipt = finalized.get("receipt") if isinstance(finalized.get("receipt"), Mapping) else {}
    terminal_snapshot = requester(args.base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot", timeout=30)
    terminal_roots, _, _ = _root_snapshot(terminal_snapshot, root_id)
    runtime_quiescence = wait_for_sessions_quiescent(args.base_url, requester=requester, session_ids=list(session_ids.values()), timeout=min(120.0, max(30.0, float(args.turn_timeout))))
    public_snapshot = requester(args.base_url, "GET", f"/api/agent/rooms/{encoded(room_id)}/snapshot", timeout=30)
    public_posts = _public_posts_from_timeline_snapshot(public_snapshot, root_id=root_id)
    reporter_id = str(terminal_roots[0].get("reporterParticipantId") or participant_ids[FACILITATOR_MEMBER]) if terminal_roots else participant_ids[FACILITATOR_MEMBER]
    receipt_checks = authoritative_receipt_checks(
        _kernel_receipts(args.db_path, root_id),
        root_id=root_id,
        reporter_id=reporter_id,
        resume_receipt_ids=resume_receipt_ids,
    )
    public_checks = reporter_terminal_summary_checks(public_posts, reporter_id=reporter_id, root_id=root_id, terminal_receipt=terminal_receipt)
    terminal_checks = terminal_receipt_checks(terminal_roots[0] if terminal_roots else {}, terminal_receipt, runtime_quiescence)
    usage_checks, usage_evidence = _provider_usage_checks(args.base_url, requester=requester, session_ids=session_ids)
    checks = {**{f"initial.{key}": value for key, value in initial_checks.items()}, **{f"clarification.{index}.{key}": value for index, answer in enumerate(answers, start=1) for key, value in answer["checks"].items()}, **{f"definition.{key}": value for key, value in definition_result_checks.items()}, **{f"lifecycle.{key}": value for key, value in lifecycle_checks.items()}, **{f"tool.{key}": value for key, value in tool_checks.items()}, **{f"workspace.{key}": value for key, value in workspace_checks.items()}, **{f"receipt.{key}": value for key, value in receipt_checks.items()}, **{f"delivery.{key}": value for key, value in delivery_checks.items()}, **{f"public.{key}": value for key, value in public_checks.items()}, **{f"terminal.{key}": value for key, value in terminal_checks.items()}, **{f"configuration.{key}": value for key, value in configuration_checks.items()}, **{f"usage.{key}": value for key, value in usage_checks.items()}, "naturalMessagesContainNoExecutionVocabulary": not leaks}
    return {"schemaVersion": SCHEMA_VERSION, "roomId": room_id, "rootId": root_id, "taskId": task_id, "openingMessage": OPENING_MESSAGE, "clarificationAnswers": answers, "definition": {"projection": definition_projection, "workItems": definition_work_items, "receipts": definition_receipts}, "members": {member: {"participantId": participant_ids[member], "sessionId": session_ids[member], "configuration": configuration_responses[member], "modelCatalog": catalogs[member]} for member in MEMBERS}, "dispatches": terminal_dispatches, "tasks": terminal_tasks, "toolReceipts": tool_rows, "usageReceipts": usage_evidence, "workspaceReceipts": [row for row in tool_rows if str(row.get("toolName") or "").startswith("workspace_")], "publicPosts": public_posts, "terminal": {"root": terminal_roots[0] if terminal_roots else None, "receipt": terminal_receipt}, "runtimeQuiescence": runtime_quiescence, "checks": checks}


if __name__ == "__main__":
    raise SystemExit("Use run_room_context_epoch_in_process.py --scenario project-collaboration")
