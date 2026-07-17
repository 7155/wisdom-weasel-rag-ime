CREATE TABLE IF NOT EXISTS agent_role_books (
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    mission TEXT NOT NULL DEFAULT '',
    base_persona_version TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(role_id, role_version)
);

CREATE TABLE IF NOT EXISTS agent_role_book_revisions (
    revision_id TEXT PRIMARY KEY,
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    status TEXT NOT NULL
        CHECK (status IN ('draft', 'active', 'superseded', 'rolled_back')),
    content_json TEXT NOT NULL,
    source_revision_id TEXT NOT NULL DEFAULT '',
    change_summary TEXT NOT NULL DEFAULT '',
    proposed_by TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    activated_at_ms INTEGER,
    superseded_at_ms INTEGER,
    rolled_back_at_ms INTEGER,
    FOREIGN KEY(role_id, role_version)
        REFERENCES agent_role_books(role_id, role_version)
        ON DELETE CASCADE,
    UNIQUE(role_id, role_version, revision_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_role_book_one_active
ON agent_role_book_revisions(role_id, role_version)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_agent_role_book_revisions_recent
ON agent_role_book_revisions(role_id, role_version, revision_number DESC);

CREATE TABLE IF NOT EXISTS agent_role_book_activation_events (
    event_id TEXT PRIMARY KEY,
    role_id TEXT NOT NULL,
    role_version TEXT NOT NULL,
    from_revision_id TEXT NOT NULL DEFAULT '',
    to_revision_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('activate', 'rollback')),
    actor TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY(role_id, role_version)
        REFERENCES agent_role_books(role_id, role_version)
        ON DELETE CASCADE,
    FOREIGN KEY(to_revision_id)
        REFERENCES agent_role_book_revisions(revision_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_role_book_activation_events_recent
ON agent_role_book_activation_events(role_id, role_version, created_at_ms DESC);

ALTER TABLE agent_sessions
ADD COLUMN role_book_revision_id TEXT NOT NULL DEFAULT '';
