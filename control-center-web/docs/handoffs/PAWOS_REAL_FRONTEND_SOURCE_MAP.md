# PAWOS 真实前端权威地图

> 给网页模型、外部评审模型和介绍页制作模型的第一份源码导航。机器可读版本是
> [`PAWOS_REAL_FRONTEND_SOURCE_MAP.v1.json`](PAWOS_REAL_FRONTEND_SOURCE_MAP.v1.json)，漂移检查是
> `python3 scripts/check_pawos_frontend_source_map.py`。

## 这份地图解决什么

仓库里同时存在生产源码、旧前端、Preview transport、fixture、静态 HTML、截图、测试、生成合同、原生宿主和
历史 handoff。按文件名搜索“看起来像前端”的文件会稳定找错。判断一个文件是否是真实前端，必须沿当前选择链
证明它确实会被产品入口渲染，或沿原生构建链证明它会被编译进 App。

当前请求回执（2026-08-28）：

> “目前正在做前端介绍页面，会需要真实前代代码做网页展示各个功能，可是网页模型老是找错，怎么告诉他每一个功能的真实前端”

本文件记录“在哪里”和“为什么是真的”；它不宣布功能完成，也不代替安装态或前台验收。

## 权威判定顺序

1. `src/main.tsx` 启动 `startControlCenter`，再挂载 `App`。
2. `frontend-product.ts` 默认选择 `paw-os`；`App.tsx` 因而渲染 `PawOsApp`。`legacy` 仍可显式选择，但不是默认产品。
3. `features/paw-os/model/app-registry.ts` 只定义 11 个 App 的身份和 route，不能单独证明哪个组件实际渲染。
4. `paw-os/apps/PawAppsRuntime.tsx` 的 `renderApp` 是 App、行星、subagent 卫星和结果窗口的当前总分派点。
5. 再沿它的 import/JSX 进入下表的叶子 render owner；CSS 只解释样式，不能反过来证明组件被选中。
6. 原生 Swift 表面必须由构建脚本证明。文件名像 UI、出现在 patch 或截图里都不够。

证据等级必须分开写：

| 等级 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| source-selected | 当前入口能沿 import/dispatch 到达该 owner | 构建、安装、运行、前台质量 |
| build-checked | 当前构建链纳入该源码且检查通过 | 已安装或当前正在运行 |
| installed | 某一已识别 revision 已安装 | 进程健康或页面可操作 |
| running | 进程/服务/宿主真实存在 | 前台交互正确或用户接受 |
| foreground-verified | 指定真实路径在前台操作通过 | 其他路径、审美或完整产品已接受 |
| user-accepted | 用户明确接受该结果 | 未覆盖路径自动完成 |

## React PAWOS 总入口

```text
control-center-web/src/main.tsx
  -> src/app/start-control-center.ts
  -> src/app/mount-control-center.tsx
  -> src/app/App.tsx
  -> src/paw-os/PawOsApp.tsx
  -> src/paw-os/shell/PawDesktop.tsx
  -> src/paw-os/shell/PawWindowLayer.tsx
  -> src/paw-os/apps/PawApps.tsx
  -> src/paw-os/apps/PawAppsRuntime.tsx
  -> 下表中的真实 App owner
```

PAWOS React 源码当前由 Electron 发布宿主加载：`scripts/build_control_center.sh` 明确转发给
`scripts/build_paw_os_electron_host.sh`，后者把 `electron/` 与 `dist/` 一起装入 App Resources；
`electron/main.mjs` 再显式加载 `?frontend=paw-os&pawHost=electron`。仓库中仍保留旧
`RagImeControlWebHost` 源码，但当前公共构建入口不选择它，因此它既不是发布宿主，也不是第二套 Swift 前端。

## 11 个 App 的真实前端

