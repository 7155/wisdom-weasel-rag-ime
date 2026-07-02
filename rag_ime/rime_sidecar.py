from __future__ import annotations

import time
from dataclasses import dataclass
from threading import BoundedSemaphore, Event, RLock, Thread
from typing import Any

from .adapter import InputMethodAdapter, SuggestionRequest
from .core_client import CoreClient
from .history_context import build_prediction_context, model_prediction_context_limits, prediction_context_metadata
from .models import (
    InputSuggestion,
    MemoryAction,
    ModelPrediction,
    RimeCandidate,
    RimeContextSnapshot,
    SideCandidateDisplayItem,
)
from .payloads import action_response_payload, model_prediction_to_payload, suggestion_to_payload
from .prediction_first import infer_input_mode, merge_prediction_first_candidates
from .predictor import PredictionProvider
from .text_utils import compact_whitespace, now_ms


RIME_SIDECAR_SCHEMA_VERSION = "rag-ime.rime-sidecar.v1"
_SEMANTIC_ASCII_TERMS = {
    "agent",
    "bm25",
    "brew",
    "cargo",
    "codex",
    "curl",
    "fts5",
    "git",
    "github",
    "kv",
    "llm",
    "mlx",
    "npm",
    "pi",
    "pip",
    "python",
    "qwen",
    "rag",
    "rime",
    "rust",
    "sqlite",
    "squirrel",
    "swift",
    "uv",
    "vcp",
    "xcode",
    "xcodebuild",
}
_RAW_COMMIT_ASCII_TERMS = {
    "brew",
    "cargo",
    "codex",
    "curl",
    "git",
    "github",
    "npm",
    "pip",
    "python",
    "pytest",
    "rust",
    "swift",
    "uv",
    "xcodebuild",
}
_SHELL_COMMAND_PREFIXES = _RAW_COMMIT_ASCII_TERMS | {
    "cat",
    "cd",
    "cp",
    "grep",
    "head",
    "less",
    "ls",
    "mkdir",
    "mv",
    "open",
    "rg",
    "sed",
    "tail",
}
_RAG_LANE_SEMAPHORE = BoundedSemaphore(1)
_MODEL_LANE_SEMAPHORE = BoundedSemaphore(1)
_MODEL_HOLDOVER_TTL_MS = 900
_MODEL_HOLDOVER_LOCK = RLock()
_MODEL_HOLDOVERS: dict[tuple[str, str], "_ModelPredictionHoldover"] = {}


@dataclass(frozen=True)
class RimeSideCandidateTriggerDecision:
    should_refresh: bool
    reason: str


@dataclass(frozen=True)
class _ModelPredictionHoldover:
    project: str
    explicit_context_fingerprint: str
    predictions: tuple[ModelPrediction, ...]
    created_at: float


