# PAWOS 用户需求账本 · UR-121–UR-150

> 导航：[UR-091–UR-120](PAWOS_REQUIREMENTS_091_120.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-151–UR-180](PAWOS_REQUIREMENTS_151_180.md)
>
> current 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-121 — Room Focus 旧卡片拼窗形态是明确失败基线

- **状态 / 优先级：** `current / P0 correction`
- 用户提供的当前安装态截图不是目标方向：中心仍堆叠旧式完成卡，卫星窗匿名重复且直接铺出长路径、
  hash 和原始回执，顶部 tab 被压成竖排，主内容与 header/composer 互相遮挡，底部流转条抢占画布，
  整体仍像旧后台拼窗而不是专注当前 Room 的信息空间。
- 新 Room Focus 必须让中央公开对话成为主叙事；Tool/WorkItem/审批是紧凑内联活动或按需披露。卫星窗
  明确显示伙伴身份、当前职责、真实 WorkItem、Tool 生命周期和状态；默认只给结构化摘要，原始详情
  由用户主动展开。流转 ledger 为次级可收起信息，不得持续挤压主画布。
- **验收：** 常规与窄宽度下 tab/标题不竖排、不裁切，正文使用可读 14–16px 层级，时间线不被固定
  header/composer 遮住；0/1/5+ 伙伴布局均不匿名重复。安装态真实 Gateway 的同一历史 Room 必须与
  失败截图形成明显结构差异，不能只换色或圆角。
- **原话依据：** “ui没改好啊”。附件截图只作为当前失败状态的视觉证据，不把其中历史 Room 文本、
  路径或浏览器 chrome 视为新指令。来源：当前任务与附件
  `codex-clipboard-<redacted-room-focus-id>.png`。

### UR-122 — Agent 工具必须按需披露，禁止重复按钮、重叠工具条和空面板挤压对话

- **状态 / 优先级：** `current / P0 correction`
- Agent 主窗口只保留“对话 / Agent 轨迹”两个一级视图。Todo、长期目标、子 Agent、文件、运行状态
  等 Session 工具不得同时形成第二排重复 tab、多个永久按钮和并列大抽屉；它们收敛为一个按需入口，
  由用户主动打开，或在真实待处理事项需要关注时以一个紧凑状态提示出现。
- 工具入口打开后的面板必须复用同一侧栏容器和关闭动作；同一对象不能同时出现在“任务中心”、
  “子 Agent 工作台”和轨迹主体中占据三份主要空间。无 Todo、无长期 Goal、无子 Agent、无文件或
  Session 未驻留时，不渲染说明书式大空态，只显示一句可恢复状态与必要动作。
- **验收：** 常规宽度和窄宽度下，一级 tab、工具入口、二级筛选、标题、关闭按钮、提示条和主内容
  不重叠、不竖排、不越界；打开工具侧栏仍保留可读的主对话/轨迹列。按钮数量以真实当前动作最少化，
  不保留为了“展示功能齐全”而常驻的控制。安装态截图必须关闭用户本次三张失败图中的重复工具条、
  Todo/Goal 空抽屉和子 Agent 右栏覆盖问题。
- **原话依据：** “按钮该减少减少，当前界面全是bug”。附件只作为当前失败布局证据，不把其中
  Session 名称、错误文本或浏览器状态视为新的产品指令。来源：当前任务与附件
  `codex-clipboard-<redacted-tools-id-1>.png`、
  `codex-clipboard-<redacted-tools-id-2>.png`、
  `codex-clipboard-<redacted-tools-id-3>.png`。

### UR-123 — Room 协作工具必须收敛为单一按需工作区，不得覆盖对话或重复伙伴动作

- **状态 / 优先级：** `current / P0 correction`
- Room 主窗口只保留“对话 / 协作工具”两个一级视图；伙伴、消息流、任务流、治理、进展不得同时形成
  第二排永久工具条、覆盖主内容的大浮层或重复 chips。协作工具进入一个互斥的按需侧栏；窄窗改用同一
  底部共享面板，关闭后必须完整释放对话空间。
- 关闭“协同态势”侧栏只关闭该信息面，不退出 Room Focus Mode；主对话、当前行星/卫星与真实协作
  聚焦继续保持。协作聚焦的退出必须是另一个显式动作，不能和面板关闭绑定。
- “铺开 N 位伙伴”是进入 Room Focus/卫星模式的唯一主动作；伙伴身份只在该动作的必要摘要或已打开的
  协作工具面板中出现一次。协作状态只保留一个紧凑、真实事件驱动的提示，不在标题栏、工具层和正文
  重复展示。
- **验收：** 默认 Room 对话没有工具面板；四个工具页互斥复用同一容器；常规、560px 与 375px 宽度下
  标题、一级视图、伙伴动作、状态和正文不重叠、不竖排、不越界。安装态截图必须关闭本次失败图中的
  大浮层覆盖、重复伙伴 chips、重复“铺开伙伴”和多层工具导航。
- **原话依据：** “逻辑好好优化，然后打包”。附件只作为当前失败布局与重复信息架构的视觉证据，
  不把其中历史 Room 名称、伙伴名字或消息内容视为新的产品指令。来源：当前任务与附件
  `codex-clipboard-<redacted-room-tools-id>.png`。最新控制修正来源：OMP `b2d77cd2`，
  `2026-09-03T01:41:24.016Z`。

### UR-124 — 网页模型包必须包含生产 Runtime 的真实 Session 与 Room 对话采样

- **状态 / 优先级：** `current / P0 correction`
- 面向下一网页模型的包不能只有源码、接口表或合成 fixture；必须另含当前安装态 Gateway 实际返回的
  安全 canary Session 与 Room 数据。至少覆盖两个真实 Session Turn，以及一个 Room 的多伙伴分派、
  Tool/失败事件、两个 WorkItem、`work_result`、Root 汇合、下一轮直接问答和终态顺序。
- 真实采样保留 schema、事件类型、`sequence`、时间戳、成功/失败、同一 Turn 归属与安全正文；UUID、
  Tool call id、hash、绝对路径、私有正文和原始 Tool 参数使用稳定 alias 或 `[redacted]`，不得把私人
  Runtime 数据直接交给外部模型。
