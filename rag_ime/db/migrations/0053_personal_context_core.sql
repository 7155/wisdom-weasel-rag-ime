CREATE TABLE IF NOT EXISTS agent_memory_evidence (
    evidence_id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    role_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL
        CHECK (source_kind IN (
            'user_message',
            'assistant_message',
            'tool_receipt',
            'session_digest',
            'room_event',
            'work_receipt'
        )),
    source_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    privacy_class TEXT NOT NULL DEFAULT 'local'
        CHECK (privacy_class IN ('local', 'private')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'tombstoned')),
    occurred_at_ms INTEGER NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    UNIQUE(project, source_kind, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_evidence_role_recent
ON agent_memory_evidence(project, role_id, status, occurred_at_ms DESC, evidence_id DESC);

CREATE INDEX IF NOT EXISTS idx_agent_memory_evidence_session_recent
ON agent_memory_evidence(session_id, status, occurred_at_ms DESC, evidence_id DESC);

CREATE TABLE IF NOT EXISTS personal_context_consolidation_runs (
    run_id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    start_cursor_at_ms INTEGER NOT NULL DEFAULT 0,
    start_cursor_evidence_id TEXT NOT NULL DEFAULT '',
    end_cursor_at_ms INTEGER NOT NULL DEFAULT 0,
    end_cursor_evidence_id TEXT NOT NULL DEFAULT '',
    window_start_ms INTEGER NOT NULL,
    window_end_ms INTEGER NOT NULL,
    source_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    output_json TEXT NOT NULL DEFAULT '{}',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_text TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER,
    completed_at_ms INTEGER,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(project, role_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_personal_context_runs_role_recent
ON personal_context_consolidation_runs(project, role_id, created_at_ms DESC, run_id DESC);

CREATE INDEX IF NOT EXISTS idx_personal_context_runs_recovery
ON personal_context_consolidation_runs(
    project, role_id, status, start_cursor_at_ms, start_cursor_evidence_id, updated_at_ms
);

CREATE TABLE IF NOT EXISTS personal_context_consolidation_cursors (
    project TEXT NOT NULL DEFAULT '',
    role_id TEXT NOT NULL,
    last_evidence_at_ms INTEGER NOT NULL DEFAULT 0,
    last_evidence_id TEXT NOT NULL DEFAULT '',
    last_successful_run_id TEXT NOT NULL DEFAULT '',
    last_succeeded_at_ms INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(project, role_id)
);
