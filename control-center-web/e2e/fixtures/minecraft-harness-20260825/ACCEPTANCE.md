# PAW Harness 多 Agent 黑盒验收报告（Minecraft 风格 3D 体素项目）

日期：2026-08-25（Asia/Shanghai）
验收结论：**changes_required（产物可玩，Harness 治理闭环未通过）**

## 1. 验收目的与边界

本轮不是由测试者替 Agent 拆任务、实现游戏或维护项目文档。测试者只做了四类动作：

1. 从已安装 PAW 前端提交自然语言目标；
2. 在中断后只发送一次自然语言“继续”；
3. 修复 PAW 自身阻断黑盒流程的运行时缺陷；
4. 在 Harness 宣布结束后独立读取 Runtime、SQLite、Session JSONL、项目文件、测试、构建和 Browser/Ego 回执。

测试者没有替 Harness 创建或修改游戏 WorkItem，没有替伙伴写游戏项目文档，没有代替 Facilitator accept/return，也没有手工操作游戏来补 Harness 的 Browser 验收。

前端主线 `/workspace/personal-agent-workbench` 未被本轮修改；验收与修复都在隔离后端 worktree：

- worktree：`/workspace/learnA/.worktrees/paw-harness-backend-recovery`
- branch：`codex/model-routing-provider-recovery`
- 安装版入口：`http://127.0.0.1:8768/#/agent`
- 游戏项目：`/workspace/minecraft-harness-20260825`

## 2. 运行身份

- Room：`room:00000000-0000-4000-8000-000000000001`
- Root Session：`agent:00000000-0000-4000-8000-000000000001`
- Goal：`goal:10000000-0000-4000-8000-000000000001`
- 恢复回合：`room-turn:10000000-0000-4000-8000-000000000002`
- 恢复 dispatch：`room-dispatch:10000000-0000-4000-8000-000000000001`
- Pi turn：`9bafefe4-3900-4f42-bbbb-82c28db8bd5c`

实际模型路由符合设置：

- 4 个可见 Room Partner 均为 `openai-codex/gpt-5.6-sol`、`high`；
- 本轮相关私有 Tool Agent 均为 `openai-codex/gpt-5.6-luna`、`max`；
- 这些值来自 `agent_sessions` 实际记录，不是 UI 文案推断。

## 3. 关键时间线

| 时间 | 事件 | 证据结论 |
|---|---|---|
| 00:25 | 受控重装并重启 Gateway/Pi Host | Session、Room、Goal 和 WorkDocument 持久状态仍在 |
| 00:29:23 | Goal 从 paused seq15 恢复为 active seq16 | 前端“一键继续/继续当前任务”路径可恢复长期 Goal |
| 00:29:25 | 用户只发送“继续” | Harness 自行重新核对旧后台 job、Browser 和未完成验收 |
| 00:29:52 | Harness 发现旧 job orphaned，启动新 job | 状态可恢复；后台进程本身不能跨 Gateway 重启接管 |
| 00:29:58–00:33:02 | Harness 自行用 PAW Browser/Ego 验证游戏 | 最终 WebGL、Pointer Lock、移动、采集/放置、存读档成功 |
| 00:40:46 | Root 发布唯一 result | Room 未出现第二份终态 result |
| 00:41:05 | Goal completed seq17 | 有 completion audit 和证据列表 |
| 00:41:25 | Pi `turn_completed` | `stopReason=natural`、aborted=false、pendingOperations=0 |
| 约 00:57 | Gateway 重启恢复时 Root WorkDocument 被归档 | 终态最终对账成功，但不是 Goal completion 同步完成 |
| 01:04 | 安装版 authority schema 回归 | `work_documents` 已常驻 Provider schema 并返回 terminal authority rev17 |

## 4. Harness 自主完成的内容

### 4.1 真实并行与上下文边界

- Room 首波两个 Partner dispatch 相隔约 245 ms，属于真实并行启动，不是顺序伪装。
- Partner 各自拥有独立 Session、独立 WorkItem 和独立 canonical WorkDocument。
- 私有 Agent batch 全部使用 `context_mode=fresh`；任务 brief 约 404–1006 字符，没有把 Root 全 transcript 直接复制给子 Agent。
- Root 是唯一最终整合者，伙伴 prose 没有直接成为 Root 最终回复。

