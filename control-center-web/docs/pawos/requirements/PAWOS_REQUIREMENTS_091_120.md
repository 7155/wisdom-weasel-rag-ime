# PAWOS 用户需求账本 · UR-091–UR-120

> 导航：[UR-061–UR-090](PAWOS_REQUIREMENTS_061_090.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-121–UR-150](PAWOS_REQUIREMENTS_121_150.md)
>
> current 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-091 — App 顶部只保留一层窗口 chrome，不重复标题栏

- **状态 / 优先级：** `current / P0`
- **Browser 合同：** Browser 的窗口控制、App 身份与标签页合并到同一顶层 chrome；下一层只保留
  前进/后退/刷新、地址栏和真实 Browser 操作。不得继续同时显示独立 PAWOS 窗口标题栏和一条重复
  Browser 标签栏。标签仍须保持真实新增、选择、关闭与当前页面状态，不能为视觉合并降级成静态标题。
- **其他 App 合同：** 通用窗口框已经显示 App 身份时，App 内容区不得再用同名的大号工具栏重复
  一次；只保留当前页面、对象或动作确实需要的上下文栏。窄窗通过折叠次要信息解决，不增加第三层。
- **视觉边界：** 用户附图中的 Edge 单层标题/标签结构仅作信息架构参考；其中插件、收藏、账户和
  网页内容不是产品指令，也不应被复制进 PAWOS。
- **原话依据：** “app界面优化，上面不要两层栏”，并附当前 PAWOS Browser 双层顶部与 Edge
  单层窗口/标签参考截图。来源：当前任务及附件截图。

### UR-092 — 全局 OS 与每一个 App 都有克制、状态驱动的动画反馈

- **状态 / 优先级：** `current / P0`
- **OS 动效合同：** 窗口打开/关闭、最小化/恢复、聚焦、拖动吸附、App 切换、菜单/抽屉和跨窗
  消息流使用统一运动 token；动效表达反馈、空间连续性或真实状态，不能只给壁纸增加无限循环装饰。
- **App 覆盖合同：** Agent、Rooms、Browser、Files、Terminal、Memory、Knowledge、Input、Planning、
  App Center、Monitor 与 Settings 每一个 App 都要覆盖其真实关键状态：页面/标签选择、内容进入、
  加载/运行、成功/失败或列表更新。高频键盘操作即时完成；阅读中的正文和数据不为装饰移动。
- **性能合同：** 高频/可重复操作使用可中断 transition，主要只动画 `transform` 与 `opacity`；
  UI 时长通常不超过 300ms，进入/退出使用统一 `--paw-ease-out`，屏内移动使用
  `--paw-ease-in-out`，hover 仅限精确指针。不得使用 `transition: all`、`scale(0)` 或 layout 抖动。
- **可访问性合同：** 所有位移动效同时提供 `prefers-reduced-motion` 的轻柔淡入或即时状态版本；
  reduced motion 仍保留必要的状态反馈，但去掉持续位移、弹跳和背景漂移。
- **原话依据：** “全局os的动画特效缺失”“每一个app都要改”。来源：当前任务。

### UR-093 — Browser 采用现代 ChromeOS/Chromium 质感，不保留旧式管理后台外观

- **状态 / 优先级：** `current / P0`
- **视觉合同：** Browser chrome、标签、地址栏、菜单、History 与 Settings 使用一套现代、轻量的
  浏览器 surface 层级；以柔和圆角、克制描边、清晰 active/hover/pressed 状态和适量背景材质建立
  层级，删除大面积脏灰、密集硬边框、默认表单样式与“每段内容一个矩形框”的旧式后台观感。
- **动效合同：** 标签新增/选择/关闭、菜单出现、设置/历史切换、页面加载与 Agent 控制状态提供
  ChromeOS 式快速连续反馈；高频导航不等待长动画，网页正文不被装饰性运动干扰，reduced motion
  下退化为淡入或即时状态。
- **功能优先合同：** 视觉重做不得牺牲 `UR-086`/`UR-088` 的真实 History、Settings、菜单动作、
  多标签和 EgoLite exact-target；网页 viewport 仍是最大、最稳定的主体。
- **原话依据：** “chrome os都有很多动效。你看看浏览器界面，还像上世纪的前端”。来源：当前任务。

### UR-094 — 卫星窗口出现时进入协作聚焦态并强化真实信息流

- **状态 / 优先级：** `current / P0`
- **聚焦合同：** Room 或 Session 调出伙伴、subagent、Flow、治理、文件等卫星窗口后，桌面壁纸与
  无关装饰应适度降亮度/饱和度，主工作窗、卫星窗和必要上下文仍保持清晰；关闭最后一个卫星窗后
  平滑恢复。不能通过给全部页面加不透明遮罩而损失可读性或点击能力。
- **窗口合同：** 卫星窗进入、获得活动状态、收到新信息和完成任务时分别提供短促可中断的空间进入、
  边缘强调与一次性到达反馈；静止后恢复稳定，不能依赖永久发光/弹跳来冒充正在运行。
- **信息流合同：** 强化的光路/消息包必须来自真实 Room FlowPacket、Session subagent 事件或
  ContextRef/receipt，方向对应实际源窗和目标窗；背景弱化与窗口特效服务于看清流转，而不遮挡正文。
- **可访问性合同：** reduced motion 下去掉消息包位移和窗口位移，只保留背景弱化、边缘/颜色状态
  和一次性淡入。
