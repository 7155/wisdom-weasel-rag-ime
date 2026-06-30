from __future__ import annotations

from .models import InputSuggestion, MemoryAction, ModelPrediction


SCHEMA_VERSION = "rag-ime.suggestions.v1"
ACTION_SCHEMA_VERSION = "rag-ime.action.v1"


def suggestion_to_payload(suggestion: InputSuggestion) -> dict[str, object]:
    """Return the stable JSON shape consumed by native frontends."""

    metadata = dict(suggestion.metadata)
    return {
        "suggestionId": suggestion.suggestion_id,
        "surfaceText": suggestion.surface_text,
        "insertText": str(metadata.get("insert_text") or suggestion.surface_text),
        "suggestionType": suggestion.suggestion_type,
        "sourceEventId": suggestion.source_event_id,
        "memoryId": str(metadata.get("memory_id") or suggestion.suggestion_id),
        "evidencePreview": suggestion.evidence_preview,
        "expandedEvidence": suggestion.expanded_evidence,
        "confidence": suggestion.confidence,
        "actions": list(suggestion.actions),
        "metadata": metadata,
    }


def suggestions_response_payload(
    *,
    current_input: str,
    recent_context: str,
    project: str,
    suggestions: list[InputSuggestion],
    model_predictions: list[ModelPrediction] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "currentInput": current_input,
        "recentContext": recent_context,
        "project": project,
        "modelPredictions": [model_prediction_to_payload(item) for item in (model_predictions or [])],
        "suggestions": [suggestion_to_payload(item) for item in suggestions],
    }


def action_response_payload(action: MemoryAction) -> dict[str, object]:
    return {
        "schemaVersion": ACTION_SCHEMA_VERSION,
        "actionId": action.action_id,
        "createdAtMs": action.created_at_ms,
        "memoryId": action.memory_id,
        "actionType": action.action_type,
        "query": action.query,
        "suggestionId": action.suggestion_id,
        "sourceEventId": action.source_event_id,
        "metadata": action.metadata,
    }


def model_prediction_to_payload(prediction: ModelPrediction) -> dict[str, object]:
    return {
        "text": prediction.text,
        "rank": prediction.rank,
        "providerName": prediction.provider_name,
        "latencyMs": prediction.latency_ms,
        "confidence": prediction.confidence,
        "metadata": dict(prediction.metadata),
    }
