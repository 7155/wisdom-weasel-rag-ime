from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .embeddings import EmbeddingProvider, NullEmbeddingProvider
from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from .input_event_assembly import recent_complete_input_context
from .memory_ownership import agent_visible_memory_owners
from .text_utils import compact_whitespace, truncate_text


SESSION_MEMORY_RECALL_SCHEMA_VERSION = "rag-ime.session-memory-recall.v1"
_BOOTSTRAP_DEDUPE_VERSION = "v2"
_RELEVANCE_LANES = frozenset(
    {
        "bm25_raw",
        "bm25_tags",
        "vector_raw",
        "vector_tag_boost",
        "tagmemo",
        "feedback",
    }
)
_ACTIVITY_TIMELINE_INTENT_RE = re.compile(
    r"(?:今天|今日|昨天|昨日|前天|最近|刚才|上周|本周|过去|此前|之前|上次|"
    r"时间线|进展|做了什么|做过什么|当前在做|接着|继续)"
)


class SessionMemoryRecallBuilder:
    """Build one query-aware, role-scoped memory pack for an Agent Session."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        project: str = "",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = compact_whitespace(project)
        self.embedding_provider = embedding_provider or NullEmbeddingProvider()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    @staticmethod
    def dedupe_key(session_id: str) -> str:
        return f"memory-bootstrap:{compact_whitespace(session_id)}:{_BOOTSTRAP_DEDUPE_VERSION}"

    def build(
        self,
        session_id: str,
        *,
        role_id: str,
        query_text: str,
        room_ids: Sequence[str] = (),
        max_items: int = 8,
        max_chars: int = 6_400,
        generated_at_ms: int | None = None,
    ) -> dict[str, object]:
        session = compact_whitespace(session_id)
        query = compact_whitespace(query_text)
        role = compact_whitespace(role_id)
        if not session:
            raise ValueError("session_id must not be empty")
        if not query:
            raise ValueError("query_text must not be empty")

        visible_owners = agent_visible_memory_owners(
            project=self.project,
            role_id=role,
            session_id=session,
            room_ids=room_ids,
        )
        bounded_items = max(1, min(int(max_items), 12))
        bounded_chars = max(1_200, min(int(max_chars), 12_000))
        generated = int(
            generated_at_ms
            if generated_at_ms is not None
            else time.time() * 1_000
        )

        with self._connect() as conn:
            recent = recent_complete_input_context(
                conn,
                project=self.project,
                query_text=query,
                baseline_records=6,
                max_records=8,
                token_budget=1_400,
                reserved_tokens=500,
            )
            recent_text = _tail_text(str(recent.get("rendered") or ""), 2_400)
            hybrid_query = HybridRagQuery(
                query_text=query,
                raw_input=recent_text,
                committed_tail=_tail_text(recent_text, 800),
                project=self.project,
                input_mode="agent_session_bootstrap",
                top_k=max(24, bounded_items * 4),
                latency_budget_ms=2_500,
                visible_owners=visible_owners,
            )
            requested_embedding = str(
                getattr(self.embedding_provider, "fingerprint", "none") or "none"
            )
            embedding_fallback = False
            try:
                retrieval = retrieve_hybrid_rag_candidates(
                    conn,
                    hybrid_query,
                    self.embedding_provider,
                )
                effective_embedding = requested_embedding
            except Exception:
                # A local/remote vector endpoint must not suppress the lexical,
                # TagMemo, ownership, and lifecycle lanes of Session startup.
                retrieval = retrieve_hybrid_rag_candidates(
                    conn,
                    hybrid_query,
                    NullEmbeddingProvider(),
                )
                effective_embedding = "none"
                embedding_fallback = requested_embedding != "none"

        selected, omitted = _select_hits(
            retrieval.get("memoryHits"),
            query_text=query,
            max_items=bounded_items,
            max_chars=bounded_chars,
        )
        activated_tags = _selected_activated_tags(retrieval, selected)
        source_ids = [str(item["sourceId"]) for item in selected]
        query_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
        recall_material = json.dumps(
            {
                "sessionId": session,
                "querySha256": query_sha256,
                "sourceIds": source_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload: dict[str, object] = {
            "schemaVersion": SESSION_MEMORY_RECALL_SCHEMA_VERSION,
            "recallId": (
                "session-memory-recall:"
                + hashlib.sha256(recall_material.encode("utf-8")).hexdigest()[:24]
            ),
            "sessionId": session,
            "project": self.project,
            "roleId": role,
            "generatedAtMs": max(0, generated),
            "trigger": "first_user_prompt",
            "query": {
                "preview": truncate_text(query, 240),
                "sha256": query_sha256,
                "recentCompleteInputCount": len(recent.get("records") or []),
                "recentCompleteInputUsedForRetrieval": bool(recent_text),
            },
            "retrieval": {
                "strategy": "vcp_hybrid_book_atom",
                "primaryQuery": truncate_text(
                    str(_mapping(retrieval.get("query")).get("primary") or query),
                    240,
                ),
                "matchedAliases": _string_list(
                    _mapping(retrieval.get("query")).get("matchedAliases"),
                    12,
                ),
                "activatedTags": activated_tags,
                "visibleOwners": [
                    {"ownerKind": kind, "ownerId": owner_id}
                    for kind, owner_id in visible_owners
                ],
                "requestedEmbeddingProvider": requested_embedding,
                "embeddingProvider": effective_embedding,
                "embeddingFallback": embedding_fallback,
            },
            "items": selected,
            "sourceIds": source_ids,
            "budget": {
                "maxItems": bounded_items,
                "maxChars": bounded_chars,
                "usedChars": sum(len(str(item.get("text") or "")) for item in selected),
                "omittedCount": omitted,
            },
            "policy": {
                "priority": "developer",
                "lifecycle": "session",
                "evidenceOnly": True,
                "currentUserMessageWins": True,
                "rawRecentInputInjected": False,
            },
        }
        validate_contract(payload, "session-memory-recall.v1.json")
        return {
            "session_id": session,
            "source_kind": "memory_bootstrap",
            "source_id": str(payload["recallId"]),
            "title": "首问相关个人记忆",
            "summary": (
                f"首问与最近完整输入从角色可见 Book/Atom 中召回 {len(selected)} 条证据。"
            ),
            "payload": payload,
            "lane": "fact",
            # The Pi Session keeps the first turn in its own conversation
            # history. Inject the recall pack once at the first real prompt;
            # repeating it on every turn would duplicate context and tokens.
            "lifecycle": "once",
            "dedupe_key": self.dedupe_key(session),
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _select_hits(
    value: object,
    *,
    query_text: str,
    max_items: int,
    max_chars: int,
) -> tuple[list[dict[str, object]], int]:
    candidates = (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )
    selected: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    type_counts = {"book": 0, "atom": 0}
    used_chars = 0
    eligible_count = 0
    activity_timeline_allowed = bool(
        _ACTIVITY_TIMELINE_INTENT_RE.search(compact_whitespace(query_text))
    )
    for item in candidates:
        doc_type = compact_whitespace(str(item.get("doc_type") or ""))
        metadata = _mapping(item.get("metadata"))
        lanes = _string_list(metadata.get("lanes"), 16)
        tags = _string_list(item.get("tags"), 16)
        if doc_type not in {"book", "atom"}:
            continue
        if bool(metadata.get("archived")):
            continue
        normalized_tags = {tag.casefold() for tag in tags}
        if (
            doc_type == "book"
            and {"daily", "activity-timeline"}.intersection(normalized_tags)
            and not activity_timeline_allowed
        ):
            # Daily activity Books deliberately summarize many unrelated
            # inputs. They help temporal/continuation questions, but their
            # breadth otherwise lets term frequency outrank a focused Topic
            # Book or Atom.
            continue
        if not set(lanes).intersection(_RELEVANCE_LANES):
            continue
        eligible_count += 1
        source_id = compact_whitespace(str(item.get("source_id") or ""))
        text = truncate_text(str(item.get("text") or ""), 760)
        if not source_id or not text or source_id in seen_sources:
            continue
        type_limit = 4 if doc_type == "book" else 5
        if type_counts[doc_type] >= type_limit:
            continue
        if selected and used_chars + len(text) > max_chars:
            continue
        raw_scores = {
            str(key): round(float(score), 6)
            for key, score in _mapping(metadata.get("rawScores")).items()
            if isinstance(score, (int, float))
        }
        selected.append(
            {
                "rank": len(selected) + 1,
                "sourceType": f"memory_{doc_type}",
                "sourceId": source_id,
                "title": truncate_text(
                    str(metadata.get("bookTitle") or metadata.get("kind") or source_id),
                    180,
                ),
                "text": text,
                "score": round(float(item.get("score") or 0.0), 6),
                "confidence": round(float(item.get("confidence") or 0.0), 6),
                "lanes": lanes,
                "rawScores": raw_scores,
                "tags": tags,
                "ownerKind": compact_whitespace(
                    str(metadata.get("ownerKind") or "user")
                ),
                "ownerId": compact_whitespace(
                    str(metadata.get("ownerId") or "default")
                ),
                "evidenceEventIds": [
                    int(event_id)
                    for event_id in item.get("evidence_event_ids") or []
                    if isinstance(event_id, int) and event_id > 0
                ][:16],
            }
        )
        seen_sources.add(source_id)
        type_counts[doc_type] += 1
        used_chars += len(text)
        if len(selected) >= max_items:
            break
    return selected, max(0, eligible_count - len(selected))


def _selected_activated_tags(
    retrieval: Mapping[str, object],
    selected: Sequence[Mapping[str, object]],
) -> list[str]:
    selected_tags = {
        tag.casefold()
        for item in selected
        for tag in _string_list(item.get("tags"), 16)
    }
    return [
        tag
        for tag in _string_list(
            _mapping(retrieval.get("query")).get("activatedTags"),
            32,
        )
        if tag.casefold() in selected_tags
    ][:16]


def _tail_text(value: str, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) <= maximum:
        return text
    return "…" + text[-max(1, maximum - 1) :]


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = compact_whitespace(str(item or ""))
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result
