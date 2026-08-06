from __future__ import annotations

import hashlib
import heapq
import io
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .rag_benchmark import validate_dataset_manifest


_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$")
_SPLIT_NAMES = ("train", "validation", "held_out")
_DEFAULT_SPLIT_RATIOS = (0.6, 0.2, 0.2)
_SCIFACT_MEMBERS = {
    "corpus": "scifact/corpus.jsonl",
    "queries": "scifact/queries.jsonl",
    "train_qrels": "scifact/qrels/train.tsv",
    "test_qrels": "scifact/qrels/test.tsv",
}


def prepare_longmemeval_dataset(
    source_path: str | Path,
    *,
    source_url: str,
    version: str,
    license_reference: str,
    split_seed: str,
) -> dict[str, Any]:
    """Load LongMemEval into Memory-only session retrieval cases."""

    source = Path(source_path)
    raw = source.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("LongMemEval source must be UTF-8 JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("LongMemEval source must be a non-empty array")
    seed = _text(split_seed, "split_seed", maximum=200)

    cases: list[dict[str, Any]] = []
    strata: dict[str, list[str]] = defaultdict(list)
    seen_queries: set[str] = set()
    duplicate_session_id_group_count = 0
    duplicate_session_occurrence_count = 0
    duplicate_session_affected_case_count = 0
    empty_turn_count = 0
    empty_turn_affected_case_count = 0
    official_qrel_mismatch_count = 0
    official_no_user_target_count = 0
    official_partial_qrel_mismatch_count = 0
    for raw_item in payload:
        if not isinstance(raw_item, dict):
            raise ValueError("LongMemEval item must be an object")
        query_id = _identifier(raw_item.get("question_id"), "question_id")
        if query_id in seen_queries:
            raise ValueError(f"duplicate LongMemEval question_id: {query_id}")
        seen_queries.add(query_id)
        question_type = _identifier(raw_item.get("question_type"), "question_type")
        abstention = query_id.endswith("_abs")
        slice_name = "abstention" if abstention else question_type
        session_ids = _identifier_list(
            raw_item.get("haystack_session_ids"),
            f"{query_id}.haystack_session_ids",
            allow_duplicates=True,
        )
        session_dates = _text_list(
            raw_item.get("haystack_dates"),
            f"{query_id}.haystack_dates",
        )
        raw_sessions = raw_item.get("haystack_sessions")
        if not isinstance(raw_sessions, list):
            raise ValueError(f"{query_id}.haystack_sessions must be an array")
        if len(session_ids) != len(session_dates) or len(session_ids) != len(raw_sessions):
            raise ValueError(f"{query_id} session IDs, dates, and content must align")
        answer_session_ids = _identifier_list(
            raw_item.get("answer_session_ids"),
            f"{query_id}.answer_session_ids",
            allow_empty=abstention,
        )
        unknown_relevant = set(answer_session_ids) - set(session_ids)
        if unknown_relevant:
            raise ValueError(
                f"{query_id} answer sessions are absent from the haystack: "
                + ", ".join(sorted(unknown_relevant))
            )
        session_id_counts = Counter(session_ids)
        duplicate_session_ids = {
            session_id for session_id, count in session_id_counts.items() if count > 1
        }
        ambiguous_relevant = duplicate_session_ids & set(answer_session_ids)
        if ambiguous_relevant:
            raise ValueError(
                f"{query_id} duplicate answer session ID is ambiguous: "
                + ", ".join(sorted(ambiguous_relevant))
            )

        normalized_turns = [
            _longmemeval_turns(raw_sessions[index], query_id, session_id)
            for index, session_id in enumerate(session_ids)
        ]
        official_relevant_session_ids = list(
            dict.fromkeys(
                session_id
                for session_id, turns in zip(
                    session_ids,
                    normalized_turns,
                    strict=True,
                )
                if any(
                    turn["role"] == "user" and turn["hasAnswer"]
                    for turn in turns
                )
            )
        )
        official_not_in_product = set(official_relevant_session_ids) - set(
            answer_session_ids
        )
        if official_not_in_product:
            raise ValueError(
                f"{query_id} user-side has_answer sessions are absent from "
                "answer_session_ids: "
                + ", ".join(sorted(official_not_in_product))
            )
        if (
            not abstention
            and set(official_relevant_session_ids) != set(answer_session_ids)
        ):
            official_qrel_mismatch_count += 1
            if not official_relevant_session_ids:
                official_no_user_target_count += 1
            else:
                official_partial_qrel_mismatch_count += 1
        case_empty_turn_count = sum(
            not turn["content"]
            for turns in normalized_turns
            for turn in turns
        )
        if case_empty_turn_count:
            empty_turn_count += case_empty_turn_count
            empty_turn_affected_case_count += 1
        canonical_turns_by_session_id: dict[str, list[dict[str, Any]]] = {}
        for session_id, turns in zip(session_ids, normalized_turns, strict=True):
            canonical = canonical_turns_by_session_id.setdefault(session_id, turns)
            if session_id in duplicate_session_ids and turns != canonical:
                raise ValueError(
                    f"{query_id} duplicate session ID {session_id} has different content"
                )

        session_occurrences: dict[str, int] = defaultdict(int)
        normalized_session_ids: set[str] = set()
        sessions: list[dict[str, Any]] = []
        for index, source_session_id in enumerate(session_ids):
            session_occurrences[source_session_id] += 1
            source_occurrence = session_occurrences[source_session_id]
            session_id = (
                source_session_id
                if source_occurrence == 1
                else _duplicate_session_reference(source_session_id, source_occurrence)
            )
            if session_id in normalized_session_ids:
                raise ValueError(
                    f"{query_id} duplicate session normalization collides at {session_id}"
                )
            normalized_session_ids.add(session_id)
            session = {
                "sessionId": session_id,
                "date": session_dates[index],
                "turns": normalized_turns[index],
            }
            if source_session_id in duplicate_session_ids:
                session["sourceSessionId"] = source_session_id
                session["sourceOccurrence"] = source_occurrence
            sessions.append(session)

        if duplicate_session_ids:
            duplicate_session_affected_case_count += 1
            duplicate_session_id_group_count += len(duplicate_session_ids)
            duplicate_session_occurrence_count += sum(
                session_id_counts[session_id] - 1
                for session_id in duplicate_session_ids
            )
        official_relevant = {
            session_id: 1.0 for session_id in official_relevant_session_ids
        }
        product_relevant = {session_id: 1.0 for session_id in answer_session_ids}
        official_retrieval_evaluable = bool(
            not abstention and official_relevant_session_ids
        )
        product_retrieval_evaluable = bool(not abstention and answer_session_ids)
        case = {
            "schemaVersion": "rag-ime.memory-retrieval-case.v1",
            "system": "memory",
            "queryId": query_id,
            "questionType": question_type,
            "slice": slice_name,
            "abstention": abstention,
            # The official retrieval runner indexes user turns only and excludes
            # non-abstention cases without a user-side has_answer target. Keep
            # that public-comparison contract as the default `relevant` arm;
            # the broader answer_session_ids arm remains an explicit product
            # diagnostic for assistant-side Memory behavior.
            "retrievalEvaluable": official_retrieval_evaluable,
            "officialRetrievalEvaluable": official_retrieval_evaluable,
            "productRetrievalEvaluable": product_retrieval_evaluable,
            "question": _text(raw_item.get("question"), f"{query_id}.question", maximum=20_000),
            "answer": _text(raw_item.get("answer"), f"{query_id}.answer", maximum=20_000),
            "questionDate": _text(
                raw_item.get("question_date"),
                f"{query_id}.question_date",
                maximum=200,
            ),
            "sessions": sessions,
            "relevant": official_relevant,
            "officialRelevant": official_relevant,
            "productRelevant": product_relevant,
        }
        cases.append(case)
        strata[slice_name].append(query_id)

    split_by_id = _stratified_split(strata, seed=seed)
    split_ids = {name: [] for name in _SPLIT_NAMES}
    for case in cases:
        split_name = split_by_id[case["queryId"]]
        case["split"] = split_name
        split_ids[split_name].append(case["queryId"])
    cases.sort(key=lambda item: item["queryId"])

    source_sha256 = hashlib.sha256(raw).hexdigest()
    manifest = validate_dataset_manifest(
        {
            "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
            "benchmarkId": f"longmemeval-{source_sha256[:12]}",
            "system": "memory",
            "tool": "memory",
            "sourceUrl": source_url,
            "version": version,
            "sourceSha256": source_sha256,
            "licenseReference": license_reference,
            "corpusIncluded": False,
            "splits": split_ids,
        }
    )
    return {
        "schemaVersion": "rag-ime.prepared-memory-benchmark.v1",
        "manifest": manifest,
        "adapter": {
            "name": "longmemeval",
            "splitSeed": seed,
            "splitRatios": dict(zip(_SPLIT_NAMES, _DEFAULT_SPLIT_RATIOS, strict=True)),
            "sliceCounts": {
                name: len(query_ids) for name, query_ids in sorted(strata.items())
            },
            "duplicateSessionPolicy": {
                "version": "preserve-identical-nonrelevant-v1",
                "preserveEveryOccurrence": True,
                "preserveSourceSessionId": True,
                "requireIdenticalTurns": True,
                "rejectAnswerRelevantDuplicates": True,
            },
            "duplicateSessionIdGroupCount": duplicate_session_id_group_count,
            "duplicateSessionOccurrenceCount": duplicate_session_occurrence_count,
            "duplicateSessionAffectedCaseCount": duplicate_session_affected_case_count,
            "duplicateRelevantSessionIdCount": 0,
            "emptyTurnPolicy": {
                "version": "preserve-nonanswer-placeholder-v1",
                "preserveEmptyTurns": True,
                "requireNonEmptySession": True,
                "rejectEmptyAnswerTurns": True,
            },
            "emptyTurnCount": empty_turn_count,
            "emptyTurnAffectedCaseCount": empty_turn_affected_case_count,
            "emptyAnswerTurnCount": 0,
            "retrievalProfiles": {
                "default": "official-user",
                "official-user": {
                    "content": "user-turns-only",
                    "qrels": "user-side-has_answer",
                    "excludeAbstention": True,
                    "excludeCasesWithoutUserTarget": True,
                },
                "product-all-turn": {
                    "content": "user-and-assistant-turns",
                    "qrels": "answer_session_ids",
                    "excludeAbstention": True,
                    "excludeCasesWithoutUserTarget": False,
                },
            },
            "officialQrelMismatchCount": official_qrel_mismatch_count,
            "officialNoUserTargetCount": official_no_user_target_count,
            "officialPartialQrelMismatchCount": official_partial_qrel_mismatch_count,
        },
        "cases": cases,
    }


def prepare_scifact_dataset(
    source_path: str | Path,
    *,
    source_url: str,
    version: str,
    license_reference: str,
    split_seed: str,
) -> dict[str, Any]:
    """Load the BEIR SciFact archive without exposing held-out labels to tuning."""

    source = Path(source_path)
    raw = source.read_bytes()
    seed = _text(split_seed, "split_seed", maximum=200)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            member_names = [item.filename for item in bundle.infolist()]
            duplicate_members = {
                name for name in member_names if member_names.count(name) > 1
            }
            if duplicate_members:
                raise ValueError(
                    "SciFact archive contains duplicate members: "
                    + ", ".join(sorted(duplicate_members))
                )
            missing = set(_SCIFACT_MEMBERS.values()) - set(member_names)
            if missing:
                raise ValueError(
                    "SciFact archive is missing required members: "
                    + ", ".join(sorted(missing))
                )
            corpus = _jsonl_records(
                bundle.read(_SCIFACT_MEMBERS["corpus"]),
                _SCIFACT_MEMBERS["corpus"],
            )
            queries = _jsonl_records(
                bundle.read(_SCIFACT_MEMBERS["queries"]),
                _SCIFACT_MEMBERS["queries"],
            )
            raw_train_qrels = bundle.read(_SCIFACT_MEMBERS["train_qrels"])
            raw_test_qrels = bundle.read(_SCIFACT_MEMBERS["test_qrels"])
    except zipfile.BadZipFile as exc:
        raise ValueError("SciFact source must be a valid ZIP archive") from exc

    documents: list[dict[str, str]] = []
    document_ids: set[str] = set()
    for raw_document in corpus:
        document_id = _identifier(raw_document.get("_id"), "SciFact document _id")
        if document_id in document_ids:
            raise ValueError(f"duplicate SciFact document ID: {document_id}")
        document_ids.add(document_id)
        documents.append(
            {
                "documentId": document_id,
                "title": _text(
                    raw_document.get("title"),
                    f"SciFact document {document_id} title",
                    maximum=20_000,
                ),
                "text": _text(
                    raw_document.get("text"),
                    f"SciFact document {document_id} text",
                    maximum=500_000,
                ),
            }
        )

    query_text_by_id: dict[str, str] = {}
    for raw_query in queries:
        query_id = _identifier(raw_query.get("_id"), "SciFact query _id")
        if query_id in query_text_by_id:
            raise ValueError(f"duplicate SciFact query ID: {query_id}")
        query_text_by_id[query_id] = _text(
            raw_query.get("text"),
            f"SciFact query {query_id} text",
            maximum=100_000,
        )

    train_qrels = _scifact_qrels(
        raw_train_qrels,
        member_name=_SCIFACT_MEMBERS["train_qrels"],
        query_ids=set(query_text_by_id),
        document_ids=document_ids,
    )
    test_qrels = _scifact_qrels(
        raw_test_qrels,
        member_name=_SCIFACT_MEMBERS["test_qrels"],
        query_ids=set(query_text_by_id),
        document_ids=document_ids,
    )
    overlap = set(train_qrels) & set(test_qrels)
    if overlap:
        raise ValueError(
            "SciFact query IDs overlap official train and test qrels: "
            + ", ".join(sorted(overlap))
        )
    missing_qrels = set(query_text_by_id) - set(train_qrels) - set(test_qrels)
    if missing_qrels:
        raise ValueError(
            "SciFact queries without qrels are not evaluable: "
            + ", ".join(sorted(missing_qrels))
        )

    ordered_train_ids = sorted(
        train_qrels,
        key=lambda query_id: hashlib.sha256(
            f"{seed}\0scifact-train\0{query_id}".encode("utf-8")
        ).digest(),
    )
    validation_count = (
        min(len(ordered_train_ids) - 1, max(1, math.ceil(len(ordered_train_ids) * 0.2)))
        if len(ordered_train_ids) > 1
        else 0
    )
    validation_ids = set(ordered_train_ids[:validation_count])
    split_by_id = {
        query_id: "validation" if query_id in validation_ids else "train"
        for query_id in ordered_train_ids
    }
    split_by_id.update({query_id: "held_out" for query_id in test_qrels})

    split_ids = {name: [] for name in _SPLIT_NAMES}
    cases: list[dict[str, Any]] = []
    for query_id in sorted(split_by_id):
        split_name = split_by_id[query_id]
        relevant = train_qrels.get(query_id, test_qrels.get(query_id))
        if relevant is None:
            raise ValueError(f"missing SciFact qrels for {query_id}")
        cases.append(
            {
                "schemaVersion": "rag-ime.knowledge-retrieval-case.v1",
                "system": "knowledge",
                "queryId": query_id,
                "query": query_text_by_id[query_id],
                "split": split_name,
                "relevant": relevant,
            }
        )
        split_ids[split_name].append(query_id)

    source_sha256 = hashlib.sha256(raw).hexdigest()
    manifest = validate_dataset_manifest(
        {
            "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
            "benchmarkId": f"beir-scifact-{source_sha256[:12]}",
            "system": "knowledge",
            "tool": "knowledge",
            "sourceUrl": source_url,
            "version": version,
            "sourceSha256": source_sha256,
            "licenseReference": license_reference,
            "corpusIncluded": False,
            "splits": split_ids,
        }
    )
    documents.sort(key=lambda item: item["documentId"])
    return {
        "schemaVersion": "rag-ime.prepared-knowledge-benchmark.v1",
        "manifest": manifest,
        "adapter": {
            "name": "beir-scifact",
            "splitSeed": seed,
            "officialSplits": {
                "train": ["train", "validation"],
                "test": "held_out",
            },
            "documentCount": len(documents),
        },
        "documents": documents,
        "cases": cases,
    }


def prepare_enterprise_rag_dataset(
    question_source_path: str | Path,
    document_source_path: str | Path,
    *,
    source_url: str,
    version: str,
    license_reference: str,
    split_seed: str,
) -> dict[str, Any]:
    """Prepare EnterpriseRAG-Bench without materializing 500k document bodies.

    JSON/JSONL are accepted for small contract fixtures. Production Parquet is
    streamed in batches and requires the optional ``pyarrow`` evaluation
    dependency; it is deliberately not a product runtime dependency.
    """

    question_source = Path(question_source_path)
    document_source = Path(document_source_path)
    seed = _text(split_seed, "split_seed", maximum=200)
    first_document_fingerprints: dict[str, str] = {}
    duplicate_document_fingerprints: dict[str, list[str]] = {}
    source_type_counts: dict[str, int] = defaultdict(int)
    document_count = 0
    for raw_document in _source_records(
        document_source,
        columns=("doc_id", "source_type", "title", "content"),
    ):
        document_id = _identifier(
            raw_document.get("doc_id"),
            "EnterpriseRAG document doc_id",
        )
        source_type = _identifier(
            raw_document.get("source_type"),
            f"EnterpriseRAG document {document_id} source_type",
        ).lower()
        fingerprint = _enterprise_document_fingerprint(
            raw_document,
            document_id=document_id,
            source_type=source_type,
        )
        first_fingerprint = first_document_fingerprints.get(document_id)
        if first_fingerprint is None:
            first_document_fingerprints[document_id] = fingerprint
        else:
            duplicate_document_fingerprints.setdefault(
                document_id,
                [first_fingerprint],
            ).append(fingerprint)
        source_type_counts[source_type] += 1
        document_count += 1
    if not document_count:
        raise ValueError("EnterpriseRAG document source must not be empty")

    document_identity_overrides: list[dict[str, Any]] = []
    duplicate_aliases: dict[str, list[str]] = {}
    for logical_document_id, fingerprints in sorted(
        duplicate_document_fingerprints.items()
    ):
        physical_versions = [
            {
                "physicalDocumentId": _enterprise_physical_document_id(
                    logical_document_id,
                    fingerprint,
                    occurrence,
                ),
                "contentSha256": fingerprint,
                "occurrence": occurrence,
            }
            for occurrence, fingerprint in enumerate(fingerprints, start=1)
        ]
        physical_ids = [
            version["physicalDocumentId"] for version in physical_versions
        ]
        duplicate_aliases[logical_document_id] = physical_ids
        document_identity_overrides.append(
            {
                "logicalDocumentId": logical_document_id,
                "physicalVersions": physical_versions,
                "conflictingContent": len(set(fingerprints)) > 1,
            }
        )

    cases: list[dict[str, Any]] = []
    strata: dict[str, list[str]] = defaultdict(list)
    seen_questions: set[str] = set()
    retrieval_evaluable_count = 0
    abstention_count = 0
    duplicate_expected_document_reference_count = 0
    for raw_question in _source_records(question_source):
        query_id = _identifier(
            raw_question.get("question_id"),
            "EnterpriseRAG question_id",
        )
        if query_id in seen_questions:
            raise ValueError(f"duplicate EnterpriseRAG question ID: {query_id}")
        seen_questions.add(query_id)
        question_type = _slice_identifier(
            raw_question.get("question_type"),
            f"EnterpriseRAG question {query_id} question_type",
        )
        source_types = _identifier_list(
            raw_question.get("source_types"),
            f"EnterpriseRAG question {query_id} source_types",
            allow_empty=True,
        )
        expected_doc_ids_field = (
            f"EnterpriseRAG question {query_id} expected_doc_ids"
        )
        raw_expected_doc_ids = raw_question.get("expected_doc_ids")
        if not isinstance(raw_expected_doc_ids, list):
            raise ValueError(f"{expected_doc_ids_field} must be an array")
        expected_doc_ids = [
            _identifier(item, f"{expected_doc_ids_field} item")
            for item in raw_expected_doc_ids
        ]
        unique_expected_doc_ids = list(dict.fromkeys(expected_doc_ids))
        if len(unique_expected_doc_ids) != len(expected_doc_ids):
            repeated_ids = {
                document_id
                for document_id in unique_expected_doc_ids
                if expected_doc_ids.count(document_id) > 1
            }
            if question_type != "conflicting_info" or not repeated_ids.issubset(
                duplicate_aliases
            ):
                raise ValueError(
                    f"{expected_doc_ids_field} contains duplicate IDs without "
                    "conflicting physical document versions"
                )
            duplicate_expected_document_reference_count += (
                len(expected_doc_ids) - len(unique_expected_doc_ids)
            )
            expected_doc_ids = unique_expected_doc_ids
        unknown = set(expected_doc_ids) - first_document_fingerprints.keys()
        if unknown:
            raise ValueError(
                f"EnterpriseRAG question {query_id} references an unknown document: "
                + ", ".join(sorted(unknown))
            )
        abstention_expected = question_type == "info_not_found"
        retrieval_evaluable = bool(expected_doc_ids)
        if not retrieval_evaluable and question_type not in {
            "high_level",
            "info_not_found",
        }:
            raise ValueError(
                f"EnterpriseRAG question {query_id} has no retrieval qrels"
            )
        retrieval_evaluable_count += int(retrieval_evaluable)
        abstention_count += int(abstention_expected)
        answer_facts = _text_list(
            raw_question.get("answer_facts"),
            f"EnterpriseRAG question {query_id} answer_facts",
            allow_empty=abstention_expected,
        )
        cases.append(
            {
                "schemaVersion": "rag-ime.knowledge-retrieval-case.v1",
                "system": "knowledge",
                "queryId": query_id,
                "questionType": question_type,
                "slice": question_type,
                "query": _text(
                    raw_question.get("question"),
                    f"EnterpriseRAG question {query_id}",
                    maximum=100_000,
                ),
                "sourceTypes": source_types,
                "relevant": {
                    physical_document_id: 1.0
                    for document_id in expected_doc_ids
                    for physical_document_id in duplicate_aliases.get(
                        document_id,
                        [document_id],
                    )
                },
                "retrievalEvaluable": retrieval_evaluable,
                "abstentionExpected": abstention_expected,
                "goldAnswer": _text(
                    raw_question.get("gold_answer"),
                    f"EnterpriseRAG question {query_id} gold_answer",
                    maximum=100_000,
                ),
                "answerFacts": answer_facts,
            }
        )
        strata[question_type].append(query_id)
    if not cases:
        raise ValueError("EnterpriseRAG question source must not be empty")

    split_by_id = _stratified_split(strata, seed=seed)
    split_ids = {name: [] for name in _SPLIT_NAMES}
    for case in cases:
        split_name = split_by_id[case["queryId"]]
        case["split"] = split_name
        split_ids[split_name].append(case["queryId"])
    cases.sort(key=lambda item: item["queryId"])

    question_sha256 = _file_sha256(question_source)
    document_sha256 = _file_sha256(document_source)
    source_sha256 = _bundle_sha256(
        {
            "documents": document_sha256,
            "questions": question_sha256,
        }
    )
    manifest = validate_dataset_manifest(
        {
            "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
            "benchmarkId": f"enterprise-rag-{source_sha256[:12]}",
            "system": "knowledge",
            "tool": "knowledge",
            "sourceUrl": source_url,
            "version": version,
            "sourceSha256": source_sha256,
            "licenseReference": license_reference,
            "corpusIncluded": False,
            "splits": split_ids,
        }
    )
    return {
        "schemaVersion": "rag-ime.prepared-knowledge-benchmark.v1",
        "manifest": manifest,
        "adapter": {
            "name": "enterprise-rag-bench",
            "splitSeed": seed,
            "splitRatios": dict(
                zip(_SPLIT_NAMES, _DEFAULT_SPLIT_RATIOS, strict=True)
            ),
            "documentCount": document_count,
            "logicalDocumentCount": len(first_document_fingerprints),
            "duplicateLogicalIdCount": len(duplicate_document_fingerprints),
            "duplicatePhysicalRowCount": (
                document_count - len(first_document_fingerprints)
            ),
            "duplicateExpectedDocumentReferenceCount": (
                duplicate_expected_document_reference_count
            ),
            "questionCount": len(cases),
            "retrievalEvaluableCount": retrieval_evaluable_count,
            "abstentionCount": abstention_count,
            "sliceCounts": {
                name: len(query_ids) for name, query_ids in sorted(strata.items())
            },
            "sourceTypeCounts": dict(sorted(source_type_counts.items())),
        },
        "sourceArtifacts": {
            "questions": {
                "sha256": question_sha256,
                "format": _source_format(question_source),
            },
            "documents": {
                "sha256": document_sha256,
                "format": _source_format(document_source),
                "materializedInPreparedArtifact": False,
            },
        },
        "documentIdentityOverrides": document_identity_overrides,
        "cases": cases,
    }


def prepare_crud_rag_dataset(
    source_path: str | Path,
    document_root: str | Path,
    *,
    source_url: str,
    version: str,
    license_reference: str,
    split_seed: str,
    distractor_limit: int = 0,
) -> dict[str, Any]:
    """Build an explicit Chinese retrieval slice from CRUD-RAG QA records.

    CRUD-RAG publishes answer-generation tasks rather than document qrels. The
    embedded ``news1..3`` fields are therefore converted to clearly labelled
    derived qrels. Deterministically sampled 80k-corpus lines are distractors;
    this score must never be reported as an official CRUD-RAG leaderboard score.
    """

    if (
        isinstance(distractor_limit, bool)
        or not isinstance(distractor_limit, int)
        or distractor_limit < 0
        or distractor_limit > 100_000
    ):
        raise ValueError("distractor_limit must be an integer from 0 to 100000")
    source = Path(source_path)
    root = Path(document_root)
    seed = _text(split_seed, "split_seed", maximum=200)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("CRUD-RAG source must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("CRUD-RAG source must be an object")

    task_specs = (
        ("questanswer_1doc", "qa_1doc", 1),
        ("questanswer_2docs", "qa_2doc", 2),
        ("questanswer_3docs", "qa_3doc", 3),
    )
    documents_by_id: dict[str, dict[str, str]] = {}
    cases: list[dict[str, Any]] = []
    strata: dict[str, list[str]] = defaultdict(list)
    seen_queries: set[str] = set()
    for task_name, slice_name, relevant_count in task_specs:
        records = payload.get(task_name)
        if not isinstance(records, list) or not records:
            raise ValueError(f"CRUD-RAG {task_name} must be a non-empty array")
        for raw_record in records:
            if not isinstance(raw_record, dict):
                raise ValueError(f"CRUD-RAG {task_name} record must be an object")
            source_id = _identifier(raw_record.get("ID"), f"{task_name}.ID")
            query_id = _identifier(
                f"crud-{slice_name}-{source_id}",
                f"{task_name}.queryId",
            )
            if query_id in seen_queries:
                raise ValueError(f"duplicate CRUD-RAG query ID: {query_id}")
            seen_queries.add(query_id)
            relevant: dict[str, float] = {}
            for document_index in range(1, relevant_count + 1):
                text = _text(
                    raw_record.get(f"news{document_index}"),
                    f"{query_id}.news{document_index}",
                    maximum=1_000_000,
                )
                document_id = _content_document_id(text)
                documents_by_id.setdefault(
                    document_id,
                    {
                        "documentId": document_id,
                        "title": f"CRUD-RAG {slice_name} evidence",
                        "text": text,
                        "source": "crud_embedded_gold",
                    },
                )
                relevant[document_id] = 1.0
            cases.append(
                {
                    "schemaVersion": "rag-ime.knowledge-retrieval-case.v1",
                    "system": "knowledge",
                    "queryId": query_id,
                    "questionType": "question_answering",
                    "slice": slice_name,
                    "query": _text(
                        raw_record.get("questions"),
                        f"{query_id}.questions",
                        maximum=100_000,
                    ),
                    "answer": _text(
                        raw_record.get("answers"),
                        f"{query_id}.answers",
                        maximum=100_000,
                    ),
                    "relevant": relevant,
                    "retrievalEvaluable": True,
                    "abstentionExpected": False,
                }
            )
            strata[slice_name].append(query_id)

    gold_document_ids = set(documents_by_id)
    distractors = _select_crud_distractors(
        root,
        seed=seed,
        limit=distractor_limit,
        excluded_document_ids=gold_document_ids,
    )
    for document in distractors:
        documents_by_id[document["documentId"]] = document

    split_by_id = _stratified_split(strata, seed=seed)
    split_ids = {name: [] for name in _SPLIT_NAMES}
    for case in cases:
        split_name = split_by_id[case["queryId"]]
        case["split"] = split_name
        split_ids[split_name].append(case["queryId"])
    cases.sort(key=lambda item: item["queryId"])

    source_file_sha256 = _file_sha256(source)
    corpus_sha256, corpus_files, corpus_lines = _directory_tree_sha256(root)
    source_sha256 = _bundle_sha256(
        {"qa": source_file_sha256, "corpus": corpus_sha256}
    )
    manifest = validate_dataset_manifest(
        {
            "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
            "benchmarkId": f"crud-rag-derived-{source_sha256[:12]}",
            "system": "knowledge",
            "tool": "knowledge",
            "sourceUrl": source_url,
            "version": version,
            "sourceSha256": source_sha256,
            "licenseReference": license_reference,
            "corpusIncluded": False,
            "splits": split_ids,
        }
    )
    return {
        "schemaVersion": "rag-ime.prepared-knowledge-benchmark.v1",
        "manifest": manifest,
        "adapter": {
            "name": "crud-rag-chinese-qa-derived-qrels",
            "splitSeed": seed,
            "splitRatios": dict(
                zip(_SPLIT_NAMES, _DEFAULT_SPLIT_RATIOS, strict=True)
            ),
            "derivedQrels": True,
            "officialRetrievalScore": False,
            "caseCount": len(cases),
            "goldDocumentCount": len(gold_document_ids),
            "distractorCount": len(distractors),
            "sourceCorpusFileCount": corpus_files,
            "sourceCorpusLineCount": corpus_lines,
            "sliceCounts": {
                name: len(query_ids) for name, query_ids in sorted(strata.items())
            },
        },
        "sourceArtifacts": {
            "qaSha256": source_file_sha256,
            "corpusTreeSha256": corpus_sha256,
        },
        "documents": [documents_by_id[key] for key in sorted(documents_by_id)],
        "cases": cases,
    }


def prepare_swe_bench_verified_dataset(
    source_path: str | Path,
    *,
    source_url: str,
    version: str,
    license_reference: str,
    split_seed: str,
    interview_size: int = 50,
) -> dict[str, Any]:
    """Prepare a pinned SWE-bench Verified Harness manifest.

    Gold and test patches are hashed for provenance but never returned. The
    Agent view therefore cannot obtain the reference solution from this adapter.
    """

    if (
        isinstance(interview_size, bool)
        or not isinstance(interview_size, int)
        or interview_size < 1
    ):
        raise ValueError("interview_size must be a positive integer")
    source = Path(source_path)
    seed = _text(split_seed, "split_seed", maximum=200)
    agent_cases: list[dict[str, Any]] = []
    verifier_cases: list[dict[str, Any]] = []
    strata: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    repository_counts: dict[str, int] = defaultdict(int)
    difficulty_counts: dict[str, int] = defaultdict(int)
    for raw_case in _source_records(source):
        instance_id = _identifier(raw_case.get("instance_id"), "SWE instance_id")
        if instance_id in seen:
            raise ValueError(f"duplicate SWE-bench instance ID: {instance_id}")
        seen.add(instance_id)
        repository = _text(raw_case.get("repo"), f"{instance_id}.repo", maximum=300)
        difficulty = _text(
            raw_case.get("difficulty") or "unspecified",
            f"{instance_id}.difficulty",
            maximum=200,
        )
        base_commit = _sha1(raw_case.get("base_commit"), f"{instance_id}.base_commit")
        environment_commit = _sha1(
            raw_case.get("environment_setup_commit"),
            f"{instance_id}.environment_setup_commit",
        )
        patch = str(raw_case.get("patch") or "")
        test_patch = str(raw_case.get("test_patch") or "")
        agent_cases.append(
            {
                "schemaVersion": "rag-ime.swe-bench-agent-case.v1",
                "instanceId": instance_id,
                "repo": repository,
                "baseCommit": base_commit,
                "problemStatement": _text(
                    raw_case.get("problem_statement"),
                    f"{instance_id}.problem_statement",
                    maximum=500_000,
                ),
                "hintsText": str(raw_case.get("hints_text") or ""),
                "createdAt": _text(
                    raw_case.get("created_at"),
                    f"{instance_id}.created_at",
                    maximum=100,
                ),
                "version": str(raw_case.get("version") or ""),
                "difficulty": difficulty,
            }
        )
        verifier_cases.append(
            {
                "instanceId": instance_id,
                "environmentSetupCommit": environment_commit,
                "failToPass": _string_array(
                    raw_case.get("FAIL_TO_PASS"),
                    f"{instance_id}.FAIL_TO_PASS",
                ),
                "passToPass": _string_array(
                    raw_case.get("PASS_TO_PASS"),
                    f"{instance_id}.PASS_TO_PASS",
                ),
                "goldPatchSha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                "testPatchSha256": hashlib.sha256(
                    test_patch.encode("utf-8")
                ).hexdigest(),
            }
        )
        repository_counts[repository] += 1
        difficulty_counts[difficulty] += 1
        strata[f"{repository}\0{difficulty}"].append(instance_id)
    if not agent_cases:
        raise ValueError("SWE-bench source must not be empty")
    if interview_size > len(agent_cases):
        raise ValueError("interview_size cannot exceed the full dataset")
    agent_cases.sort(key=lambda item: item["instanceId"])
    verifier_cases.sort(key=lambda item: item["instanceId"])
    full_ids = [item["instanceId"] for item in agent_cases]
    interview_ids = _stratified_subset(strata, seed=seed, size=interview_size)
    source_sha256 = _file_sha256(source)
    return {
        "schemaVersion": "rag-ime.swe-bench-verified-dataset.v1",
        "source": {
            "url": source_url,
            "version": _text(version, "version", maximum=200),
            "sha256": source_sha256,
            "licenseReference": _text(
                license_reference,
                "license_reference",
                maximum=2_000,
            ),
            "corpusIncluded": False,
        },
        "adapter": {
            "name": "swe-bench-verified",
            "splitSeed": seed,
            "fullCount": len(full_ids),
            "interviewCount": len(interview_ids),
            "repositoryCounts": dict(sorted(repository_counts.items())),
            "difficultyCounts": dict(sorted(difficulty_counts.items())),
            "goldPatchExposed": False,
            "testPatchExposed": False,
        },
        "fullInstanceIds": full_ids,
        "fullSplitSha256": _bundle_sha256({"instanceIds": full_ids}),
        "interviewInstanceIds": interview_ids,
        "interviewSplitSha256": _bundle_sha256(
            {"instanceIds": interview_ids}
        ),
        "agentCases": agent_cases,
        "verifierCases": verifier_cases,
    }


def _jsonl_records(raw: bytes, member_name: str) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{member_name} must be UTF-8 JSONL") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{member_name}:{line_number} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{member_name}:{line_number} must be an object")
        records.append(value)
    if not records:
        raise ValueError(f"{member_name} must contain at least one record")
    return records


