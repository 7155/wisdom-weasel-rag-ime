-- Persist weekly global Memory catalog consolidation admission and result state.
-- Every state transition appends a receipt; existing tables remain untouched.
CREATE TABLE IF NOT EXISTS memory_catalog_consolidation_receipts (
    receipt_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    project TEXT NOT NULL,
    state TEXT NOT NULL,
    last_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    last_completion_at_ms INTEGER NOT NULL DEFAULT 0,
    next_due_at_ms INTEGER NOT NULL DEFAULT 0,
    catalog_digest TEXT NOT NULL DEFAULT '',
    curation_run_id TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_catalog_consolidation_project_updated
    ON memory_catalog_consolidation_receipts(project, updated_at_ms DESC, receipt_sequence DESC);
