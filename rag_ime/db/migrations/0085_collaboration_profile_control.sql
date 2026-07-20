CREATE TABLE IF NOT EXISTS collaboration_profile_guards (
    profile_id TEXT PRIMARY KEY,
    guard_epoch INTEGER NOT NULL CHECK(guard_epoch >= 0),
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS collaboration_profile_command_receipts (
    receipt_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    command_hash TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'inspect', 'validate', 'compile', 'dry_run', 'stage',
        'activate', 'rollback', 'revoke'
    )),
    profile_id TEXT,
    route_hash TEXT NOT NULL,
    guard_epoch INTEGER NOT NULL CHECK(guard_epoch >= 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_collaboration_profile_command_recent
ON collaboration_profile_command_receipts(profile_id, created_at_ms DESC);

ALTER TABLE room_v2_guard_execution_bindings ADD COLUMN guard_config_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_guard_execution_bindings ADD COLUMN guard_candidate_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE room_v2_guard_execution_bindings ADD COLUMN activation_receipt_id TEXT NOT NULL DEFAULT '';

CREATE TABLE room_v2_incident_ingest_receipts (
    kernel_receipt_id TEXT PRIMARY KEY REFERENCES room_kernel_receipts(receipt_id),
    incident_id TEXT,
    occurrence_id TEXT,
    disposition TEXT NOT NULL CHECK(disposition IN ('recorded','ignored','no_binding')),
    processed_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_reflection_jobs (
    job_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL UNIQUE REFERENCES room_v2_incidents(incident_id),
    state TEXT NOT NULL CHECK(state IN ('pending','retry_wait','completed','dead_letter')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),
    available_at_ms INTEGER NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    lesson_candidate_id TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_guard_materialization_outbox (
    outbox_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    guard_candidate_id TEXT,
    guard_epoch INTEGER NOT NULL,
    candidate_hash TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('materialize','cleanup')),
    state TEXT NOT NULL CHECK(state IN ('pending','applied','dead_letter')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(scope_key, guard_epoch, action)
);

CREATE TABLE room_v2_guard_materializations (
    scope_key TEXT NOT NULL,
    surface TEXT NOT NULL CHECK(surface IN ('prompt','skill','tool','test_fixture')),
    guard_candidate_id TEXT NOT NULL,
    guard_epoch INTEGER NOT NULL,
    candidate_hash TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','tombstoned')),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(scope_key, surface)
);

CREATE TABLE room_v2_managed_cancel_outbox (
    cancel_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('guard_rollback','profile_rollback','profile_revoke')),
    source_receipt_id TEXT NOT NULL,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id),
    dispatch_id TEXT,
    state TEXT NOT NULL CHECK(state IN ('pending','processing','applied','unknown')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_until_ms INTEGER NOT NULL DEFAULT 0,
    kernel_receipt_id TEXT,
    runtime_receipts_json TEXT NOT NULL DEFAULT '[]',
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(source_kind, source_receipt_id, root_id, dispatch_id)
);

CREATE INDEX idx_room_v2_reflection_ready
ON room_v2_reflection_jobs(state, available_at_ms, created_at_ms);

CREATE INDEX idx_room_v2_guard_materialization_ready
ON room_v2_guard_materialization_outbox(state, created_at_ms);

CREATE INDEX idx_room_v2_managed_cancel_ready
ON room_v2_managed_cancel_outbox(state, created_at_ms);
