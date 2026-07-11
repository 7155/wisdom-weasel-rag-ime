from __future__ import annotations

import json
import plistlib
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from rag_ime.release_staging import prepare_release_candidate


class ReleaseStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-release-staging-")
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        (self.root / "README.md").write_text("public source\n", encoding="utf-8")
        (self.root / "module.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)
        self.squirrel = self.root / "squirrel"
        self.squirrel.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.squirrel, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.squirrel, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.squirrel, check=True)
        (self.squirrel / "LICENSE.txt").write_text("GPL fixture\n", encoding="utf-8")
        (self.squirrel / "sources").mkdir()
        (self.squirrel / "sources" / "Main.swift").write_text("// source\n", encoding="utf-8")
        (self.squirrel / "download").mkdir()
        (self.squirrel / "download" / "binary.zip").write_bytes(b"not source")
        subprocess.run(["git", "add", "."], cwd=self.squirrel, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.squirrel, check=True)
        self.apps = {
            "squirrel": self._app("Squirrel.app", "im.rime.inputmethod.Squirrel"),
            "control": self._app("RagImeControl.app", "com.rag-ime.control"),
            "voice": self._app("RagImeVoice.app", "com.rag-ime.voice"),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_staging_is_deterministic_and_cannot_claim_release_ready(self) -> None:
        reports = []
        for name in ("out-a", "out-b"):
            reports.append(
                prepare_release_candidate(
                    self.root,
                    release_id="v0.1.0-rc1",
                    output_root=self.root / name,
                    squirrel_source=self.squirrel,
                    apps=self.apps,
                    project_files=("README.md", "module.py"),
                )
            )

        self.assertFalse(reports[0]["releaseEligible"])
        self.assertEqual(reports[0]["status"], "unsigned_staging_only")
        self.assertNotEqual(reports[0]["schemaVersion"], "rag-ime.release-manifest.v1")
        self.assertEqual(
            [item["sha256"] for item in reports[0]["artifacts"]],
            [item["sha256"] for item in reports[1]["artifacts"]],
        )
        source_archive = Path(reports[0]["artifacts"][0]["path"])
        with tarfile.open(source_archive, "r:gz") as archive:
            names = archive.getnames()
        self.assertIn("patched-squirrel-source/sources/Main.swift", names)
        self.assertNotIn("patched-squirrel-source/download/binary.zip", names)
        self.assertIn("SOURCE-SNAPSHOT.json", names)

    def test_staging_excludes_removed_native_harness_even_if_it_reappears(self) -> None:
        harness = self.root / "macos" / "RagImeMac" / "Info.plist"
        harness.parent.mkdir(parents=True)
        harness.write_text("legacy harness\n", encoding="utf-8")
        installer = self.root / "scripts" / "install_macos_frontend.sh"
        installer.parent.mkdir(parents=True)
        installer.write_text("#!/bin/sh\n", encoding="utf-8")

        report = prepare_release_candidate(
            self.root,
            release_id="no-legacy-harness",
            output_root=self.root / "out-no-legacy",
            squirrel_source=self.squirrel,
            apps=self.apps,
            project_files=(
                "README.md",
                "module.py",
                "macos/RagImeMac/Info.plist",
                "scripts/install_macos_frontend.sh",
            ),
        )

        with tarfile.open(Path(report["artifacts"][0]["path"]), "r:gz") as archive:
            names = archive.getnames()
        self.assertNotIn("rag-ime-project/macos/RagImeMac/Info.plist", names)
        self.assertNotIn("rag-ime-project/scripts/install_macos_frontend.sh", names)

    def test_rejects_unsafe_symlink_in_app_bundle(self) -> None:
        bad = self.apps["voice"] / "Contents" / "escape"
        bad.symlink_to("../../../../outside")

        with self.assertRaisesRegex(ValueError, "unsafe symlink"):
            prepare_release_candidate(
                self.root,
                release_id="rc",
                output_root=self.root / "out",
                squirrel_source=self.squirrel,
                apps=self.apps,
                project_files=("README.md",),
            )

    def _app(self, name: str, bundle_id: str) -> Path:
        app = self.root / "apps" / name
        contents = app / "Contents"
        executable = contents / "MacOS" / name.removesuffix(".app")
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleIdentifier": bundle_id}, handle)
        return app


if __name__ == "__main__":
    unittest.main()
