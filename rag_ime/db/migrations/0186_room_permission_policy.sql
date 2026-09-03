-- Persist the three-layer Room permission projection separately from participant Sessions.
-- Lower layers retain an explicit inherit marker so a Room row remains the authority
-- after restart; participant policy is a derived projection only.
ALTER TABLE agent_rooms
    ADD COLUMN partner_execution_mode TEXT NOT NULL DEFAULT 'inherit'
    CHECK (partner_execution_mode IN ('inherit', 'read_only', 'per_action', 'workspace_managed', 'full_trust'));

ALTER TABLE agent_rooms
    ADD COLUMN tool_agent_execution_mode TEXT NOT NULL DEFAULT 'inherit'
    CHECK (tool_agent_execution_mode IN ('inherit', 'read_only', 'per_action', 'workspace_managed', 'full_trust'));

-- Repair rows written while 0146's Room owner was present but reads still inferred
-- the displayed mode from participant Sessions.  Only complete, uniform active
-- participant evidence may replace the Room value; mixed or missing evidence is
-- deterministically least-privileged.  Roleplay remains non-elevated.
UPDATE agent_rooms
SET execution_mode = CASE
    WHEN room_kind = 'roleplay' THEN 'per_action'
    WHEN (
        SELECT COUNT(*)
        FROM agent_room_participants AS p
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
    ) > 0
    AND (
        SELECT COUNT(*)
        FROM agent_room_participants AS p
        JOIN agent_sessions AS s ON s.id = p.session_id
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
          AND s.execution_mode IN ('read_only', 'per_action', 'workspace_managed', 'full_trust')
    ) = (
        SELECT COUNT(*)
        FROM agent_room_participants AS p
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
    )
    AND (
        SELECT COUNT(DISTINCT s.execution_mode)
        FROM agent_room_participants AS p
        JOIN agent_sessions AS s ON s.id = p.session_id
        WHERE p.room_id = agent_rooms.id
          AND p.participant_status = 'active'
          AND s.execution_mode IN ('read_only', 'per_action', 'workspace_managed', 'full_trust')
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
