# PAWOS 下一轮网页模型：源码一致的脱敏渲染数据

## User Requirement Ledger

### WEB-DATA-001 — 给每个 App 足够的真实数据形状 | current / P0

- **要求：** 下一模型不能靠猜测或候选 HTML 的假数字设计页面；必须按当前 TypeScript consumer、route、reducer 和聚焦测试的真实字段与状态渲染。
- **验收：** 11 个 App 至少用本文件提供的 normal、empty、pending、error/partial 代表形状检查布局，长字段不遮挡，状态不被误判为成功。
- **原话：** “打包md额外打包一个md，就是给他通过每个功能的部分真实数据，这样做他才能正确渲染和改前端”。

### WEB-DATA-002 — 样例不是第二套数据层 | current / P0

- **要求：** 以下 JSON 是从真实源码形状提炼的脱敏、合成 fixture，仅用于设计、组件渲染与测试；生产前端仍必须读取 typed transport、reducer、SSE、Electron/native bridge 与 Runtime projection。
- **禁止：** 把样例写进生产 store；把 `{loading:true}` 伪造成 Gateway 响应；复制真实用户历史、凭据、Cookie、浏览记录、Shell 历史、绝对 home 路径或本机数据库。

### WEB-DATA-003 — 最新视觉方向优先 | current / P0

- **要求：** 这些数据要渲染在最新默认单主题上：冷白/柔白、轻透、青春鲜活、明亮 Dock；深色只用于 Terminal、代码、媒体等功能局部。
- **禁止：** 以旧候选包的暖工程纸、深色 Dock、大面积暗背景或静态 1440px 画布套数据。

### WEB-DATA-004 — 必须提供可直接渲染的跨路由场景，尤其是多人 Room 对话 | current / P0 correction

- **要求：** 除单路由 normal/empty/error 外，还要给出同一批 ID、时间、对象和因果连续的场景包。下一模型不能自行发明伙伴、消息、WorkItem、Tool、审批、卫星上下文或最终结果。
- **验收：** 仅使用本文件即可渲染四人 Room 的主时间线、并发执行 lane、工具/审批、局部失败、新输入恢复、最终 Root 答复与四个卫星投影；其他核心 App 也有至少一条跨页面/跨路由数据链。
- **原话：** “都说了打包部分真实数据，例如多人对话这些”。

### WEB-DATA-005 — fixture 事件不是“一条一张卡”，对话与轨迹有不同投影 | current / P0 correction

- **要求：** 同一批真实事件必须经过当前 reducer/consumer 再渲染。对话页按 turn 显示用户右侧输入、Agent 左侧正文和所属活动；Agent 轨迹按 Turn 与事件节点显示诊断信息。两者共享事件 authority，但不是相同 DOM，也不能互相复制完整正文。
- **顺序：** `timelineSequence` 优先于时间；连续同类活动可折叠，跨类型不得重排。Room 必须按 `sequence` 保留公开 loop、伙伴消息、Tool、审批、失败恢复和 Root 的先后关系。
- **原话：** “而且你没弄完吧，我看他做的消息流都和现在不一样”。最新网页模型截图只作为 Agent 轨迹的视觉证据。

### WEB-DATA-006 — 提供多组可连续渲染的 Session 与 Room 对话 | current / P0 correction

- **要求：** 不能只给列表、单条事件或一个多人 Room；必须提供几组完整 Session 与 Room 对话，使网页模型能同时检查自然正文、Tool/审批/子 Agent、失败后新输入、compaction、多人直接问答、卫星和 Root 收敛。
- **验收：** 本文件至少含两组 Session 连续场景和两组 Room 连续场景；每组都说明同一事件如何分别进入对话、Agent 轨迹、Room 主窗或卫星，而不是将 JSONL 一条一张卡。
- **原话：** “你要塞几个真实对话，session和room的”；“这些zip里面都有的，它对话记录也都发你了”。

### WEB-DATA-007 — fixture 必须指向新版生产 owner，而不是旧卡片 renderer | current / P0 correction

- **要求：** Agent 对话由 `PawSessionWorkspace` 消费生产 Session projection，Agent 轨迹由 `PawContextTrace` 从同一 projection 派生；Room 中央公开叙事由 `PawRoomConversation` 消费生产 Room projection，伙伴/Browser/Terminal 卫星由 `PawOsSatelliteHost` 渲染，跨窗流转由 `PawWindowLayer` 派生。
- **验收：** fixture 能逐项指出上述 owner、typed route/reducer 和窗口 target；不再把旧 `RoomTurn` 卡片 DOM、静态候选 HTML 或 fixture store 当成生产主线。中央 Room 只显示公开 chronology，伙伴窗显示身份、当前 WorkItem、紧凑 Tool/状态摘要；路径、长 JSON 和 hash 只可在用户主动展开的公开详情中出现。
- **需求对齐：** `UR-119` 要求结构级生产迁移，`UR-120` 要求新版前端直接连接现有 PAW 后端并成为唯一主线，`UR-121` 明确否定旧卡片拼窗和默认泄露原始回执的 Room Focus。

### WEB-DATA-008 — Agent 空态、未驻留与 Session 工具只按真实需要出现 | current / P0 correction

- **要求：** 对齐 `UR-122`：Agent 只保留“对话 / Agent 轨迹”两个一级视图与一个“Session 工具”入口。任务与状态、子 Agent、文件互斥复用同一侧栏；只有真实待处理 approval/input/review 才显示一个“待处理”提示。
- **状态：** 无 Session、空 projection、无文件和 Pi Session 未驻留必须使用当前 consumer 的简短恢复状态，不能为了展示功能而伪造 Todo、Goal、子 Agent、文件、运行数字或常驻空抽屉。
- **隐私：** 用户提供的失败截图只证明重复工具条、空面板和遮挡问题；fixture 不摘录其中的 Session 名称、对话、路径、错误原文或浏览器内容。

### WEB-DATA-009 — 打包本机生产 Runtime 的真实 Session / Room 对话采样 | current / P0 correction

- **要求：** 不能只给“像真的”合成 fixture。打包时必须另含当前安装态 Gateway 实际返回的安全 canary 对话，保留真实 schema、事件类型、`sequence`、时间戳、状态、消息正文和因果顺序。
- **脱敏边界：** 真实 UUID、Tool call id、hash、绝对路径、私有正文和原始 Tool 参数统一替换为稳定 alias 或 `[redacted]`；不能因为脱敏而改变事件先后、参与者关系、成功/失败或同一 Turn 的归属。
- **验收：** 下方“生产 Runtime 真实采样”至少包含两个真实 Session Turn，以及一个真实 Room 的两轮对话、并行分派、两条 `work_result`、Root 汇合和简短直接问答。
- **原话：** “打包需要真实room和session对话数据”。

> 证据标签：`[S]` 由当前 TypeScript 类型、consumer 或聚焦测试直接支持；`[C]` 当前 consumer 可接受但聚焦测试未单独实例化；`[UI]` 是 React/query 本地状态，不是 HTTP/SSE 返回体。

## 使用规则

1. 先读 `control.bootstrap` / capabilities；缺少 routeId 时渲染 unavailable，不显示假按钮。
2. loading 通常通过 unresolved Promise 验证，error 通常通过 reject route 验证；除非合同明确定义，不发明 `{ "loading": true }` wire body。
3. preview token 只是等待确认；receipt 才是已应用；rollback 仍要受 authority/revision 约束。
4. SSE/event 必须按 `sequence`、`resumeToken`、`lastEventId` 连续消费；gap 进入 snapshot-required，不能静默追加。
5. 除“生产 Runtime 真实采样”外，ID、时间戳、hash、路径、名称和 URL 均为脱敏合成值。`<workspace>/project-01` 是占位授权根，不是可访问路径；示例 hash 只是格式占位值，不对应任何真实内容。真实采样保留生产时间戳与 `sequence`，但 ID 和敏感字段使用稳定 alias。
6. Room 属于 Agent；顶层 App 始终是 11 个。
7. 一条 event 不等于一张 UI 卡。先经 reducer 合并 delta、Tool lifecycle、approval receipt 和 provisional message，再由“对话”或“Agent 轨迹”各自投影；禁止把 JSONL 原样循环成静态卡片墙。

## 生产 Runtime 真实采样（2026-08-23，安全 canary，已脱敏）

这一节不是手写剧情。源数据来自本机已安装 Preview 连接的 `127.0.0.1:8766` 生产 Gateway：

- Session：`GET /api/agent/sessions/:sessionId/messages`
- Room：`GET /api/agent/rooms/:roomId` 与 `GET /api/agent/rooms/:roomId/history`
- 采样时 Room 的真实状态为 `active`、3 位伙伴、2 个 WorkItem、`lastEventSequence=277`。
- 只对标识符和敏感参数做稳定 alias；下面的 schema、时间、`sequence`、事件类型、状态和安全 canary 正文来自真实返回。

### 真实 Session A：Tool loop 与最终答复

```json
{
  "schemaVersion": "rag-ime.agent-message-list.v1",
  "sessionId": "session-live-a",
  "status": "idle",
  "lastSequence": 37,
  "resumeToken": "session-live-a:37",
  "items": [
    {
      "id": "message-live-a-user",
      "role": "user",
      "status": "completed",
      "turnId": "turn-live-a",
      "createdAtMs": 1787229509293,
      "blocks": [{"type":"text","status":"completed","presentationKind":"markdown","data":{"text":"请先调用 read 工具读取当前工作区 package.json，确认 name 字段；然后在最终答复中说明读取到的 name，并单独输出标记 SESSION_INSTALLED_0842_OK。不要修改任何文件。"}}]
    },
    {
      "id": "message-live-a-assistant",
      "role": "assistant",
      "status": "completed",
      "turnId": "turn-live-a",
      "createdAtMs": 1787229513845,
      "blocks": [{"type":"text","status":"completed","presentationKind":"markdown","data":{"text":"读取到的 `name` 是：`voxel-web-prototype`\n\nSESSION_INSTALLED_0842_OK"}}]
    }
  ],
  "liveEvents": [
    {"sequence":1,"eventType":"reasoning_summary","turnId":"turn-live-a","createdAtMs":1787229509531,"payload":{"source":"provider_reasoning_summary","state":"completed"}},
    {"sequence":2,"eventType":"tool_started","turnId":"turn-live-a","createdAtMs":1787229509532,"payload":{"toolCallId":"[redacted]","toolName":"read","isError":false}},
    {"sequence":3,"eventType":"tool_finished","turnId":"turn-live-a","createdAtMs":1787229513804,"payload":{"toolCallId":"[redacted]","toolName":"read","isError":false}},
    {"sequence":4,"eventType":"reasoning_summary","turnId":"turn-live-a","createdAtMs":1787229513845,"payload":{"source":"provider_reasoning_summary","state":"completed"}}
  ]
}
```

### 真实 Session B：低延迟短答

```json
{
  "schemaVersion": "rag-ime.agent-message-list.v1",
  "sessionId": "session-live-b",
  "status": "idle",
  "lastSequence": 8,
  "resumeToken": "session-live-b:8",
  "items": [
    {"id":"message-live-b-user","role":"user","status":"completed","turnId":"turn-live-b","createdAtMs":1787378374786,"blocks":[{"type":"text","status":"completed","presentationKind":"markdown","data":{"text":"前台即时回显验收：请只回复“已收到”。"}}]},
    {"id":"message-live-b-assistant","role":"assistant","status":"completed","turnId":"turn-live-b","createdAtMs":1787378374942,"blocks":[{"type":"text","status":"completed","presentationKind":"markdown","data":{"text":"已收到"}}]}
  ],
  "liveEvents": []
}
```

### 真实 Room：三位伙伴、并行 WorkItem、Root 汇合与下一轮直接问答

Room snapshot 的真实可见摘要：

