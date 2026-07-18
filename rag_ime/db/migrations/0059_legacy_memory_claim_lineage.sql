-- Bring pre-governance Atoms into the claim model without inventing facts.
-- Existing supersession edges are the historical truth: every connected
-- component shares one lineage and only its terminal, evidence-backed Atom may
-- become current. Unsupported legacy Atoms remain auditable but are hidden.

CREATE TABLE IF NOT EXISTS memory_legacy_atom_migration_audit (
    atom_id TEXT NOT NULL REFERENCES memory_atoms(id) ON DELETE RESTRICT,
    migration_version INTEGER NOT NULL CHECK (migration_version = 59),
    previous_status TEXT NOT NULL,
    previous_claim_state TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN (
        'quarantined_missing_visible_evidence',
        'current_evidence_backed',
        'superseded_history'
    )),
    representation_status TEXT NOT NULL,
    representation_claim_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY(atom_id, migration_version)
);

CREATE INDEX IF NOT EXISTS idx_legacy_atom_migration_audit_disposition
ON memory_legacy_atom_migration_audit(
    migration_version,
    disposition,
    atom_id
);

CREATE TEMP TABLE _legacy_atom_scope AS
SELECT id
FROM memory_atoms
WHERE trim(COALESCE(claim_key, '')) = ''
   OR trim(COALESCE(lineage_id, '')) = '';

CREATE TEMP TABLE _legacy_atom_components AS
WITH RECURSIVE
edges(left_id, right_id) AS (
    SELECT old_memory_id, new_memory_id
    FROM memory_supersessions
    WHERE status = 'active'
    UNION
    SELECT new_memory_id, old_memory_id
    FROM memory_supersessions
    WHERE status = 'active'
),
reach(start_id, member_id) AS (
    SELECT id, id FROM memory_atoms
    UNION
    SELECT reach.start_id, edges.right_id
    FROM reach
    JOIN edges ON edges.left_id = reach.member_id
),
resolved AS (
    SELECT
        start_id AS atom_id,
        COALESCE(
            MIN(
                CASE WHEN NOT EXISTS (
                    SELECT 1
                    FROM memory_supersessions outgoing
                    WHERE outgoing.status = 'active'
                      AND outgoing.old_memory_id = reach.member_id
                ) THEN reach.member_id END
            ),
            MIN(member_id)
        ) AS anchor_id
    FROM reach
    GROUP BY start_id
)
SELECT atom_id, anchor_id FROM resolved;

CREATE TEMP TABLE _legacy_atom_evidence AS
SELECT atom.id AS atom_id,
       CASE WHEN EXISTS (
           SELECT 1
           FROM json_each(COALESCE(atom.source_event_ids_json, '[]')) source
           JOIN input_events event ON event.id = CAST(source.value AS INTEGER)
           LEFT JOIN memory_state state ON state.event_id = event.id
           WHERE COALESCE(state.deleted, 0) = 0
             AND NOT EXISTS (
                 SELECT 1
                 FROM memory_tombstones tombstone
                 WHERE tombstone.active = 1
                   AND (
                       (tombstone.target_type = 'source_event_id'
                        AND tombstone.target_value = CAST(event.id AS TEXT))
                       OR
                       (tombstone.target_type = 'memory_id'
                        AND tombstone.target_value = ('event:' || event.id))
                   )
             )
       ) OR EXISTS (
           SELECT 1
           FROM memory_atom_evidence_links link
           JOIN agent_memory_evidence evidence
             ON evidence.evidence_id = link.evidence_id
           WHERE link.memory_atom_id = atom.id
             AND evidence.status = 'active'
       ) THEN 1 ELSE 0 END AS has_visible_evidence
FROM memory_atoms atom;

