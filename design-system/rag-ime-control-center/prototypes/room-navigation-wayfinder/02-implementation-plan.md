# Room 导航与项目图谱 · 实现规划

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
> Stage: `implementation-planning`
> 状态：complete

## Observable target

用历史派生 DAG 还原项目从初始输入需求到 Project Field 的真实演化：初始愿景先进入第一个可验收 Room，随后按需求细化形成多个纵向 Room；历史日期只作为拓扑与来源证据，不在总览显示时间轴或日期。七张结果纸可点击进入详情，真实使用与发布作为贯穿式验收轨道，目的地保持未抵达。统一产品架构只作为内部运行约束，不成为图面对象。

## Vertical slices

1. 建立项目级权威 docs：初始愿景、目的地、八个 Room 和语义关系。
2. 精简 manifest：只保留身份、坐标、形状和来源 receipts。
3. 确定性构建 `ProjectWayfinderProjection`，校验完整 schema 与来源覆盖。
4. 先用失败测试约束出现时间、历史阶段、带回执连线、验收证据进度、贯穿式发布轨道、无独立汇聚节点和未连接目的地。
5. 将 Room 总览改为与现有 Control Center 一致的历史派生纸张图；七张结果纸等宽等高、按稳定拓扑列与内部基线对齐并留出明显空白，不显示时间轴或卡片日期，所有收起 Room 显示标题、整理后的需求、自然阶段和证据进度。
6. 默认绘制 `refines` / `led-to` 历史主线，聚焦时显示 `requires`；发布验收单独作为底部轨道，不绘制到目的地的完成连接。
7. 完成自动测试、构建、1672×941 同视口视觉对照和原生可见页面交接。

## Single owners

| Concern | Owner |
| --- | --- |
| Wayfinder 内容 | 本目录 Markdown |
| Room 身份、布局、receipts | reconstruction manifest |
| 派生投影 | Python builder |
| 浏览器边界校验 | TypeScript parser |
| 项目图交互 | Project Field React feature |
| 用户视觉结论 | 用户原生可见验收 |

## Exit criteria

- docs 与生成物可确定性重建且无漂移。
- 所有八个 Room 的需求、决定、阶段、验收和来源通过 Python / TypeScript 校验。
- UI 在收起状态不显示决定清单、过程术语或文档哈希，展开后直接显示权威 docs 中的决定与来源。
- 七张结果型 Room 纸张在总览中具有相同宽高和内部基线；阶段优先级不改变卡片尺寸。
- 默认总览及用户当前缩放下纸张和发布轨道不重叠；每个进度数字与填充比例都直接来自已核验验收项，并同时用文字表达。
- 质量门拥有同代测试、构建与可见浏览器证据。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-field`
- `session-codex-project-reconstruction`