但是复杂度压力结果不理想：本次时间窗共有 7 个私有 batch、11 个 Luna/max run，其中只有 2 个 completed，5 个 timed_out，4 个 aborted。PAW 能创建真实并行网络，但当前 Tool Agent 长任务的完成率不足以通过稳定性验收。

### 4.2 异步 dispatch、wake 与恢复

- `room_partner delegate` 产生持久 `childDispatchId/workItemId` receipt，伙伴完成后进入 submitted/review；没有在一次工具调用里同步阻塞 300 秒。
- 当前 Room 共留下 13 个持久 wake schedule：1 completed、4 cancelled、8 failed。
- 至少一个 generation=3 的 Room completion wake 真实 delivered，证明 durable wake 主路径可工作。
- Gateway 重启后 Room/Goal/Session 可继续；用户一次“继续”即可恢复 Root loop。

边界：旧 `workspace_job` 在宿主退出后成为 orphaned，错误为“后台任务宿主异常退出，进程组已清理且无法重新接管”；Harness 能识别并重启，但不是原 job 自动续接。大量历史 wake 失败也说明恢复链仍不稳定。

### 4.3 Browser/Ego 同窗验收

最终两个关键 command 均 completed、exit 0、`controlProtocol=ego-browser`、`secondBrowserProcess=false`：

- `bcmd_f9ed4f3e478349fbad7216af49f34050`：WebGL2、启动、Pointer Lock 和覆盖层隐藏通过；
- `bcmd_8f2ba2dc52784b7fb1ef2019433bbb9a`：移动 `1.3318200000000253`、存读档误差 `0`、库存 `20→21→20`、存档 `12801 bytes`。

截图 `snap_e38066a62d014e558fdc487f7fe6aded` 对应 `http://127.0.0.1:4174/?build=original-final`，591,556 bytes。

同一恢复回合也暴露了真实脆弱点：首次 active-tab attach 竞态、3 次 screenshot/CDP timeout、1 次 movement 失败；后续 Agent 自己恢复成功。期间出现两个游戏 tab，但都在同一 Electron guest/profile 内，不是外部 Chrome 或第二浏览器进程。

### 4.4 游戏产物

独立新鲜检查：

- `npm test`：10/10 passed；
- `npm run build`：通过，生成零外部运行依赖的 `dist/`；
- `node --check src/game/runtime.js`：通过；
- `GET http://127.0.0.1:4174/`：HTTP 200；
- `src` 与 `dist/src` 的 14 个文件一致；
- `FINAL.md` 明确列出未实现的无限区块、完整合成/熔炼、工具耐久、主动生物、战斗、天气、维度、多人等，不把核心体验夸成完整 Java 版复刻。

因此游戏对 Harness 自己收窄后的“原创单人核心闭环”是可玩且有真实证据的；它不能证明“基本完整还原 Minecraft Java 全玩法”。

## 5. 文档治理验收

### 通过项

- `docs/agent/` 有 INDEX、requirements、architecture、decisions、WORKBOARD、tests、acceptance、FINAL 和 WorkDocument registry。
- 8/8 个 Markdown 相对链接物理可解析。
- Root 与独立 Core migration 文档现已归档；Root authority revision=17、document revision=9、terminal=true。
- 新 Core migration `room-work:9eec...` / `workdoc_33e...@2` 的 7/7 测试、语法和 hash 证据一致。
- FINAL 的“已实现/未实现”边界总体诚实。

### 未通过项

1. `requirements.md` 把 R1–R5 指向 `ROOT.md`，但 `ROOT.md` 只是 registry 导航；R1–R5 实际在归档 Root WorkDocument。物理链接有效，语义追踪错误。
2. `ROOT.md` 仍指示从 `ACTIVE.json` 读取 Root，但 Root 已归档，应路由到 authority lookup 或 ARCHIVE。
3. `WORKBOARD.md` 仍写 Browser/Pointer Lock/移动/采集放置/存读档待复验，与后来真实 Browser receipt 和 FINAL 冲突。
4. 旧 Core `workdoc_378...` 仍是 active，registry hash `3ea37f...` 与实际文件 hash `d9eebe...` 不符；其 WorkItem 仍 blocked，无明确 superseded/abandoned 终态。
5. 项目没有任何 Git commit；所有源码、测试、docs 和 dist 都是 untracked。`git diff --check` 对 untracked 文件没有审查意义，无法形成可追溯提交基线。

