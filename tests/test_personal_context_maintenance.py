from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_role_book import AgentRoleBookStore
from rag_ime.personal_context import (
    AgentMemoryEvidenceStore,
    PersonalContextConsolidator,
)
from rag_ime.personal_context_maintenance import (
    PersonalContextMaintenanceConfig,
    PersonalContextMaintenanceRunner,
    write_personal_context_maintenance_report,
)


class PersonalContextMaintenanceRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-personal-context-maintenance-"
        )
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.role_books = AgentRoleBookStore(self.db_path)
        self.role_books.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_run_is_per_project_and_role_draft_only_and_idempotent_by_default(
        self,
    ) -> None:
        self._seed_role("architect", "role-v1", created_at_ms=10)
        self._seed_role("reviewer", "role-v2", created_at_ms=20)
        self._record_work(
            "project-a",
            "architect",
            "receipt:a",
            "完成个人上下文游标",
            occurred_at_ms=100,
        )
        self._record_work(
            "project-b",
            "reviewer",
            "receipt:b",
            "完成角色书草案审阅",
            occurred_at_ms=110,
        )
        runner = PersonalContextMaintenanceRunner(
            self.db_path,
            config=PersonalContextMaintenanceConfig(min_interval_ms=86_400_000),
        )

        first = runner.run_once(now_ms=1_000)
        second = runner.run_once(now_ms=1_001)
        status = runner.status(now_ms=1_001)

        self.assertTrue(first["ok"])
        self.assertTrue(first["draftOnly"])
        self.assertFalse(first["applySafeRecentWork"])
        self.assertEqual(first["summary"]["targetCount"], 2)
        self.assertEqual(first["summary"]["succeededCount"], 2)
        self.assertEqual(
            {(item["project"], item["roleId"]) for item in first["targets"]},
            {("project-a", "architect"), ("project-b", "reviewer")},
        )
        for target in first["targets"]:
            self.assertTrue(target["artifacts"]["digestId"])
            self.assertTrue(target["artifacts"]["userMemoryDraftId"])
            self.assertTrue(target["artifacts"]["roleBookDraftId"])
            self.assertEqual(target["artifacts"]["appliedRoleBookRevisionId"], "")
        self.assertEqual(second["summary"]["succeededCount"], 0)
        self.assertEqual(second["summary"]["notDueCount"], 2)
        self.assertEqual(status["summary"]["targetCount"], 2)
        for target in status["targets"]:
            self.assertEqual(target["dueReason"], "no_evidence")
            self.assertEqual(target["lastRunStatus"], "succeeded")
            self.assertEqual(target["lastSucceededAtMs"], 1_000)
            self.assertEqual(target["lastRunError"], "")

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT project, role_id, status, output_json
                FROM personal_context_consolidation_runs
                ORDER BY project, role_id
                """
            ).fetchall()
        self.assertEqual(len(rows), 2)
        for _, _, run_status, output_json in rows:
            output = json.loads(output_json)
            self.assertEqual(run_status, "succeeded")
            self.assertTrue(output["digest"])
            self.assertTrue(output["userMemoryDraft"])
            self.assertTrue(output["roleBookDraft"])
            self.assertEqual(output["appliedRoleBookRevisionId"], "")
        self.assertEqual(
            self.role_books.active("architect", "role-v1")["revisionNumber"],
            1,
        )
        self.assertEqual(
            self.role_books.active("reviewer", "role-v2")["revisionNumber"],
            1,
        )

    def test_safe_recent_work_is_applied_only_with_explicit_switch(self) -> None:
        self._seed_role("architect", "role-v1", created_at_ms=10)
        self._record_work(
            "project-a",
            "architect",
            "receipt:apply",
            "完成可验证的每日整理任务",
            occurred_at_ms=100,
        )
        config = PersonalContextMaintenanceConfig(
            project="project-a",
            apply_safe_recent_work=True,
            min_interval_ms=86_400_000,
        )

        report = PersonalContextMaintenanceRunner(
            self.db_path,
            config=config,
        ).run_once(now_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertFalse(report["draftOnly"])
        self.assertTrue(report["applySafeRecentWork"])
        target = report["targets"][0]
        self.assertEqual(target["runStatus"], "succeeded")
        self.assertTrue(target["artifacts"]["appliedRoleBookRevisionId"])
        active = self.role_books.active("architect", "role-v1")
        self.assertEqual(active["revisionNumber"], 2)
        self.assertEqual(
            [item["text"] for item in active["sections"]["recentWork"]],
            ["已验收工作项 work:receipt:apply"],
        )

    def test_periodic_runner_persists_model_role_review_without_activation(
        self,
    ) -> None:
        seed = self._seed_role("architect", "role-v1", created_at_ms=10)
        evidence = AgentMemoryEvidenceStore(self.db_path, project="project-a")
        user = evidence.record_user_message(
            session_id="session:periodic",
            pi_entry_id="user:periodic",
            role_id="architect",
            text="后续继续维护角色书中的当前承诺。",
            occurred_at_ms=100,
        )["evidence"]
        assistant = evidence.record_assistant_message(
            session_id="session:periodic",
            pi_entry_id="assistant:periodic",
            role_id="architect",
            text="今天已经发现并修正时间线证据边界问题。",
            occurred_at_ms=110,
        )["evidence"]
        self._record_work(
            "project-a",
            "architect",
            "receipt:periodic",
            "完成周期性角色书整理",
            occurred_at_ms=120,
        )
        organizer = _MaintenanceRoleBookOrganizer(
            [user["evidenceId"], assistant["evidenceId"]]
        )

        report = PersonalContextMaintenanceRunner(
            self.db_path,
            config=PersonalContextMaintenanceConfig(
                project="project-a",
                min_interval_ms=0,
                apply_safe_recent_work=True,
            ),
            role_book_organizer=organizer,
        ).run_once(now_ms=1_000, force=True)

        self.assertTrue(report["ok"])
        artifact = report["targets"][0]["artifacts"]
        self.assertTrue(artifact["proposedRoleBookRevisionId"])
        self.assertTrue(artifact["appliedRoleBookRevisionId"])
        proposed = self.role_books.get_revision(
            artifact["proposedRoleBookRevisionId"]
        )
        self.assertEqual(proposed["status"], "draft")
        self.assertEqual(
            proposed["sourceRevisionId"],
            artifact["appliedRoleBookRevisionId"],
        )
        self.assertTrue(proposed["sections"]["lessonsAndLimits"])
        self.assertTrue(proposed["sections"]["activeCommitments"])
        self.assertEqual(
            self.role_books.active("architect", "role-v1")["revisionId"],
            artifact["appliedRoleBookRevisionId"],
        )
        self.assertNotEqual(artifact["appliedRoleBookRevisionId"], seed["revisionId"])
        self.assertEqual(len(organizer.calls), 1)

    def test_one_target_failure_is_reported_without_stopping_other_targets(
        self,
    ) -> None:
        self._seed_role("architect", "role-v1", created_at_ms=10)
        self._seed_role("reviewer", "role-v2", created_at_ms=20)
        self._record_work(
            "broken-project",
            "architect",
            "receipt:broken",
            "这一条会触发测试故障",
            occurred_at_ms=100,
        )
        self._record_work(
            "healthy-project",
            "reviewer",
            "receipt:healthy",
            "这一条仍应成功整理",
            occurred_at_ms=110,
        )

        def factory(
            db_path: str | Path,
            *,
            project: str,
            role_book_applier: object | None,
        ) -> PersonalContextConsolidator:
            if project == "broken-project":
                return _ExplodingConsolidator()  # type: ignore[return-value]
            return PersonalContextConsolidator(
                db_path,
                project=project,
                role_book_applier=role_book_applier,
            )

        report = PersonalContextMaintenanceRunner(
            self.db_path,
            config=PersonalContextMaintenanceConfig(min_interval_ms=0),
            consolidator_factory=factory,
        ).run_once(now_ms=1_000)

        by_project = {item["project"]: item for item in report["targets"]}
        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["failedCount"], 1)
        self.assertEqual(by_project["broken-project"]["runStatus"], "failed")
        self.assertIn(
            "synthetic background failure",
            by_project["broken-project"]["error"],
        )
        self.assertEqual(by_project["healthy-project"]["runStatus"], "succeeded")
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT project, status
                FROM personal_context_consolidation_runs
                ORDER BY project
                """
            ).fetchall()
        self.assertEqual(rows, [("healthy-project", "succeeded")])

    def test_failed_persisted_run_exposes_retry_due_error_and_last_run(self) -> None:
        self._seed_role("architect", "role-v1", created_at_ms=10)
        self._record_work(
            "project-a",
            "architect",
            "receipt:failed-apply",
            "这一条会进入 recentWork 的安全应用边界",
            occurred_at_ms=100,
        )

        def failing_applier(request: object) -> object:
            del request
            raise RuntimeError("role book apply unavailable")

        runner = PersonalContextMaintenanceRunner(
            self.db_path,
            config=PersonalContextMaintenanceConfig(
                project="project-a",
                apply_safe_recent_work=True,
                min_interval_ms=86_400_000,
            ),
            role_book_applier=failing_applier,
        )
        run = runner.run_once(now_ms=1_000)
        status = runner.status(now_ms=1_001)

        self.assertFalse(run["ok"])
        self.assertEqual(run["targets"][0]["runStatus"], "failed")
        target = status["targets"][0]
        self.assertFalse(status["ok"])
        self.assertTrue(target["due"])
        self.assertEqual(target["dueReason"], "retry_failed")
        self.assertEqual(target["status"], "failed")
        self.assertEqual(target["lastRunStatus"], "failed")
        self.assertEqual(target["lastRunAtMs"], 1_000)
        self.assertEqual(target["lastSucceededAtMs"], 0)
        self.assertIn("role book apply unavailable", target["error"])

    def test_configuration_defaults_to_enabled_draft_only_and_report_is_atomic(
        self,
    ) -> None:
        default = PersonalContextMaintenanceConfig.from_environ({})
        explicit = PersonalContextMaintenanceConfig.from_environ(
            {
                "RAG_IME_PERSONAL_CONTEXT_MAINTENANCE_ENABLED": "true",
                "RAG_IME_PERSONAL_CONTEXT_APPLY_SAFE_RECENT_WORK": "1",
                "RAG_IME_PERSONAL_CONTEXT_INTERVAL_SECONDS": "900",
                "RAG_IME_PERSONAL_CONTEXT_BATCH_LIMIT": "25",
            },
            project="project-a",
            role_id="architect",
            role_version="role-v1",
        )
        report_path = Path(self.temporary.name) / "runs" / "latest.json"
        write_personal_context_maintenance_report(
            report_path,
            {"schemaVersion": "test.v1", "ok": True},
        )

        self.assertTrue(default.enabled)
        self.assertFalse(default.apply_safe_recent_work)
        self.assertEqual(default.min_interval_ms, 86_400_000)
        self.assertTrue(explicit.apply_safe_recent_work)
        self.assertEqual(explicit.min_interval_ms, 900_000)
        self.assertEqual(explicit.batch_limit, 25)
        self.assertEqual(
            json.loads(report_path.read_text(encoding="utf-8")),
            {"schemaVersion": "test.v1", "ok": True},
        )
        self.assertEqual(
            list(report_path.parent.glob(f".{report_path.name}.*.tmp")),
            [],
        )

    def test_cli_run_and_status_expose_the_background_maintenance_state(
        self,
    ) -> None:
        self._seed_role("architect", "role-v1", created_at_ms=10)
        self._record_work(
            "project-a",
            "architect",
            "receipt:cli",
            "通过真实 CLI 入口整理个人上下文",
            occurred_at_ms=100,
        )
        root = Path(__file__).resolve().parents[1]
        report_path = Path(self.temporary.name) / "runs" / "cli-run.json"
        common = [
            sys.executable,
            "-m",
            "rag_ime.cli",
            "--core-mode",
            "local",
            "--db-path",
            str(self.db_path),
        ]

        run = subprocess.run(
            [
                *common,
                "personal-context-maintenance-run",
                "--project",
                "project-a",
                "--interval-seconds",
                "86400",
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            env={
                **os.environ,
                "RAG_IME_PERSONAL_CONTEXT_APPLY_SAFE_RECENT_WORK": "0",
            },
            text=True,
            capture_output=True,
            check=True,
        )
        status = subprocess.run(
            [
                *common,
                "personal-context-maintenance-status",
                "--project",
                "project-a",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        run_payload = json.loads(run.stdout)
        status_payload = json.loads(status.stdout)
        self.assertTrue(run_payload["ok"])
        self.assertTrue(run_payload["draftOnly"])
        self.assertEqual(run_payload["targets"][0]["runStatus"], "succeeded")
        self.assertEqual(
            json.loads(report_path.read_text(encoding="utf-8")),
            run_payload,
        )
        self.assertEqual(
            status_payload["targets"][0]["lastRunStatus"],
            "succeeded",
        )
        self.assertEqual(status_payload["targets"][0]["dueReason"], "no_evidence")

    def _seed_role(
        self,
        role_id: str,
        role_version: str,
        *,
        created_at_ms: int,
    ) -> dict[str, object]:
        return self.role_books.ensure_seeded(
            role_id,
            role_version,
            display_name=role_id,
            mission="维护个人上下文",
            created_at_ms=created_at_ms,
        )

    def _record_work(
        self,
        project: str,
        role_id: str,
        receipt_id: str,
        text: str,
        *,
        occurred_at_ms: int,
    ) -> None:
        store = AgentMemoryEvidenceStore(self.db_path, project=project)
        store.initialize()
        store.record_work_receipt(
            work_item_id=f"work:{receipt_id}",
            receipt_id=receipt_id,
            role_id=role_id,
            text=text,
            occurred_at_ms=occurred_at_ms,
        )


class _ExplodingConsolidator:
    def due(
        self,
        role_id: str,
        *,
        now_ms: int,
        min_interval_ms: int,
    ) -> dict[str, object]:
        del role_id, now_ms, min_interval_ms
        return {
            "due": True,
            "reason": "new_evidence",
            "cursor": {},
            "runId": "",
        }

    def run(self, *args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        raise RuntimeError("synthetic background failure")


class _MaintenanceRoleBookOrganizer:
    provider_name = "fake-maintenance-role-organizer"

    def __init__(self, evidence_ids: list[str]) -> None:
        self.evidence_ids = evidence_ids
        self.calls: list[dict[str, object]] = []

    def curate_role_book(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        role_id: str,
        role_version: str,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "bundle": bundle,
                "project": project,
                "roleId": role_id,
                "roleVersion": role_version,
            }
        )
        user_id, assistant_id = self.evidence_ids
        return {
            "traitProposals": [],
            "capabilityProposals": [],
            "lessonProposals": [
                {
                    "text": "时间线只能辅助判断，角色经验必须引用对话证据",
                    "confidence": 0.95,
                    "sourceEvidenceIds": [assistant_id],
                }
            ],
            "commitmentProposals": [
                {
                    "text": "继续维护角色书中的当前承诺",
                    "confidence": 0.85,
                    "sourceEvidenceIds": [user_id],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
