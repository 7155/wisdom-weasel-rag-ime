-- Keep the Gateway worker process-owned, but retain its admission and result
-- receipt so a Trace handoff can recover after a Gateway restart.
CREATE TABLE IF NOT EXISTS memory_maintenance_jobs (
    job_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    progress_json TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_maintenance_jobs_updated
    ON memory_maintenance_jobs(updated_at_ms DESC);
