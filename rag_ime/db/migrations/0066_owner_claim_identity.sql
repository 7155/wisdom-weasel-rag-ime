-- A durable claim is identified by its owner and scope, not by the model's
-- mutable category label. Before this migration, changing an Atom from
-- project_fact to project_decision could leave two current values, while two
-- different owners could not store the same claim key at all.

DROP INDEX IF EXISTS idx_memory_atoms_one_current_claim;
DROP INDEX IF EXISTS idx_memory_atoms_claim_history;

-- Repair any cross-kind duplicates that the old index allowed. The newest
-- valid fact remains current; every other row becomes auditable history.
CREATE TEMP TABLE _memory_claim_rank_0066 AS
SELECT
    id,
    FIRST_VALUE(id) OVER claim_partition AS winner_id,
    ROW_NUMBER() OVER claim_partition AS claim_rank
FROM memory_atoms
WHERE trim(COALESCE(claim_key, '')) <> ''
  AND claim_state = 'current'
  AND status IN ('active', 'approved')
WINDOW claim_partition AS (
    PARTITION BY owner_kind, owner_id, claim_key,
                 COALESCE(scope_project, ''), COALESCE(scope_app, '')
    ORDER BY valid_from_ms DESC, updated_at_ms DESC,
             created_at_ms DESC, id DESC
);

CREATE TEMP TABLE _memory_claim_duplicates_0066 AS
SELECT
    ranked.id AS old_id,
    ranked.winner_id AS new_id,
    CASE
        WHEN COALESCE(winner.valid_from_ms, 0) > 0
        THEN winner.valid_from_ms
        ELSE winner.updated_at_ms
    END AS valid_to_ms,
    winner.lineage_id AS lineage_id,
    winner.source_event_ids_json AS source_event_ids_json
FROM _memory_claim_rank_0066 ranked
JOIN memory_atoms winner ON winner.id = ranked.winner_id
WHERE ranked.claim_rank > 1;

INSERT OR IGNORE INTO memory_supersessions(
    supersession_id,
    old_memory_id,
    new_memory_id,
    reason,
    source_event_ids_json,
    status,
    created_at_ms,
    rolled_back_at_ms,
    metadata_json
)
SELECT
    'supersession:migration-0066:' || old_id || '->' || new_id,
    old_id,
    new_id,
    'same_owner_claim_key_newer_value',
    COALESCE(source_event_ids_json, '[]'),
    'active',
    CAST(strftime('%s', 'now') AS INTEGER) * 1000,
    NULL,
    '{"source":"schema_migration","version":66}'
FROM _memory_claim_duplicates_0066;

UPDATE memory_atoms
SET status = 'superseded',
    claim_state = 'superseded',
    valid_to_ms = COALESCE(
        valid_to_ms,
        (
            SELECT duplicate.valid_to_ms
            FROM _memory_claim_duplicates_0066 duplicate
            WHERE duplicate.old_id = memory_atoms.id
        ),
        updated_at_ms
    ),
    lineage_id = COALESCE(
        NULLIF(
            (
                SELECT duplicate.lineage_id
                FROM _memory_claim_duplicates_0066 duplicate
                WHERE duplicate.old_id = memory_atoms.id
            ),
            ''
        ),
        lineage_id
    ),
    updated_at_ms = MAX(
        updated_at_ms,
        CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
WHERE id IN (SELECT old_id FROM _memory_claim_duplicates_0066);

-- The scalar predecessor is meaningful only for a single-parent update. The
-- full many-to-one history always remains in memory_supersessions.
UPDATE memory_atoms
SET supersedes_id = (
    SELECT MIN(duplicate.old_id)
    FROM _memory_claim_duplicates_0066 duplicate
    WHERE duplicate.new_id = memory_atoms.id
)
WHERE id IN (SELECT new_id FROM _memory_claim_duplicates_0066)
  AND COALESCE(supersedes_id, '') = ''
  AND (
      SELECT COUNT(*)
      FROM _memory_claim_duplicates_0066 duplicate
      WHERE duplicate.new_id = memory_atoms.id
  ) = 1;

DROP TABLE _memory_claim_duplicates_0066;
DROP TABLE _memory_claim_rank_0066;

CREATE INDEX idx_memory_atoms_claim_history
ON memory_atoms(
    owner_kind,
    owner_id,
    claim_key,
    COALESCE(scope_project, ''),
    COALESCE(scope_app, ''),
    valid_from_ms DESC,
    updated_at_ms DESC
)
WHERE claim_key <> '';

CREATE UNIQUE INDEX idx_memory_atoms_one_current_claim
ON memory_atoms(
    owner_kind,
    owner_id,
    claim_key,
    COALESCE(scope_project, ''),
    COALESCE(scope_app, '')
)
WHERE claim_key <> ''
  AND claim_state = 'current'
  AND status IN ('active', 'approved');
