from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rag_ime.cli import main
from rag_ime.memory_eval import run_memory_optimizer_eval


class MemoryOptimizerEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "RAG_IME_MEMORY_OPTIMIZER",
                "RAG_IME_MEMORY_OPTIMIZER_TRACE",
                "RAG_IME_MEMORY_OPTIMIZER_MAX_MS",
            )
        }

    def tearDown(self) -> None:
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_run_memory_optimizer_eval_passes_regression_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-eval-test-") as tmp:
            cases_path = Path(tmp) / "cases.jsonl"
            cases_path.write_text(_sample_cases_jsonl(), encoding="utf-8")

            report = run_memory_optimizer_eval(
                cases_file=cases_path,
                project="wisdom-weasel-rag-ime",
                repeat=1,
                max_visible_candidates=4,
                max_side_candidates=2,
                latency_budget_ms=150,
                optimizer_max_ms=50,
            )

        self.assertTrue(report["gatePassed"])
        self.assertEqual(report["failedCases"], 0)
        cases = {item["caseId"]: item for item in report["cases"]}
        self.assertIn("连续预测", cases["stable-memory-surfaces"]["ragCandidateSurfaces"])
        self.assertIn("recent_committed_echo", cases["recent-echo-blocked"]["blockedReasons"])
        self.assertEqual(cases["repeated-skip-cooldown"]["ragCandidateCount"], 0)

    def test_repository_memory_optimizer_eval_covers_plan_cases(self) -> None:
        cases_path = Path("docs/eval/memory_optimizer_cases.jsonl")

        report = run_memory_optimizer_eval(
            cases_file=cases_path,
            project="wisdom-weasel-rag-ime",
            repeat=1,
            max_visible_candidates=4,
            max_side_candidates=2,
            latency_budget_ms=150,
            optimizer_max_ms=50,
        )

        self.assertTrue(report["gatePassed"])
        self.assertEqual(report["failedCases"], 0)
        self.assertEqual(report["repeat"]["baseCaseCount"], 14)
        cases = {item["caseId"]: item for item in report["cases"]}
        self.assertEqual(cases["old-raw-input-echo-blocked"]["filteredSuggestionCount"], 1)
        self.assertEqual(cases["accepted-phrase-not-promoted-in-unrelated-context"]["ragCandidateCount"], 0)
        self.assertEqual(cases["cold-knowledge-disabled-by-default"]["blockedReasons"], ["cold_knowledge_disabled"])
        self.assertEqual(cases["rollback-cleanup-diff"]["cleanup"]["applyRollback"]["rollbackStatus"], "rolled_back")

    def test_cli_eval_memory_optimizer_returns_nonzero_on_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-eval-cli-") as tmp:
            cases_path = Path(tmp) / "failing.jsonl"
            db_path = Path(tmp) / "unused.sqlite"
            cases_path.write_text(
                json.dumps(
                    {
                        "id": "will-fail",
                        "query": "sequenceFork",
                        "rawInput": "sequenceFork",
                        "preedit": "sequenceFork",
                        "committedContext": "我们要做 continuation 优化",
                        "rimeCandidates": ["sequenceFork"],
                        "mustContainAny": ["不存在的候选"],
                        "memoryState": {
                            "items": [
                                {
                                    "memoryId": "stable:sequencefork-continuation",
                                    "kind": "stable_memory",
                                    "text": "连续预测",
                                    "summary": "sequenceFork continuation candidate",
                                    "tags": ["sequenceFork", "continuation", "连续预测"],
                                    "status": "approved",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--db-path",
                        str(db_path),
                        "eval-memory-optimizer",
                        str(cases_path),
                        "--optimizer-max-ms",
                        "50",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertFalse(payload["gatePassed"])
        self.assertEqual(payload["failedCases"], 1)


def _sample_cases_jsonl() -> str:
    cases = [
        {
            "id": "stable-memory-surfaces",
            "description": "Stable memory can surface a short phrase for a related sequenceFork query.",
            "query": "sequenceFork",
            "rawInput": "sequenceFork",
            "preedit": "sequenceFork",
            "committedContext": "我们要做 continuation 优化",
            "rimeCandidates": ["sequenceFork"],
            "mustContainAny": ["连续预测"],
            "minRagCandidates": 1,
            "maxOptimizerLatencyMs": 50,
            "memoryState": {
                "items": [
                    {
                        "memoryId": "stable:sequencefork-continuation",
                        "kind": "stable_memory",
                        "text": "连续预测",
                        "summary": "sequenceFork continuation candidate",
                        "tags": ["sequenceFork", "continuation", "连续预测"],
                        "status": "approved",
                        "qualityScore": 0.9,
                        "confidence": 0.9,
                        "metadata": {"direct_candidate_allowed": True},
                    }
                ]
            },
        },
        {
            "id": "recent-echo-blocked",
            "description": "Fresh committed phrase should not echo back into the side candidate lane.",
            "query": "连续",
            "rawInput": "",
            "preedit": "",
            "committedContext": "我想继续写连续",
            "rimeCandidates": ["连续"],
            "mustNotContain": ["连续预测"],
            "mustHaveBlockedReasons": ["recent_committed_echo"],
            "maxRagCandidates": 0,
            "maxOptimizerLatencyMs": 50,
            "memoryState": {
                "events": [
                    {
                        "text": "连续预测",
                        "recentContext": "RAG 输入法需要更好的候选",
                        "tags": ["phrase-memory"],
                    }
                ]
            },
        },
        {
            "id": "tombstone-suppresses-candidate",
            "description": "Normalized text tombstones should keep phrase candidates out of the IME lane.",
            "query": "sequenceFork",
            "rawInput": "sequenceFork",
            "preedit": "sequenceFork",
            "committedContext": "我们要做 continuation 优化",
            "rimeCandidates": ["sequenceFork"],
            "mustNotContain": ["连续预测"],
            "maxRagCandidates": 0,
            "maxOptimizerLatencyMs": 50,
            "memoryState": {
                "items": [
                    {
                        "memoryId": "stable:sequencefork-continuation",
                        "kind": "stable_memory",
                        "text": "连续预测",
                        "summary": "sequenceFork continuation candidate",
                        "tags": ["sequenceFork", "continuation", "连续预测"],
                        "status": "approved",
                    }
                ],
                "tombstones": [
                    {
                        "targetType": "normalized_text",
                        "targetValue": "连续预测",
                        "reason": "manual-test",
                    }
                ],
            },
        },
        {
            "id": "repeated-skip-cooldown",
            "description": "Repeated skips should suppress the same memory candidate in the optimizer lane.",
            "query": "sequenceFork",
            "rawInput": "sequenceFork",
            "preedit": "sequenceFork",
            "committedContext": "我们要做 continuation 优化",
            "committedContextHash": "ctx:memory-eval-skip",
            "rimeCandidates": ["sequenceFork"],
            "mustNotContain": ["连续预测"],
            "maxRagCandidates": 0,
            "maxOptimizerLatencyMs": 50,
            "memoryState": {
                "items": [
                    {
                        "memoryId": "stable:sequencefork-continuation",
                        "kind": "stable_memory",
                        "text": "连续预测",
                        "summary": "sequenceFork continuation candidate",
                        "tags": ["sequenceFork", "continuation", "连续预测"],
                        "status": "approved",
                    }
                ],
                "feedback": [
                    {
                        "event": "skipped",
                        "candidateId": "stable:sequencefork-continuation",
                        "candidateText": "连续预测",
                        "sourceType": "memory",
                        "contextHash": "ctx:memory-eval-skip",
                        "timestampMs": 1,
                    },
                    {
                        "event": "skipped",
                        "candidateId": "stable:sequencefork-continuation",
                        "candidateText": "连续预测",
                        "sourceType": "memory",
                        "contextHash": "ctx:memory-eval-skip",
                        "timestampMs": 2,
                    },
                ],
            },
        },
    ]
    return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in cases)
