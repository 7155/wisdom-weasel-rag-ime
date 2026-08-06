# RAG、Memory 与 Agent 面试评测

这里仅保存可公开复现的配置、数据集收据和命令说明。原始语料、个人输入、
模型权重、运行数据库、完整 trace 与分数报告全部留在 Git 忽略的
`.rag-ime-data/`，不得上传。

## 系统边界

- Memory 使用独立索引和 `memory` Tool，评测个人偏好、事实、时间变化、
  冲突更新、跨会话召回与拒答。
- Knowledge 使用独立知识库和 `knowledge` Tool，评测建库、导入、切块、
  embedding、检索、重排、图增强与引用。
- Knowledge 文档不能写入个人 Memory；Memory 评测内容不能导入企业知识库。
- 真实 `knowledge` 写操作的回执固定标记
  `memoryDomain=document_knowledge`、`personalMemoryEligible=false`；Memory
  入口还会按 Tool/domain 再拒绝一次。回执可作为项目审计来源，但不得生成个人
  Evidence、Atom、Book 或 Memory 检索文档。
- 当前中文 Knowledge 主线使用本地中文 embedding。英文 embedding 不在本轮
  参数矩阵或结论中。

## 固定数据和协议

- 中文 Knowledge：CRUD-RAG 固定 revision 与派生 qrels，详情见
  [public-dataset-receipt.v1.json](public-dataset-receipt.v1.json)。这些分数是
  产品检索诊断，不是 CRUD-RAG 官方排行榜分数。
- 企业 Knowledge：EnterpriseRAG-Bench 固定 revision；全量语料较大，开发
  slice 与最终全量结果必须分开标注。
- Personal Memory：[LongMemEval-S cleaned 收据](longmemeval-s-cleaned-receipt.v1.json)
  固定 500 例。`official-user` 只索引
  user turn 并使用 user-side `has_answer` qrels；`product-all-turn` 是单独的
  产品 profile，不能混报。
- Agent：SWE-bench Verified 固定 500 题，并冻结 50 题面试子集。只在本地运行，
  不提交 leaderboard。

## 三张独立成绩表

用以下命令从已 hash 校验的本地报告生成公开安全 scorecard。它分别输出
Knowledge、Memory、Agent 三个命名空间的 baseline、optimized、绝对变化和相对变化，
并保留冻结的 baseline/optimized 检索配置；绝不计算混合总分。Agent 报告缺失、失败或 development-only 时状态固定为
`pending_formal_run`/`ineligible_development_or_failure`，不会把旧回放填入正式成绩。

```bash
.venv/bin/python scripts/build_rag_interview_scorecard.py \
  --knowledge-report .rag-ime-data/results/rag-interview/crud-rag-qwen3-rerank-diverse-exact-heldout60-final-v1.json \
  --memory-report .rag-ime-data/results/rag-interview/longmemeval-memory-official-user-lexical-full-v2.json \
  --output eval/rag-interview/scorecard.v1.json
```

当前 scorecard 已记录 Knowledge/Memory 的正式 held-out 变化；Memory 另列
`temporalReasoning` 与 `updateOrConflict` 分片，避免时效/更新冲突被总分掩盖；Agent
等待同条件 Luna/Metal 可用后的四档正式回放。

逐项验收状态、正式/开发证据边界和当前环境阻塞见本地审计矩阵：
`docs/agent/audits/2026-08-05-rag-acceptance-matrix.md`。

## 中文切块消融

候选配置在 [chunk-profiles-zh.v1.json](chunk-profiles-zh.v1.json)。所有候选
共享相同 seed、case slice、文档和 embedding。候选阶段只生成 validation
指标；只有 validation 的唯一赢家允许再运行一次 held-out。

