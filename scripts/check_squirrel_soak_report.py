#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_squirrel_frontend_trace import (
    DEFAULT_LOG_PATH,
    SOURCE_BADGES,
    SOURCE_COLOR_TOKENS,
    build_report,
    candidate_quota_violations,
    candidates_match_selection_route,
    event_timestamp_ms,
    is_post_commit_followup_request,
    is_side_selection_route_event,
    is_valid_side_commit_event,
    load_events,
    report_passes,
    summarize_event,
)
from rag_ime.contracts.trace import (
    INPUT_SOURCE_SELECTION_SCHEMA_VERSION,
    POST_COMMIT_BARRIER_EVENTS,
    PREDICTION_TRACE_EVENT_NAMES,
    RAG_MEMORY_SOURCE_TYPES,
    REALTIME_SIDE_SOURCE_TYPES,
    REQUIRED_TRACE_EVENT_NAMES,
    SOAK_REPORT_SCHEMA_VERSION,
    SOURCE_MODEL,
    SOURCE_RIME,
    SOURCE_STATUS,
    VISIBLE_SOURCE_TYPES,
)


DEFAULT_REPORT_PATH = Path("/tmp/rag-ime-squirrel-soak-report.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate a machine-readable Squirrel foreground soak report.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument(
        "--input-source-selection-report",
        default="",
        help="Optional JSON report from select_macos_input_source.sh --report-path.",
    )
    parser.add_argument("--wait", type=float, default=0.0, help="Wait this many seconds for the soak gate to pass.")
    parser.add_argument("--print-last", type=int, default=8)
    parser.add_argument("--require-mixed-panel", action="store_true")
    parser.add_argument("--require-side-panel", action="store_true")
    parser.add_argument("--require-side-commit", action="store_true")
    parser.add_argument("--require-commit-observed", action="store_true")
    parser.add_argument("--require-post-commit-followup", action="store_true")
    parser.add_argument("--require-delete-resync", action="store_true")
    parser.add_argument("--require-modern-prediction-session", action="store_true")
    parser.add_argument("--require-balanced-quota", action="store_true")
    parser.add_argument(
        "--require-rime-composition-ok",
        action="store_true",
        help="Require proof that composition-time Rime candidates remained owned by Rime, not the post-commit predictor.",
    )
    parser.add_argument(
        "--require-no-ai-during-composition",
        action="store_true",
        help="Require that composition panels contain no AI/model/RAG/memory/action candidates.",
    )
    parser.add_argument(
        "--require-assistant-overlay-post-commit",
        action="store_true",
        help="Require post-commit AI output to be shown through assistant overlay trace events.",
    )
    parser.add_argument(
        "--require-assistant-overlay-key-policy",
        action="store_true",
        help="Require overlay Tab/Option-number acceptance or accepted overlay candidate trace evidence.",
    )
    parser.add_argument(
        "--require-post-commit-visible",
        action="store_true",
        help="Require at least one real non-status post-commit prediction panel in the foreground trace.",
    )
    parser.add_argument(
        "--require-source-badges",
        action="store_true",
        help="Require every displayed typed side/Rime candidate to carry the expected source badge and color token.",
    )
    parser.add_argument(
        "--require-post-commit-key-policy",
        action="store_true",
        help="Require evidence that post-commit panels route number keys to Rime and side picks through tab/option-number.",
    )
    parser.add_argument(
        "--require-app-switch-stale-drop",
        action="store_true",
        help="Require app/focus/input-source switch evidence plus stale response drop/reject coverage.",
    )
    parser.add_argument(
        "--require-followup-after-select",
        action="store_true",
        help="Require a candidate selection/commit followed by a post-commit sidecar request.",
    )
    parser.add_argument(
        "--require-snapshot-selection-trace",
        action="store_true",
        help="Require accepted snapshot-selection trace coverage for paired side-candidate commits.",
    )
    parser.add_argument("--min-sidecar-requests", type=int, default=1)
    parser.add_argument("--min-sidecar-applied", type=int, default=1)
    parser.add_argument("--min-panel-displays", type=int, default=1)
    parser.add_argument("--min-side-commits", type=int, default=1)
    parser.add_argument("--min-post-commit-followups", type=int, default=1)
    parser.add_argument("--min-duration-sec", type=float, default=0.0)
    parser.add_argument("--min-backspaces", type=int, default=0)
    parser.add_argument("--min-app-switches", type=int, default=0)
    parser.add_argument(
        "--min-model-candidates-per-panel",
        type=int,
        default=0,
        help="Candidate count used by --min-model-multi-candidate-panels. Use 3 to prove real foreground multi-candidate model display.",
    )
    parser.add_argument(
        "--min-model-multi-candidate-panels",
        type=int,
        default=0,
        help="Require this many foreground panels to contain at least --min-model-candidates-per-panel model candidates.",
    )
    parser.add_argument(
        "--min-source-triplet-panels",
        type=int,
        default=0,
        help="Require this many foreground panels to contain model, RAG/memory, and Rime candidates together.",
    )
    parser.add_argument(
        "--min-chain-depth",
        type=int,
        default=0,
        help="Require this many consecutive side-candidate commits with matching post-commit follow-up requests.",
    )
    parser.add_argument("--max-stale-applied", type=int, default=0)
    parser.add_argument(
        "--max-stale-apply-count",
        type=int,
        dest="max_stale_applied",
        help="Alias for --max-stale-applied, named for the v1 foreground acceptance gate.",
    )
    parser.add_argument("--max-flicker-count", type=int, default=0)
    parser.add_argument("--max-min-visible-violations", type=int, default=0)
    parser.add_argument("--max-rag-empty-cleared-panel", type=int, default=0)
    parser.add_argument(
        "--max-first-visible-ms",
        type=int,
        default=-1,
        help="Fail if first real post-commit foreground candidate appears after this many ms from commit/schedule.",
    )
    parser.add_argument(
        "--max-context-echo-count",
        type=int,
        default=-1,
        help="Fail if post-commit foreground candidates echo committed context more than this count.",
    )
    parser.add_argument(
        "--manual-required",
        action="append",
        default=[],
        help="Append a manual confirmation note to the report. May be repeated.",
    )
    args = parser.parse_args()

    log_path = Path(args.log_path).expanduser()
    report_path = Path(args.report_path).expanduser()
    deadline = time.monotonic() + max(0.0, args.wait)

    soak_report: dict[str, Any] = {}
    input_source_selection = load_input_source_selection_report(args.input_source_selection_report)
    while True:
        events = load_events(log_path)
        frontend_report = build_report(events, log_path=log_path, print_last=max(0, args.print_last))
        soak_report = build_soak_report(
            events,
            frontend_report=frontend_report,
            log_path=log_path,
            input_source_selection=input_source_selection,
            manual_required=args.manual_required,
            require_mixed_panel=args.require_mixed_panel,
            require_side_panel=args.require_side_panel,
            require_side_commit=args.require_side_commit,
            require_commit_observed=args.require_commit_observed,
            require_post_commit_followup=args.require_post_commit_followup,
            require_delete_resync=args.require_delete_resync,
            require_modern_prediction_session=args.require_modern_prediction_session,
            require_balanced_quota=args.require_balanced_quota,
            require_rime_composition_ok=args.require_rime_composition_ok,
            require_no_ai_during_composition=args.require_no_ai_during_composition,
            require_assistant_overlay_post_commit=args.require_assistant_overlay_post_commit,
            require_assistant_overlay_key_policy=args.require_assistant_overlay_key_policy,
            require_post_commit_visible=args.require_post_commit_visible,
            require_source_badges=args.require_source_badges,
            require_post_commit_key_policy=args.require_post_commit_key_policy,
            require_app_switch_stale_drop=args.require_app_switch_stale_drop,
            require_followup_after_select=args.require_followup_after_select,
            require_snapshot_selection_trace=args.require_snapshot_selection_trace,
            min_sidecar_requests=max(0, args.min_sidecar_requests),
            min_sidecar_applied=max(0, args.min_sidecar_applied),
            min_panel_displays=max(0, args.min_panel_displays),
            min_side_commits=max(0, args.min_side_commits),
            min_post_commit_followups=max(0, args.min_post_commit_followups),
            min_duration_sec=max(0.0, args.min_duration_sec),
            min_backspaces=max(0, args.min_backspaces),
            min_app_switches=max(0, args.min_app_switches),
            min_model_candidates_per_panel=max(0, args.min_model_candidates_per_panel),
            min_model_multi_candidate_panels=max(0, args.min_model_multi_candidate_panels),
            min_source_triplet_panels=max(0, args.min_source_triplet_panels),
            min_chain_depth=max(0, args.min_chain_depth),
            max_stale_applied=max(0, args.max_stale_applied),
            max_flicker_count=max(0, args.max_flicker_count),
            max_min_visible_violations=max(0, args.max_min_visible_violations),
            max_rag_empty_cleared_panel=max(0, args.max_rag_empty_cleared_panel),
            max_first_visible_ms=int(args.max_first_visible_ms),
            max_context_echo_count=int(args.max_context_echo_count),
        )
        if soak_report["passed"] or time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(soak_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(soak_report, ensure_ascii=False, indent=2))
    return 0 if soak_report["passed"] else 1


