from __future__ import annotations

import unittest

from rag_ime.agent_room_application import _normalize_room_execution_plan


def _participant(identifier: str, name: str) -> dict[str, object]:
    return {
        "id": identifier,
        "displayName": name,
        "status": "active",
    }


class RoomExecutionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.participants = [
            _participant("facilitator", "澄·远"),
            _participant("worker-a", "澄·今"),
            _participant("worker-b", "澄·瞬"),
            _participant("reviewer", "澄·初"),
        ]

    def _normalize(
        self,
        plan: dict[str, object],
        *,
        review: bool = True,
    ) -> dict[str, object]:
        return _normalize_room_execution_plan(
            plan,
            objective="让用户完成四项客户管理操作",
            expected_output="用户能在真实界面完成操作并看到结果",
            default_participant=self.participants[1],
            participant_refs={},
            participants=self.participants,
            acceptance_plan=["用户能完成全部操作并看到可核对结果"],
        )

    @staticmethod
    def _plan() -> dict[str, object]:
        return {
            "sharedContracts": ["所有功能都使用同一份客户身份，并保留每次修改记录"],
            "featureTasks": [
                {
                    "title": "批量导入客户",
                    "participantRef": "worker-a",
                    "userOutcome": "用户上传表格后可预览问题，确认后看到逐行结果",
                    "dependencies": [],
                    "wave": 1,
                    "writeBoundary": "只负责从上传到确认结果的完整操作",
                },
                {
                    "title": "保存标签筛选",
                    "participantRef": "worker-b",
                    "userOutcome": "用户筛选客户后可保存并再次打开同一视图",
                    "dependencies": [],
                    "wave": 1,
                    "writeBoundary": "只负责筛选、保存和恢复视图",
                },
            ],
            "integrationPlan": "主持伙伴统一核对公共约定并完成集成，不领取功能实现",
            "acceptancePlan": ["在真实界面分别完成导入和筛选保存"],
        }

    def test_adds_one_governed_requirement_and_execution_record(self) -> None:
        normalized = self._normalize(self._plan())

        self.assertIn("唯一的受管工作文档", normalized["continuityPlan"])
        self.assertIn("用户原话与愿景", normalized["continuityPlan"])
        self.assertIn("上下文恢复", normalized["continuityPlan"])

    def test_rejects_internal_english_schema_from_chinese_start_plan(self) -> None:
        plan = self._plan()
        plan["sharedContracts"] = [
            "Canonical Customer: stable customerId and normalized tags"
        ]

        with self.assertRaisesRegex(ValueError, "用户正在使用的语言"):
            self._normalize(plan)

    def test_facilitator_remains_a_peer_who_can_own_a_feature(self) -> None:
        plan = self._plan()
        plan["featureTasks"][0]["participantRef"] = "facilitator"  # type: ignore[index]

        normalized = self._normalize(plan)

        self.assertEqual(normalized["featureTasks"][0]["ownerDisplayName"], "澄·远")

    def test_plan_does_not_freeze_an_idle_reviewer_before_authorship_exists(self) -> None:
        plan = self._plan()
        limited = self.participants[:3]

        normalized = _normalize_room_execution_plan(
            plan,
            objective="让用户完成两项客户管理操作",
            expected_output="用户能在真实界面看到结果",
            default_participant=limited[1],
            participant_refs={},
            participants=limited,
            acceptance_plan=["真实界面操作通过"],
        )

        self.assertEqual(len(normalized["featureTasks"]), 2)

    def test_one_owner_cannot_claim_two_features_in_the_same_wave(self) -> None:
        plan = self._plan()
        plan["featureTasks"][1]["participantRef"] = "worker-a"  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "同一波并行承担两个功能"):
            self._normalize(plan)


if __name__ == "__main__":
    unittest.main()
