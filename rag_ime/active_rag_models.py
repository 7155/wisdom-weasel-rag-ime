from __future__ import annotations

from dataclasses import dataclass, field

from .text_utils import compact_whitespace, stable_text_hash


ACTIVE_RAG_MODE = "active_rag_assist"
ACTIVE_RAG_SCHEMA_VERSION = "rag-ime.active-rag.v1"


@dataclass(frozen=True)
class ActiveRagFrame:
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
    project: str = "wisdom-weasel-rag-ime"
    app: str = ""
    max_candidates: int = 5

    @classmethod
    def from_text(
        cls,
        selected_text: str,
        *,
        frontend_revision: int = 1,
        selection_epoch: int = 1,
        panel_session_id: str = "",
        front_app_bundle_id: str = "",
        surrounding_before: str = "",
        surrounding_after: str = "",
        intent: str = "rewrite",
        placement: str = "replace_selection",
        project: str = "wisdom-weasel-rag-ime",
        app: str = "",
        max_candidates: int = 5,
    ) -> "ActiveRagFrame":
        selected = compact_whitespace(selected_text)
        return cls(
            selected_text=selected,
            selected_text_hash=stable_text_hash(selected),
            frontend_revision=frontend_revision,
            selection_epoch=selection_epoch,
            panel_session_id=panel_session_id,
            front_app_bundle_id=front_app_bundle_id,
            surrounding_before=surrounding_before,
            surrounding_after=surrounding_after,
            intent=intent,
            placement=placement,
            project=project,
            app=app or front_app_bundle_id,
            max_candidates=max_candidates,
        )


@dataclass(frozen=True)
class ActiveRagEvidence:
    evidence_id: str
    text: str
    source_type: str
    source_lane: str
    score: float = 0.0
    confidence: float = 0.0
    tags: tuple[str, ...] = ()
    memory_ids: tuple[str, ...] = ()
    atom_ids: tuple[str, ...] = ()
    book_ids: tuple[str, ...] = ()
    evidence_event_ids: tuple[int, ...] = ()
    preview: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


def active_rag_key_policy(*, ready: bool) -> dict[str, object]:
    return {
        "uiMode": ACTIVE_RAG_MODE,
        "ready": ready,
        "numberKeys": "select_candidate_when_ready_else_noop",
        "optionNumber": "select_candidate_by_ordinal",
        "tab": "accept_top_when_ready",
        "escape": "cancel_active_rag",
        "enter": "accept_highlighted_when_ready",
        "thinkingRowSelectable": False,
    }
