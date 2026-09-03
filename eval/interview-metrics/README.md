# PAW 面试指标与证据账本

## User Requirement Ledger

这份目录只负责“指标、运行和表述边界”，不替代 PAWOS 的需求权威、Runtime
事件、Git 状态或安装/前台验收。PAWOS 原需求仍由
`control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md` 维护。

| ID | 用户原话 | 本目录的解释 | 状态 |
| --- | --- | --- | --- |
| IM-001 | “整理本项目的面试能写的指标，没有就去网上找和构建测试。设置为goal” | 盘点已有指标，验证证据；缺口先找权威公开口径，再补最小可复现测试。 | 已建立 Goal 与账本 |
| IM-002 | “当前已经有很多指标了” | 先复用已有 scorecard、receipt、canary 和 benchmark，不重复造数。 | 已盘点 |
| IM-003 | “做了都要记录的” | 绿、红、被中断、环境差异和不可宣传结果都写入 `runs`，不只保留最好结果。 | 已落实为校验规则 |
| IM-004 | “还有完成记忆的全部整理，找找rag数据集之类的” | Memory 按写入治理、维护、投影、召回、注入、反馈、Trace、Eval 和前台分层；Knowledge 独立；公开数据集分级。 | 见 `MEMORY_AND_RAG_EVAL.md` |
| IM-005 | “trace得做通，因为后续我开发垂直类的agent的应用需要tarce基础，所以现在就得打好地基，例如开发sgg文件夹的示例，掌柜问数之类的。还有rag，记忆这些的检测。还有我之后是准备agent能自己开发垂直应用，自己评测检查trace，准备沙盒之类的，就像rag的agent自己测试和自己构建。” | 指标账本必须能被统一 Trace/Eval、垂直 Agent 沙盒、自测与自评复用；确定性事实和 AI Judge 分开。 | 当前 Trace 修复闭环已有 121 项聚焦回归；安装态与前台证据仍单列 |
| IM-006 | “你可以辅助他” | 本轮可辅助另一条 Room/Trace Session，但避免共享文件写冲突；这里新增独立评测目录和校验器。 | 已隔离实施 |
| IM-007 | “我们要面向面试来eavl，来做指标” | 从简历 Headline 和面试追问倒推指标；每个数字必须回答业务问题、选型收益、失败与证据边界。 | 已加入 Agent Experiment 硬合同 |
| IM-008 | “还要展示我们eavel agent 和traceagent 对系统和提示词，工具，流程 skill的提示，前后优化的效果” | 对 System Prompt、Tool、Workflow、Skill 四层分别记录发现、建议、授权、实施、复验、同题输出和指标 delta。 | 已设为必填字段 |
| IM-009 | “不够的指标就补充……我们完全可以作为各种agetn的试验场” | PAW 作为各垂直 Agent 的共同实验场；缺指标时增加冻结 Validation case 和 scorer，再搜索候选配置，不用单条演示代替评测。 | 已设为实验入口要求 |
| IM-010 | “结果可以往好的写……春秋笔法，star法则” | 简历第一屏选最强且有证据的正向结果，按 STAR 压缩；失败和限制留在深挖页，禁止改分母、泄露 Gold 或伪造结果。 | 已写入 narrativePolicy |
| IM-011 | “一次并行一批，但每个候选只改变一个层……质量评测可以自动执行，但每次候选实际运行前要有用户确认。尤其是修改 Prompt、Skill、Tool，要确保模型能往正确的改才能不白跑” | 每批候选并行提出，但每个候选绑定一个改动层、失败原因、目标指标、保护门禁和验证方式；用户确认后才运行，未通过候选保留为拒绝/回退，不能删除。 | 当前控制要求 |
| IM-012 | “达到目标即停止” | 每个场景达到主指标、保护门禁和已声明效率/成本目标后，由 Facilitator 收口，不为穷举分支继续消耗调用。 | 当前停止规则 |
| IM-013 | “room这个沙盒这个特殊，行星traceagent直接全新上下文输入trace提示词和技能就行” | Agent Lab 的沙盒 Room 为每个 Trace Reviewer 建立全新上下文，只注入受限 Trace/Eval evidence envelope、Trace Prompt 和 Trace Skill，不继承普通 Agent 对话。 | 当前上下文边界 |
| IM-014 | “你应该把room弄过来，单独的，因为这个是单独app，对话也不要划分到agent项目，这个是app的对话” | Agent Lab 使用 App-owned Room/Session；评测对话按 App owner 隔离，不进入普通 Agent 项目列表、项目记忆或项目上下文。 | 当前产品边界 |
| IM-015 | “每个场景有自己的主指标和保护门禁Reviewer相当于traceagent，这里是不是也要多个啊，并行检查agent trace” | 每个垂直场景独立定义主指标与保护门禁；一批候选完成后由多个受限 Trace Reviewer 并行检查不同证据维度，Host Verifier 仍拥有最终 pass/fail 权限，Facilitator 汇总分歧。 | 当前评测流程 |

