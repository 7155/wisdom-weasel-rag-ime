# Agent Lab 面试数据卡（更新至 2026-09-03）

这份文档是 Agent Lab 的面试讲述入口。它把“能改的实验变量”“必须冻结的对照条件”“确定性验收指标”和“暂时不能声称的范围”放在同一张账上。数字只来自仓库里的评测回执；没有运行回执的内容标为 `OPEN-GAP`。

## 一句话定位

PAW 不是把所有 Agent 结果平均成一个分数，而是提供一个可复用的实验场：在同一份冻结数据和 Host 验收器下，分别改变 Model、Prompt、Skill、Tool、Workflow、Context/Memory/RAG、Guardrail、执行策略和人工审核边界，记录 before/after Trace，最后由 Host verifier 决定 Keep、Reject 或 Rollback。

Agent Lab 是统一展示层，不是新的 Agent Runtime。RAG、CloudOps、EnterpriseOps、Trace/Memory 和模型成本都使用同一份实验合同；掌柜问数/SGG 作为独立的垂直沙盒，不能把一个 Text2SQL fixture 包装成生产准确率。

## Agent Lab Room 闭环（当前产品要求）

每个垂直场景拥有自己的主指标和保护门禁。用户从 Agent Lab App 进入该场景的
App-owned Room，先补齐数据并确认评测合同；Facilitator 再一次并行提出一批候选，
每个候选只改变一个层（Model、Prompt、Skill、Tool、Workflow、Context/RAG 或
Memory）。候选实际运行前必须得到用户确认，且 Room 消息中包含：失败原因、要修复的
具体问题、改动层、预期指标、保护门禁和验证方式。

Validation 可在用户确认后自动执行；失败、回退和不可比候选都保留，不能删除或重跑到
“好结果”。候选完成后，多个 Trace Reviewer 使用全新上下文并行检查前后 Agent Trace，
只接收受限 evidence envelope、Trace Prompt 和 Trace Skill；Host-private Verifier
负责最终通过/失败，Facilitator 只负责汇总。用户可以保留、继续下一轮或停止；达到该
场景的目标即停止，不为穷举所有分支继续消耗调用。Luna 是每个场景里的 Model 候选，
不是单独场景。

Agent Lab Room 的对话、Session、沙盒和评测证据归 App owner 管理，不进入普通 Agent
项目列表、项目记忆或项目上下文。简历表述从最终回执另行生成，不出现在用户产品页面。

## 实验变量与冻结控制

| 类别 | 可调整变量 | 典型实验问题 | 必须冻结的控制 |
| --- | --- | --- | --- |
| Model | provider、model、thinking、上下文上限 | Sol 与 Luna 的质量/成本边界是什么？ | provider/model identity、pricing snapshot、调用预算 |
| Prompt | 任务契约、日期/角色语义、输出格式 | 缺少 as-of date 是模型错还是输入契约错？ | Prompt hash、system/developer 层级、同一用户任务 |
| Skill | 诊断规则、路由卡、Room 优化流程 | Trace Skill 是否真的增加 first-failing-span 召回？ | Skill revision、路由条件、公开/私有证据边界 |
| Tool | catalog、权限、transport、幂等键 | Tool 不可达时是 Agent 拒绝还是 Gateway 缺陷？ | Tool catalog、capability token、权限策略、Tool 版本 |
| Workflow | 单 Agent、Room、plan→execute→verify、重试策略 | 多 Agent 是否减少返工而非增加 orchestration tax？ | case 顺序、阶段依赖、timeout、取消/恢复规则 |
| Context / Memory / RAG | 来源、chunk、BM25/dense/RRF、rerank、压缩 | 召回提升是否传递到最终引用和拒答？ | corpus/index/qrels、source revision、split、token budget |
| Guardrail | schema、citation、abstention、fail-closed | 能否阻止 unsupported claim 或部分写入？ | evaluator/gold、hard gates、分母和拒答定义 |
| Execution policy | sandbox、network、workspace roots、approval | 候选修复能否在不影响 PAW 的沙盒落地？ | runtime identity、sandbox profile、workspace digest |
| Human loop / Pricing | 审核点、授权、实际 API 价格 | 省钱是否建立在相同质量和相同 token 口径上？ | 审核权限、账单/usage receipt、价格日期与来源 |

**实验原则：** 一次只改变一个主要变量或一组有明确因果关系的变量；先在 Validation 诊断，候选通过硬门禁后才允许一次性 Held-out。质量未达到同一水平时，不用 token、延迟或价格宣布“更高效”。

