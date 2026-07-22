#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.db import apply_database_migrations
from rag_ime.embeddings import EmbeddingProvider, MlxBertEmbeddingProvider
from rag_ime.hybrid_rag_models import HybridRagHit, HybridRagQuery
from rag_ime.hybrid_rag_ranker import (
    METADATA_FAMILY_LANES,
    rank_hybrid_hits_to_memory_hits,
)
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_projection_consistency import (
    repair_superseded_memory_residuals,
)
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.retrieval_vector_index import (
    load_retrieval_doc_vectors,
    rebuild_retrieval_doc_vectors,
)
from rag_ime.retrieval_quality_evaluation import evaluate_retrieval_quality
from rag_ime.text_utils import compact_whitespace, token_terms


SCHEMA_VERSION = "rag-ime.memory-consistency-eval.v2"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate memory projection consistency on a private DB copy."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument(
        "--post-apply-db",
        type=Path,
        help="Optionally verify the repaired runtime DB in read-only mode.",
    )
    parser.add_argument("--max-queries", type=int, default=200)
    parser.add_argument(
        "--mlx-model",
        type=Path,
        help="Local MLX BERT model used to run the real vector lanes.",
    )
    parser.add_argument("--mlx-query-prefix", default="")
    parser.add_argument("--mlx-document-prefix", default="")
    parser.add_argument("--mlx-bits", type=int, default=8)
    parser.add_argument("--mlx-group-size", type=int, default=32)
    args = parser.parse_args()
    embedding_provider = (
        MlxBertEmbeddingProvider(
            model=str(args.mlx_model.expanduser()),
            query_prefix=args.mlx_query_prefix,
            document_prefix=args.mlx_document_prefix,
            bits=max(0, int(args.mlx_bits)),
            group_size=max(1, int(args.mlx_group_size)),
            cache_size=max(256, int(args.max_queries) * 3),
        )
        if args.mlx_model is not None
        else None
    )

    report = evaluate(
        args.db.expanduser(),
        project=compact_whitespace(args.project),
        max_queries=max(1, min(int(args.max_queries), 500)),
        embedding_provider=embedding_provider,
        post_apply_db=(
            args.post_apply_db.expanduser() if args.post_apply_db is not None else None
        ),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(_markdown(report), encoding="utf-8")
    return 0


def evaluate(
    db_path: Path,
    *,
    project: str,
    max_queries: int,
    embedding_provider: EmbeddingProvider | None = None,
    post_apply_db: Path | None = None,
) -> dict[str, object]:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="rag-ime-memory-eval-") as tmp:
        copied_path = Path(tmp) / "evaluation.sqlite"
        with closing(
            sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        ) as source, closing(sqlite3.connect(copied_path)) as target:
            source.backup(target)

        with closing(sqlite3.connect(copied_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            migration = apply_database_migrations(conn)
            baseline = _consistency_counts(conn)
            repair = repair_superseded_memory_residuals(conn)
            rebuild = rebuild_retrieval_docs(conn, project=project)
            conn.commit()
            after = _consistency_counts(conn)
            ranking = _metadata_family_ablation(
                conn,
                project=project,
                max_queries=max_queries,
                embedding_provider=embedding_provider,
            )
            retrieval_quality = evaluate_retrieval_quality(
                conn,
                project=project,
                embedding_provider=embedding_provider,
                max_cases_per_suite=max_queries,
            )
            vector_actual = _actual_vector_gate_check(conn)
            cache_gate = _cache_gate_check(conn)
            purpose = _purpose_profile_check(conn)

        cas_gate = _cas_gate_check(Path(tmp) / "cas.sqlite")
        post_apply = _post_apply_check(post_apply_db)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAtMs": int(time.time() * 1000),
        "database": {
            "sourceFile": db_path.name,
            "evaluationMutatedSourceDatabase": False,
            "evaluationUsedSQLiteBackup": True,
            "liveRepairAppliedSeparately": post_apply_db is not None,
            "project": project,
        },
        "migration": {
            "appliedVersions": list(migration.applied_versions),
            "currentVersion": migration.current_version,
        },
        "consistency": {
            "beforeRepair": baseline,
            "repair": repair,
            "rebuild": {
                "documents": int(rebuild.get("docCount") or 0),
                "changedDocuments": len(rebuild.get("changedDocIds") or []),
                "removedDocuments": len(rebuild.get("removedDocIds") or []),
            },
            "afterRepair": after,
        },
        "vectorRevisionGates": {
            "actualData": vector_actual,
            "cacheInvalidationInjection": cache_gate,
            "casLateWriterInjection": cas_gate,
        },
        "metadataFamilyAblation": ranking,
        "retrievalQuality": retrieval_quality,
        "purposeAndCapture": {
            **purpose,
            "activeCaptureHints": after["activeCaptureHints"],
        },
        "postApplyVerification": post_apply,
        "limitations": [
            "metadata self-retrieval is a proxy derived from stored metadata, not a human relevance label",
            "linked user inputs and supersession history are weak supervision, not human relevance judgments",
            "the tuning/holdout evaluation supports parameter selection but does not replace a manually labeled production benchmark",
            "private query text, memory text, and raw identifiers are intentionally omitted",
        ],
        "elapsedMs": int((time.perf_counter() - started) * 1000),
    }


def _consistency_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "activeAtomDocsWithNoncurrentSource": _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM memory_retrieval_docs AS doc
            LEFT JOIN memory_atoms AS atom ON atom.id = doc.source_id
            WHERE doc.status = 'active' AND doc.doc_type = 'atom'
              AND (
                  atom.id IS NULL OR atom.status NOT IN ('active', 'approved')
                  OR atom.claim_state != 'current'
              )
            """,
        ),
        "retrievalBookDocsWithNoncurrentAtoms": _scalar(
            conn,
            """
            SELECT COUNT(DISTINCT doc.doc_id)
            FROM memory_retrieval_docs AS doc
            JOIN memory_books AS book ON book.book_id = doc.source_id
            JOIN json_each(book.memory_atom_ids_json) AS member
            LEFT JOIN memory_atoms AS atom
              ON atom.id = CAST(member.value AS TEXT)
             AND atom.status IN ('active', 'approved')
             AND atom.claim_state = 'current'
            WHERE doc.status = 'active' AND doc.doc_type = 'book'
              AND json_valid(book.memory_atom_ids_json) AND atom.id IS NULL
            """,
        ),
        "allBooksWithNoncurrentAtoms": _scalar(
            conn,
            """
            SELECT COUNT(DISTINCT book.book_id)
            FROM memory_books AS book
            JOIN json_each(book.memory_atom_ids_json) AS member
            LEFT JOIN memory_atoms AS atom
              ON atom.id = CAST(member.value AS TEXT)
             AND atom.status IN ('active', 'approved')
             AND atom.claim_state = 'current'
            WHERE json_valid(book.memory_atom_ids_json) AND atom.id IS NULL
            """,
        ),
        "currentBooksWithNoncurrentAtoms": _scalar(
            conn,
            """
            SELECT COUNT(DISTINCT book.book_id)
            FROM memory_books AS book
            JOIN json_each(book.memory_atom_ids_json) AS member
            LEFT JOIN memory_atoms AS atom
              ON atom.id = CAST(member.value AS TEXT)
             AND atom.status IN ('active', 'approved')
             AND atom.claim_state = 'current'
            WHERE json_valid(book.memory_atom_ids_json) AND atom.id IS NULL
              AND book.status IN ('active', 'approved')
              AND COALESCE(
                    json_extract(book.metadata_json, '$.retrievalStale'),
                    0
                  ) != 1
            """,
        ),
        "noncurrentAtomGroupMemberships": _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM memory_semantic_group_members AS member
            LEFT JOIN memory_atoms AS atom ON atom.id = member.member_id
            WHERE member.member_type = 'atom'
              AND (
                  atom.id IS NULL OR atom.status NOT IN ('active', 'approved')
                  OR atom.claim_state != 'current'
              )
            """,
        ),
        "activePhraseDocsOnlySupportedByNoncurrentAtoms": _scalar(
            conn,
            """
            SELECT COUNT(DISTINCT doc.doc_id)
            FROM memory_retrieval_docs AS doc
            JOIN memory_projection_dependencies AS dependency
              ON dependency.dependent_type = 'phrase'
             AND dependency.dependent_id = doc.source_id
             AND dependency.source_type = 'atom'
            JOIN memory_atoms AS atom ON atom.id = dependency.source_id
            WHERE doc.status = 'active' AND doc.doc_type = 'phrase'
              AND (
                  atom.status NOT IN ('active', 'approved')
                  OR atom.claim_state != 'current'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_projection_dependencies AS support
                  JOIN memory_atoms AS current_atom
                    ON current_atom.id = support.source_id
                  WHERE support.source_type = 'atom'
                    AND support.dependent_type = 'phrase'
                    AND support.dependent_id = doc.source_id
                    AND current_atom.status IN ('active', 'approved')
                    AND current_atom.claim_state = 'current'
              )
            """,
        ),
        "supersessionSuppressedPhrases": _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM memory_items
            WHERE kind = 'phrase' AND status = 'hidden'
              AND json_valid(metadata_json)
              AND json_extract(metadata_json, '$.supersessionSuppressed') = 1
            """,
        ),
        "historicalAcceptedFeedbackForSuppressedPhrases": _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM candidate_feedback AS feedback
            JOIN memory_items AS item ON item.memory_id = feedback.memory_id
            WHERE item.kind = 'phrase' AND item.status = 'hidden'
              AND feedback.action IN ('accepted', 'accept', 'active_rag_accept', 'pin')
              AND json_valid(item.metadata_json)
              AND json_extract(item.metadata_json, '$.supersessionSuppressed') = 1
            """,
        ),
        "retrievableAcceptedFeedbackForSuppressedPhrases": _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM candidate_feedback AS feedback
            JOIN memory_items AS item ON item.memory_id = feedback.memory_id
            JOIN memory_retrieval_docs AS doc
              ON doc.doc_type = 'phrase'
             AND doc.source_id = item.memory_id
             AND doc.status = 'active'
            WHERE item.kind = 'phrase' AND item.status = 'hidden'
              AND feedback.action IN ('accepted', 'accept', 'active_rag_accept', 'pin')
              AND json_valid(item.metadata_json)
              AND json_extract(item.metadata_json, '$.supersessionSuppressed') = 1
            """,
        ),
        "vectorRevisionMismatches": _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM memory_retrieval_doc_vectors AS vector
            JOIN memory_retrieval_docs AS doc ON doc.doc_id = vector.doc_id
            WHERE doc.status = 'active'
              AND (
                  vector.source_revision != doc.source_revision
                  OR vector.projection_version != doc.projection_version
              )
            """,
        ),
        "activeCaptureHints": _scalar(
            conn,
            "SELECT COUNT(*) FROM memory_capture_hints WHERE status = 'active'",
        ),
        "projectionDependencies": _scalar(
            conn,
            "SELECT COUNT(*) FROM memory_projection_dependencies",
        ),
    }


