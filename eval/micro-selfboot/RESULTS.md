# 小预算自举评测结果 · 2026-09-05

这是首轮保留记录；最新五类补测与独立 Web App 验收见 [FIVE_METRIC_RESULTS.md](FIVE_METRIC_RESULTS.md)。以下原始失败和费用勘误仍有效。

已完成本轮微任务的实现、真实 Pi 运行、源码故障验证、导出运行和技能流核对。结果包含明确失败；不代表六项成果全部获证，更不代表已经发布或在正式 Lab UI 验收。

## 可引用结果

| 能力 | 本轮实际结果 | 可以陈述的范围 |
| --- | --- | --- |
| 显式跨 Session 交接 | 前后两个真实 Pi Session，3/3 约束满足；完整轨迹 3 次模型调用、7,480 tokens | 显式交接能在这一合成任务保留接口、幂等字段与非必填约束；不能当生产长期记忆收益 |
| 更新信息 | r2 旧值控制与最新值均正确；2 次模型调用、4,848 tokens | 提供完整日期上下文后，使用最新 800 配置；不是自动 Memory 召回率 |
| 可靠执行 | 12/12 个指定源码故障测试通过，一轮 12 次观察 | 并发重复准入、排队取消、运行取消/清理、迟到绑定、重启禁止付费重放、abort 失败、settlement 丢失、未知准入、错误终态身份、metadata 失败、worker 崩溃、重复终态恢复 |
| Lab 配置优化 | r2 基线 4/4、候选 4/4；完整轨迹基线估算 $0.000553，候选 $0.0011352，诊断 $0.0006954；总计 $0.0023836 | 质量保住，但候选费用更高，结论 **no_improvement**，不能写降本 |
| 独立导出 | 费用规则 CLI 在新目录、空 HOME、`python -I` 下执行四个输入，4/4；ZIP 不含答案/测试或 PAW 依赖 | 独立小 CLI 的功能一致性；不是完整 PAW Extension App、macOS App 或新机器安装成功率 |
| Room | r3、r4 单 Agent 均完整答对；Room 原始合并失败。r4 Lab 正确指出字段名问题，但唯一候选仍输出旧字段，验收 Reject | 可以证明 Room 执行、诊断和拒绝错误候选的链路；不能证明协作提升或该问题已修好 |

这些是合成开发题、单轮/修正后的观察；没有 Held-out 泛化声明，也不把四条业务断言说成四个独立模型任务。

## 自举闭环的实际内容

使用源码 `AgentService → AgentLabTrialApplication → MicroAdapter → GoldenPiExecutor/Room dispatch → installed Pi`，保存真实 job、Session、turn、Room dispatch 和 Pi transcript。

费用任务：Lab 的一次诊断提出去掉无关办公室信息与过期规则，生成一个候选 Prompt；宿主固定验收器判四条真实 CLI 行为。候选有完整通过回执，但费用更高，不把 quality Keep 当 cost Keep。

Room 任务：伙伴错把 consumer 旧字段 `requestId` 当成应输出的 API 字段。Lab 诊断正确指出应为 `clientMessageId`，但同一个 integrator 仍返回旧字段；真实验收器拒绝，未追加第二候选。没有通过修改答案标签或放宽断言把失败转成成功。

## 准备错误与修正记录

| 回合 | 事实 | 后续处理 |
| --- | --- | --- |
| first | 可靠性清单有一处测试类名拼错；11 个实际场景通过，另一项是加载错误 | 修正引用；r2 12 个实际场景全部执行通过，first 日志保留 |
| first | 旧日期控制的“current”含义不够明确，模型返回 null；新日期返回正确 | r2 明确为“截至已提供最后记录”的封闭合成场景；不把旧结果删除 |
| first | 候选输出 `manual review`，应用只接受 `manual` 枚举 | 修复评测接线：基线和候选附加同一不可变输出契约；r2 重新留证，不覆盖旧实验 |
| first | 脚本直接修改活跃 Room 伙伴 Session 权限，被 owner 拒绝 | 改由 Room 创建参数管理只读策略；这是 harness 接线问题，不是 Room 产品缺陷 |
| r2 | 脚本错误读取 dispatch.turnId | 修正为 sessionTurnId，Pi client identity 用 dispatchId；旧已接受工作未自动重放 |
| r3 | 真实三伙伴合并失败 | r4 增加一次 Lab 诊断、一个候选，仍失败后停止 |
| 复核 | Golden settlement 只含最后一条 assistant usage，漏了同 turn 的 tool_search 调用 | 新 `turn_usage` 按精确 Pi turn binding 汇总所有 assistant 调用；旧文件不可变，单独输出 reconciled.v2 |

