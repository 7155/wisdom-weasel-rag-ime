ALTER TABLE agent_rooms
ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'per_action'
CHECK (execution_mode IN ('read_only', 'per_action', 'workspace_managed', 'full_trust'));

UPDATE agent_rooms
SET execution_mode = CASE
    WHEN room_kind = 'roleplay' THEN 'per_action'
    WHEN (
        SELECT COUNT(*)
        FROM agent_room_participants AS p
        JOIN agent_sessions AS s ON s.id = p.session_id
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
    ) > 0
    AND (
        SELECT COUNT(DISTINCT s.execution_mode)
        FROM agent_room_participants AS p
        JOIN agent_sessions AS s ON s.id = p.session_id
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
    ) = 1
    THEN (
        SELECT MIN(s.execution_mode)
        FROM agent_room_participants AS p
        JOIN agent_sessions AS s ON s.id = p.session_id
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
    )
    ELSE 'per_action'
END;
