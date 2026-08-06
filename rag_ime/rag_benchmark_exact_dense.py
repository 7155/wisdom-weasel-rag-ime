from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Sequence

from .embeddings import EmbeddingProvider, embed_query
from .knowledge_library.dense import SqliteDenseIndex


class BenchmarkExactDenseIndex(SqliteDenseIndex):
    """Deterministic exact scan with benchmark-local in-memory acceleration.

    SQLite remains the persisted projection.  The matrix and query vectors are
    cached only inside one disposable benchmark process so repeated candidate
    evaluation does not turn exact retrieval into a JSON parsing benchmark.
    Production Knowledge continues to use its configured dense backend.
    """

    def __init__(
        self,
        database_path: Path,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
    ) -> None:
        self._benchmark_lock = threading.RLock()
        self._projection_cache: tuple[
            list[str],
            list[str],
            list[str],
            Any,
            Any,
        ] | None = None
        self._query_cache: dict[str, Any] = {}
        self._numpy_available = True
        super().__init__(database_path, provider, batch_size=batch_size)

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[dict[str, Any]],
    ) -> None:
        super().replace_document(document_id, chunks)
        self._invalidate_projection()

    def delete_document(self, document_id: str) -> None:
        super().delete_document(document_id)
        self._invalidate_projection()

    def search(
        self,
        query: str,
        *,
        base_ids: Sequence[str],
        limit: int,
        document_ids: Sequence[str] = (),
    ) -> Sequence[tuple[str, float]]:
        try:
            import numpy as np
        except ImportError:
            self._numpy_available = False
            return super().search(
                query,
                base_ids=base_ids,
                limit=limit,
                document_ids=document_ids,
            )

        with self._benchmark_lock:
            query_vector = self._query_cache.get(query)
            if query_vector is None:
                embedded = embed_query(self.provider, query)
                if not embedded:
                    return ()
                query_vector = np.asarray(embedded, dtype=np.float64)
                self._query_cache[query] = query_vector
            chunk_ids, stored_base_ids, stored_document_ids, matrix, row_norms = (
                self._projection(np)
            )

        if not chunk_ids or query_vector.size == 0 or matrix.size == 0:
            return ()
        dimensions = min(int(query_vector.shape[0]), int(matrix.shape[1]))
        if dimensions <= 0:
            return ()
        selected_bases = set(base_ids)
        selected_documents = set(document_ids)
        selected = [
            index
            for index, (base_id, document_id) in enumerate(
                zip(stored_base_ids, stored_document_ids)
            )
            if (not selected_bases or base_id in selected_bases)
            and (not selected_documents or document_id in selected_documents)
        ]
        if not selected:
            return ()

        indexes = np.asarray(selected, dtype=np.int64)
        bounded_query = query_vector[:dimensions]
        query_norm = float(np.linalg.norm(bounded_query))
        if query_norm <= 0:
            scores = np.zeros(len(selected), dtype=np.float64)
        elif dimensions == int(matrix.shape[1]):
            denominators = row_norms[indexes] * query_norm
            numerators = matrix[indexes] @ bounded_query
            scores = np.divide(
                numerators,
                denominators,
                out=np.zeros_like(numerators),
                where=denominators > 0,
            )
        else:
            selected_matrix = matrix[indexes, :dimensions]
            selected_norms = np.linalg.norm(selected_matrix, axis=1)
            denominators = selected_norms * query_norm
            numerators = selected_matrix @ bounded_query
            scores = np.divide(
                numerators,
                denominators,
                out=np.zeros_like(numerators),
                where=denominators > 0,
            )
        ranked = sorted(
            (
                (chunk_ids[index], float(score))
                for index, score in zip(selected, scores.tolist())
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[: max(1, min(100, int(limit)))]

    def status(self) -> dict[str, Any]:
        result = super().status()
        result.update(
            {
                "benchmarkDeterministicExact": True,
                "benchmarkMatrixCached": self._projection_cache is not None,
                "benchmarkQueryCacheEntries": len(self._query_cache),
                "benchmarkNumpyAcceleration": self._numpy_available,
            }
        )
        return result

    def _invalidate_projection(self) -> None:
        with self._benchmark_lock:
            self._projection_cache = None

    def _projection(self, np: Any) -> tuple[list[str], list[str], list[str], Any, Any]:
        if self._projection_cache is not None:
            return self._projection_cache
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT chunk_id, base_id, document_id, vector_json "
                "FROM knowledge_dense_chunks WHERE fingerprint=? ORDER BY chunk_id",
                (str(self.provider.fingerprint),),
            ).fetchall()
        chunk_ids: list[str] = []
        base_ids: list[str] = []
        document_ids: list[str] = []
        vectors: list[list[float]] = []
        dimensions = 0
        for row in rows:
            try:
                vector = [float(value) for value in json.loads(str(row["vector_json"]))]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not vector:
                continue
            if dimensions == 0:
                dimensions = len(vector)
            if len(vector) != dimensions:
                continue
            chunk_ids.append(str(row["chunk_id"]))
            base_ids.append(str(row["base_id"]))
            document_ids.append(str(row["document_id"]))
            vectors.append(vector)
        matrix = np.asarray(vectors, dtype=np.float64)
        if matrix.ndim != 2:
            matrix = np.empty((0, 0), dtype=np.float64)
        row_norms = (
            np.linalg.norm(matrix, axis=1)
            if matrix.size
            else np.empty((0,), dtype=np.float64)
        )
        self._projection_cache = (
            chunk_ids,
            base_ids,
            document_ids,
            matrix,
            row_norms,
        )
        return self._projection_cache