## 结论

目前最适合面试陈述的不是“指标很多”，而是下面六条带限定条件的事实：

1. 在冻结的 60 题中文 Knowledge held-out 诊断切片上，混合检索加重排把
   MRR 从 `0.250` 提到 `0.922`，Recall@10 从 `0.244` 提到 `0.989`。
2. 两次有原始收据的复跑中，在结果 checksum 一致的 1k/5k 合成工作区中，
   `rg` 后端相对 Python 扫描取得 `2.20–3.01x` / `4.10–7.19x` 的 p95
   加速；范围同时保留较慢与较快观察，不挑最好一次。
3. 2026-08-16 的安装开发版 Room 自举验收包含 3 个参与者、2 个受委派
   Partner、19 个 Tool step、1/1 任务、唯一 final 和刷新恢复。
4. 16 个 Memory optimizer case 重复三轮共 48 次全部通过并保存 48 条
   Trace；本机端到端 p95 `37 ms`。这里必须说“16 个独立 case”，不能把重复轮次
   说成 48 个独立样本。
5. 隔离的 Pi 稳定前缀 canary 中，两次热轮都从 Provider cache 读取 `9,728`
   token，未缓存输入相对冷轮减少 `90.96%–91.16%`；改变前缀的对照组缓存命中为
   `0`。这不是账单或所有真实任务的节省率。
6. Trace 修复链路的当前源码回归为后端 `41/41`、前端 `80/80`：诊断报告经用户
   确认后交给普通可写 Agent，最后由新 Trace 权威复检；`121` 是测试数，不是
   修复的 bug 数。

2026-09-01 的 CloudOps 垂直 Validation 进一步跑通了真实 PAW Agent 路径：冻结的
12 个故障定位 case 被拆成 3 个顺序批次、每批 4 题，由 GPT-5.6 Sol Session
通过受限 `cloudops_benchmark` Tool 自主索引、读取并提交答案。最终 12/12 作答，
98/98 Tool 调用成功，CA 为 `1.00`，FA/JRA/Top3JRA 均为 `0.8333`，并产生
Trace、Eval、Sandbox 与 Artifact 标识。前三次失败试跑均保留：它们依次暴露网络
受限传输、模型路由漂移和结构化 observation hash 合同不一致。该结果来自
source-local 实验版 Runtime，故意只在隔离环境验证，不直接应用到当前 PAWOS，
以免失败候选污染用户正在使用的系统。Provider token 尚未进入聚合投影，因此不能说
生产验收、当前系统已恢复、Held-out 泛化或“零 Token 成本”。