def _metadata_family_ablation(
    conn: sqlite3.Connection,
    *,
    project: str,
    max_queries: int,
    embedding_provider: EmbeddingProvider | None,
) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT doc_id, project, owner_kind, owner_id, tags_text, aliases_text,
               surface_hints_text, query_expansions_text
        FROM memory_retrieval_docs
        WHERE status = 'active' AND doc_type != 'item'
          AND (? = '' OR project = ? OR project = '')
        ORDER BY doc_id
        """,
        (project, project),
    ).fetchall()
    samples: list[tuple[str, str, str, str, str]] = []
    seen_terms: set[str] = set()
    for row in rows:
        metadata_text = " ".join(
            str(row[key] or "")
            for key in (
                "tags_text",
                "aliases_text",
                "surface_hints_text",
                "query_expansions_text",
            )
        )
        terms = [term for term in token_terms(metadata_text, max_terms=12) if len(term) >= 2]
        for term in terms:
            normalized = term.casefold()
            if normalized in seen_terms:
                continue
            seen_terms.add(normalized)
            samples.append(
                (
                    term,
                    str(row["doc_id"]),
                    str(row["project"] or project),
                    str(row["owner_kind"] or "user"),
                    str(row["owner_id"] or "default"),
                )
            )
            break
        if len(samples) >= max_queries:
            break

    top1_changed = 0
    top5_churn = 0.0
    evaluated = 0
    multi_lane_queries = 0
    penalized_docs = 0
    family_ratios: list[float] = []
    self_top5_legacy = 0
    self_top5_capped = 0
    legacy_metadata_only_top1 = 0
    capped_metadata_only_top1 = 0
    for term, expected_doc_id, sample_project, owner_kind, owner_id in samples:
        payload = retrieve_hybrid_rag_candidates(
            conn,
            HybridRagQuery(
                query_text=term,
                project=sample_project,
                top_k=20,
                latency_budget_ms=1_000,
                visible_owners=((owner_kind, owner_id),),
                enabled_lanes=(("time", False), ("feedback", False)),
            ),
            embedding_provider,
        )
        hits = [_hit_from_payload(item) for item in payload.get("hits") or []]
        hits = [hit for hit in hits if hit is not None]
        if not hits:
            continue
        evaluated += 1
        lanes_by_doc: dict[str, set[str]] = defaultdict(set)
        for hit in hits:
            lanes_by_doc[hit.doc_id].add(hit.source_lane)
        if any(
            len(lanes.intersection(METADATA_FAMILY_LANES)) >= 2
            for lanes in lanes_by_doc.values()
        ):
            multi_lane_queries += 1
        capped = rank_hybrid_hits_to_memory_hits(
            hits,
            query_text=term,
            metadata_family_mode="capped",
        )
        legacy = rank_hybrid_hits_to_memory_hits(
            hits,
            query_text=term,
            metadata_family_mode="legacy_sum",
        )
        capped_ids = [item.doc_id for item in capped[:5]]
        legacy_ids = [item.doc_id for item in legacy[:5]]
        if capped_ids[:1] != legacy_ids[:1]:
            top1_changed += 1
        denominator = max(1, len(set(capped_ids).union(legacy_ids)))
        top5_churn += len(set(capped_ids).symmetric_difference(legacy_ids)) / denominator
        self_top5_capped += int(expected_doc_id in capped_ids)
        self_top5_legacy += int(expected_doc_id in legacy_ids)
        if legacy and lanes_by_doc[legacy[0].doc_id].issubset(METADATA_FAMILY_LANES):
            legacy_metadata_only_top1 += 1
        if capped and lanes_by_doc[capped[0].doc_id].issubset(METADATA_FAMILY_LANES):
            capped_metadata_only_top1 += 1
        for item in capped:
            penalty = float(
                item.debug_features.get("metadata_family_overlap_penalty") or 0.0
            )
            if penalty >= 0.0:
                continue
            penalized_docs += 1
            raw = sum(
                float(item.debug_features.get(lane) or 0.0)
                for lane in METADATA_FAMILY_LANES
            )
            fused = raw + penalty
            if fused > 0.0:
                family_ratios.append(raw / fused)

    return {
        "querySampleCount": len(samples),
        "evaluatedQueryCount": evaluated,
        "queriesWithCorrelatedMetadataLanes": multi_lane_queries,
        "top1ChangedCount": top1_changed,
        "meanTop5SetChurn": round(top5_churn / evaluated, 6) if evaluated else 0.0,
        "metadataOnlyTop1Legacy": legacy_metadata_only_top1,
        "metadataOnlyTop1Capped": capped_metadata_only_top1,
        "metadataSelfRetrievalAt5Legacy": round(self_top5_legacy / evaluated, 6)
        if evaluated
        else 0.0,
        "metadataSelfRetrievalAt5Capped": round(self_top5_capped / evaluated, 6)
        if evaluated
        else 0.0,
        "penalizedDocumentOccurrences": penalized_docs,
        "maxLegacyToCappedMetadataContributionRatio": round(
            max(family_ratios, default=1.0),
            6,
        ),
        "privateQueriesOrTextsEmitted": False,
    }


def _actual_vector_gate_check(conn: sqlite3.Connection) -> dict[str, object]:
    provider_rows = conn.execute(
        """
        SELECT provider_fingerprint, COUNT(*) AS count
        FROM memory_retrieval_doc_vectors
        GROUP BY provider_fingerprint
        ORDER BY count DESC, provider_fingerprint
        """
    ).fetchall()
    if not provider_rows:
        active_documents = _scalar(
            conn,
            "SELECT COUNT(*) FROM memory_retrieval_docs WHERE status = 'active'",
        )
        return {
            "providerCount": 0,
            "activeDocuments": active_documents,
            "validVectors": 0,
            "bm25OnlyDocuments": active_documents,
            "loaderAgreement": True,
        }
    provider = str(provider_rows[0]["provider_fingerprint"])
    doc_ids = [
        str(row[0])
        for row in conn.execute(
            "SELECT doc_id FROM memory_retrieval_docs WHERE status = 'active' ORDER BY doc_id"
        ).fetchall()
    ]
    expected = _scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM memory_retrieval_doc_vectors AS vector
        JOIN memory_retrieval_docs AS doc ON doc.doc_id = vector.doc_id
        WHERE doc.status = 'active' AND vector.provider_fingerprint = ?
          AND vector.source_revision = doc.source_revision
          AND vector.projection_version = doc.projection_version
        """,
        (provider,),
    )
    loaded = load_retrieval_doc_vectors(conn, provider, doc_ids)
    return {
        "providerCount": len(provider_rows),
        "activeDocuments": len(doc_ids),
        "validVectors": expected,
        "bm25OnlyDocuments": max(0, len(doc_ids) - expected),
        "loaderReturnedVectors": len(loaded),
        "loaderAgreement": len(loaded) == expected,
    }


