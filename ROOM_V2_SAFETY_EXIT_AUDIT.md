# Room V2 安全退出审计

审计基线：产品 `a4c12fc`、Pi `692bb0e878772129766b9eb837a8caa57f48e0e7`（历史原始审计基线为 `feea050`）。审计日期：2026-07-20。

## 2026-08-01 Control Center 任务流转投影增补

本节只更新任务生命周期的可见投影，不改变 Kernel、取消、结算或
`isFinal` 的权威 owner。Control Center 的任务页不再用三个统计数字代替流程，
而是从同一份 Room snapshot/SSE reducer 投影：

```text
任务创建 -> 每项分工 -> 伙伴派发/执行 -> 共同结果
```

每个 Task 形成一条路径，按 `taskId` 关联 Dispatch，并同时显示伙伴、动作和
等待/执行/完成/失败/停止状态。详细公开进度、复核、回执和可选私有 Session
披露继续保留在图下方。窄容器转为纵向流，不产生横向滚动；图标和文字重复颜色
语义，活动连线遵守 `prefers-reduced-motion`。

最终态继续 fail closed：只有 `root.isFinal && root.state == completed` 才把共同
结果画成完成。`blocked`、`failed`、`cancelled`、`cancelling` 和
`cancelled_with_unknowns` 均保持各自的未完成/待处理语义，公开 Post 数量或成员
回复不能让图自行推断成功。当前证据是 source-focused React tests、TypeScript
检查以及 1440×1000/430×900 浏览器投影检查；这不是 installed macOS 或发布放行
证据。

## 2026-07-21 受管工具产物与前端文件预览增补

本节只增加交付与展示链，不改变 Root final、取消或权限结论。产品不再让模型或浏览器传任意文件路径：`workspace_patch` 的已批准结果先核对授权根、普通文件、postimage digest 和批准 Diff，再导入 Session-scoped media store。工具回执中的 `agentBlocks` 不进入 Provider 文本；它们由独立缓冲器交给最终 assistant message，或在 Pi Host 中交给后续 `room_post/room_commit`。Room Kernel 会再次核对 Session、media receipt、MIME、大小、digest 和 canonical content URL，伪造或跨 Session 文件块 fail closed。

前端只消费同一个受管 `file` Rich Block。Markdown、代码、统一/并排 Diff、图片和静态 HTML 由注册表选择 renderer；读取支持真实 AbortSignal、旧请求抑制和 8 项有界缓存。HTML 同时经过 DOM 清洗、空 iframe sandbox、无网络 CSP 与后端 `nosniff/sandbox/no-store` 响应头。这里参考 Cafe 的文件/Artifact 交互，但没有引入第二条协议；实现按 Pi 风格保持薄入口、明确状态 owner 和生命周期组合。

Pi 最低审核提交更新为 `58c7070348db40e0bf2442a66a1afe341a615e70`，来源固定为用户 fork `https://github.com/7155/pi.git`。构建门禁除 `tool-artifact-buffer.ts` 外，还固定 Provider Context epoch、压缩恢复、取消回执和收工修复四个生命周期源码面；该 Pi 提交已推送到 `7155/pi` 的 `codex/rag-ime-runtime-host`。产品仍未正式覆盖安装，因此本节状态仍是 `verified-not-installed`，不是发布声明。

## 2026-07-20 最终独立复审（待 P0 整改复测）

本节覆盖前三批结论；后文保留每一轮当时的事实，不能用旧结论替代当前结论。本轮不只重跑原七项审计测试，还检查了 live 产品链、正式 Pi handler、进程 kill gate、九类 surface receipt、Root 资源账本、前端 reducer，以及 `/private/tmp` staged Runtime 的清单和离线 E2E。

当前发现一个必须阻止合并放行的 P0：`cancelled_with_unknowns` 表示仍可能有后台执行，但前端把它算作 `isFinal=true`，随后显示“已结束/终态已确认”并隐藏停止按钮。这正是“看起来完成了但后台还可能在跑”。在该语义修复并复测前，第 5 项必须判为 ❌。

