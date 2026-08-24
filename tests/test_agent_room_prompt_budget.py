from __future__ import annotations

import unittest
from pathlib import Path

from rag_ime.agent_room_prompt_context import (
    ROOM_CONTEXT_PROMPT_CHAR_BUDGET,
    room_participant_prompt,
)


class AgentRoomPromptBudgetTests(unittest.TestCase):
    def test_extreme_context_preserves_request_hard_rules_and_closing_tag(
        self,
    ) -> None:
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
                    "objective": f"objective-{ordinal}-" + ("o" * 900),
                    "currentOwnerParticipantId": participant_id,
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

        room = {
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
        }
        target = {
            "id": participant_id,
            "collaborationRole": "coordinator",
        }
        request = (
            "REQUEST-BEGIN "
            + ("真实用户请求。" * 700)
            + " REQUEST-CRITICAL-TAIL"
        )

        prompt = room_participant_prompt(
            room,
            target,
            request,
            work_item={
                **work_items[0],
                "expectedOutput": "deliverable-" + ("e" * 980),
                "acceptanceCriteria": [
                    f"criterion-{ordinal}-" + ("a" * 280)
                    for ordinal in range(12)
                ],
            },
            work_documents=work_documents,
            work_document_authorities=authorities,
        )

        self.assertLessEqual(
            len(prompt),
            ROOM_CONTEXT_PROMPT_CHAR_BUDGET,
        )
        self.assertIn("REQUEST-BEGIN", prompt)
        self.assertIn("REQUEST-CRITICAL-TAIL", prompt)
        self.assertIn("当前职责：Room Facilitator", prompt)
        self.assertIn(
            "只有可核对的 Tool 回执、WorkItem 验收和最终 Root 汇合才能作为成功证据。",
            prompt,
        )
        self.assertIn("delegate/delegate_batch 只返回异步 receipt", prompt)
        self.assertIn("伙伴完成后由持久 wake 唤醒你", prompt)
        self.assertIn("显式 accept 或 return", prompt)
        self.assertIn("携带原 workItemId", prompt)
        self.assertIn("非空 reason accept", prompt)
        self.assertIn("不得写成 passed/satisfied", prompt)
        self.assertIn("不要把仍在进行的 Room Goal 暂停", prompt)
        self.assertIn("网页验收只用 product browser", prompt)
        self.assertIn("live authorityRevision", prompt)
        self.assertIn("op=post、kind=progress", prompt)
        self.assertIn("progress 是非终态", prompt)
        self.assertIn("不得根据 content 前缀", prompt)
        self.assertIn("op=post、kind=result", prompt)
        self.assertIn("恰好一次", prompt)
        self.assertIn("普通 turn_completed", prompt)
        self.assertEqual(prompt.count("op=post、kind=result"), 1)
        self.assertNotIn("documentRevision >= 2）后才会自动验收", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))
        self.assertEqual(prompt.count("</room-context>"), 1)

    def test_facilitator_skill_requires_one_typed_result_before_turn_completion(
        self,
    ) -> None:
        skill = (
            Path(__file__).parents[1]
            / "integrations/pi/skills/facilitate-room/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("`op=post`, `kind=progress`", skill)
        self.assertIn("non-terminal", skill)
        self.assertIn("content prefix", skill)
        self.assertIn("`op=post`, `kind=result`", skill)
        self.assertIn("exactly once", skill)
        self.assertIn("ordinary `turn_completed`", skill)
        self.assertIn("Do not pause a live Room Goal to wait", skill)
        self.assertIn("If a reviewer reported `unverified`", skill)
        self.assertEqual(skill.count("`op=post`, `kind=result`"), 1)
        self.assertLess(
            skill.index("`op=post`, `kind=result`"),
            skill.index("ordinary `turn_completed`"),
        )

    def test_partner_work_result_is_submission_not_acceptance(self) -> None:
        work_item = {
            "id": "work-one",
            "state": "active",
            "objective": "完成这个交付",
            "expectedOutput": "可验收结果",
            "acceptanceCriteria": ["通过聚焦回归"],
            "currentOwnerParticipantId": "participant-worker",
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

        self.assertIn("只会把 WorkItem 提交到 review", prompt)
        self.assertIn("不会自动验收", prompt)
        self.assertNotIn("当前尚未形成结构化 WorkItem", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))


if __name__ == "__main__":
    unittest.main()