```bash
PAW_MODEL_DIR="/absolute/path/to/bge-base-zh-v1.5-mlx-q8"
PAW_KNOWLEDGE_PYTHON="/absolute/path/to/knowledge-runtime/python"

"$PAW_KNOWLEDGE_PYTHON" scripts/run_rag_chunking_ablation.py \
  --prepared .rag-ime-data/prepared/rag-interview/crud-rag.prepared.json \
  --profiles-json eval/rag-interview/chunk-profiles-zh.v1.json \
  --baseline-profile-id general-1200-160 \
  --output .rag-ime-data/results/rag-interview/chunking-ablation.json \
  --work-root .rag-ime-data/runs/chunking-ablation \
  --max-cases-per-split 60 \
  --distractor-limit 1000 \
  --embedding-provider mlx-bert \
  --embedding-model "$PAW_MODEL_DIR" \
  --embedding-dimensions 768 \
  --embedding-query-prefix "为这个句子生成表示以用于检索相关文章：" \
  --embedding-bits 8 \
  --embedding-group-size 32 \
  --dense-backend usearch
```

验收报告必须同时满足：每个候选 held-out 被抑制、validation split 相同、
corpus 相同、held-out 复现冻结的 chunk profile 和 retrieval config。报告必须
包含基线、优化值、绝对提升、相对提升、延迟和资源成本。

## Luna 四档 Agent 对比

四档固定为：无 Skill、仅 Skill、Skill 加离线调参、Skill 加调参加 Agentic
多轮检索。模型、thinking、case IDs、权限、索引 generation 和重试策略必须相同。
当前第 4 档固定为父 Agent 两阶段检索：先逐题用原问题做一次 top-10 reranked
search，再把第一轮的有界证据包交给唯一一个无 Tool 的 `reviewer` 子 Agent 做槽位
覆盖审查；父 Agent 随后逐题用 reviewer 给出的不同 query 再做一次 top-10 search，
最后自行合成。safety case 只检索一次。reviewer 只能指出遗漏、冲突、必须保留的
citationRef 和补检索 query，不能检索、代答或覆盖父级直接证据。
报告必须同时证明 reviewer 完成且没有 Tool 调用、run binding、每个真实 case 恰好
两次父级检索、第一轮 query 原样、第二轮 query 非空且不同、父子 lineage、参数合同、
Memory 隔离、取消和清理。reviewer 超时或自行检索都拒绝整批。
单批固定为四题；最终分母通过多个互斥批次聚合，避免把大量题塞进一个上下文。

```bash
python3 scripts/run_rag_agent_ablation.py \
  --prepared .rag-ime-data/prepared/rag-interview/crud-rag.prepared.json \
  --retrieval-report .rag-ime-data/results/rag-interview/frozen-retrieval.json \
  --output .rag-ime-data/results/rag-interview/luna-four-lane.json \
  --private-root .rag-ime-data/runs/luna-four-lane \
  --slice-seed paw-chunking-ablation-v1 \
  --slice-cases-per-split 60 \
  --agent-case-limit 4 \
  --distractor-limit 1000 \
  --development-report .rag-ime-data/results/rag-interview/prior-agent-batch.json \
  --reranker-model .rag-ime-data/models/Qwen3-Reranker-0.6B-4bit \
  --reranker-revision 5f324548f1d20c2b5a450f126fc6ef2fb1126524 \
  --reranker-cache .rag-ime-data/cache/rag-interview/qwen3-reranker-v1.json \
  --timeout-seconds 720
```

`slice-seed` 是冻结语料身份的一部分；省略或更换它会在模型调用前触发 corpus hash
拒绝。新批次必须把所有已观察过的报告作为 `--development-report`，包括失败、
校准和旧合同运行；不能重跑同题后只保留最好一次。只排除“成功报告”会让旧失败题
重新进入 held-out，形成隐蔽泄漏。至少两个 `passed=true`、每批固定四题且 case ID
互斥的批次再用 `scripts/aggregate_rag_agent_ablation.py` 聚合。

在已观察 case 上验证新 Prompt/委派合同必须显式传 `--development-only`。它仍运行
真实 Luna、语义索引和 reranker，但强制 `passed=false`、
`formalAcceptanceEligible=false`，因此只能用于调试，不能进入正式聚合。

