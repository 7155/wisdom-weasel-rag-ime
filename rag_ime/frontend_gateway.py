from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


FRONTEND_GATEWAY_VERSION = "rag-ime.frontend-gateway.v1"
FRONTEND_SUGGEST_REQUEST_VERSION = "rag-ime.frontend-suggest-request.v1"
FRONTEND_SUGGEST_RESPONSE_VERSION = "rag-ime.frontend-suggest-response.v1"
FRONTEND_SELECTION_VERSION = "rag-ime.frontend-selection.v1"
FRONTEND_SELECTION_RESPONSE_VERSION = "rag-ime.frontend-selection-response.v1"
FRONTEND_CAPABILITIES_VERSION = "rag-ime.frontend-capabilities.v1"


SuggestHandler = Callable[[dict[str, Any]], dict[str, object]]
SelectionHandler = Callable[[dict[str, Any]], dict[str, object]]


@dataclass(frozen=True)
class FrontendGateway:
    """Translate a small engine-neutral contract onto the existing IME core."""

    suggest_handler: SuggestHandler
    selection_handler: SelectionHandler
    default_project: str = "wisdom-weasel-rag-ime"

    def capabilities(self) -> dict[str, object]:
        return frontend_capabilities()

    def suggest(self, payload: dict[str, Any]) -> dict[str, object]:
        legacy_request = frontend_suggest_to_legacy(payload, default_project=self.default_project)
        legacy_response = self.suggest_handler(legacy_request)
        return frontend_suggest_from_legacy(payload, legacy_response)

    def select(self, payload: dict[str, Any]) -> dict[str, object]:
        legacy_request = frontend_selection_to_legacy(payload, default_project=self.default_project)
        legacy_response = self.selection_handler(legacy_request)
        return frontend_selection_from_legacy(payload, legacy_response)


def frontend_capabilities() -> dict[str, object]:
    return {
        "schemaVersion": FRONTEND_CAPABILITIES_VERSION,
        "gatewayVersion": FRONTEND_GATEWAY_VERSION,
        "contracts": {
            "suggestRequest": FRONTEND_SUGGEST_REQUEST_VERSION,
            "suggestResponse": FRONTEND_SUGGEST_RESPONSE_VERSION,
            "selectionRequest": FRONTEND_SELECTION_VERSION,
            "selectionResponse": FRONTEND_SELECTION_RESPONSE_VERSION,
        },
        "features": {
            "nativeCandidates": True,
            "modelCandidates": True,
            "retrievalCandidates": True,
            "memoryCandidates": True,
            "progressiveResponses": True,
            "selectionFeedback": True,
            "privacyAttestationRequired": True,
        },
        "adapterBoundary": {
            "required": ["frontend", "session", "privacy", "input"],
            "nativeCandidateOwner": "frontend_adapter",
            "nativeSelectionOwner": "frontend_adapter",
            "modelRagMemoryOwner": "shared_backend",
            "supportedPrivacyDispositions": ["allowed", "sensitive", "unknown"],
        },
        "legacyCompatibility": {
            "suggest": ["/rime-suggest", "/api/rime-suggest"],
            "select": ["/rime-select", "/api/rime-select"],
        },
    }


