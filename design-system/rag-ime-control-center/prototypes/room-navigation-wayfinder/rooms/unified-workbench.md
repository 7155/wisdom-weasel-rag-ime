# 统一产品工作台

> Room: `unified-workbench`
> Stage: `implementation-execution`
> Delivery: active
> Epoch: `memory-control`
> Emerged: `2026-07-10`
> Topology: `room`

## Requirement

让输入、Agent、Room、记忆和工具在同一内容优先的 Control Center 中保持清晰所有权。

## Problem

产品身份与共享工作区已有基线，但 Project / Room 导航尚未作为真实领域投影融入同一产品体验。

## Decisions

- 输入、Agent、Room、记忆和工具属于同一个 Control Center，不建立平行产品或第二套主导航。
- UI 只投影 Runtime、权限、取消与终态；这些状态继续由各自单一 Owner 管理。

## Observable acceptance

- [x] 输入、Agent、Room、记忆和工具位于同一工作台，不形成平行产品。 | refs: `commit-native-control-center`, `commit-personal-agent-identity`
- [x] UI 只投影 Runtime、权限、取消和终态，不复制这些状态的 Owner。 | refs: `doc-product-readme`, `session-claude-ui-redesign`
- [ ] Project Field 与已有 Session、Room、Tool 和记忆界面使用一致的导航与交互语言。 | refs: `session-claude-ui-redesign`

## Current delivery

产品身份、共享纸张工作区和单一前端投影边界已经统一，正在接入 Project Field 的结果型导航。

## Next move

让 Project Field 复用现有设计系统和 Room 能力，并验证聚焦与返回仍处于同一产品上下文。

## Source refs

- `doc-product-readme`
- `session-claude-ui-redesign`
- `commit-native-control-center`
- `commit-personal-agent-identity`
- `commit-product-identity`
