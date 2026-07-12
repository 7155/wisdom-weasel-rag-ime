from __future__ import annotations

import threading
import uuid
import re
import time
from dataclasses import dataclass, field, replace

from .active_rag_candidate_compiler import (
    ActiveRagCandidate,
    compile_active_rag_candidates,
    compile_active_rag_candidates_from_evidence,
)
from .active_rag_models import ActiveRagEvidence, ActiveRagFrame, ACTIVE_RAG_MODE, active_rag_key_policy
from .active_rag_retriever import retrieve_active_rag_evidence
from .contracts.context_observability import (
    ACTIVE_RAG_ROUTE_STATUS_SCHEMA_VERSION,
    build_context_injection_trace,
    evidence_injection_diagnostics,
    text_fingerprint,
)
from .deepseek_completion import (
    CompletionCandidateDelta,
    DeepSeekCompletionError,
    DeepSeekCompletionRequest,
    build_deepseek_completion_messages,
    resolved_active_rag_current_request,
)
from .local_sqlite_core import LocalSqliteCoreClient
from .prediction_status import thinking_animation_frame, thinking_animation_suffix
from .runtime_flags import assert_deepseek_scene_allowed
from .smart_rag_context_packet import build_active_rag_context_packet
from .text_utils import compact_whitespace, now_ms, stable_text_hash, token_terms
from .timeline_context import timeline_evidence_pack_from_core


ACTIVE_RAG_SERVICE_SCHEMA_VERSION = "rag-ime.active-rag-service.v1"
ACTIVE_RAG_VISIBLE_READY_TIMEOUT_MS = 15_000
ACTIVE_RAG_DEFAULT_MAX_CHARS = 120
SENSITIVE_FIELD_BLOCK_REASON = "sensitive_field_blocked"

_TIMELINE_GENERIC_TERMS = {
    "这里",
    "当前",
    "前台",
    "上下文",
    "测试",
    "内容",
    "应该",
    "没有",
    "功能",
    "一下",
    "一个",
    "这个",
    "那个",
    "目前",
    "现在",
    "可以",
    "需要",
    "进行",
    "问题",
    "输入",
    "输出",
    "输入法",
    "候选",
    "rag",
    "ime",
    "squirrel",
    "codex",
}
# ``token_terms`` emits CJK bigrams/trigrams. A literal stop-word check alone
# therefore lets fragments such as ``下文`` or ``台上`` manufacture relevance
# for an unrelated memory book. Drop n-grams made entirely from generic UI words.
_TIMELINE_GENERIC_CJK_CHARS = frozenset(
    "这里当前前台上下文测试内容应该没有功能一下一个这个那个目前现在可以需要进行问题输入输出法候选用于"
)


@dataclass(frozen=True)
class ActiveRagStartRequest:
    selected_text: str
    selected_text_hash: str
    frontend_revision: int
    selection_epoch: int
    panel_session_id: str = ""
    front_app_bundle_id: str = ""
    surrounding_before: str = ""
    surrounding_after: str = ""
    intent: str = "rewrite"
    placement: str = "replace_selection"
    context: str = ""
    context_source: str = ""
    frontend_context_hash: str = ""
    frontend_context_chars: int = 0
    frontend_selected_text_chars: int = 0
    evidence_pack: tuple[dict[str, object], ...] = ()
    project: str = "wisdom-weasel-rag-ime"
    app: str = ""
    max_candidates: int = 1
    max_chars: int = ACTIVE_RAG_DEFAULT_MAX_CHARS
    latency_budget_ms: int = 15000
    remote_model_allowed: bool | None = None
    remote_model_skip_reason: str = ""
    remote_model_gates: dict[str, bool] = field(default_factory=dict)
    sensitive_field: bool = False
    secure_input: bool = False
    sensitive_text_guard_enabled: bool = True
    sensitive_text_guard_hit: bool = False
    local_retrieval_allowed: bool = True
    local_retrieval_skip_reason: str = ""
    rag_enabled_lanes: tuple[tuple[str, bool], ...] = ()
    rag_lane_weights: tuple[tuple[str, float], ...] = ()


@dataclass
class ActiveRagSession:
    session_id: str
    request: ActiveRagStartRequest
    status: str = "pending"
    evidence: tuple[ActiveRagEvidence, ...] = ()
    candidates: tuple[ActiveRagCandidate, ...] = ()
    error: str = ""
    diagnostics: dict[str, object] = field(default_factory=dict)
    trace_events: list[dict[str, object]] = field(default_factory=list)
    created_at_ms: int = field(default_factory=now_ms)
    updated_at_ms: int = field(default_factory=now_ms)