## 已有六张业务实验卡 + 一张成本门禁卡

### 1. EnterpriseOps CSM execution-chain repair（保留，基础设施结果）

- 业务：跨实体客户支持修改需要真实 Tool、依赖顺序、幂等写入、终态验收和临时数据库清理，不能用一条聊天回复代替。
- 对照：3 条 Validation task、31 个 Host-private verifier、同一 seed 和 Gold 隐藏。
- 变化：read-only/错误 transport → capability-token Gateway + per-action authority；best-effort verifier/cleanup → fail-closed lifecycle。
- 结果：业务 Tool 调用 `0 → 47`，Tool failure `0`，可执行 verifier `3/31 → 26/31`；三份临时数据库全部清理。
- 讲法：这是执行链修复，不是“业务质量提升 74.19 个百分点”，也不是 100% 或生产验收。Suite v2 另有一次 Held-out，不能与这张历史卡混写。

### 2. EnterpriseOps CSM state-contract selection（拒绝推广）

- 业务：请求含精确字符串、相对日期、角色身份和跨实体状态，最终数据库必须满足 Host verifier。
- Validation：state-contract 候选 `3/3 task、31/31 verifier`。
- Held-out：一次性 `1/8 task、54/65 verifier`，8/8 turn 完成，140 次 Tool、2 次 Tool failure，8/8 cleanup。
- 变化：补齐 `2025-11-04` as-of、exact-string/dynamic-owner contract，并只增加需要的 `find_locations` Tool。
- 决策：拒绝 Promotion。失败保留为泛化证据；不能为了 100% 改分母、改 Gold 或重跑 Held-out。

### 3. Enterprise RAG retrieval selection（诊断性保留）

- 业务：企业问题同时包含精确标识、语义表达、冲突修订和跨文档完整性；只用 lexical 会漏召回或排序过晚。
- 对照：5,101 篇文档、29,846 个 chunk、16 条冻结 Validation query，qrels 对检索器隐藏，Held-out 未消费。
- 变化：lexical floor → BM25+dense hybrid、RRF 变体和 Qwen3 reranker depth 对比；保留 lexical floor 作为独立来源。
- 结果：Recall@10 `0.6719 → 0.9554`，nDCG@10 `0.6128 → 0.8872`，MRR `0.6042 → 0.8672`。
- 边界：这是 retrieval Validation 结果，不等于最终答案引用、拒答或生产提升；answer/citation gate 仍是 `OPEN-GAP`。
- Tag/Graph 的定位：Tag 图可以做实体扩展、关系过滤或候选去重，但它不是天然的 reranker。要比较“Tag 能否替代 Qwen3 reranker”，必须固定同一 corpus/query/qrels/Top-K，在 `hybrid+rerank`、`hybrid+tag`、`hybrid+tag+rerank` 三组上测 Recall、nDCG、引用覆盖、延迟和候选独立来源数；当前 Graph+Tag readiness 为 0 node / 0 edge，不能先写成已替代。

### 3A. Enterprise RAG Luna Max answer-evidence candidate（Reject）

- 这是 Enterprise RAG 的单因素 Model 候选：只把 `gpt-5.6-sol / max` 换成 `gpt-5.6-luna / max`；Prompt、Skill、Tool、Workflow、Context/RAG、corpus、split、qrels、answer-case 选择、judge contract 和 hard gates 均冻结。候选使用 source-local `build/managed-pi-runtime/luna-output-budget-compat-920e42b9c`，未安装。
- 对照与合同：5,101 documents、29,846 chunks、同一 16-query Validation retrieval slice；同一 host-private `fact → source/chunk/quote` 合同覆盖 9 个必要事实、11 个 support groups、13 个 source/chunk/quote bindings；只评分 4 个 answer cases：`qst_0474`、`qst_0477`、`qst_0488`、`qst_0492`。Held-out 未打开，qrels 未进入 Agent 或 Judge。
- Aggregate（全来自真实 v20 report；`latencyMs / tokens / Tool calls / search calls`）：

  四 lane 的 Judge/answer 结果为：baseline `2/4`、Skill `2/4`、tuned `2/4`，Agentic `0/4`；这只是同一 4-case Validation 的报告内结果，不是生产质量结论。

  | lane | Judge / answer success | fact / citation fact | citation support | abstention accuracy | latency ms | tokens | Tool / search | failed hard gates |
  | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
  | baseline | 0.50 / 0.50 | 0.6667 / 0.2222 | 0 | 1.00 | 51,577.706 | 25,778 | 6 / 5 | citationResolution |
  | Skill | 0.50 / 0.50 | 0.6667 / 0.2222 | 0 | 1.00 | 208,063.982 | 74,769 | 7 / 5 | citationResolution |
  | tuned | 0.50 / 0.50 | 0.6667 / 0.2222 | 0 | 1.00 | 182,436.769 | 88,941 | 7 / 5 | citationResolution |
  | Agentic | 0 / 0 | 0 / 0 | 0 | 0.50 | 420,642.371 | 7,713* | 12 / 7 | abstention, agenticPolicy, citationResolution, terminalCompletion, toolContract |