def build_soak_report(
    events: list[dict[str, Any]],
    *,
    frontend_report: dict[str, Any],
    log_path: Path,
    input_source_selection: dict[str, Any] | None,
    manual_required: list[str],
    require_mixed_panel: bool,
    require_side_panel: bool,
    require_side_commit: bool,
    require_commit_observed: bool,
    require_post_commit_followup: bool,
    require_delete_resync: bool,
    require_modern_prediction_session: bool,
    require_balanced_quota: bool,
    require_rime_composition_ok: bool,
    require_no_ai_during_composition: bool,
    require_assistant_overlay_post_commit: bool,
    require_assistant_overlay_key_policy: bool,
    require_post_commit_visible: bool,
    require_source_badges: bool,
    require_post_commit_key_policy: bool,
    require_app_switch_stale_drop: bool,
    require_followup_after_select: bool,
    require_snapshot_selection_trace: bool,
    min_sidecar_requests: int,
    min_sidecar_applied: int,
    min_panel_displays: int,
    min_side_commits: int,
    min_post_commit_followups: int,
    min_duration_sec: float,
    min_backspaces: int,
    min_app_switches: int,
    min_model_candidates_per_panel: int,
    min_model_multi_candidate_panels: int,
    min_source_triplet_panels: int,
    min_chain_depth: int,
    max_stale_applied: int,
    max_flicker_count: int,
    max_min_visible_violations: int,
    max_rag_empty_cleared_panel: int,
    max_first_visible_ms: int,
    max_context_echo_count: int,
) -> dict[str, Any]:
    event_counts = Counter(str(event.get("event") or "") for event in events if isinstance(event, dict))
    side_commit_pairs, unmatched_routes = collect_number_key_side_commit_pairs(events)
    post_commit_followups = collect_post_commit_followups(events)
    chain = summarize_chaining(events)
    stale_applied = collect_stale_applied_responses(events)
    composition_ai_violations = collect_composition_ai_candidate_violations(events)
    assistant_overlay_post_commit_ok = has_assistant_overlay_post_commit(events)
    assistant_overlay_key_policy_ok = has_assistant_overlay_key_policy(events)
    prediction_stability = summarize_prediction_stability(events, stale_applied_count=len(stale_applied))
    lane_stability = summarize_lane_stability(events)
    display_quality = summarize_display_quality(
        events,
        frontend_report=frontend_report,
        min_model_candidates_per_panel=min_model_candidates_per_panel,
    )
    foreground_coverage = summarize_foreground_coverage(events)
    selection_quality = summarize_selection_quality(
        events,
        paired_side_commit_count=len(side_commit_pairs),
    )
    v1_foreground = summarize_v1_foreground(
        events,
        frontend_report=frontend_report,
        display_quality=display_quality,
        foreground_coverage=foreground_coverage,
        selection_quality=selection_quality,
        post_commit_followup_count=len(post_commit_followups),
        stale_applied_count=len(stale_applied),
    )
    required_trace_events = summarize_required_trace_events(events)
    post_commit_barrier_violations = [
        violation
        for violation in frontend_report.get("postCommitBarrierViolations") or []
        if isinstance(violation, dict)
    ]

    frontend_ok = report_passes(
        frontend_report,
        require_mixed_panel=require_mixed_panel,
        require_side_panel=require_side_panel,
        require_side_commit=require_side_commit,
        require_commit_observed=require_commit_observed,
        require_post_commit_followup=require_post_commit_followup,
        require_delete_resync=require_delete_resync,
        require_modern_prediction_session=require_modern_prediction_session,
        require_balanced_quota=require_balanced_quota,
    )

    thresholds = {
        "minSidecarRequests": min_sidecar_requests,
        "minSidecarApplied": min_sidecar_applied,
        "minPanelDisplays": min_panel_displays,
        "minSideCommits": min_side_commits,
        "minPostCommitFollowups": min_post_commit_followups,
        "minDurationSec": min_duration_sec,
        "minBackspaces": min_backspaces,
        "minAppSwitches": min_app_switches,
        "minModelCandidatesPerPanel": min_model_candidates_per_panel,
        "minModelMultiCandidatePanels": min_model_multi_candidate_panels,
        "minSourceTripletPanels": min_source_triplet_panels,
        "minChainDepth": min_chain_depth,
        "maxStaleApplied": max_stale_applied,
        "maxFlickerCount": max_flicker_count,
        "maxMinVisibleViolations": max_min_visible_violations,
        "maxRagEmptyClearedPanel": max_rag_empty_cleared_panel,
        "maxFirstVisibleMs": max_first_visible_ms,
        "maxContextEchoCount": max_context_echo_count,
        "requireRimeCompositionOk": require_rime_composition_ok,
        "requireNoAiDuringComposition": require_no_ai_during_composition,
        "requireAssistantOverlayPostCommit": require_assistant_overlay_post_commit,
        "requireAssistantOverlayKeyPolicy": require_assistant_overlay_key_policy,
        "requirePostCommitVisible": require_post_commit_visible,
        "requireSourceBadges": require_source_badges,
        "requirePostCommitKeyPolicy": require_post_commit_key_policy,
        "requireAppSwitchStaleDrop": require_app_switch_stale_drop,
        "requireFollowupAfterSelect": require_followup_after_select,
        "requireSnapshotSelectionTrace": require_snapshot_selection_trace,
        "inputSourceSelectionReport": bool(input_source_selection),
    }
    input_source_selection_ok = True
    if input_source_selection is not None:
        input_source_selection_ok = bool(input_source_selection.get("ok"))
    threshold_results = {
        "inputSourceSelection": input_source_selection_ok,
        "sidecarRequests": int(event_counts.get("sidecar_request_scheduled", 0)) >= min_sidecar_requests,
        "sidecarApplied": int(event_counts.get("sidecar_response_applied", 0)) >= min_sidecar_applied,
        "panelDisplays": int(event_counts.get("panel_display_candidates", 0)) >= min_panel_displays,
        "sideCommits": len(side_commit_pairs) >= min_side_commits,
        "postCommitFollowups": len(post_commit_followups) >= min_post_commit_followups,
        "durationSec": float(foreground_coverage["durationSec"]) >= min_duration_sec,
        "backspaces": int(foreground_coverage["backspaceCount"]) >= min_backspaces,
        "appSwitches": int(foreground_coverage["appSwitchCount"]) >= min_app_switches,
        "modelMultiCandidatePanels": (
            int(display_quality["multiModelCandidatePanelCount"]) >= min_model_multi_candidate_panels
        ),
        "sourceTripletPanels": int(display_quality["sourceTripletPanelCount"]) >= min_source_triplet_panels,
        "chainDepth": int(chain["maxChainDepth"]) >= min_chain_depth,
        "staleApplied": len(stale_applied) <= max_stale_applied,
        "flickerCount": int(prediction_stability["flickerCount"]) <= max_flicker_count,
        "minVisibleViolations": int(prediction_stability["minVisibleViolationCount"]) <= max_min_visible_violations,
        "ragEmptyClearedPanel": int(lane_stability["ragEmptyClearedPanelCount"]) <= max_rag_empty_cleared_panel,
        "noAiDuringComposition": not require_no_ai_during_composition or not composition_ai_violations,
        "assistantOverlayPostCommit": not require_assistant_overlay_post_commit or assistant_overlay_post_commit_ok,
        "assistantOverlayKeyPolicy": not require_assistant_overlay_key_policy or assistant_overlay_key_policy_ok,
        "snapshotSelectionTrace": (
            not require_snapshot_selection_trace
            or int(selection_quality["sideCommitWithoutAcceptedSnapshotSelectionCount"]) == 0
        ),
        "rimeCompositionOk": not require_rime_composition_ok or bool(v1_foreground["rimeCompositionOk"]),
        "postCommitVisible": not require_post_commit_visible or bool(v1_foreground["postCommitVisible"]),
        "sourceBadges": not require_source_badges or int(display_quality["sourceBadgeMissingCount"]) == 0,
        "postCommitKeyPolicy": (
            not require_post_commit_key_policy
            or bool(v1_foreground["postCommitKeyPolicyOk"])
        ),
        "appSwitchStaleDrop": (
            not require_app_switch_stale_drop
            or bool(v1_foreground["appSwitchStaleDropOk"])
        ),
        "followupAfterSelect": (
            not require_followup_after_select
            or bool(v1_foreground["followupAfterSelectOk"])
        ),
        "firstVisibleMs": (
            max_first_visible_ms < 0
            or (
                int(v1_foreground["firstPostCommitVisibleMs"]) >= 0
                and int(v1_foreground["firstPostCommitVisibleMs"]) <= max_first_visible_ms
            )
        ),
        "contextEchoCount": (
            max_context_echo_count < 0
            or int(v1_foreground["contextEchoCount"]) <= max_context_echo_count
        ),
    }

    violations: list[dict[str, Any]] = []
    if input_source_selection is not None and not input_source_selection_ok:
        source = input_source_selection.get("source")
        source = source if isinstance(source, dict) else {}
        violations.append(
            {
                "type": "input_source_selection_failed",
                "inputSourceId": input_source_selection.get("inputSourceId"),
                "failureKind": input_source_selection.get("failureKind"),
                "tisSelectStatus": input_source_selection.get("tisSelectStatus"),
                "current": source.get("current"),
                "selected": source.get("selected"),
                "thirdPartyEnabled": source.get("thirdPartyEnabled"),
            }
        )
    for violation in frontend_report.get("frontendTransactionViolations") or []:
        if isinstance(violation, dict):
            violations.append(
                {
                    "type": "frontend_transaction_violation",
                    "event": violation.get("event"),
                    "timestampMs": violation.get("timestampMs"),
                    "reason": violation.get("reason"),
                    "candidate": violation.get("candidate"),
                }
            )
    for violation in frontend_report.get("postDeleteContextViolations") or []:
        if isinstance(violation, dict):
            violations.append(
                {
                    "type": "post_delete_context_violation",
                    "event": violation.get("event"),
                    "timestampMs": violation.get("timestampMs"),
                    "reason": violation.get("reason"),
                    "expectedCommittedContextHash": violation.get("expectedCommittedContextHash"),
                    "committedContextHash": violation.get("committedContextHash"),
                }
            )
    for violation in frontend_report.get("tracePrivacyViolations") or []:
        if isinstance(violation, dict):
            violations.append(
                {
                    "type": "trace_privacy_violation",
                    "event": violation.get("event"),
                    "timestampMs": violation.get("timestampMs"),
                    "field": violation.get("field"),
                    "reason": violation.get("reason"),
                }
            )
    for violation in post_commit_barrier_violations:
        violations.append(
            {
                "type": violation.get("type") or "post_commit_after_cancel",
                "timestampMs": violation.get("timestampMs"),
                "commitTimestampMs": violation.get("commitTimestampMs"),
                "cancelTimestampMs": violation.get("cancelTimestampMs"),
                "cancelEvent": violation.get("cancelEvent"),
                "cancelReason": violation.get("cancelReason"),
                "commitTextPreview": violation.get("commitTextPreview"),
                "committedContextHash": violation.get("committedContextHash"),
            }
        )
    if len(stale_applied) > max_stale_applied:
        for violation in stale_applied:
            violations.append(violation)
    for route in unmatched_routes:
        violations.append(
            {
                "type": "unmatched_number_key_route",
                "timestampMs": route.get("timestampMs"),
                "key": route.get("key"),
                "candidate": route.get("candidate"),
            }
        )
    if int(prediction_stability["flickerCount"]) > max_flicker_count:
        violations.append(
            {
                "type": "prediction_flicker_threshold",
                "actual": prediction_stability["flickerCount"],
                "expectedAtMost": max_flicker_count,
            }
        )
    if int(prediction_stability["minVisibleViolationCount"]) > max_min_visible_violations:
        violations.append(
            {
                "type": "min_visible_threshold",
                "actual": prediction_stability["minVisibleViolationCount"],
                "expectedAtMost": max_min_visible_violations,
            }
        )
    if int(lane_stability["ragEmptyClearedPanelCount"]) > max_rag_empty_cleared_panel:
        violations.append(
            {
                "type": "rag_empty_cleared_panel",
                "actual": lane_stability["ragEmptyClearedPanelCount"],
                "expectedAtMost": max_rag_empty_cleared_panel,
            }
        )
    display_quality_violation_types = {
        "sourceBadgeMissingCount": "source_badge_missing",
        "modelOccupiedAllSlotsViolation": "model_occupied_all_slots",
        "longCandidateViolation": "long_candidate",
        "postCommitNumberKeyViolation": "post_commit_number_key",
        "snapshotOrdinalDriftViolation": "snapshot_ordinal_drift",
    }
    for key, violation_type in display_quality_violation_types.items():
        actual = int(display_quality.get(key) or 0)
        if actual > 0:
            violations.append({"type": violation_type, "actual": actual, "expected": 0})
    if int(chain["maxChainDepth"]) < min_chain_depth:
        violations.append(
            {
                "type": "chain_depth_threshold",
                "actual": chain["maxChainDepth"],
                "expectedAtLeast": min_chain_depth,
            }
        )
    if float(foreground_coverage["durationSec"]) < min_duration_sec:
        violations.append(
            {
                "type": "duration_threshold",
                "actual": foreground_coverage["durationSec"],
                "expectedAtLeast": min_duration_sec,
            }
        )
    if int(foreground_coverage["backspaceCount"]) < min_backspaces:
        violations.append(
            {
                "type": "backspace_threshold",
                "actual": foreground_coverage["backspaceCount"],
                "expectedAtLeast": min_backspaces,
            }
        )
    if int(foreground_coverage["appSwitchCount"]) < min_app_switches:
        violations.append(
            {
                "type": "app_switch_threshold",
                "actual": foreground_coverage["appSwitchCount"],
                "expectedAtLeast": min_app_switches,
            }
        )
    if int(display_quality["multiModelCandidatePanelCount"]) < min_model_multi_candidate_panels:
        violations.append(
            {
                "type": "model_multi_candidate_panel_threshold",
                "actual": display_quality["multiModelCandidatePanelCount"],
                "expectedAtLeast": min_model_multi_candidate_panels,
                "requiredModelCandidatesPerPanel": display_quality["requiredModelCandidatesPerPanel"],
                "maxModelCandidateCountInPanel": display_quality["maxModelCandidateCountInPanel"],
            }
        )
    if int(display_quality["sourceTripletPanelCount"]) < min_source_triplet_panels:
        violations.append(
            {
                "type": "source_triplet_panel_threshold",
                "actual": display_quality["sourceTripletPanelCount"],
                "expectedAtLeast": min_source_triplet_panels,
                "maxSourceFamilyCountInPanel": display_quality["maxSourceFamilyCountInPanel"],
            }
        )
    if require_snapshot_selection_trace and int(selection_quality["sideCommitWithoutAcceptedSnapshotSelectionCount"]) > 0:
        violations.append(
            {
                "type": "snapshot_selection_trace_missing",
                "actual": selection_quality["snapshotSelectionAcceptedCount"],
                "expectedAtLeast": selection_quality["pairedSideCommitCount"],
                "missing": selection_quality["sideCommitWithoutAcceptedSnapshotSelectionCount"],
            }
        )
    v1_violation_checks = [
        (require_rime_composition_ok and not v1_foreground["rimeCompositionOk"], "rime_composition_not_proven"),
        (require_no_ai_during_composition and composition_ai_violations, "ai_candidate_during_composition"),
        (
            require_assistant_overlay_post_commit and not assistant_overlay_post_commit_ok,
            "assistant_overlay_post_commit_not_proven",
        ),
        (
            require_assistant_overlay_key_policy and not assistant_overlay_key_policy_ok,
            "assistant_overlay_key_policy_not_proven",
        ),
        (require_post_commit_visible and not v1_foreground["postCommitVisible"], "post_commit_visible_not_proven"),
        (require_post_commit_key_policy and not v1_foreground["postCommitKeyPolicyOk"], "post_commit_key_policy_not_proven"),
        (require_app_switch_stale_drop and not v1_foreground["appSwitchStaleDropOk"], "app_switch_stale_drop_not_proven"),
        (require_followup_after_select and not v1_foreground["followupAfterSelectOk"], "followup_after_select_not_proven"),
    ]
    for failed, violation_type in v1_violation_checks:
        if failed:
            violations.append({"type": violation_type, "v1Foreground": v1_foreground})
    if max_first_visible_ms >= 0 and not threshold_results["firstVisibleMs"]:
        violations.append(
            {
                "type": "first_post_commit_visible_too_slow",
                "actual": v1_foreground["firstPostCommitVisibleMs"],
                "expectedAtMost": max_first_visible_ms,
            }
        )
    if max_context_echo_count >= 0 and not threshold_results["contextEchoCount"]:
        violations.append(
            {
                "type": "context_echo_threshold",
                "actual": v1_foreground["contextEchoCount"],
                "expectedAtMost": max_context_echo_count,
                "samples": v1_foreground["contextEchoSamples"],
            }
        )

    response_age_values = [
        int(event.get("responseAgeMs") or 0)
        for event in events
        if event.get("event") == "sidecar_response_applied" and int(event.get("responseAgeMs") or 0) > 0
    ]
    post_commit_followup_values = [
        max(
            0,
            event_timestamp_ms(match.get("request")) - event_timestamp_ms(match.get("commit")),
        )
        for match in post_commit_followups
        if match.get("request") and match.get("commit")
    ]
    response_apply_values = [
        max(
            0,
            event_timestamp_ms(pair.get("applied")) - event_timestamp_ms(pair.get("received")),
        )
        for pair in collect_response_receive_apply_pairs(events)
    ]

    passed = frontend_ok and all(threshold_results.values()) and not violations
    return {
        "schemaVersion": SOAK_REPORT_SCHEMA_VERSION,
        "generatedAtMs": int(time.time() * 1000),
        "logPath": str(log_path),
        "eventCount": len(events),
        "eventCounts": dict(sorted(event_counts.items())),
        "required": {
            "mixedPanel": require_mixed_panel,
            "sidePanel": require_side_panel,
            "sideCommit": require_side_commit,
            "commitObserved": require_commit_observed,
            "postCommitFollowup": require_post_commit_followup,
            "deleteResync": require_delete_resync,
            "modernPredictionSession": require_modern_prediction_session,
            "balancedQuota": require_balanced_quota,
            "rimeCompositionOk": require_rime_composition_ok,
            "noAiDuringComposition": require_no_ai_during_composition,
            "assistantOverlayPostCommit": require_assistant_overlay_post_commit,
            "assistantOverlayKeyPolicy": require_assistant_overlay_key_policy,
            "postCommitVisible": require_post_commit_visible,
            "sourceBadges": require_source_badges,
            "postCommitKeyPolicy": require_post_commit_key_policy,
            "appSwitchStaleDrop": require_app_switch_stale_drop,
            "followupAfterSelect": require_followup_after_select,
            "snapshotSelectionTrace": require_snapshot_selection_trace,
        },
        "thresholds": thresholds,
        "thresholdResults": threshold_results,
        "manualRequired": [item for item in manual_required if item],
        "inputSourceSelection": input_source_selection,
        "metrics": {
            "numberKeyRouteCount": int(event_counts.get("number_key_route", 0)),
            "sideSelectionRouteCount": int(event_counts.get("number_key_route", 0))
            + int(event_counts.get("tab_key_route", 0))
            + int(event_counts.get("option_number_route", 0)),
            "pairedSideCommitCount": len(side_commit_pairs),
            "pairedSideSelectionCommitCount": len(side_commit_pairs),
            "unmatchedNumberKeyRouteCount": len(unmatched_routes),
            "unmatchedSideSelectionRouteCount": len(unmatched_routes),
            "postCommitFollowupCount": len(post_commit_followups),
            "deleteResyncObserved": bool(frontend_report.get("latestDeleteResync")),
            "postDeleteContextUseObserved": bool(frontend_report.get("latestPostDeleteContextUse")),
            "postCommitBarrierViolationCount": len(post_commit_barrier_violations),
            "compositionAiViolationCount": len(composition_ai_violations),
            "assistantOverlayPostCommit": assistant_overlay_post_commit_ok,
            "assistantOverlayKeyPolicy": assistant_overlay_key_policy_ok,
            "staleAppliedResponseCount": len(stale_applied),
            "staleResponseDropCount": int(event_counts.get("sidecar_response_dropped_stale", 0))
            + int(event_counts.get("sidecar_response_dropped", 0)),
            "staleSelectionRejectedCount": int(event_counts.get("stale_candidate_selection_rejected", 0)),
        },
        "predictionStability": prediction_stability,
        "laneStability": lane_stability,
        "displayQuality": display_quality,
        "v1Foreground": v1_foreground,
        "requiredTraceEvents": required_trace_events,
        "foregroundCoverage": foreground_coverage,
        "selectionQuality": selection_quality,
        "chain": chain,
        "latency": {
            "responseAgeMs": summarize_numeric(response_age_values),
            "responseReceivedToAppliedMs": summarize_numeric(response_apply_values),
            "postCommitFollowupMs": summarize_numeric(post_commit_followup_values),
        },
        "violations": violations,
        "frontendTrace": frontend_report,
        "passed": passed,
    }


