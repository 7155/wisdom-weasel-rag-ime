from __future__ import annotations

import copy
import unittest

from rag_ime.rag_agent_ablation import (
    SAFETY_CASE_ID,
    flat_retrieval_metrics,
    score_agent_lane,
    select_agent_held_out_cases,
)


class RagAgentAblationTests(unittest.TestCase):
    def test_selection_is_slice_aware_and_does_not_depend_on_labels_or_answers(self) -> None:
        cases = [
            {
                "queryId": f"q-{slice_name}-{index}",
                "query": f"question {slice_name} {index}",
                "answer": f"answer {index}",
                "relevant": {f"doc-{slice_name}-{index}": 1.0},
                "split": "held_out",
                "slice": slice_name,
                "retrievalEvaluable": True,
            }
            for slice_name in ("one", "two", "three")
            for index in range(3)
        ]

        first = select_agent_held_out_cases(cases, limit=4, seed="fixed")
        changed = copy.deepcopy(cases)
        for item in changed:
            item["answer"] = "changed"
            item["relevant"] = {"different-doc": 9.0}
        second = select_agent_held_out_cases(changed, limit=4, seed="fixed")

        self.assertEqual(
            [item["queryId"] for item in first],
            [item["queryId"] for item in second],
        )
        self.assertEqual({"one", "two", "three"}, {item["slice"] for item in first})

        excluded = select_agent_held_out_cases(
            cases,
            limit=4,
            seed="fixed",
            excluded_query_ids={str(first[0]["queryId"])},
        )
        self.assertNotIn(first[0]["queryId"], {item["queryId"] for item in excluded})

    def test_lane_score_uses_gateway_hits_citations_answers_and_abstention(self) -> None:
        cases = [
            {
                "queryId": "q-1",
                "answer": "审批人是林岚",
                "relevant": {"doc-a": 1.0},
                "slice": "one",
            },
            {
                "queryId": "q-2",
                "answer": "期限为三十天",
                "relevant": {"doc-b": 1.0},
                "slice": "one",
            },
        ]
        ledger = {
            "items": [
                self._search("q-1", ["doc-x", "doc-a"]),
                self._search("q-2", ["doc-b"]),
                self._search(SAFETY_CASE_ID, []),
            ]
        }
        assistant = (
            '{"cases":['
            '{"caseId":"q-1","answer":"林岚是审批人","citations":["doc-a"],"abstained":false},'
            '{"caseId":"q-2","answer":"期限为三十天","citations":["doc-b"],"abstained":false},'
            '{"caseId":"safety-not-found","answer":"证据不足","citations":[],"abstained":true}'
            "]}"
        )

        score = score_agent_lane(
            lane="baseline",
            cases=cases,
            ledger=ledger,
            assistant_text=assistant,
            max_searches_per_case=1,
        )

        metrics = flat_retrieval_metrics(score)
        self.assertAlmostEqual(0.75, metrics["mrr"])
        self.assertEqual(1.0, score["agentMetrics"]["citationSuccessRate"])
        self.assertEqual(1.0, score["agentMetrics"]["answerCharPrecision"])
        self.assertEqual(1.0, score["agentMetrics"]["answerCharRecall"])
        self.assertEqual(1.0, score["agentMetrics"]["answerSuccessRate"])
        self.assertTrue(score["hardEvidence"]["abstention"])
        self.assertTrue(score["hardEvidence"]["parameterBounded"])

    def test_protocol_aliases_do_not_replace_source_query_ids(self) -> None:
        cases = [
            {
                "queryId": "crud-long-source-id",
                "evaluationCaseId": "case-01",
                "answer": "林岚",
                "relevant": {"doc-a": 1.0},
                "slice": "one",
            }
        ]
        ledger = {
            "items": [
                self._search("case-01", ["doc-a"]),
                self._search(SAFETY_CASE_ID, []),
            ]
        }
        assistant = (
            '{"cases":['
            '{"caseId":"case-01","answer":"林岚","citations":["doc-a"],"abstained":false},'
            '{"caseId":"safety-not-found","answer":"证据不足","citations":[],"abstained":true}'
            "]}"
        )

        score = score_agent_lane(
            lane="baseline",
            cases=cases,
            ledger=ledger,
            assistant_text=assistant,
            max_searches_per_case=1,
        )

        self.assertEqual("crud-long-source-id", score["retrievalCases"][0]["queryId"])
        self.assertEqual("case-01", score["retrievalCases"][0]["evaluationCaseId"])
        self.assertEqual("case-01", score["answerCases"][0]["evaluationCaseId"])
        self.assertTrue(score["hardEvidence"]["parameterBounded"])

    def test_short_citation_refs_resolve_to_exact_source_ids(self) -> None:
        cases = [
            {
                "queryId": "q-short-ref",
                "answer": "审批人是林岚",
                "relevant": {"opaque-document-identifier-123456789": 1.0},
                "slice": "one",
            }
        ]
        ledger = {
            "items": [
                {
                    "operation": "search",
                    "ok": True,
                    "args": {"evaluationCaseId": "q-short-ref"},
                    "resultSummary": {
                        "hits": [
                            {
                                "externalDocumentId": "opaque-document-identifier-123456789",
                                "citationRef": "K-12ab34cd56",
                            }
                        ]
                    },
                },
                self._search(SAFETY_CASE_ID, []),
            ]
        }
        assistant = (
            '{"cases":['
            '{"caseId":"q-short-ref","answer":"审批人是林岚",'
            '"citations":["K-12ab34cd56"],"abstained":false},'
            '{"caseId":"safety-not-found","answer":"证据不足",'
            '"citations":[],"abstained":true}'
            "]}"
        )

        score = score_agent_lane(
            lane="baseline",
            cases=cases,
            ledger=ledger,
            assistant_text=assistant,
            max_searches_per_case=1,
        )

        answer = score["answerCases"][0]
        self.assertEqual(["K-12ab34cd56"], answer["citationTokens"])
        self.assertEqual(
            ["opaque-document-identifier-123456789"],
            answer["citations"],
        )
        self.assertEqual(1.0, score["agentMetrics"]["citationRecall"])
        self.assertTrue(score["hardEvidence"]["citationResolution"])

    def test_supported_abstention_has_resolved_empty_citations(self) -> None:
        cases = [
            {
                "queryId": "q-no-evidence",
                "answer": "库中参考答案",
                "relevant": {"doc-missing": 1.0},
                "slice": "one",
            }
        ]
        ledger = {
            "items": [
                self._search("q-no-evidence", []),
                self._search(SAFETY_CASE_ID, []),
            ]
        }
        assistant = (
            '{"cases":['
            '{"caseId":"q-no-evidence","answer":"证据不足","citations":[],"abstained":true},'
            '{"caseId":"safety-not-found","answer":"证据不足","citations":[],"abstained":true}'
            "]}"
        )

        score = score_agent_lane(
            lane="baseline",
            cases=cases,
            ledger=ledger,
            assistant_text=assistant,
            max_searches_per_case=1,
        )

        self.assertTrue(score["hardEvidence"]["citationResolution"])
        self.assertEqual(0.0, score["agentMetrics"]["citationRecall"])
        self.assertTrue(score["answerCases"][0]["abstained"])

    @staticmethod
    def _search(case_id: str, documents: list[str]) -> dict[str, object]:
        return {
            "operation": "search",
            "ok": True,
            "args": {"evaluationCaseId": case_id},
            "resultSummary": {
                "hits": [
                    {"externalDocumentId": document_id}
                    for document_id in documents
                ]
            },
        }


if __name__ == "__main__":
    unittest.main()
