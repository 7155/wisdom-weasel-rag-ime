from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.room_runtime_host_kill_gate import _process_identity


ROOT = Path(__file__).resolve().parents[1]
HOST = r'''
import json, pathlib, shlex, sqlite3, sys, time
from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.room_runtime_host_kill_gate import _process_identity
root = pathlib.Path(sys.argv[1])
session_id, phase = sys.argv[2:4]

def pause(pid):
    (root / 'fault-ready').write_text(json.dumps({'pid': pid, 'identity': _process_identity(pid)}))
    time.sleep(30)

class Harness(WorkspaceHarness):
    def spawn_background(self, prepared, **kwargs):
        launched = super().spawn_background(prepared, **kwargs)
        if phase == 'before_identity_commit':
            pause(launched.process.pid)
        return launched

sessions = AgentSessionStore(root / 'jobs.sqlite')
service = AgentBackgroundJobService(root / 'jobs.sqlite', events=lambda *a, **k: None, workspace_harness=Harness())
service.initialize()
if phase == 'after_identity_commit':
    release = service._release_launch
    def pause_release(job_id):
        row = service._row_for_job(job_id)
        pause(int(row['pid']))
        release(job_id)
    service._release_launch = pause_release
code = "from pathlib import Path; Path('effects.txt').open('a').write('effect\\n')"
prepared = service.workspace_harness.prepare_background_command(sessions.get(session_id), {
    'command': shlex.join([sys.executable, '-c', code]), 'cwd': str(root), 'timeoutSeconds': 10,
})
service.start(session_id, prepared, idempotency_key='crashed-launch')
time.sleep(30)
'''


