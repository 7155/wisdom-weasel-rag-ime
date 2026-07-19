CREATE TABLE IF NOT EXISTS agent_lifecycle_hook_policies (
    event_type TEXT PRIMARY KEY CHECK (
        event_type IN (
            'session_start', 'turn_end', 'compaction',
            'project_complete', 'tool_failed', 'idle'
        )
    ),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    action TEXT NOT NULL CHECK (
        action IN ('audit_only', 'context_checkpoint', 'memory_review_suggestion')
    ),
    token_limit INTEGER NOT NULL CHECK (token_limit BETWEEN 0 AND 2048),
    cooldown_seconds INTEGER NOT NULL CHECK (cooldown_seconds BETWEEN 0 AND 86400),
    updated_at_ms INTEGER NOT NULL
);

INSERT OR IGNORE INTO agent_lifecycle_hook_policies(
    event_type, enabled, action, token_limit, cooldown_seconds, updated_at_ms
) VALUES
    ('session_start', 1, 'audit_only', 0, 0, 0),
    ('turn_end', 1, 'audit_only', 128, 0, 0),
    ('compaction', 1, 'context_checkpoint', 256, 60, 0),
    ('project_complete', 1, 'memory_review_suggestion', 256, 300, 0),
    ('tool_failed', 1, 'memory_review_suggestion', 192, 120, 0),
    ('idle', 1, 'memory_review_suggestion', 128, 900, 0);

CREATE TABLE IF NOT EXISTS agent_lifecycle_hook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (
        status IN ('recorded', 'suggested', 'skipped', 'disabled', 'cooldown')
    ),
    action TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    suggestion_json TEXT,
    occurred_at_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY(event_type) REFERENCES agent_lifecycle_hook_policies(event_type)
);

CREATE INDEX IF NOT EXISTS idx_agent_lifecycle_hook_events_recent
    ON agent_lifecycle_hook_events(created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_agent_lifecycle_hook_events_cooldown
    ON agent_lifecycle_hook_events(event_type, session_id, created_at_ms DESC);