- **原话依据：** “卫星窗口调出后，就得弱化背景，强化信息流转，窗口加特效等才能看出”。来源：当前任务。

### UR-095 — 每个既有 Feature 都要完成真正的 App 内页适配，不能只套 PAWOS 窗口

- **状态 / 优先级：** `current / P0`
- **适配合同：** 将旧 Feature 整页挂入 PAWOS window 只能算数据接通，不能算 App 完成。Project、
  Memory、Knowledge、Input、Planning、App Center、Monitor、Settings、Files 与 Terminal 必须逐一移除
  重复 App 名称、第二套侧栏/顶栏、旧网页大标题、调试说明和相互争抢空间的多层布局，只保留真实对象、
  页面级导航、关键动作、状态与恢复。
- **可读性合同：** 语义字体角色必须真实作用到每个 Feature 内部，不能被后加载旧 CSS 的 7–12px
  硬编码覆盖；导航、表格、卡片、空状态、表单和详情在安装态前台都清晰可读。桌面宽屏利用空间但不
  堆满面板，窄窗切换主次而不是裁切按钮或把字体继续缩小。
- **产品质感合同：** 每个 App 都要围绕自身核心任务重排信息架构、surface、交互和状态动效，达到
  可独立使用的真正 App 前端；不得用统一灰框、通用卡片墙或仅换颜色来伪造“惊艳”。
- **验收合同：** Knowledge 等复杂 App 必须在安装态逐页点击资料/材料/检索/图谱/处理/设置并验证
  无重复 shell、无横向裁切、真实操作仍可用；Memory 等空态也要有清晰下一步而不是大面积空白。
- **原话依据：** “当前很多还没做app适配”“字体也没调整，看都看不清楚。每一个都要细细打磨前端。
  惊艳”“要拿出做真正app前端的劲”。来源：当前任务及 Knowledge/Memory 附件截图。

### UR-096 — 主 Agent/Room 聚焦对话，卫星窗口直接呈现其真实关注内容

- **状态 / 优先级：** `current / P0`
- **主窗合同：** Agent/Room 主窗口第一视觉层是当前对话、消息状态与 Composer；伙伴、治理、任务流、
  进展、文件和 trace 只在用户调出或真实运行需要时进入卫星，不用多排导航/状态卡挤压对话。
- **卫星合同：** 通用窗口标题栏已经标识对象后，卫星内容区不得再重复 `ROOM`、Room 名、`协作中`
  和大块 generic hero。伙伴卫星直接从真实对话/工具/思考活动开始；任务流、治理、进展、消息流等
  面板直接从对应真实内容与当前动作开始，并使用适合该内容的尺寸、滚动和密度。
- **编排合同：** 初始卫星布局围绕主窗形成可辨识层级，不默认大面积互相遮挡；活动源/目标窗口与
  FlowPacket 视觉关联，非活动卫星稳定弱化但仍可读、可拖动、可聚焦。
- **原话依据：** “卫星你看看，太难看了”“对话关注的内容你都没搞清楚”，并附主窗被多排控制和
  状态内容占据、卫星重复大 header 且相互遮挡的截图。来源：当前任务及附件截图。

### UR-097 — 卫星是一种铺满桌面的 Room 聚焦模式，不是普通多窗口集合

- **状态 / 优先级：** `current / P0`
- **模式合同：** 用户从 Room 调出卫星协作时进入明确的 Room Focus Mode。当前 Room 的主窗、伙伴、
  subagent、任务流、进展、治理、文件或上下文视图共同组成一块专用协作空间；模式具有可识别的进入、
  当前 Room 身份和退出动作，不依赖用户手动把一堆普通窗口摆好。
- **布局合同：** 主对话占据中心最大区域，辅助信息按左右信息轨或适合内容的分区铺满其余可用桌面；
  初始布局无大面积重叠和无意义空洞，内容区随窗口/屏幕尺寸重新分配。信息轨可聚焦、滚动，必要时
  调整，但模式布局不能退化回截图中的随意层叠窗口。
- **专注合同：** 模式内只突出当前 Room 相关窗口与真实流转；壁纸、桌面图标、Dock、其他 App 和
  非当前 Room 窗口退场或显著弱化且不可误触。退出后恢复进入前的普通桌面窗口状态与内容，不销毁
  Session/Room 权威数据。
- **动效合同：** 进入/退出以 200–300ms 的可中断空间过渡表达从普通桌面到 Room 协作画布；真实
  FlowPacket/ContextRef/receipt 在专用布局中拥有清楚方向。reduced motion 使用淡入/显隐与静态边缘。
- **原话依据：** “卫星不应该只普通多窗口，而是一种模式，这种模式信息排布占满并且专注当前room”。
  来源：当前任务。

### UR-098 — Pi 调用后台 Shell 或 Browser Tool 时提供同一真实执行视图

- **状态 / 优先级：** `partially superseded by UR-130 / P0`
- **Shell 合同：** Pi Session/Room 启动后台 `shell`、`bash` 或 process-terminal 运行时，PAWOS 为同一
  真实 run 保留可按需打开的 Terminal/Process 投影，持续关联命令、cwd、stdout/stderr、运行、退出码、
  失败或停止状态；不能用静态摘要冒充控制台，也不能启动第二份命令。后台运行的默认显隐与焦点合同
  由 UR-130 取代本条原有的“自动弹出”要求。