| 检查项 | 当前结论 | 最终复审 |
|---|---|---|
| 1. 路径唯一性 | ⚠️ 需关注 | managed create/dispatch/commit/finalize/control 均经 `KernelCommandBus`，RoomBinding 会拒绝 legacy intercom/mention/wake；但 Store 状态迁移仍是公开 Python API，普通 noRoom/legacy Room 仍保留独立执行方式。managed Root 的 owner 唯一，模块级误用仍靠约定。 |
| 2. 深度与资源限制 | ✅ 代码安全 | hop 12、depth 4、旧 budget 1000 之外，Root 现有 4 小时墙钟、输入/输出 Token、Dispatch 64、并发 4、Tool call/cost、retry 8、repair 4 的 Kernel 硬账本；入队原子 reserve，settle/cancel consume 或 release，调用者不能放宽。真实 Provider Token/费用口径仍是 canary 校准项，不改变代码 Gate 结论。 |
| 3. 取消传播 | ⚠️ 需关注 | accepted-before-ACK、retry/timer/outbox crash、unknown、profile revoke 均进入 durable cancel；Pi 返回 provider/tool/exec/retry/compaction/branch summary/timer/continuation/session 九类 typed receipt，`pendingTargets` 非空保持 cancelling。真实 Provider、命令子进程和正式 App 权限尚未逐 surface 故障注入。 |
| 4. 去重 | ✅ 安全（managed） | Root owner、Dispatch/Commit/Continuation/Post/command/cancel intent 均有 durable fence；unknown Dispatch 不重放；重复 settle/maintenance 不双开火。 |
| 5. isFinal | ❌ 危险 | 后端允许 unknown surface 形成 `cancelled_with_unknowns` terminal receipt；前端 reducer 又把它列入 final 集合，ControlPlane 因 `isFinal` 优先而遮住“仍有未知执行”并隐藏停止。这必须在最终复测前修复。 |
| 6. 失控恢复 | ⚠️ 需关注 | Runtime Host 已登记 PID/PGID/job/birth token，cancel timeout、orphan reconcile 和 admin panic 可 SIGKILL process group，PID 复用时 fail closed；但显式 `panic_kill()` 尚无产品管理 route，正式 App 的 `ps/killpg` 权限和真实进程树也未演练。 |

### 真实入口和边界结论

| 范围 | 结论 | 本轮证据 |
|---|---|---|
| live create -> dispatch -> post/complete -> finalize | ✅ | `RoomKernelServiceTests` 走真实 `AgentService`、command bus、capability tool、settle、公开 Post、需求证明和 terminal receipt；loopback HTTP 测试因当前沙箱禁止 bind 而跳过。 |
| 正式 Pi handler/pointer | ✅ 源码，⚠️ 发布产物 | product contract 固定 `692bb0e...` 和 `room.dispatch/room.cancel`；Pi worktree HEAD 精确匹配且 clean。staged manifest 的 Pi commit/hash 正确，但 `source.productCommit=7934bd5`，落后最新产品 `a4c12fc`，最终候选必须重建。 |
| staged Runtime E2E | ✅ 离线 staging | `/private/tmp/room-v2-pi-build-692bb0e8.wYXEHW` 经 manifest 全文件校验后以 `--no-activate` 安装到临时目录；manifest SHA-256 为 `54f580eb43494d95315357a0ca0c2daef4232d3c4b13d614aa0b175003447652`。离线 deterministic Provider 实跑得到 prompt -> followUp、protocol 2、9 个 terminated surface、`passed_not_installed`。 |
| kill gate | ⚠️ | unit tests证明 admin auth、PGID kill、orphan reconcile、PID reuse fence；Python cross-process tests在本沙箱因 `ps` 被拒绝而无法注册 birth token。这不是成功证据，正式签名 App 必须验证权限。 |
| Prompt/Skill/Profile/continuation | ✅ 代码链 | PromptPlan stable prefix/provider tail、唯一 native Skill load/restore、Root 固定 Profile/revoke cancel、A -> B -> A structured continuation 与三次 settle 兜底均有通过测试。 |
| Session/Post | ✅ | managed Session assistant正文、reasoning/progress/audio 不投影；只有显式 `room_post` 公开。 |
| Governance/Knowledge | ✅ 代码路由 | canonical `agent.governance.read` 与 `agent.knowledgeGovernance.read` 只返回投影；Knowledge caller 从 authenticated binding 派生，先做 owner/scope filter。正式 App 鉴权与大数据性能仍需 canary。 |
| ordinary noRoom | ✅ | 无 RoomBinding 时 PromptPlan/Skill/Profile/Knowledge/Kernel 都不会偷偷创建 managed side effect，原普通 Agent 模式保留。 |
| Voice | ✅ 范围清晰 | 用户语音输入仅在确认 Final Text 后复用文字入口。Room capability 没有 TTS、VoiceProfile、SpeechChunk、播放队列或自动播放；Agent/Room 发声仍明确 out-of-scope。 |

