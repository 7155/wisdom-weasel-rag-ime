# PAW 简历与演示证据稿 · 2026-09-05

这是项目经历的改写候选和证据索引，尚未写入个人简历母版。当前数字读取
`agent-experiments.v1.json` 与 `evidence-ledger.v1.json`；运行记录、单次 Validation、
private-shadow、安装态和生产效果分别陈述。

## 本次演示主线

**用同一套 Lab 流程，针对不同业务任务寻找通过质量门禁的低成本配置。**
每个场景依次展示任务与 Golden、基线失败、Trace 归因、一个候选改动、同题复验、
Keep/Reject 和可回放证据。已测候选中的选择不等于所有模型与配置的全局最优。

四个业务场景是 EnterpriseOps、Enterprise RAG、CloudOps、Memory Maintenance。
多 Agent、Memory、Knowledge 是跨场景能力；它们的收益需要单独消融，不能把某次
场景优化的全部收益归给多 Agent。

## 四个场景的当前结果

成本降幅由表内前后值计算；这些是 Runtime 用量对账或确定性定价估算，均不是
Provider 账单。不同场景不合并为一个总成功率或一个总节省率。

| 场景与冻结分母 | 质量结果 | API 估算成本 | 当前可解释结论 |
| --- | --- | --- | --- |
| EnterpriseOps：3 个任务、31 条 SQL 验收 | 任务 `3/3 → 3/3`；验收 `31/31 → 31/31`；候选 Tool 失败 `0` | `$1.711214 → $0.07291692`，降低 `95.74%` | Sol 基线 → Luna model-only 被拒绝 → Luna 通用 Prompt 适配后保留；三阶段结果，单轮 Validation |
| Enterprise RAG：4 个问答、9 条必要事实 | 完整任务 `3/4 → 4/4`；引用事实 `7/9 → 9/9` | `$2.170603 → $0.1029376`，降低 `95.26%` | Sol → Luna model-only → Luna Prompt-v4；采用已经观察候选的 r6 标准，不能称盲测或独立泛化结果 |
| CloudOps：12 个故障任务 | CA/Top3JRA 保持 `100%`；FA/JRA `83.33% → 91.67%`；候选 Tool `130/130` 成功 | `$4.568166 → $0.27613024`，降低 `93.96%` | Luna model-only 被拒绝后，通过通用 owner/mechanism Prompt 恢复并改善质量；单轮 Validation |
| Memory Maintenance：5 个 synthetic fixture（4 durable + 1 non-memory） | 两侧均有 5 次整理决策、6 个受治理且 lineage 合法的 atom；5-case 检索门禁和回滚/重放通过；各 2 请求、0 失败 | `$0.163425 → $0.0071846`，降低 `95.60%` | 新 Pi current-runtime 配对，full-json-v1 + standard-v1 + max，仅换模型；不代表生产个人记忆或旧 CLI Prompt 复现 |

对应实验 ID：

- `enterpriseops-csm.luna-prompt-adaptation-r7.v1`
- `enterprise-rag.luna-prompt-v4-standard-r6.v1`
- `cloudops.luna-owner-mechanism-prompt-r5.v1`
- `memory.maintenance-pi-model-only-20260905-r3.v1`

每个 ID 在 [`agent-experiments.v1.json`](agent-experiments.v1.json) 中绑定 baseline、
candidate、factors、frozenControls、comparison、claim 和原始回执路径。演示页面应
从这些字段读取，不手写第二套分数。

Memory 的旧 `memory.maintenance-luna-model-only-r1.v1` 仍独立保留：它使用 CLI 与
concise-json-v1，成本 `$0.269115 → $0.0107502`，不能混作这轮 Pi 的新收益。
新配对 Runtime DB/transcript 用量已对账；token `14,450 → 15,078`，没有下降。
当前公开 Trial 回执只输出聚合门禁，不把它扩写为逐 case 的 durable/abstention pass 计数。

## 简历改写候选

### Bullet 1 · 垂直场景优化平台

**原句**：构建 Agent 评测平台，并优化模型成本。

**问题**：没有说明成功标准、可修改对象和质量保护方式。

**建议改写**：构建基于 Pi Session/Room 的垂直 Agent 实验平台，实现 Golden 起草、审核、
Judge 校准和问答 Prompt 对照；以固定业务任务和 Host verifier 完成 EnterpriseOps 的 3 任务/31 验收
单轮 Validation 中，通过低成本模型与通用 Prompt 适配保持 `3/3、31/31`，API
成本估算降低 `95.74%`。

