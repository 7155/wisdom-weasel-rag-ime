---
name: agent-eval-room-optimizer
description: Execute a bounded PAW Agent Lab experiment in a real Room from its supplied dispatch contract, or guide the user to fill missing evaluation data. Use for evaluation-driven Agent, Tool, workflow, RAG, or Memory tests; do not use for ordinary code changes or ungoverned benchmark tuning.
---

# Agent Lab 评测向导与优化 Room

已有完整实验设置时，直接执行其中授权的有界实验；缺少设置时进入向导模式。
由 Host evaluator 判断结果；Room 只是协作容器，不替代 Pi Runtime、评测器
或用户授权。

## 0. 已授权实验合同

App 把 `agentLabDispatch` JSON 持久记录到 Room `scenarioPrompt` 和首条消息。
`schemaVersion=rag-ime.agent-lab-dispatch.v1` 的合同包含 `objective`、`scope`、
`baseline`、`dataset`、`budget`、`stopConditions`、`workspace`、
`repairOperators` 和 `counterfactualProbes`。用户提交设置就是这次精确 dispatch
的执行授权；不要重新问已给出的目标、预算或权限。

- 只在 `scope.allowedChanges` 内选择有失败证据支持的 operator。配置层修改
  通用 Prompt 或一个检索参数族；实现层修改已定位的 Tool、检索或 Workflow
  owner，并运行其回归检查。`scope.target` 还必须明确是 `prompt`、`retrieval`、
  `tool`、`skill`、`model` 或 `workflow`，所选 operator 的 target 必须完全匹配；不能把
  Tool/Skill 的收益归因给 Prompt。`planned` 探针只是待验证的假设，不是已发生的结果。
- 先在选定目录内准备独立候选副本，记录 baseline revision、candidate root 和
  实际 diff。目录选择或 Room `full_trust` 不是已完成隔离的证据。
- 在同一 Pi Session/Room 中连续提出、执行、比较和淘汰候选，达到
  `maxCandidates`、`maxEstimatedCostUsd` 或任一停止条件就收束。每次付费候选前
  读取累计 usage/价格回执，缺失则停止付费尝试并返回 `blocked`。
  `budget.enforcement=agent_observed` 表示 Agent 观察预算，不能声称 Host 已有
  Room 累计美元硬限。候选数、费用和停止原因必须由真实回执支持。
- 用户经 `agent.room.message` 干预，经 `agent.room.abort` 停止；复用 Pi 的
  Steer、Stop、恢复与 Room 取消扇出。不得创建第二套模型或生命周期 loop。
- 合法终态包括 `improved`、`no_improvement`、`budget_exhausted`、`stopped`、
  `blocked`、`failed`。无有效改善也是完整实验结果。`Keep` 只保留候选，应用到
  指定场景是独立动作；已有 Session 的资源快照不随候选改变。

## 1. 缺失设置时补齐数据

如果 intake 不完整，每轮最多问四组问题，并把答案写入一个短的
`TaskBrief`（包含 compact run, case, and evidence references）。优先复用
historical evidence；不要猜路径、许可证、Gold、价格或成功标准，也不要为了凑
数据生成“真实日志”。优先询问：

1. **目标**：这次要优化什么业务结果？哪些是不可失败的硬门禁？
2. **数据**：数据文件/目录在哪里，来源与许可是什么，是否允许脱敏副本，
   train/validation/held-out 如何划分，Gold 是否由 Host 隐藏？
3. **基准与变量**：基准 receipt/run 是什么；本轮只改变模型、Prompt、
   Skill、Tool、Workflow、Context/RAG 或价格中的哪一项？
4. **成本与权限**：Provider 价格快照和 usage receipt 在哪里；本轮只做
   read-only、Validation，还是用户明确授权了 Room/沙盒修复？

每个缺失项都输出 `dataGap`：缺什么、为什么影响判定、用户要提供的最小
文件/字段、状态 `pending_data`。数据未齐时停在提问，不运行 Validation，
不消费 Held-out。

最小数据清单（只记录元数据，不把隐私原文塞进 Room）：

```json
{
  "datasetId": "...",
  "sourceRef": "user-provided-ref",
  "manifestSha256": "sha256",
  "split": "validation",
  "caseCount": 0,
  "goldAuthority": "host",
  "license": "...",
  "privacy": "redacted|private-shadow",
  "evidenceAvailable": true
}
```