### 当前 production blockers

1. 修复 `cancelled_with_unknowns -> isFinal` P0，并证明未知 surface 时输入解锁、停止按钮、警告和管理员 kill 行为符合产品语义。
2. 用最新产品提交重新构建 staged Runtime；manifest 的 `source.productCommit`、contract hash、文件 hash 必须与最终候选一致。
3. 在正式安装路径验证 Runtime 指针、签名 App 的 `ps/killpg` 权限、Host process-group、cancel timeout、orphan reconcile 与 admin panic 管理入口。
4. 使用真实网络 Provider 对账 Token/Tool cost，并逐个注入九类 surface 卡死；不得只依赖 deterministic Provider。
5. 完成真实 HTTP、前端 desktop/mobile、named canary、rollback 和管理员审计演练。production 开关继续保持关闭，不得签发 release receipt。

本轮 staged 证据是 `passed_not_installed`，不是 installed、不是 online Provider、也不是 production E2E。

## 2026-07-20 unknown finality P0 修正

`unknown` 只表示“尚不能证明后台执行已停止”，绝不是一种可解锁输入的完成态。Kernel 现在把 unknown surface 保留在 durable cancel retry 与 `pendingTargets` 中，Root 可显示为 `cancelled_with_unknowns`，但不生成 terminal receipt；前端即使重连时读到历史 terminal receipt，也强制 `isFinal=false`，继续显示停止入口和红色管理员 kill/reconcile 提示。只有后续 reconcile 把全部 surface 更新为 `terminated`、`pendingTargets=0` 并生成同 generation terminal receipt，Root 才能进入真正 `cancelled` 和 final。

## 2026-07-20 独立复审结论

本轮从产品路由、`AgentService`、`KernelCommandBus`、持久化状态机、worker、正式 Pi handler 合同和前端终态语义重新走了一遍真实入口。旧的三个危险复现已经改成了正向安全不变量：accepted-before-ACK 会进入 durable cancel；直接 Store cancel 也会留下可重放 runtime effect；cancel 会关闭 Task 并生成同代 terminal receipt。历史章节保留原结论，不能再把那些旧复现当成当前行为。

生产仍不能放行。当前不是发现新的双开火 P0，而是确认还有四个必须在真实生产演练前补齐的硬 Gate：管理员 process-group kill、未确认 cancel target 清单、墙钟/Token/单 Root Dispatch 总数硬上限、真实 installed Pi + Provider + 前端 E2E。

