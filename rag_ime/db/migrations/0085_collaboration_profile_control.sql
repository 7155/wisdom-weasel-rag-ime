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
