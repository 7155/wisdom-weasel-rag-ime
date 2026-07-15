from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from ..embeddings import EmbeddingProvider, cosine_similarity, embed_query


class DenseIndex(Protocol):
    """Optional projection index. SQLite remains the canonical content store."""

    def replace_document(self, document_id: str, chunks: Sequence[dict[str, Any]]) -> None:
        ...

    def delete_document(self, document_id: str) -> None:
        ...

    def search(self, query: str, *, base_ids: Sequence[str], limit: int) -> Sequence[tuple[str, float]]:
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

    def search(self, query: str, *, base_ids: Sequence[str], limit: int) -> Sequence[tuple[str, float]]:
        return ()

    def status(self) -> dict[str, Any]:
        return {"available": False, "degraded": True, "reason": self.reason}


class SqliteDenseIndex:
    """Persistent local vector projection backed by the document library SQLite file."""

    def __init__(self, database_path: Path, provider: EmbeddingProvider):
        self.database_path = Path(database_path)
        self.provider = provider
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
        for chunk in chunks:
            vector = self.provider.embed(str(chunk.get("content") or ""))
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

    def search(self, query: str, *, base_ids: Sequence[str], limit: int) -> Sequence[tuple[str, float]]:
        vector = embed_query(self.provider, query)
        if not vector:
            return ()
        params: list[Any] = [str(self.provider.fingerprint)]
        filter_sql = ""
        if base_ids:
            filter_sql = f" AND base_id IN ({', '.join('?' for _ in base_ids)})"
            params.extend(base_ids)
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
        return {
            "available": True,
            "degraded": False,
            "kind": "sqlite-vector-projection",
            "fingerprint": str(self.provider.fingerprint),
            "vectorCount": count,
        }


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
