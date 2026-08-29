# Memory 全链路与 RAG 数据集路线

## 边界先于指标

PAW 的 Personal Memory 与 Knowledge 是两个数据域：

- Memory 保存经治理的用户事实、偏好、任务/项目上下文及其 Evidence、Atom、Book、
  时间和冲突谱系；默认按用户、Agent、项目和 Room owner 控制可见/可写范围。
- Knowledge 保存导入文档、chunk、embedding、图与引用；`knowledge` 写回执固定标记
  `memoryDomain=document_knowledge`、`personalMemoryEligible=false`。
- Session recall 是有界上下文注入，不等于把 compaction summary 自动写成长记忆。
- 输入法候选是 Memory/Knowledge 的消费投影，不是任一数据域的权威存储。

任何总分都不得把 Memory、Knowledge、Session recall、Tool、Browser 或输入候选混在
一起。跨域只允许用同一 Trace envelope 关联，不能共用 qrels 或检索索引。

## 当前 Memory 全链路

| 阶段 | 当前 owner / 契约 | 本轮证据 | 下一项真实指标 |
| --- | --- | --- | --- |
| 采集与 admission | `agent_memory_evidence.py`、`memory_evidence_policy.py`、`memory_ingest.py`、`agent-memory-evidence.v1.json` | E1；相关 Memory 测试纳入 484-case 矩阵 | admission precision/recall；敏感/无价值/Knowledge 输入的拒绝率 |
| 人工写入治理 | `agent_governed_memory_tools.py`、`memory-governance-preview.v1.json` | `remember/correct/forget` 均先 preview，再 apply，可 rollback | preview→approve→apply 成功率；越权拒绝率；rollback 恢复一致性 |
| 周期维护 | `owner_memory_curation.py`、`memory_compiler.py`、`memory_model_executor.py`、`memory_cleanup.py` | 16 个 optimizer case 与大量 owner-curation tests | 每轮输入/输出、冲突、重复、过期、误删、成本、耗时和 model failure 分栏 |
| 权威语义层 | canonical Evidence、Atom、Book 与 claim lineage；迁移 `0130`–`0140` | 当前有 23 个 Memory 命名 append-only migration | Evidence→Atom→Book 可追溯率；无来源 Atom 数；冲突闭环率 |
| 投影 | `memory_projection.py`、`memory_projection_consistency.py`、`retrieval_docs.py` | 有 freshness/checkpoint owner；本轮 ad-hoc probe 暴露 backlog=941 | backlog、lag p50/p95、freshness SLO、重建前后 hash/数量一致性 |
| 召回 | `hybrid_rag_retriever.py`、`memory_optimizer.py`、`memory_tag_graph.py` | 4-case hybrid gate 12/12，p95 8 ms；LongMemEval 有冻结基线 | LongMemEval Recall/MRR/nDCG、abstention、temporal/update/conflict slice、冷/热延迟 |
| Session 注入 | `agent_memory_context.py`、`session_recall_policy.py`、`generation_memory.py` | 6-case 0.8/0.2 微评测 | 真实 compaction 前后 task success、错误旧主题、跨 scope、token overhead |
| 输入候选投影 | `memory_projectors.py`、`rag_core_v3.py`、`suggestion_compiler.py` | optimizer case 含 anti-echo/tombstone；前台选择仍缺 | TTFC、曝光率、选择率、KSR、误触、删除/应用切换一致性 |
| 反馈与治理动作 | `memory_actions.py`、`local_sqlite_core.py` | fixture 中 feedback、suppress、tombstone 路径通过 | 接受后提升、拒绝后抑制、墓碑零复活、revision/cache 失效一致性 |
| 可解释与图读取 | `memory_graph_read.py`、`management_service.py`、Memory `trace/explain` | 10 个 reference test 通过；HTTP 图用例受沙盒阻塞 | 引用完整率、分页稳定性、越权节点/边为零、Trace→source 可回放率 |
| Eval 与恢复 | `memory_eval.py`、`personal_memory_luna_evaluation.py`、`memory_rebuild.py`、`memory_pipeline_diagnostics.py` | 确定性 gate、LongMemEval receipt、失败运行均入账 | 真实 shadow rebuild、故障注入、周期 Eval、数据漂移与恢复时间 |

当前源代码清单为 56 个 Memory 命名 Python owner、64 个 Memory 命名测试文件、
12 个 JSON contract、23 个 append-only migration。这只能说明实现面广，不能据此
宣布“Memory 全部完成”。

## Memory 的当前成绩与硬缺口

### 已能证明

- 16 个 optimizer 独立 case × 3 轮，48/48 通过、48 条 Trace，端到端 p95 37 ms。
- 4 个多路召回/安全独立 case × 3 轮，12/12 通过，p95 8 ms；fixture 中原句、
  旧输入、墓碑和重复候选泄漏率均为 0。
- 6-case Session recall 微评测选择 0.8 query + 0.2 summary 后，有用命中
  `4 → 6`、compaction recovery `0 → 2`、无关注入 `2 → 0`。
- 本轮拆分发现 484 个 Memory 命名 unittest：482 通过，2 个 loopback HTTP 用例
  因沙盒 403 未验；它们没有被涂成绿色。

### 当前不能证明

