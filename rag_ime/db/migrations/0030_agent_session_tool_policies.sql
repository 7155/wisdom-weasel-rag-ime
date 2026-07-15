CREATE TABLE IF NOT EXISTS agent_session_tool_policies (
    session_id TEXT PRIMARY KEY REFERENCES agent_sessions(id) ON DELETE CASCADE,
    allowed_tools_json TEXT NOT NULL DEFAULT 'null',
    updated_at_ms INTEGER NOT NULL
);
