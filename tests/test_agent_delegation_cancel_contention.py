from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from tests import test_agent_delegation as fixtures


class DelegationCancellationContentionTests(unittest.TestCase):
    """Hold the real advisory Artifact mutex while exercising real control rows."""

    def setUp(self) -> None:
        self.fixture = fixtures.AgentDelegationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def _assert_one_result(self, coordinator, batch_id: str) -> None:
        batch = coordinator.wait(batch_id)
        self.assertEqual(batch["state"], "aborted")
        self.assertEqual({run["state"] for run in batch["runs"]}, {"aborted"})
        coordinator._schedule_pending_result_contexts()
        coordinator._schedule_pending_result_contexts()
        items = [
            item for item in self.fixture.context_runtime.list_items(str(self.fixture.parent["id"]))
            if item["sourceKind"] == "subagent_result"
        ]
        self.assertEqual(len(items), 1)
        run = batch["runs"][0]
        events = coordinator.store.list_events(str(run["id"]))
        terminals = [event for event in events if event["eventType"] in {"completed", "failed", "aborted", "timed_out"}]
        self.assertEqual([event["eventType"] for event in terminals], ["aborted"])

    def test_queued_abort_acknowledges_without_waiting_for_artifact_lock(self) -> None:
        coordinator = self.fixture.coordinator()
        with patch.object(coordinator, "_start_run_thread"):
            batch = coordinator.delegate(str(self.fixture.parent["id"]), {
                "agent": "researcher", "task": "cancel queued fixture",
                "wait": False, **fixtures._TASK_CONTRACT,
            })["batch"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            with coordinator.artifacts._lock:
                future = pool.submit(coordinator.abort, str(self.fixture.parent["id"]), {"batchId": batch["id"]})
                receipt = future.result(timeout=2)
                self.assertEqual(receipt["cancellation"]["state"], "terminated")
                self.assertTrue(receipt["batch"]["abortRequested"])
                self.assertNotIn("artifact", receipt["batch"]["runs"][0])
        self._assert_one_result(coordinator, str(batch["id"]))

    def test_running_abort_reaches_runtime_before_advisory_checkpoint(self) -> None:
        entered = threading.Event()
        abort_called = threading.Event()

        class Runtime(fixtures._HangingRuntime):
            def prompt(self, session_id, message):
                receipt = super().prompt(session_id, message)
                entered.set()
                return receipt

            def abort(self, session_id):
                abort_called.set()
                super().abort(session_id)

        coordinator = self.fixture.coordinator(Runtime)
        batch = coordinator.delegate(str(self.fixture.parent["id"]), {
            "agent": "researcher", "task": "cancel running fixture",
            "wait": False, **fixtures._TASK_CONTRACT,
        })["batch"]
        self.assertTrue(entered.wait(3), "fixture runtime did not start")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with coordinator.artifacts._lock:
                future = pool.submit(coordinator.abort, str(self.fixture.parent["id"]), {"runId": batch["runs"][0]["id"]})
                self.assertTrue(abort_called.wait(1), "Artifact blocked cancellation delivery")
                receipt = future.result(timeout=2)
                self.assertTrue(receipt["batch"]["abortRequested"])
                self.assertIn(receipt["cancellation"]["state"], {"requested", "terminated"})
        self._assert_one_result(coordinator, str(batch["id"]))

    def test_ignored_abort_stops_owned_runtime_before_artifact_checkpoint(self) -> None:
        entered = threading.Event()
        stopped = threading.Event()

        class Runtime(fixtures._HangingRuntime):
            def prompt(self, session_id, message):
                result = super().prompt(session_id, message)
                entered.set()
                return result

            def abort(self, _session_id):
                pass

            def stop(self):
                super().stop()
                stopped.set()

        coordinator = self.fixture.coordinator(Runtime)
        batch = coordinator.delegate(str(self.fixture.parent["id"]), {
            "agent": "researcher", "task": "ignored abort fixture",
            "wait": False, **fixtures._TASK_CONTRACT,
        })["batch"]
        self.assertTrue(entered.wait(3))
        with ThreadPoolExecutor(max_workers=1) as pool:
            with coordinator.artifacts._lock:
                future = pool.submit(coordinator.abort, str(self.fixture.parent["id"]), {"batchId": batch["id"]})
                self.assertTrue(stopped.wait(1), "Artifact delayed runtime escalation")
                receipt = future.result(timeout=2)
                self.assertEqual(receipt["cancellation"]["state"], "requested")
        self._assert_one_result(coordinator, str(batch["id"]))


if __name__ == "__main__":
    unittest.main()