```json
{
  "schemaVersion": "rag-ime.agent-room-get.v1",
  "ok": true,
  "room": {
    "id": "room-live-a",
    "title": "LIVE-ROOM-CLEAN-WORKRESULT-LOOP-0842",
    "status": "active",
    "lastEventSequence": 277,
    "participants": [
      {"id":"participant-facilitator","displayName":"澄·远","collaborationRole":"coordinator","status":"active","sessionId":"session-room-facilitator"},
      {"id":"participant-a","displayName":"澄·今","collaborationRole":"implementer","status":"active","sessionId":"session-room-a"},
      {"id":"participant-b","displayName":"澄·初","collaborationRole":"implementer","status":"active","sessionId":"session-room-b"}
    ],
    "workItems": [
      {"id":"workitem-a","status":"completed","ownerParticipantId":"participant-a","documentRevision":2},
      {"id":"workitem-b","status":"completed","ownerParticipantId":"participant-b","documentRevision":2}
    ]
  }
}
```

真实 Room 历史中用于渲染主叙事的代表事件。中间大量 `participant_delta` 必须由 reducer 合并，不能逐条生成卡片：

```jsonl
{"sequence":1,"eventType":"participant_status","turnId":"","createdAtMs":1787227118338,"payload":{"roomKind":"collaboration","routingPolicy":"parallel","status":"room_created","participants":["participant-facilitator","participant-a","participant-b"]}}
{"sequence":2,"eventType":"user_message","turnId":"room-turn-1","createdAtMs":1787227151604,"payload":{"text":"已安装 Room 验收：主持者只分派一次并行 wave；A、B 分别完成真实 WorkItem，返回结构化 work_result 后由主持者单独 Root 汇合。","targetParticipantIds":["participant-facilitator"]}}
{"sequence":3,"eventType":"route_decision","turnId":"room-turn-1","participantId":"participant-facilitator","createdAtMs":1787227151647,"payload":{"dispatchId":"dispatch-root","targetDisplayName":"澄·远","reason":"facilitator","routingPolicy":"parallel"}}
{"sequence":10,"eventType":"participant_activity","turnId":"room-turn-1","participantId":"participant-facilitator","createdAtMs":1787227168827,"payload":{"toolName":"read","isError":true}}
{"sequence":23,"eventType":"route_decision","turnId":"room-turn-1","participantId":"participant-a","createdAtMs":1787227196599,"payload":{"dispatchId":"dispatch-a","targetDisplayName":"澄·今","reason":"partner_delegate","routingPolicy":"parallel"}}
{"sequence":26,"eventType":"route_decision","turnId":"room-turn-1","participantId":"participant-b","createdAtMs":1787227196681,"payload":{"dispatchId":"dispatch-b","targetDisplayName":"澄·初","reason":"partner_delegate","routingPolicy":"parallel"}}
{"sequence":38,"eventType":"participant_activity","turnId":"room-turn-1","participantId":"participant-a","createdAtMs":1787227208420,"payload":{"toolName":"read","summary":"已读取 AGENTS.md 第 1-38 行","isError":false}}
{"sequence":47,"eventType":"participant_activity","turnId":"room-turn-1","participantId":"participant-b","createdAtMs":1787227212825,"payload":{"toolName":"read","summary":"已读取 package.json 第 1-20 行","isError":false}}
{"sequence":95,"eventType":"room_post","turnId":"room-turn-1","participantId":"participant-a","createdAtMs":1787227242392,"payload":{"post":{"kind":"work_result","content":{"workItem":"workitem-a","status":"completed","documentRevision":2,"canonicalPath":"[redacted]"}}}}
{"sequence":157,"eventType":"room_post","turnId":"room-turn-1","participantId":"participant-b","createdAtMs":1787227255908,"payload":{"post":{"kind":"work_result","content":{"workItem":"workitem-b","status":"completed","documentRevision":2,"canonicalPath":"[redacted]"}}}}
{"sequence":226,"eventType":"room_post","turnId":"room-turn-1","participantId":"participant-facilitator","createdAtMs":1787227272082,"payload":{"post":{"kind":"result","content":"Root 汇合完成；两个并行 WorkItem 均返回 work_result，第二次写入使用 canonicalPath 且 documentRevision>=2。"}}}
{"sequence":266,"eventType":"participant_message","turnId":"room-turn-1","participantId":"participant-facilitator","createdAtMs":1787227280454,"payload":{"message":{"role":"assistant","status":"completed","text":"已执行完成：一次并行分派、两个真实 WorkItem、两个 work_result、一次 Root result。CLEAN_WORKRESULT_LOOP_0842_OK"}}}
{"sequence":267,"eventType":"turn_completed","turnId":"room-turn-1","participantId":"participant-facilitator","createdAtMs":1787227280610,"payload":{"sourceEventType":"turn_completed"}}
{"sequence":268,"eventType":"user_message","turnId":"room-turn-2","createdAtMs":1787295068725,"payload":{"text":"你好","targetParticipantIds":["participant-facilitator"]}}
{"sequence":269,"eventType":"route_decision","turnId":"room-turn-2","participantId":"participant-facilitator","createdAtMs":1787295068781,"payload":{"dispatchId":"dispatch-direct","targetDisplayName":"澄·远","reason":"facilitator","routingPolicy":"parallel"}}
{"sequence":276,"eventType":"participant_message","turnId":"room-turn-2","participantId":"participant-facilitator","createdAtMs":1787295073702,"payload":{"message":{"role":"assistant","status":"completed","text":"你好！有什么我可以帮你处理的吗？"}}}
{"sequence":277,"eventType":"turn_completed","turnId":"room-turn-2","participantId":"participant-facilitator","createdAtMs":1787295073995,"payload":{"sourceEventType":"turn_completed"}}
```

渲染要求：

- Room 中央只显示两轮公开对话与可理解的协作摘要；`participant_delta`、Tool lifecycle 和两个 `work_result` 折叠进对应 Turn。
- “协作工具”按需打开后，可在同一个互斥面板切换消息流、任务流、治理、进展；不得覆盖中央对话或复制伙伴按钮。
- sequence 10 的旧 `read` 失败属于第一轮历史；第二轮新输入后不显示旧“重试/再次运行”主操作。
- Agent 轨迹可以显示 sequence、事件类型、时长和 Tool 名，但不能复制上述完整对话正文或泄露 `[redacted]` 字段。

## 共享传输状态

### capability ready [S]

```json
{
  "ok": true,
  "routeIds": [
    "overview.get",
    "agent.sessions.list",
    "memory.summary",
    "knowledgeBases.list",
    "input.source.get",
    "agent.extensions.catalog",
    "observability.snapshot",
    "configuration.settings",
    "agent.session.workspace.list",
    "browser.tabs",
    "terminal.sessions.list"
  ],
  "features": {
    "nativeBrowser": true,
    "nativeTerminal": true
  }
}
```

### capability unavailable [UI]

不要返回假 wire JSON。让 bootstrap/capability 请求失败或缺少对应 `routeId`，组件显示“当前安装未提供此能力”与可执行恢复路径。

---

## 1. Project Workbench

UI routes：`/overview`, `/planning`, `/work-documents`  
PathIds：`overview.get`, `planning.dashboard`, `workDocuments.list`, `workDocuments.get`

### normal WorkDocument [S]

```json
{
  "schemaVersion": "rag-ime.work-document-list.v1",
  "items": [{
    "documentId": "workdoc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "authorityKind": "session_todo",
    "authorityId": "session-01",
    "authorityRevision": 3,
    "authorityKey": "session_todo:session-01:3",
    "documentRevision": 2,
    "contentSha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "workspaceRoot": "<workspace>/project-01",
    "path": "<workspace>/project-01/docs/active/paw-os.md",
    "activePath": "<workspace>/project-01/docs/active/paw-os.md",
    "archivePath": "<workspace>/project-01/docs/archive/paw-os.md",
    "state": "active",
    "title": "PAWOS 交互重建",
    "terminalReceiptId": "",
    "error": "",
    "createdAtMs": 1787400000000,
    "updatedAtMs": 1787400300000
  }],
  "total": 1
}
```

### empty / pending / error [S][UI]

```json
{"schemaVersion":"rag-ime.work-document-list.v1","items":[],"total":0}
```

- pending：保持 `workDocuments.list` unresolved。
- error：reject `workDocuments.list`；本地 `NativeResourceState` 投影为 `loading:false` 和公开错误文案，不把它当 Gateway JSON。
- planning 状态直接消费 `active`, `review`, `done`；`completed` 只在前端归一为 `done`。

Source refs：`control-center-web/src/paw-os/apps/PawNativeApps.test.tsx`; `control-center-web/src/paw-os/apps/PawNativeApps.tsx`; `control-center-web/src/platform/routes.ts`。

## 2. Agent（包含 Room）

UI routes：`/agent`, `/rooms`  
PathIds：`agent.sessions.list`, `agent.rooms.list`, `agent.session.events`, `agent.room.events`

### 当前生产渲染 owner [S][UI]

| 表面 | `[S]` authority | `[UI]` 当前 owner 与投影边界 |
| --- | --- | --- |
| Session 对话 | `agent.session.snapshot` + `agent.session.events`，由 `agent-reducer` 连续归并 | `PawSessionWorkspace` 挂载一个真实 `AgentTimeline`；用户输入、Agent 正文、Tool、审批、失败恢复仍属于同一 Turn |
| Agent 轨迹 | 同一 `AgentProjectionState`；可选的真实上下文装配 route 只补充诊断 | `PawContextTrace.projectionTraceTurns()` 按 Turn、`timelineSequence` 和类别派生，不复制 transcript |
| Room 中央对话 | `agent.room.get`/snapshot + `agent.room.events`，由 `room-reducer` 连续归并 | `PawRoomConversation` 按 `sequence` 混排公开 message、可见 activity 和失败终态；明确不渲染旧 `RoomTurn` 卡片 DOM |
| 伙伴卫星 | 同一 Room metadata + `RoomProjectionState` | `PawOsSatelliteHost` 按 `participantId` 筛选公开 message/activity，显示真实身份、当前 WorkItem 和紧凑摘要；原始公开详情默认折叠 |
| Browser/Terminal 卫星 | Session/Room Tool 事件中的精确 `targetId`、`toolCallId`、`runId`、`terminalId` | `runtimeToolWindowRequest()` 生成 target；`PawOsSatelliteHost` 读取同一 Browser target 或后台 run，不启动第二个运行 |
| Room 跨窗流转 | reducer 中的 route、approval、intercom、公开 message | `PawWindowLayer.roomWindowFlowGroups()` 派生 request/dispatch/approval/result packet 和可收起 ledger；它不是持久状态 |

### normal Session / Room [S]

```json
{
  "ok": true,
  "activeSessionId": "session-01",
  "items": [{
    "id": "session-01",
    "title": "发布检查",
    "mode": "coordinator",
    "status": "idle",
    "updatedAtMs": 1787400300000,
    "workspaceRoots": ["<workspace>/project-01"],
    "messageCount": 3,
    "lastMessagePreview": "检查构建结果"
  }]
}
```

```json
{
  "ok": true,
  "items": [{
    "id": "room-01",
    "title": "迁移作战室",
    "status": "active",
    "roomKind": "collaboration",
    "routingPolicy": "parallel",
    "moderatorParticipantId": "participant-01",
    "updatedAtMs": 1787400300000,
    "workspaceRoots": ["<workspace>/project-01"],
    "participants": [{
      "id": "participant-01",
      "sessionId": "session-room-01",
      "roleId": "builder",
      "roleVersion": "1",
      "displayName": "构建者",
      "status": "active",
      "ordinal": 0
    }]
  }]
}
```

### streaming / failed event [S]

