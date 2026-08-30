# PAWOS 用户需求账本 · UR-195

> 导航：[UR-192–UR-194](PAWOS_REQUIREMENTS_192_194.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-196–UR-205](PAWOS_REQUIREMENTS_196_205.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-195 — Trace Agent 诊断页直接呈现原对话、实际动作和诊断对话入口

- **状态 / 优先级：** `current / P0 Trace Agent usability`
- **真实需求：** Trace Agent 诊断页在用户选择 Session、Room 或运行记录后，直接
  显示被诊断对象的原始对话内容，以及 Agent 实际执行的动作和工具调用时间线；
  页面还必须提供进入诊断 Agent 自己对话的明确入口，让用户可以继续询问、查看
  诊断过程和修复建议。
- **必须保留：** 原对话与实际动作/工具事件按权威时间线关联展示，不得只显示
  一段摘要、统计或“无数据”占位；诊断对象和诊断 Agent 对话的身份必须可区分，
  入口不得把用户带回错误的 Room/Session。
- **禁止：** 不得把诊断页做成脱离原始运行记录的静态报告，也不得把诊断 Agent
  的建议或修复状态写成已执行、已修复或已验收，除非有对应 Runtime 收据。
- **用户可见验收：** 选择一个真实对话记录后，用户无需离开诊断页即可看到原对话、
  Agent 动作和工具时间线；点击诊断 Agent 入口能进入对应诊断对话，并继续看到
  诊断结果和未验证边界。
- **原话依据：** “Trace Agent 诊断页要直接看到原对话、Agent 实际动作/工具时间线，并能跳进诊断 Agent 对话。”来源：当前继续任务，2026-08-28；当前 Codex 环境无逐条 turn ID，不伪造编号。

## 继续阅读 / 编辑

- 下一份：[UR-196–UR-205](PAWOS_REQUIREMENTS_196_205.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
