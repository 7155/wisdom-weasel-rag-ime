"""Trace contract names for the v1 foreground IME acceptance path."""

from __future__ import annotations

from .source import (
    RAG_MEMORY_SOURCE_TYPES,
    REALTIME_SIDE_SOURCE_TYPES,
    SOURCE_MEMORY,
    SOURCE_MODEL,
    SOURCE_RAG,
    SOURCE_RIME,
    SOURCE_STATUS,
    VISIBLE_SOURCE_TYPES,
)

SOAK_REPORT_SCHEMA_VERSION = "rag-ime.squirrel-soak-report.v1"
INPUT_SOURCE_SELECTION_SCHEMA_VERSION = "rag-ime.macos-input-source-selection.v1"

ACTIVE_RAG_TRACE_EVENT_NAMES = frozenset(
    {
        "active_rag_context_captured",
        "active_rag_sensitive_field_blocked",
        "active_rag_retrieval_completed",
        "active_rag_evidence_governed",
        "deepseek_request_context_built",
        "deepseek_request_started",
        "deepseek_request_completed",
        "deepseek_request_failed",
        "active_rag_candidates_displayed",
    }
)

POST_COMMIT_BARRIER_EVENTS = frozenset(
    {
        "commit_observe_timeout",
        "post_commit_chain_cancelled",
        "display_invalidated_by_input_change",
        "frontend_transaction_invalidated",
    }
)

REQUIRED_TRACE_EVENT_NAMES = (
    "rime_composition_started",
    "rime_composition_candidates_visible",
    "rime_commit_observed",
    "post_commit_prediction_scheduled",
    "sidecar_request_sent",
    "sidecar_response_received",
    "foreground_context_capture_resolved",
    "panel_display_candidates",
    "assistant_overlay_candidate_visible",
    "post_commit_prediction_applied",
    "sidecar_response_dropped_stale",
    "sidecar_progressive_followup_sent",
    "sidecar_progressive_followup_skipped",
    "candidate_snapshot_selection_accepted",
    "candidate_snapshot_selection_rejected_stale",
    "assistant_overlay_candidate_accepted",
    "side_candidate_commit_observed",
    "side_candidate_feedback_recorded",
    "delete_context_resynced",
    "app_switch_context_invalidated",
    "focus_context_invalidated",
)

PREDICTION_TRACE_EVENT_NAMES = frozenset(
    {
        "prediction_anchor_computed",
        "prediction_refresh_decision",
        "prediction_show_decision",
        "prediction_snapshot_created",
        "prediction_snapshot_reused",
        "prediction_panel_soft_hold",
        "prediction_panel_soft_hide",
        "prediction_panel_hard_clear",
        "prediction_empty_lane_did_not_clear_panel",
        "prediction_lane_timeout_with_holdover",
        "prediction_lane_timeout_without_holdover",
        "prediction_trigger_dirty",
        "prediction_trigger_coalesced",
        "prediction_trigger_fired",
        "prediction_trigger_skipped",
        "prediction_trigger_rate_limited",
        "prediction_trigger_direct_memory_hit",
        "prediction_provider_called",
        "candidate_snapshot_selection_accepted",
        "candidate_snapshot_selection_rejected_stale",
        "candidate_snapshot_progressive_append",
        "candidate_snapshot_progressive_replace",
    }
)

V1_FOREGROUND_METRIC_KEYS = (
    "firstVisibleMs",
    "firstUsefulCandidateMs",
    "modelCandidateCount",
    "ragMemoryCandidateCount",
    "rimeCandidateCount",
    "sourceBadgeCoverage",
    "contextEchoCount",
    "staleDropCount",
    "staleAppliedCount",
    "pendingPanelClearCount",
    "followupRestartCount",
    "selectionAcceptedCount",
    "feedbackRecordedCount",
    "deleteResyncObserved",
    "appSwitchInvalidationObserved",
)
