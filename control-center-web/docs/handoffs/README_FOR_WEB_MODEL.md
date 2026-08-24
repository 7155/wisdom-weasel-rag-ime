# PAWOS 网页模型工作区：先读我

这不是静态网页素材包，而是 Personal Agent Workbench 当前生产前端的可编辑工作区。你的任务是直接修改
`control-center-web/` 中现有 React + TypeScript + CSS + Electron 源码，保留真实 PAW/Pi Runtime 合同，
最终返回同样目录结构的源码 ZIP。不要只输出独立 HTML、截图、设计稿或另一套 demo Runtime。

## 一句话愿景

PAWOS 是一个明亮、轻透、年轻、精致、真正可日常使用的个人 Agent OS。全部设计决定都服务于美、清楚、
专注和真实操作；不是普通 SaaS Dashboard，不是旧后台换皮，也不依赖某张壁纸掩盖布局和信息架构问题。

## 必读顺序

1. `docs/pawos/PAWOS_REQUIREMENTS.md`：用户原始需求与最新纠正，当前到 `UR-125`。
2. `docs/handoffs/pawos/PAWOS_WEB_MODEL_APP_FUNCTION_HANDOFF.md`：11 个 App 的真实用户流程。
3. `docs/handoffs/pawos/PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md`：生产采样与完整渲染场景。
4. `docs/handoffs/pawos/PAWOS_FUNCTION_INTERFACE_GUIDE.md`：233 条 typed route 与前端能力地图。
5. `docs/pawos/PAWOS_FRONTEND_HANDOFF.md`：已迁移内容、验证证据和仍未闭环边界。
6. `docs/project/DESIGN.md`、`docs/project/PRODUCT.md`、`docs/project/ARCHITECTURE.md`：视觉、产品和权威边界。
7. 再读并修改 `control-center-web/`；`rag_ime/` 是后端合同参考，不要在纯前端优化中重写它。

`docs/handoffs/pawos/PAWOS_FRONTEND_MODEL_BUNDLE.md` 是上述文本与生产前端源码的单文件镜像，供检索或
上下文受限模型使用；本 ZIP 已同时提供原始目录，因此优先编辑真实文件。

## 绝对不能破坏的架构

- Pi Runtime 只拥有 Session、对话历史、Provider/模型与 Tool loop、compaction、Steer、Stop 和恢复。
- `rag_ime/` 是 PAW 产品后端，拥有 Room 编排、Memory、Knowledge、Browser/Terminal 工具合同、SQLite、
  权限与 HTTP/SSE。它调用 Pi，不重复实现 Pi。
- `control-center-web/` 是唯一新版生产前端。它消费 typed transport、reducers/projections、SSE 与
  Electron/native bridge；不得另建 mock-first store 或复制后端状态机。
- Room 属于 Agent，是一种专注协作模式，不是第 12 个顶层 App。
- Browser 和 Agent 控制同一个可见 target；Terminal 是 PAWOS 内嵌 PTY/xterm，不打开 Ghostty 或系统终端。
- 真实数据、成功/失败、审批、Stop、恢复和 revision 必须如实呈现；接口存在不等于当前安装实例已启用。

## 当前顶层产品地图

1. Project：项目概览、任务编排、工作文档三条真实路径。
2. Agent：对话优先、Session/Room、即时发送反馈、真实 Agent 轨迹、无头像。
3. Memory：第二大脑六页与真实持久化偏好。
4. Knowledge：知识库选择器，以及资料、材料、检索、图谱、处理、设置六页。
5. Input：输入法、词库、语音、输入记录。
6. App Center：已安装、目录、建议与真实 preview/apply/rollback mutation。
7. Monitor：活动、上下文、诊断。
8. Settings：Agent、外观、配置、治理、审批。
9. Files：真实授权目录树、选择、预览、错误和空态。
10. Browser：同窗可上网浏览器、标签页、地址栏、页面、下载、查找、打印、缩放、设置与 Ego/CDP 控制。
11. Terminal：同窗真实 PTY、输入输出、resize、Stop 与后台进程卫星。

## 视觉与交互硬约束

