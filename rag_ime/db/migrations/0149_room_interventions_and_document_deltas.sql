CREATE TABLE IF NOT EXISTS room_interventions (
    intervention_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    root_id TEXT NOT NULL
        REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    intervention_kind TEXT NOT NULL
        CHECK(intervention_kind IN (
            'correction','priority_change','pause','status_question'
        )),
    state TEXT NOT NULL
        CHECK(state IN (
            'accepted','pending_reconciliation','resolved','cancelled'
        )),
    post_id TEXT NOT NULL UNIQUE,
    requirement_anchor_id TEXT NOT NULL,
    requirement_catalog_revision_id TEXT,
    requires_plan_revision INTEGER NOT NULL DEFAULT 0
        CHECK(requires_plan_revision IN (0,1)),
    affected_task_ids_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_room_interventions_root_state
ON room_interventions(root_id, state, created_at_ms);

CREATE TABLE IF NOT EXISTS room_work_document_deltas (
    delta_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES work_documents(document_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL
        REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    delta_kind TEXT NOT NULL
        CHECK(delta_kind IN (
            'user_correction','progress','evidence','failure_recovery',
            'handoff','next_action','plan_revision'
        )),
    source_ref TEXT NOT NULL,
    content_bytes BLOB NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    materialized_at_ms INTEGER,
    UNIQUE(root_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_room_work_document_deltas_pending
ON room_work_document_deltas(root_id, sequence)
WHERE materialized_at_ms IS NULL;
