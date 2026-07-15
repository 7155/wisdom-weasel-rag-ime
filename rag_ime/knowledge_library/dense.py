from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from ..embeddings import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    NullEmbeddingProvider,
    cosine_similarity,
    embed_query,
    embedding_provider_info,
)


class DenseIndex(Protocol):
    """Optional projection index. SQLite remains the canonical content store."""

    def replace_document(self, document_id: str, chunks: Sequence[dict[str, Any]]) -> None:
        ...

    def delete_document(self, document_id: str) -> None:
        ...

    def search(
        self,
        query: str,
        *,
        base_ids: Sequence[str],
        limit: int,
        document_ids: Sequence[str] = (),
    ) -> Sequence[tuple[str, float]]:
        ...

    def status(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class NullDenseIndex:
    reason: str = "dense index is not configured; lexical FTS5 search remains available"

    def replace_document(self, document_id: str, chunks: Sequence[dict[str, Any]]) -> None:
        return None

    def delete_document(self, document_id: str) -> None:
        return None

    def search(
        self,
        query: str,
        *,
        base_ids: Sequence[str],
        limit: int,
        document_ids: Sequence[str] = (),
    ) -> Sequence[tuple[str, float]]:
        return ()

    def status(self) -> dict[str, Any]:
        return {
            "available": False,
            "degraded": True,
            "kind": "none",
            "ann": False,
            "scalable": False,
            "provider": embedding_provider_info(NullEmbeddingProvider()),
            "reason": self.reason,
        }


class SqliteDenseIndex:
    """Persistent local vector projection backed by the document library SQLite file."""

    def __init__(
        self,
        database_path: Path,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
        fallback_from: str = "",
        fallback_reason: str = "",
    ):
        self.database_path = Path(database_path)
        self.provider = provider
        self.batch_size = max(1, min(128, int(batch_size)))
        self.fallback_from = str(fallback_from or "")
        self.fallback_reason = str(fallback_reason or "")
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_dense_chunks ("
                "chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, base_id TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, vector_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_dense_base ON knowledge_dense_chunks(base_id, fingerprint)"
            )

    def replace_document(self, document_id: str, chunks: Sequence[dict[str, Any]]) -> None:
        records: list[tuple[str, str, str, str, str]] = []
        texts = [str(chunk.get("content") or "") for chunk in chunks]
        embed_many = getattr(self.provider, "embed_many", None)
        vectors = (
            embed_many(texts, batch_size=self.batch_size)
            if callable(embed_many)
            else [self.provider.embed(text) for text in texts]
        )
        if len(vectors) != len(chunks):
            raise RuntimeError("embedding provider returned an unexpected batch size")
        for chunk, vector in zip(chunks, vectors):
            if not vector:
                continue
            records.append(
                (
                    str(chunk["id"]),
                    document_id,
                    str(chunk["base_id"]),
                    str(self.provider.fingerprint),
                    json.dumps(vector, separators=(",", ":")),
                )
            )
        with self._connection() as connection:
            connection.execute("DELETE FROM knowledge_dense_chunks WHERE document_id=?", (document_id,))
            connection.executemany(
                "INSERT INTO knowledge_dense_chunks(chunk_id, document_id, base_id, fingerprint, vector_json) "
                "VALUES (?, ?, ?, ?, ?)",
                records,
            )

    def delete_document(self, document_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM knowledge_dense_chunks WHERE document_id=?", (document_id,))

    def search(
        self,
        query: str,
        *,
        base_ids: Sequence[str],
        limit: int,
        document_ids: Sequence[str] = (),
    ) -> Sequence[tuple[str, float]]:
        vector = embed_query(self.provider, query)
        if not vector:
            return ()
        params: list[Any] = [str(self.provider.fingerprint)]
        filter_sql = ""
        if base_ids:
            filter_sql += f" AND base_id IN ({', '.join('?' for _ in base_ids)})"
            params.extend(base_ids)
        if document_ids:
            filter_sql += f" AND document_id IN ({', '.join('?' for _ in document_ids)})"
            params.extend(document_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT chunk_id, vector_json FROM knowledge_dense_chunks WHERE fingerprint=?{filter_sql}",
                params,
            ).fetchall()
        scored: list[tuple[str, float]] = []
        for row in rows:
            try:
                stored = [float(value) for value in json.loads(str(row["vector_json"]))]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            scored.append((str(row["chunk_id"]), cosine_similarity(vector, stored)))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[: max(1, min(100, int(limit)))]

    def status(self) -> dict[str, Any]:
        with self._connection() as connection:
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_dense_chunks WHERE fingerprint=?",
                    (str(self.provider.fingerprint),),
                ).fetchone()[0]
            )
        provider = embedding_provider_info(self.provider)
        degraded = isinstance(self.provider, HashingEmbeddingProvider) or bool(self.fallback_reason)
        result = {
            "available": True,
            "degraded": degraded,
            "kind": "sqlite-exact-vector-scan",
            "backend": "sqlite-exact",
            "ann": False,
            "scalable": False,
            "fingerprint": str(self.provider.fingerprint),
            "provider": provider,
            "batchSize": self.batch_size,
            "vectorCount": count,
        }
        if isinstance(self.provider, HashingEmbeddingProvider):
            result["reason"] = "local-hash is a lexical baseline, not a semantic embedding model"
        if self.fallback_reason:
            result.update(
                {
                    "fallbackFrom": self.fallback_from,
                    "reason": self.fallback_reason,
                }
            )
        return result


