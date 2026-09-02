CREATE TABLE agent_lab_experiment_revisions (
    experiment_id TEXT NOT NULL,
    revision_sha256 TEXT NOT NULL CHECK (
        length(revision_sha256) = 64
        AND revision_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    imported_at_ms INTEGER NOT NULL CHECK (imported_at_ms >= 0),
    payload_hash TEXT NOT NULL CHECK (
        length(payload_hash) = 64
        AND payload_hash NOT GLOB '*[^0-9a-f]*'
    ),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, revision_sha256)
);

CREATE INDEX idx_agent_lab_experiment_revisions_latest
ON agent_lab_experiment_revisions(experiment_id, imported_at_ms DESC, revision_sha256 DESC);
