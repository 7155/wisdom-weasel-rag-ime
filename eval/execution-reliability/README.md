# Agent 执行故障矩阵与 Worker 演进路线

日期：2026-09-06。关联 [O1](../../OUTCOMES.md#o1--long-running-session)、
[O3](../../OUTCOMES.md#o3--tool-agent-capacity)。

本轮先验证故障，再补已有执行层的缺口。结果属于源码、真实进程、SQLite、
回环网络和原生沙箱实验；不代表分布式部署、真实 Provider 或已安装应用验收。
当前统一矩阵 **45/45 通过，0 失败、0 错误、0 跳过**，运行前后源码摘要一致。

## 用户确认的要求

| ID | 要求 |
| --- | --- |
| R1 | 逻辑任务与执行尝试分开，保留多次尝试的身份和记录 |
| R2 | 显式重复请求不能随意产生重复业务动作 |
| R3 | 心跳、租约确定当前有权执行与提交结果的 Worker |
| R4 | 旧 Worker 的迟到结果不能覆盖新尝试 |
| R5 | 外部写入结果不明时查询、对账或显式交接，不能盲目重放 |
| R6 | 先验证重启、断网、重复提交、取消、越界访问，再确定 Worker 改动 |
| R7 | Trace Agent 保留自举所需全权限；Room 保留广泛权限，不增加逐 Tool 人工或模型审批，不因此中断工作 |

本轮交付边界是可在本机复现的执行可靠性改造。R1 验证独立尝试和前驱记录；
R2 验证显式去重；R3/R4 增加两个真实宿主进程之间的租约、心跳和过期所有者
写回保护；R5 验证未知状态不盲目重放并交回父 Session；R6 覆盖五类故障；
R7 保持现有全权限和免逐 Tool 审批契约。
跨机器传输/部署、企业多人身份、任意外部系统的自动对账属于后续发展路线，
这里不把本机验证当作这些能力已经实现的证明。

R7 是本轮补充的硬约束。Worker 拆进程用于执行、回收和恢复，权限继续由现有
Session/Room 执行上下文决定。受限模式的越界拒绝、全权限模式的允许访问分别验收。
全权限访问成功本身不是隔离失败。

Pi 继续独占 Session、Agent/Tool 循环、上下文、Steer、Stop 和恢复。
Room 保持 Session 的轻量组合，不增加第二套 Agent 内核。

## 故障矩阵

| ID | 实际实验与观察 | 证明边界 |
| --- | --- | --- |
| F1 重启 | SIGKILL 测试宿主，重建服务后接续同一 PID 的后台任务，效果仅写一次；杀掉 Worker 且缺少退出回执时返回 `orphaned`，不重跑 | 真实宿主/Worker 进程；不是跨机器接管 |
| F2 断连 | 回环 HTTP 在效果与终态落库后断开 TCP，相同请求键返回原 Job；另在效果写入、终态提交前 SIGKILL，重启为 `interrupted`，不重复写入 | HTTP 是测试适配器，生命周期使用真实 Lab Application/Store |
| F3 重复提交 | Lab 四个并发同键请求只有一个 Job；后台同键并发仅一个进程；同键异输入冲突；不同 Session 独立；Gateway 重放为 `mutationApplied=false` | 要求调用方复用显式键；另验证 migration 0192 保留旧行并约束同 Session 显式键 |
| F1/F4 所有者接管 | 暂停 A 宿主，B 在租约到期后接管同一命令进程；恢复 A 后七类旧操作被拒绝，命令效果一次；无人接管时 A 可原子续租继续 | 两个同机独立宿主，单机 SQLite；暂停点明确位于数据库事务之外 |
| F4 取消 | 超时或显式终止时，组长退出不能留下忽略 TERM 的子进程写入；已回收 handle 不再发信号；Room 拒绝迟到事件、只认领一次取消终态、不启动迟到 wake | 真实进程树与 Room 契约；不承诺阻止全权限程序主动脱离进程组 |
| F5a 受限越界 | 真实 workspace sandbox 允许授权目录读取，拒绝测试用相邻目录读取；只读执行仅可写命令临时目录 | 原生沙箱；不可用则记 skipped，不能算通过 |
| F5b 权限保持 | 全权限命令保留环境与系统/网络能力；Room 活动 dispatch 无逐 Tool 提示；Trace Skill 保留直接修复权限 | 执行/策略/Skill 契约；Trace 两项是静态检查，未调用真实 Trace Agent |

所有副作用发生在测试创建的临时目录或 SQLite。效果表没有去重唯一约束，
重复执行会留下可计数记录。没有重启已安装产品或调用配置的 Provider。

## 本轮修复

1. **回收残留进程组。** `WorkspaceHarness._terminate_group` 原来仅在组长等待
   超时时才发 KILL；组长收到 TERM 退出后，忽略 TERM 的后代仍能写入。
   两条先红回归复现并转绿。复核后增加非回收式退出观察：持有 Popen 的
   waitpid 锁，用 POSIX `waitid(WNOWAIT)` 保持组长 PID 未被回收，先清理专属
   进程组，再 wait。已经回收的 handle 不再发送信号，避免使用复用的 PID。
   这依赖当前 CPython/POSIX 执行宿主；没有改变权限 profile。
2. **已有后台 Worker 增加显式启动身份。** `AgentBackgroundJobService.start`
   增加可选 `idempotency_key`，由 `workspace_job.start.idempotencyKey` 传入。
   migration `0192` 追加列及非空 `(session_id, idempotency_key)` 唯一索引。
   在 `BEGIN IMMEDIATE` 中先查旧记录再接纳，避免并发重复 spawn。
3. **把身份传过 Gateway。** 稳定键进入原有 preview、摘要、执行参数。
   重放返回原 Job、`replayed=true`、`mutationApplied=false`。
   复用已有内部授权/审计路径，没有增加用户提示或 Room 审批步骤。
4. **取消控制不等待 Artifact。** `abort` 与 `cancel_causal` 使用主表快照受理
   取消和投递结果，不同步展开或刷新 Artifact，也不在取消回执前执行 Artifact
   回收。运行中的取消先送达 Pi；无应答时先停止自有 Runtime，再补监督记录。
   共享 Runtime 仍只取消对应子 Session。主表记录、结果唯一性和原有权限不变。
   三个先红测试分别持有真实 Artifact mutex，覆盖 queued 取消回执、运行中取消
   送达、忽略取消后的强制停止。锁释放后验证只有一个终态和一个父 Session 结果。
5. **补齐有启动回执的崩溃窗口。** 后台命令通过内部 `agent_background_launch`
   launcher 启动。它先持久化自己的 PID、出生身份和命令摘要，等待现有 owner
   将身份绑定 queued 记录后才 `exec` 原来的 sandbox/zsh 命令。重启时验证回执，
   接续同一 PID，不创建替代执行。记录已进入 cancelling 则终止等待进程、不放行。
   新协议不增加数据库迁移、用户操作或审批；使用原有环境和 sandbox argv。
   正常启动回执不等待新的用户确认。内部等待最长 60 秒，未放行则不执行命令。
6. **为现有后台 Worker 补监督租约。** migration `0193` 保存 owner ID、进程
   出生身份、递增 generation、心跳时间和同宿主单调时钟期限。新任务与初始
   租约同事务接纳；备用宿主只观察，租约到期或证实旧进程已死亡后才接管。
   正常关闭主动释放。命令无日志时仍续心跳，不能用日志更新时间代替存活证明。
   generation 代表监督权转移，不代表命令又执行了一次。
7. **拒绝旧所有者的写回和清理。** 结果、进度、超时、启动放行、终止和临时
   文件回收均验证 owner/generation；验证与对应变更使用同一 SQLite 写事务。
   失去租约后监控线程脱离，不终止新 owner 接续的进程。取消意图可以从另一
   控制宿主提交，由当前 owner 执行；最终状态在事务内重新读取取消意图。
   进程创建本身不持有数据库写锁，用户命令仍须经过有租约校验的内部放行。

租约六项实测：活跃 owner 排他、无输出心跳、正常关闭后的自动接管、备用宿主
提交取消、真实 SIGSTOP/SIGCONT 接管、无人接管时暂停恢复。旧 A 的七个入口
（进度、失败终态、正式结果、超时、放行、终止、清理）均拒绝代次过期的操作。
续租只允许 owner/generation 仍未变化的宿主恢复；B 已接管时，A 无法续回旧租约。
SQLite 事务内暂停属于存储锁故障，不宣称租约能绕过锁持有者继续提交。

Task/Attempt 另用真实 Delegation Store/Coordinator、测试 Pi Runtime 验证：
通过现有 retry 控制生成第二次尝试，逻辑 node ID 保持，attempt ID 变化，
predecessor 指向第一次；重复控制不创建第三次。旧尝试的迟到成功不能覆盖原失败
或第二次结果。这个测试没有新增重试内核，也没有调用配置的 Provider。

启动协议六项实测：两个真实 SIGKILL 窗口（spawn 后/身份落库前，身份落库后/
放行前）、预先持久化的取消、摘要不匹配、放行 I/O 失败、受限命令仍被原生沙箱
拒绝越界。回执损坏、缺失或进程身份失效继续报告 unknown/orphaned，不盲重放；
特别是 launcher 尚未来得及持久化有效回执的极早崩溃，不宣称已经自动恢复。
这里只证明单宿主进程崩溃恢复，不推导为断电持久性或跨机器接管。

取消回执保持 `requested` / `terminated` 的真实区别；Artifact 延迟时不提前宣称
已完成终态归档。这里隔离的是辅助 Artifact I/O，主数据库自身的全局写锁、以及
Runtime RPC 本身长期无应答需要按各自 owner 继续验证，不能推导为任意故障下零延迟。

执行摘要绑定 command、cwd、workspace roots、timeout、network、read-only、
unrestricted。同键异输入报冲突。展示 label、新生成的 approval ID 不进入执行摘要。

已有 queued、终态、orphaned 记录均只返回，不因重试再次启动。无键调用保留
旧行为，新的独立业务任务使用新键。这是有边界的 admission 去重，
不是任意外部系统的 exactly-once 保证。

## 可复现验证

在仓库根目录执行：

```bash
python3 scripts/check_agent_execution_fault_matrix.py
```

可用 `--output-root` 指定尚不存在的仓库外目录。输出逐条结果、各组日志、
Python/平台、前后源码 SHA-256 和未验证项。失败、错误、跳过或运行期间源码
变化均返回非零；耗时仅作诊断。最终运行结果见本文件末尾。

相关回归与基线分开记录，不与矩阵重复相加：

- workspace、vertical sandbox、background jobs：最终相关回归 **60/60**。
- 启动协议接入后，后台服务/幂等/宿主崩溃/Gateway 相关回归 **28/28**；
  后续异常回收细化又通过 **2/2**，已有进程组身份回归 **3/3**。
- Gateway 全模块 **96/96**；数据库 migration 全模块 **23/23**。
- 租约最终回归：后台服务 19、租约 6、后台去重 6、migration 23，共 **54/54**。
- 本轮 Delegation 全模块 **55/55**；随后对强制停止顺序的调整通过相关 **5/5**
  （含三个锁竞争测试与两个预算取消测试）；生命周期取消全模块 **12/12**。
- Room turn registry 基线 **22/22**，Partner restart recovery **22/22**。
- Lab Trial execution/store 回归 **24/24**。
- 已有 `scripts/eval_paw_execution_reliability.py` 只读复用：8 场景 × 3 次
  **24/24**，重复效果 0；其 ACK 丢失和重建为进程内模拟。
- Project harness、import boundaries、route ownership 检查通过。
- Repository release 检查未通过：其他工作文档含机器路径，工作树仍有 dirty
  work，发布状态声明 blocked，manifest / foreground acceptance 尚未就绪；
  安装与推送状态另以安装回执和 Git 远端记录验证。

既有 delegation 基线同时启动 12 个独立测试进程时出现时序失败：四个历史失败
逐项重跑 4/4、四进程并行 4/4，但再次 12 进程压力仍有 3 个失败。每个测试使用
自己的临时 DB，压力放大初始化、CPU/磁盘调度和测试内部 SQLite 竞争，
不能解释成 12 个进程共享一个 DB。另有等待栈位于
`abort → _schedule_pending_result_contexts → get_batch → Artifact snapshot`。
这是初始基线的未完成记录；本轮补齐单进程全模块 **55/55**，并通过三个针对
Artifact 等待位置的故障回归。没有靠延长断言时间掩盖结果，也没有把单进程
通过外推成 12 进程压力已稳定。

## 下一阶段：沿现有 Worker 边界推进

源码已有 PiRuntimeHostClient 的独立宿主进程、WorkspaceHarness 的后台进程。
AgentBackgroundJobService 持久化 PID、出生身份、日志、退出回执，支持宿主
重建后接续。Delegation 已有 logical_node_id、attempt_id、attempt_number、
predecessor_attempt_id、owner_run_id；下一步补这些身份跨宿主执行的闭环。

| 顺序 | 真实缺口 | 验收标准 |
| --- | --- | --- |
| 1（已补有效启动回执） | spawn 与 PID 落库/放行之间的恢复 | 两个精确 SIGKILL 窗口接续同一进程且效果一次；有效回执生成前仍保留未知状态 |
| 2（已补） | Delegation 取消同步等待 Artifact | 持有真实 Artifact mutex 时，queued 回执、取消送达、自有 Runtime 强制停止均通过；释放后结果唯一 |
| 3（已补同机协议） | 跨机器的传输与持久化服务 | 同机 A/B 接管已验证；远端仍需服务端时间、任务接口和独立节点部署验证 |
| 4 | 通用外部写入缺少对账适配器 | 下游支持幂等键则沿用，支持查询则回读，无法确认则保留未知状态并显式交接 |
| 5 | Task/Attempt/结果接管跨宿主串联 | 同一任务保留多次尝试，只接受当前尝试的结果，历史证据不丢失 |

先在同机多个进程验证通信，再部署两个节点。远端 Worker 通过服务访问任务状态，
不能以多机直接共享 SQLite 文件替代分布式存储设计。持久化后台路径的复杂后代
清理也需要独立验证；本轮真实子进程树测试覆盖 WorkspaceHarness 路径。

启动协议和同机多个执行 owner 的租约竞争已接入现有 owner/harness。远端阶段
复用 Task/Attempt、幂等键和 generation 契约，经控制服务领取任务、续租和提交，
把工作目录产物改为明确上传/下载；不能把当前依赖本机 PID 和单调时钟的实现
直接放到共享磁盘上就宣称完成跨机器接管。

租约和 fencing 约束的是执行所有者。Trace 自举权限与 Room 免审批体验继续保留；
多人 Room、项目身份和 App 打包在这条可靠执行链上继续组合。

## 外部调研与项目取舍

- AWS 建议调用方提供显式请求标识，并区分同键不同参数；本轮使用这一设计，
  不按相同文本猜测用户是否发起了新任务。
  [Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
- Temporal 区分一次 Activity Execution 与其中的多次 Task Execution，并使用
  超时、心跳和取消协议。这里借鉴执行生命周期边界，没有为 PAW 引入 Temporal
  或替换 Pi。
  [Activity Execution](https://docs.temporal.io/activity-execution)
- Cursor Cloud Agent 通过组织安装的 Git App 与触发用户的可访问范围取得代码
  权限。这支持多人项目身份的设计参考；从中推导 PAW 的项目授权模型，不等于
  当前 PAW 已实现企业多租户，更不要求减少 Trace 的自举权限。
  [Security overview](https://cursor.com/docs/cloud-agent/security)

## 文件与交付边界

生产改动涉及 agent_workspace 的进程终止、agent_background_jobs 的启动
去重、租约与恢复，追加 migration 0192/0193、agent_tools 的 workspace_job 幂等字段传递，以及
agent_delegation 的取消控制/辅助 Artifact 分离。
另新增可信后台启动 launcher、租约模块、故障测试及进程 fixture
和矩阵脚本。迁移测试仅推进 latest
版本预期。agent_tools 中已有 Pi Package 等无关 dirty work 保留。

提交仅包含本轮补丁与可复现测试所需依赖；不修改已应用的历史 migration。
安装与 Git 推送分别验证，不以源码测试代替运行中的服务验收。

## 最终统一运行

矩阵各组：Task/Attempt 与重试/迟到结果 3、重启与启动协议 8、真实网络/崩溃/并发 3、
后台去重/Gateway/迁移 7、租约接管 6、取消/迟到结果/回收身份/Artifact 竞争 10、
受限原生沙箱 2、全权限与 Room/Trace 6，合计 **45/45 通过**。
独立审查最初指出进程回收代际和 fixture 清理顺序问题；修复后复核无 P1/P2
阻塞项；该独立审查对应首轮进程/启动去重改动，本轮取消改动由主 Agent 源码核对
及故障回归验收。启动协议同样由主 Agent 核对，并完成真实进程故障回归。
跨机器部署、极早启动未知状态与任意外部写入自动对账仍保留上文的边界。
