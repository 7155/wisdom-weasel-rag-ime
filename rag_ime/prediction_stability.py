from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .prediction_anchors import PredictionAnchors, prediction_mode_family
from .pinyin_index import text_initials
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
    progressive_update: bool = False,
    max_visible_candidates: int | None = None,
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
        if progressive_update and previous is not None:
            progressive_result = _render_progressive_fresh_candidates(
                state=state,
                previous=previous,
                anchors=anchors,
                mode=mode,
                fresh_candidates=tuple(fresh_candidates),
                lane_status=lane_status,
                now_ms=now,
                max_visible_candidates=max_visible_candidates,
            )
            if progressive_result is not None:
                return progressive_result
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

    prefix_filter_result = _render_prefix_filtered_snapshot(
        state=state,
        previous=previous,
        anchors=anchors,
        mode=mode,
        lane_status=lane_status,
        now_ms=now,
    )
    if prefix_filter_result is not None:
        return prefix_filter_result

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


def _render_prefix_filtered_snapshot(
    *,
    state: StablePanelState,
    previous: StableCandidateSnapshot,
    anchors: PredictionAnchors,
    mode: str,
    lane_status: dict[str, object],
    now_ms: int,
) -> tuple[StableCandidateSnapshot | None, StablePanelState, dict[str, object]] | None:
    if prediction_mode_family(mode) != "prefix_composing":
        return None
    prefix = _active_prefix_from_anchors(anchors)
    if not prefix or _allow_semantic_holdover_for_prefix(prefix):
        return None
    kept: list[object] = []
    removed_count = 0
    side_seen = 0
    side_kept = 0
    for candidate in previous.candidates:
        if _candidate_is_side_prediction(candidate):
            side_seen += 1
            if not _candidate_matches_prefix(candidate, prefix):
                removed_count += 1
                continue
            side_kept += 1
        kept.append(candidate)
    if removed_count <= 0:
        return None

    if not kept:
        reason = "prefix_incompatible_candidates_removed"
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
            now_ms=now_ms,
            extra={
                "prefixFiltered": True,
                "activePinyinPrefix": prefix,
                "prefixRemovedCandidateCount": removed_count,
                "prefixKeptSideCandidateCount": side_kept,
                "previousSideCandidateCount": side_seen,
            },
        )

    generation = max(state.generation, previous.generation) + 1
    snapshot = _new_snapshot(
        generation=generation,
        anchors=anchors,
        mode=mode,
        candidates=tuple(kept),
        lane_status=lane_status,
        now_ms=now_ms,
    )
    snapshot = replace(
        snapshot,
        min_visible_until_ms=max(previous.min_visible_until_ms, snapshot.min_visible_until_ms),
        expires_at_ms=max(previous.expires_at_ms, snapshot.expires_at_ms),
        stale_level="soft_stale",
    )
    next_state = StablePanelState(
        last_snapshot=snapshot,
        last_soft_hold_reason="prefix_filtered_last_good_snapshot",
        generation=generation,
    )
    return snapshot, next_state, _diagnostics(
        action="prefix_filter",
        reason="prefix_incompatible_candidates_removed",
        anchors=anchors,
        snapshot=snapshot,
        previous=previous,
        now_ms=now_ms,
        extra={
            "prefixFiltered": True,
            "activePinyinPrefix": prefix,
            "prefixRemovedCandidateCount": removed_count,
            "prefixKeptSideCandidateCount": side_kept,
            "previousSideCandidateCount": side_seen,
        },
    )


