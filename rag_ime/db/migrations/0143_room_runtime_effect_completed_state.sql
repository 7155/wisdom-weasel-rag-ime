ALTER TABLE room_kernel_runtime_effects
RENAME TO room_kernel_runtime_effects_v142;

CREATE TABLE room_kernel_runtime_effects (
    dispatch_id TEXT PRIMARY KEY
        REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    dispatch_generation INTEGER NOT NULL,
    state TEXT NOT NULL
        CHECK(state IN (
            'intent','accepted','unknown','cancelled','failed','completed'
        )),
    runtime_receipt_json TEXT NOT NULL DEFAULT '{}',
    updated_at_ms INTEGER NOT NULL
);

INSERT INTO room_kernel_runtime_effects(
    dispatch_id, root_id, session_id, dispatch_generation,
    state, runtime_receipt_json, updated_at_ms
)
SELECT
    dispatch_id, root_id, session_id, dispatch_generation,
    state, runtime_receipt_json, updated_at_ms
FROM room_kernel_runtime_effects_v142;

DROP TABLE room_kernel_runtime_effects_v142;

ALTER TABLE room_kernel_abort_scopes
RENAME TO room_kernel_abort_scopes_v142;

CREATE TABLE room_kernel_abort_scopes (
    dispatch_id TEXT PRIMARY KEY
        REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    state TEXT NOT NULL
        CHECK(state IN (
            'registered','cancelling','cancelled','unknown','failed','completed'
        )),
    surfaces_json TEXT NOT NULL,
    cancel_receipt_json TEXT NOT NULL DEFAULT '{}',
    updated_at_ms INTEGER NOT NULL
);

INSERT INTO room_kernel_abort_scopes(
    dispatch_id, root_id, session_id, generation,
    state, surfaces_json, cancel_receipt_json, updated_at_ms
)
SELECT
    dispatch_id, root_id, session_id, generation,
    state, surfaces_json, cancel_receipt_json, updated_at_ms
FROM room_kernel_abort_scopes_v142;

DROP TABLE room_kernel_abort_scopes_v142;
