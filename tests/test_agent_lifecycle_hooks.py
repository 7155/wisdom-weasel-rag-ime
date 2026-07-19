from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_lifecycle_hooks import AgentLifecycleHookService


class AgentLifecycleHookServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-lifecycle-")
        self.service = AgentLifecycleHookService(Path(self.tmp.name) / "state.sqlite")
        self.service.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_review_events_only_queue_a_next_turn_suggestion_and_are_idempotent(self) -> None:
        payload = {
            "schemaVersion": "rag-ime.agent-lifecycle-event.v1",
            "eventId": "event-1",
            "eventType": "project_complete",
            "sessionId": "session-1",
            "project": "demo",
            "payload": {
                "facts": [{"text": "Focused tests passed", "evidence": "test output"}]
            },
        }
        first = self.service.record_event(payload)
        replay = self.service.record_event(payload)

        self.assertEqual(first["result"]["status"], "suggested")
        self.assertIn("Focused tests passed", first["result"]["nextTurnContext"])
        self.assertLessEqual(len(first["result"]["nextTurnContext"]), 2000)
        self.assertFalse(first["guardrails"]["writesLongTermMemory"])
        self.assertTrue(replay["result"]["deduplicated"])
        self.assertEqual(
            len(self.service.snapshot()["recentEvents"]),
            1,
        )

    def test_tool_failure_without_facts_is_audit_only_and_policy_can_be_toggled(self) -> None:
        recorded = self.service.record_event(
            {
                "schemaVersion": "rag-ime.agent-lifecycle-event.v1",
                "eventId": "event-empty",
                "eventType": "tool_failed",
                "sessionId": "session-1",
                "payload": {"facts": []},
            }
        )
        self.assertEqual(recorded["result"]["status"], "recorded")
        self.assertEqual(recorded["result"]["reason"], "")
        self.assertEqual(recorded["result"]["nextTurnContext"], "")
        self.assertFalse(recorded["guardrails"]["writesLongTermMemory"])

        snapshot = self.service.update_policy(
            {"eventType": "idle", "enabled": False, "tokenLimit": 64}
        )
        idle = next(value for value in snapshot["policies"] if value["eventType"] == "idle")
        self.assertFalse(idle["enabled"])
        self.assertEqual(idle["tokenLimit"], 64)

    def test_review_hooks_cannot_be_changed_to_a_direct_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "not injected as an implicit checkpoint"):
            self.service.update_policy(
                {"eventType": "project_complete", "action": "context_checkpoint"}
            )

    def test_audit_only_event_records_without_facts_and_returns_idle_delay(self) -> None:
        result = self.service.record_event(
            {
                "schemaVersion": "rag-ime.agent-lifecycle-event.v1",
                "eventId": "event-turn-end",
                "eventType": "turn_end",
                "sessionId": "session-1",
                "payload": {},
            }
        )
        self.assertEqual(result["result"]["status"], "recorded")
        self.assertEqual(result["result"]["nextTurnContext"], "")
        self.assertEqual(result["result"]["idleDelayMs"], 900_000)
