from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.room_runtime_host_kill_gate import _process_identity

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix" and Path("/bin/zsh").is_file(), "requires POSIX and zsh")
class WorkspaceProcessFaultTests(unittest.TestCase):
    """Real processes, no Provider and no access outside the test's files."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-process-fault-")
        self.root = Path(self.temporary.name).resolve()
        self.harness = WorkspaceHarness()
        self.session = {
            "id": "process-fault-session",
            "mode": "coordinator",
            "executionMode": "full_trust",
            "toolProfileVersion": "control-center-auto-approve-v1",
            "workspaceRoots": [str(self.root), "/"],
        }

    def tearDown(self) -> None:
        identity_path = self.root / "child.json"
        if identity_path.exists():
            identity = json.loads(identity_path.read_text())
            try:
                if (
                    identity["pgid"] != os.getpgrp()
                    and _process_identity(identity["pid"]) == (
                        identity["pgid"], identity["birth"],
                    )
                ):
                    os.kill(identity["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.temporary.cleanup()

    def _prepared(self):
        child_code = "\n".join(
            [
                "import json, os, pathlib, signal, sys, time",
                f"sys.path.insert(0, {str(REPO)!r})",
                "from rag_ime.room_runtime_host_kill_gate import _process_identity",
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                "pgid, birth = _process_identity(os.getpid())",
                "pathlib.Path('child.json').write_text(json.dumps({'pid': os.getpid(), 'pgid': pgid, 'birth': birth}))",
                "deadline = time.monotonic() + 6",
                "while not pathlib.Path('release').exists() and time.monotonic() < deadline:",
                "    time.sleep(0.01)",
                "if pathlib.Path('release').exists():",
                "    pathlib.Path('late.txt').write_text('late side effect')",
            ]
        )
        parent_code = (
            "import subprocess, sys; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]).wait()"
        )
        return self.harness.prepare_command(
            self.session,
            {
                "command": shlex.join([sys.executable, "-c", parent_code]),
                "cwd": str(self.root),
                "timeoutSeconds": 1,
            },
        )

    def _assert_no_late_effect(self) -> None:
        self.assertTrue((self.root / "child.json").exists(), "fixture child never became ready")
        (self.root / "release").touch()
        deadline = time.monotonic() + 0.35
        while time.monotonic() < deadline and not (self.root / "late.txt").exists():
            time.sleep(0.01)
        self.assertFalse(
            (self.root / "late.txt").exists(),
            "the group leader exited but its SIGTERM-resistant child still wrote",
        )
        identity = json.loads((self.root / "child.json").read_text())
        observed = _process_identity(identity["pid"])
        if observed == (identity["pgid"], identity["birth"]):
            state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(identity["pid"])],
                capture_output=True, text=True, timeout=1,
            ).stdout.strip()
            self.assertTrue(not state or state.startswith("Z"), f"child still alive: {state}")

    def test_reaped_handle_never_signals_a_potentially_reused_process_group(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        process.wait(timeout=3)
        with patch("rag_ime.agent_workspace.os.killpg") as killpg:
            self.harness._terminate_group(process)
        killpg.assert_not_called()

    @unittest.skipUnless(sys.platform == "darwin", "Darwin waitid compatibility")
    def test_native_observation_without_python_waitid_keeps_child_waitable(self) -> None:
        from rag_ime.agent_workspace import _child_exit_observed_without_reaping

        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                                   start_new_session=True)
        try:
            with patch("rag_ime.agent_workspace.os.waitid", None, create=True):
                self.assertFalse(_child_exit_observed_without_reaping(process.pid))
                os.killpg(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + 3
                while not _child_exit_observed_without_reaping(process.pid):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                self.assertIsNone(process.returncode)
                self.assertTrue(_child_exit_observed_without_reaping(process.pid))
                self.assertEqual(process.wait(timeout=2), -signal.SIGTERM)
                with self.assertRaises(ChildProcessError):
                    _child_exit_observed_without_reaping(process.pid)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)

    def test_timeout_reaps_descendant_even_when_group_leader_exits_on_term(self) -> None:
        prepared = self._prepared()
        self.assertTrue(prepared.unrestricted)
        self.assertTrue(prepared.allow_network)
        receipt = self.harness.execute(prepared)
        self.assertTrue(receipt["timedOut"])
        self._assert_no_late_effect()

    def test_explicit_termination_reaps_sigterm_resistant_descendant(self) -> None:
        launched = self.harness.spawn_background(self._prepared())
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not (self.root / "child.json").exists():
                time.sleep(0.01)
            self.assertTrue((self.root / "child.json").exists())
            self.harness.terminate_background(launched)
            launched.process.wait(timeout=2)
            self._assert_no_late_effect()
        finally:
            self.harness.terminate_background(launched)
            if launched.process.stdout is not None:
                launched.process.stdout.close()
            launched.cleanup()


if __name__ == "__main__":
    unittest.main()