- LongMemEval 的优化显著有效：MRR 只提升约 0.14%，Recall@3/5 还回退。
- 拒答可靠：冻结切片的 abstention F1 只有 0.0556。
- Memory 检索是亚毫秒：临时 cache probe 的 projection 不新鲜，不能使用。
- 周期维护在真实用户数据上安全：缺 held-out admission/maintenance gold labels。
- 安装版或前台输入法完成 Memory 选择、反馈、删除、应用切换与长期 soak。

## 下一轮 Memory Eval 的最小闭环

1. 固定一个无私密数据的 synthetic lifecycle suite，覆盖 capture、correct、forget、
   maintenance、projection、retrieve、inject、feedback 和 rollback；每步写真实 Trace。
2. 为 projection 建立可复现 benchmark：先等待 `fresh=true`、`backlog=0`，再同时记录
   文档数、向量数、checkpoint、冷/热 p50/p95 和结果 checksum。
3. 用 LongMemEval validation 只调 retrieval 与 abstention；冻结 winner 后一次性跑
   held-out，并分别报告 temporal、knowledge-update/conflict 和 abstention。
4. 追加 LongMemEval-V2，验证长生命周期 Agent 的准确率—延迟前沿；不要与
   LongMemEval-S 混成一个分数。
5. 为维护 Agent 建 capture/merge/supersede/delete 的人工小金标；AI Judge 只评价
   解释质量和有用性，不能覆盖来源、越权、删除和状态一致性等确定性事实。
6. 最后做 E4–E6：安装、Runtime 事件、前台可见候选与真实选择/反馈；分别留收据。

## RAG / Agent 数据集分级

| 优先级 | 数据集 | 领域与用途 | 本地状态 | 接入边界 |
| --- | --- | --- | --- | --- |
| A-current | CRUD-RAG-derived | 中文 Knowledge；单/多文档检索与生成 | 2394-case receipt、60-case scorecard 已有；源报告缺失 | qrels 为项目派生，不能称官方榜分；先恢复 hash 输入 |
| A-current | LongMemEval-S cleaned | Personal Memory；多会话、时间、更新、拒答 | 500-case manifest、82-case scorecard 已有；源报告缺失 | `official-user` 与 `product-all-turn` 必须分报 |
| A-next | MIRACL-zh | 中文检索；提供独立公开 relevance judgments | 未导入 | 先 pin revision；dev qrels 只给 evaluator，不给 Agent |
| A-next | LongMemEval-V2 | 长生命周期 Agent Memory；准确率—延迟 | 未导入 | 单独建表，不与 V1/S cleaned 混报 |
| B-next | MultiHop-RAG | 多跳检索、supporting evidence coverage | 未导入 | 先有单跳基线，再定位 planning/retrieval/synthesis 失败 |
| B-later | EnterpriseRAG-Bench | 企业文档、metadata、答案完整性和无效额外信息 | 未导入，语料大 | 开发 slice 和全量分开；记录建库时间、存储、延迟、成本 |
| C-secondary | LoCoMo | 长对话 QA/摘要的补充检查 | 未导入 | 语料规模小；Judge 分数显式标记 `ai_estimate` |
| A-next | BFCL V4 | Tool/function calling、多轮状态、Agentic search | 未导入 | 只适配可在 PAW sandbox 确定性复现的 tool 状态 |
| A-next | ToolSandbox | 有状态对话 Tool use 与 before/after state | 未导入 | 映射到统一 Tool Trace，状态 diff 为 ground truth |
| A-vertical | Spider 2.0 | “掌柜问数”类企业 Text-to-SQL | 未导入 | 先本地 sandbox 与 execution accuracy，再加 AI 解释评分 |
| B-later | WebArena | Browser Agent 端到端任务 | 未导入 | 等 PAW 的一个共享可见 Browser guest 和 lifecycle 稳定后再接 |

权威入口和本地接入状态同时保存在
[`evidence-ledger.v1.json`](evidence-ledger.v1.json) 的 `datasets` 数组。首次接入任何
数据集都要记录 revision、license、下载 hash、split、qrels 可见性、去重策略、
语料是否可提交和清理/回滚方式。

## 统一 Trace/Eval 的 Memory 事件建议

下面是给垂直 Agent、自建 RAG 与 Memory 自测复用的最小事件族，不要求 Trace 平台
照抄命名，但字段语义必须保留：

| 事件族 | 必须有的确定性字段 | 可选 AI 估计 |
| --- | --- | --- |
| `memory.capture` | source ref/hash、owner/scope、purpose、admitted/rejected、reason | 是否值得长期记忆 |
| `memory.maintenance` | run/revision、input ids、proposal、review、apply/rollback、状态 diff | 合并/改写质量 |
| `memory.projection` | source revision、checkpoint、backlog、doc/vector counts、freshness | 无 |
| `memory.retrieve` | query hash、config/index generation、candidate ids/scores、latency/cache | 语义相关性 |
| `memory.inject` | Session/turn、selected ids、token bytes、scope filter、drop reason | 对任务帮助度 |
| `memory.feedback` | candidate/source、accept/reject/edit、revision/cache invalidation | 用户意图推断 |
| `memory.forget` | preview、approval、tombstone/supersede、依赖失效、rollback | 删除解释质量 |
| `memory.eval` | dataset/revision/split/case、ground truth、metric、failure taxonomy | Judge rubric 分数 |

AI 评分必须存 `judgeModel`、prompt/rubric hash、温度/seed、重试与失败，并使用
`ai_estimate` 字段；召回、泄漏、状态 diff、越权、删除、延迟和成本保持确定性。
