-- Lab is a general Agent-led workspace. Domain-specific goals, standards and
-- output forms live in versioned artifacts, not a universal business schema.
ALTER TABLE agent_lab_project_goal_versions RENAME TO agent_lab_project_brief_versions;
ALTER TABLE agent_lab_projects ADD COLUMN scope_id TEXT NOT NULL DEFAULT 'local';
CREATE INDEX agent_lab_projects_by_scope ON agent_lab_projects(scope_id, updated_at_ms DESC);

CREATE TABLE agent_lab_project_artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES agent_lab_projects(project_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX agent_lab_project_artifacts_by_project ON agent_lab_project_artifacts(project_id, updated_at_ms DESC);
CREATE TABLE agent_lab_project_artifact_versions (
    artifact_id TEXT NOT NULL REFERENCES agent_lab_project_artifacts(artifact_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(artifact_id, revision)
);
CREATE TRIGGER agent_lab_project_artifact_versions_no_update
BEFORE UPDATE ON agent_lab_project_artifact_versions
BEGIN SELECT RAISE(ABORT, 'Lab artifact versions are immutable'); END;
CREATE TRIGGER agent_lab_project_artifact_versions_no_delete
BEFORE DELETE ON agent_lab_project_artifact_versions
BEGIN SELECT RAISE(ABORT, 'Lab artifact versions are immutable'); END;