def load_input_source_selection_report(path_value: str) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.exists():
        return {
            "schemaVersion": INPUT_SOURCE_SELECTION_SCHEMA_VERSION,
            "ok": False,
            "path": str(path),
            "failureKind": "selection-report-missing",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schemaVersion": INPUT_SOURCE_SELECTION_SCHEMA_VERSION,
            "ok": False,
            "path": str(path),
            "failureKind": "selection-report-invalid-json",
            "error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "schemaVersion": INPUT_SOURCE_SELECTION_SCHEMA_VERSION,
            "ok": False,
            "path": str(path),
            "failureKind": "selection-report-not-object",
        }
    payload = dict(payload)
    payload.setdefault("path", str(path))
    return payload


def summarize_v1_foreground(
    events: list[dict[str, Any]],
    *,
    frontend_report: dict[str, Any],
    display_quality: dict[str, Any],
    foreground_coverage: dict[str, Any],
    selection_quality: dict[str, Any],
    post_commit_followup_count: int,
    stale_applied_count: int,
) -> dict[str, Any]:
    first_visible_ms = first_post_commit_visible_latency_ms(events)
    context_echoes = collect_context_echo_candidates(events)
    source_counts = summarize_visible_source_counts(events)
    source_badge_coverage = summarize_source_badge_coverage(events)
    pending_panel_clear_count = count_pending_panel_clears(events)
    followup_restart_count = count_followup_restarts(events)
    stale_drop_count = sum(
        1
        for event in events
        if str(event.get("event") or "") in {"sidecar_response_dropped_stale", "sidecar_response_dropped"}
    )
    stale_reject_count = int(selection_quality.get("snapshotSelectionRejectedStaleCount") or 0) + int(
        selection_quality.get("legacyStaleSelectionRejectedCount") or 0
    )
    return {
        "rimeCompositionOk": bool(frontend_report.get("latestRimeCompositionMode")),
        "postCommitVisible": has_post_commit_visible_panel(events),
        "sourceBadgesOk": int(display_quality.get("sourceBadgeMissingCount") or 0) == 0,
        "postCommitKeyPolicyOk": int(display_quality.get("postCommitNumberKeyViolation") or 0) == 0
        and has_post_commit_visible_panel(events),
        "appSwitchStaleDropOk": int(foreground_coverage.get("appSwitchCount") or 0) > 0
        and (stale_drop_count + stale_reject_count) > 0,
        "followupAfterSelectOk": post_commit_followup_count > 0
        and int(selection_quality.get("snapshotSelectionAcceptedCount") or 0) > 0,
        "firstPostCommitVisibleMs": first_visible_ms,
        "firstVisibleMs": first_visible_ms,
        "firstUsefulCandidateMs": first_visible_ms,
        "modelCandidateCount": source_counts["modelCandidateCount"],
        "ragMemoryCandidateCount": source_counts["ragMemoryCandidateCount"],
        "rimeCandidateCount": source_counts["rimeCandidateCount"],
        "sourceBadgeCoverage": source_badge_coverage,
        "contextEchoCount": len(context_echoes),
        "contextEchoSamples": context_echoes[:8],
        "staleDropCount": stale_drop_count,
        "staleAppliedCount": stale_applied_count,
        "staleRejectCount": stale_reject_count,
        "pendingPanelClearCount": pending_panel_clear_count,
        "followupRestartCount": followup_restart_count,
        "selectionAcceptedCount": int(selection_quality.get("snapshotSelectionAcceptedCount") or 0),
        "deleteResyncObserved": bool(foreground_coverage.get("deleteResyncCount")),
        "appSwitchInvalidationObserved": bool(foreground_coverage.get("appSwitchCount")),
    }


