#!/usr/bin/env python3
"""Import immutable EnterpriseOps evaluation transcripts into PAW Agent sessions.

The source run remains read-only.  A write import copies each exact Pi JSONL
transcript into PAW-managed storage, verifies the copy by SHA-256, and registers
an ordinary conversation Session marked as an evaluation snapshot.  Eval Lab
metadata is deliberately path-free and does not expose raw task identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_sessions import AgentSessionStore


_REPORT_SCHEMA = "paw.enterpriseops-csm-eval.v1"
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
_MAX_TRANSCRIPT_BYTES = 128 * 1024 * 1024
_MAX_EXPLANATION_TEXT = 600
_MAX_ACCEPTANCE_ITEMS = 64
_TASK_MARKERS = ("customer request:", "user request:", "task request:")
_TASK_END_MARKERS = (
    "\nwork only through",
    "\nsuite v2 frozen",
    "\nstop after the task",
)
_PATH_PATTERN = re.compile(
    r"(?<![\w])"
    r"(?:(?:[A-Za-z]:[\\/])|"
    r"/(?:Users|Volumes|private|tmp|var|home|opt|workspace|"
    r"mnt|data|root|usr|etc|srv|dev|System|Library|Applications)"
    r"(?:[\\/]|(?=\s|$)))"
    r"[^\n`'\"<>),;]*?"
    r"(?=(?:[.!?](?:\s|$)|[,;)}\]]|$))",
)
_SQL_PATTERN = re.compile(
    r"\b(?:select\b(?:[^;]{0,2000}\bfrom\b|[^;]{1,2000};)|"
    r"insert\s+into\b|update\s+\S+\s+set\b|delete\s+from\b|"
    r"create\s+(?:table|index|view|trigger|database)\b|alter\s+table\b|"
    r"drop\s+(?:table|index|view|database)\b|truncate\s+table\b|"
    r"with\s+\w+\s+as\s*\(|(?:sql|query)\s*[:=])[^;]{0,2000};?",
    re.IGNORECASE,
)
_HIDDEN_EVALUATION_PATTERN = re.compile(
    r"\b(?:(?:hidden|raw)[\s_.-]+(?:gold|answer|expected|value|sql|result)|"
    r"ground[\s_.-]+truth|oracle|"
    r"expected[\s_.-]+(?:value|answer|sql|result))\b"
    r"(?:\s*[:=]\s*[^.;]{0,240})?",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid evaluation report: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("evaluation report must be a JSON object")
    return payload


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _resolved_regular_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved


def _transcript_session_id(path: Path) -> str:
    if path.stat().st_size > _MAX_TRANSCRIPT_BYTES:
        raise ValueError("source transcript is too large")
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("source transcript header is invalid JSONL") from exc
            if not isinstance(payload, dict) or payload.get("type") != "session":
                raise ValueError("source transcript is missing its Pi session header")
            session_id = str(payload.get("id") or "").strip()
            if not session_id:
                raise ValueError("source transcript header has no session id")
            return session_id
    raise ValueError("source transcript is empty")


def _source_rows(source_db: Path, tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    with _read_only_connection(source_db) as connection:
        rows = connection.execute(
            """
            SELECT s.title, s.model_profile, s.thinking_level,
                   s.created_at_ms, s.updated_at_ms, s.message_count,
                   b.external_session_id, b.transcript_ref
            FROM agent_sessions AS s
            JOIN agent_runtime_bindings AS b ON b.session_id = s.id
            WHERE b.runtime_kind = 'pi_rpc'
            ORDER BY s.created_at_ms, s.id
            """
        ).fetchall()

    matched: list[dict[str, Any]] = []
    used_titles: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        task_id = str(task.get("taskId") or "").strip()
        if not task_id:
            raise ValueError(f"evaluation task {index} has no taskId")
        candidates = [row for row in rows if task_id in str(row["title"])]
        if len(candidates) != 1:
            raise ValueError(
                f"evaluation task {index} must match exactly one source Session"
            )
        row = candidates[0]
        if str(row["title"]) in used_titles:
            raise ValueError("multiple evaluation tasks matched the same source Session")
        used_titles.add(str(row["title"]))
        matched.append({"task": dict(task), "row": dict(row), "taskIndex": index})
    return matched


def _validate_source_transcript(
    transcript_ref: str,
    *,
    source_root: Path,
    external_session_id: str,
) -> tuple[Path, str]:
    candidate = Path(transcript_ref)
    if not candidate.is_absolute():
        candidate = source_root / candidate
    path = _resolved_regular_file(candidate, label="source transcript")
    if not path.is_relative_to(source_root):
        raise ValueError("source transcript escapes source run")
    header_id = _transcript_session_id(path)
    if header_id != external_session_id:
        raise ValueError("source transcript identity does not match its runtime binding")
    return path, _sha256(path)


def _atomic_copy(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, 0o600)
        if _sha256(temporary) != expected_sha256:
            raise ValueError("copied transcript failed SHA-256 verification")
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _existing_run_sessions(store: AgentSessionStore, run_id: str) -> list[dict[str, Any]]:
    existing: list[dict[str, Any]] = []
    for session in store.list():
        if session.get("evaluationSnapshot") is not True:
            continue
        binding = store.runtime_binding(str(session["id"]))
        metadata = binding.get("metadata") if isinstance(binding, dict) else None
        snapshot = metadata.get("evaluationSnapshot") if isinstance(metadata, dict) else None
        if isinstance(snapshot, dict) and snapshot.get("runId") == run_id:
            existing.append({"session": session, "snapshot": snapshot})
    return existing


def _task_id_sha256(task: Mapping[str, Any]) -> str:
    return hashlib.sha256(str(task.get("taskId") or "").encode("utf-8")).hexdigest()


def _existing_snapshot_matches(
    store: AgentSessionStore,
    existing: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    run_id: str,
    source_database_sha256: str,
    source_report_sha256: str,
    target_session_dir: Path,
) -> list[dict[str, Any]]:
    """Verify an existing import before deciding whether metadata can be backfilled."""

    expected_by_index = {
        int(record["taskIndex"]): record
        for record in records
    }
    target_root = target_session_dir.resolve()
    matches: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    if len(existing) != len(records):
        raise ValueError("target contains a partial or conflicting evaluation snapshot run")
    for existing_record in existing:
        snapshot = existing_record["snapshot"]
        task_index_value = snapshot.get("taskIndex")
        if isinstance(task_index_value, bool) or not isinstance(task_index_value, int):
            raise ValueError("existing snapshot source hashes do not match current source")
        task_index = task_index_value
        if task_index in seen_indexes or task_index not in expected_by_index:
            raise ValueError("existing snapshot source hashes do not match current source")
        seen_indexes.add(task_index)
        record = expected_by_index[task_index]
        task = record["task"]
        row = record["row"]
        if (
            snapshot.get("runId") != run_id
            or snapshot.get("sourceDatabaseSha256") != source_database_sha256
            or snapshot.get("sourceReportSha256") != source_report_sha256
            or snapshot.get("sourceTranscriptSha256") != record["transcriptSha256"]
            or snapshot.get("taskIdSha256") != _task_id_sha256(task)
        ):
            raise ValueError("existing snapshot source hashes do not match current source")
        binding = store.runtime_binding(str(existing_record["session"]["id"]))
        if not isinstance(binding, Mapping):
            raise ValueError("existing snapshot source hashes do not match current source")
        if (
            binding.get("driverId") != "managed-pi"
            or binding.get("runtimeKind") != "pi_rpc"
            or binding.get("externalSessionId") != row.get("external_session_id")
        ):
            raise ValueError("existing snapshot source hashes do not match current source")
        transcript_ref = str(binding.get("transcriptRef") or "")
        try:
            target_transcript = _resolved_regular_file(
                Path(transcript_ref),
                label="existing snapshot transcript",
            )
        except (OSError, ValueError) as exc:
            raise ValueError("existing snapshot source hashes do not match current source") from exc
        if (
            not target_transcript.is_relative_to(target_root)
            or _sha256(target_transcript) != str(record["transcriptSha256"])
        ):
            raise ValueError("existing snapshot source hashes do not match current source")
        matches.append(
            {
                "existing": existing_record,
                "record": record,
                "binding": dict(binding),
                "targetTranscript": target_transcript,
            }
        )
    if seen_indexes != set(expected_by_index):
        raise ValueError("existing snapshot source hashes do not match current source")
    matches.sort(key=lambda match: int(match["record"]["taskIndex"]))
    return matches


def _backfill_explanations(
    store: AgentSessionStore,
    matches: list[dict[str, Any]],
) -> list[str]:
    session_ids: list[str] = []
    for match in matches:
        existing = match["existing"]
        snapshot = dict(existing["snapshot"])
        if "explanation" in snapshot:
            if not isinstance(snapshot["explanation"], Mapping):
                raise ValueError("existing evaluation explanation is invalid")
            continue
        binding = match["binding"]
        metadata = binding.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        snapshot["explanation"] = _explanation(
            match["record"]["task"],
            match["targetTranscript"],
        )
        metadata["evaluationSnapshot"] = snapshot
        session_id = str(existing["session"]["id"])
        store.bind_runtime_session(
            session_id,
            driver_id=str(binding["driverId"]),
            runtime_kind=str(binding["runtimeKind"]),
            external_session_id=str(binding["externalSessionId"]),
            transcript_ref=str(binding.get("transcriptRef") or ""),
            branch_anchor=str(binding.get("branchAnchor") or ""),
            binding_state=str(binding["state"]),
            metadata=metadata,
            updated_at_ms=int(binding["updatedAtMs"]),
        )
        session_ids.append(session_id)
    return session_ids


def _number(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _message_text(message: Mapping[str, Any]) -> str:
    """Return only visible text parts; thinking/tool payloads are excluded."""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if not isinstance(part, Mapping) or part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def _redact_path(match: re.Match[str]) -> str:
    path = match.group(0)
    trailing = ""
    while path and path[-1] in ".!?":
        trailing = path[-1] + trailing
        path = path[:-1]
    return "[path redacted]" + trailing


def _public_text(value: str, *, fallback: str) -> str:
    """Normalize a transcript excerpt into a bounded, privacy-safe UI string."""

    normalized = re.sub(r"\s+", " ", str(value)).strip()
    if not normalized:
        return fallback
    normalized = _PATH_PATTERN.sub(_redact_path, normalized)
    normalized = _SQL_PATTERN.sub("[evaluation detail redacted]", normalized)
    normalized = _HIDDEN_EVALUATION_PATTERN.sub(
        "[evaluation detail redacted]", normalized
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:_MAX_EXPLANATION_TEXT] or fallback


def _task_excerpt(value: str) -> str:
    """Prefer the business request over the policy preamble in CSM prompts."""

    candidate = value
    lowered = value.casefold()
    marker_end = -1
    for marker in _TASK_MARKERS:
        marker_start = lowered.find(marker)
        if marker_start >= 0:
            marker_end = marker_start + len(marker)
            candidate = value[marker_end:]
            break
    if marker_end >= 0:
        lowered_candidate = candidate.casefold()
        cut_points = [
            lowered_candidate.find(marker.casefold())
            for marker in _TASK_END_MARKERS
            if lowered_candidate.find(marker.casefold()) >= 0
        ]
        if cut_points:
            candidate = candidate[: min(cut_points)]
    return _public_text(candidate, fallback="暂无可用的任务文本。")


def _transcript_texts(path: Path) -> tuple[str, str]:
    """Read the first user and last assistant visible text from one Pi JSONL."""

    first_user = ""
    last_assistant = ""
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("source transcript contains invalid JSONL") from exc
            if not isinstance(payload, Mapping) or payload.get("type") != "message":
                continue
            message = payload.get("message")
            if not isinstance(message, Mapping):
                continue
            role = message.get("role")
            text = _message_text(message)
            if not text.strip():
                continue
            if role == "user" and not first_user:
                first_user = text
            elif role == "assistant":
                last_assistant = text
    return first_user, last_assistant


def _failure_owner(task: Mapping[str, Any]) -> str:
    if task.get("verifierExecutionErrorType"):
        return "evaluator_gold"
    if task.get("runtimeErrorType") or task.get("runtimeErrorFingerprint"):
        return "unknown"
    return "agent"


def _acceptance_projection(
    task: Mapping[str, Any],
) -> dict[str, object]:
    raw_results = task.get("verifierResults")
    if raw_results is not None and not isinstance(raw_results, list):
        raise ValueError("evaluation verifierResults must be an array")
    results = raw_results if isinstance(raw_results, list) else []
    items: list[dict[str, object]] = []
    seen_indexes: set[int] = set()
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("evaluation verifier result must be an object")
        index = result.get("verifierIndex")
        passed = result.get("passed")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ValueError("evaluation verifier result has an invalid index")
        if not isinstance(passed, bool):
            raise ValueError("evaluation verifier result has an invalid status")
        if index in seen_indexes:
            raise ValueError("evaluation verifier results contain duplicate indexes")
        seen_indexes.add(index)
        items.append(
            {
                "id": f"verifier-{index}",
                "label": f"Verifier {index}",
                "status": "pass" if passed else "fail",
                "failureOwner": None if passed else _failure_owner(task),
                "explanation": (
                    "验收项通过。"
                    if passed
                    else "Agent 输出未满足该验收项。"
                ),
            }
        )
    items.sort(key=lambda item: int(str(item["id"]).split("-", 1)[1]))
    if results:
        passed_count = sum(
            isinstance(result, Mapping) and result.get("passed") is True
            for result in results
        )
        total_count = len(results)
    else:
        verifier = (
            task.get("verifier")
            if isinstance(task.get("verifier"), Mapping)
            else {}
        )
        passed_count = max(0, int(verifier.get("passed") or 0))
        total_count = max(0, int(verifier.get("total") or 0))
    if len(items) > _MAX_ACCEPTANCE_ITEMS:
        items = items[:_MAX_ACCEPTANCE_ITEMS]
    return {
        "passed": passed_count,
        "total": total_count,
        "items": items,
    }


def _explanation(
    task: Mapping[str, Any],
    transcript: Path,
) -> dict[str, object]:
    first_user, last_assistant = _transcript_texts(transcript)
    task_id_hash = hashlib.sha256(
        str(task.get("taskId") or "").encode("utf-8")
    ).hexdigest()
    return {
        "caseId": f"case-{task_id_hash[:16]}",
        "businessRequest": {"normalizedText": _task_excerpt(first_user)},
        "agentOutcome": {
            "normalizedSummary": _public_text(
                last_assistant,
                fallback="暂无可用的 Agent 输出。",
            )
        },
        "acceptance": _acceptance_projection(task),
    }


def import_snapshot(
    *,
    source_db: Path,
    report_path: Path,
    target_db: Path,
    target_session_dir: Path,
    run_id: str,
    write: bool,
) -> dict[str, object]:
    """Validate, and optionally import, one EnterpriseOps evaluation run."""

    normalized_run_id = str(run_id).strip()
    if not _RUN_ID.fullmatch(normalized_run_id):
        raise ValueError("run id must be a path-safe lowercase identifier")
    source_db = _resolved_regular_file(Path(source_db), label="source database")
    report_path = _resolved_regular_file(Path(report_path), label="evaluation report")
    target_db = Path(target_db)
    target_session_dir = Path(target_session_dir)
    source_root = source_db.parent.resolve()
    report = _json_object(report_path)
    if report.get("schemaVersion") != _REPORT_SCHEMA:
        raise ValueError("unsupported EnterpriseOps evaluation report schema")
    lane = report.get("lane")
    if not isinstance(lane, dict):
        raise ValueError("evaluation report has no lane object")
    tasks_value = lane.get("tasks")
    if not isinstance(tasks_value, list) or not tasks_value:
        raise ValueError("evaluation report has no tasks")
    tasks = [task for task in tasks_value if isinstance(task, dict)]
    if len(tasks) != len(tasks_value):
        raise ValueError("evaluation report contains an invalid task")
    if int(lane.get("taskCount") or len(tasks)) != len(tasks):
        raise ValueError("evaluation taskCount does not match task records")

    source_sha256 = _sha256(source_db)
    report_sha256 = _sha256(report_path)
    records = _source_rows(source_db, tasks)
    for record in records:
        row = record["row"]
        transcript, transcript_sha256 = _validate_source_transcript(
            str(row.get("transcript_ref") or ""),
            source_root=source_root,
            external_session_id=str(row.get("external_session_id") or ""),
        )
        record["transcript"] = transcript
        record["transcriptSha256"] = transcript_sha256

    receipt: dict[str, object] = {
        "schemaVersion": "rag-ime.eval-snapshot-import-receipt.v1",
        "status": "dry_run",
        "runId": normalized_run_id,
        "sessionCount": len(records),
        "sourceDatabaseSha256": source_sha256,
        "sourceReportSha256": report_sha256,
    }
    if not write:
        return receipt

    store = AgentSessionStore(target_db)
    store.initialize()
    existing = _existing_run_sessions(store, normalized_run_id)
    if existing:
        matches = _existing_snapshot_matches(
            store,
            existing,
            records,
            run_id=normalized_run_id,
            source_database_sha256=source_sha256,
            source_report_sha256=report_sha256,
            target_session_dir=target_session_dir,
        )
        backfilled_ids = _backfill_explanations(store, matches)
        if backfilled_ids:
            return {
                **receipt,
                "status": "explanation_backfilled",
                "sessionIds": backfilled_ids,
            }
        return {**receipt, "status": "already_imported"}

    split = str(report.get("split") or "unknown")
    workflow_profile = str(lane.get("workflowProfile") or "unknown")
    suite_id = "enterpriseops-csm"
    imported_ids: list[str] = []
    for record in records:
        task = record["task"]
        row = record["row"]
        index = int(record["taskIndex"])
        task_succeeded = bool(task.get("taskSucceeded"))
        verdict = "通过" if task_succeeded else "需复核"
        destination = (
            target_session_dir
            / "eval-lab"
            / normalized_run_id
            / f"task-{index:02d}-{record['transcriptSha256'][:12]}.jsonl"
        )
        _atomic_copy(
            record["transcript"],
            destination,
            str(record["transcriptSha256"]),
        )
        verifier = (
            task.get("verifier")
            if isinstance(task.get("verifier"), dict)
            else {}
        )
        metadata = {
            "protocolVersion": "2",
            "evaluationSnapshot": {
                "schemaVersion": "rag-ime.evaluation-snapshot.v1",
                "runId": normalized_run_id,
                "suiteId": suite_id,
                "split": split,
                "workflowProfile": workflow_profile,
                "sourceDatabaseSha256": source_sha256,
                "sourceReportSha256": report_sha256,
                "sourceTranscriptSha256": str(record["transcriptSha256"]),
                "taskAlias": f"Task {index}",
                "taskIndex": index,
                "taskIdSha256": hashlib.sha256(
                    str(task["taskId"]).encode("utf-8")
                ).hexdigest(),
                "taskSucceeded": task_succeeded,
                "terminalEvent": str(task.get("terminalEvent") or "unknown"),
                "verifier": {
                    "passed": int(verifier.get("passed") or 0),
                    "total": int(verifier.get("total") or 0),
                    "passRate": _number(verifier.get("passRate")),
                },
                "explanation": _explanation(
                    task,
                    record["transcript"],
                ),
                "toolCalls": int(task.get("toolCalls") or 0),
                "failedToolCalls": int(task.get("failedToolCalls") or 0),
                "latencyMs": _number(task.get("latencyMs")),
            },
        }
        created_at_ms = int(row.get("created_at_ms") or 0) or None
        updated_at_ms = int(row.get("updated_at_ms") or 0) or created_at_ms
        session = store.create(
            title=f"EnterpriseOps CSM · Task {index} · {verdict}",
            model_profile=str(row.get("model_profile") or "openai-codex/gpt-5.6-sol"),
            thinking_level=str(row.get("thinking_level") or "high"),
            tool_profile_version="subagent-readonly-v1",
            execution_mode="read_only",
            evaluation_snapshot=True,
            created_at_ms=created_at_ms,
        )
        session_id = str(session["id"])
        store.bind_runtime_session(
            session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id=str(row["external_session_id"]),
            transcript_ref=destination.as_posix(),
            binding_state="prepared",
            metadata=metadata,
            updated_at_ms=updated_at_ms,
        )
        store.set_status(
            session_id,
            "idle",
            message_count=int(row.get("message_count") or 0),
            last_message_preview="真实评测 Session · 只读快照",
            updated_at_ms=updated_at_ms,
        )
        imported_ids.append(session_id)

    return {
        **receipt,
        "status": "imported",
        "sessionIds": imported_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--target-db", type=Path, required=True)
    parser.add_argument("--target-session-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--write",
        action="store_true",
        help="copy and register snapshots; without this flag the command is read-only",
    )
    args = parser.parse_args()
    receipt = import_snapshot(
        source_db=args.source_db,
        report_path=args.report,
        target_db=args.target_db,
        target_session_dir=args.target_session_dir,
        run_id=args.run_id,
        write=args.write,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
