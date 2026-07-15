from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.public_release import (
    RELEASE_MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    audit_public_release,
    audit_release_manifest,
)


class PublicReleaseAuditTests(unittest.TestCase):
    def test_clean_public_tree_with_verified_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            self._write_valid_manifest(root)

            report = audit_public_release(root, tracked_files=tracked, dirty=False)

        self.assertEqual(report["schemaVersion"], SCHEMA_VERSION)
        self.assertTrue(report["ok"])
        self.assertEqual(report["releaseManifest"]["status"], "valid")
        self.assertEqual(report["blockers"], [])

    def test_ready_status_cannot_bypass_missing_release_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)

            report = audit_public_release(root, tracked_files=tracked, dirty=False)

        blocker_ids = {item["id"] for item in report["blockers"]}
        self.assertFalse(report["ok"])
        self.assertIn("release_manifest_missing", blocker_ids)
        self.assertEqual(report["releaseManifest"]["status"], "missing")

    def test_tampered_artifact_and_missing_evidence_block_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            manifest_path = self._write_valid_manifest(root)
            package_path = root / "output" / "release" / "RAG-IME-test.dmg"
            package_path.write_bytes(b"tampered package")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            del payload["evidence"]["notarization"]
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            report = audit_public_release(root, tracked_files=tracked, dirty=False)

        self.assertFalse(report["ok"])
        manifest_issues = report["releaseManifest"]["issues"]
        issue_ids = {item["id"] for item in manifest_issues}
        self.assertIn("artifact_sha256_mismatch", issue_ids)
        self.assertIn("artifact_size_mismatch", issue_ids)
        self.assertIn("evidence_artifact_sha256_mismatch", issue_ids)
        self.assertIn("required_evidence_missing", issue_ids)
        self.assertIn("release_manifest_invalid", {item["id"] for item in report["blockers"]})

    def test_manifest_rejects_path_escape_and_unverified_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            self._write_public_metadata(root, ready=True, include_license=True)
            manifest_path = self._write_valid_manifest(root)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["evidence"]["codesign"]["result"] = "claimed"
            payload["evidence"]["codesign"]["path"] = "../outside.txt"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            manifest = audit_release_manifest(root)

        issue_ids = {item["id"] for item in manifest["issues"]}
        self.assertEqual(manifest["status"], "invalid")
        self.assertIn("release_path_outside_root", issue_ids)
        self.assertIn("evidence_result_invalid", issue_ids)

    def test_manifest_requires_project_license_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            manifest_path = self._write_valid_manifest(root)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            del payload["evidence"]["projectLicense"]
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            report = audit_public_release(root, tracked_files=tracked, dirty=False)

        issue_ids = {item["id"] for item in report["releaseManifest"]["issues"]}
        self.assertIn("required_evidence_missing", issue_ids)

    def test_generated_artifacts_license_and_secret_shapes_block_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = list(self._write_public_metadata(root, ready=True, include_license=False))
            (root / "README.md").write_text(
                "Bearer abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8"  # public-audit-secret-fixture
            )
            quarantine = root / "dataset" / "quarantine"
            quarantine.mkdir(parents=True)
            (quarantine / "generated.jsonl").write_text("{}\n", encoding="utf-8")
            obsolete_generator = root / "scripts" / "quarantine" / "generate_old_data.py"
            obsolete_generator.parent.mkdir(parents=True)
            obsolete_generator.write_text("print('old')\n", encoding="utf-8")
            archived_agent_log = root / "docs" / "archive" / "20260705-doc-cleanup" / "agent" / "notes.md"
            archived_agent_log.parent.mkdir(parents=True)
            archived_agent_log.write_text("old machine log\n", encoding="utf-8")
            obsolete_plan = root / "docs" / "codex_next_step_stability_ui_plan.md"
            obsolete_plan.write_text("superseded execution plan\n", encoding="utf-8")
            obsolete_reset_audit = root / "docs" / "agent" / "requirements-reset-audit-20260707.md"
            obsolete_reset_audit.parent.mkdir(parents=True, exist_ok=True)
            obsolete_reset_audit.write_text("superseded product audit\n", encoding="utf-8")
            handoff = root / "docs" / "agent" / "rag-ime-v1-reset-handoff-2026-07-07.txt"
            handoff.parent.mkdir(parents=True, exist_ok=True)
            handoff.write_text("internal handoff\n", encoding="utf-8")
            tracked.extend(
                (
                    "dataset/quarantine/generated.jsonl",
                    "scripts/quarantine/generate_old_data.py",
                    "docs/archive/20260705-doc-cleanup/agent/notes.md",
                    "docs/codex_next_step_stability_ui_plan.md",
                    "docs/agent/requirements-reset-audit-20260707.md",
                    "docs/agent/rag-ime-v1-reset-handoff-2026-07-07.txt",
                )
            )

            report = audit_public_release(root, tracked_files=tracked, dirty=True)

        blocker_ids = {item["id"] for item in report["blockers"]}
        self.assertFalse(report["ok"])
        self.assertIn("top_level_license_missing", blocker_ids)
        self.assertIn("forbidden_tracked_artifacts", blocker_ids)
        self.assertIn("scripts/quarantine/generate_old_data.py", report["forbiddenTracked"])
        self.assertIn("docs/archive/20260705-doc-cleanup/agent/notes.md", report["forbiddenTracked"])
        self.assertIn("docs/codex_next_step_stability_ui_plan.md", report["forbiddenTracked"])
        self.assertIn("docs/agent/requirements-reset-audit-20260707.md", report["forbiddenTracked"])
        self.assertIn("docs/agent/rag-ime-v1-reset-handoff-2026-07-07.txt", report["forbiddenTracked"])
        self.assertIn("possible_secret_shapes", blocker_ids)
        self.assertIn("working_tree_dirty", blocker_ids)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", str(report["secretShapeHits"]))

    def test_untracked_candidate_artifact_and_machine_path_are_scanned_before_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            self._write_valid_manifest(root)
            generated = root / "output" / "private.log"
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text("local output\n", encoding="utf-8")
            script = root / "scripts" / "local-default.sh"
            script.parent.mkdir(parents=True)
            script.write_text('MODEL="/Volumes/private-disk/models/current"\n', encoding="utf-8")

            report = audit_public_release(
                root,
                tracked_files=tracked,
                candidate_files=(*tracked, "output/private.log", "scripts/local-default.sh"),
                dirty=False,
            )

        blocker_ids = {item["id"] for item in report["blockers"]}
        self.assertFalse(report["ok"])
        self.assertEqual(report["untrackedCandidateCount"], 2)
        self.assertIn("output/private.log", report["forbiddenCandidates"])
        self.assertIn("forbidden_candidate_artifacts", blocker_ids)
        self.assertIn("machine_specific_paths", blocker_ids)
        self.assertEqual(report["machinePathHits"][0]["path"], "scripts/local-default.sh")
        self.assertNotIn("private-disk", str(report["machinePathHits"]))

    def test_machine_path_scan_ignores_explicit_test_fixtures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            self._write_valid_manifest(root)
            fixture = root / "tests" / "test_redaction.py"
            fixture.parent.mkdir()
            fixture.write_text('value = "/Users/private/redact-me"\n', encoding="utf-8")

            report = audit_public_release(
                root,
                tracked_files=tracked,
                candidate_files=(*tracked, "tests/test_redaction.py"),
                dirty=False,
            )

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["machinePathHits"], [])

    def test_legacy_browser_control_surface_cannot_reenter_candidate_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            self._write_valid_manifest(root)
            browser = root / "debug" / "index.html"
            browser.parent.mkdir()
            browser.write_text("<title>Second control center</title>\n", encoding="utf-8")

            report = audit_public_release(
                root,
                tracked_files=tracked,
                candidate_files=(*tracked, "debug/index.html"),
                dirty=False,
            )

        self.assertFalse(report["ok"])
        self.assertIn("debug/index.html", report["forbiddenCandidates"])
        self.assertIn("forbidden_candidate_artifacts", {item["id"] for item in report["blockers"]})

    def test_removed_native_harness_cannot_reenter_candidate_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=True, include_license=True)
            self._write_valid_manifest(root)
            harness = root / "macos" / "RagImeMac" / "Info.plist"
            harness.parent.mkdir(parents=True)
            harness.write_text("legacy harness\n", encoding="utf-8")
            installer = root / "scripts" / "install_macos_frontend.sh"
            installer.parent.mkdir(parents=True)
            installer.write_text("#!/bin/sh\n", encoding="utf-8")

            report = audit_public_release(
                root,
                tracked_files=tracked,
                candidate_files=(*tracked, "macos/RagImeMac/Info.plist", "scripts/install_macos_frontend.sh"),
                dirty=False,
            )

        self.assertFalse(report["ok"])
        self.assertIn("macos/RagImeMac/Info.plist", report["forbiddenCandidates"])
        self.assertIn("scripts/install_macos_frontend.sh", report["forbiddenCandidates"])

    def test_foreground_and_declared_status_remain_release_blockers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-public-release-") as tmp:
            root = Path(tmp)
            tracked = self._write_public_metadata(root, ready=False, include_license=True)
            self._write_valid_manifest(root)

            report = audit_public_release(root, tracked_files=tracked, dirty=False)

        blocker_ids = {item["id"] for item in report["blockers"]}
        self.assertIn("foreground_acceptance_pending", blocker_ids)
        self.assertIn("release_status_declared_blocked", blocker_ids)
        self.assertNotIn("release_manifest_missing", blocker_ids)

    @staticmethod
    def _write_public_metadata(root: Path, *, ready: bool, include_license: bool) -> tuple[str, ...]:
        for name in ("README.md", "THIRD_PARTY_NOTICES.md", "pyproject.toml"):
            (root / name).write_text("public metadata\n", encoding="utf-8")
        if include_license:
            (root / "LICENSE").write_text("test license\n", encoding="utf-8")
        release = root / "release"
        release.mkdir()
        (release / "feature-registry.json").write_text("[]\n", encoding="utf-8")
        (release / "release-manifest.example.json").write_text("{}\n", encoding="utf-8")
        (release / "product-status.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.product-status.v1",
                    "productStatus": "foreground_verified" if ready else "backend_only",
                    "releaseStatus": "ready" if ready else "blocked",
                    "foregroundEvidence": {
                        "strictSoakPassed": ready,
                        "releaseSignedAndNotarized": ready,
                    },
                }
            ),
            encoding="utf-8",
        )
        tracked = [
            "README.md",
            "THIRD_PARTY_NOTICES.md",
            "pyproject.toml",
            "release/feature-registry.json",
            "release/product-status.json",
            "release/release-manifest.example.json",
        ]
        if include_license:
            tracked.append("LICENSE")
        return tuple(tracked)

    @classmethod
    def _write_valid_manifest(cls, root: Path) -> Path:
        release = root / "output" / "release"
        evidence_dir = release / "evidence"
        evidence_dir.mkdir(parents=True)
        package = release / "RAG-IME-test.dmg"
        source = release / "RAG-IME-test-squirrel-source.tar.gz"
        package.write_bytes(b"signed macOS package")
        source.write_bytes(b"patched Squirrel corresponding source")

        evidence_files = {
            "codesign": ("valid", "macos-package", "codesign.txt", b"codesign --verify: valid"),
            "notarization": ("accepted", "macos-package", "notarization.json", b'{"status":"Accepted"}'),
            "stapling": ("valid", "macos-package", "stapler.txt", b"stapler validate: valid"),
            "correspondingSource": (
                "verified",
                "patched-squirrel-source",
                "corresponding-source.txt",
                b"source archive and build instructions verified",
            ),
            "foregroundAcceptance": (
                "passed",
                "macos-package",
                "foreground-acceptance.json",
                b'{"strictSoak":"passed"}',
            ),
        }
        evidence: dict[str, dict[str, object]] = {}
        for evidence_id, (result, artifact_id, filename, content) in evidence_files.items():
            path = evidence_dir / filename
            path.write_bytes(content)
            artifact_path = package if artifact_id == "macos-package" else source
            evidence[evidence_id] = {
                "result": result,
                "artifactId": artifact_id,
                "artifactSha256": cls._sha256(artifact_path),
                "path": str(path.relative_to(root)),
                "sha256": cls._sha256(path),
            }
        notices = root / "THIRD_PARTY_NOTICES.md"
        license_file = root / "LICENSE"
        evidence["projectLicense"] = {
            "result": "verified",
            "path": "LICENSE",
            "sha256": cls._sha256(license_file),
        }
        evidence["thirdPartyNotices"] = {
            "result": "verified",
            "path": "THIRD_PARTY_NOTICES.md",
            "sha256": cls._sha256(notices),
        }
        payload = {
            "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
            "releaseId": "v0.1.0-test",
            "sourceCommit": "a" * 40,
            "artifacts": [
                {
                    "id": "macos-package",
                    "kind": "macos_release",
                    "path": str(package.relative_to(root)),
                    "sha256": cls._sha256(package),
                    "sizeBytes": package.stat().st_size,
                },
                {
                    "id": "patched-squirrel-source",
                    "kind": "corresponding_source",
                    "path": str(source.relative_to(root)),
                    "sha256": cls._sha256(source),
                    "sizeBytes": source.stat().st_size,
                },
            ],
            "evidence": evidence,
        }
        manifest = release / "release-manifest.json"
        manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return manifest

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