def frontend_suggest_to_legacy(
    payload: Mapping[str, Any],
    *,
    default_project: str,
) -> dict[str, Any]:
    frontend = _mapping(payload.get("frontend"))
    session = _mapping(payload.get("session"))
    privacy = _mapping(payload.get("privacy"))
    input_payload = _mapping(payload.get("input"))
    context = _mapping(payload.get("context"))
    limits = _mapping(payload.get("limits"))
    flags = _mapping(payload.get("flags"))
    native_state = _mapping(payload.get("nativeState"))

    session_id, request_seq, input_generation = _required_session(session)
    disposition = _privacy_disposition(privacy)
    candidates = [
        _native_candidate_to_legacy(item, index=index)
        for index, item in enumerate(_mapping_items(payload.get("nativeCandidates")))
    ]
    legacy: dict[str, Any] = {
        "schemaVersion": _text(payload.get("schemaVersion")) or FRONTEND_SUGGEST_REQUEST_VERSION,
        "frontendBuild": _text(frontend.get("build") or frontend.get("id")),
        "frontendAdapterId": _text(frontend.get("id")),
        "frontendPlatform": _text(frontend.get("platform")),
        "inputFramework": _text(frontend.get("inputFramework")),
        "inputEngine": _text(frontend.get("inputEngine")),
        "sessionId": session_id,
        "requestSeq": request_seq,
        "inputGeneration": input_generation,
        "privacyDisposition": disposition,
        "privacyReason": _text(privacy.get("reason")),
        "sensitiveField": bool(privacy.get("sensitiveField", False)),
        "secureInput": bool(privacy.get("secureInput", False)),
        "rawInput": _text(input_payload.get("raw")),
        "preedit": _text(input_payload.get("preedit")),
        "commitTextPreview": _text(input_payload.get("commitPreview")),
        "committedContext": _text(input_payload.get("committedContext")),
        "project": _text(context.get("project")) or default_project,
        "app": _text(context.get("appId")),
        "frontAppBundleId": _text(context.get("appId")),
        "inputSourceId": _text(context.get("inputSourceId")),
        "idleMs": _integer(input_payload.get("idleMs"), default=0),
        "latencyBudgetMs": _integer(limits.get("latencyBudgetMs"), default=900),
        "maxVisibleCandidates": _integer(limits.get("maxVisibleCandidates"), default=8),
        "maxSideCandidates": _integer(limits.get("maxAssistantCandidates"), default=5),
        "forceSideCandidates": bool(flags.get("forceAssistantCandidates", False)),
        "predictionFirstMerge": bool(flags.get("predictionFirst", True)),
        "progressiveFollowUp": bool(flags.get("progressiveFollowUp", False)),
        "rimeContext": {
            "candidates": candidates,
            "highlightedIndex": _integer(native_state.get("highlightedIndex"), default=0),
            "page": _integer(native_state.get("page"), default=0),
            "isLastPage": bool(native_state.get("isLastPage", True)),
        },
    }
    foreground = context.get("foreground")
    if isinstance(foreground, Mapping):
        legacy["foregroundText"] = dict(foreground)
    return legacy


def frontend_suggest_from_legacy(
    request: Mapping[str, Any],
    response: Mapping[str, object],
) -> dict[str, object]:
    session = _mapping(request.get("session"))
    frontend = _mapping(request.get("frontend"))
    input_payload = _mapping(request.get("input"))
    assistant_overlay = _mapping(response.get("assistantOverlay"))
    session_id, request_seq, input_generation = _required_session(session)
    response_session_id = _text(response.get("sessionId")).strip() or session_id
    response_request_seq = _integer(response.get("requestSeq"), default=request_seq)
    if response_session_id != session_id or response_request_seq != request_seq:
        raise ValueError("legacy suggest response does not match the frontend session request")
    prediction_session = _mapping(response.get("predictionSession"))
    legacy_candidates = _mapping_items(response.get("displayCandidates"))
    snapshot_id = _candidate_snapshot_id(
        session_id=response_session_id,
        request_seq=response_request_seq,
        input_generation=input_generation,
        prediction_session=prediction_session,
        candidates=legacy_candidates,
    )
    snapshot_generation = _candidate_snapshot_generation(
        input_generation=input_generation,
        prediction_session=prediction_session,
        candidates=legacy_candidates,
    )
    candidates = [
        frontend_candidate_from_legacy(
            item,
            index=index,
            snapshot_id=snapshot_id,
            snapshot_generation=snapshot_generation,
            input_generation=input_generation,
        )
        for index, item in enumerate(legacy_candidates)
    ]
    return {
        "schemaVersion": FRONTEND_SUGGEST_RESPONSE_VERSION,
        "gatewayVersion": FRONTEND_GATEWAY_VERSION,
        "frontend": dict(frontend),
        "session": {
            "id": response_session_id,
            "requestSeq": response_request_seq,
            "inputGeneration": input_generation,
        },
        "input": {
            "raw": _text(response.get("rawInput")) or _text(input_payload.get("raw")),
            "preedit": _text(response.get("preedit")) or _text(input_payload.get("preedit")),
            "committedContext": _text(response.get("committedContext")),
            "semanticQuery": _text(response.get("semanticQuery")),
        },
        "candidates": candidates,
        "presentation": {
            "mode": _text(response.get("uiMode")),
            "visible": bool(assistant_overlay.get("visible", bool(candidates))),
            "dismissReason": _text(assistant_overlay.get("dismissReason")),
            "statusText": _text(assistant_overlay.get("statusText")),
            "keyPolicy": dict(_mapping(response.get("keyPolicy"))),
            "overlayConfig": dict(_mapping(response.get("overlayConfig"))),
            "animation": dict(_mapping(assistant_overlay.get("animation"))),
        },
        "selectionPolicy": {
            "actions": dict(_mapping(response.get("selectionActions"))),
            "merge": dict(_mapping(response.get("mergePolicy"))),
        },
        "predictionSession": dict(prediction_session),
        "progressive": dict(_mapping(response.get("progressive"))),
        "privacy": {
            "assessment": dict(_mapping(response.get("privacyAssessment"))),
            "storageReceipt": dict(_mapping(response.get("storageReceipt"))),
            "stored": bool(response.get("stored", False)),
            "noStore": bool(response.get("noStore", False)),
        },
        "diagnostics": {
            "backendContract": _text(response.get("schemaVersion")),
            "queryBasis": _text(response.get("queryBasis")),
            "triggerDecision": dict(_mapping(response.get("triggerDecision"))),
            "runtimeRevision": _integer(response.get("runtimeRevision"), default=0),
        },
    }


