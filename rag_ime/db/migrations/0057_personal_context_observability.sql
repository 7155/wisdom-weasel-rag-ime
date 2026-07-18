ALTER TABLE agent_runtime_events
ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS personal_context_draft_decisions (
    decision_id TEXT PRIMARY KEY,
    draft_kind TEXT NOT NULL
        CHECK (draft_kind IN (
            'user_memory',
            'role_book',
            'activity_timeline'
        )),
    draft_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    role_id TEXT NOT NULL DEFAULT '',
    role_version TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL
        CHECK (decision IN ('accepted', 'rejected', 'deferred')),
    decided_by TEXT NOT NULL,
    reason_sha256 TEXT NOT NULL
        CHECK (length(reason_sha256) = 64),
    created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_personal_context_draft_decisions_scope
ON personal_context_draft_decisions(
    project, role_id, draft_kind, created_at_ms DESC, decision_id DESC
);

CREATE INDEX IF NOT EXISTS idx_personal_context_draft_decisions_draft
ON personal_context_draft_decisions(draft_kind, draft_id, created_at_ms DESC);
