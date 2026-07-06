from __future__ import annotations

from typing import Literal

from .text_utils import compact_whitespace, stable_text_hash


ForegroundTextSource = Literal[
    "unavailable",
    "rime_composition",
    "ime_commit_ledger",
    "text_input_client",
    "accessibility",
    "clipboard_fallback",
    "manual_clipboard",
]

CommittedContextSource = Literal["ime_commit_ledger", "frontend_snapshot", "unknown"]


def source_confidence(source: str) -> float:
    normalized = compact_whitespace(source)
    if normalized == "rime_composition":
        return 1.0
    if normalized == "ime_commit_ledger":
        return 0.65
    if normalized == "text_input_client":
        return 0.8
    if normalized == "accessibility":
        return 0.7
    if normalized in {"clipboard_fallback", "manual_clipboard"}:
        return 0.55
    return 0.0


def committed_source(*, committed_context: str, commit_text_preview: str) -> CommittedContextSource:
    if compact_whitespace(committed_context) or compact_whitespace(commit_text_preview):
        return "ime_commit_ledger"
    return "unknown"


def selected_text_identity(text: str) -> tuple[str, int]:
    normalized = compact_whitespace(text)
    return (stable_text_hash(normalized) if normalized else "", len(normalized))

