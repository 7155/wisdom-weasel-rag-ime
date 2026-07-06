#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

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


DEFAULT_REPORT_PATH = Path("/tmp/rag-ime-squirrel-soak-report.json")
POST_COMMIT_BARRIER_EVENTS = {
    "commit_observe_timeout",
    "post_commit_chain_cancelled",
    "display_invalidated_by_input_change",
    "frontend_transaction_invalidated",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate a machine-readable Squirrel foreground soak report.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
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
    parser.add_argument("--min-sidecar-requests", type=int, default=1)
    parser.add_argument("--min-sidecar-applied", type=int, default=1)
    parser.add_argument("--min-panel-displays", type=int, default=1)
    parser.add_argument("--min-side-commits", type=int, default=1)
    parser.add_argument("--min-post-commit-followups", type=int, default=1)
    parser.add_argument(
        "--min-chain-depth",
        type=int,
        default=0,
        help="Require this many consecutive side-candidate commits with matching post-commit follow-up requests.",
    )
    parser.add_argument("--max-stale-applied", type=int, default=0)
    parser.add_argument("--max-flicker-count", type=int, default=0)
    parser.add_argument("--max-min-visible-violations", type=int, default=0)
    parser.add_argument("--max-rag-empty-cleared-panel", type=int, default=0)
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
    while True:
        events = load_events(log_path)
        frontend_report = build_report(events, log_path=log_path, print_last=max(0, args.print_last))
        soak_report = build_soak_report(
            events,
            frontend_report=frontend_report,
            log_path=log_path,
            manual_required=args.manual_required,
            require_mixed_panel=args.require_mixed_panel,
            require_side_panel=args.require_side_panel,
            require_side_commit=args.require_side_commit,
            require_commit_observed=args.require_commit_observed,
            require_post_commit_followup=args.require_post_commit_followup,
            require_delete_resync=args.require_delete_resync,
            require_modern_prediction_session=args.require_modern_prediction_session,
            require_balanced_quota=args.require_balanced_quota,
            min_sidecar_requests=max(0, args.min_sidecar_requests),
            min_sidecar_applied=max(0, args.min_sidecar_applied),
            min_panel_displays=max(0, args.min_panel_displays),
            min_side_commits=max(0, args.min_side_commits),
            min_post_commit_followups=max(0, args.min_post_commit_followups),
            min_chain_depth=max(0, args.min_chain_depth),
            max_stale_applied=max(0, args.max_stale_applied),
            max_flicker_count=max(0, args.max_flicker_count),
            max_min_visible_violations=max(0, args.max_min_visible_violations),
            max_rag_empty_cleared_panel=max(0, args.max_rag_empty_cleared_panel),
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
    manual_required: list[str],
    require_mixed_panel: bool,
    require_side_panel: bool,
    require_side_commit: bool,
    require_commit_observed: bool,
    require_post_commit_followup: bool,
    require_delete_resync: bool,
    require_modern_prediction_session: bool,
    require_balanced_quota: bool,
    min_sidecar_requests: int,
    min_sidecar_applied: int,
    min_panel_displays: int,
    min_side_commits: int,
    min_post_commit_followups: int,
    min_chain_depth: int,
    max_stale_applied: int,
    max_flicker_count: int,
    max_min_visible_violations: int,
    max_rag_empty_cleared_panel: int,
) -> dict[str, Any]:
    event_counts = Counter(str(event.get("event") or "") for event in events if isinstance(event, dict))
    side_commit_pairs, unmatched_routes = collect_number_key_side_commit_pairs(events)
    post_commit_followups = collect_post_commit_followups(events)
    chain = summarize_chaining(events)
    stale_applied = collect_stale_applied_responses(events)
    prediction_stability = summarize_prediction_stability(events, stale_applied_count=len(stale_applied))
    lane_stability = summarize_lane_stability(events)
    display_quality = summarize_display_quality(events, frontend_report=frontend_report)
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
        "minChainDepth": min_chain_depth,
        "maxStaleApplied": max_stale_applied,
        "maxFlickerCount": max_flicker_count,
        "maxMinVisibleViolations": max_min_visible_violations,
        "maxRagEmptyClearedPanel": max_rag_empty_cleared_panel,
    }
    threshold_results = {
        "sidecarRequests": int(event_counts.get("sidecar_request_scheduled", 0)) >= min_sidecar_requests,
        "sidecarApplied": int(event_counts.get("sidecar_response_applied", 0)) >= min_sidecar_applied,
        "panelDisplays": int(event_counts.get("panel_display_candidates", 0)) >= min_panel_displays,
        "sideCommits": len(side_commit_pairs) >= min_side_commits,
        "postCommitFollowups": len(post_commit_followups) >= min_post_commit_followups,
        "chainDepth": int(chain["maxChainDepth"]) >= min_chain_depth,
        "staleApplied": len(stale_applied) <= max_stale_applied,
        "flickerCount": int(prediction_stability["flickerCount"]) <= max_flicker_count,
        "minVisibleViolations": int(prediction_stability["minVisibleViolationCount"]) <= max_min_visible_violations,
        "ragEmptyClearedPanel": int(lane_stability["ragEmptyClearedPanelCount"]) <= max_rag_empty_cleared_panel,
    }

    violations: list[dict[str, Any]] = []
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
        "schemaVersion": "rag-ime.squirrel-soak-report.v1",
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
        },
        "thresholds": thresholds,
        "thresholdResults": threshold_results,
        "manualRequired": [item for item in manual_required if item],
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
            "staleAppliedResponseCount": len(stale_applied),
            "staleResponseDropCount": int(event_counts.get("sidecar_response_dropped_stale", 0))
            + int(event_counts.get("sidecar_response_dropped", 0)),
            "staleSelectionRejectedCount": int(event_counts.get("stale_candidate_selection_rejected", 0)),
        },
        "predictionStability": prediction_stability,
        "laneStability": lane_stability,
        "displayQuality": display_quality,
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


PREDICTION_TRACE_EVENT_NAMES = {
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


def summarize_display_quality(events: list[dict[str, Any]], *, frontend_report: dict[str, Any]) -> dict[str, Any]:
    panel_candidates = list(iter_panel_candidates(events))
    source_badge_missing = sum(1 for candidate in panel_candidates if source_visual_violation(candidate))
    long_candidate_violation = sum(1 for candidate in panel_candidates if long_candidate_violation_for(candidate))
    quota_violations = candidate_quota_violations(events)
    ordinal_drift_violations = snapshot_ordinal_drift_violations(events)
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
        "progressiveAppendCount": len(dedupe_trace_events(progressive_appends)),
        "progressiveReplaceCount": len(dedupe_trace_events(progressive_replaces)),
        "candidateQuotaViolations": quota_violations[:20],
        "snapshotOrdinalDriftViolations": ordinal_drift_violations[:20],
        "latestBalancedCandidatePanelPresent": bool(frontend_report.get("latestBalancedCandidatePanel")),
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
    if source_type not in {"model", "rag", "memory"}:
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
    value = (
        candidate.get("candidateOrdinal")
        or candidate.get("selectionRank")
        or candidate.get("selectionKey")
        or candidate.get("label")
        or fallback
    )
    return str(value)


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
        "staleSelectionRejected": sum(1 for event in events if event.get("event") == "stale_candidate_selection_rejected"),
        "staleSelectionApplied": stale_applied_count,
        "snapshotSpans": snapshot_spans[:20],
    }


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
