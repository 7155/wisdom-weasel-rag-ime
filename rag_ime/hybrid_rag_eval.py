from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from .local_sqlite_core import LocalSqliteCoreClient
from .memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from .memory_ingest import normalize_text, upsert_memory_item
from .models import InputEvent, MemoryAction
from .retrieval_docs import rebuild_retrieval_docs
from .text_utils import compact_whitespace, now_ms


HYBRID_RAG_EVAL_SCHEMA_VERSION = "rag-ime.hybrid-rag-eval.v1"


@dataclass(frozen=True)
class HybridRagEvalCase:
    case_id: str
    description: str
    query: str
    raw_input: str
    preedit: str
    committed_context: str
    project: str
    app: str
    rime_candidates: tuple[str, ...]
    must_contain_any: tuple[str, ...]
    must_contain_all: tuple[str, ...]
    must_not_contain: tuple[str, ...]
    must_have_lane: tuple[str, ...]
    must_not_have_lane: tuple[str, ...]
    must_not_contain_raw_sentence: bool
    max_latency_ms: int | None
    top_k: int
    memory_state: dict[str, Any]


def load_hybrid_rag_eval_cases(path: Path, *, default_project: str) -> list[HybridRagEvalCase]:
    cases: list[HybridRagEvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid JSONL in {path}:{line_number}: {exc}") from exc
        if not isinstance(obj, dict):
            raise SystemExit(f"hybrid RAG eval case at {path}:{line_number} must be a JSON object")
        query = compact_whitespace(str(obj.get("query") or obj.get("currentInput") or obj.get("rawInput") or ""))
        if not query:
            raise SystemExit(f"hybrid RAG eval case at {path}:{line_number} is missing query/rawInput")
        cases.append(
            HybridRagEvalCase(
                case_id=compact_whitespace(str(obj.get("id") or obj.get("caseId") or f"case-{line_number}")),
                description=compact_whitespace(str(obj.get("description") or "")),
                query=query,
                raw_input=compact_whitespace(_case_string(obj, "rawInput", "currentInput", default=query)),
                preedit=compact_whitespace(_case_string(obj, "preedit", "rawInput", "currentInput", default=query)),
                committed_context=compact_whitespace(_case_string(obj, "committedContext", "recentContext", default="")),
                project=compact_whitespace(str(obj.get("project") or default_project)),
                app=compact_whitespace(str(obj.get("app") or "")),
                rime_candidates=_str_tuple(obj.get("rimeCandidates"), fallback=(query,)),
                must_contain_any=_str_tuple(obj.get("mustContainAny")),
                must_contain_all=_str_tuple(obj.get("mustContainAll")),
                must_not_contain=_str_tuple(obj.get("mustNotContain")),
                must_have_lane=_str_tuple(obj.get("mustHaveLane")),
                must_not_have_lane=_str_tuple(obj.get("mustNotHaveLane")),
                must_not_contain_raw_sentence=bool(obj.get("mustNotContainRawSentence", False)),
                max_latency_ms=_optional_int(obj.get("maxLatencyMs")),
                top_k=max(1, int(obj.get("topK") or 5)),
                memory_state=dict(obj.get("memoryState") or {}),
            )
        )
    if not cases:
        raise SystemExit(f"no hybrid RAG eval cases found in {path}")
    return cases


def run_hybrid_rag_eval(
    *,
    cases_file: Path,
    project: str,
    repeat: int,
    top_k: int = 5,
    latency_budget_ms: int = 25,
    include_cases: bool = True,
) -> dict[str, object]:
    cases = load_hybrid_rag_eval_cases(cases_file, default_project=project)
    reports: list[dict[str, object]] = []
    for repeat_index in range(1, max(1, repeat) + 1):
        for case in cases:
            reports.append(
                _run_one_case(
                    case=case,
                    repeat_index=repeat_index,
                    repeat_count=max(1, repeat),
                    top_k=top_k,
                    latency_budget_ms=latency_budget_ms,
                )
            )

    passed_cases = sum(1 for item in reports if bool(item.get("passed")))
    failed_cases = len(reports) - passed_cases
    latencies = [float(item.get("elapsedMs") or 0.0) for item in reports]
    metrics = _metrics(reports, latencies=latencies)
    gate_passed = failed_cases == 0 and metrics["rawSentenceLeakRate"] == 0.0 and metrics["tombstoneLeakRate"] == 0.0
    return {
        "schemaVersion": HYBRID_RAG_EVAL_SCHEMA_VERSION,
        "casesFile": str(cases_file),
        "project": project,
        "repeat": {
            "requested": max(1, repeat),
            "baseCaseCount": len(cases),
            "effectiveCaseCount": len(reports),
        },
        "topK": max(1, int(top_k)),
        "latencyBudgetMs": max(1, int(latency_budget_ms)),
        "caseCount": len(reports),
        "passedCases": passed_cases,
        "failedCases": failed_cases,
        "passRate": (passed_cases / len(reports)) if reports else 0.0,
        "gatePassed": gate_passed,
        "metrics": metrics,
        "cases": reports if include_cases else [],
    }


def _run_one_case(
    *,
    case: HybridRagEvalCase,
    repeat_index: int,
    repeat_count: int,
    top_k: int,
    latency_budget_ms: int,
) -> dict[str, object]:
    case_id = case.case_id if repeat_count <= 1 else f"{case.case_id}#r{repeat_index}"
    with tempfile.TemporaryDirectory(prefix="rag-ime-hybrid-rag-eval-") as tmp:
        db_path = Path(tmp) / "hybrid-rag-eval.sqlite"
        core = LocalSqliteCoreClient(db_path)
        core.initialize()
        _seed_case_state(core=core, case=case)
        started = time.perf_counter()
        with core._connect() as conn:  # type: ignore[attr-defined]
            rebuild_retrieval_docs(conn, project=case.project)
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text=case.query,
                    raw_input=case.raw_input,
                    preedit=case.preedit,
                    committed_tail=case.committed_context,
                    rime_candidates=case.rime_candidates,
                    project=case.project,
                    app=case.app,
                    top_k=max(1, int(top_k or case.top_k)),
                    latency_budget_ms=max(1, int(latency_budget_ms)),
                ),
            )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
    candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
    lanes = payload.get("lanes") if isinstance(payload.get("lanes"), dict) else {}
    top3_texts = [compact_whitespace(str(item.get("text") or item.get("insert_text") or "")) for item in candidates[:3]]
    all_texts = [compact_whitespace(str(item.get("text") or item.get("insert_text") or "")) for item in candidates]
    raw_sentences = _raw_sentences(case)
    failures = _case_failures(
        case=case,
        top3_texts=top3_texts,
        all_texts=all_texts,
        lanes=lanes,
        raw_sentences=raw_sentences,
        elapsed_ms=elapsed_ms,
    )
    return {
        "caseId": case_id,
        "description": case.description,
        "passed": not failures,
        "failures": failures,
        "elapsedMs": elapsed_ms,
        "retrieverElapsedMs": int(payload.get("elapsedMs") or 0),
        "overBudget": bool(payload.get("overBudget")) or (case.max_latency_ms is not None and elapsed_ms > case.max_latency_ms),
        "top3Texts": top3_texts,
        "candidateTexts": all_texts,
        "lanes": {
            str(name): {
                "count": int(value.get("count") or 0) if isinstance(value, dict) else 0,
                "docIds": list(value.get("docIds") or []) if isinstance(value, dict) else [],
            }
            for name, value in lanes.items()
        },
        "rawSentenceLeak": _has_raw_sentence_leak(all_texts, raw_sentences),
        "oldInputEcho": _has_old_input_echo(all_texts, case=case),
        "tombstoneLeak": _has_tombstone_leak(all_texts, case=case),
        "duplicateSurface": _has_duplicate_surface(all_texts),
    }


