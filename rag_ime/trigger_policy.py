from __future__ import annotations

from dataclasses import dataclass


BOUNDARY_CHARS = set("，。！？；,.!?;\n")
LONG_TEXT_APPS = {"editor", "notes", "docs", "chat", "ide", "terminal", "browser"}
SENSITIVE_APPS = {"password", "banking", "private_browser"}


@dataclass(frozen=True)
class TypingState:
    current_input: str
    recent_context: str = ""
    idle_ms: int = 0
    app_kind: str = "editor"
    explicit_request: bool = False
    recording_enabled: bool = True
    field_is_sensitive: bool = False


@dataclass(frozen=True)
class TriggerDecision:
    should_refresh: bool
    reason: str


def should_refresh_rag(state: TypingState) -> TriggerDecision:
    """Decide whether background RAG should refresh.

    The IME may update retrieval on every keystroke internally, but user-visible
    RAG candidates should appear only when there is enough signal and no privacy
    risk.
    """

    if not state.recording_enabled:
        return TriggerDecision(False, "disabled: recording is off")
    if state.field_is_sensitive or state.app_kind in SENSITIVE_APPS:
        return TriggerDecision(False, "disabled: sensitive field/app")
    if state.explicit_request:
        return TriggerDecision(True, "explicit request")

    current = state.current_input.strip()
    if not current:
        return TriggerDecision(False, "skip: empty input")
    if current[-1] in BOUNDARY_CHARS and len(current) >= 2:
        return TriggerDecision(True, "boundary punctuation")
    if state.idle_ms >= 300 and len(current) >= 4:
        return TriggerDecision(True, "idle threshold")
    if state.app_kind in LONG_TEXT_APPS and len(current) >= 6:
        return TriggerDecision(True, "long-text app threshold")
    return TriggerDecision(False, "skip: not enough semantic signal")
