from __future__ import annotations

from collections.abc import Mapping, Sequence


CANDIDATE_PANEL_SCHEMA_VERSION = "rag-ime.candidate-panel.v1"
ASSISTANT_OVERLAY_SCHEMA_VERSION = "rag-ime.assistant-overlay.v1"

_COMPOSITION_INPUT_MODES = {"anchor_composing", "prefix_constrained_composing"}
_OVERLAY_CANDIDATE_SOURCE_TYPES = {"model", "rag", "memory", "action"}


def build_candidate_panel_payload(
    *,
    input_mode: str,
    display_candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Payload for the native Rime/Squirrel candidate panel.

    This panel must remain Rime-only in composition; AI/status/action rows are
    consumed by the assistant overlay instead of polluting digit selection.
    """

    rime_candidates = [
        dict(candidate)
        for candidate in display_candidates
        if str(candidate.get("sourceType") or "") == "rime"
    ]
    return {
        "schemaVersion": CANDIDATE_PANEL_SCHEMA_VERSION,
        "mode": "rime_only",
        "inputMode": input_mode,
        "candidates": rime_candidates,
        "candidateCount": len(rime_candidates),
    }


def build_assistant_overlay_payload(
    *,
    ui_mode: str,
    input_mode: str,
    display_candidates: Sequence[Mapping[str, object]],
    rag_candidates: Sequence[Mapping[str, object]],
    prediction_session: Mapping[str, object] | None,
    key_policy: Mapping[str, object] | None,
    progressive: Mapping[str, object] | None,
    frontend_transaction: Mapping[str, object] | None,
) -> dict[str, object]:
    if input_mode in _COMPOSITION_INPUT_MODES:
        return _hidden_overlay_payload(
            ui_mode=ui_mode,
            input_mode=input_mode,
            key_policy=key_policy,
            progressive=progressive,
            frontend_transaction=frontend_transaction,
            reason="composition_owned_by_rime",
        )

    status_rows = [
        dict(candidate)
        for candidate in display_candidates
        if str(candidate.get("sourceType") or "") == "status" or bool(candidate.get("isStatus"))
    ]
    overlay_candidates = [
        dict(candidate)
        for candidate in display_candidates
        if str(candidate.get("sourceType") or "") in _OVERLAY_CANDIDATE_SOURCE_TYPES
    ]
    actual_candidates = [
        candidate
        for candidate in overlay_candidates
        if str(candidate.get("sourceType") or "") != "status"
    ]
    pending = _overlay_is_pending(
        ui_mode=ui_mode,
        progressive=progressive,
        status_rows=status_rows,
        actual_candidates=actual_candidates,
    )
    source_cards = _source_cards_from_candidates(display_candidates=display_candidates, rag_candidates=rag_candidates)
    visible = bool(
        actual_candidates
        or status_rows
        or pending
        or ui_mode.startswith("post_commit")
    )
    status_text = _status_text(
        ui_mode=ui_mode,
        pending=pending,
        status_rows=status_rows,
        actual_candidate_count=len(actual_candidates),
    )
    session = dict(prediction_session or {})
    return {
        "schemaVersion": ASSISTANT_OVERLAY_SCHEMA_VERSION,
        "visible": visible,
        "uiMode": ui_mode,
        "phase": _overlay_phase(input_mode=input_mode, session=session),
        "inputMode": input_mode,
        "statusText": status_text,
        "animation": {
            "kind": "thinking_dots" if pending else "none",
            "frame": int(session.get("requestSeq") or 0) % 3,
        },
        "candidates": actual_candidates,
        "sourceCards": source_cards,
        "snapshotId": str(session.get("snapshotId") or session.get("stableSnapshotId") or ""),
        "sessionFingerprint": str(session.get("sessionFingerprint") or ""),
        "expiresAfterMs": int(session.get("expiresAfterMs") or 0),
        "keyPolicy": dict(key_policy or {}),
        "progressive": dict(progressive or {}),
        "frontendTransaction": dict(frontend_transaction or {}),
        "dismissReason": "" if visible else "empty_overlay",
    }


def _hidden_overlay_payload(
    *,
    ui_mode: str,
    input_mode: str,
    key_policy: Mapping[str, object] | None,
    progressive: Mapping[str, object] | None,
    frontend_transaction: Mapping[str, object] | None,
    reason: str,
) -> dict[str, object]:
    return {
        "schemaVersion": ASSISTANT_OVERLAY_SCHEMA_VERSION,
        "visible": False,
        "uiMode": ui_mode,
        "phase": "composition",
        "inputMode": input_mode,
        "statusText": "",
        "animation": {"kind": "none", "frame": 0},
        "candidates": [],
        "sourceCards": [],
        "snapshotId": "",
        "sessionFingerprint": "",
        "expiresAfterMs": 0,
        "keyPolicy": dict(key_policy or {}),
        "progressive": dict(progressive or {}),
        "frontendTransaction": dict(frontend_transaction or {}),
        "dismissReason": reason,
    }


def _overlay_is_pending(
    *,
    ui_mode: str,
    progressive: Mapping[str, object] | None,
    status_rows: Sequence[Mapping[str, object]],
    actual_candidates: Sequence[Mapping[str, object]],
) -> bool:
    if actual_candidates:
        return any(
            bool(dict(candidate.get("metadata") if isinstance(candidate.get("metadata"), Mapping) else {}).get("presentationPartial"))
            for candidate in actual_candidates
        )
    if "pending" in ui_mode:
        return True
    state = dict(progressive or {})
    if bool(state.get("partial")) or bool(state.get("shouldFollowUp")):
        return True
    return any("中" in str(row.get("text") or row.get("insertText") or "") for row in status_rows)


def _status_text(
    *,
    ui_mode: str,
    pending: bool,
    status_rows: Sequence[Mapping[str, object]],
    actual_candidate_count: int,
) -> str:
    if status_rows:
        row_text = str(status_rows[0].get("text") or status_rows[0].get("insertText") or "").strip()
        if row_text:
            return row_text
    if pending:
        return "AI 正在想..."
    if actual_candidate_count:
        return "AI 建议"
    if ui_mode.startswith("post_commit"):
        return "AI 待命"
    return ""


def _overlay_phase(*, input_mode: str, session: Mapping[str, object]) -> str:
    phase = str(session.get("phase") or "")
    if phase:
        return phase
    if input_mode == "post_commit_predicting":
        return "post_commit"
    if input_mode in _COMPOSITION_INPUT_MODES:
        return "composition"
    return input_mode or "unknown"


def _source_cards_from_candidates(
    *,
    display_candidates: Sequence[Mapping[str, object]],
    rag_candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in display_candidates:
        source_type = str(candidate.get("sourceType") or "")
        if source_type not in {"rag", "memory"}:
            continue
        key = str(candidate.get("suggestionId") or candidate.get("memoryId") or candidate.get("text") or "")
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            {
                "sourceType": source_type,
                "sourceBadge": candidate.get("sourceBadge") or candidate.get("badge") or source_type,
                "title": candidate.get("text") or candidate.get("insertText") or "",
                "evidencePreview": candidate.get("evidencePreview") or candidate.get("comment") or "",
                "confidence": candidate.get("metadata", {}).get("confidence") if isinstance(candidate.get("metadata"), Mapping) else None,
                "suggestionId": candidate.get("suggestionId") or "",
                "memoryId": candidate.get("memoryId") or "",
            }
        )
        if len(cards) >= 3:
            return cards
    for candidate in rag_candidates:
        metadata = candidate.get("metadata")
        metadata_map = metadata if isinstance(metadata, Mapping) else {}
        source_type = str(metadata_map.get("source_type") or candidate.get("suggestionType") or "rag")
        if source_type not in {"rag", "memory", "phrase"}:
            source_type = "rag"
        key = str(candidate.get("suggestionId") or candidate.get("memoryId") or candidate.get("surfaceText") or "")
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            {
                "sourceType": "memory" if source_type == "phrase" else source_type,
                "sourceBadge": "忆" if source_type in {"memory", "phrase"} else "RAG",
                "title": candidate.get("surfaceText") or candidate.get("insertText") or "",
                "evidencePreview": candidate.get("evidencePreview") or "",
                "confidence": candidate.get("confidence"),
                "suggestionId": candidate.get("suggestionId") or "",
                "memoryId": candidate.get("memoryId") or "",
            }
        )
        if len(cards) >= 3:
            return cards
    return cards