def _seed_case_state(*, core: LocalSqliteCoreClient, case: HybridRagEvalCase) -> None:
    memory_state = case.memory_state
    for event in _list_of_dicts(memory_state.get("events")):
        core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=int(event.get("createdAtMs") or now_ms()),
                source=str(event.get("source") or "hybrid-rag-eval"),
                committed_text=str(event.get("text") or event.get("committedText") or ""),
                recent_context=str(event.get("recentContext") or ""),
                preedit=str(event.get("preedit") or ""),
                schema_id=str(event.get("schemaId") or "hybrid-rag-eval"),
                app=str(event.get("app") or case.app or "eval"),
                project=str(event.get("project") or case.project),
                provider_name=str(event.get("providerName") or "hybrid-rag-eval"),
                tags=tuple(_str_tuple(event.get("tags"))),
            )
        )
    _apply_memory_book_state(core=core, case=case)
    _apply_item_state(core=core, case=case)
    for feedback in _list_of_dicts(memory_state.get("feedback")):
        core.record_memory_feedback(dict(feedback))
    if _list_of_dicts(memory_state.get("feedback")):
        with core._connect() as conn:  # type: ignore[attr-defined]
            for feedback in _list_of_dicts(memory_state.get("feedback")):
                memory_id = compact_whitespace(str(feedback.get("memoryId") or feedback.get("memory_id") or ""))
                candidate_text = compact_whitespace(str(feedback.get("candidateText") or feedback.get("text") or ""))
                action = compact_whitespace(str(feedback.get("action") or feedback.get("event") or "accepted"))
                if not memory_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO candidate_feedback(
                        created_at_ms, query_hash, candidate_text, source_type, memory_id, action, app, project, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(feedback.get("createdAtMs") or now_ms()),
                        str(feedback.get("queryHash") or "eval"),
                        candidate_text,
                        str(feedback.get("sourceType") or "phrase"),
                        memory_id,
                        action,
                        str(feedback.get("app") or case.app),
                        str(feedback.get("project") or case.project),
                        json.dumps(dict(feedback.get("metadata") or {}), ensure_ascii=False, sort_keys=True),
                    ),
                )
    for action in _list_of_dicts(memory_state.get("actions")):
        core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=int(action.get("createdAtMs") or now_ms()),
                memory_id=str(action.get("memoryId") or action.get("memory_id") or ""),
                action_type=str(action.get("actionType") or action.get("action_type") or "accepted"),
                query=str(action.get("query") or case.query),
                metadata=dict(action.get("metadata") or {}),
            )
        )
    for tombstone in _list_of_dicts(memory_state.get("tombstones")):
        core.add_memory_tombstone(
            target_type=str(tombstone.get("targetType") or tombstone.get("target_type") or "memory_id"),
            target_value=str(tombstone.get("targetValue") or tombstone.get("target_value") or ""),
            reason=str(tombstone.get("reason") or "hybrid-rag-eval"),
            metadata=dict(tombstone.get("metadata") or {}),
        )
    if _list_of_dicts(memory_state.get("suppressions")):
        with core._connect() as conn:  # type: ignore[attr-defined]
            for suppression in _list_of_dicts(memory_state.get("suppressions")):
                match_type = compact_whitespace(str(suppression.get("matchType") or suppression.get("match_type") or "memory_id"))
                match_value = compact_whitespace(str(suppression.get("matchValue") or suppression.get("match_value") or ""))
                if not match_type or not match_value:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_candidate_suppressions(
                        id, match_type, match_value, action, reason, strength, created_at_ms
                    )
                    VALUES (?, ?, ?, 'block', ?, ?, ?)
                    """,
                    (
                        f"eval:suppression:{normalize_text(match_type + ':' + match_value)[:48]}",
                        match_type,
                        match_value,
                        str(suppression.get("reason") or "hybrid-rag-eval"),
                        float(suppression.get("strength") or 1.0),
                        now_ms(),
                    ),
                )


def _apply_memory_book_state(*, core: LocalSqliteCoreClient, case: HybridRagEvalCase) -> None:
    memory_state = case.memory_state
    books = _list_of_dicts(memory_state.get("books"))
    atoms = _list_of_dicts(memory_state.get("memoryAtoms") or memory_state.get("atoms"))
    edges = _list_of_dicts(memory_state.get("tagEdges"))
    phrases = _list_of_dicts(memory_state.get("phraseCandidates") or memory_state.get("phrases"))
    if not any((books, atoms, edges, phrases)):
        return
    _ensure_source_events(core=core, case=case, ids=_memory_book_source_ids(books=books, atoms=atoms, edges=edges, phrases=phrases))
    compile_output = {
        "schemaVersion": "rag-ime.memory-book-compile.v1",
        "dailyBooks": [_book_payload(item, case=case, index=index) for index, item in enumerate(books, start=1)],
        "memoryAtoms": atoms,
        "tagEdges": [_tag_edge_payload(item) for item in edges],
        "phraseCandidates": [_phrase_payload(item, case=case) for item in phrases],
        "warnings": [],
    }
    plan = memory_book_plan_from_compile_output(
        compile_output,
        project=case.project,
        provider="hybrid-rag-eval",
        model="fixture",
    )
    with core._connect() as conn:  # type: ignore[attr-defined]
        apply_memory_book_plan(conn, plan)


def _ensure_source_events(*, core: LocalSqliteCoreClient, case: HybridRagEvalCase, ids: tuple[int, ...]) -> None:
    if not ids:
        return
    with core._connect() as conn:  # type: ignore[attr-defined]
        for event_id in ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO input_events(
                    id, created_at_ms, source, committed_text, recent_context, preedit,
                    schema_id, app, project, candidate_rank, provider_name, tags_json
                )
                VALUES (?, ?, 'hybrid-rag-eval-source', ?, '', '', 'hybrid-rag-eval', ?, ?, NULL, 'hybrid-rag-eval', '[]')
                """,
                (
                    event_id,
                    now_ms(),
                    f"hybrid RAG eval source event {event_id}",
                    case.app or "eval",
                    case.project,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO memory_state(event_id, updated_at_ms) VALUES (?, ?)",
                (event_id, now_ms()),
            )
        conn.commit()


