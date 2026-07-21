ALTER TABLE agent_room_participants
ADD COLUMN collaboration_role_key TEXT NOT NULL DEFAULT 'implementer'
CHECK (collaboration_role_key IN ('coordinator', 'researcher', 'implementer', 'reviewer', 'specialist'));

UPDATE agent_room_participants
SET collaboration_role_key = CASE
    WHEN collaboration_role = 'executor' THEN 'implementer'
    ELSE collaboration_role
END;
