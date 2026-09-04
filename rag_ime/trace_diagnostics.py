"""Bounded Trace diagnostic extraction, score inputs, and report persistence.

The extractor reads only public Runtime projections supplied by its owner.  It
does not reopen Provider context, expose raw Tool arguments, or ask an AI Judge
to manufacture deterministic metrics.  A report freezes that extraction first;
later model findings may only cite evidence IDs from the frozen inspection.
"""

from __future__ import annotations

import hashlib
import json
import math
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
_FAILURE_ATTRIBUTION_LAYERS = ("tool", "skill", "template", "workflow", "model")
_FAILURE_ATTRIBUTION_VERDICTS = frozenset(
    {"primary", "contributing", "healthy", "unknown", "not_applicable"}
)
_EVIDENCE_FAILURE_RE = re.compile(
    r"timeout|timed out|failed|failure|error|unavailable|blocked|stale|超时|失败|错误|不可用|阻塞",
    re.IGNORECASE,
)
_SCHEMA_ERROR_RE = re.compile(r"schema|validation|invalid arguments?|参数校验|验证失败", re.IGNORECASE)
_TOKEN_RE = re.compile(r"token", re.IGNORECASE)
_TRACE_FINGERPRINT_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_REPORT_CURSOR_RE = re.compile(r"^([0-9]+)\.([a-f0-9]{32})$")
_PATH_RE = re.compile(r"(?:/Users|/home|/Volumes)/[^\s'\"]+")
_SECRET_RE = re.compile(r"(?i)(authorization|api[_-]?key|token|secret)\s*[:=]\s*[^\s,;]+")
_RESULT_START = "--- TRACE_DIAGNOSTIC_RESULT_V1 ---"
_RESULT_END = "--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"


Reader = Callable[[str], Mapping[str, object] | None]
ObservationReader = Callable[[Mapping[str, object]], Mapping[str, object]]
EvalReader = Callable[[str], Sequence[Mapping[str, object]] | Mapping[str, object]]
EnvironmentReader = Callable[[str, str], Mapping[str, object] | None]