```jsonl
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-01:1","sessionId":"session-01","turnId":"turn-01","sequence":1,"createdAtMs":1787400300010,"eventType":"status_changed","payload":{"messageId":"turn-01:assistant","blockId":"turn-01:assistant:text","status":"working"},"resumeToken":"session-01:1"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-01:2","sessionId":"session-01","turnId":"turn-01","sequence":2,"createdAtMs":1787400300020,"eventType":"text_delta","payload":{"messageId":"turn-01:assistant","blockId":"turn-01:assistant:text","delta":"正在核对发布门禁。","replaceBlock":true},"resumeToken":"session-01:2"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-01:3","sessionId":"session-01","turnId":"turn-01","sequence":3,"createdAtMs":1787400300030,"eventType":"turn_failed","payload":{"messageId":"turn-01:assistant","blockId":"turn-01:assistant:text","error":"当前模型不可用，请切换模型后重试。"},"resumeToken":"session-01:3"}
```

### empty / pending / gap [S][UI]

```jsonl
{"ok":true,"activeSessionId":null,"items":[]}
{"ok":true,"items":[]}
```

- pending first prompt：保持 `agent.session.prompt` unresolved；乐观 Session 可先出现，但不能出现假成功 receipt。
- gap：`sequence` 不连续时 reducer 设 `needsSnapshot`；不得接受后续事件或复制一份聊天原文作为 trace。
- Agent 无头像；Room 是 Agent 内模式，不新增第 12 个 App。

### Agent 空态、未驻留与按需 Session 工具 [S][UI]

空 Session list 仍使用上面的 `[S]` `{"ok":true,"activeSessionId":null,"items":[]}`。进入一个已知但没有 Turn/activity/file 的 Session 后，`PawSessionWorkspace` 的 `[UI]` 初始投影如下；这不是 Gateway JSON：

```json
{
  "workspaceView": "conversation",
  "primaryViews": ["对话", "Agent 轨迹"],
  "toolMenuOpen": false,
  "panel": "none",
  "toolEntry": {"label": "Session 工具", "attention": false},
  "projectionExcerpt": {"turnOrder": [], "messageOrder": [], "activityOrder": []},
  "sidebar": null,
  "emptyDetail": "当前没有 Todo、子 Agent、文件或产物。"
}
```

行为断言：

- 未点击“Session 工具”时不存在 `Session 工具侧栏`，不能预先铺开 Todo/Goal、子 Agent 或文件抽屉。
- 点击入口后只有三个互斥 menuitem：`任务与状态`、`子 Agent`、`文件`；选择任一项只挂载一个共用 aside，切换时替换原面板。
- `workspaceRoots:[]` 的文件面板只显示“当前没有文件；选择工作区目录后即可浏览。”和“选择目录”动作，不渲染说明书式大空态。
- 当 reducer 中存在等待中的 human approval、generic input 或 memory review 时，`toolEntry.attention` 才派生为 `true`，可见文案为“待处理”；这不是服务端字段。

Agent 轨迹查询到 Pi Session 未驻留时的 `[S]` 响应样本：

```json
{
  "available": false,
  "transient": true,
  "sessionId": "session-sleeping",
  "turnId": "",
  "error": "session_not_resident",
  "availableTurns": [],
  "telemetry": {}
}
```

`PawContextTrace` 将它投影为一句恢复状态：“这段 Session 当前未驻留 Pi Runtime。重新打开或发送一条消息后，再查看 Agent 轨迹。”不得补造 context stages、Tool 计数或模型调用。

Source refs：`control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx`; `control-center-web/src/paw-os/apps/PawSessionWorkspace.test.tsx`; `control-center-web/src/paw-os/apps/PawContextTrace.tsx`; `control-center-web/src/paw-os/apps/PawContextTrace.test.tsx`; `control-center-web/src/contracts/agent-reducer.ts`。

### Session 对话与 Agent 轨迹的渲染映射 [UI]

| reducer/projected fact | 对话视图 | Agent 轨迹 |
| --- | --- | --- |
| user message | 右侧独立气泡；保留发送/Steer/Follow-up 反馈 | 只显示必要的 prompt 事件摘要，不复制全文 |
| assistant message | 左侧自然正文，无头像、无同形气泡 | message 事件节点、时间与因果引用 |
| reasoning summary | 所属回合中的可折叠公开摘要 | 所属 Turn 的 reasoning 节点 |
| Tool start/progress/result | 同一 `toolCallId` 合并为一个可折叠活动；保留真实位置 | Tool call/end 节点与安全 payload/result disclosure |
| approval request/receipt | 所属回合内联操作与已解决状态 | approval request/decision 节点 |
| subagent lifecycle | 所属回合活动，必要时打开真实子 Agent 窗口 | spawn/end 节点与引用，不复制子会话 transcript |
| turn failed/aborted | 回合内失败；只有最新回合可继续/重试 | Turn 终态节点；新输入不删除历史证据 |
| usage/context/compaction | 回合尾部用量与必要 compaction 通知 | 独立事件/上下文装配详情 |

源码映射：`PawSessionWorkspace` 在 conversation/trace 两个同级视图之间保留同一个 composer，并把生产 `AgentProjectionState` 分别交给 `AgentTimeline` 与 `PawContextTrace`；`projectionTraceTurns()` 再按 Turn 和 `timelineSequence` 排序 message/activity。网页模型不得用截图中的 `24/6/10/2/3/3` 等演示计数替换真实 projection。

Source refs：`control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx`; `control-center-web/src/paw-os/apps/PawSessionWorkspace.test.tsx`; `control-center-web/src/paw-os/apps/PawContextTrace.tsx`; `control-center-web/src/paw-os/apps/PawContextTrace.test.tsx`; `control-center-web/src/features/agent/timeline/AgentTimeline.tsx`; `control-center-web/src/contracts/agent-reducer.ts`; `control-center-web/src/test/fixtures/events.ts`。

### 场景包 S1：三轮 Session，Tool、子 Agent 与审批连续出现 [S]

此场景对应 `pawos-agent-fx-v1` 的对话结构，但下面的对象使用当前 `rag-ime.agent-message.v1` / `rag-ime.agent-event.v1` 形状。内容为脱敏合成值；真实之处是字段、顺序、合并规则和 UI 状态，不是用户私人聊天。

#### S1.1 `agent.session.snapshot` 的持久消息

```json
{
  "messages": [
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s1-u1","sessionId":"session-lexicon","turnId":"s1-t1","role":"user","status":"completed","blocks":[{"id":"s1-u1:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"把近 30 天输入记录整理进词库，先给我看候选。"}}],"attachments":[],"citations":[],"createdAtMs":1787400400000,"completedAtMs":1787400400010},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s1-a1","sessionId":"session-lexicon","turnId":"s1-t1","role":"assistant","status":"completed","blocks":[{"id":"s1-a1:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"已扫描全部输入记录。先跑一次统计，再按频率分组生成候选词表。"}}],"attachments":[],"citations":[],"createdAtMs":1787400400100,"completedAtMs":1787400400110,"provider":"openai","model":"gpt-5.6-sol","usage":{"input":3100,"output":188,"cacheRead":12400,"cacheWrite":0,"totalTokens":15688}},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s1-u2","sessionId":"session-lexicon","turnId":"s1-t2","role":"user","status":"completed","blocks":[{"id":"s1-u2:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"按频率分三组，长尾保留但权重调低。"}}],"attachments":[],"citations":[],"createdAtMs":1787400410000,"completedAtMs":1787400410010},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s1-u3","sessionId":"session-lexicon","turnId":"s1-t3","role":"user","status":"completed","blocks":[{"id":"s1-u3:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"批准。应用后跑一次回归校验。"}}],"attachments":[],"citations":[],"createdAtMs":1787400420000,"completedAtMs":1787400420010},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s1-a3","sessionId":"session-lexicon","turnId":"s1-t3","role":"assistant","status":"completed","blocks":[{"id":"s1-a3:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"已应用 342 词；写入 3 个文件，快照可回滚。回归校验进行中。"}}],"attachments":[],"citations":[],"createdAtMs":1787400420060,"completedAtMs":1787400420070}
  ],
  "lastSequence": 16,
  "resumeToken": "session-lexicon:16",
  "status": "active"
}
```

#### S1.2 `agent.session.events` 的真实活动顺序

```jsonl
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:1","sessionId":"session-lexicon","turnId":"s1-t1","sequence":1,"createdAtMs":1787400400050,"eventType":"reasoning_summary","payload":{"requestId":"reasoning-s1-t1","sourceMessageId":"s1-a1","summary":"先统计输入记录，再生成分组候选。","items":["统计近 30 天输入记录","按频率生成候选"],"source":"provider_reasoning_summary","state":"completed"},"resumeToken":"session-lexicon:1"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:2","sessionId":"session-lexicon","turnId":"s1-t1","sequence":2,"createdAtMs":1787400400060,"eventType":"tool_started","payload":{"toolCallId":"tool-scan","toolName":"ime.lexicon.scan","args":{"window":"30d","dedup":true},"summary":"正在扫描输入记录"},"resumeToken":"session-lexicon:2"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:3","sessionId":"session-lexicon","turnId":"s1-t1","sequence":3,"createdAtMs":1787400400090,"eventType":"tool_finished","payload":{"toolCallId":"tool-scan","toolName":"ime.lexicon.scan","summary":"已去重 12,438 条输入记录","publicResult":{"recordCount":12438,"deduplicatedCount":9211,"artifacts":[{"path":"ime/scan-report.json","sizeBytes":98304},{"path":"ime/freq-top500.csv","sizeBytes":41984}]}},"resumeToken":"session-lexicon:3"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:4","sessionId":"session-lexicon","turnId":"s1-t1","sequence":4,"createdAtMs":1787400400120,"eventType":"turn_completed","payload":{"status":"completed"},"resumeToken":"session-lexicon:4"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:5","sessionId":"session-lexicon","turnId":"s1-t2","sequence":5,"createdAtMs":1787400410030,"eventType":"reasoning_summary","payload":{"requestId":"reasoning-s1-t2","summary":"高频 1.0、中频 0.8、长尾 0.6；长尾保留但等待确认。","items":["高频 58 词","中频 121 词","长尾 163 词"],"source":"provider_reasoning_summary","state":"completed"},"resumeToken":"session-lexicon:5"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:6","sessionId":"session-lexicon","turnId":"s1-t2","sequence":6,"createdAtMs":1787400410060,"eventType":"tool_started","payload":{"toolCallId":"tool-build","toolName":"ime.lexicon.build","args":{"bands":[1,0.8,0.6]},"summary":"正在生成候选词表"},"resumeToken":"session-lexicon:6"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:7","sessionId":"session-lexicon","turnId":"s1-t2","sequence":7,"createdAtMs":1787400410100,"eventType":"tool_finished","payload":{"toolCallId":"tool-build","toolName":"ime.lexicon.build","summary":"候选 342 词，diff +342 -0","publicResult":{"candidateCount":342,"diffSummary":"+342 -0","artifact":"ime/lexicon.candidates.yaml"}},"resumeToken":"session-lexicon:7"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:8","sessionId":"session-lexicon","turnId":"s1-t2","sequence":8,"createdAtMs":1787400410110,"eventType":"tool_started","payload":{"toolCallId":"tool-subagent-review","toolName":"subagent","args":{"task":"抽检候选词表中的长尾词权重","scope":"read_only"},"summary":"子 Agent 正在复核词频"},"resumeToken":"session-lexicon:8"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:9","sessionId":"session-lexicon","turnId":"s1-t2","sequence":9,"createdAtMs":1787400410160,"eventType":"tool_finished","payload":{"toolCallId":"tool-subagent-review","toolName":"subagent","summary":"词频复核完成","result":{"details":{"results":[{"status":"completed","output":"抽检 500 条，误判 3 条；长尾权重 0.6 可保留。"}]}}},"resumeToken":"session-lexicon:9"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:10","sessionId":"session-lexicon","turnId":"s1-t2","sequence":10,"createdAtMs":1787400410170,"eventType":"approval_required","payload":{"approvalId":"approval-lexicon-apply","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","summary":"应用候选词表","riskLevel":"R2","preview":{"title":"应用词表 preview","summary":"改动 3 个文件，可由快照回滚","changes":[{"label":"候选词","before":"0","after":"342"}]}},"resumeToken":"session-lexicon:10"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:11","sessionId":"session-lexicon","turnId":"s1-t3","sequence":11,"createdAtMs":1787400420020,"eventType":"approval_resolved","payload":{"approvalId":"approval-lexicon-apply","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","resolutionState":"approved","state":"approved","summary":"用户已批准"},"resumeToken":"session-lexicon:11"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:12","sessionId":"session-lexicon","turnId":"s1-t3","sequence":12,"createdAtMs":1787400420040,"eventType":"tool_finished","payload":{"toolCallId":"tool-apply","toolName":"ime.lexicon.apply","summary":"写入 3 个文件，快照 #41","publicResult":{"snapshotId":"41","filesChanged":3}},"resumeToken":"session-lexicon:12"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:13","sessionId":"session-lexicon","turnId":"s1-t3","sequence":13,"createdAtMs":1787400420080,"eventType":"tool_started","payload":{"toolCallId":"tool-regression","toolName":"ime.regression.run","args":{"suite":"lexicon-regression","words":342},"summary":"已确认 210 / 342"},"resumeToken":"session-lexicon:13"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:14","sessionId":"session-lexicon","turnId":"s1-t3","sequence":14,"createdAtMs":1787400420090,"eventType":"tool_progress","payload":{"toolCallId":"tool-regression","toolName":"ime.regression.run","summary":"已确认 210 / 342","progress":{"completed":210,"total":342}},"resumeToken":"session-lexicon:14"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:15","sessionId":"session-lexicon","turnId":"s1-t3","sequence":15,"createdAtMs":1787400420120,"eventType":"tool_finished","payload":{"toolCallId":"tool-regression","toolName":"ime.regression.run","summary":"342 个候选词回归校验完成","isError":false,"publicResult":{"completed":342,"total":342,"failed":0}},"resumeToken":"session-lexicon:15"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-lexicon:16","sessionId":"session-lexicon","turnId":"s1-t3","sequence":16,"createdAtMs":1787400420130,"eventType":"turn_completed","payload":{"status":"completed"},"resumeToken":"session-lexicon:16"}
```

