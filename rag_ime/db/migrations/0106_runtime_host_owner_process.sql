ALTER TABLE room_v2_runtime_host_processes
ADD COLUMN owner_process_id INTEGER NOT NULL DEFAULT 0;

ALTER TABLE room_v2_runtime_host_processes
ADD COLUMN owner_process_birth_token TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_room_v2_runtime_host_owner_process
ON room_v2_runtime_host_processes(
    state,
    owner_process_id,
    owner_process_birth_token
);
