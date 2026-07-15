CREATE TABLE IF NOT EXISTS memory_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room')),
    owner_id TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'archived', 'tombstoned')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(owner_kind, owner_id, project, entity_type, normalized_name)
);

CREATE INDEX IF NOT EXISTS idx_memory_entities_scope_name
ON memory_entities(owner_kind, owner_id, project, status, normalized_name);

CREATE TABLE IF NOT EXISTS memory_entity_aliases (
    entity_id TEXT NOT NULL REFERENCES memory_entities(entity_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'synonym',
    weight REAL NOT NULL DEFAULT 0.8 CHECK (weight >= 0.0 AND weight <= 1.0),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(entity_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_memory_entity_aliases_lookup
ON memory_entity_aliases(normalized_alias, weight DESC);

CREATE TABLE IF NOT EXISTS memory_relations (
    relation_id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL REFERENCES memory_entities(entity_id) ON DELETE RESTRICT,
    target_entity_id TEXT NOT NULL REFERENCES memory_entities(entity_id) ON DELETE RESTRICT,
    relation_type TEXT NOT NULL,
    fact TEXT NOT NULL,
    normalized_fact TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('user', 'shared', 'agent', 'session', 'room')),
    owner_id TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    valid_from_ms INTEGER NOT NULL,
    valid_to_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'retracted', 'tombstoned')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    idempotency_key TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (valid_to_ms IS NULL OR valid_to_ms > valid_from_ms),
    UNIQUE(owner_kind, owner_id, project, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_memory_relations_source_time
ON memory_relations(source_entity_id, status, valid_from_ms, valid_to_ms);

CREATE INDEX IF NOT EXISTS idx_memory_relations_target_time
ON memory_relations(target_entity_id, status, valid_from_ms, valid_to_ms);

CREATE INDEX IF NOT EXISTS idx_memory_relations_scope
ON memory_relations(owner_kind, owner_id, project, status, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS memory_relation_sources (
    relation_id TEXT NOT NULL REFERENCES memory_relations(relation_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1),
    evidence_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(relation_id, source_type, source_id, source_revision)
);

CREATE INDEX IF NOT EXISTS idx_memory_relation_sources_source
ON memory_relation_sources(source_type, source_id, relation_id);

CREATE TABLE IF NOT EXISTS memory_projection_outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    projection_kind TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'processing', 'applied', 'failed', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    processed_at_ms INTEGER,
    last_error TEXT,
    UNIQUE(projection_kind, aggregate_type, aggregate_id, operation, revision)
);

CREATE INDEX IF NOT EXISTS idx_memory_projection_outbox_ready
ON memory_projection_outbox(projection_kind, state, available_at_ms, outbox_id);

CREATE TABLE IF NOT EXISTS memory_projection_checkpoints (
    projection_kind TEXT PRIMARY KEY,
    last_outbox_id INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_graph_projection_map (
    projection_kind TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(projection_kind, aggregate_type, aggregate_id)
);
