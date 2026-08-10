# Room 协作交付

> Room: `room-delivery`
> Stage: `implementation-execution`
> Delivery: active
> Epoch: `agent-room`
> Emerged: `2026-07-14`
> Topology: `room`

## Requirement

让一个 Room 围绕一个用户结果组织多 Agent、工作区、交接、质量和终态。

## Problem

Room 容易退化成工单列表或聊天集合，真实文件修改、取消、重连、图片和破坏性审批的组合交付仍不完整。

## Decisions

- 一个 Room 围绕一个可验收的用户结果组织协作，而不是按前端、后端、聊天或工单拆分。
- 参与 Agent 保留私有 Session；交接、证据、审批与终态通过 Room 的受控回执协作。

## Observable acceptance

- [x] 一个 Room 能围绕同一用户结果组织并行任务、结构化交接、证据提交和确定性终态。 | refs: `doc-room-workflow`, `commit-room-web`, `commit-room-governance`
- [x] 多个 Agent 保留私有 Session，不各自复制任务或工作区 Owner。 | refs: `session-claude-room-audit`, `commit-room-autonomy`
- [ ] 文件修改、取消、重连、冲突、图片和破坏性审批进入同一可恢复交付矩阵。 | refs: `commit-room-waves`

## Current delivery

多成员任务、公开结果、共同复核和确定性终态已有真实实现，正在补齐高风险组合场景。

## Next move

把文件修改、取消、重连、图片和破坏性审批压进同一个可恢复、可审计的 Room 交付矩阵。

## Source refs

- `doc-room-workflow`
- `session-claude-room-audit`
- `session-pi-room-bootstrap`
- `session-omp-adaptation`
- `commit-room-web`
- `commit-room-governance`
- `commit-room-autonomy`
- `commit-room-waves`
