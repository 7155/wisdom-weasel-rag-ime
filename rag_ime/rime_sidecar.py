from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, replace
from threading import BoundedSemaphore, Event, RLock, Thread
from typing import Any, Mapping

from .adapter import InputMethodAdapter, SuggestionRequest
from .context_frame import build_current_input_frame, context_frame_trace_payload
from .context_views import (
    build_display_view,
    build_model_prompt_view,
    build_rag_retrieval_view,
    build_rime_view,
    context_views_trace_payload,
)
from .contracts.key_policy import key_policy_for_prediction_session as contract_key_policy_for_prediction_session
from .contracts.source import source_badge_for, source_color_token_for
from .core_client import CoreClient
from .deepseek_completion import DeepSeekCompletionRequest
from .embeddings import NullEmbeddingProvider
from .history_context import build_prediction_context, model_prediction_context_limits, prediction_context_metadata
from .local_sqlite_core import LocalSqliteCoreClient
from .memory_optimizer import MemoryOptimizerConfig, optimize_suggestions_if_enabled
from .models import (
    FrontendTransaction,
    InputSuggestion,
    MemoryAction,
    ModelPrediction,
    RimeCandidate,
    RimeContextSnapshot,
    SideCandidateDisplayItem,
)
from .memory.curated_store import (
    RealtimeMemoryContext,
    annotate_realtime_memory_candidate,
    decide_realtime_memory_candidate,
)
from .payloads import action_response_payload, model_prediction_to_payload, suggestion_to_payload
from .pinyin_index import build_pinyin_metadata, text_initials
from .prediction_anchors import build_prediction_anchors_from_snapshot, prediction_mode_family
from .prediction_first import (
    InputMode,
    infer_input_mode,
    prediction_session_to_payload,
)
from .prediction.quality import reject_context_echo as quality_reject_context_echo
from .prediction.quality import reject_prompt_leak as quality_reject_prompt_leak
from .prediction_manager import PredictionManager
from .prediction_status import prediction_status_row
from .predictor import (
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
    PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
    PREDICTION_REQUEST_RIME_REORDER,
    PredictionProvider,
    predict_with_optional_request_context,
)
from .runtime_flags import assert_deepseek_not_called, assert_deepseek_scene_allowed
from .side_lane_scheduler import LaneRequestToken, LatestWinsLaneScheduler
from .text_utils import compact_whitespace, now_ms, stable_text_hash, token_terms


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
_REALTIME_MODEL_CONTEXT_BUDGET_MS = 500
_MODEL_HOLDOVER_TTL_MS = 5000
_MODEL_LANE_LEASE_TTL_MS = 3000
_PROGRESSIVE_FIRST_RESPONSE_MS = 700
_PROGRESSIVE_FOLLOW_UP_RETRY_MS = 280
_POST_COMMIT_FIRST_RESPONSE_MS = 150
_POST_COMMIT_COMPLETION_TTL_MS = 12000
_POST_COMMIT_MODEL_HARD_TIMEOUT_MS = 12000
_POST_COMMIT_PANEL_TTL_MS = 8000
_PREFIX_CONSTRAINED_PANEL_TTL_MS = 2600
_REFRESH_DEBOUNCE_MS = 100
_MODEL_LANE_LOCK = RLock()
_MODEL_LANE_ACTIVE_TOKEN: str | None = None
_MODEL_LANE_ACTIVE_STARTED_AT = 0.0
_MODEL_HOLDOVER_LOCK = RLock()
_MODEL_HOLDOVERS: dict[tuple[str, str], "_ModelPredictionHoldover"] = {}
_PREDICTION_MANAGER_LOCK = RLock()
_PREDICTION_MANAGERS: dict[tuple[str, str, str], PredictionManager] = {}
_REFRESH_DEBOUNCE_LOCK = RLock()
_REFRESH_DEBOUNCE: dict[tuple[str, str, str, str, str], "_RefreshDebounceState"] = {}
_SIDE_LANE_SCHEDULER = LatestWinsLaneScheduler()
_POST_COMMIT_COMPLETION_CACHE: "PostCommitCompletionCache"
_POST_COMMIT_PRESENTATION_STREAM_LOCK = RLock()
_POST_COMMIT_PRESENTATION_STREAM_STAGES: dict[str, tuple[int, float]] = {}
_FALSEY_ENV_VALUES = {"0", "false", "no", "off"}
_CANDIDATE_SOURCE_SUFFIXES = (
    "_model",
    "_rag",
    "_memory",
    " [LLM]",
    " [RAG]",
    " LLM",
    " RAG",
    " 模",
    " 查",
    " 忆",
)
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


@dataclass(frozen=True)
class _RefreshDebounceState:
    created_at_ms: int
    request_seq: int
    semantic_query_hash: str


@dataclass(frozen=True)
class PostCommitCompletionKey:
    project: str
    app: str
    hard_context_anchor: str
    context_fingerprint: str
    commit_text_hash: str
    commit_text_length: int
    input_source_id: str
    selection_epoch: int
    request_type: str = PREDICTION_REQUEST_POST_COMMIT_COMPLETION


@dataclass
class PostCommitCompletionJob:
    key: PostCommitCompletionKey
    job_id: str
    created_at: float
    started_at_ms: int
    hard_timeout_ms: int
    state: str = "pending"
    predictions: tuple[ModelPrediction, ...] = ()
    error: str = ""
    completed_at: float = 0.0
    provider_call_count: int = 0
    presentation_stage: int = 0


class PostCommitCompletionCache:
    def __init__(self, *, ttl_ms: int = _POST_COMMIT_COMPLETION_TTL_MS) -> None:
        self._ttl_ms = max(1000, int(ttl_ms))
        self._lock = RLock()
        self._jobs: dict[PostCommitCompletionKey, PostCommitCompletionJob] = {}

    def poll_or_start(
        self,
        *,
        key: PostCommitCompletionKey,
        snapshot: RimeContextSnapshot,
        core: CoreClient,
        predictor: PredictionProvider,
        project: str,
        explicit_recent_context: str,
        max_candidates: int,
        ttl_ms: int,
        hard_timeout_ms: int,
    ) -> tuple[list[ModelPrediction], dict[str, object]]:
        now = time.time()
        ttl_ms = max(1000, int(ttl_ms))
        hard_timeout_ms = max(500, int(hard_timeout_ms))
        start_kwargs: dict[str, object] | None = None
        with self._lock:
            self._ttl_ms = ttl_ms
            self._drop_expired_locked(now)
            job = self._jobs.get(key)
            if job is not None:
                return self._payload_for_job_locked(job, now=now, cache_hit=job.state == "completed")
            job_id = _short_stable_id(
                "post-commit-completion",
                key.project,
                key.app,
                key.context_fingerprint,
                key.commit_text_hash,
                str(key.selection_epoch),
                key.input_source_id,
            )
            job = PostCommitCompletionJob(
                key=key,
                job_id=job_id,
                created_at=now,
                started_at_ms=now_ms(),
                hard_timeout_ms=hard_timeout_ms,
                state="pending",
            )
            self._jobs[key] = job
            predictions, lane = self._payload_for_job_locked(job, now=now, cache_hit=False, started=True)
            start_kwargs = {
                "job": job,
                "snapshot": snapshot,
                "core": core,
                "predictor": predictor,
                "project": project,
                "explicit_recent_context": explicit_recent_context,
                "max_candidates": max_candidates,
            }
        Thread(
            target=self._run_job,
            name=f"rag-ime-post-commit-completion-{job.job_id}",
            kwargs=start_kwargs,
            daemon=True,
        ).start()
        return predictions, lane

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()

    def _run_job(
        self,
        *,
        job: PostCommitCompletionJob,
        snapshot: RimeContextSnapshot,
        core: CoreClient,
        predictor: PredictionProvider,
        project: str,
        explicit_recent_context: str,
        max_candidates: int,
    ) -> None:
        started = time.perf_counter()
        predictions: list[ModelPrediction] = []
        state = "completed"
        error = ""
        try:
            recent_context = compact_whitespace(explicit_recent_context)[-420:]
            if not recent_context:
                context_event_limit, context_char_limit = model_prediction_context_limits()
                recent_context = build_prediction_context(
                    core,
                    explicit_recent_context=explicit_recent_context,
                    project=project,
                    limit=context_event_limit,
                    max_chars=context_char_limit,
                )
            raw_predictions = predict_with_optional_request_context(
                predictor,
                current_input="",
                recent_context=recent_context,
                max_candidates=max_candidates,
                request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                rime_candidates=(),
            )
            predictions = filter_post_commit_model_completions(
                raw_predictions,
                snapshot=snapshot,
                existing_texts=(),
                max_candidates=max_candidates,
            )
            if int((time.perf_counter() - started) * 1000) > job.hard_timeout_ms:
                state = "timeout"
                predictions = []
        except Exception as exc:  # pragma: no cover - defensive fail-closed guard
            state = "error"
            error = exc.__class__.__name__
        with self._lock:
            current = self._jobs.get(job.key)
            if current is not job:
                return
            current.provider_call_count += 1
            current.completed_at = time.time()
            current.error = error
            current.state = state
            current.predictions = tuple(predictions)

    def _payload_for_job_locked(
        self,
        job: PostCommitCompletionJob,
        *,
        now: float,
        cache_hit: bool,
        started: bool = False,
    ) -> tuple[list[ModelPrediction], dict[str, object]]:
        elapsed_ms = int((now - job.created_at) * 1000)
        if job.state == "pending" and elapsed_ms > job.hard_timeout_ms:
            job.state = "timeout"
            job.completed_at = now
            job.predictions = ()
        predictions, presentation_pending, presentation_stage, presentation_stage_count = (
            _post_commit_presentation_stream_predictions(job)
        )
        state = "hit" if cache_hit and predictions and not presentation_pending else ("started" if started else job.state)
        if presentation_pending:
            state = "streaming"
        lane = _model_lane_status(
            called=True,
            timed_out=job.state == "timeout",
            skipped_reason="" if predictions else f"post-commit completion {state}",
            budget_ms=post_commit_model_hard_timeout_ms(),
            elapsed_ms=elapsed_ms,
            prediction_count=len(predictions),
            request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
            rime_candidate_count=0,
            requested_max_candidates=len(predictions),
        )
        lane.update(
            {
                "asyncMode": True,
                "completionJobId": job.job_id,
                "completionKeyHash": _short_stable_id(
                    job.key.project,
                    job.key.app,
                    job.key.hard_context_anchor,
                    job.key.context_fingerprint,
                    job.key.commit_text_hash,
                    str(job.key.commit_text_length),
                    job.key.input_source_id,
                    str(job.key.selection_epoch),
                    job.key.request_type,
                ),
                "completionJobState": state,
                "cacheHit": bool(cache_hit and predictions),
                "inFlight": job.state == "pending" or presentation_pending,
                "pending": job.state == "pending" or presentation_pending,
                "jobElapsedMs": elapsed_ms,
                "firstResponseMs": post_commit_first_response_budget_ms(),
                "noPinyinFilter": True,
                "requestType": PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                "providerCallCount": job.provider_call_count,
                "completionCacheSize": len(self._jobs),
                "presentationStreaming": bool(presentation_stage_count > 1),
                "presentationStage": presentation_stage,
                "presentationStageCount": presentation_stage_count,
            }
        )
        if job.error:
            lane["error"] = job.error
        return predictions, lane

    def _drop_expired_locked(self, now: float) -> None:
        expired = [
            key
            for key, job in self._jobs.items()
            if int((now - job.created_at) * 1000) > self._ttl_ms
        ]
        for key in expired:
            self._jobs.pop(key, None)


def _post_commit_presentation_stream_predictions(
    job: PostCommitCompletionJob,
) -> tuple[list[ModelPrediction], bool, int, int]:
    if job.state != "completed" or not job.predictions:
        return [], False, 0, 0
    first = job.predictions[0]
    steps = _post_commit_presentation_stream_steps(first.text)
    if not post_commit_presentation_stream_enabled() or len(steps) <= 1:
        return list(job.predictions), False, len(steps), len(steps)
    job.presentation_stage = min(job.presentation_stage + 1, len(steps))
    visible_text = steps[job.presentation_stage - 1]
    presentation_pending = job.presentation_stage < len(steps)
    metadata = dict(first.metadata)
    metadata.update(
        {
            "presentationStreaming": True,
            "presentationStage": job.presentation_stage,
            "presentationStageCount": len(steps),
            "presentationPartial": presentation_pending,
            "presentationFinalTextHash": stable_text_hash(first.text),
        }
    )
    staged_first = replace(
        first,
        text=visible_text,
        metadata=metadata,
    )
    if presentation_pending:
        return [staged_first], True, job.presentation_stage, len(steps)
    return [staged_first, *list(job.predictions[1:])], False, job.presentation_stage, len(steps)