- **验收：** 单独的真实数据 Markdown 能直接用于 Session 对话、Agent 轨迹、Room 主窗和协作工具面板
  的渲染；文档明确区分“生产采样”和“源码一致的合成 fixture”，并与最新版单文件源码包一起进入
  无 `__MACOSX`、无 `.DS_Store` 的 ZIP。
- **原话依据：** “打包吧，因为我感觉你前端修复不好了。我让网页模型修复，打包需要真实room和
  session对话数据”。来源：当前任务。

### UR-125 — 网页模型 ZIP 必须提供可直接修改的完整代码工作区，而不只是单文件转录

- **状态 / 优先级：** `current / P0 correction`
- 网页模型已支持 ZIP 后，交接包必须保留真实仓库目录结构，包含当前 `control-center-web/` 源码、
  Electron 宿主、公共视觉资产、相邻测试、E2E 与构建配置；同时提供必要 `rag_ime/` 后端合同参考、
  相关构建/检查脚本、许可证、愿景、完整需求、逐 App 功能说明、接口目录、Handoff 和真实脱敏数据。
- 包内必须有一个先读说明，明确可编辑前端与只读后端参考、Pi/PAW/前端权威边界、11 App、默认明亮
  单主题、Agent/Room 信息架构、Browser/Terminal 边界、构建测试命令及期望交付格式。下一模型必须直接
  返回修改后的源码 ZIP，不得只交独立 HTML、截图或 demo。
- ZIP 排除 dependency tree、构建产物、浏览器 profile、Cookie、浏览历史、Shell 历史、SQLite、日志、
  缓存、报告、截图和用户私人文本；不得因“全量”而打包机器数据或凭据。
- **原话依据：** “网页支持zip，你可以把他需要的所有代码和数据都打包，还有我的愿景和说明”。
  来源：当前任务。

### UR-126 — Browser 直接迁移 EgoLite 的前台体验与 Agent 执行特效

- **状态 / 优先级：** `current / P0 correction`
- 当前 PAWOS Browser 的功能接线不等于体验完成。普通浏览时必须让真实网页占据主体，使用干净、
  现代的 Chromium 浏览器 chrome；详细 Agent 轨迹默认收起。通用 App 标签样式不得把 Browser
  标签误做成黑色胶囊、后台卡片或第二层管理 UI。
- Agent/EgoLite 正在控制当前 exact `targetId` 时，同一个可见 guest 必须出现来源于真实 command/
  trace 状态的执行场：克制的蓝紫边界光、目标/动作反馈和底部紧凑任务胶囊，至少显示当前动作、目标、
  “接管”和“停止”。“接管”停止当前 Agent Browser run 并把输入焦点交回该网页；“停止”取消同一
  run。详细步骤仍可按需展开，但不得常驻挤压网页或另开 screenshot/第二 Browser。
- 特效只在真实执行或短暂完成反馈期间存在，不能用永久循环动画冒充 Agent 活动；高频网页操作保持
  即时，`prefers-reduced-motion` 保留状态/颜色反馈并去掉位移、缩放和持续扫描运动。
- `ego-lite` 开源仓库不含其闭源浏览器壳，因此“直接嵌入”按结果合同解释为：在 PAW 当前唯一
  Electron `webview`/隔离 Profile/CDP target 上直接迁移 EgoLite 可观察的 Browser 体验与特效，并
  继续复用已 vendor 的 `ego-browser` 控制内核；不得捆绑闭源 EgoLite App、启动第二浏览器或复制
  Browser authority。
- **双轴验收：** (1) 真实路径：安装态 Electron Browser 能在同一 guest 上浏览，真实 Agent
  Browser command 能驱动执行场、接管/停止和按需轨迹；(2) 需求满足：常态网页优先、chrome 不再
  被通用黑色标签规则污染，执行态视觉与 EgoLite 参考同类且不遮挡网页，常规/窄窗与 reduced-motion
  均可用。源码测试、静态截图或模拟 trace 不能单独关闭安装态轴。
- **原话依据：** “你直接把egolite浏览器嵌入我们os不行吗，现在我们os浏览器还是不完整”；更正：
  “ui丑，没ego的特效”。来源：当前任务。

### UR-127 — Browser 地址框必须是一个干净控件，OS App 层级不得落在 Dock 后面

- **状态 / 优先级：** `current / P0 foreground correction`
- Browser omnibox 必须表现为一个完整输入控件：外层承载圆角、白色底、细边界与 focus ring，内部真实
  `input` 保持透明、无独立边框、无第二个胶囊底色。旧 Composition/WebModel 的高特异性表单规则不得
  再把输入元素覆盖成米色底、深色描边或嵌套输入框。
- PAW Dock 是桌面启动器，不是永远压住 App 的系统遮罩。普通 App window 的堆叠层必须高于 Dock；
  两者几何相交时由 App 表面覆盖 Dock，Dock 只在未被窗口占用的桌面区域可见。Menu Bar、Launchpad、
  窗口总览和显式系统 overlay 继续按各自 owner 的层级处理，不能通过给单个 Browser 写特例解决。
- **验收：** 安装态 Browser 的 `input` 计算样式为透明且无边框，omnibox 外层为白色；所有普通
  window 的最低 stack 层高于 Dock，最大化或移动到 Dock 区域时 App 不被 Dock 覆盖。源码 CSS 断言
  与前台 Playwright 计算样式/矩形证据都通过。
- **原话依据：** “输入框不正常，而且os的app居然在docker后面”。来源：当前任务。

### UR-128 — Agent 必须连接当前 PAW Electron Browser，而不是共享 Profile 的陈旧调试端口

- **状态 / 优先级：** `current / P0 runtime correction`
- Preview 与 Release 可以同时存在并复用持久 Browser Profile，但 Agent Browser Runtime 必须把
  `PAWBrowserHost.pid` 指向的当前 Electron 宿主作为控制权威。共享 Profile 中的
  `DevToolsActivePort` 可能由另一宿主或已退出进程改写，不能在存在 live Electron handoff 时直接
  作为控制端口。
