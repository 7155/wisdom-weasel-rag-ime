# PAWOS Frontend Vision And Function Interface Guide

## User Requirement Ledger

### IFACE-001 — 愿景必须先于接口和源码 | current / P0

- **Current controlling requirement:** 网页模型先理解 PAWOS 是一个以美、专注和真实 Agent 工作流为中心的个人操作系统，再看到逐 App 工作流、前端接口和实现源码。
- **User-visible acceptance:** 文档顺序固定为 `愿景 -> 逐 App 工作流 -> 前端状态合同 -> 完整接口目录 -> 实现源码`；外部模型不能只给现有静态页面换 CSS。
- **Must preserve:** “全部所有都是为了美”；“整个前端是为了美，你不用硬靠组合8的那幅画”；每个 App 都要从头到尾单独设计、统一系统语言但各有信息架构；字体、字号、图标、颜色、空间、动效和状态都要精心打磨。
- **Must not do:** 不做普通 SaaS dashboard，不做上世纪网页，不让 Composition 8 背景画替界面承担设计，不用单调色和通用线性图标凑数。
- **Source quotes:** “就是前端需要的多给他，还有主要是愿景”；“全部所有都是为了美”。来源：当前对话。

### IFACE-002 — 给前端完整真实功能，不让模型猜 | current / P0

- **Current controlling requirement:** 逐 App 说明真实读、写、事件、文件、二进制和 Native 能力，并附当前全部 233 条 typed route；页面和按钮必须接真实 owner，不得凭 mock HTML 发明功能。
- **User-visible acceptance:** Project、Agent/Room、Memory、Knowledge、Input、App Center、Monitor、Settings、Files、Browser、Terminal 都有愿景、真实工作流、route 覆盖和前端 owner；接口目录能直接查 pathId/method/path/allowlisted fields/response/stream/binary。
- **Must preserve:** Pi 是唯一 Agent Runtime；PAW 后端拥有 Room、Memory、Knowledge、Browser/Terminal 工具合同、SQLite、权限与 HTTP/SSE；前端只投影和操控，不复制第二套生命周期。
- **Must not do:** 不把“源码中有 route”写成“当前安装实例可用”，不绕过 capability/allowlist，不把接口名原样当 UI 文案，不造假成功态。
- **Source quote:** “把功能接口全部告诉他吧，他可能不知道后端那些功能”。来源：当前对话。

### IFACE-003 — 当前修正必须压过历史方向 | current / P0 correction

- **Current controlling requirement:** Browser 是 PAWOS 同窗内可真正上网并可由 Agent 控制的完整浏览器；Terminal 是同窗内嵌 App，后台 shell/bash 可弹出查看，但不打开 Ghostty 或新应用；Ego 轨迹更名为 Agent 轨迹；Browser/App 顶部不做重复双层栏。
- **Must preserve:** Room 卫星是一种专注模式：弱化背景、占满信息排布、强化当前 Room 的上下文和流转，不是普通多窗口。
- **Must not do:** 不恢复已撤销的 Ghostty 方案，不用截图交互桥作为最终 Browser，不把卫星窗做成互相遮挡的灰色小窗口。
- **Source quotes:** “终端不是打开新应用”；“那就不要Ghostty”；“卫星不应该只普通多窗口，而是一种模式”。来源：当前对话。

### IFACE-004 — 下一模型必须在真实 PAWOS 源码中实现，不再交独立 HTML | current / P0 correction

- **Current controlling requirement:** 外部模型收到本说明和最新前端包后，应直接修改真实 React/TypeScript/CSS owner，使用现有 registry、transport、routes、reducers、native bridge 和测试；不得把独立 HTML/PNG 当交付物。
- **Must preserve:** 顶层只有 11 个 App，Room 是 Agent 内的协作模式；设计先对齐用户任务、authority、状态矩阵和窗口适配，再做高保真。正文可读，宽/常规/窄窗都不能错行、乱位、遮挡或靠缩字硬塞。
- **Must not do:** 不以静态演示点击代替 mutation，不以截图 QA 代替安装态前台交互，不用假数据填满空态，不先套统一皮肤再猜功能。
- **Source quotes:** “为什么他不再os代码上完成，而是输出html”“你先更新项目，才能打包”“他当前问题就是很不精致，错行，乱位”“需求没对齐”。来源：当前对话。

### IFACE-005 — 本轮只完成默认单主题 | current / P0 scope correction

- 当前模型只设计、实现和验收一个默认主题；不要制作 Glacier / Ink Paper / Blueprint 变体，不要把主题切换当成当前工作，也不要为三套皮复制组件。
- 现有主题历史代码不是本轮删除目标，但它也不是完成证据。优先把默认主题下 11 个 App 的真实功能、排版、宽窄窗、状态和动效做精致；三主题留给后续独立需求。
- **Source quote:** “三主题不推进了，默认单主题跑通，后面才搞这个”。来源：当前对话。

### IFACE-006 — 默认主题是明亮现代 OS，不是深色 Shell | current / P0 correction

- 默认视觉必须轻、透、青春鲜活：冷白/柔白窗口、清楚深色文字、鲜活 App 身份色与轻盈深度。不得把深色 Dock、深色菜单栏或大面积暗底作为 OS 主身份。
- 深色只留给 Terminal、代码块、媒体等有功能意义的局部。Composition 8 退到极低存在感背景；PAW 使用字标/系统 identity，不使用爪印或抽象线条 Logo。
- **Source quote:** “你读对话记录，我完全不是这个设计，至少不是深色”。用户提供对话中的最终材料修正是“现代 OS 语言：轻、透、颜色青春鲜活”。

### IFACE-007 — 当前源码已经吸收候选 ZIP，下一模型从真实 owner 继续 | current / P0 handoff

- 14 个候选包的 12 个迁移面已按“视觉/布局/状态/图标/动效可迁，假后端/种子数据/临时路由/静态 HTML 壳不迁”合并进当前 TSX/CSS。
- 下一模型应直接精修 `PawWorkbenchMigrated`、`PawSessionWorkspace` / `PawContextTrace`、`PawRoomWorkspace`、`PawSystemAppsMigrated`、`PawBrowserApp`、`PawOsFilesApp`、`PawOsTerminalApp`、Memory 与 Knowledge 的当前 owner；不要重新创建 demo。
- 全彩 App 图标和 PAW 字标的 owner 是 `paw-os/shell/PawAppIcon.tsx` 与 `paw-app-icon.css`；Room 仍是 Agent 模式，不得从候选图标墙恢复第 12 个 App。

## Product Vision — Read This Before Any Code

PAWOS 的目标不是给管理后台套一层桌面边框，而是把个人 Agent、项目、记忆、知识、输入和工具做成一个真正可生活的操作系统。它首先要美：清晰、克制、富有节奏，能用精心选择的字体、颜色、图标、层次和可中断动效让复杂信息变得自然。每一个 App 都要按自己的核心对象与任务从头设计，同时共享同一套系统级比例、交互物理和状态语义。

前端不是第二个 Runtime。Pi 拥有 Session、对话历史、模型/Tool loop、compaction、Steer、Stop 和恢复；PAW 产品后端拥有 Room 编排、Memory、Knowledge、Browser/Terminal 工具合同、SQLite、权限和 HTTP/SSE；PAWOS 负责让这些真实能力可见、可理解、可操作。任何静态假数据、复制状态机或没有真实 mutation 的按钮都违背这个愿景。

### Visual and interaction north star

- **Typography first:** 全 OS 建立清晰字号阶梯、合适中英文字体与行高；正文不再缩小到看不清，信息密度由布局而非微型字体承担。
- **App-specific color:** 共享中性色、材质与深度规则，但每个 App 有自己的识别色和数据语义；避免一屏只剩灰白和青色描边。
- **Custom icon system:** 重做与当前艺术方向一致的图标，统一网格、笔画、圆角、光学尺寸和 active 状态，不复用不协调的通用图标拼盘。
- **Motion has meaning:** App 打开、层级切换、列表 mutation、事件流到达、Browser 导航、Room Focus 与卫星流转都要有物理连续性；支持 `prefers-reduced-motion`，禁止无意义常驻漂浮。
- **One chrome layer:** App 自己的导航应与 OS 窗口 chrome 协调，不能在顶部连续堆两个同等权重的栏。
- **Truthful states:** loading、empty、unavailable、permission denied、preview、applying、success、partial failure、rollback、reconnect、snapshot required 都是设计对象，不是最后补一个 toast。

## Reading Order For The Web Model

1. 先用本页愿景决定信息架构、视觉语言和动效性格。
2. 再按下面逐 App 工作流设计完整路径，不要从现有 DOM 结构反推产品。
3. 使用 transport/capabilities 和 typed route 接上真实功能；mutation 必须展示前置确认、进行中、结果和恢复。
4. 完整 route catalog 只用于实现时检索，不应成为界面文案或页面结构。
5. 最后阅读前端包中的真实 Feature 源码，复用数据/合同/状态 owner；可以重构表现层，但不能另造 Runtime。

## Per-App Vision And Real Workflows

下面每段的“typed route 覆盖”是该领域的 catalog 统计，不是 Feature 的完整依赖闭包。真实页面可能跨域读取配置、Session、RoleBook 或 Native bridge；实现时以 owner 源码和 `capabilities()` 为准，不能把分组数字当成“页面只会调用这些路由”。

