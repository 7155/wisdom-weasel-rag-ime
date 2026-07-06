#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path.home() / "Library" / "Logs" / "RagIme" / "squirrel-frontend.jsonl"
SOURCE_BADGES = {
    "rime": "词",
    "model": "模",
    "rag": "查",
    "memory": "忆",
    "raw_english": "input",
}
SOURCE_COLOR_TOKENS = {
    "rime": "rimeOrange",
    "model": "modelBlue",
    "rag": "ragTeal",
    "memory": "memoryPurple",
    "raw_english": "rawGray",
}
SIDE_SELECTION_ROUTE_EVENTS = {"number_key_route", "tab_key_route", "option_number_route"}
USER_TEXT_TRACE_KEYS = {
    "rawInput",
    "preedit",
    "requestRawInput",
    "responseRawInput",
    "currentRawInput",
    "requestPreedit",
    "responsePreedit",
    "commitTextPreview",
    "committedText",
    "committedContextSuffix",
    "query",
    "text",
    "insertText",
    "comment",
    "evidencePreview",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local Squirrel RAG-IME frontend trace events.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--clear", action="store_true", help="Delete the current trace log and exit unless --wait is set.")
    parser.add_argument("--wait", type=float, default=0.0, help="Wait this many seconds for required events.")
    parser.add_argument("--require-mixed-panel", action="store_true")
    parser.add_argument("--require-side-panel", action="store_true")
    parser.add_argument("--require-side-commit", action="store_true")
    parser.add_argument("--require-commit-observed", action="store_true")
    parser.add_argument("--require-post-commit-followup", action="store_true")
    parser.add_argument("--require-delete-resync", action="store_true")
    parser.add_argument("--require-modern-prediction-session", action="store_true")
    parser.add_argument(
        "--require-balanced-quota",
        action="store_true",
        help="Require visible model/RAG/Rime candidates to obey product quota rules.",
    )
    parser.add_argument("--print-last", type=int, default=5)
    args = parser.parse_args()

    log_path = Path(args.log_path).expanduser()
    if args.clear and log_path.exists():
        log_path.unlink()

    deadline = time.monotonic() + max(0.0, args.wait)
    report: dict[str, Any] = {}
    while True:
        events = load_events(log_path)
        report = build_report(events, log_path=log_path, print_last=max(0, args.print_last))
        if report_passes(
            report,
            require_mixed_panel=args.require_mixed_panel,
            require_side_panel=args.require_side_panel,
            require_side_commit=args.require_side_commit,
            require_commit_observed=args.require_commit_observed,
            require_post_commit_followup=args.require_post_commit_followup,
            require_delete_resync=args.require_delete_resync,
            require_modern_prediction_session=args.require_modern_prediction_session,
            require_balanced_quota=args.require_balanced_quota,
        ):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    report["required"] = {
        "mixedPanel": bool(args.require_mixed_panel),
        "sidePanel": bool(args.require_side_panel),
        "sideCommit": bool(args.require_side_commit),
        "commitObserved": bool(args.require_commit_observed),
        "postCommitFollowup": bool(args.require_post_commit_followup),
        "deleteResync": bool(args.require_delete_resync),
        "modernPredictionSession": bool(args.require_modern_prediction_session),
        "balancedQuota": bool(args.require_balanced_quota),
    }
    report["passed"] = report_passes(
        report,
        require_mixed_panel=args.require_mixed_panel,
        require_side_panel=args.require_side_panel,
        require_side_commit=args.require_side_commit,
        require_commit_observed=args.require_commit_observed,
        require_post_commit_followup=args.require_post_commit_followup,
        require_delete_resync=args.require_delete_resync,
        require_modern_prediction_session=args.require_modern_prediction_session,
        require_balanced_quota=args.require_balanced_quota,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def load_events(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def build_report(events: list[dict[str, Any]], *, log_path: Path, print_last: int) -> dict[str, Any]:
    mixed_panel = latest_matching(events, is_mixed_panel_event)
    side_panel = latest_matching(events, is_side_panel_event)
    mixed_text_layout = latest_matching(events, is_mixed_text_layout_event)
    side_commit = latest_matching(events, lambda event: event.get("event") == "side_candidate_commit")
    valid_side_commit = latest_matching(events, is_valid_side_commit_event)
    number_route = latest_matching(events, lambda event: event.get("event") == "number_key_route")
    side_selection_route = latest_matching(events, is_side_selection_route_event)
    sidecar_response = latest_matching(events, lambda event: event.get("event") == "sidecar_response_applied")
    balanced_candidate_panel = latest_matching(events, is_balanced_candidate_quota_event)
    stale_response_drop = latest_matching(events, is_stale_response_drop_event)
    stale_selection_rejected = latest_matching(events, lambda event: event.get("event") == "stale_candidate_selection_rejected")
    modern_prediction_session = latest_matching(events, is_modern_prediction_session_event)
    prediction_trace_events = [event for event in events if is_prediction_trace_event(event)]
    commit_observed = latest_matching(events, lambda event: event.get("event") == "commit_observed")
    delete_resync = latest_delete_resync(events)
    post_delete_context_use = latest_post_delete_context_use(events, delete_resync)
    post_commit_barrier_violations = collect_post_commit_barrier_violations(events)
    trace_privacy_violations = collect_trace_privacy_violations(events)
    side_commit_barrier_ms = max(
        event_timestamp_ms(mixed_panel),
        event_timestamp_ms(side_panel),
        event_timestamp_ms(mixed_text_layout),
        event_timestamp_ms(modern_prediction_session),
    )
    historical_number_key_side_commit = latest_number_key_side_commit(events)
    number_key_side_commit = latest_number_key_side_commit(events, min_timestamp_ms=side_commit_barrier_ms)
    historical_side_selection_commit = latest_side_selection_commit(events)
    side_selection_commit = latest_side_selection_commit(events, min_timestamp_ms=side_commit_barrier_ms)
    post_commit_followup = latest_post_commit_followup(events, min_timestamp_ms=side_commit_barrier_ms)
    return {
        "schemaVersion": "rag-ime.squirrel-frontend-trace-check.v1",
        "logPath": str(log_path),
        "eventCount": len(events),
        "latestSidecarResponse": summarize_event(sidecar_response),
        "latestBalancedCandidatePanel": summarize_event(balanced_candidate_panel),
        "candidateQuotaViolations": candidate_quota_violations(events),
        "latestStaleResponseDrop": summarize_event(stale_response_drop),
        "latestStaleSelectionRejected": summarize_event(stale_selection_rejected),
        "frontendTransactionViolations": frontend_transaction_violations(events),
        "latestModernPredictionSession": summarize_event(modern_prediction_session),
        "latestPredictionTraceEvents": [summarize_event(event) for event in prediction_trace_events[-8:]],
        "latestCommitObserved": summarize_event(commit_observed),
        "latestDeleteResync": summarize_delete_resync(delete_resync),
        "latestPostDeleteContextUse": summarize_post_delete_context_use(post_delete_context_use),
        "postDeleteContextViolations": post_delete_context_violations(events, delete_resync),
        "postCommitBarrierViolations": post_commit_barrier_violations,
        "tracePrivacyViolations": trace_privacy_violations,
        "latestMixedPanel": summarize_event(mixed_panel),
        "latestSidePanel": summarize_event(side_panel),
        "latestMixedTextLayout": summarize_event(mixed_text_layout),
        "latestNumberKeyRoute": summarize_event(number_route),
        "latestSideSelectionRoute": summarize_event(side_selection_route),
        "latestSideCommit": summarize_event(side_commit),
        "latestValidSideCommit": summarize_event(valid_side_commit),
        "sideCommitBarrierTimestampMs": side_commit_barrier_ms,
        "latestSideSelectionCommit": summarize_side_selection_commit(side_selection_commit),
        "latestHistoricalSideSelectionCommit": summarize_side_selection_commit(historical_side_selection_commit),
        "latestNumberKeySideCommit": summarize_number_key_side_commit(number_key_side_commit),
        "latestHistoricalNumberKeySideCommit": summarize_number_key_side_commit(historical_number_key_side_commit),
        "latestPostCommitFollowup": summarize_post_commit_followup(post_commit_followup),
        "lastEvents": [summarize_event(event) for event in events[-print_last:]] if print_last else [],
    }


def latest_matching(events: list[dict[str, Any]], predicate: Any) -> dict[str, Any] | None:
    for event in reversed(events):
        if predicate(event):
            return event
    return None


def event_timestamp_ms(event: dict[str, Any] | None) -> int:
    if not event:
        return 0
    try:
        return int(event.get("timestampMs") or 0)
    except (TypeError, ValueError):
        return 0


def is_mixed_panel_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "panel_display_candidates":
        return False
    counts = event.get("candidateCounts")
    candidates = event.get("candidates")
    return (
        isinstance(counts, dict)
        and int(counts.get("modelInline") or 0) > 0
        and int(counts.get("ragBlock") or 0) > 0
        and bool(event.get("forcesHorizontalLayout"))
        and visible_candidates_are_side_first(candidates)
    )


def is_side_panel_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "panel_display_candidates":
        return False
    counts = event.get("candidateCounts")
    if not isinstance(counts, dict):
        return False
    side_count = int(counts.get("modelInline") or 0) + int(counts.get("ragBlock") or 0)
    if side_count <= 0:
        return False
    candidates = event.get("candidates")
    if isinstance(candidates, list):
        return visible_candidates_have_selectable_side(candidates)
    return True


def is_mixed_text_layout_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "panel_text_layout":
        return False
    counts = event.get("candidateCounts")
    if not isinstance(counts, dict) or not bool(event.get("forcesHorizontalLayout")):
        return False
    if bool(event.get("vertical")):
        return False
    model_inline = int(counts.get("modelInline") or 0)
    rag_block = int(counts.get("ragBlock") or 0)
    separators = event.get("separators")
    candidates = event.get("candidates")
    if model_inline <= 0 or rag_block <= 0 or not isinstance(separators, list):
        return False
    if not visible_candidates_are_side_first(candidates):
        return False
    if len(separators) <= model_inline:
        return False
    for index in range(1, model_inline):
        if str(separators[index]) == "\n":
            return False
    return str(separators[model_inline]) == "\n"


def visible_candidates_have_selectable_side(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return False
    side_indices: list[int] = []
    rime_indices: list[int] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            return False
        label = str(candidate.get("label") or "")
        selection_key = str(candidate.get("selectionKey") or label)
        expected_label = "0" if index == 9 else str(index + 1)
        if label and label != expected_label:
            return False
        if selection_key and label and selection_key != label:
            return False

        source_type = str(candidate.get("sourceType") or "")
        if not candidate_source_visuals_match(candidate):
            return False
        selection_action = str(candidate.get("selectionAction") or "")
        if source_type == "model":
            side_indices.append(index)
            if selection_action != "commit_side_candidate":
                return False
        elif source_type in {"rag", "memory"}:
            side_indices.append(index)
            if selection_action != "commit_side_candidate":
                return False
        elif source_type == "rime":
            rime_indices.append(index)
            if selection_action and selection_action != "select_rime_candidate":
                return False
        else:
            return False
    if not side_indices:
        return False
    if rime_indices and min(rime_indices) < max(side_indices):
        return False
    return True


def visible_candidates_are_side_first(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return True
    model_indices: list[int] = []
    rag_indices: list[int] = []
    rime_indices: list[int] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            return False
        label = str(candidate.get("label") or "")
        selection_key = str(candidate.get("selectionKey") or label)
        expected_label = "0" if index == 9 else str(index + 1)
        if label and label != expected_label:
            return False
        if selection_key and label and selection_key != label:
            return False

        source_type = str(candidate.get("sourceType") or "")
        if not candidate_source_visuals_match(candidate):
            return False
        display_layout = str(candidate.get("displayLayout") or "")
        display_lane = str(candidate.get("displayLane") or "")
        selection_action = str(candidate.get("selectionAction") or "")
        if source_type == "model":
            model_indices.append(index)
            if display_layout != "inline" or display_lane != "model" or selection_action != "commit_side_candidate":
                return False
        elif source_type in {"rag", "memory"}:
            rag_indices.append(index)
            if display_layout != "block" or display_lane != "memory" or selection_action != "commit_side_candidate":
                return False
        elif source_type == "rime":
            rime_indices.append(index)
            if selection_action and selection_action != "select_rime_candidate":
                return False
        else:
            return False

    if not model_indices or not rag_indices:
        return False
    side_indices = model_indices + rag_indices
    if max(model_indices) > min(rag_indices):
        return False
    if rime_indices and min(rime_indices) < max(side_indices):
        return False
    return True


def is_balanced_candidate_quota_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "panel_display_candidates":
        return False
    candidates = event.get("candidates")
    return visible_candidates_obey_balanced_quota(candidates)


def visible_candidates_obey_balanced_quota(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return False
    counts = candidate_source_counts(candidates)
    side_count = counts["model"] + counts["rag"] + counts["memory"]
    if side_count <= 0:
        return True
    if counts["model"] > 2 and (counts["rag"] + counts["memory"]) > 0:
        return False
    if counts["model"] > 3 and (counts["rag"] + counts["memory"]) == 0:
        return False
    return visible_candidates_have_selectable_side(candidates)


def candidate_source_counts(candidates: Any) -> dict[str, int]:
    counts = {"model": 0, "rag": 0, "memory": 0, "rime": 0, "raw_english": 0, "other": 0}
    if not isinstance(candidates, list):
        return counts
    for candidate in candidates:
        if not isinstance(candidate, dict):
            counts["other"] += 1
            continue
        source_type = str(candidate.get("sourceType") or "")
        if source_type in counts:
            counts[source_type] += 1
        else:
            counts["other"] += 1
    return counts


def candidate_quota_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        candidates = event.get("candidates")
        counts = candidate_source_counts(candidates)
        if counts["model"] > 2 and (counts["rag"] + counts["memory"]) > 0:
            violations.append(
                {
                    "event": "panel_display_candidates",
                    "timestampMs": event.get("timestampMs"),
                    "reason": "model_candidates_exceed_quota_when_rag_or_memory_visible",
                    "sourceCounts": counts,
                }
            )
        elif counts["model"] > 3 and (counts["rag"] + counts["memory"]) == 0:
            violations.append(
                {
                    "event": "panel_display_candidates",
                    "timestampMs": event.get("timestampMs"),
                    "reason": "model_only_candidates_exceed_quota",
                    "sourceCounts": counts,
                }
            )
    return violations


def is_valid_side_commit_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "side_candidate_commit":
        return False
    candidate = event.get("candidate")
    if not isinstance(candidate, dict):
        return False
    if not candidate_source_visuals_match(candidate):
        return False
    if str(candidate.get("selectionAction") or "") != "commit_side_candidate":
        return False
    if str(candidate.get("sourceType") or "") not in {"model", "rag", "memory"}:
        return False
    selection_key = str(candidate.get("selectionKey") or candidate.get("label") or "")
    return bool(selection_key)


def candidate_source_visuals_match(candidate: dict[str, Any]) -> bool:
    source_type = str(candidate.get("sourceType") or "")
    expected_badge = SOURCE_BADGES.get(source_type)
    expected_color = SOURCE_COLOR_TOKENS.get(source_type)
    if expected_badge is None or expected_color is None:
        return source_type in {"", "side"}
    return (
        str(candidate.get("badge") or "") == expected_badge
        and str(candidate.get("colorToken") or "") == expected_color
    )


def is_modern_prediction_session_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "sidecar_response_applied":
        return False
    session = event.get("predictionSession")
    if not isinstance(session, dict):
        return False
    phase = str(session.get("phase") or "")
    selection_scope = str(session.get("selectionScope") or "")
    expires_after_ms = int(session.get("expiresAfterMs") or 0)
    return phase not in {"", "legacy"} and bool(selection_scope) and expires_after_ms > 0


def is_stale_response_drop_event(event: dict[str, Any]) -> bool:
    return str(event.get("event") or "") in {"sidecar_response_dropped", "sidecar_response_dropped_stale"}


def is_prediction_trace_event(event: dict[str, Any]) -> bool:
    name = str(event.get("event") or "")
    return name.startswith("prediction_") or name.startswith("candidate_snapshot_")


def latest_delete_resync(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for invalidation_index, invalidation_event in enumerate(events):
        if invalidation_event.get("event") != "display_invalidated_by_input_change":
            continue
        if str(invalidation_event.get("reason") or "") not in {"delete_key", "backspace", "delete"}:
            continue
        invalidation_generation = invalidation_event.get("inputGeneration")
        invalidation_timestamp = event_timestamp_ms(invalidation_event)
        for resync_event in events[invalidation_index + 1 :]:
            if resync_event.get("event") != "committed_context_resynced_after_delete":
                continue
            if event_timestamp_ms(resync_event) < invalidation_timestamp:
                continue
            resync_generation = resync_event.get("inputGeneration")
            if invalidation_generation is not None or resync_generation is not None:
                if str(invalidation_generation) != str(resync_generation):
                    continue
            latest = {
                "invalidation": invalidation_event,
                "resync": resync_event,
            }
            break
    return latest


def latest_post_delete_context_use(
    events: list[dict[str, Any]],
    delete_resync: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not delete_resync:
        return None
    resync_event = delete_resync.get("resync")
    if not isinstance(resync_event, dict):
        return None
    target_hash = str(resync_event.get("committedContextHash") or "")
    if not target_hash:
        return None
    min_timestamp_ms = event_timestamp_ms(resync_event)
    latest: dict[str, Any] | None = None
    for event in events:
        if event_timestamp_ms(event) < min_timestamp_ms:
            continue
        if event.get("event") not in {"sidecar_request_scheduled", "sidecar_response_applied"}:
            continue
        observed_hash = str(event.get("committedContextHash") or "")
        if observed_hash == target_hash:
            latest = {"resync": resync_event, "use": event}
    return latest


def post_delete_context_violations(
    events: list[dict[str, Any]],
    delete_resync: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not delete_resync:
        return []
    resync_event = delete_resync.get("resync")
    if not isinstance(resync_event, dict):
        return []
    target_hash = str(resync_event.get("committedContextHash") or "")
    if not target_hash:
        return []
    min_timestamp_ms = event_timestamp_ms(resync_event)
    violations: list[dict[str, Any]] = []
    for event in events:
        if event_timestamp_ms(event) < min_timestamp_ms:
            continue
        event_name = str(event.get("event") or "")
        if event_name not in {"sidecar_request_scheduled", "sidecar_response_applied"}:
            continue
        observed_hash = str(event.get("committedContextHash") or "")
        if not observed_hash:
            continue
        if observed_hash == target_hash:
            break
        violations.append(
            {
                "event": event_name,
                "timestampMs": event.get("timestampMs"),
                "reason": "post_delete_context_hash_mismatch",
                "expectedCommittedContextHash": target_hash,
                "committedContextHash": observed_hash,
                "frontendRevision": event.get("frontendRevision"),
                "selectionEpoch": event.get("selectionEpoch"),
            }
        )
    return violations


def frontend_transaction_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") == "sidecar_response_applied":
            session = event.get("predictionSession")
            if isinstance(session, dict) and not transaction_fields_match(event, session):
                violations.append(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": event.get("timestampMs"),
                        "reason": "prediction_session_transaction_mismatch",
                    }
                )
        if event.get("event") == "panel_display_candidates":
            candidates = event.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, dict) and not transaction_fields_match(event, candidate):
                        violations.append(
                            {
                                "event": "panel_display_candidates",
                                "timestampMs": event.get("timestampMs"),
                                "reason": "candidate_transaction_mismatch",
                                "candidate": candidate.get("label"),
                            }
                        )
                        break
    return violations


def collect_trace_privacy_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("traceIncludesText") is True:
            continue
        if event.get("traceIncludesText") is not False:
            continue
        for violation in trace_privacy_violations_for_value(event, path=""):
            violations.append(
                {
                    "event": event.get("event"),
                    "timestampMs": event.get("timestampMs"),
                    **violation,
                }
            )
    return violations


def trace_privacy_violations_for_value(value: Any, *, path: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        violations: list[dict[str, Any]] = []
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in USER_TEXT_TRACE_KEYS:
                if is_unsanitized_trace_text_value(child):
                    violations.append(
                        {
                            "field": child_path,
                            "reason": "raw_text_in_default_trace",
                            "valueType": type(child).__name__,
                        }
                    )
                continue
            violations.extend(trace_privacy_violations_for_value(child, path=child_path))
        return violations
    if isinstance(value, list):
        violations = []
        for index, item in enumerate(value):
            violations.extend(trace_privacy_violations_for_value(item, path=f"{path}[{index}]"))
        return violations
    return []


def is_unsanitized_trace_text_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(compact_trace_text(value))
    if isinstance(value, dict):
        return not (
            isinstance(value.get("hash"), str)
            and str(value.get("hash") or "").startswith("sha256:")
            and isinstance(value.get("chars"), int)
        )
    if isinstance(value, list):
        return any(is_unsanitized_trace_text_value(item) for item in value)
    return False


POST_COMMIT_BARRIER_EVENTS = {
    "commit_observe_timeout",
    "post_commit_chain_cancelled",
    "display_invalidated_by_input_change",
    "frontend_transaction_invalidated",
}


def collect_post_commit_barrier_violations(
    events: list[dict[str, Any]],
    *,
    min_timestamp_ms: int = 0,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for commit_index, commit_event in enumerate(events):
        if event_timestamp_ms(commit_event) < min_timestamp_ms:
            continue
        if not is_valid_side_commit_event(commit_event):
            continue
        cancelled_by: dict[str, Any] | None = None
        scheduled_after_cancel: dict[str, Any] | None = None
        for event in events[commit_index + 1 :]:
            if event.get("event") == "side_candidate_commit":
                break
            if event_timestamp_ms(event) < event_timestamp_ms(commit_event):
                continue
            event_name = str(event.get("event") or "")
            if event_name in POST_COMMIT_BARRIER_EVENTS and cancelled_by is None:
                cancelled_by = event
                scheduled_after_cancel = None
                continue
            if cancelled_by and event_name in {"side_candidate_continuation_scheduled", "post_commit_prediction_scheduled"}:
                scheduled_after_cancel = event
                continue
            if not cancelled_by or event_name != "sidecar_request_scheduled":
                continue
            if not is_post_commit_followup_request(event, commit_event):
                continue
            violations.append(
                {
                    "type": "post_commit_after_cancel",
                    "timestampMs": event.get("timestampMs"),
                    "commitTimestampMs": commit_event.get("timestampMs"),
                    "cancelTimestampMs": cancelled_by.get("timestampMs"),
                    "cancelEvent": cancelled_by.get("event"),
                    "cancelReason": cancelled_by.get("reason"),
                    "scheduledAfterCancel": summarize_event(scheduled_after_cancel),
                    "commitTextPreview": event.get("commitTextPreview"),
                    "committedContextHash": event.get("committedContextHash"),
                    "frontendRevision": event.get("frontendRevision"),
                    "selectionEpoch": event.get("selectionEpoch"),
                }
            )
            break
    return violations


def transaction_fields_match(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    for key in ("frontendRevision", "selectionEpoch", "panelSessionId", "compositionHash", "committedContextHash"):
        parent_value = parent.get(key)
        child_value = child.get(key)
        if parent_value is None or child_value is None:
            continue
        if str(parent_value) != str(child_value):
            return False
    return True


def latest_number_key_side_commit(
    events: list[dict[str, Any]],
    *,
    min_timestamp_ms: int = 0,
) -> dict[str, Any] | None:
    return latest_side_selection_commit(events, min_timestamp_ms=min_timestamp_ms, route_events={"number_key_route"})


def latest_side_selection_commit(
    events: list[dict[str, Any]],
    *,
    min_timestamp_ms: int = 0,
    route_events: set[str] | None = None,
) -> dict[str, Any] | None:
    allowed_events = route_events or SIDE_SELECTION_ROUTE_EVENTS
    latest: dict[str, Any] | None = None
    for route_index, route_event in enumerate(events):
        if str(route_event.get("event") or "") not in allowed_events:
            continue
        if event_timestamp_ms(route_event) < min_timestamp_ms:
            continue
        route_candidate = route_event.get("candidate")
        if not isinstance(route_candidate, dict):
            continue
        key = str(route_event.get("key") or "")
        if not key:
            continue
        for commit_event in events[route_index + 1 :]:
            if event_timestamp_ms(commit_event) < min_timestamp_ms:
                continue
            if not is_valid_side_commit_event(commit_event):
                continue
            if candidates_match_selection_route(route_event, commit_event):
                latest = {
                    "route": route_event,
                    "commit": commit_event,
                    "key": key,
                    "routeEvent": route_event.get("event"),
                }
            break
    return latest


def latest_post_commit_followup(
    events: list[dict[str, Any]],
    *,
    min_timestamp_ms: int = 0,
) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for commit_index, commit_event in enumerate(events):
        if event_timestamp_ms(commit_event) < min_timestamp_ms:
            continue
        if not is_valid_side_commit_event(commit_event):
            continue
        schedule_event: dict[str, Any] | None = None
        for event in events[commit_index + 1 :]:
            if event_timestamp_ms(event) < event_timestamp_ms(commit_event):
                continue
            if str(event.get("event") or "") in POST_COMMIT_BARRIER_EVENTS:
                break
            if event.get("event") in {"side_candidate_continuation_scheduled", "post_commit_prediction_scheduled"}:
                schedule_event = event
                continue
            if event.get("event") != "sidecar_request_scheduled":
                continue
            if not is_post_commit_followup_request(event, commit_event):
                continue
            latest = {
                "commit": commit_event,
                "scheduled": schedule_event,
                "request": event,
            }
            break
    return latest


def is_post_commit_followup_request(request_event: dict[str, Any], commit_event: dict[str, Any]) -> bool:
    raw_input = str(request_event.get("rawInput") or "")
    preedit = str(request_event.get("preedit") or "")
    if raw_input or preedit:
        return False
    if int(request_event.get("committedContextChars") or 0) <= 0:
        return False
    commit_text = compact_trace_text(committed_candidate_text(commit_event))
    request_preview = compact_trace_text(str(request_event.get("commitTextPreview") or ""))
    return bool(commit_text and request_preview and request_preview == commit_text)


def committed_candidate_text(commit_event: dict[str, Any]) -> str:
    candidate = commit_event.get("candidate")
    if not isinstance(candidate, dict):
        return ""
    return str(candidate.get("insertText") or candidate.get("text") or "")


def compact_trace_text(value: str) -> str:
    return " ".join(str(value or "").split())


def is_side_selection_route_event(event: dict[str, Any]) -> bool:
    if str(event.get("event") or "") not in SIDE_SELECTION_ROUTE_EVENTS:
        return False
    return isinstance(event.get("candidate"), dict)


def candidates_match_number_route(route_event: dict[str, Any], commit_event: dict[str, Any]) -> bool:
    return candidates_match_selection_route(route_event, commit_event)


def candidates_match_selection_route(route_event: dict[str, Any], commit_event: dict[str, Any]) -> bool:
    route_candidate = route_event.get("candidate")
    commit_candidate = commit_event.get("candidate")
    if not isinstance(route_candidate, dict) or not isinstance(commit_candidate, dict):
        return False
    route_name = str(route_event.get("event") or "")
    route_key = str(route_event.get("key") or "")
    route_candidate_key = str(route_candidate.get("selectionKey") or route_candidate.get("label") or "")
    commit_candidate_key = str(commit_candidate.get("selectionKey") or commit_candidate.get("label") or "")
    route_session = str(route_candidate.get("sessionFingerprint") or "")
    commit_session = str(commit_candidate.get("sessionFingerprint") or "")
    if (route_session or commit_session) and route_session != commit_session:
        return False
    for key in (
        "frontendRevision",
        "selectionEpoch",
        "panelSessionId",
        "compositionHash",
        "committedContextHash",
        "snapshotId",
        "candidateStableId",
        "candidateOrdinal",
        "hardContextAnchor",
        "queryAnchor",
        "displayAnchor",
    ):
        route_value = route_candidate.get(key)
        commit_value = commit_candidate.get(key)
        if route_value is not None or commit_value is not None:
            if str(route_value) != str(commit_value):
                return False
    if route_name == "tab_key_route":
        route_ordinal = str(route_event.get("ordinal") or route_candidate.get("candidateOrdinal") or "1")
        commit_ordinal = str(commit_candidate.get("candidateOrdinal") or route_ordinal)
        route_key_matches = route_ordinal == "1" and commit_ordinal == route_ordinal
    else:
        route_key_matches = bool(route_key) and route_key == route_candidate_key and route_key == commit_candidate_key
    return (
        route_key_matches
        and str(route_candidate.get("sourceType") or "") == str(commit_candidate.get("sourceType") or "")
        and str(route_candidate.get("selectionAction") or "") == "commit_side_candidate"
        and str(commit_candidate.get("selectionAction") or "") == "commit_side_candidate"
    )


def summarize_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    result = {
        "event": event.get("event"),
        "timestampMs": event.get("timestampMs"),
        "reason": event.get("reason"),
        "rawInput": event.get("rawInput"),
        "preedit": event.get("preedit"),
        "requestRawInput": event.get("requestRawInput"),
        "responseRawInput": event.get("responseRawInput"),
        "currentRawInput": event.get("currentRawInput"),
        "requestPreedit": event.get("requestPreedit"),
        "responsePreedit": event.get("responsePreedit"),
        "queryBasis": event.get("queryBasis"),
        "forcesHorizontalLayout": event.get("forcesHorizontalLayout"),
        "linear": event.get("linear"),
        "vertical": event.get("vertical"),
        "candidateCounts": event.get("candidateCounts"),
        "separators": event.get("separators"),
        "key": event.get("key"),
        "selectionKey": event.get("selectionKey"),
        "keyCode": event.get("keyCode"),
        "sourceType": event.get("sourceType"),
        "sessionFingerprint": event.get("sessionFingerprint"),
        "snapshotId": event.get("snapshotId"),
        "candidateStableId": event.get("candidateStableId"),
        "candidateOrdinal": event.get("candidateOrdinal"),
        "hardContextAnchor": event.get("hardContextAnchor"),
        "queryAnchor": event.get("queryAnchor"),
        "displayAnchor": event.get("displayAnchor"),
        "commitTextPreview": event.get("commitTextPreview"),
        "committedContextChars": event.get("committedContextChars"),
        "displayCount": event.get("displayCount"),
        "visibleCandidateCount": event.get("visibleCandidateCount"),
        "sourceSummary": event.get("sourceSummary"),
        "action": event.get("action"),
        "shouldRefresh": event.get("shouldRefresh"),
        "refreshReason": event.get("refreshReason"),
        "shouldShow": event.get("shouldShow"),
        "showReason": event.get("showReason"),
        "debounced": event.get("debounced"),
        "debounceMs": event.get("debounceMs"),
        "coalescedWithAgeMs": event.get("coalescedWithAgeMs"),
        "ragTimedOut": event.get("ragTimedOut"),
        "modelTimedOut": event.get("modelTimedOut"),
        "holdoverHit": event.get("holdoverHit"),
        "hardClearReason": event.get("hardClearReason"),
        "latencyBudgetMs": event.get("latencyBudgetMs"),
        "responseAgeMs": event.get("responseAgeMs"),
        "inputGeneration": event.get("inputGeneration"),
        "liveInputGeneration": event.get("liveInputGeneration"),
        "previousDisplayCount": event.get("previousDisplayCount"),
        "frontendRevision": event.get("frontendRevision"),
        "selectionEpoch": event.get("selectionEpoch"),
        "panelSessionId": event.get("panelSessionId"),
        "compositionHash": event.get("compositionHash"),
        "committedContextHash": event.get("committedContextHash"),
        "requestFrontendRevision": event.get("requestFrontendRevision"),
        "responseFrontendRevision": event.get("responseFrontendRevision"),
        "liveFrontendRevision": event.get("liveFrontendRevision"),
        "requestSelectionEpoch": event.get("requestSelectionEpoch"),
        "responseSelectionEpoch": event.get("responseSelectionEpoch"),
        "liveSelectionEpoch": event.get("liveSelectionEpoch"),
        "predictionSession": event.get("predictionSession"),
    }
    candidates = event.get("candidates")
    if isinstance(candidates, list):
        result["candidates"] = candidates[:8]
    candidate = event.get("candidate")
    if isinstance(candidate, dict):
        result["candidate"] = candidate
    return {key: value for key, value in result.items() if value is not None}


def summarize_number_key_side_commit(match: dict[str, Any] | None) -> dict[str, Any] | None:
    return summarize_side_selection_commit(match)


def summarize_side_selection_commit(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    return {
        "key": match.get("key"),
        "routeEvent": match.get("routeEvent"),
        "route": summarize_event(match.get("route")),
        "commit": summarize_event(match.get("commit")),
    }


def summarize_post_commit_followup(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    return {
        "commit": summarize_event(match.get("commit")),
        "scheduled": summarize_event(match.get("scheduled")),
        "request": summarize_event(match.get("request")),
    }


def summarize_delete_resync(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    return {
        "invalidation": summarize_event(match.get("invalidation")),
        "resync": summarize_event(match.get("resync")),
    }


def summarize_post_delete_context_use(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    return {
        "resync": summarize_event(match.get("resync")),
        "use": summarize_event(match.get("use")),
    }


def report_passes(
    report: dict[str, Any],
    *,
    require_mixed_panel: bool,
    require_side_panel: bool,
    require_side_commit: bool,
    require_commit_observed: bool,
    require_post_commit_followup: bool,
    require_delete_resync: bool,
    require_modern_prediction_session: bool,
    require_balanced_quota: bool = False,
) -> bool:
    if require_mixed_panel and not report.get("latestMixedPanel"):
        return False
    if require_mixed_panel and not report.get("latestMixedTextLayout"):
        return False
    if require_side_panel and not report.get("latestSidePanel"):
        return False
    if require_side_commit and not report.get("latestSideSelectionCommit"):
        return False
    if require_commit_observed and not report.get("latestCommitObserved"):
        return False
    if require_post_commit_followup and not report.get("latestPostCommitFollowup"):
        return False
    if require_delete_resync and not report.get("latestDeleteResync"):
        return False
    if require_delete_resync and not report.get("latestPostDeleteContextUse"):
        return False
    if require_delete_resync and report.get("postDeleteContextViolations"):
        return False
    if report.get("postCommitBarrierViolations"):
        return False
    if require_modern_prediction_session and not report.get("latestModernPredictionSession"):
        return False
    if require_balanced_quota and not report.get("latestBalancedCandidatePanel"):
        return False
    if require_balanced_quota and report.get("candidateQuotaViolations"):
        return False
    if report.get("frontendTransactionViolations"):
        return False
    if report.get("tracePrivacyViolations"):
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