def _memory_book_source_ids(
    *,
    books: list[dict[str, object]],
    atoms: list[dict[str, object]],
    edges: list[dict[str, object]],
    phrases: list[dict[str, object]],
) -> tuple[int, ...]:
    ids: set[int] = set()
    for item in [*books, *atoms, *phrases]:
        ids.update(_positive_ints(item.get("sourceEventIds")))
    for item in edges:
        ids.update(_positive_ints(item.get("evidenceEventIds")))
    return tuple(sorted(ids or {1}))


def _apply_item_state(*, core: LocalSqliteCoreClient, case: HybridRagEvalCase) -> None:
    with core._connect() as conn:  # type: ignore[attr-defined]
        for item in _list_of_dicts(case.memory_state.get("items")):
            text = compact_whitespace(str(item.get("text") or ""))
            if not text:
                continue
            memory_id = compact_whitespace(str(item.get("memoryId") or item.get("memory_id") or f"item:{normalize_text(text)[:32]}"))
            upsert_memory_item(
                conn,
                memory_id=memory_id,
                kind=str(item.get("kind") or "stable_memory"),
                text=text,
                normalized_text=normalize_text(str(item.get("normalizedText") or text)),
                summary=str(item.get("summary") or ""),
                source_event_id=_optional_int(item.get("sourceEventId")),
                project=str(item.get("project") or case.project),
                app=str(item.get("app") or case.app),
                confidence=float(item.get("confidence") or 0.9),
                quality_score=float(item.get("qualityScore") or 0.9),
                status=str(item.get("status") or "approved"),
                privacy_class=str(item.get("privacyClass") or "local"),
                created_at_ms=int(item.get("createdAtMs") or now_ms()),
                updated_at_ms=int(item.get("updatedAtMs") or item.get("createdAtMs") or now_ms()),
                metadata=dict(item.get("metadata") or {"direct_candidate_allowed": True}),
                tags=tuple(_str_tuple(item.get("tags"))),
                embedding_provider=None,
            )


