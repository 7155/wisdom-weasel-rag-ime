from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .adapter import InputMethodAdapter
from .local_sqlite_core import LocalSqliteCoreClient
from .memory_ingest import normalize_text, upsert_memory_item
from .models import InputEvent
from .predictor import PredictionProvider
from .rime_sidecar import build_rime_sidecar_response
from .text_utils import compact_whitespace, now_ms


@dataclass(frozen=True)
class MemoryOptimizerEvalCase:
    case_id: str
    description: str
    query: str
    raw_input: str
    preedit: str
    committed_context: str
    committed_context_hash: str
    project: str
    app: str
    rime_candidates: tuple[str, ...]
    must_contain_any: tuple[str, ...]
    must_contain_all: tuple[str, ...]
    must_not_contain: tuple[str, ...]
    must_have_blocked_reasons: tuple[str, ...]
    must_not_have_blocked_reasons: tuple[str, ...]
    min_rag_candidates: int | None
    max_rag_candidates: int | None
    max_optimizer_latency_ms: int | None
    require_trace_id: bool
    memory_state: dict[str, Any]


class _NoopPredictionProvider(PredictionProvider):
    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 3,
        latency_budget_ms: int = 150,
    ):
        del current_input, recent_context, max_candidates, latency_budget_ms
        return []