-- Capture the pre-migration meaning before claim_state is rewritten. The
-- durable audit row is inserted only after the final representation is known.
-- "retracted" remains the old schema's storage representation for quarantine;
-- it must not be interpreted as a user-issued withdrawal.
CREATE TEMP TABLE _legacy_atom_audit_before AS
SELECT
    atom.id AS atom_id,
    atom.status AS previous_status,
    atom.claim_state AS previous_claim_state,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM memory_supersessions edge
            WHERE edge.status = 'active'
              AND edge.old_memory_id = atom.id
        ) THEN 'superseded_history'
        WHEN atom.status IN ('active', 'approved')
             AND COALESCE(evidence.has_visible_evidence, 0) = 1
        THEN 'current_evidence_backed'
        ELSE 'quarantined_missing_visible_evidence'
    END AS disposition,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM memory_supersessions edge
            WHERE edge.status = 'active'
              AND edge.old_memory_id = atom.id
        ) THEN 'Active supersession history establishes this Atom as a predecessor.'
        WHEN atom.status IN ('active', 'approved')
             AND COALESCE(evidence.has_visible_evidence, 0) = 1
        THEN 'The terminal legacy Atom has visible evidence and may remain current.'
        WHEN COALESCE(evidence.has_visible_evidence, 0) = 0
        THEN 'No visible evidence remains; retracted is a compatibility representation, not a user withdrawal.'
        ELSE 'The legacy Atom was already non-current; retracted is a compatibility representation, not a user withdrawal.'
    END AS reason
FROM memory_atoms atom
JOIN _legacy_atom_scope scope ON scope.id = atom.id
LEFT JOIN _legacy_atom_evidence evidence ON evidence.atom_id = atom.id;

-- An active edge wins over stale row status. This prevents an old predecessor
-- from becoming current merely because an older cleanup forgot to change it.
UPDATE memory_atoms
SET status = 'superseded',
    claim_state = 'superseded',
    valid_from_ms = CASE
        WHEN COALESCE(valid_from_ms, 0) > 0 THEN valid_from_ms
        ELSE created_at_ms
    END,
    valid_to_ms = COALESCE(
        valid_to_ms,
        (
            SELECT MIN(created_at_ms)
            FROM memory_supersessions edge
            WHERE edge.status = 'active' AND edge.old_memory_id = memory_atoms.id
        ),
        updated_at_ms
    )
WHERE id IN (SELECT id FROM _legacy_atom_scope)
  AND EXISTS (
      SELECT 1 FROM memory_supersessions edge
      WHERE edge.status = 'active' AND edge.old_memory_id = memory_atoms.id
  );

-- No visible evidence means "not established", not "Current Fact". Keep the
-- row and provenance for review, but remove it from active retrieval.
UPDATE memory_atoms
SET status = 'hidden',
    claim_state = 'retracted',
    valid_from_ms = CASE
        WHEN COALESCE(valid_from_ms, 0) > 0 THEN valid_from_ms
        ELSE created_at_ms
    END,
    valid_to_ms = COALESCE(valid_to_ms, updated_at_ms)
WHERE id IN (SELECT id FROM _legacy_atom_scope)
  AND status IN ('active', 'approved')
  AND NOT EXISTS (
      SELECT 1 FROM memory_supersessions edge
      WHERE edge.status = 'active' AND edge.old_memory_id = memory_atoms.id
  )
  AND COALESCE(
      (SELECT has_visible_evidence FROM _legacy_atom_evidence evidence
       WHERE evidence.atom_id = memory_atoms.id),
      0
  ) = 0;

