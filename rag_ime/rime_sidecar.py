from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, replace
from threading import BoundedSemaphore, Event, RLock, Thread
from typing import Any, Mapping

from .adapter import InputMethodAdapter, SuggestionRequest
from .core_client import CoreClient
from .embeddings import NullEmbeddingProvider
from .history_context import build_prediction_context, model_prediction_context_limits, prediction_context_metadata
from .local_sqlite_core import LocalSqliteCoreClient
from .models import (
    InputSuggestion,
    MemoryAction,
    ModelPrediction,
    RimeCandidate,
    RimeContextSnapshot,
    SideCandidateDisplayItem,
)
from .payloads import action_response_payload, model_prediction_to_payload, suggestion_to_payload
from .pinyin_index import build_pinyin_metadata, text_initials
from .prediction_first import (
    infer_input_mode,
    prediction_session_to_payload,
)
from .prediction_manager import PredictionManager
from .predictor import (
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
    PREDICTION_REQUEST_RIME_REORDER,
    PredictionProvider,
    predict_with_optional_request_context,
)
from .text_utils import compact_whitespace, now_ms, token_terms


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
_REALTIME_MODEL_CONTEXT_BUDGET_MS = 500
_MODEL_HOLDOVER_TTL_MS = 5000
_PROGRESSIVE_FIRST_RESPONSE_MS = 700
_PROGRESSIVE_FOLLOW_UP_RETRY_MS = 280
_POST_COMMIT_PANEL_TTL_MS = 8000
_PREFIX_CONSTRAINED_PANEL_TTL_MS = 2600
_MODEL_HOLDOVER_LOCK = RLock()
_MODEL_HOLDOVERS: dict[tuple[str, str], "_ModelPredictionHoldover"] = {}
_PREDICTION_MANAGER_LOCK = RLock()
_PREDICTION_MANAGERS: dict[tuple[str, str, str], PredictionManager] = {}
_RECENT_MEMORY_KEYWORDS = (
    "输入法",
    "RAG",
    "rag",
    "LLM",
    "llm",
    "记忆",
    "模型",
    "候选",
    "预测",
    "调试",
    "流程",
    "Codex",
    "Agent",
    "agent",
)
_RECENT_MEMORY_LOW_VALUE = {
    "根据",
    "基于",
    "测试",
    "分析",
    "验证",
    "假设",
    "或者",
    "现在",
    "目前",
    "下一步",
    "接下来",
}
_LOW_INFORMATION_CJK_TOKENS = {
    "的",
    "得",
    "地",
    "了",
    "是",
    "和",
    "与",
    "及",
    "或",
    "在",
    "就",
    "都",
    "而",
    "把",
    "被",
    "个",
    "这",
    "那",
    "吗",
    "呢",
    "啊",
    "呀",
    "吧",
    "嗯",
    "呃",
    "额",
    "哦",
}
_PROMPT_EXAMPLE_LEAK_SURFACES = {
    "把流程跑通",
    "接入本地",
    "接入本地记忆",
    "验证 LLM 候选",
    "验证LLM候选",
    "预测流程完成",
    "部署 RAG 组件",
    "部署RAG组件",
    "模型相关表达",
    "调试流程",
}
_RECENT_MEMORY_TRAILING_NOISE = _RECENT_MEMORY_LOW_VALUE | {
    "啊",
    "阿",
    "呃",
    "嗯",
    "额",
    "哦",
    "噢",
    "唔",
    "下一步",
    "接下来",
    "法",
    "撒旦",
    "深度",
}
_POST_COMMIT_GENERIC_QUERY_TERMS = {
    "一下",
    "一个",
    "一些",
    "以及",
    "包括",
    "今天",
    "他们",
    "你们",
    "使用",
    "候选词",
    "刚刚",
    "可以",
    "已经",
    "我们",
    "文档",
    "项目",
    "正在",
    "输入",
    "输入法",
    "这个",
    "那个",
    "继续",
    "现在",
    "目前",
    "用户",
    "需要",
    "问题",
}


@dataclass(frozen=True)
class RimeSideCandidateTriggerDecision:
    should_refresh: bool
    reason: str