- Runtime 必须从当前宿主进程的本地监听端口中探测真实 CDP `/json/version`，只连接该宿主；找不到
  可验证端口时 fail closed。只有没有 live Electron handoff 的独立受管 Chromium 才回退读取
  Profile port file。不得通过手工改端口文件、停止另一个 PAW channel 或连接不明 Chromium 来伪造恢复。
- **验收：** 单元测试覆盖“live 宿主 + 陈旧共享端口”“live 宿主无自己的 CDP listener 时拒绝”以及
  独立 Chromium port-file 回退；安装态 Sidecar 在 Preview/Release 同时运行时仍返回当前 Preview 的
  exact webview，Browser 的 `tabs + traces` 轮询不再因错误端口整体失败，真实 Agent command 可触发
  `UR-126` 执行场并由“接管”取消同一 command。
- **原话依据：** 这是“现在我们os浏览器还是不完整”的真实路径根因修正；来源：当前任务及安装态诊断。

### UR-129 — Browser 必须在同一可见 guest 中真实完成任务，Ego Host 必须跟随当前宿主端口

- **状态 / 优先级：** `current / P0 real-task correction`
- “可打开网页”不等于任务完成。以“查看今天新闻”为验收样例时，Browser 必须冻结用户时区下的
  “今天”，在当前 PAWOS Browser 的同一个可见 guest 中访问真实新闻源、读取至少五条当天内容、
  返回可核验标题/链接/时间或摘要，并把最终新闻页留在前台；不得用演示数据、外部浏览器结果或
  screenshot 冒充执行。
- 常驻 Ego Host 的 Unix socket 可响应不代表其 Browser/CDP 仍有效。每次 `run` 前必须核对 doctor
  返回的 `cdpPort`、Profile 与当前 Electron Browser authority，并要求 `cdpUp=true`；旧 Host 绑定
  陈旧随机端口时必须只重启 Ego Host，再连接当前宿主，不得转而寻找或启动第二个 Chrome。
- **双轴验收：** (1) 回归测试证明旧 Host 端口或失联 CDP 会触发一次有界重启，匹配当前端口后才
  放行；(2) 安装态真实 `run` 通过 `taskSpaces` 驱动当前可见 guest 完成新闻任务，产生真实 trace，
  输出至少五条已读取内容，并以 `completed` 关闭该任务空间。底层 direct-CDP 成功可作为诊断证据，
  但不能单独替代完整 Ego `run` 验收。
- **原话依据：** “真实完成一个任务，比如查看今天新闻”。来源：当前任务。

### UR-130 — 后台 Bash 默认静默运行，仅在用户显式查看时打开同一运行视图

- **状态 / 优先级：** `current / P0 correction`
- Pi、Session、Room 或 Tool Agent 启动后台 `shell`/`bash`/process 时，PAWOS 只在主对话或任务状态中
  显示紧凑的运行、完成、失败或停止反馈；不得因为 Tool 启动、进度事件、输出分片或 Room 切换而自动
  弹出 Terminal/Process 窗口、卫星窗或独立 macOS App，也不得抢走 Composer 焦点。
- 只有用户显式点击“查看后台 Bash”“查看终端”或等价运行入口后，才打开 PAWOS 内嵌视图。视图必须
  复用原始 `runId`/`terminalId` 的命令、cwd、stdout/stderr、退出码和 Stop/cancel 状态，不得重新执行
  命令、复制一份进程或按每个事件制造新窗口。
- 用户关闭或退出该视图只影响投影，不取消仍在运行的后台任务；再次查看应恢复同一运行上下文。Room
  Focus Mode 中也遵守按需显示，不能把所有后台 Bash 自动铺成卫星窗口。
- **验收：** 安装态分别触发普通 Session 与 Room 的长、短后台命令；未点击查看前窗口数、焦点和
  Composer 保持不变，仅显示紧凑状态。显式查看后只出现一个 PAWOS 内嵌投影，输出连续且 `runId`
  相同；关闭再打开不重跑，结束后可查退出状态。覆盖迟到进度、Room 切换与多段 stdout。
- **原话依据：** “命令行默认不弹出，只有用户专门点击查看后台运行的bash才弹出”。来源：当前任务。

### UR-131 — PAWOS 右键菜单必须能按 App 或全桌面一键关闭窗口

- **状态 / 优先级：** `current / P0 foreground correction`
- 桌面 App 图标、Dock App 图标和已打开窗口都使用 PAWOS 自己的右键菜单。对 App 图标右键时，菜单
  必须提供“关闭该 App 的全部窗口”；对具体窗口右键时，同时提供关闭当前窗口和关闭该 App 全部窗口；
  对桌面空白处右键时，存在窗口才提供“一键关闭全部窗口”。不得回退到浏览器原生菜单。
- “关闭全部”只关闭 PAWOS 的窗口投影，不停止后台 Bash、Browser command、Session、Room 或其他
  Runtime 工作；用户之后再次显式查看同一 `runId`/`targetId` 时恢复原运行，而不是重新执行。
- 关闭后必须同时清理 window stack、active window、Overview 和 Room/Session Focus 的失效引用；若关闭
  的只是某个 App，其余 App 的最上层可见窗口成为 active。菜单标签必须包含 App 名称，避免误关范围。
- **验收：** 单元测试覆盖 Dock/App 图标右键、窗口右键、桌面空白右键、零窗口禁用/隐藏、多个同 App
  窗口与混合 App 窗口；安装态验证一次点击关闭准确范围，后台任务继续运行且随后查看仍是同一 runId。
- **原话依据：** “你先改正窗口弹出，右键功能一键关闭所有”。来源：当前任务，2026-08-24。

### UR-132 — 当前单一明亮外观统一为圆角冷色系统，旧方形纸面层退出运行时