def build_rime_sidecar_response(
    *,
    payload: dict[str, Any],
    adapter: InputMethodAdapter,
    core: CoreClient,
    predictor: PredictionProvider,
    default_project: str = "wisdom-weasel-rag-ime",
) -> dict[str, object]:
    snapshot = parse_rime_context_payload(payload, default_project=default_project)
    semantic_query, query_basis = choose_semantic_query(snapshot)
    trigger_decision = decide_side_candidate_refresh(
        snapshot=snapshot,
        semantic_query=semantic_query,
        query_basis=query_basis,
    )
    if trigger_decision.should_refresh:
        lane_started = time.perf_counter()
        suggestions, rag_lane, model_predictions, model_lane = run_side_lanes_with_latency_budget(
            adapter=adapter,
            core=core,
            predictor=predictor,
            current_input=semantic_query,
            recent_context=snapshot.committed_context,
            explicit_recent_context=snapshot.committed_context,
            project=snapshot.project or default_project,
            app=snapshot.app,
            top_k=snapshot.max_side_candidates,
            max_candidates=snapshot.max_side_candidates,
            latency_budget_ms=snapshot.latency_budget_ms,
        )
        prediction_context = _string(model_lane.get("historyContext"))
        model_lane.pop("historyContext", None)
        total_elapsed_ms = int((time.perf_counter() - lane_started) * 1000)
        rag_lane.update(
            {
                "totalLatencyBudgetMs": snapshot.latency_budget_ms,
                "sideLaneMode": "parallel",
                "sideLaneElapsedMs": total_elapsed_ms,
            }
        )
        model_lane.update(
            {
                "totalLatencyBudgetMs": snapshot.latency_budget_ms,
                "elapsedBeforeModelMs": 0,
                "sideLaneMode": "parallel",
                "sideLaneElapsedMs": total_elapsed_ms,
            }
        )
    else:
        prediction_context = ""
        model_predictions = []
        suggestions = []
        rag_lane = {
            "called": False,
            "timedOut": False,
            "skippedReason": "side candidates disabled by trigger",
            "suggestionCount": 0,
            "latencyBudgetMs": 0,
            "elapsedMs": 0,
            "totalLatencyBudgetMs": snapshot.latency_budget_ms,
        }
        model_lane = {
            "called": False,
            "timedOut": False,
            "skippedReason": "side candidates disabled by trigger",
            "predictionCount": 0,
            "latencyBudgetMs": 0,
            "elapsedMs": 0,
            "totalLatencyBudgetMs": snapshot.latency_budget_ms,
            "elapsedBeforeModelMs": 0,
        }
    prediction_first_enabled = _bool(payload.get("predictionFirstMerge"), default=False)
    if prediction_first_enabled:
        prediction_first_result = merge_prediction_first_candidates(
            snapshot=snapshot,
            model_predictions=model_predictions,
            suggestions=suggestions,
            raw_commit_text=raw_english_candidate_text(snapshot),
        )
        display_candidates = list(prediction_first_result.display_candidates)
        prediction_first_payload: dict[str, object] = {
            "enabled": True,
            "mode": prediction_first_result.mode.value,
            "pinyinPrefix": prediction_first_result.pinyin_prefix,
            "policy": prediction_first_result.policy,
        }
    else:
        display_candidates = merge_display_candidates(
            snapshot=snapshot,
            model_predictions=model_predictions,
            suggestions=suggestions,
        )
        input_mode = infer_input_mode(snapshot)
        prediction_first_payload = {
            "enabled": False,
            "mode": input_mode.value,
            "pinyinPrefix": snapshot.preedit or snapshot.raw_input,
            "policy": {
                "engine": "legacy-sidecar-merge",
                "reason": "prediction-first merge is behind explicit flag",
            },
        }
    return {
        "schemaVersion": RIME_SIDECAR_SCHEMA_VERSION,
        "sessionId": snapshot.session_id,
        "requestSeq": snapshot.request_seq,
        "project": snapshot.project or default_project,
        "rawInput": snapshot.raw_input,
        "preedit": snapshot.preedit,
        "commitTextPreview": snapshot.commit_text_preview,
        "committedContext": snapshot.committed_context,
        "semanticQuery": semantic_query,
        "queryBasis": query_basis,
        "triggerDecision": {
            "shouldRefresh": trigger_decision.should_refresh,
            "reason": trigger_decision.reason,
            "idleMs": snapshot.idle_ms,
            "semanticSignalLength": semantic_signal_length(semantic_query),
            "forceSideCandidates": snapshot.force_side_candidates,
        },
        "historyContext": prediction_context,
        "historyContextMeta": prediction_context_metadata(prediction_context),
        "latencyBudgetMs": snapshot.latency_budget_ms,
        "ragLane": rag_lane,
        "modelLane": model_lane,
        "rimeContext": rime_context_to_payload(snapshot),
        "modelPredictions": [model_prediction_to_payload(item) for item in model_predictions],
        "ragCandidates": [suggestion_to_payload(item) for item in suggestions],
        "displayCandidates": [display_item_to_payload(item) for item in display_candidates],
        "predictionFirst": prediction_first_payload,
        "selectionActions": {
            "rime": "select_rime_candidate",
            "side": "commit_side_candidate",
        },
        "mergePolicy": {
            "rimeFirst": False,
            "sideFirst": True,
            "maxVisibleCandidates": snapshot.max_visible_candidates,
            "maxSideCandidates": snapshot.max_side_candidates,
            "reservedSideSlots": min(snapshot.max_side_candidates, snapshot.max_visible_candidates),
            "maxRimeVisibleCandidates": max(0, snapshot.max_visible_candidates - min(snapshot.max_side_candidates, snapshot.max_visible_candidates)),
            "maxModelSideCandidates": max_model_side_candidates(snapshot.max_side_candidates),
            "ragBlockReserve": rag_block_reserve(snapshot.max_side_candidates),
            "ragKeepsRemainingSideSlots": True,
            "rawPinyinFallback": query_basis == "rawInputFallback",
            "sideCandidatesEnabled": trigger_decision.should_refresh,
            "fallbackOrder": ["model", "rag", "rime"],
        },
    }