| App / 要展示的功能 | 真实 render owner | 当前选择证据 | 介绍页应打开/覆盖 |
| --- | --- | --- | --- |
| 项目工作台：概览、计划/目标/任务、工作文档 | `paw-os/apps/PawNativeApps.tsx`；`PawWorkbenchMigrated.tsx`；`PawWorkbenchDocumentLifecycle.tsx`；`PawWorkbenchOperations.tsx`；`PawWorkbenchPlanningTools.tsx` | `PawAppsRuntime.renderApp('project-workbench') -> PawNativeApp -> ProjectSurface` | `/overview`、`/planning`、`/work-documents`，含空态、preview/confirm、stale revision、receipt |
| Agent：首页、Session 对话、Agent 轨迹、Room、协同模式、行星/卫星/结果 | `PawAgentApp.tsx`；`PawAgentHome.tsx`；`PawSessionWorkspace.tsx`；`PawContextTrace.tsx`；`PawRoomWorkspace.tsx`；`features/paw-os/PawOsSatelliteHost.tsx`；`PawResultWindow.tsx` | `renderApp('agent') -> PawAgentApp`；带 panel 的 Room participant 行星、subagent 卫星、work-document、project、task、package、result、process-terminal 目标由同一分派点送进对应窗口 owner | `/agent`、`/rooms`；对话和轨迹分开展示，Room 不是第 12 个 App，不能用多路消息刷屏代替真实协作投影 |
| Memory：记忆库、伙伴记忆、时间线、关系图、整理、偏好 | `features/memory/index.tsx` 及 `RoleBookLayer.tsx`、`ActivityTimeline.tsx`、`MemoryRelations.tsx`、`MemoryCurationWorkbench.tsx`、`MemoryPreferences.tsx` | `renderApp('memory') -> PawNativeApp -> MemoryFeature` | `/memory` 与各 `view`；召回/整理结果和 Trace/Eval 状态必须来自真实 transport，不造记忆 |
| Knowledge：知识库、资料/文档、检索/处理、图谱 | `features/knowledge/index.tsx`；`document-workspace.tsx`；`knowledge-graph.tsx`；`interactive-graph-canvas.tsx` | `renderApp('knowledge') -> PawNativeApp -> KnowledgeFeature` | `/knowledge`；材料、索引 job、查询、图谱、空/失败/处理中状态 |
| Input Studio：输入法、词库、语音管理、输入记录 | `paw-os/apps/PawSystemAppsMigrated.tsx`；`features/input-method/index.tsx`；`lexicon-workflow.tsx`；`features/voice/index.tsx`；`features/history/index.tsx` | `renderApp('input-studio') -> PawNativeApp -> PawSystemAppsMigrated -> InputMethodFeature/InputLexiconFeature/VoiceFeature/HistoryFeature` | `/input`、`/input?view=lexicon`、`/voice`、`/history`；这是管理 UI，不是输入时浮层 |
| App Center：已安装、目录、Agent 建议 | `PawSystemAppsMigrated.tsx`；`features/plugins/index.tsx` | `renderApp('app-center') -> PawNativeApp -> PawSystemAppsMigrated -> PluginsFeature/PawPackageCatalog` | `/plugins`、`?view=catalog`、`?view=proposals`；保留 validate/preview/confirm/apply/rollback 边界 |
| System Monitor：活动/Trace/Eval、上下文、Trace Agent、诊断 | `PawSystemAppsMigrated.tsx`；`features/observability/index.tsx`；`features/context-debug/index.tsx`；`features/trace-agent/index.tsx`；`features/diagnostics/index.tsx` | `renderApp('system-monitor') -> PawNativeApp -> PawSystemAppsMigrated` | `/observability`、`/context-debug`、`/trace-agent`、`/diagnostics`；Trace Agent 可看原对话和实际动作并进入诊断对话；真实指标与 AI Judge 估计必须分栏/分字段，不互相冒充 |
| System Settings：配置、外观、Agent 默认、治理、审批 | `PawSystemAppsMigrated.tsx`；`features/configuration/index.tsx`；`PawOsAppearanceSettings.tsx`；`features/governance/index.tsx`；`features/approvals/index.tsx` | `renderApp('system-settings') -> PawNativeApp -> PawSystemAppsMigrated` | `/configuration`、`/appearance`、`?view=agent`、`/governance`、`/approvals` |
| Files：授权工作区树、选择、预览、真实错误 | `features/files/PawOsFilesApp.tsx`；`SvgFilePreview.tsx` | `renderApp('files') -> lazy import PawOsFilesApp -> FilesApp` | `/files`；文件/文件夹是 OS 投影，不能复制 transcript、写 Finder/Git 或成为第二权威 |
| Browser：标签、地址栏、同一个可见 guest、查找/状态/历史/下载/设置 | `paw-os/apps/PawBrowserApp.tsx`；`features/browser/BrowserTabStrip.tsx`、`BrowserOmnibox.tsx`、`BrowserFindBar.tsx`、`BrowserPageStatus.tsx`；host 语义在 `paw-browser-host.ts` 和 `electron/` | `renderApp('browser') -> PawBrowserApp`；组件创建 `<webview>`；Electron `will-attach-webview` 固定隔离 partition | `/browser`；PAW React chrome 加同窗真实 guest，不能拿后端截图或另一浏览器窗口冒充 |
| Terminal：内嵌 PTY 与后台进程运行窗口 | `features/terminal/PawOsTerminalApp.tsx`；后台 process 由 `PawOsSatelliteHost.tsx` | `renderApp('terminal') -> lazy import PawOsTerminalApp`；`process-terminal` target 走运行窗口分派 | `/terminal`；真实 session/read/write/resize/close 状态，不打开系统终端或用假日志 |