| 检查项 | 当前结论 | 复审原因 |
|---|---|---|
| 1. 路径唯一性 | ⚠️ 需关注 | managed 产品 create/dispatch/commit/finalize/control 已收敛到 `KernelCommandBus`，`AgentService` 没有再直调状态迁移；但 Store 的迁移方法仍是公开 Python API，普通 legacy Room 也仍存在。模块边界靠约定而非 capability token 强制。 |
| 2. 深度限制 | ⚠️ 需关注 | `MAX_HOPS=12`、`MAX_DEPTH=4`、`MAX_BUDGET=1000` 不能被请求放大，A -> B -> A 和第 15 次互相触发会被 hop ceiling 截断；仍没有独立墙钟、Token 和单 Root Dispatch 总数上限。 |
| 3. 取消传播 | ⚠️ 需关注 | queued/running/provider/tool/process/retry/compaction/timer/continuation 均登记 AbortScope；unknown、panic、profile revoke 和 DB/RPC 崩溃窗都走 durable cancel outbox。连续 5 次 cancel 失败会 dead-letter，Root 正确停在 `cancelling` 且不伪造终态，但尚无进程级兜底和明确的未确认目标清单。 |
| 4. 去重 | ✅ 安全（managed） | Dispatch、Commit、Continuation、RoomPost、Kernel command 和 cancel intent 都有 durable idempotency fence；unknown effect 不会重放。这个结论只覆盖 managed Root，不替 legacy Room 背书。 |
| 5. isFinal 语义 | ✅ 安全（managed） | complete/cancel 只有 Root 终态、同 generation terminal receipt、quiescence 同时成立才 final；取消 dead-letter 时 Root 保持 `cancelling`，前端不会假解锁。 |
| 6. 失控恢复 | ⚠️ 需关注 | panic 会推进 generation fence 并为 unknown/running effect 建 durable cancel；但 Host 卡死时仍缺 PID/process-group kill，worker `close()` 超时后也会丢弃 thread 引用，管理员最终仍可能需要人工停进程。 |

### 真实链路复审

```text
POST kernel/create
  -> AgentService.create_room_kernel_root
  -> KernelCommandBus.create_root_task
  -> Root + Task 同事务

POST kernel/dispatch
  -> KernelCommandBus.dispatch
  -> Dispatch + outbox + AbortScope 同事务
  -> worker lease
  -> record runtime_effect=intent
  -> Pi room.dispatch
  -> matching dispatch_accepted receipt

Pi agent_settled + RoomCommit
  -> settle fence (Root/Dispatch/Session/generation/capability epoch)
  -> KernelCommandBus.commit
  -> RoomPost 或 child Dispatch 同事务
  -> quiescence + acceptance
  -> terminal receipt
```

accepted-before-ACK 的崩溃路径现在是：

```text
Pi 已 accepted -> Kernel 在 ACK 入库前崩溃
  -> lease 到期 -> Dispatch unknown（不重放）
  -> Root generation + 1 / cancelling
  -> durable cancel intent
  -> Pi room.cancel matching receipt
  -> Dispatch/AbortScope cancelled
  -> Task closed + Root terminal receipt
```

A -> B -> A 不再由自由文本 `@` 直接开火。Agent 只能在 `RoomCommit.continuation` 提交结构化 child Dispatch；Kernel 原子校验 parent、generation、hop/depth/budget 后才入队。第 13 hop 被拒绝，因此 15 个 Agent 连续互相 `@` 不会无限执行。缺失 Commit 会重试三次，然后 block，不会静默断链。

### Prompt、Skill、Profile 与上下文

| 面 | 当前结论 | 证据边界 |
|---|---|---|
| Prompt | ✅ 代码闭环 | managed Dispatch 固定六层稳定前缀，动态上下文只走 ProjectionJournal；需要真实 Provider cache/overflow 指标。 |
| Skill | ✅ 代码闭环 | 每阶段最多一个 native `SKILL.md`，load/restore receipt 与正文 hash 有 fence；需要真实目录升级和 compaction 中断演练。 |
| Profile | ✅ 代码闭环 | Root 固定 profile/version/bundle/definition/pointer/epoch；revoke 生成 durable managed cancel；需要多 Root 滚动与撤销演练。 |
| Session/Post | ✅ 安全 | Session 的模型正文、reasoning、progress、audio 不自动公开；只有显式 `room_post` 进入公共 Room。 |
| Voice | ✅ 不在链内 | 仅用户确认后的语音输入 Final Text 复用文字入口；没有 Agent/Room TTS、音频队列或自动播放。 |
| Pi 来源 | ✅ 已固定源码 | build 要求 Pi HEAD 包含 `692bb0e878772129766b9eb837a8caa57f48e0e7` 且 handler 提供 `room.dispatch/room.cancel`；本轮只验证 `/tmp` staged runtime，没有验证已安装运行时。 |

### 绕过路径复核