对话视图把 S1.1 的用户消息放右侧、Agent 正文放左侧，并将 S1.2 的活动按 sequence 插在所属回合中。Agent 轨迹则按 `s1-t1`–`s1-t3` 分三组，显示事件类型、时间、状态和安全摘要；不得把 `summary` 再复制成第二份聊天正文。

### 场景包 S2：失败后新输入、旧重试清除与 compaction 恢复 [S][UI]

`agent.session.snapshot` 中与两个连续 Turn 对应的持久 message 投影：

```json
{
  "messages": [
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s2-u1","sessionId":"session-recovery","turnId":"s2-failed","role":"user","status":"completed","blocks":[{"id":"s2-u1:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"检查安装态截图是否已经生成。"}}],"attachments":[],"citations":[],"createdAtMs":1787400500000,"completedAtMs":1787400500000},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s2-a1","sessionId":"session-recovery","turnId":"s2-failed","role":"assistant","status":"failed","blocks":[{"id":"s2-a1:error","type":"error","status":"failed","presentationKind":"error","data":{"message":"缺少安装态截图；生成后再复核。"}}],"attachments":[],"citations":[],"createdAtMs":1787400500010,"completedAtMs":1787400500030},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s2-u2","sessionId":"session-recovery","turnId":"s2-repair","role":"user","status":"completed","blocks":[{"id":"s2-u2:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"截图已经生成，只重跑复核；保留上一轮证据。"}}],"attachments":[],"citations":[],"createdAtMs":1787400510000,"completedAtMs":1787400510000},
    {"schemaVersion":"rag-ime.agent-message.v1","id":"s2-a2","sessionId":"session-recovery","turnId":"s2-repair","role":"assistant","status":"completed","blocks":[{"id":"s2-a2:text","type":"text","status":"completed","presentationKind":"markdown","data":{"text":"已保留旧失败证据，并完成缺失的复核步骤。"}}],"attachments":[],"citations":[],"createdAtMs":1787400510030,"completedAtMs":1787400510100}
  ],
  "lastSequence": 7,
  "resumeToken": "session-recovery:7",
  "status": "active"
}
```

同一 projection 的连续活动：

```jsonl
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:1","sessionId":"session-recovery","turnId":"s2-failed","sequence":1,"createdAtMs":1787400500010,"eventType":"tool_started","payload":{"toolCallId":"tool-missing","toolName":"workspace.read","args":{"path":"output/acceptance.png"},"summary":"读取安装态截图"},"resumeToken":"session-recovery:1"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:2","sessionId":"session-recovery","turnId":"s2-failed","sequence":2,"createdAtMs":1787400500020,"eventType":"tool_finished","payload":{"toolCallId":"tool-missing","toolName":"workspace.read","summary":"截图不存在","isError":true,"error":"ENOENT","publicResult":{"outputPreview":"output/acceptance.png 不存在"}},"resumeToken":"session-recovery:2"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:3","sessionId":"session-recovery","turnId":"s2-failed","sequence":3,"createdAtMs":1787400500030,"eventType":"turn_failed","payload":{"error":"缺少安装态截图；生成截图后再复核","status":"failed"},"resumeToken":"session-recovery:3"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:4","sessionId":"session-recovery","turnId":"s2-repair","sequence":4,"createdAtMs":1787400510010,"eventType":"reasoning_summary","payload":{"requestId":"reasoning-s2-repair","summary":"新输入只补截图与复核，不重放已经完成的实现。","items":["保留旧 Tool 证据","只执行缺失复核"],"source":"provider_reasoning_summary","state":"completed"},"resumeToken":"session-recovery:4"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:5","sessionId":"session-recovery","turnId":"s2-repair","sequence":5,"createdAtMs":1787400510020,"eventType":"compaction_started","payload":{"reason":"threshold","tokensBefore":119800,"summary":"正在折叠较早对话"},"resumeToken":"session-recovery:5"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:6","sessionId":"session-recovery","turnId":"s2-repair","sequence":6,"createdAtMs":1787400510060,"eventType":"compaction_completed","payload":{"reason":"threshold","tokensBefore":119800,"estimatedTokensAfter":46100,"summary":"已保留目标、已完成结果、失败证据和下一步"},"resumeToken":"session-recovery:6"}
{"schemaVersion":"rag-ime.agent-event.v1","eventId":"session-recovery:7","sessionId":"session-recovery","turnId":"s2-repair","sequence":7,"createdAtMs":1787400510100,"eventType":"turn_completed","payload":{"status":"completed"},"resumeToken":"session-recovery:7"}
```

当 `s2-repair` 已存在时，对话页仍保留旧失败证据，但旧 `s2-failed` 不再显示“重试本轮/继续/切换模型”操作；仅最新回合拥有恢复动作。`PawContextTrace` 保留两个 Turn，并把 compaction 作为第二个 Turn 的状态节点，而不是把它复制成聊天正文。

### 场景包 B：两位伙伴直接提问、回复并由 Root 收束 [S]

这是第二组独立 Room 连续场景，用于检查伙伴不是固定 pipeline：界面伙伴可以越过主持者直接向
复核伙伴提问，回复沿真实 `intercom` activity 返回；两条边都保留 source/target/replyTo，Root 最后只
总结公开结果。主 Room 按 sequence 展示 ask/reply；两个伙伴卫星各自只显示本人发出或收到的公开边，
其余桌面在 Focus 模式中降权。

```jsonl
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:1","roomId":"room-peer","sequence":1,"turnId":"peer-root-1","eventType":"user_message","participantId":null,"sourceSessionId":"","topicId":"topic-peer-review","createdAtMs":1787400600010,"payload":{"rootId":"peer-root-1","messageId":"peer-user-1","clientMessageId":"peer-client-1","text":"让界面伙伴和复核伙伴直接确认窄窗规则，主持者最后只给结论。"},"resumeToken":"room-peer:1"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:2","roomId":"room-peer","sequence":2,"turnId":"peer-root-1","eventType":"route_decision","participantId":"peer-facilitator","sourceSessionId":"session-peer-facilitator","topicId":"topic-peer-review","createdAtMs":1787400600020,"payload":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-root","targetParticipantId":"peer-facilitator"},"resumeToken":"room-peer:2"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:3","roomId":"room-peer","sequence":3,"turnId":"peer-root-1","eventType":"route_decision","participantId":"peer-ui","sourceSessionId":"session-peer-ui","topicId":"topic-peer-review","createdAtMs":1787400600030,"payload":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-ui","parentDispatchId":"dispatch-peer-root","targetParticipantId":"peer-ui","child":true},"resumeToken":"room-peer:3"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:4","roomId":"room-peer","sequence":4,"turnId":"peer-root-1","eventType":"route_decision","participantId":"peer-review","sourceSessionId":"session-peer-review","topicId":"topic-peer-review","createdAtMs":1787400600040,"payload":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-review","parentDispatchId":"dispatch-peer-root","targetParticipantId":"peer-review","child":true},"resumeToken":"room-peer:4"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:5","roomId":"room-peer","sequence":5,"turnId":"peer-root-1","eventType":"participant_activity","participantId":"peer-ui","sourceSessionId":"session-peer-ui","topicId":"topic-peer-review","createdAtMs":1787400600050,"payload":{"sourceEventId":"session-peer-ui:11","sourceEventType":"peer_message","data":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-ui","activityKind":"intercom","phase":"delivered","message":{"id":"peer-message-ask","kind":"ask","sourceParticipantId":"peer-ui","targetParticipantId":"peer-review","status":"delivered","content":"请直接核对 420px 时审批卡是否仍留在所属 lane。"}}},"resumeToken":"room-peer:5"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:6","roomId":"room-peer","sequence":6,"turnId":"peer-root-1","eventType":"participant_activity","participantId":"peer-review","sourceSessionId":"session-peer-review","topicId":"topic-peer-review","createdAtMs":1787400600060,"payload":{"sourceEventId":"session-peer-review:21","sourceEventType":"tool_finished","data":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-review","toolCallId":"tool-peer-narrow","toolName":"browser","summary":"420px 窄窗复核通过","isError":false,"result":{"viewportWidth":420,"approvalLanePreserved":true}}},"resumeToken":"room-peer:6"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:7","roomId":"room-peer","sequence":7,"turnId":"peer-root-1","eventType":"participant_activity","participantId":"peer-review","sourceSessionId":"session-peer-review","topicId":"topic-peer-review","createdAtMs":1787400600070,"payload":{"sourceEventId":"session-peer-review:22","sourceEventType":"peer_message","data":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-review","activityKind":"intercom","phase":"delivered","message":{"id":"peer-message-reply","kind":"reply","sourceParticipantId":"peer-review","targetParticipantId":"peer-ui","status":"delivered","content":"已核对：审批卡留在原 lane，次要治理面板折叠。","replyTo":"peer-message-ask"}}},"resumeToken":"room-peer:7"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:8","roomId":"room-peer","sequence":8,"turnId":"peer-root-1","eventType":"room_post","participantId":"peer-facilitator","sourceSessionId":"session-peer-facilitator","topicId":"topic-peer-review","createdAtMs":1787400600080,"payload":{"rootId":"peer-root-1","dispatchId":"dispatch-peer-root","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"peer-root-result","roomId":"room-peer","rootId":"peer-root-1","generation":0,"dispatchId":"dispatch-peer-root","authorActorRef":"participant:peer-facilitator","kind":"result","visibility":"root","content":"直接问答已完成：420px 下审批仍归属原执行 lane，次要治理内容有序折叠。","idempotencyKey":"peer-root-result","publicationSource":{"kind":"room_commit","ref":"commit:peer-root-result"},"createdAtMs":1787400600080}},"resumeToken":"room-peer:8"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-peer:9","roomId":"room-peer","sequence":9,"turnId":"peer-root-1","eventType":"turn_completed","participantId":null,"sourceSessionId":"","topicId":"topic-peer-review","createdAtMs":1787400600090,"payload":{"rootId":"peer-root-1","status":"completed"},"resumeToken":"room-peer:9"}
```

