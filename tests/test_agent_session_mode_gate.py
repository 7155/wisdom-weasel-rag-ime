from __future__ import annotations

import unittest

from rag_ime.agent_session_mode_gate import (
    AgentSessionModeConflict,
    AgentSessionModeGate,
)


class AgentSessionModeGateTests(unittest.TestCase):
    def test_agent_and_room_entry_claims_are_mutually_exclusive(self) -> None:
        gate = AgentSessionModeGate()

        with gate.claim_agent("session:shared"):
            with self.assertRaisesRegex(
                AgentSessionModeConflict,
                "正在接收 Agent 消息",
            ):
                with gate.claim_room(["session:shared"]):
                    self.fail("conflicting Room claim must not run")

        with gate.claim_room(["session:shared"]):
            with self.assertRaisesRegex(
                AgentSessionModeConflict,
                "正在进入 Room 任务",
            ):
                with gate.claim_agent("session:shared"):
                    self.fail("conflicting Agent claim must not run")

    def test_room_batch_claim_is_released_after_failure(self) -> None:
        gate = AgentSessionModeGate()

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with gate.claim_room(["session:a", "session:b", "session:a"]):
                raise RuntimeError("boom")

        with gate.claim_agent("session:a"):
            pass
        with gate.claim_agent("session:b"):
            pass

    def test_agent_continuation_joins_without_admitting_new_prompt(self) -> None:
        gate = AgentSessionModeGate()
        initial = gate.claim_agent("session:shared")
        continuation = gate.claim_agent_continuation(
            "session:shared"
        )

        initial.__enter__()
        continuation.__enter__()
        initial.__exit__(None, None, None)
        try:
            with self.assertRaisesRegex(
                AgentSessionModeConflict,
                "正在接收 Agent 消息",
            ):
                with gate.claim_room(["session:shared"]):
                    self.fail("continuation must retain the Agent claim")
            with self.assertRaisesRegex(
                AgentSessionModeConflict,
                "另一条 Agent 消息",
            ):
                with gate.claim_agent("session:shared"):
                    self.fail("continuation must not admit a new prompt")
        finally:
            continuation.__exit__(None, None, None)

        with gate.claim_room(["session:shared"]):
            pass