def suggest_rag_with_latency_budget(
    *,
    adapter: InputMethodAdapter,
    current_input: str,
    recent_context: str,
    project: str,
    app: str,
    top_k: int,
    latency_budget_ms: int,
) -> tuple[list[InputSuggestion], dict[str, object]]:
    budget_ms = max(0, int(latency_budget_ms))
    if budget_ms <= 0:
        return [], _rag_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="no latency budget remaining",
            budget_ms=budget_ms,
        )
    if top_k <= 0:
        return [], _rag_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="no side candidate slot",
            budget_ms=budget_ms,
        )
    if not _RAG_LANE_SEMAPHORE.acquire(blocking=False):
        return [], _rag_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="RAG lane already running",
            budget_ms=budget_ms,
        )

    done = Event()
    result: dict[str, object] = {"suggestions": []}

    def run_suggest() -> None:
        started = time.perf_counter()
        try:
            result["suggestions"] = adapter.suggest(
                SuggestionRequest(
                    current_input=current_input,
                    recent_context=recent_context,
                    project=project,
                    app=app,
                    top_k=top_k,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive fail-open guard
            result["error"] = exc.__class__.__name__
        finally:
            result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
            done.set()
            _RAG_LANE_SEMAPHORE.release()

    Thread(target=run_suggest, name="rag-ime-rag-lane", daemon=True).start()
    if not done.wait(timeout=budget_ms / 1000):
        return [], _rag_lane_status(
            called=True,
            timed_out=True,
            skipped_reason="RAG lane exceeded latency budget",
            budget_ms=budget_ms,
        )

    suggestions = result.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    error = _string(result.get("error"))
    return suggestions, _rag_lane_status(
        called=True,
        timed_out=False,
        skipped_reason=f"error: {error}" if error else "",
        budget_ms=budget_ms,
        elapsed_ms=_optional_int(result.get("elapsedMs")) or 0,
        suggestion_count=len(suggestions),
    )


def run_side_lanes_with_latency_budget(
    *,
    adapter: InputMethodAdapter,
    core: CoreClient,
    predictor: PredictionProvider,
    current_input: str,
    recent_context: str,
    explicit_recent_context: str,
    project: str,
    app: str,
    top_k: int,
    max_candidates: int,
    latency_budget_ms: int,
) -> tuple[list[InputSuggestion], dict[str, object], list[ModelPrediction], dict[str, object]]:
    rag_result: dict[str, object] = {}
    model_result: dict[str, object] = {}

    def run_rag() -> None:
        suggestions, lane = suggest_rag_with_latency_budget(
            adapter=adapter,
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=top_k,
            latency_budget_ms=latency_budget_ms,
        )
        rag_result["suggestions"] = suggestions
        rag_result["lane"] = lane

    def run_model() -> None:
        predictions, lane = predict_model_with_latency_budget(
            core=core,
            predictor=predictor,
            current_input=current_input,
            explicit_recent_context=explicit_recent_context,
            project=project,
            max_candidates=max_candidates,
            latency_budget_ms=latency_budget_ms,
        )
        model_result["predictions"] = predictions
        model_result["lane"] = lane

    threads = [
        Thread(target=run_rag, name="rag-ime-sidecar-rag-dispatch", daemon=True),
        Thread(target=run_model, name="rag-ime-sidecar-model-dispatch", daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(0, latency_budget_ms) / 1000)

    suggestions = rag_result.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    rag_lane = rag_result.get("lane")
    if not isinstance(rag_lane, dict):
        rag_lane = _rag_lane_status(
            called=True,
            timed_out=True,
            skipped_reason="RAG dispatch exceeded latency budget",
            budget_ms=max(0, int(latency_budget_ms)),
        )

    predictions = model_result.get("predictions")
    if not isinstance(predictions, list):
        predictions = []
    model_lane = model_result.get("lane")
    if not isinstance(model_lane, dict):
        predictions = _get_model_holdover_predictions(
            project=project,
            explicit_recent_context=explicit_recent_context,
            max_candidates=max_candidates,
        )
        if predictions:
            model_lane = _model_lane_status(
                called=True,
                timed_out=True,
                skipped_reason="model dispatch exceeded latency budget; reused recent model holdover",
                budget_ms=max(0, int(latency_budget_ms)),
                prediction_count=len(predictions),
                holdover_hit=True,
            )
        else:
            model_lane = _model_lane_status(
                called=True,
                timed_out=True,
                skipped_reason="model dispatch exceeded latency budget",
                budget_ms=max(0, int(latency_budget_ms)),
            )

    return suggestions, rag_lane, predictions, model_lane


def predict_model_with_latency_budget(
    *,
    core: CoreClient,
    predictor: PredictionProvider,
    current_input: str,
    explicit_recent_context: str,
    project: str,
    max_candidates: int,
    latency_budget_ms: int,
) -> tuple[list[ModelPrediction], dict[str, object]]:
    budget_ms = max(0, int(latency_budget_ms))
    if budget_ms <= 0:
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="no latency budget remaining",
            budget_ms=budget_ms,
        )
    if max_candidates <= 0:
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="no side candidate slot",
            budget_ms=budget_ms,
        )
    if not _MODEL_LANE_SEMAPHORE.acquire(blocking=False):
        cached_predictions = _get_model_holdover_predictions(
            project=project,
            explicit_recent_context=explicit_recent_context,
            max_candidates=max_candidates,
        )
        if cached_predictions:
            return cached_predictions, _model_lane_status(
                called=False,
                timed_out=False,
                skipped_reason="model lane already running; reused recent model holdover",
                budget_ms=budget_ms,
                prediction_count=len(cached_predictions),
                holdover_hit=True,
            )
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="model lane already running",
            budget_ms=budget_ms,
        )

    done = Event()
    result: dict[str, object] = {"predictions": []}

    def run_prediction() -> None:
        started = time.perf_counter()
        try:
            context_event_limit, context_char_limit = model_prediction_context_limits()
            recent_context = build_prediction_context(
                core,
                explicit_recent_context=explicit_recent_context,
                project=project,
                limit=context_event_limit,
                max_chars=context_char_limit,
            )
            result["historyContext"] = recent_context
            if int((time.perf_counter() - started) * 1000) >= budget_ms:
                result["skippedReason"] = "history context exceeded latency budget"
                return
            predictions = predictor.predict(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
            )
            result["predictions"] = predictions
            if not predictions:
                predictor_error = _predictor_last_error(predictor)
                if predictor_error:
                    result["error"] = predictor_error
            if isinstance(result["predictions"], list) and result["predictions"]:
                _store_model_holdover_predictions(
                    project=project,
                    explicit_recent_context=explicit_recent_context,
                    predictions=result["predictions"],
                )
        except Exception as exc:  # pragma: no cover - defensive fail-open guard
            result["error"] = exc.__class__.__name__
        finally:
            result["elapsedMs"] = int((time.perf_counter() - started) * 1000)
            done.set()
            _MODEL_LANE_SEMAPHORE.release()

    Thread(target=run_prediction, name="rag-ime-model-lane", daemon=True).start()
    if not done.wait(timeout=budget_ms / 1000):
        cached_predictions = _get_model_holdover_predictions(
            project=project,
            explicit_recent_context=explicit_recent_context,
            max_candidates=max_candidates,
        )
        if cached_predictions:
            return cached_predictions, _model_lane_status(
                called=True,
                timed_out=True,
                skipped_reason="model lane exceeded latency budget; reused recent model holdover",
                budget_ms=budget_ms,
                prediction_count=len(cached_predictions),
                holdover_hit=True,
            )
        return [], _model_lane_status(
            called=True,
            timed_out=True,
            skipped_reason="model lane exceeded latency budget",
            budget_ms=budget_ms,
        )

    predictions = result.get("predictions")
    if not isinstance(predictions, list):
        predictions = []
    error = _string(result.get("error"))
    skipped_reason = _string(result.get("skippedReason"))
    return predictions, _model_lane_status(
        called=True,
        timed_out=False,
        skipped_reason=f"error: {error}" if error else skipped_reason,
        budget_ms=budget_ms,
        elapsed_ms=_optional_int(result.get("elapsedMs")) or 0,
        prediction_count=len(predictions),
        history_context=_string(result.get("historyContext")),
    )


