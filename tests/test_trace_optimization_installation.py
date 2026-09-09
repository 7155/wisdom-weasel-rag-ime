from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_extensions import AgentExtensionService
from rag_ime.db import sqlite_connection
from rag_ime.trace_optimization_installation import apply_trace_candidate
from rag_ime.trace_optimization_versions import TraceOptimizationVersionStore


class CandidateOwner:
    """Host boundary mock: candidates and comparisons cannot be supplied by UI."""

    def __init__(self, candidate, versions):
        self.candidate = copy.deepcopy(candidate)
        self.versions = versions
        self.comparisons = [{"candidateId": candidate["candidateId"], "comparisonId": "comparison:one",
            "decision": "kept", "comparable": True}]
        self.applications = {}

    def get_candidate(self, candidate_id):
        return copy.deepcopy(self.candidate) if candidate_id == self.candidate["candidateId"] else None

    def read(self, report_id):
        if report_id != self.candidate["reportId"]:
            raise KeyError(report_id)
        return {"comparisons": copy.deepcopy(self.comparisons), "applications": list(self.applications.values())}

    def bind_application(self, candidate_id, *, client_request_id, action, receipt_ref):
        if client_request_id in self.applications:
            return self.applications[client_request_id]
        receipt = self.versions.application_receipt(receipt_ref)
        expected = {"candidateId": candidate_id, "comparisonId": self.comparisons[-1]["comparisonId"],
            "targetKind": self.candidate["targetKind"], "targetRef": self.candidate["targetRef"],
            "versionRef": self.candidate["candidateVersionRef"], "action": action}
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise ValueError("receipt identity differs from candidate")
        self.applications[client_request_id] = {"applicationId": "application:" + client_request_id,
            "receiptRef": receipt_ref, "status": receipt["status"], **expected}
        return self.applications[client_request_id]


class PackageRuntime:
    """No real Pi or package install: exercise the real extension service API."""

    def __init__(self):
        self.calls = []
        self.prepared = {}
        self.installed = []
        self.preview_enabled = {}
        self.failure = None
        self.receipt_drift = False
        self.on_install = None

    @staticmethod
    def package_digest(source):
        root = Path(source)
        files = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}
        return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()

    def plugin_prepare_package(self, source):
        self.calls.append(("prepare", source))
        manifest = json.loads((Path(source) / "package.json").read_text())
        prepared_id = "prepared:" + str(len(self.prepared))
        result = {"preparedPackageId": prepared_id, "manifest": {"id": manifest["name"],
            "name": manifest["name"], "version": manifest["version"], "description": "temporary fixture", "permissions": []},
            "digest": self.package_digest(source), "files": ["package.json", "index.ts"], "totalBytes": 100,
            "source": {"kind": "local", "requested": source}, "resources": {"extensions": ["index.ts"]},
            "installPreview": {"operation": "install", "enabledAfterInstall": False}}
        self.prepared[prepared_id] = result
        return copy.deepcopy(result)

    def plugin_list(self):
        self.calls.append(("list", None))
        return copy.deepcopy(self.installed)

    def plugin_preview_install(self, payload):
        self.calls.append(("preview", copy.deepcopy(payload)))
        prepared = self.prepared[payload["preparedPackageId"]]
        if payload["expectedDigest"] != prepared["digest"]:
            raise ValueError("prepared digest mismatch")
        token = "native-preview:" + payload["preparedPackageId"]
        self.preview_enabled[token] = payload["enable"]
        return {"previewToken": token, "payloadSha256": "b" * 64, "requiredConfirm": "apply"}

    def plugin_install(self, payload):
        self.calls.append(("install", copy.deepcopy(payload)))
        if self.on_install:
            self.on_install()
        if self.failure:
            raise self.failure
        prepared = self.prepared[payload["preparedPackageId"]]
        self.assert_gate(payload)
        plugin = {"id": prepared["manifest"]["id"], "name": prepared["manifest"]["name"],
            "version": prepared["manifest"]["version"], "digest": prepared["digest"],
            "enabled": payload["enable"], "installedVersions": [{"version": prepared["manifest"]["version"], "digest": prepared["digest"]}]}
        if self.receipt_drift:
            plugin["digest"] = "c" * 64
        self.installed = [plugin]
        return plugin

    def assert_gate(self, payload):
        if payload["confirmText"] != "apply" or payload["payloadSha256"] != "b" * 64 or not payload["previewToken"]:
            raise ValueError("missing real owner gate")


class TraceOptimizationInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="paw-trace-installation-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "active" / "SKILL.md"
        self.target.parent.mkdir()
        self.target.write_text("Original skill\n", encoding="utf-8")
        self.draft = self.root / "draft.md"
        self.draft.write_text("Candidate skill with bounded retry\n", encoding="utf-8")
        self.versions = TraceOptimizationVersionStore(self.root / "paw.sqlite", artifact_root=self.root / "artifacts")
        common = {"targetKind": "skill", "targetRef": "skill:retry", "destinationPath": str(self.target)}
        before = self.versions.register("report:one", {**common, "sourcePath": str(self.target)}, roots=[str(self.root)])
        after = self.versions.register("report:one", {**common, "sourcePath": str(self.draft)}, roots=[str(self.root)])
        self.candidate = {"candidateId": "candidate:one", "reportId": "report:one", "targetKind": "skill",
            "targetRef": "skill:retry", "parentVersionRef": before["versionRef"], "candidateVersionRef": after["versionRef"],
            "availableActions": ["keep_original", "run_candidate", "apply", "replace"]}
        self.candidates = CandidateOwner(self.candidate, self.versions)
        self.extensions = None

    def apply(self, **kwargs):
        return apply_trace_candidate(versions=self.versions, candidates=self.candidates, extensions=self.extensions,
            candidate=self.candidate, action=kwargs.pop("action", "apply"),
            client_request_id=kwargs.pop("client_request_id", "request:one"), **kwargs)

    def test_actual_file_replacement_returns_bound_receipt_and_retry_does_not_apply_again(self):
        result = self.apply()
        self.assertEqual(self.target.read_text(), "Candidate skill with bounded retry\n")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["receipt"]["versionRef"], self.candidate["candidateVersionRef"])
        self.assertEqual(result["application"]["comparisonId"], "comparison:one")
        self.target.write_text("A later user edit\n", encoding="utf-8")
        replay = self.apply()
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["receipt"], result["receipt"])
        self.assertEqual(self.target.read_text(), "A later user edit\n")

    def package_candidate(self, *, installed=False):
        self.runtime = PackageRuntime()
        self.extensions = AgentExtensionService(runtime_provider=lambda: self.runtime, inbox_root=self.root / "inbox")
        baseline = self.root / "original-package"
        baseline.mkdir()
        candidate_path = self.root / "candidate-package"
        candidate_path.mkdir()
        for path, version in ((baseline, "1.0.0"), (candidate_path, "2.0.0")):
            (path / "package.json").write_text(json.dumps({"name": "retry-helper", "version": version,
                "pi": {"extensions": ["index.ts"]}}))
            (path / "index.ts").write_text("// " + version)
        common = {"targetKind": "tool", "targetRef": "tool:retry-helper", "destinationPath": str(baseline)}
        before = self.versions.register("report:one", {**common, "sourcePath": str(baseline)}, roots=[str(self.root)])
        after = self.versions.register("report:one", {**common, "sourcePath": str(candidate_path)}, roots=[str(self.root)])
        self.candidate.update(targetKind="tool", targetRef="tool:retry-helper", parentVersionRef=before["versionRef"],
            candidateVersionRef=after["versionRef"], availableActions=["keep_original", "run_candidate", "install", "replace"])
        self.candidates = CandidateOwner(self.candidate, self.versions)
        if installed:
            self.runtime.installed = [{"id": "retry-helper", "name": "retry-helper", "version": "1.0.0",
                "digest": self.runtime.package_digest(baseline), "enabled": True}]
        return baseline, candidate_path

    def test_action_requires_current_host_candidate_and_real_kept_comparison(self):
        for mutation in (lambda: self.candidates.candidate.update(availableActions=["keep_original", "run_candidate"]),
                         lambda: self.candidates.comparisons[-1].update(decision="rejected")):
            self.candidates = CandidateOwner(self.candidate, self.versions)
            mutation()
            with self.assertRaises(ValueError):
                self.apply()
            self.assertEqual(self.target.read_text(), "Original skill\n")
        self.candidates = CandidateOwner(self.candidate, self.versions)
        with self.assertRaises(ValueError):
            apply_trace_candidate(self.versions, self.candidates, None, {**self.candidate, "targetRef": "another-tool"}, "apply", "forged")
        with self.assertRaises(ValueError):
            self.apply(action="rollback")

    def test_registered_destination_report_and_snapshot_must_match(self):
        after = self.versions.get(self.candidate["candidateVersionRef"])
        tampered = {**after, "destinationPath": str(self.root / "unrelated.txt")}
        original_get = self.versions.get
        with patch.object(self.versions, "get", side_effect=lambda ref: tampered if ref == after["versionRef"] else original_get(ref)):
            with self.assertRaisesRegex(ValueError, "destinations differ"):
                self.apply()
        (Path(after["snapshotPath"]) / after["entryPath"]).write_text("changed after evaluation")
        with self.assertRaisesRegex(ValueError, "snapshot has changed"):
            self.apply()
        self.assertEqual(self.target.read_text(), "Original skill\n")

    def test_destination_drift_fails_before_mutation_and_failed_retry_is_read_only(self):
        self.target.write_text("User edit after comparison\n")
        result = self.apply()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["receipt"]["details"]["phase"], "preparation")
        self.target.write_text("Original skill\n")
        replay = self.apply()
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["status"], "failed")
        self.assertEqual(self.target.read_text(), "Original skill\n")

    def test_symlink_destination_is_not_followed(self):
        original = self.root / "untouched.md"
        original.write_text("Original skill\n")
        self.target.unlink()
        self.target.symlink_to(original)
        result = self.apply()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(original.read_text(), "Original skill\n")

    def test_application_request_cannot_be_reused_for_another_action(self):
        self.apply()
        with self.assertRaisesRegex(ValueError, "different input"):
            self.apply(action="replace")

    def test_begin_is_durable_before_file_effect_and_concurrent_same_request_applies_once(self):
        entered, resume = threading.Event(), threading.Event()
        original_apply = self.versions.apply_file
        calls = []

        def delayed(before, after):
            with sqlite_connection(self.versions.db_path) as conn:
                rows = conn.execute("SELECT status FROM trace_optimization_application_receipts").fetchall()
            self.assertEqual(rows, [("applying",)])
            calls.append(True)
            entered.set()
            self.assertTrue(resume.wait(10))
            return original_apply(before, after)

        with patch.object(self.versions, "apply_file", side_effect=delayed), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.apply)
            self.assertTrue(entered.wait(10))
            duplicate = self.apply()
            self.assertEqual(duplicate["status"], "applying")
            self.assertTrue(duplicate["requiresReconciliation"])
            self.assertTrue(duplicate["replayed"])
            self.assertIsNone(duplicate["application"])
            with self.assertRaisesRegex(ValueError, "unresolved"):
                self.apply(client_request_id="request:two")
            resume.set()
            self.assertEqual(first.result(10)["status"], "applied")
        self.assertEqual(len(calls), 1)

    def test_successful_file_effect_with_lost_settlement_is_not_replayed(self):
        with patch.object(self.versions, "finish_application", side_effect=sqlite3.OperationalError("receipt disk unavailable")):
            with self.assertRaises(sqlite3.OperationalError):
                self.apply()
        self.assertEqual(self.target.read_text(), "Candidate skill with bounded retry\n")
        with patch.object(self.versions, "apply_file", side_effect=AssertionError("must not retry")):
            replay = self.apply()
        self.assertEqual(replay["status"], "applying")
        self.assertTrue(replay["requiresReconciliation"])

    def test_package_install_uses_real_extension_service_native_package_gate_and_bound_receipt(self):
        baseline, draft = self.package_candidate()
        after = self.versions.get(self.candidate["candidateVersionRef"])
        result = self.apply(action="install")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.runtime.calls[0], ("prepare", after["snapshotPath"]))
        self.assertFalse(any(call[0] == "validate" for call in self.runtime.calls))
        installed = next(call[1] for call in self.runtime.calls if call[0] == "install")
        self.assertNotIn("sourcePath", installed)
        self.assertTrue(installed["preparedPackageId"])
        self.assertEqual(installed["confirmText"], "apply")
        self.assertEqual(result["receipt"]["details"]["installedVersion"], "2.0.0")
        self.assertEqual(result["receipt"]["details"]["installedDigest"], self.runtime.package_digest(draft))
        self.assertNotEqual(result["receipt"]["candidateContentSha256"], result["receipt"]["details"]["installedDigest"])
        self.assertEqual(json.loads((baseline / "package.json").read_text())["version"], "1.0.0")
        before_count = len(self.runtime.calls)
        self.assertTrue(self.apply(action="install")["replayed"])
        self.assertEqual(len(self.runtime.calls), before_count)

    def test_package_replace_checks_parent_identity_and_uses_update(self):
        self.package_candidate(installed=True)
        result = self.apply(action="replace")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["receipt"]["details"]["ownerAction"], "update")
        self.assertEqual(result["receipt"]["details"]["installedVersion"], "2.0.0")
        self.assertEqual(sum(call[0] == "prepare" for call in self.runtime.calls), 2)

    def test_package_parent_drift_fails_without_installation(self):
        self.package_candidate(installed=True)
        self.runtime.installed[0]["digest"] = "other-owner-version"
        result = self.apply(action="replace")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(any(call[0] == "install" for call in self.runtime.calls))

    def test_package_install_does_not_silently_replace_an_installed_identity(self):
        self.package_candidate(installed=True)
        result = self.apply(action="install")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(any(call[0] == "install" for call in self.runtime.calls))

    def test_uncertain_package_owner_exception_retains_interrupted_and_never_replays(self):
        self.package_candidate()
        self.runtime.failure = TimeoutError("owner response timed out")
        result = self.apply(action="install")
        self.assertEqual(result["status"], "interrupted")
        self.assertTrue(result["requiresReconciliation"])
        self.assertEqual(result["application"]["status"], "interrupted")
        self.runtime.failure = None
        again = self.apply(action="install")
        self.assertTrue(again["replayed"])
        self.assertEqual(sum(call[0] == "install" for call in self.runtime.calls), 1)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.apply(action="install", client_request_id="different-request")

    def test_owner_receipt_version_drift_is_uncertain_not_false_success(self):
        self.package_candidate()
        self.runtime.receipt_drift = True
        result = self.apply(action="install")
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["receipt"]["details"]["reasonCode"], "ValueError")

    def test_side_effect_runs_only_after_persisted_reservation_for_package_too(self):
        self.package_candidate()

        def assert_reservation():
            with sqlite_connection(self.versions.db_path) as conn:
                row = conn.execute("SELECT payload_json FROM trace_optimization_application_receipts").fetchone()
            receipt = json.loads(row[0])
            self.assertEqual(receipt["status"], "applying")
            self.assertEqual(receipt["candidateId"], self.candidate["candidateId"])
            self.assertEqual(receipt["versionRef"], self.candidate["candidateVersionRef"])
        self.runtime.on_install = assert_reservation
        self.assertEqual(self.apply(action="install")["status"], "applied")

    def test_database_reservation_rejects_two_different_requests_for_same_candidate(self):
        request = {"candidateId": self.candidate["candidateId"], "reportId": self.candidate["reportId"],
            "versionRef": self.candidate["candidateVersionRef"], "action": "apply"}
        barrier = threading.Barrier(2)

        def reserve(key):
            barrier.wait(10)
            try:
                return self.versions.begin_application(key, request)
            except ValueError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(reserve, ["first-click", "second-click"]))
        self.assertEqual(sum(isinstance(item, tuple) for item in replies), 1)
        self.assertEqual(sum(isinstance(item, str) for item in replies), 1)
        with sqlite_connection(self.versions.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM trace_optimization_application_receipts").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
