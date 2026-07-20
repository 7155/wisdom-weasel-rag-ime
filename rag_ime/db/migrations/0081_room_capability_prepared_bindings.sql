CREATE TABLE room_v2_capability_runtime_bindings_v2 (
    session_id TEXT NOT NULL,
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
    state TEXT NOT NULL CHECK(state IN ('prepared', 'active', 'revoked')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(manifest_id) REFERENCES room_v2_capability_manifests(manifest_id),
    PRIMARY KEY(session_id, manifest_id)
);

INSERT INTO room_v2_capability_runtime_bindings_v2(
    session_id, manifest_id, manifest_hash, prompt_compile_receipt_id,
    prompt_plan_hash, compiled_profile_id, compiled_profile_revision,
    compiled_profile_hash, room_binding_json, participant_binding_json,
    capability_epoch, state, created_at_ms, updated_at_ms
)
SELECT
    session_id, manifest_id, manifest_hash, prompt_compile_receipt_id,
    prompt_plan_hash, compiled_profile_id, compiled_profile_revision,
    compiled_profile_hash, room_binding_json, participant_binding_json,
    capability_epoch, state, created_at_ms, updated_at_ms
FROM room_v2_capability_runtime_bindings;

DROP TABLE room_v2_capability_runtime_bindings;
ALTER TABLE room_v2_capability_runtime_bindings_v2
RENAME TO room_v2_capability_runtime_bindings;

CREATE UNIQUE INDEX idx_room_v2_capability_one_live_session
ON room_v2_capability_runtime_bindings(session_id)
WHERE state IN ('prepared', 'active');