class USearchDenseIndex(SqliteDenseIndex):
    """Optional persistent USearch HNSW projection.

    Vector metadata remains canonical in SQLite. HNSW files are rebuildable
    projections sharded by base so scoped searches do not need a global scan.
    """

    def __init__(
        self,
        database_path: Path,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
        index_factory: Callable[..., Any] | None = None,
        array_factory: Callable[[Sequence[Any], str], Any] | None = None,
    ):
        self._index_factory = index_factory
        self._array_factory = array_factory
        self._ann_lock = threading.RLock()
        self.index_root = Path(database_path).parent / "ann"
        self.index_root.mkdir(parents=True, exist_ok=True)
        super().__init__(database_path, provider, batch_size=batch_size)
        self._migrate_ann()
        self._startup_rebuilt = 0
        self._startup_error = ""
        try:
            self._dependencies()
            self._synchronize_projection()
        except RuntimeError as exc:
            self._startup_error = str(exc)

    def _migrate_ann(self) -> None:
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_ann_keys ("
                "ann_key INTEGER PRIMARY KEY AUTOINCREMENT, chunk_id TEXT NOT NULL UNIQUE, "
                "document_id TEXT NOT NULL, base_id TEXT NOT NULL, fingerprint TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_ann_base "
                "ON knowledge_ann_keys(base_id, fingerprint)"
            )

    def _dependencies(self) -> tuple[Callable[..., Any], Callable[[Sequence[Any], str], Any]]:
        if self._index_factory is not None and self._array_factory is not None:
            return self._index_factory, self._array_factory
        try:
            import numpy as np
            from usearch.index import Index
        except ImportError as exc:
            raise RuntimeError(
                "USearch ANN requires the 'knowledge-ann' optional dependency"
            ) from exc
        return Index, lambda values, dtype: np.asarray(values, dtype=dtype)

    def replace_document(self, document_id: str, chunks: Sequence[dict[str, Any]]) -> None:
        with self._ann_lock:
            old_bases = self._document_bases(document_id)
            super().replace_document(document_id, chunks)
            with self._connection() as connection:
                connection.execute("DELETE FROM knowledge_ann_keys WHERE document_id=?", (document_id,))
                connection.execute(
                    "INSERT INTO knowledge_ann_keys(chunk_id, document_id, base_id, fingerprint) "
                    "SELECT chunk_id, document_id, base_id, fingerprint FROM knowledge_dense_chunks "
                    "WHERE document_id=? AND fingerprint=?",
                    (document_id, str(self.provider.fingerprint)),
                )
            new_bases = {str(chunk["base_id"]) for chunk in chunks}
            for base_id in sorted(old_bases | new_bases):
                self.rebuild_base(base_id)

    def delete_document(self, document_id: str) -> None:
        with self._ann_lock:
            bases = self._document_bases(document_id)
            super().delete_document(document_id)
            with self._connection() as connection:
                connection.execute("DELETE FROM knowledge_ann_keys WHERE document_id=?", (document_id,))
            for base_id in sorted(bases):
                self.rebuild_base(base_id)

    def rebuild(self) -> None:
        with self._connection() as connection:
            base_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT base_id FROM knowledge_dense_chunks WHERE fingerprint=?",
                    (str(self.provider.fingerprint),),
                ).fetchall()
            ]
        for base_id in base_ids:
            self.rebuild_base(base_id)

    def _synchronize_projection(self) -> None:
        fingerprint = str(self.provider.fingerprint)
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM knowledge_ann_keys WHERE NOT EXISTS ("
                "SELECT 1 FROM knowledge_dense_chunks d WHERE d.chunk_id=knowledge_ann_keys.chunk_id "
                "AND d.fingerprint=knowledge_ann_keys.fingerprint)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_ann_keys(chunk_id, document_id, base_id, fingerprint) "
                "SELECT chunk_id, document_id, base_id, fingerprint FROM knowledge_dense_chunks WHERE fingerprint=?",
                (fingerprint,),
            )
            base_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT base_id FROM knowledge_dense_chunks WHERE fingerprint=? ORDER BY base_id",
                    (fingerprint,),
                ).fetchall()
            ]
        for base_id in base_ids:
            expected = self._base_vector_count(base_id)
            actual = self._index_file_count(base_id)
            if actual != expected:
                self.rebuild_base(base_id)
                self._startup_rebuilt += 1

    def rebuild_base(self, base_id: str) -> None:
        with self._ann_lock:
            rows = self._ann_rows(base_id)
            path = self._index_path(base_id)
            if not rows:
                path.unlink(missing_ok=True)
                return
            vectors = [json.loads(str(row["vector_json"])) for row in rows]
            dimensions = len(vectors[0])
            if dimensions <= 0 or any(len(vector) != dimensions for vector in vectors):
                raise RuntimeError("dense vectors have inconsistent dimensions")
            index_factory, array_factory = self._dependencies()
            index = index_factory(ndim=dimensions, metric="cos", dtype="f32")
            index.add(
                array_factory([int(row["ann_key"]) for row in rows], "uint64"),
                array_factory(vectors, "float32"),
            )
            temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
            index.save(temporary)
            os.replace(temporary, path)

    def search(
        self,
        query: str,
        *,
        base_ids: Sequence[str],
        limit: int,
        document_ids: Sequence[str] = (),
    ) -> Sequence[tuple[str, float]]:
        if document_ids:
            # A file-scoped search is already a narrow projection. Keep it exact
            # rather than silently dropping filtered HNSW candidates.
            return super().search(
                query,
                base_ids=base_ids,
                limit=limit,
                document_ids=document_ids,
            )
        vector = embed_query(self.provider, query)
        if not vector:
            return ()
        selected_bases = list(base_ids) or self._indexed_bases()
        index_factory, array_factory = self._dependencies()
        scored: list[tuple[str, float]] = []
        with self._ann_lock:
            for base_id in selected_bases:
                path = self._index_path(base_id)
                if not path.is_file():
                    self.rebuild_base(base_id)
                if not path.is_file():
                    continue
                count = self._base_vector_count(base_id)
                if count <= 0:
                    continue
                index = index_factory(ndim=len(vector), metric="cos", dtype="f32")
                index.load(path)
                matches = index.search(
                    array_factory(vector, "float32"),
                    min(count, max(1, min(100, int(limit)))),
                )
                keys = [int(value) for value in matches.keys]
                distances = [float(value) for value in matches.distances]
                mapping = self._chunk_ids_for_keys(keys)
                scored.extend(
                    (mapping[key], max(-1.0, min(1.0, 1.0 - distance)))
                    for key, distance in zip(keys, distances)
                    if key in mapping
                )
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[: max(1, min(100, int(limit)))]

    def status(self) -> dict[str, Any]:
        base = super().status()
        try:
            self._dependencies()
            dependency_available = True
            dependency_error = ""
        except RuntimeError as exc:
            dependency_available = False
            dependency_error = str(exc)
        with self._connection() as connection:
            index_count = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT base_id) FROM knowledge_ann_keys WHERE fingerprint=?",
                    (str(self.provider.fingerprint),),
                ).fetchone()[0]
            )
            mapped_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_ann_keys WHERE fingerprint=?",
                    (str(self.provider.fingerprint),),
                ).fetchone()[0]
            )
        vector_count = int(base.get("vectorCount") or 0)
        stale_count = 0
        for base_id in self._indexed_bases():
            if self._index_file_count(base_id) != self._base_vector_count(base_id):
                stale_count += 1
        base.update(
            {
                "available": dependency_available,
                "degraded": not dependency_available or isinstance(self.provider, HashingEmbeddingProvider),
                "kind": "usearch-hnsw",
                "backend": "usearch",
                "ann": True,
                "scalable": True,
                "indexCount": index_count,
                "mappedVectorCount": mapped_count,
                "projectionConsistent": mapped_count == vector_count and stale_count == 0,
                "staleIndexCount": stale_count,
                "startupRebuiltIndexCount": self._startup_rebuilt,
            }
        )
        if dependency_error or self._startup_error:
            base["reason"] = dependency_error or self._startup_error
            base["degraded"] = True
        return base

    def _ann_rows(self, base_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return list(
                connection.execute(
                    "SELECT a.ann_key, d.vector_json FROM knowledge_ann_keys a "
                    "JOIN knowledge_dense_chunks d ON d.chunk_id=a.chunk_id "
                    "WHERE a.base_id=? AND a.fingerprint=? AND d.fingerprint=? ORDER BY a.ann_key",
                    (base_id, str(self.provider.fingerprint), str(self.provider.fingerprint)),
                ).fetchall()
            )

    def _document_bases(self, document_id: str) -> set[str]:
        with self._connection() as connection:
            return {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT base_id FROM knowledge_ann_keys WHERE document_id=?",
                    (document_id,),
                ).fetchall()
            }

    def _indexed_bases(self) -> list[str]:
        with self._connection() as connection:
            return [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT base_id FROM knowledge_ann_keys WHERE fingerprint=? ORDER BY base_id",
                    (str(self.provider.fingerprint),),
                ).fetchall()
            ]

    def _base_vector_count(self, base_id: str) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_ann_keys WHERE base_id=? AND fingerprint=?",
                    (base_id, str(self.provider.fingerprint)),
                ).fetchone()[0]
            )

    def _index_file_count(self, base_id: str) -> int:
        path = self._index_path(base_id)
        if not path.is_file():
            return 0
        rows = self._ann_rows(base_id)
        if not rows:
            return 0
        try:
            index_factory, _array_factory = self._dependencies()
            vector = json.loads(str(rows[0]["vector_json"]))
            index = index_factory(ndim=len(vector), metric="cos", dtype="f32")
            index.load(path)
            return int(getattr(index, "size", len(index)))
        except Exception:
            return -1

    def _chunk_ids_for_keys(self, keys: Sequence[int]) -> dict[int, str]:
        if not keys:
            return {}
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT ann_key, chunk_id FROM knowledge_ann_keys WHERE ann_key IN "
                f"({', '.join('?' for _ in keys)})",
                list(keys),
            ).fetchall()
        return {int(row["ann_key"]): str(row["chunk_id"]) for row in rows}

    def _index_path(self, base_id: str) -> Path:
        fingerprint_hash = hashlib.sha256(str(self.provider.fingerprint).encode()).hexdigest()[:16]
        safe_base = hashlib.sha256(base_id.encode()).hexdigest()[:24]
        directory = self.index_root / fingerprint_hash
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{safe_base}.usearch"


