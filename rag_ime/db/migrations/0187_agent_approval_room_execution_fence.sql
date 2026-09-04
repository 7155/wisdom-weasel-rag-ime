-- Bind automatic Room execution to the exact live dispatch and give Stop a
-- durable, atomic boundary against an approval that has not begun executing.

ALTER TABLE agent_approvals
ADD COLUMN room_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approvals
ADD COLUMN room_root_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approvals
ADD COLUMN room_dispatch_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approvals
ADD COLUMN room_generation INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_approvals
ADD COLUMN execution_claimed_at_ms INTEGER NOT NULL DEFAULT 0;
