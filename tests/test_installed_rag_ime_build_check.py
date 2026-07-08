from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstalledRagImeBuildCheckTests(unittest.TestCase):
    def test_checker_reports_installed_latest_from_marker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_sha = _sha256(root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch")
        with tempfile.TemporaryDirectory(prefix="rag-ime-installed-build-") as tmp:
            tmp_path = Path(tmp)
            app = tmp_path / "Squirrel.app"
            marker_path = app / "Contents" / "Resources" / "rag-ime-build-marker.json"
            marker_path.parent.mkdir(parents=True)
            marker_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.squirrel-build-marker.v1",
                        "patchSha256": patch_sha,
                        "bundleId": "im.rime.inputmethod.Squirrel",
                        "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            check_script = _write_fake_check_script(tmp_path)

            result = subprocess.run(
                [
                    str(root / "scripts" / "check_installed_rag_ime_build.py"),
                    "--app",
                    str(app),
                    "--check-script",
                    str(check_script),
                    "--no-process",
                    "--require-latest",
                ],
                cwd=root,
                env={**os.environ},
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(result.stdout)

        self.assertEqual(payload["schemaVersion"], "rag-ime.installed-build-check.v1")
        self.assertTrue(payload["installedLatest"])
        self.assertTrue(payload["selected"])
        self.assertTrue(payload["hitoolboxEnabled"])
        self.assertTrue(payload["thirdPartyEnabled"])
        self.assertEqual(payload["runningProcessCount"], 0)

    def test_checker_fails_require_latest_when_patch_hash_differs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-installed-build-") as tmp:
            tmp_path = Path(tmp)
            app = tmp_path / "Squirrel.app"
            marker_path = app / "Contents" / "Resources" / "rag-ime-build-marker.json"
            marker_path.parent.mkdir(parents=True)
            marker_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.squirrel-build-marker.v1",
                        "patchSha256": "old",
                        "bundleId": "im.rime.inputmethod.Squirrel",
                        "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            check_script = _write_fake_check_script(tmp_path)

            result = subprocess.run(
                [
                    str(root / "scripts" / "check_installed_rag_ime_build.py"),
                    "--app",
                    str(app),
                    "--check-script",
                    str(check_script),
                    "--no-process",
                    "--require-latest",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )
            payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["installedLatest"])
        self.assertEqual(payload["markerPatchSha256"], "old")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fake_check_script(tmp_path: Path) -> Path:
    script = tmp_path / "check-input-source.sh"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "report=''",
                "while [[ \"${1:-}\" == --* ]]; do",
                "  case \"$1\" in",
                "    --report-path) report=\"$2\"; shift 2 ;;",
                "    --report-path=*) report=\"${1#--report-path=}\"; shift ;;",
                "    *) shift ;;",
                "  esac",
                "done",
                "target=\"${1:-im.rime.inputmethod.Squirrel.Hans}\"",
                "cat > \"$report\" <<JSON",
                "{\"ok\":true,\"source\":{\"selected\":true,\"hitoolboxEnabled\":true,\"thirdPartyEnabled\":true},\"inputSourceId\":\"$target\"}",
                "JSON",
                "echo \"id=$target selected=true hitoolboxEnabled=true thirdPartyEnabled=true\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


if __name__ == "__main__":
    unittest.main()
