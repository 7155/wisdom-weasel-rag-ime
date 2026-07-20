CREATE TABLE IF NOT EXISTS room_v2_dispatch_requirement_bindings (
    dispatch_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    anchor_refs_json TEXT NOT NULL,
    catalog_revision_id TEXT,
    proof_receipt_refs_json TEXT NOT NULL,
    observation_warnings_json TEXT NOT NULL,
    gate_observation_ref TEXT,
    state TEXT NOT NULL CHECK(state IN ('prepared', 'active', 'terminal')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(dispatch_id) REFERENCES room_kernel_dispatches(dispatch_id),
    FOREIGN KEY(root_id) REFERENCES room_kernel_roots(root_id),
    FOREIGN KEY(task_id) REFERENCES room_kernel_tasks(task_id),
    FOREIGN KEY(catalog_revision_id)
        REFERENCES room_v2_requirement_catalog_revisions(catalog_revision_id),
    FOREIGN KEY(gate_observation_ref)
        REFERENCES room_v2_delivery_gate_receipts(gate_receipt_id)
);

CREATE INDEX IF NOT EXISTS idx_room_v2_dispatch_requirement_root
ON room_v2_dispatch_requirement_bindings(root_id, state, dispatch_id);