## 预算与费用边界

- 最新源码会在每次结算后检查 **真实 Provider call 数与完整 turn tokens**；超过阈值后不再启动下一次请求。单次输出上限下传 Pi。仍不是对在途输入的实时硬截断。
- r4 用旧计量路径运行，原报表只看六次 completion；离线复核实际 **7 次模型调用、20,098 tokens**，应标 **budget_exhausted / candidate rejected**。不能写成预算内完成；新计量修复以回归验证，未再消耗模型额度重跑。
- 四个回合中可对账的 **29 次模型调用、76,551 tokens**，已知目录价估算 **$0.01621748**。两个 Room 准备/接线失败回合的全成本不完整，因此不是一个完整总账。单独 2,325-token 连通探针不在此数内。
- r2 optimization 旧 job 报告只记末条回复并以 quality-only 判 Keep；最新解释以完整轨迹为准：候选额外 tool_search 也计价，故 **无降本收益**。reconciled 保留原报告用于溯源，不静默改写。
- 数据来源是模型目录估算，不是 Provider 实际账单。所有失败、诊断和修正保留；不能只汇总成功试跑。

## 技能流

完整检查见 [SKILL_FLOW_REVIEW.md](SKILL_FLOW_REVIEW.md)。七个核心方法的已安装 PAW 配置/Bundle 与仓库一致；Codex 本地四份副本有差异。当前按需路由正确，建议同步 Codex 副本，不恢复强制流水线。本次仅审查，未覆盖个人 Skill。

## 本轮验证

- `python3 -m unittest tests.test_agent_lab_micro tests.test_agent_lab_trial_execution tests.test_agent_lab_golden_pi`：此前固定版本 38 项通过。
- 增加完整 turn 用量回归后，`python3 -m unittest tests.test_agent_lab_micro`：9 项通过；覆盖预算、未知用量、输出契约、导出隔离、Room identity、12 项测试引用有效性、跨 turn 用量排除与中间调用计入。
- Skill routing/Lab optimizer/Trace Skill：7 项通过。
- `python3 scripts/check_import_boundaries.py`：通过。
- 最终六模块聚焦回归：46 项通过，56.351 秒；根 `validate_project_harness`、route ownership、import boundaries、`git diff --check` 通过。route checker 自身报告 29/40 undeclared，为既有统计，不冒充所有路径均已声明。没有运行整个产品测试套件或安装。

## 保留的下一步与不可扩大陈述

本轮已达到“有真实小数据、保留失败、可以复验”的交付；没有达到全面证明协作增益、长期上下文收益、原生 App 导出或线上稳定性的目标。完整自动 Memory consumer 接续、Room 成本改善、正式 Lab 页面集成/安装、原生干净环境仍未验收。本轮不再追加模型调用。

简历可以使用的候选表述：

> 构建复用 Pi 的小任务评测与诊断闭环，以固定验收器筛选候选并保留失败轨迹；覆盖 12 类执行故障回归，验证显式跨 Session 交接保留 3 条约束，并使独立费用规则 CLI 在隔离环境通过 4 条业务验收。

不要使用“多 Agent 提升成功率”“上下文召回达到 100%”“优化降本”“整个 OS 已完成干净机器验收”。

原始私有运行与逐文件校验副本位于本机 `RagIme/EvaluationArtifacts/micro-selfboot-20260905`；含 transcript 与数据库，不提交仓库。仓库只保留任务、runner、验收代码与本摘要。未提交、未推送、未发布。
