CREATE TABLE IF NOT EXISTS memory_candidate_suppressions (
    id TEXT PRIMARY KEY,
    match_type TEXT NOT NULL,
    match_value TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 1.0,
    expires_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_suppressions_match
ON memory_candidate_suppressions(match_type, match_value);
