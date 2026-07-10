"""Management/runtime setting bridge descriptors."""

from __future__ import annotations

RUNTIME_CONFIG_ARTIFACTS = (
    "sidecar_settings_store",
    "memory_governance_settings",
    "model_profile_settings",
    "rime_or_squirrel_user_config",
)

REQUIRED_FOREGROUND_PROOF_EVENTS = (
    "assistant_overlay_candidate_visible",
    "source_badge_setting_applied",
    "key_policy_setting_applied",
)
