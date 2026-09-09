from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_message_snapshot import _merge_tool_events
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.pi.config import PiRuntimeConfig
from rag_ime.pi.public import public_reasoning_summaries
from rag_ime.pi.runtime import PiRuntimeHostManager
from rag_ime.pi.transcript import durable_branch_messages, durable_tool_history_events


class PiReasoningProjectionTests(unittest.TestCase):
    """A long Responses message updates one public card, including on replay."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="paw-reasoning-projection-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        sessions = AgentSessionStore(root / "agent.sqlite")
        sessions.initialize()
        self.session_id = str(sessions.create(title="reasoning regression")["id"])
        config = PiRuntimeConfig(
            enabled=True,
            executable=None,
            agent_dir=root / "agent",
            session_dir=root / "sessions",
            logs_dir=root / "logs",
            idle_timeout_seconds=0,
        )
        self.events = {"v2": AgentEventHub()}
        self.v2 = PiRuntimeHostManager(config=config, sessions=sessions, events=self.events["v2"])
        self.addCleanup(self.v2.stop)

    def emit(self, message: dict, index: int) -> None:
        event = {
            "type": "message_update",
            "assistantMessageEvent": {"type": "thinking_end", "contentIndex": index},
            "message": message,
        }
        self.v2._handle_host_event({
            "protocolVersion": "2", "event": "agent.event",
            "sessionId": self.session_id, "turnId": "turn-reasoning", "payload": event,
        })

    def summaries(self, protocol: str) -> list:
        return [event for event in self.events[protocol].replay(self.session_id)[0]
                if event.event_type == "reasoning_summary"]

    def test_long_message_updates_one_card_with_recent_summaries(self) -> None:
        blocks = [{"type": "thinking", "thinking": f"**Step {i:02d}**"} for i in range(25)]
        message = {"id": "response-long", "role": "assistant", "api": "openai-codex-responses"}
        for index in range(len(blocks)):
            self.emit({**message, "content": blocks[:index + 1]}, index)

        for protocol in self.events:
            with self.subTest(protocol=protocol):
                events = self.summaries(protocol)
                self.assertEqual(len({event.payload["requestId"] for event in events}), 1)
                self.assertEqual(events[-1].payload["summary"], "Step 24")
                self.assertEqual(events[-1].payload["items"], [f"Step {i:02d}" for i in range(17, 25)])
                self.assertTrue(all(len(event.payload["items"]) <= 8 for event in events))

    def test_empty_or_redacted_end_does_not_repeat_the_prior_summary(self) -> None:
        public = {"type": "thinking", "thinking": "**Inspecting current work**"}
        base = {"id": "response-empty", "role": "assistant", "api": "openai-codex-responses"}
        self.emit({**base, "content": [public]}, 0)
        for block in [
            {"type": "thinking", "thinking": "", "thinkingSignature": "opaque-signature"},
            {"type": "redacted_thinking", "thinking": "private"},
            {"type": "text", "text": "ordinary text"},
        ]:
            self.emit({**base, "content": [public, block]}, 1)
        for protocol in self.events:
            with self.subTest(protocol=protocol):
                self.assertEqual(len(self.summaries(protocol)), 1)

    def test_identical_text_from_distinct_messages_remains_separate(self) -> None:
        for message_id in ["response-one", "response-two"]:
            self.emit({"id": message_id, "role": "assistant", "api": "openai-codex-responses",
                       "content": [{"type": "thinking", "thinking": "**Checking results**"}]}, 0)
        for protocol in self.events:
            with self.subTest(protocol=protocol):
                self.assertEqual(len({e.payload["requestId"] for e in self.summaries(protocol)}), 2)

    def test_durable_entry_id_does_not_duplicate_the_live_reasoning_card(self) -> None:
        message = {"role": "assistant", "timestamp": 200, "api": "openai-codex-responses",
                   "content": [{"type": "thinking", "thinking": "**Checking results**"}]}
        self.emit(message, 0)
        entries = [
            {"type": "message", "id": "entry-user", "timestamp": 100,
             "message": {"role": "user", "timestamp": 100, "content": "Check"}},
            {"type": "message", "id": "entry-assistant", "timestamp": 250, "message": message},
        ]
        messages, selected = durable_branch_messages(entries)
        history = durable_tool_history_events(messages, session_id=self.session_id, raw_entries=selected)
        live = self.summaries("v2")[-1].to_payload()
        self.assertEqual(history[0]["payload"]["requestId"], live["payload"]["requestId"])
        self.assertEqual(history[0]["payload"]["sourceMessageId"], live["payload"]["sourceMessageId"])
        self.assertEqual(len(_merge_tool_events(history, [live])), 1)
        self.assertEqual(history[0]["createdAtMs"], 250)

    def test_bounded_recent_summary_keeps_provider_privacy_gate(self) -> None:
        message = {"api": "openai-responses", "content": [
            {"type": "thinking", "thinking": f"**Step {i:02d}**"} for i in range(25)
        ]}
        self.assertEqual(public_reasoning_summaries(message), [f"Step {i:02d}" for i in range(17, 25)])
        self.assertEqual(public_reasoning_summaries({**message, "api": "anthropic-messages"}), [])


if __name__ == "__main__":
    unittest.main()
