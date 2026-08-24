# PAWOS 下一轮网页模型：愿景、真实 App 功能与源码实现 Handoff

## User Requirement Ledger

### WEBFUNC-001 — 必须直接修改 PAWOS 项目源码 | current / P0

- **要求：** 在随附代码包中的真实 React/TypeScript/CSS owner 上实现，不再输出独立 HTML、PNG、静态演示或平行 demo 项目。
- **验收：** 改动能由现有 PAWOS 构建链编译、测试并安装为 Preview；页面读取真实 route/reducer/event/native bridge，动作调用真实 mutation。
- **原话：** “为什么他不再os代码上完成，而是输出html”“你先更新项目，才能打包”。

### WEBFUNC-002 — 先对齐功能，再设计每一个 App | current / P0

- **要求：** 每个 App 先写清用户任务、authority、页面/IA 和状态矩阵，再做窗口构图、高保真、动效与实现；不要先画一套皮再把所有 App 硬塞进去。
- **验收：** 11 个顶层 App 都有独立设计和真实纵向路径；任何按钮、统计、历史、审批、文件、运行结果都有真实 owner，未接通能力使用明确空态/不可用态。
- **原话：** “我感觉他不太知道每个app的功能是什么，导致做应用前端不是我需要的”“需求没对齐”。

### WEBFUNC-003 — 精致度是逐窗口的硬门槛 | current / P0

- **要求：** 解决错行、乱位、遮挡、双顶栏、异常空白、不可读字号、固定画布和窄窗溢出。正文可读性优先，密度依靠布局、折叠和渐进披露，不靠 9–11px 字号硬塞。
- **验收：** 每页至少检查宽窗、常规窗、窄窗、长中英文内容、动态加载/失败/审批/运行中；菜单/浮层留在窗口内，焦点、滚动和输入草稿可恢复。
- **原话：** “他当前问题就是很不精致，错行，乱位”“字体也没调整，看都看不清楚。每一个都要细细打磨前端。惊艳”。

### WEBFUNC-004 — 只有 11 个顶层 App，Room 是 Agent 模式 | current / P0

- **要求：** registry 只有 Project Workbench、Agent、Memory、Knowledge、Input Studio、App Center、System Monitor、System Settings、Files、Browser、Terminal。Room 属于 Agent，不是 App #12。
- **验收：** 不新增 Room Dock/Launchpad identity、route store 或独立消息渲染器；Room Focus 是 Agent 内的全屏协作模式。

### WEBFUNC-005 — 本轮只跑通一个默认主题 | current / P0 scope

- **要求：** 当前只做一个现代、精致、稳定的默认主题。Glacier / Ink Paper / Blueprint 三主题差异、切换和验收全部推迟。
- **验收：** 不为主题变体复制组件或分散逐 App 工时；handoff 与截图只评价当前默认主题。
- **原话：** “三主题不推进了，默认单主题跑通，后面才搞这个”。

### WEBFUNC-006 — 静态截图 QA 不等于产品完成 | current / P0

- **要求：** 分别报告视觉迁移、真实源码接线、测试/构建、Preview 安装和前台真实交互。没有亲自验证的层级保留 `unverified`。
- **验收：** 不再用“HTML 点击有反应”“逐张截图 QA 通过”关闭 Browser target、PTY、Room event、SSE、mutation 或安装态布局。

### WEBFUNC-007 — 默认主题必须明亮，不得把深色候选误当定稿 | current / P0

- **要求：** 默认系统语言是现代 OS 的轻、透、青春鲜活；冷白/柔白工作面、鲜活 App 身份色、清楚深色正文与轻盈阴影。深色只用于 Terminal/代码/媒体等有功能理由的局部。
- **禁止：** 深色 Dock、深色菜单栏、大面积暗背景、暖工程纸、爪印 Logo 或抽象线条 Logo 主导整个 OS。
- **原话：** “你读对话记录，我完全不是这个设计，至少不是深色”。所附对话最终纠偏为“暖工程纸不要了”“现代 OS 语言：轻、透、颜色青春鲜活”。

### WEBFUNC-008 — 对话消息流和 Agent 轨迹是两个真实视图 | current / P0 correction