v11 两阶段合同的首个四题回放已观察到 reviewer 完成、父级两轮检索完成，但驱动在
最终合成前被外部终止，未生成报告；随后的一题 no-Metal 校准因 MLX 无 Metal 且
Luna 在 Tool 前瞬态失败而拒绝。两者都不计分。恢复 Luna/Metal 后必须用同一命令、同一
已观察 case 重跑，先拿到完整 `turn_completed`、reviewer 无 Tool、两轮父检索和 judge
报告，才能消耗新的 held-out。

正式 runner 现在会在加载 MLX reranker 前用独立子进程执行一次真实 Metal
运算；`is_available()` 但设备不可用会生成完整的 `preflight` 失败收据，
不创建 benchmark sandbox，也不会误写成零分。当前 v20d 收据明确记录
`formalAcceptanceEligible=false`、`scoreEligible=false`、cleanup 通过和
`metal::load_device` 原始诊断。

### Agent 自主建库与验证集盲调优

`rag_benchmark` 是仅由本地评测 harness 临时绑定的 Tool，不进入生产 Tool
catalog。它现在覆盖 `create_run`、`create_base`、`import_documents`、
`configure_base`、`rebuild_preview`、`rebuild`、`graph_rebuild`、`search`、
`evaluate_validation`、`status` 和 `cleanup`。其中 `evaluate_validation` 只能运行
harness 预注册的 validation suite，并只向 Agent 返回聚合 Recall@K、MRR、nDCG、
suite/hash 收据；qrels、逐题结果和 held-out 标签均不进入 Tool 返回。
指标只报告真实检索深度内的 cutoff，并始终包含请求的 TopK；例如 TopK=2 只会
报告 K=1、2，不会把两个候选误写成 Recall@10。

```bash
.venv/bin/python scripts/canary_rag_benchmark_agent.py \
  --output .rag-ime-data/results/rag-interview/luna-lifecycle-validation-current-v6.json \
  --private-root .rag-ime-data/runs/rag-interview/luna-lifecycle-validation-current-v6 \
  --timeout-seconds 180
```

该 canary 要求 Luna Max 在重建前后各调用一次同一 validation suite，随后检索、
记录状态并清理。v2 曾在任何 Tool 调用前以 `fetch failed` 终止；v4 的受限诊断
进一步证明 Pi 扩展没有继承 wrapper 对 `globalThis.fetch` 的 spool patch，两个
`create_run` 调用均未进入 Python ledger。当前实现优先使用带随机 capability token
的 `127.0.0.1` loopback transport，只有 bind 被拒时才退回私有 spool。

v6 已通过真实 Luna Max 生命周期：模型为 `openai-codex/gpt-5.6-luna`、
`thinking=max`，依次成功调用 11 个建库、导入、验证、配置、预览重建、重建、
检索、状态和清理操作；重建前后两次 validation 均只返回聚合指标，qrels、逐题
结果和 held-out 标签都不可见。两题的 Recall@1/2、MRR 和 nDCG@1/2 均为 1.0，
最终回答引用 `policy-001`，Agent 与 harness 双重清理均通过，且没有调用 Memory。
这是一份两题生命周期 canary，只证明自主闭环，不作为总体质量 headline。报告内
SHA-256 为
`4e2af68028c8604afe9b545d4cfa834d63e428f123b6f67c578a5fd8e853bebe`，
文件 SHA-256 为
`acda8438aa425cc2e4f592bf31e2cd41b910adc0eb01e838a78518ddeb94c973`。

## Personal Memory 全量检索

LongMemEval-S cleaned 的公开复现实验使用独立 Memory 索引和
`official-user` profile：只索引 user turn，拒答题不进入位置召回分母，
Knowledge 表、Knowledge 文档和 Knowledge Tool 均不得参与。候选只看
validation；唯一赢家冻结后才允许打开一次 held-out。

```bash
.venv/bin/python scripts/run_longmemeval_memory_retrieval.py \
  --prepared .rag-ime-data/prepared/rag-interview/longmemeval-s-cleaned.prepared.json \
  --sandbox-root .rag-ime-data/runs/memory-retrieval \
  --output .rag-ime-data/results/rag-interview/longmemeval-memory-official-user-lexical-full-v2.json \
  --seed paw-longmemeval-retrieval-v1 \
  --max-cases-per-split 0 \
  --evaluation-profile official-user \
  --embedding-provider none \
  --skip-vectors
```

