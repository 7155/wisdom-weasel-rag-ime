CREATE TABLE sandbox_runs (
    sandbox_run_id TEXT PRIMARY KEY,
    app_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'cancelled')
    ),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);

CREATE INDEX idx_sandbox_runs_created
    ON sandbox_runs(created_at_ms DESC, sandbox_run_id DESC);
