# Room 工作流优化收益 · 2026-09-05

已完成一次同任务配对实验和一次冻结候选复验。在三个结构化检查全部正确的前提下，用程序校验合并代替重复的模型整合，将 Provider 调用从 **3 次降到 2 次**。复验完整 turn tokens 下降 **35.49%**，目录价估算成本下降 **24.70%**。这是 source Lab 中执行的窄工作流优化；2026-09-06 已将结果和图表接入已安装 PAWOS 的 Lab，查看路径见 [OS 结果](OS_RESULTS.md)。它尚未成为通用 Room 默认行为。

## 为什么改这一处

此前 [单 Session / Room 对照](FIVE_METRIC_RESULTS.md#m1--同任务同预算上限的-room-对照)没有测出协作收益。轨迹显示两个伙伴的结构化结果互不重叠，第三次模型请求只是重新整合这些结果。此次优化对象明确为 **workflow**：

```diff
 worker_a(cases[0:2])
 worker_b(cases[2:3])
-model_integrator(cases, partner_outputs)
+merge_disjoint(partner_outputs, output_schemas)
```

合并器校验 case 身份、完整性、字段和精确类型；拒绝重复、遗漏或错误结构，原样保留值。它不读取 Gold、不修补错误答案。两个伙伴继续通过真实 PAW Room dispatch / Pi Session 执行，模型和工具生命周期仍归 Pi 所有。

旧题目的字段类型有歧义。本次在配对实验之前向两侧统一提供 `typed-contract-v2`，固定同一模型、worker Prompt、输出 schema、评分器与每臂上限。**旧 2/3 与新 3/3 不构成质量提升对照**。新任务仍是三个合成契约检查：Room receipt 身份、执行完成与质量通过的区别、完整 turn 用量汇总；不是三个大型业务任务。

## 实测结果

| 指标 | 基线：模型整合 | 首次候选：程序合并 | 冻结候选复验 |
| --- | ---: | ---: | ---: |
| 严格检查通过 | 3/3 | 3/3，保留输出重评 | 3/3 |
| 完整组通过 | 1/1 | 1/1 | 1/1 |
| Provider 调用 | 3 | 2 | 2 |
| 完整 turn tokens | 9,911 | 6,391 | 6,394 |
| 每成功完整组估算成本 | $0.00203172 | $0.00124572 | $0.00152980 |
| 相对基线 token 降幅 | — | 35.52% | **35.49%** |
| 相对基线估算成本降幅 | — | 38.69% | **24.70%** |
| 完整阶段墙钟时间 | 24.084 秒 | 原始报告未保存 | 15.953 秒 |

复验复用保留的匹配基线，没有再支付一次基线，也没有更换候选。这是一个新 Room 中的候选确认，不能当作新的完整配对试验或未见题测试。三个 case 重复验收不能写成九个独立任务。

首次基线和候选各有 1,536 cache-read tokens；确认候选没有缓存命中。因此采用复验的 **24.70%** 写摘要，同时保留首次 **38.69%**。金额来自 Pi transcript 的目录价估算，包含中间 assistant 调用；不是 Provider 账单或固定生产降幅。墙钟时间本次下降 33.76%，但只有一条匹配基线，作为诊断信息，不作为稳定加速承诺。

## 自举过程、预算和投入

1. 主 Session 从旧轨迹定位重复整合，并实现一个受限候选 operator；候选实现与业务 Gold 分离。
2. 真实 source Lab 运行基线，由一次 Luna low 的 Pi 诊断读取基线轨迹，从 `deterministic_disjoint_merge` / `keep_baseline` 两项中选择前者。
3. 新 Room 执行原样 worker Prompt，程序合并并由原 Host verifier 判定质量。随后只追加两次模型调用确认已冻结的同一个候选。
4. 主 Session 对八个实际模型调用的 turn、完整 usage、模型和 transcript hash 复算；六个 worker 的输入正文匹配冻结 Prompt，分属六个 Session、三个 Room。

用户授权来自“优化完成。测出收益，才有故事”，控制延续“小任务、token 有限、Lab 自举”。发现、候选实现和最终核验由主 Session负责；PAW Lab Pi 负责从已实现的候选中选择；通过票由 Host verifier 给出。这不证明模型自动生成了任意 Workflow 修复代码。

首次实验上限为 6 Provider calls、20k 结算后观察阈值，每臂 3 calls / 12k，单次输出 768。六次实际调用共 **20,407 tokens**，在最后结算时超出阈值 **407**，没有第七次调用。原始 job 的预算失败状态完整保留；离线重评只恢复已返回答案的质量，不把这次实验改写成预算内完成。

复验预算单独冻结为 **2 calls / 10k observed tokens**，实际 **2 calls / 6,394 tokens**，`withinBudget=true`、`qualityVerdict=keep`、`optimizationVerdict=improved`。修复后的预算回归确保：最终结算超额仍可免费评分；存在下一步时禁止再发付费请求。修复没有更换本次候选算法、Gold 或冻结 worker 输入。

| 本轮 PAW Lab 支出 | 调用 | tokens | 目录价估算 |
| --- | ---: | ---: | ---: |
| 基线 | 3 | 9,911 | $0.00203172 |
| 诊断 | 1 | 4,105 | $0.00096800 |
| 首次候选，含超阈值结算 | 2 | 6,391 | $0.00124572 |
| 冻结候选确认 | 2 | 6,394 | $0.00152980 |
| **本轮合计** | **8** | **26,801** | **$0.00577524** |

以确认观察的每组节省 $0.00050192 计算，约 12 个同类成功组可覆盖上述八次调用的支出。这只是条件式算术，不包含开发人工、本对话 Codex 用量、此前费用候选和旧 Room 对照；完整工程回本时间未知。此前失败与无收益实验继续保存在各自账本，不从历史删除。

## 简历与追问材料

可用表述：

> 基于 PAW 自身的 Lab、Room 与 Pi 运行链路建立评测优化闭环，定位并移除结构化协作中的重复模型整合；在同模型、同输入的三个契约检查全部通过时，将模型调用由 3 次降至 2 次，复验 token 用量降低 35.5%、目录价估算成本降低 24.7%。

追问时解释：问题来自已观察轨迹；只改合并方式；两个伙伴输入不变；程序只验证结构而不答题；质量先通过才比较成本；首次预算超额和缓存差异都保留。本结论是 **Room 内部工作流的开销优化**，没有证明 Room 优于单 Agent、复杂任务普遍加速、生产长期效果或全自动代码自修复。

## 实现、回执与验收

- 实现：[合并器和两个 Lab adapter](../../rag_ime/agent_lab_room_merge.py)、[真实运行入口](../../scripts/run_paw_micro_eval.py)、[回归](../../tests/test_agent_lab_room_merge.py)。
- 初次运行：本机 `RagIme/EvaluationArtifacts/room-merge-gain-20260905/room-merge-job.json`；原始失败留存。`reconciled-room-merge.v1.json` 复核六条完整 transcript，新增模型调用为 0。
- 确认运行：`room-merge-confirm-20260905/room-merge-confirm-job.json`、`parent-usage-verification.json`、`parent-controls-verification.json`。后者检查实际 `config/auth.json` 已清理，并记录输入正文 hash 与三个 Room 的隔离证据。
- 每轮 `frozen.json` 记录运行时源文件 hash；预算回归修复发生在运行后，不回写旧 hash 冒充相同源码。任务 hash 为 `7137a8e49e7d629a8710085592ab849bafbf506140cf069a81193a88e48783e1`。
- 最终相关回归 **54/54**；项目 harness、import boundaries、语法与文档检查通过，详见 [工作记录](OPTIMIZATION_WORK.md)。`verified-gain.json` 汇总七份回执 hash、投入与归因。未提交、推送、安装或发布。
