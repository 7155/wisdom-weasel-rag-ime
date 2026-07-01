from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class WaitSquirrelScriptsTests(unittest.TestCase):
    def test_open_settings_helper_skips_open_when_source_is_already_added(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-open-source-added-") as tmp:
            tmp_path = Path(tmp)
            check_script = tmp_path / "check-input-source.sh"
            open_script = tmp_path / "open-should-not-run.sh"
            open_log = tmp_path / "open.log"
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
            open_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo unexpected > {open_log}",
                        "exit 7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)
            open_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "open_squirrel_input_source_settings.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_OPEN_COMMAND": str(open_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("already fully added", result.stdout)
        self.assertFalse(open_log.exists())

    def test_open_settings_helper_opens_keyboard_settings_when_source_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-open-source-missing-") as tmp:
            tmp_path = Path(tmp)
            check_script = tmp_path / "check-input-source.sh"
            open_script = tmp_path / "fake-open.sh"
            open_log = tmp_path / "open.log"
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
            open_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"printf '%s\\n' \"$1\" > {open_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)
            open_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "open_squirrel_input_source_settings.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_OPEN_COMMAND": str(open_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            opened_url = open_log.read_text(encoding="utf-8").strip()

        self.assertIn("Manual Add flow", result.stdout)
        self.assertIn("scripts/wait_squirrel_input_source_added.sh", result.stdout)
        self.assertEqual(opened_url, "x-apple.systempreferences:com.apple.Keyboard-Settings.extension")

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

    def test_wait_input_source_added_timeout_points_to_settings_helper(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wait-source-timeout-") as tmp:
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
                ["bash", str(root / "scripts" / "wait_squirrel_input_source_added.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_INPUT_SOURCE_ADDED_TIMEOUT_SECONDS": "1",
                    "RAG_IME_INPUT_SOURCE_ADDED_POLL_SECONDS": "1",
                },
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("thirdPartyEnabled=false", result.stderr)
        self.assertIn("open_squirrel_input_source_settings.sh --wait", result.stderr)

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
        self.assertIn("open_squirrel_input_source_settings.sh --wait", result.stderr)
        self.assertIn("wait_squirrel_input_source_added.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
