"""Bridge designed features back to the real Squirrel/Rime IME path."""

from .registry import (
    ALLOWED_V1_STATUSES,
    REQUIRED_FEATURE_FIELDS,
    FeatureRegistryError,
    load_feature_registry,
    validate_feature_registry,
)

__all__ = [
    "ALLOWED_V1_STATUSES",
    "REQUIRED_FEATURE_FIELDS",
    "FeatureRegistryError",
    "load_feature_registry",
    "validate_feature_registry",
]