@dataclass(frozen=True)
class _ModelPredictionHoldover:
    project: str
    input_state_fingerprint: str
    explicit_recent_context: str
    current_input: str
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
        suggestions, rag_lane, model_predictions, model_lane, progressive_state = run_side_lanes_with_latency_budget(
            adapter=adapter,
            core=core,
            predictor=predictor,
            snapshot=snapshot,
            current_input=semantic_query,
            recent_context=snapshot.committed_context,
            explicit_recent_context=snapshot.committed_context,
            project=snapshot.project or default_project,
            app=snapshot.app,
            top_k=snapshot.max_side_candidates,
            max_candidates=snapshot.max_side_candidates,
            latency_budget_ms=snapshot.latency_budget_ms,
        )
        raw_model_prediction_count = len(model_predictions)
        model_predictions = _filter_model_predictions_for_snapshot(
            model_predictions,
            snapshot=snapshot,
            query_basis=query_basis,
        )
        if raw_model_prediction_count != len(model_predictions):
            model_lane["filteredPredictionCount"] = raw_model_prediction_count - len(model_predictions)
        model_lane["predictionCount"] = len(model_predictions)
        prediction_context = _string(model_lane.get("historyContext"))
        raw_suggestion_count = len(suggestions)
        suggestions = _filter_rag_suggestions_for_query(
            suggestions,
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
            prediction_context=prediction_context,
        )
        post_commit_filtered_suggestions = len(suggestions)
        suggestions = _filter_post_commit_rag_suggestions_for_query(
            suggestions,
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
        )
        if post_commit_filtered_suggestions != len(suggestions):
            rag_lane["postCommitQualityFilteredCount"] = post_commit_filtered_suggestions - len(suggestions)
        rag_lane["suggestionCount"] = len(suggestions)
        if raw_suggestion_count != len(suggestions):
            rag_lane["filteredSuggestionCount"] = raw_suggestion_count - len(suggestions)
        if _should_suppress_post_commit_rag_only(snapshot, model_predictions, suggestions):
            rag_lane["postCommitRagOnlySuppressed"] = True
            rag_lane["suppressedSuggestionCount"] = len(suggestions)
            rag_lane["suggestionCount"] = 0
            suggestions = []
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
        progressive_state = _progressive_state(
            enabled=progressive_sidecar_updates_enabled(),
            partial=False,
            should_follow_up=False,
        )
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
    prediction_first_enabled = prediction_first_merge_enabled(payload)
    if prediction_first_enabled:
        prediction_manager = _prediction_manager_for_snapshot(snapshot, default_project=default_project)
        raw_commit_text = raw_english_candidate_text(snapshot)
        if _should_clear_prediction_pool(
            snapshot=snapshot,
            trigger_decision=trigger_decision,
            raw_commit_text=raw_commit_text,
        ):
            prediction_manager.clear()
        source_update = trigger_decision.should_refresh or bool(model_predictions) or bool(suggestions)
        manager_result = prediction_manager.render(
            snapshot=snapshot,
            model_predictions=model_predictions if source_update else None,
            suggestions=suggestions if source_update else None,
            raw_commit_text=raw_commit_text,
            now_ms=now_ms(),
        )
        prediction_first_result = manager_result.merge_result
        display_candidates = list(prediction_first_result.display_candidates)
        prediction_session_payload = prediction_session_to_payload(manager_result.session)
        prediction_session_payload.update(
            {
                "sessionFingerprint": manager_result.session_fingerprint,
                "contextFingerprint": manager_result.context_fingerprint,
                "requestSeq": snapshot.request_seq,
                "expiresAfterMs": _prediction_session_expiry_ms(prediction_session_payload),
            }
        )
        prediction_first_payload: dict[str, object] = {
            "enabled": True,
            "mode": prediction_first_result.mode.value,
            "pinyinPrefix": prediction_first_result.pinyin_prefix,
            "policy": {
                **prediction_first_result.policy,
                "candidatePoolActive": manager_result.candidate_pool_active,
                "candidatePoolReused": manager_result.reused_candidate_pool,
                "candidatePoolStale": manager_result.candidate_pool_stale,
                "candidatePoolContextFingerprint": manager_result.context_fingerprint,
                "candidatePoolSessionFingerprint": manager_result.session_fingerprint,
            },
        }
    else:
        display_candidates = merge_display_candidates(
            snapshot=snapshot,
            model_predictions=model_predictions,
            suggestions=suggestions,
        )
        input_mode = infer_input_mode(snapshot)
        prediction_session_payload = {
            "phase": "legacy",
            "inputMode": input_mode.value,
            "pinyinPrefix": snapshot.preedit or snapshot.raw_input,
            "candidatePanelVisible": bool(display_candidates),
            "predictionPanelVisible": False,
            "shouldClearPredictionPanel": False,
            "clearReason": "",
            "selectionScope": "legacy",
            "rimeCompositionOwnedByRime": input_mode.value.endswith("composing"),
            "sessionFingerprint": _response_session_fingerprint(
                snapshot=snapshot,
                mode=input_mode.value,
                display_candidates=tuple(display_candidates),
            ),
            "contextFingerprint": _context_fingerprint(snapshot.committed_context),
            "requestSeq": snapshot.request_seq,
            "expiresAfterMs": 0,
        }
        prediction_first_payload = {
            "enabled": False,
            "mode": input_mode.value,
            "pinyinPrefix": snapshot.preedit or snapshot.raw_input,
            "policy": {
                "engine": "legacy-sidecar-merge",
                "reason": "prediction-first merge is behind explicit flag",
            },
        }
    display_candidates = _bind_display_candidates_to_session(
        display_candidates=display_candidates,
        snapshot=snapshot,
        prediction_session_payload=prediction_session_payload,
    )
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
        "predictionSession": prediction_session_payload,
        "selectionActions": {
            "rime": "select_rime_candidate",
            "side": "commit_side_candidate",
        },
        "progressive": progressive_state,
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
    core: CoreClient,
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
    retrieval_top_k = max(int(top_k), min(20, int(top_k) * 2 + 4))
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
            realtime_adapter = _realtime_rag_adapter(adapter=adapter, core=core, budget_ms=budget_ms)
            result["suggestions"] = realtime_adapter.suggest(
                SuggestionRequest(
                    current_input=current_input,
                    recent_context=recent_context,
                    project=project,
                    app=app,
                    top_k=retrieval_top_k,
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


def _realtime_rag_adapter(*, adapter: InputMethodAdapter, core: CoreClient, budget_ms: int) -> InputMethodAdapter:
    if budget_ms > _REALTIME_MODEL_CONTEXT_BUDGET_MS or not isinstance(core, LocalSqliteCoreClient):
        return adapter
    return InputMethodAdapter(
        LocalSqliteCoreClient(
            core.db_path,
            suggestion_cache_size=core.suggestion_cache_size,
            embedding_provider=NullEmbeddingProvider(),
            vector_candidate_limit=0,
            vector_weight=0.0,
        ),
        project=str(getattr(adapter, "project", "wisdom-weasel-rag-ime")),
    )


def run_side_lanes_with_latency_budget(
    *,
    adapter: InputMethodAdapter,
    core: CoreClient,
    predictor: PredictionProvider,
    snapshot: RimeContextSnapshot,
    current_input: str,
    recent_context: str,
    explicit_recent_context: str,
    project: str,
    app: str,
    top_k: int,
    max_candidates: int,
    latency_budget_ms: int,
) -> tuple[list[InputSuggestion], dict[str, object], list[ModelPrediction], dict[str, object], dict[str, object]]:
    started = time.perf_counter()
    rag_result: dict[str, object] = {}
    model_result: dict[str, object] = {}
    rag_budget_ms = _rag_lane_budget_for_request(latency_budget_ms)
    request_type = model_request_type_for_snapshot(snapshot)
    model_candidate_limit = realtime_model_candidate_limit(max_candidates)
    rime_candidate_count = len(
        [
            item
            for item in snapshot.candidates[:10]
            if compact_whitespace(item.text)
        ]
    )
    rag_current_input = current_input
    model_current_input = current_input
    if request_type == "pinyin_constrained_prediction":
        prefix = stable_short_pinyin_prefix(snapshot)
        if prefix:
            rag_current_input = prefix
            model_current_input = prefix

    def run_rag() -> None:
        suggestions, lane = suggest_rag_with_latency_budget(
            adapter=adapter,
            core=core,
            current_input=rag_current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=top_k,
            latency_budget_ms=rag_budget_ms,
        )
        lane["queryInput"] = rag_current_input
        rag_result["suggestions"] = suggestions
        rag_result["lane"] = lane

    def run_model() -> None:
        predictions, lane = predict_model_with_latency_budget(
            core=core,
            predictor=predictor,
            snapshot=snapshot,
            current_input=model_current_input,
            explicit_recent_context=explicit_recent_context,
            project=project,
            max_candidates=model_candidate_limit,
            latency_budget_ms=latency_budget_ms,
        )
        model_result["predictions"] = predictions
        model_result["lane"] = lane

    rag_thread = Thread(target=run_rag, name="rag-ime-sidecar-rag-dispatch", daemon=True)
    model_thread = Thread(target=run_model, name="rag-ime-sidecar-model-dispatch", daemon=True)
    threads = [rag_thread, model_thread]
    for thread in threads:
        thread.start()
    deadline = started + max(0, latency_budget_ms) / 1000
    progressive_enabled = progressive_sidecar_updates_enabled()
    allow_progressive_first_response = progressive_enabled and not snapshot.progressive_follow_up
    first_response_budget_ms = progressive_first_response_budget_ms(latency_budget_ms)
    progressive_deadline = started + first_response_budget_ms / 1000
    progressive_partial = False
    while True:
        now = time.perf_counter()
        if not rag_thread.is_alive() and not model_thread.is_alive():
            break
        if now >= deadline:
            break
        if (
            allow_progressive_first_response
            and now >= progressive_deadline
            and _has_progressive_visible_lane_result(
                rag_result=rag_result,
                model_result=model_result,
                snapshot=snapshot,
            )
        ):
            progressive_partial = True
            break
        time.sleep(min(0.01, max(0.001, deadline - now)))

    suggestions = rag_result.get("suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    rag_lane = rag_result.get("lane")
    rag_pending = rag_thread.is_alive()
    if not isinstance(rag_lane, dict):
        rag_lane = _rag_lane_status(
            called=True,
            timed_out=not (progressive_partial and rag_pending),
            skipped_reason="RAG lane pending after progressive first response"
            if progressive_partial and rag_pending
            else "RAG dispatch exceeded latency budget",
            budget_ms=rag_budget_ms,
        )
        if progressive_partial and rag_pending:
            rag_lane["pending"] = True
    if recent_context_candidate_fallback_enabled():
        recent_fallback = recent_context_memory_suggestions(
            recent_context=explicit_recent_context or recent_context,
            current_input=current_input,
            top_k=max(0, int(top_k) - len(suggestions)),
        )
        if recent_fallback:
            seen_surfaces = {compact_whitespace(item.surface_text) for item in suggestions}
            for item in recent_fallback:
                if compact_whitespace(item.surface_text) not in seen_surfaces:
                    suggestions.append(item)
                    seen_surfaces.add(compact_whitespace(item.surface_text))
            rag_lane["recentContextFallbackCount"] = len(recent_fallback)
            rag_lane["suggestionCount"] = len(suggestions)

    predictions = model_result.get("predictions")
    if not isinstance(predictions, list):
        predictions = []
    model_lane = model_result.get("lane")
    model_pending = model_thread.is_alive()
    if not isinstance(model_lane, dict):
        predictions = _get_model_holdover_predictions(
            project=project,
            current_input=current_input,
            explicit_recent_context=explicit_recent_context,
            max_candidates=model_candidate_limit,
            allow_nearby=False,
        )
        if predictions:
            model_lane = _model_lane_status(
                called=True,
                timed_out=not (progressive_partial and model_pending),
                skipped_reason="model lane pending after progressive first response; reused recent model holdover"
                if progressive_partial and model_pending
                else "model dispatch exceeded latency budget; reused recent model holdover",
                budget_ms=max(0, int(latency_budget_ms)),
                prediction_count=len(predictions),
                holdover_hit=True,
                request_type=request_type,
                rime_candidate_count=rime_candidate_count,
                requested_max_candidates=model_candidate_limit,
            )
        else:
            model_lane = _model_lane_status(
                called=True,
                timed_out=not (progressive_partial and model_pending),
                skipped_reason="model lane pending after progressive first response"
                if progressive_partial and model_pending
                else "model dispatch exceeded latency budget",
                budget_ms=max(0, int(latency_budget_ms)),
                request_type=request_type,
                rime_candidate_count=rime_candidate_count,
                requested_max_candidates=model_candidate_limit,
            )
        if progressive_partial and model_pending:
            model_lane["pending"] = True

    if isinstance(model_lane, dict):
        model_lane["requestedMaxCandidates"] = model_candidate_limit
    pending_lanes = _progressive_pending_lanes(rag_lane=rag_lane, model_lane=model_lane)
    should_follow_up = bool(pending_lanes) and not bool(model_lane.get("holdoverHit"))
    progressive_state = _progressive_state(
        enabled=progressive_enabled,
        partial=progressive_partial,
        should_follow_up=should_follow_up,
        pending_lanes=pending_lanes,
        first_response_budget_ms=first_response_budget_ms,
        retry_after_ms=progressive_follow_up_retry_ms(),
    )
    return suggestions, rag_lane, predictions, model_lane, progressive_state


def _rag_lane_budget_for_request(latency_budget_ms: int) -> int:
    budget = max(0, int(latency_budget_ms))
    return budget


def progressive_sidecar_updates_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_PROGRESSIVE_DISPLAY", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def progressive_first_response_budget_ms(latency_budget_ms: int, env: Mapping[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    configured = _bounded_int(
        source.get("RAG_IME_PROGRESSIVE_FIRST_RESPONSE_MS"),
        default=_PROGRESSIVE_FIRST_RESPONSE_MS,
        minimum=120,
        maximum=2000,
    )
    budget = max(0, int(latency_budget_ms))
    if budget <= 0:
        return configured
    if budget <= configured + 80:
        return budget
    return min(configured, max(120, budget - 80))


def progressive_follow_up_retry_ms(env: Mapping[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    return _bounded_int(
        source.get("RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS"),
        default=_PROGRESSIVE_FOLLOW_UP_RETRY_MS,
        minimum=80,
        maximum=1500,
    )


def _has_progressive_visible_lane_result(
    *,
    rag_result: Mapping[str, object],
    model_result: Mapping[str, object],
    snapshot: RimeContextSnapshot,
) -> bool:
    suggestions = rag_result.get("suggestions")
    if isinstance(suggestions, list) and suggestions:
        return True
    predictions = model_result.get("predictions")
    if isinstance(predictions, list) and predictions:
        return True
    return bool(snapshot.candidates)


def _progressive_pending_lanes(*, rag_lane: Mapping[str, object], model_lane: Mapping[str, object]) -> list[str]:
    pending: list[str] = []
    if bool(rag_lane.get("pending")):
        pending.append("rag")
    model_reason = _string(model_lane.get("skippedReason"))
    if bool(model_lane.get("pending")) or (
        not bool(model_lane.get("holdoverHit"))
        and model_reason
        and (
            "model lane already running" in model_reason
            or "model lane pending" in model_reason
            or "model lane exceeded latency budget" in model_reason
        )
    ):
        pending.append("model")
    return pending


def _progressive_state(
    *,
    enabled: bool,
    partial: bool,
    should_follow_up: bool,
    pending_lanes: list[str] | None = None,
    first_response_budget_ms: int = 0,
    retry_after_ms: int = 0,
) -> dict[str, object]:
    return {
        "enabled": bool(enabled),
        "partial": bool(partial),
        "shouldFollowUp": bool(should_follow_up),
        "pendingLanes": list(pending_lanes or []),
        "firstResponseBudgetMs": max(0, int(first_response_budget_ms)),
        "retryAfterMs": max(0, int(retry_after_ms)),
    }


def realtime_model_candidate_limit(max_candidates: int) -> int:
    configured = _bounded_int(
        os.environ.get("RAG_IME_MODEL_LANE_MAX_CANDIDATES"),
        default=5,
        minimum=1,
        maximum=10,
    )
    return min(max(0, int(max_candidates)), configured)


def recent_context_memory_suggestions(
    *,
    recent_context: str,
    current_input: str,
    top_k: int,
) -> list[InputSuggestion]:
    if top_k <= 0:
        return []
    context = compact_whitespace(recent_context)
    if len(context) < 12:
        return []
    if not any(keyword in context for keyword in _RECENT_MEMORY_KEYWORDS):
        return []
    current = compact_whitespace(current_input)
    candidates: list[str] = []
    for segment in re.split(r"[，。！？；;,.!?、\n\r]+", context):
        text = compact_whitespace(segment)
        if 4 <= len(text) <= 28:
            candidates.append(text)
        for keyword in _RECENT_MEMORY_KEYWORDS:
            pos = text.find(keyword)
            if pos < 0:
                continue
            start = max(0, pos - 6)
            end = min(len(text), pos + len(keyword) + 12)
            phrase = compact_whitespace(text[start:end])
            if 4 <= len(phrase) <= 24:
                candidates.append(phrase)
    result: list[InputSuggestion] = []
    seen: set[str] = set()
    for text in candidates:
        text = _normalize_recent_memory_surface(text)
        if not text or text in seen or text == current:
            continue
        if _looks_like_broken_recent_memory_surface(text):
            continue
        if text in _RECENT_MEMORY_LOW_VALUE:
            continue
        seen.add(text)
        index = len(result)
        result.append(
            InputSuggestion(
                suggestion_id=f"recent-context-memory:{index}:{_short_stable_id(context[-80:], text)}",
                surface_text=text,
                suggestion_type="memory",
                source_event_id=0,
                evidence_preview=context[-160:],
                confidence=0.72 - (index * 0.02),
                expanded_evidence=context,
                metadata={
                    "source_type": "memory",
                    "memory_id": f"recent-context:{index}",
                    "insert_text": text,
                    "fallback": "recent_context",
                    **build_pinyin_metadata(text),
                },
            )
        )
        if len(result) >= top_k:
            break
    return result


def recent_context_candidate_fallback_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Debug-only escape hatch for turning recent screen text into candidates.

    The production IME must not treat the just-typed context as a memory
    candidate. Recent context is still fed to model/RAG retrieval, but direct
    slicing makes the UI behave like a clipboard and crowds out real memories.
    """

    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_RECENT_CONTEXT_CANDIDATES", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _normalize_recent_memory_surface(text: str) -> str:
    text = compact_whitespace(text)
    text = re.sub(r"^[,，。！？；;、\s]+|[,，。！？；;、\s]+$", "", text)
    text = re.sub(r"^(的|和|与|及|或|把|再|先|然后)\s*(?=[A-Za-z0-9\u3400-\u9fff])", "", text)
    text = compact_whitespace(text)
    text = _collapse_repeated_recent_memory_surface(text)
    return text


def _looks_like_broken_recent_memory_surface(text: str) -> bool:
    if _is_low_value_recent_memory_surface(text):
        return True
    if re.match(r"^[A-Za-z]{1,2}\s+[A-Za-z0-9\u3400-\u9fff]", text):
        return True
    if re.search(r"[A-Za-z]-$", text):
        return True
    if re.search(r"(^|[\s，,。])[-_][A-Za-z0-9]", text):
        return True
    parts = [part for part in re.split(r"[\s,，、;；。.!?！？/]+", compact_whitespace(text)) if part]
    if len(parts) <= 4 and all(part in _RECENT_MEMORY_TRAILING_NOISE for part in parts):
        return True
    return False


def _collapse_repeated_recent_memory_surface(text: str) -> str:
    surface = compact_whitespace(text)
    parts = [part for part in surface.split(" ") if part]
    if len(parts) < 3:
        return surface
    for width in range(1, min(5, len(parts) // 2 + 1)):
        first = parts[:width]
        second = parts[width : width * 2]
        if first != second:
            continue
        tail = parts[width * 2 :]
        if not tail or all(part in _RECENT_MEMORY_TRAILING_NOISE or len(part) <= 1 for part in tail):
            candidate = compact_whitespace(" ".join(first))
            if candidate and not _is_low_value_recent_memory_surface(candidate):
                return candidate
    return surface


def _is_low_value_recent_memory_surface(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return True
    if surface in _RECENT_MEMORY_LOW_VALUE:
        return True
    parts = [part for part in re.split(r"[\s,，、;；。.!?！？/]+", surface) if part]
    if not parts:
        return True
    if len(parts) <= 4 and all(part in _RECENT_MEMORY_TRAILING_NOISE for part in parts):
        return True
    return False


def _filter_rag_suggestions_for_query(
    suggestions: list[InputSuggestion],
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
    prediction_context: str = "",
) -> list[InputSuggestion]:
    result: list[InputSuggestion] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        surface = compact_whitespace(suggestion.surface_text)
        if not surface:
            continue
        if _rag_suggestion_repeats_context(
            suggestion,
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
            prediction_context=prediction_context,
        ):
            continue
        if _looks_like_assistant_history_candidate(suggestion):
            continue
        if _looks_like_low_quality_memory_candidate(surface):
            continue
        if _looks_like_uncompiled_raw_history_candidate(suggestion):
            continue
        key = _display_text_norm(surface)
        if key in seen:
            continue
        seen.add(key)
        result.append(suggestion)
    return result


def _rag_suggestion_repeats_context(
    suggestion: InputSuggestion,
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
    prediction_context: str,
) -> bool:
    surface = compact_whitespace(suggestion.surface_text)
    if not surface:
        return True
    if _surface_repeats_current_context(
        surface,
        snapshot=snapshot,
        semantic_query=semantic_query,
        query_basis=query_basis,
    ):
        return True
    if _suggestion_has_durable_memory_signal(dict(suggestion.metadata)):
        return False
    return _surface_repeats_history_reference(surface, prediction_context)


def _surface_repeats_current_context(
    surface: str,
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
) -> bool:
    surface_norm = _repeat_norm(surface)
    if len(surface_norm) < 3:
        return False
    anchors = [
        compact_whitespace(snapshot.committed_context),
        compact_whitespace(snapshot.commit_text_preview),
    ]
    if query_basis in {"committedContext", "commitTextPreview"}:
        anchors.append(compact_whitespace(semantic_query))
    for anchor in anchors:
        anchor_norm = _repeat_norm(anchor)
        if len(anchor_norm) < 3:
            continue
        if surface_norm == anchor_norm:
            return True
        if surface_norm in anchor_norm:
            coverage = len(surface_norm) / max(1, len(anchor_norm))
            if coverage >= 0.9:
                return True
        if len(anchor_norm) >= 4 and anchor_norm in surface_norm:
            coverage = len(anchor_norm) / max(1, len(surface_norm))
            if coverage >= 0.75:
                return True
    return False


def _surface_repeats_history_reference(surface: str, prediction_context: str) -> bool:
    if "历史参考" not in prediction_context and "历史输入:" not in prediction_context:
        return False
    surface_norm = _repeat_norm(surface)
    context_norm = _repeat_norm(prediction_context)
    if len(surface_norm) < 4 or not context_norm:
        return False
    if surface_norm in context_norm:
        return True
    if len(surface_norm) >= 8 and _cjk_context_overlap_ratio(surface, prediction_context) >= 0.8:
        return True
    return False


def _suggestion_has_durable_memory_signal(metadata: Mapping[str, object]) -> bool:
    tags = {
        compact_whitespace(str(tag)).lower()
        for tag in metadata.get("tags", [])
        if compact_whitespace(str(tag))
    } if isinstance(metadata.get("tags"), list) else set()
    if tags.intersection({"generated-memory", "api-core-optimized", "api-lexicon", "lexicon-phrase", "phrase-memory", "curated", "structure"}):
        return True
    state = metadata.get("state") if isinstance(metadata.get("state"), dict) else {}
    assert isinstance(state, dict)
    if bool(state.get("pinned")):
        return True
    durable_count = max(
        _safe_int(state.get("accepted_count")),
        _safe_int(state.get("event_accepted_count")),
        _safe_int(state.get("effective_frequency")),
        _safe_int(state.get("project_input_frequency")),
        _safe_int(state.get("app_input_frequency")),
    )
    return durable_count >= 3


def _looks_like_uncompiled_raw_history_candidate(suggestion: InputSuggestion) -> bool:
    surface = compact_whitespace(suggestion.surface_text)
    if not surface:
        return True
    metadata = dict(suggestion.metadata)
    if _suggestion_has_curated_or_repeated_accept_signal(metadata):
        return False

    source_ref = compact_whitespace(str(metadata.get("source_ref") or metadata.get("memory_id") or "")).lower()
    suggestion_id = compact_whitespace(suggestion.suggestion_id).lower()
    raw_event_like = (
        suggestion.source_event_id is not None
        or source_ref.startswith(("input_event:", "event:", "committed:"))
        or suggestion_id.startswith(("sug-event:", "event:", "input_event:", "committed:"))
    )
    if not raw_event_like:
        return False

    cjk_count = len(re.findall(r"[\u3400-\u9fff]", surface))
    punctuation_count = len(re.findall(r"[，。！？；：,.!?;:]", surface))
    if punctuation_count > 0:
        return True
    if len(surface) > 42:
        return True
    if cjk_count >= 18 and punctuation_count > 0:
        return True
    if compact_whitespace(suggestion.suggestion_type).lower() in {"paragraph", "history", "input_event"} and cjk_count >= 14:
        return True
    return False


def _suggestion_has_curated_or_repeated_accept_signal(metadata: Mapping[str, object]) -> bool:
    tags = {
        compact_whitespace(str(tag)).lower()
        for tag in metadata.get("tags", [])
        if compact_whitespace(str(tag))
    } if isinstance(metadata.get("tags"), list) else set()
    if tags.intersection({"generated-memory", "api-core-optimized", "api-lexicon", "lexicon-phrase", "phrase-memory", "curated", "structure"}):
        return True
    state = metadata.get("state") if isinstance(metadata.get("state"), dict) else {}
    assert isinstance(state, dict)
    raw_signals = state.get("rawSignals") if isinstance(state.get("rawSignals"), dict) else {}
    assert isinstance(raw_signals, dict)
    if bool(state.get("pinned") or raw_signals.get("pinned")):
        return True
    accepted_count = max(
        _safe_int(state.get("accepted_count")),
        _safe_int(state.get("event_accepted_count")),
        _safe_int(state.get("acceptedCount")),
        _safe_int(raw_signals.get("acceptedCount")),
    )
    return accepted_count >= 3


def _cjk_context_overlap_ratio(surface: str, context: str) -> float:
    candidate_chars = re.findall(r"[\u3400-\u9fff]", surface)
    context_chars = set(re.findall(r"[\u3400-\u9fff]", context))
    if len(candidate_chars) < 4 or not context_chars:
        return 0.0
    covered = sum(1 for char in candidate_chars if char in context_chars)
    return covered / max(1, len(candidate_chars))


def _filter_post_commit_rag_suggestions_for_query(
    suggestions: list[InputSuggestion],
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    query_basis: str,
) -> list[InputSuggestion]:
    if not _is_post_commit_prediction_snapshot(snapshot):
        return suggestions
    result: list[InputSuggestion] = []
    for suggestion in suggestions:
        if _post_commit_rag_candidate_has_strong_signal(
            suggestion,
            semantic_query=semantic_query,
            query_basis=query_basis,
        ):
            result.append(suggestion)
    return result


def _filter_model_predictions_for_snapshot(
    predictions: list[ModelPrediction],
    *,
    snapshot: RimeContextSnapshot,
    query_basis: str,
) -> list[ModelPrediction]:
    if not predictions or not _is_post_commit_prediction_snapshot(snapshot):
        return predictions
    if query_basis not in {"committedContext", "commitTextPreview"}:
        return predictions
    result: list[ModelPrediction] = []
    for prediction in predictions:
        if _post_commit_model_prediction_echoes_context(prediction.text, snapshot.committed_context):
            continue
        result.append(prediction)
    return result


def _is_post_commit_prediction_snapshot(snapshot: RimeContextSnapshot) -> bool:
    if compact_whitespace(snapshot.raw_input) or compact_whitespace(snapshot.preedit):
        return False
    if snapshot.candidates:
        return False
    return bool(compact_whitespace(snapshot.committed_context) or compact_whitespace(snapshot.commit_text_preview))


def _post_commit_model_prediction_echoes_context(candidate: str, committed_context: str) -> bool:
    surface = compact_whitespace(candidate)
    context = compact_whitespace(committed_context)
    if not surface or not context:
        return False
    if len(surface) >= 3 and surface in context:
        return True
    candidate_chars = re.findall(r"[\u3400-\u9fff]", surface)
    context_chars = set(re.findall(r"[\u3400-\u9fff]", context))
    if len(candidate_chars) < 4 or not context_chars:
        return False
    covered = sum(1 for char in candidate_chars if char in context_chars)
    return covered / max(1, len(candidate_chars)) >= 0.65


def _post_commit_rag_candidate_has_strong_signal(
    suggestion: InputSuggestion,
    *,
    semantic_query: str,
    query_basis: str,
) -> bool:
    metadata = dict(suggestion.metadata)
    if _suggestion_has_positive_user_signal(metadata):
        return True

    query = compact_whitespace(semantic_query)
    surface = compact_whitespace(suggestion.surface_text)
    if not query or not surface:
        return False

    if query_basis == "commitTextPreview" and semantic_signal_length(query) < 4:
        return False

    hits = _important_surface_overlap_terms(query=query, surface=surface)
    if query_basis == "commitTextPreview" and hits:
        return True
    if len(hits) >= 2:
        return True
    if any(len(term) >= 4 for term in hits):
        return True
    if any(term in {"agent", "codex", "llm", "mlx", "rag", "rime", "squirrel"} for term in hits):
        return True
    return False


def _suggestion_has_positive_user_signal(metadata: Mapping[str, object]) -> bool:
    state = metadata.get("state") if isinstance(metadata.get("state"), dict) else {}
    assert isinstance(state, dict)
    raw_signals = state.get("rawSignals") if isinstance(state.get("rawSignals"), dict) else {}
    assert isinstance(raw_signals, dict)
    generated_side_candidate = _suggestion_is_generated_side_candidate(metadata)
    if bool(state.get("pinned") or raw_signals.get("pinned")):
        return True
    if generated_side_candidate:
        generated_accepts = max(
            _safe_int(state.get("accepted_count")),
            _safe_int(state.get("event_accepted_count")),
            _safe_int(state.get("acceptedCount")),
            _safe_int(raw_signals.get("acceptedCount")),
        )
        generated_frequency = max(
            _safe_int(state.get("input_frequency")),
            _safe_int(state.get("project_input_frequency")),
            _safe_int(state.get("app_input_frequency")),
            _safe_int(state.get("effective_frequency")),
            _safe_int(raw_signals.get("inputFrequency")),
            _safe_int(raw_signals.get("projectInputFrequency")),
            _safe_int(raw_signals.get("appInputFrequency")),
            _safe_int(raw_signals.get("effectiveFrequency")),
        )
        return generated_accepts >= 3 or generated_frequency >= 3
    for key in (
        "accepted_count",
        "event_accepted_count",
        "acceptedCount",
    ):
        if _safe_int(state.get(key) if key in state else raw_signals.get(key)) > 0:
            return True
    for key in (
        "input_frequency",
        "project_input_frequency",
        "effective_frequency",
        "inputFrequency",
        "projectInputFrequency",
        "effectiveFrequency",
    ):
        if _safe_int(state.get(key) if key in state else raw_signals.get(key)) >= 2:
            return True
    return False


def _suggestion_is_generated_side_candidate(metadata: Mapping[str, object]) -> bool:
    tags_raw = metadata.get("tags")
    tags = {compact_whitespace(str(tag)).lower() for tag in tags_raw if str(tag).strip()} if isinstance(tags_raw, list) else set()
    if tags.intersection({"source:model", "source:rag"}):
        return True
    source_ref = compact_whitespace(str(metadata.get("source_ref") or "")).lower()
    reason = compact_whitespace(str(metadata.get("reason") or "")).lower()
    provider = compact_whitespace(str(metadata.get("provider_name") or "")).lower()
    return "rime-sidecar:model" in reason or "rime-sidecar:model" in provider or "source:model" in source_ref


def _important_surface_overlap_terms(*, query: str, surface: str) -> list[str]:
    surface_lower = compact_whitespace(surface).lower()
    result: list[str] = []
    seen: set[str] = set()
    for term in token_terms(query, max_terms=48):
        normalized = compact_whitespace(term).lower()
        if len(normalized) < 2:
            continue
        if normalized in _POST_COMMIT_GENERIC_QUERY_TERMS:
            continue
        if normalized in seen:
            continue
        if normalized in surface_lower:
            seen.add(normalized)
            result.append(normalized)
    return result


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _looks_like_low_quality_memory_candidate(surface: str) -> bool:
    text = compact_whitespace(surface)
    if not text:
        return True
    if _looks_like_prompt_example_leak(text):
        return True
    if _looks_like_session_identifier_surface(text):
        return True
    if _looks_like_complaint_or_debug_fragment(text):
        return True
    if _looks_like_meta_candidate_surface(text):
        return True
    if _is_low_value_recent_memory_surface(text):
        return True
    if not _text_has_meaningful_ime_signal(text):
        return True
    return False


def _looks_like_prompt_example_leak(text: str) -> bool:
    return compact_whitespace(text) in _PROMPT_EXAMPLE_LEAK_SURFACES


def _looks_like_session_identifier_surface(text: str) -> bool:
    surface = compact_whitespace(text)
    if re.search(
        r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])",
        surface,
    ):
        return True
    if re.fullmatch(r"(?i)[0-9a-f]{16,}", surface):
        return True
    return False


def _looks_like_complaint_or_debug_fragment(text: str) -> bool:
    surface = compact_whitespace(text)
    lowered = surface.lower()
    if "…" in surface or "..." in surface:
        return True
    complaint_markers = (
        "不能用",
        "用不了",
        "没办法",
        "没法",
        "没区别",
        "没意义",
        "没记录",
        "没有记录",
        "不然这个",
        "感觉随机",
        "真实生效",
        "输入不了",
        "崩溃",
        "报错",
        "错误",
        "失败",
        "切成豆包",
    )
    if any(marker in surface for marker in complaint_markers):
        return True
    debug_markers = (
        "exception",
        "traceback",
        "brokenpipe",
        "timeout",
        "failure",
        "error",
    )
    if any(marker in lowered for marker in debug_markers):
        return True
    if surface.startswith(("现在的话", "然后可以再查", "不然")):
        return True
    return False


def _looks_like_meta_candidate_surface(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return True
    meta_prefixes = (
        "你正在输入",
        "你正在尝试",
        "你正在使用",
        "你正在看",
        "你正在查看",
        "你当前正在",
        "您正在输入",
        "您正在尝试",
        "您正在使用",
        "您正在看",
        "您正在查看",
        "您当前正在",
        "用户正在输入",
        "用户正在尝试",
        "用户正在使用",
        "用户正在看",
        "用户正在查看",
        "正在输入一个",
        "正在查看",
        "正在看",
    )
    if surface.startswith(meta_prefixes):
        return True
    meta_markers = (
        "已经上屏的文本",
        "上屏的文本",
        "作为输入法候选",
        "这是一个候选",
        "这个项目",
        "号项目",
    )
    return any(marker in surface for marker in meta_markers)


def _looks_like_assistant_history_candidate(suggestion: InputSuggestion) -> bool:
    metadata = dict(suggestion.metadata)
    material = "\n".join(
        compact_whitespace(str(value or ""))
        for value in (
            suggestion.evidence_preview,
            suggestion.expanded_evidence,
            metadata.get("preview_text"),
        )
    )
    return bool(re.search(r"(?m)^\[\d+\]\s*assistant:", material))


def _short_stable_id(*parts: str) -> str:
    material = "\x1f".join(parts)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:10]


def model_request_type_for_snapshot(snapshot: RimeContextSnapshot) -> str:
    active_prefix = compact_whitespace(snapshot.preedit or snapshot.raw_input)
    committed_context = compact_whitespace(snapshot.committed_context)
    if active_prefix and committed_context:
        if stable_short_pinyin_prefix(snapshot):
            return PREDICTION_REQUEST_PINYIN_CONSTRAINED
        return PREDICTION_REQUEST_NO_INPUT
    if active_prefix and snapshot.candidates:
        return PREDICTION_REQUEST_RIME_REORDER
    return PREDICTION_REQUEST_NO_INPUT


def predict_model_with_latency_budget(
    *,
    core: CoreClient,
    predictor: PredictionProvider,
    snapshot: RimeContextSnapshot,
    current_input: str,
    explicit_recent_context: str,
    project: str,
    max_candidates: int,
    latency_budget_ms: int,
) -> tuple[list[ModelPrediction], dict[str, object]]:
    budget_ms = max(0, int(latency_budget_ms))
    request_type = model_request_type_for_snapshot(snapshot)
    rime_candidate_texts = tuple(
        compact_whitespace(item.text)
        for item in snapshot.candidates[:10]
        if compact_whitespace(item.text)
    )
    if budget_ms <= 0:
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="no latency budget remaining",
            budget_ms=budget_ms,
            request_type=request_type,
            rime_candidate_count=len(rime_candidate_texts),
        )
    if max_candidates <= 0:
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="no side candidate slot",
            budget_ms=budget_ms,
            request_type=request_type,
            rime_candidate_count=len(rime_candidate_texts),
        )
    if not _MODEL_LANE_SEMAPHORE.acquire(blocking=False):
        cached_predictions = _get_model_holdover_predictions(
            project=project,
            current_input=current_input,
            explicit_recent_context=explicit_recent_context,
            max_candidates=max_candidates,
            allow_nearby=False,
        )
        if cached_predictions:
            return cached_predictions, _model_lane_status(
                called=False,
                timed_out=False,
                skipped_reason="model lane already running; reused recent model holdover",
                budget_ms=budget_ms,
                prediction_count=len(cached_predictions),
                holdover_hit=True,
                request_type=request_type,
                rime_candidate_count=len(rime_candidate_texts),
            )
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="model lane already running",
            budget_ms=budget_ms,
            request_type=request_type,
            rime_candidate_count=len(rime_candidate_texts),
        )

    done = Event()
    result: dict[str, object] = {"predictions": []}

    def run_prediction() -> None:
        started = time.perf_counter()
        try:
            if request_type == PREDICTION_REQUEST_PINYIN_CONSTRAINED:
                # Small local IME models follow short prefix-constrained prompts
                # more reliably when the context is the clean on-screen text,
                # not the expanded "history/reference" wrapper used for RAG.
                recent_context = compact_whitespace(explicit_recent_context)[-420:]
                result["contextMode"] = "explicit-pinyin-constrained"
            elif budget_ms <= _REALTIME_MODEL_CONTEXT_BUDGET_MS:
                recent_context = compact_whitespace(explicit_recent_context)[-420:]
                result["contextMode"] = "explicit-realtime"
            elif request_type == PREDICTION_REQUEST_NO_INPUT:
                # Post-commit prediction is a continuation task. The RAG lane
                # can use expanded history, but small local models are more
                # reliable when they see only clean on-screen context instead
                # of "history/reference/current context" wrappers.
                recent_context = compact_whitespace(explicit_recent_context)[-420:]
                result["contextMode"] = "explicit-post-commit"
            else:
                context_event_limit, context_char_limit = model_prediction_context_limits()
                recent_context = build_prediction_context(
                    core,
                    explicit_recent_context=explicit_recent_context,
                    project=project,
                    limit=context_event_limit,
                    max_chars=context_char_limit,
                )
                result["contextMode"] = "history-expanded"
            result["historyContext"] = recent_context
            if int((time.perf_counter() - started) * 1000) >= budget_ms:
                result["skippedReason"] = "history context exceeded latency budget"
                return
            result["requestType"] = request_type
            result["rimeCandidateCount"] = len(rime_candidate_texts)
            raw_predictions = predict_with_optional_request_context(
                predictor,
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                request_type=request_type,
                rime_candidates=rime_candidate_texts,
            )
            result["rawPredictionCount"] = len(raw_predictions)
            predictions = _filter_model_predictions(
                raw_predictions,
                current_input=current_input,
                explicit_recent_context=explicit_recent_context,
                prediction_context=recent_context,
                pinyin_prefix=stable_short_pinyin_prefix(snapshot) if request_type == PREDICTION_REQUEST_PINYIN_CONSTRAINED else "",
            )
            result["predictions"] = predictions
            if not predictions:
                predictor_error = _predictor_last_error(predictor)
                if predictor_error:
                    result["error"] = predictor_error
                elif request_type == PREDICTION_REQUEST_PINYIN_CONSTRAINED and raw_predictions:
                    result["skippedReason"] = "model predictions did not match pinyin prefix"
            if isinstance(result["predictions"], list) and result["predictions"]:
                _store_model_holdover_predictions(
                    project=project,
                    current_input=current_input,
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
            current_input=current_input,
            explicit_recent_context=explicit_recent_context,
            max_candidates=max_candidates,
            allow_nearby=False,
        )
        if cached_predictions:
            return cached_predictions, _model_lane_status(
                called=True,
                timed_out=True,
                skipped_reason="model lane exceeded latency budget; reused recent model holdover",
                budget_ms=budget_ms,
                prediction_count=len(cached_predictions),
                holdover_hit=True,
                request_type=request_type,
                rime_candidate_count=len(rime_candidate_texts),
            )
        return [], _model_lane_status(
            called=True,
            timed_out=True,
            skipped_reason="model lane exceeded latency budget",
            budget_ms=budget_ms,
            request_type=request_type,
            rime_candidate_count=len(rime_candidate_texts),
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
        context_mode=_string(result.get("contextMode")),
        request_type=_string(result.get("requestType")) or request_type,
        rime_candidate_count=_optional_int(result.get("rimeCandidateCount")) or len(rime_candidate_texts),
    )


def _filter_model_predictions(
    predictions: list[ModelPrediction],
    *,
    current_input: str,
    explicit_recent_context: str,
    prediction_context: str = "",
    pinyin_prefix: str = "",
) -> list[ModelPrediction]:
    cleaned: list[ModelPrediction] = []
    seen: set[str] = set()
    for prediction in predictions:
        text = _clean_model_prediction_text(
            prediction.text,
            current_input=current_input,
            explicit_recent_context=explicit_recent_context,
            prediction_context=prediction_context,
        )
        normalized = compact_whitespace(text).lower()
        if not normalized or normalized in seen:
            continue
        if pinyin_prefix and not _model_prediction_matches_pinyin_prefix(prediction, text, pinyin_prefix):
            continue
        seen.add(normalized)
        if text == prediction.text:
            cleaned.append(prediction)
        else:
            cleaned.append(
                ModelPrediction(
                    text=text,
                    rank=prediction.rank,
                    provider_name=prediction.provider_name,
                    latency_ms=prediction.latency_ms,
                    confidence=prediction.confidence,
                    metadata=dict(prediction.metadata),
                )
            )
    return cleaned


def _model_prediction_matches_pinyin_prefix(prediction: ModelPrediction, text: str, prefix: str) -> bool:
    prefix_norm = _pinyin_constraint_norm(prefix)
    if not prefix_norm:
        return True
    keys: list[str] = []
    metadata = dict(prediction.metadata or {})
    for key in ("initials", "pinyin_initials"):
        value = metadata.get(key)
        if isinstance(value, str):
            keys.append(_pinyin_constraint_norm(value))
    for key in ("pinyin", "full_pinyin", "pinyin_prefixes"):
        value = metadata.get(key)
        if isinstance(value, str):
            keys.extend(_pinyin_constraint_norm(part) for part in value.replace("'", " ").split())
            keys.append(_pinyin_constraint_norm(value))
        elif isinstance(value, (list, tuple)):
            keys.extend(_pinyin_constraint_norm(str(part)) for part in value)
    keys.append(_pinyin_constraint_norm(text_initials(text)))
    return any(key.startswith(prefix_norm) for key in dict.fromkeys(keys) if key)


def _pinyin_constraint_norm(value: str) -> str:
    return "".join(char.lower() for char in compact_whitespace(value) if char.isascii() and char.isalnum())


def _clean_model_prediction_text(
    text: str,
    *,
    current_input: str,
    explicit_recent_context: str,
    prediction_context: str = "",
) -> str:
    surface = compact_whitespace(text)
    if not surface:
        return ""
    surface = re.sub(r"(?is)<think>.*?</think>", " ", surface)
    surface = re.sub(r"(?is)<think>.*", " ", surface)
    surface = compact_whitespace(surface)
    for prefix in (current_input, explicit_recent_context):
        prefix = compact_whitespace(prefix)
        if prefix and surface.startswith(prefix) and _has_repeated_recent_memory_prefix(prefix):
            surface = compact_whitespace(surface.removeprefix(prefix))
    surface = compact_whitespace(surface)
    surface = re.sub(r"^[,，。！？；;、\s]+|[,，。！？；;、\s]+$", "", surface)
    surface = _collapse_repeated_recent_memory_surface(surface)
    if not surface:
        return ""
    if _looks_like_broken_recent_memory_surface(surface):
        return ""
    if _looks_like_model_prompt_echo(surface):
        return ""
    if _looks_like_meta_candidate_surface(surface):
        return ""
    if _model_prediction_repeats_context(
        surface,
        current_input=current_input,
        explicit_recent_context=explicit_recent_context,
        prediction_context=prediction_context,
    ):
        return ""
    if surface in {"续写", "继续", "候选", "预测"}:
        return ""
    return surface


def _looks_like_model_prompt_echo(surface: str) -> bool:
    normalized = compact_whitespace(surface)
    lowered = normalized.lower()
    if _looks_like_prompt_example_leak(normalized):
        return True
    markers = (
        "已上屏上下文",
        "当前拼音",
        "当前输入",
        "候选词",
        "候选 JSON",
        "assistant",
        "system",
        "user",
        "/no_think",
    )
    if any(marker.lower() in lowered for marker in markers):
        return True
    if normalized.endswith("候选") and len(normalized) <= 6:
        return True
    return False


def _model_prediction_repeats_context(
    surface: str,
    *,
    current_input: str,
    explicit_recent_context: str,
    prediction_context: str,
) -> bool:
    candidate_norm = _repeat_norm(surface)
    if not candidate_norm:
        return True
    for context in (current_input, explicit_recent_context, prediction_context):
        context_norm = _repeat_norm(context)
        if not context_norm:
            continue
        if candidate_norm == context_norm or candidate_norm in context_norm:
            return True
    return False


def _repeat_norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", compact_whitespace(text), flags=re.UNICODE).lower()


def _has_repeated_recent_memory_prefix(text: str) -> bool:
    parts = [part for part in compact_whitespace(text).split(" ") if part]
    if len(parts) < 3:
        return False
    for width in range(1, min(5, len(parts) // 2 + 1)):
        if parts[:width] == parts[width : width * 2]:
            return True
    return False


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
    context_mode: str = "",
    request_type: str = "",
    rime_candidate_count: int = 0,
    requested_max_candidates: int = 0,
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
        "contextMode": context_mode,
        "requestType": request_type,
        "rimeCandidateCount": max(0, int(rime_candidate_count)),
        "requestedMaxCandidates": max(0, int(requested_max_candidates)),
    }


def clear_model_prediction_holdover_cache() -> None:
    with _MODEL_HOLDOVER_LOCK:
        _MODEL_HOLDOVERS.clear()


def clear_prediction_manager_cache() -> None:
    with _PREDICTION_MANAGER_LOCK:
        _PREDICTION_MANAGERS.clear()


def wait_for_model_prediction_lane_idle(timeout_s: float = 1.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() <= deadline:
        if _MODEL_LANE_SEMAPHORE.acquire(blocking=False):
            _MODEL_LANE_SEMAPHORE.release()
            return True
        time.sleep(0.005)
    return False


def _prediction_manager_for_snapshot(
    snapshot: RimeContextSnapshot,
    *,
    default_project: str,
) -> PredictionManager:
    project = compact_whitespace(snapshot.project or default_project)
    app = compact_whitespace(snapshot.app)
    session_id = compact_whitespace(snapshot.session_id)
    key = (project, app, session_id)
    with _PREDICTION_MANAGER_LOCK:
        manager = _PREDICTION_MANAGERS.get(key)
        if manager is None:
            manager = PredictionManager(candidate_pool_ttl_ms=_POST_COMMIT_PANEL_TTL_MS)
            _PREDICTION_MANAGERS[key] = manager
        return manager


def _should_clear_prediction_pool(
    *,
    snapshot: RimeContextSnapshot,
    trigger_decision: RimeSideCandidateTriggerDecision,
    raw_commit_text: str,
) -> bool:
    if compact_whitespace(raw_commit_text):
        return True
    if not compact_whitespace(snapshot.committed_context):
        return True
    reason = trigger_decision.reason
    if reason in {
        "skip: stale post-commit continuation",
        "skip: raw pinyin fallback",
        "skip: empty semantic signal",
        "skip: low-information Rime candidates",
    }:
        return True
    return False


def _store_model_holdover_predictions(
    *,
    project: str,
    current_input: str,
    explicit_recent_context: str,
    predictions: list[ModelPrediction],
) -> None:
    fingerprint = _holdover_input_state_fingerprint(
        explicit_recent_context=explicit_recent_context,
        current_input=current_input,
    )
    context = _holdover_context_text(explicit_recent_context)
    query = _holdover_query_text(current_input)
    if not fingerprint:
        return
    visible = tuple(predictions[:10])
    if not visible:
        return
    with _MODEL_HOLDOVER_LOCK:
        _MODEL_HOLDOVERS[(project, fingerprint)] = _ModelPredictionHoldover(
            project=project,
            input_state_fingerprint=fingerprint,
            explicit_recent_context=context,
            current_input=query,
            predictions=visible,
            created_at=time.monotonic(),
        )


def _get_model_holdover_predictions(
    *,
    project: str,
    current_input: str,
    explicit_recent_context: str,
    max_candidates: int,
    allow_nearby: bool = False,
) -> list[ModelPrediction]:
    fingerprint = _holdover_input_state_fingerprint(
        explicit_recent_context=explicit_recent_context,
        current_input=current_input,
    )
    if not fingerprint:
        return []
    now = time.monotonic()
    limit = max(1, min(10, int(max_candidates)))
    with _MODEL_HOLDOVER_LOCK:
        cached = _MODEL_HOLDOVERS.get((project, fingerprint))
        if cached is not None and now - cached.created_at > _MODEL_HOLDOVER_TTL_MS / 1000:
            _MODEL_HOLDOVERS.pop((project, fingerprint), None)
            return []
        if cached is not None:
            return list(cached.predictions[:limit])
        if not allow_nearby:
            return []
        context = _holdover_context_text(explicit_recent_context)
        query = _holdover_query_text(current_input)
        stale_keys: list[tuple[str, str]] = []
        nearby: _ModelPredictionHoldover | None = None
        for key, candidate in _MODEL_HOLDOVERS.items():
            if key[0] != project:
                continue
            if now - candidate.created_at > _MODEL_HOLDOVER_TTL_MS / 1000:
                stale_keys.append(key)
                continue
            if not _nearby_holdover_input_state_matches(
                candidate,
                explicit_recent_context=context,
                current_input=query,
            ):
                continue
            if nearby is None or candidate.created_at > nearby.created_at:
                nearby = candidate
        for key in stale_keys:
            _MODEL_HOLDOVERS.pop(key, None)
        if nearby is None:
            return []
        return list(nearby.predictions[:limit])


def _holdover_input_state_fingerprint(*, explicit_recent_context: str, current_input: str) -> str:
    context = _holdover_context_text(explicit_recent_context)
    query = _holdover_query_text(current_input)
    if not context and not query:
        return ""
    return _short_stable_id(context, query)


def _holdover_context_text(explicit_recent_context: str) -> str:
    return compact_whitespace(explicit_recent_context)[-420:]


def _holdover_query_text(current_input: str) -> str:
    return compact_whitespace(current_input)[:240]


def _nearby_holdover_input_state_matches(
    cached: _ModelPredictionHoldover,
    *,
    explicit_recent_context: str,
    current_input: str,
) -> bool:
    if not cached.explicit_recent_context or not explicit_recent_context:
        return False
    if not _nearby_holdover_text_match(cached.explicit_recent_context, explicit_recent_context):
        return False
    if cached.current_input and current_input:
        return _nearby_holdover_text_match(cached.current_input, current_input)
    return True


def _nearby_holdover_text_match(previous: str, current: str) -> bool:
    previous_norm = compact_whitespace(previous)
    current_norm = compact_whitespace(current)
    if not previous_norm or not current_norm:
        return False
    if previous_norm == current_norm:
        return True
    min_len = min(len(previous_norm), len(current_norm))
    if min_len < 8:
        return False
    if current_norm.startswith(previous_norm):
        return len(current_norm) - len(previous_norm) <= 24
    if previous_norm.startswith(current_norm):
        return len(previous_norm) - len(current_norm) <= 16
    return False


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
    memory_context = _selection_memory_context(recent_context=recent_context, query=query)
    preedit = _string(payload.get("preedit"))
    label = _string(candidate.get("selectionKey") or candidate.get("label"))
    candidate_rank = _optional_int(candidate.get("selectionRank")) or _candidate_rank(label)
    tags = tuple(
        item
        for item in (
            "squirrel",
            "rime-sidecar",
            "sidecar-selected",
            f"source:{source_type}" if source_type else "",
        )
        if item
    )
    event_id = ""
    if not dry_run:
        event_id = adapter.commit_text(
            insert_text,
            recent_context=memory_context,
            preedit=preedit,
            schema_id="rime_sidecar",
            app=_string(payload.get("app")) or "squirrel",
            project=project,
            source=_string(payload.get("source")) or "squirrel_rime_sidecar",
            candidate_rank=candidate_rank,
            provider_name=_string(payload.get("providerName")) or f"rime-sidecar:{source_type}",
            tags=tags,
        )

    commit_action_payload: dict[str, object] | None = None
    action_payload: dict[str, object] | None = None
    skipped_actions: list[dict[str, object]] = []
    if not dry_run:
        action_payload = _apply_candidate_memory_action(
            core=core,
            candidate=candidate,
            action_type="accepted",
            query=query,
            metadata={
                "surface_text": _string(candidate.get("text")) or insert_text,
                "insert_text": insert_text,
                "source": "rime-sidecar-select",
            },
        )
        if action_payload is None:
            commit_action_payload = _apply_committed_event_feedback(
                core=core,
                event_id=event_id,
                action_type="accepted",
                query=query,
                suggestion_id=_string(candidate.get("suggestionId") or candidate.get("suggestion_id"))
                or f"committed:{source_type}:{candidate_rank or 0}",
                metadata={
                    "surface_text": _string(candidate.get("text")) or insert_text,
                    "insert_text": insert_text,
                    "source": "rime-sidecar-select-committed-event",
                    "source_type": source_type,
                    "selection_rank": candidate_rank or 0,
                },
            )
        if candidate_rank is not None:
            for shown_candidate in _shown_candidate_payloads(payload):
                shown_rank = _candidate_display_rank(shown_candidate)
                if shown_rank is None or shown_rank >= candidate_rank:
                    continue
                if _same_candidate_identity(shown_candidate, candidate):
                    continue
                skipped_payload = _apply_candidate_memory_action(
                    core=core,
                    candidate=shown_candidate,
                    action_type="skipped",
                    query=query,
                    metadata={
                        "surface_text": _string(shown_candidate.get("text")),
                        "insert_text": _string(
                            shown_candidate.get("insertText")
                            or shown_candidate.get("insert_text")
                            or shown_candidate.get("text")
                        ),
                        "source": "rime-sidecar-select-skipped-higher",
                        "selected_text": _string(candidate.get("text")) or insert_text,
                        "selected_source_type": source_type,
                        "selected_rank": candidate_rank,
                        "skipped_rank": shown_rank,
                    },
                )
                if skipped_payload is not None:
                    skipped_actions.append(skipped_payload)

    return {
        "schemaVersion": "rag-ime.rime-selection.v1",
        "ok": True,
        "dryRun": dry_run,
        "eventId": event_id,
        "project": project,
        "sourceType": source_type,
        "insertText": insert_text,
        "recordedAction": action_payload is not None,
        "recordedCommitAction": commit_action_payload is not None,
        "recordedActionCount": (1 if action_payload is not None else 0)
        + (1 if commit_action_payload is not None else 0)
        + len(skipped_actions),
        "action": action_payload,
        "commitAction": commit_action_payload,
        "skippedActionCount": len(skipped_actions),
        "skippedActions": skipped_actions,
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
        latency_budget_ms=_bounded_int(payload.get("latencyBudgetMs"), default=300, minimum=30, maximum=20000),
        max_visible_candidates=_bounded_int(payload.get("maxVisibleCandidates"), default=8, minimum=1, maximum=10),
        max_side_candidates=_bounded_int(payload.get("maxSideCandidates"), default=8, minimum=0, maximum=10),
        idle_ms=_bounded_int(_first_present(payload, rime_context, "idleMs"), default=0, minimum=0, maximum=10000),
        force_side_candidates=_bool(
            _first_present(payload, rime_context, "forceSideCandidates"),
            default=False,
        ),
        progressive_follow_up=_bool(
            _first_present(payload, rime_context, "progressiveFollowUp"),
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
        prefix = stable_short_pinyin_prefix(snapshot)
        context = compact_whitespace(snapshot.committed_context)
        query_parts = tuple(part for part in (context[-160:] if context else "", prefix, candidate_text) if part)
        if context:
            return compact_whitespace(" ".join(query_parts)), "rimeCandidates"
        if prefix:
            return compact_whitespace(f"{prefix} {candidate_text}"), "rimeCandidates"
        return candidate_text, "rimeCandidates"
    preedit = compact_whitespace(snapshot.preedit)
    raw_input = compact_whitespace(snapshot.raw_input)
    if preedit and preedit != raw_input:
        return preedit, "preedit"
    context = compact_whitespace(snapshot.committed_context)
    if context:
        return context[-240:], "committedContext"
    return raw_input, "rawInputFallback"


def prediction_first_merge_enabled(payload: Mapping[str, object]) -> bool:
    if "predictionFirstMerge" in payload:
        return _bool(payload.get("predictionFirstMerge"), default=False)
    frontend_build = compact_whitespace(str(payload.get("frontendBuild") or ""))
    schema_version = compact_whitespace(str(payload.get("schemaVersion") or ""))
    return frontend_build.startswith("rag-ime.") or schema_version.startswith("rag-ime.squirrel")


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

    if raw_english_candidate_text(snapshot):
        return RimeSideCandidateTriggerDecision(False, "skip: raw ascii passthrough")

    if query_basis == "rimeCandidates" and _active_rime_candidates_are_low_information(snapshot):
        return RimeSideCandidateTriggerDecision(False, "skip: low-information Rime candidates")

    signal_len = semantic_signal_length(semantic_query)
    if signal_len <= 0:
        return RimeSideCandidateTriggerDecision(False, "skip: empty semantic signal")

    if query_basis == "committedContext" and _committed_context_is_low_information(snapshot, semantic_query):
        return RimeSideCandidateTriggerDecision(False, "skip: low-information committed context")

    if snapshot.force_side_candidates:
        return RimeSideCandidateTriggerDecision(True, "force: explicit side candidate refresh")

    if query_basis == "rawInputFallback":
        return RimeSideCandidateTriggerDecision(False, "skip: raw pinyin fallback")

    if query_basis == "rawSemanticInput":
        return RimeSideCandidateTriggerDecision(True, "refresh: semantic raw input")

    if query_basis == "commitTextPreview" and signal_len >= 2:
        return RimeSideCandidateTriggerDecision(True, "refresh: commit preview")

    if query_basis == "rimeCandidates":
        if not _rime_candidates_have_meaningful_signal(snapshot):
            return RimeSideCandidateTriggerDecision(False, "skip: low-information Rime candidates")
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
        no_active_composition = not compact_whitespace(snapshot.raw_input) and not compact_whitespace(snapshot.preedit)
        if signal_len >= 4:
            if snapshot.idle_ms > _POST_COMMIT_PANEL_TTL_MS:
                return RimeSideCandidateTriggerDecision(False, "skip: stale post-commit continuation")
            return RimeSideCandidateTriggerDecision(
                True,
                "refresh: post-commit continuation" if no_active_composition else "refresh: committed context fallback",
            )
        if snapshot.idle_ms >= 300 and signal_len >= 4:
            return RimeSideCandidateTriggerDecision(True, "refresh: idle committed context")
        return RimeSideCandidateTriggerDecision(False, "skip: waiting for active composition signal")

    return RimeSideCandidateTriggerDecision(False, "skip: unsupported query basis")


def semantic_signal_length(text: str) -> int:
    return sum(1 for char in compact_whitespace(text) if not char.isspace())


def _committed_context_is_low_information(snapshot: RimeContextSnapshot, semantic_query: str) -> bool:
    if compact_whitespace(snapshot.raw_input) or compact_whitespace(snapshot.preedit):
        return False
    if compact_whitespace(snapshot.commit_text_preview) or snapshot.candidates:
        return False
    return semantic_signal_length(semantic_query) < 8


def _should_suppress_post_commit_rag_only(
    snapshot: RimeContextSnapshot,
    model_predictions: list[ModelPrediction],
    suggestions: list[InputSuggestion],
) -> bool:
    _ = snapshot, model_predictions, suggestions
    # Weak post-commit retrieval is filtered before this point. If a RAG/memory
    # item survives, it is either semantically aligned with the current text or
    # backed by explicit user feedback, so it should remain selectable even when
    # the local model has no live candidate.
    return False


def _active_rime_candidates_are_low_information(snapshot: RimeContextSnapshot) -> bool:
    active_input = compact_whitespace(snapshot.preedit or snapshot.raw_input)
    if not active_input or not snapshot.candidates:
        return False
    return not _rime_candidates_have_meaningful_signal(snapshot)


def _rime_candidates_have_meaningful_signal(snapshot: RimeContextSnapshot) -> bool:
    for candidate in snapshot.candidates[:6]:
        if _text_has_meaningful_ime_signal(candidate.text):
            return True
    return False


def _text_has_meaningful_ime_signal(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return False
    lowered = surface.lower()
    if lowered in _SEMANTIC_ASCII_TERMS:
        return True
    ascii_terms = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}", surface)
    if any(term.lower() in _SEMANTIC_ASCII_TERMS for term in ascii_terms):
        return True
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", surface)
    for run in cjk_runs:
        if len(run) >= 2 and any(char not in _LOW_INFORMATION_CJK_TOKENS for char in run):
            return True
    return False


def stable_short_pinyin_prefix(snapshot: RimeContextSnapshot) -> str:
    """Return a short user pinyin prefix that can constrain RAG/memory lookup.

    Long raw strings are often typo-heavy pinyin fragments; those should not be
    used as semantic RAG queries. A short prefix such as "sj" is different: it is
    the user's active constraint and should match the phrase-memory pinyin index.
    """

    prefix = compact_whitespace(snapshot.preedit or snapshot.raw_input).lower()
    if not prefix or not prefix.isascii() or not prefix.isalnum():
        return ""
    return prefix if 1 <= len(prefix) <= 4 else ""


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
        return display
    input_mode = infer_input_mode(snapshot)
    rime_reserve = _display_rime_reserve(snapshot=snapshot, mode=input_mode, max_visible=max_visible)
    side_budget = min(snapshot.max_side_candidates, max(0, max_visible - rime_reserve))
    model_items = list(model_predictions)
    rag_items: list[tuple[int, InputSuggestion]] = []
    memory_items: list[tuple[int, InputSuggestion]] = []
    for index, suggestion in enumerate(suggestions):
        metadata = dict(suggestion.metadata)
        source_type = str(metadata.get("source_type") or "rag")
        if source_type == "memory":
            memory_items.append((index, suggestion))
        else:
            rag_items.append((index, suggestion))

    side_inserted = 0
    has_suggestion_items = bool(rag_items or memory_items)
    suggestion_count = len(rag_items) + len(memory_items)
    if side_budget <= 1:
        suggestion_reserve = 0
    elif side_budget == 2:
        suggestion_reserve = min(suggestion_count, 1)
    else:
        minimum_model_slots = min(2, len(model_items))
        suggestion_reserve = min(
            suggestion_count,
            rag_block_reserve(side_budget),
            max(0, side_budget - minimum_model_slots),
        )
    model_before_suggestions_limit = max(0, side_budget - suggestion_reserve)

    def append_model() -> bool:
        nonlocal side_inserted
        while model_items:
            if side_inserted >= side_budget or len(display) >= max_visible - rime_reserve:
                return False
            prediction = model_items.pop(0)
            normalized_text = _display_text_norm(prediction.text)
            if not normalized_text or normalized_text in display_texts:
                continue
            display_texts.add(normalized_text)
            display.append(
                SideCandidateDisplayItem(
                    label=_display_label("", len(display)),
                    text=prediction.text,
                    insert_text=str(prediction.metadata.get("insert_text") or prediction.text),
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
            side_inserted += 1
            return True
        return False

    def append_suggestion(group: list[tuple[int, InputSuggestion]]) -> bool:
        nonlocal side_inserted
        while group:
            if side_inserted >= side_budget or len(display) >= max_visible - rime_reserve:
                return False
            source_index, suggestion = group.pop(0)
            normalized_text = _display_text_norm(suggestion.surface_text)
            if not normalized_text or normalized_text in display_texts:
                continue
            display_texts.add(normalized_text)
            metadata = dict(suggestion.metadata)
            source_type = str(metadata.get("source_type") or "rag")
            if source_type not in {"rag", "memory"}:
                source_type = "rag"
            display.append(
                SideCandidateDisplayItem(
                    label=_display_label("", len(display)),
                    text=suggestion.surface_text,
                    insert_text=str(metadata.get("insert_text") or suggestion.surface_text),
                    source_type=source_type,
                    selection_action="commit_side_candidate",
                    source_index=source_index,
                    comment=suggestion.suggestion_type,
                    evidence_preview=suggestion.evidence_preview,
                    expanded_evidence=suggestion.expanded_evidence,
                    suggestion_id=suggestion.suggestion_id,
                    memory_id=str(metadata.get("memory_id") or suggestion.suggestion_id),
                    source_event_id=suggestion.source_event_id,
                    display_layout="block",
                    display_lane="memory",
                    metadata=metadata,
                )
            )
            side_inserted += 1
            return True
        return False

    while side_inserted < model_before_suggestions_limit and len(display) < max_visible - rime_reserve:
        if not append_model():
            break
    append_suggestion(rag_items)
    append_suggestion(memory_items)
    while side_inserted < side_budget and len(display) < max_visible - rime_reserve:
        if has_suggestion_items:
            progressed = append_suggestion(rag_items) or append_suggestion(memory_items)
        else:
            progressed = append_model()
        if not progressed:
            break
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


def _display_rime_reserve(*, snapshot: RimeContextSnapshot, mode: object, max_visible: int) -> int:
    mode_value = getattr(mode, "value", str(mode))
    if mode_value not in {"anchor_composing", "prefix_constrained_composing"}:
        return 0
    rime_count = sum(1 for candidate in snapshot.candidates if compact_whitespace(candidate.text))
    if rime_count <= 0:
        return 0
    if max_visible >= 8:
        return min(3, rime_count)
    if max_visible >= 5:
        return min(2, rime_count)
    return min(1, rime_count)


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
        "expandedEvidence": item.expanded_evidence,
        "suggestionId": item.suggestion_id,
        "memoryId": item.memory_id,
        "sourceEventId": item.source_event_id,
        "rimeIndex": item.rime_index,
        "displayLayout": item.display_layout,
        "displayLane": item.display_lane or item.source_type,
        "metadata": dict(item.metadata),
    }


def _bind_display_candidates_to_session(
    *,
    display_candidates: list[SideCandidateDisplayItem],
    snapshot: RimeContextSnapshot,
    prediction_session_payload: Mapping[str, object],
) -> list[SideCandidateDisplayItem]:
    session_fingerprint = _string(prediction_session_payload.get("sessionFingerprint"))
    context_fingerprint = _string(prediction_session_payload.get("contextFingerprint")) or _context_fingerprint(
        snapshot.committed_context
    )
    phase = _string(prediction_session_payload.get("phase"))
    scope = _string(prediction_session_payload.get("selectionScope"))
    bound: list[SideCandidateDisplayItem] = []
    for item in display_candidates:
        metadata = dict(item.metadata)
        metadata.update(
            {
                "sessionFingerprint": session_fingerprint,
                "contextFingerprint": context_fingerprint,
                "requestSeq": snapshot.request_seq,
                "sessionId": snapshot.session_id,
                "predictionSessionPhase": phase,
                "selectionScope": scope,
            }
        )
        bound.append(replace(item, metadata=metadata))
    return bound


def _prediction_session_expiry_ms(prediction_session_payload: Mapping[str, object]) -> int:
    phase = _string(prediction_session_payload.get("phase"))
    if phase == "post_commit":
        return _POST_COMMIT_PANEL_TTL_MS
    if phase == "prefix_constrained":
        return _PREFIX_CONSTRAINED_PANEL_TTL_MS
    return 0


def _response_session_fingerprint(
    *,
    snapshot: RimeContextSnapshot,
    mode: str,
    display_candidates: tuple[SideCandidateDisplayItem, ...],
) -> str:
    visible_material = "\x1e".join(
        f"{item.label}:{item.selection_action}:{item.source_type}:{item.source_index}:{item.text}"
        for item in display_candidates[: snapshot.max_visible_candidates]
    )
    material = "\x1f".join(
        (
            snapshot.session_id,
            str(snapshot.request_seq),
            _context_fingerprint(snapshot.committed_context),
            compact_whitespace(snapshot.raw_input),
            compact_whitespace(snapshot.preedit),
            mode,
            visible_material,
        )
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _context_fingerprint(committed_context: str) -> str:
    return compact_whitespace(committed_context)[-420:]


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


def _shown_candidate_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = (
        payload.get("shownCandidates")
        or payload.get("displayCandidates")
        or payload.get("shown_candidates")
        or payload.get("display_candidates")
    )
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _candidate_display_rank(candidate: dict[str, Any]) -> int | None:
    return (
        _optional_int(candidate.get("selectionRank") or candidate.get("selection_rank"))
        or _candidate_rank(
            _string(
                candidate.get("selectionKey")
                or candidate.get("selection_key")
                or candidate.get("label")
            )
        )
    )


def _same_candidate_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_id = (
        _string(left.get("suggestionId") or left.get("suggestion_id")),
        _optional_int(left.get("sourceEventId") or left.get("source_event_id")),
        _string(left.get("memoryId") or left.get("memory_id")),
    )
    right_id = (
        _string(right.get("suggestionId") or right.get("suggestion_id")),
        _optional_int(right.get("sourceEventId") or right.get("source_event_id")),
        _string(right.get("memoryId") or right.get("memory_id")),
    )
    if any(left_id) and left_id == right_id:
        return True
    return (
        _string(left.get("sourceType") or left.get("source_type"))
        == _string(right.get("sourceType") or right.get("source_type"))
        and _string(left.get("text")) == _string(right.get("text"))
        and _string(left.get("insertText") or left.get("insert_text"))
        == _string(right.get("insertText") or right.get("insert_text"))
    )


def _apply_candidate_memory_action(
    *,
    core: CoreClient,
    candidate: dict[str, Any],
    action_type: str,
    query: str,
    metadata: dict[str, object],
) -> dict[str, object] | None:
    source_type = _string(candidate.get("sourceType") or candidate.get("source_type"))
    memory_id = _string(candidate.get("memoryId") or candidate.get("memory_id"))
    suggestion_id = _string(candidate.get("suggestionId") or candidate.get("suggestion_id"))
    source_event_id = _optional_int(candidate.get("sourceEventId") or candidate.get("source_event_id"))
    if (
        source_type not in {"rag", "memory"}
        or not memory_id
        or not suggestion_id
        or source_event_id is None
        or source_event_id <= 0
    ):
        return None
    action = core.apply_action(
        MemoryAction(
            action_id=None,
            created_at_ms=now_ms(),
            memory_id=memory_id,
            action_type=action_type,
            query=query,
            suggestion_id=suggestion_id,
            source_event_id=source_event_id,
            metadata=metadata,
        )
    )
    return action_response_payload(action)


def _apply_committed_event_feedback(
    *,
    core: CoreClient,
    event_id: str,
    action_type: str,
    query: str,
    suggestion_id: str,
    metadata: dict[str, object],
) -> dict[str, object] | None:
    source_event_id = _event_id_from_memory_id(event_id)
    if source_event_id is None:
        return None
    action = core.apply_action(
        MemoryAction(
            action_id=None,
            created_at_ms=now_ms(),
            memory_id=event_id,
            action_type=action_type,
            query=query,
            suggestion_id=suggestion_id,
            source_event_id=source_event_id,
            metadata=metadata,
        )
    )
    return action_response_payload(action)


def _selection_memory_context(*, recent_context: str, query: str) -> str:
    context = compact_whitespace(recent_context)
    query_text = compact_whitespace(query)
    if not query_text:
        return context
    if query_text in context:
        return context
    if not context:
        return query_text
    return compact_whitespace(f"{context} {query_text}")


def _event_id_from_memory_id(memory_id: str) -> int | None:
    value = _string(memory_id)
    if not value.startswith("event:"):
        return None
    try:
        event_id = int(value.split(":", 1)[1])
    except (TypeError, ValueError):
        return None
    return event_id if event_id > 0 else None


def _candidate_rank(label: str) -> int | None:
    if not label:
        return None
    if label == "0":
        return 10
    if label.isdigit():
        return int(label)
    return None
