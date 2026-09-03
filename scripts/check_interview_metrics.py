#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_interview_agent_experiments import validate_agent_experiments


SCHEMA_VERSION = "paw.interview-metrics-ledger.v1"
EVIDENCE_LEVELS = ("E1", "E2", "E3", "E4", "E5", "E6")
CLAIMABLE_STATUSES = frozenset({"headline", "supporting", "diagnostic"})
ALLOWED_STATUSES = CLAIMABLE_STATUSES | frozenset({"blocked", "target"})
ALLOWED_MEASUREMENT_KINDS = frozenset(
    {"deterministic", "ai_estimate", "mixed", "status"}
)
ALLOWED_RUN_OUTCOMES = frozenset({"passed", "failed", "interrupted", "blocked"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _repo_ref_path(ref: str, repo_root: Path) -> Path | None:
    if ref.startswith(("http://", "https://")):
        return None
    raw_path = ref.split("#", 1)[0].strip()
    if not raw_path:
        return None
    return repo_root / raw_path


def _receipt_refs(
    metric_id: str, calculation: Mapping[str, object]
) -> tuple[list[str], list[str]]:
    raw_refs = calculation.get("refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        return [], [f"{metric_id}: receiptCalculation.refs must be non-empty"]
    refs: list[str] = []
    errors: list[str] = []
    for raw_ref in raw_refs:
        if not _non_empty_text(raw_ref):
            errors.append(f"{metric_id}: receiptCalculation.refs contains an empty value")
            continue
        refs.append(str(raw_ref))
    return refs, errors


def _load_receipts(
    metric_id: str, refs: Sequence[str], repo_root: Path
) -> tuple[list[tuple[str, Mapping[str, object]]], list[str]]:
    receipts: list[tuple[str, Mapping[str, object]]] = []
    errors: list[str] = []
    for ref in refs:
        path = _repo_ref_path(ref, repo_root)
        if path is None:
            errors.append(f"{metric_id}: receipt must be a repository path: {ref}")
            continue
        if not path.is_file():
            errors.append(f"{metric_id}: receipt does not exist: {ref}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{metric_id}: receipt is not readable JSON: {ref}: {exc}")
            continue
        if not isinstance(payload, Mapping):
            errors.append(f"{metric_id}: receipt must contain a JSON object: {ref}")
            continue
        receipts.append((ref, payload))
    return receipts, errors


def _compare_receipt_value(
    *,
    metric_id: str,
    field: str,
    expected: object,
    actual: object,
) -> list[str]:
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        matches = abs(float(expected) - float(actual)) < 0.000001
    else:
        matches = expected == actual
    if matches:
        return []
    return [
        f"{metric_id}: {field} must equal receipt-derived {expected}, got {actual}"
    ]


def _validate_workspace_speedup_range(
    metric_id: str,
    values: Mapping[str, object],
    receipts: Sequence[tuple[str, Mapping[str, object]]],
) -> list[str]:
    errors: list[str] = []
    grouped: dict[int, list[float]] = {1_000: [], 5_000: []}
    parity_by_size: dict[int, bool] = {1_000: True, 5_000: True}
    corpus_by_size: dict[int, str] = {}
    for ref, receipt in receipts:
        if receipt.get("schemaVersion") != "paw.workspace-tool-benchmark.v1":
            errors.append(f"{metric_id}: unexpected workspace receipt schema: {ref}")
            continue
        case = _mapping(receipt.get("case"))
        files = case.get("files")
        if files not in grouped:
            errors.append(f"{metric_id}: unsupported workspace receipt size in {ref}: {files}")
            continue
        speedup = receipt.get("p95Speedup")
        if not isinstance(speedup, (int, float)) or isinstance(speedup, bool):
            errors.append(f"{metric_id}: p95Speedup must be numeric in {ref}")
            continue
        grouped[int(files)].append(float(speedup))

        corpus = case.get("corpusSha256")
        if not _non_empty_text(corpus):
            errors.append(f"{metric_id}: corpusSha256 is required in {ref}")
            parity_by_size[int(files)] = False
        elif int(files) in corpus_by_size and corpus_by_size[int(files)] != corpus:
            errors.append(
                f"{metric_id}: corpus checksum drift for files{files}: "
                f"{corpus_by_size[int(files)]} != {corpus}"
            )
            parity_by_size[int(files)] = False
        else:
            corpus_by_size[int(files)] = str(corpus)

        backends = receipt.get("backends")
        checksums: list[str] = []
        if isinstance(backends, list):
            for raw_backend in backends:
                checksum = _mapping(_mapping(raw_backend).get("result")).get(
                    "checksumSha256"
                )
                if _non_empty_text(checksum):
                    checksums.append(str(checksum))
        checksum_parity = len(checksums) >= 2 and len(set(checksums)) == 1
        receipt_parity = receipt.get("parity") is True
        if not receipt_parity or not checksum_parity:
            errors.append(f"{metric_id}: backend result parity failed in {ref}")
            parity_by_size[int(files)] = False

    for files in (1_000, 5_000):
        field = f"files{files}"
        observed = grouped[files]
        claimed = _mapping(values.get(field))
        if not observed:
            errors.append(f"{metric_id}: no valid receipts for {field}")
            continue
        derived = {
            "runCount": len(observed),
            "p95SpeedupMin": round(min(observed), 3),
            "p95SpeedupMax": round(max(observed), 3),
            "checksumParity": parity_by_size[files],
        }
        for key, expected in derived.items():
            errors.extend(
                _compare_receipt_value(
                    metric_id=metric_id,
                    field=f"{field}.{key}",
                    expected=expected,
                    actual=claimed.get(key),
                )
            )
    return errors


def _validate_pi_context_cache(
    metric_id: str,
    values: Mapping[str, object],
    receipts: Sequence[tuple[str, Mapping[str, object]]],
) -> list[str]:
    errors: list[str] = []
    if len(receipts) != 1:
        return [f"{metric_id}: pi_context_cache requires exactly one valid receipt"]
    ref, receipt = receipts[0]
    if receipt.get("schemaVersion") != "rag-ime.pi-context-cache-canary.v1":
        return [f"{metric_id}: unexpected Pi cache receipt schema: {ref}"]
    if receipt.get("status") != "passed_not_installed":
        errors.append(f"{metric_id}: Pi cache receipt did not pass in {ref}")

    raw_turns = receipt.get("stableTurns")
    if not isinstance(raw_turns, list) or len(raw_turns) < 2:
        return errors + [f"{metric_id}: stableTurns must contain cold and warm turns"]
    turns = [_mapping(raw_turn) for raw_turn in raw_turns]
    cold_input = turns[0].get("inputTokens")
    if not isinstance(cold_input, int) or isinstance(cold_input, bool) or cold_input <= 0:
        return errors + [f"{metric_id}: cold inputTokens must be a positive integer"]
    warm_turns = [
        turn
        for turn in turns[1:]
        if isinstance(turn.get("cacheReadTokens"), int)
        and not isinstance(turn.get("cacheReadTokens"), bool)
        and int(turn["cacheReadTokens"]) > 0
    ]
    if len(warm_turns) != len(turns) - 1:
        errors.append(f"{metric_id}: every warm stable turn must report a cache hit")
    warm_inputs = [
        int(turn["inputTokens"])
        for turn in warm_turns
        if isinstance(turn.get("inputTokens"), int)
        and not isinstance(turn.get("inputTokens"), bool)
        and int(turn["inputTokens"]) >= 0
    ]
    cache_reads = [int(turn["cacheReadTokens"]) for turn in warm_turns]
    if len(warm_inputs) != len(warm_turns) or not warm_inputs:
        return errors + [f"{metric_id}: warm inputTokens must be non-negative integers"]
    if len(set(cache_reads)) != 1:
        errors.append(f"{metric_id}: warm stable cacheReadTokens must be identical")

    control = _mapping(receipt.get("changedPrefixControl"))
    control_cache_read = control.get("cacheReadTokens")
    reductions = [((cold_input - value) / cold_input) * 100 for value in warm_inputs]
    derived = {
        "stableTurns": len(turns),
        "warmHitTurns": len(warm_turns),
        "coldInputTokens": cold_input,
        "warmInputTokensMin": min(warm_inputs),
        "warmInputTokensMax": max(warm_inputs),
        "stableCacheReadTokens": cache_reads[0],
        "uncachedInputReductionPercentMin": round(min(reductions), 2),
        "uncachedInputReductionPercentMax": round(max(reductions), 2),
        "changedPrefixControlCacheReadTokens": control_cache_read,
    }
    for field, expected in derived.items():
        errors.extend(
            _compare_receipt_value(
                metric_id=metric_id,
                field=field,
                expected=expected,
                actual=values.get(field),
            )
        )
    return errors


def _validate_rag_validation_selection(
    metric_id: str,
    values: Mapping[str, object],
    receipts: Sequence[tuple[str, Mapping[str, object]]],
) -> list[str]:
    errors: list[str] = []
    if len(receipts) != 1:
        return [
            f"{metric_id}: rag_validation_selection requires exactly one valid receipt"
        ]
    ref, receipt = receipts[0]
    if receipt.get("schemaVersion") != "paw.enterprise-rag-validation-receipt.v1":
        return [f"{metric_id}: unexpected RAG validation receipt schema: {ref}"]
    if receipt.get("status") != "evaluated_not_promoted":
        errors.append(f"{metric_id}: validation receipt is not diagnostic-only")
    if receipt.get("evaluationScope") != "validation-only":
        errors.append(f"{metric_id}: validation receipt scope must be validation-only")
    if receipt.get("heldOutEvaluated") is not False:
        errors.append(
            f"{metric_id}: validation receipt must not contain held-out evaluation"
        )
    if receipt.get("objective") != "ndcgAtK.10":
        errors.append(f"{metric_id}: validation receipt objective must be ndcgAtK.10")
    if receipt.get("decision") != "candidate_selected_not_promoted":
        errors.append(f"{metric_id}: validation receipt must remain unpromoted")

    hashes = _mapping(receipt.get("hashes"))
    required_hashes = (
        "rawFileSha256",
        "reportSha256",
        "selectionReceiptSha256",
        "validationSplitSha256",
        "winnerConfigSha256",
    )
    for field in required_hashes:
        value = hashes.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            errors.append(f"{metric_id}: hashes.{field} must be a lowercase SHA-256")

    hard_gates = receipt.get("hardGates")
    if (
        not isinstance(hard_gates, Mapping)
        or not hard_gates
        or any(value is not True for value in hard_gates.values())
    ):
        errors.append(f"{metric_id}: every validation hard gate must pass")

    sample = _mapping(receipt.get("sample"))
    query_count = sample.get("validationQueryCount")
    candidate_count = sample.get("candidateCount")
    if (
        not isinstance(query_count, int)
        or isinstance(query_count, bool)
        or query_count < 1
    ):
        errors.append(f"{metric_id}: validationQueryCount must be positive")
    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count < 2
    ):
        errors.append(f"{metric_id}: candidateCount must be at least two")

    derived: dict[str, object] = {
        "validationQueryCount": query_count,
        "candidateCount": candidate_count,
        "winnerConfigSha256": hashes.get("winnerConfigSha256"),
    }
    receipt_metrics = _mapping(receipt.get("metrics"))
    for group in ("lexicalFloor", "strongNaiveDense", "winner"):
        observed = _mapping(receipt_metrics.get(group))
        derived_group: dict[str, float] = {}
        for field in ("mrr", "ndcgAt10", "recallAt10"):
            raw_value = observed.get(field)
            if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
                errors.append(f"{metric_id}: metrics.{group}.{field} must be numeric")
                continue
            derived_group[field] = round(float(raw_value), 6)
        derived[group] = derived_group

    for field in ("validationQueryCount", "candidateCount", "winnerConfigSha256"):
        errors.extend(
            _compare_receipt_value(
                metric_id=metric_id,
                field=field,
                expected=derived.get(field),
                actual=values.get(field),
            )
        )
    for group in ("lexicalFloor", "strongNaiveDense", "winner"):
        claimed = _mapping(values.get(group))
        for field, expected in _mapping(derived.get(group)).items():
            errors.extend(
                _compare_receipt_value(
                    metric_id=metric_id,
                    field=f"{group}.{field}",
                    expected=expected,
                    actual=claimed.get(field),
                )
            )
    return errors


def _validate_rag_agent_validation_reject(
    metric_id: str,
    values: Mapping[str, object],
    receipts: Sequence[tuple[str, Mapping[str, object]]],
) -> list[str]:
    errors: list[str] = []
    if len(receipts) != 1:
        return [
            f"{metric_id}: rag_agent_validation_reject requires exactly one valid receipt"
        ]
    ref, receipt = receipts[0]
    if receipt.get("schemaVersion") != "paw.enterprise-rag-agent-validation-reject.v1":
        return [f"{metric_id}: unexpected RAG Agent reject receipt schema: {ref}"]
    expected_boundary = {
        "status": "rejected",
        "evaluationScope": "validation-only",
        "evaluationMode": "answer-only",
        "heldOutEvaluated": False,
        "decision": "reject",
        "formalAcceptanceEligible": False,
        "heldOutGateProduced": False,
        "cleanupPassed": True,
    }
    for field, expected in expected_boundary.items():
        if receipt.get(field) != expected:
            errors.append(
                f"{metric_id}: receipt {field} must equal {expected!r}"
            )

    hashes = _mapping(receipt.get("hashes"))
    for field in (
        "rawFileSha256",
        "reportSha256",
        "promotionFileSha256",
        "promotionReceiptSha256",
        "runtimeContractSha256",
        "caseSetSha256",
    ):
        value = hashes.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            errors.append(f"{metric_id}: hashes.{field} must be a lowercase SHA-256")

    sample = _mapping(receipt.get("sample"))
    answer_case_count = sample.get("answerCaseCount")
    lane_count = sample.get("laneCount")
    if (
        not isinstance(answer_case_count, int)
        or isinstance(answer_case_count, bool)
        or answer_case_count < 1
    ):
        errors.append(f"{metric_id}: answerCaseCount must be positive")
    if (
        not isinstance(lane_count, int)
        or isinstance(lane_count, bool)
        or lane_count < 1
    ):
        errors.append(f"{metric_id}: laneCount must be positive")

    resume = _mapping(receipt.get("resume"))
    if resume.get("resumed") is not True:
        errors.append(f"{metric_id}: receipt must prove a resumed run")
    if resume.get("recoveryFailClosed") is not False:
        errors.append(f"{metric_id}: recovery must complete without a blocked gate")
    integer_fields = (
        "reusedLaneCount",
        "freshLaneCount",
        "interruptedAttemptCount",
        "retryAttemptCount",
        "recoveredOrphanCount",
        "blockedOrphanCount",
    )
    resume_counts: dict[str, int] = {}
    for field in integer_fields:
        value = resume.get(field)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            errors.append(f"{metric_id}: resume.{field} must be non-negative")
        else:
            resume_counts[field] = value
    if isinstance(lane_count, int) and not isinstance(lane_count, bool) and lane_count > 0:
        if (
            resume_counts.get("reusedLaneCount", -1)
            + resume_counts.get("freshLaneCount", -1)
            != lane_count
        ):
            errors.append(f"{metric_id}: reused plus fresh lanes must equal laneCount")
        reused_percent = round(
            resume_counts.get("reusedLaneCount", 0) / lane_count * 100,
            2,
        )
    else:
        reused_percent = None
    if (
        resume_counts.get("recoveredOrphanCount", 0)
        + resume_counts.get("blockedOrphanCount", 0)
        != resume_counts.get("interruptedAttemptCount", -1)
    ):
        errors.append(
            f"{metric_id}: recovered plus blocked orphans must equal interrupted attempts"
        )
    errors.extend(
        _compare_receipt_value(
            metric_id=metric_id,
            field="resume.reusedLanePercent",
            expected=reused_percent,
            actual=resume.get("reusedLanePercent"),
        )
    )

    comparison = _mapping(receipt.get("comparison"))
    if comparison.get("fromLane") != "baseline" or comparison.get("toLane") != "agentic":
        errors.append(f"{metric_id}: comparison must be baseline to agentic")
    latency = _mapping(comparison.get("latencyMs"))
    tools = _mapping(comparison.get("toolCalls"))
    correctness = _mapping(comparison.get("answerJudgeCorrectnessRate"))
    baseline_latency = latency.get("baseline")
    agentic_latency = latency.get("agentic")
    baseline_tools = tools.get("baseline")
    agentic_tools = tools.get("agentic")
    if not isinstance(baseline_latency, (int, float)) or baseline_latency <= 0:
        errors.append(f"{metric_id}: baseline latency must be positive")
        latency_increase = None
    elif not isinstance(agentic_latency, (int, float)) or agentic_latency < 0:
        errors.append(f"{metric_id}: agentic latency must be non-negative")
        latency_increase = None
    else:
        latency_increase = round(
            (float(agentic_latency) - float(baseline_latency))
            / float(baseline_latency)
            * 100,
            2,
        )
    if not isinstance(baseline_tools, int) or isinstance(baseline_tools, bool) or baseline_tools <= 0:
        errors.append(f"{metric_id}: baseline tool calls must be positive")
        tool_increase = None
    elif not isinstance(agentic_tools, int) or isinstance(agentic_tools, bool) or agentic_tools < 0:
        errors.append(f"{metric_id}: agentic tool calls must be non-negative")
        tool_increase = None
    else:
        tool_increase = round((agentic_tools - baseline_tools) / baseline_tools * 100, 2)
    for field, expected, actual in (
        ("comparison.latencyMs.increasePercent", latency_increase, latency.get("increasePercent")),
        ("comparison.toolCalls.increasePercent", tool_increase, tools.get("increasePercent")),
    ):
        errors.extend(
            _compare_receipt_value(
                metric_id=metric_id,
                field=field,
                expected=expected,
                actual=actual,
            )
        )

    derived = {
        "answerCaseCount": answer_case_count,
        "laneCount": lane_count,
        "reusedLaneCount": resume_counts.get("reusedLaneCount"),
        "reusedLanePercent": reused_percent,
        "recoveredOrphanCount": resume_counts.get("recoveredOrphanCount"),
        "blockedOrphanCount": resume_counts.get("blockedOrphanCount"),
        "baselineLatencyMs": baseline_latency,
        "agenticLatencyMs": agentic_latency,
        "agenticLatencyIncreasePercent": latency_increase,
        "baselineToolCalls": baseline_tools,
        "agenticToolCalls": agentic_tools,
        "agenticToolCallIncreasePercent": tool_increase,
        "baselineAnswerJudgeCorrectnessRate": correctness.get("baseline"),
        "agenticAnswerJudgeCorrectnessRate": correctness.get("agentic"),
        "decision": receipt.get("decision"),
    }
    for field, expected in derived.items():
        errors.extend(
            _compare_receipt_value(
                metric_id=metric_id,
                field=field,
                expected=expected,
                actual=values.get(field),
            )
        )
    return errors


def validate_metric_receipt_calculation(
    metric: Mapping[str, object], *, repo_root: Path
) -> list[str]:
    """Recompute claim values from privacy-safe receipts; never trust copied totals."""

    raw_calculation = metric.get("receiptCalculation")
    if raw_calculation is None:
        return []
    metric_id = str(metric.get("id") or "").strip() or "<missing-metric-id>"
    if not isinstance(raw_calculation, Mapping) or not raw_calculation:
        return [f"{metric_id}: receiptCalculation must be a non-empty object"]
    calculation = raw_calculation
    refs, errors = _receipt_refs(metric_id, calculation)
    receipts, load_errors = _load_receipts(metric_id, refs, repo_root)
    errors.extend(load_errors)
    if errors:
        return errors
    values = _mapping(metric.get("values"))
    kind = calculation.get("kind")
    if kind == "workspace_speedup_range":
        return _validate_workspace_speedup_range(metric_id, values, receipts)
    if kind == "pi_context_cache":
        return _validate_pi_context_cache(metric_id, values, receipts)
    if kind == "rag_validation_selection":
        rag_errors = _validate_rag_validation_selection(metric_id, values, receipts)
        if metric.get("status") == "headline":
            rag_errors.append(
                f"{metric_id}: validation-only receipt cannot support headline status"
            )
        return rag_errors
    if kind == "rag_agent_validation_reject":
        rag_errors = _validate_rag_agent_validation_reject(
            metric_id, values, receipts
        )
        if metric.get("status") == "headline":
            rag_errors.append(
                f"{metric_id}: rejected validation receipt cannot support headline status"
            )
        return rag_errors
    return [f"{metric_id}: unsupported receiptCalculation kind: {kind}"]


def validate_interview_metrics(
    payload: Mapping[str, object], *, repo_root: Path | None = None
) -> list[str]:
    errors: list[str] = []
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    source_revision = payload.get("sourceRevision")
    if not _non_empty_text(source_revision):
        errors.append("sourceRevision is required")
    elif repo_root is not None:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(source_revision), "HEAD"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"sourceRevision is not an ancestor of HEAD: {source_revision}")

    levels = payload.get("evidenceLevels")
    if levels != list(EVIDENCE_LEVELS):
        errors.append("evidenceLevels must be exactly E1 through E6")

    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        errors.append("metrics must be a list")
        metrics = []
    metric_ids: set[str] = set()
    for raw_metric in metrics:
        metric = _mapping(raw_metric)
        metric_id = str(metric.get("id") or "").strip() or "<missing-metric-id>"
        if metric_id in metric_ids:
            errors.append(f"duplicate metric id: {metric_id}")
        metric_ids.add(metric_id)

        status = str(metric.get("status") or "")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{metric_id}: unsupported status: {status}")
        level = str(metric.get("evidenceLevel") or "")
        if level not in EVIDENCE_LEVELS:
            errors.append(f"{metric_id}: unsupported evidenceLevel: {level}")
        measurement_kind = str(metric.get("measurementKind") or "")
        if measurement_kind not in ALLOWED_MEASUREMENT_KINDS:
            errors.append(
                f"{metric_id}: unsupported measurementKind: {measurement_kind}"
            )
        if measurement_kind == "ai_estimate" and metric.get("reportedAs") == "deterministic":
            errors.append(
                f"{metric_id}: ai_estimate must not be reportedAs deterministic"
            )

        if repo_root is not None and metric.get("receiptCalculation") is not None:
            errors.extend(
                validate_metric_receipt_calculation(metric, repo_root=repo_root)
            )

        if status not in CLAIMABLE_STATUSES:
            continue
        values = metric.get("values")
        if not isinstance(values, dict) or not values:
            errors.append(f"{metric_id}: values must be a non-empty object")
        sample = _mapping(metric.get("sample"))
        count = sample.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            errors.append(f"{metric_id}: sample.count must be a positive integer")
        if not _non_empty_text(sample.get("unit")):
            errors.append(f"{metric_id}: sample.unit is required")
        reproduction = _mapping(metric.get("reproduction"))
        if not _non_empty_text(reproduction.get("command")):
            errors.append(f"{metric_id}: reproduction.command is required")
        evidence_refs = metric.get("evidenceRefs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(f"{metric_id}: evidenceRefs must be non-empty")
            evidence_refs = []
        claim = _mapping(metric.get("claim"))
        if not _non_empty_text(claim.get("allowed")):
            errors.append(f"{metric_id}: claim.allowed is required")
        if not _non_empty_text(claim.get("forbidden")):
            errors.append(f"{metric_id}: claim.forbidden is required")
        limitations = metric.get("limitations")
        if not isinstance(limitations, list):
            errors.append(f"{metric_id}: limitations must be a list")
        if repo_root is not None:
            for raw_ref in evidence_refs:
                if not _non_empty_text(raw_ref):
                    errors.append(f"{metric_id}: evidenceRefs contains an empty value")
                    continue
                ref_path = _repo_ref_path(str(raw_ref), repo_root)
                if ref_path is not None and not ref_path.exists():
                    errors.append(f"{metric_id}: evidence ref does not exist: {raw_ref}")

    runs = payload.get("runs")
    if not isinstance(runs, list):
        errors.append("runs must be a list")
        runs = []
    run_ids: set[str] = set()
    for raw_run in runs:
        run = _mapping(raw_run)
        run_id = str(run.get("id") or "").strip() or "<missing-run-id>"
        if run_id in run_ids:
            errors.append(f"duplicate run id: {run_id}")
        run_ids.add(run_id)
        outcome = str(run.get("outcome") or "")
        if outcome not in ALLOWED_RUN_OUTCOMES:
            errors.append(f"{run_id}: unsupported run outcome: {outcome}")
        if not _non_empty_text(run.get("command")):
            errors.append(f"{run_id}: command is required")
        if not _non_empty_text(run.get("measuredAt")):
            errors.append(f"{run_id}: measuredAt is required")
        if not _non_empty_text(run.get("summary")):
            errors.append(f"{run_id}: summary is required")

    datasets = payload.get("datasets")
    if not isinstance(datasets, list):
        errors.append("datasets must be a list")
        datasets = []
    dataset_ids: set[str] = set()
    for raw_dataset in datasets:
        dataset = _mapping(raw_dataset)
        dataset_id = str(dataset.get("id") or "").strip() or "<missing-dataset-id>"
        if dataset_id in dataset_ids:
            errors.append(f"duplicate dataset id: {dataset_id}")
        dataset_ids.add(dataset_id)
        if not _non_empty_text(dataset.get("domain")):
            errors.append(f"{dataset_id}: domain is required")
        if not _non_empty_text(dataset.get("sourceUrl")):
            errors.append(f"{dataset_id}: sourceUrl is required")
        if not _non_empty_text(dataset.get("localStatus")):
            errors.append(f"{dataset_id}: localStatus is required")

    if repo_root is not None:
        experiment_ref = payload.get("agentExperimentLedger")
        if not _non_empty_text(experiment_ref):
            errors.append("agentExperimentLedger is required")
        else:
            experiment_path = _repo_ref_path(str(experiment_ref), repo_root)
            if experiment_path is None or not experiment_path.is_file():
                errors.append(
                    f"agentExperimentLedger does not exist: {experiment_ref}"
                )
            else:
                try:
                    experiment_payload = json.loads(
                        experiment_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(
                        f"agentExperimentLedger is not readable JSON: {experiment_ref}: {exc}"
                    )
                else:
                    if not isinstance(experiment_payload, Mapping):
                        errors.append(
                            "agentExperimentLedger must contain a JSON object"
                        )
                    else:
                        errors.extend(
                            f"agentExperimentLedger: {error}"
                            for error in validate_agent_experiments(
                                experiment_payload,
                                repo_root=repo_root,
                            )
                        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the evidence and claim boundaries in the PAW interview metrics ledger."
    )
    parser.add_argument(
        "--ledger",
        default="eval/interview-metrics/evidence-ledger.v1.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    ledger_path = Path(args.ledger).resolve()
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("interview metrics ledger must contain a JSON object")
    repo_root = Path(__file__).resolve().parents[1]
    errors = validate_interview_metrics(payload, repo_root=repo_root)
    report = {
        "schemaVersion": "paw.interview-metrics-check.v1",
        "ok": not errors,
        "ledgerPath": str(ledger_path),
        "metricCount": len(payload.get("metrics") or []),
        "runCount": len(payload.get("runs") or []),
        "datasetCount": len(payload.get("datasets") or []),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("OK" if report["ok"] else "FAILED")
        for error in errors:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