随后在同一冻结 Validation 上保留了 v1–v4 四轮候选。v1 暴露搜索 Schema 与隐藏
12-term 实现限制不一致；v2 修复搜索合同后又暴露全零 usage 被误判为可用；v3 用
两阶段诊断、调用预算和重复调用拒绝把 Tool 数从 `189` 降到 `82`，但出现一次长
`cacheKey` 转录失败；v4 只把公开地址换成 case-scoped `observationId`，实现
`94/94` Tool 成功，却让 CA/JRA/Top3JRA 降到 `0.50/0.4167/0.50`。因此短 ID
只作为 Tool 合同修复保留，业务工作流候选严格 Reject，baseline 继续是 incumbent，
且不再用同一 Validation 继续跑 v5。

掌柜问数现在也有独立的 Extension App candidate 测评入口：它先校验
App/Package/Skill 的绑定与摘要，再解析已注册的 `sgg/fixture-v2`，在新临时工作区运行
离线自测并产出相互关联的 SandboxRun、Trace 和 ground-truth Eval。当前只覆盖 1 个
fixture，precision/recall/F1 均为 `1.0`、Provider 调用 `0`、生产写入被阻断；这证明
自举源码与沙盒合同能跑通，不代表真实 Text-to-SQL、真实业务数据、安装态或前台验收。

2026-08-31 另新增一条 **validation-only 诊断数据**：在冻结的 16 个
Enterprise RAG 检索问题上比较 14 个候选后，选出的混合检索加重排配置相对词法
floor 将 nDCG@10 从 `0.6128` 提到 `0.8872`、MRR 从 `0.6042` 提到
`0.8672`、Recall@10 从 `0.6719` 提到 `0.9554`。held-out 尚未打开，因此这条
数据不进入上面的正式 headline，也不能称为已 Keep 或生产提升。

同一套企业语料上的 `Graph + Tag → shortlist` 目前不能和 Qwen3 reranker 做公平
A/B：2026-09-01 的只读 readiness 审计确认，5,101 篇文档与 29,846 个 chunk
对应的 Knowledge graph node、edge、extraction 均为 `0`，语料也没有可连接
`document_id + chunk_id` 的受治理 Tag。PAW 现有 Tag 图属于 Personal Memory，输出
的是 `memory_item_id` 分数；直接拿关键词造 Tag 会换掉被测系统。因此这项结果记为
`blocked_missing_enterprise_graph`，而不是编一个比 reranker 更快或更准的数字。

2026-09-01 的冻结 answer-only Validation 又验证了恢复与淘汰链：人为硬中断
后，Runner 收口了 `1/1` 个私有 orphan Session/Knowledge sandbox，并在恢复跑中
复用 `1/4` 条 Agent lane（`25%` lane 复用，不是端到端提速）。同一 4 题切片上，
Agentic lane 相对 baseline 的延迟从 `71.1s` 增到 `242.6s`（`+241.05%`）、
Tool 调用从 `6` 增到 `11`（`+83.33%`），AI Judge 正确率从 `0.5` 降到 `0`，
因此生成了严格 `Reject` 回执，未创建 held-out gate。

随后 v16 把旧的 token-overlap “证据可用”判定换成 host-private 的逐事实
source/chunk/quote 合同：先离线验证两道 high-level 题的 `9/9` 个必要事实都确有
来源，再把 `11` 个 support group、`13` 个精确绑定留在 host 侧，既不进入 Agent
Prompt，也不进入 Judge Prompt。新合同下，baseline、Skill、tuned 的逐事实引用覆盖
都只有 `2/9 = 0.2222`，可回答问题的 citation support 均为 `0`；Agentic 又在
`600.6s`、`13` 次 Tool call 后未完成终态。因此 v16 仍是四 lane 全部 `Reject`，
而且不能把一般回答成功率或“引用存在”冒充“引用支持了答案”。

同日还记录了一次 Trace Agent 的 **bootstrap 边界**：安装态 Pi 在 Provider
请求阶段因不支持的 `max_output_tokens` 字段失败，Trace Agent 尚未调用 Skill 或
Tool 就终止，因此不可能“自己修好自己”。外层 supervisor 用同 OAuth、同模型、
同基础 payload 做 HTTP/WS A/B，定位 Pi wire contract 后构建未安装 candidate；
相同两个失败 Session 在 candidate 中由 Trace Agent 完成 `skill_load + inspect`，
独立给出 `unsupported-max-output-tokens` finding。这里能说的是“诊断链恢复并生成
未应用候选修复”，不能说安装态已修复或 Trace Agent 已完成自安装。

