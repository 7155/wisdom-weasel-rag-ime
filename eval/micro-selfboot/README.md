# PAW 小预算自举评测

## 原始需求与当前范围

以下是本对话用户原文；本次可见上下文未提供消息 ID，不编造 ID：

- U1：“我大概主要是为了有简历数据，这个检测和优化也可以在lab完成，或者traceagent来评估，我们os一个特点就是自举。然后任务不要选太大的，因为token会不够”
- U2：“完成”——授权执行上轮提出的小任务方案。
- U3：“顺便看看，我们的技能流有没有问题，就是grill到验收的我们自己做的技能流”——补充技能流审查，未替换 U1/U2。
- U4：“优化完成。测出收益，才有故事”——继续实施一个有界优化，要求真实前后收益。已完成结果见 [Room 工作流优化收益](OPTIMIZATION_RESULTS.md)。
- U5：“在来个中等大小任务大小。因为多agent，主要不是省token，而是任务成功和持久不便宜”——增加中等编码任务，以完整交付和持久接续为先，费用单列。两臂最终均未完成，见 [中等任务实测](MEDIUM_TASK_RESULTS.md)。
- U6：“结果展示可以加一些可视化”——将保留回执导入已安装 PAWOS Lab，增加验收、用量费用和取消恢复图表，见 [OS 结果查看与验收](OS_RESULTS.md)。

解释：优先取得真实可追溯的小样本，保留失败与 no-improvement。不能把设计的目标提升百分比填进简历。六任务及 6 calls/20k/768/一次候选的具体值来自本次实现选择，不是用户逐字指定。

首轮由主 Agent 完成；后续补测并行分给三个有固定文件责任的 Codex 子 Agent，主 Agent 复核整合。Codex 子 Agent 不计作 PAW Room 的能力证据；被测伙伴通过 PAW 自己的 Room dispatch 运行。不将被测模型的诊断当作通过票。

## 工作项与验收

| 工作项 | owning seam / 输出 | 运行验收 | 需求验收 | 依赖/回滚 |
| --- | --- | --- | --- | --- |
| 固定小任务与预算 | tasks.v1.json、MicroAdapter | 有效输入、预算停止、实际回执 | 六类目标逐项区分，失败不丢 | 无；新增文件可独立移除 |
| Lab 真实调用 | TrialApplication + GoldenPiExecutor + installed Pi | 持久化 job/session/turn/usage | handoff、更新、候选按固定值验收 | 任务定义；独立 DB，不改生产 |
| Room 微交接 | RoomManagement/dispatch/Pi settlement | 真实 room/dispatch/Pi identity | 两处字段问题及合并完整性 | 真实调用；关独立 service |
| 故障矩阵 | 12 个已有 owner 测试 | 独立运行且有日志 | 场景覆盖，不能用总套件数替代 | 源码；不访问 Provider |
| 导出 | 固定 CLI runtime + 模型配置 | 新目录、空 HOME、隔离 Python | 四业务输入与原验收一致 | 合法策略配置；无 OS 安装 |
| 技能流核对 | SKILL_FLOW_REVIEW.md | 三处副本与路由测试 | 按需流程、预算、完成权 | 只读；不改 Skill |

## 使用

在项目根运行，产物目录必须是不存在的仓库外路径：

```sh
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-micro-example
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-micro-live-example --live
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-micro-one-example --live --tasks optimization --skip-faults
python3 -m unittest tests.test_agent_lab_micro
```

后续补测入口（每条只执行指定小范围）：

```sh
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-room-pair --live --tasks room-comparison --skip-faults
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-memory-continuation --live --tasks context-continuation --skip-faults
python3 scripts/eval_paw_execution_reliability.py --output-root /tmp/paw-reliability --repeats 20
python3 scripts/summarize_paw_optimization_metrics.py --output /tmp/paw-optimization-summary.json
python3 scripts/export_paw_policy_app.py --source-run /path/to/retained-paw-micro-selfboot-r2 --output-root /tmp/paw-policy-web-app
```

最后一条从保留的真实 Lab 候选读取配置，不生成新候选；三个隔离 HTTP 启动和十二条业务观察不消耗 Provider tokens。独立浏览器 App 验收与掌柜问数静态包的依赖限制分别见最新结果。

结构化工作流优化入口如下。首条最多六次调用，第二条只确认第一条已选定的候选，最多两次调用；确认要求保留的六条原始回执完整可核算。已有本轮结果，不必为了查看数据再次运行：

```sh
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-room-merge --live --tasks room-merge --skip-faults
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-room-merge-confirm --baseline-run /tmp/paw-room-merge --live --tasks room-merge-confirm --skip-faults
```

第一条只有源码故障矩阵和技能副本清单，不调用模型。`--live` 使用已安装 PAW 的 OAuth 与 Pi binary，临时私有凭据副本在 finally 删除；模型运行经源码 AgentService/现有 Lab TrialApplication/GoldenPiExecutor。独立数据库保留原始模型文本与回执，不使用个人历史，不写生产数据库。

这是可注入 `TrialAdapter` 的 source Lab 微任务入口；2026-09-06 已将八条保留结果导入已安装 PAWOS 的 Lab，并提供图表查看。运行入口仍是 source Lab；结果展示不等于把候选执行器改成通用 Room 默认实现。Pi 仍持有模型执行、Session 和 settlement，Lab job 控制准入、停止和终态。

## 统计口径

- handoff：两个真实新 Session，用前一模型输出的显式交接作为后者输入。不是自动长期记忆检索/压缩收益。
- update：显式控制的历史包及更新包；不是生产 Memory consumer 的召回率。
- Room：脚本逐个指派 Request、Response、Integrator；不是自主分解或并行加速对照。单 Agent 与 Room 各按原题评分，记录每臂用量，但不据一题推普遍收益。
- optimization：固定合成政策，基线→Lab 诊断→一个 Prompt 候选→同验收器。无隐藏测试，属于候选已被观察的开发验证。四个业务用例不等于四次独立模型任务。
- export：独立费用规则 CLI，Python 标准库即可运行；不等于完整 PAW Extension App、原生 App 或新机器 OS 验收。
- reliability：真实应用 owner 配合模拟故障的源码测试，不冒充安装态 soak。测试耗时不是取消收口时间。
- 成本：Pi model_catalog_estimate；不是账单。总成本包含诊断与失败回执，未知成本保持未知。候选若没有更省钱，则不能写降本。
- `maxObservedTokensPerTrial` 在结算后停止下一次调用；单次输出限制下传 Pi，输入没有硬截断，因此允许一次调用跨过 20k 阈值但不再推进。

## 外部方法参考

本对话前一轮已查官方资料：
[Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)、
[τ-bench 终态验收](https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md)、
[LongMemEval](https://github.com/xiaowu0162/LongMemEval)、
[Terminal-Bench 隔离任务](https://www.tbench.ai/news/announcement)。
当前题目为自建 synthetic micro tasks，不宣称跑过这些公开基准。

最新优化收益见 [OPTIMIZATION_RESULTS.md](OPTIMIZATION_RESULTS.md)，中等任务见 [MEDIUM_TASK_RESULTS.md](MEDIUM_TASK_RESULTS.md)，OS 图表与查看路径见 [OS_RESULTS.md](OS_RESULTS.md)，五类结果见 [FIVE_METRIC_RESULTS.md](FIVE_METRIC_RESULTS.md)，首轮历史见 [RESULTS.md](RESULTS.md)，范围账本见 [METRIC_COMPLETION.md](METRIC_COMPLETION.md)，技能流见 [SKILL_FLOW_REVIEW.md](SKILL_FLOW_REVIEW.md)。
