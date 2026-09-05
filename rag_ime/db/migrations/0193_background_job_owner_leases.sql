-- Supervisor ownership is separate from the identity of the command process.
CREATE TABLE agent_background_job_owner_leases (
    job_id TEXT PRIMARY KEY REFERENCES agent_background_jobs(job_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    owner_pid INTEGER NOT NULL,
    owner_birth_token TEXT NOT NULL,
    heartbeat_at_ms INTEGER NOT NULL,
    deadline_tick_ms INTEGER NOT NULL
);
