CREATE TABLE room_workspace_root_baselines (
    root_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    base_root TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(root_id, repository_id)
);

CREATE TABLE room_workspace_bindings (
    binding_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL DEFAULT '',
    root_id TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    work_item_id TEXT NOT NULL DEFAULT '',
    dispatch_id TEXT NOT NULL DEFAULT '',
    requirement_revision TEXT NOT NULL DEFAULT '',
    acceptance_aliases_json TEXT NOT NULL DEFAULT '[]',
    participant_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    repository_id TEXT NOT NULL DEFAULT '',
    base_root TEXT NOT NULL DEFAULT '',
    base_commit TEXT NOT NULL DEFAULT '',
    workspace_root TEXT NOT NULL,
    workspace_policy TEXT NOT NULL,
    restore_policy_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL,
    attention_required INTEGER NOT NULL DEFAULT 0 CHECK (attention_required IN (0, 1)),
    current_owner_participant_id TEXT NOT NULL DEFAULT '',
    current_owner_session_id TEXT NOT NULL DEFAULT '',
    delivery_revision TEXT NOT NULL DEFAULT '',
    delivery_head TEXT NOT NULL DEFAULT '',
    delivery_snapshot_sha256 TEXT NOT NULL DEFAULT '',
    integration_ref TEXT NOT NULL DEFAULT '',
    integration_patch_sha256 TEXT NOT NULL DEFAULT '',
    integrated_revision TEXT NOT NULL DEFAULT '',
    integrated_snapshot_sha256 TEXT NOT NULL DEFAULT '',
    terminal_reason TEXT NOT NULL DEFAULT '',
    cleanup_policy TEXT NOT NULL DEFAULT 'after_integrated_receipt',
    cleanup_state TEXT NOT NULL DEFAULT 'not_authorized',
    last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_room_workspace_binding_task
ON room_workspace_bindings(root_id, task_id)
WHERE root_id <> '' AND task_id <> '';

CREATE UNIQUE INDEX idx_room_workspace_binding_path
ON room_workspace_bindings(workspace_root);

CREATE INDEX idx_room_workspace_binding_attention
ON room_workspace_bindings(attention_required, updated_at_ms);

CREATE INDEX idx_room_workspace_binding_root
ON room_workspace_bindings(root_id, updated_at_ms);

CREATE TABLE room_workspace_events (
    event_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_kind TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    actor_ref TEXT NOT NULL DEFAULT '',
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(binding_id, sequence),
    UNIQUE(binding_id, idempotency_key)
);

CREATE INDEX idx_room_workspace_event_binding
ON room_workspace_events(binding_id, sequence);

CREATE TABLE room_workspace_integration_leases (
    root_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(root_id, repository_id)
);
