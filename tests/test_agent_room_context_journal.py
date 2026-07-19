from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_context import (
    ProjectionGenerationMismatch,
    ProviderProjectionJournalStore,
    RoomContextConflict,
    RoomContextLedgerStore,
)


class RoomContextJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-context-journal-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.context = RoomContextLedgerStore(self.db_path)
        self.journals = ProviderProjectionJournalStore(self.db_path)
        self.context.initialize()
        self.journals.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_room_post_requires_explicit_user_or_commit_publication(self) -> None:
        post = self._post()
        stored, created = self.context.publish_post(post)

        self.assertTrue(created)
        self.assertEqual(stored["content"], "结论第一行\n结论第二行  ")
        self.assertEqual(stored["publicationSource"], {"kind": "user", "ref": "user:1"})
        self.assertEqual(len(self.context.replay_root("root:1")), 1)

        for forbidden in ("message_completed", "assistant_output", "turn_completed"):
            with self.subTest(forbidden=forbidden), self.assertRaisesRegex(
                ValueError,
                "explicit user or room_commit",
            ):
                self.context.publish_post(
                    {
                        **post,
                        "postId": f"post:{forbidden}",
                        "idempotencyKey": f"post:{forbidden}",
                        "publicationSource": {"kind": forbidden, "ref": "event:1"},
                    }
                )

        with self.assertRaisesRegex(ValueError, "unsupported Room context entry kind"):
            self.context.append_entry(
                root_id="root:1",
                room_id="room:1",
                generation=3,
                entry_kind="message_completed",
                source_ref="event:assistant",
                dedupe_key="event:assistant",
                content="不能自动进入 Room",
                created_at_ms=20,
            )

    def test_room_commit_post_requires_commit_reference(self) -> None:
        with self.assertRaisesRegex(ValueError, "commit ref"):
            self.context.publish_post(
                {
                    **self._post(),
                    "publicationSource": {"kind": "room_commit", "ref": ""},
                }
            )

    def test_post_and_context_entry_are_idempotent_but_immutable(self) -> None:
        first, created = self.context.publish_post(self._post())
        repeated, repeated_created = self.context.publish_post(self._post())

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated, first)
        with self.assertRaises(RoomContextConflict):
            self.context.publish_post({**self._post(), "content": "被替换的结论"})

        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_posts").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM room_v2_context_entries").fetchone()[0],
                1,
            )

    def test_projection_is_read_only_until_provider_receipt_seals_it(self) -> None:
        entry = self.context.publish_post(self._post())[0]["contextEntry"]
        self._open_journal()
        item, created = self.journals.append_entry(
            "journal:1",
            str(entry["entryId"]),
            dedupe_key="root:1/post:1",
            expected_generation=3,
            appended_at_ms=20,
        )

        self.assertTrue(created)
        before_send = self.journals.projection("journal:1", expected_generation=3)
        replayed = self.journals.projection("journal:1", expected_generation=3)
        self.assertEqual(replayed, before_send)
        self.assertEqual(before_send["sealedPrefix"], [])
        self.assertEqual([value["sequence"] for value in before_send["pendingTail"]], [1])
        self.assertEqual(item["state"], "pending")
        with sqlite3.connect(self.db_path) as conn:
            state = conn.execute(
                "SELECT state FROM room_v2_provider_projection_items"
            ).fetchone()[0]
        self.assertEqual(state, "pending")

        receipt, receipt_created = self.journals.record_provider_receipt(
            "journal:1",
            receipt_id="provider-receipt:1",
            provider_request_id="provider-request:1",
            through_sequence=int(before_send["throughSequence"]),
            projection_hash=str(before_send["projectionHash"]),
            expected_generation=3,
            created_at_ms=30,
        )
        self.assertTrue(receipt_created)
        self.assertEqual(receipt["sealedThroughSequence"], 1)
        after_receipt = self.journals.projection("journal:1", expected_generation=3)
        self.assertEqual(after_receipt["pendingTail"], [])
        self.assertEqual([value["sequence"] for value in after_receipt["sealedPrefix"]], [1])

    def test_crash_before_receipt_replays_pending_bytes_exactly(self) -> None:
        content = "第一段\n  保留开头空格\n尾部空格  "
        entry, _ = self.context.append_entry(
            root_id="root:1",
            room_id="room:1",
            generation=3,
            entry_kind="control_receipt",
            source_ref="event:1",
            dedupe_key="event:1",
            content=content,
            created_at_ms=10,
        )
        self._open_journal()
        self.journals.append_entry(
            "journal:1",
            str(entry["entryId"]),
            dedupe_key="event:1",
            expected_generation=3,
            appended_at_ms=20,
        )
        sent = self.journals.projection("journal:1", expected_generation=3)

        restarted = ProviderProjectionJournalStore(self.db_path)
        restarted.initialize()
        replayed = restarted.projection("journal:1", expected_generation=3)

        self.assertEqual(replayed["projectionBytes"], sent["projectionBytes"])
        self.assertEqual(replayed["projectionHash"], sent["projectionHash"])
        self.assertEqual(replayed["pendingTail"][0]["content"], content)

    def test_crash_after_receipt_replays_sealed_prefix_and_receipt_idempotently(self) -> None:
        entry = self.context.publish_post(self._post())[0]["contextEntry"]
        self._open_journal()
        self.journals.append_entry(
            "journal:1",
            str(entry["entryId"]),
            dedupe_key="post:1",
            expected_generation=3,
            appended_at_ms=20,
        )
        sent = self.journals.projection("journal:1", expected_generation=3)
        receipt_args = {
            "receipt_id": "provider-receipt:stable",
            "provider_request_id": "provider-request:stable",
            "through_sequence": int(sent["throughSequence"]),
            "projection_hash": str(sent["projectionHash"]),
            "expected_generation": 3,
            "created_at_ms": 30,
        }
        self.journals.record_provider_receipt("journal:1", **receipt_args)

        restarted = ProviderProjectionJournalStore(self.db_path)
        restarted.initialize()
        repeated, created = restarted.record_provider_receipt("journal:1", **receipt_args)
        projection = restarted.projection("journal:1", expected_generation=3)

        self.assertFalse(created)
        self.assertEqual(repeated["receiptId"], "provider-receipt:stable")
        self.assertEqual(projection["pendingTail"], [])
        self.assertEqual(projection["sealedPrefix"][0]["content"], self._post()["content"])

    def test_new_tail_after_send_does_not_invalidate_receipt_for_sent_prefix(self) -> None:
        first = self.context.publish_post(self._post())[0]["contextEntry"]
        second, _ = self.context.append_entry(
            root_id="root:1",
            room_id="room:1",
            generation=3,
            entry_kind="task_state",
            source_ref="event:2",
            dedupe_key="event:2",
            content="任务状态已变化",
            created_at_ms=15,
        )
        self._open_journal()
        self.journals.append_entry(
            "journal:1",
            str(first["entryId"]),
            dedupe_key="post:1",
            expected_generation=3,
            appended_at_ms=20,
        )
        sent = self.journals.projection("journal:1", expected_generation=3)
        self.journals.append_entry(
            "journal:1",
            str(second["entryId"]),
            dedupe_key="event:2",
            expected_generation=3,
            appended_at_ms=25,
        )

        self.journals.record_provider_receipt(
            "journal:1",
            receipt_id="provider-receipt:prefix",
            provider_request_id="provider-request:prefix",
            through_sequence=int(sent["throughSequence"]),
            projection_hash=str(sent["projectionHash"]),
            expected_generation=3,
            created_at_ms=30,
        )
        final = self.journals.projection("journal:1", expected_generation=3)

        self.assertEqual([value["sequence"] for value in final["sealedPrefix"]], [1])
        self.assertEqual([value["sequence"] for value in final["pendingTail"]], [2])

    def test_generation_fences_append_projection_and_receipt(self) -> None:
        entry = self.context.publish_post(self._post())[0]["contextEntry"]
        self._open_journal()
        with self.assertRaises(ProjectionGenerationMismatch):
            self.journals.append_entry(
                "journal:1",
                str(entry["entryId"]),
                dedupe_key="post:1",
                expected_generation=2,
                appended_at_ms=20,
            )
        with self.assertRaises(ProjectionGenerationMismatch):
            self.journals.projection("journal:1", expected_generation=4)
        self.journals.append_entry(
            "journal:1",
            str(entry["entryId"]),
            dedupe_key="post:1",
            expected_generation=3,
            appended_at_ms=20,
        )
        sent = self.journals.projection("journal:1", expected_generation=3)
        with self.assertRaises(ProjectionGenerationMismatch):
            self.journals.record_provider_receipt(
                "journal:1",
                receipt_id="provider-receipt:stale",
                provider_request_id="provider-request:stale",
                through_sequence=int(sent["throughSequence"]),
                projection_hash=str(sent["projectionHash"]),
                expected_generation=4,
                created_at_ms=30,
            )

    def _open_journal(self) -> None:
        self.journals.open_journal(
            journal_id="journal:1",
            root_id="root:1",
            room_id="room:1",
            binding_id="binding:1",
            session_id="session:1",
            session_epoch=1,
            context_epoch=1,
            generation=3,
            created_at_ms=10,
        )

    @staticmethod
    def _post() -> dict[str, object]:
        return {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:1",
            "roomId": "room:1",
            "rootId": "root:1",
            "generation": 3,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "user:1",
            "kind": "finding",
            "visibility": "room",
            "content": "结论第一行\n结论第二行  ",
            "idempotencyKey": "post:1",
            "publicationSource": {"kind": "user", "ref": "user:1"},
            "createdAtMs": 10,
        }


if __name__ == "__main__":
    unittest.main()