## 2. 冻结合同与候选树

intake 完成后，先冻结：`case-set/manifest`、split、成功标准、verifier、
Prompt/Context、Skill、Tool/schema、Workflow、模型、预算、价格单位和
`heldOutConsumed=false`。同一父节点下每个候选只改一个因素；记录
`parentNodeId`、变更摘要、配置哈希和 Validation run ref。矩阵展示横向
结果，树展示实验谱系；不能把不同 case、长度、模型路由或 scorer 的数字
硬拼成一个提升率。

质量门禁顺序固定为：

```text
task completion → verifier / evidence → runtime reliability
→ context / collaboration / RAG quality → latency / tokens → API cost
```

成本只有在质量门禁通过且 usage、价格快照、输入/输出口径可比时才计算。
没有 usage receipt 就写 `cost: unavailable`，不写“节省 80%”。

### 候选不是优化结果

Room 必须把每个候选节点明确标成一种结果，不能把所有尝试都写成“优化成功”：

```text
improved   目标指标按预设方向改善，硬门禁通过，有前后证据
neutral    质量持平，且没有可证明的效率或成本收益
regressed  目标指标或保护性门禁回退
not_run    没有实际 Validation run
unverified 有运行，但缺少可比 receipt、Gold 或阶段证据
```

只有 `improved` 才能进入场景摘要的“保留优化”。`neutral`、`regressed`、
`not_run`、`unverified` 必须进入“未纳入方案”，保留原因和证据。没有
`before`、`after`、预设方向、硬门禁结果和 evidence refs 时，不得标成
`verified`。这不是要求探索过程每次都成功，而是禁止把失败探针伪装成优化。

一次候选同时改变 Model、Prompt、Tool、Workflow 等多个层时，标记为
`compound_repair`，只能证明“组合修复有效”，不能把收益归因给某一层；下一轮
必须拆成单变量候选。路径树可以保留组合节点，但矩阵的“改了什么”必须写清楚
“组合修复”。

## 3. 按失败 owner 选择改动

先读 Host receipt 和必要的 Trace，再选一个最小候选；不要看见失败就改
Prompt：

| 证据中的 owner | 只允许优先尝试 | 不应做的事 |
| --- | --- | --- |
| `prompt_context` | Prompt、Context envelope、检索查询改写 | 不改 Tool/Runtime 来掩盖上下文缺失 |
| `tool_runtime` | Tool schema、transport、timeout、增量 framing | 不用 Prompt 解释协议失败 |
| `workflow` | 状态合同、依赖、retry/resume、delegation、cleanup | 不换模型来掩盖状态机错误 |
| `rag_retrieval` | parse/chunk/index/hybrid/rerank/packing 的一个 family | 不从单个问答臆测最优参数 |
| `memory` | recall、provenance、冲突、freshness、consolidation 的一个 seam | 不把个人 Memory 当 Knowledge RAG |
| `evaluator_gold` | 修正矛盾的评测合同并重新冻结 | 不重跑到“好结果”或改分母 |
| `pricing` | usage 采集、模型价格快照、成本单位 | 不把价格差当质量提升 |

App 合同中的 `scope.target` 是本轮唯一优化对象：

| target | 可改变的变量 | 必须保留的对照 |
| --- | --- | --- |
| `model` | 业务执行模型（配置层） | Judge 模型、推理强度、Prompt、Tool、Skill、Workflow、数据集、评分器；用同口径价格与完整 usage 比较 |
| `prompt` | Prompt 模板、证据覆盖和拒答规则 | 模型、Tool、Skill、RAG、数据集、评分器 |
| `retrieval` | parse/chunk/search/rerank/packing 或一个检索参数族 | Prompt、模型、Tool、Skill、数据集、评分器 |
| `tool` | Tool 选择、schema、transport 或错误语义 | Prompt、模型、Skill、权限、数据集、评分器 |
| `skill` | Skill 选择、版本、加载与输出契约 | Prompt、模型、Tool、权限、数据集、评分器 |
| `workflow` | 依赖、重试、恢复、清理和编排边界 | Prompt、模型、Tool、Skill、权限、数据集、评分器 |