def _render_progressive_fresh_candidates(
    *,
    state: StablePanelState,
    previous: StableCandidateSnapshot,
    anchors: PredictionAnchors,
    mode: str,
    fresh_candidates: tuple[object, ...],
    lane_status: dict[str, object],
    now_ms: int,
    max_visible_candidates: int | None,
) -> tuple[StableCandidateSnapshot | None, StablePanelState, dict[str, object]] | None:
    if previous.hard_context_anchor != anchors.hard_context_anchor:
        return None
    if previous.display_anchor != anchors.display_anchor:
        return None
    if now_ms > previous.expires_at_ms:
        return None

    presentation_replaced = _replace_presentation_stream_candidates(
        previous_candidates=previous.candidates,
        fresh_candidates=fresh_candidates,
        max_visible_candidates=max_visible_candidates,
    )
    if presentation_replaced is not None:
        snapshot = replace(
            previous,
            query_anchor=anchors.query_anchor,
            updated_at_ms=now_ms,
            candidates=presentation_replaced,
            source_summary=source_summary(presentation_replaced),
            lane_status=lane_status,
            min_visible_until_ms=max(previous.min_visible_until_ms, now_ms + MIN_VISIBLE_MS),
            expires_at_ms=max(previous.expires_at_ms, now_ms + _ttl_for_mode(mode)),
            stale_level="fresh",
        )
        next_state = StablePanelState(last_snapshot=snapshot, generation=state.generation)
        return snapshot, next_state, _diagnostics(
            action="progressive_replace",
            reason="presentation_stream_candidate_replaced",
            anchors=anchors,
            snapshot=snapshot,
            previous=previous,
            now_ms=now_ms,
            extra={
                "previousCandidateCount": len(previous.candidates),
                "freshCandidateCount": len(fresh_candidates),
                "appendedCandidateCount": max(0, len(presentation_replaced) - len(previous.candidates)),
                "replacedCandidateCount": 1,
            },
        )

    previous_keys = [_candidate_key(item) for item in previous.candidates]
    fresh_keys = [_candidate_key(item) for item in fresh_candidates]
    preserved_count = _preserved_prefix_count(previous_keys, fresh_keys)
    appended = _append_only_candidates(
        previous_candidates=previous.candidates,
        fresh_candidates=fresh_candidates,
        max_visible_candidates=max_visible_candidates,
    )
    if not appended:
        snapshot = replace(
            previous,
            query_anchor=anchors.query_anchor,
            updated_at_ms=now_ms,
            lane_status=lane_status,
            min_visible_until_ms=max(previous.min_visible_until_ms, now_ms + MIN_VISIBLE_MS),
            expires_at_ms=max(previous.expires_at_ms, now_ms + _ttl_for_mode(mode)),
            stale_level="fresh",
        )
        next_state = StablePanelState(last_snapshot=snapshot, generation=state.generation)
        return snapshot, next_state, _diagnostics(
            action="progressive_append",
            reason="progressive_append_no_new_candidates",
            anchors=anchors,
            snapshot=snapshot,
            previous=previous,
            now_ms=now_ms,
            extra={
                "preservedOrdinalCount": preserved_count,
                "previousCandidateCount": len(previous.candidates),
                "freshCandidateCount": len(fresh_candidates),
                "appendedCandidateCount": 0,
                "reorderedCandidateCount": max(0, len(fresh_candidates) - preserved_count),
                "replacedCandidateCount": 0,
            },
        )
    snapshot = replace(
        previous,
        query_anchor=anchors.query_anchor,
        updated_at_ms=now_ms,
        candidates=previous.candidates + appended,
        source_summary=source_summary(previous.candidates + appended),
        lane_status=lane_status,
        min_visible_until_ms=max(previous.min_visible_until_ms, now_ms + MIN_VISIBLE_MS),
        expires_at_ms=max(previous.expires_at_ms, now_ms + _ttl_for_mode(mode)),
        stale_level="fresh",
    )
    next_state = StablePanelState(last_snapshot=snapshot, generation=state.generation)
    return snapshot, next_state, _diagnostics(
        action="progressive_append",
        reason="progressive_appended_prediction_candidates",
        anchors=anchors,
        snapshot=snapshot,
        previous=previous,
        now_ms=now_ms,
        extra={
            "preservedOrdinalCount": preserved_count,
            "previousCandidateCount": len(previous.candidates),
            "freshCandidateCount": len(fresh_candidates),
            "appendedCandidateCount": len(appended),
            "reorderedCandidateCount": max(0, len(fresh_candidates) - preserved_count),
            "replacedCandidateCount": 0,
        },
    )


def _new_snapshot(
    *,
    generation: int,
    anchors: PredictionAnchors,
    mode: str,
    candidates: tuple[object, ...],
    lane_status: dict[str, object],
    now_ms: int,
) -> StableCandidateSnapshot:
    return StableCandidateSnapshot(
        snapshot_id=_snapshot_id(
            generation=generation,
            anchors=anchors,
            candidates=candidates,
            now_ms=now_ms,
        ),
        generation=generation,
        hard_context_anchor=anchors.hard_context_anchor,
        query_anchor=anchors.query_anchor,
        display_anchor=anchors.display_anchor,
        mode=compact_whitespace(mode),
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
        min_visible_until_ms=now_ms + MIN_VISIBLE_MS,
        expires_at_ms=now_ms + _ttl_for_mode(mode),
        candidates=tuple(candidates),
        source_summary=source_summary(tuple(candidates)),
        lane_status=lane_status,
    )


def _preserved_prefix_count(previous_keys: list[dict[str, object]], fresh_keys: list[dict[str, object]]) -> int:
    count = 0
    for previous_key, fresh_key in zip(previous_keys, fresh_keys):
        if previous_key != fresh_key:
            break
        count += 1
    return count


def _append_only_candidates(
    *,
    previous_candidates: tuple[object, ...],
    fresh_candidates: tuple[object, ...],
    max_visible_candidates: int | None,
) -> tuple[object, ...]:
    try:
        limit = max(0, int(max_visible_candidates)) if max_visible_candidates is not None else len(fresh_candidates)
    except (TypeError, ValueError):
        limit = len(fresh_candidates)
    remaining_slots = max(0, limit - len(previous_candidates))
    if remaining_slots <= 0:
        return ()
    previous_keys = {_stable_candidate_key_json(item) for item in previous_candidates}
    appendable: list[object] = []
    for candidate in fresh_candidates:
        key = _stable_candidate_key_json(candidate)
        if key in previous_keys:
            continue
        appendable.append(candidate)
        previous_keys.add(key)
        if len(appendable) >= remaining_slots:
            break
    return tuple(appendable)