def _rag_lane_status(
    *,
    called: bool,
    timed_out: bool,
    skipped_reason: str,
    budget_ms: int,
    elapsed_ms: int = 0,
    suggestion_count: int = 0,
) -> dict[str, object]:
    return {
        "called": called,
        "timedOut": timed_out,
        "skippedReason": skipped_reason,
        "suggestionCount": suggestion_count,
        "latencyBudgetMs": budget_ms,
        "elapsedMs": elapsed_ms,
    }


def _model_lane_status(
    *,
    called: bool,
    timed_out: bool,
    skipped_reason: str,
    budget_ms: int,
    elapsed_ms: int = 0,
    prediction_count: int = 0,
    history_context: str = "",
    holdover_hit: bool = False,
) -> dict[str, object]:
    return {
        "called": called,
        "timedOut": timed_out,
        "skippedReason": skipped_reason,
        "predictionCount": prediction_count,
        "latencyBudgetMs": budget_ms,
        "elapsedMs": elapsed_ms,
        "historyContext": history_context,
        "holdoverHit": holdover_hit,
    }


def clear_model_prediction_holdover_cache() -> None:
    with _MODEL_HOLDOVER_LOCK:
        _MODEL_HOLDOVERS.clear()


def wait_for_model_prediction_lane_idle(timeout_s: float = 1.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() <= deadline:
        if _MODEL_LANE_SEMAPHORE.acquire(blocking=False):
            _MODEL_LANE_SEMAPHORE.release()
            return True
        time.sleep(0.005)
    return False


def _store_model_holdover_predictions(
    *,
    project: str,
    explicit_recent_context: str,
    predictions: list[ModelPrediction],
) -> None:
    fingerprint = _holdover_context_fingerprint(explicit_recent_context)
    if not fingerprint:
        return
    visible = tuple(predictions[:10])
    if not visible:
        return
    with _MODEL_HOLDOVER_LOCK:
        _MODEL_HOLDOVERS[(project, fingerprint)] = _ModelPredictionHoldover(
            project=project,
            explicit_context_fingerprint=fingerprint,
            predictions=visible,
            created_at=time.monotonic(),
        )


def _get_model_holdover_predictions(
    *,
    project: str,
    explicit_recent_context: str,
    max_candidates: int,
) -> list[ModelPrediction]:
    fingerprint = _holdover_context_fingerprint(explicit_recent_context)
    if not fingerprint:
        return []
    with _MODEL_HOLDOVER_LOCK:
        cached = _MODEL_HOLDOVERS.get((project, fingerprint))
        if cached is None:
            return []
        if time.monotonic() - cached.created_at > _MODEL_HOLDOVER_TTL_MS / 1000:
            _MODEL_HOLDOVERS.pop((project, fingerprint), None)
            return []
        return list(cached.predictions[: max(1, min(10, int(max_candidates)))])


def _holdover_context_fingerprint(text: str) -> str:
    return compact_whitespace(text)[-420:]


def _predictor_last_error(predictor: PredictionProvider) -> str:
    direct_error = _string(getattr(predictor, "last_error", ""))
    if direct_error:
        return direct_error
    cooldown_status = getattr(predictor, "cooldown_status", None)
    if callable(cooldown_status):
        try:
            status = cooldown_status()
        except Exception:  # pragma: no cover - defensive debug-only guard
            return ""
        if isinstance(status, dict):
            return _string(status.get("lastError"))
    return ""


def record_rime_side_candidate_selection(
    *,
    payload: dict[str, Any],
    adapter: InputMethodAdapter,
    core: CoreClient,
    default_project: str = "wisdom-weasel-rag-ime",
) -> dict[str, object]:
    candidate = _candidate_payload(payload)
    insert_text = (
        _string(candidate.get("insertText"))
        or _string(candidate.get("insert_text"))
        or _string(candidate.get("text"))
        or _string(payload.get("insertText"))
    ).strip()
    if not insert_text:
        raise ValueError("candidate insertText/text must not be empty")

    dry_run = _bool(
        payload.get("dryRun", payload.get("dry_run", payload.get("recordingDisabled"))),
        default=False,
    )
    source_type = _string(candidate.get("sourceType") or candidate.get("source_type")) or "side"
    project = _string(payload.get("project")) or default_project
    query = _string(payload.get("query") or payload.get("semanticQuery"))
    recent_context = _string(payload.get("recentContext") or payload.get("committedContext"))
    preedit = _string(payload.get("preedit"))
    label = _string(candidate.get("selectionKey") or candidate.get("label"))
    candidate_rank = _optional_int(candidate.get("selectionRank")) or _candidate_rank(label)
    tags = tuple(
        item
        for item in (
            "squirrel",
            "rime-sidecar",
            f"source:{source_type}" if source_type else "",
        )
        if item
    )
    event_id = ""
    if not dry_run:
        event_id = adapter.commit_text(
            insert_text,
            recent_context=recent_context,
            preedit=preedit,
            schema_id="rime_sidecar",
            app=_string(payload.get("app")) or "squirrel",
            project=project,
            source=_string(payload.get("source")) or "squirrel_rime_sidecar",
            candidate_rank=candidate_rank,
            provider_name=_string(payload.get("providerName")) or f"rime-sidecar:{source_type}",
            tags=tags,
        )

    action_payload: dict[str, object] | None = None
    memory_id = _string(candidate.get("memoryId") or candidate.get("memory_id"))
    suggestion_id = _string(candidate.get("suggestionId") or candidate.get("suggestion_id"))
    source_event_id = _optional_int(candidate.get("sourceEventId") or candidate.get("source_event_id"))
    if not dry_run and source_type == "rag" and memory_id and suggestion_id and source_event_id is not None:
        action = core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=now_ms(),
                memory_id=memory_id,
                action_type="accepted",
                query=query,
                suggestion_id=suggestion_id,
                source_event_id=source_event_id,
                metadata={
                    "surface_text": _string(candidate.get("text")) or insert_text,
                    "insert_text": insert_text,
                    "source": "rime-sidecar-select",
                },
            )
        )
        action_payload = action_response_payload(action)

    return {
        "schemaVersion": "rag-ime.rime-selection.v1",
        "ok": True,
        "dryRun": dry_run,
        "eventId": event_id,
        "project": project,
        "sourceType": source_type,
        "insertText": insert_text,
        "recordedAction": action_payload is not None,
        "action": action_payload,
    }


