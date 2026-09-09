"""Goal-bound proposals and host-recorded intervention comparisons.

The public mutation accepts identities, never scores or success receipts. A
registered Lab adapter must persist its frozen input, actual loaded versions,
Trace and ground-truth Eval before a comparison can claim an effect. Existing
adapters lacking that evidence remain usable but yield needs_validation. The
strict failure-only TraceReplayVerificationStore is deliberately unchanged.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .contracts.json_schema import load_contract, validate_contract
from .db import apply_database_migrations, sqlite_connection
from .eval_run_store import EvalRunStore
from .trace_store import TraceStore

FOCUS_AREAS = ("tool", "skill", "prompt", "workflow", "model")
_ACTIONS = {"run_candidate", "install", "replace", "apply", "keep_original", "rollback"}
_APPLY_ACTIONS = {"install", "replace", "apply"}
_SCHEMA = "trace-optimization.v1.json"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 640:
        raise ValueError(f"{name} must be a nonempty identifier")
    return value.strip()


def _validate(value: object, definition: str) -> None:
    schema = load_contract(_SCHEMA)
    validate_contract(value, {"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"})


def normalize_trace_optimization_intent(intent: Mapping | None = None) -> dict:
    """Defaults apply to new requests only; legacy saved reports stay absent."""
    if intent is not None and not isinstance(intent, Mapping):
        raise ValueError("intent must be an object")
    result = {"mode": "improve", "scopeMode": "all", "focusAreas": list(FOCUS_AREAS), "objective": ""} if intent is None else dict(intent)
    _validate(result, "optimizationIntent")
    if result["scopeMode"] == "all" and set(result["focusAreas"]) != set(FOCUS_AREAS):
        raise ValueError("all focus must contain every supported area")
    result["focusAreas"] = [area for area in FOCUS_AREAS if area in result["focusAreas"]]
    result["objective"] = result["objective"].strip()
    return result


class _EvidenceGap(ValueError):
    pass


def _record(value: object, name: str) -> dict:
    if not isinstance(value, Mapping):
        raise _EvidenceGap(f"{name} is unavailable")
    return dict(value)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _EvidenceGap(f"{name} is unavailable")
    return float(value)


def _decode_record(raw: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("contentSha256") != _hash({key: item for key, item in value.items() if key != "contentSha256"}):
        raise ValueError("Persisted optimization record identity is invalid")
    return value


def _application_state(applications: list[dict]) -> tuple[str, dict]:
    state, applied = "not_applied", {}
    for item in applications:
        if item["status"] == "applied":
            state, applied = "applied", item
        elif item["status"] == "rolled_back":
            state, applied = "not_applied", {}
        elif item["status"] == "interrupted":
            state = "uncertain"
        # A failed operation does not undo a previous installation.
    return state, applied


def _pending_applications(conn: sqlite3.Connection, report_id: str, result: Mapping) -> list[dict]:
    """Expose the owner's unsettled reservations without fabricating completion.

    A lost settlement remains an `applying` receipt even if the external side
    effect happened. This is a bounded read model, not polling or recovery.
    Only reservations bound to this report's exact candidate and comparison
    are eligible; private owner details and filesystem paths stay omitted.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_optimization_application_receipts'").fetchone():
        return []
    candidates = {item["candidateId"]: item for item in result["candidates"]}
    comparisons = {item["comparisonId"]: item for item in result["comparisons"]}
    rows = conn.execute("""SELECT receipt_ref,status,payload_json,created_at_ms,request_hash
        FROM trace_optimization_application_receipts
        WHERE json_extract(payload_json,'$.reportId')=? AND status IN ('applying','interrupted')
        ORDER BY created_at_ms,receipt_ref LIMIT 512""", (report_id,)).fetchall()
    items = []
    for row in rows:
        receipt = json.loads(row[2])
        candidate = candidates.get(receipt.get("candidateId"))
        if candidate is None:
            continue
        comparison = comparisons.get(receipt.get("comparisonId"))
        request = {key: value for key, value in receipt.items()
            if key not in {"receiptRef", "status", "createdAtMs", "completedAtMs", "details"}}
        if (receipt.get("receiptRef") != row[0] or receipt.get("status") != row[1]
            or receipt.get("createdAtMs") != row[3] or _hash(request) != row[4]
            or receipt.get("action") not in {"install", "replace", "apply", "rollback"}
            or receipt.get("targetKind") != candidate["targetKind"] or receipt.get("targetRef") != candidate["targetRef"]
            or receipt.get("versionRef") != candidate["parentVersionRef" if receipt.get("action") == "rollback" else "candidateVersionRef"]
            or comparison is None or comparison["candidateId"] != candidate["candidateId"]):
            raise ValueError("Pending application receipt differs from its registered candidate or comparison")
        items.append({key: receipt[key] for key in ("candidateId", "comparisonId", "receiptRef", "versionRef", "action", "status", "createdAtMs")})
    return items