- Per-case output/evidence/Judge（只公开报告内的 hash 与标签，不伪造 transcript）：
  - `qst_0474 / case-01`：baseline Judge `incomplete`, output `ed1709f5…`, answer fact `0.4`, citation `K3` resolved but support `false`; Skill `cda07b55…`、tuned `cc6cf11a…` 同为 `incomplete`, `K3,K10` resolved but unsupported；Agentic output `e3b0c442…`、无 citation、`incomplete`。
  - `qst_0477 / case-02`：baseline Judge `correct`, output `13c9133d…`, answer fact `1.0`, citation `K1` resolved but support `false`; Skill `df74d501…`、tuned `38e31c54…` 同为 `correct`；Agentic output `e3b0c442…`、`incomplete`。
  - `qst_0488 / case-03` 与 `qst_0492 / case-04`：baseline/Skill/tuned 均 `correct_abstention`、无 citation；Agentic 均 `abstention_mismatch`，无有效答案 output。
- 失败归因：baseline/Skill/tuned 不是 citation 缺失，而是 citation 已 resolve 但逐事实 source/chunk/quote support 为 `false`；Agentic 的 delegation Tool receipt 报错，parent query policy 与 coverage audit 失败，最终没有 `cases[]` JSON 和 terminal completion。`7,713*` 是不完整 Agentic usage，不是零成本或可与 Sol 的失败占位 `0` 比较。
- Luna 与 Sol v16 的受控描述性 delta：baseline/Skill/tuned 所有质量指标均 `0` 变化；Luna latency 分别 `-12,115.480 ms (-19.02%)`、`-16,416.000 ms (-7.31%)`、`-28,229.551 ms (-13.40%)`，tokens 分别 `+394 (+1.55%)`、`+6,365 (+9.31%)`、`+6,470 (+7.85%)`，Tool calls 不变。Agentic latency `-179,962.585 ms (-29.96%)`、Tool `-1`，但 Sol token 是失败占位且 Luna token 不完整，不能报 token/cost delta。没有冻结 USD 价格或 Provider bill，故不报成本节省。
- 决策：`Reject` promotion，保留失败 candidate、per-case output/evidence/Judge hash、lane session/turn hash 和 usage。Runner 完成后清理 run-owned managed Session JSONL；receipt 不声称 raw transcript 仍存在。正式 receipt：`runs/enterprise-rag-answer-evidence-luna-max-validation-20260902.v1.json`；私有原始报告：`.rag-ime-data/eval/results/validation-answer-evidence-luna-max-v20.json`。

### 3B. Enterprise RAG Graph+Tag readiness（Open-gap / Blocked）

- 这是读取 `runs/enterprise-rag-tag-reranker-readiness-20260901.v1.json` 的只读 readiness 行，不是 A/B：同一冻结 Enterprise RAG Validation 为 `5,101` documents、`29,846` chunks、`16` queries；当前 source-bound Graph 为 `0` nodes、`0` edges、`0` extractions，Tag metrics 不可用。
- 已测参照只保留现有 Qwen3 reranker：MRR `0.8672`、nDCG@10 `0.8872`、Recall@10 `0.9554`。Memory Tag 的 `memory_item_id` 与 Knowledge 的 `document_id + chunk_id` 不直接兼容，因此没有填 Graph+Tag 分数，也没有把它写成优于、劣于或等价于 Qwen3。
- 下一条候选路径必须先生成带 `sourceChunkId/evidenceSpan/contentHash/revision` 的企业 Graph，再在相同 pool/depth 下比较 no-rerank、Qwen3、Graph+Tag、Graph+Tag+Qwen3；Held-out 未消费。正式 receipt：`runs/enterprise-rag-tag-reranker-readiness-20260901.v1.json`。

