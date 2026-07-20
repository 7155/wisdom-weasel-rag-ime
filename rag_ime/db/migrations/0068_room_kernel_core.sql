CREATE TABLE IF NOT EXISTS room_kernel_roots (
    root_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    state TEXT NOT NULL,
    owner TEXT NOT NULL,
    requirement_anchor_ref TEXT NOT NULL,
    budget_remaining INTEGER NOT NULL CHECK (budget_remaining >= 0),
    budget_reserved INTEGER NOT NULL DEFAULT 0 CHECK (budget_reserved >= 0),
    max_hops INTEGER NOT NULL CHECK (max_hops >= 0),
    max_depth INTEGER NOT NULL CHECK (max_depth >= 0),
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    covered_criteria_json TEXT NOT NULL DEFAULT '[]',
    terminal_receipt_id TEXT,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_kernel_tasks (
    task_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    parent_task_id TEXT,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_kernel_commands (
    command_id TEXT PRIMARY KEY,
    root_id TEXT REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    command_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(room_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS room_kernel_compatibility_refs (
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    command_id TEXT NOT NULL REFERENCES room_kernel_commands(command_id) ON DELETE CASCADE,
    observed_at_ms INTEGER NOT NULL,
    PRIMARY KEY(source_kind, source_id)
);

CREATE TABLE IF NOT EXISTS room_kernel_dispatches (
    dispatch_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES room_kernel_tasks(task_id) ON DELETE CASCADE,
    parent_dispatch_id TEXT,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    hop_count INTEGER NOT NULL CHECK (hop_count >= 0),
    depth INTEGER NOT NULL CHECK (depth >= 0),
    budget_cost INTEGER NOT NULL CHECK (budget_cost >= 0),
    target_session_id TEXT NOT NULL,
    target_participant_id TEXT NOT NULL,
    trigger_id TEXT NOT NULL,
    intent_kind TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(root_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS room_kernel_commits (
    commit_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    dispatch_id TEXT NOT NULL UNIQUE REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_kernel_outbox (
    outbox_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    dispatch_id TEXT NOT NULL UNIQUE REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    state TEXT NOT NULL,
    shadow_only INTEGER NOT NULL DEFAULT 1 CHECK (shadow_only IN (0, 1)),
    available_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_kernel_leases (
    lease_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    dispatch_id TEXT NOT NULL UNIQUE REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    lease_token TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_kernel_receipts (
    receipt_id TEXT PRIMARY KEY,
    root_id TEXT,
    command_id TEXT,
    receipt_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS room_kernel_dead_letters (
    dead_letter_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    dispatch_id TEXT NOT NULL UNIQUE REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    reason_code TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_room_kernel_dispatch_state
ON room_kernel_dispatches(root_id, state, updated_at_ms);

CREATE INDEX IF NOT EXISTS idx_room_kernel_outbox_ready
ON room_kernel_outbox(state, shadow_only, available_at_ms);

CREATE INDEX IF NOT EXISTS idx_room_kernel_lease_expiry
ON room_kernel_leases(state, expires_at_ms);
