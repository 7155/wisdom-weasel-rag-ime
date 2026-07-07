from __future__ import annotations

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .active_rag_service import ActiveRagService, ActiveRagStartRequest
from .local_sqlite_core import LocalSqliteCoreClient
from .memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from .models import InputEvent
from .retrieval_docs import rebuild_retrieval_docs
from .text_utils import compact_whitespace, now_ms, stable_text_hash


ACTIVE_RAG_EVAL_SCHEMA_VERSION = "rag-ime.active-rag-eval.v1"


def run_active_rag_eval(
    *,
    db_path: Path | None = None,
    cases_file: Path,
    project: str = "wisdom-weasel-rag-ime",
    repeat: int = 1,
    max_candidates: int = 5,
    ready_budget_ms: int = 3000,
) -> dict[str, object]:
    cases = _load_cases(cases_file)
    if db_path is None:
        with TemporaryDirectory(prefix="rag-ime-active-rag-eval-") as temp_dir:
            temp_db = Path(temp_dir) / "active-rag-eval.sqlite"
            return _run_eval_on_db(
                db_path=temp_db,
                cases=cases,
                project=project,
                repeat=repeat,
                max_candidates=max_candidates,
                ready_budget_ms=ready_budget_ms,
                seed_cases=True,
            )
    return _run_eval_on_db(
        db_path=db_path,
        cases=cases,
        project=project,
        repeat=repeat,
        max_candidates=max_candidates,
        ready_budget_ms=ready_budget_ms,
        seed_cases=False,
    )


def _run_eval_on_db(
    *,
    db_path: Path,
    cases: list[dict[str, Any]],
    project: str,
    repeat: int,
    max_candidates: int,
    ready_budget_ms: int,
    seed_cases: bool,
) -> dict[str, object]:
    core = LocalSqliteCoreClient(db_path)
    core.initialize()
    if seed_cases:
        _seed_active_rag_cases(core, cases=cases, project=project)
    service = ActiveRagService(core=core)
    case_reports: list[dict[str, object]] = []
    latencies: list[int] = []
    for run_index in range(max(1, int(repeat))):
        for case_index, case in enumerate(cases, start=1):
            selected_text = compact_whitespace(str(case.get("selectedText") or case.get("query") or ""))
            request = ActiveRagStartRequest(
                selected_text=selected_text,
                selected_text_hash=stable_text_hash(selected_text),
                frontend_revision=run_index + 1,
                selection_epoch=case_index,
                panel_session_id=f"eval-panel-{run_index}-{case_index}",
                front_app_bundle_id=str(case.get("frontAppBundleId") or "eval.active-rag"),
                surrounding_before=str(case.get("surroundingBefore") or ""),
                surrounding_after=str(case.get("surroundingAfter") or ""),
                intent=str(case.get("intent") or "rewrite"),
                placement=str(case.get("placement") or "replace_selection"),
                project=project,
                app=str(case.get("app") or ""),
                max_candidates=max_candidates,
            )
            started_at = time.perf_counter()
            started = service.start(request)
            first_status_ms = int((time.perf_counter() - started_at) * 1000)
            ready = _wait_ready(service, str(started["sessionId"]), budget_ms=ready_budget_ms)
            ready_ms = int((time.perf_counter() - started_at) * 1000)
            latencies.append(ready_ms)
            candidate_texts = [str(item.get("text") or "") for item in ready.get("candidates", []) if isinstance(item, dict)]
            expected = [compact_whitespace(str(item)) for item in case.get("expectedTerms", []) if compact_whitespace(str(item))]
            leaks_selected = any(selected_text and len(selected_text) > 8 and selected_text in text for text in candidate_texts)
            stale_accept = service.accept(
                session_id=str(started["sessionId"]),
                candidate_id=str(ready.get("candidates", [{}])[0].get("candidateId") if ready.get("candidates") else "missing"),
                selected_text_hash=stable_text_hash(selected_text + " stale"),
                frontend_revision=request.frontend_revision,
                selection_epoch=request.selection_epoch,
            )
            matched = [term for term in expected if any(term in candidate for candidate in candidate_texts)]
            passed = (
                ready.get("status") == "ready"
                and first_status_ms <= 100
                and ready_ms <= ready_budget_ms
                and bool(candidate_texts)
                and not leaks_selected
                and stale_accept.get("reason") == "selected_text_hash_mismatch"
                and (not expected or bool(matched))
            )
            case_reports.append(
                {
                    "caseId": str(case.get("id") or f"case-{case_index}"),
                    "passed": passed,
                    "status": ready.get("status"),
                    "firstStatusMs": first_status_ms,
                    "readyMs": ready_ms,
                    "candidateTexts": candidate_texts,
                    "matchedTerms": matched,
                    "leaksSelectedText": leaks_selected,
                    "staleAcceptReason": stale_accept.get("reason"),
                }
            )
    passed_count = sum(1 for item in case_reports if item.get("passed"))
    total = len(case_reports)
    return {
        "schemaVersion": ACTIVE_RAG_EVAL_SCHEMA_VERSION,
        "gatePassed": total > 0 and passed_count == total,
        "project": project,
        "caseCount": total,
        "passedCount": passed_count,
        "failedCount": total - passed_count,
        "maxReadyMs": max(latencies) if latencies else 0,
        "cases": case_reports,
    }


