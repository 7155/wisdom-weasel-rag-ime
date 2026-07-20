CREATE TABLE IF NOT EXISTS room_v2_capability_manifests (
    manifest_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL CHECK (length(binding_id) > 0),
    room_id TEXT NOT NULL CHECK (length(room_id) > 0),
    root_id TEXT NOT NULL CHECK (length(root_id) > 0),
    task_id TEXT NOT NULL DEFAULT '',
    dispatch_id TEXT NOT NULL CHECK (length(dispatch_id) > 0),
    generation INTEGER NOT NULL CHECK (generation >= 0),
    capability_revision TEXT NOT NULL CHECK (length(capability_revision) > 0),
    capability_epoch INTEGER NOT NULL CHECK (capability_epoch >= 0),
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(binding_id, root_id, dispatch_id, generation, capability_epoch, manifest_hash)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_capability_manifest_scope
ON room_v2_capability_manifests(
    binding_id, root_id, task_id, dispatch_id, generation, capability_epoch
);

CREATE TABLE IF NOT EXISTS room_v2_tool_disclosure_receipts (
    receipt_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL
        REFERENCES room_v2_capability_manifests(manifest_id) ON DELETE RESTRICT,
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
    receipt_kind TEXT NOT NULL CHECK (receipt_kind IN ('search', 'load')),
    query_text TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    schema_hash TEXT NOT NULL DEFAULT '',
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(manifest_id, receipt_kind, query_text, tool_name, payload_hash)
);

CREATE TABLE IF NOT EXISTS room_v2_tool_invocation_receipts (
    receipt_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL
        REFERENCES room_v2_capability_manifests(manifest_id) ON DELETE RESTRICT,
    manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
    load_receipt_id TEXT NOT NULL
        REFERENCES room_v2_tool_disclosure_receipts(receipt_id) ON DELETE RESTRICT,
    invocation_key TEXT NOT NULL,
    canonical_tool_name TEXT NOT NULL,
    original_tool_name TEXT NOT NULL,
    command_hash TEXT NOT NULL CHECK (length(command_hash) = 64),
    command_json TEXT NOT NULL,
    authorization_state TEXT NOT NULL CHECK (authorization_state = 'authorized'),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(manifest_id, invocation_key)
);