随后对 CloudOps v3 的四条 Trace 做 source-local 复诊时，又暴露了第二层问题：
前两次 Agent 都完成 `skill_load + inspect`，却因结构化报告合同漂移被拒绝，其中一次
可确定为把 `confidence` 输出成数字。第三次只有在提示词显式复述 schema 时才成功，
不算 Skill 已经可靠。为此给 `trace-agent-diagnostics` 增加 exact-envelope 自检并以
测试锁定；新建的 dirty-source derived candidate 只在隔离实验环境复验，普通提示词下的新只读 Session
成功生成合法报告，并在 `sourceAvailable=false`、timeline 为空、usage 未投影时保留
`unknown`、不编造 finding。这里验证的是 **Skill 输出合同修复**，不是 Runtime 已安装、
CloudOps 已有完整可观测性，或 Trace Agent 可以绕过授权改写自己。

按“一个独立根因 + 保留的失败/拒绝证据 + 修复 + 验证边界”去重后，当前可审计
清单共有 **11 个闭环合同缺陷**：3 个有主仓 Validation/控制面证据，8 个只在隔离的
source-local 实验版上复验；另有 5 个 source/test-only 修复不计入这 11 个。
同一清单还记录了 3 个 Skill 问题（2 个结构修复、1 个仅诊断）、6 项流程改进和
9 项 Tool/Runtime 合同改进。四组分类有重叠，不能相加，也不能表述为“Trace Agent
自主发现并修复了全部 11 个问题”。

EnterpriseOps CSM 又提供了一条独立的垂直执行链证据。最初 plumbing run 因
Thinking 绑定、spool transport 和 `read_only` 权限语义错误，没有进入真实业务
Tool，仅得到 0/3 任务、3/31 verifier。修复这些问题，并补上 MCP `isError`、清理、
gold redaction、terminal gate、oracle Tool 标识、toolCallId 幂等和 split 隔离后，
最终 baseline 达到 1/3 任务、26/31 verifier、47 次业务 Tool、0 次 Tool failure，
3/3 临时数据库完成删除。`9.68% → 83.87%` 只能称执行/评测链修复，不能称业务
workflow 提升。这一步之后另起 suite-v2 合同：state-contract 在同一组 3 条
Validation 上由 2/3 task、28/31 verifier 推进到 3/3、31/31，并把 Tool 从 72
降到 64；代价是耗时从 529.35 秒升到 758.44 秒。该 Validation winner 只消费过
一次冻结 Held-out，结果仅 1/8 task、54/65 verifier，Promotion 被拒绝且未重跑。
详细修复项见 [`ENTERPRISEOPS_CSM_TRACE_REPAIR_20260901.md`](ENTERPRISEOPS_CSM_TRACE_REPAIR_20260901.md)。

完整数值、命令、来源和限制在
[`evidence-ledger.v1.json`](evidence-ledger.v1.json)。账本是当前唯一的机器可读
指标入口。

## 可直接使用的面试表述

### 中文简历版

- 设计并落地中文 Knowledge 混合检索与重排，在冻结的 60 题 held-out
  诊断集上将 MRR 从 0.250 提升到 0.922、Recall@10 从 0.244 提升到 0.989；
  同时固定语料、split、配置和报告 hash，防止调参污染 held-out。
- 将 Agent 工作区字面搜索从 Python 文件扫描迁移到受治理的 `rg` 后端；两次
  checksum 等价复跑中，1k/5k 合成语料的 p95 加速范围分别为
  2.20–3.01x / 4.10–7.19x，并用收据重算校验阻止手抄指标漂移。