- **状态 / 优先级：** `current / P0 visual correction`
- 当前设置页只暴露一套“默认明亮”外观；运行时内部可继续用 `blueprint` 作为兼容存储值，但该 ID
  不再授权旧蓝图主题把窗口、标题栏、Dock、菜单、卡片或交通灯改回方角纸面。共享 shell 使用一套
  冷白、轻蓝、圆角、细边界的组件语法，逐 App 颜色只通过身份、选中、导航和内容材质参与层级。
- 全局色彩控制原则是“冷白空间中散布少量高质量彩色坐标”：冷白材质承载正文和复杂信息，较高彩度
  只用于 App 身份图标、当前导航、关键动作和真实状态信号；大面积容器仅允许极淡身份染色。颜色帮助
  识别和导航，不得喧宾夺主，也不能用“全部变淡”削弱应用辨识度。
- **反 Aero 合同：** 普通窗口不得使用 Windows 7/Aero 式蓝灰标题栏、双层描边、内外高光、凸起
  bevel、厚重常驻投影或立体交通灯。常态窗口使用冷白单层表面、1px 低对比边界和近乎无阴影；只有
  活动/拖动窗口获得极轻的环境分离，菜单与浮层使用短而柔的局部阴影。交通灯保持扁平语义色，焦点
  通过单一 focus ring 或颜色/层级变化表达，不能叠出第二个蓝框。
- 本条取代 `UR-061` 的“默认直角几何”和 `UR-072` 的“交通灯采用方形”视觉部分；`UR-072` 的窗口
  关闭/最小化/最大化 authority、独立实例生命周期、命中区和不重叠合同继续有效。文档型对象可在其
  内容内部使用克制的纸面材质，但不能由全局高优先级 CSS 把整个 App 拉回另一套视觉系统。
- **验收：** 删除旧主题对共享 shell 的高优先级/`!important` 覆盖；普通窗口只有一组圆形交通灯，
  标题和 portalled App 控件始终位于其右侧安全区；Dock、窗口、菜单和浮层使用同一 radius/border/focus
  体系。覆盖 active/inactive、窄窗、reduced motion、键盘焦点与 11 App，安装态逐页截图仍是最终门槛。
- **原话依据：** “当前这个我看到这个还是两套 UI……系统 UI 它是蓝色的、圆角的嘛，然后点开好多
  界面，它还是方形的，就是之前那种纸质风格，所以现在还是很错乱”“交通灯不能和其他按钮重复”。
  来源：当前任务，2026-08-24。补充控制语义：“为冷白空间中散布少量高质量彩色坐标，颜色帮助识别
  和导航，不要喧宾夺主”“当前这种 app 界面有一种 Windows 7 的复古感，就是不该有的阴影有了，
  当代不怎么用这些了”。来源：当前任务，2026-08-26。

### UR-133 — Agent 对话内置受治理的 Memory Recall 与 Knowledge/Agent RAG

- **状态 / 优先级：** `current / P0 conversation capability`
- Agent 对话的能力选择必须包含两个彼此清楚、可单独开关的真实能力：**Memory Recall** 负责从个人
  Memory 中召回与当前问题、最近对话和当前项目相关的记忆；**Knowledge / Agent RAG** 负责从选定
  Knowledge 库检索，并允许 Agent 在现有权限和配置合同内调整检索策略、反复搜索和收敛证据。两者
  复用现有 Memory、Knowledge、Active RAG、Skill 和上下文装配 owner，不建立平行向量库或第二套
  对话 Runtime。
- 召回查询同时考虑用户的新问题、近期对话和项目上下文；发生 compaction 后，后续召回必须使用当前
  压缩摘要/保留上下文继续生成查询，不能因为原始长对话退出窗口就停止 RAG。用户提到的“百分之最新
  对话”是策略方向，**精确比例在现有合同核实前保持可配置/未定，不在文档中臆造固定百分比**。
- Raw 输入、Memory Atom、Knowledge 文档、检索结果和最终上下文保持各自权威与治理边界。召回结果
  进入 Provider 上下文前遵守既有许可、预算、去重、来源和冷知识闸门；开关关闭时不得暗中注入。
- **用户可见验收：** Composer/能力菜单能看见并切换两项能力；真实一轮对话分别触发 Memory 与
  Knowledge 检索，最终上下文可证明命中来源；压缩后再问相关问题仍能重新召回。关闭开关后，相应
  来源不进入这一轮装配。
- **原话依据：** “那个对话能力里面加入记忆召回和知识库这些技能，因为这是对话的必要功能”
  “根据用户的最近发的内容或者新问的问题或者项目来进行RAG”“压缩之后就会根据压缩之后的内容来
  进行RAG”“还有一个能力就是Agent RAG……默认是就是给知识库用的……反复搜索”。来源：当前任务，
  2026-08-26 15:43。

### UR-134 — Memory/RAG 注入必须在对话与上下文装配中留下可追溯收据

- **状态 / 优先级：** `current / P0 visibility`
- 每次实际使用 Memory Recall 或 Knowledge/Agent RAG，都必须由现有 Runtime/context trace 产生真实
  投影：对话时间线的思考/工具区显示“使用了 Memory”或“使用了 Knowledge RAG”、耗时、命中数和
  有界摘要；上下文装配/Agent 轨迹显示对应层、预算、disposition 和 Provider delivery。未执行时不得
  伪造活动卡。
- 每条召回收据标注可公开的来源类型、条目/文档标题或安全标识、相关度/选择结果，并能跳转到 Memory
  Atom、Knowledge 文档或精确 context-trace 节点。跳转是只读反向投影，不复制聊天原文，也不把
  context trace 变成新的权威数据库。
- **用户可见验收：** 从对话中的 RAG 收据可进入来源条目，再从来源条目回到使用它的 Session/trace；
  同一轮的上下文分层与工具活动能对上，来源不可用时诚实显示而不是空白。
- **原话依据：** “得展示出来，比如说那个上下文装配或者天文技能或者聊天过程中，就得在那个思考
  或者工具里面展示一下使用了记忆或者使用了RAG。可以标注来源，跳转过去。”来源：当前任务，
  2026-08-26 15:43。

### UR-135 — 模型与推理强度分层选择，弹层按内容收敛而非做成大面板

