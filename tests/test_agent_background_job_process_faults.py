from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.room_runtime_host_kill_gate import _process_identity


REPO = Path(__file__).resolve().parents[1]
HOST = r"""
import json, pathlib, shlex, sys, time
from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_workspace import WorkspaceHarness
root = pathlib.Path(sys.argv[1])
session_id = sys.argv[2]
sessions = AgentSessionStore(root / 'jobs.sqlite')
harness = WorkspaceHarness()
service = AgentBackgroundJobService(root / 'jobs.sqlite', events=lambda *a, **k: None, workspace_harness=harness)
service.initialize()
code = '''import pathlib, time
with pathlib.Path('effects.txt').open('a') as output:
    output.write('effect\\n')
pathlib.Path('worker-ready').touch()
deadline = time.monotonic() + 8
while not pathlib.Path('release').exists() and time.monotonic() < deadline:
    time.sleep(0.01)
print('worker finished', flush=True)
'''
prepared = harness.prepare_background_command(sessions.get(session_id), {
    'command': shlex.join([sys.executable, '-c', code]),
    'cwd': str(root), 'timeoutSeconds': 15,
})
receipt = service.start(session_id, prepared)
(root / 'job.json').write_text(json.dumps(receipt['job']))
try:
    time.sleep(20)
finally:
    service.close()
"""


@unittest.skipUnless(os.name == "posix" and Path("/bin/zsh").is_file(), "requires POSIX and zsh")
class BackgroundWorkerProcessFaultTests(unittest.TestCase):
    """Kill only this test's host/worker; retain the product's real job owner."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-background-fault-")
        self.root = Path(self.temporary.name).resolve()
        sessions = AgentSessionStore(self.root / "jobs.sqlite")
        sessions.initialize()
        self.session = sessions.create(
            title="isolated process fault fixture",
            mode="coordinator",
            tool_profile_version="control-center-auto-approve-v1",
            execution_mode="full_trust",
            workspace_roots=[str(self.root), "/"],
        )
        self.host = None
        self.owner = None
        self.worker_identity = None
        self.worker_pid = 0

    def tearDown(self) -> None:
        (self.root / "release").touch()
        if self.host is not None and self.host.poll() is None:
            self.host.kill()
            self.host.wait(timeout=3)
        if self.worker_identity is not None:
            observed = _process_identity(self.worker_pid)
            if observed == self.worker_identity and observed[0] != os.getpgrp():
                try:
                    os.killpg(observed[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.owner is not None:
            self.owner.close()
        self.temporary.cleanup()

    def _start(self):
        with (self.root / "host.log").open("wb") as output:
            self.host = subprocess.Popen(
                [sys.executable, "-c", HOST, str(self.root), str(self.session["id"])],
                cwd=REPO,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 5
        job = None
        while time.monotonic() < deadline:
            if (self.root / "job.json").exists() and (self.root / "worker-ready").exists():
                try:
                    job = json.loads((self.root / "job.json").read_text())
                    break
                except json.JSONDecodeError:
                    pass
            if self.host.poll() is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(job, (self.root / "host.log").read_text())
        self.worker_pid = int(job["pid"])
        self.worker_identity = _process_identity(self.worker_pid)
        self.assertIsNotNone(self.worker_identity)
        self.assertNotEqual(self.worker_identity[0], os.getpgrp())
        self.assertTrue(job["networkAllowed"])
        return job

    def _reopen(self):
        self.owner = AgentBackgroundJobService(
            self.root / "jobs.sqlite", events=lambda *args, **kwargs: None
        )
        self.owner.initialize()

    def _terminal(self, job_id):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            job = self.owner.status(str(self.session["id"]), job_id)["job"]
            if job["status"] not in {"queued", "running", "cancelling"}:
                return job
            time.sleep(0.02)
        self.fail(f"job did not settle: {job}")

    def test_sigkill_host_reattaches_same_worker_without_repeating_effect(self) -> None:
        original = self._start()
        self.host.kill()
        self.host.wait(timeout=3)
        self._reopen()
        recovered = self.owner.status(str(self.session["id"]), original["jobId"])["job"]
        self.assertEqual(recovered["pid"], original["pid"])
        self.assertEqual(recovered["status"], "running")
        (self.root / "release").touch()
        terminal = self._terminal(original["jobId"])
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["pid"], original["pid"])
        self.assertEqual((self.root / "effects.txt").read_text().splitlines(), ["effect"])

    def test_worker_death_without_exit_receipt_is_orphaned_not_reexecuted(self) -> None:
        original = self._start()
        self.host.kill()
        self.host.wait(timeout=3)
        os.killpg(self.worker_identity[0], signal.SIGKILL)
        # Reopen the real service after both processes are gone. Missing exit
        # receipt is uncertainty, not permission to execute the command again.
        deadline = time.monotonic() + 2
        while _process_identity(self.worker_pid) == self.worker_identity and time.monotonic() < deadline:
            time.sleep(0.02)
        self._reopen()
        terminal = self._terminal(original["jobId"])
        self.assertEqual(terminal["status"], "orphaned")
        self.assertEqual((self.root / "effects.txt").read_text().splitlines(), ["effect"])


if __name__ == "__main__":
    unittest.main()
