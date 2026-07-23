#!/usr/bin/env python3
"""Verify a completed Room context canary without invoking the Provider again."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from room_context_epoch_canary import (
    _FORBIDDEN_MEMORY_METADATA,
    _provider_session_memory_blocks,
    debug_evidence,
    encoded,
    progressive_discovery_check,
    provider_prefix_evidence,
    request_json,
    transcript_evidence,
)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _transition_evidence(
    db_path: Path,
    *,
    session_id: str,
    source_ref: str,
) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT from_epoch, to_epoch, epoch_reason, evidence_json
            FROM room_v2_session_context_epoch_transitions
            WHERE session_id = ? AND source_ref = ?
            """,
            (session_id, source_ref),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"No context transition for {session_id} / {source_ref}")
    evidence = json.loads(row[3])
    tool_receipt_ids = [
        str(value)
        for value in evidence.get("toolReceiptIds") or []
        if str(value).strip()
    ]
    tool_receipts: list[dict[str, Any]] = []
    skill_receipt = None
    with sqlite3.connect(db_path) as connection:
        if tool_receipt_ids:
            placeholders = ",".join("?" for _ in tool_receipt_ids)
            tool_rows = connection.execute(
                f"""
                SELECT receipt_id, tool_name, schema_hash, receipt_kind
                FROM room_v2_tool_disclosure_receipts
                WHERE receipt_id IN ({placeholders})
                ORDER BY receipt_id
                """,
                tool_receipt_ids,
            ).fetchall()
            tool_receipts = [
                {
                    "receiptId": str(item[0]),
                    "toolName": str(item[1]),
                    "schemaHash": str(item[2]),
                    "kind": str(item[3]),
                }
                for item in tool_rows
            ]
        skill_receipt_id = str(evidence.get("skillReceiptId") or "")
        if skill_receipt_id:
            skill_row = connection.execute(
                """
                SELECT receipt_id, skill_id, skill_hash, load_reason
                FROM room_v2_skill_load_receipts
                WHERE receipt_id = ?
                """,
                (skill_receipt_id,),
            ).fetchone()
            if skill_row is not None:
                skill_receipt = {
                    "receiptId": str(skill_row[0]),
                    "skillId": str(skill_row[1]),
                    "skillHash": str(skill_row[2]),
                    "loadReason": str(skill_row[3]),
                }
    return {
        "from": row[0],
        "to": row[1],
        "reason": row[2],
        "originalRequirementCount": evidence.get("originalRequirementCount"),
        "currentTaskPresent": evidence.get("currentTaskPresent"),
        "acceptanceCount": evidence.get("acceptanceCount"),
        "blockerCount": evidence.get("blockerCount"),
        "handoffPresent": evidence.get("handoffPresent"),
        "skillReceiptPresent": bool(evidence.get("skillReceiptId")),
        "skillReceipt": skill_receipt,
        "toolReceiptCount": len(tool_receipt_ids),
        "toolReceiptIds": tool_receipt_ids,
        "toolReceipts": tool_receipts,
        "providerHashes": [
            str(value)
            for value in (
                evidence.get("roomProviderEntryHash"),
                evidence.get("sessionProviderEntryHash"),
            )
            if str(value or "").strip()
        ],
    }


def _turn_memory_evidence(
    base_url: str,
    session_id: str,
    turn_id: str,
) -> dict[str, Any]:
    debug = request_json(
        base_url,
        "GET",
        (
            f"/api/agent/sessions/{encoded(session_id)}/debug-context"
            f"?turnId={encoded(turn_id)}"
        ),
        timeout=20,
    )
    context = debug.get("context") or {}
    blocks = _provider_session_memory_blocks(context.get("providerRequests") or [])
    forbidden = sorted(
        {
            token
            for block in blocks
            for token in _FORBIDDEN_MEMORY_METADATA
            if token in block
        }
    )
    return {
        "turnId": turn_id,
        "blockCount": len(blocks),
        "nonEmptyBlockCount": sum("## Session 记忆" in block for block in blocks),
        "forbiddenMetadata": forbidden,
        "assistantConversationBlockCount": sum(
            "## 最近对话" in block or "**Agent**" in block
            for block in blocks
        ),
        "source": "live_debug_context",
    }