Source refs：`control-center-web/src/paw-os/apps/PawRoomWorkspace.tsx` (`PawRoomConversation`); `control-center-web/src/paw-os/apps/PawRoomConversation.test.tsx`; `control-center-web/src/features/paw-os/PawOsSatelliteHost.tsx`; `control-center-web/src/paw-os/shell/PawWindowLayer.tsx`; `control-center-web/src/features/rooms/RoomTaskGraph.peer-relations.test.ts`; `control-center-web/src/features/rooms/runtime/room-execution-lanes.test.ts`; `control-center-web/src/contracts/room-reducer.ts`。

### 场景包 A：四人 Room 的完整协作对话 [S]

这不是“四张伙伴卡”，而是同一个 `room-01` 的连续产品场景。四位参与者各自绑定一个 Pi Session；Room 只负责公开路由、顺序、协作对象和最终 Root。这里所有名字、内容、路径、ID 和时间均为脱敏合成值，但字段和 reducer 语义来自当前源码。

#### A1. 初始 `agent.room.snapshot`：四位参与者、话题与三个 WorkItem

```json
{
  "schemaVersion": "rag-ime.agent-room-snapshot.v1",
  "ok": true,
  "room": {
    "schemaVersion": "rag-ime.agent-room.v1",
    "id": "room-01",
    "title": "PAWOS 多人协作验收",
    "status": "active",
    "roomKind": "collaboration",
    "description": "实现、运行核对与独立复核在一个 Room 中公开协作。",
    "routingPolicy": "parallel",
    "moderatorParticipantId": "participant-facilitator",
    "activeTopicId": "topic-room-focus",
    "configRevision": 3,
    "workspaceRoots": ["<workspace>/project-01"],
    "executionMode": "workspace_managed",
    "createdAtMs": 1787400000000,
    "updatedAtMs": 1787400300000,
    "lastEventSequence": 0,
    "participants": [
      {
        "schemaVersion": "rag-ime.agent-participant.v1",
        "id": "participant-facilitator",
        "roomId": "room-01",
        "sessionId": "session-room-facilitator",
        "roleId": "room-facilitator",
        "roleVersion": "1",
        "displayName": "主理 Agent",
        "collaborationRole": "coordinator",
        "status": "active",
        "ordinal": 0,
        "createdAtMs": 1787400000000,
        "lastSpokeAtMs": null
      },
      {
        "schemaVersion": "rag-ime.agent-participant.v1",
        "id": "participant-implementer",
        "roomId": "room-01",
        "sessionId": "session-room-implementer",
        "roleId": "frontend-implementer",
        "roleVersion": "1",
        "displayName": "界面 Agent",
        "collaborationRole": "implementer",
        "status": "active",
        "ordinal": 1,
        "createdAtMs": 1787400000010,
        "lastSpokeAtMs": null
      },
      {
        "schemaVersion": "rag-ime.agent-participant.v1",
        "id": "participant-runtime",
        "roomId": "room-01",
        "sessionId": "session-room-runtime",
        "roleId": "runtime-verifier",
        "roleVersion": "1",
        "displayName": "运行 Agent",
        "collaborationRole": "researcher",
        "status": "active",
        "ordinal": 2,
        "createdAtMs": 1787400000020,
        "lastSpokeAtMs": null
      },
      {
        "schemaVersion": "rag-ime.agent-participant.v1",
        "id": "participant-reviewer",
        "roomId": "room-01",
        "sessionId": "session-room-reviewer",
        "roleId": "independent-reviewer",
        "roleVersion": "1",
        "displayName": "复核 Agent",
        "collaborationRole": "reviewer",
        "status": "active",
        "ordinal": 3,
        "createdAtMs": 1787400000030,
        "lastSpokeAtMs": null
      }
    ],
    "topics": [{
      "id": "topic-room-focus",
      "roomId": "room-01",
      "title": "Room Focus 与真实信息流",
      "summary": "核对主时间线、卫星上下文和工具执行视图。",
      "status": "active",
      "ordinal": 0,
      "createdAtMs": 1787400000100,
      "updatedAtMs": 1787400000100
    }],
    "artifacts": [],
    "workItems": [
      {
        "schemaVersion": "rag-ime.agent-room-work-item.v1",
        "id": "work-room-layout",
        "roomId": "room-01",
        "topicId": "topic-room-focus",
        "rootTurnId": "room-turn-01",
        "rootWorkId": "work-room-layout",
        "parentWorkId": "",
        "objective": "完成 Room 主时间线与四人 Focus 排布",
        "expectedOutput": "可在宽窗和窄窗渲染的真实 Room 工作面",
        "acceptanceCriteria": ["不显示 Agent 头像", "主对话优先", "四个伙伴上下文可读"],
        "accountableParticipantId": "participant-facilitator",
        "currentOwnerParticipantId": "participant-implementer",
        "offeredToParticipantId": "",
        "createdByParticipantId": "participant-facilitator",
        "clientMessageId": "room-client-01",
        "assignmentKey": "room-01:layout",
        "state": "active",
        "depth": 1,
        "revision": 0,
        "resultSummary": "",
        "artifactRefs": [],
        "evidenceRefs": [],
        "blocker": {},
        "acceptedTurnId": "room-turn-01",
        "createdAtMs": 1787400300000,
        "updatedAtMs": 1787400300000,
        "completedAtMs": null
      },
      {
        "schemaVersion": "rag-ime.agent-room-work-item.v1",
        "id": "work-runtime-proof",
        "roomId": "room-01",
        "topicId": "topic-room-focus",
        "rootTurnId": "room-turn-01",
        "rootWorkId": "work-runtime-proof",
        "parentWorkId": "",
        "objective": "核对 Browser 与 Terminal 的真实运行投影",
        "expectedOutput": "同一事件链上的 Tool 与目标窗口证据",
        "acceptanceCriteria": ["Browser target 与 trace 同源", "Terminal 显示真实运行状态"],
        "accountableParticipantId": "participant-facilitator",
        "currentOwnerParticipantId": "participant-runtime",
        "offeredToParticipantId": "",
        "createdByParticipantId": "participant-facilitator",
        "clientMessageId": "room-client-01",
        "assignmentKey": "room-01:runtime",
        "state": "active",
        "depth": 1,
        "revision": 0,
        "resultSummary": "",
        "artifactRefs": [],
        "evidenceRefs": [],
        "blocker": {},
        "acceptedTurnId": "room-turn-01",
        "createdAtMs": 1787400300000,
        "updatedAtMs": 1787400300000,
        "completedAtMs": null
      },
      {
        "schemaVersion": "rag-ime.agent-room-work-item.v1",
        "id": "work-independent-review",
        "roomId": "room-01",
        "topicId": "topic-room-focus",
        "rootTurnId": "room-turn-01",
        "rootWorkId": "work-independent-review",
        "parentWorkId": "",
        "objective": "独立检查错行、遮挡、失败恢复与最终收束",
        "expectedOutput": "带证据的通过或阻塞结论",
        "acceptanceCriteria": ["检查长中文", "检查 420px 窄窗", "不把局部失败冒充成功"],
        "accountableParticipantId": "participant-facilitator",
        "currentOwnerParticipantId": "participant-reviewer",
        "offeredToParticipantId": "",
        "createdByParticipantId": "participant-facilitator",
        "clientMessageId": "room-client-01",
        "assignmentKey": "room-01:review",
        "state": "queued",
        "depth": 1,
        "revision": 0,
        "resultSummary": "",
        "artifactRefs": [],
        "evidenceRefs": [],
        "blocker": {},
        "acceptedTurnId": "room-turn-01",
        "createdAtMs": 1787400300000,
        "updatedAtMs": 1787400300000,
        "completedAtMs": null
      }
    ]
  },
  "events": [],
  "firstSequence": 0,
  "lastSequence": 0,
  "resumeToken": "",
  "truncated": false
}
```

#### A2. `agent.room.events`：三轮连续 JSONL

第 1 轮四人并行工作并完成；第 2 轮复核工具失败，Root 如实失败；第 3 轮是用户的新输入，复用已完成证据并重跑失败部分。网页模型必须按 `sequence` 渲染，不得按角色分组后打乱时间。

