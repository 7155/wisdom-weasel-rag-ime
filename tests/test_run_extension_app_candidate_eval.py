from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_extension_app_candidate_eval import run_extension_app_candidate_eval


ROOT = Path(__file__).resolve().parents[1]
SOURCE_APP = ROOT / "control-center-web" / "extension-apps" / "zhanggui-wenshu"


class RunExtensionAppCandidateEvalTests(unittest.TestCase):
    def test_cli_help_runs_directly_from_repository_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_extension_app_candidate_eval.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--app-directory", completed.stdout)

    def test_valid_source_candidate_emits_linked_sandbox_trace_and_eval_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="extension-app-candidate-") as temporary:
            root = Path(temporary)
            report = run_extension_app_candidate_eval(
                SOURCE_APP,
                root / "workspace",
            )

        self.assertEqual("sandbox_verified", report["status"])
        self.assertEqual("extension:zhanggui-wenshu", report["candidate"]["appId"])
        self.assertEqual("sgg", report["suite"]["suiteId"])
        self.assertEqual(1, report["suite"]["fixtureCount"])
        self.assertEqual({"precision": 1.0, "recall": 1.0, "f1": 1.0}, report["result"]["metrics"])
        self.assertEqual(0, report["result"]["providerCalls"])
        self.assertTrue(report["result"]["productionWriteBlocked"])
        self.assertTrue(report["result"]["traceVerified"])
        self.assertTrue(str(report["receipts"]["traceId"]).startswith("trace:sgg:"))
        self.assertTrue(str(report["receipts"]["evalRunId"]).startswith("eval:"))
        self.assertTrue(str(report["receipts"]["sandboxRunId"]).startswith("sandbox:sgg:"))
        self.assertFalse(report["boundary"]["realBusinessData"])
        self.assertFalse(report["candidate"]["installActionPerformed"])
        self.assertFalse(report["boundary"]["installActionPerformed"])
        self.assertNotIn("installedStateChanged", report["candidate"])
        self.assertNotIn(str(root), json.dumps(report, ensure_ascii=False))

    def test_invalid_binding_emits_failure_receipt_without_running_sandbox(self) -> None:
        with tempfile.TemporaryDirectory(prefix="extension-app-invalid-") as temporary:
            root = Path(temporary)
            candidate = root / "zhanggui-wenshu"
            shutil.copytree(SOURCE_APP, candidate)
            manifest_path = candidate / "pawos-app.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bindingSha256"] = "f" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = run_extension_app_candidate_eval(
                candidate,
                root / "workspace",
            )

        self.assertEqual("source_validation_failed", report["status"])
        self.assertEqual("binding_digest_mismatch", report["failure"]["failureClass"])
        self.assertFalse(report["boundary"]["sandboxExecuted"])
        self.assertFalse(report["boundary"]["installActionPerformed"])

    def test_candidate_tree_rejects_symlink_before_hashing_external_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="extension-app-symlink-") as temporary:
            root = Path(temporary)
            candidate = root / "zhanggui-wenshu"
            shutil.copytree(SOURCE_APP, candidate)
            external = root / "host-secret.txt"
            external.write_text("first private value", encoding="utf-8")
            (candidate / "host-link.txt").symlink_to(external)

            first = run_extension_app_candidate_eval(candidate, root / "workspace-1")
            external.write_text("different private value", encoding="utf-8")
            second = run_extension_app_candidate_eval(candidate, root / "workspace-2")

        self.assertEqual("source_validation_failed", first["status"])
        self.assertEqual("source_contract_invalid", first["failure"]["failureClass"])
        self.assertFalse(first["candidate"]["sourceTreeHashAvailable"])
        self.assertEqual("", first["candidate"]["sourceTreeSha256"])
        self.assertEqual(first["failure"]["errorFingerprint"], second["failure"]["errorFingerprint"])


if __name__ == "__main__":
    unittest.main()
