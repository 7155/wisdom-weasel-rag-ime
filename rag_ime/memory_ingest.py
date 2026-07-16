from __future__ import annotations

import json
import re
import sqlite3

from .embeddings import EmbeddingProvider
from .text_utils import build_fts_document, compact_whitespace, now_ms


_TECH_TERMS = {
    "rag",
    "ime",
    "mlx",
    "squirrel",
    "rime",
    "sqlite",
    "fts5",
    "embedding",
    "predictor",
    "sidecar",
    "memory",
}
_CURATED_IMPORT_SIGNALS = {"compiled-memory", "compiled-phrase", "curated", "phrase-memory", "stable-memory"}
_RETRIEVAL_TAG_SOURCES = {"curated_import", "dsv4", "user"}
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
    context_group_id: str = "",
    context_group_level: str = "app",
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    text = compact_whitespace(committed_text)
    normalized = normalize_text(text)
    privacy_class = "sensitive" if looks_sensitive(text) else "local"
    source_tags = extract_tags(
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
        "source_tags": list(source_tags),
        "semantic_tags_pending": privacy_class != "sensitive",
        "contextGroupId": compact_whitespace(context_group_id),
        "contextGroupLevel": compact_whitespace(context_group_level) or "app",
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
        # Raw input is evidence for the periodic organizer, not a retrieval
        # document. DSV4 must clean it before anything enters semantic memory.
        status="hidden",
        privacy_class=privacy_class,
        created_at_ms=created_at_ms,
        updated_at_ms=created_at_ms,
        metadata=raw_metadata,
        tags=(),
        embedding_provider=None,
    )

    phrase_item_id: int | None = None
    curated_item_id: int | None = None
    normalized_source_tags = {normalize_text(tag) for tag in tags}
    curated_import = bool(normalized_source_tags & _CURATED_IMPORT_SIGNALS) and privacy_class != "sensitive"
    phrase_import = bool(normalized_source_tags & {"compiled-phrase", "phrase-memory"})
    stable_import = bool(normalized_source_tags & {"compiled-memory", "stable-memory"}) or (
        "curated" in normalized_source_tags and not phrase_import
    )
    if curated_import:
        curated_metadata = {
            "direct_candidate_allowed": True,
            "source": "explicit_curated_import",
            "source_tags": list(source_tags),
            "contextGroupId": compact_whitespace(context_group_id),
            "contextGroupLevel": compact_whitespace(context_group_level) or "app",
        }
        if stable_import:
            curated_item_id = upsert_memory_item(
                conn,
                memory_id=f"event:{event_id}",
                kind="stable_memory",
                text=text,
                normalized_text=normalized,
                summary=compact_whitespace(recent_context)[:240],
                source_event_id=event_id,
                project=project,
                app=app,
                confidence=0.75,
                quality_score=0.75,
                status="approved",
                privacy_class="local",
                created_at_ms=created_at_ms,
                updated_at_ms=created_at_ms,
                metadata=curated_metadata,
                tags=source_tags,
                embedding_provider=embedding_provider,
                tag_source="curated_import",
            )
        if phrase_import and 2 <= len(text) <= 40:
            phrase_item_id = upsert_memory_item(
                conn,
                memory_id=f"phrase:{normalized}",
                kind="phrase",
                text=text,
                normalized_text=normalized,
                summary="explicit curated phrase import",
                source_event_id=event_id,
                project=project,
                app=app,
                confidence=0.8,
                quality_score=0.8,
                status="active",
                privacy_class="local",
                created_at_ms=created_at_ms,
                updated_at_ms=created_at_ms,
                metadata=curated_metadata,
                tags=source_tags,
                embedding_provider=embedding_provider,
                tag_source="curated_import",
            )
    kind = classify_text_kind(text)
    return {
        "rawItemId": raw_item_id,
        "curatedItemId": curated_item_id,
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
    # These are source metadata only. Semantic tags are exclusively produced
    # by the offline organizer, otherwise Chinese n-grams pollute both the
    # notebook and retrieval lanes.
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
    tag_source: str = "legacy_auto",
    owner_kind: str = "user",
    owner_id: str = "default",
) -> int:
    existing = conn.execute(
        "SELECT id, created_at_ms, owner_kind, owner_id FROM memory_items WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    if existing is not None and (
        str(existing["owner_kind"] or "user"),
        str(existing["owner_id"] or "default"),
    ) != (owner_kind, owner_id):
        raise ValueError("memory item id is already owned by another scope")
    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO memory_items(
                memory_id, kind, text, normalized_text, summary, source_event_id,
                project, app, confidence, quality_score, status, privacy_class,
                owner_kind, owner_id, created_at_ms, updated_at_ms, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                owner_kind,
                owner_id,
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
                privacy_class = ?, owner_kind = ?, owner_id = ?,
                updated_at_ms = ?, metadata_json = ?
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
                owner_kind,
                owner_id,
                updated_at_ms,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                memory_item_id,
            ),
        )
    retrieval_eligible = status in {"active", "approved"} and privacy_class != "sensitive"
    retrieval_tags = tags if tag_source in _RETRIEVAL_TAG_SOURCES else ()
    if retrieval_eligible:
        _refresh_item_fts(
            conn,
            memory_item_id=memory_item_id,
            text=text,
            normalized_text=normalized_text,
            summary=summary,
            project=project,
            app=app,
            tags=retrieval_tags,
        )
    else:
        # The raw ledger is consumed by the periodic organizer only. Keeping
        # hidden source text out of both indexes makes it impossible for BM25
        # or vector retrieval to bypass the DSV4 cleaning/governance step.
        conn.execute("DELETE FROM memory_items_fts WHERE rowid = ?", (memory_item_id,))
        conn.execute("DELETE FROM memory_item_vectors WHERE memory_item_id = ?", (memory_item_id,))
    _refresh_item_tags(conn, memory_item_id=memory_item_id, tags=tags, source=tag_source)
    if retrieval_eligible and embedding_provider is not None and getattr(embedding_provider, "fingerprint", "none") != "none":
        document = build_fts_document(text, summary, project, app, " ".join(retrieval_tags))
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


