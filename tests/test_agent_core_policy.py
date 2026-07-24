from __future__ import annotations

import unittest

from rag_ime.agent_core_policy import (
    core_agent_policy_prompt,
    durable_memory_policy_prompt,
    managed_goal_policy_prompt,
)


class AgentCorePolicyTests(unittest.TestCase):
    def test_durable_memory_policy_has_positive_triggers_and_strict_exclusions(self) -> None:
        prompt = durable_memory_policy_prompt()

        for expected in (
            "用户明确要求记住",
            "稳定偏好",
            "纠正",
            "项目决定",
            "可复用坑",
            "memory_capture",
            "preference",
            "project",
            "只把高置信度候选送入现有记忆治理管线",
            "临时进度",
            "未经确认的猜测",
            "密钥与隐私",
            "Room 私有草稿",
            "不得循环重试",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("</durable-memory-policy>"), 1)
        self.assertNotIn("ime_memory", prompt)

    def test_managed_goal_policy_is_bounded_and_never_activates_ordinary_chat(self) -> None:
        prompt = managed_goal_policy_prompt()

        for expected in (
            "仅当 Runtime 明确注入 Goal、Task 或 Room Dispatch 时启用",
            "普通对话",
            "用户尚未确认的计划不得进入持续执行循环",
            "与失败动作不同",
            "能产生新证据",
            "不得重复同一失败调用",
            "handoff",
            "建议的能力或模型",
            "只向用户询问一个",
            "wait",
            "blocked",
            "有界备选已经耗尽",
            "Kernel 依据验收证据",
            "取消栅栏",
            "预算和期限",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<managed-goal-policy>"), 1)
        self.assertEqual(prompt.count("</managed-goal-policy>"), 1)

    def test_core_policy_composes_safety_memory_and_execution_once(self) -> None:
        prompt = core_agent_policy_prompt(
            "SAFETY",
            {
                "executionMode": "workspace_managed",
                "workspaceRoots": ["/tmp/project"],
            },
        )

        self.assertLess(prompt.index("SAFETY"), prompt.index("<durable-memory-policy>"))
        self.assertLess(
            prompt.index("</durable-memory-policy>"),
            prompt.index("<managed-goal-policy>"),
        )
        self.assertLess(prompt.index("</managed-goal-policy>"), prompt.index("执行权限"))
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("<managed-goal-policy>"), 1)


if __name__ == "__main__":
    unittest.main()