当前冻结赢家是 session 与 turn 两路 lexical 检索加权 RRF，权重 `3:1`，
`rrfK=60`，候选倍数 `2`。它在 86 个 validation 检索题上相对 session-only
基线把 MRR `0.881824 -> 0.890338`、Recall@1
`0.503876 -> 0.515504`、Recall@10 `0.942829 -> 0.948643`、nDCG@10
`0.869375 -> 0.878442`。

82 个 held-out 检索题只打开一次：MRR `0.836619 -> 0.837805`
（绝对 `+0.001186`，相对 `+0.14%`），Recall@1
`0.433740 -> 0.447967`（绝对 `+0.014228`，相对 `+3.28%`），Recall@10
保持 `0.928455`，nDCG@10 `0.836329 -> 0.837465`（相对 `+0.14%`）；
Recall@3 和 Recall@5 分别相对下降 `3.17%`、`1.03%`。拒答也未达验收：
held-out precision `0.033333`、recall `0.166667`、F1 `0.055556`。

因此这份报告是“多粒度检索能力和泛化失败诊断”，不是面试 headline。
报告内 SHA-256 为
`534f9a956e6be96d001c671beeaeeb64be31a10bb936d0192e58f65d9766dd13`；
完整报告、会话文本和运行库仍只保存在忽略目录，不上传。

Memory 的整理与检索是两张独立成绩表。现有真实 Luna Max 私有影子验收已
证明 Evidence→Atom→Book、独立 verifier、三个 durable personal case 的
rank-1 召回、两个 project/transient control 的拒写，以及 apply→rollback→
content-addressed replay；公开安全摘要见
`docs/agent/audits/personal-memory-luna-rag-evaluation-20260802-verified-clean.md`。
另一份 74 条真实历史表达实验得到 72 条 `not_for_memory`、2 条
`needs_review`、0 个 Atom，并由独立 verifier 通过；这证明 fail-closed，不能
被解释成“整理器没工作”。当前源上的 personal curation、Luna shadow、Owner
curation 和 governed Memory Tool 共 75 项聚焦测试通过。时间冲突、纠正和遗忘
已有权威写入门与回滚测试，但仍需补同一版本 Luna 的公开安全顺序生命周期
报告后才能作为新的模型效果 headline。

当前顺序生命周期 harness 已复用权威 `OwnerMemoryCurator` 并新增显式 Luna
lane。`calibration` 在临时 SQLite 中测试 6 个 current claim 的一次更新、1 个
显式 forget、1 个不得覆盖长期偏好的临时冲突、3 条语义噪声和 12 条确定性噪声；
`stress` 测全部 18 个 claim，其中 9 个再更新一次，再加相同 forget/冲突门、
18 条语义噪声和 90 条确定性噪声。
报告检查每个 claim 恰有一个 current 版本、历史深度、supersession edge、forget
后的 retracted Atom/active tombstone/Book 清理、来源 disposition、Book 不引用旧
Atom，并把临时库、生产库未触碰、Luna 身份和质量设为硬门槛。

```bash
.venv/bin/python scripts/eval_owner_memory_model_updates.py \
  --organizer luna \
  --profile calibration \
  --timeout-seconds 1200 \
  --artifact-root .rag-ime-data/runs/rag-interview/luna-memory-update-calibration/artifacts \
  --report .rag-ime-data/results/rag-interview/luna-memory-update-calibration.json \
  --summary-only
```

该 lane 固定 `openai-codex/gpt-5.6-luna`、`thinking=max` 和
`codex_cli_ephemeral`，不读取 Provider 环境文件。评测包装器必须继续暴露
`atom-first-v1` 和模型运行生命周期；夹具使用 user-scoped canonical Evidence，
project-scoped 输入仍按产品边界被隔离。Provider 未完成时报告固定为
`modelExecution=false`、`scoreEligible=false`，所有零计数都禁止进入效果表。