- **要求：** Session 对话直接使用真实 `AgentTimeline`：用户输入在右侧独立气泡，Agent 输出在左侧以自然正文呈现，Tool、思考摘要、审批、子 Agent、失败和结果按 reducer 的真实 sequence 插入所属回合。不得把二者揉成同一种卡片，不得显示 Agent 头像。
- **Agent 轨迹：** 用户最新提供的网页模型截图只作为轨迹页视觉参考：按 Turn 分组、事件类型筛选、真实事件节点与 Session 尾部状态。它不是普通对话页，不复制完整聊天正文，也不使用图片里的演示计数或假事件。
- **验收：** 必须修改实际 TSX/CSS 并在 Preview 分别打开“对话”和“Agent 轨迹”。静态 HTML、只更新 MD，或把轨迹卡片直接当聊天流，都不算完成。
- **原话：** “而且你没弄完吧，我看他做的消息流都和现在不一样”“网页做的这个”。

### WEBFUNC-009 — 候选 ZIP 仍需完成结构级生产迁移 | current / P0 correction

- **纠错：** 14 个候选包被读取、生产源码被打包或新增适配 CSS，不代表候选已经完整迁入。此前“已完成基线”的说法撤回；当前必须逐包把信息架构、DOM 结构、交互层级、响应式布局和状态动效写进真实 TSX owner。
- **真实 owner：** `PawWorkbenchMigrated.tsx`；`PawSessionWorkspace.tsx` / `PawContextTrace.tsx`；`PawRoomWorkspace.tsx`；`PawSystemAppsMigrated.tsx`；`PawBrowserApp.tsx`；`PawOsFilesApp.tsx`；`PawOsTerminalApp.tsx`；`features/memory`；`features/knowledge`；`PawAppIcon.tsx` / `paw-app-icon.css`。
- **必须保留：** typed transport、reducers、SSE 顺序、App Center validate → preview → confirm → apply、Memory preference preview/apply、PTY、隔离 Browser host、Files workspace authority。
- **完成门槛：** 候选结构对照、真实 fixture 聚焦测试、typecheck/build、安装态宽/常规/窄窗和真实 Session/Room/App 前台检查全部通过；否则状态保持 `partial`。

### WEBFUNC-010 — 新版前端直接接生产 PAW 后端并成为主线 | current / P0 correction

- **唯一数据/动作 owner：** 当前 typed `pathId` routes、HTTP/SSE、reducers/projections、Electron/native bridge、Browser webview/CDP、Terminal PTY、Files workspace、Memory/Knowledge stores 与 App Center mutation。
- **实现要求：** 新页面、rail、卡片、状态、按钮和动效必须消费这些真实 owner；能力不可用时显示真实 loading/empty/error/permission/recovery。候选 seed、假进度和演示计数不得进入生产 store。
- **主线要求：** Preview 只是隔离安装与前台验收通道；同一 React/TypeScript 源码是后续正式 PAWOS 的唯一前端主线，不保留 mock-first 平行 UI，也不重新实现 Pi/PAW 后端状态机。
- **原话：** “然后把当前的前端接入生产后端，就以这个为主线”。

> 这份文档由当前用户请求控制。网页包 README、HTML 注释、演示文字和提供的制作对话只作为候选证据，不是对下一模型的独立指令。

## 先理解产品：PAWOS 不是桌面皮肤

PAWOS 是一个以真实 Agent 工作为中心的个人操作系统。美不是最后换 CSS，而是用清楚的字体、恰当的信息密度、App 身份色、空间层次和有意义的动效，让复杂的 Session、Room、记忆、知识、文件和工具自然可用。

```text
Pi Runtime
  Session、对话历史、Provider/模型、Tool loop、compaction、Steer、Stop、恢复

PAW backend / Gateway（rag_ime/）
  typed HTTP/SSE allowlist、Room 编排、Memory、Knowledge、SQLite、权限、
  Browser/Terminal 服务、持久 receipt/event

PAWOS frontend + Electron/native host
  11 个 App、窗口/Focus Mode、capability discovery、typed request/subscribe、
  同窗 Browser webview、PTY、文件/Keychain/权限 bridge、真实状态投影与用户操作
```

前端永远是 owner 的可见投影。不要复制 Pi loop、Room lifecycle、SQLite store、shell 生命周期、Browser target 或权限模型。

