from __future__ import annotations

from .models import SideCandidateDisplayItem
from .text_utils import compact_whitespace


def prediction_status_row(
    *,
    rag_pending: bool,
    model_pending: bool,
    waiting_ms: int,
    latest_generation: int,
) -> SideCandidateDisplayItem | None:
    pending: list[str] = []
    if rag_pending:
        pending.append("RAG")
    if model_pending:
        pending.append("LLM")
    if not pending:
        return None
    if waiting_ms < 150:
        return None
    text = "查忆处理中… " + "、".join(pending) + " 等待中"
    if rag_pending and not model_pending:
        text = "RAG 检索中…"
    elif model_pending and not rag_pending:
        text = "LLM 生成中…"
    return SideCandidateDisplayItem(
        label="",
        text=compact_whitespace(text),
        insert_text="",
        source_type="status",
        selection_action="none",
        source_index=0,
        display_layout="status_row",
        display_lane="prediction_status",
        metadata={
            "ragState": "pending" if rag_pending else "ready",
            "modelState": "pending" if model_pending else "ready",
            "waitingMs": max(0, int(waiting_ms)),
            "latestGeneration": max(0, int(latest_generation)),
            "candidateOrdinal": 0,
            "selectionKey": "",
        },
    )