def _purpose_profile_check(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT profile_id, purpose_revision, schema_revision
        FROM memory_purpose_profiles
        WHERE profile_id = 'personal_current_state' AND active = 1
        ORDER BY purpose_revision DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"active": False, "profileRef": "", "schemaRevision": ""}
    return {
        "active": True,
        "profileRef": f"{row['profile_id']}@{int(row['purpose_revision'])}",
        "schemaRevision": str(row["schema_revision"] or ""),
    }


def _post_apply_check(db_path: Path | None) -> dict[str, object]:
    if db_path is None:
        return {"executed": False}
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return {
            "executed": True,
            "sourceFile": db_path.name,
            "readOnly": True,
            "consistency": _consistency_counts(conn),
            "vectorRevisionGates": _actual_vector_gate_check(conn),
        }


def _cache_gate_check(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT doc.doc_id, vector.provider_fingerprint
        FROM memory_retrieval_docs AS doc
        JOIN memory_retrieval_doc_vectors AS vector
          ON vector.doc_id = doc.doc_id
         AND vector.source_revision = doc.source_revision
         AND vector.projection_version = doc.projection_version
        WHERE doc.status = 'active'
        ORDER BY doc.doc_id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"executed": False, "reason": "no_valid_actual_vector"}
    doc_id = str(row["doc_id"])
    provider = str(row["provider_fingerprint"])
    before = bool(load_retrieval_doc_vectors(conn, provider, [doc_id]))
    conn.execute("SAVEPOINT cache_gate")
    conn.execute(
        "UPDATE memory_retrieval_docs SET source_revision = source_revision + 1 WHERE doc_id = ?",
        (doc_id,),
    )
    conn.execute(
        "DELETE FROM memory_retrieval_doc_vectors WHERE doc_id = ? AND provider_fingerprint = ?",
        (doc_id, provider),
    )
    after = bool(load_retrieval_doc_vectors(conn, provider, [doc_id]))
    conn.execute("ROLLBACK TO cache_gate")
    conn.execute("RELEASE cache_gate")
    return {
        "executed": True,
        "cachedBeforeMutation": before,
        "returnedAfterRevisionAdvanceAndVectorDelete": after,
        "passed": before and not after,
    }


