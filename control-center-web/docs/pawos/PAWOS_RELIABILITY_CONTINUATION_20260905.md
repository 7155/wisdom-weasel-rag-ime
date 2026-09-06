# PAWOS 可靠性续接：原因、改法与验证（2026-09-05）

## User Requirement Ledger / 用户需求账本

本记录接续任务 `01a070e8-ba60-7390-a628-8bef2d3c2e1b`，需求原话、消息 ID、修正关系和来源覆盖以 [UR-260–UR-264](requirements/PAWOS_REQUIREMENTS_260_264.md) 为准。`current` 表示当前控制要求，不表示已经验收。

| 需求 | 当前控制含义及原话 | 本文对应内容与验收约束 |
| --- | --- | --- |
| UR-260 · current | “全部，整个os的ui都需要优化，我们讨论一下如何加动效，比如现在背景简单，完全可以加一个伪3d的星际，好看的那种”；用户选择“浅色宇宙，通透有纵深（推荐）” | 全 OS 视觉与动效方向继续保留；概念图不能代替实际 App 优化。先解除登录、窗口和同步障碍。 |
| UR-261 · current | “登录还没解决，我得登录来继续完成面试的那些数值” | 登录、诊断调用、正式评测分别留证；恢复登录不等于四场景数字全部完成。 |
| UR-262 · current | “协同模式行星没有弹出窗口”；“需要运行的行星都弹出”；“一个窗口不够” | 实际执行伙伴独立出现、同时保留、增量恢复；旧成员身份不能冒充本轮运行。 |
| UR-263 · current | “前后端同步问题需要优化。Runtime 未及时返回轨迹快照；对话不受影响。请稍后重新读取。**重新读取**” | 处理首次读取和恢复链路，验证消息、控制回复及轨迹各自的结果。用户转贴的“对话不受影响”是界面提示，不是已证明的影响边界。 |
| UR-264 · current | “就是得记录文档，怎么改的，为什么这么改，都要有逻辑” | 每项记录现象、证据、原因、改动、理由、验证及未完成边界。不得从源码测试推断已安装或前台已验收。 |

主记录负责人：当前 Session 的主 Agent。支持 Agent 分别负责 OAuth/Runtime、Room UI、评测录入；主 Agent 负责核对、集成、安装和关闭记录。本文不是 Runtime 状态源，当前运行状态须读取实际进程和持久化事件。

本记录使用 `<PAW_STORAGE>` 表示本机外置工作存储根，`<LOCAL_LOG_DIR>` 表示本次本地日志目录。精确路径留在本地回执，仓库不提交凭据、私人对话、SQLite、完整轨迹或安装产物。

## 1. OAuth：从端口冲突追到失败任务没有结束

**现象。** 浏览器登录报回调端口 1455 被占用；设备码登录也没有完成。界面显示已有连接不能证明凭据仍能被 Provider 接受。

**证据和原因。** 本次 bundled OAuth bridge 传给 Pi 0.84.2 的登录 interaction 缺少 `AbortSignal`。浏览器路径先绑定端口，随后访问缺失的 signal 抛错；设备码路径同样抛错。一个已失败的登录进程仍保留监听，因此用户重试时看到的是后续端口冲突。端口占用是残留现象，原始原因在 bridge 契约与进程收尾。

**改动。** [pi_provider_bridge_bundled.ts](../../../rag_ime/node/pi_provider_bridge_bundled.ts) 补齐 signal 和失败/完成收尾；[pi_provider_auth.py](../../../rag_ime/pi_provider_auth.py) 对失败、取消、关闭后的进程做幂等回收。历史残留进程在核对 PID、启动时间、命令及失败任务归属后单独终止，未删除账号或用户配置。

**为什么这样改。** 只换端口或删除凭据不能补上 interaction 契约，也不能阻止下一次失败留下监听。取消信号属于登录会话的生命周期；进程回收属于启动它的认证 owner。修复放回这两个边界后，重试才有稳定前提。

