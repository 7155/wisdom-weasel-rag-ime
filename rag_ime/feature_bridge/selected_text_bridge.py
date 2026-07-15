"""Selected-text Active RAG bridge descriptors."""

from __future__ import annotations

SELECTED_TEXT_BRIDGE_FIELDS = (
    "selectedText",
    "currentSelectedText",
    "contextAnchor",
)

REQUIRED_FOREGROUND_PROOF_EVENTS = (
    "selected_text_context_captured",
    "assistant_overlay_candidate_visible",
    "candidate_snapshot_selection_accepted",
)

CANDIDATE_SOURCE_TYPE = "rag"
