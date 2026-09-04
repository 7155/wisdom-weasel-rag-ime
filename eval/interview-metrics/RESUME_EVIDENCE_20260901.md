# PAW 简历证据稿（更新至 2026-09-03）

## 推荐写法

### 项目标题

**PAW：可自举、可追溯、可回放的本地 Agent Runtime 与垂直工作流实验平台**

### 六条核心项目经历

- 构建面向企业 Knowledge 的混合检索与冻结评测链，在 5,101 篇文档、29,846 个 chunk、16 条 Validation query 上比较 14 组配置；Hybrid Retrieval + Qwen3 Reranker 相对 lexical floor 将 nDCG@10 从 0.6128 提升至 0.8872（相对 +44.78%），MRR 从 0.6042 提升至 0.8672（+43.53%），Recall@10 从 0.6719 提升至 0.9554（+42.19%）。
- 设计 Trace“真实失败 → full-trust 诊断与候选修复 → 同 Case 重放 → 新 Trace/Eval 复检”闭环；可选独立 repair Agent 只作责任隔离、不增加第二次用户审批。既有缺陷账本按独立根因去重：11 个缺陷具备失败证据、修复与复验边界，另记录 3 个 Skill 问题（2 个结构修复）、6 项流程改进和 9 项 Tool/Runtime 合同改进；分类重叠不相加。
- 在 EnterpriseOps-Gym CSM 场景构建 source-local Pi、89-Tool MCP Gateway、临时数据库和 31 条 Host-private SQL verifier。Trace 驱动修复 Thinking 绑定、Tool transport、权限语义、幂等、清理和 gold 泄漏等 11 个评测链问题，使可执行 verifier 从 3/31 提升到 26/31、业务 Tool 从 0 恢复到 47 次且 3/3 临时库清理；state-contract 在同一 Validation 上由 2/3 task、28/31 verifier 提升到 3/3、31/31，但一次性 Held-out 仅 1/8、54/65，因而被 Promotion gate 拒绝。
- 在 12-case CloudOps 故障定位沙盒中打通 source-local Pi、能力令牌 Tool Gateway、Host-only CA/FA/JRA scorer 与 Trace/Eval/Sandbox/Artifact 回执链，修复 Tool transport 和 observation hash 合同后实现 12/12 作答、98/98 Tool 成功、CA 1.00；对三条效率候选执行消融并自动拒绝质量回退分支。
- 将真实 Memory maintenance 的 834.945 秒 JSONL 晚失败转成可复现 private-shadow 优化链；通过精确 pre-run snapshot、content-addressed replay、本地 dense provider 与合法 JSON receipt，最终在 v5 完成 5/5 整理决策、4/4 durable recall、1/1 temporary abstention，并通过 rollback/replay 门禁。
- 设计受质量约束的 Sol/Luna 单变量模型评测，并用 receipt checker 锁定相同 task manifest、Prompt、Tool catalog、runner、Runtime provenance、thinking=max 与价格来源；匹配重跑中 Luna Max 将 API 成本估算从 $3.243385 降至 $0.725239（-77.64%）、延迟降低 16.45%，但 task 从 3/3 回退到 2/3、verifier 从 31/31 回退到 30/31，因此阻止低价模型越过质量门禁。

## 四个垂直场景结果矩阵（面试可引用）

所有行都保留原始分母、Validation/Held-out 边界和 Keep/Reject 结论；不同垂直不合并成一个总分。

| 场景 | 为什么改 | 具体怎么改 | 前后效果 | 决策 / 代价 |
| --- | --- | --- | --- | --- |
| EnterpriseOps CSM | 执行链在进入业务 Tool 前就失败；执行链修复后，剩余错误集中在相对日期、角色和跨实体终态 | 先修 capability-token Gateway、MCP `isError`、per-action authority、幂等和 fail-closed cleanup；再固定 as-of date、exact string、动态 owner 和终态审计；模型成本轮锁定同一 task/Prompt/Tool/runner/Runtime provenance/`thinking=max` | 执行链 `3/31→26/31`、业务 Tool `0→47`、cleanup `3/3`；状态合同 Validation `2/3→3/3`、`28/31→31/31`、Tool `72→64`；匹配模型轮 Luna 成本估算 `-77.64%`、延迟 `-16.45%` | state-contract 赢 Validation，但一次性 Held-out 仅 `1/8、54/65`，拒绝 Promotion；Luna 因 task `3/3→2/3`、verifier `31/31→30/31` 被质量门禁 Reject，保留 Sol |
| Enterprise RAG | 纯关键词检索对语义改写和跨来源排序不足；检索改善后，最终答案仍缺逐事实引用 | 在 5,101 文档/29,846 chunk 上建 BM25+dense hybrid，比较 RRF、candidate depth 和 Qwen3 reranker；答案层拆开事实覆盖、引用支持和拒答分母 | Recall@10 `0.6719→0.9554`（相对 `+42.19%`）、MRR `0.6042→0.8672`（`+43.53%`）、nDCG@10 `0.6128→0.8872`（`+44.78%`）；答案引用支持仍 `0/2` | 保留检索 winner；Skill/tuned/Agentic 答案候选因引用门禁失败被拒绝，不用拒答样本抬高引用覆盖 |
| CloudOps | 原始运行因 Tool transport / observation hash 合同错误无法产生正式分；Luna retry2 又在 Prompt 前被错误时序门禁拦下 | 冻结 12-case、3×4 Session 和 Host-only scorer，修复 snapshot/Tool 地址/回执；retry3 改为 `Runtime 就绪→模型校验→thinking 选择→回执校验→Prompt` | baseline 从无正式分恢复到 `12/12`、`98/98` Tool、CA `1.00`；retry3 从“Prompt 未进入”到“已进入”，随后暴露 8 次 Provider fetch failure | 效率候选因 CA 回退被 Reject；retry3 无质量分、无可计价 usage，也 Reject；原 Luna 超时失败运行估算 `$0.627878`，不算节省 |
| Memory Maintenance | 真实月度整理在 `834.945s` 后 JSONL 截断；早期 shadow 又先后缺 replay、dense coverage 和机器可验证回执 | 依次加 private shadow、精确 pre-run snapshot、content-addressed output replay、Boolean gate 修复、确定性 dense provider 和合法 JSON receipt | v1/v3/v4 逐步暴露并关闭缺口；v5 达到整理 `5/5`、durable recall `4/4`、temporary abstention `1/1`、vector coverage `0→1`，rollback/replay/receipt 全通过 | v1/v3/v4 作为 Reject 回执保留；v5 仅是 private-shadow winner，模型调用 `90.642s→85.172s`，不声称生产 Memory 已修复 |