def _case_failures(
    *,
    case: HybridRagEvalCase,
    top3_texts: list[str],
    all_texts: list[str],
    lanes: object,
    raw_sentences: tuple[str, ...],
    elapsed_ms: int,
) -> list[str]:
    failures: list[str] = []
    if case.must_contain_any and not any(_contains_any(text, case.must_contain_any) for text in top3_texts):
        failures.append(f"missing_top3_any:{'|'.join(case.must_contain_any)}")
    for expected in case.must_contain_all:
        if not any(expected in text for text in top3_texts):
            failures.append(f"missing_top3:{expected}")
    for forbidden in case.must_not_contain:
        if any(forbidden and forbidden in text for text in all_texts):
            failures.append(f"forbidden_candidate:{forbidden}")
    lane_names = _lane_names(lanes)
    for lane in case.must_have_lane:
        if lane not in lane_names:
            failures.append(f"missing_lane:{lane}")
        elif _lane_count(lanes, lane) <= 0:
            failures.append(f"empty_lane:{lane}")
    for lane in case.must_not_have_lane:
        if lane in lane_names and _lane_count(lanes, lane) > 0:
            failures.append(f"forbidden_lane:{lane}")
    if case.must_not_contain_raw_sentence and _has_raw_sentence_leak(all_texts, raw_sentences):
        failures.append("raw_sentence_leak")
    if case.max_latency_ms is not None and elapsed_ms > case.max_latency_ms:
        failures.append(f"latency:{elapsed_ms}>{case.max_latency_ms}")
    if _has_tombstone_leak(all_texts, case=case):
        failures.append("tombstone_leak")
    if _has_duplicate_surface(all_texts):
        failures.append("duplicate_surface")
    return failures


