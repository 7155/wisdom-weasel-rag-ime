CREATE TABLE input_capture_receipts (
    capture_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    channel TEXT NOT NULL CHECK (channel IN ('input_method', 'voice')),
    boundary_kind TEXT NOT NULL CHECK (boundary_kind IN (
        'host_return',
        'focus_change',
        'app_change',
        'deactivate',
        'voice_final'
    )),
    boundary_confidence TEXT NOT NULL CHECK (boundary_confidence IN ('strong', 'weak')),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    metadata_sha256 TEXT NOT NULL CHECK (length(metadata_sha256) = 64),
    input_event_id INTEGER REFERENCES input_events(id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN ('stored', 'no_store', 'quarantined')),
    reason_code TEXT NOT NULL,
    occurred_start_ms INTEGER NOT NULL CHECK (occurred_start_ms >= 0),
    occurred_end_ms INTEGER NOT NULL CHECK (occurred_end_ms >= occurred_start_ms),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(channel, transaction_id, sequence)
);

CREATE INDEX idx_input_capture_receipts_event
ON input_capture_receipts(input_event_id)
WHERE input_event_id IS NOT NULL;

CREATE INDEX idx_input_capture_receipts_transaction
ON input_capture_receipts(channel, transaction_id, sequence, created_at_ms);
