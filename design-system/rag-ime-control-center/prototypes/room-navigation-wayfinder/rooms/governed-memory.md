# 受控项目记忆

> Room: `governed-memory`
> Stage: `implementation-execution`
> Delivery: active
> Epoch: `memory-control`
> Emerged: `2026-07-04`
> Topology: `room`

## Requirement

从不可变用户来源形成 Evidence、Atom、Book，使知识可追溯、可晋升、可撤销。

## Problem

用户来源、项目文档、Project Map 与正式记忆之间缺少自动但受控的适配边界，容易把整理结果误当作事实或静默写回个人记忆。

## Decisions

- 不可变用户来源依次形成 Evidence、Atom 与 Book；每次晋升、归档和回滚都必须可追溯、可撤销。
- Project Map 只引用项目来源，不拥有或静默写回个人记忆；整理结果不能自动升级为事实。

## Observable acceptance

- [x] 每项知识都能从 Book 回溯到 Atom、Evidence 和不可变用户来源。 | refs: `doc-memory-pipeline`, `commit-memory-database`
- [x] 晋升、归档和回滚都有显式回执并可撤销。 | refs: `doc-memory-pipeline`, `commit-historical-memory`
- [ ] Project Map 只引用项目来源，不静默写入或拥有个人 Memory。 | refs: `session-codex-project-field`

## Current delivery

用户来源、证据账本、Atom、Book、回滚和文档边界已经对齐，正在实现地图与项目知识的受控适配。

## Next move

让文档投影自动更新且可撤销，并让跨 Room 知识候选经过证据审查后再晋升。

## Source refs

- `doc-memory-pipeline`
- `session-pi-memory-pipeline`
- `session-codex-project-field`
- `commit-memory-database`
- `commit-historical-memory`
- `commit-governed-workflow`
