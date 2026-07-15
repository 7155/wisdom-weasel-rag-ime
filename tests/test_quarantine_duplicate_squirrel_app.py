from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


class QuarantineDuplicateSquirrelAppTests(unittest.TestCase):
    def test_preflight_reports_same_bundle_duplicate_without_modifying_it(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-quarantine-") as tmp:
            base = Path(tmp)
            canonical = _write_app(base / "user/Squirrel.app", patched=True)
            duplicate = _write_app(base / "system/Squirrel.app", patched=False)
            result = subprocess.run(
                ["bash", str(root / "scripts/quarantine_duplicate_squirrel_app.sh"), "--preflight"],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_APP": str(canonical),
                    "RAG_IME_SQUIRREL_SYSTEM_APP": str(duplicate),
                },
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertTrue(duplicate.is_dir())

        self.assertIn("canonical_patch=true", result.stdout)
        self.assertIn("duplicate_exists=true", result.stdout)
        self.assertIn("same_bundle_id=true", result.stdout)


def _write_app(path: Path, *, patched: bool) -> Path:
    executable = path / "Contents/MacOS/Squirrel"
    executable.parent.mkdir(parents=True)
    (path / "Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleIdentifier": "im.rime.inputmethod.Squirrel"})
    )
    markers = (
        "rag-ime.foreground-trace.v2 composition_ai_suppressed foreground_context_capture_resolved"
        if patched
        else "old"
    )
    executable.write_text(markers, encoding="utf-8")
    executable.chmod(0o755)
    return path


if __name__ == "__main__":
    unittest.main()