def read_trace_optimization(conn: sqlite3.Connection, report_id: str) -> dict:
    """Join immutable child records; does not change a diagnosis revision."""
    result = {"schemaVersion": "rag-ime.trace-optimization.v1", "candidates": [], "comparisons": [], "applications": []}
    keys = {"candidate": "candidates", "comparison": "comparisons", "application": "applications"}
    rows = conn.execute("SELECT record_kind,payload_json FROM trace_optimization_records WHERE report_id=? ORDER BY rowid", (report_id,)).fetchall()
    for row in rows:
        result[keys[row[0]]].append(_decode_record(row[1]))
    owner_pending = _pending_applications(conn, report_id, result)
    pending_candidate_ids = {item["candidateId"] for item in owner_pending}
    bound_receipts = {item["receiptRef"] for item in result["applications"]}
    result["pendingApplications"] = [item for item in owner_pending if item["receiptRef"] not in bound_receipts]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trace_optimization_run_pairs'").fetchone():
        executions = conn.execute(
            "SELECT pair.request_id,pair.candidate_id,pair.baseline_job_id,pair.candidate_job_id,"
            "baseline.state,candidate.state,baseline.progress,candidate.progress,pair.comparison_id,pair.created_at_ms "
            "FROM trace_optimization_run_pairs pair "
            "LEFT JOIN agent_lab_trials baseline ON baseline.job_id=pair.baseline_job_id "
            "LEFT JOIN agent_lab_trials candidate ON candidate.job_id=pair.candidate_job_id "
            "WHERE pair.report_id=? ORDER BY pair.created_at_ms,pair.request_id",
            (report_id,),
        ).fetchall()
        result["executions"] = [{"requestId": row[0], "candidateId": row[1], "baselineJobId": row[2], "candidateJobId": row[3], "baselineState": row[4] or "unavailable", "candidateState": row[5] or "unavailable", "baselineSummary": row[6] or "", "candidateSummary": row[7] or "", "comparisonId": row[8], "createdAtMs": row[9]} for row in executions]
    report_row = conn.execute("SELECT r.payload_json FROM trace_diagnostic_report_revisions r JOIN trace_diagnostic_reports h ON h.report_id=r.report_id AND h.current_revision=r.revision WHERE h.report_id=?", (report_id,)).fetchone()
    report = json.loads(report_row[0]) if report_row else {}
    findings = (report.get("result") or {}).get("findings", [])
    for candidate in result["candidates"]:
        candidate["findingIds"] = list(dict.fromkeys(candidate["findingIds"] + [item["findingId"] for item in findings if candidate["candidateId"] in item.get("candidateIds", [])]))
        comparisons = [item for item in result["comparisons"] if item["candidateId"] == candidate["candidateId"]]
        latest = comparisons[-1] if comparisons else {}
        supported = set(candidate["supportedActions"])
        candidate["availableActions"] = ["keep_original"]
        if "run_candidate" in supported:
            candidate["availableActions"].append("run_candidate")
        active_states = {"queued", "preparing", "running", "cancelling"}
        if any(item["candidateId"] == candidate["candidateId"] and (item["baselineState"] in active_states or item["candidateState"] in active_states) for item in result.get("executions", [])):
            candidate["availableActions"] = [action for action in candidate["availableActions"] if action != "run_candidate"]
        if latest.get("decision") == "kept" and latest.get("comparable") is True:
            candidate["availableActions"].extend(sorted(supported & _APPLY_ACTIONS))
        applications = [item for item in result["applications"] if item["candidateId"] == candidate["candidateId"]]
        application_state, _ = _application_state(applications)
        if application_state in {"applied", "uncertain"}:
            candidate["availableActions"] = [action for action in candidate["availableActions"] if action == "run_candidate"]
        if application_state == "applied" and "rollback" in supported:
            candidate["availableActions"].append("rollback")
        if candidate["candidateId"] in pending_candidate_ids:
            candidate["availableActions"] = []
    validate_contract(result, _SCHEMA)
    return result