def has_post_commit_visible_panel(events: list[dict[str, Any]]) -> bool:
    return any(event_is_visible_post_commit_panel(event) for event in events)


def has_assistant_overlay_post_commit(events: list[dict[str, Any]]) -> bool:
    overlay_events = {
        "assistant_overlay_displayed",
        "assistant_overlay_updated",
        "assistant_overlay_candidate_visible",
        "assistant_overlay_active_rag_thinking",
        "assistant_overlay_active_rag_ready",
        "post_commit_local_action_placeholder_displayed",
    }
    for event in events:
        if str(event.get("event") or "") not in overlay_events:
            continue
        phase = str(event.get("phase") or "")
        ui_mode = str(event.get("uiMode") or "")
        if phase in {"post_commit", "active_rag"} or ui_mode.startswith(("post_commit", "active_rag")):
            return True
        if str(event.get("event") or "") == "post_commit_local_action_placeholder_displayed":
            return True
    return False


def has_assistant_overlay_key_policy(events: list[dict[str, Any]]) -> bool:
    for event in events:
        name = str(event.get("event") or "")
        if name == "assistant_overlay_candidate_accepted":
            return True
        if name in {"tab_key_route", "option_number_route"} and bool(event.get("overlay")):
            return True
    return False


def collect_composition_ai_candidate_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        if not panel_is_composition_event(event):
            continue
        for candidate in event_candidates(event):
            if not isinstance(candidate, dict):
                continue
            source_type = str(candidate.get("sourceType") or "")
            if source_type and source_type != SOURCE_RIME:
                violations.append(
                    {
                        "event": event.get("event"),
                        "sourceType": source_type,
                        "text": candidate_display_text(candidate),
                        "snapshotId": candidate.get("snapshotId"),
                    }
                )
    return violations


def event_is_visible_post_commit_panel(event: dict[str, Any]) -> bool:
    if event.get("event") != "panel_display_candidates":
        return False
    if not panel_is_post_commit_event(event):
        return False
    return any(candidate_is_real_side_candidate(candidate) for candidate in event_candidates(event))


def panel_is_post_commit_event(event: dict[str, Any]) -> bool:
    ui_mode = str(event.get("uiMode") or "")
    if ui_mode in {"post_commit_prediction", "post_commit_pending"}:
        return True
    session = event.get("predictionSession")
    if isinstance(session, dict):
        phase = str(session.get("phase") or "")
        selection_scope = str(session.get("selectionScope") or "")
        return phase == "post_commit" or selection_scope == "prediction"
    return False


def panel_is_composition_event(event: dict[str, Any]) -> bool:
    ui_mode = str(event.get("uiMode") or "")
    if ui_mode == "composition_rime":
        return True
    prediction_session = event.get("predictionSession")
    if isinstance(prediction_session, dict):
        phase = str(prediction_session.get("phase") or "")
        owned = bool(prediction_session.get("rimeCompositionOwnedByRime"))
        return phase == "composition" or owned
    return False


def candidate_is_real_side_candidate(candidate: Any) -> bool:
    if not isinstance(candidate, dict) or is_status_candidate(candidate):
        return False
    text = candidate_display_text(candidate) or str(candidate.get("insertText") or "").strip()
    return bool(text) and str(candidate.get("sourceType") or "") in REALTIME_SIDE_SOURCE_TYPES


def first_post_commit_visible_latency_ms(events: list[dict[str, Any]]) -> int:
    anchor_ms = -1
    best_ms: int | None = None
    for event in events:
        name = str(event.get("event") or "")
        if name in {
            "commit_observed",
            "side_candidate_commit",
            "side_candidate_commit_observed",
            "post_commit_prediction_scheduled",
            "side_candidate_continuation_scheduled",
        }:
            timestamp = event_timestamp_ms(event)
            if timestamp > 0 and (anchor_ms < 0 or name != "post_commit_prediction_scheduled"):
                anchor_ms = timestamp
        if not event_is_visible_post_commit_panel(event) or anchor_ms < 0:
            continue
        latency = max(0, event_timestamp_ms(event) - anchor_ms)
        best_ms = latency if best_ms is None else min(best_ms, latency)
    return -1 if best_ms is None else best_ms


