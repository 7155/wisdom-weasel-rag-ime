"""Authoritative Trace repair receipts and repair-bound AI Judge rechecks.

The observation journal is a progress projection.  This module gives a repair
run an append-only authority: the change and test identifiers must first be
stored as typed evidence, and a recheck can only evaluate the exact repair
trace named by the receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .ai_judge_eval import (
    AI_JUDGE_RUBRIC_VERSION,
    DEFAULT_AI_JUDGE_EVALUATOR,
    parse_ai_judge_metrics,
)
from .db import apply_database_migrations, sqlite_connection
from .contracts.json_schema import ContractValidationError, validate_contract
from .eval_run_store import EvalRunStore
from .trace_runtime import build_eval_run
from .trace_store import TraceStore


TRACE_REPAIR_RECEIPT_SCHEMA_VERSION = "rag-ime.trace-repair-receipt.v1"
_TOKEN = r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$"
_TEST_STATUSES = frozenset({"passed", "failed", "blocked"})
_TERMINAL_EVENT_TYPES = frozenset(
    {
        "tool_finished",
        "tool_result",
        "tool_execution_end",
        "tool_completed",
    }
)
_COMPLETED_SESSION_STATUS = "idle"
_MUTATING_TOOL_RE = re.compile(
    r"(?:^|[._:/ -])(?:workspace[_ -]?)?(?:patch|edit|write|delete|remove|move|rename|mkdir|touch|chmod)(?:$|[._:/ -])"
    r"|(?:^|[._:/ -])(?:apply_patch|file_change|changed_file)(?:$|[._:/ -])",
    re.IGNORECASE,
)
_TEST_TOOL_RE = re.compile(
    r"(?:^|[._:/ -])(?:test|tests|typecheck|type-check|lint|build|verify|check)(?:$|[._:/ -])",
    re.IGNORECASE,
)
_TEST_COMMAND_RE = re.compile(
    r"(?:\b(?:pytest|vitest|jest|mocha|unittest|rspec|go\s+test|cargo\s+test)\b"
    r"|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|typecheck|lint|build|verify|check)\b"
    r"|\b(?:tsc|eslint|ruff|mypy|pyright)\b"
    r"|(?:^|\s)(?:make|just)\s+(?:test|typecheck|lint|build|verify|check)\b)",
    re.IGNORECASE,
)
_SAFE_CANONICAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


class TraceRepairValidationError(ValueError):
    """The repair receipt or one of its evidence links is invalid."""


class TraceRepairConflict(RuntimeError):
    """A stable repair identity was rebound to different content."""


def _token(value: object, name: str) -> str:
    import re

    if not isinstance(value, str) or re.fullmatch(_TOKEN, value) is None:
        raise TraceRepairValidationError(f"{name} must be a bounded identifier")
    return value


def _json_object(value: object, name: str) -> str:
    if not isinstance(value, Mapping):
        raise TraceRepairValidationError(f"{name} must be an object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TraceRepairValidationError(f"{name} must be JSON serializable") from exc
    return encoded


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _record_is_change(name: str) -> bool:
    return bool(name and _MUTATING_TOOL_RE.search(name))


def _record_is_test(name: str, command: str) -> bool:
    return bool(
        (name and _TEST_TOOL_RE.search(name))
        or (command and _TEST_COMMAND_RE.search(command))
    )


def _public_tool_name(name: str) -> str:
    """Keep only a bounded tool label in canonical evidence."""

    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "_", name.strip())[:80]
    return normalized if _SAFE_CANONICAL_ID_RE.fullmatch(normalized or "") else "tool"


def _canonical_signal(
    *,
    identity: object,
    tool_name: object,
    command: object = "",
    operation: object = "",
    failed: bool,
    sandboxed: bool = False,
    executed: bool = False,
    order: int = 0,
) -> dict[str, object] | None:
    if not isinstance(identity, str) or not identity.strip():
        return None
    raw_identity = identity.strip()
    canonical_identity = (
        raw_identity
        if _SAFE_CANONICAL_ID_RE.fullmatch(raw_identity) is not None
        else f"signal:{hashlib.sha256(raw_identity.encode('utf-8')).hexdigest()[:32]}"
    )
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None
    normalized_name = tool_name.strip()
    command_text = command.strip() if isinstance(command, str) else ""
    operation_text = operation.strip() if isinstance(operation, str) else ""
    is_change = _record_is_change(normalized_name)
    is_test = _record_is_test(normalized_name, f"{operation_text} {command_text}")
    if not is_change and not is_test:
        return None
    return {
        "id": canonical_identity,
        "toolName": _public_tool_name(normalized_name),
        "isChange": is_change,
        "isTest": is_test,
        "failed": failed,
        "sandboxed": sandboxed if is_test else False,
        "executed": executed if is_test else False,
        "order": max(0, int(order)),
    }


def _session_tool_signal(event: Mapping[str, object]) -> dict[str, object] | None:
    event_type = event.get("eventType")
    if not isinstance(event_type, str) or event_type.lower() not in _TERMINAL_EVENT_TYPES:
        return None
    payload = _mapping(event.get("payload"))
    args = _mapping(payload.get("args"))
    payload_result = _mapping(payload.get("result"))
    nested_receipt = _mapping(payload_result.get("receipt"))
    result = nested_receipt or payload_result
    exit_code = result.get("exitCode")
    workspace_receipt = (
        result.get("schemaVersion") == "rag-ime.workspace-command-receipt.v1"
    )
    has_exit_code = isinstance(exit_code, int) and not isinstance(exit_code, bool)
    receipt_failed = bool(
        workspace_receipt
        and (
            result.get("timedOut") is True
            or result.get("outputLimited") is True
            or result.get("ok") is False
            or result.get("validationSucceeded") is False
        )
    )
    failed = payload.get("isError") is True or (
        has_exit_code and exit_code != 0
    ) or receipt_failed
    command_sha256 = result.get("commandSha256")
    sandboxed = bool(
        workspace_receipt
        and isinstance(command_sha256, str)
        and re.fullmatch(r"[a-f0-9]{64}", command_sha256) is not None
        and result.get("networkAllowed") is False
        and result.get("timedOut") is False
        and result.get("outputLimited") is False
        and isinstance(result.get("sourceReadOnly"), bool)
        and isinstance(result.get("temporaryWritesDiscarded"), bool)
    )
    executed = bool(workspace_receipt and has_exit_code)
    return _canonical_signal(
        identity=payload.get("toolCallId") or event.get("eventId"),
        tool_name=payload.get("toolName"),
        command=args.get("command"),
        failed=failed,
        sandboxed=sandboxed,
        executed=executed,
        order=event.get("sequence") if isinstance(event.get("sequence"), int) else 0,
    )


def _trace_tool_signal(span: Mapping[str, object]) -> dict[str, object] | None:
    status = span.get("status")
    if status not in {"completed", "failed"}:
        return None
    attributes = _mapping(span.get("attributes"))
    metrics = _mapping(span.get("metrics"))
    exit_code = attributes.get("exitCode")
    failed = status == "failed" or metrics.get("isError") is True or (
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
    )
    return _canonical_signal(
        identity=span.get("spanId"),
        tool_name=attributes.get("toolName"),
        command=attributes.get("command"),
        operation=span.get("name"),
        failed=failed,
        executed=isinstance(exit_code, int) and not isinstance(exit_code, bool),
        order=(
            int(span.get("endedAtMs"))
            if isinstance(span.get("endedAtMs"), int)
            else 0
        ),
    )


def _snapshot_records(
    session_snapshot: Mapping[str, object],
    repair_trace: Mapping[str, object],
) -> list[dict[str, object]]:
    """Extract and correlate only the two canonical Runtime containers."""

    candidates: list[dict[str, object]] = []
    trace_order_by_identity: dict[str, int] = {}

    spans = repair_trace.get("spans")
    if isinstance(spans, list):
        for span in spans:
            if not isinstance(span, Mapping):
                continue
            span_id = span.get("spanId")
            ended_at_ms = span.get("endedAtMs")
            if (
                isinstance(span_id, str)
                and span_id
                and isinstance(ended_at_ms, int)
                and not isinstance(ended_at_ms, bool)
            ):
                trace_order_by_identity[span_id] = max(0, ended_at_ms)
            signal = _trace_tool_signal(span)
            if signal is not None:
                candidates.append(signal)

    live_events = session_snapshot.get("liveEvents")
    if isinstance(live_events, list):
        started_by_call: dict[str, Mapping[str, object]] = {}
        for event in live_events:
            if not isinstance(event, Mapping):
                continue
            payload = _mapping(event.get("payload"))
            tool_call_id = payload.get("toolCallId")
            event_type = str(event.get("eventType") or "").lower()
            if event_type == "tool_started":
                if isinstance(tool_call_id, str) and tool_call_id:
                    started_by_call[tool_call_id] = payload
                continue
            started = (
                started_by_call.get(tool_call_id)
                if isinstance(tool_call_id, str)
                else None
            )
            candidate_event = event
            if started is not None:
                terminal_args = _mapping(payload.get("args"))
                candidate_event = {
                    **event,
                    "payload": {
                        **started,
                        **payload,
                        "args": dict(terminal_args or _mapping(started.get("args"))),
                    },
                }
            signal = _session_tool_signal(candidate_event)
            if signal is not None:
                trace_order = trace_order_by_identity.get(str(signal["id"]))
                if trace_order is not None:
                    signal["order"] = trace_order
                candidates.append(signal)
    return candidates


def derive_repair_evidence(
    *,
    repair_session_id: str,
    repair_trace_id: str,
    session_snapshot: Mapping[str, object],
    repair_trace: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Derive canonical repair evidence from server-owned Session + Trace data.

    The caller supplies only candidate IDs.  All user-controlled evidence
    prose, command strings, paths, status claims, and counts are ignored.
    The returned records contain bounded IDs, counts, and tool labels only.
    """

    session_id = _token(repair_session_id, "repairSessionId")
    trace_id = _token(repair_trace_id, "repairTraceId")
    if not isinstance(session_snapshot, Mapping):
        raise TraceRepairValidationError("repair Session snapshot is unavailable")
    if not isinstance(repair_trace, Mapping):
        raise TraceRepairValidationError("repair Trace snapshot is unavailable")
    persisted_trace_id = str(repair_trace.get("traceId") or "").strip()
    if persisted_trace_id and persisted_trace_id != trace_id:
        raise TraceRepairValidationError("repairTraceId does not match persisted Trace")
    if str(repair_trace.get("status") or "").strip().lower() != "completed":
        raise TraceRepairValidationError("repair trace must be completed")
    binding = repair_trace.get("binding")
    binding_session_id = (
        str(binding.get("sessionId") or "").strip()
        if isinstance(binding, Mapping)
        else ""
    )
    if binding_session_id != session_id:
        raise TraceRepairValidationError("repair trace is bound to a different Session")
    if repair_trace.get("truncated") is True or repair_trace.get("partial") is True:
        raise TraceRepairValidationError("repair trace is truncated")
    if session_snapshot.get("partial") is True or session_snapshot.get("truncated") is True:
        raise TraceRepairValidationError("repair Session snapshot is truncated")
    snapshot_scope = str(session_snapshot.get("snapshotScope") or "").strip().lower()
    if snapshot_scope == "recent":
        raise TraceRepairValidationError("repair Session snapshot is partial")
    snapshot_session_id = str(session_snapshot.get("sessionId") or "").strip()
    if snapshot_session_id and snapshot_session_id != session_id:
        raise TraceRepairValidationError("repairSessionId does not match Session snapshot")
    if session_snapshot.get("status") != _COMPLETED_SESSION_STATUS:
        raise TraceRepairValidationError("repair Session must be idle")

    # Deduplicate the same Tool call represented by a durable event and a
    # Trace span. A failed terminal event wins over a successful-looking span.
    by_identity: dict[str, dict[str, object]] = {}
    for signal in _snapshot_records(session_snapshot, repair_trace):
        identity = str(signal["id"])
        current = by_identity.get(identity)
        if current is None:
            by_identity[identity] = signal
        else:
            current["failed"] = bool(current.get("failed")) or bool(signal.get("failed"))
            current["isChange"] = bool(current.get("isChange")) or bool(signal.get("isChange"))
            current["isTest"] = bool(current.get("isTest")) or bool(signal.get("isTest"))
            current["sandboxed"] = bool(current.get("sandboxed")) or bool(
                signal.get("sandboxed")
            )
            current["executed"] = bool(current.get("executed")) or bool(
                signal.get("executed")
            )
            current["order"] = max(
                int(current.get("order") or 0),
                int(signal.get("order") or 0),
            )
            if str(current.get("toolName") or "tool") == "tool":
                current["toolName"] = signal.get("toolName")
    signals = list(by_identity.values())
    changes = [item for item in signals if item.get("isChange") and not item.get("failed")]
    executed_tests = [
        item for item in signals if item.get("isTest") and item.get("executed")
    ]
    latest_change_order = max(
        (int(item.get("order") or 0) for item in changes),
        default=0,
    )
    tests = (
        [
            item
            for item in executed_tests
            if int(item.get("order") or 0) > latest_change_order
        ]
        if latest_change_order > 0
        else executed_tests
    )
    successful_tests = [item for item in tests if not item.get("failed")]
    sandboxed_tests = [item for item in successful_tests if item.get("sandboxed")]
    passed_tests = successful_tests
    failed_tests = [item for item in tests if item.get("failed")]
    test_status = "failed" if failed_tests else ("passed" if passed_tests else "blocked")

    def project(kind: str, selected: list[dict[str, object]]) -> dict[str, object]:
        tool_names = sorted({str(item.get("toolName") or "tool") for item in selected})[:32]
        signal_ids = sorted({str(item.get("id") or "") for item in selected})[:64]
        common: dict[str, object] = {
            "schemaVersion": "rag-ime.trace-repair-canonical-evidence.v1",
            "evidenceKind": kind,
            "repairSessionId": session_id,
            "repairTraceId": trace_id,
            "eventCount": len(selected),
            "completedCount": len(selected),
            "toolCount": len(tool_names),
            "toolNames": tool_names,
            "signalIds": signal_ids,
        }
        if kind == "change":
            common["changeCount"] = len(selected)
        else:
            common.update(
                {
                    "testCount": len(tests),
                    "passedCount": len(passed_tests),
                    "failedCount": len(failed_tests),
                    "sandboxRequired": False,
                    "sandboxedCount": len(sandboxed_tests),
                    "sessionTerminalRequired": True,
                    "sessionTerminalCount": len(passed_tests),
                    "status": test_status,
                }
            )
        return common

    return {
        "change": project("change", changes),
        "test": project("test", tests),
    }