def frontend_selection_to_legacy(
    payload: Mapping[str, Any],
    *,
    default_project: str,
) -> dict[str, Any]:
    frontend = _mapping(payload.get("frontend"))
    session = _mapping(payload.get("session"))
    privacy = _mapping(payload.get("privacy"))
    context = _mapping(payload.get("context"))
    candidate = _mapping(payload.get("candidate"))
    if not candidate:
        raise ValueError("frontend selection candidate must be an object")
    if _text(candidate.get("origin")).strip().lower() == "native":
        raise ValueError("native candidate selection is owned by the frontend adapter")
    session_id, request_seq, input_generation = _required_session(session)
    snapshot_id, snapshot_generation = _required_candidate_snapshot(
        candidate,
        input_generation=input_generation,
    )
    for visible in _mapping_items(payload.get("visibleCandidates")):
        visible_snapshot_id, visible_snapshot_generation = _required_candidate_snapshot(
            visible,
            input_generation=input_generation,
        )
        if (visible_snapshot_id, visible_snapshot_generation) != (snapshot_id, snapshot_generation):
            raise ValueError("frontend selection visibleCandidates must match the selected candidate snapshot")
    return {
        "candidate": frontend_candidate_to_legacy(candidate),
        "shownCandidates": [frontend_candidate_to_legacy(item) for item in _mapping_items(payload.get("visibleCandidates"))],
        "query": _text(context.get("query")),
        "recentContext": _text(context.get("recentText")),
        "committedContext": _text(context.get("recentText")),
        "preedit": _text(context.get("preedit")),
        "project": _text(context.get("project")) or default_project,
        "app": _text(context.get("appId")),
        "frontAppBundleId": _text(context.get("appId")),
        "contextGroupId": _text(context.get("groupId")),
        "contextGroupLevel": _text(context.get("groupLevel")),
        "sessionId": session_id,
        "requestSeq": request_seq,
        "inputGeneration": input_generation,
        "snapshotId": snapshot_id,
        "snapshotGeneration": snapshot_generation,
        "frontendTransaction": {"inputGeneration": input_generation},
        "source": _text(frontend.get("id")) or "frontend_gateway",
        "providerName": _text(payload.get("providerName")) or "frontend-gateway",
        "privacyDisposition": _privacy_disposition(privacy),
        "privacyReason": _text(privacy.get("reason")),
        "sensitiveField": bool(privacy.get("sensitiveField", False)),
        "secureInput": bool(privacy.get("secureInput", False)),
        "dryRun": bool(payload.get("dryRun", False)),
    }


def frontend_selection_from_legacy(
    request: Mapping[str, Any],
    response: Mapping[str, object],
) -> dict[str, object]:
    session = _mapping(request.get("session"))
    candidate = _mapping(request.get("candidate"))
    session_id, request_seq, input_generation = _required_session(session)
    snapshot_id, snapshot_generation = _required_candidate_snapshot(
        candidate,
        input_generation=input_generation,
    )
    return {
        "schemaVersion": FRONTEND_SELECTION_RESPONSE_VERSION,
        "gatewayVersion": FRONTEND_GATEWAY_VERSION,
        "ok": bool(response.get("ok", False)),
        "session": {
            "id": session_id,
            "requestSeq": request_seq,
            "inputGeneration": input_generation,
        },
        "selectionReceipt": {
            "sessionId": session_id,
            "requestSeq": request_seq,
            "inputGeneration": input_generation,
            "snapshotId": snapshot_id,
            "snapshotGeneration": snapshot_generation,
            "candidateId": _text(candidate.get("id")),
            "requestConsistencyValidated": True,
            "runtimeFreshnessValidated": False,
        },
        "eventId": _text(response.get("eventId")),
        "origin": _origin_from_legacy(_text(response.get("sourceType"))),
        "insertText": _text(response.get("insertText")),
        "recordedActionCount": _integer(response.get("recordedActionCount"), default=0),
        "privacy": {
            "assessment": dict(_mapping(response.get("privacyAssessment"))),
            "storageReceipt": dict(_mapping(response.get("storageReceipt"))),
            "stored": bool(response.get("stored", False)),
            "noStore": bool(response.get("noStore", False)),
        },
        "backendContract": _text(response.get("schemaVersion")),
    }