def _seed_active_rag_cases(core: LocalSqliteCoreClient, *, cases: list[dict[str, Any]], project: str) -> None:
    compile_output = {
        "schemaVersion": "rag-ime.active-rag-eval-seed.v1",
        "memoryAtoms": [],
        "tagEdges": [],
        "phraseCandidates": [],
    }
    event_ids: dict[int, int] = {}
    base_ms = now_ms()
    for index, case in enumerate(cases, start=1):
        event_ref = core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=base_ms + index,
                source="active_rag_eval_seed",
                committed_text=compact_whitespace(str(case.get("memoryText") or case.get("selectedText") or case.get("query") or f"Active RAG case {index}")),
                recent_context=compact_whitespace(str(case.get("selectedText") or case.get("query") or "")),
                app="eval.active-rag",
                project=project,
                provider_name="local-eval-seed",
                tags=tuple(str(tag) for tag in case.get("tags", []) if str(tag)),
            )
        )
        event_ids[index] = int(str(event_ref).split(":")[-1])
    for index, case in enumerate(cases, start=1):
        tags = [str(tag) for tag in case.get("tags", [])] or ["active-rag"]
        expected_terms = [compact_whitespace(str(item)) for item in case.get("expectedTerms", []) if compact_whitespace(str(item))]
        title = compact_whitespace(str(case.get("title") or (expected_terms[0] if expected_terms else f"Active RAG case {index}")))
        atom_id = f"active_rag_eval_atom_{index}"
        compile_output["memoryAtoms"].append(
            {
                "id": atom_id,
                "kind": "preference",
                "text": compact_whitespace(str(case.get("memoryText") or title)),
                "canonicalText": compact_whitespace(str(case.get("memoryText") or title)),
                "tags": tags,
                "aliases": expected_terms,
                "surfaceHints": expected_terms or [title],
                "queryExpansions": [str(case.get("selectedText") or case.get("query") or ""), *tags],
                "confidence": 0.92,
                "qualityScore": 0.9,
                "scopeProject": project,
                "scopeApp": "",
                "sourceEventIds": [event_ids[index]],
                "metadata": {"source": "active_rag_eval_seed"},
            }
        )
        for phrase in expected_terms:
            compile_output["phraseCandidates"].append(
                {
                    "text": phrase,
                    "tags": tags,
                    "project": project,
                    "app": "",
                    "sourceEventIds": [event_ids[index]],
                    "metadata": {"source": "active_rag_eval_seed", "atomId": atom_id},
                }
            )
    with core._connect() as conn:
        plan = memory_book_plan_from_compile_output(
            compile_output,
            project=project,
            provider="local-eval-seed",
            model="active-rag-eval",
        )
        apply_memory_book_plan(conn, plan)
        rebuild_retrieval_docs(conn, project=project)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"invalid case at {path}:{line_number}: expected object")
            cases.append(item)
    if not cases:
        raise ValueError(f"no active rag eval cases found: {path}")
    return cases


def _wait_ready(service: ActiveRagService, session_id: str, *, budget_ms: int) -> dict[str, object]:
    deadline = time.monotonic() + max(1, int(budget_ms)) / 1000.0
    last = service.status(session_id)
    while time.monotonic() < deadline:
        last = service.status(session_id)
        if last.get("status") in {"ready", "error", "stale_dropped", "cancelled"}:
            return last
        time.sleep(0.01)
    return last
