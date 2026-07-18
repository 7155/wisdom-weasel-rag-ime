ALTER TABLE memory_atoms
ADD COLUMN claim_key TEXT NOT NULL DEFAULT '';

ALTER TABLE memory_atoms
ADD COLUMN lineage_id TEXT NOT NULL DEFAULT '';

ALTER TABLE memory_atoms
ADD COLUMN claim_state TEXT NOT NULL DEFAULT 'current'
CHECK (claim_state IN ('current', 'superseded', 'retracted'));

ALTER TABLE memory_atoms
ADD COLUMN valid_from_ms INTEGER NOT NULL DEFAULT 0;

ALTER TABLE memory_atoms
ADD COLUMN valid_to_ms INTEGER;

ALTER TABLE memory_atoms
ADD COLUMN supersedes_id TEXT;

CREATE INDEX IF NOT EXISTS idx_memory_atoms_claim_history
ON memory_atoms(
    claim_key,
    scope_project,
    scope_app,
    kind,
    valid_from_ms DESC,
    updated_at_ms DESC
)
WHERE claim_key <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_atoms_one_current_claim
ON memory_atoms(
    claim_key,
    COALESCE(scope_project, ''),
    COALESCE(scope_app, ''),
    kind
)
WHERE claim_key <> ''
  AND claim_state = 'current'
  AND status IN ('active', 'approved');
