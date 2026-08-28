-- Keep the Room-only execution mode separate from the independent Session
-- execution_mode CHECK constraint.  The projected Session contract exposes
-- room_execution_mode as executionMode for an active Room participant, while
-- ordinary Sessions continue to use the existing four-mode column unchanged.
ALTER TABLE agent_sessions
ADD COLUMN room_execution_mode TEXT NOT NULL DEFAULT ''
CHECK (room_execution_mode IN ('', 'room_unrestricted'));
