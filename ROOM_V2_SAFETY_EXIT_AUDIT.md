# Room V2 安全退出审计

审计基线：`feea050`。审计日期：2026-07-20。

## 结论

当前实现是有价值的 **Kernel 原型与 test cohort**，不是已经接管产品 Room 的生产执行面。六项安全退出检查中，路径唯一性、取消传播、最终态和 panic 恢复均为危险；深度/预算与去重仍需关注。不要因为单元测试或 `room-v2-test` cohort 通过而宣布生产完成。

| 检查项 | 结论 | 核心原因 |
|---|---|---|
| 路径唯一性 | ❌ 危险 | 产品 HTTP Room 仍走 legacy `post_room_message -> prompt`；没有 Root/Task/Dispatch 创建入口。Kernel 又同时暴露 typed command、worker 直调和 store 直调三层路径。 |
| 深度与预算 | ⚠️ 需关注 | Kernel enqueue 会检查 hop/depth/budget，但上限由调用者传入且没有硬上限；legacy Room 链完全不经过这些计数器。 |
| 取消传播与幽灵执行 | ❌ 危险 | Pi 接受 Dispatch 后、Kernel 接收 ACK 前崩溃，会得到 `unknown`；reconcile 只撤销 capability，不调用 `room.cancel`，panic 也不选择 unknown。 |
| 去重与双开火 | ⚠️ 需关注 | Kernel 的 `(root_id,idempotency_key)` 与 lease 防重放较好；但 legacy message 可不传 `clientMessageId`，且 legacy/Kernel 尚未真正完成切换。 |
| isFinal | ❌ 危险 | 前端 reducer 的判定是正确的，但后端没有产品 finalize route；cancel 不关闭 Task，也不写 terminal receipt，因此输入面可能永久等待。 |
| panic 恢复 | ❌ 危险 | panic 能取消数据库里的 active 状态并尝试 RPC，但没有 durable cancel outbox；unknown/崩溃窗口无法补发，最后仍可能需要停止 Pi Host/进程。 |

## 真实入口与路径清点

### 当前产品路径

```text
POST /api/agent/rooms/{roomId}/messages
  -> DebugRequestHandler.do_POST
  -> AgentService.post_room_message
  -> AgentService._post_room_message_once
  -> Rooms.plan_route
  -> AgentService.prompt(target_session)
  -> Pi Session
  -> message_completed
  -> _room_event_projection
  -> participant_message 直接进入旧 Room timeline
```

证据：

- `rag_ime/debug_server.py:7504-7508`
- `rag_ime/agent_service.py:2610-2894`
- `rag_ime/agent_service.py:6186-6204`

这条路径没有创建 `room_kernel_roots`、`room_kernel_tasks` 或 `room_kernel_dispatches`。全仓产品代码也没有调用 `RoomKernelStore.create_root/create_task/enqueue_dispatch`；这些调用目前只在测试中出现。

### 预期 Kernel 路径

```text
Root(generation=g)
  -> canonical Dispatch + outbox
  -> worker lease
  -> Pi room.dispatch
  -> runtime dispatch_accepted receipt
  -> Kernel running
  -> agent_settled + RoomCommit
  -> optional explicit RoomPost
  -> quiescence + acceptance + terminal receipt
```

HTTP 目前只提供 snapshot/events/commands/settle，没有 Root 创建、Task 创建、Dispatch 创建或 finalize route。`RoomCommit.action="dispatch"` 只会把当前 Dispatch 标成 committed，`apply_commit()` 不创建后继 Dispatch。

### A -> B -> A 完整循环

当前产品无法通过 Kernel 自己形成该循环；它只能由测试或内部调用手工 enqueue：

```text
d1: A -> B, hop=0
  -> B settle RoomCommit(action="dispatch")
  -> 没有 continuation producer，链条在这里断裂

若外部代码手工补 d2:
d1 A -> B (hop=0)
  -> d2 B -> A (hop=1,parent=d1)
  -> d3 A -> B (hop=2,parent=d2)
  -> ... -> hop > max_hops 时拒绝
```

Legacy 实际路径则是：

```text
Room message -> 路由到 A -> A 通过 intercom/旧消息触发 B
  -> B 再触发 A -> ...
```

因为正常产品流没有 RoomBinding，`_guard_legacy_room_route()` 不会把它交给 Kernel，所以 Kernel hop/depth/budget 对此不生效。Room 初始成员虽限制为 2-4 个，但同一批 Agent 可以进行 15 次以上互相触发；这不是 15 个并发成员，却同样会造成上下文、费用和循环风险。

## 六项详细审计

### 1. 路径唯一性：❌

同一个取消语义至少有三条 Python 路径：

1. `AgentService.apply_room_kernel_command -> RoomKernelWorker.apply_control_command`，会尝试运行时传播。
2. `RoomKernelWorker.cancel_root`，先直接调用 store，再调用 runtime。
3. `RoomKernelStore.cancel_root/panic/cancel_target`，只改数据库，不传播运行时。