### Project

**体验愿景：** 把项目概览、任务编排、工作文档做成三条真实路径；用户从当前目标进入任务，再进入有来源和结果的工作文档，不是三块统计卡。

**真实工作流：** 读取项目/计划投影；预览并执行 task/goal mutation；撤销或 rollback；注册、修复、重开、归档和受确认保护的擦除 WorkDocument；查看与管理唤醒计划及运行记录。

**typed route 覆盖（21）：** `overview.get`, `agent.wakeSchedules.list`, `agent.wakeSchedules.create`, `agent.wakeSchedule.runs`, `agent.wakeSchedule.action`, `planning.dashboard`, `planning.mutation.preview`, `planning.task.save`, `planning.goal.save`, `planning.task.action`, `planning.taskEvent.undo`, `planning.mutation.rollback`, `workDocuments.list`, `workDocuments.history.search`, `workDocuments.get`, `workDocuments.register`, `workDocuments.archive`, `workDocuments.repair`, `workDocuments.reopen`, `workDocuments.erase.preview`, `workDocuments.erase`

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawWorkbenchMigrated.tsx`, `control-center-web/src/features/overview`, `control-center-web/src/features/planning`, `control-center-web/src/features/work-documents`, `control-center-web/src/features/project-field`

### Agent / Room

**体验愿景：** Agent 以对话为第一视觉对象，无头像；Pi Session 的历史、模型/Tool loop、compaction、Steer、Stop 与恢复只做真实投影。Room Focus 是专注当前 Room 的全屏信息编排模式，不是把普通小窗堆满桌面；卫星窗展示真实伙伴上下文、任务和消息流。

**真实工作流：** 创建/选择/修改/归档/删除 Session；发送、改写、fork、stop、compact、切换模型与 thinking；处理 review 和 UI request；显示工作流、上下文、附件、后台任务和 Agent trace。Room 支持成员、话题、产物、WorkItem、消息、steer、abort、历史和事件流。新输入必须清除旧失败/重试操作。

**typed route 覆盖（74）：** `agent.runtime.get`, `agent.runtime.ensure`, `agent.sessions.list`, `agent.sessions.create`, `agent.session.snapshot`, `agent.session.rename`, `agent.session.archive`, `agent.session.mode.update`, `agent.session.capability-policy.update`, `agent.session.delete`, `agent.session.prompt`, `agent.session.rewrite`, `agent.session.forks.list`, `agent.session.forks.create`, `agent.session.abort`, `agent.session.review.resolve`, `agent.session.ui.resolve`, `agent.session.compact`, `agent.session.workflow.get`, `agent.session.goal.mutate`, `agent.session.commands`, `agent.session.command.invoke`, `agent.session.models`, `agent.session.model.select`, `agent.session.thinking.select`, `agent.session.events`, `agent.session.backgroundJobs.list`, `agent.session.backgroundJob.get`, `agent.session.backgroundJob.logs`, `agent.session.backgroundJob.cancel`, `agent.session.intercom.list`, `agent.session.intercom.send`, `agent.session.contextItems.list`, `agent.session.contextItems.ack`, `agent.session.contextTraces.list`, `agent.session.contextTrace.get`, `agent.session.debugContext.get`, `agent.artifact.get`, `agent.media.list`, `agent.media.preview`, `agent.deep-search`, `agent.rooms.list`, `agent.rooms.create`, `agent.room.get`, `agent.room.snapshot`, `agent.room.history`, `agent.room.archive`, `agent.room.participant.add`, `agent.room.participant.remove`, `agent.room.participant.update`, `agent.room.delete`, `agent.room.message`, `agent.room.participant.steer`, `agent.room.abort`, `agent.room.events`, `agent.collaborationProfile.get`, `agent.collaborationProfile.command`, `agent.room.topics`, `agent.room.topic.create`, `agent.room.topic.update`, `agent.room.artifacts`, `agent.room.artifact.add`, `agent.room.artifact.update`, `agent.room.workItems.list`, `agent.room.workItem.create`, `agent.room.workItem.get`, `agent.room.workItem.reassign`, `agent.subagents.templates`, `agent.subagents.list`, `agent.subagents.create`, `agent.subagent.get`, `agent.subagent.console`, `agent.subagent.control`, `agent.subagent.abort`

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx`, `control-center-web/src/paw-os/apps/PawContextTrace.tsx`, `control-center-web/src/paw-os/apps/PawRoomWorkspace.tsx`, `control-center-web/src/features/agent`, `control-center-web/src/features/rooms`, `control-center-web/src/features/context-debug`, `control-center-web/src/features/approvals`

### Memory

**体验愿景：** Memory 是用户的第二大脑，不是空时间线。六个页面应共同回答：记住了什么、从哪里来、彼此如何关联、何时形成、如何治理，以及用户希望系统以后怎样记。偏好必须真实持久化。

**真实工作流：** 显示摘要、页面、引用、实体与关系图；编辑或处置来源；构建/批准/拒绝活动时间线；执行记忆维护；通过 preview/apply/rollback 归档记忆簿；读取个人上下文可观察性与来源。

**typed route 领域覆盖（19）：** `agent.personalContext.observability`, `agent.memoryMaintenance.run`, `agent.memoryMaintenance.trigger`, `agent.memorySources.list`, `memory.summary`, `memory.pages`, `memory.reference.get`, `memory.graph.get`, `memory.entity.get`, `memory.edit`, `memory.source.disposition`, `memory.book.archive.preview`, `memory.book.archive.apply`, `memory.book.archive.rollback`, `memory.activityTimeline.get`, `memory.activityTimeline.calendar`, `memory.activityTimeline.build`, `memory.activityTimeline.approve`, `memory.activityTimeline.reject`。偏好页还使用 `configuration.settings/preview/apply`，伙伴记忆使用 roles/RoleBook 投影。

**当前前端 owner：** `control-center-web/src/features/memory/MemoryPreferences.tsx`, `control-center-web/src/features/memory`

### Knowledge

**体验愿景：** Knowledge 是可工作的知识空间：知识库选择器，以及资料、查看材料、检索测试、知识图谱、处理记录、设置六个真实页面。页面必须围绕用户选择的知识库连续工作，不能用一张静态管理表冒充。

**真实工作流：** 创建/更新/删除知识库；导入、打开原文、查看资产、重试/删除文档；看任务并取消；预览 chunk；search/find/open；重建索引和图谱；检查 worker/parser/embedding；数据库变更遵循 preview/edit/apply/rollback。

**typed route 覆盖（39）：** `agent.knowledge.search`, `agent.knowledgeGovernance.read`, `agent.knowledge.read`, `knowledge.start`, `knowledge.cancel`, `knowledge.status`, `knowledge.routeStatus`, `knowledge.database.apply.preview`, `knowledge.database.draft.edit`, `knowledge.database.apply`, `knowledge.database.rollback`, `knowledgeBases.list`, `knowledgeBases.create`, `knowledgeBases.get`, `knowledgeBases.update`, `knowledgeBases.delete.preview`, `knowledgeBases.delete.apply`, `knowledgeBases.documents.list`, `knowledgeBases.document.import`, `knowledgeBases.document.retry`, `knowledgeBases.document.delete`, `knowledgeBases.document.get`, `knowledgeBases.document.source`, `knowledgeBases.asset.get`, `knowledgeBases.jobs.list`, `knowledgeBases.job.cancel`, `knowledgeBases.chunkPreview`, `knowledgeBases.search`, `knowledgeBases.find`, `knowledgeBases.open`, `knowledgeBases.reindexPreview`, `knowledgeBases.rebuild`, `knowledgeBases.graph.get`, `knowledgeBases.graph.rebuild`, `knowledgeWorker.health`, `knowledgeParsers.list`, `knowledgeEmbedding.profile`, `knowledgeEmbedding.probe`, `knowledgeEmbedding.impact`

**当前前端 owner：** `control-center-web/src/features/knowledge`

### Input

**体验愿景：** 输入法、词库、语音、输入记录必须是一个连贯工具，而不是诊断后台。历史和设置要能看见、能操作，并明确本地/显式联网边界。

**真实工作流：** 读取输入源；审阅词库后 apply/rollback；分页查看输入记录、详情和受确认保护的 tombstone；Voice 使用受能力约束的凭据状态、保存与原生动作。

**typed route 领域覆盖（9）：** `input.source.get`, `input.lexicon.review`, `input.lexicon.apply`, `input.lexicon.rollback`, `history.page`, `history.detail`, `history.tombstone.preview`, `history.tombstone.apply`, `history.tombstone.rollback`。Voice 另走 `voiceCredentialStatus()`, `saveVoiceCredentials()`, `runVoiceAction()` 等受信 Native transport。

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawSystemAppsMigrated.tsx`, `control-center-web/src/features/input-method`, `control-center-web/src/features/history`, `control-center-web/src/features/voice`

### App Center

**体验愿景：** App Center 是能力扩展中心：已安装、目录、建议都必须连接真实 mutation；用户应清楚扩展会得到什么能力、需要什么权限、何时生效。

**真实工作流：** 列出工具、扩展、目录和提案；创建、验证、预览和应用扩展；查看和更新 lifecycle hooks。前端必须保留验证、预览、应用结果和恢复语义。

**typed route 领域覆盖（10）：** `agent.tools.list`, `agent.extensions.list`, `agent.extensions.catalog`, `agent.extensions.create`, `agent.extensions.proposals`, `agent.extensions.validate`, `agent.extensions.preview`, `agent.extensions.apply`, `agent.lifecycleHooks.get`, `agent.lifecycleHooks.update`。当前页面还读取/更新 `agent.configuration.get/update` 中的能力默认值。

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawSystemAppsMigrated.tsx`, `control-center-web/src/features/plugins`, `control-center-web/src/features/paw-os/package-apps.ts`

