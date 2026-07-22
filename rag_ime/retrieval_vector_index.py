from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from threading import RLock

from .embeddings import EmbeddingProvider
from .text_utils import compact_whitespace, now_ms

VectorLanes = tuple[list[float], list[float], list[float]]
VectorCacheToken = tuple[int, int, int]
_VECTOR_CACHE: dict[
    tuple[str, str],
    dict[str, tuple[VectorCacheToken, VectorLanes]],
] = {}
_VECTOR_CACHE_LOCK = RLock()


def rebuild_retrieval_doc_vectors(
    conn: sqlite3.Connection,
    provider: EmbeddingProvider,
    *,
    project: str = "",
    limit: int = 0,
    doc_ids: Iterable[str] | None = None,
) -> dict[str, object]:
    """Precompute vector lanes with a source-revision CAS write."""
    restricted = doc_ids is not None
    requested_ids = tuple(
        dict.fromkeys(str(value) for value in (doc_ids or ()) if value)
    )
    if restricted and not requested_ids:
        return {
            "schemaVersion": "rag-ime.retrieval-vector-index.v1",
            "providerFingerprint": provider.fingerprint,
            "documents": 0,
            "requestedDocuments": 0,
            "skippedStale": 0,
            "uniqueTextsEmbedded": 0,
            "dimensions": 0,
        }
    sql = """
        SELECT doc_id, raw_text, tags_text, aliases_text, surface_hints_text,
               query_expansions_text, project, app, metadata_json,
               source_revision, projection_version
        FROM memory_retrieval_docs
        WHERE status = 'active' AND (? = '' OR project = ? OR project = '')
    """
    params: list[object] = [project, project]
    if restricted:
        sql += f" AND doc_id IN ({','.join('?' for _ in requested_ids)})"
        params.extend(requested_ids)
    sql += " ORDER BY updated_at_ms DESC"
    if limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    cache: dict[str, list[float]] = {}

    lane_texts: list[str] = []
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        lane_texts.extend([
            str(row["raw_text"] or ""),
            " ".join(str(row[key] or "") for key in (
                "tags_text", "aliases_text", "surface_hints_text", "query_expansions_text"
            )),
            " ".join(filter(None, (
                str(metadata.get("contextGroupId") or metadata.get("context_group_id") or ""),
                str(row["project"] or ""), str(row["app"] or ""),
            ))),
        ])
    unique_texts = list(dict.fromkeys(compact_whitespace(text) for text in lane_texts if compact_whitespace(text)))
    embed_many = getattr(provider, "embed_many", None)
    if callable(embed_many) and unique_texts:
        cache.update(zip(unique_texts, embed_many(unique_texts)))

    def vector(text: str) -> list[float]:
        normalized = compact_whitespace(text)
        if not normalized:
            return []
        if normalized not in cache:
            cache[normalized] = provider.embed(normalized)
        return cache[normalized]

    written = 0
    skipped_stale = 0
    dimensions = 0
    for row in rows:
        metadata = _metadata(row["metadata_json"])
        raw = vector(str(row["raw_text"] or ""))
        tag = vector(" ".join(str(row[key] or "") for key in (
            "tags_text", "aliases_text", "surface_hints_text", "query_expansions_text"
        )))
        group = vector(" ".join(filter(None, (
            str(metadata.get("contextGroupId") or metadata.get("context_group_id") or ""),
            str(row["project"] or ""), str(row["app"] or ""),
        ))))
        dimensions = max(dimensions, len(raw), len(tag), len(group))
        built_at = now_ms()
        write = conn.execute(
            """
            INSERT INTO memory_retrieval_doc_vectors(
                doc_id, provider_fingerprint, raw_vector_json, tag_vector_json,
                group_vector_json, dimensions, source_revision,
                projection_version, built_at_ms, updated_at_ms
            )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE EXISTS (
                SELECT 1
                FROM memory_retrieval_docs AS current_doc
                WHERE current_doc.doc_id = ?
                  AND current_doc.status = 'active'
                  AND current_doc.source_revision = ?
                  AND current_doc.projection_version = ?
            )
            ON CONFLICT(doc_id, provider_fingerprint) DO UPDATE SET
                raw_vector_json=excluded.raw_vector_json,
                tag_vector_json=excluded.tag_vector_json,
                group_vector_json=excluded.group_vector_json,
                dimensions=excluded.dimensions,
                source_revision=excluded.source_revision,
                projection_version=excluded.projection_version,
                built_at_ms=excluded.built_at_ms,
                updated_at_ms=excluded.updated_at_ms
            WHERE EXISTS (
                SELECT 1
                FROM memory_retrieval_docs AS current_doc
                WHERE current_doc.doc_id = excluded.doc_id
                  AND current_doc.status = 'active'
                  AND current_doc.source_revision = excluded.source_revision
                  AND current_doc.projection_version = excluded.projection_version
            )
            """,
            (
                row["doc_id"],
                provider.fingerprint,
                _json(raw),
                _json(tag),
                _json(group),
                max(len(raw), len(tag), len(group)),
                int(row["source_revision"]),
                int(row["projection_version"]),
                built_at,
                built_at,
                row["doc_id"],
                int(row["source_revision"]),
                int(row["projection_version"]),
            ),
        )
        if write.rowcount == 1:
            written += 1
        else:
            skipped_stale += 1
    if restricted:
        active_ids = {str(row["doc_id"]) for row in rows}
        removed_ids = tuple(doc_id for doc_id in requested_ids if doc_id not in active_ids)
        if removed_ids:
            conn.executemany(
                """
                DELETE FROM memory_retrieval_doc_vectors
                WHERE doc_id = ? AND provider_fingerprint = ?
                """,
                ((doc_id, provider.fingerprint) for doc_id in removed_ids),
            )
    conn.commit()
    with _VECTOR_CACHE_LOCK:
        _VECTOR_CACHE.clear()
    return {
        "schemaVersion": "rag-ime.retrieval-vector-index.v1",
        "providerFingerprint": provider.fingerprint,
        "documents": written,
        "requestedDocuments": len(requested_ids) if restricted else len(rows),
        "skippedStale": skipped_stale,
        "uniqueTextsEmbedded": len(cache),
        "dimensions": dimensions,
    }


