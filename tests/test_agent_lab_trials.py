from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class AgentLabTrialStoreTests(unittest.TestCase):
    def setUp(self):
        from rag_ime.agent_lab_trials import AgentLabTrialStore
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "trials.sqlite"
        self.store = AgentLabTrialStore(self.path)
        self.prepared = []

    def prepare(self, spec, job_id):
        self.prepared.append(job_id)
        return {"publicSpec": {"model": spec["model"]}, "privateInput": {"token": "private-sentinel", "spec": spec}}

    def admit(self, request="request-1", spec=None):
        return self.store.admit(request, "scene-one", spec or {"model": "test"}, self.prepare)

    def test_concurrent_replay_is_durable_and_prepares_only_once(self):
        from rag_ime.agent_lab_trials import AgentLabTrialStore
        other = AgentLabTrialStore(self.path)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: (self.store if i % 2 else other).admit("same", "scene-one", {"model": "test"}, self.prepare), range(8)))
        self.assertEqual(len({r["job"]["jobId"] for r in results}), 1)
        self.assertEqual(len(self.prepared), 1)
        self.assertEqual(sum(not r["replayed"] for r in results), 1)
        self.assertEqual(AgentLabTrialStore(self.path).read()["jobs"][0]["state"], "queued")

    def test_changed_request_conflicts_without_repreparing(self):
        from rag_ime.agent_lab_trials import AgentLabTrialConflict
        self.admit()
        with self.assertRaises(AgentLabTrialConflict) as conflict:
            self.admit(spec={"model": "different"})
        self.assertEqual(conflict.exception.http_status, 409)
        self.assertEqual(len(self.prepared), 1)

    def test_frozen_input_is_copied_private_and_sql_immutable(self):
        spec = {"model": "test", "nested": {"value": 1}}
        admitted = self.admit(spec=spec)
        job_id = admitted["job"]["jobId"]
        spec["nested"]["value"] = 2
        self.assertEqual(self.store.job_input(job_id)["privateInput"]["spec"]["nested"]["value"], 1)
        self.assertNotIn("private-sentinel", json.dumps(self.store.read()))
        self.assertNotIn("privateInput", json.dumps(self.store.read(job_id)))
        with sqlite3.connect(self.path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE agent_lab_trials SET private_input_json='{}' WHERE job_id=?", (job_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE agent_lab_trials SET public_spec_json='{}' WHERE job_id=?", (job_id,))

    def test_terminal_result_and_progress_cannot_be_rewritten(self):
        job_id = self.admit()["job"]["jobId"]
        self.assertIsNotNone(self.store.claim(job_id))
        self.store.request_cancel(job_id)
        self.store.finish(job_id, "cancelled")
        self.store.finish(job_id, "completed", result={"quality": "passed"})
        self.store.progress(job_id, "late success")
        job = self.store.read(job_id)["job"]
        self.assertEqual(job["state"], "cancelled")
        self.assertIsNone(job["result"])
        self.assertNotEqual(job["progress"], "late success")

    def test_read_never_claims_or_recovers_queued_work(self):
        job_id = self.admit()["job"]["jobId"]
        for _ in range(3):
            self.assertEqual(self.store.read(job_id)["job"]["state"], "queued")
        self.assertIsNotNone(self.store.claim(job_id))
        self.assertIsNone(self.store.claim(job_id))

    def test_recovery_marks_unsettled_work_interrupted_retaining_bindings(self):
        queued = self.admit("queued")["job"]["jobId"]
        running = self.admit("running")["job"]["jobId"]
        self.store.claim(running)
        self.store.bind_session(running, "session-actual", "turn-actual")
        self.store.request_cancel(running)
        recovered = self.store.recover_interrupted()
        self.assertEqual(len(recovered), 2)
        for job_id in (queued, running):
            self.assertEqual(self.store.read(job_id)["job"]["state"], "interrupted")
            self.assertIsNone(self.store.claim(job_id))
        self.assertEqual(self.store.read(running)["job"]["sessions"], [{"sessionId": "session-actual", "turnId": "turn-actual"}])

    def test_failed_preparation_admits_nothing(self):
        def fail(spec, job_id):
            raise ValueError("Invalid frozen input")
        with self.assertRaises(ValueError):
            self.store.admit("bad", "scene-one", {}, fail)
        self.assertEqual(self.store.read()["jobs"], [])


if __name__ == "__main__":
    unittest.main()
