#!/usr/bin/env python3
"""Verify a completed Room context canary without invoking the Provider again."""

from __future__ import annotations

import argparse
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
        "toolReceiptCount": len(evidence.get("toolReceiptIds") or []),
        "providerHashes": [
            evidence.get("roomProviderEntryHash"),
            evidence.get("sessionProviderEntryHash"),
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
    if not isinstance(block_count, int) or not isinstance(non_empty_count, int):
        return None
    if not isinstance(forbidden, list) or not all(
        isinstance(item, str) for item in forbidden
    ):
        return None
    return {
        "turnId": turn_id,
        "blockCount": block_count,
        "nonEmptyBlockCount": non_empty_count,
        "forbiddenMetadata": forbidden,
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
    }


def build_report(
    *,
    base_url: str,
    db_path: Path,
    canary_report_path: Path,
    pi_session_dir: Path,
    recorded_evidence_path: Path | None = None,
) -> dict[str, Any]:
    raw = json.loads(canary_report_path.read_text(encoding="utf-8"))
    session_id = str(raw.get("sessionId") or "")
    epochs = raw.get("epochs") if isinstance(raw.get("epochs"), list) else []
    if not session_id or len(epochs) != 3:
        raise RuntimeError("Expected one resident Session and exactly three canary epochs")

    prior_memory = _prior_memory_by_turn(recorded_evidence_path)
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
                "compactionObservedApplied": applied,
                "hashesMatch": hashes_match,
                "positiveCacheRead": bool(before.get("positiveCacheRead")),
                "pendingContinuations": before.get("pendingContinuations"),
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
            and item["transition"]["skillReceiptPresent"] is True
            and item["transition"]["toolReceiptCount"] == 2
            for item in verified_epochs
        ),
        "roomMemoryIsBounded": all(
            item["memory"]["blockCount"] > 0
            and item["memory"]["nonEmptyBlockCount"] > 0
            and not item["memory"]["forbiddenMetadata"]
            for item in verified_epochs
        ),
        "kvCacheObservedEveryTask": all(
            item["positiveCacheRead"] for item in verified_epochs
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