- 构建可恢复的多 Agent Room 开发版闭环；一次安装态自举验收中，3 个参与者、
  2 个受委派 Partner 完成 19 个 Tool step 与 1/1 任务，输出唯一 final，并在
  浏览器刷新后恢复任务与时间线投影。
- 为 Personal Memory 建立 admission、Evidence/Atom/Book、投影、混合召回、
  反回声、墓碑、反馈、治理审批/回滚与 Trace；16 个确定性 case 重复三轮
  48/48 通过，端到端 p95 37 ms。
- 为 Pi Agent 验证稳定前缀缓存：隔离 canary 的两次热轮各命中 9,728 个
  Provider cache token，未缓存输入由 10,647 降至 941/963（减少
  90.96%–91.16%），且改变前缀的对照组命中为 0。
- 建立 Trace“诊断报告 → 用户确认 → 普通可写 Agent 修复 → 新 Trace 权威复检”
  闭环；当前聚焦回归后端 41/41、前端 80/80，并明确测试数不冒充 bug 数。
- 用 4 组同 OAuth、模型和基础请求的 HTTP/WebSocket A/B 将一次 Trace 启动失败
  定位到 Pi Codex wire field；隔离修复候选让同一只读诊断从 0 次 Tool 调用推进到
  `skill_load + trace_diagnostics.inspect` 和完整报告，候选安装态仍单独验收。
- 建立 Trace/Eval 缺陷去重账本，以“失败证据 + 修复 + 复验边界”为计数门槛，
  审计出 11 个闭环合同缺陷、3 个 Skill 问题、6 项流程改进与 9 项 Tool/Runtime
  合同改进；分类重叠不相加，并区分主仓 Validation 与隔离实验版证据。
- 为 CloudOps 故障定位构建受限 Tool 与 host-only scorer；在冻结的 12 题
  Validation 上用 3 个 Sol Session 完成 3x4 工作流，12/12 作答、98/98 Tool 调用
  成功，CA `1.00`、FA/JRA/Top3JRA `0.8333`，并保留三次失败 Trace 作为 OS 合同
  修复证据；实验版 Tool/Runtime 只在 source-local 沙盒运行、未影响当前 PAWOS 安装态；
  Sol baseline 缺 Provider usage，因此不计算该场景的模型成本下降。
- 对同一 CloudOps Validation 保留四轮 falsification：修复搜索 Schema、usage
  投影与长 Tool ID 三个合同缺陷，将 observationId 路径做到 `94/94` Tool 成功；
  因 CA/JRA 退化到 `0.50/0.4167` 主动 Reject，保留 baseline 并停止继续调参。
- 为 EnterpriseOps CSM 构建 source-local Pi、89-Tool MCP Gateway、临时数据库与
  31 条 Host-private SQL verifier；Trace 驱动修复 11 个 Runner/Tool/评测合同问题，
  将可执行 verifier 从 3/31 恢复到 26/31、业务 Tool 从 0 恢复到 47 次并完成
  3/3 数据库清理；suite-v2 state-contract 在 Validation 达到 3/3、31/31，但
  一次性 Held-out 仅 1/8、54/65，系统拒绝 Promotion 并保留完整失败回执。
- 为 EnterpriseOps 建立受质量约束的单变量模型成本门禁：receipt checker 锁定相同
  task manifest、Prompt、Skill、Tool catalog、Workflow、runner、Runtime provenance、
  `thinking=max` 与价格来源后，Luna Max 将 API 成本估算从 `$3.243385` 降到
  `$0.725239`（`-77.64%`）、耗时降低 `16.45%`，但 task `3/3→2/3`、Verifier
  `31/31→30/31`；系统因此 Reject 低价候选并保留 Sol，旧的 `-96.43%` 结论因
  thinking/source provenance 不匹配撤回。

### 面试展开时应主动补充

- CRUD-RAG 的 qrels 是项目派生口径，不是官方排行榜；当前 checkout 缺忽略目录下
  的两个源报告，所以这是一条带 hash 的冻结历史结果，不是今天重新跑出的分数。
