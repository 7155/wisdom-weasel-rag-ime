# 输入体验闭环

> Room: `input-experience`
> Stage: `quality-gate`
> Delivery: active
> Epoch: `input-origin`
> Emerged: `2026-07-01`
> Topology: `room`

## Requirement

保留 Rime 输入权威，让助手候选在删除、切换、选择和真实前台使用中可靠。

## Problem

原生输入、助手候选和异步响应存在上下文失效与前台证据缺口，旧候选可能在用户已经修改输入后再次出现。

## Decisions

- Rime / 万象继续拥有拼音解析、原生候选、翻页与普通数字键；助手候选只做可区分的增量补充。
- 删除、组合、焦点、应用或上下文变化必须使旧代助手候选失效，真实 Squirrel 前台是最终验收边界。

## Observable acceptance

- [x] Rime 始终负责拼音解析、原生候选和普通数字键，助手候选不会静默改写其顺序。 | refs: `doc-product-readme`, `commit-squirrel-rag-ime`
- [x] 删除、焦点或上下文变化会使旧代助手候选失效。 | refs: `session-claude-input-audit`, `commit-input-reliability`
- [ ] 在真实 Squirrel 中完成删除、应用切换、候选选择和持续输入的同代组合验收。 | refs: `doc-handoff-goal`

## Current delivery

Rime 边界、候选代际和旧响应失效已进入同一输入链路，正在等待真实 Squirrel 组合验收。

## Next move

在真实前台运行同代组合场景，并保存候选出现、失效与选择结果的可复查回执。

## Source refs

- `doc-product-readme`
- `session-claude-input-audit`
- `doc-handoff-goal`
- `commit-squirrel-rag-ime`
- `commit-input-reliability`
