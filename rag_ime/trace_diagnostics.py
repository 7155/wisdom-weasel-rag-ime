"""Bounded Trace diagnostic extraction, score inputs, and report persistence.

The extractor reads only public Runtime projections supplied by its owner.  It
does not reopen Provider context, expose raw Tool arguments, or ask an AI Judge
to manufacture deterministic metrics.  A report freezes that extraction first;
later model findings may only cite evidence IDs from the frozen inspection.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations, sqlite_connection


TRACE_DIAGNOSTIC_INSPECTION_SCHEMA_VERSION = "rag-ime.trace-diagnostic-inspection.v1"
TRACE_DIAGNOSTIC_REPORT_SCHEMA_VERSION = "rag-ime.trace-diagnostic-report.v1"
TRACE_DIAGNOSTIC_RESULT_SCHEMA_VERSION = "rag-ime.trace-diagnostic-result.v1"
TRACE_DIAGNOSTIC_RUBRIC_VERSION = "trace-score-v1"

_TARGET_KINDS = frozenset({"session", "room", "run"})
_DIMENSIONS = (
    ("task_completion", "任务完成度"),
    ("evidence_diagnosis", "证据与诊断质量"),
    ("tool_runtime", "Tool / Runtime 可靠性"),
    ("context", "Context 质量"),
    ("room_collaboration", "Room / 多 Agent 协作"),
    ("memory_rag", "Memory / RAG"),
    ("efficiency", "效率"),
    ("repair_quality", "修复质量"),
)
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_FAILED_STATUSES = frozenset({"failed", "cancelled"})
_TIMEOUT_RE = re.compile(r"timeout|timed out|超时", re.IGNORECASE)
_SCHEMA_ERROR_RE = re.compile(r"schema|validation|invalid arguments?|参数校验|验证失败", re.IGNORECASE)
_TOKEN_RE = re.compile(r"token", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:/Users|/home|/Volumes)/[^\s'\"]+")
_SECRET_RE = re.compile(r"(?i)(authorization|api[_-]?key|token|secret)\s*[:=]\s*[^\s,;]+")
_RESULT_START = "--- TRACE_DIAGNOSTIC_RESULT_V1 ---"
_RESULT_END = "--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"


Reader = Callable[[str], Mapping[str, object] | None]
ObservationReader = Callable[[Mapping[str, object]], Mapping[str, object]]
EvalReader = Callable[[str], Sequence[Mapping[str, object]] | Mapping[str, object]]


def extract_trace_diagnostic_result(session_snapshot: Mapping[str, object]) -> dict[str, object]:
    """Parse the newest completed public assistant result block.

    The delimiter is only a transport envelope.  ``_validate_result`` still
    constrains every field, and report persistence later verifies all cited
    evidence IDs against the frozen inspection.
    """

    candidates: list[tuple[float, str]] = []
    for message in _mapping_sequence(session_snapshot.get("items")):
        if str(message.get("role") or "") != "assistant":
            continue
        if str(message.get("status") or "") not in {"completed", "idle"}:
            continue
        sequence = _number(message.get("timelineSequence"), _number(message.get("createdAtMs"), 0.0))
        for block in _mapping_sequence(message.get("blocks")):
            if str(block.get("status") or "") not in {"completed", "idle", ""}:
                continue
            text = _diagnostic_block_text(_mapping(block.get("data")))
            if _RESULT_START in text and _RESULT_END in text:
                candidates.append((sequence, text))
    if not candidates:
        raise ValueError("diagnostic Session has no completed structured result")
    text = max(candidates, key=lambda item: item[0])[1]
    encoded = text.split(_RESULT_START, 1)[1].split(_RESULT_END, 1)[0].strip()
    if encoded.startswith("```json"):
        encoded = encoded[7:].strip()
    elif encoded.startswith("```"):
        encoded = encoded[3:].strip()
    if encoded.endswith("```"):
        encoded = encoded[:-3].strip()
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ValueError("diagnostic structured result is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("diagnostic structured result must be an object")
    return _validate_result(value)


def inspect_trace_targets(
    *,
    targets: Sequence[Mapping[str, object]],
    session_reader: Reader,
    room_reader: Reader,
    observation_reader: ObservationReader,
    trace_reader: Reader,
    eval_reader: EvalReader,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Build one bounded multi-target diagnostic slice.

    Target order is preserved.  Repeated targets and Trace IDs are collapsed,
    but every target retains its own Trace mapping.  Missing source projections
    produce an explicit unavailable target rather than a fabricated snapshot.
    """

    normalized_targets = _normalize_targets(targets)
    timeline: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    observation_events: list[dict[str, object]] = []
    trace_ids: list[str] = []
    target_rows: list[dict[str, object]] = []
    room_sources: list[Mapping[str, object]] = []

    for target in normalized_targets:
        kind = str(target["kind"])
        identifier = str(target["id"])
        target_key = str(target["targetKey"])
        source: Mapping[str, object] | None = None
        try:
            if kind == "session":
                source = session_reader(identifier)
            elif kind == "room":
                source = room_reader(identifier)
                if source:
                    room_sources.append(source)
        except (KeyError, ValueError):
            source = None

        source_available = isinstance(source, Mapping) and bool(source)
        if source_available:
            if kind == "session":
                _extract_session_source(source or {}, target_key, timeline, evidence)
            elif kind == "room":
                _extract_room_source(source or {}, target_key, timeline, evidence)

        filters = {f"{kind}Id": identifier, "limit": 100}
        try:
            observation = observation_reader(filters)
        except (KeyError, ValueError):
            observation = {}
        target_trace_ids: list[str] = []
        for event in _mapping_sequence(observation.get("items")):
            projected = _observation_evidence(event, target_key)
            if projected is not None:
                observation_events.append(dict(event))
                evidence.append(projected)
                timeline.append(_timeline_from_evidence(projected, event))
            trace_id = _bounded_id(event.get("traceId"), 240)
            if trace_id and trace_id not in target_trace_ids:
                target_trace_ids.append(trace_id)
            if trace_id and trace_id not in trace_ids:
                trace_ids.append(trace_id)
        for trace_id in _string_sequence(target.get("traceIds"), maximum=32, item_maximum=240):
            if trace_id not in target_trace_ids:
                target_trace_ids.append(trace_id)
            if trace_id not in trace_ids:
                trace_ids.append(trace_id)
        target_rows.append(
            {
                **target,
                "traceIds": target_trace_ids[:32],
                "sourceAvailable": source_available,
            }
        )

    trace_ids_truncated = len(trace_ids) > 32
    trace_ids = trace_ids[:32]
    trace_payloads: list[Mapping[str, object]] = []
    eval_runs: list[Mapping[str, object]] = []
    for trace_id in trace_ids:
        try:
            raw_trace = trace_reader(trace_id)
        except (KeyError, ValueError):
            raw_trace = None
        trace = _unwrap_trace(raw_trace)
        if trace is not None:
            trace_payloads.append(trace)
            _extract_trace(trace, evidence)
        try:
            raw_evals = eval_reader(trace_id)
        except (KeyError, ValueError):
            raw_evals = []
        for run in _eval_items(raw_evals):
            eval_runs.append(run)
            evidence.append(_eval_evidence(run, trace_id))

    timeline = _dedupe(timeline, "evidenceId")
    evidence = _dedupe(evidence, "evidenceId")
    timeline.sort(key=lambda item: (int(item.get("createdAtMs") or 0), float(item.get("sequence") or 0), str(item["evidenceId"])))
    evidence.sort(key=lambda item: (int(item.get("createdAtMs") or 0), str(item["evidenceId"])))
    timeline_truncated = len(timeline) > 240
    evidence_truncated = len(evidence) > 512
    timeline = timeline[-240:]
    evidence = evidence[-512:]
    valid_evidence_ids = {str(item["evidenceId"]) for item in evidence}
    scorecard = _scorecard(
        observation_events=observation_events,
        traces=trace_payloads,
        eval_runs=eval_runs,
        rooms=room_sources,
        target_count=len(target_rows),
        valid_evidence_ids=valid_evidence_ids,
    )
    result = {
        "schemaVersion": TRACE_DIAGNOSTIC_INSPECTION_SCHEMA_VERSION,
        "generatedAtMs": int(time.time() * 1000) if now_ms is None else int(now_ms),
        "targets": target_rows,
        "traceIds": trace_ids,
        "timeline": timeline,
        "evidence": evidence,
        "scorecard": scorecard,
        "truncated": {
            "timeline": timeline_truncated,
            "evidence": evidence_truncated,
            "traceIds": trace_ids_truncated,
        },
    }
    validate_contract(result, "trace-diagnostic-inspection.v1.json")
    return result


