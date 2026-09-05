CREATE TABLE agent_lab_scene_recipe_versions (
    scene_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (scene_id, version_id)
);

CREATE TABLE agent_lab_scene_recipe_events (
    scene_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    event_id TEXT NOT NULL UNIQUE,
    client_request_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('apply', 'rollback')),
    request_json TEXT NOT NULL,
    from_version_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    rollback_revision INTEGER CHECK (rollback_revision >= 0),
    event_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (scene_id, revision),
    UNIQUE (scene_id, client_request_id),
    FOREIGN KEY (scene_id, from_version_id)
        REFERENCES agent_lab_scene_recipe_versions(scene_id, version_id),
    FOREIGN KEY (scene_id, version_id)
        REFERENCES agent_lab_scene_recipe_versions(scene_id, version_id)
);

CREATE TRIGGER agent_lab_scene_recipe_versions_no_update
BEFORE UPDATE ON agent_lab_scene_recipe_versions
BEGIN
    SELECT RAISE(ABORT, 'Agent Lab scene recipe versions are immutable');
END;

CREATE TRIGGER agent_lab_scene_recipe_versions_no_delete
BEFORE DELETE ON agent_lab_scene_recipe_versions
BEGIN
    SELECT RAISE(ABORT, 'Agent Lab scene recipe versions are immutable');
END;

CREATE TRIGGER agent_lab_scene_recipe_events_no_update
BEFORE UPDATE ON agent_lab_scene_recipe_events
BEGIN
    SELECT RAISE(ABORT, 'Agent Lab scene recipe events are append-only');
END;

CREATE TRIGGER agent_lab_scene_recipe_events_no_delete
BEFORE DELETE ON agent_lab_scene_recipe_events
BEGIN
    SELECT RAISE(ABORT, 'Agent Lab scene recipe events are append-only');
END;
