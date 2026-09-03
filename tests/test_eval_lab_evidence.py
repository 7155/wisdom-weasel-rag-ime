from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.control_api import ControlPathId, default_route_policy
from rag_ime.control_api.route_table import find_route
from rag_ime.eval_lab_evidence import EvalLabEvidenceProjection


class EvalLabEvidenceProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="paw-eval-evidence-")
        self.root = Path(self.tmp.name) / "archive"
        self.run = self.root / "runs" / "enterpriseops-test-run"
        (self.run / "agent" / "sessions").mkdir(parents=True)
        self.db = self.run / "paw.sqlite"
        transcript = self.run / "agent" / "sessions" / "task.jsonl"
        lines = [
            {"type": "session", "version": 3, "id": "pi-test"},
            {"type": "model_change", "provider": "openai-codex", "modelId": "gpt-5.6-sol"},
            {"type": "thinking_level_change", "thinkingLevel": "max"},
            {"type": "message", "id": "u1", "timestamp": "2026-09-01T00:00:00Z", "message": {"role": "user", "content": [{"type": "text", "text": "Customer request: create a case for alice@example.com\nWork only through the provided tools."}]}},
            {"type": "message", "id": "a1", "timestamp": "2026-09-01T00:00:01Z", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "private reasoning"}, {"type": "toolCall", "name": "create_case", "arguments": {"query": "SELECT secret FROM hidden_gold;", "account_id": 7}}], "usage": {"input": 10, "output": 4}}},
            {"type": "message", "id": "t1", "timestamp": "2026-09-01T00:00:02Z", "message": {"role": "toolResult", "toolName": "create_case", "isError": False, "content": [{"type": "text", "text": "{\"case_id\":\"CS-0001\",\"email\":\"alice@example.com\"}"}]}},
            {"type": "message", "id": "a2", "timestamp": "2026-09-01T00:00:03Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "已创建工单。"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(item) for item in lines) + "\n", encoding="utf-8")
        store = AgentSessionStore(self.db)
        store.initialize()
        session = store.create(title="EnterpriseOps CSM task_test", model_profile="openai-codex/gpt-5.6-sol", thinking_level="high", execution_mode="per_action", created_at_ms=100)
        store.bind_pi_session(str(session["id"]), pi_session_id="pi-test", session_file=transcript.as_posix(), message_count=4, updated_at_ms=200)
        store.set_status(str(session["id"]), "idle", message_count=4, updated_at_ms=200)
        self.report = self.run / "report.json"
        self.report.write_text(json.dumps({"schemaVersion": "paw.enterpriseops-csm-eval.v1", "split": "validation", "evaluationContract": {"provider": "openai-codex", "model": "gpt-5.6-sol", "thinking": "high", "workflowProfile": "baseline-v1", "transport": "loopback-http-v1", "timeoutSeconds": 900}, "runtimeIdentity": {"piVersion": "0.84.2", "runtimeVersion": "test"}, "lane": {"workflowProfile": "baseline-v1", "taskCount": 1, "taskSuccessCount": 1, "taskSuccessRate": 1, "verifierCount": 2, "verifierPassCount": 2, "verifierPassRate": 1, "toolCalls": 1, "failedToolCalls": 0, "latencyMs": 100, "tasks": [{"taskId": "task_test", "taskSucceeded": True, "terminalEvent": "turn_completed", "toolCalls": 1, "failedToolCalls": 0, "latencyMs": 100, "verifier": {"passed": 2, "total": 2}}]}}, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_catalog_finds_all_sessions_and_detail_is_public_only(self) -> None:
        projection = EvalLabEvidenceProjection(self.root)
        catalog = projection.read()
        self.assertTrue(catalog["source"]["available"])
        self.assertEqual(catalog["source"]["runCount"], 1)
        self.assertEqual(catalog["source"]["transcriptCount"], 1)
        self.assertEqual(len(catalog["sources"]), 1)
        run = catalog["runs"][0]
        self.assertEqual(run["sessionCount"], 1)
        self.assertEqual(run["metrics"]["verifierPassCount"], 2)
        detail = projection.read({"runId": "enterpriseops-test-run", "taskIndex": "1"})["detail"]
        self.assertEqual(detail["status"], "available")
        text = json.dumps(detail, ensure_ascii=False)
        self.assertIn("create_case", text)
        self.assertIn("[邮箱已隐藏]", text)
        self.assertNotIn("private reasoning", text)
        self.assertNotIn("SELECT secret", text)
        self.assertNotIn("hidden_gold", text)
        self.assertNotIn(str(self.root), text)
        self.assertFalse(detail["protected"]["thinkingShown"])
        self.assertFalse(detail["protected"]["rawSqlShown"])

        report_detail = projection.read({"runId": "enterpriseops-test-run", "taskIndex": "0"})["detail"]
        self.assertEqual(report_detail["status"], "report_available")
        self.assertEqual(report_detail["turns"], [])
        self.assertEqual(report_detail["report"]["schemaVersion"], "paw.enterpriseops-csm-eval.v1")

    def test_missing_archive_is_a_truthful_empty_projection(self) -> None:
        projection = EvalLabEvidenceProjection(Path(self.tmp.name) / "missing")
        payload = projection.read()
        self.assertFalse(payload["source"]["available"])
        self.assertEqual(payload["runs"], [])

    def test_report_only_receipt_is_visible_without_inventing_a_session(self) -> None:
        report_run = self.root / "runs" / "ledger-receipt"
        report_run.mkdir(parents=True)
        (report_run / "report.json").write_text(json.dumps({
            "schemaVersion": "paw.example-receipt.v1",
            "status": "rejected",
            "decision": "reject",
            "metrics": {"quality": 0.5},
            "provenanceGaps": ["没有公开 transcript"],
        }, ensure_ascii=False), encoding="utf-8")
        projection = EvalLabEvidenceProjection(self.root)
        catalog = projection.read()
        run = next(item for item in catalog["runs"] if item["runId"] == "ledger-receipt")
        self.assertEqual(run["sessionCount"], 0)
        self.assertEqual(run["status"], "rejected")
        self.assertEqual(run["evidenceKind"], "report_only")
        detail = projection.read({"runId": "ledger-receipt"})["detail"]
        self.assertEqual(detail["status"], "report_only")
        self.assertEqual(detail["turns"], [])
        self.assertEqual(detail["report"]["decision"], "reject")
        explicit_report = projection.read({"runId": "ledger-receipt", "taskIndex": "0"})["detail"]
        self.assertEqual(explicit_report["status"], "report_only")

    def test_default_catalog_discovers_source_local_enterpriseops_sessions(self) -> None:
        repo_root = Path(self.tmp.name) / "product"
        run = repo_root / ".rag-ime-data" / "enterpriseops-agent-eval" / "enterpriseops-csm-luna-validation-v2"
        sessions = run / "agent" / "sessions"
        sessions.mkdir(parents=True)
        transcript = sessions / "task.jsonl"
        transcript.write_text("\n".join([
            json.dumps({"type": "session", "version": 3, "id": "pi-local"}),
            json.dumps({"type": "model_change", "provider": "openai-codex", "modelId": "gpt-5.6-luna"}),
            json.dumps({
                "type": "message",
                "message": {"role": "user", "content": [{"type": "text", "text": "Customer request: update the account.\nWork only through the provided tools."}]},
            }),
            json.dumps({
                "type": "message",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "已完成更新。"}]},
            }),
        ]) + "\n", encoding="utf-8")
        store = AgentSessionStore(run / "paw.sqlite")
        store.initialize()
        session = store.create(
            title="EnterpriseOps CSM local task",
            model_profile="openai-codex/gpt-5.6-luna",
            thinking_level="max",
            execution_mode="per_action",
            created_at_ms=100,
        )
        store.bind_pi_session(
            str(session["id"]),
            pi_session_id="pi-local",
            session_file=transcript.as_posix(),
            message_count=2,
            updated_at_ms=200,
        )

        with patch("rag_ime.eval_lab_evidence._project_root", return_value=repo_root):
            projection = EvalLabEvidenceProjection()
            catalog = projection.read()

        local_run = next(item for item in catalog["runs"] if item["runId"] == "enterpriseops-local--enterpriseops-csm-luna-validation-v2")
        self.assertEqual(local_run["sourceId"], "paw-local-enterpriseops")
        self.assertEqual(local_run["sessionCount"], 1)
        self.assertEqual(local_run["transcriptCount"], 1)
        self.assertEqual(local_run["family"], "EnterpriseOps CSM")

    def test_report_task_rows_keep_per_task_failure_without_fake_transcript(self) -> None:
        report_run = self.root / "runs" / "report-with-tasks"
        report_run.mkdir(parents=True)
        (report_run / "report.json").write_text(json.dumps({
            "schemaVersion": "paw.example-receipt.v1",
            "status": "rejected",
            "tasks": [{
                "taskAlias": "Task 1",
                "taskSucceeded": False,
                "verifierPassed": 1,
                "verifierTotal": 2,
                "failedVerifierIndexes": [2],
                "provisionalFirstOwner": "prompt_context",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        projection = EvalLabEvidenceProjection(self.root)
        run = next(item for item in projection.read()["runs"] if item["runId"] == "report-with-tasks")
        self.assertEqual(run["sessionCount"], 0)
        self.assertEqual(len(run["tasks"]), 1)
        self.assertEqual(run["tasks"][0]["title"], "Task 1")
        self.assertEqual(run["tasks"][0]["evidenceStatus"], "report_only")
        self.assertEqual(run["tasks"][0]["failureOwner"], "prompt_context")
        task_detail = projection.read({"runId": "report-with-tasks", "taskIndex": "1"})["detail"]
        self.assertEqual(task_detail["status"], "report_only")
        self.assertEqual(task_detail["task"]["failedVerifierIndexes"], [2])

    def test_report_projects_public_trace_receipt_ids(self) -> None:
        report_run = self.root / "runs" / "trace-receipts"
        report_run.mkdir(parents=True)
        (report_run / "report.json").write_text(json.dumps({
            "schemaVersion": "paw.example-receipt.v1",
            "status": "completed",
            "traceIds": ["trace:case:one"],
            "receipts": {
                "aggregateTraceId": "trace:aggregate:one",
                "traceId": "trace:case:two",
                "notTrace": "secret-value",
            },
        }, ensure_ascii=False), encoding="utf-8")

        projection = EvalLabEvidenceProjection(self.root)
        run = next(
            item for item in projection.read()["runs"]
            if item["runId"] == "trace-receipts"
        )

        self.assertEqual(run["environment"]["traceCount"], 3)
        self.assertEqual(
            run["environment"]["traceIds"],
            ["trace:case:one", "trace:aggregate:one", "trace:case:two"],
        )
        self.assertNotIn("secret-value", json.dumps(run, ensure_ascii=False))

    def test_report_allowlist_sanitizes_scalar_and_credential_fields(self) -> None:
        report_run = self.root / "runs" / "unsafe-report"
        report_run.mkdir(parents=True)
        (report_run / "report.json").write_text(json.dumps({
            "schemaVersion": "paw.example-receipt.v1",
            "status": "/Users/private/report SELECT value FROM hidden_table;",
            "decision": "password=short-pass",
            "result": "apiKey:short-key",
            "runtime": "/Volumes/private/runtime",
            "environment": {
                "password": "p@ss",
                "apiKey": "key-value",
                "reasoning": "private reasoning",
                "safeLabel": "Darwin",
            },
            "metrics": {"/Users/private/metric": 1},
        }, ensure_ascii=False), encoding="utf-8")

        projection = EvalLabEvidenceProjection(self.root)
        detail = projection.read({"runId": "unsafe-report", "taskIndex": "0"})["detail"]
        rendered = json.dumps(detail, ensure_ascii=False)

        for forbidden in (
            "/Users/private/report",
            "SELECT value FROM hidden_table",
            "password=short-pass",
            "apiKey:short-key",
            "/Volumes/private/runtime",
            "p@ss",
            "key-value",
            "private reasoning",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)
        self.assertIn("safeLabel", rendered)

    def test_transcript_only_run_is_not_reported_as_completed(self) -> None:
        transcript_run = self.root / "runs" / "transcript-only"
        sessions = transcript_run / "agent" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "task.jsonl").write_text(json.dumps({
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "完成了公开步骤。"}],
            },
        }, ensure_ascii=False) + "\n", encoding="utf-8")

        projection = EvalLabEvidenceProjection(self.root)
        run = next(item for item in projection.read()["runs"] if item["runId"] == "transcript-only")
        self.assertEqual(run["status"], "transcript_only")
        self.assertEqual(run["evidenceKind"], "transcript_only")
        self.assertFalse(run["reportAvailable"])

    def test_evidence_route_is_local_read_only_with_bounded_query_keys(self) -> None:
        policy = default_route_policy()
        route = policy.resolve(ControlPathId.AGENT_EVAL_LAB_EVIDENCE)
        descriptor = find_route("GET", "/api/agent/eval-lab/evidence")

        self.assertEqual(route.local_8766_path, "/api/agent/eval-lab/evidence")
        self.assertIsNone(route.gateway_8768_path)
        self.assertFalse(route.remote_safe)
        self.assertEqual(route.query, frozenset({"runId", "taskIndex"}))
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor.handler, "agent.eval_lab_evidence_read")
        self.assertEqual(descriptor.query_args, ("runId", "taskIndex"))
        self.assertTrue(descriptor.takes_arguments)


if __name__ == "__main__":
    unittest.main()
