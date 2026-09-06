#!/usr/bin/env python3
"""Project source-grounded Agent Lab optimization metrics.

The exporter reads the checked-in experiment and evidence ledgers plus the
retained JSON receipts they reference.  It never runs a Provider request and
does not turn a missing optimizer receipt into a zero.  Evaluation spend is
reported separately from the (usually unavailable) cost of building or
searching candidates.

Usage::

    python3 scripts/summarize_paw_optimization_metrics.py \
      --output /tmp/paw-optimization-metrics.json

Pass ``--check`` to verify an existing projection without rewriting it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
METRICS_DIR = ROOT / "eval" / "interview-metrics"
RUNS_DIR = METRICS_DIR / "runs"

CURRENT_EXPERIMENTS: tuple[tuple[str, str, str], ...] = (
    ("enterpriseops", "enterpriseops-csm.luna-prompt-adaptation-r7.v1", "enterprise-customer-support"),
    ("enterprise_rag", "enterprise-rag.luna-prompt-v4-standard-r6.v1", "enterprise-knowledge-retrieval"),
    ("cloudops", "cloudops.luna-owner-mechanism-prompt-r5.v1", "cloudops-incident-diagnosis"),
    ("memory", "memory.maintenance-pi-model-only-20260905-r3.v1", "memory-maintenance"),
)

_COST_KEYS = ("apiCostUsd", "estimatedApiCostUsd", "costUsd")
_ELAPSED_KEYS = ("latencyMs", "elapsedMs", "trialElapsedMs", "actualModelCallElapsedMs")
_JUDGE_KEYS = ("judgeCalls", "judgeCallCount")
_MISSING = object()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and math.isfinite(float(value))


def _number(value: object, *, label: str) -> int | float:
    if not _is_number(value):
        raise ValueError(f"{label} must be a finite number")
    return value  # type: ignore[return-value]


def _decimal(value: object, *, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be a finite decimal")
    return result


def _money(value: Decimal) -> str:
    """Serialize USD without float rounding or scientific notation."""

    if not value.is_finite():
        raise ValueError("money must be finite")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _get(mapping: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return _MISSING


def _as_int(value: object, *, label: str) -> int | None:
    if value is _MISSING or value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite integer")
    rounded = int(value)
    if float(value) != float(rounded):
        raise ValueError(f"{label} must be an integer")
    return rounded


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if isinstance(item, str) and item))


def _relative_ref(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"receipt is outside repository: {path}") from exc


def _collect_refs(value: object) -> list[str]:
    refs: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"evidenceRefs", "refs"} and isinstance(child, list):
                refs.extend(item for item in child if isinstance(item, str))
            elif key in {"ref", "path", "sourceRef", "standardRef", "calibrationReceiptRef"} and isinstance(child, str):
                # Only path-like repository refs are useful to this projection.
                if child.endswith(".json") or child.startswith("eval/") or child.startswith("runs/"):
                    refs.append(child)
            else:
                refs.extend(_collect_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_collect_refs(child))
    elif isinstance(value, str) and (value.endswith(".json") or value.startswith("eval/") or value.startswith("runs/")):
        refs.append(value)
    return _dedupe(refs)


def _json_refs(value: object, repo_root: Path) -> list[str]:
    result: list[str] = []
    for ref in _collect_refs(value):
        path = (repo_root / ref).resolve()
        if path.suffix != ".json" or not path.is_file():
            continue
        # Receipts are intentionally restricted to the checked-in interview
        # evidence tree.  Source code refs remain in the ledger, not this data
        # projection.
        if not path.is_relative_to(METRICS_DIR.resolve()):
            continue
        result.append(_relative_ref(path, repo_root))
    return _dedupe(result)


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _build_receipt_index(repo_root: Path) -> tuple[dict[str, list[tuple[str, dict[str, Any]]]], list[tuple[str, dict[str, Any], str]]]:
    """Index run identities while retaining the relative receipt ref."""

    identity_index: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    all_receipts: list[tuple[str, dict[str, Any], str]] = []
    if not RUNS_DIR.is_dir():
        return identity_index, all_receipts
    for path in sorted(RUNS_DIR.glob("*.json")):
        raw = _load_json(path)
        if not isinstance(raw, dict):
            continue
        ref = _relative_ref(path, repo_root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        all_receipts.append((ref, raw, text))
        identities: list[str] = []
        for key in ("runId", "sourceRunId", "trialId", "jobId"):
            value = raw.get(key)
            if isinstance(value, str):
                identities.append(value)
        runtime = raw.get("runtimeCostReceipt")
        if isinstance(runtime, Mapping):
            source_ref = runtime.get("sourceRef")
            if isinstance(source_ref, str):
                identities.append(source_ref.removeprefix("runtime-cost:"))
        for identity in _dedupe(identities):
            identity_index.setdefault(identity, []).append((ref, raw))
    return identity_index, all_receipts


def _stage_receipts(
    stage_run_id: str,
    refs: Iterable[str],
    *,
    repo_root: Path,
    identity_index: Mapping[str, list[tuple[str, dict[str, Any]]]],
    all_receipts: list[tuple[str, dict[str, Any], str]],
) -> list[tuple[str, dict[str, Any]]]:
    selected: dict[str, dict[str, Any]] = {}
    for ref in refs:
        path = (repo_root / ref).resolve()
        raw = _load_json(path)
        if isinstance(raw, dict):
            selected[_relative_ref(path, repo_root)] = raw
    for ref, raw in identity_index.get(stage_run_id, []):
        selected[ref] = raw
    # Do not search arbitrary receipt bodies for the run id.  Historical
    # calibration/preflight files mention many run ids in prose and would
    # otherwise be mistaken for evidence for this exact stage.  Every current
    # stage has either an endpoint binding or a matching historical experiment
    # side above; absence is intentionally represented as unknown.
    return [(ref, selected[ref]) for ref in sorted(selected)]


def _metrics_for_stage(
    experiment: Mapping[str, Any],
    stage: Mapping[str, Any],
    all_experiments: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    """Merge the stage row with its exact experiment endpoint when available."""

    merged: dict[str, Any] = {}
    matched: Mapping[str, Any] | None = None
    stage_run_id = stage.get("runId")
    candidates_in_order = [experiment] + [candidate for candidate in all_experiments if candidate is not experiment]
    if isinstance(stage_run_id, str):
        for candidate in candidates_in_order:
            for side in ("baseline", "candidate"):
                run = candidate.get(side)
                if isinstance(run, Mapping) and run.get("runId") == stage_run_id:
                    values = run.get("metrics")
                    if isinstance(values, Mapping):
                        merged.update(values)
                    matched = candidate
                    break
            if matched is not None:
                break
    direct_metrics = stage.get("metrics")
    if isinstance(direct_metrics, Mapping):
        merged.update(direct_metrics)
    for key, value in stage.items():
        if key not in {"stage", "runId", "decision", "metrics"} and _is_number(value):
            merged[key] = value
    return merged, matched


def _raw_task_counts(raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> tuple[int, int] | None:
    for _, raw in raw_receipts:
        for container in (raw.get("lane"), raw):
            if not isinstance(container, Mapping):
                continue
            tasks = container.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                continue
            statuses = [task.get("taskSucceeded") for task in tasks if isinstance(task, Mapping)]
            if statuses and all(isinstance(value, bool) for value in statuses):
                return sum(statuses), len(statuses)
    return None


def _count_from_rate(rate: object, total: object, *, label: str) -> int | None:
    if not _is_number(rate) or not _is_number(total):
        return None
    total_int = int(total)
    if total_int <= 0:
        return None
    value = float(rate) * total_int
    rounded = round(value)
    if not math.isclose(value, rounded, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError(f"{label} does not resolve to an integer count")
    return int(rounded)


def _primary_pass(
    key: str,
    metrics: Mapping[str, Any],
    raw_receipts: Iterable[tuple[str, Mapping[str, Any]]],
    case_count: int | None,
) -> tuple[dict[str, int] | None, str | None, dict[str, int] | None, list[str]]:
    unknowns: list[str] = []
    raw_counts = _raw_task_counts(raw_receipts)
    if key == "memory":
        gates = (
            metrics.get("curationOk") in (True, 1),
            metrics.get("retrievalPassed") == 1,
            metrics.get("rollbackPassed") == 1,
            metrics.get("replayPassed") == 1,
        )
        if all(value is True for value in gates) and metrics.get("failedRequestCount") == 0:
            return None, None, {"passed": 1, "total": 1}, unknowns
        if any(value is True for value in gates) and metrics.get("failedRequestCount") is not None:
            return None, None, {"passed": 0, "total": 1}, unknowns
        unknowns.append("memory lifecycle gate result is incomplete")
        return None, None, None, unknowns
    # CloudOps retains CA/FA/JRA quality rubrics, but no frozen overall
    # business-task-success numerator.  CA is projected separately below;
    # never promote a CA rate or a case projection's taskSucceeded field into
    # the cross-scenario taskPass metric.
    if key == "cloudops":
        unknowns.append("overall business task success is unavailable; CloudOps CA is reported as a separate rubric")
        return None, None, None, unknowns
    if raw_counts is not None:
        passed, total = raw_counts
        return {"passed": passed, "total": total}, "task", None, unknowns
    if key == "enterpriseops":
        passed = _as_int(metrics.get("taskSuccessCount", _MISSING), label="taskSuccessCount")
        total = _as_int(metrics.get("taskCount", _MISSING), label="taskCount")
        if passed is not None and total is not None:
            return {"passed": passed, "total": total}, "task", None, unknowns
    elif key == "enterprise_rag":
        total = _as_int(metrics.get("agentCaseCount", case_count or _MISSING), label="agentCaseCount")
        passed = _as_int(metrics.get("agentSuccessCount", _MISSING), label="agentSuccessCount")
        if passed is None:
            passed = _count_from_rate(metrics.get("agentSuccessRate", _MISSING), total, label="agentSuccessRate")
        if passed is not None and total is not None:
            return {"passed": passed, "total": total}, "answer_case", None, unknowns
    elif key == "cloudops":
        total = _as_int(metrics.get("caseCount", case_count or _MISSING), label="caseCount")
        passed = _as_int(metrics.get("taskSuccessCount", _MISSING), label="taskSuccessCount")
        if passed is None:
            passed = _count_from_rate(metrics.get("ca", _MISSING), total, label="CA")
        if passed is not None and total is not None:
            return {"passed": passed, "total": total}, "diagnosis_case", None, unknowns
    if key != "memory":
        unknowns.append("primary task pass denominator or numerator is unavailable")
    return None, None, None, unknowns


def _cloudops_ca_pass(metrics: Mapping[str, Any], case_count: int | None) -> dict[str, int] | None:
    """Return the frozen CA rubric count without treating it as task success."""

    total = _as_int(metrics.get("caseCount", case_count or _MISSING), label="caseCount")
    ca = metrics.get("ca", metrics.get("CA", _MISSING))
    passed = _count_from_rate(ca, total, label="CA")
    if passed is None or total is None:
        return None
    return {"passed": passed, "total": total}


def _cost_with_source(
    metrics: Mapping[str, Any],
    raw_receipts: Iterable[tuple[str, Mapping[str, Any]]],
) -> tuple[Decimal | None, str | None]:
    # A bound Runtime receipt is the authoritative source for current cost:
    # it reconciles the complete assistant-turn usage, including intermediate
    # tool calls.  Do not silently substitute a last-message usage projection.
    for _, raw in raw_receipts:
        runtime = raw.get("runtimeCostReceipt")
        if isinstance(runtime, Mapping):
            reported = runtime.get("reportedCostUsd")
            if isinstance(reported, Mapping) and reported.get("total") is not None:
                return (
                    _decimal(reported["total"], label="runtimeCostReceipt.reportedCostUsd.total"),
                    "runtimeCostReceipt.reportedCostUsd.total",
                )
            per_model = runtime.get("perModel")
            if isinstance(per_model, list):
                # The Memory pair receipt contains both model totals under one
                # Runtime reconciliation.  Match the exact stage amount from
                # the experiment row; never charge the pair aggregate to one
                # stage or guess from last-message usage.
                metric_amounts: list[Decimal] = []
                for key in _COST_KEYS:
                    value = metrics.get(key, _MISSING)
                    if value is not _MISSING and value is not None:
                        metric_amounts.append(_decimal(value, label=key))
                nested_totals: list[Decimal] = []
                for item in per_model:
                    if not isinstance(item, Mapping):
                        continue
                    item_runtime = item.get("runtimeCostReceipt")
                    item_reported = item_runtime.get("reportedCostUsd") if isinstance(item_runtime, Mapping) else None
                    if isinstance(item_reported, Mapping) and item_reported.get("total") is not None:
                        nested_totals.append(
                            _decimal(item_reported["total"], label="runtimeCostReceipt.perModel.reportedCostUsd.total")
                        )
                matches = [total for total in nested_totals if total in metric_amounts]
                if len(matches) == 1:
                    return matches[0], "runtimeCostReceipt.perModel.reportedCostUsd.total"
                if len(nested_totals) == 1:
                    return nested_totals[0], "runtimeCostReceipt.perModel.reportedCostUsd.total"
            aggregate = runtime.get("aggregate")
            if (
                isinstance(aggregate, Mapping)
                and not isinstance(per_model, list)
                and aggregate.get("totalCostUsd") is not None
            ):
                return (
                    _decimal(aggregate["totalCostUsd"], label="runtimeCostReceipt.aggregate.totalCostUsd"),
                    "runtimeCostReceipt.aggregate.totalCostUsd",
                )
    for _, raw in raw_receipts:
        estimate = raw.get("estimate")
        if isinstance(estimate, Mapping) and estimate.get("totalCostUsd") is not None:
            return _decimal(estimate["totalCostUsd"], label="estimate.totalCostUsd"), "estimate.totalCostUsd"
    for key in _COST_KEYS:
        value = metrics.get(key, _MISSING)
        if value is not _MISSING and value is not None:
            return _decimal(value, label=key), f"experiment.metrics.{key}"
    return None, None


def _cost(metrics: Mapping[str, Any], raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> Decimal | None:
    """Compatibility wrapper for focused callers that only need the amount."""

    amount, _ = _cost_with_source(metrics, raw_receipts)
    return amount


def _elapsed(metrics: Mapping[str, Any], raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> float | int | None:
    for key in _ELAPSED_KEYS:
        value = metrics.get(key, _MISSING)
        if value is not _MISSING and value is not None:
            return _number(value, label=key)
    for _, raw in raw_receipts:
        signals = raw.get("signals")
        if isinstance(signals, Mapping) and signals.get("elapsedMs") is not None:
            return _number(signals["elapsedMs"], label="signals.elapsedMs")
        lane = raw.get("lane")
        if isinstance(lane, Mapping) and lane.get("latencyMs") is not None:
            return _number(lane["latencyMs"], label="lane.latencyMs")
        for key in ("elapsedMs", "latencyMs"):
            if raw.get(key) is not None:
                return _number(raw[key], label=key)
    return None


def _failed_hard_gates(metrics: Mapping[str, Any], raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> list[str]:
    result: list[str] = []
    value = metrics.get("failedHardGates")
    if isinstance(value, list):
        result.extend(item for item in value if isinstance(item, str))
    if metrics.get("citationHardGatePassed") == 0:
        result.append("citationHardGate")
    for _, raw in raw_receipts:
        value = raw.get("failedHardGates")
        if isinstance(value, list):
            result.extend(item for item in value if isinstance(item, str))
        for container in (raw.get("agenticResult"), raw.get("resultsByLane")):
            if isinstance(container, Mapping):
                result.extend(_find_string_list(container, "failedHardGates"))
    return sorted(set(result))


def _find_string_list(value: object, key: str) -> list[str]:
    result: list[str] = []
    if isinstance(value, Mapping):
        for name, child in value.items():
            if name == key and isinstance(child, list):
                result.extend(item for item in child if isinstance(item, str))
            else:
                result.extend(_find_string_list(child, key))
    elif isinstance(value, list):
        for child in value:
            result.extend(_find_string_list(child, key))
    return result


def _explicit_tool_failures(metrics: Mapping[str, Any], raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> int | None:
    value = metrics.get("failedToolCalls", _MISSING)
    if value is not _MISSING and value is not None:
        return _as_int(value, label="failedToolCalls")
    for _, raw in raw_receipts:
        signals = raw.get("signals")
        if isinstance(signals, Mapping) and signals.get("failedToolCalls") is not None:
            return _as_int(signals["failedToolCalls"], label="signals.failedToolCalls")
        lane = raw.get("lane")
        if isinstance(lane, Mapping) and lane.get("failedToolCalls") is not None:
            return _as_int(lane["failedToolCalls"], label="lane.failedToolCalls")
    if metrics.get("toolSuccessRate") == 1.0:
        return 0
    if metrics.get("toolCalls") == 0:
        return 0
    return None


def _explicit_request_failures(metrics: Mapping[str, Any], raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> int | None:
    value = metrics.get("failedRequestCount", _MISSING)
    if value is not _MISSING and value is not None:
        return _as_int(value, label="failedRequestCount")
    for _, raw in raw_receipts:
        runtime = raw.get("runtimeCostReceipt")
        if isinstance(runtime, Mapping) and runtime.get("failedRequestCount") is not None:
            return _as_int(runtime["failedRequestCount"], label="runtimeCostReceipt.failedRequestCount")
        aggregate = raw.get("aggregate")
        if isinstance(aggregate, Mapping) and aggregate.get("failedRequestCount") is not None:
            return _as_int(aggregate["failedRequestCount"], label="aggregate.failedRequestCount")
    # A completed runtime/evaluation receipt with a complete usage receipt is
    # positive evidence that no Provider request failed in that run.  This is
    # deliberately narrower than treating an absent audit field as zero.
    saw_complete_runtime = False
    saw_request_count = False
    for _, raw in raw_receipts:
        status = str(raw.get("status") or "").lower()
        runtime = raw.get("runtimeCostReceipt")
        if status in {"completed", "passed", "completed_with_post_terminal_projection_failure"}:
            saw_complete_runtime = True
        if isinstance(runtime, Mapping):
            request_count = runtime.get("requestCount")
            if isinstance(request_count, int) and request_count > 0:
                saw_request_count = True
    if saw_complete_runtime and saw_request_count:
        return 0
    return None


def _runtime_failures(raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> int:
    count = 0
    for _, raw in raw_receipts:
        failed = False
        status = raw.get("status")
        if isinstance(status, str) and "fail" in status.lower():
            failed = True
        outer = raw.get("evidence")
        if isinstance(outer, Mapping):
            outer_status = outer.get("outerReportStatus")
            if isinstance(outer_status, str) and "fail" in outer_status.lower():
                failed = True
        if raw.get("runtimeFailureCategory"):
            failed = True
        if raw.get("errorType"):
            failed = True
        if failed:
            # Several fields can describe the same terminal boundary in one
            # receipt (for example status plus outerReportStatus).  Count the
            # receipt once so severe errors remain additive across receipts,
            # not duplicated by projections of one failure.
            count += 1
    return count


def _failure_projection(
    key: str,
    metrics: Mapping[str, Any],
    raw_receipts: Iterable[tuple[str, Mapping[str, Any]]],
    task_pass: Mapping[str, int] | None,
    unknowns: list[str],
) -> dict[str, Any]:
    tool_failures = _explicit_tool_failures(metrics, raw_receipts)
    request_failures = _explicit_request_failures(metrics, raw_receipts)
    runtime_failures = _runtime_failures(raw_receipts)
    # Memory has no Tool contract in this pair; report that component as zero
    # only because the lifecycle receipt has an explicit request count and no
    # Tool lane.  Other missing components remain unknown.
    if key == "memory" and tool_failures is None:
        tool_failures = 0
    if tool_failures is None:
        unknowns.append("failed Tool-call count is unavailable")
    if request_failures is None:
        unknowns.append("failed Provider-request count is unavailable")
    execution_signals: int | None
    if tool_failures is None or request_failures is None:
        execution_signals = None
        unknowns.append("execution failure signal count cannot be closed without all failure components")
    else:
        # This is an additive signal count.  One underlying event can appear
        # in more than one layer, so it must not be presented as a unique
        # error-event or business-severity count.
        execution_signals = tool_failures + request_failures + runtime_failures
    return {
        "executionFailureSignalDefinition": "Additive explicit Tool, Provider-request, and Runtime failure signals; cross-layer overlap is possible and this is not a business-severity count",
        "executionFailureSignalCount": execution_signals,
        "severeBusinessErrorDefinition": "Unknown: no frozen business-severity rubric is recorded for these scenarios",
        "severeBusinessErrorCount": None,
        "failedToolCalls": tool_failures,
        "failedRequestCount": request_failures,
        "runtimeFailureCount": runtime_failures,
        "taskFailureCount": None if task_pass is None else task_pass["total"] - task_pass["passed"],
        "failedHardGates": _failed_hard_gates(metrics, raw_receipts),
    }


def _judge_projection(
    key: str,
    raw_receipts: Iterable[tuple[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    runtime_calls: list[int] = []
    retained_judgments: list[int] = []
    offline = False
    refs: list[str] = []
    for ref, raw in raw_receipts:
        refs.append(ref)
        for name in _JUDGE_KEYS:
            if raw.get(name) is not None:
                value = _as_int(raw[name], label=name)
                if value is not None:
                    runtime_calls.append(value)
        source = raw.get("sourceEvidence")
        if isinstance(source, Mapping):
            sufficiency = source.get("evidenceSufficiency")
            if isinstance(sufficiency, Mapping) and sufficiency.get("judgeJudgmentCount") is not None:
                value = _as_int(sufficiency["judgeJudgmentCount"], label="judgeJudgmentCount")
                if value is not None:
                    retained_judgments.append(value)
        comparison = raw.get("qualityComparability")
        if isinstance(comparison, Mapping) and comparison.get("semanticJudgeReusedNotRerun") is True:
            offline = True
        boundary = raw.get("claimBoundary")
        if isinstance(boundary, list) and any("offline rescore" in str(item).lower() for item in boundary):
            offline = True
    if key != "enterprise_rag" and not runtime_calls and not retained_judgments:
        return {
            "kind": "not_applicable_deterministic_verifier",
            "runtimeCalls": 0,
            "retainedJudgmentCount": 0,
            "offlineRescore": False,
            "receiptRefs": [],
        }
    if not runtime_calls and not retained_judgments:
        return {
            "kind": "unknown",
            "runtimeCalls": None,
            "retainedJudgmentCount": None,
            "offlineRescore": None,
            "receiptRefs": sorted(set(refs)),
        }
    return {
        "kind": "frozen_judge_evidence",
        "runtimeCalls": sum(runtime_calls) if runtime_calls else 0,
        "retainedJudgmentCount": sum(retained_judgments) if retained_judgments else 0,
        "offlineRescore": offline,
        "receiptRefs": sorted(set(refs)),
    }


def _provider_bill_available(metrics: Mapping[str, Any], raw_receipts: Iterable[tuple[str, Mapping[str, Any]]]) -> bool | None:
    if metrics.get("providerBillAvailable") is not None:
        return bool(metrics["providerBillAvailable"])
    observed: list[bool] = []
    for _, raw in raw_receipts:
        billing = raw.get("billing")
        if isinstance(billing, Mapping) and billing.get("status") is not None:
            observed.append(str(billing["status"]).lower() not in {"not_provided", "unavailable"})
    return observed[0] if observed and all(item == observed[0] for item in observed) else (None if not observed else False)


def _stage_projection(
    key: str,
    experiment: Mapping[str, Any],
    stage: Mapping[str, Any],
    all_experiments: list[Mapping[str, Any]],
    *,
    repo_root: Path,
    identity_index: Mapping[str, list[tuple[str, dict[str, Any]]]],
    all_receipts: list[tuple[str, dict[str, Any], str]],
) -> dict[str, Any]:
    metrics, matched_experiment = _metrics_for_stage(experiment, stage, all_experiments)
    stage_run_id = str(stage.get("runId") or "")
    refs: list[str] = []
    # Bind receipts to the exact stage endpoint.  Loading every receipt from
    # the parent experiment would repeat the frozen Judge evidence for every
    # stage and would make investment counts look larger than they are.
    for owner in (experiment, matched_experiment):
        if not isinstance(owner, Mapping):
            continue
        for side in ("baseline", "candidate"):
            binding = owner.get(side)
            if isinstance(binding, Mapping) and binding.get("runId") == stage_run_id:
                refs.extend(_json_refs(binding, repo_root))
    receipts = _stage_receipts(
        stage_run_id,
        refs,
        repo_root=repo_root,
        identity_index=identity_index,
        all_receipts=all_receipts,
    )
    unknowns: list[str] = []
    task_pass, task_unit, lifecycle_pass, pass_unknowns = _primary_pass(
        key,
        metrics,
        receipts,
        _as_int(experiment.get("dataset", {}).get("caseCount", _MISSING), label="dataset.caseCount")
        if isinstance(experiment.get("dataset"), Mapping)
        else None,
    )
    unknowns.extend(pass_unknowns)
    case_count = (
        _as_int(experiment.get("dataset", {}).get("caseCount", _MISSING), label="dataset.caseCount")
        if isinstance(experiment.get("dataset"), Mapping)
        else None
    )
    ca_pass = _cloudops_ca_pass(metrics, case_count) if key == "cloudops" else None
    cost, cost_source = _cost_with_source(metrics, receipts)
    elapsed = _elapsed(metrics, receipts)
    if cost is None:
        unknowns.append("apiCostUsd is unavailable")
    if elapsed is None:
        unknowns.append("elapsed time is unavailable or was not remeasured for this receipt")
    failure = _failure_projection(key, metrics, receipts, task_pass, unknowns)
    result: dict[str, Any] = {
        "stage": stage.get("stage"),
        "runId": stage_run_id or None,
        "decision": stage.get("decision"),
        "taskPass": task_pass,
        "taskPassUnit": task_unit,
        "caPass": ca_pass,
        "caPassUnit": "cause_identification_case" if key == "cloudops" else None,
        "caPassRubric": "CA" if key == "cloudops" else None,
        "lifecyclePass": lifecycle_pass,
        "fixtureCaseCount": _as_int(experiment.get("dataset", {}).get("caseCount", _MISSING), label="dataset.caseCount")
        if key == "memory" and isinstance(experiment.get("dataset"), Mapping)
        else None,
        "costUsd": None if cost is None else _money(cost),
        "costSource": cost_source,
        "costPerSuccessfulTaskUsd": None,
        "costPerSuccessfulCaseUsd": None,
        "costPerSuccessfulCaseDefinition": (
            "Cost per CA-passed cause-identification case; this is not complete business task success."
            if key == "cloudops"
            else None
        ),
        "costPerSuccessfulLifecycleUsd": None,
        "elapsedMs": elapsed,
        "providerBillAvailable": _provider_bill_available(metrics, receipts),
        **failure,
        "judge": _judge_projection(key, receipts),
        "evidenceRefs": [
            {"file": ref, "sha256": _sha256_file((repo_root / ref).resolve())}
            for ref in sorted(set(ref for ref, _ in receipts))
            if (repo_root / ref).resolve().is_file()
        ],
        "unknowns": sorted(set(unknowns)),
    }
    if cost is not None and task_pass is not None and task_pass["passed"] > 0:
        with localcontext() as context:
            context.prec = 28
            result["costPerSuccessfulTaskUsd"] = _money(cost / Decimal(task_pass["passed"]))
    elif key != "memory":
        result["unknowns"].append("cost per successful task requires both cost and successful-task count")
    if cost is not None and ca_pass is not None and ca_pass["passed"] > 0:
        with localcontext() as context:
            context.prec = 28
            result["costPerSuccessfulCaseUsd"] = _money(cost / Decimal(ca_pass["passed"]))
    if cost is not None and lifecycle_pass is not None and lifecycle_pass["passed"] > 0:
        result["costPerSuccessfulLifecycleUsd"] = _money(cost / Decimal(lifecycle_pass["passed"]))
    return result


def _attempt_summary(
    experiment: Mapping[str, Any],
    *,
    key: str,
    repo_root: Path,
    identity_index: Mapping[str, list[tuple[str, dict[str, Any]]]],
    all_receipts: list[tuple[str, dict[str, Any], str]],
    all_experiments: list[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate = experiment.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    run = {"runId": candidate.get("runId"), "metrics": candidate.get("metrics", {})}
    stage = {
        "stage": "candidate",
        "runId": run.get("runId"),
        "decision": experiment.get("comparison", {}).get("decision") if isinstance(experiment.get("comparison"), Mapping) else None,
    }
    projected = _stage_projection(
        key,
        experiment,
        stage,
        all_experiments,
        repo_root=repo_root,
        identity_index=identity_index,
        all_receipts=all_receipts,
    )
    return {
        "experimentId": experiment.get("id"),
        "status": experiment.get("status"),
        "decision": stage.get("decision"),
        "datasetId": experiment.get("dataset", {}).get("id") if isinstance(experiment.get("dataset"), Mapping) else None,
        "taskPass": projected["taskPass"],
        "caPass": projected["caPass"],
        "caPassUnit": projected["caPassUnit"],
        "caPassRubric": projected["caPassRubric"],
        "costUsd": projected["costUsd"],
        "costPerSuccessfulTaskUsd": projected["costPerSuccessfulTaskUsd"],
        "costPerSuccessfulCaseUsd": projected["costPerSuccessfulCaseUsd"],
        "elapsedMs": projected["elapsedMs"],
        "executionFailureSignalCount": projected["executionFailureSignalCount"],
        "severeBusinessErrorCount": projected["severeBusinessErrorCount"],
        "failedToolCalls": projected["failedToolCalls"],
        "failedHardGates": projected["failedHardGates"],
        "reason": (experiment.get("comparison", {}).get("decisionReason")
                   if isinstance(experiment.get("comparison"), Mapping)
                   else None),
        "evidenceRefs": projected["evidenceRefs"],
    }


def _optimization_investment(
    key: str,
    current: Mapping[str, Any],
    related: list[Mapping[str, Any]],
    stages: list[Mapping[str, Any]],
    *,
    repo_root: Path,
    identity_index: Mapping[str, list[tuple[str, dict[str, Any]]]],
    all_receipts: list[tuple[str, dict[str, Any], str]],
    all_experiments: list[Mapping[str, Any]],
) -> dict[str, Any]:
    failed = []
    for experiment in related:
        comparison = experiment.get("comparison")
        decision = comparison.get("decision") if isinstance(comparison, Mapping) else None
        status = str(experiment.get("status") or "")
        if status in {"rejected", "diagnostic", "open_gap", "blocked"} or str(decision).startswith(("reject", "diagnostic", "open_gap")):
            failed.append(
                _attempt_summary(
                    experiment,
                    key=key,
                    repo_root=repo_root,
                    identity_index=identity_index,
                    all_receipts=all_receipts,
                    all_experiments=all_experiments,
                )
            )
    current_search = current.get("optimizationContract", {}).get("candidateSearchSpace", [])
    candidate_search = []
    if isinstance(current_search, list):
        for item in current_search:
            if not isinstance(item, Mapping):
                continue
            candidate_search.append({
                "axis": item.get("axis"),
                "candidatesEvaluated": item.get("candidatesEvaluated"),
                "values": item.get("values"),
            })
    # Sum unique checked-in cost receipts from the full same-vertical history;
    # this is observed evaluation spend, never the cost of optimizer/engineering
    # work.  Shared receipts are counted once.
    cost_refs: list[str] = []
    for experiment in related:
        cost_refs.extend(ref for ref in _json_refs(experiment, repo_root) if "agent-lab-cost" in ref)
    observed_total: Decimal = Decimal("0")
    missing_cost_experiments: list[str] = []
    cost_receipts = []
    for ref in sorted(set(cost_refs)):
        raw = _load_json((repo_root / ref).resolve())
        amount: Decimal | None = None
        if isinstance(raw, Mapping):
            estimate = raw.get("estimate")
            if isinstance(estimate, Mapping) and estimate.get("totalCostUsd") is not None:
                amount = _decimal(estimate["totalCostUsd"], label="estimate.totalCostUsd")
        if amount is None:
            continue
        cost_receipts.append({"file": ref, "sha256": _sha256_file((repo_root / ref).resolve()), "costUsd": _money(amount)})
        observed_total += amount
    for experiment in related:
        experiment_refs = [ref for ref in _json_refs(experiment, repo_root) if "agent-lab-cost" in ref]
        if not experiment_refs:
            missing_cost_experiments.append(str(experiment.get("id")))
    current_stage_rejects = sum(1 for stage in stages if str(stage.get("decision") or "").startswith("reject"))
    failure_receipts = _failure_receipts(related, repo_root)
    return {
        "currentStageCount": len(stages),
        "currentCandidateCount": max(0, len(stages) - 1),
        "currentRejectedStageCount": current_stage_rejects,
        "relatedExperimentCount": len(related),
        "candidateRecordCount": sum(1 for experiment in related if isinstance(experiment.get("candidate"), Mapping)),
        "rejectedOrDiagnosticRecordCount": len(failed),
        "sameDatasetExperimentCount": sum(
            1
            for experiment in related
            if isinstance(experiment.get("dataset"), Mapping)
            and experiment.get("dataset", {}).get("id") == current.get("dataset", {}).get("id")
        ),
        "candidateSearchSpace": candidate_search,
        "failedAttempts": failed,
        "failureReceiptCount": len(failure_receipts),
        "failureReceipts": failure_receipts,
        "observedEvaluationCostUsd": None if missing_cost_experiments else _money(observed_total),
        "observedEvaluationCostKnownSubsetUsd": _money(observed_total),
        "observedEvaluationCostStatus": "incomplete" if missing_cost_experiments else "complete",
        "observedEvaluationCostMissingExperimentIds": sorted(set(missing_cost_experiments)),
        "observedEvaluationCostAuthority": "unique retained Runtime-reconciled estimates; not optimizer or engineering cost; total stays unknown when any related attempt lacks a receipt",
        "observedCostReceiptCount": len(cost_receipts),
        "observedCostReceipts": cost_receipts,
        "optimizerCostUsd": None,
        "optimizerCostStatus": "unknown",
        "optimizerCostGap": "No independent optimizer, implementation, or Judge engineering cost receipt exists in the current ledgers.",
    }


def _failure_receipts(related: Iterable[Mapping[str, Any]], repo_root: Path) -> list[dict[str, str]]:
    """Retain explicit failed receipt boundaries without treating rejects as runtime failures."""

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for experiment in related:
        for ref in _json_refs(experiment, repo_root):
            if ref in seen:
                continue
            seen.add(ref)
            raw = _load_json((repo_root / ref).resolve())
            if not isinstance(raw, Mapping):
                continue
            statuses: list[str] = []
            for key in ("status", "errorType"):
                value = raw.get(key)
                if isinstance(value, str) and ("fail" in value.lower() or key == "errorType"):
                    statuses.append(f"{key}={value}")
            evidence = raw.get("evidence")
            if isinstance(evidence, Mapping):
                value = evidence.get("outerReportStatus")
                if isinstance(value, str) and "fail" in value.lower():
                    statuses.append(f"outerReportStatus={value}")
            if statuses:
                result.append({
                    "file": ref,
                    "sha256": _sha256_file((repo_root / ref).resolve()),
                    "failure": "; ".join(sorted(set(statuses))),
                })
    return sorted(result, key=lambda item: item["file"])


def _break_even(stages: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not stages:
        return {"status": "unknown", "reuseCount": None, "reason": "no comparable stages"}
    baseline = stages[0]
    candidate = stages[-1]
    savings: str | None = None
    if baseline.get("costUsd") is not None and candidate.get("costUsd") is not None:
        before = _decimal(baseline["costUsd"], label="baseline costUsd")
        after = _decimal(candidate["costUsd"], label="candidate costUsd")
        savings = _money(before - after)
    return {
        "status": "unknown",
        "reuseCount": None,
        "perEquivalentRunSavingsUsd": savings,
        "reason": "Break-even requires an independent optimizer/engineering investment and a production reuse volume; neither is recorded.",
    }


def _validation_boundary(experiment: Mapping[str, Any]) -> dict[str, Any]:
    comparison = experiment.get("comparison")
    boundary = comparison.get("validationBoundary", {}) if isinstance(comparison, Mapping) else {}
    result = {
        key: value
        for key, value in boundary.items()
        if isinstance(value, (bool, int, float, str))
    }
    dataset = experiment.get("dataset")
    if isinstance(dataset, Mapping):
        result.setdefault("heldOutConsumed", dataset.get("heldOutConsumed"))
        result.setdefault("split", dataset.get("split"))
    return result


def _ledger_metric_ids(
    key: str,
    current: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> list[str]:
    refs = set(_collect_refs(current))
    result = []
    for metric in ledger.get("metrics", []) if isinstance(ledger.get("metrics"), list) else []:
        if not isinstance(metric, Mapping):
            continue
        metric_refs = set(_collect_refs(metric.get("evidenceRefs", [])))
        metric_id = str(metric.get("id") or "")
        token_match = {
            "enterpriseops": "enterpriseops",
            "enterprise_rag": "knowledge.enterprise",
            "cloudops": "cloudops",
            "memory": "memory",
        }[key]
        if refs & metric_refs or token_match in metric_id.lower():
            result.append(metric_id)
    return sorted(set(result))


def _project_scenario(
    key: str,
    current: Mapping[str, Any],
    all_experiments: list[Mapping[str, Any]],
    ledger: Mapping[str, Any],
    *,
    repo_root: Path,
    identity_index: Mapping[str, list[tuple[str, dict[str, Any]]]],
    all_receipts: list[tuple[str, dict[str, Any], str]],
) -> dict[str, Any]:
    comparison = current.get("comparison")
    if not isinstance(comparison, Mapping):
        raise ValueError(f"{current.get('id')} has no comparison")
    chain = comparison.get("stageChain")
    if not isinstance(chain, list) or not chain:
        chain = [
            {"stage": "baseline", "runId": current.get("baseline", {}).get("runId"), "decision": "baseline"},
            {"stage": "candidate", "runId": current.get("candidate", {}).get("runId"), "decision": comparison.get("decision")},
        ]
    stages = [
        _stage_projection(
            key,
            current,
            stage,
            all_experiments,
            repo_root=repo_root,
            identity_index=identity_index,
            all_receipts=all_receipts,
        )
        for stage in chain
        if isinstance(stage, Mapping)
    ]
    if len(stages) < 2:
        raise ValueError(f"{current.get('id')} does not have a baseline and candidate stage")
    related = [
        experiment
        for experiment in all_experiments
        if experiment.get("vertical") == current.get("vertical")
    ]
    investment = _optimization_investment(
        key,
        current,
        related,
        stages,
        repo_root=repo_root,
        identity_index=identity_index,
        all_receipts=all_receipts,
        all_experiments=all_experiments,
    )
    current_unknowns = sorted({unknown for stage in stages for unknown in stage.get("unknowns", [])})
    if current.get("status") != "kept" or comparison.get("decision") != "keep":
        current_unknowns.append("current candidate is not a Keep decision")
    return {
        "key": key,
        "experimentId": current.get("id"),
        "vertical": current.get("vertical"),
        "status": current.get("status"),
        "dataset": {
            "id": current.get("dataset", {}).get("id") if isinstance(current.get("dataset"), Mapping) else None,
            "split": current.get("dataset", {}).get("split") if isinstance(current.get("dataset"), Mapping) else None,
            "caseCount": current.get("dataset", {}).get("caseCount") if isinstance(current.get("dataset"), Mapping) else None,
            "unit": current.get("dataset", {}).get("unit") if isinstance(current.get("dataset"), Mapping) else None,
            "heldOutConsumed": current.get("dataset", {}).get("heldOutConsumed") if isinstance(current.get("dataset"), Mapping) else None,
            "manifestSha256": current.get("dataset", {}).get("manifestSha256") if isinstance(current.get("dataset"), Mapping) else None,
        },
        "decision": comparison.get("decision"),
        "stages": stages,
        "baseline": stages[0],
        "candidate": stages[-1],
        "validationBoundary": _validation_boundary(current),
        "candidateAwareLimitations": {
            "candidateAware": comparison.get("validationBoundary", {}).get("candidateAware") if isinstance(comparison.get("validationBoundary"), Mapping) else None,
            "candidateBlind": comparison.get("validationBoundary", {}).get("candidateBlind") if isinstance(comparison.get("validationBoundary"), Mapping) else None,
            "heldOutOpened": comparison.get("validationBoundary", {}).get("heldOutOpened") if isinstance(comparison.get("validationBoundary"), Mapping) else current.get("dataset", {}).get("heldOutConsumed") is True,
            "unbiasedPromotionClaimAllowed": comparison.get("validationBoundary", {}).get("unbiasedPromotionClaimAllowed") if isinstance(comparison.get("validationBoundary"), Mapping) else None,
        },
        "judge": {
            "runtimeCalls": sum(stage["judge"]["runtimeCalls"] for stage in stages if isinstance(stage["judge"].get("runtimeCalls"), int)),
            "retainedJudgmentCount": sum(stage["judge"]["retainedJudgmentCount"] for stage in stages if isinstance(stage["judge"].get("retainedJudgmentCount"), int)),
            "offlineRescore": any(stage["judge"].get("offlineRescore") is True for stage in stages),
            "stageCount": len(stages),
        },
        "optimizationInvestment": investment,
        "breakEven": _break_even(stages),
        "ledgerMetricIds": _ledger_metric_ids(key, current, ledger),
        "unknowns": sorted(set(current_unknowns)),
        "evidenceRefs": [
            {"file": ref, "sha256": _sha256_file((repo_root / ref).resolve())}
            for ref in _json_refs(current, repo_root)
        ],
    }


def project(
    experiments: Mapping[str, Any],
    ledger: Mapping[str, Any],
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    if not isinstance(experiments, Mapping) or not isinstance(experiments.get("experiments"), list):
        raise ValueError("experiment ledger must contain an experiments list")
    if not isinstance(ledger, Mapping) or not isinstance(ledger.get("metrics"), list):
        raise ValueError("evidence ledger must contain a metrics list")
    all_experiments = [item for item in experiments["experiments"] if isinstance(item, Mapping)]
    identity_index, all_receipts = _build_receipt_index(repo_root)
    scenarios = []
    for key, experiment_id, vertical in CURRENT_EXPERIMENTS:
        matches = [item for item in all_experiments if item.get("id") == experiment_id]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one current experiment: {experiment_id}")
        current = matches[0]
        if current.get("vertical") != vertical or current.get("projectionState") != "current":
            raise ValueError(f"current experiment is not bound to the expected current projection: {experiment_id}")
        scenarios.append(
            _project_scenario(
                key,
                current,
                all_experiments,
                ledger,
                repo_root=repo_root,
                identity_index=identity_index,
                all_receipts=all_receipts,
            )
        )
    experiment_path = repo_root / "eval/interview-metrics/agent-experiments.v1.json"
    ledger_path = repo_root / "eval/interview-metrics/evidence-ledger.v1.json"
    return {
        "schemaVersion": "paw.optimization-metrics-summary.v1",
        "generatedFrom": "agent-experiments.v1.json + evidence-ledger.v1.json + referenced JSON receipts",
        "providerCallsMade": False,
        "sourceFiles": [
            {"file": _relative_ref(experiment_path, repo_root), "sha256": _sha256_file(experiment_path)},
            {"file": _relative_ref(ledger_path, repo_root), "sha256": _sha256_file(ledger_path)},
        ],
        "definitions": {
            "taskPass": "The scenario's primary frozen unit; RAG uses answer cases, while CloudOps has no frozen overall business-task-success denominator and reports CA as a separate cause-identification-case rubric. Memory reports lifecycle 1/1 separately because no per-task success count is retained.",
            "executionFailureSignal": "An additive count of explicit Tool, Provider-request, and Runtime failure signals. Cross-layer overlap is possible, so it is not a unique error-event or business-severity count.",
            "severeBusinessError": "Unknown for every scenario because no frozen business-severity rubric is recorded; null is preserved.",
            "cost": "Runtime-reconciled estimate or deterministic pricing estimate from the retained receipt; never a Provider bill.",
            "observedEvaluationCost": "Sum of unique retained cost receipts in the same vertical history; it is not optimizer, engineering, or Judge labor cost.",
            "breakEven": "Left unknown until an independent optimizer/engineering investment and a production reuse volume are recorded.",
        },
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiments", type=Path, default=ROOT / "eval/interview-metrics/agent-experiments.v1.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "eval/interview-metrics/evidence-ledger.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    experiments = json.loads(args.experiments.read_text(encoding="utf-8"))
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    result = project(experiments, ledger, repo_root=ROOT)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != encoded:
            raise SystemExit("optimization metric projection differs from source ledgers")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(f"{'Verified' if args.check else 'Exported'} {len(result['scenarios'])} PAW optimization scenarios; no Provider call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