`tests/test_room_v2_safety_exit_audit.py::test_reproducer_direct_store_cancel_commits_without_runtime_propagation` 已证明第 3 条能留下“数据库显示 cancelled，Runtime 未收到 cancel”的分裂状态。

改进要求：保留一个可调用的 `KernelCommandBus.submit()`；把 store 的状态迁移方法改成模块私有或要求 transaction capability，worker/callback/HTTP 全部提交同一个 typed command。Root/Task/Dispatch 的产品创建也必须只有该入口。

### 2. 深度、预算和 15 次互相触发：⚠️

`RoomKernelStore._enqueue_dispatch()` 正确检查：

- generation 一致；
- parent 属于同 Root；
- child hop 必须为 parent hop + 1；
- depth 不可倒退；
- budget 在 enqueue 时预留。

问题：`create_root()` 对 `budget/max_hops/max_depth` 只检查非负，不设系统硬上限；`depth` 也不要求明确的 +1/同层语义。更重要的是 legacy 路径绕过全部限制。

改进要求：Kernel 内部常量给出不可绕过的 ceiling，例如 `MAX_HOPS <= 12`、`MAX_DEPTH <= 4`、单 Root 最大 Dispatch/墙钟/Token；请求值只能向下收紧。continuation producer 必须原子增加 hop 并预留预算。

### 3. 取消传播与幽灵执行：❌

可复现窗口：

```text
lease committed
  -> Pi room.dispatch 返回 accepted（副作用已经开始）
  -> 进程在 accept_runtime_receipt 前崩溃
  -> lease 过期，Kernel 标记 unknown/dead_letter
  -> reconcile 仅 revoke capability
  -> panic 查询 active targets，不包括 unknown
  -> Pi 执行可能继续
```

可执行证据：`test_reproducer_runtime_accept_then_kernel_ack_crash_becomes_uncancellable_unknown`。

另一个窗口是取消先提交数据库、再调用 runtime；两者之间崩溃时没有 durable cancel outbox 可恢复。`RoomKernelWorkerLoop.close()` 的 join 有超时，随后无条件丢弃 thread 引用；如果 `runtime.dispatch_room()` 卡住，也可能形成进程内幽灵线程。

改进要求：

- 在同一数据库事务中写入 `cancel_intents` outbox 和 generation fence，再由可重放 worker 投递。
- Runtime cancel 必须以 `(root,dispatch,session,generation)` 幂等，回执完整匹配。
- unknown 仍要保留可取消的 runtime target，直到收到 cancel receipt 或管理员确认进程已死亡。
- close 后 thread 仍 alive 必须报告 unhealthy，不能清空引用假装停止。
- 模型、工具、命令子进程、retry/timer、follow-up、compaction 都要注册到同一个 Root AbortScope。

### 4. 去重与双开火：⚠️

Kernel 内部优点：

- `(root_id,idempotency_key)` 唯一；
- compatibility source 有稳定映射；
- lease 过期后进入 unknown，不盲目重放；
- RoomCommit 对每个 Dispatch 唯一，RoomPost 另有 idempotency key。

剩余问题：legacy `post_room_message()` 允许缺少 `clientMessageId`，此时没有 durable command receipt；Kernel 又没有接管产品入口，因此当前仍存在两套语义不一致的执行模型。typed Pi Host handler 源码不在仓库，无法审计 host 端是否按 idempotency key 去重。

### 5. isFinal 与后台仍在跑：❌

前端 `reconcileFinal()` 本身是安全的：只有 Root 终态、同 generation 的 applied terminal receipt、且 `root.terminalReceiptId` 精确匹配时才设 `isFinal=true`。

后端闭环不成立：

- 没有产品 HTTP finalize route；
- settle complete 只关闭 Task/Dispatch，不更新 Root；
- cancel_root 不关闭 Task，也不写 terminal receipt；
- `finalize_root()` 因 open Task 拒绝取消后的 Root。

可执行证据：`test_finality_query_proves_cancelled_root_has_no_terminal_receipt_and_open_task`。

因此这里不是“看起来完成但后台还在跑”，而是更直接的“即使取消成功也永远得不到 authoritative final”。生产解锁条件必须由后端 `RootFinalized` 投影提供，前端不能从 Session idle、模型 settled 或普通 cancel receipt 推断。

### 6. panic 与管理员恢复：❌

panic route 可以经 `/kernel/commands` 提交，但只覆盖查询时仍处于 leased/running/retry_wait/timer_wait 的目标。unknown 不在 runtime target 中；数据库提交与 RPC 之间也没有恢复队列。当前最坏情况仍需停止 Pi Runtime Host 或整个服务，并人工核对 unknown/dead-letter。

必须增加独立于普通 worker 的管理员 kill switch：持久化 room-wide generation fence、durable cancel outbox、Host PID/process-group kill、未确认目标清单和恢复后 reconciliation。

## Prompt、Skill、Tool、Context、Knowledge、Profile