- 当前只做一个默认明亮主题；三主题延后。不要恢复大面积深色、暖工程纸或灰色后台感。
- 每个 App 单独从真实工作流设计，但共享精心统一的字体、字号、间距、色彩、窗口、Dock 和动效语言。
- 使用包内全彩独立 App 图标；不得恢复同一方框里换 glyph 的廉价图标系统。
- 正文通常 14–16px，可见 metadata 不低于 12px；中文、英文、数字和等宽内容都需真实窗口检查。
- 顶部只允许一层 App chrome。减少按钮，主动作唯一，二级能力按需披露，空态不写说明书。
- Agent 顶层只保留“对话 / Agent 轨迹”和一个按需 `Session 工具` 入口；轨迹不复制聊天原文或私有 Tool 参数。
- Room 顶层只保留“对话 / 协作工具”。四个协作工具页复用同一互斥面板；默认关闭，窄窗进入正常
  底部布局，不覆盖对话或 composer。`铺开 N 位伙伴` 是卫星/Room Focus 唯一主动作。
- 卫星不是普通随意堆叠窗口，而是专注当前 Room 的模式：背景弱化、主叙事强化、伙伴真实上下文可读、
  信息流向可理解，0/1/5/7 伙伴和窄窗都不能匿名、遮挡、错行或乱位。
- 动效用于空间连续性、状态、直接操作反馈和信息流转；以 transform/opacity 为主，普通交互低于 300ms，
  可中断，并完整支持 `prefers-reduced-motion`。
- 所有界面文案只说当前对象、状态、可执行动作、结果或恢复步骤；不要把架构和产品宣言写进 App UI。

## 真实数据怎么用

`PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md` 同时包含两类数据：

- “生产 Runtime 真实采样”：当前安装态 Gateway 的两个真实 Session canary，以及一个三伙伴 Room 的
  277 序列事件、并行 WorkItem、两条 `work_result`、Root 汇合和第二轮直接问答。敏感字段已稳定脱敏。
- “源码一致合成 fixture”：覆盖 normal/empty/loading/error/partial、失败后新输入、compaction、审批、
  Browser、Terminal、Memory、Knowledge 和其他 App 状态。

数据用于把页面撑到真实长度和状态，不得复制进生产 store。一条 event 不等于一张卡；必须先经过当前
reducer，再分别投影到对话、Agent 轨迹、Room 主窗、协作面板或卫星。

## 源码地图

- App/OS：`control-center-web/src/paw-os/`
- 生产 Feature owners：`control-center-web/src/features/`
- typed routes/transport：`control-center-web/src/platform/`
- contracts/reducers：`control-center-web/src/contracts/`、`control-center-web/src/features/agent/`
- Electron Browser/Terminal host：`control-center-web/electron/`
- 静态视觉资产：`control-center-web/public/`
- 前端测试：相邻 `*.test.ts(x)` 与 `control-center-web/e2e/`
- 后端 HTTP/SSE 路由：`rag_ime/debug_server.py`、`rag_ime/agent_routes.py`
- Room/Session 后端参考：`rag_ime/agent_rooms.py`、`rag_ime/agent_sessions.py`、`rag_ime/agent_service.py`
- Browser/Terminal 后端参考：`rag_ime/browser_control.py`、`rag_ime/paw_browser_runtime.py`、
  `rag_ime/system_terminal.py`

## 当前诚实边界

- 最新 Room/Agent 信息架构、Project mutation、独立图标、Memory/Knowledge/App Center/Files/Terminal 等已进入
  当前源码并有聚焦测试，但最终审美仍未由用户接受；因此你的主要任务是结构和视觉精修，不是另做 demo。
- Browser 当前可见 webview、真实网络、下载与 Ego/CDP 控制已接通；但 Electron webview 不生成可作为唯一
  权威的 Chromium 原生 `History` 数据库。不得把 PAW JSON sidecar 历史包装成“原生 History 已完成”。
- Preview 安装与测试不等于正式发布验收；不要删除这些诚实边界。

## 修改与交付规则

1. 直接修改真实 TSX/CSS/TypeScript owner；不要新建独立 HTML 产品实现。
2. 不改 API 字段、route authority 或 Runtime 行为来迁就视觉稿；先复用现有 consumer/reducer。
3. 每次页面调整同时检查宽窗、常规窗、560px、375px、长中文、长路径、空态、失败态和真实多伙伴数据。
4. 保留测试并为修复的布局/交互补最小回归；不要删除失败测试来通过。
5. 运行：`cd control-center-web && pnpm typecheck && pnpm test && pnpm build`。
6. 最终返回完整源码 ZIP，保留本包路径结构，并列出修改文件、测试结果和仍未验证事项。
7. 不提交凭据、Cookie、浏览历史、Shell 历史、SQLite、日志、缓存、构建产物或用户私人文本。
