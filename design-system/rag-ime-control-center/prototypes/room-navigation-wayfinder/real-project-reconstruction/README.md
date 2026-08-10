# Personal Agent Workbench 真实项目资料重建

> 事实源：`.worktrees/personal-agent-workbench-main-release`
> 快照：`main@8a50a6b21ced` 加截止时工作文档
> 时间窗：2026-07-19 至 2026-08-04 23:59:59 +08:00
> 输出：八个纵向需求 Room 的只读 Project Field 投影

这是一份可追溯的回顾重建，不是生产 Project / Room 数据库导出。它从真实需求、项目文档、主 Agent 会话和代表提交中恢复 Room 边界与来源，再由上级权威 Markdown 整理为项目愿景、Room 需求、验收、交付阶段和关系。

## Owner 边界

`reconstruction-manifest.v1.json` 只拥有：

- Project / Room 稳定身份与标题；
- Room 的 `x`、`y`、`shape` 空间布局；
- 每个 Room 已审核的来源 receipts；
- 事实快照、隐私位、来源计数与 Luna 整理回执引用。

manifest 不得保存需求、问题、阶段、验收、区域、工作流、Room 关系、目的地或 UI 文案。这些内容全部来自上级目录 Markdown，并由 builder 确定性生成。

## 证据优先级

1. 用户要求与需求文档决定为什么做以及用户结果边界。
2. 当前 Goal、需求、设计与审计文档决定已形成合同和未完成验收。
3. Codex、Claude Code、Pi、OMP 主会话补足需求变化与交付上下文。
4. Git 提交只证明实现曾进入历史，不单独证明真实前台可用或 Room 已完成。

冲突时，原始需求不会被后续摘要覆盖；没有同代验收的实现保持未验收。

## 隐私与去噪

- 只读取各 Provider 主 JSONL；排除子 Agent、子任务、Bash 与评测日志。
- Tool 结果、助手推理、原始 Provider payload、机器绝对路径和聊天正文不进入前端投影。
- 会话 receipts 只保存 Provider、日期、会话标识、用户消息计数与 SHA-256。
- 活跃会话固定到已审核用户消息前缀；前缀被改写时失败关闭。
- 项目文档固定到 Git HEAD 或审核时内容哈希。
- Luna Max 只产生候选；人工裁决后由人修改权威 Markdown。

## 截止语料与投影 receipts

完整无正文索引见 [`../reconciliation/wayfinder-luna-source-audit.v1.json`](../reconciliation/wayfinder-luna-source-audit.v1.json)：

- 45 份历史项目文档；
- 19 个去重主会话、5 个 exact alias ref、1338 条用户消息；
- 9 个代表 Git 提交；
- Luna Max 运行身份、结构 schema、输入与输出哈希、冲突和人工裁决。

当前前端投影选择 7 份项目文档、12 个主会话和 8 个 Git 提交：

### 项目文档

- `README.md`
- `docs/agent/handoff-goal.md`
- `docs/agent/room-facilitated-workflow-requirements.md`
- `docs/agent/memory-pipeline-requirements.md`
- `docs/agent/prompt-runtime-reference-audit.md`
- `docs/agent/chat-summary.md`
- `design-system/rag-ime-control-center/pages/project-field.md`

### 主 Agent 会话

- Codex：Project Field 对齐、Room 恢复、OMP 适配、项目资料重建和生产边界复核，共 5 个主会话。
- Claude Code：输入链路、统一工作台 UI、Room / Kernel 审计，共 3 个主会话。
- Pi：Room 自举与记忆三层恢复，共 2 个主会话。
- OMP：机制适配与 Prompt / Todo / LSP 收敛，共 2 个主会话。

### Git 旁证

- `92e6a62` 输入上下文可靠性
- `7e09954` 统一产品身份
- `923a9e1` 统一 Agent / Room Runtime
- `bf0f3d6` Room 自举
- `d94674e` 自主 Room 协作
- `084fefb` Room 活动与恢复
- `3ffacd5` 受管协作波次
- `5f0f114` 受治理工作流与前台证据

## 八个 Room

| Room | 纵向用户结果 |
| --- | --- |
| 输入体验闭环 | 保留 Rime 权威并可靠显示、失效和选择助手候选 |
| 统一产品工作台 | 在一个产品里理解和操作输入、Agent、Room、记忆与工具 |
| Agent 长任务连续性 | 长任务跨 Tool、压缩、模型和重连仍沿同一目标继续 |
| Room 协作交付 | 一个 Room 完成多 Agent 的完整结果交付 |
| 受控项目记忆 | 项目知识可追溯、可晋升、可撤销 |
| 工作流与能力收敛 | 用固定五段流程交付 Room 且不复制状态 Owner |
| Room 导航与项目图谱 | 从项目愿景找到、理解并继续正确 Room |
| 真实使用与发布 | 从实现推进到可安装、可验证、可恢复和公开交付 |

这些 Room 不按前端、后端、数据库、提交或内部任务划分。每个 Room 跨越实现层，并有自己的可观察验收。

## 构建与核验

生成物：

```text
control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json
```

完整来源核验并生成：

```bash
python3 scripts/build_project_field_projection.py \
  --source-worktree ../personal-agent-workbench-main-release
```

只核验生成物：

```bash
python3 scripts/build_project_field_projection.py \
  --source-worktree ../personal-agent-workbench-main-release \
  --verify-only
```

仅当事实快照与来源选择未改变、只迁移派生 docs 内容时，才可复用封存 receipts：

```bash
python3 scripts/build_project_field_projection.py \
  --source-worktree ../personal-agent-workbench-main-release \
  --reuse-verified-receipts \
    control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json
```

复用模式不会声明事实源已经重新采集或仍然新鲜。需要更新截止时间或来源选择时，必须重新完成来源核验与人工复核。
