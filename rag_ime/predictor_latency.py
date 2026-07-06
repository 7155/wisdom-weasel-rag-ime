from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class PredictorLatencyTrace:
    request_id: str
    request_type: str
    profile_id: str
    model_id: str
    queued_ms: float = 0.0
    request_parse_ms: float = 0.0
    prompt_build_ms: float = 0.0
    tokenize_ms: float = 0.0
    cache_lookup_ms: float = 0.0
    prefill_ms: float = 0.0
    first_token_ms: float = 0.0
    first_candidate_ms: float = 0.0
    decode_ms: float = 0.0
    branch_ms: float = 0.0
    parse_ms: float = 0.0
    total_ms: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    candidate_count: int = 0
    cache_hit: bool = False
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    cancelled: bool = False
    cancel_reason: str = ""
    stale_dropped: bool = False
    rss_mb: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        payload = _camelize_keys(asdict(self))
        return {key: value for key, value in payload.items() if value not in ("", None)}


class LatencyTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self._marks: dict[str, float] = {}

    def mark(self, key: str) -> None:
        self._marks[key] = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def since_start_ms(self, key: str) -> float:
        value = self._marks.get(key)
        if value is None:
            return 0.0
        return (value - self.started) * 1000.0


def latency_log_path_from_env(env: dict[str, str] | None = None) -> Path:
    source = env or os.environ
    configured = source.get("RAG_IME_PREDICTOR_LATENCY_LOG", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Logs" / "RagIme" / "predictor-latency.jsonl"


def append_latency_trace(trace: PredictorLatencyTrace | dict[str, Any], *, path: Path | None = None) -> None:
    target = path or latency_log_path_from_env()
    payload = trace.to_payload() if isinstance(trace, PredictorLatencyTrace) else _redacted_trace_payload(trace)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def read_latency_traces(path: Path, *, last: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    selected = lines[-max(1, int(last)) :]
    result: list[dict[str, Any]] = []
    for line in selected:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            result.append(_redacted_trace_payload(payload))
    return result


def latency_report(path: Path, *, last: int = 200) -> dict[str, Any]:
    traces = read_latency_traces(path, last=last)
    return {
        "schemaVersion": "rag-ime.predictor-latency-report.v1",
        "log": str(path),
        "count": len(traces),
        "last": max(1, int(last)),
        "summary": {
            "firstCandidateMs": _percentiles(_numbers(item.get("firstCandidateMs") for item in traces)),
            "totalMs": _percentiles(_numbers(item.get("totalMs") for item in traces)),
            "prefillMs": _percentiles(_numbers(item.get("prefillMs") for item in traces)),
            "decodeMs": _percentiles(_numbers(item.get("decodeMs") for item in traces)),
            "cacheHitRate": _rate(bool(item.get("cacheHit")) for item in traces),
            "cancelledRate": _rate(bool(item.get("cancelled")) for item in traces),
            "staleDropRate": _rate(bool(item.get("staleDropped")) for item in traces),
        },
    }


def trace_from_prediction_payload(
    payload: dict[str, Any],
    *,
    request_id: str,
    request_type: str,
    profile_id: str,
    model_id: str,
    prompt_tokens: int = 0,
    output_tokens: int = 0,
) -> PredictorLatencyTrace:
    timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
    prompt_cache = payload.get("promptCache") if isinstance(payload.get("promptCache"), dict) else {}
    prefix_cache = payload.get("prefixCache") if isinstance(payload.get("prefixCache"), dict) else {}
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    branch_timings = timing.get("branches") if isinstance(timing.get("branches"), list) else []
    branch_ms = sum(_float(item.get("elapsedMs")) for item in branch_timings if isinstance(item, dict))
    total_ms = _float(payload.get("totalMs"))
    first_candidate_ms = _float(timing.get("firstCandidateMs")) or _float(timing.get("logitsMs")) or (total_ms if candidates else 0.0)
    cache_hit_tokens = _int(prefix_cache.get("cacheHitTokens"))
    if cache_hit_tokens <= 0 and _cache_hit(prompt_cache):
        cache_hit_tokens = _int(prompt_cache.get("stablePrefixTokens"))
    return PredictorLatencyTrace(
        request_id=request_id,
        request_type=request_type,
        profile_id=profile_id,
        model_id=model_id,
        prompt_build_ms=_float(timing.get("promptBuildMs")),
        tokenize_ms=_float(timing.get("tokenizeMs")),
        cache_lookup_ms=_float(timing.get("cacheLookupMs")),
        prefill_ms=_float(timing.get("prefillMs")),
        first_token_ms=_float(timing.get("firstTokenMs")) or first_candidate_ms,
        first_candidate_ms=first_candidate_ms,
        decode_ms=max(0.0, total_ms - branch_ms - _float(timing.get("logitsMs"))),
        branch_ms=branch_ms,
        parse_ms=_float(timing.get("parseMs")),
        total_ms=total_ms,
        prompt_tokens=max(0, int(prompt_tokens)),
        output_tokens=max(0, int(output_tokens)),
        candidate_count=len(candidates),
        cache_hit=_cache_hit(prompt_cache) or bool(prefix_cache.get("cacheHit")),
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=max(0, int(prompt_tokens) - cache_hit_tokens),
        cancelled=bool(payload.get("cancelled") or timing.get("cancelled")),
        cancel_reason=str(payload.get("cancelReason") or timing.get("cancelReason") or ""),
        stale_dropped=bool(payload.get("staleDropped") or timing.get("staleDropped")),
        rss_mb=_rss_mb(),
    )


def _cache_hit(prompt_cache: dict[str, Any]) -> bool:
    return bool(prompt_cache.get("usedForGeneration") or prompt_cache.get("cacheHit"))


def _redacted_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"prompt", "rawPrompt", "recentContext", "currentInput", "rawText", "text", "content"}
    return {str(key): value for key, value in payload.items() if str(key) not in blocked}


def _camelize_keys(payload: dict[str, Any]) -> dict[str, Any]:
    return {_camelize(key): value for key, value in payload.items()}


def _camelize(key: str) -> str:
    head, *tail = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _numbers(values: Iterable[Any]) -> list[float]:
    return [number for number in (_float(value) for value in values) if number > 0]


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50Ms": 0.0, "p95Ms": 0.0, "maxMs": 0.0}
    ordered = sorted(values)
    return {
        "p50Ms": round(float(statistics.median(ordered)), 3),
        "p95Ms": round(_nearest_percentile(ordered, 0.95), 3),
        "maxMs": round(float(ordered[-1]), 3),
    }


def _nearest_percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int(round((len(values) - 1) * pct))))
    return float(values[index])


def _rate(values: Iterable[bool]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return round(sum(1 for item in items if item) / len(items), 6)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _rss_mb() -> float:
    try:
        import resource

        rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        return 0.0
    if rss <= 0:
        return 0.0
    if os.uname().sysname == "Darwin":
        return round(rss / 1024 / 1024, 3)
    return round(rss / 1024, 3)
