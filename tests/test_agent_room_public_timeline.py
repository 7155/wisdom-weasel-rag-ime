from __future__ import annotations

import unittest
from typing import Any

from rag_ime.agent_room_public_timeline import (
    assert_public_room_report_claims,
    canonical_room_alignment_content,
    RoomPublicTimelineProjector,
    public_room_report_content,
)


class _RecordingEventHub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish_projection(self, **values: Any) -> dict[str, object]:
        self.calls.append(values)
        return {
            "eventType": values["event_type"],
            "payload": values["payload"],
        }


class RoomPublicTimelineProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room_id = "room:1"
        self.events = _RecordingEventHub()
        self.projector = RoomPublicTimelineProjector(self.events)  # type: ignore[arg-type]

    def test_published_event_excludes_context_journal_evidence(self) -> None:
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:1",
            "roomId": self.room_id,
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "participant:1",
            "kind": "result",
            "visibility": "room",
            "content": "正式交付",
            "idempotencyKey": "post:1",
            "publicationSource": {"kind": "room_commit", "ref": "commit:1"},
            "createdAtMs": 2,
            "contentHash": "private-hash",
            "contextEntry": {"entryId": "private-entry"},
        }

        event = self.projector.publish_post(
            post,
            participant_id="participant:1",
            source_session_id="session:1",
        )

        self.assertIsNotNone(event)
        projected = event["payload"]["post"]
        self.assertEqual(projected["content"], "正式交付")
        self.assertEqual(projected["dispatchId"], "dispatch:1")
        self.assertNotIn("contentHash", projected)
        self.assertNotIn("contextEntry", projected)

    def test_structured_question_is_preserved_for_live_and_replay_projection(
        self,
    ) -> None:
        question = {
            "prompt": "采用哪个方案？",
            "options": [
                {
                    "value": "safe",
                    "label": "稳妥方案",
                    "recommended": True,
                },
                {
                    "value": "fast",
                    "label": "快速方案",
                },
            ],
        }
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:question",
            "roomId": self.room_id,
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "participant:1",
            "kind": "wait",
            "visibility": "room",
            "content": "需要用户澄清",
            "question": question,
            "idempotencyKey": "post:question",
            "publicationSource": {
                "kind": "room_commit",
                "ref": "commit:question",
            },
            "createdAtMs": 2,
        }

        live = self.projector.publish_post(
            post,
            participant_id="participant:1",
            source_session_id="session:1",
        )

        self.assertIsNotNone(live)
        assert live is not None
        self.assertEqual(live["payload"]["post"]["question"], question)
        replay_payload = self.events.calls[-1]["payload"]
        assert isinstance(replay_payload, dict)
        self.assertEqual(replay_payload["post"]["question"], question)

        legacy_post = {
            **post,
            "postId": "post:legacy",
            "idempotencyKey": "post:legacy",
            "publicationSource": {
                "kind": "room_commit",
                "ref": "commit:legacy",
            },
        }
        legacy_post.pop("question")
        legacy = self.projector.publish_post(
            legacy_post,
            participant_id="participant:1",
            source_session_id="session:1",
        )
        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertNotIn("question", legacy["payload"]["post"])

    def test_post_after_root_terminal_is_not_projected(self) -> None:
        projector = RoomPublicTimelineProjector(  # type: ignore[arg-type]
            self.events,
            root_is_terminal=lambda root_id: root_id == "root:1",
        )
        post = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": "post:late",
            "roomId": self.room_id,
            "rootId": "root:1",
            "generation": 0,
            "taskId": "task:1",
            "dispatchId": "dispatch:1",
            "authorActorRef": "participant:1",
            "kind": "result",
            "visibility": "room",
            "content": "迟到交付",
            "idempotencyKey": "post:late",
            "publicationSource": {"kind": "room_commit", "ref": "commit:late"},
            "createdAtMs": 3,
        }

        event = projector.publish_post(
            post,
            participant_id="participant:1",
            source_session_id="session:1",
        )

        self.assertIsNone(event)
        self.assertEqual(self.events.calls, [])

    def test_public_report_rejects_internal_protocol_artifacts(self) -> None:
        self.assertEqual(
            public_room_report_content(
                "审查已经完成；主要风险与下一步均已向用户说明。",
                field_name="publicSummary",
            ),
            "审查已经完成；主要风险与下一步均已向用户说明。",
        )
        internal_reports = (
            "检查完成，rootId 为 root:private。",
            "证据 evidenceRef 来自 proof:settle。",
            "回执是 4fd950e8-712e-4708-bcb0-ba2c1c211bf4。",
            "详情位于 /Volumes/private/project/report.json。",
            f"结果哈希为 {'a' * 64}。",
            "qualityGateReceipt 已经通过。",
            "executionReceipt 已返回。",
            "内部 root_id=root-private。",
            "内部 evidence_ref=proof-private。",
            "Kernel 已经完成最终汇总。",
            "Root 已经满足全部条件。",
            "Dispatch 已经提交。",
            "Task 已经完成。",
            "AC 已经通过。",
            "Receipt ID 已经生成。",
            r"详情位于 C:\Users\private\report.json。",
            "详情位于 ../private/report.json。",
        )
        for report in internal_reports:
            with self.subTest(report=report), self.assertRaisesRegex(
                ValueError,
                "must be rewritten for users",
            ):
                public_room_report_content(
                    report,
                    field_name="publicSummary",
                )


    def test_public_report_rejects_protocol_placeholders(self) -> None:
        for report in (
            "public:deliver",
            "done",
            "已完成",
            "等待。",
            "正在处理中……",
            "我在执行这个任务。",
            "Working...",
        ):
            with self.subTest(report=report), self.assertRaisesRegex(
                ValueError,
                "meaningful user-facing report",
            ):
                public_room_report_content(
                    report,
                    field_name="publicSummary",
                )

    def test_alignment_content_is_canonical_public_natural_language(self) -> None:
        content = canonical_room_alignment_content(
            objective="  完成终端原生 TUI 的可运行闭环  ",
            expected_output=" 可运行实现与聚焦验证记录。 ",
        )

        self.assertEqual(
            content,
            "已经对齐：目标是“完成终端原生 TUI 的可运行闭环”，"
            "交付边界是“可运行实现与聚焦验证记录”。",
        )
        self.assertNotRegex(
            content,
            r"rootId|dispatchId|schemaVersion|room-root:|room-dispatch:|\{",
        )

        for objective, expected_output in (
            (
                "完善 Task 列表的用户可读说明",
                "说明 receipt 与 invoice 的业务差异",
            ),
            (
                "完成 Root Cause 分析并修复公开页面",
                "可运行实现与聚焦验证记录",
            ),
        ):
            with self.subTest(objective=objective):
                self.assertIn(
                    objective,
                    canonical_room_alignment_content(
                        objective=objective,
                        expected_output=expected_output,
                    ),
                )

    def test_alignment_content_rejects_raw_protocol_material(self) -> None:
        raw_protocol_fragments = (
            '{"rootId":"room-root:private"}',
            '{"objective":"完成实现"}',
            "完成 room-dispatch:private",
            "schemaVersion=wisdom-weasel.room-post.v2",
            "按 AC-1 验收",
            "读取 requirement:private",
            "附上 receipt-12345",
            "使用 rootId root-private",
            "公开 qualityGateReceipt",
        )
        for fragment in raw_protocol_fragments:
            for field_name in ("objective", "expectedOutput"):
                with self.subTest(
                    field_name=field_name,
                    fragment=fragment,
                ), self.assertRaisesRegex(ValueError, "natural language"):
                    canonical_room_alignment_content(
                        objective=(
                            fragment
                            if field_name == "objective"
                            else "完成用户可见实现"
                        ),
                        expected_output=(
                            fragment
                            if field_name == "expectedOutput"
                            else "可运行实现"
                        ),
                    )

    def test_non_delivery_report_cannot_overstate_kernel_evidence(self) -> None:
        cases = (
            (
                "handoff",
                True,
                "整个任务已经完成并交付。",
                "whole request is complete",
            ),
            (
                "wait",
                False,
                "测试全部通过，只需等待部署窗口。",
                "authoritative evidence",
            ),
            (
                "blocked",
                False,
                "所有验收标准均已满足，但外部服务不可用。",
                "authoritative evidence",
            ),
        )
        for decision, all_verified, report, message in cases:
            with self.subTest(decision=decision), self.assertRaisesRegex(
                ValueError,
                message,
            ):
                assert_public_room_report_claims(
                    report,
                    field_name="publicSummary",
                    decision=decision,
                    all_criteria_verified=all_verified,
                )

        assert_public_room_report_claims(
            "当前阶段检查已经完成；另一位伙伴将独立复核后再给出结论。",
            field_name="publicSummary",
            decision="handoff",
            all_criteria_verified=True,
        )

if __name__ == "__main__":
    unittest.main()
