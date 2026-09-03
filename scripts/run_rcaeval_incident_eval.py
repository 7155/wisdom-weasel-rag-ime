#!/usr/bin/env python3
"""Run a reproducible, source-bound RCAEval metric-only validation.

The benchmark data and the RCAEval implementation deliberately live outside
this repository.  This runner keeps the PAW-side contract small: it selects
only RE1 repetitions 1 and 2 for validation, hashes the selected inputs and
source tree, invokes the upstream BARO/NSigma methods lazily, and reports the
official service/fine-grained AC@1/3/5 metrics.  A failed case is retained in
the denominator and contributes zero to every metric.

Held-out repetitions are never selected without an explicit promotion receipt
or gate whose contract hash matches ``FROZEN_VALIDATION_CONTRACT``.  No
runtime dependency (pandas, NumPy, or RCAEval) is imported at module load so
the contract helpers and their tests run on system Python.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


DATA_ROOT_DEFAULT = Path(
    os.environ.get("PAW_RCAEVAL_DATA_ROOT", "eval/external/rcaeval/data")
)
SOURCE_ROOT_DEFAULT = Path(
    os.environ.get("PAW_RCAEVAL_SOURCE_ROOT", "eval/external/rcaeval/source")
)

VALIDATION_REPETITIONS = (1, 2)
HELD_OUT_REPETITIONS = (3, 4, 5)
VALIDATION_CASE_COUNT = 150
HELD_OUT_CASE_COUNT = 225
# RCAEval main.py defaults --length=20 and converts minutes to samples with
# ``length * 60 // 2``.  Keep the upstream default rather than a nicer-looking
# ad-hoc window.
NORMAL_WINDOW_ROWS = 600
FAULTY_WINDOW_ROWS = 600
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

EXPECTED_RE1_SERVICES = {
    "ob": {
        "adservice",
        "cartservice",
        "checkoutservice",
        "currencyservice",
        "productcatalogservice",
    },
    "ss": {"carts", "catalogue", "orders", "payment", "user"},
    "tt": {
        "ts-auth-service",
        "ts-order-service",
        "ts-route-service",
        "ts-train-service",
        "ts-travel-service",
    },
}
EXPECTED_RE1_FAULTS = {"cpu", "mem", "disk", "delay", "loss"}

PROFILE_CONFIGS: dict[str, dict[str, Any]] = {
    "baro": {
        "methods": ["baro"],
        "kind": "baseline",
        "implementation": "RCAEval.e2e.baro.baro",
    },
    "rrf-v1": {
        "methods": ["baro", "nsigma"],
        "kind": "candidate",
        "implementation": "reciprocal-rank-fusion",
        "rrfK": 10,
        "weights": {"baro": 0.25, "nsigma": 0.75},
    },
    "rrf-v2": {
        "methods": ["baro", "nsigma"],
        "kind": "candidate",
        "implementation": "reciprocal-rank-fusion",
        "rrfK": 3,
        "weights": {"baro": 0.35, "nsigma": 0.65},
    },
}

FROZEN_VALIDATION_CONTRACT: dict[str, Any] = {
    "schemaVersion": "paw.rcaeval-validation-contract.v1",
    "benchmark": "RCAEval",
    "suite": "RE1",
    "validation": {
        "split": "validation",
        "repetitions": list(VALIDATION_REPETITIONS),
        "caseCount": VALIDATION_CASE_COUNT,
    },
    "heldOut": {
        "split": "held-out",
        "repetitions": list(HELD_OUT_REPETITIONS),
        "caseCount": HELD_OUT_CASE_COUNT,
    },
    "profiles": {
        "baro": {
            "methods": ["baro"],
            "kind": "baseline",
            "implementation": "RCAEval.e2e.baro.baro",
        },
        "rrf-v1": {
            "methods": ["baro", "nsigma"],
            "kind": "candidate",
            "implementation": "reciprocal-rank-fusion",
            "rrfK": 10,
            "weights": {"baro": 0.25, "nsigma": 0.75},
        },
        "rrf-v2": {
            "methods": ["baro", "nsigma"],
            "kind": "candidate",
            "implementation": "reciprocal-rank-fusion",
            "rrfK": 3,
            "weights": {"baro": 0.35, "nsigma": 0.65},
        },
    },
    "preprocessing": {
        "replaceInfWithNaN": True,
        "fillForward": True,
        "fillRemainingNaN": 0,
        "normalRows": NORMAL_WINDOW_ROWS,
        "faultyRows": FAULTY_WINDOW_ROWS,
        "dropLatency50": True,
        "renameLatency90ToLatency": True,
    },
    "metrics": {
        "service": "AC@k",
        "fineGrained": "AC@k",
        "k": [1, 3, 5],
        "failedCaseCountsAsZero": True,
        "validationAllowedFailedCaseIds": ["re1ob_currencyservice_loss_1"],
        "serviceProjection": "deduplicate-services-before-top-k-as-in-main.py",
    },
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


FROZEN_VALIDATION_CONTRACT_SHA256 = sha256_json(FROZEN_VALIDATION_CONTRACT)


def _json_safe(value: object) -> object:
    """Convert pandas/numpy scalar values without importing either package."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    return str(value)


def _coerce_repetition(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("RCAEval repetition must be an integer")
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("RCAEval repetition is missing or invalid") from exc


def _normalize_split(split: str) -> str:
    normalized = str(split or "").strip().lower().replace("_", "-")
    if normalized in {"validation", "validate"}:
        return "validation"
    if normalized in {"held-out", "heldout"}:
        return "held-out"
    raise ValueError("RCAEval split must be validation or held-out")


def _safe_case_id(value: object) -> str:
    case_id = str(value or "").strip()
    if not case_id or Path(case_id).name != case_id or case_id in {".", ".."}:
        raise ValueError("RCAEval case id must be a single safe directory name")
    return case_id


def _select_re1_cases(rows: Iterable[Mapping[str, object]], repetitions: Sequence[int]) -> list[dict[str, object]]:
    """Filter suite before repetition so RE2/RE3 counts cannot bleed in."""

    allowed = {int(repetition) for repetition in repetitions}
    selected: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("suite", "")).strip().upper() != "RE1":
            continue
        repetition = _coerce_repetition(row.get("repetition"))
        if repetition in allowed:
            selected.append(dict(row))
    selected.sort(key=lambda row: _safe_case_id(row.get("case")))
    return selected