### Monitor

**体验愿景：** Monitor 用活动、上下文、诊断三条路径解释系统正在做什么、为什么这样做、哪里失败；Ego 轨迹统一改为 Agent 轨迹。

**真实工作流：** 读取观察快照并续接事件流；筛选 session/room/trace/category/status；显示 Runtime、predictor、model 诊断；受控诊断动作先 preview，再启动并跟踪 job。

**typed route 领域覆盖（8）：** `observability.snapshot`, `observability.events`, `diagnostics.runtime`, `diagnostics.predictor`, `diagnostics.models`, `diagnostics.action.preview`, `diagnostics.action.start`, `diagnostics.action.job`。上下文页还跨读 `agent.sessions.list`, `agent.session.debugContext.get`, `input.source.get`。

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawSystemAppsMigrated.tsx`, `control-center-web/src/features/observability`, `control-center-web/src/features/context-debug`, `control-center-web/src/features/diagnostics`

### Settings

**体验愿景：** Settings 覆盖 Agent、外观、配置、治理、审批。它是用户控制系统行为的地方，而不是把产品内部架构术语直接摊给用户。

**真实工作流：** 读取 schema/current settings；preview/apply/rollback；导入、备份、恢复；管理 Provider auth/OAuth、Agent 配置、角色与 Runtime defaults、RoleBook 激活/回滚、治理和审批。

**typed route 覆盖（32）：** `agent.providers.get`, `agent.provider.auth.preview`, `agent.provider.auth.apply`, `agent.provider.oauth.status`, `agent.provider.oauth.cancel`, `agent.configuration.get`, `agent.configuration.update`, `agent.governance.read`, `agent.roles.list`, `agent.roles.create`, `agent.roles.update`, `agent.roles.archive`, `agent.role.models`, `agent.role.runtimeDefaults.update`, `agent.roleBook.get`, `agent.roleBook.activation.preview`, `agent.roleBook.activation.apply`, `agent.roleBook.activation.rollback`, `agent.roleBook.draft.decision`, `agent.approvals.list`, `agent.approval.get`, `agent.approval.decide`, `configuration.settings`, `configuration.schema`, `configuration.settings.preview`, `configuration.settings.apply`, `configuration.settings.rollback`, `configuration.import.preview`, `configuration.import.apply`, `configuration.backup.export`, `configuration.restore.preview`, `configuration.restore.apply`

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawSystemAppsMigrated.tsx`, `control-center-web/src/features/configuration/PawOsAppearanceSettings.tsx`, `control-center-web/src/features/configuration`, `control-center-web/src/features/governance`, `control-center-web/src/features/approvals`, `control-center-web/src/features/roles`

### Files

**体验愿景：** Files 是真实工作区入口：目录树、选择、预览、错误和空态都要精心设计；不得用假文件列表。

**真实工作流：** 当前 Files 页面先选择 Session，再按授权 root/path 读取目录与最多 64 KB 的文件片段。owner-bound picker、Agent 产物/媒体预览与 `revealPath()` 是共享 transport/Agent 工作流能力，目前不能冒充为 Files 页面已接通写入或系统磁盘管理。路径错误、权限、截断、二进制和空目录都必须有专用状态。

**typed route 领域覆盖（2）：** `agent.session.workspace.list`, `agent.session.workspace.read`；当前页面还读取 `agent.sessions.list`。

**当前前端 owner：** `control-center-web/src/features/files/PawOsFilesApp.tsx`, `control-center-web/src/features/agent/file-preview`, `control-center-web/src/features/agent/workspace`

### Browser

**体验愿景：** Browser 是 PAWOS 同窗内可真正上网的完整浏览器，具有 tabs、地址栏、导航、历史、设置、下载/权限反馈，并与 Agent 控制同一个可见目标。不要双层顶栏，也不要截图桥伪装浏览器。

**真实工作流：** Electron 主路径使用隔离 `persist:paw-browser` webview/host bridge，人与 Agent 操作同一可见 target；读取 tabs/trace，导航、设置、缓存、下载、截图和历史。非 Electron 才使用 backend snapshot/command fallback；当前组件实际调用 `browser.tabs`, `browser.traces`, `browser.snapshot.latest`, `browser.command`, `browser.stop`, `browser.managed.start`，其余 route 是合同能力而非当前页面已调用。二进制快照不能冒充最终 Browser 交互面。

**typed route 覆盖（9）：** `browser.status`, `browser.tabs`, `browser.snapshot.latest`, `browser.snapshot.image`, `browser.traces`, `browser.command`, `browser.stop`, `browser.managed.start`, `browser.managed.stop`

**当前前端 owner：** `control-center-web/src/paw-os/apps/PawBrowserApp.tsx`, `control-center-web/src/paw-os/apps/paw-browser-host.ts`, `control-center-web/electron`; `control-center-web/src/features/browser` 仅作 Feature 导出边界

### Terminal

**体验愿景：** Terminal 是 PAWOS 内嵌 App，不打开 Ghostty 或新的外部应用。Pi 调用后台 shell/bash 时可弹出当前会话的可见终端，并与 Agent 运行上下文关联。

**真实工作流：** 列出/创建 Terminal Session；按 cursor 轮询增量读取、写入、resize、close。Agent 后台 shell 另通过 background job 的 list/get/logs/cancel 投影为 process-terminal 卫星；两条路径可以关联但不共享或复制同一个生命周期。

**typed route 覆盖（6）：** `terminal.sessions.list`, `terminal.session.create`, `terminal.session.read`, `terminal.session.write`, `terminal.session.resize`, `terminal.session.close`

**当前前端 owner：** `control-center-web/src/features/terminal/PawOsTerminalApp.tsx`

### Shared control plane

所有 App 先经 bootstrap、capabilities 和 health 建立真实可用边界，再从 control events 衔接增量状态。任何 App 都不得绕过 route allowlist 自由拼 URL。

**typed route 覆盖（4）：** `control.bootstrap`, `control.capabilities`, `control.events`, `system.health`

## Frontend State Contract

每个真实路径至少设计以下适用状态，不能只画理想完成态：

| state | required behavior |
| --- | --- |
| capability loading | 首屏先确定 host、route 和 native 能力；保持骨架稳定，不闪现不可用按钮。 |
| empty | 说明当前对象为何为空，并只给真实下一步。Memory/History/Knowledge 不得用大块空白收场。 |
| unavailable | 明确当前 host 没有能力、服务未启动或 route 不存在；不要伪装成功。 |
| permission required | 解释权限用途，通过受批准动作进入系统设置或重试；不自动扩大权限。 |
| preview / confirmation | 危险或可回滚 mutation 先展示影响、token/revision/receipt 和确认条件。 |
| pending / streaming | 显示真实执行阶段、可停止边界和增量信息；新输入清理旧失败/重试控件。 |
| success | 将 receipt、revision 或新快照并回真实投影，不用永久成功 banner 占位。 |
| partial failure | 精确到文件、成员、工具或步骤，保留已成功结果和可重试项。 |
| rollback / undo | 仅在真实 rollbackId/undo route 存在时出现；展示回滚进行中和最终投影。 |
| reconnect | SSE 断线显示轻量连接状态，按 lastEventId 续接；避免重复消息和乱序。 |
| snapshot required | 丢失增量时重新取 snapshot 后再续接，不把旧本地状态当权威。 |
| stale revision | 停止覆盖写入，刷新 owner 投影并让用户重新确认差异。 |

### Contract rules that shape the UI

- `pathId` 是跨 Web/Native 的固定权威；页面不能接收运行时 URL 后自由请求。
- 只发送 route 声明的 params/query/body 字段；required 字段在动作进入 pending 前校验。
- `binary: true` 的内容必须使用对应 typed transport method，不经普通 JSON request。
- Session/Room/Knowledge 的文件回执必须保留 owner binding；不要让一个附件悄悄跨 owner 复用。
- `capabilities().routeIds` 与 `native` flags 决定动作是否展示/可用；源码目录存在不等于当前实例可用。
- SSE observer 必须实现 reconnect 和 snapshotRequired；动画不能掩盖断线、回补和顺序变化。
- Provider token、Voice 凭据、私有历史和数据库内容不进入前端持久层或设计模型样例。

## Frontend Transport And Native Surface

来源：`control-center-web/src/platform/transport.ts`。这些方法描述前端能请求什么；`FrontendCapabilities` 决定当前 host 实际允许什么。