**验证。** 认证 bridge、生命周期和 HTTP 路径共 14 项测试通过。标准构建、暂存 Session 验收和激活得到 OAuth 修复 generation `pi-0.84.2-9c3f93c8b1c4-raghost-b33df9afea`，前一代保留。18:13 CST 浏览器 OAuth 完成；随后实际 PAW 凭据完成 Luna/low 调用并返回 `OK`，耗时 2.659 秒、26 tokens。该调用只证明认证可用，未计入面试评测。

**回执与边界。** `<PAW_STORAGE>/install-candidates/pi-oauth-signal-20260905*` 保存 build、staged acceptance、安装及 previous-pointer 回执。此回执只证明 bundled bridge 已更新；Python 认证 owner 的安装结果须看本文最终安装记录，不能从 Pi generation 自动推导。

## 2. 轨迹超时：大快照与无缓冲读取共同阻塞控制通道

**现象。** 截图中的 Agent 3 有消息历史，却出现空白消息区、模型/工具加载中，以及一秒左右返回的轨迹读取失败提示。

**分层实测。** 对目标 Session `agent:795aa13e-7561-46aa-9f54-6b51331b9003`：完整 messages 返回 15 条（8 user、7 assistant），约 2.26 MB、1.329 秒；recent 返回 5 条共享 Room 消息，约 0.318 秒。这 5 条共享消息不能证明该伙伴真的执行了五次。`debug-context` 重复约 1.13 秒返回 `runtime_unresponsive`。最新持久化轨迹有 6 次模型调用，文件约 47.24 MB；7 份轨迹合计约 290 MB。另一位确实零消息的 Agent 4 与 Agent 3 分开判断。

**原因链。** `PawContextTrace → AgentService.debug_context → PiRuntimeHostManager.debug_context → session.debug.context`。已安装 Pi 从 recorder 的 `get()` 复制完整 capture；历史 context windows、provider requests 和各次 model call 上下文在回复中重复携带。另一方面，Python 以 `Popen(bufsize=0)` 读取 stdout，原始 `readline()` 在大 JSON 行上大量细粒度读取。局部 1 MB 实验约 0.395 秒，缓冲读取约 0.021 秒。轨迹与普通控制 ACK 共用这个管道，因此不能把提示中的“对话不受影响”当作已证实结论。

**改动 A：读取边界。** [pi_runtime_v2.py](../../../rag_ime/pi_runtime_v2.py) 的 `_read_stdout` 使用 64 KiB `io.BufferedReader`。只改变接收缓冲，stdin 的及时 flush、RPC identity 和一秒 deadline 保持原有契约。独立回归在同一通道先读完整 12 MiB 响应，再读下一条控制 ACK，检查消息完整性和 deadline；真正挂起的 Runtime 仍返回 unresponsive。

**改动 B：返回内容。** Pi recorder 增加 `getRuntimeProjection()`，`pi-session.ts` 的 `debugContext()` 使用它。在线投影保留最近上下文、所有调用的元信息、工具身份/回执和成本，去掉重复历史 context windows/provider requests/tool updates 及旧调用完整上下文。原有 `get()` 与磁盘完整记录保持不变。只提取这三个已审查文件的补丁进入固定基线，不整合另一个 Pi 工作树的其他修改。

**真实记录的离线复核。** 主 Agent 将目标 Session 最新轨迹复制到独立诊断目录，通过修复后的 recorder 读取；没有 Provider 调用或生产目录写入。原 JSON 47,240,950 bytes，在线投影 2,063,982 bytes，减少 95.6309%；6 次 model calls 和 15 条 tool executions 数量不变，前后 `get()` 完整输出一致。单次复制约 135.729 ms→5.971 ms；这只测投影构造，不冒充 HTTP 或前台延迟。回执为 `<PAW_STORAGE>/install-candidates/pi-trace-projection-probe-20260905/receipt.json`。

