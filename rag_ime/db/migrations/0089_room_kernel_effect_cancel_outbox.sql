CREATE TABLE room_kernel_runtime_effects (
    dispatch_id TEXT PRIMARY KEY REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    dispatch_generation INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('intent','accepted','unknown','cancelled')),
    runtime_receipt_json TEXT NOT NULL DEFAULT '{}',
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_kernel_cancel_outbox (
    cancel_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    terminalize_root INTEGER NOT NULL DEFAULT 0 CHECK(terminalize_root IN (0,1)),
    state TEXT NOT NULL CHECK(state IN ('pending','leased','retry_wait','applied','dead_letter')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at_ms INTEGER NOT NULL,
    lease_until_ms INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    runtime_receipt_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    UNIQUE(root_id,dispatch_id,generation)
);

CREATE INDEX idx_room_kernel_cancel_ready
ON room_kernel_cancel_outbox(state,available_at_ms,created_at_ms);