## 6. P0：主管验收判断失败

这是本轮最终不能判 Pass 的主因。

两个 Partner 的提交结果明确写了失败边界：

- Integration reviewer：`operability UNVERIFIED`、`requirement satisfaction UNVERIFIED`，并报告 1 个 High、3 个 Medium；
- Browser reviewer：Browser Provider 未连接，所有真实项目均 `NOT EXECUTED`，结论为 Browser execution FAILED、两轴 UNVERIFIED。

但 Facilitator 后续显式调用 accept，把二者均写成：

- `review_operability_verdict=passed`
- `review_requirement_verdict=satisfied`

这不是旧代码自动 accept：事件链包含 assigned → submitted → Facilitator completed，说明新的“伙伴只提交、主管显式验收”机械合同已经生效。失败发生在主管语义判断：它无视同一 submission 中明确的 UNVERIFIED/FAILED，却用不支持通过结论的 evidenceRefs 给出 passed/satisfied。

后续 Root 自己取得的新 Browser 成功证据可以支持**顶层当前产品**，但不能追溯性地把历史失败 reviewer receipt 改写为通过。正确做法应是 return 原 reviewer，或创建一条明确 superseding 的新复验 WorkItem，并保留旧 verdict。

因此：

- 机械双轴 API：通过；
- 主管双轴判断质量：失败；
- 审计链不可篡改性：历史事件保留，正向；
- 最终 Room 治理闭环：不通过。

## 7. 本轮修复并安装验证的 PAW 缺陷

### 7.1 `work_documents` Provider schema 缺失

根因：active Facilitator 的 `work_documents` 虽从 `modelVisible=false` 提升为可见并缩到 `authority.context`，但没有 `alwaysAvailable=true`。Pi Runtime Host 只自动向 Provider 披露 always-available 工具，所以 Skill 要求的权威 preflight 在模型层实际上不可调用。

最小修复：

- `rag_ime/agent_tools.py`：对 active Facilitator 的 scoped `work_documents` 设置 `alwaysAvailable=True`；
- `tests/test_agent_tools.py`：增加 manifest 常驻断言。

安装版 fresh Session 实证：Provider schemas 从 20 个增加到 21 个；第 20 个为 `work_documents`，唯一 operation 是 `authority.context`。诊断回合中 Agent 先通过 `agent_goal` 取得 authority id，再调用 `work_documents authority.context` 得到：

- authorityRevision=17
- state=completed
- terminal=true
- transitionReceiptId=`goal-event:2c8b417a-f8df-4d03-89f5-ed2fc7b46ad6`

之后才读取 ACTIVE/ARCHIVE。安装文件与隔离源码 SHA-256 相同：`49b7cc5e...`。

### 7.2 已知残余

- Pi Package 已注册 `work_documents`，但 `PI_PACKAGE_OWNED_CONTROL_TOOL_IDS` 尚未纳入它；legacy tool selection 仍有半接线。
- v2 已打开 Session 的 reuse 分支没有 `tools.sync`；本轮通过 Gateway 重启和 fresh open 验证，不能证明无重启热同步。
- 这些属于 P1 一致性/热更新边界，不影响本轮 fresh installed schema 证明，但应在合并前收口。

## 8. 回归测试与安装证据

后端聚焦回归共 232 个测试通过：

- `tests.test_agent_tools`：80；
- `tests.test_agent_wake_scheduler`：12；
- `tests.test_agent_rooms`：51；
- `tests.test_agent_room_prompt_budget`：6；
- `tests.test_pi_runtime_v2`：83。

此外：

- Browser guest 注册聚焦测试：1/1；
- Browser/Desktop Python 聚焦：22/22；
- Electron host 聚焦：13/13；
- Browser runtime Python 聚焦：35/35；
- Gateway 安装门：TypeScript、完整 Vitest、Vite production build 通过；
- `git diff --check`：通过；
- Agent Gateway health：OK。

说明：安装门的完整 Vitest 输出未保留总数，因此只声明“完整命令通过”，不虚报测试数量。

## 9. 与 Tutti 流程的对照

### PAW 当前优势

