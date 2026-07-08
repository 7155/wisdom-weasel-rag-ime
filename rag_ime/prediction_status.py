from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import SideCandidateDisplayItem
from .text_utils import compact_whitespace


PredictionLaneState = Literal["idle", "pending", "ready", "empty", "timeout", "stale_dropped", "error"]


@dataclass(frozen=True)
class PredictionStatusState:
    rag_state: PredictionLaneState
    model_state: PredictionLaneState
    waiting_ms: int
    trigger: str
    stale_drop_reason: str = ""


def build_prediction_status_rows(
    state: PredictionStatusState,
    *,
    diagnostics_enabled: bool = False,
) -> list[SideCandidateDisplayItem]:
    row = prediction_status_row(
        rag_pending=state.rag_state == "pending",
        model_pending=state.model_state == "pending",
        waiting_ms=state.waiting_ms,
        latest_generation=0,
        rag_state=state.rag_state,
        model_state=state.model_state,
        trigger=state.trigger,
        stale_drop_reason=state.stale_drop_reason if diagnostics_enabled else "",
    )
    return [row] if row is not None else []


def prediction_status_row(
    *,
    rag_pending: bool,
    model_pending: bool,
    waiting_ms: int,
    latest_generation: int,
    rag_state: str | None = None,
    model_state: str | None = None,
    trigger: str = "",
    stale_drop_reason: str = "",
) -> SideCandidateDisplayItem | None:
    resolved_rag_state = compact_whitespace(rag_state or ("pending" if rag_pending else "ready"))
    resolved_model_state = compact_whitespace(model_state or ("pending" if model_pending else "ready"))
    if resolved_rag_state == "stale_dropped" or resolved_model_state == "stale_dropped":
        if stale_drop_reason:
            text = f"当前输入已变化，旧响应已丢弃：{stale_drop_reason}"
        else:
            text = "当前输入已变化，旧响应已丢弃"
    elif rag_pending and model_pending:
        text = f"查忆处理中{thinking_animation_suffix(waiting_ms)}"
    elif resolved_rag_state == "ready" and model_pending:
        text = f"RAG 已返回，LLM 生成中{thinking_animation_suffix(waiting_ms)}"
    elif resolved_model_state == "ready" and rag_pending:
        text = f"RAG 检索中{thinking_animation_suffix(waiting_ms)}"
    elif model_pending:
        text = f"LLM 生成中{thinking_animation_suffix(waiting_ms)}"
    elif rag_pending:
        text = f"RAG 检索中{thinking_animation_suffix(waiting_ms)}"
    elif resolved_model_state == "timeout" and resolved_rag_state in {"ready", "empty"}:
        text = "LLM 超时，保留 RAG 候选"
    elif resolved_rag_state == "empty" and resolved_model_state == "pending":
        text = "RAG 空结果，继续等待模型"
    else:
        return None
    return SideCandidateDisplayItem(
        label="",
        text=compact_whitespace(text),
        insert_text="",
        source_type="status",
        selection_action="none",
        source_index=0,
        display_layout="status_row",
        display_lane="post_commit_status",
        metadata={
            "ragState": resolved_rag_state,
            "modelState": resolved_model_state,
            "waitingMs": max(0, int(waiting_ms)),
            "animated": bool(rag_pending or model_pending),
            "animationFrame": thinking_animation_frame(waiting_ms),
            "trigger": compact_whitespace(trigger),
            "staleDropReason": compact_whitespace(stale_drop_reason),
            "latestGeneration": max(0, int(latest_generation)),
            "candidateOrdinal": 0,
            "selectionKey": None,
            "group": "status",
            "groupLabel": "状态",
            "isSelectable": False,
            "isStatus": True,
        },
    )


def thinking_animation_frame(waiting_ms: int) -> int:
    return (max(0, int(waiting_ms)) // 250) % 4


def thinking_animation_suffix(waiting_ms: int) -> str:
    return ("…", "·", "··", "···")[thinking_animation_frame(waiting_ms)]
