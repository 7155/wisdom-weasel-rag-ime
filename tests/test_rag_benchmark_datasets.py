from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from rag_ime.rag_benchmark_datasets import (
    prepare_crud_rag_dataset,
    prepare_enterprise_rag_dataset,
    prepare_longmemeval_dataset,
    prepare_scifact_dataset,
    prepare_swe_bench_verified_dataset,
)


ROOT = Path(__file__).resolve().parents[1]


def _longmemeval_duplicate_session_record() -> dict[str, object]:
    return {
        "question_id": "memory-duplicate",
        "question_type": "temporal-reasoning",
        "question": "What was the remembered answer?",
        "answer": "the answer",
        "question_date": "2026/08/04 (Tue) 12:00",
        "haystack_session_ids": [
            "session-duplicate",
            "session-duplicate",
            "session-answer",
        ],
        "haystack_dates": [
            "2026/08/01 (Sat) 12:00",
            "2026/08/02 (Sun) 12:00",
            "2026/08/03 (Mon) 12:00",
        ],
        "haystack_sessions": [
            [{"role": "user", "content": "same history", "has_answer": False}],
            [{"role": "user", "content": "same history", "has_answer": False}],
            [{"role": "user", "content": "the answer", "has_answer": True}],
        ],
        "answer_session_ids": ["session-answer"],
    }


def _longmemeval_single_session_record(index: int) -> dict[str, object]:
    session_id = f"session-extra-{index}"
    return {
        "question_id": f"memory-extra-{index}",
        "question_type": "temporal-reasoning",
        "question": f"What was answer {index}?",
        "answer": f"answer {index}",
        "question_date": "2026/08/04 (Tue) 12:00",
        "haystack_session_ids": [session_id],
        "haystack_dates": ["2026/08/03 (Mon) 12:00"],
        "haystack_sessions": [
            [{"role": "user", "content": f"answer {index}", "has_answer": True}]
        ],
        "answer_session_ids": [session_id],
    }


