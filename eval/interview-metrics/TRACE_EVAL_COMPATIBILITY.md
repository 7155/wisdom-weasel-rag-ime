# Trace/Eval 与指标账本兼容性审计

## 审计范围

这是对共享工作树中另一条并发实现线的只读快照，不接管其 owner，也不把未提交源码
说成安装态平台。审计文件：

- `rag_ime/contracts/json/trace-envelope.v1.json`
- `rag_ime/contracts/json/eval-run.v1.json`
- `rag_ime/contracts/json/sandbox-run.v1.json`
- `rag_ime/trace_runtime.py`
- `rag_ime/trace_adapters.py`
- `rag_ime/vertical_agent_harness.py`
- `examples/vertical_agents/{sgg,zhanggui-wenshu}.json`

2026-08-28 运行：

```bash
python3 -m unittest \
  tests/test_trace_runtime.py \
  tests/test_trace_adapters.py \
  tests/test_vertical_agent_harness.py
```

结果为 `10/10` 通过，属于 E2 源码测试证据。

## 当前已经打好的地基

- 一个 `TraceEnvelope` 可承载 Session/Room/vertical app 的 span、evidence、artifact
  与 run binding。
- 输入默认只留完整 SHA-256；适配器测试证明原始“掌柜问数”输入不进入 envelope。
- 真正记录的 duration 必须等于 `end-start`；缺测和不一致时保留 `null + reason`，
  不伪造为 0。
- `EvalRun` 在构造时分开 `ground_truth` 与 `ai_judge_estimate`，AI Judge 不能写入
  precision/recall/F1。
- `SandboxRun` 明确 `productionWriteBlocked=true`，并把 Trace/Eval run 关联起来。
- `sgg` 与“掌柜问数”使用同一 vertical harness，RAG 和 Memory 证据缺一即失败。

这些可以表述为“公共契约骨架与确定性 fixture gate 已存在”，不能表述为“统一 Trace
平台已完成”“垂直 Agent 已能自行开发应用”或“周期 Eval 已运行”。

## 与指标账本的字段映射

| 指标账本字段 | 当前契约 | 判定 |
| --- | --- | --- |
| `run id` / `trace ids` | `evalRunId` / `traceIds` | 已覆盖 |
| Ground Truth / AI estimate | `mode` + `metricAuthority` | 已强制分离 |
| dataset id / label revision | `truth.datasetId` / `labelRevision` | 部分覆盖 |
| source revision / dirty state | 无 | P0 缺口 |
| install/runtime identity | 无 | P0 缺口 |
| dataset revision/split/hash | 只有自由文本 `labelRevision` | P0 缺口 |
| unique cases / observations / attempts | 无 | P0 缺口 |
| metric cutoff/unit/denominator/slice | flat numeric `metrics` | P0 缺口 |
| prompt/config/model/evaluator hash | evaluator 有名字，无 revision/hash | P0 缺口 |
| environment/dependency profile | 无 | P0 缺口 |
| failure/timeout/cancel/skip taxonomy | Eval 只有 `failed`，无结构化原因 | P0 缺口 |
| E1–E6 / allowed / forbidden / missing evidence | 无 | P0 缺口 |
| input raw-data policy | Trace `contentPolicy` | 已覆盖输入；span/evidence/artifact 还需扩展 |

## P0：接真实 Eval 前必须补

1. 为 Eval 增加稳定的 provenance：`sourceRevision`、dirty 标记、Runtime/安装 identity、
   capability/domain、dataset revision/split/hash、case set hash。
2. 分开 `uniqueCaseCount`、`observationCount`、attempt/retry。16 个 case 重复三轮不能
   自动变成 48 个样本。
3. 将 flat `metrics` 扩成带 `metricId/value/unit/authority/cutoff/denominator/slice`
   的记录。当前 `recallAtK` 无法说明 K，也表达不了 task success、exact match、
   latency、cost、leak rate、projection backlog/freshness 等系统指标。
4. Ground Truth evaluator 记录 evaluator implementation/revision/hash；AI Judge 另记
   provider/model revision、thinking、rubric/prompt hash、temperature/seed 和重试。
5. Eval 失败收据需要 stage、error kind、timeout/cancel/blocked/skipped、partial counts、
   cleanup 和 residual artifacts；不能只有一个 `status=failed`。
6. 绑定 E1–E6、证据 refs、允许说法、禁止说法和 missing evidence，防止 source test
   被前端误投影成 Runtime/前台验收。

## P1：平台化前应补

- Trace envelope 增 producer/schema revision、sequence/causal link，以及 Session、Room、
  Tool、Browser、Memory、Knowledge、Input 的稳定查询键；不要长期依赖自由 attributes。
- `evidence.sourceRef`、span attributes 和 artifact 也要有 content policy。当前 adapter
  会过滤敏感 key，但其他 producer 仍可把原文放进自由对象。
- sandbox `workspaceRoot` 需要可移植的 workspace binding 或 fingerprint，避免把机器绝对
  路径当公开证据；同时记录 allowlist、资源限制、清理和 rollback 收据。
- `sgg`/“掌柜问数” manifest 明确是公开 canary，truth 中直接包含 required evidence ID；
  它们不能当 formal held-out。正式 Eval 的 labels/qrels 必须只在 evaluator 侧可见。
- 补持久化、查询、手动触发、周期调度、取消、保留策略和 UI 投影；当前模块注释也明确
  尚不负责 persistence/model/runtime。

## 最小集成验收

在宣布统一地基可复用前，至少做两条真实垂直切片：

1. 把 `scripts/run_memory_optimizer_algorithm_gate.sh` 的一次 run 投影为公共 Trace +
   Eval，保留 16 unique/48 observations、p95、阻断原因和 48 条 trace 的真实分母。
2. 把 CRUD-RAG 或 MIRACL-zh 的 Knowledge run 投影为公共 Trace + Eval，绑定 revision、
   split/qrels hash、检索 config 与 source report hash；缺源报告时必须返回 blocked，不能
   用 tracked scorecard 伪造 fresh run。

两条都要通过以下负向检查：AI Judge 无法提交确定性 metric；缺 dataset revision、
case set、source revision、失败原因或证据等级时无法进入“可面试陈述”投影。