class TraceOptimizationStore:
    """Readers are private owning-service dependencies, never route arguments.

    version_reader(kind, ref) returns {targetKind,targetRef,versionRef,
    contentSha256,content?,availableActions?}. application_reader(ref) returns
    {candidateId,comparisonId,targetKind,targetRef,versionRef,action,status}.
    """

    def __init__(self, db_path: str | Path, *, version_reader: Callable | None = None, application_reader: Callable | None = None):
        self.db_path = Path(db_path)
        self.version_reader = version_reader
        self.application_reader = application_reader
        self.traces = TraceStore(db_path)
        self.evals = EvalRunStore(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def _connection(self):
        self.initialize()
        return sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True)

    def _get(self, record_id: str, kind: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute("SELECT payload_json FROM trace_optimization_records WHERE record_id=? AND record_kind=?", (record_id, kind)).fetchone()
            return _decode_record(row[0]) if row else None

    def get_candidate(self, candidate_id: str) -> dict | None:
        raw = self._get(candidate_id, "candidate")
        return next((item for item in self.read(raw["reportId"])["candidates"] if item["candidateId"] == candidate_id), None) if raw else None

    def get_comparison(self, comparison_id: str) -> dict | None:
        return self._get(comparison_id, "comparison")

    def get_application(self, application_id: str) -> dict | None:
        return self._get(application_id, "application")

    def read(self, report_id: str) -> dict:
        with self._connection() as conn:
            return read_trace_optimization(conn, _identifier(report_id, "reportId"))

    def list_candidates(self, report_id: str) -> list[dict]:
        return self.read(report_id)["candidates"]

    def _previous(self, kind: str, report_id: str, request_id: str, request: Mapping) -> dict | None:
        _identifier(request_id, "clientRequestId")
        with self._connection() as conn:
            row = conn.execute("SELECT request_sha256,payload_json FROM trace_optimization_records WHERE record_kind=? AND report_id=? AND client_request_id=?", (kind, report_id, request_id)).fetchone()
            if row and row[0] != _hash(request):
                raise ValueError("Trace optimization request identity conflict")
            return _decode_record(row[1]) if row else None

    def _persist(self, kind: str, request_id: str, request: Mapping, payload: dict) -> dict:
        payload["contentSha256"] = _hash(payload)
        _validate(payload, "optimization" + kind.title())
        identifier = payload[{"candidate": "candidateId", "comparison": "comparisonId", "application": "applicationId"}[kind]]
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT request_sha256,payload_json FROM trace_optimization_records WHERE record_kind=? AND report_id=? AND client_request_id=?", (kind, payload["reportId"], request_id)).fetchone()
            if row:
                if row[0] != _hash(request):
                    raise ValueError("Trace optimization request identity conflict")
                return _decode_record(row[1])
            count = conn.execute("SELECT COUNT(*) FROM trace_optimization_records WHERE report_id=? AND record_kind=?", (payload["reportId"], kind)).fetchone()[0]
            if count >= (128 if kind == "candidate" else 512):
                raise ValueError("This report reached its bounded optimization record limit; start a new report")
            conn.execute("INSERT INTO trace_optimization_records VALUES(?,?,?,?,?,?,?,?)", (identifier, kind, payload["reportId"], payload["candidateId"], request_id, _hash(request), _json(payload), payload["createdAtMs"]))
        return payload

    def _version(self, kind: str, version_ref: str, target_ref: str) -> dict:
        if self.version_reader is None:
            raise _EvidenceGap("No owning version reader is registered")
        try:
            version = _record(self.version_reader(kind, version_ref), "candidate version")
        except (KeyError, ValueError) as error:
            raise _EvidenceGap(f"Candidate version is unavailable: {version_ref}") from error
        if any(version.get(key) != value for key, value in {"targetKind": kind, "targetRef": target_ref, "versionRef": version_ref}.items()):
            raise _EvidenceGap("Candidate version identity does not match its owning target")
        digest = version.get("contentSha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise _EvidenceGap("Candidate version lacks an immutable content identity")
        # contentSha256 can identify a whole package manifest. A reader may
        # additionally identify the displayed entry text; never equate the two.
        text_digest = version.get("contentTextSha256")
        if text_digest is not None and hashlib.sha256(str(version.get("content", "")).encode()).hexdigest() != text_digest:
            raise _EvidenceGap("Candidate version content changed after registration")
        return version

    def propose(self, report_id: str, *, client_request_id: str, proposal: Mapping) -> dict:
        from .trace_diagnostics import TraceDiagnosticReportStore

        _validate(proposal, "optimizationProposal")
        frozen = json.loads(_json(proposal))
        previous = self._previous("candidate", report_id, client_request_id, frozen)
        if previous:
            return self.get_candidate(previous["candidateId"])
        report = TraceDiagnosticReportStore(self.db_path).get(report_id)
        if report is None or report["status"] not in {"generating", "completed"}:
            raise ValueError("An active or completed diagnostic report is required for a candidate")
        if "intent" not in report:
            raise ValueError("Legacy report has no frozen optimization scope; start a new report")
        intent = report["intent"]
        if frozen["targetKind"] not in intent["focusAreas"]:
            raise ValueError("Candidate target is outside the frozen focus")
        known_findings = {item["findingId"] for item in (report.get("result") or {}).get("findings", [])}
        known_evidence = {item["evidenceId"] for item in report["inspection"]["evidence"]}
        if not set(frozen["findingIds"]) <= known_findings:
            raise ValueError("Candidate references an unknown finding")
        if not set(frozen["evidenceIds"]) <= known_evidence:
            raise ValueError("Candidate references unknown current evidence")
        contract = frozen["comparisonContract"]
        seen = set()
        for change in contract["declaredChanges"]:
            kind = change["kind"]
            if kind not in intent["focusAreas"] or kind in seen:
                raise ValueError("Declared change is duplicated or outside the frozen focus")
            if change["beforeVersionRef"] == change["afterVersionRef"]:
                raise ValueError("Declared intervention must change a version")
            seen.add(kind)
        primary = {"kind": frozen["targetKind"], "targetRef": frozen["targetRef"], "beforeVersionRef": frozen["parentVersionRef"], "afterVersionRef": frozen["candidateVersionRef"]}
        if primary not in contract["declaredChanges"]:
            raise ValueError("Candidate target must match its declared intervention")
        if len({gate["metricId"] for gate in contract["qualityGates"]}) != len(contract["qualityGates"]):
            raise ValueError("Quality metrics must be unique")
        payload = {**frozen, "candidateId": "trace-candidate:" + _hash({"reportId": report_id, "requestId": client_request_id, "proposal": frozen})[:32], "reportId": report_id, "optimizationProjectId": report.get("optimizationProjectId", ""), "intent": intent, "comparisonContractSha256": _hash(contract), "executionStatus": "not_started", "diffStatus": "unverified", "availableActions": ["keep_original"], "supportedActions": [], "createdAtMs": time.time_ns() // 1_000_000}
        try:
            before = self._version(frozen["targetKind"], frozen["parentVersionRef"], frozen["targetRef"])
            after = self._version(frozen["targetKind"], frozen["candidateVersionRef"], frozen["targetRef"])
            payload["diffStatus"] = "verified"
            payload["supportedActions"] = sorted(set(after.get("availableActions", [])) & _ACTIONS)
            if "run_candidate" in payload["supportedActions"]:
                payload["availableActions"].append("run_candidate")
            if isinstance(before.get("content"), str) and isinstance(after.get("content"), str):
                if max(len(before["content"]), len(after["content"])) <= 100000:
                    diff = "".join(difflib.unified_diff(before["content"].splitlines(keepends=True), after["content"].splitlines(keepends=True), fromfile=frozen["parentVersionRef"], tofile=frozen["candidateVersionRef"]))
                    payload["actualDiff"] = {"before": before["content"], "after": after["content"], "unifiedDiff": diff[:200000]}
        except _EvidenceGap:
            pass
        return self._persist("candidate", client_request_id, frozen, payload)

    def _trial(self, trial_id: str) -> dict:
        # Read the real owning table, never a caller-provided run body.
        with self._connection() as conn:
            row = conn.execute("SELECT state,public_spec_json,result_json FROM agent_lab_trials WHERE job_id=?", (trial_id,)).fetchone()
        if row is None:
            raise _EvidenceGap(f"Lab Trial is unavailable: {trial_id}")
        return {"state": row[0], "publicSpec": json.loads(row[1]), "result": json.loads(row[2]) if row[2] else None}

    def _execution(self, candidate: Mapping, trial: Mapping, role: str) -> dict:
        if trial["state"] != "completed":
            raise _EvidenceGap(f"{role} Trial is {trial['state']}")
        identity = {"candidateId": candidate["candidateId"], "role": role, "comparisonContractSha256": candidate["comparisonContractSha256"]}
        spec = _record(trial.get("publicSpec"), "Trial input")
        if spec.get("traceOptimization") != identity:
            raise _EvidenceGap(f"{role} Trial was not frozen for this candidate and comparison contract")
        result = _record(_record(trial.get("result"), "Trial result").get("traceOptimization"), "Loaded-version execution receipt")
        if any(result.get(key) != value for key, value in identity.items()):
            raise _EvidenceGap("Execution receipt is bound to another candidate or contract")
        controls = _record(result.get("controls"), "Execution controls")
        if controls != candidate["comparisonContract"]["controls"]:
            raise _EvidenceGap("Undeclared input, environment, evaluator or permission control drift")
        versions = _record(result.get("loadedVersions"), "Actual loaded versions")
        if set(versions) != set(FOCUS_AREAS) or any(not isinstance(value, str) or not value for value in versions.values()):
            raise _EvidenceGap("All five actual component versions must be recorded")
        fixed_context = None
        if "fixedContextFingerprints" in result:
            fixed_context = _record(result["fixedContextFingerprints"], "Fixed Pi context fingerprints")
            if len(fixed_context) > 32 or any(not isinstance(key, str) or not 1 <= len(key) <= 120
                or not isinstance(value, str) or not 1 <= len(value) <= 640 for key, value in fixed_context.items()):
                raise _EvidenceGap("Fixed Pi context fingerprints must be a bounded string map")
        cases = result.get("cases")
        if not isinstance(cases, list) or any(not isinstance(item, Mapping) for item in cases):
            raise _EvidenceGap("Per-case execution identities are unavailable")
        ids = [item.get("caseId") for item in cases]
        if len(set(ids)) != len(ids) or set(ids) != set(candidate["comparisonContract"]["caseIds"]):
            raise _EvidenceGap("Execution case set differs from the frozen comparison")
        loaded = {}
        for case in cases:
            trace = _record(self.traces.get(str(case.get("traceId", ""))), "Executed Trace")
            run = _record(self.evals.get(str(case.get("evalRunId", ""))), "Ground-truth Eval")
            if trace.get("status") not in {"completed", "failed"} or trace.get("binding", {}).get("caseId") != case["caseId"]:
                raise _EvidenceGap("Trace does not identify the terminal frozen case")
            expected = {**identity, "controls": controls, "loadedVersions": versions}
            if fixed_context is not None:
                expected["fixedContextFingerprints"] = fixed_context
            if not any(span.get("recorded") is True and span.get("name") == "trace.optimization.execution" and span.get("attributes", {}).get("traceOptimization") == expected for span in trace.get("spans", [])):
                raise _EvidenceGap("Trace lacks actual loaded-version evidence from its execution owner")
            if run.get("status") != "completed" or run.get("mode") != "ground_truth" or run.get("metricAuthority") != "ground_truth" or run.get("truth", {}).get("status") not in {"human", "frozen"}:
                raise _EvidenceGap("A completed ground-truth Eval is required; model scores are unverified")
            if trace["traceId"] not in run.get("traceIds", []) or run.get("inputTraceFingerprint") != trace["input"]["fingerprint"]:
                raise _EvidenceGap("Eval is not bound to the executed Trace and input")
            loaded[case["caseId"]] = {"trace": trace, "eval": run}
        return {**result, "loadedCases": loaded}

    def record_validation(self, candidate_id: str, *, client_request_id: str, baseline_trial_id: str, candidate_trial_id: str) -> dict:
        candidate = self._get(candidate_id, "candidate")
        if candidate is None:
            raise KeyError(candidate_id)
        request = {"candidateId": candidate_id, "baselineTrialId": _identifier(baseline_trial_id, "baselineTrialId"), "candidateTrialId": _identifier(candidate_trial_id, "candidateTrialId")}
        previous = self._previous("comparison", candidate["reportId"], client_request_id, request)
        if previous:
            return previous
        payload = {"comparisonId": "trace-comparison:" + _hash({**request, "requestId": client_request_id})[:32], "reportId": candidate["reportId"], "candidateId": candidate_id, "optimizationProjectId": candidate["optimizationProjectId"], "baselineTrialId": baseline_trial_id, "candidateTrialId": candidate_trial_id, "executionStatus": "not_started", "effectStatus": "unverified", "decision": "needs_validation", "validationScope": "unverified", "comparable": False, "reason": "", "pairedMetrics": [], "cases": [], "regressions": [], "usage": {"baselineCost": None, "candidateCost": None, "currency": "", "complete": False}, "evidenceRefs": [baseline_trial_id, candidate_trial_id], "actualLoadedVersions": {"baseline": {}, "candidate": {}}, "createdAtMs": time.time_ns() // 1_000_000}
        try:
            if baseline_trial_id == candidate_trial_id:
                raise _EvidenceGap("Baseline and candidate must be separate actual executions")
            before_trial, after_trial = self._trial(baseline_trial_id), self._trial(candidate_trial_id)
            states = {before_trial["state"], after_trial["state"]}
            payload["executionStatus"] = next((state for state in ("failed", "cancelled", "interrupted") if state in states), "completed" if states == {"completed"} else "not_started")
            before, after = self._execution(candidate, before_trial, "baseline"), self._execution(candidate, after_trial, "candidate")
            payload["actualLoadedVersions"] = {"baseline": before["loadedVersions"], "candidate": after["loadedVersions"]}
            self._compare(candidate, before, after, payload)
            kinds = {before_trial["publicSpec"].get("evaluationKind"), after_trial["publicSpec"].get("evaluationKind")}
            if kinds == {"frozen_local_task_fixture"}:
                payload["validationScope"] = "frozen_local_task_fixture"
                payload["reason"] += "; 仅验证冻结的本地任务用例，未证明未见任务或真实模型行为的改善。"
            else:
                payload["validationScope"] = "registered_task_execution"
        except (_EvidenceGap, KeyError, TypeError) as error:
            payload["reason"] = str(error)[:2000]
            if payload["executionStatus"] in {"failed", "cancelled", "interrupted"}:
                payload["decision"] = "rejected"
        return self._persist("comparison", client_request_id, request, payload)

    def _compare(self, candidate: Mapping, before: Mapping, after: Mapping, payload: dict) -> None:
        if before.get("fixedContextFingerprints") != after.get("fixedContextFingerprints"):
            raise _EvidenceGap("Undeclared fixed Pi context drift")
        contract = candidate["comparisonContract"]
        changes = {change["kind"]: change for change in contract["declaredChanges"]}
        for kind in FOCUS_AREAS:
            baseline_version, candidate_version = before["loadedVersions"][kind], after["loadedVersions"][kind]
            if kind in changes:
                change = changes[kind]
                if baseline_version != change["beforeVersionRef"] or candidate_version != change["afterVersionRef"]:
                    raise _EvidenceGap("Actually loaded target versions differ from the declared intervention")
                self._version(kind, baseline_version, change["targetRef"])
                self._version(kind, candidate_version, change["targetRef"])
            elif baseline_version != candidate_version:
                raise _EvidenceGap(f"Undeclared {kind} version drift")
        values = {gate["metricId"]: ([], []) for gate in contract["qualityGates"]}
        regressions, gates_passed = [], True
        for case_id in contract["caseIds"]:
            left, right = before["loadedCases"][case_id], after["loadedCases"][case_id]
            baseline, current = left["eval"], right["eval"]
            for key in ("truth", "evaluator", "suiteBinding", "inputTraceFingerprint", "promptVersion", "rubricVersion"):
                if baseline.get(key) != current.get(key):
                    raise _EvidenceGap(f"Undeclared per-case {key} drift")
            case_regressed = False
            primary_values = None
            for gate in contract["qualityGates"]:
                metric = gate["metricId"]
                b, c = _number(baseline["metrics"].get(metric), metric), _number(current["metrics"].get(metric), metric)
                if not 0 <= b <= 1 or not 0 <= c <= 1:
                    raise _EvidenceGap("Quality metrics must use the frozen unit interval")
                values[metric][0].append(b); values[metric][1].append(c)
                case_regressed |= c < b
                gates_passed &= c >= gate["minimum"]
                primary_values = primary_values or (b, c)
            if case_regressed:
                regressions.append(case_id)
            payload["cases"].append({"caseId": case_id, "baseline": primary_values[0], "candidate": primary_values[1], "regressed": case_regressed})
            payload["evidenceRefs"].extend([left["trace"]["traceId"], baseline["evalRunId"], right["trace"]["traceId"], current["evalRunId"]])
        quality_improved = False
        for metric, (baseline, current) in values.items():
            b, c = sum(baseline) / len(baseline), sum(current) / len(current)
            quality_improved |= c > b
            payload["pairedMetrics"].append({"metricId": metric, "kind": "quality", "baseline": b, "candidate": c, "delta": c - b, "baselineNumerator": sum(baseline), "baselineDenominator": len(baseline), "candidateNumerator": sum(current), "candidateDenominator": len(current)})
        payload["comparable"] = True
        payload["regressions"] = regressions
        costs = [before.get("usage"), after.get("usage")]
        if all(isinstance(cost, Mapping) and cost.get("complete") is True and cost.get("currency") and isinstance(cost.get("receiptRefs"), list) and cost["receiptRefs"] for cost in costs):
            if costs[0]["currency"] == costs[1]["currency"]:
                b, c = _number(costs[0].get("totalCost"), "baseline cost"), _number(costs[1].get("totalCost"), "candidate cost")
                # Only identities already present in this host-bound execution
                # may substantiate cost completeness.
                known = set(payload["evidenceRefs"])
                if b >= 0 and c >= 0 and all(set(cost["receiptRefs"]) <= known for cost in costs):
                    payload["usage"] = {"baselineCost": b, "candidateCost": c, "currency": costs[0]["currency"], "complete": True}
        if regressions:
            payload.update(effectStatus="regressed", decision="rejected", reason="Quality regressed on frozen cases; cost cannot offset this regression")
        elif not gates_passed:
            payload.update(effectStatus="neutral", decision="rejected", reason="Candidate does not satisfy the frozen quality requirements")
        else:
            usage = payload["usage"]
            cost_improved = usage["complete"] and usage["candidateCost"] < usage["baselineCost"]
            if contract["costMetric"] and not usage["complete"] and not quality_improved:
                payload.update(effectStatus="unverified", decision="needs_validation", reason="Quality is comparable, but complete execution cost is unavailable")
            elif quality_improved or (contract["costMetric"] and cost_improved):
                payload.update(effectStatus="improved", decision="kept", reason="Frozen quality requirements passed without case regressions; the declared intervention improved quality or execution cost")
            else:
                payload.update(effectStatus="neutral", decision="rejected", reason="No measured improvement under the frozen quality and cost objective")
            if usage["complete"]:
                payload["pairedMetrics"].append({"metricId": "totalCost", "kind": "cost", "baseline": usage["baselineCost"], "candidate": usage["candidateCost"], "delta": usage["candidateCost"] - usage["baselineCost"], "baselineNumerator": None, "baselineDenominator": None, "candidateNumerator": None, "candidateDenominator": None})

    def bind_application(self, candidate_id: str, *, client_request_id: str, action: str, receipt_ref: str = "") -> dict:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if action not in _ACTIONS - {"run_candidate"}:
            raise ValueError("Unsupported application action")
        request = {"candidateId": candidate_id, "action": action, "receiptRef": receipt_ref}
        previous = self._previous("application", candidate["reportId"], client_request_id, request)
        if previous:
            return previous
        report_state = self.read(candidate["reportId"])
        comparisons = [item for item in report_state["comparisons"] if item["candidateId"] == candidate_id]
        latest = comparisons[-1] if comparisons else {}
        applications = [item for item in report_state["applications"] if item["candidateId"] == candidate_id]
        application_state, applied = _application_state(applications)
        pending = [item for item in report_state.get("pendingApplications", []) if item["candidateId"] == candidate_id]
        comparison_id = applied["comparisonId"] if action == "rollback" and applied else latest.get("comparisonId", "")
        version = candidate["parentVersionRef"] if action in {"rollback", "keep_original"} else candidate["candidateVersionRef"]
        status = "kept_original"
        if action != "keep_original":
            # Attaching an already persisted uncertain owner result closes
            # its report linkage; it does not authorize another side effect.
            pending_receipt = next((item for item in pending if item["receiptRef"] == receipt_ref
                and item["action"] == action and item["status"] == "interrupted"), None)
            if action not in candidate["availableActions"] and pending_receipt is None:
                raise ValueError("Candidate has no validated owning action available")
            if self.application_reader is None or not receipt_ref:
                raise ValueError("An owning application receipt is required")
            receipt = _record(self.application_reader(receipt_ref), "Application receipt")
            identity = {"candidateId": candidate_id, "targetKind": candidate["targetKind"], "targetRef": candidate["targetRef"], "versionRef": version, "action": action, "comparisonId": comparison_id}
            if any(receipt.get(key) != value for key, value in identity.items()):
                raise ValueError("Application receipt differs from the exact candidate, comparison or version")
            status = receipt.get("status")
            if status not in ({"rolled_back", "failed", "interrupted"} if action == "rollback" else {"applied", "failed", "interrupted"}):
                raise ValueError("Application receipt does not contain a terminal action result")
        elif application_state != "not_applied" or pending:
            raise ValueError("An applied or uncertain version requires its owning rollback or recovery result")
        elif receipt_ref:
            raise ValueError("Keeping the original version does not accept an installation receipt")
        payload = {"applicationId": "trace-application:" + _hash({**request, "requestId": client_request_id})[:32], "reportId": candidate["reportId"], "candidateId": candidate_id, "comparisonId": comparison_id, "action": action, "status": status, "receiptRef": receipt_ref, "targetRef": candidate["targetRef"], "versionRef": version, "createdAtMs": time.time_ns() // 1_000_000}
        return self._persist("application", client_request_id, request, payload)