def load_memory_optimizer_eval_cases(path: Path, *, default_project: str) -> list[MemoryOptimizerEvalCase]:
    cases: list[MemoryOptimizerEvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid JSONL in {path}:{line_number}: {exc}") from exc
        if not isinstance(obj, dict):
            continue
        query = compact_whitespace(
            str(
                obj.get("query")
                or obj.get("rawInput")
                or obj.get("currentInput")
                or obj.get("preedit")
                or ""
            )
        )
        if not query:
            raise SystemExit(f"memory optimizer eval case at {path}:{line_number} is missing query/rawInput")
        case_id = compact_whitespace(str(obj.get("id") or obj.get("caseId") or f"case-{line_number}"))
        cases.append(
            MemoryOptimizerEvalCase(
                case_id=case_id,
                description=compact_whitespace(str(obj.get("description") or "")),
                query=query,
                raw_input=compact_whitespace(_case_string(obj, "rawInput", "currentInput", default=query)),
                preedit=compact_whitespace(_case_string(obj, "preedit", "rawInput", "currentInput", default=query)),
                committed_context=compact_whitespace(_case_string(obj, "committedContext", "recentContext", default="")),
                committed_context_hash=compact_whitespace(str(obj.get("committedContextHash") or "")),
                project=compact_whitespace(str(obj.get("project") or default_project)),
                app=compact_whitespace(str(obj.get("app") or "")),
                rime_candidates=_str_tuple(obj.get("rimeCandidates"), fallback=(query,)),
                must_contain_any=_str_tuple(obj.get("mustContainAny")),
                must_contain_all=_str_tuple(obj.get("mustContainAll")),
                must_not_contain=_str_tuple(obj.get("mustNotContain")),
                must_have_blocked_reasons=_str_tuple(obj.get("mustHaveBlockedReasons")),
                must_not_have_blocked_reasons=_str_tuple(obj.get("mustNotHaveBlockedReasons")),
                min_rag_candidates=_optional_int(obj.get("minRagCandidates")),
                max_rag_candidates=_optional_int(obj.get("maxRagCandidates")),
                max_optimizer_latency_ms=_optional_int(obj.get("maxOptimizerLatencyMs")),
                require_trace_id=bool(obj.get("requireTraceId", True)),
                memory_state=dict(obj.get("memoryState") or {}),
            )
        )
    if not cases:
        raise SystemExit(f"no memory optimizer eval cases found in {path}")
    return cases


def run_memory_optimizer_eval(
    *,
    cases_file: Path,
    project: str,
    repeat: int,
    max_visible_candidates: int,
    max_side_candidates: int,
    latency_budget_ms: int,
    optimizer_max_ms: int,
) -> dict[str, object]:
    cases = load_memory_optimizer_eval_cases(cases_file, default_project=project)
    predictor = _NoopPredictionProvider()
    reports: list[dict[str, object]] = []
    elapsed_ms_by_case: dict[str, int] = {}
    optimizer_latency_by_case: dict[str, float] = {}
    blocked_reason_counts: dict[str, int] = {}
    trace_stored_count = 0

    for repeat_index in range(1, max(1, repeat) + 1):
        for case in cases:
            report = _run_one_case(
                case=case,
                predictor=predictor,
                repeat_index=repeat_index,
                repeat_count=max(1, repeat),
                max_visible_candidates=max_visible_candidates,
                max_side_candidates=max_side_candidates,
                latency_budget_ms=latency_budget_ms,
                optimizer_max_ms=optimizer_max_ms,
            )
            reports.append(report)
            elapsed_ms_by_case[str(report["caseId"])] = int(report["elapsedMs"])
            optimizer_latency_by_case[str(report["caseId"])] = float(report["optimizerLatencyMs"])
            if bool(report.get("traceStored")):
                trace_stored_count += 1
            for reason in report.get("blockedReasons", []):
                if isinstance(reason, str) and reason:
                    blocked_reason_counts[reason] = blocked_reason_counts.get(reason, 0) + 1

    passed_cases = sum(1 for item in reports if bool(item.get("passed")))
    failed_cases = len(reports) - passed_cases
    optimizer_latency = _latency_payload(list(optimizer_latency_by_case.values()))
    gate_passed = (
        failed_cases == 0
        and float(optimizer_latency["p95Ms"]) <= float(max(1, optimizer_max_ms))
        and trace_stored_count == len(reports)
    )
    return {
        "schemaVersion": "rag-ime.memory-optimizer-eval.v1",
        "casesFile": str(cases_file),
        "project": project,
        "repeat": {
            "requested": max(1, repeat),
            "baseCaseCount": len(cases),
            "effectiveCaseCount": len(reports),
        },
        "maxVisibleCandidates": max_visible_candidates,
        "maxSideCandidates": max_side_candidates,
        "latencyBudgetMs": latency_budget_ms,
        "optimizerMaxMs": optimizer_max_ms,
        "caseCount": len(reports),
        "passedCases": passed_cases,
        "failedCases": failed_cases,
        "passRate": (passed_cases / len(reports)) if reports else 0.0,
        "gatePassed": gate_passed,
        "latency": _latency_payload([float(value) for value in elapsed_ms_by_case.values()]),
        "optimizerLatency": optimizer_latency,
        "traceStoredCount": trace_stored_count,
        "blockedReasonCounts": blocked_reason_counts,
        "cases": reports,
    }


def _run_one_case(
    *,
    case: MemoryOptimizerEvalCase,
    predictor: PredictionProvider,
    repeat_index: int,
    repeat_count: int,
    max_visible_candidates: int,
    max_side_candidates: int,
    latency_budget_ms: int,
    optimizer_max_ms: int,
) -> dict[str, object]:
    case_id = case.case_id if repeat_count <= 1 else f"{case.case_id}#r{repeat_index}"
    with tempfile.TemporaryDirectory(prefix="rag-ime-memory-eval-") as tmp:
        db_path = Path(tmp) / "memory-eval.sqlite"
        core = LocalSqliteCoreClient(db_path)
        core.initialize()
        _seed_case_state(core=core, case=case)
        payload = _payload_for_case(
            case=case,
            case_id=case_id,
            max_visible_candidates=max_visible_candidates,
            max_side_candidates=max_side_candidates,
            latency_budget_ms=latency_budget_ms,
        )
        started = time.perf_counter()
        with _temporary_env(
            {
                "RAG_IME_MEMORY_OPTIMIZER": "1",
                "RAG_IME_MEMORY_OPTIMIZER_TRACE": "1",
                "RAG_IME_MEMORY_OPTIMIZER_MAX_MS": str(max(1, optimizer_max_ms)),
            }
        ):
            response = build_rime_sidecar_response(
                payload=payload,
                adapter=InputMethodAdapter(core, project=case.project),
                core=core,
                predictor=predictor,
                default_project=case.project,
            )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        rag_candidates = _eval_candidates(response)
        candidate_haystacks = [_candidate_haystack(item) for item in rag_candidates]
        candidate_surfaces = [compact_whitespace(str(item.get("surfaceText") or item.get("text") or item.get("insertText") or "")) for item in rag_candidates]
        optimizer = response.get("ragLane", {}).get("memoryOptimizer", {}) if isinstance(response.get("ragLane"), dict) else {}
        blocked_reasons = [
            str(item.get("reason") or "")
            for item in optimizer.get("blocked", [])
            if isinstance(item, dict) and str(item.get("reason") or "")
        ]
        trace_id = str(optimizer.get("traceId") or "")
        stored_trace = core.get_memory_optimizer_trace(trace_id) if trace_id else None
        failures = _case_failures(
            case=case,
            candidate_haystacks=candidate_haystacks,
            blocked_reasons=blocked_reasons,
            rag_candidate_count=len(rag_candidates),
            optimizer_latency_ms=float(optimizer.get("latencyMs") or 0.0),
            trace_stored=stored_trace is not None,
        )
        return {
            "caseId": case_id,
            "description": case.description,
            "query": case.query,
            "passed": not failures,
            "failures": failures,
            "elapsedMs": elapsed_ms,
            "optimizerLatencyMs": float(optimizer.get("latencyMs") or 0.0),
            "traceId": trace_id,
            "traceStored": stored_trace is not None,
            "blockedReasons": blocked_reasons,
            "ragCandidateCount": len(rag_candidates),
            "ragCandidateSurfaces": candidate_surfaces,
            "committedContextHash": str(response.get("committedContextHash") or ""),
        }


def _case_failures(
    *,
    case: MemoryOptimizerEvalCase,
    candidate_haystacks: list[str],
    blocked_reasons: list[str],
    rag_candidate_count: int,
    optimizer_latency_ms: float,
    trace_stored: bool,
) -> list[str]:
    failures: list[str] = []
    combined = "\n".join(item.lower() for item in candidate_haystacks)
    if case.must_contain_any and not any(term.lower() in combined for term in case.must_contain_any):
        failures.append(f"missing_any:{','.join(case.must_contain_any)}")
    for term in case.must_contain_all:
        if term.lower() not in combined:
            failures.append(f"missing:{term}")
    for term in case.must_not_contain:
        if term.lower() in combined:
            failures.append(f"forbidden:{term}")
    blocked_set = set(blocked_reasons)
    for reason in case.must_have_blocked_reasons:
        if reason not in blocked_set:
            failures.append(f"missing_blocked_reason:{reason}")
    for reason in case.must_not_have_blocked_reasons:
        if reason in blocked_set:
            failures.append(f"forbidden_blocked_reason:{reason}")
    if case.min_rag_candidates is not None and rag_candidate_count < case.min_rag_candidates:
        failures.append(f"min_rag_candidates:{case.min_rag_candidates}")
    if case.max_rag_candidates is not None and rag_candidate_count > case.max_rag_candidates:
        failures.append(f"max_rag_candidates:{case.max_rag_candidates}")
    if case.max_optimizer_latency_ms is not None and optimizer_latency_ms > case.max_optimizer_latency_ms:
        failures.append(f"optimizer_latency_ms>{case.max_optimizer_latency_ms}")
    if case.require_trace_id and not trace_stored:
        failures.append("trace_not_stored")
    return failures


def _seed_case_state(*, core: LocalSqliteCoreClient, case: MemoryOptimizerEvalCase) -> None:
    for event in case.memory_state.get("events", []):
        if not isinstance(event, dict):
            continue
        core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=int(event.get("createdAtMs") or now_ms()),
                source=str(event.get("source") or "memory-eval"),
                committed_text=str(event.get("text") or event.get("committedText") or ""),
                recent_context=str(event.get("recentContext") or ""),
                preedit=str(event.get("preedit") or ""),
                schema_id=str(event.get("schemaId") or "eval"),
                app=str(event.get("app") or case.app or "eval"),
                project=str(event.get("project") or case.project),
                candidate_rank=None,
                provider_name=str(event.get("providerName") or "memory-eval"),
                tags=tuple(_str_tuple(event.get("tags"))),
            )
        )
    for item in case.memory_state.get("items", []):
        if not isinstance(item, dict):
            continue
        with core._connect() as conn:
            upsert_memory_item(
                conn,
                memory_id=str(item.get("memoryId") or item.get("memory_id") or ""),
                kind=str(item.get("kind") or "stable_memory"),
                text=str(item.get("text") or ""),
                normalized_text=normalize_text(str(item.get("normalizedText") or item.get("text") or "")),
                summary=str(item.get("summary") or ""),
                source_event_id=_optional_int(item.get("sourceEventId")),
                project=str(item.get("project") or case.project),
                app=str(item.get("app") or case.app),
                confidence=float(item.get("confidence") or 0.9),
                quality_score=float(item.get("qualityScore") or 0.9),
                status=str(item.get("status") or "approved"),
                privacy_class=str(item.get("privacyClass") or "local"),
                created_at_ms=int(item.get("createdAtMs") or 1),
                updated_at_ms=int(item.get("updatedAtMs") or item.get("createdAtMs") or 1),
                metadata=dict(item.get("metadata") or {"direct_candidate_allowed": True}),
                tags=tuple(_str_tuple(item.get("tags"))),
                embedding_provider=None,
            )
            conn.commit()
    for feedback in case.memory_state.get("feedback", []):
        if isinstance(feedback, dict):
            core.record_memory_feedback(dict(feedback))
    for tombstone in case.memory_state.get("tombstones", []):
        if not isinstance(tombstone, dict):
            continue
        core.add_memory_tombstone(
            target_type=str(tombstone.get("targetType") or tombstone.get("target_type") or "memory_id"),
            target_value=str(tombstone.get("targetValue") or tombstone.get("target_value") or ""),
            reason=str(tombstone.get("reason") or "memory-eval"),
            metadata=dict(tombstone.get("metadata") or {}),
        )