def parse_rime_context_payload(payload: dict[str, Any], *, default_project: str) -> RimeContextSnapshot:
    rime_context = payload.get("rimeContext") if isinstance(payload.get("rimeContext"), dict) else {}
    assert isinstance(rime_context, dict)
    candidates_source = rime_context.get("candidates", payload.get("rimeCandidates"))
    candidates = tuple(_parse_rime_candidates(candidates_source))
    select_keys = _string(rime_context.get("selectKeys") or payload.get("selectKeys"))
    if select_keys:
        candidates = tuple(
            RimeCandidate(
                text=item.text,
                label=item.label or (select_keys[index] if index < len(select_keys) else ""),
                comment=item.comment,
                index=item.index,
            )
            for index, item in enumerate(candidates)
        )
    return RimeContextSnapshot(
        session_id=_string(payload.get("sessionId")) or "default",
        request_seq=_bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1),
        raw_input=_string(payload.get("rawInput") or payload.get("currentInput")),
        preedit=_string(payload.get("preedit")),
        commit_text_preview=_string(payload.get("commitTextPreview") or rime_context.get("commitTextPreview")),
        committed_context=_string(payload.get("committedContext") or payload.get("recentContext")),
        project=_string(payload.get("project")) or default_project,
        app=_string(payload.get("app") or payload.get("frontmostApp") or rime_context.get("app") or rime_context.get("frontmostApp")),
        candidates=candidates,
        highlighted_index=_bounded_int(
            rime_context.get("highlightedIndex", payload.get("highlightedIndex")),
            default=0,
            minimum=0,
            maximum=999,
        ),
        page=_bounded_int(rime_context.get("page", payload.get("page")), default=0, minimum=0, maximum=999),
        is_last_page=_bool(rime_context.get("isLastPage", payload.get("isLastPage")), default=True),
        latency_budget_ms=_bounded_int(payload.get("latencyBudgetMs"), default=300, minimum=30, maximum=2000),
        max_visible_candidates=_bounded_int(payload.get("maxVisibleCandidates"), default=8, minimum=1, maximum=10),
        max_side_candidates=_bounded_int(payload.get("maxSideCandidates"), default=8, minimum=0, maximum=10),
        idle_ms=_bounded_int(_first_present(payload, rime_context, "idleMs"), default=0, minimum=0, maximum=10000),
        force_side_candidates=_bool(
            _first_present(payload, rime_context, "forceSideCandidates"),
            default=False,
        ),
    )