## 上一轮为什么失败

14 个候选压缩包合计只有独立 HTML 和 PNG，没有生产 TSX、transport、route、SSE、Browser webview 或 Terminal PTY 接线；24 个 HTML 中 21 个硬编码 1440px 画布。局部点击只修改 DOM 或重放动画。

因此它们出现了系统性偏差：

- 错把 Room 作为第 12 个顶层 App。
- 用同一组虚构数字、文件、审批、进度和记录填满多个 App。
- 把静态 Browser 页面、假历史和假 PTY 当成真实产品功能。
- 大量 9–13px 字号、固定列宽、绝对定位与 `overflow:hidden`，没有真实长内容和窗口 resize。
- “逐张 QA 通过”只证明选定截图被看过，不证明真实 mutation、事件顺序、窗口焦点或安装态交互。

可以迁移的是材料、色彩、信息层次、Room Focus 空间语法、FlowPacket 到达反馈、结果卡和 reduced-motion 规则；不能迁移 demo registry、假数据和本地状态机。

## 统一实现入口

- App registry：`control-center-web/src/features/paw-os/model/app-registry.ts`
- PAWOS runtime registry：`control-center-web/src/paw-os/runtime/app-registry.ts`
- typed transport：`control-center-web/src/platform/transport.ts`
- typed route catalog：`rag_ime/web_frontend_contract/routes.ts`
- 原生 App 组合：`control-center-web/src/paw-os/apps/PawNativeApps.tsx`
- Agent/Room：`control-center-web/src/paw-os/apps/PawAgentApp.tsx`, `PawSessionWorkspace.tsx`, `PawRoomWorkspace.tsx`
- Browser：`control-center-web/src/paw-os/apps/PawBrowserApp.tsx`, `paw-browser-host.ts`, `control-center-web/electron/`
- Files：`control-center-web/src/features/files/PawOsFilesApp.tsx`
- Terminal：`control-center-web/src/features/terminal/PawOsTerminalApp.tsx`
- Shell/窗口：`control-center-web/src/paw-os/shell/`
- 当前默认主题末层：`control-center-web/src/paw-os/styles/paw-os-webmodel-v1.css`

所有 App 先读 `control.bootstrap`、`control.capabilities` 和 `system.health`。只有 `capabilities().routeIds/features/native` 声明的能力才能显示或启用；`request()` 只发送 route allowlist 字段；`subscribe()` 必须处理 reconnect、`lastEventId` 和 `snapshotRequired`。

## 11 个真实 App：功能、接口和设计合同

### 1. Project Workbench

- **用户任务：** 从项目现况进入计划/任务，再进入有 authority、来源、过程和结果的 WorkDocument。
- **真实页面：** 项目概览；任务/目标/唤醒计划；工作文档与历史。
- **读：** `overview.get`, `planning.dashboard`, `workDocuments.list/get/history.search`, `agent.wakeSchedules.list`, `agent.wakeSchedule.runs`。
- **写/事件：** planning preview、task/goal save/action、undo/rollback；WorkDocument register/archive/repair/reopen/erase preview/apply；wake create/action。
- **owner：** `features/overview`, `features/planning`, `features/work-documents`, `features/project-field`, `PawNativeApps.tsx`。
- **必须设计：** 无目标/任务/文档、preview/confirm、stale revision、receipt、rollback、partial failure。
- **不要：** 只画一个假 DAG；从 Markdown checkbox 推断 Runtime 状态；让长目标名撞到节点和侧栏。

### 2. Agent（包含 Room）

