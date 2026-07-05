from __future__ import annotations

import json
import re
import sqlite3
from itertools import combinations

from .embeddings import EmbeddingProvider
from .text_utils import build_fts_document, compact_whitespace, now_ms, token_terms


_TECH_TERMS = {
    "rag",
    "ime",
    "mlx",
    "squirrel",
    "rime",
    "wanxiang",
    "sequencefork",
    "kv",
    "reranker",
    "sqlite",
    "fts5",
    "embedding",
    "predictor",
    "sidecar",
    "memory",
    "candidate",
}
_SENSITIVE_RE = re.compile(
    r"(password|token|api[_ -]?key|bearer|sk-[a-z0-9]{8,}|验证码|身份证|手机号|地址|secret)",
    re.IGNORECASE,
)


def sync_event_to_memory_v2(
    conn: sqlite3.Connection,
    *,
    event_id: int,
    created_at_ms: int,
    source: str,
    committed_text: str,
    recent_context: str,
    preedit: str,
    project: str,
    app: str,
    provider_name: str,
    tags: tuple[str, ...],
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    text = compact_whitespace(committed_text)
    normalized = normalize_text(text)
    privacy_class = "sensitive" if looks_sensitive(text) else "local"
    extracted_tags = extract_tags(
        text=text,
        recent_context=recent_context,
        project=project,
        app=app,
        explicit_tags=tags,
    )
    raw_metadata = {
        "direct_candidate_allowed": False,
        "provider_name": provider_name,
        "source": source,
        "tag_count": len(extracted_tags),
    }
    raw_item_id = upsert_memory_item(
        conn,
        memory_id=f"raw:event:{event_id}",
        kind="raw_event",
        text=text,
        normalized_text=normalized,
        summary=compact_whitespace(recent_context)[:240],
        source_event_id=event_id,
        project=project,
        app=app,
        confidence=0.45,
        quality_score=0.35,
        status="hidden" if privacy_class == "sensitive" else "active",
        privacy_class=privacy_class,
        created_at_ms=created_at_ms,
        updated_at_ms=created_at_ms,
        metadata=raw_metadata,
        tags=extracted_tags if privacy_class != "sensitive" else (),
        embedding_provider=embedding_provider if privacy_class != "sensitive" else None,
    )

    phrase_item_id: int | None = None
    kind = classify_text_kind(text)
    if privacy_class != "sensitive" and kind == "phrase":
        quality_score = 0.65 if "phrase-memory" in {tag.lower() for tag in extracted_tags} else 0.56
        phrase_item_id = upsert_memory_item(
            conn,
            memory_id=f"phrase:{normalized}",
            kind="phrase",
            text=text,
            normalized_text=normalized,
            summary=compact_whitespace(recent_context)[:240],
            source_event_id=event_id,
            project=project,
            app=app,
            confidence=0.7,
            quality_score=quality_score,
            status="active",
            privacy_class="local",
            created_at_ms=created_at_ms,
            updated_at_ms=created_at_ms,
            metadata={
                "direct_candidate_allowed": True,
                "provider_name": provider_name,
                "source": source,
                "raw_memory_id": f"raw:event:{event_id}",
            },
            tags=extracted_tags,
            embedding_provider=embedding_provider,
        )
    return {
        "rawItemId": raw_item_id,
        "phraseItemId": phrase_item_id,
        "privacyClass": privacy_class,
        "kind": kind,
    }


def normalize_text(text: str) -> str:
    return compact_whitespace(text).lower()


def classify_text_kind(text: str) -> str:
    compact = compact_whitespace(text)
    if not compact:
        return "raw_event"
    if 2 <= len(compact) <= 12 and not compact.endswith(("。", "！", "？")):
        return "phrase"
    return "raw_event"


def looks_sensitive(text: str) -> bool:
    return bool(_SENSITIVE_RE.search(compact_whitespace(text)))


def extract_tags(
    *,
    text: str,
    recent_context: str,
    project: str,
    app: str,
    explicit_tags: tuple[str, ...],
) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        tag = compact_whitespace(tag)
        normalized = tag.lower()
        if not tag or normalized in seen:
            return
        seen.add(normalized)
        found.append(tag)

    for tag in explicit_tags:
        add(tag)
    if project:
        add(project)
    if app:
        add(app.split(".")[-1])
    for term in token_terms(f"{text} {recent_context}", max_terms=64):
        if term.lower() in _TECH_TERMS:
            add(term)
        elif 2 <= len(term) <= 12 and not term.isdigit():
            add(term)
    return tuple(found[:24])


def upsert_memory_item(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    kind: str,
    text: str,
    normalized_text: str,
    summary: str,
    source_event_id: int | None,
    project: str,
    app: str,
    confidence: float,
    quality_score: float,
    status: str,
    privacy_class: str,
    created_at_ms: int,
    updated_at_ms: int,
    metadata: dict[str, object],
    tags: tuple[str, ...],
    embedding_provider: EmbeddingProvider | None,
) -> int:
    existing = conn.execute("SELECT id, created_at_ms FROM memory_items WHERE memory_id = ?", (memory_id,)).fetchone()
    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO memory_items(
                memory_id, kind, text, normalized_text, summary, source_event_id,
                project, app, confidence, quality_score, status, privacy_class,
                created_at_ms, updated_at_ms, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                kind,
                text,
                normalized_text,
                summary,
                source_event_id,
                project,
                app,
                confidence,
                quality_score,
                status,
                privacy_class,
                created_at_ms,
                updated_at_ms,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        memory_item_id = int(cur.lastrowid)
    else:
        memory_item_id = int(existing["id"])
        conn.execute(
            """
            UPDATE memory_items
            SET kind = ?, text = ?, normalized_text = ?, summary = ?, source_event_id = ?,
                project = ?, app = ?, confidence = ?, quality_score = ?, status = ?,
                privacy_class = ?, updated_at_ms = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                kind,
                text,
                normalized_text,
                summary,
                source_event_id,
                project,
                app,
                confidence,
                quality_score,
                status,
                privacy_class,
                updated_at_ms,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                memory_item_id,
            ),
        )
    _refresh_item_fts(conn, memory_item_id=memory_item_id, text=text, normalized_text=normalized_text, summary=summary, project=project, app=app, tags=tags)
    _refresh_item_tags(conn, memory_item_id=memory_item_id, tags=tags)
    if embedding_provider is not None and getattr(embedding_provider, "fingerprint", "none") != "none":
        document = build_fts_document(text, summary, project, app, " ".join(tags))
        vector = embedding_provider.embed(document)
        if vector:
            conn.execute(
                """
                INSERT INTO memory_item_vectors(memory_item_id, provider_fingerprint, vector_json, updated_at_ms)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(memory_item_id, provider_fingerprint) DO UPDATE SET
                    vector_json = excluded.vector_json,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (memory_item_id, embedding_provider.fingerprint, json.dumps(vector, separators=(",", ":")), now_ms()),
            )
    return memory_item_id


def _refresh_item_fts(
    conn: sqlite3.Connection,
    *,
    memory_item_id: int,
    text: str,
    normalized_text: str,
    summary: str,
    project: str,
    app: str,
    tags: tuple[str, ...],
) -> None:
    conn.execute("DELETE FROM memory_items_fts WHERE rowid = ?", (memory_item_id,))
    conn.execute(
        """
        INSERT INTO memory_items_fts(rowid, text, normalized_text, summary, project, app, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (memory_item_id, build_fts_document(text), normalized_text, summary, project, app, " ".join(tags)),
    )


def _refresh_item_tags(conn: sqlite3.Connection, *, memory_item_id: int, tags: tuple[str, ...]) -> None:
    conn.execute("DELETE FROM memory_item_tags WHERE memory_item_id = ?", (memory_item_id,))
    tag_rows: list[tuple[int, int]] = []
    for position, tag in enumerate(tags):
        normalized = normalize_text(tag)
        row = conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (tag,)).fetchone()
        if row is None:
            cur = conn.execute(
                """
                INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tag, normalized, infer_tag_type(tag), 0.55, now_ms(), now_ms()),
            )
            tag_id = int(cur.lastrowid)
        else:
            tag_id = int(row["id"])
            conn.execute("UPDATE memory_tags SET updated_at_ms = ? WHERE id = ?", (now_ms(), tag_id))
        conn.execute(
            """
            INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_item_id, tag_id, max(0.3, 1.0 - position * 0.05), position, tag),
        )
        tag_rows.append((position, tag_id))
    for (_, src_tag_id), (_, dst_tag_id) in combinations(tag_rows, 2):
        _upsert_tag_edge(conn, src_tag_id=src_tag_id, dst_tag_id=dst_tag_id)
        _upsert_tag_edge(conn, src_tag_id=dst_tag_id, dst_tag_id=src_tag_id)


def infer_tag_type(tag: str) -> str:
    normalized = normalize_text(tag)
    if normalized in _TECH_TERMS:
        return "tech"
    if "." in tag:
        return "app"
    return "concept"


def _upsert_tag_edge(conn: sqlite3.Connection, *, src_tag_id: int, dst_tag_id: int) -> None:
    conn.execute(
        """
        INSERT INTO memory_tag_edges(src_tag_id, dst_tag_id, edge_type, weight, direction_bias, evidence_count, updated_at_ms, metadata_json)
        VALUES (?, ?, 'cooccur', 1.0, 0.0, 1, ?, '{}')
        ON CONFLICT(src_tag_id, dst_tag_id, edge_type) DO UPDATE SET
            weight = memory_tag_edges.weight + 0.2,
            evidence_count = memory_tag_edges.evidence_count + 1,
            updated_at_ms = excluded.updated_at_ms
        """,
        (src_tag_id, dst_tag_id, now_ms()),
    )
