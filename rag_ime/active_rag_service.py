from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from .active_rag_candidate_compiler import (
    ActiveRagCandidate,
    compile_active_rag_candidates,
    compile_active_rag_candidates_from_evidence,
)
from .active_rag_models import ActiveRagEvidence, ActiveRagFrame, ACTIVE_RAG_MODE, active_rag_key_policy
from .active_rag_retriever import retrieve_active_rag_evidence
from .deepseek_completion import DeepSeekCompletionRequest, fallback_deepseek_completion_candidates
from .local_sqlite_core import LocalSqliteCoreClient
from .prediction_status import thinking_animation_frame, thinking_animation_suffix
from .runtime_flags import assert_deepseek_scene_allowed
from .smart_rag_context_packet import build_active_rag_context_packet
from .text_utils import compact_whitespace, now_ms, stable_text_hash
from .timeline_context import timeline_evidence_pack_from_core


ACTIVE_RAG_SERVICE_SCHEMA_VERSION = "rag-ime.active-rag-service.v1"
ACTIVE_RAG_VISIBLE_READY_TIMEOUT_MS = 15_000


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
    evidence_pack: tuple[dict[str, object], ...] = ()
    project: str = "wisdom-weasel-rag-ime"
    app: str = ""
    max_candidates: int = 1
    max_chars: int = 18
    latency_budget_ms: int = 15000