```jsonl
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:1","roomId":"room-01","sequence":1,"turnId":"room-turn-01","eventType":"user_message","participantId":null,"sourceSessionId":"","topicId":"topic-room-focus","createdAtMs":1787400300010,"payload":{"rootId":"room-turn-01","messageId":"room-user-01","clientMessageId":"room-client-01","text":"请四位一起完成 Room Focus：界面实现、Browser/Terminal 运行核对、窄窗复核，最后由主理 Agent 给一个结论。"},"resumeToken":"room-01:1"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:2","roomId":"room-01","sequence":2,"turnId":"room-turn-01","eventType":"route_decision","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400300020,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-facilitator-01","targetParticipantId":"participant-facilitator"},"resumeToken":"room-01:2"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:3","roomId":"room-01","sequence":3,"turnId":"room-turn-01","eventType":"route_decision","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300030,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","parentDispatchId":"dispatch-facilitator-01","targetParticipantId":"participant-implementer","child":true},"resumeToken":"room-01:3"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:4","roomId":"room-01","sequence":4,"turnId":"room-turn-01","eventType":"route_decision","participantId":"participant-runtime","sourceSessionId":"session-room-runtime","topicId":"topic-room-focus","createdAtMs":1787400300040,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-runtime-01","parentDispatchId":"dispatch-facilitator-01","targetParticipantId":"participant-runtime","child":true},"resumeToken":"room-01:4"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:5","roomId":"room-01","sequence":5,"turnId":"room-turn-01","eventType":"route_decision","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400300050,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-reviewer-01","parentDispatchId":"dispatch-facilitator-01","targetParticipantId":"participant-reviewer","child":true},"resumeToken":"room-01:5"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:6","roomId":"room-01","sequence":6,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400300060,"payload":{"sourceEventId":"session-room-facilitator:11","sourceEventType":"reasoning_summary","data":{"rootId":"room-turn-01","dispatchId":"dispatch-facilitator-01","state":"running","summary":"已分成界面、运行和独立复核三条公开工作线。"}},"resumeToken":"room-01:6"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:7","roomId":"room-01","sequence":7,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300070,"payload":{"sourceEventId":"session-room-implementer:21","sourceEventType":"tool_started","data":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","toolCallId":"tool-bash-layout","toolName":"bash","args":{"command":"pnpm exec vitest run PawRoomConversation.test.tsx","cwd":"<workspace>/project-01/control-center-web"}}},"resumeToken":"room-01:7"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:8","roomId":"room-01","sequence":8,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300080,"payload":{"sourceEventId":"session-room-implementer:22","sourceEventType":"tool_progress","data":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","toolCallId":"tool-bash-layout","toolName":"bash","summary":"正在运行 Room 时间线聚焦测试。"}},"resumeToken":"room-01:8"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:9","roomId":"room-01","sequence":9,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300090,"payload":{"sourceEventId":"session-room-implementer:23","sourceEventType":"tool_finished","data":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","toolCallId":"tool-bash-layout","toolName":"bash","summary":"Room 时间线聚焦测试通过 6 项。","isError":false,"result":{"runId":"run-layout-01","terminalId":"terminal-layout-01","exitCode":0,"outputPreview":"6 tests passed","outputTruncated":false}}},"resumeToken":"room-01:9"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:10","roomId":"room-01","sequence":10,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300100,"payload":{"sourceEventId":"session-room-implementer:24","sourceEventType":"approval_required","data":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","approvalId":"approval-layout-write","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","toolId":"workspace_write","operation":"apply","state":"pending","summary":"等待确认写入 Room Focus 样式。"}},"resumeToken":"room-01:10"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:11","roomId":"room-01","sequence":11,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300110,"payload":{"sourceEventId":"session-room-implementer:25","sourceEventType":"approval_resolved","data":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","approvalId":"approval-layout-write","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"approved","resolutionState":"approved","resolutionSource":"user","approvalDecisionReceiptId":"approval-decision-01","summary":"用户已批准写入。"}},"resumeToken":"room-01:11"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:12","roomId":"room-01","sequence":12,"turnId":"room-turn-01","eventType":"room_post","participantId":"participant-implementer","sourceSessionId":"session-room-implementer","topicId":"topic-room-focus","createdAtMs":1787400300120,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-implementer-01","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-implementer-01","roomId":"room-01","rootId":"room-turn-01","generation":0,"dispatchId":"dispatch-implementer-01","authorActorRef":"participant:participant-implementer","kind":"work_result","visibility":"room","content":"Room 主时间线已保持对话优先；四个伙伴位使用无头像文字身份，窄窗收起次要治理面板。","idempotencyKey":"post-implementer-01","publicationSource":{"kind":"room_commit","ref":"commit:post-implementer-01"},"createdAtMs":1787400300120}},"resumeToken":"room-01:12"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:13","roomId":"room-01","sequence":13,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-runtime","sourceSessionId":"session-room-runtime","topicId":"topic-room-focus","createdAtMs":1787400300130,"payload":{"sourceEventId":"session-room-runtime:31","sourceEventType":"tool_started","data":{"rootId":"room-turn-01","dispatchId":"dispatch-runtime-01","toolCallId":"tool-browser-runtime","toolName":"browser","targetId":"target-pawos-preview","tabId":41,"commandId":"browser-command-01","args":{"action":"navigate","url":"https://example.test/room-focus"}}},"resumeToken":"room-01:13"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:14","roomId":"room-01","sequence":14,"turnId":"room-turn-01","eventType":"participant_activity","participantId":"participant-runtime","sourceSessionId":"session-room-runtime","topicId":"topic-room-focus","createdAtMs":1787400300140,"payload":{"sourceEventId":"session-room-runtime:32","sourceEventType":"tool_finished","data":{"rootId":"room-turn-01","dispatchId":"dispatch-runtime-01","toolCallId":"tool-browser-runtime","toolName":"browser","targetId":"target-pawos-preview","tabId":41,"commandId":"browser-command-01","summary":"同窗 Browser target 已打开并完成导航。","isError":false,"result":{"title":"Room Focus Preview","url":"https://example.test/room-focus"}}},"resumeToken":"room-01:14"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:15","roomId":"room-01","sequence":15,"turnId":"room-turn-01","eventType":"room_post","participantId":"participant-runtime","sourceSessionId":"session-room-runtime","topicId":"topic-room-focus","createdAtMs":1787400300150,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-runtime-01","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-runtime-01","roomId":"room-01","rootId":"room-turn-01","generation":0,"dispatchId":"dispatch-runtime-01","authorActorRef":"participant:participant-runtime","kind":"work_result","visibility":"room","content":"Browser target、Agent trace 与可见页面使用同一 target；bash 运行也已投影到 PAWOS 内嵌 Terminal。","idempotencyKey":"post-runtime-01","publicationSource":{"kind":"room_commit","ref":"commit:post-runtime-01"},"createdAtMs":1787400300150}},"resumeToken":"room-01:15"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:16","roomId":"room-01","sequence":16,"turnId":"room-turn-01","eventType":"participant_delta","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400300160,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-reviewer-01","messageId":"review-stream-01","blockId":"review-stream-01:text","contentIndex":0,"delta":"已完成宽窗、常规窗和 420px 窄窗检查；"},"resumeToken":"room-01:16"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:17","roomId":"room-01","sequence":17,"turnId":"room-turn-01","eventType":"room_post","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400300170,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-reviewer-01","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-reviewer-01","roomId":"room-01","rootId":"room-turn-01","generation":0,"dispatchId":"dispatch-reviewer-01","authorActorRef":"participant:participant-reviewer","kind":"review_result","visibility":"room","content":"宽窗、常规窗和 420px 窄窗均无标题错行；长中文会换行，审批卡保持在当前执行 lane 内。","idempotencyKey":"post-reviewer-01","publicationSource":{"kind":"room_commit","ref":"commit:post-reviewer-01"},"createdAtMs":1787400300170}},"resumeToken":"room-01:17"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:18","roomId":"room-01","sequence":18,"turnId":"room-turn-01","eventType":"room_post","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400300180,"payload":{"rootId":"room-turn-01","dispatchId":"dispatch-facilitator-01","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-root-01","roomId":"room-01","rootId":"room-turn-01","generation":0,"dispatchId":"dispatch-facilitator-01","authorActorRef":"participant:participant-facilitator","kind":"result","visibility":"root","content":"本轮完成：主时间线、四人 Focus、Terminal/Browser 执行投影和窄窗复核均有公开证据。","idempotencyKey":"post-root-01","publicationSource":{"kind":"room_commit","ref":"commit:post-root-01"},"createdAtMs":1787400300180}},"resumeToken":"room-01:18"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:19","roomId":"room-01","sequence":19,"turnId":"room-turn-01","eventType":"turn_completed","participantId":null,"sourceSessionId":"","topicId":"topic-room-focus","createdAtMs":1787400300190,"payload":{"rootId":"room-turn-01","status":"completed"},"resumeToken":"room-01:19"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:20","roomId":"room-01","sequence":20,"turnId":"room-turn-02","eventType":"user_message","participantId":null,"sourceSessionId":"","topicId":"topic-room-focus","createdAtMs":1787400310000,"payload":{"rootId":"room-turn-02","messageId":"room-user-02","clientMessageId":"room-client-02","text":"再检查一次超长中英文混排和卫星窗口恢复。"},"resumeToken":"room-01:20"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:21","roomId":"room-01","sequence":21,"turnId":"room-turn-02","eventType":"route_decision","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400310010,"payload":{"rootId":"room-turn-02","dispatchId":"dispatch-facilitator-02","targetParticipantId":"participant-facilitator"},"resumeToken":"room-01:21"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:22","roomId":"room-01","sequence":22,"turnId":"room-turn-02","eventType":"route_decision","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400310020,"payload":{"rootId":"room-turn-02","dispatchId":"dispatch-reviewer-02","parentDispatchId":"dispatch-facilitator-02","targetParticipantId":"participant-reviewer","child":true},"resumeToken":"room-01:22"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:23","roomId":"room-01","sequence":23,"turnId":"room-turn-02","eventType":"participant_activity","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400310030,"payload":{"sourceEventId":"session-room-reviewer:41","sourceEventType":"tool_started","data":{"rootId":"room-turn-02","dispatchId":"dispatch-reviewer-02","toolCallId":"tool-read-screenshot","toolName":"read","args":{"path":"<workspace>/project-01/output/room-focus.png"}}},"resumeToken":"room-01:23"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:24","roomId":"room-01","sequence":24,"turnId":"room-turn-02","eventType":"participant_activity","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400310040,"payload":{"sourceEventId":"session-room-reviewer:42","sourceEventType":"tool_finished","data":{"rootId":"room-turn-02","dispatchId":"dispatch-reviewer-02","toolCallId":"tool-read-screenshot","toolName":"read","summary":"截图证据尚未生成。","isError":true,"result":{"error":"ENOENT","outputPreview":"room-focus.png 不存在","outputTruncated":false}}},"resumeToken":"room-01:24"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:25","roomId":"room-01","sequence":25,"turnId":"room-turn-02","eventType":"turn_failed","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400310050,"payload":{"rootId":"room-turn-02","dispatchId":"dispatch-reviewer-02","summary":"缺少本轮安装态截图证据","nextStep":"生成截图后只重跑独立复核"},"resumeToken":"room-01:25"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:26","roomId":"room-01","sequence":26,"turnId":"room-turn-02","eventType":"room_post","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400310060,"payload":{"rootId":"room-turn-02","dispatchId":"dispatch-facilitator-02","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-blocked-02","roomId":"room-01","rootId":"room-turn-02","generation":0,"dispatchId":"dispatch-facilitator-02","authorActorRef":"participant:participant-facilitator","kind":"blocked","visibility":"root","content":"源码检查保留，但安装态截图缺失；本轮不能宣称视觉验收完成。","idempotencyKey":"post-blocked-02","publicationSource":{"kind":"room_commit","ref":"commit:post-blocked-02"},"createdAtMs":1787400310060}},"resumeToken":"room-01:26"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:27","roomId":"room-01","sequence":27,"turnId":"room-turn-02","eventType":"turn_failed","participantId":null,"sourceSessionId":"","topicId":"topic-room-focus","createdAtMs":1787400310070,"payload":{"rootId":"room-turn-02","error":"一条复核 lane 未完成"},"resumeToken":"room-01:27"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:28","roomId":"room-01","sequence":28,"turnId":"room-turn-03","eventType":"user_message","participantId":null,"sourceSessionId":"","topicId":"topic-room-focus","createdAtMs":1787400320000,"payload":{"rootId":"room-turn-03","messageId":"room-user-03","clientMessageId":"room-client-03","text":"截图已经生成。保留上一轮已完成结果，只重跑复核并给我最终结论。"},"resumeToken":"room-01:28"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:29","roomId":"room-01","sequence":29,"turnId":"room-turn-03","eventType":"route_decision","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400320010,"payload":{"rootId":"room-turn-03","dispatchId":"dispatch-facilitator-03","targetParticipantId":"participant-facilitator"},"resumeToken":"room-01:29"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:30","roomId":"room-01","sequence":30,"turnId":"room-turn-03","eventType":"route_decision","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400320020,"payload":{"rootId":"room-turn-03","dispatchId":"dispatch-reviewer-03","parentDispatchId":"dispatch-facilitator-03","targetParticipantId":"participant-reviewer","child":true},"resumeToken":"room-01:30"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:31","roomId":"room-01","sequence":31,"turnId":"room-turn-03","eventType":"participant_activity","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400320030,"payload":{"sourceEventId":"session-room-reviewer:43","sourceEventType":"current_progress","data":{"rootId":"room-turn-03","dispatchId":"dispatch-reviewer-03","state":"running","summary":"已读取新截图，正在检查卫星收起后的背景恢复。"}},"resumeToken":"room-01:31"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:32","roomId":"room-01","sequence":32,"turnId":"room-turn-03","eventType":"room_post","participantId":"participant-reviewer","sourceSessionId":"session-room-reviewer","topicId":"topic-room-focus","createdAtMs":1787400320040,"payload":{"rootId":"room-turn-03","dispatchId":"dispatch-reviewer-03","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-reviewer-03","roomId":"room-01","rootId":"room-turn-03","generation":0,"dispatchId":"dispatch-reviewer-03","authorActorRef":"participant:participant-reviewer","kind":"review_result","visibility":"room","content":"新截图已核对：Focus 打开时背景降权，关闭最后一个卫星后恢复；长中英文内容未遮挡操作。","idempotencyKey":"post-reviewer-03","publicationSource":{"kind":"room_commit","ref":"commit:post-reviewer-03"},"createdAtMs":1787400320040}},"resumeToken":"room-01:32"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:33","roomId":"room-01","sequence":33,"turnId":"room-turn-03","eventType":"room_post","participantId":"participant-facilitator","sourceSessionId":"session-room-facilitator","topicId":"topic-room-focus","createdAtMs":1787400320050,"payload":{"rootId":"room-turn-03","dispatchId":"dispatch-facilitator-03","post":{"schemaVersion":"wisdom-weasel.room-post.v2","postId":"post-root-03","roomId":"room-01","rootId":"room-turn-03","generation":0,"dispatchId":"dispatch-facilitator-03","authorActorRef":"participant:participant-facilitator","kind":"result","visibility":"root","content":"最终结论：复核缺口已补齐；此前成功证据保留，失败操作只属于上一轮，当前轮已经成功收束。","idempotencyKey":"post-root-03","publicationSource":{"kind":"room_commit","ref":"commit:post-root-03"},"createdAtMs":1787400320050}},"resumeToken":"room-01:33"}
{"schemaVersion":"rag-ime.agent-room-event.v1","eventId":"room-01:34","roomId":"room-01","sequence":34,"turnId":"room-turn-03","eventType":"turn_completed","participantId":null,"sourceSessionId":"","topicId":"topic-room-focus","createdAtMs":1787400320060,"payload":{"rootId":"room-turn-03","status":"completed"},"resumeToken":"room-01:34"}
```

