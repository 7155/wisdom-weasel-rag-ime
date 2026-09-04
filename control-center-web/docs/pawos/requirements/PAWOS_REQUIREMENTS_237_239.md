# PAWOS 用户需求账本 · UR-237–UR-239

> 导航：[UR-236](PAWOS_REQUIREMENTS_236_236.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-240–UR-241](PAWOS_REQUIREMENTS_240_241.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

## User Requirement Ledger

### UR-237 — 同一轮消息必须立即、唯一且按真实终态收敛

- **状态 / 优先级：** `current / P0 conversation correctness`
- **需求：** 首条和后续用户消息点击发送后立即显示，且在 optimistic、HTTP admission、
  SSE、recent/full snapshot、持久 transcript 与刷新恢复之间始终只保留一条公开用户消息。
  同一轮必须共享并可追踪 `clientMessageId`、`turnId` 与真实终态。
- **必须保留：** Provider/Tool 真正失败、用户 Stop 和未执行的 admission 必须诚实显示，输入
  在可安全重发时恢复；刷新后仍能回到同一对话实例和同一轮证据。
- **禁止：** 不得因早到 idle snapshot、目录刷新、临时 SSE 断线或 ID 丢失先显示“本轮未完成”，
  随后又把迟到答案渲染成另一轮；不得用文本/时间近似长期代替稳定身份。
- **验收：** 首发、已知 Session 发送、断线重连、同 cursor/gap 修复、刷新恢复、冲突重发和
  真实失败均有回归；真实 PAWOS 前台连续发送与刷新后，每个 case 只有一个用户锚点、一个
  终态和零幽灵失败卡。
- **来源：** 导出 Session 条目 `b2d77cd2`、`fd98baec`、`89036c3f`、`14c46013`、
  `9d78fc81`、`95cff8dc`、`a2f8c69f`、`7548ab40`、`734f84ed`、`55bd6e3c`、
  `9b73a55c`、`3e018899`、`d0466ad0`、`6cb9499c`；当前 Goal 中“设置为goal……”与截图。逐字原文见
  [用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md#2026-09-03--对话前后端稳定性与恢复-goal)。

### UR-238 — HTTP、SSE、Runtime 与持久会话必须形成稳健的单一收敛协议

- **状态 / 优先级：** `current / P0 transport and recovery stability`
- **需求：** HTTP 负责一次可辨认的 admission 回执，SSE 负责增量事件，snapshot 负责缺口
  修复，durable transcript 负责刷新恢复；四者以稳定身份和单调 cursor 对账，而不是各自猜
  测运行状态。`snapshot_required`、`Last-Event-ID`、`resumeToken`、sequence gap、丢失终态、
  reconnect 和进程恢复均必须可重复收敛。
- **必须保留：** 真正的数据损坏、越权和仍有副作用的不确定 admission 继续 fail closed；
  其余重复目录检查、旧快照门禁、虚构终态和阻塞发送的非权威校验应从热路径移除。
- **禁止：** 不得把 transient recovery control 当 durable cursor；不得让一个窗口回调异常断开
  其他窗口；不得因 list/snapshot 辅助读取失败阻塞已有 Session 的 prompt authority。
- **验收：** 注入断流、重连、回放缺口、equal-cursor snapshot、丢失 `agent_settled` 与 Host
  重启后，下一轮仍可发送，且前端与 Runtime 的 active/idle/failed 状态一致。
- **来源：** 导出 Session 条目 `b2d77cd2`、`fd98baec`、`9d78fc81`、`95cff8dc`、
  `7548ab40`、`734f84ed`、`f568f27e`、`42e619f7`、`65e5eae0`、`dcb427e6`、
  `1963d0d6`；当前 Goal 中“是不是sse不够稳健啊”“加强前后端稳定性”。

### UR-239 — 冲突与 Memory 故障必须隔离，旧错误路径不得回流

- **状态 / 优先级：** `current / P0 fault isolation and regression hygiene`
- **需求：** command fingerprint/turn conflict 只影响对应 admission；自动 Memory timeout、晚到
  settlement、数据库打开失败或清理任务失败只进入 Memory 自己的恢复与审计面，不得把普通
  对话标失败、归档、找不到实例或自动重复发送。
- **删除语义：** 修复后应删除或旁路已被证明错误且无现行消费者的热路径代码、重复状态、
  旧 fallback 与投影；仍被 provisional deep-link、历史 transcript 或确定性 recovery 使用的
  路径不得为了“看起来干净”误删，其消费者和保留理由必须记录。
- **验收：** command conflict 恢复输入且不创建伪失败轮；Memory 故障注入后普通 busy/idle
  Session 及其 transcript 不变；同一 case 重放不会恢复已删除的错误行为。实现、原因、diff、
  红绿测试和前台结果全部可追踪。
- **来源：** 导出 Session 条目 `d6c2be6e`、`691bc8c6`、`1963d0d6`；当前 Goal 中用户粘贴的
  `Message rendering regression` 未完成清单与“并行完成”。

## 本轮执行约束（不新增产品能力）

- 当前修复、实现与审计统一使用 **Sol Max**；**Luna Max 只用于完成实现后的模型兼容或真实
  任务对照测试**。这条以“你的subagent都用sol”“你干活都用好的，测试的时候才测试luan
  max”修正此前“luan也可以继续了”的临时恢复授权。
- 用户授权 Sol subagent 并行写入；主 Session 仍负责文件边界、冲突处理、集成、真实验收和
  单一最终结论。来源原话：“并行完成”“他们可以写，sol没问题”。
- “都恢复了”只表示当时 Provider 服务恢复，是外部状态更新，不是产品完成证据。

## 来源覆盖与边界

- 命名导出：`omp-session-2026-09-03T14-55-34-850Z_01a067c4-a1c2-7674-9691-8fc5c8be6fdc.html`；
  仅提取 active path 的直接用户消息，嵌套 Agent 文本、Tool 输出和屏幕里的 TODO 不冒充用户
  原话。条目 ID 与 UTC 时间原样保留在逐字证据中。
- 当前 Goal thread：`01a0653f-8a73-7c50-880b-53f729cce993`。当前界面未向文档写入器提供
  每条新消息的稳定 ID，因此不伪造；以 Goal thread、消息顺序、采集时间和逐字原文作为
  临时 sourceRef，后续只追加真实 ID 映射。
- CodingTo 是用户要求检查的参考实现，不是 PAW 已采用的依赖或完成证据。
- 这三条补强既有 `UR-216`、`UR-219`、`UR-220`、`UR-223`、`UR-224`、`UR-234`–`UR-236`，
  不把此前任何未评估要求自动改成完成。

## 继续阅读 / 编辑

- 下一份：[UR-240–UR-241](PAWOS_REQUIREMENTS_240_241.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
