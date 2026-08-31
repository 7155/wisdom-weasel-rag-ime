-- Keep Extension App conversations in Pi's ordinary conversation lifecycle
-- while giving their owning product surface a durable, queryable identity.
ALTER TABLE agent_sessions
ADD COLUMN surface_kind TEXT NOT NULL DEFAULT 'agent'
CHECK (surface_kind IN ('agent', 'extension_app'));

ALTER TABLE agent_sessions
ADD COLUMN owner_app_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_sessions
ADD COLUMN surface_key TEXT NOT NULL DEFAULT '';

UPDATE agent_sessions
SET surface_kind = 'extension_app',
    owner_app_id = 'extension:zhanggui-wenshu',
    surface_key = CASE title
        WHEN '掌柜问数 · 问数' THEN 'ask'
        WHEN '掌柜问数 · 对账' THEN 'reconcile'
        WHEN '掌柜问数 · 解释' THEN 'explain'
        ELSE surface_key
    END
WHERE session_kind = 'conversation'
  AND title IN ('掌柜问数 · 问数', '掌柜问数 · 对账', '掌柜问数 · 解释');

CREATE INDEX idx_agent_sessions_surface_recent
ON agent_sessions(
    surface_kind,
    owner_app_id,
    surface_key,
    status,
    updated_at_ms DESC,
    id DESC
);
