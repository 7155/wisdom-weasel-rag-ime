CREATE TABLE IF NOT EXISTS agent_runtime_bindings (
    session_id TEXT PRIMARY KEY REFERENCES agent_sessions(id) ON DELETE CASCADE,
    driver_id TEXT NOT NULL,
    runtime_kind TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    transcript_ref TEXT NOT NULL DEFAULT '',
    branch_anchor TEXT NOT NULL DEFAULT '',
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
    binding_state TEXT NOT NULL CHECK (binding_state IN ('prepared', 'active', 'stale')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(driver_id, external_session_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_bindings_driver_recent
ON agent_runtime_bindings(driver_id, binding_state, updated_at_ms DESC);

INSERT OR IGNORE INTO agent_runtime_bindings(
    session_id, driver_id, runtime_kind, external_session_id,
    transcript_ref, branch_anchor, generation, binding_state,
    metadata_json, created_at_ms, updated_at_ms
)
SELECT
    id, 'managed-pi', 'pi_rpc', pi_session_id,
    session_file, '', 1,
    CASE WHEN status IN ('active', 'busy') THEN 'active' ELSE 'prepared' END,
    '{}', created_at_ms, updated_at_ms
FROM agent_sessions
WHERE pi_session_id <> '';