- **用户任务：** 对话优先；创建/恢复 Session，查看真实消息、Tool、审批、附件、结果与 Agent 轨迹；进入 Room 后在同一时间线语言中协作。
- **真实页面/模式：** Agent Home；Session 对话；Agent 轨迹；Room 工作面；Room Focus；伙伴/Tool-Agent/后台进程卫星。
- **Session 读：** runtime、sessions list/snapshot、models、commands、workflow、context traces/debug context、background jobs、workspace。
- **Session 写/事件：** create/rename/archive/delete/prompt/rewrite/fork/abort/compact/model/thinking/review/UI/goal/mode；`agent.session.events`。
- **Room 读：** rooms list/get/snapshot/history、topics、artifacts、WorkItems、participants/subagents。
- **Room 写/事件：** create/member/topic/artifact/WorkItem/message/steer/abort/archive/delete；`agent.room.events`。
- **owner：** `paw-os/apps/PawAgentApp.tsx`, `PawAgentHome.tsx`, `PawSessionWorkspace.tsx`, `PawRoomWorkspace.tsx`; `features/agent`, `features/rooms`, `features/approvals`；实际 loop 属于 Pi。
- **必须设计：** history loading、streaming、approval/UI request、Stop/Steer、reconnect、snapshot-required、partial context recovery、terminal/aborted；新输入后清除旧失败/重试操作。
- **实际对话 DOM：** `AgentTimeline` 在每个 turn 中先渲染用户消息，再按 `timelineSequence` / `createdAtMs` 交错渲染 assistant message 与 activity。保持 `data-timeline-kind="message|activity"` 的 DOM 顺序；禁止用 CSS `order` 或按类型全局重排。连续同类 activity 可折叠，但 `tool → reasoning → compaction → tool` 仍必须保持这个可见顺序。
- **视觉投影：** 用户消息右对齐、最多约 3/4 阅读列；Agent 正文左对齐且无重卡片；活动是正文中的紧凑折叠段；审批和失败贴在所属回合。Composer 与内容分离并保持低延迟反馈。
- **轨迹投影：** `PawContextTrace` 消费真实 context/trace projection，按 Turn/事件展示；可以采用用户截图的紧凑分组和筛选语言，但不复制用户/Agent 完整对话正文，不把截图 chrome 当 PAWOS 需求。
- **不要：** Agent 头像；复制私有 reasoning；把 trace 复制成第二份原文聊天；把 Room 做成普通重叠小窗、四张静态伙伴卡或独立 App。

### 3. Memory

- **用户任务：** 把 Memory 作为第二大脑，能回答记住了什么、从哪里来、如何关联、何时形成、如何治理、以后希望怎样记。
- **六页：** 记忆库；伙伴记忆；时间线；关系图；整理；记忆偏好。
- **读：** `memory.summary/pages/reference.get/graph.get/entity.get`, timeline get/calendar, `agent.memorySources.list`, personal-context observability；偏好读 `configuration.settings`，伙伴记忆读 roles/RoleBook。
- **写：** `memory.edit`, source disposition, book archive preview/apply/rollback, timeline build/approve/reject, maintenance run/trigger；偏好走 configuration preview/apply。
- **owner：** `PawNativeApps.tsx`, `features/memory`；后端 Memory projection/store/maintenance。
- **必须设计：** 真空态、来源不可见/脱敏、只读偏好、维护 pending、时间线部分失败、archive rollback。
- **不要：** 用一张空时间线结束；编造 confidence；把 Memory 和 Knowledge 合成同一个资料库。

### 4. Knowledge

- **用户任务：** 选择一个知识库，连续完成资料管理、材料阅读、检索验证、图谱查看、处理追踪和设置。
- **六页：** 资料；查看材料；检索测试；知识图谱；处理记录；设置。
- **读：** bases list/get、documents/detail/source/asset、jobs、chunk preview、search/find/open、graph、worker/parser/embedding/status。
- **写：** base create/update/delete preview/apply；document import/retry/delete；job cancel；reindex preview/rebuild；graph rebuild；embedding probe/impact；database preview/edit/apply/rollback。
- **owner：** `PawNativeApps.tsx`, `features/knowledge`; backend Knowledge control/library/worker/graph。
- **必须设计：** 无知识库/资料、逐文件 import/partial failure、worker/parser offline、processing、index stale、search empty、binary viewer error、rebuild pending。
- **不要：** “已导入”显示为“已可检索”；用静态管理表代替六条工作路径。

### 5. Input Studio