class TraceDiagnosticReportStore:
    """Revisioned local persistence for structured Trace diagnostic reports."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def create(
        self,
        *,
        diagnostic_session_id: str,
        title: str,
        targets: Sequence[Mapping[str, object]],
        inspection: Mapping[str, object],
        now_ms: int | None = None,
    ) -> dict[str, object]:
        session_id = _required_id(diagnostic_session_id, "diagnosticSessionId", 240)
        normalized_title = " ".join(str(title).split())[:240]
        if not normalized_title:
            raise ValueError("title is required")
        inspection_payload = dict(inspection)
        validate_contract(inspection_payload, "trace-diagnostic-inspection.v1.json")
        normalized_targets = [dict(item) for item in targets]
        if normalized_targets != inspection_payload.get("targets"):
            raise ValueError("targets must match the frozen inspection")
        encoded_inspection = _canonical_json(inspection_payload)
        inspection_hash = _sha256(encoded_inspection)
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        report_id = f"trace-report:{_sha256(f'{session_id}|{inspection_hash}')[:32]}"
        payload = {
            "schemaVersion": TRACE_DIAGNOSTIC_REPORT_SCHEMA_VERSION,
            "reportId": report_id,
            "revision": 1,
            "status": "generating",
            "title": normalized_title,
            "diagnosticSessionId": session_id,
            "targets": normalized_targets,
            "traceIds": list(inspection_payload.get("traceIds") or []),
            "inspectionSha256": inspection_hash,
            "inspection": inspection_payload,
            "result": None,
            "failureReason": "",
            "createdAtMs": timestamp,
            "updatedAtMs": timestamp,
        }
        validate_contract(payload, "trace-diagnostic-report.v1.json")
        self.initialize()
        encoded = _canonical_json(payload)
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT report_id FROM trace_diagnostic_reports WHERE diagnostic_session_id=?",
                (session_id,),
            ).fetchone()
            if existing is not None:
                # Resolve the persisted head by the session binding first.  A
                # changed inspection produces a different content-derived
                # report ID, so loading by the new ID would leak a KeyError
                # instead of reporting the binding conflict to the caller.
                existing_payload = _load_report(conn, str(existing["report_id"]))
                if (
                    existing_payload.get("diagnosticSessionId") != session_id
                    or existing_payload.get("inspectionSha256") != inspection_hash
                ):
                    raise ValueError("diagnostic Session is already bound to another report")
                return existing_payload
            conn.execute(
                "INSERT INTO trace_diagnostic_reports(report_id,diagnostic_session_id,current_revision,status,created_at_ms,updated_at_ms) VALUES(?,?,1,'generating',?,?)",
                (report_id, session_id, timestamp, timestamp),
            )
            conn.execute(
                "INSERT INTO trace_diagnostic_report_revisions(report_id,revision,payload_hash,payload_json,created_at_ms) VALUES(?,1,?,?,?)",
                (report_id, _sha256(encoded), encoded, timestamp),
            )
            conn.executemany(
                "INSERT INTO trace_diagnostic_report_targets(report_id,target_kind,target_id) VALUES(?,?,?)",
                [(report_id, str(item["kind"]), str(item["id"])) for item in normalized_targets],
            )
        return payload

    def complete(
        self,
        report_id: str,
        *,
        expected_revision: int,
        result: Mapping[str, object],
        now_ms: int | None = None,
    ) -> dict[str, object]:
        identifier = _required_id(report_id, "reportId", 80)
        normalized_result = _validate_result(result)
        self.initialize()
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _load_report(conn, identifier)
            revision = int(current["revision"])
            if current["status"] == "completed":
                if current["result"] == normalized_result:
                    return current
                raise ValueError("completed report is immutable")
            if revision != int(expected_revision):
                raise ValueError("report revision conflict")
            evidence_ids = {
                str(item["evidenceId"])
                for item in _mapping_sequence(_mapping(current.get("inspection")).get("evidence"))
            }
            for evidence_id in _result_evidence_ids(normalized_result):
                if evidence_id not in evidence_ids:
                    raise ValueError(f"unknown evidenceId: {evidence_id}")
            next_payload = {
                **current,
                "revision": revision + 1,
                "status": "completed",
                "result": normalized_result,
                "failureReason": "",
                "updatedAtMs": timestamp,
            }
            validate_contract(next_payload, "trace-diagnostic-report.v1.json")
            encoded = _canonical_json(next_payload)
            conn.execute(
                "INSERT INTO trace_diagnostic_report_revisions(report_id,revision,payload_hash,payload_json,created_at_ms) VALUES(?,?,?,?,?)",
                (identifier, revision + 1, _sha256(encoded), encoded, timestamp),
            )
            conn.execute(
                "UPDATE trace_diagnostic_reports SET current_revision=?,status='completed',updated_at_ms=? WHERE report_id=? AND current_revision=?",
                (revision + 1, timestamp, identifier, revision),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("report revision conflict")
        return next_payload

    def fail(
        self,
        report_id: str,
        *,
        expected_revision: int,
        reason: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        identifier = _required_id(report_id, "reportId", 80)
        public_reason = _public_text(reason, 1000)
        if not public_reason:
            raise ValueError("failure reason is required")
        self.initialize()
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _load_report(conn, identifier)
            revision = int(current["revision"])
            if current["status"] == "failed":
                return current
            if current["status"] == "completed":
                raise ValueError("completed report is immutable")
            if revision != int(expected_revision):
                raise ValueError("report revision conflict")
            next_payload = {
                **current,
                "revision": revision + 1,
                "status": "failed",
                "result": None,
                "failureReason": public_reason,
                "updatedAtMs": timestamp,
            }
            validate_contract(next_payload, "trace-diagnostic-report.v1.json")
            encoded = _canonical_json(next_payload)
            conn.execute(
                "INSERT INTO trace_diagnostic_report_revisions(report_id,revision,payload_hash,payload_json,created_at_ms) VALUES(?,?,?,?,?)",
                (identifier, revision + 1, _sha256(encoded), encoded, timestamp),
            )
            conn.execute(
                "UPDATE trace_diagnostic_reports SET current_revision=?,status='failed',updated_at_ms=? WHERE report_id=? AND current_revision=?",
                (revision + 1, timestamp, identifier, revision),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("report revision conflict")
        return next_payload

    def get(self, report_id: str) -> dict[str, object] | None:
        identifier = _required_id(report_id, "reportId", 80)
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = conn.execute(
                "SELECT 1 FROM trace_diagnostic_reports WHERE report_id=?",
                (identifier,),
            ).fetchone()
            return _load_report(conn, identifier) if row is not None else None

    def list(self, *, limit: int = 100) -> dict[str, object]:
        safe_limit = _bounded_integer(limit, minimum=1, maximum=100, name="limit")
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM trace_diagnostic_reports").fetchone()[0])
            rows = conn.execute(
                "SELECT report_id FROM trace_diagnostic_reports ORDER BY updated_at_ms DESC,report_id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
            items = [_report_summary(_load_report(conn, str(row["report_id"]))) for row in rows]
        result = {
            "schemaVersion": "rag-ime.trace-diagnostic-report-list.v1",
            "total": total,
            "truncated": total > len(items),
            "items": items,
        }
        validate_contract(result, "trace-diagnostic-report-list.v1.json")
        return result

    def for_target(self, kind: str, target_id: str, *, limit: int = 100) -> list[dict[str, object]]:
        normalized_kind = str(kind).strip()
        if normalized_kind not in _TARGET_KINDS:
            raise ValueError("target kind is not supported")
        identifier = _required_id(target_id, "targetId", 240)
        safe_limit = _bounded_integer(limit, minimum=1, maximum=100, name="limit")
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            rows = conn.execute(
                """
                SELECT reports.report_id
                FROM trace_diagnostic_report_targets AS targets
                JOIN trace_diagnostic_reports AS reports ON reports.report_id=targets.report_id
                WHERE targets.target_kind=? AND targets.target_id=?
                ORDER BY reports.updated_at_ms DESC,reports.report_id DESC LIMIT ?
                """,
                (normalized_kind, identifier, safe_limit),
            ).fetchall()
            return [_load_report(conn, str(row["report_id"])) for row in rows]


def _normalize_targets(targets: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    if isinstance(targets, (str, bytes, bytearray)) or not 1 <= len(targets) <= 12:
        raise ValueError("targets must contain between 1 and 12 objects")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in targets:
        if not isinstance(raw, Mapping):
            raise ValueError("target must be an object")
        kind = str(raw.get("kind") or "").strip()
        if kind not in _TARGET_KINDS:
            raise ValueError("target kind is not supported")
        identifier = _required_id(raw.get("id"), "target id", 240)
        key = f"{kind}:{identifier}"
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "targetKey": key,
                "kind": kind,
                "id": identifier,
                "title": _public_text(raw.get("title"), 240),
                "traceIds": _string_sequence(raw.get("traceIds"), maximum=32, item_maximum=240),
                "sourceAvailable": bool(raw.get("sourceAvailable", False)),
            }
        )
    if not result:
        raise ValueError("targets must not collapse to an empty set")
    return result


def _extract_session_source(
    source: Mapping[str, object],
    target_key: str,
    timeline: list[dict[str, object]],
    evidence: list[dict[str, object]],
) -> None:
    session_id = _bounded_id(source.get("sessionId"), 240) or target_key.removeprefix("session:")
    for message in _mapping_sequence(source.get("items")):
        message_id = _bounded_id(message.get("id"), 240) or _sha256(_canonical_json(message))[:24]
        role = _bounded_id(message.get("role"), 40) or "message"
        status = _bounded_id(message.get("status"), 80)
        sequence = _number(message.get("timelineSequence"), _number(message.get("sequence"), 0.0))
        created = _nonnegative_int(message.get("createdAtMs"))
        for block in _mapping_sequence(message.get("blocks")):
            block_id = _bounded_id(block.get("id"), 240) or _sha256(_canonical_json(block))[:24]
            kind = _bounded_id(block.get("type"), 80) or role
            text = _text_from_mapping(_mapping(block.get("data")))
            if not text:
                continue
            evidence_id = f"session:{session_id}:message:{message_id}:block:{block_id}"
            item = {
                "evidenceId": evidence_id,
                "targetKey": target_key,
                "sourceKind": "session",
                "sourceRef": f"session:{session_id}:message:{message_id}",
                "status": status,
                "summary": text,
                "createdAtMs": created,
                "traceId": "",
            }
            evidence.append(item)
            timeline.append(
                {
                    "evidenceId": evidence_id,
                    "targetKey": target_key,
                    "kind": kind if kind != "text" else role,
                    "status": status,
                    "summary": text,
                    "sequence": sequence,
                    "createdAtMs": created,
                    "sourceRef": item["sourceRef"],
                    "traceId": "",
                }
            )
    for event in _mapping_sequence(source.get("liveEvents")):
        event_id = _bounded_id(event.get("eventId"), 240) or _sha256(_canonical_json(event))[:24]
        payload = _mapping(event.get("payload"))
        summary = _text_from_mapping(payload)
        if not summary:
            continue
        evidence_id = f"session:{session_id}:event:{event_id}"
        item = {
            "evidenceId": evidence_id,
            "targetKey": target_key,
            "sourceKind": "session_event",
            "sourceRef": f"session:{session_id}:event:{event_id}",
            "status": _bounded_id(payload.get("status"), 80),
            "summary": summary,
            "createdAtMs": _nonnegative_int(event.get("createdAtMs")),
            "traceId": _bounded_id(payload.get("traceId"), 240),
        }
        evidence.append(item)
        timeline.append(
            {
                "evidenceId": evidence_id,
                "targetKey": target_key,
                "kind": _bounded_id(event.get("eventType"), 80) or "session_event",
                "status": item["status"],
                "summary": summary,
                "sequence": _number(event.get("timelineSequence"), _number(event.get("sequence"), 0.0)),
                "createdAtMs": item["createdAtMs"],
                "sourceRef": item["sourceRef"],
                "traceId": item["traceId"],
            }
        )


def _extract_room_source(
    source: Mapping[str, object],
    target_key: str,
    timeline: list[dict[str, object]],
    evidence: list[dict[str, object]],
) -> None:
    room = _mapping(source.get("room"))
    room_id = _bounded_id(room.get("id"), 240) or target_key.removeprefix("room:")
    for event in _mapping_sequence(source.get("events")):
        event_id = _bounded_id(event.get("eventId"), 240) or _sha256(_canonical_json(event))[:24]
        summary = _text_from_mapping(_mapping(event.get("payload")))
        if not summary:
            summary = _bounded_id(event.get("eventType"), 80)
        evidence_id = f"room:{room_id}:event:{event_id}"
        item = {
            "evidenceId": evidence_id,
            "targetKey": target_key,
            "sourceKind": "room_event",
            "sourceRef": f"room:{room_id}:event:{event_id}",
            "status": _room_event_status(event),
            "summary": summary,
            "createdAtMs": _nonnegative_int(event.get("createdAtMs")),
            "traceId": _bounded_id(_mapping(event.get("payload")).get("traceId"), 240),
        }
        evidence.append(item)
        timeline.append(
            {
                "evidenceId": evidence_id,
                "targetKey": target_key,
                "kind": _bounded_id(event.get("eventType"), 80) or "room_event",
                "status": item["status"],
                "summary": summary,
                "sequence": _number(event.get("sequence"), 0.0),
                "createdAtMs": item["createdAtMs"],
                "sourceRef": item["sourceRef"],
                "traceId": item["traceId"],
            }
        )


def _observation_evidence(event: Mapping[str, object], target_key: str) -> dict[str, object] | None:
    event_id = _bounded_id(event.get("eventId"), 240)
    if not event_id:
        return None
    return {
        "evidenceId": f"observation:{event_id}",
        "targetKey": target_key,
        "sourceKind": "observation",
        "sourceRef": f"observation:{event_id}",
        "status": _bounded_id(event.get("status"), 80),
        "summary": _public_text(event.get("summary") or event.get("name"), 1200),
        "createdAtMs": _nonnegative_int(event.get("createdAtMs")),
        "traceId": _bounded_id(event.get("traceId"), 240),
    }


def _timeline_from_evidence(item: Mapping[str, object], event: Mapping[str, object]) -> dict[str, object]:
    return {
        "evidenceId": item["evidenceId"],
        "targetKey": item["targetKey"],
        "kind": _bounded_id(event.get("phase"), 80) or _bounded_id(event.get("category"), 80) or "observation",
        "status": item["status"],
        "summary": item["summary"],
        "sequence": _number(event.get("sequence"), 0.0),
        "createdAtMs": item["createdAtMs"],
        "sourceRef": item["sourceRef"],
        "traceId": item["traceId"],
    }


def _extract_trace(trace: Mapping[str, object], evidence: list[dict[str, object]]) -> None:
    trace_id = _bounded_id(trace.get("traceId"), 240)
    binding = _mapping(trace.get("binding"))
    target_key = _trace_target_key(binding)
    for span in _mapping_sequence(trace.get("spans")):
        span_id = _bounded_id(span.get("spanId"), 240)
        if not span_id:
            continue
        evidence.append(
            {
                "evidenceId": f"trace:{trace_id}:span:{span_id}",
                "targetKey": target_key,
                "sourceKind": "trace_span",
                "sourceRef": f"trace:{trace_id}:span:{span_id}",
                "status": _bounded_id(span.get("status"), 80),
                "summary": _public_text(span.get("name"), 1200),
                "createdAtMs": _nonnegative_int(span.get("startedAtMs")),
                "traceId": trace_id,
            }
        )
    for item in _mapping_sequence(trace.get("evidence")):
        evidence_id = _bounded_id(item.get("evidenceId"), 240)
        if not evidence_id:
            continue
        evidence.append(
            {
                "evidenceId": f"trace:{trace_id}:evidence:{evidence_id}",
                "targetKey": target_key,
                "sourceKind": "trace_evidence",
                "sourceRef": _public_text(item.get("sourceRef"), 640) or f"trace:{trace_id}",
                "status": _bounded_id(item.get("disposition"), 80),
                "summary": _public_text(item.get("evidenceStage"), 1200),
                "createdAtMs": _nonnegative_int(trace.get("updatedAtMs")),
                "traceId": trace_id,
            }
        )


def _eval_evidence(run: Mapping[str, object], trace_id: str) -> dict[str, object]:
    eval_id = _bounded_id(run.get("evalRunId"), 240) or _sha256(_canonical_json(run))[:24]
    return {
        "evidenceId": f"eval:{eval_id}",
        "targetKey": "",
        "sourceKind": "eval_run",
        "sourceRef": f"eval:{eval_id}",
        "status": _bounded_id(run.get("status"), 80),
        "summary": _public_text(_mapping(run.get("evaluator")).get("displayName") or run.get("evaluatorDisplayName") or "EvalRun", 1200),
        "createdAtMs": _nonnegative_int(run.get("createdAtMs")),
        "traceId": trace_id,
    }


def _scorecard(
    *,
    observation_events: Sequence[Mapping[str, object]],
    traces: Sequence[Mapping[str, object]],
    eval_runs: Sequence[Mapping[str, object]],
    rooms: Sequence[Mapping[str, object]],
    target_count: int,
    valid_evidence_ids: set[str],
) -> dict[str, object]:
    dimensions = {
        identifier: _dimension(identifier, title)
        for identifier, title in _DIMENSIONS
    }
    terminal_tools = [
        event
        for event in observation_events
        if str(event.get("category") or "") == "tool"
        and str(event.get("status") or "") in _TERMINAL_STATUSES
    ]
    terminal_ids = [f"observation:{event['eventId']}" for event in terminal_tools if f"observation:{event.get('eventId')}" in valid_evidence_ids]
    if terminal_tools:
        completed = sum(str(event.get("status") or "") == "completed" for event in terminal_tools)
        failed = sum(str(event.get("status") or "") in _FAILED_STATUSES for event in terminal_tools)
        timeouts = sum(_TIMEOUT_RE.search(_event_search_text(event)) is not None for event in terminal_tools)
        schema_errors = sum(_SCHEMA_ERROR_RE.search(_event_search_text(event)) is not None for event in terminal_tools)
        metrics = [
            _metric("terminal_tool_success_rate", "终态 Tool 成功率", completed / len(terminal_tools), "ratio", terminal_ids),
            _metric(
                "timeout_rate",
                "超时率",
                timeouts / len(terminal_tools),
                "ratio",
                terminal_ids,
                note="当前按公开终态事件文本分类，是可复现 proxy，不替代未来的 typed Tool receipt。",
            ),
            _metric(
                "schema_error_rate",
                "Schema 错误率",
                schema_errors / len(terminal_tools),
                "ratio",
                terminal_ids,
                note="当前按公开终态事件文本分类，是可复现 proxy，不替代未来的 typed Tool receipt。",
            ),
            _metric("terminal_tool_count", "终态 Tool 数", float(len(terminal_tools)), "count", terminal_ids),
            _metric("failed_tool_count", "失败 Tool 数", float(failed), "count", terminal_ids),
        ]
        dimensions["tool_runtime"] = _measured_dimension(
            dimensions["tool_runtime"],
            score=100.0 * completed / len(terminal_tools),
            metrics=metrics,
            evidence_ids=terminal_ids,
            note="成功率只统计已有终态 Tool；额外验证调用不会因数量多而被惩罚。",
        )

        durations = [float(event["durationMs"]) for event in terminal_tools if isinstance(event.get("durationMs"), (int, float)) and not isinstance(event.get("durationMs"), bool)]
        token_values = _numeric_metric_values((*observation_events, *traces), _TOKEN_RE)
        efficiency_metrics: list[dict[str, object]] = []
        if durations:
            durations.sort()
            efficiency_metrics.extend(
                [
                    _metric("wall_clock_total_ms", "累计 Tool 墙钟时间", sum(durations), "ms", terminal_ids),
                    _metric("wall_clock_p95_ms", "Tool p95 墙钟时间", _percentile(durations, 0.95), "ms", terminal_ids),
                ]
            )
        if token_values:
            efficiency_metrics.append(_metric("observed_token_total", "已观测 Token", sum(token_values), "tokens", terminal_ids))
        if efficiency_metrics:
            dimensions["efficiency"] = _measured_dimension(
                dimensions["efficiency"],
                score=None,
                metrics=efficiency_metrics,
                evidence_ids=terminal_ids,
                note="仅展示绝对成本；没有可比 cohort 时不声称浪费或节省。",
                applicability="partial",
            )

    ground_truth_metrics = _ground_truth_eval_metrics(eval_runs)
    evidence_metrics = _select_metrics(ground_truth_metrics, {"precision", "recall", "f1", "evidence_precision", "evidence_recall", "evidence_f1"})
    if evidence_metrics:
        eval_ids = _eval_evidence_ids(eval_runs, ground_truth_only=True, valid=valid_evidence_ids)
        f1 = evidence_metrics.get("evidence_f1", evidence_metrics.get("f1"))
        dimensions["evidence_diagnosis"] = _measured_dimension(
            dimensions["evidence_diagnosis"],
            score=(100.0 * f1) if f1 is not None and 0 <= f1 <= 1 else None,
            metrics=[_metric(key, key, value, "ratio", eval_ids, authority="ground_truth") for key, value in sorted(evidence_metrics.items())],
            evidence_ids=eval_ids,
            note="来自冻结标签 EvalRun；AI Judge 不参与 evidence F1。",
            authority="ground_truth",
        )
    retrieval_metrics = _select_metrics(
        ground_truth_metrics,
        {"recall_at_k", "recall@k", "mrr", "ndcg", "ndcg@k", "citation_precision", "citation_recall", "abstention_success_rate"},
    )
    if retrieval_metrics:
        eval_ids = _eval_evidence_ids(eval_runs, ground_truth_only=True, valid=valid_evidence_ids)
        dimensions["memory_rag"] = _measured_dimension(
            dimensions["memory_rag"],
            score=None,
            metrics=[_metric(key, key, value, "ratio", eval_ids, authority="ground_truth") for key, value in sorted(retrieval_metrics.items())],
            evidence_ids=eval_ids,
            note="只采用冻结测试集或人工标签 EvalRun。",
            authority="ground_truth",
        )

    context_events = [event for event in observation_events if str(event.get("category") or "") == "context"]
    if context_events:
        context_ids = [f"observation:{event['eventId']}" for event in context_events if f"observation:{event.get('eventId')}" in valid_evidence_ids]
        context_metrics = _all_numeric_metrics(context_events)
        dimensions["context"] = _measured_dimension(
            dimensions["context"],
            score=None,
            metrics=[_metric(key, key, value, "observed", context_ids) for key, value in sorted(context_metrics.items())],
            evidence_ids=context_ids,
            note="仅报告 Runtime 已记录的 Context 指标；语义组织质量留给标记为估计的 Judge。",
            applicability="partial",
        )

    if rooms:
        orphaned = 0
        total_work = 0
        room_ids: list[str] = []
        for source in rooms:
            room = _mapping(source.get("room"))
            room_id = _bounded_id(room.get("id"), 240)
            work_items = _mapping_sequence(room.get("workItems"))
            total_work += len(work_items)
            orphaned += sum(not _work_item_owner(item) for item in work_items)
            for event in _mapping_sequence(source.get("events")):
                evidence_id = f"room:{room_id}:event:{_bounded_id(event.get('eventId'), 240)}"
                if evidence_id in valid_evidence_ids:
                    room_ids.append(evidence_id)
        dimensions["room_collaboration"] = _measured_dimension(
            dimensions["room_collaboration"],
            score=None,
            metrics=[
                _metric("work_item_count", "WorkItem 数", float(total_work), "count", room_ids),
                _metric("orphaned_work_item_count", "无 owner WorkItem 数", float(orphaned), "count", room_ids),
            ],
            evidence_ids=room_ids,
            note="拆解是否合理等语义项不冒充确定性分数。",
            applicability="partial",
        )

    requirement_metrics = _requirement_metrics(observation_events)
    if requirement_metrics is not None:
        satisfied, expected, requirement_ids = requirement_metrics
        score = (100.0 * satisfied / expected) if expected else None
        dimensions["task_completion"] = _measured_dimension(
            dimensions["task_completion"],
            score=score,
            metrics=[
                _metric("requirements_satisfied", "已满足需求", float(satisfied), "count", requirement_ids),
                _metric("requirements_expected", "应满足需求", float(expected), "count", requirement_ids),
            ],
            evidence_ids=requirement_ids,
            note="需求总数和完成数必须来自 Runtime/Eval 证据。",
        )

    comparison = _comparison(traces, target_count)
    return {
        "rubricVersion": TRACE_DIAGNOSTIC_RUBRIC_VERSION,
        "hardGates": [
            {
                "gateId": "task_completion",
                "status": "unknown" if requirement_metrics is None else ("passed" if requirement_metrics[0] == requirement_metrics[1] else "failed"),
                "evidenceIds": [] if requirement_metrics is None else requirement_metrics[2],
                "reason": "缺少权威需求完成回执。" if requirement_metrics is None else "按权威需求计数判定。",
            },
            {
                "gateId": "unsupported_completion_claim",
                "status": "unknown",
                "evidenceIds": [],
                "reason": "需要将助手完成声明与文件、测试、安装或运行证据做语义核对。",
            },
        ],
        "dimensions": [dimensions[identifier] for identifier, _title in _DIMENSIONS],
        "comparison": comparison,
    }


def _dimension(identifier: str, title: str) -> dict[str, object]:
    return {
        "dimensionId": identifier,
        "title": title,
        "applicability": "unknown",
        "authority": "deterministic",
        "score": None,
        "scoreMax": 100,
        "metrics": [],
        "evidenceIds": [],
        "note": "当前 canonical Trace 没有足够证据，不能打分。",
    }


def _measured_dimension(
    base: Mapping[str, object],
    *,
    score: float | None,
    metrics: Sequence[Mapping[str, object]],
    evidence_ids: Sequence[str],
    note: str,
    applicability: str = "measured",
    authority: str = "deterministic",
) -> dict[str, object]:
    return {
        **base,
        "applicability": applicability,
        "authority": authority,
        "score": None if score is None else max(0.0, min(100.0, float(score))),
        "metrics": [dict(item) for item in metrics],
        "evidenceIds": list(dict.fromkeys(evidence_ids)),
        "note": note,
    }


def _metric(
    identifier: str,
    label: str,
    value: float | None,
    unit: str,
    evidence_ids: Sequence[str],
    *,
    authority: str = "deterministic",
    note: str = "",
) -> dict[str, object]:
    return {
        "metricId": identifier,
        "label": label[:160],
        "value": None if value is None else float(value),
        "unit": unit[:40],
        "authority": authority,
        "evidenceIds": list(dict.fromkeys(evidence_ids))[:128],
        "note": note[:500],
    }


def _comparison(traces: Sequence[Mapping[str, object]], target_count: int) -> dict[str, object]:
    if target_count < 2:
        return {"eligible": False, "status": "incomparable", "reason": "只有一个诊断对象，不能形成对照。"}
    fingerprints = {
        str(_mapping(trace.get("input")).get("fingerprint") or "")
        for trace in traces
    }
    if not traces or "" in fingerprints:
        return {"eligible": False, "status": "unknown", "reason": "缺少完整 source fingerprint，禁止声称差值或节省。"}
    if len(fingerprints) != 1:
        return {"eligible": False, "status": "incomparable", "reason": "输入 fingerprint 不同，只能分别展示，不能推导修复或效率差值。"}
    return {"eligible": True, "status": "conditionally_comparable", "reason": "输入 fingerprint 相同，但 fixture、模型、配置与工具版本尚未全部冻结。"}


def _validate_result(result: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(result, Mapping):
        raise ValueError("result must be an object")
    normalized = dict(result)
    if normalized.get("schemaVersion") != TRACE_DIAGNOSTIC_RESULT_SCHEMA_VERSION:
        raise ValueError("trace diagnostic result schemaVersion is invalid")
    normalized["summary"] = _public_text(normalized.get("summary"), 4000)
    if not normalized["summary"]:
        raise ValueError("result summary is required")
    hard_gates: list[dict[str, object]] = []
    for gate in _mapping_sequence(normalized.get("hardGates"))[:16]:
        status = str(gate.get("status") or "")
        if status not in {"passed", "failed", "unknown"}:
            raise ValueError("hard gate status is invalid")
        hard_gates.append(
            {
                "gateId": _required_id(gate.get("gateId"), "gateId", 120),
                "status": status,
                "reason": _public_text(gate.get("reason"), 1000),
                "evidenceIds": _string_sequence(gate.get("evidenceIds"), maximum=128, item_maximum=640),
            }
        )
    judge_scores: list[dict[str, object]] = []
    dimension_ids = {identifier for identifier, _title in _DIMENSIONS}
    raw_judge_score_value = normalized.get("judgeScores")
    if not isinstance(raw_judge_score_value, list):
        raise ValueError("judgeScores must be an array")
    if any(not isinstance(item, Mapping) for item in raw_judge_score_value):
        raise ValueError("judgeScores must contain only objects")
    raw_judge_scores = list(raw_judge_score_value)
    if len(raw_judge_scores) > 8:
        raise ValueError("too many judge scores")
    seen_judge_dimensions: set[str] = set()
    for score in raw_judge_scores:
        dimension_id = str(score.get("dimensionId") or "")
        if dimension_id not in dimension_ids:
            raise ValueError("judge dimension is invalid")
        if dimension_id in seen_judge_dimensions:
            raise ValueError(f"duplicate judge dimension: {dimension_id}")
        seen_judge_dimensions.add(dimension_id)
        value = score.get("score")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3):
            raise ValueError("AI Judge score must be 0..3 or null")
        if score.get("authority") != "ai_judge_estimate":
            raise ValueError("semantic score authority must be ai_judge_estimate")
        judge_scores.append(
            {
                "dimensionId": dimension_id,
                "score": value,
                "authority": "ai_judge_estimate",
                "explanation": _public_text(score.get("explanation"), 1600),
                "evidenceIds": _string_sequence(score.get("evidenceIds"), maximum=128, item_maximum=640),
            }
        )
    findings: list[dict[str, object]] = []
    for finding in _mapping_sequence(normalized.get("findings"))[:100]:
        dimension_id = str(finding.get("dimensionId") or "")
        if dimension_id not in dimension_ids:
            raise ValueError("finding dimension is invalid")
        severity = str(finding.get("severity") or "")
        confidence = str(finding.get("confidence") or "")
        if severity not in {"critical", "high", "medium", "low"}:
            raise ValueError("finding severity is invalid")
        if confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("finding confidence is invalid")
        findings.append(
            {
                "findingId": _required_id(finding.get("findingId"), "findingId", 160),
                "dimensionId": dimension_id,
                "severity": severity,
                "observation": _public_text(finding.get("observation"), 2000),
                "hypothesis": _public_text(finding.get("hypothesis"), 2000),
                "conclusion": _public_text(finding.get("conclusion"), 2000),
                "confidence": confidence,
                "evidenceIds": _string_sequence(finding.get("evidenceIds"), maximum=128, item_maximum=640),
                "candidateRepair": _public_text(finding.get("candidateRepair"), 2000),
                "verification": _public_text(finding.get("verification"), 2000),
            }
        )
    payload = {
        "schemaVersion": TRACE_DIAGNOSTIC_RESULT_SCHEMA_VERSION,
        "summary": normalized["summary"],
        "hardGates": hard_gates,
        "judgeScores": judge_scores,
        "findings": findings,
    }
    validate_contract(payload, "trace-diagnostic-result.v1.json")
    return payload


def _result_evidence_ids(result: Mapping[str, object]) -> list[str]:
    values: list[str] = []
    for collection in ("hardGates", "judgeScores", "findings"):
        for item in _mapping_sequence(result.get(collection)):
            for evidence_id in _string_sequence(item.get("evidenceIds"), maximum=128, item_maximum=640):
                if evidence_id not in values:
                    values.append(evidence_id)
    return values


def _load_report(conn: sqlite3.Connection, report_id: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT revisions.payload_json
        FROM trace_diagnostic_reports AS reports
        JOIN trace_diagnostic_report_revisions AS revisions
          ON revisions.report_id=reports.report_id AND revisions.revision=reports.current_revision
        WHERE reports.report_id=?
        """,
        (report_id,),
    ).fetchone()
    if row is None:
        raise KeyError(report_id)
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):
        raise RuntimeError("persisted Trace diagnostic report is invalid")
    validate_contract(payload, "trace-diagnostic-report.v1.json")
    return payload


