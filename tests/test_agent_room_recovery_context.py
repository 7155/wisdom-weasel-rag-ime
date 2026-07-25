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
                            {
                                "criterionId": "criterion:exact",
                                "statement": "验收：每项只出现一次",
                            },
                            {
                                "criterionId": "criterion:exact",
                                "statement": "验收：每项只出现一次",
                            },
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
            covered_criterion_ids=("criterion:exact",),
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
        self.assertNotIn("criterion:exact", rendered)

        self.assertEqual(
            packet["acceptance"],
            [
                {
                    "alias": "AC-1",
                    "statement": "验收：每项只出现一次",
                    "status": "evidence_available",
                }
            ],
        )
        self.assertEqual(
            packet["handoff"],
            {"intentKind": "handoff"},
        )
        self.assertEqual(
            packet["skillReceipt"],
            {
                "restoredFromReceiptId": "skill:exact",
                "skillId": "implementation",
            },
        )
        self.assertEqual(
            packet["toolReceipt"],
            {
                "items": [
                    {
                        "name": "room_state",
                        "receiptId": "tool:exact",
                    }
                ]
            },
        )
        for forbidden in (
            "schemaVersion",
            "participant:owner",
            "participant:worker",
            "dispatch:parent",
            "criterion:exact",
            "hopCount",
            "depth",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_invalid_task_context_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            room_compaction_recovery_context("not-json")

    def test_acceptance_uses_public_aliases_and_compact_statuses(self) -> None:
        rendered = room_compaction_recovery_context(
            json.dumps(
                {
                    "requirements": {"original": [], "items": []},
                    "task": {
                        "objective": "恢复当前任务",
                        "expectedOutput": "恢复包",
                        "state": "completed",
                    },
                    "acceptance": {
                        "criteria": [
                            {
                                "criterionId": "criterion:verified",
                                "statement": "已由 Kernel 验证",
                                "passed": True,
                            },
                            {
                                "criterionId": "criterion:pending",
                                "statement": "仍待证据",
                                "passed": False,
                            },
                        ]
                    },
                    "blockers": {"obstacles": []},
                    "continuation": {},
                },
                ensure_ascii=False,
            ),
            covered_criterion_ids=("criterion:verified",),
        )

        packet = json.loads(rendered)
        self.assertEqual(
            packet["acceptance"],
            [
                {
                    "alias": "AC-1",
                    "statement": "已由 Kernel 验证",
                    "status": "verified",
                },
                {
                    "alias": "AC-2",
                    "statement": "仍待证据",
                    "status": "pending",
                },
            ],
        )
        self.assertNotIn("criterion:", rendered)


if __name__ == "__main__":
    unittest.main()
