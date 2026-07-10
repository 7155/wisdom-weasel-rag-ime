from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from .context_provenance import (
    ForegroundTextSource,
    committed_source,
    selected_text_identity,
    source_confidence,
)
from .models import FrontendTransaction, RimeCandidate, RimeContextSnapshot
from .prediction_anchors import PredictionAnchors, build_prediction_anchors_from_snapshot
from .text_utils import compact_whitespace, now_ms, stable_text_hash, truncate_text


@dataclass(frozen=True)
class InputSessionIdentity:
    session_id: str
    request_seq: int
    panel_session_id: str
    input_generation: int


@dataclass(frozen=True)
class InputUiState:
    ui_mode: Literal["composition_rime", "post_commit_pending", "post_commit_prediction", "active_rag_assist"]
    front_app_bundle_id: str
    input_source_id: str
    project: str
    app: str


@dataclass(frozen=True)
class CompositionContext:
    raw_input: str
    preedit: str
    rime_candidates: tuple[RimeCandidate, ...]
    highlighted_index: int
    page: int
    is_last_page: bool


@dataclass(frozen=True)
class CommittedContext:
    commit_text_preview: str
    committed_tail: str
    committed_context_hash: str
    source: Literal["ime_commit_ledger", "frontend_snapshot", "unknown"]
    confidence: float


@dataclass(frozen=True)
class ForegroundTextSnapshot:
    available: bool
    source: ForegroundTextSource
    confidence: float
    freshness_ms: int
    selected_text_hash: str = ""
    selected_text_chars: int = 0
    selected_text_preview: str = ""
    surrounding_before: str = ""
    surrounding_after: str = ""
    whole_value_hash: str = ""
    whole_value_chars: int = 0
    can_replace_selection: bool = False
    capture_epoch: int = 0
    captured_at_ms: int = 0
    source_app_bundle_id: str = ""
    input_source_id: str = ""
    capture_failure_reason: str = ""
    warnings: tuple[str, ...] = ()
    snapshot_id: str = ""
    context_group_id: str = ""
    context_group_level: str = "app"
    context_group_confidence: float = 0.0
    commit_text_matched: bool = False


@dataclass(frozen=True)
class ContextPrivacyState:
    raw_text_redacted_in_trace: bool
    sensitive_text_blocked: bool
    capture_allowed: bool
    redaction_reason: str = ""


@dataclass(frozen=True)
class CurrentInputFrame:
    schema_version: str
    frame_id: str
    created_at_ms: int
    session: InputSessionIdentity
    ui: InputUiState
    composition: CompositionContext
    committed: CommittedContext
    foreground_text: ForegroundTextSnapshot
    transaction: FrontendTransaction
    anchors: PredictionAnchors
    privacy: ContextPrivacyState
    diagnostics: dict[str, object] = field(default_factory=dict)


def build_current_input_frame(
    snapshot: RimeContextSnapshot,
    *,
    ui_mode: str,
    semantic_query: str = "",
    query_basis: str = "",
    anchors: PredictionAnchors | None = None,
    foreground_text_payload: Mapping[str, object] | None = None,
    created_at_ms: int | None = None,
) -> CurrentInputFrame:
    transaction = snapshot.frontend_transaction
    resolved_ui_mode = _ui_mode(ui_mode)
    input_generation = transaction.input_generation or transaction.frontend_revision
    created = now_ms() if created_at_ms is None else max(0, int(created_at_ms))
    resolved_anchors = anchors or build_prediction_anchors_from_snapshot(
        snapshot=snapshot,
        mode=_anchor_mode_for_ui(resolved_ui_mode),
        semantic_query=semantic_query,
        query_basis=query_basis,
    )
    committed_tail = compact_whitespace(snapshot.committed_context)[-420:]
    source = committed_source(
        committed_context=snapshot.committed_context,
        commit_text_preview=snapshot.commit_text_preview,
    )
    foreground = foreground_text_from_payload(
        foreground_text_payload,
        snapshot=snapshot,
        created_at_ms=created,
    )
    frame_id = "ctx:" + ":".join(
        (
            compact_whitespace(snapshot.session_id) or "default",
            compact_whitespace(transaction.panel_session_id) or "panel",
            str(snapshot.request_seq),
            str(input_generation),
        )
    )
    return CurrentInputFrame(
        schema_version="rag-ime.context-frame.v1",
        frame_id=frame_id,
        created_at_ms=created,
        session=InputSessionIdentity(
            session_id=snapshot.session_id,
            request_seq=snapshot.request_seq,
            panel_session_id=transaction.panel_session_id,
            input_generation=input_generation,
        ),
        ui=InputUiState(
            ui_mode=resolved_ui_mode,
            front_app_bundle_id=transaction.front_app_bundle_id or snapshot.app,
            input_source_id=transaction.input_source_id,
            project=snapshot.project,
            app=snapshot.app,
        ),
        composition=CompositionContext(
            raw_input=snapshot.raw_input,
            preedit=snapshot.preedit,
            rime_candidates=snapshot.candidates,
            highlighted_index=snapshot.highlighted_index,
            page=snapshot.page,
            is_last_page=snapshot.is_last_page,
        ),
        committed=CommittedContext(
            commit_text_preview=snapshot.commit_text_preview,
            committed_tail=committed_tail,
            committed_context_hash=transaction.committed_context_hash or stable_text_hash(snapshot.committed_context),
            source=source,
            confidence=source_confidence(source),
        ),
        foreground_text=foreground,
        transaction=transaction,
        anchors=resolved_anchors,
        privacy=ContextPrivacyState(
            raw_text_redacted_in_trace=True,
            sensitive_text_blocked=False,
            capture_allowed=foreground.source not in {"accessibility", "clipboard_fallback", "manual_clipboard"},
            redaction_reason="trace text redacted by default",
        ),
        diagnostics={
            "semanticQueryHash": stable_text_hash(semantic_query),
            "queryBasis": compact_whitespace(query_basis),
        },
    )


