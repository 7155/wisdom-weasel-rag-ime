from __future__ import annotations

import os
from typing import Protocol

from .text_utils import compact_whitespace


DEFAULT_HISTORY_CONTEXT_EVENTS = 6
DEFAULT_HISTORY_CONTEXT_CHARS = 420


class HistoryContextCore(Protocol):
    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        ...


def history_context_limits(env: dict[str, str] | None = None) -> tuple[int, int]:
    source = env or os.environ
    return (
        _int_env(source, "RAG_IME_HISTORY_CONTEXT_EVENTS", DEFAULT_HISTORY_CONTEXT_EVENTS),
        _int_env(source, "RAG_IME_HISTORY_CONTEXT_CHARS", DEFAULT_HISTORY_CONTEXT_CHARS),
    )


def build_prediction_context(
    core: object,
    *,
    explicit_recent_context: str = "",
    project: str = "",
    limit: int | None = None,
    max_chars: int | None = None,
) -> str:
    event_limit, char_limit = history_context_limits()
    if limit is not None:
        event_limit = limit
    if max_chars is not None:
        char_limit = max_chars

    explicit = compact_whitespace(explicit_recent_context)
    history = ""
    method = getattr(core, "recent_input_context", None)
    if callable(method) and event_limit > 0 and char_limit > 0:
        reserved = len(explicit) + (18 if explicit else 0)
        history_limit = max(80, char_limit - reserved) if char_limit > reserved else 0
        history = compact_whitespace(method(project=project, limit=event_limit, max_chars=history_limit))

    if history and explicit:
        merged = f"历史输入: {history} 当前上下文: {explicit}"
    elif history:
        merged = f"历史输入: {history}"
    else:
        merged = explicit
    return _tail_chars(compact_whitespace(merged), max(0, char_limit))


def _int_env(env: dict[str, str], name: str, fallback: int) -> int:
    try:
        value = int(env.get(name, ""))
    except ValueError:
        return fallback
    return value if value >= 0 else fallback


def _tail_chars(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