| surface | frontend purpose | required UI behavior |
| --- | --- | --- |
| `capabilities()` | 能力发现 | 先读 routeIds/features/native；不可假设安装态能力。 |
| `request()` | typed route 请求 | 只传 pathId 和 allowlisted params/query/body。 |
| `subscribe()` | SSE 事件 | 处理 open/reconnect/snapshotRequired，并以快照恢复。 |
| `browserSnapshotImageUrl()` | Browser 二进制快照 URL | 仅对合法 snapshotId；不是 Browser 的交互替身。 |
| `agentMediaContentUrl()` | Agent owner-bound 媒体 URL | Session/Room owner 必须唯一。 |
| `pickFiles()` | 文件/目录选择 | purpose + sessionId/roomId/kbId 绑定回执。 |
| `pasteImages()` | 粘贴图像导入 | 导入到 Session 或 Room，不能同时归属两者。 |
| `importKnowledgeDocuments()` | 知识文档导入 | 返回 kbId/documentId/hash/status；展示逐文件结果。 |
| `readKnowledgeAsset()` | 读取知识资产 | typed Blob；显示 mime/size/hash 与错误状态。 |
| `readKnowledgeDocumentSource()` | 读取知识原文 | typed Blob；用于真实材料查看器。 |
| `revealPath()` | 在系统中显示路径 | 仅 capability 为真时提供动作。 |
| `runApprovedExternalAction()` | 执行已批准外部动作 | 需要 receipt/hash；只展示 allowlisted action。 |
| `voiceCredentialStatus()` | Voice 凭据状态 | 只显示是否配置，不回显秘密。 |
| `saveVoiceCredentials()` | 保存 Voice 凭据 | 通过受信宿主/Keychain；前端不持久化 token。 |
| `runVoiceAction()` | Voice 原生动作 | 启动/停止/重载/权限与设置动作，展示真实 receipt。 |
| `dispose()` | 释放 transport | App/host teardown 时取消连接与资源。 |

## Complete Route Catalog (233)

此表是当前前端 typed authority 的逐条投影，不证明某个安装实例已启用对应 capability。UI 仍须先检查 `capabilities()`。

