from __future__ import annotations

import unittest

from rag_ime.agent_memory_evidence import AgentMemoryEvidenceService
from rag_ime.agent_protocol import AgentEventEnvelope


class _Sessions:
    def get(self, _session_id: str) -> dict[str, object]:
        return {"roleId": "companion-present-v1"}


class _EvidenceStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def record_user_message(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("user", dict(kwargs)))
        return {"stored": True}

    def record_assistant_message(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("assistant", dict(kwargs)))
        return {"stored": True}


class AgentMemoryEvidenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = _EvidenceStore()
        self.memory_enabled = True
        self.service = AgentMemoryEvidenceService(
            sessions=_Sessions(),
            memory_evidence=self.store,
            message_text=lambda message: str(message.get("text") or ""),
            memory_enabled_provider=lambda: self.memory_enabled,
        )

    def test_user_memory_workflow_instruction_is_not_recorded(self) -> None:
        result = self.service.record_user(
            session_id="session:1",
            pi_entry_id="entry:1",
            turn_id="turn:1",
            text="请调用 memory 的 curation_prepare 并返回 runId。",
        )

        self.assertEqual(
            result["status"],
            "skipped_memory_workflow_instruction",
        )
        self.assertEqual(self.store.calls, [])

    def test_assistant_empty_curation_receipt_is_not_recorded(self) -> None:
        result = self.service.record_assistant(
            AgentEventEnvelope(
                event_id="event:1",
                session_id="session:1",
                turn_id="turn:1",
                sequence=1,
                created_at_ms=1,
                event_type="message_completed",
                payload={
                    "message": {
                        "id": "assistant:1",
                        "role": "assistant",
                        "text": (
                            "已按 conservative 策略执行整理，"
                            "没有通过 Atom-first 门槛，未生成可审阅草案。"
                        ),
                    }
                },
                resume_token="resume:1",
            )
        )

        self.assertEqual(
            result["status"],
            "skipped_memory_workflow_instruction",
        )
        self.assertEqual(self.store.calls, [])

    def test_meaningful_user_input_is_recorded(self) -> None:
        result = self.service.record_user(
            session_id="session:1",
            pi_entry_id="entry:meaningful",
            turn_id="turn:meaningful",
            text="我希望个人记忆优先保留用户输入和对话总结。",
        )

        self.assertTrue(result["stored"])
        self.assertEqual(self.store.calls[0][0], "user")

    def test_master_switch_skips_new_evidence_without_erasing_existing_rows(self) -> None:
        existing = ("user", {"text": "已有长期偏好"})
        self.store.calls.append(existing)
        self.memory_enabled = False

        disabled = self.service.record_user(
            session_id="session:1",
            pi_entry_id="entry:disabled",
            turn_id="turn:disabled",
            text="关闭后不应进入记忆证据",
        )

        self.assertEqual(disabled["status"], "skipped_memory_disabled")
        self.assertEqual(self.store.calls, [existing])

        self.memory_enabled = True
        restored = self.service.record_user(
            session_id="session:1",
            pi_entry_id="entry:restored",
            turn_id="turn:restored",
            text="重新开启后恢复记录",
        )
        self.assertTrue(restored["stored"])
        self.assertEqual(len(self.store.calls), 2)


if __name__ == "__main__":
    unittest.main()