def _replace_presentation_stream_candidates(
    *,
    previous_candidates: tuple[object, ...],
    fresh_candidates: tuple[object, ...],
    max_visible_candidates: int | None,
) -> tuple[object, ...] | None:
    previous_keys = [_presentation_stream_slot_key(item) for item in previous_candidates]
    fresh_keys = [_presentation_stream_slot_key(item) for item in fresh_candidates]
    if not any(fresh_keys):
        return None
    replaced = False
    result = list(previous_candidates)
    for fresh, fresh_key in zip(fresh_candidates, fresh_keys):
        if not fresh_key:
            continue
        try:
            index = previous_keys.index(fresh_key)
        except ValueError:
            continue
        result[index] = fresh
        replaced = True
    if not replaced:
        return None
    existing_keys = {_stable_candidate_key_json(item) for item in result}
    try:
        limit = max(0, int(max_visible_candidates)) if max_visible_candidates is not None else len(result)
    except (TypeError, ValueError):
        limit = len(result)
    for fresh, fresh_key in zip(fresh_candidates, fresh_keys):
        if fresh_key:
            continue
        stable_key = _stable_candidate_key_json(fresh)
        if stable_key in existing_keys or len(result) >= limit:
            continue
        result.append(fresh)
        existing_keys.add(stable_key)
    return tuple(result)


def _presentation_stream_slot_key(candidate: object) -> str:
    metadata = _candidate_metadata(candidate)
    if not bool(metadata.get("presentationStreaming")):
        return ""
    explicit_slot = compact_whitespace(str(metadata.get("presentationStreamSlotKey") or ""))
    if explicit_slot:
        return json.dumps(
            {"slot": explicit_slot},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    final_hash = compact_whitespace(str(metadata.get("presentationFinalTextHash") or ""))
    if not final_hash:
        return ""
    key = _candidate_key(candidate)
    return json.dumps(
        {
            "sourceType": key.get("sourceType"),
            "sourceIndex": key.get("sourceIndex"),
            "finalTextHash": final_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_candidate_key_json(candidate: object) -> str:
    return json.dumps(_candidate_key(candidate), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _candidate_metadata(candidate: object) -> dict[str, object]:
    if isinstance(candidate, Mapping):
        metadata = candidate.get("metadata")
    else:
        metadata = getattr(candidate, "metadata", {})
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _candidate_text(candidate: object, key: str) -> str:
    if isinstance(candidate, Mapping):
        return compact_whitespace(str(candidate.get(key) or ""))
    return compact_whitespace(str(getattr(candidate, key, "") or ""))


def _candidate_is_side_prediction(candidate: object) -> bool:
    return _candidate_source(candidate) in {"model", "rag", "memory"}


def _active_prefix_from_anchors(anchors: PredictionAnchors) -> str:
    return _pinyin_norm(str(anchors.query_fields.get("stableShortPinyinPrefix") or ""))


def _allow_semantic_holdover_for_prefix(prefix: str) -> bool:
    return len(_pinyin_norm(prefix)) >= 6


def _candidate_matches_prefix(candidate: object, prefix: str) -> bool:
    prefix_norm = _pinyin_norm(prefix)
    if not prefix_norm:
        return True
    keys = _candidate_pinyin_keys(candidate)
    return any(key.startswith(prefix_norm) for key in keys)


def _candidate_pinyin_keys(candidate: object) -> tuple[str, ...]:
    metadata = _candidate_metadata(candidate)
    keys: list[str] = []
    for key in ("initials", "pinyin_initials"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            keys.append(_pinyin_norm(value))
    for key in ("full_pinyin", "pinyin"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts = value.replace("'", " ").split()
            keys.append(_pinyin_norm("".join(parts)))
            keys.extend(_pinyin_norm(part) for part in parts)
        elif isinstance(value, (list, tuple)):
            parts = [_pinyin_norm(str(item)) for item in value]
            keys.append(_pinyin_norm("".join(parts)))
            keys.extend(parts)
    for key in ("text", "insert_text", "insertText"):
        text = _candidate_text(candidate, key)
        if text:
            keys.append(_pinyin_norm(text_initials(text)))
    return tuple(item for item in dict.fromkeys(keys) if item)


def _pinyin_norm(value: str) -> str:
    return "".join(char.lower() for char in compact_whitespace(value) if char.isascii() and char.isalnum())


def _lane_summary(lane: Mapping[str, object]) -> dict[str, object]:
    return {
        "called": bool(lane.get("called")),
        "timedOut": bool(lane.get("timedOut")),
        "holdoverHit": bool(lane.get("holdoverHit")),
        "staleDropped": bool(lane.get("staleDropped")),
        "count": _lane_count(lane),
        "skippedReason": compact_whitespace(str(lane.get("skippedReason") or "")),
        "staleDropReason": compact_whitespace(str(lane.get("staleDropReason") or "")),
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
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload = {
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
    if extra:
        payload.update(dict(extra))
    return payload