- Room 数字来自 2026-08-16 的单次安装开发版运行，不代表长时间稳定、当前工作树
  或签名发行版。
- Memory 37 ms 来自本地确定性 case gate，不是 LongMemEval 泛化质量，也不是
  macOS 前台首屏延迟。
- 检索优化必须同时说绝对值和相对值，不能只写“提升 304%”。
- Prompt cache 的 `90.96%–91.16%` 是两次热轮“未缓存输入 token”降幅，不是
  账单节省、总 token 节省或所有真实 Session 的平均值。
- Trace 的 `41 + 80` 是聚焦回归测试，不是 121 个线上故障，也不替代安装态和
  前台真实修复验收；当前还没有同一 Replay Case 的 before/after Ground Truth
  Verification Receipt，因此不能计算“Trace 修复率”或效果 delta。
- Trace Provider bootstrap 的 4-case A/B 与 `0 → 2` Tool 调用来自隔离候选 Runtime；
  在正式安装并用新 Trace/Eval 复检前，不能说当前安装态已修好。
- Enterprise RAG v16 的 `2/9` 是逐事实引用覆盖，不是检索 Recall；它说明检索
  winner 仍未被可靠地转化成最终带证据答案。v16 与旧 token-overlap 合同不能直接
  计算前后提升，Agentic 失败后的 `0 token` 也只是缺失 usage，不是零成本。

## 禁止当正向 headline 的数字

| 项目 | 真实结果 | 为什么不能包装 |
| --- | --- | --- |
| LongMemEval-S 82 题 | MRR `0.8366 → 0.8378`；Recall@3/5 回退；拒答 F1 `0.0556` | 改进太小且关键 slice 退化，只能作为已发现问题的诊断基线 |
| MiniMind 语义基线 | 后端 p50/p95 `117/251 ms`，但人工 Top-1/Top-3 都是 `0` | 返回三个候选和低延迟不等于候选有效 |
| Memory cache 临时探针 | 热缓存约 `0.02 ms`，但 projection backlog `941`、retrieval docs `0` | 走的是不新鲜的合成/legacy 路径，不能声称生产 Memory 亚毫秒召回 |
| Agent 四档消融 | `pending_formal_run` | 没有正式 Luna 四档报告，不能拿旧回放或失败报告补分 |
| Enterprise RAG validation | nDCG@10 `0.6128 → 0.8872`、MRR `0.6042 → 0.8672`、Recall@10 `0.6719 → 0.9554` | 仅 16 个 validation query；held-out 未运行，不能称泛化、正式 Keep 或生产提升 |
| Enterprise RAG Agent Validation | baseline → agentic：延迟 `71.1s → 242.6s`、Tool `6 → 11`、Judge 正确率 `0.5 → 0`；恢复复用 `1/4` lane | 4 个 answer case，结论是 `Reject`；25% 仅指 lane 复用，索引仍重建，held-out 未运行 |
| Enterprise RAG exact citation v16 | 9/9 事实有 host 证据；baseline/Skill/tuned 仅覆盖 2/9 引用事实，四 lane citation support 均为 0 | 新证据合同下的 4 题 Validation Reject；不能与旧 token-overlap 分数算提升，held-out 未运行 |
| Graph+Tag reranker readiness | 企业投影为 `0` node、`0` edge、`0` extraction，Memory Tag 身份不能直接对应 Knowledge chunk | 这是正确阻断伪 A/B 的 readiness 审计，不是 Graph+Tag 与 Qwen3 的性能比较 |
| CloudOps Agent Validation | 12/12 作答、CA `1.00`、FA/JRA/Top3JRA `0.8333`、98/98 Tool 调用成功 | 隔离实验版的 Validation，未应用到当前系统；Provider token 与 process signals 不可用，不能称生产验收、Held-out 或零成本 |
| 掌柜问数 App candidate | 1 个离线 fixture，precision/recall/F1 `1.0`，Provider `0`，Trace/Eval/Sandbox 已关联 | 仅源码绑定与确定性沙盒合同；不能称真实 Text-to-SQL 100%、真实数据、安装或前台验收 |
| 产品发行 | 当前安装开发版与公开发行是两条证据；`releaseStatus` 仍为 `blocked` | 单测、build 或安装开发版都不等于签名、公证、干净机或完整前台验收 |