def load_retrieval_doc_vectors(
    conn: sqlite3.Connection,
    provider_fingerprint: str,
    doc_ids: Iterable[str],
) -> dict[str, VectorLanes]:
    ids = tuple(dict.fromkeys(str(value) for value in doc_ids if value))
    if not ids:
        return {}
    cache_key = (provider_fingerprint, _database_cache_identity(conn))
    with _VECTOR_CACHE_LOCK:
        provider_cache = _VECTOR_CACHE.get(cache_key)
        if provider_cache is None:
            if len(_VECTOR_CACHE) >= 4:
                _VECTOR_CACHE.pop(next(iter(_VECTOR_CACHE)))
            provider_cache = {}
            _VECTOR_CACHE[cache_key] = provider_cache
        step = 500
        visible_ids: set[str] = set()
        for offset in range(0, len(ids), step):
            chunk = ids[offset:offset + step]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                    SELECT v.doc_id, v.raw_vector_json, v.tag_vector_json,
                           v.group_vector_json, v.source_revision,
                           v.projection_version, v.built_at_ms
                    FROM memory_retrieval_doc_vectors AS v
                    JOIN memory_retrieval_docs AS d ON d.doc_id = v.doc_id
                    WHERE v.provider_fingerprint = ?
                      AND v.doc_id IN ({placeholders})
                      AND d.status = 'active'
                      AND v.source_revision = d.source_revision
                      AND v.projection_version = d.projection_version
                    """,
                (provider_fingerprint, *chunk),
            ).fetchall()
            for row in rows:
                doc_id = str(row["doc_id"])
                visible_ids.add(doc_id)
                token = (
                    int(row["source_revision"]),
                    int(row["projection_version"]),
                    int(row["built_at_ms"]),
                )
                cached = provider_cache.get(doc_id)
                if cached is None or cached[0] != token:
                    provider_cache[doc_id] = (
                        token,
                        (
                            _vector(row["raw_vector_json"]),
                            _vector(row["tag_vector_json"]),
                            _vector(row["group_vector_json"]),
                        ),
                    )
        for doc_id in ids:
            if doc_id not in visible_ids:
                provider_cache.pop(doc_id, None)
        return {
            doc_id: provider_cache[doc_id][1]
            for doc_id in ids
            if doc_id in provider_cache
        }


def warm_retrieval_doc_vector_cache(
    conn: sqlite3.Connection,
    provider_fingerprint: str,
    *,
    project: str = "",
) -> dict[str, object]:
    started = time.perf_counter()
    rows = conn.execute(
        """
        SELECT d.doc_id
        FROM memory_retrieval_docs d
        JOIN memory_retrieval_doc_vectors v
          ON v.doc_id = d.doc_id AND v.provider_fingerprint = ?
         AND v.source_revision = d.source_revision
         AND v.projection_version = d.projection_version
        WHERE d.status = 'active'
          AND (? = '' OR d.project = ? OR d.project = '')
        ORDER BY d.doc_id
        """,
        (provider_fingerprint, project, project),
    ).fetchall()
    doc_ids = tuple(str(row["doc_id"]) for row in rows)
    vectors = load_retrieval_doc_vectors(conn, provider_fingerprint, doc_ids)
    return {
        "schemaVersion": "rag-ime.retrieval-vector-cache-warmup.v1",
        "providerFingerprint": provider_fingerprint,
        "documents": len(vectors),
        "elapsedMs": int((time.perf_counter() - started) * 1000),
        "ok": len(vectors) == len(doc_ids),
    }


def _metadata(raw: object) -> dict[str, object]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _database_cache_identity(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is not None:
        path = str(row[2] or "")
        if path:
            return path
    return f"memory:{id(conn)}"


def _vector(raw: object) -> list[float]:
    try:
        values = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return [float(value) for value in values] if isinstance(values, list) else []


def _json(values: list[float]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))