def choose_semantic_query(snapshot: RimeContextSnapshot) -> tuple[str, str]:
    commit_preview = compact_whitespace(snapshot.commit_text_preview)
    if commit_preview:
        return commit_preview, "commitTextPreview"
    raw_semantic_input = semantic_ascii_input_text(snapshot)
    if raw_semantic_input:
        return raw_semantic_input, "rawSemanticInput"
    candidate_text = compact_whitespace(" ".join(item.text for item in snapshot.candidates[:3] if item.text))
    if candidate_text:
        return candidate_text, "rimeCandidates"
    preedit = compact_whitespace(snapshot.preedit)
    raw_input = compact_whitespace(snapshot.raw_input)
    if preedit and preedit != raw_input:
        return preedit, "preedit"
    context = compact_whitespace(snapshot.committed_context)
    if context:
        return context[-240:], "committedContext"
    return raw_input, "rawInputFallback"


def decide_side_candidate_refresh(
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
) -> RimeSideCandidateTriggerDecision:
    """Decide whether this Rime refresh should call model/RAG side lanes.

    Squirrel can refresh the candidate panel on nearly every composing event.
    Rime candidates should always render, but local model and RAG work should
    wait until there is a stable semantic signal instead of raw pinyin noise.
    """

    if snapshot.max_side_candidates <= 0:
        return RimeSideCandidateTriggerDecision(False, "skip: side candidates disabled")

    if snapshot.force_side_candidates:
        return RimeSideCandidateTriggerDecision(True, "force: explicit side candidate refresh")

    signal_len = semantic_signal_length(semantic_query)
    if signal_len <= 0:
        return RimeSideCandidateTriggerDecision(False, "skip: empty semantic signal")

    if query_basis == "rawInputFallback":
        return RimeSideCandidateTriggerDecision(False, "skip: raw pinyin fallback")

    if query_basis == "rawSemanticInput":
        return RimeSideCandidateTriggerDecision(True, "refresh: semantic raw input")

    composing_without_rime_candidate = bool(compact_whitespace(snapshot.raw_input)) and not snapshot.candidates
    if composing_without_rime_candidate and query_basis == "committedContext":
        if signal_len >= 4:
            return RimeSideCandidateTriggerDecision(True, "refresh: recent committed context fallback")
        return RimeSideCandidateTriggerDecision(False, "skip: composing without stable Rime candidate")

    if query_basis == "commitTextPreview" and signal_len >= 2:
        return RimeSideCandidateTriggerDecision(True, "refresh: commit preview")

    if query_basis == "rimeCandidates":
        if signal_len >= 3:
            return RimeSideCandidateTriggerDecision(True, "refresh: stable Rime candidates")
        if snapshot.idle_ms >= 300 and signal_len >= 2:
            return RimeSideCandidateTriggerDecision(True, "refresh: idle short Rime candidate")
        return RimeSideCandidateTriggerDecision(False, "skip: Rime candidate signal too short")

    if query_basis == "preedit":
        if snapshot.idle_ms >= 300 and signal_len >= 4:
            return RimeSideCandidateTriggerDecision(True, "refresh: idle semantic preedit")
        return RimeSideCandidateTriggerDecision(False, "skip: preedit not stable enough")

    if query_basis == "committedContext":
        if snapshot.idle_ms >= 300 and signal_len >= 4:
            return RimeSideCandidateTriggerDecision(True, "refresh: idle committed context")
        return RimeSideCandidateTriggerDecision(False, "skip: waiting for active composition signal")

    return RimeSideCandidateTriggerDecision(False, "skip: unsupported query basis")


