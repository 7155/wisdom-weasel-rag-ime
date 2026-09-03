from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.eval_lab import EvalLabProjection
from scripts.import_enterpriseops_eval_snapshot import import_snapshot


class ImportEnterpriseOpsEvalSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="paw-eval-lab-import-")
        self.root = Path(self.tmp.name)
        self.source_root = self.root / "source-run"
        self.source_root.mkdir()
        self.source_db = self.source_root / "paw.sqlite"
        self.source_sessions = self.source_root / "agent" / "sessions"
        self.source_sessions.mkdir(parents=True)
        self.target_db = self.root / "target" / "paw.sqlite"
        self.target_sessions = self.root / "target" / "Agent" / "sessions"
        self._create_source_task("task_alpha", "pi-alpha", 11)
        self._create_source_task("task_beta", "pi-beta", 5)
        self.report = self.root / "report.json"
        self.report.write_text(
            json.dumps(
                {
                    "schemaVersion": "paw.enterpriseops-csm-eval.v1",
                    "split": "validation",
                    "reportSha256": "a" * 64,
                    "lane": {
                        "workflowProfile": "baseline-v1",
                        "taskCount": 2,
                        "taskSuccessCount": 1,
                        "taskSuccessRate": 0.5,
                        "verifierCount": 16,
                        "verifierPassCount": 14,
                        "verifierPassRate": 0.875,
                        "toolCalls": 19,
                        "failedToolCalls": 0,
                        "latencyMs": 1200.0,
                        "allDatabasesCleaned": True,
                        "tasks": [
                            {
                                "taskId": "task_alpha",
                                "taskSucceeded": True,
                                "toolCalls": 8,
                                "failedToolCalls": 0,
                                "latencyMs": 500.0,
                                "terminalEvent": "turn_completed",
                                "verifier": {"passed": 11, "total": 11, "passRate": 1.0},
                            },
                            {
                                "taskId": "task_beta",
                                "taskSucceeded": False,
                                "toolCalls": 11,
                                "failedToolCalls": 0,
                                "latencyMs": 700.0,
                                "terminalEvent": "turn_completed",
                                "verifier": {"passed": 3, "total": 5, "passRate": 0.6},
                            },
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_source_task(self, task_id: str, pi_session_id: str, message_count: int) -> None:
        store = AgentSessionStore(self.source_db)
        store.initialize()
        transcript = self.source_sessions / f"{pi_session_id}.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    json.dumps({"type": "session", "version": 3, "id": pi_session_id}),
                    json.dumps(
                        {
                            "type": "message",
                            "id": f"message-{task_id}",
                            "parentId": None,
                            "message": {
                                "role": "user",
                                "content": [{"type": "text", "text": f"Customer request: {task_id}"}],
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        session = store.create(
            title=f"EnterpriseOps CSM {task_id}",
            model_profile="openai-codex/gpt-5.6-sol",
            thinking_level="high",
            created_at_ms=100,
        )
        store.bind_pi_session(
            str(session["id"]),
            pi_session_id=pi_session_id,
            session_file=transcript.as_posix(),
            message_count=message_count,
            updated_at_ms=200,
        )
        store.set_status(
            str(session["id"]),
            "idle",
            message_count=message_count,
            updated_at_ms=300,
        )

    def test_dry_run_is_read_only_and_write_imports_exact_snapshot_sessions(self) -> None:
        before_source = hashlib.sha256(self.source_db.read_bytes()).hexdigest()
        dry = import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=False,
        )

        self.assertEqual(dry["status"], "dry_run")
        self.assertEqual(dry["sessionCount"], 2)
        self.assertFalse(self.target_db.exists())
        self.assertEqual(before_source, hashlib.sha256(self.source_db.read_bytes()).hexdigest())

        written = import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=True,
        )

        self.assertEqual(written["status"], "imported")
        self.assertEqual(written["sessionCount"], 2)
        target = AgentSessionStore(self.target_db)
        sessions = target.list()
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(item["evaluationSnapshot"] for item in sessions))
        self.assertTrue(all(item["executionMode"] == "read_only" for item in sessions))
        for item in sessions:
            binding = target.runtime_binding(str(item["id"]))
            self.assertIsNotNone(binding)
            transcript = Path(str(binding["transcriptRef"]))
            self.assertTrue(transcript.is_file())
            self.assertTrue(transcript.is_relative_to(self.target_sessions))
            metadata = binding["metadata"]["evaluationSnapshot"]
            self.assertEqual(metadata["runId"], "enterpriseops-validation-v1")
            self.assertNotIn("sourcePath", metadata)
        self.assertEqual(before_source, hashlib.sha256(self.source_db.read_bytes()).hexdigest())

        repeated = import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=True,
        )
        self.assertEqual(repeated["status"], "already_imported")
        self.assertEqual(len(AgentSessionStore(self.target_db).list()), 2)

    def test_rejects_transcript_outside_the_source_run(self) -> None:
        outside = self.root / "outside.jsonl"
        outside.write_text('{}\n', encoding="utf-8")
        with sqlite3.connect(self.source_db) as connection:
            connection.execute(
                "UPDATE agent_runtime_bindings SET transcript_ref = ? WHERE external_session_id = 'pi-alpha'",
                (outside.as_posix(),),
            )

        with self.assertRaisesRegex(ValueError, "escapes source run"):
            import_snapshot(
                source_db=self.source_db,
                report_path=self.report,
                target_db=self.target_db,
                target_session_dir=self.target_sessions,
                run_id="enterpriseops-validation-v1",
                write=False,
            )

    def test_persists_bounded_redacted_explanation_from_transcript_and_verifiers(self) -> None:
        transcript = self.source_sessions / "pi-alpha.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    json.dumps({"type": "session", "version": 3, "id": "pi-alpha"}),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "user-alpha",
                            "parentId": None,
                            "message": {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": (
                                            "Policy details.\n\nCustomer request:\n"
                                            "Update the entitlement and create the case. "
                                            "The private file is /Volumes/private/run.sql.\n\n"
                                            "Work only through the available CSM tools."
                                        ),
                                    }
                                ],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "assistant-alpha",
                            "parentId": "user-alpha",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "thinking",
                                        "thinking": "private reasoning must not be projected",
                                    },
                                    {
                                        "type": "text",
                                        "text": (
                                            "Completed the case. Read /private/secret/output.txt; "
                                            "Read /Volumes/undo 4t/git/private.txt. "
                                            "SELECT hidden_value FROM gold; hidden_gold: expected value."
                                        ),
                                    },
                                ],
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["lane"]["tasks"][0]["verifierResults"] = [
            {"verifierIndex": 1, "passed": True},
            {"verifierIndex": 2, "passed": False},
        ]
        self.report.write_text(json.dumps(report), encoding="utf-8")

        written = import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=True,
        )

        self.assertEqual(written["status"], "imported")
        target = AgentSessionStore(self.target_db)
        alpha = next(
            item for item in target.list() if "Task 1" in str(item.get("title"))
        )
        metadata = target.runtime_binding(str(alpha["id"]))["metadata"]
        explanation = metadata["evaluationSnapshot"]["explanation"]
        self.assertEqual(
            explanation["businessRequest"]["normalizedText"],
            "Update the entitlement and create the case. The private file is [path redacted].",
        )
        outcome = explanation["agentOutcome"]["normalizedSummary"]
        self.assertNotIn("/private/secret", outcome)
        self.assertNotIn("/Volumes/", outcome)
        self.assertNotIn("4t/git", outcome)
        self.assertNotIn("SELECT", outcome)
        self.assertNotIn("hidden gold", outcome.lower())
        self.assertNotIn("hidden_gold", outcome.lower())
        self.assertNotIn("private reasoning", outcome.lower())
        self.assertLessEqual(len(outcome), 600)
        self.assertEqual(explanation["acceptance"]["passed"], 1)
        self.assertEqual(explanation["acceptance"]["total"], 2)
        self.assertEqual(
            explanation["acceptance"]["items"],
            [
                {
                    "id": "verifier-1",
                    "label": "Verifier 1",
                    "status": "pass",
                    "failureOwner": None,
                    "explanation": "验收项通过。",
                },
                {
                    "id": "verifier-2",
                    "label": "Verifier 2",
                    "status": "fail",
                    "failureOwner": "agent",
                    "explanation": "Agent 输出未满足该验收项。",
                },
            ],
        )
        self.assertNotIn("task_alpha", json.dumps(explanation, ensure_ascii=False))

        payload = EvalLabProjection(self.target_db).list_runs()
        validate_contract(payload, "eval-lab-run-list.v1.json")
        task = next(item for item in payload["items"][0]["tasks"] if item["taskIndex"] == 1)
        self.assertEqual(task["explanation"], explanation)

    def test_backfills_explanation_for_exact_existing_run_without_copying_transcripts(self) -> None:
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["lane"]["tasks"][0]["verifierResults"] = [
            {"verifierIndex": 1, "passed": True},
        ]
        self.report.write_text(json.dumps(report), encoding="utf-8")
        initial = import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=True,
        )
        target = AgentSessionStore(self.target_db)
        before_ids = sorted(str(item["id"]) for item in target.list())
        before_transcripts = {
            str(item["id"]): Path(str(target.runtime_binding(str(item["id"]))["transcriptRef"])).read_bytes()
            for item in target.list()
        }
        with sqlite3.connect(self.target_db) as connection:
            rows = connection.execute(
                "SELECT session_id, metadata_json FROM agent_runtime_bindings"
            ).fetchall()
            for session_id, metadata_json in rows:
                metadata = json.loads(metadata_json)
                del metadata["evaluationSnapshot"]["explanation"]
                connection.execute(
                    "UPDATE agent_runtime_bindings SET metadata_json = ? WHERE session_id = ?",
                    (json.dumps(metadata, separators=(",", ":")), session_id),
                )

        backfilled = import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=True,
        )

        self.assertEqual(backfilled["status"], "explanation_backfilled")
        self.assertEqual(initial["sessionCount"], 2)
        self.assertEqual(before_ids, sorted(str(item["id"]) for item in target.list()))
        for item in target.list():
            session_id = str(item["id"])
            binding = target.runtime_binding(session_id)
            self.assertEqual(Path(str(binding["transcriptRef"])).read_bytes(), before_transcripts[session_id])
            self.assertIn("explanation", binding["metadata"]["evaluationSnapshot"])

        tampered_path = Path(str(target.runtime_binding(before_ids[0])["transcriptRef"]))
        tampered_path.write_bytes(tampered_path.read_bytes() + b"tampered\n")
        with self.assertRaisesRegex(ValueError, "source hashes do not match"):
            import_snapshot(
                source_db=self.source_db,
                report_path=self.report,
                target_db=self.target_db,
                target_session_dir=self.target_sessions,
                run_id="enterpriseops-validation-v1",
                write=True,
            )

    def test_existing_run_fails_closed_when_current_report_hash_changes(self) -> None:
        import_snapshot(
            source_db=self.source_db,
            report_path=self.report,
            target_db=self.target_db,
            target_session_dir=self.target_sessions,
            run_id="enterpriseops-validation-v1",
            write=True,
        )
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["lane"]["workflowProfile"] = "tampered-profile"
        self.report.write_text(json.dumps(report), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source hashes do not match"):
            import_snapshot(
                source_db=self.source_db,
                report_path=self.report,
                target_db=self.target_db,
                target_session_dir=self.target_sessions,
                run_id="enterpriseops-validation-v1",
                write=True,
            )


if __name__ == "__main__":
    unittest.main()
