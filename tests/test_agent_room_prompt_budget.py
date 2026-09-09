from __future__ import annotations

import unittest
from pathlib import Path

from rag_ime.rooms.prompt_context import (
    ROOM_CONTEXT_PROMPT_CHAR_BUDGET,
    room_participant_prompt,
)


ROOT = Path(__file__).parents[1]


class AgentRoomPromptBudgetTests(unittest.TestCase):
    def test_extreme_context_preserves_request_and_state_contract(self) -> None:
        participant_id = "participant-coordinator"
        work_items = []
        work_documents = []
        authorities = {}
        for ordinal in range(12):
            work_id = f"work-{ordinal}-" + ("w" * 220)
            authority_key = f"room_work_item:{work_id}"
            work_items.append(
                {
                    "id": work_id,
                    "state": "active",
                    "revision": ordinal,
                    "objective": f"objective-{ordinal}-" + ("o" * 900),
                    "currentOwnerParticipantId": participant_id,
                    "allowedOperations": ["retry", "block"],
                }
            )
            work_documents.append(
                {
                    "authorityKey": authority_key,
                    "path": f"docs/work-{ordinal}-" + ("p" * 980),
                    "documentId": f"document-{ordinal}-" + ("d" * 220),
                    "authorityRevision": 2,
                    "title": f"title-{ordinal}-" + ("t" * 220),
                }
            )
            authorities[authority_key] = {
                "authorityRevision": 2,
                "transitionReceiptId": f"receipt-{ordinal}",
            }

        prompt = room_participant_prompt(
            {
                "title": "Prompt budget pressure",
                "roomKind": "collaboration",
                "participants": [
                    {
                        "id": participant_id,
                        "status": "active",
                        "displayName": "Facilitator",
                        "sessionId": "session-" + ("s" * 300),
                    }
                ],
                "workItems": work_items,
            },
            {
                "id": participant_id,
                "collaborationRole": "coordinator",
            },
            "REQUEST-BEGIN " + ("真实用户请求。" * 700) + " REQUEST-CRITICAL-TAIL",
            work_item={
                **work_items[0],
                "expectedOutput": "deliverable-" + ("e" * 980),
                "acceptanceCriteria": [
                    f"criterion-{ordinal}-" + ("a" * 280)
                    for ordinal in range(12)
                ],
                "recommendedOperation": {
                    "op": "retry",
                    "expectedRevision": 0,
                },
            },
            work_documents=work_documents,
            work_document_authorities=authorities,
        )

        self.assertEqual(ROOM_CONTEXT_PROMPT_CHAR_BUDGET, 12_000)
        self.assertLessEqual(len(prompt), ROOM_CONTEXT_PROMPT_CHAR_BUDGET)
        self.assertIn("REQUEST-BEGIN", prompt)
        self.assertIn("REQUEST-CRITICAL-TAIL", prompt)
        self.assertIn("当前职责：Room Facilitator", prompt)
        self.assertIn("skill_load 加载 facilitate-room", prompt)
        self.assertIn("recommendedOperation=retry，expectedRevision=0", prompt)
        self.assertIn("Room Context 只提供当前状态", prompt)
        self.assertIn("唯一终态、幂等、Goal 完成、wake 抑制和 turn settlement 由 Runtime 负责", prompt)
        self.assertNotIn("op=post、kind=result", prompt)
        self.assertNotIn("agent_goal complete", prompt)
        self.assertNotIn("普通 turn_completed", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))
        self.assertEqual(prompt.count("</room-context>"), 1)

    def test_facilitation_skill_is_method_first_and_progressively_disclosed(self) -> None:
        skill_path = ROOT / "integrations/pi/skills/facilitate-room/SKILL.md"
        reference_path = skill_path.parent / "references/runtime-operations.md"
        skill = skill_path.read_text(encoding="utf-8")
        reference = reference_path.read_text(encoding="utf-8")

        self.assertLess(len(skill.encode("utf-8")), 8_000)
        self.assertIn("Do not load this Skill merely because the Session belongs to a Room", skill)
        self.assertIn("Choose the smallest topology", skill)
        self.assertIn("visible responsibility topology and Root closeout", skill)
        self.assertIn("references/runtime-operations.md", skill)
        self.assertEqual(
            skill.count("[references/runtime-operations.md](references/runtime-operations.md)"),
            1,
        )
        self.assertNotIn("## Failure Recovery and Terminal Rule", skill)
        self.assertNotIn("expectedRevision", skill)
        self.assertNotIn("documentSync", skill)
        self.assertLessEqual(skill.count("room_partner"), 3)

        self.assertIn("live Tool schema", reference)
        self.assertIn("allowedOperations", reference)
        self.assertIn("recommendedOperation", reference)
        self.assertIn("Runtime owns idempotency", reference)
        self.assertIn("unique terminality", reference)

    def test_partner_submission_is_not_acceptance_or_facilitation(self) -> None:
        work_item = {
            "id": "work-one",
            "state": "active",
            "revision": 3,
            "objective": "完成这个交付",
            "expectedOutput": "可验收结果",
            "acceptanceCriteria": ["通过聚焦回归"],
            "currentOwnerParticipantId": "participant-worker",
            "allowedOperations": ["post_work_result", "peer_ask"],
        }
        prompt = room_participant_prompt(
            {
                "title": "Async Room",
                "roomKind": "collaboration",
                "participants": [
                    {
                        "id": "participant-worker",
                        "status": "active",
                        "displayName": "Worker",
                        "sessionId": "session-worker",
                    }
                ],
                "workItems": [work_item],
            },
            {
                "id": "participant-worker",
                "collaborationRole": "implementer",
            },
            "完成这个交付",
            work_item=work_item,
        )

        self.assertIn("当前职责：Room Partner", prompt)
        self.assertIn("不要加载 facilitate-room", prompt)
        self.assertIn("typed work_result", prompt)
        self.assertIn("只会把 WorkItem 提交到 review，不会自动验收", prompt)
        self.assertIn("allowedOperations=post_work_result,peer_ask", prompt)
        self.assertIn("当前工作卡片已在上文给出；不要扩大其范围", prompt)
        self.assertIn("不要代替 Facilitator 接受其他工作或发布 Root 结果", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))

    def test_facilitator_sees_current_retry_recovery_without_full_manual(self) -> None:
        work_item = {
            "id": "room-work:returned-one",
            "state": "active",
            "revision": 1,
            "objective": "补齐真实浏览器验收",
            "currentOwnerParticipantId": "participant-worker",
            "accountableParticipantId": "participant-coordinator",
            "blocker": {"reviewFeedback": "浏览器不可用，证据不足。"},
            "review": {
                "operabilityVerdict": "unverified",
                "requirementVerdict": "unverified",
            },
            "recommendedOperation": {
                "op": "retry",
                "expectedRevision": 1,
            },
        }
        prompt = room_participant_prompt(
            {
                "title": "Recovery Room",
                "roomKind": "collaboration",
                "participants": [
                    {
                        "id": "participant-coordinator",
                        "status": "active",
                        "displayName": "Facilitator",
                        "sessionId": "session-coordinator",
                    },
                    {
                        "id": "participant-worker",
                        "status": "active",
                        "displayName": "Worker",
                        "sessionId": "session-worker",
                    },
                ],
                "workItems": [work_item],
            },
            {
                "id": "participant-coordinator",
                "collaborationRole": "coordinator",
            },
            "继续完成刚才没做完的任务。",
        )

        self.assertIn("返修待重新派发", prompt)
        self.assertIn("op=retry", prompt)
        self.assertIn("workItemId=room-work:returned-one", prompt)
        self.assertIn("expectedRevision=1", prompt)
        self.assertIn("不要新建替代任务", prompt)
        self.assertIn("重新提交到 review 后再验收", prompt)
        self.assertNotIn("省略 targetParticipantId", prompt)
        self.assertLess(prompt.index("返修待重新派发"), prompt.index("当前职责：Room Facilitator"))

    def test_retry_directive_survives_extreme_request_pressure(self) -> None:
        participant_id = "participant-coordinator"
        work_item = {
            "id": "room-work:returned-under-pressure",
            "state": "active",
            "revision": 4,
            "objective": "返修真实验收" + ("长" * 900),
            "currentOwnerParticipantId": "participant-worker",
            "accountableParticipantId": participant_id,
            "blocker": {"reviewFeedback": "需要返修" + ("证据" * 300)},
            "recommendedOperation": {"op": "retry", "expectedRevision": 4},
        }
        prompt = room_participant_prompt(
            {
                "title": "Budgeted recovery",
                "roomKind": "collaboration",
                "participants": [
                    {
                        "id": participant_id,
                        "status": "active",
                        "displayName": "Facilitator",
                        "sessionId": "session-coordinator",
                    },
                    {
                        "id": "participant-worker",
                        "status": "active",
                        "displayName": "Worker",
                        "sessionId": "session-worker",
                    },
                ],
                "workItems": [work_item],
            },
            {
                "id": participant_id,
                "collaborationRole": "coordinator",
            },
            "REQUEST-BEGIN " + ("继续。" * 3_000) + " REQUEST-END",
        )

        self.assertLessEqual(len(prompt), ROOM_CONTEXT_PROMPT_CHAR_BUDGET)
        self.assertIn("workItemId=room-work:returned-under-pressure", prompt)
        self.assertIn("expectedRevision=4", prompt)
        self.assertIn("REQUEST-BEGIN", prompt)
        self.assertIn("REQUEST-END", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))


if __name__ == "__main__":
    unittest.main()