def _cas_gate_check(db_path: Path) -> dict[str, object]:
    LocalSqliteCoreClient(db_path).initialize()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO memory_retrieval_docs(
                doc_id, doc_type, source_id, raw_text, status,
                source_revision, projection_version, updated_at_ms, metadata_json
            ) VALUES ('synthetic:cas', 'phrase', 'synthetic:cas', 'cas',
                      'active', 1, 1, 1, '{}')
            """
        )

        class Provider:
            fingerprint = "eval:cas"

            def embed_many(self, texts: list[str]) -> list[list[float]]:
                conn.execute(
                    """
                    UPDATE memory_retrieval_docs
                    SET source_revision = 2
                    WHERE doc_id = 'synthetic:cas'
                    """
                )
                return [[1.0, 0.0] for _ in texts]

            def embed(self, text: str) -> list[float]:
                return [1.0, 0.0]

        result = rebuild_retrieval_doc_vectors(
            conn,
            Provider(),
            doc_ids=["synthetic:cas"],
        )
        stored = _scalar(
            conn,
            "SELECT COUNT(*) FROM memory_retrieval_doc_vectors WHERE doc_id = 'synthetic:cas'",
        )
    return {
        "executed": True,
        "staleWritesSkipped": int(result.get("skippedStale") or 0),
        "vectorsStoredByLateWorker": stored,
        "passed": int(result.get("skippedStale") or 0) == 1 and stored == 0,
    }


def _hit_from_payload(raw: object) -> HybridRagHit | None:
    if not isinstance(raw, dict):
        return None
    return HybridRagHit(
        doc_id=str(raw.get("doc_id") or ""),
        doc_type=str(raw.get("doc_type") or ""),
        source_id=str(raw.get("source_id") or ""),
        text=str(raw.get("text") or ""),
        surface_hints=tuple(str(value) for value in raw.get("surface_hints") or []),
        tags=tuple(str(value) for value in raw.get("tags") or []),
        source_lane=str(raw.get("source_lane") or ""),
        rank=int(raw.get("rank") or 1),
        raw_score=float(raw.get("raw_score") or 0.0),
        metadata=dict(raw.get("metadata") or {}),
    )


def _scalar(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] = (),
) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _suite_count(suites: dict[str, object], suite: str) -> int:
    value = suites.get(suite)
    return int(value.get("total") or 0) if isinstance(value, dict) else 0


def _score_value(score: dict[str, object], key: str) -> float:
    return round(float(score.get(key) or 0.0), 6)


def _suite_score(
    score: dict[str, object],
    suite: str,
    key: str,
) -> float:
    by_suite = score.get("bySuite")
    if not isinstance(by_suite, dict):
        return 0.0
    value = by_suite.get(suite)
    if not isinstance(value, dict):
        return 0.0
    return round(float(value.get(key) or 0.0), 6)


def _delta_suite_score(
    delta: dict[str, object],
    suite: str,
    key: str,
) -> float:
    return _suite_score(delta, suite, key)


def _markdown(report: dict[str, object]) -> str:
    database = dict(report["database"])
    evaluation_mutated = "是" if database.get("evaluationMutatedSourceDatabase") else "否"
    live_repair_applied = "是" if database.get("liveRepairAppliedSeparately") else "否"
    consistency = dict(report["consistency"])
    before = dict(consistency["beforeRepair"])
    after = dict(consistency["afterRepair"])
    vector = dict(report["vectorRevisionGates"])
    actual = dict(vector["actualData"])
    cache = dict(vector["cacheInvalidationInjection"])
    cas = dict(vector["casLateWriterInjection"])
    ranking = dict(report["metadataFamilyAblation"])
    retrieval = dict(report.get("retrievalQuality") or {})
    dataset = dict(retrieval.get("dataset") or {})
    dataset_suites = dict(dataset.get("bySuite") or {})
    execution = dict(retrieval.get("retrievalExecution") or {})
    latency = dict(execution.get("latencyMs") or {})
    provider = dict(retrieval.get("provider") or {})
    search = dict(retrieval.get("search") or {})
    safety = dict(retrieval.get("safety") or {})
    baseline_retrieval = dict(retrieval.get("baseline") or {})
    recommendation = dict(retrieval.get("recommendation") or {})
    baseline_holdout = dict(baseline_retrieval.get("holdout") or {})
    recommended_holdout = dict(recommendation.get("holdout") or {})
    holdout_delta = dict(retrieval.get("holdoutDelta") or {})
    recommended_parameters = dict(recommendation.get("parameters") or {})
    recommended_weights = dict(recommended_parameters.get("laneWeights") or {})
    recommended_metadata = dict(recommended_parameters.get("metadataFamily") or {})
    purpose = dict(report["purposeAndCapture"])
    post_apply = dict(report.get("postApplyVerification") or {})
    post_apply_markdown = ""
    if post_apply.get("executed"):
        post_counts = dict(post_apply["consistency"])
        post_vectors = dict(post_apply["vectorRevisionGates"])
        post_apply_markdown = f"""