## 证据等级

| 等级 | 含义 | 不能替代 |
| --- | --- | --- |
| E1 | 当前 revision 有 owner/契约 | 测试、Runtime |
| E2 | 指定测试或 benchmark 在限定环境通过 | build、安装、前台 |
| E3 | 指定 build/package 通过 | 安装、Runtime、前台 |
| E4 | 指定 artifact 经产品路径安装 | Runtime 行为、前台体验 |
| E5 | 安装/当前 Runtime 产生权威事件或状态 | 真实用户可见前台验收 |
| E6 | 真实前台交互满足验收 | 签名、公证和公开发行仍需单列 |

等级描述范围而不是自动升级阶梯。一个 E5 历史 Room run 不会自动证明今天的 E1
源码；一个 E2 benchmark 也不会自动证明 E4–E6。

## 复现与校验

先校验账本本身：

```bash
python3 scripts/check_interview_metrics.py
python3 -m unittest tests/test_interview_metrics.py
```

本轮新鲜的三个 Memory/RAG gate：

```bash
RAG_IME_MEMORY_OPTIMIZER_EVAL_REPEAT=3 \
  scripts/run_memory_optimizer_algorithm_gate.sh

scripts/run_hybrid_rag_gate.sh

RAG_IME_ACTIVE_RAG_EVAL_REPEAT=3 \
  scripts/run_active_rag_gate.sh
```

工作区搜索 benchmark：

```bash
python3 scripts/benchmark_workspace_tools.py \
  --files 1000 --repeat 7 --warmup 2

python3 scripts/benchmark_workspace_tools.py \
  --files 5000 --repeat 5 --warmup 1
```

Pi 稳定前缀缓存 canary（隔离运行，不改前台 Session）：

```bash
payload=$(jq -r '.version' \
  "$HOME/Library/Application Support/RagIme/PiRuntime/current.json")
python3 scripts/canary_pi_context_cache.py \
  --payload "$HOME/Library/Application Support/RagIme/PiRuntime/$payload" \
  --workspace-root . \
  --provider openai-codex \
  --model gpt-5.6-luna \
  --thinking-level off \
  --source-agent-config \
    "$HOME/Library/Application Support/RagIme/Agent/config" \
  --evidence-output \
    eval/interview-metrics/runs/pi-context-cache-20260830.v1.json
```

Trace 修复链路的聚焦回归：

```bash
python3 -m unittest \
  tests.test_trace_diagnostics \
  tests.test_trace_diagnostic_http \
  tests.test_agent_configuration \
  tests.test_agent_routes

cd control-center-web
pnpm exec vitest run \
  src/features/trace-agent/trace-agent-feature.test.tsx \
  src/features/trace-agent/failure-reasons.test.tsx \
  src/features/roles/roles-feature.test.tsx \
  src/platform/routes.test.ts \
  --maxWorkers=1 --testTimeout=60000
```

历史 Knowledge/Memory scorecard 的生成命令已经记录，但当前 checkout 缺少
`.rag-ime-data/results/rag-interview/` 下的两个私有源报告；在找回 hash 对应输入前，
不要覆盖现有 scorecard，也不要写“已重新复现”。

## 记录规则

本轮 Agent Lab 的变量矩阵、冻结控制、六张垂直实验卡与一张成本门禁卡、STAR 讲法和简历边界见
[`AGENT_LAB_INTERVIEW_DATA_20260901.md`](AGENT_LAB_INTERVIEW_DATA_20260901.md)。
页面与文档使用同一份 `agent-experiments.v1.json` 总账；文档中标为 `OPEN-GAP` 的项目
不能在面试中写成已完成结果。

