# Agent 长任务连续性

> Room: `agent-continuity`
> Stage: `quality-gate`
> Delivery: active
> Epoch: `agent-room`
> Emerged: `2026-07-20`
> Topology: `room`

## Requirement

让长任务跨 Tool、压缩、恢复、模型切换和重连后仍沿同一目标继续。

## Problem

Provider 长时恢复、历史改写和多次重连的组合场景尚未形成同代闭环，目标与当前运行状态可能在边界处漂移。

## Decisions

- Session 是目标、当前分支和恢复位置的单一 Owner；Tool、压缩、模型切换与重连不得复制任务状态。
- 恢复必须沿同一原始目标继续，并留下可定位中断、改写或状态漂移的回执。

## Observable acceptance

- [x] 同一个原始目标跨 Tool 循环、压缩、模型切换、重连和恢复后保持一致。 | refs: `doc-prompt-runtime-audit`, `commit-room-governance`
- [x] Session 历史与当前分支只有一个权威 Owner，恢复不会复制或倒退当前任务状态。 | refs: `session-codex-room-recovery`, `commit-room-recovery`
- [ ] 当前安装代际可以回放组合场景，并从回执定位任何中断或状态漂移。 | refs: `doc-handoff-goal`

## Current delivery

Session、Tool 时间线、压缩恢复和当前状态 Owner 已完成分层收束，正在验证跨边界组合行为。

## Next move

用当前安装代际完成跨压缩、改写、模型切换与重连的同目标回放。

## Source refs

- `doc-handoff-goal`
- `session-codex-room-recovery`
- `doc-prompt-runtime-audit`
- `commit-room-governance`
- `commit-room-recovery`