## 运行库应用后复验

- 复验方式：只读连接 `{post_apply.get('sourceFile', '')}`
- 旧 Book Retrieval Doc / 旧 Atom Group 成员 / 旧 Phrase Doc：{post_counts['retrievalBookDocsWithNoncurrentAtoms']} / {post_counts['noncurrentAtomGroupMemberships']} / {post_counts['activePhraseDocsOnlySupportedByNoncurrentAtoms']}
- 归档 Book 历史引用：{post_counts['allBooksWithNoncurrentAtoms']}（继续保留但不可召回）
- 活跃 Doc / revision 匹配向量：{post_vectors.get('activeDocuments', 0)} / {post_vectors.get('validVectors', 0)}
- BM25-only Doc / 混合 revision 向量：{post_vectors.get('bm25OnlyDocuments', 0)} / {post_counts['vectorRevisionMismatches']}
- revision-aware loader 一致：{post_vectors.get('loaderAgreement', True)}
"""
    return f"""# 记忆一致性真实数据测试报告

## 测试边界

- 数据来源：本机实际 SQLite 的一致性快照副本
- 评测脚本是否修改来源数据库：{evaluation_mutated}
- 运行库修复是否另行应用：{live_repair_applied}
- 输出是否包含记忆正文、查询词或原始 ID：否
- Schema：`{report['schemaVersion']}`

