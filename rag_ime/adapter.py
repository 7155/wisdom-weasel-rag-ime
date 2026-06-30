from __future__ import annotations

from dataclasses import dataclass

from .core_client import CoreClient
from .models import AgentContextInjection, InputEvent, InputSuggestion, MemoryAction
from .text_utils import now_ms


@dataclass(frozen=True)
class SuggestionRequest:
    current_input: str
    recent_context: str = ""
    project: str = "wisdom-weasel-rag-ime"
    top_k: int = 5


class InputMethodAdapter:
    """Input-method side adapter over the shared RAG/memory core."""

    def __init__(self, core: CoreClient, *, project: str = "wisdom-weasel-rag-ime"):
        self.core = core
        self.project = project

    def commit_text(
        self,
        text: str,
        *,
        recent_context: str = "",
        preedit: str = "",
        schema_id: str = "luna_pinyin",
        app: str = "manual",
        project: str | None = None,
        recording_enabled: bool = True,
        field_is_sensitive: bool = False,
        source: str = "manual_commit",
        candidate_rank: int | None = None,
        provider_name: str = "ime-adapter",
        tags: tuple[str, ...] = (),
    ) -> str:
        if not recording_enabled:
            return "skipped:recording_disabled"
        if field_is_sensitive:
            return "skipped:sensitive_field"
        event = InputEvent(
            event_id=None,
            created_at_ms=now_ms(),
            source=source,
            committed_text=text,
            recent_context=recent_context,
            preedit=preedit,
            schema_id=schema_id,
            app=app,
            project=project or self.project,
            candidate_rank=candidate_rank,
            provider_name=provider_name,
            tags=tags,
        )
        return self.core.record_event(event)

    def suggest(self, request: SuggestionRequest) -> list[InputSuggestion]:
        suggestions = self.core.suggest_for_input(
            current_input=request.current_input,
            recent_context=request.recent_context,
            project=request.project or self.project,
            top_k=request.top_k,
        )
        return [normalize_suggestion(item) for item in suggestions]

    def choose(self, suggestion: InputSuggestion, *, query: str = "") -> MemoryAction:
        return self._action(suggestion, "accepted", query=query)

    def skip(self, suggestion: InputSuggestion, *, query: str = "") -> MemoryAction:
        return self._action(suggestion, "skipped", query=query)

    def pin(self, suggestion: InputSuggestion, *, query: str = "") -> MemoryAction:
        return self._action(suggestion, "pin", query=query)

    def downrank(self, suggestion: InputSuggestion, *, query: str = "") -> MemoryAction:
        return self._action(suggestion, "downrank", query=query)

    def delete(self, suggestion: InputSuggestion, *, query: str = "") -> MemoryAction:
        return self._action(suggestion, "delete", query=query)

    def agent_context(self, *, query: str, project: str | None = None, top_k: int = 5) -> AgentContextInjection:
        return self.core.build_agent_context(project=project or self.project, query=query, top_k=top_k)

    def _action(self, suggestion: InputSuggestion, action_type: str, *, query: str) -> MemoryAction:
        memory_id = str(suggestion.metadata.get("memory_id") or suggestion.suggestion_id)
        action = MemoryAction(
            action_id=None,
            created_at_ms=now_ms(),
            memory_id=memory_id,
            action_type=action_type,
            query=query,
            suggestion_id=suggestion.suggestion_id,
            source_event_id=suggestion.source_event_id,
            metadata={"surface_text": suggestion.surface_text},
        )
        return self.core.apply_action(action)


def normalize_suggestion(suggestion: InputSuggestion) -> InputSuggestion:
    actions = suggestion.actions or ("commit", "expand", "pin", "downrank", "delete")
    return InputSuggestion(
        suggestion_id=suggestion.suggestion_id,
        surface_text=suggestion.surface_text.strip(),
        suggestion_type=suggestion.suggestion_type,
        source_event_id=suggestion.source_event_id,
        evidence_preview=suggestion.evidence_preview.strip(),
        confidence=max(0.0, min(1.0, suggestion.confidence)),
        actions=tuple(dict.fromkeys(actions)),
        expanded_evidence=suggestion.expanded_evidence.strip(),
        metadata=dict(suggestion.metadata),
    )