def _source_records(
    source: Path,
    *,
    columns: tuple[str, ...] | None = None,
) -> Iterator[dict[str, Any]]:
    suffix = source.suffix.casefold()
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as parquet  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError(
                "Parquet benchmark sources require the optional pyarrow eval dependency"
            ) from exc
        try:
            parquet_file = parquet.ParquetFile(source)
            for batch in parquet_file.iter_batches(
                batch_size=4_096,
                columns=list(columns) if columns else None,
            ):
                for record in batch.to_pylist():
                    if not isinstance(record, dict):
                        raise ValueError("Parquet benchmark row must be an object")
                    yield record
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read Parquet benchmark source {source.name}") from exc
        return
    if suffix == ".jsonl":
        try:
            with source.open("r", encoding="utf-8") as handle:
                observed = False
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    observed = True
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"{source.name}:{line_number} is invalid JSON"
                        ) from exc
                    if not isinstance(value, dict):
                        raise ValueError(
                            f"{source.name}:{line_number} must be an object"
                        )
                    yield (
                        {name: value.get(name) for name in columns}
                        if columns
                        else value
                    )
                if not observed:
                    raise ValueError(f"{source.name} must not be empty")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read JSONL benchmark source {source.name}") from exc
        return
    if suffix == ".json":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read JSON benchmark source {source.name}") from exc
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"{source.name} must contain a non-empty JSON array")
        for value in payload:
            if not isinstance(value, dict):
                raise ValueError(f"{source.name} row must be an object")
            yield (
                {name: value.get(name) for name in columns}
                if columns
                else value
            )
        return
    raise ValueError("benchmark source must be .json, .jsonl, or .parquet")