- **Browser 合同：** Pi 调用 Browser/EgoLite Tool 时，PAWOS 自动打开或聚焦 Browser App 中该
  exact `targetId` 对应的同一可见标签，并显示 Agent 轨迹；不得另开 screenshot viewer、重复 Browser
  或只在 trace 写一行而不显示页面。
- **身份合同：** 同一 shell run/terminalId 与 Browser target 复用稳定窗口/标签，后续事件更新原投影，
  不按每个 Tool event 重复创建。Room Focus Mode 内这些视图进入当前 Room 的信息轨；普通 Session 中
  作为不抢 Composer 焦点的可见卫星/App 窗口。
- **原话依据：** “然后shell，就是pi调用后台shell后台bash的时候，就可以弹出查看。浏览器也是调用
  的时候就可以弹出”。来源：当前任务。

### UR-099 — Terminal 优先接入本机 Ghostty，未安装时回退系统默认终端

- **状态 / 优先级：** `superseded by UR-105`
- **更正：** 本节保留为历史原话收据；当前实现与验收不得继续执行下述 Ghostty/System Terminal
  外部宿主合同，权威要求见 UR-105。
- **宿主选择合同：** PAWOS 在 macOS 上先探测已安装的 Ghostty；存在时，Terminal App 与 Pi
  shell/bash/process-terminal 的可见终端表面直接调起、聚焦并复用 Ghostty，不再额外制作一套
  “像 Ghostty”的模拟皮肤。本机已确认安装 `<system-apps>/Ghostty.app`，因此当前安装态必须走
  Ghostty 路径；只有 Ghostty 未安装或宿主明确不可用时，才回退 macOS 系统默认终端。
- **运行身份合同：** Ghostty 负责真实终端表面与键盘/渲染体验；PAW 继续持有 Pi run、terminalId、
  cwd、Stop/cancel、完成状态和审计。打开或聚焦可见终端不得重复执行已经启动的命令；同一 run 的
  后续输出与状态必须回到同一可恢复终端身份。
- **回退合同：** 非 macOS、Ghostty 不可用或宿主桥失败时，现有 PAW 真实 PTY/内嵌终端可作为
  同一运行合同的可用回退；回退必须显示实际使用的终端提供者，不得静默假装已经接入 Ghostty。
- **原话依据：** “终端优先接入ghost”“如果本机已有 Ghostty/源码，就直接复用现成能力，安装了
  就这个，没安装就系统默认。本机安装了的”。来源：当前任务。

### UR-100 — 全量重制 PAWOS App 图标系统并与当前视觉语言统一

- **状态 / 优先级：** `current / P0`
- **身份图标合同：** Project、Agent、Memory、Knowledge、Input、App Center、Monitor、Settings、
  Files、Browser 与 Terminal 不再直接使用通用 Lucide 图标塞入白色方块。每个 App 使用原创、可辨识
  的 PAWOS 身份图标，并在桌面、Dock、Launchpad、窗口标题栏和 App 内身份位复用同一资产与名称。
- **已批准源资产：** 用户提供的 `pawos-brand-icons-v1/icon-wall.html` 中的
  `app-agent`、`app-room`、`app-browser`、`app-terminal`、`app-files`、`app-workbench`、
  `app-memory`、`app-knowledge`、`app-input`、`app-appcenter`、`app-monitor`、`app-settings`
  SVG 是本轮生产迁移源，不是只供再创作的情绪板。生产 `PawAppIcon` 必须直接迁移其已批准的
  色彩、轮廓和内部几何，并在 16/24/32/48px 复用同一确定性资产；不得继续另画一套相似但不同的
  Sol、轨道、卡片或通用线图标。只允许为当前冷白系统做光学尺寸、对比度、无障碍和材质减法，
  不能改变各 App 的识别语义。
- **视觉合同：** 图标以冷白空间中的少量高质量彩色坐标承担 App 身份；饱和彩色只停留在身份图标，
  不扩散成大面积容器底色。不得复制游戏、Chrome、Ghostty 或其他产品商标。
- **系统合同：** App 身份图标与操作图标分层：全彩/复合几何只用于 App 身份；关闭、搜索、返回、
  Stop、刷新等动作继续使用一套克制、单色、语义稳定的操作符号，不能因重制而降低可理解性。
- **交付合同：** 图标使用确定性的代码原生 SVG/矢量资产，支持 `currentColor`/主题变量、键盘焦点、
  high-contrast 与 reduced-motion；不得用模糊位图或生成式缩略图代替小尺寸系统资产。
- **原话依据：** “图标也得全部重新制作，因为和当前风格完全不符合”“图表icon为什么不直接把我
  之前发的html示例迁移过来”。来源：当前任务及附件截图，2026-08-26。

### UR-101 — 使用 Impeccable / Frontend Design / Taste 作为逐 App 设计打磨参考

- **状态 / 优先级：** `current / P0 quality bar`
- **方法合同：** 逐 App 重设计以 Impeccable 为主线，统一检查视觉方向、信息架构、布局、字体、交互、
  动效、完整状态与真实浏览器验证；以 Anthropic Frontend Design 的 anti-slop 方法压掉通用 SaaS
  模板感；以 Taste Skill 提高构图差异性与产品辨识度。