def _payload_for_case(
    *,
    case: MemoryOptimizerEvalCase,
    case_id: str,
    max_visible_candidates: int,
    max_side_candidates: int,
    latency_budget_ms: int,
) -> dict[str, object]:
    rime_candidates = [
        {"label": str(index), "text": text, "comment": "eval-rime"}
        for index, text in enumerate(case.rime_candidates or (case.query,), start=1)
    ]
    payload: dict[str, object] = {
        "sessionId": f"eval-memory-optimizer:{case_id}",
        "requestSeq": repeat_index_from_case_id(case_id),
        "rawInput": case.raw_input,
        "preedit": case.preedit,
        "committedContext": case.committed_context,
        "project": case.project,
        "app": case.app,
        "latencyBudgetMs": latency_budget_ms,
        "maxVisibleCandidates": max_visible_candidates,
        "maxSideCandidates": max_side_candidates,
        "forceSideCandidates": True,
        "rimeContext": {
            "candidates": rime_candidates,
            "highlightedIndex": 0,
            "page": 0,
            "isLastPage": True,
        },
    }
    if case.committed_context_hash:
        payload["committedContextHash"] = case.committed_context_hash
    return payload


def repeat_index_from_case_id(case_id: str) -> int:
    if "#r" not in case_id:
        return 1
    try:
        return max(1, int(case_id.rsplit("#r", 1)[1]))
    except ValueError:
        return 1