**依据**：`enterpriseops-csm.luna-prompt-adaptation-r7.v1`；Golden 四步实现与测试；
`agent-eval-room-optimizer` 的对象级优化合同。

**事实状态**：`section=projects; source=artifact; confidence=high; metric_status=verified`
（已核验的是估算计算与质量回执，不是实际账单；四业务场景的通用候选执行闭环仍在接入，
不能把 Golden 的问答 Prompt 执行能力写成已完成任意 Tool/Skill 自主优化）。

### Bullet 2 · Knowledge 与答案证据

**原句**：实现 RAG 知识库，提高检索准确率。

**问题**：检索质量与最终回答质量混在一起。

**建议改写**：为 5,101 篇企业文档、29,846 个 chunk 建立冻结检索评测，比较 14 组
检索配置，在 16 条 Validation query 上将 nDCG@10 从 `0.613` 提升到 `0.887`；
进一步以逐事实引用与拒答门禁评测答案，使开发集候选从 `7/9` 引用事实覆盖达到 `9/9`。

**依据**：`enterprise-rag.retrieval-selection.v1`、
`enterprise-rag.luna-prompt-v4-standard-r6.v1`。两段使用不同任务分母，必须分段陈述；
答案段是 candidate-aware Validation。

**事实状态**：`section=projects; source=artifact; confidence=high; metric_status=verified`。

### Bullet 3 · 记忆治理与低成本执行

**原句**：实现长期记忆与自动整理。

**问题**：缺少“什么应记、什么不应记”以及失败恢复的证据。

**建议改写**：实现 Evidence/Atom/Book 记忆治理与可重放整理流程，在 5 个合成 fixture 的
当前 Pi 配对中，两模型均完成 5 次整理决策并通过检索、回滚和重放门禁；固定
full-json-v1、standard-v1、max 与业务输入，仅替换模型，在共 4 次请求、0 失败的单轮
验证中，将 Runtime 对账成本估算从 `$0.163425` 降至 `$0.0071846`（`95.60%`）。

**依据**：`memory.maintenance-pi-model-only-20260905-r3.v1`。这是 synthetic validation，
不是生产个人记忆质量、Held-out 泛化、旧 CLI Prompt 复现或 Provider 实际账单。

**事实状态**：`section=projects; source=artifact; confidence=high; metric_status=verified`。

### Bullet 4 · 多 Agent 协作

**原句**：多 Agent 显著提高效率和成功率。

**问题**：当前没有同预算、同模型、同任务的单 Agent/多 Agent 完整对照，不能写收益比例。

**建议改写**：实现轻量 Room 协作与私有 Tool Agent 委派，统一消息路由、取消、终态和
刷新恢复；在一次安装开发版验收中完成 3 个参与者、2 个委派伙伴、19 个 Tool step 的
端到端任务，并保持唯一 final 和刷新恢复。

**依据**：`room.installed.self_host.20260816`。这条证明协作机制可运行，不证明普遍加速。

**事实状态**：`section=projects; source=artifact; confidence=high; metric_status=verified`。

## 还要补的收益指标

| 能力 | 必须比较的基线 | 主指标 | 解释与保护指标 |
| --- | --- | --- | --- |
| 多 Agent 并行分工 | 单 Agent、同模型私有委派、同模型 Room；相同任务与总预算 | 完整任务成功率、每成功任务成本 | 墙钟时间、重复工作率、交接成功率、消息开销、取消/恢复一致性；只在独立子任务足够多时预期加速 |
| 多 Agent 复核 | 单 Agent 与额外 reviewer；固定检索结果和回答预算 | 错误检出率、最终任务成功率 | 误拒率、额外成本、reviewer 是否给出可定位证据；不能把 reviewer 自评分当真值 |
| Memory 召回 | 无记忆、直接历史、治理后召回 | 任务成功率、Recall/MRR、正确拒记率 | 无关上下文注入、过期/冲突信息、跨范围泄漏、输入 token；按 temporal/update/abstention 分组 |
| Knowledge RAG | lexical、hybrid、rerank、agentic retrieval | Recall@K、MRR、nDCG、最终答案成功率 | 事实覆盖、引用支持、拒答、检索与回答分别计价；检索改善不自动代表答案改善 |
| 自动优化循环 | 固定原方案与各个单变量候选 | 同题成功率、每成功任务成本 | 候选数、优化本身成本、回本任务量、质量回退、停止原因、最终保留集结果 |

这些是待运行的测量合同，不能直接填写提升百分比。当前 LongMemEval 的改进很小且
部分 Recall 回退，不能用 Knowledge 的成绩替代 Memory 的成绩。

## 自举能力的当前边界