- **产品适配合同：** PAWOS 是高密度桌面产品，不照搬营销落地页的 AIDA、巨型 Hero、滚动劫持、
  无限 marquee 或无关 GSAP。只吸收适用于桌面 App 的字体节奏、非模板构图、反馈、状态迁移、
  reduced-motion、对比度和逐页 pre-flight；真实数据、快捷操作与长期可读性优先。
- **验收合同：** 最终集中验收除类型、测试和构建外，必须逐 App 在真实安装态检查首屏重点、宽窄窗、
  loading/empty/error/success、菜单和直接操作、字体可读性、图标一致性、动效目的与减弱动态效果。
- **原话依据：** “你设计ui的时候可以参考”并推荐 Impeccable、Anthropic Frontend Design 与
  Taste Skill。来源：当前任务。

### UR-102 — 九个核心工作 App 必须逐个设计并单独通过审美检查

- **状态 / 优先级：** `current / P0 quality gate`
- **逐项合同：** Project、Agent、Memory、Knowledge、Input、App Center、Monitor、Settings、Files
  各自拥有独立的核心任务、首屏重点、信息层级、页面导航、宽窄窗重排、loading/empty/error/success、
  交互反馈和视觉节奏；不能用“Native App 已统一适配”代替逐项设计凭据。
- **审美合同：** 每个 App 单独检查字体可读性、信息密度、对齐/间距、空白使用、主次色、身份图标、
  选中/焦点/禁用状态、动效目的、旧网页壳/重复标题/通用卡片墙残留，以及 1280/800/560px 下的
  内容裁切和操作可达性。审美检查必须结合真实数据状态与浏览器/安装态截图，不只扫 CSS。
- **边界合同：** Browser 与 Terminal 继续受完整 App 验收清单约束；本条是对用户明确列出的九个
  工作 App 增加逐项审美签收，不是降低其余 App 的完成标准。
- **原话依据：** 用户逐项列出 Project、Agent、Memory、Knowledge、Input、App Center、Monitor、
  Settings、Files，并要求“需要逐个好好设计，审美检查”。来源：当前任务。

### UR-103 — 废弃折角工程牌套图，直接采用已批准全彩身份图标墙

- **状态 / 优先级：** `current / P0 correction`
- **废弃合同：** 把各 App 细线符号塞入折角工程牌、底轨和信号条的旧方案被明确拒绝，不再通过
  改色、加粗或微调比例抢救。该禁令针对旧折角工程牌，不得误伤 `icon-wall.html` 已批准的统一
  圆角色砖平台。
- **当前图标合同：** 直接采用 `UR-100` 指定图标墙：统一圆角色砖提供系统级外形，各 App 通过
  独立颜色和白色/信号色内部几何形成身份。Agent 使用对话连接语义而非脸或头像；Room 是 Agent
  内的协作身份，不成为第十二个顶层 App。16/24/32/48px 都要直接可辨识，动作图标仍与身份图标分层。
- **视觉验收合同：** 接入产品前必须先制作 11 App x 4 尺寸的真实图标墙，在桌面纸面与 Dock
  背景上截图并至少完成一轮肉眼迭代；DOM/单测只能防止身份路径回退，不能替代审美签收。
- **原话依据：** “我的天呐，图标还能丑到这种地步”“太丑了，我都想不到怎么能画出这么丑的图标”。
  来源：当前任务。

### UR-104 — 美感优先的逐 App 色彩与视觉方向，不受 Composition 8 绑架

- **状态 / 优先级：** `current / P0 correction`
- **美感合同：** 整个 PAWOS 前端以清楚、愉悦、精致和长期耐看为首要视觉目标；不得把“符合某张
  壁纸”“系统统一”或几何概念正确当成审美完成。Composition 8 只是一张可替换桌面背景，不再
  约束 App 布局、图标轮廓、配色、材质或动效语言。
- **逐 App 色彩合同：** Project、Agent、Memory、Knowledge、Input、App Center、Monitor、Settings、
  Files、Browser 与 Terminal 各自建立有辨识度的主色、辅助色、内容材质和语义状态色；保留可读的
  中性色与跨 App 状态一致性，但不得继续退化为“大面积灰白 + 同一信号青”。颜色必须参与信息层级、
  选中、反馈和对象识别，而不是给现有框线模板换皮。
- **图标修正合同：** UR-103 的独立轮廓继续有效，但“来自 Composition 8”不再是设计理由。接触表
  必须优先证明图标本身漂亮、饱满、清楚且像真正的 App 身份；可以使用克制的双色、渐变、柔和材质
  与光学深度，只要小尺寸仍清晰、各 App 不共享同一容器且不复制其他品牌。
- **验收合同：** 最终逐 App 截图需要单独评价色彩层级、材质、对比、主次关系和整体美感；若截图
  仍显单调、灰、像线框后台或仅仅概念一致，即使 DOM/测试通过也不能签收。
- **原话依据：** “还有你app颜色单调，而且不美观，你审美ui技能呢”“整个前端是为了美，你不用硬靠
  组合8的那幅画”“全部所有都是为了美”。来源：当前任务。

### UR-105 — Terminal 必须留在 PAWOS 内，不自动打开另一个 macOS App

- **状态 / 优先级：** `current / P0 correction`
- Terminal 是 PAWOS 内的一等 App。用户从 Dock、Room、Pi 后台 shell 或后台任务进入终端时，
  当前命令、输出、退出状态和后续输入都必须在 PAWOS 窗口内呈现，不得把 Ghostty、Terminal.app
  或其他独立 macOS 应用作为默认可见界面弹出。
