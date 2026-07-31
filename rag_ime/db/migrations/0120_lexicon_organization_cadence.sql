CREATE TABLE IF NOT EXISTS lexicon_organization_runs (
    run_id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    filtered_entry_count INTEGER NOT NULL DEFAULT 0,
    review_token_sha256 TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    error_text TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_lexicon_organization_runs_project_time
ON lexicon_organization_runs(project, started_at_ms DESC);
