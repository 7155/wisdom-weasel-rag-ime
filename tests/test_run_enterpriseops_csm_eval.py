from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_enterpriseops_csm_eval import (
    ENTERPRISEOPS_SUITE_V2_BUSINESS_AS_OF_DATE,
    ENTERPRISEOPS_SUITE_V2_OVERLAY_PATH,
    ENTERPRISEOPS_SUITE_V2_REVISION,
    HELD_OUT_TASK_COUNT,
    FROZEN_HELD_OUT_TASK_IDS,
    FROZEN_VALIDATION_TASK_IDS,
    MISSING_SEED_TASK_ID,
    VALIDATION_TASK_COUNT,
    EnterpriseOpsToolGateway,
    build_agent_prompt,
    build_task_manifest,
    execute_verifiers,
    infer_business_as_of_date,
    load_tasks,
    load_suite_overlay,
    apply_suite_overlay,
    reserve_held_out_consumption,
    _sha256,
    score_verifiers,
    select_csm_task_split,
    task_execution_succeeded,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str, dict[str, object]]] = []

    def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        database_id: str = "",
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append((name, arguments, database_id, dict(context or {})))
        return {"success": True, "result": {"tool": name, "arguments": arguments}}


class FakeSqlClient:
    def sql_query(
        self,
        query: str,
        *,
        database_id: str,
        context: dict[str, object],
    ) -> dict[str, object]:
        return {"data": [{"count": 1}]}


