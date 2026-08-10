CREATE TABLE IF NOT EXISTS room_plan_revisions (
    plan_revision_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL
        REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision > 0),
    state TEXT NOT NULL
        CHECK(state IN ('proposed','active','superseded','cancelled')),
    requirement_catalog_revision_id TEXT NOT NULL,
    work_document_ref_json TEXT,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    activated_at_ms INTEGER,
    UNIQUE(root_id, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_room_plan_one_active
ON room_plan_revisions(root_id)
WHERE state='active';

CREATE INDEX IF NOT EXISTS idx_room_plan_root_revision
ON room_plan_revisions(root_id, revision DESC);
