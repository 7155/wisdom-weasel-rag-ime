CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_role_book_personal_context_idempotency
ON agent_role_book_revisions(role_id, role_version, proposed_by)
WHERE proposed_by GLOB 'personal-context:*';
