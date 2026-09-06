# 五类指标补测与可引用边界 · 2026-09-05

本文件接续 [首轮记录](RESULTS.md)，保留负结果。目标是用小任务取得可追溯的简历证据；不把全部指标都包装成提升。当前原始回执保存在本机 `RagIme/EvaluationArtifacts`，不提交 transcript、数据库或生成包。

后续用户要求“测出收益”已另行完成：[Room 工作流优化](OPTIMIZATION_RESULTS.md)在新的同输入配对中将模型整合替换为程序校验合并，三个检查保持 3/3，确认调用 3→2、tokens 降低 35.5%、估算成本降低 24.7%。这是 Room 内部编排优化，下面单 Agent / Room 负结果与费用候选无收益记录继续有效。

## 任务选择与预算

选 PAW 已经遇到、能用代码判定的窄任务：三个 Room/Runtime 契约，四种 Memory 接续条件，八类执行故障，一个费用配置候选，以及一个现有 Extension App 导出。任务、验收器与成本分母在运行前确定。故障与包验证不调用模型；Room 每臂同为 Luna low、最多 4 次 Provider 调用、12k 结算后 token 阈值、单次输出 768。一次失败保留，不为得到好看的分数持续重跑。

方法参考：从实际故障建立小型任务库、检查最终环境状态、区分 task/trial/check，并记录完整轨迹，参考 [Anthropic Agent evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)；记忆按保留、更新、拒答分组参考 [LongMemEval](https://github.com/xiaowu0162/LongMemEval)。本次没有运行这两个来源的公开基准，不作榜单比较。

## M1 · 同任务同预算上限的 Room 对照

同一组三个合成契约题，单 Session 与脚本指定的两个伙伴加一个整合者各运行一次。Room 伙伴串行 dispatch，没有测自主拆解或并行加速。

| 指标 | 单 Session | Room |
| --- | ---: | ---: |
| 严格输出契约通过 | 2/3 | 2/3 |
| 完整组通过 | 0/1 | 0/1 |
| 真实 Provider 调用 | 1 | 3 |
| 完整 turn tokens | 2,793 | 9,855 |
| 目录价估算成本 | $0.00046612 | $0.00209552 |
| 每个成功 case 成本 | $0.00023306 | $0.00104776 |
| 墙钟时间 | 8.572 秒 | 26.534 秒 |

Room 保留了伙伴已经答对的 **2/2** 个结果，遗漏 **0/2**；分配重叠 **0**，相同发现的重复行 **0**。它们不等于所有工作均无重复，也不等于 3/3 任务成功。两个方案都把总 token 输出成分类对象，未满足冻结的标量输出验收；题目没有逐字段类型 schema，这也是该小样本的解释限制。原始失败没有被改判。

结论：这一小任务没有测出协作收益。Room 成本约为单 Session 的 4.50 倍；不能据此推断复杂任务一定更贵或无益。总计 4 次模型调用、12,648 tokens，估算 $0.00256164。

回执：`room-comparison-20260905/room-comparison-job.json` 与其 `comparison/*/report.json`；实现 [Room comparison](../../rag_ime/agent_lab_room_comparison.py)。原运行冻结了题目和答案；该模块的顶层源码 hash 纳入是后续补强，不回填旧回执冒充当时已有。

## M2 · Memory 接续

真实 source owner 从隔离 SQLite 的 Memory Atom 生成检索投影，经 `AgentService.prompt`、`SessionMemoryRecallBuilder`、`AgentContextRuntime` 投递，并保存 Context Trace。四组条件为保留、更新、废弃、敏感信息排除。

确定性 consumer 检查：接续上下文合同 **4/4**；正例关键信息召回 **2/2**；负例排除 **2/2**；错误/过期内容暴露 **0/4**。不得把负例算作正例 Recall。八次上下文投递的 Memory token **估算**合计 452、均值 56.5、最大 113；这些是 Trace tokenEstimate，不能混入 Provider 实际用量。

将实际恢复后的上下文交给四个独立 Pi Session 后，**真实模型接续 4/4**：保留原始需求/失败轨迹、选用更新后的 Luna 5.6、对已取消方案和未提供的凭据依据分别拒答。主 Session 逐条复核答案，未观察到错误/过期内容使用。完整 turn 用量 **4 次 Provider 调用、10,746 tokens、估算 $0.00197072**；四条 transcript hash、turn 绑定和用量重新核算均一致。每个 settled Session 随即关闭。

该轮经过真实 Lab Trial owner；初始 ACK 与 compaction summary 是合成 fixture，不能声称已测真实 Pi 自动压缩或生产长期记忆。单个 fixture 一次模型请求，无重复试到通过。回执：`context-continuation-live-20260905/context-continuation-report.json` 及 `parent-usage-verification.json`。

实现与复验：[context continuation runner](../../scripts/eval_paw_context_continuation.py)。

## M3 · 执行故障与取消/恢复时间

真实 `AgentLabTrialApplication` 与 SQLite Store，模拟业务副作用表无唯一约束，避免用数据库约束遮住重复执行。八类场景各 20 次：并发准入、ACK 丢失后相同 ID 重试、排队取消、运行取消、迟到绑定取消、写入后结果丢失、已完成任务恢复、已领取但未执行业务时重建 owner。

**160/160 通过，重复业务副作用 0。** 以下均为单机测量，不是测试套件总耗时。

| 测量起止点 | n | p95 |
| --- | ---: | ---: |
| 排队取消请求 → 持久终态 | 20 | 18.602 ms |
| 运行取消请求 → worker 收口及终态读回 | 20 | 31.521 ms |
| 迟到绑定取消 → worker 收口及终态读回 | 20 | 29.992 ms |
| 已完成任务 owner 重建 → 原任务读回 | 20 | 21.952 ms |
| 写入后结果丢失，owner 重建 → interrupted 读回 | 20 | 21.936 ms |
| running claim 后 owner 重建 → interrupted 读回 | 20 | 28.917 ms |

使用 nearest-rank p95。最后一组每条回执都确认重建前状态确为 `running`，不是提前恢复后才开始计时。恢复是进程内 owner 重建，Provider 与业务为模拟；没有宣称真实网络断包、进程 kill、原生前台或线上 SLA。

回执：`reliability-metrics-20260905-r3/report.json`；实现 [reliability runner](../../scripts/eval_paw_execution_reliability.py)。首轮 12 类源码回归与这组 8 类重复测量分别陈述，不相加成新的独立故障种类数。

## M4 · 优化：业务成本与优化投入分开

四场景的新投影从原实验账本和绑定回执计算，没有重跑 Provider。金额是 Runtime 对账/目录价估算，不是账单。

| 场景与成功单位 | 基线 → 候选 | 每成功单位成本，基线 → 候选 | 耗时，基线 → 候选 |
| --- | --- | --- | --- |
| EnterpriseOps 完整任务 | 3/3 → 3/3 | $0.570405 → $0.024306 | 583.475 → 574.320 秒 |
| Enterprise RAG 回答案例 | 3/4 → 4/4 | $0.723534 → $0.025734 | 未提供同口径实测 |
| CloudOps 原因识别 CA | 12/12 → 12/12 | $0.380681 → $0.023011 | 1,036.278 → 1,492.913 秒 |
| Memory 整理/检索/回滚/重放生命周期 | 1/1 → 1/1 | $0.163425 → $0.007185 | 165.559 → 82.277 秒 |

CloudOps 完整任务通过数仍未知；FA/JRA 为 10/12 → 11/12，不能用 CA 12/12 替代。Memory 分母是一个生命周期，不把五个 fixture 都写成独立模型成功任务。RAG 是 candidate-aware Validation，延迟仍只诊断使用。

四个候选的执行失败信号均为 0，但**业务严重错误数未知**：没有冻结的严重性 rubric。Tool、Provider、Runtime 信号可能描述同一事件，不相加称独立严重错误。历史失败、被拒绝候选和缺失成本均保留。历史总评测成本、优化器完整成本、工程投入、Judge 投入与回本量，缺乏完整来源的字段保持 null。

本次小费用闭环提供了可完整核算的投入实例：首轮错误候选和 r2 两轮共 **7 次调用、17,715 tokens、$0.004189**；其中两次诊断合计 **$0.0013798**。r2 基线和候选业务验收均 **4/4**，但成本 $0.000553 → $0.0011352，属于 **no-improvement**。确定性验收器调用模型次数为 0，不代表开发该验收器的人力成本为 0。

四条规则是一个配置生成任务的四条业务断言，不是四个独立模型请求。基线/候选每成功配置成本分别为 $0.000553/$0.0011352；本次把“超额、无票据、未知币种被直接批准”定义为禁止批准事件，三个固定负例在两侧均 **0/3**。这是对保留输出的确定性分类，不回填四个历史场景的“业务严重错误数”。r2 三个阶段记录耗时 3.411/7.325/7.857 秒，分别属于基线、诊断、候选；不混作生产单次业务响应时间。

实现 [optimization summarizer](../../scripts/summarize_paw_optimization_metrics.py)；回执 `optimization-metrics-20260905/summary.json`。小费用数据来自首轮 `reconciled.v2.json`，不并入四个历史场景分母。

## M5 · App 导出与实际使用

最终使用与 M4 同一真实 Lab 候选，导出一个小型费用规则 Web App。其归档含配置、原规则执行器、Python HTTP 入口和操作页面，不含答案、验收器、PAW 库、Node、凭据或外部网络依赖。`export.json` 绑定 Lab job 与候选回执 hash；未把质量通过改写成成本优化成功。

**导出 1/1；空 HOME、新工作目录、`python -I -S` 隔离启动 3/3；4 个唯一业务用例 × 3 次启动共 12/12 通过；导出前后结果完全一致。** 另在真实浏览器依次填写金额/币种/票据并点击执行，**4/4** 显示正确结果，未模拟 API。正常、超额、缺票据、未知币种分别显示通过、不通过、不通过、转人工审核。模型调用为 0。

这是可独立使用的合成政策 Web App，依赖 Python 标准库；不是原生 macOS 二进制，也没有声称已在另一台实体机器验收。UI 验收后已关闭唯一临时标签页和服务。

实现 [policy App exporter](../../scripts/export_paw_policy_app.py)；可交付归档及验收回执：本机 `policy-web-app-20260905/expense-policy-web-app.zip`、`acceptance.json`、`browser-acceptance.json`。没有为该导出再调用模型。

### 现有掌柜问数的单独检查

真实现有“掌柜问数”源码、Pi Package/Skill 与生产 HTTP 前端已导出；一个导出包的完整性与隔离 HOME 静态资源启动通过，导出前后离线 fixture 的 P/R/F1 均为 1.0、Provider calls 为 0。离线 evaluator 仍使用宿主仓库 `rag_ime`，只证明绑定和 fixture parity。

主 Session 将该包解压到仓库外目录，在无模拟 API 的浏览器打开：PAW 壳显示“暂时无法连接本机控制服务 / 连接受限”，`/api/agent/extensions` 等实际返回 404，目标 App 未注册，业务任务没有执行。因此 **独立业务就绪检查 0/1**。这是需要 PAW Gateway/Pi 的静态导出包，不能写成已独立交付可用 App。

包内旧回执错误地把 `not_requested` 的 UI 两项投影成 `true`；本次已修正 runner 并新增父验收勘误，原包不静默重写。原包只能用于调试，不作为完整交付验收通过证据。源 UI 原有断言也有失败，未算通过。没有重新构建、安装、发布或增加模拟 API 来制造独立成功。

实现 [App export acceptance](../../scripts/eval_paw_app_export_acceptance.py)；原包与勘误 `app-export-unmocked-20260905/`。用户反馈卡顿后，临时静态服务与两个验收标签页均关闭。

## 技能流与剩余工作

[技能流检查](SKILL_FLOW_REVIEW.md)已完成只读核对：PAW 仓库/安装配置/安装 bundle 的七份一致；Codex 本地四份有差异。按需选择 Grill、规划、执行、复核；父 Session 分别核验能否运行、是否满足需求。没有覆盖用户个人 Skill。

本次五类小样本测量与技能流审查已完成，含有失败与 no-improvement。尚未获得的更广结论包括：Room 在复杂任务的增益、生产长期记忆质量、掌柜问数脱离 Gateway 的完整业务交付、历史优化投入的完整来源以及历史场景严重错误 rubric。小费用 Web App 的独立验收不能扩大到所有 PAW Extension App。

可用于简历的限定表述：

> 构建复用 Pi 的 Lab 小任务评测与诊断闭环，按完整 turn 对账成本并保留拒绝候选；在 8 类受控执行故障的 160 次观察中未出现重复副作用，4 个合成 Memory 接续任务全部通过，并将同一 Lab 配置导出为独立费用规则 Web App，通过 3 次隔离启动及 4 条界面业务验收。

## 最终验证与交付

- 十个相关模块的聚焦回归 **35/35 通过，42.171 秒**；包括实际 HTTP 导出、Memory consumer、Room 评分、未知费用、故障计数与技能路由。
- Python 编译、import boundaries、根文档 `validate_project_harness` 与本任务差异空白检查通过。根 O6 增量因字数上限压缩后再次通过，没有删其他 Outcome。
- Memory 新运行的四个完整 turn、Provider 调用数、usage 和 transcript hash 逐项复算 **4/4 一致**；临时 OAuth 文件已清除，运行进程已退出。
- 新 Room + Memory 两组实际模型调用共 **8 次、23,394 tokens、估算 $0.00453236**。首轮的失败/未知成本仍独立保留，不说所有历史成本已结清。
- 导出包 SHA256：`a2b0d979df54b6f53e6b371b5efcb689a8bee8b6607af1344af01e5c56bc9519`。三个隔离 HTTP 回执与四个真实界面回执绑定同一归档。
- 未提交、推送、安装或发布。用户反馈卡顿后关闭了三组自动化 Chrome，普通 Chrome/Edge 保留；本次所有临时验收页面与服务也已关闭。
