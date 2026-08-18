CREATE TABLE IF NOT EXISTS agent_connector_bindings (
    binding_id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    external_chat_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('session', 'room')),
    target_id TEXT NOT NULL,
    busy_delivery TEXT NOT NULL DEFAULT 'followUp'
        CHECK(busy_delivery IN ('followUp', 'steer')),
    state TEXT NOT NULL DEFAULT 'active'
        CHECK(state IN ('active', 'disabled')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(connector_id, external_chat_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_connector_bindings_target
ON agent_connector_bindings(target_kind, target_id, state);

CREATE TABLE IF NOT EXISTS agent_connector_inbound (
    ingress_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL REFERENCES agent_connector_bindings(binding_id)
        ON DELETE CASCADE,
    connector_id TEXT NOT NULL,
    external_chat_id TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    message_text TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('session', 'room')),
    target_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending', 'processing', 'routed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retryable INTEGER NOT NULL DEFAULT 1 CHECK(retryable IN (0, 1)),
    lease_token TEXT NOT NULL DEFAULT '',
    lease_until_ms INTEGER NOT NULL DEFAULT 0,
    response_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    routed_at_ms INTEGER,
    UNIQUE(connector_id, external_chat_id, external_message_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_connector_inbound_recovery
ON agent_connector_inbound(state, lease_until_ms, updated_at_ms);

CREATE TABLE IF NOT EXISTS agent_connector_deliveries (
    delivery_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL REFERENCES agent_connector_bindings(binding_id)
        ON DELETE CASCADE,
    connector_id TEXT NOT NULL,
    external_chat_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('session', 'room')),
    source_id TEXT NOT NULL,
    stream_key TEXT NOT NULL,
    turn_id TEXT NOT NULL DEFAULT '',
    source_event_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT 'active'
        CHECK(outcome IN ('active', 'completed', 'failed')),
    terminal INTEGER NOT NULL DEFAULT 0 CHECK(terminal IN (0, 1)),
    desired_revision INTEGER NOT NULL DEFAULT 1,
    delivered_revision INTEGER NOT NULL DEFAULT 0,
    leased_revision INTEGER NOT NULL DEFAULT 0,
    platform_message_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending', 'leased', 'delivered', 'retry_wait', 'dead_letter')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT NOT NULL DEFAULT '',
    lease_until_ms INTEGER NOT NULL DEFAULT 0,
    available_at_ms INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    delivered_at_ms INTEGER,
    UNIQUE(binding_id, stream_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_connector_deliveries_ready
ON agent_connector_deliveries(connector_id, state, available_at_ms, updated_at_ms);

CREATE INDEX IF NOT EXISTS idx_agent_connector_deliveries_turn
ON agent_connector_deliveries(binding_id, turn_id, terminal);