失败终态中“再试一次”的真实请求形状；这是交互样例，不属于上方 1–34 的已消费事件：

```json
{"pathId":"agent.room.message","params":{"roomId":"room-01"},"body":{"message":"再检查一次超长中英文混排和卫星窗口恢复。","clientMessageId":"paw-room-retry-fixture-01","attachmentIds":[],"retryOfRootId":"room-turn-02"}}
```

#### A3. 同一事件链派生的窗口与卫星目标 [UI]

以下是当前 `PawOsWindowTarget` / `runtimeToolWindowRequest()` 能生成的前端目标，不是新的 Gateway JSON。伙伴卫星从同一个 Room projection 筛出该 `participantId` 的公开消息与 activity；bash/browser 目标由第 7/13 条 Tool 事件自动投影。不要为卫星复制一份聊天 store。

```json
[
  {"appId":"agent","background":true,"target":{"kind":"participant","id":"participant-facilitator","title":"主理 Agent","subtitle":"最终汇合与回复 · session-room-facilitator","roomId":"room-01"}},
  {"appId":"agent","background":true,"target":{"kind":"participant","id":"participant-implementer","title":"界面 Agent","subtitle":"实现与验证 · session-room-implementer","roomId":"room-01"}},
  {"appId":"agent","background":true,"target":{"kind":"participant","id":"participant-runtime","title":"运行 Agent","subtitle":"调研与证据 · session-room-runtime","roomId":"room-01"}},
  {"appId":"agent","background":true,"target":{"kind":"participant","id":"participant-reviewer","title":"复核 Agent","subtitle":"最终独立复核 · session-room-reviewer","roomId":"room-01"}},
  {"appId":"terminal","background":true,"target":{"kind":"process-terminal","id":"tool-bash-layout","title":"pnpm exec vitest run PawRoomConversation.test.tsx","sessionId":"session-room-implementer","roomId":"room-01","participantId":"participant-implementer","toolCallId":"tool-bash-layout","runId":"run-layout-01","terminalId":"terminal-layout-01","command":"pnpm exec vitest run PawRoomConversation.test.tsx","cwd":"<workspace>/project-01/control-center-web","runStatus":"completed","exitCode":0}},
  {"appId":"browser","background":true,"target":{"kind":"browser-target","id":"target-pawos-preview","title":"Browser","sessionId":"session-room-runtime","roomId":"room-01","participantId":"participant-runtime","toolCallId":"tool-browser-runtime","targetId":"target-pawos-preview","tabId":41,"commandId":"browser-command-01"}}
]
```

#### A4. 渲染与交互断言

- `PawRoomConversation` 从 1–34 的权威顺序投影三轮公开 chronology，不按伙伴拆成四份聊天记录，也不把每条底层事件各画成一张卡；provisional delta、重复 lifecycle 和不公开 activity 先由 reducer 合并或过滤。
- 第 10 条进入 `waiting` 审批卡；只有第 11 条 receipt 后才显示继续，不能把 pending 当成功。
- 第 24–27 条只让 `room-turn-02` 失败；失败终态的“再试一次”通过 `retryOfRootId` 关联旧 Root。第 28 条是独立的新输入，失败证据仍可回看。
- `PawRoomConversation` 只为尚未被更新用户输入取代的当前 failed/aborted Turn 显示重试；新的用户消息到达后，旧失败摘要仍保留为历史，但其“再试一次”动作立即失效。迟到的旧 `turn_failed` 更新不得复活该动作。对应生产测试覆盖当前失败可重试、新输入后失效以及迟到事件不复活。
- Room Focus 中四个伙伴窗占四角/辅助轨，主 Room 保持中心；窗口标题不重复伙伴大卡。`PawOsSatelliteHost` 显示本人身份、当前 WorkItem、公开消息、Tool 和状态摘要；长 JSON、占位路径与格式占位 hash 默认收在“查看原始公开内容”，不展示私有 reasoning。
- 第 7 条打开/复用 PAWOS 内嵌 Terminal 目标，第 13 条打开/复用同窗 Browser target；它们是 Room Focus 的同组卫星，不启动外部 App。
- `PawWindowLayer` 从 `route_decision`、approval、intercom 和公开 result 派生 FlowPacket 动画与可收起 ledger；FlowPacket 只是一过性的 `[UI]` 投影，不写回 Runtime，也不持续挤压中央对话。

Source refs：`control-center-web/src/contracts/generated/agent-room.v1.ts`; `control-center-web/src/contracts/generated/agent-room-event.v1.ts`; `control-center-web/src/contracts/generated/agent-room-work-item.v1.ts`; `control-center-web/src/contracts/room-reducer.ts`; `control-center-web/src/contracts/room-reducer.test.ts`; `control-center-web/src/features/rooms/room-types.ts`; `control-center-web/src/paw-os/apps/PawRoomWorkspace.tsx` (`PawRoomConversation`); `control-center-web/src/paw-os/apps/PawRoomConversation.test.tsx`; `control-center-web/src/features/paw-os/model/desktop.ts`; `control-center-web/src/paw-os/runtime/runtime-tool-window.ts`; `control-center-web/src/paw-os/runtime/runtime-tool-window.test.ts`; `control-center-web/src/features/paw-os/PawOsSatelliteHost.tsx`; `control-center-web/src/features/paw-os/PawOsSatelliteHost.test.tsx`; `control-center-web/src/paw-os/shell/PawWindowLayer.tsx`; `control-center-web/src/paw-os/shell/PawWindowLayer.test.tsx`。

## 3. Memory

UI route：`/memory`  
PathIds：`memory.summary`, `memory.pages`, `agent.memoryMaintenance.run`, `agent.memoryMaintenance.trigger`

### normal [S]

```json
{
  "ok": true,
  "memoryBookCount": 3,
  "memoryAtomCount": 8,
  "activityTimelineCounts": {"draft": 1},
  "roleBookRevisionCounts": {"active": 1},
  "projection": {"fresh": true, "retrievalDocuments": 12, "backlog": 0}
}
```

```json
{
  "ok": true,
  "items": [{
    "id": "book-01",
    "type": "topic",
    "title": "控制中心迁移",
    "summary": "React 页面与受控接口",
    "status": "active",
    "source": "dsv4",
    "tags": ["控制中心", "迁移"],
    "updatedAtMs": 1787400300000
  }],
  "nextCursor": "",
  "limit": 50
}
```

### empty / maintenance / backoff [S]

```jsonl
{"ok":true,"items":[],"nextCursor":"","limit":50}
{"ok":true,"jobId":"memory-maintenance:01","state":"queued"}
{"ok":true,"jobId":"memory-maintenance:01","state":"running","progress":{"phase":"activity_timeline_catch_up","completedDayCount":2,"totalDayCount":19,"currentDate":"2026-08-10"}}
```

```json
{
  "ok": true,
  "autoApply": false,
  "scheduledDraftOnly": true,
  "ownerCuration": {
    "pendingSourceCount": 244,
    "needsReviewSourceCount": 10,
    "scopes": [{"status":"backoff","consecutiveFailures":14,"lastError":"受管记忆模型暂时不可用。"}]
  }
}
```

偏好页读取/写入 `configuration.settings` 的真实 preview/apply，不创建浏览器 localStorage 偏好真相。

Source refs：`features/memory/memory-feature.test.tsx`; `platform/routes.ts`。

## 4. Knowledge

UI route：`/knowledge`  
PathIds：`knowledgeBases.list/get`, `knowledgeBases.documents.list`, `knowledgeBases.jobs.list`, `knowledgeBases.graph.get`

### normal base [S]

```json
{
  "items": [{
    "id": "kb-01",
    "name": "伙伴运行资料",
    "description": "只包含已授权资料",
    "documentCount": 1,
    "chunkCount": 42,
    "status": "ready",
    "agentEnabled": false,
    "parserProvider": "auto",
    "updatedAtMs": 1787400300000,
    "revision": 8,
    "chunkingConfig": {"strategy":"markdown","size":1200,"overlap":160,"separator":"\n\n","respectHeadings":true,"respectPageBoundaries":true},
    "retrievalConfig": {"mode":"hybrid","topK":10,"threshold":0.2,"lexicalWeight":1,"denseWeight":1,"graphEnabled":true,"graphWeight":0.7,"rrfK":60,"candidateMultiplier":4}
  }]
}
```

### empty / processing / failure [S]

```json
{"items":[]}
```

```json
{
  "items": [{
    "id":"job-01","fileId":"file-01","fileName":"runtime.pdf","kind":"reindex","parserMode":"builtin",
    "status":"running","stage":"indexing","progress":0.8,"cancellable":true,"revision":3,
    "createdAtMs":1787400298000,"startedAtMs":1787400298500,"finishedAtMs":0,"updatedAtMs":1787400299500
  }]
}
```

```json
{
  "items": [{
    "id":"file-01","baseId":"kb-01","name":"runtime.pdf","mimeType":"application/pdf","byteSize":4096,
    "status":"failed","stage":"parse","progress":0.4,"error":"扫描文本质量不足","chunkCount":0,
    "parserProvider":"builtin","updatedAtMs":1787400300000,"revision":3,
    "sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "pageCount":12,"tokenCount":3200,"parserVersion":"builtin-1","indexedConfigRevision":8,
    "sourceReadPath":"/api/knowledge-bases/kb-01/documents/file-01/source"
  }]
}
```

Graph 直接验证的状态包括 `building`, `ready`, `stale`；导入成功不等于已可检索。

Source refs：`features/knowledge/knowledge-feature.test.tsx`; `platform/routes.ts`。

## 5. Input Studio

UI routes：`/input`, `/voice`, `/history`  
PathIds：`input.source.get`, `input.lexicon.review/apply/rollback`, `history.page`

### lexicon review [S]

```json
{
  "schemaVersion":"rag-ime.rime-lexicon-review.v1",
  "ok":true,
  "project":"project-01",
  "entryCount":1,
  "entries":[{
    "reviewKey":"项目名\txiang mu ming","text":"项目名","pinyin":"xiang mu ming","weight":180,
    "positiveCount":3,"negativeCount":0,"reasons":["accepted"],"reviewSource":"usage",
    "reviewReason":"来自真实选词反馈","selected":true
  }],
  "reviewToken":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "confirmText":"APPLY_REVIEWED_RIME_LEXICON",
  "applySupported":true,
  "reviewRequired":true
}
```

### apply / stale / pending [S][UI]

```jsonl
{"schemaVersion":"rag-ime.rime-lexicon-review.v1","ok":true,"applied":true,"entryCount":1,"rollbackId":"rollback-lexicon-01","requiresRedeploy":true}
{"schemaVersion":"rag-ime.rime-lexicon-review.v1","ok":false,"applied":false,"reason":"review_token_stale"}
```

pending apply：保持 `input.lexicon.apply` unresolved；不能提前显示成功 receipt。语音凭据只走 native/Keychain，样例中绝不放 token。

Source refs：`features/input-method/input-method-feature.test.tsx`; `platform/routes.ts`。

## 6. App Center

UI route：`/plugins`  
PathIds：`agent.extensions.list/catalog/proposals/validate/preview/apply`

### catalog [S]

```json
{
  "ok":true,
  "items":[{
    "id":"session-review","displayName":"Session Review","description":"基于事实审阅会话结果",
    "publisher":"Personal Agent Workbench","source":{"kind":"bundled","label":"Product bundle"},
    "permissions":["session.read"],"security":{"notes":"只读会话权限"},
    "versions":[{"version":"1.1.0"},{"version":"1.0.0"}],"latestVersion":"1.1.0",
    "installed":false,"updateAvailable":false,"actionable":true
  }]
}
```