- **状态 / 优先级：** `current / P0 visual interaction`
- Composer 中**选择模型**与**选择推理强度**必须是相邻但完全独立的紧凑控件，不能继续使用一个
  摘要按钮或同一纵列菜单。模型入口只展开真实可用模型并显示数量；强度入口只打开当前模型支持的
  紧凑离散强度轨/选择器。选择模型后可以校正不再受支持的强度值，但不得自动打开强度面板，也不能
  让长模型列表与强度控件同时占据一个高大弹层。
- 弹层高度跟随实际内容并设合理上限；搜索/Provider 分组仅在模型足够多时出现。关闭、选择、Escape、
  外点、窄窗、键盘和焦点恢复都必须稳定。用户提到“三种情况/组合”，但本轮只明确了模型与强度两个
  子选择；第三种含义保持 `pending clarification`，不能自行新增产品概念。
- **原话依据：** “这个框就太大了”“一个就选择模型，然后它弹出有多少个模型。第二个就是强度，
  然后拉动强度条来选择”“这种交互没有认真设计，模型和思考强度不应该在同一列”。来源：当前任务，
  2026-08-26。

### UR-136 — 每个思考与 Tool 活动显示真实耗时和 token/返回占用

- **状态 / 优先级：** `current / P0 observability`
- 思考活动显示持续时间与 Runtime 提供的 reasoning/output token；每个 Tool 行除成功/失败外，显示真实
  耗时、公开返回大小，以及能够从权威 usage/trace 归属的输入、输出或上下文 token。Tool 内容默认
  收起，摘要行必须足够判断成本与结果。
- 若 Provider/Runtime 没有提供可靠的逐 Tool token 归属，UI 必须显示“未提供”或带明确标签的估算，
  不得把字符数、整轮 usage 或缓存量伪装成精确的 Tool token。Context Usage 的总量必须拆成系统提示词、
  项目/角色/Skill、用户消息、Agent 消息、Tool 定义、Tool 结果、Memory/Knowledge 注入、压缩摘要和
  其他已知层；弹层可以适度放大以便读清各部分。
- **用户可见验收：** 一轮包含思考、成功 Tool、失败 Tool、压缩和 RAG 的真实 Session 中，每行成本与
  状态一致；总上下文分层之和与总量关系可解释，未知项不被合并成误导性的单一红条。
- **原话依据：** “每个工具显示，还有这种思考啊，得显示手token的时间。工具右边就不只是成功与
  失败，还要显示返回，就占用多少token”“这个红条明明是分成各种提示词，各个部分，比如说Agent的
  输出和用户输出……工具调用……压缩……系统提示词”。来源：当前任务，2026-08-26 15:18、15:52。

### UR-137 — 运行态、错误态与对话气泡降低框感并使用高质量状态动效

- **状态 / 优先级：** `current / P0 visual correction`
- 用户/Agent 消息、思考中状态和未完成错误都服从对话阅读节奏：气泡按内容收紧，不制造大片空白；
  “思考中”使用克制、清晰、不中断阅读的 live indicator，现有粗糙星球旋转和厚重描边不是验收基线；
  错误以靠近原消息的紧凑状态/可恢复动作呈现，不用一个大红框占满阅读列。
- 视觉弱化不能隐藏错误原因、恢复状态、Stop 或重新同步入口。运行结束时 indicator 必须由 terminal/
  durable snapshot 收敛为完成，不能在最终回复已经出现后继续显示“正在对话/思考中”。
- **原话依据：** “对话框太明显了，在下面空的很多”“右边这个也是一个框太明显了，和那个星球旋转
  动画太粗糙太劣质了”“当前还是对话早就结束了，但是还是显示正在对话”。来源：当前任务，
  2026-08-26 15:19、15:52。

### UR-138 — 流式输出不得闪烁、抢滚动或让长 Session 看起来丢历史

- **状态 / 优先级：** `current / P0 stability`
- 流式消息只追加稳定增量，已经完成的 chunk 不得反复卸载/重建或闪烁。自动跟随只在用户位于底部时
  生效；用户向上阅读或滚动时立即停止抢滚动，并提供“回到最新”。长 Session 的折叠/虚拟化不能删除
  durable 历史，也不能因为 compaction 或快照恢复把已经显示的回合暂时消失又重新出现。
- terminal SSE 漏失时，前端必须用 durable snapshot 静默收敛 active 状态；最终回复已出现后仍显示
  运行态、无法滚动、首屏对话框长时间不出现，均属于同一 P0 前端稳定性失败。
- 进入已存在 Session 时先立即挂载稳定的对话阅读面、轻量骨架与可用 Composer，再渐进恢复 durable
  历史、活动和调试投影；不得等待完整快照或轨迹查询结束后才让整个对话框出现。骨架不能伪造消息，
  恢复期间必须保留 Session identity、输入草稿和真实 loading/error 边界。
- **用户可见验收：** 在超长真实 Session 中持续输出并同时滚动，完成内容不闪、滚轮可自由上下、
  用户离底后不被拉回；终态出现后运行 indicator 及时消失。重开任务后当天 durable 消息仍可检索和
  逐步恢复，UI 若只加载局部必须明确标注。
- **原话依据：** “输出的时候，我那个一直闪烁，一直滚不动，滚轮没办法往下滚”“是不是对话历史又
  损失了，今天一天的记录”“那个对话框一时半会加载不出来”。来源：当前任务，2026-08-26。

### UR-139 — 本地前端为集成主线，远端早期提交只逐项择优吸收

- **状态 / 优先级：** `current / P0 integration constraint`
- 当前本地工作树是前端集成 authority。GitHub 其他分支只能通过逐提交/逐文件审查吸收确有价值且不
  覆盖本地新修复的改动，禁止整树 merge 或以远端旧视觉替换本地。用户明确允许查看 2026-08-26
  12:00 之前的提交，并要求忽略较晚提交；原话对 12:00–13:00 的边界不完全一致，该时段默认不自动
  引入，待精确确认或以明显早于 12:00 的提交为候选。