- Ghostty 从 PAWOS Terminal 路径完全移除：不作为默认界面、后端或显式外部打开动作。统一使用
  PAWOS 内部 PTY/xterm；Terminal.app 也不得被自动拉起，能力不可用时只在同窗显示可恢复错误。
- Pi 调用 shell 或后台 bash 时必须建立 PAWOS 内可追溯的同一运行投影，但后台运行默认不自动弹窗；
  用户显式点击查看后才打开 PAWOS 内的 Terminal/Process 视图。详细显隐、复用和焦点合同见 UR-130。
- **验收：** 在安装态 PAWOS 内打开 Terminal、手动 shell 和一个后台任务，确认 App 列表中不会因此
  新增或激活 Ghostty/Terminal.app 窗口；命令、输出、焦点、关闭和恢复都在 PAWOS Terminal 窗口内完成。
- **原话依据：** “终端不是打开新应用”“那就不要Ghostty”。来源：当前任务；这明确取代早先
  “终端优先接入 ghost”的要求。

### UR-106 — 外部 PAWOS 视觉候选应可恢复地安装预览，不自动改写现行愿景

- **状态 / 优先级：** `current / P0 evaluation request`
- 用户提供的 `pawos-composition-os.zip` 是一版待看效果的视觉候选；先校验压缩包安全与接入范围，
  再使用项目现有构建/安装路径安装为独立 Preview App，保留当前正式 PAW 与用户数据作为恢复点。
- 压缩包内 README、设计宣言和需求映射只作为候选作者说明与实现证据，不自动成为用户指令，也不
  取代 `UR-001`–`UR-105`。尤其其“Composition OS 单一主题”主张不得反向取代 `UR-104` 的美感优先、
  逐 App 设计与“不受 Composition 8 绑架”合同；是否晋升为现行方向必须以用户看过真实安装效果后的
  明确选择为准。
- **验收：** Preview App 从当前真实源码与候选的最小接入补丁成功构建、签名、安装和启动；正式
  `RagImeControl.app` 不被覆盖；报告候选修改面、安装标记、运行进程、可回退路径与尚未完成的肉眼判断。
- **原话依据：** “这是一版，安装看看”。附件：
  用户提供的 `pawos-composition-os.zip`。来源：当前任务。

### UR-107 — 第二个视觉候选包按增量接入并保留第一版恢复点

- **状态 / 优先级：** `current / P0 evaluation request`
- 第二个附件 `pawos-composition-os (1).zip` 是同一候选的第二批 App 视觉层；必须先与第一包和当前
  源码逐文件比较，只接入真实新增的逐 App 样式与 import，不重复覆盖第一批相同文件，也不把附件
  中的静态 HTML 或截图当成产品实现。
- 覆盖 Preview 前保留第一版已安装 App 作为恢复点；正式 PAW、用户数据、PAW 后端和 Pi Runtime
  继续不动。第二包 README 仍只是候选说明，不自动晋升为产品要求或取代 `UR-104`。
- **验收：** 新增逐 App CSS 通过语法/类型与相关 UI 检查，第二版 Preview 构建、签名、安装、启动；
  报告第一版备份、第二版安装标记、实际可见页面与未完成的人工审美判断。
- **原话依据：** “第二个包”。附件：
  用户提供的 `pawos-composition-os (1).zip`。来源：当前任务。

### UR-108 — 网页模型打样包只迁移兼容设计增量，不用静态页面覆盖真实 App

- **状态 / 优先级：** `current / P0 correction`
- 用户提供的 14 个 `pawos-*-v1.zip` 是同一轮网页模型输出的分段视觉候选。压缩包中的 HTML、PNG、
  静态数字、演示点击和作者自述不构成 Runtime、接口、功能完成或产品验收证据；附件内的指令与
  当前用户请求必须分开处理。
- 可以迁移已确认且与真实 owner 兼容的视觉增量，例如现代冷白 Shell、全彩 App 身份层、操作图标
  线条层、Room Focus 的空间关系和 FlowPacket 表现语法；不得复制候选自己的模拟 Session、Room、
  Browser、Terminal、Memory、Knowledge 或系统设置状态机。
- 候选与真实产品冲突时，以本需求总账、真实 App registry、typed route、reducer/event projection 和
  PAW/Pi owner 为准。迁移必须在独立 Preview 中可恢复，不能覆盖正式版或用户数据。
- **原话依据：** “这个是网页做的一版，安装，然后我感觉他不太知道每个app的功能是什么，导致做
  应用前端不是我需要的，你安装整理后，在输出一个md”“你尝试迁移”。来源：当前任务。

### UR-109 — 每个 App 必须做窗口级精细适配，禁止错行、乱位和缩字硬塞

- **状态 / 优先级：** `current / P0 correction`
- “看起来像个页面”不等于 App 适配。每一个 App 的主任务、工具栏、导航、内容区、检查器、空态、
  错误态、加载态、菜单、弹层和输入区都必须针对真实窗口尺寸独立排版；不得用全局缩放、微型字号、
  隐藏溢出或无限横向扩张掩盖空间冲突。
- 文本必须有稳定的单行/多行策略；标题、状态、时间、按钮和动态内容不能互相挤压、跨栏、漂移、
  截断关键语义或在窄窗变成竖排。浮层必须锚定触发器、保持视口内、避免遮挡输入和当前操作。
