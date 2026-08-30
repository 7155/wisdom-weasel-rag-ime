from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.trace_diagnostics import (
    TraceDiagnosticReportStore,
    extract_trace_diagnostic_result,
    inspect_trace_targets,
)


class TraceDiagnosticInspectionTests(unittest.TestCase):
    def test_extracts_multiple_targets_with_stable_evidence_and_objective_tool_metrics(self) -> None:
        sessions = {
            "session:a": {
                "ok": True,
                "sessionId": "session:a",
                "status": "idle",
                "items": [
                    {
                        "id": "message:user:a",
                        "role": "user",
                        "status": "completed",
                        "timelineSequence": 1,
                        "createdAtMs": 10,
                        "blocks": [
                            {
                                "id": "block:user:a",
                                "type": "text",
                                "status": "completed",
                                "data": {"text": "检查当前实现"},
                            }
                        ],
                    }
                ],
                "liveEvents": [],
            },
            "session:b": {
                "ok": True,
                "sessionId": "session:b",
                "status": "idle",
                "items": [],
                "liveEvents": [],
            },
        }
        observations = {
            "session:a": _observation_snapshot(
                session_id="session:a",
                trace_id="trace:a",
                status="failed",
                summary="tool timeout",
            ),
            "session:b": _observation_snapshot(
                session_id="session:b",
                trace_id="trace:b",
                status="completed",
                summary="tool completed",
            ),
        }

        result = inspect_trace_targets(
            targets=[
                {"kind": "session", "id": "session:a", "title": "A"},
                {"kind": "session", "id": "session:b", "title": "B"},
            ],
            session_reader=lambda session_id: sessions[session_id],
            room_reader=lambda room_id: {},
            observation_reader=lambda filters: observations[str(filters["sessionId"])],
            trace_reader=lambda trace_id: _trace(trace_id),
            eval_reader=lambda trace_id: [],
            now_ms=100,
        )

        self.assertEqual(result["schemaVersion"], "rag-ime.trace-diagnostic-inspection.v1")
        self.assertEqual([item["targetKey"] for item in result["targets"]], ["session:session:a", "session:session:b"])
        self.assertEqual(result["traceIds"], ["trace:a", "trace:b"])
        evidence_ids = {item["evidenceId"] for item in result["evidence"]}
        self.assertIn("session:session:a:message:message:user:a:block:block:user:a", evidence_ids)
        self.assertIn("observation:observation:session:a", evidence_ids)
        tool_dimension = next(item for item in result["scorecard"]["dimensions"] if item["dimensionId"] == "tool_runtime")
        metrics = {item["metricId"]: item for item in tool_dimension["metrics"]}
        self.assertEqual(metrics["terminal_tool_success_rate"]["value"], 0.5)
        self.assertEqual(metrics["timeout_rate"]["value"], 0.5)
        self.assertEqual(metrics["schema_error_rate"]["value"], 0.0)
        self.assertTrue(tool_dimension["evidenceIds"])

    def test_marks_unobservable_dimensions_not_available_instead_of_inventing_scores(self) -> None:
        result = inspect_trace_targets(
            targets=[{"kind": "session", "id": "session:a", "title": "A"}],
            session_reader=lambda _session_id: {
                "ok": True,
                "sessionId": "session:a",
                "status": "idle",
                "items": [],
                "liveEvents": [],
            },
            room_reader=lambda _room_id: {},
            observation_reader=lambda _filters: _empty_observation_snapshot(),
            trace_reader=lambda _trace_id: None,
            eval_reader=lambda _trace_id: [],
            now_ms=100,
        )

        dimensions = {item["dimensionId"]: item for item in result["scorecard"]["dimensions"]}
        self.assertEqual(dimensions["task_completion"]["applicability"], "unknown")
        self.assertIsNone(dimensions["task_completion"]["score"])
        self.assertEqual(dimensions["memory_rag"]["applicability"], "unknown")
        self.assertFalse(result["scorecard"]["comparison"]["eligible"])

    def test_public_session_projection_is_bounded_and_redacts_paths_and_secrets(self) -> None:
        result = inspect_trace_targets(
            targets=[{"kind": "session", "id": "session:a", "title": "A"}],
            session_reader=lambda _session_id: {
                "ok": True,
                "sessionId": "session:a",
                "status": "idle",
                "items": [
                    {
                        "id": "message:1",
                        "role": "assistant",
                        "status": "completed",
                        "blocks": [
                            {
                                "id": "block:1",
                                "type": "text",
                                "status": "completed",
                                "data": {
                                    "text": "Authorization: bearer-secret /Users/private/project/file.txt"
                                },
                            }
                        ],
                    }
                ],
                "liveEvents": [],
            },
            room_reader=lambda _room_id: {},
            observation_reader=lambda _filters: _empty_observation_snapshot(),
            trace_reader=lambda _trace_id: None,
            eval_reader=lambda _trace_id: [],
            now_ms=100,
        )

        encoded = str(result["evidence"])
        self.assertNotIn("bearer-secret", encoded)
        self.assertNotIn("/Users/private", encoded)
        self.assertIn("[redacted]", encoded)


