CREATE TABLE IF NOT EXISTS room_v2_capability_runtime_bindings (
    session_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    prompt_compile_receipt_id TEXT NOT NULL,
    prompt_plan_hash TEXT NOT NULL,
    compiled_profile_id TEXT NOT NULL,
    compiled_profile_revision TEXT NOT NULL,
    compiled_profile_hash TEXT NOT NULL,
    room_binding_json TEXT NOT NULL,
    participant_binding_json TEXT NOT NULL,
    capability_epoch INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active', 'revoked')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(manifest_id) REFERENCES room_v2_capability_manifests(manifest_id)
);

CREATE TABLE IF NOT EXISTS room_v2_tool_execution_receipts (
    execution_receipt_id TEXT PRIMARY KEY,
    invocation_receipt_id TEXT NOT NULL UNIQUE,
    kernel_receipt_id TEXT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('applied', 'rejected', 'cancelled', 'failed')),
    result_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY(invocation_receipt_id) REFERENCES room_v2_tool_invocation_receipts(receipt_id)
);
