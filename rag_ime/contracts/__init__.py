"""Stable request/response contracts for the v1 foreground IME path."""

from .key_policy import (
    NUMBER_KEYS_PASS_THROUGH,
    NUMBER_KEYS_SELECT_RIME_CANDIDATE,
    OPTION_NUMBER_SELECT_PREDICTION_BY_ORDINAL,
    SELECTION_ACTION_COMMIT_SIDE_CANDIDATE,
    SELECTION_ACTION_SELECT_RIME_CANDIDATE,
    TAB_ACCEPT_TOP_PREDICTION,
    key_policy_for_prediction_session,
)
from .context_observability import (
    ACTIVE_RAG_ROUTE_STATUS_SCHEMA_VERSION,
    CONTEXT_INJECTION_TRACE_SCHEMA_VERSION,
    build_context_injection_trace,
    evidence_injection_diagnostics,
    text_fingerprint,
)
from .source import (
    SOURCE_BADGES,
    SOURCE_COLOR_TOKENS,
    SOURCE_MEMORY,
    SOURCE_MODEL,
    SOURCE_RAG,
    SOURCE_RAW_ENGLISH,
    SOURCE_RIME,
    SOURCE_STATUS,
    source_badge_for,
    source_color_token_for,
)
from .trace import (
    ACTIVE_RAG_TRACE_EVENT_NAMES,
    REQUIRED_TRACE_EVENT_NAMES,
    SOAK_REPORT_SCHEMA_VERSION,
    V1_FOREGROUND_METRIC_KEYS,
)

__all__ = [
    "ACTIVE_RAG_TRACE_EVENT_NAMES",
    "ACTIVE_RAG_ROUTE_STATUS_SCHEMA_VERSION",
    "CONTEXT_INJECTION_TRACE_SCHEMA_VERSION",
    "NUMBER_KEYS_PASS_THROUGH",
    "NUMBER_KEYS_SELECT_RIME_CANDIDATE",
    "OPTION_NUMBER_SELECT_PREDICTION_BY_ORDINAL",
    "REQUIRED_TRACE_EVENT_NAMES",
    "SELECTION_ACTION_COMMIT_SIDE_CANDIDATE",
    "SELECTION_ACTION_SELECT_RIME_CANDIDATE",
    "SOURCE_BADGES",
    "SOURCE_COLOR_TOKENS",
    "SOURCE_MEMORY",
    "SOURCE_MODEL",
    "SOURCE_RAG",
    "SOURCE_RAW_ENGLISH",
    "SOURCE_RIME",
    "SOURCE_STATUS",
    "SOAK_REPORT_SCHEMA_VERSION",
    "TAB_ACCEPT_TOP_PREDICTION",
    "V1_FOREGROUND_METRIC_KEYS",
    "build_context_injection_trace",
    "evidence_injection_diagnostics",
    "key_policy_for_prediction_session",
    "source_badge_for",
    "source_color_token_for",
    "text_fingerprint",
]