def semantic_signal_length(text: str) -> int:
    return sum(1 for char in compact_whitespace(text) if not char.isspace())


def merge_display_candidates(
    *,
    snapshot: RimeContextSnapshot,
    model_predictions: list[ModelPrediction],
    suggestions: list[InputSuggestion],
) -> list[SideCandidateDisplayItem]:
    max_visible = snapshot.max_visible_candidates
    display: list[SideCandidateDisplayItem] = []
    display_texts: set[str] = set()
    raw_english = raw_english_candidate_text(snapshot)
    if raw_english:
        display_texts.add(_display_text_norm(raw_english))
        display.append(
            SideCandidateDisplayItem(
                label=_display_label("", len(display)),
                text=raw_english,
                insert_text=raw_english,
                source_type="raw_english",
                selection_action="commit_side_candidate",
                source_index=0,
                comment="english",
                display_layout="inline",
                display_lane="input",
                metadata={"candidate_mode": "raw-english"},
            )
        )
    side_budget = min(snapshot.max_side_candidates, max_visible)
    rag_reserve = min(rag_block_reserve(side_budget), len(suggestions)) if model_predictions else 0
    side_limit = min(
        max(0, max_model_side_candidates(side_budget) - rag_reserve),
        max(0, max_visible - len(display)),
        len(model_predictions),
    )
    model_count = 0
    for prediction in model_predictions:
        if model_count >= side_limit or len(display) >= max_visible:
            break
        normalized_text = _display_text_norm(prediction.text)
        if normalized_text in display_texts:
            continue
        display_texts.add(normalized_text)
        display.append(
            SideCandidateDisplayItem(
                label=_display_label("", len(display)),
                text=prediction.text,
                insert_text=prediction.text,
                source_type="model",
                selection_action="commit_side_candidate",
                source_index=prediction.rank - 1,
                comment=prediction.provider_name,
                display_layout="inline",
                display_lane="model",
                metadata={
                    "providerName": prediction.provider_name,
                    "latencyMs": prediction.latency_ms,
                    "confidence": prediction.confidence,
                    **dict(prediction.metadata),
                },
            )
        )
        model_count += 1
    remaining_side_budget = max(0, side_budget - side_limit)
    rag_count = 0
    remaining = min(remaining_side_budget, max(0, max_visible - len(display)))
    for suggestion in suggestions:
        if rag_count >= remaining or len(display) >= max_visible:
            break
        normalized_text = _display_text_norm(suggestion.surface_text)
        if normalized_text in display_texts:
            continue
        display_texts.add(normalized_text)
        metadata = dict(suggestion.metadata)
        display.append(
            SideCandidateDisplayItem(
                label=_display_label("", len(display)),
                text=suggestion.surface_text,
                insert_text=str(metadata.get("insert_text") or suggestion.surface_text),
                source_type="rag",
                selection_action="commit_side_candidate",
                source_index=rag_count,
                comment=suggestion.suggestion_type,
                evidence_preview=suggestion.evidence_preview,
                suggestion_id=suggestion.suggestion_id,
                memory_id=str(metadata.get("memory_id") or suggestion.suggestion_id),
                source_event_id=suggestion.source_event_id,
                display_layout="block",
                display_lane="memory",
                metadata=metadata,
            )
        )
        rag_count += 1
    rime_remaining = max(0, max_visible - len(display))
    for candidate in snapshot.candidates:
        if len(display) >= max_visible:
            break
        normalized_text = _display_text_norm(candidate.text)
        if normalized_text in display_texts:
            continue
        display_texts.add(normalized_text)
        display.append(
            SideCandidateDisplayItem(
                label=_display_label(candidate.label if not display else "", len(display)),
                text=candidate.text,
                insert_text=candidate.text,
                source_type="rime",
                selection_action="select_rime_candidate",
                source_index=candidate.index,
                comment=candidate.comment,
                rime_index=candidate.index,
                display_layout="fallback",
                display_lane="rime",
            )
        )
    return display


def _display_text_norm(text: str) -> str:
    return compact_whitespace(text).lower()