| 尝试绕过 | 结果 | 判定 |
|---|---|---|
| 直接调用 Store cancel | 仍会在同一事务写 runtime effect/cancel outbox；重启可继续投递，不再出现“DB cancelled、Pi 继续跑”。但公开方法没有 capability token，仍可能绕过 command audit record。 | ⚠️ |
| managed Session 走 legacy HTTP/intercom/mention/wake | canonical RoomBinding 会在进入 prompt 前拒绝；普通 Room 保留 legacy 行为，两种 owner 不能绑定同一 Root。 | ✅ |
| retry/timer/queued/running 时停止 | 都在 active state 与 AbortScope 内，target/root/panic 会取消并释放预算；cancel intent 幂等。 | ✅ |
| outbox delivery 崩溃 | runtime effect intent 先于 Pi RPC；ACK 丢失变 unknown 并 cancel，不重放 Dispatch。 | ✅ |
| unknown 后 panic | unknown effect 保留 session/root/generation target，panic/cancel 会补发 durable cancel；连续失败则 dead-letter 且保持非 final。 | ⚠️ |
| Profile revoke | revoke 先写 durable managed cancel outbox，maintenance 经 command bus 到 Kernel/Pi，重复 maintenance 不双发。 | ✅ |
| compaction 恢复 | 恢复精确 Skill load receipt 与 context epoch；catalog/body/epoch 改变时 fail closed，不重新猜 Skill。 | ✅ |
| continuation 重启/重复 settle | Commit 与 child Dispatch 同事务，重复 Commit 返回同 receipt；缺 Commit 仅重试三次再 block。 | ✅ |
| Provider/tool/process 卡死 | logical AbortScope 已登记，但没有每个 surface 的独立 runtime termination receipt，也没有 Host process-group kill。 | ⚠️ |

这里的“✅”表示当前 managed 代码路径的不变量成立，不代表 production release。任何 `⚠️` 都必须继续阻止 production receipt。

### 剩余 Gate 的可执行证据

`tests/test_room_v2_safety_exit_audit.py` 当前包含七项复审：三个旧危险复现对应的正向修复、不可放大的系统 ceiling、Pi handler commit/method pin，以及 cancel 连续失败进入 dead-letter 后保持非终态的 fail-closed 证明。最后一项同时说明为什么管理员 kill 仍不能删掉。

尚未有代码级硬限制的三个维度必须明确实现为 Kernel 自有字段，不能依赖 Prompt 或调用者：

1. `rootDeadlineAtMs`：入队、lease、settle、timer/continuation 恢复时都检查。
2. `tokenBudgetTotal/tokenUsed`：Provider receipt 原子累加，超限进入 cancel/block。
3. `maxDispatchesTotal/dispatchesCreated`：每次 continuation 入队原子占位，防止零成本或极小成本 Dispatch 放大。

管理员恢复还需：Host PID/process-group ownership、kill receipt、每个 Abort surface 的独立终止回执、`unconfirmedTargets[]` 管理接口，以及 worker close 后仍 alive 的 unhealthy 状态。完成这些之前，release receipt 必须继续是 `staged_not_installed`，production rollout 保持关闭。

本轮验证：Kernel/worker/audit 25 项、service 16 项通过且 1 项因沙箱禁止 loopback bind 跳过、Profile/Prompt 17 项、Skill 12 项，合计 70 项通过、1 项环境跳过。真实 HTTP loopback、installed runtime 和网络 Provider 不在本轮证据范围内。

## 2026-07-20 第三批强制 Gate 整改（生产仍关闭）

本批把第二批仍标记为缺失的资源与进程终止边界落到真实 Kernel/Pi 链。结论仍是 `staged_not_installed`，不签发 production release receipt。