@dataclass
class ActiveRagSession:
    session_id: str
    request: ActiveRagStartRequest
    status: str = "pending"
    evidence: tuple[ActiveRagEvidence, ...] = ()
    candidates: tuple[ActiveRagCandidate, ...] = ()
    error: str = ""
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

    def start(self, request: ActiveRagStartRequest) -> dict[str, object]:
        _validate_selected_text_hash(request)
        session = ActiveRagSession(session_id=f"active-rag:{uuid.uuid4().hex[:16]}", request=request)
        with self._lock:
            self._drop_stale_sessions_locked(request)
            self._sessions[session.session_id] = session
        thread = threading.Thread(target=self._run_session, args=(session.session_id,), daemon=True)
        thread.start()
        return self.status(session.session_id)

    def preview(self, request: ActiveRagStartRequest, *, local_only: bool = True) -> dict[str, object]:
        _validate_selected_text_hash(request)
        evidence = self._retrieve_local_evidence(request)
        local_candidates = compile_active_rag_candidates_from_evidence(
            evidence,
            frame=_frame_from_request(request),
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
        )
        if not local_only:
            deepseek_candidates = self._deepseek_candidates(request, evidence=evidence)
            candidates = (
                deepseek_candidates
                if _remote_active_rag_model_enabled(self.completion_provider)
                else _merge_candidates(
                    local_candidates,
                    deepseek_candidates,
                    max_candidates=request.max_candidates,
                    prefer_deepseek=True,
                )
            )
        else:
            candidates = local_candidates
        session = ActiveRagSession(
            session_id="active-rag:preview",
            request=request,
            status="ready",
            evidence=evidence,
            candidates=candidates,
        )
        return {"ok": True, "dryRun": True, **_session_payload(session)}

    def status(self, session_id: str) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {"schemaVersion": ACTIVE_RAG_SERVICE_SCHEMA_VERSION, "sessionId": session_id, "status": "missing"}
            if session.status == "pending" and _should_force_visible_fallback(session):
                self._force_visible_fallback_locked(session, reason="visible_timeout")
            return _session_payload(session)

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
            evidence = self._retrieve_local_evidence(session.request)
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current.status != "pending":
                    return
                current.evidence = evidence
                current.updated_at_ms = now_ms()
            remote_model_enabled = _remote_active_rag_model_enabled(self.completion_provider)
            if remote_model_enabled:
                candidates = self._deepseek_candidates(session.request, evidence=evidence)
            else:
                candidates = self._local_candidates(session.request, evidence=evidence)
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current.status != "pending":
                    return
                current.evidence = evidence
                if remote_model_enabled and not candidates:
                    candidates = self._fallback_candidates(session.request, evidence=evidence, reason="empty_remote_content")
                current.candidates = candidates
                self._record_shown_feedback(session=current, candidates=candidates)
                if candidates or not remote_model_enabled:
                    current.status = "ready"
                else:
                    current.status = "error"
                    current.error = "DeepSeek returned no governed candidates"
                current.updated_at_ms = now_ms()
        except Exception as exc:
            with self._lock:
                current = self._sessions.get(session_id)
                if current is not None and current.status == "pending":
                    self._force_visible_fallback_locked(current, reason=type(exc).__name__)
                    if current.status == "error":
                        current.error = str(exc)
                    current.updated_at_ms = now_ms()

    def _retrieve_local_evidence(self, request: ActiveRagStartRequest) -> tuple[ActiveRagEvidence, ...]:
        evidence: tuple[ActiveRagEvidence, ...] = ()
        if self.core is not None:
            try:
                evidence = retrieve_active_rag_evidence(self.core, _frame_from_request(request))
            except Exception:
                evidence = ()
            evidence = _merge_evidence(evidence, _timeline_evidence_from_core(self.core, request))
        if evidence:
            return evidence
        return _evidence_from_pack(request.evidence_pack)

    def _deepseek_candidates(
        self,
        request: ActiveRagStartRequest,
        *,
        evidence: tuple[ActiveRagEvidence, ...],
    ) -> tuple[ActiveRagCandidate, ...]:
        provider = self.completion_provider
        if provider is None:
            return ()
        try:
            assert_deepseek_scene_allowed("active_rag")
        except RuntimeError:
            return ()
        completion_request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context=request.context,
            selected_text=request.selected_text,
            evidence_pack=_deepseek_evidence_pack(request=request, evidence=evidence),
            context_packet=build_active_rag_context_packet(
                scene="active_rag",
                current_context=request.context or request.surrounding_before,
                selected_text=request.selected_text,
                selected_text_hash=request.selected_text_hash,
                frontend_revision=request.frontend_revision,
                selection_epoch=request.selection_epoch,
                panel_session_id=request.panel_session_id,
                project=request.project,
                app=request.app or request.front_app_bundle_id,
                evidence=evidence,
                intent=request.intent,
                placement=request.placement,
                max_candidates=request.max_candidates,
                max_chars=request.max_chars,
                latency_budget_ms=request.latency_budget_ms,
                remote_model_allowed=True,
            ),
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
            latency_budget_ms=_remote_completion_budget_ms(request),
        )
        return compile_active_rag_candidates(
            provider.stream_candidates(completion_request),
            selected_text=request.selected_text,
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
        )

    def _fallback_candidates(
        self,
        request: ActiveRagStartRequest,
        *,
        evidence: tuple[ActiveRagEvidence, ...],
        reason: str,
    ) -> tuple[ActiveRagCandidate, ...]:
        completion_request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context=request.context or request.surrounding_before,
            selected_text=request.selected_text,
            evidence_pack=_deepseek_evidence_pack(request=request, evidence=evidence),
            context_packet=build_active_rag_context_packet(
                scene="active_rag",
                current_context=request.context or request.surrounding_before,
                selected_text=request.selected_text,
                selected_text_hash=request.selected_text_hash,
                frontend_revision=request.frontend_revision,
                selection_epoch=request.selection_epoch,
                panel_session_id=request.panel_session_id,
                project=request.project,
                app=request.app or request.front_app_bundle_id,
                evidence=evidence,
                intent=request.intent,
                placement=request.placement,
                max_candidates=request.max_candidates,
                max_chars=request.max_chars,
                latency_budget_ms=request.latency_budget_ms,
                remote_model_allowed=False,
            ),
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
            latency_budget_ms=request.latency_budget_ms,
        )
        return compile_active_rag_candidates(
            fallback_deepseek_completion_candidates(completion_request, fallback_reason=reason),
            selected_text=request.selected_text,
            max_candidates=request.max_candidates,
            max_chars=request.max_chars,
        )

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
        fallback_candidates = self._fallback_candidates(request, evidence=evidence, reason="remote_model_disabled")
        if fallback_candidates and _should_prefer_model_fallback(request, evidence=evidence):
            return fallback_candidates
        return local_candidates or fallback_candidates

    def _force_visible_fallback_locked(self, session: ActiveRagSession, *, reason: str) -> None:
        evidence = session.evidence or _evidence_from_pack(session.request.evidence_pack)
        candidates = self._fallback_candidates(session.request, evidence=evidence, reason=reason)
        if not candidates:
            candidates = compile_active_rag_candidates_from_evidence(
                evidence,
                frame=_frame_from_request(session.request),
                max_candidates=session.request.max_candidates,
                max_chars=session.request.max_chars,
            )
        session.evidence = evidence
        session.candidates = candidates
        self._record_shown_feedback(session=session, candidates=candidates)
        if candidates:
            session.status = "ready"
            session.error = f"DeepSeek fallback: {reason}"
        else:
            session.status = "error"
            session.error = f"DeepSeek returned no visible candidate: {reason}"
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


