from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping


PERSONAL_CURRENT_STATE_PROFILE_ID = "personal_current_state"
PERSONAL_CURRENT_STATE_PURPOSE_REVISION = 1
PERSONAL_CURRENT_STATE_SCHEMA_REVISION = "rag-ime.owner-memory-curation.v1"

_DEFAULT_PURPOSE = {
    "goal": [
        "maintain_current_user_facts",
        "maintain_stable_preferences",
        "provide_traceable_agent_context",
    ],
    "prioritize": [
        "explicit_user_statement",
        "applied_tool_receipt",
        "repeated_stable_behavior",
        "recent_current_state",
        "verified_capture_hint",
    ],
    "avoid": [
        "generic_knowledge",
        "one_off_chat",
        "model_self_loop",
        "unsupported_psychology",
        "historical_as_current",
        "workflow_prompt",
        "temporary_progress",
    ],
}


def personal_current_state_profile(
    conn: sqlite3.Connection | None = None,
) -> dict[str, object]:
    purpose: dict[str, object] = dict(_DEFAULT_PURPOSE)
    schema_revision = PERSONAL_CURRENT_STATE_SCHEMA_REVISION
    if conn is not None:
        row = conn.execute(
            """
            SELECT purpose_json, schema_revision
            FROM memory_purpose_profiles
            WHERE profile_id = ? AND purpose_revision = ? AND active = 1
            """,
            (
                PERSONAL_CURRENT_STATE_PROFILE_ID,
                PERSONAL_CURRENT_STATE_PURPOSE_REVISION,
            ),
        ).fetchone()
        if row is not None:
            try:
                stored = json.loads(str(row[0] or "{}"))
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, Mapping):
                purpose = dict(stored)
            schema_revision = str(row[1] or schema_revision)
    return {
        "profileId": PERSONAL_CURRENT_STATE_PROFILE_ID,
        "purposeRevision": PERSONAL_CURRENT_STATE_PURPOSE_REVISION,
        "schemaRevision": schema_revision,
        "profileRef": (
            f"{PERSONAL_CURRENT_STATE_PROFILE_ID}@"
            f"{PERSONAL_CURRENT_STATE_PURPOSE_REVISION}"
        ),
        **purpose,
    }


def purpose_audit_fields(
    profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    resolved = dict(profile or personal_current_state_profile())
    return {
        "purpose_profile_id": str(
            resolved.get("profileId") or PERSONAL_CURRENT_STATE_PROFILE_ID
        ),
        "purpose_revision": int(
            resolved.get("purposeRevision")
            or PERSONAL_CURRENT_STATE_PURPOSE_REVISION
        ),
        "schema_revision": str(
            resolved.get("schemaRevision")
            or PERSONAL_CURRENT_STATE_SCHEMA_REVISION
        ),
    }
