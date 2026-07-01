from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class WaitSquirrelScriptsTests(unittest.TestCase):
    def test_wait_input_source_added_succeeds_when_strict_check_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wait-source-") as tmp:
            check_script = Path(tmp) / "check-input-source.sh"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=true thirdPartyEnabled=true'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "wait_squirrel_input_source_added.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_INPUT_SOURCE_ADDED_TIMEOUT_SECONDS": "1",
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("input-source-added:", result.stdout)
        self.assertIn("thirdPartyEnabled=true", result.stdout)

    def test_wait_typing_ready_fails_fast_when_squirrel_is_not_fully_added(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wait-typing-") as tmp:
            check_script = Path(tmp) / "check-input-source.sh"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false thirdPartyEnabled=false'",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "wait_squirrel_typing_ready.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_TYPING_READY_TIMEOUT_SECONDS": "1",
                },
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("not fully added", result.stderr)
        self.assertIn("thirdPartyEnabled=false", result.stderr)
        self.assertIn("wait_squirrel_input_source_added.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