def extract_trace_diagnostic_result(session_snapshot: Mapping[str, object]) -> dict[str, object]:
    """Parse the newest completed public assistant result block.

    The delimiter is only a transport envelope.  New extraction is governed
    by ``_validate_result`` and therefore requires the presentation and its
    complete failure attribution; report loading is the only compatibility
    path that permits legacy omissions.
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
    environment_reader: EnvironmentReader | None = None,
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
    environment_inputs: dict[str, Mapping[str, object]] = {}
    source_hashes: dict[str, str] = {}

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
            source_hashes[target_key] = _sha256(_canonical_json(source))
            if kind == "session":
                _extract_session_source(source or {}, target_key, timeline, evidence)
            elif kind == "room":
                _extract_room_source(source or {}, target_key, timeline, evidence)
        if environment_reader is not None:
            try:
                environment = environment_reader(kind, identifier)
            except (KeyError, ValueError):
                environment = None
            if isinstance(environment, Mapping):
                environment_inputs[target_key] = environment

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
    trace_payloads_by_id: dict[str, Mapping[str, object]] = {}
    eval_runs: list[Mapping[str, object]] = []
    for trace_id in trace_ids:
        try:
            raw_trace = trace_reader(trace_id)
        except (KeyError, ValueError):
            raw_trace = None
        trace = _unwrap_trace(raw_trace)
        if trace is not None:
            trace_payloads.append(trace)
            persisted_trace_id = _bounded_id(trace.get("traceId"), 240)
            if persisted_trace_id:
                trace_payloads_by_id[persisted_trace_id] = trace
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
    evidence_by_id = {str(item["evidenceId"]): item for item in evidence}
    requirements = _requirements_from_timeline(timeline, valid_evidence_ids)
    captured_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    environment = _environment_snapshot(
        captured_at_ms=captured_at_ms,
        targets=target_rows,
        source_hashes=source_hashes,
        environment_inputs=environment_inputs,
        traces=trace_payloads_by_id,
    )
    scorecard = _scorecard(
        observation_events=observation_events,
        traces=trace_payloads,
        eval_runs=eval_runs,
        rooms=room_sources,
        targets=target_rows,
        target_count=len(target_rows),
        valid_evidence_ids=valid_evidence_ids,
        evidence_by_id=evidence_by_id,
    )
    result = {
        "schemaVersion": TRACE_DIAGNOSTIC_INSPECTION_SCHEMA_VERSION,
        "generatedAtMs": captured_at_ms,
        "targets": target_rows,
        "traceIds": trace_ids,
        "timeline": timeline,
        "evidence": evidence,
        "requirements": requirements,
        "environment": environment,
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
            requirement_ids = {
                str(item["requirementId"])
                for item in _mapping_sequence(
                    _mapping(_mapping(current.get("inspection")).get("requirements")).get("items")
                )
            }
            for assessment in _mapping_sequence(normalized_result.get("requirementAssessments")):
                requirement_id = str(assessment.get("requirementId") or "")
                if requirement_id not in requirement_ids:
                    raise ValueError(f"unknown requirementId: {requirement_id}")
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

    def authorize_repair(
        self,
        report_id: str,
        *,
        expected_revision: int,
        finding_id: str,
        source_scope: str,
        source_trace_id: str,
        failure_ref: str,
        repair_session_id: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        """Append a full-disk/all-tool auto-approved repair handoff."""

        identifier = _required_id(report_id, "reportId", 80)
        finding = _required_id(finding_id, "findingId", 160)
        scope = _required_id(source_scope, "sourceScope", 160)
        source_trace = _required_id(source_trace_id, "sourceTraceId", 160)
        failure = _required_id(failure_ref, "failureRef", 160)
        repair_session = _required_id(repair_session_id, "repairSessionId", 160)
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _load_report(conn, identifier)
            revision = int(current["revision"])
            if current.get("status") != "completed":
                raise ValueError("repair handoff requires a completed diagnostic report")
            existing_lifecycle = _mapping(current.get("repairLifecycle"))
            existing_authorization = _mapping(existing_lifecycle.get("authorization"))
            comparable = {
                "findingId": finding,
                "sourceScope": scope,
                "sourceTraceId": source_trace,
                "failureRef": failure,
                "repairSessionId": repair_session,
            }
            if existing_authorization and not all(
                existing_authorization.get(key) == value
                for key, value in comparable.items()
            ):
                raise ValueError("diagnostic report already has a different repair authorization")
            if not existing_authorization and revision != int(expected_revision):
                raise ValueError("report revision conflict")
            result = _mapping(current.get("result"))
            matching_finding = next(
                (item for item in _mapping_sequence(result.get("findings")) if item.get("findingId") == finding),
                None,
            )
            if matching_finding is None:
                raise ValueError("repair authorization finding is not in the diagnostic result")
            source_target = next(
                (
                    item
                    for item in _mapping_sequence(current.get("targets"))
                    if str(item.get("targetKey") or "") == scope
                ),
                None,
            )
            if source_target is None:
                raise ValueError("repair authorization scope is outside the report")
            target_trace_ids = _string_sequence(
                source_target.get("traceIds"),
                maximum=32,
                item_maximum=240,
            )
            if source_trace not in target_trace_ids:
                raise ValueError(
                    "repair authorization source Trace is outside the frozen target"
                )
            valid_failure_refs = {
                finding,
                *[
                    str(value)
                    for value in _string_sequence(
                        matching_finding.get("evidenceIds"),
                        maximum=128,
                        item_maximum=640,
                    )
                ],
            }
            if failure not in valid_failure_refs:
                raise ValueError("repair authorization failureRef is not bound to the finding")
            inspection_evidence = {
                str(item.get("evidenceId") or ""): item
                for item in _mapping_sequence(_mapping(current.get("inspection")).get("evidence"))
                if str(item.get("evidenceId") or "")
            }
            finding_evidence_ids = _string_sequence(
                matching_finding.get("evidenceIds"),
                maximum=128,
                item_maximum=640,
            )
            failed_evidence_ids = {
                evidence_id
                for evidence_id in finding_evidence_ids
                if str(inspection_evidence.get(evidence_id, {}).get("status") or "").lower()
                in _FAILED_STATUSES
            }
            if not failed_evidence_ids:
                raise ValueError(
                    "repair authorization requires recorded failed evidence"
                )
            if failure != finding and failure not in failed_evidence_ids:
                raise ValueError(
                    "repair authorization failureRef is not recorded failed evidence"
                )
            if existing_authorization:
                return current
            authorization_id = "repair-authorization:" + _sha256(
                f"{identifier}|{finding}|{scope}|{source_trace}|{failure}|{repair_session}"
            )[:32]
            lifecycle = {
                "authorization": {
                    "state": "authorized",
                    "authorizationKind": "repair_handoff",
                    "writeAuthority": "auto_approved_full_trust",
                    "authorizationId": authorization_id,
                    **comparable,
                    "authorizedAtMs": timestamp,
                },
                "verification": {
                    "state": "pending",
                    "repairReceiptId": "",
                    "repairTraceId": "",
                    "evalRunId": "",
                    "testStatus": "",
                    "sandboxStatus": "",
                    "sandboxedTestCount": 0,
                    "verifiedAtMs": 0,
                    "comparison": {
                        "status": "pending",
                        "reason": "已授权全信任自动批准修复交接；所有 Tool 操作无需逐项审批，等待修复 Trace 中已记录的修改与通过测试证据，以及 AI Judge 复检。",
                        "sourceStatus": "",
                        "repairStatus": "",
                        "sourceFingerprint": "",
                        "repairFingerprint": "",
                        "beforeMetrics": {},
                        "afterMetrics": {},
                        "deltas": {},
                    },
                },
            }
            next_payload = {
                **current,
                "revision": revision + 1,
                "repairLifecycle": lifecycle,
                "updatedAtMs": timestamp,
            }
            _persist_report_revision(conn, identifier, revision, next_payload, timestamp)
        return next_payload

    def verify_repair(
        self,
        report_id: str,
        *,
        expected_revision: int,
        receipt: Mapping[str, object],
        eval_run: Mapping[str, object],
        comparison: Mapping[str, object],
        verification_receipt: Mapping[str, object] | None = None,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        """Append receipt/Eval linkage; comparison still controls effect claims."""

        identifier = _required_id(report_id, "reportId", 80)
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        receipt_id = _required_id(receipt.get("repairReceiptId"), "repairReceiptId", 160)
        repair_trace = _required_id(receipt.get("repairTraceId"), "repairTraceId", 160)
        repair_session = _required_id(receipt.get("repairSessionId"), "repairSessionId", 160)
        eval_run_id = _required_id(eval_run.get("evalRunId"), "evalRunId", 160)
        replay_verification = dict(verification_receipt or {})
        verification_receipt_id = ""
        replay_case_id = ""
        decision = ""
        verification_created_at_ms = 0
        if replay_verification:
            verification_receipt_id = _required_id(
                replay_verification.get("verificationReceiptId"),
                "verificationReceiptId",
                160,
            )
            replay_case_id = _required_id(
                replay_verification.get("replayCaseId"),
                "replayCaseId",
                160,
            )
            decision = str(replay_verification.get("decision") or "")
            if decision not in {"kept", "rejected"}:
                raise ValueError("Trace verification decision is invalid")
            if (
                replay_verification.get("repairReceiptId") != receipt_id
                or replay_verification.get("sourceTraceId")
                != receipt.get("sourceTraceId")
                or replay_verification.get("repairTraceId") != repair_trace
            ):
                raise ValueError(
                    "Trace verification receipt does not match the repair receipt"
                )
            verification_created_at_ms = _bounded_integer(
                replay_verification.get("createdAtMs"),
                minimum=0,
                maximum=9_007_199_254_740_991,
                name="verification createdAtMs",
            )
        if receipt.get("testStatus") != "passed":
            raise ValueError("repair verification requires passed test evidence")
        sandbox_status = str(receipt.get("sandboxStatus") or "")
        sandboxed_test_count = int(receipt.get("sandboxedTestCount") or 0)
        if not (
            (sandbox_status == "passed" and sandboxed_test_count >= 1)
            or (sandbox_status == "not_required" and sandboxed_test_count == 0)
        ):
            raise ValueError(
                "repair verification requires authoritative completed test evidence"
            )
        if eval_run.get("status") != "completed" or eval_run.get("metricAuthority") != "ai_judge_estimate":
            raise ValueError("repair verification requires a completed bounded EvalRun")
        normalized_comparison = _normalize_repair_comparison(comparison)
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _load_report(conn, identifier)
            revision = int(current["revision"])
            lifecycle = _mapping(current.get("repairLifecycle"))
            authorization = _mapping(lifecycle.get("authorization"))
            if not authorization or authorization.get("state") != "authorized":
                raise ValueError("repair verification requires an authorized repair handoff")
            existing_verification = _mapping(lifecycle.get("verification"))
            if existing_verification.get("repairReceiptId"):
                if not (
                    existing_verification.get("repairReceiptId") == receipt_id
                    and existing_verification.get("evalRunId") == eval_run_id
                ):
                    raise ValueError(
                        "diagnostic report already has a different repair verification"
                    )
                existing_receipt_id = str(
                    existing_verification.get("verificationReceiptId") or ""
                )
                if not verification_receipt_id or (
                    existing_receipt_id == verification_receipt_id
                ):
                    return current
                if existing_receipt_id:
                    raise ValueError(
                        "diagnostic report already has a different Trace verification"
                    )
                if revision != int(expected_revision):
                    raise ValueError("report revision conflict")
            if revision != int(expected_revision):
                raise ValueError("report revision conflict")
            for receipt_key, authorization_key in (
                ("sourceScope", "sourceScope"),
                ("sourceTraceId", "sourceTraceId"),
                ("failureRef", "failureRef"),
                ("repairSessionId", "repairSessionId"),
            ):
                if receipt.get(receipt_key) != authorization.get(authorization_key):
                    raise ValueError("repair receipt does not match the report authorization")
            comparison_status = str(normalized_comparison.get("status") or "")
            verification_state = (
                "verified"
                if verification_receipt_id
                else "failed" if comparison_status == "failed" else "pending"
            )
            verification = {
                # A repair receipt, passing focused tests, and a one-sided
                # Judge run prove that the candidate was executed; they do not
                # prove that it improved the frozen source case. Keep this
                # lifecycle unresolved until the separate ReplayCase contract
                # produces a comparable kept/rejected VerificationReceipt.
                "state": verification_state,
                "repairReceiptId": receipt_id,
                "repairTraceId": repair_trace,
                "evalRunId": eval_run_id,
                "verificationReceiptId": verification_receipt_id,
                "replayCaseId": replay_case_id,
                "decision": decision,
                "testStatus": "passed",
                "sandboxStatus": sandbox_status,
                "sandboxedTestCount": sandboxed_test_count,
                "verifiedAtMs": (
                    verification_created_at_ms
                    if verification_receipt_id
                    else timestamp if verification_state == "failed" else 0
                ),
                "comparison": normalized_comparison,
            }
            next_payload = {
                **current,
                "revision": revision + 1,
                "repairLifecycle": {
                    "authorization": dict(authorization),
                    "verification": verification,
                },
                "updatedAtMs": timestamp,
            }
            _persist_report_revision(conn, identifier, revision, next_payload, timestamp)
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

    def for_diagnostic_session(
        self,
        diagnostic_session_id: str,
    ) -> dict[str, object] | None:
        session_id = _required_id(
            diagnostic_session_id,
            "diagnosticSessionId",
            240,
        )
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = conn.execute(
                "SELECT report_id FROM trace_diagnostic_reports WHERE diagnostic_session_id=?",
                (session_id,),
            ).fetchone()
            return (
                _load_report(conn, str(row["report_id"]))
                if row is not None
                else None
            )

    def owns_session(self, session_id: str) -> bool:
        """Return whether a Session is bound to a diagnostic or repair report."""

        identifier = _required_id(session_id, "sessionId", 240)
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM trace_diagnostic_reports AS report
                JOIN trace_diagnostic_report_revisions AS revision
                  ON revision.report_id = report.report_id
                 AND revision.revision = report.current_revision
                WHERE report.diagnostic_session_id = ?
                   OR (
                        json_valid(revision.payload_json)
                        AND json_extract(
                            revision.payload_json,
                            '$.repairLifecycle.authorization.repairSessionId'
                        ) = ?
                   )
                LIMIT 1
                """,
                (identifier, identifier),
            ).fetchone()
            return row is not None

    def list(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, object]:
        safe_limit = _bounded_integer(limit, minimum=1, maximum=100, name="limit")
        cursor_value = str(cursor or "").strip()
        cursor_position: tuple[int, str] | None = None
        if cursor_value:
            match = _REPORT_CURSOR_RE.fullmatch(cursor_value)
            if match is None:
                raise ValueError("Trace diagnostic report cursor is invalid")
            cursor_position = (
                int(match.group(1)),
                f"trace-report:{match.group(2)}",
            )
        self.initialize()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM trace_diagnostic_reports").fetchone()[0])
            if cursor_position is None:
                rows = conn.execute(
                    "SELECT report_id,updated_at_ms FROM trace_diagnostic_reports "
                    "ORDER BY updated_at_ms DESC,report_id DESC LIMIT ?",
                    (safe_limit + 1,),
                ).fetchall()
            else:
                updated_at_ms, report_id = cursor_position
                rows = conn.execute(
                    "SELECT report_id,updated_at_ms FROM trace_diagnostic_reports "
                    "WHERE updated_at_ms < ? OR (updated_at_ms = ? AND report_id < ?) "
                    "ORDER BY updated_at_ms DESC,report_id DESC LIMIT ?",
                    (updated_at_ms, updated_at_ms, report_id, safe_limit + 1),
                ).fetchall()
            has_more = len(rows) > safe_limit
            page_rows = rows[:safe_limit]
            items = [
                _report_summary(_load_report(conn, str(row["report_id"])))
                for row in page_rows
            ]
            next_cursor = None
            if has_more and page_rows:
                tail = page_rows[-1]
                next_cursor = (
                    f"{int(tail['updated_at_ms'])}."
                    f"{str(tail['report_id']).removeprefix('trace-report:')}"
                )
        result = {
            "schemaVersion": "rag-ime.trace-diagnostic-report-list.v1",
            "total": total,
            "truncated": has_more,
            "nextCursor": next_cursor,
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


def _requirements_from_timeline(
    timeline: Sequence[Mapping[str, object]],
    valid_evidence_ids: set[str],
) -> dict[str, object]:
    """Freeze user-authored source rows without asking the model to invent them."""

    candidates: list[dict[str, object]] = []
    for item in timeline:
        if str(item.get("kind") or "") not in {"user", "user_message"}:
            continue
        evidence_id = str(item.get("evidenceId") or "")
        statement = _public_text(item.get("summary"), 2000)
        target_key = _bounded_id(item.get("targetKey"), 500)
        source_ref = _public_text(item.get("sourceRef"), 640)
        if not evidence_id or evidence_id not in valid_evidence_ids or not statement or not target_key or not source_ref:
            continue
        candidates.append(
            {
                "requirementId": evidence_id,
                "statement": statement,
                "targetKey": target_key,
                "sourceRef": source_ref,
                "evidenceIds": [evidence_id],
            }
        )
    candidates = _dedupe(candidates, "requirementId")
    truncated = len(candidates) > 100
    items = candidates[-100:]
    return {
        "source": "user_input" if items else "unknown",
        "items": items,
        "truncated": truncated,
    }


def _environment_snapshot(
    *,
    captured_at_ms: int,
    targets: Sequence[Mapping[str, object]],
    source_hashes: Mapping[str, str],
    environment_inputs: Mapping[str, Mapping[str, object]],
    traces: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Project reproducibility facts while excluding paths and credentials."""

    rows: list[dict[str, object]] = []
    limitations = {
        "未冻结 Provider 服务端构建、系统镜像与依赖锁文件；不能据此声称字节级复现。"
    }
    for target in targets:
        target_key = str(target.get("targetKey") or "")
        config = _mapping(environment_inputs.get(target_key))
        runtime = _mapping(config.get("runtimeBinding"))
        fingerprints: list[str] = []
        statuses: list[str] = []
        for trace_id in _string_sequence(target.get("traceIds"), maximum=32, item_maximum=240):
            trace = traces.get(trace_id)
            if trace is None:
                continue
            fingerprint = str(_mapping(trace.get("input")).get("fingerprint") or "")
            if _TRACE_FINGERPRINT_RE.fullmatch(fingerprint) and fingerprint not in fingerprints:
                fingerprints.append(fingerprint)
            status = _bounded_id(trace.get("status"), 80)
            if status:
                statuses.append(status)
        if not config:
            limitations.add(f"{target_key} 缺少 Session/Room 配置快照。")
        if not fingerprints:
            limitations.add(f"{target_key} 缺少 Trace input fingerprint。")
        if not source_hashes.get(target_key):
            limitations.add(f"{target_key} 缺少可冻结的公开源快照。")
        policy_revision = config.get("policyRevision")
        runtime_generation = runtime.get("generation")
        rows.append(
            {
                "targetKey": target_key,
                "sourceSha256": source_hashes.get(target_key, ""),
                "modelProfile": _public_text(config.get("modelProfile"), 160),
                "toolProfileVersion": _public_text(config.get("toolProfileVersion"), 160),
                "executionMode": _public_text(config.get("executionMode"), 80),
                "policyRevision": (
                    int(policy_revision)
                    if isinstance(policy_revision, int) and not isinstance(policy_revision, bool) and policy_revision >= 0
                    else None
                ),
                "workspaceScopeSha256": (
                    str(config.get("workspaceScopeSha256") or "")
                    if re.fullmatch(r"[a-f0-9]{64}", str(config.get("workspaceScopeSha256") or ""))
                    else ""
                ),
                "shellPolicyVersion": _public_text(config.get("shellPolicyVersion"), 160),
                "runtimeKind": _public_text(runtime.get("runtimeKind"), 80),
                "runtimeGeneration": (
                    int(runtime_generation)
                    if isinstance(runtime_generation, int) and not isinstance(runtime_generation, bool) and runtime_generation >= 0
                    else None
                ),
                "traceInputFingerprints": fingerprints,
                "traceStatuses": statuses,
            }
        )
    return {
        "capturedAtMs": captured_at_ms,
        "rubricVersion": TRACE_DIAGNOSTIC_RUBRIC_VERSION,
        "targets": rows,
        "limitations": sorted(limitations),
    }


def _scorecard(
    *,
    observation_events: Sequence[Mapping[str, object]],
    traces: Sequence[Mapping[str, object]],
    eval_runs: Sequence[Mapping[str, object]],
    rooms: Sequence[Mapping[str, object]],
    targets: Sequence[Mapping[str, object]],
    target_count: int,
    valid_evidence_ids: set[str],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    dimensions = {
        identifier: _dimension(identifier, title)
        for identifier, title in _DIMENSIONS
    }
    standalone_memory_maintenance = any(
        str(target.get("kind") or "") == "run"
        and "memory-maintenance" in str(target.get("id") or "").lower()
        for target in targets
    )
    collaboration_observed = bool(rooms) or any(
        any(
            str(event.get(key) or "").strip()
            for key in (
                "roomId",
                "workItemId",
                "dispatchId",
                "participantId",
            )
        )
        for event in observation_events
    )
    if standalone_memory_maintenance and not collaboration_observed:
        dimensions["room_collaboration"] = _not_applicable_dimension(
            dimensions["room_collaboration"],
            note="独立 Memory 维护 run 没有 Room 协作边界。",
        )
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
            evidence_by_id=evidence_by_id,
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
                evidence_by_id=evidence_by_id,
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
            evidence_by_id=evidence_by_id,
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
            evidence_by_id=evidence_by_id,
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
            evidence_by_id=evidence_by_id,
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
            evidence_by_id=evidence_by_id,
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
            evidence_by_id=evidence_by_id,
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


def _not_applicable_dimension(
    base: Mapping[str, object],
    *,
    note: str,
) -> dict[str, object]:
    return {
        **base,
        "applicability": "not_applicable",
        "note": note,
    }


def _measured_dimension(
    base: Mapping[str, object],
    *,
    score: float | None,
    metrics: Sequence[Mapping[str, object]],
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, object]],
    note: str,
    applicability: str = "measured",
    authority: str = "deterministic",
) -> dict[str, object]:
    bounded_evidence_ids, evidence_gap = _bounded_dimension_evidence_ids(
        evidence_ids,
        evidence_by_id=evidence_by_id,
    )
    note_budget = 800 - len(evidence_gap) - (1 if note and evidence_gap else 0)
    bounded_note = f"{note[:max(0, note_budget)]} {evidence_gap}".strip()
    return {
        **base,
        "applicability": applicability,
        "authority": authority,
        "score": None if score is None else max(0.0, min(100.0, float(score))),
        "metrics": [dict(item) for item in metrics],
        "evidenceIds": bounded_evidence_ids,
        "note": bounded_note,
    }


def _bounded_dimension_evidence_ids(
    evidence_ids: Sequence[str],
    *,
    evidence_by_id: Mapping[str, Mapping[str, object]],
    maximum: int = 256,
) -> tuple[list[str], str]:
    unique = list(dict.fromkeys(str(value) for value in evidence_ids if str(value)))
    if len(unique) <= maximum:
        return unique, ""

    def priority(evidence_id: str) -> tuple[int, int, str]:
        evidence = evidence_by_id.get(evidence_id, {})
        status = str(evidence.get("status") or "").lower()
        summary = str(evidence.get("summary") or "")
        is_failure = status in _FAILED_STATUSES or _EVIDENCE_FAILURE_RE.search(
            f"{status} {summary}"
        ) is not None
        is_terminal = status in _TERMINAL_STATUSES
        return (
            2 if is_failure else (1 if is_terminal else 0),
            _nonnegative_int(evidence.get("createdAtMs")),
            evidence_id,
        )

    selected = sorted(
        unique,
        key=lambda evidence_id: (
            -priority(evidence_id)[0],
            -priority(evidence_id)[1],
            priority(evidence_id)[2],
        ),
    )[:maximum]
    gap = (
        "证据引用已按失败/超时、终态、最新时间优先的确定性顺序"
        f"从 {len(unique)} 项截断至 {maximum} 项；完整候选仍保留在 inspection.evidence。"
    )
    return selected, gap


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


def _comparison(
    traces: Sequence[Mapping[str, object]],
    target_count: int,
) -> dict[str, object]:
    if target_count < 2:
        return {
            "eligible": False,
            "status": "incomparable",
            "reason": "只有一个诊断对象，不能形成对照。",
        }
    fingerprints = {
        str(_mapping(trace.get("input")).get("fingerprint") or "")
        for trace in traces
    }
    if not traces or "" in fingerprints:
        return {
            "eligible": False,
            "status": "unknown",
            "reason": "缺少完整 source fingerprint，禁止声称差值或节省。",
        }
    if len(fingerprints) != 1:
        return {
            "eligible": False,
            "status": "incomparable",
            "reason": "输入 fingerprint 不同，只能分别展示，不能推导修复或效率差值。",
        }
    return {
        "eligible": True,
        "status": "conditionally_comparable",
        "reason": "输入 fingerprint 相同，但 fixture、模型、配置与工具版本尚未全部冻结。",
    }


def _validate_result(
    result: Mapping[str, object],
    *,
    require_governed: bool = True,
) -> dict[str, object]:
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
    raw_requirement_assessments = normalized.get("requirementAssessments", [])
    if not isinstance(raw_requirement_assessments, list):
        raise ValueError("requirementAssessments must be an array")
    if any(not isinstance(item, Mapping) for item in raw_requirement_assessments):
        raise ValueError("requirementAssessments must contain only objects")
    requirement_assessments: list[dict[str, object]] = []
    seen_requirements: set[str] = set()
    for assessment in raw_requirement_assessments[:100]:
        requirement_id = _required_id(assessment.get("requirementId"), "requirementId", 640)
        if requirement_id in seen_requirements:
            raise ValueError(f"duplicate requirement assessment: {requirement_id}")
        seen_requirements.add(requirement_id)
        status = str(assessment.get("status") or "")
        if status not in {"satisfied", "partial", "unsatisfied", "unverified"}:
            raise ValueError("requirement assessment status is invalid")
        if assessment.get("authority") != "ai_judge_estimate":
            raise ValueError("requirement assessment authority must be ai_judge_estimate")
        requirement_assessments.append(
            {
                "requirementId": requirement_id,
                "status": status,
                "owner": _public_text(assessment.get("owner"), 240),
                "authority": "ai_judge_estimate",
                "evidenceIds": _string_sequence(assessment.get("evidenceIds"), maximum=128, item_maximum=640),
                "note": _public_text(assessment.get("note"), 1600),
            }
        )
    raw_causal_links = normalized.get("causalLinks", [])
    if not isinstance(raw_causal_links, list):
        raise ValueError("causalLinks must be an array")
    if any(not isinstance(item, Mapping) for item in raw_causal_links):
        raise ValueError("causalLinks must contain only objects")
    causal_links: list[dict[str, object]] = []
    seen_links: set[str] = set()
    valid_relations = {"triggered", "delegated", "responded_to", "returned", "verified", "caused", "recovered"}
    for link in raw_causal_links[:120]:
        link_id = _required_id(link.get("linkId"), "linkId", 160)
        if link_id in seen_links:
            raise ValueError(f"duplicate causal link: {link_id}")
        seen_links.add(link_id)
        relation = str(link.get("relation") or "")
        confidence = str(link.get("confidence") or "")
        if relation not in valid_relations:
            raise ValueError("causal relation is invalid")
        if confidence not in {"high", "medium", "low", "unknown"}:
            raise ValueError("causal confidence is invalid")
        if link.get("authority") != "ai_judge_estimate":
            raise ValueError("causal link authority must be ai_judge_estimate")
        causal_links.append(
            {
                "linkId": link_id,
                "fromEvidenceId": _required_id(link.get("fromEvidenceId"), "fromEvidenceId", 640),
                "toEvidenceId": _required_id(link.get("toEvidenceId"), "toEvidenceId", 640),
                "relation": relation,
                "authority": "ai_judge_estimate",
                "confidence": confidence,
                "explanation": _public_text(link.get("explanation"), 1600),
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
    presentation = None
    if "presentation" not in normalized:
        if require_governed:
            raise ValueError("result presentation is required")
    else:
        presentation = _normalize_result_presentation(
            normalized.get("presentation"),
            finding_ids={str(item["findingId"]) for item in findings},
            require_failure_attribution=require_governed,
        )
    payload: dict[str, object] = {
        "schemaVersion": TRACE_DIAGNOSTIC_RESULT_SCHEMA_VERSION,
        "summary": normalized["summary"],
        "hardGates": hard_gates,
        "judgeScores": judge_scores,
        "findings": findings,
    }
    # These v1 additions remain optional so older results can still be
    # normalized on read. The governed presentation above is required for
    # every new extraction and completion. Empty arrays are preserved when
    # the diagnosing Agent explicitly emits them.
    if "requirementAssessments" in normalized:
        payload["requirementAssessments"] = requirement_assessments
    if "causalLinks" in normalized:
        payload["causalLinks"] = causal_links
    if presentation is not None:
        payload["presentation"] = presentation
    validate_contract(payload, "trace-diagnostic-result.v1.json")
    return payload


def _normalize_result_presentation(
    value: object,
    *,
    finding_ids: set[str],
    require_failure_attribution: bool = False,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("presentation must be an object")
    required_keys = {
        "headline",
        "impact",
        "primaryFindingId",
        "knownFacts",
        "evidenceGaps",
        "causalNodes",
        "expectedStageCount",
        "recordedStageReceiptEvidenceIds",
    }
    allowed_keys = required_keys | {"failureAttribution"}
    unknown_keys = set(value) - allowed_keys
    missing_keys = required_keys - set(value)
    if unknown_keys:
        raise ValueError(f"presentation has unknown fields: {', '.join(sorted(unknown_keys))}")
    if missing_keys:
        raise ValueError(f"presentation is missing fields: {', '.join(sorted(missing_keys))}")
    if require_failure_attribution and "failureAttribution" not in value:
        raise ValueError("presentation.failureAttribution is required")

    primary_finding_id = _strict_public_text(
        value.get("primaryFindingId"),
        "presentation.primaryFindingId",
        160,
        allow_empty=True,
    )
    if primary_finding_id and primary_finding_id not in finding_ids:
        raise ValueError(f"unknown primaryFindingId: {primary_finding_id}")

    known_facts = _strict_mapping_array(value.get("knownFacts"), "presentation.knownFacts", 12)
    normalized_known_facts: list[dict[str, object]] = []
    for index, fact in enumerate(known_facts):
        _require_exact_keys(
            fact,
            {"fact", "evidenceIds"},
            f"presentation.knownFacts[{index}]",
        )
        evidence_ids = _strict_evidence_ids(
            fact.get("evidenceIds"),
            f"presentation.knownFacts[{index}].evidenceIds",
            maximum=32,
        )
        if not evidence_ids:
            raise ValueError("known presentation facts require frozen evidence")
        normalized_known_facts.append(
            {
                "fact": _strict_public_text(
                    fact.get("fact"),
                    f"presentation.knownFacts[{index}].fact",
                    800,
                ),
                "evidenceIds": evidence_ids,
            }
        )

    evidence_gaps = _strict_mapping_array(value.get("evidenceGaps"), "presentation.evidenceGaps", 12)
    normalized_evidence_gaps: list[dict[str, object]] = []
    for index, gap in enumerate(evidence_gaps):
        prefix = f"presentation.evidenceGaps[{index}]"
        _require_exact_keys(gap, {"gap", "consequence", "howToObtain"}, prefix)
        normalized_evidence_gaps.append(
            {
                "gap": _strict_public_text(gap.get("gap"), f"{prefix}.gap", 800),
                "consequence": _strict_public_text(
                    gap.get("consequence"), f"{prefix}.consequence", 1000
                ),
                "howToObtain": _strict_public_text(
                    gap.get("howToObtain"), f"{prefix}.howToObtain", 1000
                ),
            }
        )

    causal_nodes = _strict_mapping_array(value.get("causalNodes"), "presentation.causalNodes", 16)
    normalized_causal_nodes: list[dict[str, object]] = []
    for index, node in enumerate(causal_nodes):
        prefix = f"presentation.causalNodes[{index}]"
        _require_exact_keys(node, {"label", "detail", "status", "evidenceIds"}, prefix)
        status = str(node.get("status") or "")
        if status not in {"confirmed", "unverified"}:
            raise ValueError(f"{prefix}.status is invalid")
        evidence_ids = _strict_evidence_ids(
            node.get("evidenceIds"), f"{prefix}.evidenceIds", maximum=32
        )
        if not evidence_ids:
            raise ValueError("presentation causal nodes require frozen evidence")
        normalized_causal_nodes.append(
            {
                "label": _strict_public_text(node.get("label"), f"{prefix}.label", 240),
                "detail": _strict_public_text(node.get("detail"), f"{prefix}.detail", 1200),
                "status": status,
                "evidenceIds": evidence_ids,
            }
        )

    expected_stage_count = value.get("expectedStageCount")
    if (
        isinstance(expected_stage_count, bool)
        or not isinstance(expected_stage_count, int)
        or not 0 <= expected_stage_count <= 32
    ):
        raise ValueError("presentation.expectedStageCount must be an integer from 0 to 32")
    failure_attribution = None
    if "failureAttribution" in value:
        failure_attribution = _normalize_failure_attribution(
            value.get("failureAttribution"),
            name="presentation.failureAttribution",
        )

    normalized = {
        "headline": _strict_public_text(value.get("headline"), "presentation.headline", 320),
        "impact": _strict_public_text(value.get("impact"), "presentation.impact", 1000),
        "primaryFindingId": primary_finding_id,
        "knownFacts": normalized_known_facts,
        "evidenceGaps": normalized_evidence_gaps,
        "causalNodes": normalized_causal_nodes,
        "expectedStageCount": expected_stage_count,
        "recordedStageReceiptEvidenceIds": _strict_evidence_ids(
            value.get("recordedStageReceiptEvidenceIds"),
            "presentation.recordedStageReceiptEvidenceIds",
            maximum=32,
        ),
    }
    if failure_attribution is not None:
        normalized["failureAttribution"] = failure_attribution
    return normalized


def _normalize_failure_attribution(
    value: object,
    *,
    name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    required_keys = {"primaryLayer", "summary", "layers"}
    _require_exact_keys(value, required_keys, name)

    primary_layer = value.get("primaryLayer")
    if not isinstance(primary_layer, str) or primary_layer not in {
        *_FAILURE_ATTRIBUTION_LAYERS,
        "unknown",
    }:
        raise ValueError(f"{name}.primaryLayer is invalid")
    summary = _strict_public_text(value.get("summary"), f"{name}.summary", 1600)
    layers = value.get("layers")
    if not isinstance(layers, list):
        raise ValueError(f"{name}.layers must be an array")
    if len(layers) != len(_FAILURE_ATTRIBUTION_LAYERS):
        raise ValueError(
            f"{name}.layers must contain exactly {len(_FAILURE_ATTRIBUTION_LAYERS)} items"
        )

    normalized_layers: list[dict[str, object]] = []
    primary_layers: list[str] = []
    for index, expected_layer in enumerate(_FAILURE_ATTRIBUTION_LAYERS):
        prefix = f"{name}.layers[{index}]"
        layer = layers[index]
        if not isinstance(layer, Mapping):
            raise ValueError(f"{prefix} must be an object")
        _require_exact_keys(layer, {"layer", "verdict", "explanation", "evidenceIds"}, prefix)
        if layer.get("layer") != expected_layer:
            raise ValueError(f"{prefix}.layer must be {expected_layer}")
        verdict = layer.get("verdict")
        if not isinstance(verdict, str) or verdict not in _FAILURE_ATTRIBUTION_VERDICTS:
            raise ValueError(f"{prefix}.verdict is invalid")
        evidence_ids = _strict_evidence_ids(
            layer.get("evidenceIds"),
            f"{prefix}.evidenceIds",
            maximum=32,
        )
        if verdict in {"primary", "contributing", "healthy"} and not evidence_ids:
            raise ValueError(f"{prefix}.evidenceIds are required for {verdict} attribution")
        if verdict == "primary":
            primary_layers.append(expected_layer)
        normalized_layers.append(
            {
                "layer": expected_layer,
                "verdict": verdict,
                "explanation": _strict_public_text(
                    layer.get("explanation"),
                    f"{prefix}.explanation",
                    1200,
                ),
                "evidenceIds": evidence_ids,
            }
        )

    if len(primary_layers) > 1:
        raise ValueError(f"{name}.layers may contain at most one primary verdict")
    if primary_layers:
        if primary_layer != primary_layers[0]:
            raise ValueError(
                f"{name}.primaryLayer must match primary layer {primary_layers[0]}"
            )
    elif primary_layer != "unknown":
        raise ValueError(f"{name}.primaryLayer must be unknown when no layer is primary")

    return {
        "primaryLayer": primary_layer,
        "summary": summary,
        "layers": normalized_layers,
    }


def _result_evidence_ids(result: Mapping[str, object]) -> list[str]:
    values: list[str] = []
    for collection in ("hardGates", "judgeScores", "requirementAssessments", "findings"):
        for item in _mapping_sequence(result.get(collection)):
            for evidence_id in _string_sequence(item.get("evidenceIds"), maximum=128, item_maximum=640):
                if evidence_id not in values:
                    values.append(evidence_id)
    for link in _mapping_sequence(result.get("causalLinks")):
        for key in ("fromEvidenceId", "toEvidenceId"):
            evidence_id = str(link.get(key) or "")
            if evidence_id and evidence_id not in values:
                values.append(evidence_id)
    presentation = _mapping(result.get("presentation"))
    for fact in _mapping_sequence(presentation.get("knownFacts")):
        for evidence_id in _string_sequence(fact.get("evidenceIds"), maximum=32, item_maximum=640):
            if evidence_id not in values:
                values.append(evidence_id)
    for node in _mapping_sequence(presentation.get("causalNodes")):
        for evidence_id in _string_sequence(node.get("evidenceIds"), maximum=32, item_maximum=640):
            if evidence_id not in values:
                values.append(evidence_id)
    for evidence_id in _string_sequence(
        presentation.get("recordedStageReceiptEvidenceIds"), maximum=32, item_maximum=640
    ):
        if evidence_id not in values:
            values.append(evidence_id)
    for layer in _mapping_sequence(_mapping(presentation.get("failureAttribution")).get("layers")):
        for evidence_id in _string_sequence(layer.get("evidenceIds"), maximum=32, item_maximum=640):
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
    if isinstance(payload.get("result"), Mapping):
        # Persisted rows may predate the governed presentation contract. Keep
        # that compatibility boundary confined to reads; every new extraction
        # and completion still uses the strict default.
        payload["result"] = _validate_result(
            payload["result"],
            require_governed=False,
        )
    validate_contract(payload, "trace-diagnostic-report.v1.json")
    return payload


def _persist_report_revision(
    conn: sqlite3.Connection,
    report_id: str,
    previous_revision: int,
    payload: Mapping[str, object],
    timestamp: int,
) -> None:
    next_payload = dict(payload)
    validate_contract(next_payload, "trace-diagnostic-report.v1.json")
    encoded = _canonical_json(next_payload)
    next_revision = int(next_payload["revision"])
    conn.execute(
        "INSERT INTO trace_diagnostic_report_revisions(report_id,revision,payload_hash,payload_json,created_at_ms) VALUES(?,?,?,?,?)",
        (report_id, next_revision, _sha256(encoded), encoded, timestamp),
    )
    conn.execute(
        "UPDATE trace_diagnostic_reports SET current_revision=?,status=?,updated_at_ms=? WHERE report_id=? AND current_revision=?",
        (next_revision, str(next_payload["status"]), timestamp, report_id, previous_revision),
    )
    if conn.execute("SELECT changes()").fetchone()[0] != 1:
        raise ValueError("report revision conflict")


def _normalize_repair_comparison(value: Mapping[str, object]) -> dict[str, object]:
    status = str(value.get("status") or "")
    if status not in {"pending", "incomparable", "failed", "unknown"}:
        raise ValueError("repair comparison status is invalid")
    source_fingerprint = str(value.get("sourceFingerprint") or "")
    repair_fingerprint = str(value.get("repairFingerprint") or "")
    for fingerprint in (source_fingerprint, repair_fingerprint):
        if fingerprint and _TRACE_FINGERPRINT_RE.fullmatch(fingerprint) is None:
            raise ValueError("repair comparison fingerprint is invalid")

    def numeric_map(raw: object, name: str) -> dict[str, float]:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{name} must be an object")
        result: dict[str, float] = {}
        for key, metric in list(raw.items())[:64]:
            identifier = _required_id(key, f"{name} metric", 160)
            if isinstance(metric, bool) or not isinstance(metric, (int, float)) or not math.isfinite(float(metric)):
                raise ValueError(f"{name} metric must be finite")
            result[identifier] = float(metric)
        return result

    before_metrics = numeric_map(value.get("beforeMetrics", {}), "beforeMetrics")
    after_metrics = numeric_map(value.get("afterMetrics", {}), "afterMetrics")
    deltas = numeric_map(value.get("deltas", {}), "deltas")
    if deltas:
        raise ValueError("non-comparable repair results cannot publish deltas")
    return {
        "status": status,
        "reason": _public_text(value.get("reason"), 1000),
        "sourceStatus": _public_text(value.get("sourceStatus"), 80),
        "repairStatus": _public_text(value.get("repairStatus"), 80),
        "sourceFingerprint": source_fingerprint,
        "repairFingerprint": repair_fingerprint,
        "beforeMetrics": before_metrics,
        "afterMetrics": after_metrics,
        "deltas": deltas,
    }


def _report_summary(report: Mapping[str, object]) -> dict[str, object]:
    targets = _mapping_sequence(report.get("targets"))
    lifecycle = _mapping(report.get("repairLifecycle"))
    authorization = _mapping(lifecycle.get("authorization"))
    verification = _mapping(lifecycle.get("verification"))
    repair_state = (
        "verified"
        if verification.get("state") == "verified"
        else "failed"
        if verification.get("state") == "failed"
        else "authorized"
        if authorization.get("state") == "authorized"
        else "not_recorded"
    )
    return {
        "reportId": str(report.get("reportId") or ""),
        "revision": int(report.get("revision") or 0),
        "status": str(report.get("status") or ""),
        "title": str(report.get("title") or ""),
        "diagnosticSessionId": str(report.get("diagnosticSessionId") or ""),
        "targetKeys": [str(item.get("targetKey") or "") for item in targets],
        "targets": targets,
        "traceIds": list(report.get("traceIds") or []),
        "repairState": repair_state,
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


def _strict_public_text(
    value: object,
    name: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = " ".join(value.split())
    if not allow_empty and not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    text = _PATH_RE.sub("[path redacted]", text)
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)


def _strict_mapping_array(value: object, name: str, maximum: int) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} items")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain only objects")
    return list(value)


def _strict_evidence_ids(value: object, name: str, *, maximum: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} items")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{name} must contain only strings")
        normalized = item.strip()
        if not normalized or len(normalized) > 640:
            raise ValueError(f"{name} contains an invalid evidenceId")
        if normalized in result:
            raise ValueError(f"{name} contains a duplicate evidenceId")
        result.append(normalized)
    return result


def _require_exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    unknown_keys = set(value) - expected
    missing_keys = expected - set(value)
    if unknown_keys:
        raise ValueError(f"{name} has unknown fields: {', '.join(sorted(unknown_keys))}")
    if missing_keys:
        raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing_keys))}")


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
