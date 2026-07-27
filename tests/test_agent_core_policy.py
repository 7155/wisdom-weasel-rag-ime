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
            "明确要求记住、以后遵守或不要再犯",
            "会改变以后协作方式的长期偏好",
            "用户纠正了你",
            "用户确认了会影响后续工作的决定",
            "希望以后能够衔接的重要经历、计划或里程碑",
            "明确肯定了一个具体、可复用的做法",
            "未来仍会复用的项目事实或踩坑结论",
            "memory_capture",
            "未提供时不要改用其他工具的兼容操作",
            "调用和回执仍作为正常工具活动记录",
            "Evidence 保留来源",
            "不自动成为事实",
            "捕获动作只提交一条 Candidate",
            "Current Atom",
            "Topic Book",
            "关系、标签和纠正沿革形成可检索图",
            "Timeline 只保留任务连续性",
            "Role Book 只描述 Agent 自身",
            "Room 公开交付",
            "输入法最终输入和语音最终文本",
            "Room 私有过程不能写成用户事实",
            "claim：一条可独立理解",
            "preference、fact、decision、correction 或 pitfall",
            "未来 Session",
            "跨项目适用的用户信息选 user",
            "只属于当前项目的事实与约束选 project",
            "explicit_user_request",
            "explicit_user_statement",
            "user_correction",
            "repeated_user_signal",
            "当前可见上下文中至少两条独立用户证据",
            "verified_outcome",
            "只有当前上下文给出精确 Evidence ID 时才填写",
            "supersedes",
            "不要猜内部 Atom、Book、关系或证据 ID",
            "同一项目的组织与关系由治理链",
            "同一事实每轮最多提交一次",
            "一轮最多提交三条",
            "已公开且有证据的交付",
            "待治理候选",
            "不要宣布“已经记住”",
            "临时进度",
            "猜测",
            "敏感信息",
            "泛泛表扬",
            "普通寒暄",
            "Room 私有过程",
            "没有指出具体可复用做法的礼貌反馈",
            "调用失败不循环重试",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("</durable-memory-policy>"), 1)
        self.assertNotIn("ime_memory", prompt)

    def test_managed_goal_policy_is_bounded_and_never_activates_ordinary_chat(self) -> None:
        prompt = managed_goal_policy_prompt()

        for expected in (
            "系统明确交给你 Goal、Task 或 Room Dispatch 时生效",
            "普通聊天",
            "用户尚未确认的计划不进入任务循环",
            "只执行其中的责任与验收",
            "不能据此接管父任务或其他成员的工作",
            "能产生新证据",
            "实际执行它",
            "不要只回复“继续”",
            "继续：",
            "完成：",
            "交接：",
            "等待：",
            "阻塞：",
            "全部验收项都有成功工具或运行证据",
            "另一位 Agent 或模型更合适",
            "目标能力",
            "准确接手点",
            "缺用户决定、授权或外部信号",
            "只问一个最小必要问题",
            "有界备选已经耗尽",
            "阻塞证据和解除条件",
            "不要重复同一失败动作空转",
            "先读取回执原因",
            "不得只更换调用 ID 就重发同一工具和完全相同的参数",
            "目录浏览、文本读取和文本搜索能由专用工作区工具完成时",
            "不得改用 Shell 的 pwd、ls、find、cat、head、tail、grep、sed 或 awk",
            "不要替换解释器路径，也不要添加 cd、管道、重定向或命令串",
            "不能靠重复 Prompt 维持循环",
            "Kernel 根据证据、权限、取消和预算决定真实状态",
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("<managed-work>"), 1)
        self.assertEqual(prompt.count("</managed-work>"), 1)

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
            prompt.index("<managed-work>"),
        )
        self.assertLess(prompt.index("</managed-work>"), prompt.index("<execution-mode"))
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("<managed-work>"), 1)


if __name__ == "__main__":
    unittest.main()