若合同没有对应 target 的失败证据或 operator，返回 `blocked` 并说明缺口，不能
退回到“先改 Prompt”这一默认猜测。

### 每个垂直项目先追加一段最小工作合同

Agent Lab 使用 Room 的 `scenarioPrompt` 追加项目合同，不替换 PAW/Pi 的全局
系统提示词，也不创建第二套 Agent loop。合同必须短、可测试，并和本轮候选
分开记录：稳定的项目合同是冻结控制；只有明确把 `Prompt` 选为本轮单一变量
时，才允许产生新的 Prompt candidate。

- **Knowledge RAG**：只依据可回跳的原始证据回答；数字、日期、否定、范围和
  限制条件不得擅自改变；每条关键事实绑定 source/chunk；证据缺失或冲突时
  输出 `info_not_found` 或需要人工确认，禁止用模型常识、隐藏 Gold 或编造内容
  补齐。Room 简报、Agent 消息和指标账本只是控制或摘要证据，不是业务原文；
  禁止把 room/session/event ID 伪装成 sourceId/chunkId。没有同时取得原文正文
  和真实 source/chunk 绑定时，不生成形式化引用。
- **EnterpriseOps / CI**：精确保留任务中的标题、日期、角色和依赖；写后回读；
  是否完成只看程序终态、业务 Tool 回执与 Host verifier，Agent 自述不算成功。
- **CloudOps**：只依据冻结日志、指标、Trace 与 runbook；观察、推断和未知分开；
  缺少观测时不猜根因，少调用或低延迟不能抵消错误诊断和 Tool failure。
- **Memory maintenance**：按人工冻结的“长期保留 / 临时拒记”样例判断；输出
  必须符合固定 JSON schema；重复运行不得新增重复记忆，并验证召回、回滚和
  replay；不把私密原文放进公共报告。

Reviewer 应先检查候选是否仍遵守该项目合同，再检查目标指标。若候选通过某个
数字却违反忠实性、引用、终态、幂等或证据门禁，必须 `Reject` 并保留回执。

### 从工作流缺口生成 Tool candidate

当 Trace 表明任务要求的事实或动作无法由当前 Tool 集合表达时，先列出
`业务条款 → 所需事实/动作 → 当前 Tool 可否提供 → 缺口`，再决定 Tool
候选；不能因为 Agent 答错就直接增加 Tool。

- 现有 catalog 已有能力时，只生成 Tool 选择、参数适配或 allowlist 候选，并
  明确标记 `existing_catalog`；不能声称从零开发了 Tool。
- 当前 catalog 确实缺能力时，生成一个 `new_sandbox_tool` 候选。候选必须写清
  输入/输出 schema、最小数据与权限范围、错误语义、写操作幂等键、审计回执、
  deterministic fixture 和回滚方式；禁止用任意 SQL、Shell 或文件访问充当通用
  后门，也禁止返回 Gold/正确 ID。
- Tool Builder 只在垂直 App 的隔离沙盒实现候选；Reviewer 先检查权限、泄漏、
  幂等和失败语义，再跑 Tool fixture。只有 Tool 层通过，才进入同一冻结业务
  Validation；安装或注册到 PAWOS 仍需单独授权。

例如任务要求“选择任职最久的英国员工”，而 `list_users` 只给
`locationId` 与任职时间：若 catalog 已有 `find_locations`，正确候选是收窄授权
并组合两次查询；只有 catalog 连国家映射能力也没有时，才创建新的只读 Tool。

RAG 和 Memory 的专门边界分别交给
`rag-retrieval-optimization` 与 `memory-curation`；跨 Session 因果证据
才调用 `trace-agent-diagnostics`。没有匹配证据时标记
`not_applicable` 或 `unknown`，不要制造 finding。

每个场景结束时，Facilitator 必须从 Host receipt、Trace 和 Eval projection
生成一份汇总：业务目标、基线、候选改动层、前后输出、质量/可靠性/效率/成本
变化、`targetObject`、`effectStatus`、Keep/Reject 原因和 evidence refs。不能从 Agent 自述
推导成功率，也不能把不同场景的指标相加。

## 4. 可用工具与调用顺序

只使用当前安装态可验证的接口：