### empty / validate / preview / receipt [S]

```jsonl
{"ok":true,"items":[]}
{"ok":true,"validationToken":"validation-token-01","extension":{"id":"guided-plugin","displayName":"Guided Plugin","version":"1.0.0","totalBytes":128}}
{"ok":true,"previewToken":"preview-token-01","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","summary":{"action":"install","pluginId":"guided-plugin","displayName":"Guided Plugin"}}
{"ok":true,"receipt":{"receiptId":"plugin:install:01"}}
```

preview token 只表示等待确认，不是安装完成。pending/error 通过 defer/reject validate、preview 或 apply。

Source refs：`features/plugins/plugins-feature.test.tsx`; `platform/routes.ts`。

## 7. System Monitor

UI routes：`/observability`, `/context-debug`, `/diagnostics`  
PathIds：`observability.snapshot/events`, `diagnostics.runtime`, `diagnostics.action.job`

### snapshot [S]

```json
{
  "schemaVersion":"rag-ime.observation-snapshot.v1","generatedAtMs":1787400300000,
  "firstSequence":1,"lastSequence":2,"resumeToken":"observation:2","truncated":false,
  "filters":{},"counts":{"total":1,"byCategory":{},"byStatus":{}},
  "items":[{
    "schemaVersion":"rag-ime.observation-event.v1","eventType":"observation","eventId":"observation:01",
    "sequence":1,"resumeToken":"observation:1","traceId":"trace:turn:01","spanId":"span:01","parentSpanId":"",
    "sessionId":"session-01","roomId":"","turnId":"turn-01","runId":"","category":"agent",
    "phase":"status_changed","name":"status_changed","status":"running","summary":"Agent 正在分析",
    "createdAtMs":1787400299000,"startedAtMs":1787400299000,"endedAtMs":null,"durationMs":null,
    "privacyClass":"redacted","metrics":{},"attributes":{},"refs":[]
  }]
}
```

### empty / mixed health / job failure [S]

```json
{"schemaVersion":"rag-ime.observation-snapshot.v1","generatedAtMs":1787400300000,"firstSequence":0,"lastSequence":0,"resumeToken":"","truncated":false,"filters":{},"counts":{"total":0,"byCategory":{},"byStatus":{}},"items":[]}
```

```jsonl
{"ok":true,"runtimeRevision":7,"runtimeConfig":{"postCommit":{"enabled":true}},"components":{"sidecar":{"ok":true,"status":"ready","detail":"运行中"},"voiceRecognition":{"ok":false,"status":"error","detail":"语音组件暂不支持完整转写"}}}
{"ok":true,"job":{"jobId":"runtime-job-01","action":"open_accessibility_settings","status":"failed","error":"修复任务失败","result":{}}}
```

Source refs：`features/observability/observability-feature.test.tsx`; `features/diagnostics/diagnostics-feature.test.tsx`; `platform/routes.ts`。

## 8. System Settings

UI routes：`/appearance`, `/configuration`, `/governance`, `/approvals`  
PathIds：`configuration.settings/schema/preview/apply/rollback`

### sanitized settings [S]

```json
{
  "ok":true,
  "settingsHash":"sha256:settings-synthetic",
  "settings":{
    "identity":{"productName":"PAW","assistantName":"伙伴","tagline":"个人 Agent 工作台"},
    "context":{"tokenBudget":2048},
    "activeRag":{"quickModel":"provider/model-fast","quickThinkingLevel":"high"}
  },
  "runtimeConfig":{"runtimeRevision":12,"settingsRevision":"sha256:settings-synthetic"}
}
```

### empty / preview / receipt / rollback [S][C]

```jsonl
{"ok":true,"settingsHash":"","settings":{},"runtimeConfig":{"runtimeRevision":0,"settingsRevision":""}}
{"schemaVersion":"rag-ime.management-work-preview.v1","ok":true,"previewToken":"preview-configuration-settings","pathId":"configuration.settings.apply","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expectedRevision":{"runtimeRevision":12,"subjectRevision":"sha256:before"},"expiresAtMs":1787400360000,"requiredConfirm":"apply","summary":{"title":"应用控制中心设置","items":["更新 context.tokenBudget","需要重启: sidecar"],"risk":"R2"}}
{"schemaVersion":"rag-ime.management-work-receipt.v1","ok":true,"receiptId":"receipt-configuration-apply","pathId":"configuration.settings.apply","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","appliedAtMs":1787400300000,"auditId":1,"rollbackAvailable":true,"rollbackToken":"rollback-configuration-settings","rollbackAuthority":{"settingKeys":["context.tokenBudget"]},"restartComponents":["sidecar"]}
{"schemaVersion":"rag-ime.management-work-receipt.v1","ok":true,"receiptId":"receipt-configuration-rollback","pathId":"configuration.settings.rollback","payloadSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","appliedAtMs":1787400310000,"auditId":2,"rollbackAvailable":false,"rollbackToken":"","rollbackAuthority":{"settingKeys":["context.tokenBudget"]},"restartComponents":["sidecar"]}
```

本轮只渲染一个默认主题；三主题切换 deferred。任何 credential 只显示 configured/not-set，不给模型值。

Source refs：`features/configuration/management-writes.test.tsx`; `platform/routes.ts`。

## 9. Files

UI route：`/files`  
PathIds：`agent.sessions.list`, `agent.session.workspace.list/read`

### authorized workspace [S]

```jsonl
{"ok":true,"activeSessionId":"session-01","items":[{"id":"session-01","title":"PAWOS 迁移","updatedAtMs":1787400300000,"workspaceRoots":["<workspace>/project-01"],"status":"idle"}]}
{"ok":true,"path":"<workspace>/project-01","items":[{"path":"<workspace>/project-01/docs","name":"docs","kind":"directory"},{"path":"<workspace>/project-01/AGENTS.md","name":"AGENTS.md","kind":"file","byteSize":128}]}
{"ok":true,"path":"<workspace>/project-01/AGENTS.md","content":"# Project guide\nRead docs before work.","byteSize":38,"truncated":false}
```

### empty / pending / error [S][UI]

```jsonl
{"ok":true,"activeSessionId":null,"items":[]}
{"ok":true,"path":"<workspace>/project-01","items":[]}
```

- defer/reject Session list、workspace list 或 read 分别验证对应 loading/error/retry。
- `truncated:true` 表示有界预览前缀，不是读取失败。
- 不展示 `/Users/...`、home、未授权 root 或任意机器文件。

Source refs：`features/files/PawOsFilesApp.tsx`; `features/files/paw-os-files-app.test.tsx`; `platform/routes.ts`。

## 10. Browser

UI route：`/browser`  
PathIds：`browser.tabs`, `browser.snapshot.latest`, `browser.traces`, `browser.command`, `browser.stop`

### tabs / snapshot / Agent trace [S]

```jsonl
{"ok":true,"items":[{"deviceId":"paw-browser","targetId":"target-01","tabId":41,"title":"Example","url":"https://example.com","active":true}]}
{"ok":true,"snapshotId":"snapshot-01","deviceId":"paw-browser","tabId":41,"url":"https://example.com","title":"Example","markdown":"# Example\n- [0:e1] button \"Continue\"","interactiveCount":1,"hasScreenshot":true,"imagePath":"/api/browser/snapshots/snapshot-01/image","createdAtMs":1787400300000}
{"ok":true,"items":[{"commandId":"command-01","action":"navigate","sourceKind":"agent","status":"completed","createdAtMs":1787400299860,"completedAtMs":1787400300000,"durationMs":140,"result":{"summary":"Example"}}]}
```

### empty / live / failure [S][C]

```jsonl
{"ok":true,"items":[]}
{"ok":true,"items":[{"commandId":"command-02","action":"navigate","sourceKind":"agent","status":"queued","createdAtMs":1787400300000,"completedAtMs":0,"durationMs":null,"result":{}}]}
{"ok":false,"status":"failed","summary":"页面暂时无法打开"}
```

consumer 还识别 `claimed` 为 live。实际 Electron 页面使用隔离 `persist:paw-browser`；样例不得包含 profile path、浏览历史、Cookie、下载路径或凭据。

Source refs：`paw-os/apps/PawBrowserApp.test.tsx`; `paw-os/apps/PawBrowserApp.tsx`; `platform/routes.ts`。

## 11. Terminal

UI route：`/terminal`  
PathIds：`terminal.sessions.list`, `terminal.session.create/read/write/resize/close`

### running PTY / cursor read [S]

```jsonl
{"schemaVersion":"rag-ime.system-terminal.v1","ok":true,"items":[{"terminalId":"terminal-01","title":"Terminal","cwd":"<workspace>/project-01","shell":"/bin/zsh","pid":4242,"cols":104,"rows":30,"status":"running","exitCode":null,"baseCursor":0,"nextCursor":18,"createdAtMs":1787400300000}]}
{"schemaVersion":"rag-ime.system-terminal.v1","ok":true,"terminal":{"terminalId":"terminal-01","title":"Terminal","cwd":"<workspace>/project-01","shell":"/bin/zsh","pid":4242,"cols":104,"rows":30,"status":"running","exitCode":null,"baseCursor":0,"nextCursor":18,"createdAtMs":1787400300000},"cursor":0,"nextCursor":18,"truncated":false,"text":"printf PAW_PTY_OK\r"}
```

### empty / exited / pending / error [S][UI]

```json
{"schemaVersion":"rag-ime.system-terminal.v1","ok":true,"items":[]}
```

```json
{"schemaVersion":"rag-ime.system-terminal.v1","ok":true,"items":[{"terminalId":"terminal-01","title":"Terminal","cwd":"<workspace>/project-01","shell":"/bin/zsh","pid":4242,"cols":104,"rows":30,"status":"exited","exitCode":1,"baseCursor":0,"nextCursor":96,"createdAtMs":1787400300000}]}
```

- terminal status 只有 `running`, `exited`, `closed`。
- create/read pending 用 unresolved Promise；reject list/read/write/resize/close 验证 inline error。
- cursor gap 或 `truncated:true` 必须重建可见 buffer，不能假装连续 append。
- 不放 Shell 历史、环境变量、凭据、真实命令、真实 PID 或真实文件路径；Terminal 是 PAWOS 内嵌 PTY，不启动 Ghostty/Terminal.app。

Source refs：`features/terminal/PawOsTerminalApp.tsx`; `features/terminal/paw-os-terminal-app.test.tsx`; `platform/routes.ts`。

## 最终护栏

这些样例只证明下一模型得到足够的字段和状态来正确设计与测试，不证明 route 已存在于当前安装、不证明原生 Browser/PTY 前台可用，也不证明任何 App 已统一验收。它们对齐 `UR-119`–`UR-122` 的生产 owner、Room 信息结构和 Agent 按需工具边界，但本文件本身不是结构迁移、生产状态或安装态验收证据。真实实现必须继续：

- 检查 `control.capabilities.routeIds`；
- 使用 typed `pathId` 和 allowlisted body；
- 保留 reducer cursor/revision/snapshot 规则；
- 展示诚实的 unavailable/loading/error/partial 状态；
- 产出真实项目 patch、测试、Preview 安装和前台证据；
- 确认 Agent 仍由 `PawSessionWorkspace`/`PawContextTrace` 消费同一生产 projection，Room 仍由 `PawRoomConversation`/`PawOsSatelliteHost`/`PawWindowLayer` 消费或派生同一 Room authority；
- 确认 Session 工具保持单入口、单侧栏、真实注意状态和简短可恢复空态，不从用户失败截图复制私人内容；
- 不把本文件、候选 HTML 或截图变成新的 PAWOS store，也不因 fixture 渲染正确而宣称 `UR-119`–`UR-122` 已验收。
