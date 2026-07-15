-- Canonical feedback schema. The Python hook rebuilds legacy variants before
-- this idempotent definition is applied.
CREATE TABLE IF NOT EXISTS memory_feedback_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT,
    candidate_text TEXT NOT NULL DEFAULT '',
    candidate_source TEXT NOT NULL DEFAULT 'unknown',
    action TEXT NOT NULL,
    context_hash TEXT,
    front_app_bundle_id TEXT,
    raw_input TEXT,
    preedit TEXT,
    committed_tail TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_feedback_context
ON memory_feedback_events(context_hash, created_at_ms);