### 垂直 Agent 实验的必填合同

所有准备进入简历、项目展示或 Eval Lab 的垂直 Agent 实验，必须先登记到
[`agent-experiments.v1.json`](agent-experiments.v1.json)。PAW 把自己作为 RAG、
CloudOps、EnterpriseOps、掌柜问数和后续 Extension Agent 的共同实验场，而不是为
每个 Demo 另写一套无法比较的漂亮数字。

一张实验卡必须同时保留：

- 真实业务问题以及为什么普通对话或单次脚本不够；
- 冻结 Dataset、split、case 数、manifest hash 和 Held-out 是否已消费；
- Baseline 与 Candidate 的真实输入、输出、指标和 Evidence；
- Eval Agent / Trace Agent 的 observation、hypothesis、evidence 与 candidate change；
- `System Prompt / Tool / Workflow / Skill` 四层逐项判决；
- `detectedBy / proposedBy / authorizedBy / implementedBy / verifiedBy` 五段归因；
- 同题前后 metric delta、输出差异以及 Keep / Reject / Rollback；
- STAR 四段、简历 Headline、允许说法、禁止说法和 `OPEN-GAP`。

`Headline` 采用春秋笔法：第一句选择最强、最相关、证据闭合的正向结果；失败版本
进入技术迭代和面试深挖，不抢第一屏。但原始分母、Reject、限制和不利结果必须保留
在证据页。不得通过删除难题、泄露 Gold、改变分母或把 Validation 改称 Held-out 来
制造好结果。

总账校验会级联校验实验账本；缺少上述字段的实验不能进入可陈述区：

```bash
python3 scripts/check_interview_metrics.py --json
python3 scripts/check_interview_agent_experiments.py --json
```

后续每一次 Trace/Eval 或 benchmark 运行至少追加这些字段：

- `run id`、日期、源码 revision、工作树是否 dirty；
- dataset id/revision、split/hash、唯一 case 数和重复 observation 数；
- model/provider/prompt/config/evaluator 版本；
- OS、架构、Python/Node 版本与关键可选依赖；
- 命令、退出状态、耗时、原始结果的私有位置或安全 hash；
- 确定性值与 `ai_estimate` 分栏；
- E1–E6 等级、允许说法、禁止说法、缺失证据与 blocker；
- 失败、中断、超时、环境降级和 ResourceWarning，不得只保留最好一次。

`scripts/check_interview_metrics.py` 会阻止缺样本、缺命令、缺证据、缺表述边界或把
AI 估计冒充确定性指标的条目进入可陈述区。对工作区搜索和 Prompt cache，它还会
直接读取原始 JSON 收据重算区间、token 和 checksum parity；手抄数字漂移会令检查
失败。

## 与统一 Trace/Eval 的交接

另一条 Trace/Eval 平台线可以直接消费本账本的字段，但不应复制 transcript 或创建
第二事实源。建议每个 Eval 结果绑定：

对共享工作树中新契约骨架的只读审计、已覆盖能力与 P0/P1 缺口见
[`TRACE_EVAL_COMPATIBILITY.md`](TRACE_EVAL_COMPATIBILITY.md)。

```text
traceRunId + evalRunId + capability/domain
+ sourceRevision + runtime/install identity
+ dataset/revision/split/caseId
+ config/prompt/model/evaluator hashes
+ deterministic metrics
+ separately labeled AI estimates
+ E1-E6 level + evidence refs + claim boundary
```

Memory 至少需要覆盖 `capture admitted/rejected`、`maintenance preview/review/apply/
rollback`、`projection freshness`、`retrieval`、`context injection`、`feedback`、
`forget/tombstone` 和 `eval result`。Room 只投影真实 Session/Tool 事件，指标系统不从
UI 文案反推运行状态。
