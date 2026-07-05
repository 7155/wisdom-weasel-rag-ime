from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .models import RimeCandidate, RimeContextSnapshot
from .text_utils import compact_whitespace, stable_text_hash


@dataclass(frozen=True)
class PredictionAnchors:
    """Stable identities for prediction refresh, display reuse, and hard clears."""

    hard_context_anchor: str
    query_anchor: str
    display_anchor: str
    hard_fields: dict[str, object]
    query_fields: dict[str, object]
    display_fields: dict[str, object]


def build_prediction_anchors(
    *,
    session_id: str,
    panel_session_id: str = "",
    front_app_bundle_id: str = "",
    input_source_id: str = "",
    selection_epoch: int = 0,
    committed_context_hash: str = "",
    composition_hash: str = "",
    mode: str = "",
    semantic_query: str = "",
    query_basis: str = "",
    stable_short_pinyin_prefix: str = "",
    preedit: str = "",
    rime_candidates: tuple[RimeCandidate, ...] = (),
) -> PredictionAnchors:
    mode_family = prediction_mode_family(mode)
    hard_fields: dict[str, object] = {
        "sessionId": compact_whitespace(session_id),
        "panelSessionId": compact_whitespace(panel_session_id),
        "frontAppBundleId": compact_whitespace(front_app_bundle_id),
        "inputSourceId": compact_whitespace(input_source_id),
        "selectionEpoch": max(0, int(selection_epoch)),
        "committedContextHash": _hash_or_empty(committed_context_hash),
        "compositionHash": _hash_or_empty(composition_hash),
    }
    query_fields: dict[str, object] = {
        "mode": compact_whitespace(mode),
        "semanticQueryHash": stable_text_hash(compact_whitespace(semantic_query)),
        "queryBasis": compact_whitespace(query_basis),
        "stableShortPinyinPrefix": compact_whitespace(stable_short_pinyin_prefix),
        "preeditHash": stable_text_hash(compact_whitespace(preedit)),
        "rimeCandidatesHash": _rime_candidates_hash(rime_candidates),
    }
    hard_anchor = _sha16(hard_fields)
    query_anchor = _sha16({"hardContextAnchor": hard_anchor, **query_fields})
    display_fields: dict[str, object] = {
        "hardContextAnchor": hard_anchor,
        "modeFamily": mode_family,
    }
    return PredictionAnchors(
        hard_context_anchor=hard_anchor,
        query_anchor=query_anchor,
        display_anchor=_sha16(display_fields),
        hard_fields=hard_fields,
        query_fields=query_fields,
        display_fields=display_fields,
    )


def build_prediction_anchors_from_snapshot(
    *,
    snapshot: RimeContextSnapshot,
    mode: str,
    semantic_query: str = "",
    query_basis: str = "",
    stable_short_pinyin_prefix: str = "",
) -> PredictionAnchors:
    transaction = snapshot.frontend_transaction
    committed_hash = transaction.committed_context_hash or stable_text_hash(snapshot.committed_context)
    composition_hash = transaction.composition_hash or stable_text_hash(snapshot.preedit or snapshot.raw_input)
    return build_prediction_anchors(
        session_id=snapshot.session_id,
        panel_session_id=transaction.panel_session_id,
        front_app_bundle_id=transaction.front_app_bundle_id or snapshot.app,
        input_source_id=transaction.input_source_id,
        selection_epoch=transaction.selection_epoch,
        committed_context_hash=committed_hash,
        composition_hash=composition_hash,
        mode=mode,
        semantic_query=semantic_query,
        query_basis=query_basis,
        stable_short_pinyin_prefix=stable_short_pinyin_prefix,
        preedit=snapshot.preedit or snapshot.raw_input,
        rime_candidates=snapshot.candidates,
    )


def prediction_mode_family(mode: str) -> str:
    normalized = compact_whitespace(mode)
    if normalized == "post_commit_predicting":
        return "post_commit"
    if normalized == "prefix_constrained_composing":
        return "prefix_composing"
    if normalized == "anchor_composing":
        return "anchor_composing"
    if normalized == "raw_input":
        return "raw"
    return normalized or "unknown"


def _sha16(material: object) -> str:
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _hash_or_empty(value: str) -> str:
    text = compact_whitespace(value)
    return text if text else ""


def _rime_candidates_hash(candidates: tuple[RimeCandidate, ...]) -> str:
    material: list[dict[str, Any]] = []
    for candidate in candidates[:8]:
        material.append(
            {
                "text": compact_whitespace(candidate.text),
                "comment": compact_whitespace(candidate.comment),
                "index": int(candidate.index),
            }
        )
    return _sha16(material)
