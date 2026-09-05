from __future__ import annotations

import os
import json
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.db import sqlite_connection
from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.room_runtime_host_kill_gate import _process_identity


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix" and Path("/bin/zsh").is_file(), "requires POSIX and zsh")
class BackgroundJobOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-job-ownership-")
        self.root = Path(self.temporary.name).resolve()
        self.db = self.root / "jobs.sqlite"
        sessions = AgentSessionStore(self.db)
        sessions.initialize()
        self.session = sessions.create(
            title="ownership fixture", mode="coordinator", execution_mode="full_trust",
            tool_profile_version="control-center-auto-approve-v1",
            workspace_roots=[str(self.root), "/"],
        )
        self.owners = []
        self.hosts = []
        self.workers = []

    def tearDown(self) -> None:
        for host in self.hosts:
            if host.poll() is None:
                host.kill()
            host.wait(timeout=3)
        for pid, identity in self.workers:
            if identity and _process_identity(pid) == identity and identity[0] != os.getpgrp():
                try:
                    os.killpg(identity[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for owner in self.owners:
            owner.close()
        self.temporary.cleanup()

    def owner(self, **kwargs):
        owner = AgentBackgroundJobService(self.db, events=lambda *a, **k: None, **kwargs)
        self.owners.append(owner)
        owner.initialize()
        return owner

    def start(self, owner):
        script = self.write_command()
        prepared = WorkspaceHarness().prepare_background_command(self.session, {
            "command": shlex.join([sys.executable, str(script)]),
            "cwd": str(self.root), "timeoutSeconds": 30,
        })
        job = owner.start(str(self.session["id"]), prepared)["job"]
        pid = int(job["pid"])
        self.workers.append((pid, _process_identity(pid)))
        self.eventually(lambda: (self.root / "started").exists())
        return job

    def write_command(self):
        script = self.root / "command.py"
        script.write_text(
            "from pathlib import Path\nimport time\n"
            "Path('started').touch()\n"
            "while not Path('finish').exists(): time.sleep(0.02)\n"
            "with Path('effects').open('a') as f: f.write('effect\\n')\n"
        )
        return script

    def lease(self, job_id):
        with sqlite_connection(self.db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM agent_background_job_owner_leases WHERE job_id=?", (job_id,)).fetchone()
            return dict(row)

    def host(self, name):
        with (self.root / (name + ".log")).open("wb") as output:
            host = subprocess.Popen(
                [sys.executable, str(ROOT / "tests/fixtures/agent_background_ownership_host.py"),
                 str(self.root), str(self.session["id"]), name],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.hosts.append(host)
        self.eventually(lambda: (self.root / (name + "-ready")).exists() or host.poll() is not None)
        self.assertIsNone(host.poll(), (self.root / (name + ".log")).read_text())
        return host

    def eventually(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        self.fail("condition did not become true before deadline")

    def test_live_owner_excludes_second_supervisor(self) -> None:
        first = self.owner()
        job = self.start(first)
        second = self.owner()
        self.assertNotIn(job["jobId"], second._live, "two hosts monitor the same active worker")
        self.assertEqual(second.status(str(self.session["id"]), job["jobId"])["job"]["pid"], job["pid"])

    def test_silent_command_has_heartbeat_independent_of_log_progress(self) -> None:
        first = self.owner(lease_seconds=1.5)
        job = self.start(first)
        before = self.lease(job["jobId"])
        self.eventually(lambda: self.lease(job["jobId"])["heartbeat_at_ms"] > before["heartbeat_at_ms"])
        after = self.lease(job["jobId"])
        self.assertEqual(after["generation"], before["generation"])
        self.assertGreater(after["deadline_tick_ms"], before["deadline_tick_ms"])
        self.assertEqual(first.logs(str(self.session["id"]), job["jobId"])["text"], "")

    def test_orderly_detach_allows_peer_to_resume_same_process_without_waiting_ttl(self) -> None:
        first = self.owner(lease_seconds=30)
        job = self.start(first)
        second = self.owner(lease_seconds=30)
        original = self.lease(job["jobId"])
        first.close()
        self.eventually(lambda: self.lease(job["jobId"])["owner_id"] == second._ownership.owner_id, timeout=3)
        self.assertEqual(self.lease(job["jobId"])["generation"], original["generation"] + 1)
        (self.root / "finish").touch()
        self.eventually(lambda: second.status(str(self.session["id"]), job["jobId"])["job"]["status"] == "completed")
        self.assertEqual(second.status(str(self.session["id"]), job["jobId"])["job"]["pid"], job["pid"])
        self.assertEqual((self.root / "effects").read_text().splitlines(), ["effect"])

    def test_cancel_through_observing_peer_reaches_current_owner(self) -> None:
        first = self.owner()
        job = self.start(first)
        second = self.owner()
        self.assertNotIn(job["jobId"], second._live)
        second.cancel(str(self.session["id"]), job["jobId"], reason="peer_control")
        self.eventually(lambda: first.status(str(self.session["id"]), job["jobId"])["job"]["status"] == "cancelled")
        self.assertFalse((self.root / "effects").exists())

    def test_sigstop_owner_peer_takeover_and_sigcont_rejects_stale_mutations(self) -> None:
        self.write_command()
        a = self.host("a")
        job = json.loads((self.root / "a-ready").read_text())
        job_id, pid = job["jobId"], int(job["pid"])
        self.workers.append((pid, _process_identity(pid)))
        self.eventually(lambda: (self.root / "started").exists())
        old = self.lease(job_id)
        b = self.host("b")
        self.assertEqual(self.lease(job_id)["owner_pid"], a.pid)
        # Pause outside a SQLite critical section. A stopped lock holder is a
        # storage outage, a separate fault from a missing supervisor heartbeat.
        with sqlite_connection(self.db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            os.kill(a.pid, signal.SIGSTOP)
        self.eventually(lambda: self.lease(job_id)["owner_pid"] == b.pid, timeout=6)
        current = self.lease(job_id)
        self.assertEqual(current["generation"], old["generation"] + 1)
        (self.root / "probe-old-owner").touch()
        os.kill(a.pid, signal.SIGCONT)
        self.eventually(lambda: (self.root / "probe-result").exists())
        rejected = json.loads((self.root / "probe-result").read_text())
        self.assertEqual(rejected, {key: "BackgroundJobLeaseLost" for key in ("progress", "terminal", "result", "timeout", "release", "terminate", "cleanup")})
        observer = self.owner(execution_owner=False)
        self.assertEqual(observer.status(str(self.session["id"]), job_id)["job"]["status"], "running")
        self.assertEqual(_process_identity(pid), self.workers[-1][1])
        self.assertTrue((self.root / "BackgroundJobs" / (job_id + ".raw")).exists())
        (self.root / "finish").touch()
        self.eventually(lambda: observer.status(str(self.session["id"]), job_id)["job"]["status"] == "completed")
        self.assertEqual((self.root / "effects").read_text().splitlines(), ["effect"])
        self.assertEqual(observer.status(str(self.session["id"]), job_id)["job"]["pid"], pid)

    def test_paused_owner_without_takeover_resumes_same_command(self) -> None:
        self.write_command()
        host = self.host("a")
        job = json.loads((self.root / "a-ready").read_text())
        job_id, pid = job["jobId"], int(job["pid"])
        self.workers.append((pid, _process_identity(pid)))
        with sqlite_connection(self.db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            os.kill(host.pid, signal.SIGSTOP)
        old = self.lease(job_id)
        self.eventually(lambda: time.monotonic_ns() // 1_000_000 > old["deadline_tick_ms"])
        os.kill(host.pid, signal.SIGCONT)
        self.eventually(lambda: self.lease(job_id)["deadline_tick_ms"] > old["deadline_tick_ms"])
        self.assertEqual(self.lease(job_id)["owner_id"], old["owner_id"])
        (self.root / "finish").touch()
        observer = self.owner(execution_owner=False)
        self.eventually(lambda: observer.status(str(self.session["id"]), job_id)["job"]["status"] == "completed")
        self.assertEqual((self.root / "effects").read_text().splitlines(), ["effect"])


if __name__ == "__main__":
    unittest.main()
