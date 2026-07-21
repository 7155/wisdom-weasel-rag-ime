#!/usr/bin/env python3
"""Run a bounded real-Provider Room context epoch canary.

The script exercises the public Control API only and writes a compact report. It
never persists Provider text; evidence is limited to hashes, counts, state and
usage metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_SESSION_MEMORY_OPEN = '<rag-ime-context type="session_memory">'
_SESSION_MEMORY_CLOSE = "</rag-ime-context>"
_FORBIDDEN_MEMORY_METADATA = (
    "相关度：",
    "相关度:",
    "命中通道",
    "检索解释",
    "sourceId",
    "source_id",
    "recallId",
    "score=",
    "score：",
    "sha256:",
)


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 130,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed ({error.code}): {body}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} {path} returned a non-object response")
    return result


def encoded(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def accepted_root_id(response: dict[str, Any]) -> str:
    root_id = str(response.get("rootId") or "")
    if not root_id.startswith("room-root:"):
        schema = str(response.get("schemaVersion") or "unknown")
        raise RuntimeError(
            "Room V2 is not active: message acceptance returned "
            f"schema={schema!r}, rootId={root_id!r}"
        )
    return root_id


def wait_for_terminal_dispatch(
    base_url: str,
    room_id: str,
    root_id: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = request_json(
            base_url,
            "GET",
            f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
            timeout=10,
        )
        roots = [item for item in snapshot.get("roots", []) if item.get("rootId") == root_id]
        dispatches = [
            item for item in snapshot.get("dispatches", []) if item.get("rootId") == root_id
        ]
        root = roots[0] if roots else {}
        last = {
            "rootState": root.get("state"),
            "dispatchStates": [item.get("state") for item in dispatches],
            "dispatchIds": [item.get("dispatchId") for item in dispatches],
        }
        if dispatches and all(
            state in {"committed", "blocked", "failed", "cancelled"}
            for state in last["dispatchStates"]
        ):
            return last
        time.sleep(0.5)
    raise TimeoutError(f"Room Root {root_id} did not settle: {last}")


def cancel_root(base_url: str, room_id: str, root_id: str) -> None:
    now_ms = int(time.time() * 1000)
    request_json(
        base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/commands",
        {
            "schemaVersion": "wisdom-weasel.room-kernel-command.v1",
            "commandId": f"command:canary-cleanup:{now_ms}",
            "rootId": root_id,
            "roomId": room_id,
            "commandKind": "cancel_root",
            "targetKind": "root",
            "targetId": root_id,
            "sourceKind": "control_center",
            "sourceId": "room-context-epoch-canary",
            "idempotencyKey": f"canary-cleanup:{root_id}",
            "generation": 0,
            "payload": {},
            "createdAtMs": now_ms,
        },
        timeout=20,
    )


def debug_evidence(base_url: str, session_id: str) -> dict[str, Any]:
    debug = request_json(
        base_url,
        "GET",
        f"/api/agent/sessions/{encoded(session_id)}/debug-context",
        timeout=15,
    )
    context = debug.get("context") or {}
    projection = context.get("contextProjection") or {}
    journal = projection.get("providerContextJournal") or {}
    cache_reads = [
        int((call.get("usage") or {}).get("cacheRead") or 0)
        for call in context.get("providerRequestReceipts", [])
        if isinstance(call, dict)
    ]
    tool_names = [
        str(item.get("toolName") or item.get("name") or "")
        for item in context.get("toolExecutions", [])
        if isinstance(item, dict)
    ]
    memory_blocks = _provider_session_memory_blocks(
        context.get("providerRequests") or []
    )
    snapshot = request_json(
        base_url,
        "GET",
        f"/api/agent/sessions/{encoded(session_id)}/messages",
        timeout=15,
    )
    message_queue = snapshot.get("messageQueue") or {}
    transcript = debug.get("transcript") or {}
    return {
        "turnId": debug.get("turnId"),
        "journal": {
            "epoch": journal.get("epoch"),
            "reason": journal.get("epochReason"),
            "entryCount": journal.get("entryCount"),
            "hashes": journal.get("contentHashes") or [],
        },
        "cacheReads": cache_reads,
        "positiveCacheRead": any(value > 0 for value in cache_reads),
        "modelCallCount": len(context.get("modelCalls", [])),
        "toolNames": tool_names,
        "roomCommitCalls": sum(name == "room_commit" for name in tool_names),
        "pendingContinuations": len(message_queue.get("steering") or [])
        + len(message_queue.get("followUp") or []),
        "sessionMemory": {
            "blockCount": len(memory_blocks),
            "nonEmptyBlockCount": sum(
                "## Session 记忆" in block for block in memory_blocks
            ),
            "forbiddenMetadata": sorted(
                {
                    token
                    for block in memory_blocks
                    for token in _FORBIDDEN_MEMORY_METADATA
                    if token in block
                }
            ),
        },
        "transcript": {
            "sha256": transcript.get("sha256"),
            "bytes": transcript.get("bytes"),
            "lineCount": transcript.get("lineCount"),
            "contentIncluded": transcript.get("contentIncluded"),
        },
    }


def _provider_session_memory_blocks(
    provider_requests: list[object],
) -> list[str]:
    blocks: list[str] = []
    for request in provider_requests:
        if not isinstance(request, dict):
            continue
        payload = request.get("payload")
        if not isinstance(payload, dict):
            continue
        for content in _walk_strings(payload.get("input")):
            cursor = 0
            while True:
                start = content.find(_SESSION_MEMORY_OPEN, cursor)
                if start < 0:
                    break
                body_start = start + len(_SESSION_MEMORY_OPEN)
                end = content.find(_SESSION_MEMORY_CLOSE, body_start)
                if end < 0:
                    break
                blocks.append(content[body_start:end].strip())
                cursor = end + len(_SESSION_MEMORY_CLOSE)
    return blocks


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _walk_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _walk_strings(item)]
    return []


def transcript_evidence(
    session_dir: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    transcript_path = _find_transcript(session_dir, expected_sha256)
    user_messages: list[str] = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if not isinstance(entry, dict) or entry.get("type") != "message":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        user_messages.extend(_walk_strings(message.get("content")))
    forbidden_envelopes = (
        "<room-turn-context",
        "<room-projection",
        "wisdom-weasel.room-task-context.v1",
    )
    return {
        "sha256": expected_sha256,
        "userMessageCount": len(user_messages),
        "privateTriggerCount": sum(
            message.startswith("执行当前受管 Room 任务") for message in user_messages
        ),
        "repairContinuationCount": sum(
            message.startswith("收工检查未通过：") for message in user_messages
        ),
        "roomEnvelopeCount": sum(
            token in message
            for message in user_messages
            for token in forbidden_envelopes
        ),
        "publicCanaryPostCount": sum("CANARY-" in message for message in user_messages),
    }


def _find_transcript(session_dir: Path, expected_sha256: str) -> Path:
    for path in sorted(session_dir.glob("*.jsonl")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == expected_sha256:
            return path
    raise RuntimeError(
        f"No Pi transcript under {session_dir} matches sha256 {expected_sha256}"
    )


def latest_transition(db_path: Path, session_id: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT source_ref, from_epoch, to_epoch, epoch_reason, evidence_json
            FROM room_v2_session_context_epoch_transitions
            WHERE session_id = ?
            ORDER BY created_at_ms DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"No Product context transition for {session_id}")
    evidence = json.loads(row[4])
    hashes = [
        evidence.get("roomProviderEntryHash"),
        evidence.get("sessionProviderEntryHash"),
    ]
    return {
        "source": row[0],
        "from": row[1],
        "to": row[2],
        "reason": row[3],
        "recovery": {
            "originalRequirements": evidence.get("originalRequirementCount"),
            "currentTask": evidence.get("currentTaskPresent"),
            "acceptance": evidence.get("acceptanceCount"),
            "blockers": evidence.get("blockerCount"),
            "handoff": evidence.get("handoffPresent"),
            "skillReceipt": bool(evidence.get("skillReceiptId")),
            "toolReceipts": len(evidence.get("toolReceiptIds") or []),
            "providerHashes": hashes,
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    stamp = int(time.time() * 1000)
    created = request_json(
        args.base_url,
        "POST",
        "/api/agent/rooms",
        {
            "title": f"Context epoch canary {stamp}",
            "routingPolicy": "manual_mentions",
            "workspaceRoots": [str(args.workspace.resolve())],
            "participants": [
                {"roleId": "companion-future-v1", "roleVersion": "1"},
                {"roleId": "companion-present-v1", "roleVersion": "1"},
            ],
        },
    )
    room = created["room"]
    target = room["participants"][1]
    room_id = str(room["id"])
    session_id = str(target["sessionId"])
    request_json(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/thinking",
        {"level": "low"},
    )

    epochs: list[dict[str, Any]] = []
    for index in range(1, 4):
        work = request_json(
            args.base_url,
            "POST",
            f"/api/agent/rooms/{encoded(room_id)}/work-items",
            {
                "currentOwnerParticipantId": target["id"],
                "createdByParticipantId": room["participants"][0]["id"],
                "clientMessageId": f"epoch-canary-work-{stamp}-{index}",
                "objective": f"确认第 {index} 个独立任务的 Room 上下文边界",
                "expectedOutput": f"只提交 CANARY-{index}-OK，并结束本轮",
                "acceptanceCriteria": [
                    f"回复包含 CANARY-{index}-OK",
                    "责任提交覆盖全部验收条件",
                    "通过收工检查后结束模型回合",
                ],
                "state": "active",
            },
        )["workItem"]
        accepted = request_json(
            args.base_url,
            "POST",
            f"/api/agent/rooms/{encoded(room_id)}/messages",
            {
                "message": (
                    f"@{target['displayName']} 执行当前结构化任务。"
                    f"发布 CANARY-{index}-OK 并提交责任；若收工检查要求修复，只修复一次。"
                ),
                "clientMessageId": f"epoch-canary-message-{stamp}-{index}",
                "workItemId": work["id"],
            },
        )
        root_id = accepted_root_id(accepted)
        try:
            settled = wait_for_terminal_dispatch(
                args.base_url,
                room_id,
                root_id,
                timeout=args.turn_timeout,
            )
        except BaseException:
            cancel_root(args.base_url, room_id, root_id)
            raise
        before = debug_evidence(args.base_url, session_id)
        compacted = request_json(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/compact",
            {"instructions": f"Epoch canary {index}: preserve only the bounded recovery packet."},
            timeout=args.turn_timeout,
        )
        compact_result = compacted.get("result") or {}
        after = debug_evidence(args.base_url, session_id)
        transition = latest_transition(args.db_path, session_id)
        transition_hashes = transition["recovery"]["providerHashes"]
        journal_hashes = after["journal"]["hashes"]
        epochs.append(
            {
                "index": index,
                "rootId": root_id,
                "dispatch": settled,
                "beforeCompaction": before,
                "compaction": {
                    "entryId": compact_result.get("compactionEntryId"),
                    "epochBefore": compact_result.get("contextEpochBefore"),
                    "epochAfter": compact_result.get("contextEpochAfter"),
                    "refreshApplied": compact_result.get("contextRefreshApplied"),
                },
                "afterCompaction": after,
                "productTransition": transition,
                "hashesMatch": transition_hashes == journal_hashes,
            }
        )

    final_transcript = None
    if args.pi_session_dir is not None:
        expected_transcript_sha = str(
            epochs[-1]["afterCompaction"]["transcript"]["sha256"] or ""
        )
        if not expected_transcript_sha:
            raise RuntimeError("Pi debug context did not expose a transcript receipt")
        final_transcript = transcript_evidence(
            args.pi_session_dir,
            expected_transcript_sha,
        )

    expected_after = [2, 4, 6]
    actual_after = [item["afterCompaction"]["journal"]["epoch"] for item in epochs]
    checks = {
        "epochSequence": actual_after == expected_after,
        "allHashesMatch": all(item["hashesMatch"] for item in epochs),
        "oneRecoveryPacketPerEpoch": all(
            item["afterCompaction"]["journal"]["entryCount"] == 2 for item in epochs
        ),
        "allCompactionsApplied": all(
            item["compaction"]["refreshApplied"] is True for item in epochs
        ),
        "kvCacheObserved": any(
            item["beforeCompaction"]["positiveCacheRead"] for item in epochs
        ),
        "boundedRoomCommitCalls": all(
            1 <= item["beforeCompaction"]["roomCommitCalls"] <= 2 for item in epochs
        ),
        "settlementQueuesDrained": all(
            item["beforeCompaction"]["pendingContinuations"] == 0 for item in epochs
        ),
        "roomMemoryIsBounded": all(
            item["beforeCompaction"]["sessionMemory"]["blockCount"] > 0
            and not item["beforeCompaction"]["sessionMemory"]["forbiddenMetadata"]
            for item in epochs
        ),
    }
    if final_transcript is not None:
        checks["roomContextAbsentFromSessionTranscript"] = (
            final_transcript["roomEnvelopeCount"] == 0
            and final_transcript["publicCanaryPostCount"] == 0
            and final_transcript["privateTriggerCount"] == 3
        )

    return {
        "schemaVersion": "wisdom-weasel.room-context-epoch-canary.v1",
        "roomId": room_id,
        "sessionId": session_id,
        "epochs": epochs,
        "transcript": final_transcript,
        "observations": {
            "expectedAfterCompaction": expected_after,
            "actualAfterCompaction": actual_after,
        },
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18768")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pi-session-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--turn-timeout", type=float, default=240)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run(args)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"ok": all(report["checks"].values()), "output": str(args.output), "checks": report["checks"]}, ensure_ascii=False, indent=2))
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