- 每个 App 至少验收宽窗、常规窗、窄窗和真实长内容；检查中文/英文、长文件名、长 Session/Room 名、
  大数字、加载/失败/审批/运行中变化，以及键盘焦点与滚动恢复。正文可读性优先，信息密度由布局、
  折叠和渐进披露承担，不靠缩小字体。
- **验收合同：** 源码/DOM 检查之外，必须在安装态逐页截图和交互检查；任何明显错行、乱位、遮挡、
  双顶栏、异常空白或不可读字号都使对应 App 视觉验收失败。
- **原话依据：** “他当前问题就是很不精致，错行，乱位”“字体也没调整，看都看不清楚。每一个都要
  细细打磨前端。惊艳”“当前很多还没做app适配”。来源：当前任务。

### UR-110 — 设计必须从真实功能、信息架构和状态矩阵长出来

- **状态 / 优先级：** `current / P0 correction`
- 不再执行“先定统一皮肤，再把所有 App 塞进去”的流程。每个 App 动手前先明确三项合同：用户任务、
  数据/动作 authority、可验收状态；再依次完成真实 IA、状态矩阵、窗口构图、高保真和安装态验收。
- Agent 对话是系统主要工作入口，Room 复用 Agent 的真实时间线/渲染器与 Pi projection；其他 App
  允许拥有独立构图、识别色、密度与交互节奏，但共享可读性、语义状态、输入反馈和 OS chrome 规则。
- 设计数据只能使用真实 reducer、typed routes、事件形状与可达 mutation。若后端能力尚未接通，
  界面显示明确空态/不可用/恢复路径，不得为了画面完整编造资料、统计、历史、审批或运行结果。
- **原话依据：** “需求没对齐”“我感觉他不太知道每个app的功能是什么，导致做应用前端不是我需要的”。
  用户要求同时参考其提供的完整对话；其中“风格不是贴上去”“三合同 → IA → 状态矩阵 → 构图 →
  高保真 → 验收矩阵”和“真实数据形状”仅在与当前原话和总账一致的范围内收录，不把模型回复当成
  新用户指令。来源：当前任务与附件 `pasted-text.txt`。

### UR-111 — 产品只有 11 个顶层 App，Room 是 Agent 内的协作模式

- **状态 / 优先级：** `current / P0 correction`
- 顶层 registry 固定为 11 个：Project Workbench、Agent、Memory、Knowledge、Input Studio、App Center、
  System Monitor、System Settings、Files、Browser、Terminal。当前候选图标墙和对话中出现的“12 App”
  是功能理解错误，不得写回产品 registry、Launchpad、Dock 或模型 handoff。
- Room 属于 Agent 的会话/协作路径，是可进入全屏占领态的 Room Focus Mode；它可以有模式标志、
  窗口身份与参与者卫星，但没有独立顶层 App、独立模拟 store 或脱离 Agent/Pi 的消息渲染器。
- **原话依据：** 用户多次要求“Agent：对话优先、会话/Room”“卫星不应该只普通多窗口，而是一种模式，
  这种模式信息排布占满并且专注当前room”。当前真实 App registry 作为可验证机械事实。来源：当前任务。

### UR-112 — 下一轮网页模型 handoff 必须以愿景和真实前端接口为中心

- **状态 / 优先级：** `current / P0 handoff`
- 在本轮兼容迁移、检查和 Preview 安装后，输出一个可单独上传的 Markdown。它必须先写用户愿景、
  当前纠偏和不可退化规则，再写系统边界、11 App 真实职责、页面/工作流、读取与 mutation 接口、事件、
  owner、状态矩阵、候选包可用部分与偏差，最后给逐 App 设计/实现/验收顺序。
- 文档必须明确指出当前网页候选“精致度不足、错行乱位、功能/需求没对齐”的失败原因，禁止下一模型
  只改配色、圆角、阴影或静态截图。若只能上传一个文件，该 Markdown 应足以让模型先理解功能再改前端；
  大体量前端代码包可以作为第二附件，不代替本说明。
- **原话依据：** “根据我发的对话，更新需求和接下来给他的md”“然后改好一版我又然他改”。来源：当前任务。

### UR-113 — 静态截图 QA 不等于真实产品验收

- **状态 / 优先级：** `current / P0 correction`
- 候选对话中“逐张 QA 通过”“全部完成”只说明作者检查了静态打样；不能证明真实路由、真实数据、
  mutation、SSE、Browser target、PTY、窗口 focus/resize、窄窗适配或安装态交互已完成。
- 每个 App 的最终回执必须分开报告：视觉参考是否迁移、源代码是否接通、测试/构建是否通过、Preview
  是否安装、前台真实页是否验收。任何未亲自验证的层级保持 `unverified`，不能被一张好看的截图关闭。
- **原话依据：** “他可能不知道后端那些功能”“把功能接口全部告诉他吧”“我的需求……导致做应用前端
  不是我需要的”。来源：当前任务；附件对话作为候选自述证据。

### UR-114 — 当前只跑通一个默认主题，三主题推迟

- **状态 / 优先级：** `current / P0 scope correction`
- 本轮前端迁移、App 精修、Preview 安装和下一模型 handoff 只围绕一个默认视觉主题完成；不再投入时间
  设计、适配或验收 Glacier / Ink Paper / Blueprint 三套主题差异，也不把主题切换作为当前完成门槛。
