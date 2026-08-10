# Room 不是工单

> 状态：closed
> 类型：domain decision

## Question

一座岛应该对应功能、工单、聊天线程，还是用户能够理解和继续的结果边界？

## Resolution

一座岛对应一个 Room；一个 Room 对应一个用户管理的结果与连续上下文。它可以包含多个相互约束的功能方向、多个独立验证的执行切片和多个 Agent 的并行工作。

只有目标、上下文和验收结果真正独立，且值得用户分别管理时，才建立关联 Room。内部计划项不会自动升级成新 Room。

## Rejected alternatives

- `Room = 单个功能`：同一目标会被拆成用户无法维护的多个聊天空间。
- `Room = Spec / Issue`：把内部交付结构暴露成产品一级导航。
- `一个清晰结果 = 多个默认 Room`：增加用户注意力负担，也让跨 Room 同步成为人为问题。

## Basis

- 用户明确纠正“一 Room 一功能”的岛屿模型。
- 2026-08-01 的 Room autonomous acceptance 记录显示，一个真实 Room 能完成并行推进、共同复核和终局回复，支持把 Room 视为完整交付边界。

## Source refs

- `session-codex-project-field`
- `commit-room-self-bootstrap`