class RunEnterpriseOpsCsmEvalTests(unittest.TestCase):
    def _task(self, task_id: str = "task_1") -> dict[str, object]:
        return {
            "taskId": task_id,
            "system_prompt": "CSM policy",
            "user_prompt": "Create the requested customer case.",
            "gym_servers_config": [
                {
                    "mcp_server_name": "sn-csm-server",
                    "mcp_server_url": "http://127.0.0.1:8001",
                    "seed_database_file": "csm/db.sql",
                    "context": {"x-user-email": "agent@example.com"},
                }
            ],
            "selected_tools": ["find_account", "create_new_case"],
            "verifiers": [
                {
                    "verifier_type": "database_state",
                    "validation_config": {
                        "query": "SELECT COUNT(*) FROM customer_case",
                        "expected_value": 1,
                        "comparison_type": "equals",
                    },
                }
            ],
            "reset_database_between_runs": True,
        }

    def test_validation_split_is_deterministic_and_disjoint(self) -> None:
        rows = [{"taskId": f"task_{index:02d}"} for index in range(11)]

        validation = select_csm_task_split(rows, "validation")
        held_out = select_csm_task_split(rows, "held-out")

        self.assertEqual(3, VALIDATION_TASK_COUNT)
        self.assertEqual(8, HELD_OUT_TASK_COUNT)
        self.assertEqual(VALIDATION_TASK_COUNT, len(validation))
        self.assertEqual(HELD_OUT_TASK_COUNT, len(held_out))
        self.assertEqual(
            {row["taskId"] for row in validation}.isdisjoint(
                row["taskId"] for row in held_out
            ),
            True,
        )
        self.assertEqual(
            [f"task_{index:02d}" for index in range(3)],
            [row["taskId"] for row in validation],
        )

    def test_validation_loader_does_not_parse_held_out_task_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks_root = root / "tasks"
            tasks_root.mkdir()
            seed = root / "seed.sql"
            seed.write_text(
                "CREATE TABLE example(id INTEGER, sys_created_on TEXT);\n"
                "INSERT INTO example VALUES (1, '2025-12-31 22:08:08');\n",
                encoding="utf-8",
            )
            for task_id in FROZEN_VALIDATION_TASK_IDS:
                task = self._task(task_id)
                task["gym_servers_config"][0]["seed_database_file"] = "seed.sql"
                (tasks_root / f"{task_id}.json").write_text(
                    json.dumps(task), encoding="utf-8"
                )
            for task_id in (*FROZEN_HELD_OUT_TASK_IDS, MISSING_SEED_TASK_ID):
                (tasks_root / f"{task_id}.json").write_text(
                    "this must not be parsed during validation", encoding="utf-8"
                )

            rows, excluded = load_tasks(
                tasks_root,
                benchmark_root=root,
                split="validation",
            )

        self.assertEqual(list(FROZEN_VALIDATION_TASK_IDS), [row["taskId"] for row in rows])
        self.assertEqual(MISSING_SEED_TASK_ID, excluded[0]["taskId"])

    def test_agent_prompt_excludes_host_verifiers_seed_sql_and_paths(self) -> None:
        prompt = build_agent_prompt(self._task(), workflow_profile="baseline-v1")

        self.assertIn("CSM policy", prompt)
        self.assertIn("Create the requested customer case", prompt)
        self.assertNotIn("verifiers", prompt)
        self.assertNotIn("SELECT COUNT(*)", prompt)
        self.assertNotIn("seed_database_file", prompt)
        self.assertNotIn("db.sql", prompt)
        self.assertIn("disposable evaluation database", prompt)

        optimized = build_agent_prompt(self._task(), workflow_profile="dependency-plan-v1")
        self.assertIn("dependency plan", optimized.lower())

        state_task = self._task()
        state_task["businessAsOfDate"] = "2025-12-31"
        state_task["user_prompt"] = "Set up full-year support for next year."
        state_contract = build_agent_prompt(
            state_task, workflow_profile="state-contract-v1"
        )
        self.assertIn("2025-12-31", state_contract)
        self.assertIn("2026-01-01 through 2026-12-31", state_contract)
        self.assertIn("exact strings", state_contract)
        self.assertIn("distinct role", state_contract)
        self.assertNotIn("2025-12-31", prompt)

    def test_business_as_of_date_comes_from_latest_seed_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / "seed.sql"
            seed.write_text(
                "INSERT INTO x VALUES ('2025-08-27 10:00:00');\n"
                "INSERT INTO y VALUES ('2025-12-31 22:08:08');\n"
                "INSERT INTO warranty VALUES ('2027-06-30');\n",
                encoding="utf-8",
            )

            self.assertEqual("2025-12-31", infer_business_as_of_date(seed))

    def test_suite_v2_freezes_business_as_of_date_and_injects_it_into_all_profiles(self) -> None:
        overlay = load_suite_overlay(ENTERPRISEOPS_SUITE_V2_OVERLAY_PATH)
        task = self._task(FROZEN_VALIDATION_TASK_IDS[0])
        task["user_prompt"] = "Create full-year support for next year."
        task["taskConfigSha256"] = overlay["tasks"][task["taskId"]]["sourceTaskSha256"]
        patched = apply_suite_overlay(task, overlay, suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION)

        self.assertEqual(ENTERPRISEOPS_SUITE_V2_BUSINESS_AS_OF_DATE, patched["businessAsOfDate"])
        for profile in ("baseline-v1", "dependency-plan-v1", "state-contract-v1"):
            prompt = build_agent_prompt(
                patched,
                workflow_profile=profile,
                suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION,
            )
            self.assertIn("2025-11-04", prompt)
            self.assertIn("model's current clock", prompt)
            self.assertIn("2026-01-01 through 2026-12-31", prompt)

    def test_suite_v2_rewrites_only_larson_contracts_without_changing_31_slot_denominator(self) -> None:
        overlay = load_suite_overlay(ENTERPRISEOPS_SUITE_V2_OVERLAY_PATH)
        task = self._task(FROZEN_VALIDATION_TASK_IDS[2])
        task["taskConfigSha256"] = overlay["tasks"][task["taskId"]]["sourceTaskSha256"]
        task["verifiers"] = [{"verifier_type": "database_state", "validation_config": {"query": "SELECT 1", "expected_value": 1, "comparison_type": "equals"}} for _ in range(15)]
        patched = apply_suite_overlay(task, overlay, suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION)
        queries = [str(item["validation_config"]["query"]) for item in patched["verifiers"]]

        self.assertEqual(15, len(queries))
        self.assertNotIn("assigned_to = 217", queries[8])
        self.assertNotIn("owner_id = 152", queries[9])
        self.assertNotIn("owner_id = 152", queries[10])
        self.assertNotIn("owner_id = 152", queries[14])
        self.assertNotIn("MIN(user_id)", queries[14])
        self.assertNotIn("+44%", queries[14])
        self.assertNotIn("user_group_member", queries[8])
        self.assertNotIn("Larson Operations Desk", queries[8])
        self.assertIn("JOIN user assigned", queries[8])
        self.assertIn("assigned.active = 1", queries[8])
        self.assertIn("SLES Setup Guide", queries[9])
        self.assertIn("used_as = 'resolution'", queries[10])
        self.assertIn("location", queries[14])
        self.assertIn("sys_created_on", queries[14])
        self.assertIn("find_locations", patched["selected_tools"])
        self.assertEqual(len(task["selected_tools"]) + 1, len(patched["selected_tools"]))

    def test_suite_v2_manifest_binds_revision_and_overlay_hash(self) -> None:
        overlay = load_suite_overlay(ENTERPRISEOPS_SUITE_V2_OVERLAY_PATH)
        rows = []
        verifier_counts = (11, 5, 15)
        for task_id, verifier_count in zip(FROZEN_VALIDATION_TASK_IDS, verifier_counts):
            task = self._task(task_id)
            task["taskConfigSha256"] = overlay["tasks"][task_id]["sourceTaskSha256"]
            task["verifiers"] = [{"verifier_type": "database_state", "validation_config": {"query": "SELECT 1", "expected_value": 1, "comparison_type": "equals"}} for _ in range(verifier_count)]
            rows.append(apply_suite_overlay(task, overlay, suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION))
        manifest = build_task_manifest(
            rows,
            split="validation",
            suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION,
            overlay_sha256=overlay["overlaySha256"],
        )

        self.assertEqual(ENTERPRISEOPS_SUITE_V2_REVISION, manifest["suiteRevision"])
        self.assertEqual(overlay["overlaySha256"], manifest["overlaySha256"])
        self.assertEqual(31, manifest["rawVerifierCount"])
        self.assertEqual(3, manifest["taskCount"])

    def test_held_out_consumption_is_exclusive_and_marker_survives_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "promotion.json"
            receipt_payload = {
                "schemaVersion": "paw.enterpriseops-csm-validation-promotion.v1",
                "status": "authorized",
                "heldOutAuthorized": True,
                "winner": {
                    "workflowProfile": "state-contract-v1",
                    "suiteRevision": ENTERPRISEOPS_SUITE_V2_REVISION,
                    "overlaySha256": "40ac966afefb0a71bb1f3e04560bdbf4953fac2788ce2ba90e05b86cfe26677b",
                },
            }
            receipt_payload["receiptSha256"] = _sha256(receipt_payload)
            receipt.write_text(json.dumps(receipt_payload), encoding="utf-8")
            marker = reserve_held_out_consumption(
                receipt,
                workflow_profile="state-contract-v1",
                suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION,
            )
            self.assertTrue(marker.exists())
            with self.assertRaisesRegex(FileExistsError, "consumed"):
                reserve_held_out_consumption(
                    receipt,
                    workflow_profile="state-contract-v1",
                    suite_revision=ENTERPRISEOPS_SUITE_V2_REVISION,
                )

    def test_task_manifest_is_order_independent_and_binds_split(self) -> None:
        first = build_task_manifest(
            [self._task("task_b"), self._task("task_a")], split="validation"
        )
        second = build_task_manifest(
            [self._task("task_a"), self._task("task_b")], split="validation"
        )

        self.assertEqual(first["manifestSha256"], second["manifestSha256"])
        self.assertEqual(first["taskIds"], ["task_a", "task_b"])
        self.assertEqual(first["split"], "validation")
        self.assertRegex(first["manifestSha256"], r"^[0-9a-f]{64}$")

    def test_gateway_binds_session_and_projects_selected_or_discovered_tools(self) -> None:
        client = FakeMcpClient()
        catalog = [
            {"name": "find_account", "description": "Find account", "inputSchema": {"type": "object"}},
            {"name": "create_new_case", "description": "Create case", "inputSchema": {"type": "object"}},
            {"name": "update_case", "description": "Update case", "inputSchema": {"type": "object"}},
        ]
        gateway = EnterpriseOpsToolGateway(client, catalog)
        gateway.bind_session(
            "session-1",
            database_id="db-1",
            context={"x-user-email": "agent@example.com"},
            allowed_tools=["find_account", "create_new_case"],
        )

        manifests = gateway.runtime_manifests({"id": "session-1"})
        self.assertEqual(
            ["find_account", "create_new_case"],
            [item["name"] for item in manifests],
        )
        result = gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": "session-1",
                "tool": "create_new_case",
                "toolCallId": "tool-1",
                "sourceLoopId": "loop-1",
                "args": {"priority": "high"},
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            [
                (
                    "create_new_case",
                    {"priority": "high"},
                    "db-1",
                    {"x-user-email": "agent@example.com"},
                )
            ],
            client.calls,
        )
        self.assertNotIn("database_id", json.dumps(manifests))
        self.assertNotIn("agent@example.com", json.dumps(manifests))
        self.assertNotIn("db-1", json.dumps(result))
        self.assertNotIn("agent@example.com", json.dumps(result))
        with self.assertRaisesRegex(ValueError, "not bound"):
            gateway.execute(
                {
                    "schemaVersion": "rag-ime.agent-tool-call.v1",
                    "sessionId": "unknown",
                    "tool": "create_new_case",
                    "toolCallId": "tool-2",
                    "args": {},
                }
            )

    def test_gateway_requires_tool_call_identity_and_deduplicates_exact_replay(self) -> None:
        client = FakeMcpClient()
        gateway = EnterpriseOpsToolGateway(
            client,
            [{"name": "create_new_case", "inputSchema": {"type": "object"}}],
        )
        gateway.bind_session(
            "session-1",
            database_id="db-1",
            context={},
            allowed_tools=["create_new_case"],
        )
        missing_identity = {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": "session-1",
            "tool": "create_new_case",
            "args": {"priority": "high"},
        }
        with self.assertRaisesRegex(ValueError, "toolCallId"):
            gateway.execute(missing_identity)

        call = {**missing_identity, "toolCallId": "tool-1"}
        first = gateway.execute(call)
        second = gateway.execute(call)

        self.assertEqual(first, second)
        self.assertEqual(1, len(client.calls))
        with self.assertRaisesRegex(ValueError, "different payload"):
            gateway.execute({**call, "args": {"priority": "critical"}})

    def test_gateway_treats_mcp_is_error_as_failed_tool_call(self) -> None:
        class ErrorClient(FakeMcpClient):
            def call_tool(self, *args: object, **kwargs: object) -> dict[str, object]:
                return {"success": True, "result": {"isError": True, "content": []}}

        gateway = EnterpriseOpsToolGateway(
            ErrorClient(),
            [{"name": "create_new_case", "inputSchema": {"type": "object"}}],
        )
        gateway.bind_session(
            "session-1",
            database_id="db-1",
            context={},
            allowed_tools=["create_new_case"],
        )
        with self.assertRaisesRegex(ValueError, "MCP Tool failed"):
            gateway.execute(
                {
                    "schemaVersion": "rag-ime.agent-tool-call.v1",
                    "sessionId": "session-1",
                    "tool": "create_new_case",
                    "toolCallId": "tool-error",
                    "args": {},
                }
            )
        self.assertEqual(False, gateway.ledger("session-1")[-1]["ok"])

    def test_public_verifier_projection_does_not_expose_gold_or_names(self) -> None:
        task = self._task()
        task["verifiers"][0]["name"] = "Confirm secret target value"
        results = execute_verifiers(
            FakeSqlClient(),
            task,
            database_id="db-1",
            context={},
        )

        self.assertEqual([{"verifierIndex": 1, "passed": True}], results)
        encoded = json.dumps(results)
        self.assertNotIn("secret", encoded)
        self.assertNotIn("expected", encoded)
        self.assertNotIn("actual", encoded)

    def test_verifier_score_requires_all_sql_verifiers_and_reports_failures(self) -> None:
        score = score_verifiers(
            [
                {"name": "one", "passed": True},
                {"name": "two", "passed": False, "error": "mismatch"},
            ]
        )

        self.assertFalse(score["overallSuccess"])
        self.assertEqual(2, score["total"])
        self.assertEqual(1, score["passed"])
        self.assertEqual(0.5, score["passRate"])
        self.assertEqual([2], score["failedVerifierIndexes"])

    def test_task_success_requires_completed_turn_and_all_verifiers(self) -> None:
        passing = {"overallSuccess": True}

        self.assertTrue(task_execution_succeeded("turn_completed", "", passing))
        self.assertFalse(task_execution_succeeded("turn_failed", "", passing))
        self.assertFalse(task_execution_succeeded("turn_completed", "RuntimeError", passing))
        self.assertFalse(
            task_execution_succeeded(
                "turn_completed", "", {"overallSuccess": False}
            )
        )

    def test_cli_help_runs_without_external_benchmark_or_runtime_imports(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_enterpriseops_csm_eval.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--tasks-root", completed.stdout)
        self.assertIn("held-out", completed.stdout)


if __name__ == "__main__":
    unittest.main()