def _source_format(source: Path) -> str:
    suffix = source.suffix.casefold().lstrip(".")
    if suffix not in {"json", "jsonl", "parquet"}:
        raise ValueError("unsupported benchmark source format")
    return suffix


def _enterprise_document_fingerprint(
    document: dict[str, Any],
    *,
    document_id: str,
    source_type: str,
) -> str:
    title = document.get("title")
    content = document.get("content")
    if not isinstance(title, str):
        raise ValueError(f"EnterpriseRAG document {document_id} title must be text")
    if not isinstance(content, str):
        raise ValueError(f"EnterpriseRAG document {document_id} content must be text")
    return _bundle_sha256(
        {
            "sourceType": source_type,
            "title": title,
            "content": content,
        }
    )


def _enterprise_physical_document_id(
    logical_document_id: str,
    fingerprint: str,
    occurrence: int,
) -> str:
    suffix = f":v:{fingerprint[:12]}:{occurrence}"
    candidate = f"{logical_document_id}{suffix}"
    if _STABLE_ID.fullmatch(candidate):
        return candidate
    fallback = (
        "enterprise-doc:v:"
        + hashlib.sha256(
            f"{logical_document_id}\0{fingerprint}\0{occurrence}".encode("utf-8")
        ).hexdigest()
    )
    return _identifier(fallback, "EnterpriseRAG physical document ID")


