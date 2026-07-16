CREATE TABLE IF NOT EXISTS agent_context_traces (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'accepted', 'failed')),
    final_fingerprint TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_context_traces_session
ON agent_context_traces(session_id, created_at_ms DESC, trace_id DESC);

CREATE TABLE IF NOT EXISTS agent_context_trace_nodes (
    trace_id TEXT NOT NULL REFERENCES agent_context_traces(trace_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    stage TEXT NOT NULL,
    label TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    disposition TEXT NOT NULL
        CHECK (disposition IN ('included', 'omitted', 'redacted', 'failed')),
    parent_ids_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    char_count INTEGER NOT NULL DEFAULT 0 CHECK (char_count >= 0),
    token_estimate INTEGER NOT NULL DEFAULT 0 CHECK (token_estimate >= 0),
    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    fingerprint TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(trace_id, node_id),
    UNIQUE(trace_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_agent_context_trace_nodes_stage
ON agent_context_trace_nodes(trace_id, stage, ordinal);

CREATE TABLE IF NOT EXISTS agent_context_items (
    item_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    lane TEXT NOT NULL
        CHECK (lane IN ('result', 'status', 'notification', 'room', 'schedule', 'fact')),
    lifecycle TEXT NOT NULL
        CHECK (lifecycle IN ('once', 'turn', 'until_ack', 'persistent')),
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'delivered', 'consumed', 'acknowledged', 'expired')),
    dedupe_key TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    available_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER,
    delivered_turn_id TEXT NOT NULL DEFAULT '',
    delivered_at_ms INTEGER,
    acknowledged_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_context_items_materialize
ON agent_context_items(session_id, status, available_at_ms, created_at_ms);

CREATE INDEX IF NOT EXISTS idx_agent_context_items_source
ON agent_context_items(source_kind, source_id, created_at_ms DESC);