class TraceRepairStore:
    """SQLite-backed append-only store for typed repair evidence and receipts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def record_change_evidence(
        self,
        *,
        source_scope: str,
        source_trace_id: str,
        evidence: Mapping[str, object],
        evidence_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        return self._record_evidence(
            kind="change",
            source_scope=source_scope,
            source_trace_id=source_trace_id,
            evidence=evidence,
            evidence_id=evidence_id,
            test_status="",
            created_at_ms=created_at_ms,
        )

    def record_test_evidence(
        self,
        *,
        source_scope: str,
        source_trace_id: str,
        evidence: Mapping[str, object],
        status: str,
        evidence_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        if status not in _TEST_STATUSES:
            raise TraceRepairValidationError("test evidence status is not supported")
        return self._record_evidence(
            kind="test",
            source_scope=source_scope,
            source_trace_id=source_trace_id,
            evidence=evidence,
            evidence_id=evidence_id,
            test_status=status,
            created_at_ms=created_at_ms,
        )

    def _record_evidence(
        self,
        *,
        kind: str,
        source_scope: str,
        source_trace_id: str,
        evidence: Mapping[str, object],
        evidence_id: str | None,
        test_status: str,
        created_at_ms: int | None,
    ) -> dict[str, object]:
        scope = _token(source_scope, "sourceScope")
        trace_id = _token(source_trace_id, "sourceTraceId")
        encoded = _json_object(evidence, "evidence")
        identifier = evidence_id or f"{kind}-evidence:{_sha256(f'{kind}|{scope}|{trace_id}|{encoded}')[:32]}"
        identifier = _token(identifier, "evidenceId")
        created = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        if created < 0:
            raise TraceRepairValidationError("createdAtMs must be non-negative")
        payload = {
            "schemaVersion": "rag-ime.trace-repair-evidence.v1",
            "evidenceId": identifier,
            "evidenceKind": kind,
            "sourceScope": scope,
            "sourceTraceId": trace_id,
            "testStatus": test_status,
            "evidence": json.loads(encoded),
            "createdAtMs": created,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_hash = _sha256(payload_json)
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT payload_hash, payload_json FROM trace_repair_evidence WHERE evidence_id = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                old_payload = json.loads(str(existing["payload_json"]))
                comparable = {key: value for key, value in payload.items() if key != "createdAtMs"}
                old_comparable = {key: value for key, value in old_payload.items() if key != "createdAtMs"}
                if old_comparable != comparable:
                    raise TraceRepairConflict(f"evidence identity {identifier!r} was rebound")
                return old_payload
            conn.execute(
                "INSERT INTO trace_repair_evidence(evidence_id, evidence_kind, source_scope, source_trace_id, test_status, created_at_ms, payload_hash, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, kind, scope, trace_id, test_status, created, payload_hash, payload_json),
            )
        return payload

    def get_evidence(self, evidence_id: str) -> dict[str, object] | None:
        identifier = _token(evidence_id, "evidenceId")
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = conn.execute("SELECT payload_hash, payload_json FROM trace_repair_evidence WHERE evidence_id = ?", (identifier,)).fetchone()
        return _decode_stored_payload(row, kind="evidence") if row is not None else None

    def persist_receipt(
        self,
        *,
        source_scope: str,
        source_trace_id: str,
        failure_ref: str,
        change_receipt_id: str,
        test_evidence_id: str,
        repair_trace_id: str,
        repair_session_id: str,
        repair_receipt_id: str | None = None,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        scope = _token(source_scope, "sourceScope")
        source = _token(source_trace_id, "sourceTraceId")
        failure = _token(failure_ref, "failureRef")
        change_id = _token(change_receipt_id, "changeReceiptId")
        test_id = _token(test_evidence_id, "testEvidenceId")
        repair = _token(repair_trace_id, "repairTraceId")
        repair_session = _token(repair_session_id, "repairSessionId")
        self.initialize()
        created = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        if created < 0:
            raise TraceRepairValidationError("createdAtMs must be non-negative")
        identifier = _token(repair_receipt_id or f"repair-receipt:{repair}", "repairReceiptId")
        repair_payload = TraceStore(self.db_path).get(repair)
        if repair_payload is None:
            raise TraceRepairValidationError("repair trace is not persisted")
        if str(repair_payload.get("status") or "") != "completed":
            raise TraceRepairValidationError("repair trace must be completed")
        if repair_payload.get("truncated") is True or repair_payload.get("partial") is True:
            raise TraceRepairValidationError("repair trace is truncated")
        binding = repair_payload.get("binding")
        if not isinstance(binding, Mapping):
            raise TraceRepairValidationError("repair Trace has no Session binding")
        bound_session = str(binding.get("sessionId") or "").strip()
        if bound_session != repair_session:
            raise TraceRepairValidationError("repair Trace Session binding does not match")
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            change = conn.execute("SELECT * FROM trace_repair_evidence WHERE evidence_id = ?", (change_id,)).fetchone()
            test = conn.execute("SELECT * FROM trace_repair_evidence WHERE evidence_id = ?", (test_id,)).fetchone()
            if change is None or str(change["evidence_kind"]) != "change":
                raise TraceRepairValidationError("changeReceiptId does not reference change evidence")
            if test is None or str(test["evidence_kind"]) != "test":
                raise TraceRepairValidationError("testEvidenceId does not reference test evidence")
            for row, name, expected_kind in (
                (change, "changeReceiptId", "change"),
                (test, "testEvidenceId", "test"),
            ):
                nested = _stored_evidence_object(row)
                if (
                    nested.get("schemaVersion")
                    != "rag-ime.trace-repair-canonical-evidence.v1"
                    or nested.get("evidenceKind") != expected_kind
                ):
                    raise TraceRepairValidationError(f"{name} canonical evidence kind is invalid")
                if (
                    str(row["source_scope"]) != "trace-repair"
                    or str(row["source_trace_id"]) != repair
                ):
                    raise TraceRepairValidationError(f"{name} is not bound to the repair Trace")
                if (
                    nested.get("repairSessionId") != repair_session
                    or nested.get("repairTraceId") != repair
                ):
                    raise TraceRepairValidationError(
                        f"{name} is not bound to the repair Trace and Session"
                    )
            source_trace = conn.execute("SELECT 1 FROM trace_envelopes WHERE trace_id = ?", (source,)).fetchone()
            if source_trace is None:
                raise TraceRepairValidationError("source trace is not persisted")
            change_payload = _stored_evidence_object(change)
            test_payload = _stored_evidence_object(test)
            if int(change_payload.get("changeCount") or 0) < 1:
                raise TraceRepairValidationError("change evidence has no completed mutating Tool")
            test_status = str(test["test_status"])
            if test_status != "passed" or test_payload.get("status") != "passed":
                raise TraceRepairValidationError("test evidence is not passed")
            sandboxed_test_count = int(test_payload.get("sandboxedCount") or 0)
            session_terminal_count = int(
                test_payload.get("sessionTerminalCount") or 0
            )
            has_host_sandbox = (
                test_payload.get("sandboxRequired") is True
                and sandboxed_test_count >= 1
            )
            has_server_terminal = (
                test_payload.get("sessionTerminalRequired") is True
                and session_terminal_count >= 1
            )
            if not has_host_sandbox and not has_server_terminal:
                raise TraceRepairValidationError(
                    "test evidence has no authoritative completed execution"
                )
            payload = {
                "schemaVersion": TRACE_REPAIR_RECEIPT_SCHEMA_VERSION,
                "repairReceiptId": identifier,
                "sourceScope": scope,
                "sourceTraceId": source,
                "failureRef": failure,
                "changeReceiptId": change_id,
                "testEvidenceId": test_id,
                "testStatus": test_status,
                "sandboxStatus": (
                    "passed" if sandboxed_test_count >= 1 else "not_required"
                ),
                "sandboxedTestCount": sandboxed_test_count,
                "repairTraceId": repair,
                "repairSessionId": repair_session,
                "createdAtMs": created,
            }
            try:
                validate_contract(payload, "trace-repair-receipt.v1.json")
            except (ContractValidationError, ValueError) as exc:
                raise TraceRepairValidationError(str(exc)) from exc
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            payload_hash = _sha256(payload_json)
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT payload_hash, payload_json FROM trace_repair_receipts WHERE repair_receipt_id = ?", (identifier,)).fetchone()
            if existing is not None:
                old = json.loads(str(existing["payload_json"]))
                comparable = {key: value for key, value in payload.items() if key != "createdAtMs"}
                old_comparable = {key: value for key, value in old.items() if key != "createdAtMs"}
                if str(existing["payload_hash"]) != payload_hash and old_comparable != comparable:
                    raise TraceRepairConflict(f"repair receipt identity {identifier!r} was rebound")
                return old
            conn.execute(
                "INSERT INTO trace_repair_receipts(repair_receipt_id, source_scope, source_trace_id, failure_ref, change_receipt_id, test_evidence_id, test_status, repair_trace_id, created_at_ms, payload_hash, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, scope, source, failure, change_id, test_id, test_status, repair, created, payload_hash, payload_json),
            )
        return payload

    def get_receipt(self, repair_receipt_id: str) -> dict[str, object] | None:
        identifier = _token(repair_receipt_id, "repairReceiptId")
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = conn.execute("SELECT payload_hash, payload_json FROM trace_repair_receipts WHERE repair_receipt_id = ?", (identifier,)).fetchone()
        return _decode_stored_payload(row, kind="receipt") if row is not None else None


def run_ai_judge_recheck(
    *,
    trace_store: TraceStore,
    repair_store: TraceRepairStore,
    eval_store: EvalRunStore,
    source_trace_id: str,
    repair_trace_id: str,
    source_scope: str,
    failure_ref: str,
    judge: Callable[[Mapping[str, object]], Mapping[str, object] | str],
    now_ms: int | None = None,
) -> dict[str, object]:
    """Evaluate exactly the receipt's repair trace and persist provenance."""

    source = _token(source_trace_id, "sourceTraceId")
    repair = _token(repair_trace_id, "repairTraceId")
    scope = _token(source_scope, "sourceScope")
    failure = _token(failure_ref, "failureRef")
    receipt = next((item for item in _receipts_for_store(repair_store) if item.get("repairTraceId") == repair), None)
    if receipt is None:
        raise TraceRepairValidationError("repair trace is not bound to a persisted repair receipt")
    source_payload = trace_store.get(source)
    repair_payload = trace_store.get(repair)
    if source_payload is None:
        raise TraceRepairValidationError("source trace is not persisted")
    if repair_payload is None:
        raise TraceRepairValidationError("repair trace is not persisted")
    if str(repair_payload.get("status")) != "completed":
        raise TraceRepairValidationError("repair trace must be completed")
    expected_binding = {
        "sourceTraceId": source,
        "sourceScope": scope,
        "failureRef": failure,
        "repairTraceId": repair,
    }
    if any(receipt.get(field) != expected for field, expected in expected_binding.items()):
        raise TraceRepairValidationError("repair receipt binding does not match recheck request")
    if receipt.get("testStatus") != "passed":
        raise TraceRepairValidationError("repair recheck requires passed test evidence")
    metrics = parse_ai_judge_metrics(judge(repair_payload))
    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    eval_id = "eval:ai-judge-recheck:" + _sha256(f"{source}|{repair}|{scope}|{failure}")[:32]
    evaluator = dict(DEFAULT_AI_JUDGE_EVALUATOR)
    run = build_eval_run(
        eval_run_id=eval_id,
        trace_ids=[repair],
        mode="ai_judge",
        truth_kind="none",
        metrics=metrics,
        evaluator=evaluator,
        requested_evaluator=evaluator,
        prompt_version=AI_JUDGE_RUBRIC_VERSION,
        rubric_version=AI_JUDGE_RUBRIC_VERSION,
        input_trace_fingerprint=str(repair_payload.get("input", {}).get("fingerprint")) if isinstance(repair_payload.get("input"), Mapping) else None,
        started_at_ms=timestamp,
        completed_at_ms=timestamp,
        elapsed_ms=0,
        latency_ms=0,
        fallback_used=False,
        now_ms=timestamp,
        updated_at_ms=timestamp,
        source_trace_id=source,
        repair_trace_id=repair,
        repair_source_scope=scope,
        repair_failure_ref=failure,
        repair_receipt_id=str(receipt["repairReceiptId"]),
        change_receipt_id=str(receipt["changeReceiptId"]),
        test_evidence_id=str(receipt["testEvidenceId"]),
        test_status="passed",
    )
    return eval_store.persist(run)


