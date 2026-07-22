CREATE TABLE IF NOT EXISTS memory_capture_hints (
    hint_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES agent_memory_sources(source_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('preference', 'fact', 'decision', 'correction', 'pitfall')),
    normalized_claim TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('user', 'project')),
    reason TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_ids_json)),
    captured_by_session_id TEXT NOT NULL DEFAULT '',
    captured_by_role_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'consumed', 'superseded')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(source_id, kind, normalized_claim)
);

CREATE INDEX IF NOT EXISTS idx_memory_capture_hints_source_status
ON memory_capture_hints(source_id, status, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS memory_purpose_profiles (
    profile_id TEXT NOT NULL,
    purpose_revision INTEGER NOT NULL CHECK (purpose_revision >= 1),
    schema_revision TEXT NOT NULL,
    purpose_json TEXT NOT NULL CHECK (json_valid(purpose_json)),
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(profile_id, purpose_revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_purpose_profiles_active
ON memory_purpose_profiles(profile_id)
WHERE active = 1;

INSERT OR IGNORE INTO memory_purpose_profiles(
    profile_id, purpose_revision, schema_revision, purpose_json,
    active, created_at_ms, updated_at_ms
)
VALUES (
    'personal_current_state',
    1,
    'rag-ime.owner-memory-curation.v1',
    '{"goal":["maintain_current_user_facts","maintain_stable_preferences","provide_traceable_agent_context"],"prioritize":["explicit_user_statement","applied_tool_receipt","repeated_stable_behavior","recent_current_state","verified_capture_hint"],"avoid":["generic_knowledge","one_off_chat","model_self_loop","unsupported_psychology","historical_as_current","workflow_prompt","temporary_progress"]}',
    1,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000
);