1. `agent.eval-lab.runs`：读取实验、任务、脱敏验收、矩阵和路径树；只读。
2. `trace_diagnostics.inspect`：一次读取选定 Session/Room/run 的公开
   Trace、span、Tool、WorkItem、Context 和 Eval 证据；不替代 transcript。
3. `scripts/score_agent_lab_optimal_path.py`：对已冻结的候选树做质量优先
   剪枝和成本/延迟排序；缺字段保持 blocked/insufficient evidence。
4. `scripts/build_agent_lab_cost_receipt_from_runtime_db.py`：仅对匹配的
   私有 runtime DB 生成 usage + price snapshot receipt；无 DB 就报告缺口。
5. `agent.rooms.create` / `agent.room.message`：用户进入讨论时发送本 Skill、
   TaskBrief 和缺失问题；用户提交完整 `agentLabDispatch` 后直接执行已授权候选。

源代码中的真实候选入口和版本边界见
[references/scene-runners.md](references/scene-runners.md)。先核对当前安装的
runner 是否提供该参数；缺少接口是运行缺口，不能仅生成一段结果 JSON 冒充执行。

诊断阶段是 read-only。验证候选必须使用 same frozen Validation case-set 和新的 sandbox/run；不能为了改善数字换题或改变分母。安装、
真实工作区写入、Memory apply、发布和 Held-out 都需要用户在对应边界明确
允许（explicit approval）。保留 Reject、失败、取消和不可比的 receipt。

## 5. 四个最小示例

**EnterpriseOps CSM。** 固定同一 suite/case-set，先保留 baseline，再只
改 state-contract workflow。3/3 task、31/31 verifier 后才能进入成本分支；
Luna 先以相同 Prompt/Tool/Workflow 做 Validation，质量持平后才比较 usage
和价格。若只有模型价格、没有 Luna usage，结论是“成本待补”，不是 80%。

**Knowledge RAG。** 用户只提供一批 PDF 而没有 QA/gold 时，先问来源、许可、
解析 manifest、问题集和证据可用性；数据齐后一次只比较 heading-aware、
semantic 或 fixed chunk 等一个 family，固定 Recall/precision、citation、
abstention、向量数和延迟。不要把 chunk 边界主观分数写成最终效果。

**CloudOps / Incident。** 先冻结告警、服务拓扑、runbook 和 verifier；若首个
失败在 Tool/transport，就修 Tool contract 并用同一 fixture 验证，不能用 Prompt
掩盖。Trace 只用于定位和回证，Host evaluator 才判定是否恢复、是否引入回归。

**Memory maintenance。** 对真实已批准 timeline 建 private shadow，保留
原始失败 `invalid Pi Runtime Host JSONL / truncated record`。候选应优先是
有界 packet、增量 framing、parse/apply 幂等和 stage-level Trace；不能把
后续 Knowledge/RAG 或 Room 协作自动归因给这次后台维护失败。先跑一个
Validation 日，再由用户决定是否扩展到更多日期。

## 6. 输出与停止

每轮返回一个短的向导结果（可被 App 渲染）：

```text
status: needs_user_input | ready_for_validation | candidate_proposed |
        validation_running | verified | no_improvement | budget_exhausted |
        stopped | failed | blocked
questions: []
dataGaps: []
baseline: run/receipt + frozen controls
candidates: parent/child + one changed factor + effectStatus
metrics: hard gates, quality, reliability, efficiency, cost + before/after evidence
nextAction: one concrete user-approved action
evidenceRefs: public receipt / Trace / Eval refs
```

只有 Host verifier receipt 能判定 pass/fail。候选建议不是修复；只有用户
明确授权、候选实际落地、且新的 Trace/Eval 验证通过，才可写 verified。
最后由 Facilitator 发出 one terminal result，并独立标注
`detectedBy/proposedBy/authorizedBy/implementedBy/verifiedBy`。

读取 [references/evaluation-routes.md](references/evaluation-routes.md) 选择
`evaluationKind`，读取 [references/result-contract.md](references/result-contract.md)
生成最终 Room 结果。若主因仍未知、数据/Host verifier/Validation sandbox
缺失、fingerprint 漂移或授权未给出，停止并返回边界，不继续试错。
