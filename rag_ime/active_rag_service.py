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
from .deepseek_completion import DeepSeekCompletionRequest
from .local_sqlite_core import LocalSqliteCoreClient
from .runtime_flags import assert_deepseek_scene_allowed
from .text_utils import compact_whitespace, now_ms, stable_text_hash


ACTIVE_RAG_SERVICE_SCHEMA_VERSION = "rag-ime.active-rag-service.v1"


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
    max_candidates: int = 5


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
        candidates = compile_active_rag_candidates_from_evidence(
            evidence,
            frame=_frame_from_request(request),
            max_candidates=request.max_candidates,
        )
        if not local_only:
            deepseek_candidates = self._deepseek_candidates(request, evidence=evidence)
            candidates = _merge_candidates(candidates, deepseek_candidates, max_candidates=request.max_candidates)
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
            candidates = compile_active_rag_candidates_from_evidence(
                evidence,
                frame=_frame_from_request(session.request),
                max_candidates=session.request.max_candidates,
            )
            deepseek_candidates = self._deepseek_candidates(session.request, evidence=evidence)
            candidates = _merge_candidates(candidates, deepseek_candidates, max_candidates=session.request.max_candidates)
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current.status != "pending":
                    return
                current.evidence = evidence
                current.candidates = candidates
                self._record_shown_feedback(session=current, candidates=candidates)
                current.status = "ready"
                current.updated_at_ms = now_ms()
        except RuntimeError as exc:
            with self._lock:
                current = self._sessions.get(session_id)
                if current is not None and current.status == "pending":
                    current.status = "error"
                    current.error = str(exc)
                    current.updated_at_ms = now_ms()

    def _retrieve_local_evidence(self, request: ActiveRagStartRequest) -> tuple[ActiveRagEvidence, ...]:
        evidence: tuple[ActiveRagEvidence, ...] = ()
        if self.core is not None:
            try:
                evidence = retrieve_active_rag_evidence(self.core, _frame_from_request(request))
            except Exception:
                evidence = ()
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
            evidence_pack=request.evidence_pack or tuple(_evidence_payload(item) for item in evidence[:8]),
            max_candidates=request.max_candidates,
            latency_budget_ms=2500,
        )
        return compile_active_rag_candidates(
            provider.stream_candidates(completion_request),
            selected_text=request.selected_text,
            max_candidates=request.max_candidates,
        )

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


def _session_payload(session: ActiveRagSession) -> dict[str, object]:
    ready = session.status == "ready"
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
        "candidates": [
            {
                "candidateId": item.candidate_id,
                "text": item.text,
                "insertText": item.insert_text,
                "sourceType": item.source_type,
                "sourceLane": item.source_lane,
                "metadata": dict(item.metadata),
            }
            for item in session.candidates
        ],
        "evidence": [_redacted_evidence_payload(item) for item in session.evidence[:8]],
        "error": session.error,
        "createdAtMs": session.created_at_ms,
        "updatedAtMs": session.updated_at_ms,
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
                metadata={"source": "evidence_pack"},
            )
        )
    return tuple(result)


def _evidence_payload(evidence: ActiveRagEvidence) -> dict[str, object]:
    return {
        "id": evidence.evidence_id,
        "text": evidence.text,
        "sourceType": evidence.source_type,
        "sourceLane": evidence.source_lane,
        "tags": list(evidence.tags),
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
) -> tuple[ActiveRagCandidate, ...]:
    seen: set[str] = set()
    result: list[ActiveRagCandidate] = []
    for candidate in (*local_candidates, *deepseek_candidates):
        key = compact_whitespace(candidate.text).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= max(1, int(max_candidates)):
            break
    return tuple(result)