- **验收：** 每个吸收项记录来源 commit、选择理由、冲突处理和聚焦测试；本地 Session/Browser/Ego
  已验证能力不回退。完成后只提交本地整合结果到 `7155/personal-agent-workbench` 的明确分支。
- **原话依据：** “GitHub上面的另一分支，12点之前的你可以看一下哪些是可以用的，就把它合进来。
  那12点之后，1点之后的提交就不用管。那你就直接以本地的为主，把本地的交上去就行。”来源：
  当前任务，2026-08-26 15:17。

### UR-140 — Memory 月度整理先展示真实样例，并以同一后台任务显示进度和防重

- **状态 / 优先级：** `current / P0 memory workflow`
- “整理到今天”不能是无上下文的重复 mutation 按钮。提交前必须从现有 Memory 月历/整理 owner 读取
  本次目标日期、待处理或需刷新的日期、来源数量和少量真实样例，让用户先看清整理范围；没有权威样例
  时诚实显示范围尚不可用，不得用静态演示数据补齐。
- 用户确认后只创建或恢复一个由 `mode + targetDate` 标识的权威后台任务。同一范围已经 queued/running
  时，按钮禁用并复用原 `jobId`，连续点击、重开页面或轮询重连都不得产生第二次整理。不同范围不能
  错误复用旧任务。
- 卡片持续投影真实 `phase/currentDate/completed/total/remaining` 或后端现有的等价字段，并在完成时显示
  可追溯收据；失败时显示原因、同一 `jobId` 和明确恢复动作。前端不得用本地计时器伪造百分比，也
  不能因刷新丢掉正在执行的整理状态。
- **用户可见验收：** 打开月度整理先看见本月真实日期样例；快速连续确认只产生一次 mutation；运行中
  能看到阶段和完成量，刷新后恢复同一任务；完成/失败均可核对 job 收据，新的目标日期才允许新任务。
- **原话依据：** “这个要获取到示例，并且展示整理进度，防止用户反复点击导致重复整理”。来源：
  当前任务，2026-08-26。

### UR-141 — Room 伙伴数量按任务可调，并支持运行中持续 steer 与重新分工

- **状态 / 优先级：** `current / P0 Room workflow`
- 新建 Room 不得固定截取四位伙伴。系统根据目标、依赖和可并行性给出建议数量，用户在创建前可在
  **1–8 位**范围内增减并看见将加入的真实伙伴；最终选择必须进入 `agent.rooms.create` 的参与者
  payload，不能只是前端标签或静态预览。只有确实需要协作时才建议多位伙伴，简单任务不为凑数量
  创建空闲行星。
- Room 开始后仍可持续 steer。Facilitator 可以先修订权威 WorkDocument/WorkItem，再携带 revision
  把变化发送给已有伙伴；可以新增或替换伙伴，把未完成工作重新派给新行星；也可以收回 WorkItem
  自己接手。不得静默改写伙伴的原 TaskBrief，也不得把旧 revision 下的结果自动当成新要求已满足。
- steer 到达 `submitted/review` 时不建立新状态机：若它改变当前 WorkItem 的范围或验收标准，复用
  现有 return/revise 操作以“需求已变更”为原因退回，推进 `expectedRevision` 后再提交；旧提交继续
  留在原事件和 WorkDocument 修订历史。若只是独立追加项，当前项仍可按旧 revision 验收，同时用
  现有 create/dependency 建立普通新 WorkItem，Root completion 继续由未清 WorkItem 门阻止。
- “相关还是独立”由 Facilitator/调度 Agent 根据权威需求和文档判断并选择操作，不在后端增加语义
  分类器。选择独立新增时，不相关的 submitted/review WorkItem、验收 Agent 和 revision 完全不变；
  选择相关修订时必须明确目标 `workItemId`。公开事件记录本次路由决定和简短理由，用户可再次 steer
  纠正，但代码只负责现有 ID、revision、权限与状态转换校验。
- 晚到的旧 `accept` 必须复用现有 `expectedRevision` 冲突保护而失败；不得增加旁路 accept、复制审计
  表或专用 steer 总线。界面只投影既有 revision old/new、退回原因、负责人和 WorkDocument 引用，
  文档差异复用已有版本/diff 能力。
- 每次调整都复用已有 Pi steer、Room dispatch/wake、WorkItem 和公开事件 owner，显示谁在何时把哪项
  工作从哪个 revision 调整到哪个 revision、原负责人和新负责人、伙伴 ACK/拒绝/失败以及后续结果。
  不建立第二套调度器，也不因增加伙伴复制 Session 历史或完整 Root 上下文。
- **用户可见验收：** 以建议 4 位创建前改为 2 位、再改为 6 位，实际 Room participants 与界面一致；
  运行中修改一项文档要求后，既能让原伙伴按新 revision 继续，也能另派一位伙伴或由 Facilitator
  接手。旧任务、修订、消息和结果仍可追溯，Room 最终只产生一个 Root 收束结果。
- **原话依据：** “Room 能够持续 steer 吗，大不了他写改好文档把任务分给新行星，或者告诉已有行星
  改动，或者自己接手做”“这个伙伴数量无法调节”。来源：当前任务，2026-08-26。

### UR-142 — Input Studio 必须显式呈现 MLX 与两段输入预测的保存态和生效态

- **状态 / 优先级：** `current / P0 Input Studio regression`
- Input Studio 首屏必须分别显示 **输入拼音时预测**、**上屏后联想**和负责生成的 **MLX 本机模型**，
  不能只把模型参数埋在“本机联想”折叠组，也不能从设置字段清单删除
  `interaction.composition.showPrediction`、`interaction.composition.showOnlyRime` 或
  `interaction.postCommit.showPendingStatus`。
- 保存设置与运行时生效值必须并列诚实呈现。若保存值要求 AI 候选，但当前 profile/safety clamp 实际
  运行在 Rime-only，界面显示“已保存但未生效”、公开原因和既有重新载入/应用入口；不得把保存成功
  说成 Runtime 已开启。Rime 仍负责拼音解析和原生候选，AI 候选保持来源可辨且不得静默重排 Rime。
