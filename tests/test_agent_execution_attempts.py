from __future__ import annotations

import unittest

from tests import test_agent_delegation as fixtures


class ExecutionAttemptIdentityTests(unittest.TestCase):
    def test_retry_keeps_logical_task_and_preserves_both_attempts(self) -> None:
        fixture = fixtures.AgentDelegationTests("runTest")
        fixture.setUp()
        try:
            coordinator = fixture.coordinator()
            parent = str(fixture.parent["id"])
            child = fixture.sessions.create(title="first attempt fixture")
            batch = coordinator.store.create_batch(
                parent_session_id=parent, parent_run_id="", context_mode="fresh",
                depth=1, max_depth=2,
                runs=[fixtures._run_spec(str(child["id"]), task="attempt identity fixture")],
            )
            first_id = str(batch["runs"][0]["id"])
            coordinator.store.start_run(first_id)
            first = coordinator.store.finish_run(
                first_id, state="failed", error="fixture transport failure",
                result={"failureClass": "transient_runtime", "summary": "first attempt failed before Tools"},
            )
            request = {"action": "retry", "clientActionId": "retry:identity-fixture"}
            receipt = coordinator.control(parent, first_id, request)
            self.assertFalse(receipt["replayed"])
            runs = [run for item in coordinator.store.list_batches(limit=10) for run in item["runs"]]
            self.assertEqual(len(runs), 2)
            second = next(run for run in runs if run["id"] != first_id)
            self.assertEqual(second["nodeId"], first["nodeId"])
            self.assertNotEqual(second["attemptId"], first["attemptId"])
            self.assertEqual(second["attemptNumber"], 2)
            self.assertEqual(second["predecessorAttemptId"], first["attemptId"])
            self.assertTrue(coordinator.control(parent, first_id, request)["replayed"])
            self.assertEqual(len(coordinator.store.list_batches(limit=10)), 2)
            fixtures._wait_until(lambda: coordinator.store.get_run(str(second["id"]))["state"] == "completed")
            late = coordinator.store.finish_run(first_id, state="completed", result={"summary": "late first attempt"})
            self.assertEqual(late["state"], "failed")
            self.assertEqual(late["attemptId"], first["attemptId"])
            self.assertEqual(coordinator.store.get_run(str(second["id"]))["state"], "completed")
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