def _receipts_for_store(store: TraceRepairStore) -> list[dict[str, object]]:
    store.initialize()
    with sqlite_connection(store.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
        rows = conn.execute("SELECT payload_hash, payload_json FROM trace_repair_receipts ORDER BY created_at_ms, repair_receipt_id").fetchall()
    return [_decode_stored_payload(row, kind="receipt") for row in rows]


def _decode_stored_payload(row: sqlite3.Row, *, kind: str) -> dict[str, object]:
    raw = str(row["payload_json"])
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TraceRepairValidationError(f"persisted repair {kind} is not an object")
    expected_hash = str(row["payload_hash"])
    if _sha256(raw) != expected_hash:
        raise TraceRepairValidationError(f"persisted repair {kind} hash does not match")
    if kind == "receipt":
        try:
            validate_contract(payload, "trace-repair-receipt.v1.json")
        except (ContractValidationError, ValueError) as exc:
            raise TraceRepairValidationError(str(exc)) from exc
    return payload


def _stored_evidence_object(row: sqlite3.Row) -> Mapping[str, object]:
    """Return the required canonical evidence object."""

    raw = str(row["payload_json"])
    if _sha256(raw) != str(row["payload_hash"]):
        raise TraceRepairValidationError("persisted repair evidence hash does not match")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise TraceRepairValidationError("persisted repair evidence is invalid")
    if not isinstance(payload, Mapping):
        raise TraceRepairValidationError("persisted repair evidence is not an object")
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping):
        raise TraceRepairValidationError("persisted repair evidence has no canonical payload")
    return evidence


__all__ = [
    "TRACE_REPAIR_RECEIPT_SCHEMA_VERSION",
    "TraceRepairConflict",
    "TraceRepairStore",
    "TraceRepairValidationError",
    "derive_repair_evidence",
    "run_ai_judge_recheck",
]