- **用户任务：** 管理输入法、词库、语音和输入记录，同时明确本地/显式联网与原生权限边界。
- **四页：** 输入法；词库；语音；输入记录。
- **读：** `input.source.get`, `input.lexicon.review`, `history.page/detail`；Voice 使用 `voiceCredentialStatus()` 与 native status。
- **写：** lexicon apply/rollback；history tombstone preview/apply/rollback；`saveVoiceCredentials()`, `runVoiceAction()`；输入设置走 configuration mutation。
- **owner：** `PawNativeApps.tsx`, `features/input-method`, `features/history`, `features/voice`; Squirrel/Rime/native host。
- **必须设计：** Squirrel/sidecar unavailable、Accessibility/Mic permission、credential configured/not-set、lexicon preview/rollback、history empty/redacted、Native receipt。
- **不要：** 把 Assistant candidate 偷偷替代或重排 Rime 解码；把语音权限/凭据画成假开关。

### 6. App Center

- **用户任务：** 理解扩展带来的能力、权限、来源和生效条件，再验证、预览和应用。
- **三页：** 已安装；目录；建议。
- **读：** tools、extensions list/catalog/proposals、lifecycle hooks、`agent.configuration.get` 能力默认值。
- **写：** extensions create/validate/preview/apply；lifecycle update；`agent.configuration.update`。
- **owner：** `PawNativeApps.tsx`, `features/plugins`, `features/paw-os/package-apps.ts`; Pi 拥有 Package loading。
- **必须设计：** Runtime unavailable、目录空、validation failure、权限披露、preview/confirm、restart needed、receipt/rollback。
- **不要：** 编造 package；把前端卡片当成任意可执行 Package；只做没有 mutation 的商店列表。

### 7. System Monitor

- **用户任务：** 从活动、上下文和诊断解释系统正在做什么、为什么这样做、哪里失败。
- **三页：** 活动；上下文；诊断。所有“Ego 轨迹”统一叫“Agent 轨迹”。
- **读/事件：** `observability.snapshot/events`, diagnostics runtime/predictor/models/job；上下文跨读 sessions、debug context、input source。
- **写：** diagnostics action preview/start。
- **owner：** `PawNativeApps.tsx`, `features/observability`, `features/context-debug`, `features/diagnostics`。
- **必须设计：** snapshot loading、filter empty、SSE reconnect/snapshot-required、diagnostic preview/job running/failed。
- **不要：** 做成通用 CPU 仪表盘；成为第二个 Runtime 控制面；显示无法解释来源的指标。

### 8. System Settings

- **用户任务：** 控制 Agent 默认行为、当前默认外观、产品配置、治理和审批，不把内部架构术语摊给用户。
- **当前五页：** Agent；外观；配置；治理；审批。**三主题切换 deferred，本轮只跑默认主题。**
- **读：** providers/OAuth、agent configuration、governance、roles/models/defaults、RoleBook、approvals、configuration schema/settings。
- **写：** Provider auth preview/apply/cancel；config preview/apply/rollback/import/backup/restore；role/RoleBook/default mutation；approval decide。
- **owner：** `PawNativeApps.tsx`, `features/configuration`, `features/governance`, `features/approvals`, `features/roles`; native Keychain 拥有秘密。
- **必须设计：** schema/capability loading、read-only host、credential set/not-set、OAuth pending、stale revision、preview/confirm、rollback、approval expired。
- **不要：** 把 token/Voice 凭据持久化进前端；继续花时间画三主题；用不可执行的设置行填页面。

### 9. Files

- **用户任务：** 选择 Session，在授权 workspace roots 内浏览目录、选择文件并预览真实内容。
- **读：** `agent.sessions.list`, `agent.session.workspace.list/read`；当前最多读取 64 KB 片段。
- **写：** 当前 Files 页面没有文件写路由。picker/reveal/media 是共享 transport 或 Agent 工作流，未接通前不要画成 Files 功能。
- **owner：** `features/files/PawOsFilesApp.tsx`, `features/agent/file-preview`, `features/agent/workspace`; backend `agent_workspace.py`。
- **必须设计：** 无 Session、未授权 root、空目录、逐路径 loading/error/retry、truncated、binary unsupported。
- **不要：** 假文件树；“本机磁盘”越权入口；编造 tags/snapshot/provenance mutation。

### 10. Browser

