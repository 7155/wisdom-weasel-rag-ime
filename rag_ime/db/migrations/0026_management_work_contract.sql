CREATE TABLE IF NOT EXISTS management_work_previews (
    preview_id TEXT PRIMARY KEY,
    preview_token_sha256 TEXT NOT NULL UNIQUE,
    path_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    expected_revision_json TEXT NOT NULL,
    required_confirm TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    consumed_at_ms INTEGER,
    receipt_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_management_work_previews_expiry
ON management_work_previews(status, expires_at_ms);

CREATE TABLE IF NOT EXISTS management_work_receipts (
    receipt_id TEXT PRIMARY KEY,
    path_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    applied_at_ms INTEGER NOT NULL,
    audit_id INTEGER,
    rollback_available INTEGER NOT NULL DEFAULT 0,
    rollback_token_sha256 TEXT NOT NULL DEFAULT '',
    rollback_path_id TEXT NOT NULL DEFAULT '',
    rollback_confirm TEXT NOT NULL DEFAULT '',
    rollback_authority_json TEXT NOT NULL DEFAULT '{}',
    rollback_data_json TEXT NOT NULL DEFAULT '{}',
    restart_components_json TEXT NOT NULL DEFAULT '[]',
    rolled_back_at_ms INTEGER,
    rollback_receipt_id TEXT,
    rollback_of_receipt_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_management_work_receipts_apply
ON management_work_receipts(path_id, applied_at_ms DESC);