| 强制 Gate | 已落地机制 | 仍需生产演练的边界 |
|---|---|---|
| Root 硬资源上限 | migration 0091 为每个 Root 固定墙钟、输入/输出 Token、Dispatch、并发、Tool call/cost、retry、repair 上限；Dispatch 在同一事务 reserve，Commit/cancel consume 或 release。请求只能消费，不能放宽系统上限。 | Provider 的实际 Token/成本口径仍需真实账单对账；超限后的长时间压力与故障注入仍需 canary。 |
| Runtime Host Kill Gate | migration 0092 持久化 Host PID、PGID、job identity、进程 birth token 和 kill receipt；正常 cancel/abort 先协作，超时后 SIGKILL 整个 process group；重启先 reconcile orphan；PID 身份不符时 fail closed 为 unknown，绝不误杀复用 PID。 | macOS 正式安装进程树、管理员 panic、崩溃重启和权限边界仍需隔离 canary。 |
| 九类终止证明 | Provider、tool、exec、retry、compaction、branch summary、timer、continuation、session 各返回 typed termination receipt。`pendingTargets` 不为空时 Root 保持 cancelling；unknown 只能形成显式 `cancelled_with_unknowns`，不能伪装成干净完成。 | 真实 Provider/命令子进程需要逐 surface 故障注入，验证无未注册执行。 |
| 治理/知识读模型 | 控制中心改读 canonical `agent.governance.read` 与 `agent.knowledgeGovernance.read`；后端只返回治理投影，不把签名/密钥暴露给浏览器。 | 正式 App 的鉴权、空态、错误态与大量数据性能仍需 UI canary。 |
| 正式 Pi 构建 | 正式源码提交 `692bb0e878772129766b9eb837a8caa57f48e0e7`；本地无网络 deterministic Provider 通过真实 Session/tool loop/cancel；构建只写 `/tmp`，smoke 确认 protocol v2 与 cancellation primitives。 | 未覆盖正式安装指针，未启用网络 Provider，未改变生产开关。 |

本批后剩余风险不再是“有没有总电闸”，而是 production 环境的实证：正式安装包的进程权限、Provider 计量偏差、长链压力、管理员操作审计与回滚演练。任何未知 surface 都必须继续对用户可见，不能由前端 `isFinal` 隐藏。

## 2026-07-20 第二批强制 Gate 整改（生产仍关闭）

本节继续追加整改证据，不修改下文原始审计。Prompt、Skill、Profile、continuation 和 AbortScope 已从“设计/影子模型”进入 managed Room 的真实执行链；这仍然不是生产放行声明。

| 强制 Gate | 已落地机制 | 仍需生产演练的边界 |
|---|---|---|
| Collaboration Profile | Root 首次 managed Dispatch 时固定 `profileId/version/bundleHash/definitionHash/pointerRevision/guardEpoch`；后续请求不能热切换；撤销会取消仍引用该版本的活跃 Root。Prompt compiler 接收真实 manifest，不再使用 `profile=None`。 | 需要签名 Profile 激活、滚动升级和撤销中的真实多 Root 演练。 |
| 六层 PromptPlan | 1-5 层按固定顺序生成 cache-stable system prompt；第 6 层只由 ProjectionJournal 形成 append-only provider tail。RoomBinding 下 legacy system-prompt producer 明确禁用，Pi `session.open` 返回 provider receipt 后才封存投影。 | 需要真实 Provider 的 cache 命中、上下文上限和断线恢复指标。 |
| native Skill | 每阶段最多一个 required `SKILL.md`；Pi 原生 search/load 做唯一匹配和正文 hash 校验，返回 load receipt；compaction 恢复原 receipt，恢复失败 fail closed；`nextCandidates` 只读，不自动派发。 | 需要真实 Skill 目录升级、撤销和 compaction 中断演练。 |
| deterministic continuation | `RoomCommit` 显式决定 `dispatch/wait/block/complete/post`；child Dispatch 与父 Commit 在同一事务写入并预留预算。settle 缺 Commit 最多重试 3 次，随后阻塞而不是静默断链。 | 需要长链、并发 settle 和 worker 重启压力测试。 |
| 深度与互相触发 | continuation 复用 Kernel 的 `MAX_HOPS=12`、`MAX_DEPTH=4`、`MAX_BUDGET=1000`，测试覆盖 A -> B -> A 以及第 13 hop/15 次互相触发被拒绝。 | 还需墙钟、Token 和单 Root Dispatch 总数的独立硬上限。 |
| Root AbortScope | Dispatch 入队即注册 queued/running/provider/tool/process/retry/compaction/timer/continuation 九个 surface；取消通过 durable outbox，只有 Pi 匹配 cancel receipt 后进入 cancelled。 | 当前仍缺 Host PID/process-group 管理员 kill、每个 surface 的独立终止回执与未确认执行清单，因此 panic 不能判定完全闭环。 |

