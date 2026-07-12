CREATE TABLE IF NOT EXISTS memory_group_overrides (
    context_group_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    color_token TEXT NOT NULL DEFAULT 'blue',
    updated_at_ms INTEGER NOT NULL
);