- Room Partner 是可见、独立 Session，而不是只在父 transcript 中出现的临时结果；
- WorkItem、WorkDocument、wake、Browser receipt、completion audit 都有持久 ID；
- 重启后能恢复 Room/Goal/Session，继续原协作图；
- 双轴验收和文档 authority 比 Tutti 的普通异步 handoff 更强；
- 同窗 Browser/Ego 给出了 `secondBrowserProcess=false` 的可审计产品证据。

### PAW 当前劣势

- 持久层较多，WorkItem、WorkDocument、wake、Goal 和后台 job 容易出现跨层残余；
- 私有 Luna Agent 在复杂长任务下 2/11 完成，超时/abort 比率过高；
- wake 有真实成功，但当前 Room 历史为 1 completed / 8 failed / 4 cancelled；
- 主管能够在 API 合法的情况下做出语义矛盾的 accept；
- Root WorkDocument 依赖重启恢复才最终归档，终态不是同事务闭合；
- Git 基线不在 Harness 的完成门内，导致“完成项目”仍不可审 diff。

Tutti 的异步 receipt + 独立 wait/collect 更轻，失败面较少；PAW 的可追溯性更强，但必须把各持久层的终态一致性和主管验收约束补齐，优势才不会变成复杂度负担。

## 10. 最终验收矩阵

| 能力 | 结论 |
|---|---|
| 自然语言 Goal → 自主拆解 | 部分通过；能拆成多轨，但目标被收窄为核心 MVP |
| Sol/high 可见 Partner | 通过 |
| Luna/max 私有 Agent | 配置通过，稳定性不通过（2/11 completed） |
| 真实并行 | 通过 |
| 有界上下文 | 通过 |
| 每 Agent 独立 WorkDocument | 通过主路径，旧 Core seam 未清理 |
| 异步 receipt + collect/wake | 机制通过，稳定性部分通过 |
| 中断后一次继续 | 通过 |
| 后台 job 原地恢复 | 不通过；需识别 orphan 后重启 |
| PAW 同窗 Browser/Ego | 通过，存在 attach/screenshot 超时 |
| 游戏测试/构建/真实交互 | 通过核心 MVP |
| 与完整 Java 版差异诚实说明 | 通过 |
| Root 唯一自然终态 | 通过 |
| Root WorkDocument 同步终态 | 部分通过；重启恢复后才归档 |
| 主管双轴语义验收 | **不通过** |
| docs 索引/交叉引用/最终一致性 | **不通过** |
| Git 可审查交付 | **不通过** |

## 11. 建议的最小后续修复顺序

### P0

1. Partner submit 增加结构化 `proposedOperabilityVerdict/proposedRequirementVerdict`；Facilitator accept 不得静默把 failed/unverified 升级为通过。若有新证据，必须创建或引用明确 superseding review receipt，而不是改写历史。
2. Goal complete 前执行权威一致性 gate：Root WorkDocument 必须匹配当前 authority revision/hash 并获得 terminal receipt；未终态 WorkItem 必须显式 superseded/blocked/abandoned，而不是留在 ACTIVE。

### P1

1. 收口 `work_documents` 的 Pi Package ownership，并为 v2 opened Session 增加 idle `tools.sync` 回归；
2. 为 Browser active-tab attach 与 screenshot timeout 增加一次有界恢复，不循环重试；
3. 提升 Tool Agent 超时后的部分结果/继续能力，避免 11 个 run 只有 2 个完成；
4. 让 Harness 在宣称项目完成前创建初始 Git commit 或至少建立可审查 baseline receipt；
5. 修复 requirements → R1–R5、ROOT → ARCHIVE、WORKBOARD → 最新 Browser evidence 的语义链接。

## 12. 最终判定

**游戏核心产物：可玩，通过。**

**PAW Browser/Ego 同窗控制：通过，有可恢复抖动。**
**PAW Harness 多 Agent 治理闭环：不通过，必须整改。**

本轮最重要的成果不是“做出了一个小游戏”，而是把 Harness 的真实边界测出来了：它已经具备持久 Room、真实并行、模型分层、同窗 Browser、重启恢复和权威文档的骨架；但主管验收仍可能与伙伴证据相矛盾，私有 Agent 与 wake 的稳定性不足，文档/Git 终态也没有被 completion gate 强制收口。当前版本适合继续工程化，不适合宣称多 Agent 项目自治已经可靠完成。
