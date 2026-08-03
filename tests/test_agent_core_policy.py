from __future__ import annotations

import unittest

from rag_ime.agent_core_policy import (
    core_agent_policy_prompt,
    durable_memory_policy_prompt,
    managed_goal_policy_prompt,
    todo_policy_prompt,
    work_policy_prompt,
)


class AgentCorePolicyTests(unittest.TestCase):
    def test_durable_memory_policy_keeps_only_the_stable_governance_boundary(self) -> None:
        prompt = durable_memory_policy_prompt()

        for expected in (
            "用户稳定偏好、个人事实、长期原则和持续约束",
            "memory_capture",
            "原始对话、会话摘要、工具回执",
            "必须绑定当前用户消息",
            "不得从助手回答、工具结果或运行状态推导",
            "一次性请求、当前任务步骤",
            "字段、作用域和数量限制",
            "以该 Tool 当前披露的合同为准",
            "不要猜内部 ID",
            "不要把候选说成“已经记住”",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("</durable-memory-policy>"), 1)
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
            "任务的当前状态与下一步以最新用户消息和本轮动态状态投影为准",
            "仍可界定目标或提供证据",
            "不能重新激活已完成、已取消或已被替代的工作",
            "避免无关重构和假想抽象",
            "用户目标、范围、验收、权限、数据、兼容性、可观察行为",
            "可检查的事实自己查",
            "授权内的可逆默认自己定",
            "无法获取的外部事实标记阻塞",
            "明确要求 Grill",
            "真实完成项、验证证据和剩余边界",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<work-policy>"), 1)
        self.assertEqual(prompt.count("</work-policy>"), 1)

    def test_todo_policy_keeps_the_execution_checklist_current(self) -> None:
        prompt = todo_policy_prompt()

        for expected in (
            "至少三个清晰动作",
            "用户给出多项要求",
            "任务名保持稳定、具体且 5-10 个词",
            "不得改写、重排或制造 task-1",
            "不能让一次 todo 调用成为",
            "整轮唯一动作",
            "当前只允许一个 in_progress",
            "立即同步",
            "block",
            "unblock",
            "不替代用户回复、最终结果或证据报告",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<todo-policy>"), 1)
        self.assertEqual(prompt.count("</todo-policy>"), 1)

    def test_material_ambiguity_routes_through_alignment_then_native_ask(self) -> None:
        prompt = work_policy_prompt()

        for expected in ("先加载", "alignment-and-decision", "原生 ask", "最小的成组选择"):
            self.assertIn(expected, prompt)
        self.assertLess(prompt.index("alignment-and-decision"), prompt.index("原生 ask"))

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
        self.assertLess(prompt.index("</work-policy>"), prompt.index("<todo-policy>"))
        self.assertLess(
            prompt.index("</todo-policy>"),
            prompt.index("<durable-memory-policy>"),
        )
        self.assertEqual(prompt.count("<todo-policy>"), 1)
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertNotIn("<managed-work>", prompt)
        self.assertNotIn("<execution-mode", prompt)

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
                self.assertEqual(prompt.count("<managed-work>"), 1)
                self.assertNotIn("<execution-mode", prompt)


if __name__ == "__main__":
    unittest.main()