def collect_context_echo_candidates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    echoes: list[dict[str, Any]] = []
    for event in events:
        if not event_is_visible_post_commit_panel(event):
            continue
        contexts = event_context_strings(event)
        if not contexts:
            continue
        for candidate in event_candidates(event):
            if not candidate_is_real_side_candidate(candidate):
                continue
            text = candidate_display_text(candidate) or str(candidate.get("insertText") or "")
            if candidate_echoes_context(text, contexts):
                echoes.append(
                    {
                        "timestampMs": event.get("timestampMs"),
                        "sourceType": candidate.get("sourceType"),
                        "text": compact_context_sample(text),
                    }
                )
    return echoes


def summarize_visible_source_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    max_counts = {"modelCandidateCount": 0, "ragMemoryCandidateCount": 0, "rimeCandidateCount": 0}
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        counts = source_family_counts(event_candidates(event))
        max_counts["modelCandidateCount"] = max(max_counts["modelCandidateCount"], counts["model"])
        max_counts["ragMemoryCandidateCount"] = max(max_counts["ragMemoryCandidateCount"], counts["ragMemory"])
        max_counts["rimeCandidateCount"] = max(max_counts["rimeCandidateCount"], counts["rime"])
    return max_counts


def summarize_source_badge_coverage(events: list[dict[str, Any]]) -> dict[str, Any]:
    expected = 0
    valid = 0
    missing_by_source: dict[str, int] = {}
    seen_by_source: dict[str, int] = {}
    for candidate in iter_panel_candidates(events):
        source_type = str(candidate.get("sourceType") or "")
        if source_type not in VISIBLE_SOURCE_TYPES:
            continue
        expected += 1
        seen_by_source[source_type] = seen_by_source.get(source_type, 0) + 1
        if source_visual_violation(candidate):
            missing_by_source[source_type] = missing_by_source.get(source_type, 0) + 1
        else:
            valid += 1
    return {
        "expectedCount": expected,
        "validCount": valid,
        "missingCount": expected - valid,
        "coverageRate": round(valid / expected, 4) if expected else 0.0,
        "seenBySource": dict(sorted(seen_by_source.items())),
        "missingBySource": dict(sorted(missing_by_source.items())),
    }


def count_pending_panel_clears(events: list[dict[str, Any]]) -> int:
    previous_real_panel: dict[str, Any] | None = None
    clears = 0
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        if not panel_is_post_commit_event(event):
            continue
        candidates = event_candidates(event)
        real_candidate_visible = any(candidate_is_real_side_candidate(candidate) for candidate in candidates)
        if real_candidate_visible:
            previous_real_panel = event
            continue
        status_only = bool(candidates) and all(isinstance(candidate, dict) and is_status_candidate(candidate) for candidate in candidates)
        if status_only and previous_real_panel is not None:
            elapsed_ms = event_timestamp_ms(event) - event_timestamp_ms(previous_real_panel)
            if 0 <= elapsed_ms <= 1000:
                clears += 1
    return clears


def count_followup_restarts(events: list[dict[str, Any]]) -> int:
    restart_events = {
        "post_commit_followup_restarted",
        "post_commit_model_provider_restarted",
        "model_provider_restarted",
    }
    count = 0
    for event in events:
        name = str(event.get("event") or "")
        if name in restart_events:
            count += 1
            continue
        if name != "sidecar_request_scheduled":
            continue
        if not bool(event.get("progressiveFollowUp") or event.get("followup") or event.get("isFollowup")):
            continue
        if bool(event.get("providerRestarted") or event.get("modelProviderRestarted")):
            count += 1
    return count


def event_candidates(event: dict[str, Any]) -> list[Any]:
    candidates = event.get("candidates")
    return candidates if isinstance(candidates, list) else []


