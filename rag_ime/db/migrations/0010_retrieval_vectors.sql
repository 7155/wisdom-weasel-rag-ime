CREATE TABLE IF NOT EXISTS memory_retrieval_doc_vectors (
    doc_id TEXT NOT NULL,
    provider_fingerprint TEXT NOT NULL,
    raw_vector_json TEXT NOT NULL DEFAULT '[]',
    tag_vector_json TEXT NOT NULL DEFAULT '[]',
    group_vector_json TEXT NOT NULL DEFAULT '[]',
    dimensions INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(doc_id, provider_fingerprint),
    FOREIGN KEY(doc_id) REFERENCES memory_retrieval_docs(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_retrieval_doc_vectors_provider
ON memory_retrieval_doc_vectors(provider_fingerprint, updated_at_ms DESC);