## 30 秒口述版

> PAW 不是再造一个聊天框，而是一套能对 Agent 工作流做隔离实验、Trace 归因和验收回放的本地 Runtime。我在四个垂直场景验证了这套闭环：企业 RAG 的 nDCG@10 从 0.613 提升到 0.887；EnterpriseOps 执行链从 3/31 恢复到 26/31，并把状态合同 Validation 做到 3/3、31/31；CloudOps 修复评测与 Tool 合同后做到 12/12 作答、98/98 Tool 成功；Memory private-shadow 从 13.9 分钟晚失败走到 5/5 整理和 4/4 持久记忆召回。每个候选只改一层，质量门禁不过就 Reject：匹配的 Luna 成本轮虽然估算便宜 77.64%、快 16.45%，却回退到 2/3 task、30/31 verifier，因此仍保留 Sol；EnterpriseOps one-shot Held-out 也只有 1/8，没有包装成生产 100%。

## 面试主动说明的边界

- Enterprise RAG 是 16 条 Validation，不是 Held-out 或生产指标。
- 74.19 个百分点是“坏掉的评测/执行链 → 修复后的执行链”，不是 workflow 算法提升。
- EnterpriseOps 分两段讲：执行链修复由 `3/31` 到 `26/31`；随后在已修复的执行链上，state-contract 才由 `2/3、28/31` 到 `3/3、31/31`。两段基线不同，不能拼成一次端到端算法提升。
- EnterpriseOps 的 5 条失败不能直接归成模型 workflow 错误：3 条来自不一致的 as-of date；1 条把 Prompt 未公开的 case assignee `217` 写成隐藏 gold；另 1 条 verifier 同时要求 owner `152` 和 seed 中按错误电话前缀规则得到的最小 ID `9`，本身不可满足。原始分数仍保留，不能事后删题拼成 100%。
- Trace 的 11 个缺陷、3 个 Skill 问题、6 个流程和 9 个 Tool/Runtime 项有重叠，不能相加。
- 所有 EnterpriseOps 运行都在隔离的 source-local 实验版中完成；为避免失败候选影响用户系统，尚未应用到当前 PAWOS。Validation winner 只消费过一次冻结 Held-out，结果为 `1/8、54/65`，之后未重跑，Promotion 被拒绝。
- Luna 的 `-77.64%` 是由 Runtime DB Provider usage 与 2026-09-01 冻结价格来源计算出的 API 成本估算，不是 Provider 账单；匹配对照中它伴随 task `3/3→2/3`、verifier `31/31→30/31` 回退，因此结论是 Reject，不是节省或替换成功。旧的 `-96.43%` 记录因 thinking/source provenance 不匹配已撤回。
- CloudOps 的“有效优化”是 Tool/Eval 执行合同修复；三个效率候选都因质量或可靠性回退被拒绝，不能写成效率 winner。
- Memory v5 是 private-shadow 评测链 winner，不等于生产 Memory 已完成修复，也不能把 `834.945s` 和 `85.172s` 当同口径加速比。

## 证据入口

- `runs/enterprise-rag-validation-20260831.v1.json`
- `trace-defect-ledger.v1.json`
- `ENTERPRISEOPS_CSM_TRACE_REPAIR_20260901.md`
- `runs/enterpriseops-csm-baseline-validation-20260901-v5.v1.json`
- `runs/enterpriseops-csm-suite-v2-validation-winner-20260901.v1.json`
- `runs/enterpriseops-csm-suite-v2-heldout-one-shot-20260901.v1.json`
- `runs/enterpriseops-csm-sol-max-validation-20260903.v1.json`
- `runs/agent-lab-cost-sol-max-20260903.v1.json`
- `runs/enterpriseops-csm-luna-max-validation-20260903.v3.json`
- `runs/agent-lab-cost-luna-max-20260903.v3.json`
- `runs/agent-lab-optimal-path-model-cost-20260903.v2.json`
- `runs/cloudops-agent-validation-20260901.v1.json`
- `runs/cloudops-evidence-search-validation-reject-20260901.v1.json`
- `runs/cloudops-bounded-workflow-validation-reject-20260901.v1.json`
- `runs/cloudops-observation-id-validation-reject-20260901.v1.json`
- `runs/cloudops-luna-max-baseline-validation-20260902-retry3.v1.json`
- `runs/agent-lab-cost-cloudops-luna-failed-run-20260902.v1.json`
- `runs/memory-maintenance-luna-max-validation-20260902.v1.json`
- `runs/memory-maintenance-luna-max-validation-20260902.v3.json`
- `runs/memory-maintenance-luna-max-validation-20260902.v4.json`
- `runs/memory-maintenance-luna-max-validation-20260902.v5.json`