**界面措辞。** [PawContextTrace.tsx](../../src/paw-os/apps/PawContextTrace.tsx) 将未经证实的“对话不受影响”改为“轨迹快照读取超时，请重新读取。”，保留实际重试动作。原有重试及迟到结果保护等 16 项测试通过。

**为什么需要两处。** 缓冲读取解决“字节如何到达”；紧凑投影解决“每次应传多少”。单纯延长超时会延长界面等待，仍让很大的历史数据阻塞后续回复；只做前端重试会重复制造同样的负担。完整原始证据继续存盘，在线界面读取有明确内容边界的投影。

**验证。** Python 12 MiB 回归先红后绿，连同真实挂起、resident/nonresident、历史命令、工具、超时、两类 abort 和 settlement 共 11 项通过。Pi 目标工作树的新测试先因缺少 `getRuntimeProjection` 失败，补源后 recorder 9 项测试通过。日志分别为 `<LOCAL_LOG_DIR>/paw-pi-projection-red-target.log`、`paw-pi-projection-green.log`。这证明源码契约；截图中的完整前台恢复仍须在安装后复查。主 Agent 后续独立运行四个 trace 回归通过（11.344 秒）；配套认证、Room admission、Trial/Memory Pi 后端六模块 65 项通过（94.705 秒），结果以各日志最终退出状态为准。

## 3. 构建身份：修改过的 Pi 不能继续使用旧 generation 名称

**发现。** 构建 compact trace 候选时，manifest 的完整 `sourceCommit` 已从 `+dirty.13f079…` 变为 `+dirty.be07d83…`，生成的 runtimeVersion 却仍是 OAuth-only 的 `b33df9afea`。此前一次从不同快照目录打包也遇到相同版本、不同 payload 的冲突。

**约束和处理。** 已安装 generation 是不可覆盖的恢复点。不能为了让安装“通过”而覆盖旧目录，也不能在 sourceCommit 已改变时声称装上了新代码。当前先修复版本生成对完整源码身份的区分，再重新构建、暂存验收和激活。[builder](../../../scripts/build_managed_pi_runtime_v2.py) 的 packager digest 现纳入带域分隔符的完整已验证 `source_commit`，保留原有展示格式。不同 dirty 源、clean/dirty 冲突分别先红后绿；相同源确定性通过，builder 50 项与 installer 31 项通过。新候选重新完整构建为 `pi-0.84.2-9c3f93c8b1c4-raghost-a70a646b22` ，通过六类 Session 方法的 staged deterministic acceptance 后，经两次核对 active Session/completion 为空，已激活并重启空闲 Gateway。manifest SHA-256 为 `51987b6e33b9eceb922dbde72094a5760ea327a1b4fd948072141c89657c3417`。发现碰撞的第一份候选没有激活。

## 4. 协同模式：窗口已经创建，显示层却只允许一个可见

**重现。** 源码 HTTP 页面进入保留的四伙伴 Room 后，DOM 中已有四个独立 `agent:participant:*` shell；点击 Earth 能显示它，点击 Mars 又把 Earth 隐藏。故障在展示约束，不在窗口身份创建。保留 Room 的 Earth 已完成，另外三位待命，不能把四个成员全部标成运行。

**改动。** [PawWindowLayer.tsx](../../src/paw-os/shell/PawWindowLayer.tsx) 为全部已打开且未最小化的伙伴窗口分配可见 frame；selected participant 只表达焦点。[PawRoomFocusParticipants.tsx](../../src/paw-os/apps/PawRoomFocusParticipants.tsx) 点击行星激活或恢复自己的窗口。[room-satellite-auto-open.ts](../../src/paw-os/apps/room-satellite-auto-open.ts) 以实际非终态 Root 的 active/admitted 伙伴与当前 roster 的交集决定自动打开；[PawRoomWorkspace.tsx](../../src/paw-os/apps/PawRoomWorkspace.tsx) 仅处理新增进入者，不在普通进展事件中反复打开用户已最小化的窗口。

