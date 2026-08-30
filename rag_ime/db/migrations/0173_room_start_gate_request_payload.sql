-- Preserve the complete first executable Room request across the explicit
-- start-confirmation pause. Attachments and retry lineage are request data,
-- not approval state, and must reach the original dispatch unchanged.
ALTER TABLE agent_room_start_gates
ADD COLUMN attachment_ids_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE agent_room_start_gates
ADD COLUMN retry_of_root_id TEXT NOT NULL DEFAULT '';
