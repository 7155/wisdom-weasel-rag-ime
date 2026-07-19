from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class RefreshSquirrelInputSourceRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-registration-refresh-")
        self.tmp_path = Path(self.tmp.name)
        self.app = self.tmp_path / "Input Methods" / "Squirrel.app"
        executable = self.app / "Contents" / "MacOS" / "Squirrel"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

        self.ls_log = self.tmp_path / "lsregister.log"
        self.kill_log = self.tmp_path / "killall.log"
        self.check_count = self.tmp_path / "check-count"
        self.check_count.write_text("0\n", encoding="utf-8")

        self.lsregister = self.tmp_path / "lsregister"
        self.lsregister.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    'if [[ "${1:-}" == "-dump" ]]; then exit 0; fi',
                    'printf "%s\\n" "$*" >> "$FAKE_LSREGISTER_LOG"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.lsregister.chmod(0o755)

        self.killall = self.tmp_path / "killall"
        self.killall.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$FAKE_KILLALL_LOG"\n',
            encoding="utf-8",
        )
        self.killall.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _check_script(self, *, missing_once: bool = False, always_missing: bool = False) -> Path:
        script = self.tmp_path / "check-input-source.sh"
        lines = [
            "#!/usr/bin/env bash",
            'count="$(cat "$FAKE_CHECK_COUNT")"',
            'printf "%s\\n" "$((count + 1))" > "$FAKE_CHECK_COUNT"',
        ]
        if always_missing:
            lines.extend(
                [
                    'echo "missing im.rime.inputmethod.Squirrel.Hans" >&2',
                    "exit 2",
                ]
            )
        elif missing_once:
            lines.extend(
                [
                    'if [[ "$count" == "0" ]]; then',
                    '  echo "missing im.rime.inputmethod.Squirrel.Hans" >&2',
                    "  exit 2",
                    "fi",
                ]
            )
        lines.append(
            'echo "id=im.rime.inputmethod.Squirrel.Hans enabled=true selectable=true '
            'selected=false current=com.apple.keylayout.ABC matchCount=1"'
        )
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)
        return script

    def _run(self, check_script: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "HOME": str(self.tmp_path),
            "TMPDIR": str(self.tmp_path),
            "RAG_IME_SQUIRREL_APP": str(self.app),
            "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
            "RAG_IME_LSREGISTER": str(self.lsregister),
            "RAG_IME_KILLALL": str(self.killall),
            "RAG_IME_INPUT_SOURCE_REFRESH_SLEEP_SECONDS": "0",
            "FAKE_LSREGISTER_LOG": str(self.ls_log),
            "FAKE_KILLALL_LOG": str(self.kill_log),
            "FAKE_CHECK_COUNT": str(self.check_count),
            **extra_env,
        }
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "refresh_squirrel_input_source_registration.sh")],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_healthy_refresh_is_idempotent_and_does_not_restart_input_services(self) -> None:
        result = self._run(self._check_script())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already healthy; left macOS input services running", result.stdout)
        self.assertFalse(self.kill_log.exists())
        self.assertFalse(self.ls_log.exists())

    def test_replaced_bundle_refreshes_launchservices_and_only_imklaunchagent(self) -> None:
        result = self._run(
            self._check_script(),
            RAG_IME_SQUIRREL_BUNDLE_REPLACED="1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("restarting imklaunchagent once", result.stdout)
        self.assertIn("healthy with a fresh IMK endpoint broker", result.stdout)
        self.assertEqual(
            self.kill_log.read_text(encoding="utf-8").splitlines(),
            ["imklaunchagent"],
        )
        self.assertIn(f"-f -R -trusted {self.app}", self.ls_log.read_text(encoding="utf-8"))

    def test_missing_source_registers_once_and_restarts_services_once(self) -> None:
        result = self._run(self._check_script(missing_once=True))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.kill_log.read_text(encoding="utf-8").splitlines(),
            ["TextInputMenuAgent TextInputSwitcher imklaunchagent"],
        )
        self.assertEqual(
            self.ls_log.read_text(encoding="utf-8").splitlines(),
            [f"-f -R -trusted {self.app}"],
        )

    def test_persistent_failure_never_restarts_global_input_services_twice(self) -> None:
        result = self._run(self._check_script(always_missing=True))

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            self.kill_log.read_text(encoding="utf-8").splitlines(),
            ["TextInputMenuAgent TextInputSwitcher imklaunchagent"],
        )
        self.assertIn("refusing a second disruptive restart", result.stderr)


if __name__ == "__main__":
    unittest.main()