### 4. Trace Agent closed-loop historical replay（证据缺口）

- 业务：根因经常早于最终报错，诊断必须找 first-failing-span、owner 和必要 Evidence，再授权修复。
- 对照：3 条公开历史 episode；Host-private diagnosis Gold、after-state 和私有原文不进入 Agent 输入。
- 变化：错误字符串查找 → Trace Skill + public-safe scorer；建议直达结论 → 诊断→授权→新 Validation Trace/Eval→Keep/Reject。
- 当前结果：scorer 和 manifest 已通过聚焦测试；尚未执行 Provider prediction，因此不能声称 Trace Agent 准确率或“自动修复”。

### 5. CloudOps evidence workflow validation and falsification（保留 baseline，拒绝省调用候选）

- 业务：云上告警需要跨服务观察、证据读取和根因判断；少调 Tool 不代表诊断更准。
- 对照：同一 12-case Validation、3 个真实 PAW Session、Sol/max、Host-only scorer，Held-out 未消费。
- 结果：baseline 12/12 作答、98/98 Tool 成功、CA `1.00`、FA/JRA/Top3JRA `0.8333`；bounded workflow 少 16.33% Tool、少 13.36% wall time，但 CA/JRA 回退并发生地址失败，故 Reject。
- 讲法：这张卡体现“效率必须服从质量门禁”和保留反例；不写成生产 AIOps 或成本降低。

#### 5A. CloudOps 候选路径（同一 Validation，逐轮保留）

| round | changed layer | evidence-backed observation | quality / reliability | efficiency / decision |
| --- | --- | --- | --- | --- |
| baseline | execution environment contract | 12/12 answers、98/98 business Tool、0 failure | CA `1.00`；FA/JRA/Top3JRA `0.8333` | incumbent；Provider usage 不可用，不报成本 |
| evidence-search-v1 | workflow | 两阶段 search/list/read；0 Tool failure | CA `0.8333`、JRA `0.8333`、Top3JRA `1.00` | 189 Tool、106 search、15 list、62 read、996,035 ms；Tool `+92.86%`，Reject |
| bounded-workflow-v2 | workflow | bounded search/read；一个长 key read 失败 | CA `0.75`、JRA `0.75`、Top3JRA `0.8333`；1 Tool failure | 82 Tool、1,175,311 ms（Tool `-16.33%`、时间 `-13.36%`）；Reject |
| observationId-v1 | tool | case-scoped observationId 消除 public cache-key read；0 Tool failure | CA `0.50`、FA `0.5833`、JRA `0.4167`、Top3JRA `0.50` | 94 Tool、1,248,603 ms；Reject 并触发“不再第五轮” |
| Luna Max model-only | model | 三个 session/receipt 观察，第三批与 abort timeout；正式 CA/JRA 不可用 | 不对 CloudOps 质量作结论；`effectStatus=not_run` | receipt `1718516 ms`、916,112 input、57,057 output、18,809,344 cache-read、278 transcript Tool/14 failures；`Reject，仅保留失败回执` |
| runtime-selection retry3 | workflow | retry2 在 Runtime 应用正式 thinking 选择前就提前校验，因时序错误未进入 Prompt | 改为 `ensure runtime → 校验 provider/model → 选择 thinking → 校验选择回执 → Prompt`；其余全冻结 | 选择校验 `0→1`、Prompt 进入 `0→1`；随后 8 次 Provider `fetch failed`、0 Tool、0 canonical submission、无 formal score/usage；`Reject，失败消耗无法计价` |

CloudOps Luna 原 timeout 行是 report-only：页面保留 `session/receipt count=3`，但 `readable transcriptCount=0`，不得渲染为三份可读对话；没有 formal CA/JRA 时不把 Runtime 失败写成质量回退。该次已用真实 usage 和冻结 Luna 价格估算出失败消耗 `$0.62787768`，但它是 burn，不是节省或 Provider 账单。retry3 是另一条 workflow-only 消融：它证明运行时选择顺序修复生效，但不证明 CloudOps 质量；因 Provider 请求在网络层失败且 usage 不可用，本次不定价。两条都只在隔离实验环境验证，尚未应用到当前系统。回执：`runs/cloudops-luna-max-baseline-validation-20260902.v1.json`、`runs/agent-lab-cost-cloudops-luna-failed-run-20260902.v1.json`、`runs/cloudops-luna-max-baseline-validation-20260902-retry3.v1.json`；其余轮次回执分别为 `cloudops-evidence-search-validation-reject-20260901.v1.json`、`cloudops-bounded-workflow-validation-reject-20260901.v1.json`、`cloudops-observation-id-validation-reject-20260901.v1.json`。