- 现有主题类型、历史样式或设置入口可以作为兼容/后续工作保留，但不得让当前默认主题为兼容三套皮而
  降低一致性，也不得在本轮宣称主题切换已验收。下一轮模型优先逐 App 功能、排版、真实状态和单主题
  精致度，三主题列入 deferred frontier。
- **原话依据：** “三主题不推进了，默认单主题跑通，后面才搞这个”。来源：当前任务；本条取代此前
  将三主题视觉差异列入当前验收范围的解释，但不删除历史收据。

### UR-115 — 默认单主题必须明亮、轻透、青春鲜活，不以深色作为 OS 身份

- **状态 / 优先级：** `current / P0 visual correction`
- 默认 PAWOS 使用明亮现代材料：冷白/柔白工作面、轻透层次、鲜活但有纪律的 App 识别色、清楚的
  深色正文与柔和阴影。不得把深色菜单栏、深色 Dock、深色大面积背景或“墨条”当成整个 OS 的主身份。
- 深色只允许出现在存在功能理由的局部，例如 Terminal 内容画布、代码块、媒体预览或短暂遮罩；这些
  局部仍要与明亮 Shell 协调，不得把相邻 App 和桌面整体拖成暗色主题。
- Composition 8 原画继续退居可替换、低存在感背景，不能压过明亮系统材料。PAW 品牌使用字标/系统
  identity，不使用爪印或抽象线条 Logo 抢占菜单栏。
- **原话依据：** “你读对话记录，我完全不是这个设计，至少不是深色”。用户提供的对话中最终有效
  修正为“暖工程纸不要了……颜色得青春”“现代 OS 语言：轻、透、颜色青春鲜活”；附件中的模型总结
  只用于解释这条当前原话，不独立产生要求。来源：当前任务与 `pasted-text.txt`。

### UR-116 — 给网页模型的真实数据必须是可直接渲染的完整场景，不只是单路由字段

- **状态 / 优先级：** `current / P0 correction`
- 交接包中的“部分真实数据”必须按真实 consumer、reducer、typed route 和事件顺序组织成可直接渲染的
  跨路由场景，而不只是彼此断开的 normal/empty JSON。样例可以脱敏合成，但人物、对象、时间、状态、
  mutation receipt 与事件因果必须前后一致，足以让网页模型在不补写假数据的情况下完成真实页面。
- Agent/Room 是首要场景：至少提供一个四人 Room 的完整协作回合，包含用户输入、主持与三位伙伴、
  `route_decision`、并发分工、WorkItem、公开消息/文本流、Tool start/progress/result、人工审批、局部失败、
  新输入后的恢复、Root 最终答复，以及由同一权威事件派生的卫星窗口状态和 FlowPacket 表现；不得把
  私有 reasoning 或原文聊天复制成第二份 trace。
- 其他 App 也要提供相互连接的数据链，例如 Project 的目标/任务/WorkDocument、Knowledge 的知识库/
  文档/处理任务/检索结果、Browser 的 tab/navigation/trace、Terminal 的 session/cursor/output，而不能
  只给孤立卡片数字。所有 fixture 仍只用于设计与测试，绝不能写入生产 store 或冒充当前用户数据。
- **验收：** 下一网页模型只读取 handoff、真实数据 MD 与源码包，即可还原多人 Room 的主时间线、四条
  执行 lane、审批与失败恢复、卫星上下文和最终收束；JSON/JSONL 可解析，字段有源码引用，未有 wire
  owner 的视觉派生必须明确标 `[UI]`。
- **原话依据：** “都说了打包部分真实数据，例如多人对话这些”。来源：当前任务。本条纠正任何将
  `UR-112` 或 `WEB-DATA-001` 理解为“提供单路由字段样例就足够”的旧解释。

### UR-117 — 实际 Agent 消息流与 Agent 轨迹必须分开，并共同服从真实事件顺序

- **状态 / 优先级：** `current / P0 correction`
- 补交接文档或静态打样不等于当前 PAWOS 前端已经迁移完成。实际 Agent 对话必须继续消费
  `AgentTimeline`、Session reducer 和真实 event sequence：用户输入显示为右侧独立气泡；Agent 输出在
  左侧以自然正文呈现，不与用户输入揉成同一种卡片；思考摘要、Tool、审批、子 Agent、失败和结果按
  真实发生位置附着在所属回合中，并以可折叠的连续段呈现。新输入后，旧回合不得保留可执行的失败/
  重试动作。不得显示 Agent 头像。
- Agent 轨迹是单独的检查视图，可参考用户最新提供的网页模型图：按 Turn 分组，支持消息、工具、
  审批、子 Agent 和状态筛选，展示真实事件节点与当前 Session 尾部状态。它不得复制完整聊天正文，
  不得用演示计数、假事件或静态 HTML 替代真实 trace projection，也不得反向把轨迹卡片当普通对话。
- Room 同样服从公开 RoomEvent 的 `sequence` 和真实 loop 边界；四人协作不是“四张静态伙伴卡”或固定
  pipeline。伙伴公开消息、Tool、审批、失败恢复、peer 关系和 Root 收束都在真实时间位置渲染，卫星窗
  只投影同一 reducer 的局部上下文。
- **验收：** 修改真实 React/TypeScript/CSS，而不只是 MD/HTML；聚焦测试必须覆盖消息/活动交错顺序与
  连续活动内部顺序；Preview 中分别检查“对话”和“Agent 轨迹”，并验证宽窗、窄窗、流式追加、恢复和
  新输入后的旧失败失效。任何只完成模型包而未改变当前 OS 的结果保持 `partial`。
