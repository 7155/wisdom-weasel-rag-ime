from __future__ import annotations

import sqlite3
import time
import unittest

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_learning_governance import LearningGovernanceError
from rag_ime.agent_room_learning_runtime import RoomLearningRuntime
from tests.test_agent_room_learning_governance import RoomLearningGovernanceTests


class _InvalidReflection:
    def reflect(self, incident, *, timeout_ms):
        del incident, timeout_ms
        return {}


class _ValidReflection:
    def reflect(self, incident, *, timeout_ms):
        del timeout_ms
        return {
            "facts": ["runtime delivery failed"],
            "causes": ["the Pi host exited"],
            "applicabilityBoundary": {"scope": "Room dispatch", "exclusions": ["ordinary sessions"]},
            "counterexamples": ["an acknowledged dispatch is not a failure"],
            "provenance": [str(incident["incident_id"])],
        }


class _SlowReflection:
    def reflect(self, incident, *, timeout_ms):
        del incident, timeout_ms
        time.sleep(0.003)
        return {}


class RoomLearningRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RoomLearningGovernanceTests(methodName="runTest")
        self.fixture.setUp()
        self.store = self.fixture.store
        self.db = self.fixture.db

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_kernel_receipts_auto_create_one_incident_with_many_occurrences(self) -> None:
        kernel = RoomKernelStore(self.db, mode="test")
        kernel.initialize()
        runtime = RoomLearningRuntime(self.store)
        for now_ms in (10, 11):
            kernel.record_learning_signal(
                root_id="root:1",
                dispatch_id="dispatch:1",
                receipt_kind="dead_letter",
                status="unknown",
                reason="runtime_failed:ConnectionError",
                now_ms=now_ms,
            )
        runtime.ingest_kernel_receipts(now_ms=20)
        self.assertEqual(runtime.ingest_kernel_receipts(now_ms=21), 0)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM room_v2_incidents WHERE taxonomy='tool_failure'").fetchone()[0],
                1,
            )
            incident_id = conn.execute(
                "SELECT incident_id FROM room_v2_incidents WHERE taxonomy='tool_failure'"
            ).fetchone()[0]
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM room_v2_incident_occurrences WHERE incident_id=?",
                    (incident_id,),
                ).fetchone()[0],
                2,
            )

    def test_reflection_schema_errors_dead_letter_and_valid_output_stays_candidate_only(self) -> None:
        slow = RoomLearningRuntime(
            self.store, reflection_provider=_SlowReflection(), reflection_timeout_ms=1
        )
        slow.enqueue_reflection("incident:1", now_ms=1, max_attempts=1)
        timeout = slow.run_reflection_once(now_ms=1)
        self.assertEqual(timeout["state"], "dead_letter")
        self.assertIn("timeout", timeout["error"])
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM room_v2_reflection_jobs WHERE incident_id='incident:1'")

        bad = RoomLearningRuntime(self.store, reflection_provider=_InvalidReflection())
        bad.enqueue_reflection("incident:1", now_ms=10, max_attempts=3)
        self.assertEqual(bad.run_reflection_once(now_ms=10)["state"], "retry_wait")
        self.assertEqual(bad.run_reflection_once(now_ms=3_000)["state"], "retry_wait")
        self.assertEqual(bad.run_reflection_once(now_ms=8_000)["state"], "dead_letter")
        with sqlite3.connect(self.db) as conn:
            state, error = conn.execute(
                "SELECT state,last_error FROM room_v2_reflection_jobs WHERE incident_id='incident:1'"
            ).fetchone()
            self.assertEqual(state, "dead_letter")
            self.assertIn("schema error", error)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_lesson_candidates").fetchone()[0], 0)

        duplicate, _ = self.fixture._incident("incident:duplicate", "occurrence:new")
        self.assertEqual(duplicate["incidentId"], "incident:1")
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM room_v2_reflection_jobs WHERE incident_id='incident:1'")
        good = RoomLearningRuntime(self.store, reflection_provider=_ValidReflection())
        good.enqueue_reflection("incident:1", now_ms=9_000)
        result = good.run_reflection_once(now_ms=9_000)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["lesson"]["state"], "candidate_only")
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_guard_active_pointers").fetchone()[0], 0)

    def test_materialization_root_pin_rollback_cleanup_and_cancel_replay(self) -> None:
        activation = self._activate_guard()
        runtime = RoomLearningRuntime(self.store)
        with self.assertRaisesRegex(RuntimeError, "materialization crash"):
            runtime.materialize_once(now_ms=101, fail_after_projection=True)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_guard_materializations").fetchone()[0], 0)
        runtime.materialize_once(now_ms=102)

        self.fixture._seed_new_root()
        pin = self.store.guard_for_root(
            binding_id="participant-binding:dispatch:new", root_id="root:new", scope_key="room:room:1"
        )
        self.assertEqual(pin["configHash"], activation["signedConfigHash"])
        surfaces = self.store.materialized_guard(
            scope_key="room:room:1", guard_epoch=1, config_hash=pin["configHash"]
        )
        self.assertEqual(set(surfaces), {"prompt", "skill", "tool", "test_fixture"})
        with sqlite3.connect(self.db) as conn:
            original = conn.execute(
                "SELECT payload_json FROM room_v2_guard_materializations WHERE scope_key='room:room:1' AND surface='tool'"
            ).fetchone()[0]
            conn.execute(
                "UPDATE room_v2_guard_materializations SET payload_json='{}' WHERE scope_key='room:room:1' AND surface='tool'"
            )
        with self.assertRaisesRegex(LearningGovernanceError, "payload mismatch"):
            self.store.materialized_guard(
                scope_key="room:room:1", guard_epoch=1, config_hash=pin["configHash"]
            )
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "UPDATE room_v2_guard_materializations SET payload_json=? WHERE scope_key='room:room:1' AND surface='tool'",
                (original,),
            )
        self.store.bind_execution(
            dispatch_id="dispatch:new", root_id="root:new", scope_key="room:room:1",
            guard_epoch=1, config_hash=pin["configHash"], now_ms=103,
        )
        self.store.accept_writeback(
            dispatch_id="dispatch:new", guard_epoch=1, config_hash=pin["configHash"]
        )
        with self.assertRaisesRegex(LearningGovernanceError, "old Guard epoch"):
            self.store.accept_writeback(
                dispatch_id="dispatch:new", guard_epoch=2, config_hash=pin["configHash"]
            )
        before = self._evidence_counts()
        self.store.rollback(
            rollback_receipt_id="rollback:runtime", scope_key="room:room:1",
            authority_ref="user:1", authority_secret=b"user-secret",
            reason="regression", now_ms=104,
        )
        with self.assertRaisesRegex(LearningGovernanceError, "old Guard epoch"):
            self.store.accept_writeback(
                dispatch_id="dispatch:new", guard_epoch=1, config_hash=pin["configHash"]
            )
        with self.assertRaisesRegex(RuntimeError, "materialization crash"):
            runtime.materialize_once(now_ms=105, fail_after_projection=True)
        runtime.materialize_once(now_ms=106)
        self.assertEqual(before, self._evidence_counts())

        calls: list[str] = []

        def cancel(item):
            calls.append(str(item["cancel_id"]))
            return {"kernelReceipt": {"receiptId": "kernel:cancel"}, "runtimeReceipts": [{"status": "applied"}]}

        first = runtime.drain_cancel_once(cancel, now_ms=107, fail_after_effect=True)
        self.assertEqual(first["state"], "pending")
        second = runtime.drain_cancel_once(cancel, now_ms=108)
        self.assertEqual(second["state"], "applied")
        self.assertEqual(calls[0], calls[1])

    def _activate_guard(self):
        self.fixture._lesson()
        guard = self.fixture._guard()
        eval_ids = []
        for eval_id, mode, dataset in (("eval:shadow", "shadow", "1"), ("eval:canary", "canary", "2")):
            self.store.record_eval(
                eval_run_id=eval_id, guard_candidate_id="guard:1", mode=mode,
                dataset_hash=dataset * 64, positive_fixture_count=2, negative_fixture_count=2,
                metrics=self.fixture._metrics(), runner_receipt_id="runner-receipt:1", created_at_ms=10,
            )
            eval_ids.append(eval_id)
        approval = self.store.approve_guard(
            approval_receipt_id="approval:runtime", guard_candidate_id="guard:1",
            authority_ref="admin:1", decision="approve", created_at_ms=11,
            authority_secret=b"approval-secret",
        )
        signature = self.store.expected_config_signature(
            scope={"kind": "room", "selector": "room:1"}, guard_candidate_id="guard:1",
            candidate_hash=guard["candidateHash"], guard_epoch=1, applies_after_ms=100,
            eval_run_ids=eval_ids,
        )
        return self.store.activate_guard(
            activation_receipt_id="activation:runtime", guard_candidate_id="guard:1",
            approval_receipt_id=approval["approvalReceiptId"], eval_run_ids=eval_ids,
            now_ms=100, config_signature=signature,
        )

    def _evidence_counts(self):
        with sqlite3.connect(self.db) as conn:
            return tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("room_v2_incidents", "room_v2_incident_occurrences", "room_v2_guard_candidates")
            )


if __name__ == "__main__":
    unittest.main()