### 6. Memory / Personal RAG shadow evaluation（诊断性）

- 业务：长期记忆要找回有用事实，也要挡住旧输入回声、跨项目内容和已经删除的候选。
- 对照：74 条私有 shadow 语义复核；另有 16 个行为 case 重复 3 轮；scope、墓碑和 Evidence 边界固定。
- 变化：把 Evidence → Atom → Book、hybrid/tag retrieval、token budget、反回声和反馈门禁放进同一条生命周期链。
- 结果：私有 shadow 独立复核 `74/74`，4 个 recall case 均 direct rank-1；行为 gate `16 × 3 = 48/48`，端到端 p95 `37 ms`。
- 边界：没有同一任务的 before/after 质量对照，所以只记为 diagnostic；不能写成 LongMemEval 泛化准确率或 uplift。

#### 6A. Memory Maintenance Luna v1 → v5（只读 private-shadow 候选路径）

- 历史起点：真实月度维护在 `834.945 s` 后以未闭合 JSONL 失败；这只是已有实验卡记录的 failure boundary，不补造一份不存在的 transcript。以下每一轮只引用仓库现有 v1/v3/v4/v5 receipt，生产 SQLite、Held-out 和安装态均未打开。

| round | changed layer | receipt-backed result | decision |
| --- | --- | --- | --- |
| v1 | replay | 5-case（4 durable + 1 non-memory）fixture、rollback 通过；replay attempted 但 `pass=false`，未复用 model outputs、logical state 不 identical，vector coverage `0.0` | Reject |
| v3 | boolean gate | 同一 5-case fixture、rollback 通过；exact snapshot、复用 outputs、identical state 均 `true`，但 replay gate 仍 `false`，vector coverage `0.0` | Reject；不写成业务质量回退 |
| v4 | dense provider | fixture、rollback、replay 均通过，5 cases / 4 durable / 1 non-memory；vector coverage 仍 `0.0` | Reject；dense gap 未闭合 |
| v5 | dense provider + receipt | `5/5` retrieval/fixture、`4` durable、`1` non-memory，vector coverage `1.0`、projection fresh、backlog `0`、rollback/replay/identical state 通过，合法 JSON receipt，CLI tokens `24,399` | Keep（仅 private-shadow） |

v1/v3/v4/v5 的真实回执分别是 `runs/memory-maintenance-luna-max-validation-20260902.v1.json`、`.v3.json`、`.v4.json`、`.v5.json`。v5 只证明评测 Workflow 在 private shadow 中补齐 replay、布尔门禁、dense provider 和 receipt contract；没有 USD 成本、生产 Memory 修复或 Held-out 泛化。

### 7. Model cost gate（EnterpriseOps Validation 已完成，候选 Reject）

- 目标：在同一 task manifest、Prompt、Skill、Tool catalog、Workflow、runner、Runtime provenance、thinking 和硬门禁下比较 Sol/max 与 Luna/max 的真实 usage 和单位成功任务成本。
- 目标口径：Luna 固定为 `gpt-5.6-luna / max`，门禁是“质量不回退且 API 成本估算降低 ≥80%”；Dataset、Verifier、`thinking=max`、900 秒 timeout 和 2026-09-01 价格来源保持冻结。
- 已完成：在当前同一源码上重跑 Sol/Luna；receipt checker 跨绑 model/thinking、task manifest、Prompt、Tool catalog、runner、Runtime provenance、usage source 和 pricing source；Decimal cost receipt 继续明确估算与账单分离。
- 实测：Sol 为 `3/3 task、31/31 verifier、87 Tool（1 次已恢复失败）、3/3 cleanup`；Luna 为 `2/3 task、30/31 verifier、66 Tool、0 Tool failure、3/3 cleanup`。总 token `3,964,517 → 3,609,609`，总耗时 `1,112.65s → 929.66s`（`-16.45%`）。
- 成本与决策：按同一冻结价格来源，API 成本估算 `$3.243385 → $0.725239`（`-77.64%`）。成本目标未到 80%，且 task/verifier 质量回退，所以候选 Reject、保留 Sol；便宜和更快不能抵消质量失败。
- 边界：usage 来自两次匹配运行的 Runtime DB Provider 事件；这是确定性估算，不是 Provider 账单，也不外推到 CloudOps/RAG/Memory。运行与成本回执为 `runs/enterpriseops-csm-sol-max-validation-20260903.v1.json`、`runs/agent-lab-cost-sol-max-20260903.v1.json`、`runs/enterpriseops-csm-luna-max-validation-20260903.v3.json`、`runs/agent-lab-cost-luna-max-20260903.v3.json`，质量优先选择回执为 `runs/agent-lab-optimal-path-model-cost-20260903.v2.json`；旧的 `-96.43%` 结论因 thinking/source provenance 不匹配已撤回。