def _eval_candidates(response: dict[str, object]) -> list[dict[str, object]]:
    rag_candidates = response.get("ragCandidates")
    if isinstance(rag_candidates, list):
        return [item for item in rag_candidates if isinstance(item, dict)]
    candidates = response.get("displayCandidates")
    if not isinstance(candidates, list):
        return []
    return [
        item
        for item in candidates
        if isinstance(item, dict) and str(item.get("sourceType") or "") != "rime"
    ]


def _candidate_haystack(item: dict[str, object]) -> str:
    return compact_whitespace(
        " ".join(
            [
                str(item.get("text") or ""),
                str(item.get("surfaceText") or ""),
                str(item.get("insertText") or ""),
                str(item.get("evidencePreview") or ""),
                str(item.get("expandedEvidence") or ""),
            ]
        )
    )


def _latency_payload(values: list[float]) -> dict[str, float | int]:
    sorted_values = sorted(values)
    count = len(sorted_values)
    p50 = sorted_values[count // 2] if sorted_values else 0.0
    p95 = sorted_values[min(count - 1, int(count * 0.95))] if sorted_values else 0.0
    return {
        "caseCount": count,
        "totalMs": round(sum(sorted_values), 3),
        "avgMs": round((sum(sorted_values) / count) if count else 0.0, 3),
        "p50Ms": round(p50, 3),
        "p95Ms": round(p95, 3),
        "maxMs": round(max(sorted_values), 3) if sorted_values else 0.0,
    }


def _str_tuple(value: object, *, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [str(item) for item in value]
    elif isinstance(value, tuple):
        items = [str(item) for item in value]
    else:
        items = list(fallback)
    return tuple(compact_whitespace(item) for item in items if compact_whitespace(item))


def _case_string(obj: dict[str, object], *keys: str, default: str) -> str:
    for key in keys:
        if key in obj and obj.get(key) is not None:
            return str(obj.get(key) or "")
    return default


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
