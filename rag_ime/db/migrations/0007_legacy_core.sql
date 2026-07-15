CREATE TABLE IF NOT EXISTS input_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_ms INTEGER NOT NULL,
    source TEXT NOT NULL,
    committed_text TEXT NOT NULL,
    recent_context TEXT NOT NULL DEFAULT '',
    preedit TEXT NOT NULL DEFAULT '',
    schema_id TEXT NOT NULL DEFAULT 'default',
    app TEXT NOT NULL DEFAULT 'manual',
    project TEXT NOT NULL DEFAULT '',
    candidate_rank INTEGER,
    provider_name TEXT NOT NULL DEFAULT 'local',
    tags_json TEXT NOT NULL DEFAULT '[]',
    context_group_id TEXT NOT NULL DEFAULT '',
    context_group_level TEXT NOT NULL DEFAULT 'app'
);

CREATE TABLE IF NOT EXISTS memory_state (
    event_id INTEGER PRIMARY KEY,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    downranked INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(event_id) REFERENCES input_events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS phrase_stats (
    committed_text TEXT PRIMARY KEY,
    input_frequency INTEGER NOT NULL DEFAULT 0,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS phrase_project_stats (
    committed_text TEXT NOT NULL,
    project TEXT NOT NULL,
    input_frequency INTEGER NOT NULL DEFAULT 0,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    PRIMARY KEY(committed_text, project)
);

CREATE TABLE IF NOT EXISTS phrase_app_stats (
    committed_text TEXT NOT NULL,
    app TEXT NOT NULL,
    input_frequency INTEGER NOT NULL DEFAULT 0,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    PRIMARY KEY(committed_text, app)
);

CREATE TABLE IF NOT EXISTS memory_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_ms INTEGER NOT NULL,
    memory_id TEXT NOT NULL,
    event_id INTEGER,
    action_type TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    suggestion_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(event_id) REFERENCES input_events(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS rime_rank_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_ms INTEGER NOT NULL,
    preedit TEXT NOT NULL,
    rejected_text TEXT NOT NULL DEFAULT '',
    accepted_text TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    app TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    candidate_rank INTEGER,
    context_hash TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_rime_rank_feedback_lookup
ON rime_rank_feedback(project, preedit, accepted_text, rejected_text, action);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content_text,
    committed_text,
    recent_context,
    project,
    tags,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS memory_vectors (
    event_id INTEGER PRIMARY KEY,
    provider_fingerprint TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(event_id) REFERENCES input_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_vectors_provider
ON memory_vectors(provider_fingerprint);