def _recorded_memory_evidence(
    value: object,
    *,
    turn_id: str,
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    block_count = value.get("blockCount")
    non_empty_count = value.get("nonEmptyBlockCount")
    forbidden = value.get("forbiddenMetadata")
    assistant_conversation_count = value.get(
        "assistantConversationBlockCount",
        0,
    )
    if not isinstance(block_count, int) or not isinstance(non_empty_count, int):
        return None
    if (
        not isinstance(assistant_conversation_count, int)
        or isinstance(assistant_conversation_count, bool)
        or not isinstance(forbidden, list)
        or not all(
            isinstance(item, str) for item in forbidden
        )
    ):
        return None
    return {
        "turnId": turn_id,
        "blockCount": block_count,
        "nonEmptyBlockCount": non_empty_count,
        "forbiddenMetadata": forbidden,
        "assistantConversationBlockCount": (
            assistant_conversation_count
        ),
        "source": source,
    }


def _prior_memory_by_turn(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    epochs = raw.get("epochs") if isinstance(raw, dict) else None
    if not isinstance(epochs, list):
        raise RuntimeError("Recorded evidence is missing its epoch list")
    result: dict[str, dict[str, Any]] = {}
    for item in epochs:
        if not isinstance(item, dict):
            continue
        turn_id = str(item.get("turnId") or "")
        memory = _recorded_memory_evidence(
            item.get("memory"),
            turn_id=turn_id,
            source="recorded_evidence",
        )
        if turn_id and memory is not None:
            result[turn_id] = memory
    return result


def _recorded_provider_prefix_evidence(
    value: object,
    *,
    turn_id: str,
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("schemaVersion") != "wisdom-weasel.provider-prefix-evidence.v1":
        return None
    if not isinstance(value.get("passed"), bool):
        return None
    checks = value.get("checks")
    calls = value.get("calls")
    transitions = value.get("transitions")
    if (
        not isinstance(checks, dict)
        or not all(isinstance(item, bool) for item in checks.values())
        or not isinstance(calls, list)
        or not isinstance(transitions, list)
    ):
        return None
    return {
        **value,
        "turnId": turn_id,
        "source": source,
    }


def _prior_provider_prefix_by_turn(
    path: Path | None,
) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    epochs = raw.get("epochs") if isinstance(raw, dict) else None
    if not isinstance(epochs, list):
        raise RuntimeError("Recorded evidence is missing its epoch list")
    result: dict[str, dict[str, Any]] = {}
    for item in epochs:
        if not isinstance(item, dict):
            continue
        turn_id = str(item.get("turnId") or "")
        evidence = _recorded_provider_prefix_evidence(
            item.get("providerPrefix"),
            turn_id=turn_id,
            source="recorded_evidence",
        )
        if turn_id and evidence is not None:
            result[turn_id] = evidence
    return result


def _context_inspection_provider_prefix_evidence(
    context_inspection_dir: Path,
    *,
    session_id: str,
    turn_id: str,
) -> dict[str, Any] | None:
    if not context_inspection_dir.is_dir():
        return None
    session_dir = context_inspection_dir / session_id.replace(":", "_")
    search_root = session_dir if session_dir.is_dir() else context_inspection_dir
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in search_root.rglob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(raw, dict)
            and raw.get("sessionId") == session_id
            and raw.get("turnId") == turn_id
        ):
            matches.append((path, raw))
    if not matches:
        return None
    selected_path, selected = max(
        matches,
        key=lambda item: (
            int(item[1].get("updatedAtMs") or 0),
            int(item[1].get("capturedAtMs") or 0),
            item[0].name,
        ),
    )
    evidence = provider_prefix_evidence(selected)
    return {
        **evidence,
        "turnId": turn_id,
        "source": "context_inspection_receipt",
        "sourceReceipt": {
            "path": str(selected_path.resolve()),
            "sha256": hashlib.sha256(selected_path.read_bytes()).hexdigest(),
            "candidateCount": len(matches),
        },
    }


def _live_provider_prefix_evidence(
    base_url: str,
    *,
    session_id: str,
    turn_id: str,
) -> dict[str, Any]:
    debug = request_json(
        base_url,
        "GET",
        (
            f"/api/agent/sessions/{encoded(session_id)}/debug-context"
            f"?turnId={encoded(turn_id)}"
        ),
        timeout=20,
    )
    context = debug.get("context") or {}
    return {
        **provider_prefix_evidence(context),
        "turnId": turn_id,
        "source": "live_debug_context",
    }


def _prior_transcript_sha(path: Path | None) -> str:
    if path is None:
        return ""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ""
    observations = raw.get("observations")
    if not isinstance(observations, dict):
        return ""
    transcript = observations.get("transcript")
    if not isinstance(transcript, dict):
        return ""
    return str(transcript.get("sha256") or "")


def _transcript_boundary_checks(
    transcript: dict[str, Any],
    *,
    epoch_count: int,
) -> dict[str, bool]:
    repair_count = int(transcript.get("repairContinuationCount") or 0)
    return {
        "repairContinuationsAreBounded": 0 <= repair_count <= epoch_count,
        "roomContextAbsentFromSessionTranscript": (
            transcript.get("roomEnvelopeCount") == 0
            and transcript.get("publicCanaryPostCount") == 0
            and transcript.get("privateTriggerCount") == epoch_count
        ),
        "piCompactionStoresOnlyRoomRecoveryPointer": (
            transcript.get("compactionCount") == epoch_count
            and transcript.get("extensionCompactionCount")
            == epoch_count
            and transcript.get("roomRecoveryPointerCount")
            == epoch_count
            and transcript.get("compactionTaskFactLeakCount") == 0
        ),
    }


def build_report(
    *,
    base_url: str,
    db_path: Path,
    canary_report_path: Path,
    pi_session_dir: Path,
    recorded_evidence_path: Path | None = None,
    context_inspection_dir: Path | None = None,
) -> dict[str, Any]:
    raw = json.loads(canary_report_path.read_text(encoding="utf-8"))
    session_id = str(raw.get("sessionId") or "")
    epochs = raw.get("epochs") if isinstance(raw.get("epochs"), list) else []
    if not session_id or len(epochs) != 3:
        raise RuntimeError("Expected one resident Session and exactly three canary epochs")

    prior_memory = _prior_memory_by_turn(recorded_evidence_path)
    prior_prefix = _prior_provider_prefix_by_turn(recorded_evidence_path)
    inspection_root = context_inspection_dir or (
        pi_session_dir.parent.parent / "context-inspection"
    )
    verified_epochs: list[dict[str, Any]] = []
    for item in epochs:
        before = item.get("beforeCompaction") or {}
        after_journal = (item.get("afterCompaction") or {}).get("journal") or {}
        transition_ref = (item.get("productTransition") or {}).get("source")
        if not transition_ref:
            raise RuntimeError("Canary epoch is missing its Product transition source")
        transition = _transition_evidence(
            db_path,
            session_id=session_id,
            source_ref=str(transition_ref),
        )
        turn_id = str(before.get("turnId") or "")
        memory = _recorded_memory_evidence(
            before.get("sessionMemory"),
            turn_id=turn_id,
            source="canary_report",
        )
        if memory is None:
            memory = prior_memory.get(turn_id)
        if memory is None:
            memory = _turn_memory_evidence(base_url, session_id, turn_id)
        prefix = _recorded_provider_prefix_evidence(
            before.get("providerPrefix"),
            turn_id=turn_id,
            source="canary_report",
        )
        if prefix is None:
            prefix = prior_prefix.get(turn_id)
        if prefix is None:
            prefix = _context_inspection_provider_prefix_evidence(
                inspection_root,
                session_id=session_id,
                turn_id=turn_id,
            )
        if prefix is None:
            prefix = _live_provider_prefix_evidence(
                base_url,
                session_id=session_id,
                turn_id=turn_id,
            )
        hashes_match = transition["providerHashes"] == after_journal.get("hashes")
        applied = (
            transition["reason"] == "compaction"
            and after_journal.get("reason") == "compaction"
            and transition["to"] == after_journal.get("epoch")
            and after_journal.get("entryCount") == 2
            and hashes_match
        )
        verified_epochs.append(
            {
                "index": item.get("index"),
                "turnId": before.get("turnId"),
                "transition": transition,
                "journal": after_journal,
                "memory": memory,
                "providerPrefix": prefix,
                "promptGovernance": before.get("promptGovernance") or {},
                "compactionObservedApplied": applied,
                "hashesMatch": hashes_match,
                "positiveCacheRead": bool(before.get("positiveCacheRead")),
                "pendingContinuations": before.get("pendingContinuations"),
                "workspaceRead": item.get("workspaceRead") or {},
            }
        )

    final_after = epochs[-1].get("afterCompaction") or {}
    final_transcript = final_after.get("transcript") or {}
    transcript_sha = str(final_transcript.get("sha256") or "")
    if not transcript_sha:
        transcript_sha = _prior_transcript_sha(recorded_evidence_path)
    if not transcript_sha:
        final_debug = debug_evidence(base_url, session_id)
        transcript_sha = str(final_debug["transcript"].get("sha256") or "")
    if not transcript_sha:
        raise RuntimeError("No sealed Pi transcript receipt is available")
    transcript = transcript_evidence(pi_session_dir, transcript_sha)
    actual_epochs = [item["journal"].get("epoch") for item in verified_epochs]
    checks = {
        "threeEpochSequence": actual_epochs == [2, 4, 6],
        "allCompactionsObservedApplied": all(
            item["compactionObservedApplied"] for item in verified_epochs
        ),
        "oneRecoveryPacketPerEpoch": all(
            item["journal"].get("entryCount") == 2 for item in verified_epochs
        ),
        "allProviderHashesMatch": all(item["hashesMatch"] for item in verified_epochs),
        "allRecoveryContractsComplete": all(
            item["transition"]["originalRequirementCount"] == 1
            and item["transition"]["currentTaskPresent"] is True
            and item["transition"]["acceptanceCount"] == 3
            and item["transition"]["blockerCount"] == 0
            and item["transition"]["handoffPresent"] is True
            and item["transition"]["skillReceipt"] is not None
            and len(item["transition"]["skillReceipt"]["skillHash"]) == 64
            and {"workspace_read", "room_commit"}
            <= {
                receipt["toolName"]
                for receipt in item["transition"]["toolReceipts"]
            }
            and len(item["transition"]["toolReceipts"])
            == item["transition"]["toolReceiptCount"]
            and all(
                receipt["kind"] == "load"
                and len(receipt["schemaHash"]) == 64
                for receipt in item["transition"]["toolReceipts"]
            )
            for item in verified_epochs
        ),
        "workspaceReadWorkloadExact": all(
            item["workspaceRead"].get("invocationCount") == 2
            and item["workspaceRead"].get("appliedExecutionCount") == 2
            and len(item["workspaceRead"].get("loadReceiptIds") or []) == 1
            for item in verified_epochs
        ),
        "workspaceReadReceiptsRecovered": all(
            set(item["workspaceRead"].get("loadReceiptIds") or [])
            <= set(item["transition"]["toolReceiptIds"])
            for item in verified_epochs
        ),
        "roomMemoryIsBounded": all(
            item["memory"]["blockCount"] > 0
            and item["memory"]["nonEmptyBlockCount"] > 0
            and not item["memory"]["forbiddenMetadata"]
            and item["memory"]["assistantConversationBlockCount"]
            == 0
            for item in verified_epochs
        ),
        "kvCacheObservedEveryTask": all(
            item["positiveCacheRead"] for item in verified_epochs
        ),
        "providerPrefixesStableWithinEpoch": all(
            item["providerPrefix"]["passed"] for item in verified_epochs
        ),
        "managedRoomWorkflowAuthorityClear": all(
            item["promptGovernance"].get("managedRoomAuthorityEveryCall") is True
            and not item["promptGovernance"].get("conflictingWorkflowMarkers")
            for item in verified_epochs
        ),
        "singleManagedRoomRecoveryOwner": all(
            item["promptGovernance"].get("lifecycleHookBlockCount") == 0
            for item in verified_epochs
        ),
        "cacheStableManagedPromptControls": all(
            item["promptGovernance"].get("volatileCurrentTimeCount") == 0
            for item in verified_epochs
        ),
        "agentMdDefaultOff": all(
            item["promptGovernance"].get("projectContextBlockCount") == 0
            for item in verified_epochs
        ),
        "roomContextProjectionIsDeduplicated": all(
            item["promptGovernance"].get(
                "originalRequirementProjectionDeduplicatedEveryCall"
            )
            is True
            and item["promptGovernance"].get(
                "roomContextOmissionAuditBlockCount"
            )
            == 0
            and item["promptGovernance"].get(
                "roomFactFramingValidEveryCall"
            )
            is True
            and not item["promptGovernance"].get(
                "forbiddenDispatchMetadata"
            )
            for item in verified_epochs
        ),
        "skillToolDiscoveryIsProgressive": progressive_discovery_check(
            [item["promptGovernance"] for item in verified_epochs]
        ),
        "settlementQueuesDrained": all(
            item["pendingContinuations"] == 0 for item in verified_epochs
        ),
        **_transcript_boundary_checks(
            transcript,
            epoch_count=len(verified_epochs),
        ),
    }
    report = {
        "schemaVersion": "wisdom-weasel.room-context-epoch-evidence.v1",
        "observedAtMs": int(time.time() * 1000),
        "sourceCanaryReport": str(canary_report_path.resolve()),
        "sessionId": session_id,
        "passed": all(checks.values()),
        "checks": checks,
        "observations": {
            "actualAfterCompaction": actual_epochs,
            "transcript": transcript,
        },
        "epochs": verified_epochs,
    }
    if not report["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"Room context epoch evidence failed: {', '.join(failed)}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a completed Room context epoch canary without another Provider run"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18768")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--canary-report", type=Path, required=True)
    parser.add_argument("--pi-session-dir", type=Path, required=True)
    parser.add_argument(
        "--context-inspection-dir",
        type=Path,
        help=(
            "Optional Pi debug-context receipt directory; defaults to the "
            "context-inspection sibling of Agent/sessions"
        ),
    )
    parser.add_argument(
        "--recorded-evidence",
        type=Path,
        help=(
            "Optional prior evidence for legacy canary reports that predate "
            "embedded session-memory receipts"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(
        base_url=args.base_url,
        db_path=args.db_path.resolve(),
        canary_report_path=args.canary_report.resolve(),
        pi_session_dir=args.pi_session_dir.resolve(),
        context_inspection_dir=(
            args.context_inspection_dir.resolve()
            if args.context_inspection_dir is not None
            else None
        ),
        recorded_evidence_path=(
            args.recorded_evidence.resolve()
            if args.recorded_evidence is not None
            else None
        ),
    )
    _atomic_write(args.output.resolve(), report)
    print(json.dumps({"passed": True, "checks": report["checks"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
