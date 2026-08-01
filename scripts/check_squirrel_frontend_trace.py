#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.contracts.key_policy import (
    ROUTE_NUMBER_KEY,
    ROUTE_OPTION_NUMBER,
    ROUTE_TAB_KEY,
    SELECTION_ACTION_COMMIT_SIDE_CANDIDATE,
    SELECTION_ACTION_NONE,
    SELECTION_ACTION_SELECT_RIME_CANDIDATE,
    SIDE_SELECTION_ROUTE_EVENTS,
)
from rag_ime.contracts.source import (
    REALTIME_SIDE_SOURCE_TYPES,
    SOURCE_BADGES,
    SOURCE_COLOR_TOKENS,
    SOURCE_STATUS,
)


DEFAULT_LOG_PATH = Path.home() / "Library" / "Logs" / "RagIme" / "squirrel-frontend.jsonl"
ASSISTANT_OVERLAY_VISIBLE_EVENT = "assistant_overlay_candidate_visible"
ASSISTANT_OVERLAY_COLOR_ALIASES = {
    "model": {"blue", "modelBlue"},
    "rag": {"teal", "ragTeal"},
    "memory": {"orange", "purple", "memoryPurple"},
    "action": {"blue", "modelBlue"},
}
ASSISTANT_OVERLAY_BADGE_ALIASES = {source_type: {badge} for source_type, badge in SOURCE_BADGES.items()}
ASSISTANT_OVERLAY_BADGE_ALIASES["action"] = {
    "生成",
    "快速生成",
    "看图生成",
    "深度查找",
}
POST_COMMIT_ACTION_SELECTION_ACTIONS = frozenset(
    {
        "start_active_rag_from_context",
        "start_visual_rag_from_context",
        "start_agent_deep_search_from_context",
    }
)
USER_TEXT_TRACE_KEYS = {
    "selectedText",
    "rawSelectedText",
    "currentSelectedText",
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
    "hardContextAnchor",
    "queryAnchor",
    "displayAnchor",
    "query",
    "text",
    "insertText",
    "comment",
    "evidencePreview",
}
OPAQUE_TEXT_IDENTITY_TRACE_KEYS = {"hardContextAnchor", "queryAnchor", "displayAnchor"}


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
    parser.add_argument("--require-rime-composition-mode", action="store_true")
    parser.add_argument(
        "--require-native-rime-input",
        action="store_true",
        help="Require a real Rime composition -> native commit -> foreground context capture chain.",
    )
    parser.add_argument("--require-post-commit-pending-status", action="store_true")
    parser.add_argument("--require-prediction-status-visible", action="store_true")
    parser.add_argument("--require-source-badges", action="store_true")
    parser.add_argument("--require-active-rag-action-button", action="store_true")
    parser.add_argument("--require-active-rag-thinking", action="store_true")
    parser.add_argument("--require-active-rag-ready", action="store_true")
    parser.add_argument("--require-active-rag-commit", action="store_true")
    parser.add_argument("--require-active-rag-stale-drop-check", action="store_true")
    parser.add_argument(
        "--max-renumber-rate",
        type=float,
        default=None,
        help="Fail if candidate ordinal drift/reuse exceeds this rate; use 0 for append-only strictness.",
    )
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
            require_rime_composition_mode=args.require_rime_composition_mode,
            require_native_rime_input=args.require_native_rime_input,
            require_post_commit_pending_status=args.require_post_commit_pending_status,
            require_prediction_status_visible=args.require_prediction_status_visible,
            require_source_badges=args.require_source_badges,
            require_active_rag_action_button=args.require_active_rag_action_button,
            require_active_rag_thinking=args.require_active_rag_thinking,
            require_active_rag_ready=args.require_active_rag_ready,
            require_active_rag_commit=args.require_active_rag_commit,
            require_active_rag_stale_drop_check=args.require_active_rag_stale_drop_check,
            require_balanced_quota=args.require_balanced_quota,
            max_renumber_rate=args.max_renumber_rate,
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
        "rimeCompositionMode": bool(args.require_rime_composition_mode),
        "nativeRimeInput": bool(args.require_native_rime_input),
        "postCommitPendingStatus": bool(args.require_post_commit_pending_status),
        "predictionStatusVisible": bool(args.require_prediction_status_visible),
        "sourceBadges": bool(args.require_source_badges),
        "activeRagActionButton": bool(args.require_active_rag_action_button),
        "activeRagThinking": bool(args.require_active_rag_thinking),
        "activeRagReady": bool(args.require_active_rag_ready),
        "activeRagCommit": bool(args.require_active_rag_commit),
        "activeRagStaleDropCheck": bool(args.require_active_rag_stale_drop_check),
        "balancedQuota": bool(args.require_balanced_quota),
        "maxRenumberRate": args.max_renumber_rate,
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
        require_rime_composition_mode=args.require_rime_composition_mode,
        require_native_rime_input=args.require_native_rime_input,
        require_post_commit_pending_status=args.require_post_commit_pending_status,
        require_prediction_status_visible=args.require_prediction_status_visible,
        require_source_badges=args.require_source_badges,
        require_active_rag_action_button=args.require_active_rag_action_button,
        require_active_rag_thinking=args.require_active_rag_thinking,
        require_active_rag_ready=args.require_active_rag_ready,
        require_active_rag_commit=args.require_active_rag_commit,
        require_active_rag_stale_drop_check=args.require_active_rag_stale_drop_check,
        require_balanced_quota=args.require_balanced_quota,
        max_renumber_rate=args.max_renumber_rate,
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
    number_route = latest_matching(events, lambda event: event.get("event") == ROUTE_NUMBER_KEY)
    side_selection_route = latest_matching(events, is_side_selection_route_event)
    sidecar_response = latest_matching(events, lambda event: event.get("event") == "sidecar_response_applied")
    balanced_candidate_panel = latest_matching(events, is_balanced_candidate_quota_event)
    rime_composition_mode = latest_matching(events, is_rime_composition_mode_event)
    native_rime_input = latest_native_rime_input_chain(events)
    post_commit_pending_status = latest_matching(events, is_post_commit_pending_status_event)
    prediction_status_visible = latest_matching(events, is_prediction_status_visible_event)
    source_badge_panel = latest_matching(events, is_source_badges_visible_event)
    active_rag_action_button = latest_matching(events, is_active_rag_action_button_event)
    active_rag_thinking = latest_matching(events, is_active_rag_thinking_event)
    active_rag_ready = latest_matching(events, is_active_rag_ready_event)
    active_rag_commit = latest_matching(events, is_active_rag_commit_event)
    active_rag_stale_drop = latest_matching(events, is_active_rag_stale_drop_event)
    stale_response_drop = latest_matching(events, is_stale_response_drop_event)
    stale_selection_rejected = latest_matching(events, lambda event: event.get("event") == "stale_candidate_selection_rejected")
    modern_prediction_session = latest_matching(events, is_modern_prediction_session_event)
    prediction_trace_events = [event for event in events if is_prediction_trace_event(event)]
    commit_observed = latest_matching(events, lambda event: event.get("event") == "commit_observed")
    delete_resync = latest_delete_resync(events)
    post_delete_context_use = latest_post_delete_context_use(events, delete_resync)
    post_commit_barrier_violations = collect_post_commit_barrier_violations(events)
    trace_privacy_violations = collect_trace_privacy_violations(events)
    renumber_metrics = candidate_renumber_metrics(events)
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
    # A successful continuation ends by rendering a newer prediction panel, so
    # using that newest panel as the lower bound would hide the very Tab ->
    # follow-up chain we are trying to prove.
    post_commit_followup = latest_post_commit_followup(events)
    return {
        "schemaVersion": "rag-ime.squirrel-frontend-trace-check.v1",
        "logPath": str(log_path),
        "eventCount": len(events),
        "latestSidecarResponse": summarize_event(sidecar_response),
        "latestBalancedCandidatePanel": summarize_event(balanced_candidate_panel),
        "latestRimeCompositionMode": summarize_event(rime_composition_mode),
        "latestNativeRimeInput": summarize_native_rime_input(native_rime_input),
        "latestPostCommitPendingStatus": summarize_event(post_commit_pending_status),
        "latestPredictionStatusVisible": summarize_event(prediction_status_visible),
        "latestSourceBadgePanel": summarize_event(source_badge_panel),
        "latestActiveRagActionButton": summarize_event(active_rag_action_button),
        "latestActiveRagThinking": summarize_event(active_rag_thinking),
        "latestActiveRagReady": summarize_event(active_rag_ready),
        "latestActiveRagCommit": summarize_event(active_rag_commit),
        "latestActiveRagStaleDrop": summarize_event(active_rag_stale_drop),
        "activeRagTraceViolations": active_rag_trace_violations(events),
        "candidateQuotaViolations": candidate_quota_violations(events),
        "candidateRenumber": renumber_metrics,
        "candidateRenumberViolations": renumber_metrics["violations"],
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
    if event.get("event") == ASSISTANT_OVERLAY_VISIBLE_EVENT:
        candidates = event.get("candidates")
        return (
            str(event.get("phase") or "") == "post_commit"
            and str(event.get("uiMode") or "") == "post_commit_prediction"
            and isinstance(candidates, list)
            and assistant_overlay_has_selectable_side(candidates)
        )
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
    return False


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
    selectable_index = 0
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            return False
        if is_status_candidate(candidate):
            if not status_candidate_is_valid(candidate):
                return False
            continue
        label = str(candidate.get("label") or "")
        selection_key = str(candidate.get("selectionKey") or label)
        expected_label = "0" if selectable_index == 9 else str(selectable_index + 1)
        selectable_index += 1
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
            if selection_action != SELECTION_ACTION_COMMIT_SIDE_CANDIDATE:
                return False
        elif source_type in {"rag", "memory"}:
            side_indices.append(index)
            if selection_action != SELECTION_ACTION_COMMIT_SIDE_CANDIDATE:
                return False
        elif source_type == "rime":
            rime_indices.append(index)
            if selection_action and selection_action != SELECTION_ACTION_SELECT_RIME_CANDIDATE:
                return False
        else:
            return False
    if not side_indices:
        return False
    if rime_indices and min(rime_indices) < max(side_indices):
        return False
    return True


def assistant_overlay_has_selectable_side(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return False
    has_real_candidate = False
    for candidate in candidates:
        if not isinstance(candidate, dict) or is_status_candidate(candidate):
            return False
        if candidate_is_real_side_candidate(candidate):
            has_real_candidate = True
            continue
        if candidate_is_assistant_action_button(candidate) and candidate_source_visuals_match(candidate):
            continue
        return False
    return has_real_candidate


def visible_candidates_are_side_first(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return True
    model_indices: list[int] = []
    rag_indices: list[int] = []
    rime_indices: list[int] = []
    selectable_index = 0
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            return False
        if is_status_candidate(candidate):
            if not status_candidate_is_valid(candidate):
                return False
            continue
        label = str(candidate.get("label") or "")
        selection_key = str(candidate.get("selectionKey") or label)
        expected_label = "0" if selectable_index == 9 else str(selectable_index + 1)
        selectable_index += 1
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
            if (
                display_layout != "inline"
                or display_lane != "model"
                or selection_action != SELECTION_ACTION_COMMIT_SIDE_CANDIDATE
            ):
                return False
        elif source_type in {"rag", "memory"}:
            rag_indices.append(index)
            if (
                display_layout != "block"
                or display_lane != "memory"
                or selection_action != SELECTION_ACTION_COMMIT_SIDE_CANDIDATE
            ):
                return False
        elif source_type == "rime":
            rime_indices.append(index)
            if selection_action and selection_action != SELECTION_ACTION_SELECT_RIME_CANDIDATE:
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
    candidates = event.get("candidates")
    if event.get("event") in {"assistant_overlay_candidate_visible", "assistant_overlay_updated"}:
        if (
            str(event.get("phase") or "") != "post_commit"
            or str(event.get("uiMode") or "") != "post_commit_prediction"
        ):
            return False
        counts = candidate_source_counts(candidates)
        if counts["model"] > 2 and (counts["rag"] + counts["memory"]) > 0:
            return False
        if counts["model"] > 3 and (counts["rag"] + counts["memory"]) == 0:
            return False
        return assistant_overlay_has_selectable_side(candidates)
    if event.get("event") != "panel_display_candidates":
        return False
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


def is_rime_composition_mode_event(event: dict[str, Any]) -> bool:
    if is_native_rime_composition_event(event):
        return True
    if event.get("event") == "sidecar_response_applied":
        ui_mode = str(event.get("uiMode") or "")
        session = event.get("predictionSession")
        input_mode = str(session.get("inputMode") or "") if isinstance(session, dict) else ""
        if ui_mode == "composition_rime" or input_mode in {"anchor_composing", "prefix_constrained_composing"}:
            return True
    if event.get("event") != "panel_display_candidates":
        return False
    if not (str(event.get("rawInput") or "") or str(event.get("preedit") or "")):
        return False
    candidates = event.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return False
    return visible_candidates_are_rime_only(candidates)


def latest_native_rime_input_chain(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a completed native Rime input chain without conflating it with side-candidate commits."""
    for capture_index in range(len(events) - 1, -1, -1):
        capture = events[capture_index]
        if not is_native_foreground_capture_event(capture):
            continue
        capture_timestamp = event_timestamp_ms(capture)
        capture_session = str(capture.get("sessionId") or "")
        capture_app = str(capture.get("sourceAppBundleId") or "")
        transaction: dict[str, Any] | None = None
        transaction_index = -1
        for index in range(capture_index - 1, -1, -1):
            candidate = events[index]
            if event_timestamp_ms(candidate) > capture_timestamp:
                continue
            if capture_session and str(candidate.get("sessionId") or "") != capture_session:
                continue
            if is_native_rime_commit_transaction(candidate, app_bundle_id=capture_app):
                transaction = candidate
                transaction_index = index
                break
        if transaction is None:
            continue
        transaction_timestamp = event_timestamp_ms(transaction)
        for index in range(transaction_index - 1, -1, -1):
            composition = events[index]
            if event_timestamp_ms(composition) > transaction_timestamp:
                continue
            if capture_session and str(composition.get("sessionId") or "") != capture_session:
                continue
            if is_native_rime_composition_event(composition):
                return {
                    "composition": composition,
                    "transaction": transaction,
                    "capture": capture,
                }
    return None


def is_native_rime_composition_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "rime_composition_started":
        return False
    try:
        candidate_count = int(event.get("candidateCount") or 0)
    except (TypeError, ValueError):
        return False
    return candidate_count > 0 and bool(event.get("rawInput") or event.get("preedit"))


def is_native_rime_commit_transaction(event: dict[str, Any], *, app_bundle_id: str) -> bool:
    if event.get("event") != "frontend_transaction_created":
        return False
    try:
        committed_chars = int(event.get("committedContextChars") or 0)
        composition_chars = int(event.get("compositionChars") or 0)
    except (TypeError, ValueError):
        return False
    event_app = str(event.get("frontAppBundleId") or "")
    return (
        committed_chars > 0
        and composition_chars == 0
        and bool(event.get("foregroundTextAvailable"))
        and bool(event_app)
        and (not app_bundle_id or event_app == app_bundle_id)
    )


def is_native_foreground_capture_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "foreground_context_capture_succeeded":
        return False
    try:
        surrounding_before_chars = int(event.get("surroundingBeforeChars") or 0)
    except (TypeError, ValueError):
        return False
    return (
        str(event.get("source") or "") == "text_input_client"
        and bool(event.get("sourceAppBundleId"))
        and surrounding_before_chars > 0
    )


def summarize_native_rime_input(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    return {
        "composition": summarize_event(match.get("composition")),
        "transaction": summarize_event(match.get("transaction")),
        "capture": summarize_event(match.get("capture")),
    }


def visible_candidates_are_rime_only(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return False
    seen_rime = False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return False
        if is_status_candidate(candidate):
            return False
        source_type = str(candidate.get("sourceType") or "")
        if source_type != "rime":
            return False
        if not candidate_source_visuals_match(candidate):
            return False
        selection_action = str(candidate.get("selectionAction") or "")
        if selection_action and selection_action != SELECTION_ACTION_SELECT_RIME_CANDIDATE:
            return False
        seen_rime = True
    return seen_rime


def is_post_commit_pending_status_event(event: dict[str, Any]) -> bool:
    if event.get("event") in {
        "assistant_overlay_post_commit_pending",
        "assistant_overlay_feedback_visible",
    }:
        return (
            str(event.get("phase") or "") == "post_commit"
            and bool(str(event.get("statusText") or "").strip())
        )
    if event.get("event") == "sidecar_response_applied":
        ui_mode = str(event.get("uiMode") or "")
        if ui_mode == "post_commit_pending":
            return True
    if event.get("event") != "panel_display_candidates":
        return False
    ui_mode = str(event.get("uiMode") or "")
    if ui_mode and ui_mode != "post_commit_pending":
        return False
    candidates = event.get("candidates")
    if isinstance(candidates, list) and any(
        isinstance(candidate, dict) and candidate_is_post_commit_active_rag_action(candidate) for candidate in candidates
    ):
        return True
    if not panel_is_post_commit(event):
        return False
    return panel_has_valid_status_row(event)


def is_prediction_status_visible_event(event: dict[str, Any]) -> bool:
    if event.get("event") == "assistant_overlay_post_commit_pending":
        return bool(str(event.get("statusText") or ""))
    if event.get("event") not in {"panel_display_candidates", "sidecar_response_applied"}:
        return False
    return panel_has_valid_status_row(event)


def is_source_badges_visible_event(event: dict[str, Any]) -> bool:
    if event.get("event") not in {"panel_display_candidates", ASSISTANT_OVERLAY_VISIBLE_EVENT}:
        return False
    candidates = event.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return False
    return all(isinstance(candidate, dict) and candidate_source_visuals_match(candidate) for candidate in candidates) and any(
        candidate_is_real_side_candidate(candidate) for candidate in candidates
    )


def is_active_rag_action_button_event(event: dict[str, Any]) -> bool:
    if event.get("event") not in {
        "panel_display_candidates",
        "sidecar_response_applied",
        "assistant_overlay_candidate_visible",
        "assistant_overlay_updated",
        "assistant_overlay_post_commit_pending",
    }:
        return False
    candidates = event.get("candidates")
    if not isinstance(candidates, list):
        return False
    has_action = any(isinstance(candidate, dict) and candidate_is_active_rag_action_button(candidate) for candidate in candidates)
    if not has_action:
        return False
    return panel_is_post_commit(event) or any(
        isinstance(candidate, dict) and candidate_is_post_commit_active_rag_action(candidate) for candidate in candidates
    )


def candidate_is_assistant_action_button(candidate: dict[str, Any]) -> bool:
    return (
        str(candidate.get("sourceType") or "") == "action"
        and str(candidate.get("selectionAction") or "") in POST_COMMIT_ACTION_SELECTION_ACTIONS
    )


def candidate_is_active_rag_action_button(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    return (
        str(candidate.get("selectionAction") or "") == "start_active_rag_from_context"
        or str(candidate.get("displayLane") or "") == "active_rag"
        or str(metadata.get("buttonRole") or "") == "active_rag_generate"
        or str(candidate.get("text") or "") == "DeepSeek 生成"
    )


def candidate_is_post_commit_active_rag_action(candidate: dict[str, Any]) -> bool:
    return (
        candidate_is_active_rag_action_button(candidate)
        and str(candidate.get("selectionAction") or "") == "start_active_rag_from_context"
        and (
            str(candidate.get("committedContextHash") or "").startswith("sha256:")
            or str(candidate.get("compositionHash") or "") == "sha256:e3b0c44298fc1c14"
        )
    )


def is_active_rag_thinking_event(event: dict[str, Any]) -> bool:
    if event.get("event") == "active_rag_thinking_displayed":
        return active_rag_anchor_fields_present(event)
    if event.get("event") != "panel_display_candidates":
        return False
    if str(event.get("uiMode") or "") != "active_rag_assist":
        return False
    candidates = event.get("candidates")
    return active_rag_anchor_fields_present(event) and panel_has_active_rag_status_row(candidates)


def is_active_rag_ready_event(event: dict[str, Any]) -> bool:
    if event.get("event") == "active_rag_ready_displayed":
        return active_rag_anchor_fields_present(event)
    if event.get("event") != "panel_display_candidates":
        return False
    if str(event.get("uiMode") or "") != "active_rag_assist":
        return False
    candidates = event.get("candidates")
    return active_rag_anchor_fields_present(event) and active_rag_candidates_are_ready(candidates)


def is_active_rag_commit_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "active_rag_candidate_committed":
        return False
    candidate = event.get("candidate")
    return active_rag_anchor_fields_present(event) and isinstance(candidate, dict) and candidate_source_visuals_match(candidate)


def is_active_rag_stale_drop_event(event: dict[str, Any]) -> bool:
    name = str(event.get("event") or "")
    if name in {"active_rag_response_dropped_stale", "active_rag_stale_response_dropped"}:
        return active_rag_anchor_fields_present(event)
    if name == "active_rag_accept_rejected":
        reason = str(event.get("reason") or "")
        return reason in {
            "selected_text_hash_mismatch",
            "frontend_revision_mismatch",
            "selection_epoch_mismatch",
            "panel_session_id_mismatch",
            "front_app_bundle_id_mismatch",
        }
    return False


def panel_has_active_rag_status_row(candidates: Any) -> bool:
    if not isinstance(candidates, list):
        return False
    return any(isinstance(candidate, dict) and status_candidate_is_valid(candidate) for candidate in candidates)


def active_rag_candidates_are_ready(candidates: Any) -> bool:
    if not isinstance(candidates, list) or not candidates:
        return False
    selectable = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and not is_status_candidate(candidate)
        and str(candidate.get("sourceType") or "") in {"model", "rag", "memory", "phrase"}
    ]
    if not selectable:
        return False
    return all(candidate_source_visuals_match(candidate) for candidate in selectable)


def active_rag_anchor_fields_present(event: dict[str, Any]) -> bool:
    return (
        bool(str(event.get("selectedTextHash") or ""))
        and event.get("frontendRevision") is not None
        and event.get("selectionEpoch") is not None
        and bool(str(event.get("panelSessionId") or ""))
        and bool(str(event.get("frontAppBundleId") or ""))
    )


def active_rag_trace_violations(events: list[dict[str, Any]]) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for event in events:
        if not is_active_rag_trace_event(event):
            continue
        if str(event.get("event") or "") in {
            "active_rag_shortcut_triggered",
            "active_rag_shortcut_action_button_route",
            "active_rag_selected_text_capture_failed",
        }:
            continue
        if not active_rag_anchor_fields_present(event):
            violations.append(
                {
                    "event": event.get("event"),
                    "timestampMs": event.get("timestampMs"),
                    "reason": "missing_active_rag_anchor_fields",
                }
            )
    return violations


def is_active_rag_trace_event(event: dict[str, Any]) -> bool:
    name = str(event.get("event") or "")
    if name.startswith("active_rag_"):
        return True
    return str(event.get("uiMode") or "") == "active_rag_assist"


def panel_is_post_commit(event: dict[str, Any]) -> bool:
    if str(event.get("uiMode") or "") in {"post_commit_pending", "post_commit_prediction"}:
        return True
    session = event.get("predictionSession")
    return isinstance(session, dict) and str(session.get("phase") or "") == "post_commit"


def panel_has_valid_status_row(event: dict[str, Any]) -> bool:
    candidates = event.get("candidates")
    if not isinstance(candidates, list):
        return False
    return any(isinstance(candidate, dict) and status_candidate_is_valid(candidate) for candidate in candidates)


def is_status_candidate(candidate: dict[str, Any]) -> bool:
    return (
        str(candidate.get("sourceType") or "") == SOURCE_STATUS
        or candidate.get("isStatus") is True
        or str(candidate.get("displayLayout") or "") == "status_row"
        or str(candidate.get("displayLane") or "") == "post_commit_status"
    )


def status_candidate_is_valid(candidate: dict[str, Any]) -> bool:
    selection_key = candidate.get("selectionKey")
    return (
        is_status_candidate(candidate)
        and str(candidate.get("selectionAction") or "") == SELECTION_ACTION_NONE
        and (selection_key is None or str(selection_key) == "")
        and candidate_source_visuals_match(candidate)
    )


def candidate_source_counts(candidates: Any) -> dict[str, int]:
    counts = {"model": 0, "rag": 0, "memory": 0, "rime": 0, "raw_english": 0, "status": 0, "other": 0}
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
    if is_status_candidate(candidate):
        return False
    if not candidate_source_visuals_match(candidate):
        return False
    if str(candidate.get("selectionAction") or "") != SELECTION_ACTION_COMMIT_SIDE_CANDIDATE:
        return False
    if str(candidate.get("sourceType") or "") not in REALTIME_SIDE_SOURCE_TYPES:
        return False
    selection_key = str(candidate.get("selectionKey") or candidate.get("label") or "")
    return bool(selection_key)


def candidate_is_real_side_candidate(candidate: Any) -> bool:
    return (
        isinstance(candidate, dict)
        and not is_status_candidate(candidate)
        and str(candidate.get("sourceType") or "") in REALTIME_SIDE_SOURCE_TYPES
        and str(candidate.get("selectionAction") or "") == SELECTION_ACTION_COMMIT_SIDE_CANDIDATE
        and candidate_source_visuals_match(candidate)
    )


def candidate_source_visuals_match(candidate: dict[str, Any]) -> bool:
    source_type = str(candidate.get("sourceType") or "")
    expected_badge = SOURCE_BADGES.get(source_type)
    expected_color = SOURCE_COLOR_TOKENS.get(source_type)
    if expected_badge is None or expected_color is None:
        return source_type in {"", "side"}
    actual_badge = str(candidate.get("badge") or candidate.get("sourceBadge") or "")
    actual_color = str(candidate.get("colorToken") or "")
    return (
        actual_badge in ASSISTANT_OVERLAY_BADGE_ALIASES.get(source_type, {expected_badge})
        and actual_color in ASSISTANT_OVERLAY_COLOR_ALIASES.get(source_type, {expected_color})
    )


def candidate_renumber_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_snapshot_ordinal: dict[tuple[str, int], str] = {}
    by_snapshot_stable_id: dict[tuple[str, str], int] = {}
    comparisons = 0
    violations: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "panel_display_candidates":
            continue
        candidates = event.get("candidates")
        if not isinstance(candidates, list):
            continue
        event_snapshot = snapshot_id_for_event(event)
        for candidate in candidates:
            if not isinstance(candidate, dict) or is_status_candidate(candidate):
                continue
            if str(candidate.get("selectionAction") or "") != SELECTION_ACTION_COMMIT_SIDE_CANDIDATE:
                continue
            snapshot_id = str(candidate.get("snapshotId") or event_snapshot)
            stable_id = str(candidate.get("candidateStableId") or "")
            ordinal = optional_int(candidate.get("candidateOrdinal"))
            if not snapshot_id or not stable_id or ordinal is None or ordinal <= 0:
                continue
            ordinal_key = (snapshot_id, ordinal)
            stable_key = (snapshot_id, stable_id)
            previous_stable = by_snapshot_ordinal.get(ordinal_key)
            if previous_stable is None:
                by_snapshot_ordinal[ordinal_key] = stable_id
            else:
                comparisons += 1
                if previous_stable != stable_id:
                    violations.append(
                        {
                            "event": "panel_display_candidates",
                            "timestampMs": event.get("timestampMs"),
                            "reason": "candidate_ordinal_reused_for_different_stable_id",
                            "snapshotId": snapshot_id,
                            "candidateOrdinal": ordinal,
                            "previousCandidateStableId": previous_stable,
                            "candidateStableId": stable_id,
                        }
                    )
            previous_ordinal = by_snapshot_stable_id.get(stable_key)
            if previous_ordinal is None:
                by_snapshot_stable_id[stable_key] = ordinal
            else:
                comparisons += 1
                if previous_ordinal != ordinal:
                    violations.append(
                        {
                            "event": "panel_display_candidates",
                            "timestampMs": event.get("timestampMs"),
                            "reason": "candidate_stable_id_changed_ordinal",
                            "snapshotId": snapshot_id,
                            "candidateStableId": stable_id,
                            "previousCandidateOrdinal": previous_ordinal,
                            "candidateOrdinal": ordinal,
                        }
                    )
    rate = float(len(violations)) / float(comparisons) if comparisons else 0.0
    return {"comparisonCount": comparisons, "violationCount": len(violations), "renumberRate": rate, "violations": violations}


def snapshot_id_for_event(event: dict[str, Any]) -> str:
    session = event.get("predictionSession")
    if isinstance(session, dict):
        return str(session.get("snapshotId") or session.get("stableSnapshotId") or "")
    return str(event.get("snapshotId") or "")


def optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_modern_prediction_session_event(event: dict[str, Any]) -> bool:
    if event.get("event") == ASSISTANT_OVERLAY_VISIBLE_EVENT:
        key_policy = event.get("keyPolicy")
        candidates = event.get("candidates")
        return (
            str(event.get("phase") or "") == "post_commit"
            and str(event.get("uiMode") or "") == "post_commit_prediction"
            and bool(str(event.get("snapshotId") or ""))
            and bool(str(event.get("panelSessionId") or ""))
            and isinstance(key_policy, dict)
            and str(key_policy.get("numberKeys") or "") == "pass_through"
            and str(key_policy.get("tab") or "") == "accept_top_prediction"
            and str(key_policy.get("optionNumber") or "") == "select_prediction_by_ordinal"
            and isinstance(candidates, list)
            and assistant_overlay_has_selectable_side(candidates)
        )
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
                if (
                    key in OPAQUE_TEXT_IDENTITY_TRACE_KEYS
                    and isinstance(child, str)
                    and child.startswith("sha256:")
                ):
                    continue
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
    return latest_side_selection_commit(events, min_timestamp_ms=min_timestamp_ms, route_events={ROUTE_NUMBER_KEY})


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
    if not request_preview and request_event.get("traceIncludesText") is False:
        # Production traces intentionally omit raw committed text. Ordering,
        # the explicit continuation schedule, and a non-empty committed context
        # still prove that this request belongs to the accepted candidate.
        return bool(commit_text)
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
    if route_name == ROUTE_TAB_KEY:
        route_ordinal = str(route_event.get("ordinal") or route_candidate.get("candidateOrdinal") or "1")
        commit_ordinal = str(commit_candidate.get("candidateOrdinal") or route_ordinal)
        route_key_matches = route_ordinal == "1" and commit_ordinal == route_ordinal
    else:
        route_key_matches = bool(route_key) and route_key == route_candidate_key and route_key == commit_candidate_key
    return (
        route_key_matches
        and str(route_candidate.get("sourceType") or "") == str(commit_candidate.get("sourceType") or "")
        and str(route_candidate.get("selectionAction") or "") == SELECTION_ACTION_COMMIT_SIDE_CANDIDATE
        and str(commit_candidate.get("selectionAction") or "") == SELECTION_ACTION_COMMIT_SIDE_CANDIDATE
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
        "uiMode": event.get("uiMode"),
        "phase": event.get("phase"),
        "surfaceState": event.get("surfaceState"),
        "statusText": event.get("statusText"),
        "candidateCount": event.get("candidateCount"),
        "keyPolicy": event.get("keyPolicy"),
        "laneStatus": event.get("laneStatus"),
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
        "compositionChars": event.get("compositionChars"),
        "foregroundTextAvailable": event.get("foregroundTextAvailable"),
        "foregroundTextSource": event.get("foregroundTextSource"),
        "frontAppBundleId": event.get("frontAppBundleId"),
        "sourceAppBundleId": event.get("sourceAppBundleId"),
        "surroundingBeforeChars": event.get("surroundingBeforeChars"),
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
    require_rime_composition_mode: bool = False,
    require_native_rime_input: bool = False,
    require_post_commit_pending_status: bool = False,
    require_prediction_status_visible: bool = False,
    require_source_badges: bool = False,
    require_active_rag_action_button: bool = False,
    require_active_rag_thinking: bool = False,
    require_active_rag_ready: bool = False,
    require_active_rag_commit: bool = False,
    require_active_rag_stale_drop_check: bool = False,
    require_balanced_quota: bool = False,
    max_renumber_rate: float | None = None,
) -> bool:
    if require_mixed_panel and not report.get("latestMixedPanel"):
        return False
    if require_mixed_panel and not report.get("latestMixedTextLayout"):
        return False
    if require_side_panel and not report.get("latestSidePanel"):
        return False
    if require_side_commit and not report.get("latestSideSelectionCommit"):
        completed_chain = (
            require_post_commit_followup
            and report.get("latestHistoricalSideSelectionCommit")
            and report.get("latestPostCommitFollowup")
        )
        if not completed_chain:
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
    if require_rime_composition_mode and not report.get("latestRimeCompositionMode"):
        return False
    if require_native_rime_input and not report.get("latestNativeRimeInput"):
        return False
    if require_post_commit_pending_status and not report.get("latestPostCommitPendingStatus"):
        return False
    if require_prediction_status_visible and not report.get("latestPredictionStatusVisible"):
        return False
    if require_source_badges and not report.get("latestSourceBadgePanel"):
        return False
    if require_active_rag_action_button and not report.get("latestActiveRagActionButton"):
        return False
    if require_active_rag_thinking and not report.get("latestActiveRagThinking"):
        return False
    if require_active_rag_ready and not report.get("latestActiveRagReady"):
        return False
    if require_active_rag_commit and not report.get("latestActiveRagCommit"):
        return False
    if require_active_rag_stale_drop_check and not report.get("latestActiveRagStaleDrop"):
        return False
    if report.get("activeRagTraceViolations"):
        return False
    if require_balanced_quota and not report.get("latestBalancedCandidatePanel"):
        return False
    if require_balanced_quota and report.get("candidateQuotaViolations"):
        return False
    if max_renumber_rate is not None:
        metrics = report.get("candidateRenumber")
        rate = float(metrics.get("renumberRate") or 0.0) if isinstance(metrics, dict) else 0.0
        if rate > max_renumber_rate:
            return False
    if report.get("frontendTransactionViolations"):
        return False
    if report.get("tracePrivacyViolations"):
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
