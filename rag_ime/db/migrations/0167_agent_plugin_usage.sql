CREATE TABLE agent_plugin_usage_events (
    event_id TEXT PRIMARY KEY,
    occurred_at_ms INTEGER NOT NULL CHECK (occurred_at_ms >= 0),
    session_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    package_version TEXT NOT NULL,
    resource_kind TEXT NOT NULL CHECK (
        resource_kind IN ('extension', 'tool', 'command', 'skill', 'prompt', 'theme')
    ),
    resource_id TEXT NOT NULL,
    activity TEXT NOT NULL CHECK (activity IN ('loaded', 'invoked', 'finished')),
    invocation_id TEXT,
    outcome TEXT CHECK (outcome IS NULL OR outcome IN ('succeeded', 'failed', 'cancelled')),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (
        (activity = 'loaded' AND invocation_id IS NULL AND outcome IS NULL AND duration_ms IS NULL)
        OR (activity = 'invoked' AND invocation_id IS NOT NULL AND outcome IS NULL AND duration_ms IS NULL)
        OR (activity = 'finished' AND invocation_id IS NOT NULL AND outcome IS NOT NULL AND duration_ms IS NOT NULL)
    ),
    UNIQUE(session_id, package_id, package_version, resource_kind, resource_id, invocation_id, activity)
);

CREATE INDEX idx_agent_plugin_usage_package_resource_time
    ON agent_plugin_usage_events(
        package_id, package_version, resource_kind, resource_id, occurred_at_ms DESC
    );

CREATE INDEX idx_agent_plugin_usage_session_time
    ON agent_plugin_usage_events(session_id, occurred_at_ms DESC);
