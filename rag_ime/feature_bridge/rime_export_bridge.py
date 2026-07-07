"""Rime export bridge descriptors."""

from __future__ import annotations

RIME_EXPORT_ARTIFACTS = (
    "generated_user_dictionary",
    "custom_schema_patch",
    "rollback_snapshot",
)

REQUIRED_FOREGROUND_PROOF_EVENTS = (
    "rime_export_applied",
    "rime_deploy_observed",
    "rime_candidate_from_export_visible",
)

CANDIDATE_SOURCE_TYPE = "rime"
