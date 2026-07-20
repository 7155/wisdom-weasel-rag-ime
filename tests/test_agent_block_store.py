from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_block_store import AgentBlockConflict, AgentBlockStore
from rag_ime.agent_blocks import normalize_trusted_agent_blocks


class AgentBlockStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "blocks.sqlite"
        self.store = AgentBlockStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def message(self, *, generation: int = 2) -> dict[str, object]:
        blocks = normalize_trusted_agent_blocks(
            [{"id": "table:1", "type": "table", "data": {"title": "结果", "columns": ["项"], "rows": [["raw"]]}}],
            source_kind="pi_runtime_event",
            source_ref="message:1",
            generation=generation,
        )
        return {
            "schemaVersion": "rag-ime.agent-message.v1",
            "id": "message:1",
            "sessionId": "session:1",
            "turnId": "turn:1",
            "role": "assistant",
            "status": "completed",
            "blocks": list(blocks),
            "attachments": [],
            "citations": [],
            "createdAtMs": 1,
        }

    def test_persists_rerender_data_and_projection_receipt(self) -> None:
        receipt = self.store.persist_message(
            self.message(), root_id="root:1", task_id="task:1",
            invocation_id="dispatch:1", generation=2, created_at_ms=10,
        )
        self.assertEqual(receipt["blockCount"], 1)
        self.assertGreater(receipt["beforeBytes"], receipt["afterBytes"])
        blocks = self.store.blocks_for_message("session:1", "message:1", generation=2)
        self.assertEqual(blocks[0]["data"]["rows"], [["raw"]])
        self.assertEqual(blocks[0]["visibility"], "private_session")

    def test_dedupe_conflict_revoke_and_cancel_generation(self) -> None:
        message = self.message()
        first = self.store.persist_message(message, root_id="root:1", generation=2, created_at_ms=10)
        replay = self.store.persist_message(message, root_id="root:1", generation=2, created_at_ms=11)
        self.assertEqual(first["projectionHash"], replay["projectionHash"])
        block_ref = str(self.store.blocks_for_message("session:1", "message:1", generation=2)[0]["ref"])
        self.assertFalse(self.store.revoke(block_ref, root_id="root:other", session_id="session:1", now_ms=12))
        self.assertTrue(self.store.revoke(block_ref, root_id="root:1", session_id="session:1", now_ms=12))
        self.assertEqual(self.store.blocks_for_message("session:1", "message:1"), [])

        second = self.message(generation=3)
        second["id"] = "message:2"
        second["blocks"][0]["id"] = "table:2"
        # New server identity must also carry a distinct ref/digest, so create it afresh.
        second["blocks"] = list(normalize_trusted_agent_blocks(
            [{"id": "table:2", "type": "table", "data": {"title": "结果", "columns": ["项"], "rows": [["raw"]]}}],
            source_kind="pi_runtime_event", source_ref="message:2", generation=3,
        ))
        self.store.persist_message(second, root_id="root:1", generation=3, created_at_ms=13)
        # Completed history remains rerenderable; Root cancellation fences stale
        # future writes rather than erasing already completed Session output.
        self.assertEqual(self.store.cancel_generation("root:1", 3, now_ms=14), 0)
        self.assertEqual(len(self.store.blocks_for_message("session:1", "message:2")), 1)

    def test_message_envelope_replay_is_atomic_and_cannot_partially_append(self) -> None:
        message = self.message()
        self.store.persist_message(message, root_id="root:1", generation=2, created_at_ms=10)
        expanded = json.loads(json.dumps(message))
        expanded["blocks"] = [
            *expanded["blocks"],
            *normalize_trusted_agent_blocks(
                [{"id": "status:2", "type": "status", "data": {"title": "late"}}],
                source_kind="pi_runtime_event", source_ref="message:1", generation=2,
            ),
        ]
        with self.assertRaisesRegex(AgentBlockConflict, "envelope"):
            self.store.persist_message(expanded, root_id="root:1", generation=2, created_at_ms=11)
        blocks = self.store.blocks_for_message("session:1", "message:1", generation=2)
        self.assertEqual([block["id"] for block in blocks], ["table:1"])

    def test_hydrates_runtime_messages_and_recovers_missing_compacted_envelope(self) -> None:
        message = self.message()
        text_block = {
            "id": "text:1", "type": "text", "status": "completed",
            "presentationKind": "markdown", "data": {"text": "可读结论"},
        }
        message["blocks"] = [text_block, *message["blocks"]]
        self.store.persist_message(message, root_id="root:1", generation=2, created_at_ms=10)

        hydrated = self.store.hydrate_messages("session:1", [{**message, "blocks": [text_block]}])
        self.assertEqual([block["type"] for block in hydrated[0]["blocks"]], ["text", "table"])
        recovered = self.store.hydrate_messages("session:1", [])
        self.assertEqual(recovered, hydrated)
        self.assertEqual(recovered[0]["blocks"][1]["data"]["rows"], [["raw"]])

        newer = {
            "schemaVersion": "rag-ime.agent-message.v1",
            "id": "message:2",
            "sessionId": "session:1",
            "turnId": "turn:2",
            "role": "assistant",
            "status": "completed",
            "blocks": [text_block],
            "attachments": [],
            "citations": [],
            "createdAtMs": 20,
        }
        merged = self.store.hydrate_messages("session:1", [newer])
        self.assertEqual([item["id"] for item in merged], ["message:1", "message:2"])

    def test_hydration_preserves_runtime_order_when_timestamps_are_reversed_or_equal(self) -> None:
        first = {
            **self.message(),
            "id": "runtime:first",
            "blocks": [],
            "createdAtMs": 200,
        }
        second = {
            **self.message(),
            "id": "runtime:second",
            "blocks": [],
            "createdAtMs": 100,
        }
        third = {
            **self.message(),
            "id": "runtime:third",
            "blocks": [],
            "createdAtMs": 100,
        }

        hydrated = self.store.hydrate_messages(
            "session:1", [first, second, third]
        )

        self.assertEqual(
            [message["id"] for message in hydrated],
            ["runtime:first", "runtime:second", "runtime:third"],
        )

    def test_exact_replay_does_not_double_count_root_budget(self) -> None:
        message = self.message()
        first = self.store.persist_message(
            message, root_id="root:1", generation=2, created_at_ms=10
        )
        with patch(
            "rag_ime.agent_block_store.MAX_ROOT_BLOCK_BYTES", first["beforeBytes"]
        ):
            replay = self.store.persist_message(
                message, root_id="root:1", generation=2, created_at_ms=11
            )
        self.assertEqual(replay, first)

    def test_same_ref_cannot_be_rebound(self) -> None:
        message = self.message()
        self.store.persist_message(message, root_id="root:1", generation=2, created_at_ms=10)
        mutated = json.loads(json.dumps(message))
        mutated["blocks"] = list(normalize_trusted_agent_blocks(
            [{"id": "table:1", "type": "table", "data": {"title": "结果", "columns": ["项"], "rows": [["changed"]]}}],
            source_kind="pi_runtime_event", source_ref="session:1:message:1", generation=2,
        ))
        with self.assertRaises(AgentBlockConflict):
            self.store.persist_message(mutated, root_id="root:1", generation=2, created_at_ms=11)

    def test_same_local_id_is_isolated_across_sessions_for_equal_or_different_data(self) -> None:
        first = self.message()
        self.store.persist_message(first, root_id="root:1", generation=2, created_at_ms=10)
        for session_id, rows in (("session:2", [["raw"]]), ("session:3", [["different"]])):
            message_id = f"message:{session_id[-1]}"
            message = {
                **self.message(),
                "id": message_id,
                "sessionId": session_id,
                "blocks": list(normalize_trusted_agent_blocks(
                    [{"id": "table:1", "type": "table", "data": {"title": "结果", "columns": ["项"], "rows": rows}}],
                    source_kind="pi_runtime_event", source_ref=f"{session_id}:{message_id}", generation=2,
                )),
            }
            self.store.persist_message(message, root_id=f"root:{session_id[-1]}", generation=2, created_at_ms=11)
            self.assertEqual(self.store.blocks_for_message(session_id, message_id)[0]["data"]["rows"], rows)

        refs = {
            self.store.blocks_for_message(session, message)[0]["ref"]
            for session, message in (("session:1", "message:1"), ("session:2", "message:2"), ("session:3", "message:3"))
        }
        self.assertEqual(len(refs), 3)


if __name__ == "__main__":
    unittest.main()
