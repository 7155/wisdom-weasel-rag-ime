from __future__ import annotations

import hashlib
import json
import sqlite3
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
        self.assertEqual(result["requirements"]["source"], "user_input")
        self.assertEqual(result["requirements"]["items"][0]["statement"], "检查当前实现")
        self.assertEqual(
            result["requirements"]["items"][0]["requirementId"],
            "session:session:a:message:message:user:a:block:block:user:a",
        )
        tool_dimension = next(item for item in result["scorecard"]["dimensions"] if item["dimensionId"] == "tool_runtime")
        metrics = {item["metricId"]: item for item in tool_dimension["metrics"]}
        self.assertEqual(metrics["terminal_tool_success_rate"]["value"], 0.5)
        self.assertEqual(metrics["timeout_rate"]["value"], 0.5)
        self.assertEqual(metrics["schema_error_rate"]["value"], 0.0)
        self.assertTrue(tool_dimension["evidenceIds"])

    def test_freezes_reproducibility_environment_without_workspace_paths(self) -> None:
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
            environment_reader=lambda _kind, _identifier: {
                "modelProfile": "codex",
                "toolProfileVersion": "control-center-v1",
                "executionMode": "per_action",
                "policyRevision": 9,
                "workspaceScopeSha256": "b" * 64,
                "shellPolicyVersion": "workspace-v2",
                "workspaceRoots": ["/Users/private/project"],
                "runtimeBinding": {
                    "runtimeKind": "pi",
                    "generation": 3,
                },
            },
            now_ms=100,
        )

        environment = result["environment"]
        self.assertEqual(environment["capturedAtMs"], 100)
        self.assertEqual(environment["rubricVersion"], "trace-score-v1")
        target = environment["targets"][0]
        self.assertEqual(target["targetKey"], "session:session:a")
        self.assertEqual(target["modelProfile"], "codex")
        self.assertEqual(target["runtimeKind"], "pi")
        self.assertEqual(target["runtimeGeneration"], 3)
        self.assertEqual(target["workspaceScopeSha256"], "b" * 64)
        self.assertEqual(len(target["sourceSha256"]), 64)
        self.assertNotIn("/Users/private/project", str(environment))

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

    def test_marks_room_collaboration_not_applicable_for_standalone_memory_maintenance_run(self) -> None:
        result = inspect_trace_targets(
            targets=[
                {
                    "kind": "run",
                    "id": "memory-maintenance:run-1",
                    "title": "记忆整理失败",
                }
            ],
            session_reader=lambda _session_id: {},
            room_reader=lambda _room_id: {},
            observation_reader=lambda _filters: _empty_observation_snapshot(),
            trace_reader=lambda _trace_id: None,
            eval_reader=lambda _trace_id: [],
            now_ms=100,
        )

        dimensions = {
            item["dimensionId"]: item
            for item in result["scorecard"]["dimensions"]
        }
        self.assertEqual(
            dimensions["room_collaboration"]["applicability"],
            "not_applicable",
        )
        self.assertEqual(
            dimensions["room_collaboration"]["note"],
            "独立 Memory 维护 run 没有 Room 协作边界。",
        )

    def test_bounds_large_dimension_evidence_with_stable_priority_and_explicit_gap(self) -> None:
        events = [
            {
                "eventId": "room:large:failed",
                "eventType": "turn_failed",
                "sequence": 1,
                "createdAtMs": 1,
                "payload": {"summary": "Root failed after timeout"},
            },
            {
                "eventId": "room:large:completed",
                "eventType": "turn_completed",
                "sequence": 2,
                "createdAtMs": 2,
                "payload": {"summary": "Replacement Root completed"},
            },
            *[
                {
                    "eventId": f"room:large:activity:{index:03d}",
                    "eventType": "participant_activity",
                    "sequence": index + 3,
                    "createdAtMs": index + 3,
                    "payload": {"summary": f"ordinary activity {index:03d}"},
                }
                for index in range(299)
            ],
        ]

        def inspect() -> dict[str, object]:
            return inspect_trace_targets(
                targets=[{"kind": "room", "id": "room:large", "title": "Large Room"}],
                session_reader=lambda _session_id: {},
                room_reader=lambda _room_id: {
                    "room": {"id": "room:large", "workItems": []},
                    "events": events,
                },
                observation_reader=lambda _filters: _empty_observation_snapshot(),
                trace_reader=lambda _trace_id: None,
                eval_reader=lambda _trace_id: [],
                now_ms=100,
            )

        first = inspect()
        second = inspect()
        dimension = next(
            item
            for item in first["scorecard"]["dimensions"]
            if item["dimensionId"] == "room_collaboration"
        )
        repeated = next(
            item
            for item in second["scorecard"]["dimensions"]
            if item["dimensionId"] == "room_collaboration"
        )

        self.assertEqual(len(dimension["evidenceIds"]), 256)
        self.assertEqual(len(set(dimension["evidenceIds"])), 256)
        self.assertEqual(dimension["evidenceIds"], repeated["evidenceIds"])
        self.assertEqual(
            dimension["evidenceIds"][:2],
            [
                "room:room:large:event:room:large:failed",
                "room:room:large:event:room:large:completed",
            ],
        )
        self.assertIn("room:room:large:event:room:large:activity:298", dimension["evidenceIds"])
        self.assertIn("301", dimension["note"])
        self.assertIn("256", dimension["note"])
        self.assertIn("截断", dimension["note"])
        self.assertIn("inspection.evidence", dimension["note"])

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
    def test_new_results_require_governed_presentation_and_failure_attribution(self) -> None:
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "旧版结果不可作为新报告完成结果。",
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
        }

        with self.assertRaisesRegex(ValueError, "result presentation is required"):
            extract_trace_diagnostic_result(_diagnostic_session(payload))
        presentation_without_attribution = _governed_presentation()
        presentation_without_attribution.pop("failureAttribution")
        with self.assertRaisesRegex(
            ValueError,
            "presentation.failureAttribution is required",
        ):
            extract_trace_diagnostic_result(
                _diagnostic_session({**payload, "presentation": presentation_without_attribution})
            )

        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:strict-result",
                title="严格结果",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            with self.assertRaisesRegex(ValueError, "result presentation is required"):
                store.complete(
                    created["reportId"],
                    expected_revision=1,
                    result=payload,
                    now_ms=120,
                )
    def test_loads_legacy_completed_row_without_governed_presentation(self) -> None:
        legacy_result = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "旧版结果仍可读取。",
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "agent.sqlite3"
            store = TraceDiagnosticReportStore(db_path)
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:legacy-load",
                title="旧版报告",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            legacy_payload = {
                **created,
                "revision": 2,
                "status": "completed",
                "result": legacy_result,
                "updatedAtMs": 120,
            }
            encoded = json.dumps(
                legacy_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "INSERT INTO trace_diagnostic_report_revisions"
                    "(report_id,revision,payload_hash,payload_json,created_at_ms) "
                    "VALUES(?,?,?,?,?)",
                    (
                        created["reportId"],
                        2,
                        hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                        encoded,
                        120,
                    ),
                )
                connection.execute(
                    "UPDATE trace_diagnostic_reports "
                    "SET current_revision=2,status='completed',updated_at_ms=120 "
                    "WHERE report_id=?",
                    (created["reportId"],),
                )
            loaded = store.get(created["reportId"])
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["status"], "completed")
            self.assertEqual(loaded["result"], legacy_result)


    def test_round_trips_structured_presentation(self) -> None:
        evidence_id = "observation:observation:session:a"
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "记忆整理失败。",
            "hardGates": [],
            "judgeScores": [],
            "findings": [
                {
                    "findingId": "finding:settlement-timeout",
                    "dimensionId": "tool_runtime",
                    "severity": "high",
                    "observation": "会话结算命令超时。",
                    "hypothesis": "上游原因尚未验证。",
                    "conclusion": "任务未生成可验证产物。",
                    "confidence": "medium",
                    "evidenceIds": [evidence_id],
                    "candidateRepair": "在沙盒中注入超时并重放。",
                    "verification": "比较新旧 Trace。",
                }
            ],
            "presentation": {
                "headline": "记忆整理任务失败",
                "impact": "本次没有生成可验证的记忆整理产物。",
                "primaryFindingId": "finding:settlement-timeout",
                "knownFacts": [
                    {
                        "fact": "Runtime Host 的会话结算命令超时。",
                        "evidenceIds": [evidence_id],
                    }
                ],
                "evidenceGaps": [
                    {
                        "gap": "缺少 Host 上游调用记录。",
                        "consequence": "无法确认超时由模型、网络还是 Host 排队导致。",
                        "howToObtain": "冻结 Host 命令起止事件并重跑。",
                    }
                ],
                "causalNodes": [
                    {
                        "label": "会话结算超时",
                        "detail": "settlement（会话结算）命令未按时返回。",
                        "status": "confirmed",
                        "evidenceIds": [evidence_id],
                    },
                    {
                        "label": "上游原因",
                        "detail": "当前 Trace 未覆盖模型请求之后的 Host 等待边界。",
                        "status": "unverified",
                        "evidenceIds": [evidence_id],
                    },
                ],
                "expectedStageCount": 4,
                "recordedStageReceiptEvidenceIds": [evidence_id],
                "failureAttribution": {
                    "primaryLayer": "tool",
                    "summary": "工具结算调用超时；其他诊断层没有足够证据承担主要责任。",
                    "layers": [
                        {
                            "layer": "tool",
                            "verdict": "primary",
                            "explanation": "冻结观察记录显示 Runtime Host 结算命令超时。",
                            "evidenceIds": [evidence_id],
                        },
                        {
                            "layer": "skill",
                            "verdict": "healthy",
                            "explanation": "诊断 Skill 已要求读取冻结 Trace 并保留证据边界。",
                            "evidenceIds": [evidence_id],
                        },
                        {
                            "layer": "template",
                            "verdict": "unknown",
                            "explanation": "当前证据不足以确认模板或提示词造成失败。",
                            "evidenceIds": [],
                        },
                        {
                            "layer": "workflow",
                            "verdict": "healthy",
                            "explanation": "现有观察记录覆盖了该次结算阶段。",
                            "evidenceIds": [evidence_id],
                        },
                        {
                            "layer": "model",
                            "verdict": "unknown",
                            "explanation": "尚未获得足以评估模型输入输出的冻结证据。",
                            "evidenceIds": [],
                        },
                    ],
                },
            },
        }

        result = extract_trace_diagnostic_result(_diagnostic_session(payload))

        self.assertEqual(result, payload)

    def test_rejects_oversized_or_extra_presentation_fields(self) -> None:
        base = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "诊断结果。",
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
            "presentation": {
                "headline": "诊断失败",
                "impact": "产物不可验证。",
                "primaryFindingId": "",
                "knownFacts": [],
                "evidenceGaps": [],
                "causalNodes": [],
                "expectedStageCount": 0,
                "recordedStageReceiptEvidenceIds": [],
                "failureAttribution": _governed_presentation()["failureAttribution"],
            },
        }
        cases = {
            "oversized headline": {"headline": "x" * 321},
            "extra property": {"internalError": "raw host detail"},
            "too many known facts": {
                "knownFacts": [
                    {"fact": f"fact {index}", "evidenceIds": [f"evidence:{index}"]}
                    for index in range(13)
                ]
            },
        }
        for label, update in cases.items():
            with self.subTest(label=label):
                payload = {
                    **base,
                    "presentation": {**base["presentation"], **update},
                }
                with self.assertRaises(ValueError):
                    extract_trace_diagnostic_result(_diagnostic_session(payload))

    def test_rejects_malformed_failure_attribution(self) -> None:
        evidence_id = "observation:observation:session:a"

        def layer(
            layer_name: str,
            verdict: str = "unknown",
            evidence_ids: list[str] | None = None,
        ) -> dict[str, object]:
            return {
                "layer": layer_name,
                "verdict": verdict,
                "explanation": f"{layer_name} attribution",
                "evidenceIds": [] if evidence_ids is None else evidence_ids,
            }

        valid_layers = [
            layer("tool", "primary", [evidence_id]),
            layer("skill"),
            layer("template"),
            layer("workflow"),
            layer("model"),
        ]
        valid_presentation = {
            "headline": "诊断失败",
            "impact": "产物不可验证。",
            "primaryFindingId": "",
            "knownFacts": [],
            "evidenceGaps": [],
            "causalNodes": [],
            "expectedStageCount": 0,
            "recordedStageReceiptEvidenceIds": [],
            "failureAttribution": {
                "primaryLayer": "tool",
                "summary": "工具层是当前有证据支持的主要失败归因。",
                "layers": valid_layers,
            },
        }
        base = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "诊断结果。",
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
            "presentation": valid_presentation,
        }
        duplicate_primary_layers = [dict(item) for item in valid_layers]
        duplicate_primary_layers[1]["verdict"] = "primary"
        duplicate_primary_layers[1]["evidenceIds"] = [evidence_id]
        no_evidence_layers = [dict(item) for item in valid_layers]
        no_evidence_layers[0]["evidenceIds"] = []
        cases = {
            "misordered layers": {
                "layers": [
                    valid_layers[1],
                    valid_layers[0],
                    *valid_layers[2:],
                ]
            },
            "duplicate primary": {"layers": duplicate_primary_layers},
            "primary layer mismatch": {"primaryLayer": "model"},
            "missing frozen evidence": {"layers": no_evidence_layers},
        }
        for label, updates in cases.items():
            with self.subTest(label=label):
                attribution = {
                    **valid_presentation["failureAttribution"],
                    **updates,
                }
                payload = {
                    **base,
                    "presentation": {
                        **base["presentation"],
                        "failureAttribution": attribution,
                    },
                }
                with self.assertRaises(ValueError):
                    extract_trace_diagnostic_result(_diagnostic_session(payload))

    def test_extracts_large_structured_result_without_display_text_truncation(self) -> None:
        summary = "诊断" * 900
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": summary,
            "hardGates": [],
            "judgeScores": [],
            "findings": [],
            "presentation": _governed_presentation(),
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
            self.assertTrue(store.owns_session("agent:diagnostic:1"))
            self.assertFalse(store.owns_session("agent:ordinary:1"))

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
                "presentation": _governed_presentation(),
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

    def test_preserves_requirement_assessments_and_explicit_causal_links(self) -> None:
        evidence_id = "observation:observation:session:a"
        requirement_id = "session:session:a:message:message:user:a:block:block:user:a"
        payload = {
            "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
            "summary": "需求未全部完成。",
            "hardGates": [],
            "judgeScores": [],
            "requirementAssessments": [
                {
                    "requirementId": requirement_id,
                    "status": "unsatisfied",
                    "owner": "Workspace Writer",
                    "authority": "ai_judge_estimate",
                    "evidenceIds": [evidence_id],
                    "note": "写入失败。",
                }
            ],
            "causalLinks": [
                {
                    "linkId": "causal:1",
                    "fromEvidenceId": requirement_id,
                    "toEvidenceId": evidence_id,
                    "relation": "triggered",
                    "authority": "ai_judge_estimate",
                    "confidence": "high",
                    "explanation": "用户要求触发了写入尝试。",
                }
            ],
            "findings": [],
            "presentation": _governed_presentation(),
        }

        result = extract_trace_diagnostic_result(
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

        self.assertEqual(result["requirementAssessments"], payload["requirementAssessments"])
        self.assertEqual(result["causalLinks"], payload["causalLinks"])

        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:requirements",
                title="需求与因果链",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            completed = store.complete(
                created["reportId"],
                expected_revision=1,
                result=result,
                now_ms=120,
            )
            self.assertEqual(completed["result"]["requirementAssessments"], payload["requirementAssessments"])
            self.assertEqual(completed["result"]["causalLinks"], payload["causalLinks"])

    def test_appends_authorized_and_verified_repair_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:repair",
                title="修复闭环",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            completed = store.complete(
                created["reportId"],
                expected_revision=1,
                result={
                    "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                    "summary": "写入失败。",
                    "hardGates": [],
                    "judgeScores": [],
                    "requirementAssessments": [],
                    "causalLinks": [],
                    "findings": [
                        {
                            "findingId": "finding:stale-revision",
                            "dimensionId": "tool_runtime",
                            "severity": "high",
                            "observation": "stale_snapshot",
                            "hypothesis": "批准后版本变化",
                            "conclusion": "旧 revision 被拒绝",
                            "confidence": "high",
                            "evidenceIds": ["observation:observation:session:a"],
                            "candidateRepair": "重新 prepare",
                            "verification": "新 Trace 与测试通过",
                        }
                    ],
                    "presentation": _governed_presentation(
                        primary_finding_id="finding:stale-revision"
                    ),
                },
                now_ms=120,
            )

            authorized = store.authorize_repair(
                completed["reportId"],
                expected_revision=2,
                finding_id="finding:stale-revision",
                source_scope="session:session:a",
                source_trace_id="trace:a",
                failure_ref="observation:observation:session:a",
                repair_session_id="agent:repair:1",
                now_ms=130,
            )
            self.assertEqual(authorized["revision"], 3)
            self.assertEqual(authorized["repairLifecycle"]["authorization"]["state"], "authorized")
            self.assertEqual(
                authorized["repairLifecycle"]["authorization"]["writeAuthority"],
                "auto_approved_full_trust",
            )
            comparison = authorized["repairLifecycle"]["verification"]["comparison"]
            self.assertEqual(
                comparison["reason"],
                "已授权全信任自动批准修复交接；所有 Tool 操作无需逐项审批，等待修复 Trace 中已记录的修改与通过测试证据，以及 AI Judge 复检。",
            )
            self.assertNotIn("实际写入仍需逐次审批", comparison["reason"])
            self.assertEqual(
                authorized["repairLifecycle"]["authorization"]["repairSessionId"],
                "agent:repair:1",
            )
            self.assertTrue(store.owns_session("agent:repair:1"))

            verified = store.verify_repair(
                authorized["reportId"],
                expected_revision=3,
                receipt={
                    "schemaVersion": "rag-ime.trace-repair-receipt.v1",
                    "repairReceiptId": "repair-receipt:trace:repair",
                    "sourceScope": "session:session:a",
                    "sourceTraceId": "trace:a",
                    "failureRef": "observation:observation:session:a",
                    "changeReceiptId": "change-evidence:1",
                    "testEvidenceId": "test-evidence:1",
                    "testStatus": "passed",
                    "sandboxStatus": "passed",
                    "sandboxedTestCount": 1,
                    "repairTraceId": "trace:repair",
                    "repairSessionId": "agent:repair:1",
                    "createdAtMs": 140,
                },
                eval_run={
                    "evalRunId": "eval:repair:1",
                    "status": "completed",
                    "metricAuthority": "ai_judge_estimate",
                    "metrics": {"task_success": 1.0},
                },
                comparison={
                    "status": "incomparable",
                    "reason": "输入 fingerprint 不同，不能声称效果提升。",
                    "sourceStatus": "failed",
                    "repairStatus": "completed",
                    "sourceFingerprint": "sha256:" + "1" * 64,
                    "repairFingerprint": "sha256:" + "2" * 64,
                    "beforeMetrics": {"task_completion": 0.0},
                    "afterMetrics": {"task_success": 1.0},
                    "deltas": {},
                },
                now_ms=150,
            )
            self.assertEqual(verified["revision"], 4)
            self.assertEqual(verified["repairLifecycle"]["verification"]["state"], "verified")
            self.assertEqual(
                verified["repairLifecycle"]["verification"]["repairReceiptId"],
                "repair-receipt:trace:repair",
            )
            self.assertEqual(
                verified["repairLifecycle"]["verification"]["comparison"]["status"],
                "incomparable",
            )
            listed = store.list(limit=10)
            self.assertEqual(listed["items"][0]["repairState"], "verified")

    def test_repair_authorization_binds_trace_to_exact_frozen_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:target-binding",
                title="目标绑定",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            completed = store.complete(
                created["reportId"],
                expected_revision=1,
                result={
                    "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                    "summary": "A 的工具失败。",
                    "hardGates": [],
                    "judgeScores": [],
                    "findings": [
                        {
                            "findingId": "finding:target-binding",
                            "dimensionId": "tool_runtime",
                            "severity": "high",
                            "observation": "A 的工具失败。",
                            "hypothesis": "工具结算超时。",
                            "conclusion": "需要修复。",
                            "confidence": "high",
                            "evidenceIds": ["observation:observation:session:a"],
                            "candidateRepair": "修复工具结算。",
                            "verification": "重放并检查回执。",
                        }
                    ],
                    "presentation": _governed_presentation(
                        primary_finding_id="finding:target-binding"
                    ),
                },
                now_ms=120,
            )

            with self.assertRaisesRegex(ValueError, "outside the frozen target"):
                store.authorize_repair(
                    completed["reportId"],
                    expected_revision=2,
                    finding_id="finding:target-binding",
                    source_scope="session:session:b",
                    source_trace_id="trace:a",
                    failure_ref="observation:observation:session:a",
                    repair_session_id="agent:repair:target-binding",
                    now_ms=130,
                )

    def test_repair_authorization_requires_recorded_failed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:failed-evidence",
                title="失败证据",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            completed = store.complete(
                created["reportId"],
                expected_revision=1,
                result={
                    "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                    "summary": "只有成功证据的高严重度发现。",
                    "hardGates": [],
                    "judgeScores": [],
                    "findings": [
                        {
                            "findingId": "finding:unconfirmed",
                            "dimensionId": "tool_runtime",
                            "severity": "critical",
                            "observation": "没有失败回执。",
                            "hypothesis": "仅由严重度推断。",
                            "conclusion": "不能确认失败。",
                            "confidence": "high",
                            "evidenceIds": ["observation:observation:session:b"],
                            "candidateRepair": "不应授权。",
                            "verification": "等待失败回执。",
                        }
                    ],
                    "presentation": _governed_presentation(
                        primary_finding_id="finding:unconfirmed"
                    ),
                },
                now_ms=120,
            )

            with self.assertRaisesRegex(ValueError, "recorded failed evidence"):
                store.authorize_repair(
                    completed["reportId"],
                    expected_revision=2,
                    finding_id="finding:unconfirmed",
                    source_scope="session:session:b",
                    source_trace_id="trace:b",
                    failure_ref="observation:observation:session:b",
                    repair_session_id="agent:repair:failed-evidence",
                    now_ms=130,
                )

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
                        "presentation": _governed_presentation(),
                    },
                    now_ms=120,
                )

    def test_rejects_presentation_evidence_not_present_in_frozen_inspection(self) -> None:
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
                        "summary": "结构化结论",
                        "hardGates": [],
                        "judgeScores": [],
                        "findings": [],
                        "presentation": {
                            "headline": "任务失败",
                            "impact": "产物不可验证。",
                            "primaryFindingId": "",
                            "knownFacts": [
                                {
                                    "fact": "Host 命令超时。",
                                    "evidenceIds": ["evidence:not-real"],
                                }
                            ],
                            "evidenceGaps": [],
                            "causalNodes": [],
                            "expectedStageCount": 0,
                            "recordedStageReceiptEvidenceIds": [],
                            "failureAttribution": _governed_presentation()["failureAttribution"],
                        },
                    },
                    now_ms=120,
                )

    def test_rejects_failure_attribution_evidence_not_present_in_frozen_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TraceDiagnosticReportStore(Path(directory) / "agent.sqlite3")
            inspection = _inspection_fixture()
            created = store.create(
                diagnostic_session_id="agent:diagnostic:attribution-evidence",
                title="报告",
                targets=inspection["targets"],
                inspection=inspection,
                now_ms=100,
            )
            attribution_layers = [
                {
                    "layer": layer_name,
                    "verdict": "primary" if layer_name == "tool" else "unknown",
                    "explanation": f"{layer_name} attribution",
                    "evidenceIds": ["evidence:not-real"] if layer_name == "tool" else [],
                }
                for layer_name in ("tool", "skill", "template", "workflow", "model")
            ]
            with self.assertRaisesRegex(ValueError, "unknown evidenceId"):
                store.complete(
                    created["reportId"],
                    expected_revision=1,
                    result={
                        "schemaVersion": "rag-ime.trace-diagnostic-result.v1",
                        "summary": "结构化归因",
                        "hardGates": [],
                        "judgeScores": [],
                        "findings": [],
                        "presentation": {
                            "headline": "任务失败",
                            "impact": "产物不可验证。",
                            "primaryFindingId": "",
                            "knownFacts": [],
                            "evidenceGaps": [],
                            "causalNodes": [],
                            "expectedStageCount": 0,
                            "recordedStageReceiptEvidenceIds": [],
                            "failureAttribution": {
                                "primaryLayer": "tool",
                                "summary": "工具层归因使用了未知证据。",
                                "layers": attribution_layers,
                            },
                        },
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
            "presentation": _governed_presentation(),
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
                    "presentation": _governed_presentation(),
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
            "presentation": _governed_presentation(),
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


def _governed_presentation(*, primary_finding_id: str = "") -> dict[str, object]:
    return {
        "headline": "诊断结果",
        "impact": "当前结果已按冻结证据完成治理呈现。",
        "primaryFindingId": primary_finding_id,
        "knownFacts": [],
        "evidenceGaps": [],
        "causalNodes": [],
        "expectedStageCount": 0,
        "recordedStageReceiptEvidenceIds": [],
        "failureAttribution": {
            "primaryLayer": "unknown",
            "summary": "当前冻结证据不足以确认唯一主要失败层。",
            "layers": [
                {
                    "layer": layer_name,
                    "verdict": "unknown",
                    "explanation": f"{layer_name} 层暂无足够冻结证据。",
                    "evidenceIds": [],
                }
                for layer_name in ("tool", "skill", "template", "workflow", "model")
            ],
        },
    }


def _diagnostic_session(payload: dict[str, object]) -> dict[str, object]:
    return {
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
            "items": [
                {
                    "id": "message:user:a",
                    "role": "user",
                    "status": "completed",
                    "timelineSequence": 1,
                    "createdAtMs": 5,
                    "blocks": [
                        {
                            "id": "block:user:a",
                            "type": "text",
                            "status": "completed",
                            "data": {"text": "写入目标文件"},
                        }
                    ],
                }
            ] if session_id == "session:a" else [],
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