def frontend_candidate_from_legacy(
    candidate: Mapping[str, Any],
    *,
    index: int = 0,
    snapshot_id: str,
    snapshot_generation: int,
    input_generation: int,
) -> dict[str, object]:
    source_type = _text(candidate.get("sourceType"))
    candidate_id = _text(
        candidate.get("candidateStableId")
        or candidate.get("suggestionId")
        or candidate.get("memoryId")
    ) or f"candidate:{index}"
    return {
        "id": candidate_id,
        "snapshotId": snapshot_id,
        "snapshotGeneration": snapshot_generation,
        "inputGeneration": input_generation,
        "label": _text(candidate.get("visibleLabel") or candidate.get("label")),
        "text": _text(candidate.get("text")),
        "insertText": _text(candidate.get("insertText") or candidate.get("text")),
        "origin": _origin_from_legacy(source_type),
        "provider": _text(candidate.get("displayLane") or candidate.get("comment")),
        "rank": _integer(candidate.get("selectionRank"), default=index + 1),
        "nativeIndex": candidate.get("rimeIndex") if isinstance(candidate.get("rimeIndex"), int) else None,
        "selectionAction": _text(candidate.get("selectionAction")),
        "layout": _text(candidate.get("displayLayout")),
        "lane": _text(candidate.get("displayLane")),
        "group": _text(candidate.get("group")),
        "badge": _text(candidate.get("sourceBadge") or candidate.get("badge")),
        "selectable": bool(candidate.get("isSelectable", True)),
        "status": bool(candidate.get("isStatus", False)),
        "suggestionId": _text(candidate.get("suggestionId")),
        "memoryId": _text(candidate.get("memoryId")),
        "sourceEventId": candidate.get("sourceEventId") if isinstance(candidate.get("sourceEventId"), int) else None,
        "metadata": dict(_mapping(candidate.get("metadata"))),
    }


def frontend_candidate_to_legacy(candidate: Mapping[str, Any]) -> dict[str, object]:
    origin = _text(candidate.get("origin"))
    rank = _integer(candidate.get("rank"), default=1)
    metadata = dict(_mapping(candidate.get("metadata")))
    metadata.update(
        {
            "snapshotId": _text(candidate.get("snapshotId")),
            "snapshotGeneration": _integer(candidate.get("snapshotGeneration"), default=0),
            "inputGeneration": _integer(candidate.get("inputGeneration"), default=0),
        }
    )
    return {
        "candidateStableId": _text(candidate.get("id")),
        "snapshotId": _text(candidate.get("snapshotId")),
        "snapshotGeneration": _integer(candidate.get("snapshotGeneration"), default=0),
        "inputGeneration": _integer(candidate.get("inputGeneration"), default=0),
        "label": _text(candidate.get("label")) or str(rank),
        "visibleLabel": _text(candidate.get("label")) or str(rank),
        "selectionKey": _text(candidate.get("label")) or str(rank),
        "selectionRank": rank,
        "text": _text(candidate.get("text")),
        "insertText": _text(candidate.get("insertText") or candidate.get("text")),
        "sourceType": _legacy_source_from_origin(origin),
        "selectionAction": _text(candidate.get("selectionAction")) or "commit_side_candidate",
        "sourceIndex": _integer(candidate.get("nativeIndex"), default=max(0, rank - 1)),
        "rimeIndex": candidate.get("nativeIndex") if isinstance(candidate.get("nativeIndex"), int) else None,
        "displayLayout": _text(candidate.get("layout")),
        "displayLane": _text(candidate.get("lane") or candidate.get("provider")),
        "group": _text(candidate.get("group")),
        "badge": _text(candidate.get("badge")),
        "suggestionId": _text(candidate.get("suggestionId")),
        "memoryId": _text(candidate.get("memoryId")),
        "sourceEventId": candidate.get("sourceEventId") if isinstance(candidate.get("sourceEventId"), int) else None,
        "metadata": metadata,
    }


def _required_session(session: Mapping[str, Any]) -> tuple[str, int, int]:
    session_id = _text(session.get("id")).strip()
    if not session_id:
        raise ValueError("frontend session.id must not be empty")
    request_seq = _required_non_negative_integer(session, "requestSeq", owner="frontend session")
    input_generation = _required_non_negative_integer(session, "inputGeneration", owner="frontend session")
    return session_id, request_seq, input_generation