def _metrics(reports: list[dict[str, object]], *, latencies: list[float]) -> dict[str, object]:
    total = max(1, len(reports))
    return {
        "hybridHitAt3": _rate(reports, lambda item: bool(item.get("passed")) or not _has_failure(item, "missing_top3_any")),
        "bm25TagHitAt3": _lane_rate(reports, "bm25_tags"),
        "tagMemoHitAt3": _lane_rate(reports, "tagmemo"),
        "timeBookHitAt3": _lane_rate(reports, "time"),
        "vectorTagBoostWinRate": _lane_rate(reports, "vector_tag_boost"),
        "rawSentenceLeakRate": sum(1 for item in reports if bool(item.get("rawSentenceLeak"))) / total,
        "oldInputEchoRate": sum(1 for item in reports if bool(item.get("oldInputEcho"))) / total,
        "tombstoneLeakRate": sum(1 for item in reports if bool(item.get("tombstoneLeak"))) / total,
        "duplicateSurfaceRate": sum(1 for item in reports if bool(item.get("duplicateSurface"))) / total,
        "p95LatencyMs": _percentile(latencies, 0.95),
        "deepseekFirstCandidateMs": None,
        "deepseekPartialCandidateRate": None,
        "deepseekFilteredOutputRate": None,
    }


def _lane_rate(reports: list[dict[str, object]], lane: str) -> float:
    requiring = [item for item in reports if lane in _case_required_lanes(item)]
    if not requiring:
        return 0.0
    return sum(1 for item in requiring if _lane_count(item.get("lanes"), lane) > 0) / len(requiring)


def _case_required_lanes(report: dict[str, object]) -> set[str]:
    return {
        failure.split(":", 1)[1]
        for failure in report.get("failures", [])
        if isinstance(failure, str) and failure.startswith("missing_lane:")
    } | {
        name
        for name, payload in (report.get("lanes") or {}).items()
        if isinstance(name, str) and isinstance(payload, dict) and int(payload.get("count") or 0) > 0
    }


def _has_failure(item: dict[str, object], prefix: str) -> bool:
    return any(isinstance(failure, str) and failure.startswith(prefix) for failure in item.get("failures", []))


def _rate(reports: list[dict[str, object]], predicate) -> float:
    if not reports:
        return 0.0
    return sum(1 for item in reports if predicate(item)) / len(reports)


def _raw_sentences(case: HybridRagEvalCase) -> tuple[str, ...]:
    values: list[str] = []
    for event in _list_of_dicts(case.memory_state.get("events")):
        text = compact_whitespace(str(event.get("text") or event.get("committedText") or ""))
        if len(text) > 16:
            values.append(text)
    return tuple(values)


