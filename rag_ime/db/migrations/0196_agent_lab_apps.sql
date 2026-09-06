-- Portable Lab applications retain immutable source versions. Activation and
-- invocation are separate from preparation, and never inferred from prose.
CREATE TABLE agent_lab_apps (
    app_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES agent_lab_projects(project_id),
    scope_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    latest_version INTEGER NOT NULL CHECK (latest_version > 0),
    active_version INTEGER,
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX agent_lab_apps_by_scope ON agent_lab_apps(scope_id, updated_at_ms DESC);
CREATE INDEX agent_lab_apps_by_project ON agent_lab_apps(project_id);
CREATE TABLE agent_lab_app_versions (
    app_id TEXT NOT NULL REFERENCES agent_lab_apps(app_id),
    version INTEGER NOT NULL CHECK (version > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (app_id, version)
);
CREATE TRIGGER agent_lab_app_versions_no_update BEFORE UPDATE ON agent_lab_app_versions
BEGIN SELECT RAISE(ABORT, 'Lab application versions are immutable'); END;
CREATE TRIGGER agent_lab_app_versions_no_delete BEFORE DELETE ON agent_lab_app_versions
BEGIN SELECT RAISE(ABORT, 'Lab application versions are immutable'); END;
CREATE TABLE agent_lab_app_commands (
    scope_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (scope_id, client_request_id)
);
CREATE TABLE agent_lab_app_calls (
    call_id TEXT PRIMARY KEY,
    app_id TEXT NOT NULL REFERENCES agent_lab_apps(app_id),
    app_version INTEGER NOT NULL,
    action_id TEXT NOT NULL,
    input_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','running','completed','failed','cancelled','interrupted')),
    session_id TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX agent_lab_app_calls_by_app ON agent_lab_app_calls(app_id, updated_at_ms DESC);