def dense_index_from_env(
    database_path: Path,
    provider: EmbeddingProvider,
    env: dict[str, str] | None = None,
) -> DenseIndex:
    source = os.environ if env is None else env
    if isinstance(provider, NullEmbeddingProvider):
        return NullDenseIndex()
    try:
        batch_size = max(1, min(128, int(source.get("RAG_IME_EMBEDDING_BATCH_SIZE", "32"))))
    except ValueError:
        batch_size = 32
    backend = source.get("RAG_IME_KNOWLEDGE_DENSE_BACKEND", "usearch").strip().lower()
    if backend in {"usearch", "hnsw", "usearch-hnsw"}:
        try:
            index = USearchDenseIndex(database_path, provider, batch_size=batch_size)
            index._dependencies()
            return index
        except RuntimeError as exc:
            return SqliteDenseIndex(
                database_path,
                provider,
                batch_size=batch_size,
                fallback_from="usearch",
                fallback_reason=str(exc),
            )
    return SqliteDenseIndex(database_path, provider, batch_size=batch_size)


def reciprocal_rank_fusion(
    lexical_ids: Sequence[str],
    dense_ids: Sequence[str],
    *,
    rank_constant: int = 60,
    lexical_weight: float = 1.2,
    dense_weight: float = 1.0,
) -> list[str]:
    scores: dict[str, float] = {}
    for ranking, weight in ((lexical_ids, lexical_weight), (dense_ids, dense_weight)):
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + max(0.0, float(weight)) / (max(1, rank_constant) + rank)
    return sorted(scores, key=lambda item_id: (-scores[item_id], item_id))
