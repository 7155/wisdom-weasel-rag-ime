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
| IM-005 | “trace得做通，因为后续我开发垂直类的agent的应用需要tarce基础，所以现在就得打好地基，例如开发sgg文件夹的示例，掌柜问数之类的。还有rag，记忆这些的检测。还有我之后是准备agent能自己开发垂直应用，自己评测检查trace，准备沙盒之类的，就像rag的agent自己测试和自己构建。” | 指标账本必须能被统一 Trace/Eval、垂直 Agent 沙盒、自测与自评复用；确定性事实和 AI Judge 分开。 | 已给出交接契约，平台实现仍属另一条工作线 |
| IM-006 | “你可以辅助他” | 本轮可辅助另一条 Room/Trace Session，但避免共享文件写冲突；这里新增独立评测目录和校验器。 | 已隔离实施 |

## 结论

目前最适合面试陈述的不是“指标很多”，而是下面四条带限定条件的事实：

1. 在冻结的 60 题中文 Knowledge held-out 诊断切片上，混合检索加重排把
   MRR 从 `0.250` 提到 `0.922`，Recall@10 从 `0.244` 提到 `0.989`。
2. 在结果 checksum 一致的 1k/5k 合成工作区中，`rg` 后端相对 Python
   扫描取得 `2.14x`/`4.40x` 的 p95 加速。
3. 2026-08-16 的安装开发版 Room 自举验收包含 3 个参与者、2 个受委派
   Partner、19 个 Tool step、1/1 任务、唯一 final 和刷新恢复。
4. 16 个 Memory optimizer case 重复三轮共 48 次全部通过并保存 48 条
   Trace；本机端到端 p95 `37 ms`。这里必须说“16 个独立 case”，不能把重复轮次
   说成 48 个独立样本。

完整数值、命令、来源和限制在
[`evidence-ledger.v1.json`](evidence-ledger.v1.json)。账本是当前唯一的机器可读
指标入口。

## 可直接使用的面试表述

### 中文简历版

- 设计并落地中文 Knowledge 混合检索与重排，在冻结的 60 题 held-out
  诊断集上将 MRR 从 0.250 提升到 0.922、Recall@10 从 0.244 提升到 0.989；
  同时固定语料、split、配置和报告 hash，防止调参污染 held-out。
- 将 Agent 工作区字面搜索从 Python 文件扫描迁移到受治理的 `rg` 后端；在
  checksum 等价的 1k/5k 合成语料上，p95 分别加速 2.14x/4.40x。
- 构建可恢复的多 Agent Room 开发版闭环；一次安装态自举验收中，3 个参与者、
  2 个受委派 Partner 完成 19 个 Tool step 与 1/1 任务，输出唯一 final，并在
  浏览器刷新后恢复任务与时间线投影。
- 为 Personal Memory 建立 admission、Evidence/Atom/Book、投影、混合召回、
  反回声、墓碑、反馈、治理审批/回滚与 Trace；16 个确定性 case 重复三轮
  48/48 通过，端到端 p95 37 ms。

### 面试展开时应主动补充

- CRUD-RAG 的 qrels 是项目派生口径，不是官方排行榜；当前 checkout 缺忽略目录下
  的两个源报告，所以这是一条带 hash 的冻结历史结果，不是今天重新跑出的分数。
- Room 数字来自 2026-08-16 的单次安装开发版运行，不代表长时间稳定、当前工作树
  或签名发行版。
- Memory 37 ms 来自本地确定性 case gate，不是 LongMemEval 泛化质量，也不是
  macOS 前台首屏延迟。
- 检索优化必须同时说绝对值和相对值，不能只写“提升 304%”。

## 禁止当正向 headline 的数字

| 项目 | 真实结果 | 为什么不能包装 |
| --- | --- | --- |
| LongMemEval-S 82 题 | MRR `0.8366 → 0.8378`；Recall@3/5 回退；拒答 F1 `0.0556` | 改进太小且关键 slice 退化，只能作为已发现问题的诊断基线 |
| MiniMind 语义基线 | 后端 p50/p95 `117/251 ms`，但人工 Top-1/Top-3 都是 `0` | 返回三个候选和低延迟不等于候选有效 |
| Memory cache 临时探针 | 热缓存约 `0.02 ms`，但 projection backlog `941`、retrieval docs `0` | 走的是不新鲜的合成/legacy 路径，不能声称生产 Memory 亚毫秒召回 |
| Agent 四档消融 | `pending_formal_run` | 没有正式 Luna 四档报告，不能拿旧回放或失败报告补分 |
| 产品发行 | `backend_only`、`releaseStatus=blocked` | 单测、build、历史安装态 canary 都不等于签名、公证、干净机或完整前台验收 |

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

历史 Knowledge/Memory scorecard 的生成命令已经记录，但当前 checkout 缺少
`.rag-ime-data/results/rag-interview/` 下的两个私有源报告；在找回 hash 对应输入前，
不要覆盖现有 scorecard，也不要写“已重新复现”。

## 记录规则

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
AI 估计冒充确定性指标的条目进入可陈述区。

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
