from __future__ import annotations

import json
import unittest

from rag_ime.agent_room_recovery_context import (
    room_compaction_recovery_context,
)


class RoomCompactionRecoveryContextTests(unittest.TestCase):
    def test_packet_deduplicates_originals_and_preserves_exact_receipts(self) -> None:
        original = "原始需求：完成 Room 压缩恢复"
        rendered = room_compaction_recovery_context(
            json.dumps(
                {
                    "requirements": {
                        "original": [
                            {"text": original},
                            {"text": original},
                        ],
                        "items": [
                            {"statement": original},
                            {"statement": "补充需求：保留精确回执"},
                        ],
                    },
                    "task": {
                        "objective": "当前任务：验证一份恢复包",
                        "expectedOutput": "恢复证据",
                        "revision": 2,
                        "state": "active",
                    },
                    "responsibility": {
                        "ownerParticipantId": "participant:owner",
                        "currentParticipantId": "participant:worker",
                    },
                    "acceptance": {
                        "criteria": [
                            {"statement": "验收：每项只出现一次"},
                            {"statement": "验收：每项只出现一次"},
                        ]
                    },
                    "blockers": {
                        "obstacles": [
                            {"kind": "blocker", "statement": "阻塞：等待环境"},
                            {"kind": "blocker", "statement": "阻塞：等待环境"},
                        ]
                    },
                    "continuation": {
                        "intentKind": "handoff",
                        "parentDispatchId": "dispatch:parent",
                        "hopCount": 1,
                        "depth": 1,
                    },
                },
                ensure_ascii=False,
            ),
            skill_receipt={
                "restoredFromReceiptId": "skill:exact",
                "skillId": "implementation",
            },
            tool_receipt={
                "items": [
                    {"name": "room_state", "receiptId": "tool:exact"}
                ]
            },
        )

        packet = json.loads(rendered)
        self.assertEqual(packet["originalRequirements"], [original])
        self.assertEqual(
            packet["requirementDirectory"],
            ["补充需求：保留精确回执"],
        )
        for fact in (
            original,
            "当前任务：验证一份恢复包",
            "验收：每项只出现一次",
            "阻塞：等待环境",
            "skill:exact",
            "tool:exact",
        ):
            self.assertEqual(rendered.count(fact), 1)

    def test_invalid_task_context_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            room_compaction_recovery_context("not-json")


if __name__ == "__main__":
    unittest.main()
