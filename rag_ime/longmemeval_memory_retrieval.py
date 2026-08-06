from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from copy import deepcopy
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingProvider, NullEmbeddingProvider, embedding_provider_info
from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from .memory_schema_v2 import ensure_memory_v2_schema
from .retrieval_vector_index import rebuild_retrieval_doc_vectors
from .text_utils import build_fts_document


_GRANULARITIES = frozenset({"session", "turn", "session_turn"})
_MODES = frozenset({"lexical", "dense", "hybrid"})
_CONTENT_PROFILES = frozenset({"official-user", "product-all-turn"})
_DATE_PREFIX = re.compile(r"^(20\d{2})/(\d{2})/(\d{2}).*?(\d{2}):(\d{2})")


class LongMemEvalMemoryIndex:
    """Isolated LongMemEval projection through the production Memory retriever.

    The adapter writes only synthetic/public benchmark Books and retrieval
    projections into its caller-owned SQLite file. It never invokes Knowledge
    services and it never treats benchmark sessions as personal runtime data.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve(strict=False)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        ensure_memory_v2_schema(self.connection)
        self.embedding_provider = embedding_provider or NullEmbeddingProvider()
        self._query_ids: set[str] = set()
        self._content_profile: str | None = None
        self._retrieval_cache: dict[str, dict[str, Any]] = {}
        self._closed = False

    def build(
        self,
        cases: Sequence[Mapping[str, object]],
        *,
        include_turn_index: bool = True,
        build_vectors: bool = False,
        content_profile: str,
    ) -> dict[str, Any]:
        if not cases:
            raise ValueError("LongMemEval Memory cases must not be empty")
        if int(
            self.connection.execute(
                "SELECT COUNT(*) FROM memory_retrieval_docs"
            ).fetchone()[0]
        ):
            raise ValueError("LongMemEval Memory index must be built only once")
        normalized_content_profile = str(content_profile or "").strip().lower()
        if normalized_content_profile not in _CONTENT_PROFILES:
            raise ValueError(
                "content_profile must be official-user or product-all-turn"
            )

        books: list[tuple[object, ...]] = []
        retrieval_docs: list[tuple[object, ...]] = []
        generations: list[tuple[object, ...]] = []
        vector_doc_ids: list[str] = []
        session_documents = 0
        turn_documents = 0
        empty_turns_skipped = 0
        seen_query_ids: set[str] = set()

        for raw_case in cases:
            if str(raw_case.get("system") or "").strip().lower() != "memory":
                raise ValueError("LongMemEval benchmark index accepts Memory cases only")
            query_id = _identifier(raw_case.get("queryId"), "queryId")
            if query_id in seen_query_ids:
                raise ValueError(f"duplicate LongMemEval queryId: {query_id}")
            seen_query_ids.add(query_id)
            sessions = raw_case.get("sessions")
            if not isinstance(sessions, list) or not sessions:
                raise ValueError(f"{query_id}.sessions must be a non-empty array")

            for raw_session in sessions:
                if not isinstance(raw_session, Mapping):
                    raise ValueError(f"{query_id} session must be an object")
                session_id = _identifier(raw_session.get("sessionId"), "sessionId")
                session_date = _text(raw_session.get("date"), "session.date", 500)
                turns = _turns(raw_session.get("turns"), query_id, session_id)
                source_session_id = _identifier(
                    raw_session.get("sourceSessionId") or session_id,
                    "sourceSessionId",
                )
                session_text = _session_text(
                    session_date,
                    turns,
                    content_profile=normalized_content_profile,
                )
                indexed_roles = tuple(
                    dict.fromkeys(
                        str(turn["role"])
                        for turn in turns
                        if normalized_content_profile == "product-all-turn"
                        or turn["role"] == "user"
                    )
                )
                session_doc_id = self._append_book_projection(
                    books=books,
                    retrieval_docs=retrieval_docs,
                    generations=generations,
                    query_id=query_id,
                    granularity="session",
                    session_id=session_id,
                    source_session_id=source_session_id,
                    session_date=session_date,
                    text=session_text,
                    turn_index=None,
                    roles=indexed_roles,
                    content_profile=normalized_content_profile,
                )
                vector_doc_ids.append(session_doc_id)
                session_documents += 1

                if not include_turn_index:
                    continue
                for turn_index, turn in enumerate(turns):
                    if (
                        normalized_content_profile == "official-user"
                        and turn["role"] != "user"
                    ):
                        continue
                    content = str(turn["content"])
                    if not content:
                        empty_turns_skipped += 1
                        continue
                    turn_doc_id = self._append_book_projection(
                        books=books,
                        retrieval_docs=retrieval_docs,
                        generations=generations,
                        query_id=query_id,
                        granularity="turn",
                        session_id=session_id,
                        source_session_id=source_session_id,
                        session_date=session_date,
                        text=_turn_text(
                            session_date,
                            role=str(turn["role"]),
                            content=content,
                            turn_index=turn_index,
                            turn_count=len(turns),
                            content_profile=normalized_content_profile,
                        ),
                        turn_index=turn_index,
                        roles=(str(turn["role"]),),
                        content_profile=normalized_content_profile,
                    )
                    vector_doc_ids.append(turn_doc_id)
                    turn_documents += 1

        self.connection.executemany(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json,
                query_expansions_json, source_event_ids_json,
                memory_atom_ids_json, status, confidence, quality_score,
                created_at_ms, updated_at_ms, metadata_json
            ) VALUES (?, 'benchmark_session', ?, ?, '', '', ?, '', ?, '[]',
                      '[]', '[]', '[]', 'active', 1.0, 1.0, ?, ?, ?)
            """,
            books,
        )
        self.connection.executemany(
            """
            INSERT OR IGNORE INTO memory_source_generations(
                source_type, source_id, generation, updated_at_ms
            ) VALUES ('book', ?, 1, ?)
            """,
            generations,
        )
        self.connection.executemany(
            """
            INSERT INTO memory_retrieval_docs(
                doc_id, doc_type, source_id, raw_text, tags_text, aliases_text,
                surface_hints_text, query_expansions_text, time_key, project,
                app, status, updated_at_ms, metadata_json,
                source_revision, projection_version
            ) VALUES (?, 'book', ?, ?, ?, '', '', '', ?, ?, '', 'active', ?, ?, 1, 1)
            """,
            retrieval_docs,
        )
        self._build_fts_projection()
        self.connection.commit()
        self._query_ids = seen_query_ids
        self._content_profile = normalized_content_profile

        vector_report: dict[str, object]
        if build_vectors:
            if str(getattr(self.embedding_provider, "fingerprint", "none")) == "none":
                raise ValueError("build_vectors requires a configured embedding provider")
            vector_report = rebuild_retrieval_doc_vectors(
                self.connection,
                self.embedding_provider,
                doc_ids=vector_doc_ids,
            )
        else:
            vector_report = {
                "schemaVersion": "rag-ime.retrieval-vector-index.v1",
                "providerFingerprint": str(
                    getattr(self.embedding_provider, "fingerprint", "none")
                ),
                "documents": 0,
                "requestedDocuments": 0,
                "skippedStale": 0,
                "uniqueTextsEmbedded": 0,
                "dimensions": 0,
            }

        return {
            "schemaVersion": "rag-ime.longmemeval-memory-index-build.v1",
            "system": "memory",
            "tool": "memory",
            "contentProfile": normalized_content_profile,
            "caseCount": len(seen_query_ids),
            "sessionDocuments": session_documents,
            "turnDocuments": turn_documents,
            "vectorEligibleDocuments": len(vector_doc_ids),
            "emptyTurnsSkippedFromTurnIndex": empty_turns_skipped,
            "embedding": embedding_provider_info(self.embedding_provider),
            "vectors": vector_report,
            "boundary": self.boundary_receipt(),
        }

    def retrieve(
        self,
        *,
        query_id: str,
        query_text: str,
        config: Mapping[str, object],
    ) -> dict[str, Any]:
        normalized_query_id = _identifier(query_id, "query_id")
        if normalized_query_id not in self._query_ids:
            raise ValueError("query_id is not present in the isolated Memory index")
        normalized_text = _text(query_text, "query_text", 100_000)
        if self._content_profile is None:
            raise ValueError("LongMemEval Memory index has not been built")
        normalized_config = _retrieval_config(config)
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "queryId": normalized_query_id,
                    "queryText": normalized_text,
                    "config": normalized_config,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        cached = self._retrieval_cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)

        if normalized_config["granularity"] == "session_turn":
            result = self._retrieve_multi_granularity(
                query_id=normalized_query_id,
                query_text=normalized_text,
                config=normalized_config,
            )
        else:
            result = self._retrieve_single_granularity(
                query_id=normalized_query_id,
                query_text=normalized_text,
                config=normalized_config,
            )
        self._retrieval_cache[cache_key] = deepcopy(result)
        return result

    def _retrieve_single_granularity(
        self,
        *,
        query_id: str,
        query_text: str,
        config: Mapping[str, object],
    ) -> dict[str, Any]:
        normalized_config = dict(config)
        granularity = str(normalized_config["granularity"])
        mode = str(normalized_config["mode"])
        lanes = {
            "bm25_raw": mode in {"lexical", "hybrid"},
            "bm25_tags": bool(normalized_config["metadataEnabled"]),
            "vector_raw": mode in {"dense", "hybrid"},
            "vector_tag_boost": False,
            "tagmemo": False,
            "time": False,
            "feedback": False,
        }
        top_k = int(normalized_config["topK"])
        query = HybridRagQuery(
            query_text=query_text,
            raw_input=query_text,
            project=_project_id(
                query_id,
                granularity,
                self._content_profile,
            ),
            top_k=max(64, top_k * 16),
            latency_budget_ms=60_000,
            enabled_lanes=tuple(lanes.items()),
            lane_weights=(
                ("bm25_raw", float(normalized_config["lexicalWeight"])),
                ("bm25_tags", float(normalized_config["metadataWeight"])),
                ("vector_raw", float(normalized_config["denseWeight"])),
                ("vector_tag_boost", 0.0),
                ("tagmemo", 0.0),
                ("time", 0.0),
                ("feedback", 0.0),
            ),
        )
        payload = retrieve_hybrid_rag_candidates(
            self.connection,
            query,
            self.embedding_provider,
        )
        threshold = float(normalized_config["threshold"])
        session_ids: list[str] = []
        session_scores: list[float] = []
        seen_sessions: set[str] = set()
        for raw_hit in payload.get("memoryHits") or []:
            if not isinstance(raw_hit, Mapping):
                continue
            score = float(raw_hit.get("score") or 0.0)
            if score < threshold:
                continue
            metadata = raw_hit.get("metadata")
            if not isinstance(metadata, Mapping):
                continue
            session_id = str(metadata.get("benchmarkSessionId") or "").strip()
            if not session_id or session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)
            session_ids.append(session_id)
            session_scores.append(score)
            if len(session_ids) >= top_k:
                break
        return {
            "schemaVersion": "rag-ime.longmemeval-memory-retrieval.v1",
            "system": "memory",
            "tool": "memory",
            "contentProfile": self._content_profile,
            "queryId": query_id,
            "config": normalized_config,
            "sessionIds": session_ids,
            "sessionScores": session_scores,
            "topScore": session_scores[0] if session_scores else 0.0,
            "elapsedMs": int(payload.get("elapsedMs") or 0),
            "lanes": payload.get("lanes") or {},
            "vectorIndexDocuments": int(payload.get("vectorIndexDocuments") or 0),
        }

    def _retrieve_multi_granularity(
        self,
        *,
        query_id: str,
        query_text: str,
        config: Mapping[str, object],
    ) -> dict[str, Any]:
        final_top_k = int(config["topK"])
        candidate_top_k = min(
            100,
            final_top_k * int(config["candidateMultiplier"]),
        )
        shared = {
            **dict(config),
            "topK": candidate_top_k,
            "threshold": 0.0,
        }
        session = self.retrieve(
            query_id=query_id,
            query_text=query_text,
            config={**shared, "granularity": "session"},
        )
        turn = self.retrieve(
            query_id=query_id,
            query_text=query_text,
            config={**shared, "granularity": "turn"},
        )
        fused = _weighted_reciprocal_rank_fusion(
            (
                list(session["sessionIds"]),
                list(turn["sessionIds"]),
            ),
            weights=(
                float(config["sessionWeight"]),
                float(config["turnWeight"]),
            ),
            rrf_k=int(config["fusionRrfK"]),
        )
        threshold = float(config["threshold"])
        accepted = [
            (session_id, score)
            for session_id, score in fused
            if score >= threshold
        ][:final_top_k]
        return {
            "schemaVersion": "rag-ime.longmemeval-memory-retrieval.v1",
            "system": "memory",
            "tool": "memory",
            "contentProfile": self._content_profile,
            "queryId": query_id,
            "config": dict(config),
            "sessionIds": [session_id for session_id, _score in accepted],
            "sessionScores": [score for _session_id, score in accepted],
            "topScore": accepted[0][1] if accepted else 0.0,
            "elapsedMs": int(session["elapsedMs"]) + int(turn["elapsedMs"]),
            "lanes": {
                "session": session["lanes"],
                "turn": turn["lanes"],
                "fusion": {
                    "algorithm": "weighted_rrf",
                    "rrfK": int(config["fusionRrfK"]),
                    "sessionWeight": float(config["sessionWeight"]),
                    "turnWeight": float(config["turnWeight"]),
                    "candidateMultiplier": int(config["candidateMultiplier"]),
                },
            },
            "vectorIndexDocuments": max(
                int(session["vectorIndexDocuments"]),
                int(turn["vectorIndexDocuments"]),
            ),
        }

    def boundary_receipt(self) -> dict[str, Any]:
        domains = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT DISTINCT knowledge_domain FROM memory_retrieval_docs"
            ).fetchall()
        }
        document_library_rows = int(
            self.connection.execute(
                """SELECT COUNT(*) FROM memory_retrieval_docs
                   WHERE knowledge_domain = 'document_library'"""
            ).fetchone()[0]
        )
        knowledge_table_rows = 0
        knowledge_tables: list[str] = []
        for row in self.connection.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name LIKE 'knowledge_%'
               ORDER BY name"""
        ).fetchall():
            table = str(row[0])
            if not re.fullmatch(r"knowledge_[A-Za-z0-9_]+", table):
                continue
            knowledge_tables.append(table)
            knowledge_table_rows += int(
                self.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
        passed = (
            document_library_rows == 0
            and knowledge_table_rows == 0
            and domains.issubset({"legacy", "user_profile_preference"})
        )
        return {
            "schemaVersion": "rag-ime.longmemeval-memory-boundary.v1",
            "system": "memory",
            "tool": "memory",
            "passed": passed,
            "retrievalDomains": sorted(domains),
            "documentLibraryRows": document_library_rows,
            "knowledgeTablesObserved": knowledge_tables,
            "knowledgeTableRows": knowledge_table_rows,
        }

    def close(self) -> None:
        if self._closed:
            return
        self.connection.close()
        self._closed = True

    def _append_book_projection(
        self,
        *,
        books: list[tuple[object, ...]],
        retrieval_docs: list[tuple[object, ...]],
        generations: list[tuple[object, ...]],
        query_id: str,
        granularity: str,
        session_id: str,
        source_session_id: str,
        session_date: str,
        text: str,
        turn_index: int | None,
        roles: tuple[str, ...],
        content_profile: str,
    ) -> str:
        material = (
            f"{query_id}\0{content_profile}\0{granularity}\0{session_id}\0{turn_index}"
        )
        token = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        book_id = f"longmemeval-{token}"
        doc_id = f"book:{book_id}"
        timestamp_ms, date_key = _date_values(session_date)
        metadata = {
            "benchmark": "LongMemEval-S-cleaned",
            "benchmarkQueryId": query_id,
            "benchmarkSessionId": session_id,
            "benchmarkSourceSessionId": source_session_id,
            "benchmarkGranularity": granularity,
            "benchmarkContentProfile": content_profile,
            "benchmarkTurnIndex": turn_index,
            "benchmarkPublicData": True,
            "sessionDate": session_date,
        }
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        project = _project_id(query_id, granularity, content_profile)
        tags = ["longmemeval", "memory", content_profile, granularity, *roles]
        tags_json = json.dumps(tags, ensure_ascii=False)
        tags_text = " ".join((*tags, *date_key.split("-")))
        books.append(
            (
                book_id,
                date_key,
                f"LongMemEval {granularity} {session_id}",
                project,
                tags_json,
                timestamp_ms,
                timestamp_ms,
                metadata_json,
            )
        )
        generations.append((book_id, timestamp_ms))
        retrieval_docs.append(
            (
                doc_id,
                book_id,
                text,
                tags_text,
                date_key,
                project,
                timestamp_ms,
                metadata_json,
            )
        )
        return doc_id

    def _build_fts_projection(self) -> None:
        cursor = self.connection.execute(
            """SELECT rowid, raw_text, tags_text, aliases_text,
                      surface_hints_text, query_expansions_text,
                      time_key, project, app
               FROM memory_retrieval_docs ORDER BY rowid"""
        )
        while True:
            rows = cursor.fetchmany(1_000)
            if not rows:
                break
            self.connection.executemany(
                """
                INSERT INTO memory_retrieval_docs_fts(
                    rowid, raw_text, tags_text, aliases_text,
                    surface_hints_text, query_expansions_text,
                    time_key, project, app
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(row["rowid"]),
                        build_fts_document(str(row["raw_text"] or "")),
                        build_fts_document(str(row["tags_text"] or "")),
                        build_fts_document(str(row["aliases_text"] or "")),
                        build_fts_document(str(row["surface_hints_text"] or "")),
                        build_fts_document(str(row["query_expansions_text"] or "")),
                        build_fts_document(str(row["time_key"] or "")),
                        build_fts_document(str(row["project"] or "")),
                        build_fts_document(str(row["app"] or "")),
                    )
                    for row in rows
                ],
            )


