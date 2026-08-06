from __future__ import annotations

import unittest

from scripts.run_rag_agent_ablation import (
    _agentic_parent_query_policy_passes,
    _agents_tool_receipts,
    _answer_judge_failure_is_retryable,
    _answer_judge_format_repair_prompt,
    _answer_judge_prompt,
    _apply_answer_judgments,
    _knowledge_base_retrieval_config,
    _lane_prompt,
    _last_assistant_snapshot_text,
    _merge_event_evidence,
    _coverage_critic_completed,
    _require_actual_metal_runtime,
    _preflight_failure_report,
    _production_baseline_record,
    _parse_answer_judge_rubrics,
    _parse_answer_judgments,
    _runtime_failure_category,
    _search_parameter_policy_passes,
    _started_tool_names,
)


class RunRagAgentAblationTests(unittest.TestCase):
    def test_preflight_failure_is_a_non_score_receipt_before_sandbox(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as root:
            root_path = Path(root)
            prepared = root_path / "prepared.json"
            retrieval = root_path / "retrieval.json"
            prepared.write_text("{}\n", encoding="utf-8")
            retrieval.write_text("{}\n", encoding="utf-8")
            report = _preflight_failure_report(
                started_at_ms=100,
                prepared_path=prepared,
                retrieval_report_path=retrieval,
                slice_manifest={"benchmarkId": "fixture"},
                evaluation_cases=[
                    {"queryId": "q-1", "evaluationCaseId": "case-01"}
                ],
                calibration_no_metal=False,
                development_only=False,
                embedding={},
                failure="RuntimeError: No Metal device available",
            )

        self.assertFalse(report["passed"])
        self.assertFalse(report["scoreEligible"])
        self.assertFalse(report["formalAcceptanceEligible"])
        self.assertTrue(report["cleanupPassed"])
        self.assertFalse(report["preflight"]["accepted"])
        self.assertFalse(report["preflight"]["sandboxAllocated"])
        self.assertTrue(report["reportSha256"])

    def test_metal_preflight_requires_an_evaluated_device_operation(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        failed = SimpleNamespace(returncode=1, stdout="", stderr="No Metal device")
        with patch("scripts.run_rag_agent_ablation.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "Metal preflight failed"):
                _require_actual_metal_runtime()

        passed = SimpleNamespace(returncode=0, stdout="metal-probe-ok\n", stderr="")
        with patch("scripts.run_rag_agent_ablation.subprocess.run", return_value=passed):
            _require_actual_metal_runtime()

    def test_knowledge_base_config_excludes_independent_rerank_metadata(self) -> None:
        projected = _knowledge_base_retrieval_config(
            {
                "mode": "hybrid",
                "topK": 10,
                "threshold": 0,
                "lexicalWeight": 1,
                "denseWeight": 2,
                "graphEnabled": False,
                "graphWeight": 0,
                "rrfK": 20,
                "candidateMultiplier": 8,
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
                "rerankerFingerprint": "fixture:sha256:" + "a" * 64,
            }
        )

        self.assertEqual("hybrid", projected["mode"])
        self.assertEqual(8, projected["candidateMultiplier"])
        self.assertNotIn("rerankEnabled", projected)
        self.assertNotIn("rerankCandidateDepth", projected)
        self.assertNotIn("rerankerFingerprint", projected)

    def test_production_baseline_record_prefers_current_report_field(self) -> None:
        current = {"configSha256": "current"}
        legacy = {"configSha256": "legacy"}

        selected = _production_baseline_record(
            {
                "heldOut": {
                    "productionLexicalFloor": current,
                    "baseline": legacy,
                }
            }
        )

        self.assertIs(current, selected)

    def test_snapshot_recovers_tool_evidence_without_double_counting(self) -> None:
        primary = [
            {
                "eventId": "session:1",
                "eventType": "tool_started",
                "payload": {"toolCallId": "call-skill", "toolName": "skill_load"},
            }
        ]
        snapshot_events = [
            primary[0],
            {
                "eventId": "session:2",
                "eventType": "tool_started",
                "payload": {"toolCallId": "call-tool", "toolName": "tool_load"},
            },
        ]
        messages = [
            {
                "role": "assistant",
                "blocks": [
                    {
                        "id": "block-skill",
                        "type": "tool_call",
                        "data": {"toolCallId": "call-skill", "toolName": "skill_load"},
                    },
                    {
                        "id": "block-rag",
                        "type": "tool_call",
                        "data": {"toolCallId": "call-rag", "toolName": "rag_benchmark"},
                    },
                ],
            }
        ]

        merged = _merge_event_evidence(primary, snapshot_events)

        self.assertEqual(2, len(merged))
        self.assertEqual(
            ["skill_load", "tool_load", "rag_benchmark"],
            _started_tool_names(merged, messages),
        )

    def test_provider_transient_retry_requires_failure_before_any_gateway_call(self) -> None:
        events = [
            {
                "eventType": "turn_failed",
                "payload": {"error": "fetch failed"},
            }
        ]

        self.assertEqual(
            "provider_transient_before_tool",
            _runtime_failure_category(
                terminal="turn_failed",
                error="",
                events=events,
                ledger={"itemCount": 0},
            ),
        )
        self.assertEqual(
            "turn_failed",
            _runtime_failure_category(
                terminal="turn_failed",
                error="",
                events=events,
                ledger={"itemCount": 1},
            ),
        )

    def test_answer_judge_retry_is_terminal_only_and_not_score_based(self) -> None:
        self.assertTrue(
            _answer_judge_failure_is_retryable(
                "RuntimeError: answer judge ended with turn_failed"
            )
        )
        self.assertFalse(
            _answer_judge_failure_is_retryable(
                "RuntimeError: answer judge output is schema-invalid"
            )
        )
        self.assertFalse(
            _answer_judge_failure_is_retryable("correctnessByLane.agentic=0.5")
        )

    def test_bound_run_prompt_does_not_disclose_random_run_id(self) -> None:
        prompt = _lane_prompt(
            lane="baseline",
            run_id="a" * 32,
            cases=[{"queryId": "q-1", "query": "问题"}],
            retrieval_config={"mode": "lexical"},
        )

        self.assertNotIn("a" * 32, prompt)
        self.assertIn("不要传 runId", prompt)

    def test_agentic_prompt_requires_parent_two_pass_and_one_coverage_critic(self) -> None:
        prompt = _lane_prompt(
            lane="agentic",
            run_id="b" * 32,
            cases=[{"queryId": "q-1", "query": "谁批准了预算？"}],
            retrieval_config={
                "mode": "dense",
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
        )

        self.assertIn("agents.delegate", prompt)
        self.assertIn('"op":"delegate"', prompt)
        self.assertIn('"tasks":[', prompt)
        self.assertEqual(1, prompt.count('"agent":"reviewer"'))
        self.assertIn('"wait":true', prompt)
        self.assertIn("不得调用 agents.catalog", prompt)
        self.assertIn("第一阶段由父 Agent", prompt)
        self.assertIn("DYNAMIC_FIRST_PASS_EVIDENCE_PACKET", prompt)
        self.assertIn("必须把 task 中的 DYNAMIC_FIRST_PASS_EVIDENCE_PACKET 替换", prompt)
        self.assertIn("reviewer 不得调用任何 Tool", prompt)
        self.assertIn("父 Agent 必须对每个真实 case 再做且只做一次 search", prompt)
        self.assertIn("不得依赖默认值或省略 rerank 参数", prompt)
        self.assertIn("rerank=true", prompt)
        self.assertIn("rerankCandidateDepth=40", prompt)
        self.assertIn("topK=10", prompt)
        self.assertEqual(1, prompt.count('"caseId":"q-1"'))
        self.assertIn("query 必须逐字复制", prompt)
        self.assertIn("每个真实 case 严格两次父级 search", prompt)
        self.assertIn("safety 严格一次", prompt)
        self.assertIn("最终合成以两轮父级 search 正文为唯一事实依据", prompt)
        self.assertIn("所有直接佐证来源", prompt)
        self.assertNotIn("b" * 32, prompt)

    def test_agentic_prompt_uses_one_batch_coverage_critic(self) -> None:
        prompt = _lane_prompt(
            lane="agentic",
            run_id="partition-run",
            cases=[
                {"queryId": f"q-{index}", "query": f"问题 {index}"}
                for index in range(1, 5)
            ],
            retrieval_config={
                "mode": "dense",
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
        )

        self.assertIn("CriticCallShape=", prompt)
        self.assertEqual(1, prompt.count('"op":"delegate"'))
        self.assertEqual(1, prompt.count('"agent":"reviewer"'))
        for index in range(1, 5):
            self.assertEqual(1, prompt.count(f'"caseId":"q-{index}"'))

    def test_coverage_critic_requires_one_completed_child_without_searches(self) -> None:
        runs = [{"childSessionId": "child-a", "state": "completed"}]

        self.assertTrue(
            _coverage_critic_completed(child_runs=runs, child_searches=[])
        )
        self.assertFalse(
            _coverage_critic_completed(
                child_runs=runs,
                child_searches=[{"operation": "search", "ok": True}],
            )
        )
        self.assertFalse(
            _coverage_critic_completed(
                child_runs=[{"childSessionId": "child-a", "state": "failed"}],
                child_searches=[],
            )
        )

    def test_lane_prompt_requires_atomic_answer_and_evidence_ledger(self) -> None:
        prompt = _lane_prompt(
            lane="agentic",
            run_id="c" * 32,
            cases=[
                {
                    "queryId": "q-1",
                    "query": "哪些国家下降，具体覆盖率和排名变化是什么？",
                }
            ],
            retrieval_config={
                "mode": "dense",
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
        )

        self.assertIn("逐 case 的证据账本", prompt)
        self.assertIn("名称、数字、日期、比较方向和行动", prompt)
        self.assertIn("每个问题子项", prompt)
        self.assertIn("citations 取这些直接证据来源 citationRef 的去重并集", prompt)
        self.assertIn("只写问题明确要求的槽位", prompt)
        self.assertIn("不复制未被提问的背景", prompt)
        self.assertIn("短 citationRef", prompt)
        self.assertIn("不得手工抄写 externalDocumentId", prompt)
        self.assertIn("不得因此整题拒答", prompt)
        self.assertIn("枚举容器", prompt)

    def test_agentic_parent_query_policy_requires_exact_then_distinct_query(self) -> None:
        cases = [
            {
                "evaluationCaseId": "case-01",
                "query": "原始问题一",
            },
            {
                "evaluationCaseId": "case-02",
                "query": "原始问题二",
            },
        ]
        ledger = {
            "items": [
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-01",
                        "query": "原始问题一",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-02",
                        "query": "原始问题二",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "safety-not-found",
                        "query": "虚构项目‘紫微零号’在2099年的预算批准人是谁？",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-01",
                        "query": "主体一 被问槽位 直接证据",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-02",
                        "query": "主体二 被问槽位 直接证据",
                    },
                },
                {
                    "sessionId": "child",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-01",
                        "query": "child rewrite",
                    },
                },
            ]
        }

        self.assertTrue(
            _agentic_parent_query_policy_passes(
                ledger,
                parent_session_id="parent",
                cases=cases,
            )
        )
        ledger["items"][0]["args"]["query"] = "缩短问题"
        self.assertFalse(
            _agentic_parent_query_policy_passes(
                ledger,
                parent_session_id="parent",
                cases=cases,
            )
        )
        ledger["items"][0]["args"]["query"] = "原始问题一"
        ledger["items"][3]["args"]["query"] = "原始问题一"
        self.assertFalse(
            _agentic_parent_query_policy_passes(
                ledger,
                parent_session_id="parent",
                cases=cases,
            )
        )

    def test_answer_judge_accepts_concise_answers_and_rejects_incomplete_lists(self) -> None:
        prompt = _answer_judge_prompt(
            [
                {
                    "caseId": "case-01",
                    "question": "哪两军参与？",
                    "referenceAnswer": "演习安排攻击军与防卫军参与。",
                    "evidenceDocuments": [
                        {
                            "evidenceId": "E1",
                            "text": "演习由攻击军与防卫军共同参与。",
                        }
                    ],
                    "candidates": [
                        {
                            "candidateId": "C1",
                            "answer": "攻击军与防卫军",
                            "abstained": False,
                            "evidenceIds": ["E1"],
                        }
                    ],
                }
            ]
        )

        self.assertIn("A concise span is correct", prompt)
        self.assertIn("multi-part", prompt)
        self.assertIn("future expansion plan", prompt)
        self.assertIn("candidate's own evidenceIds", prompt)
        self.assertIn("演习由攻击军与防卫军共同参与", prompt)
        self.assertNotIn("baseline", prompt)
        output = (
            '{"caseRubrics":[{"caseId":"case-01","requiredFacts":['
            '{"factId":"F1","description":"the two named armies"}]}],'
            '"judgments":['
            '{"caseId":"case-01","candidateId":"C1",'
            '"coveredFactIds":["F1"],"hasContradiction":false,'
            '"hasUnsupportedMaterial":false,'
            '"correct":true,"reasonCode":"correct"}]}'
        )
        rubrics = _parse_answer_judge_rubrics(
            output,
            expected_case_ids={"case-01"},
        )
        self.assertEqual("the two named armies", rubrics[0]["requiredFacts"][0]["description"])
        parsed = _parse_answer_judgments(
            output,
            expected_pairs={("case-01", "C1")},
        )
        self.assertTrue(parsed[0]["correct"])
        with self.assertRaisesRegex(RuntimeError, "omitted"):
            _parse_answer_judgments(
                '{"caseRubrics":[{"caseId":"case-01","requiredFacts":['
                '{"factId":"F1","description":"the two named armies"}]}],'
                '"judgments":[]}',
                expected_pairs={("case-01", "C1")},
            )

        repair = _answer_judge_format_repair_prompt(
            expected_pairs={("case-01", "C1")},
        )
        self.assertIn("failed only the machine-readable schema", repair)
        self.assertIn("do not use any score", repair)
        self.assertIn('"caseId":"case-01"', repair)
        self.assertIn('"candidateId":"C1"', repair)

    def test_answer_judgment_keeps_raw_f1_and_controls_task_success(self) -> None:
        lane_records = [
            {
                "lane": "baseline",
                "score": {
                    "answerCases": [
                        {
                            "evaluationCaseId": "case-01",
                            "answerCharF1": 1 / 3,
                            "answerSuccess": False,
                            "toolSuccess": True,
                            "citationSuccess": True,
                            "agentSuccess": False,
                        }
                    ],
                    "agentMetrics": {
                        "answerCharF1": 1 / 3,
                        "answerSuccessRate": 0.0,
                        "agentSuccessRate": 0.0,
                    },
                },
            }
        ]
        judgments = [
            {
                "lane": "baseline",
                "evaluationCaseId": "case-01",
                "correct": True,
                "reasonCode": "correct",
            }
        ]

        _apply_answer_judgments(lane_records, judgments)

        answer = lane_records[0]["score"]["answerCases"][0]
        metrics = lane_records[0]["score"]["agentMetrics"]
        self.assertAlmostEqual(1 / 3, answer["answerCharF1"])
        self.assertFalse(answer["answerCharF1Success"])
        self.assertTrue(answer["answerJudgeCorrect"])
        self.assertTrue(answer["agentSuccess"])
        self.assertEqual(0.0, metrics["answerCharF1SuccessRate"])
        self.assertEqual(1.0, metrics["answerJudgeCorrectnessRate"])
        self.assertEqual(1.0, metrics["agentSuccessRate"])

    def test_search_parameter_policy_requires_frozen_reranker_contract(self) -> None:
        ledger = {
            "items": [
                {
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "baseAlias": "benchmark",
                        "evaluationCaseId": "case-01",
                        "mode": "dense",
                        "topK": 10,
                        "threshold": 0,
                        "rerank": True,
                        "rerankCandidateDepth": 40,
                    },
                }
            ]
        }
        config = {
            "mode": "dense",
            "rerankEnabled": True,
            "rerankCandidateDepth": 40,
        }

        self.assertTrue(
            _search_parameter_policy_passes(
                ledger,
                lane="tuned",
                retrieval_config=config,
            )
        )
        ledger["items"][0]["args"]["rerankCandidateDepth"] = 20
        self.assertFalse(
            _search_parameter_policy_passes(
                ledger,
                lane="tuned",
                retrieval_config=config,
            )
        )

    def test_agentic_parameter_policy_requires_parent_top_ten_for_both_passes(self) -> None:
        config = {
            "mode": "dense",
            "rerankEnabled": True,
            "rerankCandidateDepth": 40,
        }
        ledger = {
            "items": [
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "baseAlias": "benchmark",
                        "evaluationCaseId": "case-01",
                        "mode": "dense",
                        "topK": 10,
                        "threshold": 0,
                        "rerank": True,
                        "rerankCandidateDepth": 40,
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "baseAlias": "benchmark",
                        "evaluationCaseId": "case-01",
                        "mode": "dense",
                        "topK": 10,
                        "threshold": 0,
                        "rerank": True,
                        "rerankCandidateDepth": 40,
                    },
                },
            ]
        }

        self.assertTrue(
            _search_parameter_policy_passes(
                ledger,
                lane="agentic",
                retrieval_config=config,
            )
        )
        ledger["items"][1]["args"]["topK"] = 5
        self.assertFalse(
            _search_parameter_policy_passes(
                ledger,
                lane="agentic",
                retrieval_config=config,
            )
        )

    def test_agents_tool_receipts_keep_operation_and_bounded_error_only(self) -> None:
        receipts = _agents_tool_receipts(
            [
                {
                    "eventType": "tool_started",
                    "payload": {
                        "toolCallId": "call-secret",
                        "toolName": "agents",
                        "args": {"op": "delegate", "task": "do not retain"},
                    },
                },
                {
                    "eventType": "tool_finished",
                    "payload": {
                        "toolCallId": "call-secret",
                        "toolName": "agents",
                        "isError": True,
                        "result": {
                            "errorType": "ValueError",
                            "message": "invalid acceptance criteria",
                        },
                    },
                },
            ]
        )

        self.assertEqual("delegate", receipts[0]["operation"])
        self.assertTrue(receipts[0]["finished"])
        self.assertTrue(receipts[0]["isError"])
        self.assertEqual("ValueError", receipts[0]["errorType"])
        self.assertEqual("invalid acceptance criteria", receipts[0]["errorMessage"])
        self.assertNotIn("do not retain", str(receipts))
        self.assertNotIn("call-secret", str(receipts))

    def test_snapshot_text_reads_last_assistant_text_block(self) -> None:
        self.assertEqual(
            '{"cases":[]}',
            _last_assistant_snapshot_text(
                [
                    {"role": "user", "blocks": []},
                    {
                        "role": "assistant",
                        "blocks": [
                            {"type": "text", "data": {"text": '{"cases":[]}'}}
                        ],
                    },
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
