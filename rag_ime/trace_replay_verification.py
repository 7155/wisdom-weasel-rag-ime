"""Same-case Trace replay authority and immutable verification receipts.

AI Judge repair reviews remain useful qualitative evidence, but they cannot
measure repair effect.  This module compares only Host-owned SandboxRun and
ground-truth EvalRun records whose replay cohort is byte-for-byte identical.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

from .contracts.json_schema import ContractValidationError, validate_contract
from .db import apply_database_migrations, sqlite_connection
from .eval_run_store import EvalRunStore
from .sandbox_run_store import SandboxRunStore
from .trace_repair import TraceRepairStore
from .trace_store import TraceStore


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_COHORT_KEYS = frozenset(
    {
        "suiteId",
        "suiteRevision",
        "caseId",
        "inputFingerprint",
        "environmentFingerprint",
        "configFingerprint",
        "modelProfileFingerprint",
        "toolProfileFingerprint",
        "skillProfileFingerprint",
    }
)


class TraceVerificationValidationError(ValueError):
    """The requested replay is not comparable or lacks authoritative evidence."""


class TraceVerificationConflict(RuntimeError):
    """A stable replay or verification identity was rebound."""


class TraceReplayVerificationStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.traces = TraceStore(self.db_path)
        self.evals = EvalRunStore(self.db_path)
        self.sandboxes = SandboxRunStore(self.db_path)
        self.repairs = TraceRepairStore(self.db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def freeze_case(
        self,
        *,
        source_scope: str,
        failure_ref: str,
        source_trace_id: str,
        baseline_eval_run_id: str,
        baseline_sandbox_run_id: str,
        success_metric: str,
        success_threshold: float,
        rollback_target: str,
        created_at_ms: int,
    ) -> dict[str, object]:
        scope = _token(source_scope, "sourceScope")
        failure = _token(failure_ref, "failureRef")
        source_trace = _required_record(
            self.traces.get(_token(source_trace_id, "sourceTraceId")),
            "source Trace",
        )
        baseline_eval = _required_record(
            self.evals.get(_token(baseline_eval_run_id, "baselineEvalRunId")),
            "baseline EvalRun",
        )
        baseline_sandbox = _required_record(
            self.sandboxes.get(
                _token(baseline_sandbox_run_id, "baselineSandboxRunId")
            ),
            "baseline SandboxRun",
        )
        metric = _token(success_metric, "success metric")
        threshold = _unit_interval(success_threshold, "success threshold")
        created = _non_negative_int(created_at_ms, "createdAtMs")
        rollback = _token(rollback_target, "rollbackTarget")

        cohort = _cohort_from_sandbox(baseline_sandbox)
        _assert_trace_matches_cohort(source_trace, cohort, "source")
        _assert_eval_matches_cohort(
            baseline_eval,
            trace_id=str(source_trace["traceId"]),
            cohort=cohort,
            label="baseline",
        )
        _assert_sandbox_binding(
            baseline_sandbox,
            trace_id=str(source_trace["traceId"]),
            eval_run_id=str(baseline_eval["evalRunId"]),
            cohort=cohort,
            label="baseline",
        )
        before = _metric_value(baseline_eval, metric, "baseline")
        if before >= threshold:
            raise TraceVerificationValidationError(
                "baseline EvalRun already satisfies the success criterion"
            )
        identity = _sha256(
            {
                "sourceScope": scope,
                "failureRef": failure,
                "sourceTraceId": source_trace["traceId"],
                "baselineEvalRunId": baseline_eval["evalRunId"],
                "baselineSandboxRunId": baseline_sandbox["sandboxRunId"],
                "replayCohort": cohort,
                "successMetric": metric,
                "successThreshold": threshold,
            }
        )
        payload = {
            "schemaVersion": "rag-ime.trace-replay-case.v1",
            "replayCaseId": f"replay-case:{identity[:32]}",
            "sourceScope": scope,
            "failureRef": failure,
            "sourceTraceId": source_trace["traceId"],
            "baselineEvalRunId": baseline_eval["evalRunId"],
            "baselineSandboxRunId": baseline_sandbox["sandboxRunId"],
            "replayCohort": cohort,
            "successCriterion": {
                "metric": metric,
                "threshold": threshold,
                "direction": "at_least",
            },
            "baselineMetricValue": before,
            "rollbackTarget": rollback,
            "createdAtMs": created,
        }
        _validate(payload, "trace-replay-case.v1.json")
        return self._persist_case(payload)

    def get_case(self, replay_case_id: str) -> dict[str, object] | None:
        return self._get(
            table="trace_replay_cases",
            id_column="replay_case_id",
            identifier=_token(replay_case_id, "replayCaseId"),
            contract="trace-replay-case.v1.json",
        )

    def verify_repair(
        self,
        *,
        replay_case_id: str,
        repair_receipt_id: str,
        repair_eval_run_id: str,
        repair_sandbox_run_id: str,
        regression_eval_run_ids: Sequence[str],
        verified_at_ms: int,
    ) -> dict[str, object]:
        replay_case = _required_record(
            self.get_case(_token(replay_case_id, "replayCaseId")),
            "ReplayCase",
        )
        repair_receipt = _required_record(
            self.repairs.get_receipt(_token(repair_receipt_id, "repairReceiptId")),
            "TraceRepairReceipt",
        )
        repair_eval = _required_record(
            self.evals.get(_token(repair_eval_run_id, "repairEvalRunId")),
            "repair EvalRun",
        )
        repair_sandbox = _required_record(
            self.sandboxes.get(_token(repair_sandbox_run_id, "repairSandboxRunId")),
            "repair SandboxRun",
        )
        regression_ids = _unique_tokens(
            regression_eval_run_ids,
            "regressionEvalRunId",
        )
        if not regression_ids:
            raise TraceVerificationValidationError(
                "at least one regression EvalRun is required"
            )
        verified_at = _non_negative_int(verified_at_ms, "verifiedAtMs")

        source_trace_id = str(replay_case["sourceTraceId"])
        if (
            repair_receipt.get("sourceTraceId") != source_trace_id
            or repair_receipt.get("failureRef") != replay_case["failureRef"]
            or repair_receipt.get("sourceScope") != replay_case["sourceScope"]
            or repair_receipt.get("testStatus") != "passed"
        ):
            raise TraceVerificationValidationError(
                "repair receipt does not match the frozen ReplayCase"
            )
        repair_trace_id = _token(
            repair_receipt.get("repairTraceId"), "repairTraceId"
        )
        repair_trace = _required_record(
            self.traces.get(repair_trace_id), "repair Trace"
        )
        cohort = _cohort(replay_case.get("replayCohort"))
        _assert_trace_matches_cohort(repair_trace, cohort, "repair")
        _assert_eval_matches_cohort(
            repair_eval,
            trace_id=repair_trace_id,
            cohort=cohort,
            label="repair",
        )
        baseline_eval = _required_record(
            self.evals.get(str(replay_case["baselineEvalRunId"])),
            "baseline EvalRun",
        )
        _assert_eval_comparable(baseline_eval, repair_eval)
        _assert_sandbox_binding(
            repair_sandbox,
            trace_id=repair_trace_id,
            eval_run_id=str(repair_eval["evalRunId"]),
            cohort=cohort,
            label="repair",
        )
        baseline_sandbox = _required_record(
            self.sandboxes.get(str(replay_case["baselineSandboxRunId"])),
            "baseline SandboxRun",
        )
        if _workspace_fingerprint(repair_sandbox) != _workspace_fingerprint(
            baseline_sandbox
        ):
            raise TraceVerificationValidationError(
                "repair workspace fingerprint differs from the baseline"
            )

        failed_regressions: list[str] = []
        sandbox_eval_ids = set(_string_list(repair_sandbox.get("evalRunIds")))
        sandbox_trace_ids = set(_string_list(repair_sandbox.get("traceIds")))
        for regression_id in regression_ids:
            run = _required_record(
                self.evals.get(regression_id), f"regression EvalRun {regression_id}"
            )
            _assert_ground_truth_eval(run, f"regression EvalRun {regression_id}")
            if regression_id not in sandbox_eval_ids:
                raise TraceVerificationValidationError(
                    "regression EvalRun is not bound to the repair SandboxRun"
                )
            trace_ids = set(_string_list(run.get("traceIds")))
            if not trace_ids or not trace_ids.issubset(sandbox_trace_ids):
                raise TraceVerificationValidationError(
                    "regression Trace is not bound to the repair SandboxRun"
                )
            if _metric_value(run, "accuracy", "regression") < 1.0:
                failed_regressions.append(regression_id)

        criterion = _required_record(
            replay_case.get("successCriterion"), "success criterion"
        )
        metric = _token(criterion.get("metric"), "success metric")
        threshold = _unit_interval(criterion.get("threshold"), "success threshold")
        before = _unit_interval(
            replay_case.get("baselineMetricValue"), "baseline metric value"
        )
        after = _metric_value(repair_eval, metric, "repair")
        delta = after - before
        repair_passed = after >= threshold
        regression_passed = not failed_regressions
        decision = "kept" if repair_passed and regression_passed else "rejected"
        relative = None if before == 0 else delta / before
        identity = _sha256(
            {
                "replayCaseId": replay_case["replayCaseId"],
                "repairReceiptId": repair_receipt["repairReceiptId"],
                "repairEvalRunId": repair_eval["evalRunId"],
                "repairSandboxRunId": repair_sandbox["sandboxRunId"],
                "regressionEvalRunIds": regression_ids,
            }
        )
        payload = {
            "schemaVersion": "rag-ime.trace-verification-receipt.v1",
            "verificationReceiptId": f"trace-verification:{identity[:32]}",
            "replayCaseId": replay_case["replayCaseId"],
            "repairReceiptId": repair_receipt["repairReceiptId"],
            "sourceTraceId": source_trace_id,
            "repairTraceId": repair_trace_id,
            "baselineEvalRunId": replay_case["baselineEvalRunId"],
            "repairEvalRunId": repair_eval["evalRunId"],
            "baselineSandboxRunId": replay_case["baselineSandboxRunId"],
            "repairSandboxRunId": repair_sandbox["sandboxRunId"],
            "regressionEvalRunIds": regression_ids,
            "replayCohort": cohort,
            "successCriterion": dict(criterion),
            "repairPassed": repair_passed,
            "regression": {
                "count": len(regression_ids),
                "passed": regression_passed,
                "failedEvalRunIds": failed_regressions,
            },
            "comparison": {
                "status": "available",
                "metric": metric,
                "before": before,
                "after": after,
                "absoluteDelta": delta,
                "relativeDelta": relative,
            },
            "efficiency": {
                "latencyMs": _integer_delta(baseline_eval, repair_eval, "latencyMs"),
                "totalTokens": _usage_delta(
                    baseline_eval,
                    repair_eval,
                    "totalTokens",
                ),
            },
            "decision": decision,
            "rollbackTarget": replay_case["rollbackTarget"],
            "createdAtMs": verified_at,
        }
        _validate(payload, "trace-verification-receipt.v1.json")
        return self._persist_verification(payload)

    def get_verification(
        self, verification_receipt_id: str
    ) -> dict[str, object] | None:
        return self._get(
            table="trace_verification_receipts",
            id_column="verification_receipt_id",
            identifier=_token(
                verification_receipt_id, "verificationReceiptId"
            ),
            contract="trace-verification-receipt.v1.json",
        )

    def list_verifications(self) -> list[dict[str, object]]:
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM trace_verification_receipts "
                "ORDER BY created_at_ms, verification_receipt_id"
            ).fetchall()
        return [
            _decode(str(row["payload_json"]), "trace-verification-receipt.v1.json")
            for row in rows
        ]

    def _persist_case(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._persist(
            table="trace_replay_cases",
            id_column="replay_case_id",
            identifier=str(payload["replayCaseId"]),
            columns=(
                "source_trace_id",
                "baseline_eval_run_id",
                "baseline_sandbox_run_id",
                "created_at_ms",
            ),
            values=(
                payload["sourceTraceId"],
                payload["baselineEvalRunId"],
                payload["baselineSandboxRunId"],
                payload["createdAtMs"],
            ),
            payload=payload,
            contract="trace-replay-case.v1.json",
        )

    def _persist_verification(
        self, payload: Mapping[str, object]
    ) -> dict[str, object]:
        return self._persist(
            table="trace_verification_receipts",
            id_column="verification_receipt_id",
            identifier=str(payload["verificationReceiptId"]),
            columns=(
                "replay_case_id",
                "repair_receipt_id",
                "repair_eval_run_id",
                "repair_sandbox_run_id",
                "decision",
                "created_at_ms",
            ),
            values=(
                payload["replayCaseId"],
                payload["repairReceiptId"],
                payload["repairEvalRunId"],
                payload["repairSandboxRunId"],
                payload["decision"],
                payload["createdAtMs"],
            ),
            payload=payload,
            contract="trace-verification-receipt.v1.json",
        )

    def _persist(
        self,
        *,
        table: str,
        id_column: str,
        identifier: str,
        columns: Sequence[str],
        values: Sequence[object],
        payload: Mapping[str, object],
        contract: str,
    ) -> dict[str, object]:
        canonical = _canonical(payload)
        payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT payload_hash, payload_json FROM {table} WHERE {id_column} = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["payload_hash"]) != payload_hash
                    or str(existing["payload_json"]) != canonical
                ):
                    raise TraceVerificationConflict(identifier)
                return _decode(str(existing["payload_json"]), contract)
            placeholders = ", ".join("?" for _ in range(len(columns) + 3))
            conn.execute(
                f"INSERT INTO {table} ({id_column}, {', '.join(columns)}, payload_hash, payload_json) "
                f"VALUES ({placeholders})",
                (identifier, *values, payload_hash, canonical),
            )
        return dict(payload)

    def _get(
        self,
        *,
        table: str,
        id_column: str,
        identifier: str,
        contract: str,
    ) -> dict[str, object] | None:
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = conn.execute(
                f"SELECT payload_json FROM {table} WHERE {id_column} = ?",
                (identifier,),
            ).fetchone()
        return None if row is None else _decode(str(row["payload_json"]), contract)


def _required_record(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TraceVerificationValidationError(f"{label} is unavailable")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise TraceVerificationValidationError(
            f"{label} must be a bounded identifier"
        )
    return value


def _fingerprint(value: object, label: str) -> str:
    if not isinstance(value, str) or _FINGERPRINT.fullmatch(value) is None:
        raise TraceVerificationValidationError(
            f"{label} must be a SHA-256 fingerprint"
        )
    return value


def _unit_interval(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TraceVerificationValidationError(f"{label} must be numeric")
    result = float(value)
    if not 0 <= result <= 1:
        raise TraceVerificationValidationError(f"{label} must be between zero and one")
    return result


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TraceVerificationValidationError(f"{label} must be non-negative")
    return value


def _cohort(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _COHORT_KEYS:
        raise TraceVerificationValidationError(
            "replay cohort is incomplete or contains unknown fields"
        )
    result = {
        "suiteId": _token(value.get("suiteId"), "suiteId"),
        "suiteRevision": _token(value.get("suiteRevision"), "suiteRevision"),
        "caseId": _token(value.get("caseId"), "caseId"),
    }
    for field in sorted(_COHORT_KEYS - {"suiteId", "suiteRevision", "caseId"}):
        result[field] = _fingerprint(value.get(field), field)
    return result


def _cohort_from_sandbox(sandbox: Mapping[str, object]) -> dict[str, str]:
    return _cohort(sandbox.get("replayCohort"))


def _trace_input(trace: Mapping[str, object]) -> str:
    return _fingerprint(
        _required_record(trace.get("input"), "Trace input").get("fingerprint"),
        "Trace input fingerprint",
    )


def _assert_trace_matches_cohort(
    trace: Mapping[str, object], cohort: Mapping[str, str], label: str
) -> None:
    if trace.get("status") not in {"completed", "failed"}:
        raise TraceVerificationValidationError(f"{label} Trace is not terminal")
    if _trace_input(trace) != cohort["inputFingerprint"]:
        raise TraceVerificationValidationError(
            f"{label} Trace input fingerprint differs from the replay cohort"
        )
    binding = _required_record(trace.get("binding"), f"{label} Trace binding")
    if binding.get("caseId") != cohort["caseId"]:
        raise TraceVerificationValidationError(
            f"{label} Trace caseId differs from the replay cohort"
        )


def _assert_ground_truth_eval(run: Mapping[str, object], label: str) -> None:
    truth = _required_record(run.get("truth"), f"{label} truth")
    if (
        run.get("status") != "completed"
        or run.get("mode") != "ground_truth"
        or run.get("metricAuthority") != "ground_truth"
        or truth.get("status") not in {"human", "frozen"}
    ):
        raise TraceVerificationValidationError(
            f"{label} must be a completed ground-truth EvalRun"
        )


def _assert_eval_matches_cohort(
    run: Mapping[str, object],
    *,
    trace_id: str,
    cohort: Mapping[str, str],
    label: str,
) -> None:
    _assert_ground_truth_eval(run, f"{label} EvalRun")
    if trace_id not in _string_list(run.get("traceIds")):
        raise TraceVerificationValidationError(
            f"{label} EvalRun is not bound to its Trace"
        )
    if run.get("inputTraceFingerprint") != cohort["inputFingerprint"]:
        raise TraceVerificationValidationError(
            f"{label} EvalRun input fingerprint differs from the ReplayCase"
        )
    suite = _required_record(run.get("suiteBinding"), f"{label} suite binding")
    if suite != {
        "suiteId": cohort["suiteId"],
        "suiteRevision": cohort["suiteRevision"],
    }:
        raise TraceVerificationValidationError(
            f"{label} EvalRun suite differs from the ReplayCase"
        )


def _assert_eval_comparable(
    before: Mapping[str, object], after: Mapping[str, object]
) -> None:
    for field in (
        "truth",
        "evaluator",
        "suiteBinding",
        "inputTraceFingerprint",
        "promptVersion",
        "rubricVersion",
    ):
        if before.get(field) != after.get(field):
            label = "input fingerprint" if field == "inputTraceFingerprint" else field
            raise TraceVerificationValidationError(
                f"before/after EvalRun {label} is not comparable"
            )


def _assert_sandbox_binding(
    sandbox: Mapping[str, object],
    *,
    trace_id: str,
    eval_run_id: str,
    cohort: Mapping[str, str],
    label: str,
) -> None:
    if sandbox.get("status") != "completed":
        raise TraceVerificationValidationError(f"{label} SandboxRun is not completed")
    policy = _required_record(sandbox.get("policy"), f"{label} sandbox policy")
    if policy.get("network") != "blocked" or policy.get("productionWriteBlocked") is not True:
        raise TraceVerificationValidationError(
            f"{label} SandboxRun is not isolated from network and production writes"
        )
    if trace_id not in _string_list(sandbox.get("traceIds")):
        raise TraceVerificationValidationError(
            f"{label} Trace is not bound to the SandboxRun"
        )
    if eval_run_id not in _string_list(sandbox.get("evalRunIds")):
        raise TraceVerificationValidationError(
            f"{label} EvalRun is not bound to the SandboxRun"
        )
    if _cohort_from_sandbox(sandbox) != dict(cohort):
        raise TraceVerificationValidationError(
            f"{label} SandboxRun replay cohort differs from the ReplayCase"
        )


def _workspace_fingerprint(sandbox: Mapping[str, object]) -> str:
    policy = _required_record(sandbox.get("policy"), "sandbox policy")
    return _fingerprint(policy.get("workspaceFingerprint"), "workspaceFingerprint")


def _metric_value(run: Mapping[str, object], metric: str, label: str) -> float:
    metrics = _required_record(run.get("metrics"), f"{label} metrics")
    if metric not in metrics:
        raise TraceVerificationValidationError(
            f"{label} EvalRun has no {metric} metric"
        )
    return _unit_interval(metrics[metric], f"{label} {metric}")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _unique_tokens(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceVerificationValidationError(f"{label}s must be a sequence")
    result: list[str] = []
    for item in value:
        token = _token(item, label)
        if token in result:
            raise TraceVerificationValidationError(f"{label}s must be unique")
        result.append(token)
    return result


def _integer_delta(
    before: Mapping[str, object], after: Mapping[str, object], field: str
) -> dict[str, int | None]:
    left = before.get(field)
    right = after.get(field)
    if (
        isinstance(left, int)
        and not isinstance(left, bool)
        and isinstance(right, int)
        and not isinstance(right, bool)
    ):
        return {"before": left, "after": right, "delta": right - left}
    return {"before": None, "after": None, "delta": None}


def _usage_delta(
    before: Mapping[str, object], after: Mapping[str, object], field: str
) -> dict[str, int | None]:
    left = before.get("usage")
    right = after.get("usage")
    return _integer_delta(
        left if isinstance(left, Mapping) else {},
        right if isinstance(right, Mapping) else {},
        field,
    )


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _validate(payload: Mapping[str, object], contract: str) -> None:
    try:
        validate_contract(payload, contract)
    except (ContractValidationError, ValueError) as exc:
        raise TraceVerificationValidationError(str(exc)) from exc


def _decode(raw: str, contract: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("persisted Trace verification payload is not an object")
    _validate(value, contract)
    return value


__all__ = [
    "TraceReplayVerificationStore",
    "TraceVerificationConflict",
    "TraceVerificationValidationError",
]