def _report_summary(report: Mapping[str, object]) -> dict[str, object]:
    targets = _mapping_sequence(report.get("targets"))
    return {
        "reportId": str(report.get("reportId") or ""),
        "revision": int(report.get("revision") or 0),
        "status": str(report.get("status") or ""),
        "title": str(report.get("title") or ""),
        "diagnosticSessionId": str(report.get("diagnosticSessionId") or ""),
        "targetKeys": [str(item.get("targetKey") or "") for item in targets],
        "targets": targets,
        "traceIds": list(report.get("traceIds") or []),
        "failureReason": str(report.get("failureReason") or ""),
        "createdAtMs": int(report.get("createdAtMs") or 0),
        "updatedAtMs": int(report.get("updatedAtMs") or 0),
    }


def _unwrap_trace(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    nested = value.get("trace")
    if isinstance(nested, Mapping):
        return nested
    return value if value.get("schemaVersion") == "rag-ime.trace-envelope.v1" else None


def _eval_items(value: Sequence[Mapping[str, object]] | Mapping[str, object]) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        return _mapping_sequence(value.get("items"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _ground_truth_eval_metrics(runs: Sequence[Mapping[str, object]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for run in runs:
        if str(run.get("metricAuthority") or "") != "ground_truth":
            continue
        for key, value in _mapping(run.get("metrics")).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[str(key).lower()] = float(value)
    return result


def _select_metrics(values: Mapping[str, float], allowed: set[str]) -> dict[str, float]:
    return {key: value for key, value in values.items() if key in allowed}


def _eval_evidence_ids(runs: Sequence[Mapping[str, object]], *, ground_truth_only: bool, valid: set[str]) -> list[str]:
    result: list[str] = []
    for run in runs:
        if ground_truth_only and str(run.get("metricAuthority") or "") != "ground_truth":
            continue
        eval_id = _bounded_id(run.get("evalRunId"), 240)
        evidence_id = f"eval:{eval_id}"
        if eval_id and evidence_id in valid:
            result.append(evidence_id)
    return result


def _requirement_metrics(events: Sequence[Mapping[str, object]]) -> tuple[int, int, list[str]] | None:
    for event in reversed(events):
        metrics = _mapping(event.get("metrics"))
        satisfied = metrics.get("requirementsSatisfied")
        expected = metrics.get("requirementsExpected")
        if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (satisfied, expected)) and int(expected) >= int(satisfied):
            return int(satisfied), int(expected), [f"observation:{event['eventId']}"]
    return None


def _all_numeric_metrics(events: Sequence[Mapping[str, object]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for event in events:
        for key, value in _mapping(event.get("metrics")).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[str(key)] = totals.get(str(key), 0.0) + float(value)
    return totals


def _numeric_metric_values(values: Sequence[Mapping[str, object]], matcher: re.Pattern[str]) -> list[float]:
    result: list[float] = []
    for value in values:
        for key, item in _mapping(value.get("metrics")).items():
            if matcher.search(str(key)) and isinstance(item, (int, float)) and not isinstance(item, bool):
                result.append(float(item))
    return result


def _event_search_text(event: Mapping[str, object]) -> str:
    return " ".join(
        (
            str(event.get("name") or ""),
            str(event.get("summary") or ""),
            _canonical_json(_mapping(event.get("attributes"))),
        )
    )


def _trace_target_key(binding: Mapping[str, object]) -> str:
    for kind, field in (("session", "sessionId"), ("room", "roomId"), ("run", "runId")):
        identifier = _bounded_id(binding.get(field), 240)
        if identifier:
            return f"{kind}:{identifier}"
    return ""


def _work_item_owner(item: Mapping[str, object]) -> str:
    for key in ("ownerId", "assignedTo", "ownerParticipantId", "participantId"):
        value = _bounded_id(item.get(key), 240)
        if value:
            return value
    return ""


def _room_event_status(event: Mapping[str, object]) -> str:
    kind = str(event.get("eventType") or "")
    if kind == "turn_failed":
        return "failed"
    if kind == "turn_completed":
        return "completed"
    return _bounded_id(_mapping(event.get("payload")).get("status"), 80)


def _text_from_mapping(value: Mapping[str, object]) -> str:
    for key in ("text", "content", "summary", "error", "message", "reason", "title"):
        text = _public_text(value.get(key), 1200)
        if text:
            return text
    for key in ("data", "post", "result"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            text = _text_from_mapping(nested)
            if text:
                return text
    return ""


def _diagnostic_block_text(value: Mapping[str, object]) -> str:
    """Return a bounded raw public text block for structured-result parsing.

    Display projections intentionally truncate text to 1,200 characters.  The
    structured report envelope is larger, so parsing uses a separate 512 KiB bound
    and applies field-level redaction/limits only after JSON decoding.
    """

    for key in ("text", "content"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            return raw[:524_288]
    for key in ("data", "post", "result"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            text = _diagnostic_block_text(nested)
            if text:
                return text
    return ""


def _public_text(value: object, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    text = _PATH_RE.sub("[path redacted]", text)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return text[:maximum]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_sequence(value: object, *, maximum: int, item_maximum: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[str] = []
    for item in value[:maximum]:
        normalized = _bounded_id(item, item_maximum)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _bounded_id(value: object, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _required_id(value: object, name: str, maximum: int) -> str:
    normalized = _bounded_id(value, maximum)
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _number(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded_integer(value: object, *, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


def _dedupe(values: Sequence[Mapping[str, object]], key: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in values:
        identity = str(value.get(key) or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(dict(value))
    return result


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * quantile + 0.999999)))
    return float(values[index])


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
