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
        self.assertIn("可见计划回执", prompt)
        self.assertIn("才在生产证据到齐后委派 Reviewer WorkItem", prompt)
        self.assertIn("有界上下文引用", prompt)
        self.assertIn("progress 是非终态", prompt)
        self.assertIn("不得根据 content 前缀", prompt)
        self.assertIn("op=post、kind=result", prompt)
        self.assertIn("恰好一次", prompt)
        self.assertIn("才能调用 agent_goal complete", prompt)
        self.assertIn("普通 turn_completed", prompt)
        self.assertIn("documentSync pending/failed", prompt)
        self.assertIn("不阻断满足功能证据的 WorkItem", prompt)
        self.assertIn("只有交付本身就是文档时才影响 requirementVerdict", prompt)
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
        self.assertIn("This is a plan receipt, not a new approval gate", skill)
        self.assertIn("Add a later Reviewer WorkItem only when", skill)
        self.assertIn("without manufacturing another WorkItem", skill)
        self.assertIn("bounded context refs", skill)
        self.assertIn("non-terminal", skill)
        self.assertIn("content prefix", skill)
        self.assertIn("`op=post`, `kind=result`", skill)
        self.assertIn("exactly once", skill)
        self.assertIn(
            "Only after that Tool receipt succeeds, call `agent_goal complete`",
            skill,
        )
        self.assertIn("ordinary `turn_completed`", skill)
        self.assertIn("Do not pause a live Room Goal to wait", skill)
        self.assertIn("If a reviewer reported `unverified`", skill)
        self.assertIn("A returned item remains `active` with `reviewFeedback`", skill)
        self.assertIn("send it back for revision with `room_partner retry`", skill)
        self.assertIn("Do not call `delegate`", skill)
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
        self.assertIn("WorkDocument 绑定最多尝试一次", prompt)
        self.assertIn("不要仅因文档同步失败 retry/return", prompt)
        self.assertIn("网页验收只用 product browser", prompt)
        self.assertIn("live authorityRevision", prompt)
        self.assertNotIn("当前尚未形成结构化 WorkItem", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))

    def test_facilitator_sees_exact_retry_for_returned_active_work(self) -> None:
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
        self.assertIn("省略 targetParticipantId", prompt)
        self.assertIn("重新提交到 review 后才能 accept", prompt)
        self.assertIn("先执行，不要把本轮结束为 blocked", prompt)
        self.assertLess(
            prompt.index("返修待重新派发"),
            prompt.index("当前职责：Room Facilitator"),
        )

    def test_retry_directive_survives_extreme_context_budget(self) -> None:
        participant_id = "participant-coordinator"
        work_items = [
            {
                "id": "room-work:returned-under-pressure",
                "state": "active",
                "revision": 4,
                "objective": "返修真实验收" + ("长" * 900),
                "currentOwnerParticipantId": "participant-worker",
                "accountableParticipantId": participant_id,
                "blocker": {"reviewFeedback": "需要返修" + ("证据" * 300)},
            }
        ]
        work_documents = []
        authorities = {}
        for ordinal in range(12):
            work_id = f"room-work:pressure-{ordinal}-" + ("w" * 180)
            work_items.append(
                {
                    "id": work_id,
                    "state": "active",
                    "objective": "o" * 1_000,
                    "accountableParticipantId": participant_id,
                }
            )
            authority_key = f"room_work_item:{work_id}"
            work_documents.append(
                {
                    "authorityKey": authority_key,
                    "path": "docs/" + ("p" * 980),
                    "documentId": "document-" + ("d" * 220),
                    "authorityRevision": 2,
                    "title": "title-" + ("t" * 220),
                }
            )
            authorities[authority_key] = {"authorityRevision": 2}

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
                "workItems": work_items,
            },
            {
                "id": participant_id,
                "collaborationRole": "coordinator",
            },
            "REQUEST-BEGIN " + ("继续。" * 3_000) + " REQUEST-END",
            work_documents=work_documents,
            work_document_authorities=authorities,
        )

        self.assertLessEqual(len(prompt), ROOM_CONTEXT_PROMPT_CHAR_BUDGET)
        self.assertIn("workItemId=room-work:returned-under-pressure", prompt)
        self.assertIn("expectedRevision=4", prompt)
        self.assertIn("先执行，不要把本轮结束为 blocked", prompt)
        self.assertIn("REQUEST-BEGIN", prompt)
        self.assertIn("REQUEST-END", prompt)
        self.assertTrue(prompt.endswith("</room-context>"))


if __name__ == "__main__":
    unittest.main()
