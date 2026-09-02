-- Give a Room the same durable App ownership boundary already used by its
-- participant Sessions. Empty values preserve legacy ordinary Agent Rooms;
-- Extension App Rooms must carry both fields together at the lifecycle seam.
ALTER TABLE agent_rooms
ADD COLUMN owner_app_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_rooms
ADD COLUMN surface_key TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_agent_rooms_surface_recent
ON agent_rooms(owner_app_id, surface_key, status, updated_at_ms DESC, id DESC);