def _refresh_item_tags(
    conn: sqlite3.Connection,
    *,
    memory_item_id: int,
    tags: tuple[str, ...],
    source: str,
) -> None:
    conn.execute("DELETE FROM memory_item_tags WHERE memory_item_id = ?", (memory_item_id,))
    for position, tag in enumerate(tags):
        normalized = normalize_text(tag)
        row = conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (tag,)).fetchone()
        if row is None:
            cur = conn.execute(
                """
                INSERT INTO memory_tags(
                    tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms,
                    description, source, status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, '{}')
                """,
                (
                    tag,
                    normalized,
                    infer_tag_type(tag),
                    0.55,
                    now_ms(),
                    now_ms(),
                    source,
                    "active" if source in _RETRIEVAL_TAG_SOURCES else "hidden",
                ),
            )
            tag_id = int(cur.lastrowid)
        else:
            tag_id = int(row["id"])
            conn.execute(
                """
                UPDATE memory_tags
                SET updated_at_ms = ?,
                    source = CASE WHEN ? IN ('curated_import', 'dsv4', 'user') THEN ? ELSE source END,
                    status = CASE WHEN ? IN ('curated_import', 'dsv4', 'user') THEN 'active' ELSE status END
                WHERE id = ?
                """,
                (now_ms(), source, source, source, tag_id),
            )
        conn.execute(
            """
            INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_item_id, tag_id, max(0.3, 1.0 - position * 0.05), position, tag),
        )


def infer_tag_type(tag: str) -> str:
    normalized = normalize_text(tag)
    if normalized in _TECH_TERMS:
        return "tech"
    if "." in tag:
        return "app"
    return "concept"
