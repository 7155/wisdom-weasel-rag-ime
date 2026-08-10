# 真实使用与发布

> Room: `release-journey`
> Stage: `implementation-planning`
> Delivery: queued
> Epoch: `input-origin`
> Emerged: `2026-07-01`
> Topology: `release-lane`

## Requirement

把已实现能力推进成可安装、可验证、可恢复并能公开交付的真实产品。

## Problem

源码、构建、局部检查和截图不能替代真实前台、正式安装、签名、公证、干净机器与公开分发验证。

## Decisions

- 构建、截图、Mock、health 与终端状态只能证明各自边界，不能替代真实前台和用户可见验收。
- 发布候选必须来自同一安装代际，并通过安装、回滚、签名、公证、stapling 与干净机器验证。

## Observable acceptance

- [x] 源码、测试、构建和真实前台证据边界被明确区分，发布门有可追溯回执。 | refs: `doc-product-readme`, `commit-runtime-release-gates`
- [ ] 完成真实前台矩阵，并证明候选、Room、Tool 与恢复行为来自同一安装代际。 | refs: `doc-handoff-goal`
- [ ] 完成签名、公证、stapling、公开包与干净机器核心路径验证。 | refs: `doc-product-readme`, `doc-handoff-goal`

## Current delivery

源码、测试和部分安装态回执已经明确区分实现、构建与真实可用，发布航程等待核心体验收束。

## Next move

核心 Room 完成质量门与独立复核后，冻结同代安装候选并执行前台与发布矩阵。

## Source refs

- `doc-product-readme`
- `doc-handoff-goal`
- `commit-squirrel-rag-ime`
- `commit-runtime-release-gates`
- `commit-governed-workflow`
- `commit-historical-memory`