UPDATE memory_atoms
SET claim_state = CASE
        WHEN status IN ('active', 'approved')
             AND NOT EXISTS (
                 SELECT 1 FROM memory_supersessions edge
                 WHERE edge.status = 'active'
                   AND edge.old_memory_id = memory_atoms.id
             )
             AND COALESCE(
                 (SELECT has_visible_evidence FROM _legacy_atom_evidence evidence
                  WHERE evidence.atom_id = memory_atoms.id),
                 0
             ) = 1
        THEN 'current'
        WHEN status = 'superseded' OR EXISTS (
            SELECT 1 FROM memory_supersessions edge
            WHERE edge.status = 'active' AND edge.old_memory_id = memory_atoms.id
        )
        THEN 'superseded'
        ELSE 'retracted'
    END,
    valid_from_ms = CASE
        WHEN COALESCE(valid_from_ms, 0) > 0 THEN valid_from_ms
        ELSE created_at_ms
    END,
    valid_to_ms = CASE
        WHEN status IN ('active', 'approved')
             AND NOT EXISTS (
                 SELECT 1 FROM memory_supersessions edge
                 WHERE edge.status = 'active'
                   AND edge.old_memory_id = memory_atoms.id
             )
             AND COALESCE(
                 (SELECT has_visible_evidence FROM _legacy_atom_evidence evidence
                  WHERE evidence.atom_id = memory_atoms.id),
                 0
             ) = 1
        THEN NULL
        ELSE COALESCE(valid_to_ms, updated_at_ms)
    END
WHERE id IN (SELECT id FROM _legacy_atom_scope);

-- Prefer an already-governed key in a mixed component; otherwise derive one
-- from the terminal successor. This preserves all active supersession chains.
UPDATE memory_atoms
SET claim_key = substr(
        COALESCE(
            (
                SELECT MIN(NULLIF(trim(member.claim_key), ''))
                FROM _legacy_atom_components peer
                JOIN memory_atoms member ON member.id = peer.atom_id
                WHERE peer.anchor_id = component.anchor_id
            ),
            'legacy:' || component.anchor_id
        ),
        1,
        240
    )
FROM _legacy_atom_components component
WHERE memory_atoms.id = component.atom_id
  AND memory_atoms.id IN (SELECT id FROM _legacy_atom_scope)
  AND trim(COALESCE(memory_atoms.claim_key, '')) = '';

UPDATE memory_atoms
SET lineage_id = substr(
        COALESCE(
            (
                SELECT MIN(NULLIF(trim(member.lineage_id), ''))
                FROM _legacy_atom_components peer
                JOIN memory_atoms member ON member.id = peer.atom_id
                WHERE peer.anchor_id = component.anchor_id
            ),
            'lineage:legacy:' || component.anchor_id
        ),
        1,
        240
    )
FROM _legacy_atom_components component
WHERE memory_atoms.id = component.atom_id
  AND memory_atoms.id IN (SELECT id FROM _legacy_atom_scope)
  AND trim(COALESCE(memory_atoms.lineage_id, '')) = '';

-- The scalar supersedes_id is populated only when history truly has one
-- immediate predecessor. Multi-parent history remains in memory_supersessions.
UPDATE memory_atoms
SET supersedes_id = (
    SELECT MIN(edge.old_memory_id)
    FROM memory_supersessions edge
    WHERE edge.status = 'active' AND edge.new_memory_id = memory_atoms.id
)
WHERE id IN (SELECT id FROM _legacy_atom_scope)
  AND (
      SELECT COUNT(*)
      FROM memory_supersessions edge
      WHERE edge.status = 'active' AND edge.new_memory_id = memory_atoms.id
  ) = 1;

INSERT INTO memory_legacy_atom_migration_audit(
    atom_id, migration_version, previous_status, previous_claim_state,
    disposition, representation_status, representation_claim_state,
    reason, created_at_ms
)
SELECT
    before.atom_id,
    59,
    before.previous_status,
    before.previous_claim_state,
    before.disposition,
    atom.status,
    atom.claim_state,
    before.reason,
    CAST(strftime('%s', 'now') AS INTEGER) * 1000
FROM _legacy_atom_audit_before before
JOIN memory_atoms atom ON atom.id = before.atom_id
ON CONFLICT(atom_id, migration_version) DO NOTHING;

DROP TABLE _legacy_atom_audit_before;
DROP TABLE _legacy_atom_evidence;
DROP TABLE _legacy_atom_components;
DROP TABLE _legacy_atom_scope;
