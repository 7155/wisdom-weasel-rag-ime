from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
            acceptance_criteria=(), now_ms=1,
        )
        self.store.create_task(task("task:1"), now_ms=2)
        self.projection = RoomKernelProjection(self.db_path)
        self.projection.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_and_event_sequence_are_stable_and_gap_requires_snapshot(self) -> None:
        first = self.projection.sync_room("room:1", now_ms=10)
        again = self.projection.sync_room("room:1", now_ms=11)
        self.assertEqual([item["sequence"] for item in first], [1, 2])
        self.assertEqual(again, [])
        snapshot = self.projection.snapshot("room:1")
        self.assertEqual(snapshot["lastSequence"], 2)
        self.assertEqual(snapshot["roots"][0]["rootId"], "root:1")
        self.assertTrue(str(snapshot["snapshotHash"]).startswith("sha256:"))

        gap = self.projection.subscribe(
            "room:1", after_event_id="room:1#99", heartbeat_seconds=0.01
        )
        chunk = next(gap).decode("utf-8")
        self.assertIn("event: snapshot_required", chunk)
        self.assertIn('"reason":"event_replay_gap"', chunk)

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

    def test_resume_token_is_room_scoped(self) -> None:
        with self.assertRaisesRegex(ValueError, "another Room"):
            next(self.projection.subscribe("room:1", after_event_id="room:2#1"))


if __name__ == "__main__":
    unittest.main()
