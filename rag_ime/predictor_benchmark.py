from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .predictor import (
    PREDICTION_REQUEST_IME_HOT,
    PREDICTION_REQUEST_IME_POST_COMMIT,
    PredictionBenchmarkCase,
    PredictionProvider,
    predict_with_optional_request_context,
)
from .text_utils import compact_whitespace


def load_predictor_latency_cases(path: Path) -> list[PredictionBenchmarkCase]:
    cases: list[PredictionBenchmarkCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        context = compact_whitespace(
            str(payload.get("contextTail") or payload.get("recentContext") or payload.get("context") or "")
        )
        current = compact_whitespace(str(payload.get("currentInput") or payload.get("query") or ""))
        request_type = str(payload.get("requestType") or PREDICTION_REQUEST_IME_POST_COMMIT)
        rime_candidates = payload.get("rimeCandidates")
        if not isinstance(rime_candidates, list):
            rime_candidates = []
        cases.append(
            PredictionBenchmarkCase(
                current_input=current,
                recent_context=context,
                case_id=str(payload.get("id") or payload.get("caseId") or ""),
            )
        )
        # Attach optional fields without changing the public dataclass contract.
        object.__setattr__(cases[-1], "request_type", request_type)
        object.__setattr__(cases[-1], "rime_candidates", tuple(str(item) for item in rime_candidates if str(item).strip()))
        object.__setattr__(cases[-1], "must_produce_at_least", int(payload.get("mustProduceAtLeast") or 1))
    return cases


def benchmark_predictor_latency(
    provider: PredictionProvider,
    cases: list[PredictionBenchmarkCase],
    *,
    profile: str,
    repeat: int = 20,
    max_candidates: int = 3,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    repeat_count = max(1, int(repeat))
    for repeat_index in range(1, repeat_count + 1):
        for case in cases:
            request_type = str(getattr(case, "request_type", PREDICTION_REQUEST_IME_POST_COMMIT))
            rime_candidates = tuple(getattr(case, "rime_candidates", ()))
            started = time.perf_counter()
            predictions = predict_with_optional_request_context(
                provider,
                current_input=case.current_input,
                recent_context=case.recent_context,
                max_candidates=max_candidates,
                request_type=request_type,
                rime_candidates=rime_candidates,
            )
            wall_ms = int((time.perf_counter() - started) * 1000)
            trace = _first_latency_trace(predictions)
            first_candidate_ms = _int(trace.get("firstCandidateMs")) or _first_candidate_ms(predictions, wall_ms)
            total_ms = _int(trace.get("totalMs")) or wall_ms
            candidate_texts = [item.text for item in predictions]
            samples.append(
                {
                    "caseId": case.case_id,
                    "repeatIndex": repeat_index,
                    "requestType": request_type,
                    "candidateCount": len(candidate_texts),
                    "firstCandidateMs": first_candidate_ms,
                    "threeCandidatesMs": first_candidate_ms if len(candidate_texts) >= 3 else total_ms,
                    "totalMs": total_ms,
                    "prefillMs": _float(trace.get("prefillMs")),
                    "decodeMs": _float(trace.get("decodeMs")),
                    "cacheHit": bool(trace.get("cacheHit")),
                    "cacheHitTokens": _int(trace.get("cacheHitTokens")),
                    "cacheMissTokens": _int(trace.get("cacheMissTokens")),
                    "cancelled": bool(trace.get("cancelled")),
                    "staleDropped": bool(trace.get("staleDropped")),
                    "formatValid": bool(candidate_texts),
                    "genericFiller": _generic_filler_count(candidate_texts),
                    "duplicateCount": len(candidate_texts) - len(set(candidate_texts)),
                    "candidates": candidate_texts,
                }
            )
    summary = _summary(samples)
    thresholds = _thresholds_for_profile(profile)
    checks = _checks(summary, thresholds)
    return {
        "schemaVersion": "rag-ime.predictor-benchmark.v1",
        "profile": profile,
        "repeat": repeat_count,
        "maxCandidates": max_candidates,
        "caseCount": len(cases),
        "sampleCount": len(samples),
        "summary": summary,
        "thresholds": thresholds,
        "checks": checks,
        "gatePassed": all(bool(item["passed"]) for item in checks),
        "cases": samples,
    }


def write_predictor_benchmark_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _first_latency_trace(predictions: list[Any]) -> dict[str, Any]:
    for prediction in predictions:
        metadata = getattr(prediction, "metadata", None)
        if isinstance(metadata, dict):
            trace = metadata.get("latency_trace") or metadata.get("latencyTrace")
            if isinstance(trace, dict):
                return trace
    return {}


def _first_candidate_ms(predictions: list[Any], fallback_ms: int) -> int:
    for item in predictions:
        metadata = getattr(item, "metadata", None)
        if isinstance(metadata, dict):
            value = metadata.get("first_candidate_ms") or metadata.get("firstCandidateMs")
            parsed = _int(value)
            if parsed > 0:
                return parsed
    return fallback_ms if predictions else 0


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    count = max(1, len(samples))
    return {
        "firstCandidateP50Ms": _percentile([_int(item.get("firstCandidateMs")) for item in samples], 0.50),
        "firstCandidateP95Ms": _percentile([_int(item.get("firstCandidateMs")) for item in samples], 0.95),
        "threeCandidatesP95Ms": _percentile([_int(item.get("threeCandidatesMs")) for item in samples], 0.95),
        "totalP95Ms": _percentile([_int(item.get("totalMs")) for item in samples], 0.95),
        "prefillP95Ms": _percentile([_float(item.get("prefillMs")) for item in samples], 0.95),
        "decodeP95Ms": _percentile([_float(item.get("decodeMs")) for item in samples], 0.95),
        "cacheHitRate": round(sum(1 for item in samples if item.get("cacheHit")) / count, 6),
        "cancelledRate": round(sum(1 for item in samples if item.get("cancelled")) / count, 6),
        "staleDropRate": round(sum(1 for item in samples if item.get("staleDropped")) / count, 6),
        "formatValidRate": round(sum(1 for item in samples if item.get("formatValid")) / count, 6),
        "genericFillerRate": round(sum(_int(item.get("genericFiller")) for item in samples) / count, 6),
        "duplicateRate": round(sum(_int(item.get("duplicateCount")) for item in samples) / count, 6),
        "candidateSampleCount": sum(1 for item in samples if _int(item.get("candidateCount")) > 0),
    }


def _thresholds_for_profile(profile: str) -> dict[str, float]:
    normalized = profile.lower()
    if "quality" in normalized:
        return {"maxFirstCandidateP95Ms": 1800, "maxThreeCandidatesP95Ms": 2500}
    if "main" in normalized or "post" in normalized:
        return {"maxFirstCandidateP95Ms": 800, "maxThreeCandidatesP95Ms": 1200}
    return {
        "maxFirstCandidateP95Ms": 500,
        "maxThreeCandidatesP95Ms": 900,
        "minFormatValidRate": 0.99,
        "maxGenericFillerRate": 0.02,
        "maxDuplicateRate": 0.05,
    }


def _checks(summary: dict[str, Any], thresholds: dict[str, float]) -> list[dict[str, Any]]:
    checks = []
    mapping = (
        ("hot-first-candidate-p95", "firstCandidateP95Ms", "maxFirstCandidateP95Ms", "<="),
        ("hot-three-candidates-p95", "threeCandidatesP95Ms", "maxThreeCandidatesP95Ms", "<="),
        ("format-valid-rate", "formatValidRate", "minFormatValidRate", ">="),
        ("generic-filler-rate", "genericFillerRate", "maxGenericFillerRate", "<="),
        ("duplicate-rate", "duplicateRate", "maxDuplicateRate", "<="),
    )
    for name, actual_key, threshold_key, op in mapping:
        if threshold_key not in thresholds:
            continue
        actual = float(summary.get(actual_key) or 0.0)
        expected = float(thresholds[threshold_key])
        passed = actual >= expected if op == ">=" else actual <= expected
        checks.append({"name": name, "passed": passed, "actual": actual, "expected": expected, "operator": op})
    return checks


def _percentile(values: list[float | int], pct: float) -> float:
    filtered = sorted(float(item) for item in values if float(item) > 0)
    if not filtered:
        return 0.0
    index = max(0, min(len(filtered) - 1, int(round((len(filtered) - 1) * pct))))
    return round(filtered[index], 3)


def _generic_filler_count(candidates: list[str]) -> int:
    pattern = re.compile(r"^(下一步|接下来|根据上述|可以进行|候选如下|以下是)$")
    return sum(1 for item in candidates if pattern.match(compact_whitespace(item)))


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
