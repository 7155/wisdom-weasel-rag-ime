CREATE TABLE IF NOT EXISTS room_v2_skill_capability_epochs (
    root_id TEXT PRIMARY KEY CHECK (length(root_id) > 0),
    capability_epoch INTEGER NOT NULL CHECK (capability_epoch >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
);

CREATE TABLE IF NOT EXISTS room_v2_skill_load_receipts (
    receipt_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    task_id TEXT NOT NULL CHECK (length(task_id) > 0),
    dispatch_id TEXT NOT NULL CHECK (length(dispatch_id) > 0),
    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
    skill_id TEXT NOT NULL CHECK (length(skill_id) > 0),
    skill_hash TEXT NOT NULL CHECK (length(skill_hash) = 64),
    hash_rule TEXT NOT NULL CHECK (hash_rule = 'sha256-skill-body-utf8-v1'),
    catalog_revision TEXT NOT NULL CHECK (length(catalog_revision) > 0),
    policy_id TEXT NOT NULL CHECK (length(policy_id) > 0),
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    load_reason TEXT NOT NULL
        CHECK (load_reason IN ('stage_required', 'model_selected', 'compaction_restore')),
    capability_epoch INTEGER NOT NULL CHECK (capability_epoch >= 0),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) > 0),
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
    source_receipt_id TEXT NOT NULL DEFAULT '',
    identity_hash TEXT NOT NULL CHECK (length(identity_hash) = 64),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    revoked_at_ms INTEGER,
    UNIQUE(root_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_skill_receipts_root_epoch
ON room_v2_skill_load_receipts(root_id, capability_epoch, state, created_at_ms);

CREATE INDEX IF NOT EXISTS idx_room_v2_skill_receipts_dispatch
ON room_v2_skill_load_receipts(dispatch_id, session_id, skill_id);
