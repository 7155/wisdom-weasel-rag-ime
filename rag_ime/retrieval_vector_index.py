from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from threading import RLock

from .embeddings import EmbeddingProvider, normalize_vector
from .text_utils import compact_whitespace, now_ms

_VECTOR_CACHE: dict[tuple[str, str], dict[str, tuple[list[float], list[float], list[float]]]] = {}
_VECTOR_CACHE_LOCK = RLock()


def rebuild_retrieval_doc_vectors(
    conn: sqlite3.Connection,
    provider: EmbeddingProvider,
    *,
    project: str = "",
    limit: int = 0,
) -> dict[str, object]:
    """Precompute the three semantic retrieval lanes for active documents."""
    sql = """
        SELECT doc_id, raw_text, tags_text, aliases_text, surface_hints_text,
               query_expansions_text, project, app, metadata_json
        FROM memory_retrieval_docs
        WHERE status = 'active' AND (? = '' OR project = ? OR project = '')
        ORDER BY updated_at_ms DESC
    """
    params: list[object] = [project, project]
    if limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    tag_rows = conn.execute(
        """
        SELECT id, tag
        FROM memory_tags
        WHERE status = 'active' AND source IN ('dsv4', 'user')
        ORDER BY id
        """
    ).fetchall()
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
    lane_texts.extend(str(row["tag"] or "") for row in tag_rows)
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
        conn.execute(
            """
            INSERT INTO memory_retrieval_doc_vectors(
                doc_id, provider_fingerprint, raw_vector_json, tag_vector_json,
                group_vector_json, dimensions, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id, provider_fingerprint) DO UPDATE SET
                raw_vector_json=excluded.raw_vector_json,
                tag_vector_json=excluded.tag_vector_json,
                group_vector_json=excluded.group_vector_json,
                dimensions=excluded.dimensions,
                updated_at_ms=excluded.updated_at_ms
            """,
            (row["doc_id"], provider.fingerprint, _json(raw), _json(tag), _json(group),
             max(len(raw), len(tag), len(group)), now_ms()),
        )
        written += 1
    tag_vectors_written = 0
    for row in tag_rows:
        tag_vector = vector(str(row["tag"] or ""))
        if not tag_vector:
            continue
        conn.execute(
            """
            UPDATE memory_tags
            SET vector_json = ?, model_fingerprint = ?
            WHERE id = ?
            """,
            (_json(tag_vector), provider.fingerprint, int(row["id"])),
        )
        dimensions = max(dimensions, len(tag_vector))
        tag_vectors_written += 1
    conn.commit()
    with _VECTOR_CACHE_LOCK:
        _VECTOR_CACHE.clear()
    return {
        "schemaVersion": "rag-ime.retrieval-vector-index.v1",
        "providerFingerprint": provider.fingerprint,
        "documents": written,
        "tagVectors": tag_vectors_written,
        "uniqueTextsEmbedded": len(cache),
        "dimensions": dimensions,
    }


def load_retrieval_doc_vectors(
    conn: sqlite3.Connection,
    provider_fingerprint: str,
    doc_ids: Iterable[str],
) -> dict[str, tuple[list[float], list[float], list[float]]]:
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
        missing = tuple(doc_id for doc_id in ids if doc_id not in provider_cache)
        step = 500
        for offset in range(0, len(missing), step):
            chunk = missing[offset:offset + step]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"""SELECT doc_id, raw_vector_json, tag_vector_json, group_vector_json
                    FROM memory_retrieval_doc_vectors
                    WHERE provider_fingerprint = ? AND doc_id IN ({placeholders})""",
                (provider_fingerprint, *chunk),
            ).fetchall()
            for row in rows:
                provider_cache[str(row["doc_id"])] = (
                    _vector(row["raw_vector_json"]),
                    _vector(row["tag_vector_json"]),
                    _vector(row["group_vector_json"]),
                )
        return {doc_id: provider_cache[doc_id] for doc_id in ids if doc_id in provider_cache}


def load_tag_vectors(
    conn: sqlite3.Connection,
    provider_fingerprint: str,
    tags: Iterable[str],
) -> dict[str, list[float]]:
    names = tuple(dict.fromkeys(compact_whitespace(str(value)) for value in tags if compact_whitespace(str(value))))
    if not names or not provider_fingerprint:
        return {}
    vectors: dict[str, list[float]] = {}
    step = 200
    for offset in range(0, len(names), step):
        chunk = names[offset:offset + step]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT tag, vector_json
            FROM memory_tags
            WHERE model_fingerprint = ?
              AND status = 'active'
              AND source IN ('dsv4', 'user')
              AND tag IN ({placeholders})
            """,
            (provider_fingerprint, *chunk),
        ).fetchall()
        for row in rows:
            vector = _vector(row["vector_json"])
            if vector:
                vectors[str(row["tag"])] = vector
    return vectors


def build_tag_boosted_query_vector(
    conn: sqlite3.Connection,
    *,
    provider_fingerprint: str,
    query_vector: list[float],
    weighted_tags: Iterable[tuple[str, float]],
    alpha: float = 0.20,
) -> tuple[list[float], dict[str, object]]:
    requested: list[tuple[str, float]] = []
    for tag, energy in weighted_tags:
        name = compact_whitespace(str(tag))
        try:
            weight = float(energy)
        except (TypeError, ValueError):
            continue
        if name and weight > 0.0:
            requested.append((name, min(1.0, weight)))
    safe_alpha = max(0.0, min(0.5, float(alpha)))
    diagnostics: dict[str, object] = {
        "applied": False,
        "alpha": safe_alpha,
        "requestedTagCount": len(requested),
        "tagVectorCount": 0,
        "usedTags": [],
        "reason": "",
    }
    normalized_query = normalize_vector(query_vector)
    if not normalized_query:
        diagnostics["reason"] = "query_vector_empty"
        return [], diagnostics
    if not requested:
        diagnostics["reason"] = "no_activated_tags"
        return normalized_query, diagnostics
    tag_vectors = load_tag_vectors(conn, provider_fingerprint, (tag for tag, _energy in requested))
    centroid = [0.0] * len(normalized_query)
    total_energy = 0.0
    used_tags: list[str] = []
    for tag, energy in requested:
        vector = tag_vectors.get(tag)
        if not vector or len(vector) != len(normalized_query):
            continue
        total_energy += energy
        used_tags.append(tag)
        for index, value in enumerate(vector):
            centroid[index] += energy * float(value)
    diagnostics["tagVectorCount"] = len(used_tags)
    diagnostics["usedTags"] = used_tags
    if total_energy <= 0.0:
        diagnostics["reason"] = "tag_vectors_unavailable"
        return normalized_query, diagnostics
    tag_centroid = normalize_vector([value / total_energy for value in centroid])
    if not tag_centroid:
        diagnostics["reason"] = "tag_centroid_empty"
        return normalized_query, diagnostics
    boosted = normalize_vector([
        (1.0 - safe_alpha) * query_value + safe_alpha * tag_value
        for query_value, tag_value in zip(normalized_query, tag_centroid)
    ])
    if not boosted:
        diagnostics["reason"] = "boost_normalization_failed"
        return normalized_query, diagnostics
    diagnostics["applied"] = safe_alpha > 0.0
    diagnostics["reason"] = "applied" if safe_alpha > 0.0 else "alpha_zero"
    return boosted, diagnostics


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