def _file_sha256(source: Path) -> str:
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"cannot hash benchmark source {source}") from exc
    return digest.hexdigest()


def _bundle_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _directory_tree_sha256(root: Path) -> tuple[str, int, int]:
    if not root.is_dir():
        raise ValueError("CRUD-RAG document_root must be a directory")
    materials: list[dict[str, object]] = []
    line_count = 0
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix != ".aria2"
    ]
    if not files:
        raise ValueError("CRUD-RAG document_root must contain corpus files")
    for path in files:
        digest = hashlib.sha256()
        file_lines = 0
        try:
            with path.open("rb") as handle:
                for line in handle:
                    digest.update(line)
                    file_lines += 1
        except OSError as exc:
            raise ValueError(f"cannot read CRUD-RAG corpus file {path.name}") from exc
        line_count += file_lines
        materials.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": digest.hexdigest(),
                "lines": file_lines,
            }
        )
    return _bundle_sha256({"files": materials}), len(files), line_count


def _content_document_id(text: str) -> str:
    return f"crud-doc-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]}"


def _select_crud_distractors(
    root: Path,
    *,
    seed: str,
    limit: int,
    excluded_document_ids: set[str],
) -> list[dict[str, str]]:
    if not root.is_dir():
        raise ValueError("CRUD-RAG document_root must be a directory")
    if limit == 0:
        return []
    selected: list[tuple[int, str, str]] = []
    observed_ids = set(excluded_document_ids)
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix != ".aria2"
    ]
    if not files:
        raise ValueError("CRUD-RAG document_root must contain corpus files")
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    document_id = _content_document_id(text)
                    if document_id in observed_ids:
                        continue
                    observed_ids.add(document_id)
                    score = int.from_bytes(
                        hashlib.sha256(
                            f"{seed}\0{document_id}".encode("utf-8")
                        ).digest(),
                        "big",
                    )
                    candidate = (-score, document_id, text)
                    if len(selected) < limit:
                        heapq.heappush(selected, candidate)
                    elif score < -selected[0][0]:
                        heapq.heapreplace(selected, candidate)
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read CRUD-RAG corpus file {path.name}") from exc
    return [
        {
            "documentId": document_id,
            "title": "CRUD-RAG deterministic distractor",
            "text": text,
            "source": "crud_80k_distractor",
        }
        for _score, document_id, text in sorted(selected, key=lambda item: item[1])
    ]


