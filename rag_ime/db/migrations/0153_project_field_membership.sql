CREATE TABLE IF NOT EXISTS project_fields (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS project_field_room_bindings (
    binding_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_fields(project_id) ON DELETE CASCADE,
    runtime_room_id TEXT NOT NULL REFERENCES agent_rooms(id) ON DELETE CASCADE,
    outcome_room_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(runtime_room_id)
);

CREATE INDEX IF NOT EXISTS idx_project_field_room_bindings_project
ON project_field_room_bindings(project_id, state, outcome_room_id, updated_at_ms DESC);