class TraceDiagnosticReportStoreTests(unittest.TestCase):
    def test_extracts_large_structured_result_without_display_text_truncation(self) -> None:
        summary = "诊断" * 900
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": summary,
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
        }
        session = {
            "items": [
                {
                    "role": "assistant",
                    "status": "completed",
                    "timelineSequence": 1,
                    "blocks": [
                        {
                            "status": "completed",
                            "data": {
                                "text": "--- TRACE_DIAGNOSTIC_RESULT_V1 ---\n"
                                + __import__("json").dumps(payload, ensure_ascii=False)
                                + "\n--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"
                            },
                        }
                    ],
                }
            ]
        }

        result = extract_trace_diagnostic_result(session)

        self.assertEqual(result["summary"], summary)

    def test_persists_report_and_indexes_every_source_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:1",
                title="两段失败对话对比",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )

            self.assertEqual(created["status"], "generating")
            self.assertEqual(created["revision"], 1)
            self.assertEqual(store.for_target("session", "session:a")[0]["reportId"], created["reportId"])
            self.assertEqual(store.for_target("session", "session:b")[0]["reportId"], created["reportId"])

            result = {
                "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                "summary": "A 的工具超时，B 成功。",
                "hardGates": [
                    {
                        "gateId": "task_completion",
                        "status": "failed",
                        "reason": "A 未完成。",
                        "evidenceIds": ["observation:observation:session:a"],
                    }
                ],
                "judgeScores": [
                    {
                        "dimensionId": "context",
                        "score": 2,
                        "authority": "ai_judge_estimate",
                        "explanation": "上下文基本完整，但缺少一次失败后的重新读取。",
                        "evidenceIds": ["observation:observation:session:a"],
                    }
                ],
                "findings": [],
            }
            completed = store.complete(
                created["reportId"],
                expected_revision=1,
                result=result,
                now_ms=120,
            )
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["revision"], 2)
            self.assertEqual(store.get(created["reportId"]), completed)
            listed = store.list(limit=10)["items"]
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["reportId"], completed["reportId"])
            self.assertEqual(listed[0]["status"], "completed")
            self.assertEqual(listed[0]["targetKeys"], ["session:session:a", "session:session:b"])
            self.assertNotIn("inspection", listed[0])

    def test_rejects_result_evidence_not_present_in_frozen_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:1",
                title="报告",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            with self.assertRaisesRegex(ValueError, "unknown evidenceId"):
                store.complete(
                    created["reportId"],
                    expected_revision=1,
                    result={
                        "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                        "summary": "伪造证据",
                        "hardGates": [],
                        "judgeScores": [],
                        "findings": [
                            {
                                "findingId": "finding:1",
                                "dimensionId": "evidence_diagnosis",
                                "severity": "high",
                                "observation": "未知",
                                "hypothesis": "未知",
                                "conclusion": "未知",
                                "confidence": "low",
                                "evidenceIds": ["evidence:not-real"],
                                "candidateRepair": "无",
                                "verification": "无",
                            }
                        ],
                    },
                    now_ms=120,
                )

    def test_persists_terminal_failure_when_diagnostic_output_is_not_usable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:failure",
                title="报告",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )

            failed = store.fail(
                created["reportId"],
                expected_revision=1,
                reason="诊断 Session 未生成可校验的结构化报告。",
                now_ms=120,
            )

            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["revision"], 2)
            self.assertEqual(failed["failureReason"], "诊断 Session 未生成可校验的结构化报告。")

    def test_rejects_same_diagnostic_session_when_inspection_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            store.create(
                diagnostic_session_id="agent:diagnostic:bound",
                title="初始报告",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )

            changed_inspection = dict(inspection)
            changed_inspection["generatedAtMs"] = 101
            with self.assertRaisesRegex(ValueError, "diagnostic Session is already bound"):
                store.create(
                    diagnostic_session_id="agent:diagnostic:bound",
                    title="变更报告",
                    targets=changed_inspection["targets"],
                    inspection=changed_inspection,
                    now_ms=120,
                )

    def test_rejects_duplicate_judge_score_dimensions(self) -> None:
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "重复维度",
            "hardGates": [],
            "judgeScores": [
                {
                    "dimensionId": "context",
                    "score": 2,
                    "authority": "ai_judge_estimate",
                    "explanation": "第一次",
                    "evidenceIds": [],
                },
                {
                    "dimensionId": "context",
                    "score": 1,
                    "authority": "ai_judge_estimate",
                    "explanation": "第二次",
                    "evidenceIds": [],
                },
            ],
            "findings": [],
        }

        with self.assertRaisesRegex(ValueError, "duplicate judge dimension"):
            extract_trace_diagnostic_result(
                {
                    "items": [
                        {
                            "role": "assistant",
                            "status": "completed",
                            "timelineSequence": 1,
                            "blocks": [
                                {
                                    "status": "completed",
                                    "data": {
                                        "text": "--- TRACE_DIAGNOSTIC_RESULT_V1 ---\n"
                                        + __import__("json").dumps(payload, ensure_ascii=False)
                                        + "\n--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"
                                    },
                                }
                            ],
                        }
                    ]
                }
            )

    def test_rejects_malformed_judge_score_collections_instead_of_filtering_them(self) -> None:
        for invalid_scores, expected_error in (
            ("not-an-array", "judgeScores must be an array"),
            (["not-an-object"], "judgeScores must contain only objects"),
        ):
            with self.subTest(invalid_scores=invalid_scores):
                payload = {
                    "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                    "summary": "畸形 Judge 评分",
                    "hardGates": [],
                    "judgeScores": invalid_scores,
                    "findings": [],
                }
                with self.assertRaisesRegex(ValueError, expected_error):
                    extract_trace_diagnostic_result(
                        {
                            "items": [
                                {
                                    "role": "assistant",
                                    "status": "completed",
                                    "timelineSequence": 1,
                                    "blocks": [
                                        {
                                            "status": "completed",
                                            "data": {
                                                "text": "--- TRACE_DIAGNOSTIC_RESULT_V1 ---\n"
                                                + __import__("json").dumps(payload, ensure_ascii=False)
                                                + "\n--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    )

    def test_rejects_more_than_eight_judge_scores(self) -> None:
        dimensions = (
            "task_completion",
            "evidence_diagnosis",
            "tool_runtime",
            "context",
            "room_collaboration",
            "memory_rag",
            "efficiency",
            "repair_quality",
            "context",
        )
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "评分数量超限",
            "hardGates": [],
            "judgeScores": [
                {
                    "dimensionId": dimension,
                    "score": 1,
                    "authority": "ai_judge_estimate",
                    "explanation": "测试",
                    "evidenceIds": [],
                }
                for dimension in dimensions
            ],
            "findings": [],
        }

        with self.assertRaisesRegex(ValueError, "too many judge scores"):
            extract_trace_diagnostic_result(
                {
                    "items": [
                        {
                            "role": "assistant",
                            "status": "completed",
                            "timelineSequence": 1,
                            "blocks": [
                                {
                                    "status": "completed",
                                    "data": {
                                        "text": "--- TRACE_DIAGNOSTIC_RESULT_V1 ---\n"
                                        + __import__("json").dumps(payload, ensure_ascii=False)
                                        + "\n--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---"
                                    },
                                }
                            ],
                        }
                    ]
                }
            )


def _observation_snapshot(*, session_id: str, trace_id: str, status: str, summary: str) -> dict[str, object]:
    event_id = f"observation:{session_id}"
    return {
        "schemaVersion": "rag-ime.observation-snapshot.v1",
        "generatedAtMs": 100,
        "firstSequence": 1,
        "lastSequence": 1,
        "resumeToken": "observation:1",
        "truncated": False,
        "filters": {"sessionId": session_id},
        "counts": {"total": 1, "byCategory": {"tool": 1}, "byStatus": {status: 1}},
        "items": [
            {
                "schemaVersion": "rag-ime.observation-event.v1",
                "eventType": "observation",
                "eventId": event_id,
                "sequence": 1,
                "resumeToken": "observation:1",
                "traceId": trace_id,
                "spanId": f"span:{session_id}",
                "parentSpanId": "",
                "sessionId": session_id,
                "roomId": "",
                "turnId": "turn:1",
                "runId": "run:1",
                "category": "tool",
                "phase": "tool_finished",
                "name": "workspace_read",
                "status": status,
                "summary": summary,
                "createdAtMs": 10,
                "startedAtMs": 1,
                "endedAtMs": 10,
                "durationMs": 9,
                "privacyClass": "metadata",
                "metrics": {},
                "attributes": {},
                "refs": [],
            }
        ],
    }


def _empty_observation_snapshot() -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.observation-snapshot.v1",
        "generatedAtMs": 100,
        "firstSequence": 0,
        "lastSequence": 0,
        "resumeToken": "observation:0",
        "truncated": False,
        "filters": {},
        "counts": {"total": 0, "byCategory": {}, "byStatus": {}},
        "items": [],
    }


def _trace(trace_id: str) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.observability-trace-get.v1",
        "traceId": trace_id,
        "trace": {
            "schemaVersion": "rag-ime.trace-envelope.v1",
            "traceId": trace_id,
            "sourceKind": "agent",
            "status": "failed" if trace_id == "trace:a" else "completed",
            "binding": {},
            "input": {
                "fingerprint": "sha256:" + "0" * 64,
                "contentPolicy": "hash_only",
                "normalization": "test",
            },
            "spans": [],
            "evidence": [],
            "artifacts": [],
            "createdAtMs": 1,
            "updatedAtMs": 10,
        },
        "truncated": False,
        "projectionSource": "trace_store",
        "observationWindow": {
            "firstSequence": 0,
            "lastSequence": 0,
            "resumeToken": f"trace-store:{trace_id}",
            "nextBeforeSequence": None,
        },
    }


def _inspection_fixture() -> dict[str, object]:
    return inspect_trace_targets(
        targets=[
            {"kind": "session", "id": "session:a", "title": "A"},
            {"kind": "session", "id": "session:b", "title": "B"},
        ],
        session_reader=lambda session_id: {
            "ok": True,
            "sessionId": session_id,
            "status": "idle",
            "items": [],
            "liveEvents": [],
        },
        room_reader=lambda _room_id: {},
        observation_reader=lambda filters: _observation_snapshot(
            session_id=str(filters["sessionId"]),
            trace_id="trace:a" if filters["sessionId"] == "session:a" else "trace:b",
            status="failed" if filters["sessionId"] == "session:a" else "completed",
            summary="tool timeout" if filters["sessionId"] == "session:a" else "tool completed",
        ),
        trace_reader=lambda trace_id: _trace(trace_id),
        eval_reader=lambda _trace_id: [],
        now_ms=100,
    )


if __name__ == "__main__":
    unittest.main()
