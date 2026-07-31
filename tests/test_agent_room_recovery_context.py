from __future__ import annotations

import json
import unittest

from rag_ime.agent_room_recovery_context import (
    room_compaction_recovery_context,
)


class RoomCompactionRecoveryContextTests(unittest.TestCase):
    def test_packet_keeps_only_unfinished_continuity_and_exact_receipts(self) -> None:
        original = "原始需求：完成 Room 压缩恢复"
        rendered = room_compaction_recovery_context(
            json.dumps(
                {
                    "rootId": "root:recovery",
                    "dispatchId": "dispatch:recovery",
                    "generation": 4,
                    "requirements": {
                        "original": [{"text": original}],
                        "items": [
                            {"statement": "补充需求：保留精确回执"},
                        ],
                    },
                    "task": {
                        "taskId": "task:recovery",
                        "objective": "当前任务：验证一份恢复包",
                        "expectedOutput": "恢复证据",
                        "revision": 2,
                        "state": "active",
                    },
                    "responsibility": {
                        "currentOwnerParticipantId": "participant:owner",
                        "ownershipRevision": 2,
                        "ownershipReceiptId": "receipt:ownership:2",
                        "currentParticipantId": "participant:worker",
                    },
                    "acceptance": {
                        "criteria": [
                            {
                                "criterionId": "criterion:covered",
                                "statement": "已由 Kernel 覆盖",
                            },
                            {
                                "criterionId": "criterion:pending",
                                "statement": "仍待完成的验收",
                                "acceptedEvidenceRefs": [
                                    "evidence:pending"
                                ],
                            },
                        ]
                    },
                    "blockers": {
                        "obstacles": [
                            {
                                "obstacleId": "blocker:compaction",
                                "kind": "blocker",
                                "statement": "阻塞：等待环境",
                            },
                            {
                                "obstacleId": "blocker:duplicate",
                                "kind": "blocker",
                                "statement": "阻塞：等待环境",
                            },
                        ]
                    },
                    "continuation": {
                        "intentKind": "handoff",
                        "parentDispatchId": "dispatch:parent",
                        "hopCount": 1,
                        "depth": 1,
                    },
                    "sharedEvidenceRefs": ["evidence:shared"],
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
            covered_criterion_ids=("criterion:covered",),
        )

        packet = json.loads(rendered)
        self.assertEqual(
            packet["authoritativeProjectionRef"],
            {
                "dispatchId": "dispatch:recovery",
                "generation": 4,
                "rootId": "root:recovery",
                "taskId": "task:recovery",
                "taskRevision": 2,
            },
        )
        self.assertEqual(
            packet["pendingAcceptance"],
            [
                {
                    "alias": "AC-2",
                    "evidenceRefs": ["evidence:pending"],
                    "statement": "仍待完成的验收",
                }
            ],
        )
        self.assertEqual(
            packet["nextAction"],
            {
                "acceptanceAlias": "AC-2",
                "blockerRef": "blocker:compaction",
                "intentKind": "handoff",
            },
        )
        self.assertEqual(
            packet["evidenceRefs"],
            ["evidence:shared"],
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
        for fact in (
            "仍待完成的验收",
            "阻塞：等待环境",
            "skill:exact",
            "tool:exact",
        ):
            self.assertEqual(rendered.count(fact), 1)
        for forbidden in (
            original,
            "补充需求：保留精确回执",
            "当前任务：验证一份恢复包",
            "恢复证据",
            "已由 Kernel 覆盖",
            "originalRequirements",
            "requirementDirectory",
            "currentTask",
            '"acceptance":',
            '"handoff":',
            "schemaVersion",
            "participant:owner",
            "participant:worker",
            "dispatch:parent",
            "criterion:covered",
            "criterion:pending",
            "hopCount",
            "depth",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_invalid_task_context_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            room_compaction_recovery_context("not-json")

    def test_terminal_task_cannot_reactivate_uncovered_acceptance(self) -> None:
        rendered = room_compaction_recovery_context(
            json.dumps(
                {
                    "rootId": "root:terminal",
                    "dispatchId": "dispatch:terminal",
                    "generation": 1,
                    "requirements": {"original": [], "items": []},
                    "task": {
                        "taskId": "task:terminal",
                        "objective": "恢复当前任务",
                        "expectedOutput": "恢复包",
                        "revision": 3,
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
        self.assertEqual(packet["pendingAcceptance"], [])
        self.assertNotIn("nextAction", packet)
        self.assertNotIn("恢复当前任务", rendered)
        self.assertNotIn("恢复包", rendered)
        self.assertNotIn("已由 Kernel 验证", rendered)
        self.assertNotIn("仍待证据", rendered)
        self.assertNotIn("criterion:", rendered)


if __name__ == "__main__":
    unittest.main()
