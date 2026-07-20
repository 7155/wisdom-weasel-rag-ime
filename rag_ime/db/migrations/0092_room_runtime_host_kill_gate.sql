CREATE TABLE room_v2_runtime_host_processes (
    host_identity TEXT PRIMARY KEY,
    owner_instance_id TEXT NOT NULL,
    pid INTEGER NOT NULL CHECK(pid > 0),
    process_group_id INTEGER NOT NULL CHECK(process_group_id > 0),
    job_identity TEXT NOT NULL,
    process_birth_token TEXT NOT NULL,
    executable_ref TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','terminated','unknown')),
    registered_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_room_runtime_host_live_job
ON room_v2_runtime_host_processes(job_identity)
WHERE state = 'running';

CREATE TABLE room_v2_runtime_host_kill_receipts (
    kill_receipt_id TEXT PRIMARY KEY,
    host_identity TEXT NOT NULL REFERENCES room_v2_runtime_host_processes(host_identity),
    request_kind TEXT NOT NULL CHECK(request_kind IN ('cancel_timeout','admin_panic','orphan_reconcile')),
    requested_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('requested','acknowledged','terminated','unknown')),
    pending_targets_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT NOT NULL DEFAULT '',
    requested_at_ms INTEGER NOT NULL,
    acknowledged_at_ms INTEGER NOT NULL DEFAULT 0,
    terminated_at_ms INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX idx_room_runtime_host_kill_pending
ON room_v2_runtime_host_kill_receipts(state,updated_at_ms);

CREATE TABLE room_v2_runtime_cancel_surface_receipts (
    cancel_id TEXT NOT NULL REFERENCES room_kernel_cancel_outbox(cancel_id) ON DELETE CASCADE,
    surface TEXT NOT NULL CHECK(surface IN ('provider','tool','exec','retry','compaction','branch_summary','timer','continuation','session')),
    state TEXT NOT NULL CHECK(state IN ('requested','acknowledged','terminated','unknown')),
    target_ref TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(cancel_id,surface)
);

CREATE INDEX idx_room_runtime_cancel_surface_state
ON room_v2_runtime_cancel_surface_receipts(state,updated_at_ms);
