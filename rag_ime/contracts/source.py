"""Candidate source visual contract for the v1 foreground IME path."""

from __future__ import annotations

SOURCE_MODEL = "model"
SOURCE_RAG = "rag"
SOURCE_MEMORY = "memory"
SOURCE_RIME = "rime"
SOURCE_RAW_ENGLISH = "raw_english"
SOURCE_STATUS = "status"

REALTIME_SIDE_SOURCE_TYPES = frozenset({SOURCE_MODEL, SOURCE_RAG, SOURCE_MEMORY})
RAG_MEMORY_SOURCE_TYPES = frozenset({SOURCE_RAG, SOURCE_MEMORY})
VISIBLE_SOURCE_TYPES = frozenset({SOURCE_MODEL, SOURCE_RAG, SOURCE_MEMORY, SOURCE_RIME})

SOURCE_BADGES = {
    SOURCE_RIME: "词",
    SOURCE_MODEL: "模",
    SOURCE_RAG: "查",
    SOURCE_MEMORY: "忆",
    SOURCE_RAW_ENGLISH: "input",
    SOURCE_STATUS: "查忆",
}
SOURCE_COLOR_TOKENS = {
    SOURCE_RIME: "rimeOrange",
    SOURCE_MODEL: "modelBlue",
    SOURCE_RAG: "ragTeal",
    SOURCE_MEMORY: "memoryPurple",
    SOURCE_RAW_ENGLISH: "rawGray",
    SOURCE_STATUS: "statusGray",
}


def source_badge_for(source_type: str) -> str:
    normalized = str(source_type or "")
    return SOURCE_BADGES.get(normalized, normalized)


def source_color_token_for(source_type: str) -> str:
    return SOURCE_COLOR_TOKENS.get(str(source_type or ""), "")