def raw_english_candidate_text(snapshot: RimeContextSnapshot) -> str:
    raw = compact_whitespace(snapshot.raw_input)
    if not raw:
        raw = compact_whitespace(snapshot.preedit)
    return raw if looks_like_raw_commit_ascii_input(raw) else ""


def semantic_ascii_input_text(snapshot: RimeContextSnapshot) -> str:
    raw = compact_whitespace(snapshot.raw_input)
    if not raw:
        raw = compact_whitespace(snapshot.preedit)
    return raw if looks_like_semantic_ascii_input(raw) else ""


def looks_like_semantic_ascii_input(raw: str) -> bool:
    if not _is_ascii_text_input(raw):
        return False
    if raw.lower() in _SEMANTIC_ASCII_TERMS:
        return True
    return looks_like_raw_commit_ascii_input(raw)


def looks_like_raw_commit_ascii_input(raw: str) -> bool:
    if not _is_ascii_text_input(raw):
        return False
    parts = raw.split()
    if parts and parts[0].lower() in _SHELL_COMMAND_PREFIXES:
        return True
    if raw.lower() in _RAW_COMMIT_ASCII_TERMS:
        return True
    code_delimiters = set("_./:-+=<>[]{}()$@#\\|")
    has_code_delimiter = any(char in code_delimiters for char in raw)
    has_upper = any(char.isupper() for char in raw)
    has_lower = any(char.islower() for char in raw)
    has_digit = any(char.isdigit() for char in raw)
    has_space = any(char.isspace() for char in raw)
    return (
        has_code_delimiter
        or (has_space and len(parts) >= 2)
        or (has_upper and has_lower)
        or (has_upper and len(raw) >= 2)
        or (has_digit and len(raw) >= 2)
    )


def _is_ascii_text_input(raw: str) -> bool:
    if not raw or len(raw) > 80:
        return False
    if raw != compact_whitespace(raw):
        return False
    if not all(32 <= ord(char) <= 126 for char in raw):
        return False
    if not any(char.isalpha() for char in raw):
        return False
    return True


def max_model_side_candidates(side_budget: int) -> int:
    if side_budget <= 0:
        return 0
    return side_budget


def rag_block_reserve(side_budget: int) -> int:
    if side_budget <= 1:
        return 0
    if side_budget <= 3:
        return side_budget - 1
    return min(3, max(0, side_budget // 2))


def rime_context_to_payload(snapshot: RimeContextSnapshot) -> dict[str, object]:
    return {
        "candidates": [
            {
                "index": item.index,
                "label": item.label or _display_label("", index),
                "text": item.text,
                "comment": item.comment,
            }
            for index, item in enumerate(snapshot.candidates)
        ],
        "highlightedIndex": snapshot.highlighted_index,
        "page": snapshot.page,
        "isLastPage": snapshot.is_last_page,
        "app": snapshot.app,
    }


def display_item_to_payload(item: SideCandidateDisplayItem) -> dict[str, object]:
    selection_key = item.label
    return {
        "label": item.label,
        "selectionKey": selection_key,
        "selectionRank": _candidate_rank(selection_key),
        "text": item.text,
        "insertText": item.insert_text,
        "sourceType": item.source_type,
        "selectionAction": item.selection_action,
        "sourceIndex": item.source_index,
        "comment": item.comment,
        "evidencePreview": item.evidence_preview,
        "suggestionId": item.suggestion_id,
        "memoryId": item.memory_id,
        "sourceEventId": item.source_event_id,
        "rimeIndex": item.rime_index,
        "displayLayout": item.display_layout,
        "displayLane": item.display_lane or item.source_type,
        "metadata": dict(item.metadata),
    }


def _parse_rime_candidates(value: object) -> list[RimeCandidate]:
    if not isinstance(value, list):
        return []
    candidates: list[RimeCandidate] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            text = item
            label = ""
            comment = ""
            rime_index = index
        elif isinstance(item, dict):
            text = _string(item.get("text") or item.get("candidate"))
            label = _string(item.get("label"))
            comment = _string(item.get("comment"))
            rime_index = _bounded_int(item.get("index"), default=index, minimum=0, maximum=999)
        else:
            continue
        text = compact_whitespace(text)
        if text:
            candidates.append(RimeCandidate(text=text, label=label, comment=comment, index=rime_index))
    return candidates


def _display_label(label: str, zero_based_index: int) -> str:
    if label:
        return label
    number = (zero_based_index + 1) % 10
    return "0" if number == 0 else str(number)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return default
    return max(minimum, min(maximum, parsed))


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return default


def _first_present(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> object:
    if key in primary:
        return primary.get(key)
    return fallback.get(key)


def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate") or payload.get("displayCandidate")
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a JSON object")
    return candidate


def _candidate_rank(label: str) -> int | None:
    if not label:
        return None
    if label == "0":
        return 10
    if label.isdigit():
        return int(label)
    return None
