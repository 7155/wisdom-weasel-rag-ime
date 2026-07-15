from __future__ import annotations

import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


class CanonicalSquirrelBundleAuditTests(unittest.TestCase):
    def test_duplicate_same_bundle_id_fails(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-canonical-audit-") as tmp:
            base = Path(tmp)
            user_dir = base / "user"
            system_dir = base / "system"
            canonical = _write_app(user_dir / "Squirrel.app", patched=True)
            _write_app(system_dir / "Squirrel.app", patched=False)
            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "audit_canonical_squirrel_bundles.py"),
                    "--canonical-app",
                    str(canonical),
                    "--user-dir",
                    str(user_dir),
                    "--system-dir",
                    str(system_dir),
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["bundleCount"], 2)
        self.assertFalse(report["ok"])

    def test_single_patched_canonical_bundle_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-canonical-audit-") as tmp:
            base = Path(tmp)
            user_dir = base / "user"
            system_dir = base / "system"
            canonical = _write_app(user_dir / "Squirrel.app", patched=True)
            system_dir.mkdir(parents=True)
            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "audit_canonical_squirrel_bundles.py"),
                    "--canonical-app",
                    str(canonical),
                    "--user-dir",
                    str(user_dir),
                    "--system-dir",
                    str(system_dir),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_preinstall_allows_missing_target_but_rejects_other_same_bundle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-canonical-preinstall-") as tmp:
            base = Path(tmp)
            user_dir = base / "user"
            system_dir = base / "system"
            user_dir.mkdir(parents=True)
            system_dir.mkdir(parents=True)
            canonical = user_dir / "Squirrel.app"
            clean = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "audit_canonical_squirrel_bundles.py"),
                    "--preinstall",
                    "--canonical-app",
                    str(canonical),
                    "--user-dir",
                    str(user_dir),
                    "--system-dir",
                    str(system_dir),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            _write_app(system_dir / "Legacy.app", patched=False)
            conflict = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "audit_canonical_squirrel_bundles.py"),
                    "--preinstall",
                    "--canonical-app",
                    str(canonical),
                    "--user-dir",
                    str(user_dir),
                    "--system-dir",
                    str(system_dir),
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertEqual(json.loads(clean.stdout)["mode"], "preinstall")
        self.assertNotEqual(conflict.returncode, 0)
        report = json.loads(conflict.stdout)
        self.assertFalse(report["ok"])
        self.assertIn("preinstall same-bundle conflict", report["errors"][0])
        self.assertIn("[ERROR] preinstall same-bundle conflict", conflict.stderr)


def _write_app(path: Path, *, patched: bool) -> Path:
    executable = path / "Contents" / "MacOS" / "Squirrel"
    executable.parent.mkdir(parents=True)
    payload = {
        "CFBundleIdentifier": "im.rime.inputmethod.Squirrel",
        "TISInputSourceID": "im.rime.inputmethod.Squirrel.Hans",
    }
    (path / "Contents" / "Info.plist").write_bytes(plistlib.dumps(payload))
    markers = "rag-ime.foreground-trace.v2 composition_ai_suppressed foreground_context_capture_resolved" if patched else "old"
    executable.write_text(markers, encoding="utf-8")
    executable.chmod(0o755)
    return path


if __name__ == "__main__":
    unittest.main()