def event_context_strings(event: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("committedContext", "committedContextSuffix", "commitTextPreview", "previousCommittedContext"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            values.append(" ".join(value.split()))
    session = event.get("predictionSession")
    if isinstance(session, dict):
        for key in ("committedContext", "committedContextSuffix", "commitTextPreview"):
            value = session.get(key)
            if isinstance(value, str) and value.strip():
                values.append(" ".join(value.split()))
    return values


def candidate_echoes_context(text: str, contexts: list[str]) -> bool:
    normalized = " ".join(str(text or "").split())
    if len(normalized) < 2:
        return False
    for context in contexts:
        if len(context) < 2:
            continue
        if normalized == context:
            return True
        if len(normalized) >= 4 and normalized in context:
            return True
    return False


def compact_context_sample(value: str) -> str:
    compact = " ".join(str(value or "").split())
    return compact[:48]


def summarize_required_trace_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    statuses = {
        "rime_composition_started": trace_event_status(
            events,
            direct_names={"rime_composition_started"},
            alias_names={"sidecar_request_scheduled"},
            alias_predicate=lambda event: bool(str(event.get("rawInput") or event.get("preedit") or "")),
        ),
        "rime_composition_candidates_visible": trace_event_status(
            events,
            direct_names={"rime_composition_candidates_visible"},
            alias_names={"panel_display_candidates"},
            alias_predicate=lambda event: is_rime_composition_panel(event),
        ),
        "rime_commit_observed": trace_event_status(
            events,
            direct_names={"rime_commit_observed"},
            alias_names={"commit_observed"},
        ),
        "post_commit_prediction_scheduled": trace_event_status(
            events,
            direct_names={"post_commit_prediction_scheduled"},
            alias_names={"side_candidate_continuation_scheduled"},
        ),
        "sidecar_request_sent": trace_event_status(
            events,
            direct_names={"sidecar_request_sent"},
            alias_names={"sidecar_request_scheduled"},
        ),
        "sidecar_response_received": trace_event_status(events, direct_names={"sidecar_response_received"}),
        "panel_display_candidates": trace_event_status(events, direct_names={"panel_display_candidates"}),
        "post_commit_prediction_applied": trace_event_status(
            events,
            direct_names={"post_commit_prediction_applied"},
            alias_names={"sidecar_response_applied"},
            alias_predicate=lambda event: str(event.get("uiMode") or "") == "post_commit_prediction"
            or panel_is_post_commit_event(event),
        ),
        "sidecar_response_dropped_stale": trace_event_status(
            events,
            direct_names={"sidecar_response_dropped_stale"},
            alias_names={"sidecar_response_dropped"},
        ),
        "sidecar_progressive_followup_sent": trace_event_status(
            events,
            direct_names={"sidecar_progressive_followup_sent"},
            alias_names={"sidecar_request_scheduled"},
            alias_predicate=lambda event: bool(event.get("progressiveFollowUp") or event.get("followup") or event.get("isFollowup")),
        ),
        "sidecar_progressive_followup_skipped": trace_event_status(
            events,
            direct_names={"sidecar_progressive_followup_skipped"},
        ),
        "candidate_snapshot_selection_accepted": trace_event_status(
            events,
            direct_names={"candidate_snapshot_selection_accepted"},
        ),
        "candidate_snapshot_selection_rejected_stale": trace_event_status(
            events,
            direct_names={"candidate_snapshot_selection_rejected_stale"},
            alias_names={"stale_candidate_selection_rejected"},
        ),
        "side_candidate_commit_observed": trace_event_status(
            events,
            direct_names={"side_candidate_commit_observed"},
            alias_names={"side_candidate_commit"},
        ),
        "delete_context_resynced": trace_event_status(
            events,
            direct_names={"delete_context_resynced"},
            alias_names={"committed_context_resynced_after_delete"},
        ),
        "app_switch_context_invalidated": trace_event_status(
            events,
            direct_names={"app_switch_context_invalidated"},
            alias_names={"frontend_transaction_invalidated"},
            alias_predicate=lambda event: foreground_switch_reason(
                str(event.get("reason") or event.get("invalidationReason") or "")
            )
            and "focus" not in str(event.get("reason") or event.get("invalidationReason") or "").lower(),
        ),
        "focus_context_invalidated": trace_event_status(
            events,
            direct_names={"focus_context_invalidated"},
            alias_names={"frontend_transaction_invalidated"},
            alias_predicate=lambda event: "focus" in str(event.get("reason") or event.get("invalidationReason") or "").lower(),
        ),
    }
    return {name: statuses[name] for name in REQUIRED_TRACE_EVENT_NAMES}


def trace_event_status(
    events: list[dict[str, Any]],
    *,
    direct_names: set[str],
    alias_names: set[str] | None = None,
    alias_predicate: Any | None = None,
) -> dict[str, Any]:
    alias_names = alias_names or set()
    direct = [event for event in events if str(event.get("event") or "") in direct_names]
    aliases = []
    for event in events:
        if str(event.get("event") or "") not in alias_names:
            continue
        if alias_predicate is not None and not alias_predicate(event):
            continue
        aliases.append(event)
    first_event = direct[0] if direct else aliases[0] if aliases else None
    return {
        "observed": bool(direct or aliases),
        "directCount": len(direct),
        "aliasCount": len(aliases),
        "directNames": sorted(direct_names),
        "aliasNames": sorted(alias_names),
        "firstTimestampMs": event_timestamp_ms(first_event) if first_event else 0,
    }


def is_rime_composition_panel(event: dict[str, Any]) -> bool:
    if event.get("event") != "panel_display_candidates":
        return False
    if not (str(event.get("rawInput") or "") or str(event.get("preedit") or "")):
        return False
    candidates = event_candidates(event)
    return bool(candidates) and all(
        isinstance(candidate, dict)
        and not is_status_candidate(candidate)
        and str(candidate.get("sourceType") or "") == SOURCE_RIME
        for candidate in candidates
    )


def summarize_display_quality(
    events: list[dict[str, Any]],
    *,
    frontend_report: dict[str, Any],
    min_model_candidates_per_panel: int = 0,
) -> dict[str, Any]:
    panel_candidates = list(iter_panel_candidates(events))
    source_badge_missing = sum(1 for candidate in panel_candidates if source_visual_violation(candidate))
    long_candidate_violation = sum(1 for candidate in panel_candidates if long_candidate_violation_for(candidate))
    quota_violations = candidate_quota_violations(events)
    ordinal_drift_violations = snapshot_ordinal_drift_violations(events)
    model_panel_coverage = summarize_model_candidate_panel_coverage(
        events,
        min_model_candidates_per_panel=min_model_candidates_per_panel,
    )
    source_triplet_coverage = summarize_source_triplet_panel_coverage(events)
    progressive_events = list(iter_prediction_trace_events(events))
    progressive_appends = [
        event for event in progressive_events if event.get("event") == "candidate_snapshot_progressive_append"
    ]
    progressive_replaces = [
        event for event in progressive_events if event.get("event") == "candidate_snapshot_progressive_replace"
    ]
    return {
        "sourceBadgeMissingCount": source_badge_missing,
        "modelOccupiedAllSlotsViolation": len(quota_violations),
        "longCandidateViolation": long_candidate_violation,
        "postCommitNumberKeyViolation": len(post_commit_number_key_violations(events)),
        "snapshotOrdinalDriftViolation": len(ordinal_drift_violations),
        **model_panel_coverage,
        **source_triplet_coverage,
        "progressiveAppendCount": len(dedupe_trace_events(progressive_appends)),
        "progressiveReplaceCount": len(dedupe_trace_events(progressive_replaces)),
        "candidateQuotaViolations": quota_violations[:20],
        "snapshotOrdinalDriftViolations": ordinal_drift_violations[:20],
        "latestBalancedCandidatePanelPresent": bool(frontend_report.get("latestBalancedCandidatePanel")),
    }


def summarize_source_triplet_panel_coverage(events: list[dict[str, Any]]) -> dict[str, Any]:
    panel_count = 0
    max_family_count = 0
    samples: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        candidates = event.get("candidates")
        if not isinstance(candidates, list):
            continue
        counts = source_family_counts(candidates)
        family_count = sum(
            1
            for present in (
                counts["model"] > 0,
                counts["ragMemory"] > 0,
                counts["rime"] > 0,
            )
            if present
        )
        max_family_count = max(max_family_count, family_count)
        if counts["model"] > 0 and counts["ragMemory"] > 0 and counts["rime"] > 0:
            panel_count += 1
            samples.append(
                {
                    "timestampMs": event.get("timestampMs"),
                    "snapshotId": panel_snapshot_id(event),
                    "sourceFamilyCounts": counts,
                    "phase": prediction_session_phase(event),
                }
            )
    return {
        "sourceTripletPanelCount": panel_count,
        "maxSourceFamilyCountInPanel": max_family_count,
        "sourceTripletPanelSamples": samples[:12],
    }


def source_family_counts(candidates: list[Any]) -> dict[str, int]:
    counts = {"model": 0, "ragMemory": 0, "rime": 0, "other": 0}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            counts["other"] += 1
            continue
        source_type = str(candidate.get("sourceType") or "")
        if source_type == SOURCE_MODEL:
            counts["model"] += 1
        elif source_type in RAG_MEMORY_SOURCE_TYPES:
            counts["ragMemory"] += 1
        elif source_type == SOURCE_RIME:
            counts["rime"] += 1
        else:
            counts["other"] += 1
    return counts


def summarize_model_candidate_panel_coverage(
    events: list[dict[str, Any]],
    *,
    min_model_candidates_per_panel: int,
) -> dict[str, Any]:
    required_per_panel = max(2, int(min_model_candidates_per_panel or 0))
    model_panel_count = 0
    multi_model_panel_count = 0
    max_model_count = 0
    samples: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        candidates = event.get("candidates")
        if not isinstance(candidates, list):
            continue
        model_count = sum(
            1 for candidate in candidates if isinstance(candidate, dict) and str(candidate.get("sourceType") or "") == "model"
        )
        if model_count <= 0:
            continue
        model_panel_count += 1
        max_model_count = max(max_model_count, model_count)
        if model_count >= required_per_panel:
            multi_model_panel_count += 1
        samples.append(
            {
                "timestampMs": event.get("timestampMs"),
                "snapshotId": panel_snapshot_id(event),
                "modelCandidateCount": model_count,
                "visibleCandidateCount": len(candidates),
                "phase": prediction_session_phase(event),
            }
        )
    return {
        "requiredModelCandidatesPerPanel": required_per_panel,
        "modelCandidatePanelCount": model_panel_count,
        "multiModelCandidatePanelCount": multi_model_panel_count,
        "maxModelCandidateCountInPanel": max_model_count,
        "modelCandidatePanelSamples": samples[:12],
    }


def iter_panel_candidates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        panel_candidates = event.get("candidates")
        if not isinstance(panel_candidates, list):
            continue
        for candidate in panel_candidates:
            if isinstance(candidate, dict):
                candidates.append(candidate)
    return candidates


def source_visual_violation(candidate: dict[str, Any]) -> bool:
    source_type = str(candidate.get("sourceType") or "")
    expected_badge = SOURCE_BADGES.get(source_type)
    expected_color = SOURCE_COLOR_TOKENS.get(source_type)
    if expected_badge is None or expected_color is None:
        return False
    observed_badge = str(candidate.get("sourceBadge") or candidate.get("badge") or "")
    observed_color = str(candidate.get("colorToken") or "")
    return observed_badge != expected_badge or observed_color != expected_color


def long_candidate_violation_for(candidate: dict[str, Any]) -> bool:
    source_type = str(candidate.get("sourceType") or "")
    if source_type not in REALTIME_SIDE_SOURCE_TYPES:
        return False
    text = candidate_display_text(candidate)
    if not text:
        return False
    # Candidate rows should be short surfaces, not evidence/debug paragraphs.
    return len(text) > 32


def candidate_display_text(candidate: dict[str, Any]) -> str:
    value = candidate.get("text") or candidate.get("displayText") or ""
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def snapshot_ordinal_drift_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        snapshot_id = panel_snapshot_id(event)
        if not snapshot_id:
            continue
        candidates = event.get("candidates")
        if not isinstance(candidates, list):
            continue
        local_ordinals: set[str] = set()
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            if is_status_candidate(candidate):
                continue
            ordinal = candidate_ordinal(candidate, fallback=index)
            if not ordinal:
                continue
            identity = candidate_stable_identity(candidate)
            if not identity:
                continue
            key = (snapshot_id, ordinal)
            if ordinal in local_ordinals:
                violations.append(
                    {
                        "type": "duplicate_ordinal_in_panel",
                        "timestampMs": event.get("timestampMs"),
                        "snapshotId": snapshot_id,
                        "ordinal": ordinal,
                    }
                )
                continue
            local_ordinals.add(ordinal)
            previous = seen.get(key)
            if previous is not None and previous.get("identity") != identity:
                violations.append(
                    {
                        "type": "snapshot_ordinal_identity_changed",
                        "timestampMs": event.get("timestampMs"),
                        "snapshotId": snapshot_id,
                        "ordinal": ordinal,
                        "previousIdentity": previous.get("identity"),
                        "currentIdentity": identity,
                        "previousTimestampMs": previous.get("timestampMs"),
                    }
                )
                continue
            seen[key] = {
                "identity": identity,
                "timestampMs": event.get("timestampMs"),
            }
    return violations


def candidate_ordinal(candidate: dict[str, Any], *, fallback: int) -> str:
    for key in ("candidateOrdinal", "selectionRank", "selectionKey", "label"):
        if key not in candidate:
            continue
        value = candidate.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return str(fallback)


def is_status_candidate(candidate: dict[str, Any]) -> bool:
    return (
        str(candidate.get("sourceType") or "") == SOURCE_STATUS
        or str(candidate.get("displayLayout") or "") == "status_row"
        or candidate.get("isStatus") is True
    )


def candidate_stable_identity(candidate: dict[str, Any]) -> str:
    explicit = str(candidate.get("candidateStableId") or candidate.get("stableId") or "")
    if explicit:
        return explicit
    text = str(candidate.get("insertText") or candidate.get("text") or candidate.get("displayText") or "")
    return "|".join(
        [
            str(candidate.get("sourceType") or ""),
            str(candidate.get("selectionAction") or ""),
            str(candidate.get("selectionKey") or candidate.get("label") or ""),
            " ".join(text.split()),
        ]
    )


def post_commit_number_key_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    active_post_commit_snapshot = ""
    active_post_commit_panel = False
    for event in events:
        name = str(event.get("event") or "")
        if name == "panel_display_candidates":
            session = event.get("predictionSession")
            session = session if isinstance(session, dict) else {}
            phase = str(session.get("phase") or "")
            selection_scope = str(session.get("selectionScope") or "")
            active_post_commit_panel = phase == "post_commit" or selection_scope == "prediction"
            active_post_commit_snapshot = panel_snapshot_id(event) if active_post_commit_panel else ""
            continue
        if name in {"display_invalidated_by_input_change", "prediction_panel_hard_clear", "prediction_panel_soft_hide"}:
            active_post_commit_panel = False
            active_post_commit_snapshot = ""
            continue
        if name != "number_key_route" or not active_post_commit_panel:
            continue
        candidate = event.get("candidate")
        candidate_snapshot = str(candidate.get("snapshotId") or "") if isinstance(candidate, dict) else ""
        if active_post_commit_snapshot and candidate_snapshot and candidate_snapshot != active_post_commit_snapshot:
            continue
        if isinstance(candidate, dict):
            source_type = str(candidate.get("sourceType") or "")
            selection_action = str(candidate.get("selectionAction") or "")
            if selection_action == "commit_side_candidate" and source_type not in {"", "rime", "raw_english"}:
                continue
        violations.append(
            {
                "event": name,
                "timestampMs": event.get("timestampMs"),
                "key": event.get("key"),
                "snapshotId": candidate_snapshot or active_post_commit_snapshot,
            }
        )
    return violations


def panel_snapshot_id(event: dict[str, Any]) -> str:
    session = event.get("predictionSession")
    if isinstance(session, dict):
        snapshot_id = str(session.get("snapshotId") or session.get("stableSnapshotId") or "")
        if snapshot_id:
            return snapshot_id
    candidates = event.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                snapshot_id = str(candidate.get("snapshotId") or candidate.get("stableSnapshotId") or "")
                if snapshot_id:
                    return snapshot_id
    return str(event.get("snapshotId") or "")


def prediction_session_phase(event: dict[str, Any]) -> str:
    session = event.get("predictionSession")
    if isinstance(session, dict):
        phase = str(session.get("phase") or session.get("selectionScope") or "")
        if phase:
            return phase
    return ""


def summarize_prediction_stability(events: list[dict[str, Any]], *, stale_applied_count: int) -> dict[str, Any]:
    prediction_events = list(iter_prediction_trace_events(events))
    panel_events = [event for event in events if event.get("event") == "panel_display_candidates"]
    snapshot_spans = collect_visible_snapshot_spans(panel_events, prediction_events)
    visible_durations = [span["durationMs"] for span in snapshot_spans if span["snapshotId"]]
    flicker_count = count_prediction_flickers(events, prediction_events)
    min_visible_violations = count_min_visible_violations(prediction_events)
    unique_snapshot_ids = {
        str(span["snapshotId"])
        for span in snapshot_spans
        if span.get("snapshotId")
    }
    unique_snapshot_ids.update(
        str(event.get("snapshotId"))
        for event in prediction_events
        if event.get("snapshotId") and event.get("event") in {"prediction_snapshot_created", "prediction_snapshot_reused"}
    )
    return {
        "visibleSnapshots": len(unique_snapshot_ids),
        "averageVisibleMs": round(sum(visible_durations) / len(visible_durations), 2) if visible_durations else 0,
        "minVisibleViolationCount": min_visible_violations,
        "flickerCount": flicker_count,
        "hardClearCount": sum(1 for event in prediction_events if event.get("event") == "prediction_panel_hard_clear")
        + sum(1 for event in events if event.get("event") == "display_invalidated_by_input_change"),
        "softHoldCount": sum(1 for event in prediction_events if event.get("event") == "prediction_panel_soft_hold"),
        "lastGoodReuseCount": sum(1 for event in prediction_events if prediction_event_reuses_last_good(event)),
        "snapshotSelectionAccepted": sum(
            1 for event in prediction_events if event.get("event") == "candidate_snapshot_selection_accepted"
        ),
        "snapshotSelectionRejectedStale": sum(
            1 for event in prediction_events if event.get("event") == "candidate_snapshot_selection_rejected_stale"
        ),
        "staleSelectionRejected": sum(1 for event in events if event.get("event") == "stale_candidate_selection_rejected"),
        "staleSelectionApplied": stale_applied_count,
        "snapshotSpans": snapshot_spans[:20],
    }


def summarize_selection_quality(events: list[dict[str, Any]], *, paired_side_commit_count: int) -> dict[str, Any]:
    prediction_events = list(iter_prediction_trace_events(events))
    accepted = [
        event for event in prediction_events if event.get("event") == "candidate_snapshot_selection_accepted"
    ]
    rejected_stale = [
        event for event in prediction_events if event.get("event") == "candidate_snapshot_selection_rejected_stale"
    ]
    legacy_stale_rejected_count = sum(1 for event in events if event.get("event") == "stale_candidate_selection_rejected")
    accepted_count = len(dedupe_trace_events(accepted))
    rejected_stale_count = len(dedupe_trace_events(rejected_stale))
    return {
        "snapshotSelectionAcceptedCount": accepted_count,
        "snapshotSelectionRejectedStaleCount": rejected_stale_count,
        "legacyStaleSelectionRejectedCount": legacy_stale_rejected_count,
        "pairedSideCommitCount": paired_side_commit_count,
        "sideCommitWithoutAcceptedSnapshotSelectionCount": max(0, paired_side_commit_count - accepted_count),
        "acceptedSnapshotSelectionWithoutSideCommitCount": max(0, accepted_count - paired_side_commit_count),
    }


def summarize_foreground_coverage(events: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [event_timestamp_ms(event) for event in events if event_timestamp_ms(event) > 0]
    duration_ms = max(timestamps) - min(timestamps) if timestamps else 0
    delete_invalidation_events = [
        event
        for event in events
        if event.get("event") == "display_invalidated_by_input_change"
        and str(event.get("reason") or "") in {"delete_key", "backspace", "delete"}
    ]
    delete_resync_events = [
        event for event in events if event.get("event") == "committed_context_resynced_after_delete"
    ]
    explicit_switch_events = [
        event
        for event in events
        if event.get("event") == "frontend_transaction_invalidated"
        and foreground_switch_reason(str(event.get("reason") or event.get("invalidationReason") or ""))
    ]
    app_switch_pairs = collect_front_app_switch_pairs(events)
    input_source_switch_pairs = collect_input_source_switch_pairs(events)
    return {
        "durationMs": duration_ms,
        "durationSec": round(duration_ms / 1000, 3),
        "backspaceCount": len(delete_invalidation_events),
        "deleteResyncCount": len(delete_resync_events),
        "appSwitchCount": len(explicit_switch_events) + len(app_switch_pairs),
        "inputSourceSwitchCount": len(input_source_switch_pairs),
        "explicitSwitchInvalidationCount": len(explicit_switch_events),
        "frontAppSwitchPairs": app_switch_pairs[:10],
        "inputSourceSwitchPairs": input_source_switch_pairs[:10],
    }


def foreground_switch_reason(reason: str) -> bool:
    normalized = reason.lower().replace("-", "_")
    return any(token in normalized for token in ("app", "focus", "input_source", "inputsource"))


def collect_front_app_switch_pairs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return collect_field_switch_pairs(events, "frontAppBundleId")


def collect_input_source_switch_pairs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return collect_field_switch_pairs(events, "inputSourceId")


def collect_field_switch_pairs(events: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    previous_value = ""
    previous_event: dict[str, Any] | None = None
    for event in events:
        value = str(event.get(field) or "")
        if not value:
            session = event.get("predictionSession")
            if isinstance(session, dict):
                value = str(session.get(field) or "")
        if not value:
            continue
        if previous_value and value != previous_value:
            pairs.append(
                {
                    "field": field,
                    "from": previous_value,
                    "to": value,
                    "timestampMs": event.get("timestampMs"),
                    "previousTimestampMs": previous_event.get("timestampMs") if previous_event else None,
                    "event": event.get("event"),
                }
            )
        previous_value = value
        previous_event = event
    return pairs


def summarize_lane_stability(events: list[dict[str, Any]]) -> dict[str, Any]:
    prediction_events = list(iter_prediction_trace_events(events))
    model_timeouts = [
        event
        for event in prediction_events
        if bool(event.get("modelTimedOut")) and str(event.get("event")) in {
            "prediction_lane_timeout_with_holdover",
            "prediction_lane_timeout_without_holdover",
            "prediction_show_decision",
        }
    ]
    model_timeouts_with_holdover = [
        event
        for event in model_timeouts
        if bool(event.get("holdoverHit")) or event.get("event") == "prediction_lane_timeout_with_holdover"
    ]
    rag_timeout_events = [
        event
        for event in prediction_events
        if bool(event.get("ragTimedOut")) and str(event.get("event")) in {
            "prediction_lane_timeout_with_holdover",
            "prediction_lane_timeout_without_holdover",
            "prediction_show_decision",
        }
    ]
    empty_lane_events = [
        event for event in prediction_events if event.get("event") == "prediction_empty_lane_did_not_clear_panel"
    ]
    rag_empty_cleared_panel = [
        event
        for event in prediction_events
        if event.get("event") in {"prediction_panel_soft_hide", "prediction_panel_hard_clear"}
        and "rag" in str(event.get("reason") or event.get("showReason") or "").lower()
        and "empty" in str(event.get("reason") or event.get("showReason") or "").lower()
    ]
    return {
        "modelTimeouts": len(dedupe_trace_events(model_timeouts)),
        "modelTimeoutsWithHoldover": len(dedupe_trace_events(model_timeouts_with_holdover)),
        "ragTimeouts": len(dedupe_trace_events(rag_timeout_events)),
        "ragEmptyCount": len(dedupe_trace_events(empty_lane_events)),
        "ragEmptyClearedPanelCount": len(dedupe_trace_events(rag_empty_cleared_panel)),
        "emptyLaneDidNotClearPanelCount": len(dedupe_trace_events(empty_lane_events)),
    }


def iter_prediction_trace_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "")
        if name in PREDICTION_TRACE_EVENT_NAMES:
            flattened.append(normalize_prediction_trace_event(event))
        nested_events = event.get("predictionTraceEvents")
        if not isinstance(nested_events, list):
            continue
        for nested in nested_events:
            if not isinstance(nested, dict):
                continue
            normalized = normalize_prediction_trace_event(nested)
            normalized.setdefault("timestampMs", event.get("timestampMs"))
            flattened.append(normalized)
    return flattened


def normalize_prediction_trace_event(event: dict[str, Any]) -> dict[str, Any]:
    fields = event.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    normalized = {**fields, **{key: value for key, value in event.items() if key != "fields"}}
    if "timestampMs" not in normalized and event.get("timestampMs") is not None:
        normalized["timestampMs"] = event.get("timestampMs")
    return normalized


def collect_visible_snapshot_spans(
    panel_events: list[dict[str, Any]],
    prediction_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    for event in panel_events:
        snapshot_id = panel_snapshot_id(event)
        if not snapshot_id:
            continue
        timestamp = event_timestamp_ms(event)
        first_seen.setdefault(snapshot_id, timestamp)
        last_seen[snapshot_id] = max(timestamp, last_seen.get(snapshot_id, timestamp))
    for event in prediction_events:
        if str(event.get("event") or "").startswith("candidate_snapshot_selection_"):
            continue
        snapshot_id = str(event.get("snapshotId") or "")
        if not snapshot_id:
            continue
        timestamp = event_timestamp_ms(event)
        first_seen.setdefault(snapshot_id, timestamp)
        last_seen[snapshot_id] = max(timestamp, last_seen.get(snapshot_id, timestamp))
    return [
        {
            "snapshotId": snapshot_id,
            "firstSeenMs": first_seen[snapshot_id],
            "lastSeenMs": last_seen.get(snapshot_id, first_seen[snapshot_id]),
            "durationMs": max(0, last_seen.get(snapshot_id, first_seen[snapshot_id]) - first_seen[snapshot_id]),
        }
        for snapshot_id in sorted(first_seen, key=lambda key: first_seen[key])
    ]


def panel_snapshot_id(event: dict[str, Any]) -> str:
    prediction_session = event.get("predictionSession")
    if isinstance(prediction_session, dict):
        snapshot_id = str(prediction_session.get("snapshotId") or prediction_session.get("stableSnapshotId") or "")
        if snapshot_id:
            return snapshot_id
    candidates = event.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                snapshot_id = str(candidate.get("snapshotId") or candidate.get("stableSnapshotId") or "")
                if snapshot_id:
                    return snapshot_id
    return str(event.get("snapshotId") or "")


def panel_candidate_count(event: dict[str, Any]) -> int:
    counts = event.get("candidateCounts")
    if isinstance(counts, dict):
        total = _optional_int(counts.get("total"))
        if total is not None:
            return total
    candidates = event.get("candidates")
    if isinstance(candidates, list):
        return len(candidates)
    return _optional_int(event.get("displayCount")) or _optional_int(event.get("visibleCandidateCount")) or 0


def count_prediction_flickers(events: list[dict[str, Any]], prediction_events: list[dict[str, Any]]) -> int:
    flickers = sum(1 for event in prediction_events if event.get("event") == "prediction_panel_soft_hide")
    previous_visible: dict[str, Any] | None = None
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        count = panel_candidate_count(event)
        if previous_visible and count == 0 and event_timestamp_ms(event) - event_timestamp_ms(previous_visible) <= 500:
            flickers += 1
        if count > 0:
            previous_visible = event
    return flickers


def count_min_visible_violations(prediction_events: list[dict[str, Any]]) -> int:
    count = 0
    for event in prediction_events:
        if event.get("event") not in {"prediction_panel_soft_hide", "prediction_panel_hard_clear"}:
            continue
        remaining = _optional_int(event.get("minVisibleRemainingMs"))
        if remaining is not None and remaining > 0 and event.get("event") == "prediction_panel_soft_hide":
            count += 1
    return count


def prediction_event_reuses_last_good(event: dict[str, Any]) -> bool:
    action = str(event.get("action") or "")
    if bool(event.get("reusedLastGood")):
        return True
    return event.get("event") == "prediction_snapshot_reused" or action in {"soft_hold", "reuse_last_good", "prefix_filter"}


def dedupe_trace_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int]] = set()
    unique: list[dict[str, Any]] = []
    for event in events:
        key = (
            str(event.get("event") or ""),
            str(event.get("snapshotId") or event.get("hardContextAnchor") or ""),
            event_timestamp_ms(event),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def collect_number_key_side_commit_pairs(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    unmatched_routes: list[dict[str, Any]] = []
    for route_index, route_event in enumerate(events):
        if not is_side_selection_route_event(route_event):
            continue
        if not isinstance(route_event.get("candidate"), dict):
            continue
        matched_commit: dict[str, Any] | None = None
        for commit_event in events[route_index + 1 :]:
            if commit_event.get("event") == "number_key_route":
                break
            if not is_valid_side_commit_event(commit_event):
                continue
            if candidates_match_selection_route(route_event, commit_event):
                matched_commit = commit_event
            break
        if matched_commit:
            pairs.append({"route": route_event, "commit": matched_commit})
        else:
            unmatched_routes.append(
                {
                    "timestampMs": route_event.get("timestampMs"),
                    "key": route_event.get("key"),
                    "candidate": summarize_event(route_event).get("candidate") if summarize_event(route_event) else None,
                }
            )
    return pairs, unmatched_routes


def collect_post_commit_followups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for commit_index, commit_event in enumerate(events):
        if not is_valid_side_commit_event(commit_event):
            continue
        match = post_commit_followup_after_commit(events, commit_index, commit_event)
        if match:
            matches.append(match)
    return matches


def summarize_chaining(events: list[dict[str, Any]]) -> dict[str, Any]:
    valid_commit_indices = [
        index
        for index, event in enumerate(events)
        if is_valid_side_commit_event(event)
    ]
    current_depth = 0
    max_depth = 0
    chained_commit_count = 0
    broken_commit_count = 0
    chain_breaks: list[dict[str, Any]] = []
    for commit_index in valid_commit_indices:
        commit_event = events[commit_index]
        match = post_commit_followup_after_commit(events, commit_index, commit_event)
        if match:
            current_depth += 1
            chained_commit_count += 1
            max_depth = max(max_depth, current_depth)
        else:
            if current_depth > 0:
                chain_breaks.append(
                    {
                        "timestampMs": commit_event.get("timestampMs"),
                        "reason": "missing_post_commit_followup_after_commit",
                        "depthBeforeBreak": current_depth,
                    }
                )
            current_depth = 0
            broken_commit_count += 1
    valid_count = len(valid_commit_indices)
    return {
        "validSideCommitCount": valid_count,
        "chainedCommitCount": chained_commit_count,
        "brokenCommitCount": broken_commit_count,
        "maxChainDepth": max_depth,
        "chainSuccessRate": round(chained_commit_count / valid_count, 4) if valid_count else 0.0,
        "chainBreaks": chain_breaks[:20],
    }


def post_commit_followup_after_commit(
    events: list[dict[str, Any]],
    commit_index: int,
    commit_event: dict[str, Any],
) -> dict[str, Any] | None:
    schedule_event: dict[str, Any] | None = None
    for event in events[commit_index + 1 :]:
        if event.get("event") == "side_candidate_commit":
            break
        if str(event.get("event") or "") in POST_COMMIT_BARRIER_EVENTS:
            return None
        if event.get("event") in {"side_candidate_continuation_scheduled", "post_commit_prediction_scheduled"}:
            schedule_event = event
            continue
        if event.get("event") != "sidecar_request_scheduled":
            continue
        if not is_post_commit_followup_request(event, commit_event):
            continue
        return {"commitIndex": commit_index, "commit": commit_event, "scheduled": schedule_event, "request": event}
    return None


def collect_stale_applied_responses(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "sidecar_response_applied":
            continue
        mismatches: list[str] = []
        mismatches.extend(compare_triplet(event, "FrontendRevision"))
        mismatches.extend(compare_triplet(event, "SelectionEpoch"))
        if mismatches:
            violations.append(
                {
                    "type": "stale_applied_response",
                    "timestampMs": event.get("timestampMs"),
                    "mismatches": mismatches,
                }
            )
    return violations


def compare_triplet(event: dict[str, Any], suffix: str) -> list[str]:
    request_key = f"request{suffix}"
    response_key = f"response{suffix}"
    live_key = f"live{suffix}"
    request_value = event.get(request_key)
    response_value = event.get(response_key)
    live_value = event.get(live_key)
    mismatches: list[str] = []
    if live_value is None:
        return mismatches
    if request_value is not None and str(request_value) != str(live_value):
        mismatches.append(f"{request_key}!={live_key}")
    if response_value is not None and str(response_value) != str(live_value):
        mismatches.append(f"{response_key}!={live_key}")
    return mismatches


def collect_response_receive_apply_pairs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    recent_receive: dict[str, Any] | None = None
    for event in events:
        name = str(event.get("event") or "")
        if name == "sidecar_response_received":
            recent_receive = event
            continue
        if name != "sidecar_response_applied" or recent_receive is None:
            continue
        if response_events_look_related(recent_receive, event):
            pairs.append({"received": recent_receive, "applied": event})
            recent_receive = None
    return pairs


def response_events_look_related(received: dict[str, Any], applied: dict[str, Any]) -> bool:
    for key in ("frontendRevision", "selectionEpoch", "panelSessionId", "compositionHash", "committedContextHash"):
        received_value = received.get(key)
        applied_value = applied.get(key)
        if received_value is None or applied_value is None:
            continue
        if str(received_value) != str(applied_value):
            return False
    return event_timestamp_ms(applied) >= event_timestamp_ms(received)


def summarize_numeric(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": percentile(ordered, 0.50),
        "p95": percentile(ordered, 0.95),
        "max": ordered[-1],
        "avg": round(sum(ordered) / len(ordered), 2),
    }


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, math.ceil(len(values) * fraction) - 1))
    return int(values[index])


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


if __name__ == "__main__":
    raise SystemExit(main())