def select_re1_validation_cases(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Return the frozen RE1 validation cohort (repetitions 1 and 2)."""

    return _select_re1_cases(rows, VALIDATION_REPETITIONS)


def _select_re1_held_out_cases(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return _select_re1_cases(rows, HELD_OUT_REPETITIONS)


def _auth_documents(
    promotion_receipt: Mapping[str, object] | None,
    held_out_gate: Mapping[str, object] | None,
) -> Iterable[Mapping[str, object]]:
    """Yield top-level and one-level nested authorization documents."""

    for document in (promotion_receipt, held_out_gate):
        if not isinstance(document, Mapping):
            continue
        yield document
        for key in ("heldOutGate", "heldOutAuthorization", "gate", "promotion"):
            nested = document.get(key)
            if isinstance(nested, Mapping):
                yield nested


def _auth_document_matches(document: Mapping[str, object]) -> bool:
    schema = str(document.get("schemaVersion", ""))
    allowed_schemas = {
        "paw.rcaeval-promotion.v1",
        "paw.rcaeval-heldout-gate.v1",
        "paw.rcaeval-validation-promotion.v1",
    }
    if schema not in allowed_schemas:
        return False

    contract_hash = (
        document.get("validationContractSha256")
        or document.get("contractSha256")
        or document.get("frozenValidationContractSha256")
    )
    if contract_hash != FROZEN_VALIDATION_CONTRACT_SHA256:
        return False

    explicitly_authorized = any(
        document.get(key) is True
        for key in ("heldOutAuthorized", "authorized", "allowHeldOut")
    )
    if not explicitly_authorized:
        return False

    required_bindings = (
        "validationReportSha256",
        "validationBaselinePrivateSha256",
        "validationCandidatePrivateSha256",
        "validationCaseManifestSha256",
        "datasetIndexSha256",
        "datasetSnapshotSha256",
        "sourceRevision",
        "sourceSha256",
        "runnerSha256",
        "environmentSha256",
        "candidateProfile",
        "candidateConfigSha256",
        "validationMetrics",
        "promotionGate",
        "oneShotId",
        "heldOutConsumed",
    )
    if any(key not in document for key in required_bindings):
        return False
    for key in (
        "validationReportSha256",
        "validationBaselinePrivateSha256",
        "validationCandidatePrivateSha256",
        "validationCaseManifestSha256",
        "datasetIndexSha256",
        "datasetSnapshotSha256",
        "sourceSha256",
        "runnerSha256",
        "environmentSha256",
    ):
        if not isinstance(document.get(key), str) or _SHA256_RE.fullmatch(document[key]) is None:  # type: ignore[arg-type]
            return False
    if not isinstance(document.get("sourceRevision"), str) or _REVISION_RE.fullmatch(document["sourceRevision"]) is None:  # type: ignore[arg-type]
        return False
    if document.get("candidateProfile") != "rrf-v2":
        return False
    if document.get("candidateConfigSha256") != sha256_json(PROFILE_CONFIGS["rrf-v2"]):
        return False
    if not isinstance(document.get("oneShotId"), str) or re.fullmatch(
        r"rcaeval-re1-heldout:[0-9a-f]{24}", str(document["oneShotId"])
    ) is None:
        return False
    if document.get("heldOutConsumed") is not False:
        return False
    receipt_hash = document.get("promotionReceiptSha256")
    unsigned = {key: value for key, value in document.items() if key != "promotionReceiptSha256"}
    if not isinstance(receipt_hash, str) or receipt_hash != sha256_json(unsigned):
        return False

    validation_metrics = document.get("validationMetrics")
    expected_metric_keys = {
        "service.AC@1",
        "service.AC@3",
        "service.AC@5",
        "fineGrained.AC@1",
        "fineGrained.AC@3",
        "fineGrained.AC@5",
    }
    if not isinstance(validation_metrics, Mapping) or set(validation_metrics) != expected_metric_keys:
        return False
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in validation_metrics.values()
    ):
        return False
    promotion_gate = document.get("promotionGate")
    if not isinstance(promotion_gate, Mapping):
        return False
    if any(
        promotion_gate.get(key) is not True
        for key in (
            "passed",
            "primaryServiceAc1StrictImprovement",
            "noRegressionAcrossSixMetrics",
            "failedCasePolicyPassed",
        )
    ):
        return False

    if "promotion" in schema or schema.endswith("promotion.v1"):
        if str(document.get("decision", "")).lower() not in {
            "keep",
            "promote",
            "approved",
        }:
            return False

    optional_contract_fields = {
        "suite": "RE1",
        "validationRepetitions": list(VALIDATION_REPETITIONS),
        "heldOutRepetitions": list(HELD_OUT_REPETITIONS),
        "heldOutCaseCount": HELD_OUT_CASE_COUNT,
    }
    for key, expected in optional_contract_fields.items():
        if key in document and _json_safe(document.get(key)) != expected:
            return False

    return True


def validate_split_authorization(
    split: str,
    *,
    promotion_receipt: Mapping[str, object] | None = None,
    held_out_gate: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Fail closed before any held-out metadata or telemetry is read."""

    normalized = _normalize_split(split)
    if normalized == "validation":
        return {
            "split": normalized,
            "authorized": True,
            "heldOutObserved": False,
            "reason": "frozen validation cohort",
        }

    saw_matching_contract = False
    for document in _auth_documents(promotion_receipt, held_out_gate):
        candidate_contract = (
            document.get("validationContractSha256")
            or document.get("contractSha256")
            or document.get("frozenValidationContractSha256")
        )
        if candidate_contract == FROZEN_VALIDATION_CONTRACT_SHA256:
            saw_matching_contract = True
        if _auth_document_matches(document):
            return {
                "split": normalized,
                "authorized": True,
                "heldOutObserved": False,
                "authorizationDocumentSha256": sha256_json(document),
                "reason": "matching promotion receipt or held-out gate",
            }
    if saw_matching_contract:
        raise ValueError(
            "held-out authorization binding is incomplete or mismatched for the "
            "frozen RCAEval validation contract"
        )
    raise ValueError(
        "held-out execution requires a promotion receipt or gate matching "
        "the frozen RCAEval validation contract"
    )


def _matching_authorization_document(
    promotion_receipt: Mapping[str, object] | None,
    held_out_gate: Mapping[str, object] | None,
) -> Mapping[str, object]:
    for document in _auth_documents(promotion_receipt, held_out_gate):
        if _auth_document_matches(document):
            return document
    raise ValueError("held-out authorization binding is unavailable")


def _verify_held_out_current_binding(
    document: Mapping[str, object],
    *,
    dataset_snapshot_sha256: str,
    source_revision: str,
    source_sha256: str,
    runner_sha256: str,
    environment_sha256: str,
    profile: str,
) -> None:
    """Bind authorization to the files and implementation about to run."""

    if not _auth_document_matches(document):
        raise ValueError("held-out authorization receipt hash or binding is invalid")
    if profile != "rrf-v2" or document.get("candidateProfile") != profile:
        raise ValueError("held-out must execute the frozen paired rrf-v2 profile")
    if document.get("datasetSnapshotSha256") != dataset_snapshot_sha256:
        raise ValueError("held-out dataset snapshot drifted from promotion")
    if document.get("sourceRevision") != source_revision:
        raise ValueError("held-out source revision drifted from promotion")
    if document.get("sourceSha256") != source_sha256:
        raise ValueError("held-out source tree drifted from promotion")
    if document.get("runnerSha256") != runner_sha256:
        raise ValueError("held-out PAW runner drifted from promotion")
    if document.get("environmentSha256") != environment_sha256:
        raise ValueError("held-out execution environment drifted from promotion")
    if document.get("candidateConfigSha256") != sha256_json(PROFILE_CONFIGS["rrf-v2"]):
        raise ValueError("held-out candidate config drifted from promotion")


def _profile_config(profile: str) -> dict[str, object]:
    normalized = str(profile or "").strip()
    if normalized not in PROFILE_CONFIGS:
        raise ValueError("RCAEval profile must be baro, rrf-v1, or rrf-v2")
    return json.loads(json.dumps(PROFILE_CONFIGS[normalized]))


def fuse_rankings_rrf(
    rankings: Mapping[str, Sequence[object]],
    *,
    rrf_k: int = 10,
    weights: Mapping[str, float] | None = None,
) -> list[str]:
    """Fuse ranked metric names with deterministic, one-based RRF ranks."""

    if rrf_k <= 0:
        raise ValueError("RRF k must be positive")
    effective_weights = dict(weights or {"baro": 0.25, "nsigma": 0.75})
    numeric_weights = [float(weight) for weight in effective_weights.values()]
    if any(not math.isfinite(weight) for weight in numeric_weights):
        raise ValueError("RRF weights must be finite")
    if any(weight < 0 for weight in numeric_weights):
        raise ValueError("RRF weights cannot be negative")
    if not numeric_weights or sum(numeric_weights) <= 0:
        raise ValueError("RRF weights must contain positive mass")

    source_order = [
        source for source in ("baro", "nsigma") if source in rankings
    ] + sorted(str(source) for source in rankings if source not in {"baro", "nsigma"})
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    seen_counter = 0
    for source in source_order:
        source_seen: set[str] = set()
        weight = float(effective_weights.get(source, 1.0))
        for rank, raw_name in enumerate(rankings[source], start=1):
            name = str(raw_name)
            if not name or name in source_seen:
                continue
            source_seen.add(name)
            if name not in scores:
                scores[name] = 0.0
                first_seen[name] = seen_counter
                seen_counter += 1
            scores[name] += weight / float(rrf_k + rank)

    return sorted(scores, key=lambda name: (-scores[name], first_seen[name], name))


def _service_and_metric(rank: object) -> tuple[str, str]:
    value = str(rank)
    if "_" not in value:
        return value.replace("-db", ""), "unknown"
    service, metric = value.split("_", 1)
    metric = metric.replace("_latency-90", "_latency")
    if metric == "latency-90":
        metric = "latency"
    return service.replace("-db", ""), metric


def _expected_fine_metric(fault: object) -> str:
    normalized = str(fault or "").strip().lower()
    return {
        "disk": "diskio",
        "delay": "latency",
        "loss": "latency",
    }.get(normalized, normalized or "unknown")


def _unique_services(ranked: Sequence[object]) -> list[str]:
    services: list[str] = []
    seen: set[str] = set()
    for rank in ranked:
        service, _ = _service_and_metric(rank)
        if service not in seen:
            services.append(service)
            seen.add(service)
    return services


def _metric_block(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    case_count = len(records)
    failed_count = sum(1 for record in records if str(record.get("status", "error")) != "ok")
    service_hits = {1: 0, 3: 0, 5: 0}
    fine_hits = {1: 0, 3: 0, 5: 0}

    for record in records:
        ranked = record.get("ranked", [])
        if not isinstance(ranked, Sequence) or isinstance(ranked, (str, bytes)):
            ranked = []
        service_ranks = _unique_services(ranked)
        fine_ranks = [_service_and_metric(rank) for rank in ranked]
        expected_service = str(record.get("rootCauseService", "")).replace("-db", "")
        expected_fine = _expected_fine_metric(record.get("fault"))
        for k in (1, 3, 5):
            if expected_service in service_ranks[:k]:
                service_hits[k] += 1
            if (expected_service, expected_fine) in fine_ranks[:k]:
                fine_hits[k] += 1

    def ratio(hits: int) -> float:
        return hits / case_count if case_count else 0.0

    return {
        "caseCount": case_count,
        "failedCaseCount": failed_count,
        "service": {f"AC@{k}": ratio(service_hits[k]) for k in (1, 3, 5)},
        "fineGrained": {f"AC@{k}": ratio(fine_hits[k]) for k in (1, 3, 5)},
    }


def compute_official_metrics(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Compute RCAEval-style AC with PAW's explicit failed-case-zero denominator."""

    materialized = [dict(record) for record in records]
    result = _metric_block(materialized)
    systems = sorted({str(record.get("system", "unknown")) for record in materialized})
    faults = sorted({str(record.get("fault", "unknown")) for record in materialized})
    result["bySystem"] = {
        system: _metric_block(
            [record for record in materialized if str(record.get("system", "unknown")) == system]
        )
        for system in systems
    }
    result["byFault"] = {
        fault: _metric_block(
            [record for record in materialized if str(record.get("fault", "unknown")) == fault]
        )
        for fault in faults
    }
    return result


def _verify_private_evaluation_receipt(
    receipt: Mapping[str, object],
    *,
    public_metrics: Mapping[str, object],
    expected_profile: str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    if receipt.get("schemaVersion") != "paw.rcaeval-private-evaluation.v1":
        raise ValueError("RCAEval private evaluator receipt schema drifted")
    receipt_hash = receipt.get("privateEvaluationSha256")
    unsigned = {key: value for key, value in receipt.items() if key != "privateEvaluationSha256"}
    if not isinstance(receipt_hash, str) or receipt_hash != sha256_json(unsigned):
        raise ValueError("RCAEval private evaluator receipt hash is invalid")
    if expected_sha256 is not None and receipt_hash != expected_sha256:
        raise ValueError("RCAEval public/private evaluator binding drifted")
    if expected_profile is not None and receipt.get("profile") != expected_profile:
        raise ValueError("RCAEval private evaluator profile drifted")
    case_results = receipt.get("caseResults")
    if not isinstance(case_results, list) or not all(
        isinstance(item, Mapping) for item in case_results
    ):
        raise ValueError("RCAEval private evaluator case results are missing")
    recomputed = compute_official_metrics(case_results)
    if sha256_json(recomputed) != sha256_json(receipt.get("metrics")):
        raise ValueError("RCAEval private metrics do not match recomputed case results")
    if sha256_json(recomputed) != sha256_json(public_metrics):
        raise ValueError("RCAEval public metrics do not match recomputed private results")
    return {
        "metrics": recomputed,
        "caseResults": [dict(item) for item in case_results],
        "privateEvaluationSha256": receipt_hash,
    }


def validate_re1_grid(rows: Sequence[Mapping[str, object]], *, split: str) -> None:
    """Reject a count-correct cohort whose service/fault grid drifted."""

    normalized = _normalize_split(split)
    expected_repetitions = (
        VALIDATION_REPETITIONS if normalized == "validation" else HELD_OUT_REPETITIONS
    )
    expected = {
        (system, service, fault, repetition)
        for system, services in EXPECTED_RE1_SERVICES.items()
        for service in services
        for fault in EXPECTED_RE1_FAULTS
        for repetition in expected_repetitions
    }
    actual: list[tuple[str, str, str, int]] = []
    for row in rows:
        actual.append(
            (
                str(row.get("system", "")),
                str(row.get("root_cause_service", "")),
                str(row.get("fault", "")),
                _coerce_repetition(row.get("repetition")),
            )
        )
    if len(actual) != len(expected) or set(actual) != expected or len(actual) != len(set(actual)):
        raise ValueError(f"RCAEval {normalized} grid drifted from the frozen RE1 contract")


def evaluate_promotion_gate(
    baseline_metrics: Mapping[str, object],
    candidate_metrics: Mapping[str, object],
) -> dict[str, object]:
    """Apply the frozen six-metric validation promotion rule."""

    required = [
        ("service", "AC@1"),
        ("service", "AC@3"),
        ("service", "AC@5"),
        ("fineGrained", "AC@1"),
        ("fineGrained", "AC@3"),
        ("fineGrained", "AC@5"),
    ]
    deltas: dict[str, float] = {}
    no_regression = True
    for lane, metric in required:
        baseline_lane = baseline_metrics.get(lane, {})
        candidate_lane = candidate_metrics.get(lane, {})
        before = float(baseline_lane.get(metric, 0.0)) if isinstance(baseline_lane, Mapping) else 0.0
        after = float(candidate_lane.get(metric, 0.0)) if isinstance(candidate_lane, Mapping) else 0.0
        key = f"{lane}.{metric}"
        deltas[key] = after - before
        if after < before:
            no_regression = False

    before_ac1 = float(
        baseline_metrics.get("service", {}).get("AC@1", 0.0)  # type: ignore[union-attr]
    )
    after_ac1 = float(
        candidate_metrics.get("service", {}).get("AC@1", 0.0)  # type: ignore[union-attr]
    )
    primary_improved = after_ac1 > before_ac1
    return {
        "passed": primary_improved and no_regression,
        "primaryServiceAc1StrictImprovement": primary_improved,
        "noRegressionAcrossSixMetrics": no_regression,
        "deltas": deltas,
        "requiredMetrics": [f"{lane}.{metric}" for lane, metric in required],
    }


def build_case_manifest(
    rows: Iterable[Mapping[str, object]],
    *,
    split: str = "validation",
) -> dict[str, object]:
    normalized_split = _normalize_split(split)
    public_fields = ("case", "dataset", "system", "repetition", "inject_time")
    normalized_rows = [
        _json_safe({key: row.get(key) for key in public_fields if key in row})
        for row in rows
    ]
    normalized_rows = sorted(
        (row for row in normalized_rows if isinstance(row, Mapping)),
        key=lambda row: _safe_case_id(row.get("case")),
    )
    case_ids = [_safe_case_id(row.get("case")) for row in normalized_rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("RCAEval case manifest contains duplicate case ids")
    repetitions = sorted({_coerce_repetition(row.get("repetition")) for row in normalized_rows})
    payload = {
        "schemaVersion": "paw.rcaeval-case-manifest.v1",
        "benchmark": "RCAEval",
        "suite": "RE1",
        "split": normalized_split,
        "repetitions": repetitions,
        "cases": normalized_rows,
    }
    manifest_sha = sha256_json(payload)
    repetition_label = "-".join(str(repetition) for repetition in repetitions) or "none"
    replay_cohort = f"replay:rcaeval:re1-{normalized_split}-r{repetition_label}:{manifest_sha[:16]}"
    return {
        **payload,
        "caseIds": case_ids,
        "caseCount": len(case_ids),
        "caseManifestSha256": manifest_sha,
        "replayCohortId": replay_cohort,
    }


def _report_metrics_for_gate(report: Mapping[str, object]) -> dict[str, object]:
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("RCAEval validation report is missing metrics")
    required_lanes = ("service", "fineGrained")
    flattened: dict[str, object] = {}
    for lane in required_lanes:
        values = metrics.get(lane)
        if not isinstance(values, Mapping):
            raise ValueError("RCAEval validation report is missing metric lane")
        for key in ("AC@1", "AC@3", "AC@5"):
            value = values.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError("RCAEval validation report contains an invalid metric")
            flattened[f"{lane}.{key}"] = float(value)
    return flattened


def _verified_validation_report(
    report: Mapping[str, object],
    *,
    expected_profile: str,
    private_receipt: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    if report.get("schemaVersion") != "paw.rcaeval-incident-eval.v1":
        raise ValueError("RCAEval promotion requires a compatible validation report")
    if report.get("split") != "validation" or report.get("suite") != "RE1":
        raise ValueError("RCAEval promotion requires RE1 validation reports")
    if report.get("repetitions") != list(VALIDATION_REPETITIONS):
        raise ValueError("RCAEval promotion validation repetitions drifted")
    if report.get("profile") != expected_profile:
        raise ValueError("RCAEval promotion report profile drifted")
    execution = report.get("execution")
    if not isinstance(execution, Mapping) or execution.get("caseCount") != VALIDATION_CASE_COUNT:
        raise ValueError("RCAEval promotion validation case count drifted")
    public_metrics = report.get("metrics")
    if not isinstance(public_metrics, Mapping):
        raise ValueError("RCAEval promotion validation metrics are missing")
    private_hash = report.get("privateEvaluationSha256")
    if not isinstance(private_hash, str) or _SHA256_RE.fullmatch(private_hash) is None:
        raise ValueError("RCAEval promotion private evaluator binding is missing")
    verified_private = _verify_private_evaluation_receipt(
        private_receipt,
        public_metrics=public_metrics,
        expected_profile=expected_profile,
        expected_sha256=private_hash,
    )
    case_results = verified_private["caseResults"]
    failed_case_ids = sorted(
        str(item.get("case"))
        for item in case_results
        if isinstance(item, Mapping) and item.get("status") != "ok"
    )
    report_hash = report.get("reportSha256")
    unsigned = {key: value for key, value in report.items() if key != "reportSha256"}
    if not isinstance(report_hash, str) or report_hash != sha256_json(unsigned):
        raise ValueError("RCAEval promotion validation report hash is invalid")
    case_manifest = report.get("caseManifestSha256")
    data_sha = report.get("dataSha256")
    index_sha = report.get("datasetIndexSha256")
    dataset_snapshot_sha = report.get("datasetSnapshotSha256")
    source_sha = report.get("sourceSha256")
    runner_sha = report.get("runnerSha256")
    environment_sha = report.get("environmentSha256")
    source = report.get("source")
    source_git = source.get("git") if isinstance(source, Mapping) else None
    source_revision = source_git.get("revision") if isinstance(source_git, Mapping) else None
    if not all(
        isinstance(value, str) and _SHA256_RE.fullmatch(value)
        for value in (
            case_manifest,
            data_sha,
            index_sha,
            dataset_snapshot_sha,
            source_sha,
            runner_sha,
            environment_sha,
        )
    ):
        raise ValueError("RCAEval promotion validation input hashes are incomplete")
    if not isinstance(source_revision, str) or _REVISION_RE.fullmatch(source_revision) is None:
        raise ValueError("RCAEval promotion source revision is incomplete")
    identifiers = report.get("identifiers")
    config_sha = identifiers.get("profileConfigSha256") if isinstance(identifiers, Mapping) else None
    if config_sha != sha256_json(PROFILE_CONFIGS[expected_profile]):
        raise ValueError("RCAEval promotion profile config hash drifted")
    return str(report_hash), {
        "caseManifestSha256": str(case_manifest),
        "dataSha256": str(data_sha),
        "datasetIndexSha256": str(index_sha),
        "datasetSnapshotSha256": str(dataset_snapshot_sha),
        "sourceSha256": str(source_sha),
        "sourceRevision": source_revision,
        "runnerSha256": str(runner_sha),
        "environmentSha256": str(environment_sha),
        "profileConfigSha256": str(config_sha),
        "metrics": report["metrics"],
        "failedCaseIds": failed_case_ids,
        "privateEvaluationSha256": private_hash,
    }


def build_promotion_receipt(
    baseline_report: Mapping[str, object],
    candidate_report: Mapping[str, object],
    *,
    baseline_private_receipt: Mapping[str, object],
    candidate_private_receipt: Mapping[str, object],
    one_shot_id: str | None = None,
    decision: str = "keep",
) -> dict[str, object]:
    """Create an evidence-bound receipt; callers cannot hand-author a gate."""

    if str(decision).lower() not in {"keep", "promote", "approved"}:
        raise ValueError("RCAEval promotion decision is unsupported")
    baseline_hash, baseline_binding = _verified_validation_report(
        baseline_report,
        expected_profile="baro",
        private_receipt=baseline_private_receipt,
    )
    candidate_hash, candidate_binding = _verified_validation_report(
        candidate_report,
        expected_profile="rrf-v2",
        private_receipt=candidate_private_receipt,
    )
    derived_one_shot_id = f"rcaeval-re1-heldout:{candidate_hash[:24]}"
    if one_shot_id is not None and str(one_shot_id) != derived_one_shot_id:
        raise ValueError("RCAEval promotion one-shot id must be report-derived")
    shared_keys = (
        "caseManifestSha256",
        "dataSha256",
        "datasetIndexSha256",
        "datasetSnapshotSha256",
        "sourceSha256",
        "sourceRevision",
        "runnerSha256",
        "environmentSha256",
    )
    for key in shared_keys:
        if baseline_binding[key] != candidate_binding[key]:
            raise ValueError(f"RCAEval promotion validation binding drifted: {key}")
    allowed_failed = list(
        FROZEN_VALIDATION_CONTRACT["metrics"]["validationAllowedFailedCaseIds"]
    )
    if baseline_binding["failedCaseIds"] != allowed_failed:
        raise ValueError("RCAEval baseline failed-case set drifted from the frozen contract")
    if candidate_binding["failedCaseIds"] != allowed_failed:
        raise ValueError("RCAEval candidate failed-case set drifted from the frozen contract")
    gate = evaluate_promotion_gate(
        baseline_binding["metrics"], candidate_binding["metrics"]  # type: ignore[arg-type]
    )
    if gate["passed"] is not True:
        raise ValueError("RCAEval candidate did not pass the frozen promotion gate")
    gate["failedCasePolicyPassed"] = True
    receipt: dict[str, object] = {
        "schemaVersion": "paw.rcaeval-promotion.v1",
        "benchmark": "RCAEval",
        "suite": "RE1",
        "validationContractSha256": FROZEN_VALIDATION_CONTRACT_SHA256,
        "heldOutAuthorized": True,
        "decision": str(decision).lower(),
        "validationReportSha256": candidate_hash,
        "validationBaselineReportSha256": baseline_hash,
        "validationCandidateReportSha256": candidate_hash,
        "validationBaselinePrivateSha256": baseline_binding["privateEvaluationSha256"],
        "validationCandidatePrivateSha256": candidate_binding["privateEvaluationSha256"],
        "validationCaseManifestSha256": candidate_binding["caseManifestSha256"],
        "datasetIndexSha256": candidate_binding["datasetIndexSha256"],
        "datasetSnapshotSha256": candidate_binding["datasetSnapshotSha256"],
        "dataSha256": candidate_binding["dataSha256"],
        "sourceRevision": candidate_binding["sourceRevision"],
        "sourceSha256": candidate_binding["sourceSha256"],
        "runnerSha256": candidate_binding["runnerSha256"],
        "environmentSha256": candidate_binding["environmentSha256"],
        "candidateProfile": "rrf-v2",
        "candidateConfigSha256": candidate_binding["profileConfigSha256"],
        "validationMetrics": _report_metrics_for_gate(candidate_report),
        "promotionGate": gate,
        "oneShotId": derived_one_shot_id,
        "heldOutConsumed": False,
    }
    receipt["promotionReceiptSha256"] = sha256_json(receipt)
    return receipt


def held_out_consumption_path(one_shot_id: str) -> Path:
    if re.fullmatch(r"rcaeval-re1-heldout:[0-9a-f]{24}", str(one_shot_id)) is None:
        raise ValueError("RCAEval held-out one-shot id is invalid")
    suffix = hashlib.sha256(str(one_shot_id).encode("utf-8")).hexdigest()[:24]
    return (
        Path(__file__).resolve().parents[1]
        / "eval"
        / "interview-metrics"
        / "runs"
        / f"rcaeval-heldout-consumption-{suffix}.v1.json"
    )


def _reserve_held_out_consumption(
    path: Path,
    *,
    document: Mapping[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    reservation = {
        "schemaVersion": "paw.rcaeval-heldout-consumption.v1",
        "status": "reserved",
        "oneShotId": document["oneShotId"],
        "promotionReceiptSha256": document["promotionReceiptSha256"],
        "heldOutConsumed": True,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ValueError("held-out one-shot was already reserved or consumed") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(reservation, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # The O_EXCL path remains as a fail-closed tombstone even if writing the
        # full reservation fails.
        raise


def _complete_held_out_consumption(
    path: Path,
    *,
    document: Mapping[str, object],
    report: Mapping[str, object],
) -> None:
    execution = report.get("execution")
    receipt = {
        "schemaVersion": "paw.rcaeval-heldout-consumption.v1",
        "status": "completed",
        "oneShotId": document["oneShotId"],
        "promotionReceiptSha256": document["promotionReceiptSha256"],
        "heldOutConsumed": True,
        "heldOutReportSha256": report["reportSha256"],
        "caseManifestSha256": report["caseManifestSha256"],
        "profile": report["profile"],
        "failedCaseCount": execution.get("failedCaseCount") if isinstance(execution, Mapping) else None,
    }
    receipt["consumptionReceiptSha256"] = sha256_json(receipt)
    _write_json_atomic(path, receipt)


def build_run_identity(
    case_manifest: Mapping[str, object],
    *,
    data_sha256: str,
    source_sha256: str,
    runner_sha256: str,
    environment_sha256: str,
    profile: str,
) -> dict[str, object]:
    config = _profile_config(profile)
    split = str(case_manifest.get("split", "validation"))
    seed = sha256_json(
        {
            "caseManifestSha256": case_manifest.get("caseManifestSha256"),
            "dataSha256": data_sha256,
            "sourceSha256": source_sha256,
            "runnerSha256": runner_sha256,
            "environmentSha256": environment_sha256,
            "profile": profile,
            "config": config,
        }
    )
    identity = {
        "traceId": f"trace:rcaeval:re1:{seed[:20]}",
        "evalRunId": f"eval:rcaeval:re1-{split}:{profile}:{seed[20:36]}",
        "sandboxRunId": f"sandbox:rcaeval:re1-{profile}:{seed[36:52]}",
        "replayCohortId": str(case_manifest.get("replayCohortId", "")),
        "profileConfigSha256": sha256_json(config),
    }
    identity["identitySha256"] = sha256_json(identity)
    return identity


def _update_file_digest(digest: Any, path: Path) -> None:
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    _update_file_digest(digest, path)
    return digest.hexdigest()


def _environment_fingerprint() -> dict[str, object]:
    """Bind the interpreter and numerical stack without importing at module load."""

    try:
        from importlib.metadata import version

        packages = {
            name: version(name)
            for name in ("numpy", "pandas", "pyarrow", "scikit-learn", "RCAEval")
        }
    except Exception:
        packages = {}
    value: dict[str, object] = {
        "python": sys.version,
        "executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }
    value["environmentSha256"] = sha256_json(value)
    return value


def _hash_files(root: Path, relative_paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(relative_paths)):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"RCAEval input file is unavailable: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        _update_file_digest(digest, path)
        digest.update(b"\0")
    return digest.hexdigest()


def _hash_selected_data(data_root: Path, rows: Sequence[Mapping[str, object]]) -> tuple[str, int]:
    relative_paths = ["cases.parquet"]
    for row in rows:
        case_id = _safe_case_id(row.get("case"))
        relative_paths.extend((f"{case_id}/metrics.parquet", f"{case_id}/inject_time.txt"))
    return _hash_files(data_root, relative_paths), len(set(relative_paths))


def _hash_source_tree(source_root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in source_root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        relative_parts = path.relative_to(source_root).parts
        if ".git" in relative_parts or "__pycache__" in relative_parts or path.suffix == ".pyc":
            continue
        files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(source_root).as_posix()):
        relative = path.relative_to(source_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        _update_file_digest(digest, path)
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def _git_metadata(root: Path) -> dict[str, object]:
    try:
        revision_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {"revision": "", "dirty": None}
    if revision_result.returncode != 0:
        return {"revision": "", "dirty": None}
    return {
        "revision": revision_result.stdout.strip(),
        "dirty": bool(status_result.stdout.strip()) if status_result.returncode == 0 else None,
    }


def _default_case_index(data_root: Path, split: str) -> Path:
    return (
        data_root.parents[1]
        / "evaluator-private"
        / f"rcaeval-re1-{_normalize_split(split)}-index.v1.json"
    )


def _load_case_rows(
    case_index: Path,
    *,
    split: str,
    dataset_snapshot_sha256: str,
) -> list[dict[str, object]]:
    payload = json.loads(case_index.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("RCAEval split index must be an object")
    if payload.get("schemaVersion") != "paw.rcaeval-re1-split-index.v1":
        raise ValueError("RCAEval split index schema drifted")
    if payload.get("split") != _normalize_split(split):
        raise ValueError("RCAEval split index does not match requested split")
    if payload.get("datasetSnapshotSha256") != dataset_snapshot_sha256:
        raise ValueError("RCAEval split index dataset snapshot drifted")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not all(isinstance(row, Mapping) for row in cases):
        raise ValueError("RCAEval split index cases are invalid")
    rows = [dict(row) for row in cases]
    required = {"case", "suite", "dataset", "system", "root_cause_service", "fault", "repetition"}
    for row in rows:
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"RCAEval split index is missing columns: {', '.join(missing)}")
    return rows


def _load_runtime_methods(source_root: Path) -> tuple[Any, Any, Any]:
    import pandas as pd

    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    from RCAEval.e2e import baro, nsigma

    return pd, baro, nsigma


def _prepare_metric_window(data: Any, *, inject_time: int) -> Any:
    import numpy as np
    import pandas as pd

    keep_columns = [
        column for column in data.columns if not str(column).endswith("_latency-50")
    ]
    data = data.loc[:, keep_columns].copy()
    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.ffill()
    data = data.fillna(0)
    normal = data[data["time"] < inject_time].tail(NORMAL_WINDOW_ROWS)
    faulty = data[data["time"] >= inject_time].head(FAULTY_WINDOW_ROWS)
    if normal.empty or faulty.empty:
        raise ValueError("RCAEval case has no normal or faulty metric window")
    window = pd.concat([normal, faulty], ignore_index=True)
    window = window.rename(
        columns={
            column: str(column).replace("_latency-90", "_latency")
            for column in window.columns
            if str(column).endswith("_latency-90")
        }
    )
    return window


def _redact_error(message: object) -> str:
    text = str(message)
    text = re.sub(r"/(?:[^\s/]+/)+[^\s/]+", "<path>", text)
    return text[:320]


def _extract_ranks(output: object) -> list[str]:
    if not isinstance(output, Mapping):
        raise ValueError("RCAEval method returned a non-object result")
    ranks = output.get("ranks")
    if not isinstance(ranks, Sequence) or isinstance(ranks, (str, bytes)):
        raise ValueError("RCAEval method returned no ranked root causes")
    return [str(item) for item in ranks if str(item)]


def _run_case(
    row: Mapping[str, object],
    *,
    data_root: Path,
    pd: Any,
    baro: Any,
    nsigma: Any,
    profile: str,
) -> dict[str, object]:
    case_id = _safe_case_id(row.get("case"))
    started = time.perf_counter()
    result: dict[str, object] = {
        "case": case_id,
        "dataset": str(row.get("dataset", "")),
        "system": str(row.get("system", "")),
        "fault": str(row.get("fault", "")),
        "repetition": _coerce_repetition(row.get("repetition")),
        "rootCauseService": str(row.get("root_cause_service", "")),
        "status": "error",
        "ranked": [],
    }
    try:
        case_root = data_root / case_id
        if case_root.is_symlink() or not case_root.is_dir():
            raise FileNotFoundError(f"RCAEval case directory is unavailable: {case_id}")
        inject_path = case_root / "inject_time.txt"
        inject_time = int(inject_path.read_text(encoding="utf-8").strip())
        metadata_inject = row.get("inject_time")
        if metadata_inject is not None and _coerce_repetition(metadata_inject) != inject_time:
            raise ValueError("RCAEval case index and inject_time.txt disagree")
        data = pd.read_parquet(case_root / "metrics.parquet")
        window = _prepare_metric_window(data, inject_time=inject_time)
        method_kwargs = {
            "inject_time": inject_time,
            "dataset": str(row.get("dataset", "")),
            "anomalies": None,
            "dk_select_useful": False,
            "sli": None,
            "verbose": False,
        }
        method_rankings: dict[str, list[str]] = {
            "baro": _extract_ranks(baro(window, **method_kwargs)),
        }
        if profile in {"rrf-v1", "rrf-v2"}:
            method_rankings["nsigma"] = _extract_ranks(nsigma(window, **method_kwargs))
            config = PROFILE_CONFIGS[profile]
            ranked = fuse_rankings_rrf(
                method_rankings,
                rrf_k=int(config["rrfK"]),
                weights=config["weights"],
            )
        else:
            ranked = method_rankings["baro"]
        result["status"] = "ok"
        result["ranked"] = ranked
        result["methodRankings"] = method_rankings
        result["methodTop5"] = {name: ranks[:5] for name, ranks in method_rankings.items()}
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = _redact_error(exc)
        result["error"] = {
            "type": error_type,
            "message": error_message,
            "fingerprint": sha256_json({"type": error_type, "message": error_message}),
        }
    result["runtimeMs"] = round((time.perf_counter() - started) * 1000, 3)
    return result


def _paired_baro_records(case_results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for result in case_results:
        methods = result.get("methodRankings")
        baro_ranks = methods.get("baro") if isinstance(methods, Mapping) else None
        record = dict(result)
        record["ranked"] = list(baro_ranks) if isinstance(baro_ranks, Sequence) else []
        record["status"] = "ok" if record["ranked"] else "error"
        records.append(record)
    return records


def _public_case_result(result: Mapping[str, object]) -> dict[str, object]:
    """Keep gold labels and full rankings out of the shareable report."""

    allowed = ("case", "dataset", "system", "repetition", "status", "runtimeMs", "error")
    public = {key: _json_safe(result[key]) for key in allowed if key in result}
    ranked = result.get("ranked")
    public["top5"] = list(ranked[:5]) if isinstance(ranked, Sequence) else []
    method_top5 = result.get("methodTop5")
    if isinstance(method_top5, Mapping):
        public["methodTop5"] = _json_safe(method_top5)
    return public


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _private_evaluation_path(output: Path) -> Path:
    return output.parent / "evaluator-private" / output.name


def run_rcaeval_incident_eval(
    *,
    data_root: str | Path = DATA_ROOT_DEFAULT,
    source_root: str | Path = SOURCE_ROOT_DEFAULT,
    case_index: str | Path | None = None,
    output: str | Path | None = None,
    split: str = "validation",
    profile: str = "baro",
    promotion_receipt: Mapping[str, object] | None = None,
    held_out_gate: Mapping[str, object] | None = None,
    consumption_receipt: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    authorization = validate_split_authorization(
        split,
        promotion_receipt=promotion_receipt,
        held_out_gate=held_out_gate,
    )
    normalized_split = str(authorization["split"])
    authorization_document: Mapping[str, object] | None = None
    consumption_path: Path | None = None
    if normalized_split == "held-out":
        if dry_run:
            raise ValueError("held-out dry-run would consume the one-shot cohort")
        if profile != "rrf-v2":
            raise ValueError("held-out must run the paired rrf-v2 profile")
        if output is None:
            raise ValueError("held-out requires a durable target output")
        if output is not None and Path(output).expanduser().exists():
            raise ValueError("held-out target output already exists")
        authorization_document = _matching_authorization_document(
            promotion_receipt,
            held_out_gate,
        )
        expected_consumption = held_out_consumption_path(
            str(authorization_document["oneShotId"])
        )
        if consumption_receipt is not None and Path(consumption_receipt).expanduser().resolve() != expected_consumption:
            raise ValueError("held-out consumption receipt path must match the one-shot registry")
        consumption_path = expected_consumption
        # O_EXCL reservation is deliberately the first persistent or data-touching
        # action after structural authorization.  Any later drift leaves a
        # fail-closed tombstone and the public cohort cannot be tried again.
        _reserve_held_out_consumption(consumption_path, document=authorization_document)
    profile_config = _profile_config(profile)
    data_path = Path(data_root).expanduser().resolve(strict=True)
    source_path = Path(source_root).expanduser().resolve(strict=True)
    if not data_path.is_dir() or not (data_path / "cases.parquet").is_file():
        raise FileNotFoundError("RCAEval data root or case index is unavailable")
    if not source_path.is_dir():
        raise FileNotFoundError("RCAEval source root is unavailable")

    case_index_path = (
        Path(case_index).expanduser().resolve(strict=True)
        if case_index is not None
        else _default_case_index(data_path, normalized_split).resolve(strict=True)
    )
    if not case_index_path.is_file():
        raise FileNotFoundError("RCAEval split-specific case index is unavailable")

    dataset_snapshot_sha256 = _file_sha256(data_path / "cases.parquet")
    dataset_index_sha256 = _file_sha256(case_index_path)
    source_sha256, source_file_count = _hash_source_tree(source_path)
    source_git = _git_metadata(source_path)
    source_revision = str(source_git.get("revision") or "")
    runner_sha256 = _file_sha256(Path(__file__).resolve())
    environment = _environment_fingerprint()
    environment_sha256 = str(environment["environmentSha256"])

    if normalized_split == "held-out":
        assert authorization_document is not None
        _verify_held_out_current_binding(
            authorization_document,
            dataset_snapshot_sha256=dataset_snapshot_sha256,
            source_revision=source_revision,
            source_sha256=source_sha256,
            runner_sha256=runner_sha256,
            environment_sha256=environment_sha256,
            profile=profile,
        )

    all_rows = _load_case_rows(
        case_index_path,
        split=normalized_split,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
    )
    if normalized_split == "validation":
        selected = select_re1_validation_cases(all_rows)
        expected_count = VALIDATION_CASE_COUNT
        repetitions = VALIDATION_REPETITIONS
    else:
        selected = _select_re1_held_out_cases(all_rows)
        expected_count = HELD_OUT_CASE_COUNT
        repetitions = HELD_OUT_REPETITIONS
    if len(selected) != expected_count:
        raise ValueError(
            f"RCAEval {normalized_split} cohort expected {expected_count} RE1 cases, "
            f"found {len(selected)}"
        )
    selected_ids = [_safe_case_id(row.get("case")) for row in selected]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("RCAEval selected cohort contains duplicate cases")
    if sorted({_coerce_repetition(row.get("repetition")) for row in selected}) != list(repetitions):
        raise ValueError("RCAEval selected cohort repetitions drifted from frozen contract")
    validate_re1_grid(selected, split=normalized_split)

    case_manifest = build_case_manifest(selected, split=normalized_split)
    data_sha256, data_file_count = _hash_selected_data(data_path, selected)
    identity = build_run_identity(
        case_manifest,
        data_sha256=data_sha256,
        source_sha256=source_sha256,
        runner_sha256=runner_sha256,
        environment_sha256=environment_sha256,
        profile=profile,
    )
    data_git = _git_metadata(data_path)
    report: dict[str, object] = {
        "schemaVersion": "paw.rcaeval-incident-eval.v1",
        "status": "prepared" if dry_run else "running",
        "benchmark": "RCAEval",
        "suite": "RE1",
        "split": normalized_split,
        "repetitions": list(repetitions),
        "profile": profile,
        "profileConfig": profile_config,
        "frozenValidationContractSha256": FROZEN_VALIDATION_CONTRACT_SHA256,
        "caseManifest": case_manifest,
        "caseManifestSha256": case_manifest["caseManifestSha256"],
        "datasetIndexSha256": dataset_index_sha256,
        "datasetSnapshotSha256": dataset_snapshot_sha256,
        "data": {
            "dataSha256": data_sha256,
            "fileCount": data_file_count,
            "git": data_git,
        },
        "dataSha256": data_sha256,
        "source": {
            "sourceSha256": source_sha256,
            "fileCount": source_file_count,
            "git": source_git,
        },
        "sourceSha256": source_sha256,
        "runnerSha256": runner_sha256,
        "environment": environment,
        "environmentSha256": environment_sha256,
        "preprocessing": {
            "replaceInfWithNaN": True,
            "fillForward": True,
            "fillRemainingNaN": 0,
            "normalRows": NORMAL_WINDOW_ROWS,
            "faultyRows": FAULTY_WINDOW_ROWS,
            "dropLatency50": True,
            "renameLatency90ToLatency": True,
        },
        "identifiers": identity,
        **identity,
        "authorization": authorization,
        "boundary": {
            "dataRootPublished": False,
            "sourceRootPublished": False,
            "goldLabelsPublished": False,
            "heldOutObserved": normalized_split == "held-out",
            "heldOutScored": normalized_split == "held-out" and not dry_run,
            "heldOutUsedForSelection": False,
            "installActionPerformed": False,
            "providerCalls": 0,
        },
        "execution": {
            "performed": not dry_run,
            "caseCount": len(selected),
            "failedCaseCount": 0,
            "runtimeMs": 0.0,
            "caseResults": [],
        },
        "metrics": None,
        "promotionGate": {
            "status": "not_evaluated",
            "reason": "run baseline and candidate reports separately before promotion",
        },
    }

    if not dry_run:
        pd, baro, nsigma = _load_runtime_methods(source_path)
        started = time.perf_counter()
        case_results = [
            _run_case(
                row,
                data_root=data_path,
                pd=pd,
                baro=baro,
                nsigma=nsigma,
                profile=profile,
            )
            for row in selected
        ]
        metrics = compute_official_metrics(case_results)
        paired_baseline_metrics = (
            compute_official_metrics(_paired_baro_records(case_results))
            if profile in {"rrf-v1", "rrf-v2"}
            else None
        )
        private_evaluation: dict[str, object] = {
            "schemaVersion": "paw.rcaeval-private-evaluation.v1",
            "benchmark": "RCAEval",
            "suite": "RE1",
            "split": normalized_split,
            "profile": profile,
            "caseManifestSha256": case_manifest["caseManifestSha256"],
            "dataSha256": data_sha256,
            "datasetIndexSha256": dataset_index_sha256,
            "datasetSnapshotSha256": dataset_snapshot_sha256,
            "sourceSha256": source_sha256,
            "runnerSha256": runner_sha256,
            "environmentSha256": environment_sha256,
            "caseResults": case_results,
            "metrics": metrics,
            "pairedBaselineMetrics": paired_baseline_metrics,
        }
        private_evaluation["privateEvaluationSha256"] = sha256_json(private_evaluation)
        report["privateEvaluationSha256"] = private_evaluation["privateEvaluationSha256"]
        if output is not None:
            _write_json_atomic(
                _private_evaluation_path(Path(output).expanduser()),
                private_evaluation,
            )
        execution = report["execution"]
        assert isinstance(execution, dict)
        execution.update(
            {
                "failedCaseCount": int(metrics["failedCaseCount"]),
                "runtimeMs": round((time.perf_counter() - started) * 1000, 3),
                "caseResults": [_public_case_result(result) for result in case_results],
            }
        )
        report["metrics"] = metrics
        if paired_baseline_metrics is not None:
            report["pairedBaselineMetrics"] = paired_baseline_metrics
            report["promotionGate"] = evaluate_promotion_gate(
                paired_baseline_metrics,
                metrics,
            )
        report["status"] = "completed" if not metrics["failedCaseCount"] else "completed_with_errors"

    report_without_hash = dict(report)
    report["reportSha256"] = sha256_json(report_without_hash)
    if output is not None:
        _write_json_atomic(Path(output), report)
    if consumption_path is not None and authorization_document is not None:
        _complete_held_out_consumption(
            consumption_path,
            document=authorization_document,
            report=report,
        )
    return report


def _load_optional_json(path: Path | None) -> Mapping[str, object] | None:
    if path is None:
        return None
    value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"authorization document must be an object: {path.name}")
    return value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run source-bound RCAEval RE1 validation without observing held-out cases."
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT_DEFAULT)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT_DEFAULT)
    parser.add_argument(
        "--case-index",
        type=Path,
        help="Split-specific evaluator index; defaults to the external evaluator-private directory.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "held-out"), default="validation")
    parser.add_argument("--profile", choices=tuple(PROFILE_CONFIGS), default="baro")
    parser.add_argument("--promotion-receipt", type=Path)
    parser.add_argument("--held-out-gate", type=Path)
    parser.add_argument(
        "--consumption-receipt",
        type=Path,
        help="Optional one-shot held-out consumption receipt; an existing path rejects the run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Hash and validate the selected cohort without importing RCAEval or running methods.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = run_rcaeval_incident_eval(
            data_root=args.data_root,
            source_root=args.source_root,
            case_index=args.case_index,
            output=args.output,
            split=args.split,
            profile=args.profile,
            promotion_receipt=_load_optional_json(args.promotion_receipt),
            held_out_gate=_load_optional_json(args.held_out_gate),
            consumption_receipt=args.consumption_receipt,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": "paw.rcaeval-incident-eval-error.v1",
                    "status": "rejected",
                    "errorType": type(exc).__name__,
                    "error": _redact_error(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "split": report["split"],
                "profile": report["profile"],
                "caseCount": report["execution"]["caseCount"],  # type: ignore[index]
                "failedCaseCount": report["execution"]["failedCaseCount"],  # type: ignore[index]
                "reportSha256": report["reportSha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
