# Agent Lab 当前完成度核对

## 目标
核对当前项目中 Agent Lab 已实现的能力、实现位置、验证证据，以及尚未完成或尚未通过真实运行验收的边界。

## 范围
- PAWOS Agent Lab 前端入口、页面与交互
- 后端/数据模型、导入、评分、成本与最优路径逻辑
- 需求状态、自动化测试和可用的前台证据

## 验收
1. 每项“已完成”均能定位到当前源码或测试。
2. 明确区分源码实现、自动化验证、安装运行和前台验收。
3. 明确列出仍依赖演示数据、未提交改动或缺少真实证据的部分。

## 工作轨道
1. 前端与可见交互核对。
2. 后端、数据契约、导入与评分能力核对。
3. 需求状态、测试与运行证据核对。

## 来源
- `PROJECT.md`
- `OUTCOMES.md`
- `control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md`
- `control-center-web/src/features/eval-lab/`
- `rag_ime/eval_lab*.py`, `rag_ime/agent_lab_*.py`
- `tests/test_*agent_lab*`, `control-center-web/src/**/*eval-lab*.test*`
- 当前 Git 状态与可用前台快照

## 当前观察

### 已有实现
- `/eval-lab` 已接入 PAWOS App registry、路由和原生窗口。
- 前端已有实验结果、方案路径、实验详情、对话与证据四个页面，以及评测向导、继续优化 Room、候选目录确认、报告导出和只读证据查看。
- 后端已有 runs/evidence 两个 GET 投影、append-only 实验 revision store、脱敏证据目录、确定性成本估算和质量门禁优先的最优路径评分。
- 公开实验账本当前有 22 条：3 kept、14 rejected、3 diagnostic、2 open_gap；四个业务项目 UI 投影 21 轮，另有 Trace 实验不进入四项目矩阵。

### 新鲜验证
- Agent Lab Python focused tests：36 tests，全部通过；有 1 条未关闭 sqlite connection 的 ResourceWarning。
- 前端 TypeScript：`pnpm typecheck` 通过。
- 前端 focused tests：首次 39 tests 中 37 通过、2 失败；证据面板失败单独重跑后通过，判定为本轮可复现性不足/疑似时序波动；剩余失败是测试仍期待旧的 Sol/Luna 成本文案，而当前账本已更新为新的质量回退 Reject 数据。

### 证据边界
- 本机默认 evidence projection 当前发现 12 个 checked-in report-only run，0 Session、0 transcript；EnterpriseOps 研究盘未连接。
- 已有 Playwright YAML 只证明较早 mock/演示页面渲染，且文案已落后于当前源码。
- Agent Lab 主要 owner 文件目前未跟踪，接入文件处于已修改状态；HEAD 与 `release/product-status.json` 的已验证 commit 均不包含这些工作区改动。
- 没有当前源码的 E4 安装、E5 Runtime、E6 真实前台验收，因此不能称为已发布或完整可用。