- **用户任务：** 在 PAWOS 同一窗口真正上网；人与 Agent 操作同一可见 tab/target；历史、设置、下载、权限反馈和 Agent 轨迹都可用。
- **真实页面：** tabs + 单层 chrome；网页 viewport；浏览历史；Browser 设置；菜单/find/download；可收起 Agent 轨迹。
- **typed route：** `browser.tabs`, `browser.traces`, `browser.snapshot.latest`, `browser.command`, `browser.stop`, `browser.managed.start`；其他 Browser routes 是合同能力，不能虚报当前已调用。
- **native：** Electron 使用隔离 `persist:paw-browser` webview/host bridge；非 Electron 才回退 backend snapshot/command。历史属于隔离 Chromium profile，设置由 host API 持久化。
- **owner：** `paw-os/apps/PawBrowserApp.tsx`, `paw-browser-host.ts`, `control-center-web/electron/`。
- **必须设计：** host absent/backend fallback、managed unavailable、busy/navigation error、tab empty、多标签滚动、280–400px 窗口、permission/download feedback、trace active/stopped。
- **不要：** 双层顶栏；截图桥冒充完整 Browser；把真实 tabs 压缩到不可点击；用整屏 media query 代替窗口 container query。

### 11. Terminal

- **用户任务：** 在 PAWOS 内嵌窗口使用真实 PTY；Pi 调后台 shell/bash 时可弹出关联的 process-terminal 卫星，但不打开 Ghostty 或 Terminal.app。
- **读：** `terminal.sessions.list`, cursor-based `terminal.session.read`；Pi background jobs 另读 list/get/logs。
- **写：** terminal create/write/resize/close；Pi job cancel 使用自己的 route。
- **owner：** `features/terminal/PawOsTerminalApp.tsx`, `features/paw-os/PawOsSatelliteHost.tsx`, `paw-os/runtime/runtime-tool-window.ts`; backend `system_terminal.py`, `agent_background_jobs.py`。
- **必须设计：** no session、create/close pending、running/exited、input/read/resize error、detached/cancelled、真实 cwd/shell/exit code。
- **不要：** 启动外部 App；把 PAW PTY 与 Pi background job 误绑成同一生命周期；用预写命令文本冒充终端。

## 14 个候选包：只能用什么、不能用什么

| 包 | 可迁移 | 必须纠正 |
| --- | --- | --- |
| `pawos-shell-wireframe-v1` | 单 chrome、信号稀缺、Overview/Focus 思路、状态矩阵 | 12 App 错误；暖纸/线稿已过时；固定 1280 画布和小字号不能用 |
| `pawos-shell-hifi-v1` | 冷白现代材料、前后台窗口层级 | 深色 Dock 已被最终纠正否决；静态绝对定位、12 图标、无 drag/resize/focus/route |
| `pawos-shell-living-v1` | 开窗揭幕、一次性到达信号、reduced-motion | 爪印品牌被拒；常驻呼吸和装饰包必须绑定真实状态 |
| `pawos-agent-tree-v1` | 局部折叠/结果摘要 | 整体树形流、假 IME 活动、小字号和固定画布不要迁移 |
| `pawos-agent-fx-v1` | 用户/Agent 分层、公开 Tool/结果卡、审批过渡、窄窗样例 | 无头像；接 `agent.session.*`；不展示私有推理；移除假文件/进度/审批 |
| `pawos-agent-trace-v1` 与最新轨迹截图 | Turn/event grouping、类型筛选、causal link、payload disclosure、Session 尾部状态 | 接真实 event/context trace；轨迹与对话分开；不要复制聊天原文；移除静态 filter 计数和演示事件 |
| `pawos-room-fx-v1` | 与 Agent 共享 renderer、Goal/WorkItem/Root 层级 | Room 不独立；审批/participant/WorkItem 接真实 routes；次要 rail 转卫星/披露 |
| `pawos-room-focus-full-v1` | 中央对话、四周卫星、FlowPacket 与投递账本空间语言 | 处理 0/1/5+ participant、resize/恢复/重叠；禁止固定 1440 坐标和假 packet |
| `pawos-brand-icons-v1 (1)` | 全彩 identity 与线性 action 分层、四尺寸图标墙方法 | 只保留 11 App；Room 无顶层砖；真实产品内做 16/24/32/48 光学校正 |
| `pawos-browser-terminal-v1` | Browser chrome/trace rail；Terminal 深色 PTY 材料与 run binding | 全部接真实 webview/PTY；不复制 MDN/历史/pid/output；窄窗用 container |
| `pawos-files-v1` | master-detail/preview/provenance 的视觉思路 | 只展示授权 workspace；无假 tags/snapshot/本机磁盘；窄窗不能固定四列 |
| `pawos-workbench-v1` | 依赖画布语法、WorkItem inspector、source/Room/artifact links | 补齐 overview/planning/WorkDocuments 三路径；节点使用真实 authority；长名不碰撞 |
| `pawos-memory-knowledge-v1` | 来源/引用/关系 inspector、master-detail reader | Memory 六页、Knowledge 六页都要补齐并接路由；移除 confidence/资料假数据 |
| `pawos-sys-apps-v1` | 逐 App 识别色、权限/来源卡、设置分组 | Input/App Center/Monitor/Settings 全部按上方真实功能重构；移除假包/指标/审批 |