def foreground_text_from_payload(
    payload: Mapping[str, object] | None,
    *,
    snapshot: RimeContextSnapshot,
    created_at_ms: int,
) -> ForegroundTextSnapshot:
    source_text = compact_whitespace(_string((payload or {}).get("source")))
    if not payload:
        if snapshot.raw_input or snapshot.preedit:
            return ForegroundTextSnapshot(
                available=True,
                source="rime_composition",
                confidence=1.0,
                freshness_ms=0,
                surrounding_before=compact_whitespace(snapshot.preedit or snapshot.raw_input),
                capture_epoch=snapshot.frontend_transaction.input_generation
                or snapshot.frontend_transaction.frontend_revision,
            )
        if snapshot.committed_context or snapshot.commit_text_preview:
            return ForegroundTextSnapshot(
                available=True,
                source="ime_commit_ledger",
                confidence=source_confidence("ime_commit_ledger"),
                freshness_ms=0,
                surrounding_before=compact_whitespace(snapshot.committed_context)[-160:],
                capture_epoch=snapshot.frontend_transaction.input_generation
                or snapshot.frontend_transaction.frontend_revision,
            )
        return ForegroundTextSnapshot(available=False, source="unavailable", confidence=0.0, freshness_ms=0)
    source: ForegroundTextSource = _foreground_source(source_text)
    selected_preview = compact_whitespace(_string(payload.get("selectedTextPreview")))
    selected_hash = compact_whitespace(_string(payload.get("selectedTextHash")))
    selected_chars = _int(payload.get("selectedTextChars"), default=0)
    if selected_preview and not selected_hash:
        selected_hash, selected_chars = selected_text_identity(selected_preview)
    whole_hash = compact_whitespace(_string(payload.get("wholeValueHash")))
    whole_chars = _int(payload.get("wholeValueChars"), default=0)
    captured_at_ms = max(0, _int(payload.get("capturedAtMs"), default=0))
    declared_freshness_ms = max(0, _int(payload.get("freshnessMs"), default=0))
    measured_freshness_ms = max(0, created_at_ms - captured_at_ms) if captured_at_ms else 0
    return ForegroundTextSnapshot(
        available=_bool(payload.get("available"), default=source != "unavailable"),
        source=source,
        confidence=_float(payload.get("confidence"), default=source_confidence(source)),
        freshness_ms=max(declared_freshness_ms, measured_freshness_ms),
        selected_text_hash=selected_hash,
        selected_text_chars=selected_chars,
        selected_text_preview=selected_preview,
        surrounding_before=compact_whitespace(_string(payload.get("surroundingBefore"))),
        surrounding_after=compact_whitespace(_string(payload.get("surroundingAfter"))),
        whole_value_hash=whole_hash,
        whole_value_chars=whole_chars,
        can_replace_selection=_bool(payload.get("canReplaceSelection"), default=False),
        capture_epoch=_int(payload.get("captureEpoch"), default=snapshot.frontend_transaction.input_generation),
        captured_at_ms=captured_at_ms,
        source_app_bundle_id=compact_whitespace(_string(payload.get("sourceAppBundleId"))),
        input_source_id=compact_whitespace(_string(payload.get("inputSourceId"))),
        capture_failure_reason=compact_whitespace(_string(payload.get("captureFailureReason"))),
        warnings=tuple(
            compact_whitespace(str(item))
            for item in payload.get("warnings", ())
            if compact_whitespace(str(item))
        )
        if isinstance(payload.get("warnings"), (list, tuple))
        else (),
        snapshot_id=compact_whitespace(_string(payload.get("snapshotId"))),
        context_group_id=compact_whitespace(_string(payload.get("contextGroupId"))),
        context_group_level=compact_whitespace(_string(payload.get("contextGroupLevel"))) or "app",
        context_group_confidence=_float(payload.get("contextGroupConfidence"), default=0.0),
        commit_text_matched=_bool(payload.get("commitTextMatched"), default=False),
    )


