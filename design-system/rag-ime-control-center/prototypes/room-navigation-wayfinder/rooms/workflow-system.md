# 工作流与能力收敛

> Room: `workflow-system`
> Stage: `implementation-execution`
> Delivery: active
> Epoch: `product-convergence`
> Emerged: `2026-07-31`
> Topology: `room`

## Requirement

用固定外层流程推进对齐、规划、执行、质量验证和独立复核，并保持 Tool、Todo、LSP 和文档单一 Owner。

## Problem

技能、Prompt、测试驱动实现、质量门、归档和 Runtime 状态之间仍有适配缺口，容易形成第二套流程或状态源。

## Decisions

- 外层交付固定为需求对齐、实现规划、实现执行、质量门和独立复核五段。
- 测试驱动实现只属于实现执行内层；Tool、Todo、LSP、文档和 Runtime 保持各自单一 Owner。

## Observable acceptance

- [x] 外层阶段严格为需求对齐、实现规划、实现执行、质量门和独立复核五段。 | refs: `session-codex-project-field`, `commit-governed-workflow`
- [x] 测试驱动实现只属于 implementation-execution 内层，不成为第六个外层阶段。 | refs: `session-codex-omp-adaptation`, `session-omp-prompt-todo-lsp`
- [ ] Tool、Todo、LSP、文档和 Runtime 各自只有一个权威 Owner，并通过真实 Room 回执联动。 | refs: `doc-prompt-runtime-audit`

## Current delivery

技能链、Prompt 顺序、能力披露和状态 Owner 已形成统一方向，正在接入真实 Room 交付状态。

## Next move

让执行、测试驱动实现、质量门、独立复核和文档归档按同一 Room 状态联动。

## Source refs

- `session-codex-project-field`
- `session-codex-omp-adaptation`
- `session-omp-prompt-todo-lsp`
- `doc-prompt-runtime-audit`
- `commit-agent-room-runtime`
- `commit-governed-workflow`
