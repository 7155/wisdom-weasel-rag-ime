CREATE TABLE IF NOT EXISTS memory_tag_profiles (
    tag_id INTEGER PRIMARY KEY,
    color_token TEXT NOT NULL DEFAULT 'blue',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY(tag_id) REFERENCES memory_tags(id) ON DELETE CASCADE
);