上述所有相对路径都以 `control-center-web/src/` 为基准，除非表中明确写了 `electron/` 或 `features/`。
完整、无缩写的路径和选择标记在 JSON manifest 中。

## 不是 App、但介绍页通常也要展示的真实表面

- 桌面 Wayfinder / Project Field：`paw-os/shell/PawWayfinderWork.tsx` 与
  `features/project-field/index.tsx`。`PawOsApp.syncPawOsRoute` 在 route 不属于 App 时调用
  `showWayfinder()`，`PawDesktop` 再渲染它。它不是第 12 个 App；其中明确标记的“交互预览”回退也不是
  Runtime 事实。
- 窗口、Dock、Overview、拖拽/缩放、协作 Focus：从 `PawDesktop.tsx`、`PawWindowLayer.tsx` 和
  `paw-os/runtime/desktop-store.ts` 读取；App 自己不另画一套窗口权威。
- 行星、subagent 卫星和结果窗：`PawAppsRuntime.tsx` 的 target 分支加 `PawOsSatelliteHost.tsx`、`PawResultWindow.tsx`。
- 共用视觉入口：`paw-os/styles/paw-os.css` 及其 import 的 PAWOS 样式层。单个历史 CSS 文件存在，不代表
  它当前会生效；必须从 import 链确认。

## 原生前端：不能让模型再靠文件名猜

### 输入时 Assistant Overlay

真实 repo-owned UI 是：

- `squirrel-patches/sources/RagImeAssistantSurfaceState.swift`
- `squirrel-patches/sources/RagImeSuggestionCardView.swift`
- `squirrel-patches/sources/RagImeSuggestionRowView.swift`
- `squirrel-patches/sources/RagImeNonActivatingPanel.swift`
- `squirrel-patches/sources/RagImeAssistantPanelController.swift`

`scripts/prepare_squirrel_workspace.sh` 会把这些文件复制到固定 Squirrel 工作区，并为 Card、Row、Panel 等写入
PBXFileReference、PBXBuildFile 和 Sources build phase；`scripts/build_patched_squirrel.sh` 再检查并构建，CI
顺序执行这两步。因此 `RagImeSuggestionCardView.swift` 已有 production build-selection 证据，不是“候选文件”。

边界：Rime/Squirrel 自己仍负责拼音解析、原生候选、翻页和 fallback；上面这些文件是 PAW Assistant
Overlay，不是用 React 或另一候选窗替换 Rime。

### 语音浮层

真实 SwiftUI owner 是 `macos/RagImeVoice/VoiceOverlay.swift`，由 `VoiceInputCoordinator.swift` 持有。
`scripts/build_voice_input.sh` 将 `macos/RagImeVoice` 和 `macos/Shared` 下所有 Swift 源加入 `swiftc`，所以它与
PAWOS 内 `/voice` 管理页是两个不同真实表面：一个负责输入时反馈，一个负责配置/状态。

