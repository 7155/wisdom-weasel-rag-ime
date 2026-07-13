CREATE TABLE IF NOT EXISTS planning_assistant_messages (
    message_id TEXT PRIMARY KEY,
    plan_date TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_planning_assistant_messages_day
ON planning_assistant_messages(plan_date DESC, project, created_at_ms ASC);
