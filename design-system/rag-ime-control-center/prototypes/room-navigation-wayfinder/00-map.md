# Personal Agent Workbench Wayfinder

> Project: `personal-agent-workbench`
> Current Room: `project-field`
> Status: active

## Initial vision

- [可靠的 macOS AI 输入辅助](project/00-initial-vision.md) — 从保留 Rime 权威、让 AI / RAG 辅助真正进入 macOS 输入前台这一初始需求开始。

## Destination

- [可持续交付的个人 Agent 工作台](project/01-destination.md) — 让每个用户结果都能被找到、继续、验收，并在全部交付后共同收敛到项目愿景。

## Rooms

- [输入体验闭环](rooms/input-experience.md) — 保留 Rime 输入权威，让助手候选在删除、切换、选择和真实前台使用中可靠。
- [受控项目记忆](rooms/governed-memory.md) — 从不可变用户来源形成 Evidence、Atom、Book，使知识可追溯、可晋升、可撤销。
- [统一产品工作台](rooms/unified-workbench.md) — 让输入、Agent、Room、记忆和工具在同一内容优先的 Control Center 中保持清晰所有权。
- [Room 协作交付](rooms/room-delivery.md) — 让一个 Room 围绕一个用户结果组织多 Agent、工作区、交接、质量和终态。
- [Agent 长任务连续性](rooms/agent-continuity.md) — 让长任务跨 Tool、压缩、恢复、模型切换和重连后仍沿同一目标继续。
- [工作流与能力收敛](rooms/workflow-system.md) — 用固定外层流程推进对齐、规划、执行、质量验证和独立复核，并保持 Tool、Todo、LSP 和文档单一 Owner。
- [Room 导航与项目图谱](rooms/project-field.md) — 让用户从 Project 初始愿景出发，找到、理解并继续八个正确的结果型 Room；纸张表面显示整理后的需求和阶段状态，点击后查看决定、问题、验收、交付与来源。
- [真实使用与发布](rooms/release-journey.md) — 把已实现能力推进成可安装、可验证、可恢复并能公开交付的真实产品。

## Relations

- `@origin` -> `input-experience` | `refines` | 初始输入愿景先形成可靠候选这一可独立验收结果。 | refs: `commit-squirrel-rag-ime`
- `input-experience` -> `governed-memory` | `led-to` | 输入历史与候选召回暴露出需要可整理、可追溯本地记忆。 | refs: `commit-memory-database`
- `input-experience` -> `unified-workbench` | `led-to` | 输入设置、诊断与记忆管理逐步需要统一的原生 Control Center。 | refs: `commit-native-control-center`
- `unified-workbench` -> `room-delivery` | `led-to` | Control Center 从输入管理扩展为 Agent、Room 与角色协作工作区。 | refs: `commit-room-web`
- `room-delivery` -> `agent-continuity` | `led-to` | Room 协作把 Session、恢复、重连与同一目标连续性变成独立结果。 | refs: `commit-room-governance`, `commit-room-recovery`
- `room-delivery` -> `workflow-system` | `led-to` | 多 Agent 交付需要对齐、执行、证据和终态使用同一受治理流程。 | refs: `commit-agent-room-runtime`, `commit-governed-workflow`
- `agent-continuity` -> `workflow-system` | `requires` | 可恢复工作流必须沿同一目标与当前 Session 状态继续。 | refs: `doc-prompt-runtime-audit`, `commit-agent-room-runtime`
- `unified-workbench` -> `project-field` | `requires` | Project Field 必须留在同一产品壳层与工作台交互语言中。 | refs: `doc-project-field-contract`, `commit-product-identity`
- `governed-memory` -> `project-field` | `requires` | 项目图谱需要可追溯来源，但不能复制或静默写回 Memory Owner。 | refs: `doc-memory-pipeline`, `session-codex-project-field`
- `workflow-system` -> `project-field` | `led-to` | Room 交付状态和来源分散后，产生了按真实演化理解并继续项目的需求。 | refs: `session-codex-project-field`, `commit-room-self-bootstrap`
- `input-experience` -> `release-journey` | `requires` | 真实发布必须包含 Squirrel 前台与同代候选验收。 | refs: `commit-runtime-release-gates`
- `room-delivery` -> `release-journey` | `requires` | Room 的取消、恢复、审批和终态必须进入同代发布矩阵。 | refs: `doc-handoff-goal`, `commit-room-waves`
- `workflow-system` -> `release-journey` | `requires` | 发布结论需要受治理工作流保存新鲜验证证据。 | refs: `commit-governed-workflow`
- `project-field` -> `release-journey` | `requires` | 当前 Project Field 仍需用户原生可见验收后才能进入发布候选。 | refs: `doc-project-field-contract`, `session-codex-project-reconstruction`

## Evolution epochs

- `input-origin` | `2026-07-01` | `7 月 1 日` | Rime / Squirrel AI 辅助进入真实输入前台。
- `memory-control` | `2026-07-04/2026-07-10` | `7 月 4—10 日` | 本地记忆与原生 Control Center 从输入需求中分化。
- `agent-room` | `2026-07-14/2026-07-20` | `7 月 14—20 日` | Agent、Room、恢复与治理形成可交付协作结果。
- `product-convergence` | `2026-07-27/2026-08-01` | `7 月 27 日—8 月 1 日` | 产品身份、Agent / Room Runtime 与受治理工作流收敛。
- `project-field` | `2026-08-04` | `8 月 4 日以后` | 长期项目需要从真实历史找到正确 Room 并继续。

## Release lane

- Room: `release-journey`
- `2026-07-01` | `Squirrel 真实输入` | `commit-squirrel-rag-ime`
- `2026-07-11` | `Runtime 与发布门` | `commit-runtime-release-gates`
- `2026-07-20` | `Room 治理与恢复` | `commit-room-governance`
- `2026-08-01` | `工作流与前台证据` | `commit-governed-workflow`
- `2026-08-04` | `历史记忆治理` | `commit-historical-memory`

## Delivery engine

- `alignment-and-decision` | 需求对齐
- `implementation-planning` | 实现规划
- `implementation-execution` | 实现执行
- `quality-gate` | 质量门
- `independent-review` | 独立复核
- Inner method: `test-driven-implementation` -> `implementation-execution` | 测试驱动实现

## Source refs

- `doc-project-field-contract`
- `session-codex-project-field`
- `session-codex-project-reconstruction`
- `commit-squirrel-rag-ime`
- `commit-memory-database`
- `commit-native-control-center`
- `commit-runtime-release-gates`
- `commit-room-web`
- `commit-room-governance`
- `commit-personal-agent-identity`
- `commit-historical-memory`
