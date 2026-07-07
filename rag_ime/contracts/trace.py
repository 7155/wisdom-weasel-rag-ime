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
    "panel_display_candidates",
    "post_commit_prediction_applied",
    "sidecar_response_dropped_stale",
    "sidecar_progressive_followup_sent",
    "sidecar_progressive_followup_skipped",
    "candidate_snapshot_selection_accepted",
    "candidate_snapshot_selection_rejected_stale",
    "side_candidate_commit_observed",
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
    "deleteResyncObserved",
    "appSwitchInvalidationObserved",
)
