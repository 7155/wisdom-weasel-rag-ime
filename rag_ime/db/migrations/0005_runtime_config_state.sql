CREATE TABLE IF NOT EXISTS runtime_config_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    runtime_revision INTEGER NOT NULL,
    snapshot_hash TEXT NOT NULL,
    settings_revision TEXT NOT NULL,
    profile TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
