CREATE TABLE room_v2_root_profile_pins (
    root_id TEXT PRIMARY KEY REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    bundle_content_hash TEXT NOT NULL,
    definition_content_hash TEXT NOT NULL,
    pointer_revision INTEGER NOT NULL CHECK(pointer_revision >= 0),
    guard_epoch INTEGER NOT NULL CHECK(guard_epoch >= 0),
    compile_receipt_id TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    pinned_at_ms INTEGER NOT NULL
);

CREATE TABLE room_kernel_continuations (
    continuation_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES room_kernel_roots(root_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES room_kernel_tasks(task_id) ON DELETE CASCADE,
    parent_dispatch_id TEXT NOT NULL REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    child_dispatch_id TEXT REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE SET NULL,
    commit_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK(decision IN ('dispatch','wait','block','complete','post')),
    state TEXT NOT NULL CHECK(state IN ('applied','retry_required','blocked')),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE room_kernel_settle_guards (
    dispatch_id TEXT PRIMARY KEY REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN ('retry_required','blocked','resolved')),
    last_receipt_id TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_kernel_abort_scopes (
    dispatch_id TEXT PRIMARY KEY REFERENCES room_kernel_dispatches(dispatch_id) ON DELETE CASCADE,
    root_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('registered','cancelling','cancelled','unknown')),
    surfaces_json TEXT NOT NULL,
    cancel_receipt_json TEXT NOT NULL DEFAULT '{}',
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX idx_room_profile_pins_profile
ON room_v2_root_profile_pins(profile_id,bundle_content_hash);

CREATE INDEX idx_room_continuations_root
ON room_kernel_continuations(root_id,created_at_ms);
