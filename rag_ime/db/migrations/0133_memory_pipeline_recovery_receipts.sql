CREATE TABLE memory_pipeline_recovery_receipts (
    receipt_id TEXT PRIMARY KEY,
    recovery_key_sha256 TEXT NOT NULL UNIQUE CHECK (length(recovery_key_sha256) = 64),
    input_event_max_id INTEGER NOT NULL CHECK (input_event_max_id >= 0),
    input_event_prefix_sha256 TEXT NOT NULL CHECK (length(input_event_prefix_sha256) = 64),
    backup_source_rows_sha256 TEXT NOT NULL CHECK (length(backup_source_rows_sha256) = 64),
    backup_audit_rows_sha256 TEXT NOT NULL CHECK (length(backup_audit_rows_sha256) = 64),
    recovered_source_rows INTEGER NOT NULL CHECK (recovered_source_rows >= 0),
    recovered_audit_rows INTEGER NOT NULL CHECK (recovered_audit_rows >= 0),
    recovered_hint_rows INTEGER NOT NULL CHECK (recovered_hint_rows >= 0),
    canonical_evidence_rows INTEGER NOT NULL CHECK (canonical_evidence_rows >= 0),
    payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    status TEXT NOT NULL CHECK (status IN ('verified', 'rolled_back')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    verified_at_ms INTEGER NOT NULL CHECK (verified_at_ms >= created_at_ms),
    rolled_back_at_ms INTEGER
);

CREATE INDEX idx_memory_pipeline_recovery_receipts_recent
ON memory_pipeline_recovery_receipts(status, verified_at_ms DESC, receipt_id DESC);