### 历史 WKWebView Control Center（当前不选中）

`macos/RagImeControlWebHost/WebHostView.swift` 和 `scripts/build_control_center_web_host.sh` 仍在仓库中，
但 `scripts/build_control_center.sh` 当前只分派到 Electron builder。网页模型不能因为文件仍存在就把它当作
当前发布宿主，更不能把 Swift host 当成另一套 App UI。

## 明确排除的“像前端但不是当前 owner”

- `src/app/preview-*`、fixture、seed：只用于预览/测试数据。
- `docs/references/**/*.html`、网页模型产出的 HTML/PNG、截图：只作设计或交互参考。
- `docs/**`、handoff、需求文档：描述产品，不渲染产品。
- `*.test.*`：验证证据，不是实现 owner。
- `dist/**`：构建产物，不能编辑为第二权威。
- `src/contracts/generated/**`：数据类型合同，不是视觉组件。
- `features/project-field/prototype-data.ts`：可为选中的 Wayfinder 提供显式预览回退，但不是 Runtime truth。
- `integrations/ego-browser/**`：当前 untracked/reference 边界，不属于 PAWOS 生产前端入口。
- `macos/RagImeControlWebHost/**`、`scripts/build_control_center_web_host.sh`：历史 WKWebView 宿主源码，当前公共
  构建入口未选择。

## 直接贴给网页模型的固定指令

```text
你正在为 PAWOS 制作前端介绍/展示，不得按文件名或网页搜索结果猜“真实前端”。

第一步只读：
1. control-center-web/CLOUD_MODEL.md
2. control-center-web/docs/handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.md
3. control-center-web/docs/handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.v1.json

对每个要展示的功能，先返回下面这张证据表，经证据成立后才读/改代码：
- feature/app id
- default or native entry
- exact selectionChain（入口、dispatch 或 build script）
- exact renderOwners
- exact styleOwners
- Runtime/host boundary
- excluded lookalikes
- proof level：source-selected / build-checked / installed / running / foreground-verified / user-accepted

只把 JSON manifest 中 authority 为 production-selected、production-selected-shell-surface 或
production-build-selected-native-surface 的 owner 当实现来源。介绍页可复用真实组件或从真实 owner 提取结构，
但不得把 preview transport、fixture、测试、静态 HTML、截图、dist、生成合同或旧 handoff 当实现；不得把
showcase 数据写回生产 store。

11 个 App 必须与 registry 精确一致；Room 在 Agent 内，不是第 12 个 App。Browser 必须展示 PAW React chrome
和同一个 Electron webview guest；Files 是 Runtime/OS 投影；Squirrel Assistant Overlay 与 Voice Overlay 是
单列原生表面。每次结论附具体路径和选择/构建标记。找不到选择链时写 unverified，不自行补一个“看起来像”的文件。

完成后运行：python3 scripts/check_pawos_frontend_source_map.py
源码、测试、构建、安装、运行和前台验收分别报告，互不冒充。
```

## 当前打包选择证据

`control-center-web/package.json` 的 `desktop:build` 指向现存的
`../scripts/build_paw_os_electron_host.sh`；公共 `scripts/build_control_center.sh` 也只转发到该 Electron builder。
builder 会复制 `electron/` 与 `dist/`，并在 release manifest 中声明 `browserHost: electron-webview`。这些是
源码选择与构建接线证据，不等于本轮已经完成打包、安装、启动或前台验收。

## 维护规则

修改以下任一处时，同一改动必须更新 JSON manifest 并运行检查器：

- 11 App registry；
- `PawAppsRuntime.renderApp`；
- 某 App 的叶子 render owner；
- Wayfinder、行星/卫星或窗口总分派；
- Squirrel/Voice/Electron host 构建脚本；
- 当前生产前端入口。

检查器只验证 registry 对齐、路径存在、选择/构建标记仍存在、权威 owner 未落入 preview/docs/test/dist 等
排除区。它不会宣称 UI 已安装、已运行、好看或已被用户接受。
