from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_command_receipts import (
    AgentCommandReceiptConflict,
    AgentCommandReceiptFailed,
    AgentCommandReceiptPending,
    AgentCommandReceiptStore,
    AgentTurnConflictError,
)


class AgentCommandReceiptStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(
            prefix="agent-command-receipts-"
        )
        self.store = AgentCommandReceiptStore(
            Path(self.tmp.name) / "agent.sqlite"
        )
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_projects_pending_accepted_failed_and_conflict_receipts(
        self,
    ) -> None:
        payload = {"message": "同一条消息", "attachments": []}
        claim = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-1",
            client_message_id="client-1",
            payload=payload,
        )

        with self.assertRaises(AgentCommandReceiptPending) as pending:
            self.store.begin(
                command_scope="session_prompt",
                scope_id="session-1",
                client_message_id="client-1",
                payload=payload,
            )
        self.assertEqual(
            pending.exception.response_payload(),
            {
                "code": "AGENT_COMMAND_PENDING",
                "commandReceipt": {
                    "state": "pending",
                    "clientMessageId": "client-1",
                    "recoveryState": "in_flight",
                },
            },
        )

        accepted = self.store.complete(
            claim,
            command_scope="session_prompt",
            scope_id="session-1",
            client_message_id="client-1",
            response={
                "ok": True,
                "commandReceipt": {
                    "state": "accepted",
                    "clientMessageId": "client-1",
                },
            },
        )
        replay = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-1",
            client_message_id="client-1",
            payload=payload,
        )
        self.assertEqual(replay.replay_response, accepted)

        with self.assertRaises(AgentCommandReceiptConflict) as conflict:
            self.store.begin(
                command_scope="session_prompt",
                scope_id="session-1",
                client_message_id="client-1",
                payload={"message": "不同消息", "attachments": []},
            )
        self.assertEqual(
            conflict.exception.response_payload()[
                "commandReceipt"
            ]["state"],
            "conflict",
        )

        failed_claim = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-1",
            client_message_id="client-failed",
            payload=payload,
        )
        source_error = AgentTurnConflictError(
            "another turn still owns the Session"
        )
        self.store.fail(
            failed_claim,
            command_scope="session_prompt",
            scope_id="session-1",
            client_message_id="client-failed",
            error=source_error,
            cause_code=source_error.error_code,
        )
        reopened = AgentCommandReceiptStore(
            self.store.db_path
        )
        reopened.initialize()
        with self.assertRaises(AgentCommandReceiptFailed) as failed:
            reopened.begin(
                command_scope="session_prompt",
                scope_id="session-1",
                client_message_id="client-failed",
                payload=payload,
            )
        self.assertEqual(
            failed.exception.response_payload(),
            {
                "code": "AGENT_COMMAND_FAILED",
                "commandReceipt": {
                    "state": "failed",
                    "clientMessageId": "client-failed",
                    "causeCode": "AGENT_TURN_CONFLICT",
                },
            },
        )
        self.assertEqual(
            reopened.failure_evidence_for_exact_command(
                command_scope="session_prompt",
                scope_id="session-1",
                client_message_id="client-failed",
            ),
            {
                "schemaVersion": "rag-ime.agent-command-failure.v1",
                "message": "another turn still owns the Session",
                "causeCode": "AGENT_TURN_CONFLICT",
            },
        )
        self.assertIsNone(
            reopened.failure_evidence_for_exact_command(
                command_scope="session_prompt",
                scope_id="session-1",
                client_message_id="client-1",
            )
        )

    def test_stale_pending_is_typed_unresolved_and_never_reclaimed(
        self,
    ) -> None:
        store = AgentCommandReceiptStore(
            self.store.db_path,
            pending_recovery_grace_ms=0,
        )
        payload = {"message": "可能已经执行", "attachments": []}
        original = store.begin(
            command_scope="session_prompt",
            scope_id="session-stale",
            client_message_id="client-stale",
            payload=payload,
        )

        with self.assertRaises(
            AgentCommandReceiptPending
        ) as pending:
            store.begin(
                command_scope="session_prompt",
                scope_id="session-stale",
                client_message_id="client-stale",
                payload=payload,
            )

        self.assertFalse(original.is_replay)
        self.assertEqual(
            pending.exception.response_payload(),
            {
                "code": "AGENT_COMMAND_PENDING",
                "commandReceipt": {
                    "state": "pending",
                    "clientMessageId": "client-stale",
                    "recoveryState": "unresolved",
                },
            },
        )

    def test_durable_evidence_can_terminalize_pending_once(
        self,
    ) -> None:
        payload = {"message": "已被 Pi 接受", "attachments": []}
        claim = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-recovered",
            client_message_id="client-recovered",
            payload=payload,
        )
        recovered = {
            "ok": True,
            "turnId": "turn-recovered",
            "commandReceipt": {
                "state": "accepted",
                "clientMessageId": "client-recovered",
                "recoveredFromDurableEvent": True,
            },
        }

        accepted = self.store.accept_pending_from_evidence(
            command_scope="session_prompt",
            scope_id="session-recovered",
            client_message_id="client-recovered",
            payload=payload,
            response=recovered,
        )
        late_completion = self.store.complete(
            claim,
            command_scope="session_prompt",
            scope_id="session-recovered",
            client_message_id="client-recovered",
            response={"ok": True, "turnId": "late"},
        )
        replay = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-recovered",
            client_message_id="client-recovered",
            payload=payload,
        )

        self.assertEqual(accepted, recovered)
        self.assertEqual(late_completion, recovered)
        self.assertEqual(replay.replay_response, recovered)

    def test_exact_command_lookup_returns_content_free_prompt_acceptance(
        self,
    ) -> None:
        payload = {"message": "Room Partner task", "attachments": []}
        claim = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-partner",
            client_message_id="room-child:receipt-window",
            payload=payload,
        )
        self.store.record_acceptance_evidence(
            claim,
            command_scope="session_prompt",
            scope_id="session-partner",
            client_message_id="room-child:receipt-window",
            accepted={
                "turnId": "turn:partner-accepted",
                "piEntryId": "pi:entry:accepted",
            },
        )

        evidence = self.store.acceptance_evidence_for_exact_command(
            command_scope="session_prompt",
            scope_id="session-partner",
            client_message_id="room-child:receipt-window",
        )

        self.assertEqual(
            evidence,
            {
                "schemaVersion": "rag-ime.agent-command-acceptance-evidence.v1",
                "accepted": True,
                "clientMessageId": "room-child:receipt-window",
                "turnId": "turn:partner-accepted",
                "piEntryId": "pi:entry:accepted",
            },
        )

    def test_retry_lineage_requires_failed_equivalent_unique_predecessor(
        self,
    ) -> None:
        base = {
            "message": "同一语义输入",
            "attachments": [],
            "retryOfClientMessageId": "",
        }
        with self.assertRaises(AgentCommandReceiptConflict):
            self.store.begin(
                command_scope="session_prompt",
                scope_id="missing",
                client_message_id="retry-2",
                payload={
                    **base,
                    "retryOfClientMessageId": "retry-1",
                },
            )

        pending = self.store.begin(
            command_scope="session_prompt",
            scope_id="pending",
            client_message_id="retry-1",
            payload=base,
        )
        self.assertFalse(pending.is_replay)
        with self.assertRaises(AgentCommandReceiptConflict):
            self.store.begin(
                command_scope="session_prompt",
                scope_id="pending",
                client_message_id="retry-2",
                payload={
                    **base,
                    "retryOfClientMessageId": "retry-1",
                },
            )

        accepted = self.store.begin(
            command_scope="session_prompt",
            scope_id="accepted",
            client_message_id="retry-1",
            payload=base,
        )
        self.store.complete(
            accepted,
            command_scope="session_prompt",
            scope_id="accepted",
            client_message_id="retry-1",
            response={"ok": True},
        )
        with self.assertRaises(AgentCommandReceiptConflict):
            self.store.begin(
                command_scope="session_prompt",
                scope_id="accepted",
                client_message_id="retry-2",
                payload={
                    **base,
                    "retryOfClientMessageId": "retry-1",
                },
            )

        failed = self.store.begin(
            command_scope="session_prompt",
            scope_id="failed",
            client_message_id="retry-1",
            payload=base,
        )
        self.store.fail(
            failed,
            command_scope="session_prompt",
            scope_id="failed",
            client_message_id="retry-1",
            error=RuntimeError("safe pre-accept rejection"),
        )
        successor = self.store.begin(
            command_scope="session_prompt",
            scope_id="failed",
            client_message_id="retry-2",
            payload={
                **base,
                "retryOfClientMessageId": "retry-1",
            },
        )
        self.assertFalse(successor.is_replay)
        with self.assertRaises(AgentCommandReceiptConflict):
            self.store.begin(
                command_scope="session_prompt",
                scope_id="failed",
                client_message_id="retry-3",
                payload={
                    **base,
                    "retryOfClientMessageId": "retry-1",
                },
            )

        mismatched = self.store.begin(
            command_scope="session_prompt",
            scope_id="mismatch",
            client_message_id="retry-1",
            payload=base,
        )
        self.store.fail(
            mismatched,
            command_scope="session_prompt",
            scope_id="mismatch",
            client_message_id="retry-1",
            error=RuntimeError("safe pre-accept rejection"),
        )
        with self.assertRaises(AgentCommandReceiptConflict):
            self.store.begin(
                command_scope="session_prompt",
                scope_id="mismatch",
                client_message_id="retry-2",
                payload={
                    **base,
                    "message": "changed",
                    "retryOfClientMessageId": "retry-1",
                },
            )

    def test_delivery_fallback_is_a_new_command_not_an_exact_replay(
        self,
    ) -> None:
        steer_payload = {
            "message": "继续处理",
            "attachments": [],
            "delivery": "steer",
            "retryOfClientMessageId": "",
        }
        failed_steer = self.store.begin(
            command_scope="session_prompt",
            scope_id="delivery-fallback",
            client_message_id="steer-1",
            payload=steer_payload,
        )
        self.store.fail(
            failed_steer,
            command_scope="session_prompt",
            scope_id="delivery-fallback",
            client_message_id="steer-1",
            error=RuntimeError("Session is idle"),
            cause_code="SESSION_IDLE",
        )

        with self.assertRaises(AgentCommandReceiptConflict) as same_id:
            self.store.begin(
                command_scope="session_prompt",
                scope_id="delivery-fallback",
                client_message_id="steer-1",
                payload={
                    **steer_payload,
                    "delivery": "prompt",
                },
            )
        self.assertEqual(
            same_id.exception.response_payload(),
            {
                "code": "AGENT_COMMAND_CONFLICT",
                "commandReceipt": {
                    "state": "conflict",
                    "clientMessageId": "steer-1",
                    "recoveryState": "new_command_required",
                },
            },
        )

        with self.assertRaises(AgentCommandReceiptConflict) as lineage:
            self.store.begin(
                command_scope="session_prompt",
                scope_id="delivery-fallback",
                client_message_id="prompt-with-lineage",
                payload={
                    **steer_payload,
                    "delivery": "prompt",
                    "retryOfClientMessageId": "steer-1",
                },
            )
        self.assertEqual(
            lineage.exception.recovery_state,
            "new_command_required",
        )

        new_prompt = self.store.begin(
            command_scope="session_prompt",
            scope_id="delivery-fallback",
            client_message_id="prompt-2",
            payload={
                **steer_payload,
                "delivery": "prompt",
            },
        )
        self.assertFalse(new_prompt.is_replay)

    def test_acceptance_evidence_fences_failure_and_fail_replays_winner(
        self,
    ) -> None:
        payload = {"message": "accepted", "attachments": []}
        claim = self.store.begin(
            command_scope="session_prompt",
            scope_id="session-evidence",
            client_message_id="client-evidence",
            payload=payload,
        )
        stored = self.store.record_acceptance_evidence(
            claim,
            command_scope="session_prompt",
            scope_id="session-evidence",
            client_message_id="client-evidence",
            accepted={
                "turnId": "turn-evidence",
                "piEntryId": "pi-evidence",
            },
        )
        self.assertEqual(
            self.store.pending_acceptance_evidence(
                command_scope="session_prompt",
                scope_id="session-evidence",
                client_message_id="client-evidence",
                payload=payload,
            ),
            stored,
        )
        with self.assertRaises(AgentCommandReceiptPending):
            self.store.fail(
                claim,
                command_scope="session_prompt",
                scope_id="session-evidence",
                client_message_id="client-evidence",
                error=RuntimeError("late projection failed"),
            )
        accepted = self.store.accept_pending_from_evidence(
            command_scope="session_prompt",
            scope_id="session-evidence",
            client_message_id="client-evidence",
            payload=payload,
            response={"ok": True, "turnId": "turn-evidence"},
        )
        self.assertEqual(
            self.store.fail(
                claim,
                command_scope="session_prompt",
                scope_id="session-evidence",
                client_message_id="client-evidence",
                error=RuntimeError("losing failure writer"),
            ),
            accepted,
        )


if __name__ == "__main__":
    unittest.main()
