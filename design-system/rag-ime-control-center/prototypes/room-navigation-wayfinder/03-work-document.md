# Room 导航与项目图谱 · 实现执行

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
> Stage: `implementation-execution`
> 状态：active

## Current slice

把真实历史整理出的八个结果型 Room 投影为历史派生纸张 DAG，并让 docs、manifest、构建器、运行时 schema 和 UI 使用同一语义；历史日期保留为拓扑和来源证据，但不在总览形成时间轴或日期标签。路径自然分化与收拢，但不创建独立汇聚节点。

## Implemented result

- `00-map.md` 现在索引初始愿景、未抵达目的地、八个 Room、五个真实历史阶段、十四条带回执关系、贯穿式发布轨道和五段交付引擎。
- `project/*.md` 与 `rooms/*.md` 保存整理后的需求、问题、验收证据、出现时间、当前阶段、当前结果、下一步和来源。
- manifest 已移除需求、阶段、区域、航线和待办文案，只保留 Project / Room 身份、布局与 receipts。
- Python builder 生成项目级 `personal-agent.project-wayfinder.v2`，并从 docs 派生历史阶段、关系 receipts、发布轨道与证据进度。
- TypeScript parser 对愿景、目的地、Room、关系 receipts、无环拓扑、验收进度、交付链、TDD 内层归属、文档和来源失败关闭。
- Project Field 从左到右显示由真实历史约束的需求拓扑、七张需求型纸张、贯穿式真实验收轨道、未连接目的地和可点击 Room 详情；总览不显示时间轴或日期，统一产品架构不作为图面对象。
- Wayfinder Room 不再渲染不规则地形；七张收起纸张等宽等高，按稳定拓扑列排列，当前和需用户状态只改变悬边、边框、图标与文字。
- 收起纸张显示 `Observable acceptance` 已核验数量和连续进度条；自然阶段单独显示，不再把阶段序号当完成比例。
- 图中不存在独立汇聚节点；投影 schema 继续拒绝任何指向 `@destination` 的未验收关系。
- 总览相机按可见画布适配整张需求网络；默认浏览器尺寸下起点、八个 Room 和目的地都保持在导航栏上方。
- 初始愿景已恢复为 Personal Agent Workbench 的实际产品需求，不再用整理方法或 Agent 过程文案充当项目内容。

## Verification receipts

- Python 投影构建与 Luna 整理回执测试：见 `tests/test_project_field_projection_builder.py` 和 `tests/test_wayfinder_luna_curation.py`。
- TypeScript 投影、几何兼容和 Project Field 交互测试：见 `control-center-web/src/features/project-field/*.test.*`。
- 生成物：`control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json`。
- 显式时间轴版本已被用户退回实现执行；无时间轴版本在恢复来源中通过 11 项 Python、23 项前端、TypeScript 与生产构建检查，但合入 canonical 后仍须复跑，且用户可见浏览器验收前不能进入质量门。

## Inner method

测试驱动实现只在 `implementation-execution` 内循环：先写可观察合同测试，再修改 docs、构建器、schema 或 UI，最后运行聚焦测试与类型检查。本轮先以失败测试固定历史阶段、带回执关系、证据进度、七张等尺寸纸张和发布轨道，再修改 manifest、投影、React 与 CSS。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-field`
- `session-codex-project-reconstruction`
- `doc-handoff-goal`
- `doc-chat-summary-c4f0bf7d`
- `session-codex-019fc62d`
- `commit-room-self-bootstrap`
