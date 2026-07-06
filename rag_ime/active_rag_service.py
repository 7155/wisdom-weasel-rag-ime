from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from .active_rag_candidate_compiler import ActiveRagCandidate, compile_active_rag_candidates
from .deepseek_completion import DeepSeekCompletionRequest
from .runtime_flags import assert_deepseek_scene_allowed
from .text_utils import compact_whitespace, now_ms, stable_text_hash


ACTIVE_RAG_SERVICE_SCHEMA_VERSION = "rag-ime.active-rag-service.v1"


@dataclass(frozen=True)
class ActiveRagStartRequest:
    selected_text: str
    selected_text_hash: str
    frontend_revision: int
    selection_epoch: int
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
    candidates: tuple[ActiveRagCandidate, ...] = ()
    error: str = ""
    created_at_ms: int = field(default_factory=now_ms)
    updated_at_ms: int = field(default_factory=now_ms)


class ActiveRagService:
    def __init__(self, *, completion_provider=None):
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
            return _session_payload(session) if session is not None else {"sessionId": session_id, "status": "missing"}

    def accept(
        self,
        *,
        session_id: str,
        candidate_id: str,
        selected_text_hash: str,
        frontend_revision: int,
        selection_epoch: int,
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
            candidate = next((item for item in session.candidates if item.candidate_id == candidate_id), None)
            if candidate is None:
                return {"ok": False, "reason": "missing_candidate"}
            return {
                "ok": True,
                "sessionId": session_id,
                "candidateId": candidate_id,
                "insertText": candidate.insert_text,
            }

    def _run_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return
        try:
            assert_deepseek_scene_allowed("active_rag")
            provider = self.completion_provider
            if provider is None:
                candidates: tuple[ActiveRagCandidate, ...] = ()
            else:
                request = DeepSeekCompletionRequest(
                    scene="active_rag",
                    current_context=session.request.context,
                    selected_text=session.request.selected_text,
                    evidence_pack=session.request.evidence_pack,
                    max_candidates=session.request.max_candidates,
                    latency_budget_ms=2500,
                )
                candidates = compile_active_rag_candidates(
                    provider.stream_candidates(request),
                    selected_text=session.request.selected_text,
                    max_candidates=session.request.max_candidates,
                )
            with self._lock:
                current = self._sessions.get(session_id)
                if current is None or current.status != "pending":
                    return
                current.candidates = candidates
                current.status = "ready"
                current.updated_at_ms = now_ms()
        except RuntimeError as exc:
            with self._lock:
                current = self._sessions.get(session_id)
                if current is not None and current.status == "pending":
                    current.status = "error"
                    current.error = str(exc)
                    current.updated_at_ms = now_ms()

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
    return {
        "schemaVersion": ACTIVE_RAG_SERVICE_SCHEMA_VERSION,
        "sessionId": session.session_id,
        "status": session.status,
        "thinkingRow": session.status == "pending",
        "selectedTextHash": session.request.selected_text_hash,
        "frontendRevision": session.request.frontend_revision,
        "selectionEpoch": session.request.selection_epoch,
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
        "error": session.error,
        "createdAtMs": session.created_at_ms,
        "updatedAtMs": session.updated_at_ms,
    }
