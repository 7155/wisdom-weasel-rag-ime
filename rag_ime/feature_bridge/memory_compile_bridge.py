"""Offline memory cleanup bridge descriptors."""

from __future__ import annotations

OFFLINE_CLEANUP_PROVIDERS = (
    "deepseek-v4",
)

DOWNSTREAM_SOURCE_TYPES = (
    "memory",
    "rag",
)

CURATED_MEMORY_REQUIRED_SIGNALS = (
    "curated",
    "accepted",
    "durable",
    "project",
    "high_confidence",
)

FORBIDDEN_REALTIME_PROVIDER_HINTS = (
    "remote typing inference",
    "deepseek-v4 realtime prediction",
)
