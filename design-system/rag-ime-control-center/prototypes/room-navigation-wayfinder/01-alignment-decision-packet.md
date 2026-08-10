# Room 导航与项目图谱 · 需求对齐

<!-- user-source:start -->
## User Source — Preserve Verbatim

### Original User Request

Source: current user message; UTF-8 SHA-256: `7ba9709702903cc40670b7a7b3357ed2efa8b09b480e62a99d42a037d49d37de`

> 用对齐等技能，完成本任务

### Original User Vision

Source: preceding user correction; UTF-8 SHA-256: `9af2bef4c6027c1de208681c6a8b52ea90342de94b1f4cbc49cabe635872767b`

> 重做“汇聚门不必要吧，这个汇聚门是干什么的

### Later User Corrections

- Source: user confirmation; UTF-8 SHA-256: `f867f34178594f891eb70a4260f62b1d9289cfa60394f9fee1cbbe4a8b4bf436`
  > 好
<!-- user-source:end -->

## AI Interpretation

> Room: `project-field`
> Stage: `alignment-and-decision`
> 状态：complete

## Curated requirement

让用户从 Project 初始愿景出发，找到、理解并继续正确的结果型 Room；未展开纸面直接显示整理后的需求和当前交付阶段，展开后直接显示决定、问题、验收、完整交付链与来源。

## Boundaries

- Room 按可独立验收的纵向用户结果划分，不按聊天、工单、前端、后端或代码模块划分。
- 一个 Room 可以包含多个讨论和实现切片，但必须保持同一用户结果。
- 连线只表达带来源回执的 `refines`、`led-to` 或 `requires`；位置按 Room 的真实出现时间从左到右排列。
- 起点只进入第一个真实输入 Room，后续需求可以分化为多个纵向 Room；目的地在全部必需 Room 验收前不连接。
- 汇聚是路径关系，不是独立节点；不创建额外的门、Room 或流程状态。
- UI 投影 Room 与 Runtime 状态，不复制 Project、Room、Session、权限、取消、记忆或终态 Owner。

## Decisions

- [Project 是长期空间](decisions/01-project-is-a-space.md)
- [Room 不是工单](decisions/02-room-is-an-outcome.md)
- [聚焦不离开项目](decisions/03-focus-stays-in-project.md)
- [导航只决定归属](decisions/04-navigator-only-routes.md)

## Observable acceptance

- 八个 Room 都能在未展开状态说明所解决的用户问题和一个短阶段；决定、问题、验收、来源与完整交付链在展开后直接读取。
- 初始输入需求、后续 Room 分化、贯穿式真实验收轨道和未连接目的地在一张图上清楚可见，不出现独立汇聚节点。
- 点击 Room 后仍处于同一 Project，并能查看需求、问题、交付结果、下一步、交付链和来源。
- 后台 Room 的注意力状态可见但不抢走当前 Room。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-field`
- `session-codex-project-reconstruction`
