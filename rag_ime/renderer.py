from __future__ import annotations

from .models import AgentContextInjection, InputSuggestion
from .text_utils import truncate_text, wrap_block


def render_candidate_bar(suggestions: list[InputSuggestion], *, max_items: int = 5) -> str:
    parts: list[str] = []
    for index, suggestion in enumerate(suggestions[:max_items], start=1):
        label = suggestion.suggestion_type.replace("_", "-")
        parts.append(f"{index}. {suggestion.surface_text} [{label}]")
    return "  ".join(parts) if parts else "(no RAG candidates)"


def render_evidence_preview(suggestion: InputSuggestion) -> str:
    actions = " / ".join(suggestion.actions)
    return "\n".join(
        [
            f"candidate: {suggestion.surface_text}",
            f"type: {suggestion.suggestion_type}",
            f"confidence: {suggestion.confidence:.2f}",
            f"preview: {truncate_text(suggestion.evidence_preview, 180)}",
            f"actions: {actions}",
        ]
    )


def render_expanded_evidence(suggestion: InputSuggestion) -> str:
    body = suggestion.expanded_evidence or suggestion.evidence_preview
    return "\n".join(
        [
            f"# {suggestion.surface_text}",
            f"- suggestion_id: {suggestion.suggestion_id}",
            f"- source_event_id: {suggestion.source_event_id or '(unknown)'}",
            f"- memory_id: {suggestion.metadata.get('memory_id', '(unknown)')}",
            "",
            wrap_block(body, width=88),
        ]
    ).strip()


def render_agent_injection(injection: AgentContextInjection) -> str:
    return injection.block.strip()


def render_terminal_panel(
    *,
    title: str,
    current_input: str,
    recent_context: str,
    suggestions: list[InputSuggestion],
    expanded_index: int = 0,
) -> str:
    lines = [
        f"== {title} ==",
        f"recent_context: {recent_context or '(empty)'}",
        f"current_input: {current_input}",
        "",
        "candidate_bar:",
        render_candidate_bar(suggestions),
    ]
    if suggestions:
        selected = suggestions[min(max(expanded_index, 0), len(suggestions) - 1)]
        lines.extend(["", "evidence_preview:", render_evidence_preview(selected), "", "expanded_evidence:", render_expanded_evidence(selected)])
    return "\n".join(lines)