## 面试问答（可直接展开）

**问：你们的 LLM-as-Judge 到底怎么打分？**

答：PAW 不让 Judge 一个人决定发布。以 Enterprise RAG 的 answer-evidence
评测为例，Runner 先冻结并匿名化每条 lane 的候选答案；Judge 只看到问题、公开
reference answer，以及该候选实际引用到的证据正文，看不到检索 qrels、指标反馈和
候选名称。Judge 必须先把题目明确询问的实体、数字、日期、方向或动作拆成
`requiredFacts`，再为每个候选输出严格 JSON：`coveredFactIds`、是否矛盾、是否含无
证据的重要主张、`correct` 和 `reasonCode`。所有必答槽位都覆盖才是 `correct`；漏一项
是 `incomplete`，与证据矛盾是 `wrong`，有证据却拒答是 `abstained`，额外的重要主张
没有引用支持是 `unsupported`。Rubric 明确不奖励文风、长度或复述 reference 的措辞。

Judge 输出还要经过确定性解析器：case/candidate 必须一一齐全、reason code 必须在
白名单、fact ID 必须来自本题，否则整次 Judge receipt fail closed。之后 Host 再用
隐藏的 `fact → source/chunk/quote` qrels 独立检查 citation 是否可解析、每条必要事实是否
真的被所引原文支持；Schema、终态、Tool contract、拒答和 citation 都是发布硬门禁，
最后才比较 token、耗时和价格。因此 Judge 是语义评分层，不是唯一真相来源。

当前诚实边界：本项目已有匿名化、严格 JSON、逐事实 rubric、确定性 hard gate 和失败
回执，但这批 RAG receipt 没有绑定一份“多位人工标注者与 Judge 的一致率”校准报告，
所以面试中不能声称已证明 85% 人类一致性。下一步应在独立标注子集上报告一致率、
分歧类型和复核规则，而不是只换一个更强 Judge 后自行宣布可靠。

实际例子：`qst_0474` 问的是 Redwood inference engine 明确列出的 serving-runtime
优化。Judge 从题目和 reference 拆出 5 个必答事实：modern attention、continuous
batching、KV/prefix cache、quantization-friendly path，以及同时感知 architecture、
sequence length 和 hardware 的 kernel selection。旧 v20 receipt 中 baseline、Skill、
tuned 都只覆盖 `F2 + F3`，没有矛盾、也没有额外无依据主张，但因为少了另外 3 项，仍
统一判为 `incomplete`，不能因“答到两个关键词”给部分成功。`qst_0477` 则询问 4 类收入
来源；候选覆盖 `F1–F4` 后 Judge 判 `correct`。但旧 receipt 中该答案的 citation support
仍未通过 Host qrels，所以最终仍被发布硬门禁拒绝。这正好说明“语义答对”不等于“引用
证据正确”。

**问：Golden Data（不是 goalen data）怎么做？**

答：先定义成功的最小可验收事实，再做数据，而不是先收一堆日志。当前 Enterprise RAG
使用公开 EnterpriseRAG-Bench 的真实语料，固定 `5,101` documents、`29,846` chunks、
split、case 选择、chunking 和检索配置；answer-evidence Validation 冻结 4 个 case，
其中 2 个可回答、2 个应拒答，避免用“每题都回答”刷分。可回答题被拆成 9 条必要事实，
再绑定到 11 个 support group、13 组精确的 source/chunk/quote 证据；拒答题把
`abstentionExpected` 作为独立 Gold。

Gold 保存在 Host-private manifest，不进入 Agent Prompt；检索 qrels 也不进入 Judge。
manifest 同时绑定 prepared source hash、split、chunking hash、fact hash、document hash、
精确 quote 和总 manifest hash。加载时只要题目漂移、split 不符、fact hash 不符、文档
变化、quote 不在对应 chunk、必要事实没有 verified support，Runner 就在模型运行前
拒绝计分。Validation 用来诊断和选候选，Held-out 只能在 Promotion 后一次性打开；
失败 case 和拒答反例都保留在原分母中。