- MLX 状态只使用现有模型状态与运行概览：显示公开 provider 名称、模型显示名、loaded/health 和配置
  是否一致；不得泄露本机绝对路径，也不得用静态“MLX 可用”卡片掩盖探测失败。
- **用户可见验收：** MLX 运行且模型已加载时，Input Studio 首屏可直接看见真实模型和健康状态；三项
  输入预测控制可独立检查与修改。制造 saved/runtime mismatch 后，页面准确显示 clamp，并在重新应用后
  更新为同一生效状态；窄窗无文字重叠或被裁掉的操作。
- **原话依据：** “mlx和那个输入法预测消失了”。来源：当前任务，2026-08-26。

### UR-143 — 最终回复出现后，Session 投影必须立即收敛到真实终态

- **状态 / 优先级：** `current / P0 runtime projection`
- Assistant 最终回复、Pi terminal 事件和 Session durable snapshot 共同构成终态证据；前端不得仅因旧的
  optimistic turn、遗漏的 SSE 帧、未清理的本地计时器或轨迹查询仍在进行，就继续显示“思考中”、
  Stop 按钮或 active 行星。最终回复已经 durable 且 Session 快照为 idle/completed 时，界面必须移除
  运行 indicator，并允许立即发送下一条消息。
- terminal SSE 暂时缺失时，复用既有 Session 快照/事件游标做幂等重新同步；不得靠固定超时把真实
  运行误判为完成，也不得让调试轨迹、Memory/Knowledge 投影或附件预览查询阻塞主对话终态。
- **用户可见验收：** 覆盖正常 terminal、terminal 帧丢失后快照恢复、Provider 仅返回最终文本、Stop/
  cancel、重开已有 Session 五条路径。每条路径中最终文本、Composer 可用态、Stop 与运行 indicator
  必须一致；连续发送下一条消息不会收到“Session 操作没有完成”或继续沿用上一轮计时。
- **原话依据：** “end没有结束，输出完了还在思考”“明显不对，明明就已经输出完了，还在显示思考中。”
  来源：当前任务，2026-08-26。

### UR-144 — Memory Recall 是独立、默认关闭、由 Agent 显式决策调用的能力

- **状态 / 优先级：** `current / P0 memory capability correction`
- Composer/能力面提供独立的 Memory Recall 图标、开关和设置入口。新 Session 默认不自动预取或注入
  Memory；开关关闭时不向 Agent 暴露可执行召回，也不生成伪收据。用户开启后，Agent 根据当前问题、
  最近对话、项目上下文和压缩摘要决定是否显式调用既有 Memory Tool，而不是每轮无条件自动召回。
- 设置复用现有能力策略和 Memory owner，至少允许配置每个 compaction cycle 的召回上限，默认上限为
  **1 次**；同一周期达到上限后 Agent 能看到预算已用尽，不能绕过 Tool 合同重复注入。新一轮压缩完成
  后预算随权威 compaction identity 复位，重启/恢复仍保持一致。后续更多预算项只有在真实 owner 字段
  存在时才展示，不建立第二套 Memory 配置数据库。
- 对话中的 Memory 收据默认折叠并使用轻量行式呈现；展开后才显示命中数、耗时、来源和 trace 跳转。
  “默认关闭”同时约束能力默认值与收据披露默认态，但不取消 `UR-133`/`UR-134` 的受治理 RAG、来源和
  双向追溯要求。本条取代 `UR-133` 中可被理解为“能力开启即自动 recall”的部分。
- **用户可见验收：** 新建 Session 不发生 Memory Tool 调用；开启后由 Agent 在相关问题上调用一次并
  留下折叠收据；同一 compaction cycle 的第二次调用被预算合同诚实拒绝或不选择，下一 cycle 可再次
  调用；关闭后下一轮不再装配 Memory 来源。
- **原话依据：** “记忆召回很丑，默认关闭，由agent调用判断”“记忆召回直接单独开关，设置符号logo，
  因为这个是本项目亮点，里面设置，比如一轮压缩周期内只能一次等自定义”。来源：当前任务，
  2026-08-26。

### UR-145 — Context Usage 必须展示可解释的分层 token 构成

- **状态 / 优先级：** `current / P0 observability correction`
- Context Usage 不得在已有上下文装配节点时只显示一条总量并写“分层内容尚不可用”。面板至少区分
  system prompt、项目/角色/Skill、用户消息、Agent 消息、Tool 定义、Tool 结果、Memory/Knowledge、
  compaction summary 与无法归属的 remainder；每层显示数值、占比和数据性质。
- Runtime/Provider 给出逐层 token 时显示精确值；只有 trace node `tokenEstimate` 时显示 `≈` 与“估算”；
  只有字符数时可用统一 tokenizer/估算器生成近似值并明确口径，不能把字符数伪装成 token。总 usage
  与已知层不相等时保留“其他/未归属”，而不是强行配平或把全部归为“当前对话与工具结果”。
- 面板可比当前适度放大，但必须保持可读层级和稳定滚动，不遮挡 Composer 的发送、Stop 或下一轮操作。
- **用户可见验收：** 在含 system prompt、工具、Memory/RAG 和 compaction 的真实 Session 中，能看到
  类似“系统提示词 ≈2K”“压缩摘要 ≈29K”的分层条目及口径；关闭某层或新一轮压缩后数值随权威轨迹
  更新，缺失层诚实标为未知而不是整面不可用。
- **原话依据：** “这个也没显示具体的，多少多少k”“比如系统提示词2k，压缩29k”“为什么不可用”。
  来源：当前任务，2026-08-26。

### UR-146 — Room 可见伙伴统一使用行星身份，退出 Agent 编号与旧角色混用

- **状态 / 优先级：** `current / P0 identity consistency`
- 所有面向用户的 Room Partner 候选、创建预览、运行时间线、协作图、卫星窗、通知和验收列表，以稳定
  行星名作为主要身份；不得再出现 `Agent 1`、`Agent 2`、`Agent 3`、`Agent 4`、随机旧代号或同一伙伴
  在不同页面使用不同名称。内部 Session/participant ID 保持 Runtime 权威，不因展示名迁移而改写。