def context_frame_trace_payload(frame: CurrentInputFrame, *, include_text: bool = False) -> dict[str, object]:
    foreground = frame.foreground_text
    composition = frame.composition
    committed = frame.committed
    payload: dict[str, object] = {
        "schemaVersion": frame.schema_version,
        "frameId": frame.frame_id,
        "createdAtMs": frame.created_at_ms,
        "uiMode": frame.ui.ui_mode,
        "session": {
            "sessionId": frame.session.session_id,
            "requestSeq": frame.session.request_seq,
            "panelSessionId": frame.session.panel_session_id,
            "inputGeneration": frame.session.input_generation,
        },
        "foregroundText": {
            "available": foreground.available,
            "source": foreground.source,
            "confidence": foreground.confidence,
            "freshnessMs": foreground.freshness_ms,
            "selectedTextHash": foreground.selected_text_hash,
            "selectedTextChars": foreground.selected_text_chars,
            "surroundingBeforeChars": len(compact_whitespace(foreground.surrounding_before)),
            "surroundingAfterChars": len(compact_whitespace(foreground.surrounding_after)),
            "wholeValueHash": foreground.whole_value_hash,
            "wholeValueChars": foreground.whole_value_chars,
            "canReplaceSelection": foreground.can_replace_selection,
            "captureEpoch": foreground.capture_epoch,
            "capturedAtMs": foreground.captured_at_ms,
            "sourceAppBundleId": foreground.source_app_bundle_id,
            "inputSourceId": foreground.input_source_id,
            "captureFailureReason": foreground.capture_failure_reason,
            "warnings": list(foreground.warnings),
            "snapshotId": foreground.snapshot_id,
            "contextGroupId": foreground.context_group_id,
            "contextGroupLevel": foreground.context_group_level,
            "contextGroupConfidence": foreground.context_group_confidence,
            "commitTextMatched": foreground.commit_text_matched,
        },
        "composition": {
            "rawInputHash": stable_text_hash(composition.raw_input),
            "preeditHash": stable_text_hash(composition.preedit),
            "rimeCandidateCount": len(composition.rime_candidates),
            "highlightedIndex": composition.highlighted_index,
            "page": composition.page,
            "isLastPage": composition.is_last_page,
        },
        "committed": {
            "commitTextPreviewHash": stable_text_hash(committed.commit_text_preview),
            "committedTailChars": len(committed.committed_tail),
            "committedContextHash": committed.committed_context_hash,
            "source": committed.source,
            "confidence": committed.confidence,
        },
        "anchors": {
            "hardClearAnchor": frame.anchors.hard_clear_anchor,
            "applyAnchor": frame.anchors.apply_anchor,
            "queryAnchor": frame.anchors.query_anchor,
            "displayAnchor": frame.anchors.display_anchor,
        },
        "privacy": {
            "rawTextRedactedInTrace": not include_text or frame.privacy.raw_text_redacted_in_trace,
            "sensitiveTextBlocked": frame.privacy.sensitive_text_blocked,
            "captureAllowed": frame.privacy.capture_allowed,
            "redactionReason": frame.privacy.redaction_reason,
        },
        "diagnostics": dict(frame.diagnostics),
    }
    if include_text:
        payload["foregroundText"]["selectedTextPreview"] = truncate_text(foreground.selected_text_preview, 80)
        payload["foregroundText"]["surroundingBefore"] = truncate_text(foreground.surrounding_before, 120)
        payload["foregroundText"]["surroundingAfter"] = truncate_text(foreground.surrounding_after, 120)
    return payload


def _anchor_mode_for_ui(ui_mode: str) -> str:
    if ui_mode == "composition_rime":
        return "prefix_constrained_composing"
    if ui_mode.startswith("post_commit"):
        return "post_commit_predicting"
    return ui_mode


def _ui_mode(value: str) -> Literal["composition_rime", "post_commit_pending", "post_commit_prediction", "active_rag_assist"]:
    normalized = compact_whitespace(value)
    if normalized in {"composition_rime", "post_commit_pending", "post_commit_prediction", "active_rag_assist"}:
        return normalized  # type: ignore[return-value]
    return "composition_rime" if normalized.endswith("composing") else "post_commit_prediction"


def _foreground_source(value: str) -> ForegroundTextSource:
    if value in {
        "unavailable",
        "rime_composition",
        "ime_commit_ledger",
        "text_input_client",
        "accessibility",
        "clipboard_fallback",
        "manual_clipboard",
    }:
        return value  # type: ignore[return-value]
    return "unavailable"


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return default


def _float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    try:
        return max(0.0, min(1.0, float(str(value).strip())))
    except ValueError:
        return default


def _bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default
