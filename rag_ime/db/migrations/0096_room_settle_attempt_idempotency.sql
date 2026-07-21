CREATE TABLE room_kernel_settle_attempt_receipts (
    settle_receipt_id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL
        REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    kernel_receipt_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX idx_room_settle_attempt_dispatch
ON room_kernel_settle_attempt_receipts(dispatch_id, created_at_ms);
