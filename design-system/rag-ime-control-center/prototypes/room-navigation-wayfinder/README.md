# Personal Agent Workbench Wayfinder 文档体系

> 资料截点：2026-08-04 23:59:59 +08:00
> 用途：把真实项目资料整理成可追溯、可构建、可点击验收的项目图谱。
> 当前状态：`project-field` 正在实现执行；项目目的地尚未抵达。

## 核心语义

- Project 从一份整理后的初始需求开始。
- Room 是一个可独立验收的纵向用户结果，不是聊天、工单、前端、后端或代码模块。
- 一个 Room 可以容纳一次或多次讨论，并由固定交付链持续推进。
- Room 按真实出现时间从左到右排布；连线只表达有来源回执的需求细化、历史导出或结果依赖，不表示技术模块调用图。
- 统一产品架构是所有 Room 的共同运行边界，不被画成一组技术模块岛。
- 汇聚是路径关系，不是独立节点；图中不存在额外的门、工单或状态 Owner。
- 目的地只有在所有必需 Room 完成质量门、独立复核和所需用户验收后才连接。

## 文档关系

```text
00-map.md                         项目愿景、Room 索引、关系与交付引擎
project/
  00-initial-vision.md            初始需求
  01-destination.md               项目目的地与完成条件
rooms/
  <room-id>.md                    每个 Room 的需求、问题、决定、验收、阶段和来源

project-field Room 的详细交付文档
  01-alignment-decision-packet.md
  decisions/*.md
  02-implementation-plan.md
  03-work-document.md
  04-quality-gate-pending.md
  05-independent-review-pending.md
  06-current-agent-handoff.md

real-project-reconstruction/
  reconstruction-manifest.v1.json  Room 身份、坐标与来源 receipts
reconciliation/
  wayfinder-luna-source-audit.v1.json  截止语料与人工裁决回执
audit/
  *.md                             用户反馈与质量路由记录
```

## 权威边界

1. 本目录 Markdown 是 Wayfinder 内容的权威来源。
2. manifest 只保存 Project / Room 身份、空间布局和来源 receipts，不保存需求、阶段、验收或 Room 关系。
3. `scripts/wayfinder_projection.py` 确定性解析 docs，生成 `personal-agent.project-wayfinder.v2`。
4. `scripts/build_project_field_projection.py` 将 docs 内容与 manifest 布局合成为前端投影。
5. Python 与 TypeScript 边界完整校验初始愿景、未抵达目的地、八个 Room、历史阶段、无环关系、验收证据进度、发布轨道、五段交付链、TDD 内层归属、文档哈希和来源引用。

## Room 交付引擎

```text
alignment-and-decision
  -> implementation-planning
  -> implementation-execution
       └─ test-driven-implementation
  -> quality-gate
  -> independent-review
```

Wayfinder 负责项目意义与空间定位；这条流程负责每个纵向 Room 如何交付。两者共享 Room 身份和回执，不建立第二份状态 Owner。

## 来源整理

- 截止语料索引包含 45 份历史项目文档、19 个去重主会话、5 个 exact alias ref、1338 条用户消息和 9 个代表提交。
- 当前前端投影选择 7 份项目文档、12 个主会话和 16 个提交作为有界 receipts。
- Luna Max 负责产生整理候选；结构校验和人工复核之后，内容才进入本目录 Markdown。
- 原始聊天、Tool 结果、助手推理、机器绝对路径和私有 packet 不进入前端投影。

## 当前验收边界

自动测试、构建和可见浏览器检查可以证明投影结构与交互没有明显回归；它们不能代替用户在原生可见页面上判断图谱是否符合自己的项目认知。当前接手入口见 [`06-current-agent-handoff.md`](06-current-agent-handoff.md)。
