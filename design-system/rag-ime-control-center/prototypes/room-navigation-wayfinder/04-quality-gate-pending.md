# Room 导航与项目图谱 · 质量门

> Room: `project-field`
> Stage: `quality-gate`
> 状态：pending

## Evidence matrix

| Requirement | Evidence | State |
| --- | --- | --- |
| manifest 只拥有身份、布局和 receipts | Python boundary test | pass |
| docs 确定性生成八个 Room、五个历史阶段、十四条带回执关系和发布轨道 | Python builder test | pass |
| 愿景、目的地、Room、决定、关系、进度、阶段、TDD、文档和来源漂移时失败关闭 | Python + TypeScript mutation tests | pass |
| 收起的纸张 Room 只显示标题、整理后的需求和准确阶段，不显示旧过程文案 | React component test | pass |
| 汇聚只由路径关系表达，不存在独立节点 | Python contract + React component test | pass |
| 点击 Room 直接显示决定、问题、当前交付、下一步、五段交付链与来源 | React interaction test | pass |
| 初始愿景只进入第一个真实 Room，历史随后分化，目的地保持未连接 | Python + React contract | pass |
| 七张纸等宽等高、按历史拓扑稳定排列且发布轨道独立贯穿 | React component test | pass |
| 总览不显示时间轴、日期刻度、卡片日期或发布检查点日期 | React component test | pass |
| 证据进度来自已核验验收项，且与自然阶段分离 | Python + TypeScript + React contract | pass |
| 当前代际在用户可见浏览器中无重叠且信息可读 | 原生页面复现 | blocked_no_visible_browser |
| 当前视觉在用户浏览器中符合项目认知 | 用户原生可见验收 | changes_requested |

## Gate rule

自动测试、构建、截图、健康状态或终端状态都不能单独替代原生可见验收。只有当前实现代际在用户可见浏览器中复现，且用户确认项目语义清楚，才能进入独立复核。

显式时间轴代际已被用户以“不要时间，太丑了”退回实现执行。此前可见几何、详情展开和焦点恢复证据仍可用于定位回归，但不能证明修改后的岛面，也不能支持当前代际进入质量门。无时间轴版本必须重新运行同代检查并在用户可见浏览器中复现。

## Previous run · 2026-08-05 · invalidated by visible UI change

- Python：`tests.test_project_field_projection_builder` 与 `tests.test_wayfinder_luna_curation`，11 项通过。
- 前端：Project Field 投影、交互、几何兼容、路由和 AppShell，23 项通过。
- TypeScript：`pnpm run typecheck` 通过。
- 生产构建：`pnpm run build` 通过；仅保留既有大 chunk 警告。
- 确定性投影：从完整来源重建并核验，8 Rooms、7 docs、12 sessions、16 commits 一致。
- 原生可见复现：显式时间轴 DAG、证据进度、发布轨道、详情展开与 Escape 返回曾在当前 Edge 标签中复现；用户已要求修改，因此本条不再代表当前实现。
- 固定差异独立复查：此前三项必修修复通过；本轮规整布局变更尚未进入新的独立复核，须在用户通过后执行。

## Current implementation run · 2026-08-05

- Python：`tests.test_project_field_projection_builder` 与 `tests.test_wayfinder_luna_curation`，11 项通过。
- 前端：Project Field 投影、交互、几何兼容、路由和 AppShell，23 项通过。
- TypeScript：`pnpm run typecheck` 通过。
- 生产构建：`pnpm run build` 通过；仅保留既有大 chunk 警告。
- 确定性投影：从完整来源重建并核验，8 Rooms、7 docs、12 sessions、16 commits 一致。
- 原生可见复现：当前没有可连接的用户可见浏览器实例；未使用隐藏浏览器、截图、health 或 terminal state 替代。
- 质量路由：保持 `implementation-execution`，重新连接可见浏览器后再评估是否进入质量门。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-reconstruction`
- `doc-handoff-goal`
