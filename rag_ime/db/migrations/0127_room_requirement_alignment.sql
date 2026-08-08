CREATE TABLE IF NOT EXISTS room_v2_requirement_alignment_runs (
    root_id TEXT PRIMARY KEY REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    room_id TEXT NOT NULL,
    user_post_id TEXT NOT NULL,
    requirement_anchor_ref TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('aligning','execution_ready','executing','cancelled')),
    next_stage_ordinal INTEGER NOT NULL DEFAULT 0 CHECK(next_stage_ordinal >= 0),
    stage_count INTEGER NOT NULL CHECK(stage_count > 0),
    stages_json TEXT NOT NULL,
    execution_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_room_requirement_alignment_room
ON room_v2_requirement_alignment_runs(room_id, created_at_ms ASC, root_id ASC);

CREATE TABLE IF NOT EXISTS room_v2_requirement_alignment_receipts (
    receipt_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_v2_requirement_alignment_runs(root_id) ON DELETE CASCADE,
    stage_ordinal INTEGER NOT NULL CHECK(stage_ordinal >= 0),
    dispatch_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status = 'confirmed'),
    summary TEXT NOT NULL,
    post_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK(created_at_ms >= 0),
    UNIQUE(root_id, stage_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_room_requirement_alignment_receipts_root
ON room_v2_requirement_alignment_receipts(root_id, stage_ordinal ASC);

CREATE TRIGGER IF NOT EXISTS room_requirement_alignment_receipts_immutable_update
BEFORE UPDATE ON room_v2_requirement_alignment_receipts
BEGIN
    SELECT RAISE(ABORT, 'Room requirement alignment receipts are immutable');
END;
