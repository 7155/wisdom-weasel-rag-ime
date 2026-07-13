#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.context_group import resolve_context_group
from rag_ime.prediction_trigger import PredictionTrigger
from rag_ime.text_utils import compact_whitespace, stable_text_hash


def load_cases(path: str | Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            cases.append(item)
    return cases


def replay_cases(cases: Iterable[dict[str, object]]) -> dict[str, object]:
    reports = [_replay_case(case) for case in cases]
    totals = _sum_metrics([dict(report["metrics"]) for report in reports])
    gates = {
        "rapidCommitPredictorBound": all(
            int(report["metrics"]["predictorCallCount"]) <= int(dict(report.get("expected") or {}).get("maxPredictorCalls", 2))
            for report in reports
        ),
        "remoteDeepSeekAutoZero": totals["remoteDeepSeekAutoCallCount"] == 0,
        "crossGroupLeakZero": totals["crossGroupLeakCount"] == 0,
        "rawHistoryLeakZero": totals["rawHistoryLeakCount"] == 0,
        "contextEchoZero": totals["contextEchoCount"] == 0,
        "longTermProvenanceComplete": totals["missingSourceEventIdsCount"] == 0,
    }
    return {
        "schemaVersion": "rag-ime.prediction-burst-replay.v1",
        "ok": all(gates.values()),
        "metrics": totals,
        "gates": gates,
        "cases": reports,
    }


def _replay_case(case: dict[str, object]) -> dict[str, object]:
    events = [item for item in case.get("events", []) if isinstance(item, dict)]
    clock = 0
    trigger = PredictionTrigger(clock_ms=lambda: clock)
    metrics = _empty_metrics()
    pending_groups: dict[str, int] = {}
    pending_direct: dict[str, tuple[str, float]] = {}

    def flush(group_id: str, at_ms: int, direct_memory: tuple[str, float] | None = None) -> None:
        nonlocal clock
        clock = at_ms
        decision = trigger.poll(group_id, now=clock, direct_memory=direct_memory, provider_kind="local")
        if decision.action == "direct_memory_hit":
            metrics["sidecarRequestCount"] += 1
            metrics["directMemoryHitCount"] += 1
        elif decision.should_call_predictor:
            metrics["sidecarRequestCount"] += 1
            metrics["predictorCallCount"] += 1
            trigger.complete(decision, result_count=1, now=clock)

    previous_timestamp = 0
    for event in events:
        timestamp = max(0, int(event.get("timestamp") or 0))
        for group_id, due_at in tuple(pending_groups.items()):
            if timestamp >= due_at:
                flush(group_id, due_at)
                pending_groups.pop(group_id, None)
        clock = timestamp
        group = resolve_context_group(
            app_bundle_id=str(event.get("app") or "unknown-app"),
            document_url=str(event.get("document") or ""),
            window_title=str(event.get("windowTitle") or ""),
            project=str(event.get("project") or ""),
        )
        group_id = compact_whitespace(str(event.get("contextGroupId") or group.context_group_id))
        text = compact_whitespace(str(event.get("commitText") or ""))
        snapshot = event.get("contextSnapshot") if isinstance(event.get("contextSnapshot"), dict) else {}
        reliable = (
            str(snapshot.get("source") or "") in {"text_input_client", "accessibility"}
            and int(snapshot.get("freshnessMs") or 0) <= 700
            and bool(snapshot.get("commitTextMatched", True))
        )
        if reliable:
            metrics["contextCaptureSuccessCount"] += 1
        metrics["commitCount"] += 1
        decision = trigger.record_commit(
            group_id=group_id,
            text=text,
            context_hash=str(snapshot.get("contextHash") or stable_text_hash(str(snapshot.get("surroundingBefore") or text))),
            reliable=reliable,
            accepted_candidate=str(event.get("action") or "") == "accepted",
            deleted=str(event.get("action") or "") == "deleted",
            now=timestamp,
        )
        if decision.action == "coalesced":
            metrics["coalescedCount"] += 1
        pending_groups[group_id] = timestamp if str(event.get("action") or "") == "accepted" else timestamp + 500
        direct_text = compact_whitespace(str(event.get("directMemoryCandidate") or ""))
        if direct_text:
            pending_direct[group_id] = (direct_text, float(event.get("directMemoryConfidence") or 0.0))
        _inspect_candidate(event, group_id=group_id, metrics=metrics)
        previous_timestamp = max(previous_timestamp, timestamp)

    for group_id, due_at in tuple(pending_groups.items()):
        flush(group_id, max(due_at, previous_timestamp + 500), direct_memory=pending_direct.get(group_id))
    return {
        "caseId": str(case.get("caseId") or ""),
        "metrics": metrics,
        "expected": dict(case.get("expected") or {}),
    }


def _inspect_candidate(event: dict[str, object], *, group_id: str, metrics: dict[str, int]) -> None:
    candidate = event.get("candidateShown") if isinstance(event.get("candidateShown"), dict) else {}
    text = compact_whitespace(str(candidate.get("text") or ""))
    if not text:
        return
    source_group = compact_whitespace(str(candidate.get("contextGroupId") or group_id))
    if bool(candidate.get("shortTerm")) and source_group != group_id:
        metrics["crossGroupLeakCount"] += 1
    raw_history = [compact_whitespace(str(value)) for value in event.get("rawHistory", []) if compact_whitespace(str(value))]
    if any(text == raw or (len(raw) > 18 and text in raw) for raw in raw_history):
        metrics["rawHistoryLeakCount"] += 1
    context = event.get("contextSnapshot") if isinstance(event.get("contextSnapshot"), dict) else {}
    before = compact_whitespace(str(context.get("surroundingBefore") or ""))
    if text and before and text in before[-200:]:
        metrics["contextEchoCount"] += 1
    if bool(candidate.get("longTerm")) and not [value for value in candidate.get("sourceEventIds", []) if isinstance(value, int) and value > 0]:
        metrics["missingSourceEventIdsCount"] += 1


def _empty_metrics() -> dict[str, int]:
    return {
        "commitCount": 0,
        "sidecarRequestCount": 0,
        "predictorCallCount": 0,
        "coalescedCount": 0,
        "directMemoryHitCount": 0,
        "contextCaptureSuccessCount": 0,
        "crossGroupLeakCount": 0,
        "rawHistoryLeakCount": 0,
        "contextEchoCount": 0,
        "remoteDeepSeekAutoCallCount": 0,
        "missingSourceEventIdsCount": 0,
    }


def _sum_metrics(metrics: list[dict[str, int]]) -> dict[str, int]:
    total = _empty_metrics()
    for item in metrics:
        for key in total:
            total[key] += int(item.get(key) or 0)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay grouped post-commit prediction bursts.")
    parser.add_argument("--cases", default="eval/group_memory_completion_cases.jsonl")
    args = parser.parse_args()
    report = replay_cases(load_cases(args.cases))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
