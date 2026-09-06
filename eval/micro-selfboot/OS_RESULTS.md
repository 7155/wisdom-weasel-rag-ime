# PAW 自举结果：OS 查看与验收

2026-09-06。八条本轮实测记录已追加到已安装 PAWOS 的 Lab，原有 35 条记录保留。新增数据来自保留回执；查看图表不需要再次调用模型。

入口：**PAWOS → Agent Lab → 当前实验 → PAW 协作与接续 → 检查结果**。也可从本机 [PAWOS Lab](http://127.0.0.1:8768/#/eval-lab) 打开。在“当前实验”中选择一条记录，再切换“验收结果”“用量与费用”“取消与恢复”；只显示实际有观测的视图。

| 记录 | 当前结果 | 可说明的范围 |
| --- | --- | --- |
| Room 整合优化 | 3/3 检查保持；调用 3→2；tokens 9,911→6,394；估算费用 $0.00203172→$0.00152980 | 窄工作流复验 tokens −35.49%、估算成本 −24.70%；不证明 Room 比单 Agent 更容易完成任务 |
| 小任务协作对照 | 两臂完整任务 0/1、检查 2/3；Room 交接遗漏 0/2 | 未测出协作收益 |
| Memory 接续 | 真实 Pi 回答 4/4、正例召回 2/2、负例排除 2/2、错误或过期暴露 0/4 | 单轮合成条件验证，没有无记忆配对收益基线 |
| 执行可靠性 | 8 类故障 × 20 次，160/160 观察通过、重复副作用 0；取消/恢复各 60 个混合计时样本，p95 31.446/23.390 ms | 真实 Lab owner、进程内重建与模拟业务，不是线上 SLA |
| 费用规则优化 | 业务断言 4/4 保持；估算费用 $0.000553→$0.0011352；两轮总投入 7 调用、17,715 tokens、$0.004189 | 成本未改善，失败与诊断投入保留 |
| 独立费用 App | 一个包；隔离启动 3/3；四个唯一业务用例 × 三次，共 12/12；真实界面 4/4；前后一致 | Python 标准库 Web App，未在另一台实体机器验收 |
| 中等 SQLite 受阻记录 | 两臂存储 6/6；最终实现 6/20、交付 0/4、完整任务 0/1 | WorkspaceHarness 文件策略阻塞，不归因为模型能力差异 |
| 中等 JSONL 配对 | 两臂实现 16/20、交付 0/4、完整任务 0/1；Room 进入真实重启后的追加需求阶段 | 接续进入和产物保留不等于接续任务完成；没有成功率提升证据 |

图表以验收为首屏，完整数值口径可展开；原始评估、适用范围和回执引用保留。相同比例指标使用 0–100% 刻度，用量/费用在各自指标内从零比较，不跨单位共用坐标。缺失基线显示“未提供”及虚线，不填零；单轮观察不显示优化方向。中等任务只报告已观察 tokens 和已知估算费用，并明确预算中断及未知在途成本。

所有美元值均为 Pi transcript 目录价估算，不是 Provider 账单。完整任务、检查、重复观察、上下文投递分别计数。对照原始失败报告没有重新评分或删除失败记录；中等任务旧验收器的副作用及修复边界见 [中等任务实测](MEDIUM_TASK_RESULTS.md)。

## 数据与实现

- [公开投影构建器](../../scripts/build_paw_resume_lab_ledger.py)从私有回执构建 `paw.interview-agent-experiment-ledger.v1`；不运行模型、不直接写生产库。`retained_observations` 的 manifest 绑定保留回执，不冒充运行前冻结。
- 本次导入文件为本机 `EvaluationArtifacts/resume-os-20260906/agent-experiments.v5.json`，SHA-256 为 `68ee11fff96c0267448852a78f1aec37e9203aa572af02838a71b52da1c11be7`。其八个稳定 experiment ID 的新 revision 通过已安装 importer 追加，旧 revision 不覆盖。公开投影只含回执别名与 hash，没有本机绝对路径或私有 transcript 正文。
- [指标映射](../../control-center-web/src/features/eval-lab/paw-selfboot-metrics.ts)只使用明确分子、分母和费用字段；[图表](../../control-center-web/src/features/eval-lab/PawSelfbootResultsChart.tsx)采用现有 Lab 配色与 CSS 条形图，没有新增图表依赖或动画。
- 只把 Lab 结果展示改动移入安装候选 `20260906-lab-selfboot`，并按 hash 保留当前安装底座中的 Memory、文件协作与路由变更。共享源码文件只按精确锚点修改，没有安装整个脏工作树。
- [现有安装器](../../scripts/install_agent_gateway_launch_agent.sh)增加 `--web-only`：仍执行源代码一致性、类型、生产构建、复制与树摘要校验，原子替换前端后退出，不执行重写 LaunchAgent 或重启 Gateway 的分支。保留本次最初前端快照 `resume-os-20260906/previous-dist/` 供回滚。

## 验证

- 安装候选：`pnpm test` 指定 `index.test.tsx`、`ExperimentWorkspace.test.tsx`、`paw-selfboot-results-chart.test.tsx`、`paw-selfboot-metrics.test.ts`、`experiment-display-metrics.test.ts`，**61/61** 通过。覆盖图表切换、缺失基线、预算费用不完整、接续语义、单轮观察与数据分母。
- 源工作树：结果页与工作区 **56/56**；指标、图表与摘要前一轮相关回归也已通过。两树的测试集合存在重叠，不相加成独立任务数。
- 数据构建两次一致，8 条完整数值与精确决策经过真实 HTTP API 回读，导入后仍为 43 条当前实验。新增数值与原回执一致，v4→v5 仅修正状态/口径并分离接续状态，没有更改已有测量值。
- `python3 scripts/check_project_harness.py`、`python3 scripts/check_import_boundaries.py`、`bash -n scripts/install_agent_gateway_launch_agent.sh` 通过。全仓库测试与完整 web 套件未执行；安装路径运行类型检查和生产构建。
- 已安装 HTTP PAWOS 的真实页面验收通过：Room 验收/用量切换、中等任务 0/1 与部分费用说明、可靠性两项 p95 和各 60 样本、Memory 缺失基线。390×844 视口下图表宽 348px、scrollWidth 348px，左右边界 21/369px，没有横向溢出；验收后清除视口覆盖，正常宽度下图表宽 883px、scrollWidth 883px。
- 最终前端树摘要为 `c4859cf5b8e70c93dc840970f87dea54614d0167c3deff1bbcc7beb9a7f4e350`；本机保存 `final-api-install-readback.json`、`final-ui-acceptance.json` 及安装候选文件摘要。结果页的 Room 费用视图作为本次可查看的标签页保留。

前台图表是原始回执的汇总投影；本次没有新增公开的逐 Case transcript 绑定，不把“0 条公开记录”说成已经公开了所有原始轨迹。安装期间有并行底座更新，跨整个时间段的 Gateway PID 发生变化；只能确认本次 `--web-only` 路径未执行重启分支，不能声称整个并行安装期间服务从未重启。生产构建通过，有既有大于 500kB 的 chunk 警告。

这是已安装 HTTP PAWOS 的结果展示验收。没有将 source Lab runner 改为通用生产默认，也不把浏览器验收扩展成原生 macOS 全链路验收。技能流检查独立保留在 [SKILL_FLOW_REVIEW.md](SKILL_FLOW_REVIEW.md)。
