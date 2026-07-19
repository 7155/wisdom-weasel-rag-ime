from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_room_store import (
    RoomShadowLedgerStore,
    ShadowObservationConflict,
)


class RoomShadowLedgerStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-shadow-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomShadowLedgerStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_canonical_edge_from_multiple_legacy_paths_is_one_record(self) -> None:
        observation = self._dispatch_observation()

        first, created = self.store.record_observation(
            observation,
            source_kind="user_message",
            source_id="room-event:1",
            observed_at_ms=10,
        )
        repeated, repeated_created = self.store.record_observation(
            observation,
            source_kind="intercom",
            source_id="intercom:1",
            observed_at_ms=20,
        )

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(repeated["sequence"], 1)
        self.assertEqual(
            repeated["legacyRefs"],
            [
                {"sourceKind": "intercom", "sourceId": "intercom:1"},
                {"sourceKind": "user_message", "sourceId": "room-event:1"},
            ],
        )
        self.assertEqual(len(self.store.replay_root("root:1")), 1)

    def test_canonical_key_reuse_with_different_payload_fails_closed(self) -> None:
        observation = self._dispatch_observation()
        self.store.record_observation(
            observation,
            source_kind="work_item",
            source_id="work:1",
            observed_at_ms=10,
        )

        with self.assertRaises(ShadowObservationConflict):
            self.store.record_observation(
                {
                    **observation,
                    "payload": {**observation["payload"], "attempt": 2},
                },
                source_kind="retry",
                source_id="retry:1",
                observed_at_ms=20,
            )

        replay = self.store.replay_root("root:1")
        self.assertEqual(len(replay), 1)
        self.assertEqual(replay[0]["payload"]["attempt"], 1)
        self.assertEqual(
            replay[0]["legacyRefs"],
            [{"sourceKind": "work_item", "sourceId": "work:1"}],
        )

    def test_legacy_ref_cannot_be_rebound_and_transaction_rolls_back(self) -> None:
        first = self._dispatch_observation()
        self.store.record_observation(
            first,
            source_kind="intercom",
            source_id="intercom:stable",
            observed_at_ms=10,
        )

        with self.assertRaises(ShadowObservationConflict):
            self.store.record_observation(
                {
                    **first,
                    "dispatchId": "dispatch:2",
                    "entityId": "dispatch:2",
                    "payload": {**first["payload"], "dispatchId": "dispatch:2"},
                },
                source_kind="intercom",
                source_id="intercom:stable",
                observed_at_ms=20,
            )

        self.assertEqual(len(self.store.replay_root("root:1")), 1)

    def test_ambiguous_legacy_event_is_quarantined_without_default_root(self) -> None:
        item, created = self.store.quarantine(
            source_kind="wake",
            source_id="wake:ambiguous",
            reason_code="missing_root",
            raw_payload={"sessionId": "session:1", "message": "resume"},
            observed_at_ms=30,
        )
        repeated, repeated_created = self.store.quarantine(
            source_kind="wake",
            source_id="wake:ambiguous",
            reason_code="missing_root",
            raw_payload={"sessionId": "session:1", "message": "resume"},
            observed_at_ms=40,
        )

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated["id"], item["id"])
        self.assertEqual(repeated["rootId"], "")
        self.assertEqual(self.store.replay_root("root:default"), [])

    def test_shadow_write_has_no_provider_tool_process_or_runnable_outbox(self) -> None:
        with (
            patch("subprocess.Popen", side_effect=AssertionError("process started")),
            patch("urllib.request.urlopen", side_effect=AssertionError("network called")),
        ):
            self.store.record_observation(
                self._dispatch_observation(),
                source_kind="user_message",
                source_id="room-event:no-effects",
                observed_at_ms=10,
            )

        with sqlite3.connect(self.db_path) as conn:
            shadow_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name LIKE 'room_v2_shadow_%'"
                )
            }
        self.assertEqual(
            shadow_tables,
            {
                "room_v2_shadow_legacy_refs",
                "room_v2_shadow_observations",
                "room_v2_shadow_quarantine",
            },
        )
        self.assertFalse(any("outbox" in name or "lease" in name for name in shadow_tables))

    def test_replay_is_stable_and_append_only(self) -> None:
        first = self._dispatch_observation()
        second = {
            **first,
            "recordKind": "event",
            "entityId": "event:2",
            "payload": {"eventKind": "legacy_delivered", "source": "intercom:1"},
        }
        self.store.record_observation(
            first,
            source_kind="work_item",
            source_id="work:1",
            observed_at_ms=10,
        )
        self.store.record_observation(
            second,
            source_kind="intercom",
            source_id="intercom:1",
            observed_at_ms=20,
        )

        expected = self.store.replay_root("root:1")
        self.assertEqual([item["sequence"] for item in expected], [1, 2])
        for _ in range(100):
            self.assertEqual(self.store.replay_root("root:1"), expected)

    @staticmethod
    def _dispatch_observation() -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.room-shadow-observation.v1",
            "rootId": "root:1",
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "triggerId": "trigger:1",
            "recordKind": "dispatch",
            "entityId": "dispatch:1",
            "payload": {
                "dispatchId": "dispatch:1",
                "rootId": "root:1",
                "taskId": "task:1",
                "generation": 0,
                "targetSessionId": "session:worker",
                "targetParticipantId": "participant:worker",
                "triggerId": "trigger:1",
                "idempotencyKey": "root:1/task:1/trigger:1/participant:worker",
                "attempt": 1,
                "state": "shadow_observed",
            },
        }


if __name__ == "__main__":
    unittest.main()
