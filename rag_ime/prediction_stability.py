from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .prediction_anchors import PredictionAnchors, prediction_mode_family
from .text_utils import compact_whitespace


MIN_VISIBLE_MS = 1800
POST_COMMIT_VISIBLE_TTL_MS = 4200
COMPOSITION_VISIBLE_TTL_MS = 2200
NO_CANDIDATE_GRACE_MS = 700
REFRESH_DEBOUNCE_MS = 100
HARD_CLEAR_COOLDOWN_MS = 250


@dataclass(frozen=True)
class StableCandidateSnapshot:
    snapshot_id: str
    generation: int
    hard_context_anchor: str
    query_anchor: str
    display_anchor: str
    mode: str
    created_at_ms: int
    updated_at_ms: int
    min_visible_until_ms: int
    expires_at_ms: int
    candidates: tuple[object, ...]
    source_summary: dict[str, int]
    lane_status: dict[str, object]
    reused_last_good: bool = False
    holdover_hit: bool = False
    stale_level: str = "fresh"


@dataclass
class StablePanelState:
    last_snapshot: StableCandidateSnapshot | None = None
    last_hard_clear_reason: str = ""
    last_soft_hold_reason: str = ""
    generation: int = 0


def render_stable_prediction_panel(
    *,
    state: StablePanelState,
    anchors: PredictionAnchors,
    mode: str,
    fresh_candidates: tuple[object, ...],
    trigger_decision: Mapping[str, object] | None = None,
    rag_lane: Mapping[str, object] | None = None,
    model_lane: Mapping[str, object] | None = None,
    now_ms: int,
    hard_clear_reason: str = "",
) -> tuple[StableCandidateSnapshot | None, StablePanelState, dict[str, object]]:
    now = max(0, int(now_ms))
    lane_status = {
        "triggerDecision": dict(trigger_decision or {}),
        "ragLane": _lane_summary(rag_lane or {}),
        "modelLane": _lane_summary(model_lane or {}),
    }
    previous = state.last_snapshot

    if hard_clear_reason:
        next_state = StablePanelState(
            last_snapshot=None,
            last_hard_clear_reason=hard_clear_reason,
            generation=state.generation,
        )
        return None, next_state, _diagnostics(
            action="hard_clear",
            reason=hard_clear_reason,
            anchors=anchors,
            snapshot=None,
            previous=previous,
            now_ms=now,
        )

    if fresh_candidates:
        generation = state.generation + 1
        snapshot = StableCandidateSnapshot(
            snapshot_id=_snapshot_id(
                generation=generation,
                anchors=anchors,
                candidates=fresh_candidates,
                now_ms=now,
            ),
            generation=generation,
            hard_context_anchor=anchors.hard_context_anchor,
            query_anchor=anchors.query_anchor,
            display_anchor=anchors.display_anchor,
            mode=compact_whitespace(mode),
            created_at_ms=now,
            updated_at_ms=now,
            min_visible_until_ms=now + MIN_VISIBLE_MS,
            expires_at_ms=now + _ttl_for_mode(mode),
            candidates=tuple(fresh_candidates),
            source_summary=source_summary(fresh_candidates),
            lane_status=lane_status,
        )
        next_state = StablePanelState(last_snapshot=snapshot, generation=generation)
        return snapshot, next_state, _diagnostics(
            action="fresh",
            reason="fresh_candidates",
            anchors=anchors,
            snapshot=snapshot,
            previous=previous,
            now_ms=now,
        )

    if previous is not None and previous.hard_context_anchor != anchors.hard_context_anchor:
        reason = "hard_context_anchor_changed"
        next_state = StablePanelState(
            last_snapshot=None,
            last_hard_clear_reason=reason,
            generation=state.generation,
        )
        return None, next_state, _diagnostics(
            action="hard_clear",
            reason=reason,
            anchors=anchors,
            snapshot=None,
            previous=previous,
            now_ms=now,
        )

    if previous is None:
        next_state = StablePanelState(generation=state.generation)
        return None, next_state, _diagnostics(
            action="hidden",
            reason="no_previous_snapshot",
            anchors=anchors,
            snapshot=None,
            previous=None,
            now_ms=now,
        )

    if previous.display_anchor != anchors.display_anchor:
        reason = "display_anchor_changed"
        next_state = StablePanelState(
            last_snapshot=None,
            last_soft_hold_reason=reason,
            generation=state.generation,
        )
        return None, next_state, _diagnostics(
            action="soft_hide",
            reason=reason,
            anchors=anchors,
            snapshot=None,
            previous=previous,
            now_ms=now,
        )

    if now > previous.expires_at_ms:
        reason = "snapshot_expired"
        next_state = StablePanelState(
            last_snapshot=None,
            last_soft_hold_reason=reason,
            generation=state.generation,
        )
        return None, next_state, _diagnostics(
            action="soft_hide",
            reason=reason,
            anchors=anchors,
            snapshot=None,
            previous=previous,
            now_ms=now,
        )

    if now <= previous.min_visible_until_ms:
        reason = "min_visible_window"
        snapshot = _reuse_snapshot(previous, anchors=anchors, lane_status=lane_status, now_ms=now, stale_level="holdover")
        next_state = StablePanelState(
            last_snapshot=snapshot,
            last_soft_hold_reason=reason,
            generation=state.generation,
        )
        return snapshot, next_state, _diagnostics(
            action="soft_hold",
            reason=reason,
            anchors=anchors,
            snapshot=snapshot,
            previous=previous,
            now_ms=now,
        )

    if _lane_empty_or_timed_out(rag_lane or {}) or _lane_empty_or_timed_out(model_lane or {}):
        reason = "lane_empty_or_timeout"
        snapshot = _reuse_snapshot(previous, anchors=anchors, lane_status=lane_status, now_ms=now, stale_level="soft_stale")
        next_state = StablePanelState(
            last_snapshot=snapshot,
            last_soft_hold_reason=reason,
            generation=state.generation,
        )
        return snapshot, next_state, _diagnostics(
            action="reuse_last_good",
            reason=reason,
            anchors=anchors,
            snapshot=snapshot,
            previous=previous,
            now_ms=now,
        )

    if now - previous.updated_at_ms <= NO_CANDIDATE_GRACE_MS:
        reason = "no_candidate_grace"
        snapshot = _reuse_snapshot(previous, anchors=anchors, lane_status=lane_status, now_ms=now, stale_level="soft_stale")
        next_state = StablePanelState(
            last_snapshot=snapshot,
            last_soft_hold_reason=reason,
            generation=state.generation,
        )
        return snapshot, next_state, _diagnostics(
            action="reuse_last_good",
            reason=reason,
            anchors=anchors,
            snapshot=snapshot,
            previous=previous,
            now_ms=now,
        )

    reason = "no_fresh_candidates"
    next_state = StablePanelState(
        last_snapshot=None,
        last_soft_hold_reason=reason,
        generation=state.generation,
    )
    return None, next_state, _diagnostics(
        action="soft_hide",
        reason=reason,
        anchors=anchors,
        snapshot=None,
        previous=previous,
        now_ms=now,
    )


