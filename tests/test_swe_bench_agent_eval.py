from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_workspace import WorkspaceHarnessError
from rag_ime.swe_bench_agent_eval import (
    DEFAULT_MODEL_REFERENCE,
    SweBenchAgentEvalError,
    SweBenchWorkspaceHarness,
    analyze_model_patch,
    build_agent_eval_report,
    capture_model_patch,
    load_official_instance_results,
    load_prepared_swe_bench,
    official_verifier_command,
    stage_agent_workspace,
    write_official_predictions,
)


INSTANCE_ID = "example__demo-1"


class SweBenchAgentEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "source"
        self.repository.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "benchmark@example.invalid")
        self._git("config", "user.name", "Benchmark")
        self._git("remote", "add", "origin", "https://github.com/example/demo.git")
        (self.repository / "demo.py").write_text(
            "def answer():\n    return 1\n", encoding="utf-8"
        )
        tests = self.repository / "tests"
        tests.mkdir()
        (tests / "test_demo.py").write_text(
            "from demo import answer\n\ndef test_answer():\n    assert answer() == 2\n",
            encoding="utf-8",
        )
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        self.base_commit = self._git("rev-parse", "HEAD")
        self.prepared_path = self.root / "prepared.json"
        self.prepared_path.write_text(
            json.dumps(self._prepared_payload(), ensure_ascii=False),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_frozen_agent_view_without_gold_or_test_patch(self) -> None:
        dataset = load_prepared_swe_bench(self.prepared_path)
        selected = dataset.select([INSTANCE_ID])

        self.assertEqual([case.instance_id for case in selected], [INSTANCE_ID])
        self.assertEqual(dataset.agent_cases[INSTANCE_ID].repo, "example/demo")
        self.assertEqual(
            dataset.verifier_cases[INSTANCE_ID].gold_patch_sha256,
            "a" * 64,
        )
        exposed = self._prepared_payload()
        exposed["agentCases"][0]["patch"] = "gold"
        self.prepared_path.write_text(json.dumps(exposed), encoding="utf-8")
        with self.assertRaisesRegex(SweBenchAgentEvalError, "verifier-only"):
            load_prepared_swe_bench(self.prepared_path)

    def test_stages_history_free_workspace_and_captures_source_patch(self) -> None:
        dataset = load_prepared_swe_bench(self.prepared_path)
        case = dataset.agent_cases[INSTANCE_ID]
        workspace = self.root / "workspace"
        mirror = self.root / "source.git"
        subprocess.run(
            ["git", "clone", "--mirror", str(self.repository), str(mirror)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                f"--git-dir={mirror}",
                "config",
                "remote.origin.url",
                "https://github.com/example/demo.git",
            ],
            check=True,
        )

        stage = stage_agent_workspace(
            case,
            source_repository=mirror,
            workspace=workspace,
        )
        self.assertFalse(stage["historyExposed"])
        self.assertFalse((workspace / ".git").exists())
        (workspace / "demo.py").write_text(
            "def answer():\n    return 2\n", encoding="utf-8"
        )
        captured = capture_model_patch(
            case,
            source_repository=mirror,
            workspace=workspace,
            verifier_case=dataset.verifier_cases[INSTANCE_ID],
        )

        self.assertTrue(captured["integrityPassed"])
        self.assertEqual(captured["changedPaths"], ["demo.py"])
        self.assertIn("+    return 2", captured["modelPatch"])
        self.assertEqual(captured["testMutationPaths"], [])

    def test_test_mutation_and_hidden_test_overlap_fail_integrity(self) -> None:
        dataset = load_prepared_swe_bench(self.prepared_path)
        patch = (
            "diff --git a/tests/test_demo.py b/tests/test_demo.py\n"
            "--- a/tests/test_demo.py\n"
            "+++ b/tests/test_demo.py\n"
            "@@ -1 +1 @@\n"
            "-assert answer() == 2\n"
            "+assert True\n"
        )

        analysis = analyze_model_patch(
            patch,
            verifier_case=dataset.verifier_cases[INSTANCE_ID],
        )

        self.assertFalse(analysis["integrityPassed"])
        self.assertEqual(analysis["testMutationPaths"], ["tests/test_demo.py"])
        self.assertEqual(
            analysis["hiddenVerifierTestOverlap"], ["tests/test_demo.py"]
        )

    def test_workspace_policy_blocks_test_writes_and_non_test_shell(self) -> None:
        workspace = self.root / "workspace-policy"
        workspace.mkdir()
        harness = SweBenchWorkspaceHarness(executor=lambda _prepared: {})
        session = {
            "mode": "coordinator",
            "executionMode": "workspace_managed",
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": [str(workspace)],
        }
        with self.assertRaisesRegex(WorkspaceHarnessError, "cannot mutate tests"):
            harness.prepare_write(
                session,
                {"path": str(workspace / "tests" / "test_demo.py"), "content": ""},
            )
        with self.assertRaisesRegex(WorkspaceHarnessError, "test/check allowlist"):
            harness.prepare_command(
                session,
                {
                    "command": "ls -la",
                    "cwd": str(workspace),
                    "timeoutSeconds": 30,
                    "allowNetwork": False,
                },
            )
        prepared = harness.prepare_command(
            session,
            {
                "command": "python -m pytest -q",
                "cwd": str(workspace),
                "timeoutSeconds": 30,
                "allowNetwork": False,
            },
        )
        self.assertEqual(prepared.command, "python -m pytest -q")

    def test_writes_official_predictions_and_builds_pinned_command(self) -> None:
        output = self.root / "predictions.jsonl"
        receipt = write_official_predictions(
            output,
            [
                {
                    "instanceId": INSTANCE_ID,
                    "modelPatch": "diff --git a/demo.py b/demo.py\n",
                    "modelNameOrPath": DEFAULT_MODEL_REFERENCE,
                }
            ],
        )
        command = official_verifier_command(
            predictions_path=output,
            instance_ids=[INSTANCE_ID],
            run_id="paw-interview-v1",
        )

        self.assertEqual(receipt["rowCount"], 1)
        self.assertIn("swebench.harness.run_evaluation", command)
        self.assertIn("princeton-nlp/SWE-bench_Verified", command)
        self.assertEqual(command[-1], INSTANCE_ID)

    def test_aggregates_only_official_per_instance_resolution(self) -> None:
        dataset = load_prepared_swe_bench(self.prepared_path)
        official_path = self.root / "official.json"
        official_path.write_text(
            json.dumps({INSTANCE_ID: {"resolved": True}}), encoding="utf-8"
        )
        official = load_official_instance_results(official_path)
        run = {
            "schemaVersion": "rag-ime.swe-bench-agent-run.v1",
            "instanceId": INSTANCE_ID,
            "terminalEvent": "turn_completed",
            "emptyPatch": False,
            "integrityPassed": True,
            "testMutationPaths": [],
            "hiddenVerifierTestOverlap": [],
            "historyExposed": False,
            "networkUsed": False,
            "modelReference": DEFAULT_MODEL_REFERENCE,
            "thinkingLevel": "max",
            "uploaded": False,
        }
        report = build_agent_eval_report(
            dataset=dataset,
            selected_instance_ids=[INSTANCE_ID],
            run_records=[run],
            official_results=official,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["officialResolvedCount"], 1)
        self.assertEqual(report["metrics"]["resolvedRateTotal"], 1.0)
        unverified = build_agent_eval_report(
            dataset=dataset,
            selected_instance_ids=[INSTANCE_ID],
            run_records=[run],
        )
        self.assertFalse(unverified["passed"])
        self.assertIsNone(unverified["metrics"]["resolvedRateTotal"])

    def _prepared_payload(self) -> dict[str, object]:
        full_ids = [INSTANCE_ID]
        interview_ids = [INSTANCE_ID]
        return {
            "schemaVersion": "rag-ime.swe-bench-verified-dataset.v1",
            "source": {
                "url": "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified",
                "version": "hf:test",
                "sha256": "f" * 64,
                "licenseReference": "https://www.swebench.com/SWE-bench/guides/datasets/",
                "corpusIncluded": False,
            },
            "adapter": {
                "name": "swe-bench-verified",
                "fullCount": 1,
                "interviewCount": 1,
                "goldPatchExposed": False,
                "testPatchExposed": False,
            },
            "fullInstanceIds": full_ids,
            "fullSplitSha256": self._bundle_sha({"instanceIds": full_ids}),
            "interviewInstanceIds": interview_ids,
            "interviewSplitSha256": self._bundle_sha(
                {"instanceIds": interview_ids}
            ),
            "agentCases": [
                {
                    "schemaVersion": "rag-ime.swe-bench-agent-case.v1",
                    "instanceId": INSTANCE_ID,
                    "repo": "example/demo",
                    "baseCommit": self.base_commit,
                    "problemStatement": "answer() should return 2",
                    "hintsText": "",
                    "createdAt": "2026-08-05T00:00:00Z",
                    "version": "1",
                    "difficulty": "<15 min fix",
                }
            ],
            "verifierCases": [
                {
                    "instanceId": INSTANCE_ID,
                    "environmentSetupCommit": self.base_commit,
                    "failToPass": ["tests/test_demo.py::test_answer"],
                    "passToPass": [],
                    "goldPatchSha256": "a" * 64,
                    "testPatchSha256": "b" * 64,
                }
            ],
        }

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.repository), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    @staticmethod
    def _bundle_sha(value: object) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


if __name__ == "__main__":
    unittest.main()
