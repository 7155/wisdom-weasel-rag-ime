ALTER TABLE agent_rooms
ADD COLUMN workspace_roots_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE agent_room_participants
ADD COLUMN collaboration_role TEXT NOT NULL DEFAULT 'executor'
CHECK (collaboration_role IN ('coordinator', 'executor', 'researcher'));
