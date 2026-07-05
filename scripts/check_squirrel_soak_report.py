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
    build_report,
    candidates_match_number_route,
    event_timestamp_ms,
    is_post_commit_followup_request,
    is_valid_side_commit_event,
    load_events,
    report_passes,
    summarize_event,
)


DEFAULT_REPORT_PATH = Path("/tmp/rag-ime-squirrel-soak-report.json")


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
    parser.add_argument("--min-sidecar-requests", type=int, default=1)
    parser.add_argument("--min-sidecar-applied", type=int, default=1)
    parser.add_argument("--min-panel-displays", type=int, default=1)
    parser.add_argument("--min-side-commits", type=int, default=1)
    parser.add_argument("--min-post-commit-followups", type=int, default=1)
    parser.add_argument("--max-stale-applied", type=int, default=0)
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
            min_sidecar_requests=max(0, args.min_sidecar_requests),
            min_sidecar_applied=max(0, args.min_sidecar_applied),
            min_panel_displays=max(0, args.min_panel_displays),
            min_side_commits=max(0, args.min_side_commits),
            min_post_commit_followups=max(0, args.min_post_commit_followups),
            max_stale_applied=max(0, args.max_stale_applied),
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
    min_sidecar_requests: int,
    min_sidecar_applied: int,
    min_panel_displays: int,
    min_side_commits: int,
    min_post_commit_followups: int,
    max_stale_applied: int,
) -> dict[str, Any]:
    event_counts = Counter(str(event.get("event") or "") for event in events if isinstance(event, dict))
    side_commit_pairs, unmatched_routes = collect_number_key_side_commit_pairs(events)
    post_commit_followups = collect_post_commit_followups(events)
    stale_applied = collect_stale_applied_responses(events)

    frontend_ok = report_passes(
        frontend_report,
        require_mixed_panel=require_mixed_panel,
        require_side_panel=require_side_panel,
        require_side_commit=require_side_commit,
        require_commit_observed=require_commit_observed,
        require_post_commit_followup=require_post_commit_followup,
        require_delete_resync=require_delete_resync,
        require_modern_prediction_session=require_modern_prediction_session,
    )

    thresholds = {
        "minSidecarRequests": min_sidecar_requests,
        "minSidecarApplied": min_sidecar_applied,
        "minPanelDisplays": min_panel_displays,
        "minSideCommits": min_side_commits,
        "minPostCommitFollowups": min_post_commit_followups,
        "maxStaleApplied": max_stale_applied,
    }
    threshold_results = {
        "sidecarRequests": int(event_counts.get("sidecar_request_scheduled", 0)) >= min_sidecar_requests,
        "sidecarApplied": int(event_counts.get("sidecar_response_applied", 0)) >= min_sidecar_applied,
        "panelDisplays": int(event_counts.get("panel_display_candidates", 0)) >= min_panel_displays,
        "sideCommits": len(side_commit_pairs) >= min_side_commits,
        "postCommitFollowups": len(post_commit_followups) >= min_post_commit_followups,
        "staleApplied": len(stale_applied) <= max_stale_applied,
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
        },
        "thresholds": thresholds,
        "thresholdResults": threshold_results,
        "manualRequired": [item for item in manual_required if item],
        "metrics": {
            "numberKeyRouteCount": int(event_counts.get("number_key_route", 0)),
            "pairedSideCommitCount": len(side_commit_pairs),
            "unmatchedNumberKeyRouteCount": len(unmatched_routes),
            "postCommitFollowupCount": len(post_commit_followups),
            "deleteResyncObserved": bool(frontend_report.get("latestDeleteResync")),
            "staleAppliedResponseCount": len(stale_applied),
            "staleResponseDropCount": int(event_counts.get("sidecar_response_dropped_stale", 0))
            + int(event_counts.get("sidecar_response_dropped", 0)),
            "staleSelectionRejectedCount": int(event_counts.get("stale_candidate_selection_rejected", 0)),
        },
        "latency": {
            "responseAgeMs": summarize_numeric(response_age_values),
            "responseReceivedToAppliedMs": summarize_numeric(response_apply_values),
            "postCommitFollowupMs": summarize_numeric(post_commit_followup_values),
        },
        "violations": violations,
        "frontendTrace": frontend_report,
        "passed": passed,
    }


def collect_number_key_side_commit_pairs(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    unmatched_routes: list[dict[str, Any]] = []
    for route_index, route_event in enumerate(events):
        if route_event.get("event") != "number_key_route":
            continue
        if not isinstance(route_event.get("candidate"), dict):
            continue
        matched_commit: dict[str, Any] | None = None
        for commit_event in events[route_index + 1 :]:
            if commit_event.get("event") == "number_key_route":
                break
            if not is_valid_side_commit_event(commit_event):
                continue
            if candidates_match_number_route(route_event, commit_event):
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
        schedule_event: dict[str, Any] | None = None
        for event in events[commit_index + 1 :]:
            if event.get("event") == "side_candidate_commit":
                break
            if event.get("event") in {"side_candidate_continuation_scheduled", "post_commit_prediction_scheduled"}:
                schedule_event = event
                continue
            if event.get("event") != "sidecar_request_scheduled":
                continue
            if not is_post_commit_followup_request(event, commit_event):
                continue
            matches.append({"commit": commit_event, "scheduled": schedule_event, "request": event})
            break
    return matches


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


if __name__ == "__main__":
    raise SystemExit(main())