def _post_commit_presentation_stream_steps(text: str) -> list[str]:
    surface = compact_whitespace(text)
    if not surface:
        return []
    if len(surface) <= 3:
        return [surface]
    if re.fullmatch(r"[\u3400-\u9fffA-Za-z0-9 _-]+", surface):
        if len(surface) <= 5:
            raw_steps = [surface[:2], surface]
        else:
            raw_steps = [surface[:2], surface[:4], surface]
    else:
        raw_steps = [surface[: max(2, min(4, len(surface) // 2))], surface]
    steps: list[str] = []
    for step in raw_steps:
        step = compact_whitespace(step)
        if step and step not in steps:
            steps.append(step)
    return steps or [surface]


_POST_COMMIT_COMPLETION_CACHE = PostCommitCompletionCache()


def build_rime_sidecar_response(
    *,
    payload: dict[str, Any],
    adapter: InputMethodAdapter,
    core: CoreClient,
    predictor: PredictionProvider,
    deepseek_completion_provider: Any | None = None,
    default_project: str = "wisdom-weasel-rag-ime",
) -> dict[str, object]:
    snapshot = parse_rime_context_payload(payload, default_project=default_project)
    semantic_query, query_basis = choose_semantic_query(snapshot)
    trigger_decision = decide_side_candidate_refresh(
        snapshot=snapshot,
        semantic_query=semantic_query,
        query_basis=query_basis,
    )
    trigger_decision, refresh_debounce = apply_refresh_debounce(
        snapshot=snapshot,
        trigger_decision=trigger_decision,
        semantic_query=semantic_query,
        query_basis=query_basis,
        default_project=default_project,
    )
    if trigger_decision.should_refresh:
        lane_started = time.perf_counter()
        suggestions, rag_lane, model_predictions, model_lane, progressive_state = run_side_lanes_with_latency_budget(
            adapter=adapter,
            core=core,
            predictor=predictor,
            deepseek_completion_provider=deepseek_completion_provider,
            snapshot=snapshot,
            current_input=semantic_query,
            query_basis=query_basis,
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
        rag_lane["postCommitQualityFilteredCount"] = post_commit_filtered_suggestions - len(suggestions)
        rag_lane["suggestionCount"] = len(suggestions)
        rag_lane["filteredSuggestionCount"] = raw_suggestion_count - len(suggestions)
        if _should_suppress_post_commit_rag_only(snapshot, model_predictions, suggestions):
            rag_lane["postCommitRagOnlySuppressed"] = True
            rag_lane["suppressedSuggestionCount"] = len(suggestions)
            rag_lane["suggestionCount"] = 0
            suggestions = []
        suggestions, optimizer_trace = optimize_suggestions_if_enabled(
            core=core,
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
            input_mode=infer_input_mode(snapshot),
            suggestions=suggestions,
            top_k=snapshot.max_side_candidates,
            latency_budget_ms=snapshot.latency_budget_ms,
        )
        rag_lane["suggestionCount"] = len(suggestions)
        fallback_predictions = _post_commit_empty_result_fallback_predictions(
            snapshot=snapshot,
            semantic_query=semantic_query,
            model_predictions=model_predictions,
            suggestions=suggestions,
            rag_lane=rag_lane,
            model_lane=model_lane,
            progressive_state=progressive_state,
        )
        if fallback_predictions:
            fallback_predictions, fallback_lane_update = _stage_post_commit_fallback_presentation_stream(
                snapshot=snapshot,
                predictions=fallback_predictions,
            )
            model_predictions = fallback_predictions
            model_lane["predictionCount"] = len(model_predictions)
            model_lane["fallbackCandidateCount"] = len(model_predictions)
            model_lane["fallbackReason"] = "demo_safe_empty_post_commit_fallback"
            model_lane["skippedReason"] = ""
            model_lane.update(fallback_lane_update)
            if bool(model_lane.get("pending")):
                progressive_state = _progressive_state(
                    enabled=progressive_sidecar_updates_enabled(),
                    partial=False,
                    should_follow_up=True,
                    pending_lanes=_progressive_pending_lanes(rag_lane=rag_lane, model_lane=model_lane),
                    first_response_budget_ms=post_commit_first_response_budget_ms(),
                    retry_after_ms=progressive_follow_up_retry_ms(),
                )
        model_lane.pop("historyContext", None)
        total_elapsed_ms = int((time.perf_counter() - lane_started) * 1000)
        rag_lane.update(
            {
                "totalLatencyBudgetMs": snapshot.latency_budget_ms,
                "sideLaneMode": "parallel",
                "sideLaneElapsedMs": total_elapsed_ms,
                "memoryOptimizer": optimizer_trace,
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
        optimizer_trace = {"enabled": False, "traceEnabled": False, "maxMs": 15}
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
            "filteredSuggestionCount": 0,
            "postCommitQualityFilteredCount": 0,
            "latencyBudgetMs": 0,
            "elapsedMs": 0,
            "totalLatencyBudgetMs": snapshot.latency_budget_ms,
            "memoryOptimizer": optimizer_trace,
        }
        model_lane = {
            "called": False,
            "timedOut": False,
            "skippedReason": "side candidates disabled by trigger",
            "predictionCount": 0,
            "filteredPredictionCount": 0,
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
                "hardContextAnchor": manager_result.anchors.hard_context_anchor,
                "applyAnchor": manager_result.anchors.apply_anchor,
                "queryAnchor": manager_result.anchors.query_anchor,
                "displayAnchor": manager_result.anchors.display_anchor,
                "snapshotId": (
                    manager_result.stable_snapshot.snapshot_id if manager_result.stable_snapshot else ""
                ),
                "stableSnapshotId": (
                    manager_result.stable_snapshot.snapshot_id if manager_result.stable_snapshot else ""
                ),
                "snapshotGeneration": (
                    manager_result.stable_snapshot.generation if manager_result.stable_snapshot else 0
                ),
                "reusedLastGood": (
                    bool(manager_result.stable_snapshot.reused_last_good) if manager_result.stable_snapshot else False
                ),
                "stablePanelAction": _string(manager_result.stability.get("action")),
                "stablePanelReason": _string(manager_result.stability.get("reason")),
                "stablePanel": manager_result.stability,
                "requestSeq": snapshot.request_seq,
                "expiresAfterMs": _prediction_session_expiry_ms(prediction_session_payload),
                **frontend_transaction_to_payload(snapshot.frontend_transaction),
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
                "stability": manager_result.stability,
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
            **frontend_transaction_to_payload(snapshot.frontend_transaction),
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
    response_input_mode = infer_input_mode(snapshot)
    if response_input_mode in {InputMode.ANCHOR_COMPOSING, InputMode.PREFIX_CONSTRAINED_COMPOSING} and not snapshot.force_side_candidates:
        rime_display_candidates = rime_only_display_candidates(snapshot)
        if rime_display_candidates:
            display_candidates = rime_display_candidates
            prediction_session_payload.update(
                {
                    "phase": "anchor_composing",
                    "inputMode": response_input_mode.value,
                    "candidatePanelVisible": True,
                    "predictionPanelVisible": False,
                    "shouldClearPredictionPanel": False,
                    "clearReason": "",
                    "selectionScope": "rime",
                    "rimeCompositionOwnedByRime": True,
                    "sideCandidateCount": 0,
                    "rimeCandidateCount": len(display_candidates),
                }
            )
    key_policy = key_policy_for_prediction_session(prediction_session_payload)
    status_row = _prediction_status_row_for_response(
        progressive_state=progressive_state,
        rag_lane=rag_lane,
        model_lane=model_lane,
        generation=snapshot.request_seq,
        input_mode=response_input_mode.value,
    )
    if status_row is not None:
        display_candidates.append(status_row)
        if response_input_mode == InputMode.POST_COMMIT_PREDICTING:
            prediction_session_payload.update(
                {
                    "phase": "post_commit",
                    "inputMode": response_input_mode.value,
                    "candidatePanelVisible": True,
                    "predictionPanelVisible": True,
                    "shouldClearPredictionPanel": False,
                    "clearReason": "",
                    "selectionScope": "prediction",
                    "rimeCompositionOwnedByRime": False,
                    "expiresAfterMs": _POST_COMMIT_PANEL_TTL_MS,
                }
            )
            key_policy = key_policy_for_prediction_session(prediction_session_payload)
    ui_mode = ui_mode_for_response(
        input_mode=response_input_mode.value,
        display_candidates=display_candidates,
        status_row_visible=status_row is not None,
    )
    display_candidates = _bind_display_candidates_to_session(
        display_candidates=display_candidates,
        snapshot=snapshot,
        prediction_session_payload=prediction_session_payload,
        key_policy=key_policy,
    )
    _record_display_memory_feedback(
        core=core,
        snapshot=snapshot,
        display_candidates=display_candidates,
        trace_id=_string(
            (
                rag_lane.get("memoryOptimizer", {}).get("traceId")
                if isinstance(rag_lane.get("memoryOptimizer"), dict)
                else ""
            )
        ),
        project=snapshot.project or default_project,
    )
    refresh_decision = refresh_decision_payload(
        snapshot=snapshot,
        trigger_decision=trigger_decision,
        semantic_query=semantic_query,
        debounce=refresh_debounce,
    )
    show_decision = show_decision_payload(
        prediction_session=prediction_session_payload,
        display_candidates=display_candidates,
    )
    prediction_trace_events = prediction_trace_events_payload(
        prediction_session=prediction_session_payload,
        refresh_decision=refresh_decision,
        show_decision=show_decision,
        rag_lane=rag_lane,
        model_lane=model_lane,
        display_candidates=display_candidates,
    )
    context_frame = build_current_input_frame(
        snapshot,
        ui_mode=ui_mode,
        semantic_query=semantic_query,
        query_basis=query_basis,
        foreground_text_payload=payload.get("foregroundText") if isinstance(payload.get("foregroundText"), Mapping) else None,
    )
    rime_view = build_rime_view(context_frame)
    model_view = build_model_prompt_view(context_frame)
    rag_view = build_rag_retrieval_view(context_frame, semantic_query=semantic_query, query_basis=query_basis)
    display_view = build_display_view(
        context_frame,
        candidates=tuple(display_candidates),
        key_policy={str(key): str(value) for key, value in key_policy.items()},
    )
    include_context_text = os.environ.get("RAG_IME_TRACE_INCLUDE_TEXT") == "1"
    return {
        "schemaVersion": RIME_SIDECAR_SCHEMA_VERSION,
        "sessionId": snapshot.session_id,
        "requestSeq": snapshot.request_seq,
        **frontend_transaction_to_payload(snapshot.frontend_transaction),
        "frontendTransaction": frontend_transaction_to_payload(snapshot.frontend_transaction),
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
            "refreshReason": trigger_decision.reason,
            "shouldShow": show_decision["shouldShow"],
            "showReason": show_decision["showReason"],
            "hardClear": show_decision["hardClear"],
            "hardClearReason": show_decision["hardClearReason"],
            "softHold": show_decision["softHold"],
            "softHoldReason": show_decision["softHoldReason"],
            "idleMs": snapshot.idle_ms,
            "semanticSignalLength": semantic_signal_length(semantic_query),
            "forceSideCandidates": snapshot.force_side_candidates,
        },
        "refreshDecision": refresh_decision,
        "showDecision": show_decision,
        "predictionTraceEvents": prediction_trace_events,
        "historyContext": prediction_context,
        "historyContextMeta": prediction_context_metadata(prediction_context),
        "latencyBudgetMs": snapshot.latency_budget_ms,
        "uiMode": ui_mode,
        "contextFrame": context_frame_trace_payload(context_frame, include_text=include_context_text),
        "contextViews": context_views_trace_payload(
            rime_view=rime_view,
            model_view=model_view,
            rag_view=rag_view,
            display_view=display_view,
        ),
        "laneStatus": lane_status_payload(
            rag_lane=rag_lane,
            model_lane=model_lane,
            rime_candidate_count=len(snapshot.candidates),
        ),
        "ragLane": rag_lane,
        "modelLane": model_lane,
        "rimeContext": rime_context_to_payload(snapshot),
        "modelPredictions": [model_prediction_to_payload(item) for item in model_predictions],
        "ragCandidates": [suggestion_to_payload(item) for item in suggestions],
        "displayCandidates": [display_item_to_payload(item) for item in display_candidates],
        "predictionFirst": prediction_first_payload,
        "predictionSession": prediction_session_payload,
        "keyPolicy": key_policy,
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
            "ragKeepsRemainingSideSlots": False,
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
            result["failClosed"] = True
            result["warnings"] = [f"rag_exception:{exc.__class__.__name__}"]
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
        fail_closed=bool(result.get("failClosed")),
        warnings=tuple(str(item) for item in result.get("warnings", []) if str(item)),
    )


def _realtime_rag_adapter(*, adapter: InputMethodAdapter, core: CoreClient, budget_ms: int) -> InputMethodAdapter:
    if budget_ms > _REALTIME_MODEL_CONTEXT_BUDGET_MS or not isinstance(core, LocalSqliteCoreClient):
        return adapter
    optimizer_enabled = MemoryOptimizerConfig.from_env().enabled
    return InputMethodAdapter(
        LocalSqliteCoreClient(
            core.db_path,
            suggestion_cache_size=core.suggestion_cache_size,
            embedding_provider=NullEmbeddingProvider(),
            vector_candidate_limit=0,
            vector_weight=0.0,
            legacy_governance_filter_enabled=not optimizer_enabled,
            v2_governance_filter_enabled=not optimizer_enabled,
        ),
        project=str(getattr(adapter, "project", "wisdom-weasel-rag-ime")),
    )


def _predictor_provider_name(predictor: PredictionProvider) -> str:
    config = getattr(predictor, "config", None)
    value = getattr(config, "provider_name", "") if config is not None else ""
    return compact_whitespace(str(value or predictor.__class__.__name__))


def _predictor_model_name(predictor: PredictionProvider) -> str:
    config = getattr(predictor, "config", None)
    value = getattr(config, "model", "") if config is not None else ""
    return compact_whitespace(str(value or ""))


def _looks_like_deepseek_provider(predictor: PredictionProvider) -> bool:
    identity = f"{_predictor_provider_name(predictor)} {_predictor_model_name(predictor)}".lower()
    return "deepseek" in identity


def run_side_lanes_with_latency_budget(
    *,
    adapter: InputMethodAdapter,
    core: CoreClient,
    predictor: PredictionProvider,
    deepseek_completion_provider: Any | None = None,
    snapshot: RimeContextSnapshot,
    current_input: str,
    query_basis: str,
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
    model_budget_ms = _model_lane_budget_for_request(latency_budget_ms, snapshot=snapshot)
    request_type = model_request_type_for_snapshot(snapshot)
    post_commit_async = _is_post_commit_prediction_snapshot(snapshot) and post_commit_async_completion_enabled()
    if post_commit_async:
        request_type = PREDICTION_REQUEST_POST_COMMIT_COMPLETION
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
    if request_type == PREDICTION_REQUEST_PINYIN_CONSTRAINED:
        prefix = stable_short_pinyin_prefix(snapshot)
        if prefix:
            model_current_input = prefix
    elif _is_post_commit_prediction_snapshot(snapshot):
        model_current_input = ""
    if post_commit_async and not snapshot.progressive_follow_up:
        predictions, model_lane = run_post_commit_completion_async(
            core=core,
            predictor=predictor,
            snapshot=snapshot,
            explicit_recent_context=explicit_recent_context,
            project=project,
            max_candidates=model_candidate_limit,
        )
        rag_lane = _rag_lane_status(
            called=True,
            timed_out=False,
            skipped_reason="RAG lane deferred to post-commit follow-up",
            budget_ms=rag_budget_ms,
        )
        rag_lane["pending"] = True
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        rag_lane.update(
            {
                "totalLatencyBudgetMs": latency_budget_ms,
                "sideLaneMode": "post_commit_async_first_response",
                "sideLaneElapsedMs": elapsed_ms,
                "memoryOptimizer": {"enabled": False, "traceEnabled": False, "maxMs": 0},
            }
        )
        model_lane.update(
            {
                "totalLatencyBudgetMs": latency_budget_ms,
                "elapsedBeforeModelMs": 0,
                "sideLaneMode": "post_commit_async_first_response",
                "sideLaneElapsedMs": elapsed_ms,
            }
        )
        pending_lanes = _progressive_pending_lanes(rag_lane=rag_lane, model_lane=model_lane)
        return [], rag_lane, predictions, model_lane, _progressive_state(
            enabled=progressive_sidecar_updates_enabled(),
            partial=True,
            should_follow_up=bool(pending_lanes),
            pending_lanes=pending_lanes,
            first_response_budget_ms=post_commit_first_response_budget_ms(),
            retry_after_ms=progressive_follow_up_retry_ms(),
        )
    lane_token = _SIDE_LANE_SCHEDULER.begin(_side_lane_request_token(snapshot, current_input, query_basis))

    def run_rag() -> None:
        if not _SIDE_LANE_SCHEDULER.is_latest(lane_token):
            rag_result["suggestions"] = []
            rag_result["lane"] = _stale_lane_status(
                lane="rag",
                reason="superseded_before_rag",
                budget_ms=rag_budget_ms,
                token=lane_token,
            )
            return
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
        if not _SIDE_LANE_SCHEDULER.is_latest(lane_token):
            suggestions = []
            lane.update(_stale_lane_fields("superseded_after_rag", lane_token))
        lane["queryInput"] = rag_current_input
        rag_result["suggestions"] = suggestions
        rag_result["lane"] = lane

    def run_model() -> None:
        if not _SIDE_LANE_SCHEDULER.is_latest(lane_token):
            model_result["predictions"] = []
            model_result["lane"] = _stale_lane_status(
                lane="model",
                reason="superseded_before_model",
                budget_ms=model_budget_ms,
                token=lane_token,
                request_type=request_type,
                rime_candidate_count=rime_candidate_count,
                requested_max_candidates=model_candidate_limit,
            )
            return
        if post_commit_async:
            predictions, lane = run_post_commit_completion_async(
                core=core,
                predictor=predictor,
                snapshot=snapshot,
                explicit_recent_context=explicit_recent_context,
                project=project,
                max_candidates=model_candidate_limit,
            )
            model_result["predictions"] = predictions
            model_result["lane"] = lane
            return
        if not _is_post_commit_prediction_snapshot(snapshot) and not composing_model_enabled():
            model_result["predictions"] = []
            model_result["lane"] = _model_lane_status(
                called=False,
                timed_out=False,
                skipped_reason="model lane disabled before post-commit",
                budget_ms=model_budget_ms,
                request_type=request_type,
                rime_candidate_count=rime_candidate_count,
                requested_max_candidates=model_candidate_limit,
            )
            return
        if request_type == PREDICTION_REQUEST_PINYIN_CONSTRAINED and not pinyin_constrained_model_enabled():
            model_result["predictions"] = []
            model_result["lane"] = _model_lane_status(
                called=False,
                timed_out=False,
                skipped_reason="pinyin constrained model disabled",
                budget_ms=model_budget_ms,
                request_type=request_type,
                rime_candidate_count=rime_candidate_count,
                requested_max_candidates=model_candidate_limit,
            )
            return
        if _is_post_commit_prediction_snapshot(snapshot):
            if _looks_like_deepseek_provider(predictor) or deepseek_completion_provider is not None:
                try:
                    assert_deepseek_scene_allowed("post_commit")
                except RuntimeError as exc:
                    model_result["predictions"] = []
                    model_result["lane"] = _model_lane_status(
                        called=False,
                        timed_out=False,
                        skipped_reason=str(exc),
                        budget_ms=model_budget_ms,
                        request_type=request_type,
                        rime_candidate_count=rime_candidate_count,
                        requested_max_candidates=model_candidate_limit,
                    )
                    return
        else:
            try:
                assert_deepseek_not_called(
                    "passive_per_key",
                    provider_name=_predictor_provider_name(predictor),
                    model=_predictor_model_name(predictor),
                )
            except RuntimeError as exc:
                model_result["predictions"] = []
                model_result["lane"] = _model_lane_status(
                    called=False,
                    timed_out=False,
                    skipped_reason=str(exc),
                    budget_ms=model_budget_ms,
                    request_type=request_type,
                    rime_candidate_count=rime_candidate_count,
                    requested_max_candidates=model_candidate_limit,
                )
                return
        predictions, lane = predict_model_with_latency_budget(
            core=core,
            predictor=predictor,
            deepseek_completion_provider=deepseek_completion_provider,
            snapshot=snapshot,
            current_input=model_current_input,
            explicit_recent_context=explicit_recent_context,
            project=project,
            max_candidates=model_candidate_limit,
            latency_budget_ms=model_budget_ms,
        )
        if not _SIDE_LANE_SCHEDULER.is_latest(lane_token):
            predictions = []
            lane.update(_stale_lane_fields("superseded_after_model", lane_token))
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
    first_response_budget_ms = (
        post_commit_first_response_budget_ms()
        if post_commit_async
        else progressive_first_response_budget_ms(latency_budget_ms)
    )
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
                semantic_query=current_input,
                query_basis=query_basis,
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
    post_commit_prediction = _is_post_commit_prediction_snapshot(snapshot)
    if not isinstance(rag_lane, dict):
        rag_lane = _rag_lane_status(
            called=True,
            timed_out=not ((progressive_partial or post_commit_prediction) and rag_pending),
            skipped_reason="RAG lane pending after progressive first response"
            if progressive_partial and rag_pending
            else "RAG dispatch exceeded latency budget",
            budget_ms=rag_budget_ms,
        )
        if (progressive_partial or post_commit_prediction) and rag_pending:
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
        predictions = []
        model_lane = _model_lane_status(
            called=True,
            timed_out=not ((progressive_partial or post_commit_prediction) and model_pending),
            skipped_reason="model lane pending after progressive first response"
            if progressive_partial and model_pending
            else "model dispatch exceeded latency budget",
            budget_ms=model_budget_ms,
            request_type=request_type,
            rime_candidate_count=rime_candidate_count,
            requested_max_candidates=model_candidate_limit,
        )
        if (progressive_partial or post_commit_prediction) and model_pending:
            model_lane["pending"] = True

    if isinstance(model_lane, dict):
        model_lane["requestedMaxCandidates"] = model_candidate_limit
    pending_lanes = _progressive_pending_lanes(rag_lane=rag_lane, model_lane=model_lane)
    should_follow_up = bool(pending_lanes)
    progressive_state = _progressive_state(
        enabled=progressive_enabled,
        partial=progressive_partial,
        should_follow_up=should_follow_up,
        pending_lanes=pending_lanes,
        first_response_budget_ms=first_response_budget_ms,
        retry_after_ms=progressive_follow_up_retry_ms(),
    )
    return suggestions, rag_lane, predictions, model_lane, progressive_state


def run_post_commit_completion_async(
    *,
    core: CoreClient,
    predictor: PredictionProvider,
    snapshot: RimeContextSnapshot,
    explicit_recent_context: str,
    project: str,
    max_candidates: int,
) -> tuple[list[ModelPrediction], dict[str, object]]:
    key = build_post_commit_completion_key(snapshot=snapshot, project=project)
    predictions, lane = _POST_COMMIT_COMPLETION_CACHE.poll_or_start(
        key=key,
        snapshot=snapshot,
        core=core,
        predictor=predictor,
        project=project,
        explicit_recent_context=explicit_recent_context,
        max_candidates=max_candidates,
        ttl_ms=post_commit_completion_ttl_ms(),
        hard_timeout_ms=post_commit_model_hard_timeout_ms(),
    )
    return predictions, lane


def build_post_commit_completion_key(*, snapshot: RimeContextSnapshot, project: str) -> PostCommitCompletionKey:
    transaction = snapshot.frontend_transaction
    context_text = compact_whitespace(snapshot.committed_context)
    commit_preview = compact_whitespace(snapshot.commit_text_preview)
    app = transaction.front_app_bundle_id or snapshot.app
    committed_hash = transaction.committed_context_hash or stable_text_hash(context_text)
    return PostCommitCompletionKey(
        project=project,
        app=app,
        hard_context_anchor=committed_hash,
        context_fingerprint=_context_fingerprint(context_text),
        commit_text_hash=stable_text_hash(commit_preview),
        commit_text_length=len(commit_preview),
        input_source_id=transaction.input_source_id,
        selection_epoch=transaction.selection_epoch,
        request_type=PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
    )


def _rag_lane_budget_for_request(latency_budget_ms: int) -> int:
    budget = max(0, int(latency_budget_ms))
    return budget


def _model_lane_budget_for_request(latency_budget_ms: int, *, snapshot: RimeContextSnapshot) -> int:
    budget = max(0, int(latency_budget_ms))
    if not _is_post_commit_prediction_snapshot(snapshot):
        return budget
    configured = _bounded_int(
        os.environ.get("RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"),
        default=900,
        minimum=300,
        maximum=12000,
    )
    return max(budget, configured)


def prediction_status_rows_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_PREDICTION_STATUS_ROW", "1")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def _prediction_status_row_for_response(
    *,
    progressive_state: Mapping[str, object],
    rag_lane: Mapping[str, object],
    model_lane: Mapping[str, object],
    generation: int,
    input_mode: str = "",
) -> SideCandidateDisplayItem | None:
    if not prediction_status_rows_enabled():
        return None
    if input_mode != InputMode.POST_COMMIT_PREDICTING.value:
        return None
    pending_lanes = progressive_state.get("pendingLanes")
    pending = {compact_whitespace(str(item)).lower() for item in pending_lanes} if isinstance(pending_lanes, list) else set()
    rag_pending = "rag" in pending or bool(rag_lane.get("pending"))
    model_pending = "model" in pending or bool(model_lane.get("pending"))
    rag_state = lane_status_state(rag_lane, count_key="suggestionCount", pending=rag_pending)
    model_state = lane_status_state(model_lane, count_key="predictionCount", pending=model_pending)
    waiting_ms = max(
        _optional_int(rag_lane.get("sideLaneElapsedMs")) or _optional_int(rag_lane.get("elapsedMs")) or 0,
        _optional_int(model_lane.get("sideLaneElapsedMs")) or _optional_int(model_lane.get("elapsedMs")) or 0,
        _bounded_int(progressive_state.get("firstResponseBudgetMs"), default=0, minimum=0, maximum=10000),
    )
    return prediction_status_row(
        rag_pending=rag_pending,
        model_pending=model_pending,
        waiting_ms=waiting_ms,
        latest_generation=generation,
        rag_state=rag_state,
        model_state=model_state,
        trigger="rime_candidate_commit",
    )


def lane_status_payload(
    *,
    rag_lane: Mapping[str, object],
    model_lane: Mapping[str, object],
    rime_candidate_count: int,
) -> dict[str, object]:
    return {
        "rag": {
            "state": lane_status_state(rag_lane, count_key="suggestionCount"),
            "elapsedMs": lane_elapsed_ms(rag_lane),
            "candidateCount": _bounded_int(rag_lane.get("suggestionCount"), default=0, minimum=0, maximum=999),
            "dropReason": _string(rag_lane.get("dropReason") or rag_lane.get("staleReason") or rag_lane.get("skippedReason")),
        },
        "model": {
            "state": lane_status_state(model_lane, count_key="predictionCount"),
            "elapsedMs": lane_elapsed_ms(model_lane),
            "candidateCount": _bounded_int(model_lane.get("predictionCount"), default=0, minimum=0, maximum=999),
            "dropReason": _string(
                model_lane.get("dropReason") or model_lane.get("staleReason") or model_lane.get("skippedReason")
            ),
        },
        "rime": {
            "state": "ready" if rime_candidate_count > 0 else "empty",
            "candidateCount": max(0, int(rime_candidate_count)),
        },
    }


def lane_status_state(lane: Mapping[str, object], *, count_key: str, pending: bool | None = None) -> str:
    if pending is True or bool(lane.get("pending")):
        return "pending"
    if bool(lane.get("stale")) or bool(lane.get("droppedStale")) or _string(lane.get("dropReason")):
        return "stale_dropped"
    if bool(lane.get("timedOut")):
        return "timeout"
    if bool(lane.get("error")):
        return "error"
    count = _bounded_int(lane.get(count_key), default=0, minimum=0, maximum=999)
    if count > 0:
        return "ready"
    if bool(lane.get("called")):
        return "empty"
    return "idle"


def lane_elapsed_ms(lane: Mapping[str, object]) -> int:
    return max(
        0,
        _optional_int(lane.get("sideLaneElapsedMs"))
        or _optional_int(lane.get("elapsedMs"))
        or _optional_int(lane.get("latencyMs"))
        or 0,
    )


def _side_lane_request_token(snapshot: RimeContextSnapshot, semantic_query: str, query_basis: str) -> LaneRequestToken:
    anchors = build_prediction_anchors_from_snapshot(
        snapshot=snapshot,
        mode=infer_input_mode(snapshot).value,
        semantic_query=semantic_query,
        query_basis=query_basis,
        stable_short_pinyin_prefix=stable_short_pinyin_prefix(snapshot),
    )
    transaction = snapshot.frontend_transaction
    return LaneRequestToken(
        session_id=snapshot.session_id,
        panel_session_id=transaction.panel_session_id,
        frontend_revision=transaction.frontend_revision,
        input_generation=snapshot.request_seq,
        apply_anchor=anchors.apply_anchor,
        query_anchor=anchors.query_anchor,
        created_at_ms=now_ms(),
    )


def _stale_lane_fields(reason: str, token: LaneRequestToken) -> dict[str, object]:
    return {
        "staleDropped": True,
        "staleDropReason": reason,
        "waitingForLatest": True,
        "activeGeneration": token.input_generation,
        "applyAnchor": token.apply_anchor,
        "queryAnchor": token.query_anchor,
    }


def _stale_lane_status(
    *,
    lane: str,
    reason: str,
    budget_ms: int,
    token: LaneRequestToken,
    request_type: str = "",
    rime_candidate_count: int = 0,
    requested_max_candidates: int = 0,
) -> dict[str, object]:
    if lane == "model":
        status = _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason=reason,
            budget_ms=budget_ms,
            request_type=request_type,
            rime_candidate_count=rime_candidate_count,
            requested_max_candidates=requested_max_candidates,
        )
    else:
        status = _rag_lane_status(
            called=False,
            timed_out=False,
            skipped_reason=reason,
            budget_ms=budget_ms,
        )
    status.update(_stale_lane_fields(reason, token))
    return status


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
    return min(configured, max(80, budget - 80))


def post_commit_first_response_budget_ms(env: Mapping[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    configured = _bounded_int(
        source.get("RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS"),
        default=_POST_COMMIT_FIRST_RESPONSE_MS,
        minimum=80,
        maximum=1000,
    )
    return configured


def post_commit_completion_ttl_ms(env: Mapping[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    return _bounded_int(
        source.get("RAG_IME_POST_COMMIT_COMPLETION_TTL_MS"),
        default=_POST_COMMIT_COMPLETION_TTL_MS,
        minimum=1000,
        maximum=60000,
    )


def post_commit_model_hard_timeout_ms(env: Mapping[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    return _bounded_int(
        source.get("RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS"),
        default=_POST_COMMIT_MODEL_HARD_TIMEOUT_MS,
        minimum=500,
        maximum=60000,
    )


def post_commit_async_completion_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION", "1")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def post_commit_presentation_stream_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_POST_COMMIT_PRESENTATION_STREAM", "1")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def composing_model_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_ENABLE_COMPOSING_MODEL", "0")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def pinyin_constrained_model_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL", "0")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def progressive_follow_up_retry_ms(env: Mapping[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    return _bounded_int(
        source.get("RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS"),
        default=_PROGRESSIVE_FOLLOW_UP_RETRY_MS,
        minimum=80,
        maximum=1500,
    )


def candidate_source_badges_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_CANDIDATE_SOURCE_BADGES", "1")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def candidate_source_colors_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_CANDIDATE_SOURCE_COLORS", "1")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def candidate_diagnostics_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get("RAG_IME_CANDIDATE_DIAGNOSTICS", "0")).strip().lower()
    return value not in _FALSEY_ENV_VALUES


def candidate_source_badge(source_type: str, env: Mapping[str, str] | None = None) -> str:
    if not candidate_source_badges_enabled(env):
        return ""
    return source_badge_for(source_type)


def candidate_color_token(source_type: str, env: Mapping[str, str] | None = None) -> str:
    if not candidate_source_colors_enabled(env):
        return ""
    return source_color_token_for(source_type)


def _strip_candidate_source_suffix(text: str) -> str:
    value = _string(text).strip()
    for suffix in _CANDIDATE_SOURCE_SUFFIXES:
        if not value.endswith(suffix):
            continue
        stripped = value[: -len(suffix)].strip()
        if stripped:
            return stripped
    return value


def _has_progressive_visible_lane_result(
    *,
    rag_result: Mapping[str, object],
    model_result: Mapping[str, object],
    snapshot: RimeContextSnapshot,
    semantic_query: str = "",
    query_basis: str = "",
) -> bool:
    if _is_post_commit_prediction_snapshot(snapshot):
        return True
    suggestions = rag_result.get("suggestions")
    if isinstance(suggestions, list) and suggestions:
        visible_suggestions = _filter_rag_suggestions_for_query(
            suggestions,
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
            prediction_context="",
        )
        if visible_suggestions:
            return True
    predictions = model_result.get("predictions")
    if isinstance(predictions, list) and predictions:
        return True
    if snapshot.force_side_candidates:
        return False
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
            or "model dispatch exceeded latency budget" in model_reason
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


def _model_lane_lease_ttl_ms() -> int:
    return _bounded_int(
        os.environ.get("RAG_IME_MODEL_LANE_LEASE_TTL_MS"),
        default=_MODEL_LANE_LEASE_TTL_MS,
        minimum=250,
        maximum=30000,
    )


def _try_acquire_model_lane() -> str | None:
    global _MODEL_LANE_ACTIVE_STARTED_AT, _MODEL_LANE_ACTIVE_TOKEN
    now = time.monotonic()
    with _MODEL_LANE_LOCK:
        active_token = _MODEL_LANE_ACTIVE_TOKEN
        if active_token is not None:
            age_ms = int((now - _MODEL_LANE_ACTIVE_STARTED_AT) * 1000)
            if age_ms < _model_lane_lease_ttl_ms():
                return None
        token = f"{now:.9f}:{id(object())}"
        _MODEL_LANE_ACTIVE_TOKEN = token
        _MODEL_LANE_ACTIVE_STARTED_AT = now
        return token


def _release_model_lane(token: str) -> None:
    global _MODEL_LANE_ACTIVE_STARTED_AT, _MODEL_LANE_ACTIVE_TOKEN
    with _MODEL_LANE_LOCK:
        if _MODEL_LANE_ACTIVE_TOKEN != token:
            return
        _MODEL_LANE_ACTIVE_TOKEN = None
        _MODEL_LANE_ACTIVE_STARTED_AT = 0.0


def _model_lane_is_idle() -> bool:
    global _MODEL_LANE_ACTIVE_STARTED_AT, _MODEL_LANE_ACTIVE_TOKEN
    with _MODEL_LANE_LOCK:
        if _MODEL_LANE_ACTIVE_TOKEN is None:
            return True
        age_ms = int((time.monotonic() - _MODEL_LANE_ACTIVE_STARTED_AT) * 1000)
        if age_ms < _model_lane_lease_ttl_ms():
            return False
        _MODEL_LANE_ACTIVE_TOKEN = None
        _MODEL_LANE_ACTIVE_STARTED_AT = 0.0
        return True


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
                    "debugOnly": True,
                    "governanceLayer": "recent_context",
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
        realtime_decision = decide_realtime_memory_candidate(
            suggestion,
            context=RealtimeMemoryContext(
                committed_context=snapshot.committed_context,
                commit_preview=snapshot.commit_text_preview,
                semantic_query=semantic_query,
                query_basis=query_basis,
            ),
        )
        if not realtime_decision.allowed:
            continue
        suggestion = annotate_realtime_memory_candidate(suggestion, decision=realtime_decision)
        metadata = dict(suggestion.metadata)
        durable_memory = _suggestion_has_durable_memory_signal(metadata)
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
        if not durable_memory and _looks_like_low_quality_memory_candidate(surface):
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
    if _metadata_memory_kind(metadata) in {"stable_memory", "phrase", "memory_alias"}:
        return True
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
    if _metadata_memory_kind(metadata) in {"stable_memory", "phrase", "memory_alias"}:
        return False
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
    if _metadata_memory_kind(metadata) in {"stable_memory", "phrase", "memory_alias"}:
        return True
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


def _metadata_memory_kind(metadata: Mapping[str, object]) -> str:
    state = metadata.get("state") if isinstance(metadata.get("state"), dict) else {}
    assert isinstance(state, dict)
    return compact_whitespace(str(metadata.get("memory_kind") or state.get("memory_kind") or "")).lower()


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
        if _post_commit_model_prediction_echoes_context(
            suggestion.surface_text,
            snapshot.committed_context,
        ) or _post_commit_model_prediction_echoes_context(
            suggestion.surface_text,
            snapshot.commit_text_preview,
        ):
            continue
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
    return filter_post_commit_model_completions(
        predictions,
        snapshot=snapshot,
        existing_texts=(),
        max_candidates=len(predictions),
    )


def _post_commit_empty_result_fallback_predictions(
    *,
    snapshot: RimeContextSnapshot,
    semantic_query: str,
    model_predictions: list[ModelPrediction],
    suggestions: list[InputSuggestion],
    rag_lane: Mapping[str, object],
    model_lane: Mapping[str, object],
    progressive_state: Mapping[str, object],
) -> list[ModelPrediction]:
    if model_predictions or suggestions:
        return []
    if not _is_post_commit_prediction_snapshot(snapshot):
        return []
    if not snapshot.progressive_follow_up:
        return []
    pending_lanes = progressive_state.get("pendingLanes")
    if isinstance(pending_lanes, list) and pending_lanes:
        return []
    if bool(rag_lane.get("pending")) or bool(model_lane.get("pending")) or bool(model_lane.get("inFlight")):
        return []
    text = _post_commit_empty_result_fallback_text(snapshot=snapshot, semantic_query=semantic_query)
    if not text:
        return []
    return [
        ModelPrediction(
            text=text,
            rank=1,
            provider_name="demo-safe-fallback",
            latency_ms=int(model_lane.get("elapsedMs") or 0),
            confidence=0.35,
            metadata={
                "requestType": PREDICTION_REQUEST_POST_COMMIT_COMPLETION,
                "noPinyinFilter": True,
                "fallbackReason": "demo_safe_empty_post_commit_fallback",
                "fallbackSource": "post_commit_empty_result",
                "queryHash": stable_text_hash(semantic_query),
            },
        )
    ]


def _post_commit_empty_result_fallback_text(*, snapshot: RimeContextSnapshot, semantic_query: str) -> str:
    context = compact_whitespace(
        " ".join(
            item
            for item in (snapshot.committed_context, semantic_query, snapshot.commit_text_preview)
            if compact_whitespace(item)
        )
    )
    if not context:
        return ""
    if "需求" in context and ("完成" in context or "没" in context or "没有" in context):
        return "继续补齐需求"
    if "为什么" in context:
        return "为什么会这样"
    if "测试" in context:
        return "继续测试一下"
    if "输入法" in context:
        return "继续调试输入法"
    if "RAG" in context or "rag" in context:
        return "继续完善 RAG"
    if "LLM" in context or "llm" in context or "模型" in context:
        return "继续检查模型输出"
    return "继续完善一下"


def _stage_post_commit_fallback_presentation_stream(
    *,
    snapshot: RimeContextSnapshot,
    predictions: list[ModelPrediction],
) -> tuple[list[ModelPrediction], dict[str, object]]:
    if not predictions or not post_commit_presentation_stream_enabled():
        return predictions, {}
    first = predictions[0]
    steps = _post_commit_presentation_stream_steps(first.text)
    if len(steps) <= 1:
        return predictions, {
            "presentationStreaming": False,
            "presentationStage": len(steps),
            "presentationStageCount": len(steps),
        }
    key = _post_commit_fallback_presentation_stream_key(snapshot=snapshot, final_text=first.text)
    now = time.time()
    with _POST_COMMIT_PRESENTATION_STREAM_LOCK:
        _drop_expired_post_commit_presentation_stream_keys(now)
        previous_stage = _POST_COMMIT_PRESENTATION_STREAM_STAGES.get(key, (0, now))[0]
        stage = min(previous_stage + 1, len(steps))
        _POST_COMMIT_PRESENTATION_STREAM_STAGES[key] = (stage, now)
    pending = stage < len(steps)
    metadata = dict(first.metadata)
    metadata.update(
        {
            "presentationStreaming": True,
            "presentationStage": stage,
            "presentationStageCount": len(steps),
            "presentationPartial": pending,
            "presentationFinalTextHash": stable_text_hash(first.text),
        }
    )
    staged_first = replace(first, text=steps[stage - 1], metadata=metadata)
    staged_predictions = [staged_first] if pending else [staged_first, *predictions[1:]]
    return staged_predictions, {
        "completionJobState": "streaming" if pending else "completed",
        "pending": pending,
        "inFlight": pending,
        "presentationStreaming": True,
        "presentationStage": stage,
        "presentationStageCount": len(steps),
    }


def _post_commit_fallback_presentation_stream_key(*, snapshot: RimeContextSnapshot, final_text: str) -> str:
    transaction = snapshot.frontend_transaction
    material = "\x1f".join(
        (
            snapshot.session_id,
            compact_whitespace(snapshot.committed_context),
            compact_whitespace(snapshot.commit_text_preview),
            transaction.front_app_bundle_id or snapshot.app,
            transaction.input_source_id,
            str(transaction.selection_epoch),
            stable_text_hash(final_text),
        )
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _drop_expired_post_commit_presentation_stream_keys(now: float) -> None:
    expired = [
        key
        for key, (_, updated_at) in _POST_COMMIT_PRESENTATION_STREAM_STAGES.items()
        if now - updated_at > 60
    ]
    for key in expired:
        _POST_COMMIT_PRESENTATION_STREAM_STAGES.pop(key, None)


def filter_post_commit_model_completions(
    predictions: list[ModelPrediction],
    *,
    snapshot: RimeContextSnapshot,
    existing_texts: tuple[str, ...] = (),
    max_candidates: int = 5,
) -> list[ModelPrediction]:
    committed = compact_whitespace(snapshot.committed_context)
    commit_preview = compact_whitespace(snapshot.commit_text_preview)
    duplicate_surfaces = {
        compact_whitespace(item).lower()
        for item in (committed, commit_preview, *existing_texts)
        if compact_whitespace(item)
    }
    result: list[ModelPrediction] = []
    seen: set[str] = set()
    for prediction in predictions:
        text = _clean_post_commit_completion_text(prediction.text)
        normalized = compact_whitespace(text).lower()
        if not normalized or normalized in seen or normalized in duplicate_surfaces:
            continue
        if _post_commit_model_prediction_echoes_context(text, committed) or _post_commit_model_prediction_echoes_context(
            text, commit_preview
        ):
            continue
        if (
            quality_reject_prompt_leak(text)
            or _looks_like_model_prompt_echo(text)
            or _looks_like_complaint_or_debug_fragment(text)
            or _looks_like_truncated_post_commit_completion(text)
        ):
            continue
        if _looks_like_meta_candidate_surface(text):
            continue
        seen.add(normalized)
        metadata = dict(prediction.metadata)
        metadata["noPinyinFilter"] = True
        metadata["requestType"] = PREDICTION_REQUEST_POST_COMMIT_COMPLETION
        result.append(
            ModelPrediction(
                text=text,
                rank=len(result) + 1,
                provider_name=prediction.provider_name,
                latency_ms=prediction.latency_ms,
                confidence=prediction.confidence,
                metadata=metadata,
            )
        )
        if len(result) >= max(0, int(max_candidates)):
            break
    return result


def _clean_post_commit_completion_text(text: str) -> str:
    surface = compact_whitespace(text)
    surface = re.sub(r"^\s*(?:[-*]|\d+[.)、]|[一二三四五六七八九十]+[.)、])\s*", "", surface)
    surface = re.sub(r"^[\"'“”‘’\[\]【】]+|[\"'“”‘’\[\]【】]+$", "", surface)
    surface = re.sub(r"^[,，。！？；;、\s]+|[,，。！？；;、\s]+$", "", surface)
    if len(surface) > 80:
        surface = surface[:80].rstrip("，。！？；;、 ")
    return compact_whitespace(surface)


def _looks_like_truncated_post_commit_completion(text: str) -> bool:
    surface = compact_whitespace(text)
    if not surface:
        return True
    if surface in {"您", "你", "我", "已", "您已", "你已", "我已", "您已经", "你已经", "我已经"}:
        return True
    return bool(re.fullmatch(r"(?:您已|你已|我已|已){2,}", surface))


def _is_post_commit_prediction_snapshot(snapshot: RimeContextSnapshot) -> bool:
    if compact_whitespace(snapshot.raw_input) or compact_whitespace(snapshot.preedit):
        return False
    if snapshot.candidates:
        return False
    return bool(compact_whitespace(snapshot.committed_context) or compact_whitespace(snapshot.commit_text_preview))


def _post_commit_model_prediction_echoes_context(candidate: str, committed_context: str) -> bool:
    return quality_reject_context_echo(candidate, committed_context, "")


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
    deepseek_completion_provider: Any | None = None,
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
    if not _is_post_commit_prediction_snapshot(snapshot) and not composing_model_enabled():
        return [], _model_lane_status(
            called=False,
            timed_out=False,
            skipped_reason="model lane disabled before post-commit",
            budget_ms=budget_ms,
            request_type=request_type,
            rime_candidate_count=len(rime_candidate_texts),
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
    if _is_post_commit_prediction_snapshot(snapshot):
        holdover_predictions = _get_model_holdover_predictions(
            project=project,
            current_input=current_input,
            explicit_recent_context=explicit_recent_context,
            max_candidates=max_candidates,
        )
        if holdover_predictions:
            return holdover_predictions, _model_lane_status(
                called=False,
                timed_out=False,
                skipped_reason="holdover prediction cache hit",
                budget_ms=budget_ms,
                elapsed_ms=0,
                prediction_count=len(holdover_predictions),
                holdover_hit=True,
                request_type=request_type,
                rime_candidate_count=len(rime_candidate_texts),
            )
    lane_token = _try_acquire_model_lane()
    if lane_token is None:
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
            if deepseek_completion_provider is not None:
                deepseek_predictions, deepseek_lane = _predict_deepseek_post_commit_candidates(
                    provider=deepseek_completion_provider,
                    snapshot=snapshot,
                    current_context=recent_context,
                    existing_predictions=predictions,
                    max_candidates=max_candidates,
                    started=started,
                    budget_ms=budget_ms,
                    rime_candidates=rime_candidate_texts,
                )
                result["deepseekLane"] = deepseek_lane
                predictions = [*predictions, *deepseek_predictions]
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
            _release_model_lane(lane_token)

    Thread(target=run_prediction, name="rag-ime-model-lane", daemon=True).start()
    if not done.wait(timeout=budget_ms / 1000):
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
    lane = _model_lane_status(
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
    deepseek_lane = result.get("deepseekLane")
    if isinstance(deepseek_lane, dict):
        lane.update(deepseek_lane)
    return predictions, lane


def _predict_deepseek_post_commit_candidates(
    *,
    provider: Any,
    snapshot: RimeContextSnapshot,
    current_context: str,
    existing_predictions: list[ModelPrediction],
    max_candidates: int,
    started: float,
    budget_ms: int,
    rime_candidates: tuple[str, ...],
) -> tuple[list[ModelPrediction], dict[str, object]]:
    if not _is_post_commit_prediction_snapshot(snapshot):
        return [], {
            "deepseekCalled": False,
            "deepseekPredictionCount": 0,
            "deepseekSkippedReason": "not post_commit",
        }
    try:
        assert_deepseek_scene_allowed("post_commit")
    except RuntimeError as exc:
        return [], {
            "deepseekCalled": False,
            "deepseekPredictionCount": 0,
            "deepseekSkippedReason": str(exc),
        }
    remaining = max(0, int(max_candidates) - len(existing_predictions))
    if remaining <= 0:
        return [], {
            "deepseekCalled": False,
            "deepseekPredictionCount": 0,
            "deepseekSkippedReason": "no side candidate slot",
        }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    remaining_budget_ms = max(1, int(budget_ms) - elapsed_ms)
    request = DeepSeekCompletionRequest(
        scene="post_commit",
        current_context=current_context,
        evidence_pack=_deepseek_post_commit_evidence_pack(
            snapshot=snapshot,
            current_context=current_context,
            rime_candidates=rime_candidates,
        ),
        max_candidates=remaining,
        latency_budget_ms=remaining_budget_ms,
    )
    predictions: list[ModelPrediction] = []
    seen = {compact_whitespace(item.text).lower() for item in existing_predictions}
    try:
        for delta in provider.stream_candidates(request):
            text = compact_whitespace(str(getattr(delta, "text", "")))
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            predictions.append(
                ModelPrediction(
                    text=text,
                    rank=len(existing_predictions) + len(predictions) + 1,
                    provider_name="deepseek-v4-flash",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    confidence=0.72,
                    metadata={
                        "source_lane": "deepseek_v4_flash",
                        "scene": "post_commit",
                        "append_only": True,
                        **dict(getattr(delta, "metadata", {}) or {}),
                    },
                )
            )
            if len(predictions) >= remaining:
                break
            if int((time.perf_counter() - started) * 1000) >= budget_ms:
                break
    except Exception as exc:  # pragma: no cover - defensive fail-open guard
        return [], {
            "deepseekCalled": True,
            "deepseekPredictionCount": 0,
            "deepseekSkippedReason": f"error: {exc.__class__.__name__}",
        }
    return predictions, {
        "deepseekCalled": True,
        "deepseekPredictionCount": len(predictions),
        "deepseekSkippedReason": "" if predictions else "empty",
        "deepseekAppendOnly": True,
        "deepseekLatencyBudgetMs": remaining_budget_ms,
    }


def _deepseek_post_commit_evidence_pack(
    *,
    snapshot: RimeContextSnapshot,
    current_context: str,
    rime_candidates: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    hints = [item for item in rime_candidates[:5] if compact_whitespace(item)]
    return (
        {
            "sourceType": "post_commit_context",
            "evidencePreview": compact_whitespace(current_context)[-240:],
            "surfaceHints": hints,
            "tags": ["post_commit", "input_method"],
            "metadata": {
                "requestSeq": snapshot.request_seq,
                "frontendRevision": snapshot.frontend_transaction.frontend_revision,
                "selectionEpoch": snapshot.frontend_transaction.selection_epoch,
            },
        },
    )


def _filter_model_predictions(
    predictions: list[ModelPrediction],
    *,
    current_input: str,
    explicit_recent_context: str,
    prediction_context: str = "",
    pinyin_prefix: str = "",
) -> list[ModelPrediction]:
    _ = current_input, explicit_recent_context, prediction_context
    cleaned: list[ModelPrediction] = []
    seen: set[str] = set()
    for prediction in predictions:
        text = compact_whitespace(prediction.text)
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
    fail_closed: bool = False,
    warnings: tuple[str, ...] = (),
) -> dict[str, object]:
    payload: dict[str, object] = {
        "called": called,
        "timedOut": timed_out,
        "skippedReason": skipped_reason,
        "suggestionCount": suggestion_count,
        "latencyBudgetMs": budget_ms,
        "elapsedMs": elapsed_ms,
    }
    if fail_closed:
        payload["failClosed"] = True
    if warnings:
        payload["warnings"] = list(warnings)
    return payload


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
    global _MODEL_LANE_ACTIVE_STARTED_AT, _MODEL_LANE_ACTIVE_TOKEN
    with _MODEL_HOLDOVER_LOCK:
        _MODEL_HOLDOVERS.clear()
    _POST_COMMIT_COMPLETION_CACHE.clear()
    with _POST_COMMIT_PRESENTATION_STREAM_LOCK:
        _POST_COMMIT_PRESENTATION_STREAM_STAGES.clear()
    with _MODEL_LANE_LOCK:
        _MODEL_LANE_ACTIVE_TOKEN = None
        _MODEL_LANE_ACTIVE_STARTED_AT = 0.0


def clear_prediction_manager_cache() -> None:
    with _PREDICTION_MANAGER_LOCK:
        _PREDICTION_MANAGERS.clear()
    clear_refresh_debounce_cache()


def clear_refresh_debounce_cache() -> None:
    with _REFRESH_DEBOUNCE_LOCK:
        _REFRESH_DEBOUNCE.clear()


def wait_for_model_prediction_lane_idle(timeout_s: float = 1.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() <= deadline:
        if _model_lane_is_idle():
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
        shown_candidates = _shown_candidate_payloads(payload)
        shown_candidate_ids = [
            _string(item.get("memoryId") or item.get("memory_id") or item.get("suggestionId") or item.get("suggestion_id"))
            for item in shown_candidates
        ]
        feedback_base = _selection_feedback_base_event(
            payload=payload,
            candidate=candidate,
            project=project,
            query=query,
            recent_context=recent_context,
            shown_candidate_ids=shown_candidate_ids,
        )
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
        _record_memory_feedback_event(
            core=core,
            event={
                **feedback_base,
                "event": "accepted",
                "candidateId": _string(candidate.get("memoryId") or candidate.get("memory_id")) or event_id,
                "candidateText": _string(candidate.get("text")) or insert_text,
                "sourceType": source_type,
                "rank": candidate_rank or 0,
                "selectedCandidateId": _string(candidate.get("memoryId") or candidate.get("memory_id")) or event_id,
                "selectedText": _string(candidate.get("text")) or insert_text,
                "selectedRank": candidate_rank or 0,
                "sourceEventId": _optional_int(candidate.get("sourceEventId") or candidate.get("source_event_id")) or _event_id_from_memory_id(event_id),
                "suggestionId": _string(candidate.get("suggestionId") or candidate.get("suggestion_id")),
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
            for shown_candidate in shown_candidates:
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
                _record_memory_feedback_event(
                    core=core,
                    event={
                        **feedback_base,
                        "event": "skipped",
                        "candidateId": _string(shown_candidate.get("memoryId") or shown_candidate.get("memory_id")),
                        "candidateText": _string(shown_candidate.get("text")),
                        "sourceType": _string(shown_candidate.get("sourceType") or shown_candidate.get("source_type")),
                        "rank": shown_rank,
                        "selectedCandidateId": _string(candidate.get("memoryId") or candidate.get("memory_id")) or event_id,
                        "selectedText": _string(candidate.get("text")) or insert_text,
                        "selectedRank": candidate_rank,
                        "sourceEventId": _optional_int(shown_candidate.get("sourceEventId") or shown_candidate.get("source_event_id")),
                        "suggestionId": _string(shown_candidate.get("suggestionId") or shown_candidate.get("suggestion_id")),
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
    raw_input = _string(payload.get("rawInput") or payload.get("currentInput"))
    preedit = _string(payload.get("preedit"))
    committed_context = _string(payload.get("committedContext") or payload.get("recentContext"))
    return RimeContextSnapshot(
        session_id=_string(payload.get("sessionId")) or "default",
        request_seq=_bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1),
        raw_input=raw_input,
        preedit=preedit,
        commit_text_preview=_string(payload.get("commitTextPreview") or rime_context.get("commitTextPreview")),
        committed_context=committed_context,
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
        frontend_transaction=_frontend_transaction_from_payload(
            payload=payload,
            rime_context=rime_context,
            raw_input=raw_input,
            preedit=preedit,
            committed_context=committed_context,
        ),
    )


def _frontend_transaction_from_payload(
    *,
    payload: Mapping[str, object],
    rime_context: Mapping[str, object],
    raw_input: str,
    preedit: str,
    committed_context: str,
) -> FrontendTransaction:
    frontend_revision = _bounded_int(
        _first_present(dict(payload), dict(rime_context), "frontendRevision"),
        default=_bounded_int(payload.get("inputGeneration"), default=0, minimum=0, maximum=2**63 - 1),
        minimum=0,
        maximum=2**63 - 1,
    )
    selection_epoch = _bounded_int(
        _first_present(dict(payload), dict(rime_context), "selectionEpoch"),
        default=frontend_revision,
        minimum=0,
        maximum=2**63 - 1,
    )
    composition_text = preedit or raw_input
    composition_hash = _hash_from_payload(
        _first_present(dict(payload), dict(rime_context), "compositionHash"),
        fallback_text=composition_text,
    )
    committed_context_hash = _hash_from_payload(
        _first_present(dict(payload), dict(rime_context), "committedContextHash"),
        fallback_text=committed_context,
    )
    session_id = _string(payload.get("sessionId")) or "default"
    request_seq = _bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1)
    front_app_bundle_id = _string(
        payload.get("frontAppBundleId")
        or payload.get("frontmostAppBundleId")
        or payload.get("frontmostApp")
        or payload.get("app")
        or rime_context.get("frontAppBundleId")
        or rime_context.get("frontmostAppBundleId")
    )
    input_source_id = _string(payload.get("inputSourceId") or rime_context.get("inputSourceId"))
    panel_session_id = _string(payload.get("panelSessionId") or rime_context.get("panelSessionId"))
    if not panel_session_id:
        panel_session_id = _short_stable_id(
            session_id,
            str(request_seq),
            str(frontend_revision),
            str(selection_epoch),
            composition_hash,
            committed_context_hash,
        )
    return FrontendTransaction(
        frontend_revision=frontend_revision,
        selection_epoch=selection_epoch,
        input_generation=_bounded_int(
            _first_present(dict(payload), dict(rime_context), "inputGeneration"),
            default=frontend_revision,
            minimum=0,
            maximum=2**63 - 1,
        ),
        front_app_bundle_id=front_app_bundle_id,
        input_source_id=input_source_id,
        composition_hash=composition_hash,
        committed_context_hash=committed_context_hash,
        panel_session_id=panel_session_id,
        created_at_ms=_bounded_int(
            _first_present(dict(payload), dict(rime_context), "createdAtMs"),
            default=0,
            minimum=0,
            maximum=2**63 - 1,
        ),
    )


def _hash_from_payload(value: object, *, fallback_text: str) -> str:
    configured = _string(value)
    if configured.startswith("sha256:") and len(configured) >= len("sha256:") + 8:
        return configured
    return stable_text_hash(fallback_text)


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


def apply_refresh_debounce(
    *,
    snapshot: RimeContextSnapshot,
    trigger_decision: RimeSideCandidateTriggerDecision,
    semantic_query: str,
    query_basis: str,
    default_project: str,
) -> tuple[RimeSideCandidateTriggerDecision, dict[str, object]]:
    debounce_ms = _refresh_debounce_ms()
    if not trigger_decision.should_refresh or debounce_ms <= 0:
        return trigger_decision, {"debounced": False, "debounceMs": debounce_ms}
    if snapshot.progressive_follow_up or compact_whitespace(snapshot.commit_text_preview):
        return trigger_decision, {"debounced": False, "debounceMs": debounce_ms, "reason": "post_commit_or_followup"}
    if not compact_whitespace(snapshot.raw_input or snapshot.preedit):
        return trigger_decision, {"debounced": False, "debounceMs": debounce_ms, "reason": "no_active_composition"}

    mode = infer_input_mode(snapshot)
    anchors = build_prediction_anchors_from_snapshot(
        snapshot=snapshot,
        mode=mode.value,
        semantic_query=semantic_query,
        query_basis=query_basis,
        stable_short_pinyin_prefix=stable_short_pinyin_prefix(snapshot),
    )
    project = compact_whitespace(snapshot.project or default_project)
    app = compact_whitespace(snapshot.app)
    session_id = compact_whitespace(snapshot.session_id)
    query_family = f"{prediction_mode_family(mode.value)}:{query_basis}"
    key = (project, app, session_id, anchors.hard_context_anchor, query_family)
    monotonic_ms = int(time.monotonic() * 1000)
    semantic_hash = stable_text_hash(semantic_query)
    with _REFRESH_DEBOUNCE_LOCK:
        previous = _REFRESH_DEBOUNCE.get(key)
        if previous is not None:
            age_ms = max(0, monotonic_ms - previous.created_at_ms)
            if age_ms <= debounce_ms:
                return (
                    RimeSideCandidateTriggerDecision(False, "skip: refresh debounce coalesced"),
                    {
                        "debounced": True,
                        "debounceMs": debounce_ms,
                        "coalescedWithAgeMs": age_ms,
                        "debounceKey": _short_stable_id(*key),
                        "previousRequestSeq": previous.request_seq,
                        "previousSemanticQueryHash": previous.semantic_query_hash,
                    },
                )
        _REFRESH_DEBOUNCE[key] = _RefreshDebounceState(
            created_at_ms=monotonic_ms,
            request_seq=snapshot.request_seq,
            semantic_query_hash=semantic_hash,
        )
        if len(_REFRESH_DEBOUNCE) > 512:
            oldest_key = min(_REFRESH_DEBOUNCE, key=lambda item: _REFRESH_DEBOUNCE[item].created_at_ms)
            _REFRESH_DEBOUNCE.pop(oldest_key, None)
    return (
        trigger_decision,
        {
            "debounced": False,
            "debounceMs": debounce_ms,
            "debounceKey": _short_stable_id(*key),
        },
    )


def _refresh_debounce_ms() -> int:
    raw = os.environ.get("RAG_IME_REFRESH_DEBOUNCE_MS", str(_REFRESH_DEBOUNCE_MS))
    try:
        return max(0, min(1000, int(raw)))
    except ValueError:
        return _REFRESH_DEBOUNCE_MS


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

    signal_len = semantic_signal_length(semantic_query)
    if signal_len <= 0:
        return RimeSideCandidateTriggerDecision(False, "skip: empty semantic signal")

    if snapshot.force_side_candidates and _forced_refresh_has_side_signal(snapshot, query_basis, semantic_query):
        return RimeSideCandidateTriggerDecision(True, "force: explicit side candidate refresh")

    if raw_english_candidate_text(snapshot):
        return RimeSideCandidateTriggerDecision(False, "skip: raw ascii passthrough")

    if query_basis == "rimeCandidates" and _active_rime_candidates_are_low_information(snapshot):
        if compact_whitespace(snapshot.raw_input or snapshot.preedit):
            return RimeSideCandidateTriggerDecision(True, "refresh: active composition warmup")
        return RimeSideCandidateTriggerDecision(False, "skip: low-information Rime candidates")

    if query_basis == "committedContext" and _committed_context_is_low_information(snapshot, semantic_query):
        if snapshot.idle_ms <= _POST_COMMIT_PANEL_TTL_MS:
            return RimeSideCandidateTriggerDecision(True, "refresh: short post-commit continuation")
        return RimeSideCandidateTriggerDecision(False, "skip: low-information committed context")

    if query_basis == "rawInputFallback":
        if compact_whitespace(snapshot.raw_input or snapshot.preedit):
            return RimeSideCandidateTriggerDecision(True, "refresh: raw pinyin warmup")
        return RimeSideCandidateTriggerDecision(False, "skip: raw pinyin fallback")

    if query_basis == "rawSemanticInput":
        return RimeSideCandidateTriggerDecision(True, "refresh: semantic raw input")

    if query_basis == "commitTextPreview" and signal_len >= 2:
        return RimeSideCandidateTriggerDecision(True, "refresh: commit preview")

    if query_basis == "rimeCandidates":
        if signal_len >= 3:
            return RimeSideCandidateTriggerDecision(True, "refresh: stable Rime candidates")
        if snapshot.idle_ms >= 300 and signal_len >= 2:
            return RimeSideCandidateTriggerDecision(True, "refresh: idle short Rime candidate")
        if compact_whitespace(snapshot.raw_input or snapshot.preedit) and signal_len >= 1:
            return RimeSideCandidateTriggerDecision(True, "refresh: active composition warmup")
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


def _forced_refresh_has_side_signal(snapshot: RimeContextSnapshot, query_basis: str, semantic_query: str) -> bool:
    if query_basis == "commitTextPreview":
        return semantic_signal_length(semantic_query) >= 2
    active_input = compact_whitespace(snapshot.preedit or snapshot.raw_input)
    if not active_input:
        return False
    if query_basis == "rawInputFallback":
        return True
    if query_basis not in {"rimeCandidates", "rawSemanticInput", "preedit"}:
        return False
    pinyin_signal = re.sub(r"[^A-Za-z0-9]+", "", active_input)
    return len(pinyin_signal) >= 4


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
    """Return a stable user pinyin prefix that can constrain model/RAG lookup.

    Long raw strings are often typo-heavy pinyin fragments; those should not be
    used as semantic RAG queries. A short prefix such as "sj" and a complete
    single syllable such as "xiang" are different: they are the user's active
    constraint and should match the phrase-memory pinyin index.
    """

    prefix = compact_whitespace(snapshot.preedit or snapshot.raw_input).lower()
    if not prefix or not prefix.isascii() or not prefix.isalnum():
        return ""
    if 1 <= len(prefix) <= 4:
        return prefix
    return prefix if _looks_like_single_pinyin_syllable(prefix) else ""


_PINYIN_SYLLABLE_FINALS = (
    "iang",
    "iong",
    "uang",
    "ang",
    "eng",
    "ing",
    "ong",
    "iao",
    "ian",
    "uan",
    "uai",
    "uei",
    "ui",
    "uo",
    "ua",
    "ue",
    "ve",
    "ai",
    "ei",
    "ao",
    "ou",
    "an",
    "en",
    "in",
    "un",
    "er",
    "a",
    "o",
    "e",
    "i",
    "u",
    "v",
)


_PINYIN_SYLLABLE_INITIALS = (
    "zh",
    "ch",
    "sh",
    "b",
    "p",
    "m",
    "f",
    "d",
    "t",
    "n",
    "l",
    "g",
    "k",
    "h",
    "j",
    "q",
    "x",
    "r",
    "z",
    "c",
    "s",
    "y",
    "w",
    "",
)


def _looks_like_single_pinyin_syllable(prefix: str) -> bool:
    if not 5 <= len(prefix) <= 6:
        return False
    for initial in _PINYIN_SYLLABLE_INITIALS:
        if not prefix.startswith(initial):
            continue
        final = prefix[len(initial) :]
        if final in _PINYIN_SYLLABLE_FINALS:
            return True
    return False


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
    model_inserted = 0
    suggestion_inserted = 0
    has_suggestion_items = bool(rag_items or memory_items)
    suggestion_count = len(rag_items) + len(memory_items)
    model_slot_cap = _display_max_model_side_candidates(side_budget, has_suggestions=has_suggestion_items)
    if side_budget <= 1:
        suggestion_reserve = 0 if model_items else min(suggestion_count, 1)
    elif side_budget == 2:
        suggestion_reserve = min(suggestion_count, 1)
    else:
        minimum_model_slots = min(2, len(model_items))
        suggestion_reserve = min(
            suggestion_count,
            rag_block_reserve(side_budget),
            max(0, side_budget - minimum_model_slots),
        )
    model_before_suggestions_limit = min(model_slot_cap, max(0, side_budget - suggestion_reserve))

    def append_model() -> bool:
        nonlocal side_inserted, model_inserted
        while model_items:
            if (
                side_inserted >= side_budget
                or model_inserted >= model_slot_cap
                or len(display) >= max_visible - rime_reserve
            ):
                return False
            prediction = model_items.pop(0)
            candidate_text = _strip_candidate_source_suffix(prediction.text)
            candidate_insert_text = _strip_candidate_source_suffix(
                str(prediction.metadata.get("insert_text") or candidate_text)
            )
            normalized_text = _display_text_norm(candidate_text)
            if not normalized_text or normalized_text in display_texts:
                continue
            display_texts.add(normalized_text)
            display.append(
                SideCandidateDisplayItem(
                    label=_display_label("", len(display)),
                    text=candidate_text,
                    insert_text=candidate_insert_text,
                    source_type="model",
                    selection_action="commit_side_candidate",
                    source_index=prediction.rank - 1,
                    comment=prediction.provider_name,
                    display_layout="block",
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
            model_inserted += 1
            return True
        return False

    def append_suggestion(group: list[tuple[int, InputSuggestion]]) -> bool:
        nonlocal side_inserted, suggestion_inserted
        while group:
            if (
                side_inserted >= side_budget
                or suggestion_inserted >= suggestion_reserve
                or len(display) >= max_visible - rime_reserve
            ):
                return False
            source_index, suggestion = group.pop(0)
            candidate_text = _strip_candidate_source_suffix(suggestion.surface_text)
            candidate_insert_text = _strip_candidate_source_suffix(
                str(suggestion.metadata.get("insert_text") or candidate_text)
            )
            normalized_text = _display_text_norm(candidate_text)
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
                    text=candidate_text,
                    insert_text=candidate_insert_text,
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
            suggestion_inserted += 1
            return True
        return False

    while side_inserted < model_before_suggestions_limit and len(display) < max_visible - rime_reserve:
        if not append_model():
            break
    append_suggestion(rag_items)
    append_suggestion(memory_items)
    while side_inserted < side_budget and len(display) < max_visible - rime_reserve:
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
                display_lane=candidate.comment or "wanxiang",
                metadata={"candidate_mode": "composition-rime"},
            )
        )
    return display


def rime_only_display_candidates(snapshot: RimeContextSnapshot) -> list[SideCandidateDisplayItem]:
    display: list[SideCandidateDisplayItem] = []
    max_visible = max(0, int(snapshot.max_visible_candidates))
    seen: set[str] = set()
    for candidate in snapshot.candidates:
        if len(display) >= max_visible:
            break
        text = compact_whitespace(candidate.text)
        if not text:
            continue
        normalized_text = _display_text_norm(text)
        if normalized_text in seen:
            continue
        seen.add(normalized_text)
        display.append(
            SideCandidateDisplayItem(
                label=_display_label(candidate.label if not display else "", len(display)),
                text=text,
                insert_text=text,
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


def ui_mode_for_response(
    *,
    input_mode: str,
    display_candidates: list[SideCandidateDisplayItem],
    status_row_visible: bool = False,
) -> str:
    if input_mode in {InputMode.ANCHOR_COMPOSING.value, InputMode.PREFIX_CONSTRAINED_COMPOSING.value}:
        if display_candidates and not all(item.source_type == "rime" for item in display_candidates):
            return "active_rag_assist"
        return "composition_rime"
    if input_mode == InputMode.POST_COMMIT_PREDICTING.value:
        has_prediction = any(
            item.source_type in {"model", "rag", "memory"} and _display_item_is_selectable(item)
            for item in display_candidates
        )
        if has_prediction:
            return "post_commit_prediction"
        if status_row_visible:
            return "post_commit_pending"
        return "post_commit_pending"
    if not display_candidates:
        return "empty"
    return "active_rag_assist"


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
    return min(3, side_budget)


def _display_max_model_side_candidates(side_budget: int, *, has_suggestions: bool) -> int:
    if side_budget <= 0:
        return 0
    if has_suggestions:
        return max_model_side_candidates(side_budget)
    return min(3, side_budget)


def rag_block_reserve(side_budget: int) -> int:
    if side_budget <= 1:
        return 0
    return 1


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


def frontend_transaction_to_payload(transaction: FrontendTransaction) -> dict[str, object]:
    return {
        "frontendRevision": transaction.frontend_revision,
        "selectionEpoch": transaction.selection_epoch,
        "inputGeneration": transaction.input_generation,
        "frontAppBundleId": transaction.front_app_bundle_id,
        "inputSourceId": transaction.input_source_id,
        "compositionHash": transaction.composition_hash,
        "committedContextHash": transaction.committed_context_hash,
        "panelSessionId": transaction.panel_session_id,
        "createdAtMs": transaction.created_at_ms,
    }


def _record_display_memory_feedback(
    *,
    core: CoreClient,
    snapshot: RimeContextSnapshot,
    display_candidates: list[SideCandidateDisplayItem],
    trace_id: str,
    project: str,
) -> None:
    shown_candidate_ids = [
        item.memory_id or item.suggestion_id
        for item in display_candidates
        if item.source_type in {"rag", "memory"} and (item.memory_id or item.suggestion_id)
    ]
    for item in display_candidates:
        if item.source_type not in {"rag", "memory"}:
            continue
        _record_memory_feedback_event(
            core=core,
            event={
                "event": "shown",
                "candidateId": item.memory_id or item.suggestion_id,
                "candidateText": item.text,
                "sourceType": item.source_type,
                "lane": item.display_lane or item.source_type,
                "rank": _candidate_rank(item.label),
                "contextHash": snapshot.frontend_transaction.committed_context_hash,
                "frontAppBundleId": snapshot.frontend_transaction.front_app_bundle_id or snapshot.app,
                "rawInput": snapshot.raw_input,
                "preedit": snapshot.preedit,
                "committedTail": snapshot.committed_context,
                "timestampMs": now_ms(),
                "project": project,
                "traceId": trace_id,
                "requestSeq": snapshot.request_seq,
                "sessionId": snapshot.session_id,
                "suggestionId": item.suggestion_id,
                "sourceEventId": item.source_event_id,
                "shownCandidateIds": shown_candidate_ids,
                "shownCandidateCount": len(shown_candidate_ids),
            },
        )


def _record_memory_feedback_event(*, core: CoreClient, event: dict[str, object]) -> None:
    recorder = getattr(core, "record_memory_feedback", None)
    if not callable(recorder):
        return
    try:
        recorder(dict(event))
    except Exception:
        # Feedback is a governance signal; typing and selection must stay live if
        # the memory store or future shared core is temporarily unavailable.
        return


def display_item_to_payload(item: SideCandidateDisplayItem) -> dict[str, object]:
    metadata = dict(item.metadata)
    selectable = _display_item_is_selectable(item)
    selection_key = item.label if selectable else None
    source_badge = candidate_source_badge(item.source_type)
    color_token = candidate_color_token(item.source_type)
    text = _strip_candidate_source_suffix(item.text)
    insert_text = _strip_candidate_source_suffix(item.insert_text or text)
    group = _display_candidate_group(item)
    return {
        "label": item.label,
        "visibleLabel": metadata.get("visibleLabel") or item.label,
        "selectionKey": selection_key,
        "selectionRank": _candidate_rank(selection_key or ""),
        "candidateOrdinal": _bounded_int(
            metadata.get("candidateOrdinal"),
            default=_candidate_rank(selection_key or "") or 0,
            minimum=0,
            maximum=99,
        ),
        "candidateStableId": _string(metadata.get("candidateStableId")),
        "snapshotId": _string(metadata.get("snapshotId") or metadata.get("stableSnapshotId")),
        "snapshotGeneration": _bounded_int(
            metadata.get("snapshotGeneration"),
            default=0,
            minimum=0,
            maximum=2**63 - 1,
        ),
        "text": text,
        "insertText": insert_text,
        "sourceType": item.source_type,
        "selectionAction": item.selection_action,
        "sourceIndex": item.source_index,
        "comment": "",
        "badge": source_badge,
        "sourceBadge": metadata.get("sourceBadge") or source_badge,
        "colorToken": color_token,
        "sourceStability": metadata.get("sourceStability") or "fresh",
        "hardContextAnchor": _string(metadata.get("hardContextAnchor")),
        "queryAnchor": _string(metadata.get("queryAnchor")),
        "displayAnchor": _string(metadata.get("displayAnchor")),
        "expiresAtMs": _bounded_int(metadata.get("expiresAtMs"), default=0, minimum=0, maximum=2**63 - 1),
        "minVisibleUntilMs": _bounded_int(
            metadata.get("minVisibleUntilMs"),
            default=0,
            minimum=0,
            maximum=2**63 - 1,
        ),
        "evidencePreview": item.evidence_preview,
        "expandedEvidence": item.expanded_evidence,
        "suggestionId": item.suggestion_id,
        "memoryId": item.memory_id,
        "sourceEventId": item.source_event_id,
        "rimeIndex": item.rime_index,
        "displayLayout": item.display_layout,
        "displayLane": item.display_lane or item.source_type,
        "group": metadata.get("group") or group,
        "groupLabel": metadata.get("groupLabel") or _display_candidate_group_label(group),
        "isSelectable": selectable,
        "isStatus": item.source_type == "status" or item.display_layout == "status_row",
        "metadata": metadata,
    }


def _display_candidate_group(item: SideCandidateDisplayItem) -> str:
    if item.source_type == "status" or item.display_layout == "status_row":
        return "status"
    if item.source_type == "rime":
        return "rime"
    return "prediction"


def _display_candidate_group_label(group: str) -> str:
    return {
        "rime": "词库",
        "prediction": "预测",
        "status": "状态",
    }.get(group, group)


def key_policy_for_prediction_session(prediction_session_payload: Mapping[str, object]) -> dict[str, object]:
    return contract_key_policy_for_prediction_session(prediction_session_payload)


def refresh_decision_payload(
    *,
    snapshot: RimeContextSnapshot,
    trigger_decision: RimeSideCandidateTriggerDecision,
    semantic_query: str,
    debounce: Mapping[str, object] | None = None,
) -> dict[str, object]:
    debounce_payload = dict(debounce or {})
    return {
        "shouldRefresh": trigger_decision.should_refresh,
        "refreshReason": trigger_decision.reason,
        "reason": trigger_decision.reason,
        "idleMs": snapshot.idle_ms,
        "semanticSignalLength": semantic_signal_length(semantic_query),
        "forceSideCandidates": snapshot.force_side_candidates,
        "debounced": bool(debounce_payload.get("debounced")),
        "debounceMs": int(debounce_payload.get("debounceMs") or _refresh_debounce_ms()),
        "coalescedWithAgeMs": int(debounce_payload.get("coalescedWithAgeMs") or 0),
        "debounceKey": _string(debounce_payload.get("debounceKey")),
    }


def show_decision_payload(
    *,
    prediction_session: Mapping[str, object],
    display_candidates: list[SideCandidateDisplayItem],
) -> dict[str, object]:
    stable_panel = prediction_session.get("stablePanel")
    stable_panel = stable_panel if isinstance(stable_panel, Mapping) else {}
    action = _string(prediction_session.get("stablePanelAction") or stable_panel.get("action"))
    reason = _string(prediction_session.get("stablePanelReason") or stable_panel.get("reason"))
    should_show = bool(display_candidates) and not _bool(
        prediction_session.get("shouldClearPredictionPanel"),
        default=False,
    )
    hard_clear = action == "hard_clear"
    soft_hold = action in {"soft_hold", "reuse_last_good", "prefix_filter"}
    if should_show:
        show_reason = reason or "visible_candidates"
    elif hard_clear:
        show_reason = reason or "hard_clear"
    else:
        show_reason = _string(prediction_session.get("clearReason")) or reason or "no_visible_candidates"
    return {
        "shouldShow": should_show,
        "showReason": show_reason,
        "action": action or ("show" if should_show else "hide"),
        "hardClear": hard_clear,
        "hardClearReason": reason if hard_clear else "",
        "softHold": soft_hold,
        "softHoldReason": reason if soft_hold else "",
        "visibleCandidateCount": len(display_candidates),
        "snapshotId": _string(prediction_session.get("snapshotId") or prediction_session.get("stableSnapshotId")),
        "sourceSummary": stable_panel.get("snapshot", {}).get("sourceSummary", {})
        if isinstance(stable_panel.get("snapshot"), Mapping)
        else {},
    }


def prediction_trace_events_payload(
    *,
    prediction_session: Mapping[str, object],
    refresh_decision: Mapping[str, object],
    show_decision: Mapping[str, object],
    rag_lane: Mapping[str, object],
    model_lane: Mapping[str, object],
    display_candidates: list[SideCandidateDisplayItem],
) -> list[dict[str, object]]:
    stable_panel = prediction_session.get("stablePanel")
    stable_panel = stable_panel if isinstance(stable_panel, Mapping) else {}
    action = _string(prediction_session.get("stablePanelAction") or stable_panel.get("action"))
    reason = _string(prediction_session.get("stablePanelReason") or stable_panel.get("reason"))
    snapshot_id = _string(prediction_session.get("snapshotId") or prediction_session.get("stableSnapshotId"))
    common = {
        "mode": _string(prediction_session.get("inputMode")),
        "phase": _string(prediction_session.get("phase")),
        "hardContextAnchor": _string(prediction_session.get("hardContextAnchor")),
        "applyAnchor": _string(prediction_session.get("applyAnchor")),
        "queryAnchor": _string(prediction_session.get("queryAnchor")),
        "displayAnchor": _string(prediction_session.get("displayAnchor")),
        "snapshotId": snapshot_id,
        "visibleCandidateCount": len(display_candidates),
        "sourceSummary": _display_source_summary(display_candidates),
        "action": action,
        "reason": reason,
        "ragTimedOut": bool(rag_lane.get("timedOut")),
        "modelTimedOut": bool(model_lane.get("timedOut")),
        "asyncMode": bool(model_lane.get("asyncMode")),
        "completionJobId": _string(model_lane.get("completionJobId")),
        "completionJobState": _string(model_lane.get("completionJobState")),
        "cacheHit": bool(model_lane.get("cacheHit")),
        "inFlight": bool(model_lane.get("inFlight")),
        "jobElapsedMs": _optional_int(model_lane.get("jobElapsedMs")) or 0,
        "firstResponseMs": _optional_int(model_lane.get("firstResponseMs")) or 0,
        "noPinyinFilter": bool(model_lane.get("noPinyinFilter")),
        "holdoverHit": bool(model_lane.get("holdoverHit")) or bool(rag_lane.get("holdoverHit")),
        "hardClearReason": _string(show_decision.get("hardClearReason")),
        "previousSnapshotId": _string(stable_panel.get("previousSnapshotId")),
        "preservedOrdinalCount": _bounded_int(
            stable_panel.get("preservedOrdinalCount"),
            default=0,
            minimum=0,
            maximum=99,
        ),
        "appendedCandidateCount": _bounded_int(
            stable_panel.get("appendedCandidateCount"),
            default=0,
            minimum=0,
            maximum=99,
        ),
        "reorderedCandidateCount": _bounded_int(
            stable_panel.get("reorderedCandidateCount"),
            default=0,
            minimum=0,
            maximum=99,
        ),
        "progressiveReorderRejected": bool(stable_panel.get("progressiveReorderRejected")),
        "prefixFiltered": bool(stable_panel.get("prefixFiltered")),
        "prefixRemovedCandidateCount": _bounded_int(
            stable_panel.get("prefixRemovedCandidateCount"),
            default=0,
            minimum=0,
            maximum=99,
        ),
        "prefixKeptSideCandidateCount": _bounded_int(
            stable_panel.get("prefixKeptSideCandidateCount"),
            default=0,
            minimum=0,
            maximum=99,
        ),
    }

    events: list[dict[str, object]] = [
        {"event": "prediction_anchor_computed", "fields": _non_empty_trace_fields(common)},
        {
            "event": "prediction_refresh_decision",
            "fields": _non_empty_trace_fields({**common, **dict(refresh_decision)}),
        },
        {
            "event": "prediction_show_decision",
            "fields": _non_empty_trace_fields({**common, **dict(show_decision)}),
        },
    ]

    if action == "fresh" and snapshot_id:
        events.append({"event": "prediction_snapshot_created", "fields": _non_empty_trace_fields(common)})
    elif action == "progressive_append" and snapshot_id:
        events.append({"event": "candidate_snapshot_progressive_append", "fields": _non_empty_trace_fields(common)})
    elif action == "progressive_replace" and snapshot_id:
        events.append({"event": "candidate_snapshot_progressive_replace", "fields": _non_empty_trace_fields(common)})
        events.append({"event": "prediction_snapshot_created", "fields": _non_empty_trace_fields(common)})
    elif action in {"soft_hold", "reuse_last_good", "prefix_filter"} and snapshot_id:
        events.append({"event": "prediction_snapshot_reused", "fields": _non_empty_trace_fields(common)})
    if action == "prefix_filter":
        events.append({"event": "prediction_prefix_filter_applied", "fields": _non_empty_trace_fields(common)})
    if action == "soft_hold":
        events.append({"event": "prediction_panel_soft_hold", "fields": _non_empty_trace_fields(common)})
    elif action == "soft_hide":
        events.append({"event": "prediction_panel_soft_hide", "fields": _non_empty_trace_fields(common)})
    elif action == "hard_clear":
        events.append({"event": "prediction_panel_hard_clear", "fields": _non_empty_trace_fields(common)})

    if bool(model_lane.get("asyncMode")):
        state = _string(model_lane.get("completionJobState"))
        if state == "started":
            events.append({"event": "post_commit_completion_job_started", "fields": _non_empty_trace_fields(common)})
        if state == "hit":
            events.append({"event": "post_commit_completion_job_cache_hit", "fields": _non_empty_trace_fields(common)})
        if bool(model_lane.get("inFlight")):
            events.append({"event": "post_commit_completion_job_pending", "fields": _non_empty_trace_fields(common)})
        if state == "hit" and _bounded_int(model_lane.get("predictionCount"), default=0, minimum=0, maximum=999) > 0:
            events.append({"event": "post_commit_completion_job_completed", "fields": _non_empty_trace_fields(common)})
        if state == "timeout" or bool(model_lane.get("timedOut")):
            events.append({"event": "post_commit_completion_job_timeout", "fields": _non_empty_trace_fields(common)})
        if state == "stale":
            events.append(
                {"event": "post_commit_completion_job_stale_dropped", "fields": _non_empty_trace_fields(common)}
            )
        if state == "error" or bool(model_lane.get("error")):
            events.append({"event": "post_commit_completion_job_error", "fields": _non_empty_trace_fields(common)})
        events.append(
            {"event": "post_commit_completion_first_response_returned", "fields": _non_empty_trace_fields(common)}
        )

    if bool(show_decision.get("shouldShow")) and _lane_empty_or_timed_out_for_trace(rag_lane, model_lane):
        events.append(
            {
                "event": "prediction_empty_lane_did_not_clear_panel",
                "fields": _non_empty_trace_fields(common),
            }
        )
    if (bool(rag_lane.get("timedOut")) or bool(model_lane.get("timedOut"))) and bool(show_decision.get("shouldShow")):
        events.append(
            {
                "event": "prediction_lane_timeout_with_holdover",
                "fields": _non_empty_trace_fields(common),
            }
        )
    elif bool(rag_lane.get("timedOut")) or bool(model_lane.get("timedOut")):
        events.append(
            {
                "event": "prediction_lane_timeout_without_holdover",
                "fields": _non_empty_trace_fields(common),
            }
        )
    return events


def _display_source_summary(display_candidates: list[SideCandidateDisplayItem]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in display_candidates:
        source = compact_whitespace(item.source_type)
        if not source:
            continue
        summary[source] = summary.get(source, 0) + 1
    return summary


def _lane_empty_or_timed_out_for_trace(
    rag_lane: Mapping[str, object],
    model_lane: Mapping[str, object],
) -> bool:
    return (
        bool(rag_lane.get("timedOut"))
        or bool(model_lane.get("timedOut"))
        or (bool(rag_lane.get("called")) and int(rag_lane.get("suggestionCount") or 0) <= 0)
        or (bool(model_lane.get("called")) and int(model_lane.get("predictionCount") or 0) <= 0)
    )


def _non_empty_trace_fields(fields: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in fields.items():
        if value in ("", None):
            continue
        result[key] = value
    return result


def _bind_display_candidates_to_session(
    *,
    display_candidates: list[SideCandidateDisplayItem],
    snapshot: RimeContextSnapshot,
    prediction_session_payload: Mapping[str, object],
    key_policy: Mapping[str, object] | None = None,
) -> list[SideCandidateDisplayItem]:
    session_fingerprint = _string(prediction_session_payload.get("sessionFingerprint"))
    context_fingerprint = _string(prediction_session_payload.get("contextFingerprint")) or _context_fingerprint(
        snapshot.committed_context
    )
    hard_context_anchor = _string(prediction_session_payload.get("hardContextAnchor"))
    apply_anchor = _string(prediction_session_payload.get("applyAnchor"))
    query_anchor = _string(prediction_session_payload.get("queryAnchor"))
    display_anchor = _string(prediction_session_payload.get("displayAnchor"))
    stable_snapshot_id = _string(prediction_session_payload.get("snapshotId")) or _string(
        prediction_session_payload.get("stableSnapshotId")
    )
    snapshot_generation = _bounded_int(
        prediction_session_payload.get("snapshotGeneration"),
        default=0,
        minimum=0,
        maximum=2**63 - 1,
    )
    min_visible_until_ms = _bounded_int(
        _nested_prediction_session_value(prediction_session_payload, "minVisibleUntilMs"),
        default=0,
        minimum=0,
        maximum=2**63 - 1,
    )
    expires_at_ms = _bounded_int(
        _nested_prediction_session_value(prediction_session_payload, "expiresAtMs"),
        default=0,
        minimum=0,
        maximum=2**63 - 1,
    )
    source_stability = _source_stability_from_session(prediction_session_payload)
    phase = _string(prediction_session_payload.get("phase"))
    scope = _string(prediction_session_payload.get("selectionScope"))
    transaction = snapshot.frontend_transaction
    bound: list[SideCandidateDisplayItem] = []
    ordinal = 0
    for item in display_candidates:
        selectable = _display_item_is_selectable(item)
        if selectable:
            ordinal += 1
        candidate_ordinal = ordinal if selectable else 0
        display_label = _display_label("", candidate_ordinal - 1) if selectable else ""
        metadata = dict(item.metadata)
        metadata.update(
            {
                "sessionFingerprint": session_fingerprint,
                "contextFingerprint": context_fingerprint,
                "hardContextAnchor": hard_context_anchor,
                "applyAnchor": apply_anchor,
                "queryAnchor": query_anchor,
                "displayAnchor": display_anchor,
                "snapshotId": stable_snapshot_id,
                "stableSnapshotId": stable_snapshot_id,
                "snapshotGeneration": snapshot_generation,
                "candidateStableId": _candidate_stable_id(item, snapshot_id=stable_snapshot_id),
                "candidateOrdinal": candidate_ordinal,
                "visibleLabel": display_label,
                "sourceBadge": candidate_source_badge(item.source_type),
                "sourceStability": source_stability,
                "expiresAtMs": expires_at_ms,
                "minVisibleUntilMs": min_visible_until_ms,
                "keyPolicy": dict(key_policy or {}),
                "requestSeq": snapshot.request_seq,
                "sessionId": snapshot.session_id,
                "predictionSessionPhase": phase,
                "selectionScope": scope,
                "frontendRevision": transaction.frontend_revision,
                "selectionEpoch": transaction.selection_epoch,
                "frontAppBundleId": transaction.front_app_bundle_id,
                "inputSourceId": transaction.input_source_id,
                "compositionHash": transaction.composition_hash,
                "committedContextHash": transaction.committed_context_hash,
                "panelSessionId": transaction.panel_session_id,
            }
        )
        bound.append(replace(item, label=display_label, metadata=metadata))
    return bound


def _display_item_is_selectable(item: SideCandidateDisplayItem) -> bool:
    return bool(compact_whitespace(item.label)) and item.selection_action not in {"", "none"} and item.source_type != "status"


def _nested_prediction_session_value(prediction_session_payload: Mapping[str, object], key: str) -> object:
    if key in prediction_session_payload:
        return prediction_session_payload.get(key)
    stable_panel = prediction_session_payload.get("stablePanel")
    if not isinstance(stable_panel, Mapping):
        return None
    snapshot = stable_panel.get("snapshot")
    if isinstance(snapshot, Mapping):
        return snapshot.get(key)
    return None


def _source_stability_from_session(prediction_session_payload: Mapping[str, object]) -> str:
    if _bool(prediction_session_payload.get("reusedLastGood"), default=False):
        return "reused_last_good"
    stable_panel = prediction_session_payload.get("stablePanel")
    if isinstance(stable_panel, Mapping):
        snapshot = stable_panel.get("snapshot")
        if isinstance(snapshot, Mapping):
            stale_level = _string(snapshot.get("staleLevel"))
            if stale_level:
                return stale_level
    return "fresh"


def _candidate_stable_id(item: SideCandidateDisplayItem, *, snapshot_id: str) -> str:
    material = "\x1f".join(
        (
            snapshot_id,
            item.source_type,
            str(item.source_index),
            compact_whitespace(item.text),
            compact_whitespace(item.insert_text),
        )
    )
    return f"{item.source_type}:{hashlib.sha1(material.encode('utf-8')).hexdigest()[:16]}"


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
    try:
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
    except Exception:
        return None
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
    try:
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
    except Exception:
        return None
    return action_response_payload(action)


def _selection_feedback_base_event(
    *,
    payload: dict[str, Any],
    candidate: dict[str, Any],
    project: str,
    query: str,
    recent_context: str,
    shown_candidate_ids: list[str],
) -> dict[str, object]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    assert isinstance(metadata, dict)
    frontend_transaction = payload.get("frontendTransaction") if isinstance(payload.get("frontendTransaction"), dict) else {}
    assert isinstance(frontend_transaction, dict)
    normalized_shown_candidate_ids = [item for item in shown_candidate_ids if item]
    context_hash = _string(
        payload.get("committedContextHash")
        or metadata.get("committedContextHash")
        or payload.get("contextHash")
        or frontend_transaction.get("committedContextHash")
    )
    front_app_bundle_id = _string(
        payload.get("frontAppBundleId")
        or metadata.get("frontAppBundleId")
        or payload.get("app")
    )
    return {
        "contextHash": context_hash,
        "frontAppBundleId": front_app_bundle_id,
        "rawInput": _string(payload.get("rawInput")),
        "preedit": _string(payload.get("preedit")),
        "committedTail": recent_context,
        "recentContext": recent_context,
        "timestampMs": now_ms(),
        "project": project,
        "query": query,
        "traceId": _string(payload.get("traceId") or metadata.get("traceId")),
        "requestSeq": _optional_int(payload.get("requestSeq")) or 0,
        "sessionId": _string(payload.get("sessionId") or metadata.get("sessionId")),
        "shownCandidateIds": normalized_shown_candidate_ids,
        "shownCandidateCount": len(normalized_shown_candidate_ids),
    }


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