## P0-3 权威来源与统一失效

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| 非当前 Atom 的活跃 Retrieval Doc | {before['activeAtomDocsWithNoncurrentSource']} | {after['activeAtomDocsWithNoncurrentSource']} |
| 引用非当前 Atom 的 Retrieval Book Doc | {before['retrievalBookDocsWithNoncurrentAtoms']} | {after['retrievalBookDocsWithNoncurrentAtoms']} |
| 当前 Book 引用非当前 Atom | {before['currentBooksWithNoncurrentAtoms']} | {after['currentBooksWithNoncurrentAtoms']} |
| 归档 Book 的历史引用（审计保留） | {before['allBooksWithNoncurrentAtoms']} | {after['allBooksWithNoncurrentAtoms']} |
| 指向非当前 Atom 的 Group 成员 | {before['noncurrentAtomGroupMemberships']} | {after['noncurrentAtomGroupMemberships']} |
| 仅由非当前 Atom 支撑的活跃 Phrase Doc | {before['activePhraseDocsOnlySupportedByNoncurrentAtoms']} | {after['activePhraseDocsOnlySupportedByNoncurrentAtoms']} |
| 因 supersession 被隐藏的 Phrase | {before['supersessionSuppressedPhrases']} | {after['supersessionSuppressedPhrases']} |
| 仍可参与召回的旧 Phrase 正反馈 | {before['retrievableAcceptedFeedbackForSuppressedPhrases']} | {after['retrievableAcceptedFeedbackForSuppressedPhrases']} |
| 显式投影依赖记录 | {before['projectionDependencies']} | {after['projectionDependencies']} |