def _retrieval_config(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("retrieval config must be an object")
    granularity = str(value.get("granularity") or "session").strip().lower()
    mode = str(value.get("mode") or "lexical").strip().lower()
    if granularity not in _GRANULARITIES:
        raise ValueError("granularity must be session, turn, or session_turn")
    if mode not in _MODES:
        raise ValueError("mode must be lexical, dense, or hybrid")
    top_k = _bounded_int(value.get("topK", 10), "topK", 1, 100)
    threshold = _bounded_float(value.get("threshold", 0.0), "threshold", 0.0, 100.0)
    return {
        "granularity": granularity,
        "mode": mode,
        "topK": top_k,
        "threshold": threshold,
        "lexicalWeight": _bounded_float(
            value.get("lexicalWeight", 1.0), "lexicalWeight", 0.0, 10.0
        ),
        "denseWeight": _bounded_float(
            value.get("denseWeight", 1.0), "denseWeight", 0.0, 10.0
        ),
        "metadataEnabled": bool(value.get("metadataEnabled", False)),
        "metadataWeight": _bounded_float(
            value.get("metadataWeight", 0.5), "metadataWeight", 0.0, 10.0
        ),
        "sessionWeight": _bounded_float(
            value.get("sessionWeight", 1.0), "sessionWeight", 0.01, 10.0
        ),
        "turnWeight": _bounded_float(
            value.get("turnWeight", 1.0), "turnWeight", 0.01, 10.0
        ),
        "fusionRrfK": _bounded_int(
            value.get("fusionRrfK", 60), "fusionRrfK", 1, 1_000
        ),
        "candidateMultiplier": _bounded_int(
            value.get("candidateMultiplier", 2), "candidateMultiplier", 1, 10
        ),
    }


def _weighted_reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    weights: Sequence[float],
    rrf_k: int,
) -> list[tuple[str, float]]:
    if not rankings or len(rankings) != len(weights):
        raise ValueError("weighted RRF requires one positive weight per ranking")
    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    sequence = 0
    for ranking, weight in zip(rankings, weights, strict=True):
        if not math.isfinite(float(weight)) or float(weight) <= 0:
            raise ValueError("weighted RRF weights must be positive")
        seen: set[str] = set()
        for rank, raw_session_id in enumerate(ranking, start=1):
            session_id = str(raw_session_id or "").strip()
            if not session_id or session_id in seen:
                continue
            seen.add(session_id)
            scores[session_id] = scores.get(session_id, 0.0) + float(weight) / (
                rrf_k + rank
            )
            best_rank[session_id] = min(best_rank.get(session_id, rank), rank)
            if session_id not in first_seen:
                first_seen[session_id] = sequence
                sequence += 1
    return [
        (session_id, scores[session_id])
        for session_id in sorted(
            scores,
            key=lambda item: (
                -scores[item],
                best_rank[item],
                first_seen[item],
                item,
            ),
        )
    ]


