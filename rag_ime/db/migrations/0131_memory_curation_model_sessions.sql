CREATE TABLE memory_curation_model_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT UNIQUE
        REFERENCES agent_sessions(id) ON DELETE SET NULL,
    profile TEXT NOT NULL DEFAULT 'MEMORY_CURATION'
        CHECK (profile = 'MEMORY_CURATION'),
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    thinking_level TEXT NOT NULL CHECK (thinking_level = 'max'),
    frozen_input_sha256 TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared'
        CHECK (state IN (
            'prepared',
            'running',
            'resumable',
            'completed',
            'failed',
            'cancelled'
        )),
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER
);

CREATE INDEX idx_memory_curation_model_runs_state_recent
ON memory_curation_model_runs(state, updated_at_ms DESC);

CREATE TABLE memory_curation_model_requests (
    request_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL
        REFERENCES memory_curation_model_runs(run_id) ON DELETE RESTRICT,
    phase TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    input_sha256 TEXT NOT NULL,
    -- The database, not the Pi transcript, owns the exact frozen request.
    messages_json TEXT NOT NULL CHECK (json_valid(messages_json)),
    input_chars INTEGER NOT NULL CHECK (input_chars >= 1),
    state TEXT NOT NULL DEFAULT 'prepared'
        CHECK (state IN (
            'prepared',
            'running',
            'completed',
            'resumable',
            'failed',
            'cancelled'
        )),
    turn_id TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    output_text TEXT NOT NULL DEFAULT '',
    receipt_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(receipt_json)),
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    UNIQUE(run_id, phase, input_sha256),
    UNIQUE(run_id, ordinal)
);

CREATE INDEX idx_memory_curation_model_requests_run_state
ON memory_curation_model_requests(run_id, state, ordinal);
