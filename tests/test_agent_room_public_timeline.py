from __future__ import annotations

import unittest
from typing import Any

from rag_ime.agent_room_public_timeline import RoomPublicTimelineProjector


class _RecordingEventHub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish_projection(self, **values: Any) -> dict[str, object]:
        self.calls.append(values)
        return {
            "eventType": values["event_type"],
            "payload": values["payload"],
        }


class RoomPublicTimelineProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room_id = "room:1"
        self.events = _RecordingEventHub()
        self.projector = RoomPublicTimelineProjector(self.events)  # type: ignore[arg-type]

    def test_published_event_excludes_context_journal_evidence(self) -> None:
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:1",
            "roomId": self.room_id,
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "participant:1",
            "kind": "result",
            "visibility": "room",
            "content": "正式交付",
            "idempotencyKey": "post:1",
            "publicationSource": {"kind": "room_commit", "ref": "commit:1"},
            "createdAtMs": 2,
            "contentHash": "private-hash",
            "contextEntry": {"entryId": "private-entry"},
        }

        event = self.projector.publish_post(
            post,
            participant_id="participant:1",
            source_session_id="session:1",
        )

        self.assertIsNotNone(event)
        projected = event["payload"]["post"]
        self.assertEqual(projected["content"], "正式交付")
        self.assertEqual(projected["dispatchId"], "dispatch:1")
        self.assertNotIn("contentHash", projected)
        self.assertNotIn("contextEntry", projected)

    def test_post_after_root_terminal_is_not_projected(self) -> None:
        projector = RoomPublicTimelineProjector(  # type: ignore[arg-type]
            self.events,
            root_is_terminal=lambda root_id: root_id == "root:1",
        )
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:late",
            "roomId": self.room_id,
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "participant:1",
            "kind": "result",
            "visibility": "room",
            "content": "迟到交付",
            "idempotencyKey": "post:late",
            "publicationSource": {"kind": "room_commit", "ref": "commit:late"},
            "createdAtMs": 3,
        }

        event = projector.publish_post(
            post,
            participant_id="participant:1",
            source_session_id="session:1",
        )

        self.assertIsNone(event)
        self.assertEqual(self.events.calls, [])


if __name__ == "__main__":
    unittest.main()