| 项目 | 结论 | 审计结果 |
|---|---|---|
| Prompt 唯一 producer | ❌ | `RoomPromptPlanStore` 明确写着 shadow-only；真实 Pi 仍使用 `PiRuntimeConfig.system_prompt_for_session()`。PromptCompile receipt 只作为 capability 元数据，没有把六层正文传给 Provider。 |
| Skill 单一正文 | ❌ | `RoomSkillPolicyStore` 能校验 native `SKILL.md` body hash，但 `AgentService` 没有初始化或调用它；stage、load receipt、compaction restore 均未接入真实 Pi skill loader。 |
| Tool manifest hash | ⚠️ | 后端 compile/load/invoke 的 hash 与 epoch fence 较完整，Room session catalog 也只返回三个 canonical tools；但仓库内没有 `room.dispatch/room.cancel` Pi Host handler，无法证明生产执行面消费相同 manifest。 |
| Session vs Post | ❌ | Kernel projection 只公开显式 RoomPost 是正确设计；当前默认 legacy 路径仍把 `message_completed` 的 assistant 正文投影为 `participant_message`，继续污染 Room 公共上下文。 |
| Provider-only context | ❌ | 常规 Session 有 transient/session context envelope；Room PromptPlan 的 journal/sealed prefix/dynamic tail 目前只编译审计，没有送到真实 Provider。 |
| Knowledge owner scope | ✅/⚠️ | search/read 的 owner/scope/session 都由 active Room binding 推导，read 绑定 retrieval receipt；noRoom search 无副作用。尚缺真实 Kernel E2E 与前端调用证明，所以只能判局部安全。 |
| Profile epoch | ❌ | Dispatch 带 `runtimeProfileRevision/capabilityEpoch`，但 `_prepare_managed_room_dispatch()` 调 compiler 时固定 `profile=None`；CollaborationProfile active pointer 尚未成为 Root/Dispatch 的 pinned input。 |
| ordinary noRoom | ✅ | PromptPlan、Capability、Knowledge promotion 的 noRoom 分支是 no-op/fail closed；本轮及原有测试覆盖了无副作用。 |
| Voice | ✅ | Room canonical manifest 只有 `room_state/room_post/room_commit`，没有语音输出工具。现有 Voice 是独立语音输入/转写产品能力，不属于 Room/Agent 发声。 |

## Agent 如何决定交接

当前两套路径都没有完整答案：

- Legacy：用户消息目标由 deterministic room router 选择，但 Agent 是否 intercom/`@` 下一个人仍主要由模型选择。
- Kernel：`RoomCommit.action="dispatch"` 是结构化意图，却没有 continuation queue producer；该 `@` 时不 `@` 会直接断链。
- Skill：`nextCandidates` 只是 pure read，既不自动调用 Skill，也不创建 Dispatch。

正确方案应是：LLM 只能提出 `ContinuationProposal`；确定性规则根据任务状态、责任人、验收项、风险与预算决定 `dispatch/wait/block/complete`，并原子写 continuation queue。settle hook 若发现仍有未覆盖验收项、未交接责任或待复查 finding，就拒绝 complete 并生成明确 next action。模型不应直接发 `@`。

Prompt 中正向触发规则必须与抑制规则成对：不仅写“不要乱 @”，还要写清楚何时必须提出 handoff/review/block proposal。最终触发仍由 Kernel 校验，而不是只靠模型服从提示词。

## 上线前必须通过的 Gate

1. 产品 Room 创建/消息入口原子创建 Root/Task/首个 Dispatch，legacy executor 在 RoomBinding 下不可达。
2. repo 内存在并测试真实 Pi Host `room.dispatch/room.cancel` handler，而非 fake client。
3. PromptPlan stable prefix + provider tail 成为真实 provider payload 的唯一 Room instruction producer。
4. native Skill load/restore 回执与 SKILL body hash 接入真实 Pi hooks。
5. continuation queue 能完成 A -> B -> A，并由硬 hop/depth/token/wall-time ceiling 截断。
6. durable cancel outbox 覆盖 accepted-before-ACK、cancel-after-DB、retry/timer/host restart。
7. cancel/complete/fail 都能关闭 Task 并生成唯一 terminal receipt；前端只消费它。
8. panic 对 unknown 仍可补发 cancel，并提供进程级 kill 与未确认清单。
9. 真实 production-mode E2E，而不只是 `room-v2-test` cohort，验证无双开火、无 Room transcript 自动公开、ordinary Agent 不回归。

## 本轮验证命令

```bash
../wisdom-weasel-rag-ime-control-web/.venv/bin/python -m unittest -v \
  tests.test_room_v2_safety_exit_audit

rg -n '\.create_root\(|\.create_task\(|\.enqueue_dispatch\(' rag_ime tests
rg -n 'room\.dispatch|room\.cancel' integrations rag_ime tests
rg -n 'post_room_message|participant_message|finalize_root|cancel_root|panic' \
  rag_ime/agent_service.py rag_ime/agent_room_kernel.py rag_ime/agent_room_kernel_worker.py
```

本审计测试是“当前缺口的可执行特征”，不是把缺口标成预期行为。相应功能落地时，应把这些 characterization assertions 改写为生产 invariant assertions。