归档 Book 保留旧 Atom ID 只是历史证据；它们已标记 `retrievalStale`，不会进入当前召回。被隐藏 Phrase 的历史正反馈仍保留 {after['historicalAcceptedFeedbackForSuppressedPhrases']} 条用于审计，但没有活跃 Retrieval Doc 时不会成为召回源。

## P0-4 Vector Revision / CAS / Cache

- 实际向量 Provider 数：{actual.get('providerCount', 0)}
- 活跃 Retrieval Doc / revision 匹配向量：{actual.get('activeDocuments', 0)} / {actual.get('validVectors', 0)}
- 暂时仅走 BM25 的 Doc：{actual.get('bm25OnlyDocuments', 0)}
- 有效向量与 revision-aware loader 一致：{actual.get('loaderAgreement', True)}
- 实际缓存注入测试通过：{cache.get('passed', False)}
- 晚到旧任务 CAS 测试通过：{cas.get('passed', False)}
- 修复后混合 revision 向量：{after['vectorRevisionMismatches']}

## Metadata Family 消融

- 实际元数据查询样本：{ranking['evaluatedQueryCount']}
- 出现两路以上相关 Metadata Lane 的查询：{ranking['queriesWithCorrelatedMetadataLanes']}
- 封顶后 Top-1 改变：{ranking['top1ChangedCount']}
- 平均 Top-5 集合 churn：{ranking['meanTop5SetChurn']}
- Metadata-only Top-1（旧加和 -> 封顶）：{ranking['metadataOnlyTop1Legacy']} -> {ranking['metadataOnlyTop1Capped']}
- 元数据自召回 Recall@5（旧加和 -> 封顶）：{ranking['metadataSelfRetrievalAt5Legacy']} -> {ranking['metadataSelfRetrievalAt5Capped']}
- 旧加和相对封顶的最大 Metadata 贡献倍率：{ranking['maxLegacyToCappedMetadataContributionRatio']}

## 真实向量召回与参数搜索