class ActiveRagService:
    def __init__(self, *, core: LocalSqliteCoreClient | None = None, completion_provider=None):
        self.core = core
        if self.core is not None:
            self.core.initialize()
        self.completion_provider = completion_provider
        self._lock = threading.RLock()
        self._sessions: dict[str, ActiveRagSession] = {}
        self._blocked_responses: dict[str, dict[str, object]] = {}

    def start(self, request: ActiveRagStartRequest) -> dict[str, object]:
        sensitive_reason = active_rag_sensitive_block_reason(request)
        if sensitive_reason:
            session_id = f"active-rag:blocked:{uuid.uuid4().hex[:12]}"
            response = _sensitive_blocked_payload(session_id=session_id, reason=sensitive_reason)
            with self._lock:
                self._blocked_responses[session_id] = response
                while len(self._blocked_responses) > 16:
                    self._blocked_responses.pop(next(iter(self._blocked_responses)))
            return dict(response)
        _validate_selected_text_hash(request)
        session = ActiveRagSession(
            session_id=f"active-rag:{uuid.uuid4().hex[:16]}",
            request=request,
            diagnostics=_initial_session_diagnostics(request, completion_provider=self.completion_provider),
        )
        _append_trace_event(session, "active_rag_context_captured", requestCapture=session.diagnostics["requestCapture"])
        with self._lock:
            self._drop_stale_sessions_locked(request)
            self._sessions[session.session_id] = session
        thread = threading.Thread(target=self._run_session, args=(session.session_id,), daemon=True)
        thread.start()
        return self.status(session.session_id)

    def preview(self, request: ActiveRagStartRequest, *, local_only: bool = True) -> dict[str, object]:
        sensitive_reason = active_rag_sensitive_block_reason(request)
        if sensitive_reason:
            return {
                "dryRun": True,
                **_sensitive_blocked_payload(
                    session_id="active-rag:blocked-preview",
                    reason=sensitive_reason,
                ),
            }
        _validate_selected_text_hash(request)
        diagnostics = _initial_session_diagnostics(request, completion_provider=self.completion_provider)
        trace_events: list[dict[str, object]] = []
        evidence = self._retrieve_local_evidence(request, diagnostics=diagnostics)
        trace_events.append(_trace_event("active_rag_retrieval_completed", retrieval=diagnostics.get("retrieval", {})))
        local_candidates = compile_active_rag_candidates_from_evidence(
            evidence,
            frame=_frame_from_request(request),
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
        )
        if not local_only:
            route = _remote_active_rag_route(self.completion_provider, request=request)
            diagnostics["route"] = route
            deepseek_candidates = (
                self._deepseek_candidates(request, evidence=evidence, diagnostics=diagnostics, trace_events=trace_events)
                if route["ready"]
                else ()
            )
            candidates = (
                deepseek_candidates
                if route["ready"]
                else _merge_candidates(
                    local_candidates,
                    deepseek_candidates,
                    max_candidates=request.max_candidates,
                    prefer_deepseek=True,
                )
            )
        else:
            diagnostics["route"] = {
                **_remote_active_rag_route(self.completion_provider, request=request),
                "ready": False,
                "attempted": False,
                "skipReason": "local_only_request",
            }
            diagnostics["remoteModel"] = {
                **dict(diagnostics.get("remoteModel") or {}),
                "requested": False,
                "allowed": False,
                "skipReason": "local_only_request",
            }
            candidates = local_candidates
        diagnostics["generation"] = {
            **dict(diagnostics.get("generation") or {}),
            "localCandidateCount": len(local_candidates),
            "displayedCandidateCount": len(candidates),
        }
        trace_events.append(
            _trace_event(
                "active_rag_candidates_displayed",
                candidateCount=len(candidates),
                sourceCounts=_candidate_source_counts(candidates),
            )
        )
        session = ActiveRagSession(
            session_id="active-rag:preview",
            request=request,
            status="ready",
            evidence=evidence,
            candidates=candidates,
            diagnostics=diagnostics,
            trace_events=trace_events,
        )
        return {"ok": True, "dryRun": True, **_session_payload(session)}

    def status(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                blocked = self._blocked_responses.get(session_id)
                if blocked is not None:
                    return dict(blocked)
                return {"schemaVersion": ACTIVE_RAG_SERVICE_SCHEMA_VERSION, "sessionId": session_id, "status": "missing"}
            if session.status == "pending" and _should_force_visible_fallback(session):
                self._force_visible_fallback_locked(session, reason="visible_timeout")
            return _session_payload(session)

    def diagnostics(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                blocked = self._blocked_responses.get(session_id)
                if blocked is not None:
                    return {
                        "schemaVersion": "rag-ime.active-rag-diagnostics.v1",
                        "ok": False,
                        "sessionId": session_id,
                        "status": "blocked",
                        "diagnostics": dict(blocked.get("diagnostics") or {}),
                        "traceEvents": list(blocked.get("traceEvents") or []),
                        "error": SENSITIVE_FIELD_BLOCK_REASON,
                    }
                return {
                    "schemaVersion": "rag-ime.active-rag-diagnostics.v1",
                    "ok": False,
                    "sessionId": session_id,
                    "status": "missing",
                    "error": "Active RAG session not found",
                }
            return {
                "schemaVersion": "rag-ime.active-rag-diagnostics.v1",
                "ok": True,
                "sessionId": session.session_id,
                "status": session.status,
                "diagnostics": dict(session.diagnostics),
                "traceEvents": list(session.trace_events),
                "error": session.error,
            }

    def cancel(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and session.status == "pending":
                session.status = "cancelled"
                session.updated_at_ms = now_ms()
                self._record_cancel_feedback(session=session)
            return _session_payload(session) if session is not None else {"sessionId": session_id, "status": "missing"}

    def accept(
        self,
        *,
        session_id: str,
        candidate_id: str,
        selected_text_hash: str,
        frontend_revision: int,
        selection_epoch: int,
        panel_session_id: str = "",
        front_app_bundle_id: str = "",
    ) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {"ok": False, "reason": "missing_session"}
            if selected_text_hash != session.request.selected_text_hash:
                return {"ok": False, "reason": "selected_text_hash_mismatch"}
            if int(frontend_revision) != int(session.request.frontend_revision):
                return {"ok": False, "reason": "frontend_revision_mismatch"}
            if int(selection_epoch) != int(session.request.selection_epoch):
                return {"ok": False, "reason": "selection_epoch_mismatch"}
            if session.request.panel_session_id and panel_session_id and panel_session_id != session.request.panel_session_id:
                return {"ok": False, "reason": "panel_session_id_mismatch"}
            if session.request.front_app_bundle_id and front_app_bundle_id and front_app_bundle_id != session.request.front_app_bundle_id:
                return {"ok": False, "reason": "front_app_bundle_id_mismatch"}
            candidate = next((item for item in session.candidates if item.candidate_id == candidate_id), None)
            if candidate is None:
                return {"ok": False, "reason": "missing_candidate"}
            self._record_accept_feedback(session=session, candidate=candidate)
            return {
                "ok": True,
                "sessionId": session_id,
                "candidateId": candidate_id,
                "insertText": candidate.insert_text,
                "placement": session.request.placement,
            }

    def _run_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return
        try:
            evidence = self._retrieve_local_evidence(session.request, diagnostics=session.diagnostics)
            _append_trace_event(
                session,
                "active_rag_retrieval_completed",
                retrieval=session.diagnostics.get("retrieval", {}),
            )
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current.status != "pending":
                    return
                current.evidence = evidence
                current.updated_at_ms = now_ms()
            route = _remote_active_rag_route(self.completion_provider, request=session.request)
            session.diagnostics["route"] = route
            remote_model_enabled = bool(route["ready"])
            if remote_model_enabled:
                candidates = self._deepseek_candidates(
                    session.request,
                    evidence=evidence,
                    diagnostics=session.diagnostics,
                    trace_events=session.trace_events,
                    stream_sink=lambda text: self._publish_deepseek_partial(session_id, text),
                )
            else:
                candidates = self._local_candidates(session.request, evidence=evidence)
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current.status != "pending":
                    return
                current.evidence = evidence
                current.candidates = candidates
                current.diagnostics["generation"] = {
                    **dict(current.diagnostics.get("generation") or {}),
                    "displayedCandidateCount": len(candidates),
                    "displayedSourceCounts": _candidate_source_counts(candidates),
                }
                _append_trace_event(
                    current,
                    "active_rag_candidates_displayed",
                    candidateCount=len(candidates),
                    sourceCounts=_candidate_source_counts(candidates),
                )
                self._record_shown_feedback(session=current, candidates=candidates)
                if candidates:
                    current.status = "ready"
                else:
                    current.status = "error"
                    current.error = (
                        "remote_generation_returned_no_insertable_content"
                        if remote_model_enabled
                        else "local_rag_returned_no_insertable_content"
                    )
                current.updated_at_ms = now_ms()
        except Exception as exc:
            with self._lock:
                current = self._sessions.get(session_id)
                if current is not None and current.status == "pending":
                    current.diagnostics["failure"] = {
                        "stage": "active_rag_session",
                        "errorType": type(exc).__name__,
                        "reason": _safe_failure_reason(exc),
                    }
                    self._force_visible_fallback_locked(current, reason=type(exc).__name__)
                    if current.status == "error":
                        current.error = _safe_failure_reason(exc)
                    current.updated_at_ms = now_ms()

    def _retrieve_local_evidence(
        self,
        request: ActiveRagStartRequest,
        *,
        diagnostics: dict[str, object] | None = None,
    ) -> tuple[ActiveRagEvidence, ...]:
        started = time.perf_counter()
        evidence: tuple[ActiveRagEvidence, ...] = ()
        primary_raw_count = 0
        primary_count = 0
        timeline_count = 0
        retrieval_error = ""
        retrieval_allowed = self.core is not None and request.local_retrieval_allowed
        if retrieval_allowed:
            try:
                evidence = retrieve_active_rag_evidence(
                    self.core,
                    _frame_from_request(request),
                    enabled_lanes=request.rag_enabled_lanes,
                    lane_weights=request.rag_lane_weights,
                )
                primary_raw_count = len(evidence)
                evidence = _filter_primary_active_rag_evidence(
                    evidence,
                    query=_resolved_active_rag_request_text(request),
                )
                primary_count = len(evidence)
            except Exception as exc:
                retrieval_error = f"{type(exc).__name__}: {_safe_failure_reason(exc)}"
                evidence = ()
            try:
                timeline_evidence = _timeline_evidence_from_core(self.core, request)
                timeline_count = len(timeline_evidence)
                evidence = _merge_evidence(evidence, timeline_evidence)
            except Exception as exc:
                if not retrieval_error:
                    retrieval_error = f"{type(exc).__name__}: {_safe_failure_reason(exc)}"
        fallback_used = not _grounding_evidence(evidence) and bool(request.evidence_pack)
        result = (
            _merge_evidence(evidence, _evidence_from_pack(request.evidence_pack))
            if fallback_used
            else evidence
        )
        if diagnostics is not None:
            evidence_payloads = tuple(_evidence_payload(item) for item in result)
            evidence_diagnostics = evidence_injection_diagnostics(evidence_payloads)
            diagnostics["retrieval"] = {
                "called": retrieval_allowed,
                "attempted": retrieval_allowed,
                "coreAvailable": self.core is not None,
                "skipReason": request.local_retrieval_skip_reason if not retrieval_allowed else "",
                "primaryRawRetrievedCount": primary_raw_count,
                "primaryRetrievedCount": primary_count,
                "timelineRetrievedCount": timeline_count,
                "requestEvidenceCount": len(request.evidence_pack),
                "fallbackToRequestEvidence": fallback_used,
                "retrievedCount": len(result),
                "evidenceCount": len(_grounding_evidence(result)),
                "contextEvidenceCount": sum(1 for item in result if _is_context_only_evidence(item)),
                "surfaceCandidateCount": sum(
                    1 for item in result if item.source_type in {"phrase", "surface_phrase"}
                ),
                "error": retrieval_error,
                **evidence_diagnostics,
                "lanes": evidence_diagnostics["sourceLaneCounts"],
                "configuredLanes": dict(request.rag_enabled_lanes),
                "configuredWeights": dict(request.rag_lane_weights),
                "embeddingProvider": getattr(getattr(self.core, "embedding_provider", None), "fingerprint", "none")
                if self.core is not None
                else "none",
                "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
            }
        return result

    def _deepseek_candidates(
        self,
        request: ActiveRagStartRequest,
        *,
        evidence: tuple[ActiveRagEvidence, ...],
        diagnostics: dict[str, object] | None = None,
        trace_events: list[dict[str, object]] | None = None,
        stream_sink=None,
    ) -> tuple[ActiveRagCandidate, ...]:
        provider = self.completion_provider
        if provider is None:
            return ()
        try:
            assert_deepseek_scene_allowed("active_rag")
        except RuntimeError as exc:
            if diagnostics is not None:
                diagnostics["route"] = {
                    **_remote_active_rag_route(provider, request=request),
                    "ready": False,
                    "skipReason": "scene_flag_disabled",
                    "reason": str(exc),
                }
            return ()
        model_evidence = _deepseek_evidence_pack(request=request, evidence=evidence)
        effective_context, effective_source, effective_context_meta = _effective_active_rag_context(
            request,
            evidence=evidence,
        )
        grounding_evidence = _grounding_evidence(evidence)
        context_packet = build_active_rag_context_packet(
            scene="active_rag",
            current_context=effective_context,
            selected_text=request.selected_text,
            selected_text_hash=request.selected_text_hash,
            frontend_revision=request.frontend_revision,
            selection_epoch=request.selection_epoch,
            panel_session_id=request.panel_session_id,
            project=request.project,
            app=request.app or request.front_app_bundle_id,
            evidence=grounding_evidence,
            intent=request.intent,
            placement=request.placement,
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
            latency_budget_ms=request.latency_budget_ms,
            remote_model_allowed=True,
        )
        completion_request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context=effective_context,
            selected_text=request.selected_text,
            evidence_pack=model_evidence,
            context_packet=context_packet,
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
            latency_budget_ms=_remote_completion_budget_ms(request),
        )
        resolved_model_request = resolved_active_rag_current_request(completion_request)
        messages = build_deepseek_completion_messages(completion_request)
        if diagnostics is not None:
            context_trace = build_context_injection_trace(
                current_context=completion_request.current_context,
                selected_text=completion_request.selected_text,
                surrounding_before=request.surrounding_before,
                surrounding_after=request.surrounding_after,
                evidence_pack=model_evidence,
                context_packet=context_packet,
                messages=messages,
            )
            context_fingerprint = text_fingerprint(completion_request.current_context)
            selected_fingerprint = text_fingerprint(completion_request.selected_text)
            injection = context_trace.get("injection") if isinstance(context_trace.get("injection"), dict) else {}
            missing = list(injection.get("missing") or []) if isinstance(injection, dict) else []
            warnings = [
                *missing,
                *_capture_validation_warnings(request, context_text=request.context or request.surrounding_before),
            ]
            if not request.context and request.surrounding_before:
                warnings.append("used_surrounding_before_fallback")
            if effective_context_meta["augmentedWithTimelineRecentInput"]:
                warnings.append("augmented_with_timeline_recent_input")
            diagnostics["contextInjection"] = {
                "applied": bool(injection.get("success")) if isinstance(injection, dict) else False,
                "source": effective_source,
                "contextChars": context_fingerprint["chars"],
                "foregroundContextChars": effective_context_meta["foregroundContextChars"],
                "effectiveContextChars": effective_context_meta["effectiveContextChars"],
                "timelineRecentInputChars": effective_context_meta["timelineRecentInputChars"],
                "augmentedWithTimelineRecentInput": effective_context_meta["augmentedWithTimelineRecentInput"],
                "timelineRecentInputUsedForGeneration": effective_context_meta[
                    "timelineRecentInputUsedForGeneration"
                ],
                "contextPolicy": effective_context_meta["contextPolicy"],
                "contextHash": stable_text_hash(completion_request.current_context),
                "selectedTextChars": selected_fingerprint["chars"],
                "selectedTextHash": request.selected_text_hash,
                "resolvedRequestChars": len(resolved_model_request),
                "resolvedRequestHash": stable_text_hash(resolved_model_request),
                "shortForegroundCapture": effective_context_meta["foregroundContextChars"] < 8,
                "fullForegroundDocumentCaptured": False,
                "warnings": warnings,
                "trace": context_trace,
            }
            diagnostics["modelRequest"] = {
                "provider": "deepseek",
                "model": _provider_model(provider),
                "scene": "active_rag",
                "attempted": True,
                "completed": False,
                "latencyBudgetMs": completion_request.latency_budget_ms,
                "requestedCandidateCount": completion_request.max_candidates,
                "stream": True,
                "evidenceRetrievedCount": len(grounding_evidence),
                "evidenceInjectedCount": len(model_evidence),
                "evidenceGovernedOutCount": max(0, len(request.evidence_pack) + len(evidence[:10]) - len(model_evidence)),
            }
            diagnostics["remoteModel"] = {
                "requested": True,
                "allowed": True,
                "provider": "deepseek",
                "model": _provider_model(provider),
                "skipReason": "",
                "elapsedMs": 0.0,
            }
        if trace_events is not None:
            trace_events.append(
                _trace_event(
                    "deepseek_request_context_built",
                    injection=(diagnostics or {}).get("contextInjection", {}),
                )
            )
            trace_events.append(_trace_event("deepseek_request_started", provider="deepseek", model=_provider_model(provider)))
        model_started = time.perf_counter()
        retry_attempted = False
        retry_reason = ""

        def run_completion(active_request: DeepSeekCompletionRequest) -> tuple[CompletionCandidateDelta, ...]:
            if stream_sink is not None and bool(getattr(provider, "supports_text_delta_callback", False)):
                return tuple(provider.stream_candidates(active_request, on_text_delta=stream_sink))
            return tuple(provider.stream_candidates(active_request))

        recovery_selected_text = (
            request.selected_text
            if request.placement == "replace_selection" and len(compact_whitespace(request.selected_text)) >= 8
            else ""
        )
        recovery_context_packet = dict(context_packet)
        recovery_current_input = (
            dict(recovery_context_packet.get("currentInput"))
            if isinstance(recovery_context_packet.get("currentInput"), dict)
            else {}
        )
        if not recovery_selected_text:
            recovery_current_input.pop("selectedText", None)
        recovery_context_packet["currentInput"] = recovery_current_input
        recovery_request = replace(
            completion_request,
            selected_text=recovery_selected_text,
            evidence_pack=(),
            context_packet=recovery_context_packet,
            recovery_mode=True,
        )

        try:
            try:
                raw_deltas = run_completion(completion_request)
            except DeepSeekCompletionError as exc:
                if not _retryable_empty_generation_error(exc):
                    raise
                retry_attempted = True
                retry_reason = _safe_failure_reason(exc)
                if trace_events is not None:
                    trace_events.append(_trace_event("deepseek_context_only_retry_started", reason=retry_reason))
                raw_deltas = run_completion(recovery_request)
            candidates = compile_active_rag_candidates(
                raw_deltas,
                selected_text=request.selected_text,
                max_candidates=request.max_candidates,
                max_chars=request.max_chars,
            )
            if not candidates and not retry_attempted:
                retry_attempted = True
                retry_reason = "empty_or_governed_remote_candidates"
                if trace_events is not None:
                    trace_events.append(_trace_event("deepseek_context_only_retry_started", reason=retry_reason))
                raw_deltas = run_completion(recovery_request)
                candidates = compile_active_rag_candidates(
                    raw_deltas,
                    selected_text=request.selected_text,
                    max_candidates=request.max_candidates,
                    max_chars=request.max_chars,
                )
        except Exception as exc:
            if diagnostics is not None:
                diagnostics["modelRequest"] = {
                    **dict(diagnostics.get("modelRequest") or {}),
                    "completed": False,
                    "errorType": type(exc).__name__,
                    "failureReason": _safe_failure_reason(exc),
                    "contentRetryAttempted": retry_attempted,
                    "contentRetryReason": retry_reason,
                    "contentRetryCompleted": False,
                }
                diagnostics["remoteModel"] = {
                    **dict(diagnostics.get("remoteModel") or {}),
                    "skipReason": type(exc).__name__,
                    "failureReason": _safe_failure_reason(exc),
                    "elapsedMs": round((time.perf_counter() - model_started) * 1000, 2),
                }
            if trace_events is not None:
                trace_events.append(
                    _trace_event(
                        "deepseek_request_failed",
                        errorType=type(exc).__name__,
                        failureReason=_safe_failure_reason(exc),
                        contentRetryAttempted=retry_attempted,
                    )
                )
            raise
        if diagnostics is not None:
            diagnostics["modelRequest"] = {
                **dict(diagnostics.get("modelRequest") or {}),
                "completed": True,
                "rawCandidateCount": len(raw_deltas),
                "governedCandidateCount": len(candidates),
                "candidateFilteredCount": max(0, len(raw_deltas) - len(candidates)),
                "contentRetryAttempted": retry_attempted,
                "contentRetryReason": retry_reason,
                "contentRetryCompleted": bool(retry_attempted and candidates),
                "fallbackReasons": sorted(
                    {
                        str(item.metadata.get("fallbackReason"))
                        for item in raw_deltas
                        if item.metadata.get("fallbackReason")
                    }
                ),
            }
            diagnostics["remoteModel"] = {
                **dict(diagnostics.get("remoteModel") or {}),
                "skipReason": "",
                "elapsedMs": round((time.perf_counter() - model_started) * 1000, 2),
            }
        if trace_events is not None:
            trace_events.append(
                _trace_event(
                    "deepseek_request_completed",
                    rawCandidateCount=len(raw_deltas),
                    governedCandidateCount=len(candidates),
                )
            )
            trace_events.append(
                _trace_event(
                    "active_rag_evidence_governed",
                    retrievedCount=len(grounding_evidence),
                    injectedCount=len(model_evidence),
                    candidateFilteredCount=max(0, len(raw_deltas) - len(candidates)),
                    contentRetryAttempted=retry_attempted,
                    contentRetryCompleted=bool(retry_attempted and candidates),
                )
            )
        return candidates

    def _publish_deepseek_partial(self, session_id: str, text: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.status != "pending":
                return
            partial = compile_active_rag_candidates(
                (
                    CompletionCandidateDelta(
                        text=text,
                        insert_text=text,
                        done=False,
                        metadata={"streamingPartial": True},
                    ),
                ),
                selected_text=session.request.selected_text,
                max_candidates=1,
                max_chars=session.request.max_chars,
            )
            if not partial:
                return
            session.candidates = partial
            model_request = dict(session.diagnostics.get("modelRequest") or {})
            model_request.update(
                {
                    "stream": True,
                    "partialVisible": True,
                    "partialChars": len(partial[0].text),
                }
            )
            session.diagnostics["modelRequest"] = model_request
            session.updated_at_ms = now_ms()

    def _local_candidates(
        self,
        request: ActiveRagStartRequest,
        *,
        evidence: tuple[ActiveRagEvidence, ...],
    ) -> tuple[ActiveRagCandidate, ...]:
        """Use RAG evidence as context, not as a raw display lane, for model-like requests."""

        local_candidates = compile_active_rag_candidates_from_evidence(
            evidence,
            frame=_frame_from_request(request),
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
        )
        return local_candidates

    def _force_visible_fallback_locked(self, session: ActiveRagSession, *, reason: str) -> None:
        evidence = session.evidence or _evidence_from_pack(session.request.evidence_pack)
        session.evidence = evidence
        session.candidates = ()
        session.status = "error"
        session.error = f"active_rag_generation_failed:{compact_whitespace(reason) or 'unknown'}"
        session.updated_at_ms = now_ms()

    def _record_accept_feedback(self, *, session: ActiveRagSession, candidate: ActiveRagCandidate) -> None:
        if self.core is None:
            return
        self.core.record_memory_feedback(
            {
                "event": "active_rag_accept",
                "candidateId": candidate.candidate_id,
                "candidateText": candidate.text,
                "sourceType": candidate.source_type,
                "sessionId": session.session_id,
                "project": session.request.project,
                "app": session.request.app or session.request.front_app_bundle_id,
                "frontAppBundleId": session.request.front_app_bundle_id,
                "contextHash": session.request.selected_text_hash,
                "metadata": {
                    "uiMode": ACTIVE_RAG_MODE,
                    "placement": session.request.placement,
                    "intent": session.request.intent,
                    "selectedTextHash": session.request.selected_text_hash,
                    "panelSessionId": session.request.panel_session_id,
                    "frontendRevision": session.request.frontend_revision,
                    "selectionEpoch": session.request.selection_epoch,
                },
            }
        )

    def _record_cancel_feedback(self, *, session: ActiveRagSession) -> None:
        if self.core is None:
            return
        self.core.record_memory_feedback(
            {
                "event": "active_rag_cancel",
                "candidateId": f"{session.session_id}:cancel",
                "candidateText": "active_rag_cancel",
                "sourceType": "active_rag",
                "sessionId": session.session_id,
                "project": session.request.project,
                "app": session.request.app or session.request.front_app_bundle_id,
                "frontAppBundleId": session.request.front_app_bundle_id,
                "contextHash": session.request.selected_text_hash,
                "metadata": {
                    "uiMode": ACTIVE_RAG_MODE,
                    "placement": session.request.placement,
                    "intent": session.request.intent,
                    "selectedTextHash": session.request.selected_text_hash,
                    "panelSessionId": session.request.panel_session_id,
                    "frontendRevision": session.request.frontend_revision,
                    "selectionEpoch": session.request.selection_epoch,
                },
            }
        )

    def _record_shown_feedback(self, *, session: ActiveRagSession, candidates: tuple[ActiveRagCandidate, ...]) -> None:
        if self.core is None or not candidates:
            return
        shown_ids = [candidate.candidate_id for candidate in candidates]
        for rank, candidate in enumerate(candidates, start=1):
            self.core.record_memory_feedback(
                {
                    "event": "active_rag_shown",
                    "candidateId": candidate.candidate_id,
                    "candidateText": candidate.text,
                    "sourceType": candidate.source_type,
                    "sessionId": session.session_id,
                    "project": session.request.project,
                    "app": session.request.app or session.request.front_app_bundle_id,
                    "frontAppBundleId": session.request.front_app_bundle_id,
                    "contextHash": session.request.selected_text_hash,
                    "rank": rank,
                    "shownCandidateIds": shown_ids,
                    "shownCandidateCount": len(candidates),
                    "metadata": {
                        "uiMode": ACTIVE_RAG_MODE,
                        "placement": session.request.placement,
                        "intent": session.request.intent,
                        "selectedTextHash": session.request.selected_text_hash,
                        "panelSessionId": session.request.panel_session_id,
                        "frontendRevision": session.request.frontend_revision,
                        "selectionEpoch": session.request.selection_epoch,
                    },
                }
            )

    def _drop_stale_sessions_locked(self, request: ActiveRagStartRequest) -> None:
        for session in self._sessions.values():
            if session.status != "pending":
                continue
            if session.request.project != request.project or session.request.app != request.app:
                continue
            if (
                int(session.request.frontend_revision) < int(request.frontend_revision)
                or int(session.request.selection_epoch) < int(request.selection_epoch)
            ):
                session.status = "stale_dropped"
                session.updated_at_ms = now_ms()


def _validate_selected_text_hash(request: ActiveRagStartRequest) -> None:
    expected = stable_text_hash(compact_whitespace(request.selected_text))
    if request.selected_text_hash != expected:
        raise ValueError("selectedTextHash does not match selectedText")


def active_rag_sensitive_block_reason(request: ActiveRagStartRequest) -> str:
    if request.sensitive_field or request.secure_input or request.sensitive_text_guard_hit:
        return SENSITIVE_FIELD_BLOCK_REASON
    if _looks_like_sensitive_account_text(
        request.selected_text,
        request.context,
        request.surrounding_before,
        request.surrounding_after,
    ):
        return SENSITIVE_FIELD_BLOCK_REASON
    return ""


def active_rag_sensitive_text_blocked(*texts: str, guard_enabled: bool = True) -> bool:
    _ = guard_enabled
    # Credential-shaped text is a non-overridable backend boundary. The setting
    # may tune broader heuristics later, but it cannot permit passwords/tokens.
    return _looks_like_sensitive_account_text(*texts)


def _looks_like_sensitive_account_text(*texts: str) -> bool:
    combined = " ".join(str(text or "") for text in texts)
    if not combined:
        return False
    return bool(
        re.search(
            r"(?i)(?:password|passwd|passcode|credential|api[ _-]?key|access[ _-]?token|bearer\s+|"
            r"secret|one[ _-]?time[ _-]?code|账号|帐号|密码|口令|验证码|银行卡|信用卡)",
            combined,
        )
    )


def _sensitive_blocked_payload(*, session_id: str, reason: str) -> dict[str, object]:
    diagnostics = {
        "schemaVersion": "rag-ime.active-rag-diagnostics.v1",
        "privacy": {
            "rawTextIncluded": False,
            "hashAlgorithm": "none_for_sensitive_fields",
            "sensitiveFieldBlocked": True,
        },
        "contextInjection": {
            "applied": False,
            "source": "sensitive_field",
            "contextChars": 0,
            "contextHash": "",
            "selectedTextChars": 0,
            "selectedTextHash": "",
            "warnings": [reason],
        },
        "retrieval": {
            "called": False,
            "attempted": False,
            "retrievedCount": 0,
            "evidenceCount": 0,
            "lanes": {},
            "elapsedMs": 0.0,
            "error": reason,
        },
        "remoteModel": {
            "requested": False,
            "allowed": False,
            "provider": "",
            "model": "",
            "skipReason": reason,
            "elapsedMs": 0.0,
        },
        "generation": {"displayedCandidateCount": 0},
    }
    trace_events = [
        {
            "name": "active_rag_sensitive_field_blocked",
            "atMs": now_ms(),
            "fields": {"reason": reason, "textRecorded": False, "hashRecorded": False},
        }
    ]
    return {
        "schemaVersion": ACTIVE_RAG_SERVICE_SCHEMA_VERSION,
        "ok": False,
        "sessionId": session_id,
        "status": "blocked",
        "thinkingRow": False,
        "uiMode": ACTIVE_RAG_MODE,
        "keyPolicy": active_rag_key_policy(ready=False),
        "selectedTextHash": "",
        "frontendRevision": 0,
        "selectionEpoch": 0,
        "panelSessionId": "",
        "frontAppBundleId": "",
        "placement": "show_only",
        "intent": "blocked",
        "evidenceCount": 0,
        "candidateCount": 0,
        "candidates": [],
        "evidence": [],
        "diagnostics": diagnostics,
        "traceEvents": trace_events,
        "error": reason,
        "createdAtMs": now_ms(),
        "updatedAtMs": now_ms(),
        "elapsedMs": 0,
        "pollAfterMs": 0,
    }


def _resolved_active_rag_request_text(request: ActiveRagStartRequest) -> str:
    """Resolve the live request without trusting a stale semantic anchor."""

    selected = compact_whitespace(request.selected_text)
    context = compact_whitespace(request.context or request.surrounding_before)
    if request.placement == "replace_selection" or not context:
        return selected[-240:]
    if selected and selected in context:
        return selected[-240:]
    clauses = [
        compact_whitespace(item)
        for item in re.split(r"(?<=[。！？!?；;])|\n+", context)
        if compact_whitespace(item)
    ]
    return (clauses[-1] if clauses else context)[-240:]


def _timeline_item_relevant(item: dict[str, object], query: str) -> bool:
    if not query:
        return False
    surface_hints = item.get("surfaceHints") if isinstance(item.get("surfaceHints"), list) else []
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    haystack = compact_whitespace(
        " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or item.get("evidencePreview") or ""),
                *(str(value) for value in surface_hints),
                *(str(value) for value in tags),
            ]
        )
    ).lower()
    matches = {
        term
        for term in token_terms(query, max_terms=48)
        if len(term) >= 2
        and term not in _TIMELINE_GENERIC_TERMS
        and not (
            all("\u3400" <= char <= "\u9fff" for char in term)
            and all(char in _TIMELINE_GENERIC_CJK_CHARS for char in term)
        )
        and term.lower() in haystack
    }
    return bool(matches)


def _is_context_only_evidence(item: ActiveRagEvidence) -> bool:
    return item.source_type == "recent_input_context" or item.source_lane == "timeline_recent_input"


def _grounding_evidence(evidence: tuple[ActiveRagEvidence, ...]) -> tuple[ActiveRagEvidence, ...]:
    return tuple(
        item
        for item in evidence
        if not _is_context_only_evidence(item) and item.source_type not in {"phrase", "surface_phrase"}
    )


def _filter_primary_active_rag_evidence(
    evidence: tuple[ActiveRagEvidence, ...],
    *,
    query: str,
) -> tuple[ActiveRagEvidence, ...]:
    result: list[ActiveRagEvidence] = []
    for item in evidence:
        if item.source_type in {"phrase", "surface_phrase"}:
            continue
        if item.source_lane.startswith("vector_"):
            result.append(item)
            continue
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        surface_hints = metadata.get("surfaceHints") if isinstance(metadata.get("surfaceHints"), list) else []
        haystack = compact_whitespace(
            " ".join(
                [
                    item.text,
                    item.preview,
                    " ".join(item.tags),
                    str(metadata.get("title") or metadata.get("summary") or ""),
                    *(str(value) for value in surface_hints),
                ]
            )
        )
        synthetic_item = {"summary": haystack, "surfaceHints": [], "tags": []}
        if _timeline_item_relevant(synthetic_item, query):
            result.append(item)
    return tuple(result)


def _evidence_pack_item_is_context_only(item: dict[str, object]) -> bool:
    source_type = compact_whitespace(str(item.get("sourceType") or ""))
    source_lane = compact_whitespace(str(item.get("sourceLane") or ""))
    return source_type == "recent_input_context" or source_lane == "timeline_recent_input"


def _evidence_pack_item_echoes_request(item: dict[str, object], request_text: str) -> bool:
    request_value = compact_whitespace(request_text).lower()
    if not request_value:
        return False
    hints = item.get("surfaceHints") if isinstance(item.get("surfaceHints"), list) else []
    values = [
        str(item.get("text") or ""),
        str(item.get("candidateText") or ""),
        str(item.get("evidencePreview") or item.get("preview") or ""),
        *(str(value) for value in hints),
    ]
    normalized_values = [compact_whitespace(value).lower() for value in values if compact_whitespace(value)]
    return bool(normalized_values) and all(
        value == request_value or (len(value) >= 12 and request_value.endswith(value))
        for value in normalized_values
    )


def _retryable_empty_generation_error(exc: DeepSeekCompletionError) -> bool:
    reason = compact_whitespace(str(exc)).lower()
    return reason.startswith("active_rag_no_insertable_content:")


def _timeline_evidence_from_core(core: LocalSqliteCoreClient, request: ActiveRagStartRequest) -> tuple[ActiveRagEvidence, ...]:
    resolved_query = _resolved_active_rag_request_text(request)
    items = timeline_evidence_pack_from_core(
        core,
        project=request.project,
        app=request.app or request.front_app_bundle_id,
        current_context=request.context or request.surrounding_before,
        selected_text=request.selected_text,
        max_items=4,
    )
    result: list[ActiveRagEvidence] = []
    for index, item in enumerate(items, start=1):
        source_type = compact_whitespace(str(item.get("sourceType") or "timeline"))
        source_lane = compact_whitespace(str(item.get("sourceLane") or "timeline_context"))
        title = compact_whitespace(str(item.get("title") or ""))
        summary = compact_whitespace(str(item.get("summary") or item.get("evidencePreview") or ""))
        if source_type != "recent_input_context" and not _timeline_item_relevant(item, resolved_query):
            continue
        if source_type == "recent_input_context":
            text = _timeline_recent_input_text(summary)
        else:
            surface_hints = item.get("surfaceHints") if isinstance(item.get("surfaceHints"), list) else []
            text = compact_whitespace(str(surface_hints[0])) if surface_hints else (summary or title)
        if not text:
            continue
        result.append(
            ActiveRagEvidence(
                evidence_id=compact_whitespace(str(item.get("bookId") or f"timeline:{index}")),
                text=text,
                source_type="memory" if source_type in {"daily_book", "memory_book"} else source_type,
                source_lane=source_lane,
                score=0.55,
                confidence=0.6,
                tags=tuple(str(tag) for tag in item.get("tags", []) if compact_whitespace(str(tag)))
                if isinstance(item.get("tags"), list)
                else (),
                book_ids=(str(item.get("bookId")),) if item.get("bookId") else (),
                evidence_event_ids=tuple(int(value) for value in item.get("sourceEventIds", []) if isinstance(value, int))
                if isinstance(item.get("sourceEventIds"), list)
                else (),
                preview=summary,
                metadata={
                    **dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
                    "title": title,
                    "summary": summary,
                    "surfaceHints": item.get("surfaceHints") if isinstance(item.get("surfaceHints"), list) else [],
                    "timelineContext": True,
                    "sourceType": source_type,
                },
            )
        )
    return tuple(result)


def _timeline_recent_input_text(summary: str) -> str:
    """Keep committed text and useful field context from recent-input rows.

    ``recent_input_context`` serializes each row as
    ``committed | context: surrounding | preedit: ...``.  Dropping everything
    after the first context marker makes a two-character commit look like the
    whole foreground request.  Preedit is not semantic context, but the
    surrounding field text is, so preserve it as a separate clause.
    """

    clauses: list[str] = []
    for raw_segment in summary.split(" / "):
        segment = compact_whitespace(raw_segment.split(" | preedit:", 1)[0])
        committed, marker, surrounding = segment.partition(" | context:")
        committed = compact_whitespace(committed)
        values = (committed, surrounding if marker and len(committed) < 8 else "")
        for value in values:
            text = compact_whitespace(value)
            if text and text not in clauses:
                clauses.append(text)
    return compact_whitespace("。".join(clauses))


def _effective_active_rag_context(
    request: ActiveRagStartRequest,
    *,
    evidence: tuple[ActiveRagEvidence, ...],
) -> tuple[str, str, dict[str, object]]:
    foreground = compact_whitespace(request.context or request.surrounding_before)
    recent = next(
        (
            compact_whitespace(item.text)
            for item in evidence
            if item.source_type == "recent_input_context" or item.source_lane == "timeline_recent_input"
        ),
        "",
    )
    # Explicit generation must never silently replace the live editable field
    # with an older Timeline row.  A short foreground capture is degraded
    # evidence, not permission to promote recent input into CurrentInput.
    # Recent input remains observable below and can still be retrieved through
    # an explicitly grounded lane, but it is not sent as the generation basis.
    effective = foreground or compact_whitespace(request.selected_text)
    augmented = False
    effective = compact_whitespace(effective)[-1200:]
    source = _active_rag_context_source(request)
    if not foreground and effective:
        source = "selected_text_fallback"
    return effective, source, {
        "foregroundContextChars": len(foreground),
        "effectiveContextChars": len(effective),
        "timelineRecentInputChars": len(recent),
        "augmentedWithTimelineRecentInput": augmented,
        "timelineRecentInputUsedForGeneration": False,
        "contextPolicy": "foreground_first",
    }


def _recent_context_overlap(recent: str, foreground: str) -> int:
    maximum = min(len(recent), len(foreground), 120)
    for width in range(maximum, 7, -1):
        if recent.endswith(foreground[:width]):
            return width
    return 0


def _merge_evidence(
    primary: tuple[ActiveRagEvidence, ...],
    secondary: tuple[ActiveRagEvidence, ...],
) -> tuple[ActiveRagEvidence, ...]:
    result: list[ActiveRagEvidence] = []
    seen: set[str] = set()
    for item in (*primary, *secondary):
        key = item.evidence_id or f"{item.source_lane}:{compact_whitespace(item.text).lower()}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _deepseek_evidence_pack(
    *,
    request: ActiveRagStartRequest,
    evidence: tuple[ActiveRagEvidence, ...],
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    resolved_query = _resolved_active_rag_request_text(request)
    for item in (*request.evidence_pack, *(_evidence_payload(evidence_item) for evidence_item in evidence[:10])):
        if not isinstance(item, dict):
            continue
        if _evidence_pack_item_is_context_only(item) or _evidence_pack_item_echoes_request(item, resolved_query):
            continue
        key = compact_whitespace(
            "|".join(
                str(item.get(field) or "")
                for field in ("sourceType", "sourceLane", "title", "text", "evidencePreview", "summary")
            )
        ).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 12:
            break
    return tuple(result)


def _session_payload(session: ActiveRagSession) -> dict[str, object]:
    ready = session.status == "ready"
    elapsed_ms = max(0, now_ms() - session.created_at_ms)
    poll_after_ms = _active_rag_poll_after_ms(status=session.status, elapsed_ms=elapsed_ms)
    candidates = [
        _active_rag_display_candidate_payload(item, session=session, index=index)
        for index, item in enumerate(session.candidates, start=1)
    ]
    if session.status == "pending" and not candidates:
        candidates = [_active_rag_thinking_candidate_payload(session)]
    if session.status == "error" and not candidates:
        candidates = [_active_rag_error_candidate_payload(session)]
    grounding_evidence = _grounding_evidence(session.evidence)
    return {
        "schemaVersion": ACTIVE_RAG_SERVICE_SCHEMA_VERSION,
        "sessionId": session.session_id,
        "status": session.status,
        "thinkingRow": session.status == "pending",
        "uiMode": ACTIVE_RAG_MODE,
        "keyPolicy": active_rag_key_policy(ready=ready),
        "selectedTextHash": session.request.selected_text_hash,
        "frontendRevision": session.request.frontend_revision,
        "selectionEpoch": session.request.selection_epoch,
        "panelSessionId": session.request.panel_session_id,
        "frontAppBundleId": session.request.front_app_bundle_id,
        "placement": session.request.placement,
        "intent": session.request.intent,
        "evidenceCount": len(grounding_evidence),
        "candidateCount": len(session.candidates),
        "candidates": candidates,
        "evidence": [_redacted_evidence_payload(item) for item in grounding_evidence[:8]],
        "diagnostics": dict(session.diagnostics),
        "traceEvents": list(session.trace_events),
        "error": session.error,
        "createdAtMs": session.created_at_ms,
        "updatedAtMs": session.updated_at_ms,
        "elapsedMs": elapsed_ms,
        "pollAfterMs": poll_after_ms,
    }


def _active_rag_poll_after_ms(*, status: str, elapsed_ms: int) -> int:
    if status != "pending":
        return 0
    if elapsed_ms < 1_000:
        return 180
    if elapsed_ms < 6_000:
        return 360
    if elapsed_ms < 15_000:
        return 700
    return 1_000


def _should_force_visible_fallback(session: ActiveRagSession) -> bool:
    elapsed_ms = max(0, now_ms() - session.created_at_ms)
    request_budget = max(100, int(session.request.latency_budget_ms or ACTIVE_RAG_VISIBLE_READY_TIMEOUT_MS))
    visible_budget = min(ACTIVE_RAG_VISIBLE_READY_TIMEOUT_MS, max(1_200, request_budget))
    return elapsed_ms >= visible_budget


def _remote_completion_budget_ms(request: ActiveRagStartRequest) -> int:
    request_budget = max(100, int(request.latency_budget_ms or ACTIVE_RAG_VISIBLE_READY_TIMEOUT_MS))
    return min(ACTIVE_RAG_VISIBLE_READY_TIMEOUT_MS, max(1_200, request_budget))


def _remote_active_rag_route(
    provider: object | None,
    *,
    request: ActiveRagStartRequest,
) -> dict[str, object]:
    request_allowed = request.remote_model_allowed is not False
    provider_available = provider is not None
    credentials_configured = _provider_credentials_configured(provider)
    scene_enabled = True
    scene_reason = ""
    try:
        assert_deepseek_scene_allowed("active_rag")
    except RuntimeError as exc:
        scene_enabled = False
        scene_reason = str(exc)
    gates = {
        "explicitActiveRagOnly": True,
        "requestAllowsRemoteModel": request_allowed,
        "sceneEnvEnabled": scene_enabled,
        "providerAvailable": provider_available,
        "credentialsConfigured": credentials_configured,
    }
    skip_reason = ""
    if not request_allowed:
        skip_reason = request.remote_model_skip_reason or "settings_remote_model_disabled"
    elif not provider_available:
        skip_reason = "provider_unavailable"
    elif not scene_enabled:
        skip_reason = "scene_flag_disabled"
    elif not credentials_configured:
        skip_reason = "credentials_missing"
    return {
        "schemaVersion": ACTIVE_RAG_ROUTE_STATUS_SCHEMA_VERSION,
        "route": "explicit_active_rag_deepseek",
        "provider": "deepseek",
        "model": _provider_model(provider),
        "ready": all(gates.values()),
        "attempted": False,
        "skipReason": skip_reason,
        "reason": scene_reason if not scene_enabled else "",
        "gates": gates,
        "managementGates": dict(request.remote_model_gates),
        "stream": True,
        "passivePostCommitRemoteAllowed": False,
    }


def _initial_session_diagnostics(
    request: ActiveRagStartRequest,
    *,
    completion_provider: object | None,
) -> dict[str, object]:
    route = _remote_active_rag_route(completion_provider, request=request)
    context_text = request.context or request.surrounding_before
    context_fingerprint = text_fingerprint(context_text)
    selected_fingerprint = text_fingerprint(request.selected_text)
    capture_warnings = _capture_validation_warnings(request, context_text=context_text)
    return {
        "schemaVersion": "rag-ime.active-rag-diagnostics.v1",
        "privacy": {"rawTextIncluded": False, "hashAlgorithm": "sha256-16"},
        "requestCapture": {
            "contextSource": _active_rag_context_source(request),
            "selectedText": text_fingerprint(request.selected_text),
            "currentContext": text_fingerprint(request.context),
            "surroundingBefore": text_fingerprint(request.surrounding_before),
            "surroundingAfter": text_fingerprint(request.surrounding_after),
            "providedEvidenceCount": len(request.evidence_pack),
            "frontendContextChars": request.frontend_context_chars,
            "frontendContextHash": request.frontend_context_hash,
            "captureWarnings": capture_warnings,
        },
        "route": route,
        "contextInjection": {
            "applied": False,
            "source": _active_rag_context_source(request),
            "contextChars": context_fingerprint["chars"],
            "contextHash": stable_text_hash(context_text) if context_text else "",
            "selectedTextChars": selected_fingerprint["chars"],
            "selectedTextHash": request.selected_text_hash,
            "warnings": ["model_request_not_built", *capture_warnings],
        },
        "retrieval": {
            "called": False,
            "attempted": False,
            "retrievedCount": 0,
            "evidenceCount": 0,
            "lanes": {},
            "elapsedMs": 0.0,
            "requestEvidenceCount": len(request.evidence_pack),
        },
        "remoteModel": {
            "requested": request.remote_model_allowed is True,
            "allowed": bool(route["ready"]),
            "provider": route["provider"],
            "model": route["model"],
            "skipReason": route["skipReason"],
            "elapsedMs": 0.0,
        },
        "generation": {"displayedCandidateCount": 0},
    }


def _active_rag_context_source(request: ActiveRagStartRequest) -> str:
    if request.context_source:
        return request.context_source
    sources: list[str] = []
    if request.context:
        sources.append("currentContext")
    if request.surrounding_before:
        sources.append("surroundingBefore")
    if request.surrounding_after:
        sources.append("surroundingAfter")
    if request.selected_text:
        sources.append("selectedText")
    if request.evidence_pack:
        sources.append("requestEvidencePack")
    return "+".join(sources) or "none"


def _capture_validation_warnings(request: ActiveRagStartRequest, *, context_text: str) -> list[str]:
    warnings: list[str] = []
    if request.frontend_context_chars and request.frontend_context_chars != len(context_text):
        warnings.append("frontend_context_chars_mismatch")
    if request.frontend_context_hash and request.frontend_context_hash != stable_text_hash(context_text):
        warnings.append("frontend_context_hash_mismatch")
    if request.frontend_selected_text_chars and request.frontend_selected_text_chars != len(request.selected_text):
        warnings.append("frontend_selected_text_chars_mismatch")
    return warnings


def _provider_model(provider: object | None) -> str:
    config = getattr(provider, "config", None)
    model = getattr(config, "model", "") if config is not None else ""
    return compact_whitespace(str(model)) or ("test-or-custom-provider" if provider is not None else "")


def _provider_credentials_configured(provider: object | None) -> bool:
    if provider is None:
        return False
    config = getattr(provider, "config", None)
    if config is None or not hasattr(config, "api_key"):
        return True
    return bool(compact_whitespace(str(getattr(config, "api_key", ""))))


def _candidate_source_counts(candidates: tuple[ActiveRagCandidate, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in candidates:
        key = item.source_lane or item.source_type or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _trace_event(name: str, **fields: object) -> dict[str, object]:
    return {"name": name, "atMs": now_ms(), "fields": fields}


def _append_trace_event(session: ActiveRagSession, name: str, **fields: object) -> None:
    session.trace_events.append(_trace_event(name, **fields))


def _safe_failure_reason(error: BaseException) -> str:
    message = compact_whitespace(str(error))[:240]
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED_SECRET]", message)
    message = re.sub(r"(?:/Users/|/Volumes/|/var/folders/)[^\s，。；;]+", "[REDACTED_PATH]", message)
    return message or type(error).__name__


def _active_rag_thinking_candidate_payload(session: ActiveRagSession) -> dict[str, object]:
    waiting_ms = max(0, now_ms() - int(session.created_at_ms))
    suffix = thinking_animation_suffix(waiting_ms)
    metadata = {
        "activeRag": True,
        "activeRagThinking": True,
        "activeRagSessionId": session.session_id,
        "selectedTextHash": session.request.selected_text_hash,
        "frontendRevision": session.request.frontend_revision,
        "selectionEpoch": session.request.selection_epoch,
        "panelSessionId": session.request.panel_session_id,
        "frontAppBundleId": session.request.front_app_bundle_id,
        "candidateOrdinal": 0,
        "visibleLabel": "",
        "animated": True,
        "animationFrame": thinking_animation_frame(waiting_ms),
        "waitingMs": waiting_ms,
    }
    return {
        "candidateId": f"{session.session_id}:thinking",
        "label": "",
        "visibleLabel": "",
        "selectionKey": None,
        "selectionRank": 0,
        "candidateOrdinal": 0,
        "candidateStableId": f"{session.session_id}:thinking",
        "snapshotId": session.session_id,
        "snapshotGeneration": 1,
        "text": f"正在生成{suffix}",
        "insertText": "",
        "sourceType": "status",
        "sourceLane": "active_rag_status",
        "selectionAction": "none",
        "sourceIndex": 0,
        "comment": "active_rag",
        "badge": "查忆",
        "sourceBadge": "查忆",
        "colorToken": "statusGray",
        "sourceStability": "fresh",
        "hardContextAnchor": "",
        "queryAnchor": "",
        "displayAnchor": "",
        "expiresAtMs": 0,
        "minVisibleUntilMs": 0,
        "evidencePreview": "",
        "expandedEvidence": "",
        "suggestionId": "",
        "memoryId": "",
        "sourceEventId": None,
        "rimeIndex": None,
        "displayLayout": "status_row",
        "displayLane": "active_rag_status",
        "group": "status",
        "groupLabel": "状态",
        "isSelectable": False,
        "isStatus": True,
        "metadata": metadata,
    }


def _active_rag_error_candidate_payload(session: ActiveRagSession) -> dict[str, object]:
    metadata = {
        "activeRag": True,
        "activeRagError": True,
        "activeRagSessionId": session.session_id,
        "selectedTextHash": session.request.selected_text_hash,
        "frontendRevision": session.request.frontend_revision,
        "selectionEpoch": session.request.selection_epoch,
        "panelSessionId": session.request.panel_session_id,
        "frontAppBundleId": session.request.front_app_bundle_id,
        "candidateOrdinal": 0,
        "visibleLabel": "",
        "error": session.error,
    }
    return {
        "candidateId": f"{session.session_id}:error",
        "label": "",
        "visibleLabel": "",
        "selectionKey": None,
        "selectionRank": 0,
        "candidateOrdinal": 0,
        "candidateStableId": f"{session.session_id}:error",
        "snapshotId": session.session_id,
        "snapshotGeneration": 1,
        "text": "生成失败，请重试",
        "insertText": "",
        "sourceType": "status",
        "sourceLane": "active_rag_status",
        "selectionAction": "none",
        "sourceIndex": 0,
        "comment": "active_rag_error",
        "badge": "查忆",
        "sourceBadge": "查忆",
        "colorToken": "statusGray",
        "sourceStability": "fresh",
        "hardContextAnchor": "",
        "queryAnchor": "",
        "displayAnchor": "",
        "expiresAtMs": 0,
        "minVisibleUntilMs": 0,
        "evidencePreview": "",
        "expandedEvidence": "",
        "suggestionId": "",
        "memoryId": "",
        "sourceEventId": None,
        "rimeIndex": None,
        "displayLayout": "status_row",
        "displayLane": "active_rag_status",
        "group": "status",
        "groupLabel": "状态",
        "isSelectable": False,
        "isStatus": True,
        "metadata": metadata,
    }


def _active_rag_display_candidate_payload(
    item: ActiveRagCandidate,
    *,
    session: ActiveRagSession,
    index: int,
) -> dict[str, object]:
    label = str(index % 10 or 0)
    metadata = {
        **dict(item.metadata),
        "activeRag": True,
        "activeRagSessionId": session.session_id,
        "sourceLane": item.source_lane,
        "selectedTextHash": session.request.selected_text_hash,
        "frontendRevision": session.request.frontend_revision,
        "selectionEpoch": session.request.selection_epoch,
        "panelSessionId": session.request.panel_session_id,
        "frontAppBundleId": session.request.front_app_bundle_id,
        "compositionHash": "",
        "committedContextHash": "",
        "candidateOrdinal": index,
        "visibleLabel": label,
        "sourceBadge": "模" if item.source_type == "model" else "忆",
        # A streaming candidate changes text several times before it is final.
        # Keep its UI identity tied to the session slot so AppKit can update the
        # row in place instead of treating every delta as a different choice.
        "candidateStableId": f"{session.session_id}:result:{index}",
        "placement": session.request.placement,
        "intent": session.request.intent,
    }
    return {
        "candidateId": item.candidate_id,
        "label": label,
        "visibleLabel": label,
        "selectionKey": label,
        "selectionRank": index,
        "candidateOrdinal": index,
        "candidateStableId": metadata["candidateStableId"],
        "snapshotId": session.session_id,
        "snapshotGeneration": 1,
        "text": item.text,
        "insertText": item.insert_text,
        "sourceType": item.source_type,
        "sourceLane": item.source_lane,
        "selectionAction": "commit_side_candidate",
        "sourceIndex": index - 1,
        "comment": item.source_lane,
        "badge": metadata["sourceBadge"],
        "sourceBadge": metadata["sourceBadge"],
        "colorToken": "modelBlue" if item.source_type == "model" else "memoryPurple",
        "sourceStability": "fresh",
        "hardContextAnchor": "",
        "queryAnchor": "",
        "displayAnchor": "",
        "expiresAtMs": 0,
        "minVisibleUntilMs": 0,
        "evidencePreview": "",
        "expandedEvidence": "",
        "suggestionId": item.candidate_id,
        "memoryId": str(item.metadata.get("memoryId") or item.candidate_id),
        "sourceEventId": None,
        "rimeIndex": None,
        "displayLayout": "block",
        "displayLane": item.source_lane or "active_rag",
        "group": "prediction",
        "groupLabel": "预测",
        "isSelectable": True,
        "isStatus": False,
        "metadata": metadata,
    }


def _frame_from_request(request: ActiveRagStartRequest) -> ActiveRagFrame:
    return ActiveRagFrame(
        selected_text=_resolved_active_rag_request_text(request),
        selected_text_hash=request.selected_text_hash,
        frontend_revision=int(request.frontend_revision),
        selection_epoch=int(request.selection_epoch),
        panel_session_id=request.panel_session_id,
        front_app_bundle_id=request.front_app_bundle_id,
        surrounding_before=request.surrounding_before,
        surrounding_after=request.surrounding_after,
        intent=request.intent,
        placement=request.placement,
        project=request.project,
        app=request.app or request.front_app_bundle_id,
        max_candidates=request.max_candidates,
    )


def _evidence_from_pack(pack: tuple[dict[str, object], ...]) -> tuple[ActiveRagEvidence, ...]:
    result: list[ActiveRagEvidence] = []
    for index, item in enumerate(pack, start=1):
        hints = item.get("surfaceHints") if isinstance(item, dict) else None
        text = ""
        if isinstance(hints, list):
            text = compact_whitespace(str(hints[0] if hints else ""))
        if not text and isinstance(item, dict):
            text = compact_whitespace(str(item.get("text") or item.get("candidateText") or ""))
        if not text:
            continue
        tags = item.get("tags") if isinstance(item, dict) else ()
        result.append(
            ActiveRagEvidence(
                evidence_id=f"pack:{index}",
                text=text,
                source_type="rag",
                source_lane="evidence_pack",
                tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                metadata={
                    "source": "evidence_pack",
                    "surfaceHints": [str(value) for value in hints if compact_whitespace(str(value))]
                    if isinstance(hints, list)
                    else [],
                    "title": compact_whitespace(str(item.get("title") or "")) if isinstance(item, dict) else "",
                    "summary": compact_whitespace(str(item.get("summary") or item.get("evidencePreview") or ""))
                    if isinstance(item, dict)
                    else "",
                },
            )
        )
    return tuple(result)


def _evidence_payload(evidence: ActiveRagEvidence) -> dict[str, object]:
    metadata = dict(evidence.metadata or {})
    surface_hints = metadata.get("surfaceHints") if isinstance(metadata.get("surfaceHints"), list) else []
    return {
        "id": evidence.evidence_id,
        "text": evidence.text,
        "sourceType": compact_whitespace(str(metadata.get("sourceType") or evidence.source_type)),
        "sourceLane": evidence.source_lane,
        "title": compact_whitespace(str(metadata.get("title") or metadata.get("bookTitle") or "")),
        "evidencePreview": evidence.preview or compact_whitespace(str(metadata.get("summary") or "")),
        "surfaceHints": [str(item) for item in surface_hints if compact_whitespace(str(item))][:8],
        "tags": list(evidence.tags),
        "bookIds": list(evidence.book_ids),
        "sourceEventIds": list(evidence.evidence_event_ids),
    }


def _redacted_evidence_payload(evidence: ActiveRagEvidence) -> dict[str, object]:
    return {
        "evidenceId": evidence.evidence_id,
        "sourceType": evidence.source_type,
        "sourceLane": evidence.source_lane,
        "score": evidence.score,
        "confidence": evidence.confidence,
        "tags": list(evidence.tags[:6]),
        "hasPreview": bool(evidence.preview),
    }


def _merge_candidates(
    local_candidates: tuple[ActiveRagCandidate, ...],
    deepseek_candidates: tuple[ActiveRagCandidate, ...],
    *,
    max_candidates: int,
    prefer_deepseek: bool = False,
) -> tuple[ActiveRagCandidate, ...]:
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    ordered = (*deepseek_candidates, *local_candidates) if prefer_deepseek else (*local_candidates, *deepseek_candidates)
    for candidate in ordered:
        key = compact_whitespace(candidate.text).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= max(1, int(max_candidates)):
            break
    return tuple(result)
