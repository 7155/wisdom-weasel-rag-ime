#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path.home() / "Library" / "Logs" / "RagIme" / "squirrel-frontend.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local Squirrel RAG-IME frontend trace events.")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--clear", action="store_true", help="Delete the current trace log and exit unless --wait is set.")
    parser.add_argument("--wait", type=float, default=0.0, help="Wait this many seconds for required events.")
    parser.add_argument("--require-mixed-panel", action="store_true")
    parser.add_argument("--require-side-commit", action="store_true")
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
        if report_passes(report, require_mixed_panel=args.require_mixed_panel, require_side_commit=args.require_side_commit):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    report["required"] = {
        "mixedPanel": bool(args.require_mixed_panel),
        "sideCommit": bool(args.require_side_commit),
    }
    report["passed"] = report_passes(
        report,
        require_mixed_panel=args.require_mixed_panel,
        require_side_commit=args.require_side_commit,
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
    mixed_text_layout = latest_matching(events, is_mixed_text_layout_event)
    side_commit = latest_matching(events, lambda event: event.get("event") == "side_candidate_commit")
    valid_side_commit = latest_matching(events, is_valid_side_commit_event)
    number_route = latest_matching(events, lambda event: event.get("event") == "number_key_route")
    number_key_side_commit = latest_number_key_side_commit(events)
    return {
        "schemaVersion": "rag-ime.squirrel-frontend-trace-check.v1",
        "logPath": str(log_path),
        "eventCount": len(events),
        "latestMixedPanel": summarize_event(mixed_panel),
        "latestMixedTextLayout": summarize_event(mixed_text_layout),
        "latestNumberKeyRoute": summarize_event(number_route),
        "latestSideCommit": summarize_event(side_commit),
        "latestValidSideCommit": summarize_event(valid_side_commit),
        "latestNumberKeySideCommit": summarize_number_key_side_commit(number_key_side_commit),
        "lastEvents": [summarize_event(event) for event in events[-print_last:]] if print_last else [],
    }


def latest_matching(events: list[dict[str, Any]], predicate: Any) -> dict[str, Any] | None:
    for event in reversed(events):
        if predicate(event):
            return event
    return None


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


def is_valid_side_commit_event(event: dict[str, Any]) -> bool:
    if event.get("event") != "side_candidate_commit":
        return False
    candidate = event.get("candidate")
    if not isinstance(candidate, dict):
        return False
    if str(candidate.get("selectionAction") or "") != "commit_side_candidate":
        return False
    if str(candidate.get("sourceType") or "") not in {"model", "rag"}:
        return False
    selection_key = str(candidate.get("selectionKey") or candidate.get("label") or "")
    return bool(selection_key)


def latest_number_key_side_commit(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for route_index, route_event in enumerate(events):
        if route_event.get("event") != "number_key_route":
            continue
        route_candidate = route_event.get("candidate")
        if not isinstance(route_candidate, dict):
            continue
        key = str(route_event.get("key") or "")
        if not key:
            continue
        for commit_event in events[route_index + 1 :]:
            if not is_valid_side_commit_event(commit_event):
                continue
            if candidates_match_number_route(route_event, commit_event):
                latest = {
                    "route": route_event,
                    "commit": commit_event,
                    "key": key,
                }
            break
    return latest


def candidates_match_number_route(route_event: dict[str, Any], commit_event: dict[str, Any]) -> bool:
    route_candidate = route_event.get("candidate")
    commit_candidate = commit_event.get("candidate")
    if not isinstance(route_candidate, dict) or not isinstance(commit_candidate, dict):
        return False
    route_key = str(route_event.get("key") or "")
    route_candidate_key = str(route_candidate.get("selectionKey") or route_candidate.get("label") or "")
    commit_candidate_key = str(commit_candidate.get("selectionKey") or commit_candidate.get("label") or "")
    route_session = str(route_candidate.get("sessionFingerprint") or "")
    commit_session = str(commit_candidate.get("sessionFingerprint") or "")
    if (route_session or commit_session) and route_session != commit_session:
        return False
    return (
        bool(route_key)
        and route_key == route_candidate_key
        and route_key == commit_candidate_key
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
        "rawInput": event.get("rawInput"),
        "preedit": event.get("preedit"),
        "queryBasis": event.get("queryBasis"),
        "forcesHorizontalLayout": event.get("forcesHorizontalLayout"),
        "linear": event.get("linear"),
        "vertical": event.get("vertical"),
        "candidateCounts": event.get("candidateCounts"),
        "separators": event.get("separators"),
        "key": event.get("key"),
    }
    candidates = event.get("candidates")
    if isinstance(candidates, list):
        result["candidates"] = candidates[:8]
    candidate = event.get("candidate")
    if isinstance(candidate, dict):
        result["candidate"] = candidate
    return {key: value for key, value in result.items() if value is not None}


def summarize_number_key_side_commit(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    return {
        "key": match.get("key"),
        "route": summarize_event(match.get("route")),
        "commit": summarize_event(match.get("commit")),
    }


def report_passes(report: dict[str, Any], *, require_mixed_panel: bool, require_side_commit: bool) -> bool:
    if require_mixed_panel and not report.get("latestMixedPanel"):
        return False
    if require_mixed_panel and not report.get("latestMixedTextLayout"):
        return False
    if require_side_commit and not report.get("latestNumberKeySideCommit"):
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
