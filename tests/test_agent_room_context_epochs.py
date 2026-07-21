from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_context_epochs import (
    RoomContextEpochConflict,
    RoomSessionContextEpochStore,
)
from rag_ime.agent_sessions import AgentSessionStore


class RoomSessionContextEpochStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-context-epochs-")
        self.db_path = Path(self.tmp.name) / "room.sqlite"
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        self.session_id = str(sessions.create(title="Epoch test")["id"])
        self.store = RoomSessionContextEpochStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dispatch_reuses_root_epoch_and_task_switch_advances(self) -> None:
        first = self.store.prepare_dispatch(
            session_id=self.session_id, root_id="root:1", generation=0,
            dispatch_id="dispatch:1", now_ms=1,
        )
        same_root = self.store.prepare_dispatch(
            session_id=self.session_id, root_id="root:1", generation=0,
            dispatch_id="dispatch:2", now_ms=2,
        )
        switched = self.store.prepare_dispatch(
            session_id=self.session_id, root_id="root:2", generation=0,
            dispatch_id="dispatch:3", now_ms=3,
        )

        self.assertEqual((first["toEpoch"], first["epochReason"]), (1, "session_open"))
        self.assertEqual(same_root["toEpoch"], 1)
        self.assertFalse(same_root["epochChanged"])
        self.assertEqual((switched["toEpoch"], switched["epochReason"]), (2, "task_switch"))

    def test_compaction_is_idempotent_and_records_exact_provider_hashes(self) -> None:
        self.store.prepare_dispatch(
            session_id=self.session_id, root_id="root:1", generation=0,
            dispatch_id="dispatch:1", now_ms=1,
        )
        recovery = json.dumps(
            {
                "schemaVersion": "wisdom-weasel.room-compaction-recovery.v1",
                "originalRequirements": ["original"],
                "currentTask": {"objective": "task"},
                "acceptance": [{"statement": "accept"}],
                "blockers": [{"statement": "blocked"}],
                "handoff": {"intentKind": "resume"},
                "skillReceipt": {"restoredFromReceiptId": "skill:1"},
                "toolReceipt": {"items": [{"receiptId": "tool:1"}]},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        first = self.store.advance_compaction(
            session_id=self.session_id, compaction_entry_id="compact:1",
            expected_epoch=1, room_recovery_context=recovery,
            session_context="session memory", now_ms=2,
        )
        replay = self.store.advance_compaction(
            session_id=self.session_id, compaction_entry_id="compact:1",
            expected_epoch=1, room_recovery_context=recovery,
            session_context="session memory", now_ms=3,
        )

        self.assertEqual(first, replay)
        self.assertEqual(first["toEpoch"], 2)
        self.assertEqual(first["evidence"]["originalRequirementCount"], 1)
        self.assertEqual(first["evidence"]["skillReceiptId"], "skill:1")
        self.assertEqual(first["evidence"]["toolReceiptIds"], ["tool:1"])
        with self.assertRaisesRegex(RoomContextEpochConflict, "stale"):
            self.store.advance_compaction(
                session_id=self.session_id, compaction_entry_id="compact:2",
                expected_epoch=1, room_recovery_context=recovery,
                session_context="session memory", now_ms=4,
            )


if __name__ == "__main__":
    unittest.main()