def source_summary(candidates: tuple[object, ...]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for candidate in candidates:
        source = _candidate_source(candidate)
        if not source:
            continue
        summary[source] = summary.get(source, 0) + 1
    return summary


def stable_snapshot_to_payload(snapshot: StableCandidateSnapshot | None) -> dict[str, object]:
    if snapshot is None:
        return {"visible": False}
    return {
        "visible": True,
        "snapshotId": snapshot.snapshot_id,
        "generation": snapshot.generation,
        "hardContextAnchor": snapshot.hard_context_anchor,
        "queryAnchor": snapshot.query_anchor,
        "displayAnchor": snapshot.display_anchor,
        "mode": snapshot.mode,
        "createdAtMs": snapshot.created_at_ms,
        "updatedAtMs": snapshot.updated_at_ms,
        "minVisibleUntilMs": snapshot.min_visible_until_ms,
        "expiresAtMs": snapshot.expires_at_ms,
        "sourceSummary": dict(snapshot.source_summary),
        "reusedLastGood": snapshot.reused_last_good,
        "holdoverHit": snapshot.holdover_hit,
        "staleLevel": snapshot.stale_level,
    }


def _reuse_snapshot(
    previous: StableCandidateSnapshot,
    *,
    anchors: PredictionAnchors,
    lane_status: dict[str, object],
    now_ms: int,
    stale_level: str,
) -> StableCandidateSnapshot:
    return replace(
        previous,
        query_anchor=anchors.query_anchor,
        updated_at_ms=now_ms,
        lane_status=lane_status,
        reused_last_good=True,
        holdover_hit=True,
        stale_level=stale_level,
    )


def _ttl_for_mode(mode: str) -> int:
    family = prediction_mode_family(mode)
    if family == "post_commit":
        return POST_COMMIT_VISIBLE_TTL_MS
    if family in {"prefix_composing", "anchor_composing"}:
        return COMPOSITION_VISIBLE_TTL_MS
    return COMPOSITION_VISIBLE_TTL_MS


def _snapshot_id(
    *,
    generation: int,
    anchors: PredictionAnchors,
    candidates: tuple[object, ...],
    now_ms: int,
) -> str:
    material = {
        "generation": generation,
        "hard": anchors.hard_context_anchor,
        "query": anchors.query_anchor,
        "display": anchors.display_anchor,
        "candidates": [_candidate_key(item) for item in candidates],
        "nowMs": now_ms,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "snap:" + hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def _candidate_key(candidate: object) -> dict[str, object]:
    if isinstance(candidate, Mapping):
        return {
            "label": compact_whitespace(str(candidate.get("label") or "")),
            "text": compact_whitespace(str(candidate.get("text") or "")),
            "sourceType": compact_whitespace(str(candidate.get("sourceType") or candidate.get("source_type") or "")),
            "sourceIndex": int(candidate.get("sourceIndex") or candidate.get("source_index") or 0),
        }
    return {
        "label": compact_whitespace(str(getattr(candidate, "label", ""))),
        "text": compact_whitespace(str(getattr(candidate, "text", ""))),
        "sourceType": compact_whitespace(str(getattr(candidate, "source_type", ""))),
        "sourceIndex": int(getattr(candidate, "source_index", 0) or 0),
    }


def _candidate_source(candidate: object) -> str:
    if isinstance(candidate, Mapping):
        return compact_whitespace(str(candidate.get("sourceType") or candidate.get("source_type") or ""))
    return compact_whitespace(str(getattr(candidate, "source_type", "")))


def _lane_summary(lane: Mapping[str, object]) -> dict[str, object]:
    return {
        "called": bool(lane.get("called")),
        "timedOut": bool(lane.get("timedOut")),
        "holdoverHit": bool(lane.get("holdoverHit")),
        "count": _lane_count(lane),
        "skippedReason": compact_whitespace(str(lane.get("skippedReason") or "")),
    }


def _lane_count(lane: Mapping[str, object]) -> int:
    for key in ("predictionCount", "suggestionCount", "candidateCount"):
        if key in lane:
            try:
                return max(0, int(lane.get(key) or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def _lane_empty_or_timed_out(lane: Mapping[str, object]) -> bool:
    if bool(lane.get("timedOut")) or bool(lane.get("holdoverHit")):
        return True
    if bool(lane.get("called")) and _lane_count(lane) <= 0:
        return True
    skipped_reason = compact_whitespace(str(lane.get("skippedReason") or ""))
    return bool(skipped_reason and "timeout" in skipped_reason.lower())


def _diagnostics(
    *,
    action: str,
    reason: str,
    anchors: PredictionAnchors,
    snapshot: StableCandidateSnapshot | None,
    previous: StableCandidateSnapshot | None,
    now_ms: int,
) -> dict[str, object]:
    return {
        "action": action,
        "reason": reason,
        "nowMs": now_ms,
        "hardContextAnchor": anchors.hard_context_anchor,
        "queryAnchor": anchors.query_anchor,
        "displayAnchor": anchors.display_anchor,
        "modeFamily": anchors.display_fields.get("modeFamily", ""),
        "snapshot": stable_snapshot_to_payload(snapshot),
        "previousSnapshotId": previous.snapshot_id if previous else "",
        "previousExpiresAtMs": previous.expires_at_ms if previous else 0,
        "previousMinVisibleUntilMs": previous.min_visible_until_ms if previous else 0,
    }
