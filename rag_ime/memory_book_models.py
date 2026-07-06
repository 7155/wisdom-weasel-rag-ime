from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MemoryBookType = Literal["daily", "topic", "project", "session"]


@dataclass(frozen=True)
class MemoryBook:
    book_id: str
    book_type: MemoryBookType
    book_key: str
    title: str
    summary: str
    tags: tuple[str, ...]
    surface_hints: tuple[str, ...]
    query_expansions: tuple[str, ...]
    source_event_ids: tuple[int, ...]
    memory_atom_ids: tuple[str, ...]
    project: str = ""
    app: str = ""
    confidence: float = 0.5
    quality_score: float = 0.5
    status: str = "active"