- 实际评测样本：{dataset.get('totalCases', 0)}（Evidence / Metadata / Supersession：{_suite_count(dataset_suites, 'evidence_input')} / {_suite_count(dataset_suites, 'metadata_term')} / {_suite_count(dataset_suites, 'superseded_value')}）
- 调参集/留出集目标 Doc 重叠：{dataset.get('targetDocOverlapAcrossSplits', 0)}；多目标歧义样本：{dataset.get('ambiguousMultiTargetCases', 0)}
- 真实 Provider 指纹匹配：{provider.get('fingerprintMatched', False)}；匹配向量：{provider.get('matchingVectors', 0)}
- 跑到 Vector Raw / Vector Tag 的查询：{execution.get('queriesWithVectorRawHits', 0)} / {execution.get('queriesWithVectorTagHits', 0)}
- 单查询耗时 p50 / p95 / max：{latency.get('p50', 0)} / {latency.get('p95', 0)} / {latency.get('max', 0)} ms
- 参数候选数：{search.get('candidateParameterSets', 0)}；只在调参集选择、留出集验收：{search.get('holdoutAccepted', False)}
- 非当前或历史 Source 命中次数：{safety.get('historicalOrNoncurrentSourceHitOccurrences', 0)}

| 留出集指标 | 调参前 | 推荐参数 | 变化 |
|---|---:|---:|---:|
| 综合质量分 | {_score_value(baseline_holdout, 'qualityScore')} | {_score_value(recommended_holdout, 'qualityScore')} | {_score_value(holdout_delta, 'qualityScore')} |
| Evidence Success@5 | {_suite_score(baseline_holdout, 'evidence_input', 'successAt5')} | {_suite_score(recommended_holdout, 'evidence_input', 'successAt5')} | {_delta_suite_score(holdout_delta, 'evidence_input', 'successAt5')} |
| Evidence MRR@10 | {_suite_score(baseline_holdout, 'evidence_input', 'mrrAt10')} | {_suite_score(recommended_holdout, 'evidence_input', 'mrrAt10')} | {_delta_suite_score(holdout_delta, 'evidence_input', 'mrrAt10')} |
| Metadata Success@5 | {_suite_score(baseline_holdout, 'metadata_term', 'successAt5')} | {_suite_score(recommended_holdout, 'metadata_term', 'successAt5')} | {_delta_suite_score(holdout_delta, 'metadata_term', 'successAt5')} |
| Supersession Success@5 | {_suite_score(baseline_holdout, 'superseded_value', 'successAt5')} | {_suite_score(recommended_holdout, 'superseded_value', 'successAt5')} | {_delta_suite_score(holdout_delta, 'superseded_value', 'successAt5')} |
| Metadata 最大放大倍率 | {_score_value(baseline_holdout, 'maxMetadataFamilyAmplification')} | {_score_value(recommended_holdout, 'maxMetadataFamilyAmplification')} | {_score_value(holdout_delta, 'maxMetadataFamilyAmplification')} |

推荐 Lane 权重：`bm25_raw={recommended_weights.get('bm25_raw', 0)}`、`vector_raw={recommended_weights.get('vector_raw', 0)}`、`bm25_tags={recommended_weights.get('bm25_tags', 0)}`、`tagmemo={recommended_weights.get('tagmemo', 0)}`、`vector_tag_boost={recommended_weights.get('vector_tag_boost', 0)}`。RRF：`k={recommended_parameters.get('rrfK', 0)}`；Query Coverage：`{recommended_parameters.get('queryCoverageWeight', 0)}`。Metadata Family：`max={recommended_metadata.get('maxMultiplier', 0)}`、`second={recommended_metadata.get('secondaryWeight', 0)}`、`third={recommended_metadata.get('tertiaryWeight', 0)}`。运行默认值已匹配推荐：{recommendation.get('runtimeDefaultsMatch', False)}。

## Purpose / Capture

- 激活 Purpose：`{purpose.get('profileRef', '')}`（已验证：{purpose.get('active', False)}）
- Purpose Schema Revision：`{purpose.get('schemaRevision', '')}`
- 当前活跃 capture hint：{purpose.get('activeCaptureHints', 0)}
- capture 只作为复验提示，不直接创建 Atom；手动 `curation_prepare` 与后台既有 `autoApply` 行为未改。

{post_apply_markdown}

## 限制

本报告的元数据自召回是基于实际投影构造的弱监督代理，不是人工相关性标注，因此只用于判断回声室、排名 churn 和安全门禁，不能单独宣称语义质量提升。
"""


if __name__ == "__main__":
    raise SystemExit(main())
