-- Preserve the original objective submission identity across the explicit
-- start confirmation replay.  This is a Room command identity, not a
-- Session/runtime or tool-approval identity.
ALTER TABLE agent_room_start_gates
ADD COLUMN client_message_id TEXT NOT NULL DEFAULT '';