当前受管执行环境在 nested `codex exec` 初始化 in-process app-server 时返回
`Operation not permitted`；独立最小探针复现同一错误。当前只验收了 8 项 evaluator
聚焦测试、13 项 evaluator/owner-flow 联合测试，以及包含 Owner Curator 和
Organizer 的 74 项回归。完整失败日志以 mode 0600 留在上方忽略目录；当前没有新
的 live Luna 分数。换到允许 Codex app-server 的普通本机终端后先跑 calibration，
通过再跑 stress，失败批次与成功批次都保留。

## SWE-bench Verified Agent harness

本地已固定官方 500 题数据和一个按 repository/difficulty 分层抽样的 50 题面试
子集。源 Parquet 为 `2,090,470` bytes，SHA-256
`43ed5a3d1d98da36472c1ade65ddd2085d7b4ff694fcaf6a023a07c5c1f32f21`；
50 题 split SHA-256 为
`7138621727051ac6a789e38300ec042b507011a30fc5632329938951a933902b`。
Agent case 只有 issue、公开 hints、repo、base commit 和难度；gold patch、test patch、
FAIL_TO_PASS/PASS_TO_PASS 均不进入模型 prompt。

PAW harness 从受信任 repo mirror 的 base commit 用 `git archive` 导出无 `.git`
工作区，禁止修改任何 test path，Shell 只允许无网络、非变更的测试/检查命令；私有
Git index 在 Agent 结束后独立捕获 patch。这样同时防止未来提交泄漏和覆盖隐藏测试
刷分。生成 patch 只算 inference gate，通过官方 Docker verifier 才能写
`officiallyResolved=true` 或 resolved rate。

```bash
.venv/bin/python scripts/run_swe_bench_agent_eval.py preflight \
  --output .rag-ime-data/results/swe-bench-agent/preflight.json

.venv/bin/python scripts/run_swe_bench_agent_eval.py run \
  --instance-id psf__requests-1724 \
  --source-repository .rag-ime-data/public-benchmarks/swe-bench-repos/psf/requests.git \
  --subagent-budget 1

.venv/bin/python scripts/run_swe_bench_agent_eval.py verifier-command \
  --predictions .rag-ime-data/results/swe-bench-agent/psf__requests-1724.predictions.jsonl \
  --instance-id psf__requests-1724 \
  --run-id paw-interview-v1
```

正式 verifier 使用 `princeton-nlp/SWE-bench_Verified`、`split=test`、显式
instance IDs、`clean=True` 和 per-instance report；聚合同时报告总分母与 submitted
分母，不能用只提交成功样本的 resolved rate 代替全切片得分。

当前 preflight 已通过数据、Luna 私有配置、managed Pi `0.80.7`、Tool 清单和
120 GiB 可用磁盘门槛，但 Docker CLI 没有可连接 daemon；当前 shell 还受失效的
Git 全局代理与受管 DNS 限制，repo mirror 未下载。因此现在只有 10/10 harness
合同测试，没有 Agent patch 或官方 resolved 分数。不得把 `inferencePassed` 写成
SWE-bench 成绩。忽略目录内 preflight 报告 SHA-256 为
`25c37858215d1d89e7e2765ad702222ce16add6358e93d46b56f8d2d9874ea05`。

## 正式 Luna 运行环境门槛

冻结配置启用本地语义 reranker 时，正式四档运行同时要求：

- 当前进程可访问 Apple Metal；
- managed Pi 子进程可访问 Provider HTTPS；
- Runtime snapshot、Tool 参数、embedding/reranker 指纹、权限、lineage、
  预算和清理门槛全部通过。

`--calibration-no-metal` 只用于验证非语义控制流，永远不能满足正式 reranker
门槛。v12 因 `No Metal device available` 在报告前停止；v13 的无 Metal
calibration 又因子进程 HTTPS 被取消而使所有 lane 在 Tool 前失败。两者都不是
零分 RAG 结果，也不能放入四档效果表。

完整踩坑、失败证据和解释保存在
`docs/agent/audits/2026-08-04-rag-memory-agentic-eval-plan.md`。这里不复制私有
报告，也不把 canary、mock 或派生 qrels 写成正式排行榜结论。