def _required_candidate_snapshot(
    candidate: Mapping[str, Any],
    *,
    input_generation: int,
) -> tuple[str, int]:
    candidate_id = _text(candidate.get("id")).strip()
    if not candidate_id:
        raise ValueError("frontend selection candidate.id must not be empty")
    snapshot_id = _text(candidate.get("snapshotId")).strip()
    if not snapshot_id:
        raise ValueError("frontend selection candidate.snapshotId must not be empty")
    snapshot_generation = _required_non_negative_integer(
        candidate,
        "snapshotGeneration",
        owner="frontend selection candidate",
    )
    candidate_input_generation = _required_non_negative_integer(
        candidate,
        "inputGeneration",
        owner="frontend selection candidate",
    )
    if candidate_input_generation != input_generation:
        raise ValueError("frontend selection candidate inputGeneration does not match session")
    return snapshot_id, snapshot_generation


def _required_non_negative_integer(payload: Mapping[str, Any], key: str, *, owner: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner}.{key} must be a non-negative integer")
    return value


def _candidate_snapshot_id(
    *,
    session_id: str,
    request_seq: int,
    input_generation: int,
    prediction_session: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> str:
    prediction_snapshot_id = _text(
        prediction_session.get("snapshotId") or prediction_session.get("stableSnapshotId")
    ).strip()
    candidate_snapshot_ids = {
        _text(candidate.get("snapshotId")).strip()
        for candidate in candidates
        if _text(candidate.get("snapshotId")).strip()
    }
    if len(candidate_snapshot_ids) > 1:
        raise ValueError("legacy candidates contain mismatched snapshotId values")
    candidate_snapshot_id = next(iter(candidate_snapshot_ids), "")
    if prediction_snapshot_id and candidate_snapshot_id and prediction_snapshot_id != candidate_snapshot_id:
        raise ValueError("legacy prediction session and candidates contain mismatched snapshotId values")
    return prediction_snapshot_id or candidate_snapshot_id or (
        f"frontend:{session_id}:{request_seq}:{input_generation}"
    )


def _candidate_snapshot_generation(
    *,
    input_generation: int,
    prediction_session: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
) -> int:
    prediction_value = prediction_session.get("snapshotGeneration")
    prediction_generation = (
        prediction_value
        if isinstance(prediction_value, int) and not isinstance(prediction_value, bool) and prediction_value >= 0
        else None
    )
    candidate_generations = {
        value
        for candidate in candidates
        for value in (candidate.get("snapshotGeneration"),)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }
    if len(candidate_generations) > 1:
        raise ValueError("legacy candidates contain mismatched snapshotGeneration values")
    candidate_generation = next(iter(candidate_generations), None)
    if (
        prediction_generation is not None
        and candidate_generation is not None
        and prediction_generation != candidate_generation
    ):
        raise ValueError("legacy prediction session and candidates contain mismatched snapshotGeneration values")
    return prediction_generation if prediction_generation is not None else (
        candidate_generation if candidate_generation is not None else input_generation
    )


def _native_candidate_to_legacy(candidate: Mapping[str, Any], *, index: int) -> dict[str, object]:
    rank = _integer(candidate.get("rank"), default=index + 1)
    return {
        "label": _text(candidate.get("label")) or str(rank),
        "text": _text(candidate.get("text")),
        "comment": _text(candidate.get("annotation")),
        "index": _integer(candidate.get("nativeIndex"), default=index),
    }


def _privacy_disposition(privacy: Mapping[str, Any]) -> str:
    disposition = _text(privacy.get("disposition")).strip().lower() or "unknown"
    if disposition not in {"allowed", "sensitive", "unknown"}:
        raise ValueError("frontend privacy.disposition must be allowed, sensitive, or unknown")
    return disposition


def _origin_from_legacy(source_type: str) -> str:
    source_type = source_type.strip().lower()
    return {
        "rime": "native",
        "model": "model",
        "rag": "retrieval",
        "memory": "memory",
        "action": "action",
        "status": "status",
        "raw_english": "literal",
    }.get(source_type, "assistant")


def _legacy_source_from_origin(origin: str) -> str:
    origin = origin.strip().lower()
    return {
        "native": "rime",
        "model": "model",
        "retrieval": "rag",
        "memory": "memory",
        "action": "action",
        "status": "status",
        "literal": "raw_english",
    }.get(origin, "model")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text(value: object) -> str:
    return str(value or "")


def _integer(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