- “协调、专家、审阅、验收”等是当前责任/WorkItem 的次级标签，不再和行星名拼成另一套角色身份。
  新增至 8 位伙伴时从同一行星命名 owner 分配并持久化，恢复、steer、替换和历史回放保持原 identity。
- **用户可见验收：** 创建 1、4、8 位 Room 并跨 Overview、Agent、Room Focus、协作图和卫星窗核对；
  同一 participant 始终只有一个行星名，旧 `Agent N` 与旧版角色身份全局搜索不再进入生产渲染路径。
- **原话依据：** “全部换成行星”“全局检查混用这种类似问题，比如旧版的成这些，旧版角色这些”。
  来源：当前任务，2026-08-26。

### UR-147 — 模型与推理强度使用不同图标、入口和弹层，任何宽度都不得相撞

- **状态 / 优先级：** `current / P0 interaction correction`
- 本条细化 `UR-135`：模型与推理强度不仅逻辑上独立，也必须在视觉和命中区上独立。模型入口使用模型/
  Provider 身份，推理入口使用明确的 reasoning 图标与强度值；不得共用一个图标、一个箭头、一个
  `aria-controls` 或一个弹层。模型列表不夹带强度选项，强度轨不重复模型名。
- workspace、能力开关、模型、推理和发送控件使用可收缩布局与明确最小宽度；窄窗按既定优先级折叠为
  独立图标/菜单，不能文字重叠、覆盖文件夹图标或产生第二层无意义方框。
- **用户可见验收：** pointer、键盘、320–1440px、125%/200% 字号下分别打开两项，焦点与选择只影响
  各自 owner；截图中模型、推理和 workspace 没有叠字、共享图标或误触。
- **原话依据：** “模型和推理强度还是一个图标”。来源：当前任务，2026-08-26。

### UR-148 — Settings 分别配置 Room 行星与私有卫星的默认模型

- **状态 / 优先级：** `current / P0 model routing settings`
- System Settings 的 Agent/模型页分别提供：**Room 行星（可见 Partner Session）默认模型/推理强度**与
  **私有卫星（Tool Agent/subagent）默认模型/推理强度**。两者读取真实可用模型清单，保存到现有模型
  路由/能力配置 owner；一个字段不得静默同时控制两类 Agent。
- 具体 dispatch 仍可依据 TaskBrief、用户选择或 Facilitator/parent 的明确 override 覆盖默认值；界面
  清楚显示“默认”与“本次覆盖”，不得把模型显示名硬编码进 Room 前端。旧设置迁移时保留当前有效值，
  未配置的一类使用产品默认并明确显示来源。
- **用户可见验收：** 给行星和卫星选择不同模型/强度后创建一个 Room，Partner receipt 与其私有 Tool
  Agent receipt 分别显示对应设置；单次 override 只影响目标 dispatch，重开 Settings 后默认值仍在。
- **原话依据：** “模型设置界面可以设置行星和卫星的模型”。来源：当前任务，2026-08-26。

### UR-149 — Room 与 Session 共用一套对话视觉，协作关系图必须清晰可读

- **状态 / 优先级：** `current / P0 Room frontend correction`
- Room 的中央工作面以 Session 已确定的对话阅读、Composer、思考/Tool 披露和终态语法为基线；不得
  继续保留另一套紫色控制台、卡片堆叠、整面边框或“窗口里再套多层窗口”的旧风格。Room 特有内容
  只增加行星身份、公开消息、WorkItem/验收与协作入口，不复制 Session 已有控件。
- 伙伴卫星是 Room focus 的渐进披露，不是永远铺满两侧的方框墙。默认优先显示当前负责人、最近活动和
  需要用户/Facilitator 关注的状态；其余伙伴可从协作入口展开。卫星使用与主对话一致的字体、间距、
  hairline 和轻材质，长原始回执、Tool 参数和文档正文默认收起。
- “协作网”必须由真实 participant、WorkItem 和公开 Room 关系生成稳定布局。节点以行星名为主、职责为
  次，文本不互撞、不被节点/边覆盖；负责、交接、复核、子任务使用可区分但克制的线型/方向。关系过多
  时按当前路径/当前 WorkItem 渐进披露或提供聚焦，不把 8 位行星和全部历史边一次塞进窄面板。
- **用户可见验收：** 同一个真实 Room 在宽窗、窄窗和 8 位伙伴三种状态下，中央对话与 Session 风格
  一致；侧边卫星不遮挡主线；协作网节点、职责和关系无叠字/截断，能聚焦当前关系并返回完整视图；
  reduced motion 与键盘路径保持可用。
- **原话依据：** “room模式前端未改，改成和sesison一样的。不要两种风格和这种方框。协作网是乱的”。
  来源：当前任务，2026-08-26。

### UR-150 — Showcase 能力必须从当前仓库与可核验证据中选择

- **状态 / 优先级：** `current / P1 final delivery`
- 最终展示项由负责收尾的 Agent 读取当前仓库、运行态与新鲜检查后自主选择，不预设为某个旧功能或
  历史截图。每个入选能力都要绑定 owning source、真实数据或公开 fixture、证据等级、当前 revision
  与仍未验证的边界；README、mock、截图或模型描述本身不能证明功能完成。
- 能力选择优先展示 PAW 的产品中心：一个可恢复的 Agent Session、一个由普通 Partner Session 组成的
  Room、受治理的 Tool/Memory/Knowledge 证据，以及同一 PAWOS 工作面中的可见结果。可选输入、语音、
  Browser 适配器只有在取得相应新鲜 Runtime/foreground 证据后才能升级为主宣传能力。
- **用户可见验收：** Showcase 文档说明候选、取舍理由、证据路径和限制；最终 README 中的每一项
  宣传能力都能反向定位到该记录和可复现检查。
- **原话依据：** “读当前仓库 → 自己找出最值得展示的能力”。来源：当前任务，2026-08-27。

## 继续阅读 / 编辑

- 下一份：[UR-151–UR-180](PAWOS_REQUIREMENTS_151_180.md)
- 原话与来源覆盖：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
