from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock


class Adapter:
    def __init__(self):
        self.calls = 0
        self.inputs = []
        self.execute_body = None

    def prepare(self, spec, job_id):
        return {"publicSpec": {"model": spec.get("model", "test")}, "privateInput": {"secret": "private-sentinel", "job": job_id}}

    def execute(self, private_input, observer, cancelled):
        self.calls += 1
        self.inputs.append(private_input)
        if self.execute_body:
            return self.execute_body(private_input, observer, cancelled)
        observer.progress("Scored actual fixture")
        observer.bind_session("actual-session", "actual-turn")
        return {"qualityVerdict": "reject", "score": 0.5}


class AgentLabTrialExecutionTests(unittest.TestCase):
    def setUp(self):
        from rag_ime.agent_lab.trials import AgentLabTrialStore
        from rag_ime.agent_lab.trial_execution import AgentLabTrialApplication
        self.application = AgentLabTrialApplication
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = AgentLabTrialStore(Path(self.tmp.name) / "trial.sqlite")
        self.adapter = Adapter()
        self.app = self.application(self.store, {"scene": self.adapter}, start_workers=False)
        self.addCleanup(self.app.close)

    def start(self, key="click"):
        return self.app.start(key, "scene", {"model": "test"})["job"]["jobId"]

    def test_double_click_and_concurrent_run_execute_once_without_implicit_quality_pass(self):
        job_id = self.start()
        self.assertEqual(self.start(), job_id)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(self.app.run_job, [job_id] * 6))
        self.assertEqual(self.adapter.calls, 1)
        job = self.app.read(job_id)["job"]
        self.assertEqual(job["state"], "completed")
        self.assertEqual(job["result"]["qualityVerdict"], "reject")
        self.assertEqual(job["sessions"], [{"sessionId": "actual-session", "turnId": "actual-turn"}])
        self.assertNotIn("private-sentinel", json.dumps(self.app.read()))

    def test_queued_cancel_does_not_execute(self):
        job_id = self.start()
        self.assertEqual(self.app.cancel(job_id)["job"]["state"], "cancelled")
        self.app.run_job(job_id)
        self.assertEqual(self.adapter.calls, 0)

    def test_scheduling_failure_returns_the_persisted_interruption_and_never_retries(self):
        self.app._pool = Mock()
        self.app._pool.submit.side_effect = RuntimeError("executor stopped: private-sentinel")
        admission = self.app.start("schedule-failed", "scene", {})
        self.assertEqual(admission["job"]["state"], "interrupted")
        self.assertFalse(admission["replayed"])
        self.assertEqual(admission["job"], self.app.read(admission["job"]["jobId"])["job"])
        replay = self.app.start("schedule-failed", "scene", {})
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"], admission["job"])
        self.app._pool.submit.assert_called_once()
        self.assertEqual(self.adapter.calls, 0)
        self.assertNotIn("private-sentinel", json.dumps(admission))

    def test_report_execution_status_is_projected_without_treating_quality_rejection_as_failure(self):
        for state in ("failed", "cancelled", "interrupted", "completed"):
            report = {"status": state, "qualityVerdict": "reject", "score": 0.5,
                      "cost": {"available": True, "estimatedUsd": 0.125}}
            self.adapter.execute_body = lambda *_, report=report: report
            job_id = self.start("report-" + state)
            self.app.run_job(job_id)
            job = self.app.read(job_id)["job"]
            with self.subTest(state=state):
                self.assertEqual(job["state"], state)
                self.assertEqual(job["result"], report)

    def test_cancelled_report_retains_actual_failure_and_cost_after_settlement(self):
        entered, aborted, release = threading.Event(), threading.Event(), threading.Event()
        report = {"status": "cancelled", "cost": {"available": True, "estimatedUsd": 0.125}}
        def execute(_, observer, cancelled):
            observer.bind_session("actual-session", "actual-turn", cancel=aborted.set)
            entered.set()
            self.assertTrue(release.wait(3))
            return report
        self.adapter.execute_body = execute
        job_id = self.start()
        worker = threading.Thread(target=self.app.run_job, args=(job_id,))
        worker.start()
        self.assertTrue(entered.wait(3))
        try:
            self.assertEqual(self.app.cancel(job_id)["job"]["state"], "cancelling")
            self.assertTrue(aborted.is_set())
        finally:
            release.set()
            worker.join(3)
        job = self.app.read(job_id)["job"]
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(job["result"], report)

    def test_running_cancel_calls_abort_and_waits_for_cleanup_before_terminal(self):
        entered, aborted, cleanup_allowed = threading.Event(), threading.Event(), threading.Event()
        def execute(_, observer, cancelled):
            observer.bind_session("session", "turn", cancel=aborted.set)
            entered.set()
            self.assertTrue(aborted.wait(3))
            self.assertTrue(cancelled())
            self.assertTrue(cleanup_allowed.wait(3))
            return {"qualityVerdict": "pass"}  # Late success cannot override cancellation.
        self.adapter.execute_body = execute
        job_id = self.start()
        thread = threading.Thread(target=self.app.run_job, args=(job_id,))
        thread.start()
        self.assertTrue(entered.wait(3))
        try:
            self.assertEqual(self.app.cancel(job_id)["job"]["state"], "cancelling")
            self.assertTrue(aborted.is_set())
            self.assertEqual(self.app.read(job_id)["job"]["state"], "cancelling")
        finally:
            cleanup_allowed.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        job = self.app.read(job_id)["job"]
        self.assertEqual(job["state"], "cancelled")
        self.assertIsNone(job["result"])

    def test_cancel_waits_for_abort_hook_even_if_execute_already_returns(self):
        entered, hook_entered, hook_release, execute_return = [threading.Event() for _ in range(4)]
        def abort():
            hook_entered.set()
            execute_return.set()
            self.assertTrue(hook_release.wait(3))
        def execute(_, observer, cancelled):
            observer.bind_session("session", cancel=abort)
            entered.set()
            self.assertTrue(execute_return.wait(3))
            return {"actual": True}
        self.adapter.execute_body = execute
        job_id = self.start()
        worker = threading.Thread(target=self.app.run_job, args=(job_id,))
        stopper = threading.Thread(target=self.app.cancel, args=(job_id,))
        worker.start(); self.assertTrue(entered.wait(3)); stopper.start()
        try:
            self.assertTrue(hook_entered.wait(3))
            self.assertEqual(self.app.read(job_id)["job"]["state"], "cancelling")
        finally:
            hook_release.set(); stopper.join(3); worker.join(3)
        self.assertEqual(self.app.read(job_id)["job"]["state"], "cancelled")

    def test_session_bound_after_cancel_is_aborted_exactly_once(self):
        entered, bind_allowed = threading.Event(), threading.Event()
        aborted = []
        def execute(_, observer, cancelled):
            entered.set(); self.assertTrue(bind_allowed.wait(3))
            for _ in range(2):
                observer.bind_session("late-session", "turn", cancel=lambda: aborted.append("abort"))
            return {}
        self.adapter.execute_body = execute
        job_id = self.start()
        worker = threading.Thread(target=self.app.run_job, args=(job_id,)); worker.start()
        self.assertTrue(entered.wait(3)); self.app.cancel(job_id); bind_allowed.set(); worker.join(3)
        self.assertEqual(aborted, ["abort"])
        self.assertEqual(self.app.read(job_id)["job"]["state"], "cancelled")

    def test_restart_interrupts_and_read_or_replay_never_starts_paid_work(self):
        job_id = self.start()
        self.store.claim(job_id)
        restarted = self.application(self.store, {"scene": self.adapter}, start_workers=False)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.read(job_id)["job"]["state"], "interrupted")
        restarted.start("click", "scene", {"model": "test"})
        restarted.run_job(job_id)
        self.assertEqual(self.adapter.calls, 0)

    def test_failed_wait_is_interrupted_and_unknown_exception_does_not_leak_secrets(self):
        for index, exception in enumerate((TimeoutError("private-sentinel"), RuntimeError("private-sentinel"))):
            def execute(*_, exception=exception): raise exception
            self.adapter.execute_body = execute
            job_id = self.start(f"error-{index}"); self.app.run_job(job_id)
            self.assertEqual(self.app.read(job_id)["job"]["state"], "interrupted" if index == 0 else "failed")
            self.assertNotIn("private-sentinel", json.dumps(self.app.read(job_id)))
            self.app.run_job(job_id)
        self.assertEqual(self.adapter.calls, 2)

    def test_only_registered_scene_is_admitted(self):
        with self.assertRaises(ValueError): self.app.start("unknown", "unknown", {})
        self.assertEqual(self.app.read()["jobs"], [])

    def test_changed_scene_conflicts_even_without_a_registered_adapter(self):
        from rag_ime.agent_lab.trials import AgentLabTrialConflict
        self.start()
        with self.assertRaises(AgentLabTrialConflict):
            self.app.start("click", "unregistered-scene", {"model": "test"})
        self.assertEqual(self.adapter.calls, 0)

    def test_replay_still_returns_original_job_if_its_adapter_is_unavailable(self):
        job_id = self.start()
        self.app.close()
        replacement = self.application(self.store, {}, start_workers=False)
        self.addCleanup(replacement.close)
        replay = replacement.start("click", "scene", {"model": "test"})
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["job"]["jobId"], job_id)
        self.assertEqual(replay["job"]["state"], "interrupted")
        self.assertEqual(self.adapter.calls, 0)

    def test_close_aborts_and_waits_for_active_cleanup(self):
        entered, abort_called, cleanup_allowed = [threading.Event() for _ in range(3)]
        def execute(_, observer, cancelled):
            observer.bind_session("session", cancel=abort_called.set)
            entered.set(); self.assertTrue(cleanup_allowed.wait(3)); return {}
        self.adapter.execute_body = execute
        job_id = self.start()
        worker = threading.Thread(target=self.app.run_job, args=(job_id,)); worker.start()
        self.assertTrue(entered.wait(3))
        closer = threading.Thread(target=self.app.close); closer.start()
        try:
            self.assertTrue(abort_called.wait(3))
            self.assertTrue(closer.is_alive())
        finally:
            cleanup_allowed.set(); worker.join(3); closer.join(3)
        self.assertEqual(self.app.read(job_id)["job"]["state"], "interrupted")

    def test_failed_abort_or_cleanup_timeout_stays_interrupted_not_cancelled(self):
        for index, hook_fails in enumerate((True, False)):
            entered, finish_allowed = threading.Event(), threading.Event()
            def abort(finish_allowed=finish_allowed, hook_fails=hook_fails):
                finish_allowed.set()
                if hook_fails:
                    raise RuntimeError("private-sentinel")
            def execute(_, observer, cancelled, entered=entered, finish_allowed=finish_allowed, hook_fails=hook_fails, abort=abort):
                observer.bind_session("uncertain-session", cancel=abort)
                entered.set()
                self.assertTrue(finish_allowed.wait(3))
                if not hook_fails:
                    raise TimeoutError("private-sentinel")
                return {}
            self.adapter.execute_body = execute
            job_id = self.start(f"uncertain-{index}")
            worker = threading.Thread(target=self.app.run_job, args=(job_id,))
            worker.start(); self.assertTrue(entered.wait(3)); self.app.cancel(job_id); worker.join(3)
            result = self.app.read(job_id)
            self.assertEqual(result["job"]["state"], "interrupted")
            self.assertNotIn("private-sentinel", json.dumps(result))

    def test_background_worker_claims_only_once_and_does_not_run_cancelled_queue(self):
        entered, release = threading.Event(), threading.Event()
        def execute(_, observer, cancelled):
            entered.set()
            self.assertTrue(release.wait(3))
            return {"report": "actual"}
        self.adapter.execute_body = execute
        background = self.application(self.store, {"scene": self.adapter}, max_workers=1)
        try:
            first = background.start("first", "scene", {})["job"]["jobId"]
            self.assertTrue(entered.wait(3))
            queued = background.start("second", "scene", {})["job"]["jobId"]
            background.cancel(queued)
            for _ in range(5):
                self.assertEqual(background.start("first", "scene", {})["job"]["jobId"], first)
            release.set()
        finally:
            release.set(); background.close()
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(background.read(queued)["job"]["state"], "cancelled")

    def test_concurrent_close_waits_for_same_cleanup_and_calls_abort_once(self):
        entered, abort_called, release = threading.Event(), threading.Event(), threading.Event()
        aborted = []
        def abort():
            aborted.append(True); abort_called.set()
        def execute(_, observer, cancelled):
            observer.bind_session("session", cancel=abort)
            entered.set(); self.assertTrue(release.wait(3)); return {}
        self.adapter.execute_body = execute
        job_id = self.start()
        worker = threading.Thread(target=self.app.run_job, args=(job_id,)); worker.start()
        self.assertTrue(entered.wait(3))
        closers = [threading.Thread(target=self.app.close) for _ in range(2)]
        for closer in closers: closer.start()
        try:
            self.assertTrue(abort_called.wait(3))
            self.assertTrue(all(closer.is_alive() for closer in closers))
        finally:
            release.set(); worker.join(3)
            for closer in closers: closer.join(3)
        self.assertEqual(aborted, [True])
        self.assertTrue(all(not closer.is_alive() for closer in closers))


if __name__ == "__main__":
    unittest.main()
