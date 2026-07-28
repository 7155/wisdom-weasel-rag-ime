from __future__ import annotations

import unittest

from rag_ime.agent_core_policy import (
    core_agent_policy_prompt,
    durable_memory_policy_prompt,
    managed_goal_policy_prompt,
    work_policy_prompt,
)


class AgentCorePolicyTests(unittest.TestCase):
    def test_durable_memory_policy_keeps_only_the_stable_governance_boundary(self) -> None:
        prompt = durable_memory_policy_prompt()

        for expected in (
            "稳定且重要信息",
            "memory_capture",
            "Evidence 只是来源",
            "待治理 Candidate",
            "Current Atom",
            "字段、证据、作用域、排除项和数量限制",
            "以该 Tool 当前披露的合同为准",
            "不要猜内部 ID",
            "不要把候选说成“已经记住”",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("</durable-memory-policy>"), 1)
        self.assertNotIn("ime_memory", prompt)
        self.assertNotIn("explicit_user_request", prompt)
        self.assertNotIn("一轮最多提交三条", prompt)

    def test_work_policy_matches_request_type_and_requires_evidence(self) -> None:
        prompt = work_policy_prompt()

        for expected in (
            "回答、诊断、修改还是持续执行",
            "只有请求包含修复时才实施",
            "先读完整相关调用链",
            "计划、进度汇报",
            "不以",
            "代替完成",
            "避免无关重构和假想抽象",
            "实质改变权限、数据、兼容性或用户目标",
            "真实完成项、验证证据和剩余边界",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<work-policy>"), 1)
        self.assertEqual(prompt.count("</work-policy>"), 1)

    def test_managed_goal_policy_is_bounded_and_never_activates_ordinary_chat(self) -> None:
        prompt = managed_goal_policy_prompt()

        for expected in (
            "仅当系统明确交给你 Goal、Task 或 Room Dispatch 时生效",
            "普通聊天",
            "未确认计划不进入此循环",
            "当前 Task/Dispatch 是本轮权威工作单",
            "不据此接管父任务或其他成员的工作",
            "已获授权",
            "能产生新证据",
            "立即执行",
            "不以答复、计划或进度报告代替动作",
            "继续：",
            "完成：",
            "交接：",
            "等待：",
            "阻塞：",
            "全部验收项都有成功证据",
            "其他 Agent 或模型更合适",
            "准确接手点",
            "缺用户决定、授权或外部信号",
            "只问一个最小问题并说明恢复条件",
            "有界备选已耗尽",
            "证据和解除条件",
            "失败先读回执",
            "不原样空转",
            "Kernel 根据证据、权限、取消和预算裁决真实状态",
        ):
            self.assertIn(expected, prompt)
        for redundant in (
            "目录浏览、文本读取和文本搜索",
            "Shell 的 pwd、ls、find、cat、head、tail、grep、sed 或 awk",
            "不要替换解释器路径",
            "只更换调用 ID",
        ):
            self.assertNotIn(redundant, prompt)
        self.assertEqual(prompt.count("<managed-work>"), 1)
        self.assertEqual(prompt.count("</managed-work>"), 1)

    def test_ordinary_core_omits_managed_state_machine(self) -> None:
        prompt = core_agent_policy_prompt(
            "SAFETY",
            {
                "mode": "assistant",
                "title": "普通聊天",
                "queryText": "你好，解释一下这个概念",
                "executionMode": "workspace_managed",
                "workspaceRoots": ["/tmp/project"],
            },
        )

        self.assertLess(prompt.index("SAFETY"), prompt.index("<work-policy>"))
        self.assertLess(
            prompt.index("</work-policy>"),
            prompt.index("<durable-memory-policy>"),
        )
        self.assertLess(
            prompt.index("</durable-memory-policy>"),
            prompt.index("<execution-mode"),
        )
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertNotIn("<managed-work>", prompt)

    def test_goal_task_and_managed_template_include_state_machine(self) -> None:
        for label, managed_session in (
            ("goal", {"goalId": "goal:1"}),
            ("task", {"currentTaskId": "task:1"}),
            ("template", {"agentTemplateId": "worker"}),
        ):
            with self.subTest(managed_session=label):
                prompt = core_agent_policy_prompt(
                    "SAFETY",
                    {
                        **managed_session,
                        "executionMode": "per_action",
                    },
                )

                self.assertLess(
                    prompt.index("</durable-memory-policy>"),
                    prompt.index("<managed-work>"),
                )
                self.assertLess(
                    prompt.index("</managed-work>"),
                    prompt.index("<execution-mode"),
                )
                self.assertEqual(prompt.count("<managed-work>"), 1)


if __name__ == "__main__":
    unittest.main()