def _turns(value: object, query_id: str, session_id: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{query_id}.{session_id}.turns must be a non-empty array")
    result: list[dict[str, object]] = []
    for raw_turn in value:
        if not isinstance(raw_turn, Mapping):
            raise ValueError(f"{query_id}.{session_id} turn must be an object")
        role = str(raw_turn.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            raise ValueError(f"{query_id}.{session_id} turn role is invalid")
        content = str(raw_turn.get("content") or "").strip()
        result.append(
            {
                "role": role,
                "content": content,
                "hasAnswer": raw_turn.get("hasAnswer") is True,
            }
        )
    if not any(str(turn["content"]) for turn in result):
        raise ValueError(f"{query_id}.{session_id} contains no indexable turn")
    return result


def _session_text(
    session_date: str,
    turns: Sequence[Mapping[str, object]],
    *,
    content_profile: str,
) -> str:
    if content_profile == "official-user":
        return " ".join(
            str(turn.get("content") or "")
            for turn in turns
            if turn.get("role") == "user" and str(turn.get("content") or "")
        )
    lines = [f"Session date: {session_date}"]
    for turn in turns:
        content = str(turn.get("content") or "")
        if content:
            lines.append(f"{str(turn['role']).title()}: {content}")
    return "\n".join(lines)


def _turn_text(
    session_date: str,
    *,
    role: str,
    content: str,
    turn_index: int,
    turn_count: int,
    content_profile: str,
) -> str:
    if content_profile == "official-user":
        return content
    return (
        f"Session date: {session_date}\n"
        f"Turn: {turn_index + 1}/{turn_count}\n"
        f"{role.title()}: {content}"
    )


def _date_values(value: str) -> tuple[int, str]:
    match = _DATE_PREFIX.match(value)
    if match is None:
        token = hashlib.sha256(value.encode("utf-8")).digest()
        return max(1, int.from_bytes(token[:6], "big")), value[:100]
    year, month, day, hour, minute = (int(item) for item in match.groups())
    parsed = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1_000), parsed.date().isoformat()


def _project_id(query_id: str, granularity: str, content_profile: str) -> str:
    return f"longmemeval:{query_id}:{content_profile}:{granularity}"


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 300 or any(ord(character) < 32 for character in text):
        raise ValueError(f"{field} must be a stable identifier")
    return text


def _text(value: object, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return text


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be from {minimum} to {maximum}")
    return result


def _bounded_float(
    value: object,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{field} must be from {minimum} to {maximum}")
    return result


__all__ = ["LongMemEvalMemoryIndex"]