@unittest.skipUnless(os.name == "posix" and Path("/bin/zsh").is_file(), "requires POSIX and zsh")
class BackgroundLaunchRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-launch-recovery-")
        self.root = Path(self.temporary.name).resolve()
        self.db = self.root / "jobs.sqlite"
        sessions = AgentSessionStore(self.db)
        sessions.initialize()
        self.session = sessions.create(
            title="startup recovery fixture", mode="coordinator",
            execution_mode="full_trust", tool_profile_version="control-center-auto-approve-v1",
            workspace_roots=[str(self.root), "/"],
        )
        self.host = None
        self.owner = None
        self.identity = None
        self.pid = 0

    def tearDown(self) -> None:
        if self.host is not None and self.host.poll() is None:
            self.host.kill()
            self.host.wait(timeout=3)
        if self.identity and _process_identity(self.pid) == self.identity:
            if self.identity[0] != os.getpgrp():
                try:
                    os.killpg(self.identity[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.owner is not None:
            self.owner.close()
        self.temporary.cleanup()

    def _crash_at(self, phase: str):
        with (self.root / "host.log").open("wb") as output:
            self.host = subprocess.Popen(
                [sys.executable, "-c", HOST, str(self.root), str(self.session["id"]), phase],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (self.root / "fault-ready").exists():
                try:
                    ready = json.loads((self.root / "fault-ready").read_text())
                    break
                except json.JSONDecodeError:
                    pass
            if self.host.poll() is not None:
                break
            time.sleep(0.01)
        else:
            self.fail("test host never reached crash point")
        self.assertTrue((self.root / "fault-ready").exists(), (self.root / "host.log").read_text())
        self.pid = int(ready["pid"])
        self.identity = tuple(ready["identity"])
        # Let the child publish its own receipt; the host is already paused.
        launches = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            launches = list((self.root / "BackgroundJobs").glob("*.launch"))
            if launches and launches[0].stat().st_size:
                break
            time.sleep(0.01)
        self.assertTrue(launches and launches[0].stat().st_size, "worker lacks a durable startup receipt")
        self.assertFalse((self.root / "effects.txt").exists(), "command ran before durable launch admission")
        self.host.kill()
        self.host.wait(timeout=3)
        return launches[0].stem

    def _assert_recovered_once(self, phase: str) -> None:
        job_id = self._crash_at(phase)
        self.owner = AgentBackgroundJobService(self.db, events=lambda *a, **k: None)
        self.owner.initialize()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.owner.status(str(self.session["id"]), job_id)["job"]
            if job["status"] not in {"queued", "running", "cancelling"}:
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["pid"], self.pid)
        self.assertEqual((self.root / "effects.txt").read_text().splitlines(), ["effect"])

    def test_sigkill_between_spawn_and_identity_commit_reattaches_waiting_worker(self) -> None:
        self._assert_recovered_once("before_identity_commit")

    def test_sigkill_between_identity_commit_and_release_resumes_same_worker(self) -> None:
        self._assert_recovered_once("after_identity_commit")

    def test_cancel_persisted_before_identity_commit_never_releases_command(self) -> None:
        job_id = self._crash_at("before_identity_commit")
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE agent_background_jobs SET status='cancelling' WHERE job_id=?", (job_id,))
        self.owner = AgentBackgroundJobService(self.db, events=lambda *a, **k: None)
        self.owner.initialize()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = self.owner.status(str(self.session["id"]), job_id)["job"]
            if job["status"] not in {"queued", "running", "cancelling"}:
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "cancelled")
        self.assertFalse((self.root / "effects.txt").exists())

    def test_mismatched_startup_receipt_remains_unknown_and_does_not_release(self) -> None:
        job_id = self._crash_at("before_identity_commit")
        path = self.root / "BackgroundJobs" / f"{job_id}.launch"
        receipt = json.loads(path.read_text())
        receipt["commandSha256"] = "0" * 64
        path.write_text(json.dumps(receipt))
        self.owner = AgentBackgroundJobService(self.db, events=lambda *a, **k: None)
        self.owner.initialize()
        job = self.owner.status(str(self.session["id"]), job_id)["job"]
        self.assertEqual(job["status"], "orphaned")
        self.assertFalse((path.with_suffix(".release")).exists())
        self.assertFalse((self.root / "effects.txt").exists())

    def test_release_io_failure_is_local_to_job_and_does_not_run_command(self) -> None:
        job_id = self._crash_at("before_identity_commit")
        self.owner = AgentBackgroundJobService(self.db, events=lambda *a, **k: None)
        with patch.object(self.owner, "_release_launch", side_effect=OSError("fixture disk failure")):
            self.owner.initialize()
        job = self.owner.status(str(self.session["id"]), job_id)["job"]
        self.assertEqual(job["status"], "failed")
        self.assertFalse((self.root / "effects.txt").exists())

    def test_launch_gate_preserves_native_restricted_command_sandbox(self) -> None:
        if not Path("/usr/bin/sandbox-exec").is_file():
            self.skipTest("native macOS sandbox unavailable")
        workspace = self.root / "restricted"
        workspace.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("synthetic fixture")
        script = workspace / "probe.py"
        script.write_text(
            "from pathlib import Path\ntry:\n"
            f"    Path({str(outside)!r}).read_text()\n"
            "except PermissionError:\n    print('DENIED', flush=True)\n"
            "else:\n    raise RuntimeError('scope escaped')\n"
        )
        session = AgentSessionStore(self.db).create(
            title="restricted startup fixture", mode="coordinator", workspace_roots=[str(workspace)],
        )
        harness = WorkspaceHarness()
        # This stdlib-only probe must launch from a system-readable location.
        # A uv base interpreter can live under /Users or /Volumes and is then
        # correctly denied before the probe can check its outside-file fence.
        interpreter = "/usr/bin/python3"
        if not Path(interpreter).is_file():
            self.skipTest("system Python is unavailable for the native sandbox probe")
        prepared = harness.prepare_background_command(session, {
            "command": shlex.join([interpreter, str(script)]), "cwd": str(workspace), "timeoutSeconds": 10,
        })
        self.assertFalse(prepared.unrestricted)
        self.owner = AgentBackgroundJobService(self.db, events=lambda *a, **k: None, workspace_harness=harness)
        self.owner.initialize()
        initial = self.owner.start(str(session["id"]), prepared)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.owner.status(str(session["id"]), initial["job"]["jobId"])["job"]
            if job["status"] not in {"queued", "running", "cancelling"}:
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "completed", job)
        self.assertIn("DENIED", self.owner.logs(str(session["id"]), job["jobId"])["text"])


if __name__ == "__main__":
    unittest.main()