def _timeline_evidence_from_core(core: LocalSqliteCoreClient, request: ActiveRagStartRequest) -> tuple[ActiveRagEvidence, ...]:
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
        if source_type == "recent_input_context":
            text = summary
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
    for item in (*request.evidence_pack, *(_evidence_payload(evidence_item) for evidence_item in evidence[:10])):
        if not isinstance(item, dict):
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
        "evidenceCount": len(session.evidence),
        "candidateCount": len(session.candidates),
        "candidates": candidates,
        "evidence": [_redacted_evidence_payload(item) for item in session.evidence[:8]],
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


def _remote_active_rag_model_enabled(provider: object | None) -> bool:
    if provider is None:
        return False
    try:
        assert_deepseek_scene_allowed("active_rag")
    except RuntimeError:
        return False
    return True


def _should_prefer_model_fallback(
    request: ActiveRagStartRequest,
    *,
    evidence: tuple[ActiveRagEvidence, ...],
) -> bool:
    request_text = compact_whitespace(" ".join((request.context, request.surrounding_before, request.selected_text)))
    haystack = compact_whitespace(
        " ".join(
            (
                request_text,
                *(
                    compact_whitespace(
                        " ".join(
                            (
                                item.text,
                                item.preview,
                                str(item.metadata.get("title") or "") if isinstance(item.metadata, dict) else "",
                                str(item.metadata.get("summary") or "") if isinstance(item.metadata, dict) else "",
                            )
                        )
                    )
                    for item in evidence[:6]
                ),
            )
        )
    )
    if not haystack:
        return False
    problem_terms = ("不显示", "没显示", "无输出", "没输出", "消失", "重复", "卡顿", "只有一个框")
    generation_terms = ("生成", "预测", "候选", "按钮", "输出")
    if ("LLM" in request_text or "模型" in request_text) and any(term in request_text for term in (*problem_terms, *generation_terms)):
        return True
    if ("DeepSeek" in request_text or "DS" in request_text) and any(term in request_text for term in (*problem_terms, *generation_terms)):
        return True
    if "RAG" in request_text and any(term in request_text for term in ("命中", "检索", "上下文", "笔记本", "记忆")):
        return True
    if ("笔记本" in request_text or "Notebook" in request_text or "记忆" in request_text) and any(
        term in request_text for term in ("DeepSeek", "DS", "预测", "上下文")
    ):
        return True
    return False


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
        "text": f"DeepSeek 思考中{suffix}",
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
        "text": "DeepSeek 无有效候选",
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
        "sourceBadge": "生成" if item.source_type == "model" else "忆",
        "candidateStableId": f"active_rag:{stable_text_hash(item.text)}",
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
        selected_text=compact_whitespace(request.selected_text),
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
