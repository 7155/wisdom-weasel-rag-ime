# EnterpriseOps CSM：Trace 驱动的评测链修复记录

日期：2026-09-01  
范围：3 个冻结 Validation 任务、31 条原始 SQL verifier、89 个 live MCP Tool。  
运行边界：外置 source-local Pi candidate；未安装、未启用 PAWOS；8 个 Held-out 未运行。

## 结果

最初的 plumbing run 没有真正进入业务 Tool：0/3 任务完成、3/31 verifier、0 次业务 Tool。修复 Runner、Tool Gateway 和 Session 权限合同后，最终 baseline 达到 1/3 任务完成、26/31 verifier、47 次业务 Tool、0 次 Tool failure，3/3 临时数据库完成删除。

这相当于 verifier 通过率从 9.68% 上升到 83.87%，增加 74.19 个百分点；但两次运行的 transport、权限和 Runner 合同不同，因此它只能表述为“评测与执行链修复”，不能表述为 workflow 算法效果提升。

在修好的合同上，`state-contract-v1` 仍为 1/3、26/31，并额外消耗 54 次 Tool、470.2 秒且出现一次 Tool failure；相对 baseline 的 47 次 Tool、376.4 秒分别增加 14.89% 和 24.93%，故严格 Reject。

## 为什么不是 100%

5 条失败 verifier 分布在后两个任务：Wayne Enterprises 任务失败 2/5，Larson PLC 任务失败 3/15。它们不是同一类问题。

| 类型 | 失败数 | 证据 | 判断 |
| --- | ---: | --- | --- |
| 相对日期合同缺失 | 3 | Prompt 没有提供共同 `businessAsOfDate`；state-contract 又显式给出 `2026-06-24`，因此 Agent 将 `next year` 解释成 2027，而 gold 固定要求 2026 | Benchmark 时间合同不一致；不能把歧义日期单纯算作 Agent 能力失败 |
| Assignee 的隐藏 gold | 1 | Larson Prompt 没有要求 case 必须指派给 `217`；“Assigned: group manager”只出现在 KB 正文模板里，但 verifier 把 case assignee 硬编码为 `217` | 观察到 Agent 复用了 knowledge owner `152`，但现有 Prompt/gold 不足以把它定性为真实 workflow 缺陷 |
| Verifier 自相矛盾 | 1 | verifier 同时硬编码 knowledge owner `152`，又要求它等于活跃英国 agent/manager 的最小 `user_id`；seed 中按该 SQL 得到的最小值是 `9`，且它把“同一国家”错误替换成电话前缀 | 该 SQL 在不篡改无关数据的前提下不可满足，属于 benchmark gold 缺陷 |

因此当前必须保留原始口径 `26/31 = 83.87%` 与 `1/3 = 33.33%`，不能事后删除失败项拼出 100%。下一轮应先以 seed header 的 `2025-11-04` 冻结共同 `businessAsOfDate`，并人工裁决 assignee 规则与矛盾 verifier，形成新 suite revision；只有在新 revision 上重跑 baseline 与 candidate，才可以产生新的可比较成功率。

端到端任务成功采用 all-or-nothing：一个任务只要有一条有效 verifier 失败，即使其余 14 条通过，也记为失败。样本只有 3 个任务，因此每个任务占 33.33 个百分点；这个数字适合说明闭环是否完整，不适合单独包装成稳定的生产成功率。

## 发现与修复

| ID | 发现 | 修复 | 当前证据 |
| --- | --- | --- | --- |
| CSM-RUNTIME-001 | `update_session(thinkingLevel)` 没有改变实际 Pi thinking，requested `high` 最终仍是 `xhigh` | Runtime ready 后显式调用 `select_thinking_level`，分别校验 effective model 与 thinking receipt | live plumbing |
| CSM-TRANSPORT-001 | 文件 spool wrapper 未截获普通业务 Tool fetch，模型看到 `fetch failed` | EnterpriseOps 改用 capability-token 保护的临时 loopback Gateway | live：单题 0 Tool、1/11 → 11 Tool、11/11 |
| CSM-AUTHORITY-001 | 沙盒数据库可写，但 Session 标成 `read_only`，优化 Agent据此拒绝业务写入 | 改为 `per_action`，Prompt 明确宿主文件不可写、仅临时 CSM DB 的受限 Tool 写入获授权 | live Validation |
| CSM-MCP-ERROR-001 | MCP 返回 `isError:true` 时 Gateway 仍记作成功 | 识别 `isError`，写失败 ledger 并返回结构化 ValueError | focused test |
| CSM-CLEANUP-001 | verifier 异常可能绕过 unbind/delete；删除失败仍可输出 completed | 嵌套 finally，区分 `not_created/deleted/delete_failed`；cleanup 失败使报告无效 | focused test + 3/3 live delete |
| CSM-GOLD-LEAK-001 | 公共报告暴露 verifier 名称和低熵 expected-value hash | 只投影 verifierIndex、passed、errorType；SQL、名称、expected 留在 Host | focused test |
| CSM-TERMINAL-001 | `turn_failed` 但数据库碰巧满足条件时也可能算任务成功 | task success 同时要求 `turn_completed`、无 Runtime error、全部 verifier 通过 | focused test |
| CSM-ORACLE-001 | Agent 实际看到 task-selected Tool，却可能被包装成 full-catalog 自主选择 | 报告固定标记 `task_selected_oracle` 与 `selectedToolNamesVisibleToAgent=true` | report contract |
| CSM-REPLAY-001 | 缺少 toolCallId 校验，同一 mutation 重放可能执行两次 | 强制非空 toolCallId；相同 ID/相同 payload 返回缓存结果，不同 payload fail closed | focused test |
| CSM-SPLIT-001 | Validation loader 先解析全部任务，存储级上读到了 Held-out body | 先核对文件名 universe，再只读取当前 split 的显式 ID | focused test with invalid Held-out bodies |
| CSM-SERVER-ERROR-001 | Gateway 的预期 RuntimeError 未被通用 HTTP Server 捕获，连接被直接断开 | EnterpriseOps 将可预期 Tool failure 转成结构化 ValueError，由 Server 返回受控错误 | focused test；尚未重跑 live candidate |

## Workflow 候选淘汰

| 候选 | 任务成功率 | Verifier | Tool | 时长 | 决策 |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline-v1 | 33.33% | 26/31 = 83.87% | 47，失败 0 | 376.4s | incumbent |
| state-contract-v1 | 33.33% | 26/31 = 83.87% | 54，失败 1 | 470.2s | Reject |

先前的 `dependency-plan-v1` 也没有晋级：在同一代 Runner 上 verifier 为 23/31，相对当轮 baseline 的 24/31 更差。它证明“增加计划、回查和 Tool 数”不等于提高完成质量。

## 可用于面试的结论

> 我没有直接把 Prompt 调长后挑一个最好结果，而是为垂直 Agent 建了 source-local Pi、临时数据库、Host-private verifier、Trace、失败回执和 Promotion gate。Trace 先定位了 Thinking、Tool transport、权限语义、错误投影、幂等和数据泄漏等 11 个评测链缺陷；修复后业务 Tool 从 0 次恢复到 47 次、verifier 从 3/31 提升到 26/31。随后两个 workflow 候选都没有超过 baseline，因此保留 Reject，而没有消费 Held-out。

不能说：业务 workflow 成功率提升 74.19 个百分点、Held-out 已通过、89 个 Tool 由模型自由选择、当前 PAWOS 已安装这些修复，或 Trace Agent 自主完成全部修复。