- Golden 已具备起草、人工审核、Judge 校准、冻结后 Prompt 候选运行与留出题验证。
- 场景实验工作区已声明 Prompt/RAG/Tool/Skill/Workflow 对象、配置/实现层、候选数、
  预算、反事实探针和证据要求，执行仍复用真实 Room/Pi。
- 通用 Tool/Skill/Workflow 的实际自动修复收益、四场景无人干预连续运行、未见任务
  泛化及多轮稳定性尚未全部完成；演示不能把合同存在说成这些结果已经验证。
- API 成本只在质量门禁通过后比较；优化器、Judge 和业务答案成本分开，保留失败尝试。

## 本次核验

`python3 scripts/check_interview_metrics.py --json` 通过：40 个指标、46 份运行、12 个
数据集条目。该检查证明账本内部一致与引用存在，不代替重跑或当前安装版验收。


## 小预算自举补充 · 2026-09-05

[最新五类实测](../micro-selfboot/FIVE_METRIC_RESULTS.md)与[技能流审查](../micro-selfboot/SKILL_FLOW_REVIEW.md)提供独立补充证据：8 类受控执行故障各 20 次，共 160/160 通过、重复副作用 0；真实 Memory consumer 后四个 Pi Session 的接续回答 4/4；同一 Lab 配置导出独立费用 Web App，隔离启动 3/3、四条界面业务验收 4/4。费用 Web App 只依赖 Python 标准库，合成规则与生产业务分开。

Room 同模型同预算上限的三 case 对照两侧均 2/3，Room 成本更高；小费用候选质量保持但没有降本。完整 Pi turn 对账含中间调用，失败及诊断都保留。不能把这组小样本并入前述四业务场景的成功率或成本降幅。

简历可选表述：构建复用 Pi 的 Lab 小任务评测与诊断闭环，按完整 turn 对账成本并保留拒绝候选；在 8 类受控执行故障的 160 次观察中未出现重复副作用，4 个合成 Memory 接续任务全部通过，并将 Lab 配置导出为独立费用规则 Web App，通过 3 次隔离启动及 4 条界面业务验收。

这不代表生产长期记忆、复杂任务多 Agent 收益、掌柜问数脱离 Gateway 独立运行或原生 App 安装验收。当前简历母版未改。

### 已实现的 Room 工作流优化收益

[前后证据与自举过程](../micro-selfboot/OPTIMIZATION_RESULTS.md)：同模型、同 worker 输入的三个合成契约检查，基线和程序合并候选均 3/3。冻结候选在新 Room 中确认后，模型调用 **3→2**，完整 turn tokens **9,911→6,394（-35.49%）**，每成功完整组目录价估算成本 **$0.00203172→$0.00152980（-24.70%）**。基线为保留的匹配运行，没有虚构第二次基线。

简历可选表述：基于 PAW 自身的 Lab、Room 与 Pi 运行链路建立评测优化闭环，定位并移除结构化协作中的重复模型整合；在同模型、同输入的三个契约检查全部通过时，将模型调用由 3 次降至 2 次，复验 token 用量降低 35.5%、目录价估算成本降低 24.7%。

主 Session 实现受限 operator，PAW 的真实 Lab Pi 诊断从可用 operator 中选择，Host verifier 判定质量并复核八条完整 turn。首次整轮超出 20k 结算观察阈值 407 tokens 的失败回执保留，确认两次调用处于 10k 阈值内。旧 2/3 对照与新的 typed-contract-v2 不拼成质量提升；首次候选有缓存、确认无缓存，因此摘要使用确认的降幅。该结果证明窄 Room 工作流开销可优化，不证明多 Agent 胜过单 Agent、生产平均降本或自动生成任意修复代码。


### 中等任务与 OS 展示 · 2026-09-06

[中等任务实测](../micro-selfboot/MEDIUM_TASK_RESULTS.md)已经完成一组单 Session / Room 对照。相同任务、空实现、Luna low 与累计预算下，两臂均为完整任务 **0/1**、实现检查 **16/20**、交付 **0/4**；Room 进入真实 Host 重启后的追加需求阶段，但没有完成整题。不能写成任务成功率提升。成本只包括已观察部分，未知在途费用不补零。

[OS 结果页](../micro-selfboot/OS_RESULTS.md)汇总本轮八条记录，覆盖五类目标、Room 整合正向收益及中等任务的负结果；验收、费用用量与取消恢复可切换查看。单轮通过与配对改善分开，160 次故障观察不换算成 160 个独立任务。新增测量使用独立合成任务，不改变前述四业务场景的分母。
