from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_kernel_projection import RoomKernelProjection
from tests.test_agent_room_kernel import dispatch, root, task


class RoomKernelProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-projection-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomKernelStore(self.db_path, mode="test")
        self.store.initialize()
        self.store.create_root(
            root("root:1"), budget=10, max_hops=3, max_depth=2,
            acceptance_criteria=("ac:1",), now_ms=1,
        )
        self.store.create_task(task("task:1"), now_ms=2)
        self.projection = RoomKernelProjection(self.db_path)
        self.projection.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_and_event_sequence_are_stable_and_gap_requires_snapshot(self) -> None:
        first = self.projection.sync_room("room:1", now_ms=10)
        again = self.projection.sync_room("room:1", now_ms=11)
        self.assertEqual([item["sequence"] for item in first], [1, 2, 3, 4])
        self.assertEqual(first[-1]["entityKind"], "projection")
        self.assertEqual(first[-1]["eventKind"], "screen_state_changed")
        self.assertEqual(again, [])
        snapshot = self.projection.snapshot("room:1")
        self.assertEqual(snapshot["lastSequence"], 4)
        self.assertEqual(snapshot["roots"][0]["rootId"], "root:1")
        self.assertEqual(snapshot["taskUpdatedAtMsById"], {"task:1": 2})
        self.assertEqual(
            snapshot["screenState"],
            {
                "schemaVersion": "wisdom-weasel.room-screen-state.v1",
                "roomId": "room:1",
                "activeRootId": "root:1",
                "activeRootGeneration": 0,
                "phase": "execution",
                "waitReason": None,
                "runnableFrontier": {"taskIds": [], "dispatchIds": []},
                "integrationReadiness": {
                    "ready": True,
                    "reason": None,
                    "pendingTaskIds": [],
                },
                "reviewReadiness": {
                    "ready": True,
                    "reason": None,
                    "pendingTaskIds": [],
                },
                "finalDeliveryPostId": None,
                "recommendedNextAction": "wait_for_progress",
            },
        )
        self.assertTrue(str(snapshot["snapshotHash"]).startswith("sha256:"))

        gap = self.projection.subscribe(
            "room:1", after_event_id="room:1#99", heartbeat_seconds=0.01
        )
        chunk = next(gap).decode("utf-8")
        self.assertIn("event: snapshot_required", chunk)
        self.assertIn('"reason":"event_replay_gap"', chunk)

    def test_sync_room_snapshot_materializes_the_room_once(self) -> None:
        self.store.create_root(
            root("root:2"), budget=10, max_hops=3, max_depth=2,
            acceptance_criteria=("ac:2",), now_ms=3,
        )
        self.store.create_task(
            task("task:2", root_id="root:2", criteria=("ac:2",)),
            now_ms=4,
        )

        with patch.object(
            self.projection,
            "_records",
            wraps=self.projection._records,
        ) as records:
            emitted, snapshot = self.projection.sync_room_snapshot(
                "room:1",
                now_ms=10,
            )

        self.assertEqual(records.call_count, 1)
        self.assertEqual(
            {item["rootId"] for item in snapshot["roots"]},
            {"root:1", "root:2"},
        )
        self.assertEqual(snapshot["lastSequence"], emitted[-1]["sequence"])

    def test_only_explicit_post_is_projected_and_private_session_contains_no_text(self) -> None:
        self.store.enqueue_dispatch(dispatch("dispatch:1", key="projection:1"), now_ms=3)
        self.projection.publish_post(
            {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:1",
                "roomId": "room:1",
                "rootId": "root:1",
                "generation": 0,
                "taskId": "task:1",
                "dispatchId": "dispatch:1",
                "authorActorRef": "participant:a",
                "kind": "result",
                "visibility": "room",
                "content": "Explicit delivery only.",
                "idempotencyKey": "post:projection:1",
                "publicationSource": {"kind": "room_commit", "ref": "commit:1"},
                "createdAtMs": 4,
            }
        )
        self.projection.sync_room("room:1", now_ms=5)
        snapshot = self.projection.snapshot("room:1")

        self.assertEqual([post["postId"] for post in snapshot["posts"]], ["post:1"])
        encoded_session = json.dumps(snapshot["sessions"], ensure_ascii=False)
        self.assertNotIn("Explicit delivery", encoded_session)
        self.assertEqual(snapshot["sessions"][0]["state"], "queued")

    def test_backend_selects_the_active_root_instead_of_leaving_it_to_ui_ordering(self) -> None:
        self.store.create_root(
            root("root:2"), budget=10, max_hops=3, max_depth=2,
            acceptance_criteria=("ac:2",), now_ms=20,
        )
        self.store.create_task(
            task("task:2", root_id="root:2", criteria=("ac:2",)),
            now_ms=21,
        )

        screen = self.projection.snapshot("room:1")["screenState"]

        self.assertEqual(screen["activeRootId"], "root:2")
        self.assertEqual(screen["activeRootGeneration"], 0)

    def test_completed_root_does_not_promote_the_last_result_without_report_receipt(self) -> None:
        self.projection.publish_post(
            {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:unproven-final",
                "roomId": "room:1",
                "rootId": "root:1",
                "generation": 0,
                "taskId": "task:1",
                "authorActorRef": "participant:a",
                "kind": "result",
                "visibility": "room",
                "content": "Looks final but has no reporter terminal authority.",
                "idempotencyKey": "post:unproven-final",
                "publicationSource": {
                    "kind": "room_commit",
                    "ref": "commit:unproven-final",
                },
                "createdAtMs": 30,
            }
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE room_kernel_roots
                   SET state='completed',reporter_participant_id=?,updated_at_ms=?
                   WHERE root_id=?""",
                ("participant:a", 31, "root:1"),
            )

        screen = self.projection.snapshot("room:1")["screenState"]

        self.assertEqual(screen["phase"], "completed")
        self.assertIsNone(screen["finalDeliveryPostId"])

    def test_resume_token_is_room_scoped(self) -> None:
        with self.assertRaisesRegex(ValueError, "another Room"):
            next(self.projection.subscribe("room:1", after_event_id="room:2#1"))


if __name__ == "__main__":
    unittest.main()