def _slice_identifier(value: object, field: str) -> str:
    text = _text(value, field, maximum=200).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return _identifier(normalized, field)


def _sha1(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{40}", text):
        raise ValueError(f"{field} must be a 40-character Git SHA")
    return text


def _string_array(value: object, field: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must be a JSON array") from exc
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result = [str(item).strip() for item in value]
    if any(not item for item in result):
        raise ValueError(f"{field} must contain non-empty strings")
    return result


def _stratified_subset(
    strata: dict[str, list[str]],
    *,
    seed: str,
    size: int,
) -> list[str]:
    queues = {
        stratum: sorted(
            identifiers,
            key=lambda item: hashlib.sha256(
                f"{seed}\0{stratum}\0{item}".encode("utf-8")
            ).digest(),
        )
        for stratum, identifiers in strata.items()
    }
    order = sorted(
        queues,
        key=lambda stratum: hashlib.sha256(
            f"{seed}\0stratum\0{stratum}".encode("utf-8")
        ).digest(),
    )
    offsets = {stratum: 0 for stratum in order}
    selected: list[str] = []
    while len(selected) < size:
        progressed = False
        for stratum in order:
            offset = offsets[stratum]
            if offset >= len(queues[stratum]):
                continue
            selected.append(queues[stratum][offset])
            offsets[stratum] = offset + 1
            progressed = True
            if len(selected) == size:
                break
        if not progressed:
            raise ValueError("stratified subset cannot satisfy requested size")
    return sorted(selected)


def _scifact_qrels(
    raw: bytes,
    *,
    member_name: str,
    query_ids: set[str],
    document_ids: set[str],
) -> dict[str, dict[str, float]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{member_name} must be UTF-8 TSV") from exc
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[0].split("\t") != ["query-id", "corpus-id", "score"]:
        raise ValueError(
            f"{member_name} header must be query-id, corpus-id, and score"
        )
    qrels: dict[str, dict[str, float]] = defaultdict(dict)
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError(f"{member_name}:{line_number} must have three fields")
        query_id = _identifier(fields[0], f"{member_name}:{line_number} query-id")
        document_id = _identifier(fields[1], f"{member_name}:{line_number} corpus-id")
        try:
            gain = float(fields[2])
        except ValueError as exc:
            raise ValueError(f"{member_name}:{line_number} score must be numeric") from exc
        if not math.isfinite(gain) or gain <= 0:
            raise ValueError(f"{member_name}:{line_number} score must be positive")
        if query_id not in query_ids:
            raise ValueError(f"{member_name}:{line_number} references an unknown query")
        if document_id not in document_ids:
            raise ValueError(f"{member_name}:{line_number} references an unknown document")
        if document_id in qrels[query_id]:
            raise ValueError(
                f"{member_name}:{line_number} duplicates query/document relevance"
            )
        qrels[query_id][document_id] = gain
    if not qrels:
        raise ValueError(f"{member_name} must contain positive qrels")
    return {query_id: dict(relevant) for query_id, relevant in qrels.items()}


def _stratified_split(strata: dict[str, list[str]], *, seed: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for stratum, raw_ids in sorted(strata.items()):
        ids = sorted(
            raw_ids,
            key=lambda item_id: hashlib.sha256(
                f"{seed}\0{stratum}\0{item_id}".encode("utf-8")
            ).digest(),
        )
        counts = _split_counts(len(ids), _DEFAULT_SPLIT_RATIOS)
        offset = 0
        for split_name, count in zip(_SPLIT_NAMES, counts, strict=True):
            for item_id in ids[offset : offset + count]:
                assignments[item_id] = split_name
            offset += count
    if len(assignments) != sum(len(ids) for ids in strata.values()):
        raise ValueError("stratified split did not assign every item")
    return assignments


def _split_counts(size: int, ratios: tuple[float, ...]) -> tuple[int, ...]:
    raw = [size * ratio for ratio in ratios]
    counts = [math.floor(value) for value in raw]
    remainder = size - sum(counts)
    order = sorted(
        range(len(ratios)),
        key=lambda index: (-(raw[index] - counts[index]), index),
    )
    for index in order[:remainder]:
        counts[index] += 1
    return tuple(counts)


def _longmemeval_turns(value: object, query_id: str, session_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{query_id}.{session_id} turns must be a non-empty array")
    turns: list[dict[str, Any]] = []
    for raw_turn in value:
        if not isinstance(raw_turn, dict):
            raise ValueError(f"{query_id}.{session_id} turn must be an object")
        role = str(raw_turn.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            raise ValueError(f"{query_id}.{session_id} turn role is invalid")
        raw_content = raw_turn.get("content")
        if not isinstance(raw_content, str):
            raise ValueError(f"{query_id}.{session_id}.content must be a string")
        content = raw_content.strip()
        if len(content) > 100_000:
            raise ValueError(f"{query_id}.{session_id}.content is too long")
        has_answer = raw_turn.get("has_answer") is True
        if not content and has_answer:
            raise ValueError(
                f"{query_id}.{session_id} answer-bearing turn must not be empty"
            )
        turns.append(
            {
                "role": role,
                "content": content,
                "hasAnswer": has_answer,
            }
        )
    if not any(turn["content"] for turn in turns):
        raise ValueError(
            f"{query_id}.{session_id} session must contain at least one non-empty turn"
        )
    return turns


def _identifier_list(
    value: object,
    field: str,
    *,
    allow_empty: bool = False,
    allow_duplicates: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result = [_identifier(item, f"{field} item") for item in value]
    if not allow_empty and not result:
        raise ValueError(f"{field} must not be empty")
    if not allow_duplicates and len(result) != len(set(result)):
        raise ValueError(f"{field} contains duplicate IDs")
    return result


def _duplicate_session_reference(source_session_id: str, occurrence: int) -> str:
    if occurrence < 2:
        raise ValueError("duplicate session occurrence must be at least two")
    suffix = f":duplicate:{occurrence}"
    candidate = f"{source_session_id}{suffix}"
    if len(candidate) <= 300:
        return _identifier(candidate, "normalized duplicate session ID")
    digest = hashlib.sha256(
        f"{source_session_id}\0{occurrence}".encode("utf-8")
    ).hexdigest()[:16]
    compact_suffix = f":dup:{occurrence}:{digest}"
    candidate = f"{source_session_id[: 300 - len(compact_suffix)]}{compact_suffix}"
    return _identifier(candidate, "normalized duplicate session ID")


def _text_list(
    value: object,
    field: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"{field} must be a non-empty array")
    return [_text(item, f"{field} item", maximum=500) for item in value]


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _STABLE_ID.fullmatch(text):
        raise ValueError(f"{field} must be a stable identifier")
    return text


def _text(value: object, field: str, *, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{field} is too long")
    return text