| pathId | App | method | path | params | query | required query | body | required body | response / stream / binary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `control.bootstrap` | Shared control plane | `GET` | `/api/agent/control/bootstrap` | — | — | — | — | — | — |
| `control.capabilities` | Shared control plane | `GET` | `/api/agent/control/capabilities` | — | — | — | — | — | — |
| `control.events` | Shared control plane | `GET` | `/api/agent/events` | — | `lastEventId` | `lastEventId` | — | — | SSE `control` |
| `system.health` | Shared control plane | `GET` | `/api/health` | — | — | — | — | — | — |
| `input.source.get` | Input | `GET` | `/api/input-source` | — | — | — | — | — | — |
| `input.lexicon.review` | Input | `GET` | `/api/rime-lexicon/review` | — | `limit`, `project` | — | — | — | — |
| `input.lexicon.apply` | Input | `POST` | `/api/rime-lexicon/apply` | — | — | — | `reviewToken`, `selectedKeys`, `confirmText`, `project`, `limit` | `reviewToken`, `selectedKeys`, `confirmText` | — |
| `input.lexicon.rollback` | Input | `POST` | `/api/rime-lexicon/rollback` | — | — | — | `rollbackId` | `rollbackId` | — |
| `observability.snapshot` | Monitor | `GET` | `/api/observability/snapshot` | — | `limit`, `beforeSequence`, `sessionId`, `roomId`, `traceId`, `category`, `status` | — | — | — | contract `observation-snapshot.v1` |
| `observability.events` | Monitor | `GET` | `/api/observability/events` | — | `lastEventId`, `sessionId`, `roomId`, `traceId`, `category`, `status` | `lastEventId` | — | — | SSE `observation` |
| `overview.get` | Project | `GET` | `/api/overview` | — | — | — | — | — | — |
| `agent.runtime.get` | Agent / Room | `GET` | `/api/agent/runtime` | — | — | — | — | — | contract `agent-runtime.v1` |
| `agent.runtime.ensure` | Agent / Room | `POST` | `/api/agent/runtime/ensure` | — | — | — | `sessionId` | `sessionId` | — |
| `agent.providers.get` | Settings | `GET` | `/api/agent/providers` | — | — | — | — | — | — |
| `agent.provider.auth.preview` | Settings | `POST` | `/api/agent/providers/auth/preview` | — | — | — | `provider`, `action` | `provider`, `action` | — |
| `agent.provider.auth.apply` | Settings | `POST` | `/api/agent/providers/auth/apply` | — | — | — | `previewToken`, `confirmText`, `apiKey` | `previewToken`, `confirmText` | — |
| `agent.provider.oauth.status` | Settings | `GET` | `/api/agent/providers/oauth/status` | — | `loginId` | `loginId` | — | — | — |
| `agent.provider.oauth.cancel` | Settings | `POST` | `/api/agent/providers/oauth/cancel` | — | — | — | `loginId` | `loginId` | — |
| `agent.configuration.get` | Settings | `GET` | `/api/agent/configuration` | — | — | — | — | — | — |
| `agent.configuration.update` | Settings | `POST` | `/api/agent/configuration` | — | — | — | `expectedRevision`, `changes`, `updatedBy` | `expectedRevision`, `changes` | — |
| `agent.sessions.list` | Agent / Room | `GET` | `/api/agent/sessions` | — | `includeArchived`, `includeInternal`, `limit` | — | — | — | — |
| `agent.sessions.create` | Agent / Room | `POST` | `/api/agent/sessions` | — | — | — | `title`, `mode`, `roleId`, `roleVersion`, `modelProfile`, `toolProfileVersion`, `executionMode`, `workspaceRoots`, `workspaceScopeConfirmation`, `dangerousModeConfirmation` | — | — |
| `agent.session.snapshot` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/messages` | `sessionId` | `view` | — | — | — | — |
| `agent.session.workspace.list` | Files | `GET` | `/api/agent/sessions/:sessionId/workspace` | `sessionId` | `path`, `depth`, `limit` | — | — | — | — |
| `agent.session.workspace.read` | Files | `GET` | `/api/agent/sessions/:sessionId/workspace-file` | `sessionId` | `path`, `offset`, `limit` | `path` | — | — | — |
| `agent.session.rename` | Agent / Room | `PATCH` | `/api/agent/sessions/:sessionId` | `sessionId` | — | — | `title` | `title` | — |
| `agent.session.archive` | Agent / Room | `PATCH` | `/api/agent/sessions/:sessionId` | `sessionId` | — | — | `archived` | `archived` | — |
| `agent.session.mode.update` | Agent / Room | `PATCH` | `/api/agent/sessions/:sessionId` | `sessionId` | — | — | `mode`, `executionMode`, `workspaceRoots`, `workspaceScopeConfirmation`, `toolProfileVersion`, `toolAllowlistMode`, `allowedTools`, `dangerousModeConfirmation`, `projectContextEnabled`, `piSkillsEnabled`, `codexSkillsEnabled` | `mode` | — |
| `agent.session.capability-policy.update` | Agent / Room | `PATCH` | `/api/agent/sessions/:sessionId` | `sessionId` | — | — | `capabilityDisclosurePreferences` | `capabilityDisclosurePreferences` | — |
| `agent.session.delete` | Agent / Room | `DELETE` | `/api/agent/sessions/:sessionId` | `sessionId` | — | — | — | — | — |
| `agent.session.prompt` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/prompt` | `sessionId` | — | — | `message`, `attachments`, `clientMessageId`, `retryOfClientMessageId`, `delivery` | `message` | — |
| `agent.session.rewrite` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/rewrite` | `sessionId` | — | — | `entryId`, `message`, `attachments`, `clientMessageId` | `entryId`, `message` | — |
| `agent.session.forks.list` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/forks` | `sessionId` | — | — | — | — | contract `agent-session-fork-candidates.v1` |
| `agent.session.forks.create` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/forks` | `sessionId` | — | — | `entryId`, `title` | `entryId` | contract `agent-session-fork-create.v1` |
| `agent.session.abort` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/abort` | `sessionId` | — | — | — | — | — |
| `agent.session.review.resolve` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/review` | `sessionId` | — | — | `runId`, `decision` | `runId`, `decision` | — |
| `agent.session.ui.resolve` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/ui-response` | `sessionId` | — | — | `requestId`, `value`, `confirmed`, `cancelled`, `resolutionSource` | `requestId` | — |
| `agent.session.compact` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/compact` | `sessionId` | — | — | `instructions` | — | — |
| `agent.session.workflow.get` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/workflow` | `sessionId` | — | — | — | — | contract `agent-workflow-state.v1` |
| `agent.session.goal.mutate` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/goal` | `sessionId` | — | — | `action`, `expectedRevision`, `confirmed`, `objective`, `successCriteria`, `evidenceExpectations`, `tokenBudget`, `timeBudgetMs`, `summary`, `reason`, `evidence` | `action` | contract `agent-workflow-state.v1` |
| `agent.session.commands` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/commands` | `sessionId` | — | — | — | — | — |
| `agent.session.command.invoke` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/commands` | `sessionId` | — | — | `command` | `command` | — |
| `agent.session.models` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/models` | `sessionId` | — | — | — | — | contract `agent-model-catalog.v1` |
| `agent.session.model.select` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/model` | `sessionId` | — | — | `provider`, `modelId` | `provider`, `modelId` | — |
| `agent.session.thinking.select` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/thinking` | `sessionId` | — | — | `level` | `level` | — |
| `agent.session.events` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/events` | `sessionId` | `lastEventId` | `lastEventId` | — | — | SSE `agent` |
| `agent.session.backgroundJobs.list` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/background-jobs` | `sessionId` | `limit`, `status` | — | — | — | — |
| `agent.session.backgroundJob.get` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/background-jobs/:jobId` | `sessionId`, `jobId` | — | — | — | — | — |
| `agent.session.backgroundJob.logs` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/background-jobs/:jobId/logs` | `sessionId`, `jobId` | `cursor`, `limitBytes` | — | — | — | — |
| `agent.session.backgroundJob.cancel` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/background-jobs/:jobId/cancel` | `sessionId`, `jobId` | — | — | `reason`, `roomTurnId` | — | — |
| `agent.session.intercom.list` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/intercom` | `sessionId` | `status`, `limit` | — | — | — | — |
| `agent.session.intercom.send` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/intercom` | `sessionId` | — | — | `kind`, `targetParticipantId`, `clientMessageId`, `replyTo`, `content` | `kind`, `clientMessageId`, `content` | — |
| `agent.session.contextItems.list` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/context-items` | `sessionId` | `status`, `limit` | — | — | — | — |
| `agent.session.contextItems.ack` | Agent / Room | `POST` | `/api/agent/sessions/:sessionId/context-items/:itemId/ack` | `sessionId`, `itemId` | — | — | — | — | — |
| `agent.session.contextTraces.list` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/context-traces` | `sessionId` | `limit` | — | — | — | — |
| `agent.session.contextTrace.get` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/context-traces/:traceId` | `sessionId`, `traceId` | — | — | — | — | contract `agent-context-trace.v1` |
| `agent.session.debugContext.get` | Agent / Room | `GET` | `/api/agent/sessions/:sessionId/debug-context` | `sessionId` | `turnId` | — | — | — | — |
| `agent.artifact.get` | Agent / Room | `GET` | `/api/agent/artifacts/:artifactId` | `artifactId` | `sessionId`, `limit` | `sessionId` | — | — | — |
| `agent.media.list` | Agent / Room | `GET` | `/api/agent/media` | — | `sessionId`, `limit` | `sessionId` | — | — | — |
| `agent.media.preview` | Agent / Room | `GET` | `/api/agent/media/:mediaId/preview` | `mediaId` | `sessionId`, `sha256` | `sessionId` | — | — | contract `agent-file-preview.v1` |
| `agent.deep-search` | Agent / Room | `POST` | `/api/agent/deep-search` | — | — | — | `query`, `privacyDisposition`, `context`, `frontAppBundleId`, `contextSource`, `evidence` | `query`, `privacyDisposition` | — |
| `agent.rooms.list` | Agent / Room | `GET` | `/api/agent/rooms` | — | `includeArchived`, `limit` | — | — | — | — |
| `agent.rooms.create` | Agent / Room | `POST` | `/api/agent/rooms` | — | — | — | `title`, `roomKind`, `avatar`, `description`, `scenarioPrompt`, `participants`, `routingPolicy`, `routingConfig`, `moderatorRoleId`, `workspaceRoots`, `executionMode`, `workspaceScopeConfirmation`, `dangerousModeConfirmation` | `participants` | — |
| `agent.room.get` | Agent / Room | `GET` | `/api/agent/rooms/:roomId` | `roomId` | — | — | — | — | — |
| `agent.room.snapshot` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/snapshot` | `roomId` | — | — | — | — | contract `agent-room-snapshot.v1` |
| `agent.room.history` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/history` | `roomId` | `beforeSequence`, `limit` | — | — | — | contract `agent-room-event-page.v1` |
| `agent.room.archive` | Agent / Room | `PATCH` | `/api/agent/rooms/:roomId` | `roomId` | — | — | `archived`, `title`, `roomKind`, `avatar`, `description`, `scenarioPrompt`, `routingPolicy`, `routingConfig`, `moderatorParticipantId`, `executionMode`, `workspaceScopeConfirmation`, `dangerousModeConfirmation` | — | — |
| `agent.room.participant.add` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/participants` | `roomId` | — | — | `roleId`, `roleVersion`, `collaborationRole` | `roleId` | — |
| `agent.room.participant.remove` | Agent / Room | `PATCH` | `/api/agent/rooms/:roomId/participants` | `roomId` | — | — | `participantId` | `participantId` | — |
| `agent.room.participant.update` | Agent / Room | `PATCH` | `/api/agent/rooms/:roomId/participants` | `roomId` | — | — | `participantId`, `collaborationRole` | `participantId`, `collaborationRole` | — |
| `agent.room.delete` | Agent / Room | `DELETE` | `/api/agent/rooms/:roomId` | `roomId` | — | — | `confirmTitle` | `confirmTitle` | — |
| `agent.room.message` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/messages` | `roomId` | — | — | `message`, `clientMessageId`, `retryOfRootId`, `participantIds`, `workItemId`, `attachmentIds`, `answerToPostId`, `answerToRootId` | `message` | — |
| `agent.room.participant.steer` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/steer` | `roomId` | — | — | `action`, `rootId`, `participantId`, `clientActionId`, `message` | `action`, `rootId`, `clientActionId`, `message` | — |
| `agent.room.abort` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/abort` | `roomId` | — | — | `roomTurnId`, `clientRequestId` | `roomTurnId`, `clientRequestId` | — |
| `agent.room.events` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/events` | `roomId` | `lastEventId` | `lastEventId` | — | — | SSE `room` |
| `agent.collaborationProfile.get` | Agent / Room | `GET` | `/api/agent/collaboration-profiles/:profileId` | `profileId` | — | — | — | — | contract `collaboration-profile-projection.v1` |
| `agent.collaborationProfile.command` | Agent / Room | `POST` | `/api/agent/collaboration-profiles/commands` | — | — | — | `schemaVersion`, `commandId`, `action`, `idempotencyKey`, `actorRef`, `profileId`, `candidateId`, `contentHash`, `expectedPointerRevision`, `activationScope`, `adminConfirmation`, `payload`, `createdAtMs` | `schemaVersion`, `commandId`, `action`, `idempotencyKey`, `actorRef`, `payload`, `createdAtMs` | contract `collaboration-profile-command-receipt.v1` |
| `agent.knowledge.search` | Knowledge | `POST` | `/api/agent/sessions/:sessionId/knowledge-search` | `sessionId` | — | — | `query`, `limit`, `retrievalReceiptId`, `createdAtMs` | `query` | — |
| `agent.governance.read` | Settings | `GET` | `/api/agent/governance` | — | `scopeKey` | — | — | — | — |
| `agent.knowledgeGovernance.read` | Knowledge | `GET` | `/api/agent/knowledge-governance` | — | — | — | — | — | — |
| `agent.knowledge.read` | Knowledge | `POST` | `/api/agent/sessions/:sessionId/knowledge-read` | `sessionId` | — | — | `retrievalReceiptId`, `claimRef`, `expectedHash` | `retrievalReceiptId`, `claimRef`, `expectedHash` | — |
| `agent.room.topics` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/topics` | `roomId` | `includeArchived` | — | — | — | — |
| `agent.room.topic.create` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/topics` | `roomId` | — | — | `title`, `summary` | `title` | — |
| `agent.room.topic.update` | Agent / Room | `PATCH` | `/api/agent/rooms/:roomId/topics` | `roomId` | — | — | `topicId`, `title`, `summary`, `activate`, `archived` | `topicId` | — |
| `agent.room.artifacts` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/artifacts` | `roomId` | `includeArchived`, `topicId`, `limit` | — | — | — | — |
| `agent.room.artifact.add` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/artifacts` | `roomId` | — | — | `path`, `displayName`, `topicId`, `mediaType`, `participantId` | `path` | — |
| `agent.room.artifact.update` | Agent / Room | `PATCH` | `/api/agent/rooms/:roomId/artifacts` | `roomId` | — | — | `artifactId`, `archived` | `artifactId`, `archived` | — |
| `agent.room.workItems.list` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/work-items` | `roomId` | `state`, `ownerParticipantId`, `limit` | — | — | — | — |
| `agent.room.workItem.create` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/work-items` | `roomId` | — | — | `objective`, `expectedOutput`, `currentOwnerParticipantId`, `createdByParticipantId`, `clientMessageId`, `accountableParticipantId`, `topicId`, `rootTurnId`, `parentWorkId`, `acceptanceCriteria`, `state`, `depth` | `objective`, `expectedOutput`, `currentOwnerParticipantId`, `clientMessageId` | — |
| `agent.room.workItem.get` | Agent / Room | `GET` | `/api/agent/rooms/:roomId/work-items/:workItemId` | `roomId`, `workItemId` | — | — | — | — | — |
| `agent.room.workItem.reassign` | Agent / Room | `POST` | `/api/agent/rooms/:roomId/work-items/:workItemId/reassign` | `roomId`, `workItemId` | — | — | `actorParticipantId`, `targetParticipantId`, `reason` | `actorParticipantId`, `targetParticipantId` | — |
| `agent.roles.list` | Settings | `GET` | `/api/agent/roles` | — | — | — | — | — | — |
| `agent.roles.create` | Settings | `POST` | `/api/agent/roles` | — | — | — | `displayName`, `tagline`, `summary`, `traits`, `timelineModel`, `selectableModes`, `suitableTasks`, `unsuitableTasks` | `displayName`, `tagline`, `summary`, `traits`, `timelineModel`, `selectableModes`, `suitableTasks`, `unsuitableTasks` | — |
| `agent.roles.update` | Settings | `PATCH` | `/api/agent/roles` | — | — | — | `roleId`, `roleVersion`, `displayName`, `tagline`, `summary`, `traits`, `timelineModel`, `selectableModes`, `suitableTasks`, `unsuitableTasks` | `roleId`, `roleVersion`, `displayName`, `tagline`, `summary`, `traits`, `timelineModel`, `selectableModes`, `suitableTasks`, `unsuitableTasks` | — |
| `agent.roles.archive` | Settings | `DELETE` | `/api/agent/roles` | — | — | — | `roleId`, `roleVersion` | `roleId`, `roleVersion` | — |
| `agent.role.models` | Settings | `GET` | `/api/agent/roles/models` | — | — | — | — | — | — |
| `agent.role.runtimeDefaults.update` | Settings | `POST` | `/api/agent/roles/runtime-defaults` | — | — | — | `roleId`, `roleVersion`, `provider`, `modelId`, `thinkingLevel` | `roleId`, `roleVersion`, `provider`, `modelId`, `thinkingLevel` | — |
| `agent.roleBook.get` | Settings | `GET` | `/api/agent/role-book` | — | `roleId`, `roleVersion`, `limit` | `roleId`, `roleVersion` | — | — | — |
| `agent.roleBook.activation.preview` | Settings | `POST` | `/api/agent/role-book/activation/preview` | — | — | — | `roleId`, `roleVersion`, `revisionId`, `draftId`, `traitIndexes`, `capabilityIndexes`, `lessonIndexes`, `commitmentIndexes` | `roleId`, `roleVersion` | — |
| `agent.roleBook.activation.apply` | Settings | `POST` | `/api/agent/role-book/activation/apply` | — | — | — | `roleId`, `roleVersion`, `revisionId`, `draftId`, `traitIndexes`, `capabilityIndexes`, `lessonIndexes`, `commitmentIndexes`, `previewToken`, `payloadSha256`, `confirmText` | `roleId`, `roleVersion`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `agent.roleBook.activation.rollback` | Settings | `POST` | `/api/agent/role-book/activation/rollback` | — | — | — | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | — |
| `agent.roleBook.draft.decision` | Settings | `POST` | `/api/agent/role-book/drafts/decision` | — | — | — | `roleId`, `roleVersion`, `draftId`, `decision` | `roleId`, `roleVersion`, `draftId`, `decision` | — |
| `agent.personalContext.observability` | Memory | `GET` | `/api/agent/personal-context/observability` | — | `sessionId`, `roleId`, `limit` | — | — | — | — |
| `agent.tools.list` | App Center | `GET` | `/api/agent/tools` | — | `sessionId` | — | — | — | — |
| `agent.extensions.list` | App Center | `GET` | `/api/agent/extensions` | — | — | — | — | — | — |
| `agent.extensions.catalog` | App Center | `GET` | `/api/agent/extensions/catalog` | — | — | — | — | — | — |
| `agent.extensions.create` | App Center | `POST` | `/api/agent/extensions/drafts` | — | — | — | `draftId`, `packageJson`, `files` | `draftId`, `packageJson`, `files` | — |
| `agent.extensions.proposals` | App Center | `GET` | `/api/agent/extensions/proposals` | — | — | — | — | — | — |
| `agent.extensions.validate` | App Center | `POST` | `/api/agent/extensions/validate` | — | — | — | `sourcePath`, `packageSource`, `catalogId`, `catalogVersion` | — | — |
| `agent.extensions.preview` | App Center | `POST` | `/api/agent/extensions/preview` | — | — | — | `action`, `validationToken`, `pluginId`, `enable` | `action` | — |
| `agent.extensions.apply` | App Center | `POST` | `/api/agent/extensions/apply` | — | — | — | `previewToken`, `payloadSha256`, `confirmText` | `previewToken`, `payloadSha256`, `confirmText` | — |
| `agent.lifecycleHooks.get` | App Center | `GET` | `/api/agent/lifecycle-hooks` | — | `limit` | — | — | — | — |
| `agent.lifecycleHooks.update` | App Center | `PATCH` | `/api/agent/lifecycle-hooks` | — | — | — | `eventType`, `enabled`, `action`, `tokenLimit`, `cooldownSeconds` | `eventType` | — |
| `agent.approvals.list` | Settings | `GET` | `/api/agent/approvals` | — | `sessionId`, `state`, `limit` | — | — | — | — |
| `agent.approval.get` | Settings | `GET` | `/api/agent/approvals/:approvalId` | `approvalId` | — | — | — | — | — |
| `agent.approval.decide` | Settings | `POST` | `/api/agent/approvals/:approvalId/decision` | `approvalId` | — | — | `decision`, `payloadSha256` | `decision`, `payloadSha256` | — |
| `agent.memoryMaintenance.run` | Memory | `GET` | `/api/agent/memory-maintenance` | — | `runId`, `jobId`, `project`, `limit` | — | — | — | — |
| `agent.memoryMaintenance.trigger` | Memory | `POST` | `/api/agent/memory-maintenance` | — | — | — | `project`, `ownerKind`, `ownerId`, `instruction`, `manual`, `maxSources` | — | — |
| `agent.subagents.templates` | Agent / Room | `GET` | `/api/agent/subagents/templates` | — | — | — | — | — | — |
| `agent.subagents.list` | Agent / Room | `GET` | `/api/agent/subagents/runs` | — | `sessionId`, `limit` | `sessionId` | — | — | — |
| `agent.subagents.create` | Agent / Room | `POST` | `/api/agent/subagents/runs` | — | — | — | `sessionId`, `tasks`, `agent`, `version`, `task`, `expectedOutput`, `acceptanceCriteria`, `outputSchema`, `modelProfile`, `thinkingLevel`, `access`, `allowedTools`, `piSkillsEnabled`, `codexSkillsEnabled`, `workspaceRoots`, `todoTask`, `contextMode`, `forkEntryId`, `wait` | `sessionId` | — |
| `agent.subagent.get` | Agent / Room | `GET` | `/api/agent/subagents/runs/:runId` | `runId` | `sessionId` | `sessionId` | — | — | — |
| `agent.subagent.console` | Agent / Room | `GET` | `/api/agent/subagents/runs/:runId/console` | `runId` | `sessionId` | `sessionId` | — | — | — |
| `agent.subagent.control` | Agent / Room | `POST` | `/api/agent/subagents/runs/:runId/control` | `runId` | — | — | `sessionId`, `action`, `clientActionId`, `message`, `inboxId` | `sessionId`, `action`, `clientActionId` | — |
| `agent.subagent.abort` | Agent / Room | `POST` | `/api/agent/subagents/runs/:runId/abort` | `runId` | — | — | `sessionId` | `sessionId` | — |
| `agent.memorySources.list` | Memory | `GET` | `/api/agent/memory-sources` | — | `sessionId`, `limit` | `sessionId` | — | — | — |
| `agent.wakeSchedules.list` | Project | `GET` | `/api/agent/wake-schedules` | — | `status`, `targetType`, `targetId`, `createdBySessionId`, `limit` | — | — | — | — |
| `agent.wakeSchedules.create` | Project | `POST` | `/api/agent/wake-schedules` | — | — | — | `title`, `instruction`, `targetType`, `targetSessionId`, `targetRoleId`, `targetRoleVersion`, `wakeAtMs`, `timezone`, `recurrenceKind`, `recurrenceInterval`, `maxRuns`, `planningTaskId`, `confirmText` | `instruction`, `targetType`, `wakeAtMs`, `confirmText` | — |
| `agent.wakeSchedule.runs` | Project | `GET` | `/api/agent/wake-schedules/:scheduleId/runs` | `scheduleId` | `limit` | — | — | — | — |
| `agent.wakeSchedule.action` | Project | `POST` | `/api/agent/wake-schedules/:scheduleId/action` | `scheduleId` | — | — | `action`, `confirmText` | `action`, `confirmText` | — |
| `browser.status` | Browser | `GET` | `/api/browser/status` | — | — | — | — | — | — |
| `browser.tabs` | Browser | `GET` | `/api/browser/tabs` | — | — | — | — | — | — |
| `browser.snapshot.latest` | Browser | `GET` | `/api/browser/snapshots/latest` | — | `deviceId`, `tabId`, `includeMarkdown` | — | — | — | — |
| `browser.snapshot.image` | Browser | `GET` | `/api/browser/snapshots/:snapshotId/image` | `snapshotId` | — | — | — | — | typed binary |
| `browser.traces` | Browser | `GET` | `/api/browser/traces` | — | `limit` | — | — | — | — |
| `browser.command` | Browser | `POST` | `/api/browser/command` | — | — | — | `action`, `deviceId`, `tabId`, `refId`, `url`, `text`, `script`, `clear`, `submit`, `direction`, `amount`, `timeoutMs`, `timeoutSeconds` | `action` | — |
| `browser.stop` | Browser | `POST` | `/api/browser/stop` | — | — | — | — | — | — |
| `browser.managed.start` | Browser | `POST` | `/api/browser/managed/start` | — | — | — | — | — | — |
| `browser.managed.stop` | Browser | `POST` | `/api/browser/managed/stop` | — | — | — | — | — | — |
| `terminal.sessions.list` | Terminal | `GET` | `/api/terminal/sessions` | — | — | — | — | — | — |
| `terminal.session.create` | Terminal | `POST` | `/api/terminal/sessions` | — | — | — | `title`, `cwd`, `shell`, `cols`, `rows` | — | — |
| `terminal.session.read` | Terminal | `POST` | `/api/terminal/read` | — | — | — | `terminalId`, `cursor`, `maxBytes` | `terminalId` | — |
| `terminal.session.write` | Terminal | `POST` | `/api/terminal/write` | — | — | — | `terminalId`, `text` | `terminalId`, `text` | — |
| `terminal.session.resize` | Terminal | `POST` | `/api/terminal/resize` | — | — | — | `terminalId`, `cols`, `rows` | `terminalId`, `cols`, `rows` | — |
| `terminal.session.close` | Terminal | `POST` | `/api/terminal/close` | — | — | — | `terminalId` | `terminalId` | — |
| `planning.dashboard` | Project | `GET` | `/api/planning/dashboard` | — | `date`, `project` | — | — | — | — |
| `planning.mutation.preview` | Project | `POST` | `/api/planning/mutation/preview` | — | — | — | `kind`, `payload`, `expectedRuntimeRevision` | `kind`, `payload`, `expectedRuntimeRevision` | — |
| `planning.task.save` | Project | `POST` | `/api/planning/task/save` | — | — | — | `taskId`, `date`, `title`, `detail`, `priority`, `status`, `dueAtMs`, `goalId`, `project`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | `date`, `title`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `planning.goal.save` | Project | `POST` | `/api/planning/goal/save` | — | — | — | `goalId`, `title`, `detail`, `horizon`, `status`, `priority`, `targetDate`, `project`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | `title`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `planning.task.action` | Project | `POST` | `/api/planning/task/action` | — | — | — | `taskId`, `action`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | `taskId`, `action`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `planning.taskEvent.undo` | Project | `POST` | `/api/planning/task-event/undo` | — | — | — | `eventId`, `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | `eventId`, `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | — |
| `planning.mutation.rollback` | Project | `POST` | `/api/planning/mutation/rollback` | — | — | — | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | — |
| `workDocuments.list` | Project | `GET` | `/api/agent/work-documents` | — | `limit` | — | — | — | contract `work-document-list.v1` |
| `workDocuments.history.search` | Project | `GET` | `/api/agent/work-documents/history/search` | — | `query`, `limit` | — | — | — | contract `work-document-list.v1` |
| `workDocuments.get` | Project | `GET` | `/api/agent/work-documents/:documentId` | `documentId` | — | — | — | — | contract `work-document-detail.v1` |
| `workDocuments.register` | Project | `POST` | `/api/agent/work-documents` | — | — | — | `authorityKind`, `authorityId`, `authorityRevision`, `workspaceRoot`, `sourcePath`, `title` | `authorityKind`, `authorityId`, `authorityRevision`, `workspaceRoot`, `sourcePath` | contract `work-document-command.v1` |
| `workDocuments.archive` | Project | `POST` | `/api/agent/work-documents/:documentId/archive` | `documentId` | — | — | `terminalReceiptId` | `terminalReceiptId` | contract `work-document-command.v1` |
| `workDocuments.repair` | Project | `POST` | `/api/agent/work-documents/:documentId/repair` | `documentId` | — | — | — | — | contract `work-document-command.v1` |
| `workDocuments.reopen` | Project | `POST` | `/api/agent/work-documents/:documentId/reopen` | `documentId` | — | — | `authorityRevision`, `transitionReceiptId` | `authorityRevision`, `transitionReceiptId` | contract `work-document-command.v1` |
| `workDocuments.erase.preview` | Project | `POST` | `/api/agent/work-documents/:documentId/erase-preview` | `documentId` | — | — | `sessionId` | `sessionId` | contract `work-document-command.v1` |
| `workDocuments.erase` | Project | `POST` | `/api/agent/work-documents/:documentId/erase` | `documentId` | — | — | `sessionId`, `approvalId`, `payloadSha256` | `sessionId`, `approvalId`, `payloadSha256` | contract `work-document-command.v1` |
| `memory.summary` | Memory | `GET` | `/api/memory/summary` | — | — | — | — | — | — |
| `memory.pages` | Memory | `GET` | `/api/memory/:kind` | `kind` | `limit`, `cursor`, `query`, `status`, `ownerKind`, `ownerId` | — | — | — | — |
| `memory.reference.get` | Memory | `GET` | `/api/memory/references/:kind/:referenceId` | `kind`, `referenceId` | — | — | — | — | contract `memory-reference.v1` |
| `memory.graph.get` | Memory | `GET` | `/api/memory/graph` | — | `plane`, `project`, `status`, `query`, `focusId`, `depth`, `nodeLimit`, `edgeLimit`, `minWeight` | `plane` | — | — | contract `memory-graph.v1` |
| `memory.entity.get` | Memory | `GET` | `/api/memory/entities/:kind/:entityId` | `kind`, `entityId` | `project`, `connectionsLimit`, `connectionsCursor`, `membersLimit`, `membersCursor` | — | — | — | contract `memory-entity.v1` |
| `memory.edit` | Memory | `POST` | `/api/memory/edit` | — | — | — | `kind`, `id`, `title`, `text`, `summary`, `note`, `description`, `tags`, `aliases`, `type`, `color`, `reason`, `active` | `kind`, `id` | — |
| `memory.source.disposition` | Memory | `POST` | `/api/memory/source/disposition` | — | — | — | `sourceId`, `evidenceId`, `disposition` | `disposition` | — |
| `memory.book.archive.preview` | Memory | `POST` | `/api/memory/book/archive/preview` | — | — | — | `bookId`, `archived`, `reason`, `expectedRuntimeRevision` | `bookId`, `archived`, `expectedRuntimeRevision` | — |
| `memory.book.archive.apply` | Memory | `POST` | `/api/memory/book/archive/apply` | — | — | — | `bookId`, `archived`, `reason`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | `bookId`, `archived`, `reason`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `memory.book.archive.rollback` | Memory | `POST` | `/api/memory/book/archive/rollback` | — | — | — | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | — |
| `memory.activityTimeline.get` | Memory | `GET` | `/api/memory/activity-timeline` | — | `timelineId`, `date`, `status` | — | — | — | — |
| `memory.activityTimeline.calendar` | Memory | `GET` | `/api/memory/activity-timeline/calendar` | — | `month` | `month` | — | — | — |
| `memory.activityTimeline.build` | Memory | `POST` | `/api/memory/activity-timeline/build` | — | — | — | `date`, `throughToday` | `date` | — |
| `memory.activityTimeline.approve` | Memory | `POST` | `/api/memory/activity-timeline/approve` | — | — | — | `timelineId`, `expectedSourceEventHash`, `confirmText` | `timelineId`, `expectedSourceEventHash`, `confirmText` | — |
| `memory.activityTimeline.reject` | Memory | `POST` | `/api/memory/activity-timeline/reject` | — | — | — | `timelineId`, `reason`, `confirmText` | `timelineId`, `reason`, `confirmText` | — |
| `history.page` | Input | `GET` | `/api/history/page` | — | `limit`, `cursor`, `query`, `filter` | — | — | — | — |
| `history.detail` | Input | `GET` | `/api/history/detail` | — | `eventId` | `eventId` | — | — | — |
| `history.tombstone.preview` | Input | `POST` | `/api/history/tombstone/preview` | — | — | — | `eventId`, `reason`, `expectedRuntimeRevision` | `eventId`, `expectedRuntimeRevision` | — |
| `history.tombstone.apply` | Input | `POST` | `/api/history/tombstone/apply` | — | — | — | `eventId`, `reason`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | `eventId`, `reason`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `history.tombstone.rollback` | Input | `POST` | `/api/history/tombstone/rollback` | — | — | — | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | — |
| `knowledge.start` | Knowledge | `POST` | `/api/knowledge/start` | — | — | — | `question`, `context`, `mode`, `includeNotion`, `generation`, `contextHash`, `clientId`, `project`, `app`, `maxChars`, `latencyBudgetMs` | `question` | — |
| `knowledge.cancel` | Knowledge | `POST` | `/api/knowledge/cancel` | — | — | — | `sessionId`, `id` | — | — |
| `knowledge.status` | Knowledge | `GET` | `/api/knowledge/status` | — | `sessionId`, `id` | — | — | — | — |
| `knowledge.routeStatus` | Knowledge | `GET` | `/api/knowledge/route-status` | — | — | — | — | — | — |
| `knowledge.database.apply.preview` | Knowledge | `POST` | `/api/knowledge/database/apply-preview` | — | — | — | `runId`, `expectedRuntimeRevision` | `runId` | — |
| `knowledge.database.draft.edit` | Knowledge | `POST` | `/api/knowledge/database/draft-edit` | — | — | — | `runId`, `diffId`, `selected`, `payload` | `runId`, `diffId`, `selected` | — |
| `knowledge.database.apply` | Knowledge | `POST` | `/api/knowledge/database/apply` | — | — | — | `runId`, `confirm`, `previewToken`, `payloadSha256`, `expectedRuntimeRevision` | `runId`, `confirm`, `previewToken`, `payloadSha256`, `expectedRuntimeRevision` | — |
| `knowledge.database.rollback` | Knowledge | `POST` | `/api/knowledge/database/rollback` | — | — | — | `runId`, `confirm`, `receiptId`, `rollbackToken`, `payloadSha256` | `runId`, `confirm`, `receiptId`, `rollbackToken`, `payloadSha256` | — |
| `knowledgeBases.list` | Knowledge | `GET` | `/api/knowledge-bases` | — | `limit`, `cursor`, `query`, `status` | — | — | — | — |
| `knowledgeBases.create` | Knowledge | `POST` | `/api/knowledge-bases` | — | — | — | `name`, `description`, `agentEnabled`, `parserProvider`, `chunkingConfig`, `retrievalConfig` | `name` | — |
| `knowledgeBases.get` | Knowledge | `GET` | `/api/knowledge-bases/:kbId` | `kbId` | — | — | — | — | — |
| `knowledgeBases.update` | Knowledge | `PATCH` | `/api/knowledge-bases/:kbId` | `kbId` | — | — | `name`, `description`, `agentEnabled`, `parserProvider`, `chunkingConfig`, `retrievalConfig`, `expectedRevision` | `expectedRevision` | — |
| `knowledgeBases.delete.preview` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/delete/preview` | `kbId` | — | — | `expectedRevision` | `expectedRevision` | — |
| `knowledgeBases.delete.apply` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/delete/apply` | `kbId` | — | — | `expectedRevision`, `previewToken`, `payloadSha256`, `confirmText` | `expectedRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `knowledgeBases.documents.list` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/documents` | `kbId` | `limit`, `cursor`, `query`, `status` | — | — | — | — |
| `knowledgeBases.document.import` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/documents/import` | `kbId` | `fileName`, `mimeType`, `parserProvider` | `fileName`, `mimeType` | — | — | — |
| `knowledgeBases.document.retry` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/documents/:fileId/retry` | `kbId`, `fileId` | — | — | `stage`, `parserProvider`, `expectedRevision` | `stage`, `expectedRevision` | — |
| `knowledgeBases.document.delete` | Knowledge | `DELETE` | `/api/knowledge-bases/:kbId/documents/:fileId` | `kbId`, `fileId` | — | — | — | — | — |
| `knowledgeBases.document.get` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/documents/:fileId` | `kbId`, `fileId` | `offset`, `limit`, `lineOffset`, `lineLimit` | — | — | — | — |
| `knowledgeBases.document.source` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/documents/:fileId/source` | `kbId`, `fileId` | — | — | — | — | typed binary |
| `knowledgeBases.asset.get` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/documents/:fileId/assets/:assetId` | `kbId`, `fileId`, `assetId` | — | — | — | — | typed binary |
| `knowledgeBases.jobs.list` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/jobs` | `kbId` | `limit`, `cursor`, `status` | — | — | — | — |
| `knowledgeBases.job.cancel` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/jobs/:jobId/cancel` | `kbId`, `jobId` | — | — | — | — | — |
| `knowledgeBases.chunkPreview` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/documents/:fileId/chunk-preview` | `kbId`, `fileId` | — | — | `chunkingConfig`, `limit` | `chunkingConfig` | — |
| `knowledgeBases.search` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/search` | `kbId` | — | — | `query`, `topK`, `mode`, `threshold`, `fileIds`, `fileName` | `query` | — |
| `knowledgeBases.find` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/documents/:fileId/find` | `kbId`, `fileId` | — | — | `query`, `regex`, `lineWindow` | `query` | — |
| `knowledgeBases.open` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/documents/:fileId/content` | `kbId`, `fileId` | `chunkId`, `page`, `startLine`, `lines` | — | — | — | — |
| `knowledgeBases.reindexPreview` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/reindex-preview` | `kbId` | — | — | — | — | — |
| `knowledgeBases.rebuild` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/rebuild` | `kbId` | — | — | `previewToken`, `payloadSha256`, `expectedRevision`, `confirmText` | `previewToken`, `payloadSha256`, `expectedRevision`, `confirmText` | — |
| `knowledgeBases.graph.get` | Knowledge | `GET` | `/api/knowledge-bases/:kbId/graph` | `kbId` | `documentId`, `query`, `kinds`, `limit`, `depth`, `excludeChunks`, `focusId` | — | — | — | contract `knowledge-graph.v1` |
| `knowledgeBases.graph.rebuild` | Knowledge | `POST` | `/api/knowledge-bases/:kbId/graph/rebuild` | `kbId` | — | — | `expectedRevision`, `documentIds`, `extractorMode`, `modelId`, `batchSize`, `extractionConcurrency`, `maxEntitiesPerChunk`, `maxRelationsPerChunk`, `maxTopicsPerChunk` | `expectedRevision` | — |
| `knowledgeWorker.health` | Knowledge | `GET` | `/api/knowledge-bases/health` | — | — | — | — | — | — |
| `knowledgeParsers.list` | Knowledge | `GET` | `/api/knowledge-bases/parsers` | — | — | — | — | — | — |
| `knowledgeEmbedding.profile` | Knowledge | `GET` | `/api/knowledge-bases/embedding-profile` | — | — | — | — | — | — |
| `knowledgeEmbedding.probe` | Knowledge | `POST` | `/api/knowledge-bases/embedding-probe` | — | — | — | `profile` | `profile` | — |
| `knowledgeEmbedding.impact` | Knowledge | `POST` | `/api/knowledge-bases/embedding-impact` | — | — | — | `profile` | `profile` | — |
| `diagnostics.runtime` | Monitor | `GET` | `/api/runtime/status` | — | — | — | — | — | — |
| `diagnostics.predictor` | Monitor | `GET` | `/api/predictor/status` | — | — | — | — | — | — |
| `diagnostics.models` | Monitor | `GET` | `/api/models/status` | — | — | — | — | — | — |
| `diagnostics.action.preview` | Monitor | `POST` | `/api/runtime/action/preview` | — | — | — | `action`, `expectedRuntimeRevision` | `action`, `expectedRuntimeRevision` | — |
| `diagnostics.action.start` | Monitor | `POST` | `/api/runtime/action/start` | — | — | — | `action`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `commandSha256`, `confirmText` | `action`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `commandSha256`, `confirmText` | — |
| `diagnostics.action.job` | Monitor | `GET` | `/api/runtime/job/:jobId` | `jobId` | — | — | — | — | — |
| `configuration.settings` | Settings | `GET` | `/api/settings` | — | — | — | — | — | — |
| `configuration.schema` | Settings | `GET` | `/api/settings/schema` | — | — | — | — | — | — |
| `configuration.settings.preview` | Settings | `POST` | `/api/settings/preview` | — | — | — | `changes`, `expectedRuntimeRevision` | `changes`, `expectedRuntimeRevision` | — |
| `configuration.settings.apply` | Settings | `POST` | `/api/settings/apply` | — | — | — | `changes`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | `changes`, `expectedRuntimeRevision`, `previewToken`, `payloadSha256`, `confirmText` | — |
| `configuration.settings.rollback` | Settings | `POST` | `/api/settings/rollback` | — | — | — | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | `receiptId`, `rollbackToken`, `payloadSha256`, `confirmText` | — |
| `configuration.import.preview` | Settings | `POST` | `/api/configuration/import-preview` | — | — | — | `path` | `path` | — |
| `configuration.import.apply` | Settings | `POST` | `/api/configuration/import-apply` | — | — | — | `path`, `expectedRuntimeRevision`, `previewToken`, `confirmText`, `confirmRemoteModel` | `path`, `expectedRuntimeRevision`, `previewToken`, `confirmText` | — |
| `configuration.backup.export` | Settings | `POST` | `/api/configuration/backup-export` | — | — | — | `destination` | `destination` | — |
| `configuration.restore.preview` | Settings | `POST` | `/api/configuration/restore-preview` | — | — | — | `path` | `path` | — |
| `configuration.restore.apply` | Settings | `POST` | `/api/configuration/restore-apply` | — | — | — | `path`, `restoreToken`, `confirmText`, `expectedRuntimeRevision` | `path`, `restoreToken`, `confirmText`, `expectedRuntimeRevision` | — |

## Source Authority And Coverage Receipt

- Typed route authority: `control-center-web/src/platform/routes.ts` — 233 unique routes, all assigned to an App or shared control plane.
- Frontend transport/native authority: `control-center-web/src/platform/transport.ts`.
- Backend allowlist/ownership evidence: `rag_ime/control_api/route_table.py`, `rag_ime/control_api/route_policy.py`.
- Generated response contracts: `control-center-web/src/contracts/generated.ts` and its validators/schema index in the repository.
- This guide describes source contracts, not live installation health or foreground acceptance. The UI must discover capabilities at runtime.
- Route grouping counts: Agent / Room 74, App Center 10, Browser 9, Files 2, Input 9, Knowledge 39, Memory 19, Monitor 8, Project 21, Settings 32, Shared control plane 4, Terminal 6.
