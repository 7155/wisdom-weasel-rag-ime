CREATE TABLE agent_lab_projects (
    project_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE TABLE agent_lab_project_material_sets (
    material_set_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES agent_lab_projects(project_id),
    version INTEGER NOT NULL CHECK (version > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(project_id, version)
);
CREATE TABLE agent_lab_project_goal_versions (
    project_id TEXT NOT NULL REFERENCES agent_lab_projects(project_id),
    version INTEGER NOT NULL CHECK (version > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(project_id, version)
);
CREATE TABLE agent_lab_project_commands (
    client_request_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES agent_lab_projects(project_id),
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE TRIGGER agent_lab_project_material_sets_no_update
BEFORE UPDATE ON agent_lab_project_material_sets
BEGIN SELECT RAISE(ABORT, 'Lab material sets are immutable'); END;
CREATE TRIGGER agent_lab_project_material_sets_no_delete
BEFORE DELETE ON agent_lab_project_material_sets
BEGIN SELECT RAISE(ABORT, 'Lab material sets are immutable'); END;
CREATE TRIGGER agent_lab_project_goal_versions_no_update
BEFORE UPDATE ON agent_lab_project_goal_versions
BEGIN SELECT RAISE(ABORT, 'Lab goal versions are immutable'); END;
CREATE TRIGGER agent_lab_project_goal_versions_no_delete
BEFORE DELETE ON agent_lab_project_goal_versions
BEGIN SELECT RAISE(ABORT, 'Lab goal versions are immutable'); END;
CREATE TRIGGER agent_lab_project_commands_no_update
BEFORE UPDATE ON agent_lab_project_commands
BEGIN SELECT RAISE(ABORT, 'Lab project command receipts are immutable'); END;
CREATE TRIGGER agent_lab_project_commands_no_delete
BEFORE DELETE ON agent_lab_project_commands
BEGIN SELECT RAISE(ABORT, 'Lab project command receipts are immutable'); END;
