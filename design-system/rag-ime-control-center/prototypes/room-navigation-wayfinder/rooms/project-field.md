# Room 导航与项目图谱

> Room: `project-field`
> Stage: `implementation-execution`
> Delivery: active
> Epoch: `project-field`
> Emerged: `2026-08-04`
> Topology: `room`

## Requirement

让用户从 Project 初始愿景出发，找到、理解并继续八个正确的结果型 Room；纸张表面显示整理后的需求和阶段状态，点击后查看决定、问题、验收、交付与来源。

## Problem

长期项目经过多次讨论和实现后，需求、当前进度与验收结果散落在不同 Room 中，用户难以快速判断项目为何存在、现在应继续哪里以及离最终愿景还有什么差距。

## Decisions

- 图谱只把初始愿景、结果型 Room、贯穿式真实验收轨道和最终愿景作为项目对象；共享架构是实现约束，不成为图上节点。
- 主图由真实历史决定从左到右的 DAG 拓扑；Room 可以分化、细化和依赖，但连线必须是有来源回执的 `refines`、`led-to` 或 `requires`，不能为视觉效果随意连接。总览不显示时间轴、日期刻度或卡片日期，日期只在详情和来源 receipts 中按需读取。
- 收起纸张只显示标题、整理后的需求和短阶段；决定、验收、来源与完整交付链在一次点击后直接读取。
- 七张结果型 Room 纸张使用统一尺寸与内部基线，并按历史阶段形成稳定列；`真实使用与发布` 不再伪装成项目末尾的一张卡，而是作为贯穿底部的长期验收轨道。
- Room 之间保留足够行列空白；每张纸的进度显示已通过的可观察验收证据数量，而阶段标签只说明当前工作处于哪里，两者不得相互推算。
- docs 拥有 Wayfinder 内容，manifest 只拥有 Room 分界、布局与来源 receipts，生成物由确定性构建器产生。

## Observable acceptance

- [x] 每个 Room 在未展开时就能说明它解决什么用户问题和当前阶段；决定、问题、验收与来源在展开后读取。 | refs: `doc-project-field-contract`, `session-codex-project-field`
- [x] docs、manifest 和生成投影保持单一权威边界，并对 Room、关系、阶段、来源与可观察验收做完整校验。 | refs: `session-codex-project-reconstruction`, `commit-room-self-bootstrap`
- [x] 七张结果纸等宽等高、按历史拓扑形成稳定列，当前状态不改变卡片尺寸，岛面不显示日期。 | refs: `doc-project-field-contract`
- [x] 真实使用与发布作为贯穿式轨道呈现；目的地在全部必需验收完成前保持未抵达。 | refs: `doc-handoff-goal`, `session-codex-project-field`
- [x] 点击纸张后看到同一 Room 的需求、决定、交付、证据进度和来源详情，关闭后回到原项目位置。 | refs: `session-codex-project-field`
- [ ] 在用户原生可见浏览器中，三秒内读出起点、历史分化、当前位置、证据进度和下一步，并给出验收结论。 | refs: `doc-handoff-goal`

## Current delivery

八个 Room 的边界和来源回执已固定。总览时间轴、卡片日期和发布检查点日期已移除，真实历史仍约束拓扑、连线和来源证据；同代自动检查已通过，但当前没有可连接的用户可见浏览器，因此仍处于实现执行。

## Next move

重新连接用户可见浏览器，复现无时间轴纸张图；完成原生可见检查后，再请用户判断是否能快速读出起点、需求分化、当前位置、证据进度和下一步。

## Delivery docs

- [需求对齐与决定](01-alignment-decision-packet.md) — 保存这个 Room 已确认的用户结果与边界。
- [实现规划](02-implementation-plan.md) — 保存纵向交付切片与退出条件。
- [实现执行](03-work-document.md) — 保存已实施结果和验证回执。
- [质量门](04-quality-gate-pending.md) — 保存进入质量门所需的可观察证据。
- [独立复核](05-independent-review-pending.md) — 保存独立复核的进入条件与结论。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-field`
- `session-codex-project-reconstruction`
- `doc-handoff-goal`
- `doc-chat-summary-c4f0bf7d`
- `session-codex-019fc62d`
- `commit-room-self-bootstrap`