Pi 真实 handler 在第二批固定到独立源码提交 `f842dfbd0cd14e80618371b888a3149c320905c5`，包含 live Prompt/Skill、compaction restore 与 fail-closed 校验；第三批最低审核 commit 已更新为 `692bb0e878772129766b9eb837a8caa57f48e0e7`。产品仍未覆盖本机安装、未打开 production rollout、未签发 release receipt。

## 2026-07-20 P0 整改进展（生产仍关闭）

本节是对原始审计的追加记录；下文保留 `feea050` 基线结论，便于复盘“发现了什么、如何修复”，不改写历史证据。当前已经完成首批 P0 整改，但 **不能据此签发 production release receipt**：Prompt、Skill、Profile、continuation、完整 AbortScope 和真实生产演练仍是强制 Gate。

| 原阻塞项 | 当前整改 | 新的不变量/证据 |
|---|---|---|
| 多条产品执行路径 | 已增加 `KernelCommandBus`；create/dispatch/control/commit/finalize/cancel 的产品服务入口经同一总线，Store 只保留持久化状态机职责。 | `AgentService` 不再直接调用 create/enqueue/commit/finalize/cancel 状态迁移。 |
| Root 与首 Task 分裂写入 | 已增加原子 `create_root_with_task()`，两者在同一 `BEGIN IMMEDIATE` 事务创建；身份冲突 fail closed。 | Task 冲突时 Root 一并回滚，重复的完全相同请求可重放。 |
| accepted-before-ACK 幽灵执行 | Dispatch 调 Pi 前先写 `runtime_effect=intent`；lease 过期转 unknown 后提升 Root generation，并创建 durable cancel intent。 | reconcile 不重放不明 Dispatch，而是补发 `room.cancel`，收到匹配回执才结束。 |
| cancel DB/RPC 崩溃窗口 | 新增 `room_kernel_cancel_outbox`，含 lease、retry、dead-letter 和 runtime receipt；root/target/panic 共享该队列。 | 用户停止、直接 Store cancel、panic 和 unknown reconciliation 都可恢复投递。 |
| cancel 没有终态 | Root cancel 先关闭全部开放 Task；所有 root-scoped cancel intent 回执齐全后才写唯一 terminal receipt 并进入 `cancelled`。 | 前端只能由 Root + 同 generation terminal receipt 解锁。 |
| 调用方可无限放大限制 | Kernel 增加不可由请求绕过的系统 ceiling：`MAX_HOPS=12`、`MAX_DEPTH=4`、`MAX_BUDGET=1000`。 | 请求只能在系统上限内向下收紧。 |
| 产品没有 create/dispatch/finalize | 已补齐三条 HTTP/Control route 和服务方法；managed cohort 入口通过 command bus。 | route policy、后端服务与控制中心 canonical path 均有测试。 |
| Pi handler 无来源证明 | 产品 integration 增加 typed adapter 和来源契约；managed runtime manifest 固定 required methods、contract hash、最低已审查 Pi commit，并在 build 时验证 handler。 | `60913d3`；只生成 `/tmp` staging payload，未覆盖本机安装。 |
| Session 正文污染 Room | managed `cohort/kernel_only` 且存在 canonical SessionBinding 时，`message_completed` 不再投影为公开 `participant_message`。 | 真实 AgentService 测试验证私有文本不进入 Room timeline/snapshot。 |

仍未完成的强制项：

1. 六层 PromptPlan 成为真实 Room Provider payload 的唯一 instruction producer，并保持稳定缓存前缀。
2. native `SKILL.md`、load/restore receipt 与 compaction hook 接入真实 Pi。
3. Collaboration Profile 固定到 Root/Dispatch/Prompt compile，而不是 `profile=None`。
4. 结构化 continuation queue 与确定性 settle 规则真正完成 A -> B -> A；模型只能提议，Kernel 决定是否交接。
5. Root AbortScope 覆盖模型、工具、命令子进程、retry/timer、follow-up、compaction，并有管理员进程级 kill 与未确认目标清单。
6. 真实 production-mode E2E、回滚演练和前端全链验证；完成前 rollout 必须保持关闭。

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