**布局与结果。** 大屏保留主输入窗和多伙伴网格；窄屏保留主窗及可横向访问的独立伙伴窗口。伙伴可以拖动、调整尺寸、单独最小化或关闭；终态保留结果，退出协同模式恢复常规窗口边界。

**为什么这样改。** store 原本已有稳定独立身份，另造一个公共弹窗会再次丢掉同时查看能力。把选择状态与可见窗口集合分开，既满足“一个窗口不够”，也不会让旧成员或已完成的工作伪装成正在运行。实际执行进入事件与用户手动收起操作必须各自生效。

**验证。** UI/布局/自动打开回归从 6 项失败推进到五文件 115 项通过，TypeScript 检查通过。在真实源码页面 1440×1000 下确认主窗加四伙伴 shell 可见、位置不重叠。HMR 后主 Room 曾停留在恢复态，不能据此宣告整个前台通过；刷新重开及安装后的完整操作结果在最终记录单列。

## 5. 其他同步修复：已接受的执行与暂未同步的投影不能混为失败

**Session 状态。** [agent-reducer.ts](../../src/contracts/agent-reducer.ts) 在恢复 snapshot 的不同阶段协调 turn 状态，最新 assistant attempt 决定当前 turn 终态；早先失败消息作为历史保留。否则成功重试可能继续显示失败，反向也可能掩盖最新失败。回归同时覆盖这两个方向。

**Room 发送。** [agent_room_session_dispatch.py](../../../rag_ime/agent_room_session_dispatch.py) 在 Pi 已接受后，将可选 delivery cursor/route metadata 的同步失败记录为 `projectionSync.state=pending` 并标识 failed operations。已接受的 turn 和幂等身份仍有效，不能把投影附带写入失败当作需要重发的执行失败。这里没有声称已经新增自动修复调度器。

**Lab 读取。** Trial API 在读取失败时保留既有回执，拒绝过时列表覆盖，正确处理幂等重放与错误恢复。结果界面区分质量不通过、执行故障、取消及成本未知；运行入口回到同一 job，不能因恢复点击再次启动评测。

**验证。** routes/reducer/live-store 三文件 108 项通过；Room admission 18 项通过；Lab 前端 57 项、相关后端 111 项通过。较宽的 Agent 六文件运行结果为 302 项通过、1 项超时；未改代码的该项单独复测通过（9.27 秒）。该事实不能写成宽套件首次全绿。TypeScript 与 HTTP 生产构建通过。随后固定候选的整套前端 268 个文件、3036 项测试全部通过（969.49 秒），生产构建 10.93 秒；测试环境报告 canvas 未实现警告，构建有既有 chunk 大小警告，均未成为失败。最终只追加超时提示及对应断言的两文件文字差异，独立 16 项回归通过，再由标准安装路径重建前端。

## 6. 新 Memory 指标：恢复认证后做独立、可追溯的 Pi 配对

**为什么另建实验。** 旧 Memory CLI 使用 `concise-json-v1`，本次 Pi adapter 使用 `standard-v1`。即便场景名称一样，也不能无声覆盖旧数字或称为完全相同条件复现。新实验固定五条合成 fixture、`full-json-v1`、`standard-v1`、max thinking、本地 hashing 和相同源码，只改变 Sol/Luna 模型。

**实际结果。** 新实验 `memory.maintenance-pi-model-only-20260905-r3.v1`：两侧均完成 5/5 源决策、6 个当前合法治理 atoms、4/4 durable recall、1/1 abstention，回滚和幂等重放通过。每模型 2 次实际请求，合计 4 次、0 次失败。Sol 估算 $0.163425，Luna 估算 $0.0071846，降低 95.6037%；tokens 为 14450→15078，因此没有把 token 降低当作成本下降原因。估算按输入、输出及缓存 token 分别乘冻结价表；模型单价与 token 构成共同决定金额，不能把成本降幅说成推理能力的提升。