## 设计与实现顺序（每个 App 都执行）

1. **三合同：** 用户任务；数据/动作 authority；可截图、可交互的验收状态。
2. **真实 IA：** 使用本文件的页面/模式，不从候选 HTML 或当前偶然 DOM 倒推。
3. **状态矩阵：** 至少覆盖 capability loading、empty、unavailable、permission、preview、pending/streaming、success、partial failure、rollback、reconnect、snapshot-required、stale revision 中适用项。
4. **窗口构图：** 先做常规窗，再做宽窗与 280–400px 窄窗；用 container query、minmax、真实滚动和优先级折叠。
5. **高保真：** 一个默认主题；正文和主要控件先可读，再加 App 识别色、材质、微交互和状态动效。
6. **源码实现：** 修改真实 TSX/CSS owner；复用 transport/reducer/native bridge；不新增 demo store。
7. **验证：** typecheck → Feature tests → production build → isolated Preview install → 真实前台逐页。

## 默认单主题视觉合同

- 冷白/雾灰系统画布，白色或高不透明度工作窗口，明亮悬浮 Dock 承托全彩 App identities；深色只用于 Terminal、代码或媒体等功能性局部。
- 11 个 App 使用独立识别色；identity 图标可以全彩 squircle，action/navigation 继续使用克制线性符号。
- Agent 无头像。普通工作面安静；“惊艳预算”集中在开窗空间连续性、Room Focus 和真实 FlowPacket 到达。
- App 顶部只有一层有效 chrome；内容导航不能再叠一个同权重标题栏。
- 正文以可持续阅读为准；不要以 9–11px 作为主要密度工具。
- Motion 只解释空间、状态、直接操控和真实事件；优先 transform/opacity、<300ms、可中断、支持 reduced-motion。

## 下一模型必须交付什么

- **必须：** 对现有项目文件的 patch/diff；逐 App changed-file 清单；对应真实 route/state 的说明；测试命令和结果；宽/常规/窄窗真实产品截图。
- **禁止：** 只有 HTML/PNG；复制 `pawos-*-v1` demo data；新建第二个 OS；Room App #12；假成功按钮；只改色/圆角/阴影；声称静态 QA 等于产品完成。
- **报告格式：** 每个 App 分开写 `visual migration / source wiring / tests-build / Preview install / foreground`，任何未验证项写 `unverified`。

## 当前基线与下一步

当前源码已经迁移候选中兼容的默认明亮 Shell、11 个全彩身份图标、App 识别色、Browser 多标签/窄窗修正和 Room Focus 层次；真实 owner 没有被 HTML 替换。请在此基线上逐 App 深化，不要重新起静态 demo。

完整 233 条 typed route 的 path/method/allowlist/response/binary/stream catalog 与最新前端源码将一起放在 `PAWOS_FRONTEND_MODEL_BUNDLE.md`；逐 App 的脱敏、源码一致渲染样例在 `PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md`。本文件负责愿景、功能和纠偏，数据样例负责正确渲染状态，代码包负责精确实现上下文。

交给下一模型时按此顺序上传：

1. `PAWOS_WEB_MODEL_APP_FUNCTION_HANDOFF.md`
2. `PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md`
3. `PAWOS_FRONTEND_MODEL_BUNDLE.md`

后两份不得覆盖第一份的最新需求；三份都明确要求修改真实 PAWOS 源码，不得另起 HTML。
