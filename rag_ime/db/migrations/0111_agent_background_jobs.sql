CREATE TABLE agent_background_jobs (
    job_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'queued',
            'running',
            'cancelling',
            'completed',
            'failed',
            'cancelled',
            'orphaned'
        )
    ),
    command TEXT NOT NULL,
    command_sha256 TEXT NOT NULL CHECK (length(command_sha256) = 64),
    cwd TEXT NOT NULL,
    network_allowed INTEGER NOT NULL DEFAULT 0 CHECK (network_allowed IN (0, 1)),
    max_run_seconds INTEGER NOT NULL CHECK (max_run_seconds BETWEEN 1 AND 86400),
    pid INTEGER,
    process_group_id INTEGER,
    log_path TEXT NOT NULL,
    output_bytes INTEGER NOT NULL DEFAULT 0 CHECK (output_bytes >= 0),
    log_start_cursor INTEGER NOT NULL DEFAULT 0 CHECK (log_start_cursor >= 0),
    log_truncated INTEGER NOT NULL DEFAULT 0 CHECK (log_truncated IN (0, 1)),
    approval_id TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER,
    cancel_requested_at_ms INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_agent_background_jobs_session_updated
ON agent_background_jobs(session_id, updated_at_ms DESC);

CREATE INDEX idx_agent_background_jobs_live
ON agent_background_jobs(session_id, status)
WHERE status IN ('queued', 'running', 'cancelling');