**证据链。** Runtime SQLite 的请求/turn 与 Pi transcript 的 usage 对齐，以冻结的公开模型价表重算，保留两份 trial receipt、独立 cost receipt、fixture hash 和执行源码 hashes。首次 harness 配置失败的准备记录保留；它没有进入 Provider turn，不计作这四次调用。认证探针同样排除。

**落点与限制。** [聚合证据](../../../eval/interview-metrics/runs/memory-pi-current-pair-20260905.r3.json)、[实验登记](../../../eval/interview-metrics/agent-experiments.v1.json)、[指标账本](../../../eval/interview-metrics/evidence-ledger.v1.json) 保留新旧实验各自身份。金额是冻结价表估算，不是账单；合成样本不是个人长期记忆表现。CloudOps、EnterpriseOps、RAG 的共同执行入口、真正反事实以及 Tool/Skill 试验仍需继续；RAG r6 的 candidate-aware 边界不变。

## 关闭记录：验证层级与下一步

固定候选经标准 `install_product_stack.sh` 安装完成，退出码 0。开发 build **1429** 的构建时间为 `2026-09-05T11:23:40.630885+00:00`，dist digest 为 `bcc9440502da473772c8c1b2533866b2c626a6ff72ffa2f58a8f613fa49d956f`。安装后 Python buffer/认证 cleanup、Room dispatch、Trial 和新 Memory 配对文件哈希与候选一致；Pi 保持已验收的 `a70a646b22` generation。前一应用、服务代码、web bundle、配置与 Pi generation 均保留恢复点。

安装回执初写时 Mac 锁屏，故标为 foreground unverified。随后实际 installed HTTP build 1429 打开保留 Room，恢复出了主 Room 的已完成内容；与先前 HMR 停留恢复态分开记录。native AX 曾读到 build 1429，但截屏接口随后失败，因此没有把 HTTP 页面复核写成完整 native 验收。

安装后 API：目标 Session messages 15 条、约 2.26 MB，1.846 秒；models 成功、0.098 秒。该 Session 在重启后非 resident，debug-context 返回 `session_not_resident`，不是 timeout，也不是 resident 大轨迹在线成功的证明；没有为验收重放 Provider 请求。Lab 实验目录出现新 Memory Pi 配对一次，总实验数 35。完整回执保存在 `<PAW_STORAGE>/install-candidates/20260905-190039-runtime-sync.installed-closeout.json` 及同名前缀的 readback/install-input 文件。

| 层级 | 当前可确认结果 | 未完成边界 |
| --- | --- | --- |
| 源码 / 聚焦回归 | 上述 OAuth、轨迹、窗口、reducer、Trial 回归有独立记录 | 构建身份及安装契约 81 项已通过；不把一次宽套件超时隐去 |
| 认证 / 真 Provider | 实际 OAuth 完成、26-token 探针以及四请求 Memory 配对完成 | 其他三个场景没有因本次认证修复自动产生新结果 |
| 构建 / 安装 | build 1429 与新 Pi generation 已一致安装并读回；health 成功 | 开发候选 audit 仍有 control/sidecar `dirty_build`，不属于发布验收 |
| 真实界面 | installed HTTP Room 恢复出已完成内容；messages/models API 成功 | resident 大轨迹重读、native 全流程及独立多窗操作仍须各自验收 |
| 设计 | 浅色方向继续；用户随后要求更酷炫，并要求优化记忆可视化 | 新星际/主题页进展在[后续记录](STELLAR_MEMORY_TOPIC_PAGES_20260905.md)，尚不属于本次 1429 安装 |
| 发布 | 未提交、未推送、未发布 | dirty 开发候选不代表可公开发布版本 |

剩余顺序：在实际 resident Session 验证在线轨迹 → 验证独立多窗与 native 操作 → 完成新星际和主题页的页面/安装验收。失败保留实际错误与下一步，不重放状态未知的 Provider 效果。[需求状态](PAWOS_REQUIREMENT_STATUS.md)及[根 Outcome](../../../OUTCOMES.md)分别记录当前边界。