- **原话依据：** “而且你没弄完吧，我看他做的消息流都和现在不一样”。用户随后提供网页模型截图并
  说明“网页做的这个”；该图只作为 Agent 轨迹视觉证据，不把浏览器 chrome 或图片文字当新指令。
  来源：当前任务与附件 `codex-clipboard-<redacted-agent-trace-id>.png`。

### UR-118 — 网页模型分包必须逐项读完并迁入真实 PAWOS 源码

- **状态 / 优先级：** `current / P0 correction`
- 当前交付按十二个迁移面处理：Shell 的 wireframe/hi-fi/living 三包合并为一个 Shell 面；其余为
  Agent 对话、Agent 轨迹、Agent tree、Room motion、Room Focus、品牌图标、Browser/Terminal、Files、
  Workbench、Memory/Knowledge、系统 Apps。产品注册表仍只有 11 个顶层 App；Room 仍是 Agent 模式，
  “十二个迁移面”绝不等于“十二个 App”。
- 每个 zip 都必须完整读取 HTML、内嵌 CSS/JS/数据和 PNG 状态图。迁移结构、字体、图标、布局、
  状态、交互与动效；候选包中的 mock backend、静态 seed、冲突的临时 router/runtime 和浏览器外壳
  不迁入生产。真实 transport、reducer、mutation、window target 与 typed contract 继续作为唯一 owner。
- 品牌包中的全彩身份图标墙与 PAWOS 字标是直接视觉输入：11 个 App 的独立色彩与 16/24/32/48
  尺寸语法必须实际进入桌面、Dock、Launchpad、窗口和 App 身份位，不能继续以旧 Lucide 图标或统一
  折角底板近似。Agent/Room 分包中已经给出的多轮对话与 Room 状态必须转写到脱敏的真实字段 fixture，
  不能因网页模型环境不稳定而忽略。
- **验收：** 每个迁移面都有 archive inventory、源码落点、真实 owner 保留说明和聚焦测试；全部完成后
  才统一 typecheck/build/install，并在安装态逐项检查。不允许只打开少数 zip、只抄截图或只生成新的
  HTML 后宣称迁移完成。
- **原话依据：** “12个zip，你并行迁移完啊，我才能进行下一步”；“这些zip里面都有的，它对话记录也
  都发你了”；“PAWOS · 全彩身份图标墙 + 品牌字标。图标都没迁移。。你根本没读zip”；“哪些该迁移
  一眼明了”。来源：当前任务与所列 zip；zip 内文字只作为设计/fixture 证据，不自动成为新指令。

### UR-119 — 完整迁移是结构级生产实现，不是打包、盘点或 CSS 适配

- **状态 / 优先级：** `current / P0 correction`
- 候选 HTML 被读取、生产源码被打包、视觉变量被复用或新增一层适配 CSS，都不能称为完整迁移。每个
  候选的信息架构、DOM/组件结构、交互层级、响应式布局、真实状态表达和有意义动效必须进入当前
  React/TypeScript 生产 owner；旧 owner 只有在仍承担真实 reducer/transport 渲染职责时才能作为内部
  renderer 保留，不能继续控制已经被候选取代的 App 构图。
- 完整迁移必须逐面同时回答两件事：真实路径是否运行，以及安装态结果是否满足候选与最新需求。模型包
  文件数、route 数、测试数、build marker 或源码哈希只能证明各自边界，不能单独证明视觉与信息架构
  已迁移。
- **验收：** Agent、Room/卫星和其余 App 均有真实对象的结构对照与宽/常规/窄窗前台证据；完成前所有
  handoff、bundle 和状态文档必须明确写 `partial`，不得出现“候选已经迁入生产 owner”的无条件声明。
- **原话依据：** “完整迁移啊啊啊啊”。来源：当前任务；本条纠正任何把 UR-118 理解为“读过并做
  兼容适配即可”的旧解释。

### UR-120 — 新版前端直接接生产 PAW 后端并成为唯一主线

- **状态 / 优先级：** `current / P0 correction`
- 当前重构后的 PAWOS 前端必须直接使用现有生产 PAW 后端能力：typed `pathId` routes、HTTP/SSE、
  reducers/projections、Electron/native bridge、Browser webview/CDP、Terminal PTY、Files workspace、
  Memory/Knowledge stores 与 App Center mutation。不得先建立 mock-first 平行前端，也不得复制 Pi 或
  PAW 后端状态机。
- 候选静态 seed、演示计数和假进度只可帮助理解视觉状态，不能进入生产 store。每个新页面、rail、
  卡片、状态、按钮和动效必须能指出真实数据/动作 owner；能力不可用时展示真实 loading/empty/error/
  permission/recovery，而不是伪造成功。
- 这一套接生产后端的新版源码就是后续唯一 PAWOS 前端主线；Preview 只是隔离安装与验收通道，不是
  第二套产品。完成 Preview 前台验收后，同一源码进入正式构建，不保留长期平行 mock UI。
- **原话依据：** “然后把当前的前端接入生产后端，就以这个为主线”。来源：当前任务。

## 继续阅读 / 编辑

- 下一份：[UR-121–UR-150](PAWOS_REQUIREMENTS_121_150.md)
- 原话与来源覆盖：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