当前诚实边界：这些合同能证明 Gold 与冻结语料一致，并阻止标签泄漏；现有 receipt 没有
完整记录双人标注、仲裁人和 inter-annotator agreement，因此不能包装成“全部 Golden
Data 已由多人双盲审核”。若扩到生产数据，应补标注指南、双标/仲裁、困难与负例分层、
来源授权、PII 脱敏、版本/hash 和定期漂移复审。

实际例子：`qst_0474` 的 Gold 不是一整段“标准作文”，而是上面的 5 条原子事实；
`qst_0477` 再贡献 4 条收入事实，因此两个可回答 case 合计 9 条必要事实。Host-private
qrels 把它们绑定为 11 个可替代 support group、13 组精确 source/chunk/quote。另两题
`qst_0488`（A100/H100 safe-mode BIOS 默认值）和 `qst_0492`（microburst surcharge 与
GL account）在冻结语料中没有完整答案，所以 Gold 是 `abstentionExpected=true`；候选
必须明确说明资料不足，不能用相似文档猜答案。Agent Lab 中点击这些 case 时，应在内置
只读面板展示问题、必答事实/拒答预期、候选输出、Judge reason code 和 citation support
摘要；Host-private 原始 qrels 只显示 hash 与通过状态，不直接弹出文件夹或泄露隐藏标签。

**问：为什么不把 RAG、CloudOps、EnterpriseOps 的分数加成一个总分？**

答：它们的成功定义不同。RAG 的主指标是 Recall/MRR/nDCG，EnterpriseOps 的硬门禁是数据库 verifier 和 cleanup，Trace 的核心是 first-failing-span 与 Evidence F1。Agent Lab 统一的是数据契约、冻结控制、证据链和决策格式，不制造没有业务意义的总分。

**问：你们到底改了哪些中间变量？**

答：先把变量分成 Model、Prompt、Skill、Tool、Workflow、Context/Memory/RAG、Guardrail、Execution policy、Human loop 和 Pricing；再把数据、split、seed、Gold、evaluator、runtime、预算和价格日期冻结。这样每个 delta 才能回答“改了什么”，而不是只展示一个更好看的最终数字。

**问：为什么 1/8、54/65 不能写成接近成功？**

答：任务完成是 all-or-nothing，verifier 通过只能说明部分状态正确。Held-out 仍有 7 个任务失败、11 个 verifier 未通过和 2 次 Tool failure；因此候选被拒绝。我们展示它来证明评测器能阻止 Validation 过拟合，而不是掩盖失败。

**问：Trace Agent 能自己修复吗？**

答：它可以提出 candidate repair，但不能把自己的文字当作修复证据。只有用户授权、候选在新 Validation sandbox 中落地、Host verifier 产生新 Trace/Eval receipt，才算 verified；Promotion 仍需单独批准。

**问：Luna 成本对比完成了吗？**

答：EnterpriseOps 这一条已完成，结论是 Reject。当前同一源码、Runtime provenance、Prompt、Tool、Workflow、`thinking=max` 和三任务 Validation 下，Luna 的 API 成本估算由 `$3.243385` 降至 `$0.725239`（`-77.64%`），耗时降低 `16.45%`、Tool 减少 21 次；但 task 从 `3/3` 降到 `2/3`、verifier 从 `31/31` 降到 `30/31`。质量硬门禁先于成本，所以保留 Sol；这也不是 Provider 账单或 Held-out 结论。

**问：Luna 如果效果不如 Sol，为什么不直接改 Prompt？**

答：因为这轮要回答的是“只换模型会怎样”。看到 Luna 的质量回退后先 Reject，不能事后改 Prompt 来挽救同一单变量结论。只有新的 Trace/Eval 将失败归因到 Prompt 或 Context，才从新 revision 开独立候选；Tool/Runtime 缺陷修 Tool，Evaluator 分母或 Gold 缺陷先修评测合同。

**问：每次实验都完全冻结，怎么找到树形分支里的最优路径？**

答：冻结的是一次比较的控制向量，不是永远不改变。先把 Sol + state-contract 作为根节点；每个子节点只改变一个主变量，保留 parent revision、changed factors、冻结控制、run receipt 和 Keep/Reject。Host evaluator 先执行硬门禁，再比较质量，最后才比较 Tool、延迟和成本。硬门禁失败就剪枝；如果是 Evaluator 合同错误，就先修合同并从新 revision 分叉，不能继续在旧树上调参。

