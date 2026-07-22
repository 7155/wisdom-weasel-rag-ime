ALTER TABLE memory_retrieval_docs
ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1);

ALTER TABLE memory_retrieval_docs
ADD COLUMN projection_version INTEGER NOT NULL DEFAULT 1 CHECK (projection_version >= 1);

ALTER TABLE memory_retrieval_doc_vectors
ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1);

ALTER TABLE memory_retrieval_doc_vectors
ADD COLUMN projection_version INTEGER NOT NULL DEFAULT 1 CHECK (projection_version >= 1);

ALTER TABLE memory_retrieval_doc_vectors
ADD COLUMN built_at_ms INTEGER NOT NULL DEFAULT 0 CHECK (built_at_ms >= 0);

CREATE TABLE IF NOT EXISTS memory_projection_dependencies (
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    dependent_type TEXT NOT NULL,
    dependent_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(source_type, source_id, dependent_type, dependent_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_projection_dependencies_dependent
ON memory_projection_dependencies(dependent_type, dependent_id, source_type, source_id);

UPDATE memory_retrieval_docs
SET source_revision = COALESCE(
        (
            SELECT generation
            FROM memory_source_generations AS generation
            WHERE generation.source_type = CASE memory_retrieval_docs.doc_type
                WHEN 'atom' THEN 'atom'
                WHEN 'book' THEN 'book'
                WHEN 'phrase' THEN 'phrase'
                WHEN 'item' THEN 'item'
                ELSE memory_retrieval_docs.doc_type
            END
              AND generation.source_id = memory_retrieval_docs.source_id
        ),
        CASE
            WHEN memory_retrieval_docs.doc_type = 'timeline'
            THEN MAX(1, memory_retrieval_docs.updated_at_ms)
            ELSE 1
        END
    ),
    projection_version = 1;

UPDATE memory_retrieval_doc_vectors
SET source_revision = COALESCE(
        (
            SELECT CASE
                WHEN memory_retrieval_doc_vectors.updated_at_ms >= doc.updated_at_ms
                THEN doc.source_revision
                ELSE doc.source_revision + 1
            END
            FROM memory_retrieval_docs AS doc
            WHERE doc.doc_id = memory_retrieval_doc_vectors.doc_id
        ),
        1
    ),
    projection_version = COALESCE(
        (
            SELECT projection_version
            FROM memory_retrieval_docs AS doc
            WHERE doc.doc_id = memory_retrieval_doc_vectors.doc_id
        ),
        1
    ),
    built_at_ms = updated_at_ms;

INSERT OR REPLACE INTO memory_projection_dependencies(
    source_type, source_id, dependent_type, dependent_id, source_revision,
    created_at_ms, updated_at_ms
)
SELECT
    CASE doc_type
        WHEN 'atom' THEN 'atom'
        WHEN 'book' THEN 'book'
        WHEN 'phrase' THEN 'phrase'
        WHEN 'item' THEN 'item'
        ELSE doc_type
    END,
    source_id,
    'retrieval_doc',
    doc_id,
    source_revision,
    updated_at_ms,
    updated_at_ms
FROM memory_retrieval_docs;

INSERT OR REPLACE INTO memory_projection_dependencies(
    source_type, source_id, dependent_type, dependent_id, source_revision,
    created_at_ms, updated_at_ms
)
SELECT
    'atom',
    CAST(member.value AS TEXT),
    'book',
    book.book_id,
    COALESCE(generation.generation, 1),
    book.updated_at_ms,
    book.updated_at_ms
FROM memory_books AS book
JOIN json_each(book.memory_atom_ids_json) AS member
LEFT JOIN memory_source_generations AS generation
  ON generation.source_type = 'atom'
 AND generation.source_id = CAST(member.value AS TEXT)
WHERE json_valid(book.memory_atom_ids_json);

INSERT OR REPLACE INTO memory_projection_dependencies(
    source_type, source_id, dependent_type, dependent_id, source_revision,
    created_at_ms, updated_at_ms
)
SELECT DISTINCT
    'atom',
    atom.id,
    'phrase',
    phrase.memory_id,
    COALESCE(generation.generation, 1),
    MAX(atom.updated_at_ms, phrase.updated_at_ms),
    MAX(atom.updated_at_ms, phrase.updated_at_ms)
FROM memory_items AS phrase
JOIN memory_atoms AS atom
  ON EXISTS (
      SELECT 1
      FROM json_each(
          CASE
              WHEN json_valid(atom.source_event_ids_json)
              THEN atom.source_event_ids_json
              ELSE '[]'
          END
      ) AS atom_event
      WHERE CAST(atom_event.value AS INTEGER) = phrase.source_event_id
         OR CAST(atom_event.value AS INTEGER) IN (
             SELECT CAST(phrase_event.value AS INTEGER)
             FROM json_each(
                 CASE
                     WHEN json_valid(phrase.metadata_json)
                     THEN phrase.metadata_json
                     ELSE '{}'
                 END,
                 '$.sourceEventIds'
             ) AS phrase_event
         )
  )
LEFT JOIN memory_source_generations AS generation
  ON generation.source_type = 'atom'
 AND generation.source_id = atom.id
WHERE phrase.kind = 'phrase';

CREATE INDEX IF NOT EXISTS idx_memory_retrieval_docs_revision
ON memory_retrieval_docs(status, doc_type, source_id, source_revision, projection_version);

CREATE INDEX IF NOT EXISTS idx_memory_retrieval_vectors_revision
ON memory_retrieval_doc_vectors(
    provider_fingerprint, doc_id, source_revision, projection_version
);