class LongMemEvalAdapterTests(unittest.TestCase):
    def test_public_summary_keeps_official_and_product_denominators_separate(self) -> None:
        receipt = json.loads(
            (
                ROOT
                / "eval"
                / "rag-interview"
                / "longmemeval-s-cleaned-receipt.v1.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(500, receipt["caseCount"])
        self.assertEqual(
            {"official-user": 419, "product-all-turn": 470},
            receipt["retrievalEvaluableCounts"],
        )
        self.assertEqual(
            "official-user",
            receipt["adapter"]["retrievalProfiles"]["default"],
        )
        self.assertEqual(83, receipt["adapter"]["officialQrelMismatchCount"])
        self.assertFalse(receipt["source"]["corpusIncluded"])

    def test_adapter_creates_stratified_memory_splits_and_session_qrels(self) -> None:
        records = []
        for index in range(10):
            abstention = index >= 5
            question_id = f"memory-{index}{'_abs' if abstention else ''}"
            session_id = f"session-{index}"
            records.append(
                {
                    "question_id": question_id,
                    "question_type": "knowledge-update" if not abstention else "temporal-reasoning",
                    "question": f"What changed in case {index}?",
                    "answer": "unknown" if abstention else f"fact-{index}",
                    "question_date": "2026/08/04 (Tue) 12:00",
                    "haystack_session_ids": [session_id, f"distractor-{index}"],
                    "haystack_dates": [
                        "2026/08/03 (Mon) 12:00",
                        "2026/08/02 (Sun) 12:00",
                    ],
                    "haystack_sessions": [
                        [{"role": "user", "content": f"fact-{index}", "has_answer": True}],
                        [
                            {
                                "role": "user",
                                "content": "" if index == 0 else "unrelated",
                                "has_answer": False,
                            },
                            {
                                "role": "assistant",
                                "content": "non-empty companion turn",
                                "has_answer": False,
                            },
                        ],
                    ],
                    "answer_session_ids": [session_id],
                }
            )

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-") as temporary:
            source = Path(temporary) / "longmemeval.json"
            source.write_text(json.dumps(records), encoding="utf-8")
            prepared = prepare_longmemeval_dataset(
                source,
                source_url="https://huggingface.co/datasets/example/longmemeval",
                version="test-revision",
                license_reference="https://example.org/mit",
                split_seed="paw-memory-v1",
            )

        manifest = prepared["manifest"]
        self.assertEqual("memory", manifest["system"])
        self.assertEqual("memory", manifest["tool"])
        self.assertEqual(
            {"train": 6, "validation": 2, "held_out": 2},
            manifest["splitCounts"],
        )
        self.assertEqual(10, len(prepared["cases"]))
        first = next(item for item in prepared["cases"] if item["queryId"] == "memory-0")
        self.assertEqual({"session-0": 1.0}, first["relevant"])
        self.assertEqual("memory", first["system"])
        self.assertFalse(first["abstention"])
        self.assertTrue(first["retrievalEvaluable"])
        self.assertEqual("session-0", first["sessions"][0]["sessionId"])
        self.assertEqual("", first["sessions"][1]["turns"][0]["content"])
        self.assertEqual(1, prepared["adapter"]["emptyTurnCount"])
        self.assertEqual(1, prepared["adapter"]["emptyTurnAffectedCaseCount"])
        self.assertEqual(0, prepared["adapter"]["emptyAnswerTurnCount"])
        abstention = next(item for item in prepared["cases"] if item["abstention"])
        self.assertEqual("abstention", abstention["slice"])
        self.assertFalse(abstention["retrievalEvaluable"])
        self.assertNotIn("knowledgeBase", json.dumps(prepared))

    def test_adapter_separates_official_user_targets_from_product_all_turn_targets(self) -> None:
        assistant_only = _longmemeval_single_session_record(20)
        assistant_only["question_id"] = "memory-assistant-only"
        assistant_only["question_type"] = "single-session-assistant"
        assistant_only["haystack_sessions"] = [
            [
                {
                    "role": "user",
                    "content": "Please tell me the project codename.",
                    "has_answer": False,
                },
                {
                    "role": "assistant",
                    "content": "The project codename is Seaglass.",
                    "has_answer": True,
                },
            ]
        ]
        partial = _longmemeval_single_session_record(21)
        partial["question_id"] = "memory-partial-target"
        partial["question_type"] = "multi-session"
        partial["haystack_session_ids"] = ["session-user-answer", "session-derived-answer"]
        partial["haystack_dates"] = [
            "2026/08/02 (Sun) 12:00",
            "2026/08/03 (Mon) 12:00",
        ]
        partial["haystack_sessions"] = [
            [{"role": "user", "content": "I chose blue.", "has_answer": True}],
            [
                {
                    "role": "user",
                    "content": "Please infer the result.",
                    "has_answer": False,
                },
                {
                    "role": "assistant",
                    "content": "The inferred result is green.",
                    "has_answer": False,
                },
            ],
        ]
        partial["answer_session_ids"] = ["session-user-answer", "session-derived-answer"]

        records = [
            assistant_only,
            partial,
            _longmemeval_single_session_record(22),
            _longmemeval_single_session_record(23),
            _longmemeval_single_session_record(24),
            _longmemeval_single_session_record(25),
            _longmemeval_single_session_record(26),
        ]
        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-profiles-") as temporary:
            source = Path(temporary) / "longmemeval.json"
            source.write_text(json.dumps(records), encoding="utf-8")
            prepared = prepare_longmemeval_dataset(
                source,
                source_url="https://huggingface.co/datasets/example/longmemeval",
                version="test-revision",
                license_reference="https://example.org/mit",
                split_seed="paw-memory-profiles-v1",
            )

        assistant_case = next(
            item for item in prepared["cases"]
            if item["queryId"] == "memory-assistant-only"
        )
        self.assertEqual({}, assistant_case["officialRelevant"])
        self.assertEqual(
            {"session-extra-20": 1.0},
            assistant_case["productRelevant"],
        )
        self.assertFalse(assistant_case["officialRetrievalEvaluable"])
        self.assertTrue(assistant_case["productRetrievalEvaluable"])
        self.assertFalse(assistant_case["retrievalEvaluable"])
        self.assertEqual({}, assistant_case["relevant"])

        partial_case = next(
            item for item in prepared["cases"]
            if item["queryId"] == "memory-partial-target"
        )
        self.assertEqual(
            {"session-user-answer": 1.0},
            partial_case["officialRelevant"],
        )
        self.assertEqual(
            {"session-user-answer": 1.0, "session-derived-answer": 1.0},
            partial_case["productRelevant"],
        )
        self.assertEqual(2, prepared["adapter"]["officialQrelMismatchCount"])
        self.assertEqual(1, prepared["adapter"]["officialNoUserTargetCount"])
        self.assertEqual(1, prepared["adapter"]["officialPartialQrelMismatchCount"])

    def test_adapter_rejects_empty_answer_turn(self) -> None:
        record = _longmemeval_single_session_record(9)
        record["haystack_sessions"][0][0]["content"] = ""

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-empty-answer-") as temporary:
            source = Path(temporary) / "longmemeval.json"
            source.write_text(json.dumps([record]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "answer-bearing turn must not be empty"):
                prepare_longmemeval_dataset(
                    source,
                    source_url="https://huggingface.co/datasets/example/longmemeval",
                    version="test-revision",
                    license_reference="https://example.org/mit",
                    split_seed="paw-memory-empty-v1",
                )

    def test_adapter_preserves_identical_duplicate_session_ids_with_stable_refs(self) -> None:
        record = _longmemeval_duplicate_session_record()

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-duplicate-") as temporary:
            source = Path(temporary) / "longmemeval.json"
            source.write_text(
                json.dumps(
                    [
                        record,
                        _longmemeval_single_session_record(1),
                        _longmemeval_single_session_record(2),
                        _longmemeval_single_session_record(3),
                        _longmemeval_single_session_record(4),
                    ]
                ),
                encoding="utf-8",
            )
            prepared = prepare_longmemeval_dataset(
                source,
                source_url="https://huggingface.co/datasets/example/longmemeval",
                version="test-revision",
                license_reference="https://example.org/mit",
                split_seed="paw-memory-duplicates-v1",
            )

        case = next(
            item for item in prepared["cases"] if item["queryId"] == "memory-duplicate"
        )
        sessions = case["sessions"]
        self.assertEqual(3, len(sessions))
        self.assertEqual(
            ["session-duplicate", "session-duplicate:duplicate:2", "session-answer"],
            [item["sessionId"] for item in sessions],
        )
        self.assertEqual("session-duplicate", sessions[0]["sourceSessionId"])
        self.assertEqual("session-duplicate", sessions[1]["sourceSessionId"])
        self.assertEqual(1, sessions[0]["sourceOccurrence"])
        self.assertEqual(2, sessions[1]["sourceOccurrence"])
        self.assertEqual({"session-answer": 1.0}, case["relevant"])
        self.assertEqual(1, prepared["adapter"]["duplicateSessionIdGroupCount"])
        self.assertEqual(1, prepared["adapter"]["duplicateSessionOccurrenceCount"])
        self.assertEqual(1, prepared["adapter"]["duplicateSessionAffectedCaseCount"])
        self.assertEqual(0, prepared["adapter"]["duplicateRelevantSessionIdCount"])

    def test_adapter_rejects_duplicate_relevant_session_id_as_ambiguous(self) -> None:
        record = _longmemeval_duplicate_session_record()
        record["answer_session_ids"] = ["session-duplicate"]

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-relevant-duplicate-") as temporary:
            source = Path(temporary) / "longmemeval.json"
            source.write_text(json.dumps([record]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate answer session ID"):
                prepare_longmemeval_dataset(
                    source,
                    source_url="https://huggingface.co/datasets/example/longmemeval",
                    version="test-revision",
                    license_reference="https://example.org/mit",
                    split_seed="paw-memory-duplicates-v1",
                )

    def test_adapter_rejects_duplicate_session_id_with_different_content(self) -> None:
        record = _longmemeval_duplicate_session_record()
        record["haystack_sessions"][1][0]["content"] = "different history"

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-conflict-") as temporary:
            source = Path(temporary) / "longmemeval.json"
            source.write_text(json.dumps([record]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different content"):
                prepare_longmemeval_dataset(
                    source,
                    source_url="https://huggingface.co/datasets/example/longmemeval",
                    version="test-revision",
                    license_reference="https://example.org/mit",
                    split_seed="paw-memory-duplicates-v1",
                )


class SciFactAdapterTests(unittest.TestCase):
    def test_adapter_keeps_official_test_held_out_and_builds_document_qrels(self) -> None:
        corpus = [
            {"_id": "doc-1", "title": "One", "text": "Evidence one", "metadata": {}},
            {"_id": "doc-2", "title": "Two", "text": "Evidence two", "metadata": {}},
            {"_id": "doc-3", "title": "Three", "text": "Evidence three", "metadata": {}},
        ]
        queries = [
            {"_id": f"q-{index}", "text": f"Claim {index}", "metadata": {}}
            for index in range(1, 7)
        ]
        train_qrels = "query-id\tcorpus-id\tscore\n" + "\n".join(
            ["q-1\tdoc-1\t1", "q-2\tdoc-2\t1", "q-3\tdoc-3\t1", "q-4\tdoc-1\t1"]
        )
        test_qrels = "query-id\tcorpus-id\tscore\nq-5\tdoc-2\t1\nq-6\tdoc-3\t1\n"

        with tempfile.TemporaryDirectory(prefix="rag-ime-scifact-") as temporary:
            archive = Path(temporary) / "scifact.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(
                    "scifact/corpus.jsonl",
                    "\n".join(json.dumps(item) for item in corpus) + "\n",
                )
                bundle.writestr(
                    "scifact/queries.jsonl",
                    "\n".join(json.dumps(item) for item in queries) + "\n",
                )
                bundle.writestr("scifact/qrels/train.tsv", train_qrels + "\n")
                bundle.writestr("scifact/qrels/test.tsv", test_qrels)
            prepared = prepare_scifact_dataset(
                archive,
                source_url="https://example.org/scifact.zip",
                version="beir-test",
                license_reference="https://github.com/allenai/scifact/blob/master/LICENSE.md",
                split_seed="paw-scifact-v1",
            )

        self.assertEqual("knowledge", prepared["manifest"]["system"])
        self.assertEqual(
            {"train": 3, "validation": 1, "held_out": 2},
            prepared["manifest"]["splitCounts"],
        )
        self.assertEqual(3, len(prepared["documents"]))
        self.assertEqual(6, len(prepared["cases"]))
        held_out = [item for item in prepared["cases"] if item["split"] == "held_out"]
        self.assertEqual({"q-5", "q-6"}, {item["queryId"] for item in held_out})
        query = next(item for item in prepared["cases"] if item["queryId"] == "q-5")
        self.assertEqual({"doc-2": 1.0}, query["relevant"])
        self.assertEqual("knowledge", query["system"])


class EnterpriseRagAdapterTests(unittest.TestCase):
    def test_adapter_streams_documents_and_separates_qrels_from_abstention(self) -> None:
        documents = [
            {
                "doc_id": f"doc-{index}",
                "source_type": "confluence" if index % 2 == 0 else "slack",
                "title": f"Document {index}",
                "content": f"Enterprise fact {index}",
            }
            for index in range(10)
        ]
        questions = []
        for index in range(10):
            abstention = index >= 5
            questions.append(
                {
                    "question_id": f"enterprise-{index}",
                    "question_type": "info_not_found" if abstention else "basic",
                    "source_types": [] if abstention else ["confluence"],
                    "question": f"What is fact {index}?",
                    "expected_doc_ids": [] if abstention else [f"doc-{index}"],
                    "gold_answer": "not found" if abstention else f"Enterprise fact {index}",
                    "answer_facts": [] if abstention else [f"Enterprise fact {index}"],
                }
            )

        with tempfile.TemporaryDirectory(prefix="rag-ime-enterprise-") as temporary:
            root = Path(temporary)
            document_source = root / "documents.jsonl"
            question_source = root / "questions.jsonl"
            document_source.write_text(
                "\n".join(json.dumps(item) for item in documents) + "\n",
                encoding="utf-8",
            )
            question_source.write_text(
                "\n".join(json.dumps(item) for item in questions) + "\n",
                encoding="utf-8",
            )
            prepared = prepare_enterprise_rag_dataset(
                question_source,
                document_source,
                source_url="https://huggingface.co/datasets/example/enterprise-rag",
                version="test-revision",
                license_reference="https://example.org/mit",
                split_seed="paw-enterprise-v1",
            )

        self.assertEqual("knowledge", prepared["manifest"]["system"])
        self.assertEqual(
            {"train": 6, "validation": 2, "held_out": 2},
            prepared["manifest"]["splitCounts"],
        )
        self.assertEqual(10, prepared["adapter"]["documentCount"])
        self.assertEqual(5, prepared["adapter"]["retrievalEvaluableCount"])
        self.assertEqual(5, prepared["adapter"]["abstentionCount"])
        self.assertNotIn("documents", prepared)
        answerable = next(
            item for item in prepared["cases"] if item["queryId"] == "enterprise-0"
        )
        self.assertEqual({"doc-0": 1.0}, answerable["relevant"])
        self.assertTrue(answerable["retrievalEvaluable"])
        abstention = next(item for item in prepared["cases"] if item["abstentionExpected"])
        self.assertEqual({}, abstention["relevant"])
        self.assertFalse(abstention["retrievalEvaluable"])

    def test_adapter_rejects_qrels_for_unknown_documents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-enterprise-bad-") as temporary:
            root = Path(temporary)
            documents = root / "documents.jsonl"
            questions = root / "questions.jsonl"
            documents.write_text(
                json.dumps(
                    {
                        "doc_id": "doc-known",
                        "source_type": "slack",
                        "title": "Known",
                        "content": "known",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            questions.write_text(
                json.dumps(
                    {
                        "question_id": "q-unknown",
                        "question_type": "basic",
                        "source_types": ["slack"],
                        "question": "unknown?",
                        "expected_doc_ids": ["doc-missing"],
                        "gold_answer": "unknown",
                        "answer_facts": ["unknown"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown document"):
                prepare_enterprise_rag_dataset(
                    questions,
                    documents,
                    source_url="https://example.org/enterprise",
                    version="bad",
                    license_reference="https://example.org/license",
                    split_seed="bad",
                )

    def test_adapter_expands_conflicting_duplicate_logical_ids_to_physical_qrels(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-enterprise-duplicates-") as temporary:
            root = Path(temporary)
            documents = root / "documents.jsonl"
            questions = root / "questions.jsonl"
            documents.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in (
                        {
                            "doc_id": "doc-conflict",
                            "source_type": "jira",
                            "title": "Old",
                            "content": "cost-ops approves termination",
                        },
                        {
                            "doc_id": "doc-conflict",
                            "source_type": "jira",
                            "title": "New",
                            "content": "infra manager approves termination",
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            records = []
            for index in range(5):
                records.append(
                    {
                        "question_id": f"q-conflict-{index}",
                        "question_type": "conflicting_info",
                        "source_types": ["jira"],
                        "question": f"Who approves termination {index}?",
                        "expected_doc_ids": ["doc-conflict", "doc-conflict"],
                        "gold_answer": "The newer policy says infra manager.",
                        "answer_facts": ["infra manager", "cost-ops was superseded"],
                    }
                )
            questions.write_text(
                "\n".join(json.dumps(item) for item in records) + "\n",
                encoding="utf-8",
            )
            prepared = prepare_enterprise_rag_dataset(
                questions,
                documents,
                source_url="https://example.org/enterprise",
                version="duplicate-test",
                license_reference="https://example.org/license",
                split_seed="duplicate-test",
            )

        self.assertEqual(2, prepared["adapter"]["documentCount"])
        self.assertEqual(1, prepared["adapter"]["logicalDocumentCount"])
        self.assertEqual(1, prepared["adapter"]["duplicateLogicalIdCount"])
        self.assertEqual(
            5,
            prepared["adapter"]["duplicateExpectedDocumentReferenceCount"],
        )
        case = next(item for item in prepared["cases"] if item["queryId"] == "q-conflict-0")
        self.assertEqual(2, len(case["relevant"]))
        self.assertTrue(
            all(item.startswith("doc-conflict:v:") for item in case["relevant"])
        )


class CrudRagAdapterTests(unittest.TestCase):
    def test_adapter_builds_explicit_derived_qrels_and_deterministic_distractors(self) -> None:
        payload = {
            "questanswer_1doc": [],
            "questanswer_2docs": [],
            "questanswer_3docs": [],
        }
        for index in range(10):
            for count in (1, 2, 3):
                record = {
                    "ID": f"crud-{count}-{index}",
                    "questions": f"问题 {count}-{index}",
                    "answers": f"答案 {count}-{index}",
                }
                for document_index in range(1, count + 1):
                    record[f"news{document_index}"] = (
                        f"第 {count}-{index}-{document_index} 条中文知识文档。"
                    )
                payload[f"questanswer_{count}doc{'s' if count > 1 else ''}"].append(record)

        with tempfile.TemporaryDirectory(prefix="rag-ime-crud-") as temporary:
            root = Path(temporary)
            source = root / "split_merged.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            corpus = root / "docs"
            corpus.mkdir()
            (corpus / "part-1").write_text(
                "\n".join(f"无关中文文档 {index}" for index in range(20)) + "\n",
                encoding="utf-8",
            )
            prepared = prepare_crud_rag_dataset(
                source,
                corpus,
                source_url="https://github.com/example/crud-rag",
                version="test-revision",
                license_reference="https://github.com/example/crud-rag",
                split_seed="paw-crud-v1",
                distractor_limit=5,
            )
            repeated = prepare_crud_rag_dataset(
                source,
                corpus,
                source_url="https://github.com/example/crud-rag",
                version="test-revision",
                license_reference="https://github.com/example/crud-rag",
                split_seed="paw-crud-v1",
                distractor_limit=5,
            )

        self.assertEqual(
            "crud-rag-chinese-qa-derived-qrels",
            prepared["adapter"]["name"],
        )
        self.assertEqual(
            {"train": 18, "validation": 6, "held_out": 6},
            prepared["manifest"]["splitCounts"],
        )
        self.assertEqual(30, len(prepared["cases"]))
        self.assertEqual(65, len(prepared["documents"]))
        self.assertEqual(5, prepared["adapter"]["distractorCount"])
        three_doc = next(item for item in prepared["cases"] if item["slice"] == "qa_3doc")
        self.assertEqual(3, len(three_doc["relevant"]))
        self.assertTrue(prepared["adapter"]["derivedQrels"])
        self.assertEqual(prepared, repeated)
        self.assertNotIn("memory", json.dumps(prepared).lower())


class SweBenchVerifiedAdapterTests(unittest.TestCase):
    def test_adapter_selects_pinned_subset_without_returning_gold_patch(self) -> None:
        rows = []
        difficulties = ["<15 min fix", "15 min - 1 hour", "1-4 hours"]
        for index in range(12):
            rows.append(
                {
                    "repo": f"org/repo-{index % 3}",
                    "instance_id": f"org__repo-{index % 3}-{index}",
                    "base_commit": f"{index:040x}",
                    "patch": f"gold patch {index}",
                    "test_patch": f"hidden tests {index}",
                    "problem_statement": f"Fix issue {index}",
                    "hints_text": "",
                    "created_at": "2025-01-01T00:00:00Z",
                    "version": "1.0",
                    "FAIL_TO_PASS": json.dumps([f"test_{index}"]),
                    "PASS_TO_PASS": json.dumps(["test_existing"]),
                    "environment_setup_commit": f"{index + 1:040x}",
                    "difficulty": difficulties[index % len(difficulties)],
                }
            )

        with tempfile.TemporaryDirectory(prefix="rag-ime-swe-") as temporary:
            source = Path(temporary) / "swe.jsonl"
            source.write_text(
                "\n".join(json.dumps(item) for item in rows) + "\n",
                encoding="utf-8",
            )
            prepared = prepare_swe_bench_verified_dataset(
                source,
                source_url="https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified",
                version="test-revision",
                license_reference="https://example.org/swe-license-note",
                split_seed="paw-swe-interview-v1",
                interview_size=6,
            )

        self.assertEqual(12, prepared["adapter"]["fullCount"])
        self.assertEqual(6, prepared["adapter"]["interviewCount"])
        self.assertEqual(6, len(prepared["interviewInstanceIds"]))
        self.assertEqual(64, len(prepared["interviewSplitSha256"]))
        self.assertEqual(12, len(prepared["agentCases"]))
        encoded = json.dumps(prepared["agentCases"])
        self.assertNotIn("gold patch", encoded)
        self.assertNotIn("hidden tests", encoded)
        self.assertNotIn("patch", encoded.lower())
        verifier = prepared["verifierCases"][0]
        self.assertNotIn("goldPatch", verifier)
        self.assertEqual(64, len(verifier["goldPatchSha256"]))


if __name__ == "__main__":
    unittest.main()
