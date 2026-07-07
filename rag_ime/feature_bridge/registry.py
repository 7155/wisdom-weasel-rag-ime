"""Machine-readable feature registry validation for real-IME bridge work."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ALLOWED_V1_STATUSES = frozenset(
    {
        "foreground_verified",
        "backend_only",
        "debug_preview",
        "offline_tool",
        "blocked_by_bug",
    }
)
REQUIRED_FEATURE_FIELDS = frozenset(
    {
        "featureId",
        "userValue",
        "currentStatus",
        "realImeTrigger",
        "sidecarEndpoint",
        "candidateSourceType",
        "keyPolicy",
        "dataSource",
        "foregroundTraceEvents",
        "acceptanceCommand",
        "failureFallback",
        "userVisibleBehavior",
        "tests",
        "v1Status",
    }
)


class FeatureRegistryError(ValueError):
    """Raised when the feature registry does not satisfy the bridge contract."""


def load_feature_registry(path: str | Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL)
    if not match:
        raise FeatureRegistryError("feature registry must contain a JSON code block")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise FeatureRegistryError(f"feature registry JSON is invalid: {exc}") from exc
    return validate_feature_registry(payload)


def validate_feature_registry(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise FeatureRegistryError("feature registry JSON must be a list")
    features: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise FeatureRegistryError(f"feature item {index} must be an object")
        feature_id = str(item.get("featureId") or "")
        if not feature_id:
            raise FeatureRegistryError(f"feature item {index} is missing featureId")
        if feature_id in seen_ids:
            raise FeatureRegistryError(f"duplicate featureId: {feature_id}")
        seen_ids.add(feature_id)
        missing = REQUIRED_FEATURE_FIELDS - set(item)
        if missing:
            raise FeatureRegistryError(f"{feature_id} missing fields: {', '.join(sorted(missing))}")
        status = str(item.get("v1Status") or "")
        if status not in ALLOWED_V1_STATUSES:
            raise FeatureRegistryError(f"{feature_id} has invalid v1Status: {status}")
        _require_non_empty_string(item, feature_id, "userValue")
        _require_non_empty_string(item, feature_id, "realImeTrigger")
        _require_non_empty_string(item, feature_id, "sidecarEndpoint")
        _require_non_empty_string(item, feature_id, "candidateSourceType")
        _require_non_empty_string(item, feature_id, "keyPolicy")
        _require_non_empty_string(item, feature_id, "dataSource")
        _require_non_empty_string(item, feature_id, "acceptanceCommand")
        _require_non_empty_string(item, feature_id, "failureFallback")
        _require_non_empty_string(item, feature_id, "userVisibleBehavior")
        _require_non_empty_list(item, feature_id, "foregroundTraceEvents")
        _require_non_empty_list(item, feature_id, "tests")
        if status == "foreground_verified":
            command = str(item.get("acceptanceCommand") or "")
            events = " ".join(str(event) for event in item.get("foregroundTraceEvents") or [])
            if "verify_squirrel_foreground_trace" not in command and "check_squirrel_soak_report" not in command:
                raise FeatureRegistryError(f"{feature_id} foreground_verified requires a foreground trace command")
            if "panel_display_candidates" not in events:
                raise FeatureRegistryError(f"{feature_id} foreground_verified requires panel_display_candidates")
        features.append(dict(item))
    return features


def _require_non_empty_string(item: dict[str, Any], feature_id: str, key: str) -> None:
    if not str(item.get(key) or "").strip():
        raise FeatureRegistryError(f"{feature_id} field {key} must be a non-empty string")


def _require_non_empty_list(item: dict[str, Any], feature_id: str, key: str) -> None:
    value = item.get(key)
    if not isinstance(value, list) or not value:
        raise FeatureRegistryError(f"{feature_id} field {key} must be a non-empty list")