def _has_raw_sentence_leak(texts: list[str], raw_sentences: tuple[str, ...]) -> bool:
    return any(sentence and any(text == sentence or sentence in text for text in texts) for sentence in raw_sentences)


def _has_old_input_echo(texts: list[str], *, case: HybridRagEvalCase) -> bool:
    tail = compact_whitespace(case.committed_context)
    raw_input = compact_whitespace(case.raw_input)
    return any(text and ((tail and text in tail[-120:]) or (raw_input and text == raw_input and len(text) > 8)) for text in texts)


def _has_tombstone_leak(texts: list[str], *, case: HybridRagEvalCase) -> bool:
    blocked_texts = {
        compact_whitespace(str(item.get("text") or item.get("targetValue") or item.get("target_value") or ""))
        for item in _list_of_dicts(case.memory_state.get("tombstones"))
    }
    blocked_texts |= {
        compact_whitespace(str(item.get("matchValue") or item.get("match_value") or ""))
        for item in _list_of_dicts(case.memory_state.get("suppressions"))
        if str(item.get("matchType") or item.get("match_type") or "") in {"normalized_text", "text"}
    }
    blocked_texts = {item for item in blocked_texts if item}
    return any(blocked and any(blocked in text or normalize_text(blocked) == normalize_text(text) for text in texts) for blocked in blocked_texts)


def _has_duplicate_surface(texts: list[str]) -> bool:
    compacted = [normalize_text(text) for text in texts if compact_whitespace(text)]
    return len(compacted) != len(set(compacted))


def _book_payload(item: dict[str, object], *, case: HybridRagEvalCase, index: int) -> dict[str, object]:
    source_ids = _positive_ints(item.get("sourceEventIds")) or (1,)
    book_id = compact_whitespace(str(item.get("bookId") or f"book:eval:{case.case_id}:{index}"))
    book_key = compact_whitespace(str(item.get("bookKey") or book_id.rsplit(":", 1)[-1] or case.case_id))
    return {
        **item,
        "bookId": book_id,
        "bookKey": book_key,
        "bookType": compact_whitespace(str(item.get("bookType") or "daily")),
        "project": compact_whitespace(str(item.get("project") or case.project)),
        "sourceEventIds": list(source_ids),
    }


def _tag_edge_payload(item: dict[str, object]) -> dict[str, object]:
    return {
        "src": compact_whitespace(str(item.get("src") or "")),
        "dst": compact_whitespace(str(item.get("dst") or "")),
        "edgeType": compact_whitespace(str(item.get("edgeType") or "related")),
        "weight": float(item.get("weight") or 0.5),
        "evidenceEventIds": list(_positive_ints(item.get("evidenceEventIds"))) or [1],
    }


def _phrase_payload(item: dict[str, object], *, case: HybridRagEvalCase) -> dict[str, object]:
    return {
        **item,
        "text": compact_whitespace(str(item.get("text") or "")),
        "project": compact_whitespace(str(item.get("project") or case.project)),
        "sourceEventIds": list(_positive_ints(item.get("sourceEventIds"))) or [1],
    }


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value and value in text for value in values)


def _lane_names(lanes: object) -> set[str]:
    return set(lanes.keys()) if isinstance(lanes, dict) else set()


def _lane_count(lanes: object, lane: str) -> int:
    if not isinstance(lanes, dict):
        return 0
    payload = lanes.get(lane)
    if not isinstance(payload, dict):
        return 0
    return int(payload.get("count") or 0)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * max(0.0, min(1.0, q))))
    return float(ordered[index])


def _case_string(obj: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = obj.get(key)
        if value is not None:
            return str(value)
    return default


def _str_tuple(value: object, fallback: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return fallback
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = [str(item) for item in value]
    else:
        values = [str(value)]
    result = tuple(compact_whitespace(item) for item in values if compact_whitespace(item))
    return result or fallback


def _positive_ints(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple)) else [value]
    result: list[int] = []
    for item in raw_values:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.append(number)
    return tuple(result)


def _optional_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