搜索不会穷举所有组合，而是按“失败归因 + 预期信息增益 + 运行成本”选择下一条分支。先用 Validation 做探索，使用 successive-halving/小预算筛掉明显失败的分支；对留下的候选做同协议重复观察和稳定性检查；只有 Pareto 前沿上的候选才进入 Promotion，Held-out 最后一次性运行。最终得到的是“在声明搜索空间和约束下的 best-known”，不是脱离任务的全局最优。

本次模型分支把这条规则真正跑通：只替换 Model，其他合同与 Runtime provenance 全部冻结；Luna 虽更快、更便宜，但只有 `2/3 task、30/31 verifier`，因此被剪枝，当前路径保留 `3/3、31/31` 的 Sol。若要继续优化，必须从这份 Reject receipt 新开归因明确的 Prompt/Context 或 Tool/Runtime 分支。

## STAR 版本

**S**：PAW 的多个 Agent 垂直实验曾分别记录结果，难以回答“到底改了 Prompt、Tool 还是工作流，以及改动是否真的有效”。

**T**：建立一个能服务 RAG、CloudOps、EnterpriseOps、Trace 和未来 Extension App 的统一评估面，同时保留每个垂直的真实验收语义。

**A**：实现 Agent Lab 实验合同与 append-only revision store；将可变因素和冻结控制显式化；把真实 Session、公开安全的任务输出、Verifier 逐项结果、Evidence hash、Room 优化入口和 STAR/简历边界放入同一页面；用 Host-private evaluator 负责最终 Keep/Reject。

**R**：EnterpriseOps 执行链在同一 Validation 分母下从 `3/31` 可执行 verifier 提升到 `26/31`，恢复 `47` 次业务 Tool 调用并完成 `3/3` cleanup；Suite v2 随后在 Held-out 以 `1/8、54/65` 被拒绝。RAG 检索 Validation 达到 Recall@10 `0.9554`、nDCG@10 `0.8872`；CloudOps 恢复为 `12/12` 可评分、`98/98` Tool 成功；Memory private-shadow v5 通过 `5/5` 整理、`4/4` durable recall 和 replay/rollback 门禁；匹配的 EnterpriseOps Luna 分支虽把 API 成本估算降低 `77.64%`、延迟降低 `16.45%`，但因 task/verifier 回退被质量门禁 Reject。

## 简历可用表述

> 设计并实现 PAW Agent Lab 评测闭环：将 Model/Prompt/Skill/Tool/Workflow/Memory-RAG 等实验变量与数据、split、Gold、Runtime、Evaluator 冻结控制显式化，接入真实 Session、Host-private Verifier、Trace/Evidence 和 Room 优化流程；在 EnterpriseOps 冻结 Validation 上将执行链可执行 Verifier 从 3/31 提升至 26/31、恢复 47 次业务 Tool 调用并完成临时数据库清理，同时通过一次性 Held-out 门禁拒绝仅在 Validation 上表现好的 state-contract 候选（1/8 task、54/65 verifier），保留可复现的失败证据。

允许说：`Validation`、`一次性 Held-out`、`Host-private verifier`、`可执行检查`、`Tool/cleanup receipt`、`diagnostic/open gap`。

禁止说：`生产 100%`、`Trace Agent 已自主修复`、`RAG 最终答案已提升`、`Luna Provider 账单降低 77.64%`、`Luna 已替换 Sol`、旧的 `-96.43%` 单变量结论、`Held-out 可反复调参`、`所有提升都来自某一个 Agent`。

## 来源与校验

- 实验总账：[`agent-experiments.v1.json`](agent-experiments.v1.json)
- Agent Lab 公开投影契约：[`rag_ime/contracts/json/agent-lab-experiment.v1.json`](../../rag_ime/contracts/json/agent-lab-experiment.v1.json)
- 评测页面：PAWOS `Agent Lab` App（读取 `agent.eval-lab.runs`，可打开真实 Session 或创建优化 Room）
- 导入：`python3 scripts/import_agent_lab_experiments.py --ledger eval/interview-metrics/agent-experiments.v1.json --target-db <PAW Runtime DB> --write`；导入是 append-only，旧 revision 会以“未记录变量”的只读投影继续可读。
- 校验：`python3 scripts/check_interview_agent_experiments.py --json`、`python3 -m unittest tests.test_import_agent_lab_experiments tests.test_agent_lab_experiment_store tests.test_eval_lab`
